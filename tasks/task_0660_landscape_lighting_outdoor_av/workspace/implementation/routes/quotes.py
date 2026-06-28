"""Quote / QuoteLine endpoints (PRD 3.3).

Quote is a cyclic revision loop: DRAFT -> SENT -> DRAFT (revise) and the
terminal branches ACCEPTED / REJECTED / EXPIRED. A SENT quote is valid 14 days
from the last send; expiry is evaluated lazily on read and on accept/reject.
"""

from datetime import timedelta

from flask import Blueprint

from common import (
    get_json_body,
    optional_string,
    paginate,
    require_bool,
    require_fields,
    require_int_ge,
    require_string,
    stamp_new,
    touch,
)
from common import parse_iso8601
from clock import clock
from db import db
from errors import err
from lookups import get_project, get_quote
from middleware import get_auth, require_role
from response import success
from services.calc import quote_pricing
from services.serialize import ser_install_job, ser_quote, ser_quote_line

bp = Blueprint("quotes", __name__)

VALIDITY = timedelta(days=14)


def _lazy_expire(quote):
    """Lazily transition a SENT quote to EXPIRED if the clock has passed 14
    days from the last send (PRD 3.3)."""
    if quote["status"] == "SENT" and quote.get("_sent_at") is not None:
        if clock.now() >= quote["_sent_at"] + VALIDITY:
            quote["status"] = "EXPIRED"
            touch(quote)


@bp.post("/quotes")
def create_quote():
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    body = get_json_body()
    require_fields(body, ["project_id"])
    project_id = require_string(body, "project_id")
    get_project(project_id)
    night_demo_requested = require_bool(body, "night_demo_requested", False)
    night_demo_at = optional_string(body, "night_demo_at", None)
    # Demo time required when requested (priority 15).
    if night_demo_requested and night_demo_at is None:
        raise err(
            "ERR_DEMO_TIME_REQUIRED",
            "night_demo_at is required when night_demo_requested is true.",
        )

    record = stamp_new(
        {
            "project_id": project_id,
            "night_demo_requested": night_demo_requested,
            "night_demo_at": night_demo_at,
            "subtotal_cents": 0,
            "discount_cents": 0,
            "tax_cents": 0,
            "grand_total_cents": 0,
            "revision_round": 0,
            "status": "DRAFT",
        }
    )
    record["_sent_at"] = None
    db.quotes[record["id"]] = record
    return success(ser_quote(record), status=201)


@bp.get("/quotes/<qid>")
def read_quote(qid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner", "Customer", "OperationsAdmin"})
    q = get_quote(qid)
    _lazy_expire(q)
    return success(ser_quote(q), status=200)


@bp.get("/projects/<pid>/quotes")
def list_project_quotes(pid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner", "Customer", "OperationsAdmin"})
    get_project(pid)
    items = [q for q in db.quotes.values() if q["project_id"] == pid]
    data, pagination = paginate(items, ser_quote)
    return success(data, status=200, pagination=pagination)


@bp.post("/quotes/<qid>/lines")
def add_line(qid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    q = get_quote(qid)
    body = get_json_body()
    require_fields(body, ["model_code", "quantity", "unit_price_cents"])
    model_code = require_string(body, "model_code")
    quantity = require_int_ge(body, "quantity", 1)
    unit_price_cents = require_int_ge(body, "unit_price_cents", 0)
    # State (6): lines may only be added while the quote is DRAFT.
    if q["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Lines may only be added to a DRAFT quote.")

    record = stamp_new(
        {
            "quote_id": qid,
            "model_code": model_code,
            "quantity": quantity,
            "unit_price_cents": unit_price_cents,
            "line_total_cents": quantity * unit_price_cents,
        }
    )
    db.quote_lines[record["id"]] = record
    return success(ser_quote_line(record), status=201)


@bp.get("/quotes/<qid>/lines")
def list_lines(qid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner", "Customer", "OperationsAdmin"})
    get_quote(qid)
    items = [l for l in db.quote_lines.values() if l["quote_id"] == qid]
    data, pagination = paginate(items, ser_quote_line)
    return success(data, status=200, pagination=pagination)


@bp.post("/quotes/<qid>/send")
def send_quote(qid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    q = get_quote(qid)
    _lazy_expire(q)
    # State (6): must be DRAFT.
    if q["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Quote is not DRAFT.")
    lines = [l for l in db.quote_lines.values() if l["quote_id"] == qid]
    # Quote must have at least one line.
    if not lines:
        raise err("ERR_QUOTE_NO_LINES", "Quote has no lines.")
    project = db.projects[q["project_id"]]
    # Owning project must be DESIGN_LOCKED.
    if project["design_status"] != "DESIGN_LOCKED":
        raise err("ERR_DESIGN_NOT_LOCKED", "Project design is not locked.")

    # Recompute pricing before SENT.
    subtotal, discount, tax, grand = quote_pricing(lines, q["night_demo_requested"])
    q["subtotal_cents"] = subtotal
    q["discount_cents"] = discount
    q["tax_cents"] = tax
    q["grand_total_cents"] = grand
    q["status"] = "SENT"
    q["_sent_at"] = clock.now()
    touch(q)

    # First send for the project advances commercial_status PRE_QUOTE->QUOTED.
    if project["commercial_status"] == "PRE_QUOTE":
        project["commercial_status"] = "QUOTED"
        touch(project)

    return success(ser_quote(q), status=200)


@bp.post("/quotes/<qid>/revise")
def revise_quote(qid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    q = get_quote(qid)
    _lazy_expire(q)
    if q["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not SENT.")
    q["status"] = "DRAFT"
    q["revision_round"] = q["revision_round"] + 1
    touch(q)
    return success(ser_quote(q), status=200)


@bp.post("/quotes/<qid>/accept")
def accept_quote(qid):
    _, role = get_auth()
    require_role(role, {"Customer"})
    q = get_quote(qid)
    _lazy_expire(q)
    if q["status"] == "EXPIRED":
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired.")
    if q["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not SENT.")
    project = db.projects[q["project_id"]]
    if project["commercial_status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Project is not QUOTED.")

    q["status"] = "ACCEPTED"
    touch(q)
    project["commercial_status"] = "ACCEPTED"
    touch(project)
    # Debit the owning customer's wallet by the grand total.
    customer = db.customers.get(project["customer_id"])
    if customer is not None:
        customer["wallet_credit_cents"] -= q["grand_total_cents"]
        touch(customer)
    return success(ser_quote(q), status=200)


@bp.post("/quotes/<qid>/reject")
def reject_quote(qid):
    _, role = get_auth()
    require_role(role, {"Customer"})
    q = get_quote(qid)
    _lazy_expire(q)
    if q["status"] == "EXPIRED":
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired.")
    if q["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not SENT.")
    q["status"] = "REJECTED"
    touch(q)
    return success(ser_quote(q), status=200)


@bp.get("/quotes/<qid>/install-jobs")
def list_quote_install_jobs(qid):
    _, role = get_auth()
    require_role(role, {"InstallTech", "LightingDesigner", "OperationsAdmin"})
    get_quote(qid)
    items = [j for j in db.install_jobs.values() if j["quote_id"] == qid]
    data, pagination = paginate(items, ser_install_job)
    return success(data, status=200, pagination=pagination)
