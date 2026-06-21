"""Serializers: internal record -> public API output dict (PRD 2.5 envelopes).

Each serializer formats datetimes to ISO 8601 UTC (three fractional digits)
and exposes exactly the entity's documented fields plus the common system
fields. Internal bookkeeping keys (prefixed '_') are never exposed.
"""
from timeutil import format_iso
import derive


def _common(record):
    return {
        "id": record["id"],
        "created_at": format_iso(record["created_at"]),
        "updated_at": format_iso(record["updated_at"]),
        "version": record["version"],
    }


def vendor(v):
    out = _common(v)
    out.update(
        {
            "name": v["name"],
            "vendor_type": v["vendor_type"],
            "support_email": v["support_email"],
            "active": v["active"],
        }
    )
    return out


def employee(e):
    out = _common(e)
    out.update(
        {
            "full_name": e["full_name"],
            "email": e["email"],
            "department": e["department"],
            "max_assigned_assets": e["max_assigned_assets"],
            "status": e["status"],
            "open_checkout_count": derive.employee_open_checkout_count(e["id"]),
        }
    )
    return out


def software_product(p):
    out = _common(p)
    out.update(
        {
            "vendor_id": p["vendor_id"],
            "name": p["name"],
            "license_model": p["license_model"],
            "core_factor": p["core_factor"],
            "min_core_units": p["min_core_units"],
            "compliance_status": p["compliance_status"],
        }
    )
    return out


def hardware_asset(a):
    out = _common(a)
    out.update(
        {
            "vendor_id": a["vendor_id"],
            "asset_tag": a["asset_tag"],
            "category": a["category"],
            "physical_cores": a["physical_cores"],
            "purchase_cost_cents": a["purchase_cost_cents"],
            "in_service_date": format_iso(a["in_service_date"]),
            "useful_life_months": a["useful_life_months"],
            "salvage_value_cents": a["salvage_value_cents"],
            "status": a["status"],
            "support_status": a["support_status"],
            "accumulated_depreciation_cents": a["accumulated_depreciation_cents"],
            "net_book_value_cents": a["net_book_value_cents"],
            "disposal_proceeds_cents": a["disposal_proceeds_cents"],
            "disposal_gain_loss_cents": a["disposal_gain_loss_cents"],
        }
    )
    return out


def warranty_lease(c):
    out = _common(c)
    out.update(
        {
            "hardware_asset_id": c["hardware_asset_id"],
            "vendor_id": c["vendor_id"],
            "coverage_type": c["coverage_type"],
            "coverage_start": format_iso(c["coverage_start"]),
            "coverage_end": format_iso(c["coverage_end"]),
            "monthly_cost_cents": c["monthly_cost_cents"],
            "auto_renew": c["auto_renew"],
            "status": c["status"],
        }
    )
    return out


def license_entitlement(e):
    out = _common(e)
    out.update(
        {
            "software_product_id": e["software_product_id"],
            "vendor_id": e["vendor_id"],
            "entitled_units": e["entitled_units"],
            "unit_price_cents": e["unit_price_cents"],
            "term_start": format_iso(e["term_start"]),
            "term_end": format_iso(e["term_end"]),
            "grace_days": e["grace_days"],
            "status": e["status"],
            "consumed_units": e["consumed_units"],
            "available_units": e["available_units"],
        }
    )
    return out


def installation_record(i):
    out = _common(i)
    out.update(
        {
            "software_product_id": i["software_product_id"],
            "hardware_asset_id": i["hardware_asset_id"],
            "license_entitlement_id": i["license_entitlement_id"],
            "required_core_units": i["required_core_units"],
            "status": i["status"],
            "activated_at": format_iso(i["activated_at"]),
        }
    )
    return out


def assignment_checkout(c):
    out = _common(c)
    out.update(
        {
            "hardware_asset_id": c["hardware_asset_id"],
            "employee_id": c["employee_id"],
            "checkout_at": format_iso(c["checkout_at"]),
            "expected_return_at": format_iso(c["expected_return_at"]),
            "returned_at": format_iso(c["returned_at"]),
            "status": c["status"],
        }
    )
    return out


def disposal_request(d):
    out = _common(d)
    out.update(
        {
            "hardware_asset_id": d["hardware_asset_id"],
            "submitted_by_user_id": d["submitted_by_user_id"],
            "reason": d["reason"],
            "proposed_proceeds_cents": d["proposed_proceeds_cents"],
            "approved_by_user_id": d["approved_by_user_id"],
            "status": d["status"],
        }
    )
    return out


def renewal_order(r):
    out = _common(r)
    out.update(
        {
            "target_type": r["target_type"],
            "license_entitlement_id": r["license_entitlement_id"],
            "warranty_lease_id": r["warranty_lease_id"],
            "extend_months": r["extend_months"],
            "added_units": r["added_units"],
            "quoted_cost_cents": r["quoted_cost_cents"],
            "status": r["status"],
        }
    )
    return out


def true_up_reconciliation(t):
    out = _common(t)
    out.update(
        {
            "software_product_id": t["software_product_id"],
            "variant": t["variant"],
            "as_of": format_iso(t["as_of"]),
            "total_entitled_units": t["total_entitled_units"],
            "total_consumed_units": t["total_consumed_units"],
            "position_units": t["position_units"],
            "verdict": t["verdict"],
            "status": t["status"],
        }
    )
    return out


def compliance_finding(f):
    # Lean entity: only id and created_at among the common fields (PRD 2.5).
    return {
        "id": f["id"],
        "created_at": format_iso(f["created_at"]),
        "true_up_reconciliation_id": f["true_up_reconciliation_id"],
        "software_product_id": f["software_product_id"],
        "finding_type": f["finding_type"],
        "detail": f["detail"],
        "shortfall_units": f["shortfall_units"],
    }
