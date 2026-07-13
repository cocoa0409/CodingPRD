"""Core domain logic for the Marina Mooring Permit API.

In-memory only. No seeding. Fresh state on every process start.
"""
import math
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD calculations / PRD)
# ---------------------------------------------------------------------------
SLIP_RATE_CENTS_PER_FT = 4000
MOORING_RATE_CENTS_PER_FT = 2500
NON_RESIDENT_MULT = "1.75"
LIVEABOARD_SURCHARGE_CENTS = 50000

NOTICE_FEE_CENTS = 15000
TOW_FEE_CENTS = 40000
STORAGE_PER_DAY_CENTS = 3000

RAMP_SEASONAL_RESIDENT_CENTS = 8000
RAMP_SEASONAL_NONRESIDENT_CENTS = 20000
RAMP_DAY_RESIDENT_CENTS = 1000
RAMP_DAY_NONRESIDENT_CENTS = 3000

OFFER_TTL_DAYS = 7
CLAIM_TTL_DAYS = 14
TRANSFER_FEE_CENTS = 5000

DEFAULT_PUMPOUT_INTERVAL_DAYS = 30
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.marinas = {}
        self.berths = {}
        self.boaters = {}
        self.vessels = {}
        self.permits = {}
        self.pumpouts = {}
        self.derelicts = {}
        self.ramppasses = {}
        self.rounds = {}
        self.entries = {}
        self.invoices = {}
        self._seq = 0
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def reset_store():
    global store
    store = Store()


def clock():
    return store.clock


# ---------------------------------------------------------------------------
# Time / formatting helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    if isinstance(s, datetime):
        return s
    s2 = str(s).strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        dt = datetime.fromisoformat(s2 + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_date(s):
    return parse_dt(s).date()


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(datetime.now(timezone.utc))


def gen_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def base_common():
    ts = now_iso()
    return {
        "id": gen_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity, computed=None):
    out = {k: v for k, v in entity.items() if not k.startswith("_")}
    if computed:
        out.update(computed)
    return out


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def money_mult(cents, mult_str):
    return int((Decimal(cents) * Decimal(mult_str)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def prorate(cents, remaining, season):
    if season <= 0:
        return 0
    return int((Decimal(cents) * Decimal(remaining) / Decimal(season)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Vessel computed fields
# ---------------------------------------------------------------------------
def vessel_last_pumpout(v):
    recs = [r for r in store.pumpouts.values() if r["vessel_id"] == v["id"]]
    if not recs:
        return None
    recs.sort(key=lambda r: (to_date(r["pumpout_date"]), r["_seq"]))
    return recs[-1]["pumpout_date"]


def vessel_reg_status(v):
    if v.get("_revoked"):
        return "REVOKED"
    if clock().date() > to_date(v["registration_expiry_date"]):
        return "EXPIRED"
    return "REGISTERED"


def _pick_permit_for_vessel(v):
    perms = [p for p in store.permits.values() if p["vessel_id"] == v["id"]]
    if not perms:
        return None
    active = [p for p in perms if p["status"] in ("ACTIVE", "SUSPENDED")]
    if active:
        active.sort(key=lambda p: p["_seq"])
        return active[0]
    perms.sort(key=lambda p: p["_seq"])
    return perms[-1]


def _pumpout_interval_and_base(v, permit=None):
    interval = DEFAULT_PUMPOUT_INTERVAL_DAYS
    p = permit or _pick_permit_for_vessel(v)
    activated = None
    if p is not None:
        m = store.marinas.get(p["marina_id"])
        if m is not None:
            interval = m.get("pumpout_interval_days", DEFAULT_PUMPOUT_INTERVAL_DAYS)
        activated = p.get("activated_on_date")
    last = vessel_last_pumpout(v)
    if last:
        base = to_date(last)
    elif activated:
        base = to_date(activated)
    else:
        base = to_date(v["created_at"])
    return interval, base


def vessel_pumpout_status(v):
    if not v.get("has_holding_tank"):
        return "NA"
    interval, base = _pumpout_interval_and_base(v)
    days = (clock().date() - base).days
    return "OVERDUE" if days > interval else "COMPLIANT"


def days_since_pumpout(v, permit):
    _, base = _pumpout_interval_and_base(v, permit)
    return (clock().date() - base).days


def serialize_vessel(v):
    return serialize(v, {
        "last_pumpout_date": vessel_last_pumpout(v),
        "registration_status": vessel_reg_status(v),
        "pumpout_status": vessel_pumpout_status(v),
    })


# ---------------------------------------------------------------------------
# Marina occupancy recompute
# ---------------------------------------------------------------------------
def recompute_marina(m):
    mid = m["id"]
    berths = [b for b in store.berths.values() if b["marina_id"] == mid]
    perms = [p for p in store.permits.values() if p["marina_id"] == mid]
    new = {
        "available_slip_count": sum(1 for b in berths if b["berth_type"] == "SLIP" and b["status"] == "AVAILABLE"),
        "occupied_slip_count": sum(1 for b in berths if b["berth_type"] == "SLIP" and b["status"] == "OCCUPIED"),
        "available_mooring_count": sum(1 for b in berths if b["berth_type"] == "MOORING" and b["status"] == "AVAILABLE"),
        "occupied_mooring_count": sum(1 for b in berths if b["berth_type"] == "MOORING" and b["status"] == "OCCUPIED"),
        "liveaboard_count": sum(1 for p in perms if p["status"] == "ACTIVE" and p.get("is_liveaboard")),
        "waitlist_length": sum(1 for p in perms if p["status"] == "WAITLISTED"),
    }
    changed = any(m.get(k) != val for k, val in new.items())
    m.update(new)
    if changed:
        touch(m)


# ---------------------------------------------------------------------------
# Invoice helper
# ---------------------------------------------------------------------------
def issue_invoice(invoice_type, reference_id, boater_id, amount_due_cents, due_date):
    inv = base_common()
    inv.update({
        "boater_id": boater_id,
        "invoice_type": invoice_type,
        "reference_id": reference_id,
        "amount_due_cents": amount_due_cents,
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "due_date": due_date,
        "status": "UNPAID",
    })
    store.invoices[inv["id"]] = inv
    return inv


# ---------------------------------------------------------------------------
# Fee calculations
# ---------------------------------------------------------------------------
def permit_fee_components(permit):
    v = store.vessels[permit["vessel_id"]]
    rate = SLIP_RATE_CENTS_PER_FT if permit["requested_berth_type"] == "SLIP" else MOORING_RATE_CENTS_PER_FT
    length_component = rate * math.ceil(v["length_ft"])
    mult = "1.00" if permit["fee_basis"] == "RESIDENT" else NON_RESIDENT_MULT
    length_scaled = money_mult(length_component, mult)
    live = LIVEABOARD_SURCHARGE_CENTS if permit.get("is_liveaboard") else 0
    return length_scaled, live


def compute_provisional_fee(permit):
    length_scaled, live = permit_fee_components(permit)
    return length_scaled + live


def compute_final_fee(permit):
    length_scaled, live = permit_fee_components(permit)
    ss = to_date(permit["season_start_date"])
    se = to_date(permit["season_end_date"])
    season_days = (se - ss).days + 1
    activated = to_date(permit["activated_on_date"])
    remaining = (se - activated).days + 1
    length_prorated = prorate(length_scaled, remaining, season_days)
    live_prorated = prorate(live, remaining, season_days)
    return length_prorated + live_prorated


def refund_on_revoke(permit, inv):
    ss = to_date(permit["season_start_date"])
    se = to_date(permit["season_end_date"])
    season_days = (se - ss).days + 1
    remaining = max((se - clock().date()).days + 1, 0)
    net = inv["amount_paid_cents"] - inv["amount_refunded_cents"]
    refund = prorate(net, remaining, season_days) if net > 0 else 0
    if refund > 0:
        inv["amount_refunded_cents"] += refund
        if inv["amount_paid_cents"] - inv["amount_refunded_cents"] == 0:
            inv["status"] = "REFUNDED"
        else:
            inv["status"] = "PARTIALLY_REFUNDED"
        touch(inv)
    return refund


def ramp_pass_fee(pass_type, fee_basis):
    if pass_type == "SEASONAL" and fee_basis == "RESIDENT":
        return RAMP_SEASONAL_RESIDENT_CENTS
    if pass_type == "SEASONAL" and fee_basis == "NON_RESIDENT":
        return RAMP_SEASONAL_NONRESIDENT_CENTS
    if pass_type == "DAY" and fee_basis == "RESIDENT":
        return RAMP_DAY_RESIDENT_CENTS
    return RAMP_DAY_NONRESIDENT_CENTS


# ---------------------------------------------------------------------------
# Berth / permit offer & promotion
# ---------------------------------------------------------------------------
def offer_permit(permit, berth):
    """Reserve berth and issue a provisional PERMIT invoice; permit -> OFFERED."""
    permit["berth_id"] = berth["id"]
    berth["status"] = "RESERVED"
    berth["current_permit_id"] = permit["id"]
    touch(berth)
    prov = compute_provisional_fee(permit)
    permit["provisional_fee_cents"] = prov
    permit["status"] = "OFFERED"
    permit["offer_expires_at"] = iso(clock() + timedelta(days=OFFER_TTL_DAYS))
    inv = issue_invoice("PERMIT", permit["id"], permit["boater_id"], prov, permit["offer_expires_at"])
    permit["invoice_id"] = inv["id"]
    touch(permit)
    m = store.marinas.get(permit["marina_id"])
    if m:
        recompute_marina(m)


def waitlist_candidates(berth):
    mid = berth["marina_id"]
    cands = []
    for p in store.permits.values():
        if p["status"] != "WAITLISTED":
            continue
        if p["marina_id"] != mid:
            continue
        if p["requested_berth_type"] != berth["berth_type"]:
            continue
        if p["requested_size_class"] != berth["size_class"]:
            continue
        v = store.vessels.get(p["vessel_id"])
        if v is None or v["length_ft"] > berth["max_length_ft"]:
            continue
        if berth.get("resident_only") and p["fee_basis"] != "RESIDENT":
            continue
        cands.append(p)
    cands.sort(key=lambda p: (p["priority_tier"], p["_seq"]))
    return cands


def waitlist_promotion(berth):
    """A berth just became AVAILABLE: promote the top-ranked eligible waitlisted permit."""
    if berth["status"] != "AVAILABLE":
        return None
    cands = waitlist_candidates(berth)
    if not cands:
        return None
    winner = cands[0]
    offer_permit(winner, berth)
    return winner


def free_berth(berth):
    berth["status"] = "AVAILABLE"
    berth["current_permit_id"] = None
    touch(berth)
    m = store.marinas.get(berth["marina_id"])
    if m:
        recompute_marina(m)
    waitlist_promotion(berth)


# ---------------------------------------------------------------------------
# Season overlap
# ---------------------------------------------------------------------------
def season_overlap_conflict(berth_id, permit):
    """Half-open [start,end) overlap among ACTIVE/OFFERED/SUSPENDED permits on berth."""
    a_start = to_date(permit["season_start_date"])
    a_end = to_date(permit["season_end_date"])
    for p in store.permits.values():
        if p["id"] == permit["id"]:
            continue
        if p.get("berth_id") != berth_id:
            continue
        if p["status"] not in ("ACTIVE", "OFFERED", "SUSPENDED"):
            continue
        b_start = to_date(p["season_start_date"])
        b_end = to_date(p["season_end_date"])
        if a_start < b_end and b_start < a_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Activation (shared by pay & waive of PERMIT invoice)
# ---------------------------------------------------------------------------
def check_activation(permit):
    v = store.vessels[permit["vessel_id"]]
    if vessel_reg_status(v) != "REGISTERED":
        raise ApiError("ERR_VESSEL_REGISTRATION_EXPIRED", 422, "Vessel registration is not current")
    if season_overlap_conflict(permit["berth_id"], permit):
        raise ApiError("ERR_BERTH_SEASON_CONFLICT", 409, "Berth already occupied for an overlapping season")
    if permit.get("is_liveaboard"):
        m = store.marinas[permit["marina_id"]]
        if m["liveaboard_count"] >= m["liveaboard_cap"]:
            raise ApiError("ERR_LIVEABOARD_LIMIT_REACHED", 422, "Liveaboard cap reached")


def activate_permit(permit, invoice, via_waive):
    berth = store.berths[permit["berth_id"]]
    berth["status"] = "OCCUPIED"
    touch(berth)
    permit["activated_on_date"] = iso(clock())
    permit["offer_expires_at"] = None
    permit["final_fee_cents"] = compute_final_fee(permit)
    permit["status"] = "ACTIVE"
    touch(permit)
    if not via_waive and invoice["status"] == "PAID":
        refund = permit["provisional_fee_cents"] - permit["final_fee_cents"]
        if refund > 0:
            invoice["amount_refunded_cents"] += refund
            if invoice["amount_paid_cents"] - invoice["amount_refunded_cents"] == 0:
                invoice["status"] = "REFUNDED"
            else:
                invoice["status"] = "PARTIALLY_REFUNDED"
            touch(invoice)
    m = store.marinas.get(permit["marina_id"])
    if m:
        recompute_marina(m)


# ---------------------------------------------------------------------------
# Permit revoke (shared by revoke endpoint and derelict impound cascade)
# ---------------------------------------------------------------------------
def revoke_permit(permit):
    inv = store.invoices.get(permit.get("invoice_id")) if permit.get("invoice_id") else None
    if inv is not None and inv["status"] in ("PAID", "PARTIALLY_REFUNDED"):
        refund_on_revoke(permit, inv)
    permit["status"] = "REVOKED"
    touch(permit)
    berth = store.berths.get(permit.get("berth_id"))
    if berth is not None:
        free_berth(berth)
    else:
        m = store.marinas.get(permit["marina_id"])
        if m:
            recompute_marina(m)


# ---------------------------------------------------------------------------
# Lottery draw
# ---------------------------------------------------------------------------
def run_lottery_draw(rnd):
    entries = [e for e in store.entries.values() if e["round_id"] == rnd["id"] and e["status"] == "ENTERED"]
    eligible = []
    ineligible = []
    for e in entries:
        v = store.vessels.get(e["vessel_id"])
        if v is not None and vessel_reg_status(v) == "REGISTERED":
            eligible.append(e)
        else:
            ineligible.append(e)
    eligible.sort(key=lambda e: (e["priority_tier"], e["draw_number"]))
    k = len(rnd["berth_ids"])
    winners = eligible[:k]
    losers = eligible[k:]
    deadline = iso(clock() + timedelta(days=CLAIM_TTL_DAYS))
    for i, e in enumerate(winners):
        e["status"] = "WON"
        e["awarded_berth_id"] = rnd["berth_ids"][i]
        e["claim_deadline"] = deadline
        touch(e)
    for e in losers + ineligible:
        e["status"] = "LOST"
        touch(e)
    rnd["status"] = "DRAWN"
    rnd["drawn_on_date"] = iso(clock())
    touch(rnd)


# ---------------------------------------------------------------------------
# Derelict cost
# ---------------------------------------------------------------------------
def derelict_actual_cost(report):
    storage_days = (to_date(report["closed_date"]) - to_date(report["notice_served_date"])).days
    storage_days = max(storage_days, 0)
    return NOTICE_FEE_CENTS + TOW_FEE_CENTS + STORAGE_PER_DAY_CENTS * storage_days


# ---------------------------------------------------------------------------
# Maintenance sweep
# ---------------------------------------------------------------------------
def run_maintenance(marina):
    mid = marina["id"]
    now = clock().date()

    # 1. Expire ACTIVE/SUSPENDED permits past season_end
    perms = sorted(
        [p for p in store.permits.values()
         if p["marina_id"] == mid and p["status"] in ("ACTIVE", "SUSPENDED")],
        key=lambda p: p["_seq"])
    for p in perms:
        if now > to_date(p["season_end_date"]):
            p["status"] = "EXPIRED"
            touch(p)
            berth = store.berths.get(p.get("berth_id"))
            if berth is not None:
                free_berth(berth)

    # 2. Decline OFFERED permits past offer_expires_at
    perms = sorted(
        [p for p in store.permits.values()
         if p["marina_id"] == mid and p["status"] == "OFFERED"],
        key=lambda p: p["_seq"])
    for p in perms:
        oea = p.get("offer_expires_at")
        if oea and now > to_date(oea):
            p["status"] = "DECLINED"
            touch(p)
            inv = store.invoices.get(p.get("invoice_id")) if p.get("invoice_id") else None
            if inv is not None and inv["status"] == "UNPAID":
                inv["status"] = "VOID"
                touch(inv)
            berth = store.berths.get(p.get("berth_id"))
            if berth is not None:
                free_berth(berth)

    # 3. Suspend ACTIVE permits whose vessel pump-out is OVERDUE
    perms = sorted(
        [p for p in store.permits.values()
         if p["marina_id"] == mid and p["status"] == "ACTIVE"],
        key=lambda p: p["_seq"])
    for p in perms:
        v = store.vessels.get(p["vessel_id"])
        if v is None or not v.get("has_holding_tank"):
            continue
        if days_since_pumpout(v, p) > marina.get("pumpout_interval_days", DEFAULT_PUMPOUT_INTERVAL_DAYS):
            p["status"] = "SUSPENDED"
            touch(p)
    recompute_marina(marina)

    # 4. Forfeit WON lottery entries past claim_deadline
    entries = sorted(
        [e for e in store.entries.values() if e["status"] == "WON"],
        key=lambda e: e["_seq"])
    for e in entries:
        rnd = store.rounds.get(e["round_id"])
        if rnd is None or rnd["marina_id"] != mid:
            continue
        cd = e.get("claim_deadline")
        if cd and now > to_date(cd):
            e["status"] = "FORFEITED"
            touch(e)
            berth = store.berths.get(e.get("awarded_berth_id"))
            if berth is not None and berth["status"] != "AVAILABLE":
                free_berth(berth)

    # 5. Expire ACTIVE ramp passes past valid_to_date
    passes = sorted(
        [rp for rp in store.ramppasses.values() if rp["status"] == "ACTIVE"],
        key=lambda rp: rp["_seq"])
    for rp in passes:
        if now > to_date(rp["valid_to_date"]):
            rp["status"] = "EXPIRED"
            touch(rp)

    # 6. Close DRAWN rounds when no WON entries remain
    rounds = sorted(
        [r for r in store.rounds.values() if r["marina_id"] == mid and r["status"] == "DRAWN"],
        key=lambda r: r["_seq"])
    for r in rounds:
        remaining_won = any(
            e["round_id"] == r["id"] and e["status"] == "WON" for e in store.entries.values())
        if not remaining_won:
            r["status"] = "CLOSED"
            touch(r)

    recompute_marina(marina)
