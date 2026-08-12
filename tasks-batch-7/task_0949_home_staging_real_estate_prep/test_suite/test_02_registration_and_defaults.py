"""Registration of the parties, the configuration rows and the warehouse units."""

from test_helpers import (
    ADMIN,
    COORD,
    WAREHOUSE,
    ApiErrorId,
    assert_bare_uuid_id,
    assert_brokerage,
    assert_client,
    assert_inventory_item,
    assert_listing,
    assert_money,
    assert_package_tier,
    assert_property,
    assert_same_instant,
    assert_vendor,
    make_listing_agent_headers,
    new_brokerage,
    new_listing_agent,
    new_seller,
    set_clock,
    setup_clock_only,
    setup_consultation_two_scope_items,
    setup_listing_ready,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_brokerage_registration_applies_declared_defaults(api):
    """PRD §3.1: "Three optional attributes shape everything the firm's agents can later
    do: `authorization_cap`, which defaults to 4500.00 and may never be set below 0.00 or
    above 15000.00, is the ceiling any listing agent of that firm may authorize on a
    seller's behalf; `tax_exempt`, which defaults to false, means that projects billed to
    this brokerage under a brokerage payer routing carry a `tax_amount` of exactly 0.00;
    and `billing_email`, the invoice delivery address used for brokerage-payer projects."
    PRD §3.1: "A brokerage also carries `open_project_count`, a derived integer that
    starts at 0 and counts the projects naming this brokerage whose `workflow_state` is
    anything other than `CLOSED`."
    PRD §4: "Endpoints that bring a genuinely new resource into existence answer with HTTP
    201; every other successful call answers with HTTP 200."

    Design: Corner/entities/brokerage_creation_returns_201_with_declared_defaults
    """
    setup_clock_only()

    resp = api.create_brokerage({"name": "Cedar Realty", "license_code": "BR-4410"}, ADMIN)

    data = validate_success(resp, 201)
    assert_brokerage(data)
    assert_money(data["authorization_cap"], 4500.00, "brokerage.authorization_cap")
    assert data["tax_exempt"] is False
    assert data["open_project_count"] == 0
    assert data["version"] == 1


def test_listing_agent_effective_cap_is_capped_by_the_brokerage(api):
    """PRD §3.1: "From these the service derives `effective_authorization_cap` at creation,
    and re-derives it whenever the referenced brokerage's own cap changes: for a
    `LISTING_AGENT` it is the smaller of the client's `personal_authorization_cap` and the
    brokerage's `authorization_cap`; for a `SELLER` or a `BROKERAGE_ADMIN` it is 15000.00,
    the hard ceiling the platform will never authorize past."
    PRD §3.1: "Every client is also created with `consent_on_file` false."

    Design: Corner/entities/client_effective_cap_is_min_of_personal_and_brokerage
    """
    setup_clock_only()
    brokerage = new_brokerage(authorization_cap=6000.00)

    resp = api.create_client(
        {"client_type": "LISTING_AGENT", "full_name": "Milo Park", "email": "milo@ex.com",
         "brokerage_id": brokerage["id"], "personal_authorization_cap": 9000.00}, ADMIN)

    data = validate_success(resp, 201)
    assert_client(data)
    assert_money(data["personal_authorization_cap"], 9000.00, "personal_authorization_cap")
    assert_money(data["effective_authorization_cap"], 6000.00, "effective_authorization_cap")
    assert data["consent_on_file"] is False


def test_seller_effective_cap_is_the_platform_hard_ceiling(api):
    """PRD §3.1: "From these the service derives `effective_authorization_cap` at creation,
    and re-derives it whenever the referenced brokerage's own cap changes: for a
    `LISTING_AGENT` it is the smaller of the client's `personal_authorization_cap` and the
    brokerage's `authorization_cap`; for a `SELLER` or a `BROKERAGE_ADMIN` it is 15000.00,
    the hard ceiling the platform will never authorize past."

    Design: Corner/entities/seller_effective_cap_is_the_hard_cap
    """
    setup_clock_only()

    resp = api.create_client(
        {"client_type": "SELLER", "full_name": "Dana Reyes", "email": "dana@ex.com",
         "personal_authorization_cap": 100.00}, ADMIN)

    data = validate_success(resp, 201)
    assert_money(data["effective_authorization_cap"], 15000.00, "effective_authorization_cap")
    assert_money(data["personal_authorization_cap"], 100.00, "personal_authorization_cap")


def test_new_property_starts_in_prep_state_new(api):
    """PRD §3.1: "Each property carries a `prep_state` that starts at `NEW` and walks
    `NEW → CONSULT_BOOKED → SCOPED → IN_PREP → STAGED → DESTAGED → CLOSED`."
    PRD §2.4: "`version` is an integer that begins at 1 when the row is created and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/property_initial_prep_state_is_new
    """
    setup_clock_only()
    seller = new_seller()

    resp = api.create_property(
        {"owner_client_id": seller["id"], "address_line": "18 Larch Ct", "city": "Bend",
         "state_code": "OR", "distance_miles": 22.0, "occupancy": "VACANT",
         "room_count": 4}, COORD)

    data = validate_success(resp, 201)
    assert_property(data)
    assert data["prep_state"] == "NEW"
    assert data["version"] == 1
    assert data["occupancy"] == "VACANT"


def test_new_listing_starts_active_with_no_fallouts(api):
    """PRD §3.1: "A listing's `listing_state` begins at `ACTIVE` and its `fallout_count` at
    0; `under_contract_at` and `closed_at` are both null until the corresponding transition
    sets them."

    Design: Corner/entities/listing_initial_state_active_with_zero_fallouts
    """
    ctx = setup_listing_ready()

    resp = api.create_listing(
        {"property_id": ctx["prop_id"], "listing_agent_client_id": ctx["agent_id"],
         "mls_number": "MLS-9001", "list_price": 749000.00}, COORD)

    data = validate_success(resp, 201)
    assert_listing(data)
    assert data["listing_state"] == "ACTIVE"
    assert data["fallout_count"] == 0
    assert data["under_contract_at"] is None
    assert data["closed_at"] is None


def test_package_tier_row_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "`PackageTier` is the single exception. Package tiers are configuration,
    declared once and immutable thereafter; a `PackageTier` row carries `id` and
    `created_at` only. It has no `updated_at` field, no `version` field, and no update
    endpoint."

    Design: Corner/entities/package_tier_is_immutable_and_carries_no_version
    """
    setup_clock_only()

    resp = api.create_package_tier(
        {"tier_code": "SIGNATURE", "tier_rank": 2, "room_cap": 3,
         "included_accessory_sets": 2, "included_photo_sessions": 2,
         "base_price": 4200.00, "monthly_rent_rate": 950.00}, ADMIN)

    data = validate_success(resp, 201)
    assert_package_tier(data)
    assert data["tier_code"] == "SIGNATURE"
    assert data["room_cap"] == 3
    assert "version" not in data
    assert "updated_at" not in data


def test_vendor_registration_applies_the_four_declared_term_defaults(api):
    """PRD §3.4: "Partner rental houses are registered as vendors with a `name` and four
    commercial terms, each of which has a declared default: `lead_time_days` defaults to 7
    and is the number of days between placing an order and the earliest legal delivery or
    install date; `min_lease_cycles` defaults to 4 and is the vendor's own minimum term in
    30-day cycles, which may legitimately exceed the project's own term; `cancel_cutoff_days`
    defaults to 4 and marks how many days before the earliest delivery date a placed order
    stops being cancelable at the early rate; and `rate_multiplier` defaults to 1.35 and is
    the multiplier applied for vendor-sourced units."
    PRD §3.4: "A vendor's `status` starts at `ACTIVE` and may be moved to `SUSPENDED`; only
    an `ACTIVE` vendor may have an order placed against it."

    Design: Corner/entities/vendor_defaults_applied_when_terms_omitted
    """
    setup_clock_only()

    resp = api.create_vendor({"name": "Metro Rentals"}, WAREHOUSE)

    data = validate_success(resp, 201)
    assert_vendor(data)
    assert data["lead_time_days"] == 7
    assert data["min_lease_cycles"] == 4
    assert data["cancel_cutoff_days"] == 4
    assert float(data["rate_multiplier"]) == 1.35
    assert data["status"] == "ACTIVE"


def test_new_inventory_item_is_server_stamped_available_grade_a(api):
    """PRD §3.4: "Every item is created with `condition_grade` `A`, `status` `AVAILABLE`
    and `times_deployed` 0."
    PRD §2.4: "It is a UUID string with no type prefix of any kind — no `proj_`, no
    `lease-`, nothing but the UUID itself — and clients never supply it."

    Design: Corner/entities/inventory_item_system_fields_are_server_minted
    """
    setup_clock_only()

    resp = api.create_inventory_item(
        {"sku": "SOFA-1", "category": "SOFA", "acquired_at": "2024-01-05T00:00:00Z",
         "replacement_value": 1200.00, "monthly_rate": 240.00}, WAREHOUSE)

    data = validate_success(resp, 201)
    assert_inventory_item(data)
    assert data["status"] == "AVAILABLE"
    assert data["condition_grade"] == "A"
    assert data["times_deployed"] == 0
    assert data["version"] == 1
    assert_bare_uuid_id(data, "inventory item")


def test_inventory_item_with_undeclared_category_is_invalid_enum(api):
    """PRD §2.6: "A field carrying a value outside its declared enumeration yields
    `ERR_INVALID_ENUM` (HTTP 422)."

    Design: Corner/entities/inventory_item_invalid_category_enum_rejected
    """
    setup_clock_only()

    resp = api.create_inventory_item(
        {"sku": "SOFA-2", "category": "HAMMOCK", "acquired_at": "2024-01-05T00:00:00Z",
         "replacement_value": 1200.00, "monthly_rate": 240.00}, WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value, 422)
    listed, meta = validate_paginated(api.list_inventory_items(WAREHOUSE))
    assert meta["total_count"] == 0, "a rejected creation must not leave a row behind"
    assert listed == []


def test_inventory_item_without_sku_is_a_missing_field(api):
    """PRD §2.6: "A field the endpoint declares as required but which is absent yields
    `ERR_MISSING_FIELD` (HTTP 400)."

    Design: Corner/entities/inventory_item_missing_required_sku_rejected
    """
    setup_clock_only()

    resp = api.create_inventory_item(
        {"category": "SOFA", "acquired_at": "2024-01-05T00:00:00Z",
         "replacement_value": 1200.00, "monthly_rate": 240.00}, WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_MISSING_FIELD.value, 400)


def test_property_distance_beyond_five_hundred_miles_is_invalid_request(api):
    """PRD §2.6: "A field of the wrong type, or a numeric value outside its declared range,
    yields `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.7: "Rung 8: every body field matches its declared type and numeric range as
    listed in §2.6; otherwise `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/property_distance_out_of_range_is_invalid_request
    """
    setup_clock_only()
    seller = new_seller()

    resp = api.create_property(
        {"owner_client_id": seller["id"], "address_line": "18 Larch Ct", "city": "Bend",
         "state_code": "OR", "distance_miles": 900.0, "occupancy": "VACANT",
         "room_count": 4}, COORD)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_listing_naming_an_unknown_property_reports_the_parents_not_found_code(api):
    """PRD §2.6: "The same not-found family answers **body** foreign keys. Any `*_id`
    supplied in a request payload must resolve to a stored row of the declared parent type,
    and failure reports that type's own not-found code with HTTP 404."

    Design: Corner/entities/listing_creation_with_unknown_property_returns_property_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    agent = new_listing_agent()

    resp = api.create_listing(
        {"property_id": "22222222-2222-4222-8222-222222222222",
         "listing_agent_client_id": agent["id"], "mls_number": "MLS-9001",
         "list_price": 749000.00}, COORD)

    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value, 404)


def test_scope_items_list_by_consultation_in_sequence_index_order(api):
    """PRD §3.1: "Each scope item carries a `room_label` unique within its consultation, an
    `action`, an `estimated_hours` figure defaulting to 0, a `requires_rental` boolean
    defaulting to false, and an `accessory_set_count` defaulting to 0; the service assigns
    each a `sequence_index`, a 1-based creation order within the consultation that pins
    deterministic processing order."
    PRD §3.1: "each addition recomputes `scoped_room_count`, which counts scope items whose
    `action` is anything other than `ACCESSORY_ONLY`, and `rental_line_count`, which counts
    scope items with `requires_rental` true."
    PRD §2.3: "`total_count` is the number of records matching the filters before
    pagination is applied, and `has_more` is true exactly when `offset` plus the number of
    returned records is smaller than `total_count`."

    Design: Corner/entities/scope_items_are_listed_by_consultation_foreign_key
    """
    ctx = setup_consultation_two_scope_items()

    resp = api.list_scope_items(COORD, params={"consultation_id": ctx["cons_id"]})

    rows, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    by_id = {row["id"]: row for row in rows}
    assert by_id[ctx["si_1"]]["sequence_index"] == 1
    assert by_id[ctx["si_2"]]["sequence_index"] == 2
    consultation = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert consultation["scoped_room_count"] == 2
    assert consultation["rental_line_count"] == 2


def test_holding_a_consultation_freezes_the_pipeline_from_property_occupancy(api):
    """PRD §3.1: "The `SCHEDULED → HELD` transition requires the logical clock to have
    reached `scheduled_at`, stamps `held_at` with the logical clock, and copies the
    property's `occupancy` into the consultation's `pipeline` — `OCCUPIED` becoming
    `OCCUPIED_PREP` and `VACANT` becoming `VACANT_STAGING`."
    PRD §3.1: "Booking a consultation is what moves the property `NEW → CONSULT_BOOKED`,
    and it is refused unless the property is in `NEW` and no consultation on that property
    currently sits in `SCHEDULED`, `HELD`, `SCOPE_DRAFTED` or `SCOPE_SUBMITTED`."

    Design: Corner/entities/consultation_pipeline_is_frozen_at_hold_from_property_occupancy
    """
    ctx = setup_listing_ready()
    cons = validate_success(api.create_consultation(
        {"property_id": ctx["prop_id"], "requested_by_client_id": ctx["agent_id"],
         "scheduled_at": "2026-06-01T00:00:00Z"}, COORD), 201)

    resp = api.hold_consultation(cons["id"], COORD)

    data = validate_success(resp)
    assert data["state"] == "HELD"
    assert data["pipeline"] == "VACANT_STAGING"
    assert_same_instant(data["held_at"], "2026-06-01T00:00:00Z", "consultation.held_at")
    prop = validate_success(api.get_property(ctx["prop_id"], COORD))
    assert prop["prep_state"] == "CONSULT_BOOKED"


def test_project_room_count_excludes_accessory_only_rooms(api):
    """PRD §3.2: "The project's `room_count` is the count of scope items on the
    consultation whose `action` is not `ACCESSORY_ONLY` — accessory-only rooms are excluded
    from the room count while still contributing their accessory sets."
    PRD §3.2: "The project's `accessory_set_count` is the sum of `accessory_set_count` over
    every scope item on that consultation."
    PRD §3.2: "The new row starts in `workflow_state` `DRAFT` and `payment_state`
    `UNBILLED`, with `window_extension_count` 0, `restage_count` 0, `photo_sessions_consumed`
    0, `reshoot_credits_remaining` 1, `destage_eligible` false and `fiscal_hold` false."

    Design: Corner/entities/project_room_count_excludes_accessory_only_rooms
    """
    ctx = setup_consultation_two_scope_items()
    validate_success(api.add_scope_item(
        ctx["cons_id"], {"room_label": "Entry", "action": "ACCESSORY_ONLY",
                         "requires_rental": False, "accessory_set_count": 0}, COORD), 201)
    validate_success(api.submit_scope(
        ctx["cons_id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    validate_success(api.approve_scope(
        ctx["cons_id"], make_listing_agent_headers(ctx["agent_id"])))

    resp = api.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_sig"],
         "payer_client_id": ctx["seller_id"], "payer_type": "SELLER"}, COORD)

    project = validate_success(resp, 201)
    consultation = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert consultation["scoped_room_count"] == 2
    assert project["room_count"] == 2
    assert project["accessory_set_count"] == 3
    assert project["pipeline"] == "VACANT_STAGING"
    assert project["workflow_state"] == "DRAFT"
    assert project["payment_state"] == "UNBILLED"
    assert project["reshoot_credits_remaining"] == 1
