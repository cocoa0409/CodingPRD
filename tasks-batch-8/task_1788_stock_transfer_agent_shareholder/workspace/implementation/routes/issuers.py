"""Issuer endpoints: onboarding, price/status patch, freeze windows, record-date report."""
from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import (get_body, req_str, req_int, opt_int, req_dt, req_enum,
                     pagination_params, parse_dt)
from middleware import auth, require_role, officer_owns
from response import success_object, success_list
from services import (stamp_new, touch, audit, sorted_recs, issuer_view, window_view,
                      payments_of_declaration, now_iso)

bp = Blueprint("issuers", __name__)

ALL_ROLES = {"AgentAdmin", "Shareholder", "TransferExaminer", "TransferSupervisor",
             "IssuerOfficer", "ComplianceOfficer", "ServiceAgent"}
FREEZE_READ_ROLES = {"AgentAdmin", "IssuerOfficer", "TransferExaminer",
                     "TransferSupervisor", "ComplianceOfficer"}


def _get_issuer_or_404(issuer_id):
    issuer = STORE["issuers"].get(issuer_id)
    if issuer is None:
        fail("ERR_ISSUER_NOT_FOUND", "issuer %s does not exist" % issuer_id)
    return issuer


@bp.post("/issuers")
def create_issuer():
    user_id, role = auth()
    require_role(role, {"AgentAdmin"})
    body = get_body()
    name = req_str(body, "name")
    cusip = req_str(body, "cusip")
    ticker = req_str(body, "ticker")
    shares_outstanding = req_int(body, "shares_outstanding")
    if shares_outstanding < 0:
        fail("ERR_INVALID_REQUEST", "shares_outstanding must be >= 0")
    par_value = opt_int(body, "par_value_cents", 0)
    if par_value < 0:
        fail("ERR_INVALID_REQUEST", "par_value_cents must be >= 0")
    price = req_int(body, "current_market_price_cents")
    if price < 0:
        fail("ERR_INVALID_REQUEST", "current_market_price_cents must be >= 0")
    for existing in STORE["issuers"].values():
        if existing["cusip"] == cusip:
            fail("ERR_DUPLICATE_CUSIP", "cusip %s is already registered" % cusip)
    issuer = stamp_new({
        "name": name,
        "cusip": cusip,
        "ticker": ticker,
        "status": "ACTIVE",
        "shares_outstanding": shares_outstanding,
        "par_value_cents": par_value,
        "current_market_price_cents": price,
    })
    STORE["issuers"][issuer["id"]] = issuer
    audit("Issuer", issuer["id"], role, user_id, "issuer.create", "", "ACTIVE",
          "issuer onboarded")
    return success_object(issuer_view(issuer), 201)


@bp.get("/issuers/<issuer_id>")
def read_issuer(issuer_id):
    user_id, role = auth()
    require_role(role, ALL_ROLES)
    if role == "IssuerOfficer":
        officer_owns(user_id, issuer_id)
    issuer = _get_issuer_or_404(issuer_id)
    return success_object(issuer_view(issuer))


@bp.patch("/issuers/<issuer_id>")
def patch_issuer(issuer_id):
    user_id, role = auth()
    require_role(role, {"IssuerOfficer"})
    officer_owns(user_id, issuer_id)
    issuer = _get_issuer_or_404(issuer_id)
    body = get_body()
    new_status = None
    if "status" in body and body["status"] is not None:
        new_status = req_enum(body, "status", {"ACTIVE", "SUSPENDED"})
    new_price = None
    if "current_market_price_cents" in body and body["current_market_price_cents"] is not None:
        new_price = req_int(body, "current_market_price_cents")
        if new_price < 0:
            fail("ERR_INVALID_REQUEST", "current_market_price_cents must be >= 0")
    transition_action = None
    if new_status is not None and new_status != issuer["status"]:
        if issuer["status"] == "ACTIVE" and new_status == "SUSPENDED":
            transition_action = ("issuer.suspend", "ACTIVE", "SUSPENDED")
        elif issuer["status"] == "SUSPENDED" and new_status == "ACTIVE":
            transition_action = ("issuer.resume", "SUSPENDED", "ACTIVE")
        else:
            fail("ERR_INVALID_STATE", "issuer status transition not permitted")
    elif new_status is not None:
        fail("ERR_INVALID_STATE", "issuer is already %s" % issuer["status"])
    if transition_action is not None:
        action, frm, to = transition_action
        issuer["status"] = new_status
        touch(issuer)
        audit("Issuer", issuer["id"], role, user_id, action, frm, to,
              "issuer status changed to %s" % to)
    if new_price is not None and new_price != issuer["current_market_price_cents"]:
        issuer["current_market_price_cents"] = new_price
        touch(issuer)
        audit("Issuer", issuer["id"], role, user_id, "issuer.patch",
              issuer["status"], issuer["status"], "market price updated")
    elif transition_action is None:
        # PATCH with no effective change still refreshes the record
        touch(issuer)
        audit("Issuer", issuer["id"], role, user_id, "issuer.patch",
              issuer["status"], issuer["status"], "issuer patched")
    return success_object(issuer_view(issuer))


@bp.post("/issuers/<issuer_id>/freeze-windows")
def create_freeze_window(issuer_id):
    user_id, role = auth()
    require_role(role, {"IssuerOfficer"})
    officer_owns(user_id, issuer_id)
    issuer = _get_issuer_or_404(issuer_id)
    body = get_body()
    start_date = req_dt(body, "start_date")
    end_date = req_dt(body, "end_date")
    reason = req_str(body, "reason")
    if end_date < start_date:
        fail("ERR_INVALID_DATE_RANGE", "freeze-window end_date is before start_date")
    for existing in STORE["freeze_windows"].values():
        if existing["issuer_id"] != issuer["id"] or existing["status"] == "EXPIRED":
            continue
        s2 = parse_dt(existing["start_date"], "start_date")
        e2 = parse_dt(existing["end_date"], "end_date")
        # closed-interval overlap: s1 <= e2 AND s2 <= e1
        if start_date <= e2 and s2 <= end_date:
            fail("ERR_FREEZE_WINDOW_OVERLAP",
                 "freeze window overlaps an existing window for this issuer")
    window = stamp_new({
        "issuer_id": issuer["id"],
        "start_date": _fmt_keep(body, "start_date", start_date),
        "end_date": _fmt_keep(body, "end_date", end_date),
        "reason": reason,
        "status": "SCHEDULED",
    })
    STORE["freeze_windows"][window["id"]] = window
    audit("TransferFreezeWindow", window["id"], role, user_id, "freeze.create",
          "", "SCHEDULED", "transfer freeze window declared")
    return success_object(window_view(window), 201)


def _fmt_keep(body, name, parsed):
    # store normalized ISO string for the datetime the client supplied
    from helpers import fmt_dt
    return fmt_dt(parsed)


@bp.get("/freeze-windows")
def list_freeze_windows():
    user_id, role = auth()
    require_role(role, FREEZE_READ_ROLES)
    issuer_filter = request.args.get("issuer_id")
    status_filter = request.args.get("status")
    if role == "IssuerOfficer" and issuer_filter is not None:
        officer_owns(user_id, issuer_filter)
    items = sorted_recs("freeze_windows")
    if issuer_filter is not None:
        items = [w for w in items if w["issuer_id"] == issuer_filter]
    if status_filter is not None:
        items = [w for w in items if w["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([window_view(w) for w in page], limit, offset, total)


@bp.get("/issuers/<issuer_id>/freeze-windows")
def list_issuer_freeze_windows(issuer_id):
    user_id, role = auth()
    require_role(role, FREEZE_READ_ROLES)
    if role == "IssuerOfficer":
        officer_owns(user_id, issuer_id)
    issuer = _get_issuer_or_404(issuer_id)
    items = [w for w in sorted_recs("freeze_windows") if w["issuer_id"] == issuer["id"]]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([window_view(w) for w in page], limit, offset, total)


@bp.get("/issuers/<issuer_id>/record-date-report")
def record_date_report(issuer_id):
    user_id, role = auth()
    require_role(role, {"IssuerOfficer", "AgentAdmin"})
    if role == "IssuerOfficer":
        officer_owns(user_id, issuer_id)
    issuer = _get_issuer_or_404(issuer_id)
    declaration_id = request.args.get("declaration_id")
    if not declaration_id:
        fail("ERR_INVALID_REQUEST", "declaration_id query parameter is required")
    decl = STORE["declarations"].get(declaration_id)
    if decl is None or decl["issuer_id"] != issuer["id"]:
        fail("ERR_DECLARATION_NOT_FOUND", "declaration %s does not exist for this issuer"
             % declaration_id)
    entries = []
    for payment in payments_of_declaration(decl["id"]):
        entries.append({
            "account_id": payment["account_id"],
            "eligible_shares": payment["eligible_shares"],
            "gross_cents": payment["gross_cents"],
            "status": payment["status"],
        })
    report = {
        "declaration_id": decl["id"],
        "record_date": decl["record_date"],
        "total_shares": sum(e["eligible_shares"] for e in entries),
        "total_accounts": len(entries),
        "entries": entries,
    }
    return success_object(report)
