"""Domain logic: lookups, active policy, calculations, seat reconciliation,
join-flag recompute, and the weather closure cascade (PRD §3)."""
from decimal import Decimal

import db
from common import round_half_up_cents, ceil_cents, touch
from errors import ApiError

DEPOSIT_PCT = Decimal("0.25")  # PRD §3.8 / scaffold group_deposit


# --------------------------------------------------------------------------- #
# Lookups (existence — ERR_NOT_FOUND, priority 3)
# --------------------------------------------------------------------------- #
def get_farm(fid):
    f = db.farms.get(fid)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Farm not found")
    return f


def get_window(wid):
    w = db.admission_windows.get(wid)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", "AdmissionWindow not found")
    return w


def get_visitor(vid):
    v = db.visitors.get(vid)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "Visitor not found")
    return v


def get_policy(pid):
    p = db.pricing_policies.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "PricingPolicy not found")
    return p


def get_pass(sid):
    s = db.season_passes.get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", "SeasonPass not found")
    return s


def get_reservation(rid):
    r = db.reservations.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Reservation not found")
    return r


def get_group(gid):
    g = db.group_bookings.get(gid)
    if g is None:
        raise ApiError("ERR_NOT_FOUND", "GroupBooking not found")
    return g


def get_pumpkin(pid):
    p = db.pumpkin_purchases.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "PumpkinPurchase not found")
    return p


def active_policy(farm_id):
    """Return the single ACTIVE PricingPolicy on a farm, or raise ERR_NO_ACTIVE_POLICY."""
    for p in db.pricing_policies.values():
        if p["farm_id"] == farm_id and p["status"] == "ACTIVE":
            return p
    raise ApiError("ERR_NO_ACTIVE_POLICY", "Farm has no ACTIVE pricing policy")


# --------------------------------------------------------------------------- #
# Calculations (PRD §3.5)
# --------------------------------------------------------------------------- #
def admission_charge(reservation, policy):
    """Provisional/settled admission charge (the variant difference is which
    group status is read by the caller at the moment it calls this)."""
    base = (reservation["adult_count"] * policy["adult_admission_cents"]
            + reservation["child_count"] * policy["child_admission_cents"])

    gbid = reservation.get("group_booking_id")
    if gbid:
        group = db.group_bookings.get(gbid)
        if group is not None and group["status"] == "CONFIRMED":
            if group["kind"] == "SCHOOL":
                pct = Decimal(str(policy["school_discount_pct"]))
            else:
                pct = Decimal(str(policy["group_discount_pct"]))
            base = round_half_up_cents(Decimal(base) * (Decimal(1) - pct))

    spid = reservation.get("season_pass_id")
    if spid:
        sp = db.season_passes.get(spid)
        if sp is not None and sp["status"] == "ACTIVE":
            return 0
    return base


def pumpkin_charge(weight_lb, policy):
    """Threshold pricing: >= heavy_pumpkin_lb -> flat-each; else per-lb round-half-up."""
    w = Decimal(str(weight_lb))
    breakpoint_lb = Decimal(str(policy["heavy_pumpkin_lb"]))
    if w >= breakpoint_lb:
        return policy["pumpkin_flat_each_cents"]
    return round_half_up_cents(w * Decimal(policy["pumpkin_per_lb_cents"]))


def group_quote(group, policy):
    """Group quote (PRD §3.7): per-head base, discount only if headcount qualifies,
    SCHOOL gets school rate else group rate, round-half-up once after the multiply."""
    per_head_base = (group["adult_count"] * policy["adult_admission_cents"]
                     + group["child_count"] * policy["child_admission_cents"])
    headcount = group["adult_count"] + group["child_count"]
    if headcount >= policy["group_rate_min_headcount"]:
        if group["kind"] == "SCHOOL":
            pct = Decimal(str(policy["school_discount_pct"]))
        else:
            pct = Decimal(str(policy["group_discount_pct"]))
    else:
        pct = Decimal(0)
    return round_half_up_cents(Decimal(per_head_base) * (Decimal(1) - pct))


def group_deposit(quoted_total_cents):
    return ceil_cents(Decimal(quoted_total_cents) * DEPOSIT_PCT)


def reservation_grand_total(reservation):
    """Computed read (PRD §3.5) — pinned step order, wallet applied last."""
    status = reservation["status"]
    if status in ("CHECKED_IN", "SETTLED"):
        step1 = reservation["settled_charge_cents"]
    else:
        step1 = reservation["admission_charge_cents"]

    rid = reservation["id"]
    step2 = sum(a["line_total_cents"] for a in db.activity_passes.values()
                if a["reservation_id"] == rid and a["status"] == "ACTIVE")
    step3 = sum(p["charge_cents"] for p in db.pumpkin_purchases.values()
                if p["reservation_id"] == rid and p["status"] in ("ESTIMATED", "WEIGHED"))
    step4 = sum(c["total_cents"] for c in db.concession_orders.values()
                if c["reservation_id"] == rid and c["status"] == "PAID")

    gross = step1 + step2 + step3 + step4
    visitor = db.visitors.get(reservation["visitor_id"])
    wallet = visitor["wallet_credit_cents"] if visitor else 0
    applied = min(wallet, gross)
    net_due = gross - applied
    return gross, net_due


# --------------------------------------------------------------------------- #
# Window seat reconciliation (PRD §3.3 / calc window_seats)
# --------------------------------------------------------------------------- #
def reconcile_window(window):
    wid = window["id"]
    held = sum(r["participant_count"] for r in db.reservations.values()
               if r["window_id"] == wid and r["status"] == "PENDING")
    committed = sum(r["participant_count"] for r in db.reservations.values()
                    if r["window_id"] == wid
                    and r["status"] in ("CONFIRMED", "CHECKED_IN", "SETTLED"))
    committed += sum(g["headcount"] for g in db.group_bookings.values()
                     if g["window_id"] == wid and g["status"] == "CONFIRMED")
    available = max(0, window["capacity"] - held - committed)

    changed = (window["seats_held"] != held
               or window["seats_committed"] != committed
               or window["seats_available"] != available)
    window["seats_held"] = held
    window["seats_committed"] = committed
    window["seats_available"] = available

    # Derived status flips (only between SCHEDULED <-> SOLD_OUT; CANCELLED is terminal).
    if window["status"] != "CANCELLED":
        if available == 0 and window["status"] == "SCHEDULED":
            window["status"] = "SOLD_OUT"
            changed = True
        elif available > 0 and window["status"] == "SOLD_OUT":
            window["status"] = "SCHEDULED"
            changed = True

    if changed:
        touch(window)


# --------------------------------------------------------------------------- #
# Reservation join-flag recompute (PRD §2.5 / §3.4)
# --------------------------------------------------------------------------- #
def recompute_waiver_satisfied(reservation):
    rid = reservation["id"]
    signed = sum(1 for w in db.waivers.values()
                 if w["reservation_id"] == rid and w["status"] == "SIGNED")
    new_val = signed >= reservation["participant_count"]
    if reservation["waiver_satisfied"] != new_val:
        reservation["waiver_satisfied"] = new_val
        touch(reservation)


def recompute_checkout_finalized(reservation):
    rid = reservation["id"]
    has_estimated = any(p["status"] == "ESTIMATED"
                        for p in db.pumpkin_purchases.values()
                        if p["reservation_id"] == rid)
    new_val = not has_estimated
    if reservation["checkout_finalized"] != new_val:
        reservation["checkout_finalized"] = new_val
        touch(reservation)


# --------------------------------------------------------------------------- #
# Reservation cancellation (shared by self-cancel and closure cascade; PRD §3.3/§3.6)
# --------------------------------------------------------------------------- #
def cancel_reservation_inventory_and_children(reservation, closure_cause):
    """Release inventory, void/revoke/refund children, and (closure only) credit
    the wallet / decrement the pass / roll up the farm refund. Does NOT set the
    reservation status — the caller does that before/after calling."""
    prev_status = reservation["status"]
    reservation["status"] = "CANCELLED"

    # Closure cascade credit (L3): only on closure, not self-cancel.
    if closure_cause:
        spid = reservation.get("season_pass_id")
        if spid:
            sp = db.season_passes.get(spid)
            if sp is not None:
                sp["visits_used"] -= 1
                touch(sp)
        visitor = db.visitors.get(reservation["visitor_id"])
        if visitor is not None:
            visitor["wallet_credit_cents"] += reservation["admission_charge_cents"]
            touch(visitor)
        farm = _farm_of_reservation(reservation)
        if farm is not None:
            farm["refunds_issued_cents"] += reservation["admission_charge_cents"]
            touch(farm)

    # Revoke/void/refund children (both paths).
    rid = reservation["id"]
    for a in db.activity_passes.values():
        if a["reservation_id"] == rid and a["status"] == "ACTIVE":
            a["status"] = "REVOKED"
            touch(a)
    for w in db.waivers.values():
        if w["reservation_id"] == rid and w["status"] == "SIGNED":
            w["status"] = "VOID"
            touch(w)
    for p in db.pumpkin_purchases.values():
        if p["reservation_id"] == rid and p["status"] in ("ESTIMATED", "WEIGHED"):
            p["status"] = "VOID"
            touch(p)
    for c in db.concession_orders.values():
        if c["reservation_id"] == rid and c["status"] == "PAID":
            c["status"] = "REFUNDED"
            touch(c)

    touch(reservation)
    return prev_status


def _farm_of_reservation(reservation):
    w = db.admission_windows.get(reservation["window_id"])
    if w is None:
        return None
    return db.farms.get(w["farm_id"])
