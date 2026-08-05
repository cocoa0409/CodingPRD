"""Custody transport: the three-input lead-time floor, the half-open slot calendar, the
escort level, the no-show cascade and the cancellation cutoff."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_transport_order,
    fixtures as fx,
    transport_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLeadTimeRequirement:
    def test_armed_escort_surcharge_beats_the_emergent_urgency_floor(
        self, api, custody_officer_headers
    ):
        """PRD §3.6: "The lead-time rule that `lead_minutes` is then tested against is built
        from three independent inputs — the referral's `urgency`, the escort level just
        derived, and the referral's accumulated `no_show_count` — and is deliberately not a
        simple sum. Start with an **escort-and-history component**: the escort surcharge,
        which is 0 minutes for `ESCORT_1`, 120 minutes for `ESCORT_2` and 480 minutes for
        `ESCORT_2_ARMED`, plus 720 minutes for each prior no-show on that referral. Cap that
        component at the routine floor of 2880 minutes by taking whichever of the two is
        smaller. Then take whichever is **larger** of that capped component and the urgency
        floor, which is 60 minutes for an `EMERGENT` referral and 2880 minutes for a
        `ROUTINE` one. The result is the required lead in minutes."

        Design: Difficulty/combinatorial_formula/transport_lead_time_nested_max_min_three_inputs
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1020",
            full_name="Dana Ellis",
            custody_level="MAXIMUM",
            booked_at="2026-05-01T00:00:00Z",
        )
        referral, _review = fx.setup_authorized_referral(
            inmate["id"], specialty="CARDIOLOGY", urgency="EMERGENT"
        )
        version = fx.referral_version(referral["id"])

        resp = api.create_transport_order(
            transport_order_payload(referral["id"], "2026-05-01T07:59:00Z", version),
            custody_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSPORT_LEAD_TIME_TOO_SHORT.value, 422)
        assert fx.transports_for(referral["id"]) == []

    def test_lead_time_is_accepted_at_exact_equality_with_the_requirement(
        self, api, custody_officer_headers
    ):
        """PRD §3.6: "The trip is accepted when `lead_minutes` is greater than or equal to
        that requirement — **exact equality is accepted**, since the requirement is a floor
        the appointment may sit precisely on. A shorter lead is rejected at rung 13 with
        `ERR_TRANSPORT_LEAD_TIME_TOO_SHORT` (422)."
        PRD §3.6: "The `lead_minutes` is the number of whole minutes from the current clock
        instant to `appointment_at`, floor-truncated."

        Design: Difficulty/combinatorial_formula/transport_lead_time_nested_max_min_three_inputs
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1021",
            full_name="Dana Ellis",
            custody_level="MAXIMUM",
            booked_at="2026-05-01T00:00:00Z",
        )
        referral, _review = fx.setup_authorized_referral(
            inmate["id"], specialty="CARDIOLOGY", urgency="EMERGENT"
        )
        version = fx.referral_version(referral["id"])

        resp = api.create_transport_order(
            transport_order_payload(referral["id"], "2026-05-01T08:00:00Z", version),
            custody_officer_headers,
        )
        trip = validate_success(resp, 201)
        assert_transport_order(trip)
        assert trip["required_escort_level"] == "ESCORT_2_ARMED"
        assert trip["lead_minutes"] == 480
        assert trip["status"] == "DRAFT"


class TestSlotOccupancy:
    def test_trip_starting_one_minute_before_the_slot_ends_collides(
        self, api, custody_officer_headers
    ):
        """PRD §3.6: "Every trip occupies a **half-open** 240-minute interval on the patient
        — beginning at its `appointment_at`, inclusive, and running to 240 minutes later,
        exclusive. Occupancy is counted across **all** referrals of the same inmate, not
        merely the one being booked, and only trips whose status is `DRAFT`,
        `ESCORT_ASSIGNED` or `DISPATCHED` occupy anything; a `COMPLETED`, `NO_SHOW` or
        `CANCELLED` trip releases its slot immediately. Two trips conflict when the new
        appointment falls strictly before the end of an occupied slot and that occupied
        appointment falls strictly before the end of the new slot."

        Design: Difficulty/resource_temporal_overlap/transport_slot_half_open_adjacency_is_legal
        """
        scenario = fx.setup_two_authorized_referrals_with_one_draft_trip()
        version = fx.referral_version(scenario["referral_two"]["id"])
        resp = api.create_transport_order(
            transport_order_payload(
                scenario["referral_two"]["id"], "2026-05-05T11:59:00Z", version
            ),
            custody_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, 409)
        assert fx.read_transport(
            scenario["referral_one"]["id"], scenario["trip"]["id"]
        )["status"] == "DRAFT"

    def test_trip_starting_exactly_when_the_slot_ends_is_legal_adjacency(
        self, api, custody_officer_headers
    ):
        """PRD §3.6: "Because the interval is half-open, a trip beginning exactly 240
        minutes after another begins does **not** conflict — adjacency is legal — while one
        beginning a single minute earlier does. A conflict is rejected at rung 14 with
        `ERR_SCHEDULE_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/transport_slot_half_open_adjacency_is_legal
        """
        scenario = fx.setup_two_authorized_referrals_with_one_draft_trip()
        version = fx.referral_version(scenario["referral_two"]["id"])
        resp = api.create_transport_order(
            transport_order_payload(
                scenario["referral_two"]["id"], "2026-05-05T12:00:00Z", version
            ),
            custody_officer_headers,
        )
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "DRAFT"
        assert_same_instant(
            adjacent["appointment_at"], "2026-05-05T12:00:00Z", "appointment_at"
        )
        assert fx.read_transport(
            scenario["referral_one"]["id"], scenario["trip"]["id"]
        )["status"] == "DRAFT"


class TestReferralVersionConcurrency:
    def test_stale_expected_referral_version_is_rejected_on_a_second_trip(
        self, api, custody_officer_headers
    ):
        """PRD §2.7: "Creating a transport — the create a `CustodyOfficer` issues against
        `POST /transport-orders` — requires the body field `expected_referral_version`,
        carrying the `version` integer of the parent specialty referral as the client last
        observed it. It too is mandatory, and a value that does not equal the referral's
        current `version` is rejected with `ERR_STALE_REFERRAL_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_referral_version_rejected_on_transport_order
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2390", full_name="Gil Jansen", booked_at="2026-05-01T00:00:00Z"
        )
        referral, _review = fx.setup_authorized_referral(
            inmate["id"], specialty="CARDIOLOGY", urgency="ROUTINE"
        )
        stale_version = fx.referral_version(referral["id"])
        first = fx.create_transport(
            referral["id"], "2026-05-05T08:00:00Z", expected_referral_version=stale_version
        )

        resp = api.create_transport_order(
            transport_order_payload(referral["id"], "2026-05-06T08:00:00Z", stale_version),
            custody_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_REFERRAL_VERSION.value, 412)

        rows, meta = validate_paginated(
            api.list_transport_orders(referral["id"], custody_officer_headers)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["status"] == "DRAFT"


class TestEscortAssignment:
    def test_escort_level_must_equal_the_required_level_exactly(self, api, custody_officer_headers):
        """PRD §3.6: "Assigning the escort detail supplies an `escort_level`, and it must
        equal the trip's `required_escort_level` **exactly** — not merely meet or exceed it.
        Assigning `ESCORT_2_ARMED` to a trip that requires `ESCORT_2` is as much a failure as
        assigning `ESCORT_1`, and both are rejected at rung 14 with
        `ERR_ESCORT_LEVEL_MISMATCH` (422)."

        Design: Corner/state_machines/transport_escort_level_mismatch_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2160", full_name="Hal Jarvis", booked_at="2026-05-01T00:00:00Z"
        )
        referral, _review = fx.setup_authorized_referral(
            inmate["id"], specialty="CARDIOLOGY", urgency="ROUTINE"
        )
        trip = fx.create_transport(referral["id"], "2026-05-05T08:00:00Z")

        resp = api.assign_escort(trip["id"], {"escort_level": "ESCORT_1"}, custody_officer_headers)
        validate_error(resp, ApiErrorId.ERR_ESCORT_LEVEL_MISMATCH.value, 422)

        unchanged = fx.read_transport(referral["id"], trip["id"])
        assert unchanged["required_escort_level"] == "ESCORT_2"
        assert unchanged["assigned_escort_level"] is None
        assert unchanged["status"] == "DRAFT"
        assert fx.read_referral(referral["id"])["status"] == "AUTHORIZED"


class TestNoShowCascade:
    def test_second_no_show_returns_the_referral_and_recomputes_its_count(self, api):
        """PRD §3.6: "A `NO_SHOW` outcome opens **Cascade D**. At level one the trip's status
        becomes `NO_SHOW`. At level two, because a no-show was recorded, the parent referral
        returns from `SCHEDULED` to `AUTHORIZED` and its `no_show_count` is recomputed as the
        number of trips under that referral whose status is `NO_SHOW`; the referral's
        `version` increments."

        Design: Difficulty/transitive_cascade/transport_no_show_depth3_referral_cap_cancel
        """
        scenario = fx.setup_two_no_show_trips_on_one_referral()
        referral_id = scenario["referral"]["id"]

        outcome = validate_success(
            api.record_transport_outcome(
                scenario["trip2"]["id"], {"outcome": "NO_SHOW"}, fx.CUSTODY
            ),
            200,
        )
        assert outcome["status"] == "NO_SHOW"
        assert fx.read_transport(referral_id, scenario["trip1"]["id"])["status"] == "NO_SHOW"
        assert fx.read_referral(referral_id)["no_show_count"] == 2

    def test_reaching_the_no_show_ceiling_cancels_the_referral(self, api):
        """PRD §3.6: "At level three, if that recomputed `no_show_count` has reached 2, the
        referral moves from `AUTHORIZED` to `CANCELLED`, and every trip still under it whose
        status is `DRAFT`, `ESCORT_ASSIGNED` or `DISPATCHED` is cancelled with `cancel_reason`
        `CLINICAL_CHANGE`."
        PRD §3.1: "the read-time `no_show_count` (the number of transport orders across all
        of that inmate's referrals whose status is `NO_SHOW`)"

        Design: Difficulty/transitive_cascade/transport_no_show_depth3_referral_cap_cancel
        """
        scenario = fx.setup_two_no_show_trips_on_one_referral()
        referral_id = scenario["referral"]["id"]
        validate_success(
            api.record_transport_outcome(
                scenario["trip2"]["id"], {"outcome": "NO_SHOW"}, fx.CUSTODY
            ),
            200,
        )
        assert fx.read_referral(referral_id)["status"] == "CANCELLED"
        assert fx.read_inmate(scenario["inmate"]["id"])["no_show_count"] == 2


class TestCancellationCutoff:
    def test_terminal_trip_state_pre_empts_the_cancellation_cutoff(self, api, custody_officer_headers):
        """PRD §2.5: "All checks in this system belong to one global ladder of fourteen
        rungs, evaluated strictly in ascending order. The first rung that fails determines the
        response, and no rung below it is evaluated at all."
        PRD §2.5: "**Target state.** The addressed row's own `status` or `outcome` is one from
        which the requested transition is declared. Failure yields `ERR_INVALID_STATE` (409)."
        PRD §3.6: "Cancelling a trip is legal from `DRAFT`, `ESCORT_ASSIGNED` or `DISPATCHED`
        and supplies a `cancel_reason` of `FACILITY_LOCKDOWN`, `VENDOR_CANCELLED`,
        `ESCORT_UNAVAILABLE` or `CLINICAL_CHANGE`."

        Design: Difficulty/priority_pair_validation_conflict/terminal_transport_state_preempts_cancel_cutoff
        """
        scenario = fx.setup_cancelled_and_draft_trips_past_their_cutoff()
        resp = api.cancel_transport(
            scenario["trip_cancelled"]["id"],
            {"cancel_reason": "FACILITY_LOCKDOWN"},
            custody_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

        unchanged = fx.read_transport(
            scenario["referral"]["id"], scenario["trip_cancelled"]["id"]
        )
        assert unchanged["status"] == "CANCELLED"
        assert unchanged["cancel_reason"] == "VENDOR_CANCELLED"

    def test_still_draft_trip_past_its_cutoff_surfaces_the_temporal_error(
        self, api, custody_officer_headers
    ):
        """PRD §3.6: "It is permitted only while the current clock instant is at or before
        `appointment_at` minus 120 minutes; at exactly that cutoff instant the trip is still
        cancellable, and strictly past it the cancellation is rejected at rung 13 with
        `ERR_CANCEL_CUTOFF_PASSED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/terminal_transport_state_preempts_cancel_cutoff
        """
        scenario = fx.setup_cancelled_and_draft_trips_past_their_cutoff()
        resp = api.cancel_transport(
            scenario["trip_draft"]["id"],
            {"cancel_reason": "FACILITY_LOCKDOWN"},
            custody_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CANCEL_CUTOFF_PASSED.value, 422)
        assert fx.read_transport(
            scenario["referral"]["id"], scenario["trip_draft"]["id"]
        )["status"] == "DRAFT"
