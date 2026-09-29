"""Simulation arithmetic, ramp constants, the spares waterfall and settlement money."""

from test_helpers import (
    DESIGN_ENGINEER,
    PROJECT_DIRECTOR,
    SITE_MANAGER,
    assert_performance_dispute,
    assert_simulation_run,
    assert_whole_cents,
    create_commissioning_ramp_payload,
    joint_retest_payload,
    make_completed_cutover,
    make_disputed_certificate,
    make_fat_passed_lot,
    make_linear_design,
    make_project,
    make_scheduled_window,
    make_segment,
    make_spare_part_line,
    make_staging_bay,
    provision_spares,
    read_certificate,
    read_project,
    read_segment,
    record_ramp,
    run_simulation,
    set_clock,
    spare_lines_by_part_no,
    validate_paginated,
    validate_success,
)


class TestDeterministicSimulationOnTheStandardLine:
    """Nameplate view of IB-01 1500 feeding TR-02 1400 at full share."""

    def test_the_run_pins_the_effective_rate_the_bottleneck_and_the_snapshot(self, api):
        """Both segments carry the whole flow, so the slower one sets the system rate.

        PRD §3.3: "Each segment implies a sustainable *system* rate: its
        `derated_capacity_cph` multiplied by 10000, divided by its `flow_share_bps`, with
        any fractional remainder discarded."

        Design: Corner/calculations/deterministic_simulation_computes_effective_throughput_and_bottleneck
        """
        design = make_linear_design(api)
        run = run_simulation(api, design["project"]["id"], "DETERMINISTIC_STEADY_STATE")

        assert_simulation_run(run)
        assert run["status"] == "COMPLETE"
        assert run["method"] == "DETERMINISTIC_STEADY_STATE"
        assert run["effective_throughput_cph"] == 1400
        assert run["bottleneck_segment_code"] == "TR-02"
        assert run["bottleneck_availability_pct"] == 95
        assert run["shortfall_cph"] == 0
        assert run["design_version_at_run"] == 4

    def test_the_deterministic_method_writes_nameplate_derated_capacities(self, api):
        """Availability never enters the arithmetic, so 1500 and 1400 survive intact.

        PRD §3.3: "If and only if the run's `method` is `DEGRADED_AVAILABILITY`, the
        working capacity is first multiplied by the segment's `availability_pct` and
        divided by 100, discarding any fractional remainder; under
        `DETERMINISTIC_STEADY_STATE` this substep is skipped entirely and
        `availability_pct` never enters the arithmetic at all, so every segment
        contributes its full nameplate capacity."

        Design: Corner/calculations/deterministic_simulation_computes_effective_throughput_and_bottleneck
        """
        design = make_linear_design(api)
        run_simulation(api, design["project"]["id"], "DETERMINISTIC_STEADY_STATE")

        upstream = read_segment(api, design["ib01"]["id"])
        downstream = read_segment(api, design["tr02"]["id"])
        assert upstream["flow_share_bps"] == 10000
        assert upstream["derated_capacity_cph"] == 1500
        assert downstream["flow_share_bps"] == 10000
        assert downstream["derated_capacity_cph"] == 1400
        assert design["link"]["split_share_bps"] == 10000


class TestDisconnectedSourcesTakeTheSystemMinimum:
    """Two unlinked sources each carry half the mix and each imply a system rate."""

    def _split_sources(self, api):
        project = make_project(
            api,
            customer_name="Harbourline Foods",
            facility_code="DC-MEM-02",
            customer_rep_user_id="cust-rep-88",
            required_throughput_cph=1250,
            service_tier="BASIC",
        )
        fast = make_segment(
            api,
            project["id"],
            segment_code="S-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=100,
            source_share_bps=5000,
        )
        slow = make_segment(
            api,
            project["id"],
            segment_code="S-02",
            equipment_class="ROLLER",
            rated_capacity_cph=600,
            availability_pct=100,
            source_share_bps=5000,
        )
        return project, fast, slow

    def test_the_smallest_grossed_up_rate_wins_and_the_shortfall_is_recorded(self, api):
        """600 cartons at half the flow supports 1200 system cartons, 50 short of 1250.

        PRD §3.3: "The run's `effective_throughput_cph` is the smallest of those
        per-segment system rates across all of the project's segments."

        Design: Corner/calculations/simulation_of_two_disconnected_sources_takes_the_system_minimum
        """
        project, _, _ = self._split_sources(api)
        run = run_simulation(api, project["id"], "DETERMINISTIC_STEADY_STATE")

        assert run["effective_throughput_cph"] == 1200
        assert run["bottleneck_segment_code"] == "S-02"
        assert run["bottleneck_availability_pct"] == 100
        assert run["shortfall_cph"] == 50

    def test_each_source_keeps_its_own_declared_share(self, api):
        """A source's flow share is its declared source share, not a derived split.

        PRD §3.3: "Each source segment's `flow_share_bps` is set to its own
        `source_share_bps`."

        Design: Corner/calculations/simulation_of_two_disconnected_sources_takes_the_system_minimum
        """
        project, fast, slow = self._split_sources(api)
        run_simulation(api, project["id"], "DETERMINISTIC_STEADY_STATE")

        stored_fast = read_segment(api, fast["id"])
        stored_slow = read_segment(api, slow["id"])
        assert stored_fast["flow_share_bps"] == 5000
        assert stored_slow["flow_share_bps"] == 5000
        assert stored_fast["derated_capacity_cph"] == 1500
        assert stored_slow["derated_capacity_cph"] == 600


class TestSimulationIgnoresForeignSegments:
    """A duplicate segment code on another project cannot poison the minimum."""

    def _two_projects(self, api):
        design = make_linear_design(api)
        other = make_project(
            api,
            customer_name="Vantage Parcel",
            facility_code="DC-DEN-01",
            customer_rep_user_id="cust-rep-88",
            required_throughput_cph=300,
            contract_base_cents=100_000_000,
            authorized_ceiling_cents=120_000_000,
            spares_budget_cents=1_000_000,
            service_tier="BASIC",
        )
        foreign = make_segment(
            api,
            other["id"],
            segment_code="TR-02",
            equipment_class="ROLLER",
            rated_capacity_cph=300,
            availability_pct=90,
            source_share_bps=10000,
        )
        return design, other, foreign

    def test_the_foreign_slower_segment_does_not_enter_the_minimum(self, api):
        """The 300 carton stranger belongs to another project, so 1400 still stands.

        PRD §3.3: "The run is computed in four steps over exactly the project's own
        rows — every conveyor segment whose `project_id` is this project, and every flow
        link whose `project_id` is this project."

        Design: Corner/calculations/simulation_excludes_segments_belonging_to_another_project
        """
        design, _, _ = self._two_projects(api)
        run = run_simulation(api, design["project"]["id"], "DETERMINISTIC_STEADY_STATE")

        assert run["effective_throughput_cph"] == 1400
        assert run["bottleneck_segment_code"] == "TR-02"
        assert read_segment(api, design["tr02"]["id"])["derated_capacity_cph"] == 1400

    def test_the_other_project_s_segment_is_left_completely_untouched(self, api):
        """Its derived fields stay at their creation zeros.

        PRD §3.3: "segments and links belonging to other projects are excluded
        entirely."

        Design: Corner/calculations/simulation_excludes_segments_belonging_to_another_project
        """
        design, _, foreign = self._two_projects(api)
        run_simulation(api, design["project"]["id"], "DETERMINISTIC_STEADY_STATE")

        stored = read_segment(api, foreign["id"])
        assert stored["flow_share_bps"] == 0
        assert stored["derated_capacity_cph"] == 0

        _, meta = validate_paginated(
            api.list_project_segments(design["project"]["id"], DESIGN_ENGINEER)
        )
        assert meta["total_count"] == 2


class TestRampSustainConstantsArePerLevel:
    """Thirty, sixty and one hundred and twenty minutes, read per step level."""

    def _commissioning(self, api):
        return make_completed_cutover(
            api,
            state=make_scheduled_window(
                api,
                state=make_fat_passed_lot(
                    api,
                    bay=make_staging_bay(api, bay_code="BAY-8", concurrent_capacity=2),
                    lot_code="LOT-800",
                    measured_cph=1313,
                    defect_count=0,
                ),
            ),
        )

    def test_one_minute_short_of_each_constant_fails_and_the_constant_itself_passes(self, api):
        """29 fails against 30 and 59 fails against 60, while 30 and 60 pass.

        PRD §3.7: "Its `min_sustained_minutes` is fixed by the level: a half-rate
        demonstration must hold for half an hour, recorded as 30 minutes; a
        three-quarter-rate demonstration must hold for a full hour, recorded as 60
        minutes; and the full-rate demonstration must hold for two full hours, recorded as
        120 minutes."

        Design: Corner/calculations/ramp_steps_apply_the_per_step_sustain_minute_constants
        """
        project_id = self._commissioning(api)["project"]["id"]

        short_half = record_ramp(api, project_id, 50, 700, 29)
        assert short_half["target_cph"] == 625
        assert short_half["min_sustained_minutes"] == 30
        assert short_half["verdict"] == "FAIL"

        exact_half = record_ramp(api, project_id, 50, 700, 30)
        assert exact_half["min_sustained_minutes"] == 30
        assert exact_half["verdict"] == "PASS"

        short_three_quarter = record_ramp(api, project_id, 75, 1000, 59)
        assert short_three_quarter["target_cph"] == 938
        assert short_three_quarter["min_sustained_minutes"] == 60
        assert short_three_quarter["verdict"] == "FAIL"

        exact_three_quarter = record_ramp(api, project_id, 75, 1000, 60)
        assert exact_three_quarter["min_sustained_minutes"] == 60
        assert exact_three_quarter["verdict"] == "PASS"

    def test_a_short_full_rate_step_is_a_created_failure_not_an_error(self, api):
        """119 minutes at the full rate is recorded as a FAIL with a 201 response.

        PRD §3.7: "The step's `verdict` is `PASS` when `measured_cph` is greater than or
        equal to `target_cph` **and** `sustained_minutes` is greater than or equal to
        `min_sustained_minutes`; otherwise it is `FAIL`."

        Design: Corner/calculations/ramp_steps_apply_the_per_step_sustain_minute_constants
        """
        project_id = self._commissioning(api)["project"]["id"]
        record_ramp(api, project_id, 50, 700, 30)
        record_ramp(api, project_id, 75, 1000, 60)

        full_rate = validate_success(
            api.create_commissioning_ramp(
                create_commissioning_ramp_payload(project_id, 100, 1250, 119), SITE_MANAGER
            ),
            expected_status=201,
        )
        assert full_rate["target_cph"] == 1250
        assert full_rate["min_sustained_minutes"] == 120
        assert full_rate["verdict"] == "FAIL"
        assert read_project(api, project_id)["acceptance_ready"] is False


class TestSparesWaterfallOrderAndBoundaryLine:
    """Critical before major, longest lead first, and the pool runs dry mid-line."""

    def _five_lines(self, api):
        project = make_project(
            api,
            facility_code="DC-ATL-05",
            spares_budget_cents=3_500_000,
        )
        for part_no, criticality, unit_cost, qty, lead in (
            ("SP-CRIT-1", "CRITICAL", 850_000, 2, 90),
            ("SP-MAJ-1", "MAJOR", 1_255_000, 2, 60),
            ("SP-MAJ-2", "MAJOR", 645_003, 2, 30),
            ("SP-MAJ-3", "MAJOR", 645_003, 2, 30),
            ("SP-MIN-1", "MINOR", 500_000, 4, 120),
        ):
            make_spare_part_line(
                api,
                project["id"],
                part_no=part_no,
                criticality=criticality,
                unit_cost_cents=unit_cost,
                min_stock_qty=qty,
                lead_time_days=lead,
            )
        return project

    def test_the_pool_drains_in_class_then_lead_time_order(self, api):
        """1,700,000 then 1,506,000, leaving 294,000 for the first thirty-day line.

        PRD §3.9: "Candidates are funded in a strict order: all `CRITICAL` lines before
        any `MAJOR` line; within the same class, the longer `lead_time_days` first,
        because a part that takes longest to replace is the one worth having on the shelf;
        and where lead times tie, the earlier `created_at` first."

        Design: Corner/calculations/spares_waterfall_funds_critical_first_and_partially_funds_the_boundary_line
        """
        project = self._five_lines(api)
        provision_spares(api, project["id"])
        lines = spare_lines_by_part_no(api, project["id"])

        assert lines["SP-CRIT-1"]["weighted_target_cents"] == 1_700_000
        assert lines["SP-CRIT-1"]["allocated_cents"] == 1_700_000
        assert lines["SP-CRIT-1"]["status"] == "ALLOCATED"

        assert lines["SP-MAJ-1"]["weighted_target_cents"] == 1_506_000
        assert lines["SP-MAJ-1"]["allocated_cents"] == 1_506_000
        assert lines["SP-MAJ-1"]["status"] == "ALLOCATED"

        assert lines["SP-MAJ-2"]["weighted_target_cents"] == 774_004
        assert lines["SP-MAJ-2"]["allocated_cents"] == 294_000
        assert lines["SP-MAJ-2"]["status"] == "PARTIAL"

        assert lines["SP-MAJ-3"]["weighted_target_cents"] == 774_004
        assert lines["SP-MAJ-3"]["allocated_cents"] == 0
        assert lines["SP-MAJ-3"]["status"] == "UNFUNDED"

    def test_the_minor_line_is_never_a_candidate_and_the_pool_conserves(self, api):
        """The longest lead time in the crib is a MINOR line and still gets nothing.

        PRD §3.9: "The candidate set is then every spare part line of that project that
        is `DRAFT` after the reset and whose `criticality` is `CRITICAL` or `MAJOR`;
        `MINOR` lines are excluded, keep `status` `DRAFT` and keep `allocated_cents` 0."

        Design: Corner/calculations/spares_waterfall_funds_critical_first_and_partially_funds_the_boundary_line
        """
        project = self._five_lines(api)
        after = provision_spares(api, project["id"])
        lines = spare_lines_by_part_no(api, project["id"])

        assert lines["SP-MIN-1"]["weighted_target_cents"] == 0
        assert lines["SP-MIN-1"]["allocated_cents"] == 0
        assert lines["SP-MIN-1"]["status"] == "DRAFT"

        assert after["spares_allocated_cents"] == 3_500_000
        assert after["spares_unallocated_cents"] == 0
        assert (
            after["spares_allocated_cents"] + after["spares_unallocated_cents"]
            == after["spares_budget_cents"]
        )
        assert_whole_cents(after["spares_allocated_cents"])


class TestDisputeFilingStoresBothVariants:
    """One claimed rate of 1100 priced under both contractual theories."""

    def test_the_nameplate_reading_is_clipped_to_the_five_percent_cap(self, api):
        """A twelve point shortfall raises 14,616,000, more than the cap allows.

        PRD §3.9: "A cap is computed alongside: `contract_value_cents` multiplied by 500
        basis points, five percent, divided by 10000 and rounded half up."

        Design: Corner/calculations/dispute_filing_computes_both_damages_variants_and_binds_the_declared_one
        """
        state = make_disputed_certificate(
            api, claimed_cph=1100, damages_basis="OBSERVED_AVAILABILITY"
        )
        dispute = state["dispute"]

        assert_performance_dispute(dispute)
        assert dispute["status"] == "OPEN"
        assert dispute["provisional_nameplate_cents"] == 12_180_000

    def test_the_observed_reading_grosses_1100_up_to_1157(self, api):
        """Seven points of surviving shortfall are worth 8,526,000 cents.

        PRD §3.9: "the basis rate is the observed rate multiplied by 100 and divided by
        the certificate's snapshotted `bottleneck_availability_pct`, discarding any
        fractional remainder; grossing the rate up this way shrinks, and frequently
        zeroes, the shortfall."

        Design: Corner/calculations/dispute_filing_computes_both_damages_variants_and_binds_the_declared_one
        """
        state = make_disputed_certificate(
            api, claimed_cph=1100, damages_basis="OBSERVED_AVAILABILITY"
        )
        dispute = state["dispute"]

        assert dispute["provisional_observed_cents"] == 8_526_000
        assert dispute["bound_provisional_cents"] == 8_526_000
        assert dispute["damages_basis"] == "OBSERVED_AVAILABILITY"
        assert dispute["final_damages_cents"] is None
        assert dispute["sla_credit_cents"] is None

        assert state["certificate"]["status"] == "DISPUTED"
        assert state["certificate"]["retention_amount_cents"] == 12_180_000
        assert state["certificate"]["retention_release_cents"] == 0
        project = read_project(api, state["project"]["id"])
        assert project["commercial_status"] == "DISPUTED"
        assert project["delivery_status"] == "ACCEPTED"


class TestJointRetestOnTheUpheldBranch:
    """Re-running the bound observed variant on 1200 zeroes the damages."""

    def _retested(self, api):
        state = make_disputed_certificate(
            api, claimed_cph=1100, damages_basis="OBSERVED_AVAILABILITY"
        )
        set_clock(api, "2026-08-10T22:00:00Z")
        state["retest"] = validate_success(
            api.joint_retest(state["dispute"]["id"], joint_retest_payload(1200), SITE_MANAGER)
        )
        return state

    def test_the_bound_variant_is_recomputed_and_collapses_to_zero(self, api):
        """1200 grossed up by 95 percent is 1263, above the 1250 requirement.

        PRD §3.9: "The retest re-evaluates the **bound variant only** — the one
        `damages_basis` selected at filing — on `retest_measured_cph` in place of
        `claimed_cph`, using exactly the arithmetic above, and writes the answer to
        `final_damages_cents`."

        Design: Corner/calculations/joint_retest_reconciles_the_bound_variant_into_a_zero_damages_upheld_settlement
        """
        state = self._retested(api)
        retest = state["retest"]

        assert retest["status"] == "RESOLVED_UPHELD"
        assert retest["retest_measured_cph"] == 1200
        assert retest["final_damages_cents"] == 0
        assert retest["sla_credit_cents"] == 0
        assert retest["bound_provisional_cents"] == 8_526_000
        assert retest["retest_by_user_id"] == SITE_MANAGER["X-User-ID"]
        assert retest["retest_recorded_at"].startswith("2026-08-10T22:00:00")

    def test_a_vindicated_integrator_releases_the_whole_retention(self, api):
        """The certificate is upheld and all 12,180,000 cents come back.

        PRD §3.9: "When the recomputed `final_damages_cents` is exactly 0, the integrator
        is vindicated: the dispute advances `OPEN → RESOLVED_UPHELD`, the certificate
        advances `DISPUTED → UPHELD` with its `retention_release_cents` set to the full
        `retention_amount_cents` and its `version` incremented, and the project's
        `commercial_status` becomes `SETTLED`."

        Design: Corner/calculations/joint_retest_reconciles_the_bound_variant_into_a_zero_damages_upheld_settlement
        """
        state = self._retested(api)

        certificate = read_certificate(api, state["certificate"]["id"])
        assert certificate["status"] == "UPHELD"
        assert certificate["retention_release_cents"] == 12_180_000
        assert certificate["retention_amount_cents"] == 12_180_000

        project = read_project(api, state["project"]["id"])
        assert project["commercial_status"] == "SETTLED"
        assert project["delivery_status"] == "ACCEPTED"


class TestJointRetestOnTheCreditedBranch:
    """A late nameplate retest nets damages and a response credit out of retention."""

    def _retested_late(self, api, at_iso8601="2026-08-11T00:01:00Z"):
        state = make_disputed_certificate(api, claimed_cph=1100, damages_basis="NAMEPLATE")
        set_clock(api, at_iso8601)
        state["retest"] = validate_success(
            api.joint_retest(state["dispute"]["id"], joint_retest_payload(1200), SITE_MANAGER)
        )
        return state

    def test_a_four_point_shortfall_and_a_late_response_are_both_priced(self, api):
        """4,872,000 of damages plus a 609,000 credit at 241 elapsed minutes.

        PRD §3.9: "If that elapsed count is **strictly greater** than the project's
        `response_sla_minutes`, then `sla_credit_cents` is the project's
        `contract_value_cents` multiplied by 25 basis points, one quarter of one percent,
        divided by 10000 and rounded half up to a whole cent; if the elapsed count is less
        than or exactly equal to the commitment, `sla_credit_cents` is 0."

        Design: Corner/calculations/sla_credit_and_final_damages_net_out_of_retention_on_the_revised_branch
        """
        state = self._retested_late(api)
        retest = state["retest"]

        assert retest["status"] == "RESOLVED_CREDITED"
        assert retest["final_damages_cents"] == 4_872_000
        assert retest["sla_credit_cents"] == 609_000
        assert retest["bound_provisional_cents"] == 12_180_000

    def test_both_deductions_come_out_of_the_released_retention(self, api):
        """12,180,000 less 4,872,000 less 609,000 releases 6,699,000 cents.

        PRD §3.9: "When `final_damages_cents` is greater than 0, the customer is
        credited: the dispute advances `OPEN → RESOLVED_CREDITED`, the certificate
        advances `DISPUTED → REVISED` with its `retention_release_cents` set to
        `retention_amount_cents` less `final_damages_cents` less `sla_credit_cents`,
        floored at 0 so that damages exceeding retention never produce a negative release,
        and its `version` incremented; and the project's `commercial_status` likewise
        becomes `SETTLED`, its terminal commercial value."

        Design: Corner/calculations/sla_credit_and_final_damages_net_out_of_retention_on_the_revised_branch
        """
        state = self._retested_late(api)

        certificate = read_certificate(api, state["certificate"]["id"])
        assert certificate["status"] == "REVISED"
        assert certificate["retention_release_cents"] == 6_699_000
        assert certificate["retention_amount_cents"] == 12_180_000

        project = read_project(api, state["project"]["id"])
        assert project["commercial_status"] == "SETTLED"
        assert project["delivery_status"] == "ACCEPTED"

    def test_a_retest_exactly_on_the_premium_commitment_earns_no_credit(self, api):
        """At exactly 240 elapsed minutes the strict comparison yields no credit.

        PRD §3.9: "The elapsed response time is the number of whole minutes between the
        dispute's `created_at` and the retest instant on the logical clock, taking the
        difference in seconds and discarding any remainder below a full minute."

        Design: Corner/calculations/retest_exactly_at_the_premium_sla_minute_yields_no_credit
        """
        state = self._retested_late(api, at_iso8601="2026-08-11T00:00:00Z")
        retest = state["retest"]

        assert retest["sla_credit_cents"] == 0
        assert retest["final_damages_cents"] == 4_872_000
        assert retest["status"] == "RESOLVED_CREDITED"
        assert read_project(api, state["project"]["id"])["response_sla_minutes"] == 240

    def test_the_uncredited_retention_release_keeps_the_full_damages_deduction(self, api):
        """Only the 4,872,000 of damages is withheld, so 7,308,000 is released.

        PRD §3.9: "Elapsed time is always measured on the logical clock, never on real
        time."

        Design: Corner/calculations/retest_exactly_at_the_premium_sla_minute_yields_no_credit
        """
        state = self._retested_late(api, at_iso8601="2026-08-11T00:00:00Z")

        certificate = read_certificate(api, state["certificate"]["id"])
        assert certificate["status"] == "REVISED"
        assert certificate["retention_release_cents"] == 7_308_000
        assert certificate["retention_amount_cents"] == 12_180_000
        assert read_project(api, state["project"]["id"])["commercial_status"] == "SETTLED"


class TestProvisioningIsRunByTheDirector:
    """The waterfall is a director act pinned on the project version."""

    def test_the_run_reports_the_conserved_pool_to_its_caller(self, api):
        """A single CRITICAL line consumes its whole weighted target.

        PRD §3.9: "When the pass is complete, the project's `spares_allocated_cents` is
        the sum of `allocated_cents` across the candidates and `spares_unallocated_cents`
        is the surviving remainder, so that `spares_budget_cents` always equals
        `spares_allocated_cents` plus `spares_unallocated_cents` after every run — the
        residual absorbs every fraction and no cent is created or destroyed."

        Design: Corner/calculations/spares_waterfall_funds_critical_first_and_partially_funds_the_boundary_line
        """
        project = make_project(api, facility_code="DC-ATL-06")
        make_spare_part_line(
            api,
            project["id"],
            part_no="SP-CRIT-9",
            criticality="CRITICAL",
            unit_cost_cents=850_000,
            min_stock_qty=2,
            lead_time_days=90,
        )

        after = provision_spares(api, project["id"], PROJECT_DIRECTOR)
        assert after["spares_allocated_cents"] == 1_700_000
        assert after["spares_unallocated_cents"] == 3_300_000
        lines = spare_lines_by_part_no(api, project["id"])
        assert lines["SP-CRIT-9"]["status"] == "ALLOCATED"
