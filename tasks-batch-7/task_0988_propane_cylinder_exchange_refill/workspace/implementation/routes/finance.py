"""Commission statements and daily reconciliation sessions."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_VALIDATION, ERR_FORBIDDEN, ERR_PERIOD_NOT_CLOSED,
    ERR_RECONCILIATION_UNRESOLVED, ERR_SESSION_EXISTS,
    ERR_IDEMPOTENCY_CONFLICT, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import get_actor, require_roles
from response import success_object, success_list
from services import core
from util import body, req_str, opt_str, req_int, req_date, paginate, sorted_by_creation

bp = Blueprint("finance", __name__)

STMT_ROLES = ("PlatformAdmin", "HostSiteManager")
SESSION_READ_ROLES = ("SiteClerk", "PlatformAdmin", "ComplianceOfficer")


def _get_statement(statement_id):
    s = db.commission_statements.get(statement_id)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Commission statement not found")
    return s


def _get_session(session_id):
    s = db.recon_sessions.get(session_id)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Reconciliation session not found")
    return s


def _dates_in_range(start, end):
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end, "%Y-%m-%d").date()
    out = []
    d = d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Commission statements
# ---------------------------------------------------------------------------

@bp.route("/commission-statements", methods=["POST"])
def create_statement():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    b = body()
    site_id = req_str(b, "site_id")
    period_start = req_date(b, "period_start")
    period_end = req_date(b, "period_end")
    if period_end < period_start:
        raise ApiError(ERR_VALIDATION, 400, "period_end must be on or after period_start")
    if len(_dates_in_range(period_start, period_end)) > core.MAX_STATEMENT_PERIOD_DAYS:
        raise ApiError(ERR_VALIDATION, 400, "Period length exceeds 62 days")
    site = db.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "site_id does not reference an existing site")

    stmt = db.new_entity({
        "site_id": site_id,
        "period_start": period_start,
        "period_end": period_end,
        "basis_used": site["commission_basis"],
        "gross_sales_cents": None,
        "refunds_cents": None,
        "base_cents": None,
        "commission_cents": None,
        "leak_count": None,
        "leak_deduction_cents": None,
        "net_payable_cents": None,
        "finalized_on": None,
        "paid_on": None,
        "dispute_note": None,
        "status": "DRAFT",
    })
    db.commission_statements[stmt["id"]] = stmt
    return success_object(core.serialize(stmt), 201)


@bp.route("/commission-statements/<statementId>", methods=["GET"])
def get_statement(statementId):
    uid, role = get_actor()
    require_roles(role, STMT_ROLES)
    s = _get_statement(statementId)
    if role == "HostSiteManager" and s["site_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "Host-site manager may only read own site's statements")
    return success_object(core.serialize(s))


@bp.route("/commission-statements", methods=["GET"])
def list_statements():
    uid, role = get_actor()
    require_roles(role, STMT_ROLES)
    items = list(db.commission_statements.values())
    if role == "HostSiteManager":
        items = [s for s in items if s["site_id"] == uid]
    for param in ("site_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[param] == v]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize(s) for s in page], total, limit, offset)


def _compute_settlement(stmt, site):
    """commission_settlement: per-sale rounded half-up, then summed; sale_seq order."""
    start, end = stmt["period_start"], stmt["period_end"]
    sales = []
    for o in db.exchange_orders.values():
        if (
            o["site_id"] == stmt["site_id"]
            and o["status"] in ("COMPLETED", "REFUNDED")
            and o["business_date"] is not None
            and start <= o["business_date"] <= end
        ):
            sales.append((o["sale_seq"], o["total_cents"], o["status"], o["refunded_on"], o["_created_seq"], "X"))
    for t in db.refill_tickets.values():
        if (
            t["site_id"] == stmt["site_id"]
            and t["status"] == "CLOSED"
            and t["business_date"] is not None
            and start <= t["business_date"] <= end
        ):
            sales.append((t["sale_seq"], t["total_cents"], "CLOSED", None, t["_created_seq"], "R"))
    sales.sort(key=lambda s: (s[0], s[4]))

    gross = sum(s[1] for s in sales)
    refunds = sum(
        s[1] for s in sales
        if s[2] == "REFUNDED" and s[3] is not None and start <= s[3] <= end
    )
    if stmt["basis_used"] == "GROSS":
        base_set = sales
        base_cents = gross
    else:
        base_set = [
            s for s in sales
            if not (s[2] == "REFUNDED" and s[3] is not None and start <= s[3] <= end)
        ]
        base_cents = gross - refunds

    rate = site["commission_rate_bps"]
    threshold = site["commission_tier_threshold_cents"]
    bonus = site["commission_tier2_bonus_bps"]
    cumulative = 0
    commission = 0
    for _, total, _, _, _, _ in base_set:
        below = max(0, min(cumulative + total, threshold) - cumulative)
        above = total - below
        sale_commission = core_round_commission(below, above, rate, bonus)
        commission += sale_commission
        cumulative += total

    leak_count = 0
    for r in db.leak_reports.values():
        if (
            r["site_id"] == stmt["site_id"]
            and r["status"] in ("CONFIRMED", "RESOLVED")
            and r["confirmed_on"] is not None
            and start <= r["confirmed_on"] <= end
        ):
            leak_count += 1
    leak_deduction = leak_count * core.LEAK_PENALTY_CENTS
    stmt["gross_sales_cents"] = gross
    stmt["refunds_cents"] = refunds
    stmt["base_cents"] = base_cents
    stmt["commission_cents"] = commission
    stmt["leak_count"] = leak_count
    stmt["leak_deduction_cents"] = leak_deduction
    stmt["net_payable_cents"] = max(0, commission - leak_deduction)


def core_round_commission(below, above, rate, bonus):
    raw = (
        Decimal(below) * Decimal(rate) / Decimal(10000)
        + Decimal(above) * Decimal(rate + bonus) / Decimal(10000)
    )
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.route("/commission-statements/<statementId>/finalize", methods=["POST"])
def finalize_statement(statementId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    stmt = _get_statement(statementId)
    if stmt["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT or DISPUTED statement can be finalized")
    # Stage 10: the period must be fully closed.
    if not (stmt["period_end"] < db.current_date()):
        raise ApiError(ERR_PERIOD_NOT_CLOSED, 422, "period_end is not strictly before the current date")
    # Stage 12: every calendar date in the period must be reconciled.
    reconciled_dates = set()
    for s in db.recon_sessions.values():
        if s["site_id"] == stmt["site_id"] and s["status"] in ("BALANCED", "RESOLVED"):
            reconciled_dates.add(s["business_date"])
    for d in _dates_in_range(stmt["period_start"], stmt["period_end"]):
        if d not in reconciled_dates:
            raise ApiError(ERR_RECONCILIATION_UNRESOLVED, 409, "Date %s lacks a BALANCED or RESOLVED session" % d)
    site = db.sites[stmt["site_id"]]
    _compute_settlement(stmt, site)
    stmt["finalized_on"] = db.current_date()
    stmt["status"] = "FINALIZED"
    db.touch(stmt)
    return success_object(core.serialize(stmt))


@bp.route("/commission-statements/<statementId>/dispute", methods=["POST"])
def dispute_statement(statementId):
    uid, role = get_actor()
    require_roles(role, ("HostSiteManager",))
    stmt = _get_statement(statementId)
    if stmt["site_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "Host-site manager may only dispute own site's statements")
    b = body()
    note = req_str(b, "note")
    if stmt["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a FINALIZED statement can be disputed")
    stmt["dispute_note"] = note
    stmt["status"] = "DISPUTED"
    db.touch(stmt)
    return success_object(core.serialize(stmt))


@bp.route("/commission-statements/<statementId>/pay", methods=["POST"])
def pay_statement(statementId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    stmt = _get_statement(statementId)
    if stmt["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a FINALIZED statement can be paid")
    stmt["paid_on"] = db.current_date()
    stmt["status"] = "PAID"
    db.touch(stmt)
    return success_object(core.serialize(stmt))


# ---------------------------------------------------------------------------
# Reconciliation sessions
# ---------------------------------------------------------------------------

@bp.route("/reconciliation-sessions", methods=["POST"])
def create_session():
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    b = body()
    site_id = req_str(b, "site_id")
    business_date = req_date(b, "business_date")
    idem = opt_str(b, "idempotency_key", None)

    site = db.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "site_id does not reference an existing site")
    # Stage 11: idempotent intake (unique per clerk), then (site, business_date) uniqueness.
    if idem is not None:
        for s in db.recon_sessions.values():
            if s["clerk_id"] == uid and s["idempotency_key"] == idem:
                if s["site_id"] == site_id and s["business_date"] == business_date:
                    return success_object(core.serialize(s), 201)
                raise ApiError(ERR_IDEMPOTENCY_CONFLICT, 409, "Idempotency key reused with a different payload")
    if core.find_session(site_id, business_date) is not None:
        raise ApiError(ERR_SESSION_EXISTS, 409, "A session already exists for this site and business_date")

    basis = site["recon_basis"]
    if basis == "BOOK":
        baseline = site["opening_float_cents"]
    else:
        # PHYSICAL: counted cash of the most recent prior BALANCED/RESOLVED session.
        prior = None
        for s in db.recon_sessions.values():
            if (
                s["site_id"] == site_id
                and s["status"] in ("BALANCED", "RESOLVED")
                and s["business_date"] < business_date
                and s["counted_cash_cents"] is not None
            ):
                if prior is None or s["business_date"] > prior["business_date"]:
                    prior = s
        baseline = prior["counted_cash_cents"] if prior is not None else site["opening_float_cents"]

    full, empty, _ = core.cage_counts(site_id)
    session = db.new_entity({
        "site_id": site_id,
        "business_date": business_date,
        "clerk_id": uid,
        "basis": basis,
        "opening_baseline_cents": baseline,
        "expected_cash_cents": None,
        "expected_full_cylinders": full,
        "expected_empty_cylinders": empty,
        "counted_cash_cents": None,
        "counted_full_cylinders": None,
        "counted_empty_cylinders": None,
        "cash_variance_cents": None,
        "full_variance": None,
        "empty_variance": None,
        "escalated_by": None,
        "resolved_by": None,
        "resolution_note": None,
        "idempotency_key": idem,
        "status": "OPEN",
    })
    core.refresh_session_expected(session)
    db.recon_sessions[session["id"]] = session
    return success_object(core.serialize(session), 201)


@bp.route("/reconciliation-sessions/<sessionId>", methods=["GET"])
def get_session(sessionId):
    uid, role = get_actor()
    require_roles(role, SESSION_READ_ROLES)
    return success_object(core.serialize(_get_session(sessionId)))


@bp.route("/reconciliation-sessions", methods=["GET"])
def list_sessions():
    uid, role = get_actor()
    require_roles(role, SESSION_READ_ROLES)
    items = list(db.recon_sessions.values())
    for param in ("site_id", "business_date", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[param] == v]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize(s) for s in page], total, limit, offset)


@bp.route("/reconciliation-sessions/<sessionId>/count", methods=["POST"])
def count_session(sessionId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    s = _get_session(sessionId)
    b = body()
    cash = req_int(b, "counted_cash_cents", min_v=0)
    fulls = req_int(b, "counted_full_cylinders", min_v=0)
    empties = req_int(b, "counted_empty_cylinders", min_v=0)
    if s["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN session accepts a count")
    core.refresh_session_expected(s)
    s["counted_cash_cents"] = cash
    s["counted_full_cylinders"] = fulls
    s["counted_empty_cylinders"] = empties
    s["cash_variance_cents"] = cash - s["expected_cash_cents"]
    s["full_variance"] = fulls - s["expected_full_cylinders"]
    s["empty_variance"] = empties - s["expected_empty_cylinders"]
    # Inclusive threshold: exactly 500 cents of cash variance flags the session.
    if (
        abs(s["cash_variance_cents"]) < core.VARIANCE_TOLERANCE_CENTS
        and s["full_variance"] == 0
        and s["empty_variance"] == 0
    ):
        s["status"] = "BALANCED"
    else:
        s["status"] = "VARIANCE_FLAGGED"
    db.touch(s)
    return success_object(core.serialize(s))


@bp.route("/reconciliation-sessions/<sessionId>/recount", methods=["POST"])
def recount_session(sessionId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    s = _get_session(sessionId)
    if s["status"] != "VARIANCE_FLAGGED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a VARIANCE_FLAGGED session can be recounted")
    s["counted_cash_cents"] = None
    s["counted_full_cylinders"] = None
    s["counted_empty_cylinders"] = None
    s["cash_variance_cents"] = None
    s["full_variance"] = None
    s["empty_variance"] = None
    core.refresh_session_expected(s)
    s["status"] = "OPEN"
    db.touch(s)
    return success_object(core.serialize(s))


@bp.route("/reconciliation-sessions/<sessionId>/escalate", methods=["POST"])
def escalate_session(sessionId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "ComplianceOfficer"))
    s = _get_session(sessionId)
    if s["status"] != "VARIANCE_FLAGGED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a VARIANCE_FLAGGED session can be escalated")
    s["escalated_by"] = uid
    s["status"] = "ESCALATED"
    db.touch(s)
    return success_object(core.serialize(s))


@bp.route("/reconciliation-sessions/<sessionId>/resolve", methods=["POST"])
def resolve_session(sessionId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "ComplianceOfficer"))
    s = _get_session(sessionId)
    b = body()
    note = req_str(b, "resolution_note")
    if s["status"] != "ESCALATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ESCALATED session can be resolved")
    # Stage 14: segregation of duties.
    if uid == s["clerk_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Resolver must differ from the shift clerk")
    s["resolved_by"] = uid
    s["resolution_note"] = note
    s["status"] = "RESOLVED"
    db.touch(s)
    return success_object(core.serialize(s))
