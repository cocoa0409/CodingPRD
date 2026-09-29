"""Commission statements and the nine-step settlement waterfall."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import FINANCE, MANAGER, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import statement_json
from services.commission import compute_statement, recompute_step_nine
from validation import (f, operator_or_404, paginate, pagination, port_call_or_404,
                        query_values, statement_or_404, validate_body)

bp = Blueprint("statements", __name__)

BASES = ("PROVISIONAL", "FINAL")
STATEMENT_STATUSES = ("DRAFT", "ISSUED", "DISPUTED", "ADJUSTED", "SETTLED", "VOIDED")
STATEMENT_ACTIONS = ("ISSUE", "DISPUTE", "ADJUST", "SETTLE")
OPEN_CLAIM_STATUSES = ("SUBMITTED", "UNDER_OPERATOR_REVIEW", "DISPUTED")

READ_ROLES = (FINANCE, MANAGER)

STATEMENT_CREATE = [
    f("operator_id", "string", required=True),
    f("port_call_id", "string", required=True),
    f("basis", "enum", required=True, enum=BASES),
    f("expected_operator_version", "int", required=True, lo=0),
]

STATEMENT_TRANSITION = [
    f("action", "enum", required=True, enum=STATEMENT_ACTIONS),
    f("note", "string"),
    f("adjustment_cents", "int"),
]


@bp.post(API_PREFIX + "/commission-statements")
@endpoint(FINANCE)
def create_statement(caller):
    body = validate_body(STATEMENT_CREATE)
    operator = operator_or_404(body["operator_id"])
    call = port_call_or_404(body["port_call_id"])

    if body["expected_operator_version"] != operator["version"]:
        fail("ERR_STALE_OPERATOR_VERSION", "the operator has been modified since it was read")

    for statement in db.ordered("statements"):
        if (statement["operator_id"] == operator["id"]
                and statement["port_call_id"] == call["id"]
                and statement["status"] == "DRAFT"):
            statement["status"] = "VOIDED"
            db.touch(statement)

    row = db.insert("statements", {
        "operator_id": operator["id"],
        "port_call_id": call["id"],
        "basis": body["basis"],
        "status": "DRAFT",
        "gross_ticket_cents": 0,
        "refunds_cents": 0,
        "port_fee_cents": 0,
        "line_commission_cents": 0,
        "claim_offset_cents": 0,
        "operational_penalty_cents": 0,
        "payable_pre_rebate_cents": 0,
        "rebate_bps": 0,
        "rebate_cents": 0,
        "adjustment_cents": 0,
        "operator_payable_cents": 0,
        "booking_line_count": 0,
        "issued_at": None,
        "settled_at": None,
    })
    compute_statement(row)
    return object_response(statement_json(row), 201)


@bp.get(API_PREFIX + "/commission-statements/<statement_id>")
@endpoint(*READ_ROLES)
def read_statement(caller, statement_id):
    return object_response(statement_json(statement_or_404(statement_id)))


@bp.get(API_PREFIX + "/commission-statements")
@endpoint(*READ_ROLES)
def list_statements(caller):
    limit, offset = pagination()
    filters = query_values([
        f("operator_id", "string"),
        f("port_call_id", "string"),
        f("status", "enum", enum=STATEMENT_STATUSES),
        f("basis", "enum", enum=BASES),
    ])
    rows = db.ordered("statements")
    for key in ("operator_id", "port_call_id", "status", "basis"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([statement_json(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/commission-statements/<statement_id>/transitions")
@endpoint(FINANCE)
def transition_statement(caller, statement_id):
    body = validate_body(STATEMENT_TRANSITION)
    statement = statement_or_404(statement_id)
    action = body["action"]
    status = statement["status"]

    if action == "ADJUST":
        if "adjustment_cents" not in body:
            fail("ERR_VALIDATION", "adjustment_cents is required to adjust a statement")
        proposed = (statement["payable_pre_rebate_cents"] + statement["rebate_cents"]
                    + body["adjustment_cents"])
        if proposed < 0:
            fail("ERR_VALIDATION", "the adjusted payable may not fall below zero")

    allowed = {
        "ISSUE": ("DRAFT",),
        "DISPUTE": ("ISSUED",),
        "ADJUST": ("DISPUTED",),
        "SETTLE": ("ISSUED", "ADJUSTED"),
    }[action]
    if status not in allowed:
        fail("ERR_INVALID_STATEMENT_ACTION",
             "%s is not declared for a statement in %s" % (action, status))
    if action == "SETTLE" and statement["basis"] != "FINAL":
        fail("ERR_INVALID_STATEMENT_ACTION", "only a FINAL statement may be settled")

    if action == "ISSUE":
        call = db.port_calls.get(statement["port_call_id"])
        if statement["basis"] == "FINAL" and (call is None or call["status"] != "CLOSED"):
            fail("ERR_PORT_CALL_NOT_CLOSED", "a FINAL statement needs a closed port call")
        for claim in db.claims.values():
            if (claim["operator_id"] == statement["operator_id"]
                    and claim["port_call_id"] == statement["port_call_id"]
                    and claim["status"] in OPEN_CLAIM_STATUSES):
                fail("ERR_OPEN_CLAIM_BLOCKS_ISSUE", "an unresolved liability claim blocks issue")

        compute_statement(statement)
        statement["status"] = "ISSUED"
        statement["issued_at"] = db.now()
        db.touch(statement)

    elif action == "DISPUTE":
        statement["status"] = "DISPUTED"
        db.touch(statement)

    elif action == "ADJUST":
        statement["adjustment_cents"] = body["adjustment_cents"]
        recompute_step_nine(statement)
        statement["status"] = "ADJUSTED"
        db.touch(statement)

    else:  # SETTLE
        statement["status"] = "SETTLED"
        statement["settled_at"] = db.now()
        db.touch(statement)
        operator = db.operators.get(statement["operator_id"])
        for claim in db.ordered("claims"):
            if (claim["operator_id"] == statement["operator_id"]
                    and claim["port_call_id"] == statement["port_call_id"]
                    and claim["status"] == "ADJUDICATED_UPHELD"):
                claim["status"] = "SETTLED"
                db.touch(claim)
                if operator is not None:
                    operator["liability_reserve_cents"] = max(
                        0, operator["liability_reserve_cents"] - claim["operator_charge_cents"])
                    db.touch(operator)

    return object_response(statement_json(statement))
