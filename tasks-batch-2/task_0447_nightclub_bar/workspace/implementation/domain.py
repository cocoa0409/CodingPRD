"""Domain logic: entity construction, computed fields, posture, calculations,
state transitions and cascades (PRD §2.4-§2.9, §3).

All monetary amounts are integer cents. Where a fractional cent arises (surge
surcharge, auto-gratuity) the result is rounded half-up to the nearest whole
cent. Decimal arithmetic is used for those steps; everything else is exact
integer arithmetic.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from clock import clock, format_iso_ms
import errors

LEGAL_DRINKING_AGE = 21
SURGE_OCCUPANCY_FRACTION = Decimal("0.9")


# ---------------------------------------------------------------------------
# Rounding helper
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    """Round a Decimal cents value to the nearest whole cent, half rounds up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common system field management
# ---------------------------------------------------------------------------
def _stamp_create(rec):
    now = clock.now_iso()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = db.next_seq()


def touch(rec):
    """Refresh updated_at and bump version (a single mutation, PRD §2.4)."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Posture recomputation (PRD §2.6, §3.8)
# ---------------------------------------------------------------------------
def occupancy_count(venue):
    return sum(
        1 for e in db.entries.values()
        if e["venue_id"] == venue["id"] and e["status"] == "INSIDE"
    )


def tabs_open_count(venue):
    return sum(
        1 for t in db.tabs.values()
        if t["venue_id"] == venue["id"] and t["status"] in ("OPEN", "RUNNING")
    )


def _last_call_start(venue):
    from clock import parse_iso
    import datetime
    closing = parse_iso(venue["closing_time_utc"])
    return closing - datetime.timedelta(minutes=venue["last_call_offset_minutes"])


def in_last_call_window(venue):
    """True iff the logical clock is within [closing - offset, closing)."""
    from clock import parse_iso
    now = clock.now()
    closing = parse_iso(venue["closing_time_utc"])
    return _last_call_start(venue) <= now < closing


def at_or_past_closing(venue):
    from clock import parse_iso
    return clock.now() >= parse_iso(venue["closing_time_utc"])


def recompute_posture(venue):
    """Re-derive posture (does not itself bump version; callers do).

    CLOSED is terminal: once closed, never recompute away from CLOSED.
    Clock-driven CLOSED is handled by close cascades in clock-set, not here.
    """
    if venue["posture"] == "CLOSED":
        return
    occ = occupancy_count(venue)
    if in_last_call_window(venue):
        venue["posture"] = "LAST_CALL"
    elif occ >= venue["fire_code_capacity"]:
        venue["posture"] = "AT_CAPACITY"
    else:
        venue["posture"] = "OPEN"


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common_out(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_venue(v):
    out = _common_out(v)
    out.update({
        "name": v["name"],
        "fire_code_capacity": v["fire_code_capacity"],
        "last_call_offset_minutes": v["last_call_offset_minutes"],
        "closing_time_utc": v["closing_time_utc"],
        "cover_base_cents": v["cover_base_cents"],
        "cover_surge_pct": v["cover_surge_pct"],
        "max_alcohol_strikes": v["max_alcohol_strikes"],
        "occupancy_count": occupancy_count(v),
        "tabs_open_count": tabs_open_count(v),
        "posture": v["posture"],
    })
    return out


def promoter_comp_committed(p):
    return sum(
        g["comp_value_cents"] for g in db.guest_list.values()
        if g.get("promoter_id") == p["id"] and g["status"] in ("CONFIRMED", "REDEEMED")
    )


def promoter_heads_credited(p):
    total = 0
    for e in db.entries.values():
        if e["status"] not in ("INSIDE", "EXITED"):
            continue
        gle_id = e.get("guest_list_entry_id")
        if not gle_id:
            continue
        gle = db.guest_list.get(gle_id)
        if gle and gle.get("promoter_id") == p["id"]:
            total += 1
    return total


def serialize_promoter(p):
    out = _common_out(p)
    out.update({
        "venue_id": p["venue_id"],
        "name": p["name"],
        "comp_budget_cents": p["comp_budget_cents"],
        "guest_discount_pct": p["guest_discount_pct"],
        "comp_committed_cents": promoter_comp_committed(p),
        "heads_credited": promoter_heads_credited(p),
    })
    return out


def serialize_guest_list(g):
    out = _common_out(g)
    out.update({
        "venue_id": g["venue_id"],
        "promoter_id": g.get("promoter_id"),
        "guest_name": g["guest_name"],
        "party_size": g["party_size"],
        "comp_value_cents": g["comp_value_cents"],
        "status": g["status"],
        "redeemed_entry_id": g.get("redeemed_entry_id"),
    })
    return out


def serialize_reservation(r):
    out = _common_out(r)
    out.update({
        "venue_id": r["venue_id"],
        "table_label": r["table_label"],
        "party_size": r["party_size"],
        "window_start_utc": r["window_start_utc"],
        "window_end_utc": r["window_end_utc"],
        "spend_minimum_cents": r["spend_minimum_cents"],
        "deposit_cents": r["deposit_cents"],
        "status": r["status"],
        "minimum_shortfall_cents": r.get("minimum_shortfall_cents"),
    })
    return out


def running_subtotal(tab):
    return sum(
        it["qty"] * it["unit_price_cents"]
        for it in db.tab_items.values()
        if it["tab_id"] == tab["id"] and not it["voided"]
    )


def serialize_tab(t):
    out = _common_out(t)
    out.update({
        "venue_id": t["venue_id"],
        "reservation_id": t.get("reservation_id"),
        "patron_name": t["patron_name"],
        "preauth_cents": t["preauth_cents"],
        "gratuity_pct": t["gratuity_pct"],
        "running_subtotal_cents": running_subtotal(t),
        "final_total_cents": t["final_total_cents"],
        "bac_strikes": t["bac_strikes"],
        "status": t["status"],
    })
    return out


def serialize_tab_item(it):
    return {
        "id": it["id"],
        "created_at": it["created_at"],
        "tab_id": it["tab_id"],
        "name": it["name"],
        "category": it["category"],
        "qty": it["qty"],
        "unit_price_cents": it["unit_price_cents"],
        "voided": it["voided"],
    }


def serialize_entry(e):
    out = _common_out(e)
    out.update({
        "venue_id": e["venue_id"],
        "guest_list_entry_id": e.get("guest_list_entry_id"),
        "id_check_id": e["id_check_id"],
        "cover_paid_cents": e["cover_paid_cents"],
        "admitted_at_utc": e["admitted_at_utc"],
        "exited_at_utc": e.get("exited_at_utc"),
        "status": e["status"],
    })
    return out


def serialize_id_check(c):
    out = _common_out(c)
    out.update({
        "venue_id": c["venue_id"],
        "patron_name": c["patron_name"],
        "date_of_birth": c["date_of_birth"],
        "id_expiry": c["id_expiry"],
        "computed_age_years": c["computed_age_years"],
        "outcome": c["outcome"],
        "refusal_reason": c.get("refusal_reason"),
    })
    return out


def serialize_incident(i):
    out = _common_out(i)
    out.update({
        "venue_id": i["venue_id"],
        "subject_entry_id": i.get("subject_entry_id"),
        "severity": i["severity"],
        "action": i["action"],
        "narrative": i["narrative"],
        "logged_at_utc": i["logged_at_utc"],
    })
    return out


# ---------------------------------------------------------------------------
# Calculations (PRD §3.4, §3.7)
# ---------------------------------------------------------------------------
def compute_cover(venue, gle):
    """cover_charge_amount (PRD §3.4 / SCAFFOLD calc cover_charge_amount).

    Ordered: surge band -> guest-list/promoter discount -> comp subtraction.
    House-list (gle set, promoter_id null): surge WAIVED, disc 0, comp applies.
    Walk-up (gle None): full surged base, no discount, no comp.
    """
    base = Decimal(venue["cover_base_cents"])
    occ = occupancy_count(venue)
    # Surge threshold: 90% of capacity, ceiling to next whole head.
    threshold = math.ceil(SURGE_OCCUPANCY_FRACTION * Decimal(venue["fire_code_capacity"]))

    house_list = gle is not None and gle.get("promoter_id") is None

    if house_list:
        # House list: surge waived -> use base, not surged.
        surged = base
    elif occ >= threshold:
        surged = Decimal(round_half_up_cents(
            base * (Decimal(1) + Decimal(str(venue["cover_surge_pct"])))
        ))
    else:
        surged = base

    if gle is None:
        return int(surged)

    if gle.get("promoter_id") is not None:
        promoter = db.promoters.get(gle["promoter_id"])
        disc = Decimal(str(promoter["guest_discount_pct"])) if promoter else Decimal(0)
    else:
        disc = Decimal(0)

    after_disc = Decimal(round_half_up_cents(surged * (Decimal(1) - disc)))
    cover_paid = max(0, int(after_disc) - gle["comp_value_cents"])
    return cover_paid


def tab_grand_total(tab):
    """tab_final_total (PRD §3.7): sum-then-gratuity, one round on the summed subtotal."""
    subtotal = running_subtotal(tab)
    gratuity = round_half_up_cents(Decimal(subtotal) * Decimal(str(tab["gratuity_pct"])))
    return subtotal + gratuity


# ---------------------------------------------------------------------------
# Age / ID-check (PRD §3.3)
# ---------------------------------------------------------------------------
def compute_age_years(date_of_birth):
    import datetime
    dob = datetime.date.fromisoformat(date_of_birth)
    now = clock.today()
    age = now.year - dob.year
    if (now.month, now.day) < (dob.month, dob.day):
        age -= 1
    return age


def compute_id_check_outcome(id_expiry, age):
    """Ordered gate: expiry BEFORE age (PRD §3.3)."""
    import datetime
    expiry = datetime.date.fromisoformat(id_expiry)
    now = clock.today()
    if expiry < now:
        return "REFUSED_EXPIRED_ID", "ID expired"
    if age < LEGAL_DRINKING_AGE:
        return "REFUSED_UNDERAGE", "Under legal drinking age"
    return "PASS", None


# ---------------------------------------------------------------------------
# Tab settlement (PRD §3.7)
# ---------------------------------------------------------------------------
def settle_tab(tab, forced=False, final_total_override=None):
    """Settle a tab: compute final_total, capture pre-auth up to total, release rest.

    forced=True waives the pre-auth-sufficiency check (venue-close / reservation
    cascade). Caller must already have validated state.

    final_total_override pins the final total to an externally computed value
    (the reservation-settle cascade: grand_step1 + shortfall). This is required
    because the appended "Minimum top-up" SERVICE line is added AFTER gratuity is
    computed and must NOT itself attract gratuity (PRD §3.7) — so the final total
    cannot be re-derived from the augmented line set.
    """
    if final_total_override is not None:
        total = final_total_override
    else:
        total = tab_grand_total(tab)
    if not forced and tab["preauth_cents"] < total:
        raise errors.preauth_insufficient()
    tab["final_total_cents"] = total
    tab["status"] = "SETTLED"
    touch(tab)


# ---------------------------------------------------------------------------
# Reservation settlement with minimum top-up (PRD §3.7)
# ---------------------------------------------------------------------------
def linked_tab(reservation):
    for t in db.tabs.values():
        if t.get("reservation_id") == reservation["id"]:
            return t
    return None


def settle_reservation(reservation, forced=False):
    """Settle a SEATED reservation: compute shortfall, append SERVICE top-up to the
    linked tab if positive, then settle the linked tab. PRD §3.7.

    forced=True (venue-close cascade) waives the linked tab's pre-auth check.
    """
    tab = linked_tab(reservation)
    if tab is not None and tab["status"] in ("SETTLED", "VOIDED"):
        tab = None  # already terminal; no further settlement

    if tab is None:
        grand_step1 = 0
    else:
        grand_step1 = tab_grand_total(tab)

    shortfall = max(0, reservation["spend_minimum_cents"] - grand_step1)

    if tab is not None and shortfall > 0:
        create_tab_item(
            tab,
            name="Minimum top-up",
            category="SERVICE",
            qty=1,
            unit_price_cents=shortfall,
            bump_strikes=False,
        )

    if tab is not None:
        # The tab's final total is grand_step1 + shortfall (PRD §3.7): the
        # appended top-up line does NOT attract gratuity, so we pin the total
        # rather than re-deriving subtotal+gratuity over the augmented lines.
        # Forced because the reservation-settle path is not gated by the pre-auth
        # check (that gate guards POST /tabs/{id}/settle directly).
        settle_tab(tab, forced=True, final_total_override=grand_step1 + shortfall)

    reservation["minimum_shortfall_cents"] = shortfall
    reservation["status"] = "SETTLED"
    touch(reservation)


# ---------------------------------------------------------------------------
# Tab item creation helper (used by route + reservation cascade)
# ---------------------------------------------------------------------------
def create_tab_item(tab, name, category, qty, unit_price_cents, bump_strikes=True):
    item = {
        "id": db.new_id(),
        "created_at": clock.now_iso(),
        "_seq": db.next_seq(),
        "tab_id": tab["id"],
        "name": name,
        "category": category,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
        "voided": False,
    }
    db.tab_items[item["id"]] = item
    # First non-voided item advances OPEN -> RUNNING.
    if tab["status"] == "OPEN":
        tab["status"] = "RUNNING"
    if bump_strikes and category == "ALCOHOL":
        tab["bac_strikes"] += 1
    touch(tab)
    return item


# ---------------------------------------------------------------------------
# Entry exit / ejection (PRD §3.5)
# ---------------------------------------------------------------------------
def exit_entry(entry, new_status="EXITED"):
    entry["status"] = new_status
    entry["exited_at_utc"] = clock.now_iso()
    touch(entry)
    venue = db.venues.get(entry["venue_id"])
    if venue:
        recompute_posture(venue)
        touch(venue)


# ---------------------------------------------------------------------------
# Venue close cascade (PRD §3.8)
# ---------------------------------------------------------------------------
def close_venue(venue):
    """Run the full close cascade and set posture CLOSED, version +1.

    Order (PRD §3.8): BOOKED reservations -> NO_SHOW; SEATED reservations ->
    SETTLED (driving linked-tab settlement); remaining OPEN/RUNNING tabs ->
    SETTLED (forced, pre-auth check waived); INSIDE entries -> EXITED. Each
    touched entity gets its own updated_at + version bump.
    """
    vid = venue["id"]

    # Reservations: BOOKED -> NO_SHOW (deposit forfeited).
    for r in list(db.reservations.values()):
        if r["venue_id"] == vid and r["status"] == "BOOKED":
            r["status"] = "NO_SHOW"
            touch(r)

    # Reservations: SEATED -> SETTLED (drives linked tab settlement, forced).
    for r in list(db.reservations.values()):
        if r["venue_id"] == vid and r["status"] == "SEATED":
            settle_reservation(r, forced=True)

    # Remaining OPEN/RUNNING tabs -> SETTLED (forced).
    for t in list(db.tabs.values()):
        if t["venue_id"] == vid and t["status"] in ("OPEN", "RUNNING"):
            settle_tab(t, forced=True)

    # Entries INSIDE -> EXITED.
    for e in list(db.entries.values()):
        if e["venue_id"] == vid and e["status"] == "INSIDE":
            e["status"] = "EXITED"
            e["exited_at_utc"] = clock.now_iso()
            touch(e)

    venue["posture"] = "CLOSED"
    touch(venue)


# ---------------------------------------------------------------------------
# Clock advance: recompute posture for all venues, run due closes (PRD §2.4, §3.8)
# ---------------------------------------------------------------------------
def advance_clock_recompute():
    for v in list(db.venues.values()):
        if v["posture"] == "CLOSED":
            continue
        if at_or_past_closing(v):
            close_venue(v)
        else:
            before = v["posture"]
            recompute_posture(v)
            if v["posture"] != before:
                touch(v)
