"""VendorApplication pipeline: submit/supersede, review loop, decide, withdraw."""
from flask import Blueprint

import serialize
from store import db
from util import (body_json, err, get_or_404, list_response, new_id, opt_enum,
                  opt_int, req_bool, req_enum, req_int, req_str, require_role,
                  stamp_new, success, touch)

bp = Blueprint("applications", __name__)

CATEGORIES = ("FOOD_HOT", "FOOD_COLD", "BEVERAGE_ALCOHOL", "BEVERAGE_NA",
              "DESSERT", "MERCHANDISE")
FEE_MODELS = ("FLAT_FEE", "REVENUE_SHARE", "HYBRID")
TIER_MODES = ("MARGINAL", "WHOLE_TIER")
DECISIONS = ("ACCEPTED", "REJECTED", "WAITLISTED")
APP_READ_ROLES = ("FestivalDirector", "VendorManager", "OperationsLead",
                  "FinanceLead", "Vendor")


@bp.route("/vendor-applications", methods=["POST"])
def create_application():
    uid, _ = require_role("Vendor")
    b = body_json()

    # (4) Existence of body FK references that are present.
    vendor = None
    if b.get("vendor_id") is not None:
        vendor = get_or_404(db.vendors, b.get("vendor_id"),
                            "ERR_VENDOR_NOT_FOUND", "Vendor")
    festival = None
    if b.get("festival_id") is not None:
        festival = get_or_404(db.festivals, b.get("festival_id"),
                              "ERR_FESTIVAL_NOT_FOUND", "Festival")
    source = None
    if b.get("supersedes_application_id") is not None:
        source = get_or_404(db.applications, b.get("supersedes_application_id"),
                            "ERR_APPLICATION_NOT_FOUND", "Application")

    # (5) Entity-backed ownership: vendor_id must equal the caller's X-User-ID.
    if b.get("vendor_id") is not None and b.get("vendor_id") != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "vendor_id must equal the acting vendor's X-User-ID")

    # (6) Festival posture gate.
    if festival is not None and festival["status"] != "APPLICATIONS_OPEN":
        err("ERR_FESTIVAL_NOT_ACCEPTING_APPLICATIONS", 409,
            "Festival is not in APPLICATIONS_OPEN")

    # (7) Vendor standing.
    if vendor is not None and vendor["status"] == "SUSPENDED":
        err("ERR_VENDOR_SUSPENDED", 409, "A SUSPENDED vendor may not submit applications")

    # (8) Request shape.
    req_str(b, "vendor_id")
    req_str(b, "festival_id")
    category = req_enum(b, "category", CATEGORIES)
    fee_model = req_enum(b, "fee_model", FEE_MODELS)
    power_needed = req_int(b, "power_needed_amps", min_v=1)
    requires_water = req_bool(b, "requires_water")
    proposed_flat = None
    proposed_share = None
    if fee_model in ("FLAT_FEE", "HYBRID"):
        proposed_flat = req_int(b, "proposed_flat_fee_cents", min_v=0)
    else:
        proposed_flat = opt_int(b, "proposed_flat_fee_cents", min_v=0)
    if fee_model in ("REVENUE_SHARE", "HYBRID"):
        proposed_share = req_int(b, "proposed_revenue_share_pct_bp",
                                 min_v=1, max_v=10000)
    else:
        proposed_share = opt_int(b, "proposed_revenue_share_pct_bp",
                                 min_v=1, max_v=10000)

    # (9) Supersede referential integrity.
    if source is not None:
        if (source["status"] != "CHANGES_REQUESTED"
                or source["vendor_id"] != b.get("vendor_id")
                or source["festival_id"] != b.get("festival_id")):
            err("ERR_SUPERSEDE_SOURCE_INVALID", 409,
                "supersedes_application_id must reference a CHANGES_REQUESTED "
                "application of the same vendor and festival")

    review_round = 0
    if source is not None:
        review_round = source["review_round"] + 1
        source["status"] = "SUPERSEDED"
        touch(source)

    app = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "vendor_id": b["vendor_id"],
        "festival_id": b["festival_id"],
        "category": category,
        "fee_model": fee_model,
        "proposed_flat_fee_cents": proposed_flat,
        "proposed_revenue_share_pct_bp": proposed_share,
        "power_needed_amps": power_needed,
        "requires_water": requires_water,
        "supersedes_application_id": b.get("supersedes_application_id"),
        "review_round": review_round,
        "curated_fee_model": None,
        "curated_flat_fee_cents": None,
        "curated_revenue_share_pct_bp": None,
        "curated_tier_mode": None,
        "curated_minimum_guarantee_cents": None,
        "curated_free_allowance_cents": None,
        "status": "SUBMITTED",
    })
    db.applications[app["id"]] = app
    return success(serialize.serialize_application(app), 201)


@bp.route("/vendor-applications", methods=["GET"])
def list_applications():
    require_role(*APP_READ_ROLES)
    return list_response(list(db.applications.values()),
                         serialize.serialize_application, {
                             "festival_id": "festival_id",
                             "vendor_id": "vendor_id",
                             "status": "status",
                             "category": "category",
                             "supersedes_application_id": "supersedes_application_id",
                         })


@bp.route("/vendor-applications/<applicationId>", methods=["GET"])
def get_application(applicationId):
    require_role(*APP_READ_ROLES)
    app = get_or_404(db.applications, applicationId,
                     "ERR_APPLICATION_NOT_FOUND", "Application")
    return success(serialize.serialize_application(app))


@bp.route("/vendor-applications/<applicationId>/start-review", methods=["POST"])
def start_review(applicationId):
    require_role("VendorManager")
    app = get_or_404(db.applications, applicationId,
                     "ERR_APPLICATION_NOT_FOUND", "Application")
    if app["status"] not in ("SUBMITTED", "WAITLISTED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"start-review is not permitted from {app['status']}")
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return success(serialize.serialize_application(app))


@bp.route("/vendor-applications/<applicationId>/request-changes", methods=["POST"])
def request_changes(applicationId):
    require_role("VendorManager")
    app = get_or_404(db.applications, applicationId,
                     "ERR_APPLICATION_NOT_FOUND", "Application")
    body_json()  # optional notes; accepted and ignored
    if app["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"request-changes is not permitted from {app['status']}")
    if app["review_round"] >= 3:
        err("ERR_REVIEW_ROUND_LIMIT", 409,
            "review_round has reached the limit of 3")
    app["status"] = "CHANGES_REQUESTED"
    touch(app)
    return success(serialize.serialize_application(app))


@bp.route("/vendor-applications/<applicationId>/decide", methods=["POST"])
def decide(applicationId):
    require_role("VendorManager")
    app = get_or_404(db.applications, applicationId,
                     "ERR_APPLICATION_NOT_FOUND", "Application")
    b = body_json()
    # (8) state legality, then request shape.
    if app["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"decide is not permitted from {app['status']}")
    decision = req_enum(b, "decision", DECISIONS)
    curated_fee_model = opt_enum(b, "curated_fee_model", FEE_MODELS)
    curated_flat = opt_int(b, "curated_flat_fee_cents", min_v=0)
    curated_share = opt_int(b, "curated_revenue_share_pct_bp", min_v=1, max_v=10000)
    curated_tier = opt_enum(b, "curated_tier_mode", TIER_MODES)
    curated_minimum = opt_int(b, "curated_minimum_guarantee_cents", min_v=0)
    curated_allowance = opt_int(b, "curated_free_allowance_cents", min_v=0)

    if decision == "ACCEPTED":
        # (12) Per-category cap.
        festival = db.festivals[app["festival_id"]]
        accepted = sum(
            1 for q in db.applications.values()
            if q["festival_id"] == app["festival_id"]
            and q["category"] == app["category"]
            and q["status"] == "ACCEPTED"
        )
        if accepted >= festival["category_cap_per_category"]:
            err("ERR_CATEGORY_CAP_REACHED", 409,
                "The festival's category cap for this category has been reached")
        # (13) Curated fee-term completeness.
        complete = False
        if curated_fee_model == "FLAT_FEE":
            complete = curated_flat is not None
        elif curated_fee_model == "REVENUE_SHARE":
            complete = curated_share is not None and curated_tier is not None
        elif curated_fee_model == "HYBRID":
            complete = (curated_flat is not None and curated_share is not None
                        and curated_minimum is not None and curated_allowance is not None)
        if not complete:
            err("ERR_FEE_TERMS_INCOMPLETE", 400,
                "Curated fee terms are incomplete for the curated fee model")
        app["curated_fee_model"] = curated_fee_model
        app["curated_flat_fee_cents"] = curated_flat
        app["curated_revenue_share_pct_bp"] = curated_share
        app["curated_tier_mode"] = curated_tier
        app["curated_minimum_guarantee_cents"] = curated_minimum
        app["curated_free_allowance_cents"] = curated_allowance

    app["status"] = decision
    touch(app)
    return success(serialize.serialize_application(app))


@bp.route("/vendor-applications/<applicationId>/withdraw", methods=["POST"])
def withdraw(applicationId):
    uid, _ = require_role("Vendor")
    app = get_or_404(db.applications, applicationId,
                     "ERR_APPLICATION_NOT_FOUND", "Application")
    if app["vendor_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "A vendor may only withdraw its own applications")
    if app["status"] not in ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
                             "WAITLISTED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"withdraw is not permitted from {app['status']}")
    app["status"] = "WITHDRAWN"
    touch(app)
    return success(serialize.serialize_application(app))
