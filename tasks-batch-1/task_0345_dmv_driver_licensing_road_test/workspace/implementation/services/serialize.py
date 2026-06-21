"""Serialization of entities to their public JSON representation.

DriverRecord computed dimensions (point_balance, prior_suspension_count,
knowledge_test_passed) reflect the current clock and posted history at read
time (PRD 3.1). licensing_status, cdl_status, real_id_status,
real_id_categories_met are persisted/system fields.
"""
from services import calculations as calc


def driver_record(record, store):
    return {
        "id": record["id"],
        "full_name": record["full_name"],
        "date_of_birth": record["date_of_birth"],
        "state_code": record["state_code"],
        "licensing_status": record["licensing_status"],
        "cdl_status": record["cdl_status"],
        "point_balance": calc.point_balance(record, store),
        "prior_suspension_count": calc.prior_suspension_count(record, store),
        "knowledge_test_passed": calc.knowledge_test_passed(record, store),
        "real_id_status": record["real_id_status"],
        "real_id_categories_met": record["real_id_categories_met"],
        "organ_donor": record["organ_donor"],
        "voter_registration_opt_in": record["voter_registration_opt_in"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def examiner(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "certified_classes": e["certified_classes"],
        "opaque_user_id": e["opaque_user_id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def knowledge_test(t):
    return {
        "id": t["id"],
        "driver_record_id": t["driver_record_id"],
        "scheduled_period": t["scheduled_period"],
        "total_questions": t["total_questions"],
        "correct_answers": t.get("correct_answers"),
        "score_pct": t.get("score_pct"),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def road_test_appointment(a):
    return {
        "id": a["id"],
        "driver_record_id": a["driver_record_id"],
        "examiner_id": a["examiner_id"],
        "license_class": a["license_class"],
        "slot_start_period": a["slot_start_period"],
        "slot_end_period": a["slot_end_period"],
        "maneuver_scores": a.get("maneuver_scores"),
        "provisional_score": a.get("provisional_score"),
        "final_score": a.get("final_score"),
        "outcome": a.get("outcome"),
        "scored_by_examiner_id": a.get("scored_by_examiner_id"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def license_obj(l):
    return {
        "id": l["id"],
        "driver_record_id": l["driver_record_id"],
        "road_test_appointment_id": l.get("road_test_appointment_id"),
        "license_class": l["license_class"],
        "is_real_id": l["is_real_id"],
        "issued_period": l["issued_period"],
        "expiry_period": l["expiry_period"],
        "fee_cents": l["fee_cents"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def violation(v):
    return {
        "id": v["id"],
        "driver_record_id": v["driver_record_id"],
        "code": v["code"],
        "points": v["points"],
        "occurred_period": v["occurred_period"],
        "recorded_by_officer": v["recorded_by_officer"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def suspension(s):
    return {
        "id": s["id"],
        "driver_record_id": s["driver_record_id"],
        "triggering_violation_id": s.get("triggering_violation_id"),
        "point_balance_at_start": s["point_balance_at_start"],
        "start_period": s["start_period"],
        "duration_days": s["duration_days"],
        "eligible_period": s["eligible_period"],
        "point_balance_at_reinstatement": s.get("point_balance_at_reinstatement"),
        "reinstatement_fee": s.get("reinstatement_fee"),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def cdl_endorsement(c):
    return {
        "id": c["id"],
        "driver_record_id": c["driver_record_id"],
        "endorsement_code": c["endorsement_code"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def medical_card(m):
    return {
        "id": m["id"],
        "driver_record_id": m["driver_record_id"],
        "issued_period": m["issued_period"],
        "valid_through_period": m["valid_through_period"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def fee_payment(f):
    return {
        "id": f["id"],
        "driver_record_id": f["driver_record_id"],
        "purpose": f["purpose"],
        "amount_cents": f["amount_cents"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }
