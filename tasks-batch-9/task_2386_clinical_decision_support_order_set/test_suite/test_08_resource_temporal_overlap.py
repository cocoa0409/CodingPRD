"""Two interval resources with deliberately opposite endpoint semantics.

An alert's monitoring timeline is half-open, so a window beginning exactly where
its predecessor ended is merely adjacent. A downtime schedule is closed, so the
identical arithmetic conflicts — and widening the scope does not help.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Half-open burden windows on one alert's timeline
# ---------------------------------------------------------------------------


RESTRAINT_REQUEST = {
    "title": "Restraint documentation reminder",
    "request_type": "ALERT",
    "clinical_domain": "GERIATRICS",
    "urgency": "ROUTINE",
    "evidence_grade": "C",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("CMS conditions of participation 2025", True),
        factories.build_citation("Unit audit 2025", False),
    ],
}

RESTRAINT_ALERT = {
    "name": "Restraint order documentation",
    "severity_tier": "TIER_3_PASSIVE",
    "override_reason_required": False,
    "firing_criteria": {
        "trigger_event": "RESTRAINT_ORDER_PLACED",
        "expression": "restraint_active AND no_reassessment_note_in_24h",
    },
}


def _alert_with_one_closed_september_window(committee):
    """An ACTIVE alert with a single CLOSED window spanning 09-01 to 09-08."""
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee, request_overrides=RESTRAINT_REQUEST, alert_overrides=RESTRAINT_ALERT
    )
    alert_id = scenario["alert"]["id"]
    first = fixtures.open_window(
        committee, alert_id, "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z"
    )
    scenario["first_window"] = fixtures.close_window(
        committee, alert_id, first["id"], closure_reason="MANUAL_CLOSE"
    )
    assert scenario["first_window"]["state"] == "CLOSED"
    return scenario


def _attempt_window(committee, alert_id, window_start, window_end):
    """Try to open a window at the alert's current version."""
    version = fixtures.read_alert(committee, alert_id)["version"]
    return api_client.create_burden_window(
        alert_id,
        factories.build_burden_window_payload(window_start, window_end, version),
        committee["chair_headers"],
    )


def test_a_window_starting_where_a_closed_window_ends_is_merely_adjacent(committee):
    """Adjacency is accepted at both ends of the chain, not just the first.

    "The interval is half-open: `window_start` is inclusive, `window_end` is
    exclusive, and a firing whose `fired_at` equals `window_end` belongs to the
    *next* window." "because overlap is computed on half-open intervals, a new
    window whose `window_start` equals an existing window's `window_end` is
    merely adjacent and is allowed".

    Design: Difficulty/resource_temporal_overlap/overlap_burden_window_half_open_allows_touching_but_rejects_intersection
    """
    scenario = _alert_with_one_closed_september_window(committee)
    alert_id = scenario["alert"]["id"]

    second = validate_success(
        _attempt_window(committee, alert_id, "2026-09-08T00:00:00Z", "2026-09-15T00:00:00Z"),
        201,
    )
    assert second["state"] == "OPEN"
    assert second["window_start"] == "2026-09-08T00:00:00Z"
    assert second["reopen_count"] == 0

    closed_second = fixtures.close_window(
        committee, alert_id, second["id"], closure_reason="MANUAL_CLOSE"
    )
    assert closed_second["state"] == "CLOSED"

    # the same arithmetic one interval further along, so the rule is symmetric
    third = validate_success(
        _attempt_window(committee, alert_id, "2026-09-15T00:00:00Z", "2026-09-22T00:00:00Z"),
        201,
    )
    assert third["state"] == "OPEN"
    assert third["window_start"] == "2026-09-15T00:00:00Z"


def test_a_window_straddling_two_closed_windows_is_an_overlap_not_a_second_open(committee):
    """The intersecting attempt is refused by the overlap rule with none open.

    "A new window may not overlap any window of the same alert in state `CLOSED`
    or `FINALIZED`; ... while a genuine intersection is refused with
    `ERR_BURDEN_WINDOW_OVERLAP`." "reopening a window while a different window of
    the same alert is open yields `ERR_ANOTHER_WINDOW_OPEN` (409)".

    Design: Difficulty/resource_temporal_overlap/overlap_burden_window_half_open_allows_touching_but_rejects_intersection
    """
    scenario = _alert_with_one_closed_september_window(committee)
    alert_id = scenario["alert"]["id"]

    second = validate_success(
        _attempt_window(committee, alert_id, "2026-09-08T00:00:00Z", "2026-09-15T00:00:00Z"),
        201,
    )
    fixtures.close_window(committee, alert_id, second["id"], closure_reason="MANUAL_CLOSE")

    # no window of this alert is OPEN at this instant, so only overlap can fire
    straddling = _attempt_window(
        committee, alert_id, "2026-09-05T00:00:00Z", "2026-09-12T00:00:00Z"
    )
    validate_error(straddling, ApiErrorId.ERR_BURDEN_WINDOW_OVERLAP, 409)

    fourth = validate_success(
        _attempt_window(committee, alert_id, "2026-09-15T00:00:00Z", "2026-09-22T00:00:00Z"),
        201,
    )
    assert fourth["state"] == "OPEN"

    windows = fixtures.read_windows(committee, alert_id)
    # the rejected attempt persisted nothing
    assert len(windows) == 3
    assert sorted(w["window_start"] for w in windows) == [
        "2026-09-01T00:00:00Z",
        "2026-09-08T00:00:00Z",
        "2026-09-15T00:00:00Z",
    ]


# ---------------------------------------------------------------------------
# Closed, scope-aware downtime intervals
# ---------------------------------------------------------------------------


def _scheduled_order_set_downtime():
    """One SCHEDULED read-only freeze over order sets from midnight to 06:00."""
    fixtures.reset_clock()
    event = fixtures.schedule_downtime(
        "2026-08-10T00:00:00Z",
        "2026-08-10T06:00:00Z",
        "ORDER_SETS_ONLY",
        "READ_ONLY",
        planned=True,
        reason="Order set catalogue reindex",
    )
    # SCHEDULED events already participate in the overlap check
    assert event["state"] == "SCHEDULED"
    return event


def test_a_touching_downtime_window_conflicts_unless_the_scope_is_disjoint():
    """06:00 meeting a 06:00 end conflicts, then the same interval is allowed.

    "A new downtime event may not overlap any existing event whose `state` is
    `SCHEDULED` or `ACTIVE` and whose scope intersects the new one ... unlike
    burden windows, downtime intervals are treated as **closed**, so events whose
    endpoints merely touch do conflict, and the rejection is
    `ERR_DOWNTIME_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/overlap_downtime_closed_interval_rejects_touching_endpoint_and_scope_widening
    """
    first = _scheduled_order_set_downtime()

    touching = api_client.create_downtime_event(
        factories.build_downtime_event_payload(
            "2026-08-10T06:00:00Z",
            "2026-08-10T12:00:00Z",
            "ORDER_SETS_ONLY",
            "READ_ONLY",
            planned=True,
            reason="Second maintenance leg",
        ),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(touching, ApiErrorId.ERR_DOWNTIME_WINDOW_OVERLAP, 409)

    disjoint = validate_success(
        api_client.create_downtime_event(
            factories.build_downtime_event_payload(
                "2026-08-10T06:00:00Z",
                "2026-08-10T12:00:00Z",
                "ALERTS_ONLY",
                "READ_ONLY",
                planned=True,
                reason="Alert engine patch",
            ),
            fixtures.ADMIN_HEADERS,
        ),
        201,
    )
    assert disjoint["state"] == "SCHEDULED"
    assert disjoint["scope"] == "ALERTS_ONLY"
    assert disjoint["blocked_mutation_count"] == 0

    # the refusal touched nothing on the incumbent
    incumbent = fixtures.read_downtime(first["id"])
    assert incumbent["state"] == "SCHEDULED"
    assert incumbent["blocked_mutation_count"] == 0


def test_widening_the_scope_cannot_slip_past_a_touching_narrower_window():
    """SYSTEM_WIDE conflicts on contact, and one second of clearance is enough.

    "A new downtime event may not overlap any existing event whose `state` is
    `SCHEDULED` or `ACTIVE` and whose scope intersects the new one, where
    `SYSTEM_WIDE` intersects every other scope". "The event opens in `state`
    `SCHEDULED` with `blocked_mutation_count` 0, `activated_at` and `closed_at`
    null".

    Design: Difficulty/resource_temporal_overlap/overlap_downtime_closed_interval_rejects_touching_endpoint_and_scope_widening
    """
    _scheduled_order_set_downtime()
    alerts_event = validate_success(
        api_client.create_downtime_event(
            factories.build_downtime_event_payload(
                "2026-08-10T06:00:00Z",
                "2026-08-10T12:00:00Z",
                "ALERTS_ONLY",
                "READ_ONLY",
                planned=True,
                reason="Alert engine patch",
            ),
            fixtures.ADMIN_HEADERS,
        ),
        201,
    )

    widened = api_client.create_downtime_event(
        factories.build_downtime_event_payload(
            "2026-08-10T12:00:00Z",
            "2026-08-10T18:00:00Z",
            "SYSTEM_WIDE",
            "FULL_UNAVAILABLE",
            planned=True,
            reason="Datacentre failover",
        ),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(widened, ApiErrorId.ERR_DOWNTIME_WINDOW_OVERLAP, 409)

    # one second of clearance pins the comparison to inclusive endpoints
    cleared = validate_success(
        api_client.create_downtime_event(
            factories.build_downtime_event_payload(
                "2026-08-10T12:00:01Z",
                "2026-08-10T18:00:00Z",
                "SYSTEM_WIDE",
                "FULL_UNAVAILABLE",
                planned=True,
                reason="Datacentre failover",
            ),
            fixtures.ADMIN_HEADERS,
        ),
        201,
    )
    assert cleared["state"] == "SCHEDULED"
    assert cleared["scope"] == "SYSTEM_WIDE"
    assert cleared["window_start"] == "2026-08-10T12:00:01Z"

    # neither rejection disturbed the narrower incumbent
    incumbent = fixtures.read_downtime(alerts_event["id"])
    assert incumbent["state"] == "SCHEDULED"
    assert incumbent["blocked_mutation_count"] == 0
