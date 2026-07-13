"""Entity -> JSON-safe dict serializers (computed fields resolved here)."""
import calc
import services
from store import db
from util import parse_iso


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity["updated_at"],
        "version": entity["version"],
    }


def registrant(r):
    out = {
        "legal_name": r["legal_name"],
        "party_type": r["party_type"],
        "email": r["email"],
        "contact_phone": r["contact_phone"],
        "mailing_address": r["mailing_address"],
        "license_number": r.get("license_number"),
    }
    out.update(_common(r))
    return out


def property_(p):
    out = {
        "registrant_id": p["registrant_id"],
        "parcel_id": p["parcel_id"],
        "street_address": p["street_address"],
        "occupancy_status": p["occupancy_status"],
        "registration_type": p["registration_type"],
        "registration_status": p["registration_status"],
        "foreclosure_status": p["foreclosure_status"],
        "registration_fee_cents": p["registration_fee_cents"],
        "registered_at": p["registered_at"],
        "registration_expires_at": p["registration_expires_at"],
        "outstanding_balance_cents": services.outstanding_balance(p["id"]),
        "lien_balance_cents": services.lien_balance(p["id"]),
        "open_violation_count": services.open_violation_count(p["id"]),
    }
    out.update(_common(p))
    return out


def maintenance_standard(s):
    return {
        "id": s["id"],
        "code": s["code"],
        "category": s["category"],
        "description": s["description"],
        "severity_weight": s["severity_weight"],
        "cure_period_days": s["cure_period_days"],
        "base_fine_cents": s["base_fine_cents"],
        "created_at": s["created_at"],
    }


def inspection(i):
    out = {
        "property_id": i["property_id"],
        "inspector_badge": i["inspector_badge"],
        "scheduled_start": i["scheduled_start"],
        "scheduled_end": i["scheduled_end"],
        "status": i["status"],
        "result": i.get("result"),
        "failed_standard_codes": i.get("failed_standard_codes", []),
        "performed_at": i.get("performed_at"),
    }
    out.update(_common(i))
    return out


def violation(v):
    out = {
        "property_id": v["property_id"],
        "inspection_id": v["inspection_id"],
        "standard_code": v["standard_code"],
        "severity_weight": v["severity_weight"],
        "status": v["status"],
        "cited_at": v["cited_at"],
        "cure_deadline_at": v["cure_deadline_at"],
        "cured_at": v.get("cured_at"),
    }
    out.update(_common(v))
    return out


def fine(f):
    accrued = calc.fine_accrual(
        f["base_amount_cents"], f["daily_penalty_cents"],
        parse_iso(f["assessed_at"]), db.clock,
    )
    out = {
        "violation_id": f["violation_id"],
        "property_id": f["property_id"],
        "base_amount_cents": f["base_amount_cents"],
        "assessed_at": f["assessed_at"],
        "daily_penalty_cents": f["daily_penalty_cents"],
        "accrued_amount_cents": accrued,
        "finalized_amount_cents": f.get("finalized_amount_cents"),
        "status": f["status"],
        "dispute_reason": f.get("dispute_reason"),
        "disputed_at": f.get("disputed_at"),
        "paid_at": f.get("paid_at"),
    }
    out.update(_common(f))
    return out


def lien(l):
    payoff_amount, payoff_quoted = calc.lien_payoff(
        l["principal_cents"], l["interest_rate_bps"],
        parse_iso(l["recorded_at"]), db.clock,
    )
    out = {
        "property_id": l["property_id"],
        "source_fine_id": l["source_fine_id"],
        "principal_cents": l["principal_cents"],
        "interest_rate_bps": l["interest_rate_bps"],
        "recorded_at": l["recorded_at"],
        "payoff_amount_cents": payoff_amount,
        "payoff_quoted_cents": payoff_quoted,
        "status": l["status"],
        "satisfied_at": l.get("satisfied_at"),
    }
    out.update(_common(l))
    return out


def abatement_order(a):
    out = {
        "property_id": a["property_id"],
        "ordered_at": a["ordered_at"],
        "scheduled_start": a["scheduled_start"],
        "scheduled_end": a["scheduled_end"],
        "estimated_cost_cents": a["estimated_cost_cents"],
        "actual_cost_cents": a.get("actual_cost_cents"),
        "admin_fee_cents": a.get("admin_fee_cents"),
        "recovered_amount_cents": a.get("recovered_amount_cents"),
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def receivership_referral(r):
    out = {
        "property_id": r["property_id"],
        "referred_at": r["referred_at"],
        "ground": r["ground"],
        "receiver_name": r["receiver_name"],
        "status": r["status"],
        "decided_at": r.get("decided_at"),
    }
    out.update(_common(r))
    return out


def demolition_listing(d):
    out = {
        "property_id": d["property_id"],
        "listed_at": d["listed_at"],
        "priority_score": d["priority_score"],
        "status": d["status"],
        "demolition_date": d.get("demolition_date"),
    }
    out.update(_common(d))
    return out


def ledger_entry(e):
    return {
        "id": e["id"],
        "property_id": e["property_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "source_type": e["source_type"],
        "source_id": e["source_id"],
        "occurred_at": e["occurred_at"],
        "memo": e["memo"],
        "created_at": e["created_at"],
    }
