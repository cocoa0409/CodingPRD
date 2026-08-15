"""Routes: product requests (value-analysis pipeline)."""

import db
import domain as D
import errors as E
import util as U
from errors import ApiError

SURGEON = "Surgeon"
VAO = "ValueAnalysisOfficer"


def register_routes(app):

    @app.route("/perioperative/product-requests", methods=["POST"])
    def create_product_request():
        uid, role = U.authenticate()
        U.authorize(role, [SURGEON])
        body = U.get_body()
        proposed_item_name = U.req_str(body, "proposed_item_name")
        proposed_sku = U.req_str(body, "proposed_sku")
        estimated_unit_cost_cents = U.req_int(body, "estimated_unit_cost_cents")
        if estimated_unit_cost_cents < 1:
            raise ApiError(E.ERR_INVALID_REQUEST,
                           "Field 'estimated_unit_cost_cents' must be >= 1",
                           400)
        rationale = U.req_str(body, "rationale")
        if len(rationale) < 10:
            raise ApiError(E.ERR_INVALID_REQUEST,
                           "Field 'rationale' must be at least 10 characters",
                           400)
        substitute_group = U.opt_str(body, "substitute_group")
        consignment_flag = U.opt_bool(body, "consignment_flag", False)
        replaces_item_id = U.opt_str(body, "replaces_item_id")
        # Entity-backed caller: X-User-ID is the acting Surgeon's id
        surgeon = db.surgeons.get(uid)
        if surgeon is None:
            raise ApiError(E.ERR_NOT_FOUND,
                           f"Surgeon '{uid}' not found", 404)
        if replaces_item_id is not None:
            D.get_or_404(db.supply_items, replaces_item_id, "SupplyItem")
        if surgeon["status"] != "ACTIVE":
            raise ApiError(E.ERR_SURGEON_INACTIVE,
                           "Requesting surgeon is INACTIVE", 409)
        if any(i["sku"] == proposed_sku for i in db.supply_items.values()):
            raise ApiError(E.ERR_INVALID_REQUEST,
                           f"sku '{proposed_sku}' already exists", 400)
        req = {
            "surgeon_id": uid,
            "proposed_item_name": proposed_item_name,
            "proposed_sku": proposed_sku,
            "estimated_unit_cost_cents": estimated_unit_cost_cents,
            "rationale": rationale,
            "substitute_group": substitute_group,
            "consignment_flag": consignment_flag,
            "replaces_item_id": replaces_item_id,
            "status": "SUBMITTED",
            "reviewing_officer_id": None,
            "endorser_ids": [],
            "endorsements_count": 0,
            "rejection_reason": None,
            "created_item_id": None,
        }
        D.stamp_new(req)
        db.product_requests[req["id"]] = req
        return U.success_object(D.ser_product_request(req), 201)

    @app.route("/perioperative/product-requests", methods=["GET"])
    def list_product_requests():
        U.authenticate()
        limit, offset = U.pagination_params()
        reqs = U.apply_filters(list(db.product_requests.values()), [
            ("surgeon_id", "surgeon_id"),
            ("status", "status"),
            ("replaces_item_id", "replaces_item_id"),
            ("created_item_id", "created_item_id"),
        ])
        page, total = U.paginate(reqs, limit, offset)
        return U.success_list([D.ser_product_request(r) for r in page],
                              total, limit, offset)

    @app.route("/perioperative/product-requests/<rid>", methods=["GET"])
    def get_product_request(rid):
        U.authenticate()
        req = D.get_or_404(db.product_requests, rid, "ProductRequest")
        return U.success_object(D.ser_product_request(req), 200)

    @app.route("/perioperative/product-requests/<rid>/open-review",
               methods=["POST"])
    def open_review(rid):
        uid, role = U.authenticate()
        U.authorize(role, [VAO])
        req = D.get_or_404(db.product_requests, rid, "ProductRequest")
        if req["status"] != "SUBMITTED":
            raise ApiError(E.ERR_REQUEST_NOT_UNDER_REVIEW,
                           "Request is not SUBMITTED", 409)
        req["status"] = "UNDER_REVIEW"
        req["reviewing_officer_id"] = uid
        D.bump(req)
        return U.success_object(D.ser_product_request(req), 200)

    @app.route("/perioperative/product-requests/<rid>/endorse", methods=["POST"])
    def endorse(rid):
        uid, role = U.authenticate()
        U.authorize(role, [VAO])
        req = D.get_or_404(db.product_requests, rid, "ProductRequest")
        if req["status"] != "UNDER_REVIEW":
            raise ApiError(E.ERR_REQUEST_NOT_UNDER_REVIEW,
                           "Request is not UNDER_REVIEW", 409)
        if uid in req["endorser_ids"]:
            raise ApiError(E.ERR_DUPLICATE_ENDORSEMENT,
                           "Officer has already endorsed this request", 409)
        req["endorser_ids"].append(uid)
        req["endorsements_count"] += 1
        D.bump(req)
        return U.success_object(D.ser_product_request(req), 200)

    @app.route("/perioperative/product-requests/<rid>/approve", methods=["POST"])
    def approve(rid):
        uid, role = U.authenticate()
        U.authorize(role, [VAO])
        req = D.get_or_404(db.product_requests, rid, "ProductRequest")
        if req["status"] != "UNDER_REVIEW":
            raise ApiError(E.ERR_REQUEST_NOT_UNDER_REVIEW,
                           "Request is not UNDER_REVIEW", 409)
        if req["endorsements_count"] < 2:
            raise ApiError(E.ERR_QUORUM_NOT_MET,
                           "Request has fewer than 2 endorsements", 409)
        if uid == req["reviewing_officer_id"]:
            raise ApiError(E.ERR_SOD_REVIEWER_CANNOT_APPROVE,
                           "The officer who opened review cannot approve", 403)
        surgeon = db.surgeons.get(req["surgeon_id"])
        if surgeon is None or surgeon["status"] != "ACTIVE":
            raise ApiError(E.ERR_REQUESTER_INACTIVE,
                           "Requesting surgeon is INACTIVE", 409)
        # SKU uniqueness is enforced again at approval time
        if any(i["sku"] == req["proposed_sku"]
               for i in db.supply_items.values()):
            raise ApiError(E.ERR_INVALID_REQUEST,
                           f"sku '{req['proposed_sku']}' already exists", 400)
        item = {
            "sku": req["proposed_sku"],
            "name": req["proposed_item_name"],
            "unit_cost_cents": req["estimated_unit_cost_cents"],
            "substitute_group": req["substitute_group"],
            "consignment_flag": req["consignment_flag"],
            "on_hand_quantity": 0,
            "status": "ACTIVE",
        }
        D.stamp_new(item)
        db.supply_items[item["id"]] = item
        req["created_item_id"] = item["id"]
        if req["replaces_item_id"] is not None:
            replaced = db.supply_items.get(req["replaces_item_id"])
            if replaced is not None and replaced["status"] == "ACTIVE":
                replaced["status"] = "DISCONTINUED"
                D.bump(replaced)
        req["status"] = "APPROVED"
        D.bump(req)
        return U.success_object(D.ser_product_request(req), 200)

    @app.route("/perioperative/product-requests/<rid>/reject", methods=["POST"])
    def reject(rid):
        _, role = U.authenticate()
        U.authorize(role, [VAO])
        body = U.get_body()
        rejection_reason = U.req_str(body, "rejection_reason")
        req = D.get_or_404(db.product_requests, rid, "ProductRequest")
        if req["status"] != "UNDER_REVIEW":
            raise ApiError(E.ERR_REQUEST_NOT_UNDER_REVIEW,
                           "Request is not UNDER_REVIEW", 409)
        req["rejection_reason"] = rejection_reason
        req["status"] = "REJECTED"
        D.bump(req)
        return U.success_object(D.ser_product_request(req), 200)
