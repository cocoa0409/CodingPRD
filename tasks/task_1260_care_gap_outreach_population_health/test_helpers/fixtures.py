"""Composite setup helpers for the care-gap outreach domain.

Every helper builds preconditions from scratch via PRD-declared endpoints and
uses get_success_data() so setup failures surface as clear "Setup failed"
errors. All roles use opaque identities (PRD §2.1); PanelManager calls use the
owning panel_manager_id as X-User-ID.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, NOON_DAY1_ISO
from .factories import (
    create_registry_payload, create_measure_payload, create_cohort_payload,
    create_member_payload, create_panel_payload, create_campaign_payload,
    create_attempt_payload, create_appointment_payload,
    create_transportation_assist_payload, create_evidence_payload,
    create_exclusion_request_payload, create_workload_payload,
    create_performance_report_payload,
)
from .test_users import (
    make_admin_headers, make_panel_manager_headers,
    make_quality_reviewer_headers, make_transport_coordinator_headers,
    make_reconciliation_bot_headers,
)

PM_ID = TEST_DEFAULTS["PANEL_MANAGER_ID"]
QR_ID = TEST_DEFAULTS["REVIEWER_ID"]


def _setup_fail(step: str, resp):
    raise AssertionError(f"Setup failed at {step}: {resp.status_code} {resp.text}")


# ---------------------------------------------------------------------------
# Tier 1/2: registry, definition, and panel materialization builders
# ---------------------------------------------------------------------------

def create_registry(name="R1", **overrides):
    """Create a registry (born ACTIVE, clock at the default instant)."""
    resp = api_client.create_registry(create_registry_payload(name=name, **overrides), make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("create_registry", resp)
    return get_success_data(resp)


def create_published_measure(registry_id, code="SCR", domain="SCREENING",
                             lookback_days=365, reporting_lag_days=None,
                             exclusion_window_days=None):
    """Create a measure and publish it (DRAFT -> PUBLISHED)."""
    payload = create_measure_payload(
        measure_code=code, measure_domain=domain, lookback_days=lookback_days,
    )
    if reporting_lag_days is not None:
        payload["reporting_lag_days"] = reporting_lag_days
    if exclusion_window_days is not None:
        payload["exclusion_window_days"] = exclusion_window_days
    resp = api_client.create_measure(registry_id, payload, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("create_measure", resp)
    measure = get_success_data(resp)
    resp = api_client.publish_measure(measure["id"], make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("publish_measure", resp)
    return get_success_data(resp)


def create_active_cohort(registry_id, code="C", min_age=50, max_age=75,
                         risk_tier_filter="ANY"):
    """Create a cohort and activate it (DRAFT -> ACTIVE)."""
    resp = api_client.create_cohort(
        registry_id,
        create_cohort_payload(cohort_code=code, min_age=min_age, max_age=max_age,
                              risk_tier_filter=risk_tier_filter),
        make_admin_headers(),
    )
    if resp.status_code >= 300:
        _setup_fail("create_cohort", resp)
    cohort = get_success_data(resp)
    resp = api_client.activate_cohort(cohort["id"], make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("activate_cohort", resp)
    return get_success_data(resp)


def create_member(registry_id, mrn="M", date_of_birth="1960-01-01T00:00:00Z",
                  risk_tier="LOW", phone_ok=None, mail_ok=None):
    """Register a member (born ENROLLED)."""
    payload = create_member_payload(mrn=mrn, date_of_birth=date_of_birth, risk_tier=risk_tier)
    if phone_ok is not None:
        payload["phone_ok"] = phone_ok
    if mail_ok is not None:
        payload["mail_ok"] = mail_ok
    resp = api_client.create_member(registry_id, payload, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("create_member", resp)
    return get_success_data(resp)


def create_panel(registry_id, cohort_id, measure_id, panel_manager_id=PM_ID):
    """Create a panel (born BUILDING)."""
    resp = api_client.create_panel(
        registry_id,
        create_panel_payload(cohort_id=cohort_id, measure_id=measure_id,
                             panel_manager_id=panel_manager_id),
        make_admin_headers(),
    )
    if resp.status_code >= 300:
        _setup_fail("create_panel", resp)
    return get_success_data(resp)


def activate_panel(panel_id):
    """Activate a panel, materializing care gaps for cohort-matching members."""
    resp = api_client.activate_panel(panel_id, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("activate_panel", resp)
    return get_success_data(resp)


def list_panel_gaps(panel_id):
    resp = api_client.list_panel_care_gaps(panel_id, make_admin_headers(),
                                           params={"limit": 100})
    if resp.status_code >= 300:
        _setup_fail("list_panel_care_gaps", resp)
    return get_success_data(resp)


def advance_clock(registry_id, to_iso8601):
    """Advance the registry logical clock (ProgramAdministrator only)."""
    resp = api_client.set_clock(
        {"registry_id": registry_id, "to_iso8601": to_iso8601},
        make_admin_headers(),
    )
    if resp.status_code >= 300:
        _setup_fail("advance_clock", resp)
    return get_success_data(resp)


def setup_panel_scenario(num_members=1, reporting_lag_days=None,
                         measure_domain="SCREENING", lookback_days=365,
                         member_specs=None, min_age=50, max_age=75,
                         risk_tier_filter="ANY", panel_manager_id=PM_ID,
                         registry_name="R"):
    """Full setup: registry + PUBLISHED measure + ACTIVE cohort + members
    + panel activated (care gaps materialized).

    member_specs: optional list of dicts overriding create_member kwargs.
    Returns dict(registry, measure, cohort, members, panel, gaps).
    """
    registry = create_registry(name=registry_name)
    measure = create_published_measure(
        registry["id"], domain=measure_domain, lookback_days=lookback_days,
        reporting_lag_days=reporting_lag_days,
    )
    cohort = create_active_cohort(registry["id"], min_age=min_age, max_age=max_age,
                                  risk_tier_filter=risk_tier_filter)
    members = []
    if member_specs is not None:
        for i, spec in enumerate(member_specs):
            spec = dict(spec)
            spec.setdefault("mrn", f"M{i + 1}")
            members.append(create_member(registry["id"], **spec))
    else:
        for i in range(num_members):
            members.append(create_member(registry["id"], mrn=f"M{i + 1}"))
    panel = create_panel(registry["id"], cohort["id"], measure["id"],
                         panel_manager_id=panel_manager_id)
    panel = activate_panel(panel["id"])
    gaps = list_panel_gaps(panel["id"])
    return {
        "registry": registry,
        "measure": measure,
        "cohort": cohort,
        "members": members,
        "panel": panel,
        "gaps": gaps,
        "panel_manager_id": panel_manager_id,
    }


# ---------------------------------------------------------------------------
# Tier 2: campaigns
# ---------------------------------------------------------------------------

def create_campaign(registry_id, panel_id, measure_id, **overrides):
    """Create a campaign (born DRAFT)."""
    resp = api_client.create_campaign(
        registry_id,
        create_campaign_payload(panel_id=panel_id, measure_id=measure_id, **overrides),
        make_admin_headers(),
    )
    if resp.status_code >= 300:
        _setup_fail("create_campaign", resp)
    return get_success_data(resp)


def schedule_campaign(campaign_id):
    resp = api_client.schedule_campaign(campaign_id, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("schedule_campaign", resp)
    return get_success_data(resp)


def launch_campaign(campaign_id):
    resp = api_client.launch_campaign(campaign_id, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("launch_campaign", resp)
    return get_success_data(resp)


def setup_active_campaign(scenario, advance_to=NOON_DAY1_ISO, **campaign_overrides):
    """Create + schedule + launch a campaign, then advance the clock.

    Launch happens while the clock still equals the default starts_at (the
    clock 'has reached' starts_at), then the clock advances — avoiding any
    dependence on auto-launch timing. Default landing time is noon on day one,
    inside default waking hours (08:00-21:00), so attempts are not blocked by
    the quiet-hours rule.
    """
    registry_id = scenario["registry"]["id"]
    campaign = create_campaign(
        registry_id, scenario["panel"]["id"], scenario["measure"]["id"],
        **campaign_overrides,
    )
    schedule_campaign(campaign["id"])
    campaign = launch_campaign(campaign["id"])
    if advance_to is not None:
        advance_clock(registry_id, advance_to)
    return campaign


# ---------------------------------------------------------------------------
# Tier 3: outreach attempts, appointments, evidence lifecycle
# ---------------------------------------------------------------------------

def get_care_gap(gap_id):
    resp = api_client.get_care_gap(gap_id, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("get_care_gap", resp)
    return get_success_data(resp)


def record_attempt(gap_id, campaign_id, outcome="NO_ANSWER", channel="CALL",
                   panel_manager_id=PM_ID, extra_payload=None):
    """Record an outreach attempt with the gap's current version (OCC token
    re-read immediately before the write). Returns the attempt body."""
    gap = get_care_gap(gap_id)
    payload = create_attempt_payload(
        campaign_id=campaign_id, channel=channel, outcome=outcome,
        expected_care_gap_version=gap["version"],
    )
    if extra_payload:
        payload.update(extra_payload)
    resp = api_client.create_outreach_attempt(
        gap_id, payload, make_panel_manager_headers(panel_manager_id),
    )
    if resp.status_code >= 300:
        _setup_fail("record_attempt", resp)
    return get_success_data(resp)


def book_appointment(gap_id, provider_id="prov_A",
                     slot_start_at="2026-06-01T14:00:00Z",
                     slot_end_at="2026-06-01T15:00:00Z",
                     provider_capacity_per_slot=None, panel_manager_id=PM_ID):
    """Schedule an appointment; the gap moves to AWAITING_APPOINTMENT."""
    payload = create_appointment_payload(
        provider_id=provider_id, slot_start_at=slot_start_at, slot_end_at=slot_end_at,
    )
    if provider_capacity_per_slot is not None:
        payload["provider_capacity_per_slot"] = provider_capacity_per_slot
    resp = api_client.create_appointment(
        gap_id, payload, make_panel_manager_headers(panel_manager_id),
    )
    if resp.status_code >= 300:
        _setup_fail("book_appointment", resp)
    return get_success_data(resp)


def create_transport(appointment_id, vendor="RideCo",
                     pickup_at="2026-06-01T13:00:00Z", cost_cents=2500):
    """Request a transportation assist (born REQUESTED)."""
    resp = api_client.create_transportation_assist(
        appointment_id,
        create_transportation_assist_payload(vendor=vendor, pickup_at=pickup_at,
                                             cost_cents=cost_cents),
        make_transport_coordinator_headers(),
    )
    if resp.status_code >= 300:
        _setup_fail("create_transportation_assist", resp)
    return get_success_data(resp)


def arrange_transport(assist_id):
    resp = api_client.arrange_transportation_assist(
        assist_id, make_transport_coordinator_headers(),
    )
    if resp.status_code >= 300:
        _setup_fail("arrange_transportation_assist", resp)
    return get_success_data(resp)


def submit_evidence(gap_id, evidence_type="CHART_REVIEW",
                    service_date=TEST_DEFAULTS["EVIDENCE_SERVICE_DATE"],
                    document_uri="s3://docs/evidence.pdf",
                    submitter_id=PM_ID):
    """Submit closure evidence as a PanelManager (born SUBMITTED; gap moves to
    PENDING_EVIDENCE)."""
    resp = api_client.create_evidence(
        gap_id,
        create_evidence_payload(evidence_type=evidence_type, service_date=service_date,
                                document_uri=document_uri),
        make_panel_manager_headers(submitter_id),
    )
    if resp.status_code >= 300:
        _setup_fail("submit_evidence", resp)
    return get_success_data(resp)


def approve_evidence(evidence_id, reviewer_id=QR_ID):
    resp = api_client.approve_evidence(
        evidence_id, {}, make_quality_reviewer_headers(reviewer_id),
    )
    if resp.status_code >= 300:
        _setup_fail("approve_evidence", resp)
    return get_success_data(resp)


def close_gap_via_evidence(gap_id, evidence_type="CHART_REVIEW",
                           service_date=TEST_DEFAULTS["EVIDENCE_SERVICE_DATE"],
                           submitter_id=PM_ID, reviewer_id=QR_ID):
    """Submit + approve evidence; the gap transitions to CLOSED."""
    evidence = submit_evidence(gap_id, evidence_type=evidence_type,
                               service_date=service_date, submitter_id=submitter_id)
    approve_evidence(evidence["id"], reviewer_id=reviewer_id)
    return evidence


# ---------------------------------------------------------------------------
# Tier 4: workloads, payouts, reports
# ---------------------------------------------------------------------------

def create_workload(registry_id, panel_manager_id=PM_ID, period_key="2026-06"):
    resp = api_client.create_workload(
        registry_id,
        create_workload_payload(panel_manager_id=panel_manager_id, period_key=period_key),
        make_admin_headers(),
    )
    if resp.status_code >= 300:
        _setup_fail("create_workload", resp)
    return get_success_data(resp)


def get_workload(workload_id):
    resp = api_client.get_workload(workload_id, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("get_workload", resp)
    return get_success_data(resp)


def create_report(measure_id, period_key="2026-06"):
    """Generate a PROVISIONAL measure performance report."""
    resp = api_client.create_performance_report(
        measure_id, create_performance_report_payload(period_key=period_key),
        make_admin_headers(),
    )
    if resp.status_code >= 300:
        _setup_fail("create_performance_report", resp)
    return get_success_data(resp)


def get_report(report_id):
    resp = api_client.get_performance_report(report_id, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("get_performance_report", resp)
    return get_success_data(resp)


def create_projection(workload_id):
    """Compute or refresh the PROJECTED payout for the workload's period."""
    resp = api_client.create_payout_projection(workload_id, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("create_payout_projection", resp)
    return get_success_data(resp)


def get_payout(payout_id):
    resp = api_client.get_payout(payout_id, make_admin_headers())
    if resp.status_code >= 300:
        _setup_fail("get_payout", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: exclusions
# ---------------------------------------------------------------------------

def create_exclusion(member_id, measure_id=None,
                     exclusion_kind="MEMBER_REFUSAL",
                     justification="member declined outreach",
                     effective_from="2026-05-01T00:00:00Z",
                     effective_until=None, submitter_id=PM_ID):
    """Submit an exclusion request as a PanelManager (born SUBMITTED)."""
    payload = create_exclusion_request_payload(
        exclusion_kind=exclusion_kind, justification=justification,
        effective_from=effective_from,
    )
    if measure_id is not None:
        payload["measure_id"] = measure_id
    if effective_until is not None:
        payload["effective_until"] = effective_until
    resp = api_client.create_exclusion_request(
        member_id, payload, make_panel_manager_headers(submitter_id),
    )
    if resp.status_code >= 300:
        _setup_fail("create_exclusion_request", resp)
    return get_success_data(resp)


def start_review_exclusion(exclusion_id, reviewer_id=QR_ID):
    resp = api_client.start_review_exclusion(
        exclusion_id, make_quality_reviewer_headers(reviewer_id),
    )
    if resp.status_code >= 300:
        _setup_fail("start_review_exclusion", resp)
    return get_success_data(resp)


def setup_exclusion_under_review(member_id, measure_id, submitter_id=PM_ID,
                                 reviewer_id=QR_ID, **overrides):
    """Exclusion request submitted and moved to UNDER_REVIEW."""
    exclusion = create_exclusion(member_id, measure_id=measure_id,
                                 submitter_id=submitter_id, **overrides)
    return start_review_exclusion(exclusion["id"], reviewer_id=reviewer_id)
