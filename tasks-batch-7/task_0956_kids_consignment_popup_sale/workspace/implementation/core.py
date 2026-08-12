"""Core helpers: in-memory store, auth, envelope, clock, calculations, serializers."""
import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

VALID_ROLES = ("Anonymous", "EventOrganizer", "Consignor", "Volunteer", "Inspector", "Cashier")

PHASES = ["DRAFT", "INTAKE_OPEN", "INTAKE_CLOSED", "PRESALE_DAY", "SALE_ACTIVE", "SETTLEMENT", "CLOSED"]
NEXT_PHASE = {PHASES[i]: PHASES[i + 1] for i in range(len(PHASES) - 1)}
TERMINAL_ITEM_STATUSES = ("SOLD", "PICKED_UP", "DONATED")

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


class Store:
    def __init__(self):
        self.sale_events = {}
        self.markdown_rules = {}
        self.consignors = {}
        self.volunteers = {}
        self.slots = {}
        self.bookings = {}
        self.items = {}
        self.inspection_records = {}
        self.shifts = {}
        self.signups = {}
        self.passes = {}
        self.transactions = {}
        self.lines = {}
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


def fmt_clock(dt):
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


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


def ok_array(recs, code=200):
    """Array response without pagination meta (action endpoints returning arrays)."""
    return jsonify({"meta": req_meta(), "response_type": "array", "data": recs}), code


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
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT", 400,
            "Missing or invalid X-User-ID / X-User-Role headers.",
        )
    return uid, role


def require(role, *allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role %s is not permitted for this endpoint." % role)


def forbidden(msg="Ownership check failed."):
    raise ApiError("ERR_FORBIDDEN", 403, msg)


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
    """InspectionRecord / TransactionLine: id + created_at only."""
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = fmt_ts(store.clock)
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = fmt_ts(store.clock)
    rec["version"] += 1


def by_created(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_or_404(table, rid, err_id, label):
    rec = getattr(store, table).get(rid)
    if rec is None:
        raise ApiError(err_id, 404, "%s not found: %s" % (label, rid))
    return rec


def apply_filters(recs, mapping):
    out = list(recs)
    for param, key in mapping.items():
        v = request.args.get(param)
        if v is not None:
            out = [r for r in out if str(r.get(key)) == v]
    return out


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------


def rhu(numerator, denominator=100):
    """round_half_up(numerator / denominator) to whole integer."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier(hours):
    if hours >= 12:
        return 20
    if hours >= 8:
        return 15
    if hours >= 4:
        return 10
    return 5


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def event_transactions(event_id):
    return [t for t in store.transactions.values() if t["sale_event_id"] == event_id]


def event_items(event_id):
    return [i for i in store.items.values() if i["sale_event_id"] == event_id]


def consignor_items(consignor_id):
    return [i for i in store.items.values() if i["consignor_id"] == consignor_id]


def txn_lines(txn_id):
    return [l for l in store.lines.values() if l["transaction_id"] == txn_id]


def txn_totals(txn):
    lines = txn_lines(txn["id"])
    subtotal = sum(l["line_price_cents"] for l in lines)
    total = sum(l["final_line_cents"] for l in lines)
    return subtotal, subtotal - total, total


def event_sold_gross(event_id):
    total = 0
    for t in event_transactions(event_id):
        if t["status"] == "COMPLETED":
            total += sum(l["final_line_cents"] for l in txn_lines(t["id"]))
    return total


def consignor_sold_gross(consignor_id):
    total = 0
    for l in store.lines.values():
        item = store.items.get(l["item_id"])
        if item is None or item["consignor_id"] != consignor_id:
            continue
        txn = store.transactions.get(l["transaction_id"])
        if txn is not None and txn["status"] == "COMPLETED":
            total += l["final_line_cents"]
    return total


def consignor_counts(consignor_id):
    items = consignor_items(consignor_id)
    return {
        "sold_count": sum(1 for i in items if i["status"] == "SOLD"),
        "unsold_count": sum(1 for i in items if i["status"] == "UNSOLD"),
        "rejected_count": sum(1 for i in items if i["status"] == "REJECTED"),
        "sold_gross_cents": consignor_sold_gross(consignor_id),
    }


def slot_booked_count(slot_id):
    return sum(
        1 for b in store.bookings.values()
        if b["slot_id"] == slot_id and b["status"] in ("BOOKED", "CHECKED_IN")
    )


def shift_signed_up_count(shift_id):
    return sum(
        1 for s in store.signups.values()
        if s["shift_id"] == shift_id and s["status"] in ("SIGNED_UP", "CHECKED_IN")
    )


def volunteer_hours(volunteer_id):
    completed = 0.0
    in_progress = 0.0
    for su in store.signups.values():
        if su["volunteer_id"] != volunteer_id:
            continue
        sh = store.shifts.get(su["shift_id"])
        if sh is None:
            continue
        if su["status"] == "COMPLETED":
            completed += float(su["hours_credited"])
        elif su["status"] == "CHECKED_IN":
            in_progress += (sh["_end"] - sh["_start"]).total_seconds() / 3600.0
    completed = round(completed, 2)
    projected = round(completed + in_progress, 2)
    return completed, projected


def has_volunteer_bonus(consignor):
    for v in store.volunteers.values():
        if v.get("linked_consignor_id") == consignor["id"]:
            completed, _ = volunteer_hours(v["id"])
            if completed >= 4:
                return True
    return False


def split_pct_for(consignor, gross):
    if gross < 20000:
        t = 60
    elif gross < 50000:
        t = 65
    else:
        t = 70
    bonus = 5 if has_volunteer_bonus(consignor) else 0
    return min(75, t + bonus)


def payout_pipeline(consignor, gross, adjustment):
    split = split_pct_for(consignor, gross)
    commission = rhu(gross * (100 - split), 100)
    pbf = gross - commission
    supply = 0 if (pbf >= 30000 or has_volunteer_bonus(consignor)) else 1000
    rejected_fee = 200 * consignor_counts(consignor["id"])["rejected_count"]
    payout = max(0, pbf - supply - rejected_fee + adjustment)
    return {
        "split_pct": split,
        "commission_cents": commission,
        "payout_before_fee_cents": pbf,
        "supply_fee_cents": supply,
        "rejected_fee_cents": rejected_fee,
        "payout_cents": payout,
    }


def markdown_pct_at(item, when):
    if not item.get("discount_eligible", True):
        return 0
    for r in store.markdown_rules.values():
        if r["sale_event_id"] != item["sale_event_id"]:
            continue
        if r["_from"] is not None and r["_to"] is not None and r["_from"] <= when < r["_to"]:
            return r["discount_pct"]
    return 0


def provisional_for_consignor(consignor):
    """Returns (provisional_gross_cents, provisional_payout_cents)."""
    actual = consignor_sold_gross(consignor["id"])
    estimated = actual
    now = store.clock
    for item in consignor_items(consignor["id"]):
        if item["status"] == "ON_FLOOR":
            md = markdown_pct_at(item, now)
            line_price = rhu(item["price_cents"] * (100 - md), 100)
            estimated += rhu(line_price * 50, 100)
    payout = payout_pipeline(consignor, estimated, 0)["payout_cents"]
    return estimated, payout


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_event(ev):
    d = pub(ev)
    d["sold_gross_cents"] = event_sold_gross(ev["id"])
    return d


def serialize_rule(r):
    return pub(r)


def serialize_consignor(c):
    d = pub(c)
    d.update(consignor_counts(c["id"]))
    return d


def serialize_volunteer(v):
    d = pub(v)
    completed, projected = volunteer_hours(v["id"])
    d["completed_hours"] = completed
    d["projected_hours"] = projected
    d["projected_discount_pct"] = tier(projected)
    return d


def serialize_slot(s):
    d = pub(s)
    d["booked_count"] = slot_booked_count(s["id"])
    return d


def serialize_booking(b):
    return pub(b)


def serialize_item(i):
    return pub(i)


def serialize_inspection(r):
    return pub(r)


def serialize_shift(s):
    d = pub(s)
    d["signed_up_count"] = shift_signed_up_count(s["id"])
    return d


def serialize_signup(s):
    return pub(s)


def serialize_pass(p):
    return pub(p)


def serialize_txn(t):
    d = pub(t)
    subtotal, discount, total = txn_totals(t)
    d["subtotal_cents"] = subtotal
    d["discount_cents"] = discount
    d["total_cents"] = total
    return d


def serialize_line(l):
    return pub(l)


def serialize_settlement(s):
    d = pub(s)
    d["sold_item_count"] = sum(
        1 for i in consignor_items(s["consignor_id"]) if i["status"] == "SOLD"
    )
    if s["status"] == "DRAFT":
        consignor = store.consignors.get(s["consignor_id"])
        if consignor is not None:
            g, payout = provisional_for_consignor(consignor)
            d["provisional_gross_cents"] = g
            d["provisional_payout_cents"] = payout
    return d
