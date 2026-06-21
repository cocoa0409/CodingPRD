"""Transitive cascades and compensating-action invariants.

Queue A rule 4 (transitive cascade) and rule 9 (compensating invariant). Each
outcome cascade is atomic within the triggering request and visible in the same
response (PRD §2.5).
"""
from test_helpers import (
    api_client,
    validate_success,
    bootstrap_shelter,
    register_animal,
    intake_animal,
    create_kennel,
    create_available_animal,
    create_adopter,
    submit_application,
    approve_application,
    finalize_application,
    assign_kennel,
    microchip_animal,
    open_owner_claim,
    TEST_USERS,
)

ADMIN = TEST_USERS["shelter_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]


# ===================================================================
# Rule 4 — transitive cascade: finalize depth-4 chain
# ===================================================================

def test_finalize_cascade_depth4_app_animal_kennel_occupancy(api):
    """PRD §2.5: "finalizing an approved application marks the application FINALIZED,
    drives the animal to ADOPTED, releases the animal's currently ACTIVE kennel
    assignment, and decrements the occupancy of the kennel that assignment held — four
    coordinated mutations in one transaction."

    Design: Difficulty/transitive_cascade/finalize_cascade_depth4_app_animal_kennel_occupancy
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-1")
    animal = register_animal(name="Duke", species="DOG", age_months=40)
    intake_animal(animal["id"], source="SURRENDER")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    # clear + make available + approve.
    from test_helpers import clear_medical, make_animal_available
    clear_medical(animal["id"])
    make_animal_available(animal["id"])
    adopter = create_adopter(email="dee@x.com", full_name="Dee")
    app = submit_application(animal["id"], adopter["id"])
    approve_application(app["id"])

    finalized = finalize_application(app["id"])
    assert finalized["status"] == "FINALIZED", "application FINALIZED"

    animal_after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert animal_after["lifecycle_status"] == "ADOPTED", "animal ADOPTED"
    ka_after = validate_success(api_client.get_kennel_assignment(ka["id"], INTAKE))
    assert ka_after["status"] == "RELEASED", "kennel assignment RELEASED by the cascade"
    kennel_after = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert kennel_after["occupied_count"] == 0, "kennel occupied_count decremented to 0"


def test_finalize_cascade_visible_in_same_response_immediate(api):
    """PRD §2.5: "The shelter's outcome operations are atomic, multi-entity cascades,
    and every cascade completes wholly within the single request that triggers it."
    PRD §3.7: "adds final_fee_cents to the shelter's collected_fee_cents, drives the
    animal from AVAILABLE to ADOPTED, and releases the animal's ACTIVE kennel
    assignment with the occupancy decrement that entails."

    Design: Difficulty/transitive_cascade/finalize_cascade_depth4_app_animal_kennel_occupancy
    """
    shelter = bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-1b")
    animal = register_animal(name="Echo", species="DOG", age_months=40)
    intake_animal(animal["id"], source="SURRENDER")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    from test_helpers import clear_medical, make_animal_available
    microchip_animal(animal["id"], chip_number="CHIP-IMM")  # ADULT chipped -> 15000
    clear_medical(animal["id"])
    make_animal_available(animal["id"])
    adopter = create_adopter(email="imm@x.com", full_name="Imm")
    app = submit_application(animal["id"], adopter["id"])
    approve_application(app["id"])
    finalize_application(app["id"])

    # A single round of reads right after finalize shows all effects, no lag.
    animal_after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    ka_after = validate_success(api_client.get_kennel_assignment(ka["id"], INTAKE))
    shelter_after = validate_success(api_client.get_shelter(shelter["id"], ADMIN))
    assert animal_after["lifecycle_status"] == "ADOPTED"
    assert ka_after["status"] == "RELEASED"
    assert shelter_after["collected_fee_cents"] == 15000, "ledger debited in the same request"


# ===================================================================
# Rule 4 — transitive cascade: owner-claim approve depth-3 chain
# ===================================================================

def test_owner_claim_approve_cascade_depth3_reclaimed(api):
    """PRD §3.6: "On a successful approval, the claim's status becomes APPROVED, the
    animal is driven from IN_CUSTODY to RECLAIMED, and the animal's ACTIVE kennel
    assignment, if any, is released with the attendant occupancy decrement."

    Design: Difficulty/transitive_cascade/owner_claim_approve_cascade_depth3_different_trigger
    """
    bootstrap_shelter(stray_hold_days=5)
    kennel = create_kennel(capacity=1, label="K-2")
    animal = register_animal(name="Bella", species="DOG", age_months=60)
    intake_animal(animal["id"], source="STRAY")
    microchip_animal(animal["id"], chip_number="CHIP-3003", owner_name="Owner O")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])
    claim = open_owner_claim(animal["id"], claimant_name="Owner O", proof_chip_number="CHIP-3003")

    approved = validate_success(api_client.approve_owner_claim(claim["id"], ADMIN))
    assert approved["status"] == "APPROVED", "claim APPROVED"
    animal_after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert animal_after["lifecycle_status"] == "RECLAIMED", "animal RECLAIMED"
    ka_after = validate_success(api_client.get_kennel_assignment(ka["id"], INTAKE))
    assert ka_after["status"] == "RELEASED", "kennel assignment RELEASED by the cascade"
    kennel_after = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert kennel_after["occupied_count"] == 0, "kennel occupied_count decremented to 0"


def test_owner_claim_approve_releases_kennel_occupancy_to_zero(api):
    """PRD §3.6: "the animal is driven from IN_CUSTODY to RECLAIMED, and the animal's
    ACTIVE kennel assignment, if any, is released with the attendant occupancy
    decrement."
    PRD §3.1: "occupied_count, the count of kennel assignments on it whose status is
    ACTIVE, which must equal that count at all times."

    Design: Difficulty/transitive_cascade/owner_claim_approve_cascade_depth3_different_trigger
    """
    bootstrap_shelter(stray_hold_days=5)
    kennel = create_kennel(capacity=1, label="K-2b")
    animal = register_animal(name="Rex", species="CAT", age_months=48)
    intake_animal(animal["id"], source="STRAY")
    microchip_animal(animal["id"], chip_number="CHIP-3009", owner_name="Owner P")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    kennel_full = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert kennel_full["occupied_count"] == 1 and kennel_full["status"] == "FULL"

    claim = open_owner_claim(animal["id"], claimant_name="Owner P", proof_chip_number="CHIP-3009")
    validate_success(api_client.approve_owner_claim(claim["id"], ADMIN))

    kennel_after = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert kennel_after["occupied_count"] == 0, "occupancy back to 0"
    assert kennel_after["status"] == "OPEN", "kennel reads OPEN below capacity"


# ===================================================================
# Rule 9 — compensating invariant: refund restores fee ledger
# ===================================================================

def test_refund_restores_shelter_fee_ledger_to_zero(api):
    """PRD §3.7: "Refund requires the application to be in FINALIZED. It sets the
    application's refunded flag to true and its status to REFUNDED, and as a
    compensating action it subtracts final_fee_cents back out of the shelter's
    collected_fee_cents. This keeps the ledger invariant intact: collected_fee_cents
    always equals the sum of final_fee_cents across applications that are FINALIZED and
    not yet refunded."

    Design: Difficulty/compensating_invariant/refund_restores_shelter_fee_ledger_money_invariant
    """
    shelter = bootstrap_shelter(promo_active=False)
    animal = create_available_animal(
        species="DOG", age_months=36, microchipped=True, chip_number="CHIP-4004", name="Ledger"
    )
    adopter = create_adopter(email="mo@x.com", full_name="Mo")
    app = submit_application(animal["id"], adopter["id"])
    approve_application(app["id"])
    finalize_application(app["id"])  # ADULT chipped -> +15000

    mid = validate_success(api_client.get_shelter(shelter["id"], ADMIN))
    assert mid["collected_fee_cents"] == 15000, "ledger at 15000 after finalize"

    refunded = validate_success(api_client.refund_adoption_application(app["id"], ADMIN))
    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded"] is True
    shelter_after = validate_success(api_client.get_shelter(shelter["id"], ADMIN))
    assert shelter_after["collected_fee_cents"] == 0, "refund restores ledger to 0 — no drift"


def test_refund_sets_application_refunded_and_status(api):
    """PRD §3.7: "It sets the application's refunded flag to true and its status to
    REFUNDED, and as a compensating action it subtracts final_fee_cents back out of the
    shelter's collected_fee_cents."

    Design: Difficulty/compensating_invariant/refund_restores_shelter_fee_ledger_money_invariant
    """
    shelter = bootstrap_shelter(promo_active=False)
    animal = create_available_animal(
        species="CAT", age_months=24, microchipped=True, chip_number="CHIP-4005", name="Ledger2"
    )
    adopter = create_adopter(email="mo2@x.com", full_name="Mo Two")
    app = submit_application(animal["id"], adopter["id"])
    approve_application(app["id"])
    final = finalize_application(app["id"])  # CAT ADULT chipped -> 15000
    assert final["final_fee_cents"] == 15000

    refunded = validate_success(api_client.refund_adoption_application(app["id"], ADMIN))
    assert refunded["refunded"] is True, "refunded flag set true"
    assert refunded["status"] == "REFUNDED", "status REFUNDED"


# ===================================================================
# Rule 9 — compensating invariant: kennel release restores occupancy
# ===================================================================

def test_kennel_release_restores_occupancy_count_to_zero(api):
    """PRD §3.4: "Releasing sets end_at to the current clock instant, transitions the
    assignment's status to RELEASED, computes the finalized board cost into
    actual_board_cents, decrements the kennel's occupied_count by one, recomputes the
    kennel's status (back to OPEN if occupied_count is again below capacity)."

    Design: Difficulty/compensating_invariant/kennel_release_restores_occupancy_count_invariant
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-6")
    animal = register_animal(name="Occ", species="DOG", age_months=36)
    intake_animal(animal["id"], source="SURRENDER")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    full = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert full["occupied_count"] == 1 and full["status"] == "FULL"

    released = validate_success(api_client.release_kennel_assignment(ka["id"], INTAKE))
    assert released["status"] == "RELEASED"
    kennel_after = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert kennel_after["occupied_count"] == 0, "occupancy back to 0"
    assert kennel_after["status"] == "OPEN", "status OPEN below capacity"


def test_kennel_assign_then_release_round_trips_occupancy(api):
    """PRD §3.1: "occupied_count, the count of kennel assignments on it whose status is
    ACTIVE, which must equal that count at all times; and status, which reads OPEN while
    occupied_count is strictly less than capacity and FULL once occupied_count equals
    capacity."

    Design: Difficulty/compensating_invariant/kennel_release_restores_occupancy_count_invariant
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-6b")
    animal = register_animal(name="Occ2", species="CAT", age_months=20)
    intake_animal(animal["id"], source="SURRENDER")

    before = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert before["occupied_count"] == 0 and before["status"] == "OPEN"

    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])
    full = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert full["occupied_count"] == 1 and full["status"] == "FULL"

    validate_success(api_client.release_kennel_assignment(ka["id"], INTAKE))
    after = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert after["occupied_count"] == 0 and after["status"] == "OPEN"
