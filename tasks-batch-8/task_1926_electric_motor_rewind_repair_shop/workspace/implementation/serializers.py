"""Serialize internal entity dicts to API response shapes (datetime -> ISO strings)."""
from db import format_ts


def _fmt_dt_fields(obj, fields):
    for f in fields:
        v = obj.get(f)
        if v is not None and not isinstance(v, str):
            obj[f] = format_ts(v)
    return obj


def _base(entity, include_version=True, include_updated=True):
    out = {"id": entity["id"]}
    if include_version and "created_at" in entity:
        out["created_at"] = format_ts(entity["created_at"]) if not isinstance(entity["created_at"], str) else entity["created_at"]
    elif "created_at" in entity:
        out["created_at"] = format_ts(entity["created_at"]) if not isinstance(entity["created_at"], str) else entity["created_at"]
    if include_updated and "updated_at" in entity:
        out["updated_at"] = format_ts(entity["updated_at"]) if not isinstance(entity["updated_at"], str) else entity["updated_at"]
    if include_version and "version" in entity:
        out["version"] = entity["version"]
    return out


def shop_view(s):
    out = _base(s)
    for k in [
        "shop_name", "easa_accreditation_id",
        "labor_rate_small_cents", "labor_rate_medium_cents",
        "labor_rate_large_cents", "labor_rate_xlarge_cents",
        "rush_premium_pct", "replace_threshold_pct",
        "supplies_low_pct", "supplies_high_pct",
        "warranty_months", "pool_slot_monthly_cents",
        "pool_loan_daily_cents", "pool_loan_grace_days", "currency",
    ]:
        out[k] = s[k]
    return out


def customer_view(c):
    out = _base(c)
    out["shop_id"] = c["shop_id"]
    out["company_name"] = c["company_name"]
    out["account_credit_cents"] = c["account_credit_cents"]
    out["standing"] = c["standing"]
    return out


def motor_view(m):
    out = _base(m)
    for k in [
        "shop_id", "owner_customer_id", "serial_number", "rated_kw",
        "frame_mm", "voltage_v", "manufacture_year", "custody",
        "is_pool_spare", "supersedes_motor_id",
    ]:
        out[k] = m[k]
    return out


def work_order_view(w):
    out = _base(w)
    for k in [
        "shop_id", "customer_id", "motor_id", "priority", "no_charge",
        "status", "failure_diagnosis", "rewind_hours", "materials_cents",
        "replacement_cost_cents", "active_quote_id", "invoice_total_cents",
    ]:
        out[k] = w.get(k)
    out["delivered_at"] = format_ts(w["delivered_at"]) if w.get("delivered_at") else None
    out["closed_at"] = format_ts(w["closed_at"]) if w.get("closed_at") else None
    return out


def test_record_view(t):
    out = {"id": t["id"], "created_at": format_ts(t["created_at"]) if not isinstance(t["created_at"], str) else t["created_at"]}
    for k in [
        "work_order_id", "kind", "measured_watts", "vibration_mm_s",
        "insulation_megohms", "verdict", "recorded_by", "notes",
    ]:
        out[k] = t.get(k)
    return out


def quote_view(q):
    out = _base(q)
    for k in [
        "work_order_id", "variant", "rewind_labor_cents",
        "rewind_materials_cents", "shop_supplies_cents",
        "rush_premium_cents", "rewind_total_cents", "risk_pct",
        "risk_cost_cents", "tco_total_cents", "recommendation", "status",
    ]:
        out[k] = q.get(k)
    out["issued_at"] = format_ts(q["issued_at"]) if q.get("issued_at") else None
    out["expires_at"] = format_ts(q["expires_at"]) if q.get("expires_at") else None
    return out


def coil_data_view(c):
    out = {"id": c["id"], "created_at": format_ts(c["created_at"]) if not isinstance(c["created_at"], str) else c["created_at"]}
    for k in [
        "work_order_id", "wire_gauge_awg", "turns_per_coil",
        "coils_per_phase", "connection", "winding_resistance_ohms",
        "easa_form_version", "recorded_by",
    ]:
        out[k] = c.get(k)
    return out


def pool_contract_view(p):
    out = _base(p)
    for k in ["shop_id", "customer_id", "slot_count", "status", "first_month_fee_cents"]:
        out[k] = p.get(k)
    out["activated_on"] = format_ts(p["activated_on"]) if p.get("activated_on") else None
    return out


def pool_loan_view(l):
    out = _base(l)
    for k in [
        "contract_id", "work_order_id", "spare_motor_id",
        "overdue_days", "overdue_charge_cents", "status",
    ]:
        out[k] = l.get(k)
    out["checked_out_at"] = format_ts(l["checked_out_at"]) if l.get("checked_out_at") else None
    out["due_at"] = format_ts(l["due_at"]) if l.get("due_at") else None
    out["returned_at"] = format_ts(l["returned_at"]) if l.get("returned_at") else None
    return out


def invoice_view(i):
    out = _base(i)
    for k in [
        "work_order_id", "customer_id", "total_cents",
        "amount_paid_cents", "balance_due_cents", "status",
    ]:
        out[k] = i.get(k)
    out["issued_at"] = format_ts(i["issued_at"]) if i.get("issued_at") else None
    out["due_at"] = format_ts(i["due_at"]) if i.get("due_at") else None
    return out


def warranty_claim_view(c):
    out = _base(c)
    for k in [
        "work_order_id", "customer_id", "failure_mode", "months_elapsed",
        "remedy", "credit_cents", "status", "reviewed_by",
        "resolution_work_order_id",
    ]:
        out[k] = c.get(k)
    out["filed_at"] = format_ts(c["filed_at"]) if c.get("filed_at") else None
    return out
