"""FormulaDispense routes (PRD 3.9) — request, fill (debit), reverse (restore)."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_fields,
    require_int_min,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_dispense, get_formula, get_patient, get_plan
from middleware import get_auth, require_role
from response import success

bp = Blueprint("dispenses", __name__)


@bp.route("/dispenses", methods=["POST"])
def request_dispense():
    _, role = get_auth()
    require_role(role, ["Pharmacist", "Practitioner"])
    body = get_json_body()
    require_fields(
        body,
        [
            "patient_id",
            "treatment_plan_id",
            "herbal_formula_id",
            "doses",
            "expected_treatment_plan_version",
        ],
    )
    # Priority 5: body FK existence.
    patient = get_patient(body["patient_id"])
    plan = get_plan(body["treatment_plan_id"])
    formula = get_formula(body["herbal_formula_id"])

    # Priority 6: well-formedness.
    doses = require_int_min(body, "doses", 1)
    expected = body.get("expected_treatment_plan_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_treatment_plan_version must be an integer.")

    # Priority 8: plan must be ACTIVE.
    if plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Dispense requires the plan to be ACTIVE.")

    # Priority 15: OCC on plan version.
    if expected != plan["version"]:
        raise err("ERR_STALE_VERSION", "expected_treatment_plan_version does not match.")

    rec = {
        "patient_id": patient["id"],
        "treatment_plan_id": plan["id"],
        "herbal_formula_id": formula["id"],
        "doses": doses,
        "total_grams_by_herb": {},
        "status": "REQUESTED",
    }
    stamp_new(rec)
    db.dispenses[rec["id"]] = rec
    # Requesting a dispense increments the referenced plan's version.
    touch(plan)
    return success(public(rec), status=201)


@bp.route("/dispenses", methods=["GET"])
def list_dispenses():
    user_id, role = get_auth()
    require_role(role, ["Pharmacist", "Practitioner", "ClinicAdmin", "Patient"])
    items = list(db.dispenses.values())
    if role == "Patient":
        items = [d for d in items if d["patient_id"] == user_id]
    else:
        pf = request.args.get("patient_id")
        if pf is not None:
            items = [d for d in items if d["patient_id"] == pf]
    tpf = request.args.get("treatment_plan_id")
    if tpf is not None:
        items = [d for d in items if d["treatment_plan_id"] == tpf]
    hff = request.args.get("herbal_formula_id")
    if hff is not None:
        items = [d for d in items if d["herbal_formula_id"] == hff]
    data, pg = paginate(items, public)
    return success(data, status=200, pagination=pg)


@bp.route("/dispenses/<rid>", methods=["GET"])
def get_dispense_route(rid):
    user_id, role = get_auth()
    require_role(role, ["Pharmacist", "Practitioner", "ClinicAdmin", "Patient"])
    rec = get_dispense(rid)
    if role == "Patient" and user_id != rec["patient_id"]:
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own dispenses.")
    return success(public(rec), status=200)


@bp.route("/dispenses/<rid>/fill", methods=["POST"])
def fill_dispense(rid):
    _, role = get_auth()
    require_role(role, ["Pharmacist"])
    rec = get_dispense(rid)
    # State precondition.
    if rec["status"] != "REQUESTED":
        raise err("ERR_DISPENSE_NOT_REQUESTED", "Fill requires status == REQUESTED.")
    # Governing plan must be ACTIVE.
    plan = db.treatment_plans.get(rec["treatment_plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Fill requires the governing plan to be ACTIVE.")

    formula = db.herbal_formulas.get(rec["herbal_formula_id"])
    doses = rec["doses"]

    # Compute the per-herb deductions (aggregating duplicate herb lines).
    deductions = {}
    for line in formula["line_items"]:
        herb_id = line["herb_item_id"]
        grams = line["grams_per_dose"] * doses
        deductions[herb_id] = deductions.get(herb_id, 0) + grams

    # Stock safety: every referenced herb must have enough on_hand. Check ALL
    # before any debit (atomicity).
    for herb_id, needed in deductions.items():
        herb = db.herb_items.get(herb_id)
        if herb is None or herb["on_hand_grams"] < needed:
            raise err(
                "ERR_INSUFFICIENT_STOCK",
                "Insufficient stock for a recipe line.",
            )

    # HOP-1: snapshot total_grams_by_herb.
    rec["total_grams_by_herb"] = dict(deductions)

    # HOP-2/HOP-3: debit each herb, then LOW_STOCK auto-flag.
    for herb_id, grams in deductions.items():
        herb = db.herb_items[herb_id]
        herb["on_hand_grams"] = herb["on_hand_grams"] - grams
        if herb["on_hand_grams"] <= herb["reorder_threshold_grams"]:
            herb["stock_status"] = "LOW_STOCK"
        else:
            herb["stock_status"] = "IN_STOCK"
        touch(herb)

    rec["status"] = "FILLED"
    touch(rec)
    return success(public(rec), status=200)


@bp.route("/dispenses/<rid>/reverse", methods=["POST"])
def reverse_dispense(rid):
    _, role = get_auth()
    require_role(role, ["Pharmacist"])
    rec = get_dispense(rid)
    body = get_json_body()
    # State precondition.
    if rec["status"] != "FILLED":
        raise err("ERR_DISPENSE_NOT_FILLED", "Reverse requires status == FILLED.")
    # OCC on the dispense's own version.
    require_fields(body, ["expected_formula_dispense_version"])
    expected = body.get("expected_formula_dispense_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_formula_dispense_version must be an integer.")
    if expected != rec["version"]:
        raise err("ERR_STALE_VERSION", "expected_formula_dispense_version does not match.")

    # Restore each herb by the grams recorded at fill (compensating restore).
    for herb_id, grams in rec["total_grams_by_herb"].items():
        herb = db.herb_items.get(herb_id)
        if herb is None:
            continue
        herb["on_hand_grams"] = herb["on_hand_grams"] + grams
        if herb["on_hand_grams"] > herb["reorder_threshold_grams"]:
            herb["stock_status"] = "IN_STOCK"
        else:
            herb["stock_status"] = "LOW_STOCK"
        touch(herb)

    rec["status"] = "REVERSED"
    touch(rec)
    return success(public(rec), status=200)
