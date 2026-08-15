"""Package endpoints: purchase (tiered pricing), list, read, refund."""
from datetime import timedelta

from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope, get_body,
                        require_fields, get_entity, touch, new_common, package_pub,
                        session_pub, list_response)
from response import success_object
from services import billing

bp = Blueprint("packages", __name__)


@bp.post("/families/<fid>/packages")
def purchase_package(fid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    fam = get_entity("family", fid)
    body = get_body()
    require_fields(body, ["track", "credits_total"])
    mw.enum_check(body["track"], ["INDIVIDUAL", "GROUP"], "track")
    mw.int_check(body["credits_total"], "credits_total", minimum=1)
    if fam["status"] != "ACTIVE":
        E.raise_error(E.ERR_FAMILY_NOT_ACTIVE, "Family is not ACTIVE")

    unit_gross, price_paid, per_credit = billing.compute_package_pricing(
        fid, body["track"], body["credits_total"])
    p = new_common()
    p.update({
        "family_id": fid,
        "track": body["track"],
        "credits_total": body["credits_total"],
        "credits_consumed": 0,
        "credits_forfeited": 0,
        "reserved_count": 0,
        "price_paid_cents": price_paid,
        "unit_gross_cents": unit_gross,
        "per_credit_value_cents": per_credit,
        "purchased_at": db.now_iso(),
        "expires_at": db.iso(db.clock + timedelta(days=billing.PACKAGE_VALIDITY_DAYS)),
        "expires_at_dt": db.clock + timedelta(days=billing.PACKAGE_VALIDITY_DAYS),
        "refund_cents": None,
        "status": "ACTIVE",
    })
    db.packages[p["id"]] = p
    billing.charge_family(fam, price_paid)  # prepaid: no auto-suspend
    touch(fam)
    return success_object(package_pub(p), 201)


@bp.get("/families/<fid>/packages")
def list_packages(fid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    require_family_scope(auth, fid)
    get_entity("family", fid)
    rows = [p for p in db.packages.values() if p["family_id"] == fid]
    return list_response(rows, package_pub, paginate=False)


@bp.get("/packages/<pid>")
def get_package(pid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember", "Coach"])
    p = get_entity("package", pid)
    require_family_scope(auth, p["family_id"])
    return success_object(package_pub(p), 200)


@bp.post("/packages/<pid>/refund")
def refund_package(pid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    p = get_entity("package", pid)
    fam = db.families[p["family_id"]]
    if p["status"] not in ("ACTIVE", "EXPIRED"):
        E.raise_error(E.ERR_PACKAGE_NOT_REFUNDABLE,
                      "Package in %s cannot be refunded" % p["status"])
    if fam["status"] == "CLOSED":
        E.raise_error(E.ERR_FAMILY_NOT_ACTIVE, "Family is CLOSED")

    p["refund_cents"] = billing.credit_refund_final(p)
    p["status"] = "REFUNDED"
    touch(p)
    billing.refund_family(fam, p["refund_cents"])
    touch(fam)
    # Reserved sessions against this package cancel early; reservations released.
    reserved = [s for s in db.sessions.values()
                if s["package_id"] == pid and s["attendance_state"] == "SCHEDULED"
                and s["billing_state"] == "RESERVED"]
    billing.cancel_sessions_early(reserved)
    billing.recompute_family_plan_postures(fam["id"])
    return success_object(package_pub(p), 200)


@bp.get("/packages/<pid>/sessions")
def package_sessions(pid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach"])
    get_entity("package", pid)
    rows = [s for s in db.sessions.values() if s["package_id"] == pid]
    return list_response(rows, session_pub, paginate=False)
