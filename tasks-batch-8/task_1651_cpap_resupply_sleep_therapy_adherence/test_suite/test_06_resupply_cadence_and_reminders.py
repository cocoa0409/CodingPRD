"""Resupply cadence gates, validation priority on order creation, and the
reminder look-ahead sweep.

Covers PRD §2.7 (evaluation order), §3.5 (cadence gate and reminder outreach).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_order_for_plan,
    create_resupply_order_payload,
    current_patient_version,
    dispense_component,
    finalize_non_compliant_report,
    get_patient,
    initiate_discontinuation_for,
    run_daily_sweep,
    set_clock,
    setup_therapy_patient,
    validate_error,
    validate_success,
)


class TestCadenceBoundary:
    """current_date >= next_eligible_on is inclusive."""

    def _dispensed_cushion(self):
        """CUSHION dispensed 2026-08-01 -> next_eligible_on 2026-08-31."""
        ctx = setup_therapy_patient()
        plan = dispense_component(ctx["patient"]["id"], "CUSHION")
        return ctx, plan

    def test_one_day_before_next_eligible_rejected(
            self, api, intake_coordinator_headers, ops_admin_headers):
        """PRD §3.5: "the order is eligible when the current date is on or
        after `next_eligible_on`; one day early is `ERR_CADENCE_NOT_MET`."

        Design: Difficulty/boundary_precision_check/cadence_boundary_next_eligible_on_inclusive
        """
        ctx, plan = self._dispensed_cushion()
        plan = validate_success(
            api.get_component_supply_plan(plan["id"], ops_admin_headers))
        # 2026-08-01 + 30 days = 2026-08-31.
        assert plan["next_eligible_on"] == "2026-08-31"

        set_clock("2026-08-30T00:00:00Z")
        res = api.create_resupply_order(
            create_resupply_order_payload(
                ctx["patient"]["id"], plan["id"], plan["quantity_per_cycle"],
                current_patient_version(ctx["patient"]["id"])),
            intake_coordinator_headers)
        validate_error(res, "ERR_CADENCE_NOT_MET", expected_status=409)

    def test_on_next_eligible_day_accepted(
            self, api, intake_coordinator_headers, ops_admin_headers):
        """PRD §2.8: "every threshold comparison in the system is **inclusive**
        unless explicitly stated otherwise: an order placed exactly on its
        plan's eligibility date is eligible"

        Design: Difficulty/boundary_precision_check/cadence_boundary_next_eligible_on_inclusive
        """
        ctx, plan = self._dispensed_cushion()
        set_clock("2026-08-31T00:00:00Z")
        order = create_order_for_plan(ctx["patient"]["id"], plan)
        assert order["auth_status"] == "PENDING_CLINICAL_CLEARANCE"


class TestHalfOpenCadenceWindow:
    """The interval [last_dispensed_on, next_eligible_on) stays occupied."""

    def _dispensed_mask(self):
        """MASK dispensed 2026-08-01 -> next_eligible_on 2026-10-30."""
        ctx = setup_therapy_patient()
        plan = dispense_component(ctx["patient"]["id"], "MASK")
        return ctx, plan

    def test_dispense_inside_occupied_interval_rejected(
            self, api, intake_coordinator_headers, ops_admin_headers):
        """PRD §3.5: "Otherwise the plan's `next_eligible_on` is the last
        dispense date plus the payer's cadence for that component type —
        `mask_cadence_days` for `MASK` ... and the order is eligible when the
        current date is on or after `next_eligible_on`; one day early is
        `ERR_CADENCE_NOT_MET`."

        Design: Difficulty/resource_temporal_overlap/component_resupply_half_open_cadence_window
        """
        ctx, plan = self._dispensed_mask()
        plan = validate_success(
            api.get_component_supply_plan(plan["id"], ops_admin_headers))
        # 2026-08-01 + 90 days = 2026-10-30.
        assert plan["next_eligible_on"] == "2026-10-30"

        set_clock("2026-10-29T00:00:00Z")
        res = api.create_resupply_order(
            create_resupply_order_payload(
                ctx["patient"]["id"], plan["id"], plan["quantity_per_cycle"],
                current_patient_version(ctx["patient"]["id"])),
            intake_coordinator_headers)
        validate_error(res, "ERR_CADENCE_NOT_MET", expected_status=409)

    def test_adjacent_dispense_at_interval_end_accepted(
            self, api, intake_coordinator_headers):
        """PRD §3.5: "the order is eligible when the current date is on or
        after `next_eligible_on`"

        Design: Difficulty/resource_temporal_overlap/component_resupply_half_open_cadence_window
        """
        ctx, plan = self._dispensed_mask()
        set_clock("2026-10-30T00:00:00Z")
        order = create_order_for_plan(ctx["patient"]["id"], plan)
        assert order["auth_status"] == "PENDING_CLINICAL_CLEARANCE"


class TestOrderCreationCheckPriority:
    """Patient state (p5) precedes plan state (p6) precedes cadence (p8)."""

    def _dispense_cushion_then_block(self, api, mode):
        """Patient with cushion dispensed 2026-08-01 (cadence unmet until
        2026-08-31), then blocked: mode='hold' suspends via non-compliance,
        mode='discontinuing' suspends via discontinuation."""
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        patient = ctx["patient"]
        plan = dispense_component(patient["id"], "CUSHION")
        if mode == "hold":
            finalize_non_compliant_report(patient["id"], ctx["enrollment"]["id"],
                                          window_end_on="2026-08-30",
                                          nights_reported=30, compliant_nights=5)
        else:
            initiate_discontinuation_for(patient["id"])
        set_clock("2026-08-15T00:00:00Z")
        return ctx, plan

    def test_patient_state_beats_plan_state_and_cadence_on_hold(
            self, api, intake_coordinator_headers):
        """PRD §2.7: "on order creation the patient-state check precedes the
        plan-state check, which precedes the quantity check, which precedes the
        cadence gate, which precedes the prior-authorization requirement."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_order_create
        """
        ctx, plan = self._dispense_cushion_then_block(api, mode="hold")
        patient = get_patient(ctx["patient"]["id"])
        # Triple failure: patient NON_COMPLIANT_HOLD, plan
        # SUSPENDED_NON_COMPLIANCE, cadence unmet (next_eligible 2026-08-31).
        assert patient["patient_status"] == "NON_COMPLIANT_HOLD"
        res = api.create_resupply_order(
            create_resupply_order_payload(
                patient["id"], plan["id"], plan["quantity_per_cycle"],
                patient["version"]),
            intake_coordinator_headers)
        validate_error(res, "ERR_PATIENT_NOT_IN_ACTIVE_THERAPY", expected_status=409)

    def test_patient_state_beats_plan_state_and_cadence_on_discontinuation(
            self, api, intake_coordinator_headers):
        """PRD §2.7: "on order creation the patient-state check precedes the
        plan-state check, which precedes the quantity check, which precedes the
        cadence gate, which precedes the prior-authorization requirement."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_order_create
        """
        ctx, plan = self._dispense_cushion_then_block(api, mode="discontinuing")
        patient = get_patient(ctx["patient"]["id"])
        # Triple failure: patient DISCONTINUING, plan SUSPENDED_DISCONTINUATION,
        # cadence unmet (next_eligible 2026-08-31).
        assert patient["patient_status"] == "DISCONTINUING"
        res = api.create_resupply_order(
            create_resupply_order_payload(
                patient["id"], plan["id"], plan["quantity_per_cycle"],
                patient["version"]),
            intake_coordinator_headers)
        validate_error(res, "ERR_PATIENT_NOT_IN_ACTIVE_THERAPY", expected_status=409)


class TestReminderLookahead:
    def test_reminder_fires_seven_days_before_eligibility(self, api):
        """PRD §3.5: "when the current date has reached seven days before that
        eligibility date, and the plan's `reminder_sent_on` is either null or
        earlier than that look-ahead date, the sweep emits a reminder event and
        stamps `reminder_sent_on` with the current date."

        Design: Corner/calculations/reminder_scheduling_seven_day_lookahead
        """
        ctx = setup_therapy_patient()
        # FILTER cadence 14: dispensed 2026-08-01 -> next_eligible 2026-08-15,
        # look-ahead date 2026-08-08.
        plan = dispense_component(ctx["patient"]["id"], "FILTER")
        assert plan["next_eligible_on"] == "2026-08-15"
        assert plan["reminder_sent_on"] is None

        set_clock("2026-08-07T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["reminders_sent"] == 0

        set_clock("2026-08-08T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["reminders_sent"] == 1

        refreshed = validate_success(api_client.get_component_supply_plan(
            plan["id"], TEST_USERS["ops_admin_headers"]))
        assert refreshed["reminder_sent_on"] == "2026-08-08"
