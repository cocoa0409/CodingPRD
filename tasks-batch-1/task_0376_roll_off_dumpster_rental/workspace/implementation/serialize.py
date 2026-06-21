"""Serialize internal records into API responses, computing derived fields."""
from db import db


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def container_type(rec):
    out = _common(rec)
    out.update({
        "size_code": rec["size_code"],
        "base_rate_cents": rec["base_rate_cents"],
        "included_days": rec["included_days"],
        "overage_day_cents": rec["overage_day_cents"],
        "included_tonnage_lbs": rec["included_tonnage_lbs"],
        "overage_rate_cents_per_lb": rec["overage_rate_cents_per_lb"],
        "active": rec["active"],
    })
    return out


def account_outstanding_cents(account_id):
    total = 0
    for inv in db.invoices.values():
        if inv["account_id"] == account_id and inv["status"] == "ISSUED":
            total += inv["total_cents"]
    return total


def contractor_account(rec):
    out = _common(rec)
    outstanding = account_outstanding_cents(rec["id"])
    out.update({
        "business_name": rec["business_name"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "outstanding_cents": outstanding,
        "available_credit_cents": rec["credit_limit_cents"] - outstanding,
        "status": rec["status"],
    })
    return out


def container(rec):
    out = _common(rec)
    out.update({
        "container_type_id": rec["container_type_id"],
        "asset_tag": rec["asset_tag"],
        "yard_code": rec["yard_code"],
        "status": rec["status"],
        "current_order_id": rec["current_order_id"],
    })
    return out


def route_stop_count(route_id):
    n = 0
    for s in db.service_stops.values():
        if s["route_id"] == route_id and s["status"] != "CANCELLED":
            n += 1
    return n


def route(rec):
    out = _common(rec)
    out.update({
        "service_date": rec["service_date"],
        "truck_code": rec["truck_code"],
        "capacity_stops": rec["capacity_stops"],
        "stop_count": route_stop_count(rec["id"]),
        "status": rec["status"],
    })
    return out


def rental_order(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "container_type_id": rec["container_type_id"],
        "container_id": rec["container_id"],
        "site_address": rec["site_address"],
        "requested_delivery_date": rec["requested_delivery_date"],
        "delivered_on": rec["delivered_on"],
        "picked_up_on": rec["picked_up_on"],
        "rental_days": rec["rental_days"],
        "requires_street_permit": rec["requires_street_permit"],
        "logistics_status": rec["logistics_status"],
        "billing_status": rec["billing_status"],
        "estimated_total_cents": rec["estimated_total_cents"],
        "final_total_cents": rec["final_total_cents"],
    })
    return out


def service_stop(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "route_id": rec["route_id"],
        "stop_type": rec["stop_type"],
        "sequence": rec["sequence"],
        "estimated_weight_lbs": rec["estimated_weight_lbs"],
        "status": rec["status"],
    })
    return out


def weigh_ticket(rec):
    # Append-only: only id + created_at, no updated_at / version.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "order_id": rec["order_id"],
        "service_stop_id": rec["service_stop_id"],
        "gross_weight_lbs": rec["gross_weight_lbs"],
        "tare_weight_lbs": rec["tare_weight_lbs"],
        "net_weight_lbs": rec["net_weight_lbs"],
        "contaminated": rec["contaminated"],
        "contamination_kind": rec["contamination_kind"],
    }


def street_permit(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "municipality": rec["municipality"],
        "permit_fee_cents": rec["permit_fee_cents"],
        "valid_from": rec["valid_from"],
        "valid_until": rec["valid_until"],
        "status": rec["status"],
    })
    return out


def invoice(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "account_id": rec["account_id"],
        "base_cents": rec["base_cents"],
        "overage_day_cents": rec["overage_day_cents"],
        "tonnage_cents": rec["tonnage_cents"],
        "permit_cents": rec["permit_cents"],
        "contamination_cents": rec["contamination_cents"],
        "total_cents": rec["total_cents"],
        "status": rec["status"],
    })
    return out


def clock_state(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "current_date": rec["current_date"],
    }
