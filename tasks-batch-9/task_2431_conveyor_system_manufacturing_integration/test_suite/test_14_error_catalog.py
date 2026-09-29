"""Every catalog code that the design index names, triggered on its own terms."""

from test_helpers import (
    CUSTOMER_REP,
    DESIGN_ENGINEER,
    NON_EXISTENT_UUID,
    PROJECT_DIRECTOR,
    SHOP_SUPERVISOR,
    SITE_MANAGER,
    TEST_INSTANTS,
    ApiErrorId,
    assert_acceptance_certificate,
    build_user_headers,
    create_acceptance_certificate_payload,
    create_commissioning_ramp_payload,
    create_cutover_window_payload,
    create_fabrication_lot_payload,
    create_performance_dispute_payload,
    create_segment_payload,
    create_spare_part_line_payload,
    decide_change_order,
    fail_fat_attempt,
    joint_retest_payload,
    make_completed_cutover,
    make_disputed_certificate,
    make_fat_passed_lot,
    make_frozen_project,
    make_planned_lot,
    make_project,
    make_project_director_headers,
    make_scheduled_window,
    make_site_zone,
    make_staging_bay,
    make_submitted_change_order,
    read_certificate,
    read_lot,
    read_project,
    read_window,
    record_ramp,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _commissioned(api, bay_code, lot_code, ramps):
    """Standard project driven to COMMISSIONING, then given the supplied ramp steps."""
    state = make_completed_cutover(
        api,
        state=make_scheduled_window(
            api,
            state=make_fat_passed_lot(
                api,
                bay=make_staging_bay(api, bay_code=bay_code, concurrent_capacity=1),
                segment_codes=["IB-01", "TR-02"],
                lot_code=lot_code,
                measured_cph=1313,
                defect_count=0,
            ),
        ),
    )
    state["ramps"] = [
        record_ramp(api, state["project"]["id"], step_pct, measured_cph, sustained_minutes)
        for step_pct, measured_cph, sustained_minutes in ramps
    ]
    state["project"] = read_project(api, state["project"]["id"])
    return state


class TestUnknownPathIdentifiersAreTypedPerEntity:
    """One unknown UUID in seven path positions yields seven different codes."""

    def test_each_path_position_reports_its_own_not_found_code(self, api):
        """A generic 404 would be wrong: the code names the entity type that failed.

        PRD §2.11: "Each resource type has its own not-found code: a project identifier
        that does not resolve yields `ERR_PROJECT_NOT_FOUND`, a segment identifier
        `ERR_SEGMENT_NOT_FOUND`, a flow-link identifier `ERR_FLOW_LINK_NOT_FOUND`, a
        fabrication-lot identifier `ERR_LOT_NOT_FOUND`, a cutover-window identifier
        `ERR_WINDOW_NOT_FOUND`, a change-order identifier `ERR_CHANGE_ORDER_NOT_FOUND`,
        an acceptance-certificate identifier `ERR_CERTIFICATE_NOT_FOUND` and a
        performance-dispute identifier `ERR_DISPUTE_NOT_FOUND`."

        Design: Corner/errors/unknown_path_ids_each_return_their_entity_specific_not_found_code
        """
        validate_error(
            api.get_project(NON_EXISTENT_UUID, PROJECT_DIRECTOR),
            ApiErrorId.ERR_PROJECT_NOT_FOUND.value,
        )
        validate_error(
            api.get_flow_link(NON_EXISTENT_UUID, DESIGN_ENGINEER),
            ApiErrorId.ERR_FLOW_LINK_NOT_FOUND.value,
        )
        validate_error(
            api.get_fabrication_lot(NON_EXISTENT_UUID, SHOP_SUPERVISOR),
            ApiErrorId.ERR_LOT_NOT_FOUND.value,
        )
        validate_error(
            api.get_cutover_window(NON_EXISTENT_UUID, SITE_MANAGER),
            ApiErrorId.ERR_WINDOW_NOT_FOUND.value,
        )
        validate_error(
            api.get_change_order(NON_EXISTENT_UUID, PROJECT_DIRECTOR),
            ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND.value,
        )
        validate_error(
            api.get_acceptance_certificate(NON_EXISTENT_UUID, PROJECT_DIRECTOR),
            ApiErrorId.ERR_CERTIFICATE_NOT_FOUND.value,
        )
        validate_error(
            api.joint_retest(NON_EXISTENT_UUID, joint_retest_payload(1200), SITE_MANAGER),
            ApiErrorId.ERR_DISPUTE_NOT_FOUND.value,
        )


class TestUnknownBodyIdentifiersAreTypedPerField:
    """The body reference band resolves each field against its own table."""

    def test_each_body_field_reports_its_own_not_found_code(self, api):
        """project_id, staging_bay_id and site_zone_id fail in three different ways.

        PRD §2.11: "Identifiers supplied in a request body are resolved with the same
        per-type codes: `project_id` yields `ERR_PROJECT_NOT_FOUND`, `from_segment_id` or
        `to_segment_id` yields `ERR_SEGMENT_NOT_FOUND`, `staging_bay_id` yields
        `ERR_STAGING_BAY_NOT_FOUND`, `site_zone_id` yields `ERR_ZONE_NOT_FOUND`,
        `fabrication_lot_id` yields `ERR_LOT_NOT_FOUND` and `acceptance_certificate_id`
        yields `ERR_CERTIFICATE_NOT_FOUND`."

        Design: Corner/errors/unknown_body_ids_each_return_their_entity_specific_not_found_code
        """
        state = make_planned_lot(
            api,
            bay=make_staging_bay(api, bay_code="BAY-16", concurrent_capacity=1),
            segment_codes=["IB-01", "TR-02"],
            lot_code="LOT-1600",
        )
        project_id = state["project"]["id"]

        validate_error(
            api.create_spare_part_line(
                create_spare_part_line_payload(
                    NON_EXISTENT_UUID,
                    part_no="SP-X",
                    criticality="CRITICAL",
                    unit_cost_cents=100_000,
                    min_stock_qty=1,
                    lead_time_days=10,
                ),
                PROJECT_DIRECTOR,
            ),
            ApiErrorId.ERR_PROJECT_NOT_FOUND.value,
        )
        validate_error(
            api.create_fabrication_lot(
                create_fabrication_lot_payload(
                    project_id, NON_EXISTENT_UUID, ["IB-01"], lot_code="LOT-1601"
                ),
                SHOP_SUPERVISOR,
            ),
            ApiErrorId.ERR_STAGING_BAY_NOT_FOUND.value,
        )
        validate_error(
            api.create_cutover_window(
                create_cutover_window_payload(project_id, NON_EXISTENT_UUID, state["lot"]["id"]),
                SITE_MANAGER,
            ),
            ApiErrorId.ERR_ZONE_NOT_FOUND.value,
        )

        _, lot_meta = validate_paginated(
            api.list_fabrication_lots(SHOP_SUPERVISOR, params={"project_id": project_id})
        )
        assert lot_meta["total_count"] == 1
        _, window_meta = validate_paginated(
            api.list_cutover_windows(SITE_MANAGER, params={"project_id": project_id})
        )
        assert window_meta["total_count"] == 0


class TestAnUndeclaredRoleDiesAtTheHeaderBand:
    """Band 1 runs before existence, so the unknown project id is never reported."""

    def test_an_auditor_role_is_unauthenticated(self, api):
        """Auditor is not one of the five declared names, so this is 401 and not 404.

        PRD §2.1: "If either header is absent, or if `X-User-Role` is not exactly one of
        the five role names below, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401) before any other consideration."

        Design: Corner/errors/unknown_role_header_returns_unauthenticated
        """
        response = api.get_project(NON_EXISTENT_UUID, build_user_headers("aud-001", "Auditor"))
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestTheDesignSurfaceClosesAtTheFreeze:
    """Once DESIGN is left the graph is sealed, and the rejection changes nothing."""

    def test_adding_a_segment_after_the_freeze_is_refused(self, api):
        """The frozen project keeps its four design versions and its complete run.

        PRD §3.2: "Segment creation is only legal while the project's `delivery_status` is
        `DESIGN`; attempting it in any other delivery state is rejected with
        `ERR_PROJECT_NOT_IN_DESIGN`, and re-using a `segment_code` already present on the
        same project is rejected with `ERR_DUPLICATE_SEGMENT_CODE`."

        Design: Corner/errors/segment_creation_after_design_freeze_returns_project_not_in_design
        """
        frozen = make_frozen_project(api)
        project_id = frozen["project"]["id"]

        response = api.create_segment(
            create_segment_payload(
                project_id,
                segment_code="OB-09",
                equipment_class="SORTATION",
                rated_capacity_cph=1100,
                availability_pct=93,
                source_share_bps=None,
            ),
            DESIGN_ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_NOT_IN_DESIGN.value)

        after = read_project(api, project_id)
        assert after["delivery_status"] == "DESIGN_FROZEN"
        assert after["design_version"] == 4

        runs, run_meta = validate_paginated(api.list_simulation_runs(project_id, DESIGN_ENGINEER))
        assert run_meta["total_count"] == 1
        assert runs[0]["status"] == "COMPLETE"

        _, segment_meta = validate_paginated(
            api.list_project_segments(project_id, DESIGN_ENGINEER)
        )
        assert segment_meta["total_count"] == 2


class TestTheRampNeedsACommissioningProject:
    """The project-state gate is reached before the ramp sequencing gate."""

    def test_a_ramp_recorded_in_design_is_refused(self, api):
        """A first half-rate step against a brand-new project is a state error, not a sequence one.

        PRD §3.7: "A step recorded while the project's `delivery_status` is anything other
        than `COMMISSIONING` is rejected with `ERR_PROJECT_NOT_COMMISSIONING`."

        Design: Corner/errors/commissioning_ramp_in_design_returns_project_not_commissioning
        """
        project = make_project(api, facility_code="DC-ATL-15")

        response = api.create_commissioning_ramp(
            create_commissioning_ramp_payload(project["id"], 50, 700, 30), SITE_MANAGER
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_NOT_COMMISSIONING.value)

        after = read_project(api, project["id"])
        assert after["acceptance_ready"] is False
        assert after["version"] == 1
        _, meta = validate_paginated(
            api.list_commissioning_ramps(project["id"], SITE_MANAGER)
        )
        assert meta["total_count"] == 0


class TestAScrappedLotAdmitsNoOperations:
    """Three strikes closes the traveller with its own dedicated code."""

    def test_a_fourth_release_after_three_failures_is_refused(self, api):
        """The lot is SCRAPPED, so this is ERR_LOT_SCRAPPED and not the generic state error.

        PRD §3.4: "Any lot operation attempted after the lot has reached `SCRAPPED` is
        rejected with `ERR_LOT_SCRAPPED`."

        Design: Corner/errors/start_fabrication_on_a_scrapped_lot_returns_lot_scrapped
        """
        state = make_planned_lot(
            api,
            bay=make_staging_bay(api, bay_code="BAY-17", concurrent_capacity=1),
            segment_codes=["IB-01", "TR-02"],
            lot_code="LOT-1700",
        )
        fail_fat_attempt(api, state, measured_cph=1000, defect_count=0)
        fail_fat_attempt(api, state, measured_cph=1000, defect_count=0)
        third = fail_fat_attempt(api, state, measured_cph=1000, defect_count=0)

        response = api.start_fabrication(state["lot"]["id"], SHOP_SUPERVISOR)
        validate_error(response, ApiErrorId.ERR_LOT_SCRAPPED.value)

        lot = read_lot(api, state["lot"]["id"])
        assert lot["status"] == "SCRAPPED"
        assert lot["fat_attempt_count"] == 3
        assert lot["fat_target_cph"] == 1313
        assert third["attempt_no"] == 3
        assert third["result"] == "FAIL"

        tests, meta = validate_paginated(api.list_fat_tests(lot["id"], SHOP_SUPERVISOR))
        assert meta["total_count"] == 3
        assert [test["attempt_no"] for test in tests] == [1, 2, 3]


class TestTheRampIsStrictlySequenced:
    """A passing measurement at the wrong level unlocks nothing and persists nothing."""

    def test_three_quarter_rate_without_a_passing_half_rate_is_refused(self, api):
        """1000 cph would have passed the 938 target, but 50 was never demonstrated.

        PRD §3.7: "A step may only be recorded once every lower level that precedes it —
        50 for a three-quarter demonstration, and both 50 and 75 for a full-rate
        demonstration — already has a ramp step whose `verdict` is `PASS`."

        Design: Corner/errors/ramp_step_seventy_five_before_step_fifty_returns_ramp_sequence_violation
        """
        state = _commissioned(api, "BAY-18", "LOT-1800", ramps=[])
        project_id = state["project"]["id"]
        assert state["project"]["delivery_status"] == "COMMISSIONING"

        response = api.create_commissioning_ramp(
            create_commissioning_ramp_payload(project_id, 75, 1000, 60), SITE_MANAGER
        )
        validate_error(response, ApiErrorId.ERR_RAMP_SEQUENCE_VIOLATION.value)

        _, meta = validate_paginated(api.list_commissioning_ramps(project_id, SITE_MANAGER))
        assert meta["total_count"] == 0
        after = read_project(api, project_id)
        assert after["delivery_status"] == "COMMISSIONING"
        assert after["acceptance_ready"] is False


class TestTheWindowIntervalIsHalfOpen:
    """Every other precondition holds; only the clock is wrong."""

    def _due_window(self, api):
        return make_scheduled_window(
            api,
            state=make_fat_passed_lot(
                api,
                bay=make_staging_bay(api, bay_code="BAY-19", concurrent_capacity=1),
                segment_codes=["IB-01", "TR-02"],
                lot_code="LOT-1900",
                measured_cph=1313,
                defect_count=0,
            ),
        )

    def test_starting_an_hour_early_is_refused(self, api):
        """18:00 is before start_utc, so the appointment cannot be brought forward.

        PRD §3.6: "The logical clock must be at or after `start_utc` and strictly before
        `end_utc`, otherwise `ERR_WINDOW_NOT_DUE`; an appointment cannot be started early
        and cannot be started once it has lapsed."

        Design: Corner/errors/window_start_outside_the_half_open_interval_returns_window_not_due
        """
        state = self._due_window(api)
        set_clock(api, "2026-08-10T18:00:00Z")

        response = api.start_cutover_window(state["window"]["id"], SITE_MANAGER)
        validate_error(response, ApiErrorId.ERR_WINDOW_NOT_DUE.value)

        window = read_window(api, state["window"]["id"])
        assert window["status"] == "SCHEDULED"
        assert window["started_at"] is None
        assert window["version"] == 1
        assert read_lot(api, state["lot"]["id"])["status"] == "FAT_PASSED"

        project = read_project(api, state["project"]["id"])
        assert project["legacy_share_bps"] == 10000
        assert project["delivery_status"] == "IN_FABRICATION"

    def test_starting_at_end_utc_is_refused(self, api):
        """The closing instant is excluded, which is what makes the interval half-open.

        PRD §3.6: "Scheduling one names the `project_id`, the zone taken out of legacy
        service in `site_zone_id`, the lot to be installed in `fabrication_lot_id`, and the
        appointment itself as `start_utc` and `end_utc`, the latter strictly after the
        former and the interval treated as half-open."

        Design: Corner/errors/window_start_outside_the_half_open_interval_returns_window_not_due
        """
        state = self._due_window(api)
        set_clock(api, TEST_INSTANTS["WINDOW_END_UTC"])

        response = api.start_cutover_window(state["window"]["id"], SITE_MANAGER)
        validate_error(response, ApiErrorId.ERR_WINDOW_NOT_DUE.value)

        window = read_window(api, state["window"]["id"])
        assert window["status"] == "SCHEDULED"
        assert window["started_at"] is None
        zones = validate_success(api.list_site_zones(state["project"]["id"], SITE_MANAGER))
        assert [zone["ops_status"] for zone in zones] == ["LIVE_LEGACY"]


class TestAZoneInCutoverRefusesASecondWindow:
    """The zone's posture fails, not the lot's and not the clock's."""

    def test_the_second_window_on_the_busy_zone_is_refused(self, api):
        """A second FAT_PASSED lot and a due clock still cannot re-enter the same zone.

        PRD §3.6: "Only then are its relatives consulted — the referenced lot must be in
        `FAT_PASSED`, otherwise `ERR_LOT_NOT_FAT_PASSED`, and the referenced zone must be
        in `LIVE_LEGACY`, otherwise `ERR_ZONE_NOT_READY`."

        Design: Corner/errors/window_start_on_a_zone_already_in_cutover_returns_zone_not_ready
        """
        frozen = make_frozen_project(api)
        bay = make_staging_bay(api, bay_code="BAY-20", concurrent_capacity=2)
        first = make_fat_passed_lot(
            api,
            frozen=frozen,
            bay=bay,
            segment_codes=["IB-01", "TR-02"],
            lot_code="LOT-2000",
            measured_cph=1313,
            defect_count=0,
        )
        second = make_fat_passed_lot(
            api,
            frozen=frozen,
            bay=bay,
            segment_codes=["TR-02"],
            lot_code="LOT-2001",
            measured_cph=1313,
            defect_count=0,
        )
        project_id = frozen["project"]["id"]
        zone = make_site_zone(api, project_id, zone_code="Z-INBOUND", throughput_share_bps=10000)

        first_window = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(project_id, zone["id"], first["lot"]["id"]),
                SITE_MANAGER,
            ),
            expected_status=201,
        )
        second_window = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(
                    project_id,
                    zone["id"],
                    second["lot"]["id"],
                    start_utc="2026-08-11T19:00:00Z",
                    end_utc="2026-08-11T23:00:00Z",
                ),
                SITE_MANAGER,
            ),
            expected_status=201,
        )

        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])
        validate_success(api.start_cutover_window(first_window["id"], SITE_MANAGER))
        set_clock(api, "2026-08-11T20:00:00Z")

        response = api.start_cutover_window(second_window["id"], SITE_MANAGER)
        validate_error(response, ApiErrorId.ERR_ZONE_NOT_READY.value)

        assert read_lot(api, second["lot"]["id"])["status"] == "FAT_PASSED"
        blocked = read_window(api, second_window["id"])
        assert blocked["status"] == "SCHEDULED"
        assert blocked["started_at"] is None
        assert read_window(api, first_window["id"])["status"] == "IN_PROGRESS"

        zones = validate_success(api.list_site_zones(project_id, SITE_MANAGER))
        assert [zone_row["ops_status"] for zone_row in zones] == ["CUTOVER_IN_PROGRESS"]
        project = read_project(api, project_id)
        assert project["legacy_share_bps"] == 0
        assert project["in_transition_share_bps"] == 10000
        assert project["cutover_share_bps"] == 0


class TestABlockedWindowReportsItsOwnState:
    """The window's own status is examined before the lot it references."""

    def test_the_blocked_start_names_the_block_and_not_the_held_lot(self, api):
        """A scope-bearing approval blocked the window and held the lot; the window wins.

        PRD §2.12: "Within this band the **target resource's own state is always examined
        before any relative's state**."

        Design: Corner/errors/window_start_while_blocked_returns_window_blocked_stale_design
        """
        state = make_scheduled_window(
            api,
            state=make_fat_passed_lot(
                api,
                bay=make_staging_bay(api, bay_code="BAY-21", concurrent_capacity=1),
                segment_codes=["IB-01", "TR-02"],
                lot_code="LOT-2100",
                measured_cph=1313,
                defect_count=0,
            ),
        )
        project_id = state["project"]["id"]
        change_order = make_submitted_change_order(
            api,
            project_id,
            title="Add second sorter bank",
            scope_delta_cph=100,
            price_delta_cents=10_000_000,
            schedule_delta_days=14,
        )
        approved = decide_change_order(
            api, project_id, change_order["id"], "APPROVE", headers=CUSTOMER_REP
        )
        assert approved["status"] == "APPROVED"
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])

        response = api.start_cutover_window(state["window"]["id"], SITE_MANAGER)
        validate_error(response, ApiErrorId.ERR_WINDOW_BLOCKED_STALE_DESIGN.value)

        window = read_window(api, state["window"]["id"])
        assert window["status"] == "BLOCKED_STALE_DESIGN"
        assert window["started_at"] is None
        assert read_lot(api, state["lot"]["id"])["status"] == "HOLD"

        runs, _ = validate_paginated(api.list_simulation_runs(project_id, DESIGN_ENGINEER))
        assert [run["status"] for run in runs] == ["STALE"]

        project = read_project(api, project_id)
        assert project["delivery_status"] == "DESIGN"
        assert project["escalation_fee_cents"] == 3_750_000
        assert project["contract_value_cents"] == 253_750_000
        assert project["legacy_share_bps"] == 10000


class TestIssuanceIsBlockedByAnOpenChangeOrder:
    """A price-only order reopens nothing yet still stops the certificate."""

    def test_a_submitted_price_only_order_blocks_issuance(self, api):
        """acceptance_ready is true, so the failure is purely commercial.

        PRD §3.7: "Three gates guard it, and their relative order follows §2.12:
        `acceptance_ready` must be true, otherwise `ERR_ACCEPTANCE_PREREQ_NOT_MET`; the
        project's `commercial_status` must be `CLEAN` — equivalently, no change order of
        the project may be sitting in `SUBMITTED` or `REVISION_REQUESTED` — otherwise
        `ERR_OPEN_CHANGE_ORDER`; and only then, the issuing `X-User-ID` must differ from
        the `recorded_by_user_id` of the passing full-rate ramp step, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/certificate_issuance_with_a_submitted_change_order_returns_open_change_order
        """
        state = _commissioned(
            api, "BAY-22", "LOT-2200", ramps=[(50, 700, 30), (75, 1000, 60), (100, 1260, 120)]
        )
        project_id = state["project"]["id"]
        assert state["project"]["acceptance_ready"] is True

        change_order = make_submitted_change_order(
            api,
            project_id,
            title="Extended commissioning support",
            scope_delta_cph=0,
            price_delta_cents=5_000_000,
            schedule_delta_days=0,
        )

        response = api.create_acceptance_certificate(
            create_acceptance_certificate_payload(project_id), PROJECT_DIRECTOR
        )
        validate_error(response, ApiErrorId.ERR_OPEN_CHANGE_ORDER.value)

        assert change_order["status"] == "SUBMITTED"
        after = read_project(api, project_id)
        assert after["delivery_status"] == "COMMISSIONING"
        assert after["commercial_status"] == "CHANGE_PENDING"
        assert after["contract_value_cents"] == 243_600_000
        _, meta = validate_paginated(
            api.list_acceptance_certificates(project_id, PROJECT_DIRECTOR)
        )
        assert meta["total_count"] == 0


class TestIssuanceIsSegregatedFromTheRampRecorder:
    """The identity comparison is on X-User-ID, not on the role."""

    def _full_rate_project(self, api):
        return _commissioned(
            api, "BAY-23", "LOT-2300", ramps=[(50, 700, 30), (75, 1000, 60), (100, 1260, 120)]
        )

    def test_the_operator_who_recorded_the_full_rate_step_may_not_issue(self, api):
        """The role is authorised and the identity is not, so this is 403 on duties.

        PRD §3.7: "and only then, the issuing `X-User-ID` must differ from the
        `recorded_by_user_id` of the passing full-rate ramp step, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/certificate_issued_by_the_ramp_recorder_returns_segregation_of_duties
        """
        state = self._full_rate_project(api)
        project_id = state["project"]["id"]
        recorder = state["ramps"][-1]
        assert recorder["recorded_by_user_id"] == SITE_MANAGER["X-User-ID"]
        assert recorder["verdict"] == "PASS"

        response = api.create_acceptance_certificate(
            create_acceptance_certificate_payload(project_id),
            make_project_director_headers(SITE_MANAGER["X-User-ID"]),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert read_project(api, project_id)["delivery_status"] == "COMMISSIONING"

    def test_a_different_operator_issues_the_same_certificate(self, api):
        """Only the identity changes, and the identical request now succeeds.

        PRD §3.7: "Its `retention_amount_cents` is the project's `contract_value_cents`
        multiplied by 500 basis points, that is five percent, divided by 10000 and rounded
        half up to a whole cent."

        Design: Corner/errors/certificate_issued_by_the_ramp_recorder_returns_segregation_of_duties
        """
        state = self._full_rate_project(api)
        project_id = state["project"]["id"]

        certificate = validate_success(
            api.create_acceptance_certificate(
                create_acceptance_certificate_payload(project_id), PROJECT_DIRECTOR
            ),
            expected_status=201,
        )
        assert_acceptance_certificate(certificate)
        assert certificate["issued_by_user_id"] == PROJECT_DIRECTOR["X-User-ID"]
        assert certificate["accepted_throughput_cph"] == 1260
        assert certificate["retention_amount_cents"] == 12_180_000
        assert read_project(api, project_id)["delivery_status"] == "ACCEPTED"


class TestSettledDisputesRefuseTheirReplays:
    """Two replays of the same settled argument fail with two different codes."""

    def _settled(self, api):
        state = make_disputed_certificate(
            api, claimed_cph=1100, damages_basis="OBSERVED_AVAILABILITY"
        )
        state["retest"] = validate_success(
            api.joint_retest(state["dispute"]["id"], joint_retest_payload(1200), SITE_MANAGER)
        )
        state["certificate"] = read_certificate(api, state["certificate"]["id"])
        state["project"] = read_project(api, state["project"]["id"])
        return state

    def test_refiling_against_the_upheld_certificate_is_refused(self, api):
        """The certificate is UPHELD, which the filing gate lists alongside DISPUTED.

        PRD §3.9: "the certificate's `status` must be `ISSUED`, and one already
        `DISPUTED`, `UPHELD` or `REVISED` is rejected with
        `ERR_CERTIFICATE_ALREADY_DISPUTED`"

        Design: Corner/errors/post_settlement_dispute_and_retest_replays_return_their_state_errors
        """
        state = self._settled(api)

        response = api.create_performance_dispute(
            create_performance_dispute_payload(state["certificate"]["id"], 1100, "NAMEPLATE"),
            CUSTOMER_REP,
        )
        validate_error(response, ApiErrorId.ERR_CERTIFICATE_ALREADY_DISPUTED.value)

        assert state["certificate"]["status"] == "UPHELD"
        assert state["certificate"]["retention_release_cents"] == 12_180_000
        assert state["project"]["commercial_status"] == "SETTLED"
        _, meta = validate_paginated(
            api.list_certificate_disputes(state["certificate"]["id"], CUSTOMER_REP)
        )
        assert meta["total_count"] == 1

    def test_a_second_retest_on_the_resolved_dispute_is_refused(self, api):
        """The dispute has left OPEN, so the retest cannot be replayed at a worse rate.

        PRD §3.9: "The dispute must still be `OPEN`; a retest against a dispute in
        `RESOLVED_UPHELD` or `RESOLVED_CREDITED` is rejected with
        `ERR_DISPUTE_INVALID_STATE`."

        Design: Corner/errors/post_settlement_dispute_and_retest_replays_return_their_state_errors
        """
        state = self._settled(api)
        settled = state["retest"]
        assert settled["status"] == "RESOLVED_UPHELD"
        assert settled["final_damages_cents"] == 0
        assert settled["sla_credit_cents"] == 0

        response = api.joint_retest(
            state["dispute"]["id"], joint_retest_payload(900), SITE_MANAGER
        )
        validate_error(response, ApiErrorId.ERR_DISPUTE_INVALID_STATE.value)

        disputes, _ = validate_paginated(
            api.list_certificate_disputes(state["certificate"]["id"], CUSTOMER_REP)
        )
        stored = disputes[0]
        assert stored["status"] == "RESOLVED_UPHELD"
        assert stored["provisional_nameplate_cents"] == 12_180_000
        assert stored["provisional_observed_cents"] == 8_526_000
        assert stored["final_damages_cents"] == 0


class TestTheDisputeWindowIsThirtyDays:
    """Past the deadline the filing fails on time, not on the certificate's status."""

    def test_filing_four_hours_late_is_refused(self, api):
        """A clock of 2026-09-10T00:00 is beyond the 2026-09-09T20:00 deadline.

        PRD §3.9: "the logical clock must be at or before the certificate's
        `dispute_deadline_utc`, the comparison being inclusive, so a filing on the deadline
        instant itself is accepted and a later one is rejected with
        `ERR_DISPUTE_WINDOW_EXPIRED`"

        Design: Corner/errors/dispute_filed_after_the_deadline_returns_dispute_window_expired
        """
        state = _commissioned(
            api, "BAY-24", "LOT-2400", ramps=[(50, 700, 30), (75, 1000, 60), (100, 1260, 120)]
        )
        certificate = validate_success(
            api.create_acceptance_certificate(
                create_acceptance_certificate_payload(state["project"]["id"]), PROJECT_DIRECTOR
            ),
            expected_status=201,
        )
        assert certificate["dispute_deadline_utc"].startswith("2026-09-09T20:00:00")
        set_clock(api, "2026-09-10T00:00:00Z")

        response = api.create_performance_dispute(
            create_performance_dispute_payload(certificate["id"], 1100, "NAMEPLATE"),
            CUSTOMER_REP,
        )
        validate_error(response, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED.value)

        stored = read_certificate(api, certificate["id"])
        assert stored["status"] == "ISSUED"
        assert stored["version"] == certificate["version"]

        project = read_project(api, state["project"]["id"])
        assert project["commercial_status"] == "CLEAN"
        assert project["delivery_status"] == "ACCEPTED"
        _, meta = validate_paginated(
            api.list_certificate_disputes(certificate["id"], CUSTOMER_REP)
        )
        assert meta["total_count"] == 0
