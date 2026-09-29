"""Warranty pricing: six ordered steps, two coverage variants, one fee ladder.

PRD.md section 3.9 prices an approved claim in a fixed order and rounds every
intermediate before the next step reads it. Two facts carry the whole partition:
the coverage percentage is rounded to two decimals *before* it multiplies the
MSRP, and the administrative-fee tier is chosen once from the gross, before any
deduction, using an at-or-above comparison against each tier's maximum. The age
those steps read is frozen once, by start-review, as floored complete calendar
months.
"""

from test_helpers import (
    AGENT_HEADERS,
    approve_claim_payload,
    assert_claim_payout_arithmetic,
    assert_instant_equals,
    assert_money_equals,
    assert_warranty_reserve_conserved,
    get_success_data,
    set_clock,
    setup_delivered_unit_with_customer,
    storage_review_payload,
    warranty_claim_payload,
)


def _p5_price_claim(api, ctx, unit_id, *, clock, claim_type, deformation_mm, note):
    """Open, review, storage-verify and approve one claim at ``clock``.

    Each approval re-reads the model's ``version`` immediately before the call,
    because PRD.md section 3.9 guards approval with optimistic concurrency on the
    hull model: "The body carries `expected_product_model_version`; a mismatch is
    `ERR_STALE_PRODUCT_MODEL_VERSION` (HTTP 412) and nothing is written, because
    the reserve balance the agent priced against has already moved."

    Returns ``(claim_after_review, approved_claim, model_version_consumed)`` so a
    test can read the frozen ``months_in_service`` before pricing, the priced
    result, and the model version each approval spent.
    """
    set_clock(clock)
    claim = get_success_data(
        api.create_warranty_claim(
            warranty_claim_payload(
                unit_id,
                ctx["customer_id"],
                claim_type=claim_type,
                reported_deformation_mm=deformation_mm,
                storage_description=note,
            ),
            AGENT_HEADERS,
        )
    )
    reviewed = get_success_data(api.start_claim_review(claim["id"], AGENT_HEADERS))
    get_success_data(
        api.submit_storage_review(
            claim["id"], storage_review_payload("VERIFIED", note), AGENT_HEADERS
        )
    )
    model_version = api.read_version("get_product_model", ctx["product_model_id"], AGENT_HEADERS)
    approved = get_success_data(
        api.approve_warranty_claim(
            claim["id"], approve_claim_payload(model_version), AGENT_HEADERS
        )
    )
    return reviewed, approved, model_version


def _p5_assert_priced(claim, *, basis, months, gross, fee, deduction, net, label):
    """Assert one claim's five recorded pricing fields plus their arithmetic."""
    assert claim["claim_status"] == "APPROVED", f"{label}: claim_status"
    assert claim["payout_basis"] == basis, (
        f"{label}: payout_basis is copied from the model, got {claim['payout_basis']!r}"
    )
    assert claim["months_in_service"] == months, (
        f"{label}: months_in_service expected {months}, got {claim['months_in_service']}"
    )
    assert_money_equals(claim["pre_fee_gross_cents"], gross, f"{label}: pre_fee_gross_cents")
    assert_money_equals(claim["admin_fee_cents"], fee, f"{label}: admin_fee_cents")
    assert_money_equals(
        claim["storage_deduction_cents"], deduction, f"{label}: storage_deduction_cents"
    )
    assert_money_equals(claim["net_payout_cents"], net, f"{label}: net_payout_cents")
    assert_claim_payout_arithmetic(claim)


def test_pro_rata_coverage_rounds_to_two_decimals_before_the_fee_tier_reads_the_gross(
    api, admin_headers
):
    """Three approvals on one 400020-cent model pay net 335671, 190009 and 55203.

    PRD.md section 3.9 pins the age: start-review "computes and freezes
    `months_in_service` as the number of **complete calendar months** from the
    hull's `delivered_at` to the logical clock, floored".  It then pins the order
    and the rounding: "**Pricing** proceeds in a fixed order and every intermediate
    is rounded before it is used again... Under the `PRO_RATA_AGE` variant the
    coverage percentage is 60 minus `months_in_service`, divided by 60, times 100,
    rounded to two decimals"; "`pre_fee_gross_cents` is the model's `msrp_cents`
    multiplied by the coverage percentage divided by 100, multiplied by the
    claim-type factor — 1.00 for `HULL_DEFORMATION`, 0.60 for `HARDWARE`, 0.30 for
    `COSMETIC` — and rounded half-up to whole cents"; "`admin_fee_cents` is the
    gross multiplied by the rate of the **first** tier whose maximum gross is at or
    above `pre_fee_gross_cents`, from an ordered ladder of 50000 cents at 12.00
    percent and 200000 cents at 8.00 percent, falling through to a top rate of 5.00
    percent, rounded half-up. That tier is chosen **once, from the gross, before any
    deduction**"; "`storage_deduction_cents` is the gross multiplied by 35.00
    percent, rounded half-up, when `storage_review_status` is `WAIVED`, and exactly
    0 when it is `GUIDANCE_VERIFIED`"; "`net_payout_cents` is the gross minus the
    deduction minus the fee, floored at 0".  The ledger then follows: "the model's
    `warranty_reserve_cents` decreases by `net_payout_cents` and its
    `warranty_paid_cents` increases by the identical integer... The invariant
    `warranty_reserve_cents` plus `warranty_paid_cents` equals
    `initial_warranty_reserve_cents` holds after every ledger move, without
    exception. Both the model's and the claim's `version` advance by 1."

    Design: Corner/calculations/calc_precision_warranty_pro_rata_coverage_and_top_fee_rate
    """
    ctx = setup_delivered_unit_with_customer(
        model_overrides={
            "warranty_basis": "PRO_RATA_AGE",
            "msrp_cents": 400020,
            "initial_warranty_reserve_cents": 1000000,
        }
    )
    first_hull, second_hull = ctx["delivered_units"][0], ctx["delivered_units"][1]
    assert_instant_equals(
        first_hull["delivered_at"], ctx["delivered_at"], "the hull's delivered_at"
    )
    assert first_hull["logistics_status"] == "DELIVERED", "the warranty clock has started"

    opening = api.read_entity("get_product_model", ctx["product_model_id"], admin_headers)
    assert_money_equals(opening["warranty_reserve_cents"], 1000000, "opening reserve")
    assert_money_equals(opening["warranty_paid_cents"], 0, "opening paid")
    assert_warranty_reserve_conserved(opening)
    opening_version = opening["version"]

    # Delivered 2026-08-02T00:00:00Z; the clock at 2027-03-02T12:00:00Z is exactly
    # seven complete calendar months later.
    reviewed_one, claim_one, version_one = _p5_price_claim(
        api,
        ctx,
        first_hull["id"],
        clock="2027-03-02T12:00:00Z",
        claim_type="HULL_DEFORMATION",
        deformation_mm=3.5,
        note="trailered on a bunk under cover",
    )
    assert reviewed_one["months_in_service"] == 7, (
        "start-review freezes the age, and the approve one call later reads the same "
        f"figure, got {reviewed_one['months_in_service']}"
    )
    # coverage = round_half_up((60 - 7) / 60 * 100, 2) = round_half_up(88.333333) = 88.33,
    # then round_half_up(400020 * 88.33 / 100 * 1.00) = round_half_up(353337.666) = 353338.
    # Carrying an unrounded 88.3333... into the multiplication would give 353351.
    # 353338 is above every tier maximum, so the 5.00 percent top rate applies:
    # round_half_up(353338 * 5.00 / 100) = round_half_up(17666.90) = 17667.
    _p5_assert_priced(
        claim_one,
        basis="PRO_RATA_AGE",
        months=7,
        gross=353338,
        fee=17667,
        deduction=0,
        net=335671,
        label="the seven-month claim",
    )

    after_one = api.read_entity("get_product_model", ctx["product_model_id"], admin_headers)
    assert_money_equals(after_one["warranty_reserve_cents"], 664329, "reserve after one payout")
    assert_money_equals(after_one["warranty_paid_cents"], 335671, "paid after one payout")
    assert_warranty_reserve_conserved(after_one)

    # Delivered 2026-08-02T00:00:00Z; 2029-02-02T12:00:00Z is thirty complete months.
    reviewed_two, claim_two, version_two = _p5_price_claim(
        api,
        ctx,
        second_hull["id"],
        clock="2029-02-02T12:00:00Z",
        claim_type="HULL_DEFORMATION",
        deformation_mm=4.0,
        note="stored on a cradle in a dry stack",
    )
    assert reviewed_two["months_in_service"] == 30, (
        f"expected thirty complete months, got {reviewed_two['months_in_service']}"
    )
    # coverage = round_half_up((60 - 30) / 60 * 100, 2) = 50.00, so the gross is
    # round_half_up(400020 * 50.00 / 100 * 1.00) = 200010 — ten cents above the
    # 200000-cent tier maximum, so the 8.00 percent band does not match and the
    # 5.00 percent top rate applies: round_half_up(10000.50) = 10001, where a
    # round-half-even implementation would pay 10000 and an 8.00 percent band
    # would pay 16001.
    _p5_assert_priced(
        claim_two,
        basis="PRO_RATA_AGE",
        months=30,
        gross=200010,
        fee=10001,
        deduction=0,
        net=190009,
        label="the thirty-month claim",
    )

    # A COSMETIC claim on the first hull at the same clock: the same 50.00 percent
    # coverage scaled by the 0.30 claim-type factor gives
    # round_half_up(400020 * 50.00 / 100 * 0.30) = round_half_up(60003.00) = 60003.
    # The factor is applied to the gross BEFORE the tier is chosen, so this claim
    # falls inside the 200000-cent band at 8.00 percent while its HULL_DEFORMATION
    # sibling at the same age pays the 5.00 percent top rate; choosing the tier
    # after the factor would instead pay 3000 and net 57003.
    _reviewed_three, claim_three, version_three = _p5_price_claim(
        api,
        ctx,
        first_hull["id"],
        clock="2029-02-02T12:00:00Z",
        claim_type="COSMETIC",
        deformation_mm=0.0,
        note="gelcoat chalking on the same hull",
    )
    _p5_assert_priced(
        claim_three,
        basis="PRO_RATA_AGE",
        months=30,
        gross=60003,
        fee=4800,
        deduction=0,
        net=55203,
        label="the cosmetic claim",
    )
    assert claim_three["claim_type"] == "COSMETIC", "claim_type"
    assert claim_three["months_in_service"] == claim_two["months_in_service"], (
        "both claims read the same frozen age, so only the claim-type factor differs"
    )
    # Cross-multiplied so the band comparison stays in exact integer arithmetic.
    assert (
        claim_three["admin_fee_cents"] * claim_two["pre_fee_gross_cents"]
        > claim_two["admin_fee_cents"] * claim_three["pre_fee_gross_cents"]
    ), (
        "the smaller gross falls inside the 200000-cent band at 8.00 percent while its "
        "sibling at the same age fell through to the cheaper 5.00 percent top rate"
    )

    final = api.read_entity("get_product_model", ctx["product_model_id"], admin_headers)
    assert_money_equals(final["warranty_reserve_cents"], 419117, "reserve after three payouts")
    assert_money_equals(final["warranty_paid_cents"], 580883, "paid after three payouts")
    assert_warranty_reserve_conserved(final)
    assert final["version"] == opening_version + 3, (
        "each approval advances the model version by exactly 1, which is why every "
        f"approve had to re-read it, got {final['version']} from {opening_version}"
    )
    assert len({version_one, version_two, version_three}) == 3, (
        "the three approvals consumed three different model versions: replaying the "
        f"first would fail the OCC guard, got {(version_one, version_two, version_three)}"
    )


def test_flat_schedule_band_is_the_first_maximum_at_or_above_the_floored_age(api, admin_headers):
    """Twelve months and twelve months plus thirty days both pay 132480; thirteen pays 82800.

    PRD.md section 3.9 makes the age a floor, not a proportion: start-review
    "computes and freezes `months_in_service` as the number of **complete calendar
    months** from the hull's `delivered_at` to the logical clock, floored: a hull
    delivered twelve months and twenty-nine days ago reads 12, not 13."  The band is
    then a step function read from the top of the ladder: "Under the `FLAT_SCHEDULE`
    variant the coverage percentage is the value of the **first** band whose maximum
    months is at or above `months_in_service`, from an ordered ladder of 12 months at
    80.00 percent, 36 months at 50.00 percent and 60 months at 25.00 percent — a step
    function that is flat inside a band and drops at 13 and at 37 months."  The fee
    ladder is the same one the gross is measured against: "the rate of the **first**
    tier whose maximum gross is at or above `pre_fee_gross_cents`, from an ordered
    ladder of 50000 cents at 12.00 percent and 200000 cents at 8.00 percent".

    Design: Corner/calculations/calc_tiered_pricing_warranty_flat_schedule_band_boundary
    """
    ctx = setup_delivered_unit_with_customer(
        model_overrides={
            "warranty_basis": "FLAT_SCHEDULE",
            "msrp_cents": 180000,
            "initial_warranty_reserve_cents": 500000,
        }
    )
    first_hull, second_hull = ctx["delivered_units"][0], ctx["delivered_units"][1]
    assert_instant_equals(
        first_hull["delivered_at"], ctx["delivered_at"], "the hull's delivered_at"
    )

    opening = api.read_entity("get_product_model", ctx["product_model_id"], admin_headers)
    assert_money_equals(opening["warranty_reserve_cents"], 500000, "opening reserve")
    assert_money_equals(opening["warranty_paid_cents"], 0, "opening paid")
    assert_warranty_reserve_conserved(opening)
    opening_version = opening["version"]

    # Delivered 2026-08-02T00:00:00Z, reviewed at 2027-08-02T12:00:00Z: exactly
    # twelve complete months, and the 12-month row's maximum is at-or-above 12, so
    # coverage is 80.00 percent. round_half_up(180000 * 80.00 / 100 * 1.00) = 144000;
    # 144000 fails the 50000 row but satisfies 200000, so the fee is
    # round_half_up(144000 * 8.00 / 100) = 11520.
    _reviewed_one, claim_one, version_one = _p5_price_claim(
        api,
        ctx,
        first_hull["id"],
        clock="2027-08-02T12:00:00Z",
        claim_type="HULL_DEFORMATION",
        deformation_mm=3.0,
        note="on a cradle under cover for the first season",
    )
    _p5_assert_priced(
        claim_one,
        basis="FLAT_SCHEDULE",
        months=12,
        gross=144000,
        fee=11520,
        deduction=0,
        net=132480,
        label="the twelve-month claim",
    )

    after_one = api.read_entity("get_product_model", ctx["product_model_id"], admin_headers)
    assert_money_equals(after_one["warranty_reserve_cents"], 367520, "reserve after one payout")
    assert_money_equals(after_one["warranty_paid_cents"], 132480, "paid after one payout")
    assert_warranty_reserve_conserved(after_one)

    # 2027-09-01T23:59:59Z is twelve months and thirty days after delivery, one
    # second short of the thirteenth month, so the floored age is still 12 and the
    # same 80.00 percent band applies. An implementation that rounded the age up, or
    # that divided elapsed days by 30.4, would drop this claim into the 36-month
    # band and pay 82800.
    _reviewed_two, claim_two, version_two = _p5_price_claim(
        api,
        ctx,
        first_hull["id"],
        clock="2027-09-01T23:59:59Z",
        claim_type="HULL_DEFORMATION",
        deformation_mm=3.2,
        note="second deformation found on the same hull one month later",
    )
    _p5_assert_priced(
        claim_two,
        basis="FLAT_SCHEDULE",
        months=12,
        gross=144000,
        fee=11520,
        deduction=0,
        net=132480,
        label="the twelve-months-and-thirty-days claim",
    )
    assert_money_equals(
        claim_two["net_payout_cents"],
        claim_one["net_payout_cents"],
        "the band is flat inside its range, so thirty extra days cost nothing",
    )

    # One more day: 2027-09-02T12:00:00Z is thirteen complete months, the 12-month
    # row's maximum now fails the at-or-above test and the 36-month row is the first
    # match, so coverage drops to 50.00 percent. round_half_up(180000 * 50.00 / 100)
    # = 90000, still inside the 200000-cent band, so the fee is
    # round_half_up(90000 * 8.00 / 100) = 7200. One extra day of age costs 54000
    # cents of gross, because the band and not the age sets the coverage.
    _reviewed_three, claim_three, version_three = _p5_price_claim(
        api,
        ctx,
        second_hull["id"],
        clock="2027-09-02T12:00:00Z",
        claim_type="HULL_DEFORMATION",
        deformation_mm=3.0,
        note="sister hull, deformation reported the following day",
    )
    _p5_assert_priced(
        claim_three,
        basis="FLAT_SCHEDULE",
        months=13,
        gross=90000,
        fee=7200,
        deduction=0,
        net=82800,
        label="the thirteen-month claim",
    )
    assert (
        claim_two["pre_fee_gross_cents"] - claim_three["pre_fee_gross_cents"] == 54000
    ), (
        "the step is not proportional to the single day between the two reviews, got "
        f"{claim_two['pre_fee_gross_cents'] - claim_three['pre_fee_gross_cents']}"
    )

    final = api.read_entity("get_product_model", ctx["product_model_id"], admin_headers)
    assert_money_equals(final["warranty_reserve_cents"], 152240, "reserve after three payouts")
    assert_money_equals(final["warranty_paid_cents"], 347760, "paid after three payouts")
    assert_warranty_reserve_conserved(final)
    assert final["version"] == opening_version + 3, (
        "three approvals advance the model version by exactly 3, got "
        f"{final['version']} from {opening_version}"
    )
    assert len({version_one, version_two, version_three}) == 3, (
        "each approve consumed a fresh model version, got "
        f"{(version_one, version_two, version_three)}"
    )
