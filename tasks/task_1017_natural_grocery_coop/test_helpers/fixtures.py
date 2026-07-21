"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures. The test
harness restarts the server (empty DB) before every test, so each helper builds all
of its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_fiscal_year_payload,
    create_member_payload,
    create_vendor_payload,
    create_product_payload,
    create_inventory_lot_payload,
    create_register_payload,
    create_sale_payload,
    create_sale_line_payload,
    create_promotion_payload,
    create_working_shift_payload,
    create_board_proposal_payload,
    create_allocation_payload,
)
from .test_users import TEST_USERS, make_member_headers

COOP = TEST_USERS["coop_admin_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]
BOARD = TEST_USERS["board_admin_headers"]


# ─── Primitives ───────────────────────────────────────────────────────────────

def create_fiscal_year(patronage_rate=0.05, equity_share_price_cents=10000, year=2026):
    """Create an OPEN fiscal year. Returns the fiscal year object."""
    return get_success_data(api_client.create_fiscal_year(
        create_fiscal_year_payload(year=year, patronage_rate=patronage_rate,
                                   equity_share_price_cents=equity_share_price_cents),
        COOP,
    ))


def create_approved_vendor(name="Green Farms"):
    """Create a vendor and move it to APPROVED. Returns the vendor object."""
    vendor = get_success_data(api_client.create_vendor(create_vendor_payload(name=name), INVENTORY))
    return get_success_data(api_client.set_vendor_status(
        vendor["id"], {"status": "APPROVED"}, INVENTORY))


def create_pending_vendor(name="Unvetted DSD"):
    """Create a vendor left in PENDING. Returns the vendor object."""
    return get_success_data(api_client.create_vendor(create_vendor_payload(name=name), INVENTORY))


def create_product(vendor_id, **overrides):
    """Create an ACTIVE product for the given vendor. Returns the product object."""
    return get_success_data(api_client.create_product(
        create_product_payload(vendor_id, **overrides), INVENTORY))


def create_posted_lot(product_id, vendor_id, received_qty=10, unit_cost_cents=200):
    """Create a DRAFT lot and post it. Returns the posted lot object."""
    lot = get_success_data(api_client.create_inventory_lot(
        create_inventory_lot_payload(product_id, vendor_id, received_qty=received_qty,
                                     unit_cost_cents=unit_cost_cents),
        INVENTORY,
    ))
    return get_success_data(api_client.post_inventory_lot(lot["id"], INVENTORY))


def create_open_register(name="R1"):
    """Create a register and open it. Returns the register object."""
    reg = get_success_data(api_client.create_register(create_register_payload(name=name), CASHIER))
    return get_success_data(api_client.set_register_open(reg["id"], {"is_open": True}, CASHIER))


def create_active_member(full_name="Mara O", email="mara@x.com", equity_cents=10000,
                         is_board_member=False):
    """Register a member, contribute equity, and approve to ACTIVE. Requires an OPEN
    fiscal year to already exist. Returns the ACTIVE member object."""
    member = get_success_data(api_client.create_member(
        create_member_payload(full_name=full_name, email=email, is_board_member=is_board_member),
        COOP,
    ))
    get_success_data(api_client.equity_contribution(
        member["id"], {"amount_cents": equity_cents}, FINANCE))
    return get_success_data(api_client.approve_member(member["id"], COOP))


def create_working_member(full_name="Wren W", email="wren@x.com",
                          start_at="2026-07-01T08:00:00Z", end_at="2026-07-01T20:00:00Z"):
    """Create an ACTIVE member who has a COMPLETED 12h shift (is_working_member true).
    Requires an OPEN fiscal year to already exist. Returns the member object (re-fetched)."""
    member = create_active_member(full_name=full_name, email=email)
    shift = get_success_data(api_client.create_working_shift(
        create_working_shift_payload(member["id"], start_at=start_at, end_at=end_at), COOP))
    api_client.complete_working_shift(shift["id"], INVENTORY)
    return get_success_data(api_client.get_member(member["id"], COOP))


def open_sale(register_id, member_id=None):
    """Open a BUILDING/UNPAID sale on a register. Returns the sale object."""
    return get_success_data(api_client.create_sale(
        create_sale_payload(register_id, member_id=member_id), CASHIER))


def add_line(sale_id, product_id, lot_id, quantity=None, gross_weight_grams=None):
    """Add a priced line to a BUILDING sale. Returns the sale object."""
    return get_success_data(api_client.add_sale_line(
        sale_id, create_sale_line_payload(product_id, lot_id, quantity=quantity,
                                          gross_weight_grams=gross_weight_grams),
        CASHIER,
    ))


def finalize_sale(sale_id):
    """Finalize a BUILDING sale. Returns the sale object."""
    return get_success_data(api_client.finalize_sale(sale_id, CASHIER))


def create_draft_allocation(fiscal_year_id, method="ESTIMATED", declared_rate=None):
    """Capture the fiscal year's current version, then create a DRAFT allocation run
    carrying that version. Returns the allocation object."""
    fy = get_success_data(api_client.get_fiscal_year(fiscal_year_id, FINANCE))
    return get_success_data(api_client.create_patronage_allocation(
        create_allocation_payload(fiscal_year_id, fy["version"], method=method,
                                  declared_rate=declared_rate),
        FINANCE,
    ))


# ─── Composite scenarios ───────────────────────────────────────────────────────

def setup_member_sale_finalized(patronage_rate=0.05, base_price_cents=10000, quantity=2,
                                is_prepared_food=False, is_taxable=False):
    """Full retail chain for a member sale: OPEN fiscal year, APPROVED vendor, ACTIVE
    member with accrued patronage from one finalized member sale of a single product.

    Returns dict with keys: fiscal_year, vendor, product, lot, member, register, sale.
    """
    fy = create_fiscal_year(patronage_rate=patronage_rate)
    vendor = create_approved_vendor()
    product = create_product(vendor["id"], sku="OATS", name="Bulk Oats",
                             base_price_cents=base_price_cents, reorder_point=0,
                             reorder_qty=10, is_taxable=is_taxable,
                             is_prepared_food=is_prepared_food)
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=5000)
    member = create_active_member(full_name="Mara O", email="mara@x.com")
    register = create_open_register()
    sale = open_sale(register["id"], member_id=member["id"])
    add_line(sale["id"], product["id"], lot["id"], quantity=quantity)
    sale = finalize_sale(sale["id"])
    member = get_success_data(api_client.get_member(member["id"], COOP))
    return {
        "fiscal_year": fy, "vendor": vendor, "product": product, "lot": lot,
        "member": member, "register": register, "sale": sale,
    }


def setup_estimated_allocation_ready(patronage_rate=0.05):
    """setup_member_sale_finalized + a DRAFT ESTIMATED allocation against the OPEN year.

    Returns dict extending setup_member_sale_finalized with key: allocation.
    """
    ctx = setup_member_sale_finalized(patronage_rate=patronage_rate)
    ctx["allocation"] = create_draft_allocation(ctx["fiscal_year"]["id"], method="ESTIMATED")
    return ctx


def setup_final_allocation_ready(patronage_rate=0.05, declared_rate=0.08):
    """Member with accrued patronage, then year CLOSED, then a DRAFT FINAL allocation
    carrying declared_rate. Returns dict with fiscal_year, member, allocation."""
    ctx = setup_member_sale_finalized(patronage_rate=patronage_rate)
    api_client.close_fiscal_year(ctx["fiscal_year"]["id"], FINANCE)
    ctx["fiscal_year"] = get_success_data(
        api_client.get_fiscal_year(ctx["fiscal_year"]["id"], FINANCE))
    ctx["allocation"] = create_draft_allocation(
        ctx["fiscal_year"]["id"], method="FINAL", declared_rate=declared_rate)
    return ctx


def setup_two_lot_product_for_shrink():
    """Product with two POSTED lots: lot A received 10 @ 100 (created first), lot B
    received 10 @ 200 (created later). Returns (product_id, lot_a_id, lot_b_id)."""
    vendor = create_approved_vendor(name="Co-op Dairy")
    product = create_product(vendor["id"], sku="MILK", name="Milk Qt",
                             base_price_cents=300, reorder_point=0, reorder_qty=20)
    lot_a = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=100)
    lot_b = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=200)
    return product["id"], lot_a["id"], lot_b["id"]


def setup_finalized_paid_sale(received_qty=10, quantity=3):
    """Non-member sale on an OPEN register: one line, finalized, then paid. Returns
    (sale, lot) with the lot reflecting drawn inventory."""
    vendor = create_approved_vendor()
    product = create_product(vendor["id"], sku="GRN", name="Granola",
                             base_price_cents=350, reorder_point=0, reorder_qty=10)
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=received_qty,
                            unit_cost_cents=150)
    register = create_open_register()
    sale = open_sale(register["id"])
    add_line(sale["id"], product["id"], lot["id"], quantity=quantity)
    sale = finalize_sale(sale["id"])
    api_client.pay_sale(sale["id"], CASHIER)
    sale = get_success_data(api_client.get_sale(sale["id"], CASHIER))
    lot = get_success_data(api_client.get_inventory_lot(lot["id"], INVENTORY))
    return sale, lot


def setup_building_sale(register_open=True):
    """OPEN register (or CLOSED if register_open is False) with a BUILDING sale and a
    posted lot/product available. Returns dict: register, product, lot, sale."""
    vendor = create_approved_vendor()
    product = create_product(vendor["id"], sku="APL", name="Apples", department="PRODUCE",
                             base_price_cents=150, reorder_point=0, reorder_qty=10)
    lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=80)
    reg = get_success_data(api_client.create_register(create_register_payload(), CASHIER))
    if register_open:
        reg = get_success_data(api_client.set_register_open(reg["id"], {"is_open": True}, CASHIER))
    sale = open_sale(reg["id"])
    return {"register": reg, "product": product, "lot": lot, "sale": sale}


def setup_voting_proposal_with_board_member(proposal_type="BUDGET"):
    """OPEN fiscal year; an ACTIVE board member; a proposal advanced to VOTING (eligible
    board snapshot = 1). Returns (proposal, board_member)."""
    create_fiscal_year()
    board_member = create_active_member(full_name="Bea B", email="bea@x.com",
                                        is_board_member=True)
    proposal = get_success_data(api_client.create_board_proposal(
        create_board_proposal_payload(title="Budget 2026", proposal_type=proposal_type), BOARD))
    api_client.advance_board_proposal(proposal["id"], {"action": "SUBMIT"}, BOARD)
    proposal = get_success_data(api_client.advance_board_proposal(
        proposal["id"], {"action": "OPEN_VOTING"}, BOARD))
    return proposal, board_member


def cast_member_vote(proposal_id, member_id, vote):
    """Cast a board vote as the member themselves (X-User-ID == member_id). Returns the
    proposal object."""
    return get_success_data(api_client.cast_board_vote(
        proposal_id, {"member_id": member_id, "vote": vote}, make_member_headers(member_id)))
