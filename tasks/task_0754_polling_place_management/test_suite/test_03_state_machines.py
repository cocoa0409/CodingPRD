"""Invalid state-machine transitions (queue B: state_machines)."""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_election, create_place,
    create_supply_kit_payload, create_incident_payload,
)

ADMIN = TEST_USERS["election_admin_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


def test_close_voting_from_planning_is_invalid_state(api):
    """PRD §3.1: "Closing voting advances it `VOTING_OPEN → VOTING_CLOSED` and is permitted
    only while the election is in `VOTING_OPEN`".
    PRD §3.1: "Attempting either transition from the wrong status is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/election_close_voting_from_planning_returns_invalid_state
    """
    el = create_election(api)  # left in PLANNING
    resp = api.close_voting(el["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reopen_voting_after_close_is_invalid_state(api):
    """PRD §3.1: "Opening voting advances the election `PLANNING → VOTING_OPEN`; it is
    permitted only while the election is in `PLANNING`."
    PRD §3.1: "`VOTING_CLOSED` is terminal."

    Design: Corner/state_machines/election_reopen_after_close_returns_invalid_state_terminal
    """
    el = create_election(api, open_voting=True)
    get_success_data(api.close_voting(el["id"], ADMIN))  # -> VOTING_CLOSED (terminal)
    resp = api.open_voting(el["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_acknowledge_already_acknowledged_incident_is_invalid_state(api):
    """PRD §3.8: "Acknowledging takes it `OPEN → ACKNOWLEDGED`."
    PRD §3.8: "a transition attempted from a status where it is undefined is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/incident_acknowledge_twice_returns_invalid_state_idempotency
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"])
    inc = get_success_data(
        api.create_incident(
            create_incident_payload(pp["id"], "STAFFING", "short a worker"), SUPPORT
        )
    )
    get_success_data(api.acknowledge_incident(inc["id"], SUPPORT))
    resp = api.acknowledge_incident(inc["id"], SUPPORT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_receive_custody_event_from_prepared_is_invalid_transition(api):
    """PRD §3.6: "RECEIVE (`IN_TRANSIT → AT_PLACE`): the request must include a
    `polling_place_id` naming an existing place".
    PRD §3.6: "Any `event_type` that is not defined from the kit's current `custody_state`,
    and any `RECEIVE` missing its `polling_place_id`, is rejected with
    `ERR_INVALID_CUSTODY_TRANSITION` (422)."

    Design: Corner/state_machines/custody_receive_from_prepared_returns_invalid_custody_transition
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"])
    kit = get_success_data(api.create_supply_kit(create_supply_kit_payload(el["id"]), CUSTODY))
    # Kit is PREPARED; RECEIVE is only defined from IN_TRANSIT. Supply a valid place so the
    # only defect is the from-state.
    resp = api.create_custody_event(
        kit["id"], {"event_type": "RECEIVE", "polling_place_id": pp["id"]}, CUSTODY
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CUSTODY_TRANSITION)
