"""Entity serializers — convert internal dicts to API response objects."""
import db


def account_view(a):
    return {
        "id": a["id"],
        "company_name": a["company_name"],
        "epa_registration_id": a["epa_registration_id"],
        "escrow_reserved_cents": a["escrow_reserved_cents"],
        "spent_cents": a["spent_cents"],
        "created_at": db.iso(a["created_at"]),
        "updated_at": db.iso(a["updated_at"]),
        "version": a["version"],
    }


def year_view(y):
    return {
        "id": y["id"],
        "account_id": y["account_id"],
        "year": y["year"],
        "projected_volume_gal": y["projected_volume_gal"],
        "actual_volume_gal": y["actual_volume_gal"],
        "std_cellulosic_pct": y["std_cellulosic_pct"],
        "std_biomass_diesel_pct": y["std_biomass_diesel_pct"],
        "std_advanced_pct": y["std_advanced_pct"],
        "std_total_pct": y["std_total_pct"],
        "status": y["status"],
        "provisional_rvo_cellulosic_rins": y["provisional_rvo_cellulosic_rins"],
        "provisional_rvo_biomass_diesel_rins": y["provisional_rvo_biomass_diesel_rins"],
        "provisional_rvo_advanced_rins": y["provisional_rvo_advanced_rins"],
        "provisional_rvo_total_rins": y["provisional_rvo_total_rins"],
        "final_rvo_cellulosic_rins": y["final_rvo_cellulosic_rins"],
        "final_rvo_biomass_diesel_rins": y["final_rvo_biomass_diesel_rins"],
        "final_rvo_advanced_rins": y["final_rvo_advanced_rins"],
        "final_rvo_total_rins": y["final_rvo_total_rins"],
        "retired_cellulosic_rins": y["retired_cellulosic_rins"],
        "retired_biomass_diesel_rins": y["retired_biomass_diesel_rins"],
        "retired_advanced_rins": y["retired_advanced_rins"],
        "retired_total_rins": y["retired_total_rins"],
        "retired_prior_cellulosic_rins": y["retired_prior_cellulosic_rins"],
        "retired_prior_biomass_diesel_rins": y["retired_prior_biomass_diesel_rins"],
        "retired_prior_advanced_rins": y["retired_prior_advanced_rins"],
        "retired_prior_total_rins": y["retired_prior_total_rins"],
        "compliance_posture": y["compliance_posture"],
        "created_at": db.iso(y["created_at"]),
        "updated_at": db.iso(y["updated_at"]),
        "version": y["version"],
    }


def vendor_view(v):
    return {
        "id": v["id"],
        "account_id": v["account_id"],
        "vendor_name": v["vendor_name"],
        "qap_audited": v["qap_audited"],
        "diligence_status": v["diligence_status"],
        "last_diligence_at": db.iso(v["last_diligence_at"]),
        "created_at": db.iso(v["created_at"]),
        "updated_at": db.iso(v["updated_at"]),
        "version": v["version"],
    }


def lot_view(lot):
    return {
        "id": lot["id"],
        "account_id": lot["account_id"],
        "origin": lot["origin"],
        "vendor_id": lot["vendor_id"],
        "trade_id": lot["trade_id"],
        "d_code": lot["d_code"],
        "vintage_year": lot["vintage_year"],
        "gallon_qty": lot["gallon_qty"],
        "equivalence_value": lot["equivalence_value"],
        "rin_qty": lot["rin_qty"],
        "attached_qty": lot["attached_qty"],
        "separated_qty": lot["separated_qty"],
        "pending_retired_qty": lot["pending_retired_qty"],
        "retired_qty": lot["retired_qty"],
        "invalidated_qty": lot["invalidated_qty"],
        "expired_qty": lot["expired_qty"],
        "available_qty": lot["available_qty"],
        "unit_cost_cents": lot["unit_cost_cents"],
        "status": lot["status"],
        "retention_until": db.iso(lot["retention_until"]),
        "created_at": db.iso(lot["created_at"]),
        "updated_at": db.iso(lot["updated_at"]),
        "version": lot["version"],
    }


def blending_record_view(b):
    return {
        "id": b["id"],
        "account_id": b["account_id"],
        "rin_lot_id": b["rin_lot_id"],
        "blended_gallons": b["blended_gallons"],
        "blended_at": db.iso(b["blended_at"]),
        "retention_until": db.iso(b["retention_until"]),
        "created_at": db.iso(b["created_at"]),
    }


def trade_view(t):
    return {
        "id": t["id"],
        "account_id": t["account_id"],
        "vendor_id": t["vendor_id"],
        "d_code": t["d_code"],
        "vintage_year": t["vintage_year"],
        "rin_qty": t["rin_qty"],
        "price_per_rin_cents": t["price_per_rin_cents"],
        "total_price_cents": t["total_price_cents"],
        "payment_status": t["payment_status"],
        "transfer_status": t["transfer_status"],
        "created_by_user_id": t["created_by_user_id"],
        "delivered_at": db.iso(t["delivered_at"]),
        "verified_by_user_id": t["verified_by_user_id"],
        "retention_until": db.iso(t["retention_until"]),
        "created_at": db.iso(t["created_at"]),
        "updated_at": db.iso(t["updated_at"]),
        "version": t["version"],
    }


def batch_view(b):
    return {
        "id": b["id"],
        "obligation_year_id": b["obligation_year_id"],
        "category": b["category"],
        "d_code": b["d_code"],
        "rin_qty": b["rin_qty"],
        "allocations": b["allocations"],
        "prior_vintage_qty": b["prior_vintage_qty"],
        "status": b["status"],
        "submitted_at": db.iso(b["submitted_at"]),
        "created_at": db.iso(b["created_at"]),
        "updated_at": db.iso(b["updated_at"]),
        "version": b["version"],
    }


def report_view(r):
    return {
        "id": r["id"],
        "obligation_year_id": r["obligation_year_id"],
        "report_type": r["report_type"],
        "quarter_end_date": db.iso(r["quarter_end_date"]),
        "due_date": db.iso(r["due_date"]),
        "status": r["status"],
        "created_by_user_id": r["created_by_user_id"],
        "submitted_at": db.iso(r["submitted_at"]),
        "is_late": r["is_late"],
        "amendment_required": r["amendment_required"],
        "retention_until": db.iso(r["retention_until"]),
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def engagement_view(e):
    return {
        "id": e["id"],
        "obligation_year_id": e["obligation_year_id"],
        "auditor_user_id": e["auditor_user_id"],
        "fieldwork_start": db.iso(e["fieldwork_start"]),
        "fieldwork_end": db.iso(e["fieldwork_end"]),
        "status": e["status"],
        "findings": e["findings"],
        "created_at": db.iso(e["created_at"]),
        "updated_at": db.iso(e["updated_at"]),
        "version": e["version"],
    }


def program_view(p):
    return {
        "id": p["id"],
        "account_id": p["account_id"],
        "state_code": p["state_code"],
        "program_type": p["program_type"],
        "ci_standard_gco2e_mj": p["ci_standard_gco2e_mj"],
        "default_ci_gco2e_mj": p["default_ci_gco2e_mj"],
        "total_credits_tons": p["total_credits_tons"],
        "created_at": db.iso(p["created_at"]),
        "updated_at": db.iso(p["updated_at"]),
        "version": p["version"],
    }


def credit_report_view(c):
    return {
        "id": c["id"],
        "state_program_id": c["state_program_id"],
        "period_label": c["period_label"],
        "fuel_gallons": c["fuel_gallons"],
        "status": c["status"],
        "measured_ci_gco2e_mj": c["measured_ci_gco2e_mj"],
        "credits_tons": c["credits_tons"],
        "verified_at": db.iso(c["verified_at"]),
        "created_at": db.iso(c["created_at"]),
        "updated_at": db.iso(c["updated_at"]),
        "version": c["version"],
    }


def quote_view(q):
    return {
        "id": q["id"],
        "account_id": q["account_id"],
        "d_code": q["d_code"],
        "vintage_year": q["vintage_year"],
        "price_cents": q["price_cents"],
        "effective_start": db.iso(q["effective_start"]),
        "effective_end": db.iso(q["effective_end"]),
        "retention_until": db.iso(q["retention_until"]),
        "created_at": db.iso(q["created_at"]),
        "updated_at": db.iso(q["updated_at"]),
        "version": q["version"],
    }
