"""Reconciliation breaks: resolution cascades, reopening compensation, and
the zero-variance guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    assert_rate,
    assert_reconciliation_break,
    base_kit,
    base_kit_with_nav,
    create_break,
    validate_error,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]


def _kit_with_break(counterparty=1200):
    kit = base_kit_with_nav(approve=False)
    brk = create_break(kit["fund"]["id"], kit["position"]["id"],
                       counterparty_quantity=counterparty)
    kit["break"] = brk
    return kit


def test_break_resolve_adjust_moves_position(api):
    """PRD §3.8: "Under `ADJUST_POSITION`, the break first captures the
    position's current `quantity` into `prior_book_quantity`, then sets the
    position's `quantity` to the `counterparty_quantity`"
    PRD §3.8: "At creation the break snapshots the position's current
    `quantity` into `book_quantity` and computes the `variance` as the
    counterparty quantity minus the book quantity."

    Design: Difficulty/transitive_cascade/break_resolve_adjust_cascade
    """
    kit = _kit_with_break(counterparty=1200)
    assert kit["break"]["book_quantity"] == 1000
    assert kit["break"]["variance"] == 200

    resolved = validate_success(
        api.resolve_reconciliation_break(
            kit["break"]["id"], {"resolution_type": "ADJUST_POSITION"}, CTRL
        ),
        200,
    )
    assert_reconciliation_break(resolved)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_type"] == "ADJUST_POSITION"
    assert resolved["prior_book_quantity"] == 1000
    position = validate_success(api.get_position(kit["position"]["id"], CTRL), 200)
    assert position["quantity"] == 1200


def test_break_resolve_adjust_recomputes_estimated_nav(api):
    """PRD §3.8: "Either way the position mutation recomputes the holding
    class's latest `ESTIMATED` record if one exists — `gross_asset_value`, the
    accrual amounts where the first-record base rule applies, then
    `expense_accrual_total`, `total_net_assets`, and `nav_per_share` —
    incrementing that record's `version` by one."

    Design: Difficulty/transitive_cascade/break_resolve_adjust_cascade
    """
    kit = _kit_with_break(counterparty=1200)
    v_before = kit["nav"]["version"]
    api.resolve_reconciliation_break(
        kit["break"]["id"], {"resolution_type": "ADJUST_POSITION"}, CTRL
    )
    nav = validate_success(api.get_nav_record(kit["nav"]["id"], CTRL), 200)
    # Hop 2: GAV recomputed from the adjusted position (1200 x 100.00).
    assert_money(nav["gross_asset_value"], 120000.00, "gross_asset_value")
    # Hop 3: first record, so the accrual base is GAV and re-prices too.
    assert_money(nav["expense_accrual_total"], 0.33, "expense_accrual_total")
    assert_money(nav["total_net_assets"], 119999.67, "total_net_assets")
    assert_rate(nav["nav_per_share"], 12.0000, "nav_per_share")
    assert nav["version"] == v_before + 1


def test_break_resolve_adjust_quantity_mid_state(api):
    """PRD §3.8: "Under `ADJUST_POSITION`, the break first captures the
    position's current `quantity` into `prior_book_quantity`, then sets the
    position's `quantity` to the `counterparty_quantity`"

    Design: Difficulty/compensating_invariant/break_adjust_reopen_conserves_position_quantity
    """
    kit = _kit_with_break(counterparty=900)
    assert kit["break"]["variance"] == -100
    resolved = validate_success(
        api.resolve_reconciliation_break(
            kit["break"]["id"], {"resolution_type": "ADJUST_POSITION"}, CTRL
        ),
        200,
    )
    assert resolved["prior_book_quantity"] == 1000
    position = validate_success(api.get_position(kit["position"]["id"], CTRL), 200)
    assert position["quantity"] == 900


def test_break_reopen_restores_position_quantity_exactly(api):
    """PRD §3.8: "If the break's `resolution_type` was `ADJUST_POSITION`, the
    position's `quantity` is restored to the captured `prior_book_quantity` —
    and a position that had auto-closed returns from `CLOSED` to `OPEN` when
    the restored quantity is above zero — and the `resolution_type` is cleared
    to null."
    PRD §3.8: "The compensating invariant is exact: resolving with
    `ADJUST_POSITION` followed by reopening leaves the position's `quantity`
    precisely equal to its pre-resolution value."

    Design: Difficulty/compensating_invariant/break_adjust_reopen_conserves_position_quantity
    """
    kit = _kit_with_break(counterparty=900)
    api.resolve_reconciliation_break(
        kit["break"]["id"], {"resolution_type": "ADJUST_POSITION"}, CTRL
    )
    reopened = validate_success(
        api.reopen_reconciliation_break(kit["break"]["id"], CTRL), 200
    )
    assert reopened["status"] == "OPEN"
    assert reopened["resolution_type"] is None
    position = validate_success(api.get_position(kit["position"]["id"], CTRL), 200)
    assert position["quantity"] == 1000


def test_break_zero_variance_rejected(api):
    """PRD §3.8: "A break with zero variance is pointless and is rejected with
    `ERR_NO_VARIANCE` (HTTP 422)."

    Design: Corner/validations/break_zero_variance_rejected
    """
    kit = base_kit(approve=False)
    resp = api.create_reconciliation_break(
        {
            "fund_id": kit["fund"]["id"],
            "position_id": kit["position"]["id"],
            "break_type": "CUSTODIAN_POSITION",
            "break_date": "2026-08-04",
            "counterparty_quantity": 1000,
        },
        TEST_USERS["fund_accountant_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NO_VARIANCE, 422)
