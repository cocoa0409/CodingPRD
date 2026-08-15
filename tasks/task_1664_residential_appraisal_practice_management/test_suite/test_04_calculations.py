"""Calculation claims: fee quote constants and variants, tier rules,
comparable adjustment/eligibility boundaries, value conclusion weighting,
turn-time boundaries, cancellation fees, retention precision (PRD 3.3-3.9)."""
from test_helpers import (
    ApiErrorId,
    add_locked_comp,
    create_client,
    create_comparable,
    create_fee_adjustment_payload,
    create_fee_schedule,
    create_order,
    first_workfile_of_type,
    get_order,
    get_scorecard,
    scope_order,
    accept_order,
    assign_order,
    set_clock,
    setup_accepted_order,
    setup_delivered_order,
    setup_order_in_analysis,
    setup_report_qc_passed,
    start_analysis,
    validate_error,
    validate_success,
    verify_comparable,
)
from test_helpers import ADMIN, COMPLIANCE


def test_fee_quote_floor_applied(api):
    """PRD 3.3: "The quote is finally bounded: raised to a floor of 35000
    cents when below it, and capped at 150000 cents when above."

    Design: Corner/calculations/fee_quote_floor_applied
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    create_fee_schedule(client["id"], base_fee_cents=30000, rush_multiplier_bps=1000)
    order = create_order(client["id"])

    scoped = validate_success(api.determine_scope(order["id"], {}, ADMIN), 200)
    # 30000 base, no rush (7 == 7), SFR/CONVENTIONAL -> below the 35000 floor
    assert scoped["fee_quoted_cents"] == 35000


def test_fee_quote_cap_applied(api):
    """PRD 3.3: "The quote is finally bounded: raised to a floor of 35000
    cents when below it, and capped at 150000 cents when above."

    Design: Corner/calculations/fee_quote_cap_applied
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    create_fee_schedule(
        client["id"],
        complexity_tier="HIGH_VALUE",
        base_fee_cents=200000,
        rush_multiplier_bps=1000,
        revision_fee_cents=20000,
    )
    order = create_order(
        client["id"],
        property_address="1 Mansion Row",
        estimated_value_cents=200000000,
    )

    scoped = validate_success(api.determine_scope(order["id"], {}, ADMIN), 200)
    assert scoped["complexity_tier"] == "HIGH_VALUE"
    assert scoped["fee_quoted_cents"] == 150000


def test_fee_rush_boundary_equal_turn_no_premium(api):
    """PRD 3.3: "If the order's `requested_turn_days` is fewer than the
    client's `default_turn_time_days`, a rush premium is added: the base
    multiplied by the rush basis points and divided by ten thousand, rounded
    half-up to whole cents."

    Design: Corner/calculations/fee_rush_boundary_equal_turn_no_premium
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    create_fee_schedule(client["id"], base_fee_cents=45000, rush_multiplier_bps=2000)
    order = create_order(client["id"], requested_turn_days=7)

    scoped = validate_success(api.determine_scope(order["id"], {}, ADMIN), 200)
    # requested 7 is not fewer than default 7 -> no rush premium
    assert scoped["fee_quoted_cents"] == 45000


def test_fee_retail_fallback_when_no_schedule(api):
    """PRD 3.3: "When no window matches, the retail rate card supplies a base
    of 45000 cents for `STANDARD`, 60000 cents for `COMPLEX`, and 85000 cents
    for `HIGH_VALUE`, with a retail rush rate of 1500 basis points."

    Design: Corner/calculations/fee_retail_fallback_when_no_schedule
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client(client_type="PRIVATE")
    order = create_order(client["id"], requested_turn_days=3)

    scoped = validate_success(api.determine_scope(order["id"], {}, ADMIN), 200)
    # retail 45000 + round_half_up(45000 * 1500 / 10000) = 45000 + 6750
    assert scoped["fee_quoted_cents"] == 51750


def test_tier_override_one_level_up_allowed(api):
    """PRD 3.3: "The administrator may supply `complexity_tier_override` to
    accept the computed tier or to raise it by exactly one level — `STANDARD`
    to `COMPLEX`, or `COMPLEX` to `HIGH_VALUE`."

    Design: Corner/calculations/tier_override_one_level_up_allowed
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    create_fee_schedule(client["id"], complexity_tier="STANDARD", base_fee_cents=45000)
    create_fee_schedule(client["id"], complexity_tier="COMPLEX", base_fee_cents=60000)
    order = create_order(client["id"])

    scoped = validate_success(
        api.determine_scope(order["id"], {"complexity_tier_override": "COMPLEX"}, ADMIN),
        200,
    )
    assert scoped["complexity_tier"] == "COMPLEX"
    assert scoped["fee_quoted_cents"] == 60000


def test_tier_override_downgrade_rejected(api):
    """PRD 3.3: "`HIGH_VALUE` admits no override, and any override that is
    neither the computed tier nor one level above it is rejected with
    `ERR_INVALID_TIER_OVERRIDE`."

    Design: Corner/calculations/tier_override_downgrade_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    order = create_order(
        client["id"],
        property_address="2 Duplex",
        property_type="MULTI_2_4",
        estimated_value_cents=50000000,
    )

    response = api.determine_scope(
        order["id"], {"complexity_tier_override": "STANDARD"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TIER_OVERRIDE, 422)


def test_desktop_flag_rejected_for_complex_tier(api):
    """PRD 3.3: "The same call may mark the order as a desktop appraisal by
    passing `requires_inspection` false, but only when the resulting tier is
    `STANDARD`; requesting a desktop assignment for any other tier fails with
    `ERR_DESKTOP_NOT_ALLOWED`."

    Design: Corner/calculations/desktop_flag_rejected_for_complex_tier
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    order = create_order(
        client["id"],
        property_address="2 Duplex",
        property_type="MULTI_2_4",
        estimated_value_cents=50000000,
    )

    response = api.determine_scope(
        order["id"], {"requires_inspection": False}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_DESKTOP_NOT_ALLOWED, 422)


def test_comp_gross_adjustment_boundary_2500(api):
    """PRD 3.5: "A comparable is eligible — `is_eligible` true — when its
    `net_adjustment_pct` is at most 15.00, its `gross_adjustment_pct` is at
    most 25.00, its `distance_miles` is at most 2.00, and its `sale_date` is
    no older than 365 days before the clock's date. All four boundaries are
    inclusive: a net of exactly 15.00, a gross of exactly 25.00, a distance
    of exactly 2.00 miles, and a sale exactly 365 days old all remain
    eligible."

    Design: Corner/calculations/comp_gross_adjustment_boundary_2500
    """
    ctx = setup_order_in_analysis()
    ok = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="G1",
        sale_price_cents=40000000,
        sale_date="2026-06-01",
        distance_miles=0.50,
        site_adjustment_cents=6000000,
        gla_adjustment_cents=0,
        condition_adjustment_cents=-4000000,
    )
    bad = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="G2",
        sale_price_cents=40000000,
        sale_date="2026-06-01",
        distance_miles=0.50,
        site_adjustment_cents=6040000,
        gla_adjustment_cents=0,
        condition_adjustment_cents=-4000000,
    )

    ok_v = verify_comparable(ok["id"], ctx["appraiser"]["id"])
    assert ok_v["net_adjustment_pct"] == 5.0
    assert ok_v["gross_adjustment_pct"] == 25.0
    assert ok_v["is_eligible"] is True

    bad_v = verify_comparable(bad["id"], ctx["appraiser"]["id"])
    assert bad_v["net_adjustment_pct"] == 5.1
    assert bad_v["gross_adjustment_pct"] == 25.1
    assert bad_v["is_eligible"] is False


def test_comp_sale_recency_365_day_boundary(api):
    """PRD 3.5: "All four boundaries are inclusive: a net of exactly 15.00, a
    gross of exactly 25.00, a distance of exactly 2.00 miles, and a sale
    exactly 365 days old all remain eligible."
    PRD 3.5: "When the verdict is false, `ineligible_reasons` carries the
    applicable subset of `NET_ADJ_EXCEEDED` (net above 15.00),
    `GROSS_ADJ_EXCEEDED` (gross above 25.00), `DISTANCE_EXCEEDED` (distance
    above 2.00 miles), and `SALE_TOO_OLD` (sale date older than 365 days)".
    PRD 3.5: "it refuses an ineligible comparable with `ERR_COMP_INELIGIBLE`."

    Design: Corner/calculations/comp_sale_recency_365_day_boundary
    """
    ctx = setup_order_in_analysis()
    ok = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="Old-OK",
        sale_price_cents=44000000,
        sale_date="2025-08-01",  # exactly 365 days before the 2026-08-01 clock
        distance_miles=0.40,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )
    bad = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="Old-Bad",
        sale_price_cents=44000000,
        sale_date="2025-07-31",  # 366 days old
        distance_miles=0.40,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )

    ok_v = verify_comparable(ok["id"], ctx["appraiser"]["id"])
    assert ok_v["is_eligible"] is True

    bad_v = verify_comparable(bad["id"], ctx["appraiser"]["id"])
    assert bad_v["is_eligible"] is False
    assert "SALE_TOO_OLD" in bad_v["ineligible_reasons"]

    response = api.lock_comparable(bad["id"], ctx["appraiser_headers"])
    validate_error(response, ApiErrorId.ERR_COMP_INELIGIBLE, 422)


def test_value_conclusion_distance_weighting(api):
    """PRD 3.6: "Each comparable carries a distance weight: 3 when its
    `distance_miles` is at most 0.50, 2 when at most 1.00, and 1 beyond that.
    The raw conclusion is the weighted mean — the sum of each weight times
    its comparable's `adjusted_price_cents`, divided by the sum of the
    weights — carried exactly, without intermediate rounding. The final
    `value_conclusion_cents` applies a single rounding: the mean, rounded
    half-up to the nearest 100000 cents — the nearest thousand dollars."

    Design: Corner/calculations/value_conclusion_distance_weighting
    """
    ctx = setup_order_in_analysis()
    add_locked_comp(
        ctx,
        address="Near",
        sale_price_cents=44000000,
        sale_date="2026-06-15",
        distance_miles=0.40,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )
    add_locked_comp(
        ctx,
        address="Mid",
        sale_price_cents=45000000,
        sale_date="2026-06-10",
        distance_miles=0.90,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )
    add_locked_comp(
        ctx,
        address="Far",
        sale_price_cents=46000000,
        sale_date="2026-05-20",
        distance_miles=1.50,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )

    from test_helpers import create_report

    report = create_report(ctx["order"]["id"], ctx["appraiser"]["id"])
    # (3*44000000 + 2*45000000 + 1*46000000) / 6 = 44666666.67 -> 44700000
    assert report["value_conclusion_cents"] == 44700000


def test_delivery_exactly_at_due_at_counts_on_time(api):
    """PRD 3.2: "Its `on_time_count` counts the subset delivered on or before
    the order's `due_at`."
    PRD 3.3: "Acceptance also stamps `accepted_at` with the logical clock,
    computes `due_at` as exactly `requested_turn_days` calendar days after
    `accepted_at`".

    Design: Corner/calculations/delivery_exactly_at_due_at_counts_on_time
    """
    # accepted at 2026-08-01, turn 7 -> due_at 2026-08-08T00:00:00Z
    ctx = setup_report_qc_passed()
    set_clock("2026-08-08T00:00:00Z")
    from test_helpers import deliver_report

    deliver_report(ctx["report"]["id"], ctx["appraiser"]["id"])

    scorecard = get_scorecard(ctx["appraiser"]["id"])
    assert scorecard["completed_count"] == 1
    assert scorecard["on_time_count"] == 1


def test_cancellation_fee_state_dependent(api):
    """PRD 3.9: "The cancellation fee, stored in `cancellation_fee_cents`, is
    zero when cancelling from `RECEIVED` or `SCOPE_DETERMINED`; from
    `ACCEPTED` or `ASSIGNED` it is half of `fee_current_cents`, rounded
    half-up to whole cents — a 45500-cent fee yields a 22750-cent
    cancellation fee."

    Design: Corner/calculations/cancellation_fee_state_dependent
    """
    ctx = setup_accepted_order()
    order1 = ctx["order"]  # SCOPE_DETERMINED? no — accepted; build a second
    # First: cancel an order that is only SCOPE_DETERMINED.
    order_scoped = create_order(ctx["client"]["id"])
    scope_order(order_scoped["id"], requires_inspection=False)
    cancelled_early = validate_success(
        api.cancel_order(order_scoped["id"], {"reason": "withdrawn early"}, ADMIN), 200
    )
    assert cancelled_early["cancellation_fee_cents"] == 0

    # Second: assign then cancel from ASSIGNED (fee_current 45000).
    assigned = assign_order(order1["id"], ctx["appraiser"]["id"])
    assert assigned["status"] == "ASSIGNED"
    cancelled_late = validate_success(
        api.cancel_order(order1["id"], {"reason": "withdrawn late"}, ADMIN), 200
    )
    assert cancelled_late["cancellation_fee_cents"] == 22500


def test_cancellation_fee_half_cent_rounds_half_up(api):
    """PRD 2.6: "Whenever a calculation would produce a fractional cent — a
    rush premium, a half-fee cancellation, a per-line comparable adjustment —
    the result is rounded half-up to the nearest whole cent, where "half-up"
    means an exact half rounds up (a 45500-cent fee halved yields 22750
    cents, never 22749)."
    PRD 3.9: "from `ACCEPTED` or `ASSIGNED` it is half of `fee_current_cents`,
    rounded half-up to whole cents".

    Design: Corner/calculations/cancellation_fee_half_cent_rounds_half_up
    """
    ctx = setup_accepted_order()
    adjusted = validate_success(
        api.create_fee_adjustment(
            ctx["order"]["id"],
            create_fee_adjustment_payload("SURCHARGE", 1, reason="rounding probe"),
            ADMIN,
        ),
        200,
    )
    assert adjusted["fee_current_cents"] == 45001

    cancelled = validate_success(
        api.cancel_order(ctx["order"]["id"], {"reason": "cancel odd fee"}, ADMIN), 200
    )
    # round_half_up(45001 * 0.5) = round_half_up(22500.5) = 22501
    assert cancelled["cancellation_fee_cents"] == 22501


def test_purge_at_exact_retention_instant_rejected(api):
    """PRD 3.8: "Its `retention_until` must be set and must fall strictly
    before the logical clock, failing with `ERR_RETENTION_NOT_EXPIRED`
    otherwise".
    PRD 3.8: "A successful purge stamps `purged_at` and lands the record in
    the terminal `PURGED` state."

    Design: Corner/calculations/purge_at_exact_retention_instant_rejected
    """
    ctx = setup_delivered_order(delivery_clock="2026-08-02T00:00:00Z")
    record = first_workfile_of_type(ctx["order"]["id"], "ORDER_FORM")

    # retention_until == 2031-08-02T00:00:00Z exactly -> still rejected
    set_clock("2031-08-02T00:00:00Z")
    response = api.purge_workfile_record(record["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_RETENTION_NOT_EXPIRED, 422)

    set_clock("2031-08-03T00:00:00Z")
    purged = validate_success(api.purge_workfile_record(record["id"], COMPLIANCE), 200)
    assert purged["status"] == "PURGED"


def test_comparable_patch_recomputes_derived_fields(api):
    """PRD 3.5: "While a comparable remains `DRAFT` or `VERIFIED`, the
    appraiser may revise `sale_price_cents`, `distance_miles`, or any of the
    four adjustment lines, and every such edit recomputes the derived
    figures."
    PRD 3.5: "The `net_adjustment_pct` is the absolute value of that net sum
    divided by `sale_price_cents`, expressed as a percentage rounded half-up
    to two decimal places."

    Design: Corner/calculations/comparable_patch_recomputes_derived_fields
    """
    ctx = setup_order_in_analysis()
    comp = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="9 Cmp Rd",
        sale_price_cents=45250000,
        sale_date="2026-06-01",
        distance_miles=0.30,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )
    assert comp["adjusted_price_cents"] == 45250000

    patched = validate_success(
        api.patch_comparable(
            comp["id"], {"condition_adjustment_cents": 6000}, ctx["appraiser_headers"]
        ),
        200,
    )
    # +6000 rounds per-line to +10000; net pct = 10000/45250000 -> 0.02
    assert patched["adjusted_price_cents"] == 45260000
    assert patched["net_adjustment_pct"] == 0.02

    fetched = validate_success(api.get_comparable(comp["id"], ADMIN), 200)
    assert fetched["adjusted_price_cents"] == 45260000
