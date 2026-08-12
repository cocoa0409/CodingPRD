"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
and use get_success_data() so a setup failure surfaces as a clear error rather
than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_capa_action_payload,
    create_collector_payload,
    create_dha_payload,
    create_dust_sample_payload,
    create_hot_work_permit_payload,
    create_housekeeping_audit_payload,
    create_housekeeping_program_payload,
    create_incident_payload,
    create_inspection_finding_payload,
    create_inspection_payload,
    create_line_item_payload,
    create_retrofit_project_payload,
    create_site_payload,
)
from .test_users import (
    AUDITOR_USER_ID,
    ENGINEER_USER_ID,
    INSPECTOR_USER_ID,
    INVESTIGATOR_USER_ID,
    PERFORMER_USER_ID,
    SAFETY_USER_ID,
    TEST_USERS,
    make_compliance_engineer_headers,
    make_hot_work_performer_headers,
    make_housekeeping_auditor_headers,
    make_incident_investigator_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["compliance_manager_headers"]
ENGINEER = TEST_USERS["compliance_engineer_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]
INSPECTOR = TEST_USERS["inspector_user_headers"]
INVESTIGATOR = TEST_USERS["incident_investigator_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.11)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-entity creation ───────────────────

def create_site(insurer_id: str = "FM-001", **overrides):
    """Create a Site. Returns the Site dict (born CONDITIONAL, counters zero)."""
    res = api_client.create_site(
        create_site_payload(insurer_id=insurer_id, **overrides), ADMIN)
    return get_success_data(res)


def create_dust_sample(site_id: str, **overrides):
    """Register a DustSample at a site. Returns the DustSample dict."""
    res = api_client.create_dust_sample(
        site_id, create_dust_sample_payload(**overrides), ENGINEER)
    return get_success_data(res)


def create_collector(site_id: str, dust_sample_id: str, **overrides):
    """Register a Collector in DRAFT. Returns the Collector dict."""
    res = api_client.create_collector(
        site_id, create_collector_payload(dust_sample_id, **overrides), ENGINEER)
    return get_success_data(res)


def create_dha(site_id: str, author_id: str = ENGINEER_USER_ID, **overrides):
    """Author a DHA (starts DRAFT). Returns the DHA dict."""
    res = api_client.create_dha(site_id, create_dha_payload(author_id, **overrides),
                                ENGINEER)
    return get_success_data(res)


def create_inspection(site_id: str, **overrides):
    """File an Inspection (starts OPEN). Returns the Inspection dict."""
    res = api_client.create_inspection(site_id, create_inspection_payload(**overrides),
                                       INSPECTOR)
    return get_success_data(res)


def create_finding(site_id: str, inspection_id: str, severity: str = "CRITICAL",
                   collector_id=None, **overrides):
    """Add a finding to an inspection. Returns the InspectionFinding dict."""
    payload = create_inspection_finding_payload(severity=severity, **overrides)
    if collector_id is not None:
        payload["collector_id"] = collector_id
    res = api_client.create_inspection_finding(site_id, inspection_id, payload,
                                               INSPECTOR)
    return get_success_data(res)


def create_housekeeping_program(site_id: str, **overrides):
    """Create a HousekeepingProgram. Returns the program dict."""
    res = api_client.create_housekeeping_program(
        site_id, create_housekeeping_program_payload(**overrides), ENGINEER)
    return get_success_data(res)


def create_audit(site_id: str, program_id: str, scheduled_for: str,
                 auditor_id: str = AUDITOR_USER_ID, **overrides):
    """Schedule a HousekeepingAudit (starts SCHEDULED). Returns the audit dict."""
    res = api_client.create_housekeeping_audit(
        site_id, program_id,
        create_housekeeping_audit_payload(auditor_id, scheduled_for, **overrides),
        make_housekeeping_auditor_headers(auditor_id))
    return get_success_data(res)


def create_permit(site_id: str, valid_from: str, valid_to: str,
                  issuer_id: str = SAFETY_USER_ID,
                  performer_id: str = PERFORMER_USER_ID,
                  fire_watch_minutes_after: int = 30,
                  collector_id=None, **overrides):
    """Issue a HotWorkPermit (starts ISSUED). Returns the permit dict."""
    payload = create_hot_work_permit_payload(
        issuer_id, performer_id, valid_from, valid_to,
        fire_watch_minutes_after=fire_watch_minutes_after, **overrides)
    if collector_id is not None:
        payload["collector_id"] = collector_id
    res = api_client.create_hot_work_permit(site_id, payload, SAFETY)
    return get_success_data(res)


def create_incident(site_id: str,
                    investigation_lead_id: str = INVESTIGATOR_USER_ID, **overrides):
    """Declare an Incident (starts OPEN). Returns the Incident dict."""
    res = api_client.create_incident(
        site_id, create_incident_payload(investigation_lead_id, **overrides), MANAGER)
    return get_success_data(res)


def create_capa(site_id: str, incident_id: str,
                owner_id: str = INVESTIGATOR_USER_ID, **overrides):
    """Author a CAPA action on an incident (starts OPEN). Returns the action."""
    res = api_client.create_capa_action(
        site_id, incident_id, create_capa_action_payload(owner_id, **overrides),
        INVESTIGATOR)
    return get_success_data(res)


# ─── Tier 2: entity hierarchy ─────────────────────────

def setup_site_with_dust(insurer_id: str = "FM-001", **sample_overrides):
    """Site + one DustSample. Returns (site, sample)."""
    site = create_site(insurer_id=insurer_id)
    sample = create_dust_sample(site["id"], **sample_overrides)
    return site, sample


def setup_site_with_collector(installed_vent_area_m2: float = 500,
                              insurer_id: str = "FM-001",
                              sample_overrides=None, collector_overrides=None):
    """Site + DustSample + DRAFT Collector. Returns (site, sample, collector)."""
    site, sample = setup_site_with_dust(insurer_id=insurer_id,
                                        **(sample_overrides or {}))
    overrides = dict(collector_overrides or {})
    overrides.setdefault("installed_vent_area_m2", installed_vent_area_m2)
    collector = create_collector(site["id"], sample["id"], **overrides)
    return site, sample, collector


def setup_inspection_with_finding(severity: str = "CRITICAL",
                                  insurer_id: str = "FM-001"):
    """Site + Inspection + one finding. Returns (site, inspection, finding)."""
    site = create_site(insurer_id=insurer_id)
    inspection = create_inspection(site["id"])
    finding = create_finding(site["id"], inspection["id"], severity=severity)
    return site, inspection, finding


# ─── Tier 3: full lifecycle shortcuts ─────────────────

def commission_collector(site_id: str, collector_id: str):
    """Commission a DRAFT collector. Returns the IN_SERVICE collector."""
    return get_success_data(
        api_client.commission_collector(site_id, collector_id, ENGINEER))


def create_commissioned_collector(site_id: str, dust_sample_id: str, **overrides):
    """Create + commission a collector. Returns the IN_SERVICE collector."""
    collector = create_collector(site_id, dust_sample_id, **overrides)
    return commission_collector(site_id, collector["id"])


def setup_site_with_in_service_collector(installed_vent_area_m2: float = 500,
                                         insurer_id: str = "FM-001"):
    """Site + combustible sample + IN_SERVICE collector.
    Returns (site, sample, collector)."""
    site, sample, collector = setup_site_with_collector(
        installed_vent_area_m2=installed_vent_area_m2, insurer_id=insurer_id)
    collector = commission_collector(site["id"], collector["id"])
    return site, sample, collector


def create_dha_with_linked_sample(site_id: str, sample_id: str,
                                  author_id: str = ENGINEER_USER_ID):
    """DRAFT DHA with one dust sample linked. Returns the DHA dict."""
    dha = create_dha(site_id, author_id=author_id)
    get_success_data(api_client.link_dha_sample(site_id, dha["id"], sample_id,
                                                ENGINEER))
    return get_success_data(api_client.get_dha(site_id, dha["id"], ENGINEER))


def create_submitted_dha(site_id: str, sample_id: str,
                         author_id: str = ENGINEER_USER_ID):
    """DRAFT DHA + link sample + submit (acting user equals author_id).
    Returns the SUBMITTED DHA dict."""
    dha = create_dha_with_linked_sample(site_id, sample_id, author_id=author_id)
    res = api_client.submit_dha(site_id, dha["id"],
                                make_compliance_engineer_headers(author_id))
    return get_success_data(res)


def create_started_permit(site_id: str, valid_from: str, valid_to: str,
                          performer_id: str = PERFORMER_USER_ID, **overrides):
    """Issue + start a permit. Caller must set the clock inside the window first.
    Returns the IN_PROGRESS permit."""
    permit = create_permit(site_id, valid_from, valid_to,
                           performer_id=performer_id, **overrides)
    res = api_client.start_hot_work_permit(
        site_id, permit["id"], make_hot_work_performer_headers(performer_id))
    return get_success_data(res)


def create_closed_incident(site_id: str,
                           lead_id: str = INVESTIGATOR_USER_ID, **overrides):
    """Drive an incident OPEN → INVESTIGATING → CAPA_DEFINED → CLOSED with one
    closed CAPA action. Returns the CLOSED incident dict."""
    incident = create_incident(site_id, investigation_lead_id=lead_id, **overrides)
    lead_headers = make_incident_investigator_headers(lead_id)
    get_success_data(api_client.start_investigation(site_id, incident["id"],
                                                    lead_headers))
    capa = create_capa(site_id, incident["id"], owner_id=lead_id)
    get_success_data(api_client.start_capa_action(site_id, incident["id"],
                                                  capa["id"], lead_headers))
    get_success_data(api_client.close_capa_action(site_id, incident["id"],
                                                  capa["id"], lead_headers))
    get_success_data(api_client.define_capa(site_id, incident["id"], lead_headers))
    res = api_client.close_incident(site_id, incident["id"], MANAGER)
    return get_success_data(res)


# ─── Tier 4: accumulation / threshold targeting ───────

def setup_site_in_stop_work(insurer_id: str = "FM-001"):
    """Site driven to STOP_WORK via two OPEN CRITICAL findings
    (2 or more open critical findings force STOP_WORK per PRD §2.4).
    Returns (site, inspection, [finding1, finding2])."""
    site = create_site(insurer_id=insurer_id)
    inspection = create_inspection(site["id"])
    f1 = create_finding(site["id"], inspection["id"], severity="CRITICAL",
                        description="critical 1")
    f2 = create_finding(site["id"], inspection["id"], severity="CRITICAL",
                        description="critical 2")
    get_success_data(api_client.recompute_posture(site["id"], ADMIN))
    return site, inspection, [f1, f2]


def create_retrofit_project(site_id: str, trigger_finding_id: str,
                            scope_budget_cents: int = 100000, **overrides):
    """Scope a RetrofitProject (starts SCOPING). Returns the project dict."""
    res = api_client.create_retrofit_project(
        site_id,
        create_retrofit_project_payload(trigger_finding_id,
                                        scope_budget_cents=scope_budget_cents,
                                        **overrides),
        ENGINEER)
    return get_success_data(res)


def add_line_item(site_id: str, project_id: str, cost_cents: int = 1000,
                  risk_tier: str = "LOW", **overrides):
    """Add a line item; bumps the parent project's version. Returns the item."""
    res = api_client.create_line_item(
        site_id, project_id,
        create_line_item_payload(cost_cents=cost_cents, risk_tier=risk_tier,
                                 **overrides),
        ENGINEER)
    return get_success_data(res)


def get_project_version(site_id: str, project_id: str) -> int:
    """Read the project's current OCC version."""
    project = get_success_data(
        api_client.get_retrofit_project(site_id, project_id, ENGINEER))
    return project["version"]


def finalize_project(site_id: str, project_id: str):
    """Finalize the estimate with a fresh OCC version. Returns ESTIMATED project."""
    version = get_project_version(site_id, project_id)
    res = api_client.finalize_estimate(site_id, project_id, version, ENGINEER)
    return get_success_data(res)


def create_estimated_project(site_id: str, trigger_finding_id: str,
                             scope_budget_cents: int = 100000,
                             line_items=((1000, "LOW"),)):
    """Project + line items + finalize_estimate. Returns the ESTIMATED project."""
    project = create_retrofit_project(site_id, trigger_finding_id,
                                      scope_budget_cents=scope_budget_cents)
    for cost, tier in line_items:
        add_line_item(site_id, project["id"], cost_cents=cost, risk_tier=tier)
    return finalize_project(site_id, project["id"])


def get_site_version(site_id: str) -> int:
    """Read the site's current OCC version."""
    site = get_success_data(api_client.get_site(site_id, MANAGER))
    return site["version"]
