"""Program tier catalogue (PRD §3.3)."""
from flask import Blueprint, request

from auth import authenticate, require_role, body, get_str, get_int
from db import store
from envelope import success, success_list, paginate
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, not_found
from serializers import tier as ser_tier, base_row, touch

bp = Blueprint("tiers", __name__)

TIER_TYPES = ("SINGLE", "PACKAGE", "MEMBERSHIP")


@bp.post("/program-tiers")
def create_tier():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin",))
    b = body()
    tier_code = get_str(b, "tier_code")
    tier_type = b.get("tier_type")
    session_count = get_int(b, "session_count")
    price_cents = get_int(b, "price_cents")
    duration_days = get_int(b, "duration_days")
    installment_count_allowed = get_int(b, "installment_count_allowed")
    reschedule_cap = get_int(b, "reschedule_cap")
    if (tier_code is None or tier_type not in TIER_TYPES
            or session_count is None or session_count < 1
            or price_cents is None or price_cents < 0
            or duration_days is None or duration_days < 1
            or installment_count_allowed is None or installment_count_allowed < 1
            or reschedule_cap is None or reschedule_cap < 0):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: tier_code; tier_type in {SINGLE,PACKAGE,MEMBERSHIP}; "
                       "session_count >= 1; price_cents >= 0; duration_days >= 1; "
                       "installment_count_allowed >= 1; reschedule_cap >= 0")
    t = base_row()
    t.update({
        "tier_code": tier_code,
        "tier_type": tier_type,
        "session_count": session_count,
        "price_cents": price_cents,
        "duration_days": duration_days,
        "installment_count_allowed": installment_count_allowed,
        "reschedule_cap": reschedule_cap,
        "tier_status": "ACTIVE",
    })
    store.tiers[t["id"]] = t
    return success(ser_tier(t)), 201


@bp.get("/program-tiers/<tid>")
def get_tier(tid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    t = store.tiers.get(tid)
    if t is None:
        raise not_found("ProgramTier not found")
    return success(ser_tier(t))


@bp.get("/program-tiers")
def list_tiers():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    rows = list(store.tiers.values())
    ts = request.args.get("tier_status")
    if ts is not None:
        rows = [t for t in rows if t["tier_status"] == ts]
    rows.sort(key=lambda t: (t["created_at"], t["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_tier(t) for t in page], meta)


@bp.post("/program-tiers/<tid>/retire")
def retire_tier(tid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin",))
    t = store.tiers.get(tid)
    if t is None:
        raise not_found("ProgramTier not found")
    if t["tier_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE tier can be retired")
    t["tier_status"] = "RETIRED"
    touch(t)
    return success(ser_tier(t))
