"""Staffing allocations and position control: the formula FTE floor, the
position-control ceiling, headroom, dual cost-estimate variants, and hiring
transitions (PRD §3.3)."""
from test_helpers import (
    ApiErrorId, assert_money, assert_position, get_success_data,
    validate_error, validate_paginated, validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_position_payload, create_staffing_allocation_payload,
    fill_position_payload,
)
from test_helpers.fixtures import (
    add_budget_line, add_projection, add_revenue_estimate,
    add_staffing_allocation, add_position, create_budget_version,
    create_fiscal_year, create_open_fiscal_year, setup_adopted_budget,
    setup_draft_budget,
)
from test_helpers.test_users import TEST_USERS

BA = TEST_USERS["budget_analyst_headers"]
BM = TEST_USERS["business_manager_headers"]
SU = TEST_USERS["superintendent_headers"]
AU = TEST_USERS["auditor_headers"]


class TestStaffingFormula:
    def test_small_band_floor_and_over_allocation_rejected(self, api):
        """PRD §3.3: "A band with fewer than 40 pupils requires exactly 1.0
        FTE." and "The supplied `allocated_fte` must be positive and a
        multiple of 0.5 (otherwise `ERR_INVALID_FIELD_VALUE`), and it may not
        exceed `required_fte`; an allocation above the formula fails with
        `ERR_ALLOCATION_EXCEEDS_FORMULA`."

        Design: Difficulty/combinatorial_formula/staffing_fte_small_band_floor_vs_half_step_ceil
        """
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 39},
                                 with_revenue_estimate=False)
        bv_id = ctx["bv"]["id"]
        ep_id = ctx["projections"]["ELEMENTARY"]["id"]
        # 39 pupils < 40 -> required_fte 1.0; 1.5 exceeds it.
        resp = api.create_staffing_allocation(
            bv_id, create_staffing_allocation_payload("ELEMENTARY", ep_id,
                                                      1.5), BA)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_FORMULA, 422)
        # allocated_fte == required_fte exactly is accepted.
        data = validate_success(api.create_staffing_allocation(
            bv_id, create_staffing_allocation_payload("ELEMENTARY", ep_id,
                                                      1.0), BA), 201)
        assert data["required_fte"] == 1.0
        assert data["allocated_fte"] == 1.0

    def test_half_step_ceil_granularity_per_band(self, api):
        """PRD §3.3: "Otherwise the requirement is the pupil count divided by
        the band's staffing ratio — 20 for `ELEMENTARY`, 22 for `MIDDLE`, 25
        for `HIGH` — with the quotient multiplied by two, rounded up to the
        next whole number, and divided by two, yielding half-FTE
        granularity."

        Design: Difficulty/combinatorial_formula/staffing_fte_small_band_floor_vs_half_step_ceil
        """
        ctx = setup_draft_budget(pupils_by_band={"MIDDLE": 41},
                                 with_revenue_estimate=False)
        # 41 / 22 = 1.8636.. -> x2 = 3.7272.. -> round up = 4 -> /2 = 2.0
        sa = add_staffing_allocation(ctx["bv"]["id"], "MIDDLE",
                                     ctx["projections"]["MIDDLE"]["id"], 2.0)
        assert sa["required_fte"] == 2.0
        assert sa["allocated_fte"] == 2.0


class TestPositionControl:
    def test_position_initial_state_proposed_before_adoption(self, api):
        """PRD §3.3: "A position created while its allocation is `DRAFT`
        starts `PROPOSED`" and "A position's `incumbent_salary` stays null
        until the slot is filled."

        Design: Corner/state_machines/position_initial_state_proposed_before_adoption
        """
        ctx = setup_draft_budget(
            pupils_by_band={"ELEMENTARY": 1200},
            allocation_specs=[("ELEMENTARY", 3.0)])
        sa = ctx["allocations"]["ELEMENTARY"]
        resp = api.create_position(
            sa["id"], create_position_payload("Teacher 1", 1.0, 64000), BA)
        data = validate_success(resp, 201)
        assert_position(data)
        assert data["status"] == "PROPOSED"
        assert data["incumbent_salary"] is None

    def test_position_headroom_exact_boundary_allowed_over_rejected(self, api):
        """PRD §3.3: "Headroom is enforced at creation: the new position's
        `fte` may not exceed the allocation's `allocated_fte` minus the summed
        `fte` of its positions that are not `ELIMINATED`; landing exactly on
        the headroom is permitted, and any excess is rejected with
        `ERR_POSITION_FTE_EXCEEDED`."

        Design: Corner/calculations/position_headroom_exact_boundary_allowed_over_rejected
        """
        ctx = setup_draft_budget(
            pupils_by_band={"ELEMENTARY": 1200},
            allocation_specs=[("ELEMENTARY", 1.0)])
        sa = ctx["allocations"]["ELEMENTARY"]
        # fte 1.0 lands exactly on the 1.0 headroom: allowed.
        add_position(sa["id"], "Teacher 1", 1.0, 64000)
        # A further 0.5 exceeds the remaining headroom of 0.0.
        resp = api.create_position(
            sa["id"], create_position_payload("Aide 1", 0.5, 32000), BA)
        validate_error(resp, ApiErrorId.ERR_POSITION_FTE_EXCEEDED, 422)
        sa_now = validate_success(api.get_staffing_allocation(sa["id"], AU),
                                  200)
        assert sa_now["positions_fte_total"] == 1.0

    def test_fte_ceiling_aggregate_boundary_across_allocations(self, api):
        """PRD §3.3: "The sum of `allocated_fte` over all staffing allocations
        of the same budget version, including the one being created, may not
        exceed the fiscal year's `fte_ceiling`. A sum that lands exactly on
        the ceiling is permitted; a strictly greater sum fails with
        `ERR_FTE_CEILING_EXCEEDED`."

        Design: Corner/calculations/fte_ceiling_aggregate_boundary_across_allocations
        """
        pupils = {"ELEMENTARY": 1200, "MIDDLE": 800, "HIGH": 1000}

        # Ceiling 130: 60.0 + 36.5 + 40.0 = 136.5 > 130 -> third fails.
        ctx_c = setup_draft_budget(pupils_by_band=pupils,
                                   with_revenue_estimate=False,
                                   fy_overrides={"fte_ceiling": 130})
        bvc = ctx_c["bv"]["id"]
        add_staffing_allocation(bvc, "ELEMENTARY",
                                ctx_c["projections"]["ELEMENTARY"]["id"], 60.0)
        add_staffing_allocation(bvc, "MIDDLE",
                                ctx_c["projections"]["MIDDLE"]["id"], 36.5)
        resp = api.create_staffing_allocation(
            bvc, create_staffing_allocation_payload(
                "HIGH", ctx_c["projections"]["HIGH"]["id"], 40.0), BA)
        validate_error(resp, ApiErrorId.ERR_FTE_CEILING_EXCEEDED, 422)

        # Ceiling 136.5: the identical set lands exactly on it — permitted.
        ctx_d = setup_draft_budget(
            pupils_by_band=pupils, with_revenue_estimate=False,
            fy_overrides={"label": "FY2029", "start_date": "2028-07-01",
                          "end_date": "2029-06-30", "fte_ceiling": 136.5})
        bvd = ctx_d["bv"]["id"]
        add_staffing_allocation(bvd, "ELEMENTARY",
                                ctx_d["projections"]["ELEMENTARY"]["id"], 60.0)
        add_staffing_allocation(bvd, "MIDDLE",
                                ctx_d["projections"]["MIDDLE"]["id"], 36.5)
        sa_h = add_staffing_allocation(bvd, "HIGH",
                                       ctx_d["projections"]["HIGH"]["id"],
                                       40.0)
        assert sa_h["allocated_fte"] == 40.0

    def test_allocation_with_cross_fiscal_year_projection_rejected(self, api):
        """PRD §3.3: "The referenced projection must exist, and it must belong
        to the same fiscal year as the budget version — a cross-year reference
        fails with `ERR_CROSS_FISCAL_YEAR_REFERENCE`."

        Design: Corner/validations/allocation_with_cross_fiscal_year_projection_rejected
        """
        fy_a = create_open_fiscal_year(label="FY2028")
        fy_b = create_open_fiscal_year(label="FY2029", start_date="2028-07-01",
                                       end_date="2029-06-30")
        ep_b = add_projection(fy_b["id"], "ELEMENTARY", 1200)
        bv = create_budget_version(fy_a["id"])
        resp = api.create_staffing_allocation(
            bv["id"], create_staffing_allocation_payload(
                "ELEMENTARY", ep_b["id"], 1.0), BA)
        validate_error(resp, ApiErrorId.ERR_CROSS_FISCAL_YEAR_REFERENCE, 422)
        allocations, meta = validate_paginated(
            api.list_staffing_allocations(bv["id"], AU))
        assert allocations == []
        assert meta["total_count"] == 0


class TestCostEstimateVariants:
    def _adopted_staffing(self):
        """ADOPTED budget: ELEMENTARY allocation 3.0 with three 1.0-FTE
        positions (base 64,000), all OPEN after the adoption cascade."""
        return setup_adopted_budget(
            pupils_by_band={"ELEMENTARY": 1200},
            allocation_specs=[("ELEMENTARY", 3.0)],
            position_specs=[("ELEMENTARY", "Teacher 1", 1.0, 64000),
                            ("ELEMENTARY", "Teacher 2", 1.0, 64000),
                            ("ELEMENTARY", "Teacher 3", 1.0, 64000)])

    def test_projected_variant_uses_district_average(self, api):
        """PRD §3.3: "`cost_estimate_projected` is formula-driven:
        `allocated_fte` multiplied by the district average salary of 62,000
        and by 1.34, loading 34 percent for benefits."

        Design: Difficulty/dual_variant_calc/staffing_cost_projected_vs_position_actual
        """
        ctx = self._adopted_staffing()
        sa_id = ctx["allocations"]["ELEMENTARY"]["id"]
        sa = validate_success(api.get_staffing_allocation(sa_id, AU), 200)
        assert sa["status"] == "AUTHORIZED"
        # 3.0 * 62,000 * 1.34 = 249,240.00
        assert_money(sa["cost_estimate_projected"], 249240.00,
                     "cost_estimate_projected")
        # Before any fill, all three slots price at base_salary:
        # (64,000 * 3) * 1.34 = 257,280.00
        assert_money(sa["cost_estimate_actual"], 257280.00,
                     "cost_estimate_actual before fills")

    def test_position_actual_variant_uses_slot_salaries(self, api):
        """PRD §3.3: "`cost_estimate_actual` is position-driven: the sum over
        the allocation's positions that are not `ELIMINATED` of each
        position's salary basis — its `incumbent_salary` when the position is
        `FILLED`, otherwise its `base_salary` — multiplied by the position's
        `fte` and by the same 1.34 load." and "Filling an `OPEN` position
        moves it to `FILLED` and records the supplied `incumbent_salary`".

        Design: Difficulty/dual_variant_calc/staffing_cost_projected_vs_position_actual
        """
        ctx = self._adopted_staffing()
        sa_id = ctx["allocations"]["ELEMENTARY"]["id"]
        p1, p2, p3 = ctx["positions"]
        # Adoption opened all three positions.
        positions, _ = validate_paginated(api.list_positions(sa_id, AU))
        assert all(row["status"] == "OPEN" for row in positions)
        get_success_data(api.fill_position(p1["id"],
                                           fill_position_payload(58000), SU))
        get_success_data(api.fill_position(p2["id"],
                                           fill_position_payload(71000), SU))
        sa = validate_success(api.get_staffing_allocation(sa_id, AU), 200)
        # POSITION_ACTUAL: (58,000 + 71,000 + 64,000) * 1.0 * 1.34 = 258,620.00
        assert_money(sa["cost_estimate_actual"], 258620.00,
                     "cost_estimate_actual after two fills")
        # PROJECTED_ALLOCATION ignores actual positions entirely.
        assert_money(sa["cost_estimate_projected"], 249240.00,
                     "cost_estimate_projected unchanged")
        positions, _ = validate_paginated(api.list_positions(sa_id, AU))
        by_id = {row["id"]: row for row in positions}
        assert by_id[p3["id"]]["status"] == "OPEN"
        assert by_id[p1["id"]]["status"] == "FILLED"
        assert by_id[p1["id"]]["incumbent_salary"] == 58000


class TestHiringTransitions:
    def _adopted_with_one_position(self):
        return setup_adopted_budget(
            pupils_by_band={"ELEMENTARY": 1200},
            allocation_specs=[("ELEMENTARY", 3.0)],
            position_specs=[("ELEMENTARY", "Teacher 1", 1.0, 64000)])

    def test_eliminate_filled_position_rejected_invalid_state(self, api):
        """PRD §3.3: "An operator may not eliminate a `FILLED` position — the
        attempt is rejected with `ERR_INVALID_STATE` — although the supersede
        cascade of §3.5 eliminates positions in any of the three live
        states."

        Design: Corner/state_machines/eliminate_filled_position_rejected_invalid_state
        """
        ctx = self._adopted_with_one_position()
        p = ctx["positions"][0]
        get_success_data(api.fill_position(p["id"],
                                           fill_position_payload(65000), SU))
        resp = api.eliminate_position(p["id"], SU)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        positions, _ = validate_paginated(
            api.list_positions(ctx["allocations"]["ELEMENTARY"]["id"], AU))
        assert positions[0]["status"] == "FILLED"
        assert positions[0]["incumbent_salary"] == 65000

    def test_vacate_open_position_rejected_invalid_state(self, api):
        """PRD §3.3: "Vacating reverses the act — `FILLED` back to `OPEN`,
        `incumbent_salary` cleared to null" — vacate exists only from FILLED,
        so vacating an OPEN position is the generic from-state violation
        (`ERR_INVALID_STATE`, PRD §2.9 stage 8).

        Design: Corner/state_machines/vacate_open_position_rejected_invalid_state
        """
        ctx = self._adopted_with_one_position()
        p = ctx["positions"][0]  # OPEN after the adoption cascade
        resp = api.vacate_position(p["id"], SU)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_fill_filled_position_rejected_invalid_state(self, api):
        """PRD §3.3: "Filling an `OPEN` position moves it to `FILLED` and
        records the supplied `incumbent_salary`" — fill exists only from OPEN,
        so filling an already-FILLED position is the generic from-state
        violation (`ERR_INVALID_STATE`, PRD §2.9 stage 8).

        Design: Corner/state_machines/fill_filled_position_rejected_invalid_state
        """
        ctx = self._adopted_with_one_position()
        p = ctx["positions"][0]
        get_success_data(api.fill_position(p["id"],
                                           fill_position_payload(65000), SU))
        resp = api.fill_position(p["id"], fill_position_payload(70000), SU)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        positions, _ = validate_paginated(
            api.list_positions(ctx["allocations"]["ELEMENTARY"]["id"], AU))
        assert positions[0]["status"] == "FILLED"
        assert positions[0]["incumbent_salary"] == 65000
