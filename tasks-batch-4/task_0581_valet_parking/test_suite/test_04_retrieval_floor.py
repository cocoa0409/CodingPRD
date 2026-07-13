"""The retrieval floor: cross-entity preconditions, the READY↔STAGING cycle, and bad-state
transitions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_retrieval_request_payload, make_attendant_headers,
)
from test_helpers.fixtures import (
    setup_checked_in_ticket, setup_settled_ticket, setup_requested_retrieval,
    setup_retrieval_ready, create_attendant, create_shift, create_active_shift,
)

SUP = TEST_USERS["supervisor_headers"]


def test_retrieval_on_closed_ticket_rejected(api):
    """PRD §3.6: "A retrieval may only be opened for a ticket that is currently `PARKED`; a
    request against a ticket in any other `park_status` is rejected with
    `ERR_TICKET_NOT_PARKED`."

    Design: Difficulty/cross_entity_state_dependency/retrieval_create_requires_ticket_parked
    """
    env = setup_settled_ticket()  # ticket park_status CLOSED
    hdr = make_attendant_headers(env["attendant"]["id"])
    res = api.create_retrieval_request(
        create_retrieval_request_payload(env["ticket"]["id"],
                                         requested_at="2026-06-01T12:40:00Z"), hdr)
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_PARKED)


def test_retrieval_on_parked_ticket_allowed(api):
    """PRD §3.6: "When a customer asks for their car, an `Attendant` opens a
    **RetrievalRequest** against the ticket via `ticket_id`, recording `requested_at`. A
    retrieval may only be opened for a ticket that is currently `PARKED`".

    Design: Difficulty/cross_entity_state_dependency/retrieval_create_requires_ticket_parked
    """
    env = setup_checked_in_ticket()  # ticket park_status PARKED
    hdr = make_attendant_headers(env["attendant"]["id"])
    res = api.create_retrieval_request(
        create_retrieval_request_payload(env["ticket"]["id"]), hdr)
    rr = validate_success(res, 201)
    assert rr["status"] == "REQUESTED"


def test_assign_to_scheduled_shift_attendant_rejected(api):
    """PRD §3.6: "Assigning a runner advances `REQUESTED` to `ASSIGNED` and sets the request's
    `attendant_id` from the supplied `attendant_id`; the named runner must currently be on an
    `ACTIVE` shift, and if they are not the assignment is rejected with
    `ERR_ATTENDANT_SHIFT_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/retrieval_assign_requires_active_shift
    """
    env = setup_requested_retrieval()
    a2 = create_attendant(env["venue"]["id"], name="Bob")
    create_shift(a2["id"], "2026-06-01T07:00:00Z", "2026-06-01T20:00:00Z")  # SCHEDULED, never started
    hdr = make_attendant_headers(env["attendant"]["id"])
    res = api.assign_retrieval(env["retrieval"]["id"], {"attendant_id": a2["id"]}, hdr)
    validate_error(res, ApiErrorId.ERR_ATTENDANT_SHIFT_INACTIVE)


def test_assign_to_active_shift_attendant_allowed(api):
    """PRD §3.6: "Assigning a runner advances `REQUESTED` to `ASSIGNED` and sets the request's
    `attendant_id` from the supplied `attendant_id`; the named runner must currently be on an
    `ACTIVE` shift".

    Design: Difficulty/cross_entity_state_dependency/retrieval_assign_requires_active_shift
    """
    env = setup_requested_retrieval()
    a2 = create_attendant(env["venue"]["id"], name="Bob")
    create_active_shift(a2["id"])  # ACTIVE
    hdr = make_attendant_headers(env["attendant"]["id"])
    res = api.assign_retrieval(env["retrieval"]["id"], {"attendant_id": a2["id"]}, hdr)
    rr = validate_success(res, 200)
    assert rr["status"] == "ASSIGNED"
    assert rr["attendant_id"] == a2["id"]


def test_revert_from_ready_returns_to_staging(api):
    """PRD §3.6: "From `READY` it goes back to `STAGING` (for a delayed customer or a wrongly
    pulled car), which reverses the earlier cross-entity effect by setting the ticket's
    `park_status` back to `PARKED` and clearing `ready_at`."

    Design: Difficulty/non_linear_state_machine/retrieval_ready_to_staging_cycle
    """
    env = setup_retrieval_ready()  # retrieval READY, ticket RETRIEVED
    hdr = make_attendant_headers(env["attendant"]["id"])
    rr = validate_success(api.revert_retrieval(env["retrieval"]["id"], hdr), 200)
    assert rr["status"] == "STAGING"


def test_revert_from_ready_returns_ticket_to_parked(api):
    """PRD §3.6: "From `READY` it goes back to `STAGING` (for a delayed customer or a wrongly
    pulled car), which reverses the earlier cross-entity effect by setting the ticket's
    `park_status` back to `PARKED` and clearing `ready_at`."

    Design: Difficulty/non_linear_state_machine/retrieval_ready_to_staging_cycle
    """
    env = setup_retrieval_ready()
    hdr = make_attendant_headers(env["attendant"]["id"])
    rr = validate_success(api.revert_retrieval(env["retrieval"]["id"], hdr), 200)
    assert rr["ready_at"] is None
    ticket = validate_success(api.get_ticket(env["ticket"]["id"], SUP), 200)
    assert ticket["park_status"] == "PARKED"


def test_stage_from_requested_rejected(api):
    """PRD §3.6: "The request then walks a small state machine, each hop driven by an
    `Attendant`, and any hop attempted from the wrong current status is rejected with
    `ERR_RETRIEVAL_BAD_STATE`."
    PRD §3.6: "Staging advances `ASSIGNED` to `STAGING` as the runner goes to fetch the
    vehicle."

    Design: Corner/state_machines/retrieval_stage_from_requested_returns_bad_state
    """
    env = setup_requested_retrieval()  # retrieval still REQUESTED (never ASSIGNED)
    hdr = make_attendant_headers(env["attendant"]["id"])
    res = api.stage_retrieval(env["retrieval"]["id"], hdr)
    validate_error(res, ApiErrorId.ERR_RETRIEVAL_BAD_STATE)
