"""Event registrations: capacity boundary and FULL flip, registration_status gating,
the conserved registered_count ledger, idempotent cancel, and reverse lookup."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    new_constituent, new_representative, new_venue, new_event, open_registration, register,
    open_event, open_event_with_registration,
    TEST_USERS,
)

ADMIN = TEST_USERS["office_admin_headers"]


# --- Difficulty: boundary_precision_check / event_capacity_full_at_equal ---

def test_registration_flips_full_at_capacity(api):
    """PRD §3.7: "the event's `registered_count` is incremented by one, and if that
    brings it up to `capacity` the `registration_status` flips to `FULL`".

    Design: Difficulty/boundary_precision_check/event_capacity_full_at_equal
    """
    s = open_event(api, event_capacity=1, venue_capacity=5)
    con1 = new_constituent(api, s["rep_id"], email="c1@x.com")
    validate_success(api.create_registration(s["event_id"], {"constituent_id": con1["id"]}, ADMIN),
                     expected_status=201)
    event = validate_success(api.get_event(s["event_id"], ADMIN))
    assert event["registered_count"] == 1
    assert event["registration_status"] == "FULL", "reaching capacity must flip registration_status to FULL"


def test_registration_rejected_when_full(api):
    """PRD §3.7: "the event's `registered_count` is strictly less than its `capacity`
    (else `ERR_EVENT_FULL`)."

    Design: Difficulty/boundary_precision_check/event_capacity_full_at_equal
    """
    s = open_event(api, event_capacity=1, venue_capacity=5)
    con1 = new_constituent(api, s["rep_id"], email="c1@x.com")
    con2 = new_constituent(api, s["rep_id"], email="c2@x.com")
    validate_success(api.create_registration(s["event_id"], {"constituent_id": con1["id"]}, ADMIN),
                     expected_status=201)
    resp = api.create_registration(s["event_id"], {"constituent_id": con2["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL)


# --- Difficulty: cross_entity_state_dependency / registration_gated_by_event_registration_status ---

def test_registration_blocked_when_registration_closed(api):
    """PRD §3.7: "Registration is admitted only when the event's `lifecycle_status` is
    `SCHEDULED` and its `registration_status` is `OPEN`".
    PRD §2.6: "State — the target resource is in a state that permits the requested
    transition (per the workflow rules in §3), else the entity-specific conflict error
    (409): `ERR_CASE_INVALID_STATE`, `ERR_REFERRAL_INVALID_STATE`, `ERR_EVENT_INVALID_STATE`,
    or `ERR_REGISTRATION_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/registration_gated_by_event_registration_status
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    venue = new_venue(api, capacity=100)
    event = new_event(api, rep["id"], venue["id"], "2026-05-03T18:00:00Z", "2026-05-03T19:00:00Z", capacity=20)
    # registration_status is still CLOSED (open-registration not called).
    resp = api.create_registration(event["id"], {"constituent_id": con["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVENT_INVALID_STATE)


def test_registration_allowed_after_open(api):
    """PRD §3.7: "An `OfficeAdmin` opens registration on a scheduled event whose
    registration is currently `CLOSED`, which sets `registration_status` to `OPEN`".

    Design: Difficulty/cross_entity_state_dependency/registration_gated_by_event_registration_status
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    venue = new_venue(api, capacity=100)
    event = new_event(api, rep["id"], venue["id"], "2026-05-03T18:00:00Z", "2026-05-03T19:00:00Z", capacity=20)
    open_registration(api, event["id"])
    reg = validate_success(api.create_registration(event["id"], {"constituent_id": con["id"]}, ADMIN),
                           expected_status=201)
    assert reg["status"] == "REGISTERED"


# --- Difficulty: compensating_invariant / event_registered_count_conserved ---

def test_registered_count_after_register(api):
    """PRD §3.7: "the event's `registered_count` is incremented by one".

    Design: Difficulty/compensating_invariant/event_registered_count_conserved
    """
    s = open_event_with_registration(api, event_capacity=10, venue_capacity=40)
    event = validate_success(api.get_event(s["event_id"], ADMIN))
    assert event["registered_count"] == 1, "registering must raise registered_count to 1"


def test_registered_count_restored_after_cancel(api):
    """PRD §3.7: "Cancelling moves it to `CANCELLED`, decrements the event's
    `registered_count` by one ... and decrements the constituent's
    `upcoming_event_count` by one."

    Design: Difficulty/compensating_invariant/event_registered_count_conserved
    """
    s = open_event_with_registration(api, event_capacity=10, venue_capacity=40)
    reg = validate_success(api.cancel_registration(s["reg_id"], ADMIN))
    assert reg["status"] == "CANCELLED"
    event = validate_success(api.get_event(s["event_id"], ADMIN))
    assert event["registered_count"] == 0, "cancel must restore registered_count to its pre-register value 0"
    con = validate_success(api.get_constituent(s["con_id"], ADMIN))
    assert con["upcoming_event_count"] == 0, "cancel must restore upcoming_event_count to 0"


# --- Corner: state_machines / cancel_registration_twice_rejected ---

def test_cancel_registration_twice_rejected(api):
    """PRD §3.7: "An already-cancelled registration cannot be cancelled again
    (`ERR_REGISTRATION_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_registration_twice_rejected
    """
    s = open_event_with_registration(api, event_capacity=5, venue_capacity=20)
    validate_success(api.cancel_registration(s["reg_id"], ADMIN))
    resp = api.cancel_registration(s["reg_id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_INVALID_STATE)
    event = validate_success(api.get_event(s["event_id"], ADMIN))
    assert event["registered_count"] == 0, "a rejected second cancel must not double-decrement"


# --- Corner: endpoints / registrations_reverse_lookup_by_constituent ---

def test_registrations_reverse_lookup_by_constituent(api):
    """PRD §3.7: "registrations can be listed globally filtered by `constituent_id`,
    `event_id`, or `status`."

    Design: Corner/endpoints/registrations_reverse_lookup_by_constituent
    """
    s = open_event_with_registration(api, event_capacity=5, venue_capacity=20)
    resp = api.list_registrations(ADMIN, params={"constituent_id": s["con_id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 registration, got {len(data)}"
    assert data[0]["id"] == s["reg_id"]
