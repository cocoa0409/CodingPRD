"""Queue A — the card-fee deduction: the two unit policies that price it and the
per-shift rounding order that pins its last cent."""
from test_helpers import (
    PREPARER,
    assert_allocations_sum_to,
    assert_pool_allocation,
    assert_pool_money_identity,
    distribute_pool,
    list_allocations_of,
    read_pool,
    read_shift,
    setup_texas_pool_world,
    setup_two_unit_card_fee_world,
    validate_success,
)


def _allocation_by_employee(pool_id: str) -> dict:
    return {row["employee_id"]: row for row in list_allocations_of(pool_id)}


# ---------------------------------------------------------------------------
# dual_variant_calc / pool_card_fee_actual_only_versus_capped_bps
# ---------------------------------------------------------------------------
def test_actual_only_unit_withholds_the_whole_four_hundred_basis_point_fee(api):
    """At ACTUAL_ONLY the shift's own 400 bps rate is what is withheld.

    PRD §3.7: "Under `ACTUAL_ONLY`, a shift's fee is that shift's
    `cc_processing_fee_bps` applied as a basis-point rate to that shift's
    `declared_charged_tips_cents`, rounded half up."
    PRD §3.7: "With the fee settled, `net_pool_cents` is `total_contributed_cents`
    plus `service_charge_tips_cents` less `cc_fee_deducted_cents`."
    PRD §3.7: "Exactly one extra cent goes to each of the first however-many
    participants the leftover permits, taken in descending order of `share_weight`
    and, where two participants tie on weight, in ascending order of their shifts'
    `created_at`."

    Design: Difficulty/dual_variant_calc/pool_card_fee_actual_only_versus_capped_bps
    """
    world = setup_two_unit_card_fee_world()
    unit = world["actual"]

    pool = validate_success(api.distribute_shift_tip_pool(unit["pool"]["id"], PREPARER))

    assert pool["total_contributed_cents"] == 6505
    assert pool["service_charge_tips_cents"] == 0
    assert pool["cc_fee_deducted_cents"] == 1682, (
        "1201 cents on the server's 30020 of card tips plus 481 on the "
        "bartender's 12020, each rounded on its own"
    )
    assert pool["net_pool_cents"] == 4823
    assert pool["total_share_weight"] == 8640
    assert pool["participant_count"] == 2
    assert pool["distributed_cents"] == 4823
    assert pool["distribution_status"] == "DISTRIBUTED"
    assert_pool_money_identity(pool)

    rows = _allocation_by_employee(unit["pool"]["id"])
    server = rows[unit["employee_server"]["id"]]
    bartender = rows[unit["employee_bartender"]["id"]]
    assert server["allocated_cents"] == 2680
    assert server["remainder_cent_awarded"] is True
    assert bartender["allocated_cents"] == 2143
    assert bartender["remainder_cent_awarded"] is False
    assert_allocations_sum_to(list(rows.values()), 4823)


def test_capped_bps_unit_withholds_only_the_three_hundred_basis_point_cap(api):
    """The identical fixture yields a smaller fee and a larger split under CAPPED_BPS.

    PRD §3.7: "Under `CAPPED_BPS`, the effective rate for a shift is the lesser of
    that shift's `cc_processing_fee_bps` and the unit's `cc_fee_cap_bps`, and the
    shift's fee is that effective rate applied to the same
    `declared_charged_tips_cents`, rounded half up."
    PRD §3.1: "`CAPPED_BPS` means the state permits a deduction but caps it, and in
    that case `cc_fee_cap_bps` is required, must be greater than 0, and must lie
    between 1 and 1000 basis points inclusive."
    PRD §3.7: "The pool's `distributed_cents` becomes the sum of the rows'
    `allocated_cents`, which must equal `net_pool_cents` exactly."

    Design: Difficulty/dual_variant_calc/pool_card_fee_actual_only_versus_capped_bps
    """
    world = setup_two_unit_card_fee_world()
    unit = world["capped"]

    pool = validate_success(api.distribute_shift_tip_pool(unit["pool"]["id"], PREPARER))

    assert pool["total_contributed_cents"] == 6505, (
        "contributions are untouched by the card-fee policy"
    )
    assert pool["cc_fee_deducted_cents"] == 1262, (
        "901 plus 361, each computed at the capped 300 bps rather than the "
        "shift's own 400 bps"
    )
    assert pool["net_pool_cents"] == 5243
    assert pool["total_share_weight"] == 8640
    assert pool["participant_count"] == 2
    assert pool["distributed_cents"] == 5243
    assert_pool_money_identity(pool)

    rows = _allocation_by_employee(unit["pool"]["id"])
    assert rows[unit["employee_server"]["id"]]["allocated_cents"] == 2913
    assert rows[unit["employee_server"]["id"]]["remainder_cent_awarded"] is True
    assert rows[unit["employee_bartender"]["id"]]["allocated_cents"] == 2330
    assert_allocations_sum_to(list(rows.values()), 5243)


# ---------------------------------------------------------------------------
# combinatorial_formula / pool_card_fee_rounded_per_shift_then_summed
# ---------------------------------------------------------------------------
def test_card_fee_is_rounded_per_contributing_shift_then_summed(api):
    """Two exact halves round up separately to 1052, not to 1051 in the aggregate.

    PRD §3.7: "Each shift's fee is rounded half up on its own, and
    `cc_fee_deducted_cents` is the sum of those already-rounded per-shift figures."
    PRD §3.7: "It is emphatically not computed by summing the unrounded per-shift
    products and rounding the total once; the two orders can differ by as much as
    one cent fewer than `contributing_shift_count`."
    PRD §3.7: "On the pool itself, `total_contributed_cents` becomes the sum of the
    contributions across the contributing shifts and `contributing_shift_count`
    becomes the number of those shifts whose contribution came out greater than 0 —
    a stamped-in busser with a contribution of 0 is therefore not counted there."

    Design: Difficulty/combinatorial_formula/pool_card_fee_rounded_per_shift_then_summed
    """
    world = setup_texas_pool_world()

    pool = validate_success(
        api.distribute_shift_tip_pool(world["pool"]["id"], PREPARER)
    )

    assert pool["total_contributed_cents"] == 6505
    assert pool["contributing_shift_count"] == 2, (
        "the busser is stamped into the pool but contributes 0, so it is not counted"
    )
    assert pool["cc_fee_deducted_cents"] == 1052, (
        "750.5 rounds to 751 and 300.5 rounds to 301; summing 1051.0 first and "
        "rounding once would give 1051"
    )
    assert pool["net_pool_cents"] == 5453
    assert_pool_money_identity(pool)


def test_net_pool_is_split_across_three_hours_weighted_participants(api):
    """The busser's zero contribution still buys a share, and only the server wins the odd cent.

    PRD §3.7: "Under `HOURS_WEIGHTED_POINTS` it is `pool_share_points` multiplied
    by the shift's `scheduled_minutes`, giving an exact integer count of
    points-minutes; no division is taken, so no rounding can enter the weight."
    PRD §3.7: "Each participant's base share is `net_pool_cents` multiplied by that
    participant's `share_weight`, divided by `total_share_weight`, with any fraction
    discarded."
    PRD §3.7: "A participant that wins a leftover cent has `remainder_cent_awarded`
    set true on its ledger row; every other row carries false."

    Design: Difficulty/combinatorial_formula/pool_card_fee_rounded_per_shift_then_summed
    """
    world = setup_texas_pool_world()
    distribute_pool(world["pool"]["id"])

    pool = read_pool(world["pool"]["id"])
    assert pool["participant_count"] == 3
    assert pool["total_share_weight"] == 10440
    assert pool["distributed_cents"] == 5453

    rows = _allocation_by_employee(world["pool"]["id"])
    server = rows[world["employee_server"]["id"]]
    bartender = rows[world["employee_bartender"]["id"]]
    busser = rows[world["employee_busser"]["id"]]

    for row in (server, bartender, busser):
        assert_pool_allocation(row)
        assert row["entry_type"] == "DISTRIBUTION"

    assert (server["share_weight"], bartender["share_weight"], busser["share_weight"]) == (
        4800,
        3840,
        1800,
    )
    assert server["allocated_cents"] == 2508
    assert bartender["allocated_cents"] == 2005
    assert busser["allocated_cents"] == 940
    assert_allocations_sum_to([server, bartender, busser], 5453)

    assert server["remainder_cent_awarded"] is True
    assert bartender["remainder_cent_awarded"] is False
    assert busser["remainder_cent_awarded"] is False

    assert read_shift(world["shift_server"]["id"])["retained_tips_cents"] == 28917
    assert read_shift(world["shift_bartender"]["id"])["retained_tips_cents"] == 12618
    assert read_shift(world["shift_busser"]["id"])["retained_tips_cents"] == 0
