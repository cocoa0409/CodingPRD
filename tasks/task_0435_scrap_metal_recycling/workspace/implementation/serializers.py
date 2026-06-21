"""Public serialization for each entity type — exact field sets per SCAFFOLD §1.1.

These projections control which stored fields are exposed and in a stable shape.
We always include the common fields (id, created_at, updated_at, version) for
mutable resources; TicketLineItem omits updated_at/version (append-only).
"""


def seller(r):
    return {
        "id": r["id"],
        "legal_name": r["legal_name"],
        "id_type": r["id_type"],
        "id_number": r["id_number"],
        "tin": r.get("tin"),
        "status": r["status"],
        "ytd_cash_paid_cents": r["ytd_cash_paid_cents"],
        "requires_1099": r["requires_1099"],
        "open_theft_reports": r["open_theft_reports"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def commodity_price(r):
    return {
        "id": r["id"],
        "grade_code": r["grade_code"],
        "category": r["category"],
        "spot_price_cents_per_lb": r["spot_price_cents_per_lb"],
        "mill_price_cents_per_lb": r["mill_price_cents_per_lb"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ticket(r):
    return {
        "id": r["id"],
        "seller_id": r["seller_id"],
        "container_id": r.get("container_id"),
        "gross_weight_lb": r["gross_weight_lb"],
        "tare_weight_lb": r.get("tare_weight_lb"),
        "net_weight_lb": r.get("net_weight_lb"),
        "status": r["status"],
        "gross_valuation_cents": r["gross_valuation_cents"],
        "theft_hold_released_by": r.get("theft_hold_released_by"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def line_item(r):
    return {
        "id": r["id"],
        "ticket_id": r["ticket_id"],
        "grade_code": r["grade_code"],
        "commodity_price_id": r["commodity_price_id"],
        "weight_lb": r["weight_lb"],
        "line_valuation_cents": r["line_valuation_cents"],
        "created_at": r["created_at"],
    }


def payout(r):
    return {
        "id": r["id"],
        "ticket_id": r["ticket_id"],
        "seller_id": r["seller_id"],
        "method": r["method"],
        "amount_cents": r["amount_cents"],
        "form_1099_issued": r["form_1099_issued"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def container(r):
    return {
        "id": r["id"],
        "category": r["category"],
        "capacity_lb": r["capacity_lb"],
        "loaded_weight_lb": r["loaded_weight_lb"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def mill_shipment(r):
    return {
        "id": r["id"],
        "container_id": r["container_id"],
        "category": r["category"],
        "shipped_weight_lb": r["shipped_weight_lb"],
        "expected_settlement_cents": r["expected_settlement_cents"],
        "final_settlement_cents": r.get("final_settlement_cents"),
        "settlement_variance_cents": r.get("settlement_variance_cents"),
        "hedge_position_id": r.get("hedge_position_id"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def hedge(r):
    return {
        "id": r["id"],
        "category": r["category"],
        "hedged_weight_lb": r["hedged_weight_lb"],
        "locked_price_cents_per_lb": r["locked_price_cents_per_lb"],
        "realized_weight_lb": r["realized_weight_lb"],
        "realized_pnl_cents": r["realized_pnl_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def theft_report(r):
    return {
        "id": r["id"],
        "seller_id": r["seller_id"],
        "ticket_id": r.get("ticket_id"),
        "reason": r["reason"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
