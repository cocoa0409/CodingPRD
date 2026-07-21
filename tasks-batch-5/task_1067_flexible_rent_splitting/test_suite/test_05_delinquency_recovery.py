"""Delinquency assessment, late fees, payoff figures, recovery workflow, and charge-off."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, create_delinquent_case, open_outreach_case,
    charge_installment, find_ledger_entry,
    make_agent_headers, make_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / assess_delinquency_cascade_cycle_case_ledger_reminder
# ---------------------------------------------------------------------------

def test_assess_delinquency_cascades_cycle_and_case(api):
    """PRD §3.8: "the cycle moves `REMITTED → DELINQUENT`. This opens a delinquency case in
    `OPEN`".
    PRD §3.8: "When that count reaches at least 5 days — the grace period — the flat late
    fee of 2500 cents is applied: a `LATE_FEE` ledger entry of 2500 is appended and the
    case's `accrued_late_fee_cents` is set to 2500."

    Design: Difficulty/transitive_cascade/assess_delinquency_cascade_cycle_case_ledger_reminder
    """
    ctx = create_delinquent_case(api, pay_first_installment=False,
                                 assess_clock="2026-07-21T00:00:00Z")
    cycle = validate_success(api.get_billing_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "DELINQUENT"
    case = validate_success(api.get_delinquency_case(ctx["case"]["id"], ADMIN))
    assert case["status"] == "OPEN"
    assert case["accrued_late_fee_cents"] == 2500


def test_assess_delinquency_cascades_ledger_and_reminder(api):
    """PRD §3.8: "a `LATE_FEE` ledger entry of 2500 is appended and the case's
    `accrued_late_fee_cents` is set to 2500."
    PRD §3.8: "The assessment also emits an `OVERDUE` reminder for the renter."

    Design: Difficulty/transitive_cascade/assess_delinquency_cascade_cycle_case_ledger_reminder
    """
    ctx = create_delinquent_case(api, pay_first_installment=False,
                                 assess_clock="2026-07-21T00:00:00Z")
    ledger = validate_success(api.list_cycle_ledger(ctx["cycle"]["id"], ADMIN))
    assert find_ledger_entry(ledger, "LATE_FEE", 2500) is not None
    reminders = validate_success(api.list_cycle_reminders(ctx["cycle"]["id"], ADMIN))
    assert any(r["kind"] == "OVERDUE" for r in reminders)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / late_fee_grace_days_ge_boundary
# ---------------------------------------------------------------------------

def test_late_fee_applied_at_grace_boundary(api):
    """PRD §3.8: "When that count reaches at least 5 days — the grace period — the flat late
    fee of 2500 cents is applied: a `LATE_FEE` ledger entry of 2500 is appended and the
    case's `accrued_late_fee_cents` is set to 2500. On the fourth overdue day no flat fee
    applies; on the fifth it does."

    Design: Difficulty/boundary_precision_check/late_fee_grace_days_ge_boundary
    """
    ctx = create_delinquent_case(api, pay_first_installment=False,
                                 assess_clock="2026-07-06T00:00:00Z")  # exactly 5 days overdue
    case = validate_success(api.get_delinquency_case(ctx["case"]["id"], ADMIN))
    assert case["accrued_late_fee_cents"] == 2500


def test_cycle_delinquent_at_grace_boundary(api):
    """PRD §3.8: "When at least one of the cycle's installments is past its `due_date` (the
    logical clock has advanced beyond it) and is not `PAID`, `WAIVED`, or `CANCELLED`, and
    the cycle's `outstanding_cents` is still greater than zero, the cycle moves
    `REMITTED → DELINQUENT`."

    Design: Difficulty/boundary_precision_check/late_fee_grace_days_ge_boundary
    """
    ctx = create_delinquent_case(api, pay_first_installment=False,
                                 assess_clock="2026-07-06T00:00:00Z")
    cycle = validate_success(api.get_billing_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "DELINQUENT"


def test_no_late_fee_before_grace_boundary(api):
    """PRD §3.8: "On the fourth overdue day no flat fee applies; on the fifth it does."

    Design: Difficulty/boundary_precision_check/late_fee_grace_days_ge_boundary
    """
    ctx = create_delinquent_case(api, pay_first_installment=False,
                                 assess_clock="2026-07-05T00:00:00Z")  # exactly 4 days overdue
    case = validate_success(api.get_delinquency_case(ctx["case"]["id"], ADMIN))
    assert case["accrued_late_fee_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / delinquency_reinstatement_vs_settlement_payoff
# ---------------------------------------------------------------------------

def test_delinquency_reinstatement_amount(api):
    """PRD §3.9: "The `reinstatement_amount_cents` is that principal plus the full
    `accrued_late_fee_cents`: the complete arrears including every late fee, paid to
    reactivate the schedule."

    Design: Difficulty/dual_variant_calc/delinquency_reinstatement_vs_settlement_payoff
    """
    ctx = create_delinquent_case(api, pay_first_installment=True,
                                 assess_clock="2026-07-21T00:00:00Z")
    case = validate_success(api.get_delinquency_case(ctx["case"]["id"], ADMIN))
    assert case["principal_outstanding_cents"] == 50000
    assert case["accrued_late_fee_cents"] == 2500
    assert case["reinstatement_amount_cents"] == 52500


def test_delinquency_settlement_amount(api):
    """PRD §3.9: "The `settlement_amount_cents` is that same principal plus a flat settlement
    administration fee of 1500 cents, with the accrued late fees waived: the discounted
    lump-sum figure collections may negotiate."

    Design: Difficulty/dual_variant_calc/delinquency_reinstatement_vs_settlement_payoff
    """
    ctx = create_delinquent_case(api, pay_first_installment=True,
                                 assess_clock="2026-07-21T00:00:00Z")
    case = validate_success(api.get_delinquency_case(ctx["case"]["id"], ADMIN))
    assert case["settlement_amount_cents"] == 51500


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / delinquency_recovery_cycle_promise_broken_outreach
# ---------------------------------------------------------------------------

def _recovery_reoutreach(api):
    """Drive a case IN_OUTREACH -> PROMISE_TO_PAY -> BROKEN_PROMISE -> IN_OUTREACH."""
    ctx = create_delinquent_case(api, pay_first_installment=True,
                                 assess_clock="2026-07-21T00:00:00Z")
    case_id = ctx["case"]["id"]
    agent = make_agent_headers("agent_a")
    validate_success(api.record_recovery_action(
        case_id, {"action_type": "OUTREACH", "note": "left voicemail"}, agent), 201)
    validate_success(api.record_recovery_action(
        case_id, {"action_type": "PROMISE_SET", "promise_date": "2026-07-28T00:00:00Z"}, agent), 201)
    set_clock("2026-08-01T00:00:00Z", api)
    validate_success(api.assess_case(case_id, ADMIN))  # PROMISE_TO_PAY -> BROKEN_PROMISE
    validate_success(api.record_recovery_action(
        case_id, {"action_type": "OUTREACH", "note": "round 2"}, agent), 201)
    return case_id


def test_recovery_cycle_reoutreach_status_and_round(api):
    """PRD §3.8: "or re-opens it `BROKEN_PROMISE → IN_OUTREACH` — the latter increments the
    case's `recovery_round` by one, closing the recovery cycle."

    Design: Difficulty/non_linear_state_machine/delinquency_recovery_cycle_promise_broken_outreach
    """
    case_id = _recovery_reoutreach(api)
    case = validate_success(api.get_delinquency_case(case_id, ADMIN))
    assert case["status"] == "IN_OUTREACH"
    assert case["recovery_round"] == 1


def test_recovery_cycle_accrued_late_fee(api):
    """PRD §3.8: "the case moves `PROMISE_TO_PAY → BROKEN_PROMISE`: the per-round late fee of
    1000 cents is applied, adding 1000 to the case's `accrued_late_fee_cents` and appending a
    `LATE_FEE` ledger entry of 1000."

    Design: Difficulty/non_linear_state_machine/delinquency_recovery_cycle_promise_broken_outreach
    """
    case_id = _recovery_reoutreach(api)
    case = validate_success(api.get_delinquency_case(case_id, ADMIN))
    assert case["accrued_late_fee_cents"] == 3500  # 2500 flat + 1000 broken-promise


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / chargeoff_sod_beats_temporal
# ---------------------------------------------------------------------------

def test_chargeoff_same_agent_reports_sod(api):
    """PRD §3.9: "the acting manager's `X-User-ID` must differ from the case's
    `last_recovery_agent_id` (the agent who last worked it); when they are equal the request
    is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."
    PRD §2.9: "then the charge-off segregation-of-duties guard (`ERR_SOD_VIOLATION`); then
    the remaining cross-entity, temporal, domain-range, and fiscal checks described in §3."

    Design: Difficulty/priority_pair_validation_conflict/chargeoff_sod_beats_temporal
    """
    # Clock at 2026-07-21, before opened_at + 30 days: BOTH SoD and recovery-period fail.
    ctx = open_outreach_case(api, agent_id="agent_x", assess_clock="2026-07-21T00:00:00Z")
    resp = api.charge_off_case(ctx["case"]["id"], make_manager_headers("agent_x"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value, 403)


def test_chargeoff_sod_preempts_recovery_period(api):
    """PRD §2.9: "then the charge-off segregation-of-duties guard (`ERR_SOD_VIOLATION`); then
    the remaining cross-entity, temporal, domain-range, and fiscal checks described in §3."

    Design: Difficulty/priority_pair_validation_conflict/chargeoff_sod_beats_temporal
    """
    ctx = open_outreach_case(api, agent_id="agent_x", assess_clock="2026-07-21T00:00:00Z")
    resp = api.charge_off_case(ctx["case"]["id"], make_manager_headers("agent_x"))
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_RECOVERY_PERIOD_NOT_ELAPSED.value


# ---------------------------------------------------------------------------
# Corner: validations / cross_cutting
# ---------------------------------------------------------------------------

def test_promise_window_exceeded_returns_422(api):
    """PRD §3.8: "the promised date must fall within 14 days of the logical clock, or the
    action is rejected with `ERR_PROMISE_WINDOW_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/promise_window_exceeded_returns_422
    """
    ctx = open_outreach_case(api, agent_id="agent_p", assess_clock="2026-07-21T00:00:00Z")
    resp = api.record_recovery_action(
        ctx["case"]["id"],
        {"action_type": "PROMISE_SET", "promise_date": "2026-08-20T00:00:00Z"},
        make_agent_headers("agent_p"))
    validate_error(resp, ApiErrorId.ERR_PROMISE_WINDOW_EXCEEDED.value, 422)


def test_chargeoff_no_outstanding_balance_returns_422(api):
    """PRD §3.9: "there must actually be a balance to write off: the cycle's
    `outstanding_cents` must be greater than zero, or the request is rejected with
    `ERR_NO_OUTSTANDING_BALANCE` (HTTP 422)."

    Design: Corner/cross_cutting/chargeoff_no_outstanding_balance_returns_422
    """
    ctx = open_outreach_case(api, agent_id="agent_c", assess_clock="2026-07-21T00:00:00Z")
    # Pay the remaining (second) installment so outstanding falls to 0.
    inst2 = sorted(ctx["installments"], key=lambda i: i["sequence_no"])[1]
    charge_installment(inst2["id"], api, "MANUAL", "SUCCEED")
    set_clock("2026-08-21T00:00:00Z", api)  # >= 30 days past opened_at
    resp = api.charge_off_case(ctx["case"]["id"], make_manager_headers("mgr_1"))
    validate_error(resp, ApiErrorId.ERR_NO_OUTSTANDING_BALANCE.value, 422)
