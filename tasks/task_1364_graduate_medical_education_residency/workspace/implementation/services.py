"""Business operations: programs, academic years, schedule blocks, complement
approvals, residents, rotations, rotation assignments.

Validation pipeline (PRD section 2.8) is honored inside each operation:
ownership/SoD (4) -> existence (5) -> OCC (6) -> state (7) -> safety (8) ->
temporal (9) -> constraints (10) -> cross-aggregate (11) -> fiscal (12).
Stages 1-3 (user context, request shape, role) run in routes.py.
"""
from datetime import timedelta
from decimal import Decimal

import calc
import core
from core import (
    get_program, get_year, get_block, get_complement, get_resident,
    get_rotation, get_assignment,
)
from db import DB, new_id
from errors import ApiError
from util import parse_dt, round0_int, dec

SPECIALTIES = [
    "INTERNAL_MEDICINE",
    "GENERAL_SURGERY",
    "PEDIATRICS",
    "EMERGENCY_MEDICINE",
    "OBSTETRICS_GYNECOLOGY",
]


def conflict(error_id, message):
    return ApiError(error_id, 409, message)


# ---------------------------------------------------------------------------
# ResidencyProgram
# ---------------------------------------------------------------------------

def create_program(data):
    rec = {
        "id": new_id(),
        "name": data["name"],
        "specialty": data["specialty"],
        "acgme_program_code": data["acgme_program_code"],
        "accreditation_status": "CONTINUED",
    }
    core.stamp(rec)
    DB["programs"][rec["id"]] = rec
    return core.pub_program(rec)


def list_programs(args):
    items = list(DB["programs"].values())
    if args.get("specialty") is not None:
        items = [p for p in items if p["specialty"] == args.get("specialty")]
    items.sort(key=lambda p: p["_seq"])
    return [core.pub_program(p) for p in items]


def get_program_view(pid):
    return core.pub_program(get_program(pid))


# ---------------------------------------------------------------------------
# AcademicYear + ScheduleBlock
# ---------------------------------------------------------------------------

def _create_blocks(year):
    """Thirteen CURRENT blocks, block i covering [start + (i-1)*28d, start + i*28d)."""
    date_only = year["_date_only"]
    for i in range(1, 14):
        b_start = year["_start"] + timedelta(days=28 * (i - 1))
        b_end = year["_start"] + timedelta(days=28 * i)
        if date_only:
            s_raw = b_start.strftime("%Y-%m-%d")
            e_raw = b_end.strftime("%Y-%m-%d")
        else:
            s_raw = b_start.strftime("%Y-%m-%dT%H:%M:%SZ")
            e_raw = b_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        blk = {
            "id": new_id(),
            "academic_year_id": year["id"],
            "block_index": i,
            "start_date": s_raw,
            "end_date": e_raw,
            "_start": b_start,
            "_end": b_end,
            "status": "CURRENT",
        }
        core.stamp(blk)
        DB["schedule_blocks"][blk["id"]] = blk


def create_year(data):
    program = get_program(data["program_id"])
    start = parse_dt(data["start_date"])
    end = parse_dt(data["end_date"])
    # Temporal: the span must equal exactly 364 days (13 x 28-day blocks).
    if end - start != timedelta(days=364):
        raise ApiError("ERR_INVALID_YEAR_SPAN", 422,
                       "Academic year span must equal exactly 364 days")
    rec = {
        "id": new_id(),
        "program_id": program["id"],
        "year_label": data["year_label"],
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "_start": start,
        "_end": end,
        "_date_only": len(data["start_date"].strip()) == 10,
        "status": "PLANNING",
    }
    core.stamp(rec)
    DB["academic_years"][rec["id"]] = rec
    _create_blocks(rec)
    return core.pub_year(rec)


def list_years(args):
    items = list(DB["academic_years"].values())
    if args.get("program_id") is not None:
        items = [y for y in items if y["program_id"] == args.get("program_id")]
    if args.get("status") is not None:
        items = [y for y in items if y["status"] == args.get("status")]
    items.sort(key=lambda y: y["_seq"])
    return [core.pub_year(y) for y in items]


def get_year_view(yid):
    return core.pub_year(get_year(yid))


def activate_year(yid):
    year = get_year(yid)
    if year["status"] != "PLANNING":
        raise conflict("ERR_ACADEMIC_YEAR_NOT_PLANNING",
                       "Year activation requires status PLANNING")
    year["status"] = "ACTIVE"
    core.touch(year)
    return core.pub_year(year)


def close_year(yid):
    year = get_year(yid)
    if year["status"] != "ACTIVE":
        raise conflict("ERR_ACADEMIC_YEAR_NOT_ACTIVE",
                       "Year close requires status ACTIVE")
    # No SUBMITTED duty-hour log may exist for any resident of the program.
    resident_ids = {
        r["id"] for r in DB["residents"].values() if r["program_id"] == year["program_id"]
    }
    for log in DB["duty_hour_logs"].values():
        if log["resident_id"] in resident_ids and log["status"] == "SUBMITTED":
            raise conflict("ERR_UNATTESTED_LOGS_EXIST",
                           "SUBMITTED duty-hour logs exist for program residents")
    year["status"] = "CLOSED"
    core.touch(year)
    return core.pub_year(year)


def regenerate_blocks(yid, data):
    year = get_year(yid)
    # OCC runs before any business rule (pipeline stage 6).
    expected = data["expected_academic_year_version"]
    if expected != year["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_academic_year_version does not match the current version")
    if year["status"] != "PLANNING":
        raise conflict("ERR_ACADEMIC_YEAR_NOT_PLANNING",
                       "Block regeneration requires status PLANNING")
    for blk in DB["schedule_blocks"].values():
        if blk["academic_year_id"] == year["id"] and blk["status"] == "CURRENT":
            blk["status"] = "SUPERSEDED"
            core.touch(blk)
    _create_blocks(year)
    core.touch(year)
    return core.pub_year(year)


def list_blocks(args):
    items = list(DB["schedule_blocks"].values())
    if args.get("academic_year_id") is not None:
        items = [b for b in items if b["academic_year_id"] == args.get("academic_year_id")]
    if args.get("status") is not None:
        items = [b for b in items if b["status"] == args.get("status")]
    # Block list is sorted by block_index ascending (deterministic capture).
    items.sort(key=lambda b: (b["block_index"], b["_seq"]))
    return [core.pub_block(b) for b in items]


def get_block_view(bid):
    return core.pub_block(get_block(bid))


# ---------------------------------------------------------------------------
# ComplementApproval
# ---------------------------------------------------------------------------

def _compute_complement_derived(rec):
    rec["resident_year_stipend_cents"] = calc.resident_year_stipend_cents(
        rec["blended_stipend_cents"]
    )
    rec["effective_funded_positions"] = calc.effective_funded_positions(
        rec["approved_positions"],
        rec["annual_funding_budget_cents"],
        rec["resident_year_stipend_cents"],
    )


def create_complement(data):
    # Existence, left-to-right in declared input order.
    program = get_program(data["program_id"])
    year = get_year(data["academic_year_id"])
    rec = {
        "id": new_id(),
        "program_id": program["id"],
        "academic_year_id": year["id"],
        "pgy_level": data["pgy_level"],
        "approved_positions": data["approved_positions"],
        "annual_funding_budget_cents": data["annual_funding_budget_cents"],
        "blended_stipend_cents": data["blended_stipend_cents"],
        "status": "DRAFT",
    }
    _compute_complement_derived(rec)
    core.stamp(rec)
    DB["complement_approvals"][rec["id"]] = rec
    return core.pub_complement(rec)


def list_complements(args):
    items = list(DB["complement_approvals"].values())
    if args.get("program_id") is not None:
        items = [c for c in items if c["program_id"] == args.get("program_id")]
    if args.get("academic_year_id") is not None:
        items = [c for c in items if c["academic_year_id"] == args.get("academic_year_id")]
    if args.get("status") is not None:
        items = [c for c in items if c["status"] == args.get("status")]
    items.sort(key=lambda c: c["_seq"])
    return [core.pub_complement(c) for c in items]


def get_complement_view(cid):
    return core.pub_complement(get_complement(cid))


def update_complement(cid, data):
    row = get_complement(cid)
    # OCC before any business rule.
    expected = data["expected_complement_approval_version"]
    if expected != row["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_complement_approval_version does not match the current version")
    if row["status"] not in ("DRAFT", "REJECTED"):
        raise conflict("ERR_COMPLEMENT_NOT_EDITABLE",
                       "Only DRAFT or REJECTED complement rows are editable")
    if "approved_positions" in data and data["approved_positions"] is not None:
        row["approved_positions"] = data["approved_positions"]
    if "annual_funding_budget_cents" in data and data["annual_funding_budget_cents"] is not None:
        row["annual_funding_budget_cents"] = data["annual_funding_budget_cents"]
    if "blended_stipend_cents" in data and data["blended_stipend_cents"] is not None:
        row["blended_stipend_cents"] = data["blended_stipend_cents"]
    _compute_complement_derived(row)
    core.touch(row)
    return core.pub_complement(row)


def submit_complement(cid):
    row = get_complement(cid)
    if row["status"] not in ("DRAFT", "REJECTED"):
        raise conflict("ERR_COMPLEMENT_NOT_SUBMITTABLE",
                       "Submit requires status DRAFT or REJECTED")
    row["status"] = "SUBMITTED"
    core.touch(row)
    return core.pub_complement(row)


def approve_complement(cid):
    row = get_complement(cid)
    # Pipeline order: state precondition, then the program-standing gate, then
    # the uniqueness constraint (PRD section 3.2).
    if row["status"] != "SUBMITTED":
        raise conflict("ERR_COMPLEMENT_NOT_SUBMITTED",
                       "Approve requires status SUBMITTED")
    program = get_program(row["program_id"])
    if program["accreditation_status"] == "PROBATIONARY":
        raise ApiError("ERR_PROGRAM_PROBATIONARY", 403,
                       "Complement approval is barred while the program is PROBATIONARY")
    for other in DB["complement_approvals"].values():
        if (
            other["id"] != row["id"]
            and other["program_id"] == row["program_id"]
            and other["academic_year_id"] == row["academic_year_id"]
            and other["pgy_level"] == row["pgy_level"]
            and other["status"] in ("APPROVED", "LOCKED")
        ):
            raise conflict("ERR_COMPLEMENT_ALREADY_APPROVED",
                           "Another row for this (program, year, level) is APPROVED or LOCKED")
    row["status"] = "APPROVED"
    core.touch(row)
    return core.pub_complement(row)


def reject_complement(cid):
    row = get_complement(cid)
    if row["status"] != "SUBMITTED":
        raise conflict("ERR_COMPLEMENT_NOT_SUBMITTED",
                       "Reject requires status SUBMITTED")
    row["status"] = "REJECTED"
    core.touch(row)
    return core.pub_complement(row)


def lock_complement(cid):
    row = get_complement(cid)
    if row["status"] != "APPROVED":
        raise conflict("ERR_COMPLEMENT_NOT_APPROVED",
                       "Lock requires status APPROVED")
    row["status"] = "LOCKED"
    core.touch(row)
    return core.pub_complement(row)


# ---------------------------------------------------------------------------
# Resident
# ---------------------------------------------------------------------------

def create_resident(data):
    # Existence, declared input order.
    program = get_program(data["program_id"])
    year = get_year(data["entry_academic_year_id"])
    # Cross-aggregate: an APPROVED or LOCKED complement must exist for the triple.
    row = calc.approved_complement_for(program["id"], year["id"], data["pgy_level"])
    if row is None:
        raise conflict("ERR_NO_APPROVED_COMPLEMENT",
                       "No APPROVED or LOCKED complement for (program, entry year, pgy_level)")
    rec = {
        "id": new_id(),
        "program_id": program["id"],
        "entry_academic_year_id": year["id"],
        "pgy_level": data["pgy_level"],
        "full_name": data["full_name"],
        "email": data["email"],
        "hire_date": data["hire_date"],
        "expected_graduation_date": data["expected_graduation_date"],
        "lifecycle_status": "INCOMING",
        "standing_status": "GOOD_STANDING",
    }
    core.stamp(rec)
    DB["residents"][rec["id"]] = rec
    return core.pub_resident(rec)


def list_residents(args):
    items = list(DB["residents"].values())
    if args.get("program_id") is not None:
        items = [r for r in items if r["program_id"] == args.get("program_id")]
    if args.get("entry_academic_year_id") is not None:
        items = [r for r in items if r["entry_academic_year_id"] == args.get("entry_academic_year_id")]
    if args.get("lifecycle_status") is not None:
        items = [r for r in items if r["lifecycle_status"] == args.get("lifecycle_status")]
    if args.get("standing_status") is not None:
        items = [r for r in items if r["standing_status"] == args.get("standing_status")]
    items.sort(key=lambda r: r["_seq"])
    return [core.pub_resident(r) for r in items]


def get_resident_view(rid):
    return core.pub_resident(get_resident(rid))


def _set_lifecycle(resident, new_status):
    resident["lifecycle_status"] = new_status
    core.touch(resident)
    # Complement fill fields recompute on every lifecycle event (a mutation of
    # the matching complement row per PRD section 2.5).
    calc.touch_complement_for_resident(resident)


def activate_resident(rid):
    resident = get_resident(rid)
    # State precondition before the fiscal gates (pipeline: state 7, fiscal 12).
    if resident["lifecycle_status"] != "INCOMING":
        raise conflict("ERR_RESIDENT_NOT_INCOMING",
                       "Activate requires lifecycle_status INCOMING")
    row = calc.approved_complement_for(
        resident["program_id"], resident["entry_academic_year_id"], resident["pgy_level"]
    )
    if row is None:
        raise conflict("ERR_NO_APPROVED_COMPLEMENT",
                       "No APPROVED or LOCKED complement for (program, entry year, pgy_level)")
    headcount, census = calc.complement_fill(row)
    # Headcount gate (headcount variant: ON_LEAVE counts 1).
    if headcount + 1 > row["approved_positions"]:
        raise conflict("ERR_COMPLEMENT_EXCEEDED",
                       "filled_headcount + 1 exceeds approved_positions")
    # Funding gate (funded-census variant: candidate counts a full 1.0).
    cost = round0_int((census + Decimal("1.0")) * row["resident_year_stipend_cents"])
    if cost > row["annual_funding_budget_cents"]:
        raise ApiError("ERR_FUNDING_CAP_EXCEEDED", 402,
                       "Projected census cost exceeds annual_funding_budget_cents")
    _set_lifecycle(resident, "ACTIVE")
    return core.pub_resident(resident)


def place_on_leave(rid):
    resident = get_resident(rid)
    if resident["lifecycle_status"] != "ACTIVE":
        raise conflict("ERR_RESIDENT_NOT_ACTIVE",
                       "Place-on-leave requires lifecycle_status ACTIVE")
    _set_lifecycle(resident, "ON_LEAVE")
    return core.pub_resident(resident)


def return_from_leave(rid):
    resident = get_resident(rid)
    if resident["lifecycle_status"] != "ON_LEAVE":
        raise conflict("ERR_RESIDENT_NOT_ON_LEAVE",
                       "Return-from-leave requires lifecycle_status ON_LEAVE")
    # No fiscal re-check: the slot stayed reserved while ON_LEAVE.
    _set_lifecycle(resident, "ACTIVE")
    return core.pub_resident(resident)


def graduate_resident(rid):
    resident = get_resident(rid)
    if resident["lifecycle_status"] != "ACTIVE":
        raise conflict("ERR_RESIDENT_NOT_ACTIVE",
                       "Graduate requires lifecycle_status ACTIVE")
    if resident["standing_status"] != "GOOD_STANDING":
        raise conflict("ERR_STANDING_NOT_CLEAR",
                       "Graduate requires standing_status GOOD_STANDING")
    progress = calc.case_progress(resident)
    if not progress["all_met"]:
        raise conflict("ERR_CASE_REQUIREMENTS_UNMET",
                       "At least one CaseRequirement is unmet for this resident")
    finalized = any(
        c["resident_id"] == resident["id"] and c["status"] == "FINALIZED"
        for c in DB["ccc_reviews"].values()
    )
    if not finalized:
        raise conflict("ERR_NO_FINALIZED_CCC_REVIEW",
                       "No FINALIZED CCC review exists for the resident")
    _set_lifecycle(resident, "GRADUATED")
    return core.pub_resident(resident)


def transfer_resident(rid):
    resident = get_resident(rid)
    if resident["lifecycle_status"] not in ("ACTIVE", "ON_LEAVE"):
        raise conflict("ERR_RESIDENT_NOT_ACTIVE",
                       "Transfer requires lifecycle_status ACTIVE or ON_LEAVE")
    _set_lifecycle(resident, "TRANSFERRED")
    return core.pub_resident(resident)


def duty_hour_summary_view(rid, week_start_raw):
    resident = get_resident(rid)
    return calc.duty_hour_summary(resident, week_start_raw)


def case_progress_view(rid):
    resident = get_resident(rid)
    return calc.case_progress(resident)


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

def create_rotation(data):
    program = get_program(data["program_id"])
    rec = {
        "id": new_id(),
        "program_id": program["id"],
        "name": data["name"],
        "min_pgy_level": data["min_pgy_level"],
        "max_residents_per_block": data["max_residents_per_block"],
        "is_night_float": data.get("is_night_float", False),
        "status": "ACTIVE",
    }
    core.stamp(rec)
    DB["rotations"][rec["id"]] = rec
    return core.pub_rotation(rec)


def list_rotations(args):
    items = list(DB["rotations"].values())
    if args.get("program_id") is not None:
        items = [r for r in items if r["program_id"] == args.get("program_id")]
    if args.get("status") is not None:
        items = [r for r in items if r["status"] == args.get("status")]
    items.sort(key=lambda r: r["_seq"])
    return [core.pub_rotation(r) for r in items]


def get_rotation_view(rid):
    return core.pub_rotation(get_rotation(rid))


def update_rotation(rid, data):
    rot = get_rotation(rid)
    expected = data["expected_rotation_version"]
    if expected != rot["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_rotation_version does not match the current version")
    if rot["status"] != "ACTIVE":
        raise conflict("ERR_ROTATION_NOT_ACTIVE",
                       "Only ACTIVE rotations are editable")
    if "name" in data and data["name"] is not None:
        rot["name"] = data["name"]
    if "min_pgy_level" in data and data["min_pgy_level"] is not None:
        rot["min_pgy_level"] = data["min_pgy_level"]
    if "max_residents_per_block" in data and data["max_residents_per_block"] is not None:
        rot["max_residents_per_block"] = data["max_residents_per_block"]
    if "is_night_float" in data and data["is_night_float"] is not None:
        rot["is_night_float"] = data["is_night_float"]
    core.touch(rot)
    return core.pub_rotation(rot)


def retire_rotation(rid):
    rot = get_rotation(rid)
    if rot["status"] != "ACTIVE":
        raise conflict("ERR_ROTATION_NOT_ACTIVE", "Retire requires status ACTIVE")
    for a in DB["rotation_assignments"].values():
        if a["rotation_id"] == rot["id"] and a["status"] in ("PLANNED", "CONFIRMED"):
            raise conflict("ERR_ROTATION_HAS_OPEN_ASSIGNMENTS",
                           "PLANNED or CONFIRMED assignments reference this rotation")
    rot["status"] = "RETIRED"
    core.touch(rot)
    return core.pub_rotation(rot)


# ---------------------------------------------------------------------------
# RotationAssignment
# ---------------------------------------------------------------------------

def create_assignment(data):
    # Existence, declared input order.
    resident = get_resident(data["resident_id"])
    block = get_block(data["schedule_block_id"])
    rotation = get_rotation(data["rotation_id"])
    # State preconditions (PRD section 3.4 order: year, rotation, resident).
    year = get_year(block["academic_year_id"])
    if block["status"] != "CURRENT" or year["status"] != "ACTIVE":
        raise conflict("ERR_ACADEMIC_YEAR_NOT_ACTIVE",
                       "The block's academic year must be ACTIVE")
    if rotation["status"] != "ACTIVE":
        raise conflict("ERR_ROTATION_NOT_ACTIVE",
                       "The rotation must be ACTIVE")
    if resident["lifecycle_status"] != "ACTIVE":
        raise conflict("ERR_RESIDENT_NOT_ACTIVE",
                       "The resident's lifecycle_status must be ACTIVE")
    # Safety gate: night-float rotations are barred to residents ON_PROBATION.
    if rotation["is_night_float"] and resident["standing_status"] == "ON_PROBATION":
        raise ApiError("ERR_PROBATION_NIGHT_FLOAT_BLOCKED", 403,
                       "ON_PROBATION resident cannot be assigned to a night-float rotation")
    # Constraints: PGY eligibility, one non-CANCELLED assignment per
    # (resident, block), rotation capacity per block.
    if resident["pgy_level"] < rotation["min_pgy_level"]:
        raise ApiError("ERR_PGY_INELIGIBLE", 422,
                       "resident.pgy_level is below rotation.min_pgy_level")
    for a in DB["rotation_assignments"].values():
        if (
            a["resident_id"] == resident["id"]
            and a["schedule_block_id"] == block["id"]
            and a["status"] != "CANCELLED"
        ):
            raise conflict("ERR_BLOCK_ASSIGNMENT_CONFLICT",
                           "Resident already has a non-CANCELLED assignment in this block")
    occupancy = sum(
        1
        for a in DB["rotation_assignments"].values()
        if a["rotation_id"] == rotation["id"]
        and a["schedule_block_id"] == block["id"]
        and a["status"] != "CANCELLED"
    )
    if occupancy >= rotation["max_residents_per_block"]:
        raise conflict("ERR_ROTATION_CAPACITY_FULL",
                       "Rotation capacity for this block has been reached")
    # Cross-aggregate consistency (last).
    if resident["program_id"] != year["program_id"] or rotation["program_id"] != year["program_id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE", 400,
                       "Resident, schedule block's year, and rotation must belong to the same program")
    rec = {
        "id": new_id(),
        "resident_id": resident["id"],
        "schedule_block_id": block["id"],
        "rotation_id": rotation["id"],
        "status": "PLANNED",
    }
    core.stamp(rec)
    DB["rotation_assignments"][rec["id"]] = rec
    return core.pub_assignment(rec)


def list_assignments(args):
    items = list(DB["rotation_assignments"].values())
    if args.get("resident_id") is not None:
        items = [a for a in items if a["resident_id"] == args.get("resident_id")]
    if args.get("schedule_block_id") is not None:
        items = [a for a in items if a["schedule_block_id"] == args.get("schedule_block_id")]
    if args.get("rotation_id") is not None:
        items = [a for a in items if a["rotation_id"] == args.get("rotation_id")]
    if args.get("status") is not None:
        items = [a for a in items if a["status"] == args.get("status")]
    items.sort(key=lambda a: a["_seq"])
    return [core.pub_assignment(a) for a in items]


def get_assignment_view(aid):
    return core.pub_assignment(get_assignment(aid))


def confirm_assignment(aid):
    a = get_assignment(aid)
    if a["status"] != "PLANNED":
        raise conflict("ERR_ASSIGNMENT_NOT_PLANNED", "Confirm requires status PLANNED")
    a["status"] = "CONFIRMED"
    core.touch(a)
    return core.pub_assignment(a)


def complete_assignment(aid):
    a = get_assignment(aid)
    if a["status"] != "CONFIRMED":
        raise conflict("ERR_ASSIGNMENT_NOT_CONFIRMED", "Complete requires status CONFIRMED")
    a["status"] = "COMPLETED"
    core.touch(a)
    return core.pub_assignment(a)


def cancel_assignment(aid):
    a = get_assignment(aid)
    if a["status"] not in ("PLANNED", "CONFIRMED"):
        raise conflict("ERR_ASSIGNMENT_NOT_CANCELLABLE",
                       "Cancel requires status PLANNED or CONFIRMED")
    a["status"] = "CANCELLED"
    core.touch(a)
    return core.pub_assignment(a)
