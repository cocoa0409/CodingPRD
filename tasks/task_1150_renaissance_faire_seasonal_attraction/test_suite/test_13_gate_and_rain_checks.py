"""Gate redemption, rain checks, and the conserved outstanding-admissions ledger."""
from test_helpers import (
    ApiErrorId,
    get_day,
    get_season,
    make_build_season,
    make_faire_day,
    make_paid_order,
    rain_checks_of_day,
    rain_checks_of_ticket,
    set_clock,
    setup_conservation_scenario,
    setup_issued_rain_check,
    setup_priority_raincheck_scenario,
    tickets_of_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, GATE, OPERATOR
from test_helpers.test_users import make_guest_headers


def test_redeem_ticket_not_valid_and_day_guards(api, gate_agent_headers):
    """PRD §3.7: "At the gate, a `GateAgent` redeems a ticket that must stand
    `VALID` (else `ERR_TICKET_NOT_VALID`). For a `DAY` ticket, its own faire day
    must be `OPERATING`; for a `SEASON` pass, some faire day of the season must be
    `OPERATING` on the clock's current calendar date; either failure is
    `ERR_DAY_NOT_OPERATING`."

    Design: Corner/validations/redeem_ticket_not_valid_and_day_guards
    """
    set_clock()
    season = make_build_season(name="ScanGuard Revel", volunteer_min_hours=0)
    day1 = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    day2 = make_faire_day(season["id"], "2026-06-07T00:00:00Z")
    season = validate_success(api.open_season(season["id"], OPERATOR), 200)
    validate_success(api.open_sales(day1["id"], OPERATOR), 200)
    validate_success(api.open_sales(day2["id"], OPERATOR), 200)
    order_a = make_paid_order(season["id"], "g-a@example.com", "DAY", 1, 3000, day1["id"])
    order_b = make_paid_order(season["id"], "g-b@example.com", "DAY", 1, 3000, day2["id"])
    validate_success(api.cancel_weather(day2["id"], OPERATOR), 200)

    # VALID ticket whose day never opened gates: the day gate fires.
    ticket_a = tickets_of_order(order_a["id"])[0]
    res = api.redeem_ticket(ticket_a["id"], gate_agent_headers)
    validate_error(res, ApiErrorId.ERR_DAY_NOT_OPERATING, expected_status=409)

    # RAINCHECKED ticket: the state gate fires.
    ticket_b = tickets_of_order(order_b["id"])[0]
    assert ticket_b["status"] == "RAINCHECKED"
    res = api.redeem_ticket(ticket_b["id"], gate_agent_headers)
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_VALID, expected_status=409)


def test_rain_check_target_terminal_day_rejected(api):
    """PRD §3.7: "Four gates guard the exchange, each with its own error: the check
    must be `ISSUED` (else `ERR_RAIN_CHECK_NOT_ISSUED`); the clock must be on or
    before the check's `redeem_by_date` (else `ERR_RAIN_CHECK_EXPIRED`); the target
    day must be `SCHEDULED` or `OPEN_FOR_SALES` (else `ERR_DAY_NOT_REDEEMABLE`); and
    the target day must have room, its `tickets_sold_count` plus one staying at or
    below the season's `daily_capacity` (else `ERR_DAY_AT_CAPACITY`)."

    Design: Corner/validations/rain_check_target_terminal_day_rejected
    """
    set_clock()
    season, source_day, target_day, order, checks = setup_issued_rain_check(
        quantity=1, buyer_email="g-t2@example.com"
    )
    # Cancel the would-be target day too, leaving it terminal.
    validate_success(api.cancel_weather(target_day["id"], OPERATOR), 200)

    res = api.redeem_rain_check(
        checks[0]["id"],
        {"target_faire_day_id": target_day["id"]},
        make_guest_headers("g-t2@example.com"),
    )
    validate_error(res, ApiErrorId.ERR_DAY_NOT_REDEEMABLE, expected_status=409)
    check_after = validate_success(api.get_rain_check(checks[0]["id"], ANY), 200)
    assert check_after["status"] == "ISSUED"


def test_rain_check_double_redeem_rejected(api):
    """PRD §3.7: "the check must be `ISSUED` (else `ERR_RAIN_CHECK_NOT_ISSUED`)"
    PRD §3.7: "On success the check becomes `REDEEMED`, its `redeemed_on_day_id`
    records the target day, and a fresh `DAY` ticket in `VALID` status is minted for
    the target day under the same `order_id` as the source ticket"

    Design: Corner/errors/rain_check_double_redeem_rejected
    """
    set_clock()
    season, source_day, target_day, order, checks = setup_issued_rain_check(
        quantity=1, buyer_email="g-dr@example.com"
    )
    validate_success(
        api.redeem_rain_check(
            checks[0]["id"],
            {"target_faire_day_id": target_day["id"]},
            make_guest_headers("g-dr@example.com"),
        ),
        200,
    )

    res = api.redeem_rain_check(
        checks[0]["id"],
        {"target_faire_day_id": target_day["id"]},
        make_guest_headers("g-dr@example.com"),
    )
    validate_error(res, ApiErrorId.ERR_RAIN_CHECK_NOT_ISSUED, expected_status=409)

    # Exactly one ticket was minted onto the target day by the first redeem.
    assert get_day(target_day["id"])["tickets_sold_count"] == 1


def test_raincheck_redeem_at_exact_redeem_by_succeeds(api):
    """PRD §3.7: "the clock must be on or before the check's `redeem_by_date` (else
    `ERR_RAIN_CHECK_EXPIRED`)"
    PRD §3.6: "one rain check in `ISSUED` status is created per such ticket,
    stamped with the season's `season_id`, the source `ticket_id`, and the
    cancelled day as `issued_for_day_id`, with `redeem_by_date` set to the season's
    `closing_date` plus its `rain_check_grace_days` days"

    Design: Difficulty/boundary_precision_check/raincheck_redeem_by_inclusive_date
    """
    set_clock()
    season, source_day, target_day, order, checks = setup_issued_rain_check(
        quantity=2, buyer_email="g-pair@example.com", rain_check_grace_days=14
    )
    # closing 2026-06-20 + 14 days -> redeem_by 2026-07-04T00:00:00Z.
    set_clock("2026-07-04T00:00:00Z")
    redeemed = validate_success(
        api.redeem_rain_check(
            checks[0]["id"],
            {"target_faire_day_id": target_day["id"]},
            make_guest_headers("g-pair@example.com"),
        ),
        200,
    )
    assert redeemed["status"] == "REDEEMED"
    assert redeemed["redeemed_on_day_id"] == target_day["id"]


def test_raincheck_redeem_one_second_past_redeem_by_rejected(api):
    """PRD §3.7: "the clock must be on or before the check's `redeem_by_date` (else
    `ERR_RAIN_CHECK_EXPIRED`)" — one second past the boundary is no longer on or
    before it.

    Design: Difficulty/boundary_precision_check/raincheck_redeem_by_inclusive_date
    """
    set_clock()
    season, source_day, target_day, order, checks = setup_issued_rain_check(
        quantity=2, buyer_email="g-pair@example.com", rain_check_grace_days=14
    )
    set_clock("2026-07-04T00:00:01Z")
    res = api.redeem_rain_check(
        checks[1]["id"],
        {"target_faire_day_id": target_day["id"]},
        make_guest_headers("g-pair@example.com"),
    )
    validate_error(res, ApiErrorId.ERR_RAIN_CHECK_EXPIRED, expected_status=409)


def test_raincheck_expiry_beats_capacity_constraint(api):
    """PRD §2.9: "the server evaluates them in a fixed nine-layer order, and the
    first failing layer determines the error returned" — clock-relative gates
    (layer 7: "rain-check redemption on or before `redeem_by_date`
    (`ERR_RAIN_CHECK_EXPIRED`)") precede the constraint layer (layer 8: "day
    admission capacity (`ERR_DAY_AT_CAPACITY`)").

    Design: Difficulty/priority_pair_validation_conflict/raincheck_expiry_beats_capacity_constraint
    """
    ctx = setup_priority_raincheck_scenario()
    # Past the check's redeem_by (closing 2026-06-20 + 14 days = 2026-07-04).
    set_clock("2026-07-05T00:00:00Z")
    res = api.redeem_rain_check(
        ctx["check"]["id"],
        {"target_faire_day_id": ctx["day2_id"]},
        make_guest_headers("g-one@example.com"),
    )
    # Both the expiry gate and the capacity gate (day sold out, capacity 1) are
    # violated; the temporal error must win.
    validate_error(res, ApiErrorId.ERR_RAIN_CHECK_EXPIRED, expected_status=409)


def test_capacity_fires_when_check_not_expired(api):
    """PRD §3.7: "the target day must have room, its `tickets_sold_count` plus one
    staying at or below the season's `daily_capacity` (else
    `ERR_DAY_AT_CAPACITY`)" — the capacity constraint fires in its own right once
    the clock-relative gate passes (clock still before `redeem_by_date`).

    Design: Difficulty/priority_pair_validation_conflict/raincheck_expiry_beats_capacity_constraint
    """
    ctx = setup_priority_raincheck_scenario()
    # Clock stays at the 2026-05-01 default: well within the redemption window.
    res = api.redeem_rain_check(
        ctx["check"]["id"],
        {"target_faire_day_id": ctx["day2_id"]},
        make_guest_headers("g-one@example.com"),
    )
    validate_error(res, ApiErrorId.ERR_DAY_AT_CAPACITY, expected_status=409)


def test_outstanding_admissions_conserved_across_cancel(api):
    """PRD §2.10: "A season's `outstanding_admissions` equals the count of its
    tickets in `VALID` status plus the count of its rain checks in `ISSUED` status.
    The figure is conserved across each compensating pair: a weather cancellation
    converts one `VALID` ticket into one `ISSUED` rain check for a net change of
    zero"
    PRD §3.6: "each owning order's `redemption_status` is recomputed, becoming
    `RAINCHECKED` when all of its tickets now stand rain-checked, while the
    season's `outstanding_admissions` does not move — each `VALID` ticket converts
    one-for-one into an `ISSUED` check."

    Design: Difficulty/compensating_invariant/outstanding_admissions_conserved_across_cancel_and_redeem
    """
    ctx = setup_conservation_scenario()
    before = get_season(ctx["season_id"])
    assert before["outstanding_admissions"] == 5

    validate_success(api.cancel_weather(ctx["day1_id"], OPERATOR), 200)

    mid = get_season(ctx["season_id"])
    assert mid["outstanding_admissions"] == 5
    # All five tickets rain-checked 1:1 into ISSUED checks.
    checks = rain_checks_of_day(ctx["day1_id"])
    assert len(checks) == 5
    for check in checks:
        assert check["status"] == "ISSUED"


def test_outstanding_admissions_conserved_across_redeem(api):
    """PRD §2.10: "a rain-check redemption consumes one `ISSUED` check while minting
    one `VALID` ticket, again net zero."
    PRD §3.7: "the season's `outstanding_admissions` is unchanged, one `ISSUED`
    check consumed against one `VALID` ticket minted."

    Design: Difficulty/compensating_invariant/outstanding_admissions_conserved_across_cancel_and_redeem
    """
    ctx = setup_conservation_scenario()
    validate_success(api.cancel_weather(ctx["day1_id"], OPERATOR), 200)

    tickets_a = tickets_of_order(ctx["order_a"]["id"])
    check1 = rain_checks_of_ticket(tickets_a[0]["id"])[0]
    check2 = rain_checks_of_ticket(tickets_a[1]["id"])[0]
    for check in (check1, check2):
        validate_success(
            api.redeem_rain_check(
                check["id"],
                {"target_faire_day_id": ctx["day2_id"]},
                make_guest_headers("ga@example.com"),
            ),
            200,
        )

    after = get_season(ctx["season_id"])
    # 2 ISSUED checks consumed against 2 fresh VALID tickets: still 5.
    assert after["outstanding_admissions"] == 5
    assert get_day(ctx["day2_id"])["tickets_sold_count"] == 2
