"""Resource serializers: strip internal fields, format timestamps.

Payment, FlightLog and WeatherAdvisory are ledger-style records: they carry
only id and created_at (no updated_at / version), per PRD section 2.5.
"""

from util import fmt_ts


def _common(r):
    return {
        "id": r["id"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def owner_json(o):
    out = _common(o)
    out.update({
        "name": o["name"],
        "contact_email": o["contact_email"],
        "revenue_share_pct": o["revenue_share_pct"],
        "guarantee_cents_per_block_min": o["guarantee_cents_per_block_min"],
    })
    return out


def aircraft_json(a):
    out = _common(a)
    out.update({
        "owner_id": a["owner_id"],
        "tail_number": a["tail_number"],
        "category": a["category"],
        "home_base_icao": a["home_base_icao"],
        "seats": a["seats"],
        "hourly_rate_cents": a["hourly_rate_cents"],
        "on_ops_spec": a["on_ops_spec"],
        "initial_airframe_minutes": a["initial_airframe_minutes"],
        "total_airframe_minutes": a["total_airframe_minutes"],
        "next_check_due_minutes": a["next_check_due_minutes"],
        "status": a["status"],
    })
    return out


def crew_member_json(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "base_icao": c["base_icao"],
        "qualified_categories": list(c["qualified_categories"]),
        "status": c["status"],
    })
    return out


def trip_json(t):
    out = _common(t)
    out.update({
        "customer_name": t["customer_name"],
        "customer_email": t["customer_email"],
        "requested_category": t["requested_category"],
        "origin_icao": t["origin_icao"],
        "destination_icao": t["destination_icao"],
        "departure_at": fmt_ts(t["departure_at"]),
        "passenger_count": t["passenger_count"],
        "international": t["international"],
        "status": t["status"],
        "payment_posture": t["payment_posture"],
        "quoted_total_cents": t["quoted_total_cents"],
        "deposit_required_cents": t["deposit_required_cents"],
        "quote_valid_until": fmt_ts(t["quote_valid_until"]),
        "collected_cents": t["collected_cents"],
        "final_total_cents": t["final_total_cents"],
        "cancellation_reason": t["cancellation_reason"],
        "cancellation_fee_cents": t["cancellation_fee_cents"],
        "refund_cents": t["refund_cents"],
    })
    return out


def quote_leg_json(lg):
    out = _common(lg)
    out.update({
        "trip_request_id": lg["trip_request_id"],
        "seq_no": lg["seq_no"],
        "leg_type": lg["leg_type"],
        "origin_icao": lg["origin_icao"],
        "destination_icao": lg["destination_icao"],
        "block_minutes": lg["block_minutes"],
        "fuel_stop": lg["fuel_stop"],
    })
    return out


def aircraft_assignment_json(a):
    out = _common(a)
    out.update({
        "trip_request_id": a["trip_request_id"],
        "aircraft_id": a["aircraft_id"],
        "status": a["status"],
        "occupied_start_at": fmt_ts(a["occupied_start_at"]),
        "occupied_end_at": fmt_ts(a["occupied_end_at"]),
    })
    return out


def crew_assignment_json(c):
    out = _common(c)
    out.update({
        "trip_request_id": c["trip_request_id"],
        "crew_member_id": c["crew_member_id"],
        "duty_role": c["duty_role"],
        "status": c["status"],
        "planned_duty_minutes": c["planned_duty_minutes"],
        "duty_legal": c["duty_legal"],
        "rest_legal": c["rest_legal"],
        "vetted_at": fmt_ts(c["vetted_at"]),
    })
    return out


def maintenance_window_json(w):
    out = _common(w)
    out.update({
        "aircraft_id": w["aircraft_id"],
        "window_type": w["window_type"],
        "starts_at": fmt_ts(w["starts_at"]),
        "ends_at": fmt_ts(w["ends_at"]),
        "status": w["status"],
    })
    return out


def passenger_json(p):
    out = _common(p)
    out.update({
        "trip_request_id": p["trip_request_id"],
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "tsa_status": p["tsa_status"],
        "screened_at": fmt_ts(p["screened_at"]),
    })
    return out


def permit_json(p):
    out = _common(p)
    out.update({
        "trip_request_id": p["trip_request_id"],
        "country_code": p["country_code"],
        "permit_type": p["permit_type"],
        "required": p["required"],
        "status": p["status"],
        "decided_at": fmt_ts(p["decided_at"]),
    })
    return out


def payment_json(p):
    return {
        "id": p["id"],
        "created_at": fmt_ts(p["created_at"]),
        "trip_request_id": p["trip_request_id"],
        "payment_type": p["payment_type"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
    }


def flight_log_json(fl):
    return {
        "id": fl["id"],
        "created_at": fmt_ts(fl["created_at"]),
        "trip_request_id": fl["trip_request_id"],
        "quote_leg_id": fl["quote_leg_id"],
        "actual_block_minutes": fl["actual_block_minutes"],
        "departed_at": fmt_ts(fl["departed_at"]),
        "arrived_at": fmt_ts(fl["arrived_at"]),
        "recorded_by_crew_id": fl["recorded_by_crew_id"],
    }


def statement_json(s):
    out = _common(s)
    out.update({
        "owner_id": s["owner_id"],
        "trip_request_id": s["trip_request_id"],
        "gross_cents": s["gross_cents"],
        "standard_share_cents": s["standard_share_cents"],
        "guarantee_floor_cents": s["guarantee_floor_cents"],
        "owner_share_cents": s["owner_share_cents"],
        "operator_retained_cents": s["operator_retained_cents"],
        "status": s["status"],
        "issued_at": fmt_ts(s["issued_at"]),
    })
    return out


def finding_json(f):
    out = _common(f)
    out.update({
        "subject_type": f["subject_type"],
        "subject_id": f["subject_id"],
        "finding_code": f["finding_code"],
        "grounding": f["grounding"],
        "notes": f["notes"],
        "status": f["status"],
        "resolved_at": fmt_ts(f["resolved_at"]),
    })
    return out


def advisory_json(w):
    return {
        "id": w["id"],
        "created_at": fmt_ts(w["created_at"]),
        "station_icao": w["station_icao"],
        "severity": w["severity"],
        "starts_at": fmt_ts(w["starts_at"]),
        "ends_at": fmt_ts(w["ends_at"]),
    }
