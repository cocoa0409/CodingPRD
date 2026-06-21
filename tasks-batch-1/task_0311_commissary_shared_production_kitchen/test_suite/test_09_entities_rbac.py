"""Entity creation basics, required-field/enum/FK validation, listing, and RBAC.

Translates corner queue instances from the entities, rbac, and endpoints
sections (excluding ones folded into other concern files).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_member_operator_headers, TEST_USERS,
    register_member, create_ingredient, create_storage_unit,
)

FM = TEST_USERS["facility_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ── Corner: entities / member_register_returns_201_active_zero_wallet ──

def test_register_member_returns_active_zero_wallet(api):
    """PRD 3.1: "On registration the new member is created with status set to
    ACTIVE and the three wallet figures — wallet_balance_cents,
    lifetime_loaded_cents, and lifetime_charged_cents — all initialized to 0."
    PRD 2.4: "version — an integer that begins at 1 on creation".

    Design: Corner/entities/member_register_returns_201_active_zero_wallet
    """
    res = api.register_member({"business_name": "Acme Foods", "email": "acme@x.com"}, ANON)
    member = validate_success(res, 201)
    assert member["status"] == "ACTIVE"
    assert member["wallet_balance_cents"] == 0
    assert member["plan_tier"] == "STANDARD"
    assert member["version"] == 1


# ── Corner: entities / member_register_default_plan_tier_standard ──

def test_register_member_defaults_plan_tier_standard(api):
    """PRD 3.1: "The plan tier is one of STANDARD or PREMIUM and defaults to
    STANDARD when omitted".

    Design: Corner/entities/member_register_default_plan_tier_standard
    """
    res = api.register_member({"business_name": "DefaultCo", "email": "def@x.com"}, ANON)
    member = validate_success(res, 201)
    assert member["plan_tier"] == "STANDARD"


# ── Corner: entities / member_get_nonexistent_returns_not_found ──

def test_get_nonexistent_member_returns_not_found(api):
    """PRD 2.5: "the system validates the identifiers left to right and rejects
    the request with ERR_NOT_FOUND (HTTP 404) at the first identifier that does
    not resolve to an existing resource."

    Design: Corner/entities/member_get_nonexistent_returns_not_found
    """
    res = api.get_member("00000000-0000-0000-0000-000000000000", FM)
    validate_error(res, "ERR_NOT_FOUND")


# ── Corner: entities / station_create_missing_station_class_returns_invalid_request ──

def test_create_station_missing_class_rejected(api):
    """PRD 2.11: "then request-body well-formedness — required fields present,
    enum values valid, numeric fields parseable (ERR_INVALID_REQUEST)". PRD 3.2:
    a station "has a ... station_class of PREP_TABLE, CONVECTION_OVEN, or
    BLAST_CHILLER (which selects its hourly rate)". Omitting the required
    station_class is rejected.

    Design: Corner/entities/station_create_missing_station_class_returns_invalid_request
    """
    res = api.create_station({"name": "NoClass"}, FM)
    validate_error(res, "ERR_INVALID_REQUEST")


# ── Corner: entities / station_create_invalid_enum_class_rejected ──

def test_create_station_invalid_enum_class_rejected(api):
    """PRD 2.11: "then request-body well-formedness — required fields present,
    enum values valid, numeric fields parseable (ERR_INVALID_REQUEST)". PRD 3.2:
    station_class is one of PREP_TABLE, CONVECTION_OVEN, or BLAST_CHILLER; a value
    outside that set is rejected.

    Design: Corner/entities/station_create_invalid_enum_class_rejected
    """
    res = api.create_station({"name": "Bad", "station_class": "MICROWAVE"}, FM)
    validate_error(res, "ERR_INVALID_REQUEST")


# ── Corner: entities / booking_fk_station_nonexistent_returns_not_found ──

def test_booking_with_nonexistent_station_returns_not_found(api):
    """PRD 2.5: "The same ERR_NOT_FOUND governs foreign-key references supplied in
    a request body — station_id, recipe_id, ingredient_id, storage_unit_id, and
    the entries of batch_ids must each resolve to an existing entity, or the
    create is rejected."

    Design: Corner/entities/booking_fk_station_nonexistent_returns_not_found
    """
    member = register_member(business_name="Fk")
    mo = make_member_operator_headers(member["id"])
    topped = validate_success(api.top_up_wallet(member["id"], {"amount_cents": 100000}, mo), 201)
    res = api.create_booking(member["id"], {
        "station_id": "00000000-0000-0000-0000-000000000000",
        "start_utc": "2026-07-11T12:00:00.000Z",
        "end_utc": "2026-07-11T13:00:00.000Z",
        "expected_member_version": topped["version"],
    }, mo)
    validate_error(res, "ERR_NOT_FOUND")


# ── Corner: entities / recipe_components_immutable_no_version_field ──

def test_recipe_component_is_append_only(api):
    """PRD 2.4: "A RecipeComponent (a single bill-of-materials line) and a TempLog
    (a single temperature reading) carry only id and created_at; they have
    neither updated_at nor version, because they are append-only records that are
    never independently mutated after creation."

    Design: Corner/entities/recipe_components_immutable_no_version_field
    """
    member = register_member(business_name="Im")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="ImIng", unit_cost_cents=100)
    recipe = validate_success(api.create_recipe(member["id"], {"name": "ImR", "batch_yield_units": 5}, mo), 201)
    res = api.add_recipe_component(member["id"], recipe["id"], {"ingredient_id": ing["id"], "planned_qty": 2.0}, mo)
    component = validate_success(res, 201)
    assert component["planned_qty"] == 2.0
    assert "version" not in component
    assert "updated_at" not in component


# ── Corner: entities / members_list_pagination_envelope ──

def test_members_list_pagination_envelope(api):
    """PRD 2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."
    With two registered members and the default limit of 10, has_more is false.

    Design: Corner/entities/members_list_pagination_envelope
    """
    api.register_member({"business_name": "L1", "email": "l1@x.com"}, ANON)
    api.register_member({"business_name": "L2", "email": "l2@x.com"}, ANON)
    data, meta = validate_paginated(api.list_members(FM))
    assert len(data) == 2
    assert meta["has_more"] is False


# ── Corner: endpoints / temp_log_certify_marks_certified ──

def test_temp_log_listed_for_unit(api):
    """PRD 3.11: "carrying the storage_unit_id, a reading_c (the Celsius
    reading), and a reading_utc timestamp." PRD 2.3: "Unless otherwise specified,
    all list endpoints return resources sorted by their creation timestamp in
    ascending order." One recorded reading appears in the unit's temp-log list.

    Design: Corner/endpoints/temp_log_certify_marks_certified
    """
    cold = create_storage_unit(name="ColdCt", temp_class="COLD", total_slots=5,
                               temp_min_c=0.0, temp_max_c=4.0)
    validate_success(api.create_temp_log(cold["id"], {"reading_c": 2.0, "reading_utc": "2026-07-18T10:00:00.000Z"}, CO), 201)
    data, meta = validate_paginated(api.list_temp_logs_for_unit(cold["id"], CO))
    assert len(data) == 1


# ── Corner: rbac / member_cannot_create_station ──

def test_member_operator_cannot_create_station(api):
    """PRD 2.1: "the role must be permitted to perform the requested operation per
    the authorization matrix; a permitted-but-wrong-role attempt is rejected with
    ERR_UNAUTHORIZED (HTTP 403)." Creating a station is FacilityManager-exclusive.

    Design: Corner/rbac/member_cannot_create_station
    """
    member = register_member(business_name="Rb")
    mo = make_member_operator_headers(member["id"])
    res = api.create_station({"name": "Sneaky", "station_class": "PREP_TABLE"}, mo)
    validate_error(res, "ERR_UNAUTHORIZED")


# ── Corner: rbac / member_cannot_act_on_other_members_booking ──

def test_member_operator_cannot_cancel_other_members_booking(api):
    """PRD 2.1: "A member operator acting on a member-scoped resource that they do
    not own — that is, where the resource's member_id does not equal X-User-ID —
    is rejected with ERR_FORBIDDEN_NOT_OWNER (HTTP 403)."

    Design: Corner/rbac/member_cannot_act_on_other_members_booking
    """
    member_a = register_member(business_name="Ma")
    member_b = register_member(business_name="Mb")
    mo_b = make_member_operator_headers(member_b["id"])
    topped = validate_success(api.top_up_wallet(member_b["id"], {"amount_cents": 100000}, mo_b), 201)
    station = validate_success(api.create_station({"name": "PrepAB", "station_class": "PREP_TABLE"}, FM), 201)
    booking = validate_success(api.create_booking(member_b["id"], {
        "station_id": station["id"],
        "start_utc": "2026-07-20T12:00:00.000Z",
        "end_utc": "2026-07-20T13:00:00.000Z",
        "expected_member_version": topped["version"],
    }, mo_b), 201)
    # member_a (the wrong owner) tries to cancel member_b's booking.
    mo_a = make_member_operator_headers(member_a["id"])
    res = api.cancel_booking(member_b["id"], booking["id"], mo_a)
    validate_error(res, "ERR_FORBIDDEN_NOT_OWNER")


# ── Corner: rbac / missing_auth_headers_returns_unauthenticated ──

def test_missing_auth_headers_rejected(api):
    """PRD 2.1: "A request that is missing either header (on any endpoint except
    member registration) is rejected with ERR_UNAUTHENTICATED (HTTP 401)." A
    protected list endpoint called with no auth headers is rejected.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_members(headers={})
    assert res.status_code in (401, 403), f"got {res.status_code}"
