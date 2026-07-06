"""Fixed-priority validation ordering: which of two live violations wins."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS,
    set_clock, make_complaint, make_officer, make_pending_dispatch,
    accept_dispatch, clear_dispatch,
    investigating_case, issue_citation, make_quarantine_hold,
    create_dispatch_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ==========================================================================
# Difficulty: priority_pair_validation_conflict / referential_beats_temporal_on_dispatch_create
# ==========================================================================
def _setup_resolved_complaint_with_busy_officer(api):
    set_clock(api, "2026-03-01T00:00:00Z")
    c1 = make_complaint(api, reporter_name="C1", complaint_type="STRAY")
    c2 = make_complaint(api, reporter_name="C2", complaint_type="STRAY")
    officer = make_officer(api, name="Ofc O", badge_number="B8")
    d2 = make_pending_dispatch(api, c2["id"], officer["id"],
                               scheduled_start_at="2026-03-01T09:00:00Z", scheduled_end_at="2026-03-01T10:00:00Z")
    accept_dispatch(api, d2["id"], officer["id"])  # officer now EN_ROUTE on 09:00-10:00
    d1 = make_pending_dispatch(api, c1["id"], officer["id"],
                               scheduled_start_at="2026-03-01T14:00:00Z", scheduled_end_at="2026-03-01T15:00:00Z")
    accept_dispatch(api, d1["id"], officer["id"])
    clear_dispatch(api, d1["id"], officer["id"], "RESOLVED_ON_SCENE")  # c1 -> RESOLVED
    return c1, officer


def test_complaint_not_dispatchable_beats_schedule_conflict(api):
    """PRD 2.6: "The target must be in a state from which the requested
    transition is legal — otherwise ERR_INVALID_STATE, or the more specific
    ERR_COMPLAINT_NOT_DISPATCHABLE or ERR_CITATION_ALREADY_RESOLVED, all 409."
    PRD 2.6: "Officer schedule conflicts and kennel occupancy conflicts —
    ERR_OFFICER_SCHEDULE_CONFLICT or ERR_KENNEL_OCCUPIED, both 409." PRD 2.6:
    "This ordering is a contract: a lower-priority violation must never mask a
    higher-priority one."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_dispatch_create
    """
    c1, officer = _setup_resolved_complaint_with_busy_officer(api)
    # 09:30-09:45 genuinely overlaps the officer's EN_ROUTE 09:00-10:00 window,
    # AND c1 is RESOLVED (not NEW). The state/eligibility error must surface first.
    resp = api.create_dispatch(create_dispatch_payload(
        c1["id"], officer["id"],
        scheduled_start_at="2026-03-01T09:30:00Z", scheduled_end_at="2026-03-01T09:45:00Z"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_DISPATCHABLE)


def test_dispatchable_conflict_leaves_complaint_resolved(api):
    """PRD 3.2: "The complaint must be in status NEW; a dispatch against a
    complaint in any other status is rejected with ERR_COMPLAINT_NOT_DISPATCHABLE."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_dispatch_create
    """
    c1, officer = _setup_resolved_complaint_with_busy_officer(api)
    resp = api.create_dispatch(create_dispatch_payload(
        c1["id"], officer["id"],
        scheduled_start_at="2026-03-01T09:30:00Z", scheduled_end_at="2026-03-01T09:45:00Z"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_DISPATCHABLE)
    assert validate_success(api.get_complaint(c1["id"], DISPATCHER))["status"] == "RESOLVED"


# ==========================================================================
# Difficulty: priority_pair_validation_conflict / safety_beats_fiscal_on_case_close
# ==========================================================================
def _setup_substantiated_case_with_hold_and_citation(api):
    ctx = investigating_case(api, case_type="BITE", complaint_overrides={"complaint_type": "BITE"})
    issue_citation(api, ctx["case"]["id"], violation_code="LEASH",
                   issued_to_name="Owner K", issued_to_ref="OWNER-1")
    make_quarantine_hold(api, ctx["case"]["id"], hold_type="HOME_QUARANTINE")
    validate_success(api.resolve_case(ctx["case"]["id"], {"resolution": "SUBSTANTIATED"}, SUPERVISOR))
    return ctx


def test_active_hold_beats_outstanding_citation_on_close(api):
    """PRD 3.8: "Per the validation ordering of Section 2.6, the active-hold and
    held-impound safety checks are evaluated ahead of the outstanding-citation
    fiscal check." PRD 3.8: "The case may not close while any quarantine hold on
    it is still ACTIVE (ERR_ACTIVE_QUARANTINE_HOLD)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_case_close
    """
    ctx = _setup_substantiated_case_with_hold_and_citation(api)
    resp = api.close_case(ctx["case"]["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_QUARANTINE_HOLD)


def test_safety_blocked_close_leaves_case_substantiated(api):
    """PRD 3.8: "it may not close while any citation on it remains in ISSUED
    (ERR_OUTSTANDING_CITATIONS). Per the validation ordering of Section 2.6, the
    active-hold and held-impound safety checks are evaluated ahead of the
    outstanding-citation fiscal check."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_case_close
    """
    ctx = _setup_substantiated_case_with_hold_and_citation(api)
    validate_error(api.close_case(ctx["case"]["id"], SUPERVISOR), ApiErrorId.ERR_ACTIVE_QUARANTINE_HOLD)
    assert validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR))["status"] == "SUBSTANTIATED"
