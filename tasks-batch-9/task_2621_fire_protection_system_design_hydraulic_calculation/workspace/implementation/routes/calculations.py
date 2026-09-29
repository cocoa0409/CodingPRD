"""Hydraulic calculations: creation, QC disposition and the engineer's seal (PRD 3.3, 3.6)."""
from flask import Blueprint

import calc_hazard
import clock
import db
import guards
import helpers
import ledger
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from utils import _dec, rhu

bp = Blueprint("calculations", __name__)

CALC_STATES = [
    "DRAFT",
    "ITERATING",
    "CONVERGED",
    "PRESSURE_DEFICIENT",
    "QC_PASSED",
    "SEALED",
    "REOPENED",
    "ARCHIVED",
]
QC_DISPOSITIONS = ["PASS", "REJECT"]


def newest_evaluated_evaluation(project_id):
    rows = [
        e
        for e in db.evaluations.values()
        if e["project_id"] == project_id and e["state"] == "EVALUATED"
    ]
    if not rows:
        return None
    return db.by_created(rows)[-1]


@bp.post("/hydraulic-calculations")
def create_calculation():
    actor = authenticate(["DesignEngineer"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    area = guards.must_fk("hazard_area", validate.raw_fk(data, "hazard_area_id"))
    guards.require_lead_engineer(actor, project)
    row = {
        "project_id": validate.req_str(data, "project_id"),
        "hazard_area_id": validate.req_str(data, "hazard_area_id"),
        "authored_by_engineer_id": actor.user_id,
        "qc_reviewed_by_engineer_id": None,
        "sealed_by_engineer_id": None,
        "reopened_by_submittal_id": None,
        "method": validate.req_str(data, "method", enum=calc_hazard.METHODS),
        "k_factor": validate.req_num(data, "k_factor", gt=0),
    }
    guards.require_not_frozen(project)
    if row["method"] == "ROOM_DESIGN" and not calc_hazard.room_design_admissible(area):
        raise ApiError(
            "ERR_ROOM_DESIGN_NOT_PERMITTED",
            "The hazard area does not satisfy the ROOM_DESIGN admissibility conditions.",
        )
    row.update(calc_hazard.demand_snapshot(area, row["method"]))
    row.update(
        {
            "chain_start_index": 1,
            "iteration_count": 0,
            "end_head_psi": 0.0,
            "required_psi_at_base_of_riser": 0.0,
            "deficiency_psi": None,
            "stale_reason": None,
            "sealed_at": None,
            "state": "DRAFT",
        }
    )
    db.stamp_create(row)
    db.calculations[row["id"]] = row
    return response.created(response.public(row))


@bp.get("/hydraulic-calculations/<calc_id>")
def get_calculation(calc_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("calculation", calc_id)))


@bp.get("/hydraulic-calculations")
def list_calculations():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.calculations.values()),
        [
            "project_id",
            "hazard_area_id",
            "authored_by_engineer_id",
            "qc_reviewed_by_engineer_id",
            "sealed_by_engineer_id",
            "reopened_by_submittal_id",
            "state",
            "method",
        ],
    )
    return helpers.list_response(rows)


@bp.post("/hydraulic-calculations/<calc_id>/qc-review")
def qc_review(calc_id):
    actor = authenticate(["QcReviewer"])
    calc = guards.must("calculation", calc_id)
    project = guards.must("project", calc["project_id"])
    guards.require_segregation(actor, calc)
    data = validate.body()
    disposition = validate.req_str(data, "disposition", enum=QC_DISPOSITIONS)
    validate.opt_str(data, "review_note")
    guards.require_not_frozen(project)
    if calc["state"] == "ARCHIVED":
        guards.terminal("The calculation is ARCHIVED and may not be dispositioned.")
    if calc["state"] != "CONVERGED":
        guards.invalid_transition(
            "Only a CONVERGED calculation may be QC-dispositioned."
        )

    before_project = db.snapshot(project)
    calc["qc_reviewed_by_engineer_id"] = actor.user_id
    if disposition == "PASS":
        calc["state"] = "QC_PASSED"
    else:
        calc["state"] = "ITERATING"
        calc["stale_reason"] = "QC_REJECTED"
    db.touch(calc)
    ledger.recompute_ledger(project)
    ledger.recompute_posture(project)
    db.touch_if_changed(project, before_project)
    return response.ok(response.public(calc))


def _require_margin_resolved(project, evaluation):
    """Seal check three: the safety margin is resolved (PRD 3.6)."""
    if evaluation is not None:
        if evaluation["margin_verdict"] != "INADEQUATE_PUMP_REQUIRED":
            return
        for pump in db.pumps.values():
            if (
                pump["water_supply_evaluation_id"] == evaluation["id"]
                and pump["state"] == "SIZED"
                and pump["sizing_verdict"] == "ACCEPTABLE"
            ):
                return
    raise ApiError(
        "ERR_SAFETY_MARGIN_UNRESOLVED",
        "The safety margin is not resolved by an adequate verdict or an acceptable sized pump.",
    )


def _require_evaluation_reconciles(project, calc, evaluation):
    """Seal check four: the reconciliation triple still agrees (PRD 3.6)."""
    stale = ApiError(
        "ERR_EVALUATION_REFERENCE_STALE",
        "The newest evaluated supply evaluation no longer reconciles with this calculation.",
    )
    if evaluation is None:
        raise stale
    if evaluation["pinned_calculation_iteration_count"] != calc["iteration_count"]:
        raise stale
    required = rhu(
        _dec(calc["required_psi_at_base_of_riser"])
        + _dec(project["underground_lead_in_loss_psi"]),
        2,
    )
    if _dec(evaluation["required_psi_at_demand"]) != _dec(required):
        raise stale
    if _dec(evaluation["design_demand_gpm"]) != _dec(project["total_system_demand_gpm"]):
        raise stale


@bp.post("/hydraulic-calculations/<calc_id>/seal")
def seal(calc_id):
    actor = authenticate(["DesignEngineer"])
    calc = guards.must("calculation", calc_id)
    project = guards.must("project", calc["project_id"])
    guards.require_lead_engineer(actor, project)
    if actor.user_id != calc["authored_by_engineer_id"]:
        raise ApiError(
            "ERR_NOT_PROJECT_ENGINEER",
            "Only the calculation's author may apply the seal.",
        )
    guards.require_not_frozen(project)
    guards.require_not_gated(project)
    if calc["state"] == "ARCHIVED":
        guards.terminal("The calculation is ARCHIVED and may not be sealed.")
    if calc["state"] != "QC_PASSED":
        guards.invalid_transition("Only a QC_PASSED calculation may be sealed.")

    engineer = db.engineers.get(actor.user_id)
    if engineer["license_status"] != "ACTIVE":
        raise ApiError(
            "ERR_SEAL_LICENSE_INACTIVE",
            "The sealing engineer's licence is not ACTIVE.",
        )
    if engineer["license_state"] != project["jurisdiction_state"]:
        raise ApiError(
            "ERR_SEAL_LICENSE_JURISDICTION_MISMATCH",
            "The sealing engineer's licence is not registered in the project's jurisdiction state.",
        )
    evaluation = newest_evaluated_evaluation(project["id"])
    _require_margin_resolved(project, evaluation)
    _require_evaluation_reconciles(project, calc, evaluation)

    calc["state"] = "SEALED"
    calc["sealed_by_engineer_id"] = actor.user_id
    calc["sealed_at"] = clock.now_iso()
    db.touch(calc)
    project["sealed_calculation_count"] = (project["sealed_calculation_count"] or 0) + 1
    ledger.recompute_ledger(project)
    ledger.recompute_posture(project)
    db.touch(project)
    return response.ok(response.public(calc))
