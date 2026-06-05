"""Entity creation/validation, VIN verification effects, fee void gate, and RBAC."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    make_owner_headers,
    set_clock,
    create_owner,
    create_vehicle,
    create_verified_vehicle,
    create_approved_title,
    setup_active_registration,
    assess_fees,
    create_owner_payload,
    create_vehicle_payload,
    create_vin_verification_payload,
)

CLERK = TEST_USERS["clerk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/create_owner_minimal_required_fields_returns_201
# ---------------------------------------------------------------------------
def test_create_owner_defaults_credential_and_real_id_status():
    """PRD §3.1: "An owner may optionally declare a `credential_type`, which is one of
    `STANDARD` or `REAL_ID` and defaults to `STANDARD` ... Each owner also carries a computed
    `real_id_status` that mirrors the REAL ID upgrade lifecycle; it is one of `NONE`, `PENDING`,
    or `UPGRADED` and is initialized to `NONE` at creation."

    Design: Corner/entities/create_owner_minimal_required_fields_returns_201
    """
    resp = api_client.create_owner(
        create_owner_payload(full_name="Jane Owner", residence_county_code="KING"), CLERK
    )
    owner = validate_success(resp, 201)
    assert owner["credential_type"] == "STANDARD"
    assert owner["real_id_status"] == "NONE"


# ---------------------------------------------------------------------------
# Corner/entities/create_vehicle_missing_required_vin_returns_validation
# ---------------------------------------------------------------------------
def test_create_vehicle_missing_vin_validation_error():
    """PRD §2.8: "A malformed body or a missing required field is rejected with `ERR_VALIDATION`
    (HTTP 400)."

    POST /vehicles omitting `vin` (a required input field with no default) is rejected.

    Design: Corner/entities/create_vehicle_missing_required_vin_returns_validation
    """
    owner = create_owner()
    resp = api_client.create_vehicle(
        {
            "owner_id": owner["id"],
            "model_year": 2024,
            "purchase_price_cents": 3000000,
            "msrp_cents": 3200000,
            "vehicle_class": "PASSENGER",
        },
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Corner/entities/create_vehicle_invalid_vin_length_returns_invalid_vin
# ---------------------------------------------------------------------------
def test_create_vehicle_short_vin_invalid_vin_error():
    """PRD §3.1: "The `vin` must be exactly 17 characters long and unique across all vehicles; a
    value that is not 17 characters, or that collides with an existing vehicle's VIN, is rejected
    with `ERR_INVALID_VIN` (HTTP 422)."

    Design: Corner/entities/create_vehicle_invalid_vin_length_returns_invalid_vin
    """
    owner = create_owner()
    resp = api_client.create_vehicle(
        create_vehicle_payload(owner["id"], vin="SHORTVIN"), CLERK
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_VIN.value)


# ---------------------------------------------------------------------------
# Corner/entities/create_vehicle_duplicate_vin_returns_invalid_vin
# ---------------------------------------------------------------------------
def test_create_vehicle_duplicate_vin_invalid_vin_error():
    """PRD §3.1: "The `vin` must be exactly 17 characters long and unique across all vehicles; a
    value that is not 17 characters, or that collides with an existing vehicle's VIN, is rejected
    with `ERR_INVALID_VIN` (HTTP 422)."

    Design: Corner/entities/create_vehicle_duplicate_vin_returns_invalid_vin
    """
    owner = create_owner()
    dup_vin = "1HGCM82633A099991"  # exactly 17 chars
    assert len(dup_vin) == 17
    validate_success(
        api_client.create_vehicle(create_vehicle_payload(owner["id"], vin=dup_vin), CLERK), 201
    )
    resp = api_client.create_vehicle(create_vehicle_payload(owner["id"], vin=dup_vin), CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_VIN.value)


# ---------------------------------------------------------------------------
# Corner/entities/get_vehicle_nonexistent_returns_not_found
# ---------------------------------------------------------------------------
def test_get_nonexistent_vehicle_not_found():
    """PRD §2.8: "Before any business rule runs, the system validates that every resource
    referenced by the request — whether named in the URL path or in the body — exists, checking
    references left to right and rejecting the first missing reference with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_vehicle_nonexistent_returns_not_found
    """
    resp = api_client.get_vehicle(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner/entities/vehicle_computed_defaults_on_create
# ---------------------------------------------------------------------------
def test_vehicle_computed_defaults_on_create():
    """PRD §3.1: "At creation a vehicle's computed `vin_status` is `UNVERIFIED`, its computed
    `title_status` is `NONE`, and its computed `active_lien_count` is 0."

    Design: Corner/entities/vehicle_computed_defaults_on_create
    """
    owner = create_owner()
    veh = validate_success(
        api_client.create_vehicle(create_vehicle_payload(owner["id"]), CLERK), 201
    )
    assert veh["vin_status"] == "UNVERIFIED"
    assert veh["title_status"] == "NONE"
    assert veh["active_lien_count"] == 0


# ---------------------------------------------------------------------------
# Corner/entities/list_vehicles_filter_by_owner_returns_array
# ---------------------------------------------------------------------------
def test_list_vehicles_filtered_by_owner():
    """PRD §3.1: "Because entities are linked by foreign keys rather than nested paths, vehicles
    can be looked up in reverse by filtering on `owner_id` or on `vin`."

    Design: Corner/entities/list_vehicles_filter_by_owner_returns_array
    """
    owner = create_owner()
    veh = create_vehicle(owner_id=owner["id"])
    resp = api_client.list_vehicles(CLERK, params={"owner_id": owner["id"]})
    body = resp.json()
    assert body["response_type"] == "array"
    assert any(row["owner_id"] == owner["id"] for row in body["data"])
    assert any(row["id"] == veh["id"] for row in body["data"])


# ---------------------------------------------------------------------------
# Corner/endpoints/vin_verification_mismatch_flags_vehicle
# ---------------------------------------------------------------------------
def test_vin_verification_mismatch_flags_vehicle():
    """PRD §3.1: "A `MATCH` outcome sets the vehicle's `vin_status` to `VERIFIED`; an outcome of
    either `MISMATCH` or `NHTSA_FLAG` sets it to `FLAGGED`."

    Design: Corner/endpoints/vin_verification_mismatch_flags_vehicle
    """
    owner = create_owner()
    veh = create_vehicle(owner_id=owner["id"])
    validate_success(
        api_client.create_vin_verification(
            create_vin_verification_payload(veh["id"], "WRONGVIN111111111", "MISMATCH"), CLERK
        ),
        201,
    )
    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    assert veh_after["vin_status"] == "FLAGGED"


# ---------------------------------------------------------------------------
# Corner/endpoints/fee_void_blocked_when_registration_not_pending
# ---------------------------------------------------------------------------
def test_void_fee_on_active_registration_rejected():
    """PRD §3.5: "An assessment may instead be voided by an administrator, advancing it
    `ASSESSED → VOIDED`; voiding requires the assessment to be in `ASSESSED` (otherwise
    `ERR_INVALID_STATE`, HTTP 409) and requires the parent registration to still be in
    `PENDING_FEES` (otherwise `ERR_REGISTRATION_NOT_ACTIVE`, HTTP 409)."

    A fresh ASSESSED assessment on an already-ACTIVE registration cannot be voided.

    Design: Corner/endpoints/fee_void_blocked_when_registration_not_pending
    """
    owner, veh, reg = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    fa2 = assess_fees(reg["id"])  # second assessment, registration already ACTIVE
    resp = api_client.void_fee_assessment(fa2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Corner/rbac/owner_cannot_issue_title_forbidden
# ---------------------------------------------------------------------------
def test_owner_cannot_issue_title_forbidden():
    """PRD §4 (authorization table): "POST | /title-applications/{id}/issue | Issue the title |
    ClerkAgent". PRD §2.1: "When both headers are present but the named role is not permitted to
    perform the requested operation (per the authorization table in §4), the request is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Issue is a ClerkAgent-only operation; an Owner calling it is forbidden.

    Design: Corner/rbac/owner_cannot_issue_title_forbidden
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"])
    ta = create_approved_title(veh["id"], owner["id"], "INITIAL")
    resp = api_client.issue_title_application(ta["id"], make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Corner/rbac/clerk_cannot_suspend_registration_forbidden
# ---------------------------------------------------------------------------
def test_clerk_cannot_suspend_registration_forbidden():
    """PRD §4 (authorization table): "POST | /registrations/{id}/suspend | Suspend an active
    registration | DmvAdmin". PRD §2.1: "When both headers are present but the named role is not
    permitted to perform the requested operation (per the authorization table in §4), the request
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Suspend is a DmvAdmin-only operation; a ClerkAgent calling it is forbidden.

    Design: Corner/rbac/clerk_cannot_suspend_registration_forbidden
    """
    owner, veh, reg = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    resp = api_client.suspend_registration(reg["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Corner/rbac/missing_headers_unauthenticated
# ---------------------------------------------------------------------------
def test_missing_auth_headers_unauthenticated():
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, naming the principal's role. A request missing either header is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api_client.create_owner(
        create_owner_payload(full_name="Anon", residence_county_code="KING"),
        {"Content-Type": "application/json"},  # no X-User-ID / X-User-Role
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
