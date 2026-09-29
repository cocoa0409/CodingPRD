"""Entity shape, defaults, computed fields and parent resolution."""

from test_helpers import (
    ADMIN,
    DEFAULT_CLOCK_UTC,
    NON_EXISTENT_UUID,
    OFFICER,
    assert_amenity_inspection,
    assert_append_only_columns,
    assert_audit_columns,
    assert_invoice_components,
    assert_membership_tier,
    assert_ordered_by_created_at,
    assert_pool_split,
    assert_reservation_state,
    create_classic_tier,
    create_member,
    create_open_park,
    create_park,
    create_president_tier,
    is_valid_uuid,
    list_invoices,
    make_amenity_inspection_payload,
    make_capital_project_payload,
    make_classic_tier_payload,
    make_member_payload,
    make_membership_payload,
    make_park_manager_headers,
    make_park_payload,
    make_reservation_payload,
    parse_instant,
    read_membership,
    read_park,
    reset_clock,
    sell_membership,
    sell_membership_to_new_member,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_tier_creation_echoes_every_declared_field(api):
    """A created tier returns all fifteen inputs plus the four common fields.

    PRD §2.4: "Alongside `id`, most resources carry three audit columns:
    `created_at`, the ISO 8601 UTC timestamp with three fractional digits at
    which the row was created; `updated_at`, the same format, refreshed on every
    mutation of the row; and `version`, an integer that starts at 1 on creation
    and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/membership_tier_creation_returns_every_declared_field
    """
    reset_clock(api)
    payload = make_classic_tier_payload()

    tier = validate_success(api.create_membership_tier(payload, ADMIN), 201)

    assert_membership_tier(tier)
    for field, sent in payload.items():
        assert tier[field] == sent, f"the response must echo the submitted {field}"
    assert_audit_columns(tier, "MembershipTier")
    assert tier["version"] == 1, "a freshly created row is at version 1"
    assert tier["updated_at"] == tier["created_at"], "nothing has mutated the row yet"
    assert parse_instant(tier["created_at"]) == parse_instant(DEFAULT_CLOCK_UTC), (
        "created_at is stamped from the logical clock"
    )


def test_park_read_returns_the_pool_split_and_creation_defaults(api):
    """Reading a park back returns exactly what creation stored, split included.

    PRD §3.2: "A new park is not open for business. Its `park_status` starts at
    `SEASONAL_CLOSED`, its `amenity_compliance_status` at `COMPLIANT`, its
    `rating_score` at 0.00, its `forced_cancellation_count` at 0, its
    `funded_capital_cents_ytd` at 0, and its `last_inspection_at` null because no
    inspection has yet been filed."

    Design: Corner/entities/park_retrieval_returns_the_stored_pool_split_and_creation_defaults
    """
    reset_clock(api)
    created = create_park(
        api,
        name="Elk Meadow RV Resort",
        park_class="CLASS_B",
        total_sites=25,
        member_allocation_pct=60,
    )

    park = validate_success(api.get_park(created["id"], ADMIN), 200)

    assert park["id"] == created["id"]
    # floor(25 * 60 / 100) is 15 member pads with the remaining 10 transient.
    assert_pool_split(park, member_sites=15, transient_sites=10)
    assert park["park_status"] == "SEASONAL_CLOSED"
    assert park["amenity_compliance_status"] == "COMPLIANT"
    assert park["rating_score"] == 0.00
    assert park["forced_cancellation_count"] == 0
    assert park["funded_capital_cents_ytd"] == 0
    assert park["last_inspection_at"] is None
    assert park["network_type"] == "CLUB_OWNED", "no affiliate_agreement_id was supplied"


def test_membership_listing_pages_with_total_count_and_has_more(api):
    """total_count counts every matching row, not the rows on the page.

    PRD §2.3: "Alongside the echoed `limit` and `offset`, every list response's
    `meta` object carries `total_count` — the number of rows matching the filters
    before the page window is applied — and `has_more`, a boolean that is true
    exactly when rows remain beyond the current page."

    Design: Corner/entities/membership_listing_paginates_with_total_count_and_has_more
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    sold = []
    for name, email in (
        ("Ada Quill", "ada@example.com"),
        ("Bo Ferreira", "bo@example.com"),
        ("Chi Nakamura", "chi@example.com"),
    ):
        member = create_member(api, full_name=name, email=email)
        sold.append(sell_membership(api, member["id"], tier["id"])["id"])

    first_rows, first_meta = validate_paginated(
        api.list_memberships(ADMIN, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3, "the count precedes the page window"
    assert first_meta["has_more"] is True
    assert_ordered_by_created_at(first_rows)

    second_rows, second_meta = validate_paginated(
        api.list_memberships(ADMIN, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    paged = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert paged == sold, "the two pages walk the three rows in created_at order with no repeats"


def test_reading_an_unknown_reservation_is_not_found(api):
    """A well-formed but unused reservation id is a 404 on its own error id.

    PRD §2.8: "Reservation existence — `ERR_RESERVATION_NOT_FOUND`, on reading
    one reservation, listing a reservation's satisfaction surveys, listing a
    reservation's occupancy exceptions, cancellation, check-in, check-out,
    extension, and survey submission."

    Design: Corner/entities/reservation_read_with_an_unknown_id_returns_not_found
    """
    reset_clock(api)

    error = validate_error(
        api.get_reservation(NON_EXISTENT_UUID, ADMIN), "ERR_RESERVATION_NOT_FOUND", 404
    )
    assert error["message"], "an error body carries a human-readable message"


def test_membership_create_without_a_tier_id_persists_nothing(api):
    """A missing required field is a 400 that writes neither contract nor invoice.

    PRD §2.8: "Body well-formedness — `ERR_INVALID_REQUEST` (HTTP 400), on every
    creating or mutating operation. All required body fields must be present,
    every enum-typed field must hold one of its declared values, every integer
    amount must be at least 0, every date must be a valid ISO 8601 calendar date,
    and a departure date must be strictly greater than its arrival date."

    Design: Corner/entities/membership_create_missing_required_tier_id_is_invalid_request
    """
    reset_clock(api)
    create_classic_tier(api)
    member = create_member(api, full_name="Nadia Brandt", email="nadia@example.com")

    response = api.create_membership(
        {"member_id": member["id"], "upfront_paid_cents": 795000}, ADMIN
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(api.list_memberships(ADMIN, {"member_id": member["id"]}))
    assert meta["total_count"] == 0, "no membership was persisted, so no invoice was minted"
    assert rows == []


def test_member_created_without_a_home_region_stores_null(api):
    """The one optional input is stored as null, and status defaults to ACTIVE.

    PRD §3.1: "A `Member` record captures `full_name`, an `email` that must be
    unique across all member records, and an optional `home_region` that is free
    text used only for reporting and never for any rule."

    Design: Corner/entities/member_create_omitting_home_region_applies_the_declared_default
    """
    reset_clock(api)
    payload = make_member_payload(full_name="Peregrine Osei", email="peregrine@example.com")
    payload.pop("home_region")

    member = validate_success(api.create_member(payload, ADMIN), 201)

    assert member["home_region"] is None, "an omitted optional field is null, not an empty string"
    assert member["status"] == "ACTIVE", "the server manages status and defaults it to ACTIVE"
    assert member["version"] == 1
    assert member["full_name"] == "Peregrine Osei"
    assert member["email"] == "peregrine@example.com"


def test_dues_invoice_components_come_from_the_tier(api):
    """The client names only three inputs; every money figure is derived.

    PRD §3.1: "Step one captures `base_dues_cents` as the tier's
    `annual_dues_cents`, frozen onto the invoice."

    Design: Corner/entities/dues_invoice_amount_cents_is_computed_from_the_tier_not_from_the_request
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    member = create_member(api, full_name="Rafi Osborne", email="rafi@example.com")

    membership = validate_success(
        api.create_membership(make_membership_payload(member["id"], tier["id"]), ADMIN), 201
    )

    invoices = list_invoices(api, membership["id"])
    assert len(invoices) == 1, "selling a contract issues exactly one invoice"
    invoice = invoices[0]
    assert invoice["status"] == "OPEN"
    assert invoice["cycle_year"] == 2026
    assert_invoice_components(
        invoice,
        base_dues_cents=42000,
        capital_assessment_cents=3360,
        loyalty_credit_cents=0,
        amount_cents=45360,
    )
    assert invoice["due_date"] == "2026-08-31", "the logical date plus the 30-day net term"

    stored = read_membership(api, membership["id"])
    assert stored["dues_balance_cents"] == 45360
    assert stored["dues_status"] == "CURRENT"


def test_park_audit_columns_are_server_generated_from_the_logical_clock(api):
    """id, created_at, updated_at and version are minted, not accepted as input.

    PRD §2.4: "Every persisted resource is addressed by an `id` that the server
    mints as a UUID. Identifiers carry no type prefix and are never supplied by
    the client."

    Design: Corner/entities/park_system_fields_are_server_generated_and_input_ignored
    """
    reset_clock(api)
    payload = make_park_payload(
        name="Kestrel Point RV Resort",
        park_class="CLASS_A",
        total_sites=30,
        member_allocation_pct=50,
    )

    park = validate_success(api.create_park(payload, ADMIN), 201)

    assert is_valid_uuid(park["id"]), "the id is a bare server-minted UUID"
    assert parse_instant(park["created_at"]) == parse_instant(DEFAULT_CLOCK_UTC), (
        "created_at comes from the logical clock, which is not wall-clock time"
    )
    assert park["updated_at"] == park["created_at"]
    assert park["version"] == 1
    assert_pool_split(park, member_sites=15, transient_sites=15)


def test_capital_project_rejects_an_unknown_category_and_a_negative_cost(api):
    """Both malformed bodies fail well-formedness before any scoring happens.

    PRD §3.9: "A `ParkManager` or a `ClubAdmin` proposes a project by naming the
    `park_id`, a short `title`, a `category` drawn from `SAFETY`, `UTILITY`,
    `AMENITY` and `EXPANSION`, a `requested_cost_cents` of at least 1, and the
    `fiscal_year` the project competes in, an integer between 2020 and 2100."

    Design: Corner/entities/capital_project_category_invalid_enum_is_rejected
    """
    reset_clock(api)
    park = create_open_park(
        api,
        name="Marsh Landing RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    manager = make_park_manager_headers(park["id"])

    validate_error(
        api.create_capital_project(
            make_capital_project_payload(
                park["id"], title="Add a splash pad", category="PLAYGROUND"
            ),
            manager,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_capital_project(
            make_capital_project_payload(
                park["id"], title="Negative cost probe", requested_cost_cents=-1
            ),
            manager,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    _rows, meta = validate_paginated(api.list_park_capital_projects(park["id"], manager))
    assert meta["total_count"] == 0, "neither rejected proposal created a project"


def test_amenity_inspections_append_rather_than_mutate(api):
    """A second inspection is a new immutable row; the first survives verbatim.

    PRD §2.4: "Two resources are deliberately append-only and therefore carry
    only `id` and `created_at` — `AmenityInspection` and `SatisfactionSurvey`
    have no `updated_at` and no `version` at all, because once filed neither is
    ever modified."

    Design: Corner/entities/amenity_inspection_is_immutable_with_no_version_and_no_update_endpoint
    """
    reset_clock(api)
    park = create_open_park(
        api,
        name="Fern Gully RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )

    first = validate_success(
        api.file_amenity_inspection(
            park["id"],
            make_amenity_inspection_payload(
                restroom_score=5, hookup_score=4, utility_score=3, road_score=2
            ),
            make_park_manager_headers(park["id"]),
        ),
        201,
    )
    assert_amenity_inspection(first)
    assert_append_only_columns(first, "AmenityInspection")
    # 0.35*5 + 0.25*4 + 0.25*3 + 0.15*2 = 3.80, a PROBATION band.
    assert first["composite_score"] == 3.80
    assert first["result"] == "PROBATION"
    assert first["inspector_user_id"] is not None

    second = validate_success(
        api.file_amenity_inspection(
            park["id"],
            make_amenity_inspection_payload(
                restroom_score=4, hookup_score=4, utility_score=4, road_score=4
            ),
            OFFICER,
        ),
        201,
    )
    assert second["id"] != first["id"], "re-inspecting appends rather than overwrites"
    assert second["composite_score"] == 4.00
    assert second["result"] == "PASS", "exactly 4.00 is a PASS on an inclusive lower edge"

    rows, meta = validate_paginated(api.list_park_amenity_inspections(park["id"], ADMIN))
    assert meta["total_count"] == 2
    preserved = next(row for row in rows if row["id"] == first["id"])
    assert preserved["composite_score"] == 3.80, "the earlier row is untouched"

    park_after = read_park(api, park["id"])
    assert park_after["amenity_compliance_status"] == "COMPLIANT", "only the newest result drives"
    assert park_after["last_inspection_at"] == second["inspected_at"]


def test_reservation_create_with_an_unknown_park_id_is_park_not_found(api):
    """Both foreign keys resolve before any business rule or ledger debit runs.

    PRD §2.8: "Park existence for every park id in a path or body —
    `ERR_PARK_NOT_FOUND`, on reading one park, on all four park sub-resource
    lists (amenity inspections, satisfaction surveys, maintenance windows,
    capital projects), on season opening, season closure, amenity inspection
    filing, member booking, transient booking, maintenance-window scheduling,
    and capital-project proposal."

    Design: Corner/entities/reservation_create_with_an_unknown_park_id_is_park_not_found
    """
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Saoirse Whitlock", "email": "saoirse@example.com"},
        upfront_paid_cents=1850000,
    )
    park = create_open_park(
        api,
        name="Dune Crest RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )

    validate_error(
        api.create_reservation(
            make_reservation_payload(
                NON_EXISTENT_UUID, holder["membership_id"], "2026-09-14", "2026-09-17"
            ),
            holder["headers"],
        ),
        "ERR_PARK_NOT_FOUND",
        404,
    )
    assert read_membership(api, holder["membership_id"])["nights_used_class_b"] == 0, (
        "the foreign key check precedes any entitlement debit"
    )

    accepted = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-09-14", "2026-09-17"
            ),
            holder["headers"],
        ),
        201,
    )
    assert accepted["park_id"] == park["id"]
    assert_reservation_state(
        accepted, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=3
    )
