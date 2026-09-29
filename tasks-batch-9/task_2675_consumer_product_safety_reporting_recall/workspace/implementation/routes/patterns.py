"""Hazard pattern analysis, recomputation and adjudication (PRD 3.2)."""

from flask import Blueprint

import auth
import calc
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("patterns", __name__)

ANALYSIS_BASES = ("PRELIMINARY", "FINAL")
PATTERN_STATUSES = ("ANALYZED", "CONFIRMED", "DISMISSED", "SUPERSEDED")
DECISIONS = ("CONFIRMED", "DISMISSED")

READ_ROLES = ("ProgramAdmin", "IntakeSpecialist", "ComplianceOfficer",
              "SafetyDirector", "PenaltyCounsel")


@bp.route("/hazard-patterns/<pattern_id>", methods=["GET"])
def get_pattern(pattern_id):
    auth.authorize(*READ_ROLES)
    return responses.object_response(lookups.find("hazard_pattern", pattern_id))


@bp.route("/hazard-patterns", methods=["GET"])
def list_patterns():
    auth.authorize(*READ_ROLES)
    limit, offset = shapes.pagination()
    product_model_id = shapes.q_str("product_model_id")
    pattern_status = shapes.q_enum("pattern_status", PATTERN_STATUSES)
    analysis_basis = shapes.q_enum("analysis_basis", ANALYSIS_BASES)

    def keep(row):
        if product_model_id is not None and row["product_model_id"] != product_model_id:
            return False
        if pattern_status is not None and row["pattern_status"] != pattern_status:
            return False
        if analysis_basis is not None and row["analysis_basis"] != analysis_basis:
            return False
        return True

    return responses.list_response(
        store.ordered(store.hazard_patterns, keep), limit, offset)


def _recluster(pattern, rows):
    """Re-point the qualifying set at this pattern; release those that dropped out."""
    kept = set(r["id"] for r in rows)
    for row in rows:
        if row["status"] == "CLASSIFIED":
            row["status"] = "CLUSTERED"
            row["hazard_pattern_id"] = pattern["id"]
            store.touch(row)
        elif row["hazard_pattern_id"] != pattern["id"]:
            row["hazard_pattern_id"] = pattern["id"]
            store.touch(row)

    def dropped(row):
        return (row["hazard_pattern_id"] == pattern["id"]
                and row["id"] not in kept
                and row["status"] == "CLUSTERED")

    for row in store.ordered(store.incidents, dropped):
        row["status"] = "CLASSIFIED"
        row["hazard_pattern_id"] = None
        store.touch(row)


@bp.route("/hazard-patterns", methods=["POST"])
def create_pattern():
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    data = shapes.body()
    product_model_id = shapes._req(data, "product_model_id")
    window_start = shapes.req_ts(data, "window_start")
    window_end = shapes.req_ts(data, "window_end")
    analysis_basis = shapes.req_enum(data, "analysis_basis", ANALYSIS_BASES)
    expected_version = shapes.req_int(data, "expected_product_model_version")
    if not window_start < window_end:
        shapes.bad()

    model = lookups.find("product_model", product_model_id)
    if expected_version != model["version"]:
        raise_error("ERR_STALE_PRODUCT_MODEL_VERSION")

    snapshot, rows = calc.pattern_snapshot(
        model, window_start, window_end, analysis_basis)

    row = store.new_row(
        product_model_id=product_model_id,
        window_start=window_start,
        window_end=window_end,
        analysis_basis=analysis_basis,
        pattern_status="ANALYZED",
        analyzed_at=store.now_logical(),
        **snapshot
    )
    store.hazard_patterns[row["id"]] = row

    _recluster(row, rows)

    def superseded(other):
        return (other["id"] != row["id"]
                and other["product_model_id"] == product_model_id
                and other["pattern_status"] in ("ANALYZED", "CONFIRMED"))

    for other in store.ordered(store.hazard_patterns, superseded):
        other["pattern_status"] = "SUPERSEDED"
        store.touch(other)

    store.touch(model)
    return responses.created(row)


@bp.route("/hazard-patterns/<pattern_id>/recompute", methods=["POST"])
def recompute_pattern(pattern_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    pattern = lookups.find("hazard_pattern", pattern_id)
    data = shapes.body()
    analysis_basis = shapes.opt_enum(data, "analysis_basis", ANALYSIS_BASES)
    window_start = shapes.opt_ts(data, "window_start")
    window_end = shapes.opt_ts(data, "window_end")

    effective_start = pattern["window_start"] if window_start is shapes.MISSING else window_start
    effective_end = pattern["window_end"] if window_end is shapes.MISSING else window_end
    if not effective_start < effective_end:
        shapes.bad()
    effective_basis = (pattern["analysis_basis"] if analysis_basis is shapes.MISSING
                       else analysis_basis)

    if pattern["pattern_status"] != "ANALYZED":
        raise_error("ERR_PATTERN_STATE_INVALID")

    model = lookups.maybe("product_model", pattern["product_model_id"])
    if model is not None and model["hazard_posture"] == "FROZEN":
        raise_error("ERR_MODEL_POSTURE_FROZEN")

    pattern["window_start"] = effective_start
    pattern["window_end"] = effective_end
    pattern["analysis_basis"] = effective_basis

    snapshot, rows = calc.pattern_snapshot(
        model, effective_start, effective_end, effective_basis)
    pattern.update(snapshot)
    pattern["analyzed_at"] = store.now_logical()
    store.touch(pattern)

    _recluster(pattern, rows)
    return responses.object_response(pattern)


@bp.route("/hazard-patterns/<pattern_id>/adjudicate", methods=["POST"])
def adjudicate_pattern(pattern_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    pattern = lookups.find("hazard_pattern", pattern_id)
    data = shapes.body()
    decision = shapes.req_enum(data, "decision", DECISIONS)
    shapes.opt_str(data, "note", 0, 2000)

    if pattern["pattern_status"] != "ANALYZED":
        raise_error("ERR_PATTERN_STATE_INVALID")

    model = lookups.maybe("product_model", pattern["product_model_id"])

    if decision == "CONFIRMED":
        if not pattern["pattern_confirmed"]:
            raise_error("ERR_PATTERN_NOT_CONFIRMABLE")
        pattern["pattern_status"] = "CONFIRMED"
        store.touch(pattern)
        return responses.object_response(pattern)

    if model is not None and model["hazard_posture"] == "FROZEN":
        raise_error("ERR_MODEL_POSTURE_FROZEN")

    pattern["pattern_status"] = "DISMISSED"
    store.touch(pattern)

    def clustered(row):
        return (row["hazard_pattern_id"] == pattern["id"]
                and row["status"] == "CLUSTERED")

    for row in store.ordered(store.incidents, clustered):
        row["status"] = "CLASSIFIED"
        row["hazard_pattern_id"] = None
        store.touch(row)

    return responses.object_response(pattern)
