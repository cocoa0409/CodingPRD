"""Leaf-lot intake, sensory grading, residue testing loop, release/recall
(PRD 3.1, 3.2)."""
from flask import Blueprint

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOT_NOT_RELEASABLE,
    ERR_MOISTURE_OUT_OF_RANGE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SUPPLIER_SUSPENDED,
    raise_err,
)
from services import (
    LEAF_TYPES,
    LOT_TERMINAL_STATES,
    RELEASE_MOISTURE_GATE_PCT,
    allocation_out,
    assessment_out,
    compute_composite,
    compute_verdict,
    hold_batches_for_lot,
    latest_residue_test,
    lot_out,
    residue_test_out,
)
from util import (
    body_json, bump, get_or_404, list_response, new_immutable_record,
    new_record, req_date, req_enum, req_int, req_num, req_str, success_object,
)

bp = Blueprint("leaf_lots", __name__)


def _lot_or_404(lot_id):
    return get_or_404(store.leaf_lots, lot_id, "LeafLot")


def _guard_lot_terminal(lot):
    if lot["status"] in LOT_TERMINAL_STATES:
        raise_err(
            ERR_ALREADY_TERMINAL,
            "LeafLot %s is in terminal state %s" % (lot["id"], lot["status"]),
        )


@bp.route("/tea-ops/leaf-lots", methods=["POST"])
def create_lot():
    uid, role = authenticate()
    authorize(role, ["ProcurementLead"])
    body = body_json()
    # Priority 3: body FK resolution (supplier_id) when present.
    supplier_id = body.get("supplier_id")
    supplier = None
    if supplier_id is not None:
        supplier = get_or_404(store.suppliers, supplier_id, "Supplier")

    # Priority 13: field shape.
    if not isinstance(supplier_id, str) or not supplier_id:
        raise_err(ERR_INVALID_REQUEST, "supplier_id is required and must be a string")
    leaf_type = req_enum(body, "leaf_type", LEAF_TYPES)
    harvest_date = req_date(body, "harvest_date")
    weight_kg = req_num(body, "weight_kg")
    if weight_kg <= 0:
        raise_err(ERR_INVALID_REQUEST, "weight_kg must be strictly positive")
    cost_per_kg_cents = req_int(body, "cost_per_kg_cents")
    if cost_per_kg_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "cost_per_kg_cents must be >= 0")
    moisture_pct = req_num(body, "moisture_pct")
    if moisture_pct <= 0 or moisture_pct > 100:
        raise_err(ERR_INVALID_REQUEST, "moisture_pct must be > 0 and <= 100")

    rec = new_record()
    rec.update({
        "supplier_id": supplier["id"],
        "leaf_type": leaf_type,
        "harvest_date": harvest_date,
        "weight_kg": weight_kg,
        "cost_per_kg_cents": cost_per_kg_cents,
        "moisture_pct": moisture_pct,
        "remaining_weight_kg": weight_kg,
        "registered_by_user_id": uid,
        "composite_grade": "NONE",
        "latest_residue_verdict": "NONE",
        "status": "REGISTERED",
    })
    store.leaf_lots[rec["id"]] = rec
    return success_object(lot_out(rec), 201)


@bp.route("/tea-ops/leaf-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(lot_out(_lot_or_404(lot_id)))


@bp.route("/tea-ops/leaf-lots", methods=["GET"])
def list_lots():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    from flask import request
    records = list(store.leaf_lots.values())
    supplier_id = request.args.get("supplier_id")
    leaf_type = request.args.get("leaf_type")
    status = request.args.get("status")
    if supplier_id is not None:
        records = [r for r in records if r["supplier_id"] == supplier_id]
    if leaf_type is not None:
        records = [r for r in records if r["leaf_type"] == leaf_type]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, lot_out)


@bp.route("/tea-ops/leaf-lots/<lot_id>/grade-assessments", methods=["POST"])
def create_grade_assessment(lot_id):
    uid, role = authenticate()
    authorize(role, ["SensoryGrader"])
    lot = _lot_or_404(lot_id)
    _guard_lot_terminal(lot)
    if lot["status"] != "REGISTERED":
        raise_err(ERR_INVALID_STATE, "LeafLot is not REGISTERED")
    # Priority 7: segregation of duties — grader != registrar.
    if uid == lot["registered_by_user_id"]:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "Grader must differ from the operator who registered the lot",
        )
    # Priority 13: field shape.
    body = body_json()
    aroma = body.get("aroma_score")
    briskness = body.get("briskness_score")
    appearance = body.get("appearance_score")
    for key, v in (("aroma_score", aroma), ("briskness_score", briskness),
                   ("appearance_score", appearance)):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 100:
            raise_err(ERR_INVALID_REQUEST, "%s must be an integer in 0..100" % key)

    score, grade = compute_composite(aroma, briskness, appearance)
    rec = new_immutable_record()
    rec.update({
        "lot_id": lot["id"],
        "grader_user_id": uid,
        "aroma_score": aroma,
        "briskness_score": briskness,
        "appearance_score": appearance,
        "composite_score": score,
        "composite_grade": grade,
    })
    store.grade_assessments[rec["id"]] = rec

    lot["composite_grade"] = grade
    lot["status"] = "REJECTED" if grade == "REJECT" else "GRADED"
    bump(lot)
    return success_object(assessment_out(rec), 201)


@bp.route("/tea-ops/leaf-lots/<lot_id>/grade-assessments", methods=["GET"])
def list_grade_assessments(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    lot = _lot_or_404(lot_id)
    records = [a for a in store.grade_assessments.values()
               if a["lot_id"] == lot["id"]]
    return list_response(records, assessment_out)


@bp.route("/tea-ops/leaf-lots/<lot_id>/residue-tests", methods=["POST"])
def create_residue_test(lot_id):
    uid, role = authenticate()
    authorize(role, ["QALabAnalyst"])
    lot = _lot_or_404(lot_id)
    _guard_lot_terminal(lot)
    if lot["status"] not in ("GRADED", "ON_HOLD"):
        raise_err(
            ERR_INVALID_STATE,
            "Residue tests require a GRADED or ON_HOLD lot",
        )
    # Priority 13: field shape.
    body = body_json()
    lab_name = req_str(body, "lab_name")
    test_method = req_str(body, "test_method")
    ppm = req_num(body, "measured_residue_ppm")
    if ppm < 0:
        raise_err(ERR_INVALID_REQUEST, "measured_residue_ppm must be >= 0")

    verdict = compute_verdict(ppm)
    prior_rounds = len([t for t in store.residue_tests.values()
                        if t["lot_id"] == lot["id"]])
    rec = new_immutable_record()
    rec.update({
        "lot_id": lot["id"],
        "lab_name": lab_name,
        "measured_residue_ppm": ppm,
        "test_method": test_method,
        "submitted_by_user_id": uid,
        "verdict": verdict,
        "test_round": prior_rounds + 1,
    })
    store.residue_tests[rec["id"]] = rec

    entered_hold = False
    if verdict == "PASS":
        lot["status"] = "LAB_SUBMITTED"
    elif verdict == "FAIL_SOFT":
        if lot["status"] != "ON_HOLD":
            entered_hold = True
        lot["status"] = "ON_HOLD"
    else:  # FAIL_HARD
        lot["status"] = "REJECTED"
    lot["latest_residue_verdict"] = verdict
    bump(lot)

    if entered_hold:
        # Soft fail: cascade links 2 and 3 fire as in supplier suspend.
        hold_batches_for_lot(lot)
    return success_object(residue_test_out(rec), 201)


@bp.route("/tea-ops/leaf-lots/<lot_id>/residue-tests", methods=["GET"])
def list_residue_tests(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    lot = _lot_or_404(lot_id)
    records = [t for t in store.residue_tests.values() if t["lot_id"] == lot["id"]]
    return list_response(records, residue_test_out)


@bp.route("/tea-ops/leaf-lots/<lot_id>/release", methods=["POST"])
def release_lot(lot_id):
    uid, role = authenticate()
    authorize(role, ["QAManager"])
    lot = _lot_or_404(lot_id)
    _guard_lot_terminal(lot)
    # Priority 6: endpoint state preconditions.
    if lot["status"] != "LAB_SUBMITTED" or lot["latest_residue_verdict"] != "PASS":
        raise_err(
            ERR_LOT_NOT_RELEASABLE,
            "Lot is not LAB_SUBMITTED with a passing latest residue verdict",
        )
    supplier = store.suppliers.get(lot["supplier_id"])
    if supplier is not None and supplier["status"] != "ACTIVE":
        raise_err(ERR_SUPPLIER_SUSPENDED, "The lot's supplier is SUSPENDED")
    # Priority 7: segregation of duties vs latest residue-test submitter.
    latest = latest_residue_test(lot["id"])
    if latest is not None and uid == latest["submitted_by_user_id"]:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "Releaser must differ from the latest residue-test submitter",
        )
    # Priority 8: moisture gate.
    if lot["moisture_pct"] > RELEASE_MOISTURE_GATE_PCT:
        raise_err(
            ERR_MOISTURE_OUT_OF_RANGE,
            "Lot moisture_pct exceeds the 7.0 release gate",
        )
    lot["status"] = "RELEASED"
    bump(lot)
    return success_object(lot_out(lot))


@bp.route("/tea-ops/leaf-lots/<lot_id>/recall", methods=["POST"])
def recall_lot(lot_id):
    _, role = authenticate()
    authorize(role, ["QAManager"])
    lot = _lot_or_404(lot_id)
    _guard_lot_terminal(lot)
    if lot["status"] != "RELEASED":
        raise_err(ERR_INVALID_STATE, "Only a RELEASED lot can be recalled")
    lot["status"] = "ON_HOLD"
    bump(lot)
    # Cascade links 2 and 3.
    hold_batches_for_lot(lot)
    return success_object(lot_out(lot))


@bp.route("/tea-ops/leaf-lots/<lot_id>/allocations", methods=["GET"])
def list_lot_allocations(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    lot = _lot_or_404(lot_id)
    records = [a for a in store.allocations.values() if a["lot_id"] == lot["id"]]
    return list_response(records, allocation_out)
