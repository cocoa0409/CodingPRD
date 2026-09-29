"""Composite setup helpers that drive the API through PRD-declared endpoints.

Nothing here asserts behaviour under test; these helpers only build the state a
test needs, using ``get_success_data`` so a setup failure surfaces immediately.

Two reachability facts shape every helper below, and both follow from the PRD:

* A signal can only reach ``ESCALATED`` when its frozen ``escalation_score`` is
  at least 70.00 (PRD §3.2), and the provisional severity reading bands the
  largest score among the incident's ``LINKED`` or ``ESCALATED`` signals while
  activation requires at least one ``ESCALATED`` signal (PRD §3.3). The
  governing score of an activated incident is therefore always at least 70.00,
  so an activated incident is always ``SEV2`` or ``SEV1`` and its
  ``quorum_required`` is always 2 or 3 (PRD §3.5).
* Because the quorum list always starts with ``INCIDENT_LEAD`` and appends
  ``LEGAL_COUNSEL`` for ``SEV1``/``SEV2``, both of those seats must be seated and
  acknowledged before any statement can be submitted for review.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    TEAM_ROLE_TO_USER_ROLE,
    make_comms_lead_headers,
    make_exec_sponsor_headers,
    make_headers,
    make_incident_lead_headers,
    make_legal_counsel_headers,
    make_program_admin_headers,
    make_social_listener_headers,
    make_spokesperson_headers,
)

Scenario = Dict[str, Any]

ADMIN_HEADERS = make_program_admin_headers()

# Reach scores that land an incident on each reachable provisional tier when the
# signal sits on a MEDIA channel with credibility tier A and neutral sentiment:
# 75 * 1.00 + 8 = 83.00 (SEV2) and 88 * 1.00 + 8 = 96.00 (SEV1) (PRD §3.2/§3.3).
TIER_REACH_SCORE = {"SEV2": 75, "SEV1": 88}
TIER_SEVERITY_SCORE = {"SEV2": 83.00, "SEV1": 96.00}

DEFAULT_SEAT_ROLES = [
    "INCIDENT_LEAD",
    "LEGAL_COUNSEL",
    "COMMS_LEAD",
    "SPOKESPERSON",
]

# Roster template. The spokesperson carries current media training and counsel
# sits inside the privilege circle (PRD §3.1).
ROSTER_TEMPLATE = {
    "lead": {"full_name": "Dana Ruiz", "org_title": "VP Operations"},
    "counsel": {
        "full_name": "Nia Fox",
        "org_title": "General Counsel",
        "privilege_cleared": True,
    },
    "comms": {"full_name": "Ivo Berg", "org_title": "Comms Director"},
    "spox": {
        "full_name": "Mara Vance",
        "org_title": "Chief Spokesperson",
        "media_training_status": "CURRENT",
        "media_training_expires_at": "2026-12-01T00:00:00.000Z",
    },
    "listener": {"full_name": "Ray Lund", "org_title": "Social Analyst"},
    "exec": {"full_name": "Tess Okon", "org_title": "Chief Executive"},
}

ROLE_HEADER_BUILDER = {
    "lead": make_incident_lead_headers,
    "counsel": make_legal_counsel_headers,
    "comms": make_comms_lead_headers,
    "spox": make_spokesperson_headers,
    "listener": make_social_listener_headers,
    "exec": make_exec_sponsor_headers,
}

SEAT_TO_ROSTER_KEY = {
    "INCIDENT_LEAD": "lead",
    "LEGAL_COUNSEL": "counsel",
    "COMMS_LEAD": "comms",
    "SPOKESPERSON": "spox",
    "SOCIAL_LISTENER": "listener",
    "EXEC_SPONSOR": "exec",
}


# ---------------------------------------------------------------------------
# Tier 0: single-call primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Reposition the logical clock (PRD §2.4)."""
    return get_success_data(
        api_client.set_clock(f.clock_payload(to_iso8601), headers or ADMIN_HEADERS)
    )


def register_member(
    headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Register one roster member (PRD §3.1)."""
    return get_success_data(
        api_client.create_team_member(
            f.team_member_payload(**overrides), headers or ADMIN_HEADERS
        )
    )


def register_channel(
    headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Register one monitored channel (PRD §3.1)."""
    return get_success_data(
        api_client.create_monitored_channel(
            f.monitored_channel_payload(**overrides), headers or ADMIN_HEADERS
        )
    )


def verify_channel_path(
    channel_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Verify a channel's trust-and-safety escalation path (PRD §3.1)."""
    return get_success_data(
        api_client.verify_escalation_path(
            channel_id,
            f.verify_escalation_path_payload(**overrides),
            headers or ADMIN_HEADERS,
        )
    )


def file_material(
    headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """File one prepared material in DRAFT (PRD §3.1)."""
    return get_success_data(
        api_client.create_prepared_material(
            f.prepared_material_payload(**overrides), headers or ADMIN_HEADERS
        )
    )


def review_material(
    material_id: str, comms_headers: Dict[str, str], **overrides: Any
) -> Dict[str, Any]:
    """Record a content review, restarting the readiness curve (PRD §3.1)."""
    return get_success_data(
        api_client.review_prepared_material(
            material_id, f.material_review_payload(**overrides), comms_headers
        )
    )


def record_signal(
    channel_id: str, listener_headers: Dict[str, str], **overrides: Any
) -> Dict[str, Any]:
    """Record an issue signal, freezing its escalation score (PRD §3.2)."""
    return get_success_data(
        api_client.create_issue_signal(
            f.issue_signal_payload(channel_id, **overrides), listener_headers
        )
    )


def link_signal(
    signal_id: str, incident_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    """Attach an OPEN signal to an incident (PRD §3.2)."""
    return get_success_data(
        api_client.link_issue_signal(signal_id, f.link_signal_payload(incident_id), headers)
    )


def escalate_signal(signal_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """Escalate a linked signal above the 70.00 threshold (PRD §3.2)."""
    return get_success_data(api_client.escalate_issue_signal(signal_id, headers))


def open_incident(lead_headers: Dict[str, str], **overrides: Any) -> Dict[str, Any]:
    """Open an incident file in MONITORING (PRD §3.3)."""
    return get_success_data(
        api_client.create_incident(f.incident_payload(**overrides), lead_headers)
    )


def seat_member(
    incident_id: str,
    member_id: str,
    team_role: str,
    lead_headers: Dict[str, str],
    decision_authority: str = "FULL",
    acknowledge: bool = True,
    member_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Seat a member in a crisis-team role and, by default, have that member
    acknowledge the seat (PRD §3.3)."""
    assignment = get_success_data(
        api_client.create_team_assignment(
            f.team_assignment_payload(
                incident_id, member_id, team_role, decision_authority
            ),
            lead_headers,
        )
    )
    if acknowledge:
        headers = member_headers or make_headers(
            TEAM_ROLE_TO_USER_ROLE[team_role], member_id
        )
        assignment = get_success_data(
            api_client.acknowledge_team_assignment(assignment["id"], headers)
        )
    return assignment


# ---------------------------------------------------------------------------
# Read-back helpers (every GET admits ProgramAdmin, PRD §4)
# ---------------------------------------------------------------------------


def read_incident(incident_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current incident row with every derived field (PRD §4)."""
    return get_success_data(api_client.get_incident(incident_id, headers or ADMIN_HEADERS))


def read_channel(channel_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current monitored-channel row."""
    return get_success_data(
        api_client.get_monitored_channel(channel_id, headers or ADMIN_HEADERS)
    )


def read_member(member_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current roster-member row."""
    return get_success_data(api_client.get_team_member(member_id, headers or ADMIN_HEADERS))


def read_signal(signal_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current issue-signal row."""
    return get_success_data(api_client.get_issue_signal(signal_id, headers or ADMIN_HEADERS))


def read_assignment(assignment_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current crisis-team seat row."""
    return get_success_data(
        api_client.get_team_assignment(assignment_id, headers or ADMIN_HEADERS)
    )


def read_statement(statement_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current statement row with its review ledger."""
    return get_success_data(api_client.get_statement(statement_id, headers or ADMIN_HEADERS))


def read_task(task_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current approval-task row."""
    return get_success_data(api_client.get_approval_task(task_id, headers or ADMIN_HEADERS))


def read_notice(notice_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current stakeholder-notice row."""
    return get_success_data(
        api_client.get_stakeholder_notice(notice_id, headers or ADMIN_HEADERS)
    )


def read_material(material_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current prepared-material row with its decayed readiness score."""
    return get_success_data(
        api_client.get_prepared_material(material_id, headers or ADMIN_HEADERS)
    )


def read_interview(interview_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current media-interview row."""
    return get_success_data(
        api_client.get_media_interview(interview_id, headers or ADMIN_HEADERS)
    )


def read_claim(claim_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current misinformation-claim row."""
    return get_success_data(
        api_client.get_misinformation_claim(claim_id, headers or ADMIN_HEADERS)
    )


def read_review(review_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Current post-crisis-review row."""
    return get_success_data(
        api_client.get_post_crisis_review(review_id, headers or ADMIN_HEADERS)
    )


def list_rows(
    endpoint: str,
    headers: Optional[Dict[str, str]] = None,
    **params: Any,
) -> List[Dict[str, Any]]:
    """List one collection with filters, returning just the row list.

    ``endpoint`` names the collection method on the client, for example
    ``"list_approval_tasks"``.
    """
    method = getattr(api_client, endpoint)
    response = method(headers or ADMIN_HEADERS, params or None)
    return get_success_data(response)


def tasks_for_statement(
    statement_id: str, headers: Optional[Dict[str, str]] = None, **params: Any
) -> List[Dict[str, Any]]:
    """Approval tasks guarding a statement, in pinned creation order (PRD §3.5)."""
    return list_rows(
        "list_approval_tasks", headers, statement_id=statement_id, **params
    )


def notices_for_incident(
    incident_id: str, headers: Optional[Dict[str, str]] = None, **params: Any
) -> List[Dict[str, Any]]:
    """Stakeholder notices on an incident (PRD §2.5)."""
    return list_rows(
        "list_stakeholder_notices", headers, incident_id=incident_id, **params
    )


def review_for_incident(
    incident_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """The post-crisis review opened by resolution (PRD §3.9)."""
    rows = list_rows("list_post_crisis_reviews", headers, incident_id=incident_id)
    assert len(rows) == 1, f"expected one post-crisis review, found {len(rows)}"
    return rows[0]


def incident_version(incident_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """The incident's current ``version``, for ``expected_incident_version``
    (PRD §2.8)."""
    return read_incident(incident_id, headers)["version"]


def channel_version(channel_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """The channel's current ``version``, for ``expected_channel_version``
    (PRD §2.8)."""
    return read_channel(channel_id, headers)["version"]


# ---------------------------------------------------------------------------
# Tier 1: the standing roster
# ---------------------------------------------------------------------------


def seed_roster(**per_member_overrides: Dict[str, Any]) -> Scenario:
    """Register the six-person crisis roster and build one header set per person.

    ``per_member_overrides`` varies one member's registration payload, e.g.
    ``seed_roster(spox={"media_training_status": "NONE"})``.

    Returns a scenario dict with a ``members`` map keyed
    ``lead/counsel/comms/spox/listener/exec``, a matching ``headers`` map that
    also carries ``admin``, and an ``ids`` map of member ids.
    """
    members: Dict[str, Any] = {}
    headers: Dict[str, Dict[str, str]] = {"admin": ADMIN_HEADERS}
    for key, template in ROSTER_TEMPLATE.items():
        payload = dict(template)
        payload.update(per_member_overrides.get(key, {}))
        member = register_member(**payload)
        members[key] = member
        headers[key] = ROLE_HEADER_BUILDER[key](member["id"])
    return {
        "members": members,
        "headers": headers,
        "ids": {key: member["id"] for key, member in members.items()},
    }


def headers_for_member(scenario: Scenario, member_id: str, team_role: str) -> Dict[str, str]:
    """Headers that let ``member_id`` act in the request role belonging to
    ``team_role`` (PRD §2.1)."""
    return make_headers(TEAM_ROLE_TO_USER_ROLE[team_role], member_id)


# ---------------------------------------------------------------------------
# Tier 2: incident state progression
# ---------------------------------------------------------------------------


def setup_monitoring_incident(
    clock: Optional[str] = None,
    scenario_code: str = "PRODUCT_RECALL",
    channel_type: str = "MEDIA",
    roster: Optional[Scenario] = None,
    **incident_overrides: Any,
) -> Scenario:
    """Roster, one monitored channel and one incident in MONITORING (PRD §3.3)."""
    if clock is not None:
        set_clock(clock)
    scenario = roster or seed_roster()
    scenario["channel"] = register_channel(channel_type=channel_type)
    scenario["incident"] = open_incident(
        scenario["headers"]["lead"], scenario_code=scenario_code, **incident_overrides
    )
    return scenario


def setup_activated_incident(
    tier: str = "SEV2",
    clock: Optional[str] = None,
    scenario_code: str = "PRODUCT_RECALL",
    channel_type: str = "MEDIA",
    seat_roles: Optional[List[str]] = None,
    roster: Optional[Scenario] = None,
    **incident_overrides: Any,
) -> Scenario:
    """An ACTIVATED incident on the requested provisional tier (PRD §3.3).

    One signal is recorded, linked and escalated, the requested seats are seated
    and acknowledged, and the incident is activated. ``tier`` may be ``"SEV2"``
    (governing score 83.00) or ``"SEV1"`` (96.00); those are the only tiers an
    activated incident can carry, because activation requires an escalated
    signal and escalation requires a score of at least 70.00.

    Adds ``signal``, ``assignments`` and the refreshed ``incident`` to the
    scenario dict.
    """
    assert tier in TIER_REACH_SCORE, (
        f"provisional tier {tier} is unreachable: an activated incident's "
        "governing score is always at least 70.00"
    )
    scenario = setup_monitoring_incident(
        clock=clock,
        scenario_code=scenario_code,
        channel_type=channel_type,
        roster=roster,
        **incident_overrides,
    )
    incident_id = scenario["incident"]["id"]
    scenario["signal"] = record_signal(
        scenario["channel"]["id"],
        scenario["headers"]["listener"],
        reach_score=TIER_REACH_SCORE[tier],
    )
    link_signal(scenario["signal"]["id"], incident_id, scenario["headers"]["listener"])
    scenario["signal"] = escalate_signal(
        scenario["signal"]["id"], scenario["headers"]["listener"]
    )

    roles = list(seat_roles if seat_roles is not None else DEFAULT_SEAT_ROLES)
    if tier == "SEV1" and "EXEC_SPONSOR" not in roles:
        roles.append("EXEC_SPONSOR")
    scenario["assignments"] = {}
    for team_role in roles:
        key = SEAT_TO_ROSTER_KEY[team_role]
        scenario["assignments"][team_role] = seat_member(
            incident_id,
            scenario["ids"][key],
            team_role,
            scenario["headers"]["lead"],
            member_headers=scenario["headers"][key],
        )

    scenario["incident"] = get_success_data(
        api_client.activate_incident(incident_id, scenario["headers"]["lead"])
    )
    return scenario


def refresh(scenario: Scenario) -> Dict[str, Any]:
    """Re-read the scenario's incident and store it back on the scenario."""
    scenario["incident"] = read_incident(scenario["incident"]["id"])
    return scenario["incident"]


# ---------------------------------------------------------------------------
# Tier 3: statement lifecycle shortcuts (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------


def draft_statement(
    scenario: Scenario,
    statement_type: str = "HOLDING",
    drafter: str = "comms",
    expected_incident_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a statement against the scenario's activated incident (PRD §3.5).

    ``expected_incident_version`` defaults to a freshly read incident version so
    the optimistic-concurrency check passes.
    """
    incident_id = scenario["incident"]["id"]
    version = (
        expected_incident_version
        if expected_incident_version is not None
        else incident_version(incident_id)
    )
    statement = get_success_data(
        api_client.create_statement(
            f.statement_payload(
                incident_id, version, statement_type=statement_type, **overrides
            ),
            scenario["headers"][drafter],
        )
    )
    scenario["statement"] = statement
    return statement


def submit_for_review(
    scenario: Scenario, statement_id: Optional[str] = None
) -> Dict[str, Any]:
    """Submit a statement for review, fanning out the quorum tasks (PRD §3.5)."""
    target = statement_id or scenario["statement"]["id"]
    statement = get_success_data(
        api_client.submit_statement_review(target, scenario["headers"]["comms"])
    )
    if target == scenario.get("statement", {}).get("id"):
        scenario["statement"] = statement
    scenario["tasks"] = tasks_for_statement(target)
    return statement


def decide_task(
    task: Dict[str, Any],
    decision: str = "APPROVE",
    decision_comment: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a decision as the task's own assignee, in the request role
    belonging to the task's ``required_team_role`` (PRD §3.5)."""
    headers = make_headers(
        TEAM_ROLE_TO_USER_ROLE[task["required_team_role"]], task["assignee_member_id"]
    )
    return get_success_data(
        api_client.decide_approval_task(
            task["id"], f.decide_payload(decision, decision_comment), headers
        )
    )


def approve_to_quorum(
    scenario: Scenario, statement_id: Optional[str] = None
) -> Dict[str, Any]:
    """Approve every PENDING task of the current round, in pinned order, until
    the statement reaches APPROVED (PRD §3.5)."""
    target = statement_id or scenario["statement"]["id"]
    for task in tasks_for_statement(target, state="PENDING"):
        decide_task(task, "APPROVE")
    statement = read_statement(target)
    if target == scenario.get("statement", {}).get("id"):
        scenario["statement"] = statement
    return statement


def publish_statement(
    scenario: Scenario, statement_id: Optional[str] = None, publisher: str = "comms"
) -> Dict[str, Any]:
    """Publish an APPROVED statement (PRD §3.6)."""
    target = statement_id or scenario["statement"]["id"]
    statement = get_success_data(
        api_client.publish_statement(target, scenario["headers"][publisher])
    )
    if target == scenario.get("statement", {}).get("id"):
        scenario["statement"] = statement
    return statement


def setup_statement_in_review(
    scenario: Optional[Scenario] = None,
    statement_type: str = "HOLDING",
    tier: str = "SEV2",
    clock: Optional[str] = None,
    **statement_overrides: Any,
) -> Scenario:
    """An activated incident carrying one statement in IN_REVIEW, with its
    approval tasks listed on ``scenario["tasks"]`` (PRD §3.5)."""
    scenario = scenario or setup_activated_incident(tier=tier, clock=clock)
    draft_statement(scenario, statement_type=statement_type, **statement_overrides)
    submit_for_review(scenario)
    return scenario


def setup_approved_statement(
    scenario: Optional[Scenario] = None,
    statement_type: str = "HOLDING",
    tier: str = "SEV2",
    clock: Optional[str] = None,
    **statement_overrides: Any,
) -> Scenario:
    """An activated incident carrying one APPROVED statement (PRD §3.5)."""
    scenario = setup_statement_in_review(
        scenario, statement_type=statement_type, tier=tier, clock=clock,
        **statement_overrides,
    )
    approve_to_quorum(scenario)
    return scenario


def setup_published_statement(
    scenario: Optional[Scenario] = None,
    statement_type: str = "HOLDING",
    tier: str = "SEV2",
    clock: Optional[str] = None,
    **statement_overrides: Any,
) -> Scenario:
    """An activated incident carrying one PUBLISHED statement (PRD §3.6)."""
    scenario = setup_approved_statement(
        scenario, statement_type=statement_type, tier=tier, clock=clock,
        **statement_overrides,
    )
    publish_statement(scenario)
    return scenario


def add_published_statement(
    scenario: Scenario, statement_type: str = "CORRECTION", **statement_overrides: Any
) -> Dict[str, Any]:
    """Draft, approve and publish one more statement on an existing activated
    incident, leaving ``scenario["statement"]`` pointing at it (PRD §3.5/§3.6)."""
    draft_statement(scenario, statement_type=statement_type, **statement_overrides)
    submit_for_review(scenario)
    approve_to_quorum(scenario)
    return publish_statement(scenario)


# ---------------------------------------------------------------------------
# Tier 4: notices, interviews and claims (PRD §3.6, §3.7, §3.8)
# ---------------------------------------------------------------------------


def queue_notice(
    scenario: Scenario,
    audience: str = "EMPLOYEE",
    estimated_reach: int = 1000,
    statement_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Queue one stakeholder notice carrying a statement (PRD §3.6)."""
    notice = get_success_data(
        api_client.create_stakeholder_notice(
            f.stakeholder_notice_payload(
                scenario["incident"]["id"],
                statement_id or scenario["statement"]["id"],
                audience=audience,
                estimated_reach=estimated_reach,
                **overrides,
            ),
            scenario["headers"]["comms"],
        )
    )
    scenario.setdefault("notices", {})[audience] = notice
    return notice


def release_notice(
    scenario: Scenario,
    notice_id: str,
    releaser: str = "comms",
    **overrides: Any,
) -> Dict[str, Any]:
    """Release a queued notice (PRD §3.6)."""
    return get_success_data(
        api_client.release_stakeholder_notice(
            notice_id,
            scenario["headers"][releaser],
            f.release_notice_payload(**overrides),
        )
    )


def cancel_notice(
    scenario: Scenario, notice_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Cancel a queued or blocked notice (PRD §3.6)."""
    return get_success_data(
        api_client.cancel_stakeholder_notice(
            notice_id, f.cancel_notice_payload(**overrides), scenario["headers"]["comms"]
        )
    )


def book_interview(
    scenario: Scenario,
    scheduled_start_at: str,
    scheduled_end_at: str,
    anticipated_question_count: int = 8,
    **overrides: Any,
) -> Dict[str, Any]:
    """Book one media interview for the scenario's spokesperson (PRD §3.7)."""
    interview = get_success_data(
        api_client.create_media_interview(
            f.media_interview_payload(
                scenario["incident"]["id"],
                scenario["ids"]["spox"],
                scenario["channel"]["id"],
                scheduled_start_at,
                scheduled_end_at,
                anticipated_question_count=anticipated_question_count,
                **overrides,
            ),
            scenario["headers"]["comms"],
        )
    )
    scenario["interview"] = interview
    return interview


def confirm_interview(
    scenario: Scenario,
    interview_id: Optional[str] = None,
    high_risk_answers_approved_count: int = 3,
) -> Dict[str, Any]:
    """Confirm a booking, charging the spokesperson-load ledger (PRD §3.7)."""
    target = interview_id or scenario["interview"]["id"]
    interview = get_success_data(
        api_client.confirm_media_interview(
            target,
            scenario["headers"]["comms"],
            f.confirm_interview_payload(high_risk_answers_approved_count),
        )
    )
    if target == scenario.get("interview", {}).get("id"):
        scenario["interview"] = interview
    return interview


def setup_confirmed_interview(
    scenario: Optional[Scenario] = None,
    scheduled_start_at: str = "2026-08-12T14:00:00Z",
    scheduled_end_at: str = "2026-08-12T15:00:00Z",
    tier: str = "SEV2",
    clock: Optional[str] = None,
) -> Scenario:
    """An activated incident with one CONFIRMED interview (PRD §3.7)."""
    scenario = scenario or setup_activated_incident(tier=tier, clock=clock)
    book_interview(scenario, scheduled_start_at, scheduled_end_at)
    confirm_interview(scenario)
    return scenario


def log_claim(
    scenario: Scenario,
    virality_score: float = 60.00,
    channel_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Log one misinformation claim in DETECTED (PRD §3.8)."""
    claim = get_success_data(
        api_client.create_misinformation_claim(
            f.misinformation_claim_payload(
                scenario["incident"]["id"],
                channel_id or scenario["channel"]["id"],
                virality_score=virality_score,
                **overrides,
            ),
            scenario["headers"]["listener"],
        )
    )
    scenario["claim"] = claim
    return claim


def triage_claim(scenario: Scenario, claim_id: Optional[str] = None) -> Dict[str, Any]:
    """Advance a claim DETECTED to TRIAGED (PRD §3.8)."""
    target = claim_id or scenario["claim"]["id"]
    claim = get_success_data(
        api_client.triage_misinformation_claim(target, scenario["headers"]["listener"])
    )
    if target == scenario.get("claim", {}).get("id"):
        scenario["claim"] = claim
    return claim


def setup_triaged_claim(
    scenario: Optional[Scenario] = None,
    virality_score: float = 60.00,
    tier: str = "SEV2",
    clock: Optional[str] = None,
) -> Scenario:
    """An activated incident with one TRIAGED claim (PRD §3.8)."""
    scenario = scenario or setup_activated_incident(tier=tier, clock=clock)
    log_claim(scenario, virality_score=virality_score)
    triage_claim(scenario)
    return scenario


def issue_correction(
    scenario: Scenario,
    correction_window_start: str,
    correction_window_end: str,
    claim_id: Optional[str] = None,
    correction_statement_id: Optional[str] = None,
    expected_channel_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Take the correction fork against a published CORRECTION statement, under
    channel optimistic concurrency (PRD §3.8)."""
    target = claim_id or scenario["claim"]["id"]
    version = (
        expected_channel_version
        if expected_channel_version is not None
        else channel_version(scenario["channel"]["id"])
    )
    claim = get_success_data(
        api_client.issue_correction(
            target,
            f.issue_correction_payload(
                correction_statement_id or scenario["statement"]["id"],
                correction_window_start,
                correction_window_end,
                version,
            ),
            scenario["headers"]["comms"],
        )
    )
    if target == scenario.get("claim", {}).get("id"):
        scenario["claim"] = claim
    return claim


def escalate_claim_to_platform(
    scenario: Scenario, claim_id: Optional[str] = None
) -> Dict[str, Any]:
    """Take the platform fork through the channel's verified path (PRD §3.8)."""
    target = claim_id or scenario["claim"]["id"]
    claim = get_success_data(
        api_client.escalate_platform(target, scenario["headers"]["listener"])
    )
    if target == scenario.get("claim", {}).get("id"):
        scenario["claim"] = claim
    return claim


def close_claim(
    scenario: Scenario, claim_id: Optional[str] = None, actor: str = "comms", **overrides: Any
) -> Dict[str, Any]:
    """Close a claim on either fork (PRD §3.8)."""
    target = claim_id or scenario["claim"]["id"]
    claim = get_success_data(
        api_client.close_misinformation_claim(
            target, f.close_claim_payload(**overrides), scenario["headers"][actor]
        )
    )
    if target == scenario.get("claim", {}).get("id"):
        scenario["claim"] = claim
    return claim


# ---------------------------------------------------------------------------
# Tier 5: finalisation and terminal states (PRD §3.4, §3.9)
# ---------------------------------------------------------------------------


def assert_privilege(
    scenario: Scenario, incident_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Assert privilege as the scenario's seated, cleared counsel (PRD §3.4)."""
    target = incident_id or scenario["incident"]["id"]
    incident = get_success_data(
        api_client.assert_privilege(
            target, f.assert_privilege_payload(**overrides), scenario["headers"]["counsel"]
        )
    )
    scenario["incident"] = incident
    return incident


def waive_privilege(
    scenario: Scenario, incident_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Waive privilege and release the legal hold (PRD §3.4)."""
    target = incident_id or scenario["incident"]["id"]
    incident = get_success_data(
        api_client.waive_privilege(
            target, scenario["headers"]["counsel"], f.waive_privilege_payload(**overrides)
        )
    )
    scenario["incident"] = incident
    return incident


def run_sla_sweep(
    scenario: Scenario, incident_id: Optional[str] = None, actor: str = "admin"
) -> Dict[str, Any]:
    """Run the operator checkpoint for one incident (PRD §3.3)."""
    target = incident_id or scenario["incident"]["id"]
    incident = get_success_data(
        api_client.sla_sweep(target, scenario["headers"][actor])
    )
    scenario["incident"] = incident
    return incident


def resolve_incident(
    scenario: Scenario,
    reputation_index_after: float = 42.70,
    incident_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the incident, opening the retrospective (PRD §3.9)."""
    target = incident_id or scenario["incident"]["id"]
    incident = get_success_data(
        api_client.resolve_incident(
            target,
            scenario["headers"]["lead"],
            f.resolve_incident_payload(reputation_index_after),
        )
    )
    scenario["incident"] = incident
    scenario["review"] = review_for_incident(target)
    return incident


def score_review(
    scenario: Scenario,
    scoring_method: str = "ADJUSTED",
    playbook_update_count: int = 2,
    review_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Score the retrospective as the executive sponsor (PRD §3.9)."""
    target = review_id or scenario["review"]["id"]
    review = get_success_data(
        api_client.score_post_crisis_review(
            target,
            f.score_review_payload(scoring_method, playbook_update_count),
            scenario["headers"]["exec"],
        )
    )
    scenario["review"] = review
    return review


def setup_open_review(
    scenario: Optional[Scenario] = None,
    reputation_index_after: float = 42.70,
    tier: str = "SEV2",
    clock: Optional[str] = None,
    **incident_overrides: Any,
) -> Scenario:
    """A RESOLVED incident whose post-crisis review sits in OPEN (PRD §3.9)."""
    scenario = scenario or setup_activated_incident(
        tier=tier, clock=clock, **incident_overrides
    )
    resolve_incident(scenario, reputation_index_after=reputation_index_after)
    return scenario
