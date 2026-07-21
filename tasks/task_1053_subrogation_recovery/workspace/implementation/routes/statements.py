"""Commission statement endpoints (§3.8)."""
from flask import Blueprint, request

import calc
import errors
import serialize
import validate as v
from auth import authorize
from envelope import success
from helpers import lookup_or_404, respond_list
from store import db, stamp, touch

bp = Blueprint("statements", __name__)


@bp.route("/subro/carriers/<carrier_id>/commission-statements", methods=["POST"])
def create_statement(carrier_id):
    authorize(request, {"FinanceOfficer"})
    carrier = lookup_or_404(db.carriers, carrier_id)
    body = v.get_body(request)
    period_label = v.req_str(body, "period_label")

    # sweep RECOVERED claims for this carrier, ordered by created_at ASC (creation order)
    recovered = [c for c in db.claims.values()
                 if c["carrier_id"] == carrier_id and c["status"] == "RECOVERED"]
    recovered.sort(key=lambda c: c["_seq"])
    lines = []
    for c in recovered:
        net_recovery = c["final_recovered_cents"] - c["deductible_reimbursed_cents"]
        commission = calc.commission_due_cents(c, carrier)
        lines.append({
            "claim_id": c["id"],
            "net_recovery_cents": net_recovery,
            "commission_cents": commission,
        })

    statement = stamp({
        "carrier_id": carrier_id,
        "period_label": period_label,
        "lines": lines,
        "total_commission_cents": 0,
        "status": "OPEN",
    })
    db.commission_statements[statement["id"]] = statement
    return success(serialize.commission_statement(statement), "object", 201)


@bp.route("/subro/commission-statements/<commission_statement_id>", methods=["GET"])
def get_statement(commission_statement_id):
    authorize(request, None)
    statement = lookup_or_404(db.commission_statements, commission_statement_id)
    return success(serialize.commission_statement(statement), "object", 200)


@bp.route("/subro/commission-statements", methods=["GET"])
def list_statements():
    authorize(request, None)
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")
    items = []
    for s in db.commission_statements.values():
        if carrier_id is not None and s["carrier_id"] != carrier_id:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(s)
    return respond_list(request, items, serialize.commission_statement)


@bp.route("/subro/commission-statements/<commission_statement_id>/finalize", methods=["POST"])
def finalize_statement(commission_statement_id):
    authorize(request, {"RecoveryManager"})
    statement = lookup_or_404(db.commission_statements, commission_statement_id)
    body = v.get_body(request)
    void = v.opt_bool(body, "void", default=False)

    if void:
        if statement["status"] != "OPEN":
            raise errors.statement_not_open()
        statement["status"] = "VOID"
        touch(statement)
        return success(serialize.commission_statement(statement), "object", 200)

    # (12) must be OPEN with non-empty lines
    if statement["status"] != "OPEN" or len(statement["lines"]) == 0:
        raise errors.statement_not_open()
    # round per line first (already whole cents), then sum
    total = sum(line["commission_cents"] for line in statement["lines"])
    statement["total_commission_cents"] = total
    statement["status"] = "FINALIZED"
    touch(statement)
    return success(serialize.commission_statement(statement), "object", 200)
