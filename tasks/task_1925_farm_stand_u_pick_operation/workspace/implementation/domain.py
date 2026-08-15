"""Domain logic: derived fields, serializers, settlements, refunds, cascades.

Derived fields (PRD §2.5) are recomputed at read time from source rows, which
is observationally identical to the PRD's "recomputed immediately inside the
mutating request": any read after a successful write observes post-write state.
Version bumps follow exactly the mutations the scaffold declares.
"""

from datetime import timedelta

import db
from errors import (
    raise_err,
    ERR_WAIVER_VOIDED,
    ERR_WAIVER_STALE,
    ERR_WAIVER_PARTY_MISMATCH,
)
from helpers import round_half_up_div

# Global constants (scaffold §1.3)
TARE_OZ_PER_CONTAINER = 4
STAFF_COVERAGE_SLOTS_PER_STAFF = 25
OFFLINE_OVERBOOK_ALLOWANCE_SLOTS = 10
FIELD_REST_DAYS = 7
OZ_PER_LB = 16
BPS_DENOMINATOR = 10000


# ------------------------------------------------------------------ entities
def new_entity():
    ts = db.wall_ts()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = db.wall_ts()


# ------------------------------------------------------------- relationships
def field_of_window(window):
    return db.fields.get(window["field_id"])


def season_of_field(field):
    return db.seasons.get(field["season_id"])


def season_of_window(window):
    field = field_of_window(window)
    return db.seasons.get(field["season_id"]) if field else None


def window_of_session(session):
    return db.windows.get(session["window_id"])


def field_of_session(session):
    window = window_of_session(session)
    return field_of_window(window) if window else None


def season_of_session(session):
    field = field_of_session(session)
    return db.seasons.get(field["season_id"]) if field else None


def sales_day_for(season_id, date):
    for day in db.sales_days.values():
        if day["season_id"] == season_id and day["date"] == date:
            return day
    return None


def sessions_on_window(window_id):
    return [s for s in db.visit_sessions.values() if s["window_id"] == window_id]


def windows_on_date(season_id, date):
    out = []
    for w in db.windows.values():
        f = field_of_window(w)
        if f and f["season_id"] == season_id and w["date"] == date:
            out.append(w)
    return out


# ------------------------------------------------------------ derived fields
def field_committed_oz(field):
    return sum(
        l["net_oz"]
        for l in db.harvest_lines.values()
        if l["field_id"] == field["id"] and l["status"] == "FINALIZED"
    )


def field_projected_remaining_oz(field):
    counted = sum(
        l["net_oz"]
        for l in db.harvest_lines.values()
        if l["field_id"] == field["id"] and l["status"] in ("PROVISIONAL", "FINALIZED")
    )
    return field["estimated_harvest_oz"] - counted


def crop_season_picked_oz(crop):
    return sum(
        l["net_oz"]
        for l in db.harvest_lines.values()
        if l["crop_id"] == crop["id"] and l["status"] == "FINALIZED"
    )


def window_booked_slots(window):
    return sum(
        s["party_size"]
        for s in db.visit_sessions.values()
        if s["window_id"] == window["id"]
        and s["visit_status"] not in ("CANCELLED", "VOIDED")
    )


def sessions_on_day(day):
    return [
        s
        for s in db.visit_sessions.values()
        if (w := window_of_session(s)) is not None
        and (f := field_of_window(w)) is not None
        and f["season_id"] == day["season_id"]
        and w["date"] == day["date"]
    ]


def day_booked_parking(day):
    return sum(
        s["parking_spaces"]
        for s in sessions_on_day(day)
        if s["visit_status"] not in ("CANCELLED", "VOIDED")
    )


def day_revenue_cents(day):
    return sum(
        session_total_paid(s) - session_total_refunded(s) for s in sessions_on_day(day)
    )


def session_payments(session):
    return [p for p in db.payments.values() if p["session_id"] == session["id"]]


def session_total_paid(session):
    return sum(
        p["amount_cents"]
        for p in session_payments(session)
        if p["status"] in ("SETTLED", "PARTIALLY_REFUNDED", "REFUNDED")
    )


def session_total_refunded(session):
    return sum(p["refunded_amount_cents"] for p in session_payments(session))


def session_payment_status(session):
    total_paid = session_total_paid(session)
    total_refunded = session_total_refunded(session)
    net_paid = total_paid - total_refunded
    if total_paid == 0:
        return "UNPAID"
    if total_refunded >= total_paid:
        return "REFUNDED"
    if total_refunded > 0:
        return "PARTIALLY_REFUNDED"
    if session["final_total_cents"] is not None and net_paid >= session["final_total_cents"]:
        return "PAID"
    if session["final_total_cents"] is None and net_paid >= session["admission_charge_cents"]:
        return "PAID"
    return "PARTIALLY_PAID"


def session_lines(session):
    return [l for l in db.harvest_lines.values() if l["session_id"] == session["id"]]


def session_bookings(session):
    return [b for b in db.addon_bookings.values() if b["session_id"] == session["id"]]


def weigh_out_total(session):
    """Sum of line_charge_cents over FINALIZED lines only (round per line
    first — lines are already pinned — then exact integer sum)."""
    return sum(l["line_charge_cents"] for l in session_lines(session) if l["status"] == "FINALIZED")


# ------------------------------------------------------------------ waivers
def check_waiver_trio(waiver, season, party_size):
    """PRD §2.7 gate 9 — fixed relative order."""
    if waiver["status"] != "SIGNED":
        raise_err(ERR_WAIVER_VOIDED, "Waiver is VOIDED")
    if waiver["waiver_version_signed"] != season["current_waiver_version"]:
        raise_err(ERR_WAIVER_STALE, "Waiver version is stale")
    if len(waiver["party_member_names"]) < party_size:
        raise_err(ERR_WAIVER_PARTY_MISMATCH, "Waiver covers fewer names than party_size")


# ------------------------------------------------------------------ pricing
def compute_admission_charge(policy, day, party_size, container_count):
    admission_component = policy["admission_per_person_cents"] * party_size
    if day is not None and day["day_type"] == "WEEKEND":
        admission_component = round_half_up_div(
            admission_component * policy["weekend_surge_bps"], BPS_DENOMINATOR
        )
    container_component = policy["container_fee_cents"] * container_count
    return admission_component + container_component


def compute_line_values(crop, gross_weight_oz, container_count):
    tare_oz = container_count * TARE_OZ_PER_CONTAINER
    net_oz = gross_weight_oz - tare_oz
    line_charge_cents = round_half_up_div(net_oz * crop["price_per_lb_cents"], OZ_PER_LB) if net_oz >= 0 else None
    return tare_oz, net_oz, line_charge_cents


def checkout_settlement(session):
    """Pinned evaluation order (PRD §3.7):
    1 addon_total over REDEEMED bookings; 2 discount base = admission + addons
    (harvest excluded); 3 bundle discount (both kinds REDEEMED required);
    4 harvest total over FINALIZED lines; 5 final total."""
    policy = db.pricing_policies.get(session["pricing_policy_id"])
    redeemed = [b for b in session_bookings(session) if b["status"] == "REDEEMED"]
    addon_total = sum(b["booked_value_cents"] for b in redeemed)
    discount_base = session["admission_charge_cents"] + addon_total
    has_wagon = any(
        (p := db.addon_products.get(b["addon_product_id"])) and p["kind"] == "WAGON_RIDE"
        for b in redeemed
    )
    has_cafe = any(
        (p := db.addon_products.get(b["addon_product_id"])) and p["kind"] == "CAFE_VOUCHER"
        for b in redeemed
    )
    if has_wagon and has_cafe and policy is not None:
        bundle_discount = min(
            policy["bundle_cap_cents"],
            round_half_up_div(policy["bundle_discount_bps"] * discount_base, BPS_DENOMINATOR),
        )
    else:
        bundle_discount = 0
    harvest_total = weigh_out_total(session)
    final_total = (
        session["admission_charge_cents"] + addon_total + harvest_total - bundle_discount
    )
    return final_total, bundle_discount


# ------------------------------------------------------------------ refunds
def apply_refund(session, amount):
    """Increment refunded_amount_cents on the session's SETTLED CHARGE payments
    in created_at ASC order. Hard cap: never refund more than the net collected
    amount — money is never created; excess is discarded."""
    remaining_cap = session_total_paid(session) - session_total_refunded(session)
    to_apply = max(0, min(amount, remaining_cap))
    eligible = sorted(
        (
            p
            for p in session_payments(session)
            if p["status"] in ("SETTLED", "PARTIALLY_REFUNDED")
            and p["refunded_amount_cents"] < p["amount_cents"]
        ),
        key=lambda p: (p["created_at"], p["_seq"]),
    )
    for p in eligible:
        if to_apply <= 0:
            break
        room = p["amount_cents"] - p["refunded_amount_cents"]
        take = min(room, to_apply)
        p["refunded_amount_cents"] += take
        p["status"] = "REFUNDED" if p["refunded_amount_cents"] == p["amount_cents"] else "PARTIALLY_REFUNDED"
        touch(p)
        to_apply -= take


def release_booking(booking, refund):
    booking["status"] = "RELEASED"
    touch(booking)
    if refund:
        session = db.visit_sessions.get(booking["session_id"])
        if session is not None:
            apply_refund(session, booking["booked_value_cents"])
            touch(session)


# --------------------------------------------------------- PICKED_OUT cascade
def maybe_pick_out_field(field):
    """Fires when committed_picked_oz >= estimated_harvest_oz on an OPEN field.
    Cancels the field's future/today SCHEDULED windows (DEPLETED) and pins the
    rotation successor."""
    if field["status"] != "OPEN":
        return
    if field_committed_oz(field) < field["estimated_harvest_oz"]:
        return
    field["status"] = "PICKED_OUT"
    today = db.logical_date_str()
    for w in db.windows.values():
        if (
            w["field_id"] == field["id"]
            and w["status"] == "SCHEDULED"
            and w["date"] >= today
        ):
            w["status"] = "CANCELLED"
            w["cancel_reason"] = "DEPLETED"
            touch(w)
    eligible = [
        f
        for f in db.fields.values()
        if f["season_id"] == field["season_id"]
        and f["rotation_group"] == field["rotation_group"]
        and f["status"] == "DORMANT"
        and (f["rest_until"] is None or f["rest_until"] <= today)
    ]
    eligible.sort(key=lambda f: (f["rotation_order"], f["created_at"], f["_seq"]))
    field["rotation_successor_field_id"] = eligible[0]["id"] if eligible else None


def tally_after_line_mutation(field, crop):
    """Version bumps declared for weigh-out create/finalize/void (PRD §2.6)."""
    touch(field)
    if crop is not None:
        touch(crop)
    maybe_pick_out_field(field)


# --------------------------------------------------------------- serializers
def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_season(s):
    return _public(s)


def serialize_crop(c):
    out = _public(c)
    out["season_picked_oz"] = crop_season_picked_oz(c)
    return out


def serialize_field(f):
    out = _public(f)
    out["committed_picked_oz"] = field_committed_oz(f)
    out["projected_remaining_oz"] = field_projected_remaining_oz(f)
    return out


def serialize_window(w):
    out = _public(w)
    out["booked_slots"] = window_booked_slots(w)
    return out


def serialize_policy(p):
    return _public(p)


def serialize_waiver(w):
    return _public(w)


def serialize_session(s):
    out = _public(s)
    out["total_paid_cents"] = session_total_paid(s)
    out["total_refunded_cents"] = session_total_refunded(s)
    out["payment_status"] = session_payment_status(s)
    return out


def serialize_line(l):
    return _public(l)


def serialize_addon_product(p):
    return _public(p)


def serialize_addon_booking(b):
    return _public(b)


def serialize_payment(p):
    return _public(p)


def serialize_sales_day(d):
    out = _public(d)
    out["booked_parking"] = day_booked_parking(d)
    out["revenue_cents"] = day_revenue_cents(d)
    return out


def serialize_batch(b):
    return _public(b)
