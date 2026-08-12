"""Composite setup helpers.

Multi-step setup sequences so tests focus on assertions. All helpers build
their preconditions from scratch using only PRD-declared endpoints (every test
runs against a freshly restarted server with an empty database and the fixed
startup clock), and use get_success_data() internally so setup failures
surface as clear "Setup failed" errors rather than confusing assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SEASON_START, SEASON_END
from .factories import (
    create_client_payload, create_site_payload, create_contract_payload,
    create_contract_site_payload, create_storm_event_payload,
    create_observation_payload, create_visit_payload, create_material_payload,
    create_photo_payload, create_event_invoice_payload, create_subcontractor_payload,
    create_coverage_payload, create_claim_payload,
)
from .test_users import (
    TEST_USERS, make_client_headers, make_subcontractor_headers,
    make_dispatcher_headers, make_crew_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCH = TEST_USERS["ops_dispatcher_headers"]
CREW = TEST_USERS["crew_lead_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock. Returns the clock payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def setup_client(name="Test Client", credit_limit_cents=10_000_000):
    """Create one client. Returns the client dict."""
    payload = create_client_payload(name=name, credit_limit_cents=credit_limit_cents)
    return get_success_data(api_client.create_client(payload, DISPATCH))


def setup_site(client_id, name="Test Lot", region_code="NE",
               pavement_area_sqft=10_000, requires_loader=False, address="1 Main St"):
    """Create one site for a client. Returns the site dict."""
    payload = create_site_payload(
        client_id, name=name, address=address, region_code=region_code,
        pavement_area_sqft=pavement_area_sqft, requires_loader=requires_loader,
    )
    return get_success_data(api_client.create_site(payload, DISPATCH))


def setup_contract(client_id, contract_type="PER_PUSH", season_start=SEASON_START,
                   season_end=SEASON_END, **terms):
    """Create one contract in DRAFT. Returns the contract dict."""
    payload = create_contract_payload(
        client_id, contract_type=contract_type,
        season_start=season_start, season_end=season_end, **terms,
    )
    return get_success_data(api_client.create_contract(payload, DISPATCH))


def link_site(contract_id, site_id, priority_sequence=1,
              completion_target_minutes=360, **overrides):
    """Link a site into a contract. Returns the ContractSite dict."""
    payload = create_contract_site_payload(
        contract_id, site_id, priority_sequence=priority_sequence,
        completion_target_minutes=completion_target_minutes, **overrides,
    )
    return get_success_data(api_client.create_contract_site(payload, DISPATCH))


def activate_contract(contract_id):
    """DRAFT -> ACTIVE. Returns the updated contract dict."""
    return get_success_data(api_client.activate_contract(contract_id, DISPATCH))


# ---------------------------------------------------------------------------
# Tier 2: active-contract hierarchies (client + site + contract + link)
# ---------------------------------------------------------------------------

def setup_active_contract(contract_type="PER_PUSH", client_name="Test Client",
                          credit_limit_cents=10_000_000, site_name="Test Lot",
                          region_code="NE", pavement_area_sqft=10_000,
                          requires_loader=False, priority_sequence=1,
                          completion_target_minutes=360, season_start=SEASON_START,
                          season_end=SEASON_END, link_overrides=None, **terms):
    """Client + site + contract + ContractSite link + activation.

    Returns {"client", "site", "contract", "contract_site"}.
    """
    client = setup_client(name=client_name, credit_limit_cents=credit_limit_cents)
    site = setup_site(client["id"], name=site_name, region_code=region_code,
                      pavement_area_sqft=pavement_area_sqft,
                      requires_loader=requires_loader)
    contract = setup_contract(client["id"], contract_type=contract_type,
                              season_start=season_start, season_end=season_end, **terms)
    contract_site = link_site(contract["id"], site["id"],
                              priority_sequence=priority_sequence,
                              completion_target_minutes=completion_target_minutes,
                              **(link_overrides or {}))
    contract = activate_contract(contract["id"])
    return {"client": client, "site": site, "contract": contract,
            "contract_site": contract_site}


def setup_active_per_push(trigger_depth_inches=2.0, per_push_rate_cents=45_000,
                          require_photo_verification=False, **kwargs):
    """Active PER_PUSH contract hierarchy. Returns the context dict."""
    return setup_active_contract(
        "PER_PUSH", trigger_depth_inches=trigger_depth_inches,
        per_push_rate_cents=per_push_rate_cents,
        require_photo_verification=require_photo_verification, **kwargs)


def setup_active_seasonal(seasonal_fee_cents=2_000_000, seasonal_push_cap=2,
                          seasonal_overage_rate_cents=40_000,
                          trigger_depth_inches=1.0, season_end="2026-12-31T23:59:59Z",
                          completion_target_minutes=480, **kwargs):
    """Active SEASONAL contract hierarchy (short season ending New Year's Eve)."""
    return setup_active_contract(
        "SEASONAL", trigger_depth_inches=trigger_depth_inches,
        seasonal_fee_cents=seasonal_fee_cents, seasonal_push_cap=seasonal_push_cap,
        seasonal_overage_rate_cents=seasonal_overage_rate_cents,
        require_photo_verification=False, season_end=season_end,
        completion_target_minutes=completion_target_minutes, **kwargs)


def setup_active_hourly(hourly_rate_cents=12_000, hourly_tier2_rate_cents=6_000,
                        hourly_tier_threshold_minutes=2400, night_premium_pct=0.25,
                        trigger_depth_inches=1.0, completion_target_minutes=720,
                        **kwargs):
    """Active HOURLY contract hierarchy. Returns the context dict."""
    return setup_active_contract(
        "HOURLY", trigger_depth_inches=trigger_depth_inches,
        hourly_rate_cents=hourly_rate_cents,
        hourly_tier2_rate_cents=hourly_tier2_rate_cents,
        hourly_tier_threshold_minutes=hourly_tier_threshold_minutes,
        night_premium_pct=night_premium_pct, require_photo_verification=False,
        completion_target_minutes=completion_target_minutes, **kwargs)


# ---------------------------------------------------------------------------
# Tier 2: storm events and observations
# ---------------------------------------------------------------------------

def setup_storm_event(region_code="NE", window_start="2026-12-10T00:00:00Z",
                      window_end="2026-12-10T08:00:00Z",
                      reported_accumulation_inches=2.0,
                      reported_source_name="NOAA"):
    """Create one REPORTED storm event. Returns the event dict."""
    payload = create_storm_event_payload(
        region_code=region_code, window_start=window_start, window_end=window_end,
        reported_accumulation_inches=reported_accumulation_inches,
        reported_source_name=reported_source_name,
    )
    return get_success_data(api_client.create_storm_event(payload, DISPATCH))


def post_observation(event_id, source_name, observed_at, accumulation_inches,
                     note=None):
    """Append one weather observation (PlatformAdmin feed). Returns the row."""
    payload = create_observation_payload(event_id, source_name, observed_at,
                                         accumulation_inches)
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_observation(payload, ADMIN))


def verify_event(event_id):
    """REPORTED|CHALLENGED -> VERIFIED. Returns the event dict."""
    return get_success_data(api_client.verify_storm_event(event_id, DISPATCH))


def verify_event_with_two_sources(event_id, observed_pairs):
    """Post (source, observed_at, inches) observations then verify. Returns event."""
    for source_name, observed_at, inches in observed_pairs:
        post_observation(event_id, source_name, observed_at, inches)
    return verify_event(event_id)


# ---------------------------------------------------------------------------
# Tier 3: visit lifecycle
# ---------------------------------------------------------------------------

def schedule_visit(event_id, contract_site_id,
                   scheduled_start="2026-12-10T09:00:00Z",
                   scheduled_end="2026-12-10T10:00:00Z",
                   assigned_subcontractor_id=None):
    """Create one SCHEDULED visit. Returns the visit dict."""
    payload = create_visit_payload(
        event_id, contract_site_id, scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    if assigned_subcontractor_id is not None:
        payload["assigned_subcontractor_id"] = assigned_subcontractor_id
    return get_success_data(api_client.create_visit(payload, DISPATCH))


def start_visit(visit_id, at=None, headers=None):
    """SCHEDULED -> IN_PROGRESS; optionally moves the clock first."""
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.start_visit(visit_id, headers or CREW))


def complete_visit(visit_id, at=None, headers=None):
    """IN_PROGRESS -> COMPLETED; optionally moves the clock first."""
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.complete_visit(visit_id, headers or CREW))


def run_visit(visit_id, start_at, complete_at, headers=None):
    """Start then complete one visit at the given logical instants."""
    start_visit(visit_id, at=start_at, headers=headers)
    return complete_visit(visit_id, at=complete_at, headers=headers)


def setup_completed_visit(ctx, event, scheduled_start="2026-12-10T09:00:00Z",
                          scheduled_end="2026-12-10T10:00:00Z",
                          start_at="2026-12-10T09:05:00Z",
                          complete_at="2026-12-10T10:00:00Z", headers=None):
    """Schedule a visit on the context's contract-site and run it to COMPLETED.

    Returns the COMPLETED visit dict.
    """
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"],
                           scheduled_start=scheduled_start,
                           scheduled_end=scheduled_end)
    return run_visit(visit["id"], start_at, complete_at, headers=headers)


def setup_billable_visit(ctx, event, observed_pairs,
                         scheduled_start="2026-12-10T09:00:00Z",
                         scheduled_end="2026-12-10T10:00:00Z",
                         start_at="2026-12-10T09:05:00Z",
                         complete_at="2026-12-10T10:00:00Z"):
    """Complete a visit, then verify the event so it flips BILLABLE_CONFIRMED.

    Returns (visit_after_verify, verified_event).
    """
    visit = setup_completed_visit(ctx, event, scheduled_start, scheduled_end,
                                  start_at, complete_at)
    verified = verify_event_with_two_sources(event["id"], observed_pairs)
    visit = get_success_data(api_client.get_visit(visit["id"], DISPATCH))
    return visit, verified


# ---------------------------------------------------------------------------
# Tier 3: materials and photos
# ---------------------------------------------------------------------------

def log_material(visit_id, material_type, quantity_lbs, headers=None):
    """Log one material application. Returns the MaterialApplication dict."""
    payload = create_material_payload(visit_id, material_type, quantity_lbs)
    return get_success_data(api_client.create_material(payload, headers or CREW))


def upload_photo(visit_id, phase, image_uri, headers=None):
    """Upload one verification photo. Returns the ServicePhoto dict."""
    payload = create_photo_payload(visit_id, phase, image_uri)
    return get_success_data(api_client.create_photo(payload, headers or CREW))


def accept_photo(photo_id):
    return get_success_data(api_client.accept_photo(photo_id, DISPATCH))


# ---------------------------------------------------------------------------
# Tier 4: invoices
# ---------------------------------------------------------------------------

def setup_event_invoice(ctx, event):
    """Generate a DRAFT EVENT invoice. Returns the invoice dict."""
    payload = create_event_invoice_payload(ctx["contract"]["id"], event["id"])
    return get_success_data(api_client.create_invoice(payload, DISPATCH))


def setup_issued_event_invoice(ctx, event, issuer_headers=None):
    """Generate + issue an EVENT invoice. Returns the issued invoice dict."""
    invoice = setup_event_invoice(ctx, event)
    return get_success_data(
        api_client.issue_invoice(invoice["id"], issuer_headers or DISPATCH))


# ---------------------------------------------------------------------------
# Tier 4: subcontractors and coverage
# ---------------------------------------------------------------------------

def setup_subcontractor(legal_name="Test Plow LLC", contact_email=None,
                        has_loader=False, has_brine_truck=False, approve=True):
    """Register a subcontractor (PENDING), optionally approve it. Returns the sub."""
    payload = create_subcontractor_payload(
        legal_name=legal_name,
        contact_email=contact_email or f"{legal_name.replace(' ', '.').lower()}@example.com",
        has_loader=has_loader, has_brine_truck=has_brine_truck,
    )
    sub = get_success_data(api_client.create_subcontractor(payload, DISPATCH))
    if approve:
        sub = get_success_data(api_client.approve_subcontractor(sub["id"], ADMIN))
    return sub


def setup_coverage(event_id, contract_id, subcontractor_id,
                   coverage_start="2026-12-10T00:00:00Z",
                   coverage_end="2026-12-10T12:00:00Z", activate=True):
    """Create a coverage assignment, optionally self-activated by the sub."""
    payload = create_coverage_payload(event_id, contract_id, subcontractor_id,
                                      coverage_start, coverage_end)
    coverage = get_success_data(api_client.create_coverage_assignment(payload, DISPATCH))
    if activate:
        coverage = get_success_data(api_client.activate_coverage_assignment(
            coverage["id"], make_subcontractor_headers(subcontractor_id)))
    return coverage


def setup_closed_event_coverage(ctx, subcontractor_id, day):
    """One prior RELEASED coverage for a subcontractor on a past event.

    Reports and verifies an event on the given day (e.g. "2026-12-01"),
    closes it via the sweep, and releases the coverage. Returns the coverage.
    """
    set_clock(f"{day}T00:30:00Z")
    event = setup_storm_event(window_start=f"{day}T00:00:00Z",
                              window_end=f"{day}T06:00:00Z",
                              reported_accumulation_inches=2.0)
    coverage = setup_coverage(event["id"], ctx["contract"]["id"], subcontractor_id,
                              coverage_start=f"{day}T00:00:00Z",
                              coverage_end=f"{day}T12:00:00Z", activate=True)
    verify_event_with_two_sources(event["id"], [
        ("NOAA", f"{day}T05:00:00Z", 2.0),
        ("DTN", f"{day}T05:30:00Z", 2.1),
    ])
    set_clock(f"{day}T13:00:00Z")
    get_success_data(api_client.close_sweep_storm_event(event["id"], DISPATCH))
    return get_success_data(
        api_client.release_coverage_assignment(coverage["id"], DISPATCH))


# ---------------------------------------------------------------------------
# Tier 5: terminal-state shortcuts
# ---------------------------------------------------------------------------

def expire_contract_at(contract_id, at_iso="2027-01-05T00:00:00Z"):
    """Advance the clock past season end and expire the contract."""
    set_clock(at_iso)
    return get_success_data(api_client.expire_contract(contract_id, DISPATCH))


def setup_claim(ctx, site_id, incident_at, severity="NEAR_MISS",
                description="Slip-and-fall incident"):
    """File a claim as the owning client contact. Returns the claim dict."""
    payload = create_claim_payload(site_id, incident_at, severity, description)
    return get_success_data(api_client.create_slip_fall_claim(
        payload, make_client_headers(ctx["client"]["id"])))
