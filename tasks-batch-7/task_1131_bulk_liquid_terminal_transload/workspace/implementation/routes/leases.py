"""LeaseAgreement endpoints: create (CustomerRep, ownership-checked), list,
get, activate, suspend, reactivate, terminate."""
from flask import Blueprint, request

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import lease_view
from services.common import touch, lazy_lease, get_lease_or_404
from validation import (get_body, req_string, req_enum, req_number, req_date,
                        sort_and_page, PRODUCT_GRADES)

bp = Blueprint("leases", __name__)


@bp.post("/lease-agreements")
def create_lease():
    user_id, _ = require_roles("CustomerRep")
    body = get_body()
    customer_id = req_string(body, "customer_id")
    product_grade = req_enum(body, "product_grade", PRODUCT_GRADES)
    committed_capacity_bbl = req_number(body, "committed_capacity_bbl", gt=0)
    min_monthly_throughput_bbl = req_number(body, "min_monthly_throughput_bbl", ge=0)
    throughput_fee_per_bbl = req_number(body, "throughput_fee_per_bbl", gt=0)
    shortfall_fee_per_bbl = req_number(body, "shortfall_fee_per_bbl", ge=0)
    loss_allowance_pct = req_number(body, "loss_allowance_pct", ge=0)
    excess_loss_rate_per_bbl = req_number(body, "excess_loss_rate_per_bbl", ge=0)
    start_date_raw, start_d = req_date(body, "start_date")
    end_date_raw, end_d = req_date(body, "end_date")
    if end_d < start_d:
        raise err("ERR_VALIDATION", "end_date must be on or after start_date")

    # Priority 3: CustomerRep ownership - customer_id must equal X-User-ID.
    if customer_id != user_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP",
                  "CustomerRep may only create leases for their own customer")
    # Priority 5: body FK resolution.
    if customer_id not in STORE.customers:
        raise err("ERR_CUSTOMER_NOT_FOUND", "Customer %s not found" % customer_id)

    now = CLOCK.now()
    lease = {
        "id": new_id(),
        "customer_id": customer_id,
        "product_grade": product_grade,
        "committed_capacity_bbl": committed_capacity_bbl,
        "min_monthly_throughput_bbl": min_monthly_throughput_bbl,
        "throughput_fee_per_bbl": throughput_fee_per_bbl,
        "shortfall_fee_per_bbl": shortfall_fee_per_bbl,
        "loss_allowance_pct": loss_allowance_pct,
        "excess_loss_rate_per_bbl": excess_loss_rate_per_bbl,
        "start_date": start_date_raw,
        "end_date": end_date_raw,
        "_start_date": start_d,
        "_end_date": end_d,
        "reserved_capacity_bbl": 0,
        "suspension_reason": None,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.leases[lease["id"]] = lease
    return success_object(lease_view(lease), status=201)


@bp.get("/lease-agreements")
def list_leases():
    current_user()
    rows = list(STORE.leases.values())
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        rows = [l for l in rows if l["customer_id"] == customer_id]
    status_filter = request.args.get("status")
    for lease in rows:
        lazy_lease(lease)
    if status_filter is not None:
        rows = [l for l in rows if l["status"] == status_filter]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([lease_view(l) for l in page], total, limit, offset)


@bp.get("/lease-agreements/<leaseId>")
def get_lease(leaseId):
    current_user()
    lease = get_lease_or_404(leaseId)
    return success_object(lease_view(lease))


@bp.post("/lease-agreements/<leaseId>/activate")
def activate_lease(leaseId):
    require_roles("TerminalManager")
    lease = get_lease_or_404(leaseId)
    if lease["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE",
                  "Lease %s is %s; activate requires DRAFT" % (leaseId, lease["status"]))
    has_active = any(a["lease_id"] == lease["id"] and a["status"] == "ACTIVE"
                     for a in STORE.allocations.values())
    if not has_active:
        raise err("ERR_NO_ACTIVE_ALLOCATION",
                  "Lease activation requires at least one ACTIVE allocation")
    lease["status"] = "ACTIVE"
    touch(lease)
    return success_object(lease_view(lease))


@bp.post("/lease-agreements/<leaseId>/suspend")
def suspend_lease(leaseId):
    require_roles("TerminalManager")
    lease = get_lease_or_404(leaseId)
    if lease["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  "Lease %s is %s; suspend requires ACTIVE" % (leaseId, lease["status"]))
    lease["status"] = "SUSPENDED"
    lease["suspension_reason"] = "MANUAL"
    touch(lease)
    return success_object(lease_view(lease))


@bp.post("/lease-agreements/<leaseId>/reactivate")
def reactivate_lease(leaseId):
    require_roles("TerminalManager")
    lease = get_lease_or_404(leaseId)
    if lease["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE",
                  "Lease %s is %s; reactivate requires SUSPENDED" % (leaseId, lease["status"]))
    lease["status"] = "ACTIVE"
    lease["suspension_reason"] = None
    touch(lease)
    return success_object(lease_view(lease))


@bp.post("/lease-agreements/<leaseId>/terminate")
def terminate_lease(leaseId):
    require_roles("TerminalManager")
    lease = get_lease_or_404(leaseId)
    if lease["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  "Lease %s is %s; terminate requires ACTIVE" % (leaseId, lease["status"]))
    for m in STORE.movements.values():
        if m["lease_id"] == lease["id"] and m["status"] in (
                "SCHEDULED", "ARRIVED", "IN_PROGRESS", "SUSPENDED"):
            raise err("ERR_INVALID_STATE",
                      "Lease has a movement in status %s" % m["status"])
    for a in STORE.allocations.values():
        if a["lease_id"] == lease["id"] and a["status"] in ("RESERVED", "ACTIVE"):
            a["status"] = "RELEASED"
            touch(a)
    lease["status"] = "TERMINATED"
    lease["reserved_capacity_bbl"] = 0
    touch(lease)
    return success_object(lease_view(lease))
