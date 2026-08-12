"""Bookkeeping: reconciliation periods, statement matching, and the close /
reopen / lock cycle."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_reconciliation_period,
    assert_same_instant,
    change_period_status,
    create_account,
    create_active_client,
    create_reconciliation_period_payload,
    dispose_statement_line,
    import_statement_line,
    list_ledger_entries,
    open_period,
    period_status_payload,
    period_version,
    read_period,
    read_statement_line,
    register_bond,
    set_clock,
    setup_period_with_deposit_and_line,
    statement_line_disposition_payload,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["fiduciary_manager_headers"]
SPECIALIST = TEST_USERS["bill_pay_specialist_headers"]


def _client_with_account_and_period(period_month="2026-06"):
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-9008")
    account = create_account(client["id"], opening_balance_cents=5000000)
    period = open_period(account["id"], period_month)
    return client, account, period


def test_a_period_that_has_never_been_reopened_closes_into_closed():
    """PRD §3.7: "**Where the close lands depends on the period's history**: a
    period whose `reopen_count` is still zero closes into `CLOSED`, while a
    period that has already been reopened once — `reopen_count` of 1 — closes
    into `LOCKED` instead."
    PRD §3.7: "Reopening raises `reopen_count` by one and every ledger entry of
    the period reads `frozen` as false again."

    Design: Difficulty/non_linear_state_machine/reconciliation_period_close_reopen_close_lands_in_locked
    """
    _client, _account, period = _client_with_account_and_period()

    change_period_status(period["id"], "IN_REVIEW", SPECIALIST)
    closed = change_period_status(period["id"], "CLOSED", MANAGER)
    assert closed["status"] == "CLOSED"
    assert closed["reopen_count"] == 0

    set_clock("2026-06-20T10:00:00Z")
    reopened = change_period_status(period["id"], "REOPENED", MANAGER)

    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1


def test_the_second_close_after_a_reopen_lands_in_locked():
    """PRD §3.7: "From `REOPENED` the period goes back to `IN_REVIEW`, and the
    next close — because `reopen_count` now reads 1 — lands in `LOCKED`."
    PRD §3.7: "The same request, the same `to_status` of `CLOSED`, produces two
    different destination states."

    Design: Difficulty/non_linear_state_machine/reconciliation_period_close_reopen_close_lands_in_locked
    """
    _client, _account, period = _client_with_account_and_period()
    change_period_status(period["id"], "IN_REVIEW", SPECIALIST)
    change_period_status(period["id"], "CLOSED", MANAGER)

    set_clock("2026-06-20T10:00:00Z")
    change_period_status(period["id"], "REOPENED", MANAGER)
    change_period_status(period["id"], "IN_REVIEW", SPECIALIST)
    locked = change_period_status(period["id"], "CLOSED", MANAGER)

    assert_reconciliation_period(locked)
    assert locked["status"] == "LOCKED"
    assert locked["reopen_count"] == 1
    assert locked["open_exception_count"] == 0
    assert locked["imported_line_count"] == 0


def test_a_period_with_zero_imported_lines_closes_successfully():
    """PRD §2.9 rung 27: "**Open exceptions.** A close request arrives while
    the period's `open_exception_count` is zero. Otherwise `ERR_OPEN_EXCEPTIONS`
    (409). Applies to a period status request whose `to_status` is `CLOSED`.
    The test is on the count, not on non-emptiness: a period with zero imported
    lines closes successfully."

    Design: Difficulty/boundary_precision_check/empty_reconciliation_period_closes_with_zero_imported_lines
    """
    _client, _account, period = _client_with_account_and_period()
    change_period_status(period["id"], "IN_REVIEW", SPECIALIST)

    response = api_client.change_period_status(
        period["id"], period_status_payload("CLOSED"), MANAGER
    )

    closed = validate_success(response, 200)
    assert closed["status"] == "CLOSED"
    assert closed["imported_line_count"] == 0
    assert closed["open_exception_count"] == 0
    assert closed["unreconciled_entry_count"] == 0
    assert closed["reopen_count"] == 0


def test_closing_stamps_closed_at_with_the_current_logical_instant():
    """PRD §3.7: "Either way the current logical instant is written to
    `closed_at`, every ledger entry of that period now reads `frozen` as true,
    and the reconciliation-freeze gate at rung 10 begins refusing the
    operations it guards."

    Design: Difficulty/boundary_precision_check/empty_reconciliation_period_closes_with_zero_imported_lines
    """
    _client, _account, period = _client_with_account_and_period()
    change_period_status(period["id"], "IN_REVIEW", SPECIALIST)

    closed = change_period_status(period["id"], "CLOSED", MANAGER)

    assert_same_instant(
        closed["closed_at"], "2026-06-01T09:00:00Z", "ReconciliationPeriod.closed_at"
    )


def test_an_adjacent_period_month_is_always_legal():
    """PRD §3.7: "Only one period may exist per account per month; a repeat is
    refused with `ERR_PERIOD_OVERLAP` at rung 18. Calendar months partition the
    timeline exactly, so an adjacent month never collides — only an exact
    repeat does."

    Design: Difficulty/resource_temporal_overlap/reconciliation_period_months_partition_the_account_timeline
    """
    _client, account, june = _client_with_account_and_period("2026-06")

    response = api_client.create_reconciliation_period(
        create_reconciliation_period_payload(account["id"], "2026-07"), SPECIALIST
    )

    july = validate_success(response, 201)
    assert july["status"] == "OPEN"
    assert read_period(june["id"])["status"] == "OPEN"


def test_an_exact_repeat_of_a_period_month_collides():
    """PRD §2.9 rung 18: "**Period non-repetition.** No `ReconciliationPeriod`
    already exists for this account with the same `period_month`. Otherwise
    `ERR_PERIOD_OVERLAP` (409). Applies to opening a reconciliation period.
    Calendar months partition the timeline exactly, so an adjacent month is
    always legal and only an exact repeat collides."

    Design: Difficulty/resource_temporal_overlap/reconciliation_period_months_partition_the_account_timeline
    """
    _client, account, _june = _client_with_account_and_period("2026-06")
    validate_success(
        api_client.create_reconciliation_period(
            create_reconciliation_period_payload(account["id"], "2026-07"), SPECIALIST
        ),
        201,
    )

    response = api_client.create_reconciliation_period(
        create_reconciliation_period_payload(account["id"], "2026-06"), SPECIALIST
    )

    validate_error(response, ApiErrorId.ERR_PERIOD_OVERLAP.value, 409)
    rows, meta = validate_paginated(
        api_client.list_account_reconciliation_periods(account["id"], MANAGER, {"limit": 100})
    )
    assert meta["total_count"] == 2, f"Expected exactly two periods, got {rows}"


def test_a_wrong_amount_match_is_refused_and_the_exception_then_blocks_the_close():
    """PRD §3.7: "The named entry must belong to the same period as the line
    and its `amount_cents` must equal the line's `amount_cents` exactly; either
    mismatch is refused with `ERR_REFERENCE_MISMATCH` at rung 14."
    PRD §3.7: "Also from `UNMATCHED`, a `FLAG_EXCEPTION` records the supplied
    `exception_note` and moves the line to `EXCEPTION`, raising the period's
    `open_exception_count` by one; nothing on the ledger side moves."
    PRD §3.7: "Closing requires the period to be `IN_REVIEW` with
    `open_exception_count` at zero; an outstanding exception is refused with
    `ERR_OPEN_EXCEPTIONS` at rung 27."

    Design: Corner/validations/corner_wrong_amount_match_then_open_exception_blocks_the_close
    """
    world = setup_period_with_deposit_and_line(
        line_amount_cents=100000, deposit_amount_cents=250000
    )
    entry = world["ledger_entries"][0]
    version = period_version(world["period"]["id"])

    bad_match = api_client.dispose_statement_line(
        world["statement_line"]["id"],
        statement_line_disposition_payload(
            "MATCH", version, ledger_entry_id=entry["id"]
        ),
        SPECIALIST,
    )
    validate_error(bad_match, ApiErrorId.ERR_REFERENCE_MISMATCH.value, 422)

    dispose_statement_line(
        world["statement_line"]["id"],
        "FLAG_EXCEPTION",
        version,
        exception_note="No matching ledger entry for this credit.",
    )
    assert read_statement_line(world["statement_line"]["id"])["match_status"] == "EXCEPTION"
    assert read_period(world["period"]["id"])["open_exception_count"] == 1

    change_period_status(world["period"]["id"], "IN_REVIEW", SPECIALIST)
    close = api_client.change_period_status(
        world["period"]["id"], period_status_payload("CLOSED"), MANAGER
    )

    validate_error(close, ApiErrorId.ERR_OPEN_EXCEPTIONS.value, 409)
    assert read_period(world["period"]["id"])["status"] == "IN_REVIEW"


def test_a_reopen_after_the_thirty_day_window_is_refused():
    """PRD §2.9 rung 23: "**Reopen window.** A reopen request arrives at or
    before the period's `closed_at` plus 30 days; exactly 30 days later still
    reopens. Otherwise `ERR_REOPEN_NOT_PERMITTED` (409). Applies to a period
    status request whose `to_status` is `REOPENED`."

    Design: Corner/validations/corner_reopen_after_the_thirty_day_window_is_rejected
    """
    _client, _account, period = _client_with_account_and_period()
    change_period_status(period["id"], "IN_REVIEW", SPECIALIST)
    change_period_status(period["id"], "CLOSED", MANAGER)

    set_clock("2026-07-02T09:00:00Z")
    response = api_client.change_period_status(
        period["id"], period_status_payload("REOPENED"), MANAGER
    )

    validate_error(response, ApiErrorId.ERR_REOPEN_NOT_PERMITTED.value, 409)
    after = read_period(period["id"])
    assert after["status"] == "CLOSED"
    assert after["reopen_count"] == 0


def test_a_stale_period_version_refuses_the_second_line_disposition():
    """PRD §2.10: "Disposing of a statement line requires
    `expected_period_version`, carrying the client's last observed `version` of
    the `ReconciliationPeriod` that owns the line. Matching or flagging a
    second, different line is legitimate on its own — but each disposition
    moves the period's `open_exception_count` and `unreconciled_entry_count`,
    and a reconciler working from a stale count is exactly the condition that
    lets a period be closed with an exception still outstanding. A mismatch is
    refused with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_period_version_rejected_on_statement_line_disposition
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-C061")
    account = create_account(client["id"], opening_balance_cents=5000000)
    period = open_period(account["id"], "2026-06")
    first = import_statement_line(
        period["id"], "BK-0001", 100000, "2026-06-01", line_description="Unidentified credit one"
    )
    second = import_statement_line(
        period["id"], "BK-0002", 200000, "2026-06-02", line_description="Unidentified credit two"
    )
    observed = period_version(period["id"])

    dispose_statement_line(
        first["id"], "FLAG_EXCEPTION", observed, exception_note="No matching ledger entry."
    )

    response = api_client.dispose_statement_line(
        second["id"],
        statement_line_disposition_payload(
            "FLAG_EXCEPTION", observed, exception_note="Also unexplained."
        ),
        SPECIALIST,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)
    assert read_statement_line(first["id"])["match_status"] == "EXCEPTION"
    assert read_statement_line(second["id"])["match_status"] == "UNMATCHED"
    assert read_period(period["id"])["open_exception_count"] == 1
