"""Entity contract corners of the water-utility high-bill service.

These tests pin the shape of the persisted estate rather than any workflow: what
a create echoes back and what it seeds, what a read returns, how a collection
listing reports its window, which not-found code names which entity, which
fields are required, which defaults are declared rather than supplied, which
money fields are derived from the register instead of the request body, which
audit fields the server mints, which schema bounds are enforced, why a ledger
entry can never be edited, how meter parentage is scoped to one account, and in
what order body references are resolved.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    assertions,
    constants,
    factories,
    fixtures,
)

UNKNOWN_INVESTIGATION_ID = "00000000-0000-0000-0000-0000000ffff1"
UNKNOWN_BILL_ID = "00000000-0000-0000-0000-0000000ffff2"
UNKNOWN_ADJUSTMENT_ID = "00000000-0000-0000-0000-0000000ffff3"
UNKNOWN_RATE_SCHEDULE_ID = "00000000-0000-0000-0000-0000000fffe1"
UNKNOWN_ACCOUNT_ID = "00000000-0000-0000-0000-0000000fffe2"
UNKNOWN_READING_ID = "00000000-0000-0000-0000-0000000fffe3"
UNKNOWN_METER_ID = "00000000-0000-0000-0000-0000000fffe4"

JUNE_PERIOD = {
    "period_code": "2025-06",
    "start_date": "2025-06-01",
    "end_date": "2025-06-30",
    "season": "SUMMER",
    "rebilling_deadline_date": "2026-12-31",
}
JULY_PERIOD = {
    "period_code": "2025-07",
    "start_date": "2025-07-01",
    "end_date": "2025-07-31",
    "season": "SUMMER",
    "rebilling_deadline_date": "2026-12-31",
}

JUNE_WATER, JUNE_SEWER, JUNE_TOTAL = constants.PINNED_CHARGES[("SUMMER", 4000)]
JULY_WATER, JULY_SEWER, JULY_TOTAL = constants.PINNED_CHARGES[("SUMMER", 8000)]


def _june_metered_account(api):
    """A rate schedule, the June 2025 period, an account and its master meter."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(api, **JUNE_PERIOD)
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(
        api, account["id"], initial_register_value=100000
    )
    return schedule, period, account, meter


# ===========================================================================
# Creating a service account
# ===========================================================================
def test_service_account_create_echoes_its_declared_inputs(api):
    """PRD §3.1: "A service account is registered with an `account_number` unique across all accounts, a `customer_name` naming the account holder of record, a `service_address` describing the premise served, and a `rate_schedule_id` naming the schedule that will price every one of its bills."

    PRD §4: "Successful resource creation returns HTTP 201; every other successful operation — retrievals, list operations, and the action endpoints that modify an existing resource — returns HTTP 200."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/corner_entity_creation_service_account_echoes_input_and_seeds_state
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)

    response = api.create_service_account(
        factories.service_account_payload(
            schedule["id"],
            account_number="ACC-2001",
            customer_name="Ines Bakke",
            service_address="4 Willow Ct",
        ),
        CSR_HEADERS,
    )
    account = validate_success(response, expected_status=201)

    assertions.assert_fields(
        account,
        account_number="ACC-2001",
        customer_name="Ines Bakke",
        service_address="4 Willow Ct",
        rate_schedule_id=schedule["id"],
    )

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]

    stored = validate_success(api.get_service_account(account["id"], CSR_HEADERS))
    assertions.assert_fields(
        stored,
        account_number="ACC-2001",
        customer_name="Ines Bakke",
        service_address="4 Willow Ct",
        rate_schedule_id=schedule["id"],
    )


def test_new_service_account_seeds_clean_derived_state(api):
    """PRD §3.1: "A fresh account starts fully clean: `service_status` is `ACTIVE`, `credit_status` is `CURRENT`, `balance_cents` is zero, both `open_investigation_hold_count` and `open_rebill_count` are zero, and `shutoff_scheduled_for` is null."

    PRD §2.4: "Most resources also carry three audit properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at 1 when the row is created and increments by one on every mutation of that row."

    Design: Corner/entities/corner_entity_creation_service_account_echoes_input_and_seeds_state
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)

    account = validate_success(
        api.create_service_account(
            factories.service_account_payload(
                schedule["id"],
                account_number="ACC-2001",
                customer_name="Ines Bakke",
                service_address="4 Willow Ct",
            ),
            CSR_HEADERS,
        ),
        expected_status=201,
    )

    assertions.assert_account_state(
        account,
        balance_cents=0,
        credit_status="CURRENT",
        service_status="ACTIVE",
        open_investigation_hold_count=0,
        open_rebill_count=0,
    )
    assertions.assert_null_fields(account, "shutoff_scheduled_for")
    assertions.assert_version(account, 1)
    for field in ("id", "created_at", "updated_at"):
        assert account.get(field), f"expected a non-null {field} on a fresh account"


# ===========================================================================
# Reading a bill back
# ===========================================================================
def test_bill_get_returns_the_persisted_charge_figures(api):
    """PRD §3.2: "`total_charge_cents` is `water_charge_cents` plus `sewer_charge_cents`, and at generation time `adjusted_total_cents` equals `total_charge_cents` because no credit has been posted."

    PRD §3.2: "`sewer_charge_cents` is `sewer_billable_gallons` multiplied by `sewer_rate_cents_per_kgal`, divided by one thousand, rounded half up once on that final product."
    PRD §3.2: "A newly generated bill sits in `DRAFT` with `rebill_of_bill_id` null and writes nothing to the ledger."

    Design: Corner/entities/corner_entity_retrieval_bill_get_returns_the_same_computed_charges
    """
    _schedule, period, account, meter = _june_metered_account(api)
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)

    created = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])
    fetched = validate_success(api.get_bill(created["id"], CSR_HEADERS))

    assertions.assert_fields(
        fetched,
        account_id=account["id"],
        period_id=period["id"],
        meter_id=meter["id"],
    )
    assertions.assert_bill_charges(
        fetched,
        consumption_gallons=4000,
        water_charge_cents=JUNE_WATER,
        sewer_charge_cents=JUNE_SEWER,
        total_charge_cents=JUNE_TOTAL,
        adjusted_total_cents=JUNE_TOTAL,
    )
    assertions.assert_fields(
        fetched,
        sewer_billable_gallons=4000,
        submeter_credit_gallons=0,
        billing_status="DRAFT",
    )
    assertions.assert_null_fields(fetched, "rebill_of_bill_id")
    assertions.assert_version(fetched, 1)

    for field in (
        "consumption_gallons",
        "water_charge_cents",
        "sewer_charge_cents",
        "total_charge_cents",
        "adjusted_total_cents",
        "sewer_billable_gallons",
        "submeter_credit_gallons",
    ):
        assert fetched[field] == created[field], (
            f"{field} drifted between create and read: "
            f"{created[field]!r} then {fetched[field]!r}"
        )


def test_bill_without_same_season_history_reports_null_baseline_fields(api):
    """PRD §3.2: "If fewer than three candidates exist, `seasonal_baseline_gallons` is null and `baseline_sample_count` records how many were found; otherwise `baseline_sample_count` is 3 and `seasonal_baseline_gallons` is the sum of the sample's `consumption_gallons` divided by three, rounded half up to a whole gallon."

    PRD §3.2: "When `seasonal_baseline_gallons` is null or zero, `anomaly_ratio` is null and `anomaly_flag` is false."

    Design: Corner/entities/corner_entity_retrieval_bill_get_returns_the_same_computed_charges
    """
    _schedule, period, account, meter = _june_metered_account(api)
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)

    bill = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])
    fetched = validate_success(api.get_bill(bill["id"], CSR_HEADERS))

    assertions.assert_null_fields(
        fetched, "seasonal_baseline_gallons", "anomaly_ratio"
    )
    assertions.assert_fields(fetched, baseline_sample_count=0, anomaly_flag=False)


# ===========================================================================
# Listing billing periods
# ===========================================================================
def _five_periods(api):
    """Five non-overlapping periods: four SUMMER and one WINTER."""
    fixtures.set_clock(api)
    specs = [
        {
            "period_code": "2025-01",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "season": "WINTER",
            "rebilling_deadline_date": "2026-12-31",
        },
        JUNE_PERIOD,
        JULY_PERIOD,
        {
            "period_code": "2025-08",
            "start_date": "2025-08-01",
            "end_date": "2025-08-31",
            "season": "SUMMER",
            "rebilling_deadline_date": "2026-12-31",
        },
        {
            "period_code": "2026-07",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "season": "SUMMER",
            "rebilling_deadline_date": "2027-01-31",
        },
    ]
    return [fixtures.create_billing_period(api, **spec) for spec in specs]


def test_billing_period_listing_windows_report_whole_set_total_count(api):
    """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100; `offset` defaults to 0 and has a minimum of 0."

    Design: Corner/entities/corner_entity_listing_billing_periods_pagination_total_count_and_has_more
    """
    _five_periods(api)

    first_response = api.list_billing_periods(ADMIN_HEADERS, {"limit": 2, "offset": 0})
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2
    assertions.assert_pagination_meta(
        first_meta, limit=2, offset=0, total_count=5, has_more=True
    )

    tail_rows, tail_meta = validate_paginated(
        api.list_billing_periods(ADMIN_HEADERS, {"limit": 2, "offset": 4})
    )
    assert len(tail_rows) == 1
    assertions.assert_pagination_meta(
        tail_meta, limit=2, offset=4, total_count=5, has_more=False
    )

    default_rows, default_meta = validate_paginated(
        api.list_billing_periods(ADMIN_HEADERS)
    )
    assert len(default_rows) == 5
    assertions.assert_pagination_meta(
        default_meta,
        limit=constants.DEFAULT_LIMIT,
        offset=constants.DEFAULT_OFFSET,
        total_count=5,
        has_more=False,
    )


def test_billing_period_season_filter_narrows_total_count(api):
    """PRD §2.11: "Billing periods filter on `season`, `status` and `period_code`."

    PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/corner_entity_listing_billing_periods_pagination_total_count_and_has_more
    """
    _five_periods(api)

    rows, meta = validate_paginated(
        api.list_billing_periods(
            ADMIN_HEADERS, {"season": "SUMMER", "limit": 2, "offset": 0}
        )
    )
    assert len(rows) == 2
    assert all(row["season"] == "SUMMER" for row in rows)
    assertions.assert_pagination_meta(
        meta, limit=2, offset=0, total_count=4, has_more=True
    )


# ===========================================================================
# Unknown path identifiers
# ===========================================================================
def test_unknown_path_ids_return_entity_specific_not_found_codes(api):
    """PRD §2.7: "**Path resource existence**, resolved left to right across the URL so the leftmost unresolvable identifier is the one reported → `ERR_RATE_SCHEDULE_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND`, `ERR_SERVICE_ACCOUNT_NOT_FOUND`, `ERR_METER_NOT_FOUND`, `ERR_METER_READING_NOT_FOUND`, `ERR_BILL_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_METER_TEST_REQUEST_NOT_FOUND`, `ERR_REPAIR_PROOF_NOT_FOUND`, `ERR_LEAK_ADJUSTMENT_NOT_FOUND`, `ERR_PAYMENT_ARRANGEMENT_NOT_FOUND` or `ERR_BOARD_APPEAL_NOT_FOUND`, all 404."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/corner_entity_not_found_unknown_path_ids_return_the_entity_specific_code
    """
    fixtures.set_clock(api)

    investigation_error = validate_error(
        api.get_investigation(UNKNOWN_INVESTIGATION_ID, CSR_HEADERS),
        "ERR_INVESTIGATION_NOT_FOUND",
    )
    bill_error = validate_error(
        api.get_bill(UNKNOWN_BILL_ID, SUPERVISOR_HEADERS),
        "ERR_BILL_NOT_FOUND",
    )
    adjustment_error = validate_error(
        api.get_leak_adjustment(UNKNOWN_ADJUSTMENT_ID, SUPERVISOR_HEADERS),
        "ERR_LEAK_ADJUSTMENT_NOT_FOUND",
    )

    for error in (investigation_error, bill_error, adjustment_error):
        assert error["message"].strip(), "every 404 must carry a human-readable message"


# ===========================================================================
# Required fields on meter registration
# ===========================================================================
def test_meter_registration_without_meter_serial_is_refused_and_creates_nothing(api):
    """PRD §2.7: "**Request schema.** Body and query parse; every required field present; every field of its declared type; every enum value drawn from its declared set; every integer inside its declared range; `limit` between 1 and 100 inclusive and `offset` at least 0 → otherwise `ERR_INVALID_REQUEST` (400)."

    PRD §3.1: "Meters are registered against an account with a `meter_serial` unique across the estate, a `meter_type`, a `size_inches` greater than zero, an `initial_register_value` of at least zero recording the cumulative register at installation, and — for devices that sit behind another meter — a `parent_meter_id`."

    Design: Corner/entities/corner_entity_required_fields_missing_meter_serial_returns_invalid_request
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    account = fixtures.create_account(api, schedule["id"])

    validate_error(
        api.create_meter(
            factories.master_meter_payload(
                account["id"], meter_serial=factories.OMIT
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_INVALID_REQUEST",
    )

    accepted = validate_success(
        api.create_meter(
            factories.master_meter_payload(account["id"], meter_serial="MTR-C-1"),
            TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        accepted, meter_serial="MTR-C-1", meter_type="POTABLE_MASTER"
    )

    rows, meta = validate_paginated(
        api.list_meters(TECHNICIAN_HEADERS, {"account_id": account["id"]})
    )
    assertions.assert_pagination_meta(meta, total_count=1)
    assertions.assert_listing_ids(rows, [accepted["id"]])


def test_meter_registration_without_account_id_fails_schema_before_reference_lookup(api):
    """PRD §2.7: "Checks are evaluated in a strict ascending order and the **first** violated check short-circuits the request; nothing after it runs."

    PRD §2.7: "**Request schema.** Body and query parse; every required field present; every field of its declared type; every enum value drawn from its declared set; every integer inside its declared range; `limit` between 1 and 100 inclusive and `offset` at least 0 → otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/corner_entity_required_fields_missing_meter_serial_returns_invalid_request
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    account = fixtures.create_account(api, schedule["id"])

    payload = factories.master_meter_payload(account["id"], meter_serial="MTR-C-1")
    payload.pop("account_id")
    validate_error(
        api.create_meter(payload, TECHNICIAN_HEADERS),
        "ERR_INVALID_REQUEST",
    )

    _rows, meta = validate_paginated(
        api.list_meters(TECHNICIAN_HEADERS, {"account_id": account["id"]})
    )
    assertions.assert_pagination_meta(meta, total_count=0)


# ===========================================================================
# Declared defaults
# ===========================================================================
def test_reference_estate_rows_take_their_declared_defaults(api):
    """PRD §2.10: "A `BillingPeriod` advances through exactly two transitions, both driven by a `SystemAdmin`, and its `status` starts at `OPEN`."

    PRD §3.1: "Every newly registered meter starts with `accuracy_status` set to `UNTESTED`, `accuracy_pct` null, `correction_factor` null and `last_test_completed_at` null."
    PRD §3.1: "Liveness is tracked by `superseded_by_reading_id`: a row whose `superseded_by_reading_id` is null is live, and posting a `CORRECTED` read sets that field on the row named by `corrects_reading_id` to the new row's identifier."
    PRD §3.1: "A `CORRECTED` read is exempt from that check because its whole purpose is to restate a figure downward or upward; in exchange it must name `corrects_reading_id`, the read it supersedes, and `corrects_reading_id` is forbidden on `ACTUAL` and `ESTIMATED` reads."

    Design: Corner/entities/corner_entity_defaults_omitted_optional_inputs_take_declared_defaults
    """
    _schedule, period, _account, meter = _june_metered_account(api)

    assertions.assert_fields(period, status="OPEN")

    assertions.assert_fields(meter, accuracy_status="UNTESTED")
    assertions.assert_null_fields(
        meter, "accuracy_pct", "correction_factor", "last_test_completed_at"
    )

    reading = fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)
    assertions.assert_null_fields(
        reading, "superseded_by_reading_id", "corrects_reading_id"
    )


def test_generated_bill_takes_its_declared_defaults(api):
    """PRD §3.2: "A newly generated bill sits in `DRAFT` with `rebill_of_bill_id` null and writes nothing to the ledger."

    PRD §3.2: "`estimated_flag` is set true exactly when the live period-end read for this bill has `read_type` of `ESTIMATED`; that single boolean later suppresses irrigation-submeter sewer relief, because an estimated master read cannot be reconciled against a submeter read."
    PRD §3.2: "The caller never supplies consumption or money: `consumption_gallons` is derived from the live `ACTUAL` or `CORRECTED` reads bounding the period and can never be negative."

    Design: Corner/entities/corner_entity_defaults_omitted_optional_inputs_take_declared_defaults
    """
    _schedule, period, account, meter = _june_metered_account(api)
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)

    bill = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])

    assertions.assert_fields(
        bill,
        billing_status="DRAFT",
        anomaly_flag=False,
        estimated_flag=False,
        consumption_gallons=4000,
    )
    assertions.assert_null_fields(bill, "rebill_of_bill_id")


# ===========================================================================
# Computed charge fields
# ===========================================================================
def test_bill_charges_follow_the_register_deltas_of_each_period(api):
    """PRD §3.2: "The caller never supplies consumption or money: `consumption_gallons` is derived from the live `ACTUAL` or `CORRECTED` reads bounding the period and can never be negative."

    PRD §3.2: "The first-tier volume is the lesser of `consumption_gallons` and `tier1_limit_gallons`."
    PRD §3.2: "Line one is the first-tier volume multiplied by `tier1_rate_cents_per_kgal`, divided by one thousand, rounded half up to whole cents."
    PRD §3.2: "If the bill's `estimated_flag` is true, or if every candidate submeter was ineligible, `submeter_credit_gallons` is zero; otherwise it is the lesser of the raw irrigation volume and `submeter_sewer_credit_cap_gallons`."

    Design: Corner/entities/corner_entity_computed_fields_charge_fields_derive_from_reads_not_from_the_body
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    june = fixtures.create_billing_period(api, **JUNE_PERIOD)
    july = fixtures.create_billing_period(api, **JULY_PERIOD)
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(
        api, account["id"], initial_register_value=100000
    )
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)
    fixtures.post_reading(api, meter["id"], "2025-07-31", 112000)

    june_bill = fixtures.generate_bill(api, account["id"], june["id"], meter["id"])
    july_bill = fixtures.generate_bill(api, account["id"], july["id"], meter["id"])

    assertions.assert_bill_charges(
        june_bill,
        consumption_gallons=4000,
        water_charge_cents=JUNE_WATER,
        sewer_charge_cents=JUNE_SEWER,
        total_charge_cents=JUNE_TOTAL,
        adjusted_total_cents=JUNE_TOTAL,
    )
    assertions.assert_fields(june_bill, sewer_billable_gallons=4000)

    assertions.assert_bill_charges(
        july_bill,
        consumption_gallons=8000,
        water_charge_cents=JULY_WATER,
        sewer_charge_cents=JULY_SEWER,
        total_charge_cents=JULY_TOTAL,
        adjusted_total_cents=JULY_TOTAL,
    )
    assertions.assert_fields(july_bill, sewer_billable_gallons=8000)

    for bill in (june_bill, july_bill):
        assertions.assert_fields(bill, submeter_credit_gallons=0)


# ===========================================================================
# Server-assigned fields on a bill
# ===========================================================================
def test_bill_due_date_anchors_on_the_period_end_not_the_clock(api):
    """PRD §3.2: "Issuing moves the bill from `DRAFT` to `ISSUED` and is permitted while the period is `OPEN` or `CLOSED`."

    PRD §3.2: "Issuing stamps `due_date` as the period's `end_date` plus twenty-one calendar days, inserts a `CHARGE` ledger entry with `source_kind` `BILL_CHARGE` for the positive `total_charge_cents`, naming this bill in both `bill_id` and `source_id`, and then recomputes the account's `balance_cents`, then its `credit_status`, then its `service_status`, in that order."

    Design: Corner/entities/corner_entity_system_fields_bill_due_date_and_version_are_server_assigned
    """
    _schedule, period, account, meter = _june_metered_account(api)
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)

    drafted = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])
    assertions.assert_fields(drafted, billing_status="DRAFT")
    assertions.assert_null_fields(drafted, "rebill_of_bill_id")

    issued = fixtures.issue_bill(api, drafted["id"])
    assertions.assert_fields(
        issued, billing_status="ISSUED", due_date="2025-07-21"
    )
    assertions.assert_null_fields(issued, "rebill_of_bill_id")

    reread = validate_success(api.get_bill(drafted["id"], SUPERVISOR_HEADERS))
    assertions.assert_fields(reread, due_date="2025-07-21", billing_status="ISSUED")


def test_bill_version_advances_and_only_issuing_moves_the_balance(api):
    """PRD §2.4: "Any operation that changes a row refreshes its `updated_at` and increments its `version`, including changes made as a downstream side effect of an operation aimed at a different resource."

    PRD §3.2: "A newly generated bill sits in `DRAFT` with `rebill_of_bill_id` null and writes nothing to the ledger."
    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    Design: Corner/entities/corner_entity_system_fields_bill_due_date_and_version_are_server_assigned
    """
    _schedule, period, account, meter = _june_metered_account(api)
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)

    drafted = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])
    assertions.assert_version(drafted, 1)
    before = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(before, balance_cents=0)

    issued = fixtures.issue_bill(api, drafted["id"])
    assertions.assert_version(issued, 2)
    assert issued["created_at"] == drafted["created_at"], (
        "issuing a bill must not restate its created_at"
    )

    after = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(after, balance_cents=JUNE_TOTAL)


# ===========================================================================
# Schema type and range constraints
# ===========================================================================
def test_out_of_set_enum_and_out_of_range_number_are_schema_failures(api):
    """PRD §2.7: "**Request schema.** Body and query parse; every required field present; every field of its declared type; every enum value drawn from its declared set; every integer inside its declared range; `limit` between 1 and 100 inclusive and `offset` at least 0 → otherwise `ERR_INVALID_REQUEST` (400)."

    PRD §3.1: "Meters are registered against an account with a `meter_serial` unique across the estate, a `meter_type`, a `size_inches` greater than zero, an `initial_register_value` of at least zero recording the cumulative register at installation, and — for devices that sit behind another meter — a `parent_meter_id`."

    Design: Corner/entities/corner_entity_type_constraints_bad_enum_and_out_of_range_numbers_rejected
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    account = fixtures.create_account(api, schedule["id"])

    september = {
        "period_code": "2025-09",
        "start_date": "2025-09-01",
        "end_date": "2025-09-30",
        "rebilling_deadline_date": "2027-03-31",
    }

    validate_error(
        api.create_billing_period(
            factories.billing_period_payload(season="AUTUMN", **september),
            ADMIN_HEADERS,
        ),
        "ERR_INVALID_REQUEST",
    )
    validate_error(
        api.create_meter(
            factories.master_meter_payload(account["id"], initial_register_value=-1),
            TECHNICIAN_HEADERS,
        ),
        "ERR_INVALID_REQUEST",
    )

    control = validate_success(
        api.create_billing_period(
            factories.billing_period_payload(season="SUMMER", **september),
            ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    assertions.assert_fields(control, season="SUMMER", period_code="2025-09")

    _rows, period_meta = validate_paginated(api.list_billing_periods(ADMIN_HEADERS))
    assertions.assert_pagination_meta(period_meta, total_count=1)

    _meters, meter_meta = validate_paginated(
        api.list_meters(TECHNICIAN_HEADERS, {"account_id": account["id"]})
    )
    assertions.assert_pagination_meta(meter_meta, total_count=0)


def test_pagination_limit_above_the_maximum_is_a_schema_failure(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a schema violation and returns `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_entity_type_constraints_bad_enum_and_out_of_range_numbers_rejected
    """
    fixtures.set_clock(api)

    validate_error(
        api.list_meters(
            TECHNICIAN_HEADERS, {"limit": constants.MAX_LIMIT + 1, "offset": 0}
        ),
        "ERR_INVALID_REQUEST",
    )

    _rows, meta = validate_paginated(
        api.list_meters(TECHNICIAN_HEADERS, {"limit": constants.MAX_LIMIT, "offset": 0})
    )
    assertions.assert_pagination_meta(meta, limit=constants.MAX_LIMIT, offset=0)


# ===========================================================================
# The append-only ledger
# ===========================================================================
def _issued_june_bill(api):
    """An account carrying one ISSUED 4000-gallon June bill."""
    _schedule, period, account, meter = _june_metered_account(api)
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)
    bill = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])
    fixtures.issue_bill(api, bill["id"])
    return account, bill


def test_ledger_entry_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "Ledger entries are append-only: once written they are never updated and never deleted, so they carry only `id` and `created_at`."

    PRD §2.4: "They have no `updated_at` and no `version` field at all."
    PRD §3.8: "An ad-hoc account payment supplies an `amount_cents` that must be strictly positive, else `ERR_PAYMENT_AMOUNT_INVALID`, plus an optional `memo`; it writes a `PAYMENT` entry with `source_kind` `CUSTOMER_PAYMENT` for the negative amount, with `bill_id` and `source_id` both null and `effective_at` taken from the logical clock, and then recomputes `balance_cents`, `credit_status` and `service_status` in that order."

    Design: Corner/entities/corner_entity_immutability_ledger_entry_carries_no_version_and_no_mutator
    """
    account, _bill = _issued_june_bill(api)

    entry = get_success_data(
        api.record_account_payment(
            account["id"],
            factories.account_payment_payload(2000, memo="partial payment"),
            CSR_HEADERS,
        )
    )

    assertions.assert_append_only_shape(entry)
    assertions.assert_fields(
        entry,
        entry_type="PAYMENT",
        source_kind="CUSTOMER_PAYMENT",
        amount_cents=-2000,
        account_id=account["id"],
    )
    assertions.assert_null_fields(entry, "bill_id", "source_id")
    assert entry["effective_at"], "a ledger entry must carry an effective_at instant"

    stored = assertions.ledger_entries(api, account["id"], CSR_HEADERS)
    payment = assertions.assert_single_entry(
        stored, "CUSTOMER_PAYMENT", amount_cents=-2000
    )
    assert payment["id"] == entry["id"]


def test_account_ledger_replays_the_balance_from_two_appended_rows(api):
    """PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    PRD §2.3: "Two collections carry a domain-specific ordering instead: an account's ledger entries are returned oldest-first by `effective_at` ascending with `created_at` ascending as the tie-break, and meter readings are returned by `read_date` ascending with `created_at` ascending as the tie-break."

    Design: Corner/entities/corner_entity_immutability_ledger_entry_carries_no_version_and_no_mutator
    """
    account, bill = _issued_june_bill(api)

    get_success_data(
        api.record_account_payment(
            account["id"],
            factories.account_payment_payload(2000, memo="partial payment"),
            CSR_HEADERS,
        )
    )

    entries = assertions.ledger_entries(api, account["id"], CSR_HEADERS)
    assert len(entries) == 2, f"expected exactly two ledger rows, got {len(entries)}"
    assertions.assert_source_kinds(entries, ["BILL_CHARGE", "CUSTOMER_PAYMENT"])
    assertions.assert_fields(
        entries[0], entry_type="CHARGE", amount_cents=JUNE_TOTAL, bill_id=bill["id"]
    )
    assertions.assert_fields(
        entries[1], entry_type="PAYMENT", amount_cents=-2000
    )
    for entry in entries:
        assertions.assert_append_only_shape(entry)

    refreshed = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(refreshed, balance_cents=JUNE_TOTAL - 2000)
    assertions.assert_balance_is_ledger_sum(refreshed, entries)


# ===========================================================================
# Meter parentage
# ===========================================================================
def _two_metered_accounts(api):
    """Two accounts on one schedule, each holding its own master meter."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    account_x = fixtures.create_account(api, schedule["id"])
    account_y = fixtures.create_account(api, schedule["id"])
    master_x = fixtures.create_master_meter(
        api, account_x["id"], size_inches=1.5, initial_register_value=200000
    )
    master_y = fixtures.create_master_meter(
        api, account_y["id"], size_inches=1.5, initial_register_value=300000
    )
    return account_x, account_y, master_x, master_y


def test_invalid_meter_parentage_is_refused_for_every_shape(api):
    """PRD §3.1: "Parentage is strict: a `POTABLE_MASTER` must be registered with no `parent_meter_id` at all, while an `IRRIGATION_SUBMETER` or a `BACKFLOW_FIRE_LINE` must supply one that points at a `POTABLE_MASTER` meter on the same account."

    PRD §3.1: "A payload that supplies a parent for a master, omits one for a submeter, or points at a meter that is not a master on the same account is refused with `ERR_SUBMETER_PARENT_INVALID`."

    Design: Corner/entities/corner_entity_parent_relationships_submeter_must_hang_off_a_master_on_the_same_account
    """
    account_x, _account_y, master_x, master_y = _two_metered_accounts(api)

    parentless = factories.submeter_payload(account_x["id"], master_x["id"])
    parentless.pop("parent_meter_id")
    validate_error(
        api.create_meter(parentless, TECHNICIAN_HEADERS),
        "ERR_SUBMETER_PARENT_INVALID",
    )
    validate_error(
        api.create_meter(
            factories.submeter_payload(account_x["id"], master_y["id"]),
            TECHNICIAN_HEADERS,
        ),
        "ERR_SUBMETER_PARENT_INVALID",
    )
    validate_error(
        api.create_meter(
            factories.master_meter_payload(
                account_x["id"], parent_meter_id=master_x["id"]
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_SUBMETER_PARENT_INVALID",
    )

    _children, child_meta = validate_paginated(
        api.list_meters(TECHNICIAN_HEADERS, {"parent_meter_id": master_x["id"]})
    )
    assertions.assert_pagination_meta(child_meta, total_count=0)

    rows, meta = validate_paginated(
        api.list_meters(TECHNICIAN_HEADERS, {"account_id": account_x["id"]})
    )
    assertions.assert_pagination_meta(meta, total_count=1)
    assertions.assert_listing_ids(rows, [master_x["id"]])


def test_submeter_behind_a_master_on_its_own_account_is_registered(api):
    """PRD §3.1: "Parentage is strict: a `POTABLE_MASTER` must be registered with no `parent_meter_id` at all, while an `IRRIGATION_SUBMETER` or a `BACKFLOW_FIRE_LINE` must supply one that points at a `POTABLE_MASTER` meter on the same account."

    PRD §2.11: "Meters filter on `account_id`, `parent_meter_id`, `meter_type` and `accuracy_status`."

    Design: Corner/entities/corner_entity_parent_relationships_submeter_must_hang_off_a_master_on_the_same_account
    """
    account_x, _account_y, master_x, _master_y = _two_metered_accounts(api)

    submeter = validate_success(
        api.create_meter(
            factories.submeter_payload(account_x["id"], master_x["id"]),
            TECHNICIAN_HEADERS,
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        submeter,
        parent_meter_id=master_x["id"],
        meter_type="IRRIGATION_SUBMETER",
        account_id=account_x["id"],
    )

    rows, meta = validate_paginated(
        api.list_meters(TECHNICIAN_HEADERS, {"parent_meter_id": master_x["id"]})
    )
    assertions.assert_pagination_meta(meta, total_count=1)
    assertions.assert_listing_ids(rows, [submeter["id"]])


# ===========================================================================
# Body reference resolution
# ===========================================================================
def _account_with_meter(api):
    """A rate schedule, one account and one master meter, with no reads posted."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(
        api, account["id"], initial_register_value=100000
    )
    return schedule, account, meter


def test_unresolvable_body_references_report_the_missing_entity(api):
    """PRD §2.7: "**Body reference existence.** Every identifier supplied in a payload must resolve, checked in the order the fields appear in that operation's input list, reporting the matching not-found code above (404)."

    PRD §2.7: "This tier governs account creation, meter registration, reading posting, bill generation, investigation opening, meter-test requesting, repair-proof submission, leak-adjustment drafting, arrangement proposal and appeal filing."

    Design: Corner/entities/corner_entity_foreign_key_integrity_body_fks_resolve_before_business_rules
    """
    _schedule, _account, meter = _account_with_meter(api)

    validate_error(
        api.create_service_account(
            factories.service_account_payload(UNKNOWN_RATE_SCHEDULE_ID),
            CSR_HEADERS,
        ),
        "ERR_RATE_SCHEDULE_NOT_FOUND",
    )
    validate_error(
        api.create_meter(
            factories.master_meter_payload(UNKNOWN_ACCOUNT_ID, initial_register_value=0),
            TECHNICIAN_HEADERS,
        ),
        "ERR_SERVICE_ACCOUNT_NOT_FOUND",
    )
    validate_error(
        api.create_meter_reading(
            factories.corrected_reading_payload(
                meter["id"], "2025-06-30", 104000, UNKNOWN_READING_ID
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_METER_READING_NOT_FOUND",
    )

    _accounts, account_meta = validate_paginated(
        api.list_service_accounts(CSR_HEADERS)
    )
    assertions.assert_pagination_meta(account_meta, total_count=1)


def test_body_reference_sweep_reports_the_first_field_in_the_input_list(api):
    """PRD §2.7: "**Body reference existence.** Every identifier supplied in a payload must resolve, checked in the order the fields appear in that operation's input list, reporting the matching not-found code above (404)."

    PRD §3.1: "A technician posts reads against a meter by supplying `meter_id`, a `read_date`, a `read_type` of `ACTUAL`, `ESTIMATED` or `CORRECTED`, and a cumulative `reading_value` of at least zero."

    Design: Corner/entities/corner_entity_foreign_key_integrity_body_fks_resolve_before_business_rules
    """
    _account_with_meter(api)

    validate_error(
        api.create_meter_reading(
            factories.corrected_reading_payload(
                UNKNOWN_METER_ID, "2025-06-30", 104000, UNKNOWN_READING_ID
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_METER_NOT_FOUND",
    )

    _readings, reading_meta = validate_paginated(
        api.list_meter_readings(TECHNICIAN_HEADERS)
    )
    assertions.assert_pagination_meta(reading_meta, total_count=0)
