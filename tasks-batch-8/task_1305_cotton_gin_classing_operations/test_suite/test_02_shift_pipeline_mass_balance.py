"""Shift pipeline: moisture gate at queue, season gate, shift state gates,
exact mass balance at close, and largest-remainder seed reconciliation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    close_shift,
    create_grower,
    create_module,
    create_seed_sale_payload,
    create_shift,
    get_module,
    get_shift,
    gin_module,
    queue_module,
    reconcile_shift,
    start_ginning,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


def _seed_yield_scenario(api):
    """Grower with two modules ginned in one shift; shift closed with scale
    totals 14880 lint / 25000 seed / 120 waste (nets 20000 + 20000)."""
    grower = create_grower("MB-100", "Delta Farms One")
    shift = create_shift("2026", "STAND-A")
    m1 = create_module(grower["id"], ticket_number="T-1", module_tag="MT-1",
                       gross_weight_lbs=22000, tare_weight_lbs=2000,
                       moisture_pct=9.0, foreign_matter_pct=3.0)
    m2 = create_module(grower["id"], ticket_number="T-2", module_tag="MT-2",
                       gross_weight_lbs=21000, tare_weight_lbs=1000,
                       moisture_pct=12.0, foreign_matter_pct=6.0)
    gin_module(m1["id"], shift["id"],
               [(f"B-{i:02d}", 500) for i in range(1, 15)] + [("B-15", 480)])
    gin_module(m2["id"], shift["id"],
               [(f"B-{i:02d}", 500) for i in range(16, 30)] + [("B-30", 400)])
    return grower, shift, m1, m2


class TestMoistureBoundary:
    def test_moisture_exactly_twelve_queues(self, api):
        """PRD: "its latest `moisture_pct` must be at most 12.0 percent — a
        reading of exactly 12.0 passes — or the queue fails with
        `ERR_MOISTURE_LIMIT_EXCEEDED` (HTTP 422)"
        PRD: "Queuing stamps `gin_shift_id` on the module, moves it to `QUEUED`,
        and increments its `version`."

        Design: Difficulty/boundary_precision_check/moisture_boundary_twelve_point_zero
        """
        grower = create_grower("MB-700", "Boundary Farm")
        shift = create_shift("2026", "STAND-J")
        mok = create_module(grower["id"], ticket_number="T-1", module_tag="MT-OK",
                            moisture_pct=12.0, foreign_matter_pct=4.0)
        queued = validate_success(api.queue_module(
            mok["id"], {"gin_shift_id": shift["id"]}, OPERATOR))
        assert queued["status"] == "QUEUED"
        assert queued["gin_shift_id"] == shift["id"]

    def test_moisture_twelve_point_zero_one_rejected(self, api):
        """PRD: "its latest `moisture_pct` must be at most 12.0 percent — a
        reading of exactly 12.0 passes — or the queue fails with
        `ERR_MOISTURE_LIMIT_EXCEEDED` (HTTP 422)"

        Design: Difficulty/boundary_precision_check/moisture_boundary_twelve_point_zero
        """
        grower = create_grower("MB-700", "Boundary Farm")
        shift = create_shift("2026", "STAND-J")
        mwet = create_module(grower["id"], ticket_number="T-2", module_tag="MT-WET",
                             moisture_pct=12.01, foreign_matter_pct=4.0)
        resp = api.queue_module(mwet["id"], {"gin_shift_id": shift["id"]}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_MOISTURE_LIMIT_EXCEEDED)
        module = get_module(mwet["id"])
        assert module["status"] == "RECEIVED"
        assert module.get("gin_shift_id") is None


class TestQueueGates:
    def test_queue_season_mismatch_rejected(self, api):
        """PRD: "the module's `season` must equal the shift's `season` (else
        `ERR_SEASON_MISMATCH`, HTTP 422)."
        PRD: "Modules may only ever queue into a shift of the same season"

        Design: Corner/validations/queue_season_mismatch_rejected
        """
        grower = create_grower("MB-C43", "Mismatch Farm")
        shift = create_shift("2025", "STAND-MM")
        module = create_module(grower["id"], season="2026", ticket_number="T-1",
                               module_tag="MT-MM")
        resp = api.queue_module(module["id"], {"gin_shift_id": shift["id"]}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_SEASON_MISMATCH)
        module = get_module(module["id"])
        assert module["status"] == "RECEIVED"
        assert module.get("gin_shift_id") is None

    def test_existence_precedes_state_for_unknown_module(self, api):
        """PRD: "Existence of every path resource id (validated left-to-right
        along the URL) and every body foreign-key reference is checked next,
        yielding the resource-specific not-found error"
        PRD: "A request failing an earlier tier never surfaces a later tier's
        error."

        Design: Corner/validations/existence_precedes_state_for_unknown_module
        """
        shift = create_shift("2026", "STAND-EX")
        resp = api.queue_module(NON_EXISTENT_UUID,
                                {"gin_shift_id": shift["id"]}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_MODULE_NOT_FOUND)


class TestShiftStateGates:
    def test_close_blocked_while_module_ginning(self, api):
        """PRD: "Closing also requires the shift to be `OPEN` (else
        `ERR_SHIFT_NOT_OPEN`) and refuses while any module of the shift is
        still in `GINNING` (else `ERR_MODULES_STILL_GINNING`, HTTP 409)."

        Design: Corner/state_machines/shift_close_blocked_while_module_ginning
        """
        grower = create_grower("MB-C14", "Close Farm")
        shift = create_shift("2026", "STAND-CB")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-CB")
        queue_module(module["id"], shift["id"])
        start_ginning(module["id"])
        resp = api.close_gin_shift(
            shift["id"], {"actual_lint_scale_lbs": 0, "actual_seed_scale_lbs": 0,
                          "waste_lbs": 0}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_MODULES_STILL_GINNING)
        assert get_shift(shift["id"])["status"] == "OPEN"

    def test_reconcile_requires_closed_and_sale_requires_reconciled(self, api):
        """PRD: "The shift must be `CLOSED` (else `ERR_SHIFT_NOT_CLOSED`,
        HTTP 409)."
        PRD: "Selling a shift that is not yet `RECONCILED` fails with
        `ERR_SHIFT_NOT_RECONCILED` (HTTP 409)"
        PRD: "the sum of `net_weight_lbs` over the shift's `GINNED` modules
        must equal lint plus seed plus waste"

        Design: Corner/state_machines/shift_state_gates_for_reconcile_and_sale
        """
        shift = create_shift("2026", "STAND-SG")
        e1 = api.reconcile_gin_shift(shift["id"], OPERATOR)
        validate_error(e1, ApiErrorId.ERR_SHIFT_NOT_CLOSED)

        closed = validate_success(api.close_gin_shift(
            shift["id"], {"actual_lint_scale_lbs": 0, "actual_seed_scale_lbs": 0,
                          "waste_lbs": 0}, OPERATOR))
        assert closed["status"] == "CLOSED", "empty shift balances: 0 == 0+0+0"

        from test_helpers import create_seed_sale_payload
        e2 = api.create_seed_sale(
            create_seed_sale_payload(shift["id"], buyer_name="Early Mill",
                                     price_cents_per_lb=20), ACCOUNTANT)
        validate_error(e2, ApiErrorId.ERR_SHIFT_NOT_RECONCILED)


    def test_closed_shift_rejects_queue_and_start(self, api):
        """PRD: "the target shift must be `OPEN` (else `ERR_SHIFT_NOT_OPEN`,
        HTTP 409)"
        PRD: "Starting ginning moves a `QUEUED` module to `GINNING` and requires
        the module's shift to still be `OPEN`; a module not in `QUEUED` yields
        `ERR_MODULE_NOT_GINNABLE` (HTTP 409), and a closed shift yields
        `ERR_SHIFT_NOT_OPEN`."

        Design: Corner/state_machines/shift_closed_rejects_queue_and_start
        """
        grower = create_grower("MB-C15", "Late Farm")
        shift = create_shift("2026", "STAND-LT")
        m1 = create_module(grower["id"], ticket_number="T-1", module_tag="MT-L1")
        m2 = create_module(grower["id"], ticket_number="T-2", module_tag="MT-L2")
        queue_module(m1["id"], shift["id"])
        close_shift(shift["id"], 0, 0, 0)

        e1 = api.start_ginning(m1["id"], OPERATOR)
        validate_error(e1, ApiErrorId.ERR_SHIFT_NOT_OPEN)
        e2 = api.queue_module(m2["id"], {"gin_shift_id": shift["id"]}, OPERATOR)
        validate_error(e2, ApiErrorId.ERR_SHIFT_NOT_OPEN)
        assert get_module(m1["id"])["status"] == "QUEUED"
        assert get_module(m2["id"])["status"] == "RECEIVED"


class TestMassBalanceAtClose:
    def test_close_mismatch_rejected(self, api):
        """PRD: "Close enforces mass conservation exactly, in integer pounds:
        the sum of `net_weight_lbs` over the shift's `GINNED` modules must
        equal lint plus seed plus waste, and `actual_lint_scale_lbs` must
        separately equal the sum of `actual_lint_lbs` over those same modules.
        Either mismatch fails with `ERR_MASS_BALANCE_VIOLATION` (HTTP 422)."

        Design: Corner/calculations/mass_balance_close_mismatch_rejected
        """
        grower = create_grower("MB-C31", "Balance Farm")
        shift = create_shift("2026", "STAND-MB")
        create_ginned = create_module(grower["id"], ticket_number="T-1",
                                      module_tag="MT-MB")
        gin_module(create_ginned["id"], shift["id"], [("B-MB1", 1000)])

        e1 = api.close_gin_shift(shift["id"], {"actual_lint_scale_lbs": 1000,
                                               "actual_seed_scale_lbs": 8000,
                                               "waste_lbs": 999}, OPERATOR)
        validate_error(e1, ApiErrorId.ERR_MASS_BALANCE_VIOLATION)

        e2 = api.close_gin_shift(shift["id"], {"actual_lint_scale_lbs": 1001,
                                               "actual_seed_scale_lbs": 8000,
                                               "waste_lbs": 999}, OPERATOR)
        validate_error(e2, ApiErrorId.ERR_MASS_BALANCE_VIOLATION)

        closed = validate_success(api.close_gin_shift(
            shift["id"], {"actual_lint_scale_lbs": 1000,
                          "actual_seed_scale_lbs": 8000, "waste_lbs": 1000},
            OPERATOR))
        assert closed["status"] == "CLOSED"


class TestReconciliationAllocation:
    def test_largest_remainder_order(self, api):
        """PRD: "Each module's raw share is the shift's `actual_seed_scale_lbs`
        multiplied by its estimated seed and divided by the total estimated seed
        across the shift's ginned modules; the share is floored to a whole
        pound, and the leftover pounds — the scale total minus the sum of
        floors — are distributed one pound each to the modules with the largest
        fractional remainders, ties broken by module `created_at` ascending."
        PRD: "the invariant holds exactly: the reconciled pounds sum to the
        shift's seed scale total."

        Design: Corner/calculations/shift_allocation_largest_remainder_order
        """
        ga = create_grower("MB-C32A", "Alloc A")
        gb = create_grower("MB-C32B", "Alloc B")
        gc = create_grower("MB-C32C", "Alloc C")
        shift = create_shift("2026", "STAND-AL")
        ma = create_module(ga["id"], ticket_number="T-1", module_tag="MT-AL-A",
                           gross_weight_lbs=15000)
        mb = create_module(gb["id"], ticket_number="T-1", module_tag="MT-AL-B",
                           gross_weight_lbs=21000)
        mc = create_module(gc["id"], ticket_number="T-1", module_tag="MT-AL-C",
                           gross_weight_lbs=9000)
        gin_module(ma["id"], shift["id"], [("B-AL-A1", 1500), ("B-AL-A2", 1500)])
        gin_module(mb["id"], shift["id"], [("B-AL-B1", 2000), ("B-AL-B2", 2000)])
        gin_module(mc["id"], shift["id"], [("B-AL-C1", 2000)])
        close_shift(shift["id"], 9000, 10000, 23000)

        reconcile_shift(shift["id"])

        # est seeds 7700 / 11000 / 4400 vs actual 10000:
        # raw 3333.33 / 4761.90 / 1904.76; floors 3333/4761/1904, remainder 2
        ma = get_module(ma["id"])
        mb = get_module(mb["id"])
        mc = get_module(mc["id"])
        assert ma["reconciled_seed_lbs"] == 3333
        assert mb["reconciled_seed_lbs"] == 4762
        assert mc["reconciled_seed_lbs"] == 1905
        assert (ma["reconciled_seed_lbs"] + mb["reconciled_seed_lbs"]
                + mc["reconciled_seed_lbs"]) == 10000


class TestSeedYieldDualVariant:
    def test_estimated_variant_before_reconcile_and_allocated_after(self, api):
        """PRD: "`est_seed_lbs` is simpler: net weight multiplied by 55
        percent, rounded half-up to whole pounds."
        PRD: "The result is written to each module's `reconciled_seed_lbs`
        (incrementing that module's `version`)"
        PRD: "Note the dual nature of module seed quantity: before
        reconciliation the estimate `est_seed_lbs` stands in; after, the
        scale-allocated `reconciled_seed_lbs` governs, and the two differ
        whenever the scale total differs from the summed estimates."

        Design: Difficulty/dual_variant_calc/seed_yield_estimated_vs_reconciled
        """
        _grower, shift, m1, m2 = _seed_yield_scenario(api)
        m1 = get_module(m1["id"])
        m2 = get_module(m2["id"])
        # estimated variant: net 20000 * 0.55 = 11000 each
        assert m1["est_seed_lbs"] == 11000
        assert m2["est_seed_lbs"] == 11000
        assert m1.get("reconciled_seed_lbs") is None
        assert m2.get("reconciled_seed_lbs") is None

        close_shift(shift["id"], 14880, 25000, 120)
        reconcile_shift(shift["id"])

        m1 = get_module(m1["id"])
        m2 = get_module(m2["id"])
        # total_est 22000 -> raw shares 12500 / 12500 (exact integers)
        assert m1["reconciled_seed_lbs"] == 12500
        assert m2["reconciled_seed_lbs"] == 12500
        assert m1["reconciled_seed_lbs"] != m1["est_seed_lbs"], (
            "reconciled variant diverges from the estimated variant for "
            "identical module data when scale total != summed estimates")

    def test_allocation_conserves_scale_total_and_shift_reconciled(self, api):
        """PRD: "the invariant holds exactly: the reconciled pounds sum to the
        shift's seed scale total."
        PRD: "The shift moves `CLOSED → RECONCILED` and its `version`
        increments."

        Design: Difficulty/dual_variant_calc/seed_yield_estimated_vs_reconciled
        """
        _grower, shift, m1, m2 = _seed_yield_scenario(api)
        close_shift(shift["id"], 14880, 25000, 120)
        reconciled = reconcile_shift(shift["id"])
        assert reconciled["status"] == "RECONCILED"
        m1 = get_module(m1["id"])
        m2 = get_module(m2["id"])
        total = m1["reconciled_seed_lbs"] + m2["reconciled_seed_lbs"]
        assert total == 25000 == reconciled["actual_seed_scale_lbs"]
