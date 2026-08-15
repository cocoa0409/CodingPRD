from flask import Blueprint, request

from auth import parse_auth
from db import store
from envelope import ok, paginate
from errors import not_found
from util import serialize, sort_key

bp = Blueprint("statements", __name__)


def get_statement(sid):
    s = store.statements.get(sid)
    if s is None:
        raise not_found("settlement statement not found")
    return s


def get_line(lid):
    l = store.lines.get(lid)
    if l is None:
        raise not_found("settlement line not found")
    return l


@bp.get("/market/statements/<statementId>")
def get_one(statementId):
    parse_auth()
    return ok(serialize(get_statement(statementId)))


@bp.get("/market/statements")
def list_statements():
    parse_auth()
    rows = sorted(store.statements.values(), key=sort_key)
    pid = request.args.get("market_participant_id")
    day_id = request.args.get("operating_day_id")
    status = request.args.get("status")
    run_type = request.args.get("run_type")
    supersedes = request.args.get("supersedes_statement_id")
    if pid is not None:
        rows = [r for r in rows if r["market_participant_id"] == pid]
    if day_id is not None:
        rows = [r for r in rows if r["operating_day_id"] == day_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if run_type is not None:
        rows = [r for r in rows if r["run_type"] == run_type]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_statement_id"] == supersedes]
    return paginate([serialize(r) for r in rows])


@bp.get("/market/statements/<statementId>/lines")
def list_statement_lines(statementId):
    parse_auth()
    stmt = get_statement(statementId)
    rows = sorted((l for l in store.lines.values()
                   if l["settlement_statement_id"] == stmt["id"]), key=sort_key)
    return paginate([serialize(r) for r in rows])


@bp.get("/market/lines/<lineId>")
def get_one_line(lineId):
    parse_auth()
    return ok(serialize(get_line(lineId)))


@bp.get("/market/lines")
def list_lines():
    parse_auth()
    rows = sorted(store.lines.values(), key=sort_key)
    sid = request.args.get("settlement_statement_id")
    gen_id = request.args.get("generator_asset_id")
    charge_type = request.args.get("charge_type")
    if sid is not None:
        rows = [r for r in rows if r["settlement_statement_id"] == sid]
    if gen_id is not None:
        rows = [r for r in rows if r["generator_asset_id"] == gen_id]
    if charge_type is not None:
        rows = [r for r in rows if r["charge_type"] == charge_type]
    return paginate([serialize(r) for r in rows])
