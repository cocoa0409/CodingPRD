"""Business logic: calculations (PRD 2.6-2.10, 3.x), state-machine cascades,
the maintenance sweep, and the FEFO selector."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from store import DB, now, touch, new_event
from constants import (
    RBC_CLASS, PLASMA_CLASS, CLASS_SHELF_HOURS, THAWED_FFP_HOURS,
    THAWED_CRYO_HOURS, POOLED_PLT_HOURS, PRICE_CENTS, TIER2_QTY, TIER1_QTY,
    DISCOUNT_TIER2, DISCOUNT_TIER1, EMERGENCY_SURCHARGE, XM_HOLD_HOURS,
    DEFAULT_MIN_SHELF_HOURS, INBOUND_HORIZON_HOURS, WASTAGE_WINDOW_DAYS,
    EXCESSIVE_RATE, RATE_SCALE, ABO_RBC_ALLOWED, ABO_PLASMA_ALLOWED,
    ALLOW_EMERGENCY_RH_MISMATCH, PACK_SPEC,
)


# ---------------------------------------------------------------------------
# Patient derived state
# ---------------------------------------------------------------------------

def patient_has_active_ts(patient_id):
    """True iff the patient holds a TypeAndScreen with status ACTIVE and
    server now < its expires_at (strict) — evaluated live (PRD 3.1)."""
    current = now()
    for ts in DB.type_and_screens.values():
        if (
            ts["patient_id"] == patient_id
            and ts["status"] == "ACTIVE"
            and current < ts["expires_at"]
        ):
            return True
    return False


def patient_active_ts(patient_id):
    """The patient's currently usable ACTIVE TypeAndScreen (latest validated)."""
    current = now()
    best = None
    for ts in DB.type_and_screens.values():
        if (
            ts["patient_id"] == patient_id
            and ts["status"] == "ACTIVE"
            and current < ts["expires_at"]
        ):
            if best is None or (ts["validated_at"], ts["_seq"]) > (best["validated_at"], best["_seq"]):
                best = ts
    return best


def patient_has_activated_mtp(patient_id):
    return any(
        m["patient_id"] == patient_id and m["status"] == "ACTIVATED"
        for m in DB.mtps.values()
    )


def any_mtp_activated():
    return any(m["status"] == "ACTIVATED" for m in DB.mtps.values())


# ---------------------------------------------------------------------------
# Demand buckets, posture ladders, wastage rate (PRD 2.10, 3.8)
# ---------------------------------------------------------------------------

def active_policy_for(product_type, abo_type, rh_type):
    for p in DB.policies.values():
        if (
            p["status"] == "ACTIVE"
            and p["product_type"] == product_type
            and p["abo_type"] == abo_type
            and p["rh_type"] == rh_type
        ):
            return p
    return None


def bucket_min_shelf_hours(product_type, abo_type, rh_type):
    policy = active_policy_for(product_type, abo_type, rh_type)
    if policy is not None:
        return policy["min_shelf_life_hours"]
    return DEFAULT_MIN_SHELF_HOURS


def bucket_usable_units(product_type, abo_type, rh_type):
    """Physical usable count: AVAILABLE units whose expires_at lies strictly
    beyond now + min_shelf_life_hours."""
    horizon = bucket_min_shelf_hours(product_type, abo_type, rh_type)
    cutoff = now() + timedelta(hours=horizon)
    count = 0
    for u in DB.units.values():
        if (
            u["product_type"] == product_type
            and u["abo_type"] == abo_type
            and u["rh_type"] == rh_type
            and u["status"] == "AVAILABLE"
            and u["expires_at"] > cutoff
        ):
            count += 1
    return count


def bucket_inbound_units_24h(product_type, abo_type, rh_type):
    """Undelivered remainders on SUBMITTED/ACKNOWLEDGED/RECEIVING orders whose
    expected_delivery_at is set and <= now + 24h."""
    horizon = now() + timedelta(hours=INBOUND_HORIZON_HOURS)
    total = 0
    for so in DB.supplier_orders.values():
        if so["status"] not in ("SUBMITTED", "ACKNOWLEDGED", "RECEIVING"):
            continue
        eta = so.get("expected_delivery_at")
        if eta is None or eta > horizon:
            continue
        received = {}
        for entry in so["received_summary"]:
            key = (entry["product_type"], entry["abo_type"], entry["rh_type"])
            received[key] = received.get(key, 0) + entry["received_qty"]
        for line in so["lines"]:
            if (line["product_type"], line["abo_type"], line["rh_type"]) == (
                product_type, abo_type, rh_type,
            ):
                key = (line["product_type"], line["abo_type"], line["rh_type"])
                total += max(0, line["quantity"] - received.get(key, 0))
    return total


def _posture_ladder(count, policy):
    """Inclusive boundary ladder: count <= critical -> CRITICAL, etc."""
    if count <= policy["critical_threshold"]:
        return "CRITICAL"
    if count <= policy["shortage_threshold"]:
        return "SHORTAGE"
    if count <= policy["watch_threshold"]:
        return "WATCH"
    return "NORMAL"


def physical_posture(product_type, abo_type, rh_type):
    policy = active_policy_for(product_type, abo_type, rh_type)
    if policy is None:
        return "NORMAL"
    return _posture_ladder(bucket_usable_units(product_type, abo_type, rh_type), policy)


def prospective_posture(product_type, abo_type, rh_type):
    policy = active_policy_for(product_type, abo_type, rh_type)
    if policy is None:
        return "NORMAL"
    total = bucket_usable_units(product_type, abo_type, rh_type) + bucket_inbound_units_24h(
        product_type, abo_type, rh_type
    )
    return _posture_ladder(total, policy)


def rolling_wastage(product_type, abo_type, rh_type, window_days=None):
    """Rolling wastage rate over [now - window, now], both ends inclusive.
    rate = round_half_up(wasted / received, 4); 0.0000 when received == 0.
    Returns (rate Decimal, wasted, received, excessive)."""
    days = WASTAGE_WINDOW_DAYS if window_days is None else window_days
    lo = now() - timedelta(days=days)
    hi = now()
    wasted = 0
    for w in DB.wastage.values():
        if (
            w["product_type"] == product_type
            and w["abo_type"] == abo_type
            and w["rh_type"] == rh_type
            and lo <= w["created_at"] <= hi
        ):
            wasted += w["quantity_units"]
    received = 0
    for u in DB.units.values():
        if (
            u["product_type"] == product_type
            and u["abo_type"] == abo_type
            and u["rh_type"] == rh_type
            and lo <= u["created_at"] <= hi
        ):
            received += 1
    if received == 0:
        rate = Decimal("0.0000")
    else:
        rate = (Decimal(wasted) / Decimal(received)).quantize(RATE_SCALE, rounding=ROUND_HALF_UP)
    return rate, wasted, received, rate >= EXCESSIVE_RATE


def bucket_excessive_wastage(product_type, abo_type, rh_type):
    return rolling_wastage(product_type, abo_type, rh_type)[3]


# ---------------------------------------------------------------------------
# calculations.supplier_order_estimated_cost — pinned rounding: round each
# line half-up first, sum, then one half-up rounding on the emergency total.
# ---------------------------------------------------------------------------

def estimate_cost_cents(lines, is_emergency):
    total_qty = sum(line["quantity"] for line in lines)
    if total_qty >= TIER2_QTY:
        discount = DISCOUNT_TIER2
    elif total_qty >= TIER1_QTY:
        discount = DISCOUNT_TIER1
    else:
        discount = Decimal("0")
    subtotal = 0
    for line in lines:
        line_cost = (
            Decimal(PRICE_CENTS[line["product_type"]]) * line["quantity"] * (Decimal("1") - discount)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        subtotal += int(line_cost)
    if is_emergency:
        return int(
            (Decimal(subtotal) * EMERGENCY_SURCHARGE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    return subtotal


# ---------------------------------------------------------------------------
# calculations.unit_expiration_at_receive
# ---------------------------------------------------------------------------

def unit_expiration(product_type, collected_at, thawed_at, pooled_at):
    base = collected_at + timedelta(hours=CLASS_SHELF_HOURS[product_type])
    derived = None
    if thawed_at is not None:
        hours = (
            THAWED_FFP_HOURS if product_type == "FFP"
            else THAWED_CRYO_HOURS if product_type == "CRYO"
            else 0
        )
        derived = thawed_at + timedelta(hours=hours)
    if pooled_at is not None:
        pooled_expiry = pooled_at + timedelta(hours=POOLED_PLT_HOURS)
        derived = pooled_expiry if derived is None else min(derived, pooled_expiry)
    return base if derived is None else min(base, derived)


# ---------------------------------------------------------------------------
# calculations.unit_compatibility_decision — the seven fixed steps.
# ctx keys: product_type, urgency, type_restriction, special_requirements.
# ---------------------------------------------------------------------------

def unit_compatible(unit, patient, ctx):
    product_type = ctx["product_type"]
    # Step 1: product class (unit must be of the ordered product type).
    if unit["product_type"] != product_type:
        return False
    rbc_class = product_type in RBC_CLASS
    patient_abo = patient["current_abo_type"]
    patient_rh = patient["current_rh_type"]

    # Step 2: untyped patient short-circuit (steps 3-4 skipped entirely).
    if patient_abo == "UNKNOWN":
        if rbc_class:
            if not (unit["abo_type"] == "O" and unit["rh_type"] == "NEG"):
                return False
        else:
            if unit["abo_type"] != "AB":
                return False
    else:
        # Step 3: ABO matrix for the product class.
        if rbc_class:
            if product_type == "WHOLE_BLOOD":
                if unit["abo_type"] != patient_abo:
                    return False
                if unit["rh_type"] != patient_rh:
                    # Step 5 relaxation evaluated against the strict rule.
                    if not (
                        ALLOW_EMERGENCY_RH_MISMATCH
                        and patient_rh == "NEG"
                        and unit["rh_type"] == "POS"
                        and ctx.get("urgency") == "EMERGENCY"
                    ):
                        return False
            else:  # RBC
                if unit["abo_type"] not in ABO_RBC_ALLOWED[patient_abo]:
                    return False
                # Step 5: Rh POS unit into Rh NEG patient only under EMERGENCY.
                if (
                    patient_rh == "NEG"
                    and unit["rh_type"] == "POS"
                    and not (
                        ALLOW_EMERGENCY_RH_MISMATCH and ctx.get("urgency") == "EMERGENCY"
                    )
                ):
                    return False
        else:
            if unit["abo_type"] not in ABO_PLASMA_ALLOWED[patient_abo]:
                return False
        # Step 4: order type restriction.
        restriction = ctx.get("type_restriction") or "NONE"
        if restriction == "O_ONLY" and unit["abo_type"] != "O":
            return False
        if restriction == "AB_ONLY" and unit["abo_type"] != "AB":
            return False

    # Step 6: antibody coverage — anti-X requires the unit tested X-negative.
    for antibody in patient.get("identified_antibodies") or []:
        antigen = antibody[len("anti-"):] if antibody.startswith("anti-") else antibody
        if antigen not in (unit.get("antigen_negative") or []):
            return False

    # Step 7: special handling requirements.
    for requirement in ctx.get("special_requirements") or []:
        if requirement == "IRRADIATED" and not unit["irradiated"]:
            return False
        if requirement == "CMV_NEGATIVE" and not unit["cmv_negative"]:
            return False
        if requirement == "WASHED" and not unit["washed"]:
            return False
    return True


# ---------------------------------------------------------------------------
# calculations.fefo_unit_selector — deterministic single winner:
# expires_at ASC, created_at ASC, unit_number ASC; id never consulted.
# ---------------------------------------------------------------------------

def fefo_candidates(product_type, abo_type, rh_type, patient, ctx, excluded_ids):
    horizon = bucket_min_shelf_hours(product_type, abo_type, rh_type)
    cutoff = now() + timedelta(hours=horizon)
    pool = []
    for u in DB.units.values():
        if u["id"] in excluded_ids:
            continue
        if u["status"] != "AVAILABLE":
            continue
        if u["product_type"] != product_type:
            continue
        if abo_type is not None and u["abo_type"] != abo_type:
            continue
        if rh_type is not None and u["rh_type"] != rh_type:
            continue
        if not (u["expires_at"] > cutoff):
            continue
        if not unit_compatible(u, patient, ctx):
            continue
        pool.append(u)
    pool.sort(key=lambda u: (u["expires_at"], u["created_at"], u["unit_number"]))
    return pool


def fefo_select(product_type, patient, ctx, abo_type=None, rh_type=None, excluded_ids=frozenset()):
    pool = fefo_candidates(product_type, abo_type, rh_type, patient, ctx, excluded_ids)
    return pool[0] if pool else None


# ---------------------------------------------------------------------------
# TransfusionOrder counter-driven state reconciliation (PRD 3.3).
# ---------------------------------------------------------------------------

def order_fulfillment(order):
    return order["units_crossmatched"] + order["units_issued_net"]


def on_xm_compatible_added(order):
    order["units_crossmatched"] += 1
    if order["status"] == "AWAITING_CROSSMATCH" and order_fulfillment(order) >= order["units_requested"]:
        order["status"] = "READY"
    touch(order)


def on_xm_released(order):
    """COMPATIBLE -> CANCELLED/EXPIRED. READY reverts when fulfillment falls
    short; PARTIALLY_ISSUED only reverts when units_issued_net also dropped
    (handled by on_issue_removed, not here)."""
    order["units_crossmatched"] -= 1
    if order["status"] == "READY" and order_fulfillment(order) < order["units_requested"]:
        order["status"] = "AWAITING_CROSSMATCH"
    touch(order)


def on_issue_added(order):
    order["units_issued_net"] += 1
    if order["status"] == "READY":
        order["status"] = "PARTIALLY_ISSUED"
    touch(order)


def on_issue_removed(order, issue=None):
    """Return/stop: units_issued_net decrements; a consumed crossmatch's slot
    is lost with the returned unit (the crossmatch is NOT revived), so
    units_crossmatched decrements too and fulfillment may drop below
    units_requested (PRD 3.2 unit ISSUED->AVAILABLE note, 3.5)."""
    order["units_issued_net"] -= 1
    if issue is not None and issue.get("_consumed_xm_id"):
        order["units_crossmatched"] = max(0, order["units_crossmatched"] - 1)
    if order["status"] == "PARTIALLY_ISSUED":
        if order_fulfillment(order) < order["units_requested"]:
            order["status"] = "AWAITING_CROSSMATCH"
        elif order["units_issued_net"] == 0:
            order["status"] = "READY"
    touch(order)


def on_transfusion_completed(order, patient):
    order["units_transfused"] += 1
    if (
        order["status"] in ("AWAITING_CROSSMATCH", "READY", "PARTIALLY_ISSUED")
        and order["units_transfused"] >= order["units_requested"]
    ):
        order["status"] = "COMPLETED"
    touch(order)
    patient["total_units_transfused"] += 1
    touch(patient)


# ---------------------------------------------------------------------------
# Crossmatch cancellation / expiry machinery (shared by cascades).
# ---------------------------------------------------------------------------

def cancel_crossmatch(xm, release_unit=True):
    """COMPATIBLE/PENDING -> CANCELLED. When the same cascade holds the unit,
    the hold wins and no release occurs (release_unit=False)."""
    if xm["status"] == "COMPATIBLE":
        xm["status"] = "CANCELLED"
        touch(xm)
        unit = DB.units.get(xm["unit_id"])
        if release_unit and unit is not None and unit["status"] == "RESERVED":
            unit["status"] = "AVAILABLE"
            touch(unit)
        on_xm_released(DB.orders[xm["order_id"]])
    elif xm["status"] == "PENDING":
        xm["status"] = "CANCELLED"
        touch(xm)


def expire_crossmatch(xm, release_unit=True):
    """COMPATIBLE -> EXPIRED (sweep or cascade)."""
    xm["status"] = "EXPIRED"
    touch(xm)
    unit = DB.units.get(xm["unit_id"])
    if release_unit and unit is not None and unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        touch(unit)
    on_xm_released(DB.orders[xm["order_id"]])


def compatible_xm_for_unit(unit_id):
    for xm in DB.crossmatches.values():
        if xm["unit_id"] == unit_id and xm["status"] == "COMPATIBLE":
            return xm
    return None


# ---------------------------------------------------------------------------
# Wastage log (append-only; PRD 2.5, 3.8)
# ---------------------------------------------------------------------------

def add_wastage(unit, reason, recorded_by, note=None):
    record = new_event({
        "unit_id": unit["id"],
        "product_type": unit["product_type"],
        "abo_type": unit["abo_type"],
        "rh_type": unit["rh_type"],
        "reason": reason,
        "quantity_units": 1,
        "recorded_by_user_id": recorded_by,
        "note": note,
    })
    DB.wastage[record["id"]] = record
    return record


# ---------------------------------------------------------------------------
# Quarantine-hold machinery (PRD 2.11)
# ---------------------------------------------------------------------------

def hold_unit(unit, reason):
    """Move a QUARANTINED/AVAILABLE/RESERVED unit into QUARANTINED_HOLD.
    A RESERVED unit's COMPATIBLE crossmatch is cancelled with no release —
    the hold wins."""
    origin = unit["status"]
    unit["status"] = "QUARANTINED_HOLD"
    unit["hold_origin_state"] = origin
    unit["hold_reason"] = reason
    touch(unit)
    if origin == "RESERVED":
        xm = compatible_xm_for_unit(unit["id"])
        if xm is not None:
            cancel_crossmatch(xm, release_unit=False)


def release_hold_to_available(unit):
    unit["status"] = "AVAILABLE"
    unit["hold_origin_state"] = None
    unit["hold_reason"] = None
    touch(unit)


# ---------------------------------------------------------------------------
# TypeAndScreen expiry cascade (PRD 3.1) — shared by the sweep.
# ---------------------------------------------------------------------------

def expire_type_and_screen(ts, counts):
    ts["status"] = "EXPIRED"
    touch(ts)
    counts["ts_expired_count"] += 1
    patient = DB.patients[ts["patient_id"]]
    if patient_has_active_ts(patient["id"]):
        return
    # Patient lost the last ACTIVE specimen: fire the T&S-expiry cascade.
    touch(patient)  # has_active_type_and_screen falls to false
    for xm in DB.crossmatches.values():
        if xm["patient_id"] != patient["id"]:
            continue
        if xm["status"] == "COMPATIBLE":
            expire_crossmatch(xm, release_unit=True)
            counts["crossmatches_expired_count"] += 1
        elif xm["status"] == "PENDING":
            xm["status"] = "CANCELLED"
            touch(xm)
    for order in DB.orders.values():
        if order["patient_id"] != patient["id"]:
            continue
        if order["status"] in ("AWAITING_CROSSMATCH", "READY", "PARTIALLY_ISSUED"):
            order["status"] = "ON_HOLD"
            touch(order)
            counts["orders_held_count"] += 1


# ---------------------------------------------------------------------------
# Maintenance sweep (PRD 2.4)
# ---------------------------------------------------------------------------

def run_sweep():
    counts = {
        "ts_expired_count": 0,
        "crossmatches_expired_count": 0,
        "units_expired_count": 0,
        "coolers_restocked_count": 0,
        "orders_held_count": 0,
    }
    current = now()

    # 1. Expire lapsed TypeAndScreens (ACTIVE and now >= expires_at).
    for ts in list(DB.type_and_screens.values()):
        if ts["status"] == "ACTIVE" and current >= ts["expires_at"]:
            expire_type_and_screen(ts, counts)

    # 2. Expire compatible crossmatches whose reservation window has closed
    #    (now >= reserved_until; boundary inclusive).
    for xm in list(DB.crossmatches.values()):
        if (
            xm["status"] == "COMPATIBLE"
            and xm["reserved_until"] is not None
            and current >= xm["reserved_until"]
        ):
            expire_crossmatch(xm, release_unit=True)
            counts["crossmatches_expired_count"] += 1

    # 3. Expire blood units (ISSUED exempt). RESERVED units take their
    #    COMPATIBLE crossmatch down with them and settle EXPIRED themselves.
    for unit in list(DB.units.values()):
        if unit["status"] not in ("AVAILABLE", "QUARANTINED", "RESERVED", "QUARANTINED_HOLD"):
            continue
        if current < unit["expires_at"]:
            continue
        origin = unit["status"]
        unit["status"] = "EXPIRED"
        unit["hold_origin_state"] = None
        unit["hold_reason"] = None
        touch(unit)
        counts["units_expired_count"] += 1
        add_wastage(unit, "EXPIRED", "system")
        if origin == "RESERVED":
            xm = compatible_xm_for_unit(unit["id"])
            if xm is not None:
                expire_crossmatch(xm, release_unit=False)
                counts["crossmatches_expired_count"] += 1

    # 4a. Release cooler occupancy whose planned window has lapsed.
    for cooler in DB.coolers.values():
        if cooler["status"] != "CHECKED_OUT":
            continue
        occupied = any(
            co["cooler_id"] == cooler["id"]
            and co["status"] == "OPEN"
            and co["planned_start"] <= current <= co["planned_end"]
            for co in DB.checkouts.values()
        )
        if not occupied:
            cooler["status"] = "AVAILABLE"
            touch(cooler)

    # 4b. Return RESTOCKING coolers whose restock_until has been reached.
    for cooler in DB.coolers.values():
        if (
            cooler["status"] == "RESTOCKING"
            and cooler["restock_until"] is not None
            and current >= cooler["restock_until"]
        ):
            cooler["status"] = "AVAILABLE"
            cooler["restock_until"] = None
            touch(cooler)
            counts["coolers_restocked_count"] += 1

    # 4c. Open checkouts whose window now covers the clock occupy their cooler.
    for cooler in DB.coolers.values():
        if cooler["status"] != "AVAILABLE":
            continue
        occupied = any(
            co["cooler_id"] == cooler["id"]
            and co["status"] == "OPEN"
            and co["planned_start"] <= current <= co["planned_end"]
            for co in DB.checkouts.values()
        )
        if occupied:
            cooler["status"] = "CHECKED_OUT"
            touch(cooler)

    # 5. Bucket postures recompute — postures are computed live on every read,
    #    so nothing needs to be stored here.
    return counts


# ---------------------------------------------------------------------------
# calculations.mtp_pack_constitution — pinned waterfall allocation.
# ---------------------------------------------------------------------------

def mtp_preference_buckets(product_type, patient):
    """ABO/Rh bucket preference list for one pack component (PRD 3.6)."""
    patient_abo = patient["current_abo_type"]
    patient_rh = patient["current_rh_type"]
    typed = patient_abo != "UNKNOWN"
    if product_type == "RBC":
        if not typed:
            prefs = [("O", "NEG")]
        else:
            opposite_rh = "NEG" if patient_rh == "POS" else "POS"
            prefs = [
                (patient_abo, patient_rh),
                ("O", "NEG"),
                (patient_abo, opposite_rh),
                ("O", "POS"),
            ]
    elif product_type == "FFP":
        if not typed:
            prefs = [("AB", "NEG")]
        else:
            prefs = [
                (patient_abo, "NEG"), ("AB", "NEG"), ("A", "NEG"),
                ("B", "NEG"), ("O", "NEG"),
            ]
            allowed = ABO_PLASMA_ALLOWED[patient_abo]
            prefs = [p for p in prefs if p[0] in allowed]
    else:  # PLT_APHERESIS
        first_abo = patient_abo if typed else "O"
        prefs = [
            (first_abo, "NEG"), ("A", "NEG"), ("B", "NEG"),
            ("AB", "NEG"), ("O", "NEG"),
        ]
    # De-duplicate preserving first occurrence.
    seen = set()
    out = []
    for p in prefs:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def dispatch_mtp_pack(activation, patient, verified_by_user_id, issued_by_user_id):
    """Walk the pinned component order, filling each per FEFO with immediate
    decrements; shortfalls are recorded, never fatal."""
    issue_records = []
    shortfalls = []
    excluded = set()
    ctx_base = {
        "urgency": "EMERGENCY",
        "type_restriction": "NONE",
        "special_requirements": list(patient.get("special_requirements") or []),
    }
    for product_type, qty in PACK_SPEC:
        need = qty
        ctx = dict(ctx_base)
        ctx["product_type"] = product_type
        for abo_type, rh_type in mtp_preference_buckets(product_type, patient):
            if need == 0:
                break
            while need > 0:
                unit = fefo_select(
                    product_type, patient, ctx,
                    abo_type=abo_type, rh_type=rh_type, excluded_ids=excluded,
                )
                if unit is None:
                    break
                excluded.add(unit["id"])
                need -= 1
                unit["status"] = "ISSUED"
                touch(unit)
                issue_records.append((unit, ctx))
        if need > 0:
            shortfalls.append({"product_type": product_type, "missing_qty": need})
    return issue_records, shortfalls
