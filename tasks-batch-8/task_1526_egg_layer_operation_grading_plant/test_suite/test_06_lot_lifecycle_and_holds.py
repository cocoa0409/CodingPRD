"""Egg-lot lifecycle and hold dimensions, ship boundary, ops-run expiry."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_flock,
    grading_submit_payload,
    run_daily_ops,
    set_clock,
    setup_active_contract,
    setup_allocated_lots,
    setup_confirmed_lot,
    setup_shipped_lots,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    CONTRACT_MANAGER,
    QA_MANAGER,
    get_contract,
    get_lot,
)


class TestParallelDimensions:
    def test_egg_lot_hold_blocks_release_until_cleared(self, api):
        """PRD §3.5: "The second, `hold_status`, toggles between `CLEAR` and
        `HELD` entirely independently — a hold transition never changes the
        lifecycle, and a lifecycle transition never changes the hold."
        PRD §3.5: "The lot's `hold_status` must be `CLEAR`, else
        `ERR_LOT_QUALITY_HELD` (HTTP 409)"

        Design: Difficulty/non_linear_state_machine/egg_lot_parallel_lifecycle_and_hold_dimensions
        """
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]

        held = validate_success(api.hold_lot(lot_id, QA_MANAGER))
        assert held["hold_status"] == "HELD"
        assert held["lifecycle_status"] == "FRESH", (
            "the hold dimension must not move the lifecycle dimension"
        )

        resp = api.release_lot(lot_id, QA_MANAGER)
        validate_error(resp, ApiErrorId.ERR_LOT_QUALITY_HELD)
        assert get_lot(lot_id)["lifecycle_status"] == "FRESH"

        cleared = validate_success(api.clear_hold_lot(lot_id, QA_MANAGER))
        assert cleared["hold_status"] == "CLEAR"
        released = validate_success(api.release_lot(lot_id, QA_MANAGER))
        assert released["lifecycle_status"] == "RELEASED"

    def test_egg_lot_hold_blocks_allocate_until_cleared(self, api):
        """PRD §3.5: "Five gates apply. The lot's `hold_status` must be
        `CLEAR`, else `ERR_LOT_QUALITY_HELD` (HTTP 409)."
        PRD §3.5: "Allocating sets the lot's `contract_id`, adds its
        `dozen_count` into the contract's `allocated_dozen`, and increments
        both the lot's and the contract's `version` by 1."

        Design: Difficulty/non_linear_state_machine/egg_lot_parallel_lifecycle_and_hold_dimensions
        """
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        contract = setup_active_contract(ctx["farm"]["id"])
        validate_success(api.release_lot(lot_id, QA_MANAGER))

        validate_success(api.hold_lot(lot_id, QA_MANAGER))
        held = get_lot(lot_id)
        assert held["lifecycle_status"] == "RELEASED" and held["hold_status"] == "HELD"

        resp = api.allocate_lot(lot_id, {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_LOT_QUALITY_HELD)

        validate_success(api.clear_hold_lot(lot_id, QA_MANAGER))
        allocated = validate_success(
            api.allocate_lot(lot_id, {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        )
        assert allocated["lifecycle_status"] == "ALLOCATED"
        assert get_contract(contract["id"])["allocated_dozen"] == 20


class TestShipShelfLifeBoundary:
    def _setup_two_shippable_lots(self, api):
        """480-egg run -> JUMBO lot (20 dozen) + LARGE lot (20 dozen), both
        RELEASED and ALLOCATED; pack 2026-08-01, sell-by 2026-09-15."""
        ctx = setup_allocated_lots(
            production_days=[
                {"lay_date": "2026-07-31", "eggs_collected": 480, "rejected_eggs": 0}
            ],
            eggs_to_grade=480,
            submit_counts=grading_submit_payload(large_count=240, jumbo_count=240),
        )
        lots = {lot["size_class"]: lot for lot in ctx["lots"]}
        for lot in ctx["lots"]:
            assert lot["sell_by_date"][:10] == "2026-09-15"
        return ctx, lots["JUMBO"], lots["LARGE"]

    def test_ship_on_exactly_sell_by_date_succeeds(self, api):
        """PRD §3.5: "the clock date must be on or before the lot's
        `sell_by_date` — equality ships on the last day — else
        `ERR_SHELF_LIFE_EXCEEDED` (HTTP 422). Shipping stamps `ship_date` to
        the clock date"

        Design: Difficulty/boundary_precision_check/ship_on_exactly_sell_by_date
        """
        ctx, lot_jumbo, _lot_large = self._setup_two_shippable_lots(api)
        set_clock("2026-09-15T00:00:00Z")
        shipped = validate_success(api.ship_lot(lot_jumbo["id"], CONTRACT_MANAGER))
        assert shipped["lifecycle_status"] == "SHIPPED"
        assert shipped["ship_date"][:10] == "2026-09-15", (
            f"ship_date must stamp the clock date, got {shipped['ship_date']!r}"
        )

    def test_ship_one_day_past_sell_by_rejected(self, api):
        """PRD §3.5: "the clock date must be on or before the lot's
        `sell_by_date` — equality ships on the last day — else
        `ERR_SHELF_LIFE_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/ship_on_exactly_sell_by_date
        """
        ctx, _lot_jumbo, lot_large = self._setup_two_shippable_lots(api)
        set_clock("2026-09-16T00:00:00Z")  # one day past sell-by 2026-09-15
        resp = api.ship_lot(lot_large["id"], CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_EXCEEDED)
        assert get_lot(lot_large["id"])["lifecycle_status"] == "ALLOCATED"


class TestShipPriorityPair:
    def _setup_held_allocated_lot(self, api):
        ctx = setup_allocated_lots(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        validate_success(api.hold_lot(lot_id, QA_MANAGER))
        return ctx, lot_id

    def test_ship_held_expired_lot_safety_beats_temporal(self, api):
        """PRD §2.8: "Tier 9 is health and claim gates — the lot hold gate
        (`ERR_LOT_QUALITY_HELD`, HTTP 409), the flock quarantine gate
        (`ERR_UNRESOLVED_POSITIVE`, HTTP 409), claim compatibility
        (`ERR_CLAIM_MISMATCH`, HTTP 409), and the one-open-recall-per-farm
        rule (`ERR_RECALL_ACTIVE`, HTTP 409). Tier 10 is temporal rules —
        shelf life on shipping (`ERR_SHELF_LIFE_EXCEEDED`, HTTP 422)"
        PRD §2.8: "checks are evaluated in twelve fixed priority tiers, and
        the lowest tier number wins."

        Design: Difficulty/priority_pair_validation_conflict/ship_held_expired_lot_safety_beats_temporal
        """
        ctx, lot_id = self._setup_held_allocated_lot(api)
        set_clock("2026-09-16T00:00:00Z")  # past sell-by 2026-09-15 as well

        resp = api.ship_lot(lot_id, CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_LOT_QUALITY_HELD)
        lot = get_lot(lot_id)
        assert lot["lifecycle_status"] == "ALLOCATED", "no ship side effects"
        assert lot["hold_status"] == "HELD"

    def test_ship_held_lot_rejection_leaves_contract_counters_unchanged(self, api):
        """PRD §3.5: "Shipping stamps `ship_date` to the clock date, moves the
        lot's `dozen_count` from the contract's `allocated_dozen` into its
        `shipped_dozen` (which sums the dozens of lots `SHIPPED` or `CLOSED`
        on the contract), and increments both versions by 1." (A rejected ship
        performs none of these moves.)
        PRD §2.8: "Tier 9 is health and claim gates — the lot hold gate
        (`ERR_LOT_QUALITY_HELD`, HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/ship_held_expired_lot_safety_beats_temporal
        """
        ctx, lot_id = self._setup_held_allocated_lot(api)
        contract_before = get_contract(ctx["contract"]["id"])
        assert contract_before["allocated_dozen"] == 20

        set_clock("2026-09-16T00:00:00Z")
        resp = api.ship_lot(lot_id, CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_LOT_QUALITY_HELD)

        contract_after = get_contract(ctx["contract"]["id"])
        assert contract_after["allocated_dozen"] == 20
        assert contract_after["shipped_dozen"] == 0
        assert get_lot(lot_id)["ship_date"] is None


class TestLotTerminalStates:
    def test_ship_shipped_lot_returns_invalid_state(self, api):
        """PRD §3.5: "Shipping completes the commercial leg: a
        `ContractManager` ships an `ALLOCATED` lot, moving it to `SHIPPED`."
        PRD §3.5: "The final step to `CLOSED` is not an action; it arrives by
        cascade when a settlement covering the lot is finalized (§3.6)."
        PRD §2.8: "Tier 6 is the target entity's own state machine — the
        requested transition must be permitted from its current state, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/ship_shipped_lot_returns_invalid_state
        """
        ctx = setup_shipped_lots(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        resp = api.ship_lot(lot_id, CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lot(lot_id)["lifecycle_status"] == "SHIPPED"
        assert get_contract(ctx["contract"]["id"])["shipped_dozen"] == 20

    def test_release_expired_lot_terminal_lockdown(self, api):
        """PRD §3.5: "Any lot still in `FRESH`, `RELEASED`, or `ALLOCATED`
        whose `sell_by_date` is strictly before the clock date moves to
        `EXPIRED`, processed in `pack_date` ascending, `created_at` ascending
        order."
        PRD §2.8: "Tier 6 is the target entity's own state machine — the
        requested transition must be permitted from its current state, else
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.4: "The run answers with a summary object containing
        `lots_expired`, `contracts_expired`, `flocks_advanced`,
        `houses_advanced`, and `tests_auto_scheduled`."

        Design: Corner/state_machines/release_expired_lot_terminal_lockdown
        """
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        set_clock("2026-09-16T00:00:00Z")  # past sell-by 2026-09-15
        summary = run_daily_ops()
        assert summary["lots_expired"] == 1
        assert get_lot(lot_id)["lifecycle_status"] == "EXPIRED"

        resp = api.release_lot(lot_id, QA_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lot(lot_id)["lifecycle_status"] == "EXPIRED"

    def test_ops_run_expires_allocated_lot_and_releases_contract(self, api):
        """PRD §3.5: "Any lot still in `FRESH`, `RELEASED`, or `ALLOCATED`
        whose `sell_by_date` is strictly before the clock date moves to
        `EXPIRED`, processed in `pack_date` ascending, `created_at` ascending
        order. Expiring a `FRESH` or `RELEASED` lot simply increments its
        `version` by 1; expiring an `ALLOCATED` lot additionally releases the
        contract — `allocated_dozen` falls by the lot's `dozen_count`,
        `contract_id` is cleared — and increments both versions by 1."

        Design: Corner/state_machines/ops_run_expires_allocated_lot_and_releases_contract
        """
        ctx = setup_allocated_lots(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        assert ctx["contract"]["allocated_dozen"] == 20

        set_clock("2026-09-16T00:00:00Z")
        run_daily_ops()

        lot = get_lot(lot_id)
        assert lot["lifecycle_status"] == "EXPIRED"
        assert lot["contract_id"] is None, "expiry must clear the allocation link"
        assert get_contract(ctx["contract"]["id"])["allocated_dozen"] == 0
