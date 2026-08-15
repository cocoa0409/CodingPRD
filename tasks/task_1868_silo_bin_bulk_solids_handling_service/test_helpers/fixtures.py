"""Composite setup helpers for multi-step test prerequisites.

Fixtures use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors. Identity threading: PlantOperator calls pass the owning
CustomerSite.id; Technician start/complete calls pass the assigned Technician.id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_entry_permit_payload,
    create_level_reading_payload,
    create_quality_report_payload,
    create_scale_calibration_payload,
    create_service_ticket_payload,
    create_site_payload,
    create_technician_payload,
    create_vessel_payload,
)
from .test_users import (
    TEST_USERS,
    make_plant_operator_headers,
    make_safety_officer_headers,
    make_technician_headers,
)

SM = TEST_USERS["service_manager_headers"]
SO = TEST_USERS["safety_officer_headers"]


# ─── Tier 1: single-entity creation ──────────────────────────────────────────

def create_site(**overrides):
    """Create a CustomerSite. Returns the site dict."""
    res = api_client.create_site(create_site_payload(**overrides), SM)
    return get_success_data(res, 201)


def create_technician(**overrides):
    """Create a Technician. Returns the technician dict."""
    res = api_client.create_technician(create_technician_payload(**overrides), SM)
    return get_success_data(res, 201)


def create_vessel(site_id, **overrides):
    """Create a Vessel under a site. Returns the vessel dict."""
    res = api_client.create_vessel(create_vessel_payload(site_id, **overrides), SM)
    return get_success_data(res, 201)


def create_site_with_vessel(site_overrides=None, vessel_overrides=None):
    """Site + one vessel. Returns (site, vessel)."""
    site = create_site(**(site_overrides or {}))
    vessel = create_vessel(site["id"], **(vessel_overrides or {}))
    return site, vessel


def create_site_vessel_technician(site_overrides=None, vessel_overrides=None,
                                  tech_overrides=None):
    """Site + one vessel + one technician. Returns (site, vessel, technician)."""
    site, vessel = create_site_with_vessel(site_overrides, vessel_overrides)
    tech = create_technician(**(tech_overrides or {}))
    return site, vessel, tech


# ─── Tier 2: inventory / replenishment setups ────────────────────────────────

def post_reading(vessel_id, measured_at, level_pct, site_id, source=None):
    """Post a LevelReading as the owning PlantOperator. Returns the reading dict."""
    payload = create_level_reading_payload(
        vessel_id, measured_at=measured_at, level_pct=level_pct
    )
    if source is not None:
        payload["source"] = source
    res = api_client.create_level_reading(payload, make_plant_operator_headers(site_id))
    return get_success_data(res, 201)


def create_vessel_with_triggered_order(site_overrides=None, vessel_overrides=None,
                                       reading_level_pct=25.0,
                                       reading_measured_at="2026-08-02T00:00:00Z"):
    """Site + vessel + one reading at/below the reorder point, which auto-creates a
    TRIGGERED ReplenishmentOrder. Returns (site, vessel, order, reading)."""
    site, vessel = create_site_with_vessel(site_overrides, vessel_overrides)
    reading = post_reading(
        vessel["id"], reading_measured_at, reading_level_pct, site["id"]
    )
    orders_res = api_client.list_replenishment_orders(
        SM, params={"vessel_id": vessel["id"], "status": "TRIGGERED"}
    )
    orders = get_success_data(orders_res)
    order = orders[0]
    return site, vessel, order, reading


def create_vessel_with_dispatched_order(**kwargs):
    """As create_vessel_with_triggered_order, plus the order dispatched.
    Returns (site, vessel, order, reading)."""
    site, vessel, order, reading = create_vessel_with_triggered_order(**kwargs)
    res = api_client.dispatch_replenishment_order(order["id"], SM)
    order = get_success_data(res)
    return site, vessel, order, reading


# ─── Tier 3: service ticket lifecycle ────────────────────────────────────────

def create_draft_ticket(site_id, vessel_id, **overrides):
    """Create a DRAFT ServiceTicket. Returns the ticket dict."""
    res = api_client.create_service_ticket(
        create_service_ticket_payload(site_id, vessel_id, **overrides), SM
    )
    return get_success_data(res, 201)


def create_quoted_ticket(site_id, vessel_id, **overrides):
    """Create a ticket and quote it (DRAFT -> QUOTED). Returns the ticket dict."""
    ticket = create_draft_ticket(site_id, vessel_id, **overrides)
    res = api_client.quote_service_ticket(ticket["id"], SM)
    return get_success_data(res)


def create_approved_ticket(site_id, vessel_id, approve_headers=None, **overrides):
    """Create, quote, and approve a ticket. For CONTRACT_SERVICE tickets the owning
    PlantOperator approves (default); pass approve_headers to override the approver
    (e.g. ServiceManager for CAPITAL_PROJECT). Returns the ticket dict."""
    ticket = create_quoted_ticket(site_id, vessel_id, **overrides)
    headers = approve_headers or make_plant_operator_headers(site_id)
    res = api_client.approve_service_ticket(ticket["id"], headers)
    return get_success_data(res)


def create_scheduled_ticket(site_id, vessel_id, technician_id,
                            window_start="2026-08-10T08:00:00Z",
                            window_end="2026-08-10T10:00:00Z",
                            **overrides):
    """Create, quote, approve, and schedule a ticket.
    Returns the SCHEDULED ticket dict."""
    ticket = create_approved_ticket(site_id, vessel_id, **overrides)
    res = api_client.schedule_service_ticket(
        ticket["id"],
        {
            "technician_id": technician_id,
            "window_start": window_start,
            "window_end": window_end,
        },
        SM,
    )
    return get_success_data(res)


def create_in_progress_ticket(site_id, vessel_id, technician_id,
                              window_start="2026-08-10T08:00:00Z",
                              window_end="2026-08-10T10:00:00Z",
                              **overrides):
    """Create a ticket walked through to IN_PROGRESS (no entry permit; only valid
    for requires_entry=False tickets). Returns the ticket dict."""
    ticket = create_scheduled_ticket(
        site_id, vessel_id, technician_id,
        window_start=window_start, window_end=window_end, **overrides
    )
    res = api_client.start_service_ticket(
        ticket["id"], make_technician_headers(technician_id)
    )
    return get_success_data(res)


# ─── Tier 4: entry permit lifecycle ──────────────────────────────────────────

def create_draft_permit(vessel_id, ticket_id, entrant_technician_id,
                        window_start="2026-08-10T08:00:00Z",
                        window_end="2026-08-10T10:00:00Z"):
    """Create a DRAFT EntryPermit. Returns the permit dict."""
    res = api_client.create_entry_permit(
        create_entry_permit_payload(
            vessel_id, ticket_id, entrant_technician_id,
            window_start=window_start, window_end=window_end,
        ),
        SO,
    )
    return get_success_data(res, 201)


def create_issued_permit(vessel_id, ticket_id, entrant_technician_id,
                         issuer_user_id="so-issuer-1", **window):
    """Create + issue an EntryPermit (lockout confirmed). Returns the permit dict."""
    permit = create_draft_permit(
        vessel_id, ticket_id, entrant_technician_id, **window
    )
    res = api_client.issue_entry_permit(
        permit["id"],
        {"lockout_checklist_confirmed": True},
        make_safety_officer_headers(issuer_user_id),
    )
    return get_success_data(res)


def create_active_permit(vessel_id, ticket_id, entrant_technician_id,
                         issuer_user_id="so-issuer-1",
                         oxygen_pct=20.9, combustible_pct=1.0, **window):
    """Create + issue + activate an EntryPermit. Returns the permit dict."""
    permit = create_issued_permit(
        vessel_id, ticket_id, entrant_technician_id,
        issuer_user_id=issuer_user_id, **window
    )
    res = api_client.activate_entry_permit(
        permit["id"],
        {"oxygen_pct": oxygen_pct, "combustible_pct": combustible_pct},
        SO,
    )
    return get_success_data(res)


def create_approved_entry_ticket_with_permit(site_overrides=None,
                                             vessel_overrides=None,
                                             tech_overrides=None,
                                             ticket_overrides=None,
                                             window_start="2026-08-10T08:00:00Z",
                                             window_end="2026-08-10T10:00:00Z",
                                             activate=False):
    """Site + vessel + technician + APPROVED requires_entry ticket + DRAFT
    (or ISSUED / ACTIVE when activate=True) permit bound to the ticket.
    Returns (site, vessel, technician, ticket, permit)."""
    site, vessel, tech = create_site_vessel_technician(
        site_overrides, vessel_overrides, tech_overrides
    )
    overrides = {"requires_entry": True, "est_hours": 4, "crew_size": 1}
    overrides.update(ticket_overrides or {})
    ticket = create_approved_ticket(site["id"], vessel["id"], **overrides)
    if activate:
        permit = create_active_permit(
            vessel["id"], ticket["id"], tech["id"],
            window_start=window_start, window_end=window_end,
        )
    else:
        permit = create_draft_permit(
            vessel["id"], ticket["id"], tech["id"],
            window_start=window_start, window_end=window_end,
        )
    return site, vessel, tech, ticket, permit


# ─── Tier 5: posture / quality / calibration setups ──────────────────────────

def post_quality_report(vessel_id, technician_id, sampled_at="2026-08-02T00:00:00Z",
                        moisture_pct=10.0, caking_index=1):
    """Submit a MaterialQualityReport as a Technician. Returns the report dict."""
    res = api_client.create_quality_report(
        create_quality_report_payload(
            vessel_id, sampled_at=sampled_at,
            moisture_pct=moisture_pct, caking_index=caking_index,
        ),
        make_technician_headers(technician_id),
    )
    return get_success_data(res, 201)


def post_scale_calibration(vessel_id, technician_id,
                           tested_at="2026-08-02T00:00:00Z",
                           test_weight_tons=20.0, indicated_tons=20.0,
                           tolerance_pct=None):
    """Record a ScaleCalibration as a Technician. Returns the calibration dict."""
    payload = create_scale_calibration_payload(
        vessel_id, tested_at=tested_at,
        test_weight_tons=test_weight_tons, indicated_tons=indicated_tons,
    )
    if tolerance_pct is not None:
        payload["tolerance_pct"] = tolerance_pct
    res = api_client.create_scale_calibration(
        payload, make_technician_headers(technician_id)
    )
    return get_success_data(res, 201)


def create_flow_impaired_vessel(site_overrides=None, vessel_overrides=None,
                                moisture_pct=15.0, caking_index=1):
    """Site + vessel + technician + one breaching quality report, so the vessel's
    flow_posture becomes FLOW_IMPAIRED. Returns (site, vessel, technician, report)."""
    site, vessel, tech = create_site_vessel_technician(
        site_overrides, vessel_overrides
    )
    report = post_quality_report(
        vessel["id"], tech["id"], moisture_pct=moisture_pct, caking_index=caking_index
    )
    return site, vessel, tech, report
