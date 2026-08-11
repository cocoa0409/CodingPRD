"""Creation, computed fields, declared defaults and the basic reads."""

from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    MOVE_MANAGER,
    PLATFORM_ADMIN,
    PUNCH_SLA_HOURS,
    ROLE_RATE_CENTS,
    VENDOR_DAILY_CAPACITY_DEFAULT,
    VENDOR_HOLDBACK_PCT_DEFAULT,
    AUTHORITY_DEFAULT_CEILING_CENTS,
    PACKAGE_BASE_CENTS,
    api_client,
    assert_append_only_fields,
    assert_client,
    assert_money,
    assert_same_instant,
    assert_two_dp,
    create_engagement_payload,
    designate,
    invoice_of,
    invoice_lines,
    is_valid_uuid,
    new_client,
    new_engagement,
    new_item,
    new_portal_party,
    new_punch_item,
    new_residence,
    new_room,
    parse_instant,
    read_engagement,
    read_milestones,
    read_residence,
    read_room,
    room_effective_capacity,
    set_clock,
    setup_engagement,
    setup_settle_in,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_client_create_mints_a_bare_uuid_and_a_zero_engagement_count():
    """PRD §2.4: "Every resource carries a server-minted `id`, a UUID string with no
    type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional
    digits."
    PRD §3.1: "It also carries `engagement_count`, a computed tally of every
    engagement row pointing at that client regardless of status, which begins at 0
    and rises by 1 each time an engagement is opened for that client."

    Design: Corner/entities/client_create_mints_system_fields_and_zero_engagement_count
    """
    set_clock("2026-05-02T09:00:00.000Z")
    response = api_client.create_client(
        {"full_name": "Ada Whitfield", "phone": "+1-555-0142", "email": "ada@example.com"},
        MOVE_MANAGER,
    )
    data = validate_success(response, expected_status=201)

    assert_client(data)
    assert data["version"] == 1
    assert data["engagement_count"] == 0
    assert data["full_name"] == "Ada Whitfield"
    assert is_valid_uuid(data["id"])


def test_engagement_create_seeds_six_milestones_and_exactly_one_draft_invoice():
    """PRD §3.1: "Six milestone rows are laid down with `sequence_index` 1 through 6
    and `milestone_key` values `ASSESSMENT`, `SORT_PLAN`, `PACK`, `MOVE_DAY`,
    `SETTLE_IN` and `CLOSE_OUT` in that order, each with its own `due_on` date. The
    `ASSESSMENT` milestone is set `IN_PROGRESS`, so the engagement's derived `phase`
    reads `ASSESSMENT` from the first moment. Exactly one invoice is created for the
    engagement, in status `DRAFT`, and there is never a second one."

    Design: Corner/entities/engagement_create_seeds_six_milestones_and_one_draft_invoice
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    engagement = new_engagement(client["id"])

    body = api_client.list_milestones(
        MOVE_MANAGER, params={"engagement_id": engagement["id"]}
    )
    rows, meta = validate_paginated(body)
    assert meta["total_count"] == 6
    assert rows[0]["milestone_key"] == "ASSESSMENT"
    assert rows[0]["sequence_index"] == 1
    assert rows[0]["status"] == "IN_PROGRESS"
    assert rows[5]["milestone_key"] == "CLOSE_OUT"
    assert rows[5]["sequence_index"] == 6
    assert rows[5]["status"] == "PENDING"

    invoices, invoice_meta = validate_paginated(
        api_client.list_invoices(BILLING_ADMIN, params={"engagement_id": engagement["id"]})
    )
    assert invoice_meta["total_count"] == 1
    assert invoices[0]["status"] == "DRAFT"
    assert_money(invoices[0]["subtotal_cents"], 0, "subtotal_cents")
    assert_money(invoices[0]["total_cents"], 0, "total_cents")

    assert engagement["status"] == "ACTIVE"
    assert read_engagement(engagement["id"])["phase"] == "ASSESSMENT"
    assert (
        validate_success(api_client.get_client(client["id"], MOVE_MANAGER))["engagement_count"]
        == 1
    )


def test_move_freeze_and_milestone_due_dates_are_offsets_off_the_move_date():
    """PRD §3.1: "The engagement's `move_freeze_at_utc` is computed as its
    `scheduled_move_start_utc` less seventy-two hours."
    PRD §3.1: "Each key has a fixed day offset applied to the calendar date of
    `scheduled_move_start_utc` in UTC: assessment is due thirty-five days before the
    move, the sort plan twenty-one days before, packing three days before, move day
    on the day itself, settle-in seven days after, and close-out twenty-one days after."

    Design: Corner/entities/engagement_computed_move_freeze_at_and_milestone_due_dates
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    engagement = new_engagement(client["id"])

    assert_same_instant(
        engagement["move_freeze_at_utc"], "2026-06-12T14:00:00.000Z", "move_freeze_at_utc"
    )
    due = {row["milestone_key"]: row["due_on"] for row in read_milestones(engagement["id"])}
    assert due["ASSESSMENT"] == "2026-05-11"
    assert due["SORT_PLAN"] == "2026-05-25"
    assert due["PACK"] == "2026-06-12"
    assert due["MOVE_DAY"] == "2026-06-15"
    assert due["SETTLE_IN"] == "2026-06-22"
    assert due["CLOSE_OUT"] == "2026-07-06"


def test_a_package_engagement_appends_its_base_line_at_creation():
    """PRD §3.1: "Under the package pipeline a `PACKAGE_BASE` ledger line is appended
    immediately, priced from the package tier alone: 185000 cents for `STUDIO`,
    265000 for `ONE_BED`, 395000 for `TWO_BED` and 620000 for `HOUSE`."

    Design: Corner/entities/package_engagement_create_appends_package_base_line
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    engagement = new_engagement(
        client["id"], billing_mode="PACKAGE", package_tier="STUDIO", home_tier="STUDIO"
    )
    invoice = invoice_of(engagement["id"])
    lines, meta = validate_paginated(
        api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": invoice["id"]})
    )
    assert meta["total_count"] == 1
    assert lines[0]["line_type"] == "PACKAGE_BASE"
    assert_money(lines[0]["amount_cents"], PACKAGE_BASE_CENTS["STUDIO"], "amount_cents")
    assert_money(invoice["subtotal_cents"], PACKAGE_BASE_CENTS["STUDIO"], "subtotal_cents")
    assert engagement["package_tier"] == "STUDIO"


def test_a_fresh_poa_seat_cannot_approve_and_has_a_zero_ceiling():
    """PRD §3.2: "`can_approve_dispositions` is true exactly when at least one
    authority record names that seat as its `holder_party_id`, is in status `ACTIVE`,
    and carries an `authority_scope` of `FULL` or `DISPOSITION_ONLY`, evaluated
    against the current logical clock; it is initialised false when the seat is created."
    PRD §3.2: "A seat of type `CLIENT` also carries the `client_id` it represents;
    for every other seat type that field is null."

    Design: Corner/entities/portal_party_defaults_cannot_approve_until_authority_active
    """
    world = setup_engagement(with_client_party=False)
    party = new_portal_party(
        world["engagement_id"], "POA", display_name="Ruth Whitfield", email="ruth@example.com"
    )
    assert party["can_approve_dispositions"] is False
    assert party["active_authority_ceiling_cents"] == 0
    assert party["client_id"] is None
    assert party["version"] == 1


def test_an_authority_record_defaults_its_ceiling_and_is_born_pending():
    """PRD §3.2: "The `approval_ceiling_cents` may be supplied and otherwise defaults
    to 100000 cents. A record is born `PENDING`."

    Design: Corner/entities/authority_record_default_ceiling_and_pending_status
    """
    world = setup_engagement(with_client_party=False, with_poa_party=True)
    record = validate_success(
        api_client.create_authority_record(
            {
                "engagement_id": world["engagement_id"],
                "holder_party_id": world["poa_party"]["id"],
                "authority_scope": "FULL",
                "effective_from_utc": "2026-05-01T00:00:00.000Z",
                "effective_to_utc": "2026-12-31T00:00:00.000Z",
            },
            MOVE_MANAGER,
        ),
        expected_status=201,
    )
    assert_money(
        record["approval_ceiling_cents"],
        AUTHORITY_DEFAULT_CEILING_CENTS,
        "approval_ceiling_cents",
    )
    assert record["status"] == "PENDING"
    assert record["suspend_count"] == 0
    assert (
        validate_success(
            api_client.get_portal_party(world["poa_party"]["id"], MOVE_MANAGER)
        )["can_approve_dispositions"]
        is False
    )


def test_a_new_room_reports_provisional_capacity_and_an_empty_load():
    """PRD §3.3: "While the parent residence is `DRAFT` or `PROPOSED`, the
    provisional variant applies: `effective_capacity_linear_inches` is the room's
    `nominal_linear_inches` multiplied by a derate of 0.80, rounded half-up to two
    decimal places, and the addendum is ignored completely."
    PRD §3.3: "the residence also carries `room_count` and
    `total_effective_capacity_linear_inches`, the latter summing
    `effective_capacity_linear_inches` across its rooms"

    Design: Corner/entities/destination_room_create_computes_provisional_capacity_and_zero_load
    """
    world = setup_engagement(with_client_party=False)
    residence = new_residence(world["engagement_id"])
    room = validate_success(
        api_client.create_destination_room(
            {
                "destination_residence_id": residence["id"],
                "room_type": "LIVING",
                "nominal_linear_inches": 240,
                "nominal_volume_cft": 400,
                "approved_addendum_linear_inches": 36,
            },
            MOVE_MANAGER,
        ),
        expected_status=201,
    )
    expected = room_effective_capacity(240, 36, approved=False)
    assert_two_dp(room["effective_capacity_linear_inches"], expected, "effective capacity")
    assert_two_dp(room["keep_load_linear_inches"], 0.00, "keep_load_linear_inches")
    assert_two_dp(room["headroom_linear_inches"], expected, "headroom_linear_inches")
    assert room["assigned_item_count"] == 0

    refreshed = read_residence(residence["id"])
    assert refreshed["room_count"] == 1
    assert refreshed["placement_status"] == "DRAFT"
    assert_two_dp(
        refreshed["total_effective_capacity_linear_inches"],
        expected,
        "total_effective_capacity_linear_inches",
    )


def test_a_catalogued_item_defaults_to_undecided_at_origin_with_no_appraisal():
    """PRD §3.4: "An `appraised_value_cents` may be given and defaults to 0,
    alongside an `appraisal_source` of `NONE`, `SELF_REPORTED` or `APPRAISED`,
    defaulting to `NONE`."
    PRD §3.4: "The disposition axis starts at `UNDECIDED` and admits `KEEP`,
    `DONATE`, `SELL` and `HAUL_AWAY`."
    PRD §3.4: "The handling axis starts at `AT_ORIGIN` and forks."

    Design: Corner/entities/inventory_item_create_defaults_undecided_at_origin_and_none_appraisal
    """
    world = setup_engagement(with_client_party=False)
    item = validate_success(
        api_client.create_inventory_item(
            {
                "engagement_id": world["engagement_id"],
                "label": "Walnut sideboard",
                "category": "FURNITURE",
                "footprint_linear_inches": 96,
                "volume_cft": 40,
            },
            MOVE_MANAGER,
        ),
        expected_status=201,
    )
    assert item["disposition"] == "UNDECIDED"
    assert item["handling_state"] == "AT_ORIGIN"
    assert item["appraisal_source"] == "NONE"
    assert_money(item["appraised_value_cents"], 0, "appraised_value_cents")
    assert item["hold_state"] == "NONE"
    assert item["disposition_locked"] is False
    assert item["redesignation_count"] == 0

    engagement = read_engagement(world["engagement_id"])
    assert engagement["inventory_item_count"] == 1
    assert_two_dp(engagement["total_inventory_volume_cft"], 40.00, "total_inventory_volume_cft")


def test_an_omitted_crew_rate_falls_back_to_the_role_standard_rate():
    """PRD §3.7: "Each carries a `full_name`, a `crew_role` from `LEAD`,
    `ORGANIZER`, `PACKER` and `DRIVER`, and an `hourly_rate_cents`; when the rate is
    omitted it falls back to the role's standard rate — 9500 cents an hour for a
    lead, 8200 for an organiser, 6800 for a packer and 7400 for a driver."

    Design: Corner/entities/crew_member_hourly_rate_defaults_to_role_constant
    """
    set_clock("2026-05-02T09:00:00.000Z")
    packer = validate_success(
        api_client.create_crew_member(
            {"full_name": "Nina Ortiz", "crew_role": "PACKER"}, PLATFORM_ADMIN
        ),
        expected_status=201,
    )
    organizer = validate_success(
        api_client.create_crew_member(
            {"full_name": "Sal Ibarra", "crew_role": "ORGANIZER"}, PLATFORM_ADMIN
        ),
        expected_status=201,
    )
    assert_money(packer["hourly_rate_cents"], ROLE_RATE_CENTS["PACKER"], "packer rate")
    assert_money(organizer["hourly_rate_cents"], ROLE_RATE_CENTS["ORGANIZER"], "organiser rate")
    assert packer["assignment_count"] == 0


def test_an_omitted_vendor_capacity_and_holdback_take_their_declared_defaults():
    """PRD §3.8: "A vendor is platform reference data registered by the platform
    administrator: a `name`, a `vendor_type` from `JUNK_HAUL`, `CONSIGNMENT`,
    `APPRAISAL`, `CLEANING` and `SHREDDING`, a `coi_expires_on`
    certificate-of-insurance expiry date in `YYYY-MM-DD` form, an optional
    `daily_capacity` defaulting to 3, and an optional `holdback_pct` defaulting to
    0.10 — the fraction of each quote withheld until the client signs off."

    Design: Corner/entities/vendor_create_defaults_capacity_and_holdback
    """
    set_clock("2026-05-02T09:00:00.000Z")
    vendor = validate_success(
        api_client.create_vendor(
            {
                "name": "Northside Junk Haul",
                "vendor_type": "JUNK_HAUL",
                "coi_expires_on": "2027-01-31",
            },
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )
    assert vendor["daily_capacity"] == VENDOR_DAILY_CAPACITY_DEFAULT
    assert float(vendor["holdback_pct"]) == VENDOR_HOLDBACK_PCT_DEFAULT
    assert vendor["coi_renewal_count"] == 0
    assert vendor["blocked_assignment_count"] == 0


def test_a_posted_ledger_line_carries_no_version_and_no_updated_at():
    """PRD §2.4: "`InvoiceLine` is the single exception. A ledger line is immutable
    once written: it carries only `id` and `created_at`, and has neither `updated_at`
    nor `version`."
    PRD §3.11: "lines produced by a consignment credit or reversal also name their
    `source_consignment_lot_id`, which is null for every other kind"

    Design: Corner/entities/invoice_line_is_immutable_and_carries_no_version_field
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    engagement = new_engagement(
        client["id"], billing_mode="PACKAGE", package_tier="STUDIO", home_tier="STUDIO"
    )
    invoice = invoice_of(engagement["id"])
    line_id = invoice_lines(invoice["id"])[0]["id"]

    data = validate_success(api_client.get_invoice_line(line_id, BILLING_ADMIN))
    assert_append_only_fields(data, "InvoiceLine")
    assert data["source_consignment_lot_id"] is None
    assert data["line_type"] == "PACKAGE_BASE"


def test_a_major_punch_item_is_due_seventy_two_hours_after_it_was_raised():
    """PRD §3.9: "Each severity carries its own service-level window measured from
    the item's `created_at`: a critical defect is due within twenty-four hours, a
    major one within seventy-two hours and a minor one within one hundred and sixty-
    eight hours, and that instant is stored as `due_at_utc`."
    PRD §3.9: "`breached_sla` is true exactly when the current logical clock is
    strictly after `due_at_utc` while the item's status is `OPEN` or `REOPENED`."

    Design: Corner/entities/punch_list_item_create_computes_severity_sla_due_at
    """
    world = setup_settle_in(settle_in_clock="2026-06-20T10:00:00.000Z")
    item = new_punch_item(world["engagement_id"], "Scratched dresser top", "MAJOR")

    expected_due = parse_instant(item["created_at"]) + timedelta(
        hours=PUNCH_SLA_HOURS["MAJOR"]
    )
    assert_same_instant(
        item["due_at_utc"], expected_due.isoformat().replace("+00:00", "Z"), "due_at_utc"
    )
    assert item["status"] == "OPEN"
    assert item["breached_sla"] is False
    assert item["reopen_count"] == 0


def test_engagement_list_honours_limit_offset_and_reports_total_count():
    """PRD §2.3: "Every endpoint that returns an array accepts two optional query
    parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100.
    `offset` defaults to 0 and has a minimum of 0; there is no upper bound on it."
    PRD §2.3: "`total_count` is the number of records matching the supplied filters
    before the window is applied, and `has_more` is true when records remain beyond
    the current window."

    Design: Corner/entities/engagement_list_honours_limit_offset_and_total_count
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    new_engagement(client["id"])
    new_engagement(
        client["id"], home_tier="ONE_BED", scheduled_move_start_utc="2026-07-15T14:00:00.000Z",
        mileage_miles=30, origin_stairs_flights=0, origin_long_carry_feet=20,
    )
    new_engagement(
        client["id"], billing_mode="PACKAGE", package_tier="TWO_BED", home_tier="TWO_BED",
        scheduled_move_start_utc="2026-08-15T14:00:00.000Z", mileage_miles=55,
        origin_stairs_flights=3, origin_long_carry_feet=200,
    )

    rows, meta = validate_paginated(
        api_client.list_engagements(
            MOVE_MANAGER, params={"client_id": client["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api_client.list_engagements(
            MOVE_MANAGER, params={"client_id": client["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert (
        validate_success(api_client.get_client(client["id"], MOVE_MANAGER))["engagement_count"]
        == 3
    )


def test_inventory_list_filters_combine_conjunctively_on_disposition_and_room():
    """PRD §2.3: "Filters offered by a list endpoint combine conjunctively —
    supplying two filters returns only records matching both."
    PRD §3.4: "Items can be listed and filtered by `engagement_id`, by
    `assigned_room_id`, by `consignment_lot_id`, by `unpack_session_id`, by
    `disposition` and by `handling_state`."

    Design: Corner/entities/inventory_items_list_filters_by_disposition_and_room
    """
    world = setup_engagement(with_client_party=False, with_residence=True)
    eng_id = world["engagement_id"]
    first = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    second = new_item(eng_id, label="Reading chair", footprint_linear_inches=90, volume_cft=35)
    third = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(first["id"], "KEEP", world["room"]["id"])
    designate(second["id"], "KEEP", world["room"]["id"])
    designate(third["id"], "DONATE")

    rows, meta = validate_paginated(
        api_client.list_inventory_items(
            MOVE_MANAGER, params={"engagement_id": eng_id, "disposition": "KEEP"}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}

    rows, meta = validate_paginated(
        api_client.list_inventory_items(
            MOVE_MANAGER, params={"assigned_room_id": world["room"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}

    rows, meta = validate_paginated(
        api_client.list_inventory_items(
            MOVE_MANAGER, params={"engagement_id": eng_id, "disposition": "DONATE"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == third["id"]
    assert read_room(world["room"]["id"])["assigned_item_count"] == 2


def test_omitting_a_required_engagement_field_returns_a_validation_error():
    """PRD §2.7: "Every required input field of the endpoint is present and of its
    declared type, and the numeric fields the domain requires to be positive are
    greater than zero: `quoted_cents`, `list_price_cents`, `gross_sale_price_cents`,
    `amount_cents` on a charge line, `truck_capacity_cft`, `truck_count`,
    `footprint_linear_inches`, `volume_cft`, `nominal_linear_inches` and
    `nominal_volume_cft`. Otherwise `ERR_VALIDATION`, HTTP 400."

    Design: Corner/entities/missing_required_field_on_engagement_create_returns_validation
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    payload = create_engagement_payload(client["id"])
    payload.pop("home_tier")

    validate_error(
        api_client.create_engagement(payload, MOVE_MANAGER), ApiErrorId.ERR_VALIDATION.value
    )
    _, meta = validate_paginated(
        api_client.list_engagements(MOVE_MANAGER, params={"client_id": client["id"]})
    )
    assert meta["total_count"] == 0
    assert (
        validate_success(api_client.get_client(client["id"], MOVE_MANAGER))["engagement_count"]
        == 0
    )


def test_an_undeclared_enum_member_returns_the_enum_error_not_the_validation_error():
    """PRD §2.7: "Every enum-typed input field carries a declared member of that
    enum. This applies to `billing_mode`, `home_tier`, `package_tier`, `party_type`,
    `authority_scope`, `unit_type`, `room_type`, `category`, `appraisal_source`,
    `disposition`, `target_handling_state`, `entry_kind`, `crew_role`,
    `vendor_type`, `service_kind`, `line_type`, `priority`, `severity`, `resolution`
    and `milestone_key`, and to no other field. Otherwise `ERR_INVALID_ENUM`, HTTP
    400. No other field routes to this error."

    Design: Corner/entities/invalid_enum_value_on_engagement_create_returns_invalid_enum
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    error = validate_error(
        api_client.create_engagement(
            create_engagement_payload(client["id"], home_tier="DUPLEX"), MOVE_MANAGER
        ),
        ApiErrorId.ERR_INVALID_ENUM.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value


def test_a_limit_above_one_hundred_is_rejected_while_one_hundred_is_accepted():
    """PRD §2.3: "A `limit` outside the range 1 to 100 inclusive, a non-integer
    `limit`, a negative `offset` or a non-integer `offset` is rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/pagination_limit_above_max_is_rejected
    """
    world = setup_engagement(with_client_party=False)
    validate_error(
        api_client.list_engagements(MOVE_MANAGER, params={"limit": 101, "offset": 0}),
        ApiErrorId.ERR_VALIDATION.value,
    )
    _, meta = validate_paginated(
        api_client.list_engagements(MOVE_MANAGER, params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1
