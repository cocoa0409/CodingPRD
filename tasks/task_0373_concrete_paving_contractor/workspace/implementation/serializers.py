"""Entity -> response-dict serializers. Field names match scaffold §1.1 exactly."""
from util import iso_format, iso_echo


def project_dict(p):
    return {
        "id": p["id"],
        "created_at": iso_format(p["created_at"]),
        "updated_at": iso_format(p["updated_at"]),
        "version": p["version"],
        "site_name": p["site_name"],
        "client_name": p["client_name"],
        "status": p["status"],
        "status_before_hold": p["status_before_hold"],
        "base_contract_amount": p["base_contract_amount"],
        "provisional_contract_value": p["provisional_contract_value"],
        "committed_contract_value": p["committed_contract_value"],
        "total_drawn_amount": p["total_drawn_amount"],
        "warranty_risk_score": p["warranty_risk_score"],
        "approved_estimate_id": p["approved_estimate_id"],
    }


def segment_dict(s):
    return {
        "id": s["id"],
        "created_at": iso_format(s["created_at"]),
        "updated_at": iso_format(s["updated_at"]),
        "version": s["version"],
        "project_id": s["project_id"],
        "label": s["label"],
        "area_sqft": s["area_sqft"],
        "thickness_in": s["thickness_in"],
        "finish_grade": s["finish_grade"],
        "reinforcement": s["reinforcement"],
    }


def estimate_dict(e):
    return {
        "id": e["id"],
        "created_at": iso_format(e["created_at"]),
        "updated_at": iso_format(e["updated_at"]),
        "version": e["version"],
        "project_id": e["project_id"],
        "provisional_cubic_yards": e["provisional_cubic_yards"],
        "total_sqft": e["total_sqft"],
        "labor_subtotal": e["labor_subtotal"],
        "material_subtotal": e["material_subtotal"],
        "estimate_total": e["estimate_total"],
        "status": e["status"],
    }


def permit_dict(p):
    return {
        "id": p["id"],
        "created_at": iso_format(p["created_at"]),
        "updated_at": iso_format(p["updated_at"]),
        "version": p["version"],
        "project_id": p["project_id"],
        "jurisdiction": p["jurisdiction"],
        "permit_number": p["permit_number"],
        "status": p["status"],
    }


def material_order_dict(m):
    return {
        "id": m["id"],
        "created_at": iso_format(m["created_at"]),
        "updated_at": iso_format(m["updated_at"]),
        "version": m["version"],
        "project_id": m["project_id"],
        "mix_type": m["mix_type"],
        "order_cubic_yards": m["order_cubic_yards"],
        "pour_scheduled_start": iso_echo(m["pour_scheduled_start"]),
        "pour_duration_hours": m["pour_duration_hours"],
        "pour_completed_at": iso_echo(m["pour_completed_at"]),
        "cure_window_end": iso_echo(m["cure_window_end"]),
        "status": m["status"],
    }


def weather_reading_dict(w):
    return {
        "id": w["id"],
        "created_at": iso_format(w["created_at"]),
        "material_order_id": w["material_order_id"],
        "reading_at": iso_echo(w["reading_at"]),
        "temp_f": w["temp_f"],
        "precip_pct": w["precip_pct"],
    }


def crew_dict(c):
    return {
        "id": c["id"],
        "created_at": iso_format(c["created_at"]),
        "updated_at": iso_format(c["updated_at"]),
        "version": c["version"],
        "crew_name": c["crew_name"],
        "skill": c["skill"],
        "headcount": c["headcount"],
    }


def equipment_dict(e):
    return {
        "id": e["id"],
        "created_at": iso_format(e["created_at"]),
        "updated_at": iso_format(e["updated_at"]),
        "version": e["version"],
        "asset_name": e["asset_name"],
        "asset_type": e["asset_type"],
    }


def crew_assignment_dict(a):
    return {
        "id": a["id"],
        "created_at": iso_format(a["created_at"]),
        "updated_at": iso_format(a["updated_at"]),
        "version": a["version"],
        "project_id": a["project_id"],
        "crew_id": a["crew_id"],
        "equipment_id": a["equipment_id"],
        "window_start": iso_echo(a["window_start"]),
        "window_end": iso_echo(a["window_end"]),
        "status": a["status"],
    }


def change_order_dict(c):
    return {
        "id": c["id"],
        "created_at": iso_format(c["created_at"]),
        "updated_at": iso_format(c["updated_at"]),
        "version": c["version"],
        "project_id": c["project_id"],
        "description": c["description"],
        "delta_amount": c["delta_amount"],
        "delta_sqft": c["delta_sqft"],
        "status": c["status"],
        "submitted_by_user_id": c["submitted_by_user_id"],
    }


def draw_dict(d):
    return {
        "id": d["id"],
        "created_at": iso_format(d["created_at"]),
        "updated_at": iso_format(d["updated_at"]),
        "version": d["version"],
        "project_id": d["project_id"],
        "draw_type": d["draw_type"],
        "amount": d["amount"],
        "status": d["status"],
        "released_by_user_id": d["released_by_user_id"],
    }


def warranty_dict(w):
    return {
        "id": w["id"],
        "created_at": iso_format(w["created_at"]),
        "updated_at": iso_format(w["updated_at"]),
        "version": w["version"],
        "project_id": w["project_id"],
        "term_months": w["term_months"],
        "defect_claims_count": w["defect_claims_count"],
        "status": w["status"],
    }
