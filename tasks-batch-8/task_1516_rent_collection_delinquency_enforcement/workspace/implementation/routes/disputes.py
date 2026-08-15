"""Dispute endpoints (PRD 3.9): Tenant-only filing on their own lease,
PropertyManager-only RESOLVE (UPHELD, or ADJUSTED running Cascade C), and the
single-reopen cycle OPEN -> RESOLVED_UPHELD -> REOPENED -> RESOLVED_*."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V
from services import workflows

bp = Blueprint("disputes", __name__)


def get_dispute_or_404(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        errors.fail(errors.ERR_NOT_FOUND, "Dispute %s does not exist." % dispute_id)
    return dispute


@bp.post("/disputes")
def create_dispute():
    uid, role = middleware.current_user()
    middleware.require_role(role, {"Tenant"})
    data = V.json_body()
    V.check_unknown(data, {"lease_id", "charge_id", "tenant_id", "reason"})
    lease_id = V.req_str(data, "lease_id")
    charge_id = V.req_str(data, "charge_id")
    tenant_id = V.req_str(data, "tenant_id")
    reason = V.req_str(data, "reason")
    # Tier 2 ownership: the filer's X-User-ID must equal the supplied tenant_id.
    if tenant_id != uid:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "A Tenant may file disputes only as themselves.",
        )
    # Tier 4: body FK references must exist.
    lease = db.leases.get(lease_id)
    if lease is None:
        errors.fail(errors.ERR_NOT_FOUND, "Lease %s does not exist." % lease_id)
    charge = db.charges.get(charge_id)
    if charge is None:
        errors.fail(errors.ERR_NOT_FOUND, "Charge %s does not exist." % charge_id)
    if tenant_id not in db.tenants:
        errors.fail(errors.ERR_NOT_FOUND, "Tenant %s does not exist." % tenant_id)
    # Tier 2 ownership, continued: the lease must be the caller's own.
    if lease["primary_tenant_id"] != uid:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "A Tenant may file disputes only on their own lease.",
        )
    # Tier 9: the disputed charge must belong to the named lease.
    if charge["lease_id"] != lease["id"]:
        errors.fail(
            errors.ERR_CHARGE_NOT_ON_LEASE,
            "Charge %s does not belong to lease %s." % (charge["id"], lease["id"]),
        )
    dispute = db.init_common({
        "lease_id": lease["id"],
        "charge_id": charge["id"],
        "tenant_id": tenant_id,
        "reason": reason,
        "status": "OPEN",
        "reopen_count": 0,
        "adjusted_amount_cents": None,
        "resolution_notes": "",
    })
    db.disputes[dispute["id"]] = dispute
    return response.success_object(serializers.dispute_view(dispute), 201)


@bp.get("/disputes/<dispute_id>")
def get_dispute(dispute_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    dispute = get_dispute_or_404(dispute_id)
    if role == "Tenant" and dispute["tenant_id"] != uid:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "A Tenant may read only their own disputes.",
        )
    return response.success_object(serializers.dispute_view(dispute))


@bp.get("/disputes")
def list_disputes():
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    rows = list(db.disputes.values())
    if role == "Tenant":
        rows = [d for d in rows if d["tenant_id"] == uid]
    page, limit, offset, total = V.sorted_page(rows, [
        ("lease_id", V.query_filter("lease_id")),
        ("charge_id", V.query_filter("charge_id")),
        ("tenant_id", V.query_filter("tenant_id")),
        ("status", V.query_filter("status")),
    ])
    return response.success_list(
        [serializers.dispute_view(d) for d in page], limit, offset, total
    )


@bp.post("/disputes/<dispute_id>/transition")
def transition_dispute(dispute_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, {"PropertyManager", "Tenant"})
    dispute = get_dispute_or_404(dispute_id)
    data = V.json_body()
    V.check_unknown(data, {"action", "outcome", "adjusted_amount_cents", "resolution_notes"})
    action = V.req_enum(data, "action", {"RESOLVE", "REOPEN"})

    if action == "RESOLVE":
        # Action-level RBAC: resolution belongs to the PropertyManager alone.
        if role != "PropertyManager":
            errors.fail(
                errors.ERR_UNAUTHORIZED,
                "Only a PropertyManager may resolve a dispute.",
            )
        # Tier 7: resolving is permitted only from OPEN or REOPENED.
        if dispute["status"] not in ("OPEN", "REOPENED"):
            errors.fail(
                errors.ERR_DISPUTE_INVALID_TRANSITION,
                "RESOLVE requires a dispute in OPEN or REOPENED status.",
            )
        outcome = V.req_enum(data, "outcome", {"UPHELD", "ADJUSTED"})
        notes = V.opt_str(data, "resolution_notes", "")
        if outcome == "UPHELD":
            dispute["status"] = "RESOLVED_UPHELD"
            dispute["resolution_notes"] = notes
            db.touch(dispute)
            return response.success_object(serializers.dispute_view(dispute))
        # ADJUSTED — Cascade C. The adjusted amount must accompany the outcome
        # and lie in [0, charge.amount_cents); zero voids the charge.
        charge = db.charges[dispute["charge_id"]]
        adjusted = data.get("adjusted_amount_cents")
        if (
            not isinstance(adjusted, int)
            or isinstance(adjusted, bool)
            or not 0 <= adjusted < charge["amount_cents"]
        ):
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "adjusted_amount_cents is required for outcome ADJUSTED and must lie "
                "in [0, %d)." % charge["amount_cents"],
            )
        dispute["status"] = "RESOLVED_ADJUSTED"
        dispute["adjusted_amount_cents"] = adjusted
        dispute["resolution_notes"] = notes
        db.touch(dispute)
        workflows.apply_dispute_adjustment(dispute, adjusted)
        return response.success_object(serializers.dispute_view(dispute))

    # REOPEN — Tenant-only, by the filing owner, from RESOLVED_UPHELD, once.
    if role != "Tenant":
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "Only a Tenant may reopen a dispute.",
        )
    if dispute["tenant_id"] != uid:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "Only the filing tenant may reopen this dispute.",
        )
    if dispute["status"] != "RESOLVED_UPHELD":
        errors.fail(
            errors.ERR_DISPUTE_INVALID_TRANSITION,
            "REOPEN requires a dispute in RESOLVED_UPHELD status.",
        )
    if dispute["reopen_count"] >= 1:
        errors.fail(
            errors.ERR_DISPUTE_REOPEN_EXHAUSTED,
            "The single reopen has already been spent.",
        )
    dispute["status"] = "REOPENED"
    dispute["reopen_count"] += 1
    db.touch(dispute)
    return response.success_object(serializers.dispute_view(dispute))
