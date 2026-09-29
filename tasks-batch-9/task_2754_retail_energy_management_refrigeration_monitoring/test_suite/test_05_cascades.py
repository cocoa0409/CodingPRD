"""Transitive cascades: readings, fault triage and standard supersession."""
import pytest

from prd_bench_local_runner.testing import get_success_data
from test_helpers import factories as f, fixtures as fx
from test_helpers.test_users import make_energy_manager_headers, make_maintenance_tech_headers

BASELINE_INTERVALS = [
    f.demand_interval("2026-08-01T14:00:00Z", 1290.5, True),
    f.demand_interval("2026-08-01T15:00:00Z", 1275.0, True),
    f.demand_interval("2026-08-01T16:00:00Z", 1245.0, True),
]


def _store_poised_for_escalation(api):
    """A COLD store in CONSTRAINED with a NOTIFIED event, a PROPOSED project and
    an ACTIVE schedule-extension override projecting 300.00 kWh."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T04:00:00Z", code="STR-TC1", climate_zone="COLD",
        floor_area_sqft=115000, override_budget_kwh_month=500.0,
    )
    account = fx.create_account(
        api, ctx["store_id"], utility_name="Northern Grid",
        rate_schedule_code="TOU-GS3", rate_family="TOU_DEMAND",
        demand_charge_per_kw=14.50, rate_on_peak=0.1450, rate_off_peak=0.0800,
    )
    fx.ingest_intervals(api, account["id"], BASELINE_INTERVALS)
    event = fx.create_event(
        api, account["id"], program_code="CPP-2026",
        curtailment_start_iso="2026-08-02T14:00:00Z",
        curtailment_end_iso="2026-08-02T15:00:00Z", target_reduction_kw=200.0,
    )
    ctx["account_id"] = account["id"]
    ctx["event_id"] = event["id"]
    ctx["notified"] = fx.notify_event(api, event["id"])
    project = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_tc1",
        measure_type="CASE_DOORS", capex_usd=88000.00,
        projected_annual_savings_kwh=210000.00,
    )
    ctx["project_id"] = project["id"]
    case = fx.create_case(
        api, ctx["store_id"], case_code="CASE-TC1-01", case_type="MEDIUM_TEMP",
        product_class="MEAT", alarm_high_f=41.0, alarm_low_f=28.0,
        product_value_usd=12800.00,
    )
    ctx["case_id"] = case["id"]
    fx.post_reading(api, case["id"], ctx["store_id"], 42.0, "2026-08-01T04:00:00Z")
    ctx["alarm_reading"] = fx.post_reading(
        api, case["id"], ctx["store_id"], 42.5, "2026-08-01T04:15:00Z"
    )
    ctx["excursion_id"] = ctx["alarm_reading"]["excursion_id"]
    # The override is requested only once the store is CONSTRAINED, so that it is
    # still ACTIVE when the lock arrives.
    ctx["override"] = fx.create_override(
        api, ctx["store_id"], zone="SALES_FLOOR", override_type="SCHEDULE_EXTEND",
        start_iso="2026-08-01T00:00:00Z", end_iso="2026-08-01T08:00:00Z",
        zone_load_kw=37.5, requested_reason="inventory count night crew",
    )
    ctx["override_id"] = ctx["override"]["id"]
    return ctx


class TestReadingEscalationCascade:
    def test_the_escalating_reading_locks_the_store_and_reports_the_cascade(self, api):
        """One reading escalates the excursion and locks the store.

        The PRD states: "Escalation is the system's most consequential cascade,
        and it fires whenever an excursion enters `ESCALATED` or
        `DISPOSITION_REQUIRED`. The owning store recomputes its posture and, by
        rule one of the posture ladder, is raised to `LOCKED` from whichever of
        `NORMAL`, `CONSTRAINED` or `CURTAILED` it held."

        Design: Difficulty/transitive_cascade/reading_escalation_cascade_depth_five
        """
        ctx = _store_poised_for_escalation(api)
        assert ctx["notified"]["event_state"] == "NOTIFIED"
        assert ctx["alarm_reading"]["store_energy_posture"] == "CONSTRAINED"
        assert ctx["override"]["state"] == "ACTIVE"
        assert ctx["override"]["projected_kwh"] == pytest.approx(300.00, abs=0.01)

        escalating = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 43.0, "2026-08-01T06:00:00Z"
        )

        assert escalating["excursion_state"] == "ESCALATED"
        assert escalating["exposure_minutes"] == 120
        assert escalating["store_energy_posture"] == "LOCKED"
        assert escalating["dr_events_opted_out"] == 1
        assert escalating["overrides_revoked"] == 1
        excursion = fx.read_excursion(api, ctx["excursion_id"])
        assert excursion["state"] == "ESCALATED"
        assert excursion["peak_temp_f"] == pytest.approx(43.0, abs=0.05)
        assert excursion["mandatory_disposition"] == "NONE"

    def test_the_lock_opts_the_notified_event_out_without_suspending_enrollment(self, api):
        """One system opt-out increments the counter but does not suspend.

        The PRD states: "Each system opt-out increments the account's
        `dr_optout_count`, and as soon as that count reaches three the account's
        `dr_enrollment_state` becomes `SUSPENDED` — a store that keeps failing its
        cases out of curtailment events loses its place in the program."

        Design: Difficulty/transitive_cascade/reading_escalation_cascade_depth_five
        """
        ctx = _store_poised_for_escalation(api)

        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 43.0, "2026-08-01T06:00:00Z")

        events, _ = fx.list_events(api, ctx["account_id"])
        event = fx.find_row(events, ctx["event_id"])
        account = fx.read_account(api, ctx["account_id"])

        assert event["event_state"] == "OPTED_OUT"
        assert event["opt_out_reason"] == "FOOD_SAFETY_POSTURE"
        assert account["dr_optout_count"] == 1
        assert account["dr_enrollment_state"] == "ENROLLED"

    def test_the_lock_revokes_the_override_and_releases_its_projection(self, api):
        """A system revocation names no user and frees the monthly allowance.

        The PRD states: "Every `ACTIVE` lighting override of the store whose
        `override_type` is `SCHEDULE_EXTEND` is revoked as a system action, and
        `overrides_revoked` counts those."

        Design: Difficulty/transitive_cascade/reading_escalation_cascade_depth_five
        """
        ctx = _store_poised_for_escalation(api)

        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 43.0, "2026-08-01T06:00:00Z")

        overrides, _ = fx.list_overrides(api, ctx["store_id"])
        override = fx.find_row(overrides, ctx["override_id"])
        store = fx.read_store(api, ctx["store_id"])

        assert override["state"] == "REVOKED"
        assert override["revoke_source"] == "SYSTEM_POSTURE"
        assert override["revoked_by_user_id"] is None
        assert store["override_kwh_used_month"] == pytest.approx(0.00, abs=0.01)
        assert store["energy_posture"] == "LOCKED"

    def test_the_lock_flags_the_proposed_project_for_escalated_review(self, api):
        """The fifth link reaches the store's capital pipeline.

        The PRD states: "Retrofit projects of the store in `PROPOSED` are marked
        with `escalated_review` true."

        Design: Difficulty/transitive_cascade/reading_escalation_cascade_depth_five
        """
        ctx = _store_poised_for_escalation(api)

        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 43.0, "2026-08-01T06:00:00Z")

        projects, _ = fx.list_projects(api, ctx["store_id"])
        project = fx.find_row(projects, ctx["project_id"])

        assert project["escalated_review"] is True
        assert project["state"] == "PROPOSED"


LIGHTING_FAULT = {
    "equipment_ref": "LTG-PANEL-3",
    "equipment_class": "LIGHTING",
    "fault_code": "BALLAST_DRIFT",
    "severity": "MINOR",
    "occurrence_count": 2,
    "affected_load_kw": 10.0,
}

REFRIGERATION_FAULT = {
    "equipment_ref": "RACK-A1",
    "equipment_class": "REFRIGERATION",
    "fault_code": "DISCHARGE_TEMP_HIGH",
    "severity": "MAJOR",
    "occurrence_count": 6,
    "affected_load_kw": 20.0,
}


def _store_with_two_projects_and_a_lighting_fault(api):
    """A MARINE store with two PROPOSED projects, plus a lighting fault already
    triaged into a routine order, and one refrigeration fault still DETECTED."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-TC2", climate_zone="MARINE", store_format="NEIGHBORHOOD",
        floor_area_sqft=44000,
    )
    ctx["project_a"] = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_tc2",
        measure_type="ECM_MOTORS", capex_usd=61600.00,
        projected_annual_savings_kwh=140000.00,
    )
    ctx["project_b"] = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_tc2",
        measure_type="LED_RETROFIT", capex_usd=44000.00,
        projected_annual_savings_kwh=120000.00,
    )
    lighting_fault = fx.create_fault(api, ctx["store_id"], **LIGHTING_FAULT)
    ctx["lighting_fault"] = lighting_fault
    ctx["lighting_triage"] = fx.triage_fault(api, lighting_fault["id"])
    refrigeration_fault = fx.create_fault(api, ctx["store_id"], **REFRIGERATION_FAULT)
    ctx["fault_id"] = refrigeration_fault["id"]
    ctx["fault_score"] = refrigeration_fault["fault_score"]
    return ctx


class TestFaultTriageCascade:
    def test_a_routine_lighting_order_stops_the_chain_at_the_first_link(self, api):
        """A ROUTINE order neither degrades the gateway nor raises the posture.

        The PRD states: "The second link, when that work order is `URGENT`,
        increments the store's `urgent_work_order_count` — which counts the
        store's work orders whose `priority` is `URGENT` and whose `state` is
        `OPEN` or `SCHEDULED`, reached through their faults — and, additionally,
        when the fault's `equipment_class` is `REFRIGERATION`, moves the store
        `ACTIVE → DEGRADED`."

        Design: Difficulty/transitive_cascade/fault_triage_cascade_depth_four
        """
        ctx = _store_with_two_projects_and_a_lighting_fault(api)

        assert ctx["store"]["energy_posture"] == "NORMAL"
        assert ctx["project_a"]["escalated_review"] is False
        assert ctx["lighting_fault"]["fault_score"] == pytest.approx(23.1, abs=0.05)
        assert ctx["lighting_triage"]["work_order_priority"] == "ROUTINE"
        assert ctx["lighting_triage"]["store_bms_status"] == "ACTIVE"
        assert ctx["lighting_triage"]["store_energy_posture"] == "NORMAL"

    def test_an_urgent_refrigeration_triage_runs_all_four_links(self, api):
        """Triage reports the whole cascade in one response.

        The PRD states: "Triage reports the whole cascade back as `fault_id`,
        `fault_state`, `fault_score`, `work_order_id`, `work_order_priority`,
        `work_order_state`, `store_bms_status`, `store_energy_posture`,
        `urgent_work_order_count` and `escalated_retrofit_count`; on a suppression
        the three work-order fields are null."

        Design: Difficulty/transitive_cascade/fault_triage_cascade_depth_four
        """
        ctx = _store_with_two_projects_and_a_lighting_fault(api)
        assert ctx["fault_score"] == pytest.approx(89.3, abs=0.05)

        triage = get_success_data(
            api.triage_fault(
                ctx["fault_id"], f.triage_payload("WORK_ORDER"),
                make_maintenance_tech_headers("u_tech_tc2"),
            )
        )

        assert triage["fault_state"] == "TRIAGED"
        assert triage["work_order_priority"] == "URGENT"
        assert triage["work_order_state"] == "OPEN"
        assert triage["store_bms_status"] == "DEGRADED"
        assert triage["store_energy_posture"] == "CONSTRAINED"
        assert triage["urgent_work_order_count"] == 1
        assert triage["escalated_retrofit_count"] == 2

    def test_the_fourth_link_flags_every_proposed_project_of_the_store(self, api):
        """Both proposed projects are marked for escalated review.

        The PRD states: "The fourth link sets `escalated_review` to true on every
        retrofit project of that store still in `PROPOSED`."

        Design: Difficulty/transitive_cascade/fault_triage_cascade_depth_four
        """
        ctx = _store_with_two_projects_and_a_lighting_fault(api)

        get_success_data(
            api.triage_fault(
                ctx["fault_id"], f.triage_payload("WORK_ORDER"),
                make_maintenance_tech_headers("u_tech_tc2"),
            )
        )

        projects, _ = fx.list_projects(api, ctx["store_id"])
        fault = get_success_data(api.get_fault_diagnostic(ctx["fault_id"], fx.TECH))

        assert fx.find_row(projects, ctx["project_a"]["id"])["escalated_review"] is True
        assert fx.find_row(projects, ctx["project_b"]["id"])["escalated_review"] is True
        assert fault["state"] == "TRIAGED"
        assert fault["triaged_by_user_id"] == "u_tech_tc2"


def _two_stores_bound_to_one_published_standard(api):
    """Store A activated and store B left in COMMISSIONING, both bound to the same
    published standard, plus a DRAFT successor naming it."""
    fx.set_clock(api)
    store_a = fx.create_store(
        api, code="STR-TC3-A", climate_zone="HOT_HUMID", store_format="EXPRESS",
        floor_area_sqft=16000,
    )
    store_b = fx.create_store(
        api, code="STR-TC3-B", climate_zone="HOT_HUMID", store_format="EXPRESS",
        floor_area_sqft=17500,
    )
    predecessor = fx.create_published_standard(
        api, climate_zone="HOT_HUMID", store_format="EXPRESS", season="SUMMER",
        cooling_setpoint_f=75.0, heating_setpoint_f=69.0, deadband_f=2.0,
        lighting_lux_target=600,
    )
    fx.commission_store(api, store_a["id"], predecessor["id"], store_a["version"])
    activated_a = fx.activate_store_bms(api, store_a["id"])
    commissioned_b = fx.commission_store(
        api, store_b["id"], predecessor["id"], store_b["version"]
    )
    successor = fx.create_standard(
        api, climate_zone="HOT_HUMID", store_format="EXPRESS", season="SUMMER",
        cooling_setpoint_f=76.0, heating_setpoint_f=69.0, deadband_f=2.5,
        lighting_lux_target=550, supersedes_standard_id=predecessor["id"],
    )
    return {
        "store_a_id": store_a["id"],
        "store_b_id": store_b["id"],
        "activated_a": activated_a,
        "commissioned_b": commissioned_b,
        "predecessor": predecessor,
        "successor": successor,
    }


class TestStandardPublishSupersessionCascade:
    def test_publication_supersedes_the_predecessor_and_stamps_the_publisher(self, api):
        """The successor is published and the incumbent is superseded.

        The PRD states: "First, the predecessor moves `PUBLISHED → SUPERSEDED` and
        its `version` increments."

        Design: Difficulty/transitive_cascade/standard_publish_supersession_cascade_depth_three
        """
        ctx = _two_stores_bound_to_one_published_standard(api)
        assert ctx["predecessor"]["status"] == "PUBLISHED"
        assert ctx["successor"]["status"] == "DRAFT"

        published = get_success_data(
            api.publish_setpoint_standard(
                ctx["successor"]["id"], make_energy_manager_headers("u_manager_tc3")
            )
        )
        predecessor = get_success_data(
            api.get_setpoint_standard(ctx["predecessor"]["id"], fx.MANAGER)
        )

        assert published["status"] == "PUBLISHED"
        assert published["published_by_user_id"] == "u_manager_tc3"
        assert published["published_at_iso"].startswith("2026-08-01T00:00:00")
        assert predecessor["status"] == "SUPERSEDED"

    def test_only_the_active_bound_store_degrades_and_constrains(self, api):
        """A store still in COMMISSIONING is untouched by the second link.

        The PRD states: "Second, every store whose `active_standard_id` points at
        that now-superseded predecessor and whose `bms_status` is `ACTIVE` moves
        `ACTIVE → DEGRADED`, on the reasoning that its deployed setpoints no longer
        match governing doctrine; each such store's `version` increments."

        Design: Difficulty/transitive_cascade/standard_publish_supersession_cascade_depth_three
        """
        ctx = _two_stores_bound_to_one_published_standard(api)
        assert ctx["activated_a"]["bms_status"] == "ACTIVE"
        assert ctx["activated_a"]["energy_posture"] == "NORMAL"
        assert ctx["commissioned_b"]["bms_status"] == "COMMISSIONING"

        get_success_data(
            api.publish_setpoint_standard(
                ctx["successor"]["id"], make_energy_manager_headers("u_manager_tc3")
            )
        )

        store_a = fx.read_store(api, ctx["store_a_id"])
        store_b = fx.read_store(api, ctx["store_b_id"])

        assert store_a["bms_status"] == "DEGRADED"
        assert store_a["energy_posture"] == "CONSTRAINED"
        assert store_b["bms_status"] == "COMMISSIONING"
        assert store_b["energy_posture"] == "NORMAL"

    def test_the_stale_binding_is_deliberately_left_in_place(self, api):
        """Neither store has its active_standard_id rewritten.

        The PRD states: "When all of that passes, `bms_status` advances to
        `COMMISSIONING`, `active_standard_id` is set to the supplied `standard_id`,
        `version` increments by one and `updated_at` is refreshed." — commissioning
        is the only write of that binding, and publication's four ordered cascade
        links do not include it.

        Design: Difficulty/transitive_cascade/standard_publish_supersession_cascade_depth_three
        """
        ctx = _two_stores_bound_to_one_published_standard(api)

        get_success_data(
            api.publish_setpoint_standard(
                ctx["successor"]["id"], make_energy_manager_headers("u_manager_tc3")
            )
        )

        store_a = fx.read_store(api, ctx["store_a_id"])
        store_b = fx.read_store(api, ctx["store_b_id"])

        assert store_a["active_standard_id"] == ctx["predecessor"]["id"]
        assert store_b["active_standard_id"] == ctx["predecessor"]["id"]
