"""Domain services: business logic, calculations, and state transitions."""
from decimal import Decimal, ROUND_HALF_UP

from db import (
    STORE, new_id, iso_from_datetime, parse_iso, add_days, add_hours,
)
from errors import ApiError


# =====================================================================
# Common field helpers
# =====================================================================

def _stamp_create(entity: dict, common: bool = True):
    now_iso = STORE.now_iso()
    entity["created_at"] = now_iso
    if common:
        entity["updated_at"] = now_iso
        entity["version"] = 1


def _touch(entity: dict):
    entity["updated_at"] = STORE.now_iso()
    entity["version"] = int(entity.get("version", 0)) + 1


# =====================================================================
# Serialization (public dict shapes)
# =====================================================================

def _base_common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _base_lite(e):
    return {"id": e["id"], "created_at": e["created_at"]}


def serialize_plan(p):
    out = _base_common(p)
    out.update({
        "tier": p["tier"],
        "billing_type": p["billing_type"],
        "base_fee_cents": p["base_fee_cents"],
        "per_employee_fee_cents": p["per_employee_fee_cents"],
        "flat_fee_cents": p["flat_fee_cents"],
        "volume_discount_threshold_headcount": p["volume_discount_threshold_headcount"],
        "volume_discount_pct": p["volume_discount_pct"],
    })
    return out


def serialize_product(p):
    out = _base_common(p)
    out.update({
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "dietary_flags": list(p["dietary_flags"]),
        "unit_cost_cents": p["unit_cost_cents"],
        "requires_refrigeration": p["requires_refrigeration"],
    })
    return out


def serialize_client(c):
    out = _base_common(c)
    out.update({
        "name": c["name"],
        "headcount": c["headcount"],
        "credit_balance_cents": c["credit_balance_cents"],
        "active_subscription_id": c["active_subscription_id"],
    })
    return out


def serialize_location(l):
    out = _base_common(l)
    out.update({
        "client_id": l["client_id"],
        "name": l["name"],
        "kind": l["kind"],
        "capacity_units": l["capacity_units"],
        "service_fee_bps": l["service_fee_bps"],
    })
    return out


def serialize_preference(pref):
    out = _base_lite(pref)
    out.update({
        "client_id": pref["client_id"],
        "dietary_flag": pref["dietary_flag"],
    })
    return out


def serialize_par_level(pl):
    out = _base_common(pl)
    out.update({
        "location_id": pl["location_id"],
        "product_id": pl["product_id"],
        "par_units": pl["par_units"],
    })
    return out


def serialize_subscription(s):
    out = _base_common(s)
    out.update({
        "client_id": s["client_id"],
        "plan_id": s["plan_id"],
        "plan_version_snapshot": s["plan_version_snapshot"],
        "status": s["status"],
        "paused_at": s["paused_at"],
        "cancelled_at": s["cancelled_at"],
        "cumulative_active_days": s["cumulative_active_days"],
    })
    return out


def serialize_rotation_cycle(rc):
    out = _base_common(rc)
    out.update({
        "subscription_id": rc["subscription_id"],
        "cycle_index": rc["cycle_index"],
        "effective_from": rc["effective_from"],
        "effective_to": rc["effective_to"],
        "status": rc["status"],
    })
    return out


def serialize_delivery(d):
    out = _base_common(d)
    out.update({
        "location_id": d["location_id"],
        "rotation_cycle_id": d["rotation_cycle_id"],
        "scheduled_at": d["scheduled_at"],
        "dispatched_at": d["dispatched_at"],
        "delivered_at": d["delivered_at"],
        "status": d["status"],
        "dispute_reason": d["dispute_reason"],
        "provisional_cents": d["provisional_cents"],
        "final_cents": d["final_cents"],
        "dispute_credit_cents": d["dispute_credit_cents"],
    })
    return out


def serialize_delivery_line(dl):
    out = _base_common(dl)
    out.update({
        "delivery_id": dl["delivery_id"],
        "product_id": dl["product_id"],
        "planned_units": dl["planned_units"],
        "actual_units": dl["actual_units"],
        "unit_price_cents_snapshot": dl["unit_price_cents_snapshot"],
        "service_fee_bps_snapshot": dl["service_fee_bps_snapshot"],
    })
    return out


def serialize_invoice(inv):
    out = _base_common(inv)
    out.update({
        "client_id": inv["client_id"],
        "rotation_cycle_id": inv["rotation_cycle_id"],
        "period_start": inv["period_start"],
        "period_end": inv["period_end"],
        "subscription_fee_cents": inv["subscription_fee_cents"],
        "consumption_cents": inv["consumption_cents"],
        "credit_applied_cents": inv["credit_applied_cents"],
        "total_cents": inv["total_cents"],
        "payment_status": inv["payment_status"],
        "dispute_status": inv["dispute_status"],
    })
    return out


def serialize_feedback(f):
    out = _base_lite(f)
    out.update({
        "client_id": f["client_id"],
        "product_id": f["product_id"],
        "rating": f["rating"],
        "comment": f["comment"],
        "swap_suggestion_product_id": f["swap_suggestion_product_id"],
    })
    return out


# =====================================================================
# Rounding helpers
# =====================================================================

def round_half_up_int(x) -> int:
    """Round a numeric value to integer cents using ROUND_HALF_UP."""
    d = Decimal(str(x)) if not isinstance(x, Decimal) else x
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(x) -> Decimal:
    d = Decimal(str(x)) if not isinstance(x, Decimal) else x
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# =====================================================================
# Existence lookups
# =====================================================================

def get_client_or_404(client_id):
    c = STORE.clients.get(client_id)
    if not c:
        raise ApiError("ERR_CLIENT_NOT_FOUND", 404, "Client not found")
    return c


def get_location_or_404(loc_id):
    l = STORE.locations.get(loc_id)
    if not l:
        raise ApiError("ERR_LOCATION_NOT_FOUND", 404, "Location not found")
    return l


def get_subscription_or_404(sid):
    s = STORE.subscriptions.get(sid)
    if not s:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    return s


def get_delivery_or_404(did):
    d = STORE.deliveries.get(did)
    if not d:
        raise ApiError("ERR_DELIVERY_NOT_FOUND", 404, "Delivery not found")
    return d


def get_rotation_or_404(rid):
    rc = STORE.rotation_cycles.get(rid)
    if not rc:
        raise ApiError("ERR_ROTATION_CYCLE_NOT_FOUND", 404, "RotationCycle not found")
    return rc


def get_invoice_or_404(iid):
    inv = STORE.invoices.get(iid)
    if not inv:
        raise ApiError("ERR_INVOICE_NOT_FOUND", 404, "Invoice not found")
    return inv


def get_product_or_404(pid):
    p = STORE.products.get(pid)
    if not p:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "Product not found")
    return p


def get_plan_or_404(pid):
    p = STORE.plans.get(pid)
    if not p:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404, "Plan not found")
    return p


def get_delivery_line_or_404(lid):
    dl = STORE.delivery_lines.get(lid)
    if not dl:
        raise ApiError("ERR_DELIVERY_LINE_NOT_FOUND", 404, "DeliveryLine not found")
    return dl


def get_feedback_or_404(fid):
    f = STORE.feedback.get(fid)
    if not f:
        raise ApiError("ERR_FEEDBACK_NOT_FOUND", 404, "Feedback not found")
    return f


def get_par_level_or_404(pl_id):
    pl = STORE.par_levels.get(pl_id)
    if not pl:
        raise ApiError("ERR_PAR_LEVEL_NOT_FOUND", 404, "ParLevel not found")
    return pl


# =====================================================================
# Ownership checks
# =====================================================================

def check_client_ownership(role, uid, client):
    if role == "ClientAdmin" and uid != client["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "ClientAdmin does not own this client")


def check_location_ownership(role, uid, location):
    if role == "LocationManager" and uid != location["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "LocationManager does not own this location")
    if role == "ClientAdmin" and uid != location["client_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "ClientAdmin does not own this location's client")


def check_subscription_ownership(role, uid, sub):
    if role == "ClientAdmin" and uid != sub["client_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "ClientAdmin does not own this subscription")


def check_delivery_ownership(role, uid, delivery):
    if role == "LocationManager" and uid != delivery["location_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "LocationManager does not own this delivery")
    if role == "ClientAdmin":
        loc = STORE.locations.get(delivery["location_id"])
        if not loc or uid != loc["client_id"]:
            raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "ClientAdmin does not own this delivery")


def check_invoice_ownership(role, uid, invoice):
    if role == "ClientAdmin" and uid != invoice["client_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "ClientAdmin does not own this invoice")


def check_rotation_ownership(role, uid, rc):
    if role == "ClientAdmin":
        sub = STORE.subscriptions.get(rc["subscription_id"])
        if not sub or uid != sub["client_id"]:
            raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "ClientAdmin does not own this rotation cycle")


def check_delivery_line_ownership(role, uid, dl):
    d = STORE.deliveries.get(dl["delivery_id"])
    if not d:
        return
    check_delivery_ownership(role, uid, d)


# =====================================================================
# Calculations
# =====================================================================

BULK_UNITS_THRESHOLD = 100
BULK_LINE_DISCOUNT_PCT = Decimal("0.05")


def _line_charge(units, unit_price, service_fee_bps, location_kind):
    raw = Decimal(units) * Decimal(unit_price)
    if location_kind == "MICRO_MARKET":
        fee = round_half_up_int(raw * Decimal(service_fee_bps) / Decimal(10000))
    else:
        fee = 0
    if units >= BULK_UNITS_THRESHOLD:
        discount = round_half_up_int(raw * BULK_LINE_DISCOUNT_PCT)
    else:
        discount = 0
    return int(raw) + fee - discount


def compute_provisional_cents(delivery):
    loc = STORE.locations[delivery["location_id"]]
    lines = [dl for dl in STORE.delivery_lines.values() if dl["delivery_id"] == delivery["id"]]
    total = 0
    for dl in lines:
        total += _line_charge(
            dl["planned_units"],
            dl["unit_price_cents_snapshot"],
            dl["service_fee_bps_snapshot"],
            loc["kind"],
        )
    return total


def compute_final_cents(delivery):
    loc = STORE.locations[delivery["location_id"]]
    lines = [dl for dl in STORE.delivery_lines.values() if dl["delivery_id"] == delivery["id"]]
    total = 0
    for dl in lines:
        actual = dl["actual_units"] if dl["actual_units"] is not None else dl["planned_units"]
        total += _line_charge(
            actual,
            dl["unit_price_cents_snapshot"],
            dl["service_fee_bps_snapshot"],
            loc["kind"],
        )
    return total


def compute_dispute_credit_cents(delivery):
    lines = [dl for dl in STORE.delivery_lines.values() if dl["delivery_id"] == delivery["id"]]
    total = 0
    for dl in lines:
        actual = dl["actual_units"] if dl["actual_units"] is not None else dl["planned_units"]
        if actual < dl["planned_units"]:
            total += (dl["planned_units"] - actual) * dl["unit_price_cents_snapshot"]
    return total


def compute_subscription_fee_cents(plan, headcount):
    if plan["billing_type"] == "FLAT":
        return int(plan["flat_fee_cents"])
    # PER_EMPLOYEE
    raw = Decimal(plan["per_employee_fee_cents"]) * Decimal(headcount)
    if headcount >= int(plan["volume_discount_threshold_headcount"]):
        discounted = raw * (Decimal(1) - Decimal(str(plan["volume_discount_pct"])))
        discounted_rounded = round_half_up_int(discounted)
    else:
        discounted_rounded = int(raw)
    return int(plan["base_fee_cents"]) + discounted_rounded


def compute_invoice_consumption_cents(rotation_cycle_id):
    total = 0
    for d in STORE.deliveries.values():
        if d["rotation_cycle_id"] == rotation_cycle_id and d["status"] == "FINALIZED":
            total += int(d["final_cents"])
    return total


# =====================================================================
# Cascade helpers
# =====================================================================

def cancel_delivery_scheduled(delivery):
    """SCHEDULED -> CANCELLED (system cascade). No client credit."""
    delivery["status"] = "CANCELLED"
    _touch(delivery)


def cancel_delivery_en_route(delivery):
    """EN_ROUTE -> CANCELLED (system cascade). Credits client."""
    delivery["dispute_credit_cents"] = int(delivery["provisional_cents"])
    client = STORE.clients[STORE.locations[delivery["location_id"]]["client_id"]]
    client["credit_balance_cents"] = int(client["credit_balance_cents"]) + int(delivery["dispute_credit_cents"])
    _touch(client)
    delivery["status"] = "CANCELLED"
    _touch(delivery)


def invalidate_rotation_cycle(rc):
    """OPEN -> INVALIDATED cascade. Called when subscription pauses or cancels-from-ACTIVE."""
    if rc["status"] != "OPEN":
        return
    rc["status"] = "INVALIDATED"
    _touch(rc)
    # Hop 3: cascade to deliveries under this cycle
    for d in list(STORE.deliveries.values()):
        if d["rotation_cycle_id"] == rc["id"]:
            if d["status"] == "SCHEDULED":
                cancel_delivery_scheduled(d)
            elif d["status"] == "EN_ROUTE":
                cancel_delivery_en_route(d)
    # Parallel fan-out: also flip any invoice under same subscription
    # whose dispute_status is CLEAN and payment_status is UNPAID.
    sub_id = rc["subscription_id"]
    sub = STORE.subscriptions.get(sub_id)
    if sub:
        for inv in STORE.invoices.values():
            if inv["client_id"] == sub["client_id"] and inv["dispute_status"] == "CLEAN" and inv["payment_status"] == "UNPAID":
                inv["dispute_status"] = "UNDER_DISPUTE"
                _touch(inv)


# =====================================================================
# Assortment / par-projection helpers
# =====================================================================

def location_par_levels(location_id):
    return [pl for pl in STORE.par_levels.values() if pl["location_id"] == location_id]


def client_preference_flags(client_id):
    return {p["dietary_flag"] for p in STORE.preferences.values() if p["client_id"] == client_id}


def project_assortment(location):
    """Return list of ParLevel dicts, filtered by client preferences and refrigeration,
    sorted by par_units DESC then created_at ASC."""
    client_id = location["client_id"]
    blocked_flags = client_preference_flags(client_id)
    pars = location_par_levels(location["id"])
    kept = []
    for pl in pars:
        prod = STORE.products.get(pl["product_id"])
        if not prod:
            continue
        if any(f in blocked_flags for f in prod["dietary_flags"]):
            continue
        if prod["requires_refrigeration"] and location["kind"] == "PANTRY":
            continue
        kept.append(pl)

    def sort_key(pl):
        # DESC on par_units, ASC on created_at (ISO strings sort lex)
        return (-pl["par_units"], pl["created_at"])

    kept.sort(key=sort_key)
    return kept


# =====================================================================
# Interval overlap for rotation cycles
# =====================================================================

def rotation_cycle_overlaps_existing(sub_id, new_from, new_to, exclude_ids=None):
    exclude_ids = exclude_ids or set()
    a = parse_iso(new_from)
    b = parse_iso(new_to)
    for rc in STORE.rotation_cycles.values():
        if rc["subscription_id"] != sub_id:
            continue
        if rc["id"] in exclude_ids:
            continue
        # INVALIDATED cycles are not resurrected and do not gate future windows —
        # per PRD §3.3: "The invalidated cycle is not resurrected; the new cycle is
        # a fresh window." CLOSED cycles similarly represent past terminal windows;
        # the overlap invariant guards against multiple live/pending cycles, not
        # against historically-terminated cycles' spans.
        if rc["status"] in ("INVALIDATED", "CLOSED"):
            continue
        c = parse_iso(rc["effective_from"])
        d = parse_iso(rc["effective_to"])
        # half-open overlap: a < d AND c < b
        if a < d and c < b:
            return True
    return False


# =====================================================================
# Pagination helper (from query args)
# =====================================================================

def pagination_params(args):
    from errors import ApiError

    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, total


def sort_by_created_at_asc(items):
    return sorted(items, key=lambda x: x["created_at"])
