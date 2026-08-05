"""Dispute lifecycle, hearing scheduling, officer overlap, collectible conservation,
dispute window, one-dispute-per-lifetime, and collections age gate.

Covers difficulty rules non_linear_state_machine (violation_dispute_reinstate_cycle),
cross_entity_state_dependency (schedule_requires_violation_disputed),
resource_temporal_overlap (officer_double_booked_halfopen),
compensating_invariant (collectible_conserved_dispute_dismiss),
plus corner validations (dispute window, second dispute, collections age).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_case_with_violations, setup_case_with_scheduled_dispute,
    file_violation, file_dispute, create_hearing_officer, schedule_dispute,
    get_case, set_clock, make_owner_headers,
)

EO = TEST_USERS["enforcement_officer_headers"]
CLERK = TEST_USERS["hearing_clerk_headers"]
COLLECTIONS = TEST_USERS["collections_admin_headers"]


# ─── non_linear_state_machine / violation_dispute_reinstate_cycle ──────────

def _dispute_then_withdraw(api):
    owner, _, case, violations = setup_case_with_violations(1, 40000, violation_type="NO_PERMIT")
    violation = violations[0]
    dispute = file_dispute(violation["id"], owner["id"])
    withdrawn = validate_success(
        api.withdraw_dispute(dispute["id"], make_owner_headers(owner["id"])), 200)
    return violation, dispute, withdrawn


def test_withdraw_returns_violation_to_outstanding(api):
    """PRD §3.3: "the owner may withdraw their own dispute while it is SUBMITTED or
    SCHEDULED; withdrawal moves the dispute to WITHDRAWN, reinstates the citation
    DISPUTED → OUTSTANDING, recomputes the balances (collectible restored), and increments
    the case's version."

    Design: Difficulty/non_linear_state_machine/violation_dispute_reinstate_cycle
    """
    violation, _, _ = _dispute_then_withdraw(api)
    fresh = validate_success(api.get_violation(violation["id"], EO), 200)
    assert fresh["status"] == "OUTSTANDING"


def test_withdraw_marks_dispute_withdrawn(api):
    """PRD §3.3: "withdrawal moves the dispute to WITHDRAWN, reinstates the citation
    DISPUTED → OUTSTANDING, recomputes the balances (collectible restored), and increments
    the case's version."

    Design: Difficulty/non_linear_state_machine/violation_dispute_reinstate_cycle
    """
    _, _, withdrawn = _dispute_then_withdraw(api)
    assert withdrawn["status"] == "WITHDRAWN"


# ─── cross_entity_state_dependency / schedule_requires_violation_disputed ──

def _submitted_dispute(api):
    owner, _, case, violations = setup_case_with_violations(1, 15000, violation_type="NO_PERMIT")
    violation = violations[0]
    officer = create_hearing_officer(full_name="Judge Judy")
    dispute = file_dispute(violation["id"], owner["id"])
    return violation, officer, dispute


def test_schedule_succeeds_while_violation_disputed(api):
    """PRD §3.3: "Scheduling requires the dispute to be SUBMITTED and the linked violation
    to still be DISPUTED (a cross-entity check; failure is ERR_INVALID_STATE, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_violation_disputed
    """
    violation, officer, dispute = _submitted_dispute(api)
    scheduled = validate_success(api.schedule_dispute(
        dispute["id"],
        {"officer_id": officer["id"], "scheduled_start": "2026-05-20T10:00:00Z",
         "scheduled_end": "2026-05-20T11:00:00Z"}, CLERK), 200)
    assert scheduled["status"] == "SCHEDULED"


def test_schedule_assigns_officer_and_keeps_violation_disputed(api):
    """PRD §3.3: "A successful schedule sets officer_id, scheduled_start, and scheduled_end
    and moves the dispute SUBMITTED → SCHEDULED."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_violation_disputed
    """
    violation, officer, dispute = _submitted_dispute(api)
    scheduled = validate_success(api.schedule_dispute(
        dispute["id"],
        {"officer_id": officer["id"], "scheduled_start": "2026-05-20T10:00:00Z",
         "scheduled_end": "2026-05-20T11:00:00Z"}, CLERK), 200)
    assert scheduled["officer_id"] == officer["id"]
    assert validate_success(api.get_violation(violation["id"], EO), 200)["status"] == "DISPUTED"


# ─── resource_temporal_overlap / officer_double_booked_halfopen ────────────

def _officer_with_first_hearing(api):
    owner, _, case, violations = setup_case_with_violations(2, 10000)
    officer = create_hearing_officer(full_name="Officer One")
    d1 = file_dispute(violations[0]["id"], owner["id"])
    d2 = file_dispute(violations[1]["id"], owner["id"])
    schedule_dispute(d1["id"], officer["id"], "2026-05-20T10:00:00Z", "2026-05-20T11:00:00Z")
    return officer, d2


def test_overlapping_hearing_rejected(api):
    """PRD §3.3: "the new window may not overlap any other SCHEDULED dispute already
    assigned to that officer, where overlap is judged on the half-open interval from
    scheduled_start up to but not including scheduled_end, so two hearings that merely
    touch end-to-start are allowed; a genuine overlap is rejected with
    ERR_OFFICER_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/officer_double_booked_halfopen
    """
    officer, d2 = _officer_with_first_hearing(api)
    res = api.schedule_dispute(
        d2["id"],
        {"officer_id": officer["id"], "scheduled_start": "2026-05-20T10:30:00Z",
         "scheduled_end": "2026-05-20T11:30:00Z"}, CLERK)
    validate_error(res, "ERR_OFFICER_DOUBLE_BOOKED", expected_status=409)


def test_adjacent_hearing_end_to_start_allowed(api):
    """PRD §3.3: "overlap is judged on the half-open interval from scheduled_start up to
    but not including scheduled_end, so two hearings that merely touch end-to-start are
    allowed;"

    Design: Difficulty/resource_temporal_overlap/officer_double_booked_halfopen
    """
    officer, d2 = _officer_with_first_hearing(api)
    scheduled = validate_success(api.schedule_dispute(
        d2["id"],
        {"officer_id": officer["id"], "scheduled_start": "2026-05-20T11:00:00Z",
         "scheduled_end": "2026-05-20T12:00:00Z"}, CLERK), 200)
    assert scheduled["status"] == "SCHEDULED"


# ─── compensating_invariant / collectible_conserved_dispute_dismiss ────────

def test_collectible_dropped_while_disputed(api):
    """PRD §3.3: "Filing a dispute creates a Dispute in SUBMITTED status, moves the
    violation OUTSTANDING → DISPUTED, and recomputes the case balances — the violation's
    current due drops out of the collectible view (see §3.4), which can de-escalate the
    case out of SCOFFLAW and cancel any still-pending enforcement order."

    Design: Difficulty/compensating_invariant/collectible_conserved_dispute_dismiss
    """
    # After dispute is filed (and scheduled), the 30000 citation is out of collectible.
    _, _, case, _, _, _ = setup_case_with_scheduled_dispute(fine=30000)
    assert get_case(case["id"])["collectible_balance_cents"] == 0


def test_dismiss_restores_collectible_balance(api):
    """PRD §3.3: "A DISMISSED decision sets decided_at, moves the dispute to DISMISSED,
    reinstates the citation (DISPUTED → OUTSTANDING), and recomputes the balances,
    restoring the citation's collectible amount."

    Design: Difficulty/compensating_invariant/collectible_conserved_dispute_dismiss
    """
    _, _, case, violation, _, dispute = setup_case_with_scheduled_dispute(fine=30000)
    validate_success(api.decide_dispute(dispute["id"], {"decision": "DISMISSED"}, CLERK), 200)
    assert validate_success(api.get_violation(violation["id"], EO), 200)["status"] == "OUTSTANDING"
    assert get_case(case["id"])["collectible_balance_cents"] == 30000


# ─── corner: dispute after window ──────────────────────────────────────────

def test_dispute_after_window_rejected(api):
    """PRD §3.3: "only while the logical clock is within DISPUTE_WINDOW_DAYS (21) days of
    the citation's issued_at"
    PRD §3.3: "A dispute filed after the window has closed is rejected with
    ERR_DISPUTE_WINDOW_EXPIRED (HTTP 422)."

    Design: Corner/validations/dispute_after_window_returns_422
    """
    owner, _, case, violations = setup_case_with_violations(
        1, 15000, violation_type="NO_PERMIT")
    set_clock("2026-06-01T00:00:00Z")  # 31 days after 2026-05-01 issued_at
    res = api.create_dispute(
        violations[0]["id"], {"reason": "too late"}, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_DISPUTE_WINDOW_EXPIRED", expected_status=422)


# ─── corner: second dispute after terminal ─────────────────────────────────

def test_second_dispute_after_withdrawal_rejected(api):
    """PRD §3.3: "only if no dispute has ever existed for that violation in any status — a
    violation may be disputed at most once in its lifetime."
    PRD §3.3: "ERR_DISPUTE_ALREADY_EXISTS (HTTP 409) becomes reachable only after a prior
    dispute has reached a terminal outcome and the violation has returned to OUTSTANDING."

    Design: Corner/validations/second_dispute_after_terminal_rejected
    """
    owner, _, case, violations = setup_case_with_violations(
        1, 15000, violation_type="NO_PERMIT")
    dispute = file_dispute(violations[0]["id"], owner["id"])
    validate_success(api.withdraw_dispute(dispute["id"], make_owner_headers(owner["id"])), 200)
    res = api.create_dispute(
        violations[0]["id"], {"reason": "second"}, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_DISPUTE_ALREADY_EXISTS", expected_status=409)


# ─── corner: collections referral before minimum age ───────────────────────

def test_collections_referral_before_min_age_rejected(api):
    """PRD §3.9: "Referral requires the case to be SCOFFLAW, requires the case's oldest
    OUTSTANDING citation to be at least COLLECTIONS_MIN_AGE_DAYS (90) days old as measured
    against the logical clock (otherwise ERR_NOT_YET_REFERABLE, HTTP 422)"

    Design: Corner/validations/collections_before_age_returns_422
    """
    _, _, case, _ = setup_case_with_violations(5, 12000)  # SCOFFLAW
    set_clock("2026-05-15T00:00:00Z")  # oldest citation only 14 days old
    res = api.create_collections_referral(
        case["id"], {"agency_name": "Early Agency"}, COLLECTIONS)
    validate_error(res, "ERR_NOT_YET_REFERABLE", expected_status=422)
