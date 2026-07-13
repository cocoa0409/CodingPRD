"""Permit issuance interval conflicts and inspection scheduling / lifecycle."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_permit_payload,
    create_inspection_payload,
    make_regulator_headers,
    register_facility,
    issue_permit,
    schedule_inspection,
    create_started_inspection,
    create_completed_inspection,
)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / permit_closed_interval_touching_overlap
# ---------------------------------------------------------------------------
def test_permit_touching_interval_same_type_overlaps(api):
    """PRD §3.6: "the permit's validity interval runs inclusively from `issued_date`
    through `expiry_date`, and it may not overlap the interval of an existing permit
    of the same `permit_type` on the same facility; an overlap is rejected with
    `ERR_PERMIT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/permit_closed_interval_touching_overlap
    """
    facility = register_facility()
    fac_id = facility["id"]
    issue_permit(fac_id, permit_type="OPERATING",
                 issued_date="2026-01-01T00:00:00Z", expiry_date="2026-06-30T00:00:00Z")
    payload = create_permit_payload(
        fac_id, permit_type="OPERATING",
        issued_date="2026-06-30T00:00:00Z", expiry_date="2026-12-31T00:00:00Z",
    )
    resp = api.create_permit(payload, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_PERMIT_PERIOD_OVERLAP.value)


def test_permit_same_interval_different_type_allowed(api):
    """PRD §3.6: "it may not overlap the interval of an existing permit of the same
    `permit_type` on the same facility; an overlap is rejected with
    `ERR_PERMIT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/permit_closed_interval_touching_overlap
    """
    facility = register_facility()
    fac_id = facility["id"]
    issue_permit(fac_id, permit_type="OPERATING",
                 issued_date="2026-01-01T00:00:00Z", expiry_date="2026-06-30T00:00:00Z")
    # Different permit_type -> the same-type overlap rule does not apply.
    payload = create_permit_payload(
        fac_id, permit_type="STORAGE",
        issued_date="2026-01-01T00:00:00Z", expiry_date="2026-06-30T00:00:00Z",
    )
    resp = api.create_permit(payload, make_regulator_headers())
    data = validate_success(resp, expected_status=201)
    assert data["permit_type"] == "STORAGE"
    assert data["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / inspector_buffer_double_booking
# ---------------------------------------------------------------------------
def test_inspector_within_24h_double_booked(api):
    """PRD §3.6: "To prevent double-booking, an inspection may not be scheduled
    within 24 hours of another inspection already booked for the same `inspector_id`;
    a conflict is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/inspector_buffer_double_booking
    """
    facility = register_facility()
    fac_id = facility["id"]
    schedule_inspection(fac_id, inspector_id="INSP-7", scheduled_date="2026-04-01T09:00:00Z")
    payload = create_inspection_payload(
        fac_id, inspector_id="INSP-7", scheduled_date="2026-04-01T20:00:00Z",  # 11h later
    )
    resp = api.create_inspection(payload, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED.value)


def test_different_inspector_same_time_allowed(api):
    """PRD §3.6: "an inspection may not be scheduled within 24 hours of another
    inspection already booked for the same `inspector_id`; a conflict is rejected
    with `ERR_INSPECTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/inspector_buffer_double_booking
    """
    facility = register_facility()
    fac_id = facility["id"]
    schedule_inspection(fac_id, inspector_id="INSP-7", scheduled_date="2026-04-01T09:00:00Z")
    # A different inspector_id has its own schedule; the buffer is per-inspector.
    payload = create_inspection_payload(
        fac_id, inspector_id="INSP-8", scheduled_date="2026-04-01T09:00:00Z",
    )
    resp = api.create_inspection(payload, make_regulator_headers())
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: state_machines / inspection_start_valid_transition
# ---------------------------------------------------------------------------
def test_start_scheduled_inspection_moves_to_in_progress(api):
    """PRD §3.6: "A regulator begins a scheduled inspection, moving it from
    `SCHEDULED` to `IN_PROGRESS` (valid only when the inspection is `SCHEDULED`, else
    `ERR_INSPECTION_NOT_SCHEDULED`)."

    Design: Corner/state_machines/inspection_start_valid_transition
    """
    facility = register_facility()
    fac_id = facility["id"]
    insp = schedule_inspection(fac_id, inspector_id="INSP-C1", scheduled_date="2026-05-01T09:00:00Z")
    resp = api.start_inspection(insp["id"], make_regulator_headers())
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Corner: state_machines / inspection_complete_twice_returns_not_in_progress
# ---------------------------------------------------------------------------
def test_complete_already_passed_inspection_rejected(api):
    """PRD §3.6: "A regulator then completes an in-progress inspection by supplying a
    `result`; completion is valid only when the inspection is `IN_PROGRESS`,
    otherwise `ERR_INSPECTION_NOT_IN_PROGRESS`."

    Design: Corner/state_machines/inspection_complete_twice_returns_not_in_progress
    """
    facility = register_facility()
    fac_id = facility["id"]
    insp = create_completed_inspection(fac_id, result="PASS",
                                       inspector_id="INSP-C2", scheduled_date="2026-05-02T09:00:00Z")
    resp = api.complete_inspection(insp["id"], {"result": "PASS"}, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_IN_PROGRESS.value)
