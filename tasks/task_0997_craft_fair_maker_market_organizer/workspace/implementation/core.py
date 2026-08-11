"""Core helpers: in-memory store, auth, envelope, clock, calculations, domain ops."""
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

VALID_ROLES = ("EventCoordinator", "Vendor", "Juror", "Treasurer", "GateAgent", "PlatformAdmin")

POSTURES = [
    "PLANNING", "APPLICATION_OPEN", "JURY_REVIEW", "SCHEDULING", "LIVE",
    "WEATHER_HOLD", "SETTLEMENT", "CLOSED", "CANCELLED",
]
TERMINAL_POSTURES = ("CLOSED", "CANCELLED")
PRE_LIVE_POSTURES = ("PLANNING", "APPLICATION_OPEN", "JURY_REVIEW", "SCHEDULING")

WEATHER_FLAGS = ("CLEAR", "ADVISORY", "SEVERE")
ZONE_EXPOSURES = ("INDOOR", "COVERED", "OPEN_AIR")
CATEGORIES = ("CERAMICS", "TEXTILES", "JEWELRY", "WOODWORK", "FOOD", "MIXED")
TIERS = ("STANDARD", "CORNER", "ANCHOR")
SLOT_KINDS = ("LOAD_IN", "LOAD_OUT")
BAYS = ("NORTH", "SOUTH")
TICKET_KINDS = ("GA", "EARLY_BIRD", "VIP")
DECIDE_OUTCOMES = ("APPROVE", "WAITLIST", "REJECT")

TIER_MULT = {"STANDARD": Decimal("1.00"), "CORNER": Decimal("1.25"), "ANCHOR": Decimal("1.60")}
CATEGORY_UPLIFT = {"FOOD": Decimal("0.10"), "MIXED": Decimal("0.05")}
COMMISSION_THRESHOLD = 100_000  # cents
COMMISSION_BUMP = Decimal("0.02")
PAYMENT_WINDOW = timedelta(hours=72)

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

APP_TERMINAL_STATUSES = ("REJECTED", "WITHDRAWN", "CANCELLED", "CONFIRMED")
ASSIGNMENT_OPEN_STATUSES = ("PENDING_PAYMENT", "ACTIVE")


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


class Store:
    def __init__(self):
        self.events = {}
        self.zones = {}
        self.booths = {}
        self.vendors = {}
        self.applications = {}
        self.jury_scores = {}
        self.assignments = {}
        self.charges = {}
        self.slots = {}
        self.tickets = {}
        self.attendance = {}
        self.sales = {}
        self.settlements = {}
        self.clock = DEFAULT_CLOCK
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()

# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------


def parse_dt(value):
    """Parse an ISO8601 string to an aware UTC datetime. None on failure."""
    if not isinstance(value, str):
        return None
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    return fmt_ts(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def req_meta():
    return {
        "api_request_id": "req_" + "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
        ),
        "api_request_timestamp": wall_now_iso(),
    }


def ok(data, code=200):
    return jsonify({"meta": req_meta(), "response_type": "object", "data": data}), code


def _pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def ok_list(recs, code=200):
    limit, offset = _pagination()
    total = len(recs)
    page = recs[offset:offset + limit]
    m = req_meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": m, "response_type": "array", "data": page}), code


def err_response(e):
    return jsonify({
        "meta": req_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip() \
            or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH", 400,
                       "X-User-ID and X-User-Role headers are required and must be well-formed.")
    return uid, role


def require(role, *allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role %s is not permitted for this endpoint." % role)


def body():
    return request.get_json(silent=True) or {}


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------


def stamp(rec):
    now = fmt_ts(store.clock)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def stamp_light(rec):
    """JuryScore / Attendance / SalesLedgerEntry: id + created_at only."""
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = fmt_ts(store.clock)
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = fmt_ts(store.clock)
    rec["version"] += 1


def by_created(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_or_404(table, rid, label="Resource"):
    rec = getattr(store, table).get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found: %s" % (label, rid))
    return rec


def apply_filters(recs, mapping):
    out = list(recs)
    for param, key in mapping.items():
        v = request.args.get(param)
        if v is not None:
            if v.lower() == "true":
                want = True
            elif v.lower() == "false":
                want = False
            else:
                want = v
            out = [r for r in out if r.get(key) == want or str(r.get(key)) == v]
    return out


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def invalid(msg):
    raise ApiError("ERR_INVALID_INPUT", 400, msg)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        invalid("Field '%s' must be a non-empty string." % field)
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        invalid("Field '%s' must be an integer." % field)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        invalid("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return v


def req_dt(data, field):
    v = data.get(field)
    dt = parse_dt(v)
    if dt is None:
        invalid("Field '%s' must be an ISO 8601 datetime string." % field)
    return dt


def req_pct(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid("Field '%s' must be a number." % field)
    d = Decimal(str(v))
    if d < 0 or d > 25:
        invalid("Field '%s' must be between 0 and 25." % field)
    return d


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------


def rhu(dec):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def event_zones(event_id):
    return [z for z in store.zones.values() if z["maker_event_id"] == event_id]


def event_booths(event_id):
    zids = {z["id"] for z in event_zones(event_id)}
    return [b for b in store.booths.values() if b["booth_zone_id"] in zids]


def event_applications(event_id):
    return [a for a in store.applications.values() if a["maker_event_id"] == event_id]


def event_assignments(event_id):
    app_ids = {a["id"] for a in event_applications(event_id)}
    return [x for x in store.assignments.values() if x["vendor_application_id"] in app_ids]


def event_settlements(event_id):
    aset = {x["id"] for x in event_assignments(event_id)}
    return [s for s in store.settlements.values() if s["booth_assignment_id"] in aset]


def event_tickets(event_id):
    return [t for t in store.tickets.values() if t["maker_event_id"] == event_id]


def event_attendance(event_id):
    return [a for a in store.attendance.values() if a["maker_event_id"] == event_id]


def event_sales(event_id):
    return [s for s in store.sales.values() if s["maker_event_id"] == event_id]


def event_slots(event_id):
    return [s for s in store.slots.values() if s["maker_event_id"] == event_id]


def assignment_for_application(app_id):
    rows = [x for x in store.assignments.values() if x["vendor_application_id"] == app_id]
    if not rows:
        return None
    return by_created(rows)[-1]


def charges_for_assignment(assignment_id):
    return by_created([c for c in store.charges.values() if c["booth_assignment_id"] == assignment_id])


def sales_for_assignment(assignment_id):
    rows = [s for s in store.sales.values() if s["booth_assignment_id"] == assignment_id]
    return sorted(rows, key=lambda r: (r["recorded_at"], r["_seq"]))


def booth_of(assignment):
    return store.booths.get(assignment["booth_id"])


def zone_of_booth(booth):
    return store.zones.get(booth["booth_zone_id"])


def event_of_assignment(assignment):
    app = store.applications.get(assignment["vendor_application_id"])
    if app is None:
        return None
    return store.events.get(app["maker_event_id"])


def event_of_settlement(settlement):
    asg = store.assignments.get(settlement["booth_assignment_id"])
    if asg is None:
        return None
    return event_of_assignment(asg)


def approved_count_for_category(event_id, category):
    return sum(
        1 for a in event_applications(event_id)
        if a["requested_category"] == category and a["status"] == "APPROVED"
    )


def category_cap_for(event_id, category):
    caps = [z["category_cap"] for z in event_zones(event_id) if z["category"] == category]
    return max(caps) if caps else 0


def booth_occupied(booth_id, exclude_assignment_id=None):
    for x in store.assignments.values():
        if x["booth_id"] != booth_id:
            continue
        if exclude_assignment_id is not None and x["id"] == exclude_assignment_id:
            continue
        if x["status"] in ASSIGNMENT_OPEN_STATUSES:
            return True
    return False


def select_booth(event, category, tier):
    """Lowest-priced matching unoccupied booth; tie by code ASC then created_at ASC."""
    cands = []
    for b in event_booths(event["id"]):
        z = zone_of_booth(b)
        if z is None or z["category"] != category:
            continue
        if b["tier"] != tier:
            continue
        if booth_occupied(b["id"]):
            continue
        cands.append(b)
    if not cands:
        return None
    cands.sort(key=lambda b: (b["price_cents"], b["code"], b["created_at"], b["_seq"]))
    return cands[0]


# ---------------------------------------------------------------------------
# Posture gate
# ---------------------------------------------------------------------------


def posture_gate(ev, allowed):
    if ev["posture"] not in allowed:
        raise ApiError(
            "ERR_POSTURE_FORBIDS", 409,
            "MakerEvent posture %s does not permit this operation." % ev["posture"],
        )


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def booth_fee_components(booth):
    zone = zone_of_booth(booth)
    base = booth["price_cents"]
    mult = TIER_MULT[booth["tier"]]
    uplift = CATEGORY_UPLIFT.get(zone["category"], Decimal("0.00")) if zone else Decimal("0.00")
    return base, mult, uplift


def booth_fee_quote(booth):
    """PROVISIONAL: round each component to integer cents, then sum."""
    base, mult, uplift = booth_fee_components(booth)
    tier_component = rhu(Decimal(base) * mult)
    uplift_component = rhu(Decimal(base) * uplift)
    return tier_component + uplift_component


def booth_fee_final(booth):
    """FINAL: sum exact components, round once."""
    base, mult, uplift = booth_fee_components(booth)
    exact = Decimal(base) * mult + Decimal(base) * uplift
    return rhu(exact)


def settlement_gross_quote(assignment_id):
    """Chronological signed accumulation over all rows (compensations included),
    floored at zero."""
    total = 0
    for r in sales_for_assignment(assignment_id):
        total += r["gross_cents"]
    return max(0, total)


def commission_quote(assignment_id):
    """PROVISIONAL commission: chronological per-row rounding with cumulative
    tiering. Only original (non-reversal) rows drive the cumulative gross;
    compensation rows subtract commission against the tier they originally hit."""
    assignment = store.assignments.get(assignment_id)
    booth = booth_of(assignment) if assignment else None
    ev = event_of_assignment(assignment) if assignment else None
    if ev is None:
        return 0
    pct = Decimal(str(ev["commission_pct_anchor"])) \
        if (booth is not None and booth["tier"] == "ANCHOR") \
        else Decimal(str(ev["commission_pct_standard"]))
    bumped = pct + COMMISSION_BUMP

    original_tier_above = {}  # entry_id -> bool: whether the original row ran above threshold
    cum = 0
    commission = 0
    for r in sales_for_assignment(assignment_id):
        gross = r["gross_cents"]
        rev_of = r.get("reversal_of_entry_id")
        if rev_of is None:
            if cum < COMMISSION_THRESHOLD and cum + gross > COMMISSION_THRESHOLD:
                below = COMMISSION_THRESHOLD - cum
                above = gross - below
                commission += rhu(Decimal(below) * pct) + rhu(Decimal(above) * bumped)
                original_tier_above[r["id"]] = True
            else:
                effective = pct if cum + gross <= COMMISSION_THRESHOLD else bumped
                commission += rhu(Decimal(gross) * effective)
                original_tier_above[r["id"]] = effective == bumped
            cum += gross
        else:
            above = original_tier_above.get(rev_of, False)
            effective = bumped if above else pct
            commission += rhu(Decimal(gross) * effective)  # gross negative -> subtracts
    return commission


def commission_final(assignment_id):
    """FINAL commission: aggregate-then-tier, single rounding per segment."""
    assignment = store.assignments.get(assignment_id)
    booth = booth_of(assignment) if assignment else None
    ev = event_of_assignment(assignment) if assignment else None
    if ev is None:
        return 0
    pct = Decimal(str(ev["commission_pct_anchor"])) \
        if (booth is not None and booth["tier"] == "ANCHOR") \
        else Decimal(str(ev["commission_pct_standard"]))
    gross_total = sum(r["gross_cents"] for r in sales_for_assignment(assignment_id))
    if gross_total > COMMISSION_THRESHOLD:
        return rhu(Decimal(COMMISSION_THRESHOLD) * pct) + \
            rhu(Decimal(gross_total - COMMISSION_THRESHOLD) * (pct + COMMISSION_BUMP))
    return rhu(Decimal(gross_total) * pct)


def paid_amount_for_assignment(assignment_id):
    """Amount actually paid = sum of FINAL charge rows (SURCHARGE rows add to it)."""
    total = 0
    for c in charges_for_assignment(assignment_id):
        if c["charge_kind"] in ("FINAL", "SURCHARGE"):
            total += c["amount_cents"]
        elif c["charge_kind"] == "REFUND":
            total += c["amount_cents"]  # negative
    return max(0, total)


def outstanding_booth_fee(assignment):
    booth = booth_of(assignment)
    if booth is None:
        return 0
    return max(0, booth_fee_final(booth) - paid_amount_for_assignment(assignment["id"]))


# ---------------------------------------------------------------------------
# Domain operations (charge minting, forfeit, promotion, cascades, sweeps)
# ---------------------------------------------------------------------------


def mint_charge(assignment_id, kind, amount_cents, trace):
    rec = {
        "booth_assignment_id": assignment_id,
        "charge_kind": kind,
        "amount_cents": amount_cents,
        "computed_at": fmt_ts(store.clock),
        "rounding_trace": trace,
    }
    stamp(rec)
    store.charges[rec["id"]] = rec
    return rec


def create_assignment_with_provisional(event, app, booth):
    """Shared side effects of an approval (decide or waitlist promotion)."""
    now = store.clock
    asg = {
        "vendor_application_id": app["id"],
        "booth_id": booth["id"],
        "status": "PENDING_PAYMENT",
        "assigned_at": fmt_ts(now),
        "payment_due_at": fmt_ts(now + PAYMENT_WINDOW),
        "expected_event_version": event["version"],
    }
    stamp(asg)
    store.assignments[asg["id"]] = asg
    mint_charge(asg["id"], "PROVISIONAL", booth_fee_quote(booth), "per_line_then_sum")
    return asg


def waitlist_promotion_scan(event, category=None, tier=None):
    """Promote head-of-line WAITLISTED applications whose category cap has spare
    capacity and for which a matching booth is unoccupied. Scoped to (category)
    when given; a freed booth may also enable the head's tier requirement."""
    categories = [category] if category else CATEGORIES
    for cat in categories:
        while True:
            heads = [
                a for a in event_applications(event["id"])
                if a["status"] == "WAITLISTED"
                and a["requested_category"] == cat
                and (tier is None or a["requested_tier"] == tier)
            ]
            if not heads:
                break
            heads.sort(key=lambda a: (
                a["waitlist_rank"] if a["waitlist_rank"] is not None else 1 << 30,
                -a["jury_score_total"], a["created_at"], a["_seq"], a["vendor_profile_id"],
            ))
            head = heads[0]
            if approved_count_for_category(event["id"], cat) >= category_cap_for(event["id"], cat):
                break
            booth = select_booth(event, head["requested_category"], head["requested_tier"])
            if booth is None:
                break
            head["status"] = "APPROVED"
            head["waitlist_rank"] = None
            touch(head)
            create_assignment_with_provisional(event, head, booth)


def forfeit_assignment(assignment, event=None, run_scan=True):
    """PENDING_PAYMENT|ACTIVE -> FORFEITED with refund, booth release,
    settlement cancel and waitlist promotion scan."""
    if event is None:
        event = event_of_assignment(assignment)
    paid = paid_amount_for_assignment(assignment["id"])
    mint_charge(assignment["id"], "REFUND", -paid, "refund")
    assignment["status"] = "FORFEITED"
    touch(assignment)
    booth = booth_of(assignment)
    if booth is not None and booth.get("assigned_application_id") == assignment["vendor_application_id"]:
        booth["assigned_application_id"] = None
        touch(booth)
    for s in store.settlements.values():
        if s["booth_assignment_id"] == assignment["id"] and s["status"] in ("PENDING", "COMPUTED"):
            s["status"] = "CANCELLED"
            touch(s)
    if run_scan and event is not None:
        app = store.applications.get(assignment["vendor_application_id"])
        cat = app["requested_category"] if app else None
        waitlist_promotion_scan(event, category=cat)


def auto_close_event_applications(event):
    """APPLICATION_OPEN -> JURY_REVIEW closing sweep."""
    event["posture"] = "JURY_REVIEW"
    touch(event)
    for a in event_applications(event["id"]):
        if a["status"] == "DRAFT":
            a["status"] = "WITHDRAWN"
            touch(a)
        elif a["status"] == "SUBMITTED":
            a["status"] = "IN_REVIEW"
            touch(a)


def sweep_expired_assignments():
    """Forfeit every PENDING_PAYMENT assignment whose payment deadline passed."""
    for asg in list(store.assignments.values()):
        if asg["status"] != "PENDING_PAYMENT":
            continue
        due = parse_dt(asg["payment_due_at"])
        if due is not None and store.clock > due:
            forfeit_assignment(asg)


def sweep_event_clock(event):
    """Auto-close the application window when the clock reaches its end."""
    if event["posture"] == "APPLICATION_OPEN":
        end = parse_dt(event["application_window_end"])
        if end is not None and store.clock >= end:
            auto_close_event_applications(event)


def weather_severe_cascade(event):
    """LIVE -> WEATHER_HOLD: forfeit ACTIVE assignments in OPEN_AIR zones."""
    event["posture"] = "WEATHER_HOLD"
    for asg in event_assignments(event["id"]):
        if asg["status"] != "ACTIVE":
            continue
        booth = booth_of(asg)
        zone = zone_of_booth(booth) if booth else None
        if zone is not None and zone["weather_exposure"] == "OPEN_AIR":
            forfeit_assignment(asg, event=event)
    touch(event)


def cancel_event_cascade(event):
    """Two cancel shapes: pre-live (void/withdraw/release) and weather-hold
    (refund/forfeit/cancel/delete)."""
    if event["posture"] in PRE_LIVE_POSTURES:
        for t in event_tickets(event["id"]):
            if t["state"] != "VOIDED":
                t["state"] = "VOIDED"
                touch(t)
        for a in event_applications(event["id"]):
            if a["status"] not in APP_TERMINAL_STATUSES:
                a["status"] = "WITHDRAWN"
                touch(a)
        for asg in event_assignments(event["id"]):
            if asg["status"] in ASSIGNMENT_OPEN_STATUSES:
                asg["status"] = "RELEASED"
                touch(asg)
                booth = booth_of(asg)
                if booth is not None and booth.get("assigned_application_id") == asg["vendor_application_id"]:
                    booth["assigned_application_id"] = None
                    touch(booth)
    elif event["posture"] == "WEATHER_HOLD":
        for t in event_tickets(event["id"]):
            if t["state"] in ("ISSUED", "REDEEMED"):
                t["state"] = "REFUNDED"
                touch(t)
        for asg in event_assignments(event["id"]):
            if asg["status"] in ASSIGNMENT_OPEN_STATUSES:
                forfeit_assignment(asg, event=event)
        for s in event_settlements(event["id"]):
            if s["status"] in ("PENDING", "COMPUTED"):
                s["status"] = "CANCELLED"
                touch(s)
        for sl in event_slots(event["id"]):
            del store.slots[sl["id"]]
    event["posture"] = "CANCELLED"
    touch(event)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_event(ev):
    return pub(ev)


def serialize_zone(z):
    return pub(z)


def serialize_booth(b):
    return pub(b)


def serialize_vendor(v):
    return pub(v)


def serialize_application(a):
    return pub(a)


def serialize_jury_score(s):
    return pub(s)


def serialize_assignment(x):
    return pub(x)


def serialize_charge(c):
    return pub(c)


def serialize_slot(s):
    return pub(s)


def serialize_ticket(t):
    return pub(t)


def serialize_attendance(a):
    return pub(a)


def serialize_sale(s):
    return pub(s)


def serialize_settlement(s):
    return pub(s)
