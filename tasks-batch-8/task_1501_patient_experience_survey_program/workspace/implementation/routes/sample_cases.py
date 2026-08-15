"""SampleCase endpoints (PRD 3.3, 3.4): sampling with the full validation
pipeline, bulk import, list/get, responses sub-list, mark-undeliverable."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CYCLE_NOT_SAMPLING_OPEN,
    ERR_NO_ACTIVE_VENDOR,
    ERR_DISCHARGE_NOT_ELIGIBLE,
    ERR_CROSS_PROGRAM_REFERENCE,
    ERR_DISCHARGE_OUTSIDE_WINDOW,
    ERR_DISCHARGE_ALREADY_SAMPLED,
    ERR_MODE_NOT_ALLOWED,
    ERR_SAMPLE_TARGET_REACHED,
    ERR_VENDOR_BUDGET_EXCEEDED,
    ERR_CYCLE_NOT_FIELDING,
    ERR_CASE_NOT_IN_FIELD,
    ERR_VENDOR_CASE_MISMATCH,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import sample_case_view, response_view
from services.core import (
    active_vendor_for_program,
    recompute_cycle_derived,
    recompute_vendor_budget,
    CASE_LIVE_FOR_TARGET,
)
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    require_enum, require_id_list, get_or_404, parse_pagination, paginate,
    sort_created, query_arg, parse_iso_date,
)

bp = Blueprint("sample_cases", __name__)

MODES = {"MAIL", "PHONE"}
CREATE_FIELDS = {"cycle_id", "discharge_id", "mode_assigned", "postage_cost_cents"}
IMPORT_FIELDS = {"cycle_id", "discharge_ids", "mode_assigned", "postage_cost_cents"}


def _mode_allowed(admin_mode: str, mode: str) -> bool:
    if admin_mode == "MAIL_ONLY":
        return mode == "MAIL"
    if admin_mode == "PHONE_ONLY":
        return mode == "PHONE"
    return True  # MIXED_MODE permits either


def _validate_sample_item(cycle: dict, discharge: dict, program: dict,
                          vendor, mode: str, postage: int,
                          live_count_so_far: int, budget_remaining_so_far: int,
                          batch_discharge_ids: set) -> None:
    """One sampling candidate through the PRD 2.6 pipeline (tiers 4-12)."""
    # (tier 4) cycle posture, then program vendor posture.
    if cycle["status"] != "SAMPLING_OPEN":
        raise_err(ERR_CYCLE_NOT_SAMPLING_OPEN,
                  "Sample cases can only be created while the cycle is SAMPLING_OPEN")
    if vendor is None:
        raise_err(ERR_NO_ACTIVE_VENDOR,
                  "Program has no ACTIVE vendor to charge sample cases to")
    # (tier 5) patient protection: only ELIGIBLE discharges may be sampled.
    if discharge["status"] != "ELIGIBLE":
        raise_err(ERR_DISCHARGE_NOT_ELIGIBLE,
                  "Only ELIGIBLE discharges may be sampled")
    # (tier 6) referential scope.
    if discharge["program_id"] != cycle["program_id"]:
        raise_err(ERR_CROSS_PROGRAM_REFERENCE,
                  "Discharge belongs to a different program than the cycle")
    # (tier 7) sampling window, both boundaries inclusive.
    d_date = parse_iso_date(discharge["discharge_date"])
    if not (parse_iso_date(cycle["discharge_window_start"]) <= d_date
            <= parse_iso_date(cycle["discharge_window_end"])):
        raise_err(ERR_DISCHARGE_OUTSIDE_WINDOW,
                  "discharge_date is outside the cycle's sampling window")
    # (tier 8) uniqueness / quota / format constraints.
    if discharge["id"] in batch_discharge_ids:
        raise_err(ERR_DISCHARGE_ALREADY_SAMPLED,
                  "Discharge is already referenced by a sample case in a non-VOIDED cycle")
    for case in db.sample_cases.values():
        if case["discharge_id"] != discharge["id"]:
            continue
        other_cycle = db.cycles.get(case["cycle_id"])
        if other_cycle is not None and other_cycle["status"] != "VOIDED":
            raise_err(ERR_DISCHARGE_ALREADY_SAMPLED,
                      "Discharge is already referenced by a sample case in a non-VOIDED cycle")
    if not _mode_allowed(program["admin_mode"], mode):
        raise_err(ERR_MODE_NOT_ALLOWED,
                  f"mode_assigned {mode} is not permitted by the program's admin_mode")
    if live_count_so_far >= cycle["target_sample_size"]:
        raise_err(ERR_SAMPLE_TARGET_REACHED,
                  "The cycle's target_sample_size has been reached")
    # (tier 9) fiscal: budget check per item, in listed order.
    if postage > budget_remaining_so_far:
        raise_err(ERR_VENDOR_BUDGET_EXCEEDED,
                  "postage_cost_cents exceeds the vendor's remaining cycle budget")


def _create_case(cycle: dict, discharge: dict, vendor, mode: str, postage: int) -> dict:
    case = db.stamp_new({
        "cycle_id": cycle["id"],
        "discharge_id": discharge["id"],
        "vendor_id": vendor["id"],
        "unit_id": discharge["unit_id"],
        "provider_id": discharge["provider_id"],
        "mode_assigned": mode,
        "postage_cost_cents": postage,
        "billing_status": "CHARGED",
        "status": "SAMPLED",
    })
    db.sample_cases[case["id"]] = case
    return case


def _live_target_count(cycle_id: str) -> int:
    return sum(1 for c in db.sample_cases.values()
               if c["cycle_id"] == cycle_id and c["status"] in CASE_LIVE_FOR_TARGET)


@bp.route("/api/sample-cases", methods=["POST"])
@require_roles("DataSteward")
def create_sample_case(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    cycle_id = require_string(body, "cycle_id")
    discharge_id = require_string(body, "discharge_id")
    mode = require_enum(body, "mode_assigned", MODES)
    postage = require_int(body, "postage_cost_cents", minimum=1)

    cycle = get_or_404(db.cycles, cycle_id, "SurveyCycle")
    discharge = get_or_404(db.discharges, discharge_id, "Discharge")
    program = db.programs.get(cycle["program_id"])
    vendor = active_vendor_for_program(cycle["program_id"])

    _validate_sample_item(cycle, discharge, program, vendor, mode, postage,
                          _live_target_count(cycle["id"]),
                          vendor["cycle_budget_remaining_cents"] if vendor else 0,
                          set())

    case = _create_case(cycle, discharge, vendor, mode, postage)
    recompute_vendor_budget(vendor)
    db.touch(vendor)
    return success_object(sample_case_view(case), 201)


@bp.route("/api/sample-cases/import", methods=["POST"])
@require_roles("DataSteward")
def import_sample_cases(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, IMPORT_FIELDS)
    cycle_id = require_string(body, "cycle_id")
    discharge_ids = require_id_list(body, "discharge_ids", minimum=1, maximum=500)
    mode = require_enum(body, "mode_assigned", MODES)
    postage = require_int(body, "postage_cost_cents", minimum=1)

    cycle = get_or_404(db.cycles, cycle_id, "SurveyCycle")
    program = db.programs.get(cycle["program_id"])
    vendor = active_vendor_for_program(cycle["program_id"])

    # Atomic: validate every item in listed order before creating any.
    live_count = _live_target_count(cycle["id"])
    budget_remaining = vendor["cycle_budget_remaining_cents"] if vendor else 0
    batch_ids: set = set()
    validated = []
    for discharge_id in discharge_ids:
        discharge = get_or_404(db.discharges, discharge_id, "Discharge")
        _validate_sample_item(cycle, discharge, program, vendor, mode, postage,
                              live_count, budget_remaining, batch_ids)
        batch_ids.add(discharge_id)
        live_count += 1
        budget_remaining -= postage
        validated.append(discharge)

    created_ids = []
    for discharge in validated:
        case = _create_case(cycle, discharge, vendor, mode, postage)
        created_ids.append(case["id"])
    if vendor is not None:
        recompute_vendor_budget(vendor)
        db.touch(vendor)

    return success_object({
        "created_count": len(created_ids),
        "sample_case_ids": created_ids,
    }, 201)


@bp.route("/api/sample-cases", methods=["GET"])
@require_roles("Any")
def list_sample_cases(_user_id: str, _role: str):
    items = list(db.sample_cases.values())
    for param in ("cycle_id", "discharge_id", "vendor_id", "unit_id", "provider_id", "status"):
        value = query_arg(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([sample_case_view(c) for c in page], limit, offset, total)


@bp.route("/api/sample-cases/<caseId>", methods=["GET"])
@require_roles("Any")
def get_sample_case(caseId: str, _user_id: str, _role: str):
    case = get_or_404(db.sample_cases, caseId, "SampleCase")
    return success_object(sample_case_view(case))


@bp.route("/api/sample-cases/<caseId>/responses", methods=["GET"])
@require_roles("Any")
def list_case_responses(caseId: str, _user_id: str, _role: str):
    case = get_or_404(db.sample_cases, caseId, "SampleCase")
    items = [r for r in db.responses.values() if r["case_id"] == case["id"]]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([response_view(r) for r in page], limit, offset, total)


@bp.route("/api/sample-cases/<caseId>/mark-undeliverable", methods=["POST"])
@require_roles("VendorOperator")
def mark_undeliverable(caseId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    case = get_or_404(db.sample_cases, caseId, "SampleCase")
    # Entity-backed ownership (priority 2.5).
    if _user_id != case["vendor_id"]:
        raise_err(ERR_VENDOR_CASE_MISMATCH,
                  "VendorOperator may only act on cases owned by their vendor")
    cycle = db.cycles.get(case["cycle_id"])
    # Cycle-posture errors precede entity-local state errors (PRD 2.6 tier 7).
    if cycle is None or cycle["status"] != "FIELDING":
        raise_err(ERR_CYCLE_NOT_FIELDING,
                  "mark-undeliverable requires the parent cycle to be FIELDING")
    if case["status"] != "IN_FIELD":
        raise_err(ERR_CASE_NOT_IN_FIELD,
                  "Only an IN_FIELD case can be marked undeliverable")

    case["status"] = "UNDELIVERABLE"
    credited = False
    if case["billing_status"] == "CHARGED":
        case["billing_status"] = "CREDITED"
        credited = True
    db.touch(case)

    if credited:
        vendor = db.vendors.get(case["vendor_id"])
        if vendor is not None:
            recompute_vendor_budget(vendor)
            db.touch(vendor)
    if cycle is not None:
        recompute_cycle_derived(cycle)
        db.touch(cycle)

    return success_object(sample_case_view(case))
