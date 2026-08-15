"""Composite setup helpers for the confined-space rescue domain.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading (PRD §2.1): EntrySupervisor, Attendant, RescueTeamLead, and
SafetyOfficer calls are entity-backed — X-User-ID must be the id of an ACTIVE
Personnel row holding the matching qualification. Every workspace dict carries
per-instance headers built from the real Personnel ids via the make_*
builders; identity-gated calls never fall back to the shared constants.

Optimistic concurrency (PRD §2.7): plan create, plan approve, permit create,
and space PATCH all require expected_space_version matching the space's
current version. The helpers here always re-read the space immediately before
the write so the version is fresh.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_atmospheric_reading_payload,
    create_client_account_payload,
    create_confined_space_payload,
    create_entry_permit_payload,
    create_incident_payload,
    create_isolation_verification_payload,
    create_personnel_payload,
    create_rescue_plan_payload,
    create_roster_entry_payload,
    create_standby_assignment_payload,
    generate_statement_payload,
)
from .test_users import (
    TEST_USERS,
    make_attendant_headers,
    make_entry_supervisor_headers,
    make_rescue_team_lead_headers,
    make_safety_officer_headers,
)

# Opaque roles (PRD §2.1): shared constants are the canonical form.
OPS = TEST_USERS["operations_manager_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]

DAY = "2026-08-03"  # a Monday in UTC
DEFAULT_PLANNED_START = f"{DAY}T05:00:00Z"
DEFAULT_PLANNED_END = f"{DAY}T20:00:00Z"
DEFAULT_STANDBY_START = f"{DAY}T05:00:00Z"
DEFAULT_STANDBY_END = f"{DAY}T20:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (OperationsManager only); runs all sweeps."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def make_personnel(full_name, qualifications, certifications=None,
                   max_duty_hours=None):
    """Create one Personnel record (born ACTIVE). Returns the record."""
    overrides = {"full_name": full_name, "role_qualifications": qualifications}
    if certifications is not None:
        overrides["certifications"] = certifications
    if max_duty_hours is not None:
        overrides["max_duty_hours"] = max_duty_hours
    return get_success_data(
        api_client.create_personnel(create_personnel_payload(**overrides), OPS))


def create_ops_team():
    """Create the standard persona set and matching entity-backed headers.

    Returns a dict with Personnel records under ``lead``, ``supervisor``,
    ``officer``, ``attendant``, ``rescuer``, ``entrant`` and header dicts
    under ``<key>_headers`` built from the real Personnel ids.
    """
    team = {}
    team["lead"] = make_personnel("Lead One", ["RESCUE_LEAD"])
    team["supervisor"] = make_personnel("Sup One", ["ENTRY_SUPERVISOR"])
    team["officer"] = make_personnel("Safe One", ["SAFETY_OFFICER"])
    team["attendant"] = make_personnel("Att One", ["ATTENDANT"])
    team["rescuer"] = make_personnel(
        "Rescuer One", ["RESCUER"], certifications=["CONFINED_SPACE_RESCUE"])
    team["entrant"] = make_personnel("Ent One", [])
    team["lead_headers"] = make_rescue_team_lead_headers(team["lead"]["id"])
    team["supervisor_headers"] = make_entry_supervisor_headers(
        team["supervisor"]["id"])
    team["officer_headers"] = make_safety_officer_headers(team["officer"]["id"])
    team["attendant_headers"] = make_attendant_headers(team["attendant"]["id"])
    return team


def create_account(**overrides):
    """Create a ClientAccount (born balance 0, hold false)."""
    return get_success_data(
        api_client.create_client_account(
            create_client_account_payload(**overrides), OPS))


def create_space(account_id, **overrides):
    """Register a ConfinedSpace under an account (born AVAILABLE)."""
    return get_success_data(
        api_client.create_confined_space(
            account_id, create_confined_space_payload(**overrides), OPS))


def read_space(space_id):
    return get_success_data(api_client.get_confined_space(space_id, OPS))


def read_account(account_id):
    return get_success_data(api_client.get_client_account(account_id, CLERK))


def read_permit(permit_id):
    return get_success_data(api_client.get_entry_permit(permit_id, OPS))


def read_personnel(personnel_id):
    return get_success_data(api_client.get_personnel(personnel_id, OPS))


def read_standby(assignment_id):
    return get_success_data(
        api_client.get_standby_assignment(assignment_id, OPS))


def read_roster_entry(entry_id):
    return get_success_data(api_client.get_roster_entry(entry_id, OPS))


def read_statement(statement_id):
    return get_success_data(api_client.get_statement(statement_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 1: OCC-threaded writes and state transitions
# ---------------------------------------------------------------------------

def create_plan(space_id, lead_headers, **overrides):
    """Create a DRAFT RescuePlan, threading a freshly read space version."""
    space = read_space(space_id)
    payload = create_rescue_plan_payload(space["version"], **overrides)
    return get_success_data(
        api_client.create_rescue_plan(space_id, payload, lead_headers))


def approve_plan(space_id, plan_id, lead_headers):
    """Approve a DRAFT plan, threading a freshly read space version."""
    space = read_space(space_id)
    return get_success_data(
        api_client.approve_rescue_plan(
            plan_id, {"expected_space_version": space["version"]},
            lead_headers))


def create_permit(space_id, supervisor_headers, purpose="Routine entry",
                  planned_start_at=DEFAULT_PLANNED_START,
                  planned_end_at=DEFAULT_PLANNED_END):
    """Create a DRAFT EntryPermit, threading a freshly read space version."""
    space = read_space(space_id)
    payload = create_entry_permit_payload(
        space["version"], purpose=purpose,
        planned_start_at=planned_start_at, planned_end_at=planned_end_at)
    return get_success_data(
        api_client.create_entry_permit(space_id, payload, supervisor_headers))


def issue_permit(permit_id, supervisor_headers):
    return get_success_data(api_client.issue_permit(permit_id, supervisor_headers))


def activate_permit(permit_id, supervisor_headers):
    return get_success_data(
        api_client.activate_permit(permit_id, supervisor_headers))


def suspend_permit(permit_id, headers, reason=None):
    return get_success_data(
        api_client.suspend_permit(permit_id, headers, reason=reason))


def resume_permit(permit_id, supervisor_headers):
    return get_success_data(api_client.resume_permit(permit_id, supervisor_headers))


def close_permit(permit_id, supervisor_headers):
    return get_success_data(api_client.close_permit(permit_id, supervisor_headers))


def cancel_permit(permit_id, supervisor_headers, reason=None):
    return get_success_data(
        api_client.cancel_permit(permit_id, supervisor_headers, reason=reason))


def post_reading(permit_id, attendant_headers, reading_kind="PRE_ENTRY",
                 o2_pct=20.9, lel_pct=0, h2s_ppm=0, co_ppm=0):
    payload = create_atmospheric_reading_payload(
        reading_kind=reading_kind, o2_pct=o2_pct, lel_pct=lel_pct,
        h2s_ppm=h2s_ppm, co_ppm=co_ppm)
    return get_success_data(
        api_client.create_atmospheric_reading(permit_id, payload,
                                              attendant_headers))


def submit_isolation(permit_id, officer_headers, isolation_type="VENTILATION",
                     evidence_ref="evidence-1"):
    payload = create_isolation_verification_payload(
        isolation_type=isolation_type, evidence_ref=evidence_ref)
    return get_success_data(
        api_client.create_isolation_verification(permit_id, payload,
                                                 officer_headers))


def verify_isolation_record(verification_id, officer_headers):
    return get_success_data(
        api_client.verify_isolation(verification_id, officer_headers))


def schedule_roster(permit_id, supervisor_headers, personnel_id,
                    assignment_role="ENTRANT",
                    scheduled_start_at=f"{DAY}T05:00:00Z",
                    scheduled_end_at=f"{DAY}T17:00:00Z",
                    relief_of_entry_id=None):
    overrides = {
        "assignment_role": assignment_role,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    if relief_of_entry_id is not None:
        overrides["relief_of_entry_id"] = relief_of_entry_id
    payload = create_roster_entry_payload(personnel_id, **overrides)
    return get_success_data(
        api_client.create_roster_entry(permit_id, payload, supervisor_headers))


def roster_checkin(entry_id, supervisor_headers):
    return get_success_data(api_client.roster_check_in(entry_id,
                                                       supervisor_headers))


def roster_checkout(entry_id, supervisor_headers):
    return get_success_data(api_client.roster_check_out(entry_id,
                                                        supervisor_headers))


def schedule_standby(permit_id, lead_headers, rescuer_id,
                     standby_start_at=DEFAULT_STANDBY_START,
                     standby_end_at=DEFAULT_STANDBY_END):
    payload = create_standby_assignment_payload(
        rescuer_id, standby_start_at=standby_start_at,
        standby_end_at=standby_end_at)
    return get_success_data(
        api_client.create_standby_assignment(permit_id, payload, lead_headers))


def standby_checkin(assignment_id, lead_headers):
    return get_success_data(
        api_client.standby_check_in(assignment_id, lead_headers))


def standby_release(assignment_id, lead_headers):
    return get_success_data(api_client.standby_release(assignment_id,
                                                       lead_headers))


def standby_cancel(assignment_id, lead_headers):
    return get_success_data(api_client.standby_cancel(assignment_id,
                                                      lead_headers))


def report_incident(permit_id, headers, severity="MINOR", kind="EQUIPMENT",
                    description="Anomaly observed"):
    payload = create_incident_payload(
        severity=severity, kind=kind, description=description)
    return get_success_data(api_client.create_incident(permit_id, payload,
                                                       headers))


def generate_statement(account_id, period_start="2026-08-03T00:00:00Z",
                       period_end="2026-08-04T00:00:00Z"):
    payload = generate_statement_payload(
        period_start=period_start, period_end=period_end)
    return get_success_data(
        api_client.generate_statement(account_id, payload, CLERK))


def statement_lines(statement_id):
    return get_success_data(api_client.list_statement_lines(statement_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — account + space (+ approved plan) + permit
# ---------------------------------------------------------------------------

def setup_account_space(team=None, account_overrides=None, space_overrides=None):
    """Create one client account and one confined space under it."""
    account = create_account(**(account_overrides or {}))
    space = create_space(account["id"], **(space_overrides or {}))
    return account, space


def setup_issued_permit(at="2026-08-03T05:30:00Z",
                        account_overrides=None, space_overrides=None,
                        with_plan=True, plan_overrides=None,
                        planned_start_at=DEFAULT_PLANNED_START,
                        planned_end_at=DEFAULT_PLANNED_END,
                        team=None):
    """Account + space (+ APPROVED plan) + DRAFT permit + issue.

    Returns a context dict with team/account/space/plan/permit. The clock is
    set to ``at`` first so later steps observe a stable logical time.
    """
    team = team or create_ops_team()
    set_clock(at)
    account, space = setup_account_space(
        team, account_overrides=account_overrides,
        space_overrides=space_overrides)
    plan = None
    if with_plan:
        plan = create_plan(space["id"], team["lead_headers"],
                           **(plan_overrides or {}))
        plan = approve_plan(space["id"], plan["id"], team["lead_headers"])
    permit = create_permit(space["id"], team["supervisor_headers"],
                           planned_start_at=planned_start_at,
                           planned_end_at=planned_end_at)
    permit = issue_permit(permit["id"], team["supervisor_headers"])
    return {"team": team, "account": account, "space": space, "plan": plan,
            "permit": permit}


# ---------------------------------------------------------------------------
# Tier 3: full activation chain — the workhorse for safety/workflow tests
# ---------------------------------------------------------------------------

def setup_active_permit(at="2026-08-03T05:30:00Z",
                        account_overrides=None, space_overrides=None,
                        plan_overrides=None,
                        planned_start_at=DEFAULT_PLANNED_START,
                        planned_end_at=DEFAULT_PLANNED_END,
                        standby_start_at=DEFAULT_STANDBY_START,
                        standby_end_at=DEFAULT_STANDBY_END,
                        check_in_standby=True,
                        pre_entry_reading=True,
                        team=None):
    """ISSUED permit + required isolations VERIFIED + fresh PRE_ENTRY reading
    + standby coverage + activation. Returns the context dict with ``permit``
    in ACTIVE, plus ``standby`` and ``reading``.

    All activation preconditions are evaluated against the same logical
    instant ``at``: the reading is 0 minutes old, the standby window contains
    ``at``, and required isolation verifications are verified at ``at``
    (12-hour validity).
    """
    ctx = setup_issued_permit(
        at=at, account_overrides=account_overrides,
        space_overrides=space_overrides, with_plan=True,
        plan_overrides=plan_overrides, planned_start_at=planned_start_at,
        planned_end_at=planned_end_at, team=team)
    team = ctx["team"]
    permit = ctx["permit"]
    space = ctx["space"]

    isolations = []
    if space.get("ventilation_required"):
        iso = submit_isolation(permit["id"], team["officer_headers"],
                               isolation_type="VENTILATION")
        isolations.append(verify_isolation_record(iso["id"],
                                                  team["officer_headers"]))
    if space.get("blind_flange_required"):
        iso = submit_isolation(permit["id"], team["officer_headers"],
                               isolation_type="BLIND_FLANGE")
        isolations.append(verify_isolation_record(iso["id"],
                                                  team["officer_headers"]))
    ctx["isolations"] = isolations

    reading = None
    if pre_entry_reading:
        reading = post_reading(permit["id"], team["attendant_headers"],
                               reading_kind="PRE_ENTRY")
    ctx["reading"] = reading

    standby = schedule_standby(permit["id"], team["lead_headers"],
                               team["rescuer"]["id"],
                               standby_start_at=standby_start_at,
                               standby_end_at=standby_end_at)
    if check_in_standby:
        standby = standby_checkin(standby["id"], team["lead_headers"])
    ctx["standby"] = standby

    ctx["permit"] = activate_permit(permit["id"], team["supervisor_headers"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: billing accumulation — released standby swept into statements
# ---------------------------------------------------------------------------

def setup_released_standby(at_setup="2026-08-03T09:00:00Z",
                           checkin_at="2026-08-03T10:00:00Z",
                           release_at="2026-08-03T12:07:00Z",
                           account_overrides=None,
                           standby_start_at="2026-08-03T10:00:00Z",
                           standby_end_at="2026-08-03T20:00:00Z",
                           team=None):
    """ISSUED permit + standby assignment checked in at ``checkin_at`` and
    released at ``release_at`` (billable fields computed at release).

    The permit is left ISSUED (standby scheduling/check-in are legal on an
    ISSUED permit per PRD §3.5). Returns the context dict with the RELEASED
    ``standby`` assignment.
    """
    ctx = setup_issued_permit(at=at_setup,
                              account_overrides=account_overrides, team=team)
    team = ctx["team"]
    standby = schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                               team["rescuer"]["id"],
                               standby_start_at=standby_start_at,
                               standby_end_at=standby_end_at)
    set_clock(checkin_at)
    standby = standby_checkin(standby["id"], team["lead_headers"])
    set_clock(release_at)
    standby = standby_release(standby["id"], team["lead_headers"])
    ctx["standby"] = standby
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: crew on duty — attendant/entrant ON_DUTY on an ACTIVE permit
# ---------------------------------------------------------------------------

def add_on_duty_attendant(ctx, scheduled_start_at=f"{DAY}T05:00:00Z",
                          scheduled_end_at=f"{DAY}T17:00:00Z",
                          attendant=None):
    """Schedule + check in an ATTENDANT roster entry on ctx's ACTIVE permit."""
    team = ctx["team"]
    person = attendant or team["attendant"]
    entry = schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                            person["id"], assignment_role="ATTENDANT",
                            scheduled_start_at=scheduled_start_at,
                            scheduled_end_at=scheduled_end_at)
    entry = roster_checkin(entry["id"], team["supervisor_headers"])
    return entry


def add_on_duty_entrant(ctx, scheduled_start_at=f"{DAY}T05:00:00Z",
                        scheduled_end_at=f"{DAY}T17:00:00Z",
                        entrant=None):
    """Schedule + check in an ENTRANT roster entry (requires an attendant
    already ON_DUTY per PRD §3.5)."""
    team = ctx["team"]
    person = entrant or team["entrant"]
    entry = schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                            person["id"], assignment_role="ENTRANT",
                            scheduled_start_at=scheduled_start_at,
                            scheduled_end_at=scheduled_end_at)
    entry = roster_checkin(entry["id"], team["supervisor_headers"])
    return entry
