"""Fixed validation precedence (§2.5): state legality (6) pre-empts certification
currency (8); sibling-entity state (7) pre-empts temporal overlap (9)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_active_incident, create_incident, create_team_and_member,
    create_assigned_task, create_certification, create_acknowledged_callout,
    create_task, create_resource, create_resource_assignment,
    current_resource_version,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]


# --- Difficulty: priority_pair_validation_conflict / deploy_state_beats_safety ---

def _acknowledged_callout_with_expired_cert(api, ics):
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc = create_active_incident(api, name="Pair One", ics_incident_number=ics)
    team, member = create_team_and_member(api, member_overrides={"full_name": "Hal Med"})
    create_certification(api, member["id"], cert_type="WFR",
                         issued_date="2024-01-01T00:00:00Z",
                         expires_date="2026-04-01T00:00:00Z")  # EXPIRED at clock
    task = create_assigned_task(api, inc["id"], segment_area_sqkm=5.0,
                                planned_searcher_hours=4, required_cert_types=["WFR"])
    co = create_acknowledged_callout(api, task["id"], member["id"])
    return co


def test_deploy_from_acknowledged_reports_invalid_state_not_cert(api):
    """PRD §2.5: "6. State legality. The target resource must be in a state from
    which the requested transition is defined, else `ERR_INVALID_STATE` (409)."
    PRD §3.4: "A `Coordinator` or `IncidentCommander` deploys a standby callout,
    moving it from `STANDBY` to `DEPLOYED`".

    Design: Difficulty/priority_pair_validation_conflict/deploy_state_beats_safety
    """
    co = _acknowledged_callout_with_expired_cert(api, "OR-2026-0009")
    resp = api.deploy_callout(co["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_deploy_state_check_precedes_certification_check(api):
    """PRD §2.5: "When more than one rule could reject a request, the checks are
    applied in a fixed order so that the returned `error_id` is deterministic."
    PRD §2.5: "8. Certification currency (deployment only), else
    `ERR_CERT_REQUIREMENT_NOT_MET` (409)."

    Design: Difficulty/priority_pair_validation_conflict/deploy_state_beats_safety
    """
    co = _acknowledged_callout_with_expired_cert(api, "OR-2026-0009b")
    resp = api.deploy_callout(co["id"], COORD)
    body = resp.json()["data"]
    assert body["error_id"] == "ERR_INVALID_STATE", (
        f"State legality (priority 6) must pre-empt cert currency (priority 8); got {body}")
    # The rejected deploy leaves the callout in its prior ACKNOWLEDGED state.
    assert validate_success(api.get_callout(co["id"], COORD))["status"] == "ACKNOWLEDGED"


# --- Difficulty: priority_pair_validation_conflict / assignment_referential_beats_temporal ---

def _oos_resource_with_reserved_window(api, ics):
    inc = create_incident(api, name="Pair Two", incident_type="AIR_SEARCH",
                          ics_incident_number=ics)
    task = create_task(api, inc["id"], task_type="AIR_RECON", segment_area_sqkm=20.0,
                       planned_searcher_hours=4, planned_start="2026-05-02T08:00:00Z",
                       planned_end="2026-05-02T18:00:00Z")
    resource = create_resource(api, name="Helo N456", resource_type="HELICOPTER")
    create_resource_assignment(api, resource["id"], task["id"], resource["version"],
                               window_start="2026-05-02T09:00:00Z",
                               window_end="2026-05-02T11:00:00Z")
    validate_success(api.set_resource_status(resource["id"], {"out_of_service": True}, COORD))
    v = current_resource_version(api, resource["id"])
    return task, resource, v


def test_assignment_on_oos_overlapping_resource_reports_unavailable(api):
    """PRD §2.5: "7. Sibling-entity state. Any required state of a referenced sibling
    entity must hold, else the specific sibling error (`ERR_TASK_NOT_READY`,
    `ERR_RESOURCE_UNAVAILABLE`, `ERR_INCIDENT_NOT_ACTIVE`,
    `ERR_INCIDENT_NOT_DEMOBILIZING`, `ERR_INCIDENT_NOT_CLOSED`, or
    `ERR_TEAM_INACTIVE`), all at 409."
    PRD §3.5: "A create is rejected with `ERR_RESOURCE_WINDOW_CONFLICT` when the
    proposed window overlaps any existing `RESERVED` or `ACTIVE` assignment on the
    same resource, and with `ERR_RESOURCE_UNAVAILABLE` when the resource is
    `OUT_OF_SERVICE`."

    Design: Difficulty/priority_pair_validation_conflict/assignment_referential_beats_temporal
    """
    task, resource, v = _oos_resource_with_reserved_window(api, "OR-2026-0010")
    resp = api.create_resource_assignment(
        {"resource_id": resource["id"], "task_id": task["id"],
         "window_start": "2026-05-02T10:00:00Z", "window_end": "2026-05-02T12:00:00Z",
         "expected_resource_version": v}, COORD)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_UNAVAILABLE)


def test_assignment_referential_check_precedes_temporal_overlap(api):
    """PRD §2.5: "9. Temporal overlap, else `ERR_RESOURCE_WINDOW_CONFLICT` or
    `ERR_MEMBER_DOUBLE_BOOKED` (409)."
    PRD §2.5: "the checks are applied in a fixed order so that the returned
    `error_id` is deterministic."

    Design: Difficulty/priority_pair_validation_conflict/assignment_referential_beats_temporal
    """
    task, resource, v = _oos_resource_with_reserved_window(api, "OR-2026-0010b")
    resp = api.create_resource_assignment(
        {"resource_id": resource["id"], "task_id": task["id"],
         "window_start": "2026-05-02T10:00:00Z", "window_end": "2026-05-02T12:00:00Z",
         "expected_resource_version": v}, COORD)
    body = resp.json()["data"]
    assert body["error_id"] == "ERR_RESOURCE_UNAVAILABLE", (
        f"Sibling state (priority 7) must pre-empt temporal overlap (priority 9); got {body}")
