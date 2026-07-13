"""RBAC partitioning, validation precedence (authorization before state), invalid-state
transitions, required-field validation, not-found paths, listing, and immediate read-back.

Covers difficulty instance authz_beats_state_on_open_protest_wrong_role and corner instances
close_hearing_from_proposed_returns_invalid_state, confirm_already_confirmed_roll_returns_invalid_state,
parcel_owner_cannot_issue_bond, auditor_cannot_create_district,
district_create_returns_201_with_system_fields, district_get_non_existent_returns_not_found,
parcel_create_missing_required_apn_rejected, list_district_parcels_paginated,
parcel_creation_immediately_readable.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    NON_EXISTENT_UUID, make_parcel_owner_headers,
    setup_formed_district, setup_confirmed_roll, authorize_bond,
    create_district, add_parcel,
    create_district_payload, create_parcel_payload,
)

ADMIN = TEST_USERS["admin_headers"]
TREAS = TEST_USERS["treasurer_headers"]
AUDIT = TEST_USERS["auditor_headers"]


# --- authorization checked before state (validation precedence) ---

def test_open_protest_wrong_role_reports_unauthorized(api):
    """PRD §2.10: "authentication first (`ERR_UNAUTHENTICATED`, HTTP 401), then authorization
    including parcel-ownership scope (`ERR_UNAUTHORIZED`, HTTP 403), then path-resource
    existence left to right ... then resource-state legality of the requested transition".
    PRD §4: open-protest (`POST /districts/{id}/open-protest`) is authorized for
    `DistrictAdministrator`.

    Design: Difficulty/priority_pair_validation_conflict/authz_beats_state_on_open_protest_wrong_role
    """
    district, _ = setup_formed_district(
        api, parcels=[{"apn": "Z-1", "owner_name": "OZ", "benefit_units": 100}], name="DAZ")
    validate_error(api.open_protest(district["id"], TREAS), ApiErrorId.ERR_UNAUTHORIZED.value)


def test_open_protest_wrong_role_leaves_district_formed(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP
    403)." PRD §3.1: "When the ratio does not exceed the threshold the district moves to
    FORMED".

    Design: Difficulty/priority_pair_validation_conflict/authz_beats_state_on_open_protest_wrong_role
    """
    district, _ = setup_formed_district(
        api, parcels=[{"apn": "Z-1", "owner_name": "OZ", "benefit_units": 100}], name="DAZ")
    validate_error(api.open_protest(district["id"], TREAS), ApiErrorId.ERR_UNAUTHORIZED.value)
    assert validate_success(api.get_district(district["id"], AUDIT))["status"] == "FORMED"


# --- corner: close-hearing from PROPOSED (protest period never opened) ---

def test_close_hearing_from_proposed_rejected(api):
    """PRD §3.1: "either path requires the district to currently be in PROTEST_PERIOD, and
    attempting to close from any other state fails with ERR_INVALID_DISTRICT_STATE (HTTP 409)."

    Design: Corner/state_machines/close_hearing_from_proposed_returns_invalid_state
    """
    district = create_district(api, name="DS2", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=500_000)
    add_parcel(api, district["id"], apn="S2-1", owner_name="O", benefit_units=100)
    validate_error(api.close_hearing(district["id"], ADMIN),
                   ApiErrorId.ERR_INVALID_DISTRICT_STATE.value)


# --- corner: confirming an already-CONFIRMED roll ---

def test_confirm_already_confirmed_roll_rejected(api):
    """PRD §3.3: "Confirmation requires the roll to currently be `DRAFT`, or
    `ERR_INVALID_ROLL_STATE` (HTTP 409) is returned".

    Design: Corner/state_machines/confirm_already_confirmed_roll_returns_invalid_state
    """
    _, _, roll = setup_confirmed_roll(
        api, parcels=[{"apn": "S1-1", "owner_name": "O", "benefit_units": 100}],
        total_project_cost_cents=500_000, roll_method="BENEFIT_UNITS", name="DS1")
    validate_error(api.confirm_roll(roll["id"], ADMIN), ApiErrorId.ERR_INVALID_ROLL_STATE.value)


# --- corner: ParcelOwner cannot issue a bond ---

def test_parcel_owner_cannot_issue_bond(api):
    """PRD §4: bond issuance (POST /bonds/{id}/issue) is authorized for DistrictAdministrator
    only. PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/parcel_owner_cannot_issue_bond
    """
    district, parcels, _ = setup_confirmed_roll(
        api, parcels=[{"apn": "RB1-1", "owner_name": "O", "benefit_units": 100}],
        total_project_cost_cents=500_000, roll_method="BENEFIT_UNITS", name="DRB1")
    bond = authorize_bond(api, district["id"], term_years=5)
    owner_headers = make_parcel_owner_headers(parcels[0]["id"])
    validate_error(api.issue_bond(bond["id"], owner_headers), ApiErrorId.ERR_UNAUTHORIZED.value)
    from test_helpers import get_bond
    assert get_bond(api, district["id"], bond["id"])["status"] == "AUTHORIZED"


# --- corner: Auditor cannot create a district ---

def test_auditor_cannot_create_district(api):
    """PRD §2.1: "An `Auditor` has read-only oversight of every resource and every disclosure
    report." PRD §4: `POST` `/districts` is authorized for `DistrictAdministrator`.

    Design: Corner/rbac/auditor_cannot_create_district
    """
    payload = create_district_payload(name="NOPE", formation_method="BENEFIT_UNITS",
                                      total_project_cost_cents=500_000)
    validate_error(api.create_district(payload, AUDIT), ApiErrorId.ERR_UNAUTHORIZED.value)


# --- corner: district creation returns system-managed fields ---

def test_district_create_returns_system_fields(api):
    """PRD §3.1: "A newly created district is stamped `PROPOSED` and has an empty
    `total_benefit_units`, an unset `total_apportioned_principal_cents`, and a null
    `formed_at`." PRD §2.4: "a `version`, an integer that begins at 1 and increments by one
    on every mutation of that resource."

    Design: Corner/entities/district_create_returns_201_with_system_fields
    """
    payload = create_district_payload(name="DE1", formation_method="BENEFIT_UNITS",
                                      total_project_cost_cents=500_000)
    data = validate_success(api.create_district(payload, ADMIN), 201)
    assert data["status"] == "PROPOSED"
    assert data["version"] == 1
    assert data.get("total_apportioned_principal_cents") in (None, 0)


# --- corner: fetching a non-existent district ---

def test_get_non_existent_district_returns_not_found(api):
    """PRD §2.5: "If a district id in the path does not exist the request fails with
    ERR_DISTRICT_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/district_get_non_existent_returns_not_found
    """
    validate_error(api.get_district(NON_EXISTENT_UUID, AUDIT),
                   ApiErrorId.ERR_DISTRICT_NOT_FOUND.value)


# --- corner: parcel creation missing required apn ---

def test_parcel_create_missing_apn_rejected(api):
    """PRD §3.1: "Each parcel supplies an `apn` (its assessor parcel number), an `owner_name`,
    and its apportionment weights". PRD §2.10: "generic body/field validation (`ERR_VALIDATION`,
    HTTP 422)".

    Design: Corner/entities/parcel_create_missing_required_apn_rejected
    """
    district = create_district(api, name="DE2", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=500_000)
    validate_error(api.create_parcel(district["id"], {"owner_name": "NoApn", "benefit_units": 10}, ADMIN),
                   ApiErrorId.ERR_VALIDATION.value)


# --- corner: list a district's parcels with pagination envelope ---

def test_list_district_parcels_paginated(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and has_more
    inside meta, where total_count is the total number of records matching the filter before
    pagination and has_more is true when records beyond the current page remain."

    Design: Corner/endpoints/list_district_parcels_paginated
    """
    district = create_district(api, name="DE4", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=500_000)
    add_parcel(api, district["id"], apn="E4-1", owner_name="O1", benefit_units=50)
    add_parcel(api, district["id"], apn="E4-2", owner_name="O2", benefit_units=50)
    data, meta = validate_paginated(api.list_district_parcels(district["id"], AUDIT,
                                                              params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# --- corner: a created parcel is immediately readable ---

def test_parcel_creation_immediately_readable(api):
    """PRD §2.4: "Every resource carries an `id`, which is a server-minted UUID with no type
    prefix". PRD §3.1: "The parcel inherits its `district_id` from the path and is created
    `ACTIVE` with a `parent_parcel_id` of null."

    Design: Corner/consistency_model/parcel_creation_immediately_readable
    """
    district = create_district(api, name="DCM", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=500_000)
    parcel = add_parcel(api, district["id"], apn="CM-1", owner_name="O", benefit_units=77)
    fetched = validate_success(api.get_parcel(parcel["id"], AUDIT))
    assert fetched["benefit_units"] == 77
    assert fetched["status"] == "ACTIVE"
