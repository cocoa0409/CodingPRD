"""Lease endpoints (PRD 3.1, 3.9): creation in DRAFT, ACTIVATE with half-open
term-overlap rejection, MOVE_OUT running Cascade B, and the computed ledger
read with both reconciliation variants."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V
from services import calc, workflows

bp = Blueprint("leases", __name__)

WRITE_ROLES = {"LeasingAgent", "PropertyManager"}

LEASE_FIELDS = {
    "property_id", "primary_tenant_id", "unit_label", "monthly_rent_cents",
    "due_day", "grace_period_days", "late_fee_type", "late_fee_flat_cents",
    "late_fee_percent_bps", "late_fee_daily_cents", "term_start_date",
    "term_end_date",
}


def get_lease_or_404(lease_id):
    lease = db.leases.get(lease_id)
    if lease is None:
        errors.fail(errors.ERR_NOT_FOUND, "Lease %s does not exist." % lease_id)
    return lease


def _tenant_scope_list(user_id, rows):
    """Tenant callers see only their own lease graph (PRD 2.1)."""
    return [l for l in rows if l["primary_tenant_id"] == user_id]


@bp.post("/leases")
def create_lease():
    _uid, role = middleware.current_user()
    middleware.require_role(role, WRITE_ROLES)
    data = V.json_body()
    V.check_unknown(data, LEASE_FIELDS)
    property_id = V.req_str(data, "property_id")
    primary_tenant_id = V.req_str(data, "primary_tenant_id")
    unit_label = V.req_str(data, "unit_label")
    monthly_rent_cents = V.req_int(data, "monthly_rent_cents")
    due_day = V.req_int(data, "due_day")
    grace_period_days = V.req_int(data, "grace_period_days")
    late_fee_type = V.req_enum(data, "late_fee_type", {"FLAT", "PERCENT_PLUS_DAILY"})
    late_fee_flat_cents = V.opt_int(data, "late_fee_flat_cents", 0)
    late_fee_percent_bps = V.opt_int(data, "late_fee_percent_bps", 0)
    late_fee_daily_cents = V.opt_int(data, "late_fee_daily_cents", 0)
    term_start = V.req_date(data, "term_start_date")
    term_end = V.req_date(data, "term_end_date")
    # Tier 4: body FK references must exist.
    if property_id not in db.properties:
        errors.fail(errors.ERR_NOT_FOUND, "Property %s does not exist." % property_id)
    if primary_tenant_id not in db.tenants:
        errors.fail(errors.ERR_NOT_FOUND, "Tenant %s does not exist." % primary_tenant_id)
    # Tier 10: date coherence and declared constraints.
    if not 1 <= due_day <= 28:
        errors.fail(errors.ERR_INVALID_REQUEST, "due_day must be an integer from 1 to 28.")
    if term_start >= term_end:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "term_start_date must be strictly before term_end_date.",
        )
    lease = db.init_common({
        "property_id": property_id,
        "primary_tenant_id": primary_tenant_id,
        "unit_label": unit_label,
        "monthly_rent_cents": monthly_rent_cents,
        "due_day": due_day,
        "grace_period_days": grace_period_days,
        "late_fee_type": late_fee_type,
        "late_fee_flat_cents": late_fee_flat_cents,
        "late_fee_percent_bps": late_fee_percent_bps,
        "late_fee_daily_cents": late_fee_daily_cents,
        "term_start_date": term_start.isoformat(),
        "term_end_date": term_end.isoformat(),
        "status": "DRAFT",
        "move_out_date": None,
    })
    db.leases[lease["id"]] = lease
    return response.success_object(serializers.lease_view(lease), 201)


@bp.get("/leases/<lease_id>")
def get_lease(lease_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    lease = get_lease_or_404(lease_id)
    if role == "Tenant":
        middleware.require_owns_lease(uid, lease)
    return response.success_object(serializers.lease_view(lease))


@bp.get("/leases")
def list_leases():
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    rows = list(db.leases.values())
    if role == "Tenant":
        rows = _tenant_scope_list(uid, rows)
    page, limit, offset, total = V.sorted_page(rows, [
        ("property_id", V.query_filter("property_id")),
        ("primary_tenant_id", V.query_filter("primary_tenant_id")),
        ("status", V.query_filter("status")),
    ])
    return response.success_list(
        [serializers.lease_view(l) for l in page], limit, offset, total
    )


@bp.post("/leases/<lease_id>/transition")
def transition_lease(lease_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, middleware.PM)
    lease = get_lease_or_404(lease_id)
    data = V.json_body()
    V.check_unknown(data, {"action", "move_out_date"})
    action = V.req_enum(data, "action", {"ACTIVATE", "MOVE_OUT"})
    today = db.clock_date()

    if action == "ACTIVATE":
        # Misused transitions are domain errors: ACTIVATE from non-DRAFT is
        # ERR_INVALID_REQUEST.
        if lease["status"] != "DRAFT":
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "ACTIVATE requires a lease in DRAFT status.",
            )
        if calc.parse_d(lease["term_end_date"]) <= today:
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "The lease term has already ended (term_end_date is not in the future).",
            )
        # Half-open term overlap on the same (property_id, unit_label) against
        # ACTIVE leases; adjacency (end == start) is not a conflict.
        start = calc.parse_d(lease["term_start_date"])
        end = calc.parse_d(lease["term_end_date"])
        for other in db.leases.values():
            if (
                other["id"] != lease["id"]
                and other["property_id"] == lease["property_id"]
                and other["unit_label"] == lease["unit_label"]
                and other["status"] == "ACTIVE"
                and start < calc.parse_d(other["term_end_date"])
                and calc.parse_d(other["term_start_date"]) < end
            ):
                errors.fail(
                    errors.ERR_LEASE_TERM_OVERLAP,
                    "An ACTIVE lease already covers an overlapping term on this unit.",
                )
        lease["status"] = "ACTIVE"
        db.touch(lease)
        return response.success_object(serializers.lease_view(lease))

    # MOVE_OUT
    if lease["status"] == "DRAFT":
        errors.fail(errors.ERR_LEASE_NOT_ACTIVE, "MOVE_OUT requires an ACTIVE lease.")
    if lease["status"] == "ENDED":
        errors.fail(errors.ERR_LEASE_ALREADY_ENDED, "The lease has already ended.")
    move_out_date = V.req_date(data, "move_out_date")
    if move_out_date < calc.parse_d(lease["term_start_date"]) or move_out_date > today:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "move_out_date must be on or after term_start_date and not in the future.",
        )
    workflows.move_out_lease(lease, move_out_date.isoformat())
    return response.success_object(serializers.lease_view(lease))


@bp.get("/leases/<lease_id>/ledger")
def get_lease_ledger(lease_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"PropertyManager", "LeasingAgent"})
    lease = get_lease_or_404(lease_id)
    forward, chronological = calc.move_out_balances(lease)
    live = [c for c in db.charges.values() if c["lease_id"] == lease["id"] and c["status"] != "VOID"]
    data = {
        "forward_balance_cents": forward,
        "chronological_balance_cents": chronological,
        "total_charged_cents": sum(c["amount_cents"] for c in live),
        "total_waived_cents": sum(c["waived_cents"] for c in live),
        "total_applied_net_cents": sum(calc.net_applied_cents(c["id"]) for c in live),
        "total_outstanding_cents": sum(c["outstanding_cents"] for c in live),
        "open_charge_count": sum(1 for c in live if c["status"] in workflows.OPEN_CHARGE_STATES),
    }
    return response.success_object(data)
