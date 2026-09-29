"""Half-open accountability intervals and the rolling change calendar.

Two occupancy rules share a shape and differ in scope. Accountability
assignments exclude one another pairwise within a single domain and role, on
half-open intervals, so an assignment beginning exactly where the incumbent ends
is adjacent rather than conflicting. Structural change windows are policed
twice: pairwise on the freeze-window separation, and in aggregate on how many
structural changes may occupy any thirty-day span of the calendar — a request can
clear the pairwise test and still be refused by the aggregate one.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    assert_instant_equals,
    assign_steward,
    domain_version,
    setup_approved_structural_requests,
    setup_domain_awaiting_data_steward,
    setup_governed_domain,
    steward_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_assignment_starting_at_the_incumbents_exclusive_end_is_adjacent(api):
    """PRD §3.1: "The governance office supplies the `domain_id`, the
    `steward_id`, the `steward_role` held — `DATA_OWNER`, `DATA_STEWARD` or
    `CUSTODIAN` — and a half-open accountability interval: `effective_from` is
    inclusive and `effective_to`, when supplied, is exclusive, so an assignment
    covers the clock when `effective_from` is at or before the current instant
    and either `effective_to` is null or the current instant falls strictly
    before it."
    PRD §3.1: "Two assignments for the same domain and the same `steward_role`
    may not have intersecting intervals; an incoming assignment that would
    intersect an `ACTIVE` incumbent is rejected with `ERR_ASSIGNMENT_OVERLAP`
    unless the caller explicitly asks to hand over by sending
    `supersede_incumbent` set to true."
    PRD §3.1: "The incoming assignment itself is created `ACTIVE` with a null
    `superseded_at`."

    Design: Difficulty/resource_temporal_overlap/steward_assignment_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_domain_awaiting_data_steward()
    domain_id = ctx["domain"]["id"]

    first = assign_steward(
        domain_id,
        ctx["steward"]["id"],
        "DATA_STEWARD",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    assert first["status"] == "ACTIVE", (
        f"a bounded accountability interval is created ACTIVE, got {first['status']}"
    )
    assert first["superseded_at"] is None, (
        f"nothing has handed the interval over, got {first['superseded_at']!r}"
    )

    second = assign_steward(
        domain_id,
        ctx["third"]["id"],
        "DATA_STEWARD",
        effective_from="2026-09-01T00:00:00Z",
    )

    assert second["status"] == "ACTIVE", (
        "an interval opening exactly at the incumbent's exclusive end is "
        f"adjacent rather than intersecting, got {second['status']}"
    )
    assert_instant_equals(
        second["effective_from"], "2026-09-01T00:00:00Z", "effective_from"
    )
    assert second["effective_to"] is None, (
        f"the successor interval is left open-ended, got {second['effective_to']!r}"
    )


def test_interval_covering_both_incumbent_stewardships_is_rejected_as_overlap(api):
    """PRD §3.1: "Two assignments for the same domain and the same
    `steward_role` may not have intersecting intervals; an incoming assignment
    that would intersect an `ACTIVE` incumbent is rejected with
    `ERR_ASSIGNMENT_OVERLAP` unless the caller explicitly asks to hand over by
    sending `supersede_incumbent` set to true."
    PRD §3.1: "A handover drives the incumbent from `ACTIVE` to `SUPERSEDED`,
    and it is only available when the incumbent is `ACTIVE` with a null
    `effective_to`, when the incumbent's `domain_id` and `steward_role` both
    match the incoming assignment's, and when the incumbent's `effective_from`
    is strictly earlier than the incoming assignment's `effective_from`."
    PRD §2.5: "Creating a steward assignment is guarded identically: it too
    requires `expected_domain_version` matching the domain's current `version`,
    and a mismatch is rejected with `ERR_STALE_DOMAIN_VERSION` (HTTP 412)."

    Design: Difficulty/resource_temporal_overlap/steward_assignment_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_domain_awaiting_data_steward()
    domain_id = ctx["domain"]["id"]

    assign_steward(
        domain_id,
        ctx["steward"]["id"],
        "DATA_STEWARD",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    assign_steward(
        domain_id,
        ctx["third"]["id"],
        "DATA_STEWARD",
        effective_from="2026-09-01T00:00:00Z",
    )

    payload = steward_assignment_payload(
        domain_id,
        ctx["third"]["id"],
        domain_version(domain_id),
        steward_role="DATA_STEWARD",
        effective_from="2026-08-31T00:00:00Z",
    )
    response = api.create_steward_assignment(payload, GOVERNANCE_ADMIN_HEADERS)
    validate_error(response, "ERR_ASSIGNMENT_OVERLAP")


def test_rejected_overlap_creates_no_assignment_and_moves_no_domain_version(api):
    """PRD §2.5: "**`Domain.version` increments exactly once per HTTP request
    that mutates the domain row or any row the domain's derived posture and
    counters read — never once per declared side effect.**"
    PRD §2.5: "A request that ends up mutating nothing on the domain leaves
    `version` untouched."
    PRD §3.1: "Assignments may be listed filtered by `domain_id`, by
    `steward_id`, by `steward_role` and by `status`."

    Design: Difficulty/resource_temporal_overlap/steward_assignment_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_domain_awaiting_data_steward()
    domain_id = ctx["domain"]["id"]

    assign_steward(
        domain_id,
        ctx["steward"]["id"],
        "DATA_STEWARD",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    assign_steward(
        domain_id,
        ctx["third"]["id"],
        "DATA_STEWARD",
        effective_from="2026-09-01T00:00:00Z",
    )
    version_before = domain_version(domain_id)

    validate_error(
        api.create_steward_assignment(
            steward_assignment_payload(
                domain_id,
                ctx["third"]["id"],
                version_before,
                steward_role="DATA_STEWARD",
                effective_from="2026-08-31T00:00:00Z",
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_ASSIGNMENT_OVERLAP",
    )

    _rows, meta = validate_paginated(
        api.list_steward_assignments(
            GOVERNANCE_ADMIN_HEADERS,
            params={"domain_id": domain_id, "steward_role": "DATA_STEWARD"},
        )
    )
    assert meta["total_count"] == 2, (
        "only the two accepted stewardship intervals may exist, got "
        f"{meta['total_count']}"
    )
    assert domain_version(domain_id) == version_before, (
        "the rejected assignment mutated nothing, so the domain version must "
        f"stay at {version_before}, got {domain_version(domain_id)}"
    )


def test_custodian_interval_may_straddle_both_data_steward_intervals(api):
    """PRD §3.1: "Two assignments for the same domain and the same
    `steward_role` may not have intersecting intervals; an incoming assignment
    that would intersect an `ACTIVE` incumbent is rejected with
    `ERR_ASSIGNMENT_OVERLAP` unless the caller explicitly asks to hand over by
    sending `supersede_incumbent` set to true."
    PRD §3.1: "The governance office supplies the `domain_id`, the `steward_id`,
    the `steward_role` held — `DATA_OWNER`, `DATA_STEWARD` or `CUSTODIAN` — and a
    half-open accountability interval: `effective_from` is inclusive and
    `effective_to`, when supplied, is exclusive, so an assignment covers the
    clock when `effective_from` is at or before the current instant and either
    `effective_to` is null or the current instant falls strictly before it."

    Design: Difficulty/resource_temporal_overlap/steward_assignment_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_domain_awaiting_data_steward()
    domain_id = ctx["domain"]["id"]

    assign_steward(
        domain_id,
        ctx["steward"]["id"],
        "DATA_STEWARD",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    assign_steward(
        domain_id,
        ctx["third"]["id"],
        "DATA_STEWARD",
        effective_from="2026-09-01T00:00:00Z",
    )

    custodian = validate_success(
        api.create_steward_assignment(
            steward_assignment_payload(
                domain_id,
                ctx["steward"]["id"],
                domain_version(domain_id),
                steward_role="CUSTODIAN",
                effective_from="2026-08-15T00:00:00Z",
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )

    assert custodian["steward_role"] == "CUSTODIAN", (
        f"the custodian seat is a different role, got {custodian['steward_role']}"
    )
    assert custodian["status"] == "ACTIVE", (
        "the exclusion is scoped to one domain and one role, so a custodian "
        f"interval may run across both stewardship intervals, got {custodian['status']}"
    )


def test_two_structural_changes_occupy_the_calendar_with_the_minimum_separation(api):
    """PRD §3.8: "The freeze window is a closed interval around that instant
    whose extent depends on whether the change is structural: a structural
    change reserves 24 hours of lead before the instant and 48 hours of trail
    after it, while a non-structural change reserves no lead at all and 12 hours
    of trail."
    PRD §3.8: "Exactly 72 hours of separation is accepted; one second less is
    refused with `ERR_FREEZE_WINDOW_CONFLICT`."
    PRD §3.8: "On success the `status` becomes `SCHEDULED`, `scheduled_apply_at`
    and the two window boundaries are stored, the domain's
    `scheduled_change_count` is incremented by one and its `version` advances by
    one, and the notification fan-out runs: every consumer subscription in the
    impacted set — determined by exactly the same filter the impact assessment
    used — has its `pending_change_request_id` set to this request, its
    `notified_at` stamped from the clock, and its `acknowledged_at` and
    `acknowledged_revision` cleared to null so that a stale acknowledgement from
    an earlier notification cannot be mistaken for a fresh one."

    Design: Difficulty/resource_temporal_overlap/structural_change_calendar_capacity_third_within_thirty_days
    """
    ctx = setup_governed_domain()
    first, second, third = setup_approved_structural_requests(ctx, count=3)

    assert third["status"] == "APPROVED", (
        f"all three structural changes are approved before scheduling, got "
        f"{third['status']}"
    )

    scheduled_first = validate_success(
        api.schedule_change_request(
            first["id"], {"scheduled_apply_at": "2026-08-20T00:00:00Z"}, ctx["owner_headers"]
        )
    )
    assert_instant_equals(
        scheduled_first["freeze_window_end"], "2026-08-22T00:00:00Z", "freeze_window_end"
    )

    scheduled_second = validate_success(
        api.schedule_change_request(
            second["id"], {"scheduled_apply_at": "2026-08-26T00:00:00Z"}, ctx["owner_headers"]
        )
    )
    assert_instant_equals(
        scheduled_second["freeze_window_start"],
        "2026-08-25T00:00:00Z",
        "freeze_window_start",
    )
    assert_instant_equals(
        scheduled_second["freeze_window_end"],
        "2026-08-28T00:00:00Z",
        "freeze_window_end",
    )
    assert scheduled_second["status"] == "SCHEDULED", (
        "the second window opens exactly 72 hours after the first one closes, "
        f"got status {scheduled_second['status']}"
    )


def test_third_structural_change_within_thirty_days_exhausts_the_calendar(api):
    """PRD §3.8: "A second, aggregate constraint applies to structural changes
    only: the system counts the other `SCHEDULED` structural change requests of
    the domain whose `scheduled_apply_at` falls within thirty days of the
    proposed instant in either direction, and if two or more such neighbours
    already exist, the schedule is refused with `ERR_CHANGE_CALENDAR_CAPACITY` —
    at most two structural changes may be scheduled on a domain within any
    rolling thirty-day span."
    PRD §3.8: "Because the window endpoints are inclusive, a mandatory
    separation buffer of 72 hours is required between windows: for every *other*
    change request of the same domain currently in `SCHEDULED` status, the new
    window is acceptable only if its start falls at or after that other window's
    end plus 72 hours, or its end plus 72 hours falls at or before that other
    window's start."
    PRD §3.8: "The derived boolean `structural` is true for exactly the two
    non-additive types, `HIERARCHY_RESTRUCTURE` and `CLASSIFICATION_UPLIFT`, and
    false for `REFERENCE_VALUE_ADD`; it is never supplied by the client."

    Design: Difficulty/resource_temporal_overlap/structural_change_calendar_capacity_third_within_thirty_days
    """
    ctx = setup_governed_domain()
    first, second, third = setup_approved_structural_requests(ctx, count=3)

    assert third["structural"] is True, (
        f"a hierarchy restructure is structural, got {third['structural']!r}"
    )

    validate_success(
        api.schedule_change_request(
            first["id"], {"scheduled_apply_at": "2026-08-20T00:00:00Z"}, ctx["owner_headers"]
        )
    )
    validate_success(
        api.schedule_change_request(
            second["id"], {"scheduled_apply_at": "2026-08-26T00:00:00Z"}, ctx["owner_headers"]
        )
    )

    response = api.schedule_change_request(
        third["id"], {"scheduled_apply_at": "2026-09-01T00:00:00Z"}, ctx["owner_headers"]
    )
    validate_error(response, "ERR_CHANGE_CALENDAR_CAPACITY")


def test_refused_third_schedule_stays_approved_and_leaves_the_calendar_at_two(api):
    """PRD §3.8: "A second, aggregate constraint applies to structural changes
    only: the system counts the other `SCHEDULED` structural change requests of
    the domain whose `scheduled_apply_at` falls within thirty days of the
    proposed instant in either direction, and if two or more such neighbours
    already exist, the schedule is refused with `ERR_CHANGE_CALENDAR_CAPACITY` —
    at most two structural changes may be scheduled on a domain within any
    rolling thirty-day span."
    PRD §2.8: "`Domain.scheduled_change_count` is the exact integer count of the
    domain's change requests whose `status` is `SCHEDULED`."
    PRD §3.8: "Requests may be listed filtered by `domain_id`,
    `requester_steward_id`, `reviewer_steward_id`, `status` and `change_type`."

    Design: Difficulty/resource_temporal_overlap/structural_change_calendar_capacity_third_within_thirty_days
    """
    ctx = setup_governed_domain()
    first, second, third = setup_approved_structural_requests(ctx, count=3)

    validate_success(
        api.schedule_change_request(
            first["id"], {"scheduled_apply_at": "2026-08-20T00:00:00Z"}, ctx["owner_headers"]
        )
    )
    validate_success(
        api.schedule_change_request(
            second["id"], {"scheduled_apply_at": "2026-08-26T00:00:00Z"}, ctx["owner_headers"]
        )
    )
    validate_error(
        api.schedule_change_request(
            third["id"], {"scheduled_apply_at": "2026-09-01T00:00:00Z"}, ctx["owner_headers"]
        ),
        "ERR_CHANGE_CALENDAR_CAPACITY",
    )

    stored = validate_success(
        api.get_change_request(third["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert stored["status"] == "APPROVED", (
        "the refused schedule leaves the request approved and waiting, got "
        f"{stored['status']}"
    )
    assert stored["scheduled_apply_at"] is None, (
        f"no apply instant was stored, got {stored['scheduled_apply_at']!r}"
    )
    assert stored["freeze_window_start"] is None, (
        f"no window was reserved, got {stored['freeze_window_start']!r}"
    )

    domain = validate_success(api.get_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS))
    assert domain["scheduled_change_count"] == 2, (
        "the calendar still holds exactly the two accepted changes, got "
        f"{domain['scheduled_change_count']}"
    )

    _rows, meta = validate_paginated(
        api.list_change_requests(
            GOVERNANCE_ADMIN_HEADERS,
            params={"domain_id": ctx["domain"]["id"], "status": "SCHEDULED"},
        )
    )
    assert meta["total_count"] == 2, (
        f"only two requests are in the scheduled state, got {meta['total_count']}"
    )
