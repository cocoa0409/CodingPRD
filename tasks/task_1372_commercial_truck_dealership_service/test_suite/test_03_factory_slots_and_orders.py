"""Build-slot pools and factory orders: tiered pricing, holds, expiry/re-hold,
cancellation cascades, build-cycle sweeps (PRD §3.2, §2.11)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    assert_factory_build_slot, assert_factory_order,
    create_account, create_slot_pool, create_order, commit_order, get_slot,
    set_clock, run_sweep, create_shipped_order, create_repair_order,
    add_labor_line, create_bay, create_bay_booking,
)

MGR = TEST_USERS["sales_manager_headers"]
CONSULTANT = TEST_USERS["sales_consultant_headers"]
ADVISOR = TEST_USERS["service_advisor_headers"]

STD_SPEC = dict(chassis_model="M2_106", engine_option="DD13", axle_config="A4X2")


# ---------------------------------------------------------------- Queue A ---

class TestTieredPricingWithVocationMultiplier:
    def _setup(self):
        acct = create_account("FLEET", credit_limit_cents=100000000, name="TierCo")
        slot_sev = create_slot_pool(build_month="2026-09", vocation_group="SEVERE", capacity=10)
        slot_std = create_slot_pool(build_month="2026-09", vocation_group="STANDARD", capacity=10)
        target = create_order(
            slot_sev["id"], account_id=acct["id"],
            chassis_model="CASCADIA_126", engine_option="DD15", axle_config="A6X4",
            upfit_lines=[{"component_code": "DUMP_BODY", "price_cents": 1800000},
                         {"component_code": "CRANE_PTO", "price_cents": 950000}])
        priors = []
        for _ in range(3):
            o = create_order(slot_std["id"], account_id=acct["id"], **STD_SPEC)
            priors.append(commit_order(o["id"]))
        return acct, slot_sev, target, priors

    def test_provisional_total_uses_creation_snapshot(self, api):
        """PRD §3.2: "at most two such prior orders means no rebate, three
        through five priors earns a rebate of two percent of the subtotal, and
        six or more priors earns four percent; the rebate is rounded half-up to
        integer cents."
        PRD §3.2: "The upfit total is the sum of the upfit line prices,
        multiplied by 1.08 when the order's vocation group is `SEVERE` and by
        1.00 otherwise, rounded half-up to integer cents. The final price is the
        subtotal minus the rebate, plus the upfit total, plus a destination fee
        of 285,000 cents."

        Design: Difficulty/combinatorial_formula/factory_order_price_tiered_rebate_with_vocation_multiplier
        """
        _, _, target, _ = self._setup()
        # At creation the customer held zero committed orders -> rebate tier 0%.
        # 14500000 + 1200000 + 850000 - 0 + round_half_up(2750000 * 1.08) + 285000
        assert target["provisional_total_cents"] == 19805000

    def test_committed_total_rebates_after_three_priors(self, api):
        """PRD §3.2: "This price is computed twice in the order's life with a
        customer-count snapshot taken at each moment: once at creation, stored
        as `provisional_total_cents` (the provisional variant), and again at
        commit, stored as `committed_total_cents` and locked. Because the
        snapshot is re-taken, the committed total may legitimately differ from
        the provisional one."

        Design: Difficulty/combinatorial_formula/factory_order_price_tiered_rebate_with_vocation_multiplier
        """
        _, _, target, _ = self._setup()
        resp = api.commit_factory_order(target["id"], CONSULTANT)
        data = validate_success(resp, 200)
        # At commit the customer holds 3 committed orders -> 2% rebate.
        # 16550000 - round_half_up(16550000 * 0.02) + 2970000 + 285000
        assert data["committed_total_cents"] == 19474000
        assert data["status"] == "COMMITTED"


class TestSlotPoolExhaustion:
    def test_last_slot_hold_succeeds_and_locks_pool(self, api):
        """PRD §3.2: "A pool begins `OPEN`, becomes `LOCKED` automatically the
        moment a hold, re-hold, or commit drives availability to zero".

        Design: Difficulty/boundary_precision_check/slot_pool_exhaustion_at_exact_zero_available
        """
        slot = create_slot_pool(build_month="2026-08", capacity=1)
        order = create_order(slot["id"], **STD_SPEC)
        assert order["status"] == "SLOT_HELD"
        pool = get_slot(slot["id"])
        assert pool["slots_available"] == 0
        assert pool["held_count"] == 1
        assert pool["status"] == "LOCKED"

    def test_hold_at_zero_available_rejected(self, api):
        """PRD §3.2: "it must have at least one slot available
        (`ERR_SLOT_POOL_EXHAUSTED`)".

        Design: Difficulty/boundary_precision_check/slot_pool_exhaustion_at_exact_zero_available
        """
        slot = create_slot_pool(build_month="2026-08", capacity=1)
        create_order(slot["id"], **STD_SPEC)
        resp = api.create_factory_order(
            {"factory_build_slot_id": slot["id"], "chassis_model": "SD_114",
             "engine_option": "DD15", "axle_config": "A6X4"}, CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_SLOT_POOL_EXHAUSTED)
        pool = get_slot(slot["id"])
        assert pool["held_count"] == 1 and pool["committed_count"] == 0
        assert pool["slots_available"] == 0


class TestExpireThenReholdCycle:
    def _setup_expired(self):
        slot_a = create_slot_pool(build_month="2026-08", capacity=1)
        order = create_order(slot_a["id"], **STD_SPEC)
        set_clock("2026-08-16T00:00:00Z")
        sweep = run_sweep()
        slot_b = create_slot_pool(build_month="2026-09", capacity=1)
        return slot_a, slot_b, order, sweep

    def test_sweep_expires_lapsed_hold_and_releases_slot(self, api):
        """PRD §3.2: "a `SLOT_HELD` order whose `hold_expires_at` has been
        reached goes `EXPIRED` with the slot released".

        Design: Difficulty/non_linear_state_machine/factory_order_expire_then_rehold_cycle
        """
        slot_a, _, order, sweep = self._setup_expired()
        assert sweep["orders_expired"] == 1
        expired = get_success_data(api.get_factory_order(order["id"], MGR))
        assert expired["status"] == "EXPIRED"
        pool_a = get_slot(slot_a["id"])
        assert pool_a["held_count"] == 0
        assert pool_a["slots_available"] == 1

    def test_rehold_moves_pools_and_restamps_hold_window(self, api):
        """PRD §3.2: "a `SalesConsultant` may re-hold it against a new pool,
        which updates the order's `factory_build_slot_id`, refreshes
        `vocation_group` from the new pool, restamps the fourteen-day hold
        window, and increments the new pool's `held_count`, locking it if
        full."

        Design: Difficulty/non_linear_state_machine/factory_order_expire_then_rehold_cycle
        """
        slot_a, slot_b, order, _ = self._setup_expired()
        resp = api.rehold_factory_order(
            order["id"], {"factory_build_slot_id": slot_b["id"]}, CONSULTANT)
        data = validate_success(resp, 200)
        assert data["status"] == "SLOT_HELD"
        assert data["factory_build_slot_id"] == slot_b["id"]
        # Clock 2026-08-16 + 14 days.
        assert data["hold_expires_at"] == "2026-08-30T00:00:00Z"
        pool_b = get_slot(slot_b["id"])
        assert pool_b["held_count"] == 1
        assert pool_b["slots_available"] == 0
        assert pool_b["status"] == "LOCKED"
        assert get_slot(slot_a["id"])["held_count"] == 0


class TestCommittedCancelCascade:
    def _setup_locked_pool(self):
        acct = create_account("FLEET", credit_limit_cents=10000000000, name="CancelCo")
        slot = create_slot_pool(build_month="2026-08", capacity=2)
        o1 = commit_order(create_order(slot["id"], account_id=acct["id"], **STD_SPEC)["id"])
        o2 = commit_order(create_order(slot["id"], account_id=acct["id"], **STD_SPEC)["id"])
        return acct, slot, o1, o2

    def test_cancel_releases_committed_count_and_reopens_pool(self, api):
        """PRD §3.2: "Cancelling is permitted from either `SLOT_HELD` or
        `COMMITTED` and releases the slot (decrementing whichever counter the
        order sat in) with the pool-posture re-evaluation described above."
        PRD §3.2: "reopens to `OPEN` when a cancellation or expiry release
        makes availability positive again while the build month is still open".

        Design: Difficulty/transitive_cascade/committed_order_cancel_releases_slot_and_reopens_pool
        """
        _, slot, _, o2 = self._setup_locked_pool()
        pool = get_slot(slot["id"])
        assert pool["status"] == "LOCKED" and pool["committed_count"] == 2
        assert pool["slots_available"] == 0

        data = validate_success(api.cancel_factory_order(o2["id"], CONSULTANT), 200)
        assert data["status"] == "CANCELLED"
        pool = get_slot(slot["id"])
        assert pool["committed_count"] == 1
        assert pool["slots_available"] == 1
        assert pool["status"] == "OPEN"

    def test_committed_cancel_charges_two_percent_fee(self, api):
        """PRD §3.2: "Cancelling a `COMMITTED` order that names a customer
        account additionally charges a cancellation fee of two percent of
        `committed_total_cents`, rounded half-up, added to that account's
        `open_ar_cents`".

        Design: Difficulty/transitive_cascade/committed_order_cancel_releases_slot_and_reopens_pool
        """
        acct, slot, _, o2 = self._setup_locked_pool()
        api.cancel_factory_order(o2["id"], CONSULTANT)
        account = get_success_data(api.get_customer_account(acct["id"], MGR))
        # round_half_up(10085000 * 0.02)
        assert account["open_ar_cents"] == 201700


class TestSlotHoldCancelConservation:
    def test_hold_then_cancel_restores_availability(self, api):
        """PRD §3.2: "Pools track `held_count` (orders currently holding a
        slot) and `committed_count` (orders committed or beyond), and expose
        `slots_available` — capacity minus both counts, never negative."

        Design: Difficulty/compensating_invariant/slot_hold_then_cancel_conserves_availability
        """
        slot = create_slot_pool(build_month="2026-08", capacity=3)
        assert get_slot(slot["id"])["slots_available"] == 3
        order = create_order(slot["id"], **STD_SPEC)
        assert get_slot(slot["id"])["slots_available"] == 2
        api.cancel_factory_order(order["id"], CONSULTANT)
        pool = get_slot(slot["id"])
        assert pool["slots_available"] == 3
        assert pool["held_count"] == 0
        assert pool["committed_count"] == 0

    def test_compensation_leaves_pool_open_and_order_cancelled(self, api):
        """PRD §3.2: "Cancelling is permitted from either `SLOT_HELD` or
        `COMMITTED` and releases the slot (decrementing whichever counter the
        order sat in) with the pool-posture re-evaluation described above."

        Design: Difficulty/compensating_invariant/slot_hold_then_cancel_conserves_availability
        """
        slot = create_slot_pool(build_month="2026-08", capacity=3)
        order = create_order(slot["id"], **STD_SPEC)
        data = validate_success(api.cancel_factory_order(order["id"], CONSULTANT), 200)
        assert data["status"] == "CANCELLED"
        pool = get_slot(slot["id"])
        assert pool["status"] == "OPEN"
        assert_factory_build_slot(pool)


# ---------------------------------------------------------------- Queue B ---

def test_commit_from_expired_rejected_invalid_from(api):
    """PRD §3.2: "Committing an order — permitted to a `SalesConsultant` while
    the order is `SLOT_HELD` and the clock is still before `hold_expires_at`;
    both violations surface `ERR_ORDER_STATE`".

    Design: Corner/state_machines/commit_from_expired_rejected_invalid_from
    """
    slot = create_slot_pool(build_month="2026-08", capacity=1)
    order = create_order(slot["id"], **STD_SPEC)
    set_clock("2026-08-16T00:00:00Z")
    sweep = run_sweep()
    assert sweep["orders_expired"] == 1
    validate_error(api.commit_factory_order(order["id"], CONSULTANT),
                   ApiErrorId.ERR_ORDER_STATE)
    assert get_success_data(api.get_factory_order(order["id"], MGR))["status"] == "EXPIRED"


def test_initial_states_on_creation(api):
    """PRD §3.2: "A created order lands in `SLOT_HELD`, copies its
    `vocation_group` from the pool".
    PRD §3.6: "The order is born with `auth_status` `DRAFT` and `work_status`
    `OPEN`, and lists can filter by `customer_account_id`, `unit_id`,
    `auth_status`, and `work_status`."

    Design: Corner/state_machines/initial_states_on_creation
    """
    slot = create_slot_pool(build_month="2026-10", capacity=3)
    acct = create_account(name="InitCo")
    order = create_order(slot["id"], account_id=acct["id"], chassis_model="SD_114",
                         engine_option="CUMMINS_X15", axle_config="A6X4")
    assert order["status"] == "SLOT_HELD"
    ro = create_repair_order(acct["id"])
    assert ro["auth_status"] == "DRAFT"
    assert ro["work_status"] == "OPEN"


def test_sweep_promotes_build_cycle_and_closes_pool(api):
    """PRD §3.2: "a `COMMITTED` order goes `IN_PRODUCTION` once the clock
    reaches the first day of its build month, and `IN_PRODUCTION` goes
    `SHIPPED` once the clock reaches fourteen days after the first of the
    build month, with at most one promotion per order per sweep."
    PRD §3.2: "once the sweep sees the logical clock past the end of the build
    month the pool goes `CLOSED`".

    Design: Corner/state_machines/sweep_promotes_build_cycle_and_closes_pool
    """
    slot = create_slot_pool(build_month="2026-09", capacity=2)
    order = commit_order(create_order(slot["id"], **STD_SPEC)["id"])

    set_clock("2026-09-01T00:00:00Z")
    sweep = run_sweep()
    assert sweep["orders_started"] == 1
    order = get_success_data(api.get_factory_order(order["id"], MGR))
    assert order["status"] == "IN_PRODUCTION"

    set_clock("2026-09-15T00:00:00Z")
    sweep = run_sweep()
    assert sweep["orders_shipped"] == 1
    order = get_success_data(api.get_factory_order(order["id"], MGR))
    assert order["status"] == "SHIPPED"

    set_clock("2026-10-01T00:00:00Z")
    sweep = run_sweep()
    assert sweep["slot_pools_closed"] == 1
    assert get_slot(slot["id"])["status"] == "CLOSED"


def test_mutations_visible_in_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.2: "The final price is the subtotal minus the rebate, plus the upfit
    total, plus a destination fee of 285,000 cents."

    Design: Corner/consistency_model/mutations_visible_in_same_response
    """
    slot = create_slot_pool(build_month="2026-10", capacity=3)
    order = create_order(slot["id"], chassis_model="SD_114", engine_option="DD15",
                         axle_config="A6X4")
    resp = api.commit_factory_order(order["id"], CONSULTANT)
    data = validate_success(resp, 200)
    assert data["status"] == "COMMITTED"
    # 12300000 + 1200000 + 850000 - 0 + 0 + 285000
    assert data["committed_total_cents"] == 14635000
    reread = get_success_data(api.get_factory_order(order["id"], MGR))
    assert reread["status"] == "COMMITTED"
    assert reread["committed_total_cents"] == 14635000
