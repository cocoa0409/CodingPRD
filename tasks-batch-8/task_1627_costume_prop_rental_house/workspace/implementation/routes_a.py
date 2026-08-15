"""Routes: clock, daily ops, renters, certificates, rate cards, items, units."""

from flask import Blueprint, request

from db import (DB, RENTER_TYPES, PERIODS, CATEGORIES, SIZE_CLASSES,
                ALTERATION_POLICIES, CONDITION_GRADES, RENTER_STATUSES,
                CERT_STATUSES, RATE_CARD_STATUSES, ITEM_STATUSES, UNIT_STATUSES,
                INSURANCE_MIN_COVERAGE, new_record, touch, now_iso, today,
                sort_key, parse_date)
from errors import fail
from middleware import (authenticate, require_roles, scope_check, BodyReader,
                        renter_id_of_cert)
from response import respond_object, respond_list, serialize, serialize_many
from services import (run_daily_ops, recompute_renter_credit,
                      recompute_item_serviceable, suspend_renter,
                      has_verified_cert)

bp = Blueprint("routes_a", __name__)

ALL_ROLES = ["HouseAdmin", "WardrobeStaff", "RenterContact", "Accountant"]


# ---------------------------------------------------------------------------
# Logical clock / daily ops
# ---------------------------------------------------------------------------

@bp.post("/rental-house/_clock/set_current_utc")
def set_clock():
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    br = BodyReader()
    to_dt = br.get_datetime("to_iso8601")
    br.raise_if_errors()
    DB.clock = to_dt
    return respond_object({"current_utc": now_iso()})


@bp.post("/rental-house/run_daily_ops")
def daily_ops():
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    report = run_daily_ops()
    return respond_object(report)


# ---------------------------------------------------------------------------
# Renters
# ---------------------------------------------------------------------------

@bp.post("/rental-house/renters")
def create_renter():
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    br = BodyReader()
    name = br.get_str("name")
    renter_type = br.get_enum("renter_type", RENTER_TYPES)
    credit_limit = br.get_int("credit_limit_cents")
    br.raise_if_errors()
    rec = new_record()
    rec.update({
        "name": name,
        "renter_type": renter_type,
        "credit_limit_cents": credit_limit,
        "status": "PENDING_VERIFICATION",
        "outstanding_balance_cents": 0,
        "credit_hold": False,
    })
    DB.renters[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/renters")
def list_renters():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.renters.values())
    if role == "RenterContact":
        recs = [r for r in recs if r["id"] == uid]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/renters/<rid>")
def get_renter(rid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.renters.get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Renter not found")
    scope_check(uid, role, rec["id"])
    return respond_object(serialize(rec))


@bp.patch("/rental-house/renters/<rid>")
def patch_renter(rid):
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    rec = DB.renters.get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Renter not found")
    br = BodyReader()
    new_limit = br.get_int("credit_limit_cents", required=False)
    new_status = br.get_str("status", required=False)

    # Priority 5: state transition validity
    if new_status is not None and new_status in RENTER_STATUSES:
        cur = rec["status"]
        if new_status == cur or new_status == "PENDING_VERIFICATION" \
                or cur == "PENDING_VERIFICATION":
            fail("ERR_INVALID_STATE",
                 "Manual status changes are limited to ACTIVE<->SUSPENDED")
        # Priority 7: reactivation safety gate
        if cur == "SUSPENDED" and new_status == "ACTIVE":
            if not has_verified_cert(rec["id"], today()):
                fail("ERR_INSURANCE_NOT_VERIFIED",
                     "Reactivation requires a VERIFIED, unexpired certificate")
    if new_status is not None and new_status not in RENTER_STATUSES:
        br.errors.append("status: must be one of " + ", ".join(RENTER_STATUSES))
    br.raise_if_errors()

    touched = False
    if new_status is not None and new_status != rec["status"]:
        if new_status == "SUSPENDED":
            suspend_renter(rec)  # touches rec and cascades reservations
        else:
            rec["status"] = new_status
            touch(rec)
        touched = True
    if new_limit is not None and new_limit != rec["credit_limit_cents"]:
        rec["credit_limit_cents"] = new_limit
        # credit-limit change recomputes credit_hold (outstanding unchanged)
        rec["credit_hold"] = rec["outstanding_balance_cents"] > new_limit
        if not touched:
            touch(rec)
        touched = True
    return respond_object(serialize(rec))


# ---------------------------------------------------------------------------
# Insurance certificates
# ---------------------------------------------------------------------------

@bp.post("/rental-house/renters/<rid>/insurance-certificates")
def create_cert(rid):
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin", "RenterContact"])
    renter = DB.renters.get(rid)
    if renter is not None:
        scope_check(uid, role, renter["id"])
    if renter is None:
        fail("ERR_NOT_FOUND", "Renter not found")
    br = BodyReader()
    insurer_name = br.get_str("insurer_name")
    policy_number = br.get_str("policy_number")
    coverage = br.get_int("coverage_cents")
    effective = br.get_date("effective_date")
    expiry = br.get_date("expiry_date")
    br.raise_if_errors()
    rec = new_record()
    rec.update({
        "renter_id": rid,
        "insurer_name": insurer_name,
        "policy_number": policy_number,
        "coverage_cents": coverage,
        "effective_date": effective.isoformat(),
        "expiry_date": expiry.isoformat(),
        "status": "SUBMITTED",
        "decided_by_user_id": None,
        "_effective_date": effective,
        "_expiry_date": expiry,
    })
    DB.certificates[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/renters/<rid>/insurance-certificates")
def list_certs(rid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    renter = DB.renters.get(rid)
    if renter is not None:
        scope_check(uid, role, renter["id"])
    if renter is None:
        fail("ERR_NOT_FOUND", "Renter not found")
    recs = [c for c in DB.certificates.values() if c["renter_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/insurance-certificates/<cid>")
def get_cert(cid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.certificates.get(cid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Insurance certificate not found")
    scope_check(uid, role, rec["renter_id"])
    return respond_object(serialize(rec))


@bp.post("/rental-house/insurance-certificates/<cid>/decide")
def decide_cert(cid):
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    rec = DB.certificates.get(cid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Insurance certificate not found")
    br = BodyReader()
    decision = br.get_enum("decision", ["VERIFIED", "REJECTED"])
    # Priority 5: state
    if rec["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Certificate is not SUBMITTED")
    # Priority 7: coverage + expiry safety gates (coverage first)
    if decision == "VERIFIED":
        renter = DB.renters.get(rec["renter_id"])
        minimum = INSURANCE_MIN_COVERAGE[renter["renter_type"]]
        if rec["coverage_cents"] < minimum:
            fail("ERR_INSUFFICIENT_COVERAGE",
                 "Coverage below the renter-type minimum")
        if rec["_expiry_date"] < today():
            fail("ERR_CERTIFICATE_EXPIRED", "Certificate is already expired")
    br.raise_if_errors()

    rec["status"] = decision
    rec["decided_by_user_id"] = uid
    touch(rec)
    if decision == "VERIFIED":
        renter = DB.renters.get(rec["renter_id"])
        if renter is not None and renter["status"] in ("PENDING_VERIFICATION", "SUSPENDED"):
            renter["status"] = "ACTIVE"
            touch(renter)
    return respond_object(serialize(rec))


# ---------------------------------------------------------------------------
# Rate cards
# ---------------------------------------------------------------------------

@bp.post("/rental-house/rate-cards")
def create_rate_card():
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    br = BodyReader()
    name = br.get_str("name")
    lrt = br.get_int("long_run_threshold_weeks")
    lrd = br.get_num("long_run_discount_pct")
    drt = br.get_int("deep_run_threshold_weeks")
    drd = br.get_num("deep_run_discount_pct")
    lfp = br.get_num("late_fee_daily_pct")
    br.raise_if_errors()
    for c in DB.rate_cards.values():
        if c["status"] == "PUBLISHED":
            c["status"] = "SUPERSEDED"
            touch(c)
    rec = new_record()
    rec.update({
        "name": name,
        "long_run_threshold_weeks": lrt,
        "long_run_discount_pct": lrd,
        "deep_run_threshold_weeks": drt,
        "deep_run_discount_pct": drd,
        "late_fee_daily_pct": lfp,
        "status": "PUBLISHED",
    })
    DB.rate_cards[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/rate-cards")
def list_rate_cards():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.rate_cards.values())
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/rate-cards/<cid>")
def get_rate_card(cid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.rate_cards.get(cid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Rate card not found")
    return respond_object(serialize(rec))


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@bp.post("/rental-house/items")
def create_item():
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    br = BodyReader()
    name = br.get_str("name")
    period = br.get_enum("period", PERIODS)
    category = br.get_enum("category", CATEGORIES)
    size_class = br.get_enum("size_class", SIZE_CLASSES)
    alteration_policy = br.get_enum("alteration_policy", ALTERATION_POLICIES)
    replacement_value = br.get_int("replacement_value_cents")
    daily = br.get_int("base_daily_rate_cents")
    weekly = br.get_int("base_weekly_rate_cents")
    br.raise_if_errors()
    rec = new_record()
    rec.update({
        "name": name,
        "period": period,
        "category": category,
        "size_class": size_class,
        "alteration_policy": alteration_policy,
        "replacement_value_cents": replacement_value,
        "base_daily_rate_cents": daily,
        "base_weekly_rate_cents": weekly,
        "status": "ACTIVE",
        "serviceable_unit_count": 0,
    })
    DB.items[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/items")
def list_items():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.items.values())
    include_deacc = request.args.get("include_deaccessioned", "").lower() in \
        ("true", "1", "yes")
    if not include_deacc:
        recs = [i for i in recs if i["status"] != "DEACCESSIONED"]
    for field in ("period", "category", "size_class", "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [i for i in recs if i[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/items/<iid>")
def get_item(iid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.items.get(iid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Item not found")
    return respond_object(serialize(rec))


@bp.post("/rental-house/items/<iid>/request-deaccession")
def request_deaccession(iid):
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    item = DB.items.get(iid)
    if item is None:
        fail("ERR_NOT_FOUND", "Item not found")
    if item["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Item is not ACTIVE")
    # Priority 5: no HELD/CONFIRMED reservations
    for r in DB.reservations.values():
        if r["item_id"] == iid and r["status"] in ("HELD", "CONFIRMED"):
            fail("ERR_ITEM_HAS_ACTIVE_HOLDS",
                 "Item has HELD or CONFIRMED reservations")
    # Priority 10: every unit AVAILABLE / AWAITING_DISPOSAL / DISPOSED
    for u in DB.units.values():
        if u["item_id"] == iid and u["status"] in ("OUT", "CLEANING", "REPAIR"):
            fail("ERR_DEACCESSION_BLOCKED",
                 "Units are OUT, CLEANING, or REPAIR")
    for u in DB.units.values():
        if u["item_id"] == iid and u["status"] == "AVAILABLE":
            u["status"] = "AWAITING_DISPOSAL"
            touch(u)
    item["status"] = "DEACCESSION_PENDING"
    touch(item)
    recompute_item_serviceable(item)
    return respond_object(serialize(item))


@bp.post("/rental-house/items/<iid>/cancel-deaccession")
def cancel_deaccession(iid):
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    item = DB.items.get(iid)
    if item is None:
        fail("ERR_NOT_FOUND", "Item not found")
    if item["status"] != "DEACCESSION_PENDING":
        fail("ERR_INVALID_STATE", "Item is not DEACCESSION_PENDING")
    for u in DB.units.values():
        if u["item_id"] == iid and u["status"] == "AWAITING_DISPOSAL":
            u["status"] = "AVAILABLE"
            touch(u)
    item["status"] = "ACTIVE"
    touch(item)
    recompute_item_serviceable(item)
    return respond_object(serialize(item))


@bp.post("/rental-house/items/<iid>/complete-deaccession")
def complete_deaccession(iid):
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    item = DB.items.get(iid)
    if item is None:
        fail("ERR_NOT_FOUND", "Item not found")
    if item["status"] != "DEACCESSION_PENDING":
        fail("ERR_INVALID_STATE", "Item is not DEACCESSION_PENDING")
    for u in DB.units.values():
        if u["item_id"] == iid and u["status"] not in ("AWAITING_DISPOSAL", "DISPOSED"):
            fail("ERR_DEACCESSION_BLOCKED",
                 "Every unit must be AWAITING_DISPOSAL or DISPOSED")
    for u in DB.units.values():
        if u["item_id"] == iid and u["status"] == "AWAITING_DISPOSAL":
            u["status"] = "DISPOSED"
            touch(u)
    item["status"] = "DEACCESSIONED"
    touch(item)
    recompute_item_serviceable(item)
    return respond_object(serialize(item))


# ---------------------------------------------------------------------------
# Item units
# ---------------------------------------------------------------------------

@bp.post("/rental-house/items/<iid>/units")
def create_unit(iid):
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    item = DB.items.get(iid)
    if item is None:
        fail("ERR_NOT_FOUND", "Item not found")
    br = BodyReader()
    barcode = br.get_str("barcode")
    grade = br.get_enum("condition_grade", CONDITION_GRADES)
    acq_date = br.get_date("acquisition_date")
    acq_cost = br.get_int("acquisition_cost_cents")
    # Priority 8: item rentable, then barcode uniqueness
    if item["status"] != "ACTIVE":
        fail("ERR_ITEM_NOT_RENTABLE", "Item is not ACTIVE")
    if barcode is not None:
        for u in DB.units.values():
            if u["barcode"] == barcode:
                fail("ERR_DUPLICATE_BARCODE", "Barcode already exists house-wide")
    br.raise_if_errors()
    rec = new_record()
    rec.update({
        "item_id": iid,
        "barcode": barcode,
        "condition_grade": grade,
        "acquisition_date": acq_date.isoformat(),
        "acquisition_cost_cents": acq_cost,
        "status": "AVAILABLE",
        "last_returned_date": None,
        "_acquisition_date": acq_date,
    })
    DB.units[rec["id"]] = rec
    recompute_item_serviceable(item)
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/items/<iid>/units")
def list_units(iid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    item = DB.items.get(iid)
    if item is None:
        fail("ERR_NOT_FOUND", "Item not found")
    recs = [u for u in DB.units.values() if u["item_id"] == iid]
    for field in ("status", "condition_grade"):
        v = request.args.get(field)
        if v is not None:
            recs = [u for u in recs if u[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/units/<uid_>")
def get_unit(uid_):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.units.get(uid_)
    if rec is None:
        fail("ERR_NOT_FOUND", "Unit not found")
    return respond_object(serialize(rec))
