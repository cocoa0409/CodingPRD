"""Routes: surgeons and the supply item catalog."""

import db
import domain as D
import errors as E
import util as U
from errors import ApiError

SCA = "SupplyChainAnalyst"
MM = "MaterialsManager"

READ_ROLES = ["Surgeon", "SupplyChainAnalyst", "CartTechnician",
              "CirculatingNurse", "ValueAnalysisOfficer", "MaterialsManager",
              "Any"]


def register_routes(app):

    # ------------------------------------------------------------- surgeons
    @app.route("/perioperative/surgeons", methods=["POST"])
    def create_surgeon():
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        body = U.get_body()
        full_name = U.req_str(body, "full_name")
        specialty = U.req_str(body, "specialty")
        s = {
            "full_name": full_name,
            "specialty": specialty,
            "status": "ACTIVE",
        }
        D.stamp_new(s)
        db.surgeons[s["id"]] = s
        return U.success_object(D.ser_surgeon(s), 201)

    @app.route("/perioperative/surgeons/<sid>", methods=["GET"])
    def get_surgeon(sid):
        U.authenticate()
        s = D.get_or_404(db.surgeons, sid, "Surgeon")
        return U.success_object(D.ser_surgeon(s), 200)

    @app.route("/perioperative/surgeons/<sid>/deactivate", methods=["POST"])
    def deactivate_surgeon(sid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        s = D.get_or_404(db.surgeons, sid, "Surgeon")
        if s["status"] != "ACTIVE":
            raise ApiError(E.ERR_INVALID_STATE,
                           "Surgeon is not ACTIVE", 409)
        s["status"] = "INACTIVE"
        D.bump(s)
        return U.success_object(D.ser_surgeon(s), 200)

    # ---------------------------------------------------------- supply items
    @app.route("/perioperative/supply-items", methods=["POST"])
    def create_supply_item():
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        body = U.get_body()
        sku = U.req_str(body, "sku")
        name = U.req_str(body, "name")
        unit_cost_cents = U.req_int(body, "unit_cost_cents")
        if unit_cost_cents < 1:
            raise ApiError(E.ERR_INVALID_REQUEST,
                           "Field 'unit_cost_cents' must be >= 1", 400)
        substitute_group = U.opt_str(body, "substitute_group")
        consignment_flag = U.opt_bool(body, "consignment_flag", False)
        initial_on_hand = U.opt_int(body, "initial_on_hand", 0)
        if initial_on_hand < 0:
            raise ApiError(E.ERR_INVALID_QUANTITY,
                           "Field 'initial_on_hand' must be >= 0", 400)
        if any(i["sku"] == sku for i in db.supply_items.values()):
            raise ApiError(E.ERR_INVALID_REQUEST,
                           f"sku '{sku}' already exists", 400)
        item = {
            "sku": sku,
            "name": name,
            "unit_cost_cents": unit_cost_cents,
            "substitute_group": substitute_group,
            "consignment_flag": consignment_flag,
            "on_hand_quantity": initial_on_hand,
            "status": "ACTIVE",
        }
        D.stamp_new(item)
        db.supply_items[item["id"]] = item
        return U.success_object(D.ser_supply_item(item), 201)

    @app.route("/perioperative/supply-items", methods=["GET"])
    def list_supply_items():
        U.authenticate()
        limit, offset = U.pagination_params()
        items = U.apply_filters(list(db.supply_items.values()), [
            ("substitute_group", "substitute_group"),
            ("consignment_flag", "consignment_flag"),
            ("status", "status"),
        ])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_supply_item(i) for i in page],
                              total, limit, offset)

    @app.route("/perioperative/supply-items/<iid>", methods=["GET"])
    def get_supply_item(iid):
        U.authenticate()
        item = D.get_or_404(db.supply_items, iid, "SupplyItem")
        return U.success_object(D.ser_supply_item(item), 200)

    @app.route("/perioperative/supply-items/<iid>/stock-adjustments",
               methods=["POST"])
    def stock_adjustment(iid):
        _, role = U.authenticate()
        U.authorize(role, [MM])
        body = U.get_body()
        delta_qty = U.req_int(body, "delta_qty")
        U.req_str(body, "reason")
        item = D.get_or_404(db.supply_items, iid, "SupplyItem")
        new_qty = item["on_hand_quantity"] + delta_qty
        if new_qty < 0:
            raise ApiError(E.ERR_INVALID_QUANTITY,
                           "Adjustment would drop on_hand_quantity below zero",
                           400)
        item["on_hand_quantity"] = new_qty
        D.bump(item)
        return U.success_object(D.ser_supply_item(item), 200)
