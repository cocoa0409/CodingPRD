"""Tenants and the tenant's dispute history."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from middleware import SINGLE_READ_ROLES, authorize
from response import created, listing, ok
from util import D

bp = Blueprint("tenants", __name__)

TENANT_STATUSES = ("ACTIVE", "DEFAULTED", "BANKRUPT")


def get_tenant(tenant_id):
    return resolve(store.tenants, tenant_id, "ERR_TENANT_NOT_FOUND")


@bp.post("/tenants")
def create_tenant():
    authorize(["LeaseAdministrator"])
    body = v.body()
    legal_name = v.req_str(body, "legal_name")
    notice_email = v.req_str(body, "notice_email")
    primary_use_code = v.req_str(body, "primary_use_code")
    is_chain = v.opt_bool(body, "is_national_chain", default=False)

    tenant = base(engine.stamp())
    tenant.update({
        "legal_name": legal_name,
        "notice_email": notice_email,
        "primary_use_code": primary_use_code,
        "is_national_chain": is_chain,
        "status": "ACTIVE",
    })
    store.tenants[tenant["id"]] = tenant
    return created(strip(tenant))


@bp.get("/tenants/<tenant_id>")
def read_tenant(tenant_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_tenant(tenant_id)))


@bp.patch("/tenants/<tenant_id>")
def patch_tenant(tenant_id):
    authorize(["LeaseAdministrator", "ComplianceOfficer"])
    body = v.body()
    status = v.req_enum(body, "status", TENANT_STATUSES)
    legal_name = v.opt_str(body, "legal_name")
    notice_email = v.opt_str(body, "notice_email")
    primary_use_code = v.opt_str(body, "primary_use_code")
    is_chain = body.get("is_national_chain")
    if is_chain is not None:
        is_chain = v.opt_bool(body, "is_national_chain")
    tenant = get_tenant(tenant_id)

    tenant["status"] = status
    if legal_name is not None:
        tenant["legal_name"] = legal_name
    if notice_email is not None:
        tenant["notice_email"] = notice_email
    if primary_use_code is not None:
        tenant["primary_use_code"] = primary_use_code
    if is_chain is not None:
        tenant["is_national_chain"] = is_chain
    engine.touch(tenant)

    # every center holding a lease of this tenant re-derives from scratch
    center_ids = []
    for lease in engine._ordered(list(store.leases.values())):
        if lease["tenant_id"] == tenant["id"] and lease["center_id"] not in center_ids:
            center_ids.append(lease["center_id"])
    for center_id in center_ids:
        center = store.centers.get(center_id)
        if center is None:
            continue
        engine.recompute_center_derived(center)
        engine.evaluate_center_conditions(center, "LIVE_STRICT")
        engine.bump_center(center)

    return ok(strip(tenant))


@bp.get("/tenants/<tenant_id>/use-violation-disputes")
def list_tenant_disputes(tenant_id):
    authorize(["ComplianceOfficer", "LeaseAdministrator", "TenantRep"])
    limit, offset = v.pagination()
    tenant = get_tenant(tenant_id)
    records = [d for d in engine._ordered(list(store.disputes.values()))
               if d["filed_by_tenant_id"] == tenant["id"]]
    records = apply_filters(records, [
        ("notice_id", v.filter_value("notice_id")),
        ("status", v.filter_value("status")),
        ("grounds_code", v.filter_value("grounds_code")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)
