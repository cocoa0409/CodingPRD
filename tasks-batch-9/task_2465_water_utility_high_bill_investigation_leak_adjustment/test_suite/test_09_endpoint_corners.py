"""The readable and actionable surface of the collections themselves.

Four shapes of endpoint behaviour are exercised here. A published tariff must
round-trip through create, single read, exact-match filter and page window
without losing a field. An action endpoint must both perform its side effect and
enforce its own precondition, so an ad-hoc payment moves the ledger while a
zero-amount payment is refused. A derived read must partition the append-only
log exactly, so the bill-scoped ledger view of a superseded bill nets to zero
while the account view still reconciles to the reported balance. A conditional
action must consult the logical clock, so a shutoff waits for its statutory
notice instant. And a create that establishes three references at once must
validate every one of them before writing anything.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    ApiErrorId,
    assertions,
    fixtures,
    make_customer_headers,
)
from test_helpers.factories import (
    account_payment_payload,
    payment_arrangement_payload,
    rate_schedule_payload,
)

# The thirteen tariff fields of the standard schedule, spelled out so the
# round-trip test compares against literals rather than against the payload it
# just sent.
STANDARD_TARIFF = {
    "base_charge_cents": 1200,
    "tier1_limit_gallons": 3000,
    "tier1_rate_cents_per_kgal": 350,
    "tier2_limit_gallons": 10000,
    "tier2_rate_cents_per_kgal": 520,
    "tier3_rate_cents_per_kgal": 890,
    "summer_surcharge_bp": 1500,
    "sewer_rate_cents_per_kgal": 610,
    "sewer_cap_gallons": 12000,
    "submeter_sewer_credit_cap_gallons": 8000,
    "admin_fee_cents": 1500,
    "admin_fee_waiver_threshold_cents": 10000,
}

LIFELINE_TARIFF = {
    "base_charge_cents": 600,
    "tier1_limit_gallons": 4000,
    "tier1_rate_cents_per_kgal": 240,
    "tier2_limit_gallons": 11000,
    "tier2_rate_cents_per_kgal": 400,
    "tier3_rate_cents_per_kgal": 700,
    "summer_surcharge_bp": 0,
    "sewer_rate_cents_per_kgal": 500,
    "sewer_cap_gallons": 10000,
    "submeter_sewer_credit_cap_gallons": 6000,
    "admin_fee_cents": 0,
    "admin_fee_waiver_threshold_cents": 0,
}


# ---------------------------------------------------------------------------
# State builders
# ---------------------------------------------------------------------------
def _two_tariffs(api):
    """Publish the standard tariff and then a cheaper lifeline tariff."""
    fixtures.set_clock(api)
    standard = validate_success(
        api.create_rate_schedule(
            rate_schedule_payload(code="RS-STD-2026"), ADMIN_HEADERS
        ),
        201,
    )
    lifeline = validate_success(
        api.create_rate_schedule(
            rate_schedule_payload(code="RS-LIFELINE-2026", **LIFELINE_TARIFF),
            ADMIN_HEADERS,
        ),
        201,
    )
    return standard, lifeline


def _billed_account(api, gallons=4000):
    """One SUMMER period, one master meter and one ISSUED bill for ``gallons``.

    With no earlier same-season history the bill carries no baseline, so the
    anomaly screen stays silent and the whole fiscal picture is the tariff
    applied to ``gallons``.
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api, code="RS-STD-2026")
    period = fixtures.create_billing_period(
        api,
        period_code="2025-06",
        start_date="2025-06-01",
        end_date="2025-06-30",
        season="SUMMER",
        rebilling_deadline_date="2026-12-31",
    )
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(
        api, account["id"], initial_register_value=100000
    )
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    end_read = fixtures.post_reading(api, meter["id"], "2025-06-30", 100000 + gallons)
    bill = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])
    bill = fixtures.issue_bill(api, bill["id"])
    return {
        "account_id": account["id"],
        "meter_id": meter["id"],
        "period_id": period["id"],
        "bill_id": bill["id"],
        "end_read_id": end_read["id"],
        "customer_headers": make_customer_headers(account["id"]),
    }


def _rebilled_bill(api):
    """A 4000-gallon bill restated down to 3000 gallons and then rebilled."""
    ctx = _billed_account(api, gallons=4000)
    fixtures.post_corrected_reading(
        api, ctx["meter_id"], "2025-06-30", 103000, ctx["end_read_id"]
    )
    replacement = validate_success(
        api.rebill_bill(ctx["bill_id"], SUPERVISOR_HEADERS)
    )
    ctx["replacement_bill_id"] = replacement["id"]
    ctx["replacement_bill"] = replacement
    return ctx


def _investigated_high_bill(api):
    """The four-bill SUMMER chain with an OPEN investigation on the 41000-gallon bill."""
    ctx = fixtures.baselined_bill(api, target_gallons=41000)
    investigation = fixtures.open_investigation(api, ctx["bill_id"], CSR_HEADERS)
    ctx["investigation_id"] = investigation["id"]
    ctx["account_version"] = fixtures.account_version(api, ctx["account_id"])
    return ctx


# ---------------------------------------------------------------------------
# Rate schedules: create, read, filter, paginate
# ---------------------------------------------------------------------------
def test_rate_schedule_create_echoes_every_tariff_field_and_reads_back_identically(api):
    """PRD §4: "Successful resource creation returns HTTP 201; every other successful operation — retrievals, list operations, and the action endpoints that modify an existing resource — returns HTTP 200."

    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §2.4: "Most resources also carry three audit properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at 1 when the row is created and increments by one on every mutation of that row."

    Design: Corner/endpoints/corner_endpoint_standard_crud_rate_schedule_create_read_and_filtered_list
    """
    fixtures.set_clock(api)

    created = validate_success(
        api.create_rate_schedule(
            rate_schedule_payload(code="RS-STD-2026"), ADMIN_HEADERS
        ),
        201,
    )

    assertions.assert_fields(created, code="RS-STD-2026", version=1, **STANDARD_TARIFF)
    assert created["id"], "the server mints the identifier of a rate schedule"
    assert created["created_at"], "a rate schedule carries created_at"
    assert created["updated_at"], "a rate schedule carries updated_at"

    fetched = validate_success(api.get_rate_schedule(created["id"], SUPERVISOR_HEADERS))
    assertions.assert_fields(
        fetched,
        id=created["id"],
        code="RS-STD-2026",
        version=1,
        created_at=created["created_at"],
        updated_at=created["updated_at"],
        **STANDARD_TARIFF,
    )


def test_rate_schedule_listing_filters_on_code(api):
    """PRD §2.11: "Collections accept narrow, exact-match filters in addition to `limit` and `offset`. Rate schedules filter on `code`."

    PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/corner_endpoint_standard_crud_rate_schedule_create_read_and_filtered_list
    """
    _standard, lifeline = _two_tariffs(api)

    rows, meta = validate_paginated(
        api.list_rate_schedules(SUPERVISOR_HEADERS, {"code": "RS-LIFELINE-2026"})
    )

    assertions.assert_pagination_meta(meta, total_count=1, has_more=False)
    assertions.assert_listing_ids(rows, [lifeline["id"]])
    assertions.assert_fields(
        rows[0], code="RS-LIFELINE-2026", summer_surcharge_bp=0, admin_fee_cents=0
    )


def test_rate_schedule_listing_reports_the_rows_beyond_a_one_row_page(api):
    """PRD §2.3: "Every collection listing accepts `limit` and `offset` as query-string parameters."

    PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."
    PRD §2.3: "Unless a subsection below says otherwise, list endpoints sort by `created_at` ascending."

    Design: Corner/endpoints/corner_endpoint_standard_crud_rate_schedule_create_read_and_filtered_list
    """
    standard, lifeline = _two_tariffs(api)

    first_page, first_meta = validate_paginated(
        api.list_rate_schedules(SUPERVISOR_HEADERS, {"limit": 1, "offset": 0})
    )
    assertions.assert_pagination_meta(
        first_meta, limit=1, offset=0, total_count=2, has_more=True
    )
    assertions.assert_listing_ids(first_page, [standard["id"]])

    second_page, second_meta = validate_paginated(
        api.list_rate_schedules(SUPERVISOR_HEADERS, {"limit": 1, "offset": 1})
    )
    assertions.assert_pagination_meta(
        second_meta, limit=1, offset=1, total_count=2, has_more=False
    )
    assertions.assert_listing_ids(second_page, [lifeline["id"]])


# ---------------------------------------------------------------------------
# Account payments: the action and its own precondition
# ---------------------------------------------------------------------------
def test_zero_amount_account_payment_is_refused_and_moves_nothing(api):
    """PRD §3.8: "An ad-hoc account payment supplies an `amount_cents` that must be strictly positive, else `ERR_PAYMENT_AMOUNT_INVALID`, plus an optional `memo`; it writes a `PAYMENT` entry with `source_kind` `CUSTOMER_PAYMENT` for the negative amount, with `bill_id` and `source_id` both null and `effective_at` taken from the logical clock, and then recomputes `balance_cents`, `credit_status` and `service_status` in that order."

    Design: Corner/endpoints/corner_endpoint_action_endpoint_account_payment_posts_a_credit_and_guards_its_amount
    """
    ctx = _billed_account(api, gallons=4000)

    validate_error(
        api.record_account_payment(
            ctx["account_id"],
            account_payment_payload(0, memo="zero-value probe"),
            ctx["customer_headers"],
        ),
        ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID.value,
    )

    entries = assertions.ledger_entries(
        api, ctx["account_id"], ctx["customer_headers"]
    )
    assertions.assert_source_kinds(entries, ["BILL_CHARGE"])
    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account, balance_cents=5210, credit_status="PAST_DUE"
    )


def test_account_payment_writes_a_negative_customer_payment_entry_and_clears_past_due(api):
    """PRD §3.8: "An ad-hoc account payment supplies an `amount_cents` that must be strictly positive, else `ERR_PAYMENT_AMOUNT_INVALID`, plus an optional `memo`; it writes a `PAYMENT` entry with `source_kind` `CUSTOMER_PAYMENT` for the negative amount, with `bill_id` and `source_id` both null and `effective_at` taken from the logical clock, and then recomputes `balance_cents`, `credit_status` and `service_status` in that order."

    PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."
    PRD §2.11: "An account's ledger listing filters on `entry_type` and `source_kind`; a bill's ledger listing filters on `source_kind`."

    Design: Corner/endpoints/corner_endpoint_action_endpoint_account_payment_posts_a_credit_and_guards_its_amount
    """
    ctx = _billed_account(api, gallons=4000)

    # PRD §4 does not pin whether this nested write reports 200 or 201, so the
    # envelope is accepted on any 2xx and the asserted rule is the ledger row.
    get_success_data(
        api.record_account_payment(
            ctx["account_id"],
            account_payment_payload(3000, memo="partial payment on account"),
            ctx["customer_headers"],
        )
    )

    entries = assertions.ledger_entries(
        api, ctx["account_id"], ctx["customer_headers"]
    )
    assertions.assert_source_kinds(entries, ["BILL_CHARGE", "CUSTOMER_PAYMENT"])
    payment = assertions.assert_single_entry(
        entries,
        "CUSTOMER_PAYMENT",
        entry_type="PAYMENT",
        amount_cents=-3000,
        bill_id=None,
        source_id=None,
    )
    assert payment["effective_at"].startswith("2026-08-01T00:00:00"), (
        f"effective_at comes from the logical clock, got {payment['effective_at']!r}"
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        balance_cents=2210,
        credit_status="CURRENT",
        service_status="ACTIVE",
    )
    assertions.assert_balance_is_ledger_sum(account, entries)

    payments, meta = validate_paginated(
        api.list_account_ledger_entries(
            ctx["account_id"], ctx["customer_headers"], {"entry_type": "PAYMENT"}
        )
    )
    assertions.assert_pagination_meta(meta, total_count=1)
    assertions.assert_listing_ids(payments, [payment["id"]])


# ---------------------------------------------------------------------------
# The bill-scoped ledger view of a rebill
# ---------------------------------------------------------------------------
def test_superseded_bill_ledger_view_nets_to_zero_and_excludes_the_replacement(api):
    """PRD §3.5: "Two ledger entries land: a `REVERSAL` with `source_kind` `REBILL_REVERSAL` whose `amount_cents` is the negative of the sum of the superseded bill's `BILL_CHARGE` and `REBILL_CHARGE` entries, and then — from the replacement's auto-issue — a `CHARGE` with `source_kind` `REBILL_CHARGE` for the positive `total_charge_cents` of the replacement."

    PRD §2.8: "Nested reads exist in exactly two places — an account's ledger entries and a bill's ledger entries — and both are read-only projections of the append-only log."
    PRD §2.3: "A bill's ledger entries are returned by `created_at` ascending."

    Design: Corner/endpoints/corner_endpoint_computed_read_bill_scoped_ledger_view_reconciles_the_rebill
    """
    ctx = _rebilled_bill(api)

    rows, meta = validate_paginated(
        api.list_bill_ledger_entries(ctx["bill_id"], SUPERVISOR_HEADERS)
    )

    assertions.assert_pagination_meta(meta, total_count=2)
    assertions.assert_source_kinds(rows, ["BILL_CHARGE", "REBILL_REVERSAL"])
    assertions.assert_single_entry(
        rows, "BILL_CHARGE", entry_type="CHARGE", amount_cents=5210
    )
    assertions.assert_single_entry(
        rows, "REBILL_REVERSAL", entry_type="REVERSAL", amount_cents=-5210
    )
    assert sum(row["amount_cents"] for row in rows) == 0, (
        "the superseded bill's own view nets to zero once its charge is reversed"
    )
    assertions.assert_no_entry_of_kind(rows, "REBILL_CHARGE")

    replacement_rows, replacement_meta = validate_paginated(
        api.list_bill_ledger_entries(ctx["replacement_bill_id"], SUPERVISOR_HEADERS)
    )
    assertions.assert_pagination_meta(replacement_meta, total_count=1)
    assertions.assert_single_entry(
        replacement_rows, "REBILL_CHARGE", entry_type="CHARGE", amount_cents=4080
    )


def test_bill_ledger_view_narrows_by_source_kind_without_changing_the_amounts(api):
    """PRD §2.11: "An account's ledger listing filters on `entry_type` and `source_kind`; a bill's ledger listing filters on `source_kind`."

    PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/corner_endpoint_computed_read_bill_scoped_ledger_view_reconciles_the_rebill
    """
    ctx = _rebilled_bill(api)

    rows, meta = validate_paginated(
        api.list_bill_ledger_entries(
            ctx["bill_id"], SUPERVISOR_HEADERS, {"source_kind": "REBILL_REVERSAL"}
        )
    )

    assertions.assert_pagination_meta(meta, total_count=1, has_more=False)
    assertions.assert_source_kinds(rows, ["REBILL_REVERSAL"])
    assertions.assert_fields(rows[0], entry_type="REVERSAL", amount_cents=-5210)

    charge_rows, charge_meta = validate_paginated(
        api.list_bill_ledger_entries(
            ctx["bill_id"], SUPERVISOR_HEADERS, {"source_kind": "BILL_CHARGE"}
        )
    )
    assertions.assert_pagination_meta(charge_meta, total_count=1, has_more=False)
    assertions.assert_fields(charge_rows[0], entry_type="CHARGE", amount_cents=5210)


def test_account_ledger_view_holds_all_three_rebill_rows_and_matches_the_balance(api):
    """PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    PRD §2.3: "Two collections carry a domain-specific ordering instead: an account's ledger entries are returned oldest-first by `effective_at` ascending with `created_at` ascending as the tie-break, and meter readings are returned by `read_date` ascending with `created_at` ascending as the tie-break."
    PRD §2.11: "Bills filter on `account_id`, `period_id`, `meter_id`, `billing_status`, `anomaly_flag` and `rebill_of_bill_id`, the last of which surfaces the replacement generated from a superseded bill."

    Design: Corner/endpoints/corner_endpoint_computed_read_bill_scoped_ledger_view_reconciles_the_rebill
    """
    ctx = _rebilled_bill(api)

    rows, meta = validate_paginated(
        api.list_account_ledger_entries(ctx["account_id"], SUPERVISOR_HEADERS)
    )

    assertions.assert_pagination_meta(meta, total_count=3)
    assertions.assert_source_kinds(
        rows, ["BILL_CHARGE", "REBILL_REVERSAL", "REBILL_CHARGE"]
    )
    assert sum(row["amount_cents"] for row in rows) == 4080, (
        "the three rows replay to the charge of the replacement bill alone"
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=4080)
    assertions.assert_balance_is_ledger_sum(account, rows)

    replacements, replacement_meta = validate_paginated(
        api.list_bills(SUPERVISOR_HEADERS, {"rebill_of_bill_id": ctx["bill_id"]})
    )
    assertions.assert_pagination_meta(replacement_meta, total_count=1)
    assertions.assert_listing_ids(replacements, [ctx["replacement_bill_id"]])
    assertions.assert_fields(
        replacements[0],
        total_charge_cents=4080,
        billing_status="ISSUED",
        consumption_gallons=3000,
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="REBILLED"
    )


# ---------------------------------------------------------------------------
# Executing a shutoff: the statutory notice instant
# ---------------------------------------------------------------------------
def test_execute_shutoff_before_the_notice_instant_is_refused(api):
    """PRD §3.8: "The current logical-clock instant must be at or after `shutoff_scheduled_for`, else `ERR_SHUTOFF_NOTICE_NOT_ELAPSED`."

    PRD §3.8: "Scheduling sets `shutoff_scheduled_for` to the current logical-clock instant plus a ten-calendar-day statutory notice and moves `service_status` to `SHUTOFF_SCHEDULED`."

    Design: Corner/endpoints/corner_endpoint_conditional_action_execute_shutoff_waits_for_the_notice_period
    """
    ctx = _billed_account(api, gallons=4000)
    scheduled = validate_success(
        api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS)
    )
    assertions.assert_account_state(
        scheduled,
        service_status="SHUTOFF_SCHEDULED",
        credit_status="PAST_DUE",
        open_investigation_hold_count=0,
        open_rebill_count=0,
    )
    assert scheduled["shutoff_scheduled_for"].startswith("2026-08-11T00:00:00"), (
        "ten calendar days after 2026-08-01 is 2026-08-11, "
        f"got {scheduled['shutoff_scheduled_for']!r}"
    )

    fixtures.set_clock(api, "2026-08-10T23:00:00Z")
    validate_error(
        api.execute_shutoff(ctx["account_id"], SUPERVISOR_HEADERS),
        ApiErrorId.ERR_SHUTOFF_NOTICE_NOT_ELAPSED.value,
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, service_status="SHUTOFF_SCHEDULED")
    assert account["shutoff_scheduled_for"].startswith("2026-08-11T00:00:00"), (
        "a refused execution leaves the notice anchor untouched"
    )


def test_execute_shutoff_at_the_notice_instant_succeeds_and_moves_no_money(api):
    """PRD §3.8: "The current logical-clock instant must be at or after `shutoff_scheduled_for`, else `ERR_SHUTOFF_NOTICE_NOT_ELAPSED`."

    PRD §3.8: "Execution moves `service_status` to `SHUTOFF_EXECUTED` and clears `shutoff_scheduled_for` to null."
    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    Design: Corner/endpoints/corner_endpoint_conditional_action_execute_shutoff_waits_for_the_notice_period
    """
    ctx = _billed_account(api, gallons=4000)
    validate_success(api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS))

    fixtures.set_clock(api, "2026-08-11T00:00:00Z")
    executed = validate_success(
        api.execute_shutoff(ctx["account_id"], SUPERVISOR_HEADERS)
    )

    assertions.assert_account_state(
        executed,
        service_status="SHUTOFF_EXECUTED",
        credit_status="PAST_DUE",
        balance_cents=5210,
    )
    assertions.assert_null_fields(executed, "shutoff_scheduled_for")

    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_source_kinds(entries, ["BILL_CHARGE"])
    assertions.assert_balance_is_ledger_sum(
        fixtures.fetch_account(api, ctx["account_id"]), entries
    )


# ---------------------------------------------------------------------------
# Payment arrangements: three references established by one create
# ---------------------------------------------------------------------------
def test_unknown_optional_investigation_reference_is_refused_and_leaves_the_version_usable(api):
    """PRD §2.7: "Every identifier supplied in a payload must resolve, checked in the order the fields appear in that operation's input list, reporting the matching not-found code above (404)."

    PRD §2.8: "Where a payload carries several references, the order of the operation's declared input list decides which not-found code surfaces first: bill generation resolves the account, then the period, then the meter; meter-test requesting resolves the investigation, then the meter; leak-adjustment drafting resolves the investigation, then the bill; arrangement proposal resolves the account, then the bill, then the optional investigation."
    PRD §2.4: "Any operation that changes a row refreshes its `updated_at` and increments its `version`, including changes made as a downstream side effect of an operation aimed at a different resource."

    Design: Corner/endpoints/corner_endpoint_cross_reference_link_arrangement_binds_account_bill_and_investigation
    """
    ctx = _investigated_high_bill(api)
    observed_version = ctx["account_version"]

    validate_error(
        api.create_payment_arrangement(
            payment_arrangement_payload(
                ctx["account_id"],
                ctx["bill_id"],
                44939,
                9000,
                12,
                observed_version,
                investigation_id=NON_EXISTENT_UUID,
            ),
            CSR_HEADERS,
        ),
        ApiErrorId.ERR_INVESTIGATION_NOT_FOUND.value,
    )

    _rows, meta = validate_paginated(
        api.list_payment_arrangements(CSR_HEADERS, {"account_id": ctx["account_id"]})
    )
    assertions.assert_pagination_meta(meta, total_count=0)
    assert fixtures.account_version(api, ctx["account_id"]) == observed_version, (
        "a refused proposal mutates no row and therefore does not move the version"
    )

    accepted = validate_success(
        api.create_payment_arrangement(
            payment_arrangement_payload(
                ctx["account_id"],
                ctx["bill_id"],
                44939,
                9000,
                12,
                observed_version,
                investigation_id=ctx["investigation_id"],
            ),
            CSR_HEADERS,
        ),
        201,
    )
    assertions.assert_fields(accepted, status="PROPOSED")


def test_payment_arrangement_echoes_all_three_references_and_floors_the_schedule(api):
    """PRD §3.8: "`installment_cents` is the financed amount divided by `installment_count`, taking the floor — the largest whole number of cents not exceeding the quotient — and it applies to every instalment from the first through the second-to-last."

    PRD §3.8: "The remainder is the financed amount minus `installment_cents` multiplied by `installment_count`, and `final_installment_cents` is `installment_cents` plus that entire remainder."
    PRD §3.8: "A new plan opens in `PROPOSED` with `paid_installment_count`, `missed_payment_count` and `reinstatement_count` all zero, and any other arrangement on the same account sitting in `PROPOSED` or `ACTIVE` is moved to the terminal `CANCELLED`, which stops it counting toward the account's `credit_status` and therefore triggers a recompute."

    Design: Corner/endpoints/corner_endpoint_cross_reference_link_arrangement_binds_account_bill_and_investigation
    """
    ctx = _investigated_high_bill(api)

    arrangement = validate_success(
        api.create_payment_arrangement(
            payment_arrangement_payload(
                ctx["account_id"],
                ctx["bill_id"],
                44939,
                9000,
                12,
                ctx["account_version"],
                investigation_id=ctx["investigation_id"],
            ),
            CSR_HEADERS,
        ),
        201,
    )

    assertions.assert_fields(
        arrangement,
        account_id=ctx["account_id"],
        bill_id=ctx["bill_id"],
        investigation_id=ctx["investigation_id"],
        total_amount_cents=44939,
        down_payment_cents=9000,
        installment_count=12,
        installment_cents=2994,
        final_installment_cents=3005,
        status="PROPOSED",
        paid_installment_count=0,
        missed_payment_count=0,
        reinstatement_count=0,
    )
    assert 2994 * 11 + 3005 == 44939 - 9000, (
        "the floored instalments plus the final instalment reconcile to the financed amount"
    )

    stored = fixtures.fetch_arrangement(api, arrangement["id"])
    assertions.assert_fields(
        stored,
        investigation_id=ctx["investigation_id"],
        installment_cents=2994,
        final_installment_cents=3005,
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=60569)
    assertions.assert_balance_is_ledger_sum(
        account, assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    )


def test_payment_arrangement_is_queryable_from_each_of_its_references(api):
    """PRD §2.11: "Payment arrangements filter on `account_id`, `bill_id`, `investigation_id` and `status`."

    PRD §2.11: "Collections accept narrow, exact-match filters in addition to `limit` and `offset`."

    Design: Corner/endpoints/corner_endpoint_cross_reference_link_arrangement_binds_account_bill_and_investigation
    """
    ctx = _investigated_high_bill(api)
    arrangement = validate_success(
        api.create_payment_arrangement(
            payment_arrangement_payload(
                ctx["account_id"],
                ctx["bill_id"],
                44939,
                9000,
                12,
                ctx["account_version"],
                investigation_id=ctx["investigation_id"],
            ),
            CSR_HEADERS,
        ),
        201,
    )

    for params in (
        {"investigation_id": ctx["investigation_id"]},
        {"bill_id": ctx["bill_id"]},
        {"account_id": ctx["account_id"], "status": "PROPOSED"},
    ):
        rows, meta = validate_paginated(
            api.list_payment_arrangements(CSR_HEADERS, params)
        )
        assertions.assert_pagination_meta(meta, total_count=1, has_more=False)
        assertions.assert_listing_ids(rows, [arrangement["id"]])

    _rows, empty_meta = validate_paginated(
        api.list_payment_arrangements(
            CSR_HEADERS, {"account_id": ctx["account_id"], "status": "ACTIVE"}
        )
    )
    assertions.assert_pagination_meta(empty_meta, total_count=0)
