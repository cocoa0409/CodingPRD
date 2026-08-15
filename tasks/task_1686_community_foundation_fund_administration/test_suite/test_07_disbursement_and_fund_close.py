"""Grant disbursement ledger effects, fund closure gates, and the activation
dependency on an executed agreement."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_fund_payload,
    create_agreement_payload,
    create_contribution_payload,
    create_active_fund,
    create_cleared_grantee,
    create_approved_grant,
    make_officer_headers,
    get_fund,
    assert_disbursement,
    assert_money_eq,
    is_iso8601_timestamp,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
GIFT = TEST_USERS["gift_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_disburse_debits_cash_and_creates_single_disbursement(api):
    """PRD §3.6: "Disbursement debits the fund's `cash_balance` by the grant
    amount, adds the amount to the fund's `allowance_used` on endowed funds,
    refreshes the fund's `last_activity_at` — waking an `INACTIVE` fund back to
    `ACTIVE` — and creates a disbursement record with `source_kind` `GRANT`, the
    `grant_id` populated, the `fund_id` denormalized from the grant for
    statement sweeps, and the disbursed `amount` copied from the grant at
    creation."

    Design: Difficulty/compensating_invariant/grant_disburse_and_cancel_conserve_fund_cash
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    grantee = create_cleared_grantee()
    grant_a = create_approved_grant(
        fund_id=fund_id, grantee_id=grantee["id"], amount=1000.00
    )
    grant_b = create_approved_grant(
        fund_id=fund_id, grantee_id=grantee["id"], amount=2000.00
    )
    disbursed = validate_success(
        api.disburse_grant(grant_a["id"], make_officer_headers("FinanceOfficer", "fo-1")),
        200,
    )
    assert disbursed["status"] == "DISBURSED"
    cancelled = validate_success(api.cancel_grant(grant_b["id"], COMPLIANCE))
    assert cancelled["status"] == "CANCELLED"

    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 49000.00, "only the disbursed grant left cash")
    disbursements, meta = validate_paginated(api.list_fund_disbursements(fund_id, FINANCE))
    assert meta["total_count"] == 1
    assert_disbursement(disbursements[0])
    assert_money_eq(disbursements[0]["amount"], 1000.00, "disbursement amount")
    assert disbursements[0]["source_kind"] == "GRANT"
    assert disbursements[0]["grant_id"] == grant_a["id"]
    assert disbursements[0]["fund_id"] == fund_id


def test_cancelled_grant_never_touches_cash(api):
    """PRD §3.6: "And an `APPROVED` grant may still be cancelled, moving it to
    `CANCELLED`, when circumstances change before payment."

    Design: Difficulty/compensating_invariant/grant_disburse_and_cancel_conserve_fund_cash
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    grantee = create_cleared_grantee()
    grant = create_approved_grant(
        fund_id=fund_id, grantee_id=grantee["id"], amount=2000.00
    )
    cancelled = validate_success(api.cancel_grant(grant["id"], COMPLIANCE))
    assert cancelled["status"] == "CANCELLED"
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 50000.00, "cancel leaves cash untouched")
    disbursements, _ = validate_paginated(api.list_fund_disbursements(fund_id, FINANCE))
    assert disbursements == []


def test_disbursement_visible_immediately(api):
    """PRD §3.6: "Disbursement debits the fund's `cash_balance` by the grant
    amount, adds the amount to the fund's `allowance_used` on endowed funds,
    refreshes the fund's `last_activity_at` — waking an `INACTIVE` fund back to
    `ACTIVE` — and creates a disbursement record with `source_kind` `GRANT`, the
    `grant_id` populated, the `fund_id` denormalized from the grant for
    statement sweeps, and the disbursed `amount` copied from the grant at
    creation."

    Design: Corner/consistency_model/immediate_visibility_of_disbursement
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    grantee = create_cleared_grantee()
    grant = create_approved_grant(
        fund_id=fund_id, grantee_id=grantee["id"], amount=500.00
    )
    resp = api.disburse_grant(
        grant["id"], make_officer_headers("FinanceOfficer", "fo-1")
    )
    assert validate_success(resp, 200)["status"] == "DISBURSED"
    # Immediately following reads already reflect the debit and the ledger row.
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 49500.00, "cash debited immediately")
    disbursements, _ = validate_paginated(api.list_fund_disbursements(fund_id, FINANCE))
    assert len(disbursements) == 1
    assert_money_eq(disbursements[0]["amount"], 500.00, "disbursement amount")
    assert disbursements[0]["source_kind"] == "GRANT"


def test_disburser_must_differ_from_approver(api):
    """PRD §3.6: "A `FinanceOfficer` disburses an `APPROVED` grant under two
    checks in order: the disbursing officer's `X-User-ID` must differ from the
    approving officer's recorded identity, failing with
    `ERR_SOD_SELF_DISBURSE` (HTTP 403), and the `amount` must not exceed the
    fund's `cash_balance`, failing with `ERR_INSUFFICIENT_CASH`."
    PRD §2.1: "Segregation-of-duties checks compare these opaque identifiers
    against each other, never against entity rows."

    Design: Corner/roles/sod_disburser_differs_from_approver
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    grantee = create_cleared_grantee()
    grant = create_approved_grant(
        fund_id=fund_id, grantee_id=grantee["id"], amount=500.00,
        claimer_id="co-1", approver_id="co-2",
    )
    # A FinanceOfficer acting under the same opaque id as the approver is blocked.
    resp = api.disburse_grant(
        grant["id"], make_officer_headers("FinanceOfficer", "co-2")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_SELF_DISBURSE)
    ok = validate_success(
        api.disburse_grant(grant["id"], make_officer_headers("FinanceOfficer", "fo-9")),
        200,
    )
    assert ok["status"] == "DISBURSED"
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 49500.00, "cash after disbursement")


def test_close_blocked_by_pending_grant(api):
    """PRD §3.1: "Closing an `ACTIVE` fund requires, in order: a zeroed ledger,
    meaning `cash_balance` is exactly 0.00 and `invested_units` is exactly
    0.0000, failing which the close is rejected with `ERR_FUND_NOT_EMPTY` (HTTP
    409); no grant recommendation of the fund resting in any of `DRAFT`,
    `SUBMITTED`, `COMPLIANCE_REVIEW`, `RETURNED`, or `APPROVED`, failing which
    the close is rejected with `ERR_PENDING_GRANTS` (HTTP 409); and no
    scholarship program of the fund in `SETUP`, `OPEN`, `SCORING`, or `AWARDED`,
    failing which the close is rejected with `ERR_PROGRAM_OPEN` (HTTP 409)."

    Design: Corner/cross_cutting_layers/cascade_ordering_fund_close_blocked_by_children
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=10000.00)
    fund_id = bundle["fund"]["id"]
    grantee = create_cleared_grantee()
    draining_grant = create_approved_grant(
        fund_id=fund_id, grantee_id=grantee["id"], amount=10000.00
    )
    pending_grant = create_approved_grant(
        fund_id=fund_id, grantee_id=grantee["id"], amount=500.00
    )
    # Zero the ledger via a full disbursement of the first grant.
    validate_success(
        api.disburse_grant(
            draining_grant["id"], make_officer_headers("FinanceOfficer", "fo-1")
        ),
        200,
    )
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 0.00, "ledger zeroed")
    # The second grant still rests in APPROVED, blocking closure.
    resp = api.close_fund(fund_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PENDING_GRANTS)
    after = get_fund(fund_id)
    assert after["status"] == "ACTIVE"


def _setup_pending_fund_with_draft_agreement(api):
    fund = get_success_data(api.create_fund(create_fund_payload(), ADMIN))
    agreement = get_success_data(
        api.create_agreement(fund["id"], create_agreement_payload(), ADMIN)
    )
    contribution = get_success_data(
        api.create_contribution(
            create_contribution_payload(fund_id=fund["id"], declared_value=20000.00),
            GIFT,
        )
    )
    get_success_data(api.accept_contribution(contribution["id"], GIFT))
    return fund, agreement


def test_activation_requires_executed_agreement(api):
    """PRD §3.1: "The fund must first hold an `EXECUTED` agreement — activating
    without one fails with `ERR_AGREEMENT_NOT_EXECUTED` (HTTP 409) — and it must
    then have received at least one accepted contribution whose `net_proceeds`
    is greater than or equal to the agreement's `min_initial_contribution`,
    failing which the activation is rejected with
    `ERR_MIN_INITIAL_CONTRIBUTION` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/fund_activation_depends_on_agreement_executed
    """
    fund, _ = _setup_pending_fund_with_draft_agreement(api)
    # Contribution minimum is met, but the agreement is still DRAFT.
    resp = api.activate_fund(fund["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED)
    after = get_fund(fund["id"])
    assert after["status"] == "PENDING_AGREEMENT"


def test_activation_succeeds_after_execution(api):
    """PRD §3.1: "Activation moves the fund from `PENDING_AGREEMENT` to
    `ACTIVE`, stamps both `inception_date` and `last_activity_at` from the
    logical clock, and advances the fund's `version`."

    Design: Difficulty/cross_entity_state_dependency/fund_activation_depends_on_agreement_executed
    """
    fund, agreement = _setup_pending_fund_with_draft_agreement(api)
    validate_error(
        api.activate_fund(fund["id"], ADMIN), ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED
    )
    validate_success(api.execute_agreement(agreement["id"], ADMIN))
    activated = validate_success(api.activate_fund(fund["id"], ADMIN), 200)
    assert activated["status"] == "ACTIVE"
    assert is_iso8601_timestamp(activated["inception_date"])
    assert is_iso8601_timestamp(activated["last_activity_at"])
