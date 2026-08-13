"""Routes: consignment counts and consignment charges."""

import db
import domain as D
import errors as E
import util as U
from errors import ApiError

MM = "MaterialsManager"


def register_routes(app):

    # ------------------------------------------------------ consignment counts
    @app.route("/perioperative/consignment-counts", methods=["POST"])
    def create_count():
        _, role = U.authenticate()
        U.authorize(role, [MM])
        body = U.get_body()
        supply_item_id = U.req_str(body, "supply_item_id")
        counted_qty = U.req_int(body, "counted_qty")
        if counted_qty < 0:
            raise ApiError(E.ERR_INVALID_QUANTITY,
                           "Field 'counted_qty' must be >= 0", 400)
        item = D.get_or_404(db.supply_items, supply_item_id, "SupplyItem")
        if not item["consignment_flag"]:
            raise ApiError(E.ERR_NOT_CONSIGNMENT_ITEM,
                           "Item is not a consignment item", 409)
        system_qty = item["on_hand_quantity"]
        variance_qty = counted_qty - system_qty
        count = {
            "supply_item_id": supply_item_id,
            "counted_qty": counted_qty,
            "system_qty_at_count": system_qty,
            "variance_qty": variance_qty,
            "variance_value_cents": variance_qty * item["unit_cost_cents"],
            "status": "RECORDED",
        }
        D.stamp_new(count)
        db.consignment_counts[count["id"]] = count
        return U.success_object(D.ser_consignment_count(count), 201)

    @app.route("/perioperative/consignment-counts", methods=["GET"])
    def list_counts():
        U.authenticate()
        limit, offset = U.pagination_params()
        counts = U.apply_filters(list(db.consignment_counts.values()), [
            ("supply_item_id", "supply_item_id"),
            ("status", "status"),
        ])
        page, total = U.paginate(counts, limit, offset)
        return U.success_list([D.ser_consignment_count(c) for c in page],
                              total, limit, offset)

    @app.route("/perioperative/consignment-counts/<cid>", methods=["GET"])
    def get_count(cid):
        U.authenticate()
        count = D.get_or_404(db.consignment_counts, cid, "ConsignmentCount")
        return U.success_object(D.ser_consignment_count(count), 200)

    @app.route("/perioperative/consignment-counts/<cid>/verify",
               methods=["POST"])
    def verify_count(cid):
        _, role = U.authenticate()
        U.authorize(role, [MM])
        count = D.get_or_404(db.consignment_counts, cid, "ConsignmentCount")
        if count["status"] != "RECORDED":
            raise ApiError(E.ERR_COUNT_NOT_RECORDED,
                           "Count is not RECORDED", 409)
        count["status"] = "VERIFIED"
        D.bump(count)
        if count["variance_qty"] != 0:
            item = db.supply_items.get(count["supply_item_id"])
            if item is not None:
                item["on_hand_quantity"] += count["variance_qty"]
                D.bump(item)
        return U.success_object(D.ser_consignment_count(count), 200)

    # ----------------------------------------------------- consignment charges
    @app.route("/perioperative/consignment-charges", methods=["GET"])
    def list_charges():
        U.authenticate()
        limit, offset = U.pagination_params()
        charges = U.apply_filters(list(db.consignment_charges.values()), [
            ("case_id", "case_id"),
            ("supply_item_id", "supply_item_id"),
            ("usage_record_id", "usage_record_id"),
            ("status", "status"),
        ])
        page, total = U.paginate(charges, limit, offset)
        return U.success_list([D.ser_consignment_charge(c) for c in page],
                              total, limit, offset)

    @app.route("/perioperative/consignment-charges/<cid>", methods=["GET"])
    def get_charge(cid):
        U.authenticate()
        charge = D.get_or_404(db.consignment_charges, cid, "ConsignmentCharge")
        return U.success_object(D.ser_consignment_charge(charge), 200)

    @app.route("/perioperative/consignment-charges/<cid>/capture",
               methods=["POST"])
    def capture_charge(cid):
        _, role = U.authenticate()
        U.authorize(role, [MM])
        charge = D.get_or_404(db.consignment_charges, cid, "ConsignmentCharge")
        if charge["status"] != "PENDING":
            raise ApiError(E.ERR_CHARGE_INVALID_STATE,
                           "Charge is not PENDING", 409)
        charge["status"] = "CAPTURED"
        D.bump(charge)
        return U.success_object(D.ser_consignment_charge(charge), 200)

    @app.route("/perioperative/consignment-charges/<cid>/void", methods=["POST"])
    def void_charge(cid):
        _, role = U.authenticate()
        U.authorize(role, [MM])
        charge = D.get_or_404(db.consignment_charges, cid, "ConsignmentCharge")
        if charge["status"] not in ("PENDING", "CAPTURED"):
            raise ApiError(E.ERR_CHARGE_INVALID_STATE,
                           "Charge is not PENDING or CAPTURED", 409)
        charge["status"] = "VOIDED"
        D.bump(charge)
        return U.success_object(D.ser_consignment_charge(charge), 200)
