"""Reconciliation endpoints."""

from flask import Blueprint

from db import db, new_resource, touch, clock
from errors import err
from response import success_object
from services import calc
from services.validate import body, req_int, filter_arg_int, filter_arg_str
from routes.helpers import (
    get_lease_or_404, get_child_or_404, list_response,
)

bp = Blueprint("reconciliations", __name__)

OPEN_CHALLENGE_STATES = {"OPEN", "UNDER_REVIEW", "ESCALATED"}


@bp.post("/lease-admin/leases/<lease_id>/reconciliations")
def create_reconciliation(lease_id):
    get_lease_or_404(lease_id)
    data = body()
    fiscal_year = req_int(data, "fiscal_year", min_v=2000, max_v=2100)
    rid, common = new_resource()
    recon = {
        **common,
        "lease_id": lease_id,
        "fiscal_year": fiscal_year,
        "status": "OPEN",
        "posted_by_user_id": None,
        "approved_by_user_id": None,
        "true_up_cents": None,
        "gross_up_applied": False,
        "closed_date": None,
    }
    db["reconciliations"][rid] = recon
    return success_object(recon, status=201)


@bp.get("/lease-admin/leases/<lease_id>/reconciliations")
def list_lease_reconciliations(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [r for r in db["reconciliations"].values()
         if r["lease_id"] == lease_id],
        filters=[
            (filter_arg_int("fiscal_year"),
             lambda r, v: r["fiscal_year"] == v),
        ])


@bp.get("/lease-admin/reconciliations/<recon_id>")
def get_reconciliation(recon_id):
    return success_object(
        get_child_or_404("reconciliations", recon_id, "Reconciliation"))


@bp.get("/lease-admin/reconciliations")
def list_reconciliations_filtered():
    return list_response(db["reconciliations"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
        (filter_arg_int("fiscal_year"), lambda r, v: r["fiscal_year"] == v),
        (filter_arg_str("status"), lambda r, v: r["status"] == v),
    ])


@bp.post("/lease-admin/reconciliations/<recon_id>/post")
def post_reconciliation(recon_id):
    from middleware import current_user_id
    recon = get_child_or_404("reconciliations", recon_id, "Reconciliation")
    if recon["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Post requires status == OPEN")
    lease = db["leases"][recon["lease_id"]]
    fy = recon["fiscal_year"]
    # Every pool on the lease's property for this fiscal year must have
    # actuals recorded.
    for pool in db["recovery_pools"].values():
        if pool["property_id"] == lease["property_id"] and \
           pool["fiscal_year"] == fy and pool["actual_cents"] is None:
            err("ERR_POOL_NOT_CLOSED",
                "At least one RecoveryPool is missing actual_cents for the fiscal year")
    true_up, gross_up = calc.compute_reconciliation_final(recon)
    recon["true_up_cents"] = true_up
    recon["gross_up_applied"] = gross_up
    recon["posted_by_user_id"] = current_user_id()
    recon["status"] = "POSTED"
    touch(recon)
    # Touch each billing whose final_cents was written.
    for b in db["recovery_billings"].values():
        if b["lease_id"] == lease["id"] and b["fiscal_year"] == fy and \
           b["final_cents"] is not None:
            touch(b)
    # Positive true-up: tenant underpaid — generate a DRAFT true-up billing
    # at period_index 13.
    if true_up > 0:
        pool_ids = [p["id"] for p in db["recovery_pools"].values()
                    if p["property_id"] == lease["property_id"]
                    and p["fiscal_year"] == fy
                    and p["category"] in calc.recoverable_categories(lease)]
        pool_ids.sort()
        anchor_pool = pool_ids[0] if pool_ids else None
        bid, common = new_resource()
        true_up_billing = {
            **common,
            "lease_id": lease["id"],
            "pool_id": anchor_pool,
            "fiscal_year": fy,
            "period_index": 13,
            "estimate_cents": true_up,
            "final_cents": None,
            "status": "DRAFT",
            "issued_at": None,
        }
        db["recovery_billings"][bid] = true_up_billing
    return success_object(recon)


@bp.post("/lease-admin/reconciliations/<recon_id>/approve")
def approve_reconciliation(recon_id):
    from middleware import current_user_id
    recon = get_child_or_404("reconciliations", recon_id, "Reconciliation")
    if recon["status"] != "POSTED":
        err("ERR_INVALID_STATE", "Approve requires status == POSTED")
    # Segregation of duties (pipeline step 7).
    if current_user_id() is not None and \
       current_user_id() == recon["posted_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES",
            "Approver must differ from the poster")
    recon["status"] = "APPROVED"
    recon["approved_by_user_id"] = current_user_id()
    touch(recon)
    return success_object(recon)


@bp.post("/lease-admin/reconciliations/<recon_id>/close")
def close_reconciliation(recon_id):
    recon = get_child_or_404("reconciliations", recon_id, "Reconciliation")
    if recon["status"] not in ("APPROVED", "CHALLENGED"):
        err("ERR_INVALID_STATE",
            "Close requires status APPROVED or CHALLENGED")
    # Fiscal gate (pipeline step 12): no open tenant challenge.
    for ch in db["tenant_challenges"].values():
        if ch["reconciliation_id"] == recon_id and \
           ch["status"] in OPEN_CHALLENGE_STATES:
            err("ERR_OPEN_CHALLENGE",
                "A TenantChallenge referencing this reconciliation is still open")
    recon["status"] = "CLOSED"
    recon["closed_date"] = clock.current().date().isoformat()
    touch(recon)
    # Audit windows open: recompute window close from the close date.
    for ar in db["audit_rights"].values():
        if ar["reconciliation_id"] == recon_id:
            ar["window_close_date"] = (
                calc.d(recon["closed_date"])
                + __import__("datetime").timedelta(days=calc.WINDOW_DAYS)
            ).isoformat()
            touch(ar)
    return success_object(recon)
