"""All API route handlers (PRD §4)."""
from math import ceil
from flask import g, request

import calc
from auth import (
    parse_auth, require_role, own_customer, own_supplier, own_leader_subtree,
    is_in_subtree,
)
from cascades import (
    recompute_leader_risk, recompute_all_active_leaders,
    suspend_leader_cascade, close_campaign_failed, close_campaign_succeeded,
    cancel_non_terminal_shipments, cascade_order_cancel_from_fulfillment,
    order_to_refund_pending, recompute_payout_total, revert_clawbacks_for_order,
    proportional_partial_compensation,
)
from envelope import success, list_success
from errors import (
    APIError, raise_err,
    ERR_VALIDATION_FAILED, ERR_INVALID_QUANTITY, ERR_INVALID_STATE,
    ERR_FORBIDDEN, ERR_OWNERSHIP_VIOLATION,
    ERR_COMMUNITY_NOT_FOUND, ERR_GROUP_LEADER_NOT_FOUND, ERR_CAMPAIGN_NOT_FOUND,
    ERR_FLASH_CAMPAIGN_NOT_FOUND, ERR_ORDER_NOT_FOUND, ERR_SHIPMENT_NOT_FOUND,
    ERR_PICKUP_POINT_NOT_FOUND, ERR_AFTER_SALES_CASE_NOT_FOUND,
    ERR_PAYOUT_NOT_FOUND, ERR_RISK_ALERT_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND, ERR_SUPPLIER_NOT_FOUND, ERR_WAREHOUSE_NOT_FOUND,
    ERR_CAMPAIGN_NOT_OPEN, ERR_FLASH_STOCK_DEPLETED, ERR_FLASH_CAMPAIGN_NOT_OPEN,
    ERR_DUPLICATE_PARTICIPATION, ERR_COMMUNITY_CAMPAIGN_OVERLAP,
    ERR_COLD_CHAIN_REQUIRED, ERR_NO_WAREHOUSE_AVAILABLE,
    ERR_PICKUP_POINT_AT_CAPACITY, ERR_PICKUP_POINT_COLD_INCOMPATIBLE,
    ERR_CONSOLIDATION_WINDOW_OVERLAP,
    ERR_AFTER_SALES_WINDOW_EXPIRED, ERR_AFTER_SALES_ALREADY_OPEN,
    ERR_AFTER_SALES_AMOUNT_EXCEEDS_REMAINING,
    ERR_PAYOUT_HAS_PENDING_CLAWBACK, ERR_PAYOUT_NOT_MATURED,
    ERR_CUSTOMER_BLOCKED, ERR_CUSTOMER_RISK_HOLD,
)
from store import store, new_id, stamp_create, stamp_create_minimal, bump


# ---------------- Body parsing helpers ----------------

def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        raise_err(ERR_VALIDATION_FAILED, "malformed JSON body")
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION_FAILED, "body must be an object")
    return body


def require_field(body, name, types=None, required=True):
    if name not in body or body[name] is None:
        if required:
            raise_err(ERR_VALIDATION_FAILED, f"missing field: {name}")
        return None
    val = body[name]
    if types is not None and not isinstance(val, types):
        raise_err(ERR_VALIDATION_FAILED, f"invalid type for field: {name}")
    return val


def require_positive_int(body, name, required=True):
    val = require_field(body, name, types=int, required=required)
    if val is None:
        return None
    if isinstance(val, bool) or val <= 0:
        raise_err(ERR_VALIDATION_FAILED, f"invalid value for field: {name}")
    return val


def require_non_negative_int(body, name, required=True):
    val = require_field(body, name, types=int, required=required)
    if val is None:
        return None
    if isinstance(val, bool) or val < 0:
        raise_err(ERR_VALIDATION_FAILED, f"invalid value for field: {name}")
    return val


# ---------------- Public helpers ----------------

def serialize_resource(resource):
    """Default serializer = identity."""
    return dict(resource)


def list_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION_FAILED, "invalid pagination parameter")
    if limit < 1 or limit > 100:
        raise_err(ERR_VALIDATION_FAILED, "limit out of bounds")
    if offset < 0:
        raise_err(ERR_VALIDATION_FAILED, "offset out of bounds")
    return limit, offset


def sort_by_created(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def flash_status(cmp):
    """Computed FlashCampaign status."""
    cur = store.system_period_index
    if cur < cmp["opens_at_period"]:
        return "SCHEDULED"
    if cur >= cmp["closes_at_period"]:
        return "CLOSED"
    if cmp.get("remaining_units", 0) <= 0:
        return "EXHAUSTED"
    return "OPEN"


def serialize_flash(cmp):
    out = dict(cmp)
    out["status"] = flash_status(out)
    out["remaining_units"] = out["total_stock"] - out.get("locked_units", 0) - out.get("allocated_units", 0)
    return out


def serialize_pickup_point(pp):
    out = dict(pp)
    out["held_package_count"] = compute_held_count(pp["id"])
    return out


def compute_held_count(pickup_point_id):
    return sum(1 for s in store.shipments.values()
               if s["pickup_point_id"] == pickup_point_id
               and s["status"] in ("AT_PICKUP", "MIS_PICK", "RECONCILED"))


def serialize_leader(l):
    out = dict(l)
    out["chronic_risk_score"] = float(l.get("chronic_risk_score", 0.0))
    out["acute_risk_score"] = float(l.get("acute_risk_score", 0.0))
    return out


def serialize_groupbuy(cmp):
    out = dict(cmp)
    out["participant_count"] = compute_group_buy_participants(cmp["id"])
    return out


def compute_group_buy_participants(campaign_id):
    cnt = 0
    for o in store.orders.values():
        if o.get("campaign_kind") != "GROUP_BUY":
            continue
        if o.get("campaign_id") != campaign_id:
            continue
        if o["payment_status"] in ("PAID", "SETTLED", "PARTIALLY_REFUNDED"):
            cnt += 1
    return cnt


def serialize_consolidation(b):
    return {
        "id": b["id"],
        "pickup_point_id": b["pickup_point_id"],
        "created_at": b["created_at"],
        "window_start_period": b["window_start_period"],
        "window_end_period": b["window_end_period"],
        "shipment_ids": list(b["shipment_ids"]),
        "status": b["status"],
    }


def serialize_risk_alert(a):
    return dict(a)


# ===================================================================
#                   ROUTE REGISTRATION
# ===================================================================

def register_routes(app):

    # ---------------- Test-driving: clock + sweeps ----------------

    @app.route("/_clock/advance", methods=["POST"])
    def advance_clock():
        parse_auth()
        require_role("PlatformAdmin")
        body = get_body()
        by = body.get("by_periods")
        if not isinstance(by, int) or isinstance(by, bool) or by < 1 or by > 365:
            raise_err(ERR_VALIDATION_FAILED, "by_periods must be 1..365")
        store.system_period_index += by
        # Order auto-finalize: PICKED_UP -> COMPLETED if 7 periods elapsed and no open after-sales case
        cur = store.system_period_index
        for order in list(store.orders.values()):
            if order["fulfillment_status"] != "PICKED_UP":
                continue
            picked_period = store.picked_up_period.get(order["id"])
            if picked_period is None:
                continue
            if cur >= picked_period + 7:
                if has_open_after_sales_case(order["id"]):
                    continue
                order["fulfillment_status"] = "COMPLETED"
                bump(order)
                cust = store.customers.get(order["customer_id"])
                if cust:
                    cust["lifetime_completed_orders"] = cust.get("lifetime_completed_orders", 0) + 1
                    bump(cust)
        # Recompute risk for all ACTIVE leaders
        recompute_all_active_leaders()
        return success({"system_period_index": store.system_period_index})

    @app.route("/_sweep/run-payouts", methods=["POST"])
    def sweep_payouts():
        parse_auth()
        require_role("PlatformAdmin")
        # Pass 1: REFUND_PENDING orders -> REFUNDED; PENDING_CLAWBACK entries -> CLAWED_BACK
        for order in list(store.orders.values()):
            if order["payment_status"] != "REFUND_PENDING":
                continue
            refund_amount = store.refund_pending.pop(order["id"], 0)
            order["refunded_amount_cents"] = order.get("refunded_amount_cents", 0) + refund_amount
            order["payment_status"] = "REFUNDED"
            bump(order)
            if order["fulfillment_status"] in ("NOT_PLANNED", "PLANNED", "DISPATCHED"):
                cascade_order_cancel_from_fulfillment(order)
            for ce in store.commission_entries.values():
                if ce["order_id"] != order["id"]:
                    continue
                if ce["status"] == "PENDING_CLAWBACK":
                    ce["status"] = "CLAWED_BACK"
                    bump(ce)
                    payout = store.payouts.get(ce.get("payout_id"))
                    if payout:
                        if payout["status"] == "RELEASED":
                            store.leader_clawback[ce["leader_id"]] = (
                                store.leader_clawback.get(ce["leader_id"], 0) + ce["net_rebate_cents"]
                            )
                        else:
                            recompute_payout_total(payout["id"])
        # Pass 2: SCHEDULED -> MATURED if no PENDING_CLAWBACK/CLAWED_BACK and target reached
        cur = store.system_period_index
        for payout in list(store.payouts.values()):
            if payout["status"] != "SCHEDULED":
                continue
            if payout["target_period_index"] > cur:
                continue
            blocked = False
            for entry_id in payout["bundled_entry_ids"]:
                ce = store.commission_entries.get(entry_id)
                if ce and ce["status"] in ("PENDING_CLAWBACK", "CLAWED_BACK"):
                    blocked = True
                    break
            if blocked:
                continue
            payout["status"] = "MATURED"
            bump(payout)
        return success({"system_period_index": store.system_period_index})

    @app.route("/_sweep/auto-close-campaigns", methods=["POST"])
    def sweep_auto_close():
        parse_auth()
        require_role("PlatformAdmin")
        cur = store.system_period_index
        for cmp in list(store.group_buy_campaigns.values()):
            if cmp["status"] not in ("FORMING", "EXTENDED"):
                continue
            if cmp["deadline_period"] > cur:
                continue
            # decide success/fail
            participants = compute_group_buy_participants(cmp["id"])
            cmp["participant_count"] = participants
            min_threshold = cmp["discount_tiers"][0]["min_participants"]
            if participants >= min_threshold:
                close_campaign_succeeded(cmp)
            else:
                close_campaign_failed(cmp, close_period=cur)
        return success({"system_period_index": cur})

    @app.route("/_sweep/recompute-risk", methods=["POST"])
    def sweep_recompute_risk():
        parse_auth()
        require_role("PlatformAdmin")
        recompute_all_active_leaders()
        return success({"system_period_index": store.system_period_index})

    # ---------------- Communities ----------------

    @app.route("/communities", methods=["POST"])
    def create_community():
        parse_auth()
        require_role("PlatformAdmin")
        body = get_body()
        name = require_field(body, "name", types=str)
        region_code = require_field(body, "region_code", types=str)
        tz = body.get("timezone_offset_minutes")
        if tz is not None and (not isinstance(tz, int) or isinstance(tz, bool)):
            raise_err(ERR_VALIDATION_FAILED, "invalid timezone_offset_minutes")
        # Unique name
        for c in store.communities.values():
            if c["name"] == name:
                raise_err(ERR_VALIDATION_FAILED, "community name must be unique")
        c = {
            **stamp_create(),
            "name": name,
            "region_code": region_code,
            "status": "ACTIVE",
            "timezone_offset_minutes": tz,
        }
        store.communities[c["id"]] = c
        return success(c, http_status=201)

    @app.route("/communities", methods=["GET"])
    def list_communities():
        parse_auth()
        require_role("PlatformAdmin", "GroupLeader", "Customer", "Supplier",
                     "PickupOperator", "CustomerService")
        limit, offset = list_pagination()
        items = sort_by_created(list(store.communities.values()))
        page = items[offset:offset + limit]
        return list_success([dict(c) for c in page], len(items), limit, offset)

    # ---------------- Group Leaders ----------------

    @app.route("/communities/<community_id>/group-leaders", methods=["POST"])
    def create_group_leader(community_id):
        parse_auth()
        require_role("PlatformAdmin")
        if community_id not in store.communities:
            raise_err(ERR_COMMUNITY_NOT_FOUND)
        body = get_body()
        display_name = require_field(body, "display_name", types=str)
        parent_leader_id = body.get("parent_leader_id")
        tier = 1
        if parent_leader_id is not None:
            parent = store.group_leaders.get(parent_leader_id)
            if parent is None:
                raise_err(ERR_GROUP_LEADER_NOT_FOUND, "parent_leader_id not found")
            if parent.get("community_id") != community_id:
                raise_err(ERR_VALIDATION_FAILED, "parent leader must be in same community")
            if parent.get("tier", 0) >= 3:
                raise_err(ERR_VALIDATION_FAILED, "parent leader is at max tier")
            tier = parent["tier"] + 1
        leader = {
            **stamp_create(),
            "community_id": community_id,
            "parent_leader_id": parent_leader_id,
            "tier": tier,
            "display_name": display_name,
            "status": "PENDING_REVIEW",
            "chronic_risk_score": 0.0,
            "acute_risk_score": 0.0,
            "collusion_audit_count": 0,
            "lifetime_settled_orders": 0,
            "created_period_index": store.system_period_index,
        }
        store.group_leaders[leader["id"]] = leader
        return success(serialize_leader(leader), http_status=201)

    @app.route("/group-leaders/<leader_id>", methods=["GET"])
    def get_group_leader(leader_id):
        parse_auth()
        require_role("PlatformAdmin", "GroupLeader", "CustomerService")
        if leader_id not in store.group_leaders:
            raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        if g.role == "GroupLeader" and not is_in_subtree(g.user_id, leader_id):
            raise_err(ERR_OWNERSHIP_VIOLATION)
        return success(serialize_leader(store.group_leaders[leader_id]))

    @app.route("/group-leaders/<leader_id>/approve", methods=["POST"])
    def approve_leader(leader_id):
        parse_auth()
        require_role("PlatformAdmin")
        leader = store.group_leaders.get(leader_id)
        if leader is None:
            raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        if leader["status"] != "PENDING_REVIEW":
            raise_err(ERR_INVALID_STATE)
        community = store.communities.get(leader["community_id"])
        if community is None or community["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE)
        leader["status"] = "ACTIVE"
        bump(leader)
        return success(serialize_leader(leader))

    @app.route("/group-leaders/<leader_id>/suspend", methods=["POST"])
    def suspend_leader(leader_id):
        parse_auth()
        require_role("PlatformAdmin")
        leader = store.group_leaders.get(leader_id)
        if leader is None:
            raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        if leader["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE)
        suspend_leader_cascade(leader)
        return success(serialize_leader(leader))

    @app.route("/group-leaders/<leader_id>/reinstate", methods=["POST"])
    def reinstate_leader(leader_id):
        parse_auth()
        require_role("PlatformAdmin")
        leader = store.group_leaders.get(leader_id)
        if leader is None:
            raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        if leader["status"] != "SUSPENDED":
            raise_err(ERR_INVALID_STATE)
        for a in store.risk_alerts.values():
            if a["status"] == "OPEN" and a["severity"] == "HIGH" \
               and a["target_kind"] == "GROUP_LEADER" and a["target_id"] == leader_id:
                raise_err(ERR_INVALID_STATE)
        leader["status"] = "ACTIVE"
        bump(leader)
        return success(serialize_leader(leader))

    @app.route("/group-leaders/<leader_id>/deactivate", methods=["POST"])
    def deactivate_leader(leader_id):
        parse_auth()
        require_role("PlatformAdmin")
        leader = store.group_leaders.get(leader_id)
        if leader is None:
            raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        if leader["status"] not in ("PENDING_REVIEW", "ACTIVE", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE)
        for cmp in store.group_buy_campaigns.values():
            if cmp.get("leader_id") == leader_id and cmp["status"] in ("FORMING", "EXTENDED"):
                raise_err(ERR_INVALID_STATE)
        leader["status"] = "DEACTIVATED"
        bump(leader)
        return success(serialize_leader(leader))

    # ---------------- Customers ----------------

    @app.route("/customers", methods=["POST"])
    def create_customer():
        parse_auth()
        require_role("PlatformAdmin")
        body = get_body()
        community_id = require_field(body, "community_id", types=str)
        display_name = require_field(body, "display_name", types=str)
        if community_id not in store.communities:
            raise_err(ERR_COMMUNITY_NOT_FOUND)
        cust = {
            **stamp_create(),
            "community_id": community_id,
            "display_name": display_name,
            "status": "ACTIVE",
            "lifetime_completed_orders": 0,
        }
        store.customers[cust["id"]] = cust
        return success(cust, http_status=201)

    @app.route("/customers/<customer_id>", methods=["GET"])
    def get_customer(customer_id):
        parse_auth()
        require_role("PlatformAdmin", "Customer", "CustomerService")
        if customer_id not in store.customers:
            raise_err(ERR_CUSTOMER_NOT_FOUND)
        if g.role == "Customer" and g.user_id != customer_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        return success(store.customers[customer_id])

    # ---------------- Suppliers and Warehouses ----------------

    @app.route("/suppliers", methods=["POST"])
    def create_supplier():
        parse_auth()
        require_role("PlatformAdmin")
        body = get_body()
        name = require_field(body, "name", types=str)
        sup = {**stamp_create(), "name": name, "status": "ACTIVE"}
        store.suppliers[sup["id"]] = sup
        return success(sup, http_status=201)

    @app.route("/suppliers/<supplier_id>/warehouses", methods=["POST"])
    def create_warehouse(supplier_id):
        parse_auth()
        require_role("PlatformAdmin", "Supplier")
        if supplier_id not in store.suppliers:
            raise_err(ERR_SUPPLIER_NOT_FOUND)
        if g.role == "Supplier" and g.user_id != supplier_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        body = get_body()
        name = require_field(body, "name", types=str)
        region_code = require_field(body, "region_code", types=str)
        cold = body.get("cold_chain_capable", False)
        if not isinstance(cold, bool):
            raise_err(ERR_VALIDATION_FAILED)
        hp = body.get("handling_periods", 1)
        chp = body.get("cold_handling_periods", 1)
        for v in (hp, chp):
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise_err(ERR_VALIDATION_FAILED)
        initial_status = body.get("initial_status")
        if initial_status is not None and initial_status not in ("ACTIVE", "DISABLED"):
            raise_err(ERR_VALIDATION_FAILED)
        wh = {
            **stamp_create(),
            "supplier_id": supplier_id,
            "name": name,
            "region_code": region_code,
            "cold_chain_capable": cold,
            "handling_periods": hp,
            "cold_handling_periods": chp,
            "status": initial_status or "ACTIVE",
            "created_period_index": store.system_period_index,
        }
        store.warehouses[wh["id"]] = wh
        return success(wh, http_status=201)

    @app.route("/suppliers/<supplier_id>/warehouses", methods=["GET"])
    def list_warehouses(supplier_id):
        parse_auth()
        require_role("PlatformAdmin", "Supplier")
        if supplier_id not in store.suppliers:
            raise_err(ERR_SUPPLIER_NOT_FOUND)
        if g.role == "Supplier" and g.user_id != supplier_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        limit, offset = list_pagination()
        items = [w for w in store.warehouses.values() if w["supplier_id"] == supplier_id]
        items = sort_by_created(items)
        page = items[offset:offset + limit]
        return list_success([dict(w) for w in page], len(items), limit, offset)

    # ---------------- Flash Campaigns ----------------

    @app.route("/suppliers/<supplier_id>/flash-campaigns", methods=["POST"])
    def create_flash_campaign(supplier_id):
        parse_auth()
        require_role("Supplier", "PlatformAdmin")
        if supplier_id not in store.suppliers:
            raise_err(ERR_SUPPLIER_NOT_FOUND)
        if g.role == "Supplier" and g.user_id != supplier_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        body = get_body()
        sku = require_field(body, "sku", types=str)
        cold = body.get("cold_chain_required", False)
        if not isinstance(cold, bool):
            raise_err(ERR_VALIDATION_FAILED)
        unit_price_cents = require_positive_int(body, "unit_price_cents")
        tier_caps = require_field(body, "tier_caps", types=list)
        if not tier_caps:
            raise_err(ERR_VALIDATION_FAILED, "tier_caps must be non-empty")
        for tc in tier_caps:
            if not isinstance(tc, dict):
                raise_err(ERR_VALIDATION_FAILED)
            t = tc.get("tier")
            mu = tc.get("max_units")
            if not isinstance(t, int) or isinstance(t, bool):
                raise_err(ERR_VALIDATION_FAILED)
            if not isinstance(mu, int) or isinstance(mu, bool) or mu <= 0:
                raise_err(ERR_VALIDATION_FAILED)
        total_stock = require_positive_int(body, "total_stock")
        opens = require_non_negative_int(body, "opens_at_period")
        closes = require_non_negative_int(body, "closes_at_period")
        if closes <= opens:
            raise_err(ERR_VALIDATION_FAILED, "closes_at_period must exceed opens_at_period")
        cmp = {
            **stamp_create(),
            "supplier_id": supplier_id,
            "sku": sku,
            "cold_chain_required": cold,
            "unit_price_cents": unit_price_cents,
            "tier_caps": [dict(tc) for tc in tier_caps],
            "total_stock": total_stock,
            "locked_units": 0,
            "allocated_units": 0,
            "remaining_units": total_stock,
            "opens_at_period": opens,
            "closes_at_period": closes,
            "status": "SCHEDULED",
        }
        store.flash_campaigns[cmp["id"]] = cmp
        store.flash_request_seq[cmp["id"]] = 0
        return success(serialize_flash(cmp), http_status=201)

    @app.route("/flash-campaigns/<flash_campaign_id>", methods=["GET"])
    def get_flash_campaign(flash_campaign_id):
        parse_auth()
        require_role("PlatformAdmin", "Supplier", "Customer")
        cmp = store.flash_campaigns.get(flash_campaign_id)
        if cmp is None:
            raise_err(ERR_FLASH_CAMPAIGN_NOT_FOUND)
        if g.role == "Supplier" and g.user_id != cmp["supplier_id"]:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        return success(serialize_flash(cmp))

    @app.route("/flash-campaigns/<flash_campaign_id>/purchase", methods=["POST"])
    def flash_purchase(flash_campaign_id):
        parse_auth()
        require_role("Customer")
        cmp = store.flash_campaigns.get(flash_campaign_id)
        if cmp is None:
            raise_err(ERR_FLASH_CAMPAIGN_NOT_FOUND)
        body = get_body()
        # Priority pair: flash campaign open status BEFORE stock check
        if flash_status(cmp) != "OPEN":
            raise_err(ERR_FLASH_CAMPAIGN_NOT_OPEN)
        # Customer status check
        cust = store.customers[g.user_id]
        if cust["status"] == "BLOCKED":
            raise_err(ERR_CUSTOMER_BLOCKED)
        if cust["status"] == "RISK_HOLD":
            raise_err(ERR_CUSTOMER_RISK_HOLD)
        # Validate requested_units
        requested_units = body.get("requested_units")
        if not isinstance(requested_units, int) or isinstance(requested_units, bool):
            raise_err(ERR_VALIDATION_FAILED, "requested_units required")
        if requested_units <= 0:
            raise_err(ERR_INVALID_QUANTITY)
        # Determine cap from tier_caps and request_seq
        seq = store.flash_request_seq.get(cmp["id"], 0)
        cap = calc.per_customer_cap(cmp["tier_caps"], seq)
        remaining = cmp["total_stock"] - cmp["locked_units"] - cmp["allocated_units"]
        # PRD §3.5: anti-oversell check — if remaining_units is below
        # requested_units, request fails with ERR_FLASH_STOCK_DEPLETED.
        if remaining < requested_units:
            raise_err(ERR_FLASH_STOCK_DEPLETED)
        granted = min(requested_units, remaining, cap)
        if granted <= 0:
            raise_err(ERR_FLASH_STOCK_DEPLETED)
        # Allocate
        cmp["allocated_units"] += granted
        cmp["remaining_units"] = cmp["total_stock"] - cmp["locked_units"] - cmp["allocated_units"]
        store.flash_request_seq[cmp["id"]] = seq + 1
        if cmp["remaining_units"] <= 0:
            cmp["status"] = "EXHAUSTED"
        bump(cmp)
        # Create order
        order = {
            **stamp_create(),
            "campaign_kind": "FLASH",
            "campaign_id": cmp["id"],
            "flash_granted_units": granted,
            "customer_id": g.user_id,
            "line_items": [{
                "sku": cmp["sku"],
                "unit_price_cents": cmp["unit_price_cents"],
                "quantity": granted,
            }],
            "subtotal_cents": cmp["unit_price_cents"] * granted,
            "provisional_discount_basis_points": 0,
            "provisional_total_cents": cmp["unit_price_cents"] * granted,
            "settled_total_cents": cmp["unit_price_cents"] * granted,
            "refunded_amount_cents": 0,
            "payment_status": "SETTLED",
            "fulfillment_status": "NOT_PLANNED",
            "created_period_index": store.system_period_index,
            "paid_period_index": store.system_period_index,
            "created_seq": store.next_seq(),
        }
        store.orders[order["id"]] = order
        return success(order, http_status=201)

    # ---------------- Group-Buy Campaigns ----------------

    @app.route("/group-leaders/<leader_id>/group-buy-campaigns", methods=["POST"])
    def create_group_buy_campaign(leader_id):
        parse_auth()
        require_role("GroupLeader")
        if leader_id not in store.group_leaders:
            raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        leader = store.group_leaders[leader_id]
        # Ownership: acting leader must be the path leader (subtree per PRD §2.1)
        if g.role == "GroupLeader" and not is_in_subtree(g.user_id, leader_id):
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if leader["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE)
        body = get_body()
        supplier_id = require_field(body, "supplier_id", types=str)
        if supplier_id not in store.suppliers:
            raise_err(ERR_SUPPLIER_NOT_FOUND)
        sku = require_field(body, "sku", types=str)
        cold = body.get("cold_chain_required", False)
        if not isinstance(cold, bool):
            raise_err(ERR_VALIDATION_FAILED)
        unit_price_cents = require_positive_int(body, "unit_price_cents")
        discount_tiers = require_field(body, "discount_tiers", types=list)
        if not discount_tiers:
            raise_err(ERR_VALIDATION_FAILED, "discount_tiers must be non-empty")
        prev_min = -1
        for t in discount_tiers:
            if not isinstance(t, dict):
                raise_err(ERR_VALIDATION_FAILED)
            mp = t.get("min_participants")
            db = t.get("discount_basis_points")
            if not isinstance(mp, int) or isinstance(mp, bool) or mp < 1:
                raise_err(ERR_VALIDATION_FAILED)
            if not isinstance(db, int) or isinstance(db, bool) or db < 0:
                raise_err(ERR_VALIDATION_FAILED)
            if mp <= prev_min:
                raise_err(ERR_VALIDATION_FAILED, "discount_tiers must be ascending by min_participants")
            prev_min = mp
        opens = require_non_negative_int(body, "opens_at_period")
        deadline = require_non_negative_int(body, "deadline_period")
        if deadline <= opens:
            raise_err(ERR_VALIDATION_FAILED, "deadline_period must exceed opens_at_period")
        partners = body.get("cross_community_partner_leader_ids") or []
        if not isinstance(partners, list):
            raise_err(ERR_VALIDATION_FAILED)
        if len(partners) > 4:
            raise_err(ERR_VALIDATION_FAILED, "max 4 partner leaders")
        for pid in partners:
            partner = store.group_leaders.get(pid)
            if partner is None:
                raise_err(ERR_GROUP_LEADER_NOT_FOUND, "partner leader not found")
            if partner["status"] != "ACTIVE":
                raise_err(ERR_VALIDATION_FAILED, "partner leader not active")
            if partner.get("tier", 0) > 2:
                raise_err(ERR_VALIDATION_FAILED, "partner tier too high")
            if partner["community_id"] == leader["community_id"]:
                raise_err(ERR_VALIDATION_FAILED, "partner must be from different community")
        # Overlap check on (community_id, sku)
        for ex in store.group_buy_campaigns.values():
            if ex["community_id"] != leader["community_id"]:
                continue
            if ex["sku"] != sku:
                continue
            if ex["status"] not in ("FORMING", "EXTENDED", "SUCCEEDED"):
                continue
            # Half-open intervals [opens, deadline)
            if opens < ex["deadline_period"] and ex["opens_at_period"] < deadline:
                raise_err(ERR_COMMUNITY_CAMPAIGN_OVERLAP)
        cmp = {
            **stamp_create(),
            "leader_id": leader_id,
            "community_id": leader["community_id"],
            "cross_community_partner_leader_ids": list(partners),
            "supplier_id": supplier_id,
            "sku": sku,
            "cold_chain_required": cold,
            "unit_price_cents": unit_price_cents,
            "discount_tiers": [dict(t) for t in discount_tiers],
            "opens_at_period": opens,
            "deadline_period": deadline,
            "participant_count": 0,
            "settled_tier_index": None,
            "settled_discount_basis_points": None,
            "status": "FORMING",
            "extension_count": 0,
        }
        store.group_buy_campaigns[cmp["id"]] = cmp
        return success(serialize_groupbuy(cmp), http_status=201)

    @app.route("/group-buy-campaigns/<campaign_id>", methods=["GET"])
    def get_group_buy(campaign_id):
        parse_auth()
        require_role("PlatformAdmin", "GroupLeader", "Customer")
        cmp = store.group_buy_campaigns.get(campaign_id)
        if cmp is None:
            raise_err(ERR_CAMPAIGN_NOT_FOUND)
        if g.role == "GroupLeader" and not is_in_subtree(g.user_id, cmp["leader_id"]):
            raise_err(ERR_OWNERSHIP_VIOLATION)
        return success(serialize_groupbuy(cmp))

    @app.route("/group-buy-campaigns/<campaign_id>/orders", methods=["POST"])
    def join_group_buy(campaign_id):
        parse_auth()
        require_role("Customer")
        cmp = store.group_buy_campaigns.get(campaign_id)
        if cmp is None:
            raise_err(ERR_CAMPAIGN_NOT_FOUND)
        body = get_body()
        # body customer_id reference
        customer_id = body.get("customer_id")
        if customer_id and customer_id not in store.customers:
            raise_err(ERR_CUSTOMER_NOT_FOUND)
        if customer_id and customer_id != g.user_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        # Campaign open check (priority 8)
        if cmp["status"] not in ("FORMING", "EXTENDED"):
            raise_err(ERR_CAMPAIGN_NOT_OPEN)
        if store.system_period_index >= cmp["deadline_period"]:
            raise_err(ERR_CAMPAIGN_NOT_OPEN)
        # Customer status (priority 15)
        cust = store.customers[g.user_id]
        if cust["status"] == "BLOCKED":
            raise_err(ERR_CUSTOMER_BLOCKED)
        if cust["status"] == "RISK_HOLD":
            raise_err(ERR_CUSTOMER_RISK_HOLD)
        # Duplicate participation (priority 16)
        for o in store.orders.values():
            if o.get("campaign_kind") != "GROUP_BUY":
                continue
            if o["campaign_id"] != campaign_id:
                continue
            if o["customer_id"] != g.user_id:
                continue
            if o["payment_status"] in ("PENDING_PAY", "PAID", "SETTLED", "PARTIALLY_REFUNDED"):
                raise_err(ERR_DUPLICATE_PARTICIPATION)
        # Validate other body
        if not customer_id:
            raise_err(ERR_VALIDATION_FAILED, "customer_id required")
        line_items = require_field(body, "line_items", types=list)
        if not line_items:
            raise_err(ERR_VALIDATION_FAILED, "line_items must be non-empty")
        if len(line_items) > 5:
            raise_err(ERR_VALIDATION_FAILED, "line_items must have at most 5 entries")
        # Validate each line; primary sku must equal campaign sku
        primary_sku = cmp["sku"]
        primary_seen = False
        subtotal = 0
        for li in line_items:
            if not isinstance(li, dict):
                raise_err(ERR_VALIDATION_FAILED)
            sku = li.get("sku")
            up = li.get("unit_price_cents")
            qty = li.get("quantity")
            if not isinstance(sku, str):
                raise_err(ERR_VALIDATION_FAILED)
            if not isinstance(up, int) or isinstance(up, bool) or up <= 0:
                raise_err(ERR_VALIDATION_FAILED)
            if not isinstance(qty, int) or isinstance(qty, bool):
                raise_err(ERR_VALIDATION_FAILED)
            if qty <= 0:
                raise_err(ERR_INVALID_QUANTITY)
            if sku == primary_sku and not primary_seen:
                primary_seen = True
            else:
                # extra line: must be a SUCCEEDED campaign owned by leader subtree
                ok = False
                for other in store.group_buy_campaigns.values():
                    if other["sku"] != sku:
                        continue
                    if other["status"] != "SUCCEEDED":
                        continue
                    # leader subtree of cmp.leader_id
                    if not is_in_subtree(cmp["leader_id"], other["leader_id"]):
                        continue
                    ok = True
                    break
                if not ok:
                    raise_err(ERR_VALIDATION_FAILED, f"sku {sku} not eligible for cross-group bundling")
            subtotal += up * qty
        if not primary_seen:
            raise_err(ERR_VALIDATION_FAILED, "primary line for campaign sku missing")
        order = {
            **stamp_create(),
            "campaign_kind": "GROUP_BUY",
            "campaign_id": campaign_id,
            "flash_granted_units": None,
            "customer_id": g.user_id,
            "line_items": [dict(li) for li in line_items],
            "subtotal_cents": subtotal,
            "provisional_discount_basis_points": None,
            "provisional_total_cents": None,
            "settled_total_cents": None,
            "refunded_amount_cents": 0,
            "payment_status": "PENDING_PAY",
            "fulfillment_status": "NOT_PLANNED",
            "created_period_index": store.system_period_index,
            "paid_period_index": None,
            "created_seq": store.next_seq(),
        }
        store.orders[order["id"]] = order
        return success(order, http_status=201)

    @app.route("/orders/<order_id>", methods=["GET"])
    def get_order(order_id):
        parse_auth()
        require_role("PlatformAdmin", "Customer", "GroupLeader", "Supplier", "CustomerService")
        order = store.orders.get(order_id)
        if order is None:
            raise_err(ERR_ORDER_NOT_FOUND)
        if g.role == "Customer" and g.user_id != order["customer_id"]:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if g.role == "Supplier":
            sup_id = order_supplier_id(order)
            if sup_id != g.user_id:
                raise_err(ERR_OWNERSHIP_VIOLATION)
        if g.role == "GroupLeader":
            if order.get("campaign_kind") != "GROUP_BUY":
                raise_err(ERR_OWNERSHIP_VIOLATION)
            cmp = store.group_buy_campaigns.get(order["campaign_id"])
            if not cmp or not is_in_subtree(g.user_id, cmp["leader_id"]):
                raise_err(ERR_OWNERSHIP_VIOLATION)
        return success(order)

    @app.route("/orders/<order_id>/pay", methods=["POST"])
    def pay_order(order_id):
        parse_auth()
        require_role("Customer")
        order = store.orders.get(order_id)
        if order is None:
            raise_err(ERR_ORDER_NOT_FOUND)
        if g.user_id != order["customer_id"]:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if order["payment_status"] != "PENDING_PAY":
            raise_err(ERR_INVALID_STATE)
        if order.get("campaign_kind") != "GROUP_BUY":
            raise_err(ERR_INVALID_STATE)
        cmp = store.group_buy_campaigns.get(order["campaign_id"])
        if cmp is None:
            raise_err(ERR_CAMPAIGN_NOT_FOUND)
        # Campaign open check
        if cmp["status"] not in ("FORMING", "EXTENDED"):
            raise_err(ERR_CAMPAIGN_NOT_OPEN)
        if store.system_period_index >= cmp["deadline_period"]:
            raise_err(ERR_CAMPAIGN_NOT_OPEN)
        cust = store.customers[g.user_id]
        if cust["status"] == "BLOCKED":
            raise_err(ERR_CUSTOMER_BLOCKED)
        if cust["status"] == "RISK_HOLD":
            raise_err(ERR_CUSTOMER_RISK_HOLD)
        order["payment_status"] = "PAID"
        order["paid_period_index"] = store.system_period_index
        bump(order)
        # recompute participant_count then pin provisional
        new_pcount = compute_group_buy_participants(cmp["id"])
        cmp["participant_count"] = new_pcount
        bump(cmp)
        idx, disc_bp = calc.select_discount_tier(new_pcount, cmp["discount_tiers"])
        order["provisional_discount_basis_points"] = disc_bp
        order["provisional_total_cents"] = calc.compute_order_total(order["subtotal_cents"], disc_bp)
        bump(order)
        return success(order)

    @app.route("/orders/<order_id>/cancel", methods=["POST"])
    def cancel_order(order_id):
        parse_auth()
        require_role("Customer")
        order = store.orders.get(order_id)
        if order is None:
            raise_err(ERR_ORDER_NOT_FOUND)
        if g.user_id != order["customer_id"]:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        # Group-buy direct cancel forbidden
        if order.get("campaign_kind") == "GROUP_BUY":
            raise_err(ERR_INVALID_STATE)
        # Flash cancel: must be before AT_PICKUP
        if order["fulfillment_status"] not in ("NOT_PLANNED", "PLANNED", "DISPATCHED"):
            raise_err(ERR_INVALID_STATE)
        order["payment_status"] = "REFUNDED"
        order["fulfillment_status"] = "CANCELLED"
        order["refunded_amount_cents"] = order.get("subtotal_cents", 0)
        bump(order)
        cancel_non_terminal_shipments(order)
        # Inventory rollback
        cmp = store.flash_campaigns.get(order["campaign_id"])
        if cmp:
            granted = order.get("flash_granted_units") or 0
            cmp["allocated_units"] = max(cmp.get("allocated_units", 0) - granted, 0)
            cmp["remaining_units"] = cmp["total_stock"] - cmp["locked_units"] - cmp["allocated_units"]
            cur = store.system_period_index
            if cmp.get("status") == "EXHAUSTED" and cmp["remaining_units"] > 0 \
               and cur < cmp["closes_at_period"]:
                cmp["status"] = "OPEN"
            bump(cmp)
        return success(order)

    @app.route("/group-buy-campaigns/<campaign_id>/extend", methods=["POST"])
    def extend_campaign(campaign_id):
        parse_auth()
        require_role("GroupLeader")
        cmp = store.group_buy_campaigns.get(campaign_id)
        if cmp is None:
            raise_err(ERR_CAMPAIGN_NOT_FOUND)
        if not is_in_subtree(g.user_id, cmp["leader_id"]):
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if cmp["status"] != "FORMING":
            raise_err(ERR_INVALID_STATE)
        if cmp.get("extension_count", 0) >= 1:
            raise_err(ERR_INVALID_STATE)
        if store.system_period_index >= cmp["deadline_period"]:
            raise_err(ERR_INVALID_STATE)
        highest_min = max(t["min_participants"] for t in cmp["discount_tiers"])
        threshold = ceil(0.6 * highest_min)
        pcount = compute_group_buy_participants(cmp["id"])
        cmp["participant_count"] = pcount
        if pcount < threshold:
            raise_err(ERR_INVALID_STATE)
        # FORMING -> EXTENDED then back to FORMING (idempotent)
        cmp["status"] = "EXTENDED"
        bump(cmp)
        cmp["deadline_period"] = cmp["deadline_period"] + 2
        cmp["extension_count"] = cmp.get("extension_count", 0) + 1
        cmp["status"] = "FORMING"
        bump(cmp)
        return success(serialize_groupbuy(cmp))

    @app.route("/group-buy-campaigns/<campaign_id>/close", methods=["POST"])
    def close_campaign(campaign_id):
        parse_auth()
        require_role("GroupLeader", "PlatformAdmin")
        cmp = store.group_buy_campaigns.get(campaign_id)
        if cmp is None:
            raise_err(ERR_CAMPAIGN_NOT_FOUND)
        if g.role == "GroupLeader" and not is_in_subtree(g.user_id, cmp["leader_id"]):
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if cmp["status"] not in ("FORMING", "EXTENDED"):
            raise_err(ERR_INVALID_STATE)
        pcount = compute_group_buy_participants(cmp["id"])
        cmp["participant_count"] = pcount
        threshold = cmp["discount_tiers"][0]["min_participants"]
        if pcount >= threshold:
            close_campaign_succeeded(cmp)
        else:
            close_campaign_failed(cmp)
        return success(serialize_groupbuy(cmp))

    @app.route("/group-buy-campaigns/<campaign_id>/finalize", methods=["POST"])
    def finalize_campaign(campaign_id):
        parse_auth()
        require_role("PlatformAdmin")
        cmp = store.group_buy_campaigns.get(campaign_id)
        if cmp is None:
            raise_err(ERR_CAMPAIGN_NOT_FOUND)
        if cmp["status"] not in ("SUCCEEDED", "FAILED"):
            raise_err(ERR_INVALID_STATE)
        # Verify all child orders are terminal in payment + fulfillment
        TERMINAL_PAY = {"REFUNDED", "PARTIALLY_REFUNDED", "SETTLED"}
        TERMINAL_FUL = {"COMPLETED", "CANCELLED"}
        for o in store.orders.values():
            if o.get("campaign_kind") != "GROUP_BUY":
                continue
            if o["campaign_id"] != campaign_id:
                continue
            if o["payment_status"] not in TERMINAL_PAY:
                raise_err(ERR_INVALID_STATE)
            if o["fulfillment_status"] not in TERMINAL_FUL:
                raise_err(ERR_INVALID_STATE)
        cmp["status"] = "CLOSED"
        bump(cmp)
        return success(serialize_groupbuy(cmp))

    # ---------------- Plan / Dispatch / Pickup ----------------

    @app.route("/orders/<order_id>/plan-shipments", methods=["POST"])
    def plan_shipments(order_id):
        parse_auth()
        require_role("Supplier", "PlatformAdmin")
        order = store.orders.get(order_id)
        if order is None:
            raise_err(ERR_ORDER_NOT_FOUND)
        sup_id = order_supplier_id(order)
        if g.role == "Supplier" and g.user_id != sup_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        # Preconditions: payment_status SETTLED; group-buy parent SUCCEEDED
        if order["payment_status"] != "SETTLED":
            raise_err(ERR_INVALID_STATE)
        if order.get("campaign_kind") == "GROUP_BUY":
            cmp = store.group_buy_campaigns.get(order["campaign_id"])
            if cmp is None or cmp["status"] != "SUCCEEDED":
                raise_err(ERR_INVALID_STATE)
        if order["fulfillment_status"] != "NOT_PLANNED":
            raise_err(ERR_INVALID_STATE)
        body = get_body()
        plan = body.get("shipment_plan")
        if not isinstance(plan, list) or not plan:
            raise_err(ERR_VALIDATION_FAILED, "shipment_plan required")
        # Determine if any line in any plan element references a cold-chain SKU
        cold_skus = set()
        for li in order["line_items"]:
            sku = li["sku"]
            # Determine cold flag: if this sku has a cold_chain_required campaign by sup_id
            for cmp in store.group_buy_campaigns.values():
                if cmp["sku"] == sku and cmp.get("cold_chain_required"):
                    cold_skus.add(sku)
            for cmp in store.flash_campaigns.values():
                if cmp["sku"] == sku and cmp.get("cold_chain_required"):
                    cold_skus.add(sku)
        # Validate each plan element
        for el in plan:
            if not isinstance(el, dict):
                raise_err(ERR_VALIDATION_FAILED)
            pp_id = el.get("pickup_point_id")
            line_units = el.get("line_units")
            if not pp_id or pp_id not in store.pickup_points:
                raise_err(ERR_PICKUP_POINT_NOT_FOUND)
            if not isinstance(line_units, list) or not line_units:
                raise_err(ERR_VALIDATION_FAILED)
            for lu in line_units:
                if not isinstance(lu, dict):
                    raise_err(ERR_VALIDATION_FAILED)
                if not isinstance(lu.get("sku"), str):
                    raise_err(ERR_VALIDATION_FAILED)
                qty = lu.get("quantity")
                if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                    raise_err(ERR_VALIDATION_FAILED)
        # Cold-chain safety check (priority 9) BEFORE warehouse pool check (priority 10)
        any_cold = False
        for el in plan:
            for lu in el["line_units"]:
                if lu["sku"] in cold_skus:
                    any_cold = True
                    break
            if any_cold:
                break
        if any_cold:
            has_cold_capable = any(
                w["supplier_id"] == sup_id and w.get("cold_chain_capable")
                for w in store.warehouses.values()
            )
            if not has_cold_capable:
                raise_err(ERR_COLD_CHAIN_REQUIRED)
        # Determine community for region matching
        community_id = order_community_id(order)
        community = store.communities.get(community_id) if community_id else None
        order_region = community["region_code"] if community else None
        # Build candidate set per shipment line group
        created_shipments = []
        for el in plan:
            cold_seg = any(lu["sku"] in cold_skus for lu in el["line_units"])
            candidates = [w for w in store.warehouses.values()
                          if w["supplier_id"] == sup_id and w["status"] == "ACTIVE"]
            if cold_seg:
                candidates = [w for w in candidates if w.get("cold_chain_capable")]
            if not candidates:
                raise_err(ERR_NO_WAREHOUSE_AVAILABLE)
            # Rank: region match (0 better), then created_period_index asc, then id asc
            def keyf(w):
                rmatch = 0 if w["region_code"] == order_region else 1
                return (rmatch, w.get("created_period_index", 0), w["id"])
            candidates.sort(key=keyf)
            chosen = candidates[0]
            shipment = {
                **stamp_create(),
                "order_id": order_id,
                "warehouse_id": chosen["id"],
                "pickup_point_id": el["pickup_point_id"],
                "line_units": [dict(lu) for lu in el["line_units"]],
                "cold_chain_segment": cold_seg,
                "dispatched_period_index": None,
                "predicted_eta_period_index": None,
                "actual_delivered_period_index": None,
                "status": "PLANNED",
            }
            store.shipments[shipment["id"]] = shipment
            created_shipments.append(shipment)
        order["fulfillment_status"] = "PLANNED"
        bump(order)
        return success([dict(s) for s in created_shipments],
                       http_status=201, response_type="array")

    @app.route("/shipments/<shipment_id>", methods=["GET"])
    def get_shipment(shipment_id):
        parse_auth()
        require_role("PlatformAdmin", "Supplier", "Customer", "PickupOperator")
        shp = store.shipments.get(shipment_id)
        if shp is None:
            raise_err(ERR_SHIPMENT_NOT_FOUND)
        if g.role == "Supplier":
            wh = store.warehouses.get(shp["warehouse_id"])
            if not wh or wh["supplier_id"] != g.user_id:
                raise_err(ERR_OWNERSHIP_VIOLATION)
        if g.role == "Customer":
            order = store.orders.get(shp["order_id"])
            if not order or order["customer_id"] != g.user_id:
                raise_err(ERR_OWNERSHIP_VIOLATION)
        return success(shp)

    @app.route("/shipments/<shipment_id>/dispatch", methods=["POST"])
    def dispatch_shipment(shipment_id):
        parse_auth()
        require_role("Supplier")
        shp = store.shipments.get(shipment_id)
        if shp is None:
            raise_err(ERR_SHIPMENT_NOT_FOUND)
        wh = store.warehouses.get(shp["warehouse_id"])
        if not wh or wh["supplier_id"] != g.user_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if shp["status"] != "PLANNED":
            raise_err(ERR_INVALID_STATE)
        shp["status"] = "DISPATCHED"
        shp["dispatched_period_index"] = store.system_period_index
        shp["predicted_eta_period_index"] = calc.compute_shipment_eta(
            store.system_period_index, wh, shp.get("cold_chain_segment", False)
        )
        bump(shp)
        # Order: PLANNED -> DISPATCHED if all child shipments are DISPATCHED+
        order = store.orders.get(shp["order_id"])
        if order:
            children = [s for s in store.shipments.values() if s["order_id"] == order["id"]]
            if all(s["status"] in ("DISPATCHED", "AT_PICKUP", "MIS_PICK", "RECONCILED",
                                   "DELIVERED") for s in children):
                if order["fulfillment_status"] == "PLANNED":
                    order["fulfillment_status"] = "DISPATCHED"
                    bump(order)
        return success(shp)

    @app.route("/shipments/<shipment_id>/arrive-at-pickup", methods=["POST"])
    def arrive_at_pickup(shipment_id):
        parse_auth()
        require_role("Supplier")
        shp = store.shipments.get(shipment_id)
        if shp is None:
            raise_err(ERR_SHIPMENT_NOT_FOUND)
        wh = store.warehouses.get(shp["warehouse_id"])
        if not wh or wh["supplier_id"] != g.user_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if shp["status"] != "DISPATCHED":
            raise_err(ERR_INVALID_STATE)
        pp = store.pickup_points.get(shp["pickup_point_id"])
        if pp is None:
            raise_err(ERR_PICKUP_POINT_NOT_FOUND)
        # Capacity check (priority 11)
        held = compute_held_count(pp["id"])
        if held + 1 > pp["capacity_packages"]:
            raise_err(ERR_PICKUP_POINT_AT_CAPACITY)
        # Cold-incompat check (priority 12)
        if shp.get("cold_chain_segment") and not pp.get("cold_storage_capable"):
            raise_err(ERR_PICKUP_POINT_COLD_INCOMPATIBLE)
        shp["status"] = "AT_PICKUP"
        bump(shp)
        bump(pp)
        # Order: DISPATCHED -> AT_PICKUP if all children at AT_PICKUP/RECONCILED
        order = store.orders.get(shp["order_id"])
        if order and order["fulfillment_status"] == "DISPATCHED":
            children = [s for s in store.shipments.values() if s["order_id"] == order["id"]]
            if all(s["status"] in ("AT_PICKUP", "RECONCILED") for s in children):
                order["fulfillment_status"] = "AT_PICKUP"
                bump(order)
        return success(shp)

    @app.route("/shipments/<shipment_id>/report-mispick", methods=["POST"])
    def report_mispick(shipment_id):
        parse_auth()
        require_role("PickupOperator")
        shp = store.shipments.get(shipment_id)
        if shp is None:
            raise_err(ERR_SHIPMENT_NOT_FOUND)
        if shp["status"] != "AT_PICKUP":
            raise_err(ERR_INVALID_STATE)
        shp["status"] = "MIS_PICK"
        bump(shp)
        return success(shp)

    @app.route("/shipments/<shipment_id>/reconcile", methods=["POST"])
    def reconcile_shipment(shipment_id):
        parse_auth()
        require_role("PickupOperator")
        shp = store.shipments.get(shipment_id)
        if shp is None:
            raise_err(ERR_SHIPMENT_NOT_FOUND)
        if shp["status"] != "MIS_PICK":
            raise_err(ERR_INVALID_STATE)
        # MIS_PICK -> RECONCILED -> AT_PICKUP equivalent (treat as AT_PICKUP)
        shp["status"] = "AT_PICKUP"
        bump(shp)
        return success(shp)

    @app.route("/orders/<order_id>/pickup-confirm", methods=["POST"])
    def pickup_confirm(order_id):
        parse_auth()
        require_role("Customer")
        order = store.orders.get(order_id)
        if order is None:
            raise_err(ERR_ORDER_NOT_FOUND)
        if g.user_id != order["customer_id"]:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if order["fulfillment_status"] != "AT_PICKUP":
            raise_err(ERR_INVALID_STATE)
        children = [s for s in store.shipments.values() if s["order_id"] == order["id"]]
        for s in children:
            if s["status"] not in ("AT_PICKUP", "RECONCILED"):
                raise_err(ERR_INVALID_STATE)
        # All children -> DELIVERED
        for s in children:
            s["status"] = "DELIVERED"
            s["actual_delivered_period_index"] = store.system_period_index
            bump(s)
        order["fulfillment_status"] = "PICKED_UP"
        bump(order)
        store.picked_up_period[order["id"]] = store.system_period_index
        return success(order)

    # ---------------- Pickup Points ----------------

    @app.route("/communities/<community_id>/pickup-points", methods=["POST"])
    def create_pickup_point(community_id):
        parse_auth()
        require_role("PlatformAdmin")
        if community_id not in store.communities:
            raise_err(ERR_COMMUNITY_NOT_FOUND)
        body = get_body()
        name = require_field(body, "name", types=str)
        capacity = body.get("capacity_packages")
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise_err(ERR_VALIDATION_FAILED)
        cold_storage = body.get("cold_storage_capable", False)
        if not isinstance(cold_storage, bool):
            raise_err(ERR_VALIDATION_FAILED)
        pp = {
            **stamp_create(),
            "community_id": community_id,
            "name": name,
            "capacity_packages": capacity,
            "cold_storage_capable": cold_storage,
            "held_package_count": 0,
            "status": "ACTIVE",
        }
        store.pickup_points[pp["id"]] = pp
        return success(serialize_pickup_point(pp), http_status=201)

    @app.route("/pickup-points/<pickup_point_id>/summary", methods=["GET"])
    def pickup_point_summary(pickup_point_id):
        parse_auth()
        require_role("PlatformAdmin", "PickupOperator")
        pp = store.pickup_points.get(pickup_point_id)
        if pp is None:
            raise_err(ERR_PICKUP_POINT_NOT_FOUND)
        held = compute_held_count(pp["id"])
        factor = calc.load_factor(held, pp["capacity_packages"])
        state = calc.load_state(factor)
        return success({
            "pickup_point_id": pp["id"],
            "held_package_count": held,
            "capacity_packages": pp["capacity_packages"],
            "load_factor": factor,
            "load_state": state,
        })

    @app.route("/pickup-points/<pickup_point_id>/consolidation-batches", methods=["POST"])
    def create_consolidation_batch(pickup_point_id):
        parse_auth()
        require_role("PickupOperator")
        if pickup_point_id not in store.pickup_points:
            raise_err(ERR_PICKUP_POINT_NOT_FOUND)
        body = get_body()
        ws = body.get("window_start_period")
        we = body.get("window_end_period")
        ship_ids = body.get("shipment_ids")
        for v in (ws, we):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise_err(ERR_VALIDATION_FAILED)
        if we < ws:
            raise_err(ERR_VALIDATION_FAILED)
        if not isinstance(ship_ids, list) or not ship_ids:
            raise_err(ERR_VALIDATION_FAILED)
        # Body-referenced existence + state
        for sid in ship_ids:
            shp = store.shipments.get(sid)
            if shp is None:
                raise_err(ERR_SHIPMENT_NOT_FOUND)
            if shp["pickup_point_id"] != pickup_point_id:
                raise_err(ERR_INVALID_STATE)
            if shp["status"] != "AT_PICKUP":
                raise_err(ERR_INVALID_STATE)
        # Overlap check (buffered vs buffered)
        new_a, new_b = ws - 1, we + 1
        for ex in store.consolidation_batches.values():
            if ex["pickup_point_id"] != pickup_point_id:
                continue
            ex_a, ex_b = ex["window_start_period"] - 1, ex["window_end_period"] + 1
            if new_a <= ex_b and ex_a <= new_b:
                raise_err(ERR_CONSOLIDATION_WINDOW_OVERLAP)
        b = {
            **stamp_create_minimal(),
            "pickup_point_id": pickup_point_id,
            "window_start_period": ws,
            "window_end_period": we,
            "shipment_ids": list(ship_ids),
            "status": "OPEN",
        }
        store.consolidation_batches[b["id"]] = b
        return success(serialize_consolidation(b), http_status=201)

    # ---------------- After-Sales ----------------

    @app.route("/orders/<order_id>/after-sales-cases", methods=["POST"])
    def file_after_sales(order_id):
        parse_auth()
        require_role("Customer")
        order = store.orders.get(order_id)
        if order is None:
            raise_err(ERR_ORDER_NOT_FOUND)
        if g.user_id != order["customer_id"]:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        # Window check
        picked_period = store.picked_up_period.get(order_id)
        if picked_period is None or store.system_period_index - picked_period > 7:
            raise_err(ERR_AFTER_SALES_WINDOW_EXPIRED)
        # Already-open check
        for c in store.after_sales_cases.values():
            if c["order_id"] != order_id:
                continue
            if c["status"] not in ("RESOLVED_REFUND_ONLY", "RESOLVED_RETURN_REFUND",
                                    "RESOLVED_PARTIAL_COMPENSATION", "REJECTED"):
                raise_err(ERR_AFTER_SALES_ALREADY_OPEN)
        body = get_body()
        case_type = body.get("case_type")
        if case_type not in ("REFUND_ONLY", "RETURN_AND_REFUND", "PARTIAL_COMPENSATION"):
            raise_err(ERR_VALIDATION_FAILED)
        ramt = body.get("requested_amount_cents")
        if not isinstance(ramt, int) or isinstance(ramt, bool) or ramt <= 0:
            raise_err(ERR_VALIDATION_FAILED)
        remaining = order.get("settled_total_cents", 0) - order.get("refunded_amount_cents", 0)
        if ramt > remaining:
            raise_err(ERR_AFTER_SALES_AMOUNT_EXCEEDS_REMAINING)
        c = {
            **stamp_create(),
            "order_id": order_id,
            "case_type": case_type,
            "requested_amount_cents": ramt,
            "status": "FILED",
            "evidence_round": 0,
            "resolved_amount_cents": 0,
            "filed_period_index": store.system_period_index,
        }
        store.after_sales_cases[c["id"]] = c
        return success(c, http_status=201)

    @app.route("/after-sales/<case_id>", methods=["GET"])
    def get_after_sales(case_id):
        parse_auth()
        require_role("PlatformAdmin", "Customer", "CustomerService")
        c = store.after_sales_cases.get(case_id)
        if c is None:
            raise_err(ERR_AFTER_SALES_CASE_NOT_FOUND)
        if g.role == "Customer":
            order = store.orders.get(c["order_id"])
            if not order or order["customer_id"] != g.user_id:
                raise_err(ERR_OWNERSHIP_VIOLATION)
        return success(c)

    @app.route("/after-sales/<case_id>/start-review", methods=["POST"])
    def start_review(case_id):
        parse_auth()
        require_role("CustomerService")
        c = store.after_sales_cases.get(case_id)
        if c is None:
            raise_err(ERR_AFTER_SALES_CASE_NOT_FOUND)
        if c["status"] != "FILED":
            raise_err(ERR_INVALID_STATE)
        c["status"] = "UNDER_REVIEW"
        bump(c)
        return success(c)

    @app.route("/after-sales/<case_id>/request-evidence", methods=["POST"])
    def request_evidence(case_id):
        parse_auth()
        require_role("CustomerService")
        c = store.after_sales_cases.get(case_id)
        if c is None:
            raise_err(ERR_AFTER_SALES_CASE_NOT_FOUND)
        if c["status"] != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE)
        if c.get("evidence_round", 0) >= 2:
            raise_err(ERR_INVALID_STATE)
        c["status"] = "EVIDENCE_REQUESTED"
        bump(c)
        return success(c)

    @app.route("/after-sales/<case_id>/submit-evidence", methods=["POST"])
    def submit_evidence(case_id):
        parse_auth()
        require_role("Customer")
        c = store.after_sales_cases.get(case_id)
        if c is None:
            raise_err(ERR_AFTER_SALES_CASE_NOT_FOUND)
        order = store.orders.get(c["order_id"])
        if not order or order["customer_id"] != g.user_id:
            raise_err(ERR_OWNERSHIP_VIOLATION)
        if c["status"] != "EVIDENCE_REQUESTED":
            raise_err(ERR_INVALID_STATE)
        c["status"] = "UNDER_REVIEW"
        c["evidence_round"] = c.get("evidence_round", 0) + 1
        bump(c)
        return success(c)

    @app.route("/after-sales/<case_id>/escalate", methods=["POST"])
    def escalate_case(case_id):
        parse_auth()
        require_role("CustomerService")
        c = store.after_sales_cases.get(case_id)
        if c is None:
            raise_err(ERR_AFTER_SALES_CASE_NOT_FOUND)
        if c["status"] != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE)
        if c.get("evidence_round", 0) < 1:
            raise_err(ERR_INVALID_STATE)
        c["status"] = "ARBITRATION"
        bump(c)
        return success(c)

    @app.route("/after-sales/<case_id>/resolve", methods=["POST"])
    def resolve_case(case_id):
        parse_auth()
        require_role("CustomerService", "PlatformAdmin")
        c = store.after_sales_cases.get(case_id)
        if c is None:
            raise_err(ERR_AFTER_SALES_CASE_NOT_FOUND)
        body = get_body()
        outcome = body.get("outcome")
        if outcome not in ("REFUND_ONLY", "RETURN_REFUND", "PARTIAL_COMPENSATION", "REJECT"):
            raise_err(ERR_VALIDATION_FAILED)
        if c["status"] not in ("UNDER_REVIEW", "ARBITRATION"):
            raise_err(ERR_INVALID_STATE)
        if c["status"] == "ARBITRATION" and g.role != "PlatformAdmin":
            raise_err(ERR_FORBIDDEN)
        if c["status"] == "UNDER_REVIEW" and g.role not in ("CustomerService", "PlatformAdmin"):
            raise_err(ERR_FORBIDDEN)
        order = store.orders.get(c["order_id"])
        if order is None:
            raise_err(ERR_ORDER_NOT_FOUND)
        # Branch
        if outcome == "REFUND_ONLY":
            if c["case_type"] != "REFUND_ONLY":
                raise_err(ERR_INVALID_STATE)
            c["resolved_amount_cents"] = c["requested_amount_cents"]
            c["status"] = "RESOLVED_REFUND_ONLY"
            order_to_refund_pending(order, c["resolved_amount_cents"])
        elif outcome == "RETURN_REFUND":
            if c["case_type"] != "RETURN_AND_REFUND":
                raise_err(ERR_INVALID_STATE)
            if order["fulfillment_status"] not in ("PICKED_UP", "COMPLETED"):
                raise_err(ERR_INVALID_STATE)
            c["resolved_amount_cents"] = c["requested_amount_cents"]
            c["status"] = "RESOLVED_RETURN_REFUND"
            order_to_refund_pending(order, c["resolved_amount_cents"])
        elif outcome == "PARTIAL_COMPENSATION":
            if c["case_type"] != "PARTIAL_COMPENSATION":
                raise_err(ERR_INVALID_STATE)
            c["resolved_amount_cents"] = c["requested_amount_cents"]
            c["status"] = "RESOLVED_PARTIAL_COMPENSATION"
            proportional_partial_compensation(order, c["resolved_amount_cents"])
        else:  # REJECT
            c["resolved_amount_cents"] = 0
            prior_status = c["status"]
            c["status"] = "REJECTED"
            # If a prior transition pushed order to REFUND_PENDING, revert.
            if order["payment_status"] == "REFUND_PENDING":
                # Revert to SETTLED
                order["payment_status"] = "SETTLED"
                bump(order)
                store.refund_pending.pop(order["id"], None)
                revert_clawbacks_for_order(order)
        bump(c)
        return success(c)

    # ---------------- Commissions / Payouts ----------------

    @app.route("/group-leaders/<leader_id>/commission-entries", methods=["GET"])
    def list_commission_entries(leader_id):
        parse_auth()
        require_role("PlatformAdmin", "GroupLeader")
        if leader_id not in store.group_leaders:
            raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        if g.role == "GroupLeader" and not is_in_subtree(g.user_id, leader_id):
            raise_err(ERR_OWNERSHIP_VIOLATION)
        status_filter = request.args.get("status")
        limit, offset = list_pagination()
        items = [e for e in store.commission_entries.values() if e["leader_id"] == leader_id]
        if status_filter:
            items = [e for e in items if e["status"] == status_filter]
        items = sort_by_created(items)
        page = items[offset:offset + limit]
        return list_success([dict(e) for e in page], len(items), limit, offset)

    @app.route("/group-leaders/<leader_id>/payouts", methods=["POST"])
    def assemble_payout(leader_id):
        parse_auth()
        require_role("PlatformAdmin")
        if leader_id not in store.group_leaders:
            raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        body = get_body()
        target = body.get("target_period_index")
        if not isinstance(target, int) or isinstance(target, bool) or target < 0:
            raise_err(ERR_VALIDATION_FAILED)
        bundled = []
        for e in store.commission_entries.values():
            if e["leader_id"] != leader_id:
                continue
            if e.get("payout_id"):
                continue
            if e["status"] not in ("PENDING", "PENDING_CLAWBACK"):
                continue
            if e["payout_target_period_index"] > target:
                continue
            bundled.append(e)
        bundled = sort_by_created(bundled)
        total = sum(e["net_rebate_cents"] for e in bundled)
        payout = {
            **stamp_create(),
            "leader_id": leader_id,
            "target_period_index": target,
            "bundled_entry_ids": [e["id"] for e in bundled],
            "total_amount_cents": total,
            "status": "SCHEDULED",
        }
        store.payouts[payout["id"]] = payout
        for e in bundled:
            e["payout_id"] = payout["id"]
            bump(e)
        return success(payout, http_status=201)

    @app.route("/payouts/<payout_id>", methods=["GET"])
    def get_payout(payout_id):
        parse_auth()
        require_role("PlatformAdmin", "GroupLeader")
        p = store.payouts.get(payout_id)
        if p is None:
            raise_err(ERR_PAYOUT_NOT_FOUND)
        if g.role == "GroupLeader" and not is_in_subtree(g.user_id, p["leader_id"]):
            raise_err(ERR_OWNERSHIP_VIOLATION)
        return success(p)

    @app.route("/payouts/<payout_id>/release", methods=["POST"])
    def release_payout(payout_id):
        parse_auth()
        require_role("PlatformAdmin")
        p = store.payouts.get(payout_id)
        if p is None:
            raise_err(ERR_PAYOUT_NOT_FOUND)
        # Bundled clawback check (priority 20) BEFORE not-matured (priority 21)
        for entry_id in p["bundled_entry_ids"]:
            ce = store.commission_entries.get(entry_id)
            if ce and ce["status"] in ("PENDING_CLAWBACK", "CLAWED_BACK"):
                raise_err(ERR_PAYOUT_HAS_PENDING_CLAWBACK)
        if p["status"] != "MATURED":
            raise_err(ERR_PAYOUT_NOT_MATURED)
        p["status"] = "RELEASED"
        bump(p)
        for entry_id in p["bundled_entry_ids"]:
            ce = store.commission_entries.get(entry_id)
            if ce and ce["status"] == "PENDING":
                ce["status"] = "SETTLED"
                bump(ce)
        return success(p)

    @app.route("/payouts/<payout_id>/cancel", methods=["POST"])
    def cancel_payout(payout_id):
        parse_auth()
        require_role("PlatformAdmin")
        p = store.payouts.get(payout_id)
        if p is None:
            raise_err(ERR_PAYOUT_NOT_FOUND)
        if p["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE)
        p["status"] = "CANCELLED"
        bump(p)
        for entry_id in list(p["bundled_entry_ids"]):
            ce = store.commission_entries.get(entry_id)
            if ce and ce.get("payout_id") == p["id"]:
                ce["payout_id"] = None
                bump(ce)
        return success(p)

    # ---------------- Risk Alerts ----------------

    @app.route("/risk-alerts", methods=["POST"])
    def create_risk_alert():
        parse_auth()
        require_role("PlatformAdmin")
        body = get_body()
        alert_type = body.get("alert_type")
        target_kind = body.get("target_kind")
        target_id = body.get("target_id")
        severity = body.get("severity")
        supporting = body.get("supporting_supplier_id")
        if alert_type not in ("BOT_ORDER", "FAKE_GROUP_BUY", "LEADER_SUPPLIER_COLLUSION"):
            raise_err(ERR_VALIDATION_FAILED)
        if target_kind not in ("CUSTOMER", "GROUP_LEADER", "SUPPLIER", "ORDER"):
            raise_err(ERR_VALIDATION_FAILED)
        if severity not in ("LOW", "MEDIUM", "HIGH"):
            raise_err(ERR_VALIDATION_FAILED)
        if not isinstance(target_id, str) or not target_id:
            raise_err(ERR_VALIDATION_FAILED)
        # Pairing rules
        if alert_type == "BOT_ORDER":
            if target_kind not in ("CUSTOMER", "ORDER"):
                raise_err(ERR_VALIDATION_FAILED)
            if target_kind == "CUSTOMER" and target_id not in store.customers:
                raise_err(ERR_CUSTOMER_NOT_FOUND)
            if target_kind == "ORDER" and target_id not in store.orders:
                raise_err(ERR_ORDER_NOT_FOUND)
        elif alert_type == "FAKE_GROUP_BUY":
            if target_kind != "GROUP_LEADER":
                raise_err(ERR_VALIDATION_FAILED)
            if target_id not in store.group_leaders:
                raise_err(ERR_GROUP_LEADER_NOT_FOUND)
        elif alert_type == "LEADER_SUPPLIER_COLLUSION":
            if target_kind != "GROUP_LEADER":
                raise_err(ERR_VALIDATION_FAILED)
            if target_id not in store.group_leaders:
                raise_err(ERR_GROUP_LEADER_NOT_FOUND)
            if not isinstance(supporting, str) or not supporting:
                raise_err(ERR_VALIDATION_FAILED)
            if supporting not in store.suppliers:
                raise_err(ERR_SUPPLIER_NOT_FOUND)
        a = {
            **stamp_create_minimal(),
            "created_period_index": store.system_period_index,
            "alert_type": alert_type,
            "target_kind": target_kind,
            "target_id": target_id,
            "supporting_supplier_id": supporting,
            "severity": severity,
            "status": "OPEN",
        }
        store.risk_alerts[a["id"]] = a
        return success(a, http_status=201)

    @app.route("/risk-alerts/<alert_id>/confirm", methods=["POST"])
    def confirm_risk_alert(alert_id):
        parse_auth()
        require_role("PlatformAdmin")
        a = store.risk_alerts.get(alert_id)
        if a is None:
            raise_err(ERR_RISK_ALERT_NOT_FOUND)
        if a["status"] != "OPEN":
            raise_err(ERR_INVALID_STATE)
        a["status"] = "CONFIRMED"
        # Cascades
        if a["alert_type"] == "LEADER_SUPPLIER_COLLUSION" and a["target_kind"] == "GROUP_LEADER":
            leader = store.group_leaders.get(a["target_id"])
            if leader:
                leader["collusion_audit_count"] = leader.get("collusion_audit_count", 0) + 1
                if leader["status"] == "ACTIVE":
                    suspend_leader_cascade(leader)
                else:
                    bump(leader)
        elif a["severity"] == "HIGH" and a["target_kind"] == "GROUP_LEADER":
            leader = store.group_leaders.get(a["target_id"])
            if leader and leader["status"] == "ACTIVE":
                suspend_leader_cascade(leader)
        if a["alert_type"] == "BOT_ORDER" and a["target_kind"] == "CUSTOMER":
            cust = store.customers.get(a["target_id"])
            if cust and cust["status"] == "ACTIVE":
                cust["status"] = "RISK_HOLD"
                bump(cust)
        # Recompute risk for relevant leader if applicable
        if a["target_kind"] == "GROUP_LEADER":
            recompute_leader_risk(a["target_id"])
        elif a["alert_type"] == "BOT_ORDER" and a["target_kind"] == "ORDER":
            order = store.orders.get(a["target_id"])
            if order and order.get("campaign_kind") == "GROUP_BUY":
                cmp = store.group_buy_campaigns.get(order["campaign_id"])
                if cmp:
                    recompute_leader_risk(cmp["leader_id"])
        return success(a)

    @app.route("/risk-alerts/<alert_id>/dismiss", methods=["POST"])
    def dismiss_risk_alert(alert_id):
        parse_auth()
        require_role("PlatformAdmin")
        a = store.risk_alerts.get(alert_id)
        if a is None:
            raise_err(ERR_RISK_ALERT_NOT_FOUND)
        if a["status"] != "OPEN":
            raise_err(ERR_INVALID_STATE)
        a["status"] = "DISMISSED"
        return success(a)


# ---------------- Helpers ----------------

def order_supplier_id(order):
    cid = order.get("campaign_id")
    if order.get("campaign_kind") == "GROUP_BUY":
        cmp = store.group_buy_campaigns.get(cid)
        return cmp["supplier_id"] if cmp else None
    if order.get("campaign_kind") == "FLASH":
        cmp = store.flash_campaigns.get(cid)
        return cmp["supplier_id"] if cmp else None
    return None


def order_community_id(order):
    if order.get("campaign_kind") == "GROUP_BUY":
        cmp = store.group_buy_campaigns.get(order["campaign_id"])
        return cmp["community_id"] if cmp else None
    if order.get("campaign_kind") == "FLASH":
        cust = store.customers.get(order["customer_id"])
        return cust["community_id"] if cust else None
    return None


def has_open_after_sales_case(order_id):
    for c in store.after_sales_cases.values():
        if c["order_id"] != order_id:
            continue
        if c["status"] not in ("RESOLVED_REFUND_ONLY", "RESOLVED_RETURN_REFUND",
                                "RESOLVED_PARTIAL_COMPENSATION", "REJECTED"):
            return True
    return False
