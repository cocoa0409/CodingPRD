"""Audit + PenaltyAssessment routes."""
import math
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store, new_id, now_iso
from middleware import get_auth, require_role, get_body, req_string, req_int, apply_pagination
from response import success_object, success_list
from errors import not_found, invalid_request, invalid_state, ApiError
from services.core import (
    touch, round4, round0, recompute_program_posture, enrolled_overlapping_members,
)

bp = Blueprint("audits", __name__)

ENCOUNTERS_PER_MEMBER_MONTH = Decimal("0.5")
RATE_PER_POINT_CENTS = 50000


def audit_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "cycle_id": a["cycle_id"],
        "sample_size": a["sample_size"],
        "defect_count": a["defect_count"],
        "completeness_intake_rate": a["completeness_intake_rate"],
        "completeness_eligibility_rate": a["completeness_eligibility_rate"],
        "accuracy_rate": a["accuracy_rate"],
        "determination": a["determination"],
        "status": a["status"],
    }


def penalty_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "cycle_id": p["cycle_id"],
        "audit_id": p["audit_id"],
        "reason": p["reason"],
        "amount_cents": p["amount_cents"],
        "reduced_amount_cents": p["reduced_amount_cents"],
        "status": p["status"],
    }


@bp.route("/programs/audits", methods=["POST"])
def create_audit():
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    body = get_body()
    cycle_id = req_string(body, "cycle_id")
    sample_size = req_int(body, "sample_size")
    defect_count = req_int(body, "defect_count")
    if sample_size < 0 or defect_count < 0:
        raise invalid_request("sample_size and defect_count must not be negative")
    cycle = store.cycles.get(cycle_id)
    if cycle is None:
        raise not_found("cycle not found")
    # uniqueness examined before sample sanity
    for a in store.audits.values():
        if a["cycle_id"] == cycle_id:
            raise ApiError("ERR_AUDIT_EXISTS", "An audit already exists for the cycle", 409)
    if sample_size < 1 or defect_count > sample_size:
        raise ApiError("ERR_AUDIT_SAMPLE_INVALID",
                       "sample_size < 1 or defect_count outside [0, sample_size]", 422)
    aid = new_id()
    a = {
        "id": aid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "cycle_id": cycle_id,
        "sample_size": sample_size,
        "defect_count": defect_count,
        "completeness_intake_rate": None,
        "completeness_eligibility_rate": None,
        "accuracy_rate": None,
        "determination": None,
        "status": "DRAFT",
    }
    store.audits[aid] = a
    return success_object(audit_view(a), 201)


@bp.route("/programs/audits/<aid>", methods=["GET"])
def get_audit(aid):
    get_auth()
    a = store.audits.get(aid)
    if a is None:
        raise not_found()
    return success_object(audit_view(a))


@bp.route("/programs/audits", methods=["GET"])
def list_audits():
    get_auth()
    cycle_id = request.args.get("cycle_id")
    status = request.args.get("status")
    items = list(store.audits.values())
    if cycle_id is not None:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = apply_pagination(items)
    return success_list([audit_view(a) for a in page], limit, offset, total)


@bp.route("/programs/audits/<aid>/determine", methods=["POST"])
def determine_audit(aid):
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    get_body(required=False)
    a = store.audits.get(aid)
    if a is None:
        raise not_found()
    if a["status"] != "DRAFT":
        raise invalid_state("Audit is not DRAFT")
    cycle = store.cycles.get(a["cycle_id"])
    if cycle is None:
        raise not_found("cycle not found")
    # statement must exist (penalty cap base)
    statement = None
    for s in store.statements.values():
        if s["cycle_id"] == a["cycle_id"]:
            statement = s
            break
    if statement is None:
        raise ApiError("ERR_STATEMENT_REQUIRED",
                       "Audit determine requires the cycle's capitation statement to exist", 409)

    program = store.programs.get(cycle["program_id"])

    numerator = cycle["net_accepted_encounter_count"]
    intake = cycle["intake_encounter_count"]
    if intake == 0:
        completeness_intake_rate = 0.0
    else:
        completeness_intake_rate = round4(Decimal(numerator) / Decimal(intake))

    members = enrolled_overlapping_members(cycle["program_id"], cycle["_window_start_at"], cycle["_window_end_at"])
    member_months = len(members)
    # expected = ceil(member_months * ENCOUNTERS_PER_MEMBER_MONTH)
    expected = math.ceil(member_months * float(ENCOUNTERS_PER_MEMBER_MONTH))
    if expected == 0:
        completeness_eligibility_rate = 0.0
    else:
        completeness_eligibility_rate = round4(Decimal(numerator) / Decimal(expected))

    accuracy_rate = round4(Decimal(1) - Decimal(a["defect_count"]) / Decimal(a["sample_size"]))

    comp_pass = Decimal(str(completeness_eligibility_rate)) >= Decimal(str(program["completeness_threshold"]))
    acc_pass = Decimal(str(accuracy_rate)) >= Decimal(str(program["accuracy_threshold"]))
    determination = "PASS" if (comp_pass and acc_pass) else "FAIL"

    a["completeness_intake_rate"] = completeness_intake_rate
    a["completeness_eligibility_rate"] = completeness_eligibility_rate
    a["accuracy_rate"] = accuracy_rate
    a["determination"] = determination
    a["status"] = "DETERMINED"
    touch(a)

    if determination == "FAIL":
        # penalty cascade
        if not comp_pass and not acc_pass:
            reason = "COMBINED"
        elif not comp_pass:
            reason = "COMPLETENESS"
        else:
            reason = "ACCURACY"
        comp_deficit = max(Decimal("0"), Decimal(str(program["completeness_threshold"])) - Decimal(str(completeness_eligibility_rate))) * 100
        acc_deficit = max(Decimal("0"), Decimal(str(program["accuracy_threshold"])) - Decimal(str(accuracy_rate))) * 100
        deficient_points = comp_deficit + acc_deficit
        raw_cents = int((deficient_points * RATE_PER_POINT_CENTS).to_integral_value(rounding=ROUND_HALF_UP))
        cap_cents = round0(Decimal(str(program["penalty_cap_percent"])) * Decimal(statement["provisional_paid_cents"]))
        amount = min(raw_cents, cap_cents)
        pid = new_id()
        penalty = {
            "id": pid,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
            "program_id": program["id"],
            "cycle_id": cycle["id"],
            "audit_id": a["id"],
            "reason": reason,
            "amount_cents": amount,
            "reduced_amount_cents": None,
            "status": "ASSESSED",
        }
        store.penalties[pid] = penalty
        recompute_program_posture(program)

    return success_object(audit_view(a))


# ---------------------------------------------------------------- penalties ---

@bp.route("/programs/penalties/<pid>", methods=["GET"])
def get_penalty(pid):
    get_auth()
    p = store.penalties.get(pid)
    if p is None:
        raise not_found()
    return success_object(penalty_view(p))


@bp.route("/programs/penalties", methods=["GET"])
def list_penalties():
    get_auth()
    cycle_id = request.args.get("cycle_id")
    audit_id = request.args.get("audit_id")
    status = request.args.get("status")
    items = list(store.penalties.values())
    if cycle_id is not None:
        items = [p for p in items if p["cycle_id"] == cycle_id]
    if audit_id is not None:
        items = [p for p in items if p["audit_id"] == audit_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = apply_pagination(items)
    return success_list([penalty_view(p) for p in page], limit, offset, total)


@bp.route("/programs/penalties/<pid>/appeal", methods=["POST"])
def appeal_penalty(pid):
    _, role = get_auth()
    require_role(role, {"McoCompliance"})
    get_body(required=False)
    p = store.penalties.get(pid)
    if p is None:
        raise not_found()
    if p["status"] != "ASSESSED":
        raise invalid_state("Penalty is not ASSESSED")
    p["status"] = "APPEALED"
    touch(p)
    return success_object(penalty_view(p))


@bp.route("/programs/penalties/<pid>/resolve", methods=["POST"])
def resolve_penalty(pid):
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    body = get_body()
    decision = req_string(body, "decision")
    if decision not in ("UPHELD", "WAIVED", "REDUCED"):
        raise invalid_request("decision must be one of UPHELD, WAIVED, REDUCED")
    reduced_amount_cents = body.get("reduced_amount_cents")
    if decision == "REDUCED":
        if reduced_amount_cents is None:
            raise invalid_request("reduced_amount_cents is required when decision is REDUCED")
        if isinstance(reduced_amount_cents, bool) or not isinstance(reduced_amount_cents, int):
            raise invalid_request("reduced_amount_cents must be an integer")
    elif reduced_amount_cents is not None:
        if isinstance(reduced_amount_cents, bool) or not isinstance(reduced_amount_cents, int):
            raise invalid_request("reduced_amount_cents must be an integer")
    p = store.penalties.get(pid)
    if p is None:
        raise not_found()
    # range check for REDUCED happens at request-validity stage, ahead of state check
    if decision == "REDUCED":
        if not (0 <= reduced_amount_cents < p["amount_cents"]):
            raise invalid_request("reduced_amount_cents out of range")
    if p["status"] != "APPEALED":
        raise invalid_state("Penalty is not APPEALED")
    program = store.programs.get(p["program_id"])
    if decision == "UPHELD":
        p["status"] = "UPHELD"
        touch(p)
    elif decision == "WAIVED":
        p["status"] = "WAIVED"
        touch(p)
        if program is not None:
            recompute_program_posture(program)
    else:  # REDUCED
        p["status"] = "REDUCED"
        p["reduced_amount_cents"] = reduced_amount_cents
        touch(p)
        if program is not None:
            recompute_program_posture(program)
    return success_object(penalty_view(p))


@bp.route("/programs/penalties/<pid>/pay", methods=["POST"])
def pay_penalty(pid):
    _, role = get_auth()
    require_role(role, {"McoFinance"})
    get_body(required=False)
    p = store.penalties.get(pid)
    if p is None:
        raise not_found()
    if p["status"] not in ("ASSESSED", "UPHELD", "REDUCED"):
        raise invalid_state("Penalty is not in a payable state (ASSESSED, UPHELD, or REDUCED)")
    p["status"] = "PAID"
    touch(p)
    program = store.programs.get(p["program_id"])
    if program is not None:
        recompute_program_posture(program)
    return success_object(penalty_view(p))
