"""Attendance and hour verification: claimed vs supervisor-attested hours, the parallel
attendance/verification axes, round-per-session-then-sum, and the exact-equality
completion boundary.

Covers Difficulty queue: dual_variant_calc (session), non_linear_state_machine (parallel
axes), combinatorial_formula (hours_completed), boundary_precision_check (exact hours).
Covers Corner queue: several verification-path validations.
"""
from test_helpers import (
    validate_success, validate_error,
    make_supervisor_headers,
    TEST_USERS,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# ============================ Difficulty: claimed vs supervisor-attested hours
def test_supervisor_attested_hours_below_claimed(api):
    """PRD §3.5: "The credited `verified_hours` is the grid-snapped `attested_hours` when supplied, and
    otherwise equals `claimed_hours` outright; the two approaches deliberately diverge for
    the same session, since a supervisor attestation lands strictly below the participant's
    clock-derived claim."

    Design: Difficulty/dual_variant_calc/dv_session_claimed_vs_supervisor_verified
    """
    s = fx.active_placement_scenario(court_case_number="CR-1")
    ws = fx.checked_out_session(s, "2026-06-01T09:00:00Z", "2026-06-01T12:15:00Z")
    assert ws["claimed_hours"] == 3.25
    verified = fx.verify_session(ws["id"], s["supervisor_id"],
                                 outcome="VERIFIED", attested=3.00)
    assert verified["verified_hours"] == 3.00
    assert verified["verified_hours"] < verified["claimed_hours"]


def test_self_reported_hours_equal_claimed_when_no_attestation(api):
    """PRD §3.5: "The credited `verified_hours` is the grid-snapped `attested_hours` when supplied, and
    otherwise equals `claimed_hours` outright".

    Design: Difficulty/dual_variant_calc/dv_session_claimed_vs_supervisor_verified
    """
    s = fx.active_placement_scenario(court_case_number="CR-1B")
    ws = fx.checked_out_session(s, "2026-06-01T09:00:00Z", "2026-06-01T12:15:00Z")
    assert ws["claimed_hours"] == 3.25
    verified = fx.verify_session(ws["id"], s["supervisor_id"], outcome="VERIFIED")
    assert verified["verified_hours"] == 3.25
    assert verified["verified_hours"] == verified["claimed_hours"]


# ============================ Difficulty: parallel attendance / verification axes
def test_dispute_leaves_attendance_completed(api):
    """PRD §3.5: "Verification is a separate axis that evolves independently of attendance; a session stays in
    attendance `COMPLETED` throughout."
    PRD §3.5: "**`DISPUTED`** is allowed only from `verification_status` `PENDING` (else
    `ERR_INVALID_STATE`). It sets `verification_status` to `DISPUTED` and credits no hours."

    Design: Difficulty/non_linear_state_machine/nlsm_worksession_parallel_attendance_and_verification_axes
    """
    s = fx.active_placement_scenario(court_case_number="CR-6")
    ws = fx.checked_out_session(s, "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
    disputed = fx.verify_session(ws["id"], s["supervisor_id"], outcome="DISPUTED")
    assert disputed["attendance_status"] == "COMPLETED"
    assert disputed["verification_status"] == "DISPUTED"


def test_reject_after_dispute_keeps_attendance_completed(api):
    """PRD §3.5: "**`REJECTED`** is allowed from `verification_status` `PENDING` or `DISPUTED` (else
    `ERR_INVALID_STATE`). It sets `verification_status` to `REJECTED` and credits no hours."
    PRD §3.5: "a session stays in attendance `COMPLETED` throughout."

    Design: Difficulty/non_linear_state_machine/nlsm_worksession_parallel_attendance_and_verification_axes
    """
    s = fx.active_placement_scenario(court_case_number="CR-6B")
    ws = fx.checked_out_session(s, "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
    fx.verify_session(ws["id"], s["supervisor_id"], outcome="DISPUTED")
    rejected = fx.verify_session(ws["id"], s["supervisor_id"], outcome="REJECTED")
    assert rejected["attendance_status"] == "COMPLETED"
    assert rejected["verification_status"] == "REJECTED"


# ============================ Difficulty: round-per-session-then-sum
def test_hours_completed_rounds_each_session_then_sums(api):
    """PRD §3.5: "Each session's `verified_hours` is already snapped to the quarter-hour grid; the sum is
    taken over those already-rounded per-session values and is not re-rounded. The order is
    fixed: round each session, then sum — never sum raw durations and round the total."

    Design: Difficulty/combinatorial_formula/cf_hours_completed_round_per_session_then_sum
    """
    s = fx.active_placement_scenario(hours_ordered=10, court_case_number="CR-4")
    ws1 = fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T10:52:00Z")
    ws2 = fx.completed_session(s, "2026-06-02T09:00:00Z", "2026-06-02T10:52:00Z")
    assert ws1["verified_hours"] == 1.75
    assert ws2["verified_hours"] == 1.75
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert ref["hours_completed"] == 3.50


def test_single_session_credit_rounds_to_grid(api):
    """PRD §3.5: "The referral's `hours_completed` is, at all times, the sum of `verified_hours` across that
    referral's sessions that are `VERIFIED` and not `VOIDED`."
    PRD §2.6: "snapping to the nearest 0.25 boundary with ties going upward."

    Design: Difficulty/combinatorial_formula/cf_hours_completed_round_per_session_then_sum
    """
    s = fx.active_placement_scenario(hours_ordered=10, court_case_number="CR-4B")
    ws = fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T10:52:00Z")
    assert ws["verified_hours"] == 1.75
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert ref["hours_completed"] == 1.75


# ============================ Difficulty: exact-equality completion boundary
def test_exact_hours_equality_completes_referral(api):
    """PRD §3.5: "If, after crediting, the referral's `hours_completed` is at least its `hours_ordered` (the
    boundary is inclusive — exact equality completes) and `hours_outstanding` has reached 0,
    the referral automatically completes".

    Design: Difficulty/boundary_precision_check/bpc_exact_hours_equality_completes_referral
    """
    s = fx.active_placement_scenario(hours_ordered=5.00, court_case_number="CR-11")
    fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T14:00:00Z")
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert ref["hours_completed"] == 5.00
    assert ref["hours_outstanding"] == 0
    assert ref["status"] == "COMPLETED"


def test_just_below_ordered_does_not_complete(api):
    """PRD §3.5: "If, after crediting, the referral's `hours_completed` is at least its `hours_ordered` (the
    boundary is inclusive — exact equality completes) and `hours_outstanding` has reached 0,
    the referral automatically completes".

    Design: Difficulty/boundary_precision_check/bpc_exact_hours_equality_completes_referral
    """
    s = fx.active_placement_scenario(hours_ordered=5.00, court_case_number="CR-11B")
    fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T13:45:00Z")  # 4.75h
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert ref["hours_completed"] == 4.75
    assert ref["hours_outstanding"] == 0.25
    assert ref["status"] == "ACTIVE"


# ============================ Corner: verification-path validations
def test_verify_before_checkout_returns_invalid_state(api):
    """PRD §3.5: "**`VERIFIED`** credits the referral. It is allowed only when attendance is `COMPLETED` (else
    `ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/state_machines/verify_before_checkout_returns_invalid_state
    """
    s = fx.active_placement_scenario(court_case_number="CR-D4")
    ws = fx.new_session(s["placement_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    res = api.verify_work_session(ws["id"], {"outcome": "VERIFIED"},
                                  make_supervisor_headers(s["supervisor_id"]))
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_double_checkin_second_returns_invalid_state(api):
    """PRD §3.5: "Checking in advances a session from `SCHEDULED` to `CHECKED_IN`".
    PRD §2.9: "the generic state check that a resource admits the requested transition, else
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/double_checkin_second_returns_invalid_state
    """
    s = fx.active_placement_scenario(court_case_number="CR-D5")
    ws = fx.new_session(s["placement_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    fx.check_in(ws["id"], s["supervisor_id"], "2026-06-05T09:00:00Z")
    res = api.check_in(ws["id"], make_supervisor_headers(s["supervisor_id"]),
                       {"check_in_at": "2026-06-05T09:05:00Z"})
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_verify_attested_hours_exceed_claimed_rejected(api):
    """PRD §3.5: "that value must be on the quarter-hour grid and must not exceed `claimed_hours` — an
    over-attestation is refused with `ERR_VERIFIED_HOURS_EXCEED_CLAIMED` (HTTP 422)."

    Design: Corner/validations/verify_attested_hours_exceed_claimed_rejected
    """
    s = fx.active_placement_scenario(court_case_number="CR-D8")
    ws = fx.checked_out_session(s, "2026-06-05T09:00:00Z", "2026-06-05T12:00:00Z")  # 3.00
    res = api.verify_work_session(ws["id"], {"outcome": "VERIFIED", "attested_hours": 4.00},
                                  make_supervisor_headers(s["supervisor_id"]))
    validate_error(res, "ERR_VERIFIED_HOURS_EXCEED_CLAIMED", 422)


def test_checkout_before_checkin_rejected(api):
    """PRD §3.5: "The supplied (or defaulted) `check_out_at` must be strictly after `check_in_at`; otherwise
    the check-out is refused with `ERR_CHECKOUT_BEFORE_CHECKIN` (HTTP 422)."

    Design: Corner/validations/checkout_before_checkin_rejected
    """
    s = fx.active_placement_scenario(court_case_number="CR-D9")
    ws = fx.new_session(s["placement_id"], "2026-06-05T09:00:00Z", "2026-06-05T12:00:00Z")
    fx.check_in(ws["id"], s["supervisor_id"], "2026-06-05T10:00:00Z")
    res = api.check_out(ws["id"], make_supervisor_headers(s["supervisor_id"]),
                        {"check_out_at": "2026-06-05T09:00:00Z"})
    validate_error(res, "ERR_CHECKOUT_BEFORE_CHECKIN", 422)
