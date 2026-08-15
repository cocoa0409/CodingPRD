"""Entity serializers — output exactly the fields declared in the scaffold
entity table plus the common system fields (id/created_at/updated_at/version).
Gallonage figures are Decimals carried at 1dp and serialize as JSON numbers."""
from timeutil import fmt_dt


def _common(e):
    return {
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def _num(v):
    """Decimal/int/float -> JSON number; None passes through."""
    if v is None:
        return None
    return float(v)


def ser_customer(c):
    out = {
        "id": c["id"],
        "name": c["name"],
        "credit_limit_cents": c["credit_limit_cents"],
        "dedicated_program_enrolled": c["dedicated_program_enrolled"],
        "status": c["status"],
        "exposure_cents": c["exposure_cents"],
    }
    out.update(_common(c))
    return out


def ser_product(p):
    out = {
        "id": p["id"],
        "name": p["name"],
        "compatibility_group": p["compatibility_group"],
        "hazmat_class": p["hazmat_class"],
        "packing_group": p["packing_group"],
        "density_lb_per_gal": _num(p["density_lb_per_gal"]),
        "temp_coeff_per_degF": _num(p["temp_coeff_per_degF"]),
        "placard_code": p["placard_code"],
    }
    out.update(_common(p))
    return out


def ser_compat_rule(r):
    out = {
        "id": r["id"],
        "prior_group": r["prior_group"],
        "next_group": r["next_group"],
        "required_wash_level": r["required_wash_level"],
        "forbidden": r["forbidden"],
    }
    out.update(_common(r))
    return out


def ser_trailer(t):
    out = {
        "id": t["id"],
        "unit_number": t["unit_number"],
        "capacity_gallons": t["capacity_gallons"],
        "tare_weight_lb": t["tare_weight_lb"],
        "tare_steer_lb": t["tare_steer_lb"],
        "tare_drive_lb": t["tare_drive_lb"],
        "tare_trailer_lb": t["tare_trailer_lb"],
        "steer_axle_rating_lb": t["steer_axle_rating_lb"],
        "drive_axle_rating_lb": t["drive_axle_rating_lb"],
        "trailer_axle_rating_lb": t["trailer_axle_rating_lb"],
        "gvwr_lb": t["gvwr_lb"],
        "last_product_group": t["last_product_group"],
        "last_wash_cert_id": t["last_wash_cert_id"],
        "dedicated_customer_id": t["dedicated_customer_id"],
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def ser_driver(d):
    out = {
        "id": d["id"],
        "full_name": d["full_name"],
        "cdl_number": d["cdl_number"],
        "tanker_endorsement": d["tanker_endorsement"],
        "hazmat_endorsement": d["hazmat_endorsement"],
        "endorsement_expires_on": d["endorsement_expires_on"].isoformat(),
        "status": d["status"],
    }
    out.update(_common(d))
    return out


def ser_wash_bay(b):
    out = {
        "id": b["id"],
        "bay_code": b["bay_code"],
        "supported_wash_levels": list(b["supported_wash_levels"]),
        "cleanup_buffer_minutes": b["cleanup_buffer_minutes"],
    }
    out.update(_common(b))
    return out


def ser_wash_cert(c):
    out = {
        "id": c["id"],
        "trailer_id": c["trailer_id"],
        "wash_bay_id": c["wash_bay_id"],
        "wash_level": c["wash_level"],
        "window_start": fmt_dt(c["window_start"]),
        "window_end": fmt_dt(c["window_end"]),
        "certified_at": fmt_dt(c["certified_at"]),
        "expires_at": fmt_dt(c["expires_at"]),
        "consumed_by_shipment_id": c["consumed_by_shipment_id"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_rack(r):
    out = {
        "id": r["id"],
        "rack_code": r["rack_code"],
        "terminal_name": r["terminal_name"],
        "authorized_groups": list(r["authorized_groups"]),
        "open_hour": r["open_hour"],
        "close_hour": r["close_hour"],
        "meter_id": r["meter_id"],
    }
    out.update(_common(r))
    return out


def ser_shipment(s):
    out = {
        "id": s["id"],
        "customer_id": s["customer_id"],
        "product_id": s["product_id"],
        "ordered_gallons": s["ordered_gallons"],
        "route_miles": s["route_miles"],
        "rate_per_gal_cents": s["rate_per_gal_cents"],
        "trailer_id": s["trailer_id"],
        "driver_id": s["driver_id"],
        "rack_id": s["rack_id"],
        "wash_cert_id": s["wash_cert_id"],
        "rack_window_start": fmt_dt(s["rack_window_start"]),
        "rack_window_end": fmt_dt(s["rack_window_end"]),
        "weights_verified_at": fmt_dt(s["weights_verified_at"]),
        "placards_confirmed": s["placards_confirmed"],
        "provisional_total_cents": s["provisional_total_cents"],
        "final_total_cents": s["final_total_cents"],
        "reconciled_at": fmt_dt(s["reconciled_at"]),
        "resolution_note": s["resolution_note"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_meter_ticket(t):
    out = {
        "id": t["id"],
        "shipment_id": t["shipment_id"],
        "rack_id": t["rack_id"],
        "opened_at": fmt_dt(t["opened_at"]),
        "closed_at": fmt_dt(t["closed_at"]),
        "meter_start_gal": _num(t["meter_start_gal"]),
        "meter_end_gal": _num(t["meter_end_gal"]),
        "observed_temp_F": _num(t["observed_temp_F"]),
        "observed_gallons": _num(t["observed_gallons"]),
        "net60_gallons": _num(t["net60_gallons"]),
        "closed_by_user_id": t["closed_by_user_id"],
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def ser_delivery_ticket(t):
    out = {
        "id": t["id"],
        "shipment_id": t["shipment_id"],
        "opened_at": fmt_dt(t["opened_at"]),
        "closed_at": fmt_dt(t["closed_at"]),
        "delivered_observed_gal": _num(t["delivered_observed_gal"]),
        "delivered_temp_F": _num(t["delivered_temp_F"]),
        "delivered_net60_gal": _num(t["delivered_net60_gal"]),
        "loaded_net60_gal": _num(t["loaded_net60_gal"]),
        "allowed_loss_gal": _num(t["allowed_loss_gal"]),
        "variance_gallons": _num(t["variance_gallons"]),
        "closed_by_driver_id": t["closed_by_driver_id"],
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def ser_retain_sample(s):
    out = {
        "id": s["id"],
        "shipment_id": s["shipment_id"],
        "delivery_ticket_id": s["delivery_ticket_id"],
        "quantity_ml": s["quantity_ml"],
        "taken_at": fmt_dt(s["taken_at"]),
        "retain_until": fmt_dt(s["retain_until"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_spill_plan(p):
    out = {
        "id": p["id"],
        "customer_id": p["customer_id"],
        "product_id": p["product_id"],
        "equipment_checklist": list(p["equipment_checklist"]),
        "approved_at": fmt_dt(p["approved_at"]),
        "expires_at": fmt_dt(p["expires_at"]),
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_spill_incident(i):
    out = {
        "id": i["id"],
        "shipment_id": i["shipment_id"],
        "reported_by_driver_id": i["reported_by_driver_id"],
        "occurred_at": fmt_dt(i["occurred_at"]),
        "reported_at": fmt_dt(i["reported_at"]),
        "gallons_spilled": _num(i["gallons_spilled"]),
        "severity": i["severity"],
        "closed_by_user_id": i["closed_by_user_id"],
        "status": i["status"],
    }
    out.update(_common(i))
    return out


def ser_agreement(a):
    out = {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "trailer_id": a["trailer_id"],
        "committed_loads_per_month": a["committed_loads_per_month"],
        "effective_from": fmt_dt(a["effective_from"]),
        "effective_to": fmt_dt(a["effective_to"]),
        "flagged_shipment_count": a["flagged_shipment_count"],
        "last_settled_month": a["last_settled_month"],
        "shortfall_events": a["shortfall_events"],
        "shortfall_fees_total_cents": a["shortfall_fees_total_cents"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out
