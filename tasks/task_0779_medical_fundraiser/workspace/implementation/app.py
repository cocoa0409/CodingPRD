"""Medical Fundraiser API (GoFundMe-style) — Python + Flask, in-memory only.

All state lives in module-level dicts and is empty on every boot. No seeding.
The test harness restarts this server (via start.sh) before every test.
"""
import os
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
KNOWN_ROLES = {"Guest", "Organizer", "Beneficiary", "Donor", "TrustSafetyAgent", "PlatformAdmin"}
ALL_ROLES = KNOWN_ROLES

PROCESSING_DIVISOR = Decimal("0.971")   # 1 - PROCESSING_RATE (0.029)
PROCESSING_FIXED_CENTS = 30
RESERVE_RATE = Decimal("0.05")
MIN_DONATION_CENTS = 100
COOLDOWN_HOURS = 24
W_DISPUTE = 15
W_REFUND = 50
UNVERIFIED_PENALTY = 20
SCORE_MAX = 100

CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0)

CATEGORY_ENUM = {"MEDICAL", "MEMORIAL", "EMERGENCY", "OTHER"}
TEAM_ROLE_ENUM = {"OWNER", "CO_ORGANIZER", "WITHDRAWAL_MANAGER"}
UPDATE_TYPE_ENUM = {"UPDATE", "THANK_YOU"}
DISPUTE_REASON_ENUM = {"FRAUD", "UNAUTHORIZED", "NOT_AS_DESCRIBED", "OTHER"}
SEVERITY_ENUM = {"STANDARD", "CRITICAL"}
PLACEMENT_CATEGORY_ENUM = {"HOMEPAGE", "MEDICAL", "EMERGENCY"}

# =============================================================================
# In-memory store
# =============================================================================
DB = {
    "organizers": {},
    "beneficiaries": {},
    "donors": {},
    "campaigns": {},
    "team_members": {},
    "donations": {},
    "updates": {},
    "payouts": {},
    "disputes": {},
    "refunds": {},
    "holds": {},
    "feature_placements": {},
}
CLOCK = {"now": CLOCK_DEFAULT}
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def invalid():
    return ApiError("ERR_INVALID_REQUEST", 400, "Malformed request body")


def not_found():
    return ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")


# =============================================================================
# Time helpers
# =============================================================================
def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_str():
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        raise invalid()
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        base = t.split("+")[0].split("-")
        # last-ditch simple formats
        raw = s.strip().rstrip("Z")
        parsed = None
        for f in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, f)
                break
            except ValueError:
                continue
        if parsed is None:
            raise invalid()
        dt = parsed
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# =============================================================================
# Response envelope
# =============================================================================
def _req_meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_str(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    return jsonify({"meta": _req_meta(pagination), "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return jsonify({
        "meta": _req_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    return jsonify({
        "meta": _req_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }), 404


@app.errorhandler(405)
def _handle_405(e):
    return jsonify({
        "meta": _req_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }), 404


@app.errorhandler(Exception)
def _handle_500(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    return jsonify({
        "meta": _req_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }), 500


# =============================================================================
# Auth / body helpers
# =============================================================================
def authorize(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")
    return uid, role


def get_body():
    b = request.get_json(silent=True)
    if b is None or not isinstance(b, dict):
        return {}
    return b


def need(b, key):
    if key not in b or b[key] is None:
        raise invalid()
    return b[key]


def as_str(v):
    if not isinstance(v, str):
        raise invalid()
    return v


def as_int(v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid()
    return v


def as_bool(v):
    if not isinstance(v, bool):
        raise invalid()
    return v


def as_enum(v, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise invalid()
    return v


# =============================================================================
# Entity base + mutation
# =============================================================================
def base(common=True):
    ts = now_str()
    d = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}
    if common:
        d["updated_at"] = ts
        d["version"] = 1
    return d


def touch(ent):
    ent["updated_at"] = now_str()
    ent["version"] = ent.get("version", 1) + 1


# =============================================================================
# Calculations
# =============================================================================
def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def donation_breakdown(amount, tip):
    subtotal = amount + tip
    total_charged = int(
        (Decimal(subtotal + PROCESSING_FIXED_CENTS) / PROCESSING_DIVISOR).to_integral_value(rounding=ROUND_CEILING)
    )
    fee = total_charged - subtotal
    net = amount
    reserve = round_half_up(Decimal(net) * RESERVE_RATE)
    return fee, total_charged, net, reserve


def risk_score(dispute_count, refunded, raised, unverified):
    denom = max(1, raised)
    ratio = Decimal(refunded) / Decimal(denom)
    if ratio > Decimal(1):
        ratio = Decimal(1)
    refund_term = round_half_up(Decimal(W_REFUND) * ratio)
    raw = W_DISPUTE * dispute_count + refund_term
    if unverified:
        raw += UNVERIFIED_PENALTY
    return min(SCORE_MAX, max(0, raw))


# =============================================================================
# Ledger / relationship helpers
# =============================================================================
def campaign_donations(cid):
    return [d for d in DB["donations"].values() if d["campaign_id"] == cid]


def donation_open_dispute(did):
    for dp in DB["disputes"].values():
        if dp["donation_id"] == did and dp["status"] in ("OPEN", "UNDER_REVIEW", "NEEDS_INFO"):
            return True
    return False


def campaign_active_holds(cid):
    return [h for h in DB["holds"].values() if h["campaign_id"] == cid and h["status"] == "ACTIVE"]


def compute_posture(c):
    ben = DB["beneficiaries"].get(c["beneficiary_id"])
    if ben and ben["verification_status"] == "REJECTED":
        return "FROZEN"
    if campaign_active_holds(c["id"]):
        return "HOLD"
    return "OPEN"


def campaign_money(c):
    cid = c["id"]
    captured = [d for d in campaign_donations(cid) if d["status"] == "CAPTURED"]
    raised = sum(d["net_to_campaign_cents"] for d in captured)
    reserve_total = sum(d["reserve_cents"] for d in captured)  # per-donation then summed
    payouts = [p for p in DB["payouts"].values() if p["campaign_id"] == cid]
    committed = sum(p["amount_cents"] for p in payouts if p["status"] in ("REQUESTED", "PROCESSING", "PAID"))
    paid_out = sum(p["amount_cents"] for p in payouts if p["status"] == "PAID")
    disputed_locked = sum(d["net_to_campaign_cents"] for d in captured if donation_open_dispute(d["id"]))
    hold_locked = sum(h["locked_amount_cents"] for h in campaign_active_holds(cid))
    provisional = raised - reserve_total - committed
    settled = provisional - disputed_locked - hold_locked
    return {
        "raised_cents": raised,
        "reserve_total_cents": reserve_total,
        "committed_cents": committed,
        "paid_out_cents": paid_out,
        "disputed_locked_cents": disputed_locked,
        "hold_locked_cents": hold_locked,
        "provisional_available_cents": provisional,
        "settled_available_cents": settled,
    }


def enforce_over_commitment(c):
    """Move REQUESTED/PROCESSING payouts to ON_HOLD, newest-first, until
    provisional_available_cents >= 0."""
    while True:
        if campaign_money(c)["provisional_available_cents"] >= 0:
            break
        candidates = [
            p for p in DB["payouts"].values()
            if p["campaign_id"] == c["id"] and p["status"] in ("REQUESTED", "PROCESSING")
        ]
        if not candidates:
            break
        candidates.sort(key=lambda p: p["_seq"], reverse=True)  # newest first
        p = candidates[0]
        p["status"] = "ON_HOLD"
        touch(p)


def recompute_posture_cascade_freeze(ben):
    """On beneficiary REJECTED: freeze campaigns, cancel non-terminal payouts."""
    for c in DB["campaigns"].values():
        if c["beneficiary_id"] != ben["id"]:
            continue
        for p in DB["payouts"].values():
            if p["campaign_id"] == c["id"] and p["status"] in ("REQUESTED", "PROCESSING", "ON_HOLD"):
                p["status"] = "CANCELLED"
                touch(p)
        touch(c)  # posture recompute advances version


def recompute_posture_cascade_plain(ben):
    """On beneficiary approve / posture-only recompute."""
    for c in DB["campaigns"].values():
        if c["beneficiary_id"] == ben["id"]:
            touch(c)


def active_member(campaign_id, organizer_id, owner_only=False):
    for tm in DB["team_members"].values():
        if tm["campaign_id"] == campaign_id and tm["organizer_id"] == organizer_id and tm["status"] == "ACTIVE":
            if owner_only and tm["team_role"] != "OWNER":
                return False
            return True
    return False


# =============================================================================
# Serializers
# =============================================================================
def s_organizer(o):
    campaigns = [c for c in DB["campaigns"].values() if c["organizer_id"] == o["id"]]
    camp_ids = {c["id"] for c in campaigns}
    donations = [d for d in DB["donations"].values() if d["campaign_id"] in camp_ids]
    don_ids = {d["id"] for d in donations}
    disputes = [dp for dp in DB["disputes"].values() if dp["donation_id"] in don_ids]
    total_dispute = len(disputes)
    upheld = len([dp for dp in disputes if dp["status"] == "UPHELD"])
    refunded = sum(r["amount_cents"] for r in DB["refunds"].values() if r["donation_id"] in don_ids)
    raised = sum(d["net_to_campaign_cents"] for d in donations if d["status"] == "CAPTURED")
    unverified = any(
        (DB["beneficiaries"].get(c["beneficiary_id"]) or {}).get("verification_status") != "VERIFIED"
        for c in campaigns
    )
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"],
        "display_name": o["display_name"], "email": o["email"],
        "total_dispute_count": total_dispute,
        "upheld_dispute_count": upheld,
        "refunded_amount_cents": refunded,
        "raised_cents": raised,
        "has_unverified_beneficiary": unverified,
        "strict_risk_score": risk_score(total_dispute, refunded, raised, unverified),
        "lenient_risk_score": risk_score(upheld, refunded, raised, unverified),
    }


def s_beneficiary(b):
    payouts = [p for p in DB["payouts"].values() if p["beneficiary_id"] == b["id"]]
    total_paid = sum(p["amount_cents"] for p in payouts if p["status"] == "PAID")
    ready = b["verification_status"] == "VERIFIED" and b["stripe_account_ref"] is not None
    return {
        "id": b["id"], "created_at": b["created_at"], "updated_at": b["updated_at"], "version": b["version"],
        "legal_name": b["legal_name"], "email": b["email"],
        "stripe_account_ref": b["stripe_account_ref"],
        "verification_status": b["verification_status"],
        "withdrawal_ready": ready,
        "total_paid_out_cents": total_paid,
        "last_payout_settled_at": fmt_dt(b["last_payout_settled_at"]),
    }


def s_donor(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
        "display_name": d["display_name"], "email": d["email"],
        "is_anonymous_default": d["is_anonymous_default"],
    }


def s_campaign(c):
    m = campaign_money(c)
    out = {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
        "organizer_id": c["organizer_id"], "beneficiary_id": c["beneficiary_id"],
        "title": c["title"], "story": c["story"], "goal_cents": c["goal_cents"],
        "category": c["category"], "is_charity": c["is_charity"],
        "lifecycle_status": c["lifecycle_status"],
        "payout_posture": compute_posture(c),
        "tax_disclosure": "TAX_DEDUCTIBLE" if c["is_charity"] else "NOT_TAX_DEDUCTIBLE",
    }
    out.update(m)
    return out


def s_team_member(t):
    return {
        "id": t["id"], "created_at": t["created_at"], "updated_at": t["updated_at"], "version": t["version"],
        "campaign_id": t["campaign_id"], "organizer_id": t["organizer_id"],
        "team_role": t["team_role"], "status": t["status"],
    }


def s_donation(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
        "campaign_id": d["campaign_id"], "donor_id": d["donor_id"],
        "amount_cents": d["amount_cents"], "tip_cents": d["tip_cents"],
        "is_anonymous": d["is_anonymous"],
        "processing_fee_cents": d["processing_fee_cents"],
        "total_charged_cents": d["total_charged_cents"],
        "net_to_campaign_cents": d["net_to_campaign_cents"],
        "reserve_cents": d["reserve_cents"],
        "status": d["status"],
        "tax_receipt_status": d["tax_receipt_status"],
        "thanked": d["thanked"],
    }


def s_update(u):
    return {
        "id": u["id"], "created_at": u["created_at"],
        "campaign_id": u["campaign_id"], "update_type": u["update_type"],
        "body": u["body"], "donation_id": u["donation_id"],
    }


def s_payout(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
        "campaign_id": p["campaign_id"], "beneficiary_id": p["beneficiary_id"],
        "amount_cents": p["amount_cents"],
        "scheduled_at": fmt_dt(p["scheduled_at"]),
        "status": p["status"],
        "stripe_payout_ref": p["stripe_payout_ref"],
        "settled_at": fmt_dt(p["settled_at"]),
    }


def s_dispute(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
        "donation_id": d["donation_id"], "reason": d["reason"],
        "status": d["status"], "resolution_note": d["resolution_note"],
    }


def s_refund(r):
    return {
        "id": r["id"], "created_at": r["created_at"],
        "donation_id": r["donation_id"], "dispute_id": r["dispute_id"],
        "amount_cents": r["amount_cents"], "reason": r["reason"],
    }


def s_hold(h):
    return {
        "id": h["id"], "created_at": h["created_at"], "updated_at": h["updated_at"], "version": h["version"],
        "campaign_id": h["campaign_id"], "reason": h["reason"],
        "severity": h["severity"], "locked_amount_cents": h["locked_amount_cents"],
        "status": h["status"],
    }


def s_placement(f):
    return {
        "id": f["id"], "created_at": f["created_at"], "updated_at": f["updated_at"], "version": f["version"],
        "campaign_id": f["campaign_id"], "category": f["category"],
        "slot_index": f["slot_index"],
        "window_start": fmt_dt(f["window_start"]),
        "window_end": fmt_dt(f["window_end"]),
        "status": f["status"],
    }


# =============================================================================
# Generic list / get
# =============================================================================
def paginate(items):
    limit = request.args.get("limit", "10")
    offset = request.args.get("offset", "0")
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        raise invalid()
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid()
    total = len(items)
    page = items[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta_extra


def do_list(collection, filter_keys, serializer):
    authorize(ALL_ROLES)
    items = list(DB[collection].values())
    for key in filter_keys:
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if str(x.get(key)) == val]
    items.sort(key=lambda x: x["_seq"])
    page, mx = paginate(items)
    return ok([serializer(x) for x in page], 200, "array", mx)


def do_get(collection, rid, serializer):
    authorize(ALL_ROLES)
    ent = DB[collection].get(rid)
    if not ent:
        raise not_found()
    return ok(serializer(ent), 200)


# =============================================================================
# Clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    authorize(["PlatformAdmin"])
    b = get_body()
    to = parse_dt(need(b, "to_iso8601"))
    CLOCK["now"] = to
    # Expire BOOKED placements whose window_end <= new clock
    for f in DB["feature_placements"].values():
        if f["status"] == "BOOKED" and f["window_end"] <= to:
            f["status"] = "EXPIRED"
            touch(f)
    return ok({}, 200)


# =============================================================================
# Organizer
# =============================================================================
@app.route("/organizers", methods=["POST"])
def create_organizer():
    authorize(["Guest"])
    b = get_body()
    display_name = as_str(need(b, "display_name"))
    email = as_str(need(b, "email"))
    o = base(common=True)
    o.update({"display_name": display_name, "email": email})
    DB["organizers"][o["id"]] = o
    return ok(s_organizer(o), 201)


@app.route("/organizers/<rid>", methods=["GET"])
def get_organizer(rid):
    return do_get("organizers", rid, s_organizer)


# =============================================================================
# Beneficiary
# =============================================================================
@app.route("/beneficiaries", methods=["POST"])
def create_beneficiary():
    authorize(["Guest"])
    b = get_body()
    legal_name = as_str(need(b, "legal_name"))
    email = as_str(need(b, "email"))
    ent = base(common=True)
    ent.update({
        "legal_name": legal_name, "email": email,
        "stripe_account_ref": None,
        "verification_status": "UNVERIFIED",
        "last_payout_settled_at": None,
    })
    DB["beneficiaries"][ent["id"]] = ent
    return ok(s_beneficiary(ent), 201)


@app.route("/beneficiaries/<rid>", methods=["GET"])
def get_beneficiary(rid):
    return do_get("beneficiaries", rid, s_beneficiary)


@app.route("/beneficiaries/<rid>/withdrawal-setup", methods=["POST"])
def beneficiary_withdrawal_setup(rid):
    uid, role = authorize(["Beneficiary", "PlatformAdmin"])
    b = get_body()
    ref = as_str(need(b, "stripe_account_ref"))
    ben = DB["beneficiaries"].get(rid)
    if not ben:
        raise not_found()
    if role == "Beneficiary" and uid != rid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the acting beneficiary")
    ben["stripe_account_ref"] = ref
    touch(ben)
    return ok(s_beneficiary(ben), 200)


@app.route("/beneficiaries/<rid>/submit-verification", methods=["POST"])
def beneficiary_submit_verification(rid):
    uid, role = authorize(["Beneficiary"])
    ben = DB["beneficiaries"].get(rid)
    if not ben:
        raise not_found()
    if uid != rid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the acting beneficiary")
    if ben["verification_status"] not in ("UNVERIFIED", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Cannot submit verification from current state")
    if ben["stripe_account_ref"] is None:
        raise ApiError("ERR_WITHDRAWAL_NOT_READY", 409, "Withdrawal account not connected")
    ben["verification_status"] = "PENDING"
    touch(ben)
    return ok(s_beneficiary(ben), 200)


@app.route("/beneficiaries/<rid>/approve-verification", methods=["POST"])
def beneficiary_approve_verification(rid):
    authorize(["TrustSafetyAgent"])
    ben = DB["beneficiaries"].get(rid)
    if not ben:
        raise not_found()
    if ben["verification_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Can only approve a PENDING beneficiary")
    ben["verification_status"] = "VERIFIED"
    touch(ben)
    recompute_posture_cascade_plain(ben)  # posture recompute per campaign (may unfreeze)
    return ok(s_beneficiary(ben), 200)


@app.route("/beneficiaries/<rid>/reject-verification", methods=["POST"])
def beneficiary_reject_verification(rid):
    authorize(["TrustSafetyAgent"])
    b = get_body()
    ben = DB["beneficiaries"].get(rid)
    if not ben:
        raise not_found()
    if ben["verification_status"] not in ("PENDING", "VERIFIED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Can only reject a PENDING or VERIFIED beneficiary")
    reason = b.get("reason")
    if reason is not None:
        ben["_reject_reason"] = reason
    ben["verification_status"] = "REJECTED"
    touch(ben)
    recompute_posture_cascade_freeze(ben)
    return ok(s_beneficiary(ben), 200)


# =============================================================================
# Donor
# =============================================================================
@app.route("/donors", methods=["POST"])
def create_donor():
    authorize(["Guest"])
    b = get_body()
    display_name = as_str(need(b, "display_name"))
    email = as_str(need(b, "email"))
    is_anon_default = False
    if "is_anonymous_default" in b and b["is_anonymous_default"] is not None:
        is_anon_default = as_bool(b["is_anonymous_default"])
    d = base(common=True)
    d.update({"display_name": display_name, "email": email, "is_anonymous_default": is_anon_default})
    DB["donors"][d["id"]] = d
    return ok(s_donor(d), 201)


@app.route("/donors/<rid>", methods=["GET"])
def get_donor(rid):
    return do_get("donors", rid, s_donor)


# =============================================================================
# Campaign
# =============================================================================
@app.route("/campaigns", methods=["POST"])
def create_campaign():
    uid, role = authorize(["Organizer"])
    b = get_body()
    beneficiary_id = as_str(need(b, "beneficiary_id"))
    title = as_str(need(b, "title"))
    story = as_str(need(b, "story"))
    goal_cents = as_int(need(b, "goal_cents"))
    category = as_enum(need(b, "category"), CATEGORY_ENUM)
    is_charity = False
    if "is_charity" in b and b["is_charity"] is not None:
        is_charity = as_bool(b["is_charity"])
    # existence
    if beneficiary_id not in DB["beneficiaries"]:
        raise not_found()
    # business constraint
    if goal_cents <= 0:
        raise ApiError("ERR_GOAL_INVALID", 422, "goal_cents must be > 0")
    c = base(common=True)
    c.update({
        "organizer_id": uid, "beneficiary_id": beneficiary_id,
        "title": title, "story": story, "goal_cents": goal_cents,
        "category": category, "is_charity": is_charity,
        "lifecycle_status": "DRAFT",
    })
    DB["campaigns"][c["id"]] = c
    # initial OWNER team member
    tm = base(common=True)
    tm.update({"campaign_id": c["id"], "organizer_id": uid, "team_role": "OWNER", "status": "ACTIVE"})
    DB["team_members"][tm["id"]] = tm
    return ok(s_campaign(c), 201)


@app.route("/campaigns/<rid>", methods=["GET"])
def get_campaign(rid):
    return do_get("campaigns", rid, s_campaign)


@app.route("/campaigns", methods=["GET"])
def list_campaigns():
    return do_list("campaigns", ["organizer_id", "beneficiary_id", "lifecycle_status"], s_campaign)


@app.route("/campaigns/<rid>", methods=["PATCH"])
def patch_campaign(rid):
    uid, role = authorize(["Organizer"])
    b = get_body()
    expected = as_int(need(b, "expected_campaign_version"))
    title = as_str(b["title"]) if ("title" in b and b["title"] is not None) else None
    story = as_str(b["story"]) if ("story" in b and b["story"] is not None) else None
    goal = as_int(b["goal_cents"]) if ("goal_cents" in b and b["goal_cents"] is not None) else None
    c = DB["campaigns"].get(rid)
    if not c:
        raise not_found()
    if not active_member(rid, uid, owner_only=True):
        raise ApiError("ERR_FORBIDDEN", 403, "Only an active OWNER may edit the campaign")
    if expected != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_campaign_version does not match")
    if title is not None:
        c["title"] = title
    if story is not None:
        c["story"] = story
    if goal is not None:
        c["goal_cents"] = goal
    touch(c)
    return ok(s_campaign(c), 200)


def _campaign_transition(rid, valid_from, target, owner_only, cascade_cancel=False):
    uid, role = authorize(["Organizer"])
    c = DB["campaigns"].get(rid)
    if not c:
        raise not_found()
    if not active_member(rid, uid, owner_only=owner_only):
        raise ApiError("ERR_FORBIDDEN", 403, "Acting organizer is not a sufficiently-privileged team member")
    if c["lifecycle_status"] not in valid_from:
        raise ApiError("ERR_INVALID_STATE", 409, "Invalid lifecycle transition")
    c["lifecycle_status"] = target
    if cascade_cancel:
        for p in DB["payouts"].values():
            if p["campaign_id"] == c["id"] and p["status"] in ("REQUESTED", "PROCESSING", "ON_HOLD"):
                p["status"] = "CANCELLED"
                touch(p)
    touch(c)
    return ok(s_campaign(c), 200)


@app.route("/campaigns/<rid>/publish", methods=["POST"])
def publish_campaign(rid):
    return _campaign_transition(rid, {"DRAFT"}, "ACTIVE", owner_only=True)


@app.route("/campaigns/<rid>/pause", methods=["POST"])
def pause_campaign(rid):
    return _campaign_transition(rid, {"ACTIVE"}, "PAUSED", owner_only=False)


@app.route("/campaigns/<rid>/resume", methods=["POST"])
def resume_campaign(rid):
    return _campaign_transition(rid, {"PAUSED"}, "ACTIVE", owner_only=False)


@app.route("/campaigns/<rid>/complete", methods=["POST"])
def complete_campaign(rid):
    return _campaign_transition(rid, {"ACTIVE", "PAUSED"}, "COMPLETED", owner_only=False)


@app.route("/campaigns/<rid>/cancel", methods=["POST"])
def cancel_campaign(rid):
    return _campaign_transition(rid, {"DRAFT", "ACTIVE", "PAUSED"}, "CANCELLED", owner_only=False, cascade_cancel=True)


# =============================================================================
# TeamMember
# =============================================================================
@app.route("/team-members", methods=["POST"])
def create_team_member():
    uid, role = authorize(["Organizer"])
    b = get_body()
    campaign_id = as_str(need(b, "campaign_id"))
    organizer_id = as_str(need(b, "organizer_id"))
    team_role = as_enum(need(b, "team_role"), TEAM_ROLE_ENUM)
    # existence left-to-right
    if campaign_id not in DB["campaigns"]:
        raise not_found()
    if organizer_id not in DB["organizers"]:
        raise not_found()
    # ownership: acting organizer must be an active member of the campaign
    if not active_member(campaign_id, uid, owner_only=False):
        raise ApiError("ERR_FORBIDDEN", 403, "Acting organizer is not a team member of this campaign")
    # duplicate active membership for the organizer being added
    for tm in DB["team_members"].values():
        if tm["campaign_id"] == campaign_id and tm["organizer_id"] == organizer_id and tm["status"] == "ACTIVE":
            raise ApiError("ERR_DUPLICATE_TEAM_MEMBER", 409, "Organizer already has an active membership")
    tm = base(common=True)
    tm.update({"campaign_id": campaign_id, "organizer_id": organizer_id, "team_role": team_role, "status": "ACTIVE"})
    DB["team_members"][tm["id"]] = tm
    return ok(s_team_member(tm), 201)


@app.route("/team-members/<rid>", methods=["GET"])
def get_team_member(rid):
    return do_get("team_members", rid, s_team_member)


@app.route("/team-members", methods=["GET"])
def list_team_members():
    return do_list("team_members", ["campaign_id", "organizer_id"], s_team_member)


@app.route("/team-members/<rid>/remove", methods=["POST"])
def remove_team_member(rid):
    uid, role = authorize(["Organizer"])
    tm = DB["team_members"].get(rid)
    if not tm:
        raise not_found()
    if not active_member(tm["campaign_id"], uid, owner_only=False):
        raise ApiError("ERR_FORBIDDEN", 403, "Acting organizer is not a team member of this campaign")
    if tm["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Team member is not ACTIVE")
    tm["status"] = "REMOVED"
    touch(tm)
    return ok(s_team_member(tm), 200)


# =============================================================================
# Donation
# =============================================================================
@app.route("/donations", methods=["POST"])
def create_donation():
    uid, role = authorize(["Donor"])
    b = get_body()
    campaign_id = as_str(need(b, "campaign_id"))
    donor_id = as_str(need(b, "donor_id"))
    amount_cents = as_int(need(b, "amount_cents"))
    tip_cents = 0
    if "tip_cents" in b and b["tip_cents"] is not None:
        tip_cents = as_int(b["tip_cents"])
    is_anonymous = None
    if "is_anonymous" in b and b["is_anonymous"] is not None:
        is_anonymous = as_bool(b["is_anonymous"])
    # existence left-to-right: campaign then donor
    c = DB["campaigns"].get(campaign_id)
    if not c:
        raise not_found()
    donor = DB["donors"].get(donor_id)
    if not donor:
        raise not_found()
    # state: campaign must be ACTIVE
    if c["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE", 409, "Campaign is not ACTIVE")
    # amount minimum
    if amount_cents < MIN_DONATION_CENTS:
        raise ApiError("ERR_AMOUNT_BELOW_MIN", 422, "Donation below minimum")
    # donor identity match
    if donor_id != uid:
        raise ApiError("ERR_DONOR_MISMATCH", 403, "donor_id does not match acting donor")
    if is_anonymous is None:
        is_anonymous = donor["is_anonymous_default"]
    fee, total_charged, net, reserve = donation_breakdown(amount_cents, tip_cents)
    d = base(common=True)
    d.update({
        "campaign_id": campaign_id, "donor_id": donor_id,
        "amount_cents": amount_cents, "tip_cents": tip_cents,
        "is_anonymous": is_anonymous,
        "processing_fee_cents": fee, "total_charged_cents": total_charged,
        "net_to_campaign_cents": net, "reserve_cents": reserve,
        "status": "CAPTURED",
        "tax_receipt_status": "DEDUCTIBLE" if c["is_charity"] else "NON_DEDUCTIBLE",
        "thanked": False,
    })
    DB["donations"][d["id"]] = d
    return ok(s_donation(d), 201)


@app.route("/donations/<rid>", methods=["GET"])
def get_donation(rid):
    return do_get("donations", rid, s_donation)


@app.route("/donations", methods=["GET"])
def list_donations():
    return do_list("donations", ["campaign_id", "donor_id", "status"], s_donation)


@app.route("/donations/<rid>/refund", methods=["POST"])
def refund_donation(rid):
    uid, role = authorize(["Donor", "TrustSafetyAgent", "PlatformAdmin"])
    d = DB["donations"].get(rid)
    if not d:
        raise not_found()
    if role == "Donor" and d["donor_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Donor may only refund their own donation")
    if d["status"] != "CAPTURED":
        raise ApiError("ERR_INVALID_STATE", 409, "Donation is not CAPTURED")
    r = base(common=False)
    r.update({
        "donation_id": d["id"], "dispute_id": None,
        "amount_cents": d["net_to_campaign_cents"], "reason": "REQUESTED_BY_DONOR",
    })
    DB["refunds"][r["id"]] = r
    d["status"] = "REFUNDED"
    touch(d)
    c = DB["campaigns"].get(d["campaign_id"])
    if c:
        enforce_over_commitment(c)
    return ok(s_refund(r), 201)


# =============================================================================
# Update / Thank-you
# =============================================================================
@app.route("/updates", methods=["POST"])
def create_update():
    uid, role = authorize(["Organizer"])
    b = get_body()
    campaign_id = as_str(need(b, "campaign_id"))
    update_type = as_enum(need(b, "update_type"), UPDATE_TYPE_ENUM)
    body_text = as_str(need(b, "body"))
    donation_id = None
    if "donation_id" in b and b["donation_id"] is not None:
        donation_id = as_str(b["donation_id"])
    # existence left-to-right
    c = DB["campaigns"].get(campaign_id)
    if not c:
        raise not_found()
    target_donation = None
    if donation_id is not None:
        target_donation = DB["donations"].get(donation_id)
        if not target_donation:
            raise not_found()
    # ownership
    if not active_member(campaign_id, uid, owner_only=False):
        raise ApiError("ERR_FORBIDDEN", 403, "Acting organizer is not a team member of this campaign")
    # frozen posture blocks writes to campaign children
    if compute_posture(c) == "FROZEN":
        raise ApiError("ERR_CAMPAIGN_FROZEN", 409, "Campaign is frozen")
    u = base(common=False)
    u.update({
        "campaign_id": campaign_id, "update_type": update_type,
        "body": body_text, "donation_id": donation_id,
    })
    DB["updates"][u["id"]] = u
    if update_type == "THANK_YOU" and target_donation is not None:
        target_donation["thanked"] = True
        touch(target_donation)
    return ok(s_update(u), 201)


@app.route("/updates/<rid>", methods=["GET"])
def get_update(rid):
    return do_get("updates", rid, s_update)


@app.route("/updates", methods=["GET"])
def list_updates():
    return do_list("updates", ["campaign_id", "donation_id"], s_update)


# =============================================================================
# Payout
# =============================================================================
@app.route("/payouts", methods=["POST"])
def create_payout():
    uid, role = authorize(["Organizer"])
    b = get_body()
    campaign_id = as_str(need(b, "campaign_id"))
    amount_cents = as_int(need(b, "amount_cents"))
    expected = as_int(need(b, "expected_campaign_version"))
    scheduled_at = None
    if "scheduled_at" in b and b["scheduled_at"] is not None:
        scheduled_at = parse_dt(b["scheduled_at"])
    # existence
    c = DB["campaigns"].get(campaign_id)
    if not c:
        raise not_found()
    ben = DB["beneficiaries"].get(c["beneficiary_id"])
    # ownership
    if not active_member(campaign_id, uid, owner_only=False):
        raise ApiError("ERR_FORBIDDEN", 403, "Acting organizer is not a team member of this campaign")
    # posture must be OPEN
    if compute_posture(c) != "OPEN":
        raise ApiError("ERR_PAYOUT_ON_HOLD", 409, "Campaign payout posture is not OPEN")
    # beneficiary verified & withdrawal ready
    ready = ben and ben["verification_status"] == "VERIFIED" and ben["stripe_account_ref"] is not None
    if not ready:
        raise ApiError("ERR_BENEFICIARY_NOT_VERIFIED", 409, "Beneficiary not verified / withdrawal not ready")
    # amount > 0
    if amount_cents <= 0:
        raise ApiError("ERR_GOAL_INVALID", 422, "amount_cents must be > 0")
    # sufficient settled availability
    if amount_cents > campaign_money(c)["settled_available_cents"]:
        raise ApiError("ERR_INSUFFICIENT_AVAILABLE", 402, "Insufficient settled availability")
    # cooldown
    sched = scheduled_at if scheduled_at is not None else CLOCK["now"]
    if ben["last_payout_settled_at"] is not None:
        earliest = ben["last_payout_settled_at"] + timedelta(hours=COOLDOWN_HOURS)
        if sched < earliest:
            raise ApiError("ERR_PAYOUT_COOLDOWN", 409, "Payout scheduled within cooldown window")
    # OCC
    if expected != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_campaign_version does not match")
    p = base(common=True)
    p.update({
        "campaign_id": campaign_id, "beneficiary_id": c["beneficiary_id"],
        "amount_cents": amount_cents, "scheduled_at": sched,
        "status": "REQUESTED", "stripe_payout_ref": None, "settled_at": None,
    })
    DB["payouts"][p["id"]] = p
    touch(c)  # payout request advances campaign version
    return ok(s_payout(p), 201)


@app.route("/payouts/<rid>", methods=["GET"])
def get_payout(rid):
    return do_get("payouts", rid, s_payout)


@app.route("/payouts", methods=["GET"])
def list_payouts():
    return do_list("payouts", ["campaign_id", "beneficiary_id", "status"], s_payout)


@app.route("/payouts/<rid>/process", methods=["POST"])
def process_payout(rid):
    authorize(["PlatformAdmin"])
    p = DB["payouts"].get(rid)
    if not p:
        raise not_found()
    if p["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payout is not REQUESTED")
    c = DB["campaigns"].get(p["campaign_id"])
    if compute_posture(c) != "OPEN":
        raise ApiError("ERR_PAYOUT_ON_HOLD", 409, "Campaign payout posture is not OPEN")
    ben = DB["beneficiaries"].get(c["beneficiary_id"])
    ready = ben and ben["verification_status"] == "VERIFIED" and ben["stripe_account_ref"] is not None
    if not ready:
        raise ApiError("ERR_BENEFICIARY_NOT_VERIFIED", 409, "Beneficiary not verified")
    p["status"] = "PROCESSING"
    touch(p)
    return ok(s_payout(p), 200)


@app.route("/payouts/<rid>/settle", methods=["POST"])
def settle_payout(rid):
    authorize(["PlatformAdmin"])
    b = get_body()
    p = DB["payouts"].get(rid)
    if not p:
        raise not_found()
    if p["status"] != "PROCESSING":
        raise ApiError("ERR_INVALID_STATE", 409, "Payout is not PROCESSING")
    ref = None
    if "stripe_payout_ref" in b and b["stripe_payout_ref"] is not None:
        ref = as_str(b["stripe_payout_ref"])
    settled_at = CLOCK["now"]
    p["status"] = "PAID"
    p["stripe_payout_ref"] = ref
    p["settled_at"] = settled_at
    touch(p)
    ben = DB["beneficiaries"].get(p["beneficiary_id"])
    if ben:
        ben["last_payout_settled_at"] = settled_at
        touch(ben)
    c = DB["campaigns"].get(p["campaign_id"])
    if c:
        touch(c)  # settled payout cascade advances campaign version
    return ok(s_payout(p), 200)


@app.route("/payouts/<rid>/fail", methods=["POST"])
def fail_payout(rid):
    authorize(["PlatformAdmin"])
    p = DB["payouts"].get(rid)
    if not p:
        raise not_found()
    if p["status"] not in ("REQUESTED", "PROCESSING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Payout is not REQUESTED/PROCESSING")
    p["status"] = "FAILED"
    touch(p)
    return ok(s_payout(p), 200)


@app.route("/payouts/<rid>/resume", methods=["POST"])
def resume_payout(rid):
    authorize(["TrustSafetyAgent"])
    p = DB["payouts"].get(rid)
    if not p:
        raise not_found()
    if p["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_STATE", 409, "Payout is not ON_HOLD")
    c = DB["campaigns"].get(p["campaign_id"])
    if compute_posture(c) != "OPEN":
        raise ApiError("ERR_PAYOUT_ON_HOLD", 409, "Campaign payout posture is not OPEN")
    if p["amount_cents"] > campaign_money(c)["settled_available_cents"]:
        raise ApiError("ERR_INSUFFICIENT_AVAILABLE", 402, "Insufficient settled availability")
    p["status"] = "REQUESTED"
    touch(p)
    return ok(s_payout(p), 200)


@app.route("/payouts/<rid>/reverse", methods=["POST"])
def reverse_payout(rid):
    authorize(["TrustSafetyAgent"])
    p = DB["payouts"].get(rid)
    if not p:
        raise not_found()
    if p["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Payout is not PAID")
    p["status"] = "REVERSED"
    touch(p)
    return ok(s_payout(p), 200)


# =============================================================================
# Dispute
# =============================================================================
@app.route("/disputes", methods=["POST"])
def create_dispute():
    uid, role = authorize(["Donor", "TrustSafetyAgent"])
    b = get_body()
    donation_id = as_str(need(b, "donation_id"))
    reason = as_enum(need(b, "reason"), DISPUTE_REASON_ENUM)
    d = DB["donations"].get(donation_id)
    if not d:
        raise not_found()
    if role == "Donor" and d["donor_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Donor may only dispute their own donation")
    if d["status"] != "CAPTURED":
        raise ApiError("ERR_INVALID_STATE", 409, "Donation is not CAPTURED")
    dp = base(common=True)
    dp.update({"donation_id": donation_id, "reason": reason, "status": "OPEN", "resolution_note": None})
    DB["disputes"][dp["id"]] = dp
    return ok(s_dispute(dp), 201)


@app.route("/disputes/<rid>", methods=["GET"])
def get_dispute(rid):
    return do_get("disputes", rid, s_dispute)


@app.route("/disputes", methods=["GET"])
def list_disputes():
    return do_list("disputes", ["donation_id", "status"], s_dispute)


@app.route("/disputes/<rid>/assign", methods=["POST"])
def assign_dispute(rid):
    authorize(["TrustSafetyAgent"])
    dp = DB["disputes"].get(rid)
    if not dp:
        raise not_found()
    if dp["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not OPEN")
    dp["status"] = "UNDER_REVIEW"
    touch(dp)
    return ok(s_dispute(dp), 200)


@app.route("/disputes/<rid>/request-info", methods=["POST"])
def request_info_dispute(rid):
    authorize(["TrustSafetyAgent"])
    dp = DB["disputes"].get(rid)
    if not dp:
        raise not_found()
    if dp["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not UNDER_REVIEW")
    dp["status"] = "NEEDS_INFO"
    touch(dp)
    return ok(s_dispute(dp), 200)


@app.route("/disputes/<rid>/provide-info", methods=["POST"])
def provide_info_dispute(rid):
    uid, role = authorize(["Donor"])
    dp = DB["disputes"].get(rid)
    if not dp:
        raise not_found()
    donation = DB["donations"].get(dp["donation_id"])
    if donation and donation["donor_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Donor may only act on their own dispute")
    if dp["status"] != "NEEDS_INFO":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not NEEDS_INFO")
    dp["status"] = "UNDER_REVIEW"
    touch(dp)
    return ok(s_dispute(dp), 200)


@app.route("/disputes/<rid>/uphold", methods=["POST"])
def uphold_dispute(rid):
    authorize(["TrustSafetyAgent"])
    b = get_body()
    dp = DB["disputes"].get(rid)
    if not dp:
        raise not_found()
    if dp["status"] not in ("UNDER_REVIEW", "NEEDS_INFO"):
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not UNDER_REVIEW/NEEDS_INFO")
    donation = DB["donations"].get(dp["donation_id"])
    if not donation or donation["status"] != "CAPTURED":
        raise ApiError("ERR_INVALID_STATE", 409, "Parent donation is not CAPTURED")
    note = b.get("resolution_note")
    dp["status"] = "UPHELD"
    dp["resolution_note"] = note
    touch(dp)
    # cascade: create refund, refund donation, recompute, hold over-committed payouts
    r = base(common=False)
    r.update({
        "donation_id": donation["id"], "dispute_id": dp["id"],
        "amount_cents": donation["net_to_campaign_cents"], "reason": "DISPUTE_UPHELD",
    })
    DB["refunds"][r["id"]] = r
    donation["status"] = "REFUNDED"
    touch(donation)
    c = DB["campaigns"].get(donation["campaign_id"])
    if c:
        touch(c)  # upheld dispute cascade advances campaign version
        enforce_over_commitment(c)
    return ok(s_dispute(dp), 200)


@app.route("/disputes/<rid>/reject", methods=["POST"])
def reject_dispute(rid):
    authorize(["TrustSafetyAgent"])
    b = get_body()
    dp = DB["disputes"].get(rid)
    if not dp:
        raise not_found()
    if dp["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not UNDER_REVIEW")
    dp["status"] = "REJECTED"
    dp["resolution_note"] = b.get("resolution_note")
    touch(dp)
    return ok(s_dispute(dp), 200)


# =============================================================================
# Refund (read-only surface)
# =============================================================================
@app.route("/refunds/<rid>", methods=["GET"])
def get_refund(rid):
    return do_get("refunds", rid, s_refund)


@app.route("/refunds", methods=["GET"])
def list_refunds():
    return do_list("refunds", ["donation_id", "dispute_id"], s_refund)


# =============================================================================
# Hold
# =============================================================================
@app.route("/holds", methods=["POST"])
def create_hold():
    authorize(["TrustSafetyAgent"])
    b = get_body()
    campaign_id = as_str(need(b, "campaign_id"))
    reason = as_str(need(b, "reason"))
    severity = as_enum(need(b, "severity"), SEVERITY_ENUM)
    locked = 0
    if "locked_amount_cents" in b and b["locked_amount_cents"] is not None:
        locked = as_int(b["locked_amount_cents"])
    c = DB["campaigns"].get(campaign_id)
    if not c:
        raise not_found()
    h = base(common=True)
    h.update({
        "campaign_id": campaign_id, "reason": reason, "severity": severity,
        "locked_amount_cents": locked, "status": "ACTIVE",
    })
    DB["holds"][h["id"]] = h
    touch(c)  # posture recompute advances campaign version
    return ok(s_hold(h), 201)


@app.route("/holds/<rid>", methods=["GET"])
def get_hold(rid):
    return do_get("holds", rid, s_hold)


@app.route("/holds", methods=["GET"])
def list_holds():
    return do_list("holds", ["campaign_id", "status"], s_hold)


@app.route("/holds/<rid>/release", methods=["POST"])
def release_hold(rid):
    authorize(["TrustSafetyAgent"])
    h = DB["holds"].get(rid)
    if not h:
        raise not_found()
    if h["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Hold is not ACTIVE")
    h["status"] = "RELEASED"
    touch(h)
    c = DB["campaigns"].get(h["campaign_id"])
    if c:
        touch(c)  # posture recompute advances campaign version
    return ok(s_hold(h), 200)


# =============================================================================
# FeaturePlacement
# =============================================================================
@app.route("/feature-placements", methods=["POST"])
def create_placement():
    authorize(["PlatformAdmin"])
    b = get_body()
    campaign_id = as_str(need(b, "campaign_id"))
    category = as_enum(need(b, "category"), PLACEMENT_CATEGORY_ENUM)
    slot_index = as_int(need(b, "slot_index"))
    window_start = parse_dt(need(b, "window_start"))
    window_end = parse_dt(need(b, "window_end"))
    c = DB["campaigns"].get(campaign_id)
    if not c:
        raise not_found()
    if not (window_end > window_start):
        raise ApiError("ERR_WINDOW_INVALID", 422, "window_end must be strictly after window_start")
    # slot conflict: overlap with existing BOOKED on same (category, slot_index); half-open
    for f in DB["feature_placements"].values():
        if f["status"] == "BOOKED" and f["category"] == category and f["slot_index"] == slot_index:
            if window_start < f["window_end"] and f["window_start"] < window_end:
                raise ApiError("ERR_SLOT_CONFLICT", 409, "Overlapping placement on same slot")
    f = base(common=True)
    f.update({
        "campaign_id": campaign_id, "category": category, "slot_index": slot_index,
        "window_start": window_start, "window_end": window_end, "status": "BOOKED",
    })
    DB["feature_placements"][f["id"]] = f
    return ok(s_placement(f), 201)


@app.route("/feature-placements/<rid>", methods=["GET"])
def get_placement(rid):
    return do_get("feature_placements", rid, s_placement)


@app.route("/feature-placements", methods=["GET"])
def list_placements():
    return do_list("feature_placements", ["campaign_id", "category"], s_placement)


@app.route("/feature-placements/<rid>/cancel", methods=["POST"])
def cancel_placement(rid):
    authorize(["PlatformAdmin"])
    f = DB["feature_placements"].get(rid)
    if not f:
        raise not_found()
    if f["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Placement is not BOOKED")
    f["status"] = "CANCELLED"
    touch(f)
    return ok(s_placement(f), 200)


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
