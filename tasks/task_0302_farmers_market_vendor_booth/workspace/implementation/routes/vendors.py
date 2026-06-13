"""Vendor, Permit, Application routes (§3.2)."""
from flask import Blueprint, request

from common import (init_common, touch, require_fields, req_str, req_date,
                    req_enum, paginate)
from db import db
from errors import err
from middleware import get_auth, require_role, get_json_body
from response import success
from routes.helpers import get_or_404, fk_or_404
from serializers import view, view_list
from services import derived

bp = Blueprint("vendors", __name__)

PERMIT_TYPES = {"HEALTH", "FIRE", "COTTAGE_FOOD", "RESALE"}
PRODUCT_CATEGORIES = {"PRODUCE", "DAIRY", "MEAT", "BAKED_GOODS",
                      "PREPARED_FOOD", "CRAFTS", "FLOWERS"}
HEALTH_GATED = {"DAIRY", "MEAT", "PREPARED_FOOD"}


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------
@bp.route("/vendors", methods=["POST"])
def create_vendor():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "Vendor"})
    body = get_json_body()
    require_fields(body, ["market_id", "legal_name", "contact_email"])
    market_id = req_str(body, "market_id")
    legal_name = req_str(body, "legal_name")
    contact_email = req_str(body, "contact_email")

    fk_or_404("market", market_id)

    # Uniqueness: contact_email per market (ERR_DUPLICATE)
    for v in db.vendors.values():
        if v["market_id"] == market_id and v["contact_email"] == contact_email:
            raise err("ERR_DUPLICATE", "Duplicate contact_email within market")

    vendor = {
        "market_id": market_id,
        "legal_name": legal_name,
        "contact_email": contact_email,
        "status": "PROSPECT",
        "permit_ok": False,
        "no_show_strikes": 0,
    }
    init_common(vendor)
    db.vendors[vendor["id"]] = vendor
    return success(view(vendor), 201)


@bp.route("/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    v = get_or_404("vendor", vendor_id)
    return success(view(v), 200)


@bp.route("/vendors", methods=["GET"])
def list_vendors():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.vendors.values())
    market_id = request.args.get("market_id")
    status = request.args.get("status")
    if market_id is not None:
        items = [v for v in items if v["market_id"] == market_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


# ---------------------------------------------------------------------------
# Permit
# ---------------------------------------------------------------------------
@bp.route("/permits", methods=["POST"])
def create_permit():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "Vendor"})
    body = get_json_body()
    require_fields(body, ["vendor_id", "permit_type", "permit_number",
                          "issue_date", "expiry_date"])
    vendor_id = req_str(body, "vendor_id")
    permit_type = req_enum(body, "permit_type", PERMIT_TYPES)
    permit_number = req_str(body, "permit_number")
    issue_date = req_date(body, "issue_date")
    expiry_date = req_date(body, "expiry_date")

    fk_or_404("vendor", vendor_id)

    if expiry_date <= issue_date:
        raise err("ERR_VALIDATION_BOUNDS", "expiry_date must be after issue_date")

    permit = {
        "vendor_id": vendor_id,
        "permit_type": permit_type,
        "permit_number": permit_number,
        "issue_date": issue_date,
        "expiry_date": expiry_date,
        "status": "PENDING",
        "verified_at": None,
    }
    init_common(permit)
    db.permits[permit["id"]] = permit
    return success(view(permit), 201)


@bp.route("/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    p = get_or_404("permit", permit_id)
    return success(view(p), 200)


@bp.route("/permits", methods=["GET"])
def list_permits():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.permits.values())
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    if vendor_id is not None:
        items = [p for p in items if p["vendor_id"] == vendor_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


@bp.route("/permits/<permit_id>/verify", methods=["POST"])
def verify_permit(permit_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    permit = get_or_404("permit", permit_id)
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = req_enum(body, "decision", {"VERIFY", "REJECT"})
    if permit["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Permit is not PENDING")
    if decision == "VERIFY":
        permit["status"] = "VERIFIED"
        permit["verified_at"] = db.clock.now_iso()
        touch(permit)
        vendor = db.vendors.get(permit["vendor_id"])
        if vendor:
            derived.recompute_vendor_permit_ok(vendor)
    else:
        permit["status"] = "REJECTED"
        touch(permit)
    return success(view(permit), 200)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
@bp.route("/applications", methods=["POST"])
def create_application():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "Vendor"})
    body = get_json_body()
    require_fields(body, ["vendor_id", "product_category"])
    vendor_id = req_str(body, "vendor_id")
    product_category = req_enum(body, "product_category", PRODUCT_CATEGORIES)

    fk_or_404("vendor", vendor_id)

    app = {
        "vendor_id": vendor_id,
        "product_category": product_category,
        "requires_health_permit": product_category in HEALTH_GATED,
        "status": "SUBMITTED",
        "review_note": None,
    }
    init_common(app)
    db.applications[app["id"]] = app
    return success(view(app), 201)


@bp.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    a = get_or_404("application", application_id)
    return success(view(a), 200)


@bp.route("/applications", methods=["GET"])
def list_applications():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.applications.values())
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    if vendor_id is not None:
        items = [a for a in items if a["vendor_id"] == vendor_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


@bp.route("/applications/<application_id>/start-review", methods=["POST"])
def start_review(application_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    app = get_or_404("application", application_id)
    if app["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application is not SUBMITTED")
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return success(view(app), 200)


@bp.route("/applications/<application_id>/approve", methods=["POST"])
def approve_application(application_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    app = get_or_404("application", application_id)
    body = get_json_body()
    if app["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Application is not UNDER_REVIEW")
    # Health-permit gate (§3.2 -> ERR_NO_HEALTH_PERMIT)
    if app["requires_health_permit"]:
        vendor = db.vendors[app["vendor_id"]]
        market = db.markets[vendor["market_id"]]
        ok = any(p["vendor_id"] == vendor["id"]
                 and p["permit_type"] == "HEALTH"
                 and p["status"] == "VERIFIED"
                 and p["expiry_date"] >= market["season_start_date"]
                 for p in db.permits.values())
        if not ok:
            raise err("ERR_NO_HEALTH_PERMIT", "VERIFIED HEALTH permit required to approve")
    review_note = body.get("review_note")
    if review_note is not None and not isinstance(review_note, str):
        raise err("ERR_INVALID_REQUEST", "review_note must be a string")
    app["status"] = "APPROVED"
    app["review_note"] = review_note
    touch(app)
    vendor = db.vendors[app["vendor_id"]]
    if vendor["status"] == "PROSPECT":
        vendor["status"] = "ACTIVE"
        touch(vendor)
    # Approval can change which category gates the vendor — refresh permit_ok.
    derived.recompute_vendor_permit_ok(vendor)
    return success(view(app), 200)


@bp.route("/applications/<application_id>/reject", methods=["POST"])
def reject_application(application_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    app = get_or_404("application", application_id)
    body = get_json_body()
    if app["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Application is not UNDER_REVIEW")
    review_note = body.get("review_note")
    if review_note is not None and not isinstance(review_note, str):
        raise err("ERR_INVALID_REQUEST", "review_note must be a string")
    app["status"] = "REJECTED"
    app["review_note"] = review_note
    touch(app)
    return success(view(app), 200)


@bp.route("/applications/<application_id>/resubmit", methods=["POST"])
def resubmit_application(application_id):
    user_id, role = get_auth()
    require_role(role, {"Vendor"})
    app = get_or_404("application", application_id)
    # Vendor ownership (§3.2): Application.vendor_id == X-User-ID
    if app["vendor_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Vendor does not own this application")
    if app["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Application is not REJECTED")
    app["status"] = "SUBMITTED"
    app["review_note"] = None
    touch(app)
    return success(view(app), 200)
