"""Appeal adjudication: the NEEDS_REMEASURE <-> UNDER_REVIEW cycle, invalid-state
transitions, the remeasure grounds precondition, and appeal/bill referential
integrity."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_measurement_payload, create_appeal_payload,
    create_active_parcel, setup_appeal_under_review, setup_appeal_needs_remeasure,
    setup_issued_bill,
)

ASSESSOR = TEST_USERS["assessor_headers"]
STORMWATER_ADMIN = TEST_USERS["stormwater_admin_headers"]


def _parcel_version(api, parcel_id):
    return validate_success(api.get_parcel(parcel_id, ASSESSOR))["version"]


def test_appeal_remeasure_returns_to_under_review(api):
    """PRD §3.7: "The loop closes when an `Assessor` records a new measurement
    whose `source` is `APPEAL_REMEASURE` for the appealed parcel: that
    measurement returns the appeal from `NEEDS_REMEASURE` back to `UNDER_REVIEW`,
    so an appeal can cycle between `UNDER_REVIEW` and `NEEDS_REMEASURE` more than
    once before it is decided."

    Design: Difficulty/non_linear_state_machine/appeal_needs_remeasure_review_cycle
    """
    base = setup_appeal_needs_remeasure(api, measured_sqft=18000)
    assert base["appeal"]["status"] == "NEEDS_REMEASURE"
    validate_success(
        api.create_measurement(
            create_measurement_payload(base["parcel"]["id"], base["parcel_version"],
                                       measured_sqft=12000, method="FIELD_SURVEY",
                                       source="APPEAL_REMEASURE"), ASSESSOR),
        expected_status=201)
    appeal = validate_success(api.get_appeal(base["appeal"]["id"], STORMWATER_ADMIN))
    assert appeal["status"] == "UNDER_REVIEW"
    parcel = validate_success(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    assert parcel["billable_eru"] == 4.0


def test_appeal_cycle_revisits_needs_remeasure_twice(api):
    """PRD §3.7: "so an appeal can cycle between `UNDER_REVIEW` and
    `NEEDS_REMEASURE` more than once before it is decided."
    PRD §3.7: "From `UNDER_REVIEW`, an appeal grounded in `MEASUREMENT_ERROR` may
    be sent back for re-measurement, advancing it from `UNDER_REVIEW` to
    `NEEDS_REMEASURE` and flagging the parcel as awaiting an `APPEAL_REMEASURE`
    measurement."

    Design: Difficulty/non_linear_state_machine/appeal_needs_remeasure_review_cycle
    """
    base = setup_appeal_needs_remeasure(api, measured_sqft=18000)
    appeal_id = base["appeal"]["id"]
    parcel_id = base["parcel"]["id"]
    # First remeasure measurement returns appeal to UNDER_REVIEW.
    validate_success(
        api.create_measurement(
            create_measurement_payload(parcel_id, _parcel_version(api, parcel_id),
                                       measured_sqft=12000, method="FIELD_SURVEY",
                                       source="APPEAL_REMEASURE"), ASSESSOR),
        expected_status=201)
    assert validate_success(api.get_appeal(appeal_id, STORMWATER_ADMIN))["status"] == "UNDER_REVIEW"
    # Send it back a SECOND time — the cycle re-enters NEEDS_REMEASURE.
    validate_success(api.remeasure_appeal(appeal_id, STORMWATER_ADMIN))
    assert validate_success(api.get_appeal(appeal_id, STORMWATER_ADMIN))["status"] == "NEEDS_REMEASURE"
    # A second APPEAL_REMEASURE measurement closes the loop again to UNDER_REVIEW.
    validate_success(
        api.create_measurement(
            create_measurement_payload(parcel_id, _parcel_version(api, parcel_id),
                                       measured_sqft=9000, method="GIS",
                                       source="APPEAL_REMEASURE"), ASSESSOR),
        expected_status=201)
    assert validate_success(api.get_appeal(appeal_id, STORMWATER_ADMIN))["status"] == "UNDER_REVIEW"


def test_appeal_decide_from_submitted_returns_not_reviewable(api):
    """PRD §3.7: "Deciding an appeal requires it to be `UNDER_REVIEW`; deciding
    one in any other state is rejected with `ERR_APPEAL_NOT_REVIEWABLE`."

    Design: Corner/state_machines/appeal_decide_from_submitted_returns_not_reviewable
    """
    base = create_active_parcel(api, measured_sqft=9000, land_use="COMMERCIAL")
    appeal = validate_success(
        api.create_appeal(
            create_appeal_payload(base["parcel"]["id"], base["account"]["id"],
                                  grounds="LAND_USE_ERROR", narrative="wrong class"),
            STORMWATER_ADMIN),
        expected_status=201)
    resp = api.decide_appeal(appeal["id"], {"outcome": "UPHELD"}, STORMWATER_ADMIN)
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_REVIEWABLE.value)


def test_appeal_remeasure_on_non_measurement_grounds_rejected(api):
    """PRD §3.7: "this step is rejected with `ERR_APPEAL_NOT_REVIEWABLE` when the
    appeal is not `UNDER_REVIEW` or when its `grounds` are anything other than
    `MEASUREMENT_ERROR`."

    Design: Corner/state_machines/appeal_remeasure_on_non_measurement_grounds_rejected
    """
    base = setup_appeal_under_review(api, grounds="LAND_USE_ERROR", measured_sqft=9000)
    resp = api.remeasure_appeal(base["appeal"]["id"], STORMWATER_ADMIN)
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_REVIEWABLE.value)


def test_appeal_bill_mismatch_rejected(api):
    """PRD §3.7: "When a `bill_id` is supplied, that bill must belong to the same
    parcel named as `parcel_id`; a bill that belongs to a different parcel is
    rejected with `ERR_APPEAL_BILL_MISMATCH`."

    Design: Corner/validations/appeal_bill_mismatch_rejected
    """
    # parcel1 (with a bill) and parcel2 both under the same account.
    base1 = setup_issued_bill(api, measured_sqft=9000, land_use="COMMERCIAL")
    base2 = create_active_parcel(api, measured_sqft=9000, land_use="COMMERCIAL",
                                 account=base1["account"])
    resp = api.create_appeal(
        create_appeal_payload(base2["parcel"]["id"], base1["account"]["id"],
                              grounds="MEASUREMENT_ERROR", narrative="mismatch",
                              bill_id=base1["bill"]["id"]),
        STORMWATER_ADMIN)
    validate_error(resp, ApiErrorId.ERR_APPEAL_BILL_MISMATCH.value)
