"""CCRC / Life Plan Community API — entry point + all routes.

Storage is in-memory (db.py dicts), wiped on every fresh boot. No seeding.
Flat entity topology under the /ccrc prefix; routes are grouped by resource.
"""
from __future__ import annotations

import os

from flask import Flask, request

import db
from errors import APIError, err
from middleware import authenticate, require_roles
from response import error_response, ok_array, ok_object
from services import calculations as calc
from services import waitlist as wl
from services.common import (
    fk_lookup,
    get_json_body,
    is_int,
    new_record,
    optional_int,
    paginate,
    path_lookup,
    require_enum,
    require_int,
    require_present,
    require_str,
    serialize,
    touch,
)

app = Flask(__name__)

CARE_LEVELS = {"INDEPENDENT", "ASSISTED", "SKILLED"}
CONTRACT_TYPES = {"TYPE_A", "TYPE_B", "TYPE_C"}
REFUND_PLANS = {"DECLINING", "FIFTY_REFUNDABLE", "NINETY_REFUNDABLE"}
CARE_CHAIN = ["INDEPENDENT", "ASSISTED", "SKILLED"]

ALL_ROLES = ("FinanceOfficer", "AdmissionsDirector", "CareCoordinator", "Resident")


# ---- error plumbing ---------------------------------------------------------
@app.errorhandler(APIError)
def _handle_api_error(e: APIError):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(_e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, APIError):
        return _handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 400)


@app.before_request
def _auth_gate():
    # All endpoints require the two auth headers; per-endpoint role checks follow.
    authenticate()


def plan_of(residency):
    return db.contract_plans[residency["contract_plan_id"]]


# =============================================================================
# Communities
# =============================================================================
@app.post("/ccrc/communities")
def create_community():
    require_roles("FinanceOfficer")
    body = get_json_body()
    name = require_str(body, "name")
    discount = require_int(body, "actuarial_discount_rate_bps")
    target = optional_int(body, "target_funded_ratio_bps", 10000)
    reserve = optional_int(body, "reserve_assets_cents", 0)
    rec = new_record(
        {
            "name": name,
            "current_period_index": 0,
            "actuarial_discount_rate_bps": discount,
            "target_funded_ratio_bps": target,
            "reserve_assets_cents": reserve,
            "is_admissions_frozen": False,
        }
    )
    db.communities[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/communities")
def list_communities():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items, limit, offset, total = paginate(ordered(db.communities))
    return ok_array(items, limit, offset, total)


@app.get("/ccrc/communities/<cid>")
def get_community(cid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.communities, cid)
    return ok_object(serialize(rec))


@app.post("/ccrc/communities/<cid>/clock/advance")
def advance_clock(cid):
    require_roles("FinanceOfficer")
    community = path_lookup(db.communities, cid)
    body = get_json_body()
    by = require_present(body, "by_periods")
    if not is_int(by) or by < 1:
        err("ERR_INVALID_CLOCK_ADVANCE", "by_periods must be an integer >= 1")
    community["current_period_index"] += by
    touch(community)
    # Accrual: every ACTIVE residency in this community gains `by` occupied_months.
    for r in db.residencies.values():
        if r["community_id"] == cid and r["status"] == "ACTIVE":
            r["occupied_months"] += by
            touch(r)
    # Sweep: HELD bed reservations whose hold window has lapsed become EXPIRED.
    new_period = community["current_period_index"]
    for br in db.bed_reservations.values():
        if br["status"] != "HELD":
            continue
        res = db.residencies.get(br["residency_id"])
        if res is None or res["community_id"] != cid:
            continue
        if new_period > br["hold_expiry_period"]:
            br["status"] = "EXPIRED"
            touch(br)
    return ok_object(serialize(community))


# =============================================================================
# Contract Plans
# =============================================================================
@app.post("/ccrc/contract-plans")
def create_contract_plan():
    require_roles("FinanceOfficer")
    body = get_json_body()
    community_id = require_str(body, "community_id")
    fk_lookup(db.communities, community_id)
    name = require_str(body, "name")
    contract_type = require_enum(body, "contract_type", CONTRACT_TYPES)
    entrance_fee = require_int(body, "entrance_fee_cents")
    refund_plan = require_enum(body, "refund_plan", REFUND_PLANS)
    monthly_service = require_int(body, "monthly_service_fee_cents")
    second_person = require_int(body, "second_person_fee_cents")
    if entrance_fee <= 0:
        err("ERR_INVALID_REQUEST", "entrance_fee_cents must be > 0")
    if monthly_service <= 0:
        err("ERR_INVALID_REQUEST", "monthly_service_fee_cents must be > 0")
    if second_person < 0:
        err("ERR_INVALID_REQUEST", "second_person_fee_cents must be >= 0")
    rec = new_record(
        {
            "community_id": community_id,
            "name": name,
            "contract_type": contract_type,
            "entrance_fee_cents": entrance_fee,
            "refund_plan": refund_plan,
            "declining_monthly_bps": optional_int(body, "declining_monthly_bps", 200),
            "declining_nonrefundable_bps": optional_int(body, "declining_nonrefundable_bps", 400),
            "monthly_service_fee_cents": monthly_service,
            "second_person_fee_cents": second_person,
            "assisted_monthly_surcharge_cents": optional_int(body, "assisted_monthly_surcharge_cents", 0),
            "skilled_per_diem_cents": optional_int(body, "skilled_per_diem_cents", 0),
            "typeb_discounted_days": optional_int(body, "typeb_discounted_days", 0),
        }
    )
    db.contract_plans[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/contract-plans")
def list_contract_plans():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.contract_plans)
    cid = request.args.get("community_id")
    if cid is not None:
        items = [p for p in items if p["community_id"] == cid]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/contract-plans/<pid>")
def get_contract_plan(pid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.contract_plans, pid)
    return ok_object(serialize(rec))


# =============================================================================
# Units
# =============================================================================
@app.post("/ccrc/units")
def create_unit():
    require_roles("AdmissionsDirector")
    body = get_json_body()
    community_id = require_str(body, "community_id")
    fk_lookup(db.communities, community_id)
    unit_number = require_str(body, "unit_number")
    care_level = require_enum(body, "care_level", CARE_LEVELS)
    bed_capacity = optional_int(body, "bed_capacity", 1)
    rec = new_record(
        {
            "community_id": community_id,
            "unit_number": unit_number,
            "care_level": care_level,
            "bed_capacity": bed_capacity,
            "status": "AVAILABLE",
        }
    )
    db.units[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/units")
def list_units():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.units)
    cid = request.args.get("community_id")
    care_level = request.args.get("care_level")
    status = request.args.get("status")
    if cid is not None:
        items = [u for u in items if u["community_id"] == cid]
    if care_level is not None:
        items = [u for u in items if u["care_level"] == care_level]
    if status is not None:
        items = [u for u in items if u["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/units/<uid>")
def get_unit(uid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.units, uid)
    return ok_object(serialize(rec))


# =============================================================================
# Residents
# =============================================================================
@app.post("/ccrc/residents")
def create_resident():
    require_roles("AdmissionsDirector")
    body = get_json_body()
    community_id = require_str(body, "community_id")
    fk_lookup(db.communities, community_id)
    full_name = require_str(body, "full_name")
    dob = require_str(body, "date_of_birth")
    priority = optional_int(body, "priority_score", 0)
    rec = new_record(
        {
            "community_id": community_id,
            "full_name": full_name,
            "date_of_birth": dob,
            "priority_score": priority,
        }
    )
    db.residents[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/residents")
def list_residents():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.residents)
    cid = request.args.get("community_id")
    if cid is not None:
        items = [r for r in items if r["community_id"] == cid]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/residents/<resdid>")
def get_resident(resdid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.residents, resdid)
    return ok_object(serialize(rec))


# =============================================================================
# Residencies
# =============================================================================
@app.post("/ccrc/residencies")
def create_residency():
    require_roles("AdmissionsDirector")
    body = get_json_body()
    community_id = require_str(body, "community_id")
    primary_resident_id = require_str(body, "primary_resident_id")
    contract_plan_id = require_str(body, "contract_plan_id")
    fk_lookup(db.communities, community_id)
    fk_lookup(db.residents, primary_resident_id)
    fk_lookup(db.contract_plans, contract_plan_id)
    rec = new_record(
        {
            "community_id": community_id,
            "primary_resident_id": primary_resident_id,
            "contract_plan_id": contract_plan_id,
            "unit_id": None,
            "care_level": "INDEPENDENT",
            "entrance_fee_paid_cents": 0,
            "occupied_months": 0,
            "skilled_days_used": 0,
            "has_second_person": False,
            "refund_disbursed_cents": 0,
            "status": "DEPOSIT_HELD",
        }
    )
    db.residencies[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/residencies")
def list_residencies():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.residencies)
    for key in ("community_id", "status", "unit_id", "contract_plan_id", "primary_resident_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/residencies/<rid>")
def get_residency(rid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.residencies, rid)
    return ok_object(serialize(rec))


@app.post("/ccrc/residencies/<rid>/assign-unit")
def assign_unit(rid):
    require_roles("AdmissionsDirector")
    residency = path_lookup(db.residencies, rid)
    body = get_json_body()
    unit_id = require_str(body, "unit_id")
    unit = fk_lookup(db.units, unit_id)
    community = db.communities[residency["community_id"]]
    # State first (specific over generic), then frozen, then unit guards (PRD §3.2).
    if residency["status"] != "DEPOSIT_HELD":
        err("ERR_RESIDENCY_NOT_DEPOSIT_HELD", "Residency is not in DEPOSIT_HELD")
    if community["is_admissions_frozen"]:
        err("ERR_ADMISSIONS_FROZEN", "Admissions are frozen")
    if unit["status"] != "AVAILABLE":
        err("ERR_UNIT_NOT_AVAILABLE", "Target unit is not AVAILABLE")
    if unit["care_level"] != "INDEPENDENT":
        err("ERR_UNIT_CARE_LEVEL_MISMATCH", "Target unit is not INDEPENDENT")
    residency["unit_id"] = unit_id
    residency["status"] = "RESERVED"
    touch(residency)
    unit["status"] = "OCCUPIED"
    touch(unit)
    return ok_object(serialize(residency))


@app.post("/ccrc/residencies/<rid>/activate")
def activate_residency(rid):
    require_roles("AdmissionsDirector")
    residency = path_lookup(db.residencies, rid)
    body = get_json_body()
    expected = require_present(body, "expected_residency_version")
    if not is_int(expected):
        err("ERR_INVALID_REQUEST", "expected_residency_version must be an integer")
    # OCC guard runs BEFORE any state-machine precondition (PRD §2.8).
    if expected != residency["version"]:
        err("ERR_STALE_VERSION", "Residency version mismatch")
    if residency["status"] != "RESERVED":
        err("ERR_RESIDENCY_NOT_RESERVED", "Residency is not RESERVED")
    if not residency["unit_id"]:
        err("ERR_NO_UNIT_ASSIGNED", "No unit assigned to residency")
    community = db.communities[residency["community_id"]]
    if community["is_admissions_frozen"]:
        err("ERR_ADMISSIONS_FROZEN", "Admissions are frozen")
    plan = plan_of(residency)
    residency["entrance_fee_paid_cents"] = plan["entrance_fee_cents"]
    residency["occupied_months"] = 0
    residency["skilled_days_used"] = 0
    residency["care_level"] = "INDEPENDENT"
    residency["status"] = "ACTIVE"
    touch(residency)
    community["reserve_assets_cents"] += residency["entrance_fee_paid_cents"]
    touch(community)
    return ok_object(serialize(residency))


@app.post("/ccrc/residencies/<rid>/terminate")
def terminate_residency(rid):
    require_roles("AdmissionsDirector")
    residency = path_lookup(db.residencies, rid)
    body = get_json_body()
    reason = require_present(body, "reason")
    expected = require_present(body, "expected_residency_version")
    if not is_int(expected):
        err("ERR_INVALID_REQUEST", "expected_residency_version must be an integer")
    # OCC guard first (PRD §2.8).
    if expected != residency["version"]:
        err("ERR_STALE_VERSION", "Residency version mismatch")
    if residency["status"] != "ACTIVE":
        err("ERR_RESIDENCY_NOT_ACTIVE", "Residency is not ACTIVE")
    if reason not in ("VOLUNTARY", "DEATH"):
        err("ERR_INVALID_REQUEST", "reason must be VOLUNTARY or DEATH")

    community = db.communities[residency["community_id"]]
    plan = plan_of(residency)

    # Cascade hop 1: free the assigned independent unit.
    if residency["unit_id"]:
        unit = db.units.get(residency["unit_id"])
        if unit is not None:
            unit["status"] = "AVAILABLE"
            touch(unit)
    # Cascade: ACTIVE second persons -> REMOVED; clear has_second_person.
    for sp in db.second_persons.values():
        if sp["residency_id"] == rid and sp["status"] == "ACTIVE":
            sp["status"] = "REMOVED"
            touch(sp)
    if residency["has_second_person"]:
        residency["has_second_person"] = False
    # Cascade hop 2-3: HELD/OCCUPIED bed reservations -> RELEASED; free OCCUPIED units.
    for br in db.bed_reservations.values():
        if br["residency_id"] == rid and br["status"] in ("HELD", "OCCUPIED"):
            was_occupied = br["status"] == "OCCUPIED"
            br["status"] = "RELEASED"
            touch(br)
            if was_occupied:
                skilled_unit = db.units.get(br["unit_id"])
                if skilled_unit is not None:
                    skilled_unit["status"] = "AVAILABLE"
                    touch(skilled_unit)

    refundable = calc.entrance_fee_refund(
        plan, residency["entrance_fee_paid_cents"], residency["occupied_months"], reason
    )
    disb = new_record(
        {
            "residency_id": rid,
            "gross_entrance_fee_cents": residency["entrance_fee_paid_cents"],
            "refundable_cents": refundable,
            "termination_reason": reason,
            "settlement_period_index": 0,
            "status": "PENDING",
        }
    )
    db.refund_disbursements[disb["id"]] = disb

    residency["refund_disbursed_cents"] = refundable
    residency["status"] = "TERMINATED_VOLUNTARY" if reason == "VOLUNTARY" else "TERMINATED_DEATH"
    touch(residency)
    community["reserve_assets_cents"] -= refundable
    touch(community)
    return ok_object(serialize(residency))


# =============================================================================
# Second Persons
# =============================================================================
@app.post("/ccrc/residencies/<rid>/second-persons")
def add_second_person(rid):
    require_roles("AdmissionsDirector")
    residency = path_lookup(db.residencies, rid)
    body = get_json_body()
    full_name = require_str(body, "full_name")
    dob = require_str(body, "date_of_birth")
    existing_active = any(
        sp["residency_id"] == rid and sp["status"] == "ACTIVE"
        for sp in db.second_persons.values()
    )
    if existing_active:
        err("ERR_SECOND_PERSON_EXISTS", "Residency already has an ACTIVE second person")
    rec = new_record(
        {
            "residency_id": rid,
            "full_name": full_name,
            "date_of_birth": dob,
            "status": "ACTIVE",
        }
    )
    db.second_persons[rec["id"]] = rec
    residency["has_second_person"] = True
    touch(residency)
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/second-persons")
def list_second_persons():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.second_persons)
    rid = request.args.get("residency_id")
    if rid is not None:
        items = [s for s in items if s["residency_id"] == rid]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/second-persons/<spid>")
def get_second_person(spid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.second_persons, spid)
    return ok_object(serialize(rec))


@app.post("/ccrc/second-persons/<spid>/remove")
def remove_second_person(spid):
    require_roles("AdmissionsDirector")
    sp = path_lookup(db.second_persons, spid)
    if sp["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Second person is not ACTIVE")
    sp["status"] = "REMOVED"
    touch(sp)
    residency = db.residencies.get(sp["residency_id"])
    if residency is not None:
        residency["has_second_person"] = False
        touch(residency)
    return ok_object(serialize(sp))


# =============================================================================
# Waitlist
# =============================================================================
@app.post("/ccrc/waitlist-entries")
def create_waitlist_entry():
    require_roles("AdmissionsDirector")
    body = get_json_body()
    community_id = require_str(body, "community_id")
    residency_id = require_str(body, "residency_id")
    fk_lookup(db.communities, community_id)
    residency = fk_lookup(db.residencies, residency_id)
    target_care_level = require_enum(body, "target_care_level", CARE_LEVELS)
    if residency["status"] != "DEPOSIT_HELD":
        err("ERR_RESIDENCY_NOT_DEPOSIT_HELD", "Residency is not in DEPOSIT_HELD")
    dup = any(
        w["residency_id"] == residency_id and w["status"] == "PENDING"
        for w in db.waitlist_entries.values()
    )
    if dup:
        err("ERR_DUPLICATE_WAITLIST_ENTRY", "Residency already has a PENDING waitlist entry")
    community = db.communities[community_id]
    resident = db.residents[residency["primary_resident_id"]]
    rec = new_record(
        {
            "community_id": community_id,
            "residency_id": residency_id,
            "target_care_level": target_care_level,
            "priority_score": resident["priority_score"],
            "enqueued_period_index": community["current_period_index"],
            "rank": 0,
            "status": "PENDING",
        }
    )
    db.waitlist_entries[rec["id"]] = rec
    wl.recompute_ranks(community_id, target_care_level)
    residency["status"] = "WAITLISTED"
    touch(residency)
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/waitlist-entries")
def list_waitlist_entries():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.waitlist_entries)
    for key in ("community_id", "residency_id", "target_care_level", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w.get(key) == val]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/waitlist-entries/<wid>")
def get_waitlist_entry(wid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.waitlist_entries, wid)
    return ok_object(serialize(rec))


@app.post("/ccrc/waitlist-entries/<wid>/offer")
def offer_waitlist_entry(wid):
    require_roles("AdmissionsDirector")
    entry = path_lookup(db.waitlist_entries, wid)
    if entry["status"] != "PENDING":
        err("ERR_WAITLIST_ENTRY_NOT_PENDING", "Waitlist entry is not PENDING")
    if entry["rank"] != 1:
        err("ERR_WAITLIST_NOT_HEAD", "Waitlist entry is not the head of its queue")
    entry["status"] = "OFFERED"
    touch(entry)
    return ok_object(serialize(entry))


@app.post("/ccrc/waitlist-entries/<wid>/place")
def place_waitlist_entry(wid):
    require_roles("AdmissionsDirector")
    entry = path_lookup(db.waitlist_entries, wid)
    body = get_json_body()
    unit_id = require_str(body, "unit_id")
    unit = fk_lookup(db.units, unit_id)
    if entry["status"] not in ("OFFERED", "PENDING"):
        err("ERR_WAITLIST_ENTRY_NOT_PLACEABLE", "Waitlist entry is not OFFERED or PENDING")
    # Head = rank 1 among PENDING entries (scaffold precondition). A PENDING entry
    # carries an up-to-date rank (recomputed on create/place/withdraw); an OFFERED
    # entry retains the rank it held when offered (offer requires it be head).
    if entry["rank"] != 1:
        err("ERR_WAITLIST_NOT_HEAD", "Waitlist entry is not the head of its queue")
    if unit["status"] != "AVAILABLE" or unit["care_level"] != "INDEPENDENT":
        err("ERR_UNIT_NOT_AVAILABLE", "Target unit is not AVAILABLE/INDEPENDENT")
    residency = db.residencies[entry["residency_id"]]
    if residency["status"] != "WAITLISTED":
        err("ERR_RESIDENCY_NOT_WAITLISTED", "Residency is not WAITLISTED")
    community = db.communities[entry["community_id"]]
    if community["is_admissions_frozen"]:
        err("ERR_ADMISSIONS_FROZEN", "Admissions are frozen")
    residency["unit_id"] = unit_id
    residency["status"] = "RESERVED"
    touch(residency)
    unit["status"] = "OCCUPIED"
    touch(unit)
    entry["status"] = "PLACED"
    touch(entry)
    wl.recompute_ranks(entry["community_id"], entry["target_care_level"])
    return ok_object(serialize(entry))


@app.post("/ccrc/waitlist-entries/<wid>/withdraw")
def withdraw_waitlist_entry(wid):
    require_roles("AdmissionsDirector")
    entry = path_lookup(db.waitlist_entries, wid)
    if entry["status"] not in ("PENDING", "OFFERED"):
        err("ERR_WAITLIST_ENTRY_NOT_WITHDRAWABLE", "Waitlist entry is not PENDING or OFFERED")
    entry["status"] = "WITHDRAWN"
    touch(entry)
    residency = db.residencies.get(entry["residency_id"])
    if residency is not None:
        residency["status"] = "DEPOSIT_HELD"
        touch(residency)
    wl.recompute_ranks(entry["community_id"], entry["target_care_level"])
    return ok_object(serialize(entry))


# =============================================================================
# Care Transitions
# =============================================================================
@app.post("/ccrc/care-transitions")
def propose_care_transition():
    require_roles("CareCoordinator")
    body = get_json_body()
    residency_id = require_str(body, "residency_id")
    residency = fk_lookup(db.residencies, residency_id)
    to_level = require_enum(body, "to_level", CARE_LEVELS)
    if residency["status"] != "ACTIVE":
        err("ERR_RESIDENCY_NOT_ACTIVE", "Residency is not ACTIVE")
    rec = new_record(
        {
            "residency_id": residency_id,
            "from_level": residency["care_level"],
            "to_level": to_level,
            "effective_period_index": 0,
            "status": "PROPOSED",
        }
    )
    db.care_transitions[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/care-transitions")
def list_care_transitions():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.care_transitions)
    for key in ("residency_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/care-transitions/<ctid>")
def get_care_transition(ctid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.care_transitions, ctid)
    return ok_object(serialize(rec))


def _one_step(from_level, to_level):
    """to_level is exactly one step from from_level along the chain, either way."""
    fi = CARE_CHAIN.index(from_level)
    ti = CARE_CHAIN.index(to_level)
    return abs(fi - ti) == 1


@app.post("/ccrc/care-transitions/<ctid>/apply")
def apply_care_transition(ctid):
    require_roles("CareCoordinator")
    ct = path_lookup(db.care_transitions, ctid)
    if ct["status"] != "PROPOSED":
        err("ERR_CARE_TRANSITION_NOT_PROPOSED", "Care transition is not PROPOSED")
    residency = db.residencies[ct["residency_id"]]
    if residency["status"] != "ACTIVE":
        err("ERR_RESIDENCY_NOT_ACTIVE", "Residency is not ACTIVE")
    if not _one_step(ct["from_level"], ct["to_level"]):
        err("ERR_INVALID_CARE_STEP", "to_level must be exactly one continuum step")
    if ct["to_level"] == "SKILLED":
        has_occupied_bed = any(
            br["residency_id"] == residency["id"] and br["status"] == "OCCUPIED"
            for br in db.bed_reservations.values()
        )
        if not has_occupied_bed:
            err("ERR_NO_BED_OCCUPIED", "No OCCUPIED bed reservation for this residency")
    community = db.communities[residency["community_id"]]
    residency["care_level"] = ct["to_level"]
    touch(residency)
    ct["effective_period_index"] = community["current_period_index"]
    ct["status"] = "APPLIED"
    touch(ct)
    return ok_object(serialize(ct))


@app.post("/ccrc/care-transitions/<ctid>/revert")
def revert_care_transition(ctid):
    require_roles("CareCoordinator")
    ct = path_lookup(db.care_transitions, ctid)
    if ct["status"] != "PROPOSED":
        err("ERR_CARE_TRANSITION_NOT_PROPOSED", "Care transition is not PROPOSED")
    ct["status"] = "REVERTED"
    touch(ct)
    return ok_object(serialize(ct))


# =============================================================================
# Bed Reservations
# =============================================================================
@app.post("/ccrc/bed-reservations")
def create_bed_reservation():
    require_roles("CareCoordinator")
    body = get_json_body()
    residency_id = require_str(body, "residency_id")
    unit_id = require_str(body, "unit_id")
    residency = fk_lookup(db.residencies, residency_id)
    unit = fk_lookup(db.units, unit_id)
    hold_expiry = require_int(body, "hold_expiry_period")
    if unit["care_level"] != "SKILLED":
        err("ERR_UNIT_NOT_SKILLED", "Target unit is not SKILLED")
    community = db.communities[residency["community_id"]]
    current = community["current_period_index"]
    if hold_expiry <= current:
        err("ERR_INVALID_HOLD_WINDOW", "hold_expiry_period must be > current period")
    committed = sum(
        1
        for br in db.bed_reservations.values()
        if br["unit_id"] == unit_id and br["status"] in ("HELD", "OCCUPIED")
    )
    if committed >= unit["bed_capacity"]:
        err("ERR_BED_CAPACITY_EXCEEDED", "Unit committed reservations equal bed_capacity")
    rec = new_record(
        {
            "residency_id": residency_id,
            "unit_id": unit_id,
            "hold_start_period": current,
            "hold_expiry_period": hold_expiry,
            "occupied_start_period": 0,
            "status": "HELD",
        }
    )
    db.bed_reservations[rec["id"]] = rec
    touch(residency)  # holding a bed bumps the parent residency's version
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/bed-reservations")
def list_bed_reservations():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.bed_reservations)
    for key in ("residency_id", "unit_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/bed-reservations/<brid>")
def get_bed_reservation(brid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.bed_reservations, brid)
    return ok_object(serialize(rec))


@app.post("/ccrc/bed-reservations/<brid>/occupy")
def occupy_bed_reservation(brid):
    require_roles("CareCoordinator")
    br = path_lookup(db.bed_reservations, brid)
    if br["status"] != "HELD":
        err("ERR_BED_RESERVATION_NOT_HELD", "Bed reservation is not HELD")
    residency = db.residencies[br["residency_id"]]
    community = db.communities[residency["community_id"]]
    if community["current_period_index"] > br["hold_expiry_period"]:
        err("ERR_BED_RESERVATION_EXPIRED", "Bed reservation hold window has lapsed")
    if residency["status"] != "ACTIVE":
        err("ERR_RESIDENCY_NOT_ACTIVE", "Residency is not ACTIVE")
    br["occupied_start_period"] = community["current_period_index"]
    br["status"] = "OCCUPIED"
    touch(br)
    unit = db.units[br["unit_id"]]
    unit["status"] = "OCCUPIED"
    touch(unit)
    return ok_object(serialize(br))


@app.post("/ccrc/bed-reservations/<brid>/release")
def release_bed_reservation(brid):
    require_roles("CareCoordinator")
    br = path_lookup(db.bed_reservations, brid)
    if br["status"] == "HELD":
        br["status"] = "RELEASED"
        touch(br)
        return ok_object(serialize(br))
    if br["status"] == "OCCUPIED":
        br["status"] = "RELEASED"
        touch(br)
        unit = db.units.get(br["unit_id"])
        if unit is not None:
            unit["status"] = "AVAILABLE"
            touch(unit)
        return ok_object(serialize(br))
    err("ERR_BED_RESERVATION_NOT_RELEASABLE", "Bed reservation is not HELD or OCCUPIED")


# =============================================================================
# Monthly Invoices
# =============================================================================
@app.post("/ccrc/residencies/<rid>/invoices")
def issue_invoice(rid):
    require_roles("FinanceOfficer")
    residency = path_lookup(db.residencies, rid)
    body = get_json_body()
    skilled_days = 0
    if "skilled_days_in_period" in body and body["skilled_days_in_period"] is not None:
        sd = body["skilled_days_in_period"]
        if not is_int(sd) or sd < 0 or sd > 30:
            err("ERR_INVALID_REQUEST", "skilled_days_in_period must be an integer in 0..30")
        skilled_days = sd
    if residency["status"] != "ACTIVE":
        err("ERR_RESIDENCY_NOT_ACTIVE", "Residency is not ACTIVE")
    plan = plan_of(residency)
    community = db.communities[residency["community_id"]]
    base, second, surcharge, total = calc.monthly_invoice_total(plan, residency, skilled_days)
    rec = new_record(
        {
            "residency_id": rid,
            "period_index": community["current_period_index"],
            "base_service_fee_cents": base,
            "second_person_fee_cents": second,
            "care_surcharge_cents": surcharge,
            "total_cents": total,
            "status": "ISSUED",
        }
    )
    db.monthly_invoices[rec["id"]] = rec
    # Post-compute side effect: only SKILLED residencies accrue skilled_days_used.
    if residency["care_level"] == "SKILLED":
        residency["skilled_days_used"] += skilled_days
        touch(residency)
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/invoices")
def list_invoices():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.monthly_invoices)
    rid = request.args.get("residency_id")
    if rid is not None:
        items = [i for i in items if i["residency_id"] == rid]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/invoices/<invid>")
def get_invoice(invid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.monthly_invoices, invid)
    return ok_object(serialize(rec))


# =============================================================================
# Refund Disbursements
# =============================================================================
@app.get("/ccrc/refund-disbursements")
def list_refunds():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.refund_disbursements)
    rid = request.args.get("residency_id")
    if rid is not None:
        items = [d for d in items if d["residency_id"] == rid]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/refund-disbursements/<dsbid>")
def get_refund(dsbid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.refund_disbursements, dsbid)
    return ok_object(serialize(rec))


@app.post("/ccrc/refund-disbursements/<dsbid>/settle")
def settle_refund(dsbid):
    require_roles("FinanceOfficer")
    disb = path_lookup(db.refund_disbursements, dsbid)
    if disb["status"] != "PENDING":
        err("ERR_INVALID_STATE", "Refund disbursement is not PENDING")
    residency = db.residencies[disb["residency_id"]]
    community = db.communities[residency["community_id"]]
    disb["settlement_period_index"] = community["current_period_index"]
    disb["status"] = "SETTLED"
    touch(disb)
    return ok_object(serialize(disb))


# =============================================================================
# Actuarial Reserve Disclosure
# =============================================================================
@app.post("/ccrc/communities/<cid>/reserve-reports")
def reserve_report(cid):
    require_roles("FinanceOfficer")
    community = path_lookup(db.communities, cid)
    from services.common import ordered
    active = [
        r
        for r in ordered(db.residencies)
        if r["community_id"] == cid and r["status"] == "ACTIVE"
    ]
    report = calc.actuarial_reserve_disclosure(community, active, plan_of)
    # Side effect: freeze admissions when funded ratio falls below half the target.
    threshold = community["target_funded_ratio_bps"] // 2
    if report["funded_ratio_bps"] < threshold:
        community["is_admissions_frozen"] = True
        touch(community)
    return ok_object(report, 201)


# =============================================================================
# Resident Council
# =============================================================================
@app.post("/ccrc/councils")
def create_council():
    require_roles("FinanceOfficer")
    body = get_json_body()
    community_id = require_str(body, "community_id")
    fk_lookup(db.communities, community_id)
    name = require_str(body, "name")
    quorum = optional_int(body, "quorum_pct_bps", 5000)
    rec = new_record(
        {
            "community_id": community_id,
            "name": name,
            "quorum_pct_bps": quorum,
        }
    )
    db.councils[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/councils")
def list_councils():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.councils)
    cid = request.args.get("community_id")
    if cid is not None:
        items = [c for c in items if c["community_id"] == cid]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/councils/<coid>")
def get_council(coid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.councils, coid)
    return ok_object(serialize(rec))


@app.post("/ccrc/council-resolutions")
def create_resolution():
    require_roles("FinanceOfficer")
    body = get_json_body()
    council_id = require_str(body, "council_id")
    fk_lookup(db.councils, council_id)
    title = require_str(body, "title")
    rec = new_record(
        {
            "council_id": council_id,
            "title": title,
            "yes_votes": 0,
            "no_votes": 0,
            "eligible_voter_count": 0,
            "status": "DRAFT",
        }
    )
    db.council_resolutions[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/ccrc/council-resolutions")
def list_resolutions():
    require_roles(*ALL_ROLES)
    from services.common import ordered
    items = ordered(db.council_resolutions)
    coid = request.args.get("council_id")
    if coid is not None:
        items = [r for r in items if r["council_id"] == coid]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@app.get("/ccrc/council-resolutions/<resid>")
def get_resolution(resid):
    require_roles(*ALL_ROLES)
    rec = path_lookup(db.council_resolutions, resid)
    return ok_object(serialize(rec))


@app.post("/ccrc/council-resolutions/<resid>/open")
def open_resolution(resid):
    require_roles("FinanceOfficer")
    res = path_lookup(db.council_resolutions, resid)
    if res["status"] != "DRAFT":
        err("ERR_RESOLUTION_NOT_DRAFT", "Resolution is not DRAFT")
    council = db.councils[res["council_id"]]
    community_id = council["community_id"]
    eligible = sum(
        1
        for r in db.residencies.values()
        if r["community_id"] == community_id and r["status"] == "ACTIVE"
    )
    res["eligible_voter_count"] = eligible
    res["status"] = "OPEN"
    touch(res)
    return ok_object(serialize(res))


@app.post("/ccrc/council-resolutions/<resid>/votes")
def cast_vote(resid):
    require_roles("Resident")
    res = path_lookup(db.council_resolutions, resid)
    body = get_json_body()
    residency_id = require_str(body, "residency_id")
    residency = fk_lookup(db.residencies, residency_id)
    choice = require_present(body, "choice")
    if choice not in ("YES", "NO"):
        err("ERR_INVALID_REQUEST", "choice must be YES or NO")
    if res["status"] != "OPEN":
        err("ERR_RESOLUTION_NOT_OPEN", "Resolution is not OPEN")
    if residency["status"] != "ACTIVE":
        err("ERR_DUPLICATE_VOTE", "Residency is not ACTIVE")
    voters = db.resolution_votes.setdefault(resid, set())
    if residency_id in voters:
        err("ERR_DUPLICATE_VOTE", "Residency already voted on this resolution")
    voters.add(residency_id)
    if choice == "YES":
        res["yes_votes"] += 1
    else:
        res["no_votes"] += 1
    touch(res)
    return ok_object(serialize(res), 201)


@app.post("/ccrc/council-resolutions/<resid>/close")
def close_resolution(resid):
    require_roles("FinanceOfficer")
    res = path_lookup(db.council_resolutions, resid)
    if res["status"] != "OPEN":
        err("ERR_RESOLUTION_NOT_OPEN", "Resolution is not OPEN")
    council = db.councils[res["council_id"]]
    cast = res["yes_votes"] + res["no_votes"]
    if cast * 10000 < res["eligible_voter_count"] * council["quorum_pct_bps"]:
        err("ERR_QUORUM_NOT_MET", "Quorum not met")
    if res["yes_votes"] > res["no_votes"]:
        res["status"] = "PASSED"
    else:
        res["status"] = "FAILED"
    touch(res)
    return ok_object(serialize(res))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
