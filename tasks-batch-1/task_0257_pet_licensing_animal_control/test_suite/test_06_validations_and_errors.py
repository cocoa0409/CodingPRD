"""Validation rules, error precedence, and invalid transitions
(PRD §2.6, §3.2–§3.5, §3.7).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_owner_headers,
    set_clock,
    advance_clock,
    create_owner,
    create_pet,
    create_rabies_record,
    create_kennel,
    create_draft_license,
    setup_expired_individual_license,
    drive_license_to_active,
)
from test_helpers import api_client

CLERK = TEST_USERS["clerk_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_existence_beats_state_on_approve(api):
    """PRD §2.6: "Existence checks follow, with every path and foreign-key-
    referenced record resolved left to right and a miss reported as ERR_NOT_FOUND
    (HTTP 404). ... Only after those gates does the system test whether the target
    resource is in a state from which the requested transition is defined, raising
    ERR_INVALID_STATE (HTTP 409) when it is not."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_approve
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.approve_license(NON_EXISTENT_UUID, CLERK)
    validate_error(res, "ERR_NOT_FOUND")


def test_existence_beats_state_on_issue_tag(api):
    """PRD §2.6: "Existence checks follow, with every path and foreign-key-
    referenced record resolved left to right and a miss reported as ERR_NOT_FOUND
    (HTTP 404). ... Only after those gates does the system test whether the target
    resource is in a state from which the requested transition is defined, raising
    ERR_INVALID_STATE (HTTP 409) when it is not."

    Companion (same existence-before-state precedence on a different transition
    endpoint): issue-tag on a non-existent license is both an existence failure
    and trivially a state failure; ERR_NOT_FOUND (404) wins over ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_approve
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.issue_tag(NON_EXISTENT_UUID, CLERK)
    validate_error(res, "ERR_NOT_FOUND")


def test_attach_vaccination_pet_mismatch_returns_vaccination_mismatch(api):
    """PRD §3.3: "The record must belong to the same pet - its pet_id must equal
    the license's pet_id - or the attach is refused with ERR_VACCINATION_MISMATCH."

    Design: Corner/validations/attach_vaccination_pet_mismatch_returns_vaccination_mismatch
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="MM Owner", email="mm@x.com", address_zip="10021")
    pa = create_pet(owner["id"], name="PA", is_altered=True, species="DOG")
    pb = create_pet(owner["id"], name="PB", is_altered=True, species="DOG")
    # RABIES record for the OTHER pet (pb).
    vb = create_rabies_record(owner["id"], pb["id"])
    lic = create_draft_license(owner["id"], pa["id"], license_kind="INDIVIDUAL", term_years=1)
    oh = make_owner_headers(owner["id"])
    validate_success(api.submit_license(lic["id"], oh), 200)
    validate_success(api.start_review_license(lic["id"], CLERK), 200)
    validate_success(api.request_vaccination_proof(lic["id"], CLERK), 200)

    res = api.attach_vaccination(lic["id"], {"vaccination_record_id": vb["id"]}, oh)
    validate_error(res, "ERR_VACCINATION_MISMATCH")


def test_approve_without_rabies_proof_returns_rabies_required(api):
    """PRD §3.3: "a rabies proof must be on file and still valid, meaning the
    license's vaccination_record_id is set and that record is a RABIES record whose
    expires_on is later than the current time, failing which the approval is
    refused with ERR_RABIES_PROOF_REQUIRED".

    Design: Corner/validations/approve_without_rabies_proof_returns_rabies_required
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="NN Owner", email="nn@x.com", address_zip="10022")
    pet = create_pet(owner["id"], name="Noproof", is_altered=True, species="DOG")
    lic = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)
    oh = make_owner_headers(owner["id"])
    # SUBMITTED → UNDER_REVIEW directly, no proof attached.
    validate_success(api.submit_license(lic["id"], oh), 200)
    validate_success(api.start_review_license(lic["id"], CLERK), 200)

    res = api.approve_license(lic["id"], CLERK)
    validate_error(res, "ERR_RABIES_PROOF_REQUIRED")


def test_attach_expired_vaccination_returns_vaccination_expired(api):
    """PRD §3.3: "the record must still be in force, meaning its expires_on is
    strictly later than the current time; a record whose expires_on falls at or
    before now is refused with ERR_VACCINATION_EXPIRED."

    Design: Corner/validations/attach_expired_vaccination_returns_vaccination_expired
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="OO Owner", email="oo2@x.com", address_zip="10023")
    pet = create_pet(owner["id"], name="Exp", is_altered=True, species="DOG")
    # RABIES record already expired vs clock 2026-01-01.
    vr = create_rabies_record(
        owner["id"], pet["id"], administered_on="2024-06-01T00:00:00Z",
        expires_on="2025-12-31T00:00:00Z",
    )
    lic = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)
    oh = make_owner_headers(owner["id"])
    validate_success(api.submit_license(lic["id"], oh), 200)
    validate_success(api.start_review_license(lic["id"], CLERK), 200)
    validate_success(api.request_vaccination_proof(lic["id"], CLERK), 200)

    res = api.attach_vaccination(lic["id"], {"vaccination_record_id": vr["id"]}, oh)
    validate_error(res, "ERR_VACCINATION_EXPIRED")


def test_individual_license_with_kennel_id_returns_kind_mismatch(api):
    """PRD §3.2: "If the kind is INDIVIDUAL, the kennel_id must be null. A
    kind/kennel mismatch - an INDIVIDUAL carrying a kennel_id ... - is rejected
    with ERR_LICENSE_KIND_MISMATCH."

    Design: Corner/validations/individual_license_with_kennel_id_returns_kind_mismatch
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="PP Owner", email="pp@x.com", address_zip="10024")
    kennel = create_kennel(owner["id"], slot_capacity=3, facility_name="PP Kennel")
    pet = create_pet(owner["id"], name="Solo", is_altered=True, species="DOG")

    res = api.create_license(
        {
            "owner_id": owner["id"], "pet_id": pet["id"],
            "license_kind": "INDIVIDUAL", "term_years": 1, "kennel_id": kennel["id"],
        },
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_LICENSE_KIND_MISMATCH")


def test_delinquent_owner_submit_returns_owner_delinquent(api):
    """PRD §3.2: "The owner's own standing must be ACTIVE: a DELINQUENT owner may
    not submit any new application, and the attempt is refused with
    ERR_OWNER_DELINQUENT."

    Design: Corner/validations/delinquent_owner_submit_returns_owner_delinquent
    """
    set_clock("2026-01-01T00:00:00Z")
    # First license expires unpaid → owner becomes DELINQUENT.
    owner, _, _, _ = setup_expired_individual_license(
        owner=create_owner(full_name="OQ Owner", email="oq@x.com", address_zip="10025"),
        pet_overrides={"is_altered": False, "name": "First"},
    )
    owner_now = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_now["status"] == "DELINQUENT"

    # Fresh DRAFT license for a second pet, ready to submit.
    pet2 = create_pet(owner["id"], name="Second", is_altered=True, species="CAT")
    lic2 = create_draft_license(owner["id"], pet2["id"], license_kind="INDIVIDUAL", term_years=1)

    res = api.submit_license(lic2["id"], make_owner_headers(owner["id"]))
    validate_error(res, "ERR_OWNER_DELINQUENT")


def test_renew_from_expired_underpaid_returns_penalty_unpaid(api):
    """PRD §3.5: "either penalty_paid is already true, or the request settles it
    now with pay_penalty_cents equal to the license's late_penalty_cents in full;
    an unsettled penalty blocks the renewal with ERR_PENALTY_UNPAID."

    Design: Corner/validations/renew_from_expired_underpaid_returns_penalty_unpaid
    """
    set_clock("2026-01-01T00:00:00Z")
    # EXPIRED license with late_penalty_cents=2000.
    owner, pet, vr, lic = setup_expired_individual_license(
        owner=create_owner(full_name="RR Owner", email="rr2@x.com", address_zip="10026"),
        pet_overrides={"is_altered": False, "name": "Late"},
    )
    assert lic["late_penalty_cents"] == 2000

    res = api.renew_license(
        lic["id"], make_owner_headers(owner["id"]), payload={"pay_penalty_cents": 1000}
    )
    validate_error(res, "ERR_PENALTY_UNPAID")


def test_submit_after_pet_deceased_returns_pet_not_active(api):
    """PRD §3.2: "The pet must be ACTIVE, else ERR_PET_NOT_ACTIVE."

    Design: Corner/errors/pet_not_active_on_submit_after_deceased
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="TT Owner", email="tt@x.com", address_zip="10027")
    pet = create_pet(owner["id"], name="Gone", is_altered=True, species="DOG")
    # DRAFT license created BEFORE the pet dies.
    lic = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)
    oh = make_owner_headers(owner["id"])
    validate_success(api.mark_pet_deceased(pet["id"], oh), 200)

    res = api.submit_license(lic["id"], oh)
    validate_error(res, "ERR_PET_NOT_ACTIVE")

    pet_after = validate_success(api.get_pet(pet["id"], CLERK), 200)
    assert pet_after["status"] == "DECEASED"


def test_pagination_limit_over_max_returns_validation(api):
    """PRD §2.3: "A request that supplies a limit below 1 or above 100, or an
    offset below 0, is rejected with ERR_VALIDATION."

    Design: Corner/errors/pagination_limit_over_max_returns_validation
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.list_licenses(CLERK, params={"limit": 500})
    validate_error(res, "ERR_VALIDATION")


def test_start_review_from_draft_returns_invalid_state(api):
    """PRD §3.3: "a LicensingClerk opens review, advancing it SUBMITTED ->
    UNDER_REVIEW; the only precondition is that the license is in SUBMITTED, else
    ERR_INVALID_STATE."

    Design: Corner/state_machines/start_review_from_draft_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="U Owner", email="uo@x.com", address_zip="10015")
    pet = create_pet(owner["id"], name="Dft", is_altered=True, species="DOG")
    lic = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)

    res = api.start_review_license(lic["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE")

    lic_after = validate_success(api.get_license(lic["id"], CLERK), 200)
    assert lic_after["status"] == "DRAFT"


def test_revoke_from_rejected_terminal_returns_invalid_state(api):
    """PRD §3.4: "The officer may revoke a license that is in ACTIVE or in GRACE,
    advancing it to the terminal REVOKED; from any other state the request fails
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/revoke_from_rejected_terminal_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="W Owner", email="wo@x.com", address_zip="10017")
    pet = create_pet(owner["id"], name="Rej", is_altered=True, species="DOG")
    lic = create_draft_license(owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1)
    oh = make_owner_headers(owner["id"])
    validate_success(api.submit_license(lic["id"], oh), 200)
    validate_success(api.start_review_license(lic["id"], CLERK), 200)
    validate_success(api.reject_license(lic["id"], CLERK), 200)

    res = api.revoke_license(lic["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE")

    lic_after = validate_success(api.get_license(lic["id"], CLERK), 200)
    assert lic_after["status"] == "REJECTED"
