"""Role-based authorization, member ownership, and optimistic concurrency on
resource-assignment creation."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS, make_member_headers,
    ApiErrorId,
    create_incident, create_active_incident, create_demobilizing_incident,
    create_team_and_member, create_member, create_team, create_task, create_callout,
    create_submitted_claim, create_resource, create_resource_assignment,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]
FIN = TEST_USERS["finance_officer_headers"]


# --- Corner: rbac ---

def test_member_cannot_approve_claim(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: the `/sar/reimbursement-claims/{claimId}/approve` operation is authorized
    for `FinanceOfficer` only.

    Design: Corner/rbac/member_cannot_approve_claim_returns_unauthorized
    """
    inc = create_demobilizing_incident(api, name="Rbac Inc", incident_type="URBAN",
                                       ics_incident_number="OR-2026-1015")
    team, member = create_team_and_member(api)
    claim = create_submitted_claim(api, member["id"], inc["id"], declared_mileage_miles=15)
    resp = api.approve_claim(claim["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_finance_officer_cannot_activate_incident(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.1: "Only an `IncidentCommander` drives the incident lifecycle. Activating
    the incident moves it from `PLANNING` to `ACTIVE`".

    Design: Corner/rbac/finance_cannot_activate_incident_returns_unauthorized
    """
    inc = create_incident(api, name="Act Inc", incident_type="URBAN",
                          ics_incident_number="OR-2026-1016")
    resp = api.activate_incident(inc["id"], FIN)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_member_cannot_acknowledge_another_members_callout(api):
    """PRD §2.1: "when a `Member` acknowledges or declines a callout, submits a
    reimbursement claim, or logs a ground track, the target's `member_id` must equal
    the caller's `X-User-ID`, or the action is rejected with `ERR_FORBIDDEN_NOT_OWNER`."

    Design: Corner/rbac/member_cannot_acknowledge_others_callout_returns_not_owner
    """
    inc = create_active_incident(api, name="Own Inc", ics_incident_number="OR-2026-1017")
    team = create_team(api)
    m_a = create_member(api, team["id"], full_name="Own A", email="owna@x.org")
    m_b = create_member(api, team["id"], full_name="Own B", email="ownb@x.org")
    task = create_task(api, inc["id"])
    co = create_callout(api, task["id"], m_a["id"])
    resp = api.acknowledge_callout(co["id"], make_member_headers(m_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER)


# --- Corner: cross_cutting / optimistic concurrency ---

def test_stale_resource_version_on_assignment_create_rejected(api):
    """PRD §2.8: "If another assignment has been created against the same resource
    since the client last read it — advancing that resource's `version` and its set
    of occupied windows — the supplied `expected_resource_version` will be older than
    the current one, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_resource_version_on_assignment_create_returns_stale_version
    """
    inc = create_incident(api, name="Occ Inc", incident_type="AIR_SEARCH",
                          ics_incident_number="OR-2026-1018")
    task = create_task(api, inc["id"], task_type="AIR_RECON", segment_area_sqkm=20.0,
                       planned_searcher_hours=4, planned_start="2026-05-02T06:00:00Z",
                       planned_end="2026-05-02T20:00:00Z")
    resource = create_resource(api, name="Fixed W1", resource_type="FIXED_WING")
    stale_version = resource["version"]
    create_resource_assignment(api, resource["id"], task["id"], stale_version,
                               window_start="2026-05-02T09:00:00Z",
                               window_end="2026-05-02T11:00:00Z")
    # Non-overlapping window, but carrying the now-stale pre-first-assignment version.
    resp = api.create_resource_assignment(
        {"resource_id": resource["id"], "task_id": task["id"],
         "window_start": "2026-05-02T12:00:00Z", "window_end": "2026-05-02T14:00:00Z",
         "expected_resource_version": stale_version}, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_assignment_create_increments_resource_version(api):
    """PRD §3.5: "A successful create opens the assignment in `RESERVED`, increments
    the resource's `active_assignment_count` by one, and increments the resource's
    `version` by one."

    Design: Corner/cross_cutting/occ_resource_version_increments_on_assignment_create
    """
    inc = create_incident(api, name="Occ2 Inc", incident_type="AIR_SEARCH",
                          ics_incident_number="OR-2026-1019")
    task = create_task(api, inc["id"], task_type="AIR_RECON", segment_area_sqkm=20.0,
                       planned_searcher_hours=4, planned_start="2026-05-02T06:00:00Z",
                       planned_end="2026-05-02T20:00:00Z")
    resource = create_resource(api, name="UTV U1", resource_type="UTV")
    create_resource_assignment(api, resource["id"], task["id"], resource["version"],
                               window_start="2026-05-02T09:00:00Z",
                               window_end="2026-05-02T11:00:00Z")
    res = validate_success(api.get_resource(resource["id"], COORD))
    assert res["version"] == 2
    assert res["active_assignment_count"] == 1
