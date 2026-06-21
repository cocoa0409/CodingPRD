"""Lien-waiver endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
import helpers as h
import services
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_CROSS_PROJECT_REFERENCE,
    ERR_WAIVER_MISMATCH, ERR_PAYAPP_NOT_CERTIFIED,
)
from middleware import authenticate, require_role
from response import success

bp = Blueprint("lien_waivers", __name__)

WAIVER_TYPES = {"CONDITIONAL_PROGRESS", "UNCONDITIONAL_PROGRESS",
                "CONDITIONAL_FINAL", "UNCONDITIONAL_FINAL"}
UNCONDITIONAL = {"UNCONDITIONAL_PROGRESS", "UNCONDITIONAL_FINAL"}


def _get_or_404(wid):
    w = db.lien_waivers.get(wid)
    if w is None:
        raise err(ERR_NOT_FOUND, "LienWaiver not found.")
    return w


@bp.post("/lien-waivers")
def create_lien_waiver():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "pay_app_id", "waiver_type",
                            "through_date", "amount_cents"])

    project_id = h.as_string(body["project_id"], "project_id")
    pay_app_id = h.as_string(body["pay_app_id"], "pay_app_id")

    # Existence left-to-right (priority 3): project then pay_app.
    project = db.projects.get(project_id)
    if project is None:
        raise err(ERR_NOT_FOUND, "Project not found.")
    pay_app = db.pay_applications.get(pay_app_id)
    if pay_app is None:
        raise err(ERR_NOT_FOUND, "PayApplication not found.")

    # Cross-project referential integrity (priority 4): pay_app's project must
    # match the waiver's own project_id.
    if pay_app["project_id"] != project_id:
        raise err(ERR_CROSS_PROJECT_REFERENCE,
                  "pay_app belongs to a different project than the waiver.")

    waiver_type = h.as_enum(body["waiver_type"], "waiver_type", WAIVER_TYPES)
    through_date_dt = h.parse_datetime(body["through_date"], "through_date")
    amount = h.as_int(body["amount_cents"], "amount_cents", allow_negative=False)

    # Validation ordering (PRD §2.10): ERR_WAIVER_MISMATCH (14) precedes
    # ERR_PAYAPP_NOT_CERTIFIED (15).
    period_to_dt = h.parse_datetime(pay_app["period_to"], "period_to")
    if amount != pay_app["current_payment_due_cents"] or through_date_dt != period_to_dt:
        raise err(ERR_WAIVER_MISMATCH,
                  "amount_cents/through_date must match the pay application.")
    if pay_app["status"] != "CERTIFIED":
        raise err(ERR_PAYAPP_NOT_CERTIFIED, "Linked pay application is not CERTIFIED.")

    record = {
        "project_id": project_id,
        "pay_app_id": pay_app_id,
        "waiver_type": waiver_type,
        "through_date": body["through_date"],
        "amount_cents": amount,
        "status": "PENDING",
    }
    db.stamp_create(record)
    db.lien_waivers[record["id"]] = record
    return success(h.lien_waiver_out(record), status=201)


@bp.get("/lien-waivers/<wid>")
def get_lien_waiver(wid):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.lien_waiver_out(_get_or_404(wid)))


@bp.get("/lien-waivers")
def list_lien_waivers():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    pay_app_id = request.args.get("pay_app_id")
    status = request.args.get("status")
    records = list(db.lien_waivers.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if pay_app_id:
        records = [r for r in records if r["pay_app_id"] == pay_app_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.lien_waiver_out(r) for r in page], pagination=meta)


@bp.post("/lien-waivers/<wid>/notarize")
def notarize_lien_waiver(wid):
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    w = _get_or_404(wid)
    if w["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "LienWaiver is not PENDING.")
    if w["waiver_type"] in UNCONDITIONAL:
        # Payment must have been made: at least one CERTIFIED pay app on the
        # project whose current_payment_due_cents == this waiver's amount_cents.
        paid = any(pa["project_id"] == w["project_id"] and pa["status"] == "CERTIFIED"
                   and pa["current_payment_due_cents"] == w["amount_cents"]
                   for pa in db.pay_applications.values())
        if not paid:
            raise err(ERR_INVALID_STATE,
                      "Unconditional waiver requires a matching certified payment.")
    w["status"] = "EFFECTIVE"
    db.touch(w)
    # Commitment-invoice sweep for unconditional waivers only.
    if w["waiver_type"] in UNCONDITIONAL:
        services.commitment_invoice_sweep(w["project_id"], w["amount_cents"])
    return success(h.lien_waiver_out(w))


@bp.post("/lien-waivers/<wid>/void")
def void_lien_waiver(wid):
    _uid, role = authenticate()
    require_role(role, {"Owner"})
    w = _get_or_404(wid)
    if w["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "LienWaiver is not PENDING.")
    w["status"] = "VOID"
    db.touch(w)
    return success(h.lien_waiver_out(w))
