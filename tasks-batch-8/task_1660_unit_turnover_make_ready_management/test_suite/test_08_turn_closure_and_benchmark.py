"""Turn closure terminal lockdown and the property benchmark aggregates."""
from test_helpers import (
    PM,
    ApiErrorId,
    accept,
    add_scope_item,
    close_turn,
    complete,
    create_property,
    create_unit,
    create_vendor,
    finalize_turn,
    get_benchmark,
    get_turn,
    open_turn,
    pass_inspection,
    schedule,
    set_clock,
    setup_closed_turn,
    validate_error,
)


def test_benchmark_counts_closed_turns_only(api):
    """PRD §3.9: "Closure is what feeds the portfolio's memory: the property's
    benchmark aggregates are recomputed over exactly the set of that property's
    turns in `CLOSED` status, with cancelled and still-open turns excluded and
    no time window applied. `benchmark_turn_count` is the size of that set;
    `avg_booked_expense_cents` is the mean of those turns'
    `booked_expense_cents` — the overhead-loaded operating cost of §3.4 —
    rounded half up to a whole integer; and `avg_days_to_ready` is the mean of
    each closed turn's calendar-day span from `started_on` to
    `actual_ready_date`, likewise rounded half up. When no turn has ever
    closed, all three aggregates read zero."

    Design: Corner/calculations/property_benchmark_counts_closed_turns_only
    """
    prop = create_property()
    unit1 = create_unit(prop["id"], unit_number="101")
    unit2 = create_unit(prop["id"], unit_number="102")
    fixer = create_vendor("FixCo", "REPAIR")
    cleaner = create_vendor("CleanCo", "CLEAN")

    def build_turn(unit, repair_estimate, repair_actual):
        turn = open_turn(unit["id"])
        repair = add_scope_item(turn["id"], "REPAIR", repair_estimate)
        clean = add_scope_item(turn["id"], "CLEAN", 1000)
        finalize_turn(turn["id"])
        asg_r = schedule(repair["id"], fixer["id"], "2026-08-01", "2026-08-03")
        accept(asg_r["id"], fixer["id"])
        complete(asg_r["id"], fixer["id"], repair_actual)
        asg_c = schedule(clean["id"], cleaner["id"], "2026-08-03", "2026-08-04")
        accept(asg_c["id"], cleaner["id"])
        complete(asg_c["id"], cleaner["id"], 1010)
        return turn

    # T1 booked: 1010+25 twice = 2070. T2 booked: 2030+51 and 1010+25 = 3116.
    turn1 = build_turn(unit1, 1000, 1010)
    turn2 = build_turn(unit2, 2000, 2030)

    set_clock("2026-08-04T00:00:00Z")
    pass_inspection(turn1["id"])  # actual_ready 08-04, started 08-01 -> 3 days

    benchmark = get_benchmark(prop["id"])
    assert benchmark["benchmark_turn_count"] == 0
    assert benchmark["avg_booked_expense_cents"] == 0
    assert benchmark["avg_days_to_ready"] == 0
    assert get_turn(turn1["id"])["status"] == "READY", (
        "a READY-but-unclosed turn stays out of the benchmark"
    )

    close_turn(turn1["id"])
    benchmark = get_benchmark(prop["id"])
    assert benchmark["benchmark_turn_count"] == 1
    assert benchmark["avg_booked_expense_cents"] == 2070
    assert benchmark["avg_days_to_ready"] == 3

    set_clock("2026-08-05T00:00:00Z")
    pass_inspection(turn2["id"])  # 08-05 minus 08-01 -> 4 days
    close_turn(turn2["id"])
    benchmark = get_benchmark(prop["id"])
    assert benchmark["benchmark_turn_count"] == 2
    # round_half_up((2070 + 3116) / 2) = 2593; round_half_up((3 + 4) / 2) = 4.
    assert benchmark["avg_booked_expense_cents"] == 2593
    assert benchmark["avg_days_to_ready"] == 4


def test_cancel_closed_turn_rejected(api):
    """PRD §3.9: "A `PropertyManager` may cancel a turn while it is `OPEN` or
    `SCOPED`; against any later status the cancellation is rejected with
    `ERR_INVALID_STATE`, because work already in flight must be run to its
    conclusion."

    Design: Corner/state_machines/cancel_closed_turn_returns_invalid_state
    """
    ctx = setup_closed_turn(5000, 4000)
    assert get_turn(ctx["turn"]["id"])["status"] == "CLOSED"

    resp = api.cancel_turn(ctx["turn"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_turn(ctx["turn"]["id"])["status"] == "CLOSED", (
        "CLOSED is terminal: nothing else changes"
    )
