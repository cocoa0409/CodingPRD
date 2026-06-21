"""CPAP resupply spacing: the 90-day window boundary and the min-gap buffer."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures,
)
from test_helpers.test_users import make_supplier_headers


# ─── Difficulty: boundary_precision_check (resupply) ──
def test_resupply_eligible_at_exactly_90_days(api):
    """PRD §3.10: "the gap in whole days — the elapsed duration between the prior
    shipped resupply's requested_at_utc and this resupply's requested_at_utc, taking
    the floor to whole days — must be at least 90; a gap of exactly 90 days is
    eligible."

    Design: Difficulty/boundary_precision_check/resupply_90day_gap_boundary
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    order, supplier, item = fixtures.setup_cpap_order(ordered_at_utc="2026-01-01T00:00:00Z")
    sup_headers = make_supplier_headers(supplier["id"])

    rs1 = fixtures.request_resupply(order, supplier, supply_kind="MASK")
    get_success_data(api.ship_resupply(rs1["id"], sup_headers))

    # 2026-01-01 -> 2026-04-01 is exactly 90 days.
    fixtures.set_clock("2026-04-01T00:00:00Z")
    rs2 = fixtures.request_resupply(order, supplier, supply_kind="MASK")
    resp = api.ship_resupply(rs2["id"], sup_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "SHIPPED"


def test_resupply_rejected_at_89_days(api):
    """PRD §3.10: "a gap of exactly 90 days is eligible, while a gap of fewer than 90
    days is rejected with ERR_RESUPPLY_TOO_SOON."

    Design: Difficulty/boundary_precision_check/resupply_90day_gap_boundary
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    order, supplier, item = fixtures.setup_cpap_order(ordered_at_utc="2026-01-01T00:00:00Z")
    sup_headers = make_supplier_headers(supplier["id"])

    rs1 = fixtures.request_resupply(order, supplier, supply_kind="MASK")
    get_success_data(api.ship_resupply(rs1["id"], sup_headers))

    # 2026-01-01 -> 2026-03-31 is 89 days.
    fixtures.set_clock("2026-03-31T00:00:00Z")
    rs2 = fixtures.request_resupply(order, supplier, supply_kind="MASK")
    resp = api.ship_resupply(rs2["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_RESUPPLY_TOO_SOON.value)


# ─── Difficulty: resource_temporal_overlap (min gap) ──
def test_resupply_too_soon_at_30_days(api):
    """PRD §3.10: "the system finds the most recent prior SHIPPED resupply of the
    same supply_kind on the same order ... must be at least 90; ... a gap of fewer
    than 90 days is rejected with ERR_RESUPPLY_TOO_SOON."

    Design: Difficulty/resource_temporal_overlap/cpap_resupply_min_gap_buffer
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    order, supplier, item = fixtures.setup_cpap_order(ordered_at_utc="2026-01-01T00:00:00Z")
    sup_headers = make_supplier_headers(supplier["id"])

    rs1 = fixtures.request_resupply(order, supplier, supply_kind="MASK")
    get_success_data(api.ship_resupply(rs1["id"], sup_headers))

    # 2026-01-31 is 30 days after 2026-01-01.
    fixtures.set_clock("2026-01-31T00:00:00Z")
    rs2 = fixtures.request_resupply(order, supplier, supply_kind="MASK")
    resp = api.ship_resupply(rs2["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_RESUPPLY_TOO_SOON.value)


def test_resupply_different_supply_kind_not_blocked(api):
    """PRD §3.10: "the system finds the most recent prior SHIPPED resupply of the
    same supply_kind on the same order ... If there is no such prior shipped
    resupply, the request is eligible."

    Design: Difficulty/resource_temporal_overlap/cpap_resupply_min_gap_buffer
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    order, supplier, item = fixtures.setup_cpap_order(ordered_at_utc="2026-01-01T00:00:00Z")
    sup_headers = make_supplier_headers(supplier["id"])

    rs1 = fixtures.request_resupply(order, supplier, supply_kind="MASK")
    get_success_data(api.ship_resupply(rs1["id"], sup_headers))

    # A TUBING resupply 30 days later has no prior SHIPPED resupply of that kind.
    fixtures.set_clock("2026-01-31T00:00:00Z")
    rs2 = fixtures.request_resupply(order, supplier, supply_kind="TUBING")
    resp = api.ship_resupply(rs2["id"], sup_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "SHIPPED"
