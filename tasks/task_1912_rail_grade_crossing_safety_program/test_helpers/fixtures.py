"""Composite setup helpers for multi-step workflows (PRD §3).

Every helper builds preconditions from scratch via PRD-declared endpoints —
each test runs against a freshly restarted server with an empty database.
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_closure_agreement_payload,
    create_crossing_payload,
    create_diagnostic_review_payload,
    create_diagnostic_team_payload,
    create_funding_program_payload,
    create_incident_report_payload,
    create_locality_payload,
    create_maintenance_assignment_payload,
    create_maintenance_work_order_payload,
    create_quiet_zone_application_payload,
    create_upgrade_project_payload,
)
from .test_users import TEST_USERS, make_local_authority_headers, make_officer_headers

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
RAILROAD = TEST_USERS["railroad_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_locality(**overrides):
    """Register a locality. Returns the Locality resource (PRD §3.1)."""
    resp = api_client.create_locality(create_locality_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_team(**overrides):
    """Register a diagnostic team (PRD §3.2)."""
    resp = api_client.create_diagnostic_team(
        create_diagnostic_team_payload(**overrides), ADMIN
    )
    return get_success_data(resp)


def create_crossing(locality_id, **overrides):
    """Register a crossing (PRD §3.1). Returns the Crossing resource."""
    payload = create_crossing_payload(
        road_authority_locality_id=locality_id, **overrides
    )
    resp = api_client.create_crossing(payload, ADMIN)
    return get_success_data(resp)


def create_program(**overrides):
    """Create a funding program (PRD §3.4). Returns the FundingProgram."""
    resp = api_client.create_funding_program(
        create_funding_program_payload(**overrides), ADMIN
    )
    return get_success_data(resp)


def create_project(crossing_id, program_id, **overrides):
    """Propose an upgrade project (PRD §3.4). Returns the UpgradeProject."""
    payload = create_upgrade_project_payload(
        crossing_id=crossing_id, program_id=program_id, **overrides
    )
    resp = api_client.create_upgrade_project(payload, OFFICER)
    return get_success_data(resp)


def nominate_project(project_id):
    """Move a PROPOSED project to ELIGIBLE, pinning priority_score (PRD §3.4)."""
    resp = api_client.transition_upgrade_project(
        project_id, {"to_status": "ELIGIBLE"}, OFFICER
    )
    return get_success_data(resp)


def create_incident(crossing_id, **overrides):
    """File an incident report (PRD §3.3). Returns the IncidentReport."""
    payload = create_incident_report_payload(crossing_id=crossing_id, **overrides)
    resp = api_client.create_incident_report(payload, OFFICER)
    return get_success_data(resp)


def transition_incident(incident_id, to_status):
    resp = api_client.transition_incident_report(
        incident_id, {"to_status": to_status}, OFFICER
    )
    return get_success_data(resp)


def issue_findings(incident_id, findings_summary="findings", functioning=True):
    payload = {
        "findings_summary": findings_summary,
        "warning_devices_functioning": functioning,
    }
    resp = api_client.issue_findings(incident_id, payload, OFFICER)
    return get_success_data(resp)


def create_assignment(crossing_id, **overrides):
    """Create a maintenance responsibility assignment (PRD §3.7)."""
    payload = create_maintenance_assignment_payload(
        crossing_id=crossing_id, **overrides
    )
    resp = api_client.create_maintenance_assignment(payload, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — locality + crossing (+ team)
# ---------------------------------------------------------------------------

def setup_locality_and_crossing(crossing_overrides=None, locality_overrides=None):
    """A registered locality and one ACTIVE crossing on it.

    Returns (locality, crossing).
    """
    locality = create_locality(**(locality_overrides or {}))
    crossing = create_crossing(locality["id"], **(crossing_overrides or {}))
    return locality, crossing


def setup_locality_team_crossing(crossing_overrides=None):
    """A locality, a diagnostic team, and an ACTIVE crossing.

    Returns (locality, team, crossing).
    """
    locality = create_locality()
    team = create_team()
    crossing = create_crossing(locality["id"], **(crossing_overrides or {}))
    return locality, team, crossing


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_accepted_review(crossing_id, team_id, scheduled_date="2026-09-10",
                           recommendations=("UPGRADE_DEVICES",)):
    """Schedule a review and walk it to ACCEPTED (PRD §3.2).

    Returns the ACCEPTED DiagnosticReview.
    """
    review = get_success_data(
        api_client.create_diagnostic_review(
            create_diagnostic_review_payload(
                crossing_id=crossing_id,
                team_id=team_id,
                scheduled_date=scheduled_date,
            ),
            ADMIN,
        )
    )
    get_success_data(
        api_client.transition_diagnostic_review(
            review["id"], {"to_status": "IN_SESSION"}, OFFICER
        )
    )
    get_success_data(
        api_client.issue_recommendations(
            review["id"], {"recommendations": list(recommendations)}, OFFICER
        )
    )
    return get_success_data(
        api_client.transition_diagnostic_review(
            review["id"], {"to_status": "ACCEPTED"}, OFFICER
        )
    )


def create_incident_in_status(crossing_id, target_status, **overrides):
    """Create an incident and walk it to the requested status.

    Supported paths (PRD §3.3):
      SCREENED / FIELD_INVESTIGATION / DESK_REVIEW / FINDINGS_ISSUED
    For FINDINGS_ISSUED the track defaults to DESK_REVIEW unless the severity
    is CASUALTY (which must take FIELD_INVESTIGATION).
    Returns the IncidentReport.
    """
    incident = create_incident(crossing_id, **overrides)
    if target_status == "REPORTED":
        return incident
    transition_incident(incident["id"], "SCREENED")
    if target_status == "SCREENED":
        return get_success_data(api_client.get_incident_report(incident["id"], ADMIN))
    if target_status in ("FIELD_INVESTIGATION", "FINDINGS_ISSUED") and (
        overrides.get("severity") == "CASUALTY" or target_status == "FIELD_INVESTIGATION"
    ):
        transition_incident(incident["id"], "FIELD_INVESTIGATION")
    elif target_status in ("DESK_REVIEW", "FINDINGS_ISSUED"):
        transition_incident(incident["id"], "DESK_REVIEW")
    if target_status == "FINDINGS_ISSUED":
        issue_findings(incident["id"])
    return get_success_data(api_client.get_incident_report(incident["id"], ADMIN))


def create_eligible_project(crossing_id, program_id, **overrides):
    """Create a project and nominate it to ELIGIBLE (PRD §3.4).

    Returns the ELIGIBLE UpgradeProject with priority_score pinned.
    """
    project = create_project(crossing_id, program_id, **overrides)
    return nominate_project(project["id"])


# ---------------------------------------------------------------------------
# Tier 3b: closure agreements
# ---------------------------------------------------------------------------

def create_proposed_agreement(crossing_id, locality_id, closure_type="CLOSURE",
                              creator_user_id="officer-1", **overrides):
    """Create a closure agreement for the DOT and table the opening offer
    (DRAFT -> PROPOSED, negotiation_round 1). Returns the PROPOSED agreement.
    """
    payload = create_closure_agreement_payload(
        crossing_id=crossing_id,
        locality_id=locality_id,
        closure_type=closure_type,
        **overrides,
    )
    creator_headers = make_officer_headers(creator_user_id)
    agreement = get_success_data(
        api_client.create_closure_agreement(payload, creator_headers)
    )
    return get_success_data(
        api_client.transition_closure_agreement(
            agreement["id"], {"to_status": "PROPOSED"}, creator_headers
        )
    )


def create_executed_agreement(crossing_id, locality_id, closure_type="CLOSURE",
                              **overrides):
    """Walk a closure agreement all the way to EXECUTED (PRD §3.5):
    DRAFT -> PROPOSED (officer-1) -> DOT_ACCEPTED (officer-2) ->
    LOCALITY_RATIFIED (owning locality) -> EXECUTED (administrator).

    After execution the crossing is CLOSURE_PENDING. Returns the agreement.
    """
    agreement = create_proposed_agreement(
        crossing_id, locality_id, closure_type, **overrides
    )
    get_success_data(
        api_client.transition_closure_agreement(
            agreement["id"],
            {"to_status": "DOT_ACCEPTED"},
            make_officer_headers("officer-2"),
        )
    )
    get_success_data(
        api_client.transition_closure_agreement(
            agreement["id"],
            {"to_status": "LOCALITY_RATIFIED"},
            make_local_authority_headers(locality_id),
        )
    )
    return get_success_data(
        api_client.transition_closure_agreement(
            agreement["id"], {"to_status": "EXECUTED"}, ADMIN
        )
    )


def setup_closure_pending_crossing(crossing_overrides=None):
    """A crossing moved ACTIVE -> CLOSURE_PENDING via an executed agreement.

    Returns (locality, crossing, agreement) with crossing re-read fresh.
    """
    locality, crossing = setup_locality_and_crossing(crossing_overrides)
    agreement = create_executed_agreement(crossing["id"], locality["id"])
    fresh = get_success_data(api_client.get_crossing(crossing["id"], ADMIN))
    return locality, fresh, agreement


# ---------------------------------------------------------------------------
# Tier 3c: quiet zones
# ---------------------------------------------------------------------------

def create_draft_zone(locality_id, **overrides):
    """Create a DRAFT quiet zone owned by the locality (PRD §3.6)."""
    payload = create_quiet_zone_application_payload(
        locality_id=locality_id, **overrides
    )
    resp = api_client.create_quiet_zone_application(
        payload, make_local_authority_headers(locality_id)
    )
    return get_success_data(resp)


def add_zone_member(qz_id, crossing_id, locality_id, ssm_codes=None):
    """Add a member crossing to an editable zone (PRD §3.6)."""
    payload = {"crossing_id": crossing_id}
    if ssm_codes is not None:
        payload["ssm_codes"] = list(ssm_codes)
    resp = api_client.add_quiet_zone_member(
        qz_id, payload, make_local_authority_headers(locality_id)
    )
    return get_success_data(resp)


def submit_zone(qz_id, locality_id):
    resp = api_client.transition_quiet_zone_application(
        qz_id, {"to_status": "SUBMITTED"}, make_local_authority_headers(locality_id)
    )
    return get_success_data(resp)


def decide_zone(qz_id):
    """SUBMITTED -> UNDER_REVIEW -> decide (PRD §3.6). Returns the decided zone."""
    get_success_data(
        api_client.transition_quiet_zone_application(
            qz_id, {"to_status": "UNDER_REVIEW"}, OFFICER
        )
    )
    return get_success_data(api_client.decide_quiet_zone_application(qz_id, OFFICER))


def create_effective_zone(locality_id, member_specs):
    """Build an EFFECTIVE quiet zone over member crossings that already hold
    ACCEPTED reviews (PRD §3.6). member_specs: list of dicts with
    'crossing_id' and optional 'ssm_codes'.

    Only usable when the pre-SSM or post-SSM risk index comes out <= 40.00
    so the decide step lands APPROVED. Returns (zone, members).
    """
    zone = create_draft_zone(locality_id)
    members = [
        add_zone_member(
            zone["id"],
            spec["crossing_id"],
            locality_id,
            ssm_codes=spec.get("ssm_codes"),
        )
        for spec in member_specs
    ]
    submit_zone(zone["id"], locality_id)
    decided = decide_zone(zone["id"])
    assert decided["status"] == "APPROVED", (
        f"fixture expected APPROVED zone, got {decided['status']}"
    )
    effective = get_success_data(
        api_client.transition_quiet_zone_application(
            zone["id"],
            {"to_status": "EFFECTIVE"},
            make_local_authority_headers(locality_id),
        )
    )
    return effective, members


# ---------------------------------------------------------------------------
# Tier 3d: maintenance work orders
# ---------------------------------------------------------------------------

def create_work_order(crossing_id, headers, **overrides):
    """Plan a maintenance work order (PRD §3.7). Returns the work order."""
    payload = create_maintenance_work_order_payload(
        crossing_id=crossing_id, **overrides
    )
    resp = api_client.create_maintenance_work_order(payload, headers)
    return get_success_data(resp)


def setup_railroad_work_order(crossing_overrides=None, work_order_overrides=None,
                              category="SIGNAL"):
    """Locality + ACTIVE crossing + ACTIVE assignment to RAILROAD + a PLANNED
    railroad work order. Returns (locality, crossing, assignment, work_order).
    """
    locality, crossing = setup_locality_and_crossing(crossing_overrides)
    assignment = create_assignment(
        crossing["id"], category=category, responsible_party="RAILROAD"
    )
    wo = create_work_order(
        crossing["id"],
        TEST_USERS["railroad_headers"],
        category=category,
        **(work_order_overrides or {}),
    )
    return locality, crossing, assignment, wo
