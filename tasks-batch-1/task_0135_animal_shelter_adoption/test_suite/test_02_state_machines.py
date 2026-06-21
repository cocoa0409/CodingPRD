"""State-machine behavior: parallel axes, cyclic foster placement, invalid
transitions, terminal lockdown, idempotency.

Queue A rule 3 (non-linear state machine) plus queue B state_machines instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    bootstrap_shelter,
    register_animal,
    intake_animal,
    create_intaken_animal,
    create_available_animal,
    create_adopter,
    submit_application,
    approve_application,
    finalize_application,
    hold_medical,
    clear_medical,
    create_foster_home,
    place_foster,
    return_foster,
    microchip_animal,
    open_euthanasia,
    TEST_USERS,
)
from test_helpers.factories import (
    create_medical_record_payload,
    create_intake_record_payload,
    create_adoption_application_payload,
    create_euthanasia_decision_payload,
)

INTAKE = TEST_USERS["intake_officer_headers"]
VET = TEST_USERS["veterinarian_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]


# ===================================================================
# Rule 3 — non-linear state machine: parallel axes on Animal
# ===================================================================

def test_hold_exam_moves_medical_axis_only_lifecycle_unchanged(api):
    """PRD §2.5: "Animal custody and animal medical readiness are two independent
    state axes carried on the same Animal record. ... No operation advances both axes
    at once — a medical exam moves only medical_status, and an intake or outcome moves
    only lifecycle_status."
    PRD §3.3: "a HOLD outcome sets it to NEEDS_TREATMENT."

    Design: Difficulty/non_linear_state_machine/animal_parallel_axes_medical_independent_of_lifecycle
    """
    bootstrap_shelter()
    animal = create_intaken_animal(species="DOG", age_months=50, source="SURRENDER", name="Max")
    assert animal["lifecycle_status"] == "IN_CUSTODY"
    assert animal["medical_status"] == "UNEXAMINED"

    hold_medical(animal["id"])
    after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert after["medical_status"] == "NEEDS_TREATMENT", "HOLD exam sets medical NEEDS_TREATMENT"
    assert after["lifecycle_status"] == "IN_CUSTODY", "lifecycle axis untouched by the exam"


def test_clear_exam_moves_medical_axis_only_lifecycle_unchanged(api):
    """PRD §2.5: "a medical exam moves only medical_status, and an intake or outcome
    moves only lifecycle_status — so the two evolve on separate tracks."
    PRD §3.3: "a CLEAR outcome sets medical_status to CLEARED."

    Design: Difficulty/non_linear_state_machine/animal_parallel_axes_medical_independent_of_lifecycle
    """
    bootstrap_shelter()
    animal = create_intaken_animal(species="CAT", age_months=20, source="SURRENDER", name="Mia")
    assert animal["lifecycle_status"] == "IN_CUSTODY"

    clear_medical(animal["id"])
    after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert after["medical_status"] == "CLEARED", "CLEAR exam sets medical CLEARED"
    assert after["lifecycle_status"] == "IN_CUSTODY", "lifecycle axis untouched by the exam"


# ===================================================================
# Rule 3 — non-linear state machine: cyclic foster placement
# ===================================================================

def test_foster_cyclic_return_then_replace_same_animal(api):
    """PRD §3.8: "The lifecycle is deliberately cyclic: a returned animal is AVAILABLE
    again and may be placed into a fresh FosterPlacement or proceed to adoption."
    PRD §3.8: "Returning a placement ... transitions its status to RETURNED ... and
    drives the animal from FOSTERED back to AVAILABLE."

    Design: Difficulty/non_linear_state_machine/foster_placement_cyclic_return_then_replace
    """
    bootstrap_shelter()
    home = create_foster_home(max_concurrent=2, cooldown_days=0, contact_name="Home1")
    animal = create_available_animal(species="CAT", age_months=30, name="Loop")

    fp1 = place_foster(home["id"], animal["id"])
    return_foster(fp1["id"])
    fp2 = place_foster(home["id"], animal["id"])  # re-place into a second placement

    fp1_after = validate_success(api_client.get_foster_placement(fp1["id"], TEST_USERS["foster_coordinator_headers"]))
    fp2_after = validate_success(api_client.get_foster_placement(fp2["id"], TEST_USERS["foster_coordinator_headers"]))
    animal_after = validate_success(api_client.get_animal(animal["id"], INTAKE))

    assert fp1_after["status"] == "RETURNED", "first placement is RETURNED"
    assert fp2_after["status"] == "ACTIVE", "second placement is ACTIVE"
    assert animal_after["lifecycle_status"] == "FOSTERED", "animal is FOSTERED again after re-placement"


def test_foster_return_drives_animal_back_to_available(api):
    """PRD §3.8: "The return sets the placement's end_at to the current clock instant,
    transitions its status to RETURNED, decrements the home's active_placement_count by
    one, and drives the animal from FOSTERED back to AVAILABLE."

    Design: Difficulty/non_linear_state_machine/foster_placement_cyclic_return_then_replace
    """
    bootstrap_shelter()
    home = create_foster_home(max_concurrent=2, cooldown_days=0, contact_name="Home2")
    animal = create_available_animal(species="DOG", age_months=40, name="Cycle")

    fp1 = place_foster(home["id"], animal["id"])
    fostered = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert fostered["lifecycle_status"] == "FOSTERED"

    returned = return_foster(fp1["id"])
    assert returned["status"] == "RETURNED"
    available = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert available["lifecycle_status"] == "AVAILABLE", "returned animal is AVAILABLE again"


# ===================================================================
# Queue B — invalid transitions / terminal lockdown / idempotency
# ===================================================================

def test_approve_rejected_application_invalid_state(api):
    """PRD §3.7: "an AdoptionCounselor either approves it (advancing status to
    APPROVED) or rejects it (advancing status to REJECTED, a terminal outcome with no
    effect on the animal)."
    PRD §3.7: "Approval is the more heavily guarded branch: it requires the application
    to be in SUBMITTED."

    Design: Corner/state_machines/reject_then_approve_rejected_application_invalid_state
    """
    bootstrap_shelter()
    animal = create_available_animal(species="DOG", age_months=36, name="Rej")
    adopter = create_adopter(email="ree@x.com", full_name="Ree")
    app = submit_application(animal["id"], adopter["id"])
    validate_success(api_client.reject_adoption_application(app["id"], COUNSELOR))

    resp = api_client.approve_adoption_application(app["id"], COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api_client.get_adoption_application(app["id"], COUNSELOR))
    assert after["status"] == "REJECTED", "status stays REJECTED after the rejected re-approve"


def test_finalize_already_finalized_application_invalid_state_no_double_debit(api):
    """PRD §3.7: "Finalization ... requires the application to be in APPROVED and the
    animal to still be AVAILABLE."
    PRD §3.7: "collected_fee_cents always equals the sum of final_fee_cents across
    applications that are FINALIZED and not yet refunded."

    Design: Corner/state_machines/finalize_terminal_adopted_animal_second_finalize_invalid_state
    """
    shelter = bootstrap_shelter()
    animal = create_available_animal(
        species="DOG", age_months=40, microchipped=True, chip_number="CHIP-9003", name="Twice"
    )
    adopter = create_adopter(email="tex@x.com", full_name="Tex")
    app = submit_application(animal["id"], adopter["id"])
    approve_application(app["id"])
    finalize_application(app["id"])  # ledger debited once: ADULT chipped -> 15000

    resp = api_client.finalize_adoption_application(app["id"], COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    shelter_after = validate_success(api_client.get_shelter(shelter["id"], TEST_USERS["shelter_admin_headers"]))
    assert shelter_after["collected_fee_cents"] == 15000, (
        "ledger debited once only; no double debit from the second finalize"
    )


def test_submit_application_for_in_custody_animal_invalid_state(api):
    """PRD §3.7: "Submission is permitted only while the animal's lifecycle_status is
    AVAILABLE and no other application for that animal sits in APPROVED or FINALIZED;
    otherwise it is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/submit_application_when_animal_not_available_invalid_state
    """
    bootstrap_shelter()
    # IN_CUSTODY but never made AVAILABLE.
    animal = create_intaken_animal(species="CAT", age_months=24, source="SURRENDER", name="NotYet")
    adopter = create_adopter(email="gus@x.com", full_name="Gus")

    resp = api_client.create_adoption_application(
        create_adoption_application_payload(animal["id"], adopter["id"]), COUNSELOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_double_intake_same_animal_invalid_state(api):
    """PRD §3.2: "Intake is permitted only when the animal's lifecycle_status is
    INTAKE_PENDING and no prior intake record exists for that animal; otherwise the
    attempt is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/double_intake_same_animal_invalid_state
    """
    bootstrap_shelter()
    animal = create_intaken_animal(species="DOG", age_months=18, source="SURRENDER", name="Dup")

    resp = api_client.create_intake_record(
        create_intake_record_payload(animal["id"], source="SURRENDER", surrendering_party="H2"), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_execute_euthanasia_before_approval_invalid_state(api):
    """PRD §3.9: "Execution is the final, irreversible step, performed by a
    Veterinarian on a decision in status APPROVED."

    Design: Corner/state_machines/euthanasia_execute_before_approval_invalid_state
    """
    bootstrap_shelter(stray_hold_days=0)
    animal = create_intaken_animal(species="DOG", age_months=80, source="SURRENDER", name="Eu")
    decision = open_euthanasia(animal["id"], reason="MEDICAL_UNTREATABLE", requester_user_id="counselor-1")

    # Execute while still REQUESTED (not APPROVED).
    from test_helpers import make_veterinarian_headers
    resp = api_client.execute_euthanasia_decision(decision["id"], make_veterinarian_headers("vet-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
