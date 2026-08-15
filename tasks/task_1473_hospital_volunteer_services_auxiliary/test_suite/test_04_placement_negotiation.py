"""Placement negotiation cycle, slot-fill evaluation order, request-state gating,
the counter-round budget, the two-placement limit, and slot conservation."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    set_clock, create_cleared_volunteer, create_department, create_role,
    create_open_request, create_offer, accept_placement,
    make_volunteer_headers, make_department_head_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
DH1 = TEST_USERS["dept_head_headers"]


def _infra(slots_needed=1, dept_name="Emergency", role_name="ED Greeter"):
    dept = create_department(name=dept_name, head_user_id="dh-1")
    role = create_role(name=role_name, category="PATIENT_FACING", minimum_age=18)
    request = create_open_request(dept["id"], role["id"], slots_needed=slots_needed)
    return dept, role, request


def _volunteer(name, email):
    return create_cleared_volunteer(full_name=name, email=email)["volunteer_id"]


class TestSlotFillEvaluationOrder:
    def _setup_two_offers(self):
        set_clock("2026-08-01T00:00:00Z")
        _, _, request = _infra(slots_needed=1)
        v1 = _volunteer("V One", "v1@x.org")
        v2 = _volunteer("V Two", "v2@x.org")
        p1 = create_offer(request["id"], v1)
        p2 = create_offer(request["id"], v2)
        return request, v1, v2, p1, p2

    def test_last_slot_accept_uses_pre_increment_status(self, api):
        """PRD §3.3: "the request must be `OPEN` (`ERR_REQUEST_NOT_OPEN`) **evaluated
        against the pre-increment `slots_filled`**, so a request one acceptance away
        from full is still open for this acceptance; only then does `slots_filled`
        increment by one; and only then, if `slots_filled` has reached `slots_needed`,
        does the request auto-transition `OPEN` → `FILLED`, stamping `filled_at` from
        the clock."

        Design: Difficulty/combinatorial_formula/slot_fill_evaluation_order
        """
        request, v1, v2, p1, p2 = self._setup_two_offers()

        accepted = validate_success(api.accept_placement(p1["id"], make_volunteer_headers(v1)))
        assert accepted["status"] == "ACCEPTED", (
            "the final slot's acceptance must pass the pre-increment OPEN check")

        request = get_success_data(api.get_department_request(request["id"], COORDINATOR))
        assert request["status"] == "FILLED"
        assert request["slots_filled"] == 1

        resp = api.accept_placement(p2["id"], make_volunteer_headers(v2))
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_OPEN)

    def test_filled_transition_stamps_filled_at_from_clock(self, api):
        """PRD §3.3: "only then, if `slots_filled` has reached `slots_needed`, does
        the request auto-transition `OPEN` → `FILLED`, stamping `filled_at` from the
        clock."

        Design: Difficulty/combinatorial_formula/slot_fill_evaluation_order
        """
        request, v1, v2, p1, p2 = self._setup_two_offers()
        validate_success(api.accept_placement(p1["id"], make_volunteer_headers(v1)))
        request = get_success_data(api.get_department_request(request["id"], COORDINATOR))
        assert request["status"] == "FILLED"
        assert str(request["filled_at"]).startswith("2026-08-01T00:00:00"), (
            f"filled_at must be stamped from the logical clock, got {request['filled_at']}")
        assert request["slots_filled"] == 1


class TestPlacementNegotiationCycle:
    def _setup_offer(self):
        set_clock("2026-08-01T00:00:00Z")
        _, _, request = _infra(dept_name="Pediatrics", role_name="Playroom Aide")
        vol_id = _volunteer("V Nego", "vn@x.org")
        placement = create_offer(request["id"], vol_id)
        return request, vol_id, placement

    def test_counter_reoffer_cycle_completes(self, api):
        """PRD §3.3: "The loop `OFFERED` → `COUNTERED` → `OFFERED` is the negotiation
        cycle, bounded by the two-counter budget."
        PRD §3.3: "The placement's own volunteer — and only that volunteer — moves
        `OFFERED` → `COUNTERED`, recording a `counter_note` and incrementing
        `counter_rounds`."

        Design: Difficulty/non_linear_state_machine/placement_counter_reoffer_cycle
        """
        request, vol_id, placement = self._setup_offer()
        pid = placement["id"]
        vol = make_volunteer_headers(vol_id)

        step = validate_success(api.counter_placement(pid, {"counter_note": "prefer weekends"}, vol))
        assert step["status"] == "COUNTERED"
        step = validate_success(api.reoffer_placement(pid, {"offer_note": "weekend schedule attached"}, DH1))
        assert step["status"] == "OFFERED", "reoffer closes the cycle back to OFFERED"
        step = validate_success(api.counter_placement(pid, {"counter_note": "mornings only please"}, vol))
        assert step["status"] == "COUNTERED"
        assert step["counter_rounds"] == 2
        step = validate_success(api.reoffer_placement(pid, {"offer_note": "agreed: Saturday mornings"}, DH1))
        assert step["status"] == "OFFERED"

        accepted = validate_success(api.accept_placement(pid, vol))
        assert accepted["status"] == "ACCEPTED"
        request = get_success_data(api.get_department_request(request["id"], COORDINATOR))
        assert request["slots_filled"] == 1
        assert request["status"] == "FILLED"

    def test_counter_and_offer_notes_recorded(self, api):
        """PRD §3.3: "moves `OFFERED` → `COUNTERED`, recording a `counter_note` and
        incrementing `counter_rounds`."
        PRD §3.3: "a reoffer moves `COUNTERED` back to `OFFERED`, records a fresh
        `offer_note`, and requires the request still `OPEN` (`ERR_REQUEST_NOT_OPEN`)"

        Design: Difficulty/non_linear_state_machine/placement_counter_reoffer_cycle
        """
        request, vol_id, placement = self._setup_offer()
        pid = placement["id"]
        vol = make_volunteer_headers(vol_id)

        validate_success(api.counter_placement(pid, {"counter_note": "c1"}, vol))
        validate_success(api.reoffer_placement(pid, {"offer_note": "r1"}, DH1))
        final = validate_success(api.counter_placement(pid, {"counter_note": "c2"}, vol))
        assert final["counter_rounds"] == 2
        assert final["counter_note"] == "c2", "latest counter note is recorded"
        final = validate_success(api.reoffer_placement(pid, {"offer_note": "r2"}, DH1))
        assert final["offer_note"] == "r2", "fresh offer note is recorded on reoffer"
        assert final["status"] == "OFFERED"

    def test_third_counter_rejected(self, api):
        """PRD §3.3: "Negotiation is bounded: once `counter_rounds` reaches 2, a
        further counter attempt is rejected with `ERR_COUNTER_ROUND_EXHAUSTED`."

        Design: Corner/state_machines/placement_third_counter_rejected
        """
        request, vol_id, placement = self._setup_offer()
        pid = placement["id"]
        vol = make_volunteer_headers(vol_id)
        validate_success(api.counter_placement(pid, {"counter_note": "c1"}, vol))
        validate_success(api.reoffer_placement(pid, {"offer_note": "r1"}, DH1))
        validate_success(api.counter_placement(pid, {"counter_note": "c2"}, vol))
        validate_success(api.reoffer_placement(pid, {"offer_note": "r2"}, DH1))

        resp = api.counter_placement(pid, {"counter_note": "c3"}, vol)
        validate_error(resp, ApiErrorId.ERR_COUNTER_ROUND_EXHAUSTED)
        row = get_success_data(api.get_placement(pid, COORDINATOR))
        assert row["counter_rounds"] == 2
        assert row["status"] == "OFFERED"


class TestPlacementAcceptGatedByRequestState:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        _, _, request = _infra(slots_needed=1)
        v1 = _volunteer("V One", "v1@x.org")
        v2 = _volunteer("V Two", "v2@x.org")
        p1 = create_offer(request["id"], v1)
        p2 = create_offer(request["id"], v2)
        accept_placement(p1["id"], v1)
        return request, v1, v2, p1, p2

    def test_accept_blocked_until_request_reopens(self, api):
        """PRD §3.3: "Rescinding an `ACCEPTED` placement is a compensating action:
        `slots_filled` decrements by one first, and if the request was `FILLED` it
        auto-reverts to `OPEN` with `filled_at` cleared."
        PRD §3.3: "the request must be `OPEN` (`ERR_REQUEST_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/placement_accept_blocked_until_request_reopens
        """
        request, v1, v2, p1, p2 = self._setup()

        resp = api.accept_placement(p2["id"], make_volunteer_headers(v2))
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_OPEN)

        validate_success(api.rescind_placement(
            p1["id"], {"reason": "volunteer unavailable"}, COORDINATOR))
        request = get_success_data(api.get_department_request(request["id"], COORDINATOR))
        assert request["status"] == "OPEN", "rescission of the only ACCEPTED placement reopens the request"

        accepted = validate_success(api.accept_placement(p2["id"], make_volunteer_headers(v2)))
        assert accepted["status"] == "ACCEPTED", (
            "the SAME accept on the SAME OFFERED placement now succeeds")
        request = get_success_data(api.get_department_request(request["id"], COORDINATOR))
        assert request["status"] == "FILLED"
        assert request["slots_filled"] == 1

    def test_reopen_clears_filled_at(self, api):
        """PRD §3.3: "if the request was `FILLED` it auto-reverts to `OPEN` with
        `filled_at` cleared."

        Design: Difficulty/cross_entity_state_dependency/placement_accept_blocked_until_request_reopens
        """
        request, v1, v2, p1, p2 = self._setup()
        mid = get_success_data(api.get_department_request(request["id"], COORDINATOR))
        assert mid["status"] == "FILLED" and mid["filled_at"] is not None

        validate_success(api.rescind_placement(p1["id"], {"reason": "schedule conflict"}, COORDINATOR))
        request = get_success_data(api.get_department_request(request["id"], COORDINATOR))
        assert request["status"] == "OPEN"
        assert request["slots_filled"] == 0
        assert request.get("filled_at") is None, "filled_at is cleared on FILLED -> OPEN revert"


class TestSlotConservation:
    def _setup_three_volunteers(self):
        set_clock("2026-08-01T00:00:00Z")
        _, _, request = _infra(slots_needed=2)
        v1 = _volunteer("V One", "v1@x.org")
        v2 = _volunteer("V Two", "v2@x.org")
        v3 = _volunteer("V Three", "v3@x.org")
        p1 = create_offer(request["id"], v1)
        p2 = create_offer(request["id"], v2)
        return request, v1, v2, v3, p1, p2

    def test_accept_rescind_reoffer_zero_drift(self, api):
        """PRD §3.3: "The request's `slots_filled` starts at zero and is maintained
        incrementally under a standing invariant: at all times, `slots_filled` equals
        the count of this request's placements in `ACCEPTED`."

        Design: Difficulty/compensating_invariant/placement_accept_rescind_slot_conservation
        """
        request, v1, v2, v3, p1, p2 = self._setup_three_volunteers()
        rid = request["id"]

        accept_placement(p1["id"], v1)
        accept_placement(p2["id"], v2)
        request = get_success_data(api.get_department_request(rid, COORDINATOR))
        assert request["slots_filled"] == 2 and request["status"] == "FILLED"

        validate_success(api.rescind_placement(p1["id"], {"reason": "schedule conflict"}, COORDINATOR))
        request = get_success_data(api.get_department_request(rid, COORDINATOR))
        assert request["slots_filled"] == 1 and request["status"] == "OPEN", (
            "compensating rescind: 2-1=1 ACCEPTED remains (P2)")

        p3 = create_offer(rid, v3)
        accept_placement(p3["id"], v3)
        request = get_success_data(api.get_department_request(rid, COORDINATOR))
        assert request["slots_filled"] == 2 and request["status"] == "FILLED", (
            "re-offer + accept restores 2 == count(ACCEPTED) with zero drift")

    def test_rescind_of_offered_placement_keeps_slots(self, api):
        """PRD §3.3: "Rescinding an `ACCEPTED` placement is a compensating action:
        `slots_filled` decrements by one first" — the compensation applies to the
        ACCEPTED rescind; rescinding a never-accepted offer changes no slot count,
        preserving "at all times, `slots_filled` equals the count of this request's
        placements in `ACCEPTED`."

        Design: Difficulty/compensating_invariant/placement_accept_rescind_slot_conservation
        """
        set_clock("2026-08-01T00:00:00Z")
        _, _, request = _infra(slots_needed=1)
        v1 = _volunteer("V One", "v1@x.org")
        p1 = create_offer(request["id"], v1)

        rescinded = validate_success(api.rescind_placement(
            p1["id"], {"reason": "offer withdrawn"}, COORDINATOR))
        assert rescinded["status"] == "RESCINDED"
        assert rescinded.get("rescinded_at") is not None
        request = get_success_data(api.get_department_request(request["id"], COORDINATOR))
        assert request["slots_filled"] == 0, "no ACCEPTED placement ever existed -> no decrement"
        assert request["status"] == "OPEN"


class TestPlacementLimit:
    def test_third_concurrent_acceptance_rejected(self, api):
        """PRD §3.3: "the volunteer must hold fewer than two `ACCEPTED` placements
        already — a third concurrent acceptance is `ERR_PLACEMENT_LIMIT_EXCEEDED`."

        Design: Corner/errors/placement_limit_exceeded_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        r1 = create_open_request(dept["id"], role["id"], slots_needed=1)
        r2 = create_open_request(dept["id"], role["id"], slots_needed=1)
        r3 = create_open_request(dept["id"], role["id"], slots_needed=1)
        vol_id = _volunteer("Limit Lou", "ll@x.org")

        p1 = create_offer(r1["id"], vol_id)
        accept_placement(p1["id"], vol_id)
        p2 = create_offer(r2["id"], vol_id)
        accept_placement(p2["id"], vol_id)
        p3 = create_offer(r3["id"], vol_id)

        resp = api.accept_placement(p3["id"], make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_LIMIT_EXCEEDED)

        row = get_success_data(api.get_placement(p3["id"], COORDINATOR))
        assert row["status"] == "OFFERED", "the rejected acceptance leaves the placement OFFERED"
        r3_now = get_success_data(api.get_department_request(r3["id"], COORDINATOR))
        assert r3_now["status"] == "OPEN" and r3_now["slots_filled"] == 0
