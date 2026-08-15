"""Entity serializers and shared helpers."""
from db import store, _parse_iso


def touch(resource):
    from db import now_iso
    resource["updated_at"] = now_iso()
    resource["version"] += 1


def serialize_cycle(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "application_opens_at": c["application_opens_at"],
        "application_deadline_at": c["application_deadline_at"],
        "deposit_deadline_at": c["deposit_deadline_at"],
        "census_at": c["census_at"],
        "target_class_size": c["target_class_size"],
        "status": c["status"],
        "inquiry_count": c["inquiry_count"],
        "application_count": c["application_count"],
        "admitted_count": c["admitted_count"],
        "deposited_count": c["deposited_count"],
        "enrolled_count": c["enrolled_count"],
        "decisioned_count": c["decisioned_count"],
        "admit_rate": c["admit_rate"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_program(p):
    return {
        "id": p["id"],
        "cycle_id": p["cycle_id"],
        "name": p["name"],
        "capacity_seats": p["capacity_seats"],
        "target_enrollment": p["target_enrollment"],
        "tuition_cents": p["tuition_cents"],
        "scholarship_budget_cents": p["scholarship_budget_cents"],
        "deposit_amount_cents": p["deposit_amount_cents"],
        "auto_waitlist_activation": p["auto_waitlist_activation"],
        "admitted_count": p["admitted_count"],
        "deposited_count": p["deposited_count"],
        "enrolled_count": p["enrolled_count"],
        "seats_open": p["seats_open"],
        "scholarship_committed_cents": p["scholarship_committed_cents"],
        "scholarship_available_cents": p["scholarship_available_cents"],
        "intake_posture": p["intake_posture"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_applicant(a):
    return {
        "id": a["id"],
        "cycle_id": a["cycle_id"],
        "full_name": a["full_name"],
        "email": a["email"],
        "applicant_type": a["applicant_type"],
        "inquiry_source": a["inquiry_source"],
        "distance_band": a["distance_band"],
        "transfer_credit_hours": a.get("transfer_credit_hours"),
        "prior_standing": a.get("prior_standing"),
        "funnel_stage": a["funnel_stage"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_application(a):
    return {
        "id": a["id"],
        "applicant_id": a["applicant_id"],
        "program_id": a["program_id"],
        "cycle_id": a["cycle_id"],
        "academic_score": a["academic_score"],
        "efc_cents": a["efc_cents"],
        "submitted_at": a["submitted_at"],
        "review_round": a["review_round"],
        "submitted_read_count": a["submitted_read_count"],
        "aid_accepted_cents": a["aid_accepted_cents"],
        "aid_gap_cents": a["aid_gap_cents"],
        "melt_risk_score": a["melt_risk_score"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_review(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "reader_id": r["reader_id"],
        "window_start_at": r["window_start_at"],
        "window_end_at": r["window_end_at"],
        "score_academic": r.get("score_academic"),
        "score_fit": r.get("score_fit"),
        "recommendation": r.get("recommendation"),
        "submitted_at": r.get("submitted_at"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_aid_offer(o):
    return {
        "id": o["id"],
        "application_id": o["application_id"],
        "fund_type": o["fund_type"],
        "amount_cents": o["amount_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_deposit(d):
    return {
        "id": d["id"],
        "application_id": d["application_id"],
        "amount_cents": d["amount_cents"],
        "paid_at": d["paid_at"],
        "refund_amount_cents": d.get("refund_amount_cents"),
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_waitlist_entry(e):
    return {
        "id": e["id"],
        "application_id": e["application_id"],
        "program_id": e["program_id"],
        "rank_score": e["rank_score"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_intervention(i):
    return {
        "id": i["id"],
        "application_id": i["application_id"],
        "advisor_id": i["advisor_id"],
        "intervention_type": i["intervention_type"],
        "window_start_at": i["window_start_at"],
        "window_end_at": i["window_end_at"],
        "trigger_source": i["trigger_source"],
        "outcome": i.get("outcome"),
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }
