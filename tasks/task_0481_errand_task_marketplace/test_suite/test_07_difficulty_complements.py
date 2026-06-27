"""Second-angle tests for each difficulty instance (≥2 tests per instance).

Each test here asserts a distinct, independently PRD-grounded observable for a difficulty
instance already exercised once elsewhere — a converse branch, a boundary neighbor, or a
separate side-effect — never a re-run of the same assertion.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_complete_payload, create_cancel_payload, create_propose_payload,
    create_accept_payload, create_claim_payload, create_review_payload,
    TEST_USERS, make_client_headers, make_tasker_headers,
    setup_catalog, create_offered_booking, create_claimed_booking,
    create_in_progress_booking, create_completed_booking, claim_booking,
    suspend_tasker, file_incident, get_tasker_version, create_skill,
)

DISP = TEST_USERS["dispatcher_headers"]
TSO = TEST_USERS["trust_safety_headers"]


# ─── dual_variant_calc ──────────────────────────────────────────────────────

def test_estimate_pins_category_default_rate_not_tasker(api):
    """PRD §3.2: "the estimated labor is the category's default_hourly_rate_cents multiplied by
    the client-supplied estimated_hours, then truncated down to whole cents — note that the
    category default rate is used here precisely because no tasker has yet been claimed."

    Design: Difficulty/dual_variant_calc/estimate_vs_final_labor_diverges_on_booking_pricing
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Est Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Rate Diff", "hourly_rate_cents": 5000},
    )
    cl = ctx["client"]["id"]
    offered = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                     estimated_hours=2.0)
    # Quote uses category default 4000, NOT the tasker's 5000.
    assert offered["estimated_labor_cents"] == 8000
    assert offered["estimated_service_fee_cents"] == 1200
    assert offered["estimated_total_cents"] == 9200


def test_trust_score_high_penalty_value_35(api):
    """PRD §3.7: "The `severity` is `LOW`, `MEDIUM`, or `HIGH`, carrying `penalty_points` of 5, 15, and
    35 respectively while the incident counts against the tasker."

    Design: Difficulty/dual_variant_calc/trust_score_penalty_included_vs_dismissed_excluded_on_tasker
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", TSO))
    tk = get_success_data(api.create_tasker({"full_name": "HighPen", "hourly_rate_cents": 5000}, DISP))
    inc = file_incident(tk["id"], severity="HIGH")
    after = validate_success(api.get_incident(inc["id"], TSO), 200)
    assert after["penalty_points"] == 35
    tasker = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert tasker["incident_penalty_total"] == 35


# ─── combinatorial_formula ──────────────────────────────────────────────────

def test_final_settlement_exact_quarter_hour_no_round(api):
    """PRD §3.5: "the reported actual_hours is divided by 0.25, rounded up to the next whole
    number, and multiplied back by 0.25 to give the billed hours."

    Design: Difficulty/combinatorial_formula/final_settlement_quarter_hour_rounding_order_mode_b
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "ExactQ Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Exact Q", "hourly_rate_cents": 5000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T13:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_in_progress_booking(cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z",
                                    estimated_hours=2.0)
    # actual_hours=1.5 is an exact multiple of 0.25 -> billed 1.5 -> floor(5000*1.5)=7500.
    get_success_data(api.complete_booking(
        bk["id"], create_complete_payload(actual_hours=1.5), make_tasker_headers(tk)))
    s = validate_success(api.get_settlement(bk["id"], DISP), 200)[0]
    assert s["final_labor_cents"] == 7500
    assert s["final_service_fee_cents"] == 1125


def test_cancellation_last_minute_tier_fifty_percent(api):
    """PRD §3.6: "anything under 2 hours is the `LAST_MINUTE` tier at fifty percent."

    Design: Difficulty/combinatorial_formula/cancellation_fee_tier_branch_selection_mode_a
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "LM Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    # 1h ahead -> LAST_MINUTE; est_labor = floor(4000*2.0)=8000 -> floor(8000*0.50)=4000.
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T09:00:00Z",
                                dispatch_mode="SAME_DAY", estimated_hours=2.0)
    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl)), 200)
    c = validate_success(api.get_cancellation(bk["id"], DISP), 200)[0]
    assert c["fee_tier"] == "LAST_MINUTE"
    assert c["cancellation_fee_cents"] == 4000


# ─── non_linear_state_machine ───────────────────────────────────────────────

def test_reschedule_decline_clears_pending_keeps_state(api):
    """PRD §3.6: "Declining likewise requires a pending proposal, clears reschedule_pending, and
    discards the proposed_start."

    Design: Difficulty/non_linear_state_machine/booking_reschedule_cycle_returns_to_same_state
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Decline Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Decl Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T16:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_claimed_booking(cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)
    validate_success(api.propose_reschedule(
        bk["id"], create_propose_payload("2026-06-25T13:00:00Z"), make_client_headers(cl)), 200)
    declined = validate_success(api.decline_reschedule(bk["id"], make_tasker_headers(tk)), 200)
    assert declined["status"] == "CLAIMED"
    assert declined["reschedule_pending"] is False
    assert declined["reschedule_count"] == 0


def test_trust_gate_restricted_band_at_score_65(api):
    """PRD §3.7: "a score from 40 through 69 inclusive sets the tasker `RESTRICTED`".

    Design: Difficulty/non_linear_state_machine/tasker_trust_gate_cycles_active_restricted_suspended
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", TSO))
    tk = get_success_data(api.create_tasker({"full_name": "Band65", "hourly_rate_cents": 5000}, DISP))
    file_incident(tk["id"], severity="HIGH")  # -> 65
    view = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert view["trust_score"] == 65
    assert view["status"] == "RESTRICTED"


# ─── transitive_cascade ─────────────────────────────────────────────────────

def test_non_last_minute_tasker_cancel_no_incident(api):
    """PRD §3.6: "when the cancellation is initiated by the tasker and lands in the `LAST_MINUTE`
    tier, the system files a trust incident of `MEDIUM` severity against that tasker, which in
    turn recomputes the tasker's `trust_score` and re-evaluates the trust gate (§3.7)."

    Design: Difficulty/transitive_cascade/tasker_late_cancel_cascades_to_incident_score_status_depth3
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "NoCascade Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Calm Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-26T09:00:00Z", "2026-06-26T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    # >24h ahead -> FREE tier (not LAST_MINUTE), so a TASKER cancel files no incident.
    bk = create_claimed_booking(cl, ctx["category"]["id"], tk, "2026-06-26T10:00:00Z",
                                estimated_hours=1.0)
    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("TASKER"), make_tasker_headers(tk)), 200)

    incidents = validate_success(api.list_incidents(TSO, params={"tasker_id": tk}), 200)
    assert incidents == []
    tasker = validate_success(api.get_tasker(tk, DISP), 200)
    assert tasker["trust_score"] == 100


def test_uphold_keeps_penalty_applied(api):
    """PRD §3.7: "The officer may uphold an OPEN incident, moving it to UPHELD while its penalty
    stays applied".
    PRD §3.7: "The tasker's incident_penalty_total is the sum of penalty_points across that
    tasker's incidents whose status is OPEN or UPHELD".

    Design: Difficulty/transitive_cascade/incident_dismiss_cascades_to_score_then_status_depth2
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", TSO))
    tk = get_success_data(api.create_tasker({"full_name": "Uphold Tasker", "hourly_rate_cents": 5000}, DISP))
    inc = file_incident(tk["id"], severity="HIGH")
    get_success_data(api.uphold_incident(inc["id"], TSO))
    view = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert view["trust_score"] == 65
    assert view["status"] == "RESTRICTED"


# ─── priority_pair_validation_conflict ──────────────────────────────────────

def test_claim_cancelled_booking_state_error_even_with_active_tasker(api):
    """PRD §2.9: "(5) whether the target resource is in a legal state for the requested
    transition, failing with the relevant invalid-state error".
    PRD §3.3: "Claiming a booking that is not OFFERED is rejected with ERR_BOOKING_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_safety_invalid_state_over_suspended
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "StateOnly Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Active Tasker", "hourly_rate_cents": 5000},
        window=("2026-06-26T09:00:00Z", "2026-06-26T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                                estimated_hours=1.0)
    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl)), 200)
    ver = get_tasker_version(tk)
    res = api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_BOOKING_INVALID_STATE")


def test_claim_suspended_error_when_vetting_also_missing(api):
    """PRD §2.9: "(6) tasker trust and vetting gates, failing with ERR_TASKER_SUSPENDED or
    ERR_VETTING_REQUIRED; (7) temporal rules such as same-day date and not-in-the-past, failing
    with ERR_SAME_DAY_DATE_MISMATCH or ERR_START_IN_PAST; (8) availability-window containment,
    failing with ERR_OUTSIDE_AVAILABILITY".
    PRD §3.3: "The target tasker must not be SUSPENDED — a suspended tasker cannot be claimed
    onto any booking and the attempt fails with ERR_TASKER_SUSPENDED".

    Design: Difficulty/priority_pair_validation_conflict/claim_safety_beats_constraint_suspended_over_outside_availability
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "SafetyWins Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Susp Avail", "hourly_rate_cents": 5000},
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    suspend_tasker(tk)  # safety gate fails (pri 6)
    # No window -> availability would also fail at pri 8; safety wins.
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                                estimated_hours=2.0)
    ver = get_tasker_version(tk)
    res = api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_TASKER_SUSPENDED")


# ─── boundary_precision_check (overlap edge complement) ─────────────────────

def test_overlap_one_minute_before_buffer_edge_conflicts(api):
    """PRD §3.4: "The candidate and an existing booking conflict when the candidate's start is
    earlier than the other booking's end plus the buffer, and simultaneously the other booking's
    start is earlier than the candidate's end plus the buffer."

    Design: Difficulty/boundary_precision_check/booking_overlap_buffer_boundary_exact_edge_admits
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "EdgeMinus Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Edge Minus", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk_a = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                  estimated_hours=1.0)
    claim_booking(bk_a["id"], tk)
    # B starts 11:29, one minute before A.end(11:00)+30min buffer(11:30) -> conflict.
    bk_b = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T11:29:00Z",
                                  estimated_hours=1.0)
    ver = get_tasker_version(tk)
    res = api.claim_booking(bk_b["id"], create_claim_payload(tk, ver), DISP)
    validate_error(res, "ERR_SCHEDULE_CONFLICT")


def test_cancellation_just_under_2h_is_last_minute(api):
    """PRD §3.6: "anything under 2 hours is the `LAST_MINUTE` tier at fifty percent."

    Design: Difficulty/boundary_precision_check/cancellation_24h_boundary_free_vs_just_under_late
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:01:00Z",
        category_overrides={"name": "Under2h Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    # 1h59m ahead -> LAST_MINUTE; est_labor floor(4000*2.0)=8000 -> floor(8000*0.50)=4000.
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                dispatch_mode="SAME_DAY", estimated_hours=2.0)
    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl)), 200)
    c = validate_success(api.get_cancellation(bk["id"], DISP), 200)[0]
    assert c["fee_tier"] == "LAST_MINUTE"
    assert c["cancellation_fee_cents"] == 4000


# ─── cross_entity_state_dependency ──────────────────────────────────────────

def test_claim_succeeds_when_tasker_active_and_available(api):
    """PRD §3.3: "When the claim succeeds, the booking moves to CLAIMED, its tasker_id is set to
    the target tasker".

    Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_tasker_suspended_state
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "ActiveOK Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Active OK", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)
    ver = get_tasker_version(tk)
    claimed = validate_success(api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP), 200)
    assert claimed["status"] == "CLAIMED"
    assert claimed["tasker_id"] == tk


def test_claim_succeeds_once_skill_is_vetted(api):
    """PRD §3.1: "Marking a skill VETTED is only permitted while the skill is still PENDING and
    requires the underlying category to be ACTIVE."
    PRD §3.3: "If the booking's category requires vetting, the tasker must hold a VETTED skill
    for that category, else ERR_VETTING_REQUIRED."

    Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_unvetted_skill_state
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "VettedOK Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": True},
        tasker_overrides={"full_name": "Vetted OK", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    skill = create_skill(tk, ctx["category"]["id"])
    get_success_data(api.vet_skill(skill["id"], TSO))
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)
    ver = get_tasker_version(tk)
    claimed = validate_success(api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP), 200)
    assert claimed["status"] == "CLAIMED"


# ─── resource_temporal_overlap ──────────────────────────────────────────────

def test_non_overlapping_second_booking_claims_cleanly(api):
    """PRD §3.4: "a candidate that starts exactly at another booking's end-plus-buffer does not
    conflict."

    Design: Difficulty/resource_temporal_overlap/booking_vs_booking_buffered_halfopen_conflict
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "NoConflict Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "No Conflict", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T16:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk_a = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                  estimated_hours=1.0)
    claim_booking(bk_a["id"], tk)
    # B at 13:00 is comfortably clear of A's 11:00 end + 30min buffer.
    bk_b = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T13:00:00Z",
                                  estimated_hours=1.0)
    ver = get_tasker_version(tk)
    claimed = validate_success(api.claim_booking(bk_b["id"], create_claim_payload(tk, ver), DISP), 200)
    assert claimed["status"] == "CLAIMED"


def test_booking_end_exactly_at_window_end_admitted(api):
    """PRD §3.4: "A booking whose end exactly meets a window's window_end is allowed".

    Design: Difficulty/resource_temporal_overlap/booking_vs_availability_closed_containment_violation
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "ExactWin Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Exact Win", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T12:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    # 2h booking 10:00-12:00 ends exactly at window_end 12:00 -> admitted (closed edge).
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                estimated_hours=2.0)
    ver = get_tasker_version(tk)
    claimed = validate_success(api.claim_booking(bk["id"], create_claim_payload(tk, ver), DISP), 200)
    assert claimed["status"] == "CLAIMED"


# ─── compensating_invariant ─────────────────────────────────────────────────

def test_claim_bumps_active_count_to_one(api):
    """PRD §3.3: "the tasker's active_booking_count is recomputed upward to reflect the newly
    held job."

    Design: Difficulty/compensating_invariant/claim_then_cancel_conserves_tasker_active_booking_count
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "BumpCount Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Bump Count", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    before = validate_success(api.get_tasker(tk, DISP), 200)
    assert before["active_booking_count"] == 0
    create_claimed_booking(cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z",
                           estimated_hours=1.0)
    after = validate_success(api.get_tasker(tk, DISP), 200)
    assert after["active_booking_count"] == 1


def test_uphold_then_dismiss_restores_trust_score(api):
    """PRD §3.7: "dismiss it from OPEN (or on a granted appeal from UPHELD), moving it to
    DISMISSED and setting its penalty_points to zero so the penalty is removed."
    PRD §3.7: "The trust_score is 100 minus that penalty total, floored at 0 so it never goes
    below zero."

    Design: Difficulty/compensating_invariant/file_then_dismiss_incident_conserves_tasker_trust_score
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", TSO))
    tk = get_success_data(api.create_tasker({"full_name": "Appeal Tasker", "hourly_rate_cents": 5000}, DISP))
    inc = file_incident(tk["id"], severity="MEDIUM")
    get_success_data(api.uphold_incident(inc["id"], TSO))
    upheld = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert upheld["trust_score"] == 85

    get_success_data(api.dismiss_incident(inc["id"], TSO))
    restored = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert restored["trust_score"] == 100
