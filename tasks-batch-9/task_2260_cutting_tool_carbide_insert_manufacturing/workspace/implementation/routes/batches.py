"""Powder blend batches: the blend / press / sinter route (PRD section 3.1)."""

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("batches", __name__)

READ_ROLES = [
    "MetallurgyEngineer",
    "ProductionPlanner",
    "QualityApprover",
    "ApplicationEngineer",
]


@bp.route("/tooling/powder-blend-batches", methods=["POST"])
def create():
    authenticate(["MetallurgyEngineer", "ProductionPlanner"])
    payload = v.body(required=("grade_id", "batch_code", "planned_mass_kg"))
    grade_id = v.as_id(payload, "grade_id")
    batch_code = v.as_string(payload, "batch_code")
    mass = v.as_number(payload, "planned_mass_kg", exclusive_min=0)

    grade = derive.must_exist("grades", grade_id)
    derive.require_unique("batches", "batch_code", batch_code)
    if grade["status"] == "RETIRED":
        raise ApiError(
            "ERR_INVALID_GRADE_STATE",
            "A blend batch cannot be opened against a RETIRED grade.",
        )

    row = db.new_row(
        {
            "grade_id": grade["id"],
            "batch_code": batch_code,
            "planned_mass_kg": mass,
            "pinned_grade_revision": grade["revision"],
            "stage": "BLENDED",
            "qc_status": "PENDING",
            "pressed_units": 0,
            "sintered_units": 0,
            "scrap_units": 0,
            "remaining_units": 0,
            "measured_density_gcc": None,
            "measured_hardness_hv": None,
            "yield_pct": None,
            "_pinned_hardness_hv": grade["hardness_hv"],
        }
    )
    db.batches[row["id"]] = row
    return object_response(serialize.batch(row), 201)


@bp.route("/tooling/powder-blend-batches", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "batches",
        READ_ROLES,
        {"grade_id": None, "stage": c.BATCH_STAGES, "qc_status": c.BATCH_QC},
    )
    return c.list_response("batches", rows, limit, offset)


@bp.route("/tooling/powder-blend-batches/<batch_id>", methods=["GET"])
def read(batch_id):
    return c.read_one("batches", batch_id, READ_ROLES)


@bp.route("/tooling/powder-blend-batches/<batch_id>/press", methods=["POST"])
def press(batch_id):
    authenticate(["ProductionPlanner", "MetallurgyEngineer"])
    payload = v.body(required=("pressed_units",))
    pressed = v.as_int(payload, "pressed_units", minimum=1)

    batch = derive.must_exist("batches", batch_id)
    if batch["stage"] != "BLENDED" or batch["qc_status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_BATCH_STATE",
            "Pressing requires stage BLENDED and qc_status PENDING (currently %s / %s)."
            % (batch["stage"], batch["qc_status"]),
        )

    batch["pressed_units"] = pressed
    batch["stage"] = "PRESSED"
    db.touch(batch)
    return object_response(serialize.batch(batch))


@bp.route("/tooling/powder-blend-batches/<batch_id>/sinter", methods=["POST"])
def sinter(batch_id):
    authenticate(["MetallurgyEngineer"])
    payload = v.body(
        required=(
            "sintered_units",
            "scrap_units",
            "measured_density_gcc",
            "measured_hardness_hv",
        )
    )
    sintered = v.as_int(payload, "sintered_units", minimum=0)
    scrap = v.as_int(payload, "scrap_units", minimum=0)
    density = v.as_number(payload, "measured_density_gcc", minimum=0)
    hardness = v.as_int(payload, "measured_hardness_hv", minimum=0)

    batch = derive.must_exist("batches", batch_id)
    if batch["stage"] != "PRESSED":
        raise ApiError(
            "ERR_INVALID_BATCH_STATE",
            "Sintering requires stage PRESSED (currently %s)." % batch["stage"],
        )
    if sintered + scrap != batch["pressed_units"]:
        raise ApiError(
            "ERR_UNIT_COUNT_MISMATCH",
            "sintered_units + scrap_units must equal pressed_units (%d)."
            % batch["pressed_units"],
        )

    target = batch.get("_pinned_hardness_hv")
    if target is None:
        grade = db.grades.get(batch["grade_id"])
        target = grade["hardness_hv"] if grade else hardness
    yield_pct, verdict = calc.sinter_qc_evaluation(
        batch["pressed_units"], sintered, density, hardness, target
    )

    batch["sintered_units"] = sintered
    batch["scrap_units"] = scrap
    batch["measured_density_gcc"] = density
    batch["measured_hardness_hv"] = hardness
    batch["yield_pct"] = float(yield_pct)
    batch["stage"] = "SINTERED"
    batch["qc_status"] = verdict
    batch["remaining_units"] = sintered
    db.touch(batch)
    return object_response(serialize.batch(batch))


@bp.route("/tooling/powder-blend-batches/<batch_id>/quarantine", methods=["POST"])
def quarantine(batch_id):
    authenticate(["QualityApprover"])
    payload = v.body(required=("quarantine_reason",))
    v.as_string(payload, "quarantine_reason")

    batch = derive.must_exist("batches", batch_id)
    if batch["qc_status"] != "PASSED":
        raise ApiError(
            "ERR_INVALID_BATCH_STATE",
            "Only a PASSED batch may be quarantined (currently %s)." % batch["qc_status"],
        )

    # Hop 1 -> 2: invalidate every trial fed by the batch, returning its units.
    affected = []
    for trial in db.ordered(
        [t for t in db.trials.values() if t["batch_id"] == batch["id"]]
    ):
        if trial["status"] in ("RUNNING", "COMPLETED"):
            trial["status"] = "INVALIDATED"
            batch["remaining_units"] = batch["remaining_units"] + trial["units_consumed"]
            db.touch(trial)
            if trial["dossier_id"] not in affected:
                affected.append(trial["dossier_id"])

    batch["qc_status"] = "QUARANTINED"
    batch["remaining_units"] = 0
    db.touch(batch)

    # Hops 2 -> 4: the dossier counters are derived, so the observable effects are
    # the SUBMITTED -> OPEN reversion and the version bump on each dossier.
    for dossier in db.ordered([db.dossiers[d] for d in affected if d in db.dossiers]):
        _completed, passed, _score = derive.dossier_counters(dossier)
        if dossier["status"] == "SUBMITTED" and passed < dossier["required_trial_count"]:
            dossier["status"] = "OPEN"
            dossier["submitted_by_user_id"] = None
        db.touch(dossier)

    return object_response(serialize.batch(batch))
