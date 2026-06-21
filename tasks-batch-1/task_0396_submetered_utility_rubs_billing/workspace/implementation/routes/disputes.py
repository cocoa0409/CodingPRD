"""Disputes: open, review (re-read cascade), resolve, reject, reopen (PRD §3.11)."""

from flask import Blueprint, request, g

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize,
    pagination_params, paginate, sort_by_creation,
)
from services.calculations import recompute_statement_totals, MAX_REOPENS

disputes_bp = Blueprint("disputes", __name__)

VALID_REASONS = {"HIGH_READING", "WRONG_METER", "RATIO_ERROR", "DOUBLE_BILLED"}


def _statement_lease(stmt):
    return db.leases.get(stmt["lease_id"])


def _statement_meter_and_period(stmt):
    """Resolve the (meter, period_label) the statement's reads belong to.

    The statement -> billing_cycle gives property+utility+period; the
    statement's unit gives the assigned meter of that utility.
    """
    cycle = db.billing_cycles.get(stmt["billing_cycle_id"])
    if cycle is None:
        return None, None
    period_label = cycle["period_label"]
    utility_id = cycle["utility_id"]
    unit_id = stmt["unit_id"]
    for meter in db.meters.values():
        if (meter["assigned_unit_id"] == unit_id
                and meter["utility_id"] == utility_id
                and meter["property_id"] == stmt["property_id"]):
            return meter, period_label
    return None, period_label


@disputes_bp.route("/statements/<statement_id>/disputes", methods=["POST"])
@require_roles("Tenant", "PropertyManager")
def open_dispute(statement_id):
    stmt = db.tenant_statements.get(statement_id)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", "TenantStatement not found")

    # Tenant ownership (priority 4).
    if g.user_role == "Tenant":
        lease = _statement_lease(stmt)
        if lease is None or lease["tenant_user_id"] != g.user_id:
            raise ApiError("ERR_NOT_STATEMENT_OWNER", "Tenant does not own this statement")

    body = get_json_body()
    require_fields(body, "reason")
    reason = body["reason"]
    if reason not in VALID_REASONS:
        raise ApiError("ERR_INVALID_REQUEST", "reason must be a valid dispute reason")

    requested_re_read = body.get("requested_re_read", False)
    if not isinstance(requested_re_read, bool):
        raise ApiError("ERR_INVALID_REQUEST", "requested_re_read must be a boolean")

    credit_amount_cents = body.get("credit_amount_cents", 0)
    if (not isinstance(credit_amount_cents, int) or isinstance(credit_amount_cents, bool)
            or credit_amount_cents < 0):
        raise ApiError("ERR_INVALID_REQUEST", "credit_amount_cents must be >= 0")

    dispute = {
        "statement_id": statement_id,
        "property_id": stmt["property_id"],
        "tenant_user_id": g.user_id,
        "reason": reason,
        "requested_re_read": requested_re_read,
        "credit_amount_cents": credit_amount_cents,
        "reopen_count": 0,
        "status": "OPEN",
        # internal: credit actually granted by the most recent resolve.
        "_granted_credit": 0,
    }
    db.stamp_create(dispute)
    db.disputes[dispute["id"]] = dispute
    return success(serialize(dispute), status=201)


@disputes_bp.route("/disputes/<dispute_id>", methods=["GET"])
@require_roles("PropertyManager", "Tenant", "Auditor")
def get_dispute(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found")
    if g.user_role == "Tenant":
        stmt = db.tenant_statements.get(dispute["statement_id"])
        lease = _statement_lease(stmt) if stmt else None
        if lease is None or lease["tenant_user_id"] != g.user_id:
            raise ApiError("ERR_NOT_STATEMENT_OWNER", "Tenant does not own this dispute")
    return success(serialize(dispute), status=200)


@disputes_bp.route("/disputes", methods=["GET"])
@require_roles("PropertyManager", "Tenant", "Auditor")
def list_disputes():
    statement_id = request.args.get("statement_id")
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    items = list(db.disputes.values())
    if statement_id is not None:
        items = [d for d in items if d["statement_id"] == statement_id]
    if property_id is not None:
        items = [d for d in items if d["property_id"] == property_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]

    if g.user_role == "Tenant":
        items = [d for d in items if d["tenant_user_id"] == g.user_id]

    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(d) for d in page], limit, offset, total)


@disputes_bp.route("/disputes/<dispute_id>/start-review", methods=["POST"])
@require_roles("PropertyManager")
def start_review(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found")
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Dispute is not OPEN")

    dispute["status"] = "UNDER_REVIEW"
    db.touch(dispute)

    # Re-read cascade.
    if dispute["requested_re_read"]:
        stmt = db.tenant_statements.get(dispute["statement_id"])
        meter, period_label = _statement_meter_and_period(stmt)
        if meter is not None:
            # Latest VALIDATED read for meter+period -> SUPERSEDED.
            validated = [r for r in db.meter_reads.values()
                         if r["meter_id"] == meter["id"]
                         and r["period_label"] == period_label
                         and r["status"] == "VALIDATED"]
            if validated:
                latest = max(validated, key=lambda r: r["_seq"])
                latest["status"] = "SUPERSEDED"
                db.touch(latest)
            # Fresh RE_READ_REQUESTED read row.
            fresh = {
                "meter_id": meter["id"],
                "property_id": meter["property_id"],
                "period_label": period_label,
                "reading_value": 0,
                "consumption": 0,
                "re_read_count": 1,
                "flag_reason": None,
                "status": "RE_READ_REQUESTED",
            }
            db.stamp_create(fresh)
            db.meter_reads[fresh["id"]] = fresh

    return success(serialize(dispute), status=200)


@disputes_bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
@require_roles("PropertyManager")
def resolve_dispute(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found")

    body = get_json_body()
    credit = body.get("credit_amount_cents", dispute["credit_amount_cents"])
    if (not isinstance(credit, int) or isinstance(credit, bool) or credit < 0):
        raise ApiError("ERR_INVALID_REQUEST", "credit_amount_cents must be >= 0")

    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW")

    stmt = db.tenant_statements.get(dispute["statement_id"])
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", "TenantStatement not found")

    if credit > stmt["total_due_cents"]:
        raise ApiError("ERR_CREDIT_EXCEEDS_DUE", "Credit exceeds statement total due")

    dispute["credit_amount_cents"] = credit
    dispute["_granted_credit"] = credit
    dispute["status"] = "RESOLVED"
    db.touch(dispute)

    # Apply credit to the statement.
    stmt["credit_cents"] += credit
    recompute_statement_totals(stmt)
    if stmt["balance_due_cents"] <= 0:
        stmt["payment_status"] = "PAID"
    db.touch(stmt)

    return success(serialize(dispute), status=200)


@disputes_bp.route("/disputes/<dispute_id>/reject", methods=["POST"])
@require_roles("PropertyManager")
def reject_dispute(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found")
    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW")
    dispute["status"] = "REJECTED"
    db.touch(dispute)
    return success(serialize(dispute), status=200)


@disputes_bp.route("/disputes/<dispute_id>/reopen", methods=["POST"])
@require_roles("Tenant", "PropertyManager")
def reopen_dispute(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found")

    # Tenant ownership (priority 4).
    if g.user_role == "Tenant" and dispute["tenant_user_id"] != g.user_id:
        # Also accept if the lease behind the statement is owned by the tenant.
        stmt = db.tenant_statements.get(dispute["statement_id"])
        lease = _statement_lease(stmt) if stmt else None
        if lease is None or lease["tenant_user_id"] != g.user_id:
            raise ApiError("ERR_NOT_STATEMENT_OWNER", "Tenant does not own this dispute")

    if dispute["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", "Dispute is not RESOLVED")

    stmt = db.tenant_statements.get(dispute["statement_id"])
    cycle = db.billing_cycles.get(stmt["billing_cycle_id"]) if stmt else None
    if cycle is not None and cycle["status"] == "CLOSED":
        raise ApiError("ERR_CYCLE_CLOSED", "Parent billing cycle is closed")

    if dispute["reopen_count"] >= MAX_REOPENS:
        raise ApiError("ERR_MAX_REOPENS_REACHED", "Max reopens reached")

    dispute["reopen_count"] += 1
    dispute["status"] = "UNDER_REVIEW"
    db.touch(dispute)

    # Reverse the previously granted credit (compensation).
    granted = dispute.get("_granted_credit", 0)
    if stmt is not None and granted:
        stmt["credit_cents"] -= granted
        recompute_statement_totals(stmt)
        # Recompute payment_status based on restored balance.
        if stmt["amount_paid_cents"] <= 0:
            stmt["payment_status"] = "UNPAID"
        elif stmt["balance_due_cents"] <= 0:
            stmt["payment_status"] = "PAID"
        else:
            stmt["payment_status"] = "PARTIALLY_PAID"
        db.touch(stmt)
        dispute["_granted_credit"] = 0

    return success(serialize(dispute), status=200)
