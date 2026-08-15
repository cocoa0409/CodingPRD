"""Business logic: terminal posture, fee calculations, screening staffing,
cascades, and serializers. All rules trace to PRD sections 2.4-2.10 and 3.x.
"""

from datetime import timedelta
from decimal import Decimal

import db
from util import parse_dt, dt_of, rhu_div, ceil_hours, floor_hours, ceil_div

# --- Calculation constants (SCAFFOLD 1.3) ---
LOA_SAFETY_MARGIN_FT = 30
BERTH_BUFFER_MINUTES = 120
MIN_TURNAROUND_HOURS = 6
DOCKAGE_MIN_BILLED_HOURS = 10
OVERTIME_MULTIPLIER_NUM = 3   # 1.5 as 3/2
OVERTIME_MULTIPLIER_DEN = 2
LATE_PENALTY_PCT = 10
TIER1_MAX_LOA_FT = 700
TIER1_RATE_CENTS = 95
TIER2_MAX_LOA_FT = 1000
TIER2_RATE_CENTS = 125
TIER3_RATE_CENTS = 150
HEAD_TAX_CENTS_PER_PAX = 1350
HEAD_TAX_VOLUME_TIER_PAX = 3000
HEAD_TAX_VOLUME_DISCOUNT_PCT = 5
PROVISIONING_RATE_CENTS = 4800
WASTE_OFFLOAD_RATE_CENTS = 6200
CONSTRAINED_SURCHARGE_PCT = 10
PAX_PER_OFFICER_HOUR = 60
EMBARK_WINDOW_CAP_HOURS = 8
EMBARK_WINDOW_TAIL_HOURS = 2
TAXI_WINDOW_MINUTES = 15


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def berths_of_terminal(terminal_id):
    return [b for b in db.all_of("berths") if b["terminal_id"] == terminal_id]


def assignments_of_call(call_id):
    return [a for a in db.all_of("berth_assignments") if a["port_call_id"] == call_id]


def live_assignments(call_id):
    """Live = TENTATIVE | CONFIRMED | ACTIVE (SCAFFOLD cascade wording)."""
    return [a for a in assignments_of_call(call_id) if a["status"] in ("TENTATIVE", "CONFIRMED", "ACTIVE")]


def entries_of_call(call_id):
    return [e for e in db.all_of("manifest_entries") if e["port_call_id"] == call_id]


def bags_of_call(call_id):
    return [b for b in db.all_of("baggage_items") if b["port_call_id"] == call_id]


def bags_of_entry(entry_id):
    return [b for b in db.all_of("baggage_items") if b["manifest_entry_id"] == entry_id]


def orders_of_call(call_id):
    return [o for o in db.all_of("service_orders") if o["port_call_id"] == call_id]


def customs_case_of(call_id):
    for c in db.all_of("customs_cases"):
        if c["port_call_id"] == call_id:
            return c
    return None


def provisional_invoice_of(call_id):
    for inv in db.all_of("invoices"):
        if inv["port_call_id"] == call_id and inv["kind"] == "PROVISIONAL":
            return inv
    return None


def final_invoice_of(call_id):
    for inv in db.all_of("invoices"):
        if inv["port_call_id"] == call_id and inv["kind"] == "FINAL":
            return inv
    return None


def draft_provisional_of(call_id):
    inv = provisional_invoice_of(call_id)
    if inv is not None and inv["status"] == "DRAFT":
        return inv
    return None


def terminal_of_call(call):
    return db.get("terminals", call["terminal_id"]) if call else None


# ---------------------------------------------------------------------------
# Terminal posture and berth occupancy (PRD 2.5)
# ---------------------------------------------------------------------------

def posture_of(term):
    """Compute (posture, active_berth_count, occupied_berth_count,
    free_berth_count) at the logical now. Half-open advisory windows
    [start, end); WATCH never gates."""
    now = db.now()
    berths = berths_of_terminal(term["id"])
    active_count = sum(1 for b in berths if b["status"] == "ACTIVE")
    berth_ids = {b["id"] for b in berths}
    occupied = len({
        a["berth_id"]
        for a in db.all_of("berth_assignments")
        if a["berth_id"] in berth_ids and a["status"] == "ACTIVE"
    })
    free = active_count - occupied

    emergency = False
    warning = False
    for adv in db.all_of("weather_advisories"):
        if adv["terminal_id"] != term["id"] or adv["status"] != "ACTIVE":
            continue
        ws = dt_of(adv, "window_start")
        we = dt_of(adv, "window_end")
        if ws <= now < we:
            if adv["severity"] == "EMERGENCY":
                emergency = True
            elif adv["severity"] == "WARNING":
                warning = True

    if emergency:
        posture = "EMERGENCY"
    elif warning or (free == 0 and active_count > 0):
        # PRD 3.1: a terminal with zero active berths starts OPERATIONAL with
        # all counters zero; the zero-free-berth constraint bites only once the
        # terminal has active berths that are all occupied.
        posture = "CONSTRAINED"
    else:
        posture = "OPERATIONAL"
    return posture, active_count, occupied, free


# ---------------------------------------------------------------------------
# Serializers (computed fields injected at read time)
# ---------------------------------------------------------------------------

def serialize_terminal(term):
    posture, active_count, occupied, free = posture_of(term)
    out = db.public(term)
    out["active_berth_count"] = active_count
    out["occupied_berth_count"] = occupied
    out["free_berth_count"] = free
    out["posture"] = posture
    return out


def serialize_call(call):
    out = db.public(call)
    out["passengers_aboard"] = sum(
        1 for e in entries_of_call(call["id"]) if e["status"] == "EMBARKED"
    )
    out["bags_aboard"] = sum(
        1 for b in bags_of_call(call["id"]) if b["status"] == "LOADED"
    )
    return out


def serialize(ent):
    return db.public(ent)


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

def tier_rate(loa_ft):
    """Single non-marginal tier rate in cents per LOA-ft per billed hour."""
    if loa_ft <= TIER1_MAX_LOA_FT:
        return TIER1_RATE_CENTS
    if loa_ft <= TIER2_MAX_LOA_FT:
        return TIER2_RATE_CENTS
    return TIER3_RATE_CENTS


def scheduled_hours(call):
    secs = (dt_of(call, "scheduled_etd") - dt_of(call, "scheduled_eta")).total_seconds()
    return ceil_hours(secs)


def dockage_fee(call, vessel, variant):
    """PROVISIONAL: scheduled times, 10h floor, no overtime/penalty.
    FINAL: pinned five-step evaluation with overtime and late penalty."""
    loa = vessel["loa_ft"]
    rate = tier_rate(loa)
    sched_h = scheduled_hours(call)
    if variant == "PROVISIONAL":
        billed = max(sched_h, DOCKAGE_MIN_BILLED_HOURS)
        return loa * rate * billed
    # FINAL
    actual_secs = (dt_of(call, "actual_etd") - dt_of(call, "actual_eta")).total_seconds()
    actual_h = ceil_hours(actual_secs)
    billed_base = max(actual_h, DOCKAGE_MIN_BILLED_HOURS)
    overtime_h = max(0, billed_base - sched_h)
    base_cents = loa * rate * (billed_base - overtime_h)
    overtime_cents = rhu_div(loa * rate * overtime_h * OVERTIME_MULTIPLIER_NUM, OVERTIME_MULTIPLIER_DEN)
    subtotal = base_cents + overtime_cents
    if dt_of(call, "actual_etd") > dt_of(call, "scheduled_etd"):
        late_penalty = rhu_div(subtotal * LATE_PENALTY_PCT, 100)
    else:
        late_penalty = 0
    return subtotal + late_penalty


def head_tax(call, variant):
    """Per-direction-side discount rounding (pinned mode b): each side's
    discount rounds half-up to whole cents before the sides are summed."""
    if variant == "PROVISIONAL":
        taxable_emb = call["booked_embark_pax"]
        taxable_deb = call["booked_debark_pax"]
    else:
        taxable_emb = sum(
            1 for e in entries_of_call(call["id"])
            if e["direction"] == "EMBARK" and e["status"] == "EMBARKED" and e["cabin_class"] != "CREW"
        )
        taxable_deb = sum(
            1 for e in entries_of_call(call["id"])
            if e["direction"] == "DEBARK"
            and e["status"] in ("DISEMBARKED", "HELD", "CLEARED")
            and e["cabin_class"] != "CREW"
        )
    if taxable_emb + taxable_deb >= HEAD_TAX_VOLUME_TIER_PAX:
        discount_emb = rhu_div(taxable_emb * HEAD_TAX_CENTS_PER_PAX * HEAD_TAX_VOLUME_DISCOUNT_PCT, 100)
        discount_deb = rhu_div(taxable_deb * HEAD_TAX_CENTS_PER_PAX * HEAD_TAX_VOLUME_DISCOUNT_PCT, 100)
        return (taxable_emb * HEAD_TAX_CENTS_PER_PAX - discount_emb) + (
            taxable_deb * HEAD_TAX_CENTS_PER_PAX - discount_deb
        )
    return (taxable_emb + taxable_deb) * HEAD_TAX_CENTS_PER_PAX


def service_fee(call, variant):
    """Per-order-line surcharge rounding (round half-up), then sum."""
    total = 0
    for so in orders_of_call(call["id"]):
        if variant == "PROVISIONAL":
            if so["status"] not in ("APPROVED", "IN_PROGRESS", "COMPLETED"):
                continue
            units = so["units"]
        else:
            if so["status"] != "COMPLETED":
                continue
            units = so["actual_units"] if so["actual_units"] is not None else 0
        rate = PROVISIONING_RATE_CENTS if so["kind"] == "PROVISIONING" else WASTE_OFFLOAD_RATE_CENTS
        line = rate * units
        if so["surcharge_applied"]:
            line = rhu_div(line * (100 + CONSTRAINED_SURCHARGE_PCT), 100)
        total += line
    return total


def compute_invoice_fields(call, variant):
    """Pinned invoice_total evaluation order: dockage, head tax, service fee,
    then gross, then total (adjustments never re-enter the fee steps)."""
    vessel = db.get("vessels", call["vessel_id"])
    dockage = dockage_fee(call, vessel, variant)
    tax = head_tax(call, variant)
    service = service_fee(call, variant)
    gross = dockage + tax + service
    return dockage, tax, service, gross


def recompute_draft_provisional(call_id):
    """Recompute service_fee_cents / gross_cents / total_cents on the call's
    DRAFT PROVISIONAL invoice, if one exists. Derived-value recompute: refresh
    updated_at only, no version bump (PRD 2.6)."""
    inv = draft_provisional_of(call_id)
    if inv is None:
        return
    call = db.get("port_calls", call_id)
    inv["service_fee_cents"] = service_fee(call, "PROVISIONAL")
    inv["gross_cents"] = inv["dockage_fee_cents"] + inv["head_tax_cents"] + inv["service_fee_cents"]
    inv["total_cents"] = inv["gross_cents"] - inv["adjustments_total_cents"]
    db.refresh(inv)


# ---------------------------------------------------------------------------
# Screening staffing requirement (PRD 3.5)
# ---------------------------------------------------------------------------

def screening_requirement(term, call, mode):
    secs = (dt_of(call, "scheduled_etd") - dt_of(call, "scheduled_eta")).total_seconds()
    turnaround_h = floor_hours(secs)
    embark_window_hours = min(EMBARK_WINDOW_CAP_HOURS, max(1, turnaround_h - EMBARK_WINDOW_TAIL_HOURS))
    if mode == "ACTUAL":
        numer = sum(
            1 for e in entries_of_call(call["id"])
            if e["direction"] == "EMBARK" and e["status"] in ("CHECKED_IN", "SCREENED", "EMBARKED")
        )
    else:  # PROJECTION (default)
        numer = call["booked_embark_pax"]
    required = ceil_div(numer, PAX_PER_OFFICER_HOUR * embark_window_hours)
    assigned = sum(
        lane["officers_assigned"]
        for lane in db.all_of("screening_lanes")
        if lane["terminal_id"] == term["id"] and lane["status"] == "OPEN"
    )
    return {
        "required_officers": required,
        "assigned_officers": assigned,
        "embark_window_hours": embark_window_hours,
        "satisfied": assigned >= required,
    }


# ---------------------------------------------------------------------------
# Berth window rules (PRD 3.3)
# ---------------------------------------------------------------------------

def berth_fits(berth, vessel):
    """length_ft >= loa_ft + 30 (equality allowed) and
    max_draft_ft >= draft_ft (equality allowed)."""
    length_ok = berth["length_ft"] >= vessel["loa_ft"] + LOA_SAFETY_MARGIN_FT
    draft_ok = Decimal(str(berth["max_draft_ft"])) >= Decimal(str(vessel["draft_ft"]))
    return length_ok and draft_ok


def window_contains_schedule(asg, call):
    """Assignment window must contain [scheduled_eta, scheduled_etd]:
    window_start <= eta and window_end >= etd (inclusive comparisons)."""
    ws = dt_of(asg, "window_start")
    we = dt_of(asg, "window_end")
    return ws <= dt_of(call, "scheduled_eta") and we >= dt_of(call, "scheduled_etd")


def window_conflict(berth_id, candidate, exclude_id=None):
    """Buffered overlap: candidate conflicts with a same-berth CONFIRMED/ACTIVE
    window [s2, e2) unless the gap on one side is >= BERTH_BUFFER_MINUTES
    (a gap of exactly the buffer is allowed)."""
    buf = timedelta(minutes=BERTH_BUFFER_MINUTES)
    s = dt_of(candidate, "window_start")
    e = dt_of(candidate, "window_end")
    for other in db.all_of("berth_assignments"):
        if other["berth_id"] != berth_id or other["id"] == exclude_id:
            continue
        if other["status"] not in ("CONFIRMED", "ACTIVE"):
            continue
        s2 = dt_of(other, "window_start")
        e2 = dt_of(other, "window_end")
        if (e + buf <= s2) or (s >= e2 + buf):
            continue
        return True
    return False


def order_window_contained(order, call_id):
    """True when the order's requested window is contained in some live
    (TENTATIVE|CONFIRMED|ACTIVE) assignment window of the call."""
    ws = dt_of(order, "window_start")
    we = dt_of(order, "window_end")
    for asg in live_assignments(call_id):
        if dt_of(asg, "window_start") <= ws and dt_of(asg, "window_end") >= we:
            return True
    return False


# ---------------------------------------------------------------------------
# Cascades (PRD 2.10, 3.2, 3.3, 3.5)
# ---------------------------------------------------------------------------

def window_loss_chain(call):
    """Hop 2 + hop 3 of the window-loss chain: service orders in
    REQUESTED|APPROVED whose window is no longer contained in any remaining
    live assignment window -> REJECTED with reject_reason WINDOW_LOST; then
    the DRAFT PROVISIONAL invoice recomputes."""
    lost = False
    for so in orders_of_call(call["id"]):
        if so["status"] in ("REQUESTED", "APPROVED") and not order_window_contained(so, call["id"]):
            so["status"] = "REJECTED"
            so["reject_reason"] = "WINDOW_LOST"
            db.touch(so)
            lost = True
    if lost:
        recompute_draft_provisional(call["id"])


def cascade_confirm_revised(call):
    """DELAYED -> SCHEDULED cascade (PRD 3.2): apply revised times, then
    hop 1: CONFIRMED assignments whose window no longer contains the new
    schedule -> SUPERSEDED; hop 2/3: window-loss chain."""
    call["scheduled_eta"] = call["revised_eta"]
    call["scheduled_etd"] = call["revised_etd"]
    superseded_confirmed = False
    for asg in assignments_of_call(call["id"]):
        if asg["status"] == "CONFIRMED" and not window_contains_schedule(asg, call):
            asg["status"] = "SUPERSEDED"
            db.touch(asg)
            superseded_confirmed = True
    if superseded_confirmed:
        window_loss_chain(call)


def cascade_depart(call):
    """TURNAROUND -> DEPARTED cascade (PRD 3.3): release the ACTIVE berth
    assignment; EMBARK entries in BOOKED/CHECKED_IN/SCREENED -> NO_SHOW;
    DEBARK entries in ABOARD -> CARRIED_AWAY; each newly NO_SHOW entry's bags
    in CHECKED/STAGED (and any still LOADED) -> OFFLOADED."""
    for asg in assignments_of_call(call["id"]):
        if asg["status"] == "ACTIVE":
            asg["status"] = "RELEASED"
            db.touch(asg)
    for entry in entries_of_call(call["id"]):
        if entry["direction"] == "EMBARK" and entry["status"] in ("BOOKED", "CHECKED_IN", "SCREENED"):
            entry["status"] = "NO_SHOW"
            db.touch(entry)
            for bag in bags_of_entry(entry["id"]):
                if bag["status"] in ("CHECKED", "STAGED", "LOADED"):
                    bag["status"] = "OFFLOADED"
                    db.touch(bag)
        elif entry["direction"] == "DEBARK" and entry["status"] == "ABOARD":
            entry["status"] = "CARRIED_AWAY"
            db.touch(entry)


_MANIFEST_TERMINAL = ("EMBARKED", "NO_SHOW", "CLEARED", "CARRIED_AWAY", "CANCELLED")
_BAG_TERMINAL = ("DELIVERED", "OFFLOADED", "CANCELLED")


def cascade_cancel(call):
    """Cancel compensation cascade (PRD 3.2)."""
    for asg in assignments_of_call(call["id"]):
        if asg["status"] in ("TENTATIVE", "CONFIRMED"):
            asg["status"] = "SUPERSEDED"
            db.touch(asg)
    for so in orders_of_call(call["id"]):
        if so["status"] in ("REQUESTED", "APPROVED"):
            so["status"] = "CANCELLED"
            db.touch(so)
    for slot in db.all_of("transport_slots"):
        if slot["port_call_id"] == call["id"] and slot["status"] == "QUEUED":
            slot["status"] = "EXPIRED"
            db.touch(slot)
    inv = provisional_invoice_of(call["id"])
    if inv is not None and inv["status"] in ("DRAFT", "ISSUED"):
        inv["status"] = "CANCELLED"
        db.touch(inv)
    for entry in entries_of_call(call["id"]):
        if entry["status"] not in _MANIFEST_TERMINAL:
            entry["status"] = "CANCELLED"
            db.touch(entry)
    for bag in bags_of_call(call["id"]):
        if bag["status"] not in _BAG_TERMINAL:
            bag["status"] = "CANCELLED"
            db.touch(bag)


def cascade_customs_hold(case):
    """CustomsCase FILED -> HELD: DEBARK entries of the call currently
    DISEMBARKED -> HELD."""
    for entry in entries_of_call(case["port_call_id"]):
        if entry["direction"] == "DEBARK" and entry["status"] == "DISEMBARKED":
            entry["status"] = "HELD"
            db.touch(entry)


# ---------------------------------------------------------------------------
# Transport dispatch window (PRD 3.9)
# ---------------------------------------------------------------------------

def current_dispatch_window_start():
    """Start of the 15-minute window containing the logical now."""
    now = db.now()
    return now.replace(minute=(now.minute // TAXI_WINDOW_MINUTES) * TAXI_WINDOW_MINUTES,
                       second=0, microsecond=0)


def dispatched_in_window(terminal_id, window_start_iso):
    """Slots consuming capacity in the window: dispatched here and now in
    DISPATCHED | COMPLETED | NO_SHOW (QUEUED/EXPIRED consume nothing)."""
    return sum(
        1 for s in db.all_of("transport_slots")
        if s["terminal_id"] == terminal_id
        and s["dispatch_window_start"] == window_start_iso
        and s["status"] in ("DISPATCHED", "COMPLETED", "NO_SHOW")
    )


# ---------------------------------------------------------------------------
# Operations checkpoint sweep (PRD 3.4)
# ---------------------------------------------------------------------------

def run_ops_sweep(term):
    """Expire time-lapsed records against the logical now, then bump
    ops_run_index and the terminal version."""
    now = db.now()
    for adv in db.all_of("weather_advisories"):
        if adv["terminal_id"] == term["id"] and adv["status"] == "ACTIVE":
            if dt_of(adv, "window_end") <= now:
                adv["status"] = "EXPIRED"
                db.touch(adv)
    berth_ids = {b["id"] for b in berths_of_terminal(term["id"])}
    for asg in db.all_of("berth_assignments"):
        if asg["berth_id"] in berth_ids and asg["status"] == "TENTATIVE":
            if dt_of(asg, "window_start") <= now:
                asg["status"] = "EXPIRED"
                db.touch(asg)
    for slot in db.all_of("transport_slots"):
        if slot["terminal_id"] == term["id"] and slot["status"] == "QUEUED":
            call = db.get("port_calls", slot["port_call_id"])
            if call is not None and call["status"] in ("DEPARTED", "CLOSED", "CANCELLED"):
                slot["status"] = "EXPIRED"
                db.touch(slot)
    term["ops_run_index"] = term.get("ops_run_index", 0) + 1
    db.touch(term)
