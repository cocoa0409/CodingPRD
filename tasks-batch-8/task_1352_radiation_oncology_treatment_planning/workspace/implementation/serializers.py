"""Entity -> JSON serializers (public field projection, computed fields)."""
from db import store
from services import calc


def patient_json(p):
    return {
        "id": p["id"], "mrn": p["mrn"], "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def course_json(c):
    return {
        "id": c["id"], "patient_id": c["patient_id"],
        "diagnosis_code": c["diagnosis_code"], "intent": c["intent"],
        "technique": c["technique"],
        "prescribed_total_dose_cGy": c["prescribed_total_dose_cGy"],
        "planned_fractions": c["planned_fractions"],
        "dose_per_fraction_cGy": c["dose_per_fraction_cGy"],
        "delivered_fractions": c["delivered_fractions"],
        "delivered_dose_cGy": c["delivered_dose_cGy"],
        "fractions_since_chart_review": c["fractions_since_chart_review"],
        "baseline_weight_kg": c["baseline_weight_kg"],
        "weekend_makeup_allowance": c["weekend_makeup_allowance"],
        "open_interruption_count": c["open_interruption_count"],
        "bed_nominal_gy": calc.bed_nominal(c),
        "bed_actual_gy": calc.bed_actual(c),
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def simulation_json(a):
    return {
        "id": a["id"], "course_id": a["course_id"], "machine_id": a["machine_id"],
        "purpose": a["purpose"], "start_time": a["start_time"],
        "end_time": a["end_time"],
        "immobilization_device": a["immobilization_device"],
        "patient_weight_kg": a["patient_weight_kg"], "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def contour_json(c):
    return {
        "id": c["id"], "course_id": c["course_id"], "set_label": c["set_label"],
        "target_volumes": c["target_volumes"], "oar_structures": c["oar_structures"],
        "created_by_user_id": c["created_by_user_id"],
        "reviewed_by_user_id": c["reviewed_by_user_id"], "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def plan_json(p):
    return {
        "id": p["id"], "course_id": p["course_id"],
        "contour_set_id": p["contour_set_id"],
        "supersedes_plan_id": p["supersedes_plan_id"],
        "plan_version": p["plan_version"],
        "target_total_dose_cGy": p["target_total_dose_cGy"],
        "planned_fractions": p["planned_fractions"],
        "dose_per_fraction_cGy": p["dose_per_fraction_cGy"],
        "planner_id": p["planner_id"],
        "pinned_contour_version": p["pinned_contour_version"],
        "primary_checker_id": p["primary_checker_id"],
        "secondary_checker_id": p["secondary_checker_id"],
        "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def constraint_json(dc):
    return {
        "id": dc["id"], "plan_id": dc["plan_id"],
        "structure_name": dc["structure_name"],
        "constraint_type": dc["constraint_type"],
        "limit_cGy": dc["limit_cGy"],
        "evaluated_value_cGy": dc["evaluated_value_cGy"],
        "satisfied": dc["satisfied"],
        "created_at": dc["created_at"], "updated_at": dc["updated_at"],
        "version": dc["version"],
    }


def check_json(chk):
    # PhysicsCheck carries only id + created_at (no updated_at / version).
    return {
        "id": chk["id"], "plan_id": chk["plan_id"], "check_type": chk["check_type"],
        "outcome": chk["outcome"], "checker_id": chk["checker_id"],
        "notes": chk["notes"], "created_at": chk["created_at"],
    }


def machine_json(m):
    return {
        "id": m["id"], "name": m["name"], "machine_type": m["machine_type"],
        "room": m["room"], "status": m["status"],
        "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"],
    }


def session_json(s):
    return {
        "id": s["id"], "course_id": s["course_id"], "plan_id": s["plan_id"],
        "machine_id": s["machine_id"], "fraction_number": s["fraction_number"],
        "start_time": s["start_time"], "end_time": s["end_time"],
        "igrt_planned": s["igrt_planned"],
        "is_first_fraction": s["is_first_fraction"],
        "is_weekend": s["is_weekend"],
        "dose_delivered_cGy": s["dose_delivered_cGy"],
        "cancellation_reason": s["cancellation_reason"],
        "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def interruption_json(i):
    return {
        "id": i["id"], "course_id": i["course_id"], "reason": i["reason"],
        "missed_count": i["missed_count"], "start_date": i["start_date"],
        "end_date": i["end_date"], "gap_days": i["gap_days"],
        "applied_strategy": i["applied_strategy"], "status": i["status"],
        "created_at": i["created_at"], "updated_at": i["updated_at"],
        "version": i["version"],
    }


def review_json(r):
    # ChartReview carries only id + created_at (no updated_at / version).
    return {
        "id": r["id"], "course_id": r["course_id"], "reviewer_id": r["reviewer_id"],
        "outcome": r["outcome"], "notes": r["notes"],
        "delivered_fractions_at_review": r["delivered_fractions_at_review"],
        "created_at": r["created_at"],
    }


def claim_json(c):
    course = store.courses.get(c["course_id"])
    return {
        "id": c["id"], "course_id": c["course_id"], "status": c["status"],
        "provisional_total_cents": calc.provisional_total(c, course) if course else 0,
        "gross_total_cents": c["gross_total_cents"],
        "discount_cents": c["discount_cents"],
        "final_total_cents": c["final_total_cents"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def line_json(l):
    # ChargeLine carries only id + created_at (no updated_at / version).
    return {
        "id": l["id"], "claim_id": l["claim_id"], "code": l["code"],
        "description": l["description"], "quantity": l["quantity"],
        "unit_charge_cents": l["unit_charge_cents"],
        "amount_cents": l["amount_cents"], "event_ref_id": l["event_ref_id"],
        "created_at": l["created_at"],
    }
