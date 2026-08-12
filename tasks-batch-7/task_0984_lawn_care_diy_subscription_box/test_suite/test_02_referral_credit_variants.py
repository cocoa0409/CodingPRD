"""Referral credit: provisional flat amount vs qualified share (PRD 3.9)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_referral_credit_provisional_vs_qualified(api):
    """PRD 3.2: "While the referral remains `PENDING`, it displays a flat `provisional_credit_cents` of 2,000 cents regardless of any invoice; the real reward is computed later at qualification time, as Section 3.9 describes."
    PRD 3.9: "`qualified_credit_cents` is computed as twenty percent of that first paid invoice's `total_cents`, rounded half up to whole cents, and capped at 5,000 cents, with the evaluation order pinned so the invoice total is computed first, then the twenty-percent share, then the cap."
    PRD 3.9: "The referral records the triggering invoice in `referee_first_invoice_id` and posts an `EARN_REFERRAL` ledger entry of `qualified_credit_cents` to the referrer — only the qualified amount is ever posted, never the provisional figure."

    Design: Difficulty/dual_variant_calc/referral_credit_provisional_vs_qualified
    """
    result = th.setup_qualified_referral(
        box_qty=3, referrer_email="ref-r@x.com", referee_email="ref-e@x.com"
    )
    # Provisional variant while PENDING: flat 2000 regardless of any invoice.
    assert result["referral_pending"]["status"] == "PENDING"
    assert result["referral_pending"]["provisional_credit_cents"] == 2000

    # Invoice: 3 x 800 (tier t1) with no early-season discount on 2026-06-10.
    assert result["invoice"]["total_cents"] == 2400

    referral = result["referral"]
    assert referral["status"] == "QUALIFIED"
    assert referral["qualified_credit_cents"] == 480, (
        f"qualified must be min(5000, round_half_up(0.20 x 2400)) = 480, got {referral['qualified_credit_cents']}"
    )
    assert referral["qualified_credit_cents"] != 2000, (
        "qualified variant diverges from the flat provisional 2000"
    )
    assert referral["referee_first_invoice_id"] == result["invoice"]["id"]

    # The EARN_REFERRAL entry lands on the referrer, not the referee.
    assert th.get_customer_balance(result["referrer"]["id"]) == 480


def test_referral_qualified_credit_capped_at_5000(api):
    """PRD 3.9: "`qualified_credit_cents` is computed as twenty percent of that first paid invoice's `total_cents`, rounded half up to whole cents, and capped at 5,000 cents, with the evaluation order pinned so the invoice total is computed first, then the twenty-percent share, then the cap."

    Design: Difficulty/dual_variant_calc/referral_credit_provisional_vs_qualified
    """
    # 38 x 800 = 30400 invoice total; 20% = 6080 -> capped at 5000.
    result = th.setup_qualified_referral(
        box_qty=38, referrer_email="cap-r@x.com", referee_email="cap-e@x.com"
    )
    assert result["invoice"]["total_cents"] == 30400
    referral = result["referral"]
    assert referral["status"] == "QUALIFIED"
    assert referral["qualified_credit_cents"] == 5000, (
        f"20% of 30400 is 6080, capped at 5000; got {referral['qualified_credit_cents']}"
    )
    assert th.get_customer_balance(result["referrer"]["id"]) == 5000
