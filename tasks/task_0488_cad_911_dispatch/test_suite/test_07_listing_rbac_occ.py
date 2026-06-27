"""Listing/pagination, error catalog coverage, RBAC denials, optimistic
concurrency, the close cascade, and immediate consistency.

Queue B (Corner): endpoints (listing), errors, rbac, cross_cutting, consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, setup_agency_station_unit, create_incident, dispatch_unit,
    get_incident_version, setup_dispatched_incident,
    SUP, CALL, DISP,
)


# =====================================================================
# Queue B — endpoints (listing / pagination)
# =====================================================================
def test_list_incidents_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return."
    PRD §2.3: "Paginated list-based responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Three PENDING incidents; limit=2 → 2 items, total_count 3, has_more true.

    Design: Corner/endpoints/list_incidents_pagination_envelope
    """
    set_clock("2026-06-21T15:00:00Z")
    create_incident(incident_type="WELFARE_CHECK", ali_grid_x=10, ali_grid_y=10, ani="5125559022")
    create_incident(incident_type="WELFARE_CHECK", ali_grid_x=11, ali_grid_y=10, ani="5125559023")
    create_incident(incident_type="WELFARE_CHECK", ali_grid_x=12, ali_grid_y=10, ani="5125559024")
    data, meta = validate_paginated(api.list_incidents(DISP, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_list_incidents_filter_by_lifecycle_status(api):
    """PRD §3.3: "Incidents may be listed and filtered by `lifecycle_status`,
    `priority_level`, and `premise_alert_id`."
    PRD §3.8: "Cancellation moves the `lifecycle_status` `PENDING → CANCELLED`".

    Filtering by lifecycle_status=CANCELLED returns only the cancelled incident.

    Design: Corner/endpoints/list_incidents_filter_by_lifecycle_status
    """
    set_clock("2026-06-21T16:00:00Z")
    keep = create_incident(incident_type="WELFARE_CHECK", ali_grid_x=10, ali_grid_y=10, ani="5125559025")
    cancel = create_incident(incident_type="WELFARE_CHECK", ali_grid_x=11, ali_grid_y=10, ani="5125559026")
    validate_success(api.cancel_incident(cancel["id"], {"reason": "x"}, CALL), 200)
    data, _ = validate_paginated(api.list_incidents(DISP, params={"lifecycle_status": "CANCELLED"}))
    ids = [i["id"] for i in data]
    assert cancel["id"] in ids
    assert keep["id"] not in ids
    assert all(i["lifecycle_status"] == "CANCELLED" for i in data)


# =====================================================================
# Queue B — errors
# =====================================================================
def test_oos_unit_set_oos_again_invalid_state(api):
    """PRD §3.1: "These two transitions, `AVAILABLE → OUT_OF_SERVICE` and
    `OUT_OF_SERVICE → AVAILABLE`, are the only ones the manual readiness toggle
    performs; it is not the path for assignment-driven status changes, and
    attempting it from any other status is rejected with `ERR_INVALID_STATE`."

    Setting OUT_OF_SERVICE on an already-OUT_OF_SERVICE unit → ERR_INVALID_STATE.

    Design: Corner/errors/error_invalid_state_unit_oos_when_already_oos
    """
    _, _, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=10, grid_y=10,
        call_sign="POo1", name_prefix="PD Oos")
    validate_success(api.set_unit_status(unit["id"], "OUT_OF_SERVICE", SUP), 200)
    res = api.set_unit_status(unit["id"], "OUT_OF_SERVICE", SUP)
    validate_error(res, "ERR_INVALID_STATE")


def test_get_nonexistent_assignment_not_found(api):
    """PRD §2.6: "every resource identifier named in the URL path is checked for
    existence, validated left to right, with the first missing identifier
    yielding `ERR_NOT_FOUND`."

    GET /assignments/{nonexistent} → ERR_NOT_FOUND (404).

    Design: Corner/errors/error_not_found_on_assignment_path_id
    """
    res = api.get_assignment("00000000-0000-0000-0000-000000000abc", DISP)
    validate_error(res, "ERR_NOT_FOUND")


# =====================================================================
# Queue B — rbac
# =====================================================================
def test_calltaker_cannot_create_assignment(api):
    """PRD §2.1: "When the header is valid but the named role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.4: "A `Dispatcher` obtains nearest-unit recommendations and commits
    units to incidents".

    A Calltaker calling POST /incidents/{id}/assignments → ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/calltaker_cannot_create_assignment_forbidden
    """
    set_clock("2026-06-22T09:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=10, grid_y=10,
        call_sign="PRb1", name_prefix="PD Rb")
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559028")
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": incident["version"], "unit_id": unit["id"]}, CALL)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_dispatcher_cannot_close_incident(api):
    """PRD §2.1: "When the header is valid but the named role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.8: "The second path is **closing with a disposition**, which a
    supervisor performs by recording a disposition against the incident."

    A Dispatcher calling POST /incidents/{id}/dispositions → ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/dispatcher_cannot_close_incident_forbidden
    """
    set_clock("2026-06-22T10:00:00Z")
    inc = create_incident(incident_type="WELFARE_CHECK", ali_grid_x=10,
                          ali_grid_y=10, ani="5125559029")
    res = api.create_disposition(inc["id"], {
        "disposition_code": "UNFOUNDED", "narrative": "x"}, DISP)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or does not name a recognized role,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    A request with no X-User-Role header → ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.list_agencies({"X-User-ID": "anon", "Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED")


# =====================================================================
# Queue B — cross_cutting (OCC + cascade)
# =====================================================================
def test_occ_stale_version_on_second_assignment_rejected(api):
    """PRD §2.5: "The server compares this value against the incident's current
    `version`. If they differ — meaning another writer has advanced the incident
    since the client's last read — the create is rejected with
    `ERR_STALE_INCIDENT_VERSION` and HTTP status 412."

    After the first assignment bumps Incident.version, a second assignment
    carrying the pre-bump version → ERR_STALE_INCIDENT_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_incident_version_on_second_assignment
    """
    set_clock("2026-06-22T11:00:00Z")
    agency, station, u1 = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", grid_x=10, grid_y=10,
        call_sign="MOc1", name_prefix="EMS Occ")
    u2 = validate_success(api.create_unit({
        "agency_id": agency["id"], "station_id": station["id"],
        "call_sign": "MOc2", "capability": "MEDIC_BLS",
        "grid_x": 11, "grid_y": 10}, SUP), 201)
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559030")
    v0 = incident["version"]
    dispatch_unit(incident["id"], v0, unit_id=u1["id"])
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": v0, "unit_id": u2["id"]}, DISP)
    validate_error(res, "ERR_STALE_INCIDENT_VERSION")


def test_occ_correct_version_second_assignment_succeeds(api):
    """PRD §2.5: "The request that creates an assignment against an incident must
    carry `expected_incident_version`, a non-optional field whose value is the
    `version` of the target incident as the client last observed it."
    PRD §2.7: "The incident's `version` is incremented specifically on first
    dispatch, on each escalation, and on close".

    Re-reading the version after the first assignment and passing it lets the
    second assignment succeed (201). Per §2.7 only first dispatch/escalation/close
    bump version, so a second (non-first) assignment leaves the version unchanged.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_second_assignment_succeeds
    """
    set_clock("2026-06-22T12:00:00Z")
    _, _, eng = setup_agency_station_unit(
        discipline="FIRE", capability="ENGINE", grid_x=10, grid_y=10,
        call_sign="EOk1", name_prefix="Fire Ok")
    _, _, med = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", grid_x=10, grid_y=10,
        call_sign="MOk1", name_prefix="EMS Ok")
    incident = create_incident(incident_type="STRUCTURE_FIRE",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559031")
    dispatch_unit(incident["id"], incident["version"], unit_id=eng["id"])
    v1 = get_incident_version(incident["id"])
    asg2 = validate_success(api.create_assignment(incident["id"], {
        "expected_incident_version": v1, "unit_id": med["id"]}, DISP), 201)
    assert asg2["unit_id"] == med["id"]
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc["version"] == v1


def test_occ_version_below_current_rejected(api):
    """PRD §2.5: "The server compares this value against the incident's current
    `version`. If they differ — meaning another writer has advanced the incident
    since the client's last read — the create is rejected with
    `ERR_STALE_INCIDENT_VERSION` and HTTP status 412."

    Passing a version one below the current (after an escalation advanced it) →
    ERR_STALE_INCIDENT_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_version_literal_stale_negative
    """
    set_clock("2026-06-22T13:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", grid_x=10, grid_y=10,
        call_sign="MNg1", name_prefix="EMS Neg")
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559032")
    v0 = incident["version"]
    validate_success(api.escalate_incident(incident["id"], {"reason": "timer"}, SUP), 200)
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": v0 - 1, "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_STALE_INCIDENT_VERSION")


# =====================================================================
# Queue B — consistency_model
# =====================================================================
def test_dispatch_immediately_visible_in_unit_and_incident(api):
    """PRD §3.4: "drives the unit's `status` to `DISPATCHED`, and sets the unit's
    `active_incident_id` to this incident."
    PRD §3.4: "When this is the incident's first accepted assignment, the
    incident's `lifecycle_status` advances from `PENDING` to `DISPATCHED`, its
    `first_dispatch_at` is stamped".

    Immediately after dispatch, a GET on the unit shows DISPATCHED and a GET on
    the incident shows DISPATCHED + first_dispatch_at set.

    Design: Corner/consistency_model/dispatch_immediately_visible_in_unit_and_incident
    """
    set_clock("2026-06-22T15:00:00Z")
    _, _, unit, incident, asg = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=10, ani="5125559034")
    unit_after = validate_success(api.get_unit(unit["id"], DISP), 200)
    inc_after = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert unit_after["status"] == "DISPATCHED"
    assert inc_after["lifecycle_status"] == "DISPATCHED"
    assert unit_after["active_incident_id"] == incident["id"]
    assert inc_after["first_dispatch_at"] is not None
