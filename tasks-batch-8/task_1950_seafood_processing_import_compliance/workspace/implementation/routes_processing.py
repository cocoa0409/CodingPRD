"""Species verifications, processing batches, batch inputs, temperature logs,
HACCP monitoring records."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import store, new_entity, new_append_only, touch
from errors import (
    ApiError, ERR_RECEIPT_LOT_NOT_FOUND, ERR_PROCESSING_BATCH_NOT_FOUND,
    ERR_BATCH_INPUT_NOT_FOUND, ERR_SPECIES_VERIFICATION_NOT_FOUND,
    ERR_INVALID_STATE, ERR_VALIDATION_FAILED, ERR_LOT_NOT_ACCEPTED,
    ERR_SPECIES_MISMATCH, ERR_INSUFFICIENT_LOT_REMAINING,
    ERR_BATCH_HAS_NO_INPUTS, ERR_STALE_VERSION, ERR_MASS_IMBALANCE,
    ERR_YIELD_VARIANCE_EXCEEDED, ERR_AMBIGUOUS_SUBJECT,
    ERR_TEMPERATURE_INTERVAL_OVERLAP,
)
from middleware import (
    require_roles, ANY_OPERATIONAL, ROLE_RECEIVING_INSPECTOR, ROLE_QA_TECH,
    ROLE_PROCESSING_SUPERVISOR,
)
from response import success
from services import (
    serialize_verification, serialize_batch, serialize_batch_input,
    serialize_temp_log, serialize_haccp_record, input_provisional_yield,
    recompute_batch_totals, batch_inputs, auto_create_corrective_action,
    quarantine_lot, recompute_temperature_effects,
    CRITICAL_LIMIT_PPM, SUBSAMPLE_CEILING_PPM, YIELD_VARIANCE_TOLERANCE,
)
from utils import (
    get_body, req_str, req_int, req_num, req_enum, req_dt, req_num_list,
    q1, q2, q3, paginate,
)

bp = Blueprint("processing", __name__)


def get_lot_or_404(lot_id):
    l = store.lots.get(lot_id)
    if l is None:
        raise ApiError(ERR_RECEIPT_LOT_NOT_FOUND,
                       "Receipt lot %s not found" % lot_id, 404)
    return l


def get_batch_or_404(batch_id):
    b = store.batches.get(batch_id)
    if b is None:
        raise ApiError(ERR_PROCESSING_BATCH_NOT_FOUND,
                       "Processing batch %s not found" % batch_id, 404)
    return b


# ---------------------------------------------------------------- verifications
@bp.route("/seafood/species-verifications", methods=["POST"])
@require_roles(ROLE_RECEIVING_INSPECTOR)
def create_verification():
    body = get_body()
    lot_id = body.get("receipt_lot_id")
    if isinstance(lot_id, str) and lot_id not in store.lots:
        raise ApiError(ERR_RECEIPT_LOT_NOT_FOUND,
                       "Receipt lot %s not found" % lot_id, 404)
    lot_id = req_str(body, "receipt_lot_id")
    lot = store.lots[lot_id]
    test_method = req_enum(body, "test_method", ("DNA_BARCODING", "SENSORY"))
    sample_size = req_int(body, "sample_size")
    if sample_size <= 0:
        raise ApiError(ERR_VALIDATION_FAILED, "sample_size must be > 0", 400)
    verified_species = req_str(body, "verified_species")
    if lot["status"] not in ("UNDER_INSPECTION", "QUARANTINED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Species verification requires the lot to be UNDER_INSPECTION or "
            "QUARANTINED", 409)
    is_match = verified_species == lot["species_declared"]
    verification = new_entity(
        receipt_lot_id=lot["id"],
        test_method=test_method,
        sample_size=sample_size,
        verified_species=verified_species,
        is_match=is_match,
        resolution=None,
        status="CONFIRMED" if is_match else "MISMATCH",
    )
    store.verifications[verification["id"]] = verification
    if is_match:
        lot["species_verified"] = verified_species
        touch(lot)
    else:
        # 3-link cascade: quarantine -> CA -> supplier counters/risk
        quarantine_lot(lot)
        auto_create_corrective_action(
            "SPECIES_MISMATCH", opened_by=g.user_id, lot=lot)
    return success(serialize_verification(verification), "object", 201)


@bp.route("/seafood/species-verifications/<vid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_verification(vid):
    v = store.verifications.get(vid)
    if v is None:
        raise ApiError(ERR_SPECIES_VERIFICATION_NOT_FOUND,
                       "Species verification %s not found" % vid, 404)
    return success(serialize_verification(v))


@bp.route("/seafood/species-verifications", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_verifications():
    items = list(store.verifications.values())
    lot_id = request.args.get("receipt_lot_id")
    if lot_id is not None:
        items = [v for v in items if v["receipt_lot_id"] == lot_id]
    page, meta = paginate(items)
    return success([serialize_verification(v) for v in page], "array", 200, meta)


@bp.route("/seafood/species-verifications/<vid>/resolve", methods=["POST"])
@require_roles(ROLE_QA_TECH)
def resolve_verification(vid):
    v = store.verifications.get(vid)
    if v is None:
        raise ApiError(ERR_SPECIES_VERIFICATION_NOT_FOUND,
                       "Species verification %s not found" % vid, 404)
    body = get_body()
    resolution = req_enum(body, "resolution",
                          ("RELABEL_AS_VERIFIED", "REJECT_LOT"))
    if v["status"] != "MISMATCH":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a MISMATCH verification can be resolved", 409)
    lot = store.lots.get(v["receipt_lot_id"])
    if lot is None or lot["status"] != "QUARANTINED":
        raise ApiError(ERR_INVALID_STATE,
                       "The lot must be QUARANTINED to resolve a mismatch", 409)
    v["resolution"] = resolution
    if resolution == "RELABEL_AS_VERIFIED":
        lot["species_declared"] = v["verified_species"]
        lot["species_verified"] = v["verified_species"]
        lot["mislabel_flag"] = True
        touch(lot)
        v["status"] = "RESOLVED_RELABELED"
    else:
        lot["status"] = "REJECTED"
        touch(lot)
        v["status"] = "RESOLVED_REJECTED"
    touch(v)
    return success(serialize_verification(v))


# ---------------------------------------------------------------- batches
@bp.route("/seafood/processing-batches", methods=["POST"])
@require_roles(ROLE_PROCESSING_SUPERVISOR)
def create_batch():
    body = get_body()
    target_species = req_str(body, "target_species")
    product_form = req_enum(body, "product_form", ("FILLET", "LOIN", "PORTION"))
    batch = new_entity(
        target_species=target_species,
        product_form=product_form,
        status="IN_PROCESS",
        input_total_kg=Decimal("0.000"),
        provisional_output_kg=Decimal("0.000"),
        actual_output_kg=None,
        trim_waste_kg=None,
        other_waste_kg=None,
        yield_pct_provisional=None,
        yield_pct_final=None,
        yield_variance_pct=None,
    )
    store.batches[batch["id"]] = batch
    return success(serialize_batch(batch), "object", 201)


@bp.route("/seafood/processing-batches/<bid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_batch(bid):
    return success(serialize_batch(get_batch_or_404(bid)))


@bp.route("/seafood/processing-batches/<bid>/inputs", methods=["POST"])
@require_roles(ROLE_PROCESSING_SUPERVISOR)
def add_batch_input(bid):
    batch = get_batch_or_404(bid)
    body = get_body()
    lot_id = body.get("receipt_lot_id")
    if isinstance(lot_id, str) and lot_id not in store.lots:
        raise ApiError(ERR_RECEIPT_LOT_NOT_FOUND,
                       "Receipt lot %s not found" % lot_id, 404)
    lot_id = req_str(body, "receipt_lot_id")
    lot = store.lots[lot_id]
    quantity = req_num(body, "quantity_kg")
    if quantity <= 0:
        raise ApiError(ERR_VALIDATION_FAILED, "quantity_kg must be > 0", 400)
    quantity = q3(quantity)
    if batch["status"] != "IN_PROCESS":
        raise ApiError(ERR_INVALID_STATE,
                       "Inputs can only be added while the batch is IN_PROCESS",
                       409)
    if lot["status"] != "ACCEPTED":
        raise ApiError(ERR_LOT_NOT_ACCEPTED,
                       "Batch input requires the lot to be ACCEPTED", 409)
    effective_species = lot["species_verified"] or lot["species_declared"]
    if effective_species != batch["target_species"]:
        raise ApiError(
            ERR_SPECIES_MISMATCH,
            "Lot species %s does not match batch target %s"
            % (effective_species, batch["target_species"]), 422)
    remaining = lot["quantity_accepted_kg"] - lot["consumed_kg"]
    if quantity > remaining:
        raise ApiError(
            ERR_INSUFFICIENT_LOT_REMAINING,
            "quantity_kg exceeds lot remaining_kg", 422)
    row = new_entity(
        processing_batch_id=batch["id"],
        receipt_lot_id=lot["id"],
        quantity_kg=quantity,
        provisional_yield_kg=input_provisional_yield(batch, lot, quantity),
    )
    store.batch_inputs[row["id"]] = row
    lot["consumed_kg"] = q3(lot["consumed_kg"] + quantity)
    if lot["quantity_accepted_kg"] - lot["consumed_kg"] == 0:
        lot["status"] = "CONSUMED"
    touch(lot)
    recompute_batch_totals(batch)
    touch(batch)
    return success(serialize_batch_input(row), "object", 201)


@bp.route("/seafood/batch-input-lots/<iid>", methods=["DELETE"])
@require_roles(ROLE_PROCESSING_SUPERVISOR)
def delete_batch_input(iid):
    row = store.batch_inputs.get(iid)
    if row is None:
        raise ApiError(ERR_BATCH_INPUT_NOT_FOUND,
                       "Batch input %s not found" % iid, 404)
    batch = store.batches.get(row["processing_batch_id"])
    if batch is None or batch["status"] != "IN_PROCESS":
        raise ApiError(ERR_INVALID_STATE,
                       "Inputs can only be removed while the batch is IN_PROCESS",
                       409)
    lot = store.lots.get(row["receipt_lot_id"])
    snapshot = dict(row)
    if lot is not None:
        lot["consumed_kg"] = q3(lot["consumed_kg"] - row["quantity_kg"])
        if (lot["status"] == "CONSUMED"
                and lot["quantity_accepted_kg"] - lot["consumed_kg"] > 0):
            lot["status"] = "ACCEPTED"
        touch(lot)
    del store.batch_inputs[iid]
    recompute_batch_totals(batch)
    touch(batch)
    return success(serialize_batch_input(snapshot))


@bp.route("/seafood/batch-input-lots/<iid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_batch_input(iid):
    row = store.batch_inputs.get(iid)
    if row is None:
        raise ApiError(ERR_BATCH_INPUT_NOT_FOUND,
                       "Batch input %s not found" % iid, 404)
    return success(serialize_batch_input(row))


@bp.route("/seafood/batch-input-lots", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_batch_inputs():
    items = list(store.batch_inputs.values())
    batch_id = request.args.get("processing_batch_id")
    lot_id = request.args.get("receipt_lot_id")
    if batch_id is not None:
        items = [r for r in items if r["processing_batch_id"] == batch_id]
    if lot_id is not None:
        items = [r for r in items if r["receipt_lot_id"] == lot_id]
    page, meta = paginate(items)
    return success([serialize_batch_input(r) for r in page], "array", 200, meta)


@bp.route("/seafood/processing-batches/<bid>/complete", methods=["POST"])
@require_roles(ROLE_PROCESSING_SUPERVISOR)
def complete_batch(bid):
    batch = get_batch_or_404(bid)
    body = get_body()
    expected_version = req_int(body, "expected_batch_version")
    actual = req_num(body, "actual_output_kg")
    trim = req_num(body, "trim_waste_kg")
    other = req_num(body, "other_waste_kg")
    for name, v in (("actual_output_kg", actual), ("trim_waste_kg", trim),
                    ("other_waste_kg", other)):
        if v < 0:
            raise ApiError(ERR_VALIDATION_FAILED, "%s must be >= 0" % name, 400)
    if batch["status"] != "IN_PROCESS":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an IN_PROCESS batch can be completed", 409)
    if not batch_inputs(batch["id"]):
        raise ApiError(ERR_BATCH_HAS_NO_INPUTS,
                       "Cannot complete a batch with zero input rows", 422)
    if expected_version != batch["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_batch_version does not match current batch "
                       "version", 412)
    recompute_batch_totals(batch)
    batch["actual_output_kg"] = q3(actual)
    batch["trim_waste_kg"] = q3(trim)
    batch["other_waste_kg"] = q3(other)
    batch["yield_pct_final"] = q2(
        Decimal("100") * batch["actual_output_kg"] / batch["input_total_kg"])
    batch["yield_variance_pct"] = q2(
        batch["yield_pct_final"] - batch["yield_pct_provisional"])
    if abs(batch["yield_variance_pct"]) > YIELD_VARIANCE_TOLERANCE:
        auto_create_corrective_action(
            "YIELD_VARIANCE", opened_by=g.user_id, batch=batch)
    batch["status"] = "COMPLETED"
    touch(batch)
    return success(serialize_batch(batch))


@bp.route("/seafood/processing-batches/<bid>/reopen", methods=["POST"])
@require_roles(ROLE_PROCESSING_SUPERVISOR)
def reopen_batch(bid):
    batch = get_batch_or_404(bid)
    if batch["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a COMPLETED batch can be reopened", 409)
    for fl in store.finished_lots.values():
        if (fl["processing_batch_id"] == batch["id"]
                and fl["status"] in ("RELEASED", "RECALLED")):
            raise ApiError(
                ERR_INVALID_STATE,
                "Cannot reopen: a finished lot is RELEASED or RECALLED", 409)
    batch["status"] = "IN_PROCESS"
    touch(batch)
    return success(serialize_batch(batch))


@bp.route("/seafood/processing-batches/<bid>/reconcile", methods=["POST"])
@require_roles(ROLE_PROCESSING_SUPERVISOR)
def reconcile_batch(bid):
    batch = get_batch_or_404(bid)
    if batch["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a COMPLETED batch can be reconciled", 409)
    mass = batch["actual_output_kg"] + batch["trim_waste_kg"] + batch["other_waste_kg"]
    if batch["input_total_kg"] != mass:
        raise ApiError(
            ERR_MASS_IMBALANCE,
            "input_total_kg must equal actual_output_kg + trim_waste_kg + "
            "other_waste_kg", 422)
    variance = batch.get("yield_variance_pct")
    if variance is not None and abs(variance) > YIELD_VARIANCE_TOLERANCE:
        resolved = any(
            c.get("processing_batch_id") == batch["id"]
            and c["source_type"] == "YIELD_VARIANCE"
            and c["status"] == "RESOLVED"
            for c in store.corrective_actions.values())
        if not resolved:
            raise ApiError(
                ERR_YIELD_VARIANCE_EXCEEDED,
                "A RESOLVED YIELD_VARIANCE corrective action is required", 422)
    batch["status"] = "RECONCILED"
    touch(batch)
    return success(serialize_batch(batch))


# ---------------------------------------------------------------- temperature logs
@bp.route("/seafood/temperature-logs", methods=["POST"])
@require_roles(ROLE_RECEIVING_INSPECTOR, ROLE_QA_TECH)
def create_temperature_log():
    body = get_body()
    lot_id = body.get("receipt_lot_id")
    batch_id = body.get("processing_batch_id")
    # p4: existence of whichever FK ids are present
    if isinstance(lot_id, str) and lot_id not in store.lots:
        raise ApiError(ERR_RECEIPT_LOT_NOT_FOUND,
                       "Receipt lot %s not found" % lot_id, 404)
    if isinstance(batch_id, str) and batch_id not in store.batches:
        raise ApiError(ERR_PROCESSING_BATCH_NOT_FOUND,
                       "Processing batch %s not found" % batch_id, 404)
    interval_start = req_dt(body, "interval_start")
    interval_end = req_dt(body, "interval_end")
    if interval_end <= interval_start:
        raise ApiError(ERR_VALIDATION_FAILED,
                       "interval_end must be strictly after interval_start", 400)
    core_temp = q1(req_num(body, "core_temp_c"))
    avg_temp = q1(req_num(body, "avg_temp_c"))
    source = req_enum(body, "source", ("CONTINUOUS_MONITOR", "MANUAL_PROBE"))
    # p26: exactly one subject
    if (lot_id is None) == (batch_id is None):
        raise ApiError(
            ERR_AMBIGUOUS_SUBJECT,
            "Exactly one of receipt_lot_id / processing_batch_id is required", 400)
    # p19: half-open interval overlap per subject; adjacency allowed
    for t in store.temp_logs.values():
        same_subject = (
            (lot_id is not None and t.get("receipt_lot_id") == lot_id)
            or (batch_id is not None and t.get("processing_batch_id") == batch_id))
        if not same_subject:
            continue
        if interval_start < t["interval_end"] and t["interval_start"] < interval_end:
            raise ApiError(
                ERR_TEMPERATURE_INTERVAL_OVERLAP,
                "Temperature interval overlaps an existing interval", 422)
    log = new_append_only(
        receipt_lot_id=lot_id,
        processing_batch_id=batch_id,
        interval_start=interval_start,
        interval_end=interval_end,
        core_temp_c=core_temp,
        avg_temp_c=avg_temp,
        source=source,
    )
    store.temp_logs[log["id"]] = log
    if lot_id is not None:
        recompute_temperature_effects(store.lots[lot_id], g.user_id)
    return success(serialize_temp_log(log), "object", 201)


@bp.route("/seafood/temperature-logs/<tid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_temperature_log(tid):
    t = store.temp_logs.get(tid)
    if t is None:
        raise ApiError("ERR_TEMPERATURE_LOG_NOT_FOUND",
                       "Temperature log %s not found" % tid, 404)
    return success(serialize_temp_log(t))


@bp.route("/seafood/temperature-logs", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_temperature_logs():
    items = list(store.temp_logs.values())
    lot_id = request.args.get("receipt_lot_id")
    batch_id = request.args.get("processing_batch_id")
    if lot_id is not None:
        items = [t for t in items if t.get("receipt_lot_id") == lot_id]
    if batch_id is not None:
        items = [t for t in items if t.get("processing_batch_id") == batch_id]
    page, meta = paginate(items)
    return success([serialize_temp_log(t) for t in page], "array", 200, meta)


# ---------------------------------------------------------------- HACCP records
@bp.route("/seafood/haccp-monitoring-records", methods=["POST"])
@require_roles(ROLE_QA_TECH)
def create_haccp_record():
    body = get_body()
    hazard_type = req_enum(body, "hazard_type", ("HISTAMINE", "PARASITE"))
    lot_id = body.get("receipt_lot_id")
    batch_id = body.get("processing_batch_id")
    # p4: existence of whichever FK ids are present
    if isinstance(lot_id, str) and lot_id not in store.lots:
        raise ApiError(ERR_RECEIPT_LOT_NOT_FOUND,
                       "Receipt lot %s not found" % lot_id, 404)
    if isinstance(batch_id, str) and batch_id not in store.batches:
        raise ApiError(ERR_PROCESSING_BATCH_NOT_FOUND,
                       "Processing batch %s not found" % batch_id, 404)
    phase = req_enum(body, "phase", ("SCREENING", "CONFIRMATORY"))
    measured_raw = body.get("measured_value")
    subsamples_raw = body.get("subsample_values")
    measured_value = None
    subsample_values = None
    if phase == "SCREENING":
        if measured_raw is None:
            raise ApiError(ERR_VALIDATION_FAILED,
                           "measured_value is required for SCREENING", 400)
        measured_value = q1(req_num(body, "measured_value"))
        if subsamples_raw is not None:
            raise ApiError(ERR_VALIDATION_FAILED,
                           "subsample_values is forbidden for SCREENING", 400)
    else:  # CONFIRMATORY
        if hazard_type == "HISTAMINE":
            subsample_values = [q1(v) for v in req_num_list(body, "subsample_values")]
            if len(subsample_values) < 3:
                raise ApiError(
                    ERR_VALIDATION_FAILED,
                    "subsample_values requires at least 3 values", 400)
            if measured_raw is not None:
                raise ApiError(
                    ERR_VALIDATION_FAILED,
                    "measured_value is forbidden for CONFIRMATORY", 400)
        else:
            if measured_raw is not None:
                raise ApiError(
                    ERR_VALIDATION_FAILED,
                    "measured_value is forbidden for CONFIRMATORY", 400)
            if subsamples_raw is not None:
                raise ApiError(
                    ERR_VALIDATION_FAILED,
                    "subsample_values is forbidden for PARASITE", 400)
    measured_at = req_dt(body, "measured_at")
    # p26: hazard-subject pairing
    if hazard_type == "HISTAMINE":
        if lot_id is None or batch_id is not None:
            raise ApiError(
                ERR_AMBIGUOUS_SUBJECT,
                "HISTAMINE records require receipt_lot_id and forbid "
                "processing_batch_id", 400)
    else:
        if batch_id is None or lot_id is not None:
            raise ApiError(
                ERR_AMBIGUOUS_SUBJECT,
                "PARASITE records require processing_batch_id and forbid "
                "receipt_lot_id", 400)
    # verdict
    if hazard_type == "HISTAMINE":
        if phase == "SCREENING":
            verdict = ("DEVIATION" if measured_value >= CRITICAL_LIMIT_PPM
                       else "PASS")
        else:
            avg = q2(sum(subsample_values) / Decimal(len(subsample_values)))
            verdict = ("PASS" if (avg < CRITICAL_LIMIT_PPM
                                  and max(subsample_values) < SUBSAMPLE_CEILING_PPM)
                       else "DEVIATION")
    else:
        verdict = ("DEVIATION" if (measured_value is not None
                                   and measured_value >= 1) else "PASS")
    record = new_append_only(
        hazard_type=hazard_type,
        receipt_lot_id=lot_id,
        processing_batch_id=batch_id,
        phase=phase,
        measured_value=measured_value,
        subsample_values=subsample_values,
        measured_at=measured_at,
        verdict=verdict,
        corrective_action_id=None,
    )
    store.haccp_records[record["id"]] = record
    if verdict == "DEVIATION":
        lot = store.lots.get(lot_id) if lot_id else None
        batch = store.batches.get(batch_id) if batch_id else None
        ca = auto_create_corrective_action(
            "HISTAMINE_DEVIATION", opened_by=g.user_id, lot=lot, batch=batch,
            monitoring_record_id=record["id"])
        record["corrective_action_id"] = ca["id"]
        if lot is not None:
            quarantine_lot(lot)
    return success(serialize_haccp_record(record), "object", 201)


@bp.route("/seafood/haccp-monitoring-records/<rid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_haccp_record(rid):
    r = store.haccp_records.get(rid)
    if r is None:
        raise ApiError("ERR_HACCP_RECORD_NOT_FOUND",
                       "HACCP monitoring record %s not found" % rid, 404)
    return success(serialize_haccp_record(r))


@bp.route("/seafood/haccp-monitoring-records", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_haccp_records():
    items = list(store.haccp_records.values())
    lot_id = request.args.get("receipt_lot_id")
    batch_id = request.args.get("processing_batch_id")
    hazard_type = request.args.get("hazard_type")
    ca_id = request.args.get("corrective_action_id")
    if lot_id is not None:
        items = [r for r in items if r.get("receipt_lot_id") == lot_id]
    if batch_id is not None:
        items = [r for r in items if r.get("processing_batch_id") == batch_id]
    if hazard_type is not None:
        items = [r for r in items if r["hazard_type"] == hazard_type]
    if ca_id is not None:
        items = [r for r in items if r.get("corrective_action_id") == ca_id]
    page, meta = paginate(items)
    return success([serialize_haccp_record(r) for r in page], "array", 200, meta)
