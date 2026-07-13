"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of every test.
Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: the Member role is entity-backed, so any ownership-gated
call made on behalf of a member (acknowledge/decline a callout, submit a claim,
log a ground track) uses make_member_headers(member["id"]) — never the shared
member constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from . import factories as f

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]
FIN = TEST_USERS["finance_officer_headers"]


def _ok(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601):
    return _ok(api.set_clock(f.set_clock_payload(to_iso8601), COORD))


# --------------------------------------------------------------------------
# Incident
# --------------------------------------------------------------------------
def create_incident(api, **overrides):
    return _ok(api.create_incident(f.create_incident_payload(**overrides), COORD))


def create_active_incident(api, **overrides):
    inc = create_incident(api, **overrides)
    inc = _ok(api.activate_incident(inc["id"], IC))
    return inc


def create_demobilizing_incident(api, **overrides):
    inc = create_active_incident(api, **overrides)
    inc = _ok(api.demobilize_incident(inc["id"], IC))
    return inc


# --------------------------------------------------------------------------
# Team / Member / Certification
# --------------------------------------------------------------------------
def create_team(api, **overrides):
    return _ok(api.create_team(f.create_team_payload(**overrides), COORD))


def create_member(api, team_id, **overrides):
    return _ok(api.create_member(f.create_member_payload(team_id, **overrides), COORD))


def create_team_and_member(api, team_overrides=None, member_overrides=None):
    team = create_team(api, **(team_overrides or {}))
    member = create_member(api, team["id"], **(member_overrides or {}))
    return team, member


def create_certification(api, member_id, **overrides):
    return _ok(api.create_certification(
        f.create_certification_payload(member_id, **overrides), COORD))


# --------------------------------------------------------------------------
# Task
# --------------------------------------------------------------------------
def create_task(api, incident_id, **overrides):
    return _ok(api.create_task(f.create_task_payload(incident_id, **overrides), COORD))


def create_assigned_task(api, incident_id, **overrides):
    """Create a task and assign it (requires the incident already ACTIVE)."""
    task = create_task(api, incident_id, **overrides)
    task = _ok(api.assign_task(task["id"], IC))
    return task


# --------------------------------------------------------------------------
# Callout lifecycle
# --------------------------------------------------------------------------
def create_callout(api, task_id, member_id):
    return _ok(api.create_callout(f.create_callout_payload(task_id, member_id), COORD))


def create_acknowledged_callout(api, task_id, member_id):
    co = create_callout(api, task_id, member_id)
    co = _ok(api.acknowledge_callout(co["id"], make_member_headers(member_id)))
    return co


def create_standby_callout(api, task_id, member_id):
    co = create_acknowledged_callout(api, task_id, member_id)
    co = _ok(api.standby_callout(co["id"], COORD))
    return co


def create_deployed_callout(api, task_id, member_id):
    """Drive a callout REQUESTED -> ACKNOWLEDGED -> STANDBY -> DEPLOYED.
    The task must already be ASSIGNED or IN_PROGRESS and cert requirements met."""
    co = create_standby_callout(api, task_id, member_id)
    co = _ok(api.deploy_callout(co["id"], COORD))
    return co


def setup_task_in_progress_with_member(api, incident_overrides=None, task_overrides=None,
                                       member_role="SEARCHER"):
    """ACTIVE incident + team + member + ASSIGNED task with one DEPLOYED member,
    task driven to IN_PROGRESS. Returns (incident, team, member, task, callout)."""
    inc = create_active_incident(api, **(incident_overrides or {}))
    team, member = create_team_and_member(api, member_overrides={"member_role": member_role})
    task = create_assigned_task(api, inc["id"], **(task_overrides or {}))
    co = create_deployed_callout(api, task["id"], member["id"])
    task = _ok(api.start_task(task["id"], COORD))
    return inc, team, member, task, co


# --------------------------------------------------------------------------
# Resource / ResourceAssignment
# --------------------------------------------------------------------------
def create_resource(api, **overrides):
    """Returns the created resource dict (carries version, starting at 1)."""
    return _ok(api.create_resource(f.create_resource_payload(**overrides), COORD))


def current_resource_version(api, resource_id):
    return _ok(api.get_resource(resource_id, COORD))["version"]


def create_resource_assignment(api, resource_id, task_id, expected_resource_version, **overrides):
    return _ok(api.create_resource_assignment(
        f.create_resource_assignment_payload(
            resource_id, task_id, expected_resource_version, **overrides),
        COORD))


def create_active_resource_assignment(api, resource_id, task_id, expected_resource_version,
                                      **overrides):
    """Create a RESERVED assignment then activate it (task must be IN_PROGRESS)."""
    asg = create_resource_assignment(api, resource_id, task_id, expected_resource_version, **overrides)
    asg = _ok(api.activate_resource_assignment(asg["id"], COORD))
    return asg


# --------------------------------------------------------------------------
# Ground tracks
# --------------------------------------------------------------------------
def log_ground_track(api, task_id, member_id, owned_by_member=False, **overrides):
    headers = make_member_headers(member_id) if owned_by_member else COORD
    return _ok(api.create_ground_track(
        f.create_ground_track_payload(task_id, member_id, **overrides), headers))


# --------------------------------------------------------------------------
# Reimbursement claim
# --------------------------------------------------------------------------
def create_claim(api, member_id, incident_id, **overrides):
    return _ok(api.create_claim(
        f.create_claim_payload(member_id, incident_id, **overrides), COORD))


def create_submitted_claim(api, member_id, incident_id, **overrides):
    claim = create_claim(api, member_id, incident_id, **overrides)
    claim = _ok(api.submit_claim(claim["id"], make_member_headers(member_id)))
    return claim


# --------------------------------------------------------------------------
# Clue
# --------------------------------------------------------------------------
def create_clue(api, incident_id, **overrides):
    return _ok(api.create_clue(f.create_clue_payload(incident_id, **overrides), COORD))


def create_dismissed_clue(api, incident_id, **overrides):
    clue = create_clue(api, incident_id, **overrides)
    clue = _ok(api.dismiss_clue(clue["id"], IC))
    return clue


# --------------------------------------------------------------------------
# After-action report
# --------------------------------------------------------------------------
def create_aar(api, incident_id, **overrides):
    return _ok(api.create_aar(f.create_aar_payload(incident_id, **overrides), COORD))
