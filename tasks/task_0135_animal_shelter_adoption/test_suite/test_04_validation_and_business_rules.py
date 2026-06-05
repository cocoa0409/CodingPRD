"""Validation ordering, cross-entity state dependencies, and business-rule errors.

Queue A rule 5 (priority-pair conflicts) and rule 7 (cross-entity state dependency),
plus queue B validations-section instances. The PRD pins a fixed validation order
(§2.7), so each dual-failure outcome is deterministic.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    bootstrap_shelter,
    set_clock,
    register_animal,
    intake_animal,
    create_intaken_animal,
    create_available_animal,
    create_kennel,
    create_adopter,
    submit_application,
    approve_application,
    clear_medical,
    microchip_animal,
    assign_kennel,
    open_owner_claim,
    open_euthanasia,
    approve_euthanasia,
    make_veterinarian_headers,
    make_adoption_counselor_headers,
    TEST_USERS,
)
from test_helpers.factories import (
    create_kennel_assignment_payload,
    create_animal_payload,
    create_adopter_account_payload,
    create_microchip_payload,
)

ADMIN = TEST_USERS["shelter_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
VET = TEST_USERS["veterinarian_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]


# ===================================================================
# Rule 5 — priority-pair validation conflict
# ===================================================================

def test_make_available_state_check_beats_medical_clearance(api):
    """PRD §2.7: "first whether the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE), and then the domain-specific
    business constraints ... medical clearance ... In short: authentication, then
    authorization, then existence, then request shape, then transition legality, then
    business rules."
    PRD §3.5: "It is permitted only from lifecycle_status IN_CUSTODY."

    Design: Difficulty/priority_pair_validation_conflict/make_available_state_beats_medical_clearance
    """
    bootstrap_shelter()
    # Freshly registered: INTAKE_PENDING + UNEXAMINED. make-available violates both
    # the from-state precondition AND medical clearance.
    animal = validate_success(
        api_client.create_animal(create_animal_payload(name="Fresh", species="CAT", age_months=36), INTAKE),
        201,
    )
    resp = api_client.make_available(animal["id"], COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert after["lifecycle_status"] == "INTAKE_PENDING", "state unchanged"


def test_make_available_in_custody_but_unexamined_surfaces_medical_check(api):
    """PRD §2.7: "Only after all of the above does the system evaluate state and business
    rules: first whether the target resource is in a state from which the requested
    transition is defined (ERR_INVALID_STATE), and then the domain-specific business
    constraints."
    PRD §3.5: "The animal's medical_status must be CLEARED; if it is not, the request is
    rejected with ERR_NOT_MEDICALLY_CLEARED."

    Design: Difficulty/priority_pair_validation_conflict/make_available_state_beats_medical_clearance
    """
    bootstrap_shelter()
    # IN_CUSTODY (state precondition now SATISFIED) but UNEXAMINED: only the lower-
    # priority medical-clearance rule fails, so its error surfaces — confirming the
    # state check is exactly what flipped the prior test to ERR_INVALID_STATE.
    animal = create_intaken_animal(species="CAT", age_months=36, source="SURRENDER", name="InCust")
    assert animal["lifecycle_status"] == "IN_CUSTODY"
    assert animal["medical_status"] == "UNEXAMINED"
    resp = api_client.make_available(animal["id"], COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_NOT_MEDICALLY_CLEARED.value)


def test_kennel_assign_existence_check_beats_occupancy(api):
    """PRD §2.6: "the first unresolved identifier — whether a path id or a body foreign
    key — causes the request to be rejected with ERR_NOT_FOUND before any later
    reference is considered."
    PRD §2.7: "Then existence of every path id and body foreign key is confirmed,
    surfacing as ERR_NOT_FOUND." PRD §2.7: "Only after all of the above does the system
    evaluate state and business rules."

    Design: Difficulty/priority_pair_validation_conflict/kennel_assign_existence_beats_occupancy
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-3")
    animal_a = create_intaken_animal(species="DOG", age_months=36, source="SURRENDER", name="A")
    assign_kennel(kennel["id"], animal_a["id"], kennel["version"])  # kennel now FULL

    kennel_full = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    # Trigger references a non-existent animal_id against the FULL kennel.
    resp = api_client.create_kennel_assignment(
        create_kennel_assignment_payload(kennel["id"], NON_EXISTENT_UUID, kennel_full["version"]), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_kennel_assign_nonexistent_kennel_fk_not_found_before_business(api):
    """PRD §2.6: "for any write whose body carries a foreign key (such as animal_id,
    kennel_id ...), each such reference must likewise resolve. References are checked in
    order, and the first unresolved identifier — whether a path id or a body foreign key
    — causes the request to be rejected with ERR_NOT_FOUND before any later reference is
    considered."
    PRD §2.7: "Then existence of every path id and body foreign key is confirmed,
    surfacing as ERR_NOT_FOUND." PRD §2.7: "Only after all of the above does the system
    evaluate state and business rules."

    Design: Difficulty/priority_pair_validation_conflict/kennel_assign_existence_beats_occupancy
    """
    bootstrap_shelter()
    # A valid in-custody animal, but the kennel_id FK does not resolve. Existence is
    # checked before any occupancy/business rule, so ERR_NOT_FOUND wins.
    animal = create_intaken_animal(species="DOG", age_months=36, source="SURRENDER", name="OnlyAnimal")
    resp = api_client.create_kennel_assignment(
        create_kennel_assignment_payload(NON_EXISTENT_UUID, animal["id"], 1), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===================================================================
# Rule 7 — cross-entity state dependency
# ===================================================================

def test_adoption_approved_then_finalizes_proves_medical_gate_satisfied(api):
    """PRD §3.7: "Approval is the more heavily guarded branch: it requires the
    application to be in SUBMITTED, the animal to be AVAILABLE, the animal's
    medical_status to be CLEARED (else ERR_NOT_MEDICALLY_CLEARED); only then does status
    become APPROVED."
    PRD §3.7: "Finalization is performed by an AdoptionCounselor and is the deepest
    cascade in the system. It requires the application to be in APPROVED and the animal
    to still be AVAILABLE."

    The CLEARED gate on approve is only reachable in the satisfied direction: an
    AVAILABLE animal is necessarily CLEARED (make-available requires it and the medical
    axis cannot leave CLEARED). This asserts the gate from the positive side — the
    medical-gated APPROVED state is real and finalizes.

    Design: Difficulty/cross_entity_state_dependency/adoption_approve_requires_animal_medically_cleared
    """
    bootstrap_shelter()
    animal = create_available_animal(species="DOG", age_months=30, name="Cleared")
    assert animal["medical_status"] == "CLEARED", "an AVAILABLE animal is medically CLEARED"
    adopter = create_adopter(email="uli@x.com", full_name="Uli")
    app = submit_application(animal["id"], adopter["id"])

    approved = validate_success(api_client.approve_adoption_application(app["id"], COUNSELOR), 200)
    assert approved["status"] == "APPROVED", "medical-gated approval yields APPROVED"
    finalized = validate_success(api_client.finalize_adoption_application(app["id"], COUNSELOR), 200)
    assert finalized["status"] == "FINALIZED", "the APPROVED application finalizes"


def test_adoption_approve_succeeds_when_animal_cleared(api):
    """PRD §3.7: "it requires the application to be in SUBMITTED, the animal to be
    AVAILABLE, the animal's medical_status to be CLEARED (else ERR_NOT_MEDICALLY_CLEARED)
    ... only then does status become APPROVED."

    Design: Difficulty/cross_entity_state_dependency/adoption_approve_requires_animal_medically_cleared
    """
    bootstrap_shelter()
    # Animal AVAILABLE and still CLEARED (the cross-entity dependency is satisfied).
    animal = create_available_animal(species="DOG", age_months=30, name="Healthy")
    assert animal["medical_status"] == "CLEARED"
    adopter = create_adopter(email="healthy@x.com", full_name="Hal")
    app = submit_application(animal["id"], adopter["id"])

    approved = validate_success(api_client.approve_adoption_application(app["id"], COUNSELOR), 200)
    assert approved["status"] == "APPROVED", "approve succeeds when the animal is medically CLEARED"


def test_kennel_assignment_requires_kennel_open(api):
    """PRD §3.4: "The assignment is permitted only when the animal's lifecycle_status is
    IN_CUSTODY, the target kennel's status is OPEN (its occupied_count strictly below
    its capacity), and no other ACTIVE assignment on that kennel overlaps the requested
    occupancy interval. A kennel that is not OPEN ... causes rejection with
    ERR_KENNEL_OCCUPIED."

    Design: Difficulty/cross_entity_state_dependency/kennel_assignment_requires_kennel_open
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-4")
    animal_a = create_intaken_animal(species="DOG", age_months=36, source="SURRENDER", name="A")
    assign_kennel(kennel["id"], animal_a["id"], kennel["version"])  # kennel FULL

    animal_b = create_intaken_animal(species="DOG", age_months=38, source="SURRENDER", name="B")
    kennel_full = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    resp = api_client.create_kennel_assignment(
        create_kennel_assignment_payload(kennel["id"], animal_b["id"], kennel_full["version"]), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_KENNEL_OCCUPIED.value)


def test_kennel_assignment_succeeds_when_kennel_open(api):
    """PRD §3.4: "The assignment is permitted only when the animal's lifecycle_status is
    IN_CUSTODY, the target kennel's status is OPEN (its occupied_count strictly below its
    capacity) ... A successful assignment is created with status ACTIVE and start_at
    stamped from the clock, increments the kennel's occupied_count by one."

    Design: Difficulty/cross_entity_state_dependency/kennel_assignment_requires_kennel_open
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-4b")
    assert kennel["status"] == "OPEN"
    animal = create_intaken_animal(species="DOG", age_months=36, source="SURRENDER", name="Open")

    ka = validate_success(
        api_client.create_kennel_assignment(
            create_kennel_assignment_payload(kennel["id"], animal["id"], kennel["version"]), INTAKE
        ),
        201,
    )
    assert ka["status"] == "ACTIVE", "assignment succeeds against an OPEN kennel"


# ===================================================================
# Queue B — validations section: violation-to-error
# ===================================================================

def test_euthanasia_approve_by_requester_segregation_of_duties(api):
    """PRD §3.9: "Approval enforces segregation of duties: the approving Veterinarian's
    X-User-ID must differ from the decision's requested_by_user_id, and an attempt by
    the same person who requested it to also approve it is rejected with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/validations/euthanasia_approve_by_requester_segregation_of_duties
    """
    bootstrap_shelter(stray_hold_days=0)
    animal = create_intaken_animal(species="DOG", age_months=90, source="SURRENDER", name="Sod")
    # vet-1 (as ShelterAdmin-role opener uses X-User-ID vet-1) opens the decision.
    decision = open_euthanasia(animal["id"], reason="BEHAVIORAL", requester_user_id="vet-1")

    # Same X-User-ID vet-1 now tries to approve as Veterinarian.
    resp = api_client.approve_euthanasia_decision(decision["id"], make_veterinarian_headers("vet-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_euthanasia_execute_during_stray_hold_rejected(api):
    """PRD §3.9: "an execution attempted during an active hold is rejected with
    ERR_STRAY_HOLD_ACTIVE, so a stray can never be euthanized while its reclamation
    window is still open."

    Design: Corner/validations/euthanasia_execute_during_stray_hold_rejected
    """
    bootstrap_shelter(stray_hold_days=5)
    animal = register_animal(name="Held", species="DOG", age_months=100)
    intake_animal(animal["id"], source="STRAY")  # release_at = 2026-06-06
    decision = open_euthanasia(animal["id"], reason="MEDICAL_UNTREATABLE", requester_user_id="counselor-1")
    approve_euthanasia(decision["id"], approver_user_id="vet-2")
    set_clock("2026-06-02T00:00:00Z")  # still inside the 5-day hold

    resp = api_client.execute_euthanasia_decision(decision["id"], make_veterinarian_headers("vet-2"))
    validate_error(resp, ApiErrorId.ERR_STRAY_HOLD_ACTIVE.value)


def test_owner_claim_approve_chip_mismatch_rejected(api):
    """PRD §3.6: "It requires that the animal's lifecycle_status still be IN_CUSTODY and
    that the claim's proof_chip_number match the chip_number of an existing microchip
    registered on that same animal; if the presented serial matches no microchip on the
    animal, the approval is rejected with ERR_CHIP_MISMATCH."

    Design: Corner/validations/owner_claim_approve_chip_mismatch_rejected
    """
    bootstrap_shelter(stray_hold_days=5)
    animal = register_animal(name="Claimed", species="CAT", age_months=40)
    intake_animal(animal["id"], source="STRAY")
    microchip_animal(animal["id"], chip_number="CHIP-5005")
    claim = open_owner_claim(animal["id"], claimant_name="Faker", proof_chip_number="WRONG-9999")

    resp = api_client.approve_owner_claim(claim["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CHIP_MISMATCH.value)
    after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert after["lifecycle_status"] == "IN_CUSTODY", "animal stays IN_CUSTODY after mismatch"


def test_second_application_approve_conflict_rejected(api):
    """PRD §3.7: "no other application for the same animal to already be in APPROVED or
    FINALIZED (else ERR_APPLICATION_CONFLICT); only then does status become APPROVED."

    Design: Corner/validations/second_application_approve_conflict_rejected
    """
    bootstrap_shelter()
    animal = create_available_animal(species="DOG", age_months=30, name="Pop")
    adopter1 = create_adopter(email="one@x.com", full_name="One")
    adopter2 = create_adopter(email="two@x.com", full_name="Two")
    app1 = submit_application(animal["id"], adopter1["id"])
    app2 = submit_application(animal["id"], adopter2["id"])
    approve_application(app1["id"])  # first APPROVED

    resp = api_client.approve_adoption_application(app2["id"], COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_CONFLICT.value)


def test_duplicate_microchip_number_rejected(api):
    """PRD §3.3: "The chip_number must be globally unique across all microchips; an
    attempt to register a serial already held by another chip is rejected with
    ERR_DUPLICATE_CHIP."

    Design: Corner/validations/duplicate_microchip_number_rejected
    """
    bootstrap_shelter()
    a1 = create_intaken_animal(species="DOG", age_months=20, source="SURRENDER", name="A1")
    microchip_animal(a1["id"], chip_number="CHIP-DUP")
    a2 = create_intaken_animal(species="DOG", age_months=22, source="SURRENDER", name="A2")

    resp = api_client.create_microchip(create_microchip_payload(a2["id"], "CHIP-DUP"), VET)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHIP.value)


def test_duplicate_adopter_email_rejected(api):
    """PRD §3.7: "The email must be unique across all adopter accounts; a duplicate is
    rejected with ERR_DUPLICATE_EMAIL."

    Design: Corner/validations/duplicate_adopter_email_rejected
    """
    bootstrap_shelter(clock=None)
    validate_success(
        api_client.create_adopter_account(create_adopter_account_payload(email="same@x.com", full_name="First"), COUNSELOR),
        201,
    )
    resp = api_client.create_adopter_account(
        create_adopter_account_payload(email="same@x.com", full_name="Second"), COUNSELOR
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "A request whose limit falls outside the range of 1 to 100 inclusive,
    or whose offset is negative, is rejected with ERR_VALIDATION_LIMIT."

    Design: Corner/validations/pagination_limit_out_of_range_rejected
    """
    bootstrap_shelter(clock=None)
    resp = api_client.list_animals_raw(COUNSELOR, "limit=500")
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value)
