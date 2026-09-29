"""RoyaltyStatement and StatementLine endpoints (§3.7, §3.8)."""

from flask import Blueprint

import lookup
import serializers
import validation
from constants import API_PREFIX, ROLE_RIGHTS_HOLDER_USER, ROLE_ROYALTY_ADMIN
from db import db, fmt_dt, now, stamp_new, touch
from errors import ApiError
from middleware import current_role, current_user_id, require
from response import created_response, object_response, paginate_and_serialize
from services import derive, statements as statement_service

bp = Blueprint("statements", __name__, url_prefix=API_PREFIX)


@bp.post("/statements")
@require(ROLE_ROYALTY_ADMIN)
def create_statement():
    data = validation.body()

    raw_holder_id = data.get("rights_holder_id")
    holder = None
    if isinstance(raw_holder_id, str) and raw_holder_id:
        holder = lookup.holder(raw_holder_id)
    raw_period_id = data.get("period_id")
    period = None
    if isinstance(raw_period_id, str) and raw_period_id:
        period = lookup.period(raw_period_id)

    rights_holder_id = validation.get_id(data, "rights_holder_id")
    period_id = validation.get_id(data, "period_id")
    expected_period_version = validation.get_int(data, "expected_period_version")

    if holder is None:
        holder = lookup.holder(rights_holder_id)
    if period is None:
        period = lookup.period(period_id)

    for existing in db.statements.values():
        if existing["rights_holder_id"] == holder["id"] \
                and existing["period_id"] == period["id"] \
                and existing["status"] in ("DRAFT", "ISSUED"):
            raise ApiError("ERR_DUPLICATE_STATEMENT")

    if period["status"] not in ("DISTRIBUTED", "REOPENED"):
        raise ApiError("ERR_INVALID_PERIOD_STATE")

    if expected_period_version != period["version"]:
        raise ApiError("ERR_STALE_PERIOD_VERSION")

    record = {
        "rights_holder_id": holder["id"],
        "period_id": period["id"],
        "status": "DRAFT",
        "issued_at": None,
    }
    stamp_new(record)
    db.statements[record["id"]] = record

    statement_service.build_lines(record, period)
    touch(period)
    return created_response(serializers.royalty_statement(record))


@bp.get("/statements/<statement_id>")
@require()
def read_statement(statement_id):
    statement = lookup.statement(statement_id)
    if current_role() == ROLE_RIGHTS_HOLDER_USER \
            and statement["rights_holder_id"] != current_user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return object_response(serializers.royalty_statement(statement))


@bp.get("/statements")
@require()
def list_statements():
    records = lookup.apply_filters(db.statements.values(), {
        "rights_holder_id": lookup.field("rights_holder_id"),
        "period_id": lookup.field("period_id"),
        "status": lookup.field("status"),
    })
    return paginate_and_serialize(records, serializers.royalty_statement)


@bp.post("/statements/<statement_id>/issue")
@require(ROLE_ROYALTY_ADMIN)
def issue_statement(statement_id):
    statement = lookup.statement(statement_id)

    if statement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")

    lines = derive.statement_lines_of(statement["id"])
    if not lines:
        raise ApiError("ERR_NO_STATEMENT_LINES")

    for line in lines:
        pool = db.pools.get(line["pool_id"])
        if pool is None or pool["status"] != "FINALIZED":
            raise ApiError("ERR_INVALID_POOL_STATE")

    statement["status"] = "ISSUED"
    statement["issued_at"] = fmt_dt(now())
    touch(statement)

    holder = db.rights_holders.get(statement["rights_holder_id"])
    if holder is not None:
        touch(holder)
    return object_response(serializers.royalty_statement(statement))


# --------------------------------------------------------------------------
# StatementLine
# --------------------------------------------------------------------------

@bp.get("/statement-lines/<line_id>")
@require()
def read_statement_line(line_id):
    line = lookup.statement_line(line_id)
    return object_response(serializers.statement_line(line))


@bp.get("/statement-lines")
@require()
def list_statement_lines():
    records = lookup.apply_filters(db.statement_lines.values(), {
        "statement_id": lookup.field("statement_id"),
        "pool_id": lookup.field("pool_id"),
        "work_id": lookup.field("work_id"),
        "payee_holder_id": lookup.field("payee_holder_id"),
        "adjustment_of_line_id": lookup.field("adjustment_of_line_id"),
        "line_type": lookup.field("line_type"),
        "right_type": lookup.field("right_type"),
        "territory_code": lookup.field("territory_code"),
        "subscription_tier": lookup.field("subscription_tier"),
    })
    return paginate_and_serialize(records, serializers.statement_line)
