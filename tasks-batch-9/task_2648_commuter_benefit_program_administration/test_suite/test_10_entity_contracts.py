"""Entity contracts: created shapes, declared policy defaults, server-derived
fields, paginated roster reads and the append-only money ledger row.

Each test builds its own employer program from scratch through the documented
endpoints, because the service is restarted against an empty database before
every test.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    PROGRAM_ADMIN,
    assert_append_only_common_fields,
    assert_mutable_common_fields,
    assert_pagination_meta,
    factories,
    fixtures,
    make_order_desk_headers,
)

CLIENT_SUPPLIED_ID = "11111111-1111-4111-8111-111111111111"
CLIENT_SUPPLIED_CREATED_AT = "2020-01-01T00:00:00Z"


def test_01_employer_registration_returns_every_declared_program_field(api):
    """Registering an employer with all ten setup values echoes each of them and
    stamps the documented opening posture.

    PRD 3.1: "Three money ceilings are required at registration:
    `transit_group_limit_cents`, the monthly pre-tax exclusion limit shared by
    the whole transit side of the program; `parking_group_limit_cents`, the
    equivalent monthly limit for parking; and `program_cap_cents`, an aggregate
    ceiling on funded pre-tax exclusion across the entire employer."
    PRD 3.1: "A newly registered employer lands in `program_status` `DRAFT` with
    `ordinance_mandate_status` `UNASSESSED`, `total_pretax_committed_cents` and
    `enrolled_employee_count` both at zero, and `version` 1."
    PRD 2.4: "Every resource in this service is identified by `id`, a
    server-minted UUID string carrying no type prefix and no embedded meaning
    — clients must never construct one."
    PRD 4: "Operations that bring a new resource into existence answer with HTTP
    201; operations that modify, transition or sweep an existing resource answer
    with HTTP 200, as do all reads."

    Design: Corner/entities/employer_create_returns_201_with_all_declared_fields
    """
    payload = factories.employer_payload(
        legal_name="Ferry Building Commute Co",
        region_code="US-CA-SFO",
        transit_group_limit_cents=31500,
        parking_group_limit_cents=31500,
        program_cap_cents=900000,
        pretax_ratio_cap_pct=80,
        spill_policy="REJECT_OVERAGE",
        rollover_policy="FULL_ROLLOVER",
        rollover_cap_cents=0,
        forfeiture_grace_days=45,
    )
    employer = validate_success(
        api.create_employer(payload, PROGRAM_ADMIN), expected_status=201
    )

    assert employer["legal_name"] == "Ferry Building Commute Co"
    assert employer["region_code"] == "US-CA-SFO"
    assert employer["transit_group_limit_cents"] == 31500
    assert employer["parking_group_limit_cents"] == 31500
    assert employer["program_cap_cents"] == 900000
    assert employer["pretax_ratio_cap_pct"] == 80
    assert employer["spill_policy"] == "REJECT_OVERAGE"
    assert employer["rollover_policy"] == "FULL_ROLLOVER"
    assert employer["forfeiture_grace_days"] == 45

    assert employer["program_status"] == "DRAFT", (
        f"a fresh registration must land in DRAFT, got {employer['program_status']}"
    )
    assert employer["ordinance_mandate_status"] == "UNASSESSED"
    assert employer["total_pretax_committed_cents"] == 0
    assert employer["enrolled_employee_count"] == 0
    assert employer["version"] == 1

    assert is_valid_uuid(employer["id"]), (
        f"id must be a bare server-minted UUID, got {employer['id']!r}"
    )
    assert_mutable_common_fields(employer, expected_version=1)
    for money_field in (
        "transit_group_limit_cents",
        "parking_group_limit_cents",
        "program_cap_cents",
        "total_pretax_committed_cents",
    ):
        assert isinstance(employer[money_field], int), (
            f"{money_field} must be a whole-cent integer, got {employer[money_field]!r}"
        )


def test_02_catalogue_product_read_returns_the_stored_row_with_vendor_defaults(api):
    """Reading a catalogue product by id returns the stored row, including the
    server-minted ACTIVE status and the three operational defaults.

    PRD 3.5: "Three operational settings complete it: `lead_days`, the vendor's
    production lead time in whole days, defaulting to 3; `replacement_fee_cents`,
    the base fee charged to an employee's benefit account when lost or
    undelivered media is reissued, defaulting to 500 cents — five dollars; and
    `requires_physical_fulfillment`, a boolean defaulting to true that marks
    products which must actually be shipped, as paper passes and smart card loads
    are, rather than provisioned digitally."
    PRD 3.5: "A new product opens in `status` `ACTIVE`."
    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp with three fractional-second digits refreshed on every mutation,
    and `version`, an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/transit_media_get_returns_stored_catalog_row
    """
    created = validate_success(
        api.create_transit_media(
            factories.transit_media_payload(
                sku="NYC-30DAY",
                media_type="PAPER_PASS",
                region_code="US-NY-NYC",
                eligible_category_type="TRANSIT_PASS",
                unit_price_cents=13200,
            ),
            make_order_desk_headers("desk-catalog"),
        ),
        expected_status=201,
    )

    stored = validate_success(api.get_transit_media(created["id"], PROGRAM_ADMIN))

    assert stored["id"] == created["id"]
    assert stored["sku"] == "NYC-30DAY"
    assert stored["media_type"] == "PAPER_PASS"
    assert stored["unit_price_cents"] == 13200
    assert stored["status"] == "ACTIVE"
    assert stored["lead_days"] == 3, (
        f"lead_days must default to 3, got {stored['lead_days']}"
    )
    assert stored["replacement_fee_cents"] == 500, (
        f"replacement_fee_cents must default to 500, got {stored['replacement_fee_cents']}"
    )
    assert stored["requires_physical_fulfillment"] is True
    assert stored["region_code"] == "US-NY-NYC"
    assert stored["eligible_category_type"] == "TRANSIT_PASS"
    assert stored["version"] == 1
    assert_mutable_common_fields(stored, expected_version=1)


def _austin_roster(api):
    """Three ACTIVE employees on one DRAFT employer, enrolled in a fixed order."""
    employer = fixtures.make_draft_employer(
        api,
        PROGRAM_ADMIN,
        legal_name="Austin Roster Co",
        region_code="US-TX-AUS",
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )
    refs = [
        ("AUS-R1", "MONTHLY", "2026-02-01T00:00:00Z"),
        ("AUS-R2", "MONTHLY", "2026-02-02T00:00:00Z"),
        ("AUS-R3", "SEMI_MONTHLY", "2026-02-03T00:00:00Z"),
    ]
    for external_ref, payroll_cycle, hire_date in refs:
        fixtures.make_employee(
            api,
            employer["id"],
            PROGRAM_ADMIN,
            external_ref=external_ref,
            work_region_code="US-TX-AUS",
            payroll_cycle=payroll_cycle,
            hire_date=hire_date,
        )
    return employer, [ref for ref, _cycle, _hire in refs]


def test_03_employee_roster_first_page_reports_the_whole_roster_count(api):
    """A limit=2 page over a three-employee roster carries two rows while
    total_count still reports all three and has_more is true.

    PRD 2.3: "The four pagination fields `limit`, `offset`, `total_count` and
    `has_more` appear in the `meta` object of every list response: `limit` and
    `offset` echo the effective values used, `total_count` reports the number of
    rows matching the filters before the page window is applied, and `has_more`
    is true exactly when rows remain beyond the current page."

    Design: Corner/entities/employees_list_paginates_with_limit_and_offset
    """
    _employer, roster_refs = _austin_roster(api)

    page, meta = validate_paginated(
        api.list_employees(PROGRAM_ADMIN, {"limit": 2, "offset": 0})
    )

    assert len(page) == 2, f"limit=2 must return two rows, got {len(page)}"
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
    page_refs = [row["external_ref"] for row in page]
    assert len(set(page_refs)) == 2, f"page rows must be distinct, got {page_refs}"
    for ref in page_refs:
        assert ref in roster_refs, f"unexpected employee {ref} on the first page"


def test_04_employee_roster_second_page_window_closes_the_roster(api):
    """offset=2 returns the single remaining employee with has_more false, and the
    two page windows together partition the roster exactly once.

    PRD 2.3: "The four pagination fields `limit`, `offset`, `total_count` and
    `has_more` appear in the `meta` object of every list response: `limit` and
    `offset` echo the effective values used, `total_count` reports the number of
    rows matching the filters before the page window is applied, and `has_more`
    is true exactly when rows remain beyond the current page."

    Design: Corner/entities/employees_list_paginates_with_limit_and_offset
    """
    _employer, roster_refs = _austin_roster(api)

    first_page, first_meta = validate_paginated(
        api.list_employees(PROGRAM_ADMIN, {"limit": 2, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_employees(PROGRAM_ADMIN, {"limit": 2, "offset": 2})
    )

    assert len(second_page) == 1, (
        f"offset=2 over three rows must return one row, got {len(second_page)}"
    )
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert first_meta["total_count"] == second_meta["total_count"] == 3

    windowed = [row["external_ref"] for row in first_page] + [
        row["external_ref"] for row in second_page
    ]
    assert sorted(windowed) == sorted(roster_refs), (
        f"the two page windows must partition the roster exactly once, got {windowed}"
    )


def test_05_employer_registration_without_policy_dials_applies_declared_defaults(api):
    """Supplying only the five required setup values materialises the five
    declared policy defaults.

    PRD 3.1: "`pretax_ratio_cap_pct` bounds the share of any election's requested
    total that may be taken pre-tax; it is an integer from 0 through 100 inclusive
    and defaults to 100, meaning no ratio restriction."
    PRD 3.1: "`spill_policy` decides what happens when a pre-tax request exceeds
    the available exclusion headroom and defaults to `SPILL_TO_POSTTAX`, the
    alternative being `REJECT_OVERAGE`."
    PRD 3.1: "`rollover_policy` governs unused dollars at month close and defaults
    to `CAP_ROLLOVER`, the alternatives being `NO_ROLLOVER` and `FULL_ROLLOVER`."
    PRD 3.1: "`rollover_cap_cents` is the ceiling applied to carried-over dollars
    when the policy is `CAP_ROLLOVER` and defaults to 5000 cents — fifty dollars a
    month."
    PRD 3.1: "Alongside them, `forfeiture_grace_days` sets how many whole days
    after a departing employee's `termination_date` unused dollars are refunded to
    the employer rather than forfeited, and defaults to 30."

    Design: Corner/entities/employer_create_omitting_optional_policies_applies_declared_defaults
    """
    employer = validate_success(
        api.create_employer(
            factories.employer_payload(
                legal_name="Default Policy Co",
                region_code="US-IL-CHI",
                transit_group_limit_cents=30000,
                parking_group_limit_cents=30000,
                program_cap_cents=5000000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assert employer["pretax_ratio_cap_pct"] == 100, (
        f"pretax_ratio_cap_pct must default to 100, got {employer['pretax_ratio_cap_pct']}"
    )
    assert employer["spill_policy"] == "SPILL_TO_POSTTAX", (
        f"spill_policy must default to SPILL_TO_POSTTAX, got {employer['spill_policy']}"
    )
    assert employer["rollover_policy"] == "CAP_ROLLOVER", (
        f"rollover_policy must default to CAP_ROLLOVER, got {employer['rollover_policy']}"
    )
    assert employer["rollover_cap_cents"] == 5000, (
        f"rollover_cap_cents must default to 5000, got {employer['rollover_cap_cents']}"
    )
    assert employer["forfeiture_grace_days"] == 30, (
        f"forfeiture_grace_days must default to 30, got {employer['forfeiture_grace_days']}"
    )
    assert employer["program_status"] == "DRAFT"
    assert employer["version"] == 1


def _group_derivation_employer(api):
    """A DRAFT employer with distinct transit and parking group limits."""
    return fixtures.make_draft_employer(
        api,
        PROGRAM_ADMIN,
        legal_name="Group Derivation Co",
        region_code="US-WA-SEA",
        transit_group_limit_cents=30000,
        parking_group_limit_cents=31500,
        program_cap_cents=5000000,
    )


def test_06_transit_pass_and_vanpool_categories_derive_the_transit_limit_group(api):
    """Both transit-side category types compute the shared TRANSIT limit group; the
    caller never supplies it.

    PRD 3.1: "The service derives `limit_group` from the category type rather than
    accepting it: a category whose `category_type` is `TRANSIT_PASS` or `VANPOOL`
    belongs to the `TRANSIT` limit group, and a `PARKING` category belongs to the
    `PARKING` limit group."
    PRD 3.1: "A new category opens in `status` `ACTIVE` with `active_election_count`
    at zero; that counter tracks the number of elections referencing the category
    whose `funding_status` is `PENDING`, `HELD` or `FUNDED`."

    Design: Corner/entities/benefit_category_limit_group_computed_from_category_type
    """
    employer = _group_derivation_employer(api)

    transit_pass = validate_success(
        api.create_benefit_category(
            factories.benefit_category_payload(
                employer["id"],
                category_type="TRANSIT_PASS",
                monthly_exclusion_limit_cents=30000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    vanpool = validate_success(
        api.create_benefit_category(
            factories.benefit_category_payload(
                employer["id"],
                category_type="VANPOOL",
                monthly_exclusion_limit_cents=30000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assert transit_pass["limit_group"] == "TRANSIT", (
        f"TRANSIT_PASS must derive TRANSIT, got {transit_pass['limit_group']}"
    )
    assert vanpool["limit_group"] == "TRANSIT", (
        f"VANPOOL must derive TRANSIT, got {vanpool['limit_group']}"
    )
    assert transit_pass["status"] == "ACTIVE"
    assert vanpool["status"] == "ACTIVE"
    assert transit_pass["active_election_count"] == 0
    assert vanpool["active_election_count"] == 0


def test_07_parking_category_derives_the_parking_limit_group(api):
    """A PARKING category computes the PARKING limit group and opens with both
    allocation halves permitted.

    PRD 3.1: "The service derives `limit_group` from the category type rather than
    accepting it: a category whose `category_type` is `TRANSIT_PASS` or `VANPOOL`
    belongs to the `TRANSIT` limit group, and a `PARKING` category belongs to the
    `PARKING` limit group."
    PRD 3.1: "Two booleans control which halves of an allocation the category will
    accept: `pretax_allowed` and `posttax_allowed`, both defaulting to true."

    Design: Corner/entities/benefit_category_limit_group_computed_from_category_type
    """
    employer = _group_derivation_employer(api)

    parking = validate_success(
        api.create_benefit_category(
            factories.benefit_category_payload(
                employer["id"],
                category_type="PARKING",
                monthly_exclusion_limit_cents=31500,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assert parking["limit_group"] == "PARKING", (
        f"PARKING must derive PARKING, got {parking['limit_group']}"
    )
    assert parking["pretax_allowed"] is True
    assert parking["posttax_allowed"] is True
    assert parking["monthly_exclusion_limit_cents"] == 31500
    assert parking["status"] == "ACTIVE"
    assert parking["active_election_count"] == 0


def test_08_catalogue_create_ignores_client_supplied_identity_and_status(api):
    """A create body that also carries id, version, status and created_at is
    accepted with those client values ignored: the server mints its own.

    PRD 2.4: "Every resource in this service is identified by `id`, a server-minted
    UUID string carrying no type prefix and no embedded meaning — clients must
    never construct one."
    PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with three fractional-second digits recorded at insertion and never modified
    afterwards."
    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp with three fractional-second digits refreshed on every mutation, and
    `version`, an integer that starts at 1 when the row is created and increments
    by exactly 1 on every mutation of that row."
    PRD 3.5: "A new product opens in `status` `ACTIVE`."

    Design: Corner/entities/transit_media_system_fields_input_ignored
    """
    product = validate_success(
        api.create_transit_media(
            factories.transit_media_payload(
                sku="SEA-IGNORE",
                media_type="DEBIT_CARD",
                region_code="US-WA-SEA",
                eligible_category_type="PARKING",
                unit_price_cents=9000,
                id=CLIENT_SUPPLIED_ID,
                version=77,
                status="DISCONTINUED",
                created_at=CLIENT_SUPPLIED_CREATED_AT,
            ),
            make_order_desk_headers("desk-catalog"),
        ),
        expected_status=201,
    )

    assert product["status"] == "ACTIVE", (
        f"a client-supplied status must be ignored, got {product['status']}"
    )
    assert product["version"] == 1, (
        f"a client-supplied version must be ignored, got {product['version']}"
    )
    assert product["id"] != CLIENT_SUPPLIED_ID, (
        "the server must mint its own id rather than honour the client's"
    )
    assert is_valid_uuid(product["id"])
    assert product["created_at"] != CLIENT_SUPPLIED_CREATED_AT, (
        "created_at is recorded at insertion, not taken from the request body"
    )
    assert is_iso8601_timestamp(product["created_at"])
    assert product["sku"] == "SEA-IGNORE"
    assert product["unit_price_cents"] == 9000


def test_09_opening_rollover_ledger_row_is_append_only(api):
    """The ROLLOVER_IN row written when an account is seeded exposes only id and
    created_at — no version and no updated_at.

    PRD 3.1: "The account may be seeded with a carried-in balance through the
    optional `opening_rollover_cents` field, which lands on the account as
    `rollover_in_cents` and defaults to zero."
    PRD 3.1: "When a non-zero opening balance is supplied, the account's very first
    ledger entry is written at creation with `entry_type` `ROLLOVER_IN` and a
    positive `amount_cents` equal to that opening balance, with `source_entity`
    `BenefitAccount` and `source_id` the account's own identifier, and the
    account's `available_balance_cents` is set accordingly."
    PRD 2.4: "A `LedgerEntry` carries only `id` and `created_at` — it has neither
    `updated_at` nor `version`, and there is no endpoint that updates or deletes
    one."

    Design: Corner/entities/ledger_entry_rows_are_immutable_and_carry_no_version_field
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        legal_name="Ledger Immutability Co",
        region_code="US-IL-CHI",
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )
    enrolled = fixtures.make_enrolled_employee(
        api,
        built["employer"]["id"],
        built["categories"][0]["id"],
        PROGRAM_ADMIN,
        account_overrides={"opening_rollover_cents": 1500},
        external_ref="CHI-LED-1",
        work_region_code="US-IL-CHI",
        hire_date="2026-02-01T00:00:00Z",
    )
    account = enrolled["account"]

    entries, meta = validate_paginated(
        api.list_account_ledger_entries(account["id"], PROGRAM_ADMIN)
    )

    assert meta["total_count"] == 1, (
        f"seeding an account writes exactly one ledger row, got {meta['total_count']}"
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entry_type"] == "ROLLOVER_IN"
    assert entry["amount_cents"] == 1500
    assert isinstance(entry["amount_cents"], int), "money is a whole-cent integer"
    assert entry["balance_after_cents"] == 1500
    assert entry["source_entity"] == "BenefitAccount"
    assert entry["source_id"] == account["id"]
    assert entry["benefit_account_id"] == account["id"]
    assert_append_only_common_fields(entry)
