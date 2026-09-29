"""The ice-bed limit boundary and the safety check that precedes claim substantiation."""
from test_helpers import ApiErrorId, fixtures, validate_error, validate_success
from test_helpers.assertions import (
    assert_cold_chain_excursion,
    assert_instant,
    assert_ice_bed_reading,
    assert_temperature,
    assert_weight,
)
from test_helpers.factories import case_label_payload, ice_bed_reading_payload
from test_helpers.test_users import make_seafood_manager_headers


def _cased_cod_lot_with_clock_at_two_pm(api) -> dict:
    """A 20.000 kg cod lot in slot 1 with the logical clock advanced past the probe times."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(api, counter_id, env["supplier"]["id"], env["cod"]["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    env["lot"] = lot
    return env


def _submit_reading(api, counter_id: str, case_slot: int, reading_at: str, temperature_c: float):
    response = api.create_ice_bed_reading(
        ice_bed_reading_payload(counter_id, case_slot, reading_at, temperature_c),
        make_seafood_manager_headers(counter_id),
    )
    return validate_success(response, expected_status=201)


def test_01_a_reading_of_exactly_the_ice_bed_limit_is_compliant(api):
    """PRD §3.7: "Each stored reading carries a computed `breach` flag, true exactly when its
    `temperature_c` is **strictly greater** than the ice-bed limit of 4.4 degrees Celsius; a
    reading of exactly 4.4 is compliant and its `breach` is false."

    Design: Difficulty/boundary_precision_check/ice_bed_reading_exactly_at_limit_is_compliant
    """
    env = _cased_cod_lot_with_clock_at_two_pm(api)
    counter_id = env["counter"]["id"]

    reading = _submit_reading(api, counter_id, 1, "2026-08-01T13:00:00Z", 4.4)

    assert_ice_bed_reading(reading)
    assert reading["breach"] is False
    assert_temperature(reading["temperature_c"], 4.4)
    assert fixtures.list_excursions(api, counter_id, {"case_slot": 1}) == []
    assert fixtures.read_lot(api, counter_id, env["lot"]["id"])["intake_status"] == "CASED"


def test_02_one_tenth_of_a_degree_above_the_limit_opens_the_excursion(api):
    """PRD §3.7: "Its `started_at` is the earliest `reading_at` in the breach set and its
    `ended_at` the latest; its `exposure_minutes` is the elapsed time between those two
    instants expressed in whole minutes, rounded half up; and its `peak_temperature_c` is the
    highest `temperature_c` in the breach set."

    Design: Difficulty/boundary_precision_check/ice_bed_reading_exactly_at_limit_is_compliant
    """
    env = _cased_cod_lot_with_clock_at_two_pm(api)
    counter_id = env["counter"]["id"]
    _submit_reading(api, counter_id, 1, "2026-08-01T13:00:00Z", 4.4)

    breaching = _submit_reading(api, counter_id, 1, "2026-08-01T13:30:00Z", 4.5)

    assert breaching["breach"] is True
    excursions = fixtures.list_excursions(api, counter_id, {"case_slot": 1})
    assert len(excursions) == 1, f"expected exactly one excursion, got {len(excursions)}"
    excursion = excursions[0]
    assert_cold_chain_excursion(excursion)
    assert excursion["status"] == "OPEN"
    assert_instant(excursion["started_at"], "2026-08-01T13:30:00Z")
    assert_instant(excursion["ended_at"], "2026-08-01T13:30:00Z")
    assert excursion["exposure_minutes"] == 0
    assert_temperature(excursion["peak_temperature_c"], 4.5)
    assert excursion["severity"] == "MINOR"


def test_03_the_newly_opened_excursion_holds_the_lot_without_touching_its_weight(api):
    """PRD §3.7: "A newly opened excursion is what puts product on hold. Every lot on that
    counter whose `case_slot` equals the excursion's `case_slot` and whose `intake_status` is
    `CASED` moves to `HELD`, which holds it out of sale while leaving its
    `remaining_weight_kg` untouched, and each newly held lot has all of its `PUBLISHED` case
    labels withdrawn with `withdraw_reason` `COLD_CHAIN_HOLD`, which in turn retracts the
    dependent published advertisements as described in §3.6."

    Design: Difficulty/boundary_precision_check/ice_bed_reading_exactly_at_limit_is_compliant
    """
    env = _cased_cod_lot_with_clock_at_two_pm(api)
    counter_id = env["counter"]["id"]
    _submit_reading(api, counter_id, 1, "2026-08-01T13:00:00Z", 4.4)
    _submit_reading(api, counter_id, 1, "2026-08-01T13:30:00Z", 4.5)

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["intake_status"] == "HELD"
    assert_weight(lot["remaining_weight_kg"], 20.000)


def test_04_an_open_excursion_blocks_publication_before_the_claim_is_examined(api):
    """PRD §3.4: "Publication is refused while the counter has any excursion whose `status`
    is `OPEN`, with `ERR_OPEN_EXCURSION_BLOCKS` — a label may not go up over a case whose
    temperature history is unresolved."

    Design: Difficulty/priority_pair_validation_conflict/case_label_publish_safety_beats_referential_certification
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(api, counter_id, env["supplier"]["id"], env["cod"]["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    certification = fixtures.file_certification(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"]
    )
    fixtures.review_certification(api, certification["id"], "REJECT")
    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    _submit_reading(api, counter_id, 2, "2026-08-01T13:00:00Z", 6.0)

    payload = case_label_payload(lot["id"], fixtures.lot_version(api, counter_id, lot["id"]))
    payload["certification_id"] = certification["id"]
    response = api.create_case_label(payload, make_seafood_manager_headers(counter_id))

    error = validate_error(
        response, ApiErrorId.ERR_OPEN_EXCURSION_BLOCKS.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED.value


def test_05_the_blocked_publication_writes_no_label_and_leaves_the_certificate_revoked(api):
    """PRD §3.5: "A `decision` of `REJECT` moves the certificate from `PENDING_REVIEW`
    straight to `REVOKED` and records the submitted `review_note`."

    Design: Difficulty/priority_pair_validation_conflict/case_label_publish_safety_beats_referential_certification
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    lot = fixtures.receive_lot(api, counter_id, supplier_id, env["cod"]["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    certification = fixtures.file_certification(api, counter_id, supplier_id, env["cod"]["id"])
    fixtures.review_certification(api, certification["id"], "REJECT")
    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    _submit_reading(api, counter_id, 2, "2026-08-01T13:00:00Z", 6.0)

    payload = case_label_payload(lot["id"], fixtures.lot_version(api, counter_id, lot["id"]))
    payload["certification_id"] = certification["id"]
    response = api.create_case_label(payload, make_seafood_manager_headers(counter_id))
    validate_error(response, ApiErrorId.ERR_OPEN_EXCURSION_BLOCKS.value, expected_status=409)

    assert fixtures.list_case_labels(api, counter_id, {"lot_id": lot["id"]}) == []
    assert fixtures.read_lot(api, counter_id, lot["id"])["intake_status"] == "CASED"
    assert fixtures.read_certification(api, supplier_id, certification["id"])["status"] == "REVOKED"
    counter = fixtures.read_counter(api, counter_id)
    assert counter["open_excursion_count"] == 1
    assert counter["posture"] == "RESTRICTED"
