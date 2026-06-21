"""Reconciliation endpoints: lifecycle, OCC post, dispute cycle, void compensation,
preview (PRD §3.7, §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_YEAR_MISMATCH, ERR_POOL_LOCKED, ERR_DUPLICATE_RECON_PERIOD,
    ERR_NOT_LEASE_OWNER, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import (
    auth_required, ALL_ROLES, PROPERTY_MANAGER, ACCOUNTANT, TENANT, current_user_id,
)
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int,
    parse_pagination, paginate, order_by_created,
)
from services.common import new_common_fields, touch
from services.ledger import post_ledger_entry
from services.calculations import compute_true_up, compute_total_recoverable_cents

bp = Blueprint("reconciliations", __name__)


def _public(recon: dict) -> dict:
    """Snapshot fields are blank (null) until POSTED (PRD §2.6)."""
    return serialize(recon)


@bp.post("/reconciliations")
def create_reconciliation():
    auth_required({PROPERTY_MANAGER})()
    body = get_body()
    require_fields(body, ["lease_id", "pool_id", "recon_year"])

    lease_id = body["lease_id"]
    pool_id = body["pool_id"]
    lease = db.leases.get(lease_id)
    if lease is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "lease_id references a non-existent lease")
    pool = db.expense_pools.get(pool_id)
    if pool is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "pool_id references a non-existent expense pool")

    recon_year = body["recon_year"]
    if not is_int(recon_year) or recon_year < 2000:
        raise APIError(ERR_INVALID_REQUEST, 400, "recon_year must be an integer >= 2000")

    # recon_year must equal the referenced pool's pool_year (year-match) at create.
    if recon_year != pool["pool_year"]:
        raise APIError(ERR_YEAR_MISMATCH, 422, "recon_year must equal the pool's pool_year")

    # A second reconciliation for a (lease, year) already covered by a POSTED recon.
    for r in db.reconciliations.values():
        if r["lease_id"] == lease_id and r["recon_year"] == recon_year and r["status"] == "POSTED":
            raise APIError(ERR_DUPLICATE_RECON_PERIOD, 409,
                           "A posted reconciliation already covers this lease and year")

    recon = {
        **new_common_fields(),
        "lease_id": lease_id,
        "pool_id": pool_id,
        "recon_year": recon_year,
        "pro_rata_share_pct": None,
        "reconciled_cam_cents": None,
        "estimated_cam_billed_cents": None,
        "true_up_cents": None,
        "status": "DRAFT",
        "_submitted_by": None,
    }
    db.reconciliations[recon["id"]] = recon
    return ok_object(_public(recon), http_status=201)


@bp.get("/reconciliations/<rid>")
def get_reconciliation(rid):
    auth_required(ALL_ROLES)()
    r = db.reconciliations.get(rid)
    if r is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")
    return ok_object(_public(r))


@bp.get("/reconciliations")
def list_reconciliations():
    auth_required(ALL_ROLES)()
    limit, offset = parse_pagination()
    items = list(db.reconciliations.values())
    lease_id = request.args.get("lease_id")
    if lease_id is not None:
        items = [r for r in items if r["lease_id"] == lease_id]
    pool_id = request.args.get("pool_id")
    if pool_id is not None:
        items = [r for r in items if r["pool_id"] == pool_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array([_public(r) for r in page], limit, offset, total)


@bp.get("/reconciliations/<rid>/preview")
def preview_reconciliation(rid):
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    recon = db.reconciliations.get(rid)
    if recon is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")
    lease = db.leases.get(recon["lease_id"])
    pool = db.expense_pools.get(recon["pool_id"])
    if lease is None or pool is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "Referenced lease or pool not found")

    # Read-only dry run: compute the four figures and return them on a copy
    # (raises ERR_EMPTY_DENOMINATOR if the denominator is zero).
    figures = compute_true_up(lease, pool)
    view = serialize(recon)
    view.update(figures)
    return ok_object(view)


@bp.post("/reconciliations/<rid>/submit")
def submit_reconciliation(rid):
    auth_required({PROPERTY_MANAGER})()
    recon = db.reconciliations.get(rid)
    if recon is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")

    if recon["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Reconciliation must be DRAFT to submit")

    lease = db.leases.get(recon["lease_id"])
    pool = db.expense_pools.get(recon["pool_id"])
    if lease is None or pool is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "Referenced lease or pool not found")
    if lease["status"] not in ("ACTIVE", "HOLDOVER"):
        raise APIError(ERR_INVALID_STATE, 409, "Referenced lease must be ACTIVE or HOLDOVER")
    if recon["recon_year"] != pool["pool_year"]:
        raise APIError(ERR_YEAR_MISMATCH, 422, "recon_year must equal the pool's pool_year")

    recon["status"] = "IN_REVIEW"
    # Record the submitting operator for the segregation-of-duties check (PRD §2.8).
    recon["_submitted_by"] = current_user_id()
    touch(recon)
    return ok_object(_public(recon))


@bp.post("/reconciliations/<rid>/return")
def return_reconciliation(rid):
    auth_required({ACCOUNTANT})()
    recon = db.reconciliations.get(rid)
    if recon is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")
    if recon["status"] != "IN_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Reconciliation must be IN_REVIEW to return")
    recon["status"] = "DRAFT"
    touch(recon)  # advances version → makes a pre-cycle post stale (PRD §2.7)
    return ok_object(_public(recon))


@bp.post("/reconciliations/<rid>/post")
def post_reconciliation(rid):
    auth_required({ACCOUNTANT})()
    recon = db.reconciliations.get(rid)
    if recon is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")

    body = get_body()
    require_fields(body, ["expected_reconciliation_version"])
    expected = body["expected_reconciliation_version"]
    if not is_int(expected):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_reconciliation_version must be an integer")

    # Priority 4: segregation of duties — poster must not be the submitter (PRD §2.8).
    if recon.get("_submitted_by") is not None and current_user_id() == recon["_submitted_by"]:
        raise APIError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The posting accountant must not be the user who submitted the reconciliation")

    # Priority 8: state.
    if recon["status"] != "IN_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Reconciliation must be IN_REVIEW to post")

    # Priority 9: OCC.
    if expected != recon["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_reconciliation_version is stale")

    lease = db.leases.get(recon["lease_id"])
    pool = db.expense_pools.get(recon["pool_id"])
    if lease is None or pool is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "Referenced lease or pool not found")

    # Priority 11: pool must be OPEN.
    if pool["status"] != "OPEN":
        raise APIError(ERR_POOL_LOCKED, 409, "Referenced expense pool is already LOCKED")

    # Priority 12: denominator guard, then compute snapshot (raises ERR_EMPTY_DENOMINATOR).
    figures = compute_true_up(lease, pool)

    # Snapshot the four computed figures onto the reconciliation.
    recon["pro_rata_share_pct"] = figures["pro_rata_share_pct"]
    recon["reconciled_cam_cents"] = figures["reconciled_cam_cents"]
    recon["estimated_cam_billed_cents"] = figures["estimated_cam_billed_cents"]
    recon["true_up_cents"] = figures["true_up_cents"]
    recon["status"] = "POSTED"

    # Cascade: lock pool, recompute its total, bump its version.
    pool["status"] = "LOCKED"
    pool["total_recoverable_cents"] = compute_total_recoverable_cents(pool)
    touch(pool)

    # Cascade: post CAM_TRUEUP ledger entry of signed true_up_cents; recompute balance;
    # bump lease version.
    post_ledger_entry(lease, "CAM_TRUEUP", figures["true_up_cents"], source_reconciliation_id=recon["id"])
    touch(lease)

    # Bump reconciliation version (its own mutation).
    touch(recon)

    return ok_object(_public(recon))


@bp.post("/reconciliations/<rid>/dispute")
def dispute_reconciliation(rid):
    # Tenant-only; ownership checked after auth (priority 3, before state).
    auth_required({TENANT})()
    recon = db.reconciliations.get(rid)
    if recon is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")

    lease = db.leases.get(recon["lease_id"])
    if lease is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "Referenced lease not found")
    if lease["tenant_id"] != current_user_id():
        raise APIError(ERR_NOT_LEASE_OWNER, 403, "Acting tenant does not own the referenced lease")

    if recon["status"] != "POSTED":
        raise APIError(ERR_INVALID_STATE, 409, "Reconciliation must be POSTED to dispute")

    recon["status"] = "DISPUTED"
    touch(recon)
    return ok_object(_public(recon))


@bp.post("/reconciliations/<rid>/resolve-dispute")
def resolve_dispute(rid):
    auth_required({ACCOUNTANT})()
    recon = db.reconciliations.get(rid)
    if recon is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")
    if recon["status"] != "DISPUTED":
        raise APIError(ERR_INVALID_STATE, 409, "Reconciliation must be DISPUTED to resolve")
    recon["status"] = "POSTED"  # cyclic re-affirm, no ledger change
    touch(recon)
    return ok_object(_public(recon))


@bp.post("/reconciliations/<rid>/void")
def void_reconciliation(rid):
    auth_required({ACCOUNTANT})()
    recon = db.reconciliations.get(rid)
    if recon is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")
    if recon["status"] != "DISPUTED":
        raise APIError(ERR_INVALID_STATE, 409, "Reconciliation must be DISPUTED to void")

    lease = db.leases.get(recon["lease_id"])
    pool = db.expense_pools.get(recon["pool_id"])

    recon["status"] = "VOID"

    # Compensation: reverse the CAM_TRUEUP with a CREDIT_ADJUSTMENT of -true_up_cents.
    if lease is not None:
        post_ledger_entry(lease, "CREDIT_ADJUSTMENT", -recon["true_up_cents"],
                          source_reconciliation_id=recon["id"])
        touch(lease)

    # Reopen the pool, recompute, bump its version.
    if pool is not None:
        pool["status"] = "OPEN"
        pool["total_recoverable_cents"] = compute_total_recoverable_cents(pool)
        touch(pool)

    touch(recon)
    return ok_object(_public(recon))


@bp.get("/reconciliations/<rid>/ledger-entries")
def list_recon_ledger_entries(rid):
    auth_required(ALL_ROLES)()
    if db.reconciliations.get(rid) is None:
        raise APIError(ERR_NOT_FOUND, 404, "Reconciliation not found")
    limit, offset = parse_pagination()
    items = order_by_created(
        [e for e in db.ledger_entries.values() if e.get("source_reconciliation_id") == rid]
    )
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
