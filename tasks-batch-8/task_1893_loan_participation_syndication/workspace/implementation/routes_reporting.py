"""Financial statements and reporting packages."""
from datetime import timedelta

from flask import Blueprint

import errors
from auth import require_roles, body, req_str, req_enum, req_date
from domain import get_or_404, paginate, apply_filters
from responses import ok, ok_list
from store import db, new_entity, touch, now_ts, today, parse_date
from calc import facility_participants

bp = Blueprint("reporting", __name__, url_prefix="/api")

READ_ROLES = ("AgentBank", "Borrower", "ParticipantLender")
STATEMENT_TYPES = ("QUARTERLY", "ANNUAL_AUDITED")
DUE_DAYS = {"QUARTERLY": 45, "ANNUAL_AUDITED": 90}


def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# financial statements
# ---------------------------------------------------------------------------

@bp.post("/financial_statements")
@require_roles("Borrower")
def statement_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    fac = db["facilities"].get(facility_id)
    if fac is None:
        raise errors.not_found("facility_id does not resolve")
    stype = req_enum(data, "statement_type", STATEMENT_TYPES)
    period_raw, period_d = req_date(data, "period_end_date")
    doc_ref = req_str(data, "document_ref")
    for s in db["statements"].values():
        if (
            s["facility_id"] == fac["id"]
            and s["statement_type"] == stype
            and s["period_end_date"] == period_raw
            and s["status"] != "WAIVED"
        ):
            raise errors.duplicate_statement()
    due = (period_d + timedelta(days=DUE_DAYS[stype])).isoformat()
    ent = new_entity()
    ent.update(
        {
            "facility_id": fac["id"],
            "borrower_id": fac["borrower_id"],
            "statement_type": stype,
            "period_end_date": period_raw,
            "document_ref": doc_ref,
            "due_date": due,
            "received_at": None,
            "status": "EXPECTED",
        }
    )
    db["statements"][ent["id"]] = ent
    return ok(pub(ent), 201)


@bp.get("/financial_statements/<statementId>")
@require_roles(*READ_ROLES)
def statement_get(uid, role, statementId):
    return ok(pub(get_or_404("statements", statementId)))


@bp.get("/financial_statements")
@require_roles(*READ_ROLES)
def statement_list(uid, role):
    items = apply_filters(
        list(db["statements"].values()),
        [("facility_id", "facility_id"), ("borrower_id", "borrower_id"), ("status", "status")],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/financial_statements/<statementId>/receive")
@require_roles("AgentBank")
def statement_receive(uid, role, statementId):
    s = get_or_404("statements", statementId)
    if s["status"] != "EXPECTED":
        raise errors.invalid_state("Only an EXPECTED statement can be received")
    s["received_at"] = now_ts()
    s["status"] = "RECEIVED" if today() <= parse_date(s["due_date"]) else "LATE_RECEIVED"
    touch(s)
    return ok(pub(s))


@bp.post("/financial_statements/<statementId>/waive")
@require_roles("AgentBank")
def statement_waive(uid, role, statementId):
    s = get_or_404("statements", statementId)
    if s["status"] != "EXPECTED":
        raise errors.invalid_state("Only an EXPECTED statement can be waived")
    s["status"] = "WAIVED"
    touch(s)
    return ok(pub(s))


# ---------------------------------------------------------------------------
# reporting packages
# ---------------------------------------------------------------------------

@bp.post("/reporting_packages")
@require_roles("AgentBank")
def package_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    fac = db["facilities"].get(facility_id)
    if fac is None:
        raise errors.not_found("facility_id does not resolve")
    label = req_str(data, "period_label")
    start_raw, start_d = req_date(data, "period_start_date")
    end_raw, end_d = req_date(data, "period_end_date")
    if end_d < start_d:
        raise errors.invalid_request("period_end_date must be on or after period_start_date")
    due_raw, _dd = req_date(data, "due_date")
    stmt_id = data.get("financial_statement_id")
    if stmt_id is not None:
        if not isinstance(stmt_id, str) or not stmt_id.strip():
            raise errors.invalid_request("financial_statement_id must be a string")
        if db["statements"].get(stmt_id) is None:
            raise errors.not_found("financial_statement_id does not resolve")
    # closed-interval overlap on the same facility: adjacency collides
    for pkg in db["packages"].values():
        if pkg["facility_id"] != fac["id"]:
            continue
        p_start = parse_date(pkg["period_start_date"])
        p_end = parse_date(pkg["period_end_date"])
        if start_d <= p_end and p_start <= end_d:
            raise errors.package_window_overlap()
    ent = new_entity()
    ent.update(
        {
            "facility_id": fac["id"],
            "period_label": label,
            "period_start_date": start_raw,
            "period_end_date": end_raw,
            "due_date": due_raw,
            "financial_statement_id": stmt_id,
            "status": "OPEN",
            "delivered_recipient_count": None,
            "delivered_at": None,
        }
    )
    db["packages"][ent["id"]] = ent
    return ok(pub(ent), 201)


@bp.get("/reporting_packages/<packageId>")
@require_roles(*READ_ROLES)
def package_get(uid, role, packageId):
    return ok(pub(get_or_404("packages", packageId)))


@bp.get("/reporting_packages")
@require_roles(*READ_ROLES)
def package_list(uid, role):
    items = apply_filters(
        list(db["packages"].values()),
        [
            ("facility_id", "facility_id"),
            ("financial_statement_id", "financial_statement_id"),
            ("status", "status"),
        ],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/reporting_packages/<packageId>/assemble")
@require_roles("AgentBank")
def package_assemble(uid, role, packageId):
    pkg = get_or_404("packages", packageId)
    if pkg["status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN package can be assembled")
    stmt_id = pkg.get("financial_statement_id")
    if stmt_id is not None:
        s = db["statements"].get(stmt_id)
        if (
            s is None
            or s["facility_id"] != pkg["facility_id"]
            or s["status"] not in ("RECEIVED", "LATE_RECEIVED")
        ):
            raise errors.statement_not_received()
    pkg["status"] = "ASSEMBLED"
    touch(pkg)
    return ok(pub(pkg))


@bp.post("/reporting_packages/<packageId>/deliver")
@require_roles("AgentBank")
def package_deliver(uid, role, packageId):
    pkg = get_or_404("packages", packageId)
    if pkg["status"] != "ASSEMBLED":
        raise errors.invalid_state("Only an ASSEMBLED package can be delivered")
    on_time = today() <= parse_date(pkg["due_date"])
    pkg["status"] = "DELIVERED" if on_time else "LATE_DELIVERED"
    pkg["delivered_at"] = now_ts()
    pkg["delivered_recipient_count"] = sum(
        1
        for p in facility_participants(pkg["facility_id"])
        if p["status"] in ("COMMITTED", "FUNDED")
    )
    touch(pkg)
    return ok(pub(pkg))
