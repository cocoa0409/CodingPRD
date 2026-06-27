"""Beekeeping & Pollination Service API — entry point and all routes.

In-memory only: all state lives in db.store (Python dicts keyed by id) and is
wiped on every process restart. No seeding, no preloaded entities, no disk I/O.
"""
import os

from flask import Flask, request

import errors
import response
import calculations as calc
from db import store
from middleware import require_roles
from serialize import public, public_list
from common import (
    stamp_create, touch, must_get, require_fk, optional_fk, get_body, paginate,
    require_str, require_number, optional_number, require_int, optional_int,
    require_bool, require_enum, optional_enum, require_dt, parse_iso,
    iso_from_dt, add_days, round2, round_cents, D,
)

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return response.error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(_e):
    return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(_e):
    return response.error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return response.error_response(err.error_id, err.message, err.http_status)
    return response.error_response("ERR_INVALID_REQUEST", str(err), 422)


# ===========================================================================
# Enums
# ===========================================================================
TREATMENT_PRODUCTS = {"APIVAR", "FORMIC_PRO", "OXALIC_ACID"}
WITHDRAWAL_DAYS = {"APIVAR": 14, "FORMIC_PRO": 0, "OXALIC_ACID": 0}
FLORAL_SOURCES = {"WILDFLOWER", "ALMOND", "CLOVER", "ORANGE_BLOSSOM"}
PRODUCT_TYPES = {"QUEEN", "NUC"}
FEED_TYPES = {"SYRUP_1_1", "SYRUP_2_1", "FONDANT", "POLLEN_PATTY"}
REQUEEN_REASONS = {"AGE", "FAILING", "QUEENLESS", "GENETICS"}


# ===========================================================================
# Ownership (PRD §2.1) — ApiaryManager X-User-ID must equal the owning apiary_id
# ===========================================================================
def assert_owns_apiary(role, user_id, apiary_id):
    """For an ApiaryManager mutation, X-User-ID must equal the owning apiary_id."""
    if role == "ApiaryManager" and user_id != apiary_id:
        raise errors.not_resource_owner()


def hive_apiary_id(hive):
    return hive["apiary_id"]


def lot_apiary_id(lot):
    return lot["apiary_id"]


# ===========================================================================
# Serialization views (computed fields surfaced)
# ===========================================================================
def hive_view(hive):
    return public(hive)


# ===========================================================================
# Logical-clock-driven re-evaluation (PRD §2.5)
# ===========================================================================
def reevaluate_registrations():
    """Any ACTIVE StateRegistration whose expiry_date <= clock transitions
    ACTIVE -> EXPIRED, setting Apiary.registration_status = EXPIRED."""
    for reg in store.registrations.values():
        if reg["status"] == "ACTIVE" and reg["_expiry_dt"] <= store.clock:
            reg["status"] = "EXPIRED"
            touch(reg)
            apiary = store.apiaries.get(reg["apiary_id"])
            if apiary is not None:
                apiary["registration_status"] = "EXPIRED"
                touch(apiary)


# ===========================================================================
# Computed roll-ups
# ===========================================================================
def recompute_active_colony_count(apiary):
    count = sum(1 for h in store.hives.values()
                if h["apiary_id"] == apiary["id"] and h["health_status"] != "DEADOUT")
    apiary["active_colony_count"] = count
    return count


def recompute_harvest_blocked_until(hive):
    """Set Hive.harvest_blocked_until = max harvest_clear_at across ACTIVE treatments,
    or None if none remain."""
    active = [t for t in store.treatments.values()
              if t["hive_id"] == hive["id"] and t["status"] == "ACTIVE"]
    if not active:
        hive["harvest_blocked_until"] = None
        hive["_harvest_blocked_dt"] = None
        return
    max_dt = max(t["_harvest_clear_dt"] for t in active)
    hive["harvest_blocked_until"] = iso_from_dt(max_dt)
    hive["_harvest_blocked_dt"] = max_dt


def hive_is_blocked(hive):
    dt = hive.get("_harvest_blocked_dt")
    return dt is not None and dt > store.clock


def recompute_provisional_yield(lot):
    total_frames = sum(h["frames_pulled"] for h in store.harvests.values()
                       if h["lot_id"] == lot["id"] and h["status"] == "RECORDED")
    lot["provisional_yield_kg"] = calc.provisional_yield(total_frames)


def recompute_gross_weight(lot):
    total = sum(D(h["weight_kg"]) for h in store.harvests.values()
                if h["lot_id"] == lot["id"] and h["status"] == "RECORDED")
    lot["gross_weight_kg"] = round2(total) if total != 0 else 0


def recompute_contract_placed(contract):
    """Count CONTRACT_GRADE hives currently in CONFIRMED placements."""
    count = sum(1 for p in store.placements.values()
                if p["contract_id"] == contract["id"]
                and p["status"] == "CONFIRMED" and p["grade"] == "CONTRACT_GRADE")
    contract["placed_strong_hives"] = count
    return count


def recompute_payout(contract):
    confirmed = [p for p in store.placements.values()
                 if p["contract_id"] == contract["id"] and p["status"] == "CONFIRMED"]
    contract["projected_payout_cents"] = calc.pollination_payout(
        confirmed, contract["base_rate_cents"],
        contract["required_strong_hives"], contract["placed_strong_hives"])


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    require_roles({"PlatformAdmin"})
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise errors.invalid_request("Missing required field 'to_iso8601'.")
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        raise errors.invalid_request("Field 'to_iso8601' is not a valid ISO 8601 datetime.")
    with store.lock:
        store.clock = dt
        reevaluate_registrations()
    return response.object_response({"current_utc": iso_from_dt(store.clock)})


@app.route("/_clock/now", methods=["GET"])
def clock_now():
    require_roles({"PlatformAdmin", "ApiaryManager", "StateApiarist", "ContractCoordinator"})
    return response.object_response({"current_utc": iso_from_dt(store.clock)})


# ===========================================================================
# Apiary
# ===========================================================================
@app.route("/apiaries", methods=["POST"])
def create_apiary():
    require_roles({"PlatformAdmin", "ApiaryManager"})
    body = get_body()
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    latitude = require_number(body, "latitude")
    longitude = require_number(body, "longitude")
    max_yard = require_int(body, "max_yard_colonies", minimum=1)
    with store.lock:
        rec = {
            "name": name,
            "state_code": state_code,
            "latitude": latitude,
            "longitude": longitude,
            "registration_status": "UNREGISTERED",
            "active_colony_count": 0,
            "max_yard_colonies": max_yard,
        }
        stamp_create(rec)
        store.apiaries[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/apiaries/<aid>", methods=["GET"])
def get_apiary(aid):
    require_roles({"PlatformAdmin", "ApiaryManager", "StateApiarist", "ContractCoordinator"})
    rec = must_get(store.apiaries, aid)
    return response.object_response(public(rec))


@app.route("/apiaries", methods=["GET"])
def list_apiaries():
    require_roles({"PlatformAdmin", "ApiaryManager", "StateApiarist", "ContractCoordinator"})
    state_code = request.args.get("state_code")
    records = list(store.apiaries.values())
    if state_code is not None:
        records = [r for r in records if r["state_code"] == state_code]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


# ===========================================================================
# StateRegistration
# ===========================================================================
@app.route("/apiaries/<aid>/registrations", methods=["POST"])
def create_registration(aid):
    require_roles({"PlatformAdmin", "StateApiarist"})
    apiary = must_get(store.apiaries, aid)
    body = get_body()
    registration_number = require_str(body, "registration_number")
    effective_dt = require_dt(body, "effective_date")
    expiry_dt = require_dt(body, "expiry_date")
    with store.lock:
        # registration_number unique (PRD §3.10)
        for r in store.registrations.values():
            if r["registration_number"] == registration_number:
                raise errors.invalid_request("registration_number must be unique.")
        rec = {
            "apiary_id": aid,
            "registration_number": registration_number,
            "status": "PENDING",
            "effective_date": body["effective_date"],
            "expiry_date": body["expiry_date"],
            "_effective_dt": effective_dt,
            "_expiry_dt": expiry_dt,
        }
        stamp_create(rec)
        store.registrations[rec["id"]] = rec
        if apiary["registration_status"] == "UNREGISTERED":
            apiary["registration_status"] = "PENDING"
            touch(apiary)
    return response.object_response(public(rec), 201)


@app.route("/apiaries/<aid>/registrations", methods=["GET"])
def list_registrations(aid):
    require_roles({"PlatformAdmin", "StateApiarist", "ApiaryManager", "ContractCoordinator"})
    must_get(store.apiaries, aid)
    records = [r for r in store.registrations.values() if r["apiary_id"] == aid]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


def _get_registration(aid, rid):
    """Validate apiary then registration (path left-to-right), and that the
    registration belongs to the apiary."""
    must_get(store.apiaries, aid)
    reg = must_get(store.registrations, rid)
    if reg["apiary_id"] != aid:
        raise errors.not_found()
    return reg


def _refresh_apiary_registration_status(apiary):
    """If no ACTIVE registration remains, fall back to UNREGISTERED."""
    has_active = any(r["status"] == "ACTIVE" and r["apiary_id"] == apiary["id"]
                     for r in store.registrations.values())
    if not has_active:
        apiary["registration_status"] = "UNREGISTERED"
        touch(apiary)


@app.route("/apiaries/<aid>/registrations/<rid>/approve", methods=["POST"])
def approve_registration(aid, rid):
    require_roles({"StateApiarist"})
    with store.lock:
        reg = _get_registration(aid, rid)
        if reg["status"] in ("REVOKED",):
            raise errors.terminal_state()
        if reg["status"] != "PENDING":
            raise errors.invalid_state("Only a PENDING registration can be approved.")
        if store.clock < reg["_effective_dt"]:
            raise errors.too_early("Clock has not reached the registration's effective_date.")
        if store.clock >= reg["_expiry_dt"]:
            raise errors.invalid_state("Clock is at or past the registration's expiry_date.")
        reg["status"] = "ACTIVE"
        touch(reg)
        apiary = store.apiaries[aid]
        apiary["registration_status"] = "ACTIVE"
        touch(apiary)
    return response.object_response(public(reg))


@app.route("/apiaries/<aid>/registrations/<rid>/expire", methods=["POST"])
def expire_registration(aid, rid):
    require_roles({"StateApiarist", "PlatformAdmin"})
    with store.lock:
        reg = _get_registration(aid, rid)
        if reg["status"] in ("REVOKED",):
            raise errors.terminal_state()
        if reg["status"] != "ACTIVE":
            raise errors.invalid_state("Only an ACTIVE registration can be expired.")
        if store.clock < reg["_expiry_dt"]:
            raise errors.too_early("Clock has not reached the registration's expiry_date.")
        reg["status"] = "EXPIRED"
        touch(reg)
        apiary = store.apiaries[aid]
        apiary["registration_status"] = "EXPIRED"
        touch(apiary)
    return response.object_response(public(reg))


@app.route("/apiaries/<aid>/registrations/<rid>/revoke", methods=["POST"])
def revoke_registration(aid, rid):
    require_roles({"StateApiarist"})
    with store.lock:
        reg = _get_registration(aid, rid)
        if reg["status"] == "REVOKED":
            raise errors.terminal_state()
        if reg["status"] != "PENDING":
            raise errors.invalid_state("Only a PENDING registration can be revoked.")
        reg["status"] = "REVOKED"
        touch(reg)
        apiary = store.apiaries[aid]
        _refresh_apiary_registration_status(apiary)
    return response.object_response(public(reg))


# ===========================================================================
# Hive
# ===========================================================================
@app.route("/hives", methods=["POST"])
def create_hive():
    user_id, role = require_roles({"ApiaryManager"})
    body = get_body()
    with store.lock:
        apiary_id, apiary = require_fk(body, "apiary_id", store.apiaries)
        assert_owns_apiary(role, user_id, apiary_id)
        source_hive_id, _ = optional_fk(body, "source_hive_id", store.hives)
        tag = require_str(body, "tag")
        brood_frames = optional_int(body, "brood_frames", default=0, non_negative=True)
        # tag unique within apiary (PRD §3.10)
        for h in store.hives.values():
            if h["apiary_id"] == apiary_id and h["tag"] == tag:
                raise errors.invalid_request("Hive tag must be unique within the apiary.")
        rec = {
            "apiary_id": apiary_id,
            "source_hive_id": source_hive_id,
            "tag": tag,
            "health_status": "HEALTHY",
            "queen_status": "QUEENRIGHT",
            "brood_frames": brood_frames,
            "honey_frames": 0,
            "last_mite_count": None,
            "harvest_blocked_until": None,
            "inspection_strength": 0,
            "_harvest_blocked_dt": None,
        }
        stamp_create(rec)
        store.hives[rec["id"]] = rec
        recompute_active_colony_count(apiary)
        touch(apiary)
    return response.object_response(hive_view(rec), 201)


@app.route("/hives/<hid>", methods=["GET"])
def get_hive(hid):
    require_roles({"ApiaryManager", "ContractCoordinator", "PlatformAdmin"})
    rec = must_get(store.hives, hid)
    return response.object_response(hive_view(rec))


@app.route("/hives", methods=["GET"])
def list_hives():
    require_roles({"ApiaryManager", "ContractCoordinator", "PlatformAdmin"})
    apiary_id = request.args.get("apiary_id")
    source_hive_id = request.args.get("source_hive_id")
    health_status = request.args.get("health_status")
    records = list(store.hives.values())
    if apiary_id is not None:
        records = [r for r in records if r["apiary_id"] == apiary_id]
    if source_hive_id is not None:
        records = [r for r in records if r["source_hive_id"] == source_hive_id]
    if health_status is not None:
        records = [r for r in records if r["health_status"] == health_status]
    window, limit, offset, total = paginate(records)
    return response.array_response([hive_view(r) for r in window], limit, offset, total)


def _owned_hive(hid, role, user_id):
    hive = must_get(store.hives, hid)
    assert_owns_apiary(role, user_id, hive["apiary_id"])
    return hive


@app.route("/hives/<hid>/quarantine", methods=["POST"])
def quarantine_hive(hid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        hive = _owned_hive(hid, role, user_id)
        if hive["health_status"] == "DEADOUT":
            raise errors.terminal_state()
        if hive["health_status"] != "HEALTHY":
            raise errors.invalid_state("Only a HEALTHY hive can be quarantined.")
        hive["health_status"] = "QUARANTINE"
        touch(hive)
        # side effect: cancel PROPOSED placements of this hive
        for p in store.placements.values():
            if p["hive_id"] == hid and p["status"] == "PROPOSED":
                p["status"] = "CANCELLED"
                touch(p)
    return response.object_response(hive_view(hive))


@app.route("/hives/<hid>/deadout", methods=["POST"])
def deadout_hive(hid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        hive = _owned_hive(hid, role, user_id)
        if hive["health_status"] == "DEADOUT":
            raise errors.terminal_state()
        hive["health_status"] = "DEADOUT"
        touch(hive)
        # hop 1: recompute apiary active_colony_count
        apiary = store.apiaries[hive["apiary_id"]]
        recompute_active_colony_count(apiary)
        touch(apiary)
        # hop 2: CONFIRMED placements of this hive -> REMOVED; decrement placed
        affected_contracts = set()
        for p in store.placements.values():
            if p["hive_id"] == hid and p["status"] == "CONFIRMED":
                p["status"] = "REMOVED"
                touch(p)
                affected_contracts.add(p["contract_id"])
        for cid in affected_contracts:
            contract = store.contracts.get(cid)
            if contract is None:
                continue
            recompute_contract_placed(contract)
            # hop 3: PLACED dropping below required -> UNDERSTAFFED + payout recompute
            if contract["status"] == "PLACED" and \
                    contract["placed_strong_hives"] < contract["required_strong_hives"]:
                contract["status"] = "UNDERSTAFFED"
            recompute_payout(contract)
            touch(contract)
    return response.object_response(hive_view(hive))


@app.route("/hives/<hid>/mark-queenless", methods=["POST"])
def mark_queenless(hid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        hive = _owned_hive(hid, role, user_id)
        if hive["health_status"] == "DEADOUT":
            raise errors.terminal_state()
        if hive["queen_status"] != "QUEENRIGHT":
            raise errors.invalid_state("Only a QUEENRIGHT hive can be marked QUEENLESS.")
        hive["queen_status"] = "QUEENLESS"
        touch(hive)
    return response.object_response(hive_view(hive))


@app.route("/hives/<hid>/requeen-complete", methods=["POST"])
def requeen_complete(hid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        hive = _owned_hive(hid, role, user_id)
        if hive["health_status"] == "DEADOUT":
            raise errors.terminal_state()
        if hive["queen_status"] != "REQUEENING":
            raise errors.invalid_state("Only a REQUEENING hive can complete requeening.")
        hive["queen_status"] = "QUEENRIGHT"
        touch(hive)
    return response.object_response(hive_view(hive))


# ===========================================================================
# Inspection (immutable, append-only)
# ===========================================================================
@app.route("/hives/<hid>/inspections", methods=["POST"])
def create_inspection(hid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        hive = _owned_hive(hid, role, user_id)
        body = get_body()
        inspected_dt = require_dt(body, "inspected_at")
        mites = require_number(body, "mites_per_100_bees", non_negative=True)
        brood_observed = require_int(body, "brood_frames_observed", non_negative=True)
        honey_observed = optional_int(body, "honey_frames_observed", default=0, non_negative=True)
        queen_seen = require_bool(body, "queen_seen")
        treatment_recommended = D(mites) >= D("3.0")
        rec = {
            "hive_id": hid,
            "inspected_at": body["inspected_at"],
            "mites_per_100_bees": mites,
            "brood_frames_observed": brood_observed,
            "honey_frames_observed": honey_observed,
            "queen_seen": queen_seen,
            "treatment_recommended": treatment_recommended,
            "_inspected_dt": inspected_dt,
        }
        stamp_create(rec, with_version=False)
        store.inspections[rec["id"]] = rec
        # write through to the hive
        hive["brood_frames"] = brood_observed
        hive["honey_frames"] = honey_observed
        hive["last_mite_count"] = mites
        # queen flip
        if queen_seen is False and hive["queen_status"] == "QUEENRIGHT":
            hive["queen_status"] = "QUEENLESS"
        # recompute point_in_time strength (uses updated frames/mite/queen)
        hive["inspection_strength"] = calc.point_in_time_strength(
            brood_observed, honey_observed, mites, hive["queen_status"])
        touch(hive)
    return response.object_response(public(rec), 201)


@app.route("/hives/<hid>/inspections", methods=["GET"])
def list_inspections(hid):
    require_roles({"ApiaryManager", "PlatformAdmin"})
    must_get(store.hives, hid)
    records = [r for r in store.inspections.values() if r["hive_id"] == hid]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


# ===========================================================================
# Treatment
# ===========================================================================
@app.route("/hives/<hid>/treatments", methods=["POST"])
def create_treatment(hid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        hive = _owned_hive(hid, role, user_id)
        if hive["health_status"] == "DEADOUT":
            raise errors.terminal_state()
        if hive["health_status"] not in ("HEALTHY", "QUARANTINE"):
            raise errors.invalid_state("A treatment may be applied only from HEALTHY or QUARANTINE.")
        body = get_body()
        product = require_enum(body, "product", TREATMENT_PRODUCTS)
        applied_dt = require_dt(body, "applied_at")
        duration_days = require_int(body, "duration_days", minimum=1)
        withdrawal_days = WITHDRAWAL_DAYS[product]
        harvest_clear_dt = add_days(applied_dt, duration_days + withdrawal_days)
        rec = {
            "hive_id": hid,
            "product": product,
            "status": "ACTIVE",
            "applied_at": body["applied_at"],
            "duration_days": duration_days,
            "withdrawal_days": withdrawal_days,
            "harvest_clear_at": iso_from_dt(harvest_clear_dt),
            "_applied_dt": applied_dt,
            "_harvest_clear_dt": harvest_clear_dt,
        }
        stamp_create(rec)
        store.treatments[rec["id"]] = rec
        # health axis -> TREATMENT
        hive["health_status"] = "TREATMENT"
        # harvest_blocked_until = max(existing, harvest_clear_at)
        recompute_harvest_blocked_until(hive)
        touch(hive)
        # cascade: DRAFT lots with a RECORDED Harvest from this hive -> BLOCKED
        for lot in store.honey_lots.values():
            if lot["status"] != "DRAFT":
                continue
            if any(h["lot_id"] == lot["id"] and h["hive_id"] == hid and h["status"] == "RECORDED"
                   for h in store.harvests.values()):
                lot["status"] = "BLOCKED"
                touch(lot)
    return response.object_response(public(rec), 201)


@app.route("/hives/<hid>/treatments", methods=["GET"])
def list_hive_treatments(hid):
    require_roles({"ApiaryManager", "PlatformAdmin"})
    must_get(store.hives, hid)
    status = request.args.get("status")
    records = [r for r in store.treatments.values() if r["hive_id"] == hid]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/treatments/<tid>/complete", methods=["POST"])
def complete_treatment(tid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        treatment = must_get(store.treatments, tid)
        hive = store.hives[treatment["hive_id"]]
        assert_owns_apiary(role, user_id, hive["apiary_id"])
        if treatment["status"] in ("COMPLETED", "VOIDED"):
            raise errors.terminal_state()
        if treatment["status"] != "ACTIVE":
            raise errors.invalid_state("Only an ACTIVE treatment can be completed.")
        complete_at = add_days(treatment["_applied_dt"], treatment["duration_days"])
        if store.clock < complete_at:
            raise errors.too_early("Clock has not reached applied_at + duration_days.")
        treatment["status"] = "COMPLETED"
        touch(treatment)
        recompute_harvest_blocked_until(hive)
        # if no ACTIVE treatments remain, health -> HEALTHY
        remaining = any(t["hive_id"] == hive["id"] and t["status"] == "ACTIVE"
                        for t in store.treatments.values())
        if not remaining and hive["health_status"] == "TREATMENT":
            hive["health_status"] = "HEALTHY"
        touch(hive)
    return response.object_response(public(treatment))


@app.route("/treatments/<tid>/void", methods=["POST"])
def void_treatment(tid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        treatment = must_get(store.treatments, tid)
        hive = store.hives[treatment["hive_id"]]
        assert_owns_apiary(role, user_id, hive["apiary_id"])
        if treatment["status"] in ("COMPLETED", "VOIDED"):
            raise errors.terminal_state()
        if treatment["status"] != "ACTIVE":
            raise errors.invalid_state("Only an ACTIVE treatment can be voided.")
        treatment["status"] = "VOIDED"
        touch(treatment)
        recompute_harvest_blocked_until(hive)
        remaining = any(t["hive_id"] == hive["id"] and t["status"] == "ACTIVE"
                        for t in store.treatments.values())
        if not remaining and hive["health_status"] == "TREATMENT":
            hive["health_status"] = "HEALTHY"
        touch(hive)
    return response.object_response(public(treatment))


# ===========================================================================
# HoneyLot
# ===========================================================================
@app.route("/honey-lots", methods=["POST"])
def create_honey_lot():
    user_id, role = require_roles({"ApiaryManager"})
    body = get_body()
    with store.lock:
        apiary_id, apiary = require_fk(body, "apiary_id", store.apiaries)
        assert_owns_apiary(role, user_id, apiary_id)
        lot_code = require_str(body, "lot_code")
        floral_source = require_enum(body, "floral_source", FLORAL_SOURCES)
        # lot_code unique per apiary (PRD §3.10)
        for l in store.honey_lots.values():
            if l["apiary_id"] == apiary_id and l["lot_code"] == lot_code:
                raise errors.invalid_request("lot_code must be unique within the apiary.")
        rec = {
            "apiary_id": apiary_id,
            "lot_code": lot_code,
            "floral_source": floral_source,
            "status": "DRAFT",
            "provisional_yield_kg": 0,
            "final_yield_kg": None,
            "gross_weight_kg": 0,
            "price_per_kg_cents": 0,
            "gross_revenue_cents": None,
            "net_revenue_cents": None,
        }
        stamp_create(rec)
        store.honey_lots[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/honey-lots/<lid>", methods=["GET"])
def get_honey_lot(lid):
    require_roles({"ApiaryManager", "PlatformAdmin"})
    rec = must_get(store.honey_lots, lid)
    return response.object_response(public(rec))


@app.route("/honey-lots", methods=["GET"])
def list_honey_lots():
    require_roles({"ApiaryManager", "PlatformAdmin"})
    apiary_id = request.args.get("apiary_id")
    status = request.args.get("status")
    records = list(store.honey_lots.values())
    if apiary_id is not None:
        records = [r for r in records if r["apiary_id"] == apiary_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


def _lot_contributing_hives(lot):
    hive_ids = set(h["hive_id"] for h in store.harvests.values()
                   if h["lot_id"] == lot["id"] and h["status"] == "RECORDED")
    return [store.hives[hid] for hid in hive_ids if hid in store.hives]


def _owned_lot(lid, role, user_id):
    lot = must_get(store.honey_lots, lid)
    assert_owns_apiary(role, user_id, lot["apiary_id"])
    return lot


@app.route("/honey-lots/<lid>/unblock", methods=["POST"])
def unblock_lot(lid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        lot = _owned_lot(lid, role, user_id)
        if lot["status"] in ("SOLD", "VOIDED"):
            raise errors.terminal_state()
        if lot["status"] != "BLOCKED":
            raise errors.invalid_state("Only a BLOCKED lot can be unblocked.")
        # no contributing hive still blocked
        for hive in _lot_contributing_hives(lot):
            if hive_is_blocked(hive):
                raise errors.harvest_blocked_withdrawal()
        lot["status"] = "DRAFT"
        touch(lot)
    return response.object_response(public(lot))


@app.route("/honey-lots/<lid>/extract", methods=["POST"])
def extract_lot(lid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        lot = _owned_lot(lid, role, user_id)
        if lot["status"] in ("SOLD", "VOIDED"):
            raise errors.terminal_state()
        if lot["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT lot can be extracted.")
        # business safety: withdrawal block precedes empty-lot per validation order
        for hive in _lot_contributing_hives(lot):
            if hive_is_blocked(hive):
                raise errors.harvest_blocked_withdrawal()
        recorded = [h for h in store.harvests.values()
                    if h["lot_id"] == lid and h["status"] == "RECORDED"]
        if len(recorded) < 1:
            raise errors.empty_lot()
        lot["final_yield_kg"] = calc.final_yield(lot["gross_weight_kg"])
        lot["status"] = "EXTRACTED"
        touch(lot)
    return response.object_response(public(lot))


@app.route("/honey-lots/<lid>/sell", methods=["POST"])
def sell_lot(lid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        lot = _owned_lot(lid, role, user_id)
        if lot["status"] in ("SOLD", "VOIDED"):
            raise errors.terminal_state()
        if lot["status"] != "EXTRACTED":
            raise errors.invalid_state("Only an EXTRACTED lot can be sold.")
        body = get_body()
        price = require_int(body, "price_per_kg_cents", minimum=1)
        lot["price_per_kg_cents"] = price
        gross, net = calc.honey_revenue(lot["final_yield_kg"], price)
        lot["gross_revenue_cents"] = gross
        lot["net_revenue_cents"] = net
        lot["status"] = "SOLD"
        touch(lot)
    return response.object_response(public(lot))


@app.route("/honey-lots/<lid>/void", methods=["POST"])
def void_lot(lid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        lot = _owned_lot(lid, role, user_id)
        if lot["status"] in ("SOLD", "VOIDED"):
            raise errors.terminal_state()
        if lot["status"] not in ("DRAFT", "BLOCKED"):
            raise errors.invalid_state("Only a DRAFT or BLOCKED lot can be voided.")
        # VOID every RECORDED Harvest, restoring gross_weight_kg to 0
        for h in store.harvests.values():
            if h["lot_id"] == lid and h["status"] == "RECORDED":
                h["status"] = "VOID"
                touch(h)
        lot["gross_weight_kg"] = 0
        recompute_provisional_yield(lot)
        lot["status"] = "VOIDED"
        touch(lot)
    return response.object_response(public(lot))


# ===========================================================================
# Harvest
# ===========================================================================
@app.route("/honey-lots/<lid>/harvests", methods=["POST"])
def create_harvest(lid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        lot = _owned_lot(lid, role, user_id)
        if lot["status"] in ("SOLD", "VOIDED"):
            raise errors.terminal_state()
        if lot["status"] != "DRAFT":
            raise errors.invalid_state("Harvests may be recorded only into a DRAFT lot.")
        body = get_body()
        hive_id, hive = require_fk(body, "hive_id", store.hives)
        frames_pulled = require_int(body, "frames_pulled", minimum=1)
        weight_kg = require_number(body, "weight_kg", positive=True)
        # business safety: contributing hive withdrawal block
        if hive_is_blocked(hive):
            raise errors.harvest_blocked_withdrawal()
        rec = {
            "lot_id": lid,
            "hive_id": hive_id,
            "frames_pulled": frames_pulled,
            "weight_kg": weight_kg,
            "status": "RECORDED",
        }
        stamp_create(rec)
        store.harvests[rec["id"]] = rec
        recompute_gross_weight(lot)
        recompute_provisional_yield(lot)
        touch(lot)
    return response.object_response(public(rec), 201)


@app.route("/honey-lots/<lid>/harvests", methods=["GET"])
def list_lot_harvests(lid):
    require_roles({"ApiaryManager", "PlatformAdmin"})
    must_get(store.honey_lots, lid)
    records = [r for r in store.harvests.values() if r["lot_id"] == lid]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/harvests/<hvid>", methods=["GET"])
def get_harvest(hvid):
    require_roles({"ApiaryManager", "PlatformAdmin"})
    rec = must_get(store.harvests, hvid)
    return response.object_response(public(rec))


@app.route("/harvests", methods=["GET"])
def list_harvests():
    require_roles({"ApiaryManager", "PlatformAdmin"})
    hive_id = request.args.get("hive_id")
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    records = list(store.harvests.values())
    if hive_id is not None:
        records = [r for r in records if r["hive_id"] == hive_id]
    if lot_id is not None:
        records = [r for r in records if r["lot_id"] == lot_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/harvests/<hvid>/void", methods=["POST"])
def void_harvest(hvid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        harvest = must_get(store.harvests, hvid)
        lot = store.honey_lots[harvest["lot_id"]]
        assert_owns_apiary(role, user_id, lot["apiary_id"])
        if harvest["status"] == "VOID":
            raise errors.terminal_state()
        if harvest["status"] != "RECORDED":
            raise errors.invalid_state("Only a RECORDED harvest can be voided.")
        if lot["status"] not in ("DRAFT", "BLOCKED"):
            raise errors.invalid_state("A harvest may be voided only while its lot is DRAFT or BLOCKED.")
        harvest["status"] = "VOID"
        touch(harvest)
        recompute_gross_weight(lot)
        recompute_provisional_yield(lot)
        touch(lot)
    return response.object_response(public(harvest))


# ===========================================================================
# PollinationContract
# ===========================================================================
@app.route("/pollination-contracts", methods=["POST"])
def create_contract():
    require_roles({"ContractCoordinator"})
    body = get_body()
    grower_name = require_str(body, "grower_name")
    orchard_state_code = require_str(body, "orchard_state_code")
    bloom_start_dt = require_dt(body, "bloom_start")
    bloom_end_dt = require_dt(body, "bloom_end")
    required_strong = require_int(body, "required_strong_hives", minimum=1)
    max_hives = require_int(body, "max_hives_on_site", minimum=1)
    base_rate = require_int(body, "base_rate_cents", non_negative=True)
    with store.lock:
        rec = {
            "grower_name": grower_name,
            "orchard_state_code": orchard_state_code,
            "bloom_start": body["bloom_start"],
            "bloom_end": body["bloom_end"],
            "required_strong_hives": required_strong,
            "max_hives_on_site": max_hives,
            "base_rate_cents": base_rate,
            "status": "DRAFT",
            "placed_strong_hives": 0,
            "projected_payout_cents": 0,
            "_bloom_start_dt": bloom_start_dt,
            "_bloom_end_dt": bloom_end_dt,
        }
        stamp_create(rec)
        store.contracts[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/pollination-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_roles({"ContractCoordinator", "PlatformAdmin"})
    rec = must_get(store.contracts, cid)
    return response.object_response(public(rec))


@app.route("/pollination-contracts", methods=["GET"])
def list_contracts():
    require_roles({"ContractCoordinator", "PlatformAdmin"})
    status = request.args.get("status")
    records = list(store.contracts.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/pollination-contracts/<cid>/sign", methods=["POST"])
def sign_contract(cid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        contract = must_get(store.contracts, cid)
        if contract["status"] in ("FULFILLED", "CANCELLED"):
            raise errors.terminal_state()
        if contract["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT contract can be signed.")
        if not (contract["_bloom_end_dt"] > contract["_bloom_start_dt"]):
            raise errors.validation("bloom_end must be strictly after bloom_start.")
        contract["status"] = "SIGNED"
        touch(contract)
    return response.object_response(public(contract))


@app.route("/pollination-contracts/<cid>/finalize-placement", methods=["POST"])
def finalize_placement(cid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        contract = must_get(store.contracts, cid)
        if contract["status"] in ("FULFILLED", "CANCELLED"):
            raise errors.terminal_state()
        if contract["status"] not in ("SIGNED", "UNDERSTAFFED"):
            raise errors.invalid_state("Only a SIGNED or UNDERSTAFFED contract can be finalized.")
        if contract["placed_strong_hives"] < contract["required_strong_hives"]:
            raise errors.invalid_state("placed_strong_hives is below required_strong_hives.")
        contract["status"] = "PLACED"
        recompute_payout(contract)
        touch(contract)
    return response.object_response(public(contract))


@app.route("/pollination-contracts/<cid>/dispute", methods=["POST"])
def dispute_contract(cid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        contract = must_get(store.contracts, cid)
        if contract["status"] in ("FULFILLED", "CANCELLED"):
            raise errors.terminal_state()
        if contract["status"] != "PLACED":
            raise errors.invalid_state("Only a PLACED contract can be disputed.")
        contract["status"] = "DISPUTED"
        touch(contract)
    return response.object_response(public(contract))


@app.route("/pollination-contracts/<cid>/resolve-dispute", methods=["POST"])
def resolve_dispute(cid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        contract = must_get(store.contracts, cid)
        if contract["status"] in ("FULFILLED", "CANCELLED"):
            raise errors.terminal_state()
        if contract["status"] != "DISPUTED":
            raise errors.invalid_state("Only a DISPUTED contract can be resolved.")
        if contract["placed_strong_hives"] < contract["required_strong_hives"]:
            raise errors.invalid_state("placed_strong_hives is below required_strong_hives.")
        contract["status"] = "PLACED"
        recompute_payout(contract)
        touch(contract)
    return response.object_response(public(contract))


@app.route("/pollination-contracts/<cid>/fulfill", methods=["POST"])
def fulfill_contract(cid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        contract = must_get(store.contracts, cid)
        if contract["status"] in ("FULFILLED", "CANCELLED"):
            raise errors.terminal_state()
        if contract["status"] != "PLACED":
            raise errors.invalid_state("Only a PLACED contract can be fulfilled.")
        if store.clock < contract["_bloom_end_dt"]:
            raise errors.too_early("Clock has not reached bloom_end.")
        # every CONFIRMED placement must be REMOVED or its removal_due <= clock
        for p in store.placements.values():
            if p["contract_id"] != cid:
                continue
            if p["status"] == "CONFIRMED" and store.clock < p["_removal_due_dt"]:
                raise errors.too_early("A confirmed placement is not yet past its removal_due.")
        contract["status"] = "FULFILLED"
        touch(contract)
    return response.object_response(public(contract))


@app.route("/pollination-contracts/<cid>/cancel", methods=["POST"])
def cancel_contract(cid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        contract = must_get(store.contracts, cid)
        if contract["status"] in ("FULFILLED", "CANCELLED"):
            raise errors.terminal_state()
        if contract["status"] not in ("DRAFT", "SIGNED", "UNDERSTAFFED"):
            raise errors.invalid_state("Only DRAFT, SIGNED, or UNDERSTAFFED contracts can be cancelled.")
        # cancel all PROPOSED/CONFIRMED placements; reset placed to 0
        for p in store.placements.values():
            if p["contract_id"] == cid and p["status"] in ("PROPOSED", "CONFIRMED"):
                p["status"] = "CANCELLED"
                touch(p)
        contract["placed_strong_hives"] = 0
        contract["status"] = "CANCELLED"
        touch(contract)
    return response.object_response(public(contract))


# ===========================================================================
# HivePlacement
# ===========================================================================
def _windows_overlap(start_a, end_a, start_b, end_b):
    """Half-open [start, end) overlap. Adjacency (one's end == other's start) is
    NOT an overlap."""
    return start_a < end_b and start_b < end_a


@app.route("/pollination-contracts/<cid>/placements", methods=["POST"])
def create_placement(cid):
    require_roles({"ContractCoordinator"})
    contract = must_get(store.contracts, cid)
    body = get_body()
    with store.lock:
        hive_id, hive = require_fk(body, "hive_id", store.hives)
        placement_start_dt = require_dt(body, "placement_start")
        removal_due_dt = require_dt(body, "removal_due")
        if not (removal_due_dt > placement_start_dt):
            raise errors.validation("removal_due must be strictly after placement_start.")
        rec = {
            "contract_id": cid,
            "hive_id": hive_id,
            "placement_start": body["placement_start"],
            "removal_due": body["removal_due"],
            "grade": None,
            "status": "PROPOSED",
            "contract_rated_strength": None,
            "_placement_start_dt": placement_start_dt,
            "_removal_due_dt": removal_due_dt,
        }
        stamp_create(rec)
        store.placements[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/pollination-contracts/<cid>/placements", methods=["GET"])
def list_contract_placements(cid):
    require_roles({"ContractCoordinator", "PlatformAdmin"})
    must_get(store.contracts, cid)
    status = request.args.get("status")
    records = [r for r in store.placements.values() if r["contract_id"] == cid]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/hive-placements/<pid>", methods=["GET"])
def get_placement(pid):
    require_roles({"ContractCoordinator", "PlatformAdmin"})
    rec = must_get(store.placements, pid)
    return response.object_response(public(rec))


@app.route("/hive-placements", methods=["GET"])
def list_placements():
    require_roles({"ContractCoordinator", "PlatformAdmin"})
    hive_id = request.args.get("hive_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    records = list(store.placements.values())
    if hive_id is not None:
        records = [r for r in records if r["hive_id"] == hive_id]
    if contract_id is not None:
        records = [r for r in records if r["contract_id"] == contract_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/hive-placements/<pid>/confirm", methods=["POST"])
def confirm_placement(pid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        placement = must_get(store.placements, pid)
        body = get_body()
        contract = store.contracts[placement["contract_id"]]
        hive = store.hives[placement["hive_id"]]

        # state gate (priority 6/7)
        if placement["status"] in ("REMOVED", "CANCELLED"):
            raise errors.terminal_state()
        if placement["status"] != "PROPOSED":
            raise errors.invalid_state("Only a PROPOSED placement can be confirmed.")

        # business safety: apiary registration ACTIVE (priority 9)
        apiary = store.apiaries[hive["apiary_id"]]
        if apiary["registration_status"] != "ACTIVE":
            raise errors.apiary_not_registered()

        # placement eligibility: contract SIGNED/UNDERSTAFFED + hive HEALTHY (priority 10)
        if contract["status"] not in ("SIGNED", "UNDERSTAFFED"):
            raise errors.hive_not_placeable("Parent contract must be SIGNED or UNDERSTAFFED.")
        if hive["health_status"] != "HEALTHY":
            raise errors.hive_not_placeable("Hive must be HEALTHY to be placed.")

        new_start = placement["_placement_start_dt"]
        new_end = placement["_removal_due_dt"]

        # double-booking: no other CONFIRMED placement of THIS hive overlaps (priority 11)
        for p in store.placements.values():
            if p["id"] == pid:
                continue
            if p["hive_id"] != hive["id"]:
                continue
            if p["status"] != "CONFIRMED":
                continue
            if _windows_overlap(new_start, new_end, p["_placement_start_dt"], p["_removal_due_dt"]):
                raise errors.hive_double_booked()

        # site capacity: aggregate hives whose windows overlap on THIS contract (priority 12)
        overlapping = 0
        for p in store.placements.values():
            if p["id"] == pid:
                continue
            if p["contract_id"] != contract["id"]:
                continue
            if p["status"] != "CONFIRMED":
                continue
            if _windows_overlap(new_start, new_end, p["_placement_start_dt"], p["_removal_due_dt"]):
                overlapping += 1
        # PRD §3.5: confirming must not push the aggregate count of hives whose
        # windows overlap the new window to a value that MEETS OR EXCEEDS
        # max_hives_on_site (PRD prose wins over the scaffold's "< max" precondition).
        if overlapping + 1 >= contract["max_hives_on_site"]:
            raise errors.site_capacity_exceeded()

        # OCC (priority 17)
        if "expected_contract_version" not in body or body["expected_contract_version"] is None:
            raise errors.invalid_request("Missing required field 'expected_contract_version'.")
        expected = body["expected_contract_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.invalid_request("Field 'expected_contract_version' must be an integer.")
        if expected != contract["version"]:
            raise errors.stale_contract_version()

        # --- snapshot grade + contract_rated_strength (forward_projected) ---
        score, grade = calc.forward_projected_strength(
            hive, contract["_bloom_start_dt"], store.clock)
        placement["contract_rated_strength"] = score
        placement["grade"] = grade
        placement["status"] = "CONFIRMED"
        touch(placement)

        if grade == "CONTRACT_GRADE":
            contract["placed_strong_hives"] = contract["placed_strong_hives"] + 1
        touch(contract)  # always increments version
    return response.object_response(public(placement))


@app.route("/hive-placements/<pid>/remove", methods=["POST"])
def remove_placement(pid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        placement = must_get(store.placements, pid)
        if placement["status"] in ("REMOVED", "CANCELLED"):
            raise errors.terminal_state()
        if placement["status"] != "CONFIRMED":
            raise errors.invalid_state("Only a CONFIRMED placement can be removed.")
        placement["status"] = "REMOVED"
        touch(placement)
        contract = store.contracts[placement["contract_id"]]
        if placement["grade"] == "CONTRACT_GRADE":
            contract["placed_strong_hives"] = max(0, contract["placed_strong_hives"] - 1)
            touch(contract)
    return response.object_response(public(placement))


@app.route("/hive-placements/<pid>/cancel", methods=["POST"])
def cancel_placement(pid):
    require_roles({"ContractCoordinator"})
    with store.lock:
        placement = must_get(store.placements, pid)
        if placement["status"] in ("REMOVED", "CANCELLED"):
            raise errors.terminal_state()
        if placement["status"] != "PROPOSED":
            raise errors.invalid_state("Only a PROPOSED placement can be cancelled.")
        placement["status"] = "CANCELLED"
        touch(placement)
    return response.object_response(public(placement))


# ===========================================================================
# QueenNucSale
# ===========================================================================
@app.route("/apiaries/<aid>/queen-nuc-sales", methods=["POST"])
def create_sale(aid):
    user_id, role = require_roles({"ContractCoordinator", "ApiaryManager"})
    apiary = must_get(store.apiaries, aid)
    assert_owns_apiary(role, user_id, aid)
    body = get_body()
    with store.lock:
        source_hive_id, source_hive = require_fk(body, "source_hive_id", store.hives)
        product_type = require_enum(body, "product_type", PRODUCT_TYPES)
        frames_drawn = optional_int(body, "frames_drawn", default=0, non_negative=True)
        price_cents = require_int(body, "price_cents", non_negative=True)
        rec = {
            "apiary_id": aid,
            "source_hive_id": source_hive_id,
            "product_type": product_type,
            "frames_drawn": frames_drawn,
            "price_cents": price_cents,
            "status": "RESERVED",
        }
        stamp_create(rec)
        store.sales[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/apiaries/<aid>/queen-nuc-sales", methods=["GET"])
def list_apiary_sales(aid):
    require_roles({"ContractCoordinator", "ApiaryManager", "PlatformAdmin"})
    must_get(store.apiaries, aid)
    status = request.args.get("status")
    records = [r for r in store.sales.values() if r["apiary_id"] == aid]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/queen-nuc-sales/<sid>", methods=["GET"])
def get_sale(sid):
    require_roles({"ContractCoordinator", "ApiaryManager", "PlatformAdmin"})
    rec = must_get(store.sales, sid)
    return response.object_response(public(rec))


@app.route("/queen-nuc-sales", methods=["GET"])
def list_sales():
    require_roles({"ContractCoordinator", "ApiaryManager", "PlatformAdmin"})
    source_hive_id = request.args.get("source_hive_id")
    apiary_id = request.args.get("apiary_id")
    status = request.args.get("status")
    records = list(store.sales.values())
    if source_hive_id is not None:
        records = [r for r in records if r["source_hive_id"] == source_hive_id]
    if apiary_id is not None:
        records = [r for r in records if r["apiary_id"] == apiary_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/queen-nuc-sales/<sid>/ship", methods=["POST"])
def ship_sale(sid):
    user_id, role = require_roles({"ContractCoordinator", "ApiaryManager"})
    with store.lock:
        sale = must_get(store.sales, sid)
        assert_owns_apiary(role, user_id, sale["apiary_id"])
        if sale["status"] == "VOIDED":
            raise errors.terminal_state()
        if sale["status"] != "RESERVED":
            raise errors.invalid_state("Only a RESERVED sale can be shipped.")
        source_hive = store.hives[sale["source_hive_id"]]
        if source_hive["health_status"] == "DEADOUT":
            raise errors.invalid_state("Source hive is DEADOUT.")
        if sale["product_type"] == "NUC":
            if source_hive["brood_frames"] < sale["frames_drawn"]:
                raise errors.insufficient_brood_frames()
            source_hive["brood_frames"] = source_hive["brood_frames"] - sale["frames_drawn"]
            touch(source_hive)
            apiary = store.apiaries[sale["apiary_id"]]
            apiary["active_colony_count"] = max(0, apiary["active_colony_count"] - 1)
            touch(apiary)
        sale["status"] = "SHIPPED"
        touch(sale)
    return response.object_response(public(sale))


@app.route("/queen-nuc-sales/<sid>/void", methods=["POST"])
def void_sale(sid):
    user_id, role = require_roles({"ContractCoordinator", "ApiaryManager"})
    with store.lock:
        sale = must_get(store.sales, sid)
        assert_owns_apiary(role, user_id, sale["apiary_id"])
        if sale["status"] == "VOIDED":
            raise errors.terminal_state()
        if sale["status"] != "SHIPPED":
            raise errors.invalid_state("Only a SHIPPED sale can be voided.")
        if sale["product_type"] == "NUC":
            apiary = store.apiaries[sale["apiary_id"]]
            if apiary["active_colony_count"] + 1 > apiary["max_yard_colonies"]:
                raise errors.yard_capacity_exceeded()
            source_hive = store.hives[sale["source_hive_id"]]
            source_hive["brood_frames"] = source_hive["brood_frames"] + sale["frames_drawn"]
            touch(source_hive)
            apiary["active_colony_count"] = apiary["active_colony_count"] + 1
            touch(apiary)
        sale["status"] = "VOIDED"
        touch(sale)
    return response.object_response(public(sale))


# ===========================================================================
# Feeding (immutable, append-only)
# ===========================================================================
@app.route("/hives/<hid>/feedings", methods=["POST"])
def create_feeding(hid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        hive = _owned_hive(hid, role, user_id)
        body = get_body()
        fed_dt = require_dt(body, "fed_at")
        feed_type = require_enum(body, "feed_type", FEED_TYPES)
        quantity_kg = require_number(body, "quantity_kg", positive=True)
        rec = {
            "hive_id": hid,
            "fed_at": body["fed_at"],
            "feed_type": feed_type,
            "quantity_kg": quantity_kg,
            "_fed_dt": fed_dt,
        }
        stamp_create(rec, with_version=False)
        store.feedings[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/hives/<hid>/feedings", methods=["GET"])
def list_feedings(hid):
    require_roles({"ApiaryManager", "PlatformAdmin"})
    must_get(store.hives, hid)
    records = [r for r in store.feedings.values() if r["hive_id"] == hid]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


# ===========================================================================
# RequeenSchedule
# ===========================================================================
@app.route("/hives/<hid>/requeen-schedules", methods=["POST"])
def create_requeen_schedule(hid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        hive = _owned_hive(hid, role, user_id)
        body = get_body()
        due_dt = require_dt(body, "due_date")
        reason = require_enum(body, "reason", REQUEEN_REASONS)
        rec = {
            "hive_id": hid,
            "due_date": body["due_date"],
            "reason": reason,
            "status": "SCHEDULED",
            "_due_dt": due_dt,
        }
        stamp_create(rec)
        store.requeen_schedules[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/hives/<hid>/requeen-schedules", methods=["GET"])
def list_requeen_schedules(hid):
    require_roles({"ApiaryManager", "PlatformAdmin"})
    must_get(store.hives, hid)
    status = request.args.get("status")
    records = [r for r in store.requeen_schedules.values() if r["hive_id"] == hid]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/requeen-schedules/<rid>/start", methods=["POST"])
def start_requeen(rid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        schedule = must_get(store.requeen_schedules, rid)
        hive = store.hives[schedule["hive_id"]]
        assert_owns_apiary(role, user_id, hive["apiary_id"])
        if schedule["status"] in ("COMPLETED", "CANCELLED"):
            raise errors.terminal_state()
        if schedule["status"] != "SCHEDULED":
            raise errors.invalid_state("Only a SCHEDULED requeen can be started.")
        if hive["health_status"] == "DEADOUT":
            raise errors.invalid_state("Hive is DEADOUT.")
        if store.clock < schedule["_due_dt"]:
            raise errors.too_early("Clock has not reached the schedule's due_date.")
        if hive["queen_status"] != "QUEENLESS":
            raise errors.invalid_state("Hive must be QUEENLESS to start requeening.")
        schedule["status"] = "COMPLETED"
        touch(schedule)
        hive["queen_status"] = "REQUEENING"
        touch(hive)
    return response.object_response(public(schedule))


@app.route("/requeen-schedules/<rid>/cancel", methods=["POST"])
def cancel_requeen(rid):
    user_id, role = require_roles({"ApiaryManager"})
    with store.lock:
        schedule = must_get(store.requeen_schedules, rid)
        hive = store.hives[schedule["hive_id"]]
        assert_owns_apiary(role, user_id, hive["apiary_id"])
        if schedule["status"] in ("COMPLETED", "CANCELLED"):
            raise errors.terminal_state()
        if schedule["status"] != "SCHEDULED":
            raise errors.invalid_state("Only a SCHEDULED requeen can be cancelled.")
        schedule["status"] = "CANCELLED"
        touch(schedule)
    return response.object_response(public(schedule))


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
