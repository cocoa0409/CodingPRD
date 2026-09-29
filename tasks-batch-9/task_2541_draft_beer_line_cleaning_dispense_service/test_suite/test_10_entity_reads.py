"""Field-level reads: seeded defaults, single reads, listing and not-found."""

from test_helpers import (
    AccountStatus,
    ApiErrorId,
    BillingMode,
    ComplianceFlag,
    ContractStatus,
    DISPATCH_HEADERS,
    FundingStatus,
    LineStatus,
    NON_EXISTENT_UUID,
    SuspendedReason,
    TechnicianStatus,
    factories,
    fixtures,
    get_success_data,
    is_iso8601_timestamp,
    make_service_technician_headers,
    validate_error,
    validate_paginated,
)


def test_registering_a_venue_seeds_every_declared_field(api):
    """PRD §3.1: "The account is created in `ACTIVE` with `version` 1, `billing_mode`
    `DIRECT_BILL`, `lines_out_of_service_count` 0, `open_complaint_count` 0 and
    `suspended_reason` `NONE`; its `status` may later be `ACTIVE`, `SUSPENDED` or
    `TERMINATED`, and `suspended_reason` may later be `NONE`, `LINE_COMPLIANCE_THRESHOLD` or
    `MANUAL`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/entities/corner_account_create_returns_every_declared_field_with_seed_values
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    response = api.create_account(
        factories.account_payload(venue_name="Corner Case Tavern", glycol_system_present=False),
        DISPATCH_HEADERS,
    )

    account = get_success_data(response, expected_status=201)
    assert account["venue_name"] == "Corner Case Tavern"
    assert account["access_window_start_minute"] == 480
    assert account["access_window_end_minute"] == 1080
    assert account["glycol_system_present"] is False
    assert account["status"] == AccountStatus.ACTIVE
    assert account["billing_mode"] == BillingMode.DIRECT_BILL
    assert account["lines_out_of_service_count"] == 0
    assert account["open_complaint_count"] == 0
    assert account["suspended_reason"] == SuspendedReason.NONE
    assert account["version"] == 1
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_reading_a_line_back_returns_the_stored_row_unprojected(api):
    """PRD §3.2: "A newly registered line opens in `IN_SERVICE` — the only other value
    `status` ever takes is `OUT_OF_SERVICE` — with `compliance_flag` `COMPLIANT`,
    `last_chemical_type` `NONE`, and `last_cleaned_at`, `next_due_at`, `applied_psi` and
    `applied_co2_pct` all null and `days_overdue` 0."

    Design: Corner/entities/corner_beer_line_get_by_id_returns_the_stored_row
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Readback Bar")
    created = venue["lines"][0]

    read_back = get_success_data(
        api.get_beer_line(created["id"], make_service_technician_headers("tech-probe-1"))
    )

    assert read_back["id"] == created["id"]
    assert read_back["version"] == 1
    assert read_back["run_length_feet"] == 32
    assert read_back["inner_diameter_inches"] == 0.375
    assert read_back["beer_style_group"] == "ALE"
    assert read_back["status"] == LineStatus.IN_SERVICE
    assert read_back["compliance_flag"] == ComplianceFlag.COMPLIANT
    assert read_back["last_chemical_type"] == "NONE"
    assert read_back["last_cleaned_at"] is None
    assert read_back["next_due_at"] is None
    assert read_back["days_overdue"] == 0


def test_the_crew_roster_pages_and_counts_only_the_filtered_rows(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching the
    supplied filters before paging and `has_more` indicates whether rows remain beyond the
    current page."
    PRD §2.3: "Unless a subsection below says otherwise, every list endpoint returns its
    rows sorted by `created_at` in ascending order, so the oldest record appears first and
    paging through a collection is stable."

    Design: Corner/entities/corner_technician_list_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    first = fixtures.create_technician(api, full_name="Dana Ruiz")
    fixtures.create_technician(
        api, full_name="Kem Adeyemi", certification_level="CERTIFIED", caustic_certified=False
    )
    third = fixtures.create_technician(
        api,
        full_name="Sol Vranken",
        certification_level="APPRENTICE",
        caustic_certified=False,
        status=TechnicianStatus.INACTIVE,
    )

    page_one, meta_one = validate_paginated(api.list_technicians(DISPATCH_HEADERS, limit=2, offset=0))
    page_two, meta_two = validate_paginated(api.list_technicians(DISPATCH_HEADERS, limit=2, offset=2))
    active, meta_active = validate_paginated(
        api.list_technicians(DISPATCH_HEADERS, status=TechnicianStatus.ACTIVE, limit=10, offset=0)
    )

    assert len(page_one) == 2
    assert page_one[0]["id"] == first["id"]
    assert (meta_one["total_count"], meta_one["has_more"]) == (3, True)
    assert len(page_two) == 1
    assert page_two[0]["id"] == third["id"]
    assert (meta_two["total_count"], meta_two["has_more"]) == (3, False)
    assert len(active) == 2
    assert (meta_active["total_count"], meta_active["has_more"]) == (2, False)
    assert active[0]["id"] == first["id"]


def test_an_unknown_visit_identifier_reports_the_visits_own_not_found_code(api):
    """PRD §2.9: "All of these rejections carry HTTP 404 and each has its own code:
    `{account_id}` yields `ERR_ACCOUNT_NOT_FOUND`, `{contract_id}` yields
    `ERR_CONTRACT_NOT_FOUND`, `{line_id}` yields `ERR_LINE_NOT_FOUND`, `{technician_id}`
    yields `ERR_TECHNICIAN_NOT_FOUND`, `{lot_id}` yields `ERR_CHEMICAL_LOT_NOT_FOUND`,
    `{part_id}` yields `ERR_PART_NOT_FOUND`, `{program_id}` yields `ERR_PROGRAM_NOT_FOUND`,
    `{visit_id}` yields `ERR_VISIT_NOT_FOUND`, `{cycle_id}` yields `ERR_CYCLE_NOT_FOUND`,
    `{record_id}` yields `ERR_BALANCE_RECORD_NOT_FOUND`, `{inspection_id}` yields
    `ERR_INSPECTION_NOT_FOUND`, `{complaint_id}` yields `ERR_COMPLAINT_NOT_FOUND`,
    `{loop_id}` yields `ERR_GLYCOL_LOOP_NOT_FOUND`, and `{reading_id}` yields
    `ERR_READING_NOT_FOUND`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/corner_service_visit_get_with_unknown_uuid_returns_visit_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    response = api.get_service_visit(NON_EXISTENT_UUID, DISPATCH_HEADERS)

    error = validate_error(response, ApiErrorId.VISIT_NOT_FOUND, 404)
    assert isinstance(error["message"], str) and error["message"]
    assert response.json()["response_type"] == "error"


def test_omitting_the_per_line_rate_is_reported_before_the_version_guard(api):
    """PRD §3.1: "Its payload names the `account_id`, the contracted
    `cleaning_frequency_days` (which must be exactly 14, 21 or 28), the
    `contracted_line_count` the deal covers (at least 1), the `per_line_rate_cents` charged
    per line per visit before any multiplier, the flat `visit_base_fee_cents` truck-roll fee
    charged once per visit, an `effective_from` instant before which the contract may not be
    activated, the `expected_account_version` guard described in §2.7, and optionally a
    `brewer_program_id` when a brewer underwrites the venue's quality programme."
    PRD §2.8: "Checks are evaluated in a strict order and the **first** violated check
    short-circuits the request; nothing after it runs, and no side effect is applied."

    Design: Corner/entities/corner_contract_create_without_per_line_rate_is_invalid_request
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    account = fixtures.create_account(api, venue_name="Missing Field Inn")
    payload = factories.contract_payload(account["id"], account["version"])
    payload.pop("per_line_rate_cents")

    refused = api.create_contract(payload, DISPATCH_HEADERS)

    validate_error(refused, ApiErrorId.INVALID_REQUEST, 400)
    assert fixtures.read_account(api, account["id"])["version"] == 1, (
        "a rejected draft never bumps the parent account"
    )
    rows, meta = validate_paginated(api.list_contracts(DISPATCH_HEADERS, account_id=account["id"]))
    assert rows == [] and meta["total_count"] == 0


def test_every_optional_input_falls_back_to_its_declared_default(api):
    """PRD §3.3: "Field staff are registered by a `DispatchCoordinator` with a `full_name`
    (non-empty, at most 120 characters), a `certification_level` from the draft guild's three
    tiers `APPRENTICE`, `CERTIFIED` and `MASTER`, an optional `caustic_certified` flag
    defaulting to false that records whether the technician may handle caustic solution at
    all, and an optional employment `status` defaulting to `ACTIVE`, whose only other value
    is `INACTIVE`."
    PRD §3.1: "An optional `glycol_system_present` flag, defaulting to false, declares
    whether the venue runs a glycol-chilled long-draw system."

    Design: Corner/entities/corner_optional_inputs_fall_back_to_their_declared_defaults
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    technician = get_success_data(
        api.create_technician(
            {"full_name": "Default Dana", "certification_level": "CERTIFIED"}, DISPATCH_HEADERS
        ),
        expected_status=201,
    )
    account = get_success_data(
        api.create_account(
            {
                "venue_name": "Default Values Pub",
                "access_window_start_minute": 480,
                "access_window_end_minute": 1080,
            },
            DISPATCH_HEADERS,
        ),
        expected_status=201,
    )
    part = get_success_data(
        api.create_part(
            factories.part_payload(sku="FOB-12", component_type="FOB", unit_price_cents=890, stock_on_hand=4),
            DISPATCH_HEADERS,
        ),
        expected_status=201,
    )

    assert technician["caustic_certified"] is False
    assert technician["status"] == TechnicianStatus.ACTIVE
    assert technician["certification_level"] == "CERTIFIED"
    assert account["glycol_system_present"] is False
    assert part["brewer_funded_eligible"] is False
    assert part["stock_on_hand"] == 4
    loops, meta = validate_paginated(api.list_glycol_loops(DISPATCH_HEADERS, account_id=account["id"]))
    assert loops == [] and meta["total_count"] == 0, (
        "no chiller loop is cascaded for a venue that never declared one"
    )


def test_the_frequency_multiplier_is_derived_and_cannot_be_supplied(api):
    """PRD §3.1: "`frequency_multiplier` is a soil-load factor keyed purely on the
    contracted interval, held to two decimal places: a fortnightly contract at 14 days
    multiplies by 1.00, a three-weekly contract at 21 days by 1.10, and a four-weekly
    contract at 28 days by 1.25 — a line left three extra weeks between cleanings carries a
    quarter more soil and costs a quarter more to circulate."
    PRD §3.1: "`funding_status` is `NONE` when no `brewer_program_id` was supplied,
    `BREWER_FUNDED` when the named programme's status is `ACTIVE`, and `SELF_FUNDED` when the
    named programme is already exhausted or ended."

    Design: Corner/entities/corner_computed_frequency_multiplier_is_derived_and_an_extra_field_is_rejected
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    account = fixtures.create_account(api, venue_name="Derived Fields Hall")

    drafted = fixtures.draft_contract(api, account["id"], account["version"])

    assert drafted["frequency_multiplier"] == 1.10
    assert drafted["funding_status"] == FundingStatus.NONE
    assert drafted["status"] == ContractStatus.DRAFT
    bumped = fixtures.read_account(api, account["id"])
    assert bumped["version"] == 2

    steered = api.create_contract(
        factories.contract_payload(account["id"], bumped["version"], frequency_multiplier=9.99),
        DISPATCH_HEADERS,
    )

    validate_error(steered, ApiErrorId.INVALID_REQUEST, 400)
    rows, meta = validate_paginated(api.list_contracts(DISPATCH_HEADERS, account_id=account["id"]))
    assert len(rows) == 1 and meta["total_count"] == 1
