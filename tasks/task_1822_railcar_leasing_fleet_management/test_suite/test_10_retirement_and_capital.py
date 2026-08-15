"""Retirement lifecycle (SoD, compensation, execution) and capital-pool
waterfall with OCC-guarded commitments."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    appraise_retirement,
    approve_retirement,
    assert_pool_available_invariant,
    create_active_lease,
    create_commitment,
    create_lease_assignment_payload,
    create_lessee,
    create_pool,
    create_railcar,
    create_tariff_pair,
    get_pool,
    get_railcar,
    get_success_data,
    propose_retirement,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLANNER = TEST_USERS["fleet_planner_headers"]


class TestRetirementCancelCompensation:
    def test_retirement_cancel_compensates_railcar_status(self, api):
        """PRD §3.14: "A case may be cancelled from `PROPOSED`, `APPRAISED`,
        or `APPROVED`; cancelling an `APPROVED` case releases the car from
        `RETIREMENT_PENDING` back to `AVAILABLE` as compensation."
        PRD §3.14: "`impairment_loss_cents` is the amount by which book value
        exceeds salvage value, floored at zero; `reinvestment_credit_cents`
        equals the salvage value."

        Design: Corner/state_machines/retirement_cancel_compensates_railcar_status
        """
        car = create_railcar(car_mark="GATX1204", car_type="BOX",
                             built_year=1974)
        case = propose_retirement(car["id"], reason="OBSOLESCENCE")
        appraised = appraise_retirement(case["id"], salvage_value_cents=900000,
                                        book_value_cents=2000000)
        assert appraised["impairment_loss_cents"] == 1100000
        approve_retirement(case["id"])
        mid = get_railcar(car["id"])
        assert mid["status"] == "RETIREMENT_PENDING"

        cancelled = validate_success(api.cancel_retirement(case["id"], PLANNER))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["impairment_loss_cents"] == 1100000, (
            "max(0, 2000000 - 900000) was computed at appraise"
        )
        after = get_railcar(car["id"])
        assert after["status"] == "AVAILABLE", (
            "Cancellation compensates the approval exactly"
        )


class TestRetiredTerminalLockdown:
    def test_retired_railcar_rejects_new_assignment(self, api):
        """PRD §3.2: "`RETIRED` is terminal."
        PRD §2.7: "Creating an assignment requires the lease to be `ACTIVE`
        (`ERR_LEASE_NOT_ACTIVE`), the lessee to be `ACTIVE`
        (`ERR_LESSEE_NOT_ACTIVE`), and the railcar to be `AVAILABLE`
        (`ERR_RAILCAR_NOT_AVAILABLE`)."
        PRD §3.14: "it moves the car `RETIREMENT_PENDING → RETIRED`, stamps
        `retired_at`, and credits the pool: the pool's `replenishment_cents`
        increases by the case's `reinvestment_credit_cents`, and
        `available_cents` is recomputed per the waterfall below."

        Design: Corner/state_machines/retired_railcar_terminal_lockdown
        """
        car = create_railcar(car_mark="GATX1203", car_type="BOX",
                             built_year=1970)
        pool = create_pool(fiscal_year=2026, opening_balance_cents=5000000)
        case = propose_retirement(car["id"], reason="AGE_LIMIT")
        appraise_retirement(case["id"], salvage_value_cents=1500000,
                            book_value_cents=8000000)
        approve_retirement(case["id"])
        get_success_data(api.execute_retirement(case["id"], PLANNER))

        retired = get_railcar(car["id"])
        assert retired["status"] == "RETIRED"
        assert retired["retired_at"] is not None
        pool_after = get_pool(pool["id"])
        assert pool_after["replenishment_cents"] == 1500000

        create_tariff_pair("BOX", 9000, 55)
        lessee = create_lessee(company_name="L")
        lease = create_active_lease(lessee["id"])
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=lease["id"],
                railcar_id=car["id"],
                planned_commodity="LUMBER",
                scheduled_start="2026-09-01",
                scheduled_end="2026-09-30",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_RAILCAR_NOT_AVAILABLE, 409)
        still = get_railcar(car["id"])
        assert still["status"] == "RETIRED"


class TestRetirementExecutionGate:
    def test_execute_without_pool_returns_pool_not_found(self, api):
        """PRD §3.14: "Execution (`APPROVED → EXECUTED`, a `FleetPlanner`
        action) requires a capital pool to exist for the fiscal year of the
        current logical date (`ERR_POOL_NOT_FOUND`, 404)".

        Design: Corner/errors/retirement_execute_without_pool_returns_pool_not_found
        """
        car = create_railcar(car_mark="GATX1601", car_type="BOX",
                             built_year=1971)
        case = propose_retirement(car["id"], reason="AGE_LIMIT")
        appraise_retirement(case["id"], salvage_value_cents=1500000,
                            book_value_cents=8000000)
        approve_retirement(case["id"])
        resp = api.execute_retirement(case["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_FOUND, 404)
        after_case = get_success_data(api.get_retirement_case(case["id"], PLANNER))
        assert after_case["status"] == "APPROVED"
        after_car = get_railcar(car["id"])
        assert after_car["status"] == "RETIREMENT_PENDING"


class TestPoolCommitCancelInvariant:
    def test_commit_reduces_available(self, api):
        """PRD §3.14: "Creation increments the pool's `version` by 1, adds
        the cost to `committed_cents`, and recomputes `available_cents`; the
        commitment is `COMMITTED` with `delivered_car_mark` null."
        PRD §3.14: "the pool's available funds follow a waterfall:
        `available_cents` is the opening balance plus replenishments minus
        committed funds minus delivered spend".

        Design: Difficulty/compensating_invariant/pool_commit_cancel_restores_available
        """
        pool = create_pool(fiscal_year=2026, opening_balance_cents=100000000)
        commitment = create_commitment(pool["id"], 30000000, pool["version"])
        assert commitment["status"] == "COMMITTED"
        assert commitment["delivered_car_mark"] is None
        after = get_pool(pool["id"])
        assert after["committed_cents"] == 30000000
        assert after["available_cents"] == 70000000
        assert_pool_available_invariant(after)

    def test_cancel_restores_available_exactly(self, api):
        """PRD §3.14: "Cancelling a `COMMITTED` commitment moves it to
        `CANCELLED`, subtracts its cost from `committed_cents`, and
        recomputes `available_cents` as exact compensation — committing an
        amount and later cancelling it restores the available funds exactly."

        Design: Difficulty/compensating_invariant/pool_commit_cancel_restores_available
        """
        pool = create_pool(fiscal_year=2026, opening_balance_cents=100000000)
        commitment = create_commitment(pool["id"], 30000000, pool["version"])
        cancelled = validate_success(
            api.cancel_commitment(pool["id"], commitment["id"], PLANNER)
        )
        assert cancelled["status"] == "CANCELLED"
        after = get_pool(pool["id"])
        assert after["committed_cents"] == 0
        assert after["available_cents"] == 100000000, (
            "available returns exactly to the opening balance"
        )
        assert_pool_available_invariant(after)


class TestPoolCommitOcc:
    def test_pool_commit_stale_version_rejected(self, api):
        """PRD §2.11: "Creating a purchase commitment against a capital pool
        requires `expected_pool_version` carrying the client's last observed
        `version` of the pool; the affordability check must run against the
        pool version the client actually observed, and a mismatch is rejected
        with `ERR_STALE_VERSION` (412)."

        Design: Corner/cross_cutting_layers/pool_commit_stale_version_rejected
        """
        pool = create_pool(fiscal_year=2026, opening_balance_cents=100000000)
        observed = pool["version"]
        first = validate_success(
            api.create_commitment(
                pool["id"],
                {"car_type": "BOX", "unit_cost_cents": 10000000,
                 "expected_pool_version": observed},
                PLANNER,
            ),
            201,
        )
        assert first["status"] == "COMMITTED"

        stale = api.create_commitment(
            pool["id"],
            {"car_type": "GONDOLA", "unit_cost_cents": 10000000,
             "expected_pool_version": observed},
            PLANNER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        after = get_pool(pool["id"])
        assert after["committed_cents"] == 10000000, (
            "Only the first commit applied"
        )


class TestPoolFiscalGate:
    def test_commitment_over_available_rejected(self, api):
        """PRD §3.14: "The affordability check requires `unit_cost_cents` to
        be at most the pool's `available_cents` at the observed pool version;
        exceeding it fails with `ERR_CAPITAL_POOL_INSUFFICIENT` (422), and a
        stale version fails with `ERR_STALE_VERSION` (412)."

        Design: Corner/validations/pool_commitment_over_available_rejected
        """
        pool = create_pool(fiscal_year=2026, opening_balance_cents=100000)
        resp = api.create_commitment(
            pool["id"],
            {"car_type": "BOX", "unit_cost_cents": 150000,
             "expected_pool_version": pool["version"]},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_CAPITAL_POOL_INSUFFICIENT, 422)
        after = get_pool(pool["id"])
        assert after["available_cents"] == 100000

    def test_duplicate_pool_year_rejected(self, api):
        """PRD §3.14: "A `SystemAdmin` opens a reinvestment pool for a unique
        `fiscal_year` (duplicates fail with `ERR_DUPLICATE_POOL_YEAR`, 409)
        with a non-negative `opening_balance_cents`".

        Design: Corner/validations/duplicate_pool_year_rejected
        """
        create_pool(fiscal_year=2026, opening_balance_cents=100000)
        resp = api.create_capital_pool(
            {"fiscal_year": 2026, "opening_balance_cents": 200000}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POOL_YEAR, 409)


class TestCommitmentDelivery:
    def test_commitment_deliver_creates_replacement_railcar(self, api):
        """PRD §3.14: "Delivery (`COMMITTED → DELIVERED`) supplies the new
        car's `car_mark` and `built_year`, moves the cost from
        `committed_cents` to `delivered_spend_cents`, recomputes
        `available_cents`, and cascade-creates the replacement railcar —
        registered with the supplied `car_mark`, the commitment's `car_type`,
        the supplied `built_year`, status `AVAILABLE` — recording its mark on
        the commitment as `delivered_car_mark`."

        Design: Corner/cross_cutting_layers/commitment_deliver_creates_replacement_railcar
        """
        pool = create_pool(fiscal_year=2026, opening_balance_cents=100000000)
        commitment = create_commitment(pool["id"], 25000000, pool["version"])
        delivered = validate_success(
            api.deliver_commitment(pool["id"], commitment["id"],
                                   "GATX1801", 2026, PLANNER)
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivered_car_mark"] == "GATX1801"

        after = get_pool(pool["id"])
        assert after["committed_cents"] == 0
        assert after["delivered_spend_cents"] == 25000000
        assert after["available_cents"] == 75000000
        assert_pool_available_invariant(after)

        cars, meta = validate_paginated(api.list_railcars(PLANNER))
        assert meta["total_count"] == 1
        new_car = cars[0]
        assert new_car["car_mark"] == "GATX1801"
        assert new_car["status"] == "AVAILABLE"
        assert new_car["car_type"] == "COVERED_HOPPER"
        assert new_car["built_year"] == 2026
