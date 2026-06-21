"""Cascades, refunds, and conserved-quantity invariants (PRD §2.9, §3.3, §3.5, §3.10).

Translates queue-A transitive_cascade, compensating_invariant, and the UNLIMITED
cancellation-refund dual_variant instance, plus queue-B calculation corners.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_plan_payload, create_single_wash_plan_payload, create_addon_payload,
    create_location_payload, adjustment_payload,
    TEST_USERS, make_account_holder_headers,
    setup_unlimited_active, setup_single_wash_active,
    create_plan, create_single_wash_plan, create_location, create_account,
    create_vehicle, enroll_membership, pay_first_cycle_invoice, fund_wallet,
    attach_one_addon, set_clock, simulate, submit_wash, latest_wallet_transaction,
)

PA = TEST_USERS["platform_admin_headers"]
BA = TEST_USERS["billing_admin_headers"]


# ─── Queue A: transitive_cascade / account_suspend_cascade_depth3 ──────────

def _setup_membership_with_addon():
    """ACTIVE UNLIMITED membership with one ACTIVE add-on. Returns (account, membership, ma)."""
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="CAS003"
    )
    addon = api_client_create_addon("WAX2", 800)
    ma = attach_one_addon(membership["id"], addon["id"], account["id"])
    return account, membership, ma


def api_client_create_addon(name, fee):
    return validate_success(api_client.create_addon(create_addon_payload(name=name, recurring_fee_cents=fee), PA), 201)


def test_suspend_cascades_account_membership_addon(api):
    """PRD §3.10: "Suspension cascades: every membership of that account that is `ACTIVE`
    or `PAST_DUE` is driven to `FROZEN` (the first cascade hop), which in turn applies the
    freeze refund and pauses that membership's add-ons (the second and third hops)."

    Design: Difficulty/transitive_cascade/account_suspend_cascade_depth3
    """
    account, membership, ma = _setup_membership_with_addon()
    suspended = validate_success(api.suspend_account(account["id"], PA), 200)
    assert suspended["status"] == "SUSPENDED"

    mem = validate_success(api.get_membership(membership["id"], PA), 200)
    assert mem["status"] == "FROZEN", "suspend drives ACTIVE membership to FROZEN (hop 1)"
    ma_after = validate_success(api.get_membership_addon(ma["id"], PA), 200)
    assert ma_after["status"] == "PAUSED", "the freeze pauses the active add-on (hop 3)"


def test_suspend_pauses_active_addon_only(api):
    """PRD §3.9: "Freezing the membership pauses each `ACTIVE` add-on to `PAUSED`".
    PRD §3.10: "every membership of that account that is `ACTIVE` or `PAST_DUE` is driven
    to `FROZEN` ... which in turn applies the freeze refund and pauses that membership's
    add-ons".

    Design: Difficulty/transitive_cascade/account_suspend_cascade_depth3
    """
    account, membership, ma = _setup_membership_with_addon()
    assert ma["status"] == "ACTIVE", "add-on starts ACTIVE before suspension"
    validate_success(api.suspend_account(account["id"], PA), 200)
    ma_after = validate_success(api.get_membership_addon(ma["id"], PA), 200)
    assert ma_after["status"] == "PAUSED"


# ─── Queue A: transitive_cascade / invoice_paid_reactivates_membership_depth2 ───

def _setup_past_due_membership():
    """ACTIVE UNLIMITED membership; advance a cycle; billing issues a new CYCLE invoice
    that is DECLINED -> membership PAST_DUE, invoice FAILED. Returns (membership_id, inv1_id, hdr)."""
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="PDU004"
    )
    hdr = make_account_holder_headers(account["id"])
    set_clock("2026-07-01T00:00:00Z")
    issued = validate_success(api_client.billing_run({"membership_id": membership["id"]}, BA), 200)
    inv1 = issued[0]
    simulate(inv1["id"], "DECLINED")
    return membership["id"], inv1["id"], hdr


def test_retry_paid_reactivates_membership(api):
    """PRD §3.4: "A retry that is then resolved successfully moves the invoice from
    `RETRYING` to `PAID`, and that success transitions the membership from `PAST_DUE` back
    to `ACTIVE`".

    Design: Difficulty/transitive_cascade/invoice_paid_reactivates_membership_depth2
    """
    mem_id, inv_id, hdr = _setup_past_due_membership()
    validate_success(api.retry_invoice(inv_id, BA), 200)
    simulate(inv_id, "SUCCEEDED")
    mem = validate_success(api.get_membership(mem_id, hdr), 200)
    assert mem["status"] == "ACTIVE", "RETRYING->PAID reactivates the PAST_DUE membership"


def test_failed_cycle_charge_moves_membership_past_due(api):
    """PRD §3.4: "A failed charge moves the invoice to `FAILED`; when the failing invoice
    is a cycle charge against an `ACTIVE` membership, that failure transitions the
    membership from `ACTIVE` to `PAST_DUE`."

    Design: Difficulty/transitive_cascade/invoice_paid_reactivates_membership_depth2
    """
    mem_id, inv_id, hdr = _setup_past_due_membership()
    mem = validate_success(api.get_membership(mem_id, hdr), 200)
    assert mem["status"] == "PAST_DUE", "declined cycle charge moves the membership to PAST_DUE"
    inv = validate_success(api.get_invoice(inv_id, hdr), 200)
    assert inv["status"] == "FAILED"


# ─── Queue A: dual_variant_calc / cancellation_refund_unlimited_unused_value ───

def _setup_unlimited_cancel_midcycle():
    """UNLIMITED membership (fee 3000) PAID at 2026-06-01; clock to 2026-06-12 (11 elapsed,
    19 remaining). Returns (account_id, membership_id, hdr)."""
    plan, account, vehicle, membership = setup_unlimited_active(
        monthly_fee_cents=3000, clock="2026-06-01T00:00:00Z", license_plate="ABC123"
    )
    hdr = make_account_holder_headers(account["id"])
    set_clock("2026-06-12T00:00:00Z")
    return account["id"], membership["id"], hdr


def test_unlimited_cancel_refunds_forward_looking_unused_value(api):
    """PRD §3.10: "For an `UNLIMITED` membership the refund is forward-looking — the unused
    value of the cycle: `current_cycle_paid_cents` multiplied by the remaining days of the
    cycle, divided by the 30-day cycle length, rounded half-up to whole cents, regardless
    of how many washes were taken."

    Design: Difficulty/dual_variant_calc/cancellation_refund_unlimited_unused_value
    """
    account_id, mem_id, hdr = _setup_unlimited_cancel_midcycle()
    cancelled = validate_success(api.cancel_membership(mem_id, hdr), 200)
    assert cancelled["status"] == "CANCEL_SCHEDULED"
    acct = validate_success(api.get_account(account_id, hdr), 200)
    # round_half_up(3000 * 19/30) = round(1900) = 1900.
    assert acct["wallet_balance_cents"] == 1900, \
        f"UNLIMITED unused-value refund = 1900; wallet got {acct['wallet_balance_cents']}"


def test_unlimited_cancel_writes_cancel_refund_transaction(api):
    """PRD §3.10: "the refund owed is computed and credited to the wallet immediately via a
    `WalletTransaction` of reason `CANCEL_REFUND`."

    Design: Difficulty/dual_variant_calc/cancellation_refund_unlimited_unused_value
    """
    account_id, mem_id, hdr = _setup_unlimited_cancel_midcycle()
    validate_success(api.cancel_membership(mem_id, hdr), 200)
    txns = validate_success(api.list_wallet_transactions(account_id, hdr), 200)
    refunds = [t for t in txns if t["reason"] == "CANCEL_REFUND"]
    assert refunds, "a CANCEL_REFUND wallet transaction must be written"
    assert refunds[-1]["amount_cents"] == 1900, \
        f"CANCEL_REFUND amount expected 1900, got {refunds[-1]['amount_cents']}"


# ─── Queue A: compensating_invariant / wallet_conservation_refund_then_topup_debit ───

def _setup_wallet_conservation():
    """One INDIVIDUAL account, an UNLIMITED(3000) membership and a SINGLE_WASH membership,
    both ACTIVE+PAID. Cancel the UNLIMITED at 2026-06-12 (refund 1900), then topup 1 credit
    on the SINGLE_WASH (debit 1200). Returns account_id."""
    set_clock("2026-06-01T00:00:00Z")
    plan_u = create_plan(name="UWal", monthly_fee_cents=3000, max_addons=3)
    plan_s = create_single_wash_plan(name="SWal", included_credits=2, per_credit_price_cents=1200)
    acct = create_account(contact_email="p@x.com")
    hdr = make_account_holder_headers(acct["id"])
    veh1 = create_vehicle(acct["id"], "WAL014", "CA", hdr)
    veh2 = create_vehicle(acct["id"], "WAL015", "CA", hdr)
    mem_u = enroll_membership(acct["id"], veh1["id"], plan_u["id"], hdr)
    pay_first_cycle_invoice(mem_u["id"], acct["id"], hdr)
    mem_s = enroll_membership(acct["id"], veh2["id"], plan_s["id"], hdr)
    pay_first_cycle_invoice(mem_s["id"], acct["id"], hdr)
    set_clock("2026-06-12T00:00:00Z")
    validate_success(api_client.cancel_membership(mem_u["id"], hdr), 200)
    mem_s_now = validate_success(api_client.get_membership(mem_s["id"], hdr), 200)
    validate_success(
        api_client.topup_membership(
            mem_s["id"], {"credit_quantity": 1, "expected_membership_version": mem_s_now["version"]}, hdr
        ), 201,
    )
    return acct["id"], hdr


def test_wallet_balance_after_refund_and_topup(api):
    """PRD §3.10: "For an `UNLIMITED` membership the refund is forward-looking ... rounded
    half-up to whole cents".
    PRD §3.5: "The system raises a `TOPUP` invoice, debits the wallet with a
    `WalletTransaction` of reason `TOPUP_DEBIT`".

    Design: Difficulty/compensating_invariant/wallet_conservation_refund_then_topup_debit
    """
    account_id, hdr = _setup_wallet_conservation()
    acct = validate_success(api.get_account(account_id, hdr), 200)
    # +1900 (CANCEL_REFUND) - 1200 (TOPUP_DEBIT, 1 credit @ 1200) = 700.
    assert acct["wallet_balance_cents"] == 700, \
        f"wallet should be 1900 - 1200 = 700; got {acct['wallet_balance_cents']}"


def test_latest_ledger_balance_after_equals_wallet_balance(api):
    """PRD §2.9: "Because the ledger is chronological, the `balance_after_cents` of the
    latest transaction always equals the account's current `wallet_balance_cents`."

    Design: Difficulty/compensating_invariant/wallet_conservation_refund_then_topup_debit
    """
    account_id, hdr = _setup_wallet_conservation()
    acct = validate_success(api.get_account(account_id, hdr), 200)
    latest = latest_wallet_transaction(account_id, hdr)
    assert latest is not None, "there must be wallet transactions after refund+topup"
    assert latest["balance_after_cents"] == acct["wallet_balance_cents"], \
        "latest balance_after_cents must equal the account wallet_balance_cents (no drift)"
    assert latest["balance_after_cents"] == 700


# ─── Queue A: compensating_invariant / entitlement_conservation_grant_minus_consumed ───

def _setup_entitlement_conservation():
    """SINGLE_WASH membership included_credits=3 (granted 3); wallet funded +5000; topup 1
    credit (granted 4); one wash consumes 1. Returns (account_id, membership_id, hdr)."""
    set_clock("2026-06-01T00:00:00Z")
    plan = create_single_wash_plan(name="SEnt", included_credits=3, per_credit_price_cents=1200)
    loc = create_location(name="EntSite", daily_wash_capacity=50, in_network=True)
    acct = create_account(contact_email="q@x.com")
    fund_wallet(acct["id"], 5000)
    hdr = make_account_holder_headers(acct["id"])
    veh = create_vehicle(acct["id"], "ENT016", "CA", hdr)
    mem = enroll_membership(acct["id"], veh["id"], plan["id"], hdr)
    pay_first_cycle_invoice(mem["id"], acct["id"], hdr)
    mem_now = validate_success(api_client.get_membership(mem["id"], hdr), 200)
    validate_success(
        api_client.topup_membership(
            mem["id"], {"credit_quantity": 1, "expected_membership_version": mem_now["version"]}, hdr
        ), 201,
    )
    submit_wash(loc["id"], "ENT016", "CA")
    return acct["id"], mem["id"], hdr


def test_entitlement_counts_after_grant_topup_and_consume(api):
    """PRD §3.3: "For a `SINGLE_WASH` plan, activation also grants the plan's
    `included_credits`: the cumulative `credits_granted` counter rises by that amount."
    PRD §3.5: "raises the membership's `credits_granted` by `credit_quantity`".
    PRD §3.6: "raises the membership's `credits_consumed` by 1".

    Design: Difficulty/compensating_invariant/entitlement_conservation_grant_minus_consumed
    """
    account_id, mem_id, hdr = _setup_entitlement_conservation()
    mem = validate_success(api.get_membership(mem_id, hdr), 200)
    assert mem["credits_granted"] == 4, f"granted 3 + topup 1 = 4; got {mem['credits_granted']}"
    assert mem["credits_consumed"] == 1, f"one wash consumes 1; got {mem['credits_consumed']}"


def test_credit_balance_equals_granted_minus_consumed(api):
    """PRD §3.3: "The membership exposes `credit_balance`, which for a `SINGLE_WASH` plan
    is `credits_granted` minus `credits_consumed`".

    Design: Difficulty/compensating_invariant/entitlement_conservation_grant_minus_consumed
    """
    account_id, mem_id, hdr = _setup_entitlement_conservation()
    mem = validate_success(api.get_membership(mem_id, hdr), 200)
    assert mem["credit_balance"] == 3, f"balance = 4 - 1 = 3; got {mem['credit_balance']}"
    assert mem["credit_balance"] == mem["credits_granted"] - mem["credits_consumed"]


# ─── Queue B: calculation + derived-field corners ─────────────────────────

def test_single_wash_cancel_refund_floors_at_zero(api):
    """PRD §3.10: "For a `SINGLE_WASH` membership the refund is the consumed value instead:
    `current_cycle_paid_cents` minus the number of credits consumed this cycle multiplied
    by a per-wash value of 400 cents, ignoring remaining days. Either way the refund is
    floored at 0 — a computed refund below zero is treated as zero."

    Design: Corner/calculations/cancellation_refund_single_wash_consumed_variant
    """
    plan, account, vehicle, membership = setup_single_wash_active(
        included_credits=2, clock="2026-06-01T00:00:00Z", license_plate="SCN001"
    )
    hdr = make_account_holder_headers(account["id"])
    set_clock("2026-06-12T00:00:00Z")
    cancelled = validate_success(api.cancel_membership(membership["id"], hdr), 200)
    assert cancelled["status"] == "CANCEL_SCHEDULED"
    acct = validate_success(api.get_account(account["id"], hdr), 200)
    # current_cycle_paid_cents == 0 (free included credits) -> consumed_value refund floors at 0.
    assert acct["wallet_balance_cents"] == 0, \
        f"consumed-value refund floors at 0 when paid is 0; wallet got {acct['wallet_balance_cents']}"


def test_wallet_balance_reconciles_after_two_adjustments(api):
    """PRD §2.9: "An account's `wallet_balance_cents` equals the sum of the `amount_cents`
    of every wallet transaction belonging to that account, considered in chronological
    order by `created_at` ascending."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_wallet_after_adjustment
    """
    acct = create_account(contact_email="der@x.com")
    validate_success(api.create_adjustment(acct["id"], adjustment_payload(2500), BA), 201)
    validate_success(api.create_adjustment(acct["id"], adjustment_payload(1500), BA), 201)
    refreshed = validate_success(api.get_account(acct["id"], BA), 200)
    assert refreshed["wallet_balance_cents"] == 4000, \
        f"2500 + 1500 = 4000; got {refreshed['wallet_balance_cents']}"
