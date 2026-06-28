"""Entity factory functions — single source of creation for each entity type.

Used by both the public route handlers and the seed fast-forwards so creation
logic is identical. Every created entity is inserted into its db store.
"""
import db
from services import calculations


def _common(entity):
    """Attach created_at/updated_at/version (full trio) plus _seq ordering key."""
    ts = db.now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def create_homeowner(full_name, email, credit_band):
    hid = db.new_id()
    entity = {
        "id": hid,
        "full_name": full_name,
        "email": email,
        "credit_band": credit_band,
        "created_at": db.now_iso(),
        "_seq": db.homeowners.next_seq(),
    }
    db.homeowners.items[hid] = entity
    return entity


def create_job(homeowner_id, property_address, structure_type, footprint_sqft):
    jid = db.new_id()
    entity = _common({
        "id": jid,
        "homeowner_id": homeowner_id,
        "property_address": property_address,
        "structure_type": structure_type,
        "footprint_sqft": footprint_sqft,
        "lifecycle_status": "LEAD",
        "financing_status": "NONE",
        "accepted_quote_id": None,
        "install_order_id": None,
        "assessment_severity": "NONE",
        "open_claim_count": 0,
    })
    entity["_seq"] = db.jobs.next_seq()
    db.jobs.items[jid] = entity
    return entity


def create_inspection(job_id, moisture_pct, structural_findings_count, standing_water):
    iid = db.new_id()
    entity = _common({
        "id": iid,
        "job_id": job_id,
        "moisture_pct": moisture_pct,
        "structural_findings_count": structural_findings_count,
        "standing_water": standing_water,
        "status": "DRAFT",
        "severity": None,
    })
    entity["_seq"] = db.inspections.next_seq()
    db.inspections.items[iid] = entity
    return entity


def create_quote(job_id, footprint_sqft, scope, drain_linear_ft, discount_code, revision=1):
    qid = db.new_id()
    priced = calculations.price_scope(footprint_sqft, scope, drain_linear_ft, discount_code)
    entity = _common({
        "id": qid,
        "job_id": job_id,
        "revision": revision,
        "includes_vapor_barrier": scope["includes_vapor_barrier"],
        "includes_sump": scope["includes_sump"],
        "includes_dehumidifier": scope["includes_dehumidifier"],
        "includes_drain": scope["includes_drain"],
        "includes_battery_backup": scope["includes_battery_backup"],
        "drain_linear_ft": drain_linear_ft,
        "discount_code": discount_code,
        "subtotal_cents": priced["subtotal_cents"],
        "discount_cents": priced["discount_cents"],
        "tax_cents": priced["tax_cents"],
        "total_cents": priced["total_cents"],
        "status": "DRAFT",
        "expires_at": None,
    })
    entity["_seq"] = db.quotes.next_seq()
    db.quotes.items[qid] = entity
    return entity


def create_financing_application(job_id, quote_id, term_months, amount_financed_cents,
                                 apr_bps, monthly_payment_cents):
    fid = db.new_id()
    entity = _common({
        "id": fid,
        "job_id": job_id,
        "quote_id": quote_id,
        "term_months": term_months,
        "amount_financed_cents": amount_financed_cents,
        "apr_bps": apr_bps,
        "monthly_payment_cents": monthly_payment_cents,
        "status": "SUBMITTED",
    })
    entity["_seq"] = db.financing_applications.next_seq()
    db.financing_applications.items[fid] = entity
    return entity


def create_install_order(job_id, quote_id, scheduled_start, scheduled_end):
    oid = db.new_id()
    entity = _common({
        "id": oid,
        "job_id": job_id,
        "quote_id": quote_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "PLANNED",
        "actual_drain_linear_ft": 0,
        "final_total_cents": None,
        "variance_cents": None,
    })
    entity["_seq"] = db.install_orders.next_seq()
    db.install_orders.items[oid] = entity
    return entity


def create_crew(name, home_region, daily_capacity, active):
    cid = db.new_id()
    entity = _common({
        "id": cid,
        "name": name,
        "home_region": home_region,
        "daily_capacity": daily_capacity,
        "active": active,
    })
    entity["_seq"] = db.crews.next_seq()
    db.crews.items[cid] = entity
    return entity


def create_crew_booking(crew_id, install_order_id, window_start, window_end):
    bid = db.new_id()
    entity = _common({
        "id": bid,
        "crew_id": crew_id,
        "install_order_id": install_order_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "RESERVED",
    })
    entity["_seq"] = db.crew_bookings.next_seq()
    db.crew_bookings.items[bid] = entity
    return entity


def create_warranty(job_id, install_order_id, holder_homeowner_id, coverage_years, next_service_due):
    wid = db.new_id()
    entity = _common({
        "id": wid,
        "job_id": job_id,
        "install_order_id": install_order_id,
        "holder_homeowner_id": holder_homeowner_id,
        "coverage_years": coverage_years,
        "status": "ACTIVE",
        "transfer_count": 0,
        "next_service_due": next_service_due,
        "last_service_at": None,
    })
    entity["_seq"] = db.warranties.next_seq()
    db.warranties.items[wid] = entity
    return entity


def create_service_visit(warranty_id, visit_type, claim_id, scheduled_for):
    sid = db.new_id()
    entity = _common({
        "id": sid,
        "warranty_id": warranty_id,
        "visit_type": visit_type,
        "claim_id": claim_id,
        "scheduled_for": scheduled_for,
        "status": "SCHEDULED",
    })
    entity["_seq"] = db.service_visits.next_seq()
    db.service_visits.items[sid] = entity
    return entity


def create_claim(job_id, warranty_id, category, description):
    cid = db.new_id()
    entity = _common({
        "id": cid,
        "job_id": job_id,
        "warranty_id": warranty_id,
        "category": category,
        "description": description,
        "status": "OPEN",
        "reopen_count": 0,
    })
    entity["_seq"] = db.claims.next_seq()
    db.claims.items[cid] = entity
    return entity


def create_foundation_referral(job_id, inspection_id, partner_name):
    rid = db.new_id()
    entity = _common({
        "id": rid,
        "job_id": job_id,
        "inspection_id": inspection_id,
        "partner_name": partner_name,
        "status": "DRAFT",
    })
    entity["_seq"] = db.foundation_referrals.next_seq()
    db.foundation_referrals.items[rid] = entity
    return entity
