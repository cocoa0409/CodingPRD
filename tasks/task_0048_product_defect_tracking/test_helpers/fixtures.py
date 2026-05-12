"""Composite setup helpers for the Product Defect Tracking test suite.

Most test claims need the system in a specific state reached through 5-15
API calls (e.g., 'defect at FIXED with a stale fix_record_id'). These
helpers encapsulate those preambles.

Identity threading (PRD §2.1):

  All four persisted roles (TriageManager, Developer, QAEngineer,
  ReleaseManager) are entity_backed:TeamMember. PRD §2.1: 'when X-User-Role
  is TriageManager, Developer, QAEngineer, or ReleaseManager, the value of
  X-User-ID is the id of the acting TeamMember, and any ownership check
  ... compares the defect's assignee_id foreign-key field to X-User-ID.'

  Every ownership-gated call below uses make_<role>_headers(member['id'])
  with the actual TeamMember.id, never the shared TEST_USERS fallback.

Setup helpers use get_success_data (lenient validator) so broken
preconditions surface as obvious 'Setup failed' rather than ambiguous
assertion failures.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    assign_payload,
    attachment_payload,
    create_defect_payload,
    create_module_payload,
    create_project_payload,
    create_team_member_payload,
    duplicate_link_payload,
    emit_event_payload,
    pause_sla_payload,
    regression_complete_payload,
    regression_run_payload,
    severity_override_payload,
    submit_fix_payload,
    unique_suffix,
    verify_payload,
)
from .test_users import (
    make_developer_headers,
    make_qa_engineer_headers,
    make_release_manager_headers,
    make_triage_manager_headers,
)


# ===========================================================================
# Bootstrap helpers — Project, TeamMember, Module
# ===========================================================================
def create_project() -> Dict[str, Any]:
    """A TriageManager is required to create a project, but Project creation
    pre-exists any TeamMember. PRD §2.1 says X-User-ID is the acting
    TeamMember.id for the four persisted roles, but at bootstrap there is
    no TeamMember yet. We use a synthetic 'bootstrap-triage' id; later
    ownership-gated calls always swap in the real TeamMember.id."""
    headers = make_triage_manager_headers("bootstrap-triage")
    return get_success_data(
        api_client.create_project(create_project_payload(), headers)
    )


def create_team_member(
    project: Dict[str, Any], role: str,
    triage_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a TeamMember of the given role. triage_headers defaults to a
    bootstrap TriageManager (because TeamMember creation is exclusive to
    TriageManager per PRD §4)."""
    headers = triage_headers or make_triage_manager_headers(
        "bootstrap-triage"
    )
    return get_success_data(
        api_client.create_team_member(
            project["id"],
            create_team_member_payload(role=role, **overrides),
            headers,
        )
    )


def create_module(
    project: Dict[str, Any],
    owner: Dict[str, Any],
    triage_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Module owned by `owner` (a TeamMember)."""
    headers = triage_headers or make_triage_manager_headers(
        "bootstrap-triage"
    )
    return get_success_data(
        api_client.create_module(
            project["id"],
            create_module_payload(
                owner_team_member_id=owner["id"], **overrides,
            ),
            headers,
        )
    )


def advance_clock(project: Dict[str, Any], minutes: int) -> Dict[str, Any]:
    """PRD §2.6 / §3 prose: admin-only POST /_clock/advance."""
    return get_success_data(
        api_client.advance_clock(
            project["id"], minutes,
            make_triage_manager_headers("bootstrap-triage"),
        )
    )


def run_escalation_sweep(
    project_or_team: Any,
) -> Dict[str, Any]:
    """PRD §3.8: TriageManager invokes POST /_sweep/sla-escalation.

    Accepts either a project dict or a TeamBundle so test code can pass
    `team` (the natural carrier of identity in the test suite). When a
    TeamBundle is supplied the call is identity-threaded to that team's
    real TriageManager.id; bare project dicts fall back to the bootstrap
    triage id."""
    if isinstance(project_or_team, TeamBundle):
        project_id = project_or_team.project["id"]
        headers = project_or_team.triage_headers
    else:
        project_id = project_or_team["id"]
        headers = make_triage_manager_headers("bootstrap-triage")
    return get_success_data(
        api_client.run_sla_escalation_sweep(project_id, headers)
    )


# ===========================================================================
# Tier 2: Composite entity hierarchy
# ===========================================================================
class TeamBundle:
    """Container for a full team in one project: one TeamMember per role.
    Use .triage_headers / .developer_headers / etc. for ownership-gated
    calls."""

    def __init__(
        self,
        project: Dict[str, Any],
        triage: Dict[str, Any],
        developer: Dict[str, Any],
        qa: Dict[str, Any],
        release: Dict[str, Any],
    ) -> None:
        self.project = project
        self.triage = triage
        self.developer = developer
        self.qa = qa
        self.release = release

    @property
    def triage_headers(self) -> Dict[str, str]:
        return make_triage_manager_headers(self.triage["id"])

    @property
    def developer_headers(self) -> Dict[str, str]:
        return make_developer_headers(self.developer["id"])

    @property
    def qa_headers(self) -> Dict[str, str]:
        return make_qa_engineer_headers(self.qa["id"])

    @property
    def release_headers(self) -> Dict[str, str]:
        return make_release_manager_headers(self.release["id"])


def setup_team(
    project: Optional[Dict[str, Any]] = None,
) -> TeamBundle:
    """Project + TriageManager + Developer + QAEngineer + ReleaseManager.

    Once the TriageManager TeamMember exists, every subsequent setup call
    (modules, defects, severity-overrides, ...) flips its X-User-ID over
    to the real TriageManager's id so ownership-checked operations work.
    """
    if project is None:
        project = create_project()

    # Bootstrap creates the TeamMembers (TriageManager-exclusive); the
    # very first TriageManager TeamMember has to be minted via the
    # synthetic bootstrap id. PRD §2.1 explicitly says X-User-ID is the
    # acting TeamMember.id — once the first TriageManager exists,
    # subsequent calls thread through THAT id.
    triage = create_team_member(project, "TRIAGE_MANAGER")
    triage_headers = make_triage_manager_headers(triage["id"])
    developer = create_team_member(
        project, "DEVELOPER", triage_headers=triage_headers,
    )
    qa = create_team_member(
        project, "QA_ENGINEER", triage_headers=triage_headers,
    )
    release = create_team_member(
        project, "RELEASE_MANAGER", triage_headers=triage_headers,
    )
    return TeamBundle(project, triage, developer, qa, release)


def setup_basic_module(
    team: Optional[TeamBundle] = None,
    *,
    kloc: float = 2.0,
    initial_defect_quota: int = 5,
    owner: Optional[Dict[str, Any]] = None,
) -> Tuple[TeamBundle, Dict[str, Any]]:
    """Tier-2 bundle: team + a Module on that project. owner defaults to
    the developer (a valid TeamMember id)."""
    if team is None:
        team = setup_team()
    actual_owner = owner if owner is not None else team.developer
    module = create_module(
        team.project, actual_owner,
        triage_headers=team.triage_headers,
        kloc=kloc, initial_defect_quota=initial_defect_quota,
    )
    return team, module


# ===========================================================================
# Tier 1+3: Defect lifecycle progression
# ===========================================================================
def create_defect(
    team: TeamBundle,
    module: Dict[str, Any],
    *,
    severity: str = "MAJOR",
    business_impact: str = "INTERNAL",
    defect_source: str = "INTERNAL_TEST",
    reporter: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None,
    environment: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a defect. reporter defaults to the team's developer (an
    ACTIVE TeamMember in the same project, hence eligible per PRD §3.2)."""
    reporter_obj = reporter if reporter is not None else team.developer
    reporter_role = (reporter_obj.get("role") or "DEVELOPER").upper()
    # PRD §2.1: header role drives RBAC. Map TeamMember.role to header.
    role_map = {
        "DEVELOPER": ("Developer", make_developer_headers),
        "QA_ENGINEER": ("QAEngineer", make_qa_engineer_headers),
        "TRIAGE_MANAGER": ("TriageManager", make_triage_manager_headers),
        "RELEASE_MANAGER": ("ReleaseManager", make_release_manager_headers),
    }
    if reporter_role not in role_map:
        # ReleaseManager cannot report defects per PRD §4; pick the
        # developer's headers as a safe default.
        headers = team.developer_headers
    else:
        _, builder = role_map[reporter_role]
        headers = builder(reporter_obj["id"])

    payload = create_defect_payload(
        project_id=team.project["id"],
        module_id=module["id"],
        reporter_id=reporter_obj["id"],
        severity=severity,
        business_impact=business_impact,
        defect_source=defect_source,
        title=title or f"Defect {unique_suffix()}",
        environment=environment,
        **overrides,
    )
    return get_success_data(api_client.create_defect(payload, headers))


def assign_defect(
    team: TeamBundle,
    defect: Dict[str, Any],
    *,
    assignee: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Walk NEW -> ASSIGNED. Defaults to assigning to team.developer."""
    target = assignee if assignee is not None else team.developer
    return get_success_data(
        api_client.assign_defect(
            defect["id"],
            team.triage_headers,
            assign_payload(assignee_id=target["id"]),
        )
    )


def start_progress(
    team: TeamBundle,
    defect: Dict[str, Any],
    *,
    developer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Walk ASSIGNED -> IN_PROGRESS. The acting developer must equal
    defect.assignee_id (PRD §3.6)."""
    dev = developer if developer is not None else team.developer
    return get_success_data(
        api_client.start_progress(
            defect["id"], make_developer_headers(dev["id"]),
        )
    )


def submit_fix(
    team: TeamBundle,
    defect: Dict[str, Any],
    *,
    developer: Optional[Dict[str, Any]] = None,
    fix_version: str = "1.0.0",
    commit_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk IN_PROGRESS -> FIXED. Returns the updated defect."""
    dev = developer if developer is not None else team.developer
    return get_success_data(
        api_client.submit_fix(
            defect["id"],
            submit_fix_payload(
                fix_version=fix_version, commit_sha=commit_sha,
            ),
            make_developer_headers(dev["id"]),
        )
    )


def latest_fix_record(
    team: TeamBundle, defect: Dict[str, Any],
) -> Dict[str, Any]:
    """Return the most recently created FixRecord for the defect.
    PRD §3.7 requires the verify body's fix_record_id to be the latest."""
    resp = api_client.list_fix_records(
        defect["id"], team.triage_headers,
        params={"limit": 100, "offset": 0},
    )
    data, _meta = _paginated(resp)
    assert data, "Expected at least one FixRecord for defect"
    # Sort by created_at ascending so the last entry is most recent.
    data.sort(key=lambda r: r.get("created_at", ""))
    return data[-1]


def verify_defect(
    team: TeamBundle,
    defect: Dict[str, Any],
    *,
    outcome: str = "PASSED",
    qa: Optional[Dict[str, Any]] = None,
    fix_record_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk FIXED -> VERIFIED|REOPENED. Verifier MUST be independent of
    the FixRecord.developer_id per PRD §3.7. qa defaults to the team's
    QA engineer, who is by construction != team.developer."""
    qa_member = qa if qa is not None else team.qa
    if fix_record_id is None:
        fix_record_id = latest_fix_record(team, defect)["id"]
    return get_success_data(
        api_client.verify_defect(
            defect["id"],
            verify_payload(outcome=outcome, fix_record_id=fix_record_id),
            make_qa_engineer_headers(qa_member["id"]),
        )
    )


def close_defect(
    team: TeamBundle, defect: Dict[str, Any],
) -> Dict[str, Any]:
    """Walk VERIFIED -> CLOSED."""
    return get_success_data(
        api_client.close_defect(defect["id"], team.triage_headers)
    )


# ===========================================================================
# Tier 3: Lifecycle shortcuts (multi-step)
# ===========================================================================
def setup_defect_in_state(
    team: TeamBundle,
    module: Dict[str, Any],
    target_state: str,
    *,
    severity: str = "MAJOR",
    business_impact: str = "INTERNAL",
    fix_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Walk the Defect state machine to `target_state`.

    Supported targets: NEW, ASSIGNED, IN_PROGRESS, FIXED, VERIFIED,
    CLOSED, REOPENED.
    """
    d = create_defect(
        team, module, severity=severity, business_impact=business_impact,
    )
    if target_state == "NEW":
        return d
    assign_defect(team, d)
    if target_state == "ASSIGNED":
        return fetch_defect(team, d["id"])
    start_progress(team, d)
    if target_state == "IN_PROGRESS":
        return fetch_defect(team, d["id"])
    submit_fix(team, d, fix_version=fix_version)
    if target_state == "FIXED":
        return fetch_defect(team, d["id"])
    if target_state == "REOPENED":
        verify_defect(team, d, outcome="FAILED")
        return fetch_defect(team, d["id"])
    verify_defect(team, d, outcome="PASSED")
    if target_state == "VERIFIED":
        return fetch_defect(team, d["id"])
    if target_state == "CLOSED":
        close_defect(team, d)
        return fetch_defect(team, d["id"])
    raise ValueError(f"Unsupported target_state: {target_state!r}")


def fetch_defect(
    team: TeamBundle, defect_id: str,
) -> Dict[str, Any]:
    """Read the current state of a defect via GET /defects/{id}."""
    return get_success_data(
        api_client.get_defect(defect_id, team.triage_headers)
    )


def fetch_module(
    team: TeamBundle, module_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_module(
            team.project["id"], module_id, team.triage_headers,
        )
    )


def fetch_project(
    team: TeamBundle, project_id: Optional[str] = None,
) -> Dict[str, Any]:
    pid = project_id or team.project["id"]
    return get_success_data(
        api_client.get_project(pid, team.triage_headers)
    )


def fetch_team_member(
    team: TeamBundle, team_member_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_team_member(
            team.project["id"], team_member_id, team.triage_headers,
        )
    )


def fetch_severity_override(
    team: TeamBundle, override_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_severity_override(
            override_id, team.triage_headers,
        )
    )


def fetch_regression_run(
    team: TeamBundle, regression_run_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_regression_run(
            regression_run_id, team.triage_headers,
        )
    )


# ===========================================================================
# Severity-override helpers
# ===========================================================================
def request_severity_override(
    team: TeamBundle,
    defect: Dict[str, Any],
    *,
    requested_severity: str,
    requester: Optional[Dict[str, Any]] = None,
    justification: str = "Severity reclassification per business case.",
) -> Dict[str, Any]:
    """A Developer/QAEngineer/TriageManager files a SeverityOverride.
    Caller is identity-threaded to `requester`'s id (defaults to the
    team developer)."""
    actor = requester if requester is not None else team.developer
    role = (actor.get("role") or "DEVELOPER").upper()
    role_builders = {
        "DEVELOPER": make_developer_headers,
        "QA_ENGINEER": make_qa_engineer_headers,
        "TRIAGE_MANAGER": make_triage_manager_headers,
    }
    builder = role_builders.get(role, make_developer_headers)
    return get_success_data(
        api_client.request_severity_override(
            defect["id"],
            severity_override_payload(
                requested_severity=requested_severity,
                justification=justification,
            ),
            builder(actor["id"]),
        )
    )


def approve_severity_override(
    team: TeamBundle,
    override: Dict[str, Any],
    *,
    approver: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """PRD §3.3: approver must be a TriageManager AND independent of
    SeverityOverride.requested_by."""
    approver_member = approver if approver is not None else team.triage
    return get_success_data(
        api_client.approve_severity_override(
            override["id"],
            make_triage_manager_headers(approver_member["id"]),
        )
    )


def reject_severity_override(
    team: TeamBundle,
    override: Dict[str, Any],
    *,
    rejector: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rejector_member = rejector if rejector is not None else team.triage
    return get_success_data(
        api_client.reject_severity_override(
            override["id"],
            make_triage_manager_headers(rejector_member["id"]),
        )
    )


# ===========================================================================
# SLA pause / resume
# ===========================================================================
def pause_sla(
    team: TeamBundle,
    defect: Dict[str, Any],
    *,
    reason: str = "WAITING_ON_REPORTER",
    developer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dev = developer if developer is not None else team.developer
    return get_success_data(
        api_client.pause_sla(
            defect["id"], pause_sla_payload(reason=reason),
            make_developer_headers(dev["id"]),
        )
    )


def resume_sla(
    team: TeamBundle,
    defect: Dict[str, Any],
    *,
    developer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dev = developer if developer is not None else team.developer
    return get_success_data(
        api_client.resume_sla(
            defect["id"], make_developer_headers(dev["id"]),
        )
    )


# ===========================================================================
# Regression runs
# ===========================================================================
def create_regression_run(
    team: TeamBundle,
    defect: Dict[str, Any],
    *,
    impact_scope: Optional[List[str]] = None,
    test_suite_key: str = "smoke",
) -> Dict[str, Any]:
    scope = impact_scope if impact_scope is not None else [
        defect["module_id"],
    ]
    return get_success_data(
        api_client.create_regression_run(
            defect["id"],
            regression_run_payload(
                test_suite_key=test_suite_key, impact_scope=scope,
            ),
            team.release_headers,
        )
    )


def start_regression_run(
    team: TeamBundle, run: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.start_regression_run(
            run["id"], team.release_headers,
        )
    )


def complete_regression_run(
    team: TeamBundle, run: Dict[str, Any], *, result: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_regression_run(
            run["id"],
            regression_complete_payload(result=result),
            team.release_headers,
        )
    )


# ===========================================================================
# Tier 4: Cumulative / threshold targeting
# ===========================================================================
def setup_critical_defect_at_clock_zero(
    *,
    business_impact: str = "REVENUE_BLOCKING",
) -> Tuple[TeamBundle, Dict[str, Any], Dict[str, Any]]:
    """A common preamble for SLA-breach and priority-score tests: a
    CRITICAL defect with priority_score == 70+50+0+0 == 120, multiplier
    1.0, response_due_minute = 60, clock at 0."""
    team, module = setup_basic_module()
    defect = create_defect(
        team, module, severity="CRITICAL",
        business_impact=business_impact,
    )
    return team, module, defect


def setup_module_at_quota_boundary(
    *,
    initial_defect_quota: int = 3,
) -> Tuple[TeamBundle, Dict[str, Any], List[Dict[str, Any]]]:
    """Create a module with quota_remaining == 0 after filling it with
    `initial_defect_quota` defects. Useful for ERR_MODULE_QUOTA_EXCEEDED
    tests (the next defect should fail)."""
    team, module = setup_basic_module(
        initial_defect_quota=initial_defect_quota,
    )
    defects: List[Dict[str, Any]] = []
    for _ in range(initial_defect_quota):
        defects.append(create_defect(team, module))
    return team, module, defects


# ===========================================================================
# Audit listing helpers
# ===========================================================================
def list_audit_entries(
    team: TeamBundle,
    *,
    defect_id: Optional[str] = None,
    event_type: Optional[str] = None,
    from_minute: Optional[int] = None,
    to_minute: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if defect_id is not None:
        params["defect_id"] = defect_id
    if event_type is not None:
        params["event_type"] = event_type
    if from_minute is not None:
        params["from_minute"] = from_minute
    if to_minute is not None:
        params["to_minute"] = to_minute
    resp = api_client.list_audit_entries(team.triage_headers, params=params)
    data, _meta = _paginated(resp)
    return data


# ===========================================================================
# Misc
# ===========================================================================
def _paginated(resp) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Local thin wrapper around validate_paginated to keep error messages
    short. Imported lazily to avoid a top-level coupling."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


__all__ = [
    "TeamBundle",
    "create_project",
    "create_team_member",
    "create_module",
    "advance_clock",
    "run_escalation_sweep",
    "setup_team",
    "setup_basic_module",
    "create_defect",
    "assign_defect",
    "start_progress",
    "submit_fix",
    "latest_fix_record",
    "verify_defect",
    "close_defect",
    "setup_defect_in_state",
    "fetch_defect",
    "fetch_module",
    "fetch_project",
    "fetch_team_member",
    "fetch_severity_override",
    "fetch_regression_run",
    "request_severity_override",
    "approve_severity_override",
    "reject_severity_override",
    "pause_sla",
    "resume_sla",
    "create_regression_run",
    "start_regression_run",
    "complete_regression_run",
    "setup_critical_defect_at_clock_zero",
    "setup_module_at_quota_boundary",
    "list_audit_entries",
]
