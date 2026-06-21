from util import iso_now


def _ts(dt):
    return iso_now(dt) if dt is not None else None


def consumer_view(c):
    return {
        "id": c["id"],
        "email": c["email"],
        "full_name": c["full_name"],
        "ssn_last4": c["ssn_last4"],
        "status": c["status"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def furnisher_view(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "furnisher_type": f["furnisher_type"],
        "status": f["status"],
        "open_reverification_count": f["open_reverification_count"],
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }


def credit_file_view(cf):
    return {
        "id": cf["id"],
        "consumer_id": cf["consumer_id"],
        "bureau_code": cf["bureau_code"],
        "protection_state": cf["protection_state"],
        "open_dispute_count": cf["open_dispute_count"],
        "tradeline_count": cf["tradeline_count"],
        "created_at": _ts(cf["created_at"]),
        "updated_at": _ts(cf["updated_at"]),
        "version": cf["version"],
    }


def tradeline_view(t):
    return {
        "id": t["id"],
        "credit_file_id": t["credit_file_id"],
        "furnisher_id": t["furnisher_id"],
        "account_type": t["account_type"],
        "balance_cents": t["balance_cents"],
        "date_of_first_delinquency": _ts(t["date_of_first_delinquency"]),
        "reported_delinquency_date": _ts(t["reported_delinquency_date"]),
        "status": t["status"],
        "reage_violation": t["reage_violation"],
        "purge_due_at": _ts(t["purge_due_at"]),
        "created_at": _ts(t["created_at"]),
        "updated_at": _ts(t["updated_at"]),
        "version": t["version"],
    }


def dispute_view(d):
    return {
        "id": d["id"],
        "credit_file_id": d["credit_file_id"],
        "tradeline_id": d["tradeline_id"],
        "consumer_id": d["consumer_id"],
        "dispute_reason": d["dispute_reason"],
        "clock_mode": d["clock_mode"],
        "filed_at": _ts(d["filed_at"]),
        "deadline_at": _ts(d["deadline_at"]),
        "priority_score": d["priority_score"],
        "reopen_count": d["reopen_count"],
        "status": d["status"],
        "outcome_reason": d["outcome_reason"],
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def reverification_view(r):
    return {
        "id": r["id"],
        "dispute_id": r["dispute_id"],
        "furnisher_id": r["furnisher_id"],
        "response_type": r["response_type"],
        "corrected_balance_cents": r["corrected_balance_cents"],
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def freeze_view(f):
    return {
        "id": f["id"],
        "credit_file_id": f["credit_file_id"],
        "freeze_type": f["freeze_type"],
        "effective_at": _ts(f["effective_at"]),
        "expires_at": _ts(f["expires_at"]),
        "status": f["status"],
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }


def complaint_view(c):
    return {
        "id": c["id"],
        "dispute_id": c["dispute_id"],
        "consumer_id": c["consumer_id"],
        "agency": c["agency"],
        "narrative": c["narrative"],
        "status": c["status"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def notification_view(n):
    return {
        "id": n["id"],
        "credit_file_id": n["credit_file_id"],
        "subject_type": n["subject_type"],
        "subject_id": n["subject_id"],
        "event_code": n["event_code"],
        "dispatched_at": _ts(n["dispatched_at"]),
        "created_at": _ts(n["created_at"]),
    }


def reage_event_view(e):
    return {
        "id": e["id"],
        "tradeline_id": e["tradeline_id"],
        "prior_delinquency_date": _ts(e["prior_delinquency_date"]),
        "new_delinquency_date": _ts(e["new_delinquency_date"]),
        "was_violation": e["was_violation"],
        "source_dispute_id": e["source_dispute_id"],
        "created_at": _ts(e["created_at"]),
    }
