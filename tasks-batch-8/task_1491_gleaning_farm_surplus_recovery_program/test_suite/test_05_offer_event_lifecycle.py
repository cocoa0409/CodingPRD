"""Offer and glean-event lifecycle claims (PRD §2.5, §2.6, §3.1, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_assignment,
    coordinator_headers,
    create_event_payload,
    create_offer_payload,
    get_assignment,
    get_event,
    get_offer,
    get_vehicle,
    invite,
    invite_and_confirm,
    make_crew_leader_headers,
    new_crew_leader,
    new_event,
    new_farm,
    new_offer,
    new_vehicle,
    new_volunteer,
    publish_event,
    set_clock,
    setup_in_progress_event,
    setup_reconciled_event,
    sign_waiver,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestOfferExpiry:
    def test_offer_expires_when_clock_reaches_window_end(self, api):
        """PRD §2.5: "setting the clock causes the system to re-evaluate offer expiry:
        any offer still `OFFERED` whose `window_end` has been reached by the new
        instant transitions to `EXPIRED`, provided no glean event exists for that
        offer."

        Design: Corner/state_machines/offer_expiry_auto_transition
        """
        farm = new_farm(farm_name="EX", county_code="EX1")
        offer = new_offer(farm["id"], window_start="2026-08-05T00:00:00Z",
                          window_end="2026-08-10T00:00:00Z")
        assert offer["status"] == "OFFERED"
        set_clock("2026-08-10T00:00:00Z")
        offer = get_offer(offer["id"])
        assert offer["status"] == "EXPIRED", (
            "at exactly window_end the half-open window has closed"
        )


class TestEventCreationOfferSideEffect:
    def test_first_event_flips_offer_to_scheduled(self, api):
        """PRD §3.3: "The first event created against an `OFFERED` offer moves the
        offer to `SCHEDULED` and bumps the offer's `version`"

        Design: Corner/endpoints/event_create_computes_offer_status_side_effect
        """
        farm = new_farm(farm_name="EC", county_code="EC1")
        veh1 = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"])
        v0 = offer["version"]
        new_event(offer["id"], lead["id"], veh1["id"])
        offer = get_offer(offer["id"])
        assert offer["status"] == "SCHEDULED"
        assert offer["version"] == v0 + 1, "first event bumps the offer version by one"

    def test_second_event_leaves_offer_status_and_version(self, api):
        """PRD §3.3: "Further events may be created while the offer is `SCHEDULED`
        without changing the offer's status — one offer may host many events"

        Design: Corner/endpoints/event_create_computes_offer_status_side_effect
        """
        farm = new_farm(farm_name="EC2", county_code="EC2")
        veh1 = new_vehicle()
        veh2 = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"])
        new_event(offer["id"], lead["id"], veh1["id"],
                  scheduled_start="2026-08-10T08:00:00Z",
                  scheduled_end="2026-08-10T12:00:00Z")
        after_first = get_offer(offer["id"])
        new_event(offer["id"], lead["id"], veh2["id"],
                  scheduled_start="2026-08-12T08:00:00Z",
                  scheduled_end="2026-08-12T12:00:00Z")
        after_second = get_offer(offer["id"])
        assert after_second["status"] == "SCHEDULED"
        assert after_second["version"] == after_first["version"], (
            "the offer transition does not re-fire for a second event"
        )


class TestEventStateMachine:
    def test_reconciled_event_lockdown_rejects_cancel(self, api):
        """PRD §2.6: "4. **State compatibility** — the target resource must be in a state
        that permits the requested transition, failing with `ERR_INVALID_STATE` (HTTP
        409)."
        PRD §2.6: "20. **Terminal-state lockdown** — any action invoked on a
        resource that has already reached a terminal state is rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/event_terminal_lockdown_reconciled
        """
        ctx = setup_reconciled_event()
        resp = api.cancel_event(ctx["event"]["id"], coordinator_headers())
        assert resp.status_code == 409
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]
        )
        assert get_event(ctx["event"]["id"])["status"] == "RECONCILED"

    def test_finish_without_verified_lot_rejected(self, api):
        """PRD §3.3: "Finishing moves the event `IN_PROGRESS` → `HARVESTED` and
        requires at least one `VERIFIED` lot."

        Design: Corner/state_machines/finish_requires_verified_lot_precondition
        """
        ctx = setup_in_progress_event(lot_specs=[{"gross": 60.0, "cull": 0.0}])
        resp = api.finish_event(ctx["event"]["id"],
                                make_crew_leader_headers(ctx["lead"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_event(ctx["event"]["id"])["status"] == "IN_PROGRESS"

    def test_event_start_time_gate(self, api):
        """PRD §3.3: "The logical clock must have reached `scheduled_start` and must
        not yet have reached `scheduled_end`, otherwise the start is rejected with
        `ERR_EVENT_NOT_STARTED`."

        Design: Corner/state_machines/event_start_time_gate
        """
        farm = new_farm(farm_name="TG", county_code="TG1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"], crew_capacity=2)
        publish_event(event["id"])
        invite_and_confirm(event["id"], witness_id=lead["id"])

        set_clock("2026-08-10T07:59:59Z")
        resp = api.start_event(event["id"], make_crew_leader_headers(lead["id"]))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_STARTED, 422)
        assert get_event(event["id"])["status"] == "OPEN"

        set_clock("2026-08-10T08:00:00Z")
        started = validate_success(
            api.start_event(event["id"], make_crew_leader_headers(lead["id"])), 200
        )
        assert started["status"] == "IN_PROGRESS", (
            "the lower bound is inclusive: start at exactly scheduled_start succeeds"
        )


class TestFarmActiveGate:
    def test_inactive_farm_cannot_publish_offer(self, api):
        """PRD §3.1: "a farm whose flag has been cleared may not publish new surplus
        offers — such an attempt is rejected with `ERR_FARM_INACTIVE`."

        Design: Corner/validations/farm_inactive_offer_creation_blocked
        """
        farm = new_farm(farm_name="FI2", county_code="FI2", active_flag=False)
        resp = api.create_offer(create_offer_payload(farm["id"]), coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_FARM_INACTIVE, 422)


class TestEventPublishOfferDependency:
    def test_event_creation_against_cancelled_offer_rejected(self, api):
        """PRD §3.3: "creating an event against an offer in `GLEANED`, `CLOSED`,
        `CANCELLED`, or `EXPIRED` is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/event_publish_requires_offer_scheduled
        """
        farm = new_farm(farm_name="FX", county_code="XXX")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer2 = new_offer(farm["id"], crop_code="APPLES",
                           window_start="2026-08-06T00:00:00Z",
                           window_end="2026-08-21T00:00:00Z")
        api_client_cancel = api.cancel_offer(offer2["id"], coordinator_headers())
        validate_success(api_client_cancel, 200)
        resp = api.create_event(
            create_event_payload(offer2["id"], lead["id"], vehicle["id"],
                                 scheduled_start="2026-08-11T08:00:00Z",
                                 scheduled_end="2026-08-11T12:00:00Z"),
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_publish_on_scheduled_offer_assigns_vehicle(self, api):
        """PRD §3.3: "Publishing moves an event `DRAFT` → `OPEN`. The offer must be
        `SCHEDULED`, the assigned vehicle must currently be `AVAILABLE`, and the
        event's schedule must still sit inside the offer's harvest window; the vehicle
        schedule-conflict check runs again at publish. Publishing transitions the
        vehicle from `AVAILABLE` to `ASSIGNED` and bumps the event's `version`."

        Design: Difficulty/cross_entity_state_dependency/event_publish_requires_offer_scheduled
        """
        farm = new_farm(farm_name="FX2", county_code="XX2")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"])
        v0 = event["version"]
        published = publish_event(event["id"])
        assert published["status"] == "OPEN"
        assert published["version"] == v0 + 1
        assert get_vehicle(vehicle["id"])["status"] == "ASSIGNED"


class TestOfferCancelCascade:
    def _scheduled_offer_with_confirmed_crew(self):
        farm = new_farm(farm_name="FT", county_code="TTT")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        vt = new_volunteer(full_name="Vol T")
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"], crew_capacity=3)
        publish_event(event["id"])
        asg = invite(event["id"], vt["id"])
        sign_waiver(event["id"], vt["id"], lead["id"])
        confirm_assignment(asg["id"], vt["id"])
        return {"farm": farm, "vehicle": vehicle, "lead": lead, "vt": vt,
                "offer": offer, "event": event, "asg": asg}

    def test_offer_cancel_cascades_to_event_and_assignment(self, api):
        """PRD §3.1: "Cancelling a `SCHEDULED` offer is permitted only while every
        event of the offer is in `DRAFT`, `OPEN`, or `CANCELLED`; the same cascade
        then runs — draft and open events are cancelled, their pending and confirmed
        assignments are declined — and additionally every container held by those
        events returns to `AVAILABLE` and every assigned vehicle returns to
        `AVAILABLE`."

        Design: Difficulty/transitive_cascade/offer_cancel_depth3_cascade
        """
        ctx = self._scheduled_offer_with_confirmed_crew()
        resp = api.cancel_offer(ctx["offer"]["id"], coordinator_headers())
        offer = validate_success(resp, 200)
        assert offer["status"] == "CANCELLED"
        assert get_event(ctx["event"]["id"])["status"] == "CANCELLED"
        assert get_assignment(ctx["asg"]["id"])["status"] == "DECLINED"

    def test_offer_cancel_releases_vehicle_and_zeroes_crew_count(self, api):
        """PRD §3.1: "Cancelling a `SCHEDULED` offer is permitted only while every
        event of the offer is in `DRAFT`, `OPEN`, or `CANCELLED`; the same cascade
        then runs — draft and open events are cancelled, their pending and confirmed
        assignments are declined — and additionally every container held by those
        events returns to `AVAILABLE` and every assigned vehicle returns to
        `AVAILABLE`."
        PRD §2.10: "When a parent resource undergoes a transition that renders its
        children moot — cancelling an offer, cancelling an event — the system resolves
        every dependent child in the same breath: events are cancelled, pending and
        confirmed assignments are declined, containers and vehicles are released."

        Design: Difficulty/transitive_cascade/offer_cancel_depth3_cascade
        """
        ctx = self._scheduled_offer_with_confirmed_crew()
        assert get_event(ctx["event"]["id"])["crew_confirmed_count"] == 1
        api_request = api.cancel_offer(ctx["offer"]["id"], coordinator_headers())
        validate_success(api_request, 200)
        event = get_event(ctx["event"]["id"])
        assert event["crew_confirmed_count"] == 0, (
            "the declined assignment recomputes the event counter"
        )
        assert get_vehicle(ctx["vehicle"]["id"])["status"] == "AVAILABLE"
