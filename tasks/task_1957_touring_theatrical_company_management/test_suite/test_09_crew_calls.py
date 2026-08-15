"""Crew calls: settlement pay tiers, cancellation window, complement rule (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    PRODUCER,
    TOUR_MANAGER,
    cancel_crew_call,
    create_crew_call,
    create_crew_call_payload,
    create_tech_check,
    get_success_data,
    record_check_actual,
    set_clock,
    settle_crew_call,
    setup_advanced_stop,
    validate_error,
    validate_success,
)


def test_crew_overtime_exact_eight_hours(api):
    """PRD §3.5: "Settlement computes `total_pay_cents` line by line, in a pinned rounding order: for each line, take `hours_worked`; the first eight hours are paid straight at the line’s rate; the next four hours — the portion of hours beyond eight, up to a cap of four — are paid at one and a half times the rate; any hours beyond twelve are paid at double the rate."
    PRD §3.5: "Exactly eight hours pays no overtime, and at exactly twelve hours
    the double-time component is zero."

    Design: Difficulty/boundary_precision_check/crew_overtime_exact_eight_hours
    """
    ctx = setup_advanced_stop()
    cc = create_crew_call(ctx["stop"]["id"], lines=[
        {"position": "carpenter", "rate_cents_per_hour": 2000},
        {"position": "rigger", "rate_cents_per_hour": 2000},
    ])
    settled = settle_crew_call(cc["id"], ("carpenter", 8), ("rigger", 8.25))
    # 8.00h exactly: 8 x 2000 = 16,000 with zero overtime (boundary inclusive).
    # 8.25h: 16,000 + 0.25 x 2000 x 1.5 = 16,750.
    assert settled["total_pay_cents"] == 32_750


def test_crew_overtime_exact_twelve_hours(api):
    """PRD §3.5: "Exactly eight hours pays no overtime, and at exactly twelve
    hours the double-time component is zero."
    PRD §3.5: "The line total is the sum of those three components rounded half-up to whole cents, and the call’s `total_pay_cents` is the sum of the per-line totals — rounding happens once per line, never on the grand sum."

    Design: Difficulty/boundary_precision_check/crew_overtime_exact_eight_hours
    """
    ctx = setup_advanced_stop()
    cc = create_crew_call(ctx["stop"]["id"])
    settled = settle_crew_call(cc["id"], ("carpenter", 12))
    # 8 x 2000 + 4 x 2000 x 1.5 + 0 double-time = 16,000 + 12,000.
    assert settled["total_pay_cents"] == 28_000


def test_crew_cancel_penalty_window(api):
    """PRD §3.5: "Cancellation measures the call’s `scheduled_start` against the logical clock: if fewer than 24 hours remain, every planned line accrues a show-up penalty of four hours at its rate, each line’s penalty rounded half-up individually and then summed into the call’s `cancellation_penalty_cents`; with 24 hours or more remaining — exactly 24 hours included — the penalty is zero."

    Design: Corner/calculations/crew_cancel_penalty_window
    """
    ctx = setup_advanced_stop()
    stop_id = ctx["stop"]["id"]
    set_clock("2026-08-01T12:00:00Z")

    cc1 = create_crew_call(stop_id, scheduled_start="2026-08-02T10:00:00Z", lines=[
        {"position": "carpenter", "rate_cents_per_hour": 2000},
        {"position": "rigger", "rate_cents_per_hour": 2050},
    ])
    cc2 = create_crew_call(stop_id, call_type="LOAD_OUT",
                           scheduled_start="2026-08-02T12:00:00Z", lines=[
        {"position": "carpenter", "rate_cents_per_hour": 2000},
        {"position": "rigger", "rate_cents_per_hour": 2050},
    ])

    cancelled1 = cancel_crew_call(cc1["id"])  # 22h out
    # Per line: 4h x rate -> 8,000 + 8,200 = 16,200.
    assert cancelled1["cancellation_penalty_cents"] == 16_200

    cancelled2 = cancel_crew_call(cc2["id"])  # exactly 24h out
    assert cancelled2["cancellation_penalty_cents"] == 0, (
        "The penalty triggers strictly inside 24 hours; == 24h pays zero"
    )


def test_crew_settle_twice_returns_invalid_state(api):
    """PRD §3.5: "Settling is legal only from `POSTED`, else
    `ERR_CREW_INVALID_STATE`."

    Design: Corner/state_machines/crew_settle_twice_returns_invalid_state
    """
    ctx = setup_advanced_stop()
    cc = create_crew_call(ctx["stop"]["id"])
    settled = settle_crew_call(cc["id"], ("carpenter", 8))
    assert settled["total_pay_cents"] == 16_000

    resp = api.put_crew_call(cc["id"],
                             {"status": "SETTLED",
                              "actual_lines": [{"position": "carpenter",
                                                "hours_worked": 12}]},
                             TOUR_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CREW_INVALID_STATE)

    calls = get_success_data(api.list_crew_calls(ctx["stop"]["id"], PRODUCER))
    stored = next(c for c in calls if c["id"] == cc["id"])
    assert stored["total_pay_cents"] == 16_000, "Rejected re-settle must not move totals"


def test_crew_complement_minimum_enforced_when_check_present(api):
    """PRD §3.5: "The crew-complement rule guards the post: when the stop carries a `CREW_MINIMUM` tech check standing at `PASS` or `WAIVED`, the number of lines on the call must be at least that check’s `required_value`; and regardless of rider checks, the line count must not exceed the venue’s `crew_available`. Violations are rejected with `ERR_CREW_COMPLEMENT_SHORT`."

    Design: Corner/validations/crew_complement_minimum_enforced_when_check_present
    """
    ctx = setup_advanced_stop()
    stop_id = ctx["stop"]["id"]
    chk = create_tech_check(stop_id, item="CREW_MINIMUM", required_value=3)
    record_check_actual(chk["id"], 20)  # PASS

    resp = api.create_crew_call(
        stop_id,
        create_crew_call_payload(lines=[
            {"position": "carpenter", "rate_cents_per_hour": 2000},
            {"position": "rigger", "rate_cents_per_hour": 2050},
        ]),
        TOUR_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_COMPLEMENT_SHORT)


def test_crew_minimum_absent_allows_small_call(api):
    """PRD §3.5: "The crew-complement rule guards the post: when the stop carries a `CREW_MINIMUM` tech check standing at `PASS` or `WAIVED`, the number of lines on the call must be at least that check’s `required_value`; and regardless of rider checks, the line count must not exceed the venue’s `crew_available`."
    PRD §3.5: "A posted call is `POSTED`."

    Design: Corner/validations/crew_minimum_absent_allows_small_call
    """
    ctx = setup_advanced_stop()
    # No CREW_MINIMUM check on the stop; one line is within venue capacity (20).
    cc = create_crew_call(ctx["stop"]["id"])
    assert cc["status"] == "POSTED"
