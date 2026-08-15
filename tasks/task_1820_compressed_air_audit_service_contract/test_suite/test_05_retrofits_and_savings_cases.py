"""Retrofit projects, savings cases (deemed/measured), and utility rebates."""
from test_helpers import (
    ApiErrorId,
    assert_savings_case,
    create_compressor,
    create_demand_profile,
    create_facility,
    create_retrofit_project,
    lock_demand_profile,
    make_contract_manager_headers,
    make_energy_engineer_headers,
    make_facility_manager_headers,
    make_service_tech_headers,
    model_savings_case,
    setup_savings_pipeline,
    validate_error,
    validate_success,
)

ENGINEER = make_energy_engineer_headers("eng-1")
TECH = make_service_tech_headers("tech-1")
CONTRACT_MGR = make_contract_manager_headers()

# The canonical three-leak set from the PRD's worked figures: 12.5 / 8.0 / 1.5 CFM
# at 6000 operating hours -> 15000 / 9600 / 1800 kWh per-tag savings.
CANONICAL_LEAKS = [
    {"location_description": "header drop", "cfm_loss": 12.5, "repair_quote_cents": 400000},
    {"location_description": "hose reel", "cfm_loss": 8.0, "repair_quote_cents": 250000},
    {"location_description": "coupling", "cfm_loss": 1.5, "repair_quote_cents": 90000},
]


class TestRetrofitCreation:
    def test_retrofit_target_pressure_must_be_lower(self, api):
        """PRD §3.5: "the post-retrofit `target_pressure_psi` — which must be
        strictly below the baseline, or the request fails schema validation with
        `ERR_INVALID_REQUEST` — an ordered `sequence_compressor_ids` array forming
        the sequencing plan"

        Design: Corner/entities/corner_retrofit_target_pressure_must_be_lower
        """
        facility = create_facility(name="F-PSI", activate=False)
        compressor = create_compressor(facility["id"])
        resp = api.create_retrofit_project(
            {
                "facility_id": facility["id"],
                "baseline_pressure_psi": 110,
                "target_pressure_psi": 110,
                "sequence_compressor_ids": [compressor["id"]],
                "project_cost_cents": 1000000,
            },
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_sequence_compressor_invalid_at_create_and_approve(self, api):
        """PRD §3.5: "Every identifier in `sequence_compressor_ids` must resolve to
        a Compressor of the same facility; an unknown or foreign entry is rejected
        with `ERR_SEQUENCE_COMPRESSOR_INVALID` (HTTP 422)."
        PRD §3.5: "A `FacilityManager` approves a `PROPOSED` project to `APPROVED`,
        and approval revalidates the sequence: every entry must still resolve to a
        compressor of the facility and must be `IN_SERVICE` at approval time,
        otherwise the approval is rejected with `ERR_SEQUENCE_COMPRESSOR_INVALID`."

        Design: Corner/validations/corner_sequence_compressor_invalid_at_create_and_approve
        """
        facility_a = create_facility(name="FA-SQ")
        comp_a = create_compressor(facility_a["id"], asset_tag="CA")
        facility_b = create_facility(name="FB-SQ", activate=False)
        comp_b = create_compressor(facility_b["id"], asset_tag="CB")
        project = create_retrofit_project(
            facility_a["id"], [comp_a["id"]], project_cost_cents=1000000
        )
        validate_success(api.mark_down(comp_a["id"], TECH))

        resp = api.create_retrofit_project(
            {
                "facility_id": facility_a["id"],
                "baseline_pressure_psi": 125,
                "target_pressure_psi": 100,
                "sequence_compressor_ids": [comp_b["id"]],
                "project_cost_cents": 1000000,
            },
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_COMPRESSOR_INVALID, 422)

        resp = api.approve_retrofit_project(
            project["id"], make_facility_manager_headers(facility_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_COMPRESSOR_INVALID, 422)
        project = validate_success(api.get_retrofit_project(project["id"], ENGINEER))
        assert project["status"] == "PROPOSED", "rejected approval must leave the project PROPOSED"


class TestSavingsCaseCreationGates:
    def test_case_create_requires_locked_baseline_and_approved_project(self, api):
        """PRD §3.6: "Creation is gated, in order: the facility must be `ACTIVE`
        (`ERR_FACILITY_NOT_ACTIVE`); the baseline profile must be `LOCKED`
        (`ERR_PROFILE_NOT_LOCKED`); the retrofit project must be `APPROVED` or later
        — `APPROVED`, `INSTALLED`, `COMMISSIONED`, or `ACCEPTED`
        (`ERR_RETROFIT_NOT_APPROVED`); and both references must belong to the same
        facility as the case (`ERR_FACILITY_MISMATCH`)."

        Design: Corner/validations/corner_case_create_requires_locked_baseline_and_approved_project
        """
        facility = create_facility(name="F-CC")
        compressor = create_compressor(facility["id"])
        profile = create_demand_profile(facility["id"])
        project = create_retrofit_project(facility["id"], [compressor["id"]])

        resp = api.create_savings_case(
            {
                "facility_id": facility["id"],
                "baseline_profile_id": profile["id"],
                "retrofit_project_id": project["id"],
            },
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_PROFILE_NOT_LOCKED, 409)

        lock_demand_profile(facility["id"], profile["id"], user_id="eng-1")
        resp = api.create_savings_case(
            {
                "facility_id": facility["id"],
                "baseline_profile_id": profile["id"],
                "retrofit_project_id": project["id"],
            },
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_RETROFIT_NOT_APPROVED, 409)


class TestDeemedSavings:
    def test_deemed_savings_computed_at_model(self, api):
        """PRD §3.6: "The leak component is the sum of the `annual_kwh_savings` of
        every `VERIFIED_CLOSED` leak tag belonging to a `VERIFIED` survey of the
        same facility — and because each tag's value was already rounded to a whole
        kilowatt-hour at closure (§3.4), the component is exactly that sum."
        PRD §3.6: "The sequencing component credits the pressure reduction: the
        pressure drop is the project's `baseline_pressure_psi` minus its
        `target_pressure_psi`, capped at 20 psi when the raw drop is larger, and the
        component is the pinned baseline profile's `baseline_annual_kwh` multiplied
        by a percentage equal to 7 percent plus an additional 0.5 percent for each
        psi of capped pressure drop, the product rounded half-up to a whole
        kilowatt-hour. `deemed_annual_savings_kwh` is the sum of the two components,
        and the rounding order is pinned: round each leak first, then sum the leaks,
        then add the sequencing component."

        Design: Difficulty/dual_variant_calc/deemed_vs_measured_savings_diverge
        """
        pipeline = setup_savings_pipeline(
            name="F-DV", num_compressors=2, leaks=CANONICAL_LEAKS, advance_to="MODELED"
        )
        case = pipeline["case"]
        assert_savings_case(case)
        assert case["savings_status"] == "MODELED"
        # leak component 15000 + 9600 + 1800 = 26400; sequencing 2920000 x 0.17 = 496400
        assert case["deemed_annual_savings_kwh"] == 522800, (
            f"deemed must be 26400 + 496400 = 522800, got {case['deemed_annual_savings_kwh']}"
        )

    def test_measured_savings_diverges_from_deemed(self, api):
        """PRD §3.6: "On success the case stores `post_profile_id` and computes
        `measured_annual_savings_kwh`: the post profile is annualized with the same
        formula as any profile — its `measured_kwh` multiplied by 365 and divided by
        its inclusive window length in days, rounded half-up — and the measured
        savings is the pinned baseline's `baseline_annual_kwh` minus that annualized
        post figure."

        Design: Difficulty/dual_variant_calc/deemed_vs_measured_savings_diverge
        """
        pipeline = setup_savings_pipeline(
            name="F-DV2", num_compressors=2, leaks=CANONICAL_LEAKS, advance_to="MEASURED"
        )
        case = pipeline["case"]
        assert case["savings_status"] == "MEASURED"
        # post annualized: 200000 x 365 / 30 = 2433333 (round half up);
        # measured = 2920000 - 2433333 = 486667
        assert case["measured_annual_savings_kwh"] == 486667, (
            f"measured must be 486667, got {case['measured_annual_savings_kwh']}"
        )
        assert case["deemed_annual_savings_kwh"] == 522800
        assert case["deemed_annual_savings_kwh"] != case["measured_annual_savings_kwh"], (
            "the deemed and measured variants are distinct algorithms and must diverge here"
        )

    def test_per_leak_rounding_values(self, api):
        """PRD §3.4: "the tag's `cfm_loss` is multiplied by 0.20 kilowatts per CFM
        and by the facility's `operating_hours_per_year`, and the product is rounded
        half-up to a whole kilowatt-hour."
        PRD §3.6: "Recomputing leak savings from raw CFM figures and rounding once
        after summing is a different, rejected formula: two leaks of 0.85 and 1.15
        CFM at 5,933 annual operating hours yield 2,374 kWh under the pinned per-tag
        rounding but 2,373 kWh when raw products are summed and rounded once, and
        only the former is authoritative."

        Design: Difficulty/combinatorial_formula/per_leak_rounding_then_sum
        """
        pipeline = setup_savings_pipeline(
            name="F-RND",
            operating_hours_per_year=5933,
            leaks=[
                {"location_description": "pinhole A", "cfm_loss": 0.85, "repair_quote_cents": 50000},
                {"location_description": "pinhole B", "cfm_loss": 1.15, "repair_quote_cents": 60000},
            ],
            target_pressure_psi=105,
            advance_to="DRAFT",
        )
        tags = pipeline["tags"]
        assert tags[0]["annual_kwh_savings"] == 1009, (
            f"0.85 x 0.20 x 5933 rounds to 1009, got {tags[0]['annual_kwh_savings']}"
        )
        assert tags[1]["annual_kwh_savings"] == 1365, (
            f"1.15 x 0.20 x 5933 rounds to 1365, got {tags[1]['annual_kwh_savings']}"
        )

    def test_per_leak_rounding_then_sum_in_deemed(self, api):
        """PRD §3.6: "Recomputing leak savings from raw CFM figures and rounding
        once after summing is a different, rejected formula: two leaks of 0.85 and
        1.15 CFM at 5,933 annual operating hours yield 2,374 kWh under the pinned
        per-tag rounding but 2,373 kWh when raw products are summed and rounded
        once, and only the former is authoritative."
        PRD §3.6: "`deemed_annual_savings_kwh` is the sum of the two components, and
        the rounding order is pinned: round each leak first, then sum the leaks,
        then add the sequencing component."

        Design: Difficulty/combinatorial_formula/per_leak_rounding_then_sum
        """
        pipeline = setup_savings_pipeline(
            name="F-RND2",
            operating_hours_per_year=5933,
            leaks=[
                {"location_description": "pinhole A", "cfm_loss": 0.85, "repair_quote_cents": 50000},
                {"location_description": "pinhole B", "cfm_loss": 1.15, "repair_quote_cents": 60000},
            ],
            target_pressure_psi=105,
            advance_to="DRAFT",
        )
        case = model_savings_case(pipeline["case"]["id"])
        # leak component = 1009 + 1365 = 2374 (per-tag rounding, NOT 2373);
        # sequencing = round(2920000 x (0.07 + 0.005 x 20)) = 496400
        assert case["deemed_annual_savings_kwh"] == 498774, (
            f"deemed must be 2374 + 496400 = 498774, got {case['deemed_annual_savings_kwh']}"
        )

    def test_deemed_input_set_excludes_unclosed_leaks(self, api):
        """PRD §3.6: "The leak component is the sum of the `annual_kwh_savings` of
        every `VERIFIED_CLOSED` leak tag belonging to a `VERIFIED` survey of the
        same facility — and because each tag's value was already rounded to a whole
        kilowatt-hour at closure (§3.4), the component is exactly that sum."

        Design: Corner/calculations/corner_deemed_input_set_excludes_unclosed_leaks
        """
        pipeline = setup_savings_pipeline(
            name="F-ISF",
            leaks=[
                {"location_description": "L1", "cfm_loss": 12.5, "repair_quote_cents": 400000},
                {"location_description": "L2", "cfm_loss": 8.0, "repair_quote_cents": 250000},
            ],
            close_leak_indices=[0],  # second tag stays QUOTED and contributes nothing
            advance_to="DRAFT",
        )
        case = model_savings_case(pipeline["case"]["id"])
        assert case["deemed_annual_savings_kwh"] == 511400, (
            f"deemed must be 15000 (closed tag only) + 496400 = 511400, "
            f"got {case['deemed_annual_savings_kwh']}"
        )


class TestIndependentDimensions:
    def test_rebate_filed_while_savings_modeled(self, api):
        """PRD §3.6: "It carries two independent state dimensions that evolve
        without touching each other: `savings_status` runs `DRAFT` to `MODELED` to
        `MEASUREMENT_OPEN` to the terminal `MEASURED`, while `rebate_status` runs
        `NONE` to `FILED` to a terminal `APPROVED` or `REJECTED`. Modeling a case,
        for instance, leaves its rebate dimension entirely alone."
        PRD §3.6: "Filing a rebate moves `rebate_status` from `NONE` to `FILED` and
        is available whenever `savings_status` is `MODELED` or `MEASURED`"

        Design: Difficulty/non_linear_state_machine/savings_case_independent_dimensions
        """
        pipeline = setup_savings_pipeline(
            name="F-PD", advance_to="MODELED", accept_project=True
        )
        case = validate_success(api.file_rebate(pipeline["case"]["id"], ENGINEER))
        assert case["rebate_status"] == "FILED"
        assert case["savings_status"] == "MODELED", (
            "filing the rebate must not move the savings dimension"
        )

    def test_measurement_closes_while_rebate_stays_filed(self, api):
        """PRD §3.6: "It carries two independent state dimensions that evolve
        without touching each other: `savings_status` runs `DRAFT` to `MODELED` to
        `MEASUREMENT_OPEN` to the terminal `MEASURED`, while `rebate_status` runs
        `NONE` to `FILED` to a terminal `APPROVED` or `REJECTED`."

        Design: Difficulty/non_linear_state_machine/savings_case_independent_dimensions
        """
        pipeline = setup_savings_pipeline(
            name="F-PD2", advance_to="MODELED", accept_project=True
        )
        facility = pipeline["facility"]
        case = validate_success(api.file_rebate(pipeline["case"]["id"], ENGINEER))
        assert case["rebate_status"] == "FILED"

        case = validate_success(api.open_measurement(case["id"], ENGINEER))
        post = create_demand_profile(
            facility["id"],
            window_start_date="2026-06-01",
            window_end_date="2026-06-30",
            measured_kwh=200000,
            measured_avg_cfm=300.0,
            measured_peak_cfm=480.0,
        )
        post = lock_demand_profile(facility["id"], post["id"], user_id="eng-1")
        case = validate_success(
            api.close_measurement(
                case["id"],
                {"post_profile_id": post["id"]},
                make_energy_engineer_headers("eng-2"),
            )
        )
        assert case["savings_status"] == "MEASURED"
        assert case["rebate_status"] == "FILED", (
            "closing the measurement must not move the rebate dimension"
        )
        assert case["measured_annual_savings_kwh"] == 486667


class TestRebates:
    def test_provisional_rebate_from_deemed(self, api):
        """PRD §3.6: "Filing computes `provisional_rebate_cents` from the rebate
        formula below over the **deemed** savings — always the deemed figure, even
        when the case is already `MEASURED` — and the provisional amount is never
        recomputed afterwards."
        PRD §3.6: "The rebate formula itself is a two-tier energy incentive under
        two caps, always evaluated tiered amount first and caps after: 7 cents for
        each of the first 100,000 kilowatt-hours of savings, plus 3 cents for each
        kilowatt-hour beyond 100,000; then a cost cap of one half of the referenced
        project's `project_cost_cents`, rounded half-up to a whole cent; the payable
        rebate is the smallest of the tiered amount, the cost cap, and the program
        ceiling of 20,000,000 cents."

        Design: Difficulty/combinatorial_formula/tiered_rebate_with_nested_min_caps
        """
        pipeline = setup_savings_pipeline(
            name="F-REB",
            num_compressors=2,
            leaks=CANONICAL_LEAKS,
            advance_to="MODELED",
            accept_project=True,
        )
        case = validate_success(api.file_rebate(pipeline["case"]["id"], ENGINEER))
        assert case["rebate_status"] == "FILED"
        # tiered: 7 x 100000 + 3 x 422800 = 1968400; cost cap 25000000; program 20000000
        assert case["provisional_rebate_cents"] == 1968400, (
            f"provisional over deemed 522800 must be 1968400, "
            f"got {case['provisional_rebate_cents']}"
        )

    def test_final_rebate_from_measured_after_approval(self, api):
        """PRD §3.6: "Approval computes `final_rebate_cents` from the same formula
        but over the **measured** savings when the case is `MEASURED`, and over the
        deemed savings otherwise; rejection leaves `final_rebate_cents` unset."

        Design: Difficulty/combinatorial_formula/tiered_rebate_with_nested_min_caps
        """
        pipeline = setup_savings_pipeline(
            name="F-REB2",
            num_compressors=2,
            leaks=CANONICAL_LEAKS,
            advance_to="MODELED",
            accept_project=True,
        )
        facility = pipeline["facility"]
        case = validate_success(api.file_rebate(pipeline["case"]["id"], ENGINEER))
        case = validate_success(api.open_measurement(case["id"], ENGINEER))
        post = create_demand_profile(
            facility["id"],
            window_start_date="2026-06-01",
            window_end_date="2026-06-30",
            measured_kwh=200000,
            measured_avg_cfm=300.0,
            measured_peak_cfm=480.0,
        )
        post = lock_demand_profile(facility["id"], post["id"], user_id="eng-1")
        case = validate_success(
            api.close_measurement(
                case["id"],
                {"post_profile_id": post["id"]},
                make_energy_engineer_headers("eng-2"),
            )
        )
        case = validate_success(
            api.record_rebate_decision(case["id"], {"outcome": "APPROVED"}, CONTRACT_MGR)
        )
        assert case["rebate_status"] == "APPROVED"
        # final over measured 486667: 7 x 100000 + 3 x 386667 = 1860001
        assert case["final_rebate_cents"] == 1860001, (
            f"final over measured 486667 must be 1860001, got {case['final_rebate_cents']}"
        )

    def test_rebate_cost_cap_binding(self, api):
        """PRD §3.6: "The rebate formula itself is a two-tier energy incentive under
        two caps, always evaluated tiered amount first and caps after: 7 cents for
        each of the first 100,000 kilowatt-hours of savings, plus 3 cents for each
        kilowatt-hour beyond 100,000; then a cost cap of one half of the referenced
        project's `project_cost_cents`, rounded half-up to a whole cent; the payable
        rebate is the smallest of the tiered amount, the cost cap, and the program
        ceiling of 20,000,000 cents."

        Design: Corner/calculations/corner_rebate_cost_cap_binding
        """
        pipeline = setup_savings_pipeline(
            name="F-CAP", project_cost_cents=1000000, advance_to="MODELED"
        )
        case = pipeline["case"]
        assert case["deemed_annual_savings_kwh"] == 496400, (
            f"with no verified-closed leaks, deemed is sequencing-only 496400, "
            f"got {case['deemed_annual_savings_kwh']}"
        )
        case = validate_success(api.file_rebate(case["id"], ENGINEER))
        # tiered 700000 + 3 x 396400 = 1889200; cost cap = 1000000 x 0.5 = 500000 binds
        assert case["provisional_rebate_cents"] == 500000, (
            f"cost cap must bind at 500000, got {case['provisional_rebate_cents']}"
        )


class TestMeasurementWindows:
    def test_post_window_before_acceptance_rejected(self, api):
        """PRD §3.6: "its `window_start_date` must fall strictly after the project's
        `accepted_date` so the measurement reflects post-acceptance operation
        (`ERR_POST_WINDOW_BEFORE_ACCEPTANCE`)"

        Design: Corner/validations/corner_post_window_before_acceptance_rejected
        """
        pipeline = setup_savings_pipeline(
            name="F-PW", advance_to="MEASUREMENT_OPEN", accept_date="2026-05-15"
        )
        facility = pipeline["facility"]
        post = create_demand_profile(
            facility["id"],
            window_start_date="2026-04-15",
            window_end_date="2026-05-14",
            measured_kwh=200000,
            measured_avg_cfm=300.0,
            measured_peak_cfm=480.0,
        )
        post = lock_demand_profile(facility["id"], post["id"], user_id="eng-1")

        resp = api.close_measurement(
            pipeline["case"]["id"],
            {"post_profile_id": post["id"]},
            make_energy_engineer_headers("eng-2"),
        )
        validate_error(resp, ApiErrorId.ERR_POST_WINDOW_BEFORE_ACCEPTANCE, 409)
        case = validate_success(api.get_savings_case(pipeline["case"]["id"], ENGINEER))
        assert case["savings_status"] == "MEASUREMENT_OPEN", (
            "rejected close must leave the case MEASUREMENT_OPEN"
        )


class TestRetrofitStaleness:
    def test_retrofit_stale_blocks_model(self, api):
        """PRD §3.6: "The transition from `DRAFT` to `MODELED` is gated by three
        checks in a pinned order: `baseline_stale` must be false — when both
        staleness flags happen to be set, `ERR_BASELINE_SUPERSEDED` is reported
        rather than `ERR_RETROFIT_STALE` — then `retrofit_stale` must be false
        (`ERR_RETROFIT_STALE`), and finally the referenced project must still be
        `APPROVED` or later (`ERR_RETROFIT_NOT_APPROVED`)."
        PRD §3.2: "Second, every SavingsCase referencing one of those freshly
        cancelled projects while its `savings_status` is `DRAFT` or `MODELED` has
        its `retrofit_stale` flag set to true."

        Design: Corner/validations/corner_retrofit_stale_blocks_model
        """
        pipeline = setup_savings_pipeline(name="F-RTS", advance_to="DRAFT")
        case = pipeline["case"]
        validate_success(
            api.decommission_compressor(pipeline["compressors"][0]["id"], CONTRACT_MGR)
        )

        resp = api.model_savings_case(case["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_RETROFIT_STALE, 409)
        case = validate_success(api.get_savings_case(case["id"], ENGINEER))
        assert case["savings_status"] == "DRAFT"
        assert case["retrofit_stale"] is True

    def test_decommission_cancels_project_and_flags_case(self, api):
        """PRD §3.2: "First, every RetrofitProject of the facility in `PROPOSED`,
        `APPROVED`, or `INSTALLED` whose `sequence_compressor_ids` contains this
        unit is cancelled to `CANCELLED`. Second, every SavingsCase referencing one
        of those freshly cancelled projects while its `savings_status` is `DRAFT` or
        `MODELED` has its `retrofit_stale` flag set to true."

        Design: Difficulty/transitive_cascade/decommission_cascade_to_savings_stale
        """
        pipeline = setup_savings_pipeline(name="F-DC", num_compressors=2, advance_to="MODELED")
        project = pipeline["project"]
        case = pipeline["case"]

        validate_success(
            api.decommission_compressor(pipeline["compressors"][0]["id"], CONTRACT_MGR)
        )

        project = validate_success(api.get_retrofit_project(project["id"], CONTRACT_MGR))
        assert project["status"] == "CANCELLED", "the decommission cascade must cancel the project"
        case = validate_success(api.get_savings_case(case["id"], CONTRACT_MGR))
        assert case["retrofit_stale"] is True, (
            "the case mutation is caused by the project cancellation"
        )
        assert case["savings_status"] == "MODELED", (
            "the staleness flag is set without moving the savings dimension"
        )

    def test_decommission_stale_case_cannot_open_measurement(self, api):
        """PRD §3.6: "Opening measurement moves a `MODELED` case to
        `MEASUREMENT_OPEN` and requires the retrofit project to have reached
        `ACCEPTED` (`ERR_RETROFIT_NOT_ACCEPTED`)."
        PRD §3.2: "First, every RetrofitProject of the facility in `PROPOSED`,
        `APPROVED`, or `INSTALLED` whose `sequence_compressor_ids` contains this
        unit is cancelled to `CANCELLED`."

        Design: Difficulty/transitive_cascade/decommission_cascade_to_savings_stale
        """
        pipeline = setup_savings_pipeline(name="F-DC2", num_compressors=2, advance_to="MODELED")
        case = pipeline["case"]
        validate_success(
            api.decommission_compressor(pipeline["compressors"][0]["id"], CONTRACT_MGR)
        )

        resp = api.open_measurement(case["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_RETROFIT_NOT_ACCEPTED, 409)
        case = validate_success(api.get_savings_case(case["id"], ENGINEER))
        assert case["savings_status"] == "MODELED"
