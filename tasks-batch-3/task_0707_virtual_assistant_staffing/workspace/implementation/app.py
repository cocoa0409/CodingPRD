"""VA-Staffing API — entry point + all routes (PRD §4).

In-memory only; the store starts empty on every boot (no seeding). The process
is restarted before every per-test run, wiping all state.
"""
import os

from flask import Flask, request

from db import db, stamp_create, touch
from errors import ApiError, err
from response import ok, ok_list, error_body
from middleware import auth, require_role
from pagination import parse_pagination, order_and_page
from validation import get_json, require_fields
import serialize as S
import services as svc
import ownership as own
import sla as sla_mod
import calculations as calc
from clock import parse_iso, iso

app = Flask(__name__)
app.url_map.strict_slashes = False

PREFIX = "/va-staffing"


# ============================================================================
# Error handling
# ============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    body = error_body(e.error_id, e.message)
    return body, e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = error_body("ERR_NOT_FOUND", "resource not found")
    return body, 404


@app.errorhandler(405)
def handle_405(e):
    body = error_body("ERR_NOT_FOUND", "method not allowed")
    return body, 404


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = error_body("ERR_INVALID_REQUEST", "unexpected error")
    return body, 422


# ============================================================================
# Fetch-or-404 helpers (priority 3: path existence, left-to-right)
# ============================================================================
def _get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return rec


def get_client(cid):
    return _get_or_404(db.clients, cid)


def get_va(vid):
    return _get_or_404(db.virtual_assistants, vid)


def get_engagement(eid):
    return _get_or_404(db.engagements, eid)


def get_cycle(cid):
    return _get_or_404(db.retainer_cycles, cid)


def get_task(tid):
    return _get_or_404(db.tasks, tid)


def get_entry(eid):
    return _get_or_404(db.time_entries, eid)


def get_addon(aid):
    return _get_or_404(db.addons, aid)


def get_escalation(eid):
    return _get_or_404(db.escalations, eid)


def get_invoice(iid):
    return _get_or_404(db.invoices, iid)


def get_skill_tag(sid):
    return _get_or_404(db.skill_tags, sid)


def get_sla_policy(sid):
    return _get_or_404(db.sla_policies, sid)


# ============================================================================
# FK existence (priority 4: ERR_REFERENCED_ENTITY_NOT_FOUND, 422)
# ============================================================================
def fk(coll, rid, label):
    if rid not in coll:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", f"{label} not found")
    return coll[rid]


# ============================================================================
# Range guards (priority 6: ERR_VALIDATION_RANGE)
# ============================================================================
def range_check(cond, msg):
    if not cond:
        raise err("ERR_VALIDATION_RANGE", msg)


# ----------------------------------------------------------------------------
# Generic list responder
# ----------------------------------------------------------------------------
def list_response(records, serializer):
    limit, offset = parse_pagination()
    page, total = order_and_page(records, limit, offset)
    return ok_list([serializer(r) for r in page], limit, offset, total)


from routes_config import register_config_routes
from routes_clients import register_client_routes
from routes_engagements import register_engagement_routes
from routes_tasks import register_task_routes
from routes_time import register_time_routes
from routes_cycles import register_cycle_routes
from routes_escalations import register_escalation_routes
from routes_invoices import register_invoice_routes

# Shared context handed to route modules.
ctx = {
    "app": app, "PREFIX": PREFIX,
    "db": db, "stamp_create": stamp_create, "touch": touch,
    "err": err, "ok": ok, "ok_list": ok_list,
    "auth": auth, "require_role": require_role,
    "get_json": get_json, "require_fields": require_fields,
    "parse_pagination": parse_pagination, "order_and_page": order_and_page,
    "list_response": list_response,
    "S": S, "svc": svc, "own": own, "sla_mod": sla_mod, "calc": calc,
    "fk": fk, "range_check": range_check,
    "get_client": get_client, "get_va": get_va, "get_engagement": get_engagement,
    "get_cycle": get_cycle, "get_task": get_task, "get_entry": get_entry,
    "get_addon": get_addon, "get_escalation": get_escalation,
    "get_invoice": get_invoice, "get_skill_tag": get_skill_tag,
    "get_sla_policy": get_sla_policy,
    "parse_iso": parse_iso, "iso": iso,
}

register_config_routes(ctx)
register_client_routes(ctx)
register_engagement_routes(ctx)
register_task_routes(ctx)
register_time_routes(ctx)
register_cycle_routes(ctx)
register_escalation_routes(ctx)
register_invoice_routes(ctx)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
