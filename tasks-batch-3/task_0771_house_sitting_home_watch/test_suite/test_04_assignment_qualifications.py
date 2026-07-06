"""Sitter-assignment qualifications: clearance precedence, reliability boundary,
and the temporal-overlap guards (sitter schedule conflict, property vacation overlap)."""
from test_helpers import validate_error, ApiErrorId, make_coordinator_headers
from test_helpers import factories as f
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/assign_not_cleared_beats_coverage_inactive
# ---------------------------------------------------------------------------

def test_assign_uncleared_and_unbonded_sitter_reports_not_cleared(api):
    """PRD 3.4: "Beyond that state guard, four business qualifications are evaluated in this fixed order:"
    PRD 3.4: "A sitter who is not cleared, or whose clearance has expired, fails first with
    ERR_SITTER_NOT_CLEARED."

    Design: Difficulty/priority_pair_validation_conflict/assign_not_cleared_beats_coverage_inactive
    """
    ctx = fx.setup_pending_booking(api, onboard_sitter=True, cleared=False, bonded=False)
    resp = api.assign_booking(ctx["booking"]["id"], {"sitter_id": ctx["sitter"]["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_SITTER_NOT_CLEARED.value, expected_status=409)


def test_assign_uncleared_unbonded_leaves_booking_pending(api):
    """PRD 3.4: "A sitter who is not cleared, or whose clearance has expired, fails first with
    ERR_SITTER_NOT_CLEARED."

    Design: Difficulty/priority_pair_validation_conflict/assign_not_cleared_beats_coverage_inactive
    """
    ctx = fx.setup_pending_booking(api, onboard_sitter=True, cleared=False, bonded=False)
    api.assign_booking(ctx["booking"]["id"], {"sitter_id": ctx["sitter"]["id"]}, COORD)
    assert fx.get_booking(api, ctx["booking"]["id"])["status"] == "PENDING_ASSIGNMENT"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/assign_requires_sitter_background_cleared
# ---------------------------------------------------------------------------

def test_assign_bonded_but_uncleared_sitter_reports_not_cleared(api):
    """PRD 3.4: "The sitter's latest background check must be CLEARED and still valid — the current
    clock must be strictly before that check's expires_at."
    PRD 3.4: "A sitter who is not cleared, or whose clearance has expired, fails first with
    ERR_SITTER_NOT_CLEARED."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_sitter_background_cleared
    """
    ctx = fx.setup_pending_booking(api, onboard_sitter=True, cleared=False, bonded=True)
    resp = api.assign_booking(ctx["booking"]["id"], {"sitter_id": ctx["sitter"]["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_SITTER_NOT_CLEARED.value, expected_status=409)


def test_assign_bonded_uncleared_leaves_booking_pending(api):
    """PRD 3.4: "A sitter who is not cleared, or whose clearance has expired, fails first with
    ERR_SITTER_NOT_CLEARED."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_sitter_background_cleared
    """
    ctx = fx.setup_pending_booking(api, onboard_sitter=True, cleared=False, bonded=True)
    api.assign_booking(ctx["booking"]["id"], {"sitter_id": ctx["sitter"]["id"]}, COORD)
    assert fx.get_booking(api, ctx["booking"]["id"])["status"] == "PENDING_ASSIGNMENT"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/reliability_threshold_at_exactly_60_allows_assign
# ---------------------------------------------------------------------------

def _sitter_at_reliability_60_with_fresh_pending_booking(api):
    """Two missed visits drop the sitter to exactly 60; return (sitter_id, fresh_booking_id)."""
    fx.set_clock(api, "2026-05-01T00:00:00Z")
    client = fx.create_client(api)
    prop1 = fx.create_property(api, client["id"], label="P1")
    prop2 = fx.create_property(api, client["id"], label="P2", center_lat=41.0, center_lng=-71.0)
    sitter = fx.onboard_cleared_bonded_sitter(api)
    bk1 = fx.create_booking(api, prop1["id"], booking_type="RECURRING", frequency="DAILY",
                            start_date="2026-06-01T00:00:00Z", end_date="2026-06-02T00:00:00Z")
    fx.submit_booking(api, bk1["id"])
    fx.assign_booking(api, bk1["id"], sitter["id"])
    visits = fx.list_visits(api, bk1["id"])
    fx.set_clock(api, "2026-06-03T00:00:00Z")
    for v in visits:
        fx.get_success_data(api.mark_missed_visit(v["id"], COORD))
    bk2 = fx.create_booking(api, prop2["id"], booking_type="VACATION",
                            start_date="2026-06-05T00:00:00Z", end_date="2026-06-05T00:00:00Z")
    fx.submit_booking(api, bk2["id"])
    return sitter["id"], bk2["id"]


def test_sitter_reliability_lands_on_threshold_60(api):
    """PRD 2.10: "the greater of zero and the value obtained by subtracting twenty times the
    missed-visit count and ten times the escalated-incident count from one hundred."
    PRD 3.8: "Marking a visit missed increments the sitter's missed_visit_count by one and
    recomputes the reliability_score".

    Design: Difficulty/boundary_precision_check/reliability_threshold_at_exactly_60_allows_assign
    """
    sitter_id, _ = _sitter_at_reliability_60_with_fresh_pending_booking(api)
    assert fx.get_sitter(api, sitter_id)["reliability_score"] == 60


def test_assign_succeeds_at_reliability_exactly_60(api):
    """PRD 3.4: "The sitter's reliability_score must be at least 60; a lower score fails with
    ERR_SITTER_RELIABILITY_TOO_LOW."
    PRD 3.4: "When all four qualifications pass, assignment records sitter_id on the booking,
    generates the visit rows, and creates the booking's invoice in DRAFT with a subtotal of zero."

    Design: Difficulty/boundary_precision_check/reliability_threshold_at_exactly_60_allows_assign
    """
    sitter_id, bk2_id = _sitter_at_reliability_60_with_fresh_pending_booking(api)
    fx.assign_booking(api, bk2_id, sitter_id)
    assert fx.get_booking(api, bk2_id)["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/sitter_visit_buffered_overlap_conflict
# ---------------------------------------------------------------------------

def _sitter_double_booked_same_window(api):
    """Sitter already assigned to a 06-01 visit; a second 06-01 booking is pending. Returns bk2_id, sitter_id."""
    fx.set_clock(api, "2026-05-01T00:00:00Z")
    client = fx.create_client(api)
    prop1 = fx.create_property(api, client["id"], label="P1")
    prop2 = fx.create_property(api, client["id"], label="P2", center_lat=41.0, center_lng=-71.0)
    sitter = fx.onboard_cleared_bonded_sitter(api)
    bk1 = fx.create_booking(api, prop1["id"], booking_type="VACATION",
                            start_date="2026-06-01T00:00:00Z", end_date="2026-06-01T00:00:00Z")
    fx.submit_booking(api, bk1["id"])
    fx.assign_booking(api, bk1["id"], sitter["id"])
    bk2 = fx.create_booking(api, prop2["id"], booking_type="VACATION",
                            start_date="2026-06-01T00:00:00Z", end_date="2026-06-01T00:00:00Z")
    fx.submit_booking(api, bk2["id"])
    return bk2["id"], sitter["id"]


def test_assign_conflicting_sitter_window_reports_schedule_conflict(api):
    """PRD 3.4: "None of the visits this booking would generate may collide with the sitter's
    existing SCHEDULED or IN_PROGRESS visits under the buffered-overlap rule: two visit windows
    conflict when the prospective visit's start is earlier than the existing visit's end extended by
    the buffer, and simultaneously the existing visit's start is earlier than the prospective visit's
    end extended by the buffer. Any such collision fails with ERR_SITTER_SCHEDULE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/sitter_visit_buffered_overlap_conflict
    """
    bk2_id, sitter_id = _sitter_double_booked_same_window(api)
    resp = api.assign_booking(bk2_id, {"sitter_id": sitter_id}, COORD)
    validate_error(resp, ApiErrorId.ERR_SITTER_SCHEDULE_CONFLICT.value, expected_status=409)


def test_assign_schedule_conflict_leaves_second_booking_pending(api):
    """PRD 3.4: "Any such collision fails with ERR_SITTER_SCHEDULE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/sitter_visit_buffered_overlap_conflict
    """
    bk2_id, sitter_id = _sitter_double_booked_same_window(api)
    api.assign_booking(bk2_id, {"sitter_id": sitter_id}, COORD)
    assert fx.get_booking(api, bk2_id)["status"] == "PENDING_ASSIGNMENT"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/property_vacation_closed_interval_overlap
# ---------------------------------------------------------------------------

def _property_with_overlapping_vacation_bookings(api):
    """Property already has a PENDING vacation 06-01..06-05; a second DRAFT vacation 06-03..06-07. Returns bk2_id."""
    fx.set_clock(api, "2026-05-01T00:00:00Z")
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"])
    bk1 = fx.create_booking(api, prop["id"], booking_type="VACATION",
                            start_date="2026-06-01T00:00:00Z", end_date="2026-06-05T00:00:00Z")
    fx.submit_booking(api, bk1["id"])
    bk2 = fx.create_booking(api, prop["id"], booking_type="VACATION",
                            start_date="2026-06-03T00:00:00Z", end_date="2026-06-07T00:00:00Z")
    return bk2["id"]


def test_overlapping_vacation_submit_reports_property_overlap(api):
    """PRD 3.3: "if any other VACATION booking on the same property that is currently in
    PENDING_ASSIGNMENT, SCHEDULED, or ACTIVE has an inclusive date range that overlaps the submitted
    booking's [start_date, end_date], submission is rejected with ERR_PROPERTY_BOOKING_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/property_vacation_closed_interval_overlap
    """
    bk2_id = _property_with_overlapping_vacation_bookings(api)
    resp = api.submit_booking(bk2_id, COORD)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_BOOKING_OVERLAP.value, expected_status=409)


def test_overlapping_vacation_submit_leaves_second_booking_draft(api):
    """PRD 3.3: "submission is rejected with ERR_PROPERTY_BOOKING_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/property_vacation_closed_interval_overlap
    """
    bk2_id = _property_with_overlapping_vacation_bookings(api)
    api.submit_booking(bk2_id, COORD)
    assert fx.get_booking(api, bk2_id)["status"] == "DRAFT"
