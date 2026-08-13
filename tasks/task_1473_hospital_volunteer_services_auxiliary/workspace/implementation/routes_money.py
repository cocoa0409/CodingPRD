"""Routes: fundraising campaigns, gift shop items/sales, recognition events."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from core import (
    db, now, today, auth, require_role, body, ok_object, page_list, get_or_404,
    raise_err, touch, new_rec, req_str, opt_str, req_int, opt_int, req_datetime,
    ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_CAMPAIGN_INVALID_STATE,
    ERR_CAMPAIGN_WINDOW_MISMATCH, ERR_SOD_DISBURSEMENT, ERR_DISBURSEMENT_COOLING_OFF,
    ERR_DISBURSEMENT_EXCEEDS_BALANCE, ERR_ITEM_INACTIVE, ERR_INSUFFICIENT_STOCK,
    ERR_INSUFFICIENT_TENDER, ERR_SALE_ALREADY_VOIDED, ERR_VOID_WINDOW_ELAPSED,
    ERR_CASHIER_NOT_GIFT_SHOP_PLACED,
)
from domain import (
    is_junior_at, recognition_points, tier_for_points,
    ser_campaign, ser_item, ser_sale, ser_event,
)

CAMPAIGN_STATUS = ["DRAFT", "ACTIVE", "CLOSED", "RECONCILED"]
SALE_STATUS = ["COMPLETED", "VOIDED"]
CAMPAIGN_READERS = ["VolunteerServicesDirector", "VolunteerCoordinator",
                    "AuxiliaryTreasurer"]
ITEM_READERS = ["VolunteerServicesDirector", "VolunteerCoordinator",
                "AuxiliaryTreasurer", "Volunteer"]
SALE_READERS = ITEM_READERS
EVENT_READERS = ["VolunteerServicesDirector", "VolunteerCoordinator", "Volunteer"]
TIER_DISCOUNT = {"BRONZE": 5, "SILVER": 10, "GOLD": 15, "PRESIDENT": 20}


def _parse_bool_param(raw, field):
    if raw is None:
        return None
    low = raw.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise_err(ERR_INVALID_REQUEST, "Query parameter '%s' must be true or false" % field)


def register(app):

    # ------------------------------------------------------------- campaigns
    @app.route("/auxiliary/fundraising-campaigns", methods=["POST"])
    def create_campaign():
        uid, role = auth()
        data = body()
        name = req_str(data, "name")
        goal_cents = req_int(data, "goal_cents", minimum=0)
        start_at = req_datetime(data, "start_at")
        end_at = req_datetime(data, "end_at")
        promo = opt_int(data, "promo_discount_pct", 0, minimum=0, maximum=50)
        if not (end_at > start_at):
            raise_err(ERR_INVALID_REQUEST, "end_at must be strictly after start_at")
        require_role(role, ["AuxiliaryTreasurer"])
        rec = new_rec()
        rec.update({"name": name, "goal_cents": goal_cents, "start_at": start_at,
                    "end_at": end_at, "promo_discount_pct": promo, "status": "DRAFT",
                    "created_by_user_id": uid, "closed_at": None, "disbursed_cents": 0})
        db["campaigns"][rec["id"]] = rec
        return ok_object(ser_campaign(rec), 201)

    @app.route("/auxiliary/fundraising-campaigns", methods=["GET"])
    def list_campaigns():
        uid, role = auth()
        require_role(role, CAMPAIGN_READERS)
        status = request.args.get("status")
        if status is not None and status not in CAMPAIGN_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        return page_list(db["campaigns"].values(), ser_campaign,
                         filters={"status": status})

    @app.route("/auxiliary/fundraising-campaigns/<rid>", methods=["GET"])
    def get_campaign(rid):
        uid, role = auth()
        require_role(role, CAMPAIGN_READERS)
        return ok_object(ser_campaign(get_or_404("campaigns", rid, "FundraisingCampaign")))

    @app.route("/auxiliary/fundraising-campaigns/<rid>/activate", methods=["POST"])
    def activate_campaign(rid):
        uid, role = auth()
        body()
        require_role(role, ["AuxiliaryTreasurer"])
        rec = get_or_404("campaigns", rid, "FundraisingCampaign")
        if rec["status"] != "DRAFT":
            raise_err(ERR_CAMPAIGN_INVALID_STATE, "Campaign is not DRAFT")
        n = now()
        if not (rec["start_at"] <= n < rec["end_at"]):
            raise_err(ERR_CAMPAIGN_WINDOW_MISMATCH,
                      "now is outside the campaign window")
        rec["status"] = "ACTIVE"
        touch(rec)
        return ok_object(ser_campaign(rec))

    @app.route("/auxiliary/fundraising-campaigns/<rid>/close", methods=["POST"])
    def close_campaign(rid):
        uid, role = auth()
        body()
        require_role(role, ["AuxiliaryTreasurer"])
        rec = get_or_404("campaigns", rid, "FundraisingCampaign")
        if rec["status"] != "ACTIVE":
            raise_err(ERR_CAMPAIGN_INVALID_STATE, "Campaign is not ACTIVE")
        n = now()
        if not (n >= rec["end_at"]):
            raise_err(ERR_CAMPAIGN_WINDOW_MISMATCH, "Campaign window has not ended")
        rec["status"] = "CLOSED"
        rec["closed_at"] = n
        touch(rec)
        return ok_object(ser_campaign(rec))

    @app.route("/auxiliary/fundraising-campaigns/<rid>/reconcile", methods=["POST"])
    def reconcile_campaign(rid):
        uid, role = auth()
        body()
        require_role(role, ["AuxiliaryTreasurer"])
        rec = get_or_404("campaigns", rid, "FundraisingCampaign")
        if rec["status"] != "CLOSED":
            raise_err(ERR_CAMPAIGN_INVALID_STATE, "Campaign is not CLOSED")
        rec["status"] = "RECONCILED"
        touch(rec)
        return ok_object(ser_campaign(rec))

    @app.route("/auxiliary/fundraising-campaigns/<rid>/disburse", methods=["POST"])
    def disburse_campaign(rid):
        uid, role = auth()
        data = body()
        amount_cents = req_int(data, "amount_cents", minimum=0)
        req_str(data, "recipient", nonempty=True)
        opt_str(data, "notes")
        require_role(role, ["AuxiliaryTreasurer"])
        rec = get_or_404("campaigns", rid, "FundraisingCampaign")
        if uid == rec["created_by_user_id"]:
            raise_err(ERR_SOD_DISBURSEMENT,
                      "Disbursing treasurer must differ from the campaign creator")
        if rec["status"] != "RECONCILED":
            raise_err(ERR_CAMPAIGN_INVALID_STATE, "Campaign is not RECONCILED")
        n = now()
        if rec["closed_at"] is None or n < rec["closed_at"] + timedelta(days=7):
            raise_err(ERR_DISBURSEMENT_COOLING_OFF,
                      "Disbursement cooling-off period has not elapsed")
        from domain import campaign_figures
        _, _, net = campaign_figures(rec)
        if amount_cents > net - rec["disbursed_cents"]:
            raise_err(ERR_DISBURSEMENT_EXCEEDS_BALANCE,
                      "Amount exceeds net proceeds minus prior disbursements")
        rec["disbursed_cents"] += amount_cents
        touch(rec)
        return ok_object(ser_campaign(rec))

    # ------------------------------------------------------------------ items
    @app.route("/auxiliary/gift-shop-items", methods=["POST"])
    def create_item():
        uid, role = auth()
        data = body()
        sku = req_str(data, "sku")
        name = req_str(data, "name")
        price = req_int(data, "unit_price_cents", minimum=0)
        cost = req_int(data, "unit_cost_cents", minimum=0)
        if cost > price:
            raise_err(ERR_INVALID_REQUEST,
                      "unit_cost_cents must not exceed unit_price_cents")
        stock = opt_int(data, "stock_on_hand", 0, minimum=0)
        reorder = opt_int(data, "reorder_level", 0, minimum=0)
        require_role(role, ["AuxiliaryTreasurer"])
        rec = new_rec()
        rec.update({"sku": sku, "name": name, "unit_price_cents": price,
                    "unit_cost_cents": cost, "stock_on_hand": stock,
                    "reorder_level": reorder, "is_active": True})
        db["items"][rec["id"]] = rec
        return ok_object(ser_item(rec), 201)

    @app.route("/auxiliary/gift-shop-items", methods=["GET"])
    def list_items():
        uid, role = auth()
        require_role(role, ITEM_READERS)
        is_active = _parse_bool_param(request.args.get("is_active"), "is_active")
        return page_list(db["items"].values(), ser_item,
                         filters={"is_active": is_active})

    @app.route("/auxiliary/gift-shop-items/<rid>", methods=["GET"])
    def get_item(rid):
        uid, role = auth()
        require_role(role, ITEM_READERS)
        return ok_object(ser_item(get_or_404("items", rid, "GiftShopItem")))

    @app.route("/auxiliary/gift-shop-items/<rid>", methods=["PUT"])
    def update_item(rid):
        uid, role = auth()
        data = body()
        price = opt_int(data, "unit_price_cents", None, minimum=0)
        restock = opt_int(data, "restock_qty", None, minimum=0)
        reorder = opt_int(data, "reorder_level", None, minimum=0)
        is_active = data.get("is_active", None)
        if is_active is not None and not isinstance(is_active, bool):
            raise_err(ERR_INVALID_REQUEST, "is_active must be a boolean")
        require_role(role, ["AuxiliaryTreasurer"])
        rec = get_or_404("items", rid, "GiftShopItem")
        if price is not None:
            if price < rec["unit_cost_cents"]:
                raise_err(ERR_INVALID_REQUEST,
                          "unit_price_cents must not be below unit_cost_cents")
            rec["unit_price_cents"] = price
        if restock is not None:
            rec["stock_on_hand"] += restock
        if reorder is not None:
            rec["reorder_level"] = reorder
        if is_active is not None:
            rec["is_active"] = is_active
        touch(rec)
        return ok_object(ser_item(rec))

    # ------------------------------------------------------------------ sales
    @app.route("/auxiliary/gift-shop-sales", methods=["POST"])
    def create_sale():
        uid, role = auth()
        data = body()
        cashier_id = req_str(data, "cashier_volunteer_id")
        buyer_id = opt_str(data, "buyer_volunteer_id")
        campaign_id = opt_str(data, "campaign_id")
        lines = data.get("lines")
        if not isinstance(lines, list) or len(lines) == 0:
            raise_err(ERR_INVALID_REQUEST, "lines must be a non-empty array")
        norm_lines = []
        for ln in lines:
            if not isinstance(ln, dict):
                raise_err(ERR_INVALID_REQUEST, "each line must be an object")
            item_id = ln.get("item_id")
            qty = ln.get("qty")
            if not isinstance(item_id, str):
                raise_err(ERR_INVALID_REQUEST, "line item_id is required")
            if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
                raise_err(ERR_INVALID_REQUEST, "line qty must be an integer >= 1")
            norm_lines.append({"item_id": item_id, "qty": qty})
        tendered = req_int(data, "tendered_cents", minimum=0)
        require_role(role, ["Volunteer", "AuxiliaryTreasurer"])
        # tier 4: existence, body FKs in declared order
        cashier = get_or_404("volunteers", cashier_id, "Volunteer")
        buyer = None
        if buyer_id is not None:
            buyer = get_or_404("volunteers", buyer_id, "Volunteer")
        campaign = None
        if campaign_id is not None:
            campaign = get_or_404("campaigns", campaign_id, "FundraisingCampaign")
        items = [get_or_404("items", ln["item_id"], "GiftShopItem") for ln in norm_lines]
        # tier 5: ownership
        if role == "Volunteer" and uid != cashier_id:
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      "Volunteers may only ring sales as themselves")
        # tier 10: item active
        for it in items:
            if not it["is_active"]:
                raise_err(ERR_ITEM_INACTIVE, "Item %s is inactive" % it["id"])
        # tier 12: cashier eligibility, then campaign attribution validity
        cashier_ok = cashier["service_status"] == "ACTIVE" and any(
            p["volunteer_id"] == cashier_id and p["status"] == "ACCEPTED"
            and db["requests"].get(p["request_id"]) is not None
            and db["roles"].get(db["requests"][p["request_id"]]["role_id"]) is not None
            and db["roles"][db["requests"][p["request_id"]]["role_id"]]["category"] == "GIFT_SHOP"
            for p in db["placements"].values())
        if not cashier_ok:
            raise_err(ERR_CASHIER_NOT_GIFT_SHOP_PLACED,
                      "Cashier is not an ACTIVE volunteer with an ACCEPTED GIFT_SHOP placement")
        if campaign is not None:
            if campaign["status"] != "ACTIVE":
                raise_err(ERR_CAMPAIGN_INVALID_STATE, "Campaign is not ACTIVE")
            n = now()
            if not (campaign["start_at"] <= n < campaign["end_at"]):
                raise_err(ERR_CAMPAIGN_WINDOW_MISMATCH,
                          "now is outside the campaign window")
        # discount: max of candidates (non-stacking)
        discount = 0
        if buyer is not None:
            tier = tier_for_points(recognition_points(buyer["id"]))
            discount = max(discount, TIER_DISCOUNT.get(tier, 0))
            if is_junior_at(buyer, today()):
                discount = max(discount, 5)
        if campaign is not None:
            discount = max(discount, campaign["promo_discount_pct"])
        # tier 13: stock (aggregate quantities per item so duplicate lines cannot oversell)
        want = {}
        for ln, it in zip(norm_lines, items):
            want[it["id"]] = want.get(it["id"], 0) + ln["qty"]
        for it in items:
            if want.get(it["id"], 0) > it["stock_on_hand"]:
                raise_err(ERR_INSUFFICIENT_STOCK,
                          "Insufficient stock for item %s" % it["id"])
        # totals: per-line round half up, then sum
        total = 0
        stored_lines = []
        for ln, it in zip(norm_lines, items):
            raw = Decimal(ln["qty"]) * Decimal(it["unit_price_cents"]) \
                * Decimal(100 - discount) / Decimal(100)
            line_cents = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            total += line_cents
            stored_lines.append({
                "item_id": it["id"], "qty": ln["qty"],
                "unit_price_cents": it["unit_price_cents"],
                "unit_cost_cents": it["unit_cost_cents"],
                "line_cents": line_cents,
            })
        if tendered < total:
            raise_err(ERR_INSUFFICIENT_TENDER, "tendered_cents is below the total")
        # commit
        for ln, it in zip(norm_lines, items):
            it["stock_on_hand"] -= ln["qty"]
            touch(it)
        rec = new_rec()
        rec.update({"cashier_volunteer_id": cashier_id,
                    "buyer_volunteer_id": buyer_id,
                    "campaign_id": campaign_id,
                    "_lines": stored_lines,
                    "total_cents": total,
                    "discount_pct_applied": discount,
                    "tendered_cents": tendered,
                    "change_cents": tendered - total,
                    "status": "COMPLETED",
                    "voided_at": None, "void_reason": None, "voided_by_user_id": None})
        db["sales"][rec["id"]] = rec
        return ok_object(ser_sale(rec), 201)

    @app.route("/auxiliary/gift-shop-sales", methods=["GET"])
    def list_sales():
        uid, role = auth()
        require_role(role, SALE_READERS)
        status = request.args.get("status")
        if status is not None and status not in SALE_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        cashier_id = request.args.get("cashier_volunteer_id")
        buyer_id = request.args.get("buyer_volunteer_id")
        rows = list(db["sales"].values())
        if role == "Volunteer":
            if (cashier_id is not None and cashier_id != uid) \
                    or (buyer_id is not None and buyer_id != uid):
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "Volunteers may only list their own sales")
            rows = [s for s in rows
                    if s["cashier_volunteer_id"] == uid or s["buyer_volunteer_id"] == uid]
        return page_list(rows, ser_sale,
                         filters={"cashier_volunteer_id": cashier_id,
                                  "buyer_volunteer_id": buyer_id,
                                  "campaign_id": request.args.get("campaign_id"),
                                  "status": status})

    @app.route("/auxiliary/gift-shop-sales/<rid>", methods=["GET"])
    def get_sale(rid):
        uid, role = auth()
        require_role(role, SALE_READERS)
        rec = get_or_404("sales", rid, "GiftShopSale")
        if role == "Volunteer" and rec["cashier_volunteer_id"] != uid \
                and rec["buyer_volunteer_id"] != uid:
            raise_err(ERR_NOT_RESOURCE_OWNER, "Volunteers may only read their own sales")
        return ok_object(ser_sale(rec))

    @app.route("/auxiliary/gift-shop-sales/<rid>/void", methods=["POST"])
    def void_sale(rid):
        uid, role = auth()
        data = body()
        reason = req_str(data, "void_reason", nonempty=True)
        require_role(role, ["AuxiliaryTreasurer", "VolunteerCoordinator"])
        rec = get_or_404("sales", rid, "GiftShopSale")
        if rec["status"] != "COMPLETED":
            raise_err(ERR_SALE_ALREADY_VOIDED, "Sale is already VOIDED")
        if now() > rec["created_at"] + timedelta(hours=24):
            raise_err(ERR_VOID_WINDOW_ELAPSED, "Void window has elapsed")
        for ln in rec["_lines"]:
            it = db["items"].get(ln["item_id"])
            if it is not None:
                it["stock_on_hand"] += ln["qty"]
                touch(it)
        rec["status"] = "VOIDED"
        rec["voided_at"] = now()
        rec["void_reason"] = reason
        rec["voided_by_user_id"] = uid
        touch(rec)
        return ok_object(ser_sale(rec))

    # ------------------------------------------------------- recognition events
    @app.route("/auxiliary/recognition-events", methods=["GET"])
    def list_events():
        uid, role = auth()
        require_role(role, EVENT_READERS)
        volunteer_id = request.args.get("volunteer_id")
        rows = list(db["events"].values())
        if role == "Volunteer":
            if volunteer_id is not None and volunteer_id != uid:
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "Volunteers may only list their own recognition events")
            rows = [e for e in rows if e["volunteer_id"] == uid]
            volunteer_id = None
        return page_list(rows, ser_event,
                         filters={"volunteer_id": volunteer_id})

    @app.route("/auxiliary/recognition-events/<rid>", methods=["GET"])
    def get_event(rid):
        uid, role = auth()
        require_role(role, EVENT_READERS)
        rec = get_or_404("events", rid, "RecognitionEvent")
        if role == "Volunteer" and rec["volunteer_id"] != uid:
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      "Volunteers may only read their own recognition events")
        return ok_object(ser_event(rec))
