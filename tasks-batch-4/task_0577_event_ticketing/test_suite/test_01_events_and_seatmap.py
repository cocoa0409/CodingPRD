"""Event lifecycle, versioning, seat-map construction, and top-level RBAC/existence.

Every test builds its own entities from scratch (empty DB per test).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    create_event_payload, create_price_level_payload, create_seat_payload,
    make_promoter_headers,
    register_buyer, create_event, create_price_level, create_seat, set_status,
    setup_onsale_event,
)

BOX = TEST_USERS["box_office_headers"]
PROMOTER = make_promoter_headers()


# ─── Corner: entities / errors / rbac ─────────────────────────────────────
def test_event_get_nonexistent_returns_not_found(api):
    """PRD §2.9: "an unresolved event yields `ERR_EVENT_NOT_FOUND`; an unresolved or
    cross-event `price_level_id` yields `ERR_PRICE_LEVEL_NOT_FOUND`".

    Design: Corner/entities/event_get_nonexistent_returns_not_found
    """
    res = api.get_event(NON_EXISTENT_UUID, BOX)
    validate_error(res, ApiErrorId.ERR_EVENT_NOT_FOUND.value, expected_status=404)


def test_seats_list_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object, where `total_count` is the number of
    matching items before pagination and `has_more` indicates whether items remain beyond
    the current page."

    Design: Corner/entities/seats_list_returns_paginated_envelope
    """
    event = create_event()
    pl = create_price_level(event["id"])
    create_seat(event["id"], pl["id"], seat_number="1")
    create_seat(event["id"], pl["id"], seat_number="2")

    data, meta = validate_paginated(api.list_seats(BOX, params={"event_id": event["id"]}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert len(data) == 2


def test_duplicate_seat_returns_duplicate_seat(api):
    """PRD §3.1: "The triple of `section`, `row`, and `seat_number` must be unique within an
    event; a repeat is rejected with `ERR_DUPLICATE_SEAT`."

    Design: Corner/validations/duplicate_seat_returns_duplicate_seat
    """
    event = create_event()
    pl = create_price_level(event["id"])
    create_seat(event["id"], pl["id"], section="A", row="1", seat_number="1")

    res = api.create_seat(
        event["id"], create_seat_payload(pl["id"], section="A", row="1", seat_number="1"), BOX
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SEAT.value, expected_status=409)


def test_gatescanner_cannot_create_event(api, gate_scanner_headers):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation — or a buyer attempts to act on a resource it does not
    own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." (event creation is
    limited to Promoter and BoxOffice per §4.)

    Design: Corner/rbac/gatescanner_cannot_create_event
    """
    res = api.create_event(create_event_payload(), gate_scanner_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_unknown_role_returns_unauthenticated(api, unknown_role_headers):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the roles
    the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    res = api.create_buyer({"name": "X", "email": "x@example.com"}, unknown_role_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_event_version_increments_on_status_transition(api):
    """PRD §2.4: "The `version` starts at 1 when the resource is created and increases by
    exactly 1 on every mutation of that resource."
    PRD §3.1: "every legal transition increments the event's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/event_version_increments_on_status_transition
    """
    created = validate_success(api.create_event(create_event_payload(), PROMOTER), 201)
    assert created["version"] == 1, f"event should be created at version 1, got {created['version']}"
    api.create_price_level(created["id"], create_price_level_payload(), PROMOTER)

    announced = validate_success(
        api.set_event_status(created["id"], {"target_status": "ANNOUNCED"}, PROMOTER), 200
    )
    assert announced["version"] == 2, f"version should be 2 after ANNOUNCED, got {announced['version']}"


def test_event_cancel_twice_returns_invalid_state(api):
    """PRD §3.1: "Any attempt to drive a transition that is not legal from the event's
    current status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/event_cancel_twice_returns_invalid_state
    """
    event = create_event()
    set_status(event["id"], "CANCELED")
    res = api.set_event_status(event["id"], {"target_status": "CANCELED"}, PROMOTER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ─── Difficulty: existence outranks the uniqueness constraint ─────────────
def test_seat_create_notfound_beats_duplicate_seat(api):
    """PRD §2.9: "existence of every referenced identifier — path identifiers and body
    foreign keys alike — resolved left to right, failing with the entity-specific not-found
    error". PRD §2.9: "when creating a seat the `event_id` in the path is resolved before the
    `price_level_id` in the body". PRD §2.9: "an unresolved or cross-event `price_level_id`
    yields `ERR_PRICE_LEVEL_NOT_FOUND`".

    Design: Difficulty/priority_pair_validation_conflict/seat_create_notfound_beats_duplicate_seat
    """
    event = create_event()
    pl = create_price_level(event["id"])
    create_seat(event["id"], pl["id"], section="A", row="1", seat_number="1")

    # Names a nonexistent price_level_id AND duplicates (A,1,1): existence resolution wins.
    res = api.create_seat(
        event["id"],
        create_seat_payload(NON_EXISTENT_UUID, section="A", row="1", seat_number="1"),
        BOX,
    )
    validate_error(res, ApiErrorId.ERR_PRICE_LEVEL_NOT_FOUND.value, expected_status=404)


def test_seat_create_duplicate_alone_returns_duplicate_seat(api):
    """PRD §3.1: "The triple of `section`, `row`, and `seat_number` must be unique within an
    event; a repeat is rejected with `ERR_DUPLICATE_SEAT`." — with a resolvable price level
    the uniqueness constraint is what surfaces, confirming §2.9's existence-before-constraint
    ordering.

    Design: Difficulty/priority_pair_validation_conflict/seat_create_notfound_beats_duplicate_seat
    """
    event = create_event()
    pl = create_price_level(event["id"])
    create_seat(event["id"], pl["id"], section="A", row="1", seat_number="1")

    res = api.create_seat(
        event["id"], create_seat_payload(pl["id"], section="A", row="1", seat_number="1"), BOX
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SEAT.value, expected_status=409)


# ─── Difficulty: ONSALE -> POSTPONED -> ONSALE reschedule cycle ───────────
def test_event_postpone_from_onsale_updates_datetime(api):
    """PRD §3.1: "The postpone transition takes a `new_event_datetime` that must be strictly
    after the current clock; it sets the event's `event_datetime` to that value".

    Design: Difficulty/non_linear_state_machine/event_onsale_postpone_onsale_cycle
    """
    env = setup_onsale_event(num_seats=1)
    ev_id = env["event"]["id"]
    postponed = validate_success(
        api.set_event_status(
            ev_id,
            {"target_status": "POSTPONED", "new_event_datetime": "2026-09-01T19:00:00Z"},
            PROMOTER,
        ),
        200,
    )
    assert postponed["status"] == "POSTPONED"
    assert postponed["event_datetime"] == "2026-09-01T19:00:00Z"


def test_event_reschedule_postponed_back_to_onsale_bumps_version(api):
    """PRD §3.1: "The `POSTPONED → ONSALE` leg is the reschedule step that puts the show back
    on sale, forming the cyclic loop between the two states." PRD §3.1: "every legal
    transition increments the event's `version` by 1."

    Design: Difficulty/non_linear_state_machine/event_onsale_postpone_onsale_cycle
    """
    env = setup_onsale_event(num_seats=1)
    ev_id = env["event"]["id"]
    v_onsale1 = env["event"]["version"]

    postponed = validate_success(
        api.set_event_status(
            ev_id,
            {"target_status": "POSTPONED", "new_event_datetime": "2026-09-01T19:00:00Z"},
            PROMOTER,
        ),
        200,
    )
    reonsale = validate_success(
        api.set_event_status(ev_id, {"target_status": "ONSALE"}, PROMOTER), 200
    )
    assert reonsale["status"] == "ONSALE"
    assert postponed["version"] > v_onsale1
    assert reonsale["version"] > postponed["version"]
