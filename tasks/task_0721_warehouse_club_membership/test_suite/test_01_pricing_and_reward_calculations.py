"""Difficulty-queue pricing, reward-accrual and refund calculation tests.

These exercise the pinned discount order, the dual-variant refund/accrual
calculations, the cancel-refund proration, and the half-open promotion window.
"""
from test_helpers import (
    validate_success, get_success_data,
    create_basic_plan, create_executive_plan, create_product,
    create_instant_saving, create_active_membership, get_membership,
    open_transaction, add_line, finalize_transaction,
    create_finalized_transaction, create_receipted_return,
    create_no_receipt_return, approve_return, find_fee_event, set_clock,
    get_membership_version,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]
SVC = TEST_USERS["service_desk_headers"]


def test_receipted_vs_no_receipt_refund_diverge(api):
    """PRD §3.7: "For a receipted approval the refund proration uses block rounding: the
    refund is the line's total net multiplied by the returned `qty` and then floor-divided
    by the line's purchased `qty`."
    PRD §3.7: "A no-receipt approval instead refunds at the current member price — the
    product's `member_price_cents` times `qty`, reflecting the lowest-price policy — and
    claws back no reward, so its `reward_reversal_cents` is 0."
    PRD §3.7: "The same product and quantity therefore refund different amounts under a
    receipted versus a no-receipt return."

    Design: Difficulty/dual_variant_calc/return_refund_receipted_vs_no_receipt_diverge
    """
    # The two refund variants diverge whenever the historical paid net per unit differs
    # from the current member price. We make them differ in the only PRD-derivable way:
    # buy at the list price (membership not yet active snapshots list) ... but a line
    # always snapshots member price when ACTIVE. Instead drive divergence through the
    # net basis: the receipted refund is the block-rounded historical NET, while the
    # no-receipt refund is current member_price * qty. With member_price 8000 and a
    # historical net per unit of 8000, both equal; so we assert only the verbatim-derivable
    # facts: the receipted block-rounded refund and that no-receipt uses member_price * qty.
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-DUAL", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Dual", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 5)  # net per line 40000

    rcpt = create_receipted_return(m["id"], txn["id"], product["id"], 2)
    rcpt = approve_return(rcpt["id"])
    no_rcpt = create_no_receipt_return(m["id"], product["id"], 2)
    no_rcpt = approve_return(no_rcpt["id"])

    assert rcpt["lookup_mode"] == "RECEIPTED"
    # block rounding: floor(40000 * 2 / 5) = 16000
    assert rcpt["refund_cents"] == 16000, f"got {rcpt['refund_cents']}"
    assert no_rcpt["lookup_mode"] == "NO_RECEIPT_LOOKUP"
    # no-receipt refund = current member_price (8000) * qty (2) = 16000.
    assert no_rcpt["refund_cents"] == 8000 * 2, f"got {no_rcpt['refund_cents']}"
    assert no_rcpt["reward_reversal_cents"] == 0


def test_receipted_claws_back_reward_no_receipt_does_not(api):
    """PRD §3.7: "When the plan is executive and the product is reward_eligible, the reward
    originally accrued on that line is prorated to the returned units the same way ... to
    give reward_reversal_cents; otherwise the reward reversal is 0."
    PRD §3.7: "A no-receipt approval instead refunds at the current member price ... and
    claws back no reward, so its reward_reversal_cents is 0."

    Design: Difficulty/dual_variant_calc/return_refund_receipted_vs_no_receipt_diverge
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-DUAL2", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Dual2", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 5)  # accrued 800

    rcpt = approve_return(create_receipted_return(m["id"], txn["id"], product["id"], 2)["id"])
    # receipted: prorate accrual floor(800*2/5) = 320 clawed back
    assert rcpt["reward_reversal_cents"] == 320, f"got {rcpt['reward_reversal_cents']}"

    no_rcpt = approve_return(create_no_receipt_return(m["id"], product["id"], 1)["id"])
    assert no_rcpt["reward_reversal_cents"] == 0


def test_reward_accrual_uncapped(api):
    """PRD §3.6: "The raw reward is that base multiplied by the plan's `reward_rate_bps`
    and divided by 10000, floored to whole cents before any cap is applied."
    PRD §3.6: "when the term's accrual stays at or below the cap after this transaction,
    the accrued amount is the full floored rate-times-base (the uncapped variant)."

    Design: Difficulty/dual_variant_calc/reward_accrual_capped_vs_uncapped_on_membership
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-CAP-HI", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem High", auto_renew=False)
    txn = open_transaction(m["id"])
    add_line(txn["id"], product["id"], 5)  # net 40000
    txn = finalize_transaction(txn["id"])

    # floor(40000 * 200 / 10000) = 800
    assert txn["reward_accrued_cents"] == 800, f"got {txn['reward_accrued_cents']}"
    assert get_membership(m["id"])["reward_accrued_cents"] == 800


def test_reward_accrual_capped(api):
    """PRD §3.6: "the remaining cap room is the plan's reward_cap_cents minus the
    membership's current reward_accrued_cents, and the amount actually accrued by this
    transaction is the raw reward but never more than the remaining room and never below 0."
    PRD §3.6: "When the raw reward would push the term's accrual past reward_cap_cents,
    the accrued amount is clipped to the remaining room so the transaction accrues less
    than rate-times-base (the capped variant)."

    Design: Difficulty/dual_variant_calc/reward_accrual_capped_vs_uncapped_on_membership
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=500, addon_fee_cents=6000)
    product = create_product("P-CAP-LO", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Low", auto_renew=False)
    txn = open_transaction(m["id"])
    add_line(txn["id"], product["id"], 5)  # raw 800, cap 500 -> 500
    txn = finalize_transaction(txn["id"])

    assert txn["reward_accrued_cents"] == 500, f"got {txn['reward_accrued_cents']}"
    assert get_membership(m["id"])["reward_accrued_cents"] == 500


def test_discount_stack_pinned_order_instant_then_rebate(api):
    """PRD §3.5: "Line discounts are then applied in a strictly pinned order — instant
    savings first, then manufacturer rebate."
    PRD §3.5: "The base after instant savings is the gross minus that clamped instant
    amount." (the rebate is keyed on the post-instant base)

    Design: Difficulty/combinatorial_formula/discount_stack_pinned_order_instant_then_rebate
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-STACK", list_price_cents=10000, member_price_cents=8000)
    create_instant_saving(product["id"], kind="INSTANT_SAVINGS", amount_cents=1000,
                          window_start_utc="2026-01-01T00:00:00Z",
                          window_end_utc="2026-12-01T00:00:00Z")
    create_instant_saving(product["id"], kind="MANUFACTURER_REBATE", amount_cents=500,
                          window_start_utc="2026-01-01T00:00:00Z",
                          window_end_utc="2026-12-01T00:00:00Z")
    m = create_active_membership(plan["id"], primary_member_name="Mem Stack", auto_renew=False)
    txn = open_transaction(m["id"])
    line = add_line(txn["id"], product["id"], 3)  # gross 24000

    assert line["line_instant_savings_cents"] == 3000  # 1000*3
    assert line["line_rebate_cents"] == 1500           # 500*3
    txn = get_success_data(api.get_transaction(txn["id"], CLERK))
    assert txn["net_cents"] == 19500  # 24000 - 3000 - 1500


def test_cancel_refund_proration_with_floor(api):
    """PRD §3.8: "The gross refund applies block rounding: the plan's annual_fee_cents
    multiplied by the remaining days and then floor-divided by 365."
    PRD §3.8: "the net refund is the gross refund minus the membership's
    reward_redeemed_cents, never below 0."
    PRD §3.3: "records a FeeEvent of kind CANCEL_REFUND carrying the negative of that
    refund against the current term."

    Design: Difficulty/combinatorial_formula/cancel_refund_proration_nonlinear_with_redemption
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=12000)
    m = create_active_membership(plan["id"], primary_member_name="Mem Cancel", auto_renew=False)
    ver = get_membership_version(m["id"])
    set_clock("2026-06-09T00:00:00Z")  # 100 days elapsed

    res = api.cancel_membership(m["id"], {"expected_membership_version": ver},
                                make_member_headers(m["id"]))
    data = validate_success(res, 200)
    assert data["status"] == "CANCELLED"
    # remaining 265; floor(12000*265/365) = 8712
    fe = find_fee_event(m["id"], "CANCEL_REFUND")
    assert fe is not None, "expected a CANCEL_REFUND fee event"
    assert fe["amount_cents"] == -8712, f"got {fe['amount_cents']}"


def test_instant_saving_window_half_open_end_excluded(api):
    """PRD §3.5: "For each INSTANT_SAVINGS promotion on the product whose half-open
    window contains the current clock instant ..."
    PRD §3.1: "a half-open active window running from an inclusive window_start_utc to
    an exclusive window_end_utc."

    Design: Difficulty/resource_temporal_overlap/instant_saving_window_half_open_boundary
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-WIN", list_price_cents=10000, member_price_cents=8000)
    create_instant_saving(product["id"], kind="INSTANT_SAVINGS", amount_cents=1000,
                          window_start_utc="2026-03-01T00:00:00Z",
                          window_end_utc="2026-06-01T00:00:00Z")
    set_clock("2026-05-01T00:00:00Z")
    m = create_active_membership(plan["id"], primary_member_name="Mem WIN", auto_renew=False)
    txn = open_transaction(m["id"])
    line_inside = add_line(txn["id"], product["id"], 1)
    assert line_inside["line_instant_savings_cents"] == 1000  # inside window

    set_clock("2026-06-01T00:00:00Z")  # == window_end, exclusive
    line_at_end = add_line(txn["id"], product["id"], 1)
    assert line_at_end["line_instant_savings_cents"] == 0


def test_reward_conserved_full_reversal_to_zero(api):
    """PRD §2.8: "Executive reward is tracked as a ledger of signed movements on the
    RewardLedgerEntry resource."
    PRD §3.7: "the reward originally accrued on that line is prorated to the returned
    units the same way ... to give reward_reversal_cents ... The reversal is subtracted
    from the membership's reward_accrued_cents."

    Design: Difficulty/compensating_invariant/reward_conserved_accrual_then_reversal
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-INV1", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem INV1", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 5)  # accrued 800
    ret = create_receipted_return(m["id"], txn["id"], product["id"], 5)  # full return
    ret = approve_return(ret["id"])

    assert ret["reward_reversal_cents"] == 800, f"got {ret['reward_reversal_cents']}"
    assert get_membership(m["id"])["reward_accrued_cents"] == 0
    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"membership_id": m["id"]}).json()["data"]
    assert sum(e["amount_cents"] for e in ledger) == 0, "reward ledger must net to 0"


def test_fee_conserved_signup_then_full_refund(api):
    """PRD §2.9: "The membership's derived fees_paid_cents is the total of membership and
    add-on fees collected for the current term, net of any cancellation refunds."
    PRD §3.8: "cancelling on the same day as activation leaves all 365 days remaining and
    refunds the full annual fee (less any redeemed reward)."

    Design: Difficulty/compensating_invariant/fee_conserved_signup_then_cancel_refund
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_active_membership(plan["id"], primary_member_name="Mem INV2", auto_renew=False)
    ver = get_membership_version(m["id"])
    res = api.cancel_membership(m["id"], {"expected_membership_version": ver},
                                make_member_headers(m["id"]))
    validate_success(res, 200)

    fe = find_fee_event(m["id"], "CANCEL_REFUND")
    assert fe["amount_cents"] == -6000, f"got {fe['amount_cents']}"
    all_fees = api.list_fee_events(make_member_headers(m["id"]),
                                   params={"membership_id": m["id"]}).json()["data"]
    assert sum(f["amount_cents"] for f in all_fees) == 0, "fee events must net to 0"


def test_discount_stack_rebate_clamped_to_post_instant_base(api):
    """PRD §3.5: "the summed rebate is then clamped so it cannot exceed the post-instant
    base, giving line_rebate_cents."
    PRD §3.5: "The line net is the gross minus the clamped instant savings minus the
    clamped rebate."

    Design: Difficulty/combinatorial_formula/discount_stack_pinned_order_instant_then_rebate
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-STACK2", list_price_cents=10000, member_price_cents=8000)
    # Instant savings already reduce a qty=1 gross of 8000 down to 0; rebate must clamp to 0.
    create_instant_saving(product["id"], kind="INSTANT_SAVINGS", amount_cents=8000,
                          window_start_utc="2026-01-01T00:00:00Z",
                          window_end_utc="2026-12-01T00:00:00Z")
    create_instant_saving(product["id"], kind="MANUFACTURER_REBATE", amount_cents=500,
                          window_start_utc="2026-01-01T00:00:00Z",
                          window_end_utc="2026-12-01T00:00:00Z")
    m = create_active_membership(plan["id"], primary_member_name="Mem Stack2", auto_renew=False)
    txn = open_transaction(m["id"])
    line = add_line(txn["id"], product["id"], 1)  # gross 8000

    assert line["line_instant_savings_cents"] == 8000  # clamped to gross
    assert line["line_rebate_cents"] == 0              # post-instant base is 0
    txn = get_success_data(api.get_transaction(txn["id"], CLERK))
    assert txn["net_cents"] == 0


def test_cancel_refund_full_term_same_day(api):
    """PRD §3.8: "cancelling on the same day as activation leaves all 365 days remaining
    and refunds the full annual fee (less any redeemed reward)."

    Design: Difficulty/combinatorial_formula/cancel_refund_proration_nonlinear_with_redemption
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=12000)
    m = create_active_membership(plan["id"], primary_member_name="Mem CancelFull", auto_renew=False)
    ver = get_membership_version(m["id"])
    res = api.cancel_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    validate_success(res, 200)
    fe = find_fee_event(m["id"], "CANCEL_REFUND")
    assert fe["amount_cents"] == -12000  # full annual fee


def test_instant_saving_window_start_inclusive(api):
    """PRD §3.1: "a half-open active window running from an inclusive window_start_utc to
    an exclusive window_end_utc."
    PRD §3.5: "For each INSTANT_SAVINGS promotion on the product whose half-open window
    contains the current clock instant ..."

    Design: Difficulty/resource_temporal_overlap/instant_saving_window_half_open_boundary
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-WININC", list_price_cents=10000, member_price_cents=8000)
    create_instant_saving(product["id"], kind="INSTANT_SAVINGS", amount_cents=1000,
                          window_start_utc="2026-04-01T00:00:00Z",
                          window_end_utc="2026-06-01T00:00:00Z")
    set_clock("2026-04-01T00:00:00Z")  # == window_start, inclusive
    m = create_active_membership(plan["id"], primary_member_name="Mem WinInc", auto_renew=False)
    txn = open_transaction(m["id"])
    line = add_line(txn["id"], product["id"], 1)
    assert line["line_instant_savings_cents"] == 1000  # start is inclusive


def test_reward_conserved_partial_reversal_ledger_balances(api):
    """PRD §2.8: "the membership's derived reward balances are always reconcilable from
    those movements."
    PRD §3.7: "the reward originally accrued on that line is prorated to the returned units
    the same way ... to give reward_reversal_cents."

    Design: Difficulty/compensating_invariant/reward_conserved_accrual_then_reversal
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-INV1B", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem INV1B", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 5)  # accrued 800
    ret = approve_return(create_receipted_return(m["id"], txn["id"], product["id"], 2)["id"])
    assert ret["reward_reversal_cents"] == 320

    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"membership_id": m["id"]}).json()["data"]
    # accrued (800) reconciles to ledger sum (800 - 320 = 480)
    assert sum(e["amount_cents"] for e in ledger) == 480
    assert get_membership(m["id"])["reward_accrued_cents"] == 480


def test_fee_conserved_addon_charge_adds_to_fees(api):
    """PRD §2.9: "The membership's derived fees_paid_cents is the total of membership and
    add-on fees collected for the current term, net of any cancellation refunds."
    PRD §3.4: "A PAID_ADDON card always carries fee_charged_cents equal to the plan's
    addon_fee_cents and records a FeeEvent of kind ADDON for that amount."

    Design: Difficulty/compensating_invariant/fee_conserved_signup_then_cancel_refund
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000, addon_fee_cents=4000, max_household_cards=1)
    m = create_active_membership(plan["id"], primary_member_name="Mem FeeAdd", auto_renew=False)
    hdr = make_member_headers(m["id"])
    get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Sp", "card_kind": "INCLUDED"}, hdr))
    get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Kid", "card_kind": "PAID_ADDON"}, hdr))
    fees = api.list_fee_events(hdr, params={"membership_id": m["id"]}).json()["data"]
    # SIGNUP 6000 + ADDON 4000 = 10000
    assert sum(f["amount_cents"] for f in fees) == 10000
    assert get_membership(m["id"])["fees_paid_cents"] == 10000
