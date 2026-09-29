"""Dealer risk indices, the sampling plan short-circuit and the bounded retest loop."""
from test_helpers import ApiErrorId, fixtures, validate_error, validate_success
from test_helpers.assertions import (
    assert_counter,
    assert_risk_index,
    assert_verification_sample,
)
from test_helpers.test_users import (
    make_compliance_officer_headers,
    make_supplier_rep_headers,
)


def _one_match_and_one_mismatch(api) -> dict:
    """Two lots on one counter for one dealer: a cod lot that matches, a tilapia lot that does not."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    tilapia = fixtures.register_tilapia(api)

    lot_a = fixtures.receive_lot(
        api, counter_id, supplier_id, env["cod"]["id"], received_weight_kg=12.000
    )
    fixtures.case_lot(api, counter_id, lot_a["id"], 1)
    fixtures.sample_with_result(api, lot_a["id"], env["cod"]["id"], lab_reference="LAB-A-0001")

    lot_b = fixtures.receive_tilapia_lot(
        api,
        counter_id,
        supplier_id,
        tilapia["id"],
        received_weight_kg=10.000,
        unit_cost_cents_per_kg=900,
        retail_price_cents_per_kg=1600,
        cooked_retail_price_cents_per_kg=1800,
    )
    fixtures.case_lot(api, counter_id, lot_b["id"], 2)
    fixtures.sample_with_result(api, lot_b["id"], env["cod"]["id"], lab_reference="LAB-B-0001")

    counter = fixtures.read_counter(api, counter_id)
    fixtures.close_verification_cycle(api, counter_id, counter["version"])
    env["tilapia"] = tilapia
    env["lot_a"] = lot_a
    env["lot_b"] = lot_b
    return env


def _disputed_tilapia_sample(api) -> dict:
    """A tilapia lot driven around the dispute-and-retest loop until the bound is reached."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    tilapia = fixtures.register_tilapia(api)
    lot = fixtures.receive_tilapia_lot(api, counter_id, supplier_id, tilapia["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)

    sample = fixtures.draw_sample(api, lot["id"])
    fixtures.send_sample_to_lab(api, sample["id"], "LAB-B-0001")
    fixtures.record_sample_result(api, sample["id"], env["cod"]["id"])
    for lab_reference in ("LAB-B-0002", "LAB-B-0003"):
        fixtures.dispute_sample(api, supplier_id, sample["id"], "dealer contests the identification")
        fixtures.send_sample_to_lab(api, sample["id"], lab_reference)
        fixtures.record_sample_result(api, sample["id"], env["cod"]["id"])

    env["tilapia"] = tilapia
    env["lot"] = lot
    env["sample"] = sample
    return env


def test_01_rolling_index_decays_a_mismatch_while_the_lifetime_index_does_not(api):
    """PRD §3.8: "Walking that set in `created_at` ascending order, each mismatch
    contributes a base weight of 40 points halved once for every complete verification cycle
    that has elapsed since it was drawn — the elapsed count being the current
    `verification_cycle_index` of the counter owning that sample's lot minus the sample's own
    `cycle_index`, which is never negative. A mismatch drawn in the current cycle therefore
    contributes its full 40, one cycle later 20, two cycles later 10, and three cycles later
    5."

    Design: Difficulty/dual_variant_calc/supplier_risk_index_rolling_vs_lifetime_diverge
    """
    env = _one_match_and_one_mismatch(api)

    supplier = fixtures.read_supplier(api, env["supplier"]["id"])
    assert_risk_index(supplier["substitution_risk_index_rolling"], 20.00)
    assert_risk_index(supplier["substitution_risk_index_lifetime"], 50.00)
    assert float(supplier["substitution_risk_index_rolling"]) != float(
        supplier["substitution_risk_index_lifetime"]
    ), "the decayed rolling variant must not collapse onto the lifetime variant"


def test_02_dealer_standing_is_derived_from_the_lifetime_variant_alone(api):
    """PRD §3.8: "If `lifetime_sample_count` is at least 2 and
    `substitution_risk_index_lifetime` is at least 60.00, the dealer's `status` becomes
    `SUSPENDED`; otherwise, if `lifetime_sample_count` is at least 2 and
    `substitution_risk_index_lifetime` is at least 25.00, the `status` becomes `PROBATION`;
    otherwise it is `GOOD_STANDING`."

    Design: Difficulty/dual_variant_calc/supplier_risk_index_rolling_vs_lifetime_diverge
    """
    env = _one_match_and_one_mismatch(api)

    supplier = fixtures.read_supplier(api, env["supplier"]["id"])
    assert supplier["lifetime_sample_count"] == 2
    assert supplier["lifetime_mismatch_count"] == 1
    assert_risk_index(supplier["substitution_risk_index_lifetime"], 50.00)
    assert supplier["status"] == "PROBATION"
    counter = fixtures.read_counter(api, env["counter"]["id"])
    assert counter["verification_cycle_index"] == 1


def test_03_an_empty_candidate_set_short_circuits_the_sampling_plan(api):
    """PRD §3.8: "If that set is empty, the plan short-circuits:
    `last_cycle_max_supplier_risk_index` is written as 0.00 and `last_cycle_required_samples`
    as 0 — not the base sample count — and step one stops."

    Design: Difficulty/boundary_precision_check/empty_candidate_set_yields_zero_required_samples
    """
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    counter = fixtures.register_counter(api)

    closed = fixtures.close_verification_cycle(api, counter["id"], counter["version"])

    assert closed["last_cycle_required_samples"] == 0
    assert closed["last_cycle_required_samples"] != 1, (
        "the base sample count must not be written when there is no candidate lot"
    )
    assert_risk_index(closed["last_cycle_max_supplier_risk_index"], 0.00)


def test_04_closing_the_cycle_advances_the_cycle_index(api):
    """PRD §3.8: "**Step two** increments the counter's `verification_cycle_index` by one."

    Design: Difficulty/boundary_precision_check/empty_candidate_set_yields_zero_required_samples
    """
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    counter = fixtures.register_counter(api)
    assert counter["verification_cycle_index"] == 0

    response = api.close_verification_cycle(
        counter["id"],
        {"expected_counter_version": counter["version"]},
        make_compliance_officer_headers(),
    )
    closed = validate_success(response, expected_status=200)

    assert_counter(closed)
    assert closed["verification_cycle_index"] == 1
    assert closed["posture"] == "OPEN"


def test_05_a_third_dispute_is_refused_once_two_retests_are_on_record(api):
    """PRD §3.8: "Both the dispute transition and the retest transition require
    `retest_count` to be strictly below 2, so the loop `IN_LAB` → `MISMATCH` → `DISPUTED` →
    `IN_LAB` is bounded at two retests; a third attempt is rejected with
    `ERR_RETEST_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/verification_sample_dispute_retest_cycle_bounded
    """
    env = _disputed_tilapia_sample(api)

    response = api.dispute_sample(
        env["sample"]["id"],
        {"dispute_reason": "dealer demands a third retest"},
        make_supplier_rep_headers(env["supplier"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RETEST_LIMIT_REACHED.value, expected_status=409)

    sample = fixtures.read_sample(api, env["sample"]["id"])
    assert_verification_sample(sample)
    assert sample["status"] == "MISMATCH"
    assert sample["retest_count"] == 2


def test_06_repeat_mismatch_results_advance_the_sample_and_nothing_else(api):
    """PRD §2.10: "Second, forward edges are idempotent at their source dimension: because
    the substitution cascade hangs off the lot's entry into `MISMATCHED`, a second mismatch
    result on a lot whose `label_status` is already `MISMATCHED` — the retest case — advances
    the sample alone. No second violation, no second label withdrawal, no second shrink event
    and no second chargeback are produced, and the dealer's `lifetime_sample_count` and
    `lifetime_mismatch_count` are counted once per sample rather than once per result."

    Design: Difficulty/non_linear_state_machine/verification_sample_dispute_retest_cycle_bounded
    """
    env = _disputed_tilapia_sample(api)
    counter_id = env["counter"]["id"]

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["label_status"] == "MISMATCHED"
    violation = fixtures.only_violation(
        api, counter_id, {"lot_id": env["lot"]["id"], "category": "SPECIES_SUBSTITUTION"}
    )
    assert violation["category"] == "SPECIES_SUBSTITUTION"
    supplier = fixtures.read_supplier(api, env["supplier"]["id"])
    assert supplier["lifetime_sample_count"] == 1
    assert supplier["lifetime_mismatch_count"] == 1
