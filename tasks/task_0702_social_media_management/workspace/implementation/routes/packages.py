"""Retainer package routes (PRD §3.1)."""
from flask import Blueprint, request

import db
import response
from errors import (
    err, ERR_INVALID_STATE, ERR_PACKAGE_ALREADY_ACTIVE,
)
from middleware import (
    get_user_context, require_role, get_json_body, get_pagination,
    require_enum, require_positive_int, require_nonneg_int, require_min_int,
)
from services import lookup, listing
from services.serialize import package_out

bp = Blueprint("packages", __name__)

TIERS = {"STARTER", "GROWTH", "SCALE"}


@bp.post("/retainer-packages")
def create_package():
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()
    # existence of FK parent (priority 4) before body field validation? PRD §3.8
    # orders existence (incl. create-body FKs) before generic body validation.
    # client_id must be a present string to look up; require it first.
    from middleware import require_string
    client_id = require_string(body, "client_id")
    with db.LOCK:
        lookup.get_client(client_id)
        tier = require_enum(body, "tier", TIERS)
        monthly_retainer_fee_cents = require_positive_int(body, "monthly_retainer_fee_cents")
        monthly_boost_budget_cents = require_nonneg_int(body, "monthly_boost_budget_cents")
        monthly_post_quota = require_min_int(body, "monthly_post_quota", 1)
        included_channels = require_min_int(body, "included_channels", 1)
        p = {
            "id": db.new_id(),
            "client_id": client_id,
            "tier": tier,
            "monthly_retainer_fee_cents": monthly_retainer_fee_cents,
            "monthly_boost_budget_cents": monthly_boost_budget_cents,
            "monthly_post_quota": monthly_post_quota,
            "included_channels": included_channels,
            "status": "DRAFT",
        }
        db.stamp_create(p, full=True)
        db.retainer_packages[p["id"]] = p
        return response.created(package_out(p))


@bp.get("/retainer-packages")
def list_packages():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.retainer_packages.values()), {
            "client_id": request.args.get("client_id"),
            "status": request.args.get("status"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([package_out(p) for p in window], limit, offset, total)


@bp.get("/retainer-packages/<package_id>")
def get_package(package_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    with db.LOCK:
        p = lookup.get_package(package_id)
        return response.ok(package_out(p))


@bp.post("/retainer-packages/<package_id>/activate")
def activate_package(package_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        p = lookup.get_package(package_id)
        # Re-activating an already-ACTIVE package -> ERR_PACKAGE_ALREADY_ACTIVE.
        if p["status"] == "ACTIVE":
            raise err(ERR_PACKAGE_ALREADY_ACTIVE,
                      "Package is already ACTIVE")
        # Activation is defined only out of DRAFT; SUPERSEDED -> ERR_INVALID_STATE.
        if p["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Package must be DRAFT to activate")
        # Supersede any prior ACTIVE package of the same client.
        for other in db.retainer_packages.values():
            if other["id"] != p["id"] and other["client_id"] == p["client_id"] \
                    and other["status"] == "ACTIVE":
                other["status"] = "SUPERSEDED"
                db.touch(other)
        p["status"] = "ACTIVE"
        db.touch(p)
        return response.ok(package_out(p))
