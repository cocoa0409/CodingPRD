"""Violation state machine, appeal window / SAFETY exception, and validation
priority precedence."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
    api_client,
    setup_homeowner_and_property,
    setup_fined_violation,
    setup_paid_assessment,
    set_clock,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]
_COMPLIANCE = TEST_USERS["compliance_headers"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict / state_vs_fiscal_pay_terminal
# ===========================================================================
def test_paid_terminal_state_beats_overpayment(api):
    """PRD §2.8: "The ordering is significant: a request that would trip
    checks 5 and 14 surfaces the state error (`ERR_INVALID_STATE`), not the
    fiscal one."
    PRD §2.8 (priority 5): "State precondition — the target resource must be
    in a state that permits the requested transition (see §3 for per-entity
    state machines); otherwise `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.8 (priority 14): "Business fiscal (overpayment) — a payment's
    `amount_cents` may not push cumulative paid above the current outstanding;
    otherwise `ERR_OVERPAYMENT` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_pay_terminal_wins_state
    """
    homeowner, prop, assessment, payment = setup_paid_assessment(
        email="hprio@ex.com",
        address="9 Prio Ln",
        monthly_dues_cents=30000,
        due_date="2026-04-15T00:00:00Z",
    )
    # Assessment is now PAID and clock is still 2026-03-01 (before due_date).
    resp = api.pay_assessment(
        assessment["id"],
        {"amount_cents": 99999, "method": "MANUAL"},
        make_homeowner_headers(homeowner["id"]),
    )
    err_data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err_data["error_id"] != "ERR_OVERPAYMENT"


# ===========================================================================
# Queue A — priority_pair_validation_conflict / constraint_vs_temporal_appeal_safety
# ===========================================================================
def test_appeal_safety_wins_over_expired_window(api):
    """PRD §2.8: "The ordering is significant"
    PRD §2.8 (priority 13): "Business constraint (appeal category) — a
    `Violation` with `category` equal to `SAFETY` may not be appealed;
    otherwise `ERR_APPEAL_NON_APPEALABLE` (HTTP 422)."
    PRD §2.8 (priority 17): "Business temporal (appeal window) — a violation
    appeal is accepted only while the current server time is at or before
    `fined_at` plus 14 days; otherwise `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422)."
    PRD §3.5: "In addition, a violation with `category` equal to `SAFETY` is
    non-appealable at any point — safety fines never enter the appeal branch,
    and any attempt to appeal one is rejected with `ERR_APPEAL_NON_APPEALABLE`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_vs_temporal_appeal_safety_wins_constraint
    """
    homeowner, prop, violation = setup_fined_violation(
        homeowner_email="hsaf@ex.com",
        address="10 Safety Ln",
        category="SAFETY",
        fine_amount_cents=25000,
        fine_at_iso="2026-03-05T00:00:00Z",
    )
    set_clock("2026-04-01T00:00:00Z")  # 27 days after fined_at
    resp = api.appeal_violation(
        violation["id"], make_homeowner_headers(homeowner["id"])
    )
    # ERROR-PRECEDENCE relaxation. At 27 days past fined_at the FINED violation has
    # already auto-transitioned to the terminal UPHELD state (PRD §3.5: "When the
    # logical clock advances strictly past fined_at plus 14 days on a violation still
    # in FINED, the server auto-transitions it to the terminal UPHELD state"). An appeal
    # then trips the higher-priority state precondition (PRD §2.8 check 5 →
    # ERR_INVALID_STATE) before the SAFETY appeal-category check (check 13). Because the
    # auto-uphold threshold and the appeal-window expiry coincide exactly, no
    # PRD-faithful eager implementation can surface ERR_APPEAL_NON_APPEALABLE past the
    # window; ERR_INVALID_STATE is the reasonable serialization. Either is accepted; the
    # point preserved is that the window-expiry code (check 17) never wins here.
    actual = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_APPEAL_NON_APPEALABLE, ApiErrorId.ERR_INVALID_STATE]
    )
    assert actual != "ERR_APPEAL_WINDOW_EXPIRED"


# ===========================================================================
# Queue B — state_machines / violation_upheld_after_appeal_window_expired
# ===========================================================================
def test_violation_auto_transitions_to_upheld_after_14_days(api):
    """PRD §3.5: "When the logical clock advances strictly past `fined_at`
    plus 14 days on a violation still in `FINED`, the server auto-transitions
    it to the terminal `UPHELD` state — the fine is now final without an
    appeal ever having been lodged."

    Design: Corner/state_machines/violation_upheld_after_appeal_window_expired
    """
    _, _, violation = setup_fined_violation(
        homeowner_email="hup@ex.com",
        address="25 Up Ln",
        category="LANDSCAPE",
        fine_amount_cents=15000,
        fine_at_iso="2026-03-05T00:00:00Z",
    )
    set_clock("2026-03-25T00:00:00Z")  # 20 days later → > 14 days
    resp = api.get_violation(violation["id"], _COMPLIANCE)
    data = validate_success(resp)
    assert data["status"] == "UPHELD"


# ===========================================================================
# Queue B — validations / appeal_non_safety_within_window
# ===========================================================================
def test_non_safety_violation_within_window_appealable(api):
    """PRD §3.5: "A homeowner may appeal a `FINED` violation, moving it to
    `APPEALED`, only within a 14-day window: the appeal succeeds only while
    the current server clock is at or before `fined_at` plus 14 days"

    Design: Corner/validations/appeal_non_safety_within_window
    """
    homeowner, _, violation = setup_fined_violation(
        homeowner_email="hap@ex.com",
        address="31 Ap Ln",
        category="NUISANCE",
        fine_amount_cents=15000,
        fine_at_iso="2026-03-05T00:00:00Z",
    )
    set_clock("2026-03-08T00:00:00Z")  # 3 days after fined_at
    resp = api.appeal_violation(
        violation["id"], make_homeowner_headers(homeowner["id"])
    )
    data = validate_success(resp)
    assert data["status"] == "APPEALED"


# ===========================================================================
# Queue B — errors / appeal_window_expired_error
# ===========================================================================
def test_appeal_after_window_returns_expired(api):
    """PRD §3.5: "an appeal after that expiry is rejected with
    `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/errors/appeal_window_expired_error
    """
    homeowner, _, violation = setup_fined_violation(
        homeowner_email="haw@ex.com",
        address="33 AW Ln",
        category="NUISANCE",
        fine_amount_cents=15000,
        fine_at_iso="2026-03-05T00:00:00Z",
    )
    set_clock("2026-03-25T00:00:00Z")  # 20 days after fined_at
    resp = api.appeal_violation(
        violation["id"], make_homeowner_headers(homeowner["id"])
    )
    # ERROR-PRECEDENCE relaxation. Advancing the clock 20 days past fined_at fires the
    # PRD §3.5 auto-transition FINED -> UPHELD (strictly past fined_at + 14 days) as part
    # of the set_current_utc request. The subsequent appeal therefore hits the
    # higher-priority state precondition (PRD §2.8 check 5 → ERR_INVALID_STATE) rather
    # than the appeal-window check (check 17 → ERR_APPEAL_WINDOW_EXPIRED). The auto-uphold
    # threshold and the window expiry are the same instant, so a faithful eager
    # implementation returns ERR_INVALID_STATE; both outcomes reject the late appeal.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, ApiErrorId.ERR_INVALID_STATE]
    )


# ===========================================================================
# Queue B — validations / overpayment_rejected
# ===========================================================================
def test_overpayment_on_open_assessment_returns_error(api):
    """PRD §3.2: "Payment where the sum would exceed the full outstanding is
    rejected with `ERR_OVERPAYMENT`."

    Design: Corner/validations/overpayment_rejected
    """
    homeowner, prop = setup_homeowner_and_property(
        email="hop@ex.com", address="30 OP Ln", monthly_dues_cents=30000
    )
    resp = api.create_assessment(
        {"property_id": prop["id"],
         "billing_period_start": "2026-03-01T00:00:00Z",
         "billing_period_end": "2026-04-01T00:00:00Z",
         "due_date": "2026-04-15T00:00:00Z"},
        _MANAGER,
    )
    assessment = validate_success(resp, expected_status=201)
    resp = api.pay_assessment(
        assessment["id"],
        {"amount_cents": 99999, "method": "MANUAL"},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)
