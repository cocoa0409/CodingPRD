"""The two dual-variant calculations: the actual-cash-value curve evaluated at
two different as-of instants, and the coverage-gap waterfall run in its two
orders."""
from test_helpers import (
    add_cataloged_item,
    add_claim_line,
    add_generated_package,
    add_policy,
    add_room,
    api_client,
    bootstrap_household,
    assert_coverage_gap_read,
    open_claim,
    schedule_item,
    set_clock,
    submit_claim,
    validate_success,
)

ELECTRONICS_SCHEDULE = {
    "category": "ELECTRONICS",
    "useful_life_months": 60,
    "annual_depreciation_pct": 20.0,
    "salvage_floor_pct": 10.0,
    "blanket_sublimit_cents": 500000,
    "appraisal_scope": "ELECTRONICS",
    "serial_required": True,
}

JEWELRY_SCHEDULE = {
    "category": "JEWELRY",
    "useful_life_months": 240,
    "annual_depreciation_pct": 4.0,
    "salvage_floor_pct": 40.0,
    "blanket_sublimit_cents": 300000,
    "appraisal_scope": "JEWELRY",
    "serial_required": False,
}


def _setup_acv_two_instants_scenario():
    """One ELECTRONICS item bought 2026-01-01 for 400000 cents, catalogued and
    packaged at 2026-05-01, then claimed at clock 2026-08-01 with a loss_date of
    2026-06-01 on an ACV-basis claim."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[ELECTRONICS_SCHEDULE])
    room = add_room(ctx, name="Study", floor_label="1")
    item = add_cataloged_item(
        ctx,
        room["id"],
        350000,
        photo_bytes=120000,
        name="Studio Monitor",
        category="ELECTRONICS",
        acquired_at="2026-01-01T00:00:00Z",
        quantity=1,
        serial_number="SM-4400",
        purchase_price_cents=400000,
    )
    policy = add_policy(
        ctx,
        policy_number="NW-1001",
        deductible_cents=100000,
        scheduled_allowance_cents=1000000,
    )
    package = add_generated_package(ctx, policy["id"])

    set_clock("2026-08-01T00:00:00Z")

    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room["id"]],
        loss_date="2026-06-01T00:00:00Z",
        peril="WATER",
        settlement_basis="ACV",
        deductible_mode="PRO_RATA",
    )
    line = add_claim_line(ctx, claim["id"], item["id"])
    submit_claim(ctx, claim["id"])
    ctx.update({"room": room, "item": item, "policy": policy, "package": package,
                "claim": claim, "line": line})
    return ctx


def test_item_acv_uses_the_current_clock_instant(api):
    """PRD 3.4: "In the **current-clock** variant the as-of instant is the
    logical clock's current instant; this is what writes `acv_value_cents` and
    what feeds the effective-value resolution on every ordinary read or write."
    PRD 3.4: "elapsed days are the whole days from `acquired_at` to the as-of
    instant, rounded down; the age in months is those elapsed days divided by 30
    and rounded down, never below zero, so a month here is a flat 30 days rather
    than a calendar month; the depreciated percentage is the category's
    `annual_depreciation_pct` divided by 12 and multiplied by the age in months,
    capped at 100; the raw amount is `purchase_price_cents` multiplied by one
    minus the depreciated percentage divided by one hundred; the salvage floor is
    `purchase_price_cents` multiplied by `salvage_floor_pct` divided by one
    hundred; and the result is the larger of the raw amount and the salvage
    floor, rounded half up to whole cents **once**, at the very end."

    Design: Difficulty/dual_variant_calc/acv_at_loss_date_diverges_from_acv_at_current_clock
    """
    ctx = _setup_acv_two_instants_scenario()

    item = validate_success(api.get_item(ctx["item"]["id"], ctx["owner_headers"]))
    assert item["acv_value_cents"] == 353333, (
        f"212 days of age is 7 whole 30-day months at 20%/yr: expected 353333, "
        f"got {item['acv_value_cents']}"
    )
    assert item["effective_value_basis"] == "ACV"
    assert item["effective_value_cents"] == 353333


def test_claim_line_gross_uses_the_loss_date_instant_not_the_clock(api):
    """PRD 3.4: "In the **loss-date** variant the as-of instant is the claim's
    `loss_date`, used when computing a claim line's gross value on an `ACV`-basis
    claim; because the loss date precedes the clock, the age in months is smaller
    and the value is strictly higher for any item whose depreciation has not yet
    reached its salvage floor — identical item data, two different numbers."
    PRD 3.7: "When the claim's `settlement_basis` is `ACV`, the unit value is the
    item's actual cash value evaluated with an as-of instant of the claim's
    `loss_date`, divided by that quantity."
    PRD 3.7: "the anchor's share is the smaller of the policy's `deductible_cents`
    and the base, minus the sum of all the other shares — so the shares always add
    up exactly, with the anchor absorbing the rounding remainder."

    Design: Difficulty/dual_variant_calc/acv_at_loss_date_diverges_from_acv_at_current_clock
    """
    ctx = _setup_acv_two_instants_scenario()

    line = validate_success(api.get_claim_line(ctx["line"]["id"], ctx["owner_headers"]))
    item = validate_success(api.get_item(ctx["item"]["id"], ctx["owner_headers"]))

    assert line["gross_value_cents"] == 366667, (
        f"151 days of age is 5 whole 30-day months at 20%/yr: expected 366667, "
        f"got {line['gross_value_cents']}"
    )
    assert line["capped_value_cents"] == 366667
    assert line["deductible_share_cents"] == 100000
    assert line["net_settlement_cents"] == 266667
    assert line["gross_value_cents"] - item["acv_value_cents"] == 13334, (
        "the two as-of instants must diverge by exactly 13334 cents"
    )


def _setup_coverage_gap_variant_scenario():
    """Two JEWELRY items: A (created first, declared 200000, SCHEDULED at
    200000) and B (created second, declared 400000, left on BLANKET), against a
    policy with a 1000000-cent scheduling allowance and a 300000-cent sublimit."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[JEWELRY_SCHEDULE])
    room = add_room(ctx, name="Dressing Room", floor_label="2")
    policy = add_policy(
        ctx,
        policy_number="NW-2002",
        deductible_cents=50000,
        scheduled_allowance_cents=1000000,
    )
    item_a = add_cataloged_item(
        ctx,
        room["id"],
        200000,
        photo_bytes=90000,
        name="Sapphire Ring",
        category="JEWELRY",
        acquired_at="2024-01-01T00:00:00Z",
        quantity=1,
    )
    item_b = add_cataloged_item(
        ctx,
        room["id"],
        400000,
        photo_bytes=90000,
        name="Pearl Necklace",
        category="JEWELRY",
        acquired_at="2024-02-01T00:00:00Z",
        quantity=1,
    )
    schedule_item(ctx, item_a["id"], policy["id"], 200000)
    ctx.update({"room": room, "policy": policy, "item_a": item_a, "item_b": item_b})
    return ctx


def test_coverage_gap_scheduled_first_spends_the_allowance_before_the_sublimit(api):
    """PRD 3.5: "Starting with the allowance pool set to the policy's
    `scheduled_allowance_cents`, each candidate in creation order that is
    `SCHEDULED` on **this** policy takes the smallest of three numbers: its own
    `scheduled_value_cents`, its effective value, and whatever remains in the
    allowance pool; that amount becomes its covered figure and leaves the pool."
    PRD 3.5: "`schedule_required_unscheduled_count` counts the candidates whose
    effective value is at or above the 500,000-cent scheduling threshold **and**
    whose `coverage_mode` is still `BLANKET` — an object that valuable which is not
    individually scheduled is only ever covered up to its category's shared
    sublimit, and this counter is the headline warning a documentation package is
    meant to surface."

    Design: Difficulty/dual_variant_calc/coverage_gap_scheduled_first_diverges_from_blanket_first
    """
    ctx = _setup_coverage_gap_variant_scenario()

    data = validate_success(
        api.get_coverage_gap(
            ctx["policy"]["id"], ctx["owner_headers"], params={"basis": "SCHEDULED_FIRST"}
        )
    )
    assert_coverage_gap_read(data)
    assert data["total_value_cents"] == 600000
    assert data["total_covered_cents"] == 500000, (
        "the scheduled item takes 200000 from the allowance, the blanket item takes "
        f"the whole 300000 sublimit; got {data['total_covered_cents']}"
    )
    assert data["coverage_gap_cents"] == 100000
    assert data["item_count"] == 2
    assert data["schedule_required_unscheduled_count"] == 0

    policy = validate_success(api.get_policy(ctx["policy"]["id"], ctx["owner_headers"]))
    assert policy["coverage_gap_cents"] == 100000, (
        "the SCHEDULED_FIRST result is the only variant written back to the policy"
    )


def test_coverage_gap_blanket_first_exhausts_the_sublimit_first(api):
    """PRD 3.5: "With a sublimit pool per category set to that category's
    `blanket_sublimit_cents`, each candidate in creation order takes the smaller of
    its effective value and its category's remaining sublimit as its covered
    figure, removing that amount from the category pool, and its residual is its
    effective value minus that amount."
    PRD 3.5: "The two variants report different gaps for identical data whenever a
    scheduled item shares a category with unscheduled items and the sublimit binds,
    because under `BLANKET_FIRST` the early unscheduled items exhaust the sublimit
    the scheduled item would otherwise have fallen back on."

    Design: Difficulty/dual_variant_calc/coverage_gap_scheduled_first_diverges_from_blanket_first
    """
    ctx = _setup_coverage_gap_variant_scenario()

    data = validate_success(
        api.get_coverage_gap(
            ctx["policy"]["id"], ctx["owner_headers"], params={"basis": "BLANKET_FIRST"}
        )
    )
    assert_coverage_gap_read(data)
    assert data["total_value_cents"] == 600000
    assert data["total_covered_cents"] == 300000, (
        "the earlier scheduled item consumes 200000 of the sublimit and keeps no "
        f"residual for the allowance stage; got {data['total_covered_cents']}"
    )
    assert data["coverage_gap_cents"] == 300000

    policy = validate_success(api.get_policy(ctx["policy"]["id"], ctx["owner_headers"]))
    assert policy["coverage_gap_cents"] == 100000, (
        "reading BLANKET_FIRST must not overwrite the stored SCHEDULED_FIRST gap"
    )
