"""Serializers: convert internal records into API output shape.

Internal records store datetimes as datetime objects and carry private keys like
`_seq`. Serializers render datetimes as ISO 8601 UTC (three fractional digits) and
strip private fields. Computed/live fields are filled by the route before calling.
"""

from clock import clock
from db import db, iso
from services import calc, domain
from services.constants import TIER_MULTIPLIER


def _base(record, with_version=True):
    out = {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
        "updated_at": iso(record["updated_at"]),
    }
    if with_version and "version" in record:
        out["version"] = record["version"]
    return out


def owner_out(o):
    """Owner with LIVE repeat_tier and prior_violation_count (PRD §3.5 live_tier)."""
    out = _base(o)
    tier, count, _ = calc.repeat_offender(o["id"], db, clock.now())
    out.update({
        "full_name": o["full_name"],
        "mailing_email": o["mailing_email"],
        "repeat_tier": tier,
        "prior_violation_count": count,
    })
    return out


def property_out(p):
    out = _base(p)
    out.update({
        "owner_id": p["owner_id"],
        "parcel_number": p["parcel_number"],
        "street_address": p["street_address"],
        "occupancy": p["occupancy"],
        "status": p["status"],
    })
    return out


def fee_schedule_out(fs):
    # FeeSchedule carries only id and created_at (PRD §2.4) — no updated_at/version.
    return {
        "id": fs["id"],
        "created_at": iso(fs["created_at"]),
        "violation_class": fs["violation_class"],
        "base_fine_cents": fs["base_fine_cents"],
        "daily_accrual_cents": fs["daily_accrual_cents"],
        "max_total_cents": fs["max_total_cents"],
        "cure_days": fs["cure_days"],
    }


def case_out(c):
    out = _base(c)
    out.update({
        "property_id": c["property_id"],
        "opened_by_user_id": c["opened_by_user_id"],
        "posture": c["posture"],
        "outstanding_balance_cents": c["outstanding_balance_cents"],
        "payments_applied_cents": c["payments_applied_cents"],
        "closed_at": iso(c["closed_at"]),
    })
    return out


def complaint_out(c):
    out = _base(c)
    out.update({
        "case_id": c["case_id"],
        "reporter_kind": c["reporter_kind"],
        "narrative": c["narrative"],
        "status": c["status"],
    })
    return out


def inspection_out(i):
    out = _base(i)
    out.update({
        "case_id": i["case_id"],
        "kind": i["kind"],
        "notice_id": i["notice_id"],
        "outcome": i["outcome"],
        "inspected_on": iso(i["inspected_on"]),
    })
    return out


def notice_out(n):
    out = _base(n)
    out.update({
        "case_id": n["case_id"],
        "owner_id": n["owner_id"],
        "source_inspection_id": n["source_inspection_id"],
        "violation_class": n["violation_class"],
        "escalation_multiplier": n["escalation_multiplier"],
        "effective_date": iso(n["effective_date"]),
        "compliance_deadline": iso(n["compliance_deadline"]),
        "status": n["status"],
        "fine_total_cents": n["fine_total_cents"],
        "days_overdue": n["days_overdue"],
    })
    return out


def reinspection_out(r):
    out = _base(r)
    out.update({
        "notice_id": r["notice_id"],
        "requested_by_user_id": r["requested_by_user_id"],
        "result": r["result"],
        "result_on": iso(r["result_on"]),
    })
    return out


def fine_out(f):
    out = _base(f)
    out.update({
        "notice_id": f["notice_id"],
        "source_kind": f["source_kind"],
        "assessed_cents": f["assessed_cents"],
        "settlement_status": f["settlement_status"],
    })
    return out


def hearing_out(h):
    out = _base(h)
    out.update({
        "notice_id": h["notice_id"],
        "requested_by_user_id": h["requested_by_user_id"],
        "scheduled_for": iso(h["scheduled_for"]),
        "status": h["status"],
        "continuance_count": h["continuance_count"],
    })
    return out


def abatement_out(a):
    out = _base(a)
    out.update({
        "case_id": a["case_id"],
        "action_kind": a["action_kind"],
        "estimated_cost_cents": a["estimated_cost_cents"],
        "actual_cost_cents": a["actual_cost_cents"],
        "status": a["status"],
    })
    return out


def lien_out(l):
    out = _base(l)
    out.update({
        "case_id": l["case_id"],
        "property_id": l["property_id"],
        "principal_cents": l["principal_cents"],
        "admin_fee_cents": l["admin_fee_cents"],
        "total_cents": l["total_cents"],
        "status": l["status"],
    })
    return out
