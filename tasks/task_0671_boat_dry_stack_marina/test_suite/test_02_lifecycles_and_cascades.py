"""State-machine lifecycles, cyclic transitions, transitive cascades, and
compensating invariants across launches, agreements, and the waitlist.

Difficulty queue: non_linear_state_machine, transitive_cascade, compensating_invariant.
Corner queue: state_machines.* instances.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_active_agreement, setup_racked_vessel_with_forklift,
    setup_scheduled_launch, setup_offered_waitlist_entry,
    create_launch, make_boat_owner_headers, TEST_USERS,
)

DM = TEST_USERS["dock_master_headers"]
BC = TEST_USERS["billing_clerk_headers"]


class TestLaunchCyclicScheduleUnschedule:
    """SCHEDULED -> REQUESTED -> SCHEDULED is a genuine cycle that releases then
    re-books a forklift slot."""

    def test_unschedule_reverts_to_requested(self, api):
        """PRD §3.5: "Unscheduling (SCHEDULED -> REQUESTED) is the cyclic revert:
        permitted only while the request is SCHEDULED, it releases the booked slot
        (the ForkliftSlot becomes RELEASED and its launch_request_id is cleared to
        null, freeing the interval) as a cascade, clears the request's
        forklift_slot_id to null, returns the request to REQUESTED, and increments
        its version."

        Design: Difficulty/non_linear_state_machine/launch_request_cyclic_schedule_unschedule_reschedule
        """
        ctx = setup_scheduled_launch()
        launch_id = ctx["launch"]["id"]
        slot_id_1 = ctx["slot_id"]
        reverted = validate_success(api.unschedule_launch(launch_id, DM), 200)
        assert reverted["status"] == "REQUESTED"
        slot1 = validate_success(api.get_forklift_slot(slot_id_1, DM), 200)
        assert slot1["status"] == "RELEASED", "unschedule releases the booked slot"

    def test_reschedule_after_unschedule_returns_to_scheduled(self, api):
        """PRD §3.5: "Scheduling a launch (REQUESTED -> SCHEDULED), a DockMaster
        action, is permitted only while the request is REQUESTED and only while the
        vessel's location_status is RACKED (the boat must be in its rack to launch)."
        PRD §3.5: "On success the system creates the slot in BOOKED status on the
        selected forklift, links it both ways (the slot's launch_request_id and the
        request's forklift_slot_id), computes launch_fee_cents, moves the request to
        SCHEDULED, and increments the request's version."

        Design: Difficulty/non_linear_state_machine/launch_request_cyclic_schedule_unschedule_reschedule
        """
        ctx = setup_scheduled_launch()
        launch_id = ctx["launch"]["id"]
        validate_success(api.unschedule_launch(launch_id, DM), 200)
        rescheduled = validate_success(api.schedule_launch(launch_id, DM), 200)
        assert rescheduled["status"] == "SCHEDULED", \
            "second schedule re-enters SCHEDULED"
        assert rescheduled["forklift_slot_id"] is not None


class TestVesselParallelStateDimensions:
    """location_status and billing_status evolve independently on the same vessel."""

    def test_splash_moves_only_location_dimension(self, api):
        """PRD §3.5: "On splash the booked slot's status becomes COMPLETED as the
        first cascade hop; caused by that slot completing, the vessel's
        location_status becomes IN_WATER as the second hop, while the rack stays
        OCCUPIED because the agreement still holds it - the vessel is merely absent."

        Design: Difficulty/non_linear_state_machine/vessel_parallel_location_and_billing_dimensions
        """
        ctx = setup_scheduled_launch(launch_overrides={
            "requested_window_start": "2026-04-02T10:00:00Z"})
        # Advance clock past slot window_start so splash is permitted.
        get_success_data(api_client.set_clock("2026-04-02T10:05:00Z", DM))
        validate_success(api.splash_launch(ctx["launch"]["id"], DM), 200)
        vessel = validate_success(api.get_vessel(ctx["vessel"]["id"], DM), 200)
        assert vessel["location_status"] == "IN_WATER", "splash moves location only"

    def test_splash_leaves_billing_dimension_unchanged(self, api):
        """PRD §3.1: "These two status dimensions are independent: location_status
        (one of OFF_SITE, RACKED, IN_WATER) tracks where the boat physically is,
        while billing_status (one of UNBILLED, ACTIVE_STORAGE, WINTER_HOLD,
        DELINQUENT, CLOSED) tracks its billing posture, and each evolves on its own
        as the workflows below fire."

        Design: Difficulty/non_linear_state_machine/vessel_parallel_location_and_billing_dimensions
        """
        ctx = setup_scheduled_launch(launch_overrides={
            "requested_window_start": "2026-04-02T10:00:00Z"})
        get_success_data(api_client.set_clock("2026-04-02T10:05:00Z", DM))
        validate_success(api.splash_launch(ctx["launch"]["id"], DM), 200)
        vessel = validate_success(api.get_vessel(ctx["vessel"]["id"], DM), 200)
        assert vessel["billing_status"] == "ACTIVE_STORAGE", \
            "splash does not touch the billing dimension"


class TestActivateCascadeDepth3:
    """activate -> Rack OCCUPIED (hop1) -> Vessel RACKED (hop2) + ACTIVE_STORAGE (hop3)."""

    def test_activate_sets_rack_occupied(self, api):
        """PRD §3.3: "As the first cascade hop, the rack's status becomes OCCUPIED,
        its current_agreement_id is set to this agreement's id, and the rack's
        version is incremented."

        Design: Difficulty/transitive_cascade/activate_cascade_rack_then_vessel_depth3
        """
        ctx = setup_active_agreement()  # activation already performed
        rack = validate_success(api.get_rack(ctx["rack"]["id"], DM), 200)
        assert rack["status"] == "OCCUPIED"
        assert rack["current_agreement_id"] == ctx["agreement"]["id"]

    def test_activate_cascades_vessel_racked_and_active_storage(self, api):
        """PRD §3.3: "As the second cascade hop - caused by the rack becoming
        occupied - the vessel's location_status becomes RACKED and its
        billing_status becomes ACTIVE_STORAGE."

        Design: Difficulty/transitive_cascade/activate_cascade_rack_then_vessel_depth3
        """
        ctx = setup_active_agreement()
        vessel = validate_success(api.get_vessel(ctx["vessel"]["id"], DM), 200)
        assert vessel["location_status"] == "RACKED"
        assert vessel["billing_status"] == "ACTIVE_STORAGE"


class TestCancelScheduledLaunchCascade:
    """cancel -> LaunchRequest CANCELLED (hop1) -> booked slot RELEASED (hop2)."""

    def test_cancel_scheduled_launch_sets_cancelled_and_clears_fee(self, api):
        """PRD §3.5: "From SCHEDULED, cancellation (permitted only from SCHEDULED)
        additionally releases the booked slot as compensation for the schedule's
        booking - the ForkliftSlot becomes RELEASED and its launch_request_id is
        cleared to null - clears the request's forklift_slot_id to null, and resets
        launch_fee_cents to zero before moving the request to CANCELLED."

        Design: Difficulty/transitive_cascade/cancel_scheduled_launch_releases_slot_depth2
        """
        ctx = setup_scheduled_launch()
        owner_headers = make_boat_owner_headers(ctx["owner"]["id"])
        cancelled = validate_success(
            api.cancel_launch(ctx["launch"]["id"], owner_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["launch_fee_cents"] == 0

    def test_cancel_scheduled_launch_releases_booked_slot(self, api):
        """PRD §3.5: "the ForkliftSlot becomes RELEASED and its launch_request_id is
        cleared to null - clears the request's forklift_slot_id to null"

        Design: Difficulty/transitive_cascade/cancel_scheduled_launch_releases_slot_depth2
        """
        ctx = setup_scheduled_launch()
        slot_id = ctx["slot_id"]
        owner_headers = make_boat_owner_headers(ctx["owner"]["id"])
        validate_success(api.cancel_launch(ctx["launch"]["id"], owner_headers), 200)
        slot = validate_success(api.get_forklift_slot(slot_id, DM), 200)
        assert slot["status"] == "RELEASED", "cancel from SCHEDULED releases the slot"


class TestLaunchCancelConservesForkliftSlots:
    """Conserved quantity: count of non-RELEASED (BOOKED) slots on the forklift
    returns to its pre-schedule value of 0 after cancel."""

    def test_booked_slot_count_returns_to_zero_after_cancel(self, api):
        """PRD §3.5: "From SCHEDULED, cancellation (permitted only from SCHEDULED)
        additionally releases the booked slot as compensation for the schedule's
        booking - the ForkliftSlot becomes RELEASED and its launch_request_id is
        cleared to null - clears the request's forklift_slot_id to null, and resets
        launch_fee_cents to zero before moving the request to CANCELLED."

        Design: Difficulty/compensating_invariant/launch_cancel_conserves_forklift_free_slot_count
        """
        ctx = setup_scheduled_launch()
        fl_id = ctx["forklift"]["id"]
        owner_headers = make_boat_owner_headers(ctx["owner"]["id"])
        validate_success(api.cancel_launch(ctx["launch"]["id"], owner_headers), 200)
        res = api.list_forklift_slots(DM, params={"forklift_id": fl_id, "status": "BOOKED"})
        data, meta = _paginated(api, res)
        assert meta["total_count"] == 0, \
            f"no BOOKED slots remain after cancel, got {meta['total_count']}"

    def test_cancelled_slot_is_released(self, api):
        """PRD §3.5: "the ForkliftSlot becomes RELEASED and its launch_request_id is
        cleared to null"

        Design: Difficulty/compensating_invariant/launch_cancel_conserves_forklift_free_slot_count
        """
        ctx = setup_scheduled_launch()
        slot_id = ctx["slot_id"]
        owner_headers = make_boat_owner_headers(ctx["owner"]["id"])
        validate_success(api.cancel_launch(ctx["launch"]["id"], owner_headers), 200)
        slot = validate_success(api.get_forklift_slot(slot_id, DM), 200)
        assert slot["status"] == "RELEASED"


class TestAgreementTerminateConservesRacks:
    """Conserved quantity: count of AVAILABLE racks in the marina restored to its
    pre-activate value of 1 after terminate."""

    def test_available_rack_count_restored_after_terminate(self, api):
        """PRD §3.3: "as compensation the rack's status returns to AVAILABLE, its
        current_agreement_id is cleared to null, and the rack's version is
        incremented; and the vessel's location_status becomes OFF_SITE while its
        billing_status becomes CLOSED."

        Design: Difficulty/compensating_invariant/agreement_terminate_conserves_available_rack_count
        """
        ctx = setup_active_agreement()
        marina_id = ctx["marina"]["id"]
        validate_success(api.terminate_storage_agreement(ctx["agreement"]["id"], DM), 200)
        res = api.list_racks(DM, params={"marina_id": marina_id, "status": "AVAILABLE"})
        data, meta = _paginated(api, res)
        assert meta["total_count"] == 1, \
            f"the single rack is AVAILABLE again after terminate, got {meta['total_count']}"

    def test_rack_status_available_after_terminate(self, api):
        """PRD §3.3: "as compensation the rack's status returns to AVAILABLE"

        Design: Difficulty/compensating_invariant/agreement_terminate_conserves_available_rack_count
        """
        ctx = setup_active_agreement()
        validate_success(api.terminate_storage_agreement(ctx["agreement"]["id"], DM), 200)
        rack = validate_success(api.get_rack(ctx["rack"]["id"], DM), 200)
        assert rack["status"] == "AVAILABLE"
        assert rack["current_agreement_id"] is None


# --------------------------------------------------------------------------- #
# Corner queue: state_machines.* instances
# --------------------------------------------------------------------------- #
class TestAgreementStateRules:

    def test_terminate_already_terminated_returns_invalid_state(self, api):
        """PRD §3.3: "A requested transition that is not legal from the agreement's
        current status is rejected with ERR_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/terminate_already_terminated_agreement_returns_invalid_state
        """
        ctx = setup_active_agreement()
        validate_success(api.terminate_storage_agreement(ctx["agreement"]["id"], DM), 200)
        res = api.terminate_storage_agreement(ctx["agreement"]["id"], DM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_winterize_pending_coi_agreement_invalid_state(self, api):
        """PRD §3.3: "Winterization (ACTIVE -> WINTERIZED) is permitted only while
        the agreement is ACTIVE and only while the bound vessel's location_status is
        RACKED"
        PRD §3.3: "A requested transition that is not legal from the agreement's
        current status is rejected with ERR_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/winterize_pending_coi_agreement_invalid_from
        """
        ctx = setup_active_agreement()  # build full env, then make a fresh PENDING one
        # Use a fresh PENDING_COI agreement (never activated) on a new rack.
        from test_helpers import create_rack, create_storage_agreement_payload
        rack2 = create_rack(ctx["marina"]["id"], bay_label="M-2")
        agr2 = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(ctx["vessel"]["id"], rack2["id"]), DM))
        res = api.winterize_storage_agreement(agr2["id"], DM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_winterize_then_reactivate_seasonal_loop(self, api):
        """PRD §3.3: "Reactivation (WINTERIZED -> ACTIVE) is permitted only while
        the agreement is WINTERIZED and only while the vessel's active_policy_id is
        non-null (else ERR_COI_NOT_VERIFIED, HTTP 422); it returns the agreement to
        ACTIVE and the vessel's billing_status to ACTIVE_STORAGE, incrementing the
        agreement's version."

        Design: Corner/state_machines/winterize_then_reactivate_seasonal_loop
        """
        ctx = setup_active_agreement()
        validate_success(api.winterize_storage_agreement(ctx["agreement"]["id"], DM), 200)
        reactivated = validate_success(
            api.reactivate_storage_agreement(ctx["agreement"]["id"], DM), 200)
        assert reactivated["status"] == "ACTIVE"
        vessel = validate_success(api.get_vessel(ctx["vessel"]["id"], DM), 200)
        assert vessel["billing_status"] == "ACTIVE_STORAGE"


class TestLaunchAndWaitlistStateRules:

    def test_splash_before_window_open_returns_slot_not_yet_open(self, api):
        """PRD §3.5: "Splashing (SCHEDULED -> SPLASHED) puts the boat in the water:
        permitted only while the request is SCHEDULED and only once the logical
        clock has reached or passed the booked slot's window_start - an earlier
        attempt is rejected with ERR_SLOT_NOT_YET_OPEN (HTTP 409)."

        Design: Corner/state_machines/splash_before_slot_window_open_returns_slot_not_yet_open
        """
        # Slot window_start 2026-04-02T10:00; clock left at 2026-04-01.
        ctx = setup_scheduled_launch(launch_overrides={
            "requested_window_start": "2026-04-02T10:00:00Z"})
        res = api.splash_launch(ctx["launch"]["id"], DM)
        validate_error(res, "ERR_SLOT_NOT_YET_OPEN")

    def test_waitlist_offer_lapse_releases_held_rack(self, api):
        """PRD §3.4: "A BillingClerk lapses an expired offer (OFFERED -> EXPIRED),
        permitted only while the entry is OFFERED and the logical clock has reached
        or passed offer_expires_at; as compensation for the held reservation, the
        offered rack's status returns to AVAILABLE, its rack version is incremented,
        the entry's offered_rack_id is cleared to null, and the entry moves to
        EXPIRED with its version incremented."

        Design: Corner/state_machines/waitlist_offer_lapse_releases_held_rack
        """
        ctx = setup_offered_waitlist_entry(size_class="SMALL", deposit_paid=True)
        # Advance the clock well past offer_expires_at.
        get_success_data(api_client.set_clock("2026-05-01T00:00:00Z", BC))
        lapsed = validate_success(api.lapse_waitlist_offer(ctx["entry"]["id"], BC), 200)
        assert lapsed["status"] == "EXPIRED"
        rack = validate_success(api.get_rack(ctx["rack"]["id"], DM), 200)
        assert rack["status"] == "AVAILABLE", "lapse releases the held rack"


def _paginated(api, res):
    from test_helpers import validate_paginated
    return validate_paginated(res)
