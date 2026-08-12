"""Auto-renew, reinstatement, and system (clock/scheduler) routes."""
from datetime import timedelta
from flask import Blueprint, request

import db
import errors
import middleware
from response import success
from services import lifecycle, pricing, scheduler

bp = Blueprint("lifecycle_ops", __name__)


def _body():
    return request.get_json(silent=True) or {}


def _get_member(mid):
    m = db.members.get(mid)
    if not m:
        raise errors.not_found()
    return m


# --- Auto-renew ---
@bp.post("/api/members/<mid>/auto-renew/enroll")
def auto_renew_enroll(mid):
    middleware.require_owner_or_roles(mid)
    m = _get_member(mid)
    cat = db.membership_categories.get(m["category_id"])
    if not cat or not cat["allows_auto_renew"]:
        raise errors.ApiError(errors.ERR_AUTO_RENEW_NOT_ALLOWED,
                              "Category does not permit auto-renew enrollment", 422)
    b = _body()
    a = lifecycle.new_entity({
        "member_id": mid,
        "payment_method_token": b.get("payment_method_token"),
        "authorized_at": db.iso(db.now_utc()),
        "revoked_at": None,
        "status": "ACTIVE",
    })
    db.auto_renew_authorizations[a["id"]] = a
    return success(lifecycle.auto_renew_out(a), status=201)


@bp.post("/api/members/<mid>/auto-renew/revoke")
def auto_renew_revoke(mid):
    middleware.require_owner_or_roles(mid)
    m = _get_member(mid)
    b = _body()
    expected = b.get("expected_member_version")
    if expected is not None and int(expected) != m["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION,
                              "expected_member_version does not match current Member.version", 412)
    auth = None
    for a in db.auto_renew_authorizations.values():
        if a["member_id"] == mid and a["status"] == "ACTIVE":
            auth = a
            break
    if auth is None:
        raise errors.invalid_state("No ACTIVE auto-renew authorization")
    auth["status"] = "REVOKED"
    auth["revoked_at"] = db.iso(db.now_utc())
    db.touch(auth)
    db.touch(m)
    return success(lifecycle.auto_renew_out(auth))


@bp.post("/api/members/<mid>/auto-renew/reactivate")
def auto_renew_reactivate(mid):
    middleware.require_owner_or_roles(mid)
    m = _get_member(mid)
    auth = None
    for a in db.auto_renew_authorizations.values():
        if a["member_id"] == mid and a["status"] == "SUSPENDED_HARD_DECLINE":
            auth = a
            break
    if auth is None:
        raise errors.ApiError(errors.ERR_NO_AUTO_RENEW_ACTIVE,
                              "Authorization is not SUSPENDED_HARD_DECLINE", 409)
    b = _body()
    auth["payment_method_token"] = b.get("payment_method_token")
    auth["status"] = "ACTIVE"
    db.touch(auth)
    return success(lifecycle.auto_renew_out(auth))


@bp.get("/api/members/<mid>/auto-renew")
def get_auto_renew(mid):
    middleware.require_owner_or_roles(mid, "MembershipAdministrator")
    _get_member(mid)
    rows = [a for a in db.auto_renew_authorizations.values() if a["member_id"] == mid]
    rows.sort(key=lambda a: a["created_at"])
    return success([lifecycle.auto_renew_out(a) for a in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


# --- Reinstatement ---
@bp.post("/api/members/<mid>/reinstatement-requests")
def file_reinstatement(mid):
    middleware.require_owner_or_roles(mid)
    m = _get_member(mid)
    if m["status"] != "LAPSED":
        raise errors.invalid_state("Member is not LAPSED")
    for r in db.reinstatement_requests.values():
        if r["member_id"] == mid and r["status"] == "PENDING":
            raise errors.ApiError(errors.ERR_REINSTATEMENT_HAS_PENDING,
                                  "Second PENDING reinstatement request", 409)
    cat = db.membership_categories.get(m["category_id"])
    lapse_ts = db.member_lapse_ts.get(mid, db.now_utc())
    if db.now_utc() > lapse_ts + timedelta(days=int(cat["reinstatement_window_days"])):
        raise errors.ApiError(errors.ERR_REINSTATEMENT_WINDOW_EXPIRED,
                              "Reinstatement window expired", 422)

    total, last_sched = pricing.compute_back_dues(m, lapse_ts, db.now_utc())
    inv = lifecycle.create_invoice(m, None, total, last_sched, db.now_utc())
    r = lifecycle.new_entity({
        "member_id": mid,
        "requested_at": db.iso(db.now_utc()),
        "back_dues_invoice_id": inv["id"],
        "decided_at": None,
        "status": "PENDING",
    })
    db.reinstatement_requests[r["id"]] = r
    return success(lifecycle.reinstatement_out(r), status=201)


@bp.get("/api/members/<mid>/reinstatement-requests")
def list_reinstatements(mid):
    middleware.require_owner_or_roles(mid, "MembershipAdministrator")
    _get_member(mid)
    rows = [r for r in db.reinstatement_requests.values() if r["member_id"] == mid]
    rows.sort(key=lambda r: r["created_at"])
    return success([lifecycle.reinstatement_out(r) for r in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


@bp.post("/api/members/<mid>/reinstatement-requests/<rid>/approve")
def approve_reinstatement(mid, rid):
    middleware.require_roles("MembershipAdministrator")
    m = _get_member(mid)
    r = db.reinstatement_requests.get(rid)
    if not r or r["member_id"] != mid:
        raise errors.not_found()
    if r["status"] != "PENDING":
        raise errors.invalid_state("ReinstatementRequest is not PENDING")
    if m["status"] != "LAPSED":
        raise errors.invalid_state("Member is not LAPSED")
    cat = db.membership_categories.get(m["category_id"])
    lapse_ts = db.member_lapse_ts.get(mid, db.now_utc())
    if db.now_utc() > lapse_ts + timedelta(days=int(cat["reinstatement_window_days"])):
        raise errors.ApiError(errors.ERR_REINSTATEMENT_WINDOW_EXPIRED,
                              "Reinstatement window expired", 422)
    inv = db.dues_invoices.get(r["back_dues_invoice_id"])
    if not inv or inv["payment_status"] != "SETTLED":
        raise errors.invalid_state("Back-dues invoice not SETTLED")

    r["status"] = "APPROVED"
    r["decided_at"] = db.iso(db.now_utc())
    db.touch(r)

    # new term + move member to ACTIVE (via REINSTATED transient in same commit)
    amount, ps, pe, sched = pricing.compute_invoice_amount(m, db.now_utc())
    term = lifecycle.create_term(m, ps, pe, "REINSTATEMENT")
    m["status"] = "ACTIVE"
    m["current_period_start"] = term["period_start"]
    m["current_period_end"] = term["period_end"]
    lifecycle.restore_benefits(m)
    for l in db.directory_listings.values():
        if l["member_id"] == mid:
            lifecycle.recompute_listing_visibility(l, m)
    lifecycle.recompute_risk_score(m)
    db.touch(m)
    return success(lifecycle.reinstatement_out(r))


@bp.post("/api/members/<mid>/reinstatement-requests/<rid>/reject")
def reject_reinstatement(mid, rid):
    middleware.require_roles("MembershipAdministrator")
    _get_member(mid)
    r = db.reinstatement_requests.get(rid)
    if not r or r["member_id"] != mid:
        raise errors.not_found()
    if r["status"] != "PENDING":
        raise errors.invalid_state("ReinstatementRequest is not PENDING")
    r["status"] = "REJECTED"
    r["decided_at"] = db.iso(db.now_utc())
    db.touch(r)
    return success(lifecycle.reinstatement_out(r))


# --- System / scheduler ---
@bp.post("/api/_clock/set_current_utc")
def set_clock():
    middleware.require_roles("DuesAdministrator")
    b = _body()
    to_dt = db.parse_dt(b.get("to_iso8601"))
    db.set_clock(to_dt)
    scheduler.run_sweep()
    return success({}, status=200)


@bp.post("/api/_scheduler/run_renewal_cycle")
def run_renewal_cycle():
    middleware.require_roles("DuesAdministrator")
    scheduler.run_sweep()
    return success({}, status=200)
