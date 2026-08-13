"""Waivers, crew confirmation, capacity boundary, and double-booking claims
(PRD §2.4, §2.10, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_waiver,
    confirm_assignment,
    decline_assignment,
    get_assignment,
    get_event,
    invite,
    make_volunteer_headers,
    new_crew_leader,
    new_event,
    new_farm,
    new_offer,
    new_vehicle,
    new_volunteer,
    publish_event,
    sign_waiver,
    validate_error,
    validate_success,
)


def _open_event_with_volunteers(capacity, volunteer_names):
    """Offer + event published OPEN with one invited PENDING volunteer per name."""
    farm = new_farm()
    vehicle = new_vehicle()
    lead = new_crew_leader()
    offer = new_offer(farm["id"])
    event = new_event(offer["id"], lead["id"], vehicle["id"], crew_capacity=capacity)
    publish_event(event["id"])
    volunteers = {}
    for name in volunteer_names:
        vol = new_volunteer(full_name=name)
        asg = invite(event["id"], vol["id"])
        sign_waiver(event["id"], vol["id"], lead["id"])
        volunteers[name] = (vol, asg)
    return {"farm": farm, "vehicle": vehicle, "lead": lead, "offer": offer,
            "event": event, "volunteers": volunteers}


class TestWaiverClaims:
    def test_waiver_is_immutable_record_without_version(self, api):
        """PRD §2.4: "Three record types are immutable once written and therefore carry
        only `id` and `created_at` — both `updated_at` and `version` are absent from
        them: the **Waiver**, the **TempLog**, and the **DonationReceipt**."

        Design: Corner/entities/waiver_immutability_no_version_field
        """
        farm = new_farm(farm_name="WF", county_code="WVV")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        vol = new_volunteer(full_name="WV")
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"], crew_capacity=2)

        resp = api.create_waiver(
            {"volunteer_id": vol["id"], "glean_event_id": event["id"],
             "signature_payload": "sigW", "witness_volunteer_id": lead["id"]},
            make_volunteer_headers(vol["id"]),
        )
        waiver = validate_success(resp, 201)
        assert_waiver(waiver)
        assert waiver["volunteer_id"] == vol["id"]
        assert waiver["glean_event_id"] == event["id"]
        assert waiver["witness_volunteer_id"] == lead["id"]
        assert waiver["signature_payload"] == "sigW"

    def test_waiver_self_witness_rejected(self, api):
        """PRD §3.2: "Segregation of duties applies at signing: the witness must differ
        from the signer, and a waiver naming the same volunteer in both roles is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/waiver_self_witness_rejected
        """
        farm = new_farm(farm_name="WS", county_code="WS1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"], crew_capacity=1)

        resp = api.create_waiver(
            {"volunteer_id": lead["id"], "glean_event_id": event["id"],
             "signature_payload": "sigSelf", "witness_volunteer_id": lead["id"]},
            make_volunteer_headers(lead["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)

    def test_confirm_without_waiver_rejected(self, api):
        """PRD §3.2: "Next, waiver presence: a waiver must exist pairing this volunteer
        with this event and witnessed by a different volunteer, failing with
        `ERR_WAIVER_MISSING`."

        Design: Corner/errors/waiver_missing_confirm_error
        """
        farm = new_farm(farm_name="WM", county_code="WM1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        vol = new_volunteer(full_name="WMV")
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"], crew_capacity=2)
        publish_event(event["id"])
        asg = invite(event["id"], vol["id"])

        resp = api.confirm_assignment(asg["id"], make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_WAIVER_MISSING, 422)
        assert get_assignment(asg["id"])["status"] == "PENDING"

    def test_confirm_response_and_parent_read_are_immediately_consistent(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §2.10: "the parent's derived totals and lifecycle position are recomputed
        immediately, without requiring an explicit client request on the parent."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
        """
        ctx = _open_event_with_volunteers(2, ["ICV"])
        vol, asg = ctx["volunteers"]["ICV"]
        resp = api.confirm_assignment(asg["id"], make_volunteer_headers(vol["id"]))
        confirmed = validate_success(resp, 200)
        assert confirmed["status"] == "CONFIRMED", (
            "the mutating response itself must carry the new status"
        )
        event = get_event(ctx["event"]["id"])
        assert event["crew_confirmed_count"] == 1, (
            "the immediately-following read must reflect the confirmation"
        )


class TestCrewFillCycle:
    """GleanEvent OPEN -> FULL -> OPEN -> FULL derived from crew assignment rows."""

    def test_confirm_to_capacity_flips_full_then_decline_reopens(self, api):
        """PRD §3.2: "when the count reaches `crew_capacity`, an `OPEN` event flips to
        `FULL`, while a count one short of capacity leaves it `OPEN`."
        PRD §3.2: "A `CONFIRMED` assignment may be declined only while its event is
        still `OPEN` or `FULL`; doing so drops the event's `crew_confirmed_count` by
        one, and if the event was `FULL` it reopens to `OPEN`."

        Design: Difficulty/non_linear_state_machine/glean_event_open_full_open_cycle
        """
        ctx = _open_event_with_volunteers(2, ["Vol A", "Vol B", "Vol C"])
        va, asg_a = ctx["volunteers"]["Vol A"]
        vb, asg_b = ctx["volunteers"]["Vol B"]

        confirm_assignment(asg_a["id"], va["id"])
        assert get_event(ctx["event"]["id"])["status"] == "OPEN", (
            "one short of capacity leaves the event OPEN"
        )
        confirm_assignment(asg_b["id"], vb["id"])
        event = get_event(ctx["event"]["id"])
        assert event["status"] == "FULL" and event["crew_confirmed_count"] == 2

        decline_assignment(asg_b["id"], vb["id"])
        event = get_event(ctx["event"]["id"])
        assert event["status"] == "OPEN" and event["crew_confirmed_count"] == 1, (
            "declining from FULL reopens the event"
        )

    def test_reconfirm_after_reopen_flips_full_again(self, api):
        """PRD §3.2: "On success the assignment becomes `CONFIRMED`, the server stamps
        `confirmed_at` from the logical clock, and the event's `crew_confirmed_count`
        rises by one — when the count reaches `crew_capacity`, an `OPEN` event flips
        to `FULL`"

        Design: Difficulty/non_linear_state_machine/glean_event_open_full_open_cycle
        """
        ctx = _open_event_with_volunteers(2, ["Vol A", "Vol B", "Vol C"])
        va, asg_a = ctx["volunteers"]["Vol A"]
        vb, asg_b = ctx["volunteers"]["Vol B"]
        vc, asg_c = ctx["volunteers"]["Vol C"]

        confirm_assignment(asg_a["id"], va["id"])
        confirm_assignment(asg_b["id"], vb["id"])
        decline_assignment(asg_b["id"], vb["id"])
        confirm_assignment(asg_c["id"], vc["id"])

        event = get_event(ctx["event"]["id"])
        assert event["status"] == "FULL" and event["crew_confirmed_count"] == 2, (
            "cycle OPEN->FULL->OPEN->FULL must be traversable"
        )
        assert get_assignment(asg_b["id"])["status"] == "DECLINED"


class TestCrewCapacityBoundary:
    def test_confirm_at_exact_capacity_succeeds_and_flips_full(self, api):
        """PRD §3.2: "when the count reaches `crew_capacity`, an `OPEN` event flips to
        `FULL`, while a count one short of capacity leaves it `OPEN`."

        Design: Difficulty/boundary_precision_check/crew_capacity_count_boundary
        """
        ctx = _open_event_with_volunteers(2, ["Vol KA", "Vol KB", "Vol KC"])
        vka, asg_ka = ctx["volunteers"]["Vol KA"]
        vkb, asg_kb = ctx["volunteers"]["Vol KB"]

        confirm_assignment(asg_ka["id"], vka["id"])
        assert get_event(ctx["event"]["id"])["crew_confirmed_count"] == 1
        resp = api.confirm_assignment(asg_kb["id"], make_volunteer_headers(vkb["id"]))
        validate_success(resp, 200)
        event = get_event(ctx["event"]["id"])
        assert event["status"] == "FULL" and event["crew_confirmed_count"] == 2, (
            "count == capacity is allowed and flips the event to FULL"
        )

    def test_confirm_beyond_capacity_rejected_crew_full(self, api):
        """PRD §3.2: "Next, capacity: confirming must not push the event's
        `crew_confirmed_count` above its `crew_capacity`, failing with `ERR_CREW_FULL`."

        Design: Difficulty/boundary_precision_check/crew_capacity_count_boundary
        """
        ctx = _open_event_with_volunteers(2, ["Vol KA", "Vol KB", "Vol KC"])
        vka, asg_ka = ctx["volunteers"]["Vol KA"]
        vkb, asg_kb = ctx["volunteers"]["Vol KB"]
        vkc, asg_kc = ctx["volunteers"]["Vol KC"]
        confirm_assignment(asg_ka["id"], vka["id"])
        confirm_assignment(asg_kb["id"], vkb["id"])

        resp = api.confirm_assignment(asg_kc["id"], make_volunteer_headers(vkc["id"]))
        validate_error(resp, ApiErrorId.ERR_CREW_FULL, 422)
        assert get_assignment(asg_kc["id"])["status"] == "PENDING"


class TestVolunteerDoubleBooking:
    def _three_event_setup(self):
        """VU invited+waivered on E_A [08:00,12:00), E_B [12:00,16:00) adjacent,
        E_C [11:00,15:00) overlapping; three separate offers (distinct crops) and
        three separate vehicles."""
        farm = new_farm()
        lead = new_crew_leader()
        vu = new_volunteer(full_name="Vol U")
        ctx = {"farm": farm, "lead": lead, "vu": vu}
        specs = [
            ("ROOT_VEG", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"),
            ("APPLES", "2026-08-10T12:00:00Z", "2026-08-10T16:00:00Z"),
            ("TOMATOES", "2026-08-10T11:00:00Z", "2026-08-10T15:00:00Z"),
        ]
        ctx["events"] = []
        for crop, start, end in specs:
            vehicle = new_vehicle()
            offer = new_offer(farm["id"], crop_code=crop)
            event = new_event(offer["id"], lead["id"], vehicle["id"],
                              scheduled_start=start, scheduled_end=end, crew_capacity=3)
            publish_event(event["id"])
            asg = invite(event["id"], vu["id"])
            sign_waiver(event["id"], vu["id"], lead["id"])
            ctx["events"].append({"offer": offer, "event": event, "asg": asg,
                                  "vehicle": vehicle})
        return ctx

    def test_adjacent_confirm_permitted_half_open(self, api):
        """PRD §3.2: "the volunteer may not hold `CONFIRMED` assignments on two events
        whose half-open schedule intervals — each running from its `scheduled_start`
        up to but not including its `scheduled_end` — overlap, with adjacency again
        permitted"

        Design: Difficulty/resource_temporal_overlap/volunteer_double_booking_aggregate_across_events
        """
        ctx = self._three_event_setup()
        vu = ctx["vu"]
        asg_a = ctx["events"][0]["asg"]
        asg_b = ctx["events"][1]["asg"]
        confirm_assignment(asg_a["id"], vu["id"])
        resp = api.confirm_assignment(asg_b["id"], make_volunteer_headers(vu["id"]))
        confirmed = validate_success(resp, 200)
        assert confirmed["status"] == "CONFIRMED", (
            "E_B starts exactly at E_A's end — adjacency permitted"
        )

    def test_overlapping_confirm_rejected_double_booked(self, api):
        """PRD §3.2: "a conflict is rejected with `ERR_VOLUNTEER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/volunteer_double_booking_aggregate_across_events
        """
        ctx = self._three_event_setup()
        vu = ctx["vu"]
        asg_a = ctx["events"][0]["asg"]
        asg_b = ctx["events"][1]["asg"]
        asg_c = ctx["events"][2]["asg"]
        confirm_assignment(asg_a["id"], vu["id"])
        confirm_assignment(asg_b["id"], vu["id"])

        resp = api.confirm_assignment(asg_c["id"], make_volunteer_headers(vu["id"]))
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED, 422)
        assert get_assignment(asg_c["id"])["status"] == "PENDING"


class TestConfirmGateOrdering:
    def _pair_setup(self):
        """VZ CONFIRMED (with waiver) on E_A [08:00,12:00); VZ invited on E_B
        [10:00,14:00) of a different offer, with NO waiver for E_B."""
        farm = new_farm()
        veh1 = new_vehicle()
        veh2 = new_vehicle()
        lead = new_crew_leader()
        vz = new_volunteer(full_name="Vol Z")
        offer_a = new_offer(farm["id"], crop_code="ROOT_VEG")
        offer_b = new_offer(farm["id"], crop_code="APPLES")
        ev_a = new_event(offer_a["id"], lead["id"], veh1["id"],
                         scheduled_start="2026-08-10T08:00:00Z",
                         scheduled_end="2026-08-10T12:00:00Z", crew_capacity=3)
        publish_event(ev_a["id"])
        ev_b = new_event(offer_b["id"], lead["id"], veh2["id"],
                         scheduled_start="2026-08-10T10:00:00Z",
                         scheduled_end="2026-08-10T14:00:00Z", crew_capacity=3)
        publish_event(ev_b["id"])
        asg_a = invite(ev_a["id"], vz["id"])
        asg_b = invite(ev_b["id"], vz["id"])
        sign_waiver(ev_a["id"], vz["id"], lead["id"])
        confirm_assignment(asg_a["id"], vz["id"])
        return {"lead": lead, "vz": vz, "ev_a": ev_a, "ev_b": ev_b,
                "asg_a": asg_a, "asg_b": asg_b}

    def test_double_booking_outranks_waiver_missing(self, api):
        """PRD §3.2: "Confirming an assignment runs a fixed gate order. The event
        must be in `OPEN` or `FULL`, since crews cannot join an event already running
        or finished (`ERR_INVALID_STATE`). Next, double-booking: the volunteer may not
        hold `CONFIRMED` assignments on two events whose half-open schedule intervals —
        each running from its `scheduled_start` up to but not including its
        `scheduled_end` — overlap, with adjacency again permitted; a conflict is
        rejected with `ERR_VOLUNTEER_DOUBLE_BOOKED`. Next, waiver presence: a waiver
        must exist pairing this volunteer with this event and witnessed by a different
        volunteer, failing with `ERR_WAIVER_MISSING`."
        PRD §2.6: "Every request is evaluated against a fixed, ordered sequence of
        gates, and the first gate that fails determines the error returned — later
        gates are never consulted on a failed request."

        Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_vs_constraint_pair
        """
        ctx = self._pair_setup()
        resp = api.confirm_assignment(ctx["asg_b"]["id"],
                                      make_volunteer_headers(ctx["vz"]["id"]))
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED, 422)
        assert get_assignment(ctx["asg_b"]["id"])["status"] == "PENDING"

    def test_waiver_missing_fires_when_no_overlap(self, api):
        """PRD §3.2: "Next, waiver presence: a waiver must exist pairing this volunteer
        with this event and witnessed by a different volunteer, failing with
        `ERR_WAIVER_MISSING`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_vs_constraint_pair
        """
        ctx = self._pair_setup()
        # Second volunteer with an assignment on E_B, no waiver, and no other
        # confirmed event: only the waiver gate can fail.
        vw = new_volunteer(full_name="Vol W")
        asg_w = invite(ctx["ev_b"]["id"], vw["id"])
        resp = api.confirm_assignment(asg_w["id"], make_volunteer_headers(vw["id"]))
        validate_error(resp, ApiErrorId.ERR_WAIVER_MISSING, 422)
        assert get_assignment(asg_w["id"])["status"] == "PENDING"
