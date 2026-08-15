"""Marketing pools: uniqueness, state gates on close/reopen/sales, the pool-close
OCC guard, and validation-tier ordering between state and fiscal checks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_pool_fresh,
    close_pool_payload,
    complete_run,
    create_open_pool,
    create_pool_payload,
    get_pool_version,
    record_sale,
    record_sale_payload,
    schedule_run,
    setup_completed_run,
    setup_packable_lot,
    get_success_data,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
POOL_MGR = TEST_USERS["pool_manager_headers"]


class TestPoolCreationAndReopen:
    def test_pool_duplicate_scope_rejected(self, api):
        """PRD §3.5: "The triple of `variety`, `grade_class`, and `season` is
        unique; a duplicate pool is rejected with
        `ERR_UNIQUE_CONSTRAINT_VIOLATION`."

        Design: Corner/validations/c_pool_duplicate_scope_rejected
        """
        create_open_pool()
        resp = api.create_pool(create_pool_payload(), POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_UNIQUE_CONSTRAINT_VIOLATION)

    def test_reopen_open_pool_rejected(self, api):
        """PRD §3.6: "a `CLOSED` pool — and only a `CLOSED` pool, else
        `ERR_POOL_INVALID_STATE` — may be reopened by a `PoolManager`."

        Design: Corner/state_machines/c_reopen_open_pool_rejected
        """
        pool = create_open_pool()
        resp = api.reopen_pool(pool["id"], POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)


class TestEmptyPoolClose:
    def test_empty_pool_close_rejected(self, api):
        """PRD §3.6: "`total_packed_cartons` must be at least one (else
        `ERR_POOL_EMPTY`)."

        Design: Difficulty/boundary_precision_check/empty_pool_close_rejected
        """
        pool = create_open_pool()
        version = get_pool_version(pool["id"])
        resp = api.close_pool(pool["id"], close_pool_payload(version), POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_POOL_EMPTY)

    def test_empty_pool_close_leaves_pool_open_until_cartons_exist(self, api):
        """PRD §3.6: "`total_packed_cartons` must be at least one (else
        `ERR_POOL_EMPTY`)."
        PRD §3.5: "A new pool is `OPEN` with every total zeroed and
        `pool_price_per_carton_cents` null until the first close computes it."

        Design: Difficulty/boundary_precision_check/empty_pool_close_rejected
        """
        # Distinct season: the (variety, grade_class, season) triple is unique
        # (PRD 3.5), and the packable-lot chain below opens its own pool on the
        # default triple.
        pool = create_open_pool(season="2025-2026")
        resp = api.close_pool(
            pool["id"], close_pool_payload(get_pool_version(pool["id"])), POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_POOL_EMPTY)

        after = get_success_data(api.get_pool(pool["id"], ADMIN))
        assert after["status"] == "OPEN", "rejected close changes nothing"
        assert after["pool_price_per_carton_cents"] is None

        # Boundary: a second pool gains cartons via one completed run plus a
        # sale, and the same close then succeeds — zero cartons is the edge.
        ctx = setup_packable_lot(received_bin_count=2, received_weight_lbs=1000)
        run = schedule_run(ctx, input_weight_lbs=1000)
        complete_run(run["id"], cartons_produced=3, packed_weight_lbs=1000,
                     cull_weight_lbs=0, juice_weight_lbs=0)
        record_sale(ctx["pool"]["id"], cartons_sold=3, gross_revenue_cents=10000)
        closed = close_pool_fresh(ctx["pool"]["id"])
        assert closed["status"] == "CLOSED"
        assert closed["total_packed_cartons"] == 3
        assert closed["pool_price_per_carton_cents"] is not None


class TestPoolCloseGuards:
    def test_pool_close_with_scheduled_run_rejected(self, api):
        """PRD §2.9: "Within this tier, the no-open-runs check is evaluated before
        the non-empty check: a close that violates both reports
        `ERR_POOL_HAS_OPEN_RUNS`."
        PRD §3.6: "no `SCHEDULED` run may still reference the pool (else
        `ERR_POOL_HAS_OPEN_RUNS`, evaluated before the emptiness check)"

        Design: Corner/validations/c_pool_close_with_scheduled_run_rejected
        """
        ctx = setup_packable_lot()
        schedule_run(ctx, input_weight_lbs=1000)  # stays SCHEDULED
        # The pool also has zero cartons, so the asserted error proves the
        # within-tier sub-order.
        resp = api.close_pool(
            ctx["pool"]["id"],
            close_pool_payload(get_pool_version(ctx["pool"]["id"])), POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_POOL_HAS_OPEN_RUNS)

    def test_occ_stale_pool_close_rejected(self, api):
        """PRD §2.7: "Closing a pool (`POST /pools/{poolId}/close`) requires
        `expected_pool_version`. Closing commits the pool-average price computed
        from the totals the client last observed; if the pool's `version` has
        advanced since that read (a sale was recorded, a run completed or was
        voided), the close is based on stale totals and is rejected with
        `ERR_STALE_VERSION` (HTTP 412). The pool remains open, and a request
        carrying the current version may legitimately close it."

        Design: Corner/cross_cutting_layers/c_occ_stale_pool_close_rejected
        """
        pool = create_open_pool()
        stale_version = pool["version"]
        record_sale(pool["id"], cartons_sold=5, gross_revenue_cents=10000)

        resp = api.close_pool(pool["id"], close_pool_payload(stale_version), POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # A request carrying the current version passes the OCC tier; with zero
        # packed cartons the business-constraint tier then reports the pool as
        # empty, proving the stale rejection was the version check.
        resp2 = api.close_pool(
            pool["id"], close_pool_payload(get_pool_version(pool["id"])), POOL_MGR)
        validate_error(resp2, ApiErrorId.ERR_POOL_EMPTY)


class TestSaleValidation:
    def test_sale_invalid_amount_on_open_pool(self, api):
        """PRD §3.5: "Each sale names `cartons_sold` and `gross_revenue_cents`,
        both strictly positive, and `deduction_cents` — freight and commission —
        which may be zero but never negative; violations are rejected with
        `ERR_SALE_AMOUNT_INVALID`."

        Design: Corner/validations/c_sale_invalid_amount_on_open_pool
        """
        pool = create_open_pool()
        resp = api.record_pool_sale(
            pool["id"],
            record_sale_payload(cartons_sold=5, gross_revenue_cents=1000,
                                deduction_cents=-1),
            POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_SALE_AMOUNT_INVALID)


class TestSaleStateBeatsFiscal:
    def _closed_pool(self, api):
        """Pool with 3 packed cartons, one 10000-cent sale, then CLOSED."""
        ctx = setup_completed_run(received_bin_count=2, received_weight_lbs=1000,
                                  input_weight_lbs=1000, cartons_produced=3,
                                  packed_weight_lbs=1000, cull_weight_lbs=0,
                                  juice_weight_lbs=0)
        record_sale(ctx["pool"]["id"], cartons_sold=3, gross_revenue_cents=10000)
        close_pool_fresh(ctx["pool"]["id"])
        return ctx

    def test_sale_on_closed_pool_state_beats_fiscal(self, api):
        """PRD §2.9: "When several checks would fail on a single call, the first
        applicable tier below determines the response."
        PRD §3.5: "Sales against the pool are recorded as they occur, while the
        pool is `OPEN` or `REOPENED` (else `ERR_POOL_INVALID_STATE`)."

        The sale below also violates the fiscal tier (negative gross), but the
        state tier is checked first.

        Design: Difficulty/priority_pair_validation_conflict/sale_on_closed_pool_state_beats_fiscal
        """
        ctx = self._closed_pool(api)
        resp = api.record_pool_sale(
            ctx["pool"]["id"],
            record_sale_payload(cartons_sold=5, gross_revenue_cents=-100,
                                deduction_cents=0),
            POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)  # 409, not 422

    def test_sale_on_closed_pool_leaves_totals_unchanged(self, api):
        """PRD §3.5: "Recording a sale adds the gross to `total_sales_cents`,
        adds the deduction to `total_sale_deductions_cents`, recomputes the
        estimated price, and increments the pool's `version` by one"
        PRD §3.5: "Sales against the pool are recorded as they occur, while the
        pool is `OPEN` or `REOPENED` (else `ERR_POOL_INVALID_STATE`)."

        A fiscally invalid sale (zero cartons) on a CLOSED pool is rejected at
        the state tier and mutates nothing.

        Design: Difficulty/priority_pair_validation_conflict/sale_on_closed_pool_state_beats_fiscal
        """
        ctx = self._closed_pool(api)
        before = get_success_data(api.get_pool(ctx["pool"]["id"], ADMIN))
        assert before["status"] == "CLOSED"
        assert before["total_sales_cents"] == 10000

        resp = api.record_pool_sale(
            ctx["pool"]["id"],
            record_sale_payload(cartons_sold=0, gross_revenue_cents=1000,
                                deduction_cents=0),
            POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)

        after = get_success_data(api.get_pool(ctx["pool"]["id"], ADMIN))
        assert after["total_sales_cents"] == 10000, "rejected sale adds nothing"
        assert after["version"] == before["version"], "no mutation, no version bump"
