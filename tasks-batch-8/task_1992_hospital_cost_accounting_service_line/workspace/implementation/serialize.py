"""Entity serializers — exact public field sets (PRD §2.4, §3).

Money stored internally as Decimal is emitted as JSON numbers; input amounts
are echoed exactly as supplied; computed figures are round-half-up 2dp.
Append-only ledger lines (ActivityCostLine, SupplyLine) carry only id +
created_at — never updated_at / version.
"""

from decimal import Decimal


def num(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def service_line(sl):
    return {
        "id": sl["id"],
        "name": sl["name"],
        "code": sl["code"],
        "base_direct_cost": num(sl["base_direct_cost"]),
        "budgeted_volume": sl["budgeted_volume"],
        "total_direct_cost": num(sl["total_direct_cost"]),
        "total_revenue": num(sl["total_revenue"]),
        "contribution_margin": num(sl["contribution_margin"]),
        "status": sl["status"],
        "created_at": sl["created_at"],
        "updated_at": sl["updated_at"],
        "version": sl["version"],
    }


def cost_center(cc):
    out = {
        "id": cc["id"],
        "name": cc["name"],
        "code": cc["code"],
        "cost_type": cc["cost_type"],
        "cost_behavior": cc["cost_behavior"],
        "allocated_cost": num(cc["allocated_cost"]),
        "capacity_measure": cc["capacity_measure"],
        "status": cc["status"],
        "created_at": cc["created_at"],
        "updated_at": cc["updated_at"],
        "version": cc["version"],
    }
    if cc["capacity_measure"] == "MINUTES":
        out["practical_capacity_minutes"] = cc.get("practical_capacity_minutes")
    if cc["capacity_measure"] == "RVU":
        out["total_rvu"] = num(cc.get("total_rvu"))
    return out


def physician(p):
    return {
        "id": p["id"],
        "npi": p["npi"],
        "full_name": p["full_name"],
        "specialty": p["specialty"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def drg(d):
    return {
        "id": d["id"],
        "drg_code": d["drg_code"],
        "description": d["description"],
        "target_cost": num(d["target_cost"]),
        "base_rate": num(d["base_rate"]),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def cost_model(m):
    return {
        "id": m["id"],
        "name": m["name"],
        "service_line_id": m["service_line_id"],
        "allocation_basis": m["allocation_basis"],
        "rate_factor": num(m["rate_factor"]),
        "overhead_cost_center_id": m["overhead_cost_center_id"],
        "status": m["status"],
        "supersedes_model_id": m.get("supersedes_model_id"),
        "effective_period": m["effective_period"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def refresh(r):
    return {
        "id": r["id"],
        "model_id": r["model_id"],
        "period": r["period"],
        "proposed_rates": r["proposed_rates"],
        "data_quality_score": num(r["data_quality_score"]),
        "status": r["status"],
        "variance_report": r["variance_report"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def case(c):
    return {
        "id": c["id"],
        "service_line_id": c["service_line_id"],
        "physician_id": c["physician_id"],
        "drg_id": c["drg_id"],
        "cost_model_id": c["cost_model_id"],
        "period": c["period"],
        "expected_reimbursement": num(c["expected_reimbursement"]),
        "status": c["status"],
        "total_direct_cost": num(c["total_direct_cost"]),
        "total_indirect_allocated": num(c["total_indirect_allocated"]),
        "total_cost": num(c["total_cost"]),
        "margin": num(c["margin"]),
        "version_at_post": c["version_at_post"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def activity_line(line):
    # Append-only ledger line: id + created_at only (no updated_at / version).
    return {
        "id": line["id"],
        "case_id": line["case_id"],
        "cost_center_id": line["cost_center_id"],
        "quantity": num(line["quantity"]),
        "is_overhead_line": line["is_overhead_line"],
        "allocated_amount": num(line["allocated_amount"]),
        "created_at": line["created_at"],
    }


def implant(im):
    return {
        "id": im["id"],
        "case_id": im["case_id"],
        "item_code": im["item_code"],
        "vendor": im["vendor"],
        "unit_cost": num(im["unit_cost"]),
        "quantity": im["quantity"],
        "created_at": im["created_at"],
        "updated_at": im["updated_at"],
        "version": im["version"],
    }


def supply_line(sl):
    # Append-only ledger line: id + created_at only (no updated_at / version).
    return {
        "id": sl["id"],
        "case_id": sl["case_id"],
        "supply_code": sl["supply_code"],
        "unit_cost": num(sl["unit_cost"]),
        "quantity": sl["quantity"],
        "created_at": sl["created_at"],
    }


def payer_contract(pc):
    return {
        "id": pc["id"],
        "service_line_id": pc["service_line_id"],
        "payer_name": pc["payer_name"],
        "payer_type": pc["payer_type"],
        "contracted_rate": num(pc["contracted_rate"]),
        "effective_period": pc["effective_period"],
        "status": pc["status"],
        "created_at": pc["created_at"],
        "updated_at": pc["updated_at"],
        "version": pc["version"],
    }


def budget_period(bp):
    return {
        "id": bp["id"],
        "cost_center_id": bp["cost_center_id"],
        "period": bp["period"],
        "static_budget_amount": num(bp["static_budget_amount"]),
        "status": bp["status"],
        "actual_indirect_volume": num(bp["actual_indirect_volume"]),
        "flexed_overhead": num(bp["flexed_overhead"]),
        "variance_amount": num(bp["variance_amount"]),
        "variance_direction": bp["variance_direction"],
        "constraints_note": bp["constraints_note"],
        "created_at": bp["created_at"],
        "updated_at": bp["updated_at"],
        "version": bp["version"],
    }
