"""Tenant routes (scaffold §1.5 — Tenants block; PRD §3.2 + §3.3).

Liveaboard lifecycle endpoints live alongside Tenant CRUD because every
transition mutates ``Tenant.liveaboard_status`` first, with marina counter and
cascade effects fanning out from that primary mutation.
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LIVEABOARD_QUOTA_EXCEEDED,
)
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.cascades import cancel_reserved_liveaboard_leases
from services.validation import (
    lookup_or_404,
    require_fields,
    require_string,
)


bp = Blueprint("tenants", __name__)


@bp.post("/tenants")
def create_tenant():
    require_auth(["HarborMaster"])()
    body = get_json_body()
    require_fields(body, ["email", "full_name"])
    email = require_string(body["email"], "email", max_len=200)
    full_name = require_string(body["full_name"], "full_name", max_len=200)

    with db.mutation_lock:
        for t in db.tenants.values():
            if t.get("email") == email:
                raise APIError(ERR_INVALID_REQUEST, 400, "email already in use")
        tenant = {
            "email": email,
            "full_name": full_name,
            "liveaboard_status": "NONE",
            "liveaboard_approved_at": None,
            # Internal: track marina_id used for the last APPROVED transition so
            # REVOKE can decrement the correct marina's count.
            "_liveaboard_marina_id": None,
        }
        db.stamp_common(tenant)
        db.tenants[tenant["id"]] = tenant
        return ok_object(_public_tenant(tenant), 201)


def _public_tenant(t: dict) -> dict:
    """Strip internal-only fields from the public projection."""
    return {k: v for k, v in t.items() if not k.startswith("_")}


@bp.get("/tenants")
def list_tenants():
    require_auth(["HarborMaster", "MarinaStaff"])()
    limit, offset = paginate_params(request.args)
    items = list(db.tenants.values())
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array([_public_tenant(t) for t in page], limit, offset, total, 200)


@bp.get("/tenants/<tid>")
def get_tenant(tid: str):
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    tenant = lookup_or_404(db.tenants, tid, "Tenant")
    return ok_object(_public_tenant(tenant), 200)


# ---- liveaboard lifecycle ---------------------------------------------------


@bp.post("/tenants/<tid>/liveaboard-applications")
def liveaboard_apply(tid: str):
    require_auth(["Tenant"])()
    tenant = lookup_or_404(db.tenants, tid, "Tenant")
    body = get_json_body()
    require_fields(body, ["marina_id"])
    marina = lookup_or_404(db.marinas, body["marina_id"], "Marina")
    with db.mutation_lock:
        cur = tenant.get("liveaboard_status")
        if cur not in ("NONE", "REVOKED"):
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "Tenant.liveaboard_status must be NONE or REVOKED to apply",
            )
        tenant["liveaboard_status"] = "PENDING"
        # Record the application's marina_id so subsequent approve can read it
        # if the approver omits the marina_id (defensive — the API requires it).
        tenant["_liveaboard_application_marina_id"] = marina["id"]
        db.bump(tenant)
        return ok_object(_public_tenant(tenant), 200)


@bp.post("/tenants/<tid>/liveaboard-approve")
def liveaboard_approve(tid: str):
    require_auth(["HarborMaster"])()
    tenant = lookup_or_404(db.tenants, tid, "Tenant")
    body = get_json_body()
    require_fields(body, ["marina_id"])
    marina = lookup_or_404(db.marinas, body["marina_id"], "Marina")

    with db.mutation_lock:
        if tenant.get("liveaboard_status") != "PENDING":
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "Tenant.liveaboard_status must be PENDING to approve",
            )
        # Quota check (scaffold §1.4 priority 11).
        if marina.get("liveaboard_current_count", 0) >= marina.get(
            "liveaboard_cap", 0
        ):
            raise APIError(
                ERR_LIVEABOARD_QUOTA_EXCEEDED,
                409,
                "Marina liveaboard cap reached",
            )
        tenant["liveaboard_status"] = "APPROVED"
        tenant["liveaboard_approved_at"] = db.now_logical_iso()
        tenant["_liveaboard_marina_id"] = marina["id"]
        marina["liveaboard_current_count"] = (
            marina.get("liveaboard_current_count", 0) + 1
        )
        db.bump(marina)
        db.bump(tenant)
        return ok_object(_public_tenant(tenant), 200)


@bp.post("/tenants/<tid>/liveaboard-deny")
def liveaboard_deny(tid: str):
    require_auth(["HarborMaster"])()
    tenant = lookup_or_404(db.tenants, tid, "Tenant")
    with db.mutation_lock:
        if tenant.get("liveaboard_status") != "PENDING":
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "Tenant.liveaboard_status must be PENDING to deny",
            )
        tenant["liveaboard_status"] = "NONE"
        db.bump(tenant)
        return ok_object(_public_tenant(tenant), 200)


@bp.post("/tenants/<tid>/liveaboard-revoke")
def liveaboard_revoke(tid: str):
    require_auth(["HarborMaster"])()
    tenant = lookup_or_404(db.tenants, tid, "Tenant")
    body = get_json_body()
    require_fields(body, ["marina_id"])
    marina = lookup_or_404(db.marinas, body["marina_id"], "Marina")

    with db.mutation_lock:
        if tenant.get("liveaboard_status") != "APPROVED":
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "Tenant.liveaboard_status must be APPROVED to revoke",
            )
        tenant["liveaboard_status"] = "REVOKED"
        marina["liveaboard_current_count"] = max(
            0, marina.get("liveaboard_current_count", 0) - 1
        )
        db.bump(marina)
        # Cascade: every RESERVED liveaboard lease for this tenant -> CANCELLED.
        cancel_reserved_liveaboard_leases(tenant["id"])
        db.bump(tenant)
        return ok_object(_public_tenant(tenant), 200)
