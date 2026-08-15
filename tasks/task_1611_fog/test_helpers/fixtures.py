"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: FseContact calls are entity-backed by Establishment and
HaulerAdmin calls are entity-backed by Hauler. Ownership-gated calls always
thread the real entity id through make_fse_contact_headers /
make_hauler_admin_headers — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    assess_blockage_payload,
    create_blockage_event_payload,
    create_campaign_payload,
    create_disposal_record_payload,
    create_establishment_payload,
    create_hauler_payload,
    create_inspection_payload,
    create_interceptor_payload,
    create_outreach_event_payload,
    create_pump_manifest_payload,
    create_variance_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_fse_contact_headers,
    make_hauler_admin_headers,
    make_inspector_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (must be strictly after the current value)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and state progression
# ---------------------------------------------------------------------------

def create_establishment(name="Test Establishment", street_address="1 Test Way",
                         seating_capacity=10, fryer_count=0,
                         has_charbroiler=None, cuisine_profile="LOW_GREASE"):
    """Register an establishment (born COMPLIANT, version 1)."""
    overrides = {}
    if has_charbroiler is not None:
        overrides["has_charbroiler"] = has_charbroiler
    payload = create_establishment_payload(
        name=name, street_address=street_address,
        seating_capacity=seating_capacity, fryer_count=fryer_count,
        cuisine_profile=cuisine_profile, **overrides)
    return get_success_data(api_client.create_establishment(payload, ADMIN))


def get_establishment(establishment_id):
    return get_success_data(api_client.get_establishment(establishment_id, ADMIN))


def create_hauler(name="Test Haul", permit_number="PN-TEST",
                  insurance_expires_on=TEST_DEFAULTS["INSURANCE_EXPIRES_ON"]):
    """Register a hauler (born APPLIED, mismatch_count 0)."""
    payload = create_hauler_payload(name=name, permit_number=permit_number,
                                    insurance_expires_on=insurance_expires_on)
    return get_success_data(api_client.create_hauler(payload, ADMIN))


def create_and_permit_hauler(name="Test Haul", permit_number="PN-TEST",
                             insurance_expires_on=TEST_DEFAULTS["INSURANCE_EXPIRES_ON"]):
    """Register + permit a hauler (status PERMITTED)."""
    hauler = create_hauler(name=name, permit_number=permit_number,
                           insurance_expires_on=insurance_expires_on)
    return get_success_data(api_client.permit_hauler(hauler["id"], ADMIN))


def create_interceptor(establishment_id, nominal_capacity_gal=50,
                       measured_flow_gpm=None):
    """Propose an interceptor (status PROPOSED) as ProgramAdmin."""
    overrides = {}
    if measured_flow_gpm is not None:
        overrides["measured_flow_gpm"] = measured_flow_gpm
    payload = create_interceptor_payload(establishment_id,
                                         nominal_capacity_gal, **overrides)
    return get_success_data(api_client.create_interceptor(payload, ADMIN))


def approve_interceptor(interceptor_id):
    return get_success_data(api_client.approve_interceptor(interceptor_id, OFFICER))


def commission_interceptor(interceptor_id):
    return get_success_data(
        api_client.commission_interceptor(interceptor_id, INSPECTOR))


def create_active_interceptor(establishment_id, nominal_capacity_gal=600,
                              measured_flow_gpm=None):
    """Propose + approve + commission: interceptor lands in ACTIVE."""
    interceptor = create_interceptor(establishment_id, nominal_capacity_gal,
                                     measured_flow_gpm=measured_flow_gpm)
    approve_interceptor(interceptor["id"])
    return commission_interceptor(interceptor["id"])


def create_inspection(establishment_id, items, inspector_user_id="test-inspector-1"):
    """Record an inspection; returns the Inspection (score/passed computed)."""
    headers = make_inspector_headers(inspector_user_id)
    payload = create_inspection_payload(establishment_id, items)
    return get_success_data(api_client.create_inspection(payload, headers))


def get_open_violation(establishment_id, status="NOTICED"):
    """Fetch the first violation of the establishment with the given status."""
    violations, _meta = validate_paginated(api_client.list_violations(
        INSPECTOR, {"establishment_id": establishment_id, "status": status}))
    assert violations, (
        f"Expected a {status} violation for establishment {establishment_id}"
    )
    return violations[0]


def create_failing_inspection(establishment_id,
                              inspector_user_id="test-inspector-1"):
    """Record a failing inspection (2 MAJOR + 5 MINOR = 31 deductions, score
    69) and return (inspection, violation). The violation opens NOTICED with
    severity MAJOR."""
    items = (
        [{"category": "GREASE_TRAP_MAINTENANCE", "severity": "MAJOR"},
         {"category": "RECORD_KEEPING", "severity": "MAJOR"}]
        + [{"category": "BMP_PRACTICES", "severity": "MINOR"},
           {"category": "BMP_PRACTICES", "severity": "MINOR"},
           {"category": "STRUCTURAL", "severity": "MINOR"},
           {"category": "STRUCTURAL", "severity": "MINOR"},
           {"category": "RECORD_KEEPING", "severity": "MINOR"}]
    )
    inspection = create_inspection(establishment_id, items,
                                   inspector_user_id=inspector_user_id)
    assert inspection["passed"] is False, "Setup: inspection should fail"
    violation = get_open_violation(establishment_id, status="NOTICED")
    return inspection, violation


def create_manifest(establishment_id, interceptor_id, hauler_id,
                    pump_date=TEST_DEFAULTS["PUMP_DATE"],
                    pumped_volume_gal=TEST_DEFAULTS["PUMPED_VOLUME_GAL"]):
    """Submit a pump manifest as the owning FseContact (status SUBMITTED)."""
    payload = create_pump_manifest_payload(
        establishment_id, interceptor_id, hauler_id,
        pump_date=pump_date, pumped_volume_gal=pumped_volume_gal)
    return get_success_data(api_client.create_pump_manifest(
        payload, make_fse_contact_headers(establishment_id)))


def create_disposal_record(hauler_id, manifest_id,
                           disposed_volume_gal=TEST_DEFAULTS["PUMPED_VOLUME_GAL"],
                           disposal_site_name="Receiving Site",
                           disposed_at=TEST_DEFAULTS["DISPOSED_AT"]):
    """File a disposal record as the owning HaulerAdmin."""
    payload = create_disposal_record_payload(
        hauler_id, manifest_id, disposed_volume_gal=disposed_volume_gal,
        disposal_site_name=disposal_site_name, disposed_at=disposed_at)
    return get_success_data(api_client.create_disposal_record(
        payload, make_hauler_admin_headers(hauler_id)))


# ---------------------------------------------------------------------------
# Tier 2: the pumping chain (establishment + interceptor + hauler + manifest)
# ---------------------------------------------------------------------------

def setup_pumping_chain(seating_capacity=200, fryer_count=3,
                        cuisine_profile="HIGH_GREASE",
                        nominal_capacity_gal=600,
                        establishment_name="Chain Diner",
                        hauler_name="Chain Haul", permit_number="PN-CHAIN"):
    """Establishment + ACTIVE interceptor + PERMITTED hauler.
    Returns (establishment, interceptor, hauler)."""
    est = create_establishment(
        name=establishment_name, seating_capacity=seating_capacity,
        fryer_count=fryer_count, cuisine_profile=cuisine_profile)
    interceptor = create_active_interceptor(est["id"], nominal_capacity_gal)
    hauler = create_and_permit_hauler(name=hauler_name,
                                      permit_number=permit_number)
    return est, interceptor, hauler


def setup_submitted_manifest(pump_date=TEST_DEFAULTS["PUMP_DATE"],
                             pumped_volume_gal=TEST_DEFAULTS["PUMPED_VOLUME_GAL"],
                             **chain_kwargs):
    """Full pumping chain plus one SUBMITTED manifest.
    Returns (establishment, interceptor, hauler, manifest)."""
    est, interceptor, hauler = setup_pumping_chain(**chain_kwargs)
    manifest = create_manifest(est["id"], interceptor["id"], hauler["id"],
                               pump_date=pump_date,
                               pumped_volume_gal=pumped_volume_gal)
    return est, interceptor, hauler, manifest


def setup_verified_manifest(pump_date=TEST_DEFAULTS["PUMP_DATE"],
                            pumped_volume_gal=TEST_DEFAULTS["PUMPED_VOLUME_GAL"],
                            disposed_volume_gal=None, **chain_kwargs):
    """Full pumping chain plus a VERIFIED manifest (matching disposal filed).
    Returns (establishment, interceptor, hauler, manifest, disposal_record)."""
    est, interceptor, hauler, manifest = setup_submitted_manifest(
        pump_date=pump_date, pumped_volume_gal=pumped_volume_gal, **chain_kwargs)
    disposal = create_disposal_record(
        hauler["id"], manifest["id"],
        disposed_volume_gal=(disposed_volume_gal
                             if disposed_volume_gal is not None
                             else pumped_volume_gal))
    verified = get_success_data(
        api_client.verify_pump_manifest(manifest["id"], INSPECTOR))
    return est, interceptor, hauler, verified, disposal


# ---------------------------------------------------------------------------
# Tier 3: variance requests
# ---------------------------------------------------------------------------

def create_variance(establishment_id, scope="INTERCEPTOR_SIZE",
                    requested_frequency_days=None,
                    justification="test justification",
                    effective_from=TEST_DEFAULTS["VARIANCE_EFFECTIVE_FROM"],
                    effective_to=TEST_DEFAULTS["VARIANCE_EFFECTIVE_TO"]):
    """File a variance request as the owning FseContact (status UNDER_REVIEW)."""
    overrides = {}
    if requested_frequency_days is not None:
        overrides["requested_frequency_days"] = requested_frequency_days
    payload = create_variance_request_payload(
        establishment_id, scope=scope, justification=justification,
        effective_from=effective_from, effective_to=effective_to, **overrides)
    return get_success_data(api_client.create_variance_request(
        payload, make_fse_contact_headers(establishment_id)))


def create_and_approve_variance(establishment, scope="PUMPING_FREQUENCY",
                                requested_frequency_days=120,
                                effective_from=TEST_DEFAULTS["VARIANCE_EFFECTIVE_FROM"],
                                effective_to=TEST_DEFAULTS["VARIANCE_EFFECTIVE_TO"]):
    """File + approve a variance with a fresh establishment version.
    Returns the APPROVED variance."""
    variance = create_variance(
        establishment["id"], scope=scope,
        requested_frequency_days=requested_frequency_days,
        effective_from=effective_from, effective_to=effective_to)
    fresh = get_establishment(establishment["id"])
    return get_success_data(api_client.approve_variance_request(
        variance["id"], fresh["version"], OFFICER))


# ---------------------------------------------------------------------------
# Tier 4: blockage events
# ---------------------------------------------------------------------------

def create_blockage(location_description="Test sewer segment",
                    inspector_user_id="test-inspector-1"):
    """Report a blockage event (status REPORTED)."""
    headers = make_inspector_headers(inspector_user_id)
    return get_success_data(api_client.create_blockage_event(
        create_blockage_event_payload(location_description=location_description),
        headers))


def create_and_assess_blockage(total_cleanup_cost_cents, contributions,
                               inspector_user_id="test-inspector-1",
                               location_description="Test sewer segment"):
    """Report + assess a blockage event (status ASSESSED). Returns the event."""
    blockage = create_blockage(location_description,
                               inspector_user_id=inspector_user_id)
    headers = make_inspector_headers(inspector_user_id)
    return get_success_data(api_client.assess_blockage_event(
        blockage["id"],
        assess_blockage_payload(total_cleanup_cost_cents, contributions),
        headers))


def pay_share(blockage_id, establishment_id):
    """Pay one contribution as the owning FseContact."""
    return get_success_data(api_client.pay_blockage_share(
        blockage_id, establishment_id, make_fse_contact_headers(establishment_id)))


def close_blockage(blockage_id, officer_user_id="test-officer-1"):
    return get_success_data(api_client.close_blockage_event(
        blockage_id, make_compliance_officer_headers(officer_user_id)))


# ---------------------------------------------------------------------------
# Tier 5: campaigns and outreach events
# ---------------------------------------------------------------------------

def create_campaign(name="Test Campaign", outreach_zone="ZTEST",
                    start_date="2026-09-01T00:00:00Z",
                    end_date="2026-10-01T00:00:00Z", budget_cents=10000):
    """Create an education campaign (remaining_budget_cents := budget_cents)."""
    payload = create_campaign_payload(
        name=name, outreach_zone=outreach_zone, start_date=start_date,
        end_date=end_date, budget_cents=budget_cents)
    return get_success_data(api_client.create_campaign(payload, ADMIN))


def record_outreach_event(campaign_id, event_date="2026-09-10T00:00:00Z",
                          venue_name="Community Hall", attendance_count=25,
                          cost_cents=1000):
    """Record an outreach event under a campaign (status RECORDED)."""
    payload = create_outreach_event_payload(
        event_date=event_date, venue_name=venue_name,
        attendance_count=attendance_count, cost_cents=cost_cents)
    return get_success_data(api_client.create_outreach_event(
        campaign_id, payload, ADMIN))


def get_campaign(campaign_id):
    return get_success_data(api_client.get_campaign(campaign_id, ADMIN))
