"""Recurring bills and cash-flow forecast: chronological same-day ordering, paused
exclusion, no-shortfall horizon, slot-conflict, resume-invalid-state.

Translates Difficulty queue (A) combinatorial_formula (cash flow),
resource_temporal_overlap (bill slot) and Corner queue (B) calculations/state_machines
(forecast, bills).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_forecast_scenario, create_bill, set_clock,
    setup_household_period_category,
)


def test_cash_flow_same_day_bills_chronological_min(api):
    """PRD §3.7: "On each day, every SCHEDULED bill whose day_of_month equals that calendar
    day's day-of-number has its amount_cents subtracted from the running balance".
    PRD §3.7: "When several bills fall due on the same day, they are applied in ascending
    order of day_of_month and then earliest created_at (the tie-break is created_at, never
    id)."

    Design: Difficulty/combinatorial_formula/cash_flow_chronological_same_day_order
    """
    ctx = setup_forecast_scenario(
        clock_iso="2026-02-01T00:00:00Z", month="2026-02",
        opening_balance_cents=10000,
        bills=[
            {"payee": "A", "amount_cents": 4000, "day_of_month": 5},
            {"payee": "B", "amount_cents": 7000, "day_of_month": 5},
        ],
    )
    resp = api.cash_flow_forecast(
        ctx["household"]["id"], ctx["owner_headers"], params={"horizon_days": 30})
    data = validate_success(resp)
    assert data["min_projected_balance_cents"] == -1000, \
        f"10000 - 4000 - 7000 = -1000, got {data['min_projected_balance_cents']}"
    assert data["shortfall"] is True, \
        f"min < 0 -> shortfall true, got {data['shortfall']}"


def test_cash_flow_no_shortfall_within_horizon(api):
    """PRD §3.7: "After the walk, min_projected_balance_cents is the minimum
    projected_balance_cents across all points, and shortfall is true exactly when that
    minimum is below zero."

    Design: Corner/calculations/cash_flow_no_shortfall_within_horizon
    """
    ctx = setup_forecast_scenario(
        clock_iso="2026-02-01T00:00:00Z", month="2026-02",
        opening_balance_cents=10000,
        bills=[{"payee": "Net", "amount_cents": 3000, "day_of_month": 10}],
    )
    resp = api.cash_flow_forecast(
        ctx["household"]["id"], ctx["owner_headers"], params={"horizon_days": 30})
    data = validate_success(resp)
    assert data["min_projected_balance_cents"] == 7000, \
        f"10000 - 3000 = 7000, got {data['min_projected_balance_cents']}"
    assert data["shortfall"] is False, \
        f"min >= 0 -> shortfall false, got {data['shortfall']}"


def test_cash_flow_starting_cash_only_minus_one_bill(api):
    """PRD §3.7: "The forecast starts from the household's current cash balance, defined as
    the sum of cleared_balance_cents across the household's LINKED DEPOSITORY accounts
    only".

    Design: Difficulty/combinatorial_formula/cash_flow_chronological_same_day_order
    """
    ctx = setup_forecast_scenario(
        clock_iso="2026-02-01T00:00:00Z", month="2026-02",
        opening_balance_cents=20000,
        bills=[
            {"payee": "X", "amount_cents": 5000, "day_of_month": 7},
            {"payee": "Y", "amount_cents": 6000, "day_of_month": 14},
        ],
    )
    resp = api.cash_flow_forecast(
        ctx["household"]["id"], ctx["owner_headers"], params={"horizon_days": 30})
    data = validate_success(resp)
    # 20000 -> day7 -5000 = 15000 -> day14 -6000 = 9000; min is 9000.
    assert data["min_projected_balance_cents"] == 9000, \
        f"20000 - 5000 - 6000 = 9000, got {data['min_projected_balance_cents']}"
    assert data["shortfall"] is False


def test_paused_bill_excluded_from_forecast(api):
    """PRD §3.7: "A bill may be paused by an owner or member, moving its status from
    SCHEDULED to PAUSED, which removes it from the cash-flow forecast".
    PRD §3.7: "Paused bills are excluded entirely."

    Design: Corner/calculations/paused_bill_excluded_from_forecast
    """
    ctx = setup_forecast_scenario(
        clock_iso="2026-02-01T00:00:00Z", month="2026-02",
        opening_balance_cents=10000,
        bills=[{"payee": "Big", "amount_cents": 9000, "day_of_month": 5}],
    )
    bill = ctx["bills"][0]
    validate_success(api.pause_recurring_bill(
        ctx["household"]["id"], bill["id"], ctx["owner_headers"]))
    resp = api.cash_flow_forecast(
        ctx["household"]["id"], ctx["owner_headers"], params={"horizon_days": 30})
    data = validate_success(resp)
    assert data["min_projected_balance_cents"] == 10000, \
        f"paused bill excluded -> stays 10000, got {data['min_projected_balance_cents']}"
    assert data["shortfall"] is False


def test_recurring_bill_due_day_buffer_collision(api):
    """PRD §3.7: "a new or resuming SCHEDULED bill conflicts with an existing SCHEDULED bill
    in the household when they share the same payee and the existing bill's day_of_month
    falls within plus-or-minus two days of the new bill's day_of_month, with the
    day-of-month window cyclically clamped to the 1-to-28 domain; such a conflict is
    rejected with ERR_BILL_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/recurring_bill_due_day_buffer_collision
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        month="2026-01", income_expected_cents=0, cat_name="Bills", allocated_cents=0)
    create_bill(hh["id"], owner_headers, cat["id"], payee="Rent",
                amount_cents=120000, day_of_month=15)
    resp = api.create_recurring_bill(
        hh["id"],
        {"payee": "Rent", "amount_cents": 120000, "day_of_month": 16,
         "funding_category_id": cat["id"]},
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BILL_SLOT_CONFLICT)


def test_recurring_bill_same_day_same_payee_collision(api):
    """PRD §3.7: "they share the same payee and the existing bill's day_of_month falls
    within plus-or-minus two days of the new bill's day_of_month".
    PRD §3.7: "This same slot-conflict rule is applied both when creating a bill and when
    resuming one."

    Design: Difficulty/resource_temporal_overlap/recurring_bill_due_day_buffer_collision
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        month="2026-01", income_expected_cents=0, cat_name="Bills", allocated_cents=0)
    create_bill(hh["id"], owner_headers, cat["id"], payee="Gym",
                amount_cents=3000, day_of_month=10)
    # Exact same day, same payee -> within +/-2 buffer -> conflict.
    resp = api.create_recurring_bill(
        hh["id"],
        {"payee": "Gym", "amount_cents": 3000, "day_of_month": 10,
         "funding_category_id": cat["id"]},
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BILL_SLOT_CONFLICT)


def test_resume_scheduled_bill_returns_invalid_state(api):
    """PRD §3.7: "it may be resumed, moving from PAUSED back to SCHEDULED".
    PRD §2.7: "for transition endpoints, the target must currently be in a state from which
    the requested transition is defined, otherwise ERR_INVALID_STATE."

    Design: Corner/state_machines/resume_scheduled_bill_returns_invalid_state
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        month="2026-01", income_expected_cents=0, cat_name="Bills", allocated_cents=0)
    bill = create_bill(hh["id"], owner_headers, cat["id"], payee="Rent",
                       amount_cents=5000, day_of_month=1)
    resp = api.resume_recurring_bill(hh["id"], bill["id"], owner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
