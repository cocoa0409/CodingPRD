"""ChargebackEntry endpoints (PRD §3.9). Entries are created only as cascade
products; the list endpoint is their sole discovery channel."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import rerun_overrun_posture_check, touch

bp = Blueprint("chargeback_entries", __name__)
from validate import require_path_resource


@bp.get("/mobility/chargeback-entries/<rid>")
def get_entry(rid):
    return get_one("chargeback_entries", rid)


@bp.get("/mobility/chargeback-entries")
def list_entries():
    return list_response("chargeback_entries", {
        "assignment_id": request.args.get("assignment_id"),
        "entry_type": request.args.get("entry_type"),
        "status": request.args.get("status"),
        "source_record_id": request.args.get("source_record_id"),
        "source_settlement_id": request.args.get("source_settlement_id"),
    })


@bp.post("/mobility/chargeback-entries/<rid>/post")
def post_entry(rid):
    authorized(["FinanceController"])
    e = require_path_resource("chargeback_entries", rid)
    if e["status"] != "ACCRUED":
        raise_error(ERR_INVALID_STATE, "only an ACCRUED entry can be posted")
    e["status"] = "POSTED"
    touch(e)
    asg = db["assignments"].get(e["assignment_id"])
    if asg is not None:
        program = db["programs"].get(asg["program_id"])
        if program is not None:
            program["total_posted_chargeback_cents"] += e["amount_cents"]
            touch(program, bump_version=False)
    return success_object(public(e))


@bp.post("/mobility/chargeback-entries/<rid>/void")
def void_entry(rid):
    authorized(["FinanceController"])
    e = require_path_resource("chargeback_entries", rid)
    if e["status"] not in ("ACCRUED", "POSTED"):
        raise_error(ERR_INVALID_STATE, "only an ACCRUED or POSTED entry can be voided")
    was_posted = e["status"] == "POSTED"
    e["status"] = "VOIDED"
    touch(e)
    asg = db["assignments"].get(e["assignment_id"])
    if asg is not None:
        if was_posted:
            program = db["programs"].get(asg["program_id"])
            if program is not None:
                program["total_posted_chargeback_cents"] -= e["amount_cents"]
                touch(program, bump_version=False)
        asg["ytd_chargeback_cents"] -= e["amount_cents"]
        touch(asg, bump_version=False)
        rerun_overrun_posture_check(asg)
    return success_object(public(e))
