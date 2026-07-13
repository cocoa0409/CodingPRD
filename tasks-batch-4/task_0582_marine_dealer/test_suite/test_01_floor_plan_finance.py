"""Floor-plan finance: dual-variant accrual/payoff, curtailment boundary and guards."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    fixtures,
)

MANAGER = TEST_USERS["manager_headers"]


def test_floor_plan_accrued_interest_is_chronological_to_now(api):
    """PRD §3.2: "The `accrued_interest_cents` figure is the plain chronological
    interest to the present moment: the `outstanding_principal_cents` multiplied by
    `apr_bps`, divided by 10000, multiplied by the days outstanding, divided by 365
    days per year, and rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/floor_plan_payoff_forward_vs_chronological
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    _unit, fp = fixtures.create_floor_planned_unit(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 950,
                      "advanced_at": "2026-03-01T00:00:00Z", "curtailment_pct_bps": 1000},
    )
    data = validate_success(api.get_floor_plan(fp["id"], MANAGER))
    assert data["accrued_interest_cents"] == 191562, \
        f"Expected chronological accrual 191562, got {data['accrued_interest_cents']}"


def test_floor_plan_payoff_projects_ten_day_notice(api):
    """PRD §3.2: "The `payoff_cents` figure is instead forward-looking, quoting what
    it would cost to retire the plan after the lender's notice period: the day count is
    projected 10 days beyond the present instant, and the payoff equals the
    `outstanding_principal_cents` plus the interest computed on that projected day count"

    Design: Difficulty/dual_variant_calc/floor_plan_payoff_forward_vs_chronological
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    _unit, fp = fixtures.create_floor_planned_unit(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 950,
                      "advanced_at": "2026-03-01T00:00:00Z", "curtailment_pct_bps": 1000},
    )
    data = validate_success(api.get_floor_plan(fp["id"], MANAGER))
    assert data["payoff_cents"] == 8212384, \
        f"Expected forward-looking payoff 8212384, got {data['payoff_cents']}"


def test_curtailment_at_exactly_ninety_days_moves_to_curtailed(api):
    """PRD §3.2: "A curtailment moves an `ACTIVE` plan to `CURTAILED`". PRD §3.2:
    "the number of days elapsed since `advanced_at` must be at least the 90-day
    curtailment window, otherwise the request is rejected with `ERR_CURTAILMENT_NOT_DUE`
    (HTTP 409)".

    Design: Difficulty/boundary_precision_check/curtailment_due_exactly_at_90_days
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    _unit, fp = fixtures.create_floor_planned_unit(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 900,
                      "advanced_at": "2026-03-03T00:00:00Z", "curtailment_pct_bps": 1000},
    )
    data = validate_success(api.curtail_floor_plan(fp["id"], 100000, MANAGER))
    assert data["status"] == "CURTAILED", f"Expected CURTAILED, got {data['status']}"


def test_curtailment_at_exactly_ninety_days_reduces_principal(api):
    """PRD §3.2: "When both pass, the payment is subtracted from
    `outstanding_principal_cents` and the unit's `floor_plan_balance_cents` is recomputed."

    Design: Difficulty/boundary_precision_check/curtailment_due_exactly_at_90_days
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    _unit, fp = fixtures.create_floor_planned_unit(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 900,
                      "advanced_at": "2026-03-03T00:00:00Z", "curtailment_pct_bps": 1000},
    )
    data = validate_success(api.curtail_floor_plan(fp["id"], 100000, MANAGER))
    assert data["outstanding_principal_cents"] == 7900000, \
        f"Expected 7900000 after 100000 curtailment, got {data['outstanding_principal_cents']}"


def test_curtailment_before_ninety_days_rejected(api):
    """PRD §3.2: "the number of days elapsed since `advanced_at` must be at least the
    90-day curtailment window, otherwise the request is rejected with
    `ERR_CURTAILMENT_NOT_DUE` (HTTP 409)".

    Design: Corner/calculations/curtailment_not_due_at_89_days_rejected
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    _unit, fp = fixtures.create_floor_planned_unit(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 900,
                      "advanced_at": "2026-03-04T00:00:00Z", "curtailment_pct_bps": 1000},
    )
    validate_error(api.curtail_floor_plan(fp["id"], 100000, MANAGER),
                   ApiErrorId.ERR_CURTAILMENT_NOT_DUE.value)


def test_curtailment_exceeding_principal_rejected(api):
    """PRD §3.2: "the payment may not exceed what is owed — `payment_cents` must be
    less than or equal to `outstanding_principal_cents`, otherwise the request is
    rejected with `ERR_CURTAILMENT_EXCEEDS_PRINCIPAL` (HTTP 422)".

    Design: Corner/validations/curtailment_payment_exceeds_principal_rejected
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    _unit, fp = fixtures.create_floor_planned_unit(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 900,
                      "advanced_at": "2026-03-01T00:00:00Z", "curtailment_pct_bps": 1000},
    )
    validate_error(api.curtail_floor_plan(fp["id"], 9000000, MANAGER),
                   ApiErrorId.ERR_CURTAILMENT_EXCEEDS_PRINCIPAL.value)


def test_unit_floor_plan_balance_reconciles_after_curtail(api):
    """PRD §3.1: "it equals the `outstanding_principal_cents` of the unit's floor plan
    whose status is either `ACTIVE` or `CURTAILED`". PRD §3.2: "When both pass, the
    payment is subtracted from `outstanding_principal_cents` and the unit's
    `floor_plan_balance_cents` is recomputed."

    Design: Corner/cross_cutting/floor_plan_balance_reconciles_after_curtail
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    unit, fp = fixtures.create_floor_planned_unit(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 900,
                      "advanced_at": "2026-03-01T00:00:00Z", "curtailment_pct_bps": 1000},
    )
    validate_success(api.curtail_floor_plan(fp["id"], 100000, MANAGER))
    fp_data = validate_success(api.get_floor_plan(fp["id"], MANAGER))
    assert fp_data["outstanding_principal_cents"] == 7900000
    unit_data = validate_success(api.get_unit(unit["id"], MANAGER))
    assert unit_data["floor_plan_balance_cents"] == 7900000, \
        f"Expected balance 7900000, got {unit_data['floor_plan_balance_cents']}"
