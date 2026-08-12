"""Vendor lifecycle (activate/suspend/exit), tier-cadenced monitoring-cycle
scheduling, overdue promotion boundaries, waive tier gating, and the
next_monitoring_due_at reconciliation."""
from test_helpers import (
    ApiErrorId,
    create_dd_package,
    create_engagement,
    create_vendor,
    get_vendor,
    iso_after_days,
    list_cycles,
    parse_iso_instant,
    reset_clock,
    setup_active_engagement,
    setup_active_vendor,
    submit_dd_package,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import VRM, RO, ADMIN, DIRECTOR

CLOCK = "2026-05-01T00:00:00Z"


class TestVendorActivation:
    def test_activate_valid_transition_schedules_first_cycle(self, api):
        """PRD §3.6: "On activation the server recomputes
        `composite_risk_score`, creates the first `MonitoringCycle` with
        `due_at` derived from the tier cadence (see §3.7), and sets
        `next_monitoring_due_at` to that cycle's `due_at`."
        PRD §3.7: "A `TIER_1_CRITICAL` vendor is monitored every 90 days,
        `TIER_2_HIGH` every 180 days, `TIER_3_STANDARD` every 365 days, and
        `TIER_4_LOW` every 730 days. The first cycle is anchored to the
        vendor's activation instant; subsequent cycles are anchored to the
        previous cycle's `completed_at`."

        Design: Corner/state_machines/vendor_activate_valid_transition
        """
        ctx = setup_active_engagement(vendor_name="ActVendor")
        activated = validate_success(api.activate_vendor(ctx["vendor"]["id"], RO), 200)
        assert activated["status"] == "ACTIVE"

        expected_due = iso_after_days(CLOCK, 365)  # TIER_3 cadence from activation instant
        assert parse_iso_instant(activated["next_monitoring_due_at"]) == expected_due

        cycles, _meta = list_cycles(ctx["vendor"]["id"])
        assert len(cycles) == 1
        assert cycles[0]["status"] == "SCHEDULED"
        assert cycles[0]["cycle_index"] == 1
        assert cycles[0]["cadence_days"] == 365
        assert parse_iso_instant(cycles[0]["due_at"]) == expected_due

    def test_activate_rejected_without_active_engagement(self, api):
        """PRD §3.6: "Activation requires the vendor to be in `ONBOARDING`
        (otherwise `ERR_VENDOR_NOT_ONBOARDING`, HTTP 409), requires at least
        one engagement in `ACTIVE` (otherwise `ERR_NO_ACTIVE_ENGAGEMENT`,
        HTTP 422), and requires the absence of any `OPEN` or `REOPENED`
        incident with severity `SEV_1` on any of the vendor's engagements
        (otherwise `ERR_OPEN_SEV1_INCIDENT`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/vendor_activate_depends_on_engagement_active
        """
        reset_clock()
        vendor = create_vendor(name="XDep2 Vendor")
        engagement = create_engagement(vendor["id"], code="XD2-E1", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="xd2")
        submit_dd_package(package["id"])  # engagement DD_IN_PROGRESS only

        res = api.activate_vendor(vendor["id"], RO)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_ENGAGEMENT.value)

    def test_activate_succeeds_once_engagement_goes_active(self, api):
        """PRD §3.6: "Activation requires the vendor to be in `ONBOARDING`
        (otherwise `ERR_VENDOR_NOT_ONBOARDING`, HTTP 409), requires at least
        one engagement in `ACTIVE` (otherwise `ERR_NO_ACTIVE_ENGAGEMENT`,
        HTTP 422), and requires the absence of any `OPEN` or `REOPENED`
        incident with severity `SEV_1` on any of the vendor's engagements
        (otherwise `ERR_OPEN_SEV1_INCIDENT`, HTTP 422)."
        PRD §3.4: "the engagement transitions `CONTRACTING → ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/vendor_activate_depends_on_engagement_active
        """
        ctx = setup_active_engagement(vendor_name="XDep2b Vendor")
        activated = validate_success(api.activate_vendor(ctx["vendor"]["id"], RO), 200)
        assert activated["status"] == "ACTIVE"

    def test_exited_vendor_is_terminal(self, api):
        """PRD §3.6: "Suspension moves a vendor `ACTIVE → SUSPENDED`. It
        requires the vendor to be `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`,
        HTTP 409) and at least one triggering condition: an `OPEN` or
        `REOPENED` `SEV_1` incident on any engagement, any monitoring cycle
        that has been `OVERDUE` for more than 30 days, or a `FAILED`
        business-continuity test on a `TIER_1_CRITICAL` engagement."
        PRD §3.6: "Vendor exit moves `ACTIVE → EXITED`."

        Design: Corner/state_machines/vendor_terminal_state_lockdown
        """
        ctx = setup_active_vendor(vendor_name="TermV")
        e_id = ctx["engagement"]["id"]
        v_id = ctx["vendor"]["id"]
        validate_success(api.initiate_exit(e_id, VRM), 200)
        validate_success(api.finalize_exit(e_id, RO), 200)
        exited = validate_success(api.exit_vendor(v_id, RO), 200)
        assert exited["status"] == "EXITED"

        res = api.suspend_vendor(v_id, RO)
        validate_error(res, ApiErrorId.ERR_VENDOR_NOT_ACTIVE.value)


class TestMonitoringCycleScheduling:
    def test_single_open_cycle_after_activation(self, api):
        """PRD §3.7: "Cycle windows are half-open: at most one cycle per vendor
        may be in `SCHEDULED` or `IN_PROGRESS` at any instant, and a new
        cycle's window must not overlap the window of any prior non-`WAIVED`
        cycle on the same vendor. Adjacent windows with no gap are permitted."

        Design: Difficulty/resource_temporal_overlap/monitoring_cycle_half_open_window_uniqueness
        """
        ctx = setup_active_vendor(vendor_name="Cycle Win Vendor")
        cycles, _meta = list_cycles(ctx["vendor"]["id"])
        open_cycles = [c for c in cycles if c["status"] in ("SCHEDULED", "IN_PROGRESS")]
        assert len(cycles) == 1
        assert len(open_cycles) == 1
        assert cycles[0]["cycle_index"] == 1
        assert parse_iso_instant(cycles[0]["due_at"]) == iso_after_days(CLOCK, 365)

    def test_completion_schedules_next_cycle_anchored_to_completed_at(self, api):
        """PRD §3.7: "The first cycle is anchored to the vendor's activation
        instant; subsequent cycles are anchored to the previous cycle's
        `completed_at`."
        PRD §3.7: "In both cases the server stamps `completed_at`, schedules
        the next cycle per tier cadence anchored to this `completed_at`, and
        updates `next_monitoring_due_at`."

        Design: Difficulty/resource_temporal_overlap/monitoring_cycle_half_open_window_uniqueness
        """
        ctx = setup_active_vendor(vendor_name="Cycle Win Vendor 2")
        first = ctx["cycles"][0]
        validate_success(api.begin_monitoring_cycle(first["id"], RO), 200)
        # Advance within the window so completion is on time.
        validate_success(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN), 200)
        completed = validate_success(
            api.complete_monitoring_cycle(first["id"], RO, {"findings_summary": "OK"}), 200
        )
        assert completed["status"] == "COMPLETED_ON_TIME"

        cycles, _meta = list_cycles(ctx["vendor"]["id"])
        scheduled = [c for c in cycles if c["status"] == "SCHEDULED"]
        assert len(scheduled) == 1, "exactly one open cycle after completion"
        new_cycle = scheduled[0]
        assert new_cycle["cycle_index"] == 2
        # Anchor = previous completed_at (2026-06-01) + 365 days.
        assert parse_iso_instant(new_cycle["due_at"]) == iso_after_days("2026-06-01T00:00:00Z", 365)
        vendor = get_vendor(ctx["vendor"]["id"])
        assert parse_iso_instant(vendor["next_monitoring_due_at"]) == parse_iso_instant(new_cycle["due_at"])

    def test_overdue_promotion_boundary(self, api):
        """PRD §2.8: "any `MonitoringCycle` still in `SCHEDULED` or
        `IN_PROGRESS` whose `due_at` is earlier than the new clock value
        transitions to `OVERDUE`"
        PRD §3.7: "A `SCHEDULED` or `IN_PROGRESS` cycle is promoted to
        `OVERDUE` by the system the moment the logical clock advances past its
        `due_at`; this promotion also triggers a `tier_posture` recompute."

        Design: Corner/calculations/monitoring_cycle_overdue_threshold_constants
        """
        ctx = setup_active_vendor(vendor_name="OdueV")
        cycle_id = ctx["cycles"][0]["id"]
        due_at = ctx["cycles"][0]["due_at"]

        # At exactly due_at: not earlier than the clock value, still SCHEDULED.
        validate_success(api.set_clock({"to_iso8601": "2027-05-01T00:00:00Z"}, ADMIN), 200)
        at_due = validate_success(api.get_monitoring_cycle(cycle_id, RO), 200)
        assert at_due["status"] == "SCHEDULED"
        assert parse_iso_instant(due_at) == iso_after_days(CLOCK, 365)

        # One second past due_at: promoted to OVERDUE.
        validate_success(api.set_clock({"to_iso8601": "2027-05-01T00:00:01Z"}, ADMIN), 200)
        after_due = validate_success(api.get_monitoring_cycle(cycle_id, RO), 200)
        assert after_due["status"] == "OVERDUE"

    def test_waive_forbidden_on_tier1_vendor(self, api):
        """PRD §3.7: "A `ComplianceDirector` may waive a scheduled cycle, but
        only for `TIER_4_LOW` vendors; attempts on other tiers are rejected
        with `ERR_WAIVE_TIER_FORBIDDEN` (HTTP 422), and attempts on
        non-`SCHEDULED` cycles are rejected with `ERR_CYCLE_NOT_SCHEDULED`."

        Design: Corner/validations/waive_monitoring_cycle_forbidden_on_tier1
        """
        ctx = setup_active_vendor(
            vendor_name="WaiveT1",
            category="CLOUD_INFRA",
            sensitivity="REGULATED",
            vendor_tier="TIER_1_CRITICAL",
            contract_overrides={
                "has_right_to_audit_clause": True,
                "has_exit_plan_section": True,
                "sla_uptime_pct": 99.99,
            },
        )
        cycle_id = ctx["cycles"][0]["id"]
        res = api.waive_monitoring_cycle(cycle_id, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_WAIVE_TIER_FORBIDDEN.value)


class TestNextMonitoringDueReconciliation:
    def test_next_monitoring_due_set_on_activation_and_cleared_on_suspend(self, api):
        """PRD §3.6: "On activation the server recomputes
        `composite_risk_score`, creates the first `MonitoringCycle` with
        `due_at` derived from the tier cadence (see §3.7), and sets
        `next_monitoring_due_at` to that cycle's `due_at`."
        PRD §3.6: "On suspension every `ACTIVE` engagement on the vendor has
        its `risk_attention_state` set to `UNDER_REVIEW`, and
        `next_monitoring_due_at` is cleared to null because no new cycles are
        scheduled while suspended."
        PRD §3.6: "It requires the vendor to be `ACTIVE` (otherwise
        `ERR_VENDOR_NOT_ACTIVE`, HTTP 409) and at least one triggering
        condition: an `OPEN` or `REOPENED` `SEV_1` incident on any engagement,
        any monitoring cycle that has been `OVERDUE` for more than 30 days, or
        a `FAILED` business-continuity test on a `TIER_1_CRITICAL` engagement."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_next_monitoring_due_at
        """
        ctx = setup_active_vendor(vendor_name="DR")
        vendor = get_vendor(ctx["vendor"]["id"])
        assert parse_iso_instant(vendor["next_monitoring_due_at"]) == iso_after_days(CLOCK, 365)

        # Create the triggering condition: cycle OVERDUE for more than 30 days.
        # Cycle due 2027-05-01; at 2027-06-15 it has been overdue for 45 days.
        validate_success(api.set_clock({"to_iso8601": "2027-06-15T00:00:00Z"}, ADMIN), 200)
        suspended = validate_success(api.suspend_vendor(ctx["vendor"]["id"], RO), 200)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["next_monitoring_due_at"] is None
