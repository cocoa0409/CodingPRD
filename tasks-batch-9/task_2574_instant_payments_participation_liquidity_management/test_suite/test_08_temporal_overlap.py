"""Scarce windows, and the exact instants at which they stop conflicting.

Policy windows are half-open, so a successor starting on the incumbent's closing instant
is adjacent rather than overlapping, and one minute earlier is a genuine collision keyed on
the participant-and-segment pair. Because every accepted publication bumps the owning
participant's record version, the same chain also shows that a refused overlap is not a
version problem — a deliberately stale version is answered on its own terms.

Outage intervals have the opposite geometry: closed on both ends, and a resolved event goes
on reserving a fifteen-minute stabilization buffer that outlives its own status.
"""

from test_helpers import (
    assert_instant,
    assert_outage_event_shape,
    assert_segment_policy_shape,
    declare_outage,
    ERR_OUTAGE_WINDOW_CONFLICT,
    ERR_POLICY_WINDOW_OVERLAP,
    ERR_STALE_PARTICIPANT_VERSION,
    list_segment_policies_with_meta,
    live_alpha,
    make_participant_admin_headers,
    NETWORK_OPERATOR,
    outage_event_payload,
    OUTAGE_STABILIZATION_BUFFER_MINUTES,
    participant_version,
    publish_segment_policy,
    read_participant,
    resolve_outage,
    segment_policy_payload,
    set_clock,
    validate_error,
    validate_paginated,
)

SUCCESSOR_CONTROLS = {
    "per_transaction_limit_cents": 400_000_000,
    "daily_aggregate_limit_cents": 700_000_000,
    "rolling_window_count_limit": 7,
    "rolling_window_amount_limit_cents": 600_000_000,
}


def _two_adjacent_corporate_windows(api):
    """Alpha with a closed CORPORATE window and an open-ended adjacent successor."""
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = live_alpha(api)
    first = publish_segment_policy(
        api,
        alpha.id,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    second = publish_segment_policy(
        api,
        alpha.id,
        per_transaction_limit_cents=300_000_000,
        daily_aggregate_limit_cents=600_000_000,
        rolling_window_count_limit=6,
        rolling_window_amount_limit_cents=500_000_000,
        effective_from="2026-09-01T00:00:00Z",
    )
    return alpha, first, second


def test_window_starting_on_the_incumbents_closing_instant_is_adjacent(api):
    """Adjacency is admitted and supersedes nothing; a minute earlier collides.

    PRD 3.2: "Because they are half-open, a new policy whose `effective_from` falls
    exactly on an incumbent's `effective_to` is adjacent and accepted, while one starting a
    minute earlier overlaps and is rejected with `ERR_POLICY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/segment_policy_windows_adjacent_admitted_overlap_rejected
    """
    alpha, first, second = _two_adjacent_corporate_windows(api)
    assert_segment_policy_shape(second)
    assert_instant(second["effective_from"], "2026-09-01T00:00:00Z", "effective_from")
    assert second["effective_to"] is None
    assert_instant(first["effective_to"], "2026-09-01T00:00:00Z", "effective_to")
    assert first["superseded_at"] is None

    current_version = participant_version(api, alpha.id)
    response = api.create_segment_policy(
        segment_policy_payload(
            alpha.id,
            current_version,
            effective_from="2026-08-31T23:59:00Z",
            **SUCCESSOR_CONTROLS,
        ),
        make_participant_admin_headers(alpha.id),
    )
    validate_error(response, ERR_POLICY_WINDOW_OVERLAP)

    policies, meta = list_segment_policies_with_meta(api, alpha.id)
    assert meta["total_count"] == 2
    assert len(policies) == 2
    assert participant_version(api, alpha.id) == current_version


def test_overlap_is_keyed_on_the_participant_and_segment_pair(api):
    """The refused window is publishable for a different segment, unchanged otherwise.

    PRD 3.2: "Windows for the same participant-and-segment pair may not overlap."

    Design: Difficulty/resource_temporal_overlap/segment_policy_windows_adjacent_admitted_overlap_rejected
    """
    alpha, _first, _second = _two_adjacent_corporate_windows(api)
    current_version = participant_version(api, alpha.id)
    validate_error(
        api.create_segment_policy(
            segment_policy_payload(
                alpha.id, current_version, effective_from="2026-08-31T23:59:00Z", **SUCCESSOR_CONTROLS
            ),
            make_participant_admin_headers(alpha.id),
        ),
        ERR_POLICY_WINDOW_OVERLAP,
    )

    consumer = publish_segment_policy(
        api,
        alpha.id,
        segment="CONSUMER",
        effective_from="2026-08-31T23:59:00Z",
        **SUCCESSOR_CONTROLS,
    )
    assert consumer["segment"] == "CONSUMER"
    assert_instant(consumer["effective_from"], "2026-08-31T23:59:00Z", "effective_from")
    policies, meta = list_segment_policies_with_meta(api, alpha.id)
    assert meta["total_count"] == 3
    assert participant_version(api, alpha.id) == current_version + 1


def test_stale_version_is_answered_before_the_overlap(api):
    """The same colliding window with an outdated view is told its view is stale.

    PRD 2.11: "**Optimistic concurrency.** `expected_position_account_version` on
    origination, yielding `ERR_STALE_POSITION_VERSION`; `expected_participant_version` on
    segment-policy publication, yielding `ERR_STALE_PARTICIPANT_VERSION`. These are checked
    before any state, compliance, limit or liquidity rule, so a caller with a stale view is
    told its view is stale rather than being told about a downstream condition it cannot yet
    see."

    Design: Difficulty/resource_temporal_overlap/segment_policy_windows_adjacent_admitted_overlap_rejected
    """
    alpha, _first, _second = _two_adjacent_corporate_windows(api)
    current_version = participant_version(api, alpha.id)

    response = api.create_segment_policy(
        segment_policy_payload(
            alpha.id,
            current_version - 2,
            effective_from="2026-08-31T23:59:00Z",
            **SUCCESSOR_CONTROLS,
        ),
        make_participant_admin_headers(alpha.id),
    )
    validate_error(response, ERR_STALE_PARTICIPANT_VERSION)

    policies, meta = list_segment_policies_with_meta(api, alpha.id)
    assert meta["total_count"] == 2
    assert participant_version(api, alpha.id) == current_version


def _resolved_outage_world(api):
    """Alpha's two-hour participant outage, resolved at 12:00 with the buffer running."""
    set_clock(api, "2026-08-03T09:00:00Z")
    alpha = live_alpha(api)
    set_clock(api, "2026-08-03T10:00:00Z")
    event = declare_outage(api, "2026-08-03T10:00:00Z", participant_id=alpha.id)
    assert event["status"] == "DECLARED"
    assert read_participant(api, alpha.id)["operational_posture"] == "OFFLINE"

    set_clock(api, "2026-08-03T12:00:00Z")
    resolved = resolve_outage(api, event["id"], "2026-08-03T12:00:00Z")
    assert_outage_event_shape(resolved)
    assert resolved["status"] == "RESOLVED"
    assert_instant(resolved["ended_at"], "2026-08-03T12:00:00Z", "ended_at")
    assert read_participant(api, alpha.id)["operational_posture"] == "NORMAL"
    return alpha, resolved


def _outage_count(api, participant_id):
    """How many outage events the rail holds for this participant."""
    _events, meta = validate_paginated(
        api.list_participant_outage_events(participant_id, NETWORK_OPERATOR)
    )
    return meta["total_count"]


def test_resolved_outage_keeps_reserving_its_stabilization_buffer(api):
    """A redeclaration inside the buffer is refused although nothing is DECLARED.

    PRD 3.9: "A `RESOLVED` event additionally reserves a stabilization buffer of 15
    minutes after its `ended_at`, and that reservation is half-open: a new event of
    conflicting scope starting at exactly 15 minutes after the earlier event's `ended_at` is
    admitted, while one starting 14 minutes after is refused."

    Design: Difficulty/resource_temporal_overlap/outage_stabilization_buffer_blocks_early_redeclaration
    """
    alpha, resolved = _resolved_outage_world(api)
    assert OUTAGE_STABILIZATION_BUFFER_MINUTES == 15

    set_clock(api, "2026-08-03T12:10:00Z")
    response = api.create_outage_event(
        outage_event_payload(
            "2026-08-03T12:10:00Z",
            severity="DEGRADED",
            fallback_rail="FALLBACK_WIRE",
            participant_id=alpha.id,
        ),
        NETWORK_OPERATOR,
    )
    validate_error(response, ERR_OUTAGE_WINDOW_CONFLICT)

    assert _outage_count(api, alpha.id) == 1
    assert read_participant(api, alpha.id)["operational_posture"] == "NORMAL"


def test_buffer_edge_admits_at_fifteen_minutes_and_refuses_at_fourteen(api):
    """The buffer's closing instant is admitting; one minute earlier still collides.

    PRD 3.9: "Outage intervals do not stack. They are **closed** on both ends, so two
    intervals that merely touch at an endpoint already conflict, and a `NETWORK_WIDE` event
    conflicts with every `PARTICIPANT`-scoped event just as a `PARTICIPANT`-scoped event
    conflicts with a network-wide one."

    Design: Difficulty/resource_temporal_overlap/outage_stabilization_buffer_blocks_early_redeclaration
    """
    alpha, resolved = _resolved_outage_world(api)

    set_clock(api, "2026-08-03T12:14:00Z")
    validate_error(
        api.create_outage_event(
            outage_event_payload(
                "2026-08-03T12:14:00Z",
                severity="DEGRADED",
                fallback_rail="FALLBACK_WIRE",
                participant_id=alpha.id,
            ),
            NETWORK_OPERATOR,
        ),
        ERR_OUTAGE_WINDOW_CONFLICT,
    )
    assert _outage_count(api, alpha.id) == 1

    set_clock(api, "2026-08-03T12:15:00Z")
    admitted = declare_outage(
        api,
        "2026-08-03T12:15:00Z",
        severity="DEGRADED",
        fallback_rail="FALLBACK_WIRE",
        participant_id=alpha.id,
    )
    assert admitted["status"] == "DECLARED"
    assert_instant(admitted["started_at"], "2026-08-03T12:15:00Z", "started_at")
    assert _outage_count(api, alpha.id) == 2
    assert read_participant(api, alpha.id)["operational_posture"] == "OFFLINE"


def test_network_wide_declaration_conflicts_with_a_participant_buffer(api):
    """Scope crosses: the reservation is not confined to same-scope declarations.

    PRD 3.9: "Any conflict is reported as `ERR_OUTAGE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/outage_stabilization_buffer_blocks_early_redeclaration
    """
    alpha, resolved = _resolved_outage_world(api)

    set_clock(api, "2026-08-03T12:10:00Z")
    response = api.create_outage_event(
        outage_event_payload("2026-08-03T12:10:00Z", scope="NETWORK_WIDE", severity="DEGRADED"),
        NETWORK_OPERATOR,
    )
    validate_error(response, ERR_OUTAGE_WINDOW_CONFLICT)
    assert _outage_count(api, alpha.id) == 1
