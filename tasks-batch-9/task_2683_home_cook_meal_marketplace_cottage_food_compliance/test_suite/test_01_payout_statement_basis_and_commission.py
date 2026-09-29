"""Payout-statement recognition bases, per-order commission rounding, and the
open-incident gate on finalisation.

The harness restarts the API server before every test, so each test below builds
its whole world from scratch through the endpoints of PRD 4.
"""

from test_helpers import fixtures as fx
from test_helpers import (
    DINER_ONE_HEADERS,
    DINER_TWO_HEADERS,
    FINANCE_ONE_HEADERS,
    OFFICER_ONE_HEADERS,
    OFFICER_TWO_HEADERS,
    assert_net_payout_identity,
    assert_order,
    assert_payout_statement,
    assert_safety_incident,
    is_iso8601_timestamp,
    round_half_up,
    statement_advance_payload,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------
# Shared world builders. Every helper is a plain function called from inside a
# test, so nothing leaks between tests.
# --------------------------------------------------------------------------

#: 610 cents a meal, quantity 2 -> a 1220-cent subtotal whose 0.225 commission
#: product is exactly 274.5 cents, i.e. a half-cent tie on every order.
_UNIT_PRICE_CENTS = 610
_ORDER_QUANTITY = 2
_SUBTOTAL_CENTS = _UNIT_PRICE_CENTS * _ORDER_QUANTITY
_TIER_RATE = 0.225
_PER_ORDER_COMMISSION_CENTS = 275


def _two_handed_off_orders(api):
    """An IN_PRODUCTION window holding two HANDED_OFF / AUTHORIZED orders.

    Both orders carry a 1220-cent subtotal and neither payment has captured, so
    the cook's ytd_gross_sales_cents is still zero.
    """
    setup = fx.selling_cook(
        api,
        cook_overrides={"claimed_kitchen_type": "COMMERCIAL_SHARED"},
        item_overrides={
            "name": "Sesame Noodle Box",
            "food_category": "NON_TCS",
            "allergens": ["WHEAT", "SESAME"],
            "shelf_life_days": 7,
            "unit_price_cents": _UNIT_PRICE_CENTS,
        },
        window_overrides={"capacity_meals": 40},
    )
    order_x = fx.routed_order(
        api, setup, quantity=_ORDER_QUANTITY, diner_headers=DINER_ONE_HEADERS
    )
    order_y = fx.routed_order(
        api, setup, quantity=_ORDER_QUANTITY, diner_headers=DINER_TWO_HEADERS
    )
    fx.open_window_into_production(api, setup)
    setup["order_x"] = fx.hand_off_order(api, setup, order_x)
    setup["order_y"] = fx.hand_off_order(api, setup, order_y)
    return setup


def _one_delivered_one_handed_off(api):
    """The same window, but order X has been diner-confirmed and captured."""
    setup = _two_handed_off_orders(api)
    setup["order_x"] = fx.deliver_order(api, setup.order_x)
    return setup


def _closed_window_with_draft_statement(api):
    """A CLOSED window whose single captured order backs one DRAFT statement."""
    setup = fx.closed_window_scenario(
        api,
        quantity=2,
        item_overrides={
            "name": "Pierogi Dozen",
            "food_category": "NON_TCS",
            "allergens": ["WHEAT", "MILK"],
            "shelf_life_days": 4,
            "unit_price_cents": 1200,
        },
        window_overrides={"capacity_meals": 6},
    )
    setup["statement"] = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="ACCRUAL_WINDOW"
    )
    return setup


def _order_subject_incident(api, setup, severity="MINOR"):
    """An INTAKE report filed against the order that the window produced."""
    return fx.report_incident(
        api,
        setup.cook_id,
        subject_type="ORDER",
        order_id=setup.order["id"],
        category="FOREIGN_OBJECT",
        severity=severity,
        description="lid seal broken on arrival",
        occurred_at="2026-08-08T17:30:00Z",
    )


# --------------------------------------------------------------------------
# Recognition basis: ACCRUAL_WINDOW versus CASH_HANDOFF over identical data
# --------------------------------------------------------------------------
def test_01_accrual_basis_admits_handed_off_and_delivered_orders(api):
    """An ACCRUAL_WINDOW statement includes both the delivered and the merely handed-off order.

    PRD: "Under `ACCRUAL_WINDOW`, the included orders are every order on the named window whose `fulfillment_status` is `HANDED_OFF` or `DELIVERED`, with no payment predicate at all, and the included refunds are every refund event on any order of that window regardless of the refund's own `status`."
    Design: Difficulty/dual_variant_calc/payout_basis_accrual_vs_cash_divergence
    """
    setup = _one_delivered_one_handed_off(api)
    assert setup.order_x["fulfillment_status"] == "DELIVERED"
    assert setup.order_x["payment_status"] == "CAPTURED"
    assert setup.order_y["fulfillment_status"] == "HANDED_OFF"
    assert setup.order_y["payment_status"] == "AUTHORIZED"

    statement = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="ACCRUAL_WINDOW"
    )

    assert_payout_statement(
        statement,
        basis="ACCRUAL_WINDOW",
        status="DRAFT",
        included_order_count=2,
        gross_sales_cents=2 * _SUBTOTAL_CENTS,
        tier_rate=_TIER_RATE,
        commission_cents=2 * _PER_ORDER_COMMISSION_CENTS,
        refund_chargeback_cents=0,
        safety_hold_cents=0,
        net_payout_cents=1890,
    )
    assert_net_payout_identity(statement)


def test_02_cash_basis_admits_only_the_delivered_and_captured_order(api):
    """A CASH_HANDOFF statement over the same window recognises only the captured order.

    PRD: "Under `CASH_HANDOFF`, the included orders are only those on the window whose `fulfillment_status` is `DELIVERED` **and** whose `payment_status` is `CAPTURED`, `PARTIALLY_REFUNDED` or `REFUNDED`, and the included refunds are only those whose `status` is `SETTLED`."
    Design: Difficulty/dual_variant_calc/payout_basis_accrual_vs_cash_divergence
    """
    setup = _one_delivered_one_handed_off(api)

    statement = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="CASH_HANDOFF"
    )

    assert_payout_statement(
        statement,
        basis="CASH_HANDOFF",
        status="DRAFT",
        included_order_count=1,
        gross_sales_cents=_SUBTOTAL_CENTS,
        tier_rate=_TIER_RATE,
        commission_cents=_PER_ORDER_COMMISSION_CENTS,
        refund_chargeback_cents=0,
        safety_hold_cents=0,
        net_payout_cents=945,
    )
    assert_net_payout_identity(statement)


def test_03_the_two_bases_disagree_by_the_uncaptured_handoff(api):
    """The accrual and cash nets differ by exactly the handed-off but unconfirmed order.

    PRD: "The two bases therefore differ exactly when an order was handed off but never diner-confirmed, or when a refund is still `PENDING`."
    Design: Difficulty/dual_variant_calc/payout_basis_accrual_vs_cash_divergence
    """
    setup = _one_delivered_one_handed_off(api)

    accrual = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="ACCRUAL_WINDOW"
    )
    cash = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="CASH_HANDOFF"
    )

    assert accrual["net_payout_cents"] == 1890
    assert cash["net_payout_cents"] == 945
    assert accrual["net_payout_cents"] - cash["net_payout_cents"] == 945
    assert accrual["included_order_count"] - cash["included_order_count"] == 1
    assert accrual["gross_sales_cents"] - cash["gross_sales_cents"] == _SUBTOTAL_CENTS


def test_04_the_second_draft_supersedes_the_first_for_the_same_pair(api):
    """Drafting the cash statement retires the earlier accrual draft on the same pair.

    PRD: "A new statement is created in `status` `DRAFT` with null `finalized_at`, `paid_at` and `superseded_at`, and it supersedes its predecessors: any prior statement for the same cook-and-window pair sitting in `DRAFT` moves `DRAFT → SUPERSEDED` and stamps `superseded_at` from the logical clock."
    Design: Difficulty/dual_variant_calc/payout_basis_accrual_vs_cash_divergence
    """
    setup = _one_delivered_one_handed_off(api)

    accrual = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="ACCRUAL_WINDOW"
    )
    assert accrual["status"] == "DRAFT"
    assert accrual["superseded_at"] is None

    cash = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="CASH_HANDOFF"
    )

    accrual = fx.read_statement(api, accrual["id"])
    assert_payout_statement(accrual, status="SUPERSEDED")
    assert is_iso8601_timestamp(accrual["superseded_at"])
    assert_payout_statement(cash, status="DRAFT", superseded_at=None)


# --------------------------------------------------------------------------
# Commission: rounded once per included order, then summed
# --------------------------------------------------------------------------
def test_05_statement_commission_rounds_each_order_before_summing(api):
    """Two 1220-cent orders at 0.225 yield 275 + 275 = 550 cents of commission.

    PRD: "`commission_cents` has a **pinned rounding order**: the `tier_rate` is applied to each included order's `subtotal_cents` individually, each product is rounded half up to a whole cent, and only then are the per-order results summed."
    Design: Difficulty/combinatorial_formula/commission_rounded_per_order_then_summed
    """
    setup = _two_handed_off_orders(api)

    statement = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="ACCRUAL_WINDOW"
    )

    assert round_half_up(_SUBTOTAL_CENTS * _TIER_RATE) == _PER_ORDER_COMMISSION_CENTS
    assert_payout_statement(
        statement,
        included_order_count=2,
        gross_sales_cents=2440,
        tier_rate=_TIER_RATE,
        commission_cents=550,
        refund_chargeback_cents=0,
        safety_hold_cents=0,
        net_payout_cents=1890,
    )
    assert_net_payout_identity(statement)


def test_06_statement_commission_is_not_the_aggregate_rounded_once(api):
    """Rounding the 2440-cent aggregate once would give 549, which is the wrong answer.

    PRD: "Summing the subtotals first and rounding once at the end is the wrong answer and produces a different number of cents whenever two or more subtotals land on a half-cent product."
    Design: Difficulty/combinatorial_formula/commission_rounded_per_order_then_summed
    """
    setup = _two_handed_off_orders(api)

    statement = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="ACCRUAL_WINDOW"
    )

    aggregate_rounded_once = round_half_up(2 * _SUBTOTAL_CENTS * _TIER_RATE)
    assert aggregate_rounded_once == 549
    assert statement["commission_cents"] == 550
    assert statement["commission_cents"] != aggregate_rounded_once
    assert statement["net_payout_cents"] == 1890
    assert statement["net_payout_cents"] != 2 * _SUBTOTAL_CENTS - aggregate_rounded_once


def test_07_each_included_order_carries_its_own_rounded_commission(api):
    """Every order on the window stamped 275 cents of commission and 945 of earnings.

    PRD: "`platform_commission_cents` is `subtotal_cents` multiplied by that rate, rounded half up to a whole cent, and `cook_earnings_cents` is `subtotal_cents` less `platform_commission_cents`."
    Design: Difficulty/combinatorial_formula/commission_rounded_per_order_then_summed
    """
    setup = _two_handed_off_orders(api)

    statement = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="ACCRUAL_WINDOW"
    )

    for order_id in (setup.order_x["id"], setup.order_y["id"]):
        order = fx.read_order(api, order_id)
        assert_order(
            order,
            subtotal_cents=_SUBTOTAL_CENTS,
            commission_rate=_TIER_RATE,
            platform_commission_cents=_PER_ORDER_COMMISSION_CENTS,
            cook_earnings_cents=_SUBTOTAL_CENTS - _PER_ORDER_COMMISSION_CENTS,
        )
    assert statement["commission_cents"] == 2 * _PER_ORDER_COMMISSION_CENTS


# --------------------------------------------------------------------------
# Finalisation is gated by an open safety incident on the window's own order
# --------------------------------------------------------------------------
def test_08_triaged_incident_on_a_window_order_blocks_finalization(api):
    """A DRAFT statement over a CLOSED window cannot finalise while an incident sits TRIAGED.

    PRD: "`DRAFT → FINALIZED` requires that the covered window's `status` be `CLOSED`, and requires that the cook have zero safety incidents in `INTAKE` or `TRIAGED` whose `order_id` points at an order belonging to that same window — open investigations freeze the money, and a violation is `ERR_OPEN_INCIDENT_BLOCKS_PAYOUT`."
    Design: Difficulty/cross_entity_state_dependency/payout_finalization_gated_by_open_safety_incident
    """
    setup = _closed_window_with_draft_statement(api)
    assert setup.window["status"] == "CLOSED"
    assert setup.statement["status"] == "DRAFT"

    incident = _order_subject_incident(api, setup)
    incident = fx.triage_incident(api, incident["id"], "ACCEPT")
    assert incident["status"] == "TRIAGED"

    resp = api.advance_payout_statement(
        setup.statement["id"], statement_advance_payload("FINALIZED"), FINANCE_ONE_HEADERS
    )
    validate_error(resp, "ERR_OPEN_INCIDENT_BLOCKS_PAYOUT", 409)

    statement = fx.read_statement(api, setup.statement["id"])
    assert_payout_statement(statement, status="DRAFT", finalized_at=None, paid_at=None)


def test_09_intake_incident_on_a_window_order_also_blocks_finalization(api):
    """An untriaged INTAKE report freezes the money exactly as a triaged one does.

    PRD: "No safety incident of this cook is in `INTAKE` or `TRIAGED` when a statement is finalised — `ERR_OPEN_INCIDENT_BLOCKS_PAYOUT`, 409, on payout-statement advancement to `FINALIZED`."
    Design: Difficulty/cross_entity_state_dependency/payout_finalization_gated_by_open_safety_incident
    """
    setup = _closed_window_with_draft_statement(api)

    incident = _order_subject_incident(api, setup)
    assert_safety_incident(incident, status="INTAKE", triaged_by_user_id=None)

    resp = api.advance_payout_statement(
        setup.statement["id"], statement_advance_payload("FINALIZED"), FINANCE_ONE_HEADERS
    )
    validate_error(resp, "ERR_OPEN_INCIDENT_BLOCKS_PAYOUT", 409)

    statement = fx.read_statement(api, setup.statement["id"])
    assert_payout_statement(statement, status="DRAFT", finalized_at=None)


def test_10_unsubstantiated_adjudication_closes_the_incident_without_a_cascade(api):
    """Dismissing the triaged report zeroes its points and leaves the cook CLEAR at 100.

    PRD: "A `decision` of `DISMISS` moves the report `TRIAGED → UNSUBSTANTIATED`, stamps the identical three fields — `adjudicated_by_user_id`, `adjudicated_at` and `resolution_note` — and sets `severity_points` to 0."
    Design: Difficulty/cross_entity_state_dependency/payout_finalization_gated_by_open_safety_incident
    """
    setup = _closed_window_with_draft_statement(api)
    incident = _order_subject_incident(api, setup)
    fx.triage_incident(api, incident["id"], "ACCEPT", officer_headers=OFFICER_ONE_HEADERS)

    incident = fx.adjudicate_incident(
        api,
        incident["id"],
        "DISMISS",
        resolution_note="packaging fault attributed to the courier",
        officer_headers=OFFICER_TWO_HEADERS,
    )

    assert_safety_incident(
        incident,
        status="UNSUBSTANTIATED",
        severity_points=0,
        resolution_note="packaging fault attributed to the courier",
    )
    assert is_iso8601_timestamp(incident["adjudicated_at"])
    cook = fx.read_cook(api, setup.cook_id)
    assert cook["compliance_standing"] == "CLEAR"
    assert cook["safety_score"] == 100


def test_11_finalization_succeeds_once_the_incident_is_adjudicated(api):
    """The identical finalisation request lands after the incident leaves INTAKE/TRIAGED.

    PRD: "Finalisation stamps `finalized_at` from the logical clock, moves every refund event still in `PENDING` whose order belongs to that window `PENDING → SETTLED` with `settled_at` stamped, and recomputes the cook's `pending_payout_cents`."
    Design: Difficulty/cross_entity_state_dependency/payout_finalization_gated_by_open_safety_incident
    """
    setup = _closed_window_with_draft_statement(api)
    assert_payout_statement(
        setup.statement, gross_sales_cents=2400, commission_cents=540, net_payout_cents=1860
    )
    assert fx.read_cook(api, setup.cook_id)["pending_payout_cents"] == 1860

    incident = _order_subject_incident(api, setup)
    fx.triage_incident(api, incident["id"], "ACCEPT", officer_headers=OFFICER_ONE_HEADERS)
    blocked = api.advance_payout_statement(
        setup.statement["id"], statement_advance_payload("FINALIZED"), FINANCE_ONE_HEADERS
    )
    validate_error(blocked, "ERR_OPEN_INCIDENT_BLOCKS_PAYOUT", 409)
    fx.adjudicate_incident(
        api, incident["id"], "DISMISS", officer_headers=OFFICER_TWO_HEADERS
    )

    resp = api.advance_payout_statement(
        setup.statement["id"], statement_advance_payload("FINALIZED"), FINANCE_ONE_HEADERS
    )
    statement = validate_success(resp, 200)

    assert_payout_statement(statement, status="FINALIZED", net_payout_cents=1860)
    assert is_iso8601_timestamp(statement["finalized_at"])
    assert statement["finalized_at"].startswith("2026-08-08T18:00:00")
    assert fx.read_cook(api, setup.cook_id)["pending_payout_cents"] == 0
