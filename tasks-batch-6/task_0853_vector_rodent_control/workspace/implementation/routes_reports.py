"""Program reporting roll-up (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import envelope
import store
import valid

bp = Blueprint("reports", __name__)
P = "/vector-control"


@bp.get(P + "/reports/program-summary")
def program_summary():
    auth.guard("ProgramAdmin", "Supervisor")
    zone_id = valid.query_str("zone_id")

    def property_zone(property_id):
        prop = store.properties.get(property_id)
        return prop["zone_id"] if prop is not None else None

    complaints = [
        c for c in store.complaints.values() if zone_id is None or c["zone_id"] == zone_id
    ]
    properties = [
        p for p in store.properties.values() if zone_id is None or p["zone_id"] == zone_id
    ]
    orders = [
        o
        for o in store.orders.values()
        if zone_id is None or property_zone(o["property_id"]) == zone_id
    ]
    invoices = [
        i
        for i in store.invoices.values()
        if zone_id is None or property_zone(i["property_id"]) == zone_id
    ]
    zones = [z for z in store.zones.values() if zone_id is None or z["id"] == zone_id]

    return envelope.obj(
        {
            "complaint_total": len(complaints),
            "complaint_open": sum(
                1 for c in complaints if c["status"] not in calc.CLOSED_COMPLAINT_STATUSES
            ),
            "complaint_closed_resolved": sum(
                1 for c in complaints if c["status"] == "CLOSED_RESOLVED"
            ),
            "orders_issued": len(orders),
            "orders_complied": sum(1 for o in orders if o["status"] == "COMPLIED"),
            "orders_city_abated": sum(1 for o in orders if o["status"] == "CITY_ABATED"),
            "chronic_property_count": sum(1 for p in properties if p["chronic_flag"]),
            "hotspot_zone_count": sum(1 for z in zones if z["posture"] == "HOTSPOT"),
            "invoiced_cents": sum(
                (i["final_total_cents"] or 0)
                for i in invoices
                if i["billing_status"] in ("APPROVED", "PARTIALLY_PAID", "PAID")
            ),
            "collected_cents": sum(i["amount_paid_cents"] for i in invoices),
            "outstanding_cents": sum(
                i["balance_due_cents"]
                for i in invoices
                if i["billing_status"] in ("APPROVED", "PARTIALLY_PAID")
            ),
            "liens_filed": sum(1 for i in invoices if i["lien_status"] == "FILED"),
        }
    )
