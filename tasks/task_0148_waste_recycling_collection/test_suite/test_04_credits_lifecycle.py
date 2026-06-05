"""Missed-pickup credits, the dispute/resolve revision loop, and balance invariants.

Covers difficulty rules dual_variant_calc (credit flat vs partial refund),
non_linear_state_machine (invoice dispute/resolve cycle, special-pickup approve/reject
branch), and compensating_invariant (issue-then-void releases credit; cancel conserves
balance), plus the credit/invoice corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_pickup_payload,
    miss_pickup_payload,
    create_diversion_period_payload,
    create_account,
    create_active_cart,
    create_active_plan,
    setup_active_account,
    setup_route_in_progress,
    schedule_pickup,
    request_special_pickup,
    setup_scheduled_special_pickup,
    make_resident_headers,
    create_invoice_payload,
)
import test_helpers as th

api = th.api_client
DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
BILLING = TEST_USERS["billing_headers"]

MAY_START = "2026-05-01T00:00:00Z"
MAY_END = "2026-06-01T00:00:00Z"


def _carrier_fault_miss(account_id, miss_reason="MISSED_BY_CREW", service_date="2026-05-20T00:00:00Z"):
    """Drive one SCHEDULED pickup to MISSED with a carrier-fault reason. Returns the
    pickup dict (its auto-created PENDING credit can be fetched by source_pickup_id)."""
    cart = create_active_cart(account_id, stream="TRASH", size_gallons=65, tare_weight_lbs=0)
    route, stops = setup_route_in_progress(account_id, stream="TRASH", service_date=service_date)
    pk = schedule_pickup(stops[0]["id"], cart["id"])
    return validate_success(api.miss_pickup(pk["id"], miss_pickup_payload(miss_reason), DRIVER), 200)


def _draft_invoice(account_id, period_start=MAY_START, period_end=MAY_END):
    acct = validate_success(api.get_account(account_id, BILLING), 200)
    return validate_success(api.create_invoice(account_id, create_invoice_payload(
        period_start, period_end, acct["version"]), BILLING), 201)


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / dual_variant_calc — credit flat (PICKUP) vs partial refund (SPECIAL)
# ═══════════════════════════════════════════════════════════════════════════

def test_carrier_fault_miss_creates_flat_pickup_credit():
    """PRD §3.7: "a `PICKUP`-sourced credit is a flat goodwill amount of 1500 cents
    regardless of weight or plan".
    PRD §3.3: "when the `miss_reason` is `MISSED_BY_CREW` or `TRUCK_FULL` — both
    carrier-fault reasons — the system automatically creates a `MissedPickupCredit` in
    `PENDING` status, with its `source_type` set to `PICKUP`".

    Design: Difficulty/dual_variant_calc/missed_credit_flat_vs_special_partial_refund
    """
    account, _cart, _plan = setup_active_account(address="2 Oak St", stream="TRASH",
                                                 base_monthly_fee_cents=1500)
    missed = _carrier_fault_miss(account["id"], miss_reason="MISSED_BY_CREW",
                                 service_date="2026-05-05T00:00:00Z")
    credits, _ = validate_paginated(api.list_credits(BILLING, params={"source_pickup_id": missed["id"]}))
    assert len(credits) == 1, f"expected exactly one credit, got {len(credits)}"
    c = credits[0]
    assert c["source_type"] == "PICKUP", f"source_type must be PICKUP, got {c['source_type']}"
    assert c["amount_cents"] == 1500, f"flat pickup credit must be 1500, got {c['amount_cents']}"
    assert c["status"] == "PENDING", f"credit must be PENDING, got {c['status']}"


def test_scheduled_special_cancel_creates_partial_refund_credit():
    """PRD §3.7: "a `SPECIAL_PICKUP`-sourced credit is 50 percent of the originating
    special pickup's `quoted_fee_cents`, rounded half-up to whole cents."
    PRD §3.5: "if the special pickup was in `SCHEDULED` status at the moment of
    cancellation — meaning the carrier had already committed a collection slot — the
    system automatically creates a `MissedPickupCredit` in `PENDING` status with its
    `source_type` set to `SPECIAL_PICKUP` and its `source_special_pickup_id` set to this
    special pickup, with the amount computed as in §3.7."

    Design: Difficulty/dual_variant_calc/missed_credit_flat_vs_special_partial_refund
    """
    # HAZARDOUS/CORROSIVE quoted 8000*1.75 = 14000; 50% = 7000.
    account, _cart, _plan = setup_active_account(address="2b Oak St", stream="TRASH",
                                                 base_monthly_fee_cents=1500)
    sp = setup_scheduled_special_pickup(account["id"], kind="HAZARDOUS", hazard_class="CORROSIVE")
    assert sp["quoted_fee_cents"] == 14000, f"setup expects quote 14000, got {sp['quoted_fee_cents']}"
    validate_success(api.cancel_special_pickup(sp["id"], make_resident_headers(account["id"])), 200)
    credits, _ = validate_paginated(api.list_credits(BILLING, params={"source_special_pickup_id": sp["id"]}))
    assert len(credits) == 1, f"expected exactly one credit, got {len(credits)}"
    c = credits[0]
    assert c["source_type"] == "SPECIAL_PICKUP", f"source_type must be SPECIAL_PICKUP, got {c['source_type']}"
    assert c["amount_cents"] == 7000, f"50% of 14000 = 7000 expected, got {c['amount_cents']}"
    assert c["status"] == "PENDING", f"credit must be PENDING, got {c['status']}"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / non_linear_state_machine — invoice dispute/resolve cycle
# ═══════════════════════════════════════════════════════════════════════════

def test_invoice_dispute_then_resolve_returns_to_issued():
    """PRD §3.7: "A `ResidentAccount` (acting on its own invoice) may dispute an
    `ISSUED` invoice, moving it to `DISPUTED`. A `Billing` operator resolves a
    `DISPUTED` invoice by re-pricing it: all charge components and `total_cents` are
    recomputed in the same pinned order described in §3.6, `balance_cents` is reset to
    the new `total_cents`, and the invoice returns to `ISSUED`."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_resolve_cycle
    """
    account, _cart, _plan = setup_active_account(address="11 Birch St", stream="TRASH",
                                                 base_monthly_fee_cents=2000)
    invoice = _draft_invoice(account["id"])
    validate_success(api.issue_invoice(invoice["id"], BILLING), 200)
    validate_success(api.dispute_invoice(invoice["id"], make_resident_headers(account["id"])), 200)
    resolved = validate_success(api.resolve_invoice(invoice["id"], BILLING), 200)
    assert resolved["status"] == "ISSUED", f"expected ISSUED after resolve, got {resolved['status']}"


def test_invoice_resolve_reprices_to_same_total():
    """PRD §3.7: "A `Billing` operator resolves a `DISPUTED` invoice by re-pricing it:
    all charge components and `total_cents` are recomputed in the same pinned order
    described in §3.6, `balance_cents` is reset to the new `total_cents`, and the invoice
    returns to `ISSUED`."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_resolve_cycle
    """
    # Base-only invoice (no weight/contam/credit): total stays 2000 across the cycle.
    account, _cart, _plan = setup_active_account(address="11b Birch St", stream="TRASH",
                                                 base_monthly_fee_cents=2000)
    invoice = _draft_invoice(account["id"])
    validate_success(api.issue_invoice(invoice["id"], BILLING), 200)
    validate_success(api.dispute_invoice(invoice["id"], make_resident_headers(account["id"])), 200)
    resolved = validate_success(api.resolve_invoice(invoice["id"], BILLING), 200)
    assert resolved["total_cents"] == 2000, f"expected re-priced total 2000, got {resolved['total_cents']}"
    assert resolved["balance_cents"] == 2000, f"balance must reset to total, got {resolved['balance_cents']}"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / non_linear_state_machine — special-pickup approve vs reject branch
# ═══════════════════════════════════════════════════════════════════════════

def test_special_pickup_approve_sets_fee():
    """PRD §3.5: "Approval sets `quoted_fee_cents` per the fee schedule in §3.7."
    PRD §3.7: "a `BULK` request quotes a flat 3500 cents with no multiplier".

    Design: Difficulty/non_linear_state_machine/special_pickup_branch_approve_vs_reject
    """
    account, _cart, _plan = setup_active_account(address="13 Cedar St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    sp = request_special_pickup(account["id"], kind="BULK", requested_date="2026-05-12T00:00:00Z")
    approved = validate_success(api.approve_special_pickup(sp["id"], DISPATCHER), 200)
    assert approved["status"] == "APPROVED", f"expected APPROVED, got {approved['status']}"
    assert approved["quoted_fee_cents"] == 3500, f"BULK quote must be 3500, got {approved['quoted_fee_cents']}"


def test_special_pickup_reject_is_terminal_no_fee():
    """PRD §3.5: "**Rejection** moves a `REQUESTED` special pickup to the terminal
    `REJECTED` state."
    PRD §1 (SpecialPickup default) / §3.5: rejection runs no fee-setting side effect, so
    a rejected request never receives a quote.

    Design: Difficulty/non_linear_state_machine/special_pickup_branch_approve_vs_reject
    """
    account, _cart, _plan = setup_active_account(address="13b Cedar St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    sp = request_special_pickup(account["id"], kind="BULK", requested_date="2026-05-13T00:00:00Z")
    rejected = validate_success(api.reject_special_pickup(sp["id"], DISPATCHER), 200)
    assert rejected["status"] == "REJECTED", f"expected REJECTED, got {rejected['status']}"
    assert rejected["quoted_fee_cents"] == 0, (
        f"a rejected (never-approved) special pickup carries no quote, got {rejected['quoted_fee_cents']}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / compensating_invariant — issue-then-void releases credit
# ═══════════════════════════════════════════════════════════════════════════

def test_invoice_void_releases_applied_credit_to_pending():
    """PRD §3.7: "Billing may also void an invoice from `DRAFT`, `ISSUED`, or
    `DISPUTED`, moving it to the terminal `VOID` state with `balance_cents` set to 0;
    voiding releases every `MissedPickupCredit` whose `applied_invoice_id` is this
    invoice back to `PENDING` status, clearing its `applied_invoice_id` and incrementing
    its `version`".

    Design: Difficulty/compensating_invariant/invoice_issue_then_void_releases_credit_balance_invariant
    """
    account, _cart, _plan = setup_active_account(address="33 Poplar St", stream="TRASH",
                                                 base_monthly_fee_cents=0)
    # Carrier-fault miss -> one PENDING credit (TRUCK_FULL, amount 1500).
    _carrier_fault_miss(account["id"], miss_reason="TRUCK_FULL", service_date="2026-05-20T00:00:00Z")
    invoice = _draft_invoice(account["id"])
    validate_success(api.issue_invoice(invoice["id"], BILLING), 200)  # absorbs credit -> APPLIED
    # Sanity: no PENDING credits remain right after issue.
    applied, _ = validate_paginated(api.list_credits(BILLING, params={"account_id": account["id"], "status": "APPLIED"}))
    assert len(applied) == 1, f"issue must apply the credit, got {len(applied)} APPLIED"
    # Void releases it back to PENDING.
    voided = validate_success(api.void_invoice(invoice["id"], BILLING), 200)
    assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"
    assert voided["balance_cents"] == 0, f"void must zero balance, got {voided['balance_cents']}"
    pending, _ = validate_paginated(api.list_credits(BILLING, params={"account_id": account["id"], "status": "PENDING"}))
    assert len(pending) == 1, f"void must release exactly one credit to PENDING, got {len(pending)}"
    assert pending[0]["applied_invoice_id"] is None, (
        f"released credit must clear applied_invoice_id, got {pending[0]['applied_invoice_id']}"
    )
    still_applied, _ = validate_paginated(api.list_credits(BILLING, params={"account_id": account["id"], "status": "APPLIED"}))
    assert still_applied == [], f"no credit may remain APPLIED after void, got {still_applied}"


def test_pending_credit_count_conserved_across_issue_void():
    """PRD §3.7: "When an invoice is issued, the system absorbs each eligible `PENDING`
    credit for that invoice's account — that is, every `PENDING` credit whose
    `account_id` matches the invoice's account — moving it to `APPLIED` and setting its
    `applied_invoice_id` to the issued invoice; the credit's `version` increments."
    PRD §3.7: "voiding releases every `MissedPickupCredit` whose `applied_invoice_id` is
    this invoice back to `PENDING` status, clearing its `applied_invoice_id` and
    incrementing its `version`, and then the account balance is recomputed."

    Design: Difficulty/compensating_invariant/invoice_issue_then_void_releases_credit_balance_invariant
    """
    account, _cart, _plan = setup_active_account(address="33b Poplar St", stream="TRASH",
                                                 base_monthly_fee_cents=0)
    _carrier_fault_miss(account["id"], miss_reason="MISSED_BY_CREW", service_date="2026-05-20T00:00:00Z")
    before, _ = validate_paginated(api.list_credits(BILLING, params={"account_id": account["id"], "status": "PENDING"}))
    assert len(before) == 1, f"pre-issue PENDING count must be 1, got {len(before)}"
    invoice = _draft_invoice(account["id"])
    validate_success(api.issue_invoice(invoice["id"], BILLING), 200)
    validate_success(api.void_invoice(invoice["id"], BILLING), 200)
    after, _ = validate_paginated(api.list_credits(BILLING, params={"account_id": account["id"], "status": "PENDING"}))
    assert len(after) == 1, f"PENDING count must return to 1 after issue+void, got {len(after)}"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / compensating_invariant — pending credit does not change balance
# ═══════════════════════════════════════════════════════════════════════════

def test_scheduled_special_cancel_credit_does_not_change_balance():
    """PRD §3.7: "Every account exposes a derived `account_balance_cents`, defined as
    the sum of `balance_cents` over the account's invoices in `ISSUED` or `DISPUTED`
    status, minus the sum of `amount_cents` over the account's credits in `APPLIED`
    status."

    Design: Difficulty/compensating_invariant/special_schedule_cancel_credit_conserves_account_balance
    """
    account, _cart, _plan = setup_active_account(address="35 Sequoia St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    sp = setup_scheduled_special_pickup(account["id"], kind="BULK")  # quote 3500
    validate_success(api.cancel_special_pickup(sp["id"], make_resident_headers(account["id"])), 200)
    credits, _ = validate_paginated(api.list_credits(BILLING, params={"source_special_pickup_id": sp["id"]}))
    assert len(credits) == 1, f"expected one credit, got {len(credits)}"
    assert credits[0]["amount_cents"] == 1750, f"50% of 3500 = 1750 expected, got {credits[0]['amount_cents']}"
    assert credits[0]["status"] == "PENDING", f"credit must be PENDING, got {credits[0]['status']}"
    acct = validate_success(api.get_account(account["id"], BILLING), 200)
    assert acct["account_balance_cents"] == 0, (
        f"a PENDING credit (not APPLIED) must not change balance, got {acct['account_balance_cents']}"
    )


def test_special_cancel_pending_credit_is_pending_status():
    """PRD §3.5: "the system automatically creates a `MissedPickupCredit` in `PENDING`
    status with its `source_type` set to `SPECIAL_PICKUP` and its
    `source_special_pickup_id` set to this special pickup".

    Design: Difficulty/compensating_invariant/special_schedule_cancel_credit_conserves_account_balance
    """
    account, _cart, _plan = setup_active_account(address="35b Sequoia St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    sp = setup_scheduled_special_pickup(account["id"], kind="BULK")
    validate_success(api.cancel_special_pickup(sp["id"], make_resident_headers(account["id"])), 200)
    credits, _ = validate_paginated(api.list_credits(BILLING, params={"source_special_pickup_id": sp["id"]}))
    assert len(credits) == 1
    assert credits[0]["source_special_pickup_id"] == sp["id"], (
        f"polymorphic source must point at the special pickup, got {credits[0]['source_special_pickup_id']}"
    )
    assert credits[0]["status"] == "PENDING"


# ═══════════════════════════════════════════════════════════════════════════
# Corner / state_machines — invoice pay idempotency
# ═══════════════════════════════════════════════════════════════════════════

def test_invoice_pay_then_pay_again_rejected():
    """PRD §3.7: "Any invoice transition attempted from a status the transition is not
    defined for is rejected with `ERR_INVALID_STATE`."
    PRD §3.7: "Billing may pay an `ISSUED` invoice, moving it to the terminal `PAID`
    state" — pay is defined only from ISSUED, so a second pay on a PAID invoice fails.

    Design: Corner/state_machines/invoice_pay_then_pay_again_idempotency_rejected
    """
    account, _cart, _plan = setup_active_account(address="117 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    invoice = _draft_invoice(account["id"])
    validate_success(api.issue_invoice(invoice["id"], BILLING), 200)
    validate_success(api.pay_invoice(invoice["id"], BILLING), 200)
    resp = api.pay_invoice(invoice["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# ═══════════════════════════════════════════════════════════════════════════
# Corner / consistency_model — issue response carries computed total immediately
# ═══════════════════════════════════════════════════════════════════════════

def test_invoice_issue_response_carries_total_immediately():
    """PRD §3.6: "On issue, `balance_cents` is set equal to `total_cents`."
    PRD §3.6 #1: "The `base_fee_cents` is the sum of `base_monthly_fee_cents` over the
    account's `ServicePlan` records that are in `ACTIVE` status."

    Design: Corner/consistency_model/invoice_issue_immediate_visibility
    """
    account, _cart, _plan = setup_active_account(address="141 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=2000)
    invoice = _draft_invoice(account["id"])
    issued = validate_success(api.issue_invoice(invoice["id"], BILLING), 200)
    assert issued["status"] == "ISSUED", f"expected ISSUED, got {issued['status']}"
    assert issued["total_cents"] == 2000, f"base-only total must be 2000, got {issued['total_cents']}"


# ═══════════════════════════════════════════════════════════════════════════
# Corner / cross_cutting — balance unchanged after voiding a PENDING credit
# ═══════════════════════════════════════════════════════════════════════════

def test_void_pending_credit_leaves_balance_zero():
    """PRD §3.7: "A `Billing` operator may also void a still-`PENDING` credit directly,
    moving it to the terminal `VOID` state."
    PRD §3.7: "Every account exposes a derived `account_balance_cents`, defined as the
    sum of `balance_cents` over the account's invoices in `ISSUED` or `DISPUTED` status,
    minus the sum of `amount_cents` over the account's credits in `APPLIED` status."

    Design: Corner/cross_cutting_complexity_layers/account_balance_recompute_after_credit_void
    """
    account, _cart, _plan = setup_active_account(address="135 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    _carrier_fault_miss(account["id"], miss_reason="MISSED_BY_CREW", service_date="2026-06-09T00:00:00Z")
    pending, _ = validate_paginated(api.list_credits(BILLING, params={"account_id": account["id"], "status": "PENDING"}))
    assert len(pending) == 1, f"expected one PENDING credit, got {len(pending)}"
    credit_id = pending[0]["id"]
    voided = validate_success(api.void_credit(credit_id, BILLING), 200)
    assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"
    acct = validate_success(api.get_account(account["id"], BILLING), 200)
    assert acct["account_balance_cents"] == 0, (
        f"voiding a PENDING credit must leave balance 0, got {acct['account_balance_cents']}"
    )
