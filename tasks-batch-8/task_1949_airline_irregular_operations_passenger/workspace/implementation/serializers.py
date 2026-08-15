"""Row -> JSON serializers. Primary resources carry id/created_at/updated_at/version;
CostEntry and CommunicationLog are append-only ledger rows with id/created_at only."""

from db import iso


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def serialize_event(e):
    out = _common(e)
    out.update({
        "event_code": e["event_code"],
        "hub": e["hub"],
        "classification": e["classification"],
        "is_controllable": e["is_controllable"],
        "event_status": e["event_status"],
        "cost_cap_cents": e["cost_cap_cents"],
        "detected_at": iso(e["detected_at"]),
        "affected_booking_count": e["affected_booking_count"],
        "affected_passenger_count": e["affected_passenger_count"],
        "accrual_total_cents": e["accrual_total_cents"],
        "settled_total_cents": e["settled_total_cents"],
    })
    return out


def serialize_flight(f):
    out = _common(f)
    out.update({
        "flight_number": f["flight_number"],
        "origin": f["origin"],
        "destination": f["destination"],
        "sched_dep_utc": iso(f["sched_dep_utc"]),
        "sched_arr_utc": iso(f["sched_arr_utc"]),
        "orig_sched_dep_utc": iso(f["orig_sched_dep_utc"]),
        "orig_sched_arr_utc": iso(f["orig_sched_arr_utc"]),
        "act_dep_utc": iso(f["act_dep_utc"]) if f["act_dep_utc"] else None,
        "act_arr_utc": iso(f["act_arr_utc"]) if f["act_arr_utc"] else None,
        "distance_km": f["distance_km"],
        "operating_carrier": f["operating_carrier"],
        "flight_status": f["flight_status"],
        "disruption_event_id": f["disruption_event_id"],
        "cancelled_at": iso(f["cancelled_at"]) if f["cancelled_at"] else None,
        "crew_coverage_status": f["crew_coverage_status"],
    })
    return out


def serialize_cabin_inventory(ci):
    out = _common(ci)
    out.update({
        "flight_id": ci["flight_id"],
        "cabin": ci["cabin"],
        "capacity": ci["capacity"],
        "seats_sold": ci["seats_sold"],
        "interline_seats_committed": ci["interline_seats_committed"],
        "seats_available": ci["capacity"] - ci["seats_sold"] - ci["interline_seats_committed"],
    })
    return out


def serialize_passenger(p):
    out = _common(p)
    out.update({
        "full_name": p["full_name"],
        "loyalty_tier": p["loyalty_tier"],
        "special_service_codes": list(p["special_service_codes"]),
        "contact_email": p["contact_email"],
    })
    return out


def serialize_booking(b):
    out = _common(b)
    out.update({
        "passenger_id": b["passenger_id"],
        "fare_cents": b["fare_cents"],
        "cabin": b["cabin"],
        "party_size": b["party_size"],
        "booking_status": b["booking_status"],
        "compensation_status": b["compensation_status"],
        "eligible_at": iso(b["eligible_at"]) if b["eligible_at"] else None,
        "election_deadline": iso(b["election_deadline"]) if b["election_deadline"] else None,
        "refund_amount_cents": b["refund_amount_cents"],
        "credit_amount_cents": b["credit_amount_cents"],
        "compensation_amount_cents": b["compensation_amount_cents"],
        "compensation_basis": b["compensation_basis"],
    })
    return out


def serialize_segment(s):
    out = _common(s)
    out.update({
        "booking_id": s["booking_id"],
        "flight_id": s["flight_id"],
        "seq_no": s["seq_no"],
        "cabin": s["cabin"],
        "segment_status": s["segment_status"],
        "reaccommodation_case_id": s["reaccommodation_case_id"],
    })
    return out


def serialize_case(c):
    out = _common(c)
    out.update({
        "booking_id": c["booking_id"],
        "disruption_event_id": c["disruption_event_id"],
        "priority_score": c["priority_score"],
        "case_status": c["case_status"],
        "queued_at": iso(c["queued_at"]),
        "committed_option_id": c["committed_option_id"],
    })
    return out


def serialize_option(o):
    out = _common(o)
    out.update({
        "case_id": o["case_id"],
        "interline_agreement_id": o["interline_agreement_id"],
        "is_interline": o["is_interline"],
        "legs": [dict(leg) for leg in o["legs"]],
        "est_first_dep_utc": iso(o["est_first_dep_utc"]),
        "est_final_arr_utc": iso(o["est_final_arr_utc"]),
        "projected_arrival_delay_minutes": o["projected_arrival_delay_minutes"],
        "interline_fare_cents": o["interline_fare_cents"],
        "rank_score": o["rank_score"],
        "option_status": o["option_status"],
    })
    return out


def serialize_agreement(a):
    out = _common(a)
    out.update({
        "partner_carrier": a["partner_carrier"],
        "origin": a["origin"],
        "destination": a["destination"],
        "cabin_map": dict(a["cabin_map"]),
        "settlement_rate_pct": a["settlement_rate_pct"],
        "seats_quota_per_flight": a["seats_quota_per_flight"],
        "agreement_status": a["agreement_status"],
    })
    return out


def serialize_voucher(v):
    out = _common(v)
    out.update({
        "booking_id": v["booking_id"],
        "disruption_event_id": v["disruption_event_id"],
        "voucher_type": v["voucher_type"],
        "check_in_date": v["check_in_date"],
        "nights": v["nights"],
        "meals_count": v["meals_count"],
        "face_value_cents": v["face_value_cents"],
        "valid_through": v["valid_through"],
        "voucher_status": v["voucher_status"],
        "redeemed_amount_cents": v["redeemed_amount_cents"],
    })
    return out


def serialize_crew_assignment(a):
    out = _common(a)
    out.update({
        "flight_id": a["flight_id"],
        "crew_member_ref": a["crew_member_ref"],
        "crew_role": a["crew_role"],
        "duty_start_utc": iso(a["duty_start_utc"]),
        "duty_end_utc": iso(a["duty_end_utc"]),
        "legality_status": a["legality_status"],
        "assignment_status": a["assignment_status"],
    })
    return out


def serialize_election(e):
    out = _common(e)
    out.update({
        "booking_id": e["booking_id"],
        "election": e["election"],
        "election_source": e["election_source"],
        "refund_amount_cents": e["refund_amount_cents"],
        "credit_amount_cents": e["credit_amount_cents"],
        "compensation_amount_cents": e["compensation_amount_cents"],
        "election_status": e["election_status"],
    })
    return out


def serialize_cost_entry(ce):
    return {
        "id": ce["id"],
        "created_at": iso(ce["created_at"]),
        "disruption_event_id": ce["disruption_event_id"],
        "source_type": ce["source_type"],
        "source_id": ce["source_id"],
        "entry_kind": ce["entry_kind"],
        "amount_cents": ce["amount_cents"],
        "note": ce["note"],
    }


def serialize_communication_log(cl):
    return {
        "id": cl["id"],
        "created_at": iso(cl["created_at"]),
        "booking_id": cl["booking_id"],
        "disruption_event_id": cl["disruption_event_id"],
        "template": cl["template"],
        "channel": cl["channel"],
        "due_at": iso(cl["due_at"]),
        "sent_at": iso(cl["sent_at"]) if cl["sent_at"] else None,
        "log_status": cl["log_status"],
    }
