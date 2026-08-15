"""Equipment purchases: committee decision gates, encumbrance bookkeeping,
execution, and fund ledger reconciliation (PRD §3.7, §2.6, §2.10)."""
from test_helpers import (
    ADMIN,
    CM1,
    CM2,
    ApiErrorId,
    api_client,
    approve_allocation,
    approve_purchase,
    assert_allocation_ledger,
    assert_trust_fund_ledger,
    create_purchase,
    get_allocation,
    get_fund,
    get_purchase,
    propose_allocation,
    setup_active_allocation,
    setup_paid_report,
    validate_error,
    validate_success,
)


def _setup_zeroed_remaining_allocation():
    """Funded fund (500000 received); allocation of 10000 ACTIVE; purchase P1
    for the full 10000 APPROVED (remaining 0); purchase P2 for 1 cent DENIED.
    Returns (fund, allocation, purchase1, purchase2)."""
    fund, _employer, allocation = setup_active_allocation(
        amount_cents=10000, funded_hours=1000, rate=500,
    )
    p1 = create_purchase(allocation["id"], 10000, description="Conduit bender")
    approve_purchase(p1["id"], approver_headers=CM1)
    assert get_allocation(allocation["id"])["remaining_cents"] == 0
    p2 = create_purchase(allocation["id"], 1, description="Wire nuts box")
    validate_success(
        api_client.deny_equipment_purchase(p2["id"], {"reason": "not in plan"}, CM1),
        200,
    )
    return fund, allocation, p1, p2


def test_state_error_wins_over_fiscal_on_purchase_approve(api):
    """PRD §2.10: "When several checks could reject the same request, the
    server evaluates them in a fixed order, and a request failing several
    checks surfaces the error from the earliest tier."
    PRD §2.10: "Sixth, state preconditions for the requested transition,
    including the fund-version match on allocation approval."
    PRD §2.10: "Ninth and last, the fiscal checks: tender-equals-due,
    allocation-fits-fund, and purchase-fits-allocation."
    PRD §3.7: "Committee review of a purchase requires it to be `REQUESTED`
    (else `ERR_PURCHASE_NOT_REQUESTED`)."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_fiscal_purchase_approve
    """
    _fund, allocation, _p1, p2 = _setup_zeroed_remaining_allocation()
    assert get_purchase(p2["id"])["status"] == "DENIED"

    resp = api.approve_equipment_purchase(p2["id"], CM2)
    validate_error(resp, ApiErrorId.ERR_PURCHASE_NOT_REQUESTED)
    assert get_purchase(p2["id"])["status"] == "DENIED", (
        "the failed approval changed nothing"
    )


def test_shadowed_fiscal_failure_leaves_allocation_untouched(api):
    """PRD §2.10: "Ninth and last, the fiscal checks: tender-equals-due,
    allocation-fits-fund, and purchase-fits-allocation."
    PRD §3.7: "Approval stamps `decided_by_user_id` — null until the purchase
    is decided — and encumbers the allocation: `encumbered_cents` grows by the
    purchase amount and `remaining_cents` is recomputed."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_fiscal_purchase_approve
    """
    _fund, allocation, _p1, p2 = _setup_zeroed_remaining_allocation()
    before = get_allocation(allocation["id"])
    assert before["encumbered_cents"] == 10000
    assert before["remaining_cents"] == 0, (
        "the fiscal gate is also violated, yet it is the shadowed tier"
    )

    resp = api.approve_equipment_purchase(p2["id"], CM2)
    validate_error(resp, ApiErrorId.ERR_PURCHASE_NOT_REQUESTED)

    after = get_allocation(allocation["id"])
    assert after["encumbered_cents"] == 10000
    assert after["remaining_cents"] == 0
    assert_allocation_ledger(after)


def test_purchase_approve_encumbers_allocation(api):
    """PRD §3.7: "Approval stamps `decided_by_user_id` — null until the
    purchase is decided — and encumbers the allocation: `encumbered_cents`
    grows by the purchase amount and `remaining_cents` is recomputed."

    Design: Difficulty/compensating_invariant/compensating_allocation_encumbrance
    """
    fund, _employer, allocation = setup_active_allocation(
        amount_cents=500000, funded_hours=1000, rate=500,
    )
    assert get_fund(fund["id"])["available_cents"] == 0
    purchase = create_purchase(allocation["id"], 200000,
                               description="Cable tray bender")
    assert purchase["decided_by_user_id"] is None

    resp = api.approve_equipment_purchase(purchase["id"], CM1)
    approved = validate_success(resp, 200)
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] is not None

    after = get_allocation(allocation["id"])
    assert after["encumbered_cents"] == 200000
    assert after["remaining_cents"] == 300000
    assert_allocation_ledger(after)


def test_cancel_approved_purchase_releases_encumbrance(api):
    """PRD §3.7: "Cancelling an approved purchase releases its encumbrance —
    `encumbered_cents` falls by the purchase amount and `remaining_cents` is
    recomputed — while cancelling a still-requested purchase touches no ledger
    at all."
    PRD §2.6: "`available_cents` is what is left for new commitments:
    contributions received minus disbursements minus the remaining balances of
    active allocations."

    Design: Difficulty/compensating_invariant/compensating_allocation_encumbrance
    """
    fund, _employer, allocation = setup_active_allocation(
        amount_cents=500000, funded_hours=1000, rate=500,
    )
    purchase = create_purchase(allocation["id"], 200000)
    approve_purchase(purchase["id"], approver_headers=CM1)

    cancelled = validate_success(
        api.cancel_equipment_purchase(purchase["id"], ADMIN), 200,
    )
    assert cancelled["status"] == "CANCELLED"

    after = get_allocation(allocation["id"])
    assert after["encumbered_cents"] == 0, "compensation restored the invariant"
    assert after["spent_cents"] == 0
    assert after["remaining_cents"] == 500000
    assert_allocation_ledger(after)

    fund_after = get_fund(fund["id"])
    assert fund_after["available_cents"] == 0, (
        "encumber-and-release never touched the fund's available pool"
    )
    assert_trust_fund_ledger(fund_after)


def test_purchase_approve_at_exact_remaining_boundary(api):
    """PRD §3.7: "Approval additionally requires an `OPERATING` fund (else
    `ERR_FUND_ON_COMPLIANCE_HOLD`), a deciding identity different from
    `requested_by_user_id` (else `ERR_SELF_APPROVAL_FORBIDDEN`), the
    allocation still `ACTIVE` at decision time (else `ERR_INVALID_STATE`), and
    an `amount_cents` that fits inside the allocation's `remaining_cents`
    (else `ERR_INSUFFICIENT_ALLOCATION_REMAINING`, HTTP 402)."

    Design: Corner/validations/purchase_approve_exact_remaining_boundary
    """
    _fund, _employer, allocation = setup_active_allocation(
        amount_cents=500000, funded_hours=1000, rate=500,
    )
    purchase = create_purchase(allocation["id"], 500000,
                               description="Full-remaining purchase")
    resp = api.approve_equipment_purchase(purchase["id"], CM1)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED", (
        "an amount equal to remaining fits inside it"
    )
    assert get_allocation(allocation["id"])["remaining_cents"] == 0


def test_approve_already_approved_purchase_rejected(api):
    """PRD §3.7: "Committee review of a purchase requires it to be `REQUESTED`
    (else `ERR_PURCHASE_NOT_REQUESTED`)."

    Design: Corner/state_machines/purchase_approve_from_approved_returns_invalid_state
    """
    _fund, _employer, allocation = setup_active_allocation(
        amount_cents=600, funded_hours=1000, rate=500,
    )
    purchase = create_purchase(allocation["id"], 200, description="Conduit bender")
    approve_purchase(purchase["id"], approver_headers=CM1)
    assert get_allocation(allocation["id"])["encumbered_cents"] == 200

    resp = api.approve_equipment_purchase(purchase["id"], CM2)
    validate_error(resp, ApiErrorId.ERR_PURCHASE_NOT_REQUESTED)
    assert get_allocation(allocation["id"])["encumbered_cents"] == 200, (
        "no double encumbrance"
    )


def test_mark_purchased_on_requested_purchase_rejected(api):
    """PRD §3.7: "Executing an approved purchase requires the `APPROVED`
    status (else `ERR_PURCHASE_NOT_APPROVED`) and converts encumbrance into
    spend: `encumbered_cents` falls by the amount, `spent_cents` rises by it,
    `remaining_cents` is recomputed, the fund's `disbursed_cents` grows by the
    amount, `available_cents` is recomputed, the fund's `version` advances by
    one, and the purchase lands in `PURCHASED`."

    Design: Corner/errors/error_purchase_not_approved_on_mark_purchased
    """
    _fund, _employer, allocation = setup_active_allocation(
        amount_cents=1000, funded_hours=1000, rate=500,
    )
    purchase = create_purchase(allocation["id"], 100, description="Multimeters")

    resp = api.mark_purchased(purchase["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PURCHASE_NOT_APPROVED)
    assert get_purchase(purchase["id"])["status"] == "REQUESTED"
    assert get_allocation(allocation["id"])["encumbered_cents"] == 0


def test_fund_ledger_reconciles_after_mark_purchased(api):
    """PRD §2.6: "`disbursed_cents` is the sum of `payable_cents` across all
    PAID instructor pay claims plus the sum of `amount_cents` across all
    PURCHASED equipment purchases."
    PRD §2.6: "`available_cents` is what is left for new commitments:
    contributions received minus disbursements minus the remaining balances of
    active allocations."
    PRD §3.7: "Executing an approved purchase requires the `APPROVED` status
    (else `ERR_PURCHASE_NOT_APPROVED`) and converts encumbrance into spend:
    `encumbered_cents` falls by the amount, `spent_cents` rises by it,
    `remaining_cents` is recomputed, the fund's `disbursed_cents` grows by the
    amount, `available_cents` is recomputed, the fund's `version` advances by
    one, and the purchase lands in `PURCHASED`."

    Design: Corner/calculations/fund_ledger_reconciles_after_disbursement
    """
    fund, _employer, _apprentice, _report = setup_paid_report(
        hours=200000, rate=500,
    )
    assert get_fund(fund["id"])["contributions_received_cents"] == 100000000
    allocation = propose_allocation(fund["id"], 60000000)
    allocation = approve_allocation(allocation["id"], approver_headers=CM1)
    purchase = create_purchase(allocation["id"], 40000000,
                               description="Training transformers")
    approve_purchase(purchase["id"], approver_headers=CM1)

    resp = api.mark_purchased(purchase["id"], ADMIN)
    executed = validate_success(resp, 200)
    assert executed["status"] == "PURCHASED"

    fund_after = get_fund(fund["id"])
    assert fund_after["disbursed_cents"] == 40000000
    assert fund_after["available_cents"] == 40000000
    assert_trust_fund_ledger(fund_after)

    allocation_after = get_allocation(allocation["id"])
    assert allocation_after["encumbered_cents"] == 0
    assert allocation_after["spent_cents"] == 40000000
    assert allocation_after["remaining_cents"] == 20000000
    assert_allocation_ledger(allocation_after)
