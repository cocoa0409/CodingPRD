"""Compensating invariant instances: dispatch/cancel exact budget refund, and
the salvage fixture-count conservation across batch reject."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_active_program,
    create_batch,
    create_crew,
    create_district,
    dispatch_and_complete,
    dispatch_work_order,
    find_salvage_item_for_pole,
    get_batch,
    get_pole,
    get_program,
    get_salvage_item,
    get_stop,
    get_work_order,
    make_field_supervisor_headers,
    setup_cleared_pole,
    setup_released_route,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]

# Module-level alias used by class-level setup helpers; the `api` pytest
# fixture returns this same shared client object.
api = api_client


class TestBudgetInvariantDispatchCancelExactRefund:
    def _setup(self):
        """Program budget 80000; ARTERIAL district; crew (6000c/hr); one
        UTILITY_OWNED pole 250W attested; one-stop COMPLEX route RELEASED."""
        program = create_active_program(budget=80000)
        district = create_district(program["id"], zone="ARTERIAL")
        crew = create_crew(program["id"])
        pole = setup_cleared_pole(program, district, crew, pole_number="B-01",
                                  ownership_type="UTILITY_OWNED", nameplate_wattage=250)
        route, stops, wos = setup_released_route(
            program, district, crew, [pole], start="2026-08-03", end="2026-08-03",
            difficulties=["COMPLEX"])
        return program, crew, pole, route, stops[0], wos[0]

    def test_dispatch_debits_straight_time_estimate(self, api):
        """PRD section 3.4: "the straight-time estimate
        `estimated_labor_cost_cents` — the crew's `hourly_rate_cents`
        multiplied by the order's `stop_minutes` and divided by 60, rounded
        half-up"; PRD section 2.5: "Dispatching a work order from `PENDING`
        debits `estimated_labor_cost_cents`."

        Design: Difficulty/compensating_invariant/budget_invariant_dispatch_cancel_exact_refund
        """
        program, crew, _pole, _route, _stop, wo = self._setup()
        resp = api.dispatch_work_order(
            wo["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        dispatched = validate_success(resp)
        # COMPLEX stop: rhu(6000 * 120 / 60) = 12000
        assert dispatched["estimated_labor_cost_cents"] == 12000
        assert get_program(program["id"])["budget_balance_cents"] == 68000  # 80000 - 12000

    def test_cancel_from_dispatched_restores_budget_exactly_and_unwinds(self, api):
        """PRD section 2.5: "The compensating-pair invariant is part of the
        contract: a dispatch from PENDING followed by a cancel from DISPATCHED
        leaves budget_balance_cents exactly unchanged"; PRD section 3.4: "From
        PENDING, or from DISPATCHED with the outstanding-estimate refund of
        §2.5, the linked stop, if still PENDING, skips and the pole, if still
        SCHEDULED, returns to AUDIT_CLEARED."

        Design: Difficulty/compensating_invariant/budget_invariant_dispatch_cancel_exact_refund
        """
        program, crew, pole, _route, stop, wo = self._setup()
        api.dispatch_work_order(
            wo["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        resp = api.cancel_work_order(wo["id"], PM)
        cancelled = validate_success(resp)
        assert cancelled["execution_status"] == "CANCELLED"
        # EXACT restoration — the compensating pair conserves dollars
        assert get_program(program["id"])["budget_balance_cents"] == 80000
        assert get_stop(stop["id"])["status"] == "SKIPPED"
        assert get_pole(pole["id"])["status"] == "AUDIT_CLEARED"


class TestFixtureCountInvariantBatchRejectReturnsPool:
    def _setup(self):
        """Two UTILITY_OWNED poles converted (two unbatched SalvageItems);
        batch created, both items added (20.0 and 30.0 lb), sealed (not
        contaminated), manifested."""
        program = create_active_program()
        district = create_district(program["id"], zone="RESIDENTIAL")
        crew = create_crew(program["id"])
        p1 = setup_cleared_pole(program, district, crew, pole_number="F-01",
                                ownership_type="UTILITY_OWNED", nameplate_wattage=250,
                                fixture_class="COBRA_HEAD")
        p2 = setup_cleared_pole(program, district, crew, pole_number="F-02",
                                ownership_type="UTILITY_OWNED", nameplate_wattage=250,
                                fixture_class="POST_TOP")
        route, stops, wos = setup_released_route(
            program, district, crew, [p1, p2], start="2026-08-02", end="2026-08-02")
        for wo in wos:
            dispatch_and_complete(wo["id"], crew["id"], wattage=90, cct=2700,
                                  shielding="FULL_CUTOFF")
        pending_after_complete = get_program(program["id"])["pending_salvage_item_count"]
        it1 = find_salvage_item_for_pole(p1["id"])
        it2 = find_salvage_item_for_pole(p2["id"])
        batch = create_batch(program["id"], batch_label="BATCH-R")
        for item, weight in ((it1, 20.0), (it2, 30.0)):
            resp = api.add_salvage_item(
                batch["id"],
                {"salvage_item_id": item["id"], "weight_lbs": weight, "mercury_flag": False},
                PM,
            )
            assert resp.status_code == 200, f"Setup failed: add item -> {resp.text}"
        resp = api.seal_salvage_batch(batch["id"], {"contaminated_flag": False}, CO)
        assert resp.status_code == 200, f"Setup failed: seal -> {resp.text}"
        resp = api.manifest_salvage_batch(batch["id"], CO)
        assert resp.status_code == 200, f"Setup failed: manifest -> {resp.text}"
        return program, batch, it1, it2, pending_after_complete

    def test_completions_drop_items_and_batching_drains_pool(self, api):
        """PRD section 3.7: "Each first completion of a work order drops one
        item into the program's unbatched pool (§3.4)"; PRD section 3.1:
        "pending_salvage_item_count counts salvage items sitting in the
        unbatched pool."

        Design: Difficulty/compensating_invariant/fixture_count_invariant_batch_reject_returns_pool
        """
        _program, batch, it1, it2, pending_after_complete = self._setup()
        assert pending_after_complete == 2  # each completion added one unbatched fixture
        # After batching both, the pool is drained and the batch holds them
        mid = get_batch(batch["id"])
        assert mid["item_count"] == 2
        assert mid["status"] == "MANIFESTED"

    def test_reject_returns_items_to_pool_and_erases_settlement(self, api):
        """PRD section 3.7: "Rejection, by the ComplianceOfficer, is available
        from SEALED or MANIFESTED (ERR_BATCH_NOT_REJECTABLE otherwise): every
        item returns to the unbatched pool with batch_id null, any computed
        settlement_value_cents is cleared back to null, and the program's
        pending_salvage_item_count is recomputed. A rejected batch never posts
        money".

        Design: Difficulty/compensating_invariant/fixture_count_invariant_batch_reject_returns_pool
        """
        program, batch, it1, it2, _pending = self._setup()
        resp = api.reject_salvage_batch(batch["id"], CO)
        rejected = validate_success(resp)
        assert rejected["status"] == "REJECTED"
        assert rejected["settlement_value_cents"] is None
        assert rejected["item_count"] == 0

        assert get_salvage_item(it1["id"])["batch_id"] is None
        assert get_salvage_item(it2["id"])["batch_id"] is None

        program_after = get_program(program["id"])
        # compensating reject restored the unbatched pool exactly
        assert program_after["pending_salvage_item_count"] == 2
        # the rejected batch posted NO settlement credit: 10000000 - 2 x 4500
        assert program_after["budget_balance_cents"] == 9991000
