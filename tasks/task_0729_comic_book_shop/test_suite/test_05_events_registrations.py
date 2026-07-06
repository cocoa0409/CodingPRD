"""Events, signings, registrations: overlap semantics, capacity, precedence, cascades."""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_customer,
    create_open_event,
    register_customer,
    create_event_payload,
    create_event_registration_payload,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap: event half-open overlap at same location
# ---------------------------------------------------------------------------
def test_event_overlap_same_store_location_rejected(api, clerk_headers):
    """PRD §3.6: "creating an event whose window overlaps a non-cancelled event at
    the same location — treating each window as the half-open interval from
    `starts_at` up to but not including `ends_at` — is rejected with
    `ERR_EVENT_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/event_halfopen_overlap_same_store_location
    """
    validate_success(
        api.create_event(create_event_payload(name="E1", store_location="OVL",
                                              starts_at="2026-05-01T10:00:00Z",
                                              ends_at="2026-05-01T12:00:00Z", capacity=10),
                         clerk_headers),
        201,
    )
    res = api.create_event(
        create_event_payload(name="E2", store_location="OVL",
                             starts_at="2026-05-01T11:00:00Z",
                             ends_at="2026-05-01T13:00:00Z", capacity=10),
        clerk_headers,
    )
    validate_error(res, ApiErrorId.ERR_EVENT_TIME_CONFLICT, expected_status=409)


def test_event_adjacent_half_open_no_conflict(api, clerk_headers):
    """PRD §3.6: "treating each window as the half-open interval from `starts_at` up to but not including `ends_at"

    Design: Difficulty/resource_temporal_overlap/event_halfopen_overlap_same_store_location
    """
    validate_success(
        api.create_event(create_event_payload(name="E1", store_location="ADJ",
                                              starts_at="2026-05-01T10:00:00Z",
                                              ends_at="2026-05-01T12:00:00Z", capacity=10),
                         clerk_headers),
        201,
    )
    # [12:00,14:00) touches [10:00,12:00) only at the exclusive endpoint -> no overlap.
    res = api.create_event(
        create_event_payload(name="E2", store_location="ADJ",
                             starts_at="2026-05-01T12:00:00Z",
                             ends_at="2026-05-01T14:00:00Z", capacity=10),
        clerk_headers,
    )
    validate_success(res, 201)


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap: buffered registration overlap same customer
# ---------------------------------------------------------------------------
def test_registration_buffered_overlap_same_customer_rejected(api, clerk_headers):
    """PRD §3.6: "the customer must not already be registered for another event whose window, expanded by a 30-minute buffer on each side, overlaps this event's window (else `ERR_REGISTRATION_TIME_CONFLICT`)"

    Design: Difficulty/resource_temporal_overlap/registration_buffered_overlap_same_customer
    """
    cust = create_customer()
    ev_a = create_open_event(store_location="LOC_A", starts_at="2026-05-04T10:00:00Z",
                             ends_at="2026-05-04T12:00:00Z", capacity=10, name="A")
    ev_b = create_open_event(store_location="LOC_B", starts_at="2026-05-04T12:15:00Z",
                             ends_at="2026-05-04T13:00:00Z", capacity=10, name="B")
    register_customer(cust["id"], ev_a["id"])
    # buffered A [9:30,12:30) overlaps buffered B [11:45,13:30) though raw windows do not.
    res = api.create_event_registration(
        create_event_registration_payload(cust["id"], ev_b["id"]), clerk_headers
    )
    validate_error(res, ApiErrorId.ERR_REGISTRATION_TIME_CONFLICT, expected_status=409)


def test_registration_far_apart_no_buffer_conflict(api, clerk_headers):
    """PRD §3.6: "the customer must not already be registered for another event whose window, expanded by a 30-minute buffer on each side, overlaps this event's window (else `ERR_REGISTRATION_TIME_CONFLICT`)"

    Design: Difficulty/resource_temporal_overlap/registration_buffered_overlap_same_customer
    """
    cust = create_customer()
    ev_a = create_open_event(store_location="LOC_A", starts_at="2026-05-04T10:00:00Z",
                             ends_at="2026-05-04T12:00:00Z", capacity=10, name="A")
    # ev_c starts well beyond the 30-min buffer of A's [10:00,12:00) window.
    ev_c = create_open_event(store_location="LOC_C", starts_at="2026-05-04T15:00:00Z",
                             ends_at="2026-05-04T16:00:00Z", capacity=10, name="C")
    register_customer(cust["id"], ev_a["id"])
    reg = validate_success(
        api.create_event_registration(
            create_event_registration_payload(cust["id"], ev_c["id"]), clerk_headers
        ),
        201,
    )
    assert reg["status"] == "REGISTERED"


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict: CLOSED beats FULL
# ---------------------------------------------------------------------------
def test_registration_closed_event_reports_closed_not_full(api, clerk_headers):
    """PRD §3.6: "the event must be `OPEN` (else `ERR_EVENT_CLOSED`)"
    PRD §2.8: "A lower-numbered check that fails masks any higher-numbered check
    that would also have failed."

    Design: Difficulty/priority_pair_validation_conflict/event_registration_closed_beats_full
    """
    c1 = create_customer()
    c2 = create_customer()
    ev = create_open_event(capacity=1, store_location="LOC5B",
                           starts_at="2026-05-01T10:00:00Z",
                           ends_at="2026-05-01T12:00:00Z", name="Signing")
    register_customer(c1["id"], ev["id"])  # fills capacity
    validate_success(api.transition_event(ev["id"], {"to_status": "CLOSED"}, clerk_headers), 200)
    # Event is both CLOSED (priority 7) and full (priority 8): CLOSED masks FULL.
    res = api.create_event_registration(
        create_event_registration_payload(c2["id"], ev["id"]), clerk_headers
    )
    validate_error(res, ApiErrorId.ERR_EVENT_CLOSED, expected_status=409)


def test_registration_closed_full_event_not_reported_full(api, clerk_headers):
    """PRD §2.8: "Referential state — required linked-entity states (issue on sale,
    event open, series active, consignor active), yielding ERR_ISSUE_NOT_ON_SALE,
    ERR_EVENT_CLOSED, ERR_SERIES_DISCONTINUED, or ERR_CUSTOMER_BANNED (409)."

    Design: Difficulty/priority_pair_validation_conflict/event_registration_closed_beats_full
    """
    c1 = create_customer()
    c2 = create_customer()
    ev = create_open_event(capacity=1, store_location="LOC5C",
                           starts_at="2026-05-01T10:00:00Z",
                           ends_at="2026-05-01T12:00:00Z", name="Signing2")
    register_customer(c1["id"], ev["id"])
    validate_success(api.transition_event(ev["id"], {"to_status": "CLOSED"}, clerk_headers), 200)
    res = api.create_event_registration(
        create_event_registration_payload(c2["id"], ev["id"]), clerk_headers
    )
    # Confirm the reported error is the referential CLOSED, not the capacity FULL.
    body = res.json()
    assert body["data"]["error_id"] == "ERR_EVENT_CLOSED"


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check: capacity boundary
# ---------------------------------------------------------------------------
def test_registration_at_capacity_rejected(api, clerk_headers):
    """PRD §3.6: "the event must not be full, meaning `registered_count` has reached `capacity` (else `ERR_EVENT_FULL`)"

    Design: Difficulty/boundary_precision_check/event_registration_at_capacity_rejects
    """
    c1 = create_customer()
    c2 = create_customer()
    c3 = create_customer()
    ev = create_open_event(capacity=2, store_location="LOC6B",
                           starts_at="2026-05-02T10:00:00Z",
                           ends_at="2026-05-02T12:00:00Z", name="Panel")
    register_customer(c1["id"], ev["id"])
    register_customer(c2["id"], ev["id"])
    res = api.create_event_registration(
        create_event_registration_payload(c3["id"], ev["id"]), clerk_headers
    )
    validate_error(res, ApiErrorId.ERR_EVENT_FULL, expected_status=409)
    ev_after = validate_success(api.get_event(ev["id"], clerk_headers), 200)
    assert ev_after["registered_count"] == 2


def test_registration_up_to_capacity_succeeds(api, clerk_headers):
    """PRD §3.6: "the event must not be full, meaning `registered_count` has reached `capacity` (else `ERR_EVENT_FULL`)"

    Design: Difficulty/boundary_precision_check/event_registration_at_capacity_rejects
    """
    c1 = create_customer()
    c2 = create_customer()
    ev = create_open_event(capacity=2, store_location="LOC6C",
                           starts_at="2026-05-02T10:00:00Z",
                           ends_at="2026-05-02T12:00:00Z", name="Panel2")
    register_customer(c1["id"], ev["id"])
    reg2 = register_customer(c2["id"], ev["id"])  # exactly fills capacity 2
    assert reg2["status"] == "REGISTERED"
    ev_after = validate_success(api.get_event(ev["id"], clerk_headers), 200)
    assert ev_after["registered_count"] == 2


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency: check-in requires OPEN event
# ---------------------------------------------------------------------------
def test_checkin_requires_event_open(api, clerk_headers):
    """PRD §3.6: "Staff check a registrant in, moving `REGISTERED` to `CHECKED_IN`, but only while the event is `OPEN` (else `ERR_EVENT_CLOSED`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_open
    """
    cust = create_customer()
    ev = create_open_event(capacity=5, store_location="LOC7B",
                           starts_at="2026-05-03T10:00:00Z",
                           ends_at="2026-05-03T12:00:00Z", name="Meet")
    reg = register_customer(cust["id"], ev["id"])
    validate_success(api.transition_event(ev["id"], {"to_status": "CLOSED"}, clerk_headers), 200)
    res = api.transition_event_registration(reg["id"], {"to_status": "CHECKED_IN"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_EVENT_CLOSED, expected_status=409)


def test_checkin_allowed_while_event_open(api, clerk_headers):
    """PRD §3.6: "Staff check a registrant in, moving `REGISTERED` to `CHECKED_IN`, but only while the event is `OPEN` (else `ERR_EVENT_CLOSED`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_open
    """
    cust = create_customer()
    ev = create_open_event(capacity=5, store_location="LOC7C",
                           starts_at="2026-05-03T10:00:00Z",
                           ends_at="2026-05-03T12:00:00Z", name="Meet2")
    reg = register_customer(cust["id"], ev["id"])
    checked = validate_success(
        api.transition_event_registration(reg["id"], {"to_status": "CHECKED_IN"}, clerk_headers),
        200,
    )
    assert checked["status"] == "CHECKED_IN"


# ---------------------------------------------------------------------------
# Queue B — state machines / validations / errors
# ---------------------------------------------------------------------------
def test_event_complete_marks_registered_no_show(api, clerk_headers):
    """PRD §3.6: "Completion transitions every registration still in `REGISTERED` to `NO_SHOW`."

    Design: Corner/state_machines/event_complete_marks_registered_no_show
    """
    cust = create_customer()
    ev = create_open_event(capacity=5, store_location="LOCC",
                           starts_at="2026-05-05T10:00:00Z",
                           ends_at="2026-05-05T12:00:00Z", name="Cmp")
    reg = register_customer(cust["id"], ev["id"])
    validate_success(api.transition_event(ev["id"], {"to_status": "CLOSED"}, clerk_headers), 200)
    validate_success(api.transition_event(ev["id"], {"to_status": "COMPLETED"}, clerk_headers), 200)
    reg_after = validate_success(api.get_event_registration(reg["id"], clerk_headers), 200)
    assert reg_after["status"] == "NO_SHOW"


def test_duplicate_event_registration_rejected(api, clerk_headers):
    """PRD §3.6: "the customer must not already hold a `REGISTERED` or `CHECKED_IN` registration for the same event (else `ERR_DUPLICATE_REGISTRATION`)"

    Design: Corner/validations/duplicate_event_registration_rejected
    """
    cust = create_customer()
    ev = create_open_event(capacity=5, store_location="LOCD",
                           starts_at="2026-05-06T10:00:00Z",
                           ends_at="2026-05-06T12:00:00Z", name="Dup")
    register_customer(cust["id"], ev["id"])
    res = api.create_event_registration(
        create_event_registration_payload(cust["id"], ev["id"]), clerk_headers
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_REGISTRATION, expected_status=409)


def test_event_ends_before_starts_validation(api, clerk_headers):
    """PRD §3.6: "an `ends_at` that must be strictly later than `starts_at"
    PRD §2.8: "Well-formedness — required fields present, enums valid, numbers in
    range, ends_at strictly after starts_at, and commission_pct at least 0 and
    strictly below 1, else ERR_VALIDATION (400)."

    Design: Corner/validations/event_ends_before_starts_validation
    """
    res = api.create_event(
        create_event_payload(name="Bad", store_location="LOCX",
                             starts_at="2026-05-07T12:00:00Z",
                             ends_at="2026-05-07T10:00:00Z", capacity=5),
        clerk_headers,
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_event_registration_after_start_rejected(api, clerk_headers):
    """PRD §3.6: "the logical clock must be strictly before the event's `starts_at` (else `ERR_EVENT_ALREADY_STARTED`)"

    Design: Corner/errors/event_registration_after_start_rejected
    """
    cust = create_customer()
    ev = create_open_event(capacity=5, store_location="LOCL",
                           starts_at="2026-05-08T10:00:00Z",
                           ends_at="2026-05-08T12:00:00Z", name="Late")
    validate_success(api.set_clock("2026-05-08T11:00:00Z", clerk_headers), 200)
    res = api.create_event_registration(
        create_event_registration_payload(cust["id"], ev["id"]), clerk_headers
    )
    validate_error(res, ApiErrorId.ERR_EVENT_ALREADY_STARTED, expected_status=422)
