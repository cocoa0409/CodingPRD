"""CommissionStatement endpoints (PRD 3.7): open, list, get, finalize."""
from flask import Blueprint, request

from common import get_json_body, get_or_404, list_response, require_str
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize
from services.commission import recompute_amounts, host_machine_ids
from services.timeutil import parse_iso, periods_overlap, in_period

bp = Blueprint("statements", __name__)

READ_ROLES = ("FieldOps", "HostManager", "FinanceClerk")


@bp.route("/operations/commission-statements", methods=["POST"])
@require_roles("FinanceClerk")
def open_statement():
    body = get_json_body()
    host_site_id = require_str(body, "host_site_id")
    period_start_raw = require_str(body, "period_start")
    period_end_raw = require_str(body, "period_end")
    start_dt = parse_iso(period_start_raw, "period_start")
    end_dt = parse_iso(period_end_raw, "period_end")
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_REQUEST", "period_end must be after period_start")

    # FK existence (priority 4)
    host = db.host_sites.get(host_site_id)
    if host is None:
        raise ApiError("ERR_HOST_SITE_NOT_FOUND", "Host site not found")

    # business_temporal (priority 10): no overlapping statement for the same host
    for s in db.statements.values():
        if s["host_site_id"] != host_site_id:
            continue
        if periods_overlap(start_dt, end_dt,
                           parse_iso(s["period_start"]), parse_iso(s["period_end"])):
            raise ApiError("ERR_STATEMENT_PERIOD_OVERLAP",
                           "Statement period overlaps an existing statement for this host")

    # business_constraint (priority 11): host must be ACTIVE
    if host["status"] == "SUSPENDED":
        raise ApiError("ERR_HOST_SUSPENDED", "Cannot open a statement for a suspended host")

    obj = {
        "host_site_id": host_site_id,
        "period_start": period_start_raw,
        "period_end": period_end_raw,
        "gross_sales_cents": 0,
        "shrink_chargeback_cents": 0,
        "gross_commission_cents": 0,
        "net_commission_cents": 0,
        "status": "OPEN",
    }
    stamp_create(obj)
    recompute_amounts(obj)
    db.statements[obj["id"]] = obj
    return object_response(serialize.statement(obj), 201)


@bp.route("/operations/commission-statements", methods=["GET"])
@require_roles(*READ_ROLES)
def list_statements():
    rows = list(db.statements.values())
    host_site_id = request.args.get("host_site_id")
    if host_site_id is not None:
        rows = [s for s in rows if s["host_site_id"] == host_site_id]
    return list_response(rows, serialize.statement)


@bp.route("/operations/commission-statements/<statement_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_statement(statement_id):
    obj = get_or_404("statements", statement_id)
    return object_response(serialize.statement(obj))


@bp.route("/operations/commission-statements/<statement_id>/finalize", methods=["POST"])
@require_roles("FinanceClerk")
def finalize_statement(statement_id):
    statement = get_or_404("statements", statement_id)

    # state (priority 5): must be OPEN
    if statement["status"] != "OPEN":
        raise ApiError("ERR_STATEMENT_NOT_OPEN", "Statement is not OPEN")

    # business: no DRAFT visit on this host's machines within the period
    start_dt = parse_iso(statement["period_start"])
    end_dt = parse_iso(statement["period_end"])
    machine_ids = host_machine_ids(statement["host_site_id"])
    for v in db.visits.values():
        if v["status"] != "DRAFT":
            continue
        if v["machine_id"] not in machine_ids:
            continue
        # A DRAFT visit has no reconcile time; PRD: "no restock visit on this host's
        # machines within the period still be in DRAFT". Use the visit's created_at
        # as its presence-in-period marker.
        if in_period(v["created_at"], start_dt, end_dt):
            raise ApiError("ERR_VISITS_PENDING", "A DRAFT visit is pending in this period")

    # recompute and freeze amounts
    recompute_amounts(statement)

    # ledger sync: host lifetime balance += net_commission
    host = db.host_sites.get(statement["host_site_id"])
    if host is not None:
        host["lifetime_commission_cents"] += statement["net_commission_cents"]
        touch(host)

    statement["status"] = "FINALIZED"
    touch(statement)
    return object_response(serialize.statement(statement))
