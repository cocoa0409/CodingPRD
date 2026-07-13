"""Deployment safety and resource scheduling: inclusive cert-expiry boundary,
cross-entity readiness gates, half-open resource windows, member rest-buffer."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_active_incident, create_team_and_member, create_certification,
    create_assigned_task, create_task, create_standby_callout, create_deployed_callout,
    create_incident, create_resource, create_resource_assignment, current_resource_version,
    create_submitted_claim,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]
FIN = TEST_USERS["finance_officer_headers"]


# --- Difficulty: boundary_precision_check / cert_expiry_inclusive_boundary_on_deploy ---

def _standby_callout_cert_expiring_at(api, ics, expires):
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc = create_active_incident(api, name="Boundary Cert", ics_incident_number=ics)
    team, member = create_team_and_member(api, member_overrides={"full_name": "Ivy Med"})
    create_certification(api, member["id"], cert_type="WFR",
                         issued_date="2024-06-01T00:00:00Z", expires_date=expires)
    task = create_assigned_task(api, inc["id"], segment_area_sqkm=5.0, planned_searcher_hours=4,
                                required_cert_types=["WFR"], planned_start="2026-06-02T08:00:00Z",
                                planned_end="2026-06-02T16:00:00Z")
    co = create_standby_callout(api, task["id"], member["id"])
    return co


def test_deploy_rejected_when_cert_expires_exactly_at_clock(api):
    """PRD §3.2: "A certification's `status` is computed, not stored as input: it is
    `EXPIRED` when the logical clock is at or after the `expires_date`, and `VALID`
    otherwise. The boundary is inclusive on expiry — a certification whose
    `expires_date` exactly equals the current logical-clock instant is already
    `EXPIRED`, because expiry takes effect at the very start of the expiry instant."
    PRD §3.4: "the member must hold a `VALID` certification for every certification
    type listed in the task's `required_cert_types`, evaluated against the logical
    clock, else `ERR_CERT_REQUIREMENT_NOT_MET`."

    Design: Difficulty/boundary_precision_check/cert_expiry_inclusive_boundary_on_deploy
    """
    co = _standby_callout_cert_expiring_at(api, "OR-2026-0011", "2026-06-01T00:00:00Z")
    api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, COORD)  # exactly the expiry instant
    resp = api.deploy_callout(co["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_CERT_REQUIREMENT_NOT_MET)


def test_deploy_at_expiry_boundary_leaves_callout_standby(api):
    """PRD §3.4: "the member must hold a `VALID` certification for every certification
    type listed in the task's `required_cert_types`, evaluated against the logical
    clock, else `ERR_CERT_REQUIREMENT_NOT_MET`."

    Design: Difficulty/boundary_precision_check/cert_expiry_inclusive_boundary_on_deploy
    """
    co = _standby_callout_cert_expiring_at(api, "OR-2026-0011b", "2026-06-01T00:00:00Z")
    api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, COORD)
    resp = api.deploy_callout(co["id"], COORD)
    assert resp.json()["data"]["error_id"] == "ERR_CERT_REQUIREMENT_NOT_MET"
    assert validate_success(api.get_callout(co["id"], COORD))["status"] == "STANDBY"


# --- Difficulty: cross_entity_state_dependency / deploy_requires_task_ready ---

def _standby_callout_on_draft_task(api, ics):
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc = create_active_incident(api, name="Dep Task", ics_incident_number=ics)
    team, member = create_team_and_member(api)
    task = create_task(api, inc["id"], segment_area_sqkm=5.0, planned_searcher_hours=4)
    co = create_standby_callout(api, task["id"], member["id"])
    return co


def test_deploy_on_draft_task_returns_task_not_ready(api):
    """PRD §3.4: "First, the target task must be `ASSIGNED` or `IN_PROGRESS`, else
    `ERR_TASK_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/deploy_requires_task_ready
    """
    co = _standby_callout_on_draft_task(api, "OR-2026-0013")
    resp = api.deploy_callout(co["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_TASK_NOT_READY)


def test_deploy_on_draft_task_does_not_deploy_member(api):
    """PRD §3.4: "First, the target task must be `ASSIGNED` or `IN_PROGRESS`, else
    `ERR_TASK_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/deploy_requires_task_ready
    """
    co = _standby_callout_on_draft_task(api, "OR-2026-0013b")
    resp = api.deploy_callout(co["id"], COORD)
    assert resp.json()["data"]["error_id"] == "ERR_TASK_NOT_READY"
    assert validate_success(api.get_callout(co["id"], COORD))["status"] == "STANDBY"


# --- Difficulty: cross_entity_state_dependency / claim_approve_requires_incident_demobilizing ---

def _submitted_claim_on_active_incident(api, ics):
    inc = create_active_incident(api, name="Dep Incident", incident_type="URBAN",
                                 ics_incident_number=ics)
    team, member = create_team_and_member(api)
    claim = create_submitted_claim(api, member["id"], inc["id"], declared_mileage_miles=30,
                                   meal_count=2, lodging_nights=0)
    return inc, claim


def test_approve_claim_on_active_incident_returns_not_demobilizing(api):
    """PRD §3.8: "A `FinanceOfficer` approves a submitted claim, moving it from
    `SUBMITTED` to `APPROVED`, but only when the parent incident is `DEMOBILIZING` or
    `CLOSED`, else `ERR_INCIDENT_NOT_DEMOBILIZING`."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_incident_demobilizing
    """
    inc, claim = _submitted_claim_on_active_incident(api, "OR-2026-0014")
    resp = api.approve_claim(claim["id"], FIN)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_DEMOBILIZING)


def test_approve_blocked_on_active_incident_leaves_claim_submitted(api):
    """PRD §3.8: "A `FinanceOfficer` approves a submitted claim, moving it from
    `SUBMITTED` to `APPROVED`, but only when the parent incident is `DEMOBILIZING` or
    `CLOSED`, else `ERR_INCIDENT_NOT_DEMOBILIZING`."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_incident_demobilizing
    """
    inc, claim = _submitted_claim_on_active_incident(api, "OR-2026-0014b")
    resp = api.approve_claim(claim["id"], FIN)
    assert resp.json()["data"]["error_id"] == "ERR_INCIDENT_NOT_DEMOBILIZING"
    assert validate_success(api.get_claim(claim["id"], COORD))["status"] == "SUBMITTED"


# --- Difficulty: resource_temporal_overlap / resource_halfopen_adjacent_ok_overlap_rejected ---

def _resource_with_two_windows(api, ics):
    inc = create_incident(api, name="Overlap Res", incident_type="AIR_SEARCH",
                          ics_incident_number=ics)
    task = create_task(api, inc["id"], task_type="AIR_RECON", segment_area_sqkm=20.0,
                       planned_searcher_hours=4, planned_start="2026-05-02T06:00:00Z",
                       planned_end="2026-05-02T20:00:00Z")
    resource = create_resource(api, name="Drone D1", resource_type="DRONE")
    create_resource_assignment(api, resource["id"], task["id"], resource["version"],
                               window_start="2026-05-02T09:00:00Z",
                               window_end="2026-05-02T11:00:00Z")
    return inc, task, resource


def test_adjacent_resource_window_is_accepted(api):
    """PRD §3.5: "The window is half-open: two assignments on the same resource
    conflict only when their intervals actually overlap, so an assignment ending
    exactly when another begins does not collide."

    Design: Difficulty/resource_temporal_overlap/resource_halfopen_adjacent_ok_overlap_rejected
    """
    inc, task, resource = _resource_with_two_windows(api, "OR-2026-0015")
    v1 = current_resource_version(api, resource["id"])
    resp = api.create_resource_assignment(
        {"resource_id": resource["id"], "task_id": task["id"],
         "window_start": "2026-05-02T11:00:00Z", "window_end": "2026-05-02T13:00:00Z",
         "expected_resource_version": v1}, COORD)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "RESERVED"


def test_overlapping_resource_window_is_rejected(api):
    """PRD §3.5: "A create is rejected with `ERR_RESOURCE_WINDOW_CONFLICT` when the
    proposed window overlaps any existing `RESERVED` or `ACTIVE` assignment on the
    same resource".

    Design: Difficulty/resource_temporal_overlap/resource_halfopen_adjacent_ok_overlap_rejected
    """
    inc, task, resource = _resource_with_two_windows(api, "OR-2026-0015b")
    v1 = current_resource_version(api, resource["id"])
    resp = api.create_resource_assignment(
        {"resource_id": resource["id"], "task_id": task["id"],
         "window_start": "2026-05-02T10:00:00Z", "window_end": "2026-05-02T12:00:00Z",
         "expected_resource_version": v1}, COORD)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_WINDOW_CONFLICT)


# --- Difficulty: resource_temporal_overlap / member_buffer_doublebook_on_deploy ---

def _member_deployed_then_second_standby(api, ics):
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc = create_active_incident(api, name="Double Book", ics_incident_number=ics)
    team, member = create_team_and_member(api, member_overrides={"full_name": "Ned Vol"})
    task1 = create_assigned_task(api, inc["id"], task_number="T-1", segment_area_sqkm=5.0,
                                 planned_searcher_hours=4, planned_start="2026-05-02T10:00:00Z",
                                 planned_end="2026-05-02T12:00:00Z")
    task2 = create_assigned_task(api, inc["id"], task_number="T-2", segment_area_sqkm=5.0,
                                 planned_searcher_hours=4, planned_start="2026-05-02T12:30:00Z",
                                 planned_end="2026-05-02T14:00:00Z")
    create_deployed_callout(api, task1["id"], member["id"])
    co2 = create_standby_callout(api, task2["id"], member["id"])
    return member, co2


def test_deploy_within_rest_buffer_returns_double_booked(api):
    """PRD §3.4: "Third, the member must not be double-booked: they may hold no other
    `DEPLOYED` callout on a task whose planned window lies within the rest buffer of
    60 minutes of this task's window, else `ERR_MEMBER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/member_buffer_doublebook_on_deploy
    """
    member, co2 = _member_deployed_then_second_standby(api, "OR-2026-0016")
    resp = api.deploy_callout(co2["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_MEMBER_DOUBLE_BOOKED)


def test_double_booked_deploy_leaves_second_callout_standby(api):
    """PRD §3.4: "Third, the member must not be double-booked: they may hold no other
    `DEPLOYED` callout on a task whose planned window lies within the rest buffer of
    60 minutes of this task's window, else `ERR_MEMBER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/member_buffer_doublebook_on_deploy
    """
    member, co2 = _member_deployed_then_second_standby(api, "OR-2026-0016b")
    resp = api.deploy_callout(co2["id"], COORD)
    assert resp.json()["data"]["error_id"] == "ERR_MEMBER_DOUBLE_BOOKED"
    assert validate_success(api.get_callout(co2["id"], COORD))["status"] == "STANDBY"
