"""Entity creation defaults, input validation, initial states, and RBAC
(PRD §2.1, §2.4, §3.1, §3.2).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_owner_headers,
    make_unknown_role_headers,
    set_clock,
    create_owner,
    create_pet,
    create_draft_license,
    assert_owner,
    assert_vaccination_record,
)
from test_helpers import api_client

CLERK = TEST_USERS["clerk_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_create_owner_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly registered owner begins in ACTIVE standing, with both
    derived figures - active_license_count and outstanding_penalty_cents - at
    zero."

    Design: Corner/entities/create_owner_returns_201_with_defaults
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_owner(
        {"full_name": "New Owner", "email": "new@x.com", "address_zip": "10000"}, CLERK
    )
    owner = validate_success(res, 201)
    assert_owner(owner)
    assert owner["status"] == "ACTIVE"
    assert owner["active_license_count"] == 0
    assert owner["outstanding_penalty_cents"] == 0


def test_get_owner_not_found_returns_404(api):
    """PRD §2.5: "the server resolves identifiers left to right and rejects the
    request with ERR_NOT_FOUND against the first identifier in the path that does
    not name an existing record".

    Design: Corner/entities/get_owner_not_found_returns_404
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.get_owner(NON_EXISTENT_UUID, CLERK)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_pet_missing_required_field_returns_invalid_request(api):
    """PRD §2.6: "Then comes request well-formedness: required fields present,
    enumerations in range ... any violation of which is ERR_INVALID_REQUEST (HTTP
    400)".

    Design: Corner/entities/create_pet_missing_required_field_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="P Owner", email="po@x.com", address_zip="10010")
    # Omit required species.
    res = api.create_pet(
        {
            "owner_id": owner["id"], "name": "Nameless", "breed": "B",
            "is_altered": False, "birth_date": "2024-01-01T00:00:00Z",
        },
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_pet_invalid_enum_species_returns_invalid_request(api):
    """PRD §2.6: "Then comes request well-formedness: required fields present,
    enumerations in range ... any violation of which is ERR_INVALID_REQUEST (HTTP
    400)".
    PRD §3.1: "a species of either DOG or CAT".

    Design: Corner/entities/create_pet_invalid_enum_species_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Q Owner", email="qo@x.com", address_zip="10011")
    res = api.create_pet(
        {
            "owner_id": owner["id"], "name": "Tweety", "species": "BIRD", "breed": "B",
            "is_altered": False, "birth_date": "2024-01-01T00:00:00Z",
        },
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_license_term_years_out_of_set_returns_invalid_request(api):
    """PRD §2.6: "term_years one of the two permitted whole-year terms ... any
    violation of which is ERR_INVALID_REQUEST (HTTP 400)".
    PRD §3.2: "a term_years that must be a whole-year term of either 1 or 3".

    Design: Corner/entities/create_license_term_years_out_of_set_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="R Owner", email="ro@x.com", address_zip="10012")
    pet = create_pet(owner["id"], name="Bud", is_altered=True, species="DOG")
    res = api.create_license(
        {
            "owner_id": owner["id"], "pet_id": pet["id"],
            "license_kind": "INDIVIDUAL", "term_years": 2,
        },
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_vaccination_record_immutable_no_version_field(api):
    """PRD §2.4: "Two record types are deliberately immutable and therefore carry
    only id and created_at - they have neither an updated_at nor a version field.
    The first is the vaccination record, which is a proof artifact captured once
    and never edited."

    Design: Corner/entities/vaccination_record_immutable_no_version_field
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="S Owner", email="so@x.com", address_zip="10013")
    pet = create_pet(owner["id"], name="Vax", is_altered=True, species="CAT")
    res = api.create_vaccination_record(
        {
            "pet_id": pet["id"], "vaccine_type": "RABIES",
            "administered_on": "2025-06-01T00:00:00Z",
            "expires_on": "2030-06-01T00:00:00Z", "vet_license_no": "VS",
        },
        make_owner_headers(owner["id"]),
    )
    vr = validate_success(res, 201)
    assert_vaccination_record(vr)
    assert vr["vaccine_type"] == "RABIES"
    assert "version" not in vr
    assert "updated_at" not in vr


def test_pet_computed_is_dangerous_defaults_false(api):
    """PRD §3.1: "is_dangerous, which starts false and flips to true only once a
    dangerous-dog case for that pet reaches designation".

    Design: Corner/entities/pet_computed_is_dangerous_input_ignored
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="T Owner", email="to@x.com", address_zip="10014")
    res = api.create_pet(
        {
            "owner_id": owner["id"], "name": "Calm", "species": "DOG", "breed": "B",
            "is_altered": True, "birth_date": "2024-01-01T00:00:00Z",
        },
        make_owner_headers(owner["id"]),
    )
    pet = validate_success(res, 201)
    assert pet["is_dangerous"] is False


def test_license_initial_state_is_draft(api):
    """PRD §3.2: "An application is created in DRAFT".
    PRD §3.2: "At creation the license carries no fees - provisional_fee_cents and
    final_fee_cents and late_penalty_cents all sit at zero".

    Design: Corner/state_machines/license_initial_state_is_draft
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="V Owner", email="vo@x.com", address_zip="10016")
    pet = create_pet(owner["id"], name="Init", is_altered=True, species="DOG")
    res = api.create_license(
        {
            "owner_id": owner["id"], "pet_id": pet["id"],
            "license_kind": "INDIVIDUAL", "term_years": 1,
        },
        make_owner_headers(owner["id"]),
    )
    lic = validate_success(res, 201)
    assert lic["status"] == "DRAFT"
    assert lic["provisional_fee_cents"] == 0


def test_clerk_cannot_designate_dangerous_dog(api):
    """PRD §2.1: "When an authenticated caller attempts an operation their role is
    not permitted to perform ... the request is rejected with ERR_UNAUTHORIZED."
    PRD §4: POST /dangerous-dog-cases is authorized for AnimalControlOfficer only.

    Design: Corner/rbac/clerk_cannot_designate_dangerous_dog
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="UU Owner", email="uu@x.com", address_zip="10028")
    pet = create_pet(owner["id"], name="Pup", is_altered=False, species="DOG")
    # A LicensingClerk opening a dangerous-dog case (officer-exclusive).
    res = api.create_dangerous_dog_case(
        {"pet_id": pet["id"], "incident_summary": "x", "severity": "BITE"}, CLERK
    )
    validate_error(res, "ERR_UNAUTHORIZED")


def test_owner_cannot_act_on_other_owners_license(api):
    """PRD §2.1: "an Owner may only submit, attach proof to, renew, pay the penalty
    on, or otherwise act on a License whose owner_id equals their X-User-ID ... a
    mismatch yields ERR_UNAUTHORIZED."

    Design: Corner/rbac/owner_cannot_act_on_other_owners_license
    """
    set_clock("2026-01-01T00:00:00Z")
    owner_a = create_owner(full_name="Owner AA", email="aa@x.com", address_zip="10029")
    owner_b = create_owner(full_name="Owner BB", email="bb@x.com", address_zip="10030")
    pet = create_pet(owner_a["id"], name="Mine", is_altered=True, species="DOG")
    lic = create_draft_license(
        owner_a["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1
    )
    # Owner B submits Owner A's draft license.
    res = api.submit_license(lic["id"], make_owner_headers(owner_b["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_owner(
        {"full_name": "Ghost", "email": "ghost@x.com", "address_zip": "10031"},
        make_unknown_role_headers(),
    )
    validate_error(res, "ERR_UNAUTHENTICATED")
