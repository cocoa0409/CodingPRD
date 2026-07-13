"""Registry and vessel CRUD, plus base authentication/authorization gates.

Translates SCAFFOLD_CORNER_DESIGN.yaml queue-B instances from the `entities`
and `validations` (auth) sections.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_owner_headers,
    new_jurisdiction, new_owner, new_vessel, register_vessel,
    setup_registered_vessel, new_inspection, raise_deficiency,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_vessel_returns_201_with_system_fields(api):
    """PRD §3.2: "A newly created vessel starts with `registration_status` `DRAFT`,
    `service_status` `NOT_IN_SERVICE`, a null `jurisdiction_number`, a null
    `current_certificate_id`, zero for both `open_deficiency_count` and
    `open_critical_deficiency_count`, and null risk scores."

    Design: Corner/entities/create_vessel_returns_201_with_fields
    """
    jur = new_jurisdiction()
    owner = new_owner()
    resp = api.create_vessel(
        {
            "owner_id": owner["id"], "jurisdiction_id": jur["id"], "manufacturer": "M",
            "national_board_number": "NBV-1", "vessel_class": "POWER_BOILER",
            "mawp_psig": 120, "installed_at": "2020-01-01T00:00:00Z",
        },
        make_owner_headers(owner["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["vessel_class"] == "POWER_BOILER"
    assert data["registration_status"] == "DRAFT"
    assert data["service_status"] == "NOT_IN_SERVICE"
    assert data["jurisdiction_number"] is None


def test_get_nonexistent_vessel_returns_not_found(api):
    """PRD §2.4: "any reference to a non-existent resource is rejected with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_vessel_nonexistent_returns_not_found
    """
    new_jurisdiction()
    resp = api.get_vessel(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_vessel_missing_vessel_class_returns_invalid_request(api):
    """PRD §2.7: "Request validity — body field types, enum membership,
    required-field presence, and cross-field ranges, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_vessel_missing_vessel_class_returns_invalid_request
    """
    jur = new_jurisdiction()
    owner = new_owner()
    resp = api.create_vessel(
        {
            "owner_id": owner["id"], "jurisdiction_id": jur["id"], "manufacturer": "M",
            "national_board_number": "NBV-1", "mawp_psig": 120,
            "installed_at": "2020-01-01T00:00:00Z",
        },
        make_owner_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_vessel_invalid_enum_returns_invalid_request(api):
    """PRD §2.7: "Request validity — body field types, enum membership,
    required-field presence, and cross-field ranges, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_vessel_invalid_enum_returns_invalid_request
    """
    jur = new_jurisdiction()
    owner = new_owner()
    resp = api.create_vessel(
        {
            "owner_id": owner["id"], "jurisdiction_id": jur["id"], "manufacturer": "M",
            "national_board_number": "NBV-1", "vessel_class": "STEAM_DRUM",
            "mawp_psig": 120, "installed_at": "2020-01-01T00:00:00Z",
        },
        make_owner_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_jurisdiction_default_admin_fee_pct_applied(api):
    """PRD §3.1: "an optional `admin_fee_pct` (the administrative surcharge already
    discussed, defaulting to 0.075 and constrained to the range 0 through 1 inclusive)".

    Design: Corner/entities/jurisdiction_default_admin_fee_pct_applied
    """
    jur = new_jurisdiction()
    data = validate_success(api.get_jurisdiction(jur["id"], ADMIN))
    assert data["admin_fee_pct"] == 0.075


def test_duplicate_national_board_number_returns_duplicate(api):
    """PRD §3.2: "A duplicate `national_board_number` is rejected with
    `ERR_DUPLICATE_UNIQUE_FIELD`."

    Design: Corner/entities/duplicate_national_board_number_returns_duplicate
    """
    jur = new_jurisdiction()
    owner = new_owner()
    new_vessel(owner["id"], jur["id"], national_board_number="NBV-1")
    resp = api.create_vessel(
        {
            "owner_id": owner["id"], "jurisdiction_id": jur["id"], "manufacturer": "M2",
            "national_board_number": "NBV-1", "vessel_class": "HEATING_BOILER",
            "mawp_psig": 30, "installed_at": "2021-01-01T00:00:00Z",
        },
        make_owner_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIQUE_FIELD.value)


def test_list_vessels_pagination_envelope(api):
    """PRD §2.3: "`total_count` is the total number of records matching the query
    before pagination is applied, and `has_more` is true exactly when records remain
    beyond the current page."

    Design: Corner/entities/list_vessels_pagination_envelope
    """
    jur = new_jurisdiction()
    owner = new_owner()
    new_vessel(owner["id"], jur["id"], national_board_number="NBV-1", vessel_class="POWER_BOILER", mawp_psig=120)
    new_vessel(owner["id"], jur["id"], national_board_number="NBV-2", vessel_class="PRESSURE_VESSEL", mawp_psig=300)
    data, meta = validate_paginated(api.list_vessels(ADMIN))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_deficiency_reverse_lookup_by_vessel(api):
    """PRD §3.5: "Deficiencies may be listed — filterable by `inspection_id`,
    `vessel_id`, `repair_order_id`, `status`, or `severity` — or fetched individually."

    Design: Corner/entities/fk_deficiency_by_vessel_reverse_lookup
    """
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="INTERNAL")
    d1 = raise_deficiency(insp1["id"], ctx["insp_a_id"], severity="NON_CRITICAL", description="pitting")
    data, meta = validate_paginated(api.list_deficiencies(ADMIN, params={"vessel_id": ctx["vessel_id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == d1["id"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name one
    of the three roles defined below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    new_jurisdiction()
    resp = api.list_vessels(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_wrong_role_create_jurisdiction_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to invoke the requested operation (per the authorization matrix summarized in §4),
    the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/wrong_role_create_jurisdiction_returns_unauthorized
    """
    owner = new_owner()
    resp = api.create_jurisdiction({"code": "TX", "name": "Texas"}, make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
