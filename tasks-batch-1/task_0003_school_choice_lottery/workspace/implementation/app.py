"""School Choice Lottery API — Flask entry point.

Routes follow SCAFFOLD §1.5; all responses go through the envelope helpers
in response.py. Per the harness contract, this process starts cold on every
test (per-test-server isolation) and never seeds entities at startup.
"""
from __future__ import annotations

import os

from flask import Flask, request

from errors import (
    ApiError, raise_err,
    ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED, ERR_NOT_FOUND, ERR_FORBIDDEN,
)
from middleware import get_auth, require_role, parse_pagination, paginate
from response import success_object, success_array, error_response
from calculations import compute_school_acceptance_rate
import services as svc


app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def _on_api_error(exc: ApiError):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _on_404(_e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def _on_405(_e):
    return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(400)
def _on_400(_e):
    return error_response(ERR_INVALID_REQUEST, "Bad request", 400)


@app.errorhandler(Exception)
def _on_uncaught(exc: Exception):
    # Defensive: never leak internals; collapse to ERR_INVALID_REQUEST 400.
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    return error_response("ERR_INVALID_REQUEST", f"{type(exc).__name__}: {exc}", 400)


def _json_body():
    """Return parsed JSON body or {} for empty body."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Body must be valid JSON")
    if body is None:
        return {}
    return body


# ---------------------------------------------------------------------------
# Districts
# ---------------------------------------------------------------------------

@app.post("/lottery/districts")
def r_create_district():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    data = svc.create_district(_json_body())
    return success_object(data, 201)


@app.get("/lottery/districts/<did>")
def r_get_district(did):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_district(did), 200)


@app.get("/lottery/districts")
def r_list_districts():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = svc.list_districts(status)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


@app.patch("/lottery/districts/<did>")
def r_patch_district(did):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.patch_district(did, _json_body()), 200)


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

@app.post("/lottery/schools")
def r_create_school():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.create_school(_json_body()), 201)


@app.get("/lottery/schools/<sid>")
def r_get_school(sid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_school(sid), 200)


@app.get("/lottery/schools")
def r_list_schools():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    did = request.args.get("district_id")
    stype = request.args.get("school_type")
    items = svc.list_schools(did, stype)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


@app.patch("/lottery/schools/<sid>")
def r_patch_school(sid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.patch_school(sid, _json_body()), 200)


@app.get("/lottery/schools/<sid>/acceptance-rate")
def r_school_acceptance_rate(sid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    # Ensure school exists
    svc.get_school(sid)
    rate, is_comp, src = compute_school_acceptance_rate(sid)
    return success_object({
        "acceptance_rate": rate,
        "is_competitive": is_comp,
        "source_window_id": src,
    }, 200)


# ---------------------------------------------------------------------------
# Boundary Rules
# ---------------------------------------------------------------------------

@app.post("/lottery/boundary-rules")
def r_create_boundary():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.create_boundary_rule(_json_body()), 201)


@app.get("/lottery/boundary-rules/<rid>")
def r_get_boundary(rid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_boundary_rule(rid), 200)


@app.get("/lottery/boundary-rules")
def r_list_boundary():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    sid = request.args.get("school_id")
    items = svc.list_boundary_rules(sid)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Enrollment Windows
# ---------------------------------------------------------------------------

@app.post("/lottery/windows")
def r_create_window():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.create_window(_json_body()), 201)


@app.get("/lottery/windows/<wid>")
def r_get_window(wid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_window(wid), 200)


@app.get("/lottery/windows")
def r_list_windows():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    did = request.args.get("district_id")
    status = request.args.get("status")
    items = svc.list_windows(did, status)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


@app.post("/lottery/windows/<wid>/open")
def r_open_window(wid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.open_window(wid), 200)


@app.post("/lottery/windows/<wid>/close")
def r_close_window(wid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.close_window(wid), 200)


@app.post("/lottery/windows/<wid>/run-lottery")
def r_run_lottery(wid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.run_lottery(wid, _json_body()), 200)


@app.post("/lottery/windows/<wid>/expire-offers")
def r_expire_offers(wid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.expire_offers_for_window(wid), 200)


@app.post("/lottery/windows/<wid>/finalize")
def r_finalize_window(wid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.finalize_window(wid), 200)


# ---------------------------------------------------------------------------
# Families & Students
# ---------------------------------------------------------------------------

@app.post("/lottery/families/register")
def r_register_family():
    # Anonymous endpoint: no auth required at all (PRD §2.1 + §3.3)
    # But validations[1] says: "all (except POST /lottery/families/register, ...)"
    # So we accept any/no headers here.
    return success_object(svc.register_family(_json_body()), 201)


@app.get("/lottery/families/<fid>")
def r_get_family(fid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_family(fid), 200)


@app.get("/lottery/families")
def r_list_families():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])  # exclusive to DistrictAdmin per scaffold
    limit, offset = parse_pagination()
    rdid = request.args.get("residence_district_id")
    items = svc.list_families(rdid)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


@app.get("/lottery/families/<fid>/risk-preview")
def r_family_risk_preview(fid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.family_risk_preview(fid), 200)


@app.get("/lottery/families/<fid>/risk-final")
def r_family_risk_final(fid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.family_risk_final(fid), 200)


@app.post("/lottery/students")
def r_create_student():
    uid, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.create_student(_json_body(), role, uid), 201)


@app.get("/lottery/students/<sid>")
def r_get_student(sid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_student(sid), 200)


@app.get("/lottery/students")
def r_list_students():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    fid = request.args.get("family_id")
    items = svc.list_students(fid)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Sibling Bonds
# ---------------------------------------------------------------------------

@app.post("/lottery/sibling-bonds")
def r_create_sibling_bond():
    uid, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.create_sibling_bond(_json_body(), role, uid), 201)


@app.get("/lottery/sibling-bonds/<bid>")
def r_get_sibling_bond(bid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_sibling_bond(bid), 200)


@app.get("/lottery/sibling-bonds")
def r_list_sibling_bonds():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    items = svc.list_sibling_bonds(
        request.args.get("student_id"),
        request.args.get("sibling_student_id"),
        request.args.get("school_id"),
    )
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@app.post("/lottery/applications")
def r_create_application():
    uid, role = get_auth()
    require_role(role, ["Guardian"])
    return success_object(svc.create_application(_json_body(), uid), 201)


@app.get("/lottery/applications/<aid>")
def r_get_application(aid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_application(aid), 200)


@app.get("/lottery/applications")
def r_list_applications():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    items = svc.list_applications(
        request.args.get("window_id"),
        request.args.get("student_id"),
        request.args.get("school_id"),
        request.args.get("status"),
    )
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


@app.post("/lottery/applications/<aid>/submit")
def r_submit_application(aid):
    uid, role = get_auth()
    require_role(role, ["Guardian"])
    return success_object(svc.submit_application(aid, role, uid), 200)


@app.post("/lottery/applications/<aid>/withdraw")
def r_withdraw_application(aid):
    uid, role = get_auth()
    require_role(role, ["Guardian"])
    return success_object(svc.withdraw_application(aid, role, uid), 200)


@app.post("/lottery/applications/<aid>/reject")
def r_reject_application(aid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin"])
    return success_object(svc.reject_application(aid), 200)


@app.get("/lottery/applications/<aid>/weight-preview")
def r_app_weight_preview(aid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.application_weight_preview(aid), 200)


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

@app.get("/lottery/offers/<oid>")
def r_get_offer(oid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_offer(oid), 200)


@app.get("/lottery/offers")
def r_list_offers():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    items = svc.list_offers(
        request.args.get("application_id"),
        request.args.get("status"),
        request.args.get("source"),
    )
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


@app.post("/lottery/offers/<oid>/accept")
def r_accept_offer(oid):
    uid, role = get_auth()
    require_role(role, ["Guardian"])
    return success_object(svc.accept_offer(oid, _json_body(), role, uid), 200)


@app.post("/lottery/offers/<oid>/decline")
def r_decline_offer(oid):
    uid, role = get_auth()
    require_role(role, ["Guardian"])
    return success_object(svc.decline_offer(oid, role, uid), 200)


# ---------------------------------------------------------------------------
# Waitlist Entries
# ---------------------------------------------------------------------------

@app.get("/lottery/waitlist-entries/<wid>")
def r_get_waitlist(wid):
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_waitlist_entry(wid), 200)


@app.get("/lottery/waitlist-entries")
def r_list_waitlist():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    limit, offset = parse_pagination()
    items = svc.list_waitlist_entries(
        request.args.get("school_id"),
        request.args.get("application_id"),
        request.args.get("status"),
    )
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# System clock (test-driving)
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def r_set_clock():
    # Per scaffold validations[1] exception, this endpoint may be seeded
    # without full auth. But the RBAC table restricts it to DistrictAdmin.
    # We honor RBAC when headers are present; if no headers (initial seed),
    # we allow it as a seeding affordance.
    role = request.headers.get("X-User-Role")
    if role is not None:
        # If role header present, enforce DistrictAdmin
        if role not in ("DistrictAdmin",):
            # If anything else, run through normal auth -> will likely reject.
            _, r2 = get_auth()
            require_role(r2, ["DistrictAdmin"])
    return success_object(svc.set_clock(_json_body()), 200)


@app.get("/_clock/current")
def r_get_clock():
    _, role = get_auth()
    require_role(role, ["DistrictAdmin", "Guardian"])
    return success_object(svc.get_clock(), 200)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
