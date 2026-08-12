"""SpecItem and VendorBid endpoints (PRD 3.2, 3.3)."""
from flask import Blueprint

import db
import services as svc
from errors import ApiError
from middleware import (auth, require_role, body, req_str, req_int, opt_int,
                        req_enum, opt_bool)
from response import ok, paginate
from routes.projects import CATEGORIES, ANY

bp = Blueprint("specs_bids", __name__)
S = db.STORE


@bp.route("/api/spec-items", methods=["POST"])
def create_spec():
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    b = body()
    project_id = b.get("project_id")
    if not isinstance(project_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: project_id")
    category = req_enum(b, "category", CATEGORIES)
    description = req_str(b, "description")
    brand_standard_ref = req_str(b, "brand_standard_ref")
    qpr = req_int(b, "quantity_per_room", 1)
    room_count = req_int(b, "room_count", 1)
    unit_budget = req_int(b, "unit_budget_cents", 1)
    required_lead_days = opt_int(b, "required_lead_days", 21, 0)
    is_critical = opt_bool(b, "is_critical", False)
    pct = b.get("attic_target_pct", 0.05)
    if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not (0 < pct <= 1):
        raise ApiError("ERR_INVALID_REQUEST", "attic_target_pct must be > 0 and <= 1")
    attic_min = opt_int(b, "attic_min_qty", 0, 0)
    attic_max = opt_int(b, "attic_max_qty", 9999)
    if attic_max < attic_min:
        raise ApiError("ERR_INVALID_REQUEST", "attic_max_qty must be >= attic_min_qty")
    svc.get_project(project_id)
    spec = db.create("spec_items", {
        "project_id": project_id,
        "category": category,
        "description": description,
        "brand_standard_ref": brand_standard_ref,
        "quantity_per_room": qpr,
        "room_count": room_count,
        "total_qty": qpr * room_count,
        "unit_budget_cents": unit_budget,
        "required_lead_days": required_lead_days,
        "is_critical": is_critical,
        "attic_target_pct": pct,
        "attic_min_qty": attic_min,
        "attic_max_qty": attic_max,
        "attic_target_qty": 0,
        "status": "DRAFT",
    })
    return ok(db.pub(spec), 201)


@bp.route("/api/spec-items/<specItemId>", methods=["GET"])
def get_spec(specItemId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_spec(specItemId)))


@bp.route("/api/spec-items/<id>/bids", methods=["GET"])
def spec_bids(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_spec(id)
    rows = db.sorted_items(r for r in S["bids"].values() if r["spec_item_id"] == id)
    page, meta = paginate(rows)
    return ok([svc.serialize_bid(r) for r in page], 200, meta)


@bp.route("/api/spec-items/<id>/po-lines", methods=["GET"])
def spec_po_lines(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_spec(id)
    rows = db.sorted_items(r for r in S["po_lines"].values() if r["spec_item_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


@bp.route("/api/spec-items/<id>/submit", methods=["POST"])
def submit_spec(id):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    spec = svc.get_spec(id)
    if spec["status"] not in ("DRAFT", "BRAND_REJECTED"):
        raise ApiError("ERR_SPEC_NOT_SUBMITTABLE",
                       "Submit requires the spec to be DRAFT or BRAND_REJECTED")
    spec["status"] = "SUBMITTED"
    db.touch(spec)
    return ok(db.pub(spec))


@bp.route("/api/spec-items/<id>/brand-review", methods=["POST"])
def brand_review(id):
    auth_user, role = auth()
    require_role(role, ("BrandApprover",))
    spec = svc.get_spec(id)
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "REJECT"))
    if spec["status"] != "SUBMITTED":
        raise ApiError("ERR_SPEC_NOT_IN_REVIEW",
                       "brand-review requires the spec to be SUBMITTED")
    spec["status"] = "BRAND_APPROVED" if decision == "APPROVE" else "BRAND_REJECTED"
    db.touch(spec)
    return ok(db.pub(spec))


# --- VendorBid (PRD 3.3) ------------------------------------------------------

@bp.route("/api/bids", methods=["POST"])
def create_bid():
    auth_user, role = auth()
    require_role(role, ("Vendor",))
    b = body()
    spec_item_id = b.get("spec_item_id")
    if not isinstance(spec_item_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: spec_item_id")
    vendor_name = req_str(b, "vendor_name")
    unit_price = req_int(b, "unit_price_cents", 1)
    freight_est = req_int(b, "freight_estimate_cents", 0)
    lead_time = req_int(b, "lead_time_days", 0)
    spec = svc.get_spec(spec_item_id)
    if spec["status"] != "BRAND_APPROVED":
        raise ApiError("ERR_SPEC_NOT_OPEN_FOR_BIDS",
                       "Bids are only accepted against BRAND_APPROVED specs")
    bid = db.create("bids", {
        "spec_item_id": spec_item_id,
        "vendor_name": vendor_name,
        "unit_price_cents": unit_price,
        "freight_estimate_cents": freight_est,
        "lead_time_days": lead_time,
        "sample_round": 1,
        "evaluated_cost_cents": 0,
        "status": "SUBMITTED",
    })
    svc.refresh_bid_cost(bid)
    return ok(db.pub(bid), 201)


@bp.route("/api/bids/<bidId>", methods=["GET"])
def get_bid(bidId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(svc.serialize_bid(svc.get_bid(bidId)))


@bp.route("/api/bids/<bidId>/sample-decision", methods=["POST"])
def sample_decision(bidId):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    bid = svc.get_bid(bidId)
    b = body()
    outcome = req_enum(b, "outcome", ("APPROVED", "REJECTED"))
    if bid["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_NOT_SUBMITTED",
                       "sample-decision requires the bid to be SUBMITTED")
    bid["status"] = "SAMPLE_APPROVED" if outcome == "APPROVED" else "SAMPLE_REJECTED"
    db.touch(bid)
    return ok(svc.serialize_bid(bid))


@bp.route("/api/bids/<bidId>/resubmit", methods=["POST"])
def resubmit_bid(bidId):
    auth_user, role = auth()
    require_role(role, ("Vendor",))
    bid = svc.get_bid(bidId)
    b = body()
    if bid["status"] != "SAMPLE_REJECTED":
        raise ApiError("ERR_BID_NOT_RESUBMITTABLE",
                       "resubmit requires the bid to be SAMPLE_REJECTED")
    if bid["sample_round"] >= svc.SAMPLE_ROUND_MAX:
        raise ApiError("ERR_SAMPLE_ROUNDS_EXHAUSTED",
                       "sample_round has reached the hard cap of 2")
    if "unit_price_cents" in b and b["unit_price_cents"] is not None:
        bid["unit_price_cents"] = req_int(b, "unit_price_cents", 1)
    if "freight_estimate_cents" in b and b["freight_estimate_cents"] is not None:
        bid["freight_estimate_cents"] = req_int(b, "freight_estimate_cents", 0)
    if "lead_time_days" in b and b["lead_time_days"] is not None:
        bid["lead_time_days"] = req_int(b, "lead_time_days", 0)
    bid["sample_round"] += 1
    bid["status"] = "SUBMITTED"
    svc.refresh_bid_cost(bid)
    db.touch(bid)
    return ok(svc.serialize_bid(bid))


@bp.route("/api/bids/<bidId>/award", methods=["POST"])
def award_bid(bidId):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    bid = svc.get_bid(bidId)
    # 1. bid itself must be SAMPLE_APPROVED
    if bid["status"] != "SAMPLE_APPROVED":
        raise ApiError("ERR_BID_NOT_SAMPLE_APPROVED",
                       "award requires the bid to be SAMPLE_APPROVED")
    # 2. project posture must be OPEN (FROZEN reported before SEALED)
    spec = svc.get_spec(bid["spec_item_id"])
    project = svc.get_project(spec["project_id"])
    svc.check_posture_open(project)
    # 3. top-ranked eligible bid: lowest evaluated_cost_cents among
    #    SAMPLE_APPROVED bids of the spec; tie-break earliest created_at
    svc.refresh_bid_cost(bid)
    pool = [x for x in S["bids"].values()
            if x["spec_item_id"] == bid["spec_item_id"] and x["status"] == "SAMPLE_APPROVED"]
    for x in pool:
        svc.refresh_bid_cost(x)
    best = min(pool, key=lambda x: (x["evaluated_cost_cents"], x["created_at"], x["_seq"]))
    if best["id"] != bid["id"]:
        raise ApiError("ERR_BID_NOT_BEST_EVALUATED",
                       "Bid is not the top-ranked SAMPLE_APPROVED bid by evaluated cost")
    bid["status"] = "AWARDED"
    db.touch(bid)
    for x in db.sorted_items([x for x in S["bids"].values()
                              if x["spec_item_id"] == bid["spec_item_id"]
                              and x["id"] != bid["id"]]):
        if x["status"] in ("SUBMITTED", "SAMPLE_APPROVED"):
            x["status"] = "REJECTED"
            db.touch(x)
    return ok(svc.serialize_bid(bid))
