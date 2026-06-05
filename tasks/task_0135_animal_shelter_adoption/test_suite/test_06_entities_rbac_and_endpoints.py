"""Entity creation/retrieval, RBAC denials, FK integrity, listing, and optimistic
concurrency.

Queue B sections: entities, rbac, endpoints, cross_cutting_complexity_layers.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    bootstrap_shelter,
    register_animal,
    intake_animal,
    create_intaken_animal,
    create_available_animal,
    create_kennel,
    create_adopter,
    submit_application,
    approve_application,
    microchip_animal,
    clear_medical,
    hold_medical,
    assign_kennel,
    make_adopter_headers,
    assert_animal,
    assert_microchip,
    TEST_USERS,
)
from test_helpers.factories import (
    create_shelter_payload,
    create_animal_payload,
    create_intake_record_payload,
    create_medical_record_payload,
    create_microchip_payload,
    create_kennel_assignment_payload,
    create_adopter_account_payload,
    create_adoption_application_payload,
)

ADMIN = TEST_USERS["shelter_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
VET = TEST_USERS["veterinarian_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]


# ===================================================================
# Queue B — entities
# ===================================================================

def test_create_animal_returns_201_with_initial_axes(api):
    """PRD §3.2: "A freshly registered animal begins with lifecycle_status of
    INTAKE_PENDING and medical_status of UNEXAMINED; its microchipped flag is false and
    its stray_hold_release_at is null until intake."
    PRD §2.4: "a version, an integer that begins at its initial value and increments by
    one on each mutation."

    Design: Corner/entities/create_animal_returns_201_with_initial_axes
    """
    bootstrap_shelter(clock=None)
    animal = validate_success(
        api_client.create_animal(create_animal_payload(name="New", species="DOG", age_months=12), INTAKE),
        201,
    )
    assert_animal(animal)
    assert animal["lifecycle_status"] == "INTAKE_PENDING"
    assert animal["medical_status"] == "UNEXAMINED"
    assert animal["microchipped"] is False
    assert animal["version"] == 1


def test_get_animal_by_id_returns_stored_entity(api):
    """PRD §3.2: "First, a ShelterAdmin or IntakeOfficer registers an Animal record by
    supplying its name, its species (one of DOG or CAT, which selects the board rate),
    and its age_months."

    Design: Corner/entities/get_animal_by_id_returns_stored_entity
    """
    bootstrap_shelter(clock=None)
    created = validate_success(
        api_client.create_animal(create_animal_payload(name="Echo", species="CAT", age_months=18), INTAKE),
        201,
    )
    fetched = validate_success(api_client.get_animal(created["id"], COUNSELOR))
    assert fetched["name"] == "Echo"
    assert fetched["species"] == "CAT"
    assert fetched["age_months"] == 18


def test_get_animal_nonexistent_returns_not_found(api):
    """PRD §2.6: "For any request that carries a resource id in its path, that id must
    resolve to an existing resource ... the first unresolved identifier ... causes the
    request to be rejected with ERR_NOT_FOUND."

    Design: Corner/entities/get_animal_nonexistent_returns_not_found
    """
    bootstrap_shelter(clock=None)
    resp = api_client.get_animal("00000000-0000-4000-8000-000000000abc", COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_animal_missing_species_returns_invalid_request(api):
    """PRD §2.6: "the body is checked for required fields, correct types, and — for any
    enum-valued field — membership in that field's declared set; a missing required
    field, a wrong type, or an out-of-range enum value yields ERR_INVALID_REQUEST."

    Design: Corner/entities/create_animal_missing_species_returns_invalid_request
    """
    bootstrap_shelter(clock=None)
    resp = api_client.create_animal({"name": "NoSpecies", "age_months": 10}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_animal_invalid_species_enum_returns_invalid_request(api):
    """PRD §2.6: "for any enum-valued field — membership in that field's declared set; a
    missing required field, a wrong type, or an out-of-range enum value yields
    ERR_INVALID_REQUEST."
    PRD §3.2: "its species (one of DOG or CAT, which selects the board rate)."

    Design: Corner/entities/create_animal_invalid_species_enum_returns_invalid_request
    """
    bootstrap_shelter(clock=None)
    resp = api_client.create_animal({"name": "Tweety", "species": "BIRD", "age_months": 5}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_shelter_defaults_applied_when_omitted(api):
    """PRD §3.1: "The mandatory stray-hold period, stray_hold_days, defaults to 5 whole
    days ... The promotional-pricing switch, promo_active, defaults to off. The two base
    board rates, dog_daily_board_cents and cat_daily_board_cents, default to 1850 and
    1250 cents per day respectively. The shelter also carries a running ledger field,
    collected_fee_cents, which starts at zero."

    Design: Corner/entities/shelter_defaults_applied_when_omitted
    """
    shelter = validate_success(
        api_client.create_shelter(create_shelter_payload(name="DefaultShelter"), ADMIN), 201
    )
    assert shelter["stray_hold_days"] == 5
    assert shelter["promo_active"] is False
    assert shelter["dog_daily_board_cents"] == 1850
    assert shelter["cat_daily_board_cents"] == 1250
    assert shelter["collected_fee_cents"] == 0


def test_microchip_create_sets_animal_microchipped_computed(api):
    """PRD §3.3: "Registering the first chip for an animal flips that animal's derived
    microchipped flag to true, which later feeds the adoption-fee microchip surcharge
    decision."

    Design: Corner/entities/microchip_create_sets_animal_microchipped_computed
    """
    bootstrap_shelter()
    animal = create_intaken_animal(species="DOG", age_months=24, source="SURRENDER", name="Chip")
    microchip_animal(animal["id"], chip_number="CHIP-9001")
    after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert after["microchipped"] is True


def test_intake_at_system_stamped_from_clock_and_release_computed(api):
    """PRD §3.2: "Recording the intake stamps the server clock onto intake_at, computes
    the stray-hold release instant, drives the animal's lifecycle_status from
    INTAKE_PENDING to IN_CUSTODY."
    PRD §3.2: "For a STRAY intake, it is the intake_at moment plus a number of hours
    equal to the shelter's stray_hold_days multiplied by 24."

    Design: Corner/entities/intake_at_is_system_stamped_from_clock
    """
    bootstrap_shelter(stray_hold_days=5)  # clock set to 2026-06-01T00:00:00Z
    animal = register_animal(name="Sys", species="DOG", age_months=30)
    ir = validate_success(
        api_client.create_intake_record(create_intake_record_payload(animal["id"], source="STRAY"), INTAKE),
        201,
    )
    assert ir["intake_at"] == "2026-06-01T00:00:00.000Z", f"intake_at stamped from clock, got {ir['intake_at']}"
    after = validate_success(api_client.get_animal(animal["id"], INTAKE))
    assert after["stray_hold_release_at"] == "2026-06-06T00:00:00.000Z", (
        f"STRAY release = intake + 5 days, got {after['stray_hold_release_at']}"
    )


def test_microchip_immutable_entity_no_version_field(api):
    """PRD §2.4: "A Microchip is an immutable registry row: it carries only id and
    created_at. It has no updated_at and no version field at all; once written, it is
    never mutated."

    Design: Corner/entities/microchip_immutable_entity_no_version_field
    """
    bootstrap_shelter()
    animal = create_intaken_animal(species="CAT", age_months=12, source="SURRENDER", name="Imm")
    chip = validate_success(
        api_client.create_microchip(create_microchip_payload(animal["id"], "CHIP-9002"), VET), 201
    )
    assert_microchip(chip)
    assert "id" in chip
    assert "version" not in chip, "Microchip must not carry a version field"


# ===================================================================
# Queue B — rbac
# ===================================================================

def test_intake_officer_cannot_record_medical(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN."
    PRD §3.3: "The medical axis is driven entirely by a Veterinarian recording a
    MedicalRecord against an animal."

    Design: Corner/rbac/intake_officer_cannot_record_medical
    """
    bootstrap_shelter()
    animal = create_intaken_animal(species="DOG", age_months=20, source="SURRENDER", name="Med")
    resp = api_client.create_medical_record(
        create_medical_record_payload(animal["id"], record_type="EXAM", outcome="CLEAR"), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_adopter_cannot_finalize_application(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN."
    PRD §3.7: "Finalization is performed by an AdoptionCounselor and is the deepest
    cascade in the system."

    Design: Corner/rbac/adopter_cannot_finalize_application
    """
    bootstrap_shelter()
    animal = create_available_animal(species="CAT", age_months=36, name="Fin")
    adopter = create_adopter(email="ada@x.com", full_name="Ada")
    adopter_hdr = make_adopter_headers(adopter["id"])
    app = validate_success(
        api_client.create_adoption_application(
            create_adoption_application_payload(animal["id"], adopter["id"]), adopter_hdr
        ),
        201,
    )
    approve_application(app["id"])

    resp = api_client.finalize_adoption_application(app["id"], adopter_hdr)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    bootstrap_shelter(clock=None)
    animal = validate_success(
        api_client.create_animal(create_animal_payload(name="Anon", species="DOG", age_months=12), INTAKE),
        201,
    )
    # No X-User-ID / X-User-Role headers.
    resp = api_client.get_animal(animal["id"], {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===================================================================
# Queue B — endpoints: FK integrity, listing
# ===================================================================

def test_create_intake_with_nonexistent_animal_fk_not_found(api):
    """PRD §2.6: "for any write whose body carries a foreign key (such as animal_id ...),
    each such reference must likewise resolve. References are checked in order, and the
    first unresolved identifier ... causes the request to be rejected with
    ERR_NOT_FOUND."

    Design: Corner/endpoints/create_intake_with_nonexistent_animal_fk_not_found
    """
    bootstrap_shelter()
    resp = api_client.create_intake_record(
        create_intake_record_payload("11111111-1111-4111-8111-111111111111", source="STRAY"), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_medical_records_filtered_by_animal(api):
    """PRD §3.3: "Medical records are readable individually and as a list filterable by
    animal_id and record_type."
    PRD §2.3: "The meta object of every list response carries the pagination fields
    limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_medical_records_filtered_by_animal_reverse_reachability
    """
    bootstrap_shelter()
    animal = create_intaken_animal(species="DOG", age_months=24, source="SURRENDER", name="Recs")
    hold_medical(animal["id"])
    clear_medical(animal["id"])

    resp = api_client.list_medical_records(VET, params={"animal_id": animal["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 medical records for the animal, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ===================================================================
# Queue B — cross_cutting: optimistic concurrency
# ===================================================================

def test_kennel_assign_stale_version_returns_412(api):
    """PRD §2.9: "The create-kennel-assignment operation requires the field
    expected_kennel_version, carrying the version of the target kennel as the client
    last observed it; this field is mandatory, not optional. If expected_kennel_version
    does not equal the kennel's current version ... the create is rejected with
    ERR_STALE_VERSION and HTTP status 412, before any occupancy mutation occurs."

    The kennel is OPEN (occupied_count 0) with no overlapping ACTIVE assignment, so the
    occupancy gate passes and only the OCC version mismatch fires — isolating
    ERR_STALE_VERSION. The version has advanced (assign then release) past the stale
    view the client still holds.

    Design: Corner/cross_cutting_complexity_layers/kennel_assign_stale_version_returns_412
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="OCC-1")
    stale_version = kennel["version"]  # version 1, the client's now-stale view
    a = create_intaken_animal(species="DOG", age_months=30, source="SURRENDER", name="A")
    b = create_intaken_animal(species="DOG", age_months=32, source="SURRENDER", name="B")
    ka = assign_kennel(kennel["id"], a["id"], stale_version)  # version 1 -> 2
    validate_success(api_client.release_kennel_assignment(ka["id"], INTAKE))  # version 2 -> 3, OPEN

    # Kennel is OPEN again, but the client still carries the version-1 view -> stale.
    resp = api_client.create_kennel_assignment(
        create_kennel_assignment_payload(kennel["id"], b["id"], stale_version), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_kennel_assign_increments_version_on_success(api):
    """PRD §3.4: "A successful assignment is created with status ACTIVE and start_at
    stamped from the clock, increments the kennel's occupied_count by one, recomputes
    the kennel's status (to FULL if occupied_count now equals capacity), and increments
    the kennel's version by one."

    Design: Corner/cross_cutting_complexity_layers/kennel_assign_increments_version_on_success
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="VER-1")
    assert kennel["version"] == 1
    animal = create_intaken_animal(species="CAT", age_months=18, source="SURRENDER", name="Inc")
    assign_kennel(kennel["id"], animal["id"], kennel["version"])

    after = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert after["version"] == 2, f"version 1 -> 2 on assignment, got {after['version']}"
    assert after["occupied_count"] == 1
    assert after["status"] == "FULL"
