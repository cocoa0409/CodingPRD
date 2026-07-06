"""Corner-queue calculation claims not owned by a difficulty instance."""
from test_helpers import (
    validate_success, get_success_data,
    create_basic_plan, create_executive_plan, create_product,
    create_instant_saving, create_active_membership, get_membership,
    set_clock, get_membership_version,
    open_transaction, add_line, finalize_transaction,
    create_finalized_transaction,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]


def test_line_discount_instant_only_no_rebate(api):
    """PRD §3.5: "For each INSTANT_SAVINGS promotion on the product whose half-open window
    contains the current clock instant, the discounted units are the line qty when the
    promotion's max_units is 0 ... and that promotion contributes its amount_cents times
    those units."

    Design: Corner/calculations/line_discount_instant_only_no_rebate
    """
    plan = create_basic_plan()
    product = create_product("P-ISONLY", list_price_cents=10000, member_price_cents=8000)
    create_instant_saving(product["id"], kind="INSTANT_SAVINGS", amount_cents=1000,
                          window_start_utc="2026-03-01T00:00:00Z",
                          window_end_utc="2026-12-01T00:00:00Z")
    set_clock("2026-04-01T00:00:00Z")
    m = create_active_membership(plan["id"], primary_member_name="ISonly Mem")
    txn = open_transaction(m["id"])
    line = add_line(txn["id"], product["id"], 2)
    assert line["line_instant_savings_cents"] == 2000  # 1000 * 2
    assert line["line_rebate_cents"] == 0
    txn = get_success_data(api.get_transaction(txn["id"], CLERK))
    assert txn["net_cents"] == 14000  # 16000 - 2000


def test_instant_saving_max_units_caps_units(api):
    """PRD §3.5: "the discounted units are the line qty when the promotion's max_units is 0,
    otherwise the smaller of qty and max_units, and that promotion contributes its
    amount_cents times those units."

    Design: Corner/calculations/instant_saving_max_units_caps_discounted_units
    """
    plan = create_basic_plan()
    product = create_product("P-MAXU", list_price_cents=10000, member_price_cents=8000)
    create_instant_saving(product["id"], kind="INSTANT_SAVINGS", amount_cents=1000,
                          window_start_utc="2026-03-01T00:00:00Z",
                          window_end_utc="2026-12-01T00:00:00Z", max_units=2)
    set_clock("2026-04-01T00:00:00Z")
    m = create_active_membership(plan["id"], primary_member_name="MaxU Mem")
    txn = open_transaction(m["id"])
    line = add_line(txn["id"], product["id"], 5)
    assert line["line_instant_savings_cents"] == 2000  # only 2 of 5 units discounted


def test_basic_member_accrues_zero_reward(api):
    """PRD §3.6: "Reward accrual earns nothing on a basic plan: when the plan's tier is not
    EXECUTIVE, the transaction accrues 0."

    Design: Corner/calculations/basic_member_accrues_zero_reward
    """
    plan = create_basic_plan()
    product = create_product("P-BASICR", reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="BasicR Mem")
    txn, line = create_finalized_transaction(m["id"], product["id"], 5)
    assert txn["reward_accrued_cents"] == 0
    assert get_membership(m["id"])["reward_accrued_cents"] == 0


def test_reward_excludes_non_eligible_lines(api):
    """PRD §3.6: "On an executive plan, the reward base is the sum of the net amounts of the
    lines whose product is reward_eligible."

    Design: Corner/calculations/reward_excludes_non_eligible_lines
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    prod_a = create_product("P-ELIG", reward_eligible=True)
    prod_b = create_product("P-NOELIG", reward_eligible=False)
    m = create_active_membership(plan["id"], primary_member_name="Elig Mem")
    txn = open_transaction(m["id"])
    add_line(txn["id"], prod_a["id"], 5)  # eligible net 40000
    add_line(txn["id"], prod_b["id"], 5)  # non-eligible net 40000
    txn = finalize_transaction(txn["id"])
    assert txn["reward_accrued_cents"] == 800  # floor(40000*200/10000)


def test_cancel_refund_full_term_same_day(api):
    """PRD §3.8: "cancelling on the same day as activation leaves all 365 days remaining and
    refunds the full annual fee (less any redeemed reward)."

    Design: Corner/calculations/cancel_refund_full_term_same_day
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_active_membership(plan["id"], primary_member_name="FullRef Mem", auto_renew=False)
    ver = get_membership_version(m["id"])
    res = api.cancel_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    validate_success(res, 200)
    fees = api.list_fee_events(make_member_headers(m["id"]),
                               params={"membership_id": m["id"], "kind": "CANCEL_REFUND"}).json()["data"]
    cr = [f for f in fees if f["kind"] == "CANCEL_REFUND"]
    assert cr[0]["amount_cents"] == -6000


def test_payment_redemption_reduces_renewal_fee(api):
    """PRD §3.8: "The amount actually applied is the requested redeem_reward_cents ... The
    payment's amount_cents is the annual fee minus the applied amount, the applied amount is
    added to the membership's reward_redeemed_cents, and a RewardLedgerEntry of type
    REDEMPTION carrying the negative applied amount is written when the applied amount is
    positive."

    Design: Corner/calculations/payment_amount_with_redemption_reduces_renewal_fee
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-REDEEM", reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Redeem Mem", auto_renew=False)
    create_finalized_transaction(m["id"], product["id"], 5)  # accrued 800
    ver = get_membership_version(m["id"])
    res = api.renew_membership(m["id"], {"expected_membership_version": ver,
                                         "redeem_reward_cents": 800}, make_member_headers(m["id"]))
    validate_success(res, 200)
    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"membership_id": m["id"], "entry_type": "REDEMPTION"}).json()["data"]
    redemptions = [e for e in ledger if e["entry_type"] == "REDEMPTION"]
    assert len(redemptions) == 1
    assert redemptions[0]["amount_cents"] == -800
    # NOTE: PRD §3.3 says renewal "resets reward_accrued_cents and reward_redeemed_cents
    # to 0 for the new term", so the derived counter is 0 once the term rolls. The
    # redemption is preserved auditably in the ledger (asserted above), which is the
    # uniquely PRD-derivable observable; the prior post-renewal reward_redeemed_cents==800
    # assertion contradicted §3.3's reset clause and was removed (STEP 1c partial split).
