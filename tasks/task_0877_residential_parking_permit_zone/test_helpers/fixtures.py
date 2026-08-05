"""Composite setup helpers for the Residential Parking Permit Zone API.

Every test starts against an empty database (the harness restarts the server
before each test), so each fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use get_success_data() internally so a
broken setup surfaces as a clear "Setup step failed" error rather than a
confusing assertion failure.

Identity threading: Resident is entity_backed:Household, so every ownership-gated
Resident call uses make_resident_headers(household_id) with the real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_payload,
    create_zone_payload,
    create_household_payload,
    create_vehicle_payload,
    create_proof_submission_payload,
    review_proof_payload,
    create_permit_application_payload,
    approve_payload,
    deny_payload,
    renew_approve_payload,
    transfer_payload,
    refund_payload,
    revoke_payload,
    create_visitor_pass_payload,
    create_citation_payload,
    adjudicate_payload,
    create_complaint_payload,
    resolve_complaint_payload,
)
from .test_users import (
    TEST_USERS,
    make_resident_headers,
    make_officer_headers,
)

SUP = TEST_USERS["permit_supervisor_headers"]
CLERK = TEST_USERS["parking_clerk_headers"]
OFFICER1 = TEST_USERS["enforcement_officer_headers"]
OFFICER2 = TEST_USERS["enforcement_officer_2_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + primitives
# ---------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Set the server logical clock (PermitSupervisor)."""
    return get_success_data(api.set_clock(clock_payload(iso), SUP))


def create_zone(api, **overrides):
    """Create an ACTIVE zone. Returns the zone dict."""
    return get_success_data(api.create_zone(create_zone_payload(**overrides), SUP))


def register_household(api, zone_id, **overrides):
    """Self-register a household (Anonymous). Returns the household dict; its id
    is the Resident X-User-ID for subsequent ownership-gated calls."""
    return get_success_data(api.create_household(create_household_payload(zone_id, **overrides), ANON))


def add_vehicle(api, household_id, **overrides):
    """Register an ACTIVE vehicle beneath a household. Returns the vehicle dict."""
    return get_success_data(
        api.create_vehicle(household_id, create_vehicle_payload(**overrides), make_resident_headers(household_id))
    )


def submit_proof(api, household_id, document_type="LEASE"):
    """Submit a proof document (PENDING). Returns the submission dict."""
    return get_success_data(
        api.create_proof_submission(
            household_id, create_proof_submission_payload(document_type=document_type),
            make_resident_headers(household_id),
        )
    )


def review_proof(api, proof_id, outcome="VERIFIED"):
    """Clerk reviews a PENDING proof submission. Returns the submission dict."""
    return get_success_data(api.review_proof_submission(proof_id, review_proof_payload(outcome), CLERK))


def verify_household_proof(api, household_id, document_type="LEASE"):
    """Submit + VERIFY proof so the household's proof_status becomes VERIFIED."""
    proof = submit_proof(api, household_id, document_type)
    review_proof(api, proof["id"], "VERIFIED")
    return proof


def zone_version(api, zone_id):
    """Current version of a zone (for OCC-gated approvals)."""
    return get_success_data(api.get_zone(zone_id, SUP))["version"]


# ---------------------------------------------------------------------------
# Tier 1: application lifecycle
# ---------------------------------------------------------------------------
def create_application(api, zone_id, household_id, vehicle_id, **overrides):
    """Resident submits a permit application (SUBMITTED). Returns the app dict."""
    return get_success_data(
        api.create_permit_application(
            create_permit_application_payload(zone_id, household_id, vehicle_id, **overrides),
            make_resident_headers(household_id),
        )
    )


def review_application(api, application_id):
    """Clerk moves an application SUBMITTED -> UNDER_REVIEW."""
    return get_success_data(api.review_permit_application(application_id, CLERK))


def approve_application(api, application_id, zone_id, expected_zone_version=None):
    """Supervisor approves an UNDER_REVIEW application and issues a permit.
    Fetches the fresh zone version unless one is supplied. Returns the Permit."""
    v = expected_zone_version if expected_zone_version is not None else zone_version(api, zone_id)
    return get_success_data(api.approve_permit_application(application_id, approve_payload(v), SUP))


def deny_application(api, application_id, denial_reason="ineligible"):
    return get_success_data(api.deny_permit_application(application_id, deny_payload(denial_reason), SUP))


def waitlist_application(api, application_id):
    """Clerk waitlists an UNDER_REVIEW application (zone must be full). Returns
    the WaitlistEntry."""
    return get_success_data(api.waitlist_permit_application(application_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 2: full "issue a permit" shortcuts
# ---------------------------------------------------------------------------
def setup_verified_household_with_vehicle(api, zone_id, plate=None, document_type="LEASE",
                                          household_overrides=None):
    """Create a household with VERIFIED proof and one ACTIVE vehicle.
    Returns (household, vehicle)."""
    hh = register_household(api, zone_id, **(household_overrides or {}))
    veh = add_vehicle(api, hh["id"], **({"license_plate": plate} if plate else {}))
    verify_household_proof(api, hh["id"], document_type)
    return hh, veh


def issue_permit(api, zone_id, household_id, vehicle_id):
    """Full issuance path for an already-verified household + ACTIVE vehicle:
    apply -> review -> approve. Returns the ACTIVE Permit."""
    app = create_application(api, zone_id, household_id, vehicle_id)
    review_application(api, app["id"])
    return approve_application(api, app["id"], zone_id)


def setup_active_permit(api, zone_overrides=None, plate=None, clock="2026-05-01T00:00:00Z"):
    """Most common composite: set clock, create a zone, a VERIFIED household with
    one ACTIVE vehicle, and issue one ACTIVE permit.

    Returns a dict: {zone, household, vehicle, permit}. Re-fetch zone via
    api.get_zone(...) for updated counters after further mutations.
    """
    if clock:
        set_clock(api, clock)
    zone = create_zone(api, **(zone_overrides or {}))
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"], plate=plate)
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    return {"zone": zone, "household": hh, "vehicle": veh, "permit": permit}


# ---------------------------------------------------------------------------
# Tier 3: waitlist / capacity scenarios
# ---------------------------------------------------------------------------
def setup_full_zone_with_waitlisted_app(api, clock="2026-05-01T00:00:00Z",
                                        holder_plate="HOLD-A", waiter_plate="WAIT-A"):
    """Capacity-1 zone filled by household H1's permit, plus household H2 with a
    WAITLISTED application (WaitlistEntry WAITING at position 1).

    Returns a dict: {zone, h1, v1, permit1, h2, v2, app2, entry2}.
    """
    set_clock(api, clock)
    zone = create_zone(api, permit_capacity=1, max_permits_per_household=2)
    h1, v1 = setup_verified_household_with_vehicle(api, zone["id"], plate=holder_plate)
    permit1 = issue_permit(api, zone["id"], h1["id"], v1["id"])
    h2, v2 = setup_verified_household_with_vehicle(api, zone["id"], plate=waiter_plate)
    app2 = create_application(api, zone["id"], h2["id"], v2["id"])
    review_application(api, app2["id"])
    entry2 = waitlist_application(api, app2["id"])
    return {"zone": zone, "h1": h1, "v1": v1, "permit1": permit1,
            "h2": h2, "v2": v2, "app2": app2, "entry2": entry2}


# ---------------------------------------------------------------------------
# Tier 4: enforcement (citations, disputes, upheld accumulation)
# ---------------------------------------------------------------------------
def issue_citation(api, zone_id, license_plate, violation_type="NO_PERMIT",
                   permit_id=None, officer="officer-1"):
    """Officer issues a citation. Returns the Citation dict."""
    return get_success_data(
        api.create_citation(
            create_citation_payload(zone_id, license_plate, violation_type, permit_id=permit_id),
            make_officer_headers(officer),
        )
    )


def dispute_citation(api, citation_id, household_id):
    """Resident disputes an ISSUED citation."""
    return get_success_data(api.dispute_citation(citation_id, make_resident_headers(household_id)))


def adjudicate_citation(api, citation_id, outcome, officer="officer-2"):
    """A different officer adjudicates a DISPUTED citation."""
    return get_success_data(
        api.adjudicate_citation(citation_id, adjudicate_payload(outcome), make_officer_headers(officer))
    )


def accumulate_upheld_citations(api, zone_id, license_plate, count, disputing_household_id,
                                permit_id=None):
    """Issue -> dispute -> UPHELD, `count` times, on the same plate+zone.

    Returns the list of the resulting UPHELD citation dicts. The disputing
    household need not own the plate (disputes are Resident-role acts and the
    plate here is used only to accumulate the prior-upheld count / permit
    revocation cascade).
    """
    result = []
    for _ in range(count):
        cit = issue_citation(api, zone_id, license_plate, "NO_PERMIT" if permit_id is None else "EXPIRED_PERMIT",
                             permit_id=permit_id, officer="officer-1")
        dispute_citation(api, cit["id"], disputing_household_id)
        adjudicate_citation(api, cit["id"], "UPHELD", officer="officer-2")
        result.append(cit)
    return result


# ---------------------------------------------------------------------------
# Tier 5: visitor passes / complaints
# ---------------------------------------------------------------------------
def issue_visitor_pass(api, household_id, permit_id, valid_from, valid_until,
                       pass_type="TEMPORARY", guest_plate=None):
    """Resident issues a visitor pass under an ACTIVE permit. Returns the pass."""
    return get_success_data(
        api.create_visitor_pass(
            create_visitor_pass_payload(household_id, permit_id, valid_from, valid_until,
                                        pass_type=pass_type, guest_plate=guest_plate),
            make_resident_headers(household_id),
        )
    )


def file_complaint(api, zone_id, complaint_type="ILLEGAL_PARKING", description="test",
                   target_plate=None, resident_id="resident-x"):
    """File a complaint (Resident). Returns the Complaint dict."""
    return get_success_data(
        api.create_complaint(
            create_complaint_payload(zone_id, complaint_type, description, target_plate=target_plate),
            make_resident_headers(resident_id),
        )
    )


def resolve_complaint(api, complaint_id, outcome, resolution_note=None, officer="officer-1"):
    return get_success_data(
        api.resolve_complaint(complaint_id, resolve_complaint_payload(outcome, resolution_note),
                              make_officer_headers(officer))
    )
