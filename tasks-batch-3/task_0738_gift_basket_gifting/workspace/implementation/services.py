"""Business logic: calculations, state transitions, cascades."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import db
from errors import (
    APIError,
    raise_err,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_RECIPIENT_NOT_FOUND,
    ERR_TEMPLATE_NOT_FOUND,
    ERR_BRANDING_PROFILE_NOT_FOUND,
    ERR_SKU_NOT_FOUND,
    ERR_FULFILLMENT_REF_NOT_FOUND,
    ERR_SUBRESOURCE_NOT_FOUND,
    ERR_INVALID_ORDER_STATE,
    ERR_INVALID_DECISION_STATE,
    ERR_INVALID_FULFILLMENT_STATE,
    ERR_ORDER_ALREADY_TERMINAL,
    ERR_INVALID_SERIES_STATE,
    ERR_PERISHABLE_SAFETY_VIOLATION,
    ERR_INSUFFICIENT_INVENTORY_CHRONOLOGICAL,
    ERR_BRANDING_PROFILE_NOT_APPROVED,
    ERR_MESSAGE_PROOF_NOT_LOCKED,
    ERR_SELF_APPROVAL_FORBIDDEN,
    ERR_SELF_PROOF_APPROVAL_FORBIDDEN,
    ERR_EMPTY_RECIPIENT_LIST,
    ERR_IMPORT_BATCH_ALL_ROWS_REJECTED,
    ERR_DUPLICATE_RECIPIENT_EMAIL,
    ERR_INSUFFICIENT_INVENTORY_FORWARD,
    ERR_ASSEMBLY_CAPACITY_EXCEEDED,
    ERR_SCHEDULED_SEND_IN_PAST,
    ERR_SHIPPING_BLACKOUT_CONFLICT,
    ERR_BUDGET_EXCEEDED,
    ERR_STALE_VERSION,
)


# ------- Constants (from calculations block) -------
BRANDING_SURCHARGE_CENTS = 150
RUSH_WINDOW_DAYS = 3
RUSH_FEE_CENTS = 2500
TIER_1_THRESHOLD_UNITS = 25
TIER_2_THRESHOLD_UNITS = 100
TIER_3_THRESHOLD_UNITS = 500
GOLD_THRESHOLD_CENTS = 1000000
SILVER_THRESHOLD_CENTS = 250000
TEMPLATE_BASE_WEIGHT_KG = Decimal("1.2")


def round_half_up_int(value) -> int:
    """Round Decimal (or numeric) half-up to nearest integer cent."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------- Existence lookups -------

def get_account_or_404(aid: str):
    acc = db.corporate_accounts.get(aid)
    if not acc:
        raise_err(ERR_ACCOUNT_NOT_FOUND)
    return acc


def get_order_or_404(oid: str):
    o = db.corporate_orders.get(oid)
    if not o:
        raise_err(ERR_ORDER_NOT_FOUND)
    return o


def get_recipient_or_404(rid: str):
    r = db.recipients.get(rid)
    if not r:
        raise_err(ERR_RECIPIENT_NOT_FOUND)
    return r


def get_template_or_404_active_required(tid: str):
    """For POST /corporate-accounts/{id}/orders and recurring-series; must be active."""
    t = db.gift_basket_templates.get(tid)
    if not t or not t.get("active", True):
        raise_err(ERR_TEMPLATE_NOT_FOUND)
    return t


def get_branding_or_404(bpid: str, account_id: str = None):
    bp = db.branding_profiles.get(bpid)
    if not bp:
        raise_err(ERR_BRANDING_PROFILE_NOT_FOUND)
    if account_id and bp.get("corporate_account_id") != account_id:
        raise_err(ERR_BRANDING_PROFILE_NOT_FOUND)
    return bp


def get_sku_or_404(sid: str):
    s = db.component_skus.get(sid)
    if not s:
        raise_err(ERR_SKU_NOT_FOUND)
    return s


# ------- Serialization helpers -------

def _copy(d: dict) -> dict:
    return {k: v for k, v in d.items()}


# ------- Component availability calculations -------

def component_available_qty_forward_looking(sku_id: str, projection_dt) -> int:
    """
    Forward-looking variant: on_hand_qty minus reserved_qty of RESERVED/ALLOCATED
    reservations whose expires_at is null or after projection_dt.
    """
    sku = db.component_skus[sku_id]
    on_hand = sku.get("on_hand_qty", 0)
    competing = 0
    for r in db.inventory_reservations.values():
        if r["sku_id"] != sku_id:
            continue
        if r["status"] not in ("RESERVED", "ALLOCATED"):
            continue
        expires_at = r.get("expires_at")
        if expires_at is not None:
            exp_dt = db.parse_iso(expires_at)
            if exp_dt <= projection_dt:
                continue
        competing += r["reserved_qty"]
    return on_hand - competing


def check_chronological_availability_for_order(order):
    """
    Chronological variant, evaluated per reservation being moved to ALLOCATED
    (for this order). For each SKU used by this order, process ALL RESERVED/ALLOCATED
    reservations for that SKU in created_at ASC order, accumulate reserved_qty,
    and verify every reservation of this order does not exceed sku.on_hand_qty.
    """
    # Group reservations for this order by sku.
    order_reservations = _order_reservations(order["id"])
    order_reservation_ids = {r["id"] for r in order_reservations}
    # For each sku touched, run the cumulative check.
    skus_used = {r["sku_id"] for r in order_reservations}
    for sku_id in skus_used:
        sku = db.component_skus[sku_id]
        on_hand = sku.get("on_hand_qty", 0)
        # Gather all RESERVED/ALLOCATED reservations for this SKU sorted by created_at ASC.
        all_res = [
            r for r in db.inventory_reservations.values()
            if r["sku_id"] == sku_id and r["status"] in ("RESERVED", "ALLOCATED")
        ]
        all_res.sort(key=lambda r: r["created_at"])
        cumulative = 0
        for r in all_res:
            cumulative += r["reserved_qty"]
            if r["id"] in order_reservation_ids:
                if cumulative > on_hand:
                    raise_err(ERR_INSUFFICIENT_INVENTORY_CHRONOLOGICAL)


def _order_reservations(order_id: str):
    """Return all inventory reservations tied (via recipient) to this order."""
    out = []
    for res in db.inventory_reservations.values():
        recipient = db.recipients.get(res["recipient_id"])
        if not recipient:
            continue
        if recipient.get("corporate_order_id") == order_id:
            out.append(res)
    return out


def _order_recipients(order_id: str, only_accepted: bool = True):
    out = []
    for r in db.recipients.values():
        if r.get("corporate_order_id") != order_id:
            continue
        if only_accepted and r.get("import_row_status") != "ACCEPTED":
            continue
        out.append(r)
    return out


# ------- Pricing -------

def _bulk_pricing(order, template, branding_profile) -> dict:
    """
    Runs the order_total_cost calc. Returns
      { subtotal_cents, discounted_subtotal_cents, rush_fee_cents, tier, total_units }
    where discounted_subtotal_cents is already rounded once.
    (Loyalty discount is applied by budget_utilization_and_approval_trigger.)
    """
    per_unit_price = template["base_price_cents"]
    if order.get("branding_profile_id"):
        per_unit_price += BRANDING_SURCHARGE_CENTS

    accepted = _order_recipients(order["id"], only_accepted=True)
    total_units = sum(r["quantity"] for r in accepted)

    subtotal_cents = per_unit_price * total_units
    if total_units >= TIER_3_THRESHOLD_UNITS:
        tier = "TIER_3"
        discount_pct = Decimal("0.15")
    elif total_units >= TIER_2_THRESHOLD_UNITS:
        tier = "TIER_2"
        discount_pct = Decimal("0.10")
    elif total_units >= TIER_1_THRESHOLD_UNITS:
        tier = "TIER_1"
        discount_pct = Decimal("0.05")
    else:
        tier = "TIER_0"
        discount_pct = Decimal("0.00")
    # Round once on discounted subtotal.
    discounted_subtotal_cents = round_half_up_int(
        Decimal(subtotal_cents) * (Decimal("1") - discount_pct)
    )

    rush_fee_cents = 0
    if (
        order.get("scheduled_send_date") is not None
        and tier == "TIER_0"
    ):
        sched = db.parse_iso(order["scheduled_send_date"])
        now = db.clock_now()
        if (sched - now) <= timedelta(days=RUSH_WINDOW_DAYS):
            rush_fee_cents = RUSH_FEE_CENTS

    return {
        "subtotal_cents": subtotal_cents,
        "discounted_subtotal_cents": discounted_subtotal_cents,
        "rush_fee_cents": rush_fee_cents,
        "tier": tier,
        "total_units": total_units,
    }


def _budget_utilization(order, account, pricing) -> dict:
    """
    Compute loyalty tier from account's remaining_budget, then apply loyalty discount
    to discounted_subtotal_cents. Add rush fee unrounded.
    """
    remaining_budget = account["monthly_budget_cents"] - account["ytd_spend_cents"]
    if remaining_budget >= GOLD_THRESHOLD_CENTS:
        loyalty_pct = Decimal("0.03")
    elif remaining_budget >= SILVER_THRESHOLD_CENTS:
        loyalty_pct = Decimal("0.01")
    else:
        loyalty_pct = Decimal("0.00")
    loyalty_applied = round_half_up_int(
        Decimal(pricing["discounted_subtotal_cents"]) * (Decimal("1") - loyalty_pct)
    )
    total_cost_cents = loyalty_applied + pricing["rush_fee_cents"]
    return {
        "total_cost_cents": total_cost_cents,
        "requires_approval": total_cost_cents > account["approval_threshold_cents"],
    }


def compute_order_pricing(order, account) -> dict:
    """
    PURE: returns { subtotal_cents, total_cost_cents, requires_approval, pricing, util }
    Does NOT mutate the order. Callers apply via apply_order_pricing().
    """
    template = db.gift_basket_templates[order["template_id"]]
    branding = None
    if order.get("branding_profile_id"):
        branding = db.branding_profiles[order["branding_profile_id"]]
    pricing = _bulk_pricing(order, template, branding)
    util = _budget_utilization(order, account, pricing)
    return {
        "subtotal_cents": pricing["subtotal_cents"],
        "total_cost_cents": util["total_cost_cents"],
        "requires_approval": util["requires_approval"],
        "pricing": pricing,
        "util": util,
    }


def apply_order_pricing(order, computed):
    order["subtotal_cents"] = computed["subtotal_cents"]
    order["total_cost_cents"] = computed["total_cost_cents"]
    order["requires_approval"] = computed["requires_approval"]


# ------- Perishable safety check -------

def check_perishable_safety(order, scheduled_dt):
    """
    Every ComponentSKU used by the order's basket composition must have remaining
    shelf life (sku.created_at + sku.shelf_life_days) that is not expired before
    the scheduled assembly day.
    """
    template = db.gift_basket_templates[order["template_id"]]
    for comp in template.get("components", []):
        sku = db.component_skus[comp["sku_id"]]
        if not sku.get("is_perishable"):
            continue
        sku_created = db.parse_iso(sku["created_at"])
        expiry = sku_created + timedelta(days=sku["shelf_life_days"])
        if expiry < scheduled_dt:
            raise_err(ERR_PERISHABLE_SAFETY_VIOLATION)


def check_assembly_capacity(station_id: str, scheduled_dt, order_id: str, add_qty: int):
    """
    sum(AssemblyTask.quantity where station_id == station_id AND scheduled_date == body.scheduled_date)
    across ALL orders + this order's total recipient quantity <= AssemblyStation.daily_capacity.
    """
    station = db.assembly_stations[station_id]
    # Compare by calendar date (Y-M-D of UTC), matching "same calendar day".
    target_day = scheduled_dt.date()
    existing = 0
    for t in db.assembly_tasks.values():
        if t.get("station_id") != station_id:
            continue
        try:
            sd = db.parse_iso(t["scheduled_date"]).date()
        except Exception:
            continue
        if sd == target_day and t.get("status") in ("QUEUED", "IN_PROGRESS", "COMPLETE"):
            existing += t.get("quantity", 0)
    if existing + add_qty > station["daily_capacity"]:
        raise_err(ERR_ASSEMBLY_CAPACITY_EXCEEDED)


# ------- Cascade: budget-decision APPROVE side effects -------

def do_approve_cascade(order, account, approver_user_id, station_id, scheduled_dt,
                       scheduled_date_raw=None):
    """
    Execute the APPROVED transition side effects atomically.
    Preconditions must have been validated already.
    scheduled_date_raw is the verbatim ISO string supplied by the caller so it can
    be recorded as-supplied on the created AssemblyTask rows (PRD §3.6: "carrying
    the station_id and scheduled_date supplied on the approval call").
    """
    # Final variant recompute using current versions (which are the pin moment).
    computed = compute_order_pricing(order, account)
    apply_order_pricing(order, computed)
    # Pin locked versions.
    template = db.gift_basket_templates[order["template_id"]]
    order["locked_template_version"] = template["version"]
    if order.get("branding_profile_id"):
        order["locked_branding_version"] = db.branding_profiles[order["branding_profile_id"]]["version"]
    else:
        order["locked_branding_version"] = None
    # BudgetApproval side effects.
    ba = _find_budget_approval(order["id"])
    if ba is not None:
        ba["decision"] = "APPROVED"
        ba["approver_user_id"] = approver_user_id
        ba["decided_at"] = db.now_iso()
        db.touch_common_fields(ba, is_create=False)
    # ytd_spend forward leg.
    account["ytd_spend_cents"] += order["total_cost_cents"]
    db.touch_common_fields(account, is_create=False)
    # Order approval state.
    order["approval_status"] = "APPROVED"
    # Cascade A hop 1: reservations RESERVED -> ALLOCATED.
    for res in _order_reservations(order["id"]):
        if res["status"] == "RESERVED":
            res["status"] = "ALLOCATED"
            db.touch_common_fields(res, is_create=False)
    # Cascade A hop 2: create one AssemblyTask per Recipient.
    # Store scheduled_date verbatim from the approval call (fall back to canonical
    # formatting if no raw string was passed).
    scheduled_iso = scheduled_date_raw if scheduled_date_raw is not None else db.format_iso(scheduled_dt)
    for r in _order_recipients(order["id"], only_accepted=True):
        tid = db.new_id()
        task = {
            "id": tid,
            "recipient_id": r["id"],
            "station_id": station_id,
            "scheduled_date": scheduled_iso,
            "quantity": r["quantity"],
            "status": "QUEUED",
        }
        db.touch_common_fields(task, is_create=True)
        db.assembly_tasks[tid] = task
    # Cascade A hop 3: production_status DRAFT -> ASSEMBLING.
    order["production_status"] = "ASSEMBLING"
    db.touch_common_fields(order, is_create=False)


def _find_budget_approval(order_id: str):
    for ba in db.budget_approvals.values():
        if ba["corporate_order_id"] == order_id:
            return ba
    return None


# ------- Order cancel -------

def cancel_order(order):
    """Cancel order and fire compensations (Rule 9 x2)."""
    was_approved = (order["approval_status"] == "APPROVED")
    # Compensation 1: RESERVED/ALLOCATED -> RELEASED.
    for res in _order_reservations(order["id"]):
        if res["status"] in ("RESERVED", "ALLOCATED"):
            res["status"] = "RELEASED"
            db.touch_common_fields(res, is_create=False)
    # Compensation 2: reverse leg of ytd_spend if it was approved.
    if was_approved:
        account = db.corporate_accounts[order["corporate_account_id"]]
        account["ytd_spend_cents"] -= order["total_cost_cents"]
        db.touch_common_fields(account, is_create=False)
    # AssemblyTasks QUEUED/IN_PROGRESS -> FAILED.
    for t in db.assembly_tasks.values():
        recipient = db.recipients.get(t["recipient_id"])
        if not recipient:
            continue
        if recipient.get("corporate_order_id") != order["id"]:
            continue
        if t["status"] in ("QUEUED", "IN_PROGRESS"):
            t["status"] = "FAILED"
            db.touch_common_fields(t, is_create=False)
    order["production_status"] = "CANCELLED"
    db.touch_common_fields(order, is_create=False)


# ------- Sweeps: perishable reservation expiry + recurring-series generation -------

def sweep_after_clock_advance():
    """
    On POST /_clock/set_current_utc:
      - RESERVED with expires_at <= now -> EXPIRED
      - active RecurringOrderSeries with next_run_date <= now -> clone new DRAFT order
    """
    now = db.clock_now()
    for res in list(db.inventory_reservations.values()):
        if res["status"] != "RESERVED":
            continue
        exp = res.get("expires_at")
        if exp is None:
            continue
        exp_dt = db.parse_iso(exp)
        if exp_dt <= now:
            res["status"] = "EXPIRED"
            db.touch_common_fields(res, is_create=False)
    # Recurring series
    for s in list(db.recurring_series.values()):
        if not s.get("active"):
            continue
        # Loop in case one clock jump crosses multiple intervals.
        while s.get("active") and db.parse_iso(s["next_run_date"]) <= now:
            src = db.corporate_orders.get(s["source_order_id"])
            if not src:
                # Source removed — bail out to avoid loop.
                break
            new_order = _clone_order_from_source(src)
            s["last_generated_order_id"] = new_order["id"]
            next_dt = db.parse_iso(s["next_run_date"]) + timedelta(days=s["interval_days"])
            s["next_run_date"] = db.format_iso(next_dt)
            db.touch_common_fields(s, is_create=False)


def _clone_order_from_source(src) -> dict:
    """Clone template_id/branding_profile_id/occasion, DRAFT, no recipients."""
    oid = db.new_id()
    o = {
        "id": oid,
        "corporate_account_id": src["corporate_account_id"],
        "template_id": src["template_id"],
        "branding_profile_id": src.get("branding_profile_id"),
        "occasion": src["occasion"],
        "scheduled_send_date": None,
        "approval_status": "DRAFT",
        "production_status": "DRAFT",
        "locked_template_version": None,
        "locked_branding_version": None,
        "subtotal_cents": 0,
        "total_cost_cents": 0,
        "requires_approval": False,
    }
    db.touch_common_fields(o, is_create=True)
    db.corporate_orders[oid] = o
    return o


# ------- Cascade B / order.production_status auto-advances -------

def maybe_advance_after_assembly_task_change(task):
    """
    Called after an AssemblyTask changes to COMPLETE.
    - If all AssemblyTasks for that order are COMPLETE and order.production_status == ASSEMBLING,
      advance to READY_TO_SHIP; then Cascade B hop 2: reservations ALLOCATED -> ASSEMBLED.
    """
    recipient = db.recipients.get(task["recipient_id"])
    if not recipient:
        return
    order = db.corporate_orders.get(recipient["corporate_order_id"])
    if not order:
        return
    if order["production_status"] != "ASSEMBLING":
        return
    tasks = [
        t for t in db.assembly_tasks.values()
        if db.recipients.get(t["recipient_id"], {}).get("corporate_order_id") == order["id"]
    ]
    if not tasks:
        return
    if all(t["status"] == "COMPLETE" for t in tasks):
        order["production_status"] = "READY_TO_SHIP"
        db.touch_common_fields(order, is_create=False)
        # Cascade B hop 2
        for res in _order_reservations(order["id"]):
            if res["status"] == "ALLOCATED":
                res["status"] = "ASSEMBLED"
                db.touch_common_fields(res, is_create=False)


def maybe_advance_after_shipment_change(shipment):
    """
    After a shipment transitions, possibly advance order.production_status:
      READY_TO_SHIP -> SHIPPED when every shipment for the order is IN_TRANSIT/DELIVERED
      SHIPPED -> COMPLETED when every shipment for the order is DELIVERED
      On COMPLETED, ASSEMBLED reservations become RELEASED.
    """
    recipient = db.recipients.get(shipment["recipient_id"])
    if not recipient:
        return
    order = db.corporate_orders.get(recipient["corporate_order_id"])
    if not order:
        return
    order_shipments = [
        s for s in db.shipments.values()
        if db.recipients.get(s["recipient_id"], {}).get("corporate_order_id") == order["id"]
    ]
    if not order_shipments:
        return
    if order["production_status"] == "READY_TO_SHIP":
        if all(s["status"] in ("IN_TRANSIT", "DELIVERED") for s in order_shipments):
            order["production_status"] = "SHIPPED"
            db.touch_common_fields(order, is_create=False)
    if order["production_status"] == "SHIPPED":
        if all(s["status"] == "DELIVERED" for s in order_shipments):
            order["production_status"] = "COMPLETED"
            db.touch_common_fields(order, is_create=False)
            # RESERVED->RELEASED for still-ASSEMBLED reservations.
            for res in _order_reservations(order["id"]):
                if res["status"] == "ASSEMBLED":
                    res["status"] = "RELEASED"
                    db.touch_common_fields(res, is_create=False)
