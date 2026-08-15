"""Endorsement contracts, live reads, and remote events: status gates,
program windows, contracted totals, close threshold, settle gate
(PRD §3.7, §3.10, §3.11)."""
from test_helpers import (
    BA,
    TD,
    ApiErrorId,
    api_client,
    book_spot_ok,
    create_active_contract,
    create_active_order,
    create_endorsement_contract,
    create_locked_log,
    create_remote_event_payload,
    create_station,
    drive_log_to_affidavit,
    get_success_data,
    import_as_run_ok,
    list_discrepancies,
    make_headers,
    make_sales_rep_headers,
    reconcile_log_as,
    schedule_live_read,
    schedule_live_read_ok,
    set_clock,
    setup_bookable_station,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

FRI_LOG_DATE = "2026-05-01"  # a Friday
WED_LOG_DATE = "2026-05-06"  # a Wednesday


def _live_read_clock_env(weekday="WED", hour=7, capacity_units=2, capacity_seconds=120):
    return setup_bookable_station(
        weekday=weekday, daypart="MORNING_DRIVE", hour=hour,
        slot_type="LIVE_READ_WINDOW",
        capacity_units=capacity_units, capacity_seconds=capacity_seconds,
    )


def test_live_read_gated_by_endorsement_contract_status_draft_rejected(api):
    """PRD §3.10: "Scheduling a live read — a `TrafficDirector` operation with
    `contract_id`, `log_id`, `hour`, and optional `duration_sec` (defaulting to
    60; allowed values are 30 and 60) — requires the contract be `ACTIVE`
    (`ERR_CONTRACT_NOT_ACTIVE` otherwise)".

    Design: Difficulty/cross_entity_state_dependency/live_read_gated_by_endorsement_contract_status
    """
    env = _live_read_clock_env()
    contract = create_endorsement_contract(env["station"]["id"])  # stays DRAFT
    log = create_locked_log(env["station"]["id"], log_date=WED_LOG_DATE)

    resp = schedule_live_read(contract["id"], log["id"], hour=7)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
    assert resp.status_code == 409


def test_live_read_gated_by_endorsement_contract_status_active_ok(api):
    """PRD §3.10: "the system computes `contracted_reads_total` as
    `reads_per_week` times the number of whole weeks in the window — that is,
    the floor of (window length in days) divided by 7, where the window length
    counts both `start_date` and `end_date`; a partial trailing week does not
    add reads."

    Design: Difficulty/cross_entity_state_dependency/live_read_gated_by_endorsement_contract_status
    """
    env = _live_read_clock_env()
    contract = create_endorsement_contract(env["station"]["id"])  # WED 6-9, 2/week, May
    assert contract["contracted_reads_total"] == 8, "2 reads/week x floor(31/7) = 4 weeks"
    contract = get_success_data(
        api.activate_endorsement_contract(contract["id"], make_headers("SalesManager", "mgr-1"))
    )
    assert contract["status"] == "ACTIVE"
    log = create_locked_log(env["station"]["id"], log_date=WED_LOG_DATE)

    read = schedule_live_read_ok(contract["id"], log["id"], hour=7)
    assert read["status"] == "SCHEDULED"


def test_live_read_outside_program_window_end_hour_excluded(api):
    """PRD §3.10: "the half-open program window from `program_start_hour` up to
    but not including `program_end_hour`" and "the weekday of `air_date` to be
    in `program_weekdays`, the `hour` to satisfy the program window,
    `air_date` to lie inside the contract window (violations yield
    `ERR_CONTRACT_WINDOW_VIOLATION`)".

    Design: Corner/validations/live_read_outside_program_window_end_hour_excluded
    """
    env = _live_read_clock_env(weekday="FRI", hour=9)
    contract = create_active_contract(
        env["station"]["id"], program_weekdays=["FRI"],
        program_start_hour=6, program_end_hour=9, reads_per_week=1,
    )
    log = create_locked_log(env["station"]["id"], log_date=FRI_LOG_DATE)

    resp = schedule_live_read(contract["id"], log["id"], hour=9)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_VIOLATION)


def test_contracted_reads_total_floors_partial_weeks(api):
    """PRD §3.10: "the system computes `contracted_reads_total` as
    `reads_per_week` times the number of whole weeks in the window — that is,
    the floor of (window length in days) divided by 7, where the window length
    counts both `start_date` and `end_date`; a partial trailing week does not
    add reads."

    Design: Corner/calculations/contracted_reads_total_floors_partial_weeks
    """
    station = create_station()
    contract = create_endorsement_contract(
        station["id"], reads_per_week=3,
        start_date="2026-05-01", end_date="2026-05-06",
    )
    assert contract["contracted_reads_total"] == 0, "3 x floor(6/7) = 0"


def test_contract_close_completed_vs_breached_threshold(api):
    """PRD §3.10: "Closing (from `ACTIVE`) requires the clock to be strictly
    past `end_date`; if `reads_completed` — the count of this contract's live
    reads in `AIRED` — is at least `contracted_reads_total`, the contract
    transitions to `COMPLETED`, otherwise to `BREACHED`."

    Design: Corner/state_machines/contract_close_completed_vs_breached_threshold
    """
    env = _live_read_clock_env(weekday="FRI", hour=7)
    station_id = env["station"]["id"]
    contract_a = create_active_contract(
        station_id, program_weekdays=["FRI"], program_start_hour=6, program_end_hour=9,
        reads_per_week=1, start_date="2026-05-01", end_date="2026-05-07",
    )
    contract_b = create_active_contract(
        station_id, program_weekdays=["FRI"], program_start_hour=6, program_end_hour=9,
        reads_per_week=2, start_date="2026-05-01", end_date="2026-05-07",
    )
    log = create_locked_log(station_id, log_date=FRI_LOG_DATE)
    read_a = schedule_live_read_ok(contract_a["id"], log["id"], hour=7)
    import_as_run_ok(log["id"], aired_live_read_ids=[read_a["id"]])

    set_clock("2026-05-08T00:00:00Z")  # strictly past end_date for both

    closed_a = get_success_data(
        api.close_endorsement_contract(contract_a["id"], make_headers("SalesManager", "mgr-1"))
    )
    assert closed_a["status"] == "COMPLETED", "1 >= 1: boundary >= completes"
    assert closed_a["reads_completed"] == 1, "only AIRED live reads count"

    closed_b = get_success_data(
        api.close_endorsement_contract(contract_b["id"], make_headers("SalesManager", "mgr-1"))
    )
    assert closed_b["status"] == "BREACHED", "0 < 2: below the contracted total"


def test_remote_event_settle_gate_delivered_defaulted(api):
    """PRD §3.11: "Settlement (`CONFIRMED → DELIVERED` or `CONFIRMED →
    DEFAULTED`) is gated cross-entity on the DailyLog for (`station_id`,
    `event_date`) existing and being in `AFFIDAVIT_ISSUED` or `CLOSED`
    posture." and "When `spots_delivered` is at least `spot_units_promised` —
    equality delivers — the event transitions to `DELIVERED`; otherwise to
    `DEFAULTED`."

    Design: Corner/state_machines/remote_event_settle_gate_delivered_defaulted
    """
    env = setup_bookable_station(
        weekday="FRI", daypart="AFTERNOON_DRIVE", hour=18,
        capacity_units=5, capacity_seconds=300,
    )
    station_id = env["station"]["id"]
    order = create_active_order(
        station_id, daypart_targets=[{"daypart": "AFTERNOON_DRIVE", "units": 1}]
    )
    e1 = get_success_data(api.create_remote_event(
        create_remote_event_payload(station_id, event_date=FRI_LOG_DATE, spot_units_promised=1),
        make_sales_rep_headers("rep-1"),
    ))
    e2 = get_success_data(api.create_remote_event(
        create_remote_event_payload(station_id, event_date=FRI_LOG_DATE, spot_units_promised=2,
                                    package_price_cents=90000),
        make_sales_rep_headers("rep-1"),
    ))
    get_success_data(api.confirm_remote_event(e1["id"], make_headers("SalesManager", "mgr-1")))
    get_success_data(api.confirm_remote_event(e2["id"], make_headers("SalesManager", "mgr-1")))

    log = create_locked_log(station_id, log_date=FRI_LOG_DATE)
    spot = book_spot_ok(order["id"], log["id"], daypart="AFTERNOON_DRIVE", hour=18,
                        event_id=e1["id"])
    import_as_run_ok(log["id"], aired_spot_ids=[spot["id"]])
    reconcile_log_as(log["id"], td_user_id="td-1")

    # Gate: log only RECONCILED (no affidavit yet) -> settle rejected.
    resp = api.settle_remote_event(e2["id"], make_headers("SalesManager", "mgr-1"))
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_LOG_POSTURE_BLOCKED]
    )

    get_success_data(api.issue_affidavit(log["id"], make_headers("BillingAdmin", "ba-1")))

    settled_e1 = get_success_data(
        api.settle_remote_event(e1["id"], make_headers("SalesManager", "mgr-1"))
    )
    assert settled_e1["status"] == "DELIVERED"
    assert settled_e1["spots_delivered"] == 1, "boundary: 1 >= 1 delivers"

    settled_e2 = get_success_data(
        api.settle_remote_event(e2["id"], make_headers("SalesManager", "mgr-1"))
    )
    assert settled_e2["status"] == "DEFAULTED", "0 delivered < 2 promised"


def test_live_read_reschedule_successor_linkage(api):
    """PRD §3.7: "Rescheduling a live read takes `target_log_id` and
    `target_hour`, requires the contract's program window to be satisfied for
    the target, and creates a successor with `makeup_of_live_read_id` set. In
    both cases, the linked `MISSED_SPOT` or `MISSED_READ` Discrepancy
    auto-transitions `UNRESOLVED → RESOLVED`."

    Design: Corner/endpoints/live_read_reschedule_successor_linkage
    """
    env = _live_read_clock_env(weekday="WED", hour=7)
    contract = create_active_contract(env["station"]["id"])  # WED 6-9, 2/week
    log = create_locked_log(env["station"]["id"], log_date=WED_LOG_DATE)
    read = schedule_live_read_ok(contract["id"], log["id"], hour=7)
    import_as_run_ok(log["id"])  # read missed -> MAKE_GOOD_PENDING + MISSED_READ

    # Reschedule requires the target log in DRAFT or LOCKED posture (PRD §3.7);
    # the import moved this log to AS_RUN, so reopen it first (PRD §3.8).
    get_success_data(api.begin_reconciliation(log["id"], TD))
    reopened = get_success_data(api.reopen_log(log["id"], TD))
    assert reopened["posture"] == "LOCKED"

    successor = get_success_data(
        api.reschedule_live_read(read["id"], {"target_log_id": log["id"], "target_hour": 7}, TD)
    )
    assert successor["status"] == "SCHEDULED"
    assert successor["makeup_of_live_read_id"] == read["id"]

    original = get_success_data(api.get_live_read(read["id"], TD))
    assert original["status"] == "RESOLVED"

    log_after = get_success_data(api.get_log(log["id"], TD))
    assert log_after["unresolved_discrepancy_count"] == 0, (
        "linked MISSED_READ discrepancy auto-RESOLVED"
    )
