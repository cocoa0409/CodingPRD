"""Subject account decisioning: the depth-3 exit cascade, execution gating,
reversal lockdown, segregation of duties (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_account,
    create_customer,
    create_staff,
    make_manager_headers,
    propose_and_approve_decision,
    propose_decision,
    reverse_decision_payload,
    setup_exit_cascade_scenario,
    validate_error,
    validate_success,
)


def test_exit_execution_exits_account_then_customer(api):
    """PRD §3.9: "`EXIT` moves the account to `EXITED`."
    PRD §3.9: "When the just-exited account was the customer's last account in
    `OPEN` or `RESTRICTED`, the customer itself transitions from `ACTIVE` to
    `EXITED`, which sets `any_account_exited` on the risk model."
    PRD §3.9: "Execution by a `BSAManager` moves the decision itself from
    `APPROVED` to `EXECUTED`."

    Link 1 (decision -> account) causes link 2 (account -> customer): with no
    remaining OPEN/RESTRICTED account, the customer exits.

    Design: Difficulty/transitive_cascade/exit_decision_three_level_cascade
    """
    staff = create_staff()
    built = setup_exit_cascade_scenario(staff)
    executed = validate_success(
        api.execute_account_decision(built.decision["id"], staff.manager), 200)
    assert executed["status"] == "EXECUTED"
    assert executed["executed_at"] is not None

    account = validate_success(api.get_account(built.account["id"], staff.analyst), 200)
    assert account["status"] == "EXITED", "link 1: caused by the decision execution"
    customer = validate_success(api.get_customer(built.customer["id"], staff.analyst), 200)
    assert customer["status"] == "EXITED", (
        "link 2: caused by the account exit — no remaining OPEN/RESTRICTED account"
    )
    assert customer["any_account_exited"] is True


def test_customer_exit_cascades_to_alerts_and_shares(api):
    """PRD §3.9: "The customer-exit event in turn cascades: every alert of the
    customer still in `NEW` or `UNDER_TRIAGE` is auto-closed with
    `closure_reason` `CUSTOMER_EXITED`, and every `DRAFT` 314(b) share of the
    customer is `CANCELLED`."

    Link 3 is caused by the customer exit (link 2), not by the decision
    directly.

    Design: Difficulty/transitive_cascade/exit_decision_three_level_cascade
    """
    staff = create_staff()
    built = setup_exit_cascade_scenario(staff)
    assert built.alert["status"] == "UNDER_TRIAGE"
    assert built.info_share["status"] == "DRAFT"

    validate_success(api.execute_account_decision(built.decision["id"], staff.manager), 200)

    alert = validate_success(api.get_alert(built.alert["id"], staff.analyst), 200)
    assert alert["status"] == "AUTO_CLOSED"
    assert alert["closure_reason"] == "CUSTOMER_EXITED"
    share = validate_success(api.get_info_share(built.info_share["id"], staff.analyst), 200)
    assert share["status"] == "CANCELLED"


def test_customer_exit_updates_risk_with_exited_account_points(api):
    """PRD §2.6: "The standard score starts from a base of 100, adds 250 points
    for every SAR filed for the customer within the trailing 365 days, adds 150
    points for every open law-enforcement inquiry, and adds 400 points if any
    of the customer's accounts has ever reached `EXITED`."
    PRD §3.9: "Every execution stamps `executed_at` and runs the risk
    recompute."

    After the exit the standard score is 100 + 400 = 500, band HIGH.

    Design: Difficulty/transitive_cascade/exit_decision_three_level_cascade
    """
    staff = create_staff()
    built = setup_exit_cascade_scenario(staff)
    validate_success(api.execute_account_decision(built.decision["id"], staff.manager), 200)

    customer = validate_success(api.get_customer(built.customer["id"], staff.analyst), 200)
    assert customer["risk_score_standard"] == 500
    assert customer["risk_rating"] == "HIGH"
    decision = validate_success(
        api.get_account_decision(built.decision["id"], staff.analyst), 200)
    assert decision["status"] == "EXECUTED"
    assert decision["executed_at"] is not None


def test_execute_decision_on_exited_account_rejected(api):
    """PRD §3.9: "It requires the account to be in `OPEN` or `RESTRICTED`
    (otherwise `ERR_ACCOUNT_NOT_OPEN`) and applies the mutation per decision."

    Design: Corner/errors/execute_decision_on_exited_account_rejected
    """
    staff = create_staff()
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8504")
    first = propose_and_approve_decision(staff, account["id"], "EXIT")
    validate_success(api.execute_account_decision(first["id"], staff.manager), 200)

    second = propose_decision(staff, account["id"], "EXIT", "Duplicate exit attempt")
    second = validate_success(
        api.approve_account_decision(second["id"], staff.manager), 200)
    res = api.execute_account_decision(second["id"], staff.manager)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_OPEN)
    assert res.status_code == 409
    second_after = validate_success(
        api.get_account_decision(second["id"], staff.analyst), 200)
    assert second_after["status"] == "APPROVED"
    account_after = validate_success(api.get_account(account["id"], staff.analyst), 200)
    assert account_after["status"] == "EXITED"


def test_reverse_after_execution_rejected(api):
    """PRD §3.9: "Before execution, an approval may be withdrawn by reversing
    the decision — a `BSAManager` supplies a non-empty `rationale`, the
    decision moves from `APPROVED` to `REVERSED`, and no account mutation is
    unwound because none was applied."
    PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/executed_decision_reverse_rejected
    """
    staff = create_staff()
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8103")
    decision = propose_and_approve_decision(staff, account["id"], "EXIT")
    validate_success(api.execute_account_decision(decision["id"], staff.manager), 200)

    res = api.reverse_account_decision(
        decision["id"],
        reverse_decision_payload(rationale="Attempted post-execution reversal"),
        staff.manager)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert res.status_code == 409
    decision_after = validate_success(
        api.get_account_decision(decision["id"], staff.analyst), 200)
    assert decision_after["status"] == "EXECUTED"
    account_after = validate_success(api.get_account(account["id"], staff.analyst), 200)
    assert account_after["status"] == "EXITED"


def test_decision_approval_by_proposer_rejected(api):
    """PRD §3.9: "Approval by a `BSAManager` is segregation-gated against the
    proposer and stamps `approved_by_analyst_id`."
    PRD §2.1: "On each, the caller's `X-User-ID` must differ from the actor who
    performed the prior step (the proposer, the drafter, or the assigned
    analyst as applicable), or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/sod_decision_approve_by_proposer_rejected
    """
    staff = create_staff()
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8602")
    decision = propose_decision(staff, account["id"], "EXIT", "Confirmed structuring")
    assert decision["proposed_by_analyst_id"] == staff.analyst_id

    proposer_as_manager = make_manager_headers(staff.analyst_id)
    res = api.approve_account_decision(decision["id"], proposer_as_manager)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert res.status_code == 403
    after = validate_success(api.get_account_decision(decision["id"], staff.analyst), 200)
    assert after["status"] == "PROPOSED"
