"""Entity -> JSON serializers. System fields: id, created_at, updated_at,
version (RefrigerantEvent is exempt: no updated_at / version). Internal keys
(starting with '_') are never serialized."""
from utils import iso, dec_out


def _common(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def contractor(c):
    out = _common(c)
    out.update({
        "company_name": c["company_name"],
        "license_number": c["license_number"],
        "tier": c["tier"],
        "ytd_purchase_cents": c["ytd_purchase_cents"],
        "coop_accrual_provisional_cents": c["coop_accrual_provisional_cents"],
        "coop_accrual_final_cents": c["coop_accrual_final_cents"],
        "training_credit_balance_hours": c["training_credit_balance_hours"],
        "compliance_standing": c["compliance_standing"],
        "heel_violation_count_12m": c["heel_violation_count_12m"],
        "credit_hold": c["credit_hold"],
        "status": c["status"],
    })
    return out


def equipment_model(m):
    out = _common(m)
    out.update({
        "model_number": m["model_number"],
        "equipment_type": m["equipment_type"],
        "refrigerant_type": m["refrigerant_type"],
        "capacity_btuh": m["capacity_btuh"],
        "family_code": m["family_code"],
        "list_price_cents": m["list_price_cents"],
        "status": m["status"],
    })
    return out


def ahri_rating(r):
    out = _common(r)
    out.update({
        "ahri_reference_number": r["ahri_reference_number"],
        "outdoor_unit_id": r["outdoor_unit_id"],
        "indoor_unit_id": r["indoor_unit_id"],
        "furnace_id": r.get("furnace_id"),
        "seer2": dec_out(r["seer2"], "0.1"),
        "eer2": dec_out(r["eer2"], "0.1"),
        "hspf2": dec_out(r["hspf2"], "0.1") if r.get("hspf2") is not None else None,
        "efficiency_class": r["efficiency_class"],
        "tax_credit_eligible": r["tax_credit_eligible"],
        "status": r["status"],
    })
    return out


def prebuy_program(p):
    out = _common(p)
    out.update({
        "name": p["name"],
        "family_code": p["family_code"],
        "window_start": iso(p["window_start"]),
        "window_end": iso(p["window_end"]),
        "ship_by_date": iso(p["ship_by_date"]),
        "deposit_pct": float(p["deposit_pct"]),
        "discount_pct": float(p["discount_pct"]),
        "status": p["status"],
    })
    return out


def order(o):
    out = _common(o)
    out.update({
        "contractor_id": o["contractor_id"],
        "prebuy_program_id": o.get("prebuy_program_id"),
        "status": o["status"],
        "billing_status": o["billing_status"],
        "subtotal_cents": o["subtotal_cents"],
        "discount_cents": o["discount_cents"],
        "total_cents": o["total_cents"],
        "deposit_due_cents": o["deposit_due_cents"],
        "submitted_at": iso(o.get("submitted_at")),
    })
    return out


def order_line(l):
    out = _common(l)
    out.update({
        "order_id": l["order_id"],
        "ahri_rating_id": l.get("ahri_rating_id"),
        "equipment_model_id": l.get("equipment_model_id"),
        "quantity": l["quantity"],
        "unit_price_cents": l["unit_price_cents"],
        "line_discount_cents": l["line_discount_cents"],
        "line_total_cents": l["line_total_cents"],
    })
    return out


def allocation_pool(p):
    out = _common(p)
    out.update({
        "family_code": p["family_code"],
        "season_start": iso(p["season_start"]),
        "season_end": iso(p["season_end"]),
        "total_qty": p["total_qty"],
        "reserved_qty": p["reserved_qty"],
        "committed_qty": p["committed_qty"],
        "status": p["status"],
    })
    return out


def warranty_registration(w):
    out = _common(w)
    out.update({
        "serial_number": w["serial_number"],
        "equipment_model_id": w["equipment_model_id"],
        "contractor_id": w["contractor_id"],
        "order_id": w["order_id"],
        "install_date": iso(w["install_date"]),
        "registration_deadline": iso(w["registration_deadline"]),
        "registered_at": iso(w.get("registered_at")),
        "extended_coverage_years": w["extended_coverage_years"],
        "status": w["status"],
    })
    return out


def parts_claim(p):
    out = _common(p)
    out.update({
        "claim_number": p["claim_number"],
        "warranty_registration_id": p["warranty_registration_id"],
        "contractor_id": p["contractor_id"],
        "failure_date": iso(p["failure_date"]),
        "part_cost_cents": p["part_cost_cents"],
        "labor_cost_cents": p["labor_cost_cents"],
        "covered_part_cents": p["covered_part_cents"],
        "covered_labor_cents": p["covered_labor_cents"],
        "total_award_cents": p["total_award_cents"],
        "revision_count": p["revision_count"],
        "status": p["status"],
    })
    return out


def refrigerant_cylinder(c):
    out = _common(c)
    out.update({
        "cylinder_tag": c["cylinder_tag"],
        "refrigerant_type": c["refrigerant_type"],
        "tare_weight_lbs": dec_out(c["tare_weight_lbs"]),
        "full_weight_lbs": dec_out(c["full_weight_lbs"]),
        "current_weight_lbs": dec_out(c["current_weight_lbs"]),
        "holder_contractor_id": c.get("holder_contractor_id"),
        "issued_at": iso(c.get("issued_at")),
        "status": c["status"],
    })
    return out


def refrigerant_event(e):
    # Append-only ledger entry: id + created_at only (no updated_at / version).
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "cylinder_id": e["cylinder_id"],
        "event_type": e["event_type"],
        "weight_delta_lbs": dec_out(e["weight_delta_lbs"]),
        "recorded_at": iso(e["recorded_at"]),
        "note": e.get("note"),
    }


def rebate_submission(r):
    out = _common(r)
    out.update({
        "contractor_id": r["contractor_id"],
        "order_id": r["order_id"],
        "ahri_rating_id": r["ahri_rating_id"],
        "program_type": r["program_type"],
        "homeowner_name": r["homeowner_name"],
        "install_address": r["install_address"],
        "install_date": iso(r["install_date"]),
        "docs": list(r.get("docs", [])),
        "qualified_amount_cents": r["qualified_amount_cents"],
        "submitted_at": iso(r.get("submitted_at")),
        "decision_deadline": iso(r.get("decision_deadline")),
        "status": r["status"],
    })
    return out


def training_course(t):
    out = _common(t)
    out.update({
        "course_code": t["course_code"],
        "title": t["title"],
        "credit_hours": t["credit_hours"],
        "session_start": iso(t["session_start"]),
        "session_end": iso(t["session_end"]),
        "instructor_name": t["instructor_name"],
        "max_seats": t["max_seats"],
        "status": t["status"],
    })
    return out


def training_credit(t):
    out = _common(t)
    out.update({
        "contractor_id": t["contractor_id"],
        "course_id": t["course_id"],
        "credit_hours": t["credit_hours"],
        "earned_at": iso(t["earned_at"]),
        "expires_at": iso(t["expires_at"]),
        "consumed_hours": t["consumed_hours"],
        "status": t["status"],
    })
    return out


def coop_claim(c):
    out = _common(c)
    out.update({
        "contractor_id": c["contractor_id"],
        "invoice_reference": c["invoice_reference"],
        "period": c["period"],
        "spend_cents": c["spend_cents"],
        "eligible_amount_cents": c["eligible_amount_cents"],
        "approved_amount_cents": c.get("approved_amount_cents"),
        "status": c["status"],
    })
    return out
