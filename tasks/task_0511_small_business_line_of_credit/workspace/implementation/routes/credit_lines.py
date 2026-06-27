"""CreditLine routes (PRD §3.3, §3.6). Activation, freeze/unfreeze, close,
declare-default, charge-off (OCC + SoD + 3-hop cascade)."""
from flask import Blueprint, request

import constants as C
import db
import serialize
from common import parse_body, require_fields, require_int, stamp_create, touch, list_response
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
                    ERR_SEGREGATION_OF_DUTIES, ERR_APPLICATION_NOT_APPROVED)
from lookups import get_application, get_credit_line
from middleware import auth_and_role
from response import object_response
from services import ledger

bp = Blueprint("credit_lines", __name__)

CADENCES = {"DAILY", "WEEKLY"}


@bp.post("/credit-lines")
def activate_line():
    auth_and_role(["CreditOfficer"])
    body = parse_body()
    require_fields(body, ["application_id", "remittance_cadence"])
    app = get_application(body["application_id"])
    cadence = body["remittance_cadence"]
    if cadence not in CADENCES:
        raise err(ERR_INVALID_REQUEST, "remittance_cadence must be DAILY or WEEKLY")

    # priority 12: application must be APPROVED and not already originated a line.
    if app["status"] != "APPROVED":
        raise err(ERR_APPLICATION_NOT_APPROVED, "Application is not APPROVED")
    for cl in db.credit_lines.values():
        if cl["application_id"] == app["id"]:
            raise err(ERR_APPLICATION_NOT_APPROVED, "Application already originated a line")

    tier = app["pricing_tier"]
    record = {
        "application_id": app["id"],
        "merchant_id": app["merchant_id"],
        "credit_limit_cents": app["approved_limit_cents"],
        "pricing_tier": tier,
        "fee_factor_bps": C.TIER_FEE_BPS[tier],
        "remittance_cadence": cadence,
        "outstanding_principal_cents": 0,
        "outstanding_fee_cents": 0,
        "available_credit_cents": max(0, app["approved_limit_cents"]),
        "nsf_strike_count": 0,
        "status": "ACTIVE",
        "defaulted_by_user_id": None,
    }
    stamp_create(record)
    db.credit_lines[record["id"]] = record
    return object_response(serialize.credit_line(record), 201)


@bp.get("/credit-lines/<rid>")
def fetch_line(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    cl = get_credit_line(rid)
    return object_response(serialize.credit_line(cl), 200)


@bp.get("/credit-lines")
def list_lines():
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    merchant_id = request.args.get("merchant_id")
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    lines = list(db.credit_lines.values())
    if merchant_id is not None:
        lines = [l for l in lines if l["merchant_id"] == merchant_id]
    if application_id is not None:
        lines = [l for l in lines if l["application_id"] == application_id]
    if status is not None:
        lines = [l for l in lines if l["status"] == status]
    return list_response(lines, serialize.credit_line)


@bp.post("/credit-lines/<rid>/freeze")
def freeze_line(rid):
    auth_and_role(["Servicer"])
    cl = get_credit_line(rid)
    if cl["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Line is not ACTIVE")
    cl["status"] = "FROZEN"
    touch(cl)
    return object_response(serialize.credit_line(cl), 200)


@bp.post("/credit-lines/<rid>/unfreeze")
def unfreeze_line(rid):
    auth_and_role(["Servicer"])
    cl = get_credit_line(rid)
    if cl["status"] != "FROZEN":
        raise err(ERR_INVALID_STATE, "Line is not FROZEN")
    cl["status"] = "ACTIVE"
    touch(cl)
    return object_response(serialize.credit_line(cl), 200)


@bp.post("/credit-lines/<rid>/close")
def close_line(rid):
    auth_and_role(["Servicer"])
    cl = get_credit_line(rid)
    if cl["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Line is not ACTIVE")
    if cl["outstanding_principal_cents"] != 0 or cl["outstanding_fee_cents"] != 0:
        raise err(ERR_INVALID_STATE, "Line is not fully paid off")
    cl["status"] = "CLOSED"
    touch(cl)
    return object_response(serialize.credit_line(cl), 200)


@bp.post("/credit-lines/<rid>/declare-default")
def declare_default(rid):
    user_id, _ = auth_and_role(["CreditOfficer"])
    cl = get_credit_line(rid)
    body = parse_body()
    # priority 5: well-formedness of expected_credit_line_version.
    expected = require_int(body, "expected_credit_line_version", minimum=0)
    # priority 6: state legality (status + nsf_strike_count threshold precondition).
    if cl["status"] != "DELINQUENT":
        raise err(ERR_INVALID_STATE, "Line is not DELINQUENT")
    if cl["nsf_strike_count"] < C.NSF_DEFAULT_THRESHOLD:
        raise err(ERR_INVALID_STATE, "nsf_strike_count below default threshold")
    # priority 7: OCC.
    if expected != cl["version"]:
        raise err(ERR_STALE_VERSION, "expected_credit_line_version does not match")

    cl["defaulted_by_user_id"] = user_id
    # cancel all SCHEDULED remittances on this line.
    for rem in db.remittances.values():
        if rem["credit_line_id"] == cl["id"] and rem["status"] == "SCHEDULED":
            rem["status"] = "CANCELLED"
            touch(rem)
    cl["status"] = "DEFAULTED"
    touch(cl)
    return object_response(serialize.credit_line(cl), 200)


@bp.post("/credit-lines/<rid>/charge-off")
def charge_off(rid):
    user_id, _ = auth_and_role(["CreditOfficer"])
    cl = get_credit_line(rid)
    body = parse_body()
    expected = require_int(body, "expected_credit_line_version", minimum=0)

    # SoD (priority 3) — charge-off operator must differ from default declarer.
    if cl.get("defaulted_by_user_id") is not None and user_id == cl["defaulted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Charge-off must differ from default declarer")
    # state legality (priority 6).
    if cl["status"] != "DEFAULTED":
        raise err(ERR_INVALID_STATE, "Line is not DEFAULTED")
    # OCC (priority 7).
    if expected != cl["version"]:
        raise err(ERR_STALE_VERSION, "expected_credit_line_version does not match")

    # 3-hop cascade: OUTSTANDING Draw -> WRITTEN_OFF -> WRITE_OFF LedgerEntry -> recompute.
    balance = ledger.current_principal_balance(cl["id"])
    outstanding = [d for d in db.draws.values()
                   if d["credit_line_id"] == cl["id"] and d["status"] == "OUTSTANDING"]
    # deterministic order by creation seq.
    outstanding.sort(key=lambda d: d["_seq"])
    for d in outstanding:
        unrepaid_principal = d["principal_cents"] - d["principal_repaid_cents"]
        d["status"] = "WRITTEN_OFF"
        touch(d)
        balance = balance - unrepaid_principal
        ledger.append_entry(
            credit_line_id=cl["id"],
            draw_id=d["id"],
            remittance_id=None,
            entry_type="WRITE_OFF",
            amount_cents=-unrepaid_principal,
            balance_after_cents=balance,
        )
    ledger.recompute_outstanding(cl)
    cl["status"] = "CHARGED_OFF"
    touch(cl)
    return object_response(serialize.credit_line(cl), 200)
