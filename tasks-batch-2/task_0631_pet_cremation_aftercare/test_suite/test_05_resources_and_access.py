"""Resource creation/retrieval surface and role-based access control.

Covers the entity corner instances and the RBAC corner instances.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    create_owner, create_case, set_clock, get_case_version,
    setup_private_case_invoiced,
    make_clinic_staff_headers, make_pet_owner_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _case(case_id):
    return get_success_data(api_client.get_case(case_id, ADMIN))


# =========================================================================== #
# Corner: entities
# =========================================================================== #
def test_create_case_returns_201_with_initial_fields(api):
    """PRD §3.2: "On creation the case begins in custody `INTAKE_PENDING` and billing
    `NOT_BILLABLE`, its `cremation_charge_cents` is 0 until a firing determines it, its
    `custody_chain_open` flag is true, and it has not yet been assigned a `batch_id` or a
    `cooler_id`"

    Design: Corner/entities/entity_case_create_returns_201_with_fields
    """
    owner = create_owner()
    payload = {
        "owner_id": owner["id"], "pet_name": "New", "species": "DOG", "weight_lbs": 40,
        "service_type": "PRIVATE", "pickup_kind": "HOME", "bill_to": "OWNER",
    }
    case = validate_success(api_client.create_case(payload, OPERATOR), 201)
    assert case["custody_status"] == "INTAKE_PENDING"
    assert case["billing_status"] == "NOT_BILLABLE"
    assert case["weight_tier"] == "MEDIUM"
    assert case["custody_chain_open"] is True
    assert case["cremation_charge_cents"] == 0


def test_get_case_not_found(api):
    """PRD §2.6: "the server validates each identifier from left to right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not name an
    existing resource."

    Design: Corner/entities/entity_case_get_not_found
    """
    validate_error(api_client.get_case(NON_EXISTENT_UUID, OPERATOR),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_case_missing_owner_id_invalid_request(api):
    """PRD §3.2: "A `CrematoryOperator` or a `ClinicStaff` principal opens a case by
    providing the `owner_id` of the bereaved owner, the `pet_name`, the `species` ... the
    `weight_lbs` ... the `service_type` ... the `pickup_kind` ... and the `bill_to` party"
    PRD §2.10: "Request well-formedness — required body fields present and correctly typed,
    enum values legal, numbers within their declared bounds — is checked fourth, failing
    with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/entity_case_missing_required_field
    """
    payload = {
        "pet_name": "X", "species": "DOG", "weight_lbs": 40, "service_type": "PRIVATE",
        "pickup_kind": "HOME", "bill_to": "OWNER",
    }
    validate_error(api_client.create_case(payload, OPERATOR),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_case_invalid_species_enum(api):
    """PRD §3.2: "the `species` (one of `DOG`, `CAT`, or `OTHER`)"
    PRD §2.10: "Request well-formedness — required body fields present and correctly typed,
    enum values legal, numbers within their declared bounds — is checked fourth, failing
    with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/entity_case_invalid_enum_species
    """
    owner = create_owner()
    payload = {
        "owner_id": owner["id"], "pet_name": "X", "species": "FISH", "weight_lbs": 40,
        "service_type": "PRIVATE", "pickup_kind": "HOME", "bill_to": "OWNER",
    }
    validate_error(api_client.create_case(payload, OPERATOR),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_clinic_create_system_fields_generated(api):
    """PRD §3.1: "A new clinic starts with an `outstanding_balance_cents` of 0 and an
    `account_status` of `CURRENT`."
    PRD §2.4: "an integer `version` that begins at its initial value and increments by one
    on each mutation."

    Design: Corner/entities/entity_clinic_create_system_fields_generated
    """
    clinic = validate_success(api_client.create_clinic(
        {"name": "CL-Sys", "account_code": "SYS-1"}, ADMIN), 201)
    assert clinic["version"] == 1
    assert clinic["outstanding_balance_cents"] == 0
    assert clinic["account_status"] == "CURRENT"


def test_clinic_default_credit_limit_applied(api):
    """PRD §3.1: "optionally a `credit_limit_cents` that defaults to 500000 (five thousand
    dollars) when not supplied."

    Design: Corner/entities/entity_clinic_default_credit_limit_applied
    """
    clinic = validate_success(api_client.create_clinic(
        {"name": "CL-Def", "account_code": "DEF-1"}, ADMIN), 201)
    assert clinic["credit_limit_cents"] == 500000


def test_case_list_pagination_envelope(api):
    """PRD §2.3: "List responses include the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/entity_case_list_pagination_envelope
    """
    owner = create_owner()
    create_case(owner["id"], service_type="PRIVATE", weight_lbs=40,
                bill_to="OWNER", pickup_kind="HOME")
    data, meta = validate_paginated(api_client.list_cases(OPERATOR,
                                    params={"limit": 10, "offset": 0}))
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False, "one case under limit 10 leaves no more pages"


def test_custody_event_is_append_only_no_version(api):
    """PRD §2.4: "the `CustodyEvent` and the `CertificateRecord` carry only `id` and
    `created_at`. Neither one exposes an `updated_at` field nor a `version` field"
    PRD §3.2: "The server immediately appends the first custody event of type `INTAKE` to
    the case's chain. Every custody event carries a per-case `seq` that starts at 1"

    Design: Corner/entities/entity_custodyevent_immutable_no_version
    """
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=40,
                       bill_to="OWNER", pickup_kind="HOME")
    events, _ = validate_paginated(api_client.list_custody_events(case["id"], OPERATOR))
    first = events[0]
    assert first["event_type"] == "INTAKE"
    assert first["seq"] == 1
    assert "version" not in first
    assert "updated_at" not in first


# =========================================================================== #
# Corner: rbac
# =========================================================================== #
def test_clinic_staff_cannot_create_clinic(api):
    """PRD §2.1: "When a request is authenticated but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 (endpoint table): "POST | `/clinics` | Create a clinic account | CrematoryAdmin"

    Design: Corner/rbac/rbac_clinicstaff_cannot_create_clinic
    """
    clinic = get_success_data(api_client.create_clinic(
        {"name": "CL-Rb", "account_code": "RB-1"}, ADMIN))
    staff = make_clinic_staff_headers(clinic["id"])
    validate_error(api_client.create_clinic(
        {"name": "CL-Sneak", "account_code": "SNK-1"}, staff),
        ApiErrorId.ERR_FORBIDDEN.value)


def test_pet_owner_cannot_pay_other_owners_invoice(api):
    """PRD §2.1: "a `PetOwner` may view only their own pet's case ... and may pay only
    their own owner-billed invoice. Any attempt by an entity-backed principal to read or
    act on another party's resource is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/rbac_petowner_cannot_pay_other_owner_invoice
    """
    ctx = setup_private_case_invoiced(clock="2026-05-15T00:00:00Z", weight_lbs=50,
                                      bill_to="OWNER")
    inv_id = ctx["invoice"]["id"]
    other_owner = create_owner()
    other_headers = make_pet_owner_headers(other_owner["id"])

    validate_error(api_client.pay_invoice(inv_id, other_headers),
                   ApiErrorId.ERR_FORBIDDEN.value)
    assert get_success_data(api_client.get_invoice(inv_id, ADMIN))["status"] == "ISSUED"


def test_unauthenticated_unknown_role_header(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` does not name a recognized
    role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/rbac_unauthenticated_missing_role_header
    """
    from prd_bench_local_runner.testing import build_user_headers
    bad_headers = build_user_headers("nobody", "Nobody")
    validate_error(api_client.get_case(NON_EXISTENT_UUID, bad_headers),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)
