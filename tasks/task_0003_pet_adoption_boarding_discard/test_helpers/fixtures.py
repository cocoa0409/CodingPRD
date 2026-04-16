"""
Composite setup helpers for multi-step test prerequisites.
Uses get_success_data() (lenient validator) so setup failures produce clear errors.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_shelter_payload,
    create_animal_payload,
    create_cat_payload,
    create_rabbit_payload,
    create_bird_payload,
    create_vaccination_record_payload,
    create_adopter_payload,
    create_adoption_application_payload,
    create_home_visit_payload,
    create_home_visit_assessment_payload,
    create_boarding_reservation_payload,
    create_compliance_hold_payload,
    create_fee_schedule_payload,
    create_payment_payload,
    create_resolve_hold_payload,
    create_rejection_payload,
)
from .constants import (
    SPECIES_VACCINE_MAP,
    DEFAULT_ADOPTION_BASE_FEE,
    DEFAULT_BOARDING_DAILY_RATE,
    DEFAULT_SPECIAL_NEEDS_SURCHARGE,
    DEFAULT_LOYALTY_DISCOUNT_RATE,
    DEFAULT_TAX_RATE,
)
from .test_users import TEST_USERS


def _future_iso(days=365):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _past_iso(days=30):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


# ─── Tier 1: Basic Entity Creation ──────────────────────────────────────────


def create_shelter(**overrides):
    """Create a shelter. Returns shelter data dict."""
    payload = create_shelter_payload(**overrides)
    res = api_client.create_shelter(payload, TEST_USERS["manager_headers"])
    return get_success_data(res)


def create_shelter_with_fee_schedules(
    boarding_capacity=20,
    adoption_base_fee=DEFAULT_ADOPTION_BASE_FEE,
    boarding_daily_rate=DEFAULT_BOARDING_DAILY_RATE,
    special_needs_surcharge=DEFAULT_SPECIAL_NEEDS_SURCHARGE,
    loyalty_discount_rate=DEFAULT_LOYALTY_DISCOUNT_RATE,
    tax_rate=DEFAULT_TAX_RATE,
):
    """Create a shelter with a full set of fee schedules for DOG. Returns shelter."""
    shelter = create_shelter(boarding_capacity=boarding_capacity, tax_rate=tax_rate)
    shelter_id = shelter["id"]
    mgr = TEST_USERS["manager_headers"]

    # Adoption base fees per species
    for species in ["DOG", "CAT", "RABBIT", "BIRD", "OTHER"]:
        api_client.create_fee_schedule(
            create_fee_schedule_payload(
                shelter_id,
                fee_type="ADOPTION_BASE",
                species=species,
                amount=adoption_base_fee,
            ),
            mgr,
        )

    # Boarding daily rates per species
    for species in ["DOG", "CAT", "RABBIT", "BIRD", "OTHER"]:
        api_client.create_fee_schedule(
            create_fee_schedule_payload(
                shelter_id,
                fee_type="BOARDING_DAILY",
                species=species,
                amount=boarding_daily_rate,
            ),
            mgr,
        )

    # Special needs surcharge per species
    for species in ["DOG", "CAT", "RABBIT", "BIRD", "OTHER"]:
        api_client.create_fee_schedule(
            create_fee_schedule_payload(
                shelter_id,
                fee_type="SPECIAL_NEEDS_SURCHARGE",
                species=species,
                amount=special_needs_surcharge,
            ),
            mgr,
        )

    # Loyalty discount (ALL species)
    api_client.create_fee_schedule(
        create_fee_schedule_payload(
            shelter_id,
            fee_type="LOYALTY_DISCOUNT",
            species="ALL",
            amount=loyalty_discount_rate,
        ),
        mgr,
    )

    return shelter


def create_animal_in_shelter(shelter_id, species="DOG", **overrides):
    """Register an animal at a shelter. Returns animal in INTAKE status."""
    if species == "CAT":
        payload = create_cat_payload(shelter_id, **overrides)
    elif species == "RABBIT":
        payload = create_rabbit_payload(shelter_id, **overrides)
    elif species == "BIRD":
        payload = create_bird_payload(shelter_id, **overrides)
    else:
        payload = create_animal_payload(shelter_id, species=species, **overrides)
    res = api_client.create_animal(payload, TEST_USERS["caseworker_headers"])
    return get_success_data(res)


def vaccinate_animal(animal_id, species="DOG", include_bordetella_for_boarding=False):
    """
    Add all required vaccination records for the given species.
    If include_bordetella_for_boarding is True, also adds BORDETELLA even if not
    required by the species default schedule (needed for boarding).
    Returns list of vaccination record dicts.
    """
    vet = TEST_USERS["vet_headers"]
    required = list(SPECIES_VACCINE_MAP.get(species, []))
    if include_bordetella_for_boarding and "BORDETELLA" not in required and species != "BIRD":
        required.append("BORDETELLA")

    records = []
    for vaccine in required:
        payload = create_vaccination_record_payload(
            animal_id,
            vaccine_name=vaccine,
            administered_date=_past_iso(days=30),
            expiry_date=_future_iso(days=365),
            batch_number=f"BATCH-{vaccine}-001",
        )
        rec = get_success_data(api_client.create_vaccination_record(payload, vet))
        records.append(rec)
    return records


def make_animal_available(animal_id):
    """Transition animal from INTAKE to AVAILABLE. Returns updated animal."""
    res = api_client.make_animal_available(animal_id, TEST_USERS["caseworker_headers"])
    return get_success_data(res)


def create_available_animal(shelter_id, species="DOG", include_bordetella=False, **overrides):
    """Create animal, vaccinate, and make available. Returns available animal."""
    animal = create_animal_in_shelter(shelter_id, species=species, **overrides)
    vaccinate_animal(animal["id"], species=species, include_bordetella_for_boarding=include_bordetella)
    return make_animal_available(animal["id"])


def create_adopter_in_shelter(shelter_id, **overrides):
    """Register an adopter at a shelter. Returns adopter data."""
    payload = create_adopter_payload(shelter_id, **overrides)
    res = api_client.create_adopter(payload, TEST_USERS["caseworker_headers"])
    return get_success_data(res)


# ─── Tier 2: Application Workflow Helpers ────────────────────────────────────


def submit_application(animal_id, adopter_id, **overrides):
    """Submit an adoption application. Returns application in SUBMITTED status."""
    payload = create_adoption_application_payload(animal_id, adopter_id, **overrides)
    res = api_client.create_adoption_application(payload, TEST_USERS["caseworker_headers"])
    return get_success_data(res)


def start_application_review(application_id, caseworker_headers=None):
    """Start review on an application. Returns application in UNDER_REVIEW."""
    headers = caseworker_headers or TEST_USERS["caseworker_headers"]
    res = api_client.start_review(application_id, headers)
    return get_success_data(res)


def require_home_visit_on_application(application_id, caseworker_headers=None):
    """Flag application as requiring home visit. Returns application in HOME_VISIT_REQUIRED."""
    headers = caseworker_headers or TEST_USERS["caseworker_headers"]
    res = api_client.require_home_visit(application_id, headers)
    return get_success_data(res)


def complete_application_review(application_id, caseworker_headers=None):
    """Complete review. Returns application in REVIEWED status."""
    headers = caseworker_headers or TEST_USERS["caseworker_headers"]
    res = api_client.complete_review(application_id, headers)
    return get_success_data(res)


def approve_application(application_id, manager_headers=None):
    """Approve an application. Returns application in APPROVED status."""
    headers = manager_headers or TEST_USERS["manager_headers"]
    res = api_client.approve_application(application_id, headers)
    return get_success_data(res)


def complete_adoption(application_id, caseworker_headers=None):
    """Complete adoption. Returns application in COMPLETED status."""
    headers = caseworker_headers or TEST_USERS["caseworker_headers"]
    res = api_client.complete_application(application_id, headers)
    return get_success_data(res)


def application_to_reviewed(animal_id, adopter_id, species="DOG", **overrides):
    """
    Create and walk an application through to REVIEWED status.
    For DOG species, this includes scheduling and completing a home visit with PASS.
    Returns (application, adopter).
    """
    cw = TEST_USERS["caseworker_headers"]
    app = submit_application(animal_id, adopter_id, **overrides)
    app = start_application_review(app["id"], cw)

    if species == "DOG":
        # Require home visit -> schedule -> complete with PASS
        app = require_home_visit_on_application(app["id"], cw)
        visit = schedule_home_visit(adopter_id, app["id"])
        complete_home_visit_with_result(visit["id"], result="PASS")
        # Application should now be REVIEWED
        app = get_success_data(api_client.get_adoption_application(app["id"], cw))
    else:
        # For CAT, BIRD, RABBIT: no home visit needed, complete review directly
        app = complete_application_review(app["id"], cw)

    return app


def application_to_approved(shelter_id, species="DOG", animal_overrides=None, adopter_overrides=None):
    """
    Full setup: shelter + animal + adopter + application through to APPROVED.
    Fee schedules must already exist for the shelter.
    Returns (application, animal, adopter, shelter_id).
    """
    animal = create_available_animal(shelter_id, species=species, **(animal_overrides or {}))
    adopter = create_adopter_in_shelter(shelter_id, **(adopter_overrides or {}))
    app = application_to_reviewed(animal["id"], adopter["id"], species=species)
    app = approve_application(app["id"])
    return app, animal, adopter


def full_adoption_lifecycle(shelter_id=None, species="DOG", animal_overrides=None, adopter_overrides=None):
    """
    Complete adoption lifecycle: shelter -> animal -> adopter -> application -> reviewed
    -> approved -> fee paid -> completed.
    If shelter_id is None, creates a new shelter with fee schedules.
    Returns (application, animal, adopter, shelter).
    """
    if shelter_id is None:
        shelter = create_shelter_with_fee_schedules()
        shelter_id = shelter["id"]
    else:
        shelter = get_success_data(
            api_client.get_shelter(shelter_id, TEST_USERS["manager_headers"])
        )

    app, animal, adopter = application_to_approved(
        shelter_id, species=species,
        animal_overrides=animal_overrides,
        adopter_overrides=adopter_overrides,
    )

    # Pay the fee invoice
    invoice = get_success_data(
        api_client.get_fee_invoice(app["fee_invoice_id"], TEST_USERS["caseworker_headers"])
    )
    api_client.pay_invoice(
        invoice["id"],
        create_payment_payload(invoice["total_amount"]),
        TEST_USERS["caseworker_headers"],
    )

    # Complete adoption
    app = complete_adoption(app["id"])
    return app, animal, adopter, shelter


# ─── Tier 2b: Home Visit Helpers ────────────────────────────────────────────


def schedule_home_visit(adopter_id, application_id, **overrides):
    """Schedule a home visit. Returns home visit in SCHEDULED status."""
    payload = create_home_visit_payload(adopter_id, application_id, **overrides)
    res = api_client.create_home_visit(payload, TEST_USERS["caseworker_headers"])
    return get_success_data(res)


def complete_home_visit_with_result(
    home_visit_id, result="PASS", caseworker_headers=None
):
    """
    Complete a home visit with assessment fields that produce the desired result.
    result: 'PASS' (score >= 70), 'CONDITIONAL_PASS' (50-69), 'FAIL' (< 50)
    Returns completed home visit.
    """
    headers = caseworker_headers or TEST_USERS["caseworker_headers"]
    if result == "PASS":
        assessment = create_home_visit_assessment_payload(
            yard_adequate=True,
            space_adequate=True,
            safety_hazards_found=False,
            existing_pets_compatible=True,
        )  # score = 25+30+25+20 = 100
    elif result == "CONDITIONAL_PASS":
        assessment = create_home_visit_assessment_payload(
            yard_adequate=True,
            space_adequate=True,
            safety_hazards_found=True,  # -25
            existing_pets_compatible=False,  # -20
        )  # score = 25+30+0+0 = 55
    else:  # FAIL
        assessment = create_home_visit_assessment_payload(
            yard_adequate=False,
            space_adequate=False,
            safety_hazards_found=True,
            existing_pets_compatible=False,
        )  # score = 0+0+0+0 = 0

    res = api_client.complete_home_visit(home_visit_id, assessment, headers)
    return get_success_data(res)


# ─── Tier 3: Boarding Workflow Helpers ───────────────────────────────────────


def create_boarding_reservation(shelter_id, animal_id, **overrides):
    """Create a boarding reservation. Returns reservation in REQUESTED status."""
    payload = create_boarding_reservation_payload(shelter_id, animal_id, **overrides)
    res = api_client.create_boarding_reservation(payload, TEST_USERS["caseworker_headers"])
    return get_success_data(res)


def confirm_boarding(reservation_id, manager_headers=None):
    """Confirm a boarding reservation. Returns reservation in CONFIRMED status."""
    headers = manager_headers or TEST_USERS["manager_headers"]
    res = api_client.confirm_boarding_reservation(reservation_id, headers)
    return get_success_data(res)


def check_in_boarding(reservation_id, caseworker_headers=None):
    """Check in an animal. Returns reservation in CHECKED_IN status."""
    headers = caseworker_headers or TEST_USERS["caseworker_headers"]
    res = api_client.check_in_boarding(reservation_id, headers)
    return get_success_data(res)


def check_out_boarding(reservation_id, caseworker_headers=None):
    """Check out an animal. Returns reservation in CHECKED_OUT status."""
    headers = caseworker_headers or TEST_USERS["caseworker_headers"]
    res = api_client.check_out_boarding(reservation_id, headers)
    return get_success_data(res)


def setup_boarding_through_check_in(shelter_id=None, species="DOG", animal_overrides=None):
    """
    Full boarding setup through CHECK_IN:
    shelter (with fees) -> animal (vaccinated for boarding) -> reservation -> confirm -> check_in.
    Returns (reservation, animal, shelter).
    """
    if shelter_id is None:
        shelter = create_shelter_with_fee_schedules()
        shelter_id = shelter["id"]
    else:
        shelter = get_success_data(
            api_client.get_shelter(shelter_id, TEST_USERS["manager_headers"])
        )

    animal = create_available_animal(
        shelter_id, species=species, include_bordetella=True,
        **(animal_overrides or {}),
    )
    reservation = create_boarding_reservation(shelter_id, animal["id"])
    reservation = confirm_boarding(reservation["id"])
    reservation = check_in_boarding(reservation["id"])
    return reservation, animal, shelter


def setup_boarding_full_cycle(shelter_id=None, species="DOG", animal_overrides=None):
    """
    Full boarding cycle through CHECK_OUT.
    Returns (reservation, animal, shelter).
    """
    reservation, animal, shelter = setup_boarding_through_check_in(
        shelter_id=shelter_id, species=species, animal_overrides=animal_overrides,
    )
    reservation = check_out_boarding(reservation["id"])
    return reservation, animal, shelter


# ─── Tier 4: Compliance Hold Helpers ────────────────────────────────────────


def create_hold_on_animal(animal_id, severity="HIGH", hold_type="HEALTH_CONCERN",
                          creator_headers=None):
    """Create a compliance hold. Returns hold in ACTIVE status."""
    headers = creator_headers or TEST_USERS["vet_headers"]
    payload = create_compliance_hold_payload(
        animal_id, severity=severity, hold_type=hold_type,
    )
    res = api_client.create_compliance_hold(payload, headers)
    return get_success_data(res)


def resolve_hold(hold_id, manager_headers=None, **overrides):
    """Resolve a compliance hold. Returns hold in RESOLVED status."""
    headers = manager_headers or TEST_USERS["manager_headers"]
    payload = create_resolve_hold_payload(**overrides)
    res = api_client.resolve_compliance_hold(hold_id, payload, headers)
    return get_success_data(res)


# ─── Tier 5: Fee / Invoice Helpers ──────────────────────────────────────────


def pay_invoice_fully(invoice_id, caseworker_headers=None):
    """Pay an invoice in full. Returns paid invoice."""
    headers = caseworker_headers or TEST_USERS["caseworker_headers"]
    invoice = get_success_data(api_client.get_fee_invoice(invoice_id, headers))
    amount = invoice["balance_due"]
    if amount > 0:
        res = api_client.pay_invoice(
            invoice_id, create_payment_payload(amount), headers,
        )
        return get_success_data(res)
    return invoice


def setup_fee_schedules_for_shelter(shelter_id, **overrides):
    """Create a standard set of fee schedules for a shelter."""
    mgr = TEST_USERS["manager_headers"]
    adoption_base = overrides.get("adoption_base_fee", DEFAULT_ADOPTION_BASE_FEE)
    boarding_daily = overrides.get("boarding_daily_rate", DEFAULT_BOARDING_DAILY_RATE)
    surcharge = overrides.get("special_needs_surcharge", DEFAULT_SPECIAL_NEEDS_SURCHARGE)
    loyalty_rate = overrides.get("loyalty_discount_rate", DEFAULT_LOYALTY_DISCOUNT_RATE)

    for species in ["DOG", "CAT", "RABBIT", "BIRD", "OTHER"]:
        api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter_id, fee_type="ADOPTION_BASE",
                                        species=species, amount=adoption_base), mgr)
        api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter_id, fee_type="BOARDING_DAILY",
                                        species=species, amount=boarding_daily), mgr)
        api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter_id, fee_type="SPECIAL_NEEDS_SURCHARGE",
                                        species=species, amount=surcharge), mgr)

    api_client.create_fee_schedule(
        create_fee_schedule_payload(shelter_id, fee_type="LOYALTY_DISCOUNT",
                                    species="ALL", amount=loyalty_rate), mgr)


# ─── Tier 5b: Repeat-Adopter Helpers ────────────────────────────────────────


def create_repeat_adopter(shelter_id, completed_adoptions=2, species="CAT"):
    """
    Create an adopter who has completed `completed_adoptions` adoptions.
    Uses CAT by default since it skips the home visit requirement.
    Returns (adopter, shelter_id).
    """
    adopter = create_adopter_in_shelter(shelter_id)
    for _ in range(completed_adoptions):
        animal = create_available_animal(shelter_id, species=species)
        app = application_to_reviewed(animal["id"], adopter["id"], species=species)
        app = approve_application(app["id"])
        pay_invoice_fully(app["fee_invoice_id"])
        complete_adoption(app["id"])
    # Re-fetch adopter to get updated adoption_history_count
    adopter = get_success_data(
        api_client.get_adopter(adopter["id"], TEST_USERS["caseworker_headers"])
    )
    return adopter
