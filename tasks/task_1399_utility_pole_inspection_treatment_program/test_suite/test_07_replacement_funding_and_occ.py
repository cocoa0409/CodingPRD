"""Replacement queue: funding boundary, OCC on the budget version, deferral
escalation, reconcile requeue, and the fund/defund compensating invariant
(PRD §2.7, §2.10, §3.8, §3.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_budget_invariant,
    assert_replacement_work_order,
    create_budget,
    create_crew,
    create_open_cycle,
    create_pole,
    create_replacement_order,
    fund_order,
    fund_order_payload,
    get_budget,
    get_order,
    get_pole,
    make_contractor_headers,
    reconcile_cycle,
    validate_error,
    validate_success,
)


class TestFundBoundary:
    def _setup_exact_fit(self, api, program_manager_headers):
        budget = create_budget(fiscal_year=2026, total_cents=200000)
        pole = create_pole(pole_number="P-FB")
        o1 = create_replacement_order(pole["id"], estimated_cost_cents=200000)
        o2 = create_replacement_order(pole["id"], estimated_cost_cents=100000)
        return budget, o1, o2

    def test_fund_exact_available_equality_succeeds(self, api, program_manager_headers):
        """PRD §3.8: "the budget's `available_cents` must be at least the order's
        `escalated_cost_cents` — the boundary is inclusive, so an order whose escalated
        cost exactly equals the available balance funds successfully, while a larger
        cost is rejected with `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/fund_exact_available_equality
        """
        budget, o1, _ = self._setup_exact_fit(api, program_manager_headers)
        resp = api.fund_replacement_work_order(
            o1["id"], fund_order_payload(budget["id"], budget["version"]),
            program_manager_headers,
        )
        funded = validate_success(resp, expected_status=200)
        assert funded["status"] == "FUNDED"
        assert funded["budget_id"] == budget["id"]
        after = get_budget(budget["id"])
        assert after["available_cents"] == 0
        assert after["committed_cents"] == 200000
        assert_budget_invariant(after)

    def test_fund_over_available_rejected(self, api, program_manager_headers):
        """PRD §3.8: "a larger cost is rejected with `ERR_BUDGET_EXCEEDED`".

        Design: Difficulty/boundary_precision_check/fund_exact_available_equality
        """
        budget, o1, o2 = self._setup_exact_fit(api, program_manager_headers)
        fund_order(o1["id"], budget["id"], budget["version"])
        fresh = get_budget(budget["id"])
        resp = api.fund_replacement_work_order(
            o2["id"], fund_order_payload(budget["id"], fresh["version"]),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        assert get_order(o2["id"])["status"] == "QUEUED"


class TestFundDefundInvariant:
    def _setup_funded(self, api, program_manager_headers):
        budget = create_budget(fiscal_year=2026, total_cents=500000)
        pole = create_pole(pole_number="P-IV")
        order = create_replacement_order(pole["id"], estimated_cost_cents=200000)
        fund_order(order["id"], budget["id"], budget["version"])
        return budget, order

    def test_fund_moves_available_to_committed(self, api, program_manager_headers):
        """PRD §3.8: "A successful fund moves the order to `FUNDED`, adds the escalated
        cost to the budget's `committed_cents`, sets the order's `budget_id` to the
        funding budget, stamps `funded_at` from the logical clock, and increments the
        `version` of both the budget and the order."
        PRD §3.1: "The invariant that the total always equals available plus committed
        plus spent holds at all times."

        Design: Difficulty/compensating_invariant/fund_defund_restores_available_cents
        """
        budget, order = self._setup_funded(api, program_manager_headers)
        after = get_budget(budget["id"])
        assert after["available_cents"] == 300000
        assert after["committed_cents"] == 200000
        assert after["spent_cents"] == 0
        assert_budget_invariant(after)
        assert after["version"] == budget["version"] + 1
        funded_order = get_order(order["id"])
        assert funded_order["status"] == "FUNDED"
        assert funded_order["funded_at"] is not None

    def test_defund_restores_prefund_available(self, api, program_manager_headers):
        """PRD §2.10: "Defunding a replacement order releases its committed funds and
        returns the budget's available balance to exactly its pre-fund value."
        PRD §3.8: "a `FUNDED` order returns to `QUEUED`, the budget's `committed_cents`
        is reduced by the escalated cost, the order's `budget_id` is cleared to null,
        and the budget's `version` increments — restoring `available_cents` to exactly
        its pre-fund value."

        Design: Difficulty/compensating_invariant/fund_defund_restores_available_cents
        """
        budget, order = self._setup_funded(api, program_manager_headers)
        resp = api.defund_replacement_work_order(order["id"], program_manager_headers)
        defunded = validate_success(resp, expected_status=200)
        assert defunded["status"] == "QUEUED"
        assert defunded["budget_id"] is None
        after = get_budget(budget["id"])
        assert after["available_cents"] == 500000, (
            "defund must restore available_cents to exactly its pre-fund value"
        )
        assert after["committed_cents"] == 0
        assert after["spent_cents"] == 0
        assert_budget_invariant(after)


class TestFundValidationOrdering:
    def _setup_deferred_order_zero_budget(self, api, program_manager_headers):
        budget = create_budget(fiscal_year=2026, total_cents=0)
        pole = create_pole(pole_number="P-PC1")
        order = create_replacement_order(pole["id"], estimated_cost_cents=100000)
        validate_success(
            api.defer_replacement_work_order(order["id"], program_manager_headers),
            expected_status=200,
        )
        return budget, order

    def test_fund_deferred_order_state_error_wins(self, api, program_manager_headers):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, and the
        stages are evaluated in a strict order; a failure at an earlier stage is
        reported and masks every later check." — stage 5 (State validity) precedes
        stage 11 (Fiscal capacity).
        PRD §3.8: "an order not currently `QUEUED` is rejected with
        `ERR_ORDER_NOT_QUEUED`".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_fund
        """
        budget, order = self._setup_deferred_order_zero_budget(api,
                                                               program_manager_headers)
        resp = api.fund_replacement_work_order(
            order["id"], fund_order_payload(budget["id"], budget["version"]),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_QUEUED)

    def test_fund_deferred_order_leaves_no_side_effects(
            self, api, program_manager_headers):
        """PRD §2.8: "a failure at an earlier stage is reported and masks every later
        check", so the rejected fund mutates neither the order nor the budget.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_fund
        """
        budget, order = self._setup_deferred_order_zero_budget(api,
                                                               program_manager_headers)
        resp = api.fund_replacement_work_order(
            order["id"], fund_order_payload(budget["id"], budget["version"]),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_QUEUED)
        after = get_order(order["id"])
        assert after["status"] == "DEFERRED"
        assert after["budget_id"] is None
        budget_after = get_budget(budget["id"])
        assert budget_after["committed_cents"] == 0
        assert_budget_invariant(budget_after)


class TestDeferAndCompleteGuards:
    def test_defer_on_funded_order_rejected(self, api, program_manager_headers):
        """PRD §3.8: "Deferring a `QUEUED` order moves it to `DEFERRED`, increments
        `deferral_count` by one, and recomputes `escalated_cost_cents` at the new
        deferral power" — deferral is defined only from `QUEUED`, and per §2.8 stage 5
        the not-queued rejection is `ERR_ORDER_NOT_QUEUED`.

        Design: Corner/state_machines/defer_on_funded_order_rejected
        """
        budget = create_budget(fiscal_year=2026, total_cents=500000)
        pole = create_pole(pole_number="P-DFR", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        order = create_replacement_order(pole["id"], estimated_cost_cents=200000)
        fund_order(order["id"], budget["id"], budget["version"])
        resp = api.defer_replacement_work_order(order["id"], program_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_QUEUED)
        after = get_order(order["id"])
        assert after["status"] == "FUNDED"
        assert after["deferral_count"] == 0

    def test_complete_on_queued_order_rejected(self, api, contractor_headers):
        """PRD §3.8: "Completing a `FUNDED` order requires a payload `actual_cost_cents`
        greater than zero and settles the money" — completion is defined only from
        `FUNDED`, so a `QUEUED` order fails the §2.8 stage-5 state-validity check with
        `ERR_INVALID_STATE`.

        Design: Corner/state_machines/complete_on_queued_order_rejected
        """
        crew = create_crew(crew_code="CR-CQ")
        pole = create_pole(pole_number="P-CQ", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        order = create_replacement_order(pole["id"], estimated_cost_cents=200000)
        resp = api.complete_replacement_work_order(
            order["id"], {"actual_cost_cents": 200000},
            make_contractor_headers(crew["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_pole(pole["id"])["status"] == "IN_SERVICE"
        assert get_order(order["id"])["status"] == "QUEUED"


class TestEscalatedCost:
    def test_escalated_cost_compounds_per_deferral(self, api, program_manager_headers):
        """PRD §3.8: "`escalated_cost_cents` — the amount funding actually commits —
        is the `estimated_cost_cents` multiplied by 1.08 raised to the power of
        `deferral_count`, rounded half-up to whole cents; it is computed at creation
        and recomputed on every defer."

        Design: Corner/calculations/escalated_cost_compounds_per_deferral
        """
        pole = create_pole(pole_number="P-ESC1", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        order = create_replacement_order(pole["id"], estimated_cost_cents=200000)
        assert order["escalated_cost_cents"] == 200000, "1.08^0 at creation"

        resp = api.defer_replacement_work_order(order["id"], program_manager_headers)
        deferred = validate_success(resp, expected_status=200)
        assert deferred["status"] == "DEFERRED"
        assert deferred["deferral_count"] == 1
        assert deferred["escalated_cost_cents"] == 216000, "200000 * 1.08^1"

        # Defer is defined only from QUEUED: a second defer from DEFERRED is rejected.
        resp = api.defer_replacement_work_order(order["id"], program_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_QUEUED)


class TestBudgetOcc:
    def test_occ_stale_budget_version_rejected(self, api, program_manager_headers):
        """PRD §2.7: "Funding a replacement order requires the request to carry
        `expected_budget_version`, a non-optional field holding the `version` of the
        target `ProgramBudget` as the client last observed it. If the budget's current
        `version` does not match — because a successful fund, defund, completion, or
        reconcile waterfall has advanced it since the client's read — the request is
        rejected with `ERR_STALE_BUDGET_VERSION` (HTTP 412), preventing the client from
        committing funds against a budget snapshot it has not observed."

        Design: Corner/complexity_layers/occ_stale_budget_version_rejected
        """
        budget = create_budget(fiscal_year=2026, total_cents=500000)
        p1 = create_pole(pole_number="P-O1", species="LARCH", original_class="2",
                         install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                         gis_tag="RURAL", height_ft=35)
        p2 = create_pole(pole_number="P-O2", species="LARCH", original_class="2",
                         install_date="2001-05-01", gis_lat=46.1, gis_lon=-121.1,
                         gis_tag="RURAL", height_ft=35)
        o1 = create_replacement_order(p1["id"], estimated_cost_cents=100000)
        o2 = create_replacement_order(p2["id"], estimated_cost_cents=100000)
        fund_order(o1["id"], budget["id"], budget["version"])

        # The first fund advanced budget.version; the client still holds the old one.
        resp = api.fund_replacement_work_order(
            o2["id"], fund_order_payload(budget["id"], budget["version"]),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_BUDGET_VERSION)
        assert get_order(o2["id"])["status"] == "QUEUED"
        after = get_budget(budget["id"])
        assert after["committed_cents"] == 100000, (
            "the stale-version rejection must not move any money"
        )
        assert_budget_invariant(after)

    def test_fund_with_bogus_budget_returns_not_found(self, api, program_manager_headers):
        """PRD §2.9: "Only after path identifiers resolve does the system resolve
        foreign-key identifiers carried in the request body — `pole_id`, `cycle_id`,
        `crew_id`, `budget_id`, and `treatment_order_id`. Each unresolved identifier
        maps to its resource-specific error".

        Design: Corner/validations/fund_with_bogus_budget_returns_not_found
        """
        pole = create_pole(pole_number="P-BNF", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        order = create_replacement_order(pole["id"], estimated_cost_cents=100000)
        resp = api.fund_replacement_work_order(
            order["id"],
            fund_order_payload(NON_EXISTENT_UUID, pole["version"]),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_NOT_FOUND)


class TestImmediateConsistency:
    def test_immediate_visibility_of_fund_effects(self, api, program_manager_headers):
        """PRD §3.8: "A successful fund moves the order to `FUNDED`, adds the escalated
        cost to the budget's `committed_cents`, sets the order's `budget_id` to the
        funding budget, stamps `funded_at` from the logical clock, and increments the
        `version` of both the budget and the order."
        PRD §3.1: "`available_cents` is the total minus committed minus spent."

        Design: Corner/consistency_model/immediate_visibility_of_fund_effects
        """
        budget = create_budget(fiscal_year=2026, total_cents=500000)
        pole = create_pole(pole_number="P-IC", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        order = create_replacement_order(pole["id"], estimated_cost_cents=100000)
        resp = api.fund_replacement_work_order(
            order["id"], fund_order_payload(budget["id"], budget["version"]),
            program_manager_headers,
        )
        funded = validate_success(resp, expected_status=200)
        assert_replacement_work_order(funded)
        assert funded["status"] == "FUNDED"
        assert funded["budget_id"] == budget["id"]

        after = get_budget(budget["id"])
        assert after["committed_cents"] == 100000, (
            "the committed balance is visible on the immediately following read"
        )
        assert after["available_cents"] == 400000
        assert_budget_invariant(after)


class TestDeferRequeueCycle:
    def _setup_deferred(self, api, program_manager_headers):
        budget = create_budget(fiscal_year=2026, total_cents=100)
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        pole = create_pole(pole_number="P-DF")
        order = create_replacement_order(pole["id"], estimated_cost_cents=200000)
        return budget, cycle, order

    def test_defer_escalates_cost(self, api, program_manager_headers):
        """PRD §3.8: "Deferring a `QUEUED` order moves it to `DEFERRED`, increments
        `deferral_count` by one, and recomputes `escalated_cost_cents` at the new
        deferral power; deferred orders wait out the cycle and are automatically
        requeued at the next reconcile."

        Design: Difficulty/non_linear_state_machine/replacement_defer_requeue_cycle
        """
        _, _, order = self._setup_deferred(api, program_manager_headers)
        resp = api.defer_replacement_work_order(order["id"], program_manager_headers)
        deferred = validate_success(resp, expected_status=200)
        assert deferred["status"] == "DEFERRED"
        assert deferred["deferral_count"] == 1
        assert deferred["escalated_cost_cents"] == 216000

    def test_reconcile_requeues_retaining_deferral(self, api, program_manager_headers):
        """PRD §3.9: "Step one requeues deferrals: every `ReplacementWorkOrder` in
        `DEFERRED` returns to `QUEUED` with its `deferral_count` retained, and its
        `priority_score` is recomputed at the current deferral count."
        PRD §3.8: "start with a deficiency of 100 minus the pole's
        `current_remaining_strength_pct`, where a null strength counts as 50.00; add a
        deferral term of 5 points per deferral".

        Design: Difficulty/non_linear_state_machine/replacement_defer_requeue_cycle
        """
        budget, cycle, order = self._setup_deferred(api, program_manager_headers)
        validate_success(
            api.defer_replacement_work_order(order["id"], program_manager_headers),
            expected_status=200,
        )
        reconcile_cycle(cycle["id"], budget["id"])
        after = get_order(order["id"])
        assert after["status"] == "QUEUED", "reconcile step one auto-requeues"
        assert after["deferral_count"] == 1, "deferral_count is retained"
        # deficiency 50 (null strength) + deferral 5 = 55.
        assert after["priority_score"] == 55
        assert after["escalated_cost_cents"] == 216000
        # The 100-cent budget cannot fund a 216000-cent order, so it stays QUEUED.
        assert get_budget(budget["id"])["committed_cents"] == 0
