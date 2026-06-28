"""Entity construction + serialization helpers.

Common system fields (PRD §2.4): id, created_at, updated_at, version.
CatalogPart is the exception: only id + created_at (immutable, no version).
"""
import db


def _stamp_common(rec, store):
    ts = db.now_iso(store)
    rec["id"] = db.new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()


def touch(rec, store):
    """Mutation: refresh updated_at and bump version by one."""
    rec["updated_at"] = db.now_iso(store)
    rec["version"] = rec.get("version", 1) + 1


# ----- creation helpers -----

def make_customer(store, email, full_name, home_zone_code, fleet_account_id=None):
    rec = {
        "email": email,
        "full_name": full_name,
        "home_zone_code": home_zone_code,
        "fleet_account_id": fleet_account_id,
        "status": "ACTIVE",
    }
    _stamp_common(rec, store)
    return rec


def make_fleet_account(store, company_name, credit_limit_cents, labor_discount_pct):
    rec = {
        "company_name": company_name,
        "credit_limit_cents": credit_limit_cents,
        "labor_discount_pct": labor_discount_pct,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    }
    _stamp_common(rec, store)
    return rec


def make_mechanic(store, full_name, zone_code, skill_tier, labor_rate_cents_per_hour):
    rec = {
        "full_name": full_name,
        "zone_code": zone_code,
        "skill_tier": skill_tier,
        "labor_rate_cents_per_hour": labor_rate_cents_per_hour,
        "status": "AVAILABLE",
    }
    _stamp_common(rec, store)
    return rec


def make_catalog_part(store, sku, name, wholesale_cost_cents):
    # CatalogPart: only id + created_at; no updated_at, no version.
    rec = {
        "sku": sku,
        "name": name,
        "wholesale_cost_cents": wholesale_cost_cents,
        "id": db.new_id(),
        "created_at": db.now_iso(store),
        "_seq": store.next_seq(),
    }
    return rec


def make_service_request(store, customer_id, vehicle_vin, symptom_text, severity,
                         zone_code, fleet_account_id):
    rec = {
        "customer_id": customer_id,
        "vehicle_vin": vehicle_vin,
        "symptom_text": symptom_text,
        "zone_code": zone_code,
        "severity": severity,
        "fleet_account_id": fleet_account_id,
        "routing_mode": None,
        "estimate_total_cents": None,
        "final_total_cents": None,
        "status": "INTAKE",
    }
    _stamp_common(rec, store)
    return rec


def make_quote(store, service_request_id, diagnosis_text, estimated_labor_hours,
               estimated_parts_cents, tow_fee_cents, labor_rate_cents_per_hour,
               quoted_total_cents):
    rec = {
        "service_request_id": service_request_id,
        "diagnosis_text": diagnosis_text,
        "estimated_labor_hours": estimated_labor_hours,
        "estimated_parts_cents": estimated_parts_cents,
        "tow_fee_cents": tow_fee_cents,
        "labor_rate_cents_per_hour": labor_rate_cents_per_hour,
        "quoted_total_cents": quoted_total_cents,
        "status": "SENT",
    }
    _stamp_common(rec, store)
    return rec


def make_job_visit(store, service_request_id, mechanic_id, scheduled_start_utc,
                   scheduled_end_utc, routing_mode):
    rec = {
        "service_request_id": service_request_id,
        "mechanic_id": mechanic_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "routing_mode": routing_mode,
        "logged_labor_hours": None,
        "visit_status": "SCHEDULED",
        # private accumulator for add-on labour hours (not serialized)
        "_addon_labor_hours": 0,
    }
    _stamp_common(rec, store)
    return rec


def make_part_line(store, service_request_id, catalog_part_id, quantity,
                   unit_cost_cents, unit_price_cents, line_total_cents, is_addon):
    rec = {
        "service_request_id": service_request_id,
        "catalog_part_id": catalog_part_id,
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
        "unit_price_cents": unit_price_cents,
        "line_total_cents": line_total_cents,
        "is_addon": is_addon,
        "status": "SOURCED",
    }
    _stamp_common(rec, store)
    return rec


def make_inspection_finding(store, service_request_id, job_visit_id, description,
                            recommended_part_id, recommended_quantity, add_on_labor_hours):
    rec = {
        "service_request_id": service_request_id,
        "job_visit_id": job_visit_id,
        "description": description,
        "recommended_part_id": recommended_part_id,
        "recommended_quantity": recommended_quantity,
        "add_on_labor_hours": add_on_labor_hours,
        "status": "PROPOSED",
    }
    _stamp_common(rec, store)
    return rec


def make_payment(store, service_request_id, fleet_account_id, total_due_cents, method):
    rec = {
        "service_request_id": service_request_id,
        "fleet_account_id": fleet_account_id,
        "total_due_cents": total_due_cents,
        "method": method,
        "status": "INVOICED",
    }
    _stamp_common(rec, store)
    return rec


def make_warranty_claim(store, service_request_id, reason_text, filed_at_utc):
    rec = {
        "service_request_id": service_request_id,
        "reason_text": reason_text,
        "filed_at_utc": filed_at_utc,
        "callback_visit_id": None,
        "status": "UNDER_REVIEW",
    }
    _stamp_common(rec, store)
    return rec


# ----- serialization -----

_HIDDEN = {"_seq", "_addon_labor_hours"}


def serialize(rec):
    """Public representation: strip private/internal keys."""
    return {k: v for k, v in rec.items() if k not in _HIDDEN}
