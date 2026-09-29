"""PRD 2.1 / 2.5 stage 3 — the owning-applicant resolvers for exactly the
fifteen ownership-guarded operations.

A resolver returns the owning applicant id, or None when the owner cannot be
determined (the addressed record or body reference does not exist), in which
case ownership cannot be violated and the request falls through to the
stage 6/7 not-found.
"""

from flask import request

from store import db


def _body_value(field):
    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return None
    value = payload.get(field)
    return value if isinstance(value, str) else None


# --- path-addressed -------------------------------------------------------

def applicant_path(kwargs):
    """GET /applicants/{id}, GET /applicants/{id}/trip-events,
    GET /applicants/{id}/suspension-proceedings,
    GET /applicants/{id}/visitor-eligibilities."""
    applicant_id = kwargs.get("applicant_id")
    if applicant_id in db.applicants:
        return applicant_id
    return None


def application_path(kwargs):
    """GET /applications/{id}, POST /applications/{id}/submit."""
    app_rec = db.applications.get(kwargs.get("application_id"))
    return None if app_rec is None else app_rec["applicant_id"]


def determination_path(kwargs):
    """GET /determinations/{id}, GET /determinations/{id}/trip-conditions,
    GET /determinations/{id}/appeals."""
    det = db.determinations.get(kwargs.get("determination_id"))
    return None if det is None else det["applicant_id"]


def proceeding_path(kwargs):
    """POST /suspension-proceedings/{id}/respond."""
    proc = db.proceedings.get(kwargs.get("proceeding_id"))
    return None if proc is None else proc["applicant_id"]


def referral_path(kwargs):
    """POST /travel-training-referrals/{id}/response."""
    ref = db.referrals.get(kwargs.get("referral_id"))
    return None if ref is None else ref["applicant_id"]


# --- body-addressed -------------------------------------------------------

def applicant_body(kwargs):
    """POST /applications — the packet's own applicant_id."""
    applicant_id = _body_value("applicant_id")
    if applicant_id is not None and applicant_id in db.applicants:
        return applicant_id
    return None


def determination_body(kwargs):
    """POST /appeals — the applicant of the determination being contested."""
    det = db.determinations.get(_body_value("determination_id"))
    return None if det is None else det["applicant_id"]


# --- query-filter scoped listings ----------------------------------------

def query_applicant_filter(kwargs):
    """GET /applications and GET /determinations.  An explicit applicant_id
    filter naming another rider is a 403; without the filter the listing is
    implicitly scoped to the acting rider."""
    return request.args.get("applicant_id")
