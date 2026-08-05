"""Entity -> JSON serializers."""
from core import common_out, fmt_ts
from calc import compute_benefit_fields


def ser_client(c):
    out = common_out(c)
    out.update({
        "legal_name": c["legal_name"],
        "entity_type": c["entity_type"],
        "marginal_tax_rate": c["marginal_tax_rate"],
        "status": c["status"],
        "outstanding_fee_cents": c["outstanding_fee_cents"],
    })
    return out


def ser_property(p):
    out = common_out(p)
    out.update({
        "client_id": p["client_id"],
        "address": p["address"],
        "building_type": p["building_type"],
        "purchase_price_cents": p["purchase_price_cents"],
        "land_value_cents": p["land_value_cents"],
        "placed_in_service_date": fmt_ts(p["placed_in_service_date"]),
        "depreciable_basis_cents": p["depreciable_basis_cents"],
    })
    return out


def ser_engineer(e):
    out = common_out(e, with_version=False)
    out.update({
        "full_name": e["full_name"],
        "email": e["email"],
    })
    return out


def ser_study(s):
    out = common_out(s)
    out.update({
        "client_id": s["client_id"],
        "property_id": s.get("property_id"),
        "assigned_engineer_id": s.get("assigned_engineer_id"),
        "study_type": s["study_type"],
        "tax_year": s["tax_year"],
        "is_look_back": s["is_look_back"],
        "fee_type": s.get("fee_type"),
        "fee_fixed_amount_cents": s.get("fee_fixed_amount_cents"),
        "fee_percent_bps": s.get("fee_percent_bps"),
        "credit_method": s.get("credit_method"),
        "fixed_base_pct": s.get("fixed_base_pct"),
        "avg_annual_gross_receipts_cents": s.get("avg_annual_gross_receipts_cents"),
        "prior_qre_year1_cents": s.get("prior_qre_year1_cents", 0),
        "prior_qre_year2_cents": s.get("prior_qre_year2_cents", 0),
        "prior_qre_year3_cents": s.get("prior_qre_year3_cents", 0),
        "status": s["status"],
        "reviewer_engineer_id": s.get("reviewer_engineer_id"),
        "total_allocated_cost_cents": s["total_allocated_cost_cents"],
        "section_481a_cents": s.get("section_481a_cents", 0),
    })
    out.update(compute_benefit_fields(s))
    return out


def ser_component(c):
    out = common_out(c)
    out.update({
        "study_id": c["study_id"],
        "component_name": c["component_name"],
        "asset_class": c["asset_class"],
        "allocated_cost_cents": c["allocated_cost_cents"],
        "recovery_period_years": c["recovery_period_years"],
        "status": c["status"],
    })
    return out


def ser_qre(q):
    out = common_out(q)
    out.update({
        "study_id": q["study_id"],
        "qre_category": q["qre_category"],
        "gross_amount_cents": q["gross_amount_cents"],
        "qualified_percent": q["qualified_percent"],
        "qualified_amount_cents": q["qualified_amount_cents"],
        "status": q["status"],
    })
    return out


def ser_report(r):
    out = common_out(r)
    out.update({
        "study_id": r["study_id"],
        "report_type": r["report_type"],
        "revision_count": r["revision_count"],
        "issued_at": fmt_ts(r["issued_at"]) if r["issued_at"] else None,
        "status": r["status"],
    })
    return out


def ser_audit(a):
    out = common_out(a)
    out.update({
        "study_id": a["study_id"],
        "irs_notice_ref": a["irs_notice_ref"],
        "resolution_note": a.get("resolution_note"),
        "status": a["status"],
    })
    return out


def ser_amended(a):
    out = common_out(a)
    out.update({
        "study_id": a["study_id"],
        "amended_tax_year": a["amended_tax_year"],
        "section_481a_cents": a["section_481a_cents"],
        "filed_at": fmt_ts(a["filed_at"]) if a["filed_at"] else None,
        "status": a["status"],
    })
    return out


def ser_fee(f):
    out = common_out(f)
    out.update({
        "study_id": f["study_id"],
        "amount_cents": f["amount_cents"],
        "fee_basis": f["fee_basis"],
        "status": f["status"],
    })
    return out
