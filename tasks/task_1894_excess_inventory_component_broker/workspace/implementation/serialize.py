"""Entity serializers — exact public representations."""

from calc import (
    bin_occupied_units,
    carrying_value_market,
    carrying_value_straight_line,
    customer_exposure,
    recommended_price_for_mpn,
    seller_payout_total,
)
from core import DB, iso


def _base(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_seller(s):
    payouts = seller_payout_total(s["id"])
    out = _base(s)
    out.update(
        {
            "name": s["name"],
            "contact_email": s["contact_email"],
            "payout_terms_days": s["payout_terms_days"],
            "account_balance_cents": payouts,
            "total_payouts_cents": payouts,
        }
    )
    return out


def ser_customer(c):
    out = _base(c)
    out.update(
        {
            "name": c["name"],
            "contact_email": c["contact_email"],
            "urgency_tier": c["urgency_tier"],
            "credit_limit_cents": c["credit_limit_cents"],
            "open_order_exposure_cents": customer_exposure(c["id"]),
        }
    )
    return out


def ser_bin(b):
    occupied = bin_occupied_units(b["id"])
    out = _base(b)
    out.update(
        {
            "bin_code": b["bin_code"],
            "capacity_units": b["capacity_units"],
            "occupied_units": occupied,
            "available_units": b["capacity_units"] - occupied,
        }
    )
    return out


def ser_offer(o):
    out = _base(o)
    out.update(
        {
            "seller_id": o["seller_id"],
            "mpn": o["mpn"],
            "quantity": o["quantity"],
            "ask_price_per_unit_cents": o["ask_price_per_unit_cents"],
            "provenance_doc_url": o["provenance_doc_url"],
            "status": o["status"],
            "agreed_unit_price_cents": o["agreed_unit_price_cents"],
            "acquisition_mode": o["acquisition_mode"],
            "inspection_result": o["inspection_result"],
            "failure_note": o["failure_note"],
        }
    )
    return out


def ser_lot(lot):
    out = _base(lot)
    out.update(
        {
            "buy_offer_id": lot["buy_offer_id"],
            "mpn": lot["mpn"],
            "storage_bin_id": lot["storage_bin_id"],
            "storage_mode": lot["storage_mode"],
            "quantity_received": lot["quantity_received"],
            "qty_available": lot["qty_available"],
            "qty_reserved": lot["qty_reserved"],
            "qty_sold": lot["qty_sold"],
            "qty_returned": lot["qty_returned"],
            "cost_basis_per_unit_cents": lot["cost_basis_per_unit_cents"],
            "received_at": iso(lot["received_at"]),
            "is_counterfeit_suspect": lot["is_counterfeit_suspect"],
            "status": lot["status"],
            "carrying_value_straight_line_cents": carrying_value_straight_line(lot),
            "carrying_value_market_cents": carrying_value_market(lot),
        }
    )
    return out


def ser_agreement(a):
    out = _base(a)
    out.update(
        {
            "seller_id": a["seller_id"],
            "lot_id": a["lot_id"],
            "effective_from": iso(a["effective_from"]),
            "effective_to": iso(a["effective_to"]),
            "broker_fee_bps": a["broker_fee_bps"],
            "status": a["status"],
        }
    )
    return out


def ser_snapshot(s):
    return {
        "id": s["id"],
        "mpn": s["mpn"],
        "spot_price_cents": s["spot_price_cents"],
        "source": s["source"],
        "observed_at": iso(s["observed_at"]),
        "created_at": iso(s["created_at"]),
    }


def ser_listing(lst):
    lot = DB.lots.get(lst["lot_id"])
    recommended = recommended_price_for_mpn(lot["mpn"]) if lot else None
    out = _base(lst)
    out.update(
        {
            "lot_id": lst["lot_id"],
            "asking_price_per_unit_cents": lst["asking_price_per_unit_cents"],
            "recommended_price_per_unit_cents": recommended,
            "status": lst["status"],
        }
    )
    return out


def ser_order(o):
    out = _base(o)
    out.update(
        {
            "customer_id": o["customer_id"],
            "listing_id": o["listing_id"],
            "quantity": o["quantity"],
            "urgency_tier_snapshot": o["urgency_tier_snapshot"],
            "consignment_fee_bps_snapshot": o["consignment_fee_bps_snapshot"],
            "provisional_unit_price_cents": o["provisional_unit_price_cents"],
            "provisional_total_cents": o["provisional_total_cents"],
            "required_escrow_cents": o["required_escrow_cents"],
            "escrow_funded_cents": o["escrow_funded_cents"],
            "final_unit_price_cents": o["final_unit_price_cents"],
            "final_total_cents": o["final_total_cents"],
            "customer_refund_cents": o["customer_refund_cents"],
            "status": o["status"],
        }
    )
    return out


def ser_escrow_entry(e):
    return {
        "id": e["id"],
        "sales_order_id": e["sales_order_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "note": e["note"],
        "created_at": iso(e["created_at"]),
    }


def ser_return_case(rc):
    out = _base(rc)
    out.update(
        {
            "sales_order_id": rc["sales_order_id"],
            "reason": rc["reason"],
            "status": rc["status"],
            "refund_amount_cents": rc["refund_amount_cents"],
            "rejection_note": rc["rejection_note"],
        }
    )
    return out
