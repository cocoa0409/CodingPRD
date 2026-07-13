"""Entity -> JSON dict serializers (with computed fields and lazy expiry)."""
from store import store
from timeutil import fmt_iso
from calc import inspection_score, violation_penalty
from domain import (
    licenses_of_property, refresh_license, refresh_notice,
    checklist_items_of, property_compliance,
)


def _common(ent):
    return {
        "created_at": fmt_iso(ent["created_at"]),
        "updated_at": fmt_iso(ent["updated_at"]),
        "version": ent["version"],
    }


def landlord_dict(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "email": e["email"],
        "phone": e["phone"],
        "mailing_address": e["mailing_address"],
        **_common(e),
    }


def inspector_dict(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "badge_number": e["badge_number"],
        "email": e["email"],
        "certification_level": e["certification_level"],
        "active": e["active"],
        **_common(e),
    }


def property_dict(e):
    # Lazily expire any of this property's licenses.
    for lic in licenses_of_property(e["id"]):
        refresh_license(lic)
    comp = property_compliance(e)
    return {
        "id": e["id"],
        "landlord_id": e["landlord_id"],
        "street_address": e["street_address"],
        "unit_count": e["unit_count"],
        "year_built": e["year_built"],
        "registration_status": e["registration_status"],
        "current_license_id": e["current_license_id"],
        "has_lead_risk": comp["has_lead_risk"],
        "open_violation_count": comp["open_violation_count"],
        "open_critical_violation_count": comp["open_critical_violation_count"],
        "total_penalty_cents": comp["total_penalty_cents"],
        "total_fees_paid_cents": e["total_fees_paid_cents"],
        **_common(e),
    }


def license_dict(e):
    refresh_license(e)
    return {
        "id": e["id"],
        "property_id": e["property_id"],
        "license_number": e["license_number"],
        "term_years": e["term_years"],
        "status": e["status"],
        "fee_cents": e["fee_cents"],
        "lead_surcharge_applied": e["lead_surcharge_applied"],
        "issued_at": fmt_iso(e.get("issued_at")),
        "expires_at": fmt_iso(e.get("expires_at")),
        "renewal_count": e["renewal_count"],
        **_common(e),
    }


def complaint_dict(e):
    return {
        "id": e["id"],
        "property_id": e["property_id"],
        "tenant_email": e["tenant_email"],
        "tenant_unit": e["tenant_unit"],
        "category": e["category"],
        "description": e["description"],
        "severity_alleged": e["severity_alleged"],
        "status": e["status"],
        "filed_at": fmt_iso(e.get("filed_at")),
        **_common(e),
    }


def inspection_dict(e):
    if e["status"] in ("SCHEDULED", "IN_PROGRESS"):
        items = checklist_items_of(e["id"])
        score, _ = inspection_score(items, final=False)
    else:
        score = e.get("result_score")
    overdue = e["status"] == "SCHEDULED" and store.now() > e["scheduled_date"]
    return {
        "id": e["id"],
        "property_id": e["property_id"],
        "inspector_id": e["inspector_id"],
        "inspection_type": e["inspection_type"],
        "complaint_id": e.get("complaint_id"),
        "prior_inspection_id": e.get("prior_inspection_id"),
        "scheduled_date": fmt_iso(e.get("scheduled_date")),
        "duration_minutes": e["duration_minutes"],
        "status": e["status"],
        "conducted_at": fmt_iso(e.get("conducted_at")),
        "result_score": score,
        "overdue": overdue,
        **_common(e),
    }


def checklist_item_dict(e):
    return {
        "id": e["id"],
        "inspection_id": e["inspection_id"],
        "category": e["category"],
        "code": e["code"],
        "result": e["result"],
        "severity": e["severity"],
        "notes": e.get("notes"),
        "created_at": fmt_iso(e["created_at"]),
    }


def violation_dict(e):
    return {
        "id": e["id"],
        "inspection_id": e["inspection_id"],
        "property_id": e["property_id"],
        "checklist_item_id": e.get("checklist_item_id"),
        "code": e["code"],
        "category": e["category"],
        "severity": e["severity"],
        "status": e["status"],
        "cure_deadline": fmt_iso(e.get("cure_deadline")),
        "penalty_cents": violation_penalty(e, store.now()),
        "remediation_notes": e.get("remediation_notes"),
        **_common(e),
    }


def notice_dict(e):
    refresh_notice(e)
    return {
        "id": e["id"],
        "property_id": e["property_id"],
        "recipient_email": e.get("recipient_email"),
        "recipient_unit": e.get("recipient_unit"),
        "notice_type": e["notice_type"],
        "status": e["status"],
        "sent_at": fmt_iso(e.get("sent_at")),
        "ack_deadline": fmt_iso(e.get("ack_deadline")),
        "acknowledged_at": fmt_iso(e.get("acknowledged_at")),
        **_common(e),
    }


def condemnation_dict(e):
    return {
        "id": e["id"],
        "property_id": e["property_id"],
        "triggering_violation_id": e.get("triggering_violation_id"),
        "basis": e["basis"],
        "status": e["status"],
        "issued_at": fmt_iso(e.get("issued_at")),
        **_common(e),
    }
