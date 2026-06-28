"""Allergy & Immunotherapy Clinic API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
Logical clock defaults to 2026-01-01T00:00:00Z.
"""

import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request

import calc
import serialize
import services
from auth import require_auth, require_role
from clock import LogicalClock
from db import store, stamp_create, touch
from errors import ApiError, err
from response import object_response, array_response, error_response
from validate import (
    parse_pagination,
    get_body,
    require_str,
    optional_str,
    require_enum,
    optional_enum,
    optional_bool,
    require_number,
    optional_number,
    optional_int,
)

app = Flask(__name__)


# =============================================================================
# Error handling
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    # Unknown route — surface as a not-found in the standard envelope.
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", str(e), 400)


# =============================================================================
# Helpers
# =============================================================================
def auth_and_role(allowed):
    """Validate auth headers (priority 1) then RBAC (priority 2)."""
    _user_id, role = require_auth()
    require_role(role, allowed)
    return role


def get_patient_or_404(patient_id):
    p = store.patients.get(patient_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Patient not found")
    return p


def get_panel_or_404(panel_id):
    p = store.panels.get(panel_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Panel not found")
    return p


def get_plan_or_404(plan_id):
    p = store.plans.get(plan_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Plan not found")
    return p


def get_lot_or_404(lot_id):
    l = store.lots.get(lot_id)
    if l is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    return l


def get_vial_or_404(vial_id):
    v = store.vials.get(vial_id)
    if v is None:
        raise err("ERR_NOT_FOUND", "Vial not found")
    return v


def get_visit_or_404(visit_id):
    v = store.visits.get(visit_id)
    if v is None:
        raise err("ERR_NOT_FOUND", "Shot visit not found")
    return v


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD 2.3), then slice."""
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def check_plan_version(plan, body):
    """OCC guard (PRD 2.6). expected_plan_version is mandatory for guarded writes."""
    if "expected_plan_version" not in body or body.get("expected_plan_version") is None:
        raise err("ERR_INVALID_REQUEST", "expected_plan_version is required")
    expected = body.get("expected_plan_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_plan_version must be an integer")
    if expected != plan["version"]:
        raise err("ERR_STALE_PLAN_VERSION", "Plan version is stale")


# =============================================================================
# Clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth_and_role({"Allergist", "Pharmacist", "Nurse", "Biller", "FrontDesk"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        store.clock.set_from_iso(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp")
    # Advancing the clock auto-expires vials past their beyond-use date.
    expired_ids = services.expire_vials_for_clock()
    return object_response({
        "current_utc": store.clock.now_iso_ms(),
        "expired_vial_ids": expired_ids,
    }, 200)


# =============================================================================
# Patients
# =============================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    auth_and_role({"FrontDesk", "Allergist"})
    body = get_body()
    full_name = require_str(body, "full_name")
    date_of_birth = require_str(body, "date_of_birth")
    epinephrine_on_file = optional_bool(body, "epinephrine_on_file", default=False)

    patient = {
        "id": store.new_id(),
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "epinephrine_on_file": epinephrine_on_file,
        "prior_systemic_reaction": False,
        "status": "ACTIVE",
    }
    stamp_create(patient)
    store.patients[patient["id"]] = patient
    return object_response(serialize.patient(patient), 201)


@app.route("/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    auth_and_role({"FrontDesk", "Allergist", "Nurse", "Biller", "Pharmacist"})
    p = get_patient_or_404(patient_id)
    return object_response(serialize.patient(p), 200)


@app.route("/patients", methods=["GET"])
def list_patients():
    auth_and_role({"FrontDesk", "Allergist", "Nurse", "Biller", "Pharmacist"})
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = list(store.patients.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.patient(p) for p in page], limit, offset, total)


@app.route("/patients/<patient_id>", methods=["PATCH"])
def update_patient(patient_id):
    auth_and_role({"FrontDesk", "Allergist"})
    p = get_patient_or_404(patient_id)
    body = get_body()
    if "full_name" in body and body.get("full_name") is not None:
        p["full_name"] = require_str(body, "full_name")
    if "epinephrine_on_file" in body and body.get("epinephrine_on_file") is not None:
        val = body.get("epinephrine_on_file")
        if not isinstance(val, bool):
            raise err("ERR_INVALID_REQUEST", "epinephrine_on_file must be a boolean")
        p["epinephrine_on_file"] = val
    if "status" in body and body.get("status") is not None:
        p["status"] = require_enum(body, "status", {"ACTIVE", "INACTIVE"})
    touch(p)
    return object_response(serialize.patient(p), 200)


# =============================================================================
# Diagnostic panels & tests
# =============================================================================
@app.route("/patients/<patient_id>/panels", methods=["POST"])
def create_panel(patient_id):
    auth_and_role({"Allergist"})
    patient = get_patient_or_404(patient_id)
    body = get_body()
    panel_name = require_str(body, "panel_name")
    control_wheal_mm = optional_number(body, "control_wheal_mm", default=3)
    # INACTIVE patient may not have new panels (PRD 3.1 / 3.2).
    if patient["status"] != "ACTIVE":
        raise err("ERR_PATIENT_INACTIVE", "Patient is INACTIVE")

    panel = {
        "id": store.new_id(),
        "patient_id": patient_id,
        "panel_name": panel_name,
        "control_wheal_mm": control_wheal_mm,
        "screening_composite": 0.0,
        "clinical_composite": 0.0,
        "recommended_tier": "LOW",
        "status": "OPEN",
    }
    stamp_create(panel)
    store.panels[panel["id"]] = panel
    return object_response(serialize.panel(panel), 201)


@app.route("/patients/<patient_id>/panels", methods=["GET"])
def list_patient_panels(patient_id):
    auth_and_role({"Allergist", "Nurse", "FrontDesk"})
    get_patient_or_404(patient_id)
    limit, offset = parse_pagination(request.args)
    items = [p for p in store.panels.values() if p["patient_id"] == patient_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.panel(p) for p in page], limit, offset, total)


@app.route("/panels/<panel_id>", methods=["GET"])
def get_panel(panel_id):
    auth_and_role({"Allergist", "Nurse", "FrontDesk"})
    p = get_panel_or_404(panel_id)
    return object_response(serialize.panel(p), 200)


@app.route("/patients/<patient_id>/panels/<panel_id>/tests", methods=["POST"])
def add_test(patient_id, panel_id):
    auth_and_role({"Allergist"})
    # Path validated left-to-right (PRD 2.5).
    get_patient_or_404(patient_id)
    panel = get_panel_or_404(panel_id)
    if panel["patient_id"] != patient_id:
        raise err("ERR_NOT_FOUND", "Panel not found for this patient")

    # Panel state (priority 6): must be OPEN to accept tests.
    if panel["status"] != "OPEN":
        raise err("ERR_PANEL_NOT_OPEN", "Panel is not OPEN")

    body = get_body()
    allergen_code = require_str(body, "allergen_code")
    method = require_enum(body, "method", {"SKIN", "BLOOD"})
    clinically_relevant = optional_bool(body, "clinically_relevant", default=False)
    wheal_mm = body.get("wheal_mm")
    specific_ige_ku = body.get("specific_ige_ku")

    # Method/value coherence (priority 10).
    if method == "SKIN":
        if specific_ige_ku is not None:
            raise err("ERR_TEST_METHOD_MISMATCH", "SKIN test must not carry specific_ige_ku")
        if wheal_mm is None:
            raise err("ERR_TEST_METHOD_MISMATCH", "SKIN test requires wheal_mm")
        wheal_mm = require_number(body, "wheal_mm")
        specific_ige_ku = None
    else:  # BLOOD
        if wheal_mm is not None:
            raise err("ERR_TEST_METHOD_MISMATCH", "BLOOD test must not carry wheal_mm")
        if specific_ige_ku is None:
            raise err("ERR_TEST_METHOD_MISMATCH", "BLOOD test requires specific_ige_ku")
        specific_ige_ku = require_number(body, "specific_ige_ku")
        wheal_mm = None

    sensitization_index, is_positive = calc.score_test(
        method, wheal_mm, specific_ige_ku, panel["control_wheal_mm"]
    )

    test = {
        "id": store.new_id(),
        "panel_id": panel_id,
        "allergen_code": allergen_code,
        "method": method,
        "wheal_mm": wheal_mm,
        "specific_ige_ku": specific_ige_ku,
        "clinically_relevant": clinically_relevant,
        "sensitization_index": sensitization_index,
        "is_positive": is_positive,
    }
    stamp_create(test)
    store.tests[test["id"]] = test

    # Recompute panel composites & tier (derived-field reconciliation): the
    # panel is a mutation, so its version bumps (PRD 2.4 note).
    recompute_panel(panel)

    return object_response(serialize.allergen_test(test), 201)


def recompute_panel(panel):
    tests = [t for t in store.tests.values() if t["panel_id"] == panel["id"]]
    screening, clinical, tier = calc.compute_composites(tests)
    panel["screening_composite"] = screening
    panel["clinical_composite"] = clinical
    panel["recommended_tier"] = tier
    touch(panel)


@app.route("/panels/<panel_id>/tests", methods=["GET"])
def list_panel_tests(panel_id):
    auth_and_role({"Allergist", "Nurse"})
    get_panel_or_404(panel_id)
    limit, offset = parse_pagination(request.args)
    items = [t for t in store.tests.values() if t["panel_id"] == panel_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.allergen_test(t) for t in page], limit, offset, total)


@app.route("/patients/<patient_id>/panels/<panel_id>/finalize", methods=["POST"])
def finalize_panel(patient_id, panel_id):
    auth_and_role({"Allergist"})
    get_patient_or_404(patient_id)
    panel = get_panel_or_404(panel_id)
    if panel["patient_id"] != patient_id:
        raise err("ERR_NOT_FOUND", "Panel not found for this patient")

    # State (priority 6): must be OPEN.
    if panel["status"] != "OPEN":
        raise err("ERR_PANEL_NOT_OPEN", "Panel is not OPEN")

    tests = [t for t in store.tests.values() if t["panel_id"] == panel_id]
    # Business constraint (priority 11): >=1 test and >=1 positive test.
    if len(tests) == 0:
        raise err("ERR_PANEL_EMPTY", "Panel has no tests")
    if not any(t["is_positive"] for t in tests):
        raise err("ERR_NO_POSITIVE_TEST", "Panel has no positive test")

    # Composites frozen at their current values; transition OPEN -> FINALIZED.
    recompute_panel(panel)
    panel["status"] = "FINALIZED"
    touch(panel)
    return object_response(serialize.panel(panel), 200)


# =============================================================================
# Immunotherapy plans
# =============================================================================
@app.route("/immunotherapy-plans", methods=["POST"])
def create_plan():
    auth_and_role({"Allergist"})
    body = get_body()
    patient_id = require_str(body, "patient_id")
    panel_id = require_str(body, "panel_id")

    # FK existence (priority 4).
    patient = store.patients.get(patient_id)
    if patient is None:
        raise err("ERR_FK_NOT_FOUND", "patient_id not found")
    panel = store.panels.get(panel_id)
    if panel is None:
        raise err("ERR_FK_NOT_FOUND", "panel_id not found")

    # A plan cannot be authored for an INACTIVE patient (PRD 3.3).
    if patient["status"] != "ACTIVE":
        raise err("ERR_PATIENT_INACTIVE", "Patient is INACTIVE")
    # Panel must be FINALIZED before a plan may reference it (PRD 3.2/3.3).
    if panel["status"] != "FINALIZED":
        raise err("ERR_PANEL_NOT_FINALIZED", "Panel is not FINALIZED")

    starting_color = calc.TIER_TO_COLOR[panel["recommended_tier"]]
    plan = {
        "id": store.new_id(),
        "patient_id": patient_id,
        "panel_id": panel_id,
        "starting_vial_color": starting_color,
        "current_vial_color": starting_color,
        "current_step_index": 1,
        "phase": "BUILD_UP",
        "last_dose_volume_ml": 0,
        "status": "DRAFT",
        # internal flag: a reduced re-entry dose overrides the next schedule lookup.
        "_reentry_override_ml": None,
    }
    stamp_create(plan)
    store.plans[plan["id"]] = plan
    return object_response(serialize.plan(plan), 201)


@app.route("/immunotherapy-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    auth_and_role({"Allergist", "Nurse", "Pharmacist", "Biller", "FrontDesk"})
    p = get_plan_or_404(plan_id)
    return object_response(serialize.plan(p), 200)


@app.route("/immunotherapy-plans", methods=["GET"])
def list_plans():
    auth_and_role({"Allergist", "Nurse", "Pharmacist", "Biller", "FrontDesk"})
    limit, offset = parse_pagination(request.args)
    items = list(store.plans.values())
    patient_id = request.args.get("patient_id")
    panel_id = request.args.get("panel_id")
    status = request.args.get("status")
    if patient_id is not None:
        items = [p for p in items if p["patient_id"] == patient_id]
    if panel_id is not None:
        items = [p for p in items if p["panel_id"] == panel_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.plan(p) for p in page], limit, offset, total)


@app.route("/immunotherapy-plans/<plan_id>/activate", methods=["POST"])
def activate_plan(plan_id):
    auth_and_role({"Allergist"})
    plan = get_plan_or_404(plan_id)

    # State (priority 6): must be DRAFT.
    if plan["status"] != "DRAFT":
        raise err("ERR_PLAN_NOT_DRAFT", "Plan is not DRAFT")
    panel = store.panels.get(plan["panel_id"])
    if panel is None or panel["status"] != "FINALIZED":
        raise err("ERR_PANEL_NOT_FINALIZED", "Panel is not FINALIZED")
    patient = store.patients.get(plan["patient_id"])
    if patient is None or patient["status"] != "ACTIVE":
        raise err("ERR_PATIENT_INACTIVE", "Patient is INACTIVE")
    # At least one IN_USE vial of starting_vial_color (PRD 3.3).
    if not services._has_in_use_vial_of_color(plan_id, plan["starting_vial_color"]):
        raise err("ERR_NO_STARTING_VIAL", "No IN_USE vial of starting_vial_color")

    plan["current_vial_color"] = plan["starting_vial_color"]
    plan["current_step_index"] = 1
    plan["phase"] = "BUILD_UP"
    plan["status"] = "ACTIVE"
    touch(plan)
    return object_response(serialize.plan(plan), 200)


@app.route("/immunotherapy-plans/<plan_id>/resume", methods=["POST"])
def resume_plan(plan_id):
    auth_and_role({"Allergist"})
    plan = get_plan_or_404(plan_id)
    body = get_body()
    # OCC guard applied defensively (priority 5 / PRD 2.6).
    check_plan_version(plan, body)

    # State (priority 6): must be HELD.
    if plan["status"] != "HELD":
        raise err("ERR_PLAN_NOT_HELD", "Plan is not HELD")
    patient = store.patients.get(plan["patient_id"])
    # epinephrine_on_file required (priority 7).
    if patient is None or not patient.get("epinephrine_on_file"):
        raise err("ERR_EPINEPHRINE_NOT_ON_FILE", "Patient epinephrine not on file")

    # Reaction reduction (PRD 3.8): reduced re-entry volume overrides the next
    # schedule lookup; ladder steps back one rung.
    reduced = calc.reduced_reentry_volume(plan["last_dose_volume_ml"])
    calc.step_back_ladder(plan)
    plan["_reentry_override_ml"] = reduced

    plan["status"] = "ACTIVE"
    touch(plan)
    return object_response(serialize.plan(plan), 200)


@app.route("/immunotherapy-plans/<plan_id>/complete", methods=["POST"])
def complete_plan(plan_id):
    auth_and_role({"Allergist"})
    plan = get_plan_or_404(plan_id)

    # State (priority 6): must be ACTIVE.
    if plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Plan is not ACTIVE")
    if plan["phase"] != "MAINTENANCE":
        raise err("ERR_NOT_AT_MAINTENANCE", "Plan phase is not MAINTENANCE")
    # No open (ADMINISTERED) visit on this plan.
    for v in store.visits.values():
        if v["plan_id"] == plan_id and v["status"] == "ADMINISTERED":
            raise err("ERR_OPEN_VISIT_EXISTS", "An open shot visit exists")

    plan["status"] = "COMPLETED"
    touch(plan)
    return object_response(serialize.plan(plan), 200)


@app.route("/immunotherapy-plans/<plan_id>/discontinue", methods=["POST"])
def discontinue_plan(plan_id):
    auth_and_role({"Allergist"})
    plan = get_plan_or_404(plan_id)

    # State (priority 6): only ACTIVE or HELD may be discontinued.
    if plan["status"] not in ("ACTIVE", "HELD"):
        raise err("ERR_PLAN_NOT_DISCONTINUABLE", "Plan is not ACTIVE/HELD")

    plan["status"] = "DISCONTINUED"
    touch(plan)
    # Cascade: discard IN_USE vials, reconcile their 95165 entries (PRD 3.7).
    services.cascade_plan_discontinue(plan)
    return object_response(serialize.plan(plan), 200)


# =============================================================================
# Serum lots
# =============================================================================
@app.route("/serum-lots", methods=["POST"])
def create_lot():
    auth_and_role({"Pharmacist"})
    body = get_body()
    vial_color = require_enum(body, "vial_color", {"GREEN", "YELLOW", "RED", "SILVER"})
    lot_number = require_str(body, "lot_number")
    potency = require_number(body, "concentrate_potency_pnu_per_ml", positive=True)
    received_at_iso = require_str(body, "received_at_iso")

    # lot_number unique among non-RECALLED lots (priority 15).
    for l in store.lots.values():
        if l["status"] != "RECALLED" and l["lot_number"] == lot_number:
            raise err("ERR_DUPLICATE_LOT_NUMBER", "lot_number collides with an existing non-recalled lot")

    lot = {
        "id": store.new_id(),
        "vial_color": vial_color,
        "lot_number": lot_number,
        "concentrate_potency_pnu_per_ml": potency,
        "received_at_iso": received_at_iso,
        "status": "AVAILABLE",
    }
    stamp_create(lot)
    store.lots[lot["id"]] = lot
    return object_response(serialize.lot(lot), 201)


@app.route("/serum-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    auth_and_role({"Pharmacist", "Allergist", "Nurse"})
    l = get_lot_or_404(lot_id)
    return object_response(serialize.lot(l), 200)


@app.route("/serum-lots", methods=["GET"])
def list_lots():
    auth_and_role({"Pharmacist", "Allergist", "Nurse"})
    limit, offset = parse_pagination(request.args)
    items = list(store.lots.values())
    status = request.args.get("status")
    vial_color = request.args.get("vial_color")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if vial_color is not None:
        items = [l for l in items if l["vial_color"] == vial_color]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.lot(l) for l in page], limit, offset, total)


@app.route("/serum-lots/<lot_id>/recall", methods=["POST"])
def recall_lot(lot_id):
    auth_and_role({"Pharmacist"})
    lot = get_lot_or_404(lot_id)
    # State (priority 6): lot must be AVAILABLE.
    if lot["status"] != "AVAILABLE":
        raise err("ERR_LOT_NOT_AVAILABLE", "Lot is not AVAILABLE")
    lot["status"] = "RECALLED"
    touch(lot)
    services.cascade_lot_recall(lot)
    return object_response(serialize.lot(lot), 200)


# =============================================================================
# Serum vials (mixing)
# =============================================================================
@app.route("/immunotherapy-plans/<plan_id>/vials", methods=["POST"])
def mix_vial(plan_id):
    auth_and_role({"Pharmacist"})
    plan = get_plan_or_404(plan_id)
    body = get_body()
    lot_id = require_str(body, "lot_id")
    prepared_volume_ml = require_number(body, "prepared_volume_ml", positive=True)

    # FK existence (priority 4).
    lot = store.lots.get(lot_id)
    if lot is None:
        raise err("ERR_FK_NOT_FOUND", "lot_id not found")

    # OCC guard (priority 5).
    check_plan_version(plan, body)

    # Lot must be AVAILABLE (state).
    if lot["status"] != "AVAILABLE":
        raise err("ERR_LOT_NOT_AVAILABLE", "Lot is not AVAILABLE")

    color = lot["vial_color"]
    mixed_at = store.clock.now()
    bud = LogicalClock.add_days(mixed_at, calc.SHELF_LIFE_DAYS[color])

    vial = {
        "id": store.new_id(),
        "plan_id": plan_id,
        "lot_id": lot_id,
        "vial_color": color,
        "dilution_factor": float(calc.DILUTION_BY_COLOR[color]),
        "prepared_volume_ml": prepared_volume_ml,
        "remaining_volume_ml": calc.round2(prepared_volume_ml),
        "shelf_life_days": calc.SHELF_LIFE_DAYS[color],
        "beyond_use_date_iso": LogicalClock.format_ms(bud),
        "mixed_at_iso": store.clock.now_iso_ms(),
        "needs_refill": Decimal(str(prepared_volume_ml)) < Decimal("1.0"),
        "status": "IN_USE",
    }
    stamp_create(vial)
    store.vials[vial["id"]] = vial

    # PROVISIONAL CPT_95165 billing entry (PRD 3.9).
    units = calc.provisional_95165_units(prepared_volume_ml)
    entry = {
        "id": store.new_id(),
        "visit_id": None,
        "vial_id": vial["id"],
        "patient_id": plan["patient_id"],
        "cpt_code": "CPT_95165",
        "billed_dose_units": units,
        "charge_cents": units * calc.PRICE_95165_PER_DOSE_CENTS,
        "variant": "PROVISIONAL",
        "status": "POSTED",
    }
    stamp_create(entry)
    store.billing_entries[entry["id"]] = entry

    # Mixing increments the owning plan's version (PRD 3.5).
    touch(plan)
    return object_response(serialize.vial(vial), 201)


@app.route("/serum-vials/<vial_id>", methods=["GET"])
def get_vial(vial_id):
    auth_and_role({"Pharmacist", "Nurse", "Allergist"})
    v = get_vial_or_404(vial_id)
    return object_response(serialize.vial(v), 200)


@app.route("/serum-vials", methods=["GET"])
def list_vials():
    auth_and_role({"Pharmacist", "Nurse", "Allergist"})
    limit, offset = parse_pagination(request.args)
    items = list(store.vials.values())
    plan_id = request.args.get("plan_id")
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    if plan_id is not None:
        items = [v for v in items if v["plan_id"] == plan_id]
    if lot_id is not None:
        items = [v for v in items if v["lot_id"] == lot_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.vial(v) for v in page], limit, offset, total)


# =============================================================================
# Shot visits
# =============================================================================
@app.route("/immunotherapy-plans/<plan_id>/shot-visits", methods=["POST"])
def administer_shot(plan_id):
    auth_and_role({"Nurse"})
    plan = get_plan_or_404(plan_id)
    body = get_body()
    vial_id = require_str(body, "vial_id")
    injection_count = optional_int(body, "injection_count", default=1, minimum=1)

    # FK existence (priority 4).
    vial = store.vials.get(vial_id)
    if vial is None:
        raise err("ERR_FK_NOT_FOUND", "vial_id not found")

    # OCC guard (priority 5).
    check_plan_version(plan, body)

    # Plan state (priority 6): must be ACTIVE; HELD specifically -> ERR_PLAN_HELD.
    if plan["status"] == "HELD":
        raise err("ERR_PLAN_HELD", "Plan is HELD")
    if plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Plan is not ACTIVE")

    # Vial belongs to the plan named in the path (priority 14).
    if vial["plan_id"] != plan_id:
        raise err("ERR_VIAL_PLAN_MISMATCH", "Vial does not belong to this plan")

    # Vial usability (priority 9): IN_USE, not expired, lot not RECALLED.
    lot = store.lots.get(vial["lot_id"])
    if vial["status"] != "IN_USE":
        raise err("ERR_VIAL_NOT_USABLE", "Vial is not usable")
    bud = LogicalClock.parse(vial["beyond_use_date_iso"])
    if store.clock.now() >= bud:
        raise err("ERR_VIAL_NOT_USABLE", "Vial is expired")
    if lot is None or lot["status"] != "AVAILABLE":
        raise err("ERR_VIAL_NOT_USABLE", "Backing lot is recalled")

    # SILVER (maintenance concentration) requires epinephrine_on_file (priority 7).
    patient = store.patients.get(plan["patient_id"])
    if vial["vial_color"] == "SILVER" and not (patient and patient.get("epinephrine_on_file")):
        raise err("ERR_EPINEPHRINE_NOT_ON_FILE", "Patient epinephrine not on file")

    # Determine scheduled / administered dose.
    reentry = plan.get("_reentry_override_ml")
    scheduled = calc.scheduled_dose(plan["current_vial_color"], plan["current_step_index"], plan["phase"])
    if reentry is not None:
        # Reduced re-entry dose overrides the schedule lookup for this first
        # visit after resume (PRD 3.8).
        administered = reentry
    else:
        administered = scheduled

    # Vial volume check (priority 16): scheduled draw must not exceed remaining.
    draw = Decimal(str(administered))
    remaining = Decimal(str(vial["remaining_volume_ml"]))
    if draw > remaining:
        # Vial closes to EXHAUSTED on insufficient volume (PRD 3.5/3.6).
        services.close_vial(vial, "EXHAUSTED")
        raise err("ERR_VIAL_INSUFFICIENT_VOLUME", "Scheduled draw exceeds remaining volume")

    # Compute antigen units (round once at end).
    antigen = calc.antigen_units(administered, vial["vial_color"], lot["concentrate_potency_pnu_per_ml"])
    # Observation window: escalation compares the scheduled step volume to last dose.
    obs = calc.observation_window(
        patient.get("prior_systemic_reaction", False),
        scheduled,
        plan["last_dose_volume_ml"],
    )

    visit = {
        "id": store.new_id(),
        "plan_id": plan_id,
        "vial_id": vial_id,
        "scheduled_dose_volume_ml": calc.round2(scheduled),
        "administered_volume_ml": calc.round2(administered),
        "antigen_units_delivered": antigen,
        "injection_count": injection_count,
        "administered_at_iso": store.clock.now_iso_ms(),
        "observation_window_min": obs,
        "released_at_iso": None,
        "reaction_grade": None,
        "epinephrine_administered": False,
        "status": "ADMINISTERED",
    }
    stamp_create(visit)
    store.visits[visit["id"]] = visit

    # The re-entry override is consumed by this administration.
    if reentry is not None:
        plan["_reentry_override_ml"] = None

    # Provisionally debit the vial (PRD 3.6).
    services.recompute_vial_remaining(vial)
    touch(vial)

    # PROVISIONAL injection billing entry (PRD 3.9).
    cpt, charge = calc.injection_charge(injection_count)
    entry = {
        "id": store.new_id(),
        "visit_id": visit["id"],
        "vial_id": None,
        "patient_id": plan["patient_id"],
        "cpt_code": cpt,
        "billed_dose_units": 1,
        "charge_cents": charge,
        "variant": "PROVISIONAL",
        "status": "POSTED",
    }
    stamp_create(entry)
    store.billing_entries[entry["id"]] = entry

    # Administration increments the owning plan's version (PRD 3.6).
    touch(plan)
    return object_response(serialize.visit(visit), 201)


@app.route("/shot-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    auth_and_role({"Nurse", "Allergist", "Biller", "FrontDesk"})
    v = get_visit_or_404(visit_id)
    return object_response(serialize.visit(v), 200)


@app.route("/shot-visits", methods=["GET"])
def list_visits():
    auth_and_role({"Nurse", "Allergist", "Biller", "FrontDesk"})
    limit, offset = parse_pagination(request.args)
    items = list(store.visits.values())
    plan_id = request.args.get("plan_id")
    vial_id = request.args.get("vial_id")
    status = request.args.get("status")
    if plan_id is not None:
        items = [v for v in items if v["plan_id"] == plan_id]
    if vial_id is not None:
        items = [v for v in items if v["vial_id"] == vial_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.visit(v) for v in page], limit, offset, total)


@app.route("/shot-visits/<visit_id>/release", methods=["POST"])
def release_visit(visit_id):
    auth_and_role({"Nurse"})
    visit = get_visit_or_404(visit_id)
    body = get_body()
    released_at_iso = require_str(body, "released_at_iso")
    reaction_grade = optional_enum(body, "reaction_grade", {"NONE", "LOCAL", "SYSTEMIC"}, default="NONE")

    # State (priority 6): must be ADMINISTERED.
    if visit["status"] != "ADMINISTERED":
        raise err("ERR_VISIT_NOT_ADMINISTERED", "Visit is not ADMINISTERED")
    # Grade must be NONE for release (priority 13).
    if reaction_grade != "NONE":
        raise err("ERR_REACTION_GRADE_MISMATCH", "Release expects reaction_grade NONE")

    # Observation window (priority 12): released_at >= administered_at + window.
    try:
        released_dt = LogicalClock.parse(released_at_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "released_at_iso must be a valid ISO 8601 timestamp")
    administered_dt = LogicalClock.parse(visit["administered_at_iso"])
    earliest = administered_dt + timedelta(minutes=visit["observation_window_min"])
    if released_dt < earliest:
        raise err("ERR_OBSERVATION_NOT_ELAPSED", "Observation window has not fully elapsed")

    visit["released_at_iso"] = released_at_iso
    visit["reaction_grade"] = "NONE"
    visit["status"] = "RELEASED"
    touch(visit)

    plan = store.plans.get(visit["plan_id"])
    vial = store.vials.get(visit["vial_id"])
    if plan is not None:
        plan["last_dose_volume_ml"] = visit["administered_volume_ml"]
        calc.advance_ladder(plan)
        touch(plan)
    # Resolved draw is now reflected; recompute vial remaining/needs_refill.
    if vial is not None:
        services.recompute_vial_remaining(vial)
        touch(vial)

    return object_response(serialize.visit(visit), 200)


@app.route("/shot-visits/<visit_id>/record-reaction", methods=["POST"])
def record_reaction(visit_id):
    auth_and_role({"Nurse"})
    visit = get_visit_or_404(visit_id)
    body = get_body()
    reaction_grade = require_enum(body, "reaction_grade", {"NONE", "LOCAL", "SYSTEMIC"})
    epinephrine_administered = optional_bool(body, "epinephrine_administered", default=False)

    # State (priority 6): must be ADMINISTERED.
    if visit["status"] != "ADMINISTERED":
        raise err("ERR_VISIT_NOT_ADMINISTERED", "Visit is not ADMINISTERED")
    # Grade must be LOCAL or SYSTEMIC for record-reaction (priority 13).
    if reaction_grade not in ("LOCAL", "SYSTEMIC"):
        raise err("ERR_REACTION_GRADE_MISMATCH", "record-reaction expects LOCAL or SYSTEMIC")

    plan = store.plans.get(visit["plan_id"])
    vial = store.vials.get(visit["vial_id"])

    if reaction_grade == "LOCAL":
        visit["reaction_grade"] = "LOCAL"
        visit["epinephrine_administered"] = epinephrine_administered
        visit["status"] = "REACTION_LOCAL"
        touch(visit)
        # Plan does NOT advance; step repeats next visit (PRD 3.6/3.8).
        if plan is not None:
            plan["last_dose_volume_ml"] = visit["administered_volume_ml"]
            touch(plan)
        if vial is not None:
            services.recompute_vial_remaining(vial)
            touch(vial)
        return object_response(serialize.visit(visit), 200)

    # SYSTEMIC: epinephrine_administered must be true (priority 8).
    if not epinephrine_administered:
        raise err("ERR_EPINEPHRINE_REQUIRED", "Systemic reaction requires epinephrine_administered=true")

    visit["reaction_grade"] = "SYSTEMIC"
    visit["epinephrine_administered"] = True
    visit["status"] = "REACTION_SYSTEMIC"
    touch(visit)

    # Cascade hop 1: plan ACTIVE -> HELD.
    if plan is not None:
        if plan["status"] == "ACTIVE":
            plan["status"] = "HELD"
        plan["last_dose_volume_ml"] = visit["administered_volume_ml"]
        touch(plan)

    # Cascade hop 2: this visit's PROVISIONAL injection entry -> REVERSED.
    for b in store.billing_entries.values():
        if (b.get("visit_id") == visit["id"]
                and b["cpt_code"] in ("CPT_95115", "CPT_95117")
                and b["status"] == "POSTED"):
            b["status"] = "REVERSED"
            touch(b)

    # Cascade hop 3: patient.prior_systemic_reaction = true.
    patient = store.patients.get(plan["patient_id"]) if plan else None
    if patient is not None:
        patient["prior_systemic_reaction"] = True
        touch(patient)

    # The resolved draw is now reflected; recompute vial remaining/needs_refill.
    if vial is not None:
        services.recompute_vial_remaining(vial)
        touch(vial)

    return object_response(serialize.visit(visit), 200)


# =============================================================================
# Billing
# =============================================================================
@app.route("/billing-entries/<entry_id>", methods=["GET"])
def get_billing_entry(entry_id):
    auth_and_role({"Biller", "Allergist"})
    b = store.billing_entries.get(entry_id)
    if b is None:
        raise err("ERR_NOT_FOUND", "Billing entry not found")
    return object_response(serialize.billing_entry(b), 200)


@app.route("/billing-entries", methods=["GET"])
def list_billing_entries():
    auth_and_role({"Biller", "Allergist"})
    limit, offset = parse_pagination(request.args)
    items = list(store.billing_entries.values())
    visit_id = request.args.get("visit_id")
    vial_id = request.args.get("vial_id")
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    cpt_code = request.args.get("cpt_code")
    if visit_id is not None:
        items = [b for b in items if b.get("visit_id") == visit_id]
    if vial_id is not None:
        items = [b for b in items if b.get("vial_id") == vial_id]
    if patient_id is not None:
        items = [b for b in items if b.get("patient_id") == patient_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if cpt_code is not None:
        items = [b for b in items if b["cpt_code"] == cpt_code]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.billing_entry(b) for b in page], limit, offset, total)


@app.route("/patients/<patient_id>/billing-summary", methods=["GET"])
def billing_summary(patient_id):
    auth_and_role({"Biller", "Allergist"})
    get_patient_or_404(patient_id)
    entries = [b for b in store.billing_entries.values() if b.get("patient_id") == patient_id]
    billed_total = 0
    reversed_total = 0
    by_cpt = {}
    for b in entries:
        if b["status"] == "REVERSED":
            reversed_total += b["charge_cents"]
            continue
        billed_total += b["charge_cents"]
        by_cpt[b["cpt_code"]] = by_cpt.get(b["cpt_code"], 0) + b["charge_cents"]
    return object_response({
        "patient_id": patient_id,
        "billed_total_cents": billed_total,
        "reversed_total_cents": reversed_total,
        "by_cpt": by_cpt,
    }, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
