"""Optimistic-concurrency pins, version accounting and immediate visibility."""

from test_helpers import (
    CUSTOMER_REP,
    PROJECT_DIRECTOR,
    SHOP_SUPERVISOR,
    SITE_MANAGER,
    ApiErrorId,
    assert_acceptance_certificate,
    assert_spares_ledger_conserved,
    create_acceptance_certificate_payload,
    create_fat_test_payload,
    make_completed_cutover,
    make_fat_passed_lot,
    make_flow_link,
    make_project,
    make_scheduled_window,
    make_segment,
    make_spare_part_line,
    make_staged_lot,
    make_staging_bay,
    make_submitted_change_order,
    read_change_order,
    read_lot,
    read_project,
    record_fat_test,
    record_ramp,
    review_decision_payload,
    run_simulation,
    spare_lines_by_part_no,
    spares_provisioning_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheChangeOrderPinIsTheProjectVersion:
    """An unrelated spare-part-line write supersedes the version the rep read."""

    def _order_with_a_superseded_pin(self, api):
        project = make_project(api, facility_code="DC-ATL-40")
        order = make_submitted_change_order(
            api,
            project["id"],
            title="Scanner tunnel upgrade",
            scope_delta_cph=0,
            price_delta_cents=10_000_000,
            schedule_delta_days=0,
        )
        pinned = read_project(api, project["id"], CUSTOMER_REP)["version"]
        make_spare_part_line(
            api,
            project["id"],
            part_no="BLT-1500-01",
            criticality="CRITICAL",
            unit_cost_cents=850_000,
            min_stock_qty=2,
            lead_time_days=90,
        )
        return {"project": project, "order": order, "pinned": pinned}

    def test_the_decision_on_the_pre_insert_version_is_refused_with_412(self, api):
        """The spare-part line moved the project version and the pin no longer matches.

        PRD §2.7: "Recording a customer decision on a change order requires
        `expected_project_version` carrying the client's last observed `version` of the
        governing project."

        Design: Corner/complexity_layers/change_order_decision_on_a_superseded_project_version_returns_412
        """
        state = self._order_with_a_superseded_pin(api)

        response = api.review_change_order(
            state["order"]["id"],
            review_decision_payload("APPROVE", state["pinned"]),
            CUSTOMER_REP,
        )
        validate_error(response, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, expected_status=412)

        assert read_change_order(api, state["order"]["id"])["status"] == "SUBMITTED"
        after = read_project(api, state["project"]["id"], CUSTOMER_REP)
        assert after["contract_value_cents"] == 243_600_000
        assert after["escalation_fee_cents"] == 3_600_000
        assert after["version"] == state["pinned"] + 1

    def test_the_identical_decision_on_the_refreshed_version_approves(self, api):
        """Only the pinned integer changes, and the repricing then runs in full.

        PRD §2.7: "If it does not equal that project's current `version`, the decision is
        rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/change_order_decision_on_a_superseded_project_version_returns_412
        """
        state = self._order_with_a_superseded_pin(api)
        api.review_change_order(
            state["order"]["id"],
            review_decision_payload("APPROVE", state["pinned"]),
            CUSTOMER_REP,
        )

        refreshed = read_project(api, state["project"]["id"], CUSTOMER_REP)["version"]
        decided = validate_success(
            api.review_change_order(
                state["order"]["id"],
                review_decision_payload("APPROVE", refreshed),
                CUSTOMER_REP,
            )
        )
        assert decided["status"] == "APPROVED"

        after = read_project(api, state["project"]["id"], CUSTOMER_REP)
        assert after["contract_value_cents"] == 253_750_000
        assert after["escalation_fee_cents"] == 3_750_000
        assert after["commercial_status"] == "CLEAN"


class TestTheProvisioningPinIsTheProjectVersion:
    """The second part line is exactly the event the pool guard watches for."""

    def _pool_with_a_late_line(self, api):
        project = make_project(api, facility_code="DC-ATL-41")
        make_spare_part_line(
            api,
            project["id"],
            part_no="BLT-1500-01",
            criticality="CRITICAL",
            unit_cost_cents=850_000,
            min_stock_qty=2,
            lead_time_days=90,
        )
        pinned = read_project(api, project["id"])["version"]
        make_spare_part_line(
            api,
            project["id"],
            part_no="RLR-1400-02",
            criticality="MAJOR",
            unit_cost_cents=1_255_000,
            min_stock_qty=2,
            lead_time_days=60,
        )
        return {"project": project, "pinned": pinned}

    def test_a_run_pinned_before_the_second_line_allocates_nothing(self, api):
        """Both lines stay DRAFT at 0 and the whole budget stays unallocated.

        PRD §2.7: "Running the spares waterfall requires `expected_project_version`
        carrying the client's last observed `version` of the target project, and a mismatch
        is likewise rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/spares_provisioning_rerun_on_a_stale_project_version_returns_412
        """
        state = self._pool_with_a_late_line(api)

        response = api.run_spares_provisioning(
            state["project"]["id"], spares_provisioning_payload(state["pinned"]), PROJECT_DIRECTOR
        )
        validate_error(response, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, expected_status=412)

        lines = spare_lines_by_part_no(api, state["project"]["id"])
        assert lines["BLT-1500-01"]["status"] == "DRAFT"
        assert lines["BLT-1500-01"]["allocated_cents"] == 0
        assert lines["RLR-1400-02"]["status"] == "DRAFT"
        assert lines["RLR-1400-02"]["allocated_cents"] == 0

        after = read_project(api, state["project"]["id"])
        assert after["spares_allocated_cents"] == 0
        assert after["spares_unallocated_cents"] == 5_000_000

    def test_the_refreshed_run_funds_both_lines_at_their_weighted_targets(self, api):
        """1700000 at full cover plus 1506000 at sixty percent leaves 1794000 in the pool.

        PRD §3.9: "The coverage factors are the policy: a `CRITICAL` line is covered at
        10000 basis points, the full requested amount; a `MAJOR` line at 6000 basis points,
        sixty percent of its request; and a `MINOR` line at 0 basis points, which is to say
        a minor line's `weighted_target_cents` is 0 at creation and it is never funded at
        all."

        Design: Corner/complexity_layers/spares_provisioning_rerun_on_a_stale_project_version_returns_412
        """
        state = self._pool_with_a_late_line(api)
        api.run_spares_provisioning(
            state["project"]["id"], spares_provisioning_payload(state["pinned"]), PROJECT_DIRECTOR
        )

        refreshed = read_project(api, state["project"]["id"])["version"]
        validate_success(
            api.run_spares_provisioning(
                state["project"]["id"], spares_provisioning_payload(refreshed), PROJECT_DIRECTOR
            )
        )

        after = read_project(api, state["project"]["id"])
        assert after["spares_allocated_cents"] == 3_206_000
        assert after["spares_unallocated_cents"] == 1_794_000
        assert_spares_ledger_conserved(after)

        lines = spare_lines_by_part_no(api, state["project"]["id"])
        critical = lines["BLT-1500-01"]
        major = lines["RLR-1400-02"]
        assert critical["requested_cents"] == 1_700_000
        assert critical["weighted_target_cents"] == 1_700_000
        assert critical["allocated_cents"] == 1_700_000
        assert critical["status"] == "ALLOCATED"
        assert major["requested_cents"] == 2_510_000
        assert major["weighted_target_cents"] == 1_506_000
        assert major["allocated_cents"] == 1_506_000
        assert major["status"] == "ALLOCATED"


class TestTheFatPinOutranksTheLotState:
    """The failing first test broke the pin and the state at once; the pin answers."""

    def _failed_first_attempt(self, api):
        state = make_staged_lot(
            api,
            bay=make_staging_bay(api, bay_code="BAY-42", concurrent_capacity=1),
            segment_codes=["IB-01", "TR-02"],
            lot_code="LOT-4200",
        )
        state["staged_version"] = state["lot"]["version"]
        state["first_test"] = record_fat_test(
            api, state["lot"], measured_cph=1000, defect_count=3
        )
        state["lot"] = read_lot(api, state["lot"]["id"])
        return state

    def test_the_stale_pin_reports_412_rather_than_the_lot_state(self, api):
        """The lot is FAT_FAILED and the pin is one behind, and band 7 wins over band 8.

        PRD §2.12: "Because version pinning sits at band 7 and state admissibility at band
        8, a caller holding a stale version on a change order in the wrong state receives
        `ERR_STALE_PROJECT_VERSION` rather than `ERR_CHANGE_ORDER_INVALID_STATE`."

        Design: Corner/complexity_layers/fat_test_on_a_stale_lot_version_returns_412_before_the_state_check
        """
        state = self._failed_first_attempt(api)
        assert state["lot"]["status"] == "FAT_FAILED"
        assert state["lot"]["version"] == state["staged_version"] + 1

        response = api.create_fat_test(
            create_fat_test_payload(
                state["lot"]["id"], state["staged_version"], measured_cph=1313, defect_count=0
            ),
            SHOP_SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_STALE_LOT_VERSION.value, expected_status=412)

    def test_the_refused_test_records_nothing_on_the_history(self, api):
        """One attempt stands, still FAIL, and the attempt counter has not moved.

        PRD §3.5: "Recording a test always increments the lot's `fat_attempt_count` by 1
        and the lot's `version` by 1."

        Design: Corner/complexity_layers/fat_test_on_a_stale_lot_version_returns_412_before_the_state_check
        """
        state = self._failed_first_attempt(api)
        api.create_fat_test(
            create_fat_test_payload(
                state["lot"]["id"], state["staged_version"], measured_cph=1313, defect_count=0
            ),
            SHOP_SUPERVISOR,
        )

        lot = read_lot(api, state["lot"]["id"])
        assert lot["status"] == "FAT_FAILED"
        assert lot["fat_attempt_count"] == 1
        assert lot["version"] == state["staged_version"] + 1

        tests, meta = validate_paginated(api.list_fat_tests(lot["id"], SHOP_SUPERVISOR))
        assert meta["total_count"] == 1
        assert tests[0]["id"] == state["first_test"]["id"]
        assert tests[0]["result"] == "FAIL"
        assert tests[0]["attempt_no"] == 1
        assert tests[0]["target_cph_at_test"] == 1313


class TestProjectVersionAdvancesOnlyOnDeclaredWrites:
    """Two segments and a link make 4; a simulation run adds nothing."""

    def _one_write_at_a_time(self, api):
        project = make_project(api, facility_code="DC-ATL-43")
        ib01 = make_segment(
            api,
            project["id"],
            segment_code="IB-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=10000,
        )
        tr02 = make_segment(
            api,
            project["id"],
            segment_code="TR-02",
            equipment_class="ROLLER",
            rated_capacity_cph=1400,
            availability_pct=95,
            source_share_bps=None,
        )
        make_flow_link(api, project["id"], ib01["id"], tr02["id"], 10000)
        return project

    def test_the_simulation_run_leaves_the_project_version_alone(self, api):
        """The run creates its own row and merely reads the project it measures.

        PRD §2.4: "Because a single request routinely mutates several resources, version
        accounting is stated per resource rather than per request."

        Design: Corner/complexity_layers/project_version_advances_only_on_writes_that_declare_it
        """
        project = self._one_write_at_a_time(api)
        assert project["version"] == 1

        before = read_project(api, project["id"])
        assert before["version"] == 4
        assert before["design_version"] == 4

        run = run_simulation(api, project["id"], "DEGRADED_AVAILABILITY")
        assert run["design_version_at_run"] == 4

        after = read_project(api, project["id"])
        assert after["version"] == 4
        assert after["design_version"] == 4

    def test_the_freeze_and_the_spare_line_each_add_exactly_one(self, api):
        """Version 4 becomes 5 on the freeze and 6 on the part line, with no funding yet.

        PRD §3.4: "A successful freeze writes `design_frozen_at` from the logical clock and
        increments the project's `version` by 1."

        Design: Corner/complexity_layers/project_version_advances_only_on_writes_that_declare_it
        """
        project = self._one_write_at_a_time(api)
        run_simulation(api, project["id"], "DEGRADED_AVAILABILITY")

        frozen = validate_success(api.design_freeze(project["id"], PROJECT_DIRECTOR))
        assert frozen["version"] == 5
        assert frozen["delivery_status"] == "DESIGN_FROZEN"

        make_spare_part_line(
            api,
            project["id"],
            part_no="BLT-1500-01",
            criticality="CRITICAL",
            unit_cost_cents=850_000,
            min_stock_qty=2,
            lead_time_days=90,
        )

        after = read_project(api, project["id"])
        assert after["version"] == 6
        assert after["spares_allocated_cents"] == 0
        assert after["spares_unallocated_cents"] == 5_000_000
        assert spare_lines_by_part_no(api, project["id"])["BLT-1500-01"]["status"] == "DRAFT"


class TestCutoverAndRampEffectsAreVisibleImmediately:
    """No reread delay: the read straight after each write already sees everything."""

    def _cutover_ready(self, api):
        return make_scheduled_window(
            api,
            state=make_fat_passed_lot(
                api,
                bay=make_staging_bay(api, bay_code="BAY-50", concurrent_capacity=1),
                segment_codes=["IB-01", "TR-02"],
                lot_code="LOT-5000",
                measured_cph=1313,
                defect_count=0,
            ),
        )

    def test_the_completion_call_alone_moves_the_zone_the_ledger_and_the_state(self, api):
        """One request flips the zone, transfers the share and bubbles the project up.

        PRD §3.6: "On success the window advances `IN_PROGRESS → COMPLETED` with
        `closed_at` stamped and its `version` incremented; the zone advances
        `CUTOVER_IN_PROGRESS → CUTOVER_COMPLETE`; the zone's share transfers out of
        `in_transition_share_bps` into `cutover_share_bps`; the installed lot advances
        `FAT_PASSED → INSTALLED` with its own `version` incremented; and if every site zone
        of the project has now reached `CUTOVER_COMPLETE`, the project bubbles up from
        `CUTOVER` to `COMMISSIONING`."

        Design: Corner/consistency_model/cutover_completion_and_the_final_ramp_are_visible_without_any_reread_delay
        """
        state = make_completed_cutover(api, state=self._cutover_ready(api))
        assert state["window"]["status"] == "COMPLETED"

        project = state["project"]
        assert project["delivery_status"] == "COMMISSIONING"
        assert project["cutover_share_bps"] == 10000
        assert project["in_transition_share_bps"] == 0
        assert project["legacy_share_bps"] == 0
        assert project["acceptance_ready"] is False
        assert state["lot"]["status"] == "INSTALLED"

        zones = validate_success(api.list_site_zones(project["id"], SITE_MANAGER))
        assert [zone["ops_status"] for zone in zones] == ["CUTOVER_COMPLETE"]

    def test_acceptance_ready_is_true_on_the_read_after_the_full_rate_ramp(self, api):
        """The lower steps leave it false and issuance succeeds on the very next call.

        PRD §3.1: "That last flag is a derived predicate rather than a stored decision: it
        is true exactly when the project has a passing commissioning ramp step for each of
        the three demonstration levels 50, 75 and 100, **and** every site zone of the
        project has reached `CUTOVER_COMPLETE`."

        Design: Corner/consistency_model/cutover_completion_and_the_final_ramp_are_visible_without_any_reread_delay
        """
        state = make_completed_cutover(api, state=self._cutover_ready(api))
        project_id = state["project"]["id"]

        record_ramp(api, project_id, 50, 700, 30)
        assert read_project(api, project_id)["acceptance_ready"] is False
        record_ramp(api, project_id, 75, 1000, 60)
        assert read_project(api, project_id)["acceptance_ready"] is False
        record_ramp(api, project_id, 100, 1260, 120)
        assert read_project(api, project_id)["acceptance_ready"] is True

        certificate = validate_success(
            api.create_acceptance_certificate(
                create_acceptance_certificate_payload(project_id), PROJECT_DIRECTOR
            ),
            expected_status=201,
        )
        assert_acceptance_certificate(certificate)
        assert certificate["accepted_throughput_cph"] == 1260
        assert certificate["status"] == "ISSUED"
        assert read_project(api, project_id)["delivery_status"] == "ACCEPTED"
