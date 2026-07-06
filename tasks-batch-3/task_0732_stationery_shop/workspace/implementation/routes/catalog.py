"""Catalog endpoints: paper stocks, finish options, event packages."""

from flask import Blueprint, request

import db
import errors
import middleware
import models
import response as resp
import util

bp = Blueprint("catalog", __name__)


# ---- Paper stocks ---------------------------------------------------------

@bp.route("/paper-stocks", methods=["POST"])
def create_paper_stock():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    body = util.get_body()
    name = util.get_str(body, "name")
    base_price_cents = util.get_int(body, "base_price_cents")
    lead_days = util.get_int(body, "lead_days")
    status = util.get_enum(body, "status", ["ACTIVE", "DISCONTINUED"], required=False, default="ACTIVE")
    if base_price_cents <= 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "base_price_cents must be > 0")
    if lead_days < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "lead_days must be >= 0")
    ps = models.make_common({
        "name": name,
        "base_price_cents": base_price_cents,
        "lead_days": lead_days,
        "status": status,
        "reserved_units": 0,
    })
    db.paper_stocks[ps["id"]] = ps
    return resp.created(ps)


@bp.route("/paper-stocks/<pid>/discontinue", methods=["POST"])
def discontinue_paper_stock(pid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    ps = models.get_paper_stock(pid)
    ps["status"] = "DISCONTINUED"
    models.bump(ps)
    return resp.ok(ps)


@bp.route("/paper-stocks/<pid>", methods=["PATCH"])
def patch_paper_stock(pid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    ps = models.get_paper_stock(pid)
    body = util.get_body()
    changed = False
    if "base_price_cents" in body and body["base_price_cents"] is not None:
        bp_val = util.get_int(body, "base_price_cents")
        if bp_val <= 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "base_price_cents must be > 0")
        ps["base_price_cents"] = bp_val
        changed = True
    if "lead_days" in body and body["lead_days"] is not None:
        ld = util.get_int(body, "lead_days")
        if ld < 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "lead_days must be >= 0")
        ps["lead_days"] = ld
        changed = True
    if changed:
        models.bump(ps)
    return resp.ok(ps)


@bp.route("/paper-stocks/<pid>", methods=["GET"])
def get_paper_stock(pid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    ps = models.get_paper_stock(pid)
    return resp.ok(ps)


@bp.route("/paper-stocks", methods=["GET"])
def list_paper_stocks():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    limit, offset = util.get_pagination()
    status_filter = request.args.get("status")
    items = list(db.paper_stocks.values())
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)


# ---- Finish options -------------------------------------------------------

@bp.route("/finish-options", methods=["POST"])
def create_finish_option():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    body = util.get_body()
    name = util.get_str(body, "name")
    surcharge_cents = util.get_int(body, "surcharge_cents")
    additional_lead_days = util.get_int(body, "additional_lead_days")
    status = util.get_enum(body, "status", ["ACTIVE", "DISCONTINUED"], required=False, default="ACTIVE")
    if surcharge_cents < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "surcharge_cents must be >= 0")
    if additional_lead_days < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "additional_lead_days must be >= 0")
    fo = models.make_common({
        "name": name,
        "surcharge_cents": surcharge_cents,
        "additional_lead_days": additional_lead_days,
        "status": status,
    })
    db.finish_options[fo["id"]] = fo
    return resp.created(fo)


@bp.route("/finish-options/<fid>", methods=["GET"])
def get_finish_option(fid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    fo = models.get_finish_option(fid)
    return resp.ok(fo)


@bp.route("/finish-options", methods=["GET"])
def list_finish_options():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    limit, offset = util.get_pagination()
    status_filter = request.args.get("status")
    items = list(db.finish_options.values())
    if status_filter:
        items = [f for f in items if f["status"] == status_filter]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)


# ---- Event packages -------------------------------------------------------

@bp.route("/event-packages", methods=["POST"])
def create_event_package():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    body = util.get_body()
    name = util.get_str(body, "name")
    package_type = util.get_enum(body, "package_type", ["WEDDING", "ANNOUNCEMENT", "CUSTOM"])
    deposit_pct = util.get_number(body, "deposit_pct")
    min_qty = util.get_int(body, "min_qty")
    proof_expiry_days = util.get_int(body, "proof_expiry_days")
    status = util.get_enum(body, "status", ["ACTIVE", "DISCONTINUED"], required=False, default="ACTIVE")
    if not (0.0 < float(deposit_pct) <= 1.0):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "deposit_pct must be in (0.0, 1.0]")
    if min_qty < 1:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "min_qty must be >= 1")
    if proof_expiry_days < 1:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "proof_expiry_days must be >= 1")
    ep = models.make_common({
        "name": name,
        "package_type": package_type,
        "deposit_pct": deposit_pct,
        "min_qty": min_qty,
        "proof_expiry_days": proof_expiry_days,
        "status": status,
    })
    db.event_packages[ep["id"]] = ep
    return resp.created(ep)


@bp.route("/event-packages/<eid>", methods=["GET"])
def get_event_package(eid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    ep = models.get_event_package(eid)
    return resp.ok(ep)


@bp.route("/event-packages", methods=["GET"])
def list_event_packages():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    limit, offset = util.get_pagination()
    ptype = request.args.get("package_type")
    status_filter = request.args.get("status")
    items = list(db.event_packages.values())
    if ptype:
        items = [e for e in items if e["package_type"] == ptype]
    if status_filter:
        items = [e for e in items if e["status"] == status_filter]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
