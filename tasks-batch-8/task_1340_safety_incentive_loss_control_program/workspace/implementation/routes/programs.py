"""SafetyProgram lifecycle: create/list/read, OCC-guarded config patch,
activate, close, reconcile, sweep, leading indicators (PRD 3.1, 3.4, 3.7, 3.8)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES, NON_CONTRACTOR_ROLES
from response import ok, ok_list
from services import core, ops

bp = Blueprint("programs", __name__)

_HAZARD_CLASSES = ("LOW", "MODERATE", "HIGH")
_SCORING_VARIANTS = ("LEADING_ONLY", "BALANCED")


def _validate_rate_card(body, name, value_key, integer_values):
    entries = core.req_list(body, name)
    for e in entries:
        if not isinstance(e, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           f"{name} entries must be objects")
        hc = e.get("hazard_class")
        if hc not in _HAZARD_CLASSES:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           f"{name}.hazard_class must be LOW|MODERATE|HIGH")
        v = e.get(value_key)
        if integer_values:
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               f"{name}.{value_key} must be a non-negative integer")
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               f"{name}.{value_key} must be a non-negative number")
    return entries


@bp.route("/safety/programs", methods=["POST"])
def create_program():
    auth(["EHSAdmin"])
    body = core.body_json()
    program_year = core.req_int(body, "program_year")
    scoring_variant = core.req_enum(body, "scoring_variant", _SCORING_VARIANTS)
    budget = core.req_int(body, "incentive_budget_cents", minimum=0)
    target_rate = core.req_num(body, "observation_target_rate", minimum=0)
    exposure = core.req_int(body, "exposure_hours", minimum=0)
    payroll = _validate_rate_card(body, "payroll_by_class", "payroll_cents", True)
    elr = _validate_rate_card(body, "elr_by_class", "elr", False)
    floor = core.opt_num(body, "near_miss_floor_ratio", default=0.20, minimum=0)
    quorum = core.opt_int(body, "quorum_min", default=5, minimum=0)

    p = core.stamp_new({
        "id": core.new_id(),
        "program_year": program_year,
        "scoring_variant": scoring_variant,
        "incentive_budget_cents": budget,
        "remaining_budget_cents": budget,
        "observation_target_rate": target_rate,
        "near_miss_floor_ratio": floor,
        "quorum_min": quorum,
        "exposure_hours": exposure,
        "payroll_by_class": payroll,
        "elr_by_class": elr,
        "status": "DRAFT",
        "posture": "NORMAL",
        "overdue_control_count": 0,
        "sla_breach_count": 0,
        "integrity_flag": False,
        "sweep_index": 0,
    })
    db.DB["programs"][p["id"]] = p
    return ok(core.program_view(p), 201)


@bp.route("/safety/programs", methods=["GET"])
def list_programs():
    auth(ALL_ROLES)
    status = request.args.get("status")
    year = request.args.get("program_year")
    items = list(db.DB["programs"].values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if year is not None:
        try:
            yv = int(year)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid program_year filter")
        items = [p for p in items if p["program_year"] == yv]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.program_view(p) for p in page], total, limit, offset)


@bp.route("/safety/programs/<pid>", methods=["GET"])
def get_program(pid):
    auth(ALL_ROLES)
    p = core.get_or_404("programs", pid, "SafetyProgram")
    return ok(core.program_view(p))


@bp.route("/safety/programs/<pid>/incentive-config", methods=["PATCH"])
def patch_incentive_config(pid):
    auth(["EHSAdmin"])
    p = core.get_or_404("programs", pid, "SafetyProgram")
    body = core.body_json()
    expected = core.req_int(body, "expected_program_version")
    # State/phase gate before the OCC comparison (validation priority 5).
    if p["status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_DRAFT", 409,
                       "Incentive config is writable only while the program is DRAFT")
    if expected != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_program_version does not match the program version")

    if "incentive_budget_cents" in body and body["incentive_budget_cents"] is not None:
        new_budget = core.req_int(body, "incentive_budget_cents", minimum=0)
        p["incentive_budget_cents"] = new_budget
        # No awards can exist while DRAFT: remaining tracks the budget change.
        p["remaining_budget_cents"] = new_budget
    if "observation_target_rate" in body and body["observation_target_rate"] is not None:
        p["observation_target_rate"] = core.req_num(
            body, "observation_target_rate", minimum=0)
    if "near_miss_floor_ratio" in body and body["near_miss_floor_ratio"] is not None:
        p["near_miss_floor_ratio"] = core.req_num(
            body, "near_miss_floor_ratio", minimum=0)
    if "quorum_min" in body and body["quorum_min"] is not None:
        p["quorum_min"] = core.req_int(body, "quorum_min", minimum=0)
    if "exposure_hours" in body and body["exposure_hours"] is not None:
        p["exposure_hours"] = core.req_int(body, "exposure_hours", minimum=0)
    if "payroll_by_class" in body and body["payroll_by_class"] is not None:
        p["payroll_by_class"] = _validate_rate_card(
            body, "payroll_by_class", "payroll_cents", True)
    if "elr_by_class" in body and body["elr_by_class"] is not None:
        p["elr_by_class"] = _validate_rate_card(body, "elr_by_class", "elr", False)

    core.touch(p)
    return ok(core.program_view(p))


@bp.route("/safety/programs/<pid>/activate", methods=["POST"])
def activate_program(pid):
    auth(["EHSAdmin"])
    p = core.get_or_404("programs", pid, "SafetyProgram")
    core.body_json()  # tolerate an absent/empty body
    # Well-formedness tier: budget and exposure must be positive to activate.
    if p["incentive_budget_cents"] <= 0 or p["exposure_hours"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "incentive_budget_cents and exposure_hours must be > 0 to activate")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_DRAFT", 409,
                       "Only a DRAFT program can be activated")
    for other in db.DB["programs"].values():
        if other["id"] != p["id"] and other["status"] == "ACTIVE":
            raise ApiError("ERR_PROGRAM_ALREADY_ACTIVE", 409,
                           "Another SafetyProgram is already ACTIVE")
    covered_payroll = {e.get("hazard_class"): e.get("payroll_cents")
                       for e in p["payroll_by_class"]}
    covered_elr = {e.get("hazard_class") for e in p["elr_by_class"]}
    if any(covered_payroll.get(c) is None or covered_payroll[c] <= 0
           for c in _HAZARD_CLASSES) \
            or any(c not in covered_elr for c in _HAZARD_CLASSES):
        raise ApiError("ERR_PAYROLL_INCOMPLETE", 422,
                       "payroll_by_class/elr_by_class must cover LOW|MODERATE|HIGH "
                       "with positive payroll")
    p["status"] = "ACTIVE"
    p["posture"] = "NORMAL"
    core.touch(p)
    return ok(core.program_view(p))


@bp.route("/safety/programs/<pid>/close", methods=["POST"])
def close_program(pid):
    auth(["EHSAdmin"])
    p = core.get_or_404("programs", pid, "SafetyProgram")
    core.body_json()
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE program can be closed")
    # Close-out guards fire in this order (PRD 3.8 / validations 18-20).
    if any(h["program_id"] == pid and h["status"] in
           ("OPEN", "ASSESSED", "CONTROLS_PLANNED", "IN_PROGRESS",
            "PENDING_VERIFICATION") for h in db.DB["hazards"].values()):
        raise ApiError("ERR_OPEN_HAZARDS_REMAIN", 422,
                       "Hazards remain open on this program")
    if any(r["program_id"] == pid and r["status"] in
           ("ISSUED", "OVERDUE", "RESPONSE_SUBMITTED", "CARRIER_REJECTED")
           for r in db.DB["recommendations"].values()):
        raise ApiError("ERR_OPEN_RECOMMENDATIONS_REMAIN", 422,
                       "Loss-control recommendations remain open on this program")
    if any(m["program_id"] == pid and m["status"] in ("SCHEDULED", "HELD")
           for m in db.DB["meetings"].values()):
        raise ApiError("ERR_OPEN_MEETINGS_REMAIN", 422,
                       "Committee meetings remain open on this program")
    ops.close_program(p)
    return ok(core.program_view(p))


@bp.route("/safety/programs/<pid>/reconcile", methods=["POST"])
def reconcile_program(pid):
    auth(["EHSAdmin"])
    p = core.get_or_404("programs", pid, "SafetyProgram")
    core.body_json()
    if p["status"] != "CLOSED":
        raise ApiError("ERR_PROGRAM_NOT_CLOSED", 409,
                       "Only a CLOSED program can be reconciled")
    if any(a["program_id"] == pid and a["status"] in ("CALCULATED", "APPROVED")
           for a in db.DB["awards"].values()):
        raise ApiError("ERR_UNPAID_AWARDS_REMAIN", 422,
                       "Awards remain in CALCULATED or APPROVED")
    p["status"] = "RECONCILED"
    core.touch(p)
    return ok(core.program_view(p))


@bp.route("/safety/programs/<pid>/sweep", methods=["POST"])
def sweep_program(pid):
    auth(["EHSAdmin"])
    p = core.get_or_404("programs", pid, "SafetyProgram")
    body = core.body_json()
    exposure = core.opt_int(body, "exposure_hours", default=None, minimum=0)
    summary = ops.sweep_program(p, exposure_hours=exposure)
    return ok(summary)


@bp.route("/safety/programs/<pid>/leading-indicators", methods=["GET"])
def leading_indicators(pid):
    auth(NON_CONTRACTOR_ROLES)
    p = core.get_or_404("programs", pid, "SafetyProgram")
    from services import calc
    result = calc.leading_indicators(p)
    # The read refreshes the program's stored integrity flag (entities.SafetyProgram).
    p["integrity_flag"] = result["integrity_flag"]
    return ok(result)
