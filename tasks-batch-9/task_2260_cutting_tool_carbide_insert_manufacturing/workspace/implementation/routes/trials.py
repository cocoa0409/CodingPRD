"""Machining trials and the flank-wear curve (PRD 3.6)."""

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("trials", __name__)

READ_ROLES = [
    "ApplicationEngineer",
    "QualityApprover",
    "GeometryEngineer",
    "MetallurgyEngineer",
    "CoatingEngineer",
]
OWNER = ["ApplicationEngineer"]

MIN_UNITS = 1
MAX_UNITS = 50


def _parse_wear(payload):
    """Priority 4 (per-entry types) then priority 5 (curve well-formedness)."""
    entries = payload.get("wear_measurements")
    if not isinstance(entries, list):
        v.bad("Field 'wear_measurements' must be an array of {minutes, vb_um} objects.")

    parsed = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            v.bad("Wear measurement %d must be an object." % index)
        unknown = [k for k in entry.keys() if k not in ("minutes", "vb_um")]
        if unknown:
            v.bad(
                "Wear measurement %d carries unknown field(s): %s."
                % (index, ", ".join(sorted(unknown)))
            )
        for name in ("minutes", "vb_um"):
            if name not in entry:
                v.bad("Wear measurement %d is missing %r." % (index, name))
        minutes = v.as_number(entry, "minutes", minimum=0)
        wear = v.as_number(entry, "vb_um", minimum=0)
        parsed.append({"minutes": minutes, "vb_um": wear})

    if len(parsed) < 2:
        raise ApiError(
            "ERR_INVALID_WEAR_CURVE", "The wear curve must hold at least 2 entries."
        )
    for i in range(1, len(parsed)):
        if calc.D(parsed[i]["minutes"]) <= calc.D(parsed[i - 1]["minutes"]):
            raise ApiError(
                "ERR_INVALID_WEAR_CURVE", "The curve's 'minutes' must be strictly increasing."
            )
        if calc.D(parsed[i]["vb_um"]) < calc.D(parsed[i - 1]["vb_um"]):
            raise ApiError(
                "ERR_INVALID_WEAR_CURVE", "The curve's 'vb_um' must be non-decreasing."
            )
    if calc.D(parsed[-1]["vb_um"]) == calc.D(parsed[-2]["vb_um"]):
        raise ApiError(
            "ERR_INVALID_WEAR_CURVE",
            "The last two 'vb_um' values must differ so the wear rate is positive.",
        )
    return parsed


@bp.route("/tooling/machining-trials", methods=["POST"])
def create():
    user_id, _role = authenticate(OWNER)
    payload = v.body(
        required=(
            "dossier_id",
            "batch_id",
            "trial_code",
            "workpiece_material_code",
            "workpiece_group",
            "units_consumed",
            "cutting_speed_vc",
            "feed_fz",
            "depth_ap",
            "coolant",
        )
    )
    dossier_id = v.as_id(payload, "dossier_id")
    batch_id = v.as_id(payload, "batch_id")
    trial_code = v.as_string(payload, "trial_code")
    material_code = v.as_string(payload, "workpiece_material_code")
    group = v.as_enum(payload, "workpiece_group", c.WORKPIECE_GROUPS)
    units = v.as_int(payload, "units_consumed", minimum=MIN_UNITS, maximum=MAX_UNITS)
    vc = v.as_number(payload, "cutting_speed_vc", exclusive_min=0)
    fz = v.as_number(payload, "feed_fz", exclusive_min=0)
    ap = v.as_number(payload, "depth_ap", exclusive_min=0)
    coolant = v.as_enum(payload, "coolant", c.COOLANTS)

    dossier = derive.must_exist("dossiers", dossier_id)
    batch = derive.must_exist("batches", batch_id)
    derive.require_unique("trials", "trial_code", trial_code)

    if dossier["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_DOSSIER_STATE",
            "Trials may be opened only while the dossier is OPEN (currently %s)."
            % dossier["status"],
        )
    if batch["qc_status"] != "PASSED" or batch["stage"] not in ("SINTERED", "CONSUMED"):
        raise ApiError(
            "ERR_BATCH_QC_NOT_PASSED",
            "The supplying batch must be QC PASSED and at stage SINTERED or CONSUMED.",
        )
    if units > batch["remaining_units"]:
        raise ApiError(
            "ERR_INSUFFICIENT_BATCH_UNITS",
            "The batch holds %d remaining unit(s)." % batch["remaining_units"],
        )

    row = db.new_row(
        {
            "dossier_id": dossier["id"],
            "batch_id": batch["id"],
            "trial_code": trial_code,
            "workpiece_material_code": material_code,
            "workpiece_group": group,
            "units_consumed": units,
            "cutting_speed_vc": vc,
            "feed_fz": fz,
            "depth_ap": ap,
            "coolant": coolant,
            "operator_user_id": user_id,
            "wear_measurements": [],
            "measured_surface_ra_um": None,
            "rated_life_min": None,
            "projected_life_min": None,
            "censored": None,
            "verdict": None,
            "status": "RUNNING",
        }
    )
    db.trials[row["id"]] = row

    batch["remaining_units"] = batch["remaining_units"] - units
    if batch["remaining_units"] == 0:
        batch["stage"] = "CONSUMED"
    db.touch(batch)
    return object_response(serialize.trial(row), 201)


@bp.route("/tooling/machining-trials", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "trials",
        READ_ROLES,
        {
            "dossier_id": None,
            "batch_id": None,
            "status": c.TRIAL_STATUSES,
            "verdict": c.VERDICTS,
        },
    )
    return c.list_response("trials", rows, limit, offset)


@bp.route("/tooling/machining-trials/<trial_id>", methods=["GET"])
def read(trial_id):
    return c.read_one("trials", trial_id, READ_ROLES)


@bp.route("/tooling/machining-trials/<trial_id>/complete", methods=["POST"])
def complete(trial_id):
    authenticate(OWNER)
    payload = v.body(required=("wear_measurements", "measured_surface_ra_um"))
    wear = _parse_wear(payload)
    ra = v.as_number(payload, "measured_surface_ra_um", exclusive_min=0)

    trial = derive.must_exist("trials", trial_id)
    if trial["status"] != "RUNNING":
        raise ApiError(
            "ERR_INVALID_TRIAL_STATE",
            "Only a RUNNING trial may be completed (currently %s)." % trial["status"],
        )
    batch = db.batches.get(trial["batch_id"])
    if batch is None or batch["qc_status"] != "PASSED":
        raise ApiError(
            "ERR_BATCH_QC_NOT_PASSED",
            "The supplying batch's qc_status is no longer PASSED.",
        )

    dossier = db.dossiers.get(trial["dossier_id"])
    product = db.products.get(dossier["product_id"]) if dossier else None
    geometry = db.geometries.get(product["geometry_id"]) if product else None
    application_class = geometry["application_class"] if geometry else None

    rated, projected, censored = calc.trial_tool_life_rating(wear)
    trial["wear_measurements"] = wear
    trial["measured_surface_ra_um"] = ra
    trial["rated_life_min"] = float(rated)
    trial["projected_life_min"] = float(projected)
    trial["censored"] = censored
    trial["verdict"] = calc.trial_verdict(application_class, rated, censored, ra)
    trial["status"] = "COMPLETED"
    db.touch(trial)

    if dossier is not None:
        db.touch(dossier)
        # A trial that closes under an already-approved dossier feeds the
        # product's qualification figures straight away.
        if dossier["status"] == "APPROVED" and product is not None:
            derive.recompute_product_index(product)
            db.touch(product)
    return object_response(serialize.trial(trial))
