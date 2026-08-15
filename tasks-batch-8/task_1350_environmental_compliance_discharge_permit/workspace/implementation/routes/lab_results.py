"""LabResult endpoints + validation cascade (exceedance detection)."""

import uuid
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_SAMPLE_NOT_FOUND,
    ERR_RESULT_NOT_FOUND,
    ERR_SAMPLE_NOT_IN_LAB,
    ERR_CUSTODY_NOT_ANALYZED,
    ERR_PARAMETER_MISMATCH,
    ERR_UNIT_MISMATCH,
    ERR_RESULT_NOT_SUBMITTED,
    ERR_RESULT_NOT_REJECTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_HOLDING_TIME_EXCEEDED,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields, parse_iso, dec, check_enum, round_half_up
from services.core import (
    base_entity,
    touch,
    append_audit,
    serialize_lab_result,
    paginate,
    recompute_permit_rollup,
    HOLDING_TIME_HOURS,
    CA_DEADLINE_DAYS,
    PARAMETER_CODES,
    UNITS,
    QUALIFIERS,
)

bp = Blueprint("lab_results", __name__)


def _governing_daily_max(outfall_id, parameter_code, at):
    """The ACTIVE DAILY_MAX limit covering `at` (half-open range)."""
    for lim in db.effluent_limits.values():
        if (
            lim["outfall_id"] == outfall_id
            and lim["status"] == "ACTIVE"
            and lim["parameter_code"] == parameter_code
            and lim["limit_type"] == "DAILY_MAX"
            and lim["effective_from"] <= at
            and (lim["effective_to"] is None or at < lim["effective_to"])
        ):
            return lim
    return None


@bp.route("/npdes/lab-results", methods=["POST"])
def create_lab_result():
    user_id, role = require_roles(["LabAnalyst"])
    body = get_body()
    require_fields(
        body,
        [
            "sampling_event_id",
            "parameter_code",
            "reported_value",
            "unit",
            "method_detection_limit",
            "flow_mgd",
            "analyzed_at",
        ],
    )
    ev = db.sampling_events.get(body["sampling_event_id"])
    if ev is None:
        raise err(ERR_SAMPLE_NOT_FOUND, 404, "SamplingEvent not found")

    check_enum(body["parameter_code"], PARAMETER_CODES, "parameter_code")
    check_enum(body["unit"], UNITS, "unit")
    qualifier = body.get("qualifier", "NONE")
    check_enum(qualifier, QUALIFIERS, "qualifier")

    reported_value = dec(body["reported_value"])
    if reported_value < 0:
        raise err(ERR_INVALID_REQUEST, 400, "reported_value must be >= 0")
    mdl = dec(body["method_detection_limit"])
    if mdl <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "method_detection_limit must be strictly greater than zero")
    flow_mgd = dec(body["flow_mgd"])
    if flow_mgd <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "flow_mgd must be strictly greater than zero")
    analyzed_at = parse_iso(body["analyzed_at"], "analyzed_at")

    # Safety gate: custody in {LAB_RECEIVED, ANALYZED}
    if ev["custody_status"] not in ("LAB_RECEIVED", "ANALYZED"):
        raise err(ERR_SAMPLE_NOT_IN_LAB, 409, "Sample custody is not in the lab")

    # Referential checks
    if body["parameter_code"] != ev["parameter_code"]:
        raise err(ERR_PARAMETER_MISMATCH, 400, "parameter_code differs from the sampling event's parameter")
    # unit must equal the governing ACTIVE limit's unit when one exists
    governing = None
    if ev["collected_at"] is not None:
        governing = _governing_daily_max(ev["outfall_id"], ev["parameter_code"], ev["collected_at"])
    if governing is not None and body["unit"] != governing["unit"]:
        raise err(ERR_UNIT_MISMATCH, 400, "unit differs from the governing ACTIVE limit's unit")

    result = base_entity("LabResult")
    result["id"] = str(uuid.uuid4())
    result.update(
        {
            "sampling_event_id": ev["id"],
            "parameter_code": body["parameter_code"],
            "reported_value": reported_value,
            "unit": body["unit"],
            "method_detection_limit": mdl,
            "qualifier": qualifier,
            "flow_mgd": flow_mgd,
            "analyzed_at": analyzed_at,
            "analyzed_by_user_id": user_id,
            "validation_status": "SUBMITTED",
            "validated_by_user_id": None,
            "validated_at": None,
            "rejection_reason": None,
            "exceeds_limit": None,
            "exceedance_id": None,
        }
    )
    db.lab_results[result["id"]] = result
    append_audit("LabResult", result["id"], "RESULT_RECORDED", user_id, role)
    return success(serialize_lab_result(result), 201)


@bp.route("/npdes/lab-results", methods=["GET"])
def list_lab_results():
    require_roles(["Any"])
    items = list(db.lab_results.values())
    sid = request.args.get("sampling_event_id")
    if sid:
        items = [r for r in items if r["sampling_event_id"] == sid]
    eid = request.args.get("exceedance_id")
    if eid:
        items = [r for r in items if r.get("exceedance_id") == eid]
    vs = request.args.get("validation_status")
    if vs:
        items = [r for r in items if r["validation_status"] == vs]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_lab_result(r) for r in page], total, limit, offset)


@bp.route("/npdes/lab-results/<rid>", methods=["GET"])
def get_lab_result(rid):
    require_roles(["Any"])
    result = db.lab_results.get(rid)
    if result is None:
        raise err(ERR_RESULT_NOT_FOUND, 404, "LabResult not found")
    return success(serialize_lab_result(result), 200)


@bp.route("/npdes/lab-results/<rid>/validate", methods=["POST"])
def validate_lab_result(rid):
    user_id, role = require_roles(["LabValidator"])
    result = db.lab_results.get(rid)
    if result is None:
        raise err(ERR_RESULT_NOT_FOUND, 404, "LabResult not found")
    # State guard
    if result["validation_status"] != "SUBMITTED":
        raise err(ERR_RESULT_NOT_SUBMITTED, 409, "LabResult is not SUBMITTED")
    # Segregation of duties
    if user_id == result["analyzed_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403, "Validator must differ from the recording analyst")
    # Custody position gate
    ev = db.sampling_events.get(result["sampling_event_id"])
    if ev is None:
        raise err(ERR_SAMPLE_NOT_FOUND, 404, "SamplingEvent not found")
    if ev["custody_status"] != "ANALYZED":
        raise err(ERR_CUSTODY_NOT_ANALYZED, 409, "Sample custody has not reached ANALYZED")
    # Holding time
    if ev["collected_at"] is not None:
        elapsed_hours = (result["analyzed_at"] - ev["collected_at"]).total_seconds() / 3600.0
        allowance = HOLDING_TIME_HOURS[result["parameter_code"]]
        if elapsed_hours > allowance:
            raise err(ERR_HOLDING_TIME_EXCEEDED, 422, "Analysis exceeded the parameter's holding time")

    now = db.clock.now()
    result["validated_by_user_id"] = user_id
    result["validated_at"] = now
    result["validation_status"] = "VALIDATED"

    # Exceedance detection
    comparison = result["method_detection_limit"] if result["qualifier"] == "BELOW_MDL" else result["reported_value"]
    governing = None
    if ev["collected_at"] is not None:
        governing = _governing_daily_max(ev["outfall_id"], result["parameter_code"], ev["collected_at"])

    if governing is not None and comparison > governing["limit_value"]:
        result["exceeds_limit"] = True
        # Create the exceedance (link 1)
        percent_over = round_half_up(
            (comparison - governing["limit_value"]) / governing["limit_value"] * 100, 2
        )
        exc = base_entity("Exceedance")
        exc["id"] = str(uuid.uuid4())
        exc.update(
            {
                "lab_result_id": result["id"],
                "effluent_limit_id": governing["id"],
                "outfall_id": ev["outfall_id"],
                "parameter_code": result["parameter_code"],
                "reported_value": comparison,
                "limit_value": governing["limit_value"],
                "percent_over": percent_over,
                "detected_at": now,
                "oral_notification_due_at": now + timedelta(hours=24),
                "written_report_due_at": now + timedelta(hours=120),
                "notification_status": "PENDING_ORAL",
                "enforcement_status": "NONE",
                "oral_notified_at": None,
                "written_filed_at": None,
                "corrective_action_id": None,
            }
        )
        db.exceedances[exc["id"]] = exc
        result["exceedance_id"] = exc["id"]
        append_audit("Exceedance", exc["id"], "EXCEEDANCE_DETECTED", user_id, role)

        # Link 2: auto-create a CorrectiveAction (source EXCEEDANCE, severity MAJOR, OPEN)
        ca = base_entity("CorrectiveAction")
        ca["id"] = str(uuid.uuid4())
        outfall = db.outfalls.get(ev["outfall_id"])
        ca.update(
            {
                "source_type": "EXCEEDANCE",
                "inspection_id": None,
                "exceedance_id": exc["id"],
                "description": (
                    f"Effluent limit exceedance detected for parameter {result['parameter_code']}: "
                    f"comparison value {comparison} exceeds DAILY_MAX limit {governing['limit_value']}."
                ),
                "severity": "MAJOR",
                "deadline_at": ca["created_at"] + timedelta(days=CA_DEADLINE_DAYS["MAJOR"]),
                "status": "OPEN",
                "resolved_at": None,
                "resolved_by_user_id": None,
                "actual_cost_cents": None,
                "verified_by_user_id": None,
            }
        )
        db.corrective_actions[ca["id"]] = ca
        exc["corrective_action_id"] = ca["id"]
        append_audit("CorrectiveAction", ca["id"], "CA_CREATED", user_id, role)

        # Link 3: bubble up to permit counters/posture
        if outfall is not None:
            recompute_permit_rollup(outfall["permit_id"])
    else:
        result["exceeds_limit"] = False
        outfall = db.outfalls.get(ev["outfall_id"])
        if outfall is not None:
            recompute_permit_rollup(outfall["permit_id"])

    touch(result)
    append_audit("LabResult", result["id"], "RESULT_VALIDATED", user_id, role)

    # Sample auto-close: every LabResult of the sample VALIDATED, none SUBMITTED/REJECTED
    siblings = [r for r in db.lab_results.values() if r["sampling_event_id"] == ev["id"]]
    if (
        ev["schedule_status"] == "COLLECTED"
        and len(siblings) > 0
        and all(r["validation_status"] == "VALIDATED" for r in siblings)
    ):
        ev["schedule_status"] = "CLOSED"
        touch(ev)
        append_audit("SamplingEvent", ev["id"], "SAMPLE_CLOSED", "system", "system")

    return success(serialize_lab_result(result), 200)


@bp.route("/npdes/lab-results/<rid>/reject", methods=["POST"])
def reject_lab_result(rid):
    user_id, role = require_roles(["LabValidator"])
    result = db.lab_results.get(rid)
    if result is None:
        raise err(ERR_RESULT_NOT_FOUND, 404, "LabResult not found")
    if result["validation_status"] != "SUBMITTED":
        raise err(ERR_RESULT_NOT_SUBMITTED, 409, "LabResult is not SUBMITTED")
    if user_id == result["analyzed_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403, "Validator must differ from the recording analyst")
    body = get_body()
    reason = body.get("reason")
    if reason is None:
        raise err(ERR_INVALID_REQUEST, 400, "reason is required")
    result["validation_status"] = "REJECTED"
    result["rejection_reason"] = reason
    touch(result)
    append_audit("LabResult", result["id"], "RESULT_REJECTED", user_id, role)
    return success(serialize_lab_result(result), 200)


@bp.route("/npdes/lab-results/<rid>/resubmit", methods=["POST"])
def resubmit_lab_result(rid):
    user_id, role = require_roles(["LabAnalyst"])
    result = db.lab_results.get(rid)
    if result is None:
        raise err(ERR_RESULT_NOT_FOUND, 404, "LabResult not found")
    if result["validation_status"] != "REJECTED":
        raise err(ERR_RESULT_NOT_REJECTED, 409, "LabResult is not REJECTED")
    body = get_body()
    if "reported_value" in body and body["reported_value"] is not None:
        rv = dec(body["reported_value"])
        if rv < 0:
            raise err(ERR_INVALID_REQUEST, 400, "reported_value must be >= 0")
        result["reported_value"] = rv
    if "qualifier" in body and body["qualifier"] is not None:
        check_enum(body["qualifier"], QUALIFIERS, "qualifier")
        result["qualifier"] = body["qualifier"]
    if "analyzed_at" in body and body["analyzed_at"] is not None:
        result["analyzed_at"] = parse_iso(body["analyzed_at"], "analyzed_at")
    result["validation_status"] = "SUBMITTED"
    result["analyzed_by_user_id"] = user_id
    result["rejection_reason"] = None
    touch(result)
    append_audit("LabResult", result["id"], "RESULT_RESUBMITTED", user_id, role)
    return success(serialize_lab_result(result), 200)
