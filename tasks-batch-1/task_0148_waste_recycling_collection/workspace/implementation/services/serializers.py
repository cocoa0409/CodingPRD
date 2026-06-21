"""Public serialization of entities. Strips internal fields, exposes
computed fields. Field set per scaffold §1.1."""
from db import db


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def account(rec):
    out = _common(rec)
    out.update(
        {
            "service_address": rec["service_address"],
            "rate_class": rec["rate_class"],
            "status": rec["status"],
            "account_balance_cents": compute_account_balance(rec["id"]),
            "diversion_floor_pct": rec["diversion_floor_pct"],
        }
    )
    return out


def cart(rec):
    out = _common(rec)
    out.update(
        {
            "account_id": rec["account_id"],
            "stream": rec["stream"],
            "size_gallons": rec["size_gallons"],
            "status": rec["status"],
            "tare_weight_lbs": rec["tare_weight_lbs"],
        }
    )
    return out


def service_plan(rec):
    out = _common(rec)
    out.update(
        {
            "account_id": rec["account_id"],
            "stream": rec["stream"],
            "frequency": rec["frequency"],
            "base_monthly_fee_cents": rec["base_monthly_fee_cents"],
            "status": rec["status"],
        }
    )
    return out


def route(rec):
    out = _common(rec)
    out.update(
        {
            "service_date": rec["service_date"],
            "stream": rec["stream"],
            "status": rec["status"],
            "assigned_driver_id": rec["assigned_driver_id"],
            "total_net_weight_lbs": compute_route_total_net_weight(rec["id"]),
        }
    )
    return out


def stop(rec):
    out = _common(rec)
    out.update(
        {
            "route_id": rec["route_id"],
            "account_id": rec["account_id"],
            "sequence": rec["sequence"],
            "status": rec["status"],
        }
    )
    return out


def pickup(rec):
    out = _common(rec)
    out.update(
        {
            "stop_id": rec["stop_id"],
            "cart_id": rec["cart_id"],
            "outcome": rec["outcome"],
            "miss_reason": rec["miss_reason"],
            "contaminated": rec["contaminated"],
        }
    )
    return out


def contamination_tag(rec):
    out = _common(rec)
    out.update(
        {
            "pickup_id": rec["pickup_id"],
            "severity": rec["severity"],
            "status": rec["status"],
            "note": rec["note"],
        }
    )
    return out


def weight_ticket(rec):
    # Leaner entity: id + created_at only (PRD §2.4), plus its data fields.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "pickup_id": rec["pickup_id"],
        "gross_weight_lbs": rec["gross_weight_lbs"],
        "net_weight_lbs": rec["net_weight_lbs"],
        "diverted": rec["diverted"],
    }


def invoice(rec):
    out = _common(rec)
    out.update(
        {
            "account_id": rec["account_id"],
            "period_start": rec["period_start"],
            "period_end": rec["period_end"],
            "status": rec["status"],
            "base_fee_cents": rec["base_fee_cents"],
            "weight_charge_cents": rec["weight_charge_cents"],
            "contamination_surcharge_cents": rec["contamination_surcharge_cents"],
            "credit_cents": rec["credit_cents"],
            "total_cents": rec["total_cents"],
            "diversion_penalty_cents": rec["diversion_penalty_cents"],
            "balance_cents": rec["balance_cents"],
        }
    )
    return out


def special_pickup(rec):
    out = _common(rec)
    out.update(
        {
            "account_id": rec["account_id"],
            "kind": rec["kind"],
            "requested_date": rec["requested_date"],
            "hazard_class": rec["hazard_class"],
            "status": rec["status"],
            "quoted_fee_cents": rec["quoted_fee_cents"],
        }
    )
    return out


def missed_pickup_credit(rec):
    out = _common(rec)
    out.update(
        {
            "account_id": rec["account_id"],
            "source_type": rec["source_type"],
            "source_pickup_id": rec["source_pickup_id"],
            "source_special_pickup_id": rec["source_special_pickup_id"],
            "amount_cents": rec["amount_cents"],
            "status": rec["status"],
            "applied_invoice_id": rec["applied_invoice_id"],
        }
    )
    return out


def diversion_period(rec):
    out = _common(rec)
    out.update(
        {
            "account_id": rec["account_id"],
            "period_start": rec["period_start"],
            "period_end": rec["period_end"],
            "status": rec["status"],
            "diverted_weight_lbs": rec["diverted_weight_lbs"],
            "total_weight_lbs": rec["total_weight_lbs"],
            "diversion_rate_pct": rec["diversion_rate_pct"],
        }
    )
    return out


# --- derived/computed field helpers used by serializers and reconcilers ---

def compute_account_balance(account_id):
    """sum of Invoice.balance_cents in {ISSUED, DISPUTED} for this account
    minus sum of MissedPickupCredit.amount_cents in APPLIED status."""
    inv_total = 0
    for inv in db.invoices.values():
        if inv["account_id"] == account_id and inv["status"] in ("ISSUED", "DISPUTED"):
            inv_total += inv["balance_cents"]
    credit_total = 0
    for cr in db.credits.values():
        if cr["account_id"] == account_id and cr["status"] == "APPLIED":
            credit_total += cr["amount_cents"]
    return inv_total - credit_total


def compute_route_total_net_weight(route_id):
    """sum of WeightTicket.net_weight_lbs across COMPLETED pickups whose stop
    belongs to this route."""
    total = 0.0
    for wt in db.weight_tickets.values():
        pu = db.pickups.get(wt["pickup_id"])
        if pu is None or pu["outcome"] != "COMPLETED":
            continue
        st = db.stops.get(pu["stop_id"])
        if st is not None and st["route_id"] == route_id:
            total += wt["net_weight_lbs"]
    # Keep float; sum of 3-dp values.
    return round(total, 3)
