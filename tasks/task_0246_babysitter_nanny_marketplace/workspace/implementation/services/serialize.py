"""Serializers: internal record -> API output dict (field names per scaffold §1.1).

Datetimes are stored internally as ISO strings under <name>_iso keys and
surfaced under their public <name> key.
"""


def family_out(f):
    return {
        "id": f["id"],
        "display_name": f["display_name"],
        "email": f["email"],
        "num_children": f["num_children"],
        "required_tier": f["required_tier"],
        "wallet_balance_cents": f["wallet_balance_cents"],
        "escrow_reserved_cents": f["escrow_reserved_cents"],
        "escrow_available_cents": f["escrow_available_cents"],
        "tax_withheld_ytd_cents": f["tax_withheld_ytd_cents"],
        "cash_wages_ytd_cents": f["cash_wages_ytd_cents"],
        "is_w2_obligated": f["is_w2_obligated"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def caregiver_out(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "hourly_rate_floor_cents": c["hourly_rate_floor_cents"],
        "background_check_tier": c["background_check_tier"],
        "verification_status": c["verification_status"],
        "availability_status": c["availability_status"],
        "pending_earnings_cents": c["pending_earnings_cents"],
        "lifetime_paid_cents": c["lifetime_paid_cents"],
        "rating_avg": c["rating_avg"],
        "rating_count": c["rating_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def background_check_out(b):
    return {
        "id": b["id"],
        "caregiver_id": b["caregiver_id"],
        "requested_tier": b["requested_tier"],
        "status": b["status"],
        "adjudication_note": b["adjudication_note"],
        "cleared_at": b["cleared_at_iso"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def job_posting_out(j):
    return {
        "id": j["id"],
        "family_id": j["family_id"],
        "title": j["title"],
        "care_type": j["care_type"],
        "family_pay_rate_cents": j["family_pay_rate_cents"],
        "required_tier": j["required_tier"],
        "status": j["status"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def interview_out(i):
    return {
        "id": i["id"],
        "job_posting_id": i["job_posting_id"],
        "family_id": i["family_id"],
        "caregiver_id": i["caregiver_id"],
        "scheduled_start": i["scheduled_start_iso"],
        "scheduled_end": i["scheduled_end_iso"],
        "kind": i["kind"],
        "status": i["status"],
        "outcome_note": i["outcome_note"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def booking_out(b):
    return {
        "id": b["id"],
        "family_id": b["family_id"],
        "caregiver_id": b["caregiver_id"],
        "job_posting_id": b["job_posting_id"],
        "care_type": b["care_type"],
        "agreed_rate_cents": b["agreed_rate_cents"],
        "scheduled_start": b["scheduled_start_iso"],
        "scheduled_end": b["scheduled_end_iso"],
        "recurrence_count": b["recurrence_count"],
        "is_holiday": b["is_holiday"],
        "status": b["status"],
        "offer_round": b["offer_round"],
        "is_last_minute": b["is_last_minute"],
        "estimated_pay_cents": b["estimated_pay_cents"],
        "final_pay_cents": b["final_pay_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def session_out(s):
    return {
        "id": s["id"],
        "booking_id": s["booking_id"],
        "caregiver_id": s["caregiver_id"],
        "sequence_index": s["sequence_index"],
        "window_start": s["window_start_iso"],
        "window_end": s["window_end_iso"],
        "status": s["status"],
        "clock_in_at": s["clock_in_at_iso"],
        "clock_out_at": s["clock_out_at_iso"],
        "actual_hours": s["actual_hours"],
        "gross_pay_cents": s["gross_pay_cents"],
        "is_holiday": s["is_holiday"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def backup_request_out(r):
    return {
        "id": r["id"],
        "family_id": r["family_id"],
        "matched_caregiver_id": r["matched_caregiver_id"],
        "needed_start": r["needed_start_iso"],
        "needed_end": r["needed_end_iso"],
        "required_tier": r["required_tier"],
        "max_rate_cents": r["max_rate_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def payout_out(p):
    return {
        "id": p["id"],
        "caregiver_id": p["caregiver_id"],
        "family_id": p["family_id"],
        "session_ids": list(p["session_ids"]),
        "gross_pay_cents": p["gross_pay_cents"],
        "fica_withheld_cents": p["fica_withheld_cents"],
        "platform_fee_cents": p["platform_fee_cents"],
        "net_pay_cents": p["net_pay_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def review_out(r):
    return {
        "id": r["id"],
        "booking_id": r["booking_id"],
        "family_id": r["family_id"],
        "caregiver_id": r["caregiver_id"],
        "rating_value": r["rating_value"],
        "comment": r["comment"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def tax_statement_out(t):
    return {
        "id": t["id"],
        "family_id": t["family_id"],
        "caregiver_id": t["caregiver_id"],
        "tax_year": t["tax_year"],
        "cash_wages_cents": t["cash_wages_cents"],
        "fica_withheld_cents": t["fica_withheld_cents"],
        "created_at": t["created_at"],
    }
