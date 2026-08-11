"""Homeowners, homes and the catalogue rows that hang off them."""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUDITOR,
    DISPATCHER,
    PLATFORM_ADMIN,
    ApiErrorId,
    assert_key_copy_conservation,
    assert_owner,
    assert_property,
    create_away_period_payload,
    create_checklist_template_payload,
    create_key_asset_payload,
    create_owner_payload,
    create_property_payload,
    create_service_plan_payload,
    create_vendor_payload,
    is_valid_uuid,
    make_owner_headers,
    new_owner,
    new_property,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_owner_registration_applies_every_declared_default(api):
    """PRD 3.1: "`snowbird_flag`, false unless supplied, declares that this owner
    migrates seasonally and unlocks cadence-driven absence scheduling."
    PRD 3.1: "Registration always stamps `status` to `ACTIVE` — the enum's other
    member is `INACTIVE` — and `lifetime_credit_balance_cents` to zero."
    PRD 2.4: "`version`, an integer that starts at 1 when the row is created and
    increases as the row is mutated."

    Design: Corner/entities/owner_create_returns_201_with_defaults_applied
    """
    set_clock("2026-06-01T00:00:00Z")
    payload = create_owner_payload(full_name="Ann Base", primary_residence_state="MN")
    response = api.create_owner(payload, PLATFORM_ADMIN)
    data = validate_success(response, 201)
    assert_owner(data)
    assert data["status"] == "ACTIVE"
    assert data["snowbird_flag"] is False
    assert data["notification_preference"] == "EMAIL"
    assert data["approval_ceiling_override_cents"] is None
    assert data["lifetime_credit_balance_cents"] == 0
    assert data["version"] == 1


def test_owner_read_back_echoes_the_stored_row_with_a_bare_uuid(api):
    """PRD 2.4: "Every persisted resource carries a server-minted `id` that is a UUID
    string with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three
    fractional digits."
    PRD 2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/entities/owner_retrieval_returns_stored_row
    """
    set_clock("2026-06-01T00:00:00Z")
    created = new_owner(full_name="Ben Read", email="ben.read@example.com",
                        primary_residence_state="WI")
    response = api.get_owner(created["id"], AUDITOR)
    data = validate_success(response, 200)
    assert data["full_name"] == "Ben Read"
    assert data["email"] == "ben.read@example.com"
    assert data["primary_residence_state"] == "WI"
    assert data["id"] == created["id"]
    assert is_valid_uuid(data["id"]), "the id must be a bare UUID with no type prefix"
    assert response.json()["response_type"] == "object"


def test_property_listing_reports_total_count_and_has_more(api):
    """PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the size of the filtered set before the page
    window is applied and `has_more` is true exactly when more rows remain beyond the
    window."

    Design: Corner/entities/property_listing_paginates_with_total_count_and_has_more
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Cal List", primary_residence_state="IL")
    for label, miles in (("P1", 5.0), ("P2", 15.0), ("P3", 30.0)):
        new_property(owner["id"], label=label, travel_distance_miles=miles)

    response = api.list_properties(headers=AUDITOR,
                                   params={"owner_id": owner["id"], "limit": 2, "offset": 0})
    rows, meta = validate_paginated(response)
    assert len(rows) == 2, f"limit 2 must return 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert response.json()["response_type"] == "array"

    tail = api.list_properties(headers=AUDITOR,
                               params={"owner_id": owner["id"], "limit": 2, "offset": 2})
    tail_rows, tail_meta = validate_paginated(tail)
    assert len(tail_rows) == 1
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False


def test_property_read_with_unknown_id_is_a_404(api):
    """PRD 2.8: "The first path id resolves to an existing row of its declared entity.
    This applies to every endpoint that has a path parameter. Otherwise
    `ERR_RESOURCE_NOT_FOUND`, HTTP 404."

    Design: Corner/entities/property_get_with_unknown_uuid_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    response = api.get_property("00000000-0000-4000-8000-0000000000ff", AUDITOR)
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_service_plan_without_included_visit_units_is_rejected(api):
    """PRD 2.8: "Every field the endpoint declares as required is present in the body,
    on every endpoint. Otherwise `ERR_MISSING_REQUIRED_FIELD`, HTTP 400."
    PRD 3.2: "A service plan is published with a `tier` of `BASIC`, `STANDARD` or
    `PREMIUM`, a strictly positive `monthly_fee_cents`, an `included_visit_units` count
    of zero or more, and a non-empty `covered_visit_types` array."

    Design: Corner/entities/service_plan_create_missing_required_field_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    payload = {"tier": "BASIC", "monthly_fee_cents": 9986, "covered_visit_types": ["ROUTINE_WATCH"]}
    response = api.create_service_plan(payload, PLATFORM_ADMIN)
    validate_error(response, ApiErrorId.ERR_MISSING_REQUIRED_FIELD.value)

    listed, meta = validate_paginated(api.list_service_plans(headers=AUDITOR))
    assert meta["total_count"] == 0, "no plan row may be created by a rejected request"


def test_property_registration_applies_the_freeze_setpoint_and_axis_defaults(api):
    """PRD 3.1: "`freeze_setpoint_f`, the minimum interior temperature in Fahrenheit the
    home must hold, defaulting to 55 and constrained to the inclusive range from 40 to
    80; and `rental_program_enrolled`, false unless supplied, marking the home as
    participating in short-term rental turnovers."
    PRD 3.1: "`seasonal_state` starts at `OPEN` and runs as a closed cycle through
    `CLOSING`, `WINTERIZED` and `OPENING` back to `OPEN`."

    Design: Corner/entities/property_freeze_setpoint_default_applied_when_omitted
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Dee Default", primary_residence_state="IA")
    response = api.create_property(
        create_property_payload(owner["id"], label="Default House", address_line="55 Set Pt",
                                travel_distance_miles=5.0),
        PLATFORM_ADMIN,
    )
    data = validate_success(response, 201)
    assert_property(data)
    assert data["freeze_setpoint_f"] == 55
    assert data["rental_program_enrolled"] is False
    assert data["seasonal_state"] == "OPEN"
    assert data["occupancy_state"] == "VACANT"
    assert data["storm_hold_flag"] is False


def test_travel_zone_is_derived_from_distance_at_every_declared_edge(api):
    """PRD 3.1: "A distance of at most 10 miles is `Z1`; otherwise a distance of at most
    25 miles is `Z2`; otherwise a distance of at most 60 miles is `Z3`; otherwise the
    zone is `OUT_OF_AREA`."
    PRD 3.1: "Ten miles exactly is `Z1` and 10.1 is `Z2`; 25.0 is `Z2`; 60.0 is `Z3` and
    60.1 is `OUT_OF_AREA`."

    Design: Corner/entities/property_travel_zone_is_computed_and_ignores_client_value
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Eve Zone", primary_residence_state="MO")
    cases = [(10.0, "Z1"), (10.1, "Z2"), (25.0, "Z2"), (60.0, "Z3"), (60.1, "OUT_OF_AREA")]
    for miles, expected_zone in cases:
        created = new_property(owner["id"], label=f"{miles} mi",
                               address_line=f"{miles} Mile Rd", travel_distance_miles=miles)
        assert created["travel_zone"] == expected_zone, (
            f"{miles} miles must map to {expected_zone}, got {created['travel_zone']}"
        )


def test_vendor_trade_outside_the_declared_enum_is_rejected(api):
    """PRD 3.6: "A contractor is onboarded with a `legal_name`, a `trade` of `PLUMBING`,
    `HVAC`, `ELECTRICAL`, `GENERAL`, `SECURITY`, `LOCKSMITH` or `LANDSCAPE`, a
    `coi_expires_at` certificate-of-insurance expiry instant, a `license_expires_at`
    trade-licence expiry instant, a strictly positive `hourly_rate_cents`, and a
    `rating` on a zero-to-five scale."
    PRD 2.8: "Every supplied enum-typed field holds a declared member of that enum."

    Design: Corner/entities/vendor_create_invalid_enum_trade_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    response = api.create_vendor(
        create_vendor_payload(legal_name="Bad Trade Co", trade="PLUMBER"), DISPATCHER
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)
    _, meta = validate_paginated(api.list_vendors(headers=AUDITOR))
    assert meta["total_count"] == 0


def test_vendor_rating_above_five_is_out_of_range(api):
    """PRD 2.8: "Every numeric field lies inside its declared range, on every endpoint:
    `travel_distance_miles` at least 0; `freeze_setpoint_f` at least 40 and at most 80;
    `rating` at least 0 and at most 5; `cadence_days` at least 3 and at most 30;
    `copies_total` at least 1; `copies_issued` at least 1; `hourly_rate_cents` strictly
    greater than 0; `monthly_fee_cents` strictly greater than 0; `included_visit_units`
    at least 0; `estimated_labour_hours` at least 0; `estimated_parts_cents` at least 0.
    Otherwise `ERR_VALUE_OUT_OF_RANGE`, HTTP 400."

    Design: Corner/entities/vendor_create_rating_out_of_range_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    response = api.create_vendor(
        create_vendor_payload(legal_name="Over Rated Co", trade="PLUMBING", rating=9.0), DISPATCHER
    )
    validate_error(response, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)


def test_travel_distance_of_the_wrong_json_type_is_rejected(api):
    """PRD 2.8: "Every supplied field carries the declared JSON type, on every endpoint.
    Otherwise `ERR_INVALID_FIELD_TYPE`, HTTP 400."

    Design: Corner/entities/property_create_wrong_type_for_travel_distance_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Gil Type", primary_residence_state="NE")
    response = api.create_property(
        create_property_payload(owner["id"], label="Type House", address_line="1 Type St",
                                travel_distance_miles="eighteen"),
        PLATFORM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_FIELD_TYPE.value)


def test_property_registration_resolves_its_owner_foreign_key(api):
    """PRD 2.8: "A body field `owner_id` resolves to an existing owner. This applies to
    property registration and away-period declaration. Otherwise `ERR_OWNER_NOT_FOUND`,
    HTTP 404."

    Design: Corner/entities/property_requires_existing_parent_owner_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    response = api.create_property(
        create_property_payload("00000000-0000-4000-8000-0000000000aa", label="Orphan House",
                                address_line="1 Orphan St", travel_distance_miles=5.0),
        PLATFORM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_OWNER_NOT_FOUND.value)


def test_template_required_item_count_is_the_length_of_item_codes(api):
    """PRD 3.3: "`required_item_count` is not supplied; it is set to the length of
    `item_codes` at publication."
    PRD 3.3: "`default_finding_category`, defaulting to `OTHER`, is the `category`
    stamped on every finding auto-created from a failed critical item of this template"

    Design: Corner/entities/checklist_template_required_item_count_is_derived_from_item_codes
    """
    set_clock("2026-06-01T00:00:00Z")
    response = api.create_checklist_template(
        create_checklist_template_payload(
            "ROUTINE_WATCH", version_label="2026.2",
            item_codes=["A", "B", "C", "D", "E"], critical_item_codes=["C"],
        ),
        PLATFORM_ADMIN,
    )
    data = validate_success(response, 201)
    assert data["required_item_count"] == 5
    assert data["default_finding_category"] == "OTHER"
    assert data["status"] == "ACTIVE"


def test_away_period_projection_is_computed_at_declaration(api):
    """PRD 3.3: "At declaration, the away-day count is the whole days between `start_at`
    and `end_at`, taken as the floor of the elapsed seconds divided by 86400, and the
    projection is the floor of that away-day count divided by `cadence_days`."
    PRD 3.3: "its `derived_status` is read from the logical clock on every read, and is
    `PLANNED` while the clock is strictly before `start_at`"

    Design: Corner/entities/away_period_projected_visit_count_is_computed_at_create
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Ike Cadence", primary_residence_state="SD")
    prop = new_property(owner["id"], label="Cadence House", address_line="14 Cycle Ct",
                        travel_distance_miles=5.0)
    response = api.create_away_period(
        create_away_period_payload(prop["id"], owner["id"], start_at="2026-07-01T00:00:00Z",
                                   end_at="2026-09-29T00:00:00Z", cadence_days=14),
        make_owner_headers(owner["id"]),
    )
    data = validate_success(response, 201)
    assert data["projected_visit_count"] == 6, "90 away days at a cadence of 14 projects 6 visits"
    assert data["scheduled_visit_count"] == 0
    assert data["derived_status"] == "PLANNED"
    assert data["cadence_revision_count"] == 0


def test_key_asset_copy_ledger_starts_wholly_on_hand(api):
    """PRD 3.7: "Registration sets `copies_on_hand` equal to `copies_total` and
    `code_rotation_count` to zero."
    PRD 2.11: "For every key asset, `copies_total` equals `copies_on_hand` plus
    `copies_issued_outstanding` plus `copies_lost`."

    Design: Corner/entities/key_asset_copy_ledger_initialised_from_copies_total
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Jan Key", primary_residence_state="MT")
    prop = new_property(owner["id"], label="Key House", address_line="4 Copy Ct",
                        travel_distance_miles=5.0)
    response = api.create_property_key_asset(
        prop["id"], create_key_asset_payload("PHYSICAL", "Front door", 4), DISPATCHER
    )
    data = validate_success(response, 201)
    assert data["copies_on_hand"] == 4
    assert data["copies_issued_outstanding"] == 0
    assert data["copies_lost"] == 0
    assert data["code_rotation_count"] == 0
    assert data["active_grant_count"] == 0
    assert data["current_code"] is None, "current_code is null for physical keys"
    assert data["rekey_pending_flag"] is False
    assert_key_copy_conservation(data)


def test_duplicate_owner_email_is_a_uniqueness_violation(api):
    """PRD 3.1: "An owner's `email` must be unique across all owners and must contain an
    at-sign; a duplicate is rejected with `ERR_UNIQUENESS_VIOLATION`."

    Design: Corner/entities/owner_email_uniqueness_violation_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    new_owner(full_name="First Dup", email="dup@example.com", primary_residence_state="OR")
    response = api.create_owner(
        create_owner_payload(full_name="Second Dup", email="dup@example.com",
                             primary_residence_state="WA"),
        PLATFORM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_UNIQUENESS_VIOLATION.value)
    _, meta = validate_paginated(api.list_owners(headers=AUDITOR))
    assert meta["total_count"] == 1, "the duplicate must not create a second owner row"
