"""DiagnosisLine and ProcedureLine endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import sort_default, stamp_new, store, touch
from errors import (ERR_CHART_NOT_FOUND, ERR_DUPLICATE_SEQUENCE,
                    ERR_FORBIDDEN, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_POA_INVALID_FOR_CODE, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.core import (CC_LEVELS, POA_VALUES, active_dx_lines,
                           assignment_for_chart, ser_dx_line, ser_proc_line)
from validators import body, has, opt_bool, opt_enum, opt_int, req_dt, req_str

bp = Blueprint("lines", __name__)


def get_dx_or_404(line_id):
    l = store.dx_lines.get(line_id)
    if l is None:
        fail(404, ERR_INVALID_REQUEST, f"DiagnosisLine {line_id} does not exist")
    return l


def get_proc_or_404(line_id):
    p = store.proc_lines.get(line_id)
    if p is None:
        fail(404, ERR_INVALID_REQUEST, f"ProcedureLine {line_id} does not exist")
    return p


def _gate_chart_for_coding(chart_id, caller_id):
    """Chart must be IN_CODING; caller must hold the chart's live assignment.

    PRD §3.3 pins the chart-state failure to ERR_INVALID_STATE; ownership is
    checked right after (ERR_FORBIDDEN).
    """
    chart = store.charts.get(chart_id)
    if chart is None:
        fail(404, ERR_CHART_NOT_FOUND, f"Chart {chart_id} does not exist")
    if chart["status"] != "IN_CODING":
        fail(409, ERR_INVALID_STATE,
             f"Chart is {chart['status']}; lines may be captured only while IN_CODING")
    asg = assignment_for_chart(chart["id"], statuses=("IN_PROGRESS", "RETURNED"))
    if asg is None or asg["coder_id"] != caller_id:
        fail(403, ERR_FORBIDDEN,
             "Only the coder holding the chart's assignment may capture lines")
    return chart


def _check_poa_rule(poa, cc_level):
    if poa == "U" and cc_level in ("CC", "MCC"):
        fail(422, ERR_POA_INVALID_FOR_CODE,
             "poa=U is forbidden on a line with cc_level CC or MCC")


# ---------------- Diagnosis lines ----------------

@bp.route("/diagnosis-lines", methods=["POST"])
def create_dx_line():
    uid, _ = require_roles("Coder")
    b = body()
    if not has(b, "chart_id"):
        fail(400, ERR_INVALID_REQUEST, "chart_id is required")
    chart = _gate_chart_for_coding(b["chart_id"], uid)
    # etiology reference (existence tier): must resolve to a line on this chart
    is_manifestation = opt_bool(b, "is_manifestation", False)
    manifestation_of_id = b.get("manifestation_of_id")
    if manifestation_of_id is not None:
        ref = store.dx_lines.get(manifestation_of_id)
        if ref is None or ref["chart_id"] != chart["id"]:
            fail(404, ERR_INVALID_REQUEST,
                 f"manifestation_of_id {manifestation_of_id} does not resolve to a line on this chart")
    if is_manifestation and manifestation_of_id is None:
        fail(400, ERR_INVALID_REQUEST,
             "manifestation_of_id is required when is_manifestation is true")
    # POA safety rule (tier 6) on the effective values
    raw_poa = b.get("poa")
    raw_cc = b.get("cc_level")
    if isinstance(raw_poa, str) and isinstance(raw_cc, str):
        _check_poa_rule(raw_poa, raw_cc)
    elif isinstance(raw_poa, str):
        _check_poa_rule(raw_poa, "NONE")
    # required fields / enums / ranges (tier 7)
    icd_code = req_str(b, "icd_code")
    poa = opt_enum(b, "poa", POA_VALUES) if has(b, "poa") else None
    if poa is None:
        fail(400, ERR_INVALID_REQUEST, "poa is required")
    cc_level = opt_enum(b, "cc_level", CC_LEVELS, "NONE")
    sequence = b.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        fail(400, ERR_INVALID_REQUEST, "sequence is required and must be an integer")
    if sequence < 1:
        fail(400, ERR_INVALID_REQUEST, "sequence must be >= 1")
    opt_bool(b, "is_principal", False)
    if any(l["sequence"] == sequence for l in active_dx_lines(chart["id"])):
        fail(422, ERR_DUPLICATE_SEQUENCE,
             f"sequence {sequence} is already used by an ACTIVE line on this chart")
    line = stamp_new({
        "chart_id": chart["id"],
        "icd_code": icd_code,
        "poa": poa,
        "sequence": sequence,
        "is_principal": opt_bool(b, "is_principal", False),
        "cc_level": cc_level,
        "is_manifestation": is_manifestation,
        "manifestation_of_id": manifestation_of_id,
        "status": "ACTIVE",
    })
    store.dx_lines[line["id"]] = line
    return ok_obj(ser_dx_line(line), 201)


@bp.route("/diagnosis-lines/<id>", methods=["GET"])
def get_dx_line(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_dx_line(get_dx_or_404(id)), 200)


@bp.route("/diagnosis-lines", methods=["GET"])
def list_dx_lines():
    require_roles(*ALL_ROLES)
    items = list(store.dx_lines.values())
    chart_id = request.args.get("chart_id")
    if chart_id is not None:
        items = [l for l in items if l["chart_id"] == chart_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    manifestation_of_id = request.args.get("manifestation_of_id")
    if manifestation_of_id is not None:
        items = [l for l in items if l["manifestation_of_id"] == manifestation_of_id]
    return paginate([ser_dx_line(l) for l in sort_default(items)])


@bp.route("/diagnosis-lines/<id>", methods=["PATCH"])
def patch_dx_line(id):
    uid, _ = require_roles("Coder")
    line = get_dx_or_404(id)
    chart = _gate_chart_for_coding(line["chart_id"], uid)
    if line["status"] != "ACTIVE":
        fail(409, ERR_INVALID_STATE,
             f"Cannot edit a line in state {line['status']}")
    b = body()
    new_poa = b.get("poa") if has(b, "poa") else line["poa"]
    new_cc = b.get("cc_level") if has(b, "cc_level") else line["cc_level"]
    if isinstance(new_poa, str) and isinstance(new_cc, str):
        _check_poa_rule(new_poa, new_cc)  # tier 6, re-applied on edits
    # tier-7 field validation
    status = b.get("status")
    if status is not None and status != "VOID":
        fail(400, ERR_INVALID_REQUEST, "status may only be patched to VOID")
    if has(b, "poa"):
        opt_enum(b, "poa", POA_VALUES)
    if has(b, "cc_level"):
        opt_enum(b, "cc_level", CC_LEVELS)
    new_sequence = line["sequence"]
    if has(b, "sequence"):
        s = b.get("sequence")
        if isinstance(s, bool) or not isinstance(s, int) or s < 1:
            fail(400, ERR_INVALID_REQUEST, "sequence must be an integer >= 1")
        new_sequence = s
    if has(b, "is_principal") and not isinstance(b["is_principal"], bool):
        fail(400, ERR_INVALID_REQUEST, "is_principal must be a boolean")
    if new_sequence != line["sequence"] and any(
            l["sequence"] == new_sequence and l["id"] != line["id"]
            for l in active_dx_lines(chart["id"])):
        fail(422, ERR_DUPLICATE_SEQUENCE,
             f"sequence {new_sequence} is already used by an ACTIVE line on this chart")
    if has(b, "poa"):
        line["poa"] = b["poa"]
    if has(b, "cc_level"):
        line["cc_level"] = b["cc_level"]
    if has(b, "sequence"):
        line["sequence"] = new_sequence
    if has(b, "is_principal"):
        line["is_principal"] = b["is_principal"]
    if status == "VOID":
        line["status"] = "VOID"
    touch(line)
    return ok_obj(ser_dx_line(line), 200)


# ---------------- Procedure lines ----------------

@bp.route("/procedure-lines", methods=["POST"])
def create_proc_line():
    uid, _ = require_roles("Coder")
    b = body()
    if not has(b, "chart_id"):
        fail(400, ERR_INVALID_REQUEST, "chart_id is required")
    chart = _gate_chart_for_coding(b["chart_id"], uid)
    pcs_code = req_str(b, "pcs_code")
    performed_at = req_dt(b, "performed_at")
    is_or = opt_bool(b, "is_or", False)
    line = stamp_new({
        "chart_id": chart["id"],
        "pcs_code": pcs_code,
        "is_or": is_or,
        "performed_at": performed_at,
    })
    store.proc_lines[line["id"]] = line
    return ok_obj(ser_proc_line(line), 201)


@bp.route("/procedure-lines/<id>", methods=["GET"])
def get_proc_line(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_proc_line(get_proc_or_404(id)), 200)


@bp.route("/procedure-lines", methods=["GET"])
def list_proc_lines():
    require_roles(*ALL_ROLES)
    items = list(store.proc_lines.values())
    chart_id = request.args.get("chart_id")
    if chart_id is not None:
        items = [p for p in items if p["chart_id"] == chart_id]
    return paginate([ser_proc_line(p) for p in sort_default(items)])
