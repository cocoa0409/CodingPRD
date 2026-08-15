"""Startup windows, remote access, labor billing, commissioning cascade, shipping."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_bom_line,
    assert_same_instant,
    create_program_version_payload,
    create_startup_session_payload,
    get_success_data,
    make_field_engineer_headers,
    make_qa_headers,
    new_component,
    new_customer,
    new_job,
    new_panel,
    set_clock,
    setup_commissioned_job,
    setup_panel_ready_to_ship,
    setup_panel_through_test_passed,
    setup_panel_with_bom,
    setup_shipped_panel,
    validate_error,
    validate_success,
    walk_asbuilt_to_released,
    walk_job_to_shipped,
    walk_panel_to_design_approved,
    walk_panel_to_labeled,
    walk_panel_to_procurement_cleared,
    walk_panel_to_test_passed,
)


class TestAsBuiltCompleteness:
    def test_as_built_completeness_weighted_steps(self, api, de_headers):
        """PRD §3.6: "The percentage is a weighted score: the wiring diagram
        contributes `0.35`, the program archive contributes `0.25`, the test report
        contributes `0.25`, and the UL label photo contributes `0.15`; the weighted
        sum is multiplied by `100` and rounded half-up to an integer percent in
        `[0, 100]`."
        PRD §3.6: "When `completeness_pct` reaches `100`, the package auto-transitions
        `INCOMPLETE → PENDING_REVIEW`."

        Design: Corner/calculations/as_built_completeness_weighted_steps
        """
        ctx = setup_panel_with_bom(
            company_name="AB Co", job_number="J-AB1", quoted_price_cents=100000,
            panel_tag="P-AB1", design_engineer_id="de-ab",
        )
        packages = get_success_data(
            api.list_panel_asbuilt_packages(ctx["panel"]["id"], de_headers), 200
        )
        pkg_id = packages[0]["id"]

        step1 = validate_success(
            api.update_asbuilt_package(pkg_id, {"has_wiring_diagram": True}, de_headers), 200
        )
        assert step1["completeness_pct"] == 35, f"wiring alone = 35, got {step1['completeness_pct']}"

        step2 = validate_success(
            api.update_asbuilt_package(
                pkg_id, {"has_program_archive": True, "has_test_report": True}, de_headers
            ),
            200,
        )
        assert step2["completeness_pct"] == 85, (
            f"wiring + program + test = 85, got {step2['completeness_pct']}"
        )

        step3 = validate_success(
            api.update_asbuilt_package(pkg_id, {"has_ul_label_photo": True}, de_headers), 200
        )
        assert step3["completeness_pct"] == 100
        assert step3["status"] == "PENDING_REVIEW", (
            f"auto-advance at exactly 100, got {step3['status']}"
        )

    def test_as_built_flag_withdrawal_regresses_pending_review(self, api, de_headers):
        """PRD §3.6: "Conversely, if any flag later flips from `true` back to `false`
        while the package is in `PENDING_REVIEW` — a document withdrawal — the
        package regresses `PENDING_REVIEW → INCOMPLETE`."

        Design: Corner/calculations/as_built_flag_withdrawal_regresses_pending_review
        """
        ctx = setup_panel_with_bom(
            company_name="Regr Co", job_number="J-RG1", quoted_price_cents=100000,
            panel_tag="P-RG1", design_engineer_id="de-rg",
        )
        packages = get_success_data(
            api.list_panel_asbuilt_packages(ctx["panel"]["id"], de_headers), 200
        )
        pkg_id = packages[0]["id"]
        full = validate_success(
            api.update_asbuilt_package(
                pkg_id,
                {"has_wiring_diagram": True, "has_program_archive": True,
                 "has_test_report": True, "has_ul_label_photo": True},
                de_headers,
            ),
            200,
        )
        assert full["status"] == "PENDING_REVIEW" and full["completeness_pct"] == 100

        regressed = validate_success(
            api.update_asbuilt_package(pkg_id, {"has_test_report": False}, de_headers), 200
        )
        assert regressed["completeness_pct"] == 75, (
            f"0.35 + 0.25 + 0.15 = 75, got {regressed['completeness_pct']}"
        )
        assert regressed["status"] == "INCOMPLETE", (
            f"withdrawal regresses PENDING_REVIEW -> INCOMPLETE, got {regressed['status']}"
        )


class TestShipGate:
    def test_job_ship_gate_requires_ready_to_ship(self, api, pm_headers, shipping_headers,
                                                  de_headers, ce_headers):
        """PRD §3.1: "A ship call against a job that is not in `READY_TO_SHIP` is
        rejected with `ERR_JOB_GATE_BLOCKED` (HTTP 409)."
        PRD §3.1: "When the job is `READY_TO_SHIP`, a `ShippingClerk` triggers
        shipment. The transition cascades: every panel in `TEST_PASSED`,
        `READY_FOR_LABEL`, or `LABELED` transitions to `SHIPPED` with `shipped_at`
        set to the current time, and the job's `version` increments by one."

        Design: Corner/endpoints/job_ship_gate_requires_ready_to_ship
        """
        ctx = setup_panel_through_test_passed(
            company_name="Gate Co", job_number="J-GT1", quoted_price_cents=100000,
            warranty_months=12, panel_tag="P-GT1", design_engineer_id="de-gt",
            qa_user_id="qa-gt", technician_id="tt-gt",
            component_spec={
                "part_number": "BPD-GT", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 100,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        # Release a program version but leave the as-built short of RELEASED.
        panel = get_success_data(api.get_panel(panel_id, pm_headers), 200)
        get_success_data(
            api.create_program_version(
                panel_id,
                create_program_version_payload(
                    expected_panel_version=panel["version"], version_tag="v1.0.0"
                ),
                ce_headers,
            ),
            201,
        )
        packages = get_success_data(api.list_panel_asbuilt_packages(panel_id, de_headers), 200)
        pkg_id = packages[0]["id"]
        get_success_data(
            api.update_asbuilt_package(
                pkg_id,
                {"has_wiring_diagram": True, "has_program_archive": True,
                 "has_ul_label_photo": True},
                de_headers,
            ),
            200,
        )

        blocked = api.ship_job(ctx["job"]["id"], shipping_headers)
        validate_error(blocked, ApiErrorId.ERR_JOB_GATE_BLOCKED, 409)

        get_success_data(
            api.approve_asbuilt_package(pkg_id, make_qa_headers("qa-gt")), 200
        )
        get_success_data(api.release_asbuilt_package(pkg_id, pm_headers), 200)
        ready = validate_success(api.get_job(ctx["job"]["id"], pm_headers), 200)
        assert ready["status"] == "READY_TO_SHIP", (
            f"as-built release unblocks the gate, got {ready['status']}"
        )

        shipped = validate_success(api.ship_job(ctx["job"]["id"], shipping_headers), 200)
        assert shipped["status"] == "SHIPPED"
        panel_after = validate_success(api.get_panel(panel_id, pm_headers), 200)
        assert panel_after["status"] == "SHIPPED"
        assert panel_after["shipped_at"] is not None, "ship cascade sets shipped_at"


class TestRemoteAccess:
    def test_remote_support_requires_remote_access_grant(self, api, pm_headers):
        """PRD §3.7: "Additionally, choosing `support_mode` of `REMOTE` requires
        `remote_access_granted` to be `true`; a remote session without the customer's
        grant is rejected with `ERR_REMOTE_ACCESS_REQUIRED` (HTTP 422)."

        Design: Corner/validations/remote_support_requires_remote_access_grant
        """
        ctx = setup_panel_with_bom(
            company_name="RA Co", job_number="J-RA1", quoted_price_cents=100000,
            panel_tag="P-RA1", design_engineer_id="de-ra",
        )
        job_id = ctx["job"]["id"]
        panel_2 = new_panel(job_id, design_engineer_id="de-ra", panel_tag="P-RA2")

        denied = api.create_startup_session(
            ctx["panel"]["id"],
            create_startup_session_payload(
                scheduled_start="2026-11-02T08:00:00Z",
                scheduled_end="2026-11-02T17:00:00Z",
                engineer_id="fe-ra", support_mode="REMOTE", remote_access_granted=False,
            ),
            pm_headers,
        )
        validate_error(denied, ApiErrorId.ERR_REMOTE_ACCESS_REQUIRED, 422)

        granted = validate_success(
            api.create_startup_session(
                panel_2["id"],
                create_startup_session_payload(
                    scheduled_start="2026-11-02T08:00:00Z",
                    scheduled_end="2026-11-02T17:00:00Z",
                    engineer_id="fe-ra", support_mode="REMOTE", remote_access_granted=True,
                ),
                pm_headers,
            ),
            201,
        )
        assert granted["status"] == "SCHEDULED"


class TestNoShowSweep:
    def test_startup_session_no_show_sweep_on_clock_advance(self, api, pm_headers):
        """PRD §2.5: "Advancing the logical clock past a `StartupSession`'s
        `scheduled_end` while that session is still in `SCHEDULED` fires the no-show
        sweep, transitioning the session to `NO_SHOW`. The same sweep is evaluated on
        any read or write of the affected session, so a no-show never lingers
        invisible."

        Design: Corner/state_machines/startup_session_no_show_sweep_on_clock_advance
        """
        ctx = setup_panel_with_bom(
            company_name="NS Co", job_number="J-NS1", quoted_price_cents=100000,
            warranty_months=12, panel_tag="P-NS1", design_engineer_id="de-ns",
        )
        set_clock("2026-10-05T00:00:00Z")
        session = validate_success(
            api.create_startup_session(
                ctx["panel"]["id"],
                create_startup_session_payload(
                    scheduled_start="2026-10-06T08:00:00Z",
                    scheduled_end="2026-10-06T17:00:00Z",
                    engineer_id="fe-ns", support_mode="ONSITE",
                ),
                pm_headers,
            ),
            201,
        )
        assert session["status"] == "SCHEDULED"

        set_clock("2026-10-07T00:00:00Z")
        after = validate_success(api.get_startup_session(session["id"], pm_headers), 200)
        assert after["status"] == "NO_SHOW", (
            f"clock past scheduled_end must sweep to NO_SHOW, got {after['status']}"
        )


class TestBackupRequired:
    def test_error_backup_required_on_startup_complete(self, api, pm_headers):
        """PRD §3.7: "Completion requires that the owning panel have a `RELEASED`
        `ProgramVersion` with `site_backup_taken` equal to `true`; without that
        evidence the complete is rejected with `ERR_BACKUP_REQUIRED`."
        PRD §3.5: "A `FieldEngineer` marks the site backup evidence on a `RELEASED`
        version via the mark-site-backup action, setting `site_backup_taken` to
        `true`."

        Design: Corner/errors/error_backup_required_on_startup_complete
        """
        ctx = setup_shipped_panel(
            company_name="BK Co", job_number="J-BK1", quoted_price_cents=100000,
            warranty_months=12, panel_tag="P-BK1", design_engineer_id="de-bk",
            qa_user_id="qa-bk", technician_id="tt-bk",
            component_spec={
                "part_number": "BPD-BK", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 100,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        set_clock("2026-10-05T09:00:00Z")
        session = validate_success(
            api.create_startup_session(
                panel_id,
                create_startup_session_payload(
                    scheduled_start="2026-10-05T08:00:00Z",
                    scheduled_end="2026-10-05T18:00:00Z",
                    engineer_id="fe-bk", support_mode="ONSITE",
                ),
                pm_headers,
            ),
            201,
        )
        fe = make_field_engineer_headers("fe-bk")
        get_success_data(api.start_startup_session(session["id"], fe), 200)

        denied = api.complete_startup_session(session["id"], {"labor_hours": 4}, fe)
        validate_error(denied, ApiErrorId.ERR_BACKUP_REQUIRED, 422)

        get_success_data(api.mark_site_backup(ctx["program_version"]["id"],
                                              make_field_engineer_headers("fe-bk")), 200)
        completed = validate_success(
            api.complete_startup_session(session["id"], {"labor_hours": 4}, fe), 200
        )
        assert completed["status"] == "COMPLETED"
        panel_after = validate_success(api.get_panel(panel_id, pm_headers), 200)
        assert panel_after["status"] == "COMMISSIONED"


class TestStartWindow:
    def test_error_outside_window_on_startup_start(self, api, pm_headers):
        """PRD §3.7: "A `FieldEngineer` begins the work only when the current logical
        clock is at or after `scheduled_start` and at or before `scheduled_end`, when
        the owning panel is in `SHIPPED`, and — when `support_mode` is `REMOTE` —
        when `remote_access_granted` is `true`. A begin attempt outside the window is
        rejected with `ERR_OUTSIDE_SCHEDULED_WINDOW` (HTTP 422)".

        Design: Corner/errors/error_outside_window_on_startup_start
        """
        ctx = setup_shipped_panel(
            company_name="OW Co", job_number="J-OW1", quoted_price_cents=100000,
            warranty_months=12, panel_tag="P-OW1", design_engineer_id="de-ow",
            qa_user_id="qa-ow", technician_id="tt-ow",
            component_spec={
                "part_number": "BPD-OW", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 100,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        session = validate_success(
            api.create_startup_session(
                panel_id,
                create_startup_session_payload(
                    scheduled_start="2026-10-05T08:00:00Z",
                    scheduled_end="2026-10-05T17:00:00Z",
                    engineer_id="fe-ow", support_mode="ONSITE",
                ),
                pm_headers,
            ),
            201,
        )
        get_success_data(
            api.mark_site_backup(ctx["program_version"]["id"],
                                 make_field_engineer_headers("fe-ow")),
            200,
        )
        fe = make_field_engineer_headers("fe-ow")

        set_clock("2026-10-05T07:00:00Z")
        early = api.start_startup_session(session["id"], fe)
        validate_error(early, ApiErrorId.ERR_OUTSIDE_SCHEDULED_WINDOW, 422)

        set_clock("2026-10-05T08:00:00Z")
        started = validate_success(api.start_startup_session(session["id"], fe), 200)
        assert started["status"] == "IN_PROGRESS", (
            "the window lower bound is inclusive: start at exactly scheduled_start succeeds"
        )


class TestEngineerDoubleBooking:
    def _setup_two_panels(self, api, pm_headers):
        customer = new_customer(company_name="Pi Ceramics", site_state_code="AZ")
        job = new_job(customer["id"], job_number="J-9301", quoted_price_cents=200000,
                      warranty_months=12)
        panel_1 = new_panel(job["id"], design_engineer_id="de-013", panel_tag="P-H1")
        panel_2 = new_panel(job["id"], design_engineer_id="de-013", panel_tag="P-H2")
        set_clock("2026-10-04T00:00:00Z")
        session_1 = validate_success(
            api.create_startup_session(
                panel_1["id"],
                create_startup_session_payload(
                    scheduled_start="2026-10-06T08:00:00Z",
                    scheduled_end="2026-10-06T17:00:00Z",
                    engineer_id="fe-060", support_mode="ONSITE",
                ),
                pm_headers,
            ),
            201,
        )
        return panel_2, session_1

    def test_engineer_overlap_rejected(self, api, pm_headers):
        """PRD §3.7: "no two sessions in `SCHEDULED` or `IN_PROGRESS` for the same
        `engineer_id` may have overlapping half-open `[scheduled_start,
        scheduled_end)` windows — adjacency, where one session's `scheduled_end`
        equals another's `scheduled_start`, is permitted — and a violation is
        rejected with `ERR_ENGINEER_DOUBLE_BOOKED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/engineer_double_booked_half_open_adjacency
        """
        panel_2, _s1 = self._setup_two_panels(api, pm_headers)
        resp = api.create_startup_session(
            panel_2["id"],
            create_startup_session_payload(
                scheduled_start="2026-10-06T12:00:00Z",
                scheduled_end="2026-10-06T20:00:00Z",
                engineer_id="fe-060", support_mode="ONSITE",
            ),
            pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ENGINEER_DOUBLE_BOOKED, 422)

    def test_engineer_adjacent_sessions_permitted(self, api, pm_headers):
        """PRD §3.7: "no two sessions in `SCHEDULED` or `IN_PROGRESS` for the same
        `engineer_id` may have overlapping half-open `[scheduled_start,
        scheduled_end)` windows — adjacency, where one session's `scheduled_end`
        equals another's `scheduled_start`, is permitted".

        Design: Difficulty/resource_temporal_overlap/engineer_double_booked_half_open_adjacency
        """
        panel_2, _s1 = self._setup_two_panels(api, pm_headers)
        adjacent = validate_success(
            api.create_startup_session(
                panel_2["id"],
                create_startup_session_payload(
                    scheduled_start="2026-10-06T17:00:00Z",
                    scheduled_end="2026-10-06T20:00:00Z",
                    engineer_id="fe-060", support_mode="ONSITE",
                ),
                pm_headers,
            ),
            201,
        )
        assert adjacent["status"] == "SCHEDULED", (
            "end == start touches under half-open semantics and is permitted"
        )


class TestPanelTurnoverBuffer:
    def _setup_panel_with_session(self, api, pm_headers):
        ctx = setup_panel_with_bom(
            company_name="Rho Glass", job_number="J-9302", quoted_price_cents=200000,
            warranty_months=12, panel_tag="P-T1", design_engineer_id="de-014",
        )
        set_clock("2026-10-04T00:00:00Z")
        session_a = validate_success(
            api.create_startup_session(
                ctx["panel"]["id"],
                create_startup_session_payload(
                    scheduled_start="2026-10-06T08:00:00Z",
                    scheduled_end="2026-10-06T17:00:00Z",
                    engineer_id="fe-070", support_mode="ONSITE",
                ),
                pm_headers,
            ),
            201,
        )
        return ctx["panel"]["id"], session_a

    def test_panel_turnover_23h_gap_rejected(self, api, pm_headers):
        """PRD §3.7: "a new session for the same panel must not begin within 24 hours
        after the `scheduled_end` of any other `SCHEDULED` or `IN_PROGRESS` session
        for that panel; the rule uses buffer-inflated interval semantics, so a gap of
        at least 24 hours is required and a gap of exactly 24 hours is permitted,
        with violations rejected with `ERR_PANEL_TURNOVER_VIOLATION` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/panel_turnover_buffer_24h_gap_boundary
        """
        panel_id, _a = self._setup_panel_with_session(api, pm_headers)
        resp = api.create_startup_session(
            panel_id,
            create_startup_session_payload(
                scheduled_start="2026-10-07T16:00:00Z",
                scheduled_end="2026-10-07T20:00:00Z",
                engineer_id="fe-071", support_mode="ONSITE",
            ),
            pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PANEL_TURNOVER_VIOLATION, 422)

    def test_panel_turnover_exactly_24h_gap_permitted(self, api, pm_headers):
        """PRD §3.7: "a new session for the same panel must not begin within 24 hours
        after the `scheduled_end` of any other `SCHEDULED` or `IN_PROGRESS` session
        for that panel; the rule uses buffer-inflated interval semantics, so a gap of
        at least 24 hours is required and a gap of exactly 24 hours is permitted".

        Design: Difficulty/resource_temporal_overlap/panel_turnover_buffer_24h_gap_boundary
        """
        panel_id, _a = self._setup_panel_with_session(api, pm_headers)
        permitted = validate_success(
            api.create_startup_session(
                panel_id,
                create_startup_session_payload(
                    scheduled_start="2026-10-07T17:00:00Z",
                    scheduled_end="2026-10-07T20:00:00Z",
                    engineer_id="fe-071", support_mode="ONSITE",
                ),
                pm_headers,
            ),
            201,
        )
        assert permitted["status"] == "SCHEDULED", (
            "a gap of exactly 24 hours after the previous scheduled_end is permitted"
        )


class TestStartupStartGatedByShipped:
    def _setup_ready_to_ship_with_session(self, api, pm_headers):
        ctx = setup_panel_ready_to_ship(
            company_name="Xi Lumber", job_number="J-9201", quoted_price_cents=300000,
            warranty_months=12, panel_tag="P-G1", design_engineer_id="de-011",
            qa_user_id="qa-908", technician_id="tt-500",
            component_spec={
                "part_number": "BPD-G100", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 45000, "lead_time_days": 21, "sccr_ka": 100,
                "heat_dissipation_w": 12,
            },
        )
        set_clock("2026-10-05T09:00:00Z")
        session = validate_success(
            api.create_startup_session(
                ctx["panel"]["id"],
                create_startup_session_payload(
                    scheduled_start="2026-10-05T08:00:00Z",
                    scheduled_end="2026-10-05T18:00:00Z",
                    engineer_id="fe-040", support_mode="ONSITE",
                ),
                pm_headers,
            ),
            201,
        )
        get_success_data(
            api.mark_site_backup(ctx["program_version"]["id"],
                                 make_field_engineer_headers("fe-040")),
            200,
        )
        return ctx, session

    def test_startup_start_rejected_while_panel_labeled(self, api, pm_headers):
        """PRD §3.7: "A `FieldEngineer` begins the work only when the current logical
        clock is at or after `scheduled_start` and at or before `scheduled_end`, when
        the owning panel is in `SHIPPED`, and — when `support_mode` is `REMOTE` —
        when `remote_access_granted` is `true`." and "a begin against a panel that is
        not `SHIPPED` is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/startup_start_gated_by_panel_shipped
        """
        ctx, session = self._setup_ready_to_ship_with_session(api, pm_headers)
        panel = validate_success(api.get_panel(ctx["panel"]["id"], pm_headers), 200)
        assert panel["status"] == "LABELED", "precondition: panel shipped-gate not yet crossed"

        resp = api.start_startup_session(session["id"], make_field_engineer_headers("fe-040"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_startup_start_succeeds_after_panel_shipped(self, api, pm_headers,
                                                        shipping_headers):
        """PRD §3.7: "A successful begin transitions `SCHEDULED → IN_PROGRESS` and
        increments the session's `version`."
        PRD §3.1: "When the job is `READY_TO_SHIP`, a `ShippingClerk` triggers
        shipment. The transition cascades: every panel in `TEST_PASSED`,
        `READY_FOR_LABEL`, or `LABELED` transitions to `SHIPPED` with `shipped_at`
        set to the current time".

        Design: Difficulty/cross_entity_state_dependency/startup_start_gated_by_panel_shipped
        """
        ctx, session = self._setup_ready_to_ship_with_session(api, pm_headers)
        validate_success(api.ship_job(ctx["job"]["id"], shipping_headers), 200)
        panel = validate_success(api.get_panel(ctx["panel"]["id"], pm_headers), 200)
        assert panel["status"] == "SHIPPED"

        started = validate_success(
            api.start_startup_session(session["id"], make_field_engineer_headers("fe-040")),
            200,
        )
        assert started["status"] == "IN_PROGRESS"


class TestStartupLaborBilling:
    def test_startup_billing_weekday_ot_rate_rounded_first(self, api, pm_headers):
        """PRD §3.7: "The first `8` hours are billed at a base rate of `18533` cents
        per hour. Hours beyond `8` and up to a total of `16` hours are overtime,
        billed at one-and-a-half times the base rate; the overtime rate is computed
        by multiplying the base rate by `1.5` and rounding half-up to integer cents
        first, and only then multiplying by the number of overtime hours — the
        rounding order is pinned, so the per-hour overtime rate is `27800` cents
        regardless of how many overtime hours are billed." and "On a weekday the
        multiplier is `1` and the bill is the raw sum rounded half-up."

        Design: Difficulty/combinatorial_formula/startup_labor_waterfall_nested_rounding_mode_b
        """
        ctx = setup_commissioned_job(
            company_name="Delta Bottling", job_number="J-4001", quoted_price_cents=800000,
            warranty_months=12, panel_tag="P-W1", design_engineer_id="de-003",
            qa_user_id="qa-902", technician_id="tt-200", engineer_id="fe-010",
            session_start="2026-10-05T08:00:00Z",  # Monday
            session_end="2026-10-05T20:00:00Z",
            work_time="2026-10-05T09:00:00Z",
            labor_hours=10,
        )
        session = ctx["startup_session"]
        assert session["status"] == "COMPLETED"
        # 8 * 18533 + 2 * 27800 = 148264 + 55600 = 203864.
        assert session["billable_cents"] == 203864, (
            f"weekday 10h: 8*18533 + 2*27800 = 203864, got {session['billable_cents']}"
        )

    def test_startup_billing_weekend_multiplier(self, api, pm_headers):
        """PRD §3.7: "When `scheduled_start` falls on a Saturday or Sunday (UTC), the
        raw bill is multiplied by `1.25`; the final `billable_cents` is that product
        rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/startup_labor_waterfall_nested_rounding_mode_b
        """
        ctx = setup_commissioned_job(
            company_name="Delta Bottling", job_number="J-4002", quoted_price_cents=800000,
            warranty_months=12, panel_tag="P-W2", design_engineer_id="de-003",
            qa_user_id="qa-902", technician_id="tt-201", engineer_id="fe-011",
            session_start="2026-10-10T08:00:00Z",  # Saturday
            session_end="2026-10-10T20:00:00Z",
            work_time="2026-10-10T09:00:00Z",
            labor_hours=10,
        )
        session = ctx["startup_session"]
        assert session["status"] == "COMPLETED"
        # round_half_up((8*18533 + 2*27800) * 1.25) = round_half_up(254830.0) = 254830.
        assert session["billable_cents"] == 254830, (
            f"Saturday 10h: 203864 * 1.25 = 254830, got {session['billable_cents']}"
        )


class TestCommissioningCascade:
    def test_startup_complete_cascades_panel_and_job_commissioned(self, api):
        """PRD §3.7: "On a successful complete, the session transitions `IN_PROGRESS
        → COMPLETED`, the panel auto-transitions `SHIPPED → COMMISSIONED` with
        `commissioned_at` set to the current time, the job posture is re-evaluated
        (so the last-commissioned panel may push the job itself into `COMMISSIONED`
        and set `warranty_expires_at`)".

        Design: Difficulty/transitive_cascade/startup_complete_cascade_panel_job_warranty_depth4
        """
        ctx = setup_commissioned_job(
            company_name="Theta Foundry", job_number="J-7001", quoted_price_cents=900000,
            warranty_months=24, panel_tag="P-C1", design_engineer_id="de-006",
            qa_user_id="qa-905", technician_id="tt-300", engineer_id="fe-020",
            labor_hours=6,
        )
        assert ctx["startup_session"]["status"] == "COMPLETED"
        assert ctx["panel"]["status"] == "COMMISSIONED"
        assert_same_instant(ctx["panel"]["commissioned_at"], "2026-10-01T09:00:00Z",
                            "panel commissioned_at")
        assert ctx["job"]["status"] == "COMMISSIONED"

    def test_job_warranty_expires_at_minted_from_commissioned_at(self, api):
        """PRD §3.1: "When every panel of a shipped job reaches `COMMISSIONED`, the
        job auto-transitions `SHIPPED → COMMISSIONED` and the server writes
        `warranty_expires_at` equal to the latest `commissioned_at` across the job's
        panels plus `warranty_months` calendar months. Before that moment,
        `warranty_expires_at` is null."

        Design: Difficulty/transitive_cascade/startup_complete_cascade_panel_job_warranty_depth4
        """
        ctx = setup_commissioned_job(
            company_name="Theta Foundry", job_number="J-7001", quoted_price_cents=900000,
            warranty_months=24, panel_tag="P-C1", design_engineer_id="de-006",
            qa_user_id="qa-905", technician_id="tt-300", engineer_id="fe-020",
            labor_hours=6,
        )
        assert ctx["job"]["warranty_expires_at"] is not None
        assert_same_instant(ctx["job"]["warranty_expires_at"], "2028-10-01T09:00:00Z",
                            "warranty_expires_at (commissioned_at + 24 months)")
