"""Resource serializers. Every field traces to the entity table; nothing extra
is emitted."""
from clock import clock, parse_date
from money import money_out, num_out
from services import buyers, consignments as cons_svc, saleday, settlements as settle_svc


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


def party(row):
    out = _common(row)
    out.update({
        "legal_name": row["legal_name"],
        "party_type": row["party_type"],
        "origin_state_code": row["origin_state_code"],
        "origin_county": row["origin_county"],
        "tax_id": row["tax_id"],
        "status": row["status"],
    })
    return out


def sale_day(row):
    out = _common(row)
    out.update({
        "sale_date": row["sale_date"],
        "barn_code": row["barn_code"],
        "barn_state_code": row["barn_state_code"],
        "status": row["status"],
        "next_ring_order": row["next_ring_order"],
        "reopen_count": row["reopen_count"],
    })
    figures = saleday.rollups(row)
    for key in ("head_received_total", "head_sold_total", "head_no_sale_total",
                "head_withdrawn_total", "head_dead_total",
                "head_in_process_total", "head_unassigned_total"):
        out[key] = figures[key]
    for key in ("total_gross_sale_value", "total_buyer_invoiced",
                "total_seller_net", "total_barn_revenue",
                "total_statutory_collected"):
        out[key] = money_out(figures[key])
    for key in ("gross_match_ok", "money_reconciliation_ok",
                "head_reconciliation_ok"):
        out[key] = figures[key]
    return out


def pen(row):
    out = _common(row)
    out.update({
        "pen_code": row["pen_code"],
        "species_class": row["species_class"],
        "head_capacity": row["head_capacity"],
        "pen_type": row["pen_type"],
        "status": row["status"],
        "current_head": row["current_head"],
    })
    return out


def scale_status(row):
    """Derived on every read against the logical clock; both bounds inclusive."""
    today = clock.now_date()
    start = parse_date(row["certified_from"])
    end = parse_date(row["certification_expires_on"])
    if start is None or end is None:
        return "EXPIRED"
    return "CERTIFIED" if start <= today <= end else "EXPIRED"


def scale(row):
    out = _common(row)
    out.update({
        "scale_code": row["scale_code"],
        "certified_from": row["certified_from"],
        "certification_expires_on": row["certification_expires_on"],
        "max_draft_lb": num_out(row["max_draft_lb"]),
        "status": scale_status(row),
    })
    return out


def drover_crew(row):
    out = _common(row)
    out.update({
        "crew_code": row["crew_code"],
        "member_count": row["member_count"],
        "duty_status": row["duty_status"],
        "last_move_completed_at": row.get("last_move_completed_at"),
    })
    return out


def consignment(row):
    out = _common(row)
    out.update({
        "sale_day_id": row["sale_day_id"],
        "consignor_party_id": row["consignor_party_id"],
        "species_class": row["species_class"],
        "head_received": row["head_received"],
        "weigh_basis": row["weigh_basis"],
        "pencil_shrink_pct": num_out(row["pencil_shrink_pct"]),
        "yardage_basis": row["yardage_basis"],
        "commission_basis": row["commission_basis"],
        "ration_type": row["ration_type"],
        "days_on_feed": row["days_on_feed"],
        "advances_amount": money_out(row["advances_amount"]),
        "hold_until_funds": row["hold_until_funds"],
        "status": row["status"],
        "checked_in_at": row.get("checked_in_at"),
        "head_unassigned": row["head_unassigned"],
        "head_in_lots": cons_svc.head_in_lots(row["id"]),
        "head_dead": row["head_dead"],
        "head_condemned": row["head_condemned"],
        "head_withdrawn": row["head_withdrawn"],
        "head_sold": cons_svc.head_sold(row["id"]),
        "head_no_saled": cons_svc.head_no_saled(row["id"]),
        "head_balance_ok": cons_svc.head_balance_ok(row),
    })
    return out


def lot(row):
    out = _common(row)
    out.update({
        "consignment_id": row["consignment_id"],
        "sale_day_id": row["sale_day_id"],
        "pen_id": row.get("pen_id"),
        "head_count": row["head_count"],
        "livestock_class": row["livestock_class"],
        "bid_basis": row["bid_basis"],
        "opening_bid": money_out(row["opening_bid"]),
        "reserve_price": money_out(row["reserve_price"]),
        "destination_state_code": row.get("destination_state_code"),
        "ring_order": row.get("ring_order"),
        "sale_status": row["sale_status"],
        "custody_status": row["custody_status"],
        "quarantine_hold": row["quarantine_hold"],
        "rering_count": row["rering_count"],
        "gross_weight_lb": num_out(row.get("gross_weight_lb")),
        "tare_weight_lb": num_out(row.get("tare_weight_lb")),
        "net_weight_lb": num_out(row.get("net_weight_lb")),
        "settle_weight_lb": num_out(row.get("settle_weight_lb")),
        "avg_weight_lb": num_out(row.get("avg_weight_lb")),
        "weight_class": row["weight_class"],
        "hammer_price": money_out(row.get("hammer_price")),
        "extended_amount": money_out(row.get("extended_amount")),
        "buy_back": row["buy_back"],
        "penned_at": row.get("penned_at"),
        "released_at": row.get("released_at"),
    })
    return out


def weigh_ticket(row):
    out = _common(row)
    out.update({
        "lot_id": row["lot_id"],
        "scale_id": row["scale_id"],
        "head_on_draft": row["head_on_draft"],
        "gross_weight_lb": num_out(row["gross_weight_lb"]),
        "tare_weight_lb": num_out(row["tare_weight_lb"]),
        "net_weight_lb": num_out(row.get("net_weight_lb")),
        "ticket_seq": row["ticket_seq"],
        "status": row["status"],
        "opened_at": row.get("opened_at"),
        "captured_at": row.get("captured_at"),
    })
    return out


def pen_move(row):
    out = _common(row)
    out.update({
        "lot_id": row["lot_id"],
        "from_pen_id": row.get("from_pen_id"),
        "to_pen_id": row["to_pen_id"],
        "crew_id": row["crew_id"],
        "head_moved": row["head_moved"],
        "scheduled_start_at": row["scheduled_start_at"],
        "scheduled_end_at": row["scheduled_end_at"],
        "status": row["status"],
        "completed_at": row.get("completed_at"),
    })
    return out


def buyer_registration(row):
    out = _common(row)
    out.update({
        "party_id": row["party_id"],
        "sale_day_id": row["sale_day_id"],
        "buyer_number": row["buyer_number"],
        "bond_type": row["bond_type"],
        "credit_limit": money_out(row["credit_limit"]),
        "cash_deposit_amount": money_out(row["cash_deposit_amount"]),
        "override_limit": money_out(row["override_limit"]),
        "status": row["status"],
        "payments_applied": money_out(row["payments_applied"]),
        "effective_limit": money_out(row["effective_limit"]),
        "open_purchase_amount": money_out(buyers.open_purchase_amount(row["id"])),
        "winning_bid_amount": money_out(buyers.winning_bid_amount(row["id"])),
        "exposure": money_out(buyers.exposure(row)),
        "available_credit": money_out(buyers.available_credit(row)),
    })
    return out


def bid(row):
    out = _common(row)
    out.update({
        "lot_id": row["lot_id"],
        "buyer_registration_id": row["buyer_registration_id"],
        "unit_price": money_out(row["unit_price"]),
        "bid_seq": row["bid_seq"],
        "projected_extension": money_out(row["projected_extension"]),
        "status": row["status"],
    })
    return out


def purchase(row):
    out = _common(row)
    out.update({
        "lot_id": row["lot_id"],
        "buyer_registration_id": row["buyer_registration_id"],
        "winning_bid_id": row["winning_bid_id"],
        "buyer_invoice_id": row.get("buyer_invoice_id"),
        "bid_basis": row["bid_basis"],
        "unit_price": money_out(row["unit_price"]),
        "head_count": row["head_count"],
        "total_weight_lb": num_out(row.get("total_weight_lb")),
        "extended_amount": money_out(row["extended_amount"]),
        "doa_head": row["doa_head"],
        "doa_credit_amount": money_out(row["doa_credit_amount"]),
        "status": row["status"],
    })
    return out


def buyer_invoice(row):
    out = _common(row)
    out.update({
        "buyer_registration_id": row["buyer_registration_id"],
        "sale_day_id": row["sale_day_id"],
        "subtotal": money_out(row["subtotal"]),
        "buyer_fee": money_out(row["buyer_fee"]),
        "credit_memo_total": money_out(row["credit_memo_total"]),
        "total_due": money_out(row["total_due"]),
        "amount_paid": money_out(row["amount_paid"]),
        "balance_due": money_out(row["balance_due"]),
        "status": row["status"],
    })
    return out


def settlement(row):
    out = _common(row)
    out.update({
        "consignment_id": row["consignment_id"],
        "consignor_party_id": row["consignor_party_id"],
        "gross_amount": money_out(row["gross_amount"]),
        "commission_amount": money_out(row["commission_amount"]),
        "yardage_amount": money_out(row["yardage_amount"]),
        "feed_amount": money_out(row["feed_amount"]),
        "statutory_amount": money_out(row["statutory_amount"]),
        "brand_fee_amount": money_out(row["brand_fee_amount"]),
        "indemnity_fee_amount": money_out(row["indemnity_fee_amount"]),
        "advances_amount": money_out(row["advances_amount"]),
        "offset_applied": money_out(row["offset_applied"]),
        "adjustment_total": money_out(row["adjustment_total"]),
        "net_amount": money_out(row["net_amount"]),
        "status": row["status"],
        "hold_reason": row["hold_reason"],
        "balance_ok": settle_svc.balance_ok(row),
    })
    return out


def charge_line(row):
    # Lean resource: id and created_at only, no updated_at and no version.
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "sale_day_id": row.get("sale_day_id"),
        "settlement_id": row.get("settlement_id"),
        "buyer_invoice_id": row.get("buyer_invoice_id"),
        "lot_id": row.get("lot_id"),
        "charge_type": row["charge_type"],
        "side": row["side"],
        "revenue_class": row["revenue_class"],
        "head": row["head"],
        "days": row["days"],
        "unit_rate": num_out(row["unit_rate"]),
        "amount": money_out(row["amount"]),
    }


def inspection_record(row):
    out = _common(row)
    out.update({
        "lot_id": row["lot_id"],
        "inspection_type": row["inspection_type"],
        "document_number": row["document_number"],
        "issue_date": row["issue_date"],
        "valid_through": row["valid_through"],
        "inspected_head": row["inspected_head"],
        "destination_state_code": row.get("destination_state_code"),
        "retest_count": row["retest_count"],
        "status": row["status"],
    })
    return out


def load_manifest(row):
    out = _common(row)
    out.update({
        "sale_day_id": row["sale_day_id"],
        "carrier_party_id": row["carrier_party_id"],
        "trailer_code": row["trailer_code"],
        "trailer_head_capacity": row["trailer_head_capacity"],
        "trailer_weight_capacity_lb": num_out(row["trailer_weight_capacity_lb"]),
        "haul_basis": row["haul_basis"],
        "loaded_miles": num_out(row["loaded_miles"]),
        "proration_basis": row["proration_basis"],
        "loaded_head": row["loaded_head"],
        "loaded_weight_lb": num_out(row["loaded_weight_lb"]),
        "haul_charge": money_out(row["haul_charge"]),
        "status": row["status"],
        "dispatched_at": row.get("dispatched_at"),
    })
    return out


def load_line(row):
    # Lean resource: id and created_at only.
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "load_manifest_id": row["load_manifest_id"],
        "lot_id": row["lot_id"],
        "head": row["head"],
        "weight_lb": num_out(row.get("weight_lb")),
        "prorated_haul_amount": money_out(row["prorated_haul_amount"]),
    }
