"""Existence resolution (ERR_NOT_FOUND, priority 3) and list helpers."""

import errors
from db import store
from errors import err


def get_family(fid):
    f = store.families.get(fid)
    if f is None:
        raise err(errors.ERR_NOT_FOUND, "Family not found")
    return f


def get_caregiver(cid):
    c = store.caregivers.get(cid)
    if c is None:
        raise err(errors.ERR_NOT_FOUND, "Caregiver not found")
    return c


def get_background_check(bid):
    b = store.background_checks.get(bid)
    if b is None:
        raise err(errors.ERR_NOT_FOUND, "BackgroundCheck not found")
    return b


def get_job_posting(jid):
    j = store.job_postings.get(jid)
    if j is None:
        raise err(errors.ERR_NOT_FOUND, "JobPosting not found")
    return j


def get_interview(iid):
    i = store.interviews.get(iid)
    if i is None:
        raise err(errors.ERR_NOT_FOUND, "Interview not found")
    return i


def get_booking(bid):
    b = store.bookings.get(bid)
    if b is None:
        raise err(errors.ERR_NOT_FOUND, "Booking not found")
    return b


def get_session(sid):
    s = store.sessions.get(sid)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "BookingSession not found")
    return s


def get_backup_request(rid):
    r = store.backup_requests.get(rid)
    if r is None:
        raise err(errors.ERR_NOT_FOUND, "BackupCareRequest not found")
    return r


def get_payout(pid):
    p = store.payouts.get(pid)
    if p is None:
        raise err(errors.ERR_NOT_FOUND, "Payout not found")
    return p


def get_review(rid):
    r = store.reviews.get(rid)
    if r is None:
        raise err(errors.ERR_NOT_FOUND, "Review not found")
    return r


def get_tax_statement(tid):
    t = store.tax_statements.get(tid)
    if t is None:
        raise err(errors.ERR_NOT_FOUND, "TaxStatement not found")
    return t


def sorted_by_created(records):
    """Default list ordering: created_at ASC, then id ASC for stability."""
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))
