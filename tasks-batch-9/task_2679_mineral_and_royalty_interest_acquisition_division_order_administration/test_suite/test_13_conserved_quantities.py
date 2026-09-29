"""Acreage and money survive their forward-and-compensating action pairs."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_acreage,
    assert_division_order_revenue_conserved,
    assert_money,
    assert_unit_acreage_conserved,
)
from test_helpers.test_users import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    ADMIN_USER_ID_ALT,
    OPERATOR_HEADERS,
)

PUGH_UNIT = {"pugh_clause_active": True, "pugh_deadline": "2026-12-31"}


def _pugh_ready_allocation(api):
    """A pugh-bearing unit with one ACTIVE 320.0000-acre allocation, clock past the deadline."""
    world = fx.unit_with_allocation_ready(api, unit_overrides=PUGH_UNIT)
    fx.set_clock(api, "2027-01-01T00:00:00Z")
    return world


def test_the_commitment_itself_conserves_the_unit_total(api):
    """320.0000 committed plus 960.0000 unallocated is still 1280.0000.

    PRD: "For any unit, the sum of `allocated_acres` across its allocations whose
    `allocation_status` is either `ACTIVE` or `PUGH_RELEASED`, plus the unit's
    `unallocated_acres`, rounded to 4 decimal places, always equals that unit's
    `unit_gross_acres`."

    Design: Difficulty/compensating_invariant/unit_acreage_total_preserved_across_pugh_release_and_termination
    """
    world = _pugh_ready_allocation(api)

    unit = fx.read_unit(api, world["unit"]["id"])
    allocations, _meta = validate_paginated(
        api.list_unit_tract_allocations(world["unit"]["id"], OPERATOR_HEADERS)
    )

    assert_acreage(unit["unallocated_acres"], "960.0000", "unallocated_acres")
    assert unit["active_allocation_count"] == 1
    assert_unit_acreage_conserved(unit, allocations)


def test_a_pugh_release_hands_back_exactly_the_released_acres(api):
    """213.3333 held plus 1066.6667 unallocated is still 1280.0000.

    PRD: "a pugh release moves exactly `released_acres` from the allocation back
    to `unallocated_acres`, so the identity also holds mid-cycle"

    Design: Difficulty/compensating_invariant/unit_acreage_total_preserved_across_pugh_release_and_termination
    """
    world = _pugh_ready_allocation(api)

    released = fx.pugh_release(api, world["allocation"]["id"])

    assert released["allocation_status"] == "PUGH_RELEASED"
    assert_acreage(released["allocated_acres"], "213.3333", "allocated_acres")
    assert_acreage(released["released_acres"], "106.6667", "released_acres")
    unit = fx.read_unit(api, world["unit"]["id"])
    assert_acreage(unit["unallocated_acres"], "1066.6667", "unallocated_acres")
    assert unit["active_allocation_count"] == 1
    assert_unit_acreage_conserved(unit, [released])


def test_termination_returns_the_remainder_and_drops_the_row(api):
    """The unit is whole again at 1280.0000 with nothing in the summed set.

    PRD: "`TERMINATED` allocations are excluded from the sum precisely because
    their acreage has already gone home."

    PRD: "Across a create-then-terminate pair no acreage drifts: the unit's total
    returns to exactly what it was."

    Design: Difficulty/compensating_invariant/unit_acreage_total_preserved_across_pugh_release_and_termination
    """
    world = _pugh_ready_allocation(api)
    fx.pugh_release(api, world["allocation"]["id"])

    terminated = fx.terminate_allocation(
        api,
        world["allocation"]["id"],
        termination_reason="Remaining producing depths released after unit contraction",
    )

    assert terminated["allocation_status"] == "TERMINATED"
    assert_acreage(terminated["allocated_acres"], "213.3333", "allocated_acres")
    assert_acreage(terminated["released_acres"], "106.6667", "released_acres")
    unit = fx.read_unit(api, world["unit"]["id"])
    assert_acreage(unit["unallocated_acres"], "1280.0000", "unallocated_acres")
    assert unit["active_allocation_count"] == 0
    assert_unit_acreage_conserved(unit, [terminated])


def test_a_variance_routes_the_whole_line_into_suspense(api):
    """106.47 sits in accrued_amount, 0.00 in paid_net_total, and the sum holds.

    PRD: "For any division order, the sum of `net_amount` across all of its
    revenue check details — regardless of `check_status` — rounded to 2 decimal
    places, always equals its `paid_net_total` plus the sum of `accrued_amount`
    across its suspense accounts, again rounded to 2 decimal places."

    Design: Difficulty/compensating_invariant/division_order_net_revenue_total_preserved_across_variance_hold_and_release
    """
    world = fx.variance_held_ready(api)

    assert_money(world["detail"]["net_amount"], "106.47", "net_amount")
    assert_money(world["detail"]["variance_amount"], "9.05", "variance_amount")
    assert world["detail"]["check_status"] == "VARIANCE_HELD"

    order = fx.read_division_order(api, world["order"]["id"])
    assert order["do_status"] == "SUSPENDED"
    assert_money(order["paid_net_total"], "0.00", "paid_net_total")
    assert_money(order["cumulative_variance_amount"], "9.05", "cumulative_variance_amount")

    account = fx.read_suspense(api, world["suspense"]["id"])
    assert_money(account["accrued_amount"], "106.47", "accrued_amount")
    assert account["held_detail_count"] == 1
    assert account["first_suspended_month"] == "2026-06"
    assert_division_order_revenue_conserved(order, [world["detail"]], [account])


def test_statutory_interest_accrues_outside_the_conserved_total(api):
    """Two months at six percent adds 1.06 to a 107.53 payout, not to the identity.

    PRD: "`interest_accrued` is `accrued_amount` multiplied by an annual statutory
    rate of six percent, multiplied by `months_held`, divided by twelve, rounded
    half-up to cents. And `release_amount` — what a release would pay out — is
    `accrued_amount` plus `interest_accrued`, rounded half-up to cents."

    Design: Difficulty/compensating_invariant/division_order_net_revenue_total_preserved_across_variance_hold_and_release
    """
    world = fx.variance_held_ready(api)

    account = fx.read_suspense(api, world["suspense"]["id"])

    assert account["months_held"] == 2
    assert_money(account["interest_accrued"], "1.06", "interest_accrued")
    assert_money(account["release_amount"], "107.53", "release_amount")
    order = fx.read_division_order(api, world["order"]["id"])
    assert_division_order_revenue_conserved(order, [world["detail"]], [account])


def test_the_release_moves_the_money_back_without_drift(api):
    """paid_net_total becomes 106.47 as accrued_amount is zeroed, identity intact.

    PRD: "A variance routes a whole line's `net_amount` into `accrued_amount`
    instead of `paid_net_total`; a release moves exactly `accrued_amount` into
    `paid_net_total` and zeroes `accrued_amount`, leaving the total untouched."

    Design: Difficulty/compensating_invariant/division_order_net_revenue_total_preserved_across_variance_hold_and_release
    """
    world = fx.variance_held_ready(api)

    released = validate_success(
        api.release_suspense(world["suspense"]["id"], ADMIN_ALT_HEADERS), 200
    )

    assert released["suspense_status"] == "RELEASED"
    assert released["released_by_user_id"] == ADMIN_USER_ID_ALT
    assert_money(released["accrued_amount"], "0.00", "accrued_amount")
    assert released["held_detail_count"] == 0
    assert_money(released["interest_accrued"], "1.06", "interest_accrued")
    assert_money(released["release_amount"], "107.53", "release_amount")

    detail = fx.read_revenue_detail(api, world["detail"]["id"])
    assert detail["check_status"] == "PAID"
    assert_money(detail["net_amount"], "106.47", "net_amount")

    order = fx.read_division_order(api, world["order"]["id"])
    assert order["do_status"] == "EXECUTED"
    assert_money(order["paid_net_total"], "106.47", "paid_net_total")
    assert_money(order["cumulative_variance_amount"], "0.00", "cumulative_variance_amount")

    details, _meta = validate_paginated(
        api.list_revenue_check_details(world["order"]["id"], ADMIN_HEADERS)
    )
    assert_division_order_revenue_conserved(order, details, [released])
