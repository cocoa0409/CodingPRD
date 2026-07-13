"""Impervious measurement, ERU assessment, create-with-supersede, and the
optimistic-concurrency guard on the parcel version."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_measurement_payload,
    create_active_parcel, grant_exemption,
)

ASSESSOR = TEST_USERS["assessor_headers"]


def test_parcel_billable_eru_computed_from_measurement(api):
    """PRD §3.2: "That exempt-adjusted area is then divided by the base area of a
    single residential unit — 3,000 square feet — to yield a raw ERU figure.
    Finally the raw figure is rounded to the nearest tenth of an ERU using round
    half up to produce `billable_eru`."
    PRD §2.6: "`current_fee_cents` holds the parcel's live marginal-variant
    annual fee for its present state."
    PRD §3.5: "The `assessed_fee_cents` is then the fixed charge plus the base
    fee minus the credit amount."

    Design: Corner/entities/parcel_billable_eru_computed_from_measurement
    """
    base = create_active_parcel(api, measured_sqft=9000, land_use="RESIDENTIAL_SF",
                                method="AERIAL")
    parcel = base["parcel"]
    assert parcel["status"] == "ACTIVE"
    assert parcel["billable_eru"] == 3.0
    assert parcel["current_fee_cents"] == 11000


def test_eru_rounding_applies_exemption_to_area_first(api):
    """PRD §3.2: "First the exemption is applied to area: the impervious area is
    multiplied by one minus the parcel's exempt fraction."
    PRD §3.2: "The order matters: applying the exemption to area before dividing
    and rounding can differ, at the tenth-of-an-ERU boundary, from rounding first
    and exempting after, so exemption-to-area-then-divide-then-round is the
    required sequence."

    Design: Corner/entities/eru_rounding_applies_exemption_to_area_first
    """
    base = create_active_parcel(api, measured_sqft=13650, land_use="COMMERCIAL")
    grant_exemption(api, base["parcel"]["id"], requested_pct=0.20, granted_pct=0.20,
                    category="LOW_IMPACT")
    parcel = validate_success(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    assert parcel["exempt_pct"] == 0.20
    assert parcel["billable_eru"] == 3.6
    assert parcel["current_fee_cents"] == 13100


def test_measurement_supersede_marks_prior_superseded(api):
    """PRD §3.2: "Recording a measurement is a create-with-supersede operation
    carried out in a single request: the new measurement is written with `status`
    `ACTIVE`, and if the parcel already had an `ACTIVE` measurement, that prior
    one is moved to `SUPERSEDED` at the same time."

    Design: Corner/state_machines/measurement_supersede_marks_prior_superseded
    """
    base = create_active_parcel(api, measured_sqft=9000, land_use="COMMERCIAL")
    # Capture the first measurement's id from the parcel's active pointer.
    parcel = validate_success(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    m1_id = parcel["active_measurement_id"]
    pv1 = parcel["version"]
    m2 = validate_success(
        api.create_measurement(
            create_measurement_payload(parcel["id"], pv1, measured_sqft=12000,
                                       method="FIELD_SURVEY"), ASSESSOR),
        expected_status=201)
    m1 = validate_success(api.get_measurement(m1_id, ASSESSOR))
    assert m1["status"] == "SUPERSEDED"
    assert m2["status"] == "ACTIVE"
    parcel = validate_success(api.get_parcel(parcel["id"], ASSESSOR))
    assert parcel["impervious_area_sqft"] == 12000
    assert parcel["billable_eru"] == 4.0


def test_occ_stale_parcel_version_rejected(api):
    """PRD §2.7: "If the parcel's `version` has advanced since then — because
    another measurement was recorded, or an exemption decision or credit change
    re-derived the parcel — the client's view is stale and the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_parcel_version_rejected
    """
    acct = validate_success(api.create_account({"owner_name": "Rivera",
                                                "contact_email": "r@x.com"}, ASSESSOR),
                            expected_status=201)
    parcel = validate_success(
        api.create_parcel({"account_id": acct["id"], "parcel_number": "P-CC1",
                           "land_use": "COMMERCIAL"}, ASSESSOR),
        expected_status=201)
    pv0 = parcel["version"]
    # First measurement with pv0 succeeds; parcel version advances to pv0+1.
    validate_success(
        api.create_measurement(
            create_measurement_payload(parcel["id"], pv0, measured_sqft=9000), ASSESSOR),
        expected_status=201)
    # Second measurement reusing the now-stale pv0 is rejected.
    resp = api.create_measurement(
        create_measurement_payload(parcel["id"], pv0, measured_sqft=12000), ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    parcel = validate_success(api.get_parcel(parcel["id"], ASSESSOR))
    assert parcel["impervious_area_sqft"] == 9000
