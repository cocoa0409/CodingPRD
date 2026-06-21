"""Interval-overlap geometry and optimistic-concurrency escalation (depth:
resource_temporal_overlap; breadth: cross_cutting_complexity_layers).

Difficulty instances translate to >=2 tests; corner instances to >=1.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    set_clock,
    create_service,
    create_responder,
    create_schedule,
    create_shift,
    create_policy,
    create_tier,
    create_window,
    setup_multi_tier_incident,
    TEST_USERS,
    WIDE_SHIFT_START,
    WIDE_SHIFT_END,
)
from test_helpers.factories import (
    create_schedule_shift_payload,
    create_maintenance_window_payload,
    escalate_payload,
)

COMMANDER = TEST_USERS["incident_commander_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Difficulty/resource_temporal_overlap/
#   schedule_shift_half_open_overlap_rejected_backtoback_ok
# ===========================================================================
def test_overlapping_shift_rejected():
    """PRD §3.6: "A new shift on a schedule is rejected when it overlaps any
    existing shift on the same `schedule_id`: an overlap exists exactly when the
    new shift's `starts_at` is strictly before the existing shift's `ends_at` and
    the existing shift's `starts_at` is strictly before the new shift's `ends_at`.
    ... A rejected overlap returns `ERR_SHIFT_OVERLAP` (HTTP 409)."

    Adding a shift [11:00,13:00) over an existing [10:00,12:00) overlaps (11:00 <
    12:00) and is rejected with ERR_SHIFT_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/schedule_shift_half_open_overlap_rejected_backtoback_ok
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    resp = create_responder()
    sch = create_schedule(svc["id"])
    create_shift(sch["id"], resp["id"], "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")

    res = api_client.create_schedule_shift(
        create_schedule_shift_payload(sch["id"], resp["id"], "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z"),
        ADMIN,
    )
    validate_error(res, "ERR_SHIFT_OVERLAP")


def test_back_to_back_shift_allowed():
    """PRD §3.6: "Because the endpoints are half-open and there is no buffer, two
    back-to-back shifts where one's `starts_at` exactly equals the other's
    `ends_at` do *not* overlap and are allowed."

    A shift [12:00,14:00) starting exactly when [10:00,12:00) ends is accepted —
    half-open zero-buffer adjacency.

    Design: Difficulty/resource_temporal_overlap/schedule_shift_half_open_overlap_rejected_backtoback_ok
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    resp = create_responder()
    sch = create_schedule(svc["id"])
    create_shift(sch["id"], resp["id"], "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")

    res = api_client.create_schedule_shift(
        create_schedule_shift_payload(sch["id"], resp["id"], "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z"),
        ADMIN,
    )
    created = validate_success(res, 201)
    assert created["starts_at"].startswith("2026-06-01T12:00:00")


# ===========================================================================
# Difficulty/resource_temporal_overlap/
#   maintenance_window_closed_interval_buffer_rejected
# ===========================================================================
def test_window_within_buffer_rejected():
    """PRD §3.6: "even when the two do not overlap, it is also rejected when the
    gap between them is less than a minimum spacing of 30 minutes. ... A rejected
    spacing violation returns `ERR_WINDOW_OVERLAP` (HTTP 409)."

    A window [11:10,12:00] only 10 minutes after [10:00,11:00] ends violates the
    30-minute buffer even though the closed intervals do not overlap.

    Design: Difficulty/resource_temporal_overlap/maintenance_window_closed_interval_buffer_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    create_window(svc["id"], "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")

    res = api_client.create_maintenance_window(
        create_maintenance_window_payload(svc["id"], "2026-06-01T11:10:00Z", "2026-06-01T12:00:00Z"),
        ADMIN,
    )
    validate_error(res, "ERR_WINDOW_OVERLAP")


def test_window_beyond_buffer_allowed():
    """PRD §3.6: "windows use closed endpoints and require at least a 30-minute
    separation, whereas shifts use half-open endpoints and permit back-to-back
    placement."

    A window [11:40,12:00] a full 40 minutes after [10:00,11:00] ends clears the
    30-minute buffer and is accepted — the complement of the rejection branch and
    the distinguishing geometry from shifts (which allow zero gap).

    Design: Difficulty/resource_temporal_overlap/maintenance_window_closed_interval_buffer_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    svc = create_service(tier="TIER_2", error_budget_minutes=1000)
    create_window(svc["id"], "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")

    res = api_client.create_maintenance_window(
        create_maintenance_window_payload(svc["id"], "2026-06-01T11:40:00Z", "2026-06-01T12:00:00Z"),
        ADMIN,
    )
    created = validate_success(res, 201)
    assert created["status"] == "SCHEDULED"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_correct_version_escalate_succeeds_and_bumps
# ===========================================================================
def test_escalate_with_correct_version_advances_tier_and_bumps_version():
    """PRD §3.4: "When a manual escalation succeeds, `current_tier_level` advances
    to the next tier ... and the incident's `version` is incremented by 1."
    PRD §2.6: "A manual escalation request must carry `expected_incident_version`,
    a non-optional field whose value is the client's last observed `version` of
    the target incident."

    A manual escalate carrying the current version succeeds, advances
    current_tier_level to 2, and bumps version by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_escalate_succeeds_and_bumps
    """
    env, incident = setup_multi_tier_incident(num_tiers=2, repeat_rounds=0)
    v0 = incident["version"]

    res = api_client.escalate_incident(incident["id"], escalate_payload(v0), COMMANDER)
    after = validate_success(res, 200)
    assert after["current_tier_level"] == 2, (
        f"correct-version escalate should advance to tier 2, got {after['current_tier_level']}"
    )
    assert after["version"] == v0 + 1, (
        f"escalate should bump version by 1 (from {v0}), got {after['version']}"
    )


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_version_escalate_rejected_412
# ===========================================================================
def test_escalate_with_stale_version_rejected_412():
    """PRD §2.6: "If that value does not equal the incident's current `version` at
    the time the request is processed — for instance because the system already
    advanced the ladder, created the next tier's paging attempts, and bumped the
    version since the client last read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no tier is advanced and no page is sent."

    After a first escalate bumps the version, a second escalate carrying the
    pre-first-escalate version is rejected with ERR_STALE_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_escalate_rejected_412
    """
    env, incident = setup_multi_tier_incident(num_tiers=3, repeat_rounds=0)
    v0 = incident["version"]

    first = validate_success(
        api_client.escalate_incident(incident["id"], escalate_payload(v0), COMMANDER), 200
    )
    v1 = first["version"]
    assert v1 == v0 + 1

    # Re-send the now-stale pre-escalate version (== v1 - 1 == v0).
    res = api_client.escalate_incident(incident["id"], escalate_payload(v1 - 1), COMMANDER)
    validate_error(res, "ERR_STALE_VERSION")
