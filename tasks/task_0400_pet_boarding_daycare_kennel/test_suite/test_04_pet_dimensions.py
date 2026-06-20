"""Pet parallel status dimensions (vaccination vs temperament) and vaccine records.

Translates difficulty (A) non_linear_state_machine/pet_parallel_dimensions_independent
and corner (B) entity / state-machine instances on Pet and VaccinationRecord.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    create_facility, create_owner, create_pet, vaccinate_cat_valid, advance_clock,
    create_vaccination_payload, review_payload,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def test_flag_review_leaves_vaccination_status_unchanged(api):
    """PRD §3.4: "When `decision` is `FLAG`, it moves from `UNREVIEWED` to `FLAGGED`; a
    flagged pet is blocked from reservation confirmation (§3.6) while its vaccination
    dimension remains entirely independent. Either outcome increments the pet's `version`
    by one and leaves `vaccination_status` unchanged."

    A VALID cat that gets FLAGGED stays VALID on the vaccination axis.

    Design: Difficulty/non_linear_state_machine/pet_parallel_dimensions_independent
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    pet = create_pet(owner["id"], weight_kg=6, temperament="REACTIVE")
    vaccinate_cat_valid(pet["id"])
    pet = get_success_data(api_client.get_pet(pet["id"], MGR))
    assert pet["vaccination_status"] == "VALID"
    reviewed = validate_success(api.review_pet(pet["id"], review_payload("FLAG"), MGR), 200)
    assert reviewed["temperament_clearance"] == "FLAGGED"
    assert reviewed["vaccination_status"] == "VALID", "FLAG must not touch the vaccination axis"


def test_clear_review_leaves_vaccination_status_unchanged(api):
    """PRD §3.4: "When `decision` is `CLEAR`, the pet's `temperament_clearance` moves from
    `UNREVIEWED` to `CLEARED`."
    PRD §3.4: "Either outcome increments the pet's `version` by one and leaves
    `vaccination_status` unchanged."

    Design: Difficulty/non_linear_state_machine/pet_parallel_dimensions_independent
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    pet = create_pet(owner["id"], weight_kg=6)
    vaccinate_cat_valid(pet["id"])
    pet = get_success_data(api_client.get_pet(pet["id"], MGR))
    assert pet["vaccination_status"] == "VALID"
    reviewed = validate_success(api.review_pet(pet["id"], review_payload("CLEAR"), MGR), 200)
    assert reviewed["temperament_clearance"] == "CLEARED"
    assert reviewed["vaccination_status"] == "VALID", "CLEAR must not touch the vaccination axis"


def test_pet_size_class_computed_from_weight(api):
    """PRD §3.2: "From the weight, the system computes the pet's `size_class`: a weight
    below 5 kg is `TOY`; from 5 kg up to but not including 15 kg is `SMALL`; from 15 kg up
    to but not including 30 kg is `MEDIUM`; and 30 kg or above is `LARGE`."
    PRD §3.2: "Its `vaccination_status` is one of `VALID`, `EXPIRED`, or `MISSING` and
    begins at `MISSING`".

    Design: Corner/entities/pet_size_class_computed_from_weight
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    pet = validate_success(
        api_client.create_pet(owner["id"], {"name": "Sized", "species": "DOG", "weight_kg": 18}, MGR),
        201,
    )
    assert pet["size_class"] == "MEDIUM"
    assert pet["vaccination_status"] == "MISSING", "no records yet -> MISSING"


def test_vaccination_expiry_flips_status_on_clock(api):
    """PRD §3.3: "The reverse flip happens during a clock advance: when the new
    `current_date` moves past the `expires_on` of at least one required vaccine, the pet
    drops from `VALID` to `EXPIRED`."

    Design: Corner/state_machines/vaccination_expiry_flips_status_on_clock
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    pet = create_pet(owner["id"], weight_kg=6)
    # Both required CAT vaccines expire 2026-01-15; clock at 2026-01-01.
    vaccinate_cat_valid(pet["id"], administered_on="2025-01-01", expires_on="2026-01-15")
    pet = get_success_data(api_client.get_pet(pet["id"], MGR))
    assert pet["vaccination_status"] == "VALID"
    advance_clock(facility["id"], "2026-02-01")
    pet = get_success_data(api_client.get_pet(pet["id"], MGR))
    assert pet["vaccination_status"] == "EXPIRED", "clock past expires_on flips VALID->EXPIRED"


def test_new_vaccination_supersedes_prior_record(api):
    """PRD §3.3: "When a new record is added for a vaccine the pet already had on file,
    the prior record for that same vaccine is marked `superseded` true, so that only the
    latest record for each vaccine governs."

    Design: Corner/entities/vaccination_record_immutable_no_version
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    pet = create_pet(owner["id"], weight_kg=6)
    v1 = validate_success(api_client.create_vaccination(
        pet["id"], create_vaccination_payload(
            vaccine="RABIES", administered_on="2025-06-01", expires_on="2027-06-01"), MGR), 201)
    validate_success(api_client.create_vaccination(
        pet["id"], create_vaccination_payload(
            vaccine="RABIES", administered_on="2026-01-01", expires_on="2028-01-01"), MGR), 201)
    records = api.list_vaccinations(pet["id"], MGR).json()["data"]
    assert len(records) == 2, "both RABIES records are retained (append-only)"
    first = next(r for r in records if r["id"] == v1["id"])
    assert first["superseded"] is True, "the earlier RABIES record is superseded"
    # Append-only: no version field on a VaccinationRecord.
    assert "version" not in first
