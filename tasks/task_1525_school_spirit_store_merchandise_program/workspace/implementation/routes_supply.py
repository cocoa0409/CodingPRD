"""Purchase orders (submit / receive / cancel), preorder campaigns
(open / lock / cancel + vendor selector + auto POs + bubble-ups), and
preorders (place / pay / fulfill / cancel)."""
from flask import Blueprint, request

from core import (AD, SM, TRE, CUST, ApiError, DB,
                  ERR_CAMPAIGN_NF, ERR_CAMPAIGN_NOT_OPEN, ERR_CAMPAIGN_WINDOW_OPEN,
                  ERR_DEPOSIT_SHORTFALL, ERR_DESIGN_NF, ERR_DESIGN_NOT_LICENSED,
                  ERR_DUP_CAMPAIGN, ERR_INSUFFICIENT_STOCK, ERR_INVALID_REQUEST,
                  ERR_INVALID_STATE, ERR_LICENSE_REVOKED, ERR_MIN_ORDER_QTY,
                  ERR_NO_ELIGIBLE_VENDOR, ERR_PAYMENT_MISMATCH, ERR_PO_NF,
                  ERR_PREORDER_NF, ERR_PREORDER_NOT_CANCELLABLE,
                  ERR_PREORDER_NOT_PAYABLE, ERR_PROGRAM_NF, ERR_ROLE,
                  ERR_VARIANT_DESIGN_MISMATCH, ERR_VARIANT_NF, ERR_VENDOR_NF,
                  ERR_VENDOR_NOT_APPROVED, auth, body, cascade_campaign_cancel,
                  campaign_units, dec, fetch, fetch_scoped, gate_active, is_int,
                  list_response, need_role, new_entity, now_logical, pub,
                  pub_campaign, req_dt, req_fields, req_int, req_pct, rhu,
                  success, touch)

bp = Blueprint("supply", __name__)


def active_quote(vendor, design_id):
    for q in vendor["quotes"]:
        if q.get("design_id") == design_id and q.get("status") == "ACTIVE":
            return q
    return None


# ----------------------------------------------------------- PurchaseOrder --
@bp.post("/spirit-store/purchase-orders")
def create_po():
    auth()
    uid, role = auth()
    need_role(role, SM)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    if data.get("variant_id") is not None:
        fetch_scoped("variants", data["variant_id"], ERR_VARIANT_NF,
                     data.get("program_id"))
    if data.get("vendor_id") is not None:
        fetch_scoped("vendors", data["vendor_id"], ERR_VENDOR_NF,
                     data.get("program_id"))
    req_fields(data, "program_id", "variant_id", "vendor_id", "qty_ordered")
    qty = req_int(data, "qty_ordered", 1)
    gate_active(program)
    variant = DB["variants"][data["variant_id"]]
    vendor = DB["vendors"][data["vendor_id"]]
    # unit_cost captured from the vendor's ACTIVE quote on the variant's design.
    quote = active_quote(vendor, variant["design_id"])
    if quote is None:
        raise ApiError(ERR_NO_ELIGIBLE_VENDOR, 422,
                       "vendor has no ACTIVE quote for the variant's design")
    po = new_entity({
        "program_id": program["id"],
        "variant_id": variant["id"],
        "vendor_id": vendor["id"],
        "campaign_id": None,
        "qty_ordered": qty,
        "qty_received": 0,
        "unit_cost_cents": quote["unit_cost_cents"],
        "auto_created": False,
        "status": "DRAFT",
        "_min_order_qty": quote["min_order_qty"],
    })
    DB["pos"][po["id"]] = po
    return success(pub(po), code=201)


@bp.get("/spirit-store/purchase-orders")
def list_pos():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE)
    items = list(DB["pos"].values())
    for param in ("program_id", "variant_id", "vendor_id", "campaign_id"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p[param] == value]
    return list_response(items, pub)


@bp.get("/spirit-store/purchase-orders/<poId>")
def get_po(poId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE)
    return success(pub(fetch("pos", poId, ERR_PO_NF)))


@bp.post("/spirit-store/purchase-orders/<poId>/submit")
def submit_po(poId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    po = fetch("pos", poId, ERR_PO_NF)
    program = DB["programs"].get(po["program_id"])
    gate_active(program)
    if po["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT purchase order can be submitted")
    vendor = DB["vendors"].get(po["vendor_id"])
    if vendor is None or vendor["status"] != "APPROVED":
        raise ApiError(ERR_VENDOR_NOT_APPROVED, 409,
                       "vendor must be APPROVED to submit")
    variant = DB["variants"].get(po["variant_id"])
    design = DB["designs"].get(variant["design_id"]) if variant else None
    if design is not None and design["status"] == "REVOKED":
        raise ApiError(ERR_LICENSE_REVOKED, 409, "design license was revoked")
    if design is None or design["status"] != "APPROVED":
        raise ApiError(ERR_DESIGN_NOT_LICENSED, 409,
                       "design must be APPROVED to submit")
    if po["qty_ordered"] < po["_min_order_qty"]:
        raise ApiError(ERR_MIN_ORDER_QTY, 422,
                       "qty_ordered is below the quote's minimum order "
                       "quantity")
    po["status"] = "SUBMITTED"
    touch(po)
    return success(pub(po))


@bp.post("/spirit-store/purchase-orders/<poId>/receive")
def receive_po(poId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    po = fetch("pos", poId, ERR_PO_NF)
    program = DB["programs"].get(po["program_id"])
    gate_active(program)
    if po["status"] not in ("SUBMITTED", "PARTIALLY_RECEIVED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SUBMITTED or PARTIALLY_RECEIVED purchase order "
                       "can receive")
    data = body()
    qty = req_int(data, "qty")
    if qty < 1 or po["qty_received"] + qty > po["qty_ordered"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "qty must be >= 1 and may not exceed the remaining "
                       "ordered quantity")
    variant = DB["variants"][po["variant_id"]]
    design = DB["designs"].get(variant["design_id"])
    po["qty_received"] += qty
    variant["on_hand_qty"] += qty
    # Landed cost: licensing fee amortized over qty_ordered, round half up;
    # the latest receipt wins.
    fee_per_unit = rhu(design["licensing_fee_cents"], po["qty_ordered"]) \
        if design is not None else 0
    landed = po["unit_cost_cents"] + fee_per_unit
    variant["landed_unit_cost_cents"] = landed
    variant["_layers"].append({"qty": qty, "cost": landed,
                               "received_at": now_logical(),
                               "po_seq": po["_seq"]})
    if po["qty_received"] == po["qty_ordered"]:
        po["status"] = "RECEIVED"
    else:
        po["status"] = "PARTIALLY_RECEIVED"
    touch(po)
    touch(variant)
    # Bubble-up: all of the campaign's POs RECEIVED -> FULFILLING.
    if po["status"] == "RECEIVED" and po["campaign_id"]:
        campaign = DB["campaigns"].get(po["campaign_id"])
        if campaign is not None and campaign["status"] == "IN_PRODUCTION":
            remaining = [p for p in DB["pos"].values()
                         if p["campaign_id"] == campaign["id"]]
            if remaining and all(p["status"] == "RECEIVED" for p in remaining):
                campaign["status"] = "FULFILLING"
                touch(campaign)
    return success(pub(po))


@bp.post("/spirit-store/purchase-orders/<poId>/cancel")
def cancel_po(poId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    po = fetch("pos", poId, ERR_PO_NF)
    program = DB["programs"].get(po["program_id"])
    gate_active(program)
    if po["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT or SUBMITTED purchase order can be "
                       "cancelled")
    po["status"] = "CANCELLED"
    touch(po)
    return success(pub(po))


# -------------------------------------------------------- PreOrderCampaign --
@bp.post("/spirit-store/preorder-campaigns")
def create_campaign():
    auth()
    uid, role = auth()
    need_role(role, SM)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    if data.get("design_id") is not None:
        fetch_scoped("designs", data["design_id"], ERR_DESIGN_NF,
                     data.get("program_id"))
    req_fields(data, "program_id", "design_id", "unit_price_cents",
               "deposit_pct", "goal_units", "opens_at", "closes_at")
    price = req_int(data, "unit_price_cents", 1)
    deposit_pct = req_pct(data, "deposit_pct")
    goal = req_int(data, "goal_units", 1)
    opens_at = req_dt(data, "opens_at")
    closes_at = req_dt(data, "closes_at")
    if not closes_at > opens_at:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "closes_at must be strictly after opens_at")
    gate_active(program)
    campaign = new_entity({
        "program_id": program["id"],
        "design_id": data["design_id"],
        "unit_price_cents": price,
        "deposit_pct": deposit_pct,
        "goal_units": goal,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "status": "DRAFT",
        "selected_vendor_id": None,
    })
    DB["campaigns"][campaign["id"]] = campaign
    return success(pub_campaign(campaign), code=201)


@bp.get("/spirit-store/preorder-campaigns")
def list_campaigns():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, CUST)
    items = list(DB["campaigns"].values())
    for param in ("program_id", "design_id", "selected_vendor_id"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    return list_response(items, pub_campaign)


@bp.get("/spirit-store/preorder-campaigns/<campaignId>")
def get_campaign(campaignId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, CUST)
    return success(pub_campaign(fetch("campaigns", campaignId,
                                      ERR_CAMPAIGN_NF)))


@bp.post("/spirit-store/preorder-campaigns/<campaignId>/open")
def open_campaign(campaignId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    campaign = fetch("campaigns", campaignId, ERR_CAMPAIGN_NF)
    program = DB["programs"].get(campaign["program_id"])
    gate_active(program)
    if campaign["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT campaign can be opened")
    design = DB["designs"].get(campaign["design_id"])
    if design is not None and design["status"] == "REVOKED":
        raise ApiError(ERR_LICENSE_REVOKED, 409, "design license was revoked")
    if design is None or design["status"] != "APPROVED":
        raise ApiError(ERR_DESIGN_NOT_LICENSED, 409,
                       "design must be APPROVED to open a campaign")
    if now_logical() < campaign["opens_at"]:
        raise ApiError(ERR_CAMPAIGN_NOT_OPEN, 409,
                       "campaign window has not started")
    for other in DB["campaigns"].values():
        if (other["id"] != campaign["id"]
                and other["design_id"] == campaign["design_id"]
                and other["status"] in ("OPEN", "IN_PRODUCTION", "FULFILLING")):
            raise ApiError(ERR_DUP_CAMPAIGN, 409,
                           "another campaign of this design is already active")
    campaign["status"] = "OPEN"
    touch(campaign)
    return success(pub_campaign(campaign))


@bp.post("/spirit-store/preorder-campaigns/<campaignId>/lock")
def lock_campaign(campaignId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    campaign = fetch("campaigns", campaignId, ERR_CAMPAIGN_NF)
    program = DB["programs"].get(campaign["program_id"])
    gate_active(program)
    if campaign["status"] != "OPEN":
        raise ApiError(ERR_CAMPAIGN_NOT_OPEN, 409,
                       "only an OPEN campaign can be locked")
    if now_logical() < campaign["closes_at"]:
        raise ApiError(ERR_CAMPAIGN_WINDOW_OPEN, 409,
                       "campaign window is still open")
    _, paid_units = campaign_units(campaign)
    if paid_units < campaign["goal_units"]:
        # Goal-unmet branch: CANCELLED + refund cascade.
        campaign["status"] = "CANCELLED"
        touch(campaign)
        cascade_campaign_cancel(campaign)
        return success(pub_campaign(campaign))
    # Goal-met branch: vendor quote selector.
    candidates = []
    for vendor in DB["vendors"].values():
        if (vendor["program_id"] != campaign["program_id"]
                or vendor["status"] != "APPROVED"):
            continue
        quote = active_quote(vendor, campaign["design_id"])
        if quote is not None:
            candidates.append((quote["unit_cost_cents"],
                               quote["production_days"], vendor["_seq"],
                               vendor, quote))
    if not candidates:
        raise ApiError(ERR_NO_ELIGIBLE_VENDOR, 422,
                       "no APPROVED vendor holds an ACTIVE quote for the "
                       "campaign's design")
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    _, _, _, winner, win_quote = candidates[0]
    campaign["selected_vendor_id"] = winner["id"]
    campaign["status"] = "IN_PRODUCTION"
    touch(campaign)
    # Auto-create one PO per variant with paid demand > 0.
    demand = {}
    for p in DB["preorders"].values():
        if (p["campaign_id"] == campaign["id"]
                and p["status"] in ("PAID", "FULFILLED")):
            demand[p["variant_id"]] = demand.get(p["variant_id"], 0) + p["qty"]
    for variant_id, units in demand.items():
        po = new_entity({
            "program_id": campaign["program_id"],
            "variant_id": variant_id,
            "vendor_id": winner["id"],
            "campaign_id": campaign["id"],
            "qty_ordered": max(units, win_quote["min_order_qty"]),
            "qty_received": 0,
            "unit_cost_cents": win_quote["unit_cost_cents"],
            "auto_created": True,
            "status": "SUBMITTED",
            "_min_order_qty": win_quote["min_order_qty"],
        })
        DB["pos"][po["id"]] = po
    return success(pub_campaign(campaign))


@bp.post("/spirit-store/preorder-campaigns/<campaignId>/cancel")
def cancel_campaign(campaignId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    campaign = fetch("campaigns", campaignId, ERR_CAMPAIGN_NF)
    program = DB["programs"].get(campaign["program_id"])
    gate_active(program)
    if campaign["status"] not in ("DRAFT", "OPEN"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT or OPEN campaign can be cancelled")
    was_open = campaign["status"] == "OPEN"
    campaign["status"] = "CANCELLED"
    touch(campaign)
    if was_open:
        cascade_campaign_cancel(campaign)
    return success(pub_campaign(campaign))


# ---------------------------------------------------------------- PreOrder --
@bp.post("/spirit-store/preorders")
def create_preorder():
    auth()
    uid, role = auth()
    need_role(role, CUST)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    if data.get("campaign_id") is not None:
        fetch_scoped("campaigns", data["campaign_id"], ERR_CAMPAIGN_NF,
                     data.get("program_id"))
    if data.get("variant_id") is not None:
        fetch_scoped("variants", data["variant_id"], ERR_VARIANT_NF,
                     data.get("program_id"))
    req_fields(data, "program_id", "campaign_id", "variant_id",
               "customer_user_id", "qty")
    qty = req_int(data, "qty", 1)
    gate_active(program)
    campaign = DB["campaigns"][data["campaign_id"]]
    variant = DB["variants"][data["variant_id"]]
    if campaign["status"] != "OPEN":
        raise ApiError(ERR_CAMPAIGN_NOT_OPEN, 409,
                       "campaign must be OPEN to place a preorder")
    design = DB["designs"].get(campaign["design_id"])
    if design is not None and design["status"] == "REVOKED":
        raise ApiError(ERR_LICENSE_REVOKED, 409, "design license was revoked")
    if design is None or design["status"] != "APPROVED":
        raise ApiError(ERR_DESIGN_NOT_LICENSED, 409,
                       "design must be APPROVED")
    if variant["design_id"] != campaign["design_id"]:
        raise ApiError(ERR_VARIANT_DESIGN_MISMATCH, 422,
                       "preorder variant's design does not match the "
                       "campaign's design")
    # Deposit split: max(floor, round_half_up(price * qty * deposit_pct)).
    raw = rhu(campaign["unit_price_cents"] * qty * dec(campaign["deposit_pct"]))
    deposit_due = max(program["deposit_floor_cents"], raw)
    balance_due = campaign["unit_price_cents"] * qty - deposit_due
    preorder = new_entity({
        "program_id": program["id"],
        "campaign_id": campaign["id"],
        "variant_id": variant["id"],
        "customer_user_id": data["customer_user_id"],
        "qty": qty,
        "status": "PLACED",
        "deposit_due_cents": deposit_due,
        "balance_due_cents": balance_due,
        "deposit_paid_cents": 0,
        "balance_paid_cents": 0,
        "refunded_cents": 0,
    })
    DB["preorders"][preorder["id"]] = preorder
    return success(pub(preorder), code=201)


@bp.get("/spirit-store/preorders")
def list_preorders():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, CUST)
    items = list(DB["preorders"].values())
    for param in ("program_id", "campaign_id", "variant_id",
                  "customer_user_id"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p[param] == value]
    return list_response(items, pub)


@bp.get("/spirit-store/preorders/<preorderId>")
def get_preorder(preorderId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, CUST)
    return success(pub(fetch("preorders", preorderId, ERR_PREORDER_NF)))


@bp.post("/spirit-store/preorders/<preorderId>/pay")
def pay_preorder(preorderId):
    auth()
    uid, role = auth()
    need_role(role, CUST)
    preorder = fetch("preorders", preorderId, ERR_PREORDER_NF)
    # Customer ownership: X-User-ID must equal the preorder's customer.
    if uid != preorder["customer_user_id"]:
        raise ApiError(ERR_ROLE, 403,
                       "customers may only pay their own preorders")
    data = body()
    req_fields(data, "phase", "amount_cents")
    phase = data["phase"]
    if phase not in ("DEPOSIT", "BALANCE"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "phase must be DEPOSIT or BALANCE")
    amount = req_int(data, "amount_cents", 1)
    program = DB["programs"].get(preorder["program_id"])
    gate_active(program)
    campaign = DB["campaigns"].get(preorder["campaign_id"])
    if phase == "DEPOSIT":
        if preorder["status"] != "PLACED":
            raise ApiError(ERR_PREORDER_NOT_PAYABLE, 409,
                           "preorder is not payable for a deposit")
        if campaign is None or campaign["status"] != "OPEN":
            raise ApiError(ERR_CAMPAIGN_NOT_OPEN, 409,
                           "campaign must be OPEN to pay a deposit")
        due = preorder["deposit_due_cents"]
        if amount < due:
            raise ApiError(ERR_DEPOSIT_SHORTFALL, 402,
                           "payment is below the deposit due")
        if amount > due:
            raise ApiError(ERR_PAYMENT_MISMATCH, 422,
                           "payment exceeds the deposit due")
        preorder["deposit_paid_cents"] = amount
        preorder["status"] = "PAID"
    else:  # BALANCE
        if preorder["status"] != "PAID":
            raise ApiError(ERR_PREORDER_NOT_PAYABLE, 409,
                           "preorder is not payable for a balance")
        if campaign is None or campaign["status"] not in ("IN_PRODUCTION",
                                                          "FULFILLING"):
            raise ApiError(ERR_PREORDER_NOT_PAYABLE, 409,
                           "balance is payable only once the campaign is in "
                           "production")
        due = preorder["balance_due_cents"]
        if amount < due:
            raise ApiError(ERR_DEPOSIT_SHORTFALL, 402,
                           "payment is below the balance due")
        if amount > due:
            raise ApiError(ERR_PAYMENT_MISMATCH, 422,
                           "payment exceeds the balance due")
        preorder["balance_paid_cents"] = amount
    touch(preorder)
    return success(pub(preorder))


@bp.post("/spirit-store/preorders/<preorderId>/fulfill")
def fulfill_preorder(preorderId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    preorder = fetch("preorders", preorderId, ERR_PREORDER_NF)
    program = DB["programs"].get(preorder["program_id"])
    gate_active(program)
    if preorder["status"] != "PAID":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a PAID preorder can be fulfilled")
    campaign = DB["campaigns"].get(preorder["campaign_id"])
    if campaign is None or campaign["status"] != "FULFILLING":
        raise ApiError(ERR_CAMPAIGN_NOT_OPEN, 409,
                       "campaign must be FULFILLING to fulfill preorders")
    variant = DB["variants"][preorder["variant_id"]]
    available = variant["on_hand_qty"] - variant["reserved_online_qty"]
    if available < preorder["qty"]:
        raise ApiError(ERR_INSUFFICIENT_STOCK, 422,
                       "available stock does not cover the preorder")
    if preorder["balance_paid_cents"] != preorder["balance_due_cents"]:
        raise ApiError(ERR_DEPOSIT_SHORTFALL, 402,
                       "balance must be fully paid before fulfillment")
    variant["on_hand_qty"] -= preorder["qty"]
    variant["_consumed"] += preorder["qty"]
    touch(variant)
    # Margin net of royalty: price*qty - qty*landed - rhu(royalty*price*qty).
    design = DB["designs"].get(campaign["design_id"])
    qty = preorder["qty"]
    revenue = campaign["unit_price_cents"] * qty
    royalty = rhu(revenue * dec(design["royalty_pct"])) if design else 0
    margin = revenue - qty * variant["landed_unit_cost_cents"] - royalty
    program["undistributed_profit_cents"] += margin
    touch(program)
    preorder["status"] = "FULFILLED"
    touch(preorder)
    # Bubble-up: no PAID preorders remain -> campaign CLOSED.
    if campaign["status"] == "FULFILLING":
        still_paid = any(p["campaign_id"] == campaign["id"]
                         and p["status"] == "PAID"
                         for p in DB["preorders"].values())
        if not still_paid:
            campaign["status"] = "CLOSED"
            touch(campaign)
    return success(pub(preorder))


@bp.post("/spirit-store/preorders/<preorderId>/cancel")
def cancel_preorder(preorderId):
    auth()
    uid, role = auth()
    need_role(role, CUST)
    preorder = fetch("preorders", preorderId, ERR_PREORDER_NF)
    if uid != preorder["customer_user_id"]:
        raise ApiError(ERR_ROLE, 403,
                       "customers may only cancel their own preorders")
    program = DB["programs"].get(preorder["program_id"])
    gate_active(program)
    campaign = DB["campaigns"].get(preorder["campaign_id"])
    # Escape hatch only while the campaign is still OPEN.
    if (preorder["status"] not in ("PLACED", "PAID")
            or campaign is None or campaign["status"] != "OPEN"):
        raise ApiError(ERR_PREORDER_NOT_CANCELLABLE, 409,
                       "preorder can no longer be cancelled")
    if preorder["status"] == "PLACED":
        preorder["status"] = "CANCELLED"
    else:  # PAID while campaign still OPEN -> deposit refunded
        preorder["status"] = "REFUNDED"
        preorder["refunded_cents"] = (preorder["deposit_paid_cents"]
                                      + preorder["balance_paid_cents"])
    touch(preorder)
    return success(pub(preorder))
