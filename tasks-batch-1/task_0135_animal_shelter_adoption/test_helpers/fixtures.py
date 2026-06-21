"""Composite setup helpers.

Every test runs against a freshly-restarted, empty server. These helpers build
the multi-step preconditions each test needs from scratch using only
PRD-declared endpoints. They use get_success_data() (lenient) internally so
setup failures surface as clear "Setup step failed" errors.

Identity threading: AdopterAccount is the only entity-backed role. Ownership-gated
Adopter calls use make_adopter_headers(adopter["id"]); the five operational roles
are opaque and use the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_shelter_payload,
    create_kennel_payload,
    create_animal_payload,
    create_intake_record_payload,
    create_kennel_assignment_payload,
    create_medical_record_payload,
    create_microchip_payload,
    create_owner_claim_payload,
    create_adopter_account_payload,
    create_adoption_application_payload,
    create_foster_home_payload,
    create_foster_placement_payload,
    create_euthanasia_decision_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_veterinarian_headers,
    make_adoption_counselor_headers,
    make_adopter_headers,
)

ADMIN = TEST_USERS["shelter_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
VET = TEST_USERS["veterinarian_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]
FOSTER = TEST_USERS["foster_coordinator_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# ─── Tier 0: bootstrap primitives ─────────────────────

def set_clock(to_iso8601):
    """Set the server logical clock. Returns the echoed clock data."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def bootstrap_shelter(clock=DEFAULT_CLOCK, **shelter_overrides):
    """Create the shelter, then set the logical clock. Returns the Shelter dict.

    A shelter must always exist before time-sensitive flows; the clock is set
    immediately afterward so intake_at / start_at stamps are deterministic.
    """
    shelter = get_success_data(
        api_client.create_shelter(create_shelter_payload(**shelter_overrides), ADMIN)
    )
    if clock is not None:
        set_clock(clock)
    return shelter


def create_kennel(capacity=1, label="K-1"):
    """Create a kennel. Returns the Kennel dict (carries version for OCC)."""
    return get_success_data(
        api_client.create_kennel(create_kennel_payload(label=label, capacity=capacity), ADMIN)
    )


def create_adopter(email="adopter@example.com", full_name="Adopter Person"):
    """Register an adopter account. Returns the AdopterAccount dict."""
    return get_success_data(
        api_client.create_adopter_account(
            create_adopter_account_payload(email=email, full_name=full_name), COUNSELOR
        )
    )


def create_foster_home(max_concurrent=2, cooldown_days=3, contact_name="Foster Family"):
    """Register a foster home. Returns the FosterHome dict."""
    return get_success_data(
        api_client.create_foster_home(
            create_foster_home_payload(
                contact_name=contact_name,
                max_concurrent=max_concurrent,
                cooldown_days=cooldown_days,
            ),
            FOSTER,
        )
    )


# ─── Tier 1: Animal state progression ─────────────────

def register_animal(name="Animal", species="DOG", age_months=36):
    """POST /animals only. Animal is INTAKE_PENDING / UNEXAMINED. Returns Animal dict."""
    return get_success_data(
        api_client.create_animal(
            create_animal_payload(name=name, species=species, age_months=age_months), INTAKE
        )
    )


def intake_animal(animal_id, source="SURRENDER", surrendering_party="Owner"):
    """Record an intake -> drives the animal to IN_CUSTODY. Returns IntakeRecord dict."""
    payload = create_intake_record_payload(
        animal_id, source=source, surrendering_party=surrendering_party
    )
    if source == "STRAY":
        payload.pop("surrendering_party", None)
    return get_success_data(api_client.create_intake_record(payload, INTAKE))


def create_intaken_animal(species="DOG", age_months=36, source="SURRENDER", name="Animal"):
    """register + intake. Animal IN_CUSTODY, UNEXAMINED. Returns the Animal dict (re-read)."""
    animal = register_animal(name=name, species=species, age_months=age_months)
    intake_animal(animal["id"], source=source)
    return get_success_data(api_client.get_animal(animal["id"], INTAKE))


def clear_medical(animal_id):
    """Record an EXAM/CLEAR -> medical_status CLEARED. Returns MedicalRecord dict."""
    return get_success_data(
        api_client.create_medical_record(
            create_medical_record_payload(animal_id, record_type="EXAM", outcome="CLEAR"), VET
        )
    )


def hold_medical(animal_id):
    """Record an EXAM/HOLD -> medical_status NEEDS_TREATMENT. Returns MedicalRecord dict."""
    return get_success_data(
        api_client.create_medical_record(
            create_medical_record_payload(animal_id, record_type="EXAM", outcome="HOLD"), VET
        )
    )


def microchip_animal(animal_id, chip_number="CHIP-DEFAULT", owner_name=None):
    """Register a microchip -> Animal.microchipped becomes true. Returns Microchip dict."""
    kwargs = {}
    if owner_name is not None:
        kwargs["owner_name"] = owner_name
    return get_success_data(
        api_client.create_microchip(
            create_microchip_payload(animal_id, chip_number, **kwargs), VET
        )
    )


def make_animal_available(animal_id):
    """make-available -> AVAILABLE (animal must already be CLEARED + hold elapsed). Returns Animal dict."""
    return get_success_data(api_client.make_available(animal_id, COUNSELOR))


def create_available_animal(species="DOG", age_months=36, source="SURRENDER",
                            name="Animal", microchipped=False, chip_number="CHIP-AVAIL"):
    """Full path to AVAILABLE: register -> intake -> (chip) -> clear -> make-available.

    For SURRENDER/TRANSFER the stray-hold is zero, so make-available passes at the
    default clock without advancing it. Returns the Animal dict (re-read).
    """
    animal = register_animal(name=name, species=species, age_months=age_months)
    intake_animal(animal["id"], source=source)
    if microchipped:
        microchip_animal(animal["id"], chip_number=chip_number)
    clear_medical(animal["id"])
    make_animal_available(animal["id"])
    return get_success_data(api_client.get_animal(animal["id"], INTAKE))


# ─── Tier 2: Kennel assignment hierarchy ──────────────

def assign_kennel(kennel_id, animal_id, expected_kennel_version):
    """POST /kennel-assignments. Returns the KennelAssignment dict."""
    return get_success_data(
        api_client.create_kennel_assignment(
            create_kennel_assignment_payload(kennel_id, animal_id, expected_kennel_version), INTAKE
        )
    )


def setup_kennel_with_active_assignment(capacity=1, species="DOG", age_months=36,
                                        source="SURRENDER", label="K-1"):
    """Kennel + intaken animal + one ACTIVE assignment.

    Returns (kennel_after, animal, assignment). kennel_after is re-read so its
    version reflects the +1 from the assignment.
    """
    kennel = create_kennel(capacity=capacity, label=label)
    animal = create_intaken_animal(species=species, age_months=age_months, source=source)
    assignment = assign_kennel(kennel["id"], animal["id"], kennel["version"])
    kennel_after = get_success_data(api_client.get_kennel(kennel["id"], INTAKE))
    return kennel_after, animal, assignment


# ─── Tier 3: Adoption pipeline shortcuts ──────────────

def submit_application(animal_id, adopter_id):
    """POST /adoption-applications -> SUBMITTED. Returns AdoptionApplication dict."""
    return get_success_data(
        api_client.create_adoption_application(
            create_adoption_application_payload(animal_id, adopter_id), COUNSELOR
        )
    )


def setup_submitted_application(species="DOG", age_months=36, microchipped=False,
                                chip_number="CHIP-APP", email="app@example.com",
                                **shelter_overrides):
    """Available animal + adopter + SUBMITTED application.

    Returns (animal, adopter, application). Shelter is bootstrapped here so the
    caller controls promo_active / board rates via shelter_overrides.
    """
    bootstrap_shelter(**shelter_overrides)
    animal = create_available_animal(
        species=species, age_months=age_months, microchipped=microchipped, chip_number=chip_number
    )
    adopter = create_adopter(email=email)
    app = submit_application(animal["id"], adopter["id"])
    return animal, adopter, app


def approve_application(app_id):
    """POST /approve -> APPROVED. Returns AdoptionApplication dict."""
    return get_success_data(api_client.approve_adoption_application(app_id, COUNSELOR))


def setup_approved_application(species="DOG", age_months=36, microchipped=False,
                               chip_number="CHIP-APP", email="app@example.com",
                               **shelter_overrides):
    """Available animal + adopter + APPROVED application.

    Returns (animal, adopter, application). The application is approved after the
    optional microchip is registered so the final-fee divergence can be exercised.
    """
    animal, adopter, app = setup_submitted_application(
        species=species, age_months=age_months, microchipped=microchipped,
        chip_number=chip_number, email=email, **shelter_overrides
    )
    approve_application(app["id"])
    app = get_success_data(api_client.get_adoption_application(app["id"], COUNSELOR))
    return animal, adopter, app


def finalize_application(app_id):
    """POST /finalize -> FINALIZED (cascade to ADOPTED). Returns AdoptionApplication dict."""
    return get_success_data(api_client.finalize_adoption_application(app_id, COUNSELOR))


# ─── Tier 4: Foster placement ─────────────────────────

def place_foster(foster_home_id, animal_id):
    """POST /foster-placements -> ACTIVE (animal FOSTERED). Returns FosterPlacement dict."""
    return get_success_data(
        api_client.create_foster_placement(
            create_foster_placement_payload(foster_home_id, animal_id), FOSTER
        )
    )


def return_foster(placement_id):
    """POST /foster-placements/{id}/return -> RETURNED (animal AVAILABLE). Returns FosterPlacement dict."""
    return get_success_data(api_client.return_foster_placement(placement_id, FOSTER))


# ─── Tier 5: Euthanasia dual-control ──────────────────

def open_euthanasia(animal_id, reason="MEDICAL_UNTREATABLE", requester_user_id="counselor-1"):
    """POST /euthanasia-decisions -> REQUESTED. requested_by_user_id = requester_user_id.

    Returns the EuthanasiaDecision dict. The requester is an AdoptionCounselor by
    default; the X-User-ID is threaded so segregation-of-duties tests can control it.
    """
    headers = make_adoption_counselor_headers(requester_user_id)
    return get_success_data(
        api_client.create_euthanasia_decision(
            create_euthanasia_decision_payload(animal_id, reason=reason), headers
        )
    )


def approve_euthanasia(decision_id, approver_user_id="vet-2"):
    """POST /approve as a Veterinarian whose X-User-ID = approver_user_id. Returns decision dict."""
    headers = make_veterinarian_headers(approver_user_id)
    return get_success_data(api_client.approve_euthanasia_decision(decision_id, headers))


# ─── Owner-claim helper ───────────────────────────────

def open_owner_claim(animal_id, claimant_name="Owner", proof_chip_number=None):
    """POST /owner-claims -> PENDING. Returns OwnerClaim dict."""
    kwargs = {}
    if proof_chip_number is not None:
        kwargs["proof_chip_number"] = proof_chip_number
    return get_success_data(
        api_client.create_owner_claim(
            create_owner_claim_payload(animal_id, claimant_name=claimant_name, **kwargs), ADMIN
        )
    )
