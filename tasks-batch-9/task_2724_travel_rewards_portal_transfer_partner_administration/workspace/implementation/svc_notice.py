"""Making a change notice effective and re-pointing the book (PRD 3.10)."""

from core import DB, add_days, clock_iso, fmt_dt, ordered, parse_dt, touch


def make_effective(notice):
    """Flip an ANNOUNCED notice to EFFECTIVE and re-point every ACTIVE account."""
    notice["status"] = "EFFECTIVE"
    touch(notice)
    effective_at = parse_dt(notice["effective_at"])
    cohort_before = parse_dt(notice["cohort_enrolled_before"])
    expires_at = fmt_dt(add_days(effective_at, notice["grandfather_window_days"]))
    for account in ordered("accounts"):
        if account["status"] != "ACTIVE":
            continue
        enrolled = parse_dt(account["enrolled_at"])
        if enrolled < cohort_before:
            account["pending_notice_id"] = notice["id"]
            account["grandfather_expires_at"] = expires_at
        else:
            account["terms_notice_id"] = notice["id"]
            account["pending_notice_id"] = None
            account["grandfather_expires_at"] = None
        touch(account)
    return notice


def promote_matured(now):
    """Second phase: a matured pending notice becomes the governing notice."""
    matured = 0
    for account in ordered("accounts"):
        pending = account.get("pending_notice_id")
        expires = account.get("grandfather_expires_at")
        if not pending or not expires:
            continue
        if parse_dt(expires) <= now:
            account["terms_notice_id"] = pending
            account["pending_notice_id"] = None
            touch(account)
            matured += 1
    return matured
