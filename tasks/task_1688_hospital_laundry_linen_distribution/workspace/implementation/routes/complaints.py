"""Complaint endpoints (PRD 3.7)."""
from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_ALREADY_TERMINAL, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_NO_ISOLATION_LINE, ERR_UNAUTHORIZED_ROLE, ERR_UNIT_OWNERSHIP, raise_err
from serializers import complaint_out
from util import body_json, bump, fk_ref, get_or_404, list_response, new_record, \
    req_enum, req_int, success_object

bp = Blueprint("complaints", __name__)

COMPLAINT_TYPES = ["STAINS", "TEARS", "FOREIGN_OBJECT", "ODOR", "ISOLATION_BREACH"]
TERMINAL = ("REJECTED", "RESCINDED", "RESOLVED")


def _conditional_role(complaint, role):
    """ISOLATION_BREACH is adjudicated by InfectionControlOfficer; all other
    types by LinenManager."""
    if complaint["complaint_type"] == "ISOLATION_BREACH":
        if role != "InfectionControlOfficer":
            raise_err(ERR_UNAUTHORIZED_ROLE,
                      "ISOLATION_BREACH complaints require InfectionControlOfficer")
    else:
        if role != "LinenManager":
            raise_err(ERR_UNAUTHORIZED_ROLE,
                      "non-isolation complaints require LinenManager")


def _check_adjudication_state(complaint, verb):
    if complaint["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL,
                  "complaint is %s (terminal)" % complaint["status"])
    if complaint["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE,
                  "%s requires status OPEN, got %s" % (verb, complaint["status"]))


@bp.route("/complaints", methods=["POST"])
def create_complaint():
    uid, role = authenticate()
    authorize(role, ["UnitClerk"])
    body = body_json()

    unit = fk_ref(body, "unit_id", store.units, "Unit")
    manifest = fk_ref(body, "manifest_id", store.manifests, "SoiledManifest")
    stock = fk_ref(body, "stock_id", store.stocks, "LinenStock")
    ctype = req_enum(body, "complaint_type", COMPLAINT_TYPES)
    pieces = req_int(body, "pieces_affected")
    if pieces < 1:
        raise_err(ERR_INVALID_REQUEST, "pieces_affected must be >= 1")

    # ownership (priority 7): the clerk files for their own unit only
    if unit["id"] != uid:
        raise_err(ERR_UNIT_OWNERSHIP,
                  "UnitClerk may only file complaints for their own unit")

    # referential (priority 10): isolation breach needs an isolation line
    if ctype == "ISOLATION_BREACH":
        if not any(l["stock_id"] == stock["id"] and l["isolation_flag"]
                   for l in manifest["lines"]):
            raise_err(ERR_NO_ISOLATION_LINE,
                      "manifest %s has no isolation-flagged line for stock %s"
                      % (manifest["id"], stock["id"]))

    rec = new_record()
    rec.update({
        "unit_id": unit["id"],
        "manifest_id": manifest["id"],
        "stock_id": stock["id"],
        "complaint_type": ctype,
        "pieces_affected": pieces,
        "status": "OPEN",
        "credit_cents": 0,
        "routed_invoice_id": None,
        "_credit_target": None,
    })
    store.complaints[rec["id"]] = rec
    return success_object(complaint_out(rec), 201)


@bp.route("/complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.complaints, complaint_id, "Complaint")
    return success_object(complaint_out(rec))


@bp.route("/complaints", methods=["GET"])
def list_complaints():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.complaints.values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        records = [r for r in records if r["unit_id"] == unit_id]
    stock_id = request.args.get("stock_id")
    if stock_id is not None:
        records = [r for r in records if r["stock_id"] == stock_id]
    manifest_id = request.args.get("manifest_id")
    if manifest_id is not None:
        records = [r for r in records if r["manifest_id"] == manifest_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, complaint_out)


@bp.route("/complaints/<complaint_id>/verify", methods=["POST"])
def verify_complaint(complaint_id):
    """complaint_credit calc: pieces_affected * per-piece rate at the
    facility's current contracted rate; routed to the invoice only when it is
    FINALIZED or DISPUTED, else to the facility credit balance (PRD 3.7)."""
    _, role = authenticate()
    authorize(role, ["LinenManager", "InfectionControlOfficer"])
    c = get_or_404(store.complaints, complaint_id, "Complaint")
    body_json()

    _conditional_role(c, role)
    _check_adjudication_state(c, "verify")

    stock = store.stocks[c["stock_id"]]
    fac = store.facilities[stock["facility_id"]]
    credit = c["pieces_affected"] * services.per_piece_rate_cents(stock, fac)

    manifest = store.manifests.get(c["manifest_id"])
    inv = store.invoices.get(manifest["invoice_id"]) if manifest and manifest["invoice_id"] else None
    if inv is not None:
        c["routed_invoice_id"] = inv["id"]
        if inv["status"] in ("FINALIZED", "DISPUTED"):
            inv["credit_total_cents"] += credit
            inv["billed_total_cents"] -= credit
            bump(inv)
            c["_credit_target"] = ("invoice", inv["id"])
        else:
            fac["credit_balance_cents"] += credit
            bump(fac)
            c["_credit_target"] = ("facility", fac["id"])
    else:
        c["routed_invoice_id"] = None
        fac["credit_balance_cents"] += credit
        bump(fac)
        c["_credit_target"] = ("facility", fac["id"])

    c["credit_cents"] = credit
    c["status"] = "VERIFIED"
    bump(c)
    return success_object(complaint_out(c), 200)


@bp.route("/complaints/<complaint_id>/reject", methods=["POST"])
def reject_complaint(complaint_id):
    _, role = authenticate()
    authorize(role, ["LinenManager", "InfectionControlOfficer"])
    c = get_or_404(store.complaints, complaint_id, "Complaint")
    body_json()  # optional reason

    _conditional_role(c, role)
    _check_adjudication_state(c, "reject")

    c["status"] = "REJECTED"
    bump(c)
    return success_object(complaint_out(c), 200)


@bp.route("/complaints/<complaint_id>/rescind", methods=["POST"])
def rescind_complaint(complaint_id):
    """Exact compensation of verification (PRD 3.7)."""
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    c = get_or_404(store.complaints, complaint_id, "Complaint")
    body_json()

    if c["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL,
                  "complaint is %s (terminal)" % c["status"])
    if c["status"] != "VERIFIED":
        raise_err(ERR_INVALID_STATE,
                  "rescind requires status VERIFIED, got %s" % c["status"])

    target = c.get("_credit_target")
    if target is not None and target[0] == "invoice":
        inv = store.invoices.get(target[1])
        if inv is not None:
            inv["credit_total_cents"] -= c["credit_cents"]
            inv["billed_total_cents"] += c["credit_cents"]
            bump(inv)
    elif target is not None:
        fac = store.facilities.get(target[1])
        if fac is not None:
            fac["credit_balance_cents"] -= c["credit_cents"]
            bump(fac)

    c["status"] = "RESCINDED"
    bump(c)
    return success_object(complaint_out(c), 200)
