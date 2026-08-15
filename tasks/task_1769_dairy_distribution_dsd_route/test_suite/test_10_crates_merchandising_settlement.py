"""Crate ledger conservation, merchandising sessions, and driver weekly
settlement tiers (PRD §2.8, §3.6, §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_return,
    cancel_order,
    confirm_order,
    create_distributor,
    create_driver,
    create_return,
    make_distributor_owner_headers,
    make_driver_headers,
    make_store_receiver_headers,
    precool_and_depart,
    record_crate_transaction,
    set_clock,
    setup_delivered_order,
    setup_planned_order,
    setup_route_with_store,
    validate_error,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]


class TestCrateDropPickupConservation:
    def test_drop_then_equal_pickup_restores_balance(self, api):
        """PRD §2.8: "a pickup larger than the current balance is rejected
        with `ERR_INSUFFICIENT_CRATE_BALANCE` (HTTP 409), while a pickup
        exactly equal to the balance is allowed and leaves the balance at
        zero"
        PRD §2.8: "The ledger is compensating — for any interval, the ending
        balance equals the starting balance plus drops minus pickups plus
        adjustments, so a drop of n followed later by a pickup of n leaves
        the balance unchanged."
        PRD §2.8: "The store's `deposit_liability_cents` is always the
        current `crate_balance` multiplied by its `crate_deposit_cents`, and
        is recomputed whenever the balance moves."

        Design: Difficulty/compensating_invariant/crate_drop_pickup_conservation
        """
        refs = setup_delivered_order(
            prefix="R", quantity_units=7, store_overrides={"crate_deposit_cents": 400},
        )
        s1 = refs["store"]["id"]
        store = validate_success(api.get_store(s1, TM), 200)
        assert store["crate_balance"] == 7
        assert store["deposit_liability_cents"] == 2800

        record_crate_transaction(s1, "PICKUP", 7, refs["driver"]["id"],
                                 "RouteDriver", note="backhaul empties")
        store = validate_success(api.get_store(s1, TM), 200)
        assert store["crate_balance"] == 0
        assert store["deposit_liability_cents"] == 0

        err = api.create_crate_transaction(
            s1, {"kind": "PICKUP", "crate_count": 1},
            make_driver_headers(refs["driver"]["id"]),
        )
        validate_error(err, ApiErrorId.ERR_INSUFFICIENT_CRATE_BALANCE)

    def test_negative_adjustment_floor_and_drop_rejected(self, api):
        """PRD §2.8: "likewise a negative adjustment may not drive the balance
        below zero and fails with the same error."
        PRD §3.6: "Submitting kind `DROP` is rejected as system-only with
        `ERR_INVALID_REQUEST` — drops exist only as delivery side effects."
        PRD §3.6: "an `ADJUSTMENT`, recordable by a `DistributorOwner` only,
        carries a signed non-zero `crate_count` where a negative value reduces
        the balance"

        Design: Difficulty/compensating_invariant/crate_drop_pickup_conservation
        """
        refs = setup_delivered_order(
            prefix="R2", quantity_units=7, store_overrides={"crate_deposit_cents": 400},
        )
        s1 = refs["store"]["id"]
        d_id = refs["distributor"]["id"]

        record_crate_transaction(s1, "ADJUSTMENT", -3, d_id, "DistributorOwner")
        store = validate_success(api.get_store(s1, TM), 200)
        assert store["crate_balance"] == 4
        assert store["deposit_liability_cents"] == 1600

        err1 = api.create_crate_transaction(
            s1, {"kind": "ADJUSTMENT", "crate_count": -5},
            make_distributor_owner_headers(d_id),
        )
        validate_error(err1, ApiErrorId.ERR_INSUFFICIENT_CRATE_BALANCE)

        err2 = api.create_crate_transaction(
            s1, {"kind": "DROP", "crate_count": 1},
            make_distributor_owner_headers(d_id),
        )
        validate_error(err2, ApiErrorId.ERR_INVALID_REQUEST)


def test_session_open_uniqueness_and_close_state(api):
    """PRD §3.7: "a driver may hold at most one `OPEN` session at a time — a
    second check-in while one is open fails with `ERR_SESSION_CONFLICT`."
    PRD §3.7: "Closing a session requires it to be `OPEN` (else
    `ERR_SESSION_NOT_OPEN`)"
    PRD §3.7: "Closing stamps `check_out_at` from the clock, computes
    `minutes` as the elapsed seconds between check-in and check-out divided by
    60 and rounded up — the result must be greater than zero — then derives
    `billable_minutes` as the greater of zero and `minutes` minus the store's
    `free_merchandising_minutes`, and `labor_charge_cents` as
    `billable_minutes` times the store's `merchandising_rate_cents_per_min`."

    Design: Corner/state_machines/session_open_uniqueness_and_close_state
    """
    refs = setup_planned_order(
        prefix="AL", quantity_units=1,
        store_overrides={"merchandising_rate_cents_per_min": 100,
                         "free_merchandising_minutes": 15},
    )
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    cancel_order(refs["order"]["id"], refs["distributor"]["id"])
    precool_and_depart(t1, dr1, "2026-08-10")

    driver_h = make_driver_headers(dr1)
    set_clock("2026-08-10T09:00:00Z")
    ms1 = validate_success(
        api.check_in_merchandising_session(t1, {"store_id": refs["store"]["id"]}, driver_h),
        201,
    )
    err1 = api.check_in_merchandising_session(
        t1, {"store_id": refs["store"]["id"]}, driver_h
    )
    validate_error(err1, ApiErrorId.ERR_SESSION_CONFLICT)

    set_clock("2026-08-10T09:30:00Z")
    closed = validate_success(api.close_merchandising_session(ms1["id"], driver_h), 200)
    assert closed["status"] == "CLOSED"
    assert closed["minutes"] == 30
    assert closed["billable_minutes"] == 15, "30 - free 15"
    assert closed["labor_charge_cents"] == 1500, "15 x 100"

    err2 = api.close_merchandising_session(ms1["id"], driver_h)
    validate_error(err2, ApiErrorId.ERR_SESSION_NOT_OPEN)


def test_weekly_settlement_tier_boundary_500000(api):
    """PRD §3.7: "The commission tier is keyed on net sales — never on any
    post-commission figure, which would make the commission depend on itself:
    below 500,000 cents the rate is 22 percent; from 500,000 up to and
    including 1,200,000 cents the rate is 24 percent — 500,000 exactly takes
    24 percent; above 1,200,000 cents the rate is 26 percent."
    PRD §3.7: "`driver_labor_cents` is the labor minutes times 50 cents per
    minute"

    Design: Corner/calculations/weekly_settlement_tier_boundary_500000
    """
    refs = setup_delivered_order(prefix="BB", quantity_units=2000, case_capacity=3000)
    dr1 = refs["driver"]["id"]
    driver_h = make_driver_headers(dr1)
    session = validate_success(
        api.check_in_merchandising_session(
            refs["trip"]["id"], {"store_id": refs["store"]["id"]}, driver_h
        ),
        201,
    )
    set_clock("2026-08-10T10:30:00Z")
    validate_success(api.close_merchandising_session(session["id"], driver_h), 200)

    data = validate_success(
        api.get_weekly_settlement(
            dr1, make_distributor_owner_headers(refs["distributor"]["id"]),
            params={"week_start": "2026-08-10"},
        ),
        200,
    )
    assert data["gross_sales_cents"] == 500000
    assert data["credits_cents"] == 0
    assert data["net_sales_cents"] == 500000
    assert data["commission_rate"] == pytest.approx(0.24), (
        "500000 is inside the [500000, 1200000] tier; lower bound inclusive"
    )
    assert data["commission_cents"] == 120000
    assert data["labor_minutes"] == 90
    assert data["driver_labor_cents"] == 4500
    assert data["settlement_cents"] == 124500


def test_weekly_settlement_credits_reduce_net(api):
    """PRD §3.7: "Credits, `credits_cents`, are the sum of
    `credit_amount_cents` over returns in `APPROVED` or `CREDITED` status
    whose order's service date is in the window and whose order's trip driver
    is this driver — evaluated as of read time, so a return approved later
    changes historical settlements."
    PRD §3.7: "below 500,000 cents the rate is 22 percent"

    Design: Corner/calculations/weekly_settlement_credits_reduce_net
    """
    refs = setup_delivered_order(prefix="BC", quantity_units=2000, case_capacity=3000)
    ret = create_return(
        refs["order"]["id"], refs["store"]["id"], refs["trip"]["id"],
        refs["product"]["id"], 7, "DAMAGED", "2026-09-01", refs["driver"]["id"],
    )
    approve_return(ret["id"], refs["distributor"]["id"])

    data = validate_success(
        api.get_weekly_settlement(
            refs["driver"]["id"],
            make_distributor_owner_headers(refs["distributor"]["id"]),
            params={"week_start": "2026-08-10"},
        ),
        200,
    )
    assert data["gross_sales_cents"] == 500000
    assert data["credits_cents"] == 875, "round(7 x 250 x 0.5)"
    assert data["net_sales_cents"] == 499125
    assert data["commission_rate"] == pytest.approx(0.22), (
        "499125 < 500000 falls to the base tier"
    )
    assert data["commission_cents"] == 109808, "round_half_up(499125 x 0.22)"
    assert data["labor_minutes"] == 0
    assert data["settlement_cents"] == 109808


def test_driver_settlement_self_vs_other(api):
    """PRD §3.7: "it is available to the owning `DistributorOwner` and to the
    driver for their own record."
    PRD §2.1: "A failed entity-backed ownership check is rejected with
    `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/driver_settlement_self_vs_other
    """
    d1 = create_distributor(name="Dairy Dist FB", license_number="LIC-FB-1")
    d2 = create_distributor(name="Dairy Dist FC", license_number="LIC-FC-1")
    dr1 = create_driver(d1["id"], name="Hank Driver")
    dr2 = create_driver(d1["id"], name="Ivy Driver", cdl_class="B")

    own = api.get_weekly_settlement(
        dr1["id"], make_driver_headers(dr1["id"]), params={"week_start": "2026-08-10"}
    )
    data = validate_success(own, 200)
    assert data["settlement_cents"] == 0, "an empty week settles to 0"

    err1 = api.get_weekly_settlement(
        dr1["id"], make_driver_headers(dr2["id"]), params={"week_start": "2026-08-10"}
    )
    validate_error(err1, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    err2 = api.get_weekly_settlement(
        dr1["id"], make_distributor_owner_headers(d2["id"]),
        params={"week_start": "2026-08-10"},
    )
    validate_error(err2, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
