"""
Requests that violate two documented guards at once.

The screening order is normative, so which of the two errors comes back is itself
the contract. One request breaks a safety rule and a capacity ceiling; another
breaks a state rule and a fiscal ceiling. In both cases the loser's error must not
appear, and nothing may be written.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CONTRACT_INVALID_STATE,
    ERR_HOIST_CAPACITY_EXCEEDED,
    ERR_HOIST_UNAVAILABLE,
    ERR_MINE_WITHDRAWAL_ORDER_ACTIVE,
    ERR_STALE_BID_CONTRACT_VERSION,
    ERR_TAKE_BAND_EXCEEDED,
)
from test_helpers.assertions import assert_tons
from test_helpers.constants import (
    ACTION_WITHDRAW,
    CONTRACT_AWARDED,
    HIGHWAY_DEICING,
    HOIST_AVAILABLE,
    JURISDICTION_MUNICIPAL,
    METHOD_SEVERITY_WEIGHTED,
    ROUTINE,
    WITHDRAWAL_ORDER,
)
from test_helpers.test_users import CONTRACT_ADMIN, MINE_PLANNER

CLOCK = "2026-08-10T00:00:00Z"

FORECAST_KWARGS = dict(
    season_code="2026-27",
    region_code="NORTHEAST",
    normal_season_tons=200000,
    severity_index=60,
    prior_season_1_actual_tons=240000,
    prior_season_2_actual_tons=180000,
    prior_season_3_actual_tons=150000,
    method=METHOD_SEVERITY_WEIGHTED,
    preseason_lock_date="2026-10-15T00:00:00Z",
)

CONTRACT_KWARGS = dict(
    customer_name="City of Buffalo",
    jurisdiction_level=JURISDICTION_MUNICIPAL,
    state_code="NY",
    product_line=HIGHWAY_DEICING,
    committed_tons=5000,
    guaranteed_price_per_ton=68.55,
    min_take_pct=80,
    max_take_pct=110,
    failure_to_supply_penalty_per_ton=22.00,
    price_guarantee_cap_pct=10,
)


def _withdrawn_mine(api):
    """
    A shaft that is mechanically fine — still `HOIST_AVAILABLE` — but sits under a
    withdrawal order, which zeroes its effective capacity outright.
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)
    panel = fx.create_panel(
        api, mine["id"], panel_code="P-1", pillar_recovery_allowed=True
    )
    fx.develop(api, panel["id"])
    fx.start_production(api, panel["id"])
    fx.compliance_action(
        api, mine["id"], ACTION_WITHDRAW, note="imminent danger order, ground control"
    )
    return {
        "mine": fx.refresh_mine(api, mine["id"]),
        "panel": fx.refresh_panel(api, panel["id"]),
    }


def test_withdrawal_order_outranks_the_capacity_ceiling_it_also_creates(api):
    """
    The withdrawal order zeroes capacity, so a 1000.0000 t/h run breaks the safety
    guard and the aggregate-capacity guard in the same breath; the earlier safety
    guard is the one the client hears about, and the two later codes must not be used.

    PRD §2.6: "The screening order below is therefore **normative**: the checks are
    evaluated in the sequence given, the first violated check is the one whose
    `error_id` and HTTP status the client receives, and **no side effect of any later
    stage is applied**."

    PRD §2.6: "**Withdrawal order** — `ERR_MINE_WITHDRAWAL_ORDER_ACTIVE` (409) when
    the mine's `compliance_state` is `WITHDRAWAL_ORDER`, regardless of hoist
    availability or remaining reserve."

    PRD §2.6: "**Aggregate hoist capacity** — `ERR_HOIST_CAPACITY_EXCEEDED` (409) on
    `POST /salt/production-runs` and `POST /salt/production-runs/{id}/reinstate`."

    Design: Difficulty/priority_pair_validation_conflict/withdrawal_order_safety_outranks_hoist_capacity_constraint_on_run_create
    """
    world = _withdrawn_mine(api)
    mine = world["mine"]
    assert mine["compliance_state"] == WITHDRAWAL_ORDER
    # The shaft itself never moved; only the compliance factor did.
    assert mine["hoist_state"] == HOIST_AVAILABLE
    assert_tons(
        mine["effective_hoist_tons_per_day"], 0.00, "effective_hoist_tons_per_day"
    )

    refused = api.create_run(
        f.run_payload(
            mine["id"],
            world["panel"]["id"],
            planned_tons=6000,
            hoist_window_start="2026-08-11T00:00:00Z",
            hoist_window_end="2026-08-11T06:00:00Z",
            expected_mine_version=mine["version"],
        ),
        MINE_PLANNER,
    )

    error = validate_error(refused, ERR_MINE_WITHDRAWAL_ORDER_ACTIVE, 409)
    assert error["error_id"] not in (
        ERR_HOIST_CAPACITY_EXCEEDED,
        ERR_HOIST_UNAVAILABLE,
    ), f"the safety guard must win, got {error['error_id']}"


def test_the_refused_run_leaves_no_row_and_no_version_movement(api):
    """
    No side effect of a later stage is applied: the rejected create writes no run and
    does not touch the mine, while the reserve figure on the panel shows only what the
    withdrawal action itself already did to it.

    PRD §3.1: "Beyond capacity, a compliance action reaches into the panels. On
    **every** compliance action, the recoverable reserve of every panel on the mine
    whose `status` is one of `PLANNED`, `DEVELOPED`, `PRODUCING` or `SUSPENDED` is
    recomputed from scratch, because one term of that reserve formula is only granted
    while the mine is compliant (§3.2)."

    PRD §3.1: "Moving to `CITED` therefore strips the pillar-recovery bonus from those
    panels; moving to `WITHDRAWAL_ORDER` strips it too; and `CLEAR` restores it
    wherever the panel's `pillar_recovery_allowed` is true."

    PRD §3.4: "A new run opens with `status` at `SCHEDULED`, `hoisted_tons` at 0,
    `held_reason` null, `open_batch_count` at 0, and `version` at 1, and its
    `planned_tons` is added into the mine's `scheduled_hoist_tons_open`."

    Design: Difficulty/priority_pair_validation_conflict/withdrawal_order_safety_outranks_hoist_capacity_constraint_on_run_create
    """
    world = _withdrawn_mine(api)
    mine = world["mine"]
    # The withdrawal already stripped the 32000.00 t pillar bonus from 617600.00.
    assert_tons(world["panel"]["recoverable_tons"], 585600.00, "recoverable_tons")

    refused = api.create_run(
        f.run_payload(
            mine["id"],
            world["panel"]["id"],
            planned_tons=6000,
            hoist_window_start="2026-08-11T00:00:00Z",
            hoist_window_end="2026-08-11T06:00:00Z",
            expected_mine_version=mine["version"],
        ),
        MINE_PLANNER,
    )
    validate_error(refused, ERR_MINE_WITHDRAWAL_ORDER_ACTIVE, 409)

    assert fx.runs_of_mine(api, mine["id"]) == []

    after = fx.refresh_mine(api, mine["id"])
    assert_tons(after["scheduled_hoist_tons_open"], 0.00, "scheduled_hoist_tons_open")
    assert after["version"] == mine["version"]
    assert_tons(
        fx.refresh_panel(api, world["panel"]["id"])["recoverable_tons"],
        585600.00,
        "recoverable_tons",
    )


def _awarded_contract_and_depot(api):
    """
    A contract that was awarded but never activated, plus a depot to order from. Its
    take band ceiling is 5500.00 t: 5000 t committed at a 110 percent maximum take.
    """
    fx.set_clock(api, CLOCK, CONTRACT_ADMIN)
    depot = fx.create_depot(api, name="Depot A", outbound_freight_rate_per_ton=4.00)
    world = fx.awarded_contract(api, FORECAST_KWARGS, CONTRACT_KWARGS)
    world["depot"] = depot
    return world


def test_contract_state_outranks_the_take_band_ceiling_on_order_create(api):
    """
    A 9000 t order against an `AWARDED` contract breaks the state guard and blows past
    the 5500.00 t take band at once; the state guard is screened first, so the fiscal
    error must not be the one returned — nor may the fresh optimistic-concurrency value
    be blamed.

    PRD §2.6: "**Contract state** — `ERR_CONTRACT_INVALID_STATE` (409) when the bid
    contract is not in the state the operation requires."

    PRD §2.6: "**Take band** — `ERR_TAKE_BAND_EXCEEDED` (409) on
    `POST /salt/delivery-orders`."

    PRD §3.9: "A new order is refused with `ERR_TAKE_BAND_EXCEEDED` when that consumed
    figure plus the new order's `requested_tons` would exceed `committed_tons`
    multiplied by `max_take_pct` divided by 100, the comparison again being made on the
    unrounded product."

    Design: Difficulty/priority_pair_validation_conflict/contract_state_outranks_take_band_fiscal_check_on_order_create
    """
    world = _awarded_contract_and_depot(api)
    contract = world["contract"]
    assert contract["status"] == CONTRACT_AWARDED

    refused = api.create_order(
        f.order_payload(
            contract["id"],
            world["depot"]["id"],
            expected_bid_contract_version=contract["version"],
            requested_tons=9000,
            required_by="2026-12-01T00:00:00Z",
            market_index_price_per_ton=70.00,
            storm_priority=ROUTINE,
        ),
        CONTRACT_ADMIN,
    )

    error = validate_error(refused, ERR_CONTRACT_INVALID_STATE, 409)
    assert error["error_id"] not in (
        ERR_TAKE_BAND_EXCEEDED,
        ERR_STALE_BID_CONTRACT_VERSION,
    ), f"the state guard must win, got {error['error_id']}"


def test_the_refused_order_writes_nothing_and_spares_the_parent_version(api):
    """
    The losing guard's side effects are not applied either: no order row exists for the
    contract afterwards, and the optimistic-concurrency parent the request named is not
    bumped by a rejection.

    PRD §2.6: "A request that would both fail authorization and exceed a capacity
    ceiling reports the authorization failure only."

    PRD §2.9: "When one request changes a fact, every number derived from that fact is
    brought up to date inside the same request, and every entity whose stored values
    changed has its `updated_at` refreshed and its `version` incremented by exactly 1."

    PRD §2.6: "the first violated check is the one whose `error_id` and HTTP status the
    client receives, and **no side effect of any later stage is applied**"

    Design: Difficulty/priority_pair_validation_conflict/contract_state_outranks_take_band_fiscal_check_on_order_create
    """
    world = _awarded_contract_and_depot(api)
    contract = world["contract"]

    refused = api.create_order(
        f.order_payload(
            contract["id"],
            world["depot"]["id"],
            expected_bid_contract_version=contract["version"],
            requested_tons=9000,
            required_by="2026-12-01T00:00:00Z",
            market_index_price_per_ton=70.00,
            storm_priority=ROUTINE,
        ),
        CONTRACT_ADMIN,
    )
    validate_error(refused, ERR_CONTRACT_INVALID_STATE, 409)

    rows = fx.list_rows(
        api.list_orders(
            CONTRACT_ADMIN, {"bid_contract_id": contract["id"], "limit": 100}
        )
    )
    assert rows == [], f"a rejected create must write no order, found {len(rows)}"

    after = fx.refresh_contract(api, contract["id"])
    assert after["version"] == contract["version"]
    assert after["status"] == CONTRACT_AWARDED
