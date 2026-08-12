"""Ledger read endpoints and the test-driving logical clock."""
import db
import domain
from domain import ledger_json, sort_entities
from envelope import success
from errors import ApiError
from routes.common import require_roles, body, req_str, paginate, get_or_404
from routes.properties import ALL_ROLES, request_arg
from util import parse_date


def list_ledger():
    require_roles(*ALL_ROLES)
    pid = request_arg("property_id")
    wid = request_arg("write_down_id")
    cid = request_arg("closing_statement_id")
    etype = request_arg("entry_type")
    items = [e for e in db.ledger.values()
             if (pid is None or e["property_id"] == pid)
             and (wid is None or e["write_down_id"] == wid)
             and (cid is None or e["closing_statement_id"] == cid)
             and (etype is None or e["entry_type"] == etype)]
    return paginate(sort_entities(items), ledger_json)


def get_ledger_entry(entity_id):
    require_roles(*ALL_ROLES)
    return success(ledger_json(get_or_404(db.ledger, entity_id, "Ledger entry")))


def set_clock():
    require_roles("OREOAdmin")
    d = body()
    raw = req_str(d, "to_iso8601")
    try:
        new_clock, _ = parse_date(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be an ISO 8601 instant")
    db.clock = new_clock
    domain.run_clock_sweep()
    return success({}, 200, "object")
