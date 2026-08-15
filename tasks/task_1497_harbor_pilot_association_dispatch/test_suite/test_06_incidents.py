"""Incident investigation: branching fork and suspension cascade (PRD §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_pilot_headers,
    assert_incident,
    make_incident_payload, create_main_tariff, place_order, dispatch,
    register_boat, register_endorsed_pilot, launch, board,
    get_pilot_fresh, get_assignment_fresh, rotation_entry_of,
    setup_assigned_scenario, setup_two_pilots,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


def _report_incident(api, assignment_id, headers, incident_type="NEAR_MISS",
                     description="near miss at buoy 4"):
    return validate_success(api.create_incident(
        make_incident_payload(assignment_id, incident_type=incident_type,
                              description=description), headers), 201)


def _two_assignment_scenario():
    """P1 holds A1 (window 08-10) and A2 (window 08-11); A1 launched EN_ROUTE."""
    create_main_tariff()
    p1 = register_endorsed_pilot()
    register_boat("Boat A")
    register_boat("Boat B")
    o1 = place_order(vessel_name="MV One")
    a1 = dispatch(o1["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
    o2 = place_order(vessel_name="MV Two", order_type="DEPARTURE",
                     eta="2026-08-11T00:00:00Z")
    a2 = dispatch(o2["id"], "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z")
    a1 = launch(a1)
    return p1, a1, a2


class TestIncidentDetail:
    def test_incident_detail_computed_read(self, api, investigator_headers):
        """PRD §3.9: "The reported incident derives its `pilot_id` from the
        assignment's pilot and is born in `REPORTED` status."

        The pilot files on their own assignment; the detail read exposes the
        derived pilot_id and the initial state.

        Design: Corner/endpoints/incident_detail_computed_read
        """
        ctx = setup_assigned_scenario()
        a1 = ctx["assignment"]
        incident = _report_incident(api, a1["id"],
                                    make_pilot_headers(ctx["pilot"]["id"]))
        assert_incident(incident)
        detail = validate_success(api.get_incident(incident["id"],
                                                   investigator_headers), 200)
        assert detail["pilot_id"] == ctx["pilot"]["id"], "derived server-side"
        assert detail["status"] == "REPORTED"


class TestDismissalBranch:
    def _setup_under_review(self, api):
        p1, a1, a2 = _two_assignment_scenario()
        incident = _report_incident(api, a1["id"], DISPATCHER,
                                    incident_type="NEAR_MISS",
                                    description="near miss at buoy 4")
        validate_success(api.open_incident_review(incident["id"], INVESTIGATOR), 200)
        return p1, a1, a2, incident

    def test_dismissed_incident_leaves_pilot_and_board_untouched(self, api):
        """PRD §3.9: "Dismissal moves `UNDER_REVIEW → DISMISSED` and touches
        nothing — the pilot, the rotation entry, and the pilot's assignments
        are all left exactly as they stand."

        Design: Difficulty/non_linear_state_machine/incident_branching_fork_divergent_side_effects
        """
        p1, _a1, _a2, incident = self._setup_under_review(api)
        dismissed = validate_success(
            api.dismiss_incident(incident["id"], INVESTIGATOR), 200)
        assert dismissed["status"] == "DISMISSED"
        assert get_pilot_fresh(p1["id"])["status"] == "ACTIVE", "no suspension"
        assert rotation_entry_of(p1["id"])["status"] == "IN_ROTATION", "no board removal"

    def test_dismissed_incident_leaves_other_assignments_untouched(self, api):
        """PRD §3.9: "Dismissal moves `UNDER_REVIEW → DISMISSED` and touches
        nothing — the pilot, the rotation entry, and the pilot's assignments
        are all left exactly as they stand."

        The pilot's second ASSIGNED assignment is not recalled on the dismiss
        branch (contrast with the substantiation cascade).

        Design: Difficulty/non_linear_state_machine/incident_branching_fork_divergent_side_effects
        """
        _p1, a1, a2, incident = self._setup_under_review(api)
        validate_success(api.dismiss_incident(incident["id"], INVESTIGATOR), 200)
        assert get_assignment_fresh(a2["id"])["service_status"] == "ASSIGNED"
        assert get_assignment_fresh(a1["id"])["service_status"] == "EN_ROUTE"


class TestSubstantiationCascade:
    def _setup_under_review(self, api):
        p1, a1, a2 = _two_assignment_scenario()
        incident = _report_incident(api, a1["id"], DISPATCHER,
                                    incident_type="COLLISION",
                                    description="contact with fender")
        validate_success(api.open_incident_review(incident["id"], INVESTIGATOR), 200)
        return p1, a1, a2, incident

    def test_substantiate_suspends_pilot_and_removes_from_board(self, api):
        """PRD §3.9: "Substantiation instead fires a three-hop cascade: the
        pilot's `status` moves `ACTIVE → SUSPENDED`; that suspension pushes the
        pilot's rotation entry to `OFF_BOARD`".

        Design: Difficulty/transitive_cascade/incident_substantiation_suspension_cascade_depth3
        """
        p1, _a1, _a2, incident = self._setup_under_review(api)
        substantiated = validate_success(
            api.substantiate_incident(incident["id"], INVESTIGATOR), 200)
        assert substantiated["status"] == "SUBSTANTIATED"
        assert get_pilot_fresh(p1["id"])["status"] == "SUSPENDED", "hop 1"
        assert rotation_entry_of(p1["id"])["status"] == "OFF_BOARD", "hop 2"

    def test_substantiate_recalls_assigned_assignments_only(self, api):
        """PRD §3.9: "and the board removal recalls every one of that pilot's
        assignments still in `ASSIGNED` — each moves to `RECALLED` with its
        `recall_count` incremented and its boat interval released, per the
        recall semantics of §3.5."

        Hop 3 reaches A2 (ASSIGNED) but not A1 (already EN_ROUTE).

        Design: Difficulty/transitive_cascade/incident_substantiation_suspension_cascade_depth3
        """
        _p1, a1, a2, incident = self._setup_under_review(api)
        validate_success(api.substantiate_incident(incident["id"], INVESTIGATOR), 200)
        a2_after = get_assignment_fresh(a2["id"])
        assert a2_after["service_status"] == "RECALLED"
        assert a2_after["recall_count"] == 1
        assert get_assignment_fresh(a1["id"])["service_status"] == "EN_ROUTE", \
            "in-progress work is not recalled"


class TestIncidentStateGuards:
    def test_incident_dismiss_twice_returns_invalid_state(self, api):
        """PRD §3.9: "`DISMISSED` and `CLOSED` are terminal; acting on an
        incident from a state the transition does not allow — dismissing from
        `REPORTED`, closing from `UNDER_REVIEW` — is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/incident_dismiss_twice_returns_invalid_state
        """
        ctx = setup_assigned_scenario()
        incident = _report_incident(api, ctx["assignment"]["id"], DISPATCHER,
                                    incident_type="CONDUCT",
                                    description="late to launch")
        validate_success(api.open_incident_review(incident["id"], INVESTIGATOR), 200)
        validate_success(api.dismiss_incident(incident["id"], INVESTIGATOR), 200)

        res = api.dismiss_incident(incident["id"], INVESTIGATOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_rbac_dispatcher_cannot_review_incident_forbidden(self, api, dispatcher_headers):
        """PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint, or that fails an ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/pilotage/incidents/{id}/open-review` |
        `REPORTED → UNDER_REVIEW` | Investigator |".

        The dispatcher who reported the incident still cannot review it.

        Design: Corner/rbac/rbac_dispatcher_cannot_review_incident_forbidden
        """
        ctx = setup_assigned_scenario()
        incident = _report_incident(api, ctx["assignment"]["id"], DISPATCHER)

        res = api.open_incident_review(incident["id"], dispatcher_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        detail = validate_success(api.get_incident(incident["id"], DISPATCHER), 200)
        assert detail["status"] == "REPORTED"
