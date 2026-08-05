"""Resource serialisers. Every timestamp goes through lclock.render()."""

import calc
import lclock

TS = lclock.render


def _common(record, out):
    out["id"] = record["id"]
    out["created_at"] = TS(record["created_at"])
    out["updated_at"] = TS(record["updated_at"])
    out["version"] = record["version"]
    return out


def zone(z):
    return _common(
        z,
        {
            "name": z["name"],
            "code": z["code"],
            "population_density_per_sqkm": z["population_density_per_sqkm"],
            "posture": z["posture"],
            "rodent_index": calc.num(z["rodent_index"]),
            "open_complaint_count": z["open_complaint_count"],
            "chronic_property_count": z["chronic_property_count"],
            "active_station_count": z["active_station_count"],
            "last_index_recomputed_at": TS(z["last_index_recomputed_at"]),
        },
    )


def owner(o):
    return _common(
        o,
        {
            "full_name": o["full_name"],
            "email": o["email"],
            "mailing_address": o["mailing_address"],
            "notice_preference": o["notice_preference"],
            "hardship_certified": o["hardship_certified"],
            "outstanding_balance_cents": o["outstanding_balance_cents"],
            "lifetime_paid_cents": o["lifetime_paid_cents"],
        },
    )


def prop(p):
    return _common(
        p,
        {
            "zone_id": p["zone_id"],
            "owner_id": p["owner_id"],
            "address_line": p["address_line"],
            "parcel_number": p["parcel_number"],
            "property_type": p["property_type"],
            "unit_count": p["unit_count"],
            "provisional_chronic_score": calc.num(p["provisional_chronic_score"]),
            "chronic_score": calc.num(p["chronic_score"]),
            "chronic_flag": p["chronic_flag"],
            "open_order_count": p["open_order_count"],
            "lien_encumbered": p["lien_encumbered"],
            "last_inspection_at": TS(p["last_inspection_at"]),
        },
    )


def officer(o):
    return _common(
        o,
        {
            "full_name": o["full_name"],
            "badge_number": o["badge_number"],
            "rank": o["rank"],
            "certification_expires_at": TS(o["certification_expires_at"]),
            "active_assignment_count": o["active_assignment_count"],
        },
    )


def complaint(c):
    return _common(
        c,
        {
            "property_id": c["property_id"],
            "zone_id": c["zone_id"],
            "complaint_type": c["complaint_type"],
            "reporter_type": c["reporter_type"],
            "reporter_name": c["reporter_name"],
            "reporter_phone": c["reporter_phone"],
            "description": c["description"],
            "reported_severity": c["reported_severity"],
            "severity": c["severity"],
            "status": c["status"],
            "priority_score": calc.num(c["priority_score"]),
            "response_due_at": TS(c["response_due_at"]),
            "closure_reason": c["closure_reason"],
            "triaged_at": TS(c["triaged_at"]),
            "closed_at": TS(c["closed_at"]),
        },
    )


def inspection(i):
    return _common(
        i,
        {
            "complaint_id": i["complaint_id"],
            "abatement_order_id": i["abatement_order_id"],
            "property_id": i["property_id"],
            "officer_id": i["officer_id"],
            "kind": i["kind"],
            "scheduled_start": TS(i["scheduled_start"]),
            "scheduled_end": TS(i["scheduled_end"]),
            "status": i["status"],
            "result": i["result"],
            "notes": i["notes"],
            "started_at": TS(i["started_at"]),
            "completed_at": TS(i["completed_at"]),
        },
    )


def assessment(a):
    return {
        "id": a["id"],
        "inspection_id": a["inspection_id"],
        "harborage_score": a["harborage_score"],
        "attractant_score": a["attractant_score"],
        "sanitation_score": a["sanitation_score"],
        "burrow_count": a["burrow_count"],
        "evidence_photo_count": a["evidence_photo_count"],
        "recommended_actions": list(a["recommended_actions"]),
        "infestation_index": calc.num(a["infestation_index"]),
        "infestation_tier": a["infestation_tier"],
        "created_at": TS(a["created_at"]),
    }


def order(o):
    hours = o["actual_labor_hours"]
    return _common(
        o,
        {
            "property_id": o["property_id"],
            "inspection_id": o["inspection_id"],
            "issued_by_officer_id": o["issued_by_officer_id"],
            "status": o["status"],
            "required_actions": list(o["required_actions"]),
            "infestation_tier_at_issue": o["infestation_tier_at_issue"],
            "escalation_level": o["escalation_level"],
            "compliance_deadline": TS(o["compliance_deadline"]),
            "served_at": TS(o["served_at"]),
            "extension_count": o["extension_count"],
            "extension_days_total": o["extension_days_total"],
            "education_advisory_served": o["education_advisory_served"],
            "actual_labor_hours": float(hours) if hours is not None else None,
            "actual_materials_cents": o["actual_materials_cents"],
            "abated_at": TS(o["abated_at"]),
            "closed_at": TS(o["closed_at"]),
        },
    )


def notice(n):
    return _common(
        n,
        {
            "abatement_order_id": n["abatement_order_id"],
            "notice_type": n["notice_type"],
            "delivery_method": n["delivery_method"],
            "recipient_address": n["recipient_address"],
            "status": n["status"],
            "service_outcome": n["service_outcome"],
            "sent_at": TS(n["sent_at"]),
            "served_at": TS(n["served_at"]),
        },
    )


def station(s):
    return _common(
        s,
        {
            "property_id": s["property_id"],
            "zone_id": s["zone_id"],
            "station_code": s["station_code"],
            "bait_type": s["bait_type"],
            "status": s["status"],
            "installed_at": TS(s["installed_at"]),
            "last_reading_at": TS(s["last_reading_at"]),
            "reading_count": s["reading_count"],
            "cumulative_take_pct": s["cumulative_take_pct"],
        },
    )


def reading(r):
    return {
        "id": r["id"],
        "bait_station_id": r["bait_station_id"],
        "reading_at": TS(r["reading_at"]),
        "take_pct": r["take_pct"],
        "activity_sign_count": r["activity_sign_count"],
        "station_condition": r["station_condition"],
        "rebaited": r["rebaited"],
        "created_at": TS(r["created_at"]),
    }


def invoice(v):
    return _common(
        v,
        {
            "abatement_order_id": v["abatement_order_id"],
            "property_id": v["property_id"],
            "owner_id": v["owner_id"],
            "prepared_by_user_id": v["prepared_by_user_id"],
            "approved_by_user_id": v["approved_by_user_id"],
            "billing_status": v["billing_status"],
            "lien_status": v["lien_status"],
            "estimated_total_cents": v["estimated_total_cents"],
            "final_total_cents": v["final_total_cents"],
            "labor_line_cents": v["labor_line_cents"],
            "materials_line_cents": v["materials_line_cents"],
            "penalty_line_cents": v["penalty_line_cents"],
            "education_credit_cents": v["education_credit_cents"],
            "admin_fee_cents": v["admin_fee_cents"],
            "hardship_discount_cents": v["hardship_discount_cents"],
            "amount_paid_cents": v["amount_paid_cents"],
            "balance_due_cents": v["balance_due_cents"],
            "due_at": TS(v["due_at"]),
            "paid_at": TS(v["paid_at"]),
            "lien_filed_at": TS(v["lien_filed_at"]),
            "voided_at": TS(v["voided_at"]),
            "void_reason": v["void_reason"],
        },
    )
