"""Discrepancy management: under-coverage sweep, explicit resolve, kind-
restricted waiver; plus spot terminal-state lockdown (PRD §3.6, §3.7, §3.8)."""
from test_helpers import (
    BA,
    TD,
    ApiErrorId,
    api_client,
    book_spot_ok,
    create_active_clock,
    create_active_order,
    create_cleared_clearance,
    create_locked_log,
    create_station,
    get_success_data,
    import_as_run_ok,
    list_discrepancies,
    make_billing_admin_headers,
    make_headers,
    reconcile_log_as,
    setup_bookable_scenario,
    setup_bookable_station,
    validate_error,
    validate_success,
)


def test_discrepancy_unfilled_barter_explicit_resolve_flow(api):
    """PRD §3.7: "if the count of avails `AIRED` at a covered hour is below the
    clearance's `barter_avails_per_hour`, one `UNFILLED_BARTER` Discrepancy per
    (clearance, hour) is created with `barter_avail_id` null." and "a
    `TrafficDirector` may explicitly resolve only an `UNFILLED_BARTER`
    discrepancy, transitioning it `UNRESOLVED → RESOLVED`".

    Design: Corner/endpoints/discrepancy_unfilled_barter_explicit_resolve_flow
    """
    station = create_station()
    create_active_clock(
        station["id"], applies_weekdays=["MON"],
        slots=[{"slot_type": "SPOT_BREAK", "hour": 10, "capacity_units": 4, "capacity_seconds": 240}],
    )
    create_cleared_clearance(station["id"], start_hour=10, duration_hours=1)
    log = create_locked_log(station["id"], log_date="2026-05-04")

    imported = import_as_run_ok(log["id"])
    assert imported["unresolved_discrepancy_count"] == 1, (
        "pure under-coverage: 1 avail/hr required at hour 10, nothing scheduled"
    )

    discrepancies = list_discrepancies(log_id=log["id"], discrepancy_kind="UNFILLED_BARTER")
    assert len(discrepancies) == 1
    disc = discrepancies[0]
    assert disc["barter_avail_id"] is None, "under-coverage carries no avail reference"

    resolved = get_success_data(
        api.resolve_discrepancy(
            disc["id"], {"note": "replacement negotiated with network"}, TD
        )
    )
    assert resolved["status"] == "RESOLVED"

    get_success_data(api.begin_reconciliation(log["id"], TD))
    reconciled = get_success_data(
        api.reconcile_log(log["id"], make_headers("TrafficDirector", "td-1"))
    )
    assert reconciled["posture"] == "RECONCILED", "count back to 0 lets reconcile pass"


def test_discrepancy_waive_kind_restriction(api):
    """PRD §3.7: "a `BillingAdmin` may waive only an `UNFILLED_BARTER`
    discrepancy, transitioning it `UNRESOLVED → WAIVED` (any other kind is
    rejected with the same `ERR_DISCREPANCY_NOT_WAIVABLE`)".

    Design: Corner/validations/discrepancy_waive_kind_restriction
    """
    env = setup_bookable_station(weekday="MON", hour=6, capacity_units=10, capacity_seconds=600)
    station_id = env["station"]["id"]
    create_cleared_clearance(station_id, start_hour=10, duration_hours=1)
    order = create_active_order(
        station_id, daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 1}]
    )
    log = create_locked_log(station_id, log_date="2026-05-04")
    spot = book_spot_ok(order["id"], log["id"])

    import_as_run_ok(log["id"])  # airs nothing: MISSED_SPOT + UNFILLED_BARTER

    missed = list_discrepancies(log_id=log["id"], discrepancy_kind="MISSED_SPOT")
    unfilled = list_discrepancies(log_id=log["id"], discrepancy_kind="UNFILLED_BARTER")
    assert len(missed) == 1 and missed[0]["spot_id"] == spot["id"]
    assert len(unfilled) == 1

    resp = api.waive_discrepancy(
        missed[0]["id"], {"note": "try waiving a missed spot"},
        make_billing_admin_headers("ba-1"),
    )
    validate_error(resp, ApiErrorId.ERR_DISCREPANCY_NOT_WAIVABLE)
    still_open = get_success_data(api.get_discrepancy(missed[0]["id"], BA))
    assert still_open["status"] == "UNRESOLVED"

    waived = get_success_data(
        api.waive_discrepancy(
            unfilled[0]["id"], {"note": "network granted waiver"},
            make_billing_admin_headers("ba-1"),
        )
    )
    assert waived["status"] == "WAIVED"


def test_spot_cancel_aired_returns_invalid_state(api):
    """PRD §3.6: "Spots may be individually cancelled from `SCHEDULED` (by a
    `TrafficDirector`, while the log's posture is `DRAFT` or `LOCKED`)" and
    "Spot terminal states are `AIRED`, `RESOLVED`, and `CANCELLED`." Cancelling
    an AIRED spot is not a declared transition.

    Design: Corner/state_machines/spot_cancel_aired_returns_invalid_state
    """
    env = setup_bookable_scenario(units=1)
    spot = book_spot_ok(env["order"]["id"], env["log"]["id"])
    import_as_run_ok(env["log"]["id"], aired_spot_ids=[spot["id"]])

    aired = get_success_data(api.get_spot(spot["id"], TD))
    assert aired["status"] == "AIRED"

    resp = api.cancel_spot(spot["id"], TD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api.get_spot(spot["id"], TD))
    assert after["status"] == "AIRED", "spot stays AIRED after a rejected cancel"
