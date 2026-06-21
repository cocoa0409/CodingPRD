"""Build jobs and warranty claims (PRD §3.9, §3.10)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok, created, list_ok
import helpers as h
import services as svc

bp = Blueprint("builds", __name__)


# ---------------- BuildJob ----------------
@bp.route("/shop/build-jobs", methods=["POST"])
def create_build():
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    body = h.get_body()
    with db.LOCK:
        customer_id = h.require_str(body, "customer_id")
        frame_sku_id = h.require_str(body, "frame_sku_id")
        required_part_count = h.require_int(body, "required_part_count", minimum=1)
        h.must_exist(db.customers, customer_id)
        frame = h.must_exist(db.skus, frame_sku_id)
        # priority 10: frame must be a BIKE
        if frame["category"] != "BIKE":
            raise ApiError("ERR_FRAME_NOT_BIKE", "Frame Sku must be a BIKE.")
        rec = {
            "customer_id": customer_id,
            "frame_sku_id": frame_sku_id,
            "required_part_count": required_part_count,
            "reserved_part_count": 0,
            "status": "DRAFT",
            "build_fee_cents": 0,
        }
        h.stamp_create(rec)
        db.build_jobs[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/build-jobs/<bid>", methods=["GET"])
def read_build(bid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.build_jobs, bid)
        rec["reserved_part_count"] = svc.reserved_part_count(rec)
        return ok(h.public(rec))


@bp.route("/shop/build-jobs", methods=["GET"])
def list_builds():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.build_jobs.values())
        for f in ("customer_id", "frame_sku_id"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        for r in recs:
            r["reserved_part_count"] = svc.reserved_part_count(r)
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/build-jobs/<bid>/reserve-part", methods=["POST"])
def reserve_part(bid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    body = h.get_body()
    with db.LOCK:
        rec = h.must_exist(db.build_jobs, bid)
        sku_id = h.require_str(body, "sku_id")
        qty = h.optional_int(body, "qty", default=1, minimum=1)
        sku = h.must_exist(db.skus, sku_id)
        if rec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Parts may only be reserved on a DRAFT build.")
        svc.create_reservation(sku_id, "BUILD_JOB", bid, qty)
        h.touch(sku)
        svc.reconcile_sku(sku)
        rec["reserved_part_count"] = svc.reserved_part_count(rec)
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/build-jobs/<bid>/reserve-frame", methods=["POST"])
def reserve_frame(bid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.build_jobs, bid)
        if rec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Frame may only be reserved on a DRAFT build.")
        sku = db.skus[rec["frame_sku_id"]]
        svc.create_reservation(rec["frame_sku_id"], "BUILD_JOB", bid, 1)
        h.touch(sku)
        svc.reconcile_sku(sku)
        rec["reserved_part_count"] = svc.reserved_part_count(rec)
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/build-jobs/<bid>/mark-parts-reserved", methods=["POST"])
def mark_parts_reserved(bid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.build_jobs, bid)
        if rec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Mark-parts-reserved requires DRAFT.")
        # priority 11: readiness — reserved_part_count >= required and frame ACTIVE
        rec["reserved_part_count"] = svc.reserved_part_count(rec)
        if (rec["reserved_part_count"] < rec["required_part_count"]
                or not svc.frame_reservation_active(rec)):
            raise ApiError("ERR_BUILD_NOT_READY", "Build is not ready.")
        rec["status"] = "PARTS_RESERVED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/build-jobs/<bid>/start", methods=["POST"])
def start_build(bid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.build_jobs, bid)
        if rec["status"] != "PARTS_RESERVED":
            raise ApiError("ERR_INVALID_STATE", "Start requires PARTS_RESERVED.")
        rec["build_fee_cents"] = svc.build_fee(rec["required_part_count"])
        rec["status"] = "ASSEMBLING"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/build-jobs/<bid>/complete", methods=["POST"])
def complete_build(bid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.build_jobs, bid)
        if rec["status"] != "ASSEMBLING":
            raise ApiError("ERR_INVALID_STATE", "Complete requires ASSEMBLING.")
        for res in svc.active_reservations_for("BUILD_JOB", bid):
            svc.commit_reservation(res)
        rec["reserved_part_count"] = svc.reserved_part_count(rec)
        rec["status"] = "COMPLETED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/build-jobs/<bid>/cancel", methods=["POST"])
def cancel_build(bid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.build_jobs, bid)
        if rec["status"] not in ("DRAFT", "PARTS_RESERVED", "ASSEMBLING"):
            raise ApiError("ERR_INVALID_STATE", "Cancel requires DRAFT, PARTS_RESERVED, or ASSEMBLING.")
        for res in svc.active_reservations_for("BUILD_JOB", bid):
            svc.release_reservation(res)
        rec["reserved_part_count"] = svc.reserved_part_count(rec)
        rec["status"] = "CANCELLED"
        h.touch(rec)
        return ok(h.public(rec))


# ---------------- WarrantyClaim ----------------
DEFECT_PARTS = {"FRAME", "COMPONENT"}
RESOLUTIONS = {"REPAIR", "REPLACE"}


def _purchase_check(claim):
    """ERR_NOT_PURCHASED: source_order_line_id belongs to a DELIVERED SalesOrder
    whose customer_id == claim.customer_id (PRD §3.10, priority 8)."""
    line = db.order_lines.get(claim["source_order_line_id"])
    if line is None:
        return False
    order = db.sales_orders.get(line["order_id"])
    if order is None:
        return False
    return (order["fulfillment_status"] == "DELIVERED"
            and order["customer_id"] == claim["customer_id"])


@bp.route("/shop/warranty-claims", methods=["POST"])
def create_warranty_claim():
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor", "Customer"])
    body = h.get_body()
    with db.LOCK:
        customer_id = h.require_str(body, "customer_id")
        sku_id = h.require_str(body, "sku_id")
        source_order_line_id = h.require_str(body, "source_order_line_id")
        defect_part = h.require_enum(body, "defect_part", DEFECT_PARTS)
        h.must_exist(db.customers, customer_id)
        h.must_exist(db.skus, sku_id)
        h.must_exist(db.order_lines, source_order_line_id)
        rec = {
            "customer_id": customer_id,
            "sku_id": sku_id,
            "source_order_line_id": source_order_line_id,
            "defect_part": defect_part,
            "status": "SUBMITTED",
            "resolution_sku_id": None,
        }
        # priority 8: purchase check at submission
        if not _purchase_check(rec):
            raise ApiError("ERR_NOT_PURCHASED", "Source line is not a delivered purchase by this customer.")
        h.stamp_create(rec)
        db.warranty_claims[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/warranty-claims/<wid>", methods=["GET"])
def read_warranty_claim(wid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.warranty_claims, wid)
        return ok(h.public(rec))


@bp.route("/shop/warranty-claims", methods=["GET"])
def list_warranty_claims():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.warranty_claims.values())
        for f in ("customer_id", "sku_id", "source_order_line_id", "resolution_sku_id"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/warranty-claims/<wid>/review", methods=["POST"])
def review_warranty_claim(wid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.warranty_claims, wid)
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Review requires SUBMITTED.")
        rec["status"] = "UNDER_REVIEW"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/warranty-claims/<wid>/approve", methods=["POST"])
def approve_warranty_claim(wid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    body = h.get_body()
    with db.LOCK:
        rec = h.must_exist(db.warranty_claims, wid)
        resolution = h.require_enum(body, "resolution", RESOLUTIONS)
        resolution_sku_id = h.optional_str(body, "resolution_sku_id", default=None)
        if resolution_sku_id is not None:
            h.must_exist(db.skus, resolution_sku_id)
        # priority 5: state
        if rec["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Approve requires UNDER_REVIEW.")
        # priority 8: purchase check (again at approval)
        if not _purchase_check(rec):
            raise ApiError("ERR_NOT_PURCHASED", "Source line is not a delivered purchase by this customer.")
        # priority 9: coverage
        sku = db.skus[rec["sku_id"]]
        if rec["defect_part"] == "FRAME":
            if not (sku["warranty_class"] == "FRAME_AND_COMPONENT" and sku["is_serialized"]):
                raise ApiError("ERR_WARRANTY_NOT_COVERED", "Frame defect not covered.")
        else:  # COMPONENT
            if sku["warranty_class"] not in ("COMPONENT", "FRAME_AND_COMPONENT"):
                raise ApiError("ERR_WARRANTY_NOT_COVERED", "Component defect not covered.")

        if resolution == "REPAIR":
            rec["status"] = "APPROVED_REPAIR"
            h.touch(rec)
            return ok(h.public(rec))
        else:  # REPLACE
            if resolution_sku_id is None:
                raise ApiError("ERR_INVALID_REQUEST", "resolution_sku_id required for REPLACE.")
            resolution_sku = db.skus[resolution_sku_id]
            # priority 13: availability of replacement Sku
            if svc.available_units(resolution_sku) < 1:
                raise ApiError("ERR_INSUFFICIENT_STOCK", "Replacement Sku unavailable.")
            # determine the source order to hold the reservation under (SALES_ORDER)
            line = db.order_lines[rec["source_order_line_id"]]
            source_order_id = line["order_id"]
            res = svc.create_reservation(resolution_sku_id, "SALES_ORDER", source_order_id, 1)
            h.touch(resolution_sku)
            svc.reconcile_sku(resolution_sku)
            rec["resolution_sku_id"] = resolution_sku_id
            rec["_replacement_reservation_id"] = res["id"]
            rec["status"] = "APPROVED_REPLACE"
            h.touch(rec)
            return ok(h.public(rec))


@bp.route("/shop/warranty-claims/<wid>/deny", methods=["POST"])
def deny_warranty_claim(wid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.warranty_claims, wid)
        if rec["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Deny requires UNDER_REVIEW.")
        rec["status"] = "DENIED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/warranty-claims/<wid>/resolve", methods=["POST"])
def resolve_warranty_claim(wid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.warranty_claims, wid)
        if rec["status"] != "APPROVED_REPLACE":
            raise ApiError("ERR_INVALID_STATE", "Resolve requires APPROVED_REPLACE.")
        # commit the replacement reservation created at approval
        res_id = rec.get("_replacement_reservation_id")
        res = db.reservations.get(res_id) if res_id else None
        if res is not None and res["status"] == "ACTIVE":
            svc.commit_reservation(res)
        rec["status"] = "RESOLVED"
        h.touch(rec)
        return ok(h.public(rec))
