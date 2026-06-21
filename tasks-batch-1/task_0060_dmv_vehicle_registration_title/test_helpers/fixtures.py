"""Composite setup helpers.

Each helper builds multi-step preconditions from scratch using only PRD-declared
endpoints, so tests can focus on assertions. All setup calls use get_success_data()
(lenient) so a broken precondition surfaces as a clear "Setup step failed" error.

The runner restarts the server (empty DB) before every test, so every helper starts
from nothing.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_owner_headers
from .factories import (
    create_owner_payload,
    create_vehicle_payload,
    create_vin_verification_payload,
    create_title_application_payload,
    create_salvage_inspection_payload,
    create_emissions_inspection_payload,
    create_lien_payload,
    create_registration_payload,
    create_fee_assessment_payload,
    create_license_plate_payload,
    create_real_id_application_payload,
    unique_vin,
)
from .constants import DEFAULT_CLOCK_ISO

CLERK = TEST_USERS["clerk_headers"]
ADMIN = TEST_USERS["admin_headers"]
INSPECTION = TEST_USERS["inspection_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso=DEFAULT_CLOCK_ISO):
    """Pin the server's logical clock. Returns the response data."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 / 2: base entities
# ---------------------------------------------------------------------------
def create_owner(**overrides):
    """Create an owner. Returns the owner dict."""
    return get_success_data(api_client.create_owner(create_owner_payload(**overrides), CLERK))


def create_vehicle(owner_id=None, **overrides):
    """Create an owner (if owner_id not given) and a vehicle. Returns the vehicle dict."""
    if owner_id is None:
        owner_id = create_owner()["id"]
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(owner_id, **overrides), CLERK)
    )


def create_verified_vehicle(owner_id=None, **overrides):
    """Create a vehicle and record a MATCH VIN verification so vin_status == VERIFIED.
    Returns the refreshed vehicle dict."""
    veh = create_vehicle(owner_id=owner_id, **overrides)
    get_success_data(
        api_client.create_vin_verification(
            create_vin_verification_payload(veh["id"], veh["vin"], "MATCH"), CLERK
        )
    )
    return get_success_data(api_client.get_vehicle(veh["id"], CLERK))


# ---------------------------------------------------------------------------
# Tier 3: title lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_approved_title(vehicle_id, applicant_owner_id, application_type="INITIAL"):
    """Create a title application and drive it DRAFT -> SUBMITTED -> APPROVED
    (clear path; vehicle must be VIN-verified). Returns the application dict."""
    ta = get_success_data(
        api_client.create_title_application(
            create_title_application_payload(vehicle_id, applicant_owner_id, application_type), CLERK
        )
    )
    get_success_data(api_client.submit_title_application(ta["id"], CLERK))
    get_success_data(api_client.approve_title_application(ta["id"], CLERK))
    return get_success_data(api_client.get_title_application(ta["id"], CLERK))


def issue_clear_title(vehicle_id, applicant_owner_id, application_type="INITIAL"):
    """Drive a clear-path title all the way to ISSUED for the vehicle/owner.
    Returns the issued application dict."""
    ta = create_approved_title(vehicle_id, applicant_owner_id, application_type)
    get_success_data(api_client.issue_title_application(ta["id"], CLERK))
    return get_success_data(api_client.get_title_application(ta["id"], CLERK))


def setup_titled_vehicle(county="KING", model_year=2024, vehicle_class="PASSENGER",
                         msrp_cents=3200000, purchase_price_cents=3000000,
                         is_salvage_branded=False):
    """Owner + VIN-verified vehicle + an INITIAL CLEAR title ISSUED to that owner.
    Returns (owner, vehicle) with the vehicle refreshed (title_status == CLEAR)."""
    owner = create_owner(residence_county_code=county)
    veh = create_verified_vehicle(
        owner_id=owner["id"], model_year=model_year, vehicle_class=vehicle_class,
        msrp_cents=msrp_cents, purchase_price_cents=purchase_price_cents,
        is_salvage_branded=is_salvage_branded,
    )
    issue_clear_title(veh["id"], owner["id"], "INITIAL")
    veh = get_success_data(api_client.get_vehicle(veh["id"], CLERK))
    return owner, veh


def create_salvage_hold_title(vehicle_id, applicant_owner_id):
    """Create + submit a title on a salvage-branded VIN-verified vehicle, forking to
    SALVAGE_HOLD. Returns the application dict."""
    ta = get_success_data(
        api_client.create_title_application(
            create_title_application_payload(vehicle_id, applicant_owner_id, "INITIAL"), CLERK
        )
    )
    get_success_data(api_client.submit_title_application(ta["id"], CLERK))
    return get_success_data(api_client.get_title_application(ta["id"], CLERK))


# ---------------------------------------------------------------------------
# Tier 3: lien helpers
# ---------------------------------------------------------------------------
def create_filed_lien(vehicle_id, **overrides):
    """File a lien on a vehicle. Returns the lien dict (status FILED)."""
    return get_success_data(
        api_client.create_lien(create_lien_payload(vehicle_id, **overrides), CLERK)
    )


def create_perfected_lien(vehicle_id, **overrides):
    """File and perfect a lien on a titled vehicle. Returns the perfected lien dict."""
    lien = create_filed_lien(vehicle_id, **overrides)
    get_success_data(api_client.perfect_lien(lien["id"], CLERK))
    return get_success_data(api_client.get_lien(lien["id"], CLERK))


# ---------------------------------------------------------------------------
# Tier 3 / 4: fee + registration lifecycle
# ---------------------------------------------------------------------------
def create_registration(vehicle_id, owner_id, registration_type="INITIAL", **overrides):
    """Create a registration (PENDING_FEES). Returns the registration dict."""
    return get_success_data(
        api_client.create_registration(
            create_registration_payload(vehicle_id, owner_id, registration_type, **overrides), CLERK
        )
    )


def assess_fees(registration_id):
    """Create a FeeAssessment for the registration. Returns the assessment dict."""
    return get_success_data(
        api_client.create_fee_assessment(create_fee_assessment_payload(registration_id), CLERK)
    )


def assess_and_pay_fees(registration_id):
    """Assess + pay fees. Returns the PAID assessment dict."""
    fa = assess_fees(registration_id)
    get_success_data(api_client.pay_fee_assessment(fa["id"], CLERK))
    return get_success_data(api_client.get_fee_assessment(fa["id"], CLERK))


def setup_active_registration(county="KING", model_year=2008, vehicle_class="PASSENGER",
                              clock=DEFAULT_CLOCK_ISO):
    """Full path to an ACTIVE registration on an emissions-exempt vehicle (default
    model_year 2008 so no emissions inspection is required):
    clock -> owner -> verified vehicle -> ISSUED title -> registration -> fees paid -> activate.

    Returns (owner, vehicle, registration) with the registration refreshed (status ACTIVE,
    version carries the post-activation value).
    """
    set_clock(clock)
    owner, veh = setup_titled_vehicle(
        county=county, model_year=model_year, vehicle_class=vehicle_class
    )
    reg = create_registration(veh["id"], owner["id"], "INITIAL")
    assess_and_pay_fees(reg["id"])
    get_success_data(api_client.activate_registration(reg["id"], CLERK))
    reg = get_success_data(api_client.get_registration(reg["id"], CLERK))
    return owner, veh, reg


def setup_pending_registration_paid(county="KING", model_year=2008, vehicle_class="PASSENGER",
                                    clock=DEFAULT_CLOCK_ISO, issue_title=True):
    """Registration in PENDING_FEES with fees PAID. If issue_title is False, the title
    is only driven to APPROVED (not ISSUED) so activation will fail ERR_TITLE_NOT_ISSUED.
    Returns (owner, vehicle, registration, fee_assessment)."""
    set_clock(clock)
    owner = create_owner(residence_county_code=county)
    veh = create_verified_vehicle(owner_id=owner["id"], model_year=model_year,
                                  vehicle_class=vehicle_class)
    if issue_title:
        issue_clear_title(veh["id"], owner["id"], "INITIAL")
    else:
        create_approved_title(veh["id"], owner["id"], "INITIAL")
    veh = get_success_data(api_client.get_vehicle(veh["id"], CLERK))
    reg = create_registration(veh["id"], owner["id"], "INITIAL")
    fa = assess_and_pay_fees(reg["id"])
    return owner, veh, reg, fa


# ---------------------------------------------------------------------------
# Tier 3: plate helpers
# ---------------------------------------------------------------------------
def assign_plate(registration_id, plate_number, plate_type, expected_version):
    """Assign a plate to a registration (status ISSUED). Returns the plate dict."""
    return get_success_data(
        api_client.create_license_plate(
            create_license_plate_payload(registration_id, plate_number, plate_type, expected_version),
            CLERK,
        )
    )


def setup_active_registration_with_plate(plate_type="ELECTRONIC", plate_number="PLATE-0001",
                                         activate_plate=True, clock=DEFAULT_CLOCK_ISO):
    """ACTIVE registration carrying one plate of plate_type. If activate_plate, the plate
    is driven ISSUED -> ACTIVE.
    Returns (owner, vehicle, registration, plate) with registration + plate refreshed."""
    owner, veh, reg = setup_active_registration(clock=clock)
    plate = assign_plate(reg["id"], plate_number, plate_type, reg["version"])
    if activate_plate:
        get_success_data(api_client.activate_license_plate(plate["id"], CLERK))
    plate = get_success_data(api_client.get_license_plate(plate["id"], CLERK))
    reg = get_success_data(api_client.get_registration(reg["id"], CLERK))
    return owner, veh, reg, plate


# ---------------------------------------------------------------------------
# Tier 3: REAL ID lifecycle
# ---------------------------------------------------------------------------
def setup_real_id_under_review(identity_verified=True, documents_complete=True):
    """Owner + REAL ID application driven SUBMITTED -> UNDER_REVIEW.
    Returns (owner, real_id_application) with the application refreshed."""
    owner = create_owner(identity_documents_verified=identity_verified)
    rid = get_success_data(
        api_client.create_real_id_application(
            create_real_id_application_payload(owner["id"], documents_complete=documents_complete),
            CLERK,
        )
    )
    get_success_data(api_client.begin_review_real_id_application(rid["id"], CLERK))
    rid = get_success_data(api_client.get_real_id_application(rid["id"], CLERK))
    return owner, rid
