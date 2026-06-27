"""Claim gates: suspended/vetting/availability/overlap, validation precedence, OCC.

Translates difficulty queue (priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap, boundary_precision_check overlap edge) and corner queue
(state_machines.claim_already_claimed, cross_cutting OCC success/stale).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_claim_payload, create_cancel_payload,
    TEST_USERS, make_client_headers, make_tasker_headers,
    setup_catalog, create_offered_booking, claim_booking, suspend_tasker,
    create_skill, create_window, get_tasker_version,
)

DISP = TEST_USERS["dispatcher_headers"]
TSO = TEST_USERS["trust_safety_headers"]


def test_claim_state_check_beats_suspended_safety(api):
    """PRD §2.9: "(5) whether the target resource is in a legal state for the requested
    transition, failing with the relevant invalid-state error (ERR_BOOKING_INVALID_STATE,
    ERR_SKILL_INVALID_STATE, ERR_INCIDENT_INVALID_STATE, ERR_REVIEW_INVALID_STATE, or
    ERR_SERIES_INVALID_STATE); (6) tasker trust and vetting gates, failing with
    ERR_TASKER_SUSPENDED or ERR_VETTING_REQUIRED".

    Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_safety_invalid_state_over_suspended
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "PriPair Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Suspended Steve", "hourly_rate_cents": 5000},
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    suspend_tasker(tk)
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                                estimated_hours=2.0)
    # Cancel it so the booking is terminal (state-illegal for claim).
    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl)), 200)

    ver = get_tasker_version(tk)
    res = api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_BOOKING_INVALID_STATE")


def test_claim_suspended_safety_beats_availability_constraint(api):
    """PRD §2.9: "(6) tasker trust and vetting gates, failing with ERR_TASKER_SUSPENDED or
    ERR_VETTING_REQUIRED; (7) temporal rules such as same-day date and not-in-the-past, failing
    with ERR_SAME_DAY_DATE_MISMATCH or ERR_START_IN_PAST; (8) availability-window containment,
    failing with ERR_OUTSIDE_AVAILABILITY".

    Design: Difficulty/priority_pair_validation_conflict/claim_safety_beats_constraint_suspended_over_outside_availability
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "PriPair2 Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Suspended Sue", "hourly_rate_cents": 5000},
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    suspend_tasker(tk)
    # No availability window exists for this tasker -> availability would fail at pri 8.
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                                estimated_hours=2.0)

    ver = get_tasker_version(tk)
    res = api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_TASKER_SUSPENDED")


def test_claim_blocked_by_suspended_tasker(api):
    """PRD §3.3: "The target tasker must not be SUSPENDED — a suspended tasker cannot be claimed
    onto any booking and the attempt fails with ERR_TASKER_SUSPENDED".

    Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_tasker_suspended_state
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "CrossDep Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Dep Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    suspend_tasker(tk)
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)

    ver = get_tasker_version(tk)
    res = api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_TASKER_SUSPENDED")

    after = validate_success(api.get_booking(bk["id"], DISP), 200)
    assert after["status"] == "OFFERED"


def test_claim_blocked_by_unvetted_skill(api):
    """PRD §3.3: "If the booking's category requires vetting, the tasker must hold a VETTED skill
    for that category, else ERR_VETTING_REQUIRED."
    PRD §3.1: "A category whose requires_vetting flag is set demands that, at claim time, the
    tasker hold a skill for that category in VETTED state; absent that, the claim is rejected
    with ERR_VETTING_REQUIRED."

    Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_unvetted_skill_state
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Vetted Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": True},
        tasker_overrides={"full_name": "Unvetted Uli", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    create_skill(tk, ctx["category"]["id"])  # PENDING, not VETTED
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)

    ver = get_tasker_version(tk)
    res = api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_VETTING_REQUIRED")

    after = validate_success(api.get_booking(bk["id"], DISP), 200)
    assert after["status"] == "OFFERED"


def test_buffered_overlap_conflict_rejected(api):
    """PRD §3.4: "The candidate and an existing booking conflict when the candidate's start is
    earlier than the other booking's end plus the buffer, and simultaneously the other booking's
    start is earlier than the candidate's end plus the buffer."
    PRD §3.4: "The platform reserves a travel buffer of 30 minutes after every booking".
    PRD §3.4: "Any genuine conflict is rejected with ERR_SCHEDULE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/booking_vs_booking_buffered_halfopen_conflict
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Conflict Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Connie Conflict", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk_a = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                  estimated_hours=1.0)
    claim_booking(bk_a["id"], tk)
    # B starts 11:15 -> within A's end(11:00)+30min buffer(11:30) -> conflict.
    bk_b = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T11:15:00Z",
                                  estimated_hours=1.0)
    ver = get_tasker_version(tk)
    res = api.claim_booking(bk_b["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_SCHEDULE_CONFLICT")

    after = validate_success(api.get_booking(bk_b["id"], DISP), 200)
    assert after["status"] == "OFFERED"


def test_overlap_buffer_exact_edge_admits(api):
    """PRD §3.4: "Because the intervals are half-open at this buffered boundary, a candidate
    that starts exactly at another booking's end-plus-buffer does not conflict."

    Design: Difficulty/boundary_precision_check/booking_overlap_buffer_boundary_exact_edge_admits
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Overlap Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Olga Overlap", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk_a = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                  estimated_hours=1.0)
    claim_booking(bk_a["id"], tk)
    # B starts exactly at A.end(11:00) + 30min buffer = 11:30 -> admitted.
    bk_b = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T11:30:00Z",
                                  estimated_hours=1.0)
    ver = get_tasker_version(tk)
    claimed = validate_success(api.claim_booking(bk_b["id"], create_claim_payload(tk, ver), DISP), 200)
    assert claimed["status"] == "CLAIMED"
    assert claimed["tasker_id"] == tk


def test_booking_outside_availability_window_rejected(api):
    """PRD §3.4: "A booking whose end exactly meets a window's window_end is allowed; a booking
    that exceeds the window end by any positive amount is rejected with ERR_OUTSIDE_AVAILABILITY."

    Design: Difficulty/resource_temporal_overlap/booking_vs_availability_closed_containment_violation
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Contain Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Cam Contain", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T11:30:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    # 2h booking 10:00-12:00 spills 30min past the 11:30 window end.
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                estimated_hours=2.0)
    ver = get_tasker_version(tk)
    res = api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_OUTSIDE_AVAILABILITY")

    after = validate_success(api.get_booking(bk["id"], DISP), 200)
    assert after["status"] == "OFFERED"


def test_claim_already_claimed_booking_rejected(api):
    """PRD §3.3: "Claiming a booking that is not OFFERED is rejected with
    ERR_BOOKING_INVALID_STATE."

    Design: Corner/state_machines/claim_already_claimed_booking_returns_invalid_state
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Claim2 Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Tasker A", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tka = ctx["client"]["id"], ctx["tasker"]["id"]
    tkb = get_success_data(api.create_tasker({"full_name": "Tasker B", "hourly_rate_cents": 4000}, DISP))
    create_window(tkb["id"], "2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z")
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)
    claim_booking(bk["id"], tka)

    ver_b = get_tasker_version(tkb["id"])
    res = api.claim_booking(bk["id"], create_claim_payload(tkb["id"], ver_b), DISP)
    validate_error(res, "ERR_BOOKING_INVALID_STATE")

    after = validate_success(api.get_booking(bk["id"], DISP), 200)
    assert after["tasker_id"] == tka


def test_occ_correct_version_claim_succeeds_and_increments(api):
    """PRD §3.3: "When the claim succeeds, the booking moves to CLAIMED, its tasker_id is set to
    the target tasker, the tasker's version is incremented by one, and the tasker's
    active_booking_count is recomputed upward to reflect the newly held job."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_claim_succeeds
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Occ Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Occ Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    ver_before = get_tasker_version(tk)
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)

    claimed = validate_success(api.claim_booking(bk["id"], create_claim_payload(tk, ver_before), DISP), 200)
    assert claimed["status"] == "CLAIMED"

    ver_after = get_tasker_version(tk)
    assert ver_after == ver_before + 1


def test_occ_stale_version_claim_rejected(api):
    """PRD §2.6: "If that value does not equal the tasker's current version at the moment the
    claim is processed, the request is rejected with ERR_STALE_TASKER_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_claim_returns_412
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Stale Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Stale Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T18:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    stale_version = get_tasker_version(tk)
    bk_a = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                  estimated_hours=1.0)
    bk_b = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T14:00:00Z",
                                  estimated_hours=1.0)
    # Claim A advances the tasker version, making `stale_version` stale.
    validate_success(api.claim_booking(bk_a["id"], create_claim_payload(tk, stale_version), DISP), 200)

    res = api.claim_booking(bk_b["id"], create_claim_payload(tk, stale_version), DISP)
    validate_error(res, "ERR_STALE_TASKER_VERSION")

    after = validate_success(api.get_booking(bk_b["id"], DISP), 200)
    assert after["status"] == "OFFERED"
