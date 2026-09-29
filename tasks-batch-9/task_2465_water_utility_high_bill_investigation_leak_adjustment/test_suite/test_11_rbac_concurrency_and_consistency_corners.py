"""Role boundaries, interleaved version guards and immediate visibility.

Three concerns meet in this file. First, who may act: issuing a bill is the one
fiscal write reserved to the billing supervisor even though the administrator
may draft the bill, while opening an account is genuinely shared between the
administrator and the representative and the read surface is shaped differently
again from the write surface. Second, the account version token that guards an
instalment-plan proposal: expressed here as a strictly sequential interleaving
in which one client reads a version, a plan is created against it, and the same
token is then replayed. Third, immediate visibility: every derived figure a
write produces is already in that write's own response body, and every cascade
it fires is already on the very next read.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    assertions,
    constants,
    factories,
    fixtures,
    make_customer_headers,
    no_headers,
)

JUNE_PERIOD = {
    "period_code": "2025-06",
    "start_date": "2025-06-01",
    "end_date": "2025-06-30",
    "season": "SUMMER",
    "rebilling_deadline_date": "2026-12-31",
}

JUNE_WATER, JUNE_SEWER, JUNE_TOTAL = constants.PINNED_CHARGES[("SUMMER", 4000)]

# A 3900-gallon SUMMER period on the standard tariff: 1200 base, 3000 gallons of
# tier one at 350/kgal, 900 gallons of tier two at 520/kgal, no tier-three
# gallons and therefore no summer surcharge; sewer bills all 3900 gallons.
CORRECTED_GALLONS = 3900
CORRECTED_WATER = 2718
CORRECTED_SEWER = 2379
CORRECTED_TOTAL = 5097

DUE_DATE = "2025-07-21"
NOTICE_PREFIX = "2026-08-11"


def _june_estate(api):
    """A rate schedule, the June 2025 period, an account and its master meter."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(api, **JUNE_PERIOD)
    account = fixtures.create_account(
        api,
        schedule["id"],
        ADMIN_HEADERS,
        account_number="ACC-5011",
        customer_name="Rosa Iglesias",
        service_address="31 Magnolia Way",
    )
    meter = fixtures.create_master_meter(
        api,
        account["id"],
        TECHNICIAN_HEADERS,
        meter_serial="MTR-5L-1",
        initial_register_value=100000,
    )
    return schedule, period, account, meter


def _draft_june_bill(api):
    """A DRAFT 4000-gallon June bill created by the administrator."""
    schedule, period, account, meter = _june_estate(api)
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    reading = fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)
    bill = fixtures.generate_bill(
        api, account["id"], period["id"], meter["id"], headers=ADMIN_HEADERS
    )
    return period, account, meter, reading, bill


def _issued_june_bill(api):
    """The same June bill, issued by a supervisor and charged to the ledger."""
    period, account, meter, reading, bill = _draft_june_bill(api)
    fixtures.issue_bill(api, bill["id"], SUPERVISOR_HEADERS)
    return period, account, meter, reading, bill


def _assert_draft_is_inert(api, account_id, bill_id, expected_version):
    """A refused issue must leave the draft, its due date and the ledger alone."""
    bill = fixtures.fetch_bill(api, bill_id)
    assertions.assert_fields(bill, billing_status="DRAFT")
    assertions.assert_null_fields(bill, "due_date")
    assertions.assert_version(bill, expected_version)

    entries, meta = validate_paginated(
        api.list_account_ledger_entries(account_id, ADMIN_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 0, (
        f"a refused issue must write no ledger entry, found {meta['total_count']}"
    )
    assert entries == []

    account = fixtures.fetch_account(api, account_id)
    assertions.assert_account_state(
        account, balance_cents=0, credit_status="CURRENT", service_status="ACTIVE"
    )


# ===========================================================================
# Issuing a bill is exclusive to the billing supervisor
# ===========================================================================
def test_bill_issue_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request except the logical-clock endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capability set that principal is exercising."

    PRD §2.1: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.7: "A request that breaks several rules always reports the earliest one in this ladder, which is why the ladder itself is part of the contract rather than an implementation detail."

    Design: Corner/rbac/corner_rbac_exclusive_operation_only_a_billing_supervisor_may_issue_a_bill
    """
    _period, account, _meter, _reading, bill = _draft_june_bill(api)

    validate_error(
        api.issue_bill(bill["id"], no_headers()), "ERR_UNAUTHENTICATED"
    )

    _assert_draft_is_inert(api, account["id"], bill["id"], bill["version"])


def test_bill_issue_is_refused_for_every_staff_role_other_than_the_supervisor(api):
    """PRD §2.1: "If `X-User-Role` is not one of the six declared role names, or is a declared role that the target operation does not list, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    PRD §2.1: "A `SystemAdmin` owns the reference data — rate schedules and billing periods, including closing and locking a period — and may register accounts, meters, readings and bills, but may not issue or rebill a bill, may not touch any leak adjustment or investigation action, may not write repair proofs, arrangements or appeals, may not schedule, execute or record payments on an account, and may not read the adjustment preview."
    PRD §2.1: "A `CustomerServiceRep` runs the investigation itself: requesting evidence, determining the cause, closing without adjustment, verifying and rejecting repair proofs, and drafting and submitting leak adjustments; the rep may not approve, return, deny or reverse a credit, may not issue or rebill, may not post readings or drive meter tests, may not schedule or execute shutoffs, may not reinstate arrangements, and may not docket or decide appeals."
    PRD §2.1: "A `MeterTechnician` owns the physical estate: posting meter readings, scheduling field tests, recording field results and recording bench results, plus registering meters; the technician touches no bill, investigation, proof, adjustment, arrangement or appeal."
    PRD §2.1: "A `UtilityBoardClerk` dockets hearings and records board decisions but may not file an appeal — the clerk decides appeals, it does not bring them — and holds read access to investigations, repair proofs, leak adjustments and appeals only."

    Design: Corner/rbac/corner_rbac_exclusive_operation_only_a_billing_supervisor_may_issue_a_bill
    """
    _period, account, _meter, _reading, bill = _draft_june_bill(api)

    # The administrator drafted this very bill and still cannot issue it.
    for headers in (ADMIN_HEADERS, CSR_HEADERS, TECHNICIAN_HEADERS, CLERK_HEADERS):
        validate_error(api.issue_bill(bill["id"], headers), "ERR_FORBIDDEN_ROLE")

    _assert_draft_is_inert(api, account["id"], bill["id"], bill["version"])


def test_bill_issue_refuses_the_owning_customer_on_the_role_check(api):
    """PRD §2.1: "A `Customer` opens investigations, submits repair proofs, requests meter tests, files appeals, proposes, activates and pays down arrangements, records account payments, and reads their own records; every reference-data write, every bill action, every investigation action, every proof review, every leak-adjustment operation, every meter or reading write, every meter-test action, hearing docketing and decision recording, shutoff scheduling and execution, arrangement reinstatement, and the adjustment preview are all closed to them."

    PRD §2.7: "This is decided on the role string alone, before any body parsing, so a forbidden role sending a malformed body still receives 403 rather than 400."
    PRD §2.7: "This tier applies to every operation whose role list includes `Customer`."

    Design: Corner/rbac/corner_rbac_exclusive_operation_only_a_billing_supervisor_may_issue_a_bill
    """
    _period, account, _meter, _reading, bill = _draft_june_bill(api)

    # The ownership scope would in fact have been satisfied: the role check is
    # earlier in the ladder, so it is the role check that answers.
    validate_error(
        api.issue_bill(bill["id"], make_customer_headers(account["id"])),
        "ERR_FORBIDDEN_ROLE",
    )

    _assert_draft_is_inert(api, account["id"], bill["id"], bill["version"])


def test_billing_supervisor_issue_stamps_the_due_date_and_posts_the_charge(api):
    """PRD §2.1: "A `BillingSupervisor` issues and rebills bills, returns, approves, denies and reverses leak adjustments, schedules and executes shutoffs, and reinstates defaulted arrangements — but may never draft or submit a leak adjustment and may never record a determination, because the drafter and the approver are separated at the role level as well as at the user level."

    PRD §3.2: "Issuing stamps `due_date` as the period's `end_date` plus twenty-one calendar days, inserts a `CHARGE` ledger entry with `source_kind` `BILL_CHARGE` for the positive `total_charge_cents`, naming this bill in both `bill_id` and `source_id`, and then recomputes the account's `balance_cents`, then its `credit_status`, then its `service_status`, in that order."
    PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."

    Design: Corner/rbac/corner_rbac_exclusive_operation_only_a_billing_supervisor_may_issue_a_bill
    """
    _period, account, _meter, _reading, bill = _draft_june_bill(api)

    issued = validate_success(api.issue_bill(bill["id"], SUPERVISOR_HEADERS))

    assertions.assert_fields(
        issued,
        billing_status="ISSUED",
        due_date=DUE_DATE,
        total_charge_cents=JUNE_TOTAL,
    )

    entries = assertions.ledger_entries(api, account["id"], SUPERVISOR_HEADERS)
    assertions.assert_source_kinds(entries, ["BILL_CHARGE"])
    assertions.assert_single_entry(
        entries,
        "BILL_CHARGE",
        entry_type="CHARGE",
        amount_cents=JUNE_TOTAL,
        bill_id=bill["id"],
        source_id=bill["id"],
    )

    after = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(
        after, balance_cents=JUNE_TOTAL, credit_status="PAST_DUE"
    )
    assertions.assert_balance_is_ledger_sum(after, entries)


# ===========================================================================
# Opening an account is shared; the read surface is shaped differently
# ===========================================================================
def test_admin_and_rep_account_creates_produce_identical_default_state(api):
    """PRD §3.1: "A service account is registered with an `account_number` unique across all accounts, a `customer_name` naming the account holder of record, a `service_address` describing the premise served, and a `rate_schedule_id` naming the schedule that will price every one of its bills."

    PRD §3.1: "A fresh account starts fully clean: `service_status` is `ACTIVE`, `credit_status` is `CURRENT`, `balance_cents` is zero, both `open_investigation_hold_count` and `open_rebill_count` are zero, and `shutoff_scheduled_for` is null."
    PRD §2.4: "Most resources also carry three audit properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at 1 when the row is created and increments by one on every mutation of that row."

    Design: Corner/rbac/corner_rbac_shared_operation_admin_and_rep_both_open_accounts_but_a_technician_cannot
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)

    by_admin = validate_success(
        api.create_service_account(
            factories.service_account_payload(
                schedule["id"],
                account_number="ACC-5012",
                customer_name="Devi Nair",
                service_address="14 Hawthorn Lane",
            ),
            ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    by_rep = validate_success(
        api.create_service_account(
            factories.service_account_payload(
                schedule["id"],
                account_number="ACC-5013",
                customer_name="Piotr Zielinski",
                service_address="16 Hawthorn Lane",
            ),
            CSR_HEADERS,
        ),
        expected_status=201,
    )

    for account in (by_admin, by_rep):
        assertions.assert_fields(
            account,
            rate_schedule_id=schedule["id"],
            service_status="ACTIVE",
            credit_status="CURRENT",
            balance_cents=0,
            open_investigation_hold_count=0,
            open_rebill_count=0,
            version=1,
        )
        assertions.assert_null_fields(account, "shutoff_scheduled_for")

    # Nothing in the row records which of the two roles created it.
    assert sorted(by_admin) == sorted(by_rep), (
        "a shared create must produce one field set, not one per creator"
    )
    assert by_admin["id"] != by_rep["id"]


def test_account_creation_is_refused_for_a_meter_technician(api):
    """PRD §2.1: "A `MeterTechnician` owns the physical estate: posting meter readings, scheduling field tests, recording field results and recording bench results, plus registering meters; the technician touches no bill, investigation, proof, adjustment, arrangement or appeal."

    PRD §2.1: "If `X-User-Role` is not one of the six declared role names, or is a declared role that the target operation does not list, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.11: "Service accounts filter on `rate_schedule_id`, `account_number` and on either state dimension independently via `service_status` and `credit_status`."

    Design: Corner/rbac/corner_rbac_shared_operation_admin_and_rep_both_open_accounts_but_a_technician_cannot
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)

    validate_error(
        api.create_service_account(
            factories.service_account_payload(
                schedule["id"],
                account_number="ACC-5014",
                customer_name="Hana Suzuki",
                service_address="18 Hawthorn Lane",
            ),
            TECHNICIAN_HEADERS,
        ),
        "ERR_FORBIDDEN_ROLE",
    )

    rows, meta = validate_paginated(
        api.list_service_accounts(ADMIN_HEADERS, {"account_number": "ACC-5014"})
    )
    assert meta["total_count"] == 0, (
        f"the refused create must persist nothing, found {meta['total_count']}"
    )
    assert rows == []


def test_billing_supervisor_lists_the_accounts_it_may_not_create(api):
    """PRD §2.1: "A `BillingSupervisor` issues and rebills bills, returns, approves, denies and reverses leak adjustments, schedules and executes shutoffs, and reinstates defaulted arrangements — but may never draft or submit a leak adjustment and may never record a determination, because the drafter and the approver are separated at the role level as well as at the user level."

    PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/rbac/corner_rbac_shared_operation_admin_and_rep_both_open_accounts_but_a_technician_cannot
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    first = fixtures.create_account(
        api, schedule["id"], ADMIN_HEADERS, account_number="ACC-5012"
    )
    second = fixtures.create_account(
        api, schedule["id"], CSR_HEADERS, account_number="ACC-5013"
    )

    rows, meta = validate_paginated(
        api.list_service_accounts(SUPERVISOR_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 2, (
        f"the supervisor must read the whole collection, got {meta['total_count']}"
    )
    assert sorted(assertions.ids_of(rows)) == sorted([first["id"], second["id"]])

    # The supervisor is not on the create side of the same collection.
    validate_error(
        api.create_service_account(
            factories.service_account_payload(
                schedule["id"], account_number="ACC-5015"
            ),
            SUPERVISOR_HEADERS,
        ),
        "ERR_FORBIDDEN_ROLE",
    )


def test_customer_reads_its_own_account_but_not_the_account_collection(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `ServiceAccount` row; ownership checks on any resource that references a `ServiceAccount` compare the resource's account identifier to `X-User-ID`, and a customer reaching a bill, meter, reading, investigation, repair proof, leak adjustment, arrangement, appeal or ledger entry that resolves to a different `ServiceAccount` is refused with `ERR_ACCOUNT_OWNERSHIP_MISMATCH`."

    PRD §2.1: "If `X-User-Role` is not one of the six declared role names, or is a declared role that the target operation does not list, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.7: "This tier applies to every operation whose role list includes `Customer`."

    Design: Corner/rbac/corner_rbac_shared_operation_admin_and_rep_both_open_accounts_but_a_technician_cannot
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    account = fixtures.create_account(
        api, schedule["id"], ADMIN_HEADERS, account_number="ACC-5012"
    )
    customer = make_customer_headers(account["id"])

    mine = validate_success(api.get_service_account(account["id"], customer))
    assertions.assert_fields(mine, id=account["id"], account_number="ACC-5012")

    # Customer is not a declared role on the collection listing at all, so the
    # refusal is the role check rather than the ownership check.
    validate_error(
        api.list_service_accounts(customer, {"limit": 100}), "ERR_FORBIDDEN_ROLE"
    )


# ===========================================================================
# The account version token guarding an instalment-plan proposal
# ===========================================================================
def _arrangement_payload(account_id, bill_id, down, count, version):
    """A valid instalment-plan proposal for the 5210-cent June bill."""
    return factories.payment_arrangement_payload(
        account_id, bill_id, JUNE_TOTAL, down, count, version
    )


def test_replayed_account_version_is_refused_and_the_first_plan_stays_proposed(api):
    """PRD §2.6: "Proposing a payment arrangement requires `expected_account_version` as a non-optional field of the request payload, carrying the client's last observed `version` of the parent `ServiceAccount`."

    PRD §2.6: "If that value does not equal the account's current `version`, the request is rejected with `ERR_STALE_ACCOUNT_VERSION` and HTTP 412."
    PRD §2.6: "Creating an arrangement cancels any `PROPOSED` or `ACTIVE` arrangement already on the account, so a create issued from a stale view would cancel a plan the client never knew about and finance an already-superseded balance."

    Design: Corner/cross_cutting_layers/corner_cross_cutting_optimistic_concurrency_stale_account_token_blocks_arrangement_create
    """
    _period, account, _meter, _reading, bill = _issued_june_bill(api)

    stale_version = fixtures.account_version(api, account["id"])

    first = validate_success(
        api.create_payment_arrangement(
            _arrangement_payload(account["id"], bill["id"], 1042, 4, stale_version),
            CSR_HEADERS,
        ),
        expected_status=201,
    )
    assertions.assert_fields(first, status="PROPOSED", total_amount_cents=JUNE_TOTAL)

    # The same token, one write later.
    validate_error(
        api.create_payment_arrangement(
            _arrangement_payload(account["id"], bill["id"], 2000, 6, stale_version),
            CSR_HEADERS,
        ),
        "ERR_STALE_ACCOUNT_VERSION",
    )

    unchanged = validate_success(
        api.get_payment_arrangement(first["id"], CSR_HEADERS)
    )
    assertions.assert_fields(
        unchanged,
        status="PROPOSED",
        down_payment_cents=1042,
        installment_count=4,
        version=first["version"],
    )

    rows, meta = validate_paginated(
        api.list_payment_arrangements(
            CSR_HEADERS, {"account_id": account["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused create must leave no plan behind, found {meta['total_count']}"
    )
    assert assertions.ids_of(rows) == [first["id"]]

    entries = assertions.ledger_entries(api, account["id"], CSR_HEADERS)
    assertions.assert_source_kinds(entries, ["BILL_CHARGE"])
    after = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(
        after, balance_cents=JUNE_TOTAL, credit_status="PAST_DUE"
    )
    assertions.assert_version(after, stale_version + 1)


def test_successful_arrangement_create_advances_the_account_version_by_one(api):
    """PRD §2.6: "A successful create increments the account's `version` by one."

    PRD §2.4: "Any operation that changes a row refreshes its `updated_at` and increments its `version`, including changes made as a downstream side effect of an operation aimed at a different resource."

    Design: Corner/cross_cutting_layers/corner_cross_cutting_optimistic_concurrency_stale_account_token_blocks_arrangement_create
    """
    _period, account, _meter, _reading, bill = _issued_june_bill(api)

    # Registered at version 1; issuing the bill moved balance_cents and
    # credit_status on the account row, which is the second version.
    first_read = fixtures.account_version(api, account["id"])
    assert first_read == 2, (
        f"the issued charge is the account's one mutation so far, got {first_read}"
    )

    get_success_data(
        api.create_payment_arrangement(
            _arrangement_payload(account["id"], bill["id"], 1042, 4, first_read),
            CSR_HEADERS,
        )
    )

    second_read = fixtures.account_version(api, account["id"])
    assert second_read == first_read + 1, (
        f"one successful create is one increment, got {second_read}"
    )


def test_refreshed_account_version_creates_the_plan_and_cancels_its_predecessor(api):
    """PRD §2.6: "Creating an arrangement cancels any `PROPOSED` or `ACTIVE` arrangement already on the account, so a create issued from a stale view would cancel a plan the client never knew about and finance an already-superseded balance."

    PRD §3.8: "`installment_cents` is the financed amount divided by `installment_count`, taking the floor — the largest whole number of cents not exceeding the quotient — and it applies to every instalment from the first through the second-to-last."
    PRD §3.8: "A new plan opens in `PROPOSED` with `paid_installment_count`, `missed_payment_count` and `reinstatement_count` all zero, and any other arrangement on the same account sitting in `PROPOSED` or `ACTIVE` is moved to the terminal `CANCELLED`, which stops it counting toward the account's `credit_status` and therefore triggers a recompute."

    Design: Corner/cross_cutting_layers/corner_cross_cutting_optimistic_concurrency_stale_account_token_blocks_arrangement_create
    """
    _period, account, _meter, _reading, bill = _issued_june_bill(api)

    stale_version = fixtures.account_version(api, account["id"])
    first = get_success_data(
        api.create_payment_arrangement(
            _arrangement_payload(account["id"], bill["id"], 1042, 4, stale_version),
            CSR_HEADERS,
        )
    )
    validate_error(
        api.create_payment_arrangement(
            _arrangement_payload(account["id"], bill["id"], 2000, 6, stale_version),
            CSR_HEADERS,
        ),
        "ERR_STALE_ACCOUNT_VERSION",
    )

    fresh_version = fixtures.account_version(api, account["id"])
    second = validate_success(
        api.create_payment_arrangement(
            _arrangement_payload(account["id"], bill["id"], 2000, 6, fresh_version),
            CSR_HEADERS,
        ),
        expected_status=201,
    )

    # 5210 - 2000 = 3210 financed; 3210 / 6 = 535 exactly, so the final
    # instalment absorbs a zero remainder.
    assertions.assert_fields(
        second,
        status="PROPOSED",
        down_payment_cents=2000,
        installment_count=6,
        installment_cents=535,
        final_installment_cents=535,
        paid_installment_count=0,
        missed_payment_count=0,
        reinstatement_count=0,
    )

    superseded = validate_success(api.get_payment_arrangement(first["id"], CSR_HEADERS))
    assertions.assert_fields(superseded, status="CANCELLED")

    _rows, meta = validate_paginated(
        api.list_payment_arrangements(
            CSR_HEADERS, {"account_id": account["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2, (
        f"two creates passed the guard, one did not; got {meta['total_count']}"
    )

    after = fixtures.fetch_account(api, account["id"])
    assertions.assert_version(after, stale_version + 2)
    # A PROPOSED plan is not an ACTIVE one, so nothing pins the account.
    assertions.assert_account_state(
        after, balance_cents=JUNE_TOTAL, credit_status="PAST_DUE"
    )


# ===========================================================================
# The rebill counter is reconciled against its source rows
# ===========================================================================
def _shutoff_scheduled_june_account(api):
    """The issued June bill with a shutoff notice already served."""
    period, account, meter, reading, bill = _issued_june_bill(api)
    scheduled = get_success_data(
        api.schedule_shutoff(account["id"], SUPERVISOR_HEADERS)
    )
    return period, account, meter, reading, bill, scheduled


def test_corrected_read_reconciles_the_rebill_counter_up_and_holds_the_shutoff(api):
    """PRD §2.9: "`open_investigation_hold_count` is the number of `HighBillInvestigation` rows on the account whose `shutoff_hold_active` is true, and `open_rebill_count` is the number of the account's bills sitting in `REBILL_PENDING`."

    PRD §3.1: "When a `CORRECTED` read lands in a period whose bill is `ISSUED`, `UNDER_INVESTIGATION` or `ADJUSTED`, that bill immediately recomputes every charge field and moves to `REBILL_PENDING`, which increments the account's `open_rebill_count` and may in turn move `service_status` from `SHUTOFF_SCHEDULED` to `SHUTOFF_HELD`."
    PRD §3.8: "When the sum of `open_investigation_hold_count` and `open_rebill_count` moves from zero to positive, an account in `SHUTOFF_SCHEDULED` moves to `SHUTOFF_HELD` with `shutoff_scheduled_for` preserved unchanged, so the notice period resumes rather than restarts when the hold lifts."

    Design: Corner/cross_cutting_layers/corner_cross_cutting_derived_field_reconciliation_rebill_counter_tracks_its_source_rows
    """
    _period, account, meter, reading, bill, _scheduled = (
        _shutoff_scheduled_june_account(api)
    )

    before = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(
        before,
        balance_cents=JUNE_TOTAL,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_SCHEDULED",
        open_investigation_hold_count=0,
        open_rebill_count=0,
    )
    notice = before["shutoff_scheduled_for"]
    assert notice is not None and notice.startswith(NOTICE_PREFIX), (
        f"shutoff_scheduled_for: expected the ten-day notice instant, got {notice!r}"
    )

    corrected = fixtures.post_corrected_reading(
        api, meter["id"], "2025-06-30", 103900, reading["id"]
    )
    assertions.assert_fields(
        corrected,
        read_type="CORRECTED",
        corrects_reading_id=reading["id"],
        consumption_since_prior_gallons=CORRECTED_GALLONS,
    )

    restated = fixtures.fetch_bill(api, bill["id"])
    assertions.assert_fields(restated, billing_status="REBILL_PENDING")
    assertions.assert_bill_charges(
        restated,
        consumption_gallons=CORRECTED_GALLONS,
        water_charge_cents=CORRECTED_WATER,
        sewer_charge_cents=CORRECTED_SEWER,
        total_charge_cents=CORRECTED_TOTAL,
    )

    after = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(
        after,
        open_rebill_count=1,
        open_investigation_hold_count=0,
        service_status="SHUTOFF_HELD",
    )
    assert after["shutoff_scheduled_for"] == notice, (
        "the notice anchor must resume, not restart, when the hold arms"
    )


def test_rebill_counter_counts_live_source_rows_not_raw_reading_inserts(api):
    """PRD §3.1: "Liveness is tracked by `superseded_by_reading_id`: a row whose `superseded_by_reading_id` is null is live, and posting a `CORRECTED` read sets that field on the row named by `corrects_reading_id` to the new row's identifier."

    PRD §2.11: "Meter readings filter on `meter_id`, `corrects_reading_id`, `superseded_by_reading_id` and `read_type`, and additionally accept `live_only`, which when true restricts the result to rows whose `superseded_by_reading_id` is null."
    PRD §2.9: "`open_investigation_hold_count` is the number of `HighBillInvestigation` rows on the account whose `shutoff_hold_active` is true, and `open_rebill_count` is the number of the account's bills sitting in `REBILL_PENDING`."

    Design: Corner/cross_cutting_layers/corner_cross_cutting_derived_field_reconciliation_rebill_counter_tracks_its_source_rows
    """
    _period, account, meter, reading, _bill, _scheduled = (
        _shutoff_scheduled_june_account(api)
    )

    corrected = fixtures.post_corrected_reading(
        api, meter["id"], "2025-06-30", 103900, reading["id"]
    )

    live, live_meta = validate_paginated(
        api.list_meter_readings(
            SUPERVISOR_HEADERS,
            {"meter_id": meter["id"], "live_only": True, "limit": 100},
        )
    )
    assert live_meta["total_count"] == 2, (
        f"two live rows bound the period, got {live_meta['total_count']}"
    )
    assert [row["reading_value"] for row in live] == [100000, 103900]

    every, all_meta = validate_paginated(
        api.list_meter_readings(
            SUPERVISOR_HEADERS, {"meter_id": meter["id"], "limit": 100}
        )
    )
    assert all_meta["total_count"] == 3, (
        f"the superseded row is retained, got {all_meta['total_count']}"
    )
    superseded = [row for row in every if row["id"] == reading["id"]]
    assert len(superseded) == 1
    assertions.assert_fields(
        superseded[0], superseded_by_reading_id=corrected["id"], reading_value=104000
    )

    account_now = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(account_now, open_rebill_count=1)


def test_rebill_reconciles_the_counter_back_to_zero_and_keeps_the_notice_anchor(api):
    """PRD §3.5: "The superseded bill moves from `REBILL_PENDING` to the terminal `REBILLED`."

    PRD §3.5: "A replacement bill is created carrying the superseded bill's `account_id`, `period_id`, `meter_id`, recomputed `consumption_gallons` and copied `read_type`, with `rebill_of_bill_id` naming the superseded bill; it is created in `DRAFT` and then immediately auto-advanced to `ISSUED` inside the same request."
    PRD §3.8: "When that sum returns to zero while `credit_status` is still `PAST_DUE` or `ARRANGEMENT_DEFAULTED`, the account moves back from `SHUTOFF_HELD` to `SHUTOFF_SCHEDULED` with `shutoff_scheduled_for` again unchanged."

    Design: Corner/cross_cutting_layers/corner_cross_cutting_derived_field_reconciliation_rebill_counter_tracks_its_source_rows
    """
    _period, account, meter, reading, bill, _scheduled = (
        _shutoff_scheduled_june_account(api)
    )
    notice = fixtures.fetch_account(api, account["id"])["shutoff_scheduled_for"]

    fixtures.post_corrected_reading(
        api, meter["id"], "2025-06-30", 103900, reading["id"]
    )

    replacement = validate_success(api.rebill_bill(bill["id"], SUPERVISOR_HEADERS))
    assertions.assert_fields(
        replacement,
        billing_status="ISSUED",
        rebill_of_bill_id=bill["id"],
        consumption_gallons=CORRECTED_GALLONS,
        total_charge_cents=CORRECTED_TOTAL,
    )

    superseded = fixtures.fetch_bill(api, bill["id"])
    assertions.assert_fields(superseded, billing_status="REBILLED")

    _rows, meta = validate_paginated(
        api.list_bills(
            SUPERVISOR_HEADERS,
            {
                "account_id": account["id"],
                "billing_status": "REBILL_PENDING",
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 0, (
        f"no source row remains for the counter to count, got {meta['total_count']}"
    )

    after = fixtures.fetch_account(api, account["id"])
    assertions.assert_account_state(
        after,
        balance_cents=CORRECTED_TOTAL,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_SCHEDULED",
        open_rebill_count=0,
        open_investigation_hold_count=0,
    )
    assert after["shutoff_scheduled_for"] == notice, (
        "leaving the hold restores the original anchor rather than a fresh notice"
    )


def test_rebill_ledger_replays_the_reversal_and_the_replacement_charge(api):
    """PRD §3.5: "Two ledger entries land: a `REVERSAL` with `source_kind` `REBILL_REVERSAL` whose `amount_cents` is the negative of the sum of the superseded bill's `BILL_CHARGE` and `REBILL_CHARGE` entries, and then — from the replacement's auto-issue — a `CHARGE` with `source_kind` `REBILL_CHARGE` for the positive `total_charge_cents` of the replacement."

    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."
    PRD §2.3: "Two collections carry a domain-specific ordering instead: an account's ledger entries are returned oldest-first by `effective_at` ascending with `created_at` ascending as the tie-break, and meter readings are returned by `read_date` ascending with `created_at` ascending as the tie-break."

    Design: Corner/cross_cutting_layers/corner_cross_cutting_derived_field_reconciliation_rebill_counter_tracks_its_source_rows
    """
    _period, account, meter, reading, bill, _scheduled = (
        _shutoff_scheduled_june_account(api)
    )
    fixtures.post_corrected_reading(
        api, meter["id"], "2025-06-30", 103900, reading["id"]
    )
    replacement = get_success_data(api.rebill_bill(bill["id"], SUPERVISOR_HEADERS))

    entries = assertions.ledger_entries(api, account["id"], SUPERVISOR_HEADERS)
    assertions.assert_source_kinds(
        entries, ["BILL_CHARGE", "REBILL_REVERSAL", "REBILL_CHARGE"]
    )
    assertions.assert_single_entry(
        entries, "BILL_CHARGE", entry_type="CHARGE", amount_cents=JUNE_TOTAL
    )
    assertions.assert_single_entry(
        entries,
        "REBILL_REVERSAL",
        entry_type="REVERSAL",
        amount_cents=-JUNE_TOTAL,
        bill_id=bill["id"],
    )
    assertions.assert_single_entry(
        entries,
        "REBILL_CHARGE",
        entry_type="CHARGE",
        amount_cents=CORRECTED_TOTAL,
        bill_id=replacement["id"],
    )

    after = fixtures.fetch_account(api, account["id"])
    assertions.assert_balance_is_ledger_sum(after, entries)
    assertions.assert_account_state(after, balance_cents=CORRECTED_TOTAL)


# ===========================================================================
# Every write already carries its own cascade
# ===========================================================================
def test_bill_generation_response_already_carries_every_computed_field(api):
    """PRD §3.2: "Generation then computes the bill's entire fiscal picture in one pass."

    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.2: "If fewer than three candidates exist, `seasonal_baseline_gallons` is null and `baseline_sample_count` records how many were found; otherwise `baseline_sample_count` is 3 and `seasonal_baseline_gallons` is the sum of the sample's `consumption_gallons` divided by three, rounded half up to a whole gallon."
    PRD §3.2: "When `seasonal_baseline_gallons` is null or zero, `anomaly_ratio` is null and `anomaly_flag` is false."
    PRD §3.2: "`total_charge_cents` is `water_charge_cents` plus `sewer_charge_cents`, and at generation time `adjusted_total_cents` equals `total_charge_cents` because no credit has been posted."

    Design: Corner/consistency_model/corner_consistency_immediate_every_write_response_already_carries_its_own_cascade
    """
    _schedule, period, account, meter = _june_estate(api)
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)

    created = validate_success(
        api.create_bill(
            factories.bill_payload(account["id"], period["id"], meter["id"]),
            SUPERVISOR_HEADERS,
        ),
        expected_status=201,
    )

    # No field is left null pending a later pass.
    assertions.assert_fields(
        created,
        billing_status="DRAFT",
        consumption_gallons=4000,
        water_charge_cents=JUNE_WATER,
        sewer_billable_gallons=4000,
        sewer_charge_cents=JUNE_SEWER,
        total_charge_cents=JUNE_TOTAL,
        adjusted_total_cents=JUNE_TOTAL,
        estimated_flag=False,
        submeter_credit_gallons=0,
        baseline_sample_count=0,
        anomaly_flag=False,
    )
    assertions.assert_null_fields(
        created, "seasonal_baseline_gallons", "anomaly_ratio", "rebill_of_bill_id"
    )

    # The immediately following read agrees with the create response.
    reread = fixtures.fetch_bill(api, created["id"])
    assertions.assert_bill_charges(
        reread,
        consumption_gallons=4000,
        water_charge_cents=JUNE_WATER,
        sewer_charge_cents=JUNE_SEWER,
        total_charge_cents=JUNE_TOTAL,
        adjusted_total_cents=JUNE_TOTAL,
    )


def test_issue_response_carries_the_due_date_and_the_next_read_sees_the_charge(api):
    """PRD §3.2: "Issuing stamps `due_date` as the period's `end_date` plus twenty-one calendar days, inserts a `CHARGE` ledger entry with `source_kind` `BILL_CHARGE` for the positive `total_charge_cents`, naming this bill in both `bill_id` and `source_id`, and then recomputes the account's `balance_cents`, then its `credit_status`, then its `service_status`, in that order."

    PRD §2.9: "`credit_status` is a pure function of the account's balance and its arrangements, recomputed after every ledger insert and after every change to a payment arrangement's status."

    Design: Corner/consistency_model/corner_consistency_immediate_every_write_response_already_carries_its_own_cascade
    """
    _period, account, _meter, _reading, bill = _draft_june_bill(api)

    issued = validate_success(api.issue_bill(bill["id"], SUPERVISOR_HEADERS))
    assertions.assert_fields(issued, billing_status="ISSUED", due_date=DUE_DATE)

    # Read by a different role on the very next call — no polling, no retry.
    account_now = validate_success(
        api.get_service_account(account["id"], CSR_HEADERS)
    )
    assertions.assert_account_state(
        account_now, balance_cents=JUNE_TOTAL, credit_status="PAST_DUE"
    )


def test_schedule_shutoff_response_already_shows_the_served_notice(api):
    """PRD §3.8: "Scheduling sets `shutoff_scheduled_for` to the current logical-clock instant plus a ten-calendar-day statutory notice and moves `service_status` to `SHUTOFF_SCHEDULED`."

    PRD §2.4: "The clock starts at `2026-08-01T00:00:00Z` when the process starts, and an operator may move it by supplying `current_utc` as an ISO 8601 UTC instant to the clock-setting capability, which echoes back the accepted `current_utc`, mutates no entity and recomputes no derived field."

    Design: Corner/consistency_model/corner_consistency_immediate_every_write_response_already_carries_its_own_cascade
    """
    _period, account, _meter, _reading, _bill = _issued_june_bill(api)

    scheduled = validate_success(
        api.schedule_shutoff(account["id"], SUPERVISOR_HEADERS)
    )
    assertions.assert_fields(scheduled, service_status="SHUTOFF_SCHEDULED")
    notice = scheduled["shutoff_scheduled_for"]
    assert notice is not None and notice.startswith(NOTICE_PREFIX), (
        f"the action's own body must carry the notice instant, got {notice!r}"
    )

    reread = fixtures.fetch_account(api, account["id"])
    assert reread["shutoff_scheduled_for"] == notice
    assertions.assert_account_state(reread, service_status="SHUTOFF_SCHEDULED")


def test_payment_cascade_is_visible_on_the_immediately_following_read(api):
    """PRD §3.8: "An ad-hoc account payment supplies an `amount_cents` that must be strictly positive, else `ERR_PAYMENT_AMOUNT_INVALID`, plus an optional `memo`; it writes a `PAYMENT` entry with `source_kind` `CUSTOMER_PAYMENT` for the negative amount, with `bill_id` and `source_id` both null and `effective_at` taken from the logical clock, and then recomputes `balance_cents`, `credit_status` and `service_status` in that order."

    PRD §3.8: "And whenever `credit_status` becomes `CURRENT` or `IN_ARRANGEMENT`, the account returns to `ACTIVE` from `SHUTOFF_HELD`, from `SHUTOFF_SCHEDULED`, or from `SHUTOFF_EXECUTED` — in the last case service is restored — and `shutoff_scheduled_for` is set to null."
    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    Design: Corner/consistency_model/corner_consistency_immediate_every_write_response_already_carries_its_own_cascade
    """
    _period, account, _meter, _reading, bill, _scheduled = (
        _shutoff_scheduled_june_account(api)
    )

    get_success_data(
        api.record_account_payment(
            account["id"],
            factories.account_payment_payload(
                JUNE_TOTAL, memo="paid in full at the counter"
            ),
            CSR_HEADERS,
        )
    )

    # The balance replay, the credit recompute and the shutoff release are all
    # already done on this one following call.
    after = validate_success(api.get_service_account(account["id"], CSR_HEADERS))
    assertions.assert_account_state(
        after, balance_cents=0, credit_status="CURRENT", service_status="ACTIVE"
    )
    assertions.assert_null_fields(after, "shutoff_scheduled_for")

    _rows, meta = validate_paginated(
        api.list_service_accounts(
            SUPERVISOR_HEADERS, {"credit_status": "CURRENT", "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"the collection index reflects the new credit_status at once, got {meta['total_count']}"
    )

    entries = assertions.ledger_entries(api, account["id"], CSR_HEADERS)
    assertions.assert_source_kinds(entries, ["BILL_CHARGE", "CUSTOMER_PAYMENT"])
    payment = assertions.assert_single_entry(
        entries, "CUSTOMER_PAYMENT", entry_type="PAYMENT", amount_cents=-JUNE_TOTAL
    )
    assertions.assert_null_fields(payment, "bill_id", "source_id")
    assertions.assert_balance_is_ledger_sum(after, entries)

    # Immediate visibility lands the declared cascade; it does not invent an
    # undeclared transition on the bill.
    settled = fixtures.fetch_bill(api, bill["id"])
    assertions.assert_fields(
        settled, billing_status="ISSUED", adjusted_total_cents=JUNE_TOTAL
    )
