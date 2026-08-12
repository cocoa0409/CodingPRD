"""RecoveryPool and RecoveryBilling endpoints."""

from flask import Blueprint

from db import db, new_resource, touch, clock
from errors import err
from response import success_object
from services import calc
from services.core import (
    recompute_billing_posture, recompute_recovery_ytd,
)
from services.validate import (
    body, req_int, req_enum, filter_arg_int, filter_arg_str, req_string,
)
from routes.helpers import (
    get_property_or_404, get_lease_or_404, get_child_or_404, list_response,
)

bp = Blueprint("recovery", __name__)

POOL_CATEGORIES = {"CAM", "TAX", "INSURANCE", "UTILITIES", "MANAGEMENT_FEE"}
BILLING_STATUS = {"DRAFT", "ISSUED", "PAID", "DISPUTED", "VOID"}


# ------------------------------------------------------------- RecoveryPool

@bp.post("/lease-admin/properties/<property_id>/recovery-pools")
def create_pool(property_id):
    get_property_or_404(property_id)
    data = body()
    category = req_enum(data, "category", POOL_CATEGORIES)
    fiscal_year = req_int(data, "fiscal_year", min_v=2000, max_v=2100)
    budgeted_cents = req_int(data, "budgeted_cents", min_v=0)
    floor = req_int(data, "gross_up_floor_pct_bps", min_v=0, max_v=10000) \
        if data.get("gross_up_floor_pct_bps") is not None else \
        calc.DEFAULT_GROSS_UP_FLOOR_BPS
    pid, common = new_resource()
    pool = {
        **common,
        "property_id": property_id,
        "category": category,
        "fiscal_year": fiscal_year,
        "budgeted_cents": budgeted_cents,
        "actual_cents": None,
        "gross_up_floor_pct_bps": floor,
    }
    db["recovery_pools"][pid] = pool
    return success_object(pool, status=201)


@bp.put("/lease-admin/recovery-pools/<pool_id>/actuals")
def record_actuals(pool_id):
    pool = get_child_or_404("recovery_pools", pool_id, "RecoveryPool")
    data = body()
    actual_cents = req_int(data, "actual_cents", min_v=0)
    pool["actual_cents"] = actual_cents
    touch(pool)
    return success_object(pool)


@bp.get("/lease-admin/properties/<property_id>/recovery-pools")
def list_property_pools(property_id):
    get_property_or_404(property_id)
    return list_response(
        [p for p in db["recovery_pools"].values()
         if p["property_id"] == property_id],
        filters=[
            (filter_arg_int("fiscal_year"),
             lambda r, v: r["fiscal_year"] == v),
        ])


@bp.get("/lease-admin/recovery-pools/<pool_id>")
def get_pool(pool_id):
    return success_object(
        get_child_or_404("recovery_pools", pool_id, "RecoveryPool"))


@bp.get("/lease-admin/recovery-pools")
def list_pools_filtered():
    return list_response(db["recovery_pools"].values(), filters=[
        (filter_arg_str("property_id"), lambda r, v: r["property_id"] == v),
        (filter_arg_int("fiscal_year"), lambda r, v: r["fiscal_year"] == v),
        (filter_arg_str("category"), lambda r, v: r["category"] == v),
    ])


# ---------------------------------------------------------- RecoveryBilling

@bp.post("/lease-admin/leases/<lease_id>/recovery-billings")
def create_billing(lease_id):
    lease = get_lease_or_404(lease_id)
    data = body()
    pool_id = req_string(data, "pool_id")
    fiscal_year = req_int(data, "fiscal_year", min_v=2000, max_v=2100)
    period_index = req_int(data, "period_index", min_v=1)
    # Referential integrity (pipeline step 8): pool must exist, belong to the
    # lease's property, and be recoverable under the lease's structure.
    pool = db["recovery_pools"].get(pool_id)
    if pool is None or pool["property_id"] != lease["property_id"]:
        err("ERR_REFERENTIAL_INTEGRITY",
            "pool_id must reference a RecoveryPool on the lease's property")
    if pool["category"] not in calc.recoverable_categories(lease):
        err("ERR_REFERENTIAL_INTEGRITY",
            "Pool category is not recoverable under the lease's recovery_structure")
    bid, common = new_resource()
    billing = {
        **common,
        "lease_id": lease_id,
        "pool_id": pool_id,
        "fiscal_year": fiscal_year,
        "period_index": period_index,
        "estimate_cents": calc.estimate_for_billing(lease, pool),
        "final_cents": None,
        "status": "DRAFT",
        "issued_at": None,
    }
    db["recovery_billings"][bid] = billing
    return success_object(billing, status=201)


@bp.get("/lease-admin/leases/<lease_id>/recovery-billings")
def list_lease_billings(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [b for b in db["recovery_billings"].values()
         if b["lease_id"] == lease_id],
        filters=[
            (filter_arg_int("fiscal_year"),
             lambda r, v: r["fiscal_year"] == v),
            (filter_arg_str("status"), lambda r, v: r["status"] == v),
        ])


@bp.get("/lease-admin/recovery-billings/<billing_id>")
def get_billing(billing_id):
    return success_object(
        get_child_or_404("recovery_billings", billing_id, "RecoveryBilling"))


@bp.get("/lease-admin/recovery-billings")
def list_billings_filtered():
    return list_response(db["recovery_billings"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
        (filter_arg_str("pool_id"), lambda r, v: r["pool_id"] == v),
        (filter_arg_int("fiscal_year"), lambda r, v: r["fiscal_year"] == v),
        (filter_arg_str("status"), lambda r, v: r["status"] == v),
    ])


@bp.post("/lease-admin/recovery-billings/<billing_id>/issue")
def issue_billing(billing_id):
    billing = get_child_or_404("recovery_billings", billing_id,
                               "RecoveryBilling")
    if billing["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Issue requires status == DRAFT")
    lease = db["leases"][billing["lease_id"]]
    if lease["status"] != "ACTIVE":
        err("ERR_LEASE_NOT_ACTIVE", "Issuing requires Lease.status == ACTIVE")
    # Estimate computed from the pool's current budgeted_cents.
    pool = db["recovery_pools"][billing["pool_id"]]
    billing["estimate_cents"] = calc.estimate_for_billing(lease, pool)
    billing["status"] = "ISSUED"
    billing["issued_at"] = clock.current_iso()
    touch(billing)
    recompute_recovery_ytd(lease)
    touch(lease)
    recompute_billing_posture(lease)
    return success_object(billing)


@bp.post("/lease-admin/recovery-billings/<billing_id>/mark-paid")
def mark_paid_billing(billing_id):
    billing = get_child_or_404("recovery_billings", billing_id,
                               "RecoveryBilling")
    if billing["status"] != "ISSUED":
        err("ERR_INVALID_STATE", "Mark-paid requires status == ISSUED")
    billing["status"] = "PAID"
    touch(billing)
    lease = db["leases"][billing["lease_id"]]
    recompute_billing_posture(lease)
    return success_object(billing)


@bp.post("/lease-admin/recovery-billings/<billing_id>/void")
def void_billing(billing_id):
    billing = get_child_or_404("recovery_billings", billing_id,
                               "RecoveryBilling")
    if billing["status"] not in ("DRAFT", "ISSUED"):
        err("ERR_INVALID_STATE", "Void requires status DRAFT or ISSUED")
    was_issued = billing["status"] == "ISSUED"
    billing["status"] = "VOID"
    touch(billing)
    lease = db["leases"][billing["lease_id"]]
    if was_issued:
        recompute_recovery_ytd(lease)
        touch(lease)
    recompute_billing_posture(lease)
    return success_object(billing)
