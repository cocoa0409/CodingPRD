"""Audit reconciliation: loss valuation variants, finalize cascade, window buffer.

Translates Difficulty queue (A) instances from `dual_variant_calc` (audit loss),
`transitive_cascade` (audit finalize depth-3), `boundary_precision_check`
(zero-count edge), and `resource_temporal_overlap` (window overlap).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_audit,
    assert_location,
    make_pool_admin_headers,
    make_pool_operator_headers,
)
import test_helpers as H

ADMIN = make_pool_admin_headers()
OPERATOR = make_pool_operator_headers()


# --------------------------------------------------------------------------
# Difficulty: NET_BOOK loss valuation diverges from REPLACEMENT
# --------------------------------------------------------------------------
def _setup_three_aged_victims_net_book():
    """Three assets aged 2024-06-30 / 2025-06-30 / 2026-01-01, issued into L_NBV
    (equity 3). DRAFT NET_BOOK audit window_end 2026-06-30 with counted_physical=0.
    base replacement_cost_cents=3000, useful_life_days=1825. Returns audit id."""
    policy = H.create_policy()
    asset_type = H.create_asset_type(replacement_cost_cents=3000, useful_life_days=1825)
    account = H.create_account(role_type="MANUFACTURER", credit_limit_cents=10_000_000)
    stock = H.create_location(account["id"], name="OperatorStock")
    lnbv = H.create_location(account["id"], name="L_NBV")
    H.set_clock("2024-06-30T00:00:00Z")
    n1 = H.create_asset(asset_type["id"], stock["id"], serial="N1", in_service_at="2024-06-30T00:00:00Z")
    n2 = H.create_asset(asset_type["id"], stock["id"], serial="N2", in_service_at="2025-06-30T00:00:00Z")
    n3 = H.create_asset(asset_type["id"], stock["id"], serial="N3", in_service_at="2026-01-01T00:00:00Z")
    to = H.get_success_data(
        H.api_client.create_transfer_order(
            {
                "from_location_id": stock["id"],
                "to_location_id": lnbv["id"],
                "kind": "ISSUANCE",
                "asset_ids": [n1["id"], n2["id"], n3["id"]],
            },
            OPERATOR,
        )
    )
    H.get_success_data(H.api_client.dispatch_transfer_order(to["id"], OPERATOR))
    H.get_success_data(H.api_client.receive_transfer_order(to["id"], OPERATOR))
    H.set_clock("2026-06-30T00:00:00Z")
    audit = H.create_audit(
        lnbv["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", 0, loss_basis="NET_BOOK"
    )
    return audit["id"]


def test_audit_loss_net_book_valuation(api):
    """PRD §3.6: "the victim's net book value is the asset type's
    replacement_cost_cents multiplied by remaining life divided by
    useful_life_days, floored to whole cents; and declared_loss_cents is the sum
    of those per-victim net book values."

    Design: Difficulty/dual_variant_calc/audit_loss_replacement_vs_net_book_diverge
    """
    audit_id = _setup_three_aged_victims_net_book()
    data = validate_success(api.finalize_audit(audit_id, OPERATOR))
    assert_audit(data)
    assert data["declared_loss_qty"] == 3
    # 1800 + 2400 + 2704 = 6904 (ages 730/365/180 days).
    assert data["declared_loss_cents"] == 6904, \
        f"expected NET_BOOK 6904, got {data['declared_loss_cents']}"


def test_audit_loss_net_book_diverges_from_replacement(api):
    """PRD §3.6: "Because an older asset depreciates lower, the same shortfall
    quantity yields a smaller declared_loss_cents under NET_BOOK than under
    REPLACEMENT."

    Design: Difficulty/dual_variant_calc/audit_loss_replacement_vs_net_book_diverge
    """
    audit_id = _setup_three_aged_victims_net_book()
    data = validate_success(api.finalize_audit(audit_id, OPERATOR))
    # REPLACEMENT would be 3 x 3000 = 9000; NET_BOOK is strictly smaller.
    assert data["declared_loss_cents"] != 9000
    assert data["declared_loss_cents"] < 9000


# --------------------------------------------------------------------------
# Difficulty: finalize cascade depth-3 (audit -> asset LOST -> location balance)
# --------------------------------------------------------------------------
def _setup_shortfall_three_replacement():
    """L1 with equity 5 (5-asset ISSUANCE) and physical 5; DRAFT REPLACEMENT
    audit counted_physical=2 -> shortfall 3. Returns (audit_id, location_id)."""
    ctx = H.setup_audit_ready(
        equity=5, counted_physical=2, loss_basis="REPLACEMENT",
    )
    return ctx["audit"]["id"], ctx["location"]["id"]


def test_audit_finalize_declares_loss_qty_and_cents(api):
    """PRD §3.6: "First it sets declared_loss_qty to the location's equity_balance
    minus counted_physical, floored at 0". PRD §3.6: "Under REPLACEMENT,
    declared_loss_cents is declared_loss_qty multiplied by the asset type's
    replacement_cost_cents, ignoring asset age."

    Design: Difficulty/transitive_cascade/audit_finalize_cascade_asset_lost_then_location_recompute_depth3
    """
    audit_id, _loc_id = _setup_shortfall_three_replacement()
    data = validate_success(api.finalize_audit(audit_id, OPERATOR))
    assert data["declared_loss_qty"] == 3
    assert data["declared_loss_cents"] == 9000


def test_audit_finalize_cascade_drops_physical_keeps_equity(api):
    """PRD §3.6: "The loss declaration does not change the location's
    equity_balance: a loss converts owed equity into a billable charge rather than
    relieving it, so equity is unchanged while physical_balance drops as the
    victims leave."

    Design: Difficulty/transitive_cascade/audit_finalize_cascade_asset_lost_then_location_recompute_depth3
    """
    audit_id, loc_id = _setup_shortfall_three_replacement()
    validate_success(api.finalize_audit(audit_id, OPERATOR))
    loc = validate_success(api.get_location(loc_id, OPERATOR))
    assert_location(loc)
    assert loc["physical_balance"] == 2, f"physical should drop to 2, got {loc['physical_balance']}"
    assert loc["equity_balance"] == 5, f"equity should stay 5, got {loc['equity_balance']}"


# --------------------------------------------------------------------------
# Difficulty: zero-count full-loss edge
# --------------------------------------------------------------------------
def test_audit_zero_count_full_loss_empty_physical_edge(api):
    """PRD §3.6: "First it sets declared_loss_qty to the location's equity_balance
    minus counted_physical, floored at 0 — that is, the shortfall, or 0 when the
    count meets or exceeds expected equity." PRD §3.6: "Under REPLACEMENT,
    declared_loss_cents is declared_loss_qty multiplied by the asset type's
    replacement_cost_cents, ignoring asset age."

    Design: Difficulty/boundary_precision_check/audit_zero_count_full_loss_empty_physical_edge
    """
    ctx = H.setup_audit_ready(equity=2, counted_physical=0, loss_basis="REPLACEMENT")
    data = validate_success(api.finalize_audit(ctx["audit"]["id"], OPERATOR))
    assert data["declared_loss_qty"] == 2
    assert data["declared_loss_cents"] == 6000


def test_audit_zero_count_full_loss_finalizes_and_drops_physical(api):
    """PRD §3.6: "Finalizing an audit advances it DRAFT to FINALIZED". PRD §3.6:
    "marks each victim's condition AVAILABLE to LOST with its current_location_id
    cleared to null. The loss declaration does not change the location's
    equity_balance ... so equity is unchanged while physical_balance drops as the
    victims leave."

    Design: Difficulty/boundary_precision_check/audit_zero_count_full_loss_empty_physical_edge
    """
    ctx = H.setup_audit_ready(equity=2, counted_physical=0, loss_basis="REPLACEMENT")
    data = validate_success(api.finalize_audit(ctx["audit"]["id"], OPERATOR))
    assert data["status"] == "FINALIZED"
    loc = validate_success(api.get_location(ctx["location"]["id"], OPERATOR))
    # All 2 victims are LOST -> physical drops to 0; equity stays 2.
    assert loc["physical_balance"] == 0, f"physical should be 0, got {loc['physical_balance']}"
    assert loc["equity_balance"] == 2, f"equity should stay 2, got {loc['equity_balance']}"


# --------------------------------------------------------------------------
# Difficulty: audit window overlap / adjacency buffer
# --------------------------------------------------------------------------
def test_audit_window_overlap_same_location_rejected(api):
    """PRD §3.6: "then no other FINALIZED audit for the same location may have a
    window that overlaps this window, nor may any prior finalized window sit closer
    than audit_min_interval_days to this one ... otherwise the finalize is rejected
    with ERR_AUDIT_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/audit_window_overlap_same_location_rejected
    """
    policy = H.create_policy(audit_min_interval_days=28)
    asset_type = H.create_asset_type()
    account = H.create_account(role_type="MANUFACTURER", credit_limit_cents=100000)
    l1 = H.create_location(account["id"], name="L1")
    audit1 = H.create_audit(l1["id"], "2026-05-01T00:00:00Z", "2026-05-31T00:00:00Z", 0)
    H.finalize_audit(audit1["id"])
    # Second window [2026-06-10, 2026-06-20] sits within 28 days of 2026-05-31.
    audit2 = H.create_audit(l1["id"], "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z", 0)
    resp = api.finalize_audit(audit2["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP.value, expected_status=409)


def test_audit_window_overlap_leaves_second_audit_draft(api):
    """PRD §3.6: "then no other FINALIZED audit for the same location may have a
    window that overlaps this window, nor may any prior finalized window sit closer
    than audit_min_interval_days to this one ... otherwise the finalize is rejected
    with ERR_AUDIT_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/audit_window_overlap_same_location_rejected
    """
    policy = H.create_policy(audit_min_interval_days=28)
    asset_type = H.create_asset_type()
    account = H.create_account(role_type="MANUFACTURER", credit_limit_cents=100000)
    l1 = H.create_location(account["id"], name="L1")
    audit1 = H.create_audit(l1["id"], "2026-05-01T00:00:00Z", "2026-05-31T00:00:00Z", 0)
    H.finalize_audit(audit1["id"])
    audit2 = H.create_audit(l1["id"], "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z", 0)
    api.finalize_audit(audit2["id"], OPERATOR)
    after = validate_success(api.get_audit(audit2["id"], OPERATOR))
    assert after["status"] == "DRAFT", f"rejected finalize must leave DRAFT, got {after['status']}"
