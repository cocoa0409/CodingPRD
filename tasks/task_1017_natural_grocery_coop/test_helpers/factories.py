"""Payload factories — one per entity, input fields only (PRD §3, §4).

Only fields sourced from client input are included; system and computed fields
(id, status, member_number, totals, ...) are never sent.
"""

DEFAULTS = {
    "YEAR": 2026,
    "PATRONAGE_RATE": 0.05,
    "EQUITY_SHARE_PRICE_CENTS": 10000,
}


def create_fiscal_year_payload(**overrides) -> dict:
    payload = {
        "year": DEFAULTS["YEAR"],
        "patronage_rate": DEFAULTS["PATRONAGE_RATE"],
        "equity_share_price_cents": DEFAULTS["EQUITY_SHARE_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(full_name="Test Member", email="member@x.com", **overrides) -> dict:
    payload = {"full_name": full_name, "email": email}
    payload.update(overrides)
    return payload


def create_vendor_payload(name="Test Vendor", **overrides) -> dict:
    payload = {"name": name}
    payload.update(overrides)
    return payload


def create_product_payload(vendor_id, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "sku": "SKU1",
        "name": "Test Product",
        "department": "GROCERY",
        "unit_type": "EACH",
        "base_price_cents": 500,
        "reorder_point": 0,
        "reorder_qty": 10,
    }
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(product_id, vendor_id, received_qty=10,
                                 unit_cost_cents=200, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "vendor_id": vendor_id,
        "received_qty": received_qty,
        "unit_cost_cents": unit_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_register_payload(name="R1", **overrides) -> dict:
    payload = {"name": name}
    payload.update(overrides)
    return payload


def create_sale_payload(register_id, member_id=None, **overrides) -> dict:
    payload = {"register_id": register_id}
    if member_id is not None:
        payload["member_id"] = member_id
    payload.update(overrides)
    return payload


def create_sale_line_payload(product_id, inventory_lot_id, quantity=None,
                             gross_weight_grams=None, **overrides) -> dict:
    payload = {"product_id": product_id, "inventory_lot_id": inventory_lot_id}
    if quantity is not None:
        payload["quantity"] = quantity
    if gross_weight_grams is not None:
        payload["gross_weight_grams"] = gross_weight_grams
    payload.update(overrides)
    return payload


def create_promotion_payload(product_id, deal_type="AD", promo_price_cents=450,
                             start_date="2026-06-01T00:00:00Z",
                             end_date="2026-08-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "deal_type": deal_type,
        "promo_price_cents": promo_price_cents,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


def create_working_shift_payload(member_id, department="GROCERY",
                                 start_at="2026-07-01T08:00:00Z",
                                 end_at="2026-07-01T20:00:00Z", **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "department": department,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_board_proposal_payload(title="Test Proposal", proposal_type="POLICY",
                                  **overrides) -> dict:
    payload = {"title": title, "proposal_type": proposal_type}
    payload.update(overrides)
    return payload


def create_allocation_payload(fiscal_year_id, expected_fiscal_year_version,
                              method="ESTIMATED", declared_rate=None, **overrides) -> dict:
    payload = {
        "fiscal_year_id": fiscal_year_id,
        "method": method,
        "expected_fiscal_year_version": expected_fiscal_year_version,
    }
    if declared_rate is not None:
        payload["declared_rate"] = declared_rate
    payload.update(overrides)
    return payload
