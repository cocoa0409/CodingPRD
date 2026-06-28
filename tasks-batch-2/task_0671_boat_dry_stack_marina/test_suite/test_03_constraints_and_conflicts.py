"""Validation precedence, cross-entity preconditions, and resource temporal
overlap (forklift slots, rack occupancy).

Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap, boundary_precision_check (forklift adjacency).
Corner queue: validations.* instances.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, setup_pending_agreement, setup_racked_vessel_with_forklift,
    setup_active_agreement, setup_owner_and_vessel,
    create_marina, create_forklift, create_rack, create_owner, create_vessel,
    create_verified_policy, rack_version, create_launch,
    create_storage_agreement_payload, create_rack_payload,
    make_boat_owner_headers, TEST_USERS,
)

DM = TEST_USERS["dock_master_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# NOTE — difficulty instance priority_pair_validation_conflict /
# coi_vs_dimensions_on_activate is SKIPPED (no test emitted). Its recipe requires a
# PENDING_COI agreement to exist on a rack the vessel does NOT fit (beam 15.00 >
# max_beam 11.00) so that activate can fail on BOTH the COI gate and the dimension
# fit. But PRD §3.3 states the misfit is rejected at agreement CREATE time
# ("at creation the system checks that the vessel physically fits the named rack ...
# rejecting a misfit with ERR_VESSEL_DIMENSIONS_EXCEED_RACK"), and the PRD exposes no
# rack-resize endpoint, so a PRD-only implementer can never reach an activate where
# both failures co-exist. The activate-time precedence outcome is therefore not
# uniquely derivable from PRD prose -> skipped per the PRD-first Core rule. (The
# COI-alone-on-activate path is covered under cross_entity_state_dependency, and the
# dimension-fit-at-create path under the corner stub's owning instance.)


class TestScheduleValidationPrecedence:
    """Forklift capacity is evaluated before slot scheduling conflicts, so the
    capacity error wins when both fail on a single forklift."""

    def test_forklift_capacity_error_beats_slot_conflict_on_schedule(self, api):
        """PRD §2.5: "the system evaluate the domain-specific business rules -
        insurance, forklift capacity, dimension fit, rack availability, scheduling
        conflicts"
        PRD §3.5: "If no forklift has the lift capacity for the vessel, the request
        is rejected with ERR_FORKLIFT_CAPACITY_EXCEEDED (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/slot_conflict_vs_forklift_capacity_on_schedule
        """
        # One weak forklift (max_lift 4000). Light vessel (3000) is scheduled first,
        # occupying the forklift's only slot at 10:00. Heavy vessel (9000 > 4000)
        # then requests the same 10:00 window: capacity AND slot-conflict both fail.
        marina = create_marina()
        create_forklift(marina["id"], label="FL-weak", max_lift_weight_lbs=4000)
        rack1 = create_rack(marina["id"], bay_label="M-1")
        rack2 = create_rack(marina["id"], bay_label="M-2")
        owner = create_owner(marina["id"])
        owner_h = make_boat_owner_headers(owner["id"])

        light = create_vessel(marina["id"], owner["id"], name="Light",
                              loa_ft=22.00, beam_ft=8.00, dry_weight_lbs=3000)
        heavy = create_vessel(marina["id"], owner["id"], name="Heavy",
                              loa_ft=25.00, beam_ft=9.00, dry_weight_lbs=9000)
        create_verified_policy(light["id"])
        create_verified_policy(heavy["id"])

        agr_light = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(light["id"], rack1["id"]), DM))
        get_success_data(api.activate_storage_agreement(
            agr_light["id"], rack_version(rack1["id"]), DM))
        agr_heavy = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(heavy["id"], rack2["id"]), DM))
        get_success_data(api.activate_storage_agreement(
            agr_heavy["id"], rack_version(rack2["id"]), DM))

        ll = create_launch(light["id"], owner["id"],
                           requested_window_start="2026-04-02T10:00:00Z")
        get_success_data(api.schedule_launch(ll["id"], DM))
        hl = create_launch(heavy["id"], owner["id"],
                           requested_window_start="2026-04-02T10:00:00Z")
        res = api.schedule_launch(hl["id"], DM)
        validate_error(res, "ERR_FORKLIFT_CAPACITY_EXCEEDED")

    def test_forklift_capacity_error_when_no_forklift_can_lift(self, api):
        """PRD §3.5: "The system must be able to book a ForkliftSlot at the
        requested_window_start on some AVAILABLE forklift whose max_lift_weight_lbs
        is at least the vessel's dry_weight_lbs. If no forklift has the lift capacity
        for the vessel, the request is rejected with ERR_FORKLIFT_CAPACITY_EXCEEDED
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/slot_conflict_vs_forklift_capacity_on_schedule
        """
        # Single forklift, no slot booked, but it cannot lift the vessel.
        ctx = setup_racked_vessel_with_forklift(
            forklift_overrides={"label": "FL-weak", "max_lift_weight_lbs": 4000},
            vessel_overrides={"loa_ft": 25.00, "beam_ft": 9.00, "dry_weight_lbs": 9000})
        launch = create_launch(ctx["vessel"]["id"], ctx["owner"]["id"])
        res = api.schedule_launch(launch["id"], DM)
        validate_error(res, "ERR_FORKLIFT_CAPACITY_EXCEEDED")


class TestActivateRequiresVerifiedCoi:
    """StorageAgreement activate depends on Vessel.active_policy_id (COI gate)."""

    def test_activate_blocked_while_policy_submitted(self, api):
        """PRD §2.9: "Any operation that requires insurance - activating an
        agreement, reactivating a winterized agreement, or accepting a waitlist offer
        - checks that the vessel's active_policy_id is not null, and rejects the
        request with ERR_COI_NOT_VERIFIED (HTTP 422) when it is null."

        Design: Difficulty/cross_entity_state_dependency/agreement_activate_requires_vessel_active_policy
        """
        # vessel has a SUBMITTED (not verified) policy -> active_policy_id null.
        ctx = setup_pending_agreement(with_verified_coi=False,
                                      vessel_overrides={"name": "NoCOI"})
        get_success_data(api_client.create_insurance_policy(
            {"vessel_id": ctx["vessel"]["id"], "carrier_name": "Acme",
             "liability_limit_cents": 50000000,
             "effective_from": "2026-01-01T00:00:00Z",
             "effective_to": "2027-01-01T00:00:00Z"}, BC))
        rv = rack_version(ctx["rack"]["id"])
        res = api.activate_storage_agreement(ctx["agreement"]["id"], rv, DM)
        validate_error(res, "ERR_COI_NOT_VERIFIED")

    def test_activate_succeeds_after_coi_verified(self, api):
        """PRD §3.2: "On verification the policy moves to VERIFIED; if the vessel has
        no other verified policy covering the clock, the vessel's active_policy_id is
        set to this policy's id."
        PRD §3.3: "It requires the vessel's active_policy_id to be non-null (else
        ERR_COI_NOT_VERIFIED, HTTP 422); it requires the target rack to be AVAILABLE
        (else ERR_RACK_NOT_AVAILABLE, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/agreement_activate_requires_vessel_active_policy
        """
        ctx = setup_pending_agreement(with_verified_coi=False,
                                      vessel_overrides={"name": "NoCOI"})
        policy = get_success_data(api_client.create_insurance_policy(
            {"vessel_id": ctx["vessel"]["id"], "carrier_name": "Acme",
             "liability_limit_cents": 50000000,
             "effective_from": "2026-01-01T00:00:00Z",
             "effective_to": "2027-01-01T00:00:00Z"}, BC))
        # First activate fails (SUBMITTED), then verify, then activate succeeds.
        rv = rack_version(ctx["rack"]["id"])
        validate_error(api.activate_storage_agreement(ctx["agreement"]["id"], rv, DM),
                       "ERR_COI_NOT_VERIFIED")
        get_success_data(api.verify_insurance_policy(policy["id"], BC))
        rv2 = rack_version(ctx["rack"]["id"])
        activated = validate_success(
            api.activate_storage_agreement(ctx["agreement"]["id"], rv2, DM), 200)
        assert activated["status"] == "ACTIVE"


class TestScheduleRequiresVesselRacked:
    """LaunchRequest schedule depends on Vessel.location_status == RACKED."""

    def test_schedule_off_site_vessel_rejected(self, api):
        """PRD §3.5: "Scheduling a launch (REQUESTED -> SCHEDULED), a DockMaster
        action, is permitted only while the request is REQUESTED and only while the
        vessel's location_status is RACKED (the boat must be in its rack to launch)."
        PRD §3.5: "A transition requested from a status where it is not defined is
        rejected with ERR_INVALID_STATE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/launch_schedule_requires_vessel_racked
        """
        # OFF_SITE vessel (no agreement), a forklift exists, REQUESTED launch.
        marina = create_marina()
        create_forklift(marina["id"])
        owner = create_owner(marina["id"])
        vessel = create_vessel(marina["id"], owner["id"], name="Beached",
                               loa_ft=25.00, beam_ft=9.00, dry_weight_lbs=5000)
        launch = create_launch(vessel["id"], owner["id"])
        res = api.schedule_launch(launch["id"], DM)
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_launch_request(launch["id"], DM), 200)
        assert after["status"] == "REQUESTED", "launch stays REQUESTED on failure"

    def test_schedule_succeeds_when_vessel_racked(self, api):
        """PRD §3.5: "Scheduling a launch (REQUESTED -> SCHEDULED), a DockMaster
        action, is permitted only while the request is REQUESTED and only while the
        vessel's location_status is RACKED (the boat must be in its rack to launch)."

        Design: Difficulty/cross_entity_state_dependency/launch_schedule_requires_vessel_racked
        """
        # With the vessel RACKED (ACTIVE agreement) the very same scheduling succeeds,
        # confirming the RACKED precondition is what gates it.
        ctx = setup_racked_vessel_with_forklift()
        launch = create_launch(ctx["vessel"]["id"], ctx["owner"]["id"])
        scheduled = validate_success(api.schedule_launch(launch["id"], DM), 200)
        assert scheduled["status"] == "SCHEDULED"


class TestForkliftSlotTemporalOverlap:
    """Forklift busy interval [window_start, window_start+service+buffer) with
    half-open adjacency at busy_until allowed."""

    def _two_racked_vessels_with_one_forklift(self):
        marina = create_marina(name="Bayfront",
                               forklift_service_minutes=30, forklift_buffer_minutes=15)
        create_forklift(marina["id"], label="FL-1", max_lift_weight_lbs=15000)
        rackA = create_rack(marina["id"], bay_label="M-1")
        rackB = create_rack(marina["id"], bay_label="M-2")
        owner = create_owner(marina["id"])
        vA = create_vessel(marina["id"], owner["id"], name="A",
                           loa_ft=24.00, beam_ft=9.00, dry_weight_lbs=5000)
        vB = create_vessel(marina["id"], owner["id"], name="B",
                           loa_ft=24.00, beam_ft=9.00, dry_weight_lbs=5000)
        create_verified_policy(vA["id"])
        create_verified_policy(vB["id"])
        agrA = get_success_data(api_client.create_storage_agreement(
            create_storage_agreement_payload(vA["id"], rackA["id"]), DM))
        get_success_data(api_client.activate_storage_agreement(
            agrA["id"], rack_version(rackA["id"]), DM))
        agrB = get_success_data(api_client.create_storage_agreement(
            create_storage_agreement_payload(vB["id"], rackB["id"]), DM))
        get_success_data(api_client.activate_storage_agreement(
            agrB["id"], rack_version(rackB["id"]), DM))
        # Schedule A at 10:00 (busy_until 10:45).
        lA = create_launch(vA["id"], owner["id"],
                           requested_window_start="2026-04-02T10:00:00Z")
        get_success_data(api_client.schedule_launch(lA["id"], DM))
        return marina, owner, vB

    def test_overlap_inside_busy_until_rejected(self, api):
        """PRD §3.5: "The new slot's busy interval - the half-open span from
        window_start up to but not including busy_until - must not overlap any
        non-RELEASED slot on the same forklift; adjacency at busy_until (one slot's
        busy interval ending exactly when the next begins) is allowed. When every
        capacity-eligible forklift has an overlapping live slot, scheduling is
        rejected with ERR_FORKLIFT_SLOT_CONFLICT (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/forklift_slot_overlap_with_buffer
        """
        marina, owner, vB = self._two_racked_vessels_with_one_forklift()
        # 10:44 falls inside the 10:00 slot's busy_until 10:45 -> conflict.
        lB = create_launch(vB["id"], owner["id"],
                           requested_window_start="2026-04-02T10:44:00Z")
        res = api.schedule_launch(lB["id"], DM)
        validate_error(res, "ERR_FORKLIFT_SLOT_CONFLICT")

    def test_overlap_in_buffer_zone_after_service_end_rejected(self, api):
        """PRD §3.5: "its computed busy_until (window_start plus
        forklift_service_minutes plus forklift_buffer_minutes - the exclusive end of
        the forklift's busy interval)."
        PRD §3.5: "The new slot's busy interval - the half-open span from
        window_start up to but not including busy_until - must not overlap any
        non-RELEASED slot on the same forklift"

        Design: Difficulty/resource_temporal_overlap/forklift_slot_overlap_with_buffer
        """
        marina, owner, vB = self._two_racked_vessels_with_one_forklift()
        # 10:35 is past the 30-min service end (10:30) yet still inside the 15-min
        # buffer (busy_until 10:45), so it must still conflict -> the buffer extends
        # the occupied window beyond the bare service window.
        lB = create_launch(vB["id"], owner["id"],
                           requested_window_start="2026-04-02T10:35:00Z")
        res = api.schedule_launch(lB["id"], DM)
        validate_error(res, "ERR_FORKLIFT_SLOT_CONFLICT")

    def test_adjacency_at_busy_until_allowed(self, api):
        """PRD §3.5: "adjacency at busy_until (one slot's busy interval ending
        exactly when the next begins) is allowed."

        Design: Difficulty/boundary_precision_check/forklift_slot_adjacency_at_busy_until
        """
        marina, owner, vB = self._two_racked_vessels_with_one_forklift()
        # 10:45 == busy_until of the 10:00 slot -> adjacency, allowed.
        lB = create_launch(vB["id"], owner["id"],
                           requested_window_start="2026-04-02T10:45:00Z")
        scheduled = validate_success(api.schedule_launch(lB["id"], DM), 200)
        assert scheduled["status"] == "SCHEDULED", \
            "start at exactly busy_until is allowed (half-open)"

    def test_start_after_busy_until_allowed(self, api):
        """PRD §3.5: "The new slot's busy interval - the half-open span from
        window_start up to but not including busy_until - must not overlap any
        non-RELEASED slot on the same forklift; adjacency at busy_until (one slot's
        busy interval ending exactly when the next begins) is allowed."

        Design: Difficulty/boundary_precision_check/forklift_slot_adjacency_at_busy_until
        """
        marina, owner, vB = self._two_racked_vessels_with_one_forklift()
        # 10:46 is strictly after the 10:00 slot's busy_until 10:45 -> clearly allowed.
        lB = create_launch(vB["id"], owner["id"],
                           requested_window_start="2026-04-02T10:46:00Z")
        scheduled = validate_success(api.schedule_launch(lB["id"], DM), 200)
        assert scheduled["status"] == "SCHEDULED"


class TestRackOccupancyOverlap:
    """Rack occupancy is unbuffered half-open; a second activate on a still-OCCUPIED
    rack is rejected."""

    def test_second_activate_on_occupied_rack_rejected(self, api):
        """PRD §3.3: "it requires the target rack to be AVAILABLE (else
        ERR_RACK_NOT_AVAILABLE, HTTP 409)"
        PRD §3.3: "the half-open interval from this agreement's activated_at up to
        but not including its terminated_at must not overlap any existing occupancy
        interval on the same rack - adjacency, where one occupancy begins exactly
        when another ended, is allowed - and an overlap is rejected with
        ERR_RACK_OCCUPANCY_CONFLICT (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rack_occupancy_overlap_half_open_no_buffer
        """
        marina = create_marina()
        rack = create_rack(marina["id"], bay_label="M-1")
        owner = create_owner(marina["id"])
        vX = create_vessel(marina["id"], owner["id"], name="X",
                           loa_ft=25.00, beam_ft=9.00, dry_weight_lbs=5000)
        vY = create_vessel(marina["id"], owner["id"], name="Y",
                           loa_ft=25.00, beam_ft=9.00, dry_weight_lbs=5000)
        create_verified_policy(vX["id"])
        create_verified_policy(vY["id"])
        agrX = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(vX["id"], rack["id"]), DM))
        get_success_data(api.activate_storage_agreement(
            agrX["id"], rack_version(rack["id"]), DM))
        agrY = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(vY["id"], rack["id"]), DM))
        rv2 = rack_version(rack["id"])
        res = api.activate_storage_agreement(agrY["id"], rv2, DM)
        # Either guard (availability or occupancy overlap) faithfully rejects.
        validate_error_is_one_of(res, ["ERR_RACK_NOT_AVAILABLE",
                                       "ERR_RACK_OCCUPANCY_CONFLICT"])
        after = validate_success(api.get_storage_agreement(agrY["id"], DM), 200)
        assert after["status"] == "PENDING_COI", "second agreement stays PENDING_COI"

    def test_rack_reusable_after_prior_occupancy_ends(self, api):
        """PRD §3.3: "the half-open interval from this agreement's activated_at up to
        but not including its terminated_at must not overlap any existing occupancy
        interval on the same rack - adjacency, where one occupancy begins exactly
        when another ended, is allowed"
        PRD §3.3: "as compensation the rack's status returns to AVAILABLE, its
        current_agreement_id is cleared to null"

        Design: Difficulty/resource_temporal_overlap/rack_occupancy_overlap_half_open_no_buffer
        """
        marina = create_marina()
        rack = create_rack(marina["id"], bay_label="M-1")
        owner = create_owner(marina["id"])
        vX = create_vessel(marina["id"], owner["id"], name="X",
                           loa_ft=25.00, beam_ft=9.00, dry_weight_lbs=5000)
        vY = create_vessel(marina["id"], owner["id"], name="Y",
                           loa_ft=25.00, beam_ft=9.00, dry_weight_lbs=5000)
        create_verified_policy(vX["id"])
        create_verified_policy(vY["id"])
        agrX = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(vX["id"], rack["id"]), DM))
        get_success_data(api.activate_storage_agreement(
            agrX["id"], rack_version(rack["id"]), DM))
        # Terminate X so the rack frees; Y can then take the now-vacant occupancy.
        validate_success(api.terminate_storage_agreement(agrX["id"], DM), 200)
        agrY = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(vY["id"], rack["id"]), DM))
        activated = validate_success(api.activate_storage_agreement(
            agrY["id"], rack_version(rack["id"]), DM), 200)
        assert activated["status"] == "ACTIVE", \
            "a freed rack is reusable; non-overlapping occupancy is allowed"


# --------------------------------------------------------------------------- #
# Corner queue: validations.* instances
# --------------------------------------------------------------------------- #
class TestBusinessValidations:

    def test_duplicate_bay_label_rejected(self, api):
        """PRD §3.1: "A rack's bay_label must be unique among the racks of the same
        marina_id; a duplicate label is rejected with ERR_DUPLICATE_BAY_LABEL
        (HTTP 409)."

        Design: Corner/validations/duplicate_bay_label_rejected
        """
        marina = create_marina()
        create_rack(marina["id"], bay_label="M-1", size_class="MEDIUM")
        res = api.create_rack(create_rack_payload(
            marina["id"], bay_label="M-1", size_class="LARGE",
            max_loa_ft=40.00, max_beam_ft=14.00, max_weight_lbs=12000), DM)
        validate_error(res, "ERR_DUPLICATE_BAY_LABEL")

    def test_invoice_invalid_period_rejected(self, api):
        """PRD §3.7: "for a STORAGE_AGREEMENT FINAL invoice the period_end must be
        strictly after period_start; a missing period on a storage invoice, or a
        period_end not strictly after period_start, is rejected with
        ERR_INVALID_PERIOD (HTTP 422)."

        Design: Corner/validations/invoice_invalid_period_rejected
        """
        ctx = setup_active_agreement()
        res = api.create_invoice({
            "owner_id": ctx["owner"]["id"], "source_kind": "STORAGE_AGREEMENT",
            "source_id": ctx["agreement"]["id"], "variant": "FINAL",
            "period_start": "2026-05-10T00:00:00Z",
            "period_end": "2026-05-10T00:00:00Z"}, BC)
        validate_error(res, "ERR_INVALID_PERIOD")

    def test_pagination_limit_zero_rejected(self, api):
        """PRD §2.3: "A limit outside the inclusive range of 1 through 100, or an
        offset below 0, is rejected with ERR_INVALID_PAGINATION (HTTP 400)."

        Design: Corner/validations/pagination_limit_out_of_bounds_rejected
        """
        marina = create_marina()
        res = api.list_racks(DM, params={"marina_id": marina["id"], "limit": 0})
        validate_error(res, "ERR_INVALID_PAGINATION")

    def test_invoice_source_not_found_rejected(self, api):
        """PRD §2.5: "when an invoice names a source_id, that identifier must resolve
        to an existing row of the exact type named by source_kind, failing which the
        request is rejected with ERR_SOURCE_NOT_FOUND (HTTP 404)."

        Design: Corner/validations/invoice_source_not_found_rejected
        """
        marina, owner, _ = setup_owner_and_vessel()
        res = api.create_invoice({
            "owner_id": owner["id"], "source_kind": "STORAGE_AGREEMENT",
            "source_id": "00000000-0000-4000-8000-000000000999",
            "variant": "PROVISIONAL",
            "period_start": "2026-05-01T00:00:00Z",
            "period_end": "2026-06-01T00:00:00Z"}, BC)
        validate_error(res, "ERR_SOURCE_NOT_FOUND")

    def test_vessel_already_stored_rejected(self, api):
        """PRD §3.3: "The vessel may not already hold another agreement in ACTIVE or
        WINTERIZED status; if it does, activation is rejected with
        ERR_VESSEL_ALREADY_STORED (HTTP 409)."

        Design: Corner/validations/vessel_already_stored_rejected
        """
        ctx = setup_active_agreement(rack_overrides={"bay_label": "M-1"})
        rack2 = create_rack(ctx["marina"]["id"], bay_label="M-2")
        agr2 = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(ctx["vessel"]["id"], rack2["id"]), DM))
        res = api.activate_storage_agreement(agr2["id"], rack_version(rack2["id"]), DM)
        validate_error(res, "ERR_VESSEL_ALREADY_STORED")
