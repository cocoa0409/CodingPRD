"""Ambassadors, shift scheduling with the buffer rule, and service-request resolution
reconciled against the work plan."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, new_bid,
    setup_ambassador_with_shift, setup_service_request_in_progress,
    make_ambassador_headers,
    create_ambassador_payload, create_service_request_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["district_administrator_headers"]


def test_shift_within_buffer_gap_rejected(api):
    """PRD §3.7: "Shifts on one ambassador are treated as closed intervals that may not
    overlap, and consecutive shifts must be separated by at least the shift buffer of 30
    minutes; a new shift that overlaps or falls within that half-hour gap of an existing
    scheduled shift of the same ambassador is rejected with ERR_SHIFT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/ambassador_shift_buffered_overlap
    """
    ctx = setup_ambassador_with_shift()  # existing 08:00-12:00
    resp = api.create_shift(ctx["ambassador"]["id"], {
        "zone": "Z2", "start_at": "2026-06-01T12:20:00Z", "end_at": "2026-06-01T14:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP.value)


def test_shift_at_exact_buffer_accepted(api):
    """PRD §3.7: "consecutive shifts must be separated by at least the shift buffer of 30
    minutes".

    Design: Difficulty/resource_temporal_overlap/ambassador_shift_buffered_overlap
    """
    ctx = setup_ambassador_with_shift()  # existing 08:00-12:00
    shift = validate_success(api.create_shift(ctx["ambassador"]["id"], {
        "zone": "Z3", "start_at": "2026-06-01T12:30:00Z", "end_at": "2026-06-01T14:00:00Z"}, ADMIN), 201)
    assert shift["status"] == "SCHEDULED"


def test_assign_to_inactive_ambassador_rejected(api):
    """PRD §3.7: "assignment (OPEN → ASSIGNED) sets assigned_ambassador_id and requires that
    the target ambassador belong to the same district and be ACTIVE, else
    ERR_AMBASSADOR_NOT_ACTIVE."

    Design: Corner/errors/ambassador_not_active_on_assign_rejected
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="AN BID")
    amb = get_success_data(api.create_ambassador(
        bid["id"], create_ambassador_payload(name="Bob", service_role="SAFE"), ADMIN))
    get_success_data(api.deactivate_ambassador(amb["id"], ADMIN))
    sr = get_success_data(api.create_service_request(
        bid["id"], create_service_request_payload(category="SAFE", source="PHONE"), ADMIN))
    resp = api.transition_service_request(
        sr["id"], {"action": "ASSIGN", "ambassador_id": amb["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_AMBASSADOR_NOT_ACTIVE.value)


def test_resolve_service_request_charges_work_plan_line(api):
    """PRD §3.7: "the request records its logged_cost_cents and work_plan_category, and that
    line's spent_amount_cents is increased by the logged cost."

    Design: Corner/calculations/workplan_spend_reconciled_on_resolve
    """
    ctx = setup_service_request_in_progress(category="CLEAN")
    amb_headers = make_ambassador_headers(ctx["ambassador"]["id"])
    sr = validate_success(api.transition_service_request(
        ctx["service_request"]["id"],
        {"action": "RESOLVE", "logged_cost_cents": 50000, "work_plan_category": "CLEAN"}, amb_headers))
    assert sr["status"] == "RESOLVED"
    lines = api.list_work_plan_lines(ctx["budget"]["id"], ADMIN).json()["data"]
    clean = next(l for l in lines if l["category"] == "CLEAN")
    assert clean["spent_amount_cents"] == 50000
