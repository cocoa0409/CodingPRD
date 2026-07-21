from flask import Blueprint, request
from core import (db, ApiError, auth, caller, body, ok, ok_list, base_full, touch,
                  as_str, as_int, as_enum, paginate, sort_seq)
import serial
import calc

bp = Blueprint("renter", __name__)


def get_renter_or_404(rid):
    r = db.renters.get(rid)
    if r is None:
        raise ApiError("ERR_RENTER_NOT_FOUND", 404, "Renter not found.")
    return r


def get_application_or_404(aid):
    a = db.applications.get(aid)
    if a is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found.")
    return a


def renter_owns(renter_id):
    uid, role = caller()
    if role == "Renter" and renter_id != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your resource.")


# ---------------------------------------------------------------------------
# Renter CRUD
# ---------------------------------------------------------------------------
@bp.post("/api/renters")
@auth("PlatformAdmin")
def create_renter():
    b = body()
    property_id = as_str(b, "property_id")
    email = as_str(b, "email")
    full_name = as_str(b, "full_name")
    portion_rent_cents = as_int(b, "portion_rent_cents", positive=True)
    prop = db.properties.get(property_id)
    if prop is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", 404, "Property not found.")
    for existing in db.renters.values():
        if existing["property_id"] == property_id and existing["email"] == email:
            raise ApiError("ERR_VALIDATION", 400, "Email already used for this property.")
    rec = base_full()
    rec.update({
        "property_id": property_id,
        "email": email,
        "full_name": full_name,
        "portion_rent_cents": portion_rent_cents,
        "status": "PROSPECT",
        "risk_band": None,
        "approved_limit_cents": 0,
        "autopay_enabled": False,
    })
    db.renters[rec["id"]] = rec
    return ok(serial.renter_out(rec), 201)


@bp.get("/api/renters/<rid>")
@auth("PlatformAdmin", "Renter")
def get_renter(rid):
    r = get_renter_or_404(rid)
    renter_owns(r["id"])
    return ok(serial.renter_out(r))


@bp.get("/api/renters")
@auth("PlatformAdmin")
def list_renters():
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    items = [r for r in db.renters.values()
             if (property_id is None or r["property_id"] == property_id)
             and (status is None or r["status"] == status)]
    items = sort_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serial.renter_out(r) for r in page], limit, offset, total)


@bp.get("/api/renters/<rid>/reminders")
@auth("PlatformAdmin", "Renter")
def renter_reminders(rid):
    r = get_renter_or_404(rid)
    renter_owns(r["id"])
    items = sort_seq([x for x in db.reminders.values() if x["renter_id"] == rid])
    page, limit, offset, total = paginate(items)
    return ok_list([serial.reminder_out(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
@bp.post("/api/renters/<rid>/applications")
@auth("Renter", "PlatformAdmin")
def submit_application(rid):
    b = body()
    income = as_int(b, "reported_monthly_income_cents", positive=True)
    split_count = as_int(b, "requested_split_count", minimum=2, maximum=4)
    prior = as_int(b, "prior_delinquency_count", required=False, non_negative=True)
    if prior is None:
        prior = 0
    r = get_renter_or_404(rid)
    renter_owns(r["id"])

    u = calc.underwrite(income, r["portion_rent_cents"], split_count, prior)
    rec = base_full()
    rec.update({
        "renter_id": rid,
        "reported_monthly_income_cents": income,
        "requested_split_count": split_count,
        "prior_delinquency_count": prior,
        "status": "SUBMITTED",
        "risk_score": u["risk_score"],
        "risk_band": u["risk_band"],
        "approved_limit_cents": u["approved_limit_cents"],
        "decision_reason": None,
    })
    db.applications[rec["id"]] = rec
    r["status"] = "UNDERWRITING"
    touch(r)
    return ok(serial.application_out(rec), 201)


@bp.get("/api/applications/<aid>")
@auth("Underwriter", "PlatformAdmin", "Renter")
def get_application(aid):
    a = get_application_or_404(aid)
    renter_owns(a["renter_id"])
    return ok(serial.application_out(a))


@bp.get("/api/renters/<rid>/applications")
@auth("Underwriter", "PlatformAdmin", "Renter")
def list_applications(rid):
    r = get_renter_or_404(rid)
    renter_owns(r["id"])
    items = sort_seq([a for a in db.applications.values() if a["renter_id"] == rid])
    page, limit, offset, total = paginate(items)
    return ok_list([serial.application_out(a) for a in page], limit, offset, total)


@bp.post("/api/applications/<aid>/decision")
@auth("Underwriter", "Renter")
def decide_application(aid):
    b = body()
    decision = as_enum(b, "decision", {"APPROVE", "DECLINE", "WITHDRAW"})
    a = get_application_or_404(aid)
    uid, role = caller()

    # role<->decision authorization (ERR_UNAUTHORIZED)
    if decision in ("APPROVE", "DECLINE") and role != "Underwriter":
        raise ApiError("ERR_UNAUTHORIZED", 403, "Only an Underwriter may approve/decline.")
    if decision == "WITHDRAW" and role != "Renter":
        raise ApiError("ERR_UNAUTHORIZED", 403, "Only the owning renter may withdraw.")

    # ownership for renter withdraw
    if role == "Renter" and a["renter_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your application.")

    # state
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not SUBMITTED.")

    renter = db.renters.get(a["renter_id"])

    if decision == "WITHDRAW":
        a["status"] = "WITHDRAWN"
        a["decision_reason"] = "withdrawn by renter"
        touch(a)
        return ok(serial.application_out(a))

    # APPROVE / DECLINE: evaluate eligibility
    ratio = calc.Decimal(a["reported_monthly_income_cents"]) / calc.Decimal(
        renter["portion_rent_cents"])
    eligible = (a["risk_score"] >= calc.DECLINE_SCORE_THRESHOLD and ratio >= calc.MIN_RATIO)

    if decision == "APPROVE" and eligible:
        a["status"] = "APPROVED"
        a["decision_reason"] = "approved: score and ratio within policy"
        touch(a)
        # cascade to renter
        if renter["status"] in ("PROSPECT", "UNDERWRITING"):
            renter["status"] = "ENROLLED"
        renter["approved_limit_cents"] = a["approved_limit_cents"]
        renter["risk_band"] = a["risk_band"]
        touch(renter)
        # cascade: create PAUSED mandate if none exists
        has_mandate = any(m["renter_id"] == renter["id"]
                          for m in db.autopay_mandates.values())
        if not has_mandate:
            m = base_full()
            m.update({"renter_id": renter["id"], "method_ref": None, "status": "PAUSED"})
            db.autopay_mandates[m["id"]] = m
        return ok(serial.application_out(a))

    # DECLINE (explicit) or APPROVE-but-ineligible -> DECLINED
    a["status"] = "DECLINED"
    a["decision_reason"] = "declined: score or income-to-rent ratio below policy"
    touch(a)
    renter["status"] = "SUSPENDED"
    touch(renter)
    return ok(serial.application_out(a))
