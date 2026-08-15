"""Difficulty queue A: the comparable net-adjustment 15.00 boundary —
inclusive at the limit, strict above it (PRD 3.5)."""
from test_helpers import (
    ApiErrorId,
    create_comparable,
    setup_order_in_analysis,
    validate_error,
    verify_comparable,
)


def _setup_pair(ctx):
    ok = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="Boundary Ln A",
        sale_price_cents=40000000,
        sale_date="2026-06-01",
        distance_miles=0.50,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=6000000,  # exactly 15.00 percent
    )
    bad = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="Boundary Ln B",
        sale_price_cents=40000000,
        sale_date="2026-06-01",
        distance_miles=0.50,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=6040000,  # 15.10 percent
    )
    return ok, bad


def test_comp_net_adjustment_exactly_15pct_is_eligible_and_locks(api):
    """PRD 3.5: "A comparable is eligible — `is_eligible` true — when its
    `net_adjustment_pct` is at most 15.00, its `gross_adjustment_pct` is at
    most 25.00, its `distance_miles` is at most 2.00, and its `sale_date` is
    no older than 365 days before the clock's date. All four boundaries are
    inclusive: a net of exactly 15.00, a gross of exactly 25.00, a distance
    of exactly 2.00 miles, and a sale exactly 365 days old all remain
    eligible."

    Design: Difficulty/boundary_precision_check/comp_net_adjustment_exactly_15pct_eligible_1501_ineligible
    """
    ctx = setup_order_in_analysis()
    ok, _ = _setup_pair(ctx)

    verified = verify_comparable(ok["id"], ctx["appraiser"]["id"])
    assert verified["net_adjustment_pct"] == 15.0
    assert verified["is_eligible"] is True

    from test_helpers import lock_comparable

    locked = lock_comparable(ok["id"], ctx["appraiser"]["id"])
    assert locked["status"] == "LOCKED"


def test_comp_net_adjustment_1510_is_ineligible_and_lock_rejected(api):
    """PRD 3.5: "When the verdict is false, `ineligible_reasons` carries the
    applicable subset of `NET_ADJ_EXCEEDED` (net above 15.00),
    `GROSS_ADJ_EXCEEDED` (gross above 25.00), `DISTANCE_EXCEEDED` (distance
    above 2.00 miles), and `SALE_TOO_OLD` (sale date older than 365 days)".
    PRD 3.5: "it refuses an ineligible comparable with
    `ERR_COMP_INELIGIBLE`."

    Design: Difficulty/boundary_precision_check/comp_net_adjustment_exactly_15pct_eligible_1501_ineligible
    """
    ctx = setup_order_in_analysis()
    _, bad = _setup_pair(ctx)

    verified = verify_comparable(bad["id"], ctx["appraiser"]["id"])
    assert verified["net_adjustment_pct"] == 15.1
    assert verified["is_eligible"] is False
    assert "NET_ADJ_EXCEEDED" in verified["ineligible_reasons"]

    response = api.lock_comparable(bad["id"], ctx["appraiser_headers"])
    validate_error(response, ApiErrorId.ERR_COMP_INELIGIBLE, 422)
