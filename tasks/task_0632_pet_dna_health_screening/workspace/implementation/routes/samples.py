"""Sample receipt, re-test, and genotyping-run routes (PRD §3.3)."""
from flask import Blueprint, request

from db import db, create_versioned, touch
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_RETEST_NOT_ELIGIBLE,
    ERR_SAMPLE_NOT_GENOTYPABLE, ERR_INVALID_RANGE,
)
from helpers import (
    get_json_body, require_fields, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_sample, serialize_genotyping_run
from services.common import get_or_404
from services.calculations import compute_qc_score_and_outcome
from services.sample_service import (
    apply_genotyping_outcome, kit_has_other_non_terminal_sample,
)

samples_bp = Blueprint("samples", __name__)


@samples_bp.route("/dna/samples", methods=["POST"])
def create_sample():
    require_roles({"LabTechnician"})
    body = get_json_body()
    require_fields(body, ["kit_id"])

    kit = get_or_404(db.kits, body["kit_id"])

    retest_of = body.get("retest_of_sample_id")
    if retest_of is not None:
        # Existence of the referenced prior sample (left-to-right).
        prior = get_or_404(db.samples, retest_of)
        # Re-test eligibility: prior must be QNS or FAILED (priority 9).
        if prior["status"] not in ("QNS", "FAILED"):
            raise err(ERR_RETEST_NOT_ELIGIBLE,
                      "Referenced sample is not eligible for re-test")
        # Re-test permitted only while owning kit is back in RECEIVED.
        if kit["status"] != "RECEIVED":
            raise err(ERR_INVALID_STATE, "Owning kit is not in RECEIVED state")

        # Mark prior sample RETESTED; create successor in RECEIVED on same kit.
        prior["status"] = "RETESTED"
        touch(prior)
        successor = create_versioned(db.samples, {
            "kit_id": kit["id"],
            "pet_id": kit["activated_pet_id"],
            "status": "RECEIVED",
            "qc_score": None,
            "retest_of_sample_id": retest_of,
        })
        return success(serialize_sample(successor), status=201)

    # Ordinary receipt: kit must be ACTIVATED.
    if kit["status"] != "ACTIVATED":
        raise err(ERR_INVALID_STATE, "Kit is not in ACTIVATED state")

    sample = create_versioned(db.samples, {
        "kit_id": kit["id"],
        "pet_id": kit["activated_pet_id"],
        "status": "RECEIVED",
        "qc_score": None,
        "retest_of_sample_id": None,
    })
    # Advance kit ACTIVATED -> RECEIVED.
    kit["status"] = "RECEIVED"
    touch(kit)
    return success(serialize_sample(sample), status=201)


@samples_bp.route("/dna/samples/<rid>", methods=["GET"])
def get_sample(rid):
    require_roles({"PlatformAdmin", "Account", "LabTechnician"})
    rec = get_or_404(db.samples, rid)
    return success(serialize_sample(rec), status=200)


@samples_bp.route("/dna/samples", methods=["GET"])
def list_samples():
    require_roles({"PlatformAdmin", "LabTechnician"})
    limit, offset = parse_pagination()
    kit_id = request.args.get("kit_id")
    pet_id = request.args.get("pet_id")
    retest_of = request.args.get("retest_of_sample_id")

    items = list(db.samples.values())
    if kit_id is not None:
        items = [s for s in items if s["kit_id"] == kit_id]
    if pet_id is not None:
        items = [s for s in items if s["pet_id"] == pet_id]
    if retest_of is not None:
        items = [s for s in items if s["retest_of_sample_id"] == retest_of]

    window, total = paginate(items, limit, offset)
    return list_success([serialize_sample(s) for s in window], limit, offset, total)


def _validate_unit_range(body):
    """call_rate/het_rate/contamination in [0,1] (ERR_INVALID_RANGE)."""
    for name in ("call_rate", "het_rate", "contamination"):
        v = body[name]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise err(ERR_INVALID_REQUEST, "%s must be numeric" % name)
        if v < 0 or v > 1:
            raise err(ERR_INVALID_RANGE, "%s out of range [0,1]" % name)


@samples_bp.route("/dna/samples/<rid>/genotyping-runs", methods=["POST"])
def create_genotyping_run(rid):
    require_roles({"LabTechnician"})
    sample = get_or_404(db.samples, rid)

    body = get_json_body()
    require_fields(body, ["call_rate", "het_rate", "contamination"])

    # Sample genotypability (priority 10): RECEIVED or GENOTYPING; the same kit
    # may not hold two non-terminal samples.
    if sample["status"] not in ("RECEIVED", "GENOTYPING"):
        raise err(ERR_SAMPLE_NOT_GENOTYPABLE, "Sample is not genotypable")
    if kit_has_other_non_terminal_sample(sample["kit_id"], sample["id"]):
        raise err(ERR_SAMPLE_NOT_GENOTYPABLE,
                  "Kit already holds another non-terminal sample")

    # Numeric range (priority 13).
    _validate_unit_range(body)

    qc_score, outcome = compute_qc_score_and_outcome(
        body["call_rate"], body["het_rate"], body["contamination"]
    )

    run = create_versioned(db.genotyping_runs, {
        "sample_id": sample["id"],
        "call_rate": body["call_rate"],
        "het_rate": body["het_rate"],
        "contamination": body["contamination"],
        "breed_segments": body.get("breed_segments"),
        "qc_score": qc_score,
        "outcome": outcome,
    })

    # First run on a RECEIVED sample advances RECEIVED -> GENOTYPING.
    if sample["status"] == "RECEIVED":
        sample["status"] = "GENOTYPING"
        touch(sample)

    # Outcome drives the sample fork and its cascades.
    apply_genotyping_outcome(sample, run)

    return success(serialize_genotyping_run(run), status=201)


@samples_bp.route("/dna/samples/<rid>/genotyping-runs", methods=["GET"])
def list_genotyping_runs(rid):
    require_roles({"PlatformAdmin", "LabTechnician"})
    sample = get_or_404(db.samples, rid)
    limit, offset = parse_pagination()
    items = [r for r in db.genotyping_runs.values() if r["sample_id"] == sample["id"]]
    window, total = paginate(items, limit, offset)
    return list_success(
        [serialize_genotyping_run(r) for r in window], limit, offset, total
    )
