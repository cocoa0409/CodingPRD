"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

The test harness restarts the server (empty DB) before every individual test, so
every helper here builds its preconditions from scratch using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_unit_payload, create_floor_plan_loan_payload,
    create_curtailment_payload, create_trade_in_payload, create_deal_payload,
    create_technician_payload, create_repair_order_payload, create_service_line_payload,
    create_part_payload, create_part_line_payload, create_storage_bay_payload,
    create_storage_agreement_payload, create_test_ride_waiver_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS

SM = TEST_USERS["sales_manager_headers"]
FM = TEST_USERS["finance_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]
PC = TEST_USERS["parts_clerk_headers"]
DP = TEST_USERS["dealer_principal_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Set the server's logical clock (DealerPrincipal-only)."""
    return get_success_data(api_client.set_clock(iso8601, DP))


# ─── Tier 1: simple building blocks ───────────────────────────────────────────
def create_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SM))


def create_unit(**overrides):
    """Create a Unit (starts IN_TRANSIT)."""
    return get_success_data(api_client.create_unit(create_unit_payload(**overrides), SM))


def create_in_stock_unit(**overrides):
    """Create + receive a Unit so it lands in IN_STOCK."""
    unit = create_unit(**overrides)
    return get_success_data(api_client.receive_unit(unit["id"], SM))


def create_technician(**overrides):
    return get_success_data(api_client.create_technician(create_technician_payload(**overrides), SA))


def create_part(**overrides):
    return get_success_data(api_client.create_part(create_part_payload(**overrides), PC))


def create_storage_bay(**overrides):
    return get_success_data(api_client.create_storage_bay(create_storage_bay_payload(**overrides), SA))


# ─── Tier 2: floor-plan loan setups ───────────────────────────────────────────
def create_floored_loan(opened_on="2026-01-01T00:00:00.000Z", apr_bps=900,
                        dealer_cost_cents=1_000_000, clock=None, **unit_overrides):
    """
    Create a NEW_FLOORED unit, receive it, and open a floor-plan loan on it.
    Returns (unit, loan). If `clock` is given the server clock is set first.
    """
    if clock is not None:
        set_clock(clock)
    unit_payload = dict(acquisition_kind="NEW_FLOORED",
                        dealer_cost_cents=dealer_cost_cents)
    unit_payload.update(unit_overrides)
    raw = create_unit(**unit_payload)
    # receive with DealerPrincipal (also a permitted receiver)
    unit = get_success_data(api_client.receive_unit(raw["id"], DP))
    loan = get_success_data(api_client.create_floor_plan_loan(
        create_floor_plan_loan_payload(unit["id"], opened_on=opened_on, apr_bps=apr_bps), DP))
    return unit, loan


def create_curtailment_due_loan(opened_on="2026-01-01T00:00:00.000Z",
                                due_clock="2026-04-01T00:00:00.000Z",
                                apr_bps=900, dealer_cost_cents=1_000_000):
    """
    Open a floored loan then age it to CURTAILMENT_DUE (default clock == day 90).
    Returns (unit, loan) where loan is the post-aging state (carrying current version).
    """
    unit, loan = create_floored_loan(opened_on=opened_on, apr_bps=apr_bps,
                                      dealer_cost_cents=dealer_cost_cents,
                                      clock=opened_on)
    set_clock(due_clock)
    aged = get_success_data(api_client.run_aging(loan["id"], DP))
    return unit, aged


# ─── Tier 3: deal lifecycle shortcuts ─────────────────────────────────────────
def setup_draft_deal(sale_price_cents=1_400_000, tax_rate_bps=800,
                     unit_overrides=None, **deal_overrides):
    """Customer + IN_STOCK unit + a DRAFT deal referencing them. Returns (cust, unit, deal)."""
    cust = create_customer()
    unit = create_in_stock_unit(**(unit_overrides or {}))
    deal = get_success_data(api_client.create_deal(
        create_deal_payload(cust["id"], unit["id"],
                            sale_price_cents=sale_price_cents,
                            tax_rate_bps=tax_rate_bps, **deal_overrides), SM))
    return cust, unit, deal


def setup_quoted_deal(**kwargs):
    """DRAFT deal advanced to QUOTED. Returns (cust, unit, deal_after_quote)."""
    cust, unit, deal = setup_draft_deal(**kwargs)
    quoted = get_success_data(api_client.quote_deal(deal["id"], SM))
    return cust, unit, quoted


def setup_finance_submitted_deal(**kwargs):
    """Deal advanced to FINANCE_SUBMITTED. Returns (cust, unit, deal)."""
    cust, unit, quoted = setup_quoted_deal(**kwargs)
    submitted = get_success_data(api_client.submit_finance_deal(quoted["id"], FM))
    return cust, unit, submitted


def setup_approved_deal(**kwargs):
    """Deal driven through APPROVED (unit SOLD). Returns (cust, unit, deal)."""
    cust, unit, deal = setup_quoted_deal(**kwargs)
    get_success_data(api_client.submit_finance_deal(deal["id"], FM))
    approved = get_success_data(api_client.approve_deal(deal["id"], FM))
    return cust, unit, approved


def setup_delivered_unit(sale_price_cents=1_400_000, tax_rate_bps=800,
                         clock="2026-06-01T00:00:00.000Z", unit_overrides=None,
                         **deal_overrides):
    """
    Take a cash unit fully through deal delivery so the Unit is DELIVERED.
    Returns (cust, unit_delivered, deal_delivered).
    """
    if clock is not None:
        set_clock(clock)
    cust, unit, deal = setup_approved_deal(sale_price_cents=sale_price_cents,
                                           tax_rate_bps=tax_rate_bps,
                                           unit_overrides=unit_overrides, **deal_overrides)
    delivered = get_success_data(api_client.deliver_deal(deal["id"], SM))
    unit_after = get_success_data(api_client.get_unit(unit["id"], SM))
    return cust, unit_after, delivered


# ─── Tier 4: repair-order lifecycle shortcuts ─────────────────────────────────
def setup_repair_order(flat_rate_hours_list=None, is_warranty=False,
                       authorized_amount_cents=100_000, clock="2026-06-01T08:00:00.000Z",
                       appointment_start="2026-06-02T09:00:00.000Z",
                       appointment_end="2026-06-02T12:00:00.000Z",
                       cleanup_buffer_minutes=30):
    """
    Customer + IN_STOCK unit + technician + an OPEN repair order with the given
    service lines added (not started). Returns (cust, unit, tech, ro, service_lines).
    """
    if clock is not None:
        set_clock(clock)
    cust = create_customer()
    unit = create_in_stock_unit()
    tech = create_technician(cleanup_buffer_minutes=cleanup_buffer_minutes)
    ro = get_success_data(api_client.create_repair_order(
        create_repair_order_payload(unit["id"], cust["id"], tech["id"],
                                    appointment_start=appointment_start,
                                    appointment_end=appointment_end,
                                    is_warranty=is_warranty,
                                    authorized_amount_cents=authorized_amount_cents), SA))
    lines = []
    for i, hrs in enumerate(flat_rate_hours_list or []):
        line = get_success_data(api_client.create_service_line(
            create_service_line_payload(ro["id"], operation_code=f"OP-{i}",
                                        flat_rate_hours=hrs), SA))
        lines.append(line)
    return cust, unit, tech, ro, lines


def setup_started_repair_order(flat_rate_hours_list=(2.0,), **kwargs):
    """RO with lines, started (IN_PROGRESS). Returns (cust, unit, tech, ro, lines)."""
    cust, unit, tech, ro, lines = setup_repair_order(
        flat_rate_hours_list=list(flat_rate_hours_list), **kwargs)
    started = get_success_data(api_client.start_repair_order(ro["id"], SA))
    return cust, unit, tech, started, lines


def setup_completed_repair_order(flat_rate_hours_list=(2.0,), **kwargs):
    """RO with lines, completed (WORK_COMPLETE, billing UNBILLED). Returns (cust, unit, tech, ro, lines)."""
    cust, unit, tech, ro, lines = setup_started_repair_order(
        flat_rate_hours_list=flat_rate_hours_list, **kwargs)
    completed = get_success_data(api_client.complete_repair_order(ro["id"], SA))
    return cust, unit, tech, completed, lines


# ─── Tier 5: parts setups ─────────────────────────────────────────────────────
def setup_part_reserved_on_open_ro(on_hand_qty=10, reserve_qty=4,
                                   clock="2026-06-01T08:00:00.000Z"):
    """
    OPEN RO + a Part with a single RESERVED PartLine.
    Returns (ro, part_after_reserve, part_line).
    """
    _, _, _, ro, _ = setup_repair_order(flat_rate_hours_list=[1.0], clock=clock,
                                        authorized_amount_cents=90_000)
    part = create_part(on_hand_qty=on_hand_qty)
    pl = get_success_data(api_client.create_part_line(
        create_part_line_payload(ro["id"], part["id"], reserve_qty, part["version"]), PC))
    part_after = get_success_data(api_client.get_part(part["id"], PC))
    return ro, part_after, pl


# ─── Tier 6: storage setups ───────────────────────────────────────────────────
def setup_reserved_storage_agreement(includes_winterization=False,
                                     period_start="2026-01-01T00:00:00.000Z",
                                     period_end="2026-03-01T00:00:00.000Z",
                                     monthly_rate_cents=12000,
                                     clock="2026-01-01T00:00:00.000Z",
                                     bay_id=None, customer_id=None):
    """A RESERVED storage agreement on a (possibly shared) bay. Returns (bay, cust, unit, agr)."""
    if clock is not None:
        set_clock(clock)
    bay = {"id": bay_id} if bay_id else create_storage_bay()
    cust = {"id": customer_id} if customer_id else create_customer()
    unit = create_in_stock_unit(category="SNOWMOBILE")
    agr = get_success_data(api_client.create_storage_agreement(
        create_storage_agreement_payload(unit["id"], cust["id"], bay["id"],
                                         period_start=period_start, period_end=period_end,
                                         monthly_rate_cents=monthly_rate_cents,
                                         includes_winterization=includes_winterization), SA))
    return bay, cust, unit, agr


def setup_checked_in_storage_agreement(includes_winterization=False, **kwargs):
    """A CHECKED_IN storage agreement. Returns (bay, cust, unit, agr_after_checkin)."""
    bay, cust, unit, agr = setup_reserved_storage_agreement(
        includes_winterization=includes_winterization, **kwargs)
    checked_in = get_success_data(api_client.check_in_storage_agreement(agr["id"], SA))
    return bay, cust, unit, checked_in


# ─── Tier 7: waiver setups ────────────────────────────────────────────────────
def setup_signed_waiver(valid_until="2026-06-30T00:00:00.000Z",
                        clock="2026-06-01T00:00:00.000Z", unit=None, customer=None):
    """A SIGNED waiver for an IN_STOCK unit. Returns (cust, unit, waiver)."""
    if clock is not None:
        set_clock(clock)
    cust = customer or create_customer()
    u = unit or create_in_stock_unit()
    waiver = get_success_data(api_client.create_test_ride_waiver(
        create_test_ride_waiver_payload(cust["id"], u["id"], valid_until=valid_until), SM))
    return cust, u, waiver


# ─── Tier 8: warranty setups ──────────────────────────────────────────────────
def setup_warranty_ro_on_delivered_unit(flat_rate_hours=2.0, reserve_part_qty=0,
                                        clock="2026-06-01T00:00:00.000Z"):
    """
    DELIVERED unit + a completed warranty RO (is_warranty=true) for it, billing UNBILLED.
    Optionally reserves+consumes a part. Returns (cust, unit, tech, ro_completed, part).
    """
    cust, unit, _deal = setup_delivered_unit(clock=clock)
    tech = create_technician()
    ro = get_success_data(api_client.create_repair_order(
        create_repair_order_payload(unit["id"], cust["id"], tech["id"],
                                    appointment_start="2026-06-12T09:00:00.000Z",
                                    appointment_end="2026-06-12T13:00:00.000Z",
                                    is_warranty=True, authorized_amount_cents=0), SA))
    get_success_data(api_client.create_service_line(
        create_service_line_payload(ro["id"], operation_code="WAR-1",
                                    flat_rate_hours=flat_rate_hours), SA))
    part = None
    if reserve_part_qty > 0:
        part = create_part(on_hand_qty=reserve_part_qty + 3)
        get_success_data(api_client.create_part_line(
            create_part_line_payload(ro["id"], part["id"], reserve_part_qty, part["version"]), PC))
    get_success_data(api_client.start_repair_order(ro["id"], SA))
    completed = get_success_data(api_client.complete_repair_order(ro["id"], SA))
    return cust, unit, tech, completed, part
