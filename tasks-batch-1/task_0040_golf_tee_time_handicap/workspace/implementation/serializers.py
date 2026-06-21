def course_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "course_rating": c["course_rating"],
        "slope_rating": c["slope_rating"],
        "peak_fee_cents": c["peak_fee_cents"],
        "offpeak_fee_cents": c["offpeak_fee_cents"],
        "peak_start_hour": c["peak_start_hour"],
        "peak_end_hour": c["peak_end_hour"],
        "member_discount_pct": c["member_discount_pct"],
    }


def golfer_out(g):
    return {
        "id": g["id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
        "full_name": g["full_name"],
        "membership_tier": g["membership_tier"],
        "handicap_index": g["handicap_index"],
        "provisional_handicap_index": g["provisional_handicap_index"],
        "handicap_revision": g["handicap_revision"],
        "low_handicap_index": g["low_handicap_index"],
    }


def score_out(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "golfer_id": s["golfer_id"],
        "course_id": s["course_id"],
        "played_on": s["played_on"],
        "adjusted_gross_score": s["adjusted_gross_score"],
        "score_differential": s["score_differential"],
        "status": s["status"],
        "counted_in_revision": s["counted_in_revision"],
    }


def tee_time_out(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "course_id": t["course_id"],
        "start_utc": t["start_utc"],
        "local_hour": t["local_hour"],
        "group_type": t["group_type"],
        "capacity": t["capacity"],
        "confirmed_count": t["confirmed_count"],
        "status": t["status"],
    }


def booking_out(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "tee_time_id": b["tee_time_id"],
        "golfer_id": b["golfer_id"],
        "status": b["status"],
        "pricing_tier": b["pricing_tier"],
        "green_fee_cents": b["green_fee_cents"],
        "standby_rank": b["standby_rank"],
    }


def revision_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "revision_number": r["revision_number"],
        "effective_utc": r["effective_utc"],
        "golfer_count": r["golfer_count"],
    }
