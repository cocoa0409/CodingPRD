"""Showing appointments, the device gateway and how the log attributes an entry."""

from test_helpers import (
    ApiErrorId,
    approve_grant,
    device_attempt,
    issue_active_credential,
    read_grant,
    read_lockbox,
    read_showing,
    request_grant,
    request_showing,
    setup_assigned_box,
    setup_placed_box,
    setup_placed_box_with_credential,
    showing_action,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_second_agent,
    confirm_showing,
    create_listing,
    intake_lockbox,
    make_member_headers,
    place_lockbox,
    read_access_event,
    register_association,
    enroll_member,
    set_clock,
    setup_association_with_agent,
)


def test_showing_confirmation_refused_without_a_placed_lockbox(api, admin_headers):
    """PRD §3.6: "There must be a placement on that listing whose `placement_status` is
    `PLACED` — an agent cannot be booked into a house with no box on the door, and the absence
    of one is `ERR_SHOWING_NO_LOCKBOX`."

    Design: Difficulty/cross_entity_state_dependency/showing_confirmation_gated_by_placed_lockbox_placement
    """
    ctx = setup_assigned_box()
    listing = create_listing(ctx["association_id"], ctx["agent_id"])
    appointment = request_showing(listing["id"], ctx["agent_id"])

    response = api.showing_state(
        appointment["id"],
        {
            "action": "CONFIRM",
            "expected_appointment_version": appointment["version"],
        },
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_SHOWING_NO_LOCKBOX.value)
    assert read_showing(appointment["id"])["status"] == "REQUESTED"


def test_showing_confirms_once_the_box_is_hanging_on_the_property(api, admin_headers):
    """PRD §3.6: "Confirmation moves it `REQUESTED → CONFIRMED` and is where the real checks
    live. The listing must be in `ACTIVE` or `UNDER_CONTRACT`. There must be a placement on
    that listing whose `placement_status` is `PLACED` — an agent cannot be booked into a house
    with no box on the door, and the absence of one is `ERR_SHOWING_NO_LOCKBOX`."
    PRD §3.4: "On success the box moves `ASSIGNED → PLACED` with `current_listing_id` set to
    the listing, and a placement record is written with `placement_status` of `PLACED`,
    `billing_status` of `NONE`, `placed_at` at the current logical clock, and
    `placed_by_member_id` recorded — copied from `X-User-ID` when a `Member` places the box,
    and from the box's `assigned_member_id` when an administrator places it on the holder's
    behalf."

    Design: Difficulty/cross_entity_state_dependency/showing_confirmation_gated_by_placed_lockbox_placement
    """
    ctx = setup_assigned_box()
    listing = create_listing(ctx["association_id"], ctx["agent_id"])
    appointment = request_showing(listing["id"], ctx["agent_id"])
    api.showing_state(
        appointment["id"],
        {"action": "CONFIRM", "expected_appointment_version": appointment["version"]},
        make_member_headers(ctx["agent_id"]),
    )

    place_lockbox(ctx["lockbox_id"], listing["id"], ctx["agent_id"])
    retry = api.showing_state(
        appointment["id"],
        {"action": "CONFIRM", "expected_appointment_version": appointment["version"]},
        make_member_headers(ctx["agent_id"]),
    )
    confirmed = validate_success(retry, 200)
    assert confirmed["status"] == "CONFIRMED"

    lockbox = read_lockbox(ctx["lockbox_id"])
    assert lockbox["status"] == "PLACED"
    assert lockbox["current_listing_id"] == listing["id"]


def _listing_with_one_confirmed_showing():
    """A listing at its default capacity of one, already carrying a confirmed 10:00-11:00
    showing, plus two further requested windows."""
    ctx = setup_placed_box(concurrent_showing_limit=1)
    add_second_agent(ctx)
    first = request_showing(
        ctx["listing_id"],
        ctx["other_agent_id"],
        window_start="2026-08-07T10:00:00Z",
        window_end="2026-08-07T11:00:00Z",
    )
    confirm_showing(first["id"], member_id=ctx["other_agent_id"])
    ctx["touching"] = request_showing(
        ctx["listing_id"],
        ctx["other_agent_id"],
        window_start="2026-08-07T11:00:00Z",
        window_end="2026-08-07T12:00:00Z",
    )
    ctx["disjoint"] = request_showing(
        ctx["listing_id"],
        ctx["other_agent_id"],
        window_start="2026-08-07T11:01:00Z",
        window_end="2026-08-07T12:00:00Z",
    )
    return ctx


def test_showing_starting_at_the_exact_minute_another_ends_exceeds_capacity(api, admin_headers):
    """PRD §2.10: "Two showings overlap when the first begins at or before the second ends and
    the second begins at or before the first ends — so an appointment starting at the exact
    minute another ends *does* count as an overlap."
    PRD §3.6: "Finally, capacity: counting the *other* appointments on the same listing that
    are currently in `CONFIRMED` and whose closed interval intersects this one, the
    confirmation is refused with `ERR_SHOWING_CAPACITY_EXCEEDED` when that count has already
    reached the listing's `concurrent_showing_limit`."

    Design: Difficulty/resource_temporal_overlap/showing_capacity_closed_interval_touching_endpoints_collide
    """
    ctx = _listing_with_one_confirmed_showing()

    response = api.showing_state(
        ctx["touching"]["id"],
        {
            "action": "CONFIRM",
            "expected_appointment_version": ctx["touching"]["version"],
        },
        make_member_headers(ctx["other_agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_SHOWING_CAPACITY_EXCEEDED.value)
    assert read_showing(ctx["touching"]["id"])["status"] == "REQUESTED"


def test_showing_starting_after_the_closed_interval_confirms(api, admin_headers):
    """PRD §2.10: "**Showing windows are closed.** A showing covers both `window_start` and
    `window_end` and everything between them."
    PRD §3.6: "Appointments in `REQUESTED`, `CANCELLED`, `COMPLETED` or `NO_SHOW` consume no
    capacity."

    Design: Difficulty/resource_temporal_overlap/showing_capacity_closed_interval_touching_endpoints_collide
    """
    ctx = _listing_with_one_confirmed_showing()
    api.showing_state(
        ctx["touching"]["id"],
        {
            "action": "CONFIRM",
            "expected_appointment_version": ctx["touching"]["version"],
        },
        make_member_headers(ctx["other_agent_id"]),
    )

    response = api.showing_state(
        ctx["disjoint"]["id"],
        {
            "action": "CONFIRM",
            "expected_appointment_version": ctx["disjoint"]["version"],
        },
        make_member_headers(ctx["other_agent_id"]),
    )
    confirmed = validate_success(response, 200)
    assert confirmed["status"] == "CONFIRMED"

    rows, _ = validate_paginated(
        api.list_showings(
            admin_headers,
            params={"listing_id": ctx["listing_id"], "status": "CONFIRMED"},
        )
    )
    assert len(rows) == 2


def test_cancelling_an_already_cancelled_showing_is_refused(api, admin_headers):
    """PRD §3.6: "Cancellation is accepted from `REQUESTED` or `CONFIRMED`, and the
    `cancel_reason` records why: `AGENT_CANCELLED` when a person cancelled it, `ACCESS_LOST`
    when one of the §2.9 cascades did. `COMPLETED`, `CANCELLED` and `NO_SHOW` are all
    terminal."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC
    timestamps with three fractional-second digits, and `version`, an integer that begins at 1
    when the resource is created and increases by exactly 1 on every mutation the server
    accepts."

    Design: Corner/state_machines/showing_cancel_twice_second_attempt_rejected
    """
    ctx = setup_association_with_agent()
    listing = create_listing(ctx["association_id"], ctx["agent_id"])
    appointment = request_showing(listing["id"], ctx["agent_id"])
    cancelled = showing_action(
        appointment["id"], "CANCEL", member_id=ctx["agent_id"]
    )
    assert cancelled["status"] == "CANCELLED"

    response = api.showing_state(
        appointment["id"],
        {"action": "CANCEL", "expected_appointment_version": cancelled["version"]},
        make_member_headers(ctx["agent_id"]),
    )
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ENTITY_TERMINAL.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
    assert response.status_code == 409

    stored = read_showing(appointment["id"])
    assert stored["status"] == "CANCELLED"
    assert stored["cancel_reason"] == "AGENT_CANCELLED"
    assert stored["version"] == 2, "a refused cancel must not advance the version"


def test_granted_entry_inside_a_confirmed_window_attributes_to_that_showing(api, admin_headers):
    """PRD §3.6: "When the outcome is `GRANTED`, a `credential_id` was supplied, and the event
    has a `listing_id`, the server looks for confirmed appointments on that listing whose
    `showing_member_id` is the member who owns the presented credential and whose closed window
    contains `occurred_at`. Among those candidates it takes the one with the earliest
    `window_start`, breaking ties by the earliest `created_at`, and writes its identifier into
    the event's `matched_appointment_id`, which in turn raises that appointment's
    `access_event_count`."
    PRD §3.6: "A confirmed showing may be completed, but only once the log agrees it happened:
    completion requires `access_event_count` of at least 1, and a completion attempt on a
    showing with no attributed access is refused with `ERR_INVALID_STATE`."

    Design: Corner/calculations/granted_event_matched_to_confirmed_showing_suppresses_penalty
    """
    ctx = setup_placed_box_with_credential(clock="2026-08-06T00:00:00Z")
    appointment = request_showing(
        ctx["listing_id"],
        ctx["agent_id"],
        window_start="2026-08-07T10:00:00Z",
        window_end="2026-08-07T11:00:00Z",
    )
    confirm_showing(appointment["id"], member_id=ctx["agent_id"])

    event = device_attempt(
        ctx["lockbox_id"],
        actor_type="MEMBER",
        credential_id=ctx["credential_id"],
        occurred_at="2026-08-07T10:30:00Z",
    )

    stored_event = read_access_event(event["id"])
    assert stored_event["outcome"] == "GRANTED"
    assert stored_event["matched_appointment_id"] == appointment["id"]
    assert stored_event["listing_id"] == ctx["listing_id"]

    completed = showing_action(appointment["id"], "COMPLETE", member_id=ctx["agent_id"])
    assert completed["status"] == "COMPLETED"
    assert read_showing(appointment["id"])["access_event_count"] == 1

    rows, _ = validate_paginated(
        api.list_access_events(
            admin_headers, params={"matched_appointment_id": appointment["id"]}
        )
    )
    assert len(rows) == 1


def test_granted_attempt_consumes_a_single_use_grant(api, admin_headers, device_headers):
    """PRD §3.5: "A grant reaches `CONSUMED` when a granted access attempt raises its
    `uses_count` to `max_uses` — formally, when the attempt about to be recorded would bring
    the count of granted events on the grant to at least `max_uses`."
    PRD §3.5: "Optionally the request names `max_uses`, which defaults to 1 and must be at
    least 1, and `supersedes_grant_id`, pointing at an approved grant that this issuance is
    intended to replace."

    Design: Corner/state_machines/grant_auto_consumes_when_uses_count_reaches_max_uses
    """
    ctx = setup_placed_box_with_credential(clock="2026-08-06T00:00:00Z")
    grant = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="ONE_DAY_MEMBER",
        window_start="2026-08-06T09:00:00Z",
        window_end="2026-08-06T17:00:00Z",
        max_uses=1,
    )
    approve_grant(grant["id"])

    response = api.device_access_attempt(
        {
            "lockbox_id": ctx["lockbox_id"],
            "actor_type": "MEMBER",
            "credential_id": ctx["credential_id"],
            "grant_id": grant["id"],
            "occurred_at": "2026-08-06T10:00:00Z",
        },
        device_headers,
    )
    event = validate_success(response, 201)
    assert event["outcome"] == "GRANTED"

    stored_grant = read_grant(grant["id"])
    assert stored_grant["uses_count"] == 1
    assert stored_grant["status"] == "CONSUMED"

    rows, _ = validate_paginated(
        api.list_access_events(admin_headers, params={"grant_id": grant["id"]})
    )
    assert len(rows) == 1


def test_access_events_filter_by_outcome_returns_only_matching_rows(api, auditor_headers, admin_headers):
    """PRD §3.6: "Access events are append-only and are never edited afterwards. They may be
    listed and filtered by `lockbox_id`, `credential_id`, `grant_id`, `listing_id`,
    `matched_appointment_id`, `incident_review_id` and `outcome`."
    PRD §3.6: "Otherwise, if neither a `credential_id` nor a `grant_id` was supplied, the
    outcome is `DENIED_NO_CREDENTIAL`."

    Design: Corner/endpoints/access_events_filtered_by_outcome_returns_only_matching_rows
    """
    association = register_association()
    set_clock("2026-08-06T00:00:00Z")
    agent = enroll_member(association["id"])
    credential = issue_active_credential(agent["id"], credential_type="KEY_APP")
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )

    granted_event = device_attempt(
        lockbox["id"],
        actor_type="MEMBER",
        credential_id=credential["id"],
        occurred_at="2026-08-06T09:00:00Z",
    )
    denied_event = device_attempt(
        lockbox["id"], actor_type="UNKNOWN", occurred_at="2026-08-06T09:30:00Z"
    )

    filtered = api.list_access_events(
        auditor_headers,
        params={"lockbox_id": lockbox["id"], "outcome": "DENIED_NO_CREDENTIAL"},
    )
    rows, meta = validate_paginated(filtered)
    assert filtered.json()["response_type"] == "array"
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["id"] == denied_event["id"]
    assert rows[0]["outcome"] == "DENIED_NO_CREDENTIAL"

    _, all_meta = validate_paginated(
        api.list_access_events(auditor_headers, params={"lockbox_id": lockbox["id"]})
    )
    assert all_meta["total_count"] == 2

    stored_granted = read_access_event(granted_event["id"])
    assert stored_granted["outcome"] == "GRANTED"
    assert stored_granted.get("matched_appointment_id") is None
