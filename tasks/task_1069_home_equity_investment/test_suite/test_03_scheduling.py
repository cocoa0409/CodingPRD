"""Appraisal-appointment scheduling gates and inspection same-day exclusivity."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS,
    fixtures,
)

ANALYST = TEST_USERS["analyst_headers"]


# --------------------------------------------------------------------------
# priority_pair: region (referential, prio 9) beats double-book (temporal, 10)
# --------------------------------------------------------------------------
def test_region_mismatch_reported_over_double_booking(api):
    """PRD §3.2: "the appointment's `region_code` must equal the appraiser's own
    `region_code`, else `ERR_APPRAISER_REGION_MISMATCH`".

    Design: Difficulty/priority_pair_validation_conflict/appointment_referential_beats_temporal
    """
    ctx = fixtures.setup_appraiser_with_pending_valuations(api, num_valuations=2)
    fixtures.schedule_appointment(
        api, ctx["appraiser"]["id"], ctx["valuations"][0]["id"],
        region_code="CA-BAY",
        scheduled_start="2026-07-05T10:00:00Z", scheduled_end="2026-07-05T11:00:00Z",
    )
    resp = api.create_appointment(
        {
            "appraiser_id": ctx["appraiser"]["id"], "valuation_id": ctx["valuations"][1]["id"],
            "region_code": "CA-LA",
            "scheduled_start": "2026-07-05T10:30:00Z", "scheduled_end": "2026-07-05T11:30:00Z",
        },
        ANALYST,
    )
    validate_error(resp, "ERR_APPRAISER_REGION_MISMATCH", 409)


def test_region_mismatch_not_masked_by_temporal_error(api):
    """PRD §2.8: "(9) cross-entity state prerequisites (basis valuation
    completed, lien recorded, appraiser region match) ... (10) resource
    temporal-overlap checks for appraisal and inspection scheduling".

    Design: Difficulty/priority_pair_validation_conflict/appointment_referential_beats_temporal
    """
    ctx = fixtures.setup_appraiser_with_pending_valuations(api, num_valuations=2)
    fixtures.schedule_appointment(
        api, ctx["appraiser"]["id"], ctx["valuations"][0]["id"],
        region_code="CA-BAY",
        scheduled_start="2026-07-05T10:00:00Z", scheduled_end="2026-07-05T11:00:00Z",
    )
    resp = api.create_appointment(
        {
            "appraiser_id": ctx["appraiser"]["id"], "valuation_id": ctx["valuations"][1]["id"],
            "region_code": "CA-LA",
            "scheduled_start": "2026-07-05T10:30:00Z", "scheduled_end": "2026-07-05T11:30:00Z",
        },
        ANALYST,
    )
    error = resp.json()["data"]["error_id"]
    assert error == "ERR_APPRAISER_REGION_MISMATCH"
    assert error != "ERR_APPRAISER_DOUBLE_BOOKED"


# --------------------------------------------------------------------------
# resource_temporal_overlap: appraiser 60-minute buffer
# --------------------------------------------------------------------------
def test_appointment_within_buffer_is_double_booked(api):
    """PRD §3.2: "if the same appraiser already has a SCHEDULED appointment
    whose window comes within sixty minutes of the requested window, the request
    is rejected with ERR_APPRAISER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/appraiser_buffer_overlap
    """
    ctx = fixtures.setup_appraiser_with_pending_valuations(api, num_valuations=2)
    fixtures.schedule_appointment(
        api, ctx["appraiser"]["id"], ctx["valuations"][0]["id"],
        scheduled_start="2026-07-05T10:00:00Z", scheduled_end="2026-07-05T11:00:00Z",
    )
    resp = api.create_appointment(
        {
            "appraiser_id": ctx["appraiser"]["id"], "valuation_id": ctx["valuations"][1]["id"],
            "region_code": "CA-BAY",
            "scheduled_start": "2026-07-05T11:30:00Z", "scheduled_end": "2026-07-05T12:30:00Z",
        },
        ANALYST,
    )
    validate_error(resp, "ERR_APPRAISER_DOUBLE_BOOKED", 409)


def test_appointment_outside_buffer_is_allowed(api):
    """PRD §3.2: "if the same appraiser already has a SCHEDULED appointment
    whose window comes within sixty minutes of the requested window, the request
    is rejected with ERR_APPRAISER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/appraiser_buffer_overlap
    """
    ctx = fixtures.setup_appraiser_with_pending_valuations(api, num_valuations=2)
    fixtures.schedule_appointment(
        api, ctx["appraiser"]["id"], ctx["valuations"][0]["id"],
        scheduled_start="2026-07-05T10:00:00Z", scheduled_end="2026-07-05T11:00:00Z",
    )
    appt = validate_success(api.create_appointment(
        {
            "appraiser_id": ctx["appraiser"]["id"], "valuation_id": ctx["valuations"][1]["id"],
            "region_code": "CA-BAY",
            "scheduled_start": "2026-07-05T13:00:00Z", "scheduled_end": "2026-07-05T14:00:00Z",
        },
        ANALYST,
    ), 201)
    assert appt["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# resource_temporal_overlap: inspector whole-day exclusivity
# --------------------------------------------------------------------------
def test_inspection_same_day_is_double_booked(api):
    """PRD §3.6: "scheduling is rejected with ERR_INSPECTOR_DOUBLE_BOOKED if
    that inspector already holds a non-cancelled inspection on the same
    scheduled_date."

    Design: Difficulty/resource_temporal_overlap/inspector_same_day_overlap
    """
    ctx = fixtures.setup_funded_agreement(api)
    inspector = fixtures.create_inspector(api)
    fixtures.schedule_inspection(api, ctx["agreement"]["id"], inspector["id"], scheduled_date="2026-09-01")
    resp = api.create_inspection(
        ctx["agreement"]["id"], {"inspector_id": inspector["id"], "scheduled_date": "2026-09-01"}, ANALYST
    )
    validate_error(resp, "ERR_INSPECTOR_DOUBLE_BOOKED", 409)


def test_inspection_different_day_is_allowed(api):
    """PRD §3.6: "scheduling is rejected with ERR_INSPECTOR_DOUBLE_BOOKED if
    that inspector already holds a non-cancelled inspection on the same
    scheduled_date."

    Design: Difficulty/resource_temporal_overlap/inspector_same_day_overlap
    """
    ctx = fixtures.setup_funded_agreement(api)
    inspector = fixtures.create_inspector(api)
    fixtures.schedule_inspection(api, ctx["agreement"]["id"], inspector["id"], scheduled_date="2026-09-01")
    second = validate_success(api.create_inspection(
        ctx["agreement"]["id"], {"inspector_id": inspector["id"], "scheduled_date": "2026-09-02"}, ANALYST
    ), 201)
    assert second["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Queue-B corner: appointment time range
# --------------------------------------------------------------------------
def test_appointment_end_before_start_rejected(api):
    """PRD §3.2: "`scheduled_end` must be strictly after `scheduled_start`, else
    `ERR_INVALID_TIME_RANGE`."

    Design: Corner/endpoints/appointment_end_before_start_returns_invalid_time_range
    """
    ctx = fixtures.setup_appraiser_with_pending_valuations(api, num_valuations=1)
    resp = api.create_appointment(
        {
            "appraiser_id": ctx["appraiser"]["id"], "valuation_id": ctx["valuations"][0]["id"],
            "region_code": "CA-BAY",
            "scheduled_start": "2026-07-05T11:00:00Z", "scheduled_end": "2026-07-05T10:00:00Z",
        },
        ANALYST,
    )
    validate_error(resp, "ERR_INVALID_TIME_RANGE", 400)
