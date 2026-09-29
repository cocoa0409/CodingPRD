"""
Minimum stock verification, the redemption average, the compliance-buy
overcharge, the LOWEST_HALF_AVG ceiling derivation, and redemption claim intake.

Every test builds its own world from scratch through the documented endpoints,
because the server is relaunched against an empty database before each one.
"""

from test_helpers import (
    ANALYST_HEADERS,
    INVESTIGATOR_HEADERS,
    SUPERVISOR_HEADERS,
    assert_ceiling_derivation,
    assert_field_values,
    assert_sanction_schedule,
    assert_stock_finding,
    factories,
    fixtures,
    make_vendor_operator_headers,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    CeilingBasis,
    ClaimStatus,
    EditResult,
    MarMethod,
    PriceCycleStatus,
    RiskFlag,
    StockVerdict,
    StoreType,
    ViolationCode,
    VisitOutcome,
    VisitStatus,
    VisitType,
)

# The UPC of a container that was never mapped into the authorized food list, so
# neither an AuthorizedFoodItem nor a PriceCeiling can be resolved from it.
_UNMAPPED_UPC = "00099988877"


def test_minimum_stock_verification_ceils_required_units_and_computes_pct(api):
    """
    Each participating category's required units are the category minimum times the
    peer group multiplier rounded up, and the pass count drives the compliance percentage.

    "**Minimum stock verification** works over the categories that participate: every FoodCategory whose `stock_required` is true, considered globally and processed in ascending `code` order."
    "The multiplier comes from the peer group of the visited vendor: its `min_stock_multiplier`."
    "For each participating category, the requirement is the category's `min_stock_units` multiplied by that multiplier and rounded **up** to a whole number, and that figure is stamped onto the finding as `required_units`."
    "The category's verdict is then decided by the first of these tests that applies: if no observation was recorded for the category at all, the verdict is `MISSING` and the server creates the finding entry itself with `observed_units` 0 and `observed_variety_count` 0; otherwise, if `observed_units` is strictly less than `required_units`, the verdict is `BELOW_UNITS`; otherwise, if `observed_variety_count` is strictly less than the category's `min_variety_count`, the verdict is `BELOW_VARIETY`; otherwise the verdict is `PASS` and the category counts as passing."
    "The `stock_compliance_pct` is then 100 multiplied by the number of passing categories divided by the number of participating categories, rounded half up to one decimal place; when no category participates at all, the figure is exactly 100.0."
    "If any participating category came out `MISSING`, the outcome is `FAIL_MISSING_CATEGORY`. Otherwise, if fewer categories passed than participated — meaning at least one `BELOW_UNITS` or `BELOW_VARIETY` verdict — the outcome is `FAIL_BELOW_MINIMUM`."
    "**Hop 1** always runs: `conducted_at`, the `outcome`, the `stock_findings` verdicts, `stock_compliance_pct`, and `overcharge_cents` are stamped; the vendor's `open_finding_count` rises by one; and the vendor's `cure_deadline_at` is set to thirty days after the logical clock, opening the cure window."
    "**Hop 2** fires only when `open_finding_count` has thereby reached two uncured findings: the vendor's `compliance_buy_required` flips to true and its `risk_flag` becomes `HIGH_FINDING_COUNT`."

    Design: Corner/calculations/minimum_stock_verification_ceils_required_units_and_computes_pct
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    # Peer group PG-SUPER-A carries min_stock_multiplier 1.5; MILK requires 4 units
    # and 2 varieties.
    bundle = fixtures.published_ceiling_setup(api)
    milk_category_id = bundle["milk_category"]["id"]
    vendor_id = bundle["vendor"]["id"]
    # A second stock-required category, so verification spans two categories.
    bread = fixtures.add_bread_category(api)  # min_stock_units 3, min_variety_count 1

    visit = fixtures.schedule_visit(api, vendor_id, "2026-08-05T00:00:00Z")
    fixtures.record_observation(api, visit["id"], milk_category_id, 6, 2)
    fixtures.record_observation(api, visit["id"], bread["id"], 4, 3)

    conducted = validate_success(
        api.conduct_visit(visit["id"], factories.conduct_payload(), ANALYST_HEADERS)
    )

    assert_field_values(
        conducted,
        status=VisitStatus.FAILED.value,
        outcome=VisitOutcome.FAIL_BELOW_MINIMUM.value,
        conducted_at="2026-08-01T00:00:00.000Z",
        overcharge_cents=0,  # the basket was omitted, so nothing was priced
        stock_compliance_pct=50.0,  # round_half_up(100 * 1 passing / 2 participating, 1)
    )
    # ceil(4 units x 1.5) = 6 required units; 6 observed is not strictly less than 6.
    assert_stock_finding(
        conducted,
        milk_category_id,
        required_units=6,
        observed_units=6,
        observed_variety_count=2,
        verdict=StockVerdict.PASS.value,
    )
    # ceil(3 units x 1.5) = ceil(4.5) = 5 required units; 4 observed is below it, and
    # the variety count of 3 is never reached because the unit test fails first.
    assert_stock_finding(
        conducted,
        bread["id"],
        required_units=5,
        observed_units=4,
        observed_variety_count=3,
        verdict=StockVerdict.BELOW_UNITS.value,
    )

    vendor = fixtures.get_vendor(api, vendor_id)
    assert_field_values(
        vendor,
        open_finding_count=1,
        cure_deadline_at="2026-08-31T00:00:00.000Z",  # 30 days after 2026-08-01
        compliance_buy_required=False,  # only the second uncured finding flips this
        risk_flag=RiskFlag.NONE.value,
    )


def test_vendor_avg_monthly_redemption_divides_by_distinct_months(api):
    """
    The redemption average sums adjudicated claim totals and divides by the number of
    distinct claim months kept, ignoring claims that are still submitted.

    "Take the vendor's RedemptionClaims whose `status` is `ADJUDICATED`, `ADJUSTED`, or `PAID`; claims still in `SUBMITTED` are excluded and never influence the average."
    "Compare their `claim_month` values as strings in descending order and keep the six greatest distinct months."
    "If no such claim exists, `avg_monthly_redemption_cents` falls back to the vendor's self-reported `reported_monthly_redemption_cents`."
    "Otherwise it is the sum of `adjudicated_total_cents` over those claims divided by the **number of distinct months** kept — not the number of claims, so two claims in the same month raise the numerator without raising the divisor — rounded half up to a whole cent."
    "Adjudication also refreshes the vendor's `avg_monthly_redemption_cents` per §3.5, since a newly adjudicated month may enter the six-month window."
    "The `base_tier` comes from the violation class: `CLASS_A` is tier 4, `CLASS_B` is tier 3, `CLASS_C` is tier 2, and `CLASS_D` is tier 1."
    "The `case_points` come from the **base** tier and never from the effective one: tier 1 carries 1 point, tier 2 carries 2, tier 3 carries 4, and tier 4 carries 8."
    "The `cmp_amount_cents` is the vendor's `avg_monthly_redemption_cents` multiplied by the tier's monthly multiplier — 0.05 at tier 1, 0.10 at tier 2, 0.25 at tier 3, and 0.50 at tier 4 — multiplied again by the tier's month count — 1 month at tier 1, 3 at tier 2, 6 at tier 3, and 12 at tier 4 — then rounded half up to a whole cent, and finally capped: the penalty is the lesser of that rounded figure and 5,625,000 cents, which is the statutory ceiling of fifty-six thousand two hundred fifty dollars."

    Design: Corner/calculations/vendor_avg_monthly_redemption_divides_by_distinct_months
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.published_ceiling_setup(api)
    vendor_id = bundle["vendor"]["id"]
    vendor_headers = make_vendor_operator_headers(vendor_id)
    # 320 cents accepted, statewide fallback basis, x1.05 = 336 with the 400 cap idle.
    assert bundle["milk_ceiling"]["mar_cents"] == 336

    # No qualifying claim exists yet, so the average is the self-reported figure.
    assert_field_values(
        fixtures.get_vendor(api, vendor_id),
        avg_monthly_redemption_cents=6_000_000,
    )

    july = validate_success(
        api.create_redemption_claim(
            factories.redemption_claim_payload(
                vendor_id,
                claim_month="2026-07",
                lines=[factories.claim_line_payload(1, fixtures.MILK_UPC, 1, 336)],
            ),
            vendor_headers,
        ),
        201,
    )
    july = validate_success(api.adjudicate_claim(july["id"], None, ANALYST_HEADERS))
    assert_field_values(july, adjudicated_total_cents=336)  # 1 x 336 allowed at the ceiling
    assert_field_values(
        fixtures.get_vendor(api, vendor_id),
        avg_monthly_redemption_cents=336,  # 336 over 1 distinct month
    )

    june = validate_success(
        api.create_redemption_claim(
            factories.redemption_claim_payload(
                vendor_id,
                claim_month="2026-06",
                lines=[
                    factories.claim_line_payload(1, fixtures.MILK_UPC, 1, 336),
                    factories.claim_line_payload(2, fixtures.MILK_UPC, 1, 336),
                ],
            ),
            vendor_headers,
        ),
        201,
    )
    june = validate_success(api.adjudicate_claim(june["id"], None, ANALYST_HEADERS))
    assert_field_values(june, adjudicated_total_cents=672)  # 336 + 336
    assert_field_values(
        fixtures.get_vendor(api, vendor_id),
        # round_half_up((336 + 672) / 2 distinct months) = 504
        avg_monthly_redemption_cents=504,
    )

    # A third month is filed but never adjudicated, so it must not enter the average.
    may = validate_success(
        api.create_redemption_claim(
            factories.redemption_claim_payload(
                vendor_id,
                claim_month="2026-05",
                lines=[factories.claim_line_payload(1, fixtures.MILK_UPC, 3, 300)],
            ),
            vendor_headers,
        ),
        201,
    )
    assert_field_values(
        may,
        status=ClaimStatus.SUBMITTED.value,
        submitted_total_cents=900,  # 3 x 300, quantity-weighted at creation
    )
    vendor = fixtures.get_vendor(api, vendor_id)
    # 1908 / 3 claims = 636 is explicitly not the rule, and the SUBMITTED month is out.
    assert_field_values(vendor, avg_monthly_redemption_cents=504)

    case = validate_success(
        api.create_sanction_case(
            factories.sanction_case_payload(
                vendor_id,
                vendor["version"],
                violation_code=ViolationCode.CLASS_D.value,
            ),
            INVESTIGATOR_HEADERS,
        ),
        201,
    )
    assert_sanction_schedule(
        case,
        base_tier=1,  # CLASS_D
        case_points=1,  # tier 1 carries 1 point
        cumulative_points_at_open=0,  # no other resolved case
        effective_tier=1,  # 0 + 1 clears neither the 4-point nor the 8-point threshold
        disqualification_months=0,  # tier 1 carries no disqualification
        cmp_permitted=True,  # every class except CLASS_A
        # min(5625000, round_half_up(504 x 0.05 x 1 month)) = round_half_up(25.2) = 25
        cmp_amount_cents=25,
    )
    assert_field_values(
        fixtures.get_vendor(api, vendor_id), avg_monthly_redemption_cents=504
    )


def test_compliance_buy_overcharge_ignores_unpriced_items(api):
    """
    A compliance-buy basket row that resolves to no authorized item contributes nothing
    to the overcharge, while a priced row contributes its excess over the ceiling times quantity.

    "**The compliance-buy overcharge** is computed from `buy_items` whenever the basket is non-empty."
    "First the governing cycle is chosen: among price cycles whose `status` is `PUBLISHED` and whose `published_at` is at or before the logical clock, the one with the greatest `published_at`, ties broken by the earlier `created_at`; if no such cycle exists, `overcharge_cents` is 0 and the basket is not priced."
    "For each entry the item is resolved from its `upc`, and the ceiling is the PriceCeiling for that item, the visited vendor's peer group, and the governing cycle whose `status` is `ACTIVE`."
    "If either the item or the ceiling cannot be found, the entry contributes nothing and the walk continues — unpriced items are not treated as overcharges."
    "Otherwise the entry contributes the excess of `charged_unit_price_cents` over the ceiling's `mar_cents`, floored at zero so a bargain never offsets an overcharge, multiplied by the entry's `quantity`."
    "Otherwise, if the visit's `overcharge_cents` is greater than 0, the outcome is `FAIL_PRICE_OVERCHARGE`."
    "**Hop 2** fires only when `open_finding_count` has thereby reached two uncured findings: the vendor's `compliance_buy_required` flips to true and its `risk_flag` becomes `HIGH_FINDING_COUNT`."
    "**Hop 3** fires only because hop 2 flipped `compliance_buy_required` to true: the system creates a MonitoringVisit of its own for the same vendor with `visit_type` `COMPLIANCE_BUY`, `status` `SCHEDULED`, `auto_generated` true, and `scheduled_for` set to fourteen days after the logical clock."
    "Client-created visits begin `SCHEDULED` with `auto_generated` false, an `outcome` of `PENDING`, an `overcharge_cents` of 0, a `stock_compliance_pct` of 0.0, and `conducted_at` and `cancelled_reason` null."

    Design: Corner/calculations/compliance_buy_overcharge_ignores_unpriced_items
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    # Two routine visits conducted with no observations, so the single stock-required
    # MILK category comes out MISSING both times.
    bundle = fixtures.compliance_buy_required_setup(api)
    vendor_id = bundle["vendor"]["id"]
    milk_category_id = bundle["milk_category"]["id"]
    assert bundle["milk_ceiling"]["mar_cents"] == 336

    assert_field_values(
        bundle["visit_one"],
        status=VisitStatus.FAILED.value,
        outcome=VisitOutcome.FAIL_MISSING_CATEGORY.value,
    )
    assert_field_values(
        bundle["visit_two"],
        status=VisitStatus.FAILED.value,
        outcome=VisitOutcome.FAIL_MISSING_CATEGORY.value,
    )
    assert_field_values(
        bundle["vendor"],
        open_finding_count=2,
        compliance_buy_required=True,
        risk_flag=RiskFlag.HIGH_FINDING_COUNT.value,
    )
    # The second failure manufactured the compliance buy itself, fourteen days out.
    assert_field_values(
        bundle["auto_visit"],
        visit_type=VisitType.COMPLIANCE_BUY.value,
        auto_generated=True,
        status=VisitStatus.SCHEDULED.value,
        scheduled_for="2026-08-15T00:00:00.000Z",  # 2026-08-01 plus 14 days
    )

    # The investigator books its own buy 26 days from the auto-created one, clear of
    # the seven-day blackout buffer.
    buy_visit = fixtures.schedule_visit(
        api,
        vendor_id,
        "2026-09-10T00:00:00Z",
        visit_type=VisitType.COMPLIANCE_BUY.value,
    )
    fixtures.record_observation(
        api, buy_visit["id"], milk_category_id, 6, 2, headers=INVESTIGATOR_HEADERS
    )

    conducted = validate_success(
        api.conduct_visit(
            buy_visit["id"],
            factories.conduct_payload(
                [
                    factories.buy_item(fixtures.MILK_UPC, 2, 400),
                    factories.buy_item(_UNMAPPED_UPC, 3, 999),
                ]
            ),
            INVESTIGATOR_HEADERS,
        )
    )

    assert_field_values(
        conducted,
        # max(0, 400 - 336) x 2 = 128; the unmapped row adds 0, not (999 - 0) x 3
        overcharge_cents=128,
        stock_compliance_pct=100.0,  # the one participating category passed
        outcome=VisitOutcome.FAIL_PRICE_OVERCHARGE.value,
        status=VisitStatus.FAILED.value,
        auto_generated=False,  # this visit was client-created
    )
    assert_stock_finding(
        conducted,
        milk_category_id,
        required_units=6,  # ceil(4 x 1.5)
        observed_units=6,
        verdict=StockVerdict.PASS.value,
    )
    assert_field_values(
        fixtures.get_visit(api, buy_visit["id"]),
        overcharge_cents=128,
        outcome=VisitOutcome.FAIL_PRICE_OVERCHARGE.value,
        auto_generated=False,
    )


def test_mar_uses_lowest_half_avg_over_three_submissions(api):
    """
    Under LOWEST_HALF_AVG the base averages the ceil(n/2) lowest prices, and the single
    rounding half up at the very end turns 220.5 into 221.

    "Under `LOWEST_HALF_AVG`, take the number of candidates, divide by two, round **up** to a whole number to get how many of the lowest prices participate, and average exactly those lowest prices — so with five candidates the three lowest are averaged."
    "When the peer count is greater than or equal to that threshold, `basis` is `PEER_GROUP` and the candidate set is the peer list itself."
    "Either way, the size of the candidate set actually used is recorded as `contributing_submission_count`, while `peer_submission_count` continues to report the peer count even when the fallback was used."
    "The allowance is applied first: the base is multiplied by one plus the peer group's `competitive_allowance_pct`, giving an allowance-adjusted figure."
    "The statewide cap is computed second, as 1.25 times the smallest price in the **same** candidate set that produced the base — not the smallest peer price when the fallback was used, and not a statewide minimum computed separately."
    "That unrounded cap is stored as `cap_cents`, and `cap_binding` is recorded as true exactly when the cap is strictly less than the allowance-adjusted figure."
    "Rounding happens once, at the very end: `mar_cents` is the lesser of the allowance-adjusted figure and the cap, rounded half up to a whole cent."
    "Second, the same pair sweep runs again and writes a fresh PriceCeiling row with `status` `ACTIVE` for every pair with a non-empty candidate set, setting `published_ceiling_count` and `skipped_pair_count` from that sweep."

    Design: Corner/calculations/mar_uses_lowest_half_avg_over_three_submissions
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.peer_group_with_three_accepted_prices(
        api,
        {
            "code": "PG-MED-A",
            "store_type": StoreType.MEDIUM_GROCERY.value,
            "min_monthly_redemption_cents": 0,
            "max_monthly_redemption_cents": 20_000_000,
            "mar_method": MarMethod.LOWEST_HALF_AVG.value,
            "competitive_allowance_pct": 0.05,
            "min_submissions_for_ceiling": 3,
            "min_stock_multiplier": 1.0,
        },
        prices=(200, 220, 300),
        reported_volumes=(1_000_000, 2_000_000, 3_000_000),
        store_type=StoreType.MEDIUM_GROCERY.value,
    )
    peer_group_id = bundle["peer_group"]["id"]
    item_id = bundle["milk_item"]["id"]
    cycle_id = bundle["cycle"]["id"]
    fixtures.close_cycle(api, cycle_id)

    summary = validate_success(
        api.publish_ceilings(cycle_id, None, SUPERVISOR_HEADERS)
    )
    assert_field_values(summary, published_ceiling_count=1)

    rows, meta = validate_paginated(
        api.list_price_ceilings(
            SUPERVISOR_HEADERS,
            {
                "peer_group_id": peer_group_id,
                "food_item_id": item_id,
                "price_cycle_id": cycle_id,
                "status": "ACTIVE",
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 1, f"expected one ACTIVE ceiling, got {meta}"
    assert_ceiling_derivation(
        rows[0],
        basis=CeilingBasis.PEER_GROUP.value,  # 3 peers >= min_submissions_for_ceiling 3
        peer_submission_count=3,
        contributing_submission_count=3,
        base_cents=210,  # k = ceil(3 / 2) = 2, so (200 + 220) / 2 = 210
        cap_cents=250.0,  # 1.25 x 200, the smallest price of the same candidate set
        cap_binding=False,  # 250 is not strictly below the allowance-adjusted 220.5
        mar_cents=221,  # one rounding at the end: round_half_up(210 x 1.05) = 221
    )

    cycle = fixtures.get_price_cycle(api, cycle_id)
    assert_field_values(
        cycle,
        status=PriceCycleStatus.PUBLISHED.value,
        published_ceiling_count=1,
        skipped_pair_count=0,  # the single pair had a non-empty candidate set
    )


def test_create_redemption_claim_creates_one_claim_line_per_payload_entry(api):
    """
    Filing a claim mints exactly one pending claim line per payload entry and totals the
    quantity-weighted charges, leaving every adjudication field null.

    "A `VendorOperator` files a month of redemptions by supplying its `vendor_id`, the benefit month as `claim_month` in four-digit-year-hyphen-two-digit-month form, and a non-empty list of `lines`."
    "Each entry becomes a ClaimLine carrying its `line_number` — a one-based position that must be at least 1 and must not repeat within the claim — the `upc` as scanned at the register, the `quantity` of containers redeemed, the `charged_unit_price_cents` per container which must be at least 0, and an optional `medical_doc_on_file` flag defaulting to false that records whether medical documentation backs an exempt-formula line."
    "At creation the claim's `status` is `SUBMITTED`, its `line_count` is the number of lines created, and its `submitted_total_cents` is the sum over lines of `quantity` multiplied by `charged_unit_price_cents`."
    "Every line starts with `edit_result` `PENDING` and with `edit_code`, `food_item_id`, and `applied_mar_cents` null, `allowed_cents` 0, and `recouped_cents` 0."
    "The claim's `governing_price_cycle_id`, `adjudicated_total_cents`, `net_payable_cents`, `adjudicated_at`, and `paid_at` are all null until adjudication, and `accepted_line_count`, `reduced_line_count`, and `rejected_line_count` all start at 0."
    "**`E03`** — the quantity is out of range: `quantity` is zero or negative, or it exceeds the category's `max_units_per_transaction`."

    Design: Corner/endpoints/create_redemption_claim_creates_one_claim_line_per_payload_entry
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.published_ceiling_setup(api)
    vendor_id = bundle["vendor"]["id"]

    claim = validate_success(
        api.create_redemption_claim(
            factories.redemption_claim_payload(
                vendor_id,
                claim_month="2026-07",
                lines=[
                    factories.claim_line_payload(1, fixtures.MILK_UPC, 2, 336),
                    factories.claim_line_payload(2, fixtures.MILK_UPC, 1, 337),
                    factories.claim_line_payload(3, _UNMAPPED_UPC, 1, 500),
                    # MILK caps a transaction at 6 units, but the quantity ceiling is a
                    # transaction edit run at adjudication, not a creation-time check.
                    factories.claim_line_payload(4, fixtures.MILK_UPC, 7, 200),
                    factories.claim_line_payload(5, fixtures.MILK_UPC, 1, 179),
                ],
            ),
            make_vendor_operator_headers(vendor_id),
        ),
        201,
    )

    assert_field_values(
        claim,
        vendor_id=vendor_id,
        claim_month="2026-07",
        status=ClaimStatus.SUBMITTED.value,
        line_count=5,
        # 2*336 + 1*337 + 1*500 + 7*200 + 1*179 = 3088, not the 1552 unit-price sum
        submitted_total_cents=3088,
        governing_price_cycle_id=None,
        adjudicated_total_cents=None,
        net_payable_cents=None,
        adjudicated_at=None,
        paid_at=None,
        accepted_line_count=0,
        reduced_line_count=0,
        rejected_line_count=0,
    )

    lines, meta = validate_paginated(
        api.list_claim_lines(
            SUPERVISOR_HEADERS, {"redemption_claim_id": claim["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 5, f"expected five claim lines, got {meta}"
    for line in lines:
        assert_field_values(
            line,
            redemption_claim_id=claim["id"],
            edit_result=EditResult.PENDING.value,
            edit_code=None,
            food_item_id=None,
            applied_mar_cents=None,
            allowed_cents=0,
            recouped_cents=0,
        )

    by_number = {line["line_number"]: line for line in lines}
    assert sorted(by_number) == [1, 2, 3, 4, 5]
    assert_field_values(by_number[1], upc=fixtures.MILK_UPC, quantity=2, charged_unit_price_cents=336)
    assert_field_values(by_number[3], upc=_UNMAPPED_UPC, quantity=1, charged_unit_price_cents=500)
    assert_field_values(by_number[4], upc=fixtures.MILK_UPC, quantity=7, charged_unit_price_cents=200)
