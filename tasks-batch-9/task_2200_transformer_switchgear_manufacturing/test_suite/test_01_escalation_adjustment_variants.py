"""Escalation adjustment computation: the two variants and the rounding order."""

import pytest

from test_helpers import (
    CONTRACT_ADMIN,
    attach_escalation_clause,
    commodity_index_point_payload,
    create_order,
    escalation_adjustment_payload,
    order_version,
    set_clock,
)
from prd_bench_local_runner.testing import validate_success

PUBLISHED_AT = "2026-05-01T00:00:00Z"


def _publish(api, commodity, index_month, index_value, is_provisional=False):
    return validate_success(
        api.create_commodity_index_point(
            commodity_index_point_payload(
                commodity=commodity,
                index_month=index_month,
                index_value=index_value,
                published_at=PUBLISHED_AT,
                is_provisional=is_provisional,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )


def _adjust(api, order_id, clause_id, variant):
    return validate_success(
        api.create_escalation_adjustment(
            order_id,
            escalation_adjustment_payload(
                clause_id, order_version(api, order_id), variant=variant
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )


def test_provisional_spots_the_latest_month_while_final_averages_the_firm_window(api):
    """PRD 3.3: "Under `PROVISIONAL`, the current level is the `index_value` of
    the usable row with the greatest `index_month` that is at or before
    `final_window_end_month`... Under `FINAL`, the window is every usable
    non-provisional row whose `index_month` falls in the inclusive range
    beginning one month after `base_index_month` and ending at
    `final_window_end_month`".

    Design: Difficulty/dual_variant_calc/escalation_provisional_spot_vs_final_nonprovisional_mean_same_clause
    """
    set_clock(api, "2026-05-10T00:00:00Z")
    order = create_order(
        api,
        order_number="TX-ESC-0001",
        product_family="POWER_TRANSFORMER",
        rated_kv=138,
        contract_value_cents=60000000,
    )
    clause = attach_escalation_clause(
        api,
        order["id"],
        copper_weight_bp=6000,
        aluminum_weight_bp=4000,
        core_steel_weight_bp=0,
        escalatable_base_cents=10000000,
        base_index_month="2026-01",
        final_window_end_month="2026-04",
        cap_bp=1000,
        collar_bp=100,
        de_escalation_enabled=False,
    )

    # Firm prints for the base month and the two interior months; the closing
    # month is published only as a provisional print.
    _publish(api, "COPPER", "2026-01", 100.0)
    _publish(api, "COPPER", "2026-02", 104.0)
    _publish(api, "COPPER", "2026-03", 110.0)
    _publish(api, "COPPER", "2026-04", 112.0, is_provisional=True)
    _publish(api, "ALUMINUM", "2026-01", 200.0)
    _publish(api, "ALUMINUM", "2026-02", 202.0)
    _publish(api, "ALUMINUM", "2026-03", 206.0)
    _publish(api, "ALUMINUM", "2026-04", 208.0, is_provisional=True)
    _publish(api, "CORE_STEEL", "2026-01", 300.0)
    _publish(api, "CORE_STEEL", "2026-04", 300.0, is_provisional=True)

    provisional = _adjust(api, order["id"], clause["id"], "PROVISIONAL")
    assert provisional["status"] == "CALCULATED"
    assert provisional["copper_component_cents"] == 720000
    assert provisional["aluminum_component_cents"] == 160000
    assert provisional["core_steel_component_cents"] == 0
    assert provisional["raw_movement_cents"] == 880000
    assert provisional["adjustment_amount_cents"] == 880000
    assert provisional["cap_applied"] is False
    assert provisional["collar_absorbed"] is False
    assert provisional["index_months_used"] == ["2026-01", "2026-04"]

    final = _adjust(api, order["id"], clause["id"], "FINAL")
    assert final["status"] == "CALCULATED"
    assert final["copper_component_cents"] == 420000
    assert final["aluminum_component_cents"] == 80000
    assert final["core_steel_component_cents"] == 0
    assert final["raw_movement_cents"] == 500000
    assert final["adjustment_amount_cents"] == 500000
    assert final["cap_applied"] is False
    assert final["collar_absorbed"] is False
    assert final["index_months_used"] == ["2026-01", "2026-02", "2026-03"]


def test_per_commodity_rounding_and_collar_and_cap_equality_boundaries(api):
    """PRD 3.3: "Each of those three raw contributions is rounded half up to
    whole cents **individually**... Only then are the three rounded figures
    added together to form `raw_movement_cents`." An absolute movement "exactly
    equal to the collar does *not* absorb and continues", and `cap_applied` "is
    true precisely when that clamp changed the value".

    Design: Difficulty/boundary_precision_check/escalation_round_before_sum_plus_collar_equality_and_cap_equality_one_basis_point_apart
    """
    set_clock(api, "2026-05-10T00:00:00Z")
    for commodity in ("COPPER", "ALUMINUM", "CORE_STEEL"):
        _publish(api, commodity, "2026-01", 160.0000)
        _publish(api, commodity, "2026-02", 170.0000)

    def build(tag, escalatable_base_cents, collar_bp, cap_bp):
        order = create_order(
            api,
            order_number=f"TX-ROUND-{tag}",
            contract_value_cents=4000000,
        )
        clause = attach_escalation_clause(
            api,
            order["id"],
            copper_weight_bp=5000,
            aluminum_weight_bp=5000,
            core_steel_weight_bp=0,
            escalatable_base_cents=escalatable_base_cents,
            base_index_month="2026-01",
            final_window_end_month="2026-02",
            collar_bp=collar_bp,
            cap_bp=cap_bp,
            de_escalation_enabled=False,
        )
        adjustment = _adjust(api, order["id"], clause["id"], "PROVISIONAL")
        return order, adjustment

    # A: each commodity contributes 4062.5 cents, so rounding before the sum
    # yields 8126 rather than the 8125 a single end-rounding would produce.
    order_a, adj_a = build("A", 130000, 0, 5000)
    assert adj_a["copper_component_cents"] == 4063
    assert adj_a["aluminum_component_cents"] == 4063
    assert adj_a["raw_movement_cents"] == 8126
    assert adj_a["adjustment_amount_cents"] == 8126
    assert adj_a["collar_absorbed"] is False
    assert adj_a["cap_applied"] is False
    assert adj_a["index_months_used"] == ["2026-01", "2026-02"]

    # B: movement exactly equals the collar, so the deadband does not absorb.
    _, adj_b = build("B", 160000, 625, 5000)
    assert adj_b["raw_movement_cents"] == 10000
    assert adj_b["adjustment_amount_cents"] == 10000
    assert adj_b["collar_absorbed"] is False

    # C: one basis point more of collar and the movement is absorbed.
    _, adj_c = build("C", 160000, 626, 5000)
    assert adj_c["raw_movement_cents"] == 10000
    assert adj_c["adjustment_amount_cents"] == 0
    assert adj_c["collar_absorbed"] is True
    assert adj_c["cap_applied"] is False

    # D: the cap sits below the movement, so the clamp changes the value.
    _, adj_d = build("D", 160000, 0, 600)
    assert adj_d["adjustment_amount_cents"] == 9600
    assert adj_d["cap_applied"] is True

    # E: the cap sits exactly at the movement, so nothing changed.
    _, adj_e = build("E", 160000, 0, 625)
    assert adj_e["adjustment_amount_cents"] == 10000
    assert adj_e["cap_applied"] is False

    for order in (order_a,):
        refreshed = validate_success(
            api.get_engineered_order(order["id"], CONTRACT_ADMIN)
        )
        assert refreshed["escalation_accepted_total_cents"] == 0
        assert refreshed["net_contract_value_cents"] == 4000000
