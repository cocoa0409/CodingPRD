"""Resource creation defaults, not-found / invalid-request handling, listing
pagination, and role/ownership enforcement.

Covers queue B (entities, rbac sections).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_account,
    create_pet,
    setup_received_sample,
)
from test_helpers.factories import (
    create_pet_payload,
    create_kit_payload,
    create_genotyping_run_payload,
    activate_kit_payload,
)
from test_helpers.test_users import make_account_headers
from test_helpers.assertions import assert_account

ADMIN = TEST_USERS["platform_admin_headers"]
LAB = TEST_USERS["lab_technician_headers"]


# =========================================================================
# Corner: entities
# =========================================================================

def test_create_account_returns_201_with_defaults(api):
    """PRD §3.1: "`data_residency`, which is one of `US` or `EU` and defaults to
    `US` when omitted" ... "`relative_finder_opt_in`, a boolean master switch for
    the genetic-relative network that defaults to `false`."
    PRD §2.4: "`version` — an integer that starts at its initial value on creation"

    Design: Corner/entities/create_account_returns_201_with_system_fields
    """
    resp = api.create_account({"email": "new-acct@example.com", "full_name": "New"}, ADMIN)
    account = validate_success(resp, expected_status=201)
    assert_account(account)
    assert account["version"] == 1, f"version must start at 1, got {account['version']}"
    assert account["data_residency"] == "US", "data_residency must default to US"
    assert account["relative_finder_opt_in"] is False, "opt-in must default to false"
    assert account["pet_count"] == 0, "pet_count must default to 0"
    assert account["purge_pending"] is False, "purge_pending must default to false"


def test_get_nonexistent_account_returns_not_found(api):
    """PRD §2.7: "the server validates existence left to right and rejects the
    first referent that does not exist with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_pet_missing_species_returns_invalid_request(api):
    """PRD §3.1: "A **Pet** is registered by its owning account, which supplies
    the pet's `account_id`, its `name`, its `species` (one of `DOG` or `CAT`), and
    its `birth_year`"
    PRD §2.8: "presence of required body fields and valid enum values
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_pet_missing_required_field_returns_invalid_request
    """
    account = create_account()
    acct_h = make_account_headers(account["id"])
    resp = api.create_pet(
        {"account_id": account["id"], "name": "NoSpecies", "birth_year": 2020}, acct_h
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_pet_invalid_species_enum_returns_invalid_request(api):
    """PRD §3.1: "its `species` (one of `DOG` or `CAT`)"
    PRD §2.8: "presence of required body fields and valid enum values
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_pet_invalid_enum_species_returns_invalid_request
    """
    account = create_account()
    acct_h = make_account_headers(account["id"])
    resp = api.create_pet(
        {"account_id": account["id"], "name": "Bird", "species": "BIRD", "birth_year": 2020},
        acct_h,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_pet_defaults_opt_in_false_and_registered(api):
    """PRD §3.1: "A pet may also be given a per-pet `relative_finder_opt_in`,
    again defaulting to `false`. On registration the pet enters the `REGISTERED`
    state"
    PRD §3.1: "A pet also carries a computed `finalized_report_id`, the id of the
    pet's most recent finalized report (the latest by creation timestamp, with
    the last one winning), or null when the pet has no finalized report."

    Design: Corner/entities/pet_defaults_relative_finder_opt_in_false
    """
    account = create_account()
    acct_h = make_account_headers(account["id"])
    pet = validate_success(
        api.create_pet(create_pet_payload(account["id"], name="Def"), acct_h),
        expected_status=201,
    )
    assert pet["relative_finder_opt_in"] is False, "opt-in must default to false"
    assert pet["status"] == "REGISTERED", f"expected REGISTERED, got {pet['status']}"
    assert pet["finalized_report_id"] is None, "finalized_report_id must default to null"


def test_kit_barcode_system_minted_and_unique(api):
    """PRD §3.2: "On creation the server mints a unique `barcode` used later for
    swab activation, and the kit enters the `ORDERED` state"

    Design: Corner/entities/kit_barcode_is_system_minted_unique
    """
    account = create_account()
    acct_h = make_account_headers(account["id"])
    k1 = validate_success(api.create_kit(create_kit_payload(account["id"], "BREED"), acct_h),
                          expected_status=201)
    k2 = validate_success(api.create_kit(create_kit_payload(account["id"], "BREED"), acct_h),
                          expected_status=201)
    assert k1["barcode"] and k2["barcode"], "barcodes must be non-null"
    assert k1["barcode"] != k2["barcode"], "barcodes must be distinct"
    assert k1["status"] == "ORDERED", f"kit must start ORDERED, got {k1['status']}"


def test_list_pets_paginated_envelope(api):
    """PRD §2.3: "The response envelope's `meta` object on any list response
    carries the four pagination fields `limit`, `offset`, `total_count`, and
    `has_more`, where `total_count` is the size of the full filtered set and
    `has_more` indicates whether further pages remain beyond the current window."

    Design: Corner/entities/list_pets_paginated_envelope
    """
    account = create_account()
    acct_h = make_account_headers(account["id"])
    create_pet(account["id"], name="L1")
    create_pet(account["id"], name="L2", species="CAT")

    resp = api.list_pets(acct_h, params={"account_id": account["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true with limit 1 over 2 pets"


# =========================================================================
# Corner: rbac
# =========================================================================

def test_account_cannot_create_genotyping_run(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4: `POST /dna/samples/{id}/genotyping-runs` is authorised for
    `LabTechnician` only.

    Design: Corner/rbac/account_cannot_create_genotyping_run
    """
    base = setup_received_sample(product_tier="BREED")
    acct_h = make_account_headers(base["account"]["id"])
    resp = api.create_genotyping_run(
        base["sample"]["id"],
        create_genotyping_run_payload(call_rate=0.99, het_rate=0.35, contamination=0.01),
        acct_h,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_account_cannot_activate_other_accounts_kit(api):
    """PRD §2.1: "an `Account` acts only on resources that resolve to its own
    `id`."
    PRD §2.8: "fourth, ownership — that the acting account owns the targeted
    resource (`ERR_NOT_RESOURCE_OWNER`)"

    Design: Corner/rbac/account_cannot_act_on_other_accounts_kit
    """
    account_a = create_account()
    pet = create_pet(account_a["id"], name="Pa")
    kit = get_success_data(
        api.create_kit(create_kit_payload(account_a["id"], "BREED"),
                       make_account_headers(account_a["id"]))
    )
    account_b = create_account()
    resp = api.activate_kit(
        kit["id"], activate_kit_payload(pet["id"]), make_account_headers(account_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "When either header is missing or malformed on an authenticated
    endpoint, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    account = create_account()
    resp = api.create_pet(
        create_pet_payload(account["id"], name="NoAuth"), headers={}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
