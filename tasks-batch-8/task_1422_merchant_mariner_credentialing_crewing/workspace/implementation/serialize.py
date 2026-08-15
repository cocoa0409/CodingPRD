"""Entity serializers: internal records -> public JSON dicts (PRD 2.4)."""

from db import fmt_dt_sec as fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_mariner(m):
    out = _common(m)
    out.update(
        {
            "full_name": m["full_name"],
            "mariner_reference_number": m["mariner_reference_number"],
            "home_port_code": m["home_port_code"],
            "hire_channel": m["hire_channel"],
            "rank_track": m["rank_track"],
            "rank_grade": m["rank_grade"],
            "primary_endorsement_code": m["primary_endorsement_code"],
            "annual_training_cap_cents": m["annual_training_cap_cents"],
            "status": m["status"],
            "readiness_posture": m["readiness_posture"],
            "readiness_reasons": list(m["readiness_reasons"]),
            "drug_test_current_until": fmt_dt(m["drug_test_current_until"]),
            "no_show_strike_count": m["no_show_strike_count"],
            "training_privileges": m["training_privileges"],
        }
    )
    return out


def ser_vessel(v):
    out = _common(v)
    out.update(
        {
            "vessel_name": v["vessel_name"],
            "imo_number": v["imo_number"],
            "vessel_class": v["vessel_class"],
            "flag_state": v["flag_state"],
            "status": v["status"],
            "compliance_posture": v["compliance_posture"],
            "slots_total": v["slots_total"],
            "slots_covered": v["slots_covered"],
        }
    )
    return out


def ser_manning_slot(s):
    out = _common(s)
    out.update(
        {
            "vessel_id": s["vessel_id"],
            "position_code": s["position_code"],
            "rank_track": s["rank_track"],
            "min_rank_grade": s["min_rank_grade"],
            "required_endorsement_code": s["required_endorsement_code"],
            "is_critical_position": s["is_critical_position"],
            "standard_tour_days": s["standard_tour_days"],
            "status": s["status"],
            "current_coverage": s["current_coverage"],
        }
    )
    return out


def ser_rotation_plan(p):
    out = _common(p)
    out.update(
        {
            "vessel_id": p["vessel_id"],
            "effective_from": fmt_dt(p["effective_from"]),
            "effective_to": fmt_dt(p["effective_to"]),
            "standard_tour_days": p["standard_tour_days"],
            "max_handover_overlap_days": p["max_handover_overlap_days"],
            "status": p["status"],
        }
    )
    return out


def ser_credential(c):
    out = _common(c)
    out.update(
        {
            "mariner_id": c["mariner_id"],
            "credential_type": c["credential_type"],
            "endorsement_code": c["endorsement_code"],
            "prerequisite_credential_id": c["prerequisite_credential_id"],
            "issue_date": fmt_dt(c["issue_date"]),
            "expiry_date": fmt_dt(c["expiry_date"]),
            "status": c["status"],
            "renewal_count": c["renewal_count"],
        }
    )
    return out


def ser_sea_service_record(r):
    out = _common(r)
    out.update(
        {
            "mariner_id": r["mariner_id"],
            "vessel_id": r["vessel_id"],
            "position_code": r["position_code"],
            "rank_track": r["rank_track"],
            "rank_grade": r["rank_grade"],
            "service_region": r["service_region"],
            "watch_schedule": r["watch_schedule"],
            "start_date": fmt_dt(r["start_date"]),
            "end_date": fmt_dt(r["end_date"]),
            "provisional_days": r["provisional_days"],
            "verified_days": r["verified_days"],
            "record_status": r["record_status"],
            "entered_by_user_id": r["entered_by_user_id"],
            "verified_by_user_id": r["verified_by_user_id"],
            "dispute_reason": r["dispute_reason"],
        }
    )
    return out


def ser_medical_certificate(c):
    out = _common(c)
    out.update(
        {
            "mariner_id": c["mariner_id"],
            "cert_type": c["cert_type"],
            "issue_date": fmt_dt(c["issue_date"]),
            "expiry_date": fmt_dt(c["expiry_date"]),
            "limitations": list(c["limitations"]),
            "status": c["status"],
        }
    )
    return out


def ser_drug_test(t):
    out = _common(t)
    out.update(
        {
            "mariner_id": t["mariner_id"],
            "test_type": t["test_type"],
            "scheduled_date": fmt_dt(t["scheduled_date"]),
            "collected_date": fmt_dt(t["collected_date"]),
            "result": t["result"],
            "status": t["status"],
            "recorded_by_user_id": t["recorded_by_user_id"],
        }
    )
    return out


def ser_training_course(c):
    out = _common(c)
    out.update(
        {
            "course_code": c["course_code"],
            "title": c["title"],
            "provider": c["provider"],
            "grants_endorsement_code": c["grants_endorsement_code"],
            "start_date": fmt_dt(c["start_date"]),
            "end_date": fmt_dt(c["end_date"]),
            "seat_capacity": c["seat_capacity"],
            "seats_reserved": c["seats_reserved"],
            "seats_open": c["seat_capacity"] - c["seats_reserved"],
            "cost_cents": c["cost_cents"],
            "status": c["status"],
        }
    )
    return out


def ser_training_enrollment(e):
    out = _common(e)
    out.update(
        {
            "course_id": e["course_id"],
            "mariner_id": e["mariner_id"],
            "status": e["status"],
            "channel_snapshot": e["channel_snapshot"],
            "provisional_amount_cents": e["provisional_amount_cents"],
            "receipt_amount_cents": e["receipt_amount_cents"],
            "reimbursed_amount_cents": e["reimbursed_amount_cents"],
            "requested_by_user_id": e["requested_by_user_id"],
            "approved_by_user_id": e["approved_by_user_id"],
            "reimbursed_by_user_id": e["reimbursed_by_user_id"],
        }
    )
    return out


def ser_training_budget(b):
    out = _common(b)
    out.update(
        {
            "mariner_id": b["mariner_id"],
            "fiscal_year": b["fiscal_year"],
            "annual_cap_cents": b["annual_cap_cents"],
            "reserved_cents": b["reserved_cents"],
            "used_cents": b["used_cents"],
            "available_cents": b["annual_cap_cents"]
            - b["reserved_cents"]
            - b["used_cents"],
        }
    )
    return out


def ser_union_hall(h):
    out = _common(h)
    out.update(
        {
            "local_number": h["local_number"],
            "name": h["name"],
            "region": h["region"],
        }
    )
    return out


def ser_union_registration(r):
    out = _common(r)
    out.update(
        {
            "hall_id": r["hall_id"],
            "mariner_id": r["mariner_id"],
            "seniority_date": fmt_dt(r["seniority_date"]),
            "shipping_card_number": r["shipping_card_number"],
            "dues_current_until": fmt_dt(r["dues_current_until"]),
            "status": r["status"],
        }
    )
    return out


def ser_assignment(a):
    out = _common(a)
    out.update(
        {
            "mariner_id": a["mariner_id"],
            "manning_slot_id": a["manning_slot_id"],
            "vessel_id": a["vessel_id"],
            "union_registration_id": a["union_registration_id"],
            "assignment_channel": a["assignment_channel"],
            "relief_of_assignment_id": a["relief_of_assignment_id"],
            "sign_on_date": fmt_dt(a["sign_on_date"]),
            "planned_relief_date": fmt_dt(a["planned_relief_date"]),
            "local_join": a["local_join"],
            "actual_sign_on_at": fmt_dt(a["actual_sign_on_at"]),
            "actual_relieved_at": fmt_dt(a["actual_relieved_at"]),
            "assignment_status": a["assignment_status"],
            "travel_status": a["travel_status"],
            "repatriation_status": a["repatriation_status"],
        }
    )
    return out


def _ser_leg(leg):
    return {
        "carrier": leg["carrier"],
        "from_port": leg["from_port"],
        "to_port": leg["to_port"],
        "depart_at": fmt_dt(leg["depart_at"]),
        "arrive_at": fmt_dt(leg["arrive_at"]),
        "base_fare_cents": leg["base_fare_cents"],
        "markup_bps": leg["markup_bps"],
    }


def ser_travel_booking(b):
    out = _common(b)
    out.update(
        {
            "assignment_id": b["assignment_id"],
            "direction": b["direction"],
            "legs": [_ser_leg(leg) for leg in b["legs"]],
            "payer": b["payer"],
            "total_fare_cents": b["total_fare_cents"],
            "cancellation_fee_cents": b["cancellation_fee_cents"],
            "status": b["status"],
        }
    )
    return out
