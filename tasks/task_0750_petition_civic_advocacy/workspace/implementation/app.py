import os
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import ceil

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# =============================================================================
# In-memory store (clean slate on every boot)
# =============================================================================
db = {
    "users": {},
    "petitions": {},
    "targets": {},
    "representatives": {},
    "signatures": {},
    "comments": {},
    "campaigns": {},
    "donations": {},
    "promotions": {},
    "delivery_meetings": {},
}

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
STATE = {"clock": DEFAULT_CLOCK, "seq": 0}

ROLES = {"Guest", "Member", "Moderator", "Admin"}

# Calculation constants
BASE_RATE_CENTS = {"STANDARD": 5000, "PREMIUM": 12000, "SPOTLIGHT": 25000}
CATEGORY_DEMAND = {"ENVIRONMENT": "1.5", "POLITICS": "2.0", "HEALTH": "1.2",
                   "EDUCATION": "1.0", "OTHER": "1.0"}
MIN_PRICE_CENTS = 5000
MAX_PRICE_CENTS = 200000
LISTING_FEE_CENTS = 1500
PLATFORM_FEE_PCT = Decimal("0.029")
FIXED_FEE_CENTS = 30
PROMO_SLOTS_PER_CATEGORY = 2
BUFFER_SECONDS = 15 * 60

CATEGORIES = {"ENVIRONMENT", "POLITICS", "HEALTH", "EDUCATION", "OTHER"}


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


NOT_FOUND = {
    "users": "ERR_USER_NOT_FOUND",
    "petitions": "ERR_PETITION_NOT_FOUND",
    "targets": "ERR_TARGET_NOT_FOUND",
    "representatives": "ERR_REPRESENTATIVE_NOT_FOUND",
    "signatures": "ERR_SIGNATURE_NOT_FOUND",
    "comments": "ERR_COMMENT_NOT_FOUND",
    "campaigns": "ERR_CAMPAIGN_NOT_FOUND",
    "donations": "ERR_DONATION_NOT_FOUND",
    "promotions": "ERR_PROMOTION_NOT_FOUND",
    "delivery_meetings": "ERR_MEETING_NOT_FOUND",
}


# =============================================================================
# Time / helpers
# =============================================================================
def now_dt():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ApiError:
        raise
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def new_entity(fields):
    now = now_dt()
    ent = dict(fields)
    ent["id"] = str(uuid.uuid4())
    ent["created_at"] = now
    ent["updated_at"] = now
    ent["version"] = 1
    ent["_seq"] = next_seq()
    return ent


def touch(ent):
    ent["updated_at"] = now_dt()
    ent["version"] += 1


# =============================================================================
# Response envelope
# =============================================================================
def base_meta():
    return {"api_request_id": new_request_id(),
            "api_request_timestamp": fmt_dt(now_dt())}


def ok(data, status=200, response_type="object", pagination=None):
    meta = base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    meta = base_meta()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    meta = base_meta()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    meta = base_meta()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}}
    return jsonify(body), 405


# =============================================================================
# Auth
# =============================================================================
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def authz(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")


def get_entity(coll, ident):
    ent = db[coll].get(ident)
    if ent is None:
        raise ApiError(NOT_FOUND[coll], 404, f"{coll} not found")
    return ent


# =============================================================================
# Body validation helpers
# =============================================================================
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "body must be a JSON object")
    return b


def need(b, name):
    if name not in b or b[name] is None:
        raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
    return b[name]


def need_str(b, name):
    v = need(b, name)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a string")
    return v


def need_int(b, name, minimum=None):
    v = need(b, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be >= {minimum}")
    return v


def need_enum(b, name, allowed):
    v = need(b, name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be one of {sorted(allowed)}")
    return v


def opt_str(b, name):
    if name not in b or b[name] is None:
        return None
    if not isinstance(b[name], str):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a string")
    return b[name]


# =============================================================================
# Serialization
# =============================================================================
DT_FIELDS = {"created_at", "updated_at", "published_at"}


def serialize(ent, kind=None):
    out = {}
    for k, v in ent.items():
        if k.startswith("_"):
            continue
        if k in DT_FIELDS:
            out[k] = fmt_dt(v) if v is not None else None
        else:
            out[k] = v
    if kind == "promotion":
        out["status"] = promo_status(ent)
    return out


# =============================================================================
# Pagination + list
# =============================================================================
def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items, kind=None):
    items = sorted(items, key=lambda e: e["_seq"])
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + len(page) < total
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": has_more}
    data = [serialize(e, kind) for e in page]
    return ok(data, 200, "array", pagination)


# =============================================================================
# Derived recomputation
# =============================================================================
def recompute_petition(p):
    sigs = [s for s in db["signatures"].values() if s["petition_id"] == p["id"]]
    verified = sum(1 for s in sigs if s["status"] == "VERIFIED")
    pending = sum(1 for s in sigs if s["status"] == "PENDING_VERIFICATION")
    comments = [c for c in db["comments"].values()
                if c["petition_id"] == p["id"]
                and c["comment_type"] == "COMMENT" and c["status"] == "APPROVED"]
    approved_comments = len(comments)
    delivered = sum(1 for m in db["delivery_meetings"].values()
                    if m["petition_id"] == p["id"] and m["status"] == "DELIVERED")
    thresholds = p.get("milestone_thresholds", [])
    milestones_reached = [t for t in thresholds if verified >= t]
    goal_reached = verified >= p["goal"]

    changed = (
        verified != p.get("verified_signature_count")
        or pending != p.get("pending_signature_count")
        or approved_comments != p.get("approved_comment_count")
        or delivered != p.get("delivered_meeting_count")
        or milestones_reached != p.get("milestones_reached")
        or goal_reached != p.get("goal_reached")
    )
    p["verified_signature_count"] = verified
    p["pending_signature_count"] = pending
    p["approved_comment_count"] = approved_comments
    p["delivered_meeting_count"] = delivered
    p["milestones_reached"] = milestones_reached
    p["goal_reached"] = goal_reached
    if changed:
        touch(p)


def recompute_campaign(c):
    dons = [d for d in db["donations"].values() if d["campaign_id"] == c["id"]]
    gross = sum(d["amount_cents"] for d in dons if d["status"] in ("PENDING", "SETTLED"))
    # A refunded donation was settled first (+net) then reversed (-net): the two
    # cancel, so its lifetime contribution to the official total is exactly zero
    # (PRD §3.6/§3.8 "backed out cent-for-cent"). Reconciling by summing net over
    # currently-SETTLED donations reproduces that incremental result; subtracting
    # the REFUNDED nets on top would double-count the reversal.
    net = sum(d["net_to_campaign_cents"] for d in dons if d["status"] == "SETTLED")
    changed = (gross != c.get("gross_pledged_cents")
               or net != c.get("funds_raised_cents"))
    c["gross_pledged_cents"] = gross
    c["funds_raised_cents"] = net
    if changed:
        touch(c)


def promo_status(p):
    if p["status"] == "CANCELLED":
        return "CANCELLED"
    clock = STATE["clock"]
    if clock < p["_ws_dt"]:
        return "SCHEDULED"
    if clock < p["_we_dt"]:
        return "ACTIVE"
    return "COMPLETED"


# =============================================================================
# USERS
# =============================================================================
@app.route("/users", methods=["POST"])
def create_user():
    b = get_body()
    email = need_str(b, "email")
    full_name = need_str(b, "full_name")
    jurisdiction = need_str(b, "jurisdiction")
    for u in db["users"].values():
        if u["email"].lower() == email.lower():
            raise ApiError("ERR_VALIDATION", 422, "email already registered")
    role_hint = b.get("role_hint", "MEMBER")
    if role_hint is None:
        role_hint = "MEMBER"
    if role_hint != "MEMBER":
        raise ApiError("ERR_VALIDATION", 422, "role_hint must be MEMBER")
    ent = new_entity({
        "email": email,
        "full_name": full_name,
        "jurisdiction": jurisdiction,
        "role_hint": role_hint,
    })
    db["users"][ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/users/<uid>", methods=["GET"])
def get_user(uid):
    return ok(serialize(get_entity("users", uid)), 200)


# =============================================================================
# PETITIONS
# =============================================================================
@app.route("/petitions", methods=["POST"])
def create_petition():
    _, role = auth()
    authz(role, {"Member"})
    b = get_body()
    title = need_str(b, "title")
    summary = need_str(b, "summary")
    body = need_str(b, "body")
    category = need_enum(b, "category", CATEGORIES)
    goal = need_int(b, "goal", minimum=1)
    eligible = opt_str(b, "eligible_jurisdiction")
    ent = new_entity({
        "author_user_id": request.headers.get("X-User-ID"),
        "title": title,
        "summary": summary,
        "body": body,
        "category": category,
        "goal": goal,
        "eligible_jurisdiction": eligible,
        "status": "DRAFT",
        "moderation_status": "PENDING",
        "verified_signature_count": 0,
        "pending_signature_count": 0,
        "goal_reached": False,
        "milestone_thresholds": [],
        "milestones_reached": [],
        "approved_comment_count": 0,
        "delivered_meeting_count": 0,
        "published_at": None,
    })
    db["petitions"][ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/petitions/<pid>", methods=["GET"])
def get_petition(pid):
    return ok(serialize(get_entity("petitions", pid)), 200)


@app.route("/petitions", methods=["GET"])
def list_petitions():
    items = list(db["petitions"].values())
    for key in ("author_user_id", "category", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    return list_response(items)


@app.route("/petitions/<pid>", methods=["PATCH"])
def edit_petition(pid):
    uid, role = auth()
    authz(role, {"Member"})
    p = get_entity("petitions", pid)
    if p["author_user_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the petition author")
    b = get_body()
    expected = need_int(b, "expected_petition_version")
    new_vals = {}
    if "title" in b and b["title"] is not None:
        new_vals["title"] = need_str(b, "title")
    if "summary" in b and b["summary"] is not None:
        new_vals["summary"] = need_str(b, "summary")
    if "body" in b and b["body"] is not None:
        new_vals["body"] = need_str(b, "body")
    if "goal" in b and b["goal"] is not None:
        new_vals["goal"] = need_int(b, "goal", minimum=1)
    if "eligible_jurisdiction" in b:
        ej = b["eligible_jurisdiction"]
        if ej is not None and not isinstance(ej, str):
            raise ApiError("ERR_VALIDATION", 422, "eligible_jurisdiction must be a string")
        new_vals["eligible_jurisdiction"] = ej
    if expected != p["version"]:
        raise ApiError("ERR_STALE_PETITION_VERSION", 412, "stale petition version")
    if p["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "petition not editable in current state")
    p.update(new_vals)
    touch(p)
    return ok(serialize(p), 200)


@app.route("/petitions/<pid>/submit", methods=["POST"])
def submit_petition(pid):
    uid, role = auth()
    authz(role, {"Member"})
    p = get_entity("petitions", pid)
    if p["author_user_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the petition author")
    if p["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "cannot submit from current state")
    if p["status"] == "DRAFT":
        has_active_target = any(t["petition_id"] == pid and t["status"] == "ACTIVE"
                                for t in db["targets"].values())
        if not has_active_target:
            raise ApiError("ERR_INVALID_STATE", 409, "petition has no active target")
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return ok(serialize(p), 200)


@app.route("/petitions/<pid>/moderate", methods=["POST"])
def moderate_petition(pid):
    _, role = auth()
    authz(role, {"Moderator"})
    p = get_entity("petitions", pid)
    b = get_body()
    decision = need_enum(b, "decision", {"APPROVE", "REQUEST_CHANGES", "REMOVE"})
    if decision == "APPROVE":
        if p["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "cannot approve from current state")
        p["status"] = "PUBLISHED"
        p["moderation_status"] = "APPROVED"
        if p["published_at"] is None:
            p["published_at"] = STATE["clock"]
        p["milestone_thresholds"] = compute_milestones(p["goal"])
        touch(p)
        recompute_petition(p)
    elif decision == "REQUEST_CHANGES":
        if p["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "cannot request changes from current state")
        p["status"] = "CHANGES_REQUESTED"
        touch(p)
    else:  # REMOVE
        if p["status"] not in ("UNDER_REVIEW", "PUBLISHED"):
            raise ApiError("ERR_INVALID_STATE", 409, "cannot remove from current state")
        p["status"] = "REMOVED"
        p["moderation_status"] = "BLOCKED"
        touch(p)
    return ok(serialize(p), 200)


def compute_milestones(goal):
    candidates = [100, ceil(goal / 2), goal]
    kept = sorted(set(c for c in candidates if 1 <= c <= goal))
    return kept


@app.route("/petitions/<pid>/close", methods=["POST"])
def close_petition(pid):
    uid, role = auth()
    authz(role, {"Member"})
    p = get_entity("petitions", pid)
    if p["author_user_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the petition author")
    b = get_body()
    outcome = need_enum(b, "outcome", {"VICTORY", "WITHDRAWN"})
    if p["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "only a published petition can be closed")
    if outcome == "VICTORY":
        if p["verified_signature_count"] <= 0:
            raise ApiError("ERR_NO_VERIFIED_SIGNATURES", 422, "no verified signatures")
        if p["delivered_meeting_count"] < 1:
            raise ApiError("ERR_NO_DELIVERY", 422, "no delivered meeting")
        p["status"] = "CLOSED_VICTORY"
        touch(p)
        close_campaign_cascade(pid)
    else:  # WITHDRAWN
        p["status"] = "CLOSED_WITHDRAWN"
        touch(p)
        for s in db["signatures"].values():
            if s["petition_id"] == pid and s["status"] == "PENDING_VERIFICATION":
                s["status"] = "REJECTED"
                touch(s)
        recompute_petition(p)
        close_campaign_cascade(pid)
    return ok(serialize(p), 200)


def close_campaign_cascade(pid):
    for c in db["campaigns"].values():
        if c["petition_id"] == pid and c["status"] != "CLOSED":
            c["status"] = "CLOSED"
            touch(c)
            for d in db["donations"].values():
                if d["campaign_id"] == c["id"] and d["status"] == "PENDING":
                    d["status"] = "REFUNDED"
                    touch(d)
            recompute_campaign(c)


@app.route("/petitions/<pid>/target", methods=["POST"])
def set_target(pid):
    uid, role = auth()
    authz(role, {"Member"})
    p = get_entity("petitions", pid)
    if p["author_user_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the petition author")
    b = get_body()
    name = need_str(b, "name")
    title = need_str(b, "title")
    office = need_str(b, "office")
    expected = need_int(b, "expected_petition_version")
    rep_id = b.get("representative_id")
    if rep_id is not None:
        if not isinstance(rep_id, str):
            raise ApiError("ERR_VALIDATION", 422, "representative_id must be a string")
        if rep_id not in db["representatives"]:
            raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND", 404, "representative not found")
    if expected != p["version"]:
        raise ApiError("ERR_STALE_PETITION_VERSION", 412, "stale petition version")
    for t in db["targets"].values():
        if t["petition_id"] == pid and t["status"] == "ACTIVE":
            t["status"] = "SUPERSEDED"
            touch(t)
    ent = new_entity({
        "petition_id": pid,
        "representative_id": rep_id,
        "name": name,
        "title": title,
        "office": office,
        "status": "ACTIVE",
    })
    db["targets"][ent["id"]] = ent
    touch(p)
    return ok(serialize(ent), 201)


# =============================================================================
# TARGETS
# =============================================================================
@app.route("/targets/<tid>", methods=["GET"])
def get_target(tid):
    return ok(serialize(get_entity("targets", tid)), 200)


@app.route("/targets", methods=["GET"])
def list_targets():
    items = list(db["targets"].values())
    for key in ("petition_id", "representative_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    return list_response(items)


@app.route("/targets/<tid>/deactivate", methods=["POST"])
def deactivate_target(tid):
    _, role = auth()
    authz(role, {"Admin"})
    t = get_entity("targets", tid)
    if t["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "target not active")
    t["status"] = "UNREACHABLE"
    touch(t)
    for m in db["delivery_meetings"].values():
        if m["target_id"] == tid and m["status"] in ("REQUESTED", "CONFIRMED"):
            m["status"] = "CANCELLED"
            touch(m)
    return ok(serialize(t), 200)


# =============================================================================
# REPRESENTATIVES
# =============================================================================
@app.route("/representatives", methods=["POST"])
def create_representative():
    _, role = auth()
    authz(role, {"Admin"})
    b = get_body()
    ent = new_entity({
        "full_name": need_str(b, "full_name"),
        "office": need_str(b, "office"),
        "jurisdiction": need_str(b, "jurisdiction"),
        "contact_email": need_str(b, "contact_email"),
    })
    db["representatives"][ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/representatives/<rid>", methods=["GET"])
def get_representative(rid):
    return ok(serialize(get_entity("representatives", rid)), 200)


@app.route("/representatives", methods=["GET"])
def list_representatives():
    items = list(db["representatives"].values())
    for key in ("jurisdiction", "office"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    return list_response(items)


# =============================================================================
# SIGNATURES
# =============================================================================
@app.route("/petitions/<pid>/signatures", methods=["POST"])
def sign_petition(pid):
    uid, role = auth()
    authz(role, {"Member"})
    p = get_entity("petitions", pid)
    b = get_body()
    public_comment = opt_str(b, "public_comment")
    if p["status"] != "PUBLISHED":
        raise ApiError("ERR_PETITION_NOT_PUBLISHED", 409, "petition not published")
    if p["eligible_jurisdiction"] is not None:
        user = db["users"].get(uid)
        signer_j = user["jurisdiction"] if user else None
        if signer_j != p["eligible_jurisdiction"]:
            raise ApiError("ERR_JURISDICTION_MISMATCH", 422, "signer jurisdiction mismatch")
    for s in db["signatures"].values():
        if (s["petition_id"] == pid and s["signer_user_id"] == uid
                and s["status"] in ("PENDING_VERIFICATION", "VERIFIED")):
            raise ApiError("ERR_DUPLICATE_SIGNATURE", 409, "already holds a signature")
    token = uuid.uuid4().hex
    ent = new_entity({
        "petition_id": pid,
        "signer_user_id": uid,
        "public_comment": public_comment,
        "verification_token": token,
        "status": "PENDING_VERIFICATION",
    })
    db["signatures"][ent["id"]] = ent
    recompute_petition(p)
    return ok(serialize(ent), 201)


@app.route("/signatures/<sid>", methods=["GET"])
def get_signature(sid):
    return ok(serialize(get_entity("signatures", sid)), 200)


@app.route("/signatures", methods=["GET"])
def list_signatures():
    items = list(db["signatures"].values())
    for key in ("petition_id", "signer_user_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    return list_response(items)


@app.route("/signatures/<sid>/verify", methods=["POST"])
def verify_signature(sid):
    uid, role = auth()
    authz(role, {"Member"})
    s = get_entity("signatures", sid)
    if s["signer_user_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the signature owner")
    b = get_body()
    token = need_str(b, "verification_token")
    if s["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", 409, "signature not pending verification")
    if token != s["verification_token"]:
        raise ApiError("ERR_INVALID_VERIFICATION_TOKEN", 422, "invalid verification token")
    p = db["petitions"].get(s["petition_id"])
    if p is None or p["status"] != "PUBLISHED":
        raise ApiError("ERR_PETITION_NOT_PUBLISHED", 409, "petition not published")
    s["status"] = "VERIFIED"
    touch(s)
    recompute_petition(p)
    return ok(serialize(s), 200)


@app.route("/signatures/<sid>/revoke", methods=["POST"])
def revoke_signature(sid):
    _, role = auth()
    authz(role, {"Moderator"})
    s = get_entity("signatures", sid)
    get_body()  # reason optional
    if s["status"] == "PENDING_VERIFICATION":
        s["status"] = "REJECTED"
    elif s["status"] == "VERIFIED":
        s["status"] = "REVOKED"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "signature not revocable")
    touch(s)
    p = db["petitions"].get(s["petition_id"])
    if p is not None:
        recompute_petition(p)
    return ok(serialize(s), 200)


# =============================================================================
# COMMENTS
# =============================================================================
@app.route("/petitions/<pid>/comments", methods=["POST"])
def create_comment(pid):
    uid, role = auth()
    authz(role, {"Member"})
    p = get_entity("petitions", pid)
    b = get_body()
    body_text = need_str(b, "body")
    ctype = b.get("comment_type", "COMMENT")
    if ctype is None:
        ctype = "COMMENT"
    if ctype not in ("COMMENT", "UPDATE"):
        raise ApiError("ERR_VALIDATION", 422, "invalid comment_type")
    if ctype == "UPDATE":
        if p["author_user_id"] != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "only author may post an update")
        status = "APPROVED"
    else:
        status = "PENDING"
    ent = new_entity({
        "petition_id": pid,
        "author_user_id": uid,
        "comment_type": ctype,
        "body": body_text,
        "status": status,
        "delivered": False,
    })
    db["comments"][ent["id"]] = ent
    if ctype == "COMMENT" and status == "APPROVED":
        recompute_petition(p)
    return ok(serialize(ent), 201)


@app.route("/comments/<cid>", methods=["GET"])
def get_comment(cid):
    return ok(serialize(get_entity("comments", cid)), 200)


@app.route("/comments", methods=["GET"])
def list_comments():
    items = list(db["comments"].values())
    for key in ("petition_id", "author_user_id", "comment_type", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return list_response(items)


@app.route("/comments/<cid>/moderate", methods=["POST"])
def moderate_comment(cid):
    _, role = auth()
    authz(role, {"Moderator"})
    c = get_entity("comments", cid)
    b = get_body()
    decision = need_enum(b, "decision", {"APPROVE", "REJECT", "DISMISS", "REMOVE"})
    if c["comment_type"] != "COMMENT":
        raise ApiError("ERR_CONTENT_NOT_MODERATABLE", 409, "not a moderatable comment")
    p = db["petitions"].get(c["petition_id"])
    if decision == "APPROVE":
        if c["status"] != "PENDING":
            raise ApiError("ERR_CONTENT_NOT_MODERATABLE", 409, "comment not pending")
        c["status"] = "APPROVED"
        touch(c)
        if p:
            recompute_petition(p)
    elif decision == "REJECT":
        if c["status"] != "PENDING":
            raise ApiError("ERR_CONTENT_NOT_MODERATABLE", 409, "comment not pending")
        c["status"] = "REJECTED"
        touch(c)
    elif decision == "DISMISS":
        if c["status"] != "FLAGGED":
            raise ApiError("ERR_CONTENT_NOT_MODERATABLE", 409, "comment not flagged")
        c["status"] = "APPROVED"
        touch(c)
        if p:
            recompute_petition(p)
    else:  # REMOVE
        if c["status"] != "FLAGGED":
            raise ApiError("ERR_CONTENT_NOT_MODERATABLE", 409, "comment not flagged")
        c["status"] = "REMOVED"
        touch(c)
    return ok(serialize(c), 200)


@app.route("/comments/<cid>/flag", methods=["POST"])
def flag_comment(cid):
    _, role = auth()
    authz(role, {"Member"})
    c = get_entity("comments", cid)
    get_body()  # reason optional
    if c["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "only approved comments can be flagged")
    c["status"] = "FLAGGED"
    touch(c)
    p = db["petitions"].get(c["petition_id"])
    if p:
        recompute_petition(p)
    return ok(serialize(c), 200)


@app.route("/comments/<cid>/deliver", methods=["POST"])
def deliver_comment(cid):
    uid, role = auth()
    authz(role, {"Member"})
    c = get_entity("comments", cid)
    if c["author_user_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the update author")
    if c["comment_type"] != "UPDATE" or c["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "not a deliverable update")
    c["delivered"] = True
    touch(c)
    return ok(serialize(c), 200)


# =============================================================================
# CAMPAIGNS & DONATIONS
# =============================================================================
@app.route("/petitions/<pid>/campaign", methods=["POST"])
def create_campaign(pid):
    _, role = auth()
    authz(role, {"Member"})
    p = get_entity("petitions", pid)
    b = get_body()
    goal_cents = need_int(b, "goal_cents", minimum=0)
    ent = new_entity({
        "petition_id": pid,
        "goal_cents": goal_cents,
        "status": "ACTIVE",
        "gross_pledged_cents": 0,
        "funds_raised_cents": 0,
    })
    db["campaigns"][ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    return ok(serialize(get_entity("campaigns", cid)), 200)


@app.route("/campaigns", methods=["GET"])
def list_campaigns():
    items = list(db["campaigns"].values())
    for key in ("petition_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return list_response(items)


@app.route("/campaigns/<cid>/moderate", methods=["POST"])
def moderate_campaign(cid):
    _, role = auth()
    authz(role, {"Moderator"})
    c = get_entity("campaigns", cid)
    b = get_body()
    action = need_enum(b, "action", {"SUSPEND", "REACTIVATE"})
    if action == "SUSPEND":
        if c["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "campaign not active")
        c["status"] = "SUSPENDED"
    else:
        if c["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", 409, "campaign not suspended")
        c["status"] = "ACTIVE"
    touch(c)
    return ok(serialize(c), 200)


@app.route("/campaigns/<cid>/donations", methods=["POST"])
def donate(cid):
    uid, role = auth()
    authz(role, {"Member"})
    c = get_entity("campaigns", cid)
    b = get_body()
    amount = need_int(b, "amount_cents", minimum=100)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_SUSPENDED", 409, "campaign not accepting donations")
    ent = new_entity({
        "campaign_id": cid,
        "donor_user_id": uid,
        "amount_cents": amount,
        "platform_fee_cents": 0,
        "net_to_campaign_cents": 0,
        "status": "PENDING",
    })
    db["donations"][ent["id"]] = ent
    recompute_campaign(c)
    return ok(serialize(ent), 201)


@app.route("/donations/<did>", methods=["GET"])
def get_donation(did):
    return ok(serialize(get_entity("donations", did)), 200)


@app.route("/donations", methods=["GET"])
def list_donations():
    items = list(db["donations"].values())
    for key in ("campaign_id", "donor_user_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d.get(key) == val]
    return list_response(items)


@app.route("/donations/<did>/transition", methods=["POST"])
def transition_donation(did):
    _, role = auth()
    authz(role, {"Admin"})
    d = get_entity("donations", did)
    b = get_body()
    to_status = need_enum(b, "to_status", {"SETTLED", "FAILED", "REFUNDED"})
    c = db["campaigns"].get(d["campaign_id"])
    if to_status == "SETTLED":
        if d["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "donation not pending")
        if c is not None and c["status"] == "CLOSED":
            raise ApiError("ERR_INVALID_STATE", 409, "campaign closed")
        fee = round_half_up(Decimal(d["amount_cents"]) * PLATFORM_FEE_PCT) + FIXED_FEE_CENTS
        d["platform_fee_cents"] = fee
        d["net_to_campaign_cents"] = d["amount_cents"] - fee
        d["status"] = "SETTLED"
        touch(d)
        if c is not None:
            recompute_campaign(c)
    elif to_status == "FAILED":
        if d["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "donation not pending")
        d["status"] = "FAILED"
        touch(d)
    else:  # REFUNDED
        if d["status"] != "SETTLED":
            raise ApiError("ERR_INVALID_STATE", 409, "only settled donations can be refunded")
        d["status"] = "REFUNDED"
        touch(d)
        if c is not None:
            recompute_campaign(c)
    return ok(serialize(d), 200)


# =============================================================================
# PROMOTIONS
# =============================================================================
@app.route("/promotions", methods=["POST"])
def create_promotion():
    uid, role = auth()
    authz(role, {"Member"})
    b = get_body()
    petition_id = need_str(b, "petition_id")
    tier = need_enum(b, "placement_tier", {"STANDARD", "PREMIUM", "SPOTLIGHT"})
    ws_raw = need_str(b, "window_start")
    we_raw = need_str(b, "window_end")
    ws = parse_dt(ws_raw)
    we = parse_dt(we_raw)
    if we <= ws:
        raise ApiError("ERR_VALIDATION", 422, "window_end must be after window_start")
    p = db["petitions"].get(petition_id)
    if p is None:
        raise ApiError("ERR_PETITION_NOT_FOUND", 404, "petition not found")
    if not (p["moderation_status"] == "APPROVED" and p["status"] == "PUBLISHED"):
        raise ApiError("ERR_PETITION_NOT_PROMOTABLE", 403, "petition not promotable")
    category = p["category"]
    overlapping = 0
    for other in db["promotions"].values():
        if other["category"] != category:
            continue
        if promo_status(other) not in ("SCHEDULED", "ACTIVE"):
            continue
        if ws < other["_we_dt"] and other["_ws_dt"] < we:
            overlapping += 1
    if overlapping >= PROMO_SLOTS_PER_CATEGORY:
        raise ApiError("ERR_PROMO_SLOT_UNAVAILABLE", 409, "no featured slot available")
    duration_days = ceil((we - ws).total_seconds() / 86400)
    raw = Decimal(BASE_RATE_CENTS[tier]) * Decimal(duration_days) * Decimal(CATEGORY_DEMAND[category])
    clamped = max(Decimal(MIN_PRICE_CENTS), min(Decimal(MAX_PRICE_CENTS), raw))
    price = round_half_up(clamped) + LISTING_FEE_CENTS
    ent = new_entity({
        "petition_id": petition_id,
        "purchaser_user_id": uid,
        "category": category,
        "placement_tier": tier,
        "window_start": ws_raw,
        "window_end": we_raw,
        "duration_days": duration_days,
        "price_cents": price,
        "status": "SCHEDULED",
        "_ws_dt": ws,
        "_we_dt": we,
    })
    db["promotions"][ent["id"]] = ent
    return ok(serialize(ent, "promotion"), 201)


@app.route("/promotions/<pid>", methods=["GET"])
def get_promotion(pid):
    return ok(serialize(get_entity("promotions", pid), "promotion"), 200)


@app.route("/promotions", methods=["GET"])
def list_promotions():
    items = list(db["promotions"].values())
    for key in ("petition_id", "purchaser_user_id", "category"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [p for p in items if promo_status(p) == status_f]
    items = sorted(items, key=lambda e: e["_seq"])
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + len(page) < total
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": has_more}
    return ok([serialize(e, "promotion") for e in page], 200, "array", pagination)


@app.route("/promotions/<pid>/cancel", methods=["POST"])
def cancel_promotion(pid):
    uid, role = auth()
    authz(role, {"Member"})
    p = get_entity("promotions", pid)
    if p["purchaser_user_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the purchaser")
    if p["status"] != "SCHEDULED" or STATE["clock"] >= p["_ws_dt"]:
        raise ApiError("ERR_PROMO_NOT_CANCELLABLE", 409, "promotion not cancellable")
    p["status"] = "CANCELLED"
    touch(p)
    return ok(serialize(p, "promotion"), 200)


# =============================================================================
# DELIVERY MEETINGS
# =============================================================================
@app.route("/delivery-meetings", methods=["POST"])
def create_meeting():
    _, role = auth()
    authz(role, {"Member"})
    b = get_body()
    petition_id = need_str(b, "petition_id")
    target_id = need_str(b, "target_id")
    ws_raw = need_str(b, "window_start")
    we_raw = need_str(b, "window_end")
    ws = parse_dt(ws_raw)
    we = parse_dt(we_raw)
    if we <= ws:
        raise ApiError("ERR_VALIDATION", 422, "window_end must be after window_start")
    if petition_id not in db["petitions"]:
        raise ApiError("ERR_PETITION_NOT_FOUND", 404, "petition not found")
    t = db["targets"].get(target_id)
    if t is None:
        raise ApiError("ERR_TARGET_NOT_FOUND", 404, "target not found")
    if t["status"] != "ACTIVE":
        raise ApiError("ERR_TARGET_UNREACHABLE", 409, "target not active")
    for m in db["delivery_meetings"].values():
        if m["target_id"] != target_id:
            continue
        if m["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        if _meeting_conflict(ws, we, m["_ws_dt"], m["_we_dt"]):
            raise ApiError("ERR_MEETING_CONFLICT", 409, "meeting window conflict")
    ent = new_entity({
        "petition_id": petition_id,
        "target_id": target_id,
        "window_start": ws_raw,
        "window_end": we_raw,
        "status": "REQUESTED",
        "_ws_dt": ws,
        "_we_dt": we,
    })
    db["delivery_meetings"][ent["id"]] = ent
    return ok(serialize(ent), 201)


def _meeting_conflict(ws, we, ows, owe):
    if ws >= owe:
        gap = (ws - owe).total_seconds()
    elif ows >= we:
        gap = (ows - we).total_seconds()
    else:
        return True  # overlapping
    return gap < BUFFER_SECONDS


@app.route("/delivery-meetings/<mid>", methods=["GET"])
def get_meeting(mid):
    return ok(serialize(get_entity("delivery_meetings", mid)), 200)


@app.route("/delivery-meetings", methods=["GET"])
def list_meetings():
    items = list(db["delivery_meetings"].values())
    for key in ("petition_id", "target_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [m for m in items if m.get(key) == val]
    return list_response(items)


@app.route("/delivery-meetings/<mid>/transition", methods=["POST"])
def transition_meeting(mid):
    uid, role = auth()
    authz(role, {"Member", "Admin"})
    m = get_entity("delivery_meetings", mid)
    b = get_body()
    to_status = need_enum(b, "to_status", {"CONFIRMED", "DELIVERED", "CANCELLED"})
    p = db["petitions"].get(m["petition_id"])
    t = db["targets"].get(m["target_id"])
    if to_status == "CONFIRMED":
        if role != "Admin":
            raise ApiError("ERR_UNAUTHORIZED", 403, "only admin can confirm")
        if m["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "meeting not requested")
        if t is None or t["status"] != "ACTIVE":
            raise ApiError("ERR_TARGET_UNREACHABLE", 409, "target not active")
        m["status"] = "CONFIRMED"
        touch(m)
    elif to_status == "DELIVERED":
        if role != "Member":
            raise ApiError("ERR_UNAUTHORIZED", 403, "only the petition author can deliver")
        if p is None or p["author_user_id"] != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the petition author")
        if m["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", 409, "meeting not confirmed")
        if t is None or t["status"] != "ACTIVE":
            raise ApiError("ERR_TARGET_UNREACHABLE", 409, "target not active")
        m["status"] = "DELIVERED"
        touch(m)
        if p is not None:
            recompute_petition(p)
    else:  # CANCELLED
        if role == "Member" and (p is None or p["author_user_id"] != uid):
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the petition author")
        if m["status"] not in ("REQUESTED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE", 409, "meeting not cancellable")
        m["status"] = "CANCELLED"
        touch(m)
    return ok(serialize(m), 200)


# =============================================================================
# CLOCK
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth()
    authz(role, {"Admin"})
    b = get_body()
    iso = need_str(b, "to_iso8601")
    STATE["clock"] = parse_dt(iso)
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
