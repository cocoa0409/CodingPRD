"""Clock, advisors, communities, inventories, families."""
from flask import Blueprint, request

import store
import calc
import services as svc
import validate as V
import envelope as E
import constants as C
from rbac import guard, deny_ownership
from errors import ApiError
from serialize import dump
from protected import PROTECTED

bp = Blueprint("ref", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    guard(["PlatformAdmin"])
    body = V.get_body()
    dt = V.req_datetime(body, "to_iso8601")
    store.set_now(dt)
    return E.ok({"current_utc": store.now_iso()}, 200)


# ---------------------------------------------------------------------------
# Advisors
# ---------------------------------------------------------------------------
def _advisor_out(a):
    svc.recompute_advisor_fields(a)
    return dump(a)


@bp.post("/advisors")
def create_advisor():
    guard(["PlatformAdmin"])
    body = V.get_body()
    V.reject_protected(body, {"full_name", "email", "region_code",
                              "is_va_certified", "caseload_capacity"}, PROTECTED["advisor"])
    full_name = V.req_str(body, "full_name")
    email = V.req_str(body, "email")
    region_code = V.req_str(body, "region_code")
    is_va = V.opt_bool(body, "is_va_certified")
    is_va = False if is_va is V._MISSING else is_va
    capacity = V.req_int(body, "caseload_capacity", 1, 25)
    row = svc.new_row("advisors", {
        "full_name": full_name, "email": email, "region_code": region_code,
        "is_va_certified": is_va, "caseload_capacity": capacity,
        "status": "ACTIVE", "active_caseload_count": 0,
        "headcount_load_index": calc.Decimal("0"),
        "weighted_load_index": calc.Decimal("0"),
    })
    return E.created(dump(row))


@bp.get("/advisors/<advisor_id>")
def get_advisor(advisor_id):
    guard(C.ALL_ROLES)
    a = V.lookup("advisors", advisor_id, "ERR_ADVISOR_NOT_FOUND")
    return E.ok(_advisor_out(a))


@bp.get("/advisors")
def list_advisors():
    guard(C.ALL_ROLES)
    rows = list(store.DB["advisors"].values())
    region = request.args.get("region_code")
    status = request.args.get("status")
    va = request.args.get("is_va_certified")
    if region is not None:
        rows = [r for r in rows if r["region_code"] == region]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if va is not None:
        want = va.lower() == "true"
        rows = [r for r in rows if r["is_va_certified"] == want]
    items, limit, offset, total, has_more = V.paginate(rows, _advisor_out)
    return E.ok_list(items, limit, offset, total, has_more)


@bp.patch("/advisors/<advisor_id>")
def patch_advisor(advisor_id):
    guard(["PlatformAdmin"])
    a = V.lookup("advisors", advisor_id, "ERR_ADVISOR_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"status", "caseload_capacity", "is_va_certified"},
                       PROTECTED["advisor"])
    status = V.opt_enum(body, "status", C.ADVISOR_STATUS)
    capacity = V.opt_int(body, "caseload_capacity", 1, 25)
    is_va = V.opt_bool(body, "is_va_certified")
    if status is not V._MISSING:
        a["status"] = status
    if is_va is not V._MISSING:
        a["is_va_certified"] = is_va
    if capacity is not V._MISSING:
        a["caseload_capacity"] = capacity
        svc.recompute_advisor_fields(a)
    svc.touch(a)
    return E.ok(dump(a))


# ---------------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------------
@bp.post("/communities")
def create_community():
    guard(["PlatformAdmin"])
    body = V.get_body()
    V.reject_protected(body, {"name", "region_code", "contract_tier", "referral_fee_pct",
                              "tour_slot_capacity", "quality_rating"}, PROTECTED["community"])
    name = V.req_str(body, "name")
    region_code = V.req_str(body, "region_code")
    tier = V.req_enum(body, "contract_tier", C.CONTRACT_TIERS)
    fee_pct = V.req_number(body, "referral_fee_pct", 0, 1.00, min_exclusive=True)
    slot = V.req_int(body, "tour_slot_capacity", 1, 20)
    quality = V.req_number(body, "quality_rating", 0.0, 5.0)
    row = svc.new_row("communities", {
        "name": name, "region_code": region_code, "contract_tier": tier,
        "referral_fee_pct": fee_pct, "tour_slot_capacity": slot,
        "quality_rating": quality, "status": "ACTIVE",
        "fee_balance_cents": 0, "satisfaction_survey_count": 0,
        "avg_satisfaction_score": calc.Decimal("0"),
    })
    return E.created(dump(row))


@bp.get("/communities/<community_id>")
def get_community(community_id):
    guard(C.ALL_ROLES)
    c = V.lookup("communities", community_id, "ERR_COMMUNITY_NOT_FOUND")
    return E.ok(dump(c))


@bp.get("/communities")
def list_communities():
    guard(C.ALL_ROLES)
    rows = list(store.DB["communities"].values())
    region = request.args.get("region_code")
    status = request.args.get("status")
    tier = request.args.get("contract_tier")
    if region is not None:
        rows = [r for r in rows if r["region_code"] == region]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tier is not None:
        rows = [r for r in rows if r["contract_tier"] == tier]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


@bp.patch("/communities/<community_id>")
def patch_community(community_id):
    guard(["PlatformAdmin"])
    c = V.lookup("communities", community_id, "ERR_COMMUNITY_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"status", "contract_tier", "referral_fee_pct",
                              "tour_slot_capacity", "quality_rating"}, PROTECTED["community"])
    status = V.opt_enum(body, "status", C.COMMUNITY_STATUS)
    tier = V.opt_enum(body, "contract_tier", C.CONTRACT_TIERS)
    fee_pct = V.opt_number(body, "referral_fee_pct", 0, 1.00, min_exclusive=True)
    slot = V.opt_int(body, "tour_slot_capacity", 1, 20)
    quality = V.opt_number(body, "quality_rating", 0.0, 5.0)
    if status is not V._MISSING:
        c["status"] = status
    if tier is not V._MISSING:
        c["contract_tier"] = tier
    if fee_pct is not V._MISSING:
        c["referral_fee_pct"] = fee_pct
    if slot is not V._MISSING:
        c["tour_slot_capacity"] = slot
    if quality is not V._MISSING:
        c["quality_rating"] = quality
    svc.touch(c)
    return E.ok(dump(c))


# ---------------------------------------------------------------------------
# Inventories
# ---------------------------------------------------------------------------
@bp.post("/inventories")
def create_inventory():
    uid, role = guard(["PlatformAdmin", "CommunityManager"])
    body = V.get_body()
    V.reject_protected(body, {"community_id", "care_level", "total_units",
                              "monthly_rate_cents"}, PROTECTED["inventory"])
    community_id = V.req_str(body, "community_id")
    care_level = V.req_enum(body, "care_level", C.CARE_LEVELS)
    total_units = V.req_int(body, "total_units", 0)
    rate = V.req_int(body, "monthly_rate_cents", 1)
    community = V.lookup("communities", community_id, "ERR_COMMUNITY_NOT_FOUND")
    if role == "CommunityManager" and uid != community_id:
        deny_ownership()
    # duplicate (community_id, care_level)
    for inv in store.DB["inventories"].values():
        if inv["community_id"] == community_id and inv["care_level"] == care_level:
            raise ApiError("ERR_DUPLICATE_INVENTORY",
                           "A unit pool already exists for this community and care level.")
    row = svc.new_row("inventories", {
        "community_id": community_id, "care_level": care_level,
        "total_units": total_units, "reserved_units": 0, "occupied_units": 0,
        "available_units": total_units, "monthly_rate_cents": rate, "status": "OPEN",
    })
    return E.created(dump(row))


@bp.get("/inventories/<inventory_id>")
def get_inventory(inventory_id):
    guard(C.ALL_ROLES)
    inv = V.lookup("inventories", inventory_id, "ERR_INVENTORY_NOT_FOUND")
    return E.ok(dump(inv))


@bp.get("/inventories")
def list_inventories():
    guard(C.ALL_ROLES)
    rows = list(store.DB["inventories"].values())
    community = request.args.get("community_id")
    care_level = request.args.get("care_level")
    status = request.args.get("status")
    if community is not None:
        rows = [r for r in rows if r["community_id"] == community]
    if care_level is not None:
        rows = [r for r in rows if r["care_level"] == care_level]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


@bp.patch("/inventories/<inventory_id>")
def patch_inventory(inventory_id):
    uid, role = guard(["PlatformAdmin", "CommunityManager"])
    inv = V.lookup("inventories", inventory_id, "ERR_INVENTORY_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"total_units", "monthly_rate_cents", "status"},
                       PROTECTED["inventory"])
    total_units = V.opt_int(body, "total_units", 0)
    rate = V.opt_int(body, "monthly_rate_cents", 1)
    status = V.opt_enum(body, "status", C.INVENTORY_STATUS)
    if role == "CommunityManager" and uid != inv["community_id"]:
        deny_ownership()
    if total_units is not V._MISSING:
        if total_units < inv["reserved_units"] + inv["occupied_units"]:
            raise ApiError("ERR_INVENTORY_UNDER_ALLOCATED",
                           "total_units below reserved + occupied.")
        inv["total_units"] = total_units
    if rate is not V._MISSING:
        inv["monthly_rate_cents"] = rate
    if status is not V._MISSING:
        inv["status"] = status
    svc.recompute_inventory_fields(inv)
    svc.touch(inv)
    return E.ok(dump(inv))


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------
@bp.post("/families")
def create_family():
    guard(["PlatformAdmin", "Advisor"])
    body = V.get_body()
    V.reject_protected(body, {"primary_contact_name", "email", "phone",
                              "relationship_to_senior", "state_code",
                              "senior_first_name", "senior_age"}, PROTECTED["family"])
    name = V.req_str(body, "primary_contact_name")
    email = V.req_str(body, "email")
    if "@" not in email:
        raise ApiError("ERR_VALIDATION", "email must contain '@'.")
    phone = V.req_str(body, "phone")
    rel = V.req_enum(body, "relationship_to_senior", C.RELATIONSHIPS)
    state_code = V.req_str(body, "state_code")
    senior_first = V.req_str(body, "senior_first_name")
    senior_age = V.req_int(body, "senior_age", 55, 120)
    row = svc.new_row("families", {
        "primary_contact_name": name, "email": email, "phone": phone,
        "relationship_to_senior": rel, "state_code": state_code,
        "senior_first_name": senior_first, "senior_age": senior_age,
    })
    return E.created(dump(row))


@bp.get("/families/<family_id>")
def get_family(family_id):
    guard(C.ALL_ROLES)
    f = V.lookup("families", family_id, "ERR_FAMILY_NOT_FOUND")
    return E.ok(dump(f))


@bp.get("/families")
def list_families():
    guard(C.ALL_ROLES)
    rows = list(store.DB["families"].values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)
