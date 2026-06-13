"""Dangerous-dog cases: the appeal cycle and the designation cross-entity gate
(PRD §3.7, §3.4).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_owner_headers,
    set_clock,
    create_owner,
    create_pet,
    create_dangerous_dog_case_payload,
    setup_designated_case,
    setup_appealed_case,
    setup_approved_individual_license,
)

OFFICER = TEST_USERS["officer_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_designation_appeal_uphold_cycle_returns_to_designated(api):
    """PRD §3.7: "Upholding it advances APPEALED -> DESIGNATED; the surcharge was
    already applied at the original designation and is not applied a second time,
    so upholding simply returns the case to DESIGNATED without touching fees."
    PRD §3.7: "the pet's is_dangerous flag is set to true."

    Design: Difficulty/non_linear_state_machine/dangerous_dog_designation_appeal_cycle
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Owner D", email="od@x.com", address_zip="30001")
    pet = create_pet(owner["id"], name="Fang", is_altered=False, species="DOG")
    case = setup_appealed_case(owner["id"], pet["id"], severity="ATTACK")
    assert case["status"] == "APPEALED"

    upheld = validate_success(api.uphold_case(case["id"], OFFICER), 200)
    assert upheld["status"] == "DESIGNATED"

    pet_after = validate_success(api.get_pet(pet["id"], CLERK), 200)
    assert pet_after["is_dangerous"] is True


def test_issue_tag_blocked_by_pet_dangerous_state(api):
    """PRD §3.4: "issuance is permitted only when the pet's is_dangerous is false,
    or when any dangerous-dog case that existed for the pet now sits in OVERTURNED
    or DISMISSED - a pet carrying an open DESIGNATED case cannot have a tag issued,
    and the attempt fails with ERR_DANGEROUS_DOG_HOLD."

    Design: Difficulty/cross_entity_state_dependency/issue_tag_depends_on_pet_dangerous_state
    """
    set_clock("2026-01-01T00:00:00Z")
    # License APPROVED for the pet, then the pet gets a DESIGNATED case.
    owner, pet, vr, lic = setup_approved_individual_license(
        owner_overrides={"full_name": "Owner J", "email": "oj@x.com"},
        pet_overrides={"is_altered": False, "name": "Tank"},
    )
    setup_designated_case(owner["id"], pet["id"], severity="ATTACK")

    res = api.issue_tag(lic["id"], CLERK)
    validate_error(res, "ERR_DANGEROUS_DOG_HOLD")

    pet_after = validate_success(api.get_pet(pet["id"], CLERK), 200)
    assert pet_after["is_dangerous"] is True


def test_designate_twice_for_same_pet_returns_already_designated(api):
    """PRD §3.7: "no other case for the same pet already sits in DESIGNATED - a
    duplicate live designation is refused with ERR_ALREADY_DESIGNATED."

    Design: Corner/state_machines/designate_twice_for_same_pet_returns_already_designated
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="X Owner", email="xo@x.com", address_zip="10018")
    pet = create_pet(owner["id"], name="Dup", is_altered=False, species="DOG")
    # First case driven to DESIGNATED.
    setup_designated_case(owner["id"], pet["id"], severity="BITE")
    # Second case for the SAME pet driven to INVESTIGATING, then designate.
    c2 = validate_success(
        api.create_dangerous_dog_case(
            create_dangerous_dog_case_payload(pet["id"], severity="ATTACK"), OFFICER
        ),
        201,
    )
    validate_success(api.investigate_case(c2["id"], OFFICER), 200)

    res = api.designate_case(c2["id"], OFFICER)
    validate_error(res, "ERR_ALREADY_DESIGNATED")

    c2_after = validate_success(api.get_dangerous_dog_case(c2["id"], CLERK), 200)
    assert c2_after["status"] == "INVESTIGATING"


def test_designated_case_can_be_appealed_then_upheld_again(api):
    """PRD §3.7: "Appealing, an owner-only action advancing DESIGNATED -> APPEALED,
    requires the acting owner to own the pet (ERR_UNAUTHORIZED) and the case to be
    in DESIGNATED (ERR_INVALID_STATE)."
    PRD §3.7: "Upholding it advances APPEALED -> DESIGNATED".

    Companion (cycle re-entry facet): after uphold returns the case to DESIGNATED,
    the owner may appeal it a SECOND time — the DESIGNATED -> APPEALED edge is
    re-traversable, which a linear pipeline cannot express.

    Design: Difficulty/non_linear_state_machine/dangerous_dog_designation_appeal_cycle
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Owner D2", email="od2@x.com", address_zip="30002")
    pet = create_pet(owner["id"], name="Fang2", is_altered=False, species="DOG")
    case = setup_appealed_case(owner["id"], pet["id"], severity="ATTACK")
    upheld = validate_success(api.uphold_case(case["id"], OFFICER), 200)
    assert upheld["status"] == "DESIGNATED"

    # Re-enter the cycle: appeal the re-DESIGNATED case again.
    reappealed = validate_success(
        api.appeal_case(case["id"], make_owner_headers(owner["id"])), 200
    )
    assert reappealed["status"] == "APPEALED"


def test_issue_tag_allowed_after_case_dismissed_clears_hold(api):
    """PRD §3.4: "issuance is permitted only when the pet's is_dangerous is false,
    or when any dangerous-dog case that existed for the pet now sits in OVERTURNED
    or DISMISSED - a pet carrying an open DESIGNATED case cannot have a tag
    issued".

    Companion (the permissive branch of the same cross-entity gate): a pet whose
    only case was DISMISSED (never designated, is_dangerous false) clears the hold,
    so issue-tag succeeds and the license becomes ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/issue_tag_depends_on_pet_dangerous_state
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, vr, lic = setup_approved_individual_license(
        owner_overrides={"full_name": "Owner J2", "email": "oj2@x.com"},
        pet_overrides={"is_altered": False, "name": "Tank2"},
    )
    # Open a case and dismiss it (INVESTIGATING -> DISMISSED); never designated.
    case = validate_success(
        api.create_dangerous_dog_case(
            create_dangerous_dog_case_payload(pet["id"], severity="BITE"), OFFICER
        ),
        201,
    )
    validate_success(api.investigate_case(case["id"], OFFICER), 200)
    validate_success(api.dismiss_case(case["id"], OFFICER), 200)

    pet_now = validate_success(api.get_pet(pet["id"], CLERK), 200)
    assert pet_now["is_dangerous"] is False

    issued = validate_success(api.issue_tag(lic["id"], CLERK), 200)
    assert issued["status"] == "ACTIVE"
