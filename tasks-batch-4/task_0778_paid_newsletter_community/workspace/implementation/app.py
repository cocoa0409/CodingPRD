import os
import math
import uuid
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

UTC = timezone.utc
PERIOD = timedelta(days=30)

# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot — no seeding)
# ---------------------------------------------------------------------------
DB = {
    "publications": {},
    "tiers": {},
    "members": {},
    "subscriptions": {},
    "invoices": {},
    "posts": {},
    "events": {},
    "registrations": {},
    "comments": {},
    "payouts": {},
}

CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)}

ROLES = {"Creator", "Member", "Moderator", "PlatformAdmin", "Anonymous"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now():
    return CLOCK["now"]


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    if not isinstance(s, str):
        err("ERR_VALIDATION", 422, "invalid datetime")
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
    except Exception:
        err("ERR_VALIDATION", 422, "invalid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def rhu(numerator, denominator=1):
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def create_entity(kind, fields):
    ts = now()
    e = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    e.update(fields)
    DB[kind][e["id"]] = e
    return e


def touch(e):
    e["updated_at"] = now()
    e["version"] += 1


def serialize(e):
    out = {}
    for k, v in e.items():
        if isinstance(v, datetime):
            out[k] = iso(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": iso(now())}
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", code=200, meta_extra=None):
    return jsonify({"meta": make_meta(meta_extra), "response_type": response_type, "data": data}), code


def ok_obj(entity, code=200):
    return ok(serialize(entity), "object", code)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(allowed):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "missing or invalid X-User-Role")
    if role != "Anonymous" and not uid:
        err("ERR_UNAUTHENTICATED", 401, "missing X-User-ID")
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "role not permitted for this endpoint")
    return role, uid


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", 422, "body must be a JSON object")
    return data


def field_str(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            err("ERR_VALIDATION", 422, "missing field: %s" % key)
        return default
    v = data[key]
    if not isinstance(v, str):
        err("ERR_VALIDATION", 422, "field %s must be a string" % key)
    return v


def field_int(data, key, required=True, default=None, minv=None, maxv=None):
    if key not in data or data[key] is None:
        if required:
            err("ERR_VALIDATION", 422, "missing field: %s" % key)
        return default
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 422, "field %s must be an integer" % key)
    if minv is not None and v < minv:
        err("ERR_VALIDATION", 422, "field %s below minimum" % key)
    if maxv is not None and v > maxv:
        err("ERR_VALIDATION", 422, "field %s above maximum" % key)
    return v


def field_bool(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            err("ERR_VALIDATION", 422, "missing field: %s" % key)
        return default
    v = data[key]
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 422, "field %s must be a boolean" % key)
    return v


def field_enum(data, key, choices, required=True, default=None):
    v = field_str(data, key, required=required, default=default)
    if v is None:
        return None
    if v not in choices:
        err("ERR_VALIDATION", 422, "field %s must be one of %s" % (key, sorted(choices)))
    return v


# ---------------------------------------------------------------------------
# Pagination + list responses
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except Exception:
            limit = 10
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except Exception:
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items):
    # stable sort by created_at ASC (insertion order preserved on ties)
    items = sorted(items, key=lambda e: e["created_at"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serialize(i) for i in page], "array", 200, meta_extra)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(kind, ident, error_id):
    e = DB[kind].get(ident)
    if e is None:
        err(error_id, 404)
    return e


def pub_of_sub(sub):
    m = DB["members"].get(sub["member_id"])
    if m is None:
        return None
    return m["publication_id"]


def pub_of_invoice(inv):
    sub = DB["subscriptions"].get(inv["subscription_id"])
    if sub is None:
        return None
    return pub_of_sub(sub)


def pub_of_post(post):
    return post["publication_id"]


# ---------------------------------------------------------------------------
# Publication recompute
# ---------------------------------------------------------------------------
def recompute_pub(pub):
    pid = pub["id"]
    active_member_ids = set()
    mrr = 0
    for sub in DB["subscriptions"].values():
        if pub_of_sub(sub) != pid:
            continue
        if sub["status"] in ("ACTIVE", "TRIALING"):
            active_member_ids.add(sub["member_id"])
            tier = DB["tiers"].get(sub["tier_id"])
            if tier:
                mrr += tier["monthly_price_cents"]
    pub["active_member_count"] = len(active_member_ids)
    pub["mrr_cents"] = mrr

    recognized = 0
    for inv in DB["invoices"].values():
        if pub_of_invoice(inv) != pid:
            continue
        if inv["payment_status"] == "PAID" and inv["paid_at"] is not None and inv["paid_at"] <= now():
            recognized += inv["creator_net_cents"]
    pub["recognized_revenue_cents"] = recognized

    pub["bounce_rate"] = pub["bounce_count"] / max(1, pub["sent_count"])


def pub_event(pub):
    recompute_pub(pub)
    touch(pub)


def credit_invoice(pub, inv):
    fee = rhu(inv["amount_due_cents"] * pub["platform_fee_bps"], 10000)
    net = inv["amount_due_cents"] - fee
    inv["platform_fee_cents"] = fee
    inv["creator_net_cents"] = net
    pub["lifetime_net_cents"] += net
    pub["payout_balance_cents"] += net


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------
def require_pub_owner(pub, role, uid):
    if role == "Creator" and pub["creator_user_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "creator does not own this publication")


def member_gate(member_id, publication_id, min_tier_rank):
    """Content/community gating: requires an ACTIVE subscription of sufficient rank."""
    active = []
    for sub in DB["subscriptions"].values():
        if sub["member_id"] != member_id:
            continue
        if sub["status"] != "ACTIVE":
            continue
        if pub_of_sub(sub) != publication_id:
            continue
        active.append(sub)
    if not active:
        err("ERR_SUBSCRIPTION_REQUIRED", 403, "an active subscription is required")
    if not any(s["current_tier_rank"] >= min_tier_rank for s in active):
        err("ERR_TIER_TOO_LOW", 403, "subscription tier is below the required minimum")


# ===========================================================================
# Test-driving endpoints
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"PlatformAdmin"})
    data = body()
    ts = parse_iso(field_str(data, "to_iso8601"))
    CLOCK["now"] = ts
    return ok({"current_utc": iso(ts)}, "object", 200)


@app.route("/_email/bounce", methods=["POST"])
def email_bounce():
    auth({"PlatformAdmin"})
    data = body()
    member_id = field_str(data, "member_id")
    member = get_or_404("members", member_id, "ERR_MEMBER_NOT_FOUND")
    pub = DB["publications"].get(member["publication_id"])
    member["email_bounced"] = True
    member["status"] = "BOUNCED"
    touch(member)
    if pub is not None:
        pub["bounce_count"] += 1
        rate = pub["bounce_count"] / max(1, pub["sent_count"])
        pub["bounce_rate"] = rate
        if rate >= 0.50:
            pub["deliverability_status"] = "SUSPENDED"
        elif rate >= 0.20:
            if pub["deliverability_status"] == "HEALTHY":
                pub["deliverability_status"] = "THROTTLED"
        touch(pub)
    return ok_obj(member)


@app.route("/_payments/simulate", methods=["POST"])
def payments_simulate():
    auth({"PlatformAdmin"})
    data = body()
    invoice_id = field_str(data, "invoice_id")
    outcome = field_enum(data, "outcome", {"SUCCEEDED", "FAILED", "REFUNDED"})
    inv = get_or_404("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    sub = DB["subscriptions"].get(inv["subscription_id"])
    pub = None
    if sub is not None:
        pid = pub_of_sub(sub)
        pub = DB["publications"].get(pid)

    if outcome == "SUCCEEDED":
        if inv["payment_status"] not in ("OPEN", "FAILED"):
            err("ERR_INVALID_STATE", 409, "invoice cannot be paid from its current state")
        activating = sub is not None and (
            (inv["reason"] == "INITIAL" and sub["status"] == "TRIALING")
            or (inv["reason"] == "RENEWAL" and sub["status"] == "PAST_DUE")
        )
        if activating and pub is not None and pub["status"] != "ACTIVE":
            err("ERR_PUBLICATION_SUSPENDED", 409, "publication is suspended")
        inv["payment_status"] = "PAID"
        inv["paid_at"] = now()
        if pub is not None:
            credit_invoice(pub, inv)
        if sub is not None:
            if inv["reason"] == "INITIAL" and sub["status"] == "TRIALING":
                sub["status"] = "ACTIVE"
                sub["current_period_start"] = now()
                sub["current_period_end"] = now() + PERIOD
                touch(sub)
            elif inv["reason"] == "RENEWAL" and sub["status"] == "PAST_DUE":
                sub["status"] = "ACTIVE"
                sub["dunning_deadline"] = None
                touch(sub)
        touch(inv)
        if pub is not None:
            pub_event(pub)

    elif outcome == "FAILED":
        if inv["payment_status"] != "OPEN":
            err("ERR_INVALID_STATE", 409, "invoice cannot fail from its current state")
        inv["payment_status"] = "FAILED"
        if sub is not None:
            if inv["reason"] == "INITIAL" and sub["status"] == "TRIALING":
                sub["status"] = "EXPIRED"
                touch(sub)
            elif inv["reason"] == "RENEWAL" and sub["status"] == "ACTIVE":
                sub["status"] = "PAST_DUE"
                sub["dunning_deadline"] = now() + timedelta(days=7)
                touch(sub)
        touch(inv)
        if pub is not None:
            pub_event(pub)

    else:  # REFUNDED
        if inv["payment_status"] != "PAID":
            err("ERR_INVALID_STATE", 409, "only paid invoices can be refunded")
        inv["payment_status"] = "REFUNDED"
        if pub is not None:
            pub["lifetime_net_cents"] -= inv["creator_net_cents"]
            pub["payout_balance_cents"] -= inv["creator_net_cents"]
        touch(inv)
        if pub is not None:
            pub_event(pub)

    return ok_obj(inv)


# ===========================================================================
# Publications
# ===========================================================================
@app.route("/publications", methods=["POST"])
def create_publication():
    role, uid = auth({"Creator"})
    data = body()
    name = field_str(data, "name")
    fee = field_int(data, "platform_fee_bps", required=False, default=1000, minv=0, maxv=3000)
    pub = create_entity("publications", {
        "name": name,
        "creator_user_id": uid,
        "platform_fee_bps": fee,
        "status": "ACTIVE",
        "deliverability_status": "HEALTHY",
        "sent_count": 0,
        "bounce_count": 0,
        "bounce_rate": 0.0,
        "lifetime_net_cents": 0,
        "payout_balance_cents": 0,
        "pending_payout_cents": 0,
        "lifetime_paid_out_cents": 0,
        "active_member_count": 0,
        "mrr_cents": 0,
        "recognized_revenue_cents": 0,
    })
    return ok_obj(pub, 201)


@app.route("/publications/<pid>", methods=["GET"])
def get_publication(pid):
    auth({"Anonymous", "Member", "Creator", "Moderator", "PlatformAdmin"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    return ok_obj(pub)


@app.route("/publications/<pid>/suspend", methods=["POST"])
def suspend_publication(pid):
    auth({"PlatformAdmin"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    if pub["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "publication is not ACTIVE")
    pub["status"] = "SUSPENDED"
    touch(pub)
    return ok_obj(pub)


@app.route("/publications/<pid>/deliverability-reset", methods=["POST"])
def deliverability_reset(pid):
    role, uid = auth({"Creator", "PlatformAdmin"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    require_pub_owner(pub, role, uid)
    pub["bounce_count"] = 0
    pub["sent_count"] = 0
    pub["bounce_rate"] = 0.0
    pub["deliverability_status"] = "HEALTHY"
    touch(pub)
    return ok_obj(pub)


@app.route("/publications/<pid>/analytics", methods=["GET"])
def publication_analytics(pid):
    role, uid = auth({"Creator", "PlatformAdmin"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    require_pub_owner(pub, role, uid)
    recompute_pub(pub)
    return ok_obj(pub)


# ===========================================================================
# Tiers
# ===========================================================================
@app.route("/publications/<pid>/tiers", methods=["POST"])
def create_tier(pid):
    role, uid = auth({"Creator"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    require_pub_owner(pub, role, uid)
    data = body()
    name = field_str(data, "name")
    tier_rank = field_int(data, "tier_rank", minv=0)
    price = field_int(data, "monthly_price_cents", minv=0)
    trial_days = field_int(data, "trial_days", required=False, default=0, minv=0)
    for t in DB["tiers"].values():
        if t["publication_id"] == pid and t["tier_rank"] == tier_rank:
            err("ERR_TIER_RANK_TAKEN", 409, "tier_rank already used in this publication")
    tier = create_entity("tiers", {
        "publication_id": pid,
        "name": name,
        "tier_rank": tier_rank,
        "monthly_price_cents": price,
        "trial_days": trial_days,
        "is_free": tier_rank == 0,
    })
    return ok_obj(tier, 201)


@app.route("/publications/<pid>/tiers", methods=["GET"])
def list_tiers(pid):
    auth({"Anonymous", "Member", "Creator", "PlatformAdmin"})
    get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    items = [t for t in DB["tiers"].values() if t["publication_id"] == pid]
    return list_response(items)


# ===========================================================================
# Members
# ===========================================================================
@app.route("/publications/<pid>/members", methods=["POST"])
def create_member(pid):
    role, uid = auth({"Anonymous", "Creator"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    if role == "Creator":
        require_pub_owner(pub, role, uid)
    data = body()
    email = field_str(data, "email")
    display_name = field_str(data, "display_name")
    for m in DB["members"].values():
        if m["publication_id"] == pid and m["email"] == email:
            err("ERR_EMAIL_TAKEN", 409, "email already registered in this publication")
    member = create_entity("members", {
        "publication_id": pid,
        "email": email,
        "display_name": display_name,
        "status": "PENDING",
        "verification_token": new_id(),
        "email_bounced": False,
    })
    return ok_obj(member, 201)


@app.route("/publications/<pid>/members", methods=["GET"])
def list_members(pid):
    auth({"Creator", "PlatformAdmin"})
    get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    items = [m for m in DB["members"].values() if m["publication_id"] == pid]
    return list_response(items)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    auth({"Member", "Creator", "PlatformAdmin"})
    member = get_or_404("members", mid, "ERR_MEMBER_NOT_FOUND")
    return ok_obj(member)


@app.route("/members/<mid>/verify", methods=["POST"])
def verify_member(mid):
    auth({"Anonymous", "Member"})
    member = get_or_404("members", mid, "ERR_MEMBER_NOT_FOUND")
    data = body()
    token = field_str(data, "verification_token")
    if token != member["verification_token"]:
        err("ERR_VALIDATION", 422, "invalid verification token")
    member["status"] = "VERIFIED"
    touch(member)
    return ok_obj(member)


# ===========================================================================
# Subscriptions
# ===========================================================================
@app.route("/members/<mid>/subscriptions", methods=["POST"])
def create_subscription(mid):
    role, uid = auth({"Member", "Creator"})
    member = get_or_404("members", mid, "ERR_MEMBER_NOT_FOUND")
    pub = DB["publications"].get(member["publication_id"])
    # ownership
    if role == "Member" and member["id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "member may only act on their own subscription")
    if role == "Creator":
        if pub is None or pub["creator_user_id"] != uid:
            err("ERR_NOT_RESOURCE_OWNER", 403, "creator does not own this member's publication")
    data = body()
    tier_id = field_str(data, "tier_id")
    # referential
    if member["status"] != "VERIFIED":
        err("ERR_MEMBER_NOT_VERIFIED", 409, "member must be VERIFIED before subscribing")
    tier = DB["tiers"].get(tier_id)
    if tier is None:
        err("ERR_TIER_NOT_FOUND", 404, "tier does not exist")
    if tier["publication_id"] != member["publication_id"]:
        err("ERR_TIER_PUBLICATION_MISMATCH", 409, "tier does not belong to member's publication")

    is_free = tier["tier_rank"] == 0
    if is_free and pub is not None and pub["status"] != "ACTIVE":
        err("ERR_PUBLICATION_SUSPENDED", 409, "publication is suspended")

    sub_fields = {
        "member_id": member["id"],
        "tier_id": tier_id,
        "status": "TRIALING",
        "current_tier_rank": tier["tier_rank"],
        "current_period_start": None,
        "current_period_end": None,
        "trial_end": None,
        "canceled_at": None,
        "dunning_deadline": None,
        "reactivation_count": 0,
        "is_win_back": False,
    }

    if is_free:
        sub_fields["status"] = "ACTIVE"
        sub_fields["current_period_start"] = now()
        sub_fields["current_period_end"] = now() + PERIOD
        sub = create_entity("subscriptions", sub_fields)
    else:
        trial_end = now() + timedelta(days=tier["trial_days"])
        sub_fields["trial_end"] = trial_end
        sub = create_entity("subscriptions", sub_fields)
        # INITIAL invoice
        create_entity("invoices", {
            "subscription_id": sub["id"],
            "reason": "INITIAL",
            "gross_cents": tier["monthly_price_cents"],
            "discount_cents": 0,
            "proration_factor": 1.0,
            "amount_due_cents": tier["monthly_price_cents"],
            "platform_fee_cents": 0,
            "creator_net_cents": 0,
            "payment_status": "OPEN",
            "due_at": trial_end,
            "paid_at": None,
        })

    if pub is not None:
        pub_event(pub)
    return ok_obj(sub, 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    auth({"Member", "Creator", "PlatformAdmin"})
    sub = get_or_404("subscriptions", sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    return ok_obj(sub)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    auth({"Member", "Creator", "PlatformAdmin"})
    member_id = request.args.get("member_id")
    tier_id = request.args.get("tier_id")
    items = []
    for s in DB["subscriptions"].values():
        if member_id is not None and s["member_id"] != member_id:
            continue
        if tier_id is not None and s["tier_id"] != tier_id:
            continue
        items.append(s)
    return list_response(items)


def _load_sub_for_owner_mutation(sid, role, uid):
    sub = get_or_404("subscriptions", sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    member = DB["members"].get(sub["member_id"])
    pub = DB["publications"].get(member["publication_id"]) if member else None
    if role == "Member" and sub["member_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "member may only act on their own subscription")
    if role == "Creator":
        if pub is None or pub["creator_user_id"] != uid:
            err("ERR_NOT_RESOURCE_OWNER", 403, "creator does not own this subscription")
    return sub, member, pub


@app.route("/subscriptions/<sid>/change-tier", methods=["POST"])
def change_tier(sid):
    role, uid = auth({"Member", "Creator"})
    sub, member, pub = _load_sub_for_owner_mutation(sid, role, uid)
    data = body()
    new_tier_id = field_str(data, "new_tier_id")
    expected = field_int(data, "expected_subscription_version", required=False, default=None)
    # state
    if sub["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "subscription must be ACTIVE to change tier")
    # referential
    new_tier = DB["tiers"].get(new_tier_id)
    if new_tier is None:
        err("ERR_TIER_NOT_FOUND", 404, "tier does not exist")
    if new_tier["publication_id"] != member["publication_id"]:
        err("ERR_TIER_PUBLICATION_MISMATCH", 409, "tier does not belong to member's publication")
    # OCC (checked last)
    if expected is not None and expected != sub["version"]:
        err("ERR_STALE_SUBSCRIPTION_VERSION", 412, "stale subscription version")

    old_tier = DB["tiers"].get(sub["tier_id"])
    delta = new_tier["monthly_price_cents"] - (old_tier["monthly_price_cents"] if old_tier else 0)
    if delta > 0:
        end = sub["current_period_end"]
        if end is not None:
            secs = (end - now()).total_seconds()
            remaining_days = math.ceil(secs / 86400.0)
        else:
            remaining_days = 0
        if remaining_days < 0:
            remaining_days = 0
        factor = remaining_days / 30.0
        charge = rhu(delta * remaining_days, 30)
        create_entity("invoices", {
            "subscription_id": sub["id"],
            "reason": "PRORATION_UPGRADE",
            "gross_cents": delta,
            "discount_cents": 0,
            "proration_factor": factor,
            "amount_due_cents": charge,
            "platform_fee_cents": 0,
            "creator_net_cents": 0,
            "payment_status": "OPEN",
            "due_at": now(),
            "paid_at": None,
        })

    sub["tier_id"] = new_tier_id
    sub["current_tier_rank"] = new_tier["tier_rank"]
    touch(sub)
    return ok_obj(sub)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    role, uid = auth({"Member", "Creator"})
    sub, member, pub = _load_sub_for_owner_mutation(sid, role, uid)
    data = body()
    reason = data.get("reason")
    if sub["status"] not in ("ACTIVE", "PAST_DUE"):
        err("ERR_INVALID_STATE", 409, "subscription cannot be canceled from its current state")
    if reason == "DUNNING":
        if sub["status"] != "PAST_DUE":
            err("ERR_INVALID_STATE", 409, "dunning cancel requires PAST_DUE")
        dd = sub["dunning_deadline"]
        if dd is None or now() < dd:
            err("ERR_INVALID_STATE", 409, "dunning deadline not reached")
    sub["status"] = "CANCELED"
    sub["canceled_at"] = now()
    touch(sub)
    # cascade: future REGISTERED registrations of this member
    for reg in list(DB["registrations"].values()):
        if reg["member_id"] != member["id"] or reg["status"] != "REGISTERED":
            continue
        ev = DB["events"].get(reg["event_id"])
        if ev is None or ev["starts_at"] <= now():
            continue
        reg["status"] = "CANCELED"
        touch(reg)
        ev["registered_count"] -= 1
        ev["available_slots"] = ev["capacity"] - ev["registered_count"]
        promote_waitlist(ev)
        touch(ev)
    if pub is not None:
        pub_event(pub)
    return ok_obj(sub)


@app.route("/subscriptions/<sid>/reactivate", methods=["POST"])
def reactivate_subscription(sid):
    role, uid = auth({"Member", "Creator"})
    sub, member, pub = _load_sub_for_owner_mutation(sid, role, uid)
    if sub["status"] != "CANCELED":
        err("ERR_INVALID_STATE", 409, "only CANCELED subscriptions can be reactivated")
    if pub is not None and pub["status"] != "ACTIVE":
        err("ERR_PUBLICATION_SUSPENDED", 409, "publication is suspended")
    canceled_at = sub["canceled_at"]
    if canceled_at is None or now() > canceled_at + timedelta(days=30):
        err("ERR_WINBACK_WINDOW_EXPIRED", 409, "win-back window has expired")
    tier = DB["tiers"].get(sub["tier_id"])
    price = tier["monthly_price_cents"] if tier else 0
    discount = rhu(price * 20, 100)
    sub["reactivation_count"] += 1
    sub["is_win_back"] = True
    sub["status"] = "ACTIVE"
    sub["current_period_start"] = now()
    sub["current_period_end"] = now() + PERIOD
    sub["canceled_at"] = None
    touch(sub)
    create_entity("invoices", {
        "subscription_id": sub["id"],
        "reason": "WIN_BACK",
        "gross_cents": price,
        "discount_cents": discount,
        "proration_factor": 1.0,
        "amount_due_cents": max(0, price - discount),
        "platform_fee_cents": 0,
        "creator_net_cents": 0,
        "payment_status": "OPEN",
        "due_at": now(),
        "paid_at": None,
    })
    if pub is not None:
        pub_event(pub)
    return ok_obj(sub)


@app.route("/subscriptions/<sid>/renew", methods=["POST"])
def renew_subscription(sid):
    role, uid = auth({"PlatformAdmin", "Creator"})
    sub = get_or_404("subscriptions", sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    member = DB["members"].get(sub["member_id"])
    pub = DB["publications"].get(member["publication_id"]) if member else None
    if role == "Creator":
        if pub is None or pub["creator_user_id"] != uid:
            err("ERR_NOT_RESOURCE_OWNER", 403, "creator does not own this subscription")
    if sub["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "subscription must be ACTIVE to renew")
    end = sub["current_period_end"]
    if end is None or now() < end:
        err("ERR_PERIOD_NOT_ENDED", 409, "current period has not ended")
    tier = DB["tiers"].get(sub["tier_id"])
    price = tier["monthly_price_cents"] if tier else 0
    create_entity("invoices", {
        "subscription_id": sub["id"],
        "reason": "RENEWAL",
        "gross_cents": price,
        "discount_cents": 0,
        "proration_factor": 1.0,
        "amount_due_cents": price,
        "platform_fee_cents": 0,
        "creator_net_cents": 0,
        "payment_status": "OPEN",
        "due_at": now(),
        "paid_at": None,
    })
    sub["current_period_start"] = end
    sub["current_period_end"] = end + PERIOD
    touch(sub)
    return ok_obj(sub)


# ===========================================================================
# Invoices
# ===========================================================================
@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    auth({"Member", "Creator", "PlatformAdmin"})
    inv = get_or_404("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    return ok_obj(inv)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    auth({"Member", "Creator", "PlatformAdmin"})
    subscription_id = request.args.get("subscription_id")
    items = []
    for inv in DB["invoices"].values():
        if subscription_id is not None and inv["subscription_id"] != subscription_id:
            continue
        items.append(inv)
    return list_response(items)


# ===========================================================================
# Posts / Newsletters
# ===========================================================================
@app.route("/publications/<pid>/posts", methods=["POST"])
def create_post(pid):
    role, uid = auth({"Creator"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    require_pub_owner(pub, role, uid)
    data = body()
    title = field_str(data, "title")
    text = field_str(data, "body")
    content_type = field_enum(data, "content_type", {"POST", "NEWSLETTER"}, required=False, default="POST")
    min_tier_rank = field_int(data, "min_tier_rank", required=False, default=0, minv=0)
    post = create_entity("posts", {
        "publication_id": pid,
        "title": title,
        "body": text,
        "content_type": content_type,
        "min_tier_rank": min_tier_rank,
        "status": "DRAFT",
        "send_window_start": None,
        "send_window_end": None,
        "recipient_count": 0,
        "approved_comment_count": 0,
    })
    return ok_obj(post, 201)


@app.route("/publications/<pid>/posts", methods=["GET"])
def list_posts(pid):
    auth({"Anonymous", "Member", "Creator", "PlatformAdmin"})
    get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    items = [p for p in DB["posts"].values() if p["publication_id"] == pid]
    return list_response(items)


@app.route("/posts/<post_id>/content", methods=["GET"])
def read_content(post_id):
    role, uid = auth({"Member", "Creator"})
    post = get_or_404("posts", post_id, "ERR_POST_NOT_FOUND")
    pub = DB["publications"].get(post["publication_id"])
    if role == "Creator":
        if pub is None or pub["creator_user_id"] != uid:
            err("ERR_NOT_RESOURCE_OWNER", 403, "creator does not own this post")
    else:  # Member
        member_gate(uid, post["publication_id"], post["min_tier_rank"])
    return ok_obj(post)


@app.route("/posts/<post_id>/publish", methods=["POST"])
def publish_post(post_id):
    role, uid = auth({"Creator"})
    post = get_or_404("posts", post_id, "ERR_POST_NOT_FOUND")
    pub = DB["publications"].get(post["publication_id"])
    require_pub_owner(pub, role, uid)
    if post["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "post must be DRAFT to publish")
    post["status"] = "PUBLISHED"
    touch(post)
    return ok_obj(post)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.route("/posts/<post_id>/send", methods=["POST"])
def send_post(post_id):
    role, uid = auth({"Creator"})
    post = get_or_404("posts", post_id, "ERR_POST_NOT_FOUND")
    pub = DB["publications"].get(post["publication_id"])
    require_pub_owner(pub, role, uid)
    # gating: deliverability
    if pub is not None and pub["deliverability_status"] == "SUSPENDED":
        err("ERR_DELIVERABILITY_SUSPENDED", 409, "deliverability is suspended")
    # temporal: send-window conflict
    win_start = now()
    win_end = now() + timedelta(minutes=60)
    for p in DB["posts"].values():
        if p["id"] == post_id:
            continue
        if p["publication_id"] != post["publication_id"]:
            continue
        if p["status"] == "SENT" and p["send_window_start"] is not None:
            if _intervals_overlap(win_start, win_end, p["send_window_start"], p["send_window_end"]):
                err("ERR_SEND_WINDOW_CONFLICT", 409, "send window overlaps a prior send")
    # recipients
    count = 0
    for m in DB["members"].values():
        if m["publication_id"] != post["publication_id"]:
            continue
        if m["status"] != "VERIFIED" or m["email_bounced"]:
            continue
        eligible = False
        for s in DB["subscriptions"].values():
            if s["member_id"] != m["id"]:
                continue
            if s["status"] in ("ACTIVE", "TRIALING") and s["current_tier_rank"] >= post["min_tier_rank"]:
                eligible = True
                break
        if eligible:
            count += 1
    post["status"] = "SENT"
    post["send_window_start"] = win_start
    post["send_window_end"] = win_end
    post["recipient_count"] = count
    touch(post)
    if pub is not None:
        pub["sent_count"] += count
        pub["bounce_rate"] = pub["bounce_count"] / max(1, pub["sent_count"])
        touch(pub)
    return ok_obj(post)


# ===========================================================================
# Events
# ===========================================================================
@app.route("/publications/<pid>/events", methods=["POST"])
def create_event(pid):
    role, uid = auth({"Creator"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    require_pub_owner(pub, role, uid)
    data = body()
    title = field_str(data, "title")
    starts_at = parse_iso(field_str(data, "starts_at"))
    ends_at = parse_iso(field_str(data, "ends_at"))
    registration_closes_at = parse_iso(field_str(data, "registration_closes_at"))
    capacity = field_int(data, "capacity", minv=1)
    min_tier_rank = field_int(data, "min_tier_rank", required=False, default=0, minv=0)
    allow_waitlist = field_bool(data, "allow_waitlist", required=False, default=True)
    if ends_at <= starts_at:
        err("ERR_VALIDATION", 422, "ends_at must be after starts_at")
    event = create_entity("events", {
        "publication_id": pid,
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "registration_closes_at": registration_closes_at,
        "min_tier_rank": min_tier_rank,
        "capacity": capacity,
        "allow_waitlist": allow_waitlist,
        "registered_count": 0,
        "waitlist_count": 0,
        "available_slots": capacity,
    })
    return ok_obj(event, 201)


@app.route("/publications/<pid>/events", methods=["GET"])
def list_events(pid):
    auth({"Anonymous", "Member", "Creator", "PlatformAdmin"})
    get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    items = [e for e in DB["events"].values() if e["publication_id"] == pid]
    return list_response(items)


def promote_waitlist(ev):
    if ev["available_slots"] <= 0:
        return
    waiters = [r for r in DB["registrations"].values()
               if r["event_id"] == ev["id"] and r["status"] == "WAITLISTED"]
    if not waiters:
        return
    waiters.sort(key=lambda r: r["created_at"])
    w = waiters[0]
    w["status"] = "REGISTERED"
    ev["registered_count"] += 1
    ev["waitlist_count"] -= 1
    ev["available_slots"] = ev["capacity"] - ev["registered_count"]
    touch(w)


@app.route("/events/<event_id>/registrations", methods=["POST"])
def create_registration(event_id):
    role, uid = auth({"Member"})
    ev = get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    # state: already registered
    for r in DB["registrations"].values():
        if r["event_id"] == event_id and r["member_id"] == uid and r["status"] in ("REGISTERED", "WAITLISTED"):
            err("ERR_ALREADY_REGISTERED", 409, "already registered for this event")
    # gating
    member_gate(uid, ev["publication_id"], ev["min_tier_rank"])
    # temporal: registration closed
    if now() > ev["registration_closes_at"]:
        err("ERR_REGISTRATION_CLOSED", 409, "registration is closed")
    # temporal: schedule conflict
    for r in DB["registrations"].values():
        if r["member_id"] != uid or r["status"] != "REGISTERED":
            continue
        other = DB["events"].get(r["event_id"])
        if other is None:
            continue
        if _intervals_overlap(ev["starts_at"], ev["ends_at"], other["starts_at"], other["ends_at"]):
            err("ERR_SCHEDULE_CONFLICT", 409, "overlaps another registered event")
    # seat allocation
    if ev["available_slots"] > 0:
        status = "REGISTERED"
        ev["registered_count"] += 1
        ev["available_slots"] = ev["capacity"] - ev["registered_count"]
    elif ev["allow_waitlist"]:
        status = "WAITLISTED"
        ev["waitlist_count"] += 1
    else:
        err("ERR_EVENT_FULL", 409, "event is full and waitlisting is disabled")
    reg = create_entity("registrations", {
        "event_id": event_id,
        "member_id": uid,
        "status": status,
        "registered_at": now(),
    })
    touch(ev)
    return ok_obj(reg, 201)


@app.route("/registrations/<rid>", methods=["GET"])
def get_registration(rid):
    auth({"Member", "Creator", "PlatformAdmin"})
    reg = get_or_404("registrations", rid, "ERR_REGISTRATION_NOT_FOUND")
    return ok_obj(reg)


@app.route("/registrations", methods=["GET"])
def list_registrations():
    auth({"Member", "Creator", "PlatformAdmin"})
    event_id = request.args.get("event_id")
    member_id = request.args.get("member_id")
    items = []
    for r in DB["registrations"].values():
        if event_id is not None and r["event_id"] != event_id:
            continue
        if member_id is not None and r["member_id"] != member_id:
            continue
        items.append(r)
    return list_response(items)


@app.route("/registrations/<rid>/cancel", methods=["POST"])
def cancel_registration(rid):
    role, uid = auth({"Member"})
    reg = get_or_404("registrations", rid, "ERR_REGISTRATION_NOT_FOUND")
    if reg["member_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "member may only cancel their own registration")
    ev = DB["events"].get(reg["event_id"])
    if reg["status"] == "REGISTERED":
        reg["status"] = "CANCELED"
        touch(reg)
        if ev is not None:
            ev["registered_count"] -= 1
            ev["available_slots"] = ev["capacity"] - ev["registered_count"]
            promote_waitlist(ev)
            touch(ev)
    elif reg["status"] == "WAITLISTED":
        reg["status"] = "CANCELED"
        touch(reg)
        if ev is not None:
            ev["waitlist_count"] -= 1
            touch(ev)
    else:
        err("ERR_INVALID_STATE", 409, "registration cannot be canceled from its current state")
    return ok_obj(reg)


# ===========================================================================
# Comments
# ===========================================================================
@app.route("/posts/<post_id>/comments", methods=["POST"])
def create_comment(post_id):
    role, uid = auth({"Member"})
    post = get_or_404("posts", post_id, "ERR_POST_NOT_FOUND")
    data = body()
    text = field_str(data, "body")
    member_gate(uid, post["publication_id"], post["min_tier_rank"])
    comment = create_entity("comments", {
        "post_id": post_id,
        "member_id": uid,
        "body": text,
        "status": "PENDING",
        "moderation_reason": None,
    })
    return ok_obj(comment, 201)


@app.route("/comments/<cid>", methods=["GET"])
def get_comment(cid):
    auth({"Anonymous", "Member", "Creator", "Moderator", "PlatformAdmin"})
    comment = get_or_404("comments", cid, "ERR_COMMENT_NOT_FOUND")
    return ok_obj(comment)


@app.route("/comments", methods=["GET"])
def list_comments():
    auth({"Anonymous", "Member", "Creator", "Moderator", "PlatformAdmin"})
    post_id = request.args.get("post_id")
    member_id = request.args.get("member_id")
    items = []
    for c in DB["comments"].values():
        if post_id is not None and c["post_id"] != post_id:
            continue
        if member_id is not None and c["member_id"] != member_id:
            continue
        items.append(c)
    return list_response(items)


def recompute_approved_count(post):
    count = 0
    for c in DB["comments"].values():
        if c["post_id"] == post["id"] and c["status"] == "APPROVED":
            count += 1
    post["approved_comment_count"] = count


@app.route("/comments/<cid>/moderate", methods=["POST"])
def moderate_comment(cid):
    role, uid = auth({"Moderator", "Creator"})
    comment = get_or_404("comments", cid, "ERR_COMMENT_NOT_FOUND")
    post = DB["posts"].get(comment["post_id"])
    pub = DB["publications"].get(post["publication_id"]) if post else None
    if role == "Creator":
        if pub is None or pub["creator_user_id"] != uid:
            err("ERR_NOT_RESOURCE_OWNER", 403, "creator does not own this comment's publication")
    data = body()
    decision = field_enum(data, "decision", {"APPROVE", "REJECT", "HOLD", "HIDE"})
    st = comment["status"]

    valid = (
        (st == "PENDING" and decision in ("APPROVE", "REJECT", "HOLD"))
        or (st == "HELD" and decision in ("APPROVE", "REJECT"))
        or (st == "APPROVED" and decision == "HIDE")
    )
    if not valid:
        err("ERR_INVALID_STATE", 409, "moderation decision not allowed from current state")

    if decision == "APPROVE":
        comment["status"] = "APPROVED"
    elif decision == "REJECT":
        comment["status"] = "REJECTED"
        comment["moderation_reason"] = "REJECT"
    elif decision == "HOLD":
        comment["status"] = "HELD"
        comment["moderation_reason"] = "HOLD"
    else:  # HIDE
        comment["status"] = "HIDDEN"
    touch(comment)
    if post is not None:
        recompute_approved_count(post)
        touch(post)
    return ok_obj(comment)


# ===========================================================================
# Payouts
# ===========================================================================
@app.route("/publications/<pid>/payouts", methods=["POST"])
def create_payout(pid):
    role, uid = auth({"Creator"})
    pub = get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    require_pub_owner(pub, role, uid)
    data = body()
    amount = field_int(data, "amount_cents", minv=1)
    expected = field_int(data, "expected_publication_version", required=False, default=None)
    # state
    if pub["status"] != "ACTIVE":
        err("ERR_PUBLICATION_SUSPENDED", 409, "publication is suspended")
    # fiscal
    if amount > pub["payout_balance_cents"]:
        err("ERR_INSUFFICIENT_BALANCE", 402, "payout exceeds available balance")
    # OCC
    if expected is not None and expected != pub["version"]:
        err("ERR_STALE_PUBLICATION_VERSION", 412, "stale publication version")
    payout = create_entity("payouts", {
        "publication_id": pid,
        "amount_cents": amount,
        "status": "REQUESTED",
        "settled_at": None,
    })
    pub["payout_balance_cents"] -= amount
    pub["pending_payout_cents"] += amount
    touch(pub)
    return ok_obj(payout, 201)


@app.route("/publications/<pid>/payouts", methods=["GET"])
def list_payouts(pid):
    auth({"Creator", "PlatformAdmin"})
    get_or_404("publications", pid, "ERR_PUBLICATION_NOT_FOUND")
    items = [p for p in DB["payouts"].values() if p["publication_id"] == pid]
    return list_response(items)


@app.route("/payouts/<payout_id>/settle", methods=["POST"])
def settle_payout(payout_id):
    auth({"PlatformAdmin"})
    payout = get_or_404("payouts", payout_id, "ERR_PAYOUT_NOT_FOUND")
    data = body()
    outcome = field_enum(data, "outcome", {"PAID", "FAILED"})
    if payout["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "payout is not REQUESTED")
    pub = DB["publications"].get(payout["publication_id"])
    amount = payout["amount_cents"]
    if outcome == "PAID":
        if pub is not None:
            pub["pending_payout_cents"] -= amount
            pub["lifetime_paid_out_cents"] += amount
            touch(pub)
        payout["status"] = "PAID"
    else:  # FAILED (compensation)
        if pub is not None:
            pub["pending_payout_cents"] -= amount
            pub["payout_balance_cents"] += amount
            touch(pub)
        payout["status"] = "FAILED"
    payout["settled_at"] = now()
    touch(payout)
    return ok_obj(payout)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
