"""Money formulas whose sub-expressions read deliberately different bases.

Both scenarios accumulate several rows against one counterparty, so a formula
that rounds at the wrong moment, or that reads the wrong basis for one of its
factors, lands on a visibly different total.
"""

from test_helpers import api_client, fixtures, validate_paginated
from test_helpers.test_users import TEST_USERS

OPERATOR = TEST_USERS["pool_operator_headers"]

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
    "restrict_threshold_pct": 25,
    "freeze_threshold_pct": 10,
    "restricted_max_kegs_per_order": 2,
}

AGREEMENT = {"per_fill_rate_cents": 2200, "replenishment_threshold_pct": 20}


def _accruals_by_keg(distributor_id):
    rows, _meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": distributor_id}
        )
    )
    return {row["keg_id"]: row for row in rows}


def _three_returns_at_silver_with_spread_dwell():
    """Three kegs handed to one `SILVER` distributor on the same day and
    returned 12, 20 and 35 days later, so each accrual falls in a different
    dwell band."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=8,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    distributor = fixtures.create_distributor(return_incentive_rate_cents_per_keg=250)
    distributor = fixtures.sign_cooperation_agreement(
        distributor["id"], "SILVER", "2026-08-01"
    )
    ctx["distributor"] = distributor

    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 3, "2026-08-01T02:00:00Z"
    )
    issued = order["allocated_keg_ids"]
    ctx["order"] = order
    ctx["issued_keg_ids"] = issued

    for keg_id in issued:
        fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T06:00:00Z", "RDG")
    for keg_id in issued:
        fixtures.distribution_scan(
            keg_id, distributor["id"], "2026-08-01T12:00:00Z", "RDG"
        )

    fixtures.pin_clock("2026-09-20T00:00:00Z")
    returned_at = [
        "2026-08-13T12:00:00Z",
        "2026-08-21T12:00:00Z",
        "2026-09-05T12:00:00Z",
    ]
    ctx["return_scans"] = [
        fixtures.return_scan(keg_id, distributor["id"], instant, "RDG")
        for keg_id, instant in zip(issued, returned_at)
    ]
    ctx["accruals"] = _accruals_by_keg(distributor["id"])
    return ctx


def test_each_return_accrual_is_rounded_once_on_its_own_row():
    """A 250-cent base under a `SILVER` multiplier gives raw values of 287.5,
    172.5 and 71.875, and each row is rounded before anything is summed.

    PRD: "The accrual's `incentive_cents` is the base rate multiplied by the
    band factor as a proportion of 10000, multiplied by the cooperation factor
    as a proportion of 10000, rounded half up to whole cents — and that
    rounding happens once, on this one row, before any summation."

    Design: Difficulty/combinatorial_formula/return_incentive_rounds_per_keg_before_summation
    """
    ctx = _three_returns_at_silver_with_spread_dwell()
    accruals = [ctx["accruals"][keg_id] for keg_id in ctx["issued_keg_ids"]]

    assert [row["cooperation_multiplier_bp"] for row in accruals] == [
        11500,
        11500,
        11500,
    ]
    assert [row["incentive_cents"] for row in accruals] == [288, 173, 72]


def test_the_dwell_band_factor_steps_down_with_the_days_held():
    """Twelve, twenty and thirty-five days of distributor accountability land in
    the 14-day, 15-to-29-day and 30-to-44-day bands respectively.

    PRD: "The dwell band factor is 10000 basis points when the accountability
    spell closed in 14 days or fewer, 6000 basis points from 15 through 29 days,
    2500 basis points from 30 through 44 days, and 0 basis points at 45 days or
    more — so a keg returned outside the 45-day distributor allowance earns
    nothing."

    Design: Difficulty/combinatorial_formula/return_incentive_rounds_per_keg_before_summation
    """
    ctx = _three_returns_at_silver_with_spread_dwell()
    accruals = [ctx["accruals"][keg_id] for keg_id in ctx["issued_keg_ids"]]

    assert [row["dwell_days"] for row in accruals] == [12, 20, 35]
    assert [row["tier_pct_bp"] for row in accruals] == [10000, 6000, 2500]


def test_the_incentive_ledger_sums_the_already_rounded_rows():
    """The ledger reads 533 cents, which is 288 plus 173 plus 72; rounding the
    raw sum instead would report 532.

    PRD: "Rounding the summed raw values instead would give a different, wrong
    answer: three returns at a base of 250 with a `SILVER` multiplier and dwell
    of 12, 20 and 35 days round to 288, 173 and 72 cents for a ledger of 533,
    whereas summing the raw 287.5, 172.5 and 71.875 and rounding the total would
    give 532."

    Design: Difficulty/combinatorial_formula/return_incentive_rounds_per_keg_before_summation
    """
    ctx = _three_returns_at_silver_with_spread_dwell()
    distributor = fixtures.read_distributor(ctx["distributor"]["id"])

    assert distributor["incentive_accrual_cents"] == 533
    assert distributor["incentive_accrual_cents"] != 532

    assert distributor["total_returns_count"] == 3
    assert distributor["on_time_returns_count"] == 3
    assert distributor["on_time_return_pct"] == 100.00
    assert distributor["avg_dwell_days"] == 22.33
    assert distributor["cooperation_tier"] == "SILVER"

    last_keg = fixtures.read_keg(ctx["issued_keg_ids"][2])
    assert last_keg["custody_state"] == "IN_SERVICE"
    assert last_keg["distributor_custody_started_at"] is None


def _two_fills_across_the_volume_tier_boundary():
    """One keg held 50 brewer-days and billed first, then a second keg dispatched
    and filled the same hour, so the second fill's tier basis is the first
    fill's ledger plus its own pre-discount amount."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=8,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    first_order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T00:00:00Z"
    )
    ctx["first_order"] = first_order
    ctx["first_keg_id"] = first_order["allocated_keg_ids"][0]

    fixtures.pin_clock("2026-09-20T06:00:00Z")
    ctx["first_fill"] = fixtures.fill_scan(
        ctx["first_keg_id"], ctx["brewer"]["id"], "2026-09-20T00:00:00Z", "RDG"
    )
    ctx["agreement_after_first_fill"] = fixtures.read_agreement(ctx["agreement"]["id"])

    second_order = fixtures.create_order(ctx["agreement"]["id"], 1)
    second_order = fixtures.allocate_order(
        second_order["id"], ctx["agreement"]["id"]
    )
    second_order = fixtures.dispatch_order(
        second_order["id"], "2026-09-20T01:00:00Z"
    )
    ctx["second_order"] = second_order
    ctx["second_keg_id"] = second_order["allocated_keg_ids"][0]
    ctx["second_fill"] = fixtures.fill_scan(
        ctx["second_keg_id"], ctx["brewer"]["id"], "2026-09-20T02:00:00Z", "RDG"
    )
    return ctx


def test_the_dwell_surcharge_is_capped_on_the_base_alone():
    """Fifty brewer-days give a raw surcharge of 600, but the cap is 20 percent
    of the 2200-cent base, so 440 is applied and the net charge is 2640 rather
    than the 2760 a cap on base-plus-surcharge would produce.

    PRD: "That raw surcharge is then capped at 20 percent of the base *alone*,
    rounded half up to whole cents — never 20 percent of the base plus the raw
    surcharge, and never a percentage of the post-discount total — and the
    surcharge actually applied is the smaller of the raw figure and that cap."

    Design: Difficulty/combinatorial_formula/fill_charge_pinned_order_cap_on_base_then_self_inclusive_tier
    """
    ctx = _two_fills_across_the_volume_tier_boundary()
    first_fill = ctx["first_fill"]

    assert first_fill["dwell_days_closed"] == 50
    assert first_fill["fill_charge_net_cents"] == 2640
    assert first_fill["fill_charge_net_cents"] != 2760
    assert ctx["agreement_after_first_fill"]["billed_amount_cents"] == 2640


def test_the_volume_tier_basis_counts_the_current_fill():
    """The second fill carries no surcharge, and its tier basis of 2640 plus 2200
    reaches 4840, earning the 150-basis-point discount and a net charge of 2167
    instead of the flat 2200 an exclusive basis would bill.

    PRD: "The volume tier is then chosen using the agreement's already-billed
    `billed_amount_cents` **plus this fill's pre-discount amount**, so the
    current fill counts toward its own tier: a basis of at least 9000 cents earns
    a 300-basis-point discount, a basis of at least 4500 cents earns 150 basis
    points, and anything less earns none, with both comparisons inclusive so a
    basis of exactly 9000 earns the higher rate."

    Design: Difficulty/combinatorial_formula/fill_charge_pinned_order_cap_on_base_then_self_inclusive_tier
    """
    ctx = _two_fills_across_the_volume_tier_boundary()
    second_fill = ctx["second_fill"]

    assert second_fill["dwell_days_closed"] == 0
    assert second_fill["fill_charge_net_cents"] == 2167
    assert second_fill["fill_charge_net_cents"] != 2200

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["billed_amount_cents"] == 4807


def test_the_charge_reads_the_agreement_base_and_not_the_order_pinned_price():
    """Both fills are priced off the agreement's own rate; the order's pinned
    copy records the same 2200 cents and is not the input to either charge.

    PRD: "The base is the agreement's current `per_fill_rate_cents` — taken from
    the agreement, not from the order's `per_fill_price_cents_pinned`."

    Design: Difficulty/combinatorial_formula/fill_charge_pinned_order_cap_on_base_then_self_inclusive_tier
    """
    ctx = _two_fills_across_the_volume_tier_boundary()

    assert ctx["second_order"]["per_fill_price_cents_pinned"] == 2200

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["per_fill_rate_cents"] == 2200
    assert agreement["billed_fills_count"] == 2

    assert fixtures.read_keg(ctx["first_keg_id"])["fill_count"] == 1
    assert fixtures.read_keg(ctx["second_keg_id"])["fill_count"] == 1
