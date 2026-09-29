"""Posture escalating on a count, the two optimistic-concurrency guards, and immediate re-derivation."""
from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_compliance_violation, assert_instant
from test_helpers.factories import case_label_payload
from test_helpers.test_users import (
    OFFICER_READ_USER_ID,
    OFFICER_SAMPLING_USER_ID,
    make_compliance_officer_headers,
    make_seafood_manager_headers,
)


def _two_breaches_on_empty_slots_three_and_four(api) -> dict:
    """A cased cod lot untouched by two excursions raised on the counter's empty slots."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    fixtures.submit_reading(api, counter_id, 3, "2026-08-01T13:00:00Z", 4.9)
    after_one = fixtures.read_counter(api, counter_id)
    fixtures.submit_reading(api, counter_id, 4, "2026-08-01T13:30:00Z", 5.2)
    env.update({"lot": lot, "after_one": after_one})
    return env


def _cased_lot_with_both_parent_versions_captured(api) -> dict:
    """A cased cod lot whose lot version and counter version were both read before any write."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    env.update(
        {
            "lot": lot,
            "lot_version": fixtures.lot_version(api, counter_id, lot["id"]),
            "counter_version": fixtures.read_counter(api, counter_id)["version"],
        }
    )
    return env


def _six_point_substitution_finding(api) -> dict:
    """A mislabelled cod lot whose cascade left one OPEN SPECIES_SUBSTITUTION finding."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    pacific = fixtures.register_species(api, factories.pacific_cod_payload())
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.publish_case_label(api, counter_id, lot["id"])
    fixtures.sample_with_result(api, lot["id"], pacific["id"], lab_reference="LAB-2026-0801-4")
    violation = fixtures.only_violation(
        api, counter_id, {"counter_id": counter_id, "category": "SPECIES_SUBSTITUTION"}
    )
    env.update({"lot": lot, "pacific": pacific, "violation": violation})
    return env


def test_01_the_second_open_excursion_suspends_the_counter_and_stops_sampling(api):
    """PRD §2.6: "Posture then follows from those two aggregates, evaluated in this order. If
    `open_excursion_count` is at least 2, or `violation_points` is at least 12, the posture is
    `SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/second_open_excursion_suspends_the_counter_and_blocks_sampling
    """
    env = _two_breaches_on_empty_slots_three_and_four(api)
    counter_id = env["counter"]["id"]

    assert env["after_one"]["open_excursion_count"] == 1
    assert env["after_one"]["posture"] == "RESTRICTED"

    suspended = fixtures.read_counter(api, counter_id)
    assert suspended["open_excursion_count"] == 2
    assert suspended["posture"] == "SUSPENDED"

    officer = make_compliance_officer_headers(OFFICER_SAMPLING_USER_ID)
    response = api.create_verification_sample(
        factories.verification_sample_payload(env["lot"]["id"]), officer
    )
    validate_error(response, ApiErrorId.ERR_COUNTER_SUSPENDED.value, expected_status=409)

    _, meta = validate_paginated(
        api.list_verification_samples(officer, params={"lot_id": env["lot"]["id"]})
    )
    assert meta["total_count"] == 0, "a suspended counter may not draw a sample"
    assert fixtures.read_lot(api, counter_id, env["lot"]["id"])["label_status"] == "UNVERIFIED"


def test_02_releasing_one_excursion_walks_the_posture_back_down_and_sampling_resumes(api):
    """PRD §2.6: "Because the derivation is a pure function of the current aggregates,
    remediation moves the posture back down the same ladder: a counter in `SUSPENDED` returns to
    `RESTRICTED` as soon as no suspension condition holds but a restriction condition still
    does"

    Design: Corner/cross_cutting_complexity_layers/second_open_excursion_suspends_the_counter_and_blocks_sampling
    """
    env = _two_breaches_on_empty_slots_three_and_four(api)
    counter_id = env["counter"]["id"]
    excursions = fixtures.list_excursions(api, counter_id, {"case_slot": 3})
    assert len(excursions) == 1, f"expected one excursion on slot 3, got {len(excursions)}"

    resolved = fixtures.resolve_excursion(
        api, excursions[0]["id"], "RELEASE", "empty slot, probe corrected"
    )
    assert resolved["status"] == "RESOLVED_RELEASED"

    counter = fixtures.read_counter(api, counter_id)
    assert counter["open_excursion_count"] == 1
    assert counter["posture"] == "RESTRICTED"

    sample = fixtures.draw_sample(api, env["lot"]["id"])
    assert sample["status"] == "DRAFT"

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["label_status"] == "SAMPLED"
    assert lot["intake_status"] == "CASED"


def test_03_a_lot_version_consumed_by_a_sale_no_longer_publishes_a_label(api):
    """PRD §2.8: "If `expected_lot_version` does not equal the lot's current `version`, the
    request is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_version_rejected_on_both_occ_write_endpoints
    """
    env = _cased_lot_with_both_parent_versions_captured(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]
    manager = make_seafood_manager_headers(counter_id)
    fixtures.record_sales(api, counter_id, lot_id, 1.000)

    stale = api.create_case_label(case_label_payload(lot_id, env["lot_version"]), manager)
    validate_error(stale, ApiErrorId.ERR_STALE_LOT_VERSION.value, expected_status=412)
    assert fixtures.list_case_labels(api, counter_id, {"lot_id": lot_id}) == []

    refreshed = fixtures.lot_version(api, counter_id, lot_id)
    assert refreshed > env["lot_version"], "recording sales must increment the lot version"

    label = validate_success(
        api.create_case_label(case_label_payload(lot_id, refreshed), manager), expected_status=201
    )
    assert label["status"] == "PUBLISHED"


def test_04_a_counter_version_consumed_by_one_cycle_close_cannot_close_the_next(api):
    """PRD §2.8: "If `expected_counter_version` does not equal the counter's current `version`,
    the request is rejected with `ERR_STALE_COUNTER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_version_rejected_on_both_occ_write_endpoints
    """
    env = _cased_lot_with_both_parent_versions_captured(api)
    counter_id = env["counter"]["id"]
    officer = make_compliance_officer_headers(OFFICER_SAMPLING_USER_ID)

    first = fixtures.close_verification_cycle(api, counter_id, env["counter_version"])
    assert first["verification_cycle_index"] == 1

    replay = api.close_verification_cycle(
        counter_id, {"expected_counter_version": env["counter_version"]}, officer
    )
    validate_error(replay, ApiErrorId.ERR_STALE_COUNTER_VERSION.value, expected_status=412)
    assert fixtures.read_counter(api, counter_id)["verification_cycle_index"] == 1

    refreshed = fixtures.read_counter(api, counter_id)["version"]
    assert refreshed > env["counter_version"], "a successful close must increment the version"

    second = fixtures.close_verification_cycle(api, counter_id, refreshed)
    assert second["verification_cycle_index"] == 2


def test_05_curing_halves_the_points_and_expunging_clears_them_in_the_same_response(api):
    """PRD §3.9: "A `SeafoodManager` cures an open finding by submitting a `cure_note`, which
    moves it from `OPEN` to `CURED`, stamps `cured_at` from the logical clock, and re-derives the
    counter's posture with that finding now contributing its weight halved and rounded up rather
    than in full."

    Design: Corner/consistency_model/posture_is_recomputed_immediately_on_cure_and_expunge
    """
    env = _six_point_substitution_finding(api)
    counter_id = env["counter"]["id"]
    violation = env["violation"]

    assert_compliance_violation(violation)
    assert violation["points"] == 6
    before = fixtures.read_counter(api, counter_id)
    assert before["violation_points"] == 6
    assert before["posture"] == "RESTRICTED"

    cured = fixtures.cure_violation(
        api, counter_id, violation["id"], "counter staff retrained and the case reset"
    )
    assert cured["status"] == "CURED"
    assert_instant(cured["cured_at"], "2026-08-01T08:00:00Z")
    after_cure = fixtures.read_counter(api, counter_id)
    assert after_cure["violation_points"] == 3
    assert after_cure["posture"] == "OPEN"

    expunged = fixtures.expunge_violation(
        api,
        violation["id"],
        "lab retest cleared the species identification",
        officer_id=OFFICER_READ_USER_ID,
    )
    assert expunged["status"] == "EXPUNGED"
    after_expunge = fixtures.read_counter(api, counter_id)
    assert after_expunge["violation_points"] == 0
    assert after_expunge["posture"] == "OPEN"

    assert fixtures.read_lot(api, counter_id, env["lot"]["id"])["chargeback_status"] == "ASSESSED"
