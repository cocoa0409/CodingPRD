"""Formulas whose rounding order and evaluation order are pinned."""

from test_helpers import (
    ADMIN,
    GUEST,
    assert_invoice_components,
    assert_reservation_state,
    create_classic_tier,
    create_member,
    create_open_park,
    create_president_tier,
    list_invoices,
    make_membership_payload,
    make_transient_reservation_payload,
    read_membership,
    reset_clock,
    validate_success,
)


def test_transient_charge_rounds_each_night_before_summing(api):
    """Each peak weekend night rounds up on its own, so the total lands a cent higher.

    PRD §3.4: "Two peak-weekend nights at a `CLASS_B` park illustrate it: each
    night is 6,200 multiplied by 1.35 and by 1.15, which is 9,625.5 cents,
    rounding half up to 9,626, so the subtotal is 19,252 cents — not the 19,251
    that a single rounding of 19,251.0 would produce."

    Design: Difficulty/combinatorial_formula/transient_stay_charge_rounds_each_night_then_sums
    """
    reset_clock(api)
    park = create_open_park(
        api,
        name="Dune Crest RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    response = api.create_transient_reservation(
        make_transient_reservation_payload(
            park["id"], "2026-08-14", "2026-08-16", guest_name="Priya Raman"
        ),
        GUEST,
    )
    reservation = validate_success(response, 201)

    assert reservation["nights"] == 2, "2026-08-14 up to but not including 2026-08-16"
    # 9626 + 9626 = 19252 subtotal; 9% resort fee 1732.68 -> 1733; 20985 total.
    assert reservation["total_charge_cents"] == 20985, (
        "per-night rounding then summing, then a single resort-fee rounding"
    )
    assert reservation["total_charge_cents"] != 20984, (
        "summing the unrounded 9625.5 night rates first is the wrong reading"
    )


def test_transient_stay_holds_a_public_pad_and_debits_no_entitlement(api):
    """The cash-paying public occupies the transient pool and no night ledger.

    PRD §3.4: "A public booking debits no entitlement and no partner quota, so
    `entitlement_nights_charged` and `affiliate_nights_charged` both remain 0."

    Design: Difficulty/combinatorial_formula/transient_stay_charge_rounds_each_night_then_sums
    """
    reset_clock(api)
    park = create_open_park(
        api,
        name="Dune Crest RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    response = api.create_transient_reservation(
        make_transient_reservation_payload(
            park["id"], "2026-08-14", "2026-08-16", guest_name="Priya Raman"
        ),
        GUEST,
    )
    reservation = validate_success(response, 201)

    assert_reservation_state(
        reservation, "CONFIRMED", pool_charged="TRANSIENT_POOL", entitlement_nights_charged=0
    )
    assert reservation["affiliate_nights_charged"] == 0, (
        "a club-owned park consumes no partner quota"
    )
    assert reservation["booker_type"] == "TRANSIENT", "no membership_id was named"
    assert reservation["membership_id"] is None, "a public booking names no membership"


def test_loyalty_band_reads_the_subtotal_that_carries_the_capital_assessment(api):
    """A base below the band whose subtotal is above it still earns the credit.

    PRD §3.1: "Reading the band off the base dues instead of the subtotal is the
    classic error — a base of 58,000 cents sits below the band while its subtotal
    of 62,640 cents sits above it."

    Design: Difficulty/combinatorial_formula/dues_invoice_loyalty_band_keyed_on_subtotal_not_base_dues
    """
    reset_clock(api)
    tier = create_president_tier(api)
    member = create_member(api, full_name="Omar Vance", home_region="Gulf")

    response = api.create_membership(
        make_membership_payload(member["id"], tier["id"], upfront_paid_cents=1850000), ADMIN
    )
    membership = validate_success(response, 201)

    invoice = list_invoices(api, membership["id"])[0]
    # 58000 base; 8% capital assessment 4640; subtotal 62640 clears the 60000
    # band at tenure 0, so 5% of the subtotal is 3132; 62640 - 3132 = 59508.
    assert_invoice_components(
        invoice,
        base_dues_cents=58000,
        capital_assessment_cents=4640,
        loyalty_credit_cents=3132,
        amount_cents=59508,
    )
    assert invoice["amount_cents"] != 62640, (
        "a base_dues-keyed band would grant no credit at all"
    )
    assert invoice["status"] == "OPEN", "the first invoice is issued OPEN"
    assert invoice["due_date"] == "2026-08-31", "the dues net term is 30 days"

    assert read_membership(api, membership["id"])["dues_balance_cents"] == 59508, (
        "the balance is the sum over OPEN and PAST_DUE invoices"
    )


def test_subtotal_below_the_band_earns_no_loyalty_credit_at_zero_tenure(api):
    """A cheaper tier's subtotal stays under the band, so the credit is zero.

    PRD §3.1: "it is 10 percent when the subtotal is at least 60,000 cents (six
    hundred dollars) *and* the membership's `tenure_years` is at least 5; 5
    percent when the subtotal is at least 60,000 cents but tenure is below 5
    years; 3 percent when tenure is at least 5 years but the subtotal is below
    60,000 cents; and 0 percent otherwise."

    Design: Difficulty/combinatorial_formula/dues_invoice_loyalty_band_keyed_on_subtotal_not_base_dues
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    member = create_member(api, full_name="Lena Fox", home_region="Plains")

    response = api.create_membership(
        make_membership_payload(member["id"], tier["id"], upfront_paid_cents=795000), ADMIN
    )
    membership = validate_success(response, 201)

    invoice = list_invoices(api, membership["id"])[0]
    # 42000 base; 8% capital assessment 3360; subtotal 45360 is below 60000 and
    # tenure is 0, so the loyalty percentage is 0.
    assert_invoice_components(
        invoice,
        base_dues_cents=42000,
        capital_assessment_cents=3360,
        loyalty_credit_cents=0,
        amount_cents=45360,
    )
