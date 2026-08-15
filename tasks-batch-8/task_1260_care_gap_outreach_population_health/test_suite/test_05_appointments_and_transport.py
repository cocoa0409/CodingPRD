"""Appointment scheduling, provider capacity, transport gating, and the no-show
cascade (PRD §3.5)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, assert_appointment,
    setup_panel_scenario, advance_clock, get_care_gap, book_appointment,
    create_transport, arrange_transport, create_appointment_payload,
    make_admin_headers, make_panel_manager_headers,
    make_transport_coordinator_headers,
)


class TestSlotValidation:
    def test_invalid_slot_rejected(self, api):
        """PRD §3.5: "and slot validity rejects with `ERR_INVALID_SLOT` (HTTP 400)
        when `slot_start_at` is not strictly before `slot_end_at` or when
        `slot_start_at` lies in the past relative to `current_business_date`."

        Design: Corner/validations/invalid_slot_rejected
        """
        scenario = setup_panel_scenario(num_members=1)
        gap_id = scenario["gaps"][0]["id"]
        resp = api.create_appointment(
            gap_id,
            create_appointment_payload(slot_start_at="2026-06-01T15:00:00Z",
                                       slot_end_at="2026-06-01T14:00:00Z"),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT)


class TestProviderSlotCapacity:
    def _three_gap_scenario(self):
        scenario = setup_panel_scenario(num_members=3)
        gaps = scenario["gaps"]
        pm = scenario["panel_manager_id"]
        slot = {"slot_start_at": "2026-06-01T14:00:00Z",
                "slot_end_at": "2026-06-01T15:00:00Z"}
        book_appointment(gaps[0]["id"], provider_capacity_per_slot=2,
                         panel_manager_id=pm, **slot)
        book_appointment(gaps[1]["id"], provider_capacity_per_slot=2,
                         panel_manager_id=pm, **slot)
        return scenario, gaps, pm, slot

    def test_provider_slot_capacity_aggregate_overlap(self, api):
        """PRD §3.5: "capacity rejects with `ERR_PROVIDER_SLOT_FULL` when the new
        window would push the count of overlapping appointments for that provider to
        or beyond the provider's per-slot capacity".
        PRD §3.5: "optionally `provider_capacity_per_slot`, the aggregate capacity
        that provider supports per overlapping slot, which defaults to 1 and thereby
        governs how much overbooking is tolerated."

        Two overlapping appointments already occupy a provider whose capacity is 2;
        a third overlapping booking is rejected.

        Design: Difficulty/resource_temporal_overlap/provider_slot_capacity_aggregate_overlap
        """
        scenario, gaps, pm, slot = self._three_gap_scenario()
        resp = api.create_appointment(
            gaps[2]["id"], create_appointment_payload(**slot),
            make_panel_manager_headers(pm))
        validate_error(resp, ApiErrorId.ERR_PROVIDER_SLOT_FULL)

    def test_provider_slot_capacity_non_overlapping_allowed(self, api):
        """PRD §3.5: "capacity rejects with `ERR_PROVIDER_SLOT_FULL` when the new
        window would push the count of overlapping appointments for that provider to
        or beyond the provider's per-slot capacity".

        A non-overlapping window for the same provider does not count against the
        overlapping occupancy and is accepted.

        Design: Difficulty/resource_temporal_overlap/provider_slot_capacity_aggregate_overlap
        """
        scenario, gaps, pm, _ = self._three_gap_scenario()
        resp = api.create_appointment(
            gaps[2]["id"],
            create_appointment_payload(slot_start_at="2026-06-02T14:00:00Z",
                                       slot_end_at="2026-06-02T15:00:00Z"),
            make_panel_manager_headers(pm))
        data = validate_success(resp, 201)
        assert_appointment(data)
        assert data["status"] == "SCHEDULED"


class TestConfirmRequiresTransportArranged:
    def _scenario_with_requested_transport(self, api):
        scenario = setup_panel_scenario(num_members=1)
        pm = scenario["panel_manager_id"]
        appointment = book_appointment(scenario["gaps"][0]["id"], panel_manager_id=pm)
        assist = create_transport(appointment["id"])
        return scenario, pm, appointment, assist

    def test_appointment_confirm_requires_transport_arranged(self, api):
        """PRD §3.5: "Confirming moves `SCHEDULED` to `CONFIRMED`; when a
        transportation assist exists for the appointment, confirmation is blocked
        unless the assist is `ARRANGED`, failing with `ERR_TRANSPORT_NOT_ARRANGED`."

        Design: Difficulty/cross_entity_state_dependency/appointment_confirm_requires_transport_arranged
        """
        scenario, pm, appointment, assist = self._scenario_with_requested_transport(api)
        assert assist["status"] == "REQUESTED"
        resp = api.confirm_appointment(appointment["id"], make_panel_manager_headers(pm))
        validate_error(resp, ApiErrorId.ERR_TRANSPORT_NOT_ARRANGED)

    def test_appointment_confirm_succeeds_once_transport_arranged(self, api):
        """PRD §3.5: "Confirming moves `SCHEDULED` to `CONFIRMED`; when a
        transportation assist exists for the appointment, confirmation is blocked
        unless the assist is `ARRANGED`, failing with `ERR_TRANSPORT_NOT_ARRANGED`."
        PRD §3.5: "The assist is born `REQUESTED`; the coordinator arranges it
        (`REQUESTED` → `ARRANGED`)".

        Design: Difficulty/cross_entity_state_dependency/appointment_confirm_requires_transport_arranged
        """
        scenario, pm, appointment, assist = self._scenario_with_requested_transport(api)
        arrange_transport(assist["id"])
        resp = api.confirm_appointment(appointment["id"], make_panel_manager_headers(pm))
        data = validate_success(resp, 200)
        assert data["status"] == "CONFIRMED", (
            f"Expected CONFIRMED, got {data['status']}")


class TestNoShowCascade:
    def _scenario_with_arranged_transport_past_slot(self, api):
        scenario = setup_panel_scenario(num_members=1)
        pm = scenario["panel_manager_id"]
        appointment = book_appointment(
            scenario["gaps"][0]["id"], panel_manager_id=pm,
            slot_start_at="2026-05-05T14:00:00Z", slot_end_at="2026-05-05T15:00:00Z")
        assist = create_transport(appointment["id"], pickup_at="2026-05-05T13:00:00Z")
        arrange_transport(assist["id"])
        # Move the registry clock strictly past slot_end_at.
        advance_clock(scenario["registry"]["id"], "2026-05-06T00:00:00Z")
        return scenario, pm, appointment, assist

    def test_no_show_cascade_cancels_transport(self, api):
        """PRD §3.5: "Marking a no-show requires the appointment to be in `SCHEDULED`
        or `CONFIRMED` and the clock to have strictly passed `slot_end_at`".
        PRD §3.5: "A no-show sets the appointment to `NO_SHOW`, reverts the gap to
        `OUTREACH_IN_PROGRESS` with its `priority_score` recomputed including the
        8-point no-show strike bonus, cancels any linked transportation assist in
        `REQUESTED` or `ARRANGED`, and appends an automatic outreach attempt with
        channel `CALL`, outcome `NO_ANSWER`, and `notes` set to `auto:no-show`; this
        auto-attempt increments the gap's `attempt_count` by one and therefore counts
        toward cadence and the attempt cap."

        Design: Difficulty/transitive_cascade/no_show_cascade_cancels_transport
        """
        scenario, pm, appointment, assist = self._scenario_with_arranged_transport_past_slot(api)
        gap_id = scenario["gaps"][0]["id"]
        resp = api.mark_no_show_appointment(appointment["id"],
                                            make_panel_manager_headers(pm))
        data = validate_success(resp, 200)
        assert data["status"] == "NO_SHOW", f"Expected NO_SHOW, got {data['status']}"
        assist_after = get_success_data(
            api.get_transportation_assist(assist["id"],
                                          make_transport_coordinator_headers()))
        assert assist_after["status"] == "CANCELLED", (
            f"Linked ARRANGED assist must be CANCELLED, got {assist_after['status']}")
        gap_after = get_care_gap(gap_id)
        assert gap_after["status"] == "OUTREACH_IN_PROGRESS", (
            f"Gap must revert to OUTREACH_IN_PROGRESS, got {gap_after['status']}")
        assert gap_after["attempt_count"] == 1, (
            f"The auto no-show attempt counts toward cadence: expected attempt_count 1, "
            f"got {gap_after['attempt_count']}")

    def test_no_show_appends_synthetic_attempt(self, api):
        """PRD §3.5: "A no-show sets the appointment to `NO_SHOW`, reverts the gap to
        `OUTREACH_IN_PROGRESS` with its `priority_score` recomputed including the
        8-point no-show strike bonus, cancels any linked transportation assist in
        `REQUESTED` or `ARRANGED`, and appends an automatic outreach attempt with
        channel `CALL`, outcome `NO_ANSWER`, and `notes` set to `auto:no-show`; this
        auto-attempt increments the gap's `attempt_count` by one and therefore counts
        toward cadence and the attempt cap."

        Design: Difficulty/transitive_cascade/no_show_cascade_cancels_transport
        """
        scenario, pm, appointment, assist = self._scenario_with_arranged_transport_past_slot(api)
        gap_id = scenario["gaps"][0]["id"]
        get_success_data(api.mark_no_show_appointment(appointment["id"],
                                                      make_panel_manager_headers(pm)))
        attempts = get_success_data(api.list_gap_outreach_attempts(
            gap_id, make_admin_headers()))
        assert len(attempts) == 1, f"Expected 1 synthetic attempt, got {len(attempts)}"
        auto = attempts[0]
        assert auto["channel"] == "CALL"
        assert auto["outcome"] == "NO_ANSWER"
        assert auto.get("notes") == "auto:no-show", (
            f"Synthetic attempt must carry notes='auto:no-show', got {auto.get('notes')!r}")


class TestTransportationRbac:
    def test_transportation_coordinator_can_arrange_assist(self, api):
        """PRD §3.5: "The assist is born `REQUESTED`; the coordinator arranges it
        (`REQUESTED` → `ARRANGED`), completes it (`ARRANGED` → `COMPLETED`, permitted
        only once the parent appointment is itself `COMPLETED`), or cancels it from
        `REQUESTED` or `ARRANGED` with an optional `reason`."

        Design: Corner/rbac/transportation_coordinator_can_arrange_assist
        """
        scenario = setup_panel_scenario(num_members=1)
        appointment = book_appointment(scenario["gaps"][0]["id"],
                                       panel_manager_id=scenario["panel_manager_id"])
        assist = create_transport(appointment["id"])
        resp = api.arrange_transportation_assist(
            assist["id"], make_transport_coordinator_headers())
        data = validate_success(resp, 200)
        assert data["status"] == "ARRANGED", f"Expected ARRANGED, got {data['status']}"
