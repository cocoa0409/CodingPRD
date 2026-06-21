"""Per-entity output serializers. Each returns a plain dict with exactly the
fields the API exposes, dates rendered as ISO strings, internal keys dropped.
"""
from util import iso_date


def _common(rec):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }
    if "updated_at" in rec:
        out["updated_at"] = rec["updated_at"]
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def herd_out(h):
    out = _common(h)
    out.update({
        "name": h["name"],
        "species": h["species"],
        "premises_id": h["premises_id"],
        "active_animal_count": h["active_animal_count"],
        "total_au_load": h["total_au_load"],
        "mortality_rate_pct": h["mortality_rate_pct"],
    })
    return out


def pasture_out(p):
    out = _common(p)
    out.update({
        "name": p["name"],
        "kind": p["kind"],
        "capacity_au": p["capacity_au"],
        "rest_days": p["rest_days"],
        "current_au_load": p["current_au_load"],
    })
    return out


def drug_product_out(d):
    out = _common(d)
    out.update({
        "name": d["name"],
        "category": d["category"],
        "route_withdrawals": d["route_withdrawals"],
        "milk_withdrawal_hours": d["milk_withdrawal_hours"],
    })
    return out


def feed_ration_out(f):
    out = _common(f)
    out.update({
        "name": f["name"],
        "target_dmi_kg": f["target_dmi_kg"],
        "ingredients": f["ingredients"],
        "status": f["status"],
    })
    return out


def animal_out(a):
    out = _common(a)
    out.update({
        "herd_id": a["herd_id"],
        "ear_tag": a["ear_tag"],
        "rfid": a.get("rfid"),
        "sex": a["sex"],
        "birth_date": iso_date(a["birth_date"]),
        "birth_weight_kg": a["birth_weight_kg"],
        "dam_animal_id": a.get("dam_animal_id"),
        "sire_animal_id": a.get("sire_animal_id"),
        "current_pasture_id": a.get("current_pasture_id"),
        "latest_weight_kg": a["latest_weight_kg"],
        "lifetime_adg_kg": a["lifetime_adg_kg"],
        "life_status": a["life_status"],
        "meat_clearance_status": a["meat_clearance_status"],
        "meat_clear_on": iso_date(a.get("meat_clear_on")),
    })
    return out


def weight_record_out(w):
    # immutable history: id + created_at only (no updated_at / version)
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "animal_id": w["animal_id"],
        "weighed_at": iso_date(w["weighed_at"]),
        "weight_kg": w["weight_kg"],
        "source": w["source"],
        "interval_adg_kg": w["interval_adg_kg"],
    }


def breeding_record_out(b):
    out = _common(b)
    out.update({
        "dam_animal_id": b["dam_animal_id"],
        "sire_animal_id": b.get("sire_animal_id"),
        "bred_on": iso_date(b["bred_on"]),
        "expected_calving_on": iso_date(b.get("expected_calving_on")),
        "calved_on": iso_date(b.get("calved_on")),
        "calf_animal_id": b.get("calf_animal_id"),
        "status": b["status"],
    })
    return out


def health_treatment_out(t):
    out = _common(t)
    out.update({
        "animal_id": t["animal_id"],
        "drug_product_id": t["drug_product_id"],
        "route": t["route"],
        "dose_count": t["dose_count"],
        "first_dose_on": iso_date(t["first_dose_on"]),
        "last_dose_on": iso_date(t["last_dose_on"]),
        "clearance_date": iso_date(t.get("clearance_date")),
        "status": t["status"],
    })
    return out


def movement_record_out(m):
    out = _common(m)
    out.update({
        "animal_id": m["animal_id"],
        "to_pasture_id": m["to_pasture_id"],
        "from_pasture_id": m.get("from_pasture_id"),
        "effective_from": _iso_dt(m["effective_from"]),
        "effective_to": _iso_dt(m.get("effective_to")),
        "status": m["status"],
    })
    return out


def sale_lot_out(s):
    out = _common(s)
    out.update({
        "herd_id": s["herd_id"],
        "channel": s["channel"],
        "pencil_shrink_pct": s["pencil_shrink_pct"],
        "commission_pct": s["commission_pct"],
        "head_count": s["head_count"],
        "gross_sale_amount": s["gross_sale_amount"],
        "commission_amount": s["commission_amount"],
        "net_proceeds": s["net_proceeds"],
        "status": s["status"],
    })
    return out


def weight_ticket_out(t):
    out = _common(t)
    out.update({
        "sale_lot_id": t["sale_lot_id"],
        "animal_id": t["animal_id"],
        "gross_weight_kg": t["gross_weight_kg"],
        "price_per_100kg": t["price_per_100kg"],
        "net_weight_kg": t["net_weight_kg"],
        "gross_line_amount": t["gross_line_amount"],
    })
    return out


def mortality_record_out(m):
    out = _common(m)
    out.update({
        "animal_id": m["animal_id"],
        "died_on": iso_date(m["died_on"]),
        "cause": m["cause"],
        "disposal_method": m["disposal_method"],
        "status": m["status"],
    })
    return out


def trace_event_out(e):
    # immutable history: id + created_at only
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "animal_id": e["animal_id"],
        "event_type": e["event_type"],
        "ref_entity": e["ref_entity"],
        "ref_id": e["ref_id"],
        "occurred_on": iso_date(e["occurred_on"]),
        "detail": e["detail"],
    }


def _iso_dt(dt):
    from util import iso_datetime
    return iso_datetime(dt)
