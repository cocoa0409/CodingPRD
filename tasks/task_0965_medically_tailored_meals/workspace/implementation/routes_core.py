"""Endpoints: logical clock, members, referrals, diet prescriptions,
menu items, menu cycles (incl. items and compliance)."""
from datetime import date

from flask import Blueprint, request

import db
from db import store
from util import (ApiError, ALL_ROLES, DIET_TYPES, authenticate, get_body,
                  f_str, f_int, f_list, f_enum, f_date, f_datetime,
                  envelope_ok, paginated, pub, not_found, invalid_request)
import domain
from domain import bump, member_view

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/mtm/_clock/set_current_utc")
def set_clock():
    authenticate(["ProgramAdmin"])
    body = get_body()
    raw, dt = f_datetime(body, "to_iso8601")
    db.set_clock(dt)
    domain.expiry_sweep()
    return envelope_ok({"current_utc": db.format_ts(dt)}, "object", 200)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@bp.post("/mtm/members")
def create_member():
    authenticate(["CareCoordinator"])
    body = get_body()
    full_name = f_str(body, "full_name")
    payer_type = f_enum(body, "payer_type", ["MEDICAID_WAIVER", "MEDICARE_ADVANTAGE"])
    payer_member_id = f_str(body, "payer_member_id")
    allergies = f_list(body, "allergies")
    diagnosis_codes = f_list(body, "diagnosis_codes", required=False)
    if diagnosis_codes is None:
        diagnosis_codes = []
    income = f_int(body, "income_fpl_percent")
    household = f_int(body, "household_size", min_val=1)
    ts = db.now_iso()
    m = {
        "id": db.new_id(), "full_name": full_name, "payer_type": payer_type,
        "payer_member_id": payer_member_id, "allergies": allergies,
        "diagnosis_codes": diagnosis_codes, "income_fpl_percent": income,
        "household_size": household, "status": "INTAKE",
        "oop_accumulator_cents": 0,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["members"][m["id"]] = m
    return envelope_ok(member_view(m), "object", 201)


@bp.get("/mtm/members")
def list_members():
    authenticate(ALL_ROLES)
    items = sorted(store["members"].values(), key=lambda r: r["created_at"])
    status_f = request.args.get("status")
    if status_f is not None:
        items = [m for m in items if m["status"] == status_f]
    return paginated([member_view(m) for m in items])


def _get_member(mid):
    m = store["members"].get(mid)
    if m is None:
        not_found("Member not found")
    return m


@bp.get("/mtm/members/<mid>")
def get_member(mid):
    authenticate(ALL_ROLES)
    return envelope_ok(member_view(_get_member(mid)), "object", 200)


@bp.post("/mtm/members/<mid>/status")
def member_status(mid):
    authenticate(["CareCoordinator", "ProgramAdmin"])
    body = get_body()
    target = f_enum(body, "target_status",
                    ["INTAKE", "ACTIVE", "SUSPENDED", "DISENROLLED"])
    m = _get_member(mid)
    if m["status"] == "DISENROLLED":
        raise ApiError("ERR_MEMBER_TERMINAL", 409,
                       "Member is DISENROLLED (terminal)")
    cur = m["status"]
    ok = ((cur == "INTAKE" and target == "ACTIVE")
          or (cur == "ACTIVE" and target == "SUSPENDED")
          or (cur == "SUSPENDED" and target == "ACTIVE")
          or (cur in ("ACTIVE", "SUSPENDED") and target == "DISENROLLED"))
    if not ok:
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Cannot transition member from {cur} to {target}")
    m["status"] = target
    bump(m)
    if target == "DISENROLLED":
        domain.disenroll_cascade(m)
    return envelope_ok(member_view(m), "object", 200)


@bp.get("/mtm/members/<mid>/summary")
def member_summary(mid):
    authenticate(ALL_ROLES)
    m = _get_member(mid)
    delivered_pct, confirmed_pct = domain.compute_adherence(mid)
    today = db.get_clock().date()
    covering = [a for a in store["reauthorizations"].values()
                if a["member_id"] == mid and a["status"] == "APPROVED"
                and a["start_date"] <= today.isoformat() <= a["end_date"]]
    covering.sort(key=lambda a: (a["end_date"], a["created_at"]))
    data = {
        "member_id": mid,
        "status": m["status"],
        "adherence_delivered_pct": delivered_pct,
        "adherence_confirmed_pct": confirmed_pct,
        "oop_accumulator_cents": m["oop_accumulator_cents"],
        "active_authorization_id": covering[0]["id"] if covering else None,
    }
    return envelope_ok(data, "object", 200)


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

@bp.post("/mtm/referrals")
def create_referral():
    uid, _ = authenticate(["ReferringProvider"])
    body = get_body()
    member_id = f_str(body, "member_id")
    diagnosis_codes = f_list(body, "diagnosis_codes")
    diet = f_enum(body, "referred_diet_type", DIET_TYPES)
    expires_at = f_date(body, "expires_at")
    if member_id not in store["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member_id does not exist")
    ts = db.now_iso()
    r = {
        "id": db.new_id(), "member_id": member_id, "provider_user_id": uid,
        "diagnosis_codes": diagnosis_codes, "referred_diet_type": diet,
        "expires_at": expires_at, "status": "SUBMITTED",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["referrals"][r["id"]] = r
    return envelope_ok(pub(r), "object", 201)


@bp.get("/mtm/referrals")
def list_referrals():
    authenticate(ALL_ROLES)
    items = sorted(store["referrals"].values(), key=lambda r: r["created_at"])
    member_f = request.args.get("member_id")
    status_f = request.args.get("status")
    if member_f is not None:
        items = [r for r in items if r["member_id"] == member_f]
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    return paginated([pub(r) for r in items])


@bp.get("/mtm/referrals/<rid>")
def get_referral(rid):
    authenticate(ALL_ROLES)
    r = store["referrals"].get(rid)
    if r is None:
        not_found("Referral not found")
    return envelope_ok(pub(r), "object", 200)


@bp.post("/mtm/referrals/<rid>/decision")
def referral_decision(rid):
    authenticate(["CareCoordinator"])
    body = get_body()
    decision = f_enum(body, "decision", ["TRIAGE", "ACCEPT", "REJECT"])
    r = store["referrals"].get(rid)
    if r is None:
        not_found("Referral not found")
    if decision == "TRIAGE":
        if r["status"] != "SUBMITTED":
            raise ApiError("ERR_REFERRAL_NOT_ACTIONABLE", 409,
                           "Referral must be SUBMITTED to triage")
        r["status"] = "TRIAGED"
    elif decision == "ACCEPT":
        if r["status"] != "TRIAGED":
            raise ApiError("ERR_REFERRAL_NOT_ACTIONABLE", 409,
                           "Referral must be TRIAGED to accept")
        if db.get_clock().date() > date.fromisoformat(r["expires_at"]):
            raise ApiError("ERR_REFERRAL_EXPIRED", 409,
                           "Logical clock date is past referral expires_at")
        r["status"] = "ACCEPTED"
    else:  # REJECT
        if r["status"] != "TRIAGED":
            raise ApiError("ERR_REFERRAL_NOT_ACTIONABLE", 409,
                           "Referral must be TRIAGED to reject")
        r["status"] = "REJECTED"
    bump(r)
    return envelope_ok(pub(r), "object", 200)


# ---------------------------------------------------------------------------
# Diet prescriptions
# ---------------------------------------------------------------------------

@bp.post("/mtm/diet-prescriptions")
def create_prescription():
    uid, _ = authenticate(["Dietitian"])
    body = get_body()
    member_id = f_str(body, "member_id")
    referral_id = f_str(body, "referral_id")
    diet_type = f_enum(body, "diet_type", DIET_TYPES)
    sodium = f_int(body, "daily_sodium_mg_max", min_val=0)
    potassium = f_int(body, "daily_potassium_mg_max", min_val=0)
    phosphorus = f_int(body, "daily_phosphorus_mg_max", min_val=0)
    carbs = f_int(body, "daily_carbs_g_max", min_val=0)
    protein = f_int(body, "daily_protein_g_min", min_val=0)
    excluded = f_list(body, "excluded_allergens")
    mpw = f_int(body, "meals_per_week", min_val=1)
    eff_from = f_date(body, "effective_from")
    eff_to = f_date(body, "effective_to")
    if eff_to < eff_from:
        invalid_request("effective_to must be on or after effective_from")
    if member_id not in store["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member_id does not exist")
    ref = store["referrals"].get(referral_id)
    if ref is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", 404, "referral_id does not exist")
    if ref["status"] != "ACCEPTED":
        raise ApiError("ERR_REFERRAL_NOT_ACTIONABLE", 409,
                       "Referral must be ACCEPTED for prescription create")
    # Temporal: closed-window overlap vs other DRAFT/ACTIVE rx of this member
    for p in store["prescriptions"].values():
        if (p["member_id"] == member_id and p["status"] in ("DRAFT", "ACTIVE")
                and eff_from <= p["effective_to"]
                and p["effective_from"] <= eff_to):
            raise ApiError("ERR_PRESCRIPTION_WINDOW_OVERLAP", 409,
                           "Effective window overlaps another DRAFT/ACTIVE prescription")
    if ref["member_id"] != member_id:
        raise ApiError("ERR_PRESCRIPTION_MEMBER_MISMATCH", 422,
                       "Referral belongs to a different member")
    ts = db.now_iso()
    p = {
        "id": db.new_id(), "member_id": member_id, "referral_id": referral_id,
        "supersedes_id": None, "dietitian_user_id": uid, "diet_type": diet_type,
        "daily_sodium_mg_max": sodium, "daily_potassium_mg_max": potassium,
        "daily_phosphorus_mg_max": phosphorus, "daily_carbs_g_max": carbs,
        "daily_protein_g_min": protein, "excluded_allergens": excluded,
        "meals_per_week": mpw, "effective_from": eff_from,
        "effective_to": eff_to, "status": "DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["prescriptions"][p["id"]] = p
    return envelope_ok(pub(p), "object", 201)


@bp.get("/mtm/diet-prescriptions")
def list_prescriptions():
    authenticate(ALL_ROLES)
    items = sorted(store["prescriptions"].values(), key=lambda r: r["created_at"])
    for param, field in (("member_id", "member_id"),
                         ("referral_id", "referral_id"),
                         ("supersedes_id", "supersedes_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p[field] == v]
    return paginated([pub(p) for p in items])


@bp.get("/mtm/diet-prescriptions/<pid>")
def get_prescription(pid):
    authenticate(ALL_ROLES)
    p = store["prescriptions"].get(pid)
    if p is None:
        not_found("Prescription not found")
    return envelope_ok(pub(p), "object", 200)


@bp.post("/mtm/diet-prescriptions/<pid>/activate")
def activate_prescription(pid):
    authenticate(["Dietitian"])
    body = get_body()
    emv = f_int(body, "expected_member_version")
    p = store["prescriptions"].get(pid)
    if p is None:
        not_found("Prescription not found")
    member = store["members"][p["member_id"]]
    # OCC before state preconditions (validation priority order)
    if emv != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION", 412,
                       "expected_member_version does not match current Member.version")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_PRESCRIPTION_NOT_DRAFT", 409,
                       "Prescription must be DRAFT to activate")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                       "Member must be ACTIVE to activate a prescription")
    ref = store["referrals"][p["referral_id"]]
    if ref["status"] != "ACCEPTED":
        raise ApiError("ERR_REFERRAL_NOT_ACTIONABLE", 409,
                       "Referral must be ACCEPTED to activate")
    priors = [q for q in store["prescriptions"].values()
              if q["member_id"] == member["id"] and q["status"] == "ACTIVE"
              and q["id"] != p["id"]]
    priors.sort(key=lambda q: q["created_at"])
    for q in priors:
        q["status"] = "SUPERSEDED"
        bump(q)
        p["supersedes_id"] = q["id"]
        for c in store["menu_cycles"].values():
            if (c["member_id"] == member["id"] and c["status"] == "PLANNED"
                    and c["prescription_id"] == q["id"]):
                c["prescription_id"] = p["id"]
                c["compliance_status"] = "UNCHECKED"
                bump(c)
    p["status"] = "ACTIVE"
    bump(p)
    ref["status"] = "CONSUMED"
    bump(ref)
    bump(member)
    return envelope_ok(pub(p), "object", 200)


@bp.post("/mtm/diet-prescriptions/<pid>/revoke")
def revoke_prescription(pid):
    authenticate(["Dietitian"])
    p = store["prescriptions"].get(pid)
    if p is None:
        not_found("Prescription not found")
    if p["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_PRESCRIPTION_NOT_DRAFT", 409,
                       "Prescription must be DRAFT or ACTIVE to revoke")
    was_active = p["status"] == "ACTIVE"
    p["status"] = "REVOKED"
    bump(p)
    if was_active:
        for c in store["menu_cycles"].values():
            if (c["member_id"] == p["member_id"] and c["status"] == "PLANNED"
                    and c["prescription_id"] == p["id"]):
                domain.cancel_cycle(c)
    return envelope_ok(pub(p), "object", 200)


# ---------------------------------------------------------------------------
# Menu items
# ---------------------------------------------------------------------------

@bp.post("/mtm/menu-items")
def create_menu_item():
    authenticate(["ProgramAdmin"])
    body = get_body()
    name = f_str(body, "name")
    sodium = f_int(body, "sodium_mg", min_val=0)
    potassium = f_int(body, "potassium_mg", min_val=0)
    phosphorus = f_int(body, "phosphorus_mg", min_val=0)
    carbs = f_int(body, "carbs_g", min_val=0)
    protein = f_int(body, "protein_g", min_val=0)
    allergens = f_list(body, "allergen_codes")
    base_cost = f_int(body, "base_cost_cents", min_val=0)
    ts = db.now_iso()
    item = {
        "id": db.new_id(), "name": name, "sodium_mg": sodium,
        "potassium_mg": potassium, "phosphorus_mg": phosphorus,
        "carbs_g": carbs, "protein_g": protein, "allergen_codes": allergens,
        "base_cost_cents": base_cost, "status": "ACTIVE",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["menu_items"][item["id"]] = item
    return envelope_ok(pub(item), "object", 201)


@bp.get("/mtm/menu-items")
def list_menu_items():
    authenticate(ALL_ROLES)
    items = sorted(store["menu_items"].values(), key=lambda r: r["created_at"])
    status_f = request.args.get("status")
    if status_f is not None:
        items = [i for i in items if i["status"] == status_f]
    return paginated([pub(i) for i in items])


def _get_menu_item(iid):
    item = store["menu_items"].get(iid)
    if item is None:
        not_found("Menu item not found")
    return item


@bp.get("/mtm/menu-items/<iid>")
def get_menu_item(iid):
    authenticate(ALL_ROLES)
    return envelope_ok(pub(_get_menu_item(iid)), "object", 200)


@bp.post("/mtm/menu-items/<iid>/retire")
def retire_menu_item(iid):
    authenticate(["ProgramAdmin"])
    item = _get_menu_item(iid)
    if item["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Menu item must be ACTIVE to retire")
    item["status"] = "RETIRED"
    bump(item)
    return envelope_ok(pub(item), "object", 200)


@bp.get("/mtm/menu-items/<iid>/menu-cycle-items")
def menu_item_cycle_items(iid):
    authenticate(ALL_ROLES)
    _get_menu_item(iid)
    lines = [li for li in store["cycle_items"].values()
             if li["menu_item_id"] == iid]
    lines.sort(key=lambda l: l["created_at"])
    return paginated([pub(li) for li in lines])


# ---------------------------------------------------------------------------
# Menu cycles
# ---------------------------------------------------------------------------

@bp.post("/mtm/menu-cycles")
def create_menu_cycle():
    authenticate(["Dietitian"])
    body = get_body()
    member_id = f_str(body, "member_id")
    prescription_id = f_str(body, "prescription_id")
    week_start = f_date(body, "week_start_date")
    if member_id not in store["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member_id does not exist")
    p = store["prescriptions"].get(prescription_id)
    if p is None:
        raise ApiError("ERR_PRESCRIPTION_NOT_FOUND", 404,
                       "prescription_id does not exist")
    if p["status"] != "ACTIVE" or p["member_id"] != member_id:
        raise ApiError("ERR_PRESCRIPTION_NOT_ACTIVE", 409,
                       "Pinned prescription must be ACTIVE and belong to the member")
    ts = db.now_iso()
    c = {
        "id": db.new_id(), "member_id": member_id,
        "prescription_id": prescription_id, "week_start_date": week_start,
        "status": "PLANNED", "compliance_status": "UNCHECKED", "meals_count": 0,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["menu_cycles"][c["id"]] = c
    return envelope_ok(pub(c), "object", 201)


@bp.get("/mtm/menu-cycles")
def list_menu_cycles():
    authenticate(ALL_ROLES)
    items = sorted(store["menu_cycles"].values(), key=lambda r: r["created_at"])
    for param, field in (("member_id", "member_id"),
                         ("prescription_id", "prescription_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    return paginated([pub(c) for c in items])


def _get_cycle(cid):
    c = store["menu_cycles"].get(cid)
    if c is None:
        not_found("Menu cycle not found")
    return c


@bp.get("/mtm/menu-cycles/<cid>")
def get_menu_cycle(cid):
    authenticate(ALL_ROLES)
    return envelope_ok(pub(_get_cycle(cid)), "object", 200)


@bp.get("/mtm/menu-cycles/<cid>/items")
def list_cycle_items(cid):
    authenticate(ALL_ROLES)
    _get_cycle(cid)
    lines = sorted(domain.cycle_lines(cid), key=lambda l: l["created_at"])
    return paginated([pub(li) for li in lines])


@bp.post("/mtm/menu-cycles/<cid>/items")
def add_cycle_item(cid):
    authenticate(["Dietitian"])
    body = get_body()
    menu_item_id = f_str(body, "menu_item_id")
    quantity = f_int(body, "quantity", min_val=1)
    c = _get_cycle(cid)
    item = store["menu_items"].get(menu_item_id)
    if item is None:
        raise ApiError("ERR_MENU_ITEM_NOT_FOUND", 404,
                       "menu_item_id does not exist")
    if c["status"] != "PLANNED":
        raise ApiError("ERR_MENU_CYCLE_NOT_PLANNED", 409,
                       "Menu cycle must be PLANNED to add items")
    if item["status"] == "RETIRED":
        raise ApiError("ERR_MENU_ITEM_RETIRED", 409,
                       "Cannot add a RETIRED menu item to a cycle")
    li = {
        "id": db.new_id(), "menu_cycle_id": cid, "menu_item_id": menu_item_id,
        "quantity": quantity, "created_at": db.now_iso(),
    }
    store["cycle_items"][li["id"]] = li
    domain.recompute_meals_count(c)
    bump(c)
    return envelope_ok(pub(li), "object", 201)


@bp.delete("/mtm/menu-cycles/<cid>/items/<itemId>")
def remove_cycle_item(cid, itemId):
    authenticate(["Dietitian"])
    c = _get_cycle(cid)
    li = store["cycle_items"].get(itemId)
    if li is None or li["menu_cycle_id"] != cid:
        not_found("Menu cycle item not found")
    if c["status"] != "PLANNED":
        raise ApiError("ERR_MENU_CYCLE_NOT_PLANNED", 409,
                       "Menu cycle must be PLANNED to remove items")
    del store["cycle_items"][itemId]
    domain.recompute_meals_count(c)
    bump(c)
    return "", 204


@bp.get("/mtm/menu-cycles/<cid>/compliance")
def cycle_compliance(cid):
    authenticate(ALL_ROLES)
    c = _get_cycle(cid)
    return envelope_ok(domain.compute_compliance(c), "object", 200)


@bp.post("/mtm/menu-cycles/<cid>/freeze")
def freeze_cycle(cid):
    authenticate(["Dietitian"])
    c = _get_cycle(cid)
    if c["status"] != "PLANNED":
        raise ApiError("ERR_MENU_CYCLE_NOT_PLANNED", 409,
                       "Menu cycle must be PLANNED to freeze")
    member = store["members"][c["member_id"]]
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                       "Member must be ACTIVE to freeze a cycle")
    p = store["prescriptions"][c["prescription_id"]]
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_NOT_ACTIVE", 409,
                       "Pinned prescription must be ACTIVE to freeze")
    comp = domain.compute_compliance(c)
    if not comp["allergen_ok"]:
        raise ApiError("ERR_ALLERGEN_VIOLATION", 422,
                       "A cycle item contains a blocked allergen")
    if not comp["nutrition_compliant"]:
        raise ApiError("ERR_NUTRITION_NON_COMPLIANT", 422,
                       "Weekly nutrient totals violate prescription gates")
    if comp["meals_count"] > p["meals_per_week"]:
        raise ApiError("ERR_MEAL_COUNT_EXCEEDED", 422,
                       "meals_count exceeds prescription meals_per_week")
    c["status"] = "FROZEN"
    c["compliance_status"] = "PASSED"
    bump(c)
    return envelope_ok(pub(c), "object", 200)


@bp.post("/mtm/menu-cycles/<cid>/unfreeze")
def unfreeze_cycle(cid):
    authenticate(["Dietitian"])
    c = _get_cycle(cid)
    if c["status"] != "FROZEN":
        raise ApiError("ERR_MENU_CYCLE_NOT_FROZEN", 409,
                       "Menu cycle must be FROZEN to unfreeze")
    open_ds = [d for d in store["deliveries"].values()
               if d["menu_cycle_id"] == cid
               and d["status"] in ("SCHEDULED", "OUT_FOR_DELIVERY")]
    if open_ds:
        raise ApiError("ERR_MENU_CYCLE_HAS_OPEN_DELIVERIES", 409,
                       "Unfreeze blocked while deliveries are open")
    c["status"] = "PLANNED"
    c["compliance_status"] = "UNCHECKED"
    bump(c)
    return envelope_ok(pub(c), "object", 200)


@bp.post("/mtm/menu-cycles/<cid>/cancel")
def cancel_cycle(cid):
    authenticate(["Dietitian"])
    c = _get_cycle(cid)
    if c["status"] not in ("PLANNED", "FROZEN"):
        raise ApiError("ERR_MENU_CYCLE_TERMINAL", 409,
                       "Menu cycle is FULFILLED or CANCELLED")
    domain.cancel_cycle(c)
    return envelope_ok(pub(c), "object", 200)
