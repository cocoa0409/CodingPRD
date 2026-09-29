"""Off-by-one boundaries: exposure on the credit limit, an order with zero versus
one line, and a return raised on day thirty versus day thirty-one."""
import pytest

from test_helpers import (
    CREDIT_MANAGER,
    ApiErrorId,
    add_line,
    api_client,
    approve_credit,
    assert_inventory_units,
    inventory_for,
    list_order_lines,
    list_return_authorizations,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_part,
    make_pricing_tier,
    make_servicer_headers,
    open_will_call_order,
    order_line_payload,
    read_account,
    read_line,
    read_order,
    read_return_authorization,
    return_authorization_payload,
    set_clock,
    setup_catalog,
    setup_will_call_order,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _account_whose_limit_is_one_line_wide():
    """A 31,197-cent credit limit and an empty order — exactly the amount three
    discounted pumps come to."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    part = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Boundary Repairs",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=31197, core_liability_limit_cents=5000000,
    )
    order = open_will_call_order(account, branch)
    return {"branch": branch, "part": part, "account": account, "order": order}


def _two_credit_approved_orders_one_empty_one_single_line():
    """Two credit-approved will-call orders on the same account: one with no lines
    at all, one with exactly one."""
    world = setup_catalog(
        tier_kwargs={
            "tier_code": "GOLD", "name": "Gold Contract",
            "electrical": 0.15, "mechanical": 0.20, "cosmetic": 0.25,
            "sealed_system": 0.10, "min_annual_volume_cents": 5000000,
        },
        branch_kwargs={
            "code": "STL", "name": "St Louis DC", "region_code": "MW",
            "will_call_enabled": True, "cutoff_hour_utc": 20,
            "overnight_surcharge_cents": 300,
        },
        on_hand_units=10,
        account_kwargs={"core_liability_limit_cents": 5000000},
    )
    empty_order = open_will_call_order(
        world["account"], world["branch"], purchase_order_ref="PO-Z"
    )
    approve_credit(empty_order)

    single_line_order = open_will_call_order(
        world["account"], world["branch"], purchase_order_ref="PO-Y"
    )
    single_line = add_line(single_line_order, world["part"], quantity=1)
    approve_credit(single_line_order)

    world["empty_order"] = empty_order
    world["single_line_order"] = single_line_order
    world["single_line"] = single_line
    return world


def _shipped_order_with_two_returnable_lines():
    """Two separate single-unit pump lines shipped on 2026-08-01, so one can be
    returned on day thirty and the other tried on day thirty-one."""
    world = setup_will_call_order(
        stage="lines", quantity=1,
        branch_kwargs={
            "code": "STL", "name": "St Louis DC", "region_code": "MW",
            "will_call_enabled": True, "cutoff_hour_utc": 20,
            "overnight_surcharge_cents": 300,
        },
        account_kwargs={"core_liability_limit_cents": 5000000},
    )
    world["second_line"] = add_line(world["order"], world["part"], quantity=1)
    approve_credit(world["order"])
    branch_headers = make_branch_counter_rep_headers(world["branch"]["id"])
    validate_success(
        api_client.allocate_part_order(world["order"]["id"], branch_headers), 200
    )
    validate_success(
        api_client.fulfill_part_order(
            world["order"]["id"], {"tracking_ref": "WILLCALL-B30"}, branch_headers
        ),
        200,
    )
    return world


# ---------------------------------------------------------------------------
# Credit exposure against the limit
# ---------------------------------------------------------------------------

class TestCreditLimitBoundary:

    def test_exposure_landing_exactly_on_the_credit_limit_is_accepted(self):
        """PRD §3.4: "and the account's credit exposure recomputed **with this
        line included** must not exceed its `credit_limit_cents`, or the add is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."
        PRD §3.5: "Approval requires the owning account to be `ACTIVE` and
        requires the account's credit exposure — which already includes this
        order's `total_cents` — to be no greater than its `credit_limit_cents`; an
        exposure exactly equal to the limit passes, one cent more fails with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/credit_exposure_exactly_at_limit_is_accepted_one_cent_over_is_not
        """
        world = _account_whose_limit_is_one_line_wide()

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(world["part"]["id"], 3, world["order"]["version"]),
            make_servicer_headers(world["account"]["id"]),
        )
        line = validate_success(response, 201)
        assert line["extended_price_cents"] == 31197, (
            f"Expected 10399 x 3 = 31197, got {line['extended_price_cents']}"
        )

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 31197, (
            f"an exposure exactly equal to the 31197 limit is accepted, got "
            f"{account['credit_used_cents']}"
        )

    def test_one_more_unit_pushes_the_exposure_over_and_is_refused(self):
        """PRD §3.4: "That last check needs care: the order's own total is already
        inside the exposure aggregate, so the new line's contribution must be
        folded into that aggregate rather than added on top of it."
        PRD §2.7: "48. `ERR_CREDIT_LIMIT_EXCEEDED` (402) — the account's credit
        exposure, recomputed with the pending change applied, does not exceed
        `credit_limit_cents`. Guards two operations:
        `POST /part-orders/{id}/lines` and
        `POST /part-orders/{id}/credit-decision`."

        Design: Difficulty/boundary_precision_check/credit_exposure_exactly_at_limit_is_accepted_one_cent_over_is_not
        """
        world = _account_whose_limit_is_one_line_wide()
        validate_success(
            api_client.add_order_line(
                world["order"]["id"],
                order_line_payload(world["part"]["id"], 3, world["order"]["version"]),
                make_servicer_headers(world["account"]["id"]),
            ),
            201,
        )
        order = read_order(world["order"]["id"])

        response = api_client.add_order_line(
            order["id"],
            order_line_payload(world["part"]["id"], 1, order["version"]),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

        after = read_order(order["id"])
        assert after["subtotal_cents"] == 31197, (
            f"the refused projection of 41596 must not be persisted, got "
            f"{after['subtotal_cents']}"
        )
        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 31197, (
            f"Expected the exposure to stay folded at 31197, got "
            f"{account['credit_used_cents']}"
        )
        lines = list_order_lines(part_order_id=order["id"])
        assert len(lines) == 1, f"Expected exactly one persisted line, got {len(lines)}"


# ---------------------------------------------------------------------------
# Zero lines versus one line at allocation
# ---------------------------------------------------------------------------

class TestAllocationLineCountBoundary:

    def test_allocating_an_order_with_no_lines_at_all_is_refused(self):
        """PRD §3.6: "The order must be in `DRAFT` with a `settlement_status` of
        either `CREDIT_APPROVED` or `PAID`, its account must be `ACTIVE`, and it
        must have at least one line whose `line_status` is not `CANCELLED` — an
        order with nothing left in it is rejected with `ERR_ORDER_HAS_NO_LINES`
        rather than allocating an empty shipment."
        PRD §3.5: "An order that has no lines at all approves cleanly at a
        `total_cents` of zero; the empty-order objection is raised later, at
        allocation."

        Design: Difficulty/boundary_precision_check/allocation_requires_at_least_one_line_zero_versus_one
        """
        world = _two_credit_approved_orders_one_empty_one_single_line()

        response = api_client.allocate_part_order(
            world["empty_order"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ORDER_HAS_NO_LINES)

        order = read_order(world["empty_order"]["id"])
        assert order["fulfillment_status"] == "DRAFT"
        assert order["total_cents"] == 0

    def test_allocating_an_order_with_exactly_one_line_succeeds(self):
        """PRD §3.6: "Each line that finds a branch moves `RESOLVED → ALLOCATED`,
        records the winning branch as its `allocation_branch_id`, raises that
        inventory record's `reserved_units` by the line's `quantity`, has its
        `available_units` recomputed, and increments that inventory record's
        `version`."
        PRD §3.6: "If at least one line ended `ALLOCATED`, the order moves
        `DRAFT → ALLOCATED`."

        Design: Difficulty/boundary_precision_check/allocation_requires_at_least_one_line_zero_versus_one
        """
        world = _two_credit_approved_orders_one_empty_one_single_line()

        response = api_client.allocate_part_order(
            world["single_line_order"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        allocated = validate_success(response, 200)
        assert allocated["fulfillment_status"] == "ALLOCATED"

        line = read_line(world["single_line"]["id"])
        assert line["line_status"] == "ALLOCATED"
        assert line["allocation_branch_id"] == world["branch"]["id"]

        order = read_order(world["single_line_order"]["id"])
        assert order["subtotal_cents"] == 10399
        assert order["total_cents"] == 10399

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=10, reserved=1, available=9)


# ---------------------------------------------------------------------------
# Day thirty versus day thirty-one of the return window
# ---------------------------------------------------------------------------

class TestReturnWindowBoundary:

    def test_a_return_raised_on_day_thirty_is_still_inside_the_window(self):
        """PRD §3.9: "A day count strictly greater than the window is refused with
        `ERR_RETURN_WINDOW_EXPIRED`; a count exactly equal to the window is still
        inside it and is accepted."
        PRD §3.9: "Otherwise consult the pinned
        `days_since_fulfilled_at_request`: a count of 15 days or fewer gives a rate
        of 0.10, and a count above 15 gives 0.20."

        Design: Difficulty/boundary_precision_check/return_window_day_thirty_accepted_day_thirty_one_expired
        """
        world = _shipped_order_with_two_returnable_lines()
        set_clock("2026-08-31T00:00:00Z")

        response = api_client.create_return_authorization(
            return_authorization_payload(
                world["account"]["id"], world["line"]["id"], 1, "NO_LONGER_NEEDED",
                world["branch"]["id"],
            ),
            make_servicer_headers(world["account"]["id"]),
        )
        ra = validate_success(response, 201)
        assert ra["days_since_fulfilled_at_request"] == 30, (
            f"Expected the pinned day count 30, got "
            f"{ra['days_since_fulfilled_at_request']}"
        )
        assert ra["ra_status"] == "REQUESTED"
        assert ra["gross_return_cents"] == 10399

        validate_success(
            api_client.decide_return_authorization(
                ra["id"], {"decision": "APPROVE", "waive_restocking_fee": False},
                CREDIT_MANAGER,
            ),
            200,
        )
        approved = read_return_authorization(ra["id"])
        assert approved["restocking_fee_pct"] == pytest.approx(0.20, abs=0.01), (
            f"day 30 is above 15, so the rate is 0.20, got "
            f"{approved['restocking_fee_pct']}"
        )
        assert approved["restocking_fee_cents"] == 2080, (
            f"Expected 10399 x 0.20 rounded half up to 2080, got "
            f"{approved['restocking_fee_cents']}"
        )
        assert approved["credit_amount_cents"] == 8319

    def test_a_return_raised_on_day_thirty_one_is_outside_the_window(self):
        """PRD §3.9: "The applicable window is 60 days when the `reason_code` is
        `CORE_RETURN` and 30 days for every other reason. A day count strictly
        greater than the window is refused with `ERR_RETURN_WINDOW_EXPIRED`; a
        count exactly equal to the window is still inside it and is accepted."
        PRD §3.9: "`days_since_fulfilled_at_request` is the whole days between the
        order's `fulfilled_at` and the logical clock at the moment the
        authorization is raised — the difference in epoch seconds divided by 86400
        and floored."

        Design: Difficulty/boundary_precision_check/return_window_day_thirty_accepted_day_thirty_one_expired
        """
        world = _shipped_order_with_two_returnable_lines()
        set_clock("2026-09-01T00:00:00Z")

        response = api_client.create_return_authorization(
            return_authorization_payload(
                world["account"]["id"], world["second_line"]["id"], 1,
                "NO_LONGER_NEEDED", world["branch"]["id"],
            ),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED)

        line = read_line(world["second_line"]["id"])
        assert line["line_status"] == "SHIPPED"
        assert line["returned_units"] == 0

        rows = list_return_authorizations(order_line_id=world["second_line"]["id"])
        assert rows == [], (
            f"the refused request must persist no authorization, got {len(rows)} row(s)"
        )
