"""Who may act, and whether holding the role is the whole answer.

Three of the six roles are opaque bearers of a role name, one is entity-backed, and
two operations compare identities rather than roles. So a valid operator is refused
at 403 on an exclusive operation while an undeclared role name is refused earlier at
401; a bank's own administrator is refused for naming a different bank in the body;
the analyst who originated a payment is refused its review even while presenting the
reviewer role; the officer whose withdrawal opened an alert is refused its sign-off;
and a transfer read is shared verbatim by four roles with entirely different jobs.
"""

from test_helpers import (
    acknowledge_alert,
    alert_acknowledgement_payload,
    alpha_scenario,
    assert_alert,
    assert_credit_transfer_shape,
    assert_instant,
    assign_review,
    CORE_BANKING_SYSTEM,
    customer_account_payload,
    cutoff_cycle,
    DUAL_HAT_OPERATOR,
    DUAL_HAT_REVIEWER,
    ERR_ALERT_SEGREGATION_OF_DUTIES,
    ERR_FORBIDDEN_ROLE,
    ERR_FRAUD_SEGREGATION_OF_DUTIES,
    ERR_PARTICIPANT_SCOPE_VIOLATION,
    ERR_UNAUTHENTICATED,
    fraud_decision_payload,
    FRAUD_REVIEWER,
    FRAUD_REVIEWER_TWO,
    get_success_data,
    held_transfer_scenario,
    LIQUIDITY_OFFICER,
    LIQUIDITY_OFFICER_TWO,
    list_alerts,
    live_alpha,
    live_beta,
    make_participant_admin_headers,
    NETWORK_OPERATOR,
    open_settlement_cycle,
    PAYMENT_OPERATOR_ALPHA,
    read_account,
    read_cycle,
    read_participant,
    read_transfer,
    send_from_alpha,
    set_clock,
    sole_fraud_review,
    UNDECLARED_ROLE,
    validate_error,
    validate_paginated,
    withdraw_from_account,
)


def test_a_valid_operator_is_forbidden_while_an_undeclared_role_is_unauthenticated(api):
    """Two refusals of the same call, and the authentication rung answers first.

    PRD 2.1: "If either header is missing or empty, or if `X-User-Role` does not name one of
    the six roles defined below, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD 2.1: "When both headers are well formed but the named role is not authorized for the
    operation being invoked, the request fails with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD 2.11: "1. **Authentication.** Both headers present, non-empty, and naming a declared
    role — otherwise `ERR_UNAUTHENTICATED`. Applies to every endpoint."

    PRD 2.11: "2. **Role authorization.** The caller's role appears in the invoked operation's
    authorized-role list — otherwise `ERR_FORBIDDEN_ROLE`. Applies to every endpoint."

    Design: Corner/rbac/payment_operator_cannot_cut_off_cycle_and_unknown_role_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    live_alpha(api)
    cycle = open_settlement_cycle(api, "2026-08-03")
    assert cycle["status"] == "OPEN"
    assert cycle["version"] == 1

    validate_error(
        api.cutoff_settlement_cycle(cycle["id"], PAYMENT_OPERATOR_ALPHA), ERR_FORBIDDEN_ROLE
    )
    validate_error(
        api.cutoff_settlement_cycle(cycle["id"], UNDECLARED_ROLE), ERR_UNAUTHENTICATED
    )

    untouched = read_cycle(api, cycle["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["cutoff_at"] is None
    assert untouched["closed_at"] is None
    assert untouched["assessed_fee_total_cents"] == 0
    assert untouched["settled_transfer_count"] == 0
    assert untouched["version"] == 1

    taken = cutoff_cycle(api, cycle["id"])
    assert taken["status"] == "CUTOFF"
    assert_instant(taken["cutoff_at"], "2026-08-03T13:00:00Z", "cutoff_at")


def test_an_administrator_may_not_register_another_banks_customer(api):
    """The scope check reads the body, and the role rung still answers before it.

    PRD 2.1: "A `ParticipantAdmin` may only read or write resources whose owning participant
    equals its own `X-User-ID`, whether that participant is resolved from the path, from a
    `participant_id` in the body, or transitively through a referenced position account,
    customer account or credit transfer; a mismatch is rejected with
    `ERR_PARTICIPANT_SCOPE_VIOLATION` (HTTP 403)."

    PRD 2.11: "3. **Participant ownership scope.** Applies to every operation whose authorized
    roles include `ParticipantAdmin`; a scope breach yields `ERR_PARTICIPANT_SCOPE_VIOLATION`."

    PRD 2.11: "When a single request violates more than one rule, the caller must receive a
    predictable answer, so the checks form one global ladder and the **first** violated rung
    determines the response."

    Design: Corner/rbac/participant_admin_cross_participant_write_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = live_alpha(api)
    beta = live_beta(api)

    body = customer_account_payload(
        alpha.id, account_reference="CUST-ALPHA-9999", segment="CORPORATE", fraud_risk_baseline=20
    )
    validate_error(
        api.create_customer_account(body, make_participant_admin_headers(beta.id)),
        ERR_PARTICIPANT_SCOPE_VIOLATION,
    )

    for bundle in (alpha, beta):
        _rows, meta = validate_paginated(
            api.list_participant_customer_accounts(
                bundle.id, make_participant_admin_headers(bundle.id)
            )
        )
        assert meta["total_count"] == 0

    validate_error(api.create_customer_account(body, NETWORK_OPERATOR), ERR_FORBIDDEN_ROLE)

    registered = get_success_data(
        api.create_customer_account(body, make_participant_admin_headers(alpha.id)),
        expected_status=201,
    )
    assert registered["participant_id"] == alpha.id
    assert registered["account_reference"] == "CUST-ALPHA-9999"
    assert registered["status"] == "ACTIVE"


def test_the_analyst_who_sent_the_payment_cannot_take_its_review(api):
    """The reviewer is identified by user, not by role, and the refusal is at assignment.

    PRD 2.1: "On fraud review, the acting `X-User-ID` must differ from the reviewed transfer's
    `initiated_by_user_id` when the review is taken and when it is decided, and on the decision
    it must additionally equal the review's `assigned_reviewer_user_id`; any breach is rejected
    with `ERR_FRAUD_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD 3.5: "Taking an item requires the item to be `QUEUED` and the reviewed transfer to be
    sitting in `FRAUD_HOLD`, and it requires the acting user to differ from that transfer's
    `initiated_by_user_id`: an operator may not review its own origination, and the attempt is
    refused with `ERR_FRAUD_SEGREGATION_OF_DUTIES`."

    PRD 3.5: "A `FraudReviewer` first takes the item, moving it `QUEUED → UNDER_REVIEW`; the
    operation carries no payload at all, binding the acting `X-User-ID` into
    `assigned_reviewer_user_id` and stamping `sla_deadline_at` at the assignment instant plus 60
    minutes."

    PRD 3.5: "Segregation of duties tightens at this step: the acting `X-User-ID` must still
    differ from the transfer's `initiated_by_user_id`, and it must additionally equal the
    review's `assigned_reviewer_user_id`, so an analyst cannot decide an item a colleague
    holds."

    Design: Corner/rbac/fraud_review_self_assignment_by_originator_rejected
    """
    scenario, transfer, review = held_transfer_scenario(api, operator=DUAL_HAT_OPERATOR)
    assert transfer["initiated_by_user_id"] == "dual-hat-01"
    assert transfer["clearing_status"] == "FRAUD_HOLD"
    assert transfer["fraud_score"] == 63
    assert review["status"] == "QUEUED"
    assert review["assigned_reviewer_user_id"] is None
    assert review["sla_deadline_at"] is None

    validate_error(
        api.assign_fraud_review(review["id"], DUAL_HAT_REVIEWER),
        ERR_FRAUD_SEGREGATION_OF_DUTIES,
    )

    unassigned = sole_fraud_review(api, transfer["id"])
    assert unassigned["status"] == "QUEUED"
    assert unassigned["assigned_reviewer_user_id"] is None
    assert unassigned["sla_deadline_at"] is None
    assert unassigned["score_at_origination"] == 63
    assert read_transfer(api, transfer["id"])["clearing_status"] == "FRAUD_HOLD"

    taken = assign_review(api, review["id"], FRAUD_REVIEWER)
    assert taken["status"] == "UNDER_REVIEW"
    assert taken["assigned_reviewer_user_id"] == "reviewer-01"
    assert_instant(taken["sla_deadline_at"], "2026-08-03T14:00:00Z", "sla_deadline_at")

    validate_error(
        api.decide_fraud_review(
            review["id"], fraud_decision_payload("RELEASE"), FRAUD_REVIEWER_TWO
        ),
        ERR_FRAUD_SEGREGATION_OF_DUTIES,
    )

    still_held = sole_fraud_review(api, transfer["id"])
    assert still_held["status"] == "UNDER_REVIEW"
    assert still_held["assigned_reviewer_user_id"] == "reviewer-01"
    assert still_held["final_fraud_score"] is None
    assert read_transfer(api, transfer["id"])["clearing_status"] == "FRAUD_HOLD"
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 50_000_000


def test_the_officer_whose_withdrawal_opened_the_alert_cannot_sign_it_off(api):
    """A second treasury officer is required even though both hold the same role.

    PRD 2.1: "On liquidity remediation, the `X-User-ID` acknowledging an alert must differ from
    the `X-User-ID` that posted the ledger adjustment which raised that alert, otherwise the
    acknowledgement is refused with `ERR_ALERT_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD 3.3: "Separation of duties applies here as it does on fraud review: the officer
    acknowledging the alert must not be the same user whose ledger adjustment raised it,
    otherwise the attempt is refused with `ERR_ALERT_SEGREGATION_OF_DUTIES`."

    PRD 3.3: "A treasury officer acknowledges an alert that is `OPEN` or `ESCALATED` by
    supplying a `remediation_plan`; the alert becomes `ACKNOWLEDGED`, `acknowledged_by_user_id`
    is taken from the acting `X-User-ID`, and neither the account's `alert_tier` nor the
    participant's posture changes — acknowledgement is a commitment to fund, not funding."

    PRD 2.9: "If the balance is strictly below `floor_cents` the tier is `BREACH`; otherwise, if
    it is at or below `critical_threshold_cents` the tier is `RED`; otherwise, if it is at or
    below `warning_threshold_cents` the tier is `AMBER`; otherwise the tier is `GREEN`."

    Design: Corner/rbac/alert_acknowledgement_by_triggering_officer_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = live_alpha(api)
    withdraw_from_account(
        api,
        alpha.account_id,
        150_000_000,
        reference="TREASURY-SWEEP-01",
        officer=LIQUIDITY_OFFICER,
    )

    opened = list_alerts(api, alpha.account_id, {"status": "OPEN", "limit": 10, "offset": 0})
    assert len(opened) == 1
    assert_alert(
        opened[0],
        tier="AMBER",
        status="OPEN",
        threshold_cents=1_100_000_000,
        observed_balance_cents=1_050_000_000,
    )

    validate_error(
        api.acknowledge_alert(
            opened[0]["id"],
            alert_acknowledgement_payload(
                "Intraday funding request already submitted to the correspondent."
            ),
            LIQUIDITY_OFFICER,
        ),
        ERR_ALERT_SEGREGATION_OF_DUTIES,
    )

    unworked = list_alerts(api, alpha.account_id, {"status": "OPEN", "limit": 10, "offset": 0})
    assert len(unworked) == 1
    assert unworked[0]["id"] == opened[0]["id"]
    assert unworked[0]["acknowledged_by_user_id"] is None
    assert unworked[0]["remediation_plan"] is None
    assert_alert(
        unworked[0],
        tier="AMBER",
        status="OPEN",
        threshold_cents=1_100_000_000,
        observed_balance_cents=1_050_000_000,
    )

    throttled = read_account(api, alpha.account_id)
    assert throttled["current_balance_cents"] == 1_050_000_000
    assert throttled["alert_tier"] == "AMBER"
    assert read_participant(api, alpha.id)["operational_posture"] == "THROTTLED"

    acknowledged = acknowledge_alert(
        api,
        opened[0]["id"],
        remediation_plan="Intraday funding request already submitted to the correspondent.",
        officer=LIQUIDITY_OFFICER_TWO,
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == "liq-02"
    assert acknowledged["tier"] == "AMBER"
    assert read_account(api, alpha.account_id)["alert_tier"] == "AMBER"
    assert read_participant(api, alpha.id)["operational_posture"] == "THROTTLED"


def test_four_roles_read_one_transfer_and_see_the_identical_row(api):
    """A shared read is the same row for every permitted role, and closed to the sixth.

    PRD 2.1: "The six roles are `NetworkOperator`, `ParticipantAdmin`, `LiquidityOfficer`,
    `PaymentOperator`, `FraudReviewer` and `CoreBankingSystem`."

    PRD 3.4: "Transfers can be read individually, returning both dimensions along with the
    frozen `fraud_score` and `fraud_reason_codes`, and listed with filters on
    `originator_participant_id`, `customer_account_id`, `segment_policy_id`, `rfp_id`,
    `compensating_for_transfer_id`, `clearing_status`, `exception_status` and
    `settlement_business_date`."

    PRD 3.4: "A send that clears the whole ladder is persisted with `direction` `OUTBOUND`,
    `rail` `INSTANT`, `clearing_status` `INITIATED`, `exception_status` `NONE`,
    `segment_policy_id` pinned to the governing policy, `initiated_by_user_id` taken from the
    acting `X-User-ID`, and `rejection_reason_code` unset."

    PRD 2.11: "2. **Role authorization.** The caller's role appears in the invoked operation's
    authorized-role list — otherwise `ERR_FORBIDDEN_ROLE`. Applies to every endpoint."

    Design: Corner/rbac/transfer_read_shared_across_four_roles
    """
    scenario = alpha_scenario(api)
    transfer = send_from_alpha(api, scenario, 50_000_000)
    assert transfer["initiated_by_user_id"] == "ops-alpha-01"

    views = []
    for headers in (NETWORK_OPERATOR, PAYMENT_OPERATOR_ALPHA, FRAUD_REVIEWER, CORE_BANKING_SYSTEM):
        view = get_success_data(api.get_credit_transfer(transfer["id"], headers))
        assert_credit_transfer_shape(view)
        assert view["amount_cents"] == 50_000_000
        assert view["direction"] == "OUTBOUND"
        assert view["rail"] == "INSTANT"
        assert view["clearing_status"] == "INITIATED"
        assert view["exception_status"] == "NONE"
        assert view["fraud_score"] == 57
        assert view["initiated_by_user_id"] == "ops-alpha-01"
        assert view["segment_policy_id"] == scenario.alpha.policy["id"]
        assert view["version"] == 1
        views.append(view)

    assert views[0] == views[1] == views[2] == views[3]

    validate_error(
        api.get_credit_transfer(transfer["id"], LIQUIDITY_OFFICER), ERR_FORBIDDEN_ROLE
    )
    assert read_transfer(api, transfer["id"])["version"] == 1
