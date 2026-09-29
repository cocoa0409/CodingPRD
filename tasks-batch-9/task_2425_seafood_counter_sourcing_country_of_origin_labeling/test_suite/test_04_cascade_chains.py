"""The substitution and cold-chain cascades, hop by hop, and the lot's parallel dimensions."""
from test_helpers import fixtures, validate_success
from test_helpers.assertions import (
    assert_case_label,
    assert_cents,
    assert_cold_chain_excursion,
    assert_instant,
    assert_risk_index,
    assert_temperature,
    assert_weight,
)
from test_helpers.factories import ice_bed_reading_payload
from test_helpers.test_users import make_seafood_manager_headers


def _substitution_cascade(api) -> dict:
    """A labelled 10.000 kg tilapia lot whose laboratory result comes back as cod."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    tilapia = fixtures.register_tilapia(api)
    lot = fixtures.receive_tilapia_lot(api, counter_id, env["supplier"]["id"], tilapia["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    label = fixtures.publish_case_label(api, counter_id, lot["id"])
    sample = fixtures.draw_sample(api, lot["id"])
    fixtures.send_sample_to_lab(api, sample["id"], "LAB-B-0001")
    fixtures.record_sample_result(api, sample["id"], env["cod"]["id"])
    env.update({"tilapia": tilapia, "lot": lot, "label": label, "sample": sample})
    return env


def _cold_chain_cascade(api) -> dict:
    """A labelled and advertised cod lot in slot 3, then one 6.2 degree probe reading."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(api, counter_id, env["supplier"]["id"], env["cod"]["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 3)
    label = fixtures.publish_case_label(api, counter_id, lot["id"])
    item = fixtures.published_ad_item(api, counter_id, lot["id"])

    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    response = api.create_ice_bed_reading(
        ice_bed_reading_payload(counter_id, 3, "2026-08-01T13:00:00Z", 6.2),
        make_seafood_manager_headers(counter_id),
    )
    reading = validate_success(response, expected_status=201)
    env.update({"lot": lot, "label": label, "ad_item": item, "reading": reading})
    return env


def test_01_a_mismatch_withdraws_the_label_and_writes_the_destruction_event(api):
    """PRD §2.10: "The substitution cascade begins when a laboratory result contradicts the
    declared species. Recording that result drives the sample to `MISMATCH` and the lot's
    `label_status` to `MISMATCHED`; the transition into `MISMATCHED` raises a
    `SPECIES_SUBSTITUTION` compliance violation worth 6 points and withdraws every
    `PUBLISHED` case label for that lot with a `withdraw_reason` of `SPECIES_MISMATCH`;
    withdrawing a published label for that particular reason creates a `ShrinkEvent` for the
    lot with a `reason` of `MISLABEL_DESTRUCTION`; creating a `MISLABEL_DESTRUCTION` shrink
    event drives the lot's `chargeback_status` from `NONE` to `ASSESSED`; and the assessment
    increases the dealer's `chargeback_assessed_total_cents` and
    `chargeback_outstanding_cents` and recomputes the dealer's `status`."

    Design: Difficulty/transitive_cascade/mismatch_cascade_depth_five_lot_label_shrink_chargeback_supplier
    """
    env = _substitution_cascade(api)
    counter_id = env["counter"]["id"]

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["label_status"] == "MISMATCHED"
    assert lot["intake_status"] == "CASED"
    assert_weight(lot["remaining_weight_kg"], 10.000)

    label = fixtures.read_case_label(api, counter_id, env["label"]["id"])
    assert_case_label(label)
    assert label["status"] == "WITHDRAWN"
    assert label["withdraw_reason"] == "SPECIES_MISMATCH"

    event = fixtures.only_shrink_event(api, counter_id, env["lot"]["id"])
    assert event["reason"] == "MISLABEL_DESTRUCTION"
    assert event["status"] == "VALUED"
    assert_weight(event["shrink_weight_kg"], 10.000)
    assert_cents(event["provisional_value_cents"], 18450)


def test_02_the_cascade_tail_reaches_the_dealer_ledger_and_the_counter_posture(api):
    """PRD §3.8: "When `observed_species_id` differs from the lot's `species_id`, the sample
    reaches `MISMATCH` and the substitution cascade of §2.10 fires: the dealer's
    `lifetime_sample_count` and `lifetime_mismatch_count` each increase by one with both risk
    index variants recomputed, the lot's `label_status` becomes `MISMATCHED`, a
    `ComplianceViolation` with `category` `SPECIES_SUBSTITUTION` and `points` 6 is raised,
    every `PUBLISHED` case label for the lot is withdrawn with `withdraw_reason`
    `SPECIES_MISMATCH`, that withdrawal creates the `MISLABEL_DESTRUCTION` shrink event, and
    the shrink event's creation drives the lot's `chargeback_status` from `NONE` to
    `ASSESSED`."

    Design: Difficulty/transitive_cascade/mismatch_cascade_depth_five_lot_label_shrink_chargeback_supplier
    """
    env = _substitution_cascade(api)
    counter_id = env["counter"]["id"]

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["chargeback_status"] == "ASSESSED"
    assert_cents(lot["chargeback_assessed_cents"], 47840)

    supplier = fixtures.read_supplier(api, env["supplier"]["id"])
    assert_cents(supplier["chargeback_assessed_total_cents"], 47840)
    assert_cents(supplier["chargeback_outstanding_cents"], 47840)
    assert_risk_index(supplier["substitution_risk_index_lifetime"], 100.00)
    assert supplier["status"] == "GOOD_STANDING"

    violation = fixtures.only_violation(api, counter_id, {"lot_id": env["lot"]["id"]})
    assert violation["category"] == "SPECIES_SUBSTITUTION"
    assert violation["points"] == 6
    counter = fixtures.read_counter(api, counter_id)
    assert counter["violation_points"] == 6
    assert counter["posture"] == "RESTRICTED"


def test_03_a_breaching_reading_holds_the_lot_pulls_the_label_and_retracts_the_ad(api):
    """PRD §2.10: "The cold-chain cascade begins when a probe reading exceeds the ice-bed
    limit. The breaching reading opens (or extends) the slot's excursion; a newly opened
    excursion holds every lot currently `CASED` in that slot, moving each to `HELD`; each
    newly held lot has every `PUBLISHED` case label withdrawn with a `withdraw_reason` of
    `COLD_CHAIN_HOLD`; and each such label withdrawal retracts every `PUBLISHED`
    advertisement pointing at that lot, setting `retract_reason` to `LABEL_WITHDRAWN` and
    raising a `COOL_MISSING` compliance violation worth 4 points."

    Design: Difficulty/transitive_cascade/cold_chain_cascade_depth_four_hold_label_ad_violation
    """
    env = _cold_chain_cascade(api)
    counter_id = env["counter"]["id"]

    assert env["reading"]["breach"] is True

    excursions = fixtures.list_excursions(api, counter_id, {"case_slot": 3})
    assert len(excursions) == 1, f"expected exactly one excursion, got {len(excursions)}"
    excursion = excursions[0]
    assert_cold_chain_excursion(excursion)
    assert excursion["status"] == "OPEN"
    assert excursion["case_slot"] == 3
    assert_instant(excursion["started_at"], "2026-08-01T13:00:00Z")
    assert_instant(excursion["ended_at"], "2026-08-01T13:00:00Z")
    assert excursion["exposure_minutes"] == 0
    assert_temperature(excursion["peak_temperature_c"], 6.2)
    assert excursion["severity"] == "MINOR"

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["intake_status"] == "HELD"

    label = fixtures.read_case_label(api, counter_id, env["label"]["id"])
    assert label["status"] == "WITHDRAWN"
    assert label["withdraw_reason"] == "COLD_CHAIN_HOLD"

    item = fixtures.read_ad_item(api, env["ad_item"]["id"])
    assert item["status"] == "RETRACTED"
    assert item["retract_reason"] == "LABEL_WITHDRAWN"

    violation = fixtures.only_violation(api, counter_id, {"lot_id": env["lot"]["id"]})
    assert violation["category"] == "COOL_MISSING"
    assert violation["points"] == 4


def test_04_a_cold_chain_withdrawal_writes_no_destruction_event(api):
    """PRD §2.10: "First, the conditional hop is genuinely conditional: the
    `MISLABEL_DESTRUCTION` shrink event fires only for a withdrawal whose `withdraw_reason`
    is `SPECIES_MISMATCH`, and never for a withdrawal reasoned `MANUAL`, `SUPERSEDED`,
    `COLD_CHAIN_HOLD` or `CLAIM_REVOKED`."

    Design: Difficulty/transitive_cascade/cold_chain_cascade_depth_four_hold_label_ad_violation
    """
    env = _cold_chain_cascade(api)
    counter_id = env["counter"]["id"]

    events = fixtures.list_shrink_events(api, counter_id, {"lot_id": env["lot"]["id"]})
    assert events == [], f"a cold-chain withdrawal must write no shrink event, got {events}"

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert_weight(lot["remaining_weight_kg"], 20.000)
    counter = fixtures.read_counter(api, counter_id)
    assert counter["open_excursion_count"] == 1
    assert counter["violation_points"] == 4
    assert counter["posture"] == "RESTRICTED"


def test_05_custody_verification_and_recovery_settle_in_three_different_states(api):
    """PRD §3.1: "Those three dimensions move independently for the rest of the lot's life:
    physical custody, label verification, and dealer recovery."

    Design: Difficulty/non_linear_state_machine/supplier_lot_three_parallel_dimensions_independent
    """
    env = _substitution_cascade(api)
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]

    fixtures.relabel_lot(api, counter_id, env["lot"]["id"], env["cod"]["id"], "Cod")
    fixtures.settle_chargeback(api, supplier_id, env["lot"]["id"], 47840)

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["intake_status"] == "CASED"
    assert lot["label_status"] == "RELABELED"
    assert lot["chargeback_status"] == "SETTLED"

    supplier = fixtures.read_supplier(api, supplier_id)
    assert_cents(supplier["chargeback_outstanding_cents"], 0)
    assert_cents(supplier["chargeback_settled_cents"], 47840)


def test_06_relabelling_replaces_the_species_but_leaves_the_finding_open(api):
    """PRD §3.8: "On success the lot's `species_id` is replaced by `corrected_species_id`,
    the `label_status` moves from `MISMATCHED` to `RELABELED`, and disputed samples are
    voided. Any `ComplianceViolation` for that lot with `category` `SPECIES_SUBSTITUTION` and
    `status` `OPEN` deliberately stays `OPEN` — curing a finding is a separate compliance act,
    not a by-product of fixing the sign."

    Design: Difficulty/non_linear_state_machine/supplier_lot_three_parallel_dimensions_independent
    """
    env = _substitution_cascade(api)
    counter_id = env["counter"]["id"]

    relabelled = fixtures.relabel_lot(
        api, counter_id, env["lot"]["id"], env["cod"]["id"], "Cod"
    )

    assert relabelled["species_id"] == env["cod"]["id"]
    assert relabelled["label_status"] == "RELABELED"

    violation = fixtures.only_violation(api, counter_id, {"lot_id": env["lot"]["id"]})
    assert violation["status"] == "OPEN"
    counter = fixtures.read_counter(api, counter_id)
    assert counter["posture"] == "RESTRICTED"
