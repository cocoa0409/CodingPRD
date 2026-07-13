"""Tool & Gear Lending Library API — Python + Flask, in-memory only.

All state lives in module-level dicts and is wiped on every process start
(the harness re-launches start.sh before each test). No seeding at startup.
"""
import os
import math
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# --------------------------------------------------------------------------- #
# Domain constants (PRD §3)
# --------------------------------------------------------------------------- #
GRACE_DAYS = 2
SUSPEND_THRESHOLD_CENTS = 2000
LOST_THRESHOLD_DAYS = 30
DEP_RATE_PER_YEAR = Decimal("0.10")
SALVAGE_FLOOR_PCT = Decimal("0.20")
REPAIR_FLAT_CENTS = 1500
DEFAULT_MAX_ACTIVE_LOANS = 5
DEFAULT_MAX_ACTIVE_HOLDS = 3
DEFAULT_BALANCE_LIMIT_CENTS = 2000
DEFAULT_MAX_RENEWALS = 2
# Not pinned by the PRD to a number (absent from the test constants); chosen defaults.
CLAIM_WINDOW_DAYS = 7
MAINTENANCE_BUFFER_DAYS = 1
SERVER_START_CLOCK = "2026-03-01T00:00:00Z"

ROLES = ("Member", "Volunteer", "Coordinator")

# --------------------------------------------------------------------------- #
# In-memory store
# --------------------------------------------------------------------------- #
members = {}
volunteers = {}
items = {}
copies = {}
reservations = {}
loans = {}
holds = {}
fees = {}
donations = {}
tickets = {}

_seq = 0
_promotions = 0  # global monotonic count of promotions performed


def _parse_dt(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    try:
        txt = str(s).strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, f"invalid datetime: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


NOW = _parse_dt(SERVER_START_CLOCK)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --------------------------------------------------------------------------- #
# Errors + response envelope
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _rand_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _rand_id(), "api_request_timestamp": iso(NOW)}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200, response_type="object", list_meta=None):
    body = {"meta": _meta(list_meta), "response_type": response_type, "data": data}
    return jsonify(body), code


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "not found"},
    }
    return jsonify(body), 404


# --------------------------------------------------------------------------- #
# Entity helpers
# --------------------------------------------------------------------------- #
def new_entity(**fields):
    global _seq
    _seq += 1
    e = {
        "id": str(uuid.uuid4()),
        "created_at": NOW,
        "updated_at": NOW,
        "version": 1,
        "_seq": _seq,
    }
    e.update(fields)
    return e


def touch(e):
    e["updated_at"] = NOW
    e["version"] += 1


def serialize(e, extra=None):
    out = {}
    for k, v in e.items():
        if k.startswith("_"):
            continue
        out[k] = iso(v) if isinstance(v, datetime) else v
    if extra:
        out.update(extra)
    return out


# --------------------------------------------------------------------------- #
# Derived computations
# --------------------------------------------------------------------------- #
def item_counts(item_id):
    cps = [c for c in copies.values() if c["item_id"] == item_id]
    return {
        "serviceable_copies_count": sum(1 for c in cps if c["condition_status"] != "RETIRED"),
        "available_copies_count": sum(
            1 for c in cps if c["availability_status"] == "AVAILABLE" and c["condition_status"] == "GOOD"
        ),
        "reserved_count": sum(1 for c in cps if c["availability_status"] == "RESERVED"),
        "on_loan_count": sum(1 for c in cps if c["availability_status"] == "ON_LOAN"),
        "maintenance_count": sum(
            1 for c in cps if c["condition_status"] in ("NEEDS_MAINTENANCE", "UNDER_MAINTENANCE")
        ),
        "waitlist_length": sum(
            1 for h in holds.values() if h["item_id"] == item_id and h["status"] in ("PENDING", "PROMOTED")
        ),
    }


def member_ledger(member_id):
    fs = [f for f in fees.values() if f["member_id"] == member_id]
    return {
        "outstanding_balance_cents": sum(f["amount_cents"] for f in fs if f["status"] in ("ACCRUING", "PENDING")),
        "total_assessed_cents": sum(f["amount_cents"] for f in fs if f["status"] in ("PENDING", "PAID", "WAIVED")),
        "total_paid_cents": sum(f["amount_cents"] for f in fs if f["status"] == "PAID"),
        "total_waived_cents": sum(f["amount_cents"] for f in fs if f["status"] == "WAIVED"),
    }


def outstanding(member_id):
    return member_ledger(member_id)["outstanding_balance_cents"]


def ser_member(m):
    return serialize(m, member_ledger(m["id"]))


def ser_item(i):
    return serialize(i, item_counts(i["id"]))


# --------------------------------------------------------------------------- #
# Auth / body helpers
# --------------------------------------------------------------------------- #
def auth(allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unknown auth headers")
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    return uid, role


def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def require(b, name):
    if name not in b or b[name] is None:
        raise ApiError("ERR_VALIDATION", 400, f"missing required field: {name}")
    return b[name]


def check_enum(val, allowed):
    if val not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 400, f"invalid enum value: {val}")
    return val


def paginate(rows):
    rows = sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return page, meta


# --------------------------------------------------------------------------- #
# Existence getters
# --------------------------------------------------------------------------- #
def get_or_404(store, key, err):
    ent = store.get(key)
    if ent is None:
        raise ApiError(err, 404, "resource not found")
    return ent


# --------------------------------------------------------------------------- #
# Calculations
# --------------------------------------------------------------------------- #
def rhu(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def late_fee_amount(item, loan, obs):
    seconds = (obs - loan["due_date"]).total_seconds()
    days_overdue = math.floor(seconds / 86400)
    billable = max(0, days_overdue - GRACE_DAYS)
    raw = item["daily_late_fee_cents"] * billable
    return min(raw, item["replacement_value_cents"])


def damage_amount(item, copy, return_condition, obs):
    rv = item["replacement_value_cents"]
    age_seconds = (obs - copy["acquired_on"]).total_seconds()
    age_years = math.floor(age_seconds / (365 * 86400))
    if age_years < 0:
        age_years = 0
    annual_dep = rhu(Decimal(rv) * DEP_RATE_PER_YEAR)
    depreciated = rv - annual_dep * age_years
    salvage_floor = rhu(Decimal(rv) * SALVAGE_FLOOR_PCT)
    full_replace = max(depreciated, salvage_floor)
    if return_condition == "MINOR_DAMAGE":
        return min(REPAIR_FLAT_CENTS, full_replace), "DAMAGE"
    # MAJOR_DAMAGE or LOST
    return full_replace, "REPLACEMENT"


# --------------------------------------------------------------------------- #
# Fee / ledger side effects
# --------------------------------------------------------------------------- #
def create_fee(member_id, loan_id, fee_type, amount_cents, status, assessed_at):
    f = new_entity(
        member_id=member_id,
        loan_id=loan_id,
        fee_type=fee_type,
        amount_cents=amount_cents,
        status=status,
        assessed_at=assessed_at,
    )
    fees[f["id"]] = f
    return f


def find_accruing_late_fee(loan_id):
    for f in fees.values():
        if f["loan_id"] == loan_id and f["fee_type"] == "LATE" and f["status"] == "ACCRUING":
            return f
    return None


def check_suspend(member):
    if member["status"] == "ACTIVE" and outstanding(member["id"]) >= SUSPEND_THRESHOLD_CENTS:
        member["status"] = "SUSPENDED"
        touch(member)
        cascade_member_release(member)


def cascade_member_release(member):
    """Cancel PENDING reservations and expire PENDING/PROMOTED holds of the member."""
    for r in list(reservations.values()):
        if r["member_id"] == member["id"] and r["status"] == "PENDING":
            r["status"] = "CANCELLED"
            touch(r)
            release_reservation_copy(r)
    for h in list(holds.values()):
        if h["member_id"] == member["id"] and h["status"] in ("PENDING", "PROMOTED"):
            if h["status"] == "PROMOTED":
                res = reservations.get(h["promoted_reservation_id"])
                if res and res["status"] == "PENDING":
                    res["status"] = "CANCELLED"
                    touch(res)
                    release_reservation_copy(res)
            h["status"] = "EXPIRED"
            touch(h)


# --------------------------------------------------------------------------- #
# Copy availability / waitlist promotion
# --------------------------------------------------------------------------- #
def release_reservation_copy(reservation):
    """Move the reservation's assigned copy from RESERVED back to AVAILABLE and
    run the promotion cascade for the item."""
    copy = copies.get(reservation.get("copy_id"))
    if copy is None:
        return
    item = items.get(copy["item_id"])
    if copy["availability_status"] == "RESERVED":
        copy["availability_status"] = "AVAILABLE"
        touch(copy)
        if item:
            touch(item)
    if item:
        try_promote(item)


def try_promote(item):
    """Promote the single earliest PENDING hold (ACTIVE member) if a lendable copy
    exists. Returns True if a promotion occurred."""
    global _promotions
    free_copy = next(
        (c for c in copies.values()
         if c["item_id"] == item["id"] and c["availability_status"] == "AVAILABLE" and c["condition_status"] == "GOOD"),
        None,
    )
    if free_copy is None:
        return False
    candidates = [
        h for h in holds.values()
        if h["item_id"] == item["id"] and h["status"] == "PENDING"
        and members.get(h["member_id"], {}).get("status") == "ACTIVE"
    ]
    if not candidates:
        return False
    hold = min(candidates, key=lambda h: (h["created_at"], h["_seq"]))
    claim_deadline = NOW + timedelta(days=CLAIM_WINDOW_DAYS)
    res = new_entity(
        member_id=hold["member_id"],
        item_id=item["id"],
        copy_id=free_copy["id"],
        window_start=NOW,
        window_end=claim_deadline,
        source="WAITLIST_PROMOTION",
        status="PENDING",
    )
    reservations[res["id"]] = res
    free_copy["availability_status"] = "RESERVED"
    touch(free_copy)
    touch(item)
    hold["status"] = "PROMOTED"
    hold["promoted_reservation_id"] = res["id"]
    hold["claim_deadline"] = claim_deadline
    touch(hold)
    _promotions += 1
    return True


# =========================================================================== #
# Members
# =========================================================================== #
@app.route("/library/members", methods=["POST"])
def create_member():
    auth(["Coordinator"])
    b = get_body()
    name = require(b, "name")
    email = require(b, "email")
    tier = check_enum(require(b, "tier"), ("BASIC", "PLUS"))
    for m in members.values():
        if m["email"] == email:
            raise ApiError("ERR_VALIDATION", 400, "email already in use")
    member = new_entity(
        name=name,
        email=email,
        tier=tier,
        status="ACTIVE",
        max_active_loans=b.get("max_active_loans", DEFAULT_MAX_ACTIVE_LOANS),
        max_active_holds=b.get("max_active_holds", DEFAULT_MAX_ACTIVE_HOLDS),
        balance_limit_cents=b.get("balance_limit_cents", DEFAULT_BALANCE_LIMIT_CENTS),
        membership_expires_at=_parse_dt(b.get("membership_expires_at")),
    )
    members[member["id"]] = member
    return ok(ser_member(member), 201)


@app.route("/library/members/<member_id>", methods=["GET"])
def get_member(member_id):
    auth(["Member", "Volunteer", "Coordinator"])
    m = get_or_404(members, member_id, "ERR_MEMBER_NOT_FOUND")
    return ok(ser_member(m))


# =========================================================================== #
# Volunteers
# =========================================================================== #
@app.route("/library/volunteers", methods=["POST"])
def create_volunteer():
    auth(["Coordinator"])
    b = get_body()
    name = require(b, "name")
    role_level = check_enum(require(b, "role_level"), ("VOLUNTEER", "COORDINATOR"))
    active = b.get("active", True)
    v = new_entity(name=name, role_level=role_level, active=bool(active))
    volunteers[v["id"]] = v
    return ok(serialize(v), 201)


# =========================================================================== #
# Items & Copies
# =========================================================================== #
@app.route("/library/items", methods=["POST"])
def create_item():
    auth(["Coordinator"])
    b = get_body()
    name = require(b, "name")
    category = check_enum(require(b, "category"), ("TOOL", "OUTDOOR", "KITCHEN"))
    item = new_entity(
        name=name,
        category=category,
        replacement_value_cents=require(b, "replacement_value_cents"),
        loan_period_days=require(b, "loan_period_days"),
        daily_late_fee_cents=require(b, "daily_late_fee_cents"),
        max_renewals=b.get("max_renewals", DEFAULT_MAX_RENEWALS),
    )
    items[item["id"]] = item
    return ok(ser_item(item), 201)


@app.route("/library/items/<item_id>", methods=["GET"])
def get_item(item_id):
    auth(["Member", "Volunteer", "Coordinator"])
    i = get_or_404(items, item_id, "ERR_ITEM_NOT_FOUND")
    return ok(ser_item(i))


@app.route("/library/items/<item_id>/copies", methods=["POST"])
def add_copy(item_id):
    auth(["Volunteer", "Coordinator"])
    item = get_or_404(items, item_id, "ERR_ITEM_NOT_FOUND")
    b = get_body()
    asset_tag = require(b, "asset_tag")
    acquired_on = _parse_dt(require(b, "acquired_on"))
    origin = check_enum(b.get("origin", "PURCHASE"), ("PURCHASE", "DONATION"))
    copy = new_entity(
        item_id=item["id"],
        asset_tag=asset_tag,
        acquired_on=acquired_on,
        origin=origin,
        availability_status="AVAILABLE",
        condition_status="GOOD",
    )
    copies[copy["id"]] = copy
    touch(item)
    return ok(serialize(copy), 201)


@app.route("/library/items/<item_id>/copies", methods=["GET"])
def list_copies(item_id):
    auth(["Member", "Volunteer", "Coordinator"])
    get_or_404(items, item_id, "ERR_ITEM_NOT_FOUND")
    rows = [c for c in copies.values() if c["item_id"] == item_id]
    page, meta = paginate(rows)
    return ok([serialize(c) for c in page], 200, "array", meta)


@app.route("/library/copies/<copy_id>", methods=["GET"])
def get_copy(copy_id):
    auth(["Member", "Volunteer", "Coordinator"])
    c = get_or_404(copies, copy_id, "ERR_COPY_NOT_FOUND")
    return ok(serialize(c))


# =========================================================================== #
# Reservations
# =========================================================================== #
def _overlaps(s1, e1, s2, e2):
    # half-open [s,e)
    return s1 < e2 and s2 < e1


@app.route("/library/reservations", methods=["POST"])
def create_reservation():
    uid, role = auth(["Member"])
    b = get_body()
    member_id = b.get("member_id")
    item_id = b.get("item_id")
    # existence (priority 3), provided ids left-to-right
    if member_id is not None and member_id not in members:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    if item_id is not None and item_id not in items:
        raise ApiError("ERR_ITEM_NOT_FOUND", 404, "item not found")
    # ownership (priority 4)
    if role == "Member" and member_id is not None and member_id != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    # body validation (priority 5)
    require(b, "member_id")
    require(b, "item_id")
    ws = _parse_dt(require(b, "window_start"))
    we = _parse_dt(require(b, "window_end"))
    if ws >= we:
        raise ApiError("ERR_INVALID_WINDOW", 400, "window_start must be before window_end")
    member = members[member_id]
    item = items[item_id]
    # member active (priority 6)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "member not active")
    counts = item_counts(item_id)
    serviceable = counts["serviceable_copies_count"]
    # capacity window check (priority 9) — evaluated before empty-candidate fallback
    existing = [
        r for r in reservations.values()
        if r["item_id"] == item_id and r["status"] == "PENDING"
        and _overlaps(r["window_start"], r["window_end"], ws, we)
    ]
    instants = [ws] + [max(r["window_start"], ws) for r in existing]
    peak = 0
    for t in instants:
        c = sum(1 for r in existing if r["window_start"] <= t < r["window_end"])
        peak = max(peak, c)
    if peak + 1 > serviceable:
        raise ApiError("ERR_ITEM_NO_CAPACITY_FOR_WINDOW", 409, "no capacity for window")
    # assignment / empty-candidate fallback (priority 11)
    free_copy = next(
        (c for c in copies.values()
         if c["item_id"] == item_id and c["availability_status"] == "AVAILABLE" and c["condition_status"] == "GOOD"),
        None,
    )
    if free_copy is None:
        raise ApiError("ERR_NO_COPY_AVAILABLE", 409, "no serviceable copy free for window")
    res = new_entity(
        member_id=member_id,
        item_id=item_id,
        copy_id=free_copy["id"],
        window_start=ws,
        window_end=we,
        source="MEMBER",
        status="PENDING",
    )
    reservations[res["id"]] = res
    free_copy["availability_status"] = "RESERVED"
    touch(free_copy)
    touch(item)
    return ok(serialize(res), 201)


@app.route("/library/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    auth(["Member", "Volunteer", "Coordinator"])
    r = get_or_404(reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    return ok(serialize(r))


@app.route("/library/reservations", methods=["GET"])
def list_reservations():
    auth(["Member", "Volunteer", "Coordinator"])
    rows = list(reservations.values())
    mid = request.args.get("member_id")
    iid = request.args.get("item_id")
    st = request.args.get("status")
    if mid:
        rows = [r for r in rows if r["member_id"] == mid]
    if iid:
        rows = [r for r in rows if r["item_id"] == iid]
    if st:
        rows = [r for r in rows if r["status"] == st]
    page, meta = paginate(rows)
    return ok([serialize(r) for r in page], 200, "array", meta)


@app.route("/library/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    uid, role = auth(["Member", "Volunteer", "Coordinator"])
    r = get_or_404(reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    if role == "Member" and r["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    if r["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "reservation not PENDING")
    r["status"] = "CANCELLED"
    touch(r)
    release_reservation_copy(r)
    return ok(serialize(r))


# =========================================================================== #
# Loans
# =========================================================================== #
@app.route("/library/loans", methods=["POST"])
def create_loan():
    uid, role = auth(["Volunteer", "Coordinator"])
    b = get_body()
    member_id = b.get("member_id")
    copy_id = b.get("copy_id")
    reservation_id = b.get("reservation_id")
    # existence (priority 3): member_id, copy_id, reservation_id (left-to-right)
    if member_id is not None and member_id not in members:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    if copy_id is not None and copy_id not in copies:
        raise ApiError("ERR_COPY_NOT_FOUND", 404, "copy not found")
    if reservation_id is not None and reservation_id not in reservations:
        raise ApiError("ERR_RESERVATION_NOT_FOUND", 404, "reservation not found")
    # body validation (priority 5)
    require(b, "member_id")
    require(b, "copy_id")
    if "expected_item_version" not in b or b["expected_item_version"] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing expected_item_version")
    expected_version = b["expected_item_version"]
    member = members[member_id]
    copy = copies[copy_id]
    item = items[copy["item_id"]]
    # member active (priority 6)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "member not active")
    # resolve/validate reservation ownership
    reservation = reservations.get(reservation_id) if reservation_id else None
    if reservation is not None:
        if reservation["member_id"] != member_id or reservation["status"] != "PENDING":
            raise ApiError("ERR_COPY_NOT_AVAILABLE", 409, "reservation not usable by member")
    # copy availability (priority 8)
    if copy["condition_status"] != "GOOD":
        raise ApiError("ERR_COPY_NOT_AVAILABLE", 409, "copy not in good condition")
    if copy["availability_status"] == "AVAILABLE":
        pass
    elif copy["availability_status"] == "RESERVED":
        owned_res = reservation
        if owned_res is None:
            owned_res = next(
                (r for r in reservations.values()
                 if r.get("copy_id") == copy_id and r["member_id"] == member_id and r["status"] == "PENDING"),
                None,
            )
        if owned_res is None:
            raise ApiError("ERR_COPY_NOT_AVAILABLE", 409, "copy reserved to another member")
        reservation = owned_res
    else:  # ON_LOAN
        raise ApiError("ERR_COPY_NOT_AVAILABLE", 409, "copy on loan")
    # loan limit (priority 13)
    active_loans = sum(
        1 for l in loans.values() if l["member_id"] == member_id and l["status"] in ("ACTIVE", "OVERDUE")
    )
    if active_loans >= member["max_active_loans"]:
        raise ApiError("ERR_LOAN_LIMIT_EXCEEDED", 409, "loan limit exceeded")
    # balance (priority 14)
    if outstanding(member_id) >= SUSPEND_THRESHOLD_CENTS:
        raise ApiError("ERR_BALANCE_LIMIT_EXCEEDED", 402, "balance limit exceeded")
    # OCC (priority 15)
    if expected_version != item["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale item version")
    # commit
    checked_out_at = NOW
    due_date = checked_out_at + timedelta(days=item["loan_period_days"])
    loan = new_entity(
        member_id=member_id,
        copy_id=copy_id,
        reservation_id=reservation["id"] if reservation else None,
        item_id=item["id"],
        checked_out_at=checked_out_at,
        due_date=due_date,
        renewals_used=0,
        status="ACTIVE",
        return_condition=None,
        returned_at=None,
        checked_out_by_volunteer_id=uid,
    )
    loans[loan["id"]] = loan
    copy["availability_status"] = "ON_LOAN"
    touch(copy)
    touch(item)  # increments item version by one (OCC) + count recompute
    if reservation is not None:
        reservation["status"] = "FULFILLED"
        touch(reservation)
        if reservation["source"] == "WAITLIST_PROMOTION":
            for h in holds.values():
                if h["promoted_reservation_id"] == reservation["id"] and h["status"] == "PROMOTED":
                    h["status"] = "FULFILLED"
                    touch(h)
                    break
    return ok(serialize(loan), 201)


@app.route("/library/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    auth(["Member", "Volunteer", "Coordinator"])
    l = get_or_404(loans, loan_id, "ERR_LOAN_NOT_FOUND")
    return ok(serialize(l))


@app.route("/library/loans", methods=["GET"])
def list_loans():
    auth(["Member", "Volunteer", "Coordinator"])
    rows = list(loans.values())
    for key, field in (("member_id", "member_id"), ("copy_id", "copy_id"),
                       ("reservation_id", "reservation_id"), ("status", "status")):
        val = request.args.get(key)
        if val:
            rows = [r for r in rows if r.get(field) == val]
    page, meta = paginate(rows)
    return ok([serialize(r) for r in page], 200, "array", meta)


@app.route("/library/loans/<loan_id>/renew", methods=["POST"])
def renew_loan(loan_id):
    uid, role = auth(["Member", "Volunteer", "Coordinator"])
    loan = get_or_404(loans, loan_id, "ERR_LOAN_NOT_FOUND")
    if role == "Member" and loan["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    member = members[loan["member_id"]]
    item = items[loan["item_id"]]
    # member active (priority 6)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "member not active")
    # loan state (priority 7)
    if loan["status"] != "ACTIVE":
        raise ApiError("ERR_LOAN_NOT_ACTIVE", 409, "loan not ACTIVE")
    # renewal limit (priority 13)
    if loan["renewals_used"] >= item["max_renewals"]:
        raise ApiError("ERR_RENEWAL_LIMIT_EXCEEDED", 409, "renewal limit exceeded")
    # waitlist block (priority 13)
    if any(h["item_id"] == item["id"] and h["status"] in ("PENDING", "PROMOTED") for h in holds.values()):
        raise ApiError("ERR_RENEWAL_BLOCKED_WAITLIST", 409, "renewal blocked by waitlist")
    # balance (priority 14)
    if outstanding(member["id"]) >= SUSPEND_THRESHOLD_CENTS:
        raise ApiError("ERR_BALANCE_LIMIT_EXCEEDED", 402, "balance limit exceeded")
    loan["due_date"] = loan["due_date"] + timedelta(days=item["loan_period_days"])
    loan["renewals_used"] += 1
    touch(loan)
    return ok(serialize(loan))


@app.route("/library/loans/<loan_id>/return", methods=["POST"])
def return_loan(loan_id):
    auth(["Volunteer", "Coordinator"])
    loan = get_or_404(loans, loan_id, "ERR_LOAN_NOT_FOUND")
    b = get_body()
    return_condition = check_enum(
        require(b, "return_condition"), ("GOOD", "MINOR_DAMAGE", "MAJOR_DAMAGE", "LOST")
    )
    # loan state (priority 7)
    if loan["status"] not in ("ACTIVE", "OVERDUE"):
        raise ApiError("ERR_LOAN_NOT_ACTIVE", 409, "loan not ACTIVE/OVERDUE")
    copy = copies[loan["copy_id"]]
    item = items[loan["item_id"]]
    member = members[loan["member_id"]]
    obs = NOW
    loan["status"] = "RETURNED"
    loan["return_condition"] = return_condition
    loan["returned_at"] = obs
    touch(loan)
    # finalize accruing late fee
    late = find_accruing_late_fee(loan["id"])
    if late is not None:
        late["amount_cents"] = late_fee_amount(item, loan, obs)
        late["status"] = "PENDING"
        touch(late)
    # condition handling
    if return_condition == "GOOD":
        copy["availability_status"] = "AVAILABLE"
        touch(copy)
        touch(item)
        try_promote(item)
    elif return_condition in ("MINOR_DAMAGE", "MAJOR_DAMAGE"):
        copy["availability_status"] = "AVAILABLE"
        copy["condition_status"] = "NEEDS_MAINTENANCE"
        touch(copy)
        severity = "MINOR" if return_condition == "MINOR_DAMAGE" else "MAJOR"
        ticket = new_entity(
            copy_id=copy["id"],
            reason="DAMAGE",
            severity=severity,
            source="DAMAGE_INTAKE",
            scheduled_start=None,
            scheduled_end=None,
            outcome=None,
            status="OPEN",
        )
        tickets[ticket["id"]] = ticket
        amount, ftype = damage_amount(item, copy, return_condition, obs)
        create_fee(member["id"], loan["id"], ftype, amount, "PENDING", obs)
        touch(item)
    else:  # LOST
        copy["condition_status"] = "RETIRED"
        touch(copy)
        amount, ftype = damage_amount(item, copy, return_condition, obs)
        create_fee(member["id"], loan["id"], ftype, amount, "PENDING", obs)
        touch(item)
    touch(member)
    check_suspend(member)
    return ok(serialize(loan))


# =========================================================================== #
# Holds / waitlist
# =========================================================================== #
@app.route("/library/holds", methods=["POST"])
def create_hold():
    uid, role = auth(["Member"])
    b = get_body()
    member_id = b.get("member_id")
    item_id = b.get("item_id")
    if member_id is not None and member_id not in members:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member not found")
    if item_id is not None and item_id not in items:
        raise ApiError("ERR_ITEM_NOT_FOUND", 404, "item not found")
    if role == "Member" and member_id is not None and member_id != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    require(b, "member_id")
    require(b, "item_id")
    member = members[member_id]
    # member active (priority 6)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "member not active")
    # copy-available / duplicate (priority 12)
    if item_counts(item_id)["available_copies_count"] > 0:
        raise ApiError("ERR_COPY_AVAILABLE_NO_HOLD", 409, "available copy exists; cannot join waitlist")
    if any(
        h["member_id"] == member_id and h["item_id"] == item_id and h["status"] in ("PENDING", "PROMOTED")
        for h in holds.values()
    ):
        raise ApiError("ERR_DUPLICATE_HOLD", 409, "duplicate hold")
    # hold limit (priority 13)
    active_holds = sum(
        1 for h in holds.values() if h["member_id"] == member_id and h["status"] in ("PENDING", "PROMOTED")
    )
    if active_holds >= member["max_active_holds"]:
        raise ApiError("ERR_HOLD_LIMIT_EXCEEDED", 409, "hold limit exceeded")
    hold = new_entity(
        member_id=member_id,
        item_id=item_id,
        promoted_reservation_id=None,
        claim_deadline=None,
        status="PENDING",
    )
    holds[hold["id"]] = hold
    return ok(serialize(hold), 201)


@app.route("/library/holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    auth(["Member", "Volunteer", "Coordinator"])
    h = get_or_404(holds, hold_id, "ERR_HOLD_NOT_FOUND")
    return ok(serialize(h))


@app.route("/library/holds", methods=["GET"])
def list_holds():
    auth(["Member", "Volunteer", "Coordinator"])
    rows = list(holds.values())
    mid = request.args.get("member_id")
    iid = request.args.get("item_id")
    st = request.args.get("status")
    if mid:
        rows = [h for h in rows if h["member_id"] == mid]
    if iid:
        rows = [h for h in rows if h["item_id"] == iid]
    if st:
        rows = [h for h in rows if h["status"] == st]
    page, meta = paginate(rows)
    return ok([serialize(h) for h in page], 200, "array", meta)


# =========================================================================== #
# Fees
# =========================================================================== #
@app.route("/library/fees/<fee_id>", methods=["GET"])
def get_fee(fee_id):
    auth(["Member", "Volunteer", "Coordinator"])
    f = get_or_404(fees, fee_id, "ERR_FEE_NOT_FOUND")
    return ok(serialize(f))


@app.route("/library/fees", methods=["GET"])
def list_fees():
    auth(["Member", "Volunteer", "Coordinator"])
    rows = list(fees.values())
    mid = request.args.get("member_id")
    lid = request.args.get("loan_id")
    st = request.args.get("status")
    if mid:
        rows = [f for f in rows if f["member_id"] == mid]
    if lid:
        rows = [f for f in rows if f.get("loan_id") == lid]
    if st:
        rows = [f for f in rows if f["status"] == st]
    page, meta = paginate(rows)
    return ok([serialize(f) for f in page], 200, "array", meta)


@app.route("/library/fees/<fee_id>/pay", methods=["POST"])
def pay_fee(fee_id):
    uid, role = auth(["Member", "Volunteer", "Coordinator"])
    f = get_or_404(fees, fee_id, "ERR_FEE_NOT_FOUND")
    if role == "Member" and f["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    if f["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "fee not PENDING")
    f["status"] = "PAID"
    touch(f)
    member = members.get(f["member_id"])
    if member:
        touch(member)
    return ok(serialize(f))


@app.route("/library/fees/<fee_id>/waive", methods=["POST"])
def waive_fee(fee_id):
    auth(["Coordinator"])
    f = get_or_404(fees, fee_id, "ERR_FEE_NOT_FOUND")
    if f["status"] not in ("ACCRUING", "PENDING"):
        raise ApiError("ERR_INVALID_STATE", 409, "fee not waivable")
    f["status"] = "WAIVED"
    touch(f)
    member = members.get(f["member_id"])
    if member:
        touch(member)
    return ok(serialize(f))


# =========================================================================== #
# Donations / intake
# =========================================================================== #
@app.route("/library/donations", methods=["POST"])
def create_donation():
    auth(["Member", "Volunteer", "Coordinator"])
    b = get_body()
    item_id = b.get("item_id")
    if item_id is not None and item_id not in items:
        raise ApiError("ERR_ITEM_NOT_FOUND", 404, "item not found")
    donor_name = require(b, "donor_name")
    require(b, "item_id")
    proposed_condition = check_enum(require(b, "proposed_condition"), ("GOOD", "FAIR"))
    donation = new_entity(
        donor_name=donor_name,
        donor_member_id=b.get("donor_member_id"),
        item_id=item_id,
        proposed_condition=proposed_condition,
        created_copy_id=None,
        status="OFFERED",
    )
    donations[donation["id"]] = donation
    return ok(serialize(donation), 201)


@app.route("/library/donations/<donation_id>", methods=["GET"])
def get_donation(donation_id):
    auth(["Volunteer", "Coordinator"])
    d = get_or_404(donations, donation_id, "ERR_DONATION_NOT_FOUND")
    return ok(serialize(d))


@app.route("/library/donations", methods=["GET"])
def list_donations():
    auth(["Volunteer", "Coordinator"])
    rows = list(donations.values())
    iid = request.args.get("item_id")
    st = request.args.get("status")
    if iid:
        rows = [d for d in rows if d["item_id"] == iid]
    if st:
        rows = [d for d in rows if d["status"] == st]
    page, meta = paginate(rows)
    return ok([serialize(d) for d in page], 200, "array", meta)


@app.route("/library/donations/<donation_id>/accept", methods=["POST"])
def accept_donation(donation_id):
    auth(["Volunteer", "Coordinator"])
    d = get_or_404(donations, donation_id, "ERR_DONATION_NOT_FOUND")
    b = get_body()
    asset_tag = require(b, "asset_tag")
    if d["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "donation not OFFERED")
    item = items.get(d["item_id"])
    if item is None:
        raise ApiError("ERR_ITEM_NOT_FOUND", 404, "item no longer exists")
    acquired_on = _parse_dt(b.get("acquired_on")) if b.get("acquired_on") else NOW
    copy = new_entity(
        item_id=item["id"],
        asset_tag=asset_tag,
        acquired_on=acquired_on,
        origin="DONATION",
        availability_status="AVAILABLE",
        condition_status="GOOD",
    )
    copies[copy["id"]] = copy
    d["status"] = "ACCEPTED"
    d["created_copy_id"] = copy["id"]
    touch(d)
    touch(item)
    try_promote(item)
    return ok(serialize(d))


@app.route("/library/donations/<donation_id>/reject", methods=["POST"])
def reject_donation(donation_id):
    auth(["Volunteer", "Coordinator"])
    d = get_or_404(donations, donation_id, "ERR_DONATION_NOT_FOUND")
    if d["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "donation not OFFERED")
    d["status"] = "REJECTED"
    touch(d)
    return ok(serialize(d))


# =========================================================================== #
# Maintenance
# =========================================================================== #
@app.route("/library/maintenance-tickets", methods=["POST"])
def create_ticket():
    auth(["Volunteer", "Coordinator"])
    b = get_body()
    copy_id = b.get("copy_id")
    if copy_id is not None and copy_id not in copies:
        raise ApiError("ERR_COPY_NOT_FOUND", 404, "copy not found")
    require(b, "copy_id")
    reason = check_enum(require(b, "reason"), ("DAMAGE", "ROUTINE", "INSPECTION"))
    severity = b.get("severity")
    if severity is not None:
        check_enum(severity, ("MINOR", "MAJOR"))
    scheduled_start = _parse_dt(b.get("scheduled_start")) if b.get("scheduled_start") else None
    scheduled_end = _parse_dt(b.get("scheduled_end")) if b.get("scheduled_end") else None
    copy = copies[copy_id]
    # maintenance window conflict (priority 10)
    if scheduled_start is not None and scheduled_end is not None:
        buf = timedelta(days=MAINTENANCE_BUFFER_DAYS)
        for l in loans.values():
            if l["copy_id"] == copy_id and l["status"] in ("ACTIVE", "OVERDUE"):
                lo = l["checked_out_at"] - buf
                hi = l["due_date"] + buf
                # closed-interval overlap
                if scheduled_start <= hi and lo <= scheduled_end:
                    raise ApiError("ERR_MAINTENANCE_WINDOW_CONFLICT", 409, "maintenance window conflict")
    ticket = new_entity(
        copy_id=copy_id,
        reason=reason,
        severity=severity,
        source="MANUAL",
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        outcome=None,
        status="OPEN",
    )
    tickets[ticket["id"]] = ticket
    # immediate service (no scheduled window): move GOOD -> NEEDS_MAINTENANCE
    if scheduled_start is None and copy["condition_status"] == "GOOD":
        copy["condition_status"] = "NEEDS_MAINTENANCE"
        touch(copy)
        item = items.get(copy["item_id"])
        if item:
            touch(item)
    return ok(serialize(ticket), 201)


@app.route("/library/maintenance-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    auth(["Volunteer", "Coordinator"])
    t = get_or_404(tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    return ok(serialize(t))


@app.route("/library/maintenance-tickets", methods=["GET"])
def list_tickets():
    auth(["Volunteer", "Coordinator"])
    rows = list(tickets.values())
    cid = request.args.get("copy_id")
    st = request.args.get("status")
    if cid:
        rows = [t for t in rows if t["copy_id"] == cid]
    if st:
        rows = [t for t in rows if t["status"] == st]
    page, meta = paginate(rows)
    return ok([serialize(t) for t in page], 200, "array", meta)


@app.route("/library/maintenance-tickets/<ticket_id>/resolve", methods=["POST"])
def resolve_ticket(ticket_id):
    auth(["Volunteer", "Coordinator"])
    t = get_or_404(tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    b = get_body()
    outcome = check_enum(require(b, "outcome"), ("RETURN_TO_SERVICE", "SCRAP"))
    if t["status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", 409, "ticket not OPEN/IN_PROGRESS")
    copy = copies[t["copy_id"]]
    item = items.get(copy["item_id"])
    if outcome == "RETURN_TO_SERVICE":
        copy["condition_status"] = "GOOD"
        copy["availability_status"] = "AVAILABLE"
        touch(copy)
        if item:
            touch(item)
        t["status"] = "RESOLVED"
        t["outcome"] = outcome
        touch(t)
        if item:
            try_promote(item)
    else:  # SCRAP
        copy["condition_status"] = "RETIRED"
        touch(copy)
        if item:
            touch(item)
        t["status"] = "RESOLVED"
        t["outcome"] = outcome
        touch(t)
    return ok(serialize(t))


# =========================================================================== #
# Reporting
# =========================================================================== #
@app.route("/library/reports/usage", methods=["GET"])
def usage_report():
    auth(["Coordinator"])
    from_date = _parse_dt(request.args.get("from_date")) if request.args.get("from_date") else datetime(1970, 1, 1, tzinfo=timezone.utc)
    to_date = _parse_dt(request.args.get("to_date")) if request.args.get("to_date") else NOW
    category = request.args.get("category")
    if category is not None:
        check_enum(category, ("TOOL", "OUTDOOR", "KITCHEN"))
        cats = [category]
    else:
        cats = ["TOOL", "OUTDOOR", "KITCHEN"]
    loans_by_category = {}
    for cat in cats:
        cnt = 0
        for l in loans.values():
            it = items.get(l["item_id"])
            if it and it["category"] == cat and from_date <= l["checked_out_at"] <= to_date:
                cnt += 1
        loans_by_category[cat] = cnt
    active_loans = sum(1 for l in loans.values() if l["status"] in ("ACTIVE", "OVERDUE"))
    overdue_loans = sum(1 for l in loans.values() if l["status"] == "OVERDUE")
    fees_collected = sum(
        f["amount_cents"] for f in fees.values()
        if f["status"] == "PAID" and from_date <= f["assessed_at"] <= to_date
    )
    copies_retired = sum(1 for c in copies.values() if c["condition_status"] == "RETIRED")
    data = {
        "loans_by_category": loans_by_category,
        "active_loans": active_loans,
        "overdue_loans": overdue_loans,
        "fees_collected_cents": fees_collected,
        "copies_retired": copies_retired,
    }
    return ok(data)


# =========================================================================== #
# System / clock / ops
# =========================================================================== #
@app.route("/library/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global NOW
    auth(["Coordinator"])
    b = get_body()
    to_iso = require(b, "to_iso8601")
    NOW = _parse_dt(to_iso)
    return ok({"current_utc": iso(NOW)})


@app.route("/library/_ops/run", methods=["POST"])
def ops_run():
    global _promotions
    auth(["Coordinator"])
    now = NOW
    counts = {
        "overdue_count": 0,
        "lost_count": 0,
        "expired_reservations": 0,
        "promoted_holds": 0,
        "expired_holds": 0,
        "reinstated_members": 0,
        "expired_members": 0,
    }
    promo_start = _promotions

    # 1. ACTIVE loans past due -> OVERDUE, ensure ACCRUING late fee
    for loan in list(loans.values()):
        if loan["status"] == "ACTIVE" and now > loan["due_date"]:
            loan["status"] = "OVERDUE"
            touch(loan)
            item = items[loan["item_id"]]
            if find_accruing_late_fee(loan["id"]) is None:
                amt = late_fee_amount(item, loan, now)
                create_fee(loan["member_id"], loan["id"], "LATE", amt, "ACCRUING", now)
            counts["overdue_count"] += 1

    # 2. accrue late fees on all OVERDUE loans, check suspension
    for loan in list(loans.values()):
        if loan["status"] == "OVERDUE":
            item = items[loan["item_id"]]
            fee = find_accruing_late_fee(loan["id"])
            if fee is None:
                amt = late_fee_amount(item, loan, now)
                fee = create_fee(loan["member_id"], loan["id"], "LATE", amt, "ACCRUING", now)
            else:
                fee["amount_cents"] = late_fee_amount(item, loan, now)
                touch(fee)
            member = members[loan["member_id"]]
            touch(member)
            check_suspend(member)

    # 3. OVERDUE loans stale >= LOST_THRESHOLD_DAYS -> LOST
    for loan in list(loans.values()):
        if loan["status"] == "OVERDUE":
            days_over = math.floor((now - loan["due_date"]).total_seconds() / 86400)
            if days_over >= LOST_THRESHOLD_DAYS:
                loan["status"] = "LOST"
                touch(loan)
                copy = copies[loan["copy_id"]]
                item = items[loan["item_id"]]
                copy["condition_status"] = "RETIRED"
                touch(copy)
                fee = find_accruing_late_fee(loan["id"])
                if fee is not None:
                    fee["amount_cents"] = late_fee_amount(item, loan, now)
                    fee["status"] = "PENDING"
                    touch(fee)
                amount, ftype = damage_amount(item, copy, "LOST", now)
                create_fee(loan["member_id"], loan["id"], ftype, amount, "PENDING", now)
                touch(item)
                member = members[loan["member_id"]]
                touch(member)
                check_suspend(member)
                counts["lost_count"] += 1

    # 4. expire promoted holds past claim deadline (cancels reservation, promotes next)
    for hold in list(holds.values()):
        if hold["status"] == "PROMOTED" and hold.get("claim_deadline") and now >= hold["claim_deadline"]:
            hold["status"] = "EXPIRED"
            touch(hold)
            res = reservations.get(hold.get("promoted_reservation_id"))
            if res and res["status"] == "PENDING":
                res["status"] = "CANCELLED"
                touch(res)
                release_reservation_copy(res)
            counts["expired_holds"] += 1

    # 5. expire reservations whose window has closed
    for res in list(reservations.values()):
        if res["status"] == "PENDING" and now >= res["window_end"]:
            res["status"] = "EXPIRED"
            touch(res)
            release_reservation_copy(res)
            counts["expired_reservations"] += 1

    # 6. general promotion sweep (items with available copies + pending holds)
    changed = True
    while changed:
        changed = False
        for item in list(items.values()):
            if try_promote(item):
                changed = True

    # 7. scheduled maintenance start: OPEN tickets whose scheduled_start reached
    for t in list(tickets.values()):
        if t["status"] == "OPEN" and t.get("scheduled_start") and now >= t["scheduled_start"]:
            t["status"] = "IN_PROGRESS"
            touch(t)
            copy = copies.get(t["copy_id"])
            if copy and copy["condition_status"] != "RETIRED":
                copy["condition_status"] = "UNDER_MAINTENANCE"
                touch(copy)
                item = items.get(copy["item_id"])
                if item:
                    touch(item)

    # 8. reinstate members whose balance cleared
    for member in list(members.values()):
        if member["status"] == "SUSPENDED" and outstanding(member["id"]) == 0:
            member["status"] = "ACTIVE"
            touch(member)
            counts["reinstated_members"] += 1

    # 9. expire memberships past expiry instant
    for member in list(members.values()):
        if member["status"] in ("ACTIVE", "SUSPENDED") and member.get("membership_expires_at") and now >= member["membership_expires_at"]:
            member["status"] = "EXPIRED"
            touch(member)
            cascade_member_release(member)
            counts["expired_members"] += 1

    counts["promoted_holds"] = _promotions - promo_start
    return ok(counts)


@app.route("/", methods=["GET"])
def health():
    return ok({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
