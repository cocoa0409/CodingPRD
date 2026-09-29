"""Entity shapes, server-minted identity, declared defaults and record retrieval.

Every test starts from an empty database and builds all of its own preconditions
through PRD-declared endpoints only.
"""

from test_helpers import (
    approve_brand,
    assert_audit_finding,
    assert_price_schedule,
    assert_price_schedule_item,
    assert_state_program,
    assert_wholesaler,
    collect_audit,
    make_filing_agent_headers,
    new_audit,
    new_brand,
    new_filing_agent,
    new_licensee_user,
    new_schedule,
    new_state_program,
    new_wholesaler,
    read_schedule,
    regulator_headers,
    set_clock,
    setup_effective_schedule,
    setup_invoice_with_lines,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# StateProgram — creation, defaults and declared input ranges
# ---------------------------------------------------------------------------

def test_01_state_program_creation_echoes_every_supplied_configuration_threshold(api):
    """PRD §3.1: "A `ComplianceOfficer` registers one by supplying a `state_code` — a
    two-letter code that must be unique across all programs — and a `program_name`
    for display."
    PRD §3.1: "Every other attribute of a program is optional on input and falls back
    to a documented default, and it is these defaults that quietly set the tone of the
    whole system:"
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."
    PRD §2.5: "A newly created record has `version` equal to 1 and `updated_at` equal to
    `created_at`."

    Design: Corner/entities/state_program_creation_returns_created_program_with_supplied_fields
    """
    set_clock(CLOCK_START)

    payload = {
        "state_code": "NV",
        "program_name": "Nevada Price Posting Program",
        "posting_deadline_day": 5,
        "hold_window_days": 2,
        "correction_window_days": 9,
        "combo_cooldown_days": 4,
        "quantity_discount_allowed": False,
        "combination_sale_allowed": False,
        "max_quantity_discount_pct": 0.20,
        "max_promotional_allowance_pct": 0.03,
        "depletion_allowance_per_case_cents": 200,
        "late_filing_penalty_cents": 300000,
        "repeat_correction_penalty_cents": 120000,
        "frivolous_amendment_penalty_cents": 80000,
        "off_posted_penalty_rate_pct": 0.50,
        "max_corrections_per_schedule": 1,
    }
    response = api.create_state_program(payload, regulator_headers())
    data = validate_success(response, 201)

    assert data["state_code"] == "NV", "state_code must be stored as supplied"
    assert data["program_name"] == "Nevada Price Posting Program", (
        "program_name must be stored as supplied"
    )
    assert data["posting_deadline_day"] == 5, "posting_deadline_day must be stored as supplied"
    assert data["hold_window_days"] == 2, "hold_window_days must be stored as supplied"
    assert data["correction_window_days"] == 9, (
        "correction_window_days must be stored as supplied"
    )
    assert data["combo_cooldown_days"] == 4, "combo_cooldown_days must be stored as supplied"
    assert data["quantity_discount_allowed"] is False, (
        "quantity_discount_allowed must be stored as supplied"
    )
    assert data["combination_sale_allowed"] is False, (
        "combination_sale_allowed must be stored as supplied"
    )
    assert data["max_quantity_discount_pct"] == 0.20, (
        "max_quantity_discount_pct must be stored as supplied"
    )
    assert data["max_promotional_allowance_pct"] == 0.03, (
        "max_promotional_allowance_pct must be stored as supplied"
    )
    assert data["depletion_allowance_per_case_cents"] == 200, (
        "depletion_allowance_per_case_cents must be stored as supplied"
    )
    assert data["late_filing_penalty_cents"] == 300000, (
        "late_filing_penalty_cents must be stored as supplied"
    )
    assert data["repeat_correction_penalty_cents"] == 120000, (
        "repeat_correction_penalty_cents must be stored as supplied"
    )
    assert data["frivolous_amendment_penalty_cents"] == 80000, (
        "frivolous_amendment_penalty_cents must be stored as supplied"
    )
    assert data["off_posted_penalty_rate_pct"] == 0.50, (
        "off_posted_penalty_rate_pct must be stored as supplied"
    )
    assert data["max_corrections_per_schedule"] == 1, (
        "max_corrections_per_schedule must be stored as supplied"
    )

    assert_state_program(data)
    assert data["version"] == 1, "a newly created record has version 1"
    assert data["updated_at"] == data["created_at"], (
        "a newly created record has updated_at equal to created_at"
    )

    body = response.json()
    assert body["response_type"] == "object", "a single resource is returned as an object"
    assert "api_request_id" in body["meta"], "meta must carry api_request_id"
    assert "api_request_timestamp" in body["meta"], "meta must carry api_request_timestamp"


def test_02_state_program_omitted_optional_fields_receive_declared_defaults(api):
    """PRD §3.1: "`posting_deadline_day` defaults to the 10th of the posting month and
    must be an integer from 1 through 28 inclusive; `hold_window_days` defaults to 3 and
    must be at least 1; `correction_window_days` defaults to 15 and must be at least 1;
    `combo_cooldown_days` defaults to 7 and must be at least 0; `quantity_discount_allowed`
    and `combination_sale_allowed` both default to `true`; `max_quantity_discount_pct`
    defaults to `0.15` and must fall between 0 and 1 inclusive;
    `max_promotional_allowance_pct` defaults to `0.05` and must fall between 0 and 1
    inclusive; `depletion_allowance_per_case_cents` defaults to 150 cents per case and must
    be at least 0; `late_filing_penalty_cents` defaults to 250,000 cents — two thousand
    five hundred dollars per late filing — and must be at least 0;
    `repeat_correction_penalty_cents` defaults to 100,000 cents and must be at least 0;
    `frivolous_amendment_penalty_cents` defaults to 75,000 cents and must be at least 0;
    `off_posted_penalty_rate_pct` defaults to `0.40` and must fall between 0 and 1
    inclusive; and `max_corrections_per_schedule` defaults to 2 and must be at least 1."

    Design: Corner/entities/state_program_omitted_optional_fields_receive_declared_defaults
    """
    set_clock(CLOCK_START)

    response = api.create_state_program(
        {"state_code": "TX", "program_name": "Texas Price Posting Program"},
        regulator_headers(),
    )
    data = validate_success(response, 201)

    assert data["posting_deadline_day"] == 10, "posting_deadline_day defaults to 10"
    assert data["hold_window_days"] == 3, "hold_window_days defaults to 3"
    assert data["correction_window_days"] == 15, "correction_window_days defaults to 15"
    assert data["combo_cooldown_days"] == 7, "combo_cooldown_days defaults to 7"
    assert data["quantity_discount_allowed"] is True, "quantity_discount_allowed defaults to true"
    assert data["combination_sale_allowed"] is True, "combination_sale_allowed defaults to true"
    assert data["max_quantity_discount_pct"] == 0.15, "max_quantity_discount_pct defaults to 0.15"
    assert data["max_promotional_allowance_pct"] == 0.05, (
        "max_promotional_allowance_pct defaults to 0.05"
    )
    assert data["depletion_allowance_per_case_cents"] == 150, (
        "depletion_allowance_per_case_cents defaults to 150"
    )
    assert data["late_filing_penalty_cents"] == 250000, (
        "late_filing_penalty_cents defaults to 250,000"
    )
    assert data["repeat_correction_penalty_cents"] == 100000, (
        "repeat_correction_penalty_cents defaults to 100,000"
    )
    assert data["frivolous_amendment_penalty_cents"] == 75000, (
        "frivolous_amendment_penalty_cents defaults to 75,000"
    )
    assert data["off_posted_penalty_rate_pct"] == 0.40, (
        "off_posted_penalty_rate_pct defaults to 0.40"
    )
    assert data["max_corrections_per_schedule"] == 2, "max_corrections_per_schedule defaults to 2"


def test_03_state_program_missing_required_program_name_is_rejected(api):
    """PRD §3.1: "A `ComplianceOfficer` registers one by supplying a `state_code` — a
    two-letter code that must be unique across all programs — and a `program_name`
    for display."
    PRD §2.10: "Every required body field is present; every field has its declared type;
    every enum field carries a declared member; every numeric field falls inside its
    declared range; every datetime field is a parseable ISO 8601 instant; and every
    interval field pair is ordered so the end strictly follows the start
    (`registration_expires_on` strictly after `registration_effective_from`;
    `promo_ends_at` strictly after `promo_starts_at`). Otherwise `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/state_program_missing_required_program_name_returns_invalid_request
    """
    set_clock(CLOCK_START)

    response = api.create_state_program({"state_code": "TX"}, regulator_headers())
    validate_error(response, "ERR_INVALID_REQUEST")
    assert response.json()["response_type"] == "error", "an error envelope is returned"

    programs, meta = validate_paginated(api.list_state_programs(regulator_headers()))
    assert programs == [], "no StateProgram may be created by a rejected request"
    assert meta["total_count"] == 0, "total_count must stay 0 after the rejected create"


def test_04_state_program_posting_deadline_day_boundary_accepts_28_and_rejects_29(api):
    """PRD §3.1: "`posting_deadline_day` defaults to the 10th of the posting month and
    must be an integer from 1 through 28 inclusive"
    PRD §2.10: "Every required body field is present; every field has its declared type;
    every enum field carries a declared member; every numeric field falls inside its
    declared range; every datetime field is a parseable ISO 8601 instant; and every
    interval field pair is ordered so the end strictly follows the start
    (`registration_expires_on` strictly after `registration_effective_from`;
    `promo_ends_at` strictly after `promo_starts_at`). Otherwise `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/state_program_posting_deadline_day_above_declared_range_returns_invalid_request
    """
    set_clock(CLOCK_START)

    at_maximum = validate_success(
        api.create_state_program(
            {
                "state_code": "OK",
                "program_name": "Oklahoma Program",
                "posting_deadline_day": 28,
            },
            regulator_headers(),
        ),
        201,
    )
    assert at_maximum["posting_deadline_day"] == 28, (
        "28 is the declared maximum and must be accepted"
    )

    above_maximum = api.create_state_program(
        {
            "state_code": "TX",
            "program_name": "Texas Program",
            "posting_deadline_day": 29,
        },
        regulator_headers(),
    )
    validate_error(above_maximum, "ERR_INVALID_REQUEST")

    _programs, meta = validate_paginated(api.list_state_programs(regulator_headers()))
    assert meta["total_count"] == 1, (
        "only the program created with the in-range deadline day may exist"
    )


# ---------------------------------------------------------------------------
# Wholesaler and Brand — enum membership and interval ordering
# ---------------------------------------------------------------------------

def test_05_wholesaler_license_status_outside_the_declared_enum_is_rejected(api):
    """PRD §3.1: "Its `license_status` is optional on input and defaults to `ACTIVE`; the
    only other permitted value is `SUSPENDED`."
    PRD §2.10: "Every required body field is present; every field has its declared type;
    every enum field carries a declared member; every numeric field falls inside its
    declared range; every datetime field is a parseable ISO 8601 instant; and every
    interval field pair is ordered so the end strictly follows the start
    (`registration_expires_on` strictly after `registration_effective_from`;
    `promo_ends_at` strictly after `promo_starts_at`). Otherwise `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/wholesaler_license_status_unknown_enum_member_returns_invalid_request
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")

    response = api.create_wholesaler(
        {
            "license_number": "W-1001",
            "legal_name": "Lone Star Distributing",
            "state_program_id": program["id"],
            "license_status": "REVOKED",
        },
        regulator_headers(),
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    wholesalers, meta = validate_paginated(api.list_wholesalers(regulator_headers()))
    assert wholesalers == [], "no Wholesaler may be created with an undeclared license_status"
    assert meta["total_count"] == 0, "total_count must stay 0 after the rejected create"


def test_06_brand_registration_interval_with_expiry_before_effective_is_rejected(api):
    """PRD §3.2: "the closed interval `registration_effective_from` through
    `registration_expires_on`, where the expiry instant must be strictly after the
    effective instant"
    PRD §2.10: "Every required body field is present; every field has its declared type;
    every enum field carries a declared member; every numeric field falls inside its
    declared range; every datetime field is a parseable ISO 8601 instant; and every
    interval field pair is ordered so the end strictly follows the start
    (`registration_expires_on` strictly after `registration_effective_from`;
    `promo_ends_at` strictly after `promo_starts_at`). Otherwise `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/brand_registration_interval_ordered_end_before_start_returns_invalid_request
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")
    wholesaler = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Distributing"
    )
    _agent, agent_headers = new_filing_agent(wholesaler["id"], "Fay Filer")

    response = api.create_brand(
        {
            "wholesaler_id": wholesaler["id"],
            "brand_name": "Rio Reserve",
            "supplier_name": "Rio Supply Co",
            "beverage_class": "SPIRITS",
            "registration_effective_from": "2027-01-01T00:00:00Z",
            "registration_expires_on": "2026-01-01T00:00:00Z",
        },
        agent_headers,
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    brands, meta = validate_paginated(
        api.list_brands(regulator_headers(), params={"wholesaler_id": wholesaler["id"]})
    )
    assert brands == [], "a reversed registration interval must not create a Brand"
    assert meta["total_count"] == 0, "total_count must stay 0 after the rejected create"


# ---------------------------------------------------------------------------
# PriceSchedule and PriceScheduleItem — server-owned derived and system fields
# ---------------------------------------------------------------------------

def test_07_price_schedule_derived_fields_ignore_client_supplied_values(api):
    """PRD §3.3: "A schedule always begins in `DRAFT`, with `filed_at`,
    `filed_by_user_id`, `certified_at`, `certified_by_user_id`, `hold_window_ends_at`,
    `return_reason` and `superseded_by_schedule_id` all unset, with `is_late` `false`, and
    with `return_count`, `correction_count` and `item_count` all 0."
    PRD §3.3: "A `posting_month` of `2026-09` therefore yields an `effective_date` of
    `2026-10-01T00:00:00.000Z`, and a `posting_month` of `2026-12` yields
    `2027-01-01T00:00:00.000Z`."

    Design: Corner/entities/price_schedule_computed_fields_are_server_derived_and_client_values_are_ignored_input
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")
    wholesaler = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Distributing"
    )
    _agent, agent_headers = new_filing_agent(wholesaler["id"], "Fay Filer")

    response = api.create_price_schedule(
        {
            "wholesaler_id": wholesaler["id"],
            "state_program_id": program["id"],
            "posting_month": "2026-09",
            "status": "POSTED",
            "effective_date": "2020-01-01T00:00:00Z",
            "is_late": True,
            "item_count": 9,
        },
        agent_headers,
    )
    data = validate_success(response, 201)
    assert_price_schedule(data)

    assert data["status"] == "DRAFT", "a schedule always begins in DRAFT"
    assert data["effective_date"] == "2026-10-01T00:00:00.000Z", (
        "effective_date is derived from posting_month, never taken from the body"
    )
    assert data["is_late"] is False, "a new schedule begins with is_late false"
    assert data["item_count"] == 0, "a new schedule begins with item_count 0"
    assert data.get("filed_at") is None, "filed_at is unset on a new schedule"
    assert data.get("filed_by_user_id") is None, "filed_by_user_id is unset on a new schedule"
    assert data.get("certified_at") is None, "certified_at is unset on a new schedule"
    assert data.get("certified_by_user_id") is None, (
        "certified_by_user_id is unset on a new schedule"
    )
    assert data.get("hold_window_ends_at") is None, (
        "hold_window_ends_at is unset on a new schedule"
    )
    assert data["return_count"] == 0, "a new schedule begins with return_count 0"
    assert data["correction_count"] == 0, "a new schedule begins with correction_count 0"
    assert data.get("superseded_by_schedule_id") is None, (
        "superseded_by_schedule_id is unset on a new schedule"
    )


def test_08_price_schedule_item_identity_is_server_minted_and_parent_rollup_advances(api):
    """PRD §2.5: "Every persisted record carries an `id`, a string holding a server-minted
    UUID with no type prefix and no client influence, and a `created_at`, an ISO 8601 UTC
    instant with three fractional digits recording when the record was first written."
    PRD §3.3: "A new item begins in `DRAFT` with `certified_case_price_cents`,
    `certified_unit_price_cents` and `supersedes_item_id` unset and with `amendment_count`
    and `correction_count` both 0."
    PRD §3.3: "Adding an item increments the schedule's `item_count` by 1 and advances the
    schedule's `version` by 1."

    Design: Corner/entities/price_schedule_item_system_fields_are_minted_by_server_and_client_id_is_ignored_input
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")
    wholesaler = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Distributing"
    )
    _agent, agent_headers = new_filing_agent(wholesaler["id"], "Fay Filer")
    brand = new_brand(
        wholesaler["id"],
        agent_headers,
        approve=True,
        brand_name="Rio Reserve",
        supplier_name="Rio Supply Co",
        beverage_class="SPIRITS",
        registration_effective_from="2026-01-01T00:00:00Z",
        registration_expires_on="2027-12-31T23:59:59Z",
    )
    schedule = new_schedule(
        wholesaler["id"], program["id"], agent_headers, posting_month="2026-09"
    )
    version_before = schedule["version"]

    response = api.create_price_schedule_item(
        {
            "schedule_id": schedule["id"],
            "brand_id": brand["id"],
            "size_ml": 750,
            "bottles_per_case": 12,
            "case_price_cents": 120000,
            "unit_price_cents": 11000,
            "id": "11111111-1111-1111-1111-111111111111",
            "created_at": "2001-01-01T00:00:00Z",
            "version": 77,
            "status": "EFFECTIVE",
            "amendment_count": 4,
        },
        agent_headers,
    )
    data = validate_success(response, 201)
    assert_price_schedule_item(data)

    assert data["id"] != "11111111-1111-1111-1111-111111111111", (
        "the id is server-minted with no client influence"
    )
    assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
        "created_at is stamped from the logical clock, not from the body"
    )
    assert data["version"] == 1, "a newly created record has version 1"
    assert data["status"] == "DRAFT", "a new item begins in DRAFT"
    assert data["amendment_count"] == 0, "a new item begins with amendment_count 0"
    assert data["correction_count"] == 0, "a new item begins with correction_count 0"
    assert data.get("certified_case_price_cents") is None, (
        "certified_case_price_cents is unset until certification"
    )
    assert data.get("certified_unit_price_cents") is None, (
        "certified_unit_price_cents is unset until certification"
    )
    assert data.get("supersedes_item_id") is None, "supersedes_item_id is unset on a new item"

    parent = read_schedule(schedule["id"])
    assert parent["item_count"] == 1, "adding an item increments the schedule's item_count by 1"
    assert parent["version"] == version_before + 1, (
        "adding an item advances the schedule's version by 1"
    )


# ---------------------------------------------------------------------------
# Retrieval, listing and not-found
# ---------------------------------------------------------------------------

def test_09_wholesaler_reads_back_with_every_penalty_bucket_and_counter_at_zero(api):
    """PRD §3.1: "All twelve of a wholesaler's derived numbers — the four penalty buckets,
    `penalty_exposure_cents`, `late_filing_count`, `frivolous_amendment_count`,
    `off_posted_violation_count` and `open_audit_count` — start at 0 and are never set
    directly by any client."
    PRD §3.1: "Its `license_status` is optional on input and defaults to `ACTIVE`; the only
    other permitted value is `SUSPENDED`."

    Design: Corner/entities/wholesaler_retrieval_returns_stored_fields_with_every_penalty_counter_zeroed
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")
    wholesaler = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Distributing"
    )
    _agent, agent_headers = new_filing_agent(wholesaler["id"], "Fay Filer")

    data = validate_success(api.get_wholesaler(wholesaler["id"], agent_headers), 200)
    assert_wholesaler(data)

    assert data["license_number"] == "W-1001", "license_number reads back as supplied"
    assert data["legal_name"] == "Lone Star Distributing", "legal_name reads back as supplied"
    assert data["state_program_id"] == program["id"], (
        "state_program_id reads back as supplied"
    )
    assert data["license_status"] == "ACTIVE", "license_status defaults to ACTIVE"

    for field in (
        "late_filing_penalty_accrued_cents",
        "correction_penalty_accrued_cents",
        "amendment_penalty_accrued_cents",
        "assessed_penalty_cents",
        "penalty_exposure_cents",
        "late_filing_count",
        "frivolous_amendment_count",
        "off_posted_violation_count",
        "open_audit_count",
    ):
        assert data[field] == 0, f"{field} must start at 0 on registration"

    assert data["version"] == 1, "a newly created record has version 1"


def test_10_licensee_user_listing_reports_unpaginated_total_count_and_has_more(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in
    the `meta` object, where `total_count` is the number of records matching the filters
    before the pagination window is applied and `has_more` is `true` exactly when the sum
    of `offset` and the number of records returned is less than `total_count`."
    PRD §2.3: "`limit` is the maximum number of records to return; when omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted value is
    100."

    Design: Corner/entities/licensee_user_listing_paginates_with_total_count_and_has_more
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")
    wholesaler = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Distributing"
    )
    agent = new_licensee_user(wholesaler["id"], "FILING_AGENT", full_name="Fay Filer")
    certifier = new_licensee_user(
        wholesaler["id"], "CERTIFYING_OFFICER", full_name="Cora Certifier"
    )
    dual = new_licensee_user(wholesaler["id"], "DUAL_ROLE", full_name="Dana Dual")

    first_response = api.list_licensee_users(
        regulator_headers(),
        params={"wholesaler_id": wholesaler["id"], "limit": 2, "offset": 0},
    )
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", (
        "a list endpoint returns response_type array"
    )
    assert len(first_page) == 2, "the first page of limit 2 must carry exactly 2 records"
    assert first_meta["total_count"] == 3, "total_count is the unpaginated count"
    assert first_meta["has_more"] is True, (
        "has_more is true when offset plus returned records is below total_count"
    )
    assert first_meta["limit"] == 2, "meta echoes the requested limit"
    assert first_meta["offset"] == 0, "meta echoes the requested offset"

    second_response = api.list_licensee_users(
        regulator_headers(),
        params={"wholesaler_id": wholesaler["id"], "limit": 2, "offset": 2},
    )
    second_page, second_meta = validate_paginated(second_response)
    assert second_response.json()["response_type"] == "array", (
        "a list endpoint returns response_type array"
    )
    assert len(second_page) == 1, "the second page must carry the single remaining record"
    assert second_meta["total_count"] == 3, "total_count stays 3 on the second page"
    assert second_meta["has_more"] is False, "has_more is false once the window is exhausted"
    assert second_meta["limit"] == 2, "meta echoes the requested limit"
    assert second_meta["offset"] == 2, "meta echoes the requested offset"

    returned_ids = [record["id"] for record in first_page] + [
        record["id"] for record in second_page
    ]
    assert len(returned_ids) == len(set(returned_ids)), "no record may repeat across pages"
    assert set(returned_ids) == {agent["id"], certifier["id"], dual["id"]}, (
        "the two pages together return exactly the three registered licensee users"
    )

    filtered, filtered_meta = validate_paginated(
        api.list_licensee_users(
            regulator_headers(),
            params={"wholesaler_id": wholesaler["id"], "user_role": "DUAL_ROLE"},
        )
    )
    assert filtered_meta["total_count"] == 1, (
        "the user_role filter is an exact-equality match combined conjunctively"
    )
    assert filtered[0]["id"] == dual["id"], "the DUAL_ROLE filter returns the DUAL_ROLE user"


def test_11_price_schedule_item_path_id_that_resolves_to_nothing_returns_its_own_404(api):
    """PRD §2.10: "Every identifier appearing in the URL path exists, checked left to
    right, and the first identifier that does not resolve determines the error. The error
    is the not-found code of that identifier's entity type (404)."
    PRD §2.11: "That identifier is resolved before the body is parsed, and the not-found
    code that is returned identifies the entity type of the segment:
    `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_WHOLESALER_NOT_FOUND`,
    `ERR_LICENSEE_USER_NOT_FOUND`, `ERR_BRAND_NOT_FOUND`, `ERR_PRICE_SCHEDULE_NOT_FOUND`,
    `ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND`, `ERR_QUANTITY_DISCOUNT_TIER_NOT_FOUND`,
    `ERR_COMBINATION_SALE_NOT_FOUND`, `ERR_HOLD_AMENDMENT_NOT_FOUND`,
    `ERR_ERROR_CORRECTION_NOT_FOUND`, `ERR_RETAILER_INVOICE_NOT_FOUND`,
    `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_COMPLIANCE_AUDIT_NOT_FOUND` or
    `ERR_AUDIT_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_price_schedule_item_with_unknown_id_returns_not_found
    """
    set_clock(CLOCK_START)

    response = api.get_price_schedule_item(
        "99999999-9999-4999-8999-999999999999", regulator_headers()
    )
    validate_error(response, "ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND")
    assert response.json()["response_type"] == "error", "an error envelope is returned"


def test_12_audit_finding_is_immutable_and_carries_no_version_key(api):
    """PRD §2.5: "`AuditFinding` is the one exception. A finding is immutable once
    recorded, so it carries only `id`, `created_at` and its payload fields; it has no
    `updated_at` field and no `version` field at all, and neither key appears in an audit
    finding response body."
    PRD §3.9: "Each finding carries an `audit_id` pointing at this audit, an
    `invoice_line_id` pointing at the line that produced it, a `finding_type` classifying
    the condition, a `variance_cents` equal to that line's `finding_variance_cents`, and a
    `penalty_component_cents`."
    PRD §3.9: "The `finding_type` is chosen by the first matching clause of this sequence:
    `UNPOSTED_BRAND` when no posted price could be resolved for the line's item as of the
    invoice date; otherwise `OFF_POSTED_UNDERCHARGE` when the line's `variance_cents` is
    greater than 0; otherwise `OFF_POSTED_OVERCHARGE` when the line's `variance_cents` is
    less than 0; otherwise `EXCESS_PROMOTIONAL_ALLOWANCE` when the line's
    `excess_promotional_cents` is greater than 0; otherwise
    `EXCESS_DEPLETION_ALLOWANCE`."
    PRD §3.9: "Each finding's `penalty_component_cents` is that finding's `variance_cents`
    multiplied by the program's `off_posted_penalty_rate_pct` — with the default rate, two
    fifths of the variance — rounded half up to whole cents."

    Design: Corner/entities/audit_finding_is_immutable_with_no_version_field_and_no_write_endpoint
    """
    scene = setup_effective_schedule(
        posting_month="2026-09",
        item_specs=[
            {
                "size_ml": 750,
                "bottles_per_case": 12,
                "case_price_cents": 120000,
                "unit_price_cents": 11000,
            }
        ],
        clock_before_run="2026-10-01T00:00:00Z",
    )
    setup_invoice_with_lines(
        scene,
        "2026-10-05T00:00:00Z",
        [
            {
                "item_id": scene["items"][0]["id"],
                "cases_quantity": 2,
                "case_price_charged_cents": 115000,
                "unit_price_charged_cents": 11000,
            }
        ],
        validate=True,
    )
    assert scene["invoice"]["validation_status"] == "FLAGGED", (
        "the undercharged line must flag the invoice so the audit has material to collect"
    )

    audit = new_audit(scene["wholesaler"]["id"], scene["program"]["id"], "2026-10")
    audit = collect_audit(audit["id"])

    findings, meta = validate_paginated(
        api.list_audit_findings(regulator_headers(), params={"audit_id": audit["id"]})
    )
    assert meta["total_count"] == 1, "collection records one finding per off-posted line"
    finding = findings[0]
    assert finding["audit_id"] == audit["id"], "the finding points at the collecting audit"
    assert finding["invoice_line_id"] == scene["lines"][0]["id"], (
        "the finding points at the line that produced it"
    )
    assert finding["finding_type"] == "OFF_POSTED_UNDERCHARGE", (
        "a positive variance_cents classifies the finding as OFF_POSTED_UNDERCHARGE"
    )
    assert finding["variance_cents"] == 10000, (
        "variance_cents equals the line's finding_variance_cents"
    )
    assert finding["penalty_component_cents"] == 4000, (
        "penalty_component_cents is round half up of variance_cents times 0.40"
    )
    assert_audit_finding(finding)

    single = validate_success(
        api.get_audit_finding(finding["id"], scene["agent_headers"]), 200
    )
    assert single["id"] == finding["id"], "the single-record read returns the same finding"
    assert single["audit_id"] == finding["audit_id"], "audit_id matches the list payload"
    assert single["invoice_line_id"] == finding["invoice_line_id"], (
        "invoice_line_id matches the list payload"
    )
    assert single["finding_type"] == finding["finding_type"], (
        "finding_type matches the list payload"
    )
    assert single["variance_cents"] == finding["variance_cents"], (
        "variance_cents matches the list payload"
    )
    assert single["penalty_component_cents"] == finding["penalty_component_cents"], (
        "penalty_component_cents matches the list payload"
    )
    assert "updated_at" not in single, "an audit finding response carries no updated_at key"
    assert "version" not in single, "an audit finding response carries no version key"
    assert_audit_finding(single)
