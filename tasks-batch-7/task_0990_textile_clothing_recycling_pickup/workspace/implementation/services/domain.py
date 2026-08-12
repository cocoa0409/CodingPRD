"""Domain helpers: serializers, computed views, cascades, shared checks."""
from datetime import timedelta
from decimal import Decimal

from db import store, touch, now_dt
from errors import fail
from services import calc


# ---------------------------------------------------------------- serializers
def pub(rec):
    """Strip internal underscore-prefixed fields for output."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def zone_view(z):
    return pub(z)


def resident_view(r):
    out = pub(r)
    out["credit_balance_cents"] = sum(
        c.get("resident_share_cents") or 0
        for c in store.credits.values()
        if c.get("beneficiary_resident_id") == r["id"] and c["status"] == "SETTLED"
    )
    return out


def kit_view(k):
    return pub(k)


def pickup_view(p):
    return pub(p)


def partner_amounts(pid):
    committed = Decimal("0")
    completed = Decimal("0")
    for a in store.assignments.values():
        if a["partner_id"] != pid:
            continue
        if a["status"] == "ACCEPTED":
            committed += calc.dec(a["assigned_weight_kg"])
        elif a["status"] == "COMPLETED":
            completed += calc.dec(a["assigned_weight_kg"])
    return committed, completed


def partner_view(p, recompute=True):
    out = pub(p)
    committed, completed = partner_amounts(p["id"])
    capacity = calc.dec(p["capacity_kg"])
    out["committed_kg"] = calc.num_out(committed)
    out["completed_kg"] = calc.num_out(completed)
    out["remaining_kg"] = calc.num_out(capacity - committed - completed)
    if recompute:
        routing, report = calc.partner_scores(p["id"], now_dt())
        out["routing_score"] = routing
        out["report_score"] = report
    return out


def assignment_view(a):
    return pub(a)


def dropbox_view(b):
    return pub(b)


def reading_view(r):
    return pub(r)


def ticket_view(t):
    return pub(t)


def credit_view(c):
    return pub(c)


def fund_amounts(fid):
    held = sum(c["gross_cents"] for c in store.credits.values()
               if c.get("fund_id") == fid and c.get("has_hold") and c.get("gross_cents") is not None)
    paid = sum(c["gross_cents"] for c in store.credits.values()
               if c.get("fund_id") == fid and c["status"] == "SETTLED"
               and c.get("gross_cents") is not None)
    return held, paid


def fund_view(f):
    out = pub(f)
    held, paid = fund_amounts(f["id"])
    out["held_cents"] = held
    out["paid_cents"] = paid
    out["available_cents"] = f["funded_total_cents"] - held - paid
    return out


def charity_view(ch):
    out = pub(ch)
    out["total_received_cents"] = charity_total(ch["id"])
    return out


def charity_total(charity_id):
    total = 0
    for c in store.credits.values():
        if c["status"] != "SETTLED":
            continue
        for line in c.get("charity_allocations") or []:
            if line["charity_id"] == charity_id:
                total += line["amount_cents"]
    return total


def report_view(r):
    return pub(r)


def period_view(p):
    return pub(p)


# ------------------------------------------------------------------ resolvers
def zone_id_of_ticket(ticket):
    if ticket["source_type"] == "PICKUP_REQUEST":
        pickup = store.pickups.get(ticket["source_id"])
        if not pickup:
            return None
        resident = store.residents.get(pickup["resident_id"])
        return resident["zone_id"] if resident else None
    box = store.dropboxes.get(ticket["source_id"])
    return box["zone_id"] if box else None


def ticket_resident_id(ticket):
    if ticket["source_type"] != "PICKUP_REQUEST":
        return None
    pickup = store.pickups.get(ticket["source_id"])
    return pickup["resident_id"] if pickup else None


def get_or_404(table, rid, label="Resource"):
    rec = table.get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", "%s not found: %s" % (label, rid))
    return rec


# --------------------------------------------------------------- shared checks
def check_window_shape(ws, we):
    """ERR_INVALID_WINDOW unless end > start and duration in [60, 240] minutes."""
    if not (we > ws):
        fail("ERR_INVALID_WINDOW", "window_end must be after window_start")
    minutes = (we - ws).total_seconds() / 60.0
    if minutes < 60 or minutes > 240:
        fail("ERR_INVALID_WINDOW", "window duration must be between 60 and 240 minutes")


def check_window_not_past(ws):
    if ws < now_dt():
        fail("ERR_WINDOW_IN_PAST", "window_start is before the current time")


def check_window_conflict(resident_id, ws, we, exclude_id=None):
    """Buffered overlap vs other SCHEDULED/ROUTED pickups (30-minute buffer)."""
    buf = timedelta(minutes=30)
    for p in store.pickups.values():
        if p["resident_id"] != resident_id or p["id"] == exclude_id:
            continue
        if p["status"] not in ("SCHEDULED", "ROUTED"):
            continue
        if ws < p["_we"] + buf and p["_ws"] < we + buf:
            fail("ERR_PICKUP_WINDOW_CONFLICT", "window conflicts with another pickup")


def open_report_on_ticket(ticket_id):
    for r in store.reports.values():
        if r["ticket_id"] == ticket_id and r["status"] == "OPEN":
            return r
    return None


def live_credit_on_ticket(ticket_id):
    """The non-VOIDED credit on a ticket, if any."""
    for c in store.credits.values():
        if c["ticket_id"] == ticket_id and c["status"] != "VOIDED":
            return c
    return None


def settled_credit_on_ticket(ticket_id):
    for c in store.credits.values():
        if c["ticket_id"] == ticket_id and c["status"] == "SETTLED":
            return c
    return None


def active_fund_for_zone(zone_id):
    for f in store.funds.values():
        if f["zone_id"] == zone_id and f["status"] == "ACTIVE":
            return f
    return None


# ------------------------------------------------------------------- cascades
def recompute_ticket_severity(ticket):
    ups = [r for r in store.reports.values()
           if r["ticket_id"] == ticket["id"] and r.get("outcome") == "UPHELD"]
    best = "NONE"
    for r in ups:
        if calc.SEVERITY_ORDER[r["severity"]] > calc.SEVERITY_ORDER[best]:
            best = r["severity"]
    if ticket["highest_upheld_severity"] != best:
        ticket["highest_upheld_severity"] = best


def apply_partner_score_transitions(partner, now):
    """ELIGIBLE<->SUSPENDED flips from a routing_score recompute (never QUARANTINED)."""
    routing, _ = calc.partner_scores(partner["id"], now)
    if partner["status"] == "ELIGIBLE" and routing < calc.SCORE_FLOOR:
        partner["status"] = "SUSPENDED"
        touch(partner)
    elif partner["status"] == "SUSPENDED" and routing >= calc.SCORE_FLOOR:
        partner["status"] = "ELIGIBLE"
        touch(partner)


def apply_strike(resident):
    """resident_strike_accumulation + suspension cascade."""
    resident["strikes"] += 1
    if resident["strikes"] >= calc.STRIKE_LIMIT and resident["status"] == "ACTIVE":
        resident["status"] = "SUSPENDED"
        for p in store.pickups.values():
            if p["resident_id"] == resident["id"] and p["status"] == "SCHEDULED":
                p["status"] = "CANCELLED"
                touch(p)
    touch(resident)


def void_credit_record(credit):
    """Credit -> VOIDED with hold release (hold is derived from has_hold flag)."""
    credit["status"] = "VOIDED"
    credit["has_hold"] = False
    touch(credit)


def decline_pending_assignments(ticket_id):
    for a in store.assignments.values():
        if a["ticket_id"] == ticket_id and a["status"] == "PENDING":
            a["status"] = "DECLINED"
            a["decline_reason"] = "SYSTEM_QUARANTINE"
            touch(a)


def quarantine_ticket(ticket):
    """CERTIFIED -> QUARANTINED cascade (SCAFFOLD WeightTicket machine)."""
    ticket["status"] = "QUARANTINED"
    touch(ticket)
    for c in store.credits.values():
        if c["ticket_id"] == ticket["id"] and c["status"] in ("PROVISIONAL", "DISPUTED", "FINALIZED"):
            void_credit_record(c)
    decline_pending_assignments(ticket["id"])
    partner_ids = {a["partner_id"] for a in store.assignments.values()
                   if a["ticket_id"] == ticket["id"] and a["status"] in ("ACCEPTED", "COMPLETED")}
    for pid in partner_ids:
        partner = store.partners.get(pid)
        if partner and partner["status"] in ("ELIGIBLE", "SUSPENDED"):
            partner["status"] = "QUARANTINED"
            touch(partner)


def recompute_box_posture(box):
    """dropbox_fill_posture: latest reading by recorded_at (tie: created_at/seq)."""
    readings = [r for r in store.readings.values() if r["dropbox_id"] == box["id"]]
    if not readings:
        box["fill_pct"] = 0
        box["posture"] = "OK"
        return
    latest = max(readings, key=lambda r: (r["_recorded_at"], r["created_at"], r["_seq"]))
    box["fill_pct"] = latest["fill_pct"]
    box["posture"] = calc.posture_for(latest["fill_pct"])


def routing_selector(ticket):
    """Run the partner selector for a CERTIFIED ticket. Returns chosen partner."""
    now = now_dt()
    # recompute routing_score for ALL partners and apply status transitions
    for p in store.partners.values():
        apply_partner_score_transitions(p, now)
    certified = calc.dec(ticket["certified_weight_kg"])
    pool = []
    for p in store.partners.values():
        if p["status"] != "ELIGIBLE":
            continue
        if ticket["grade"] not in p["accepted_grades"]:
            continue
        committed, completed = partner_amounts(p["id"])
        remaining = calc.dec(p["capacity_kg"]) - committed - completed
        if remaining < certified:
            continue
        declined = any(a["ticket_id"] == ticket["id"] and a["partner_id"] == p["id"]
                       and a["status"] == "DECLINED" for a in store.assignments.values())
        if declined:
            continue
        routing, _ = calc.partner_scores(p["id"], now)
        pool.append((p, routing))
    pool.sort(key=lambda item: (-item[1], item[0]["created_at"], item[0]["_seq"]))
    if not pool:
        fail("ERR_NO_ELIGIBLE_PARTNER", "No eligible partner for this ticket")
    return pool[0][0]
