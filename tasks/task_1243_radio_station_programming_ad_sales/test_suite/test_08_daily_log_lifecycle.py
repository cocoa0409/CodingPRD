"""Daily log lifecycle: lock OCC + clock pinning, duplicate rejection, the
reopen loop, reconcile zero-discrepancy gate, and the RECONCILED revert branch
(PRD §2.7, §3.5, §3.8)."""
from test_helpers import (
    TD,
    ApiErrorId,
    assert_daily_log,
    book_spot_ok,
    create_active_clock,
    create_active_order,
    create_locked_log,
    create_log,
    create_station,
    get_success_data,
    import_as_run,
    import_as_run_ok,
    list_discrepancies,
    lock_log,
    make_billing_admin_headers,
    make_headers,
    make_sales_rep_headers,
    reconcile_log_as,
    setup_bookable_scenario,
    setup_bookable_station,
    setup_log_with_missed_spot,
    validate_error,
    validate_success,
)


def test_no_active_clock_blocks_lock(api):
    """PRD §3.5: "the clock-pin-selection rule must find an `ACTIVE`
    FormatClock whose `applies_weekdays` covers the weekday of `log_date` —
    activation-time disjointness guarantees at most one candidate, and an
    empty candidate set rejects the lock with `ERR_NO_ACTIVE_CLOCK`."

    Design: Corner/errors/no_active_clock_blocks_lock
    """
    station = create_station()
    create_active_clock(station["id"], applies_weekdays=["TUE"], slots=[])
    log = create_log(station["id"], log_date="2026-05-04")  # a MON

    resp = api.lock_log(log["id"], {"expected_log_version": log["version"]}, TD)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CLOCK)

    after = get_success_data(api.get_log(log["id"], TD))
    assert after["posture"] == "DRAFT"
    assert after["clock_id"] is None


def test_occ_stale_log_lock_version_returns_412(api):
    """PRD §2.7: "Locking a log requires `expected_log_version` matching the
    target DailyLog's current `version`." and "is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_log_lock_version_returns_412
    """
    station = create_station()
    create_active_clock(station["id"], applies_weekdays=["MON"], slots=[])
    log = create_log(station["id"], log_date="2026-05-04")

    resp = api.lock_log(
        log["id"], {"expected_log_version": log["version"] - 1}, TD
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = get_success_data(api.get_log(log["id"], TD))
    assert after["posture"] == "DRAFT", "log stays DRAFT after a stale lock"


def test_duplicate_log_rejected(api):
    """PRD §3.5: "only one log may exist per station and date, and a duplicate
    is rejected with `ERR_LOG_ALREADY_EXISTS`."

    Design: Corner/validations/duplicate_log_rejected
    """
    station = create_station()
    create_log(station["id"], log_date="2026-05-04")

    resp = api.create_log({"station_id": station["id"], "log_date": "2026-05-04"}, TD)
    validate_error(resp, ApiErrorId.ERR_LOG_ALREADY_EXISTS)


def test_as_run_import_foreign_id_returns_404(api):
    """PRD §3.7: "Every identifier in these lists must belong to the log being
    imported; an unknown or foreign id is rejected with `ERR_NOT_FOUND`."

    Design: Corner/errors/as_run_import_foreign_id_returns_404
    """
    env = setup_bookable_station(weekday="MON", rate_weekday_set=["MON", "TUE"])
    # Log B falls on a Tuesday; pin a disjoint TUE clock so the lock finds an
    # ACTIVE clock covering weekday(log_date) (PRD §3.5).
    create_active_clock(env["station"]["id"], applies_weekdays=["TUE"])
    order = create_active_order(
        env["station"]["id"], daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 1}]
    )
    log_a = create_locked_log(env["station"]["id"], log_date="2026-05-04")
    spot = book_spot_ok(order["id"], log_a["id"])
    log_b = create_locked_log(env["station"]["id"], log_date="2026-05-05")

    resp = import_as_run(log_b["id"], aired_spot_ids=[spot["id"]])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    after = get_success_data(api.get_log(log_b["id"], TD))
    assert after["posture"] == "LOCKED", "failed import has no side effects"


def test_log_reopen_from_reconciled_returns_reconciling(api):
    """PRD §3.8: "Reopening from `RECONCILED` reverts to `RECONCILING` and
    clears `reconciled_by_user_id` to null."

    Design: Corner/state_machines/log_reopen_from_reconciled_returns_reconciling
    """
    station = create_station()
    create_active_clock(station["id"], applies_weekdays=["MON"], slots=[])
    log = create_locked_log(station["id"], log_date="2026-05-04")
    import_as_run_ok(log["id"])
    reconciled = reconcile_log_as(log["id"], td_user_id="td-1")
    assert reconciled["posture"] == "RECONCILED"
    assert reconciled["reconciled_by_user_id"] == "td-1"

    reverted = get_success_data(api.reopen_log(log["id"], TD))
    assert reverted["posture"] == "RECONCILING"
    assert reverted["reconciled_by_user_id"] is None, "cleared by the revert"


# ---------------------------------------------------------------------------
# Reconcile gate: exactly zero unresolved discrepancies
# ---------------------------------------------------------------------------

def _setup_two_logs_one_clean_one_dirty(api):
    """Log A imported with its spot aired (0 discrepancies); log B imported
    with its spot missing (1 discrepancy). Both walked to RECONCILING."""
    env = setup_bookable_station(weekday="MON", rate_weekday_set=["MON", "TUE"])
    # Log B falls on a Tuesday; pin a disjoint TUE clock so the lock finds an
    # ACTIVE clock covering weekday(log_date) (PRD §3.5).
    create_active_clock(env["station"]["id"], applies_weekdays=["TUE"])
    order = create_active_order(
        env["station"]["id"], daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 2}]
    )
    log_a = create_locked_log(env["station"]["id"], log_date="2026-05-04")
    spot_a = book_spot_ok(order["id"], log_a["id"])
    import_as_run_ok(log_a["id"], aired_spot_ids=[spot_a["id"]])
    get_success_data(api.begin_reconciliation(log_a["id"], TD))

    log_b = create_locked_log(env["station"]["id"], log_date="2026-05-05")
    book_spot_ok(order["id"], log_b["id"])
    import_as_run_ok(log_b["id"])  # airs nothing -> 1 MISSED_SPOT discrepancy
    get_success_data(api.begin_reconciliation(log_b["id"], TD))

    env.update({"order": order, "log_a": log_a, "log_b": log_b})
    return env


def test_reconcile_succeeds_at_exactly_zero_discrepancies(api):
    """PRD §3.8: "or reconcile it (`RECONCILING → RECONCILED`), which requires
    `unresolved_discrepancy_count` to be exactly zero (any positive count is
    rejected with `ERR_UNRESOLVED_DISCREPANCIES`) and stamps
    `reconciled_by_user_id` from the caller."

    Design: Difficulty/boundary_precision_check/reconcile_requires_exactly_zero_unresolved_discrepancies
    """
    env = _setup_two_logs_one_clean_one_dirty(api)
    log_a = env["log_a"]
    reconciled = get_success_data(
        api.reconcile_log(log_a["id"], make_headers("TrafficDirector", "td-1"))
    )
    assert reconciled["posture"] == "RECONCILED"
    assert reconciled["unresolved_discrepancy_count"] == 0
    assert reconciled["reconciled_by_user_id"] == "td-1"


def test_reconcile_blocked_at_one_discrepancy(api):
    """PRD §3.8: "which requires `unresolved_discrepancy_count` to be exactly
    zero (any positive count is rejected with `ERR_UNRESOLVED_DISCREPANCIES`)".

    Design: Difficulty/boundary_precision_check/reconcile_requires_exactly_zero_unresolved_discrepancies
    """
    env = _setup_two_logs_one_clean_one_dirty(api)
    log_b = env["log_b"]

    resp = api.reconcile_log(log_b["id"], make_headers("TrafficDirector", "td-1"))
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_DISCREPANCIES)

    after = get_success_data(api.get_log(log_b["id"], TD))
    assert after["posture"] == "RECONCILING", "posture stays RECONCILING"
    assert after["unresolved_discrepancy_count"] == 1


# ---------------------------------------------------------------------------
# The reopen loop: RECONCILING -> LOCKED re-enables booking
# ---------------------------------------------------------------------------

def _setup_reconciling_log_with_missed_spot(api):
    """LOCKED log with one spot; import airs nothing (spot MAKE_GOOD_PENDING
    + 1 discrepancy); log moved to RECONCILING."""
    env = setup_log_with_missed_spot(units=5, base_rate_cents=2000, min_rate_cents=500)
    get_success_data(api.begin_reconciliation(env["log"]["id"], TD))
    return env


def test_reopen_reconciling_returns_locked_and_reenables_booking(api):
    """PRD §3.8: "From `RECONCILING`, a `TrafficDirector` may either reopen the
    log back to `LOCKED` — which preserves all `MAKE_GOOD_PENDING` obligations
    and existing discrepancies (obligations are not erased) while re-enabling
    bookings and edits, with a later as-run-import re-evaluating spots still in
    `SCHEDULED` or `AIRED` — or reconcile it".

    Design: Difficulty/non_linear_state_machine/daily_log_reopen_loop_reconciling_to_locked_and_back
    """
    env = _setup_reconciling_log_with_missed_spot(api)
    reopened = get_success_data(api.reopen_log(env["log"]["id"], TD))
    assert reopened["posture"] == "LOCKED", "RECONCILING -> LOCKED revert"

    survivor = get_success_data(api.get_spot(env["spot"]["id"], TD))
    assert survivor["status"] == "MAKE_GOOD_PENDING", "obligations are not erased"
    assert reopened["unresolved_discrepancy_count"] == 1

    new_spot = book_spot_ok(env["order"]["id"], env["log"]["id"])
    assert new_spot["status"] == "SCHEDULED", "booking works in the reopened window"


def test_reopen_loop_completes_to_reconciled_after_credit(api):
    """PRD §3.8: "with a later as-run-import re-evaluating spots still in
    `SCHEDULED` or `AIRED`" and PRD §3.7: "**Issue-credit** — by a
    `BillingAdmin`, optionally carrying a `note` — closes the obligation with
    no successor; for spots this is straightforward because no billing occurred
    for non-AIRED spots and any TRADE reversal already posted at
    `MAKE_GOOD_PENDING` time. Issue-credit also auto-resolves the linked
    Discrepancy."

    Design: Difficulty/non_linear_state_machine/daily_log_reopen_loop_reconciling_to_locked_and_back
    """
    env = _setup_reconciling_log_with_missed_spot(api)
    get_success_data(api.reopen_log(env["log"]["id"], TD))
    s2 = book_spot_ok(env["order"]["id"], env["log"]["id"])

    # Second import: the new spot airs; the make-good-pending spot persists.
    imported = import_as_run_ok(env["log"]["id"], aired_spot_ids=[s2["id"]])
    s2_after = get_success_data(api.get_spot(s2["id"], TD))
    assert s2_after["status"] == "AIRED"
    assert imported["posture"] == "AS_RUN"

    get_success_data(api.begin_reconciliation(env["log"]["id"], TD))
    credited = get_success_data(
        api.issue_spot_credit(env["spot"]["id"], {"note": "preempt credit"},
                              make_billing_admin_headers("ba-1"))
    )
    assert credited["status"] == "RESOLVED"

    reconciled = get_success_data(
        api.reconcile_log(env["log"]["id"], make_headers("TrafficDirector", "td-1"))
    )
    assert reconciled["posture"] == "RECONCILED"
    assert reconciled["unresolved_discrepancy_count"] == 0
    assert_daily_log(reconciled)
