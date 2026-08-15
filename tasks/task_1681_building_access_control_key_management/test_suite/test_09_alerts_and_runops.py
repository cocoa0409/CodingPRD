"""Propped-door alerts, escalation, door-close auto-resolution, retention
archival, and the run-ops vendor-expiry sweep with the badge pool boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    access_check,
    api_client,
    assert_timestamp_equals,
    create_credential,
    create_person,
    get_alert_for_door,
    get_door,
    get_propped_incident_for_door,
    get_credential,
    get_success_data,
    issue_credential,
    set_clock,
    setup_access_ready_door,
    setup_building_with_chain,
    setup_open_propped_alert,
    setup_propped_door_open,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
OFFICER = TEST_USERS["security_officer_headers"]
DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Corner: alert lifecycle
# ---------------------------------------------------------------------------

def test_alert_double_acknowledge_rejected(api):
    """PRD §3.4: "A `SecurityOfficer` or `SecurityAdmin` acknowledges an `OPEN`
    alert (`OPEN` → `ACKNOWLEDGED`; from elsewhere, `ERR_ALERT_INVALID_STATE`)."

    Design: Corner/state_machines/alert_double_acknowledge_rejected
    """
    ctx = setup_open_propped_alert("Ack House", threshold=120,
                                   open_at="2026-08-01T08:00:00Z",
                                   detect_at="2026-08-01T08:03:00Z")
    alert = ctx["alert"]
    validate_success(api.acknowledge_propped_alert(alert["id"], OFFICER))

    resp = api.acknowledge_propped_alert(alert["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_ALERT_INVALID_STATE)
    assert validate_success(api.get_propped_alert(alert["id"], OFFICER))["status"] == "ACKNOWLEDGED"


def test_door_close_auto_resolves_open_alert(api):
    """PRD §3.4: "Resolution closes the alert with `resolved_reason` recorded:
    manual resolve accepts `OPEN`, `ACKNOWLEDGED`, or `ESCALATED` and stamps
    `MANUAL`; recording the door physically closed — which sets the door's
    `open_since` to null — auto-resolves any alert on that door in `OPEN` or
    `ACKNOWLEDGED` with `DOOR_CLOSED`."

    Design: Corner/state_machines/door_close_auto_resolves_open_alert
    """
    ctx = setup_open_propped_alert("Close House", threshold=120,
                                   open_at="2026-08-01T08:00:00Z",
                                   detect_at="2026-08-01T08:03:00Z")
    alert, door = ctx["alert"], ctx["door"]

    closed = validate_success(api.close_door(door["id"], OFFICER))
    assert closed["open_since"] is None

    alert_after = validate_success(api.get_propped_alert(alert["id"], OFFICER))
    assert alert_after["status"] == "RESOLVED"
    assert alert_after["resolved_reason"] == "DOOR_CLOSED"


def test_escalated_alert_survives_door_close(api):
    """PRD §3.4: "An `ESCALATED` alert is deliberately not auto-resolved by door
    close: once escalated, the linked incident owns the case."
    PRD §3.6: "Third, stale-alert escalation: any alert that has remained `OPEN`
    for longer than the building's `alert_escalation_minutes` — measuring now
    minus its `created_at` — escalates to `ESCALATED`, spawning an `Incident` of
    `type` `PROPPED_DOOR` in `OPEN` status linked by `door_id` and `alert_id`,
    with the alert's `incident_id` set."

    Design: Corner/state_machines/escalated_alert_survives_door_close
    """
    ctx = setup_open_propped_alert("Escalation House", threshold=120,
                                   open_at="2026-08-01T08:00:00Z",
                                   detect_at="2026-08-01T08:03:00Z",
                                   alert_escalation_minutes=30)
    alert = ctx["alert"]
    set_clock("2026-08-01T08:34:00Z")
    summary = validate_success(api.run_ops(ctx["building"]["id"], OFFICER))
    assert summary["alerts_escalated"] == 1

    alert_after = validate_success(api.get_propped_alert(alert["id"], OFFICER))
    assert alert_after["status"] == "ESCALATED"
    assert alert_after["incident_id"] is not None
    incident = validate_success(api.get_incident(alert_after["incident_id"], OFFICER))
    assert incident["type"] == "PROPPED_DOOR"
    assert incident["status"] == "OPEN"

    validate_success(api.close_door(ctx["door"]["id"], OFFICER))
    final = validate_success(api.get_propped_alert(alert["id"], OFFICER))
    assert final["status"] == "ESCALATED"


def test_retention_archive_strict_cutoff_and_visibility(api):
    """PRD §3.6: "Fourth, retention archival: the cutoff is now minus the
    building's `audit_retention_days`, and every `AccessEvent` whose `archived`
    flag is still false and whose `occurred_at` is strictly older than the
    cutoff is flipped to `archived` true, walking events in `occurred_at`
    ascending order; an event exactly at the cutoff is kept unarchived."
    PRD §3.6: "Archived rows disappear from the audit-trail list unless the
    caller passes `include_archived` as true, though any archived event remains
    readable directly by its id."

    Design: Corner/calculations/retention_archive_strict_cutoff_and_visibility
    """
    ctx = setup_access_ready_door("Retention House", clock="2026-08-01T07:59:00Z",
                                  audit_retention_days=30)
    door, cred = ctx["door"], ctx["credential"]
    access_check(door["id"], cred["id"], mode="RECORDED")  # event at 07:59
    set_clock("2026-08-01T08:00:00Z")
    validate_success(api.close_door(door["id"], OFFICER))
    access_check(door["id"], cred["id"], mode="RECORDED")  # event at 08:00

    set_clock("2026-08-31T08:00:00Z")
    summary = validate_success(api.run_ops(ctx["building"]["id"], OFFICER))
    # Cutoff is 2026-08-01T08:00:00Z; only the 07:59 event is strictly older.
    assert summary["events_archived"] == 1

    visible, meta = validate_paginated(
        api.list_access_events(OFFICER, params={"door_id": door["id"]})
    )
    assert len(visible) == 1
    assert meta["total_count"] == 1
    assert_timestamp_equals(visible[0]["occurred_at"], "2026-08-01T08:00:00Z")

    with_arch, meta2 = validate_paginated(
        api.list_access_events(OFFICER, params={"door_id": door["id"],
                                                "include_archived": "true"})
    )
    assert len(with_arch) == 2
    assert meta2["total_count"] == 2


# ---------------------------------------------------------------------------
# Difficulty: propped-duration exact-threshold boundary
# ---------------------------------------------------------------------------

def _setup_boundary_house():
    return setup_propped_door_open(
        "Boundary House", threshold=120, open_at="2026-08-01T08:00:00Z",
        alert_escalation_minutes=30, audit_retention_days=30,
    )


def test_propped_alert_not_created_at_exact_threshold(api):
    """PRD §3.6: "Second, the propped-door check: walking the building's doors
    in `door_code` ascending order, any door whose `open_since` is non-null and
    whose open duration in seconds is strictly greater than its
    `propped_threshold_seconds` gets a `ProppedDoorAlert` in `OPEN` with
    `opened_at` copied from `open_since` — but only when no alert for that door
    is already in `OPEN` or `ACKNOWLEDGED`; a duration exactly equal to the
    threshold raises nothing."

    Design: Difficulty/boundary_precision_check/propped_alert_exact_threshold_boundary
    """
    ctx = _setup_boundary_house()
    assert ctx["open_event_id"] is not None

    set_clock("2026-08-01T08:02:00Z")  # exactly 120 s open
    summary = validate_success(api.run_ops(ctx["building"]["id"], OFFICER))
    assert summary["propped_alerts_created"] == 0


def test_propped_alert_created_one_second_past_threshold(api):
    """PRD §3.6: "Second, the propped-door check: walking the building's doors
    in `door_code` ascending order, any door whose `open_since` is non-null and
    whose open duration in seconds is strictly greater than its
    `propped_threshold_seconds` gets a `ProppedDoorAlert` in `OPEN` with
    `opened_at` copied from `open_since` — but only when no alert for that door
    is already in `OPEN` or `ACKNOWLEDGED`; a duration exactly equal to the
    threshold raises nothing."

    Design: Difficulty/boundary_precision_check/propped_alert_exact_threshold_boundary
    """
    ctx = _setup_boundary_house()
    door = ctx["door"]

    set_clock("2026-08-01T08:02:00Z")  # exactly at threshold: nothing
    summary = validate_success(api.run_ops(ctx["building"]["id"], OFFICER))
    assert summary["propped_alerts_created"] == 0

    set_clock("2026-08-01T08:02:01Z")  # one second past: exactly one alert
    summary = validate_success(api.run_ops(ctx["building"]["id"], OFFICER))
    assert summary["propped_alerts_created"] == 1

    alert = get_alert_for_door(door["id"])
    assert alert["status"] == "OPEN"
    assert_timestamp_equals(alert["opened_at"], "2026-08-01T08:00:00Z")


# ---------------------------------------------------------------------------
# Difficulty: vendor badge pool capacity at the issue instant
# ---------------------------------------------------------------------------

def _setup_pool_house():
    ctx = setup_building_with_chain("Pool House", vendor_badge_pool_max=2)
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    v1 = create_person(building["id"], "Vendor One", "VENDOR", employer_name="ACME")
    v2 = create_person(building["id"], "Vendor Two", "VENDOR", employer_name="ACME")
    v3 = create_person(building["id"], "Vendor Three", "VENDOR", employer_name="ACME")
    vb1 = create_credential(building["id"], change["id"], "VB-1", "FOB")
    vb2 = create_credential(building["id"], change["id"], "VB-2", "FOB")
    vb3 = create_credential(building["id"], change["id"], "VB-3", "FOB")
    issue_credential(vb1["id"], v1["id"], expires_at="2026-08-01T12:00:00Z")
    issue_credential(vb2["id"], v2["id"], expires_at="2026-08-01T12:00:00Z")
    ctx.update({"v1": v1, "v2": v2, "v3": v3, "vb1": vb1, "vb2": vb2, "vb3": vb3})
    return ctx


def test_vendor_badge_pool_exhausted_at_capacity(api):
    """PRD §3.2: "the building-wide count of live vendor credentials must be
    strictly below the building's `vendor_badge_pool_max`, else
    `ERR_VENDOR_BADGE_POOL_EXHAUSTED`;"

    Design: Difficulty/resource_temporal_overlap/vendor_badge_pool_capacity_at_instant
    """
    ctx = _setup_pool_house()
    resp = api.issue_credential(
        ctx["vb3"]["id"],
        {"person_id": ctx["v3"]["id"], "expires_at": "2026-08-01T12:00:00Z"},
        DESK,
    )
    validate_error(resp, ApiErrorId.ERR_VENDOR_BADGE_POOL_EXHAUSTED)
    assert get_credential(ctx["vb3"]["id"])["status"] == "IN_STOCK"


def test_vendor_badge_pool_freed_after_expiry_sweep(api):
    """PRD §3.6: "First, the vendor expiry sweep: walking the building's
    credentials in `created_at` ascending, `serial_no` ascending order, every
    credential in `ISSUED` with a non-null `expires_at` at or before now is
    deactivated with `deactivated_reason` `EXPIRED` — the boundary is consistent
    with the access rule that a credential is valid only while now is strictly
    before `expires_at`."
    PRD §3.2: "the building-wide count of live vendor credentials must be
    strictly below the building's `vendor_badge_pool_max`, else
    `ERR_VENDOR_BADGE_POOL_EXHAUSTED`;"

    Design: Difficulty/resource_temporal_overlap/vendor_badge_pool_capacity_at_instant
    """
    ctx = _setup_pool_house()
    resp = api.issue_credential(
        ctx["vb3"]["id"],
        {"person_id": ctx["v3"]["id"], "expires_at": "2026-08-01T12:00:00Z"},
        DESK,
    )
    validate_error(resp, ApiErrorId.ERR_VENDOR_BADGE_POOL_EXHAUSTED)

    set_clock("2026-08-01T12:30:00Z")
    summary = validate_success(api.run_ops(ctx["building"]["id"], OFFICER))
    assert summary["vendor_credentials_expired"] == 2

    vb1_after = get_credential(ctx["vb1"]["id"])
    assert vb1_after["status"] == "DEACTIVATED"
    assert vb1_after["deactivated_reason"] == "EXPIRED"

    issued = validate_success(api.issue_credential(
        ctx["vb3"]["id"],
        {"person_id": ctx["v3"]["id"], "expires_at": "2026-08-01T15:00:00Z"},
        DESK,
    ))
    assert issued["status"] == "ISSUED"
