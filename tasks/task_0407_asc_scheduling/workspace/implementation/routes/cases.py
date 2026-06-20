"""SurgicalCase action routes: reschedule, assignment, clearance lifecycle,
intra-op progression, completion settlement, cancel (PRD §3.5-§3.13)."""
from flask import Blueprint

from db import db, stamp_common, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_response, now_iso
from services.helpers import (
    lookup, get_body, require_str, require_int, require_positive_int,
    require_enum, paginate, sorted_by_created, ser_default, ser_clearance_check,
)
from services.calculations import (
    estimated_case_cost, actual_case_cost, asc_payment_grouping, recompute_day,
)
from services.case_ops import cancel_case_effects, recompute_estimate_if_scheduled
from services.timeutil import hp_is_fresh
from routes.blocks import _check_or_conflict, _check_anesthesia_conflict

bp = Blueprint("cases", __name__)

ALL_ROLES = {"Scheduler", "PreOpNurse", "ORManager", "BillingAnalyst"}
CHECK_TYPES = {"HP_REVIEW", "LABS", "ANESTHESIA_ASSESSMENT", "CARDIAC_CONSULT"}
OUTCOMES = {"PASS", "FAIL", "DEFER"}


def _case_implants(case_id):
    return [ci for ci in db.case_implants.values() if ci["surgical_case_id"] == case_id]


# ------------------------------------------------------------------- list/get
@bp.route("/asc/surgical-cases", methods=["GET"])
def list_cases():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.surgical_cases.values())
    for field in ("surgical_day_id", "surgeon_block_id", "patient_id", "procedure_id",
                  "operating_room_id", "anesthesiologist_id", "recovery_bay_id",
                  "facility_id", "case_status"):
        v = _arg(field)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/surgical-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("surgical_cases", case_id)))


# ------------------------------------------------------------------ reschedule
@bp.route("/asc/surgical-cases/<case_id>/reschedule", methods=["PATCH"])
def reschedule(case_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    case = lookup("surgical_cases", case_id)
    body = get_body()
    new_start = require_int(body, "start_min")
    # State guard: only SCHEDULED cases may be rescheduled.
    if case["case_status"] != "SCHEDULED":
        raise err("ERR_CASE_NOT_SCHEDULED", "Only SCHEDULED cases may be rescheduled.")
    new_end = new_start + case["scheduled_minutes"]
    block = db.surgeon_blocks[case["surgeon_block_id"]]
    day = db.surgical_days[case["surgical_day_id"]]
    # Non-add-on must remain within the block window (PRD §3.4 booking contract).
    if not case["is_add_on"]:
        if not (new_start >= block["start_min"] and new_end <= block["end_min"]):
            raise err("ERR_CASE_OUTSIDE_BLOCK_WINDOW",
                      "Rescheduled footprint must lie within the block window.")
    _check_or_conflict(day, case["operating_room_id"], new_start, new_end, exclude_case_id=case_id)
    if case.get("anesthesiologist_id") is not None:
        _check_anesthesia_conflict(day, case["anesthesiologist_id"], new_start, new_end,
                                   exclude_case_id=case_id)
    case["start_min"] = new_start
    case["end_min"] = new_end
    touch(case)
    recompute_day(day)
    touch(day)
    return success(ser_default(case))


# ------------------------------------------------------------ assign-anesthesia
@bp.route("/asc/surgical-cases/<case_id>/assign-anesthesia", methods=["POST"])
def assign_anesthesia(case_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    case = lookup("surgical_cases", case_id)
    body = get_body()
    anesth_id = require_str(body, "anesthesiologist_id")
    anesth = lookup("anesthesiologists", anesth_id)
    if anesth["facility_id"] != case["facility_id"]:
        raise err("ERR_ANESTHESIOLOGIST_NOT_FOUND", "Anesthesiologist not in facility.")
    if not anesth["active"]:
        raise err("ERR_ANESTHESIOLOGIST_INACTIVE", "Anesthesiologist is inactive.")
    procedure = db.procedures[case["procedure_id"]]
    if anesth["credential"] == "CRNA" and procedure["anesthesia_class"] == "GENERAL":
        raise err("ERR_CRNA_CANNOT_COVER_GENERAL",
                  "CRNA may not solo-cover a GENERAL anesthesia case.")
    day = db.surgical_days[case["surgical_day_id"]]
    _check_anesthesia_conflict(day, anesth_id, case["start_min"], case["end_min"],
                               exclude_case_id=case_id)
    case["anesthesiologist_id"] = anesth_id
    touch(case)
    return success(ser_default(case))


# -------------------------------------------------------------- assign-recovery
@bp.route("/asc/surgical-cases/<case_id>/assign-recovery", methods=["POST"])
def assign_recovery(case_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    case = lookup("surgical_cases", case_id)
    body = get_body()
    bay_id = require_str(body, "recovery_bay_id")
    bay = lookup("recovery_bays", bay_id)
    if bay["facility_id"] != case["facility_id"]:
        raise err("ERR_RECOVERY_BAY_NOT_FOUND", "Recovery bay not in facility.")
    procedure = db.procedures[case["procedure_id"]]
    if procedure["requires_phase2"] and not bay["phase2_capable"]:
        raise err("ERR_RECOVERY_PHASE2_REQUIRED",
                  "Procedure requires a Phase II-capable recovery bay.")
    case["recovery_bay_id"] = bay_id
    touch(case)
    return success(ser_default(case))


# ------------------------------------------------------------- clearance-checks
@bp.route("/asc/surgical-cases/<case_id>/clearance-checks", methods=["POST"])
def record_clearance_check(case_id):
    user_id, role = get_user_context()
    require_role(role, {"PreOpNurse"})
    case = lookup("surgical_cases", case_id)
    body = get_body()
    check_type = require_enum(body, "check_type", CHECK_TYPES)
    outcome = require_enum(body, "outcome", OUTCOMES)
    # State guard: clearance must be PENDING_CLEARANCE to record a check.
    if case["clearance_status"] != "PENDING_CLEARANCE":
        raise err("ERR_CLEARANCE_NOT_PENDING",
                  "Clearance must be PENDING_CLEARANCE to record a check.")
    # Append-only event: only id + created_at (no updated_at/version).
    rec = {
        "id": db.new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "surgical_case_id": case_id,
        "check_type": check_type,
        "outcome": outcome,
        "recorded_by": user_id,
    }
    db.clearance_checks[rec["id"]] = rec
    if outcome == "FAIL":
        case["clearance_status"] = "ON_HOLD"
        touch(case)
    return success(ser_clearance_check(rec), status=201)


@bp.route("/asc/clearance-checks", methods=["GET"])
def list_clearance_checks():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.clearance_checks.values())
    v = _arg("surgical_case_id")
    if v is not None:
        items = [r for r in items if r["surgical_case_id"] == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_clearance_check(r) for r in page], limit, offset, total)


@bp.route("/asc/clearance-checks/<check_id>", methods=["GET"])
def get_clearance_check(check_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_clearance_check(lookup("clearance_checks", check_id)))


# --------------------------------------------------------------- clearance-reset
@bp.route("/asc/surgical-cases/<case_id>/clearance-reset", methods=["POST"])
def clearance_reset(case_id):
    _, role = get_user_context()
    require_role(role, {"PreOpNurse"})
    case = lookup("surgical_cases", case_id)
    if case["clearance_status"] != "ON_HOLD":
        raise err("ERR_CLEARANCE_NOT_ON_HOLD", "Clearance must be ON_HOLD to reset.")
    case["clearance_status"] = "PENDING_CLEARANCE"
    # Mark the reset boundary for DEFER supersession logic.
    case["_last_clearance_reset_seq"] = db.next_seq()
    touch(case)
    return success(ser_default(case))


# ----------------------------------------------------------------------- clear
@bp.route("/asc/surgical-cases/<case_id>/clear", methods=["POST"])
def clear_case(case_id):
    _, role = get_user_context()
    require_role(role, {"PreOpNurse"})
    case = lookup("surgical_cases", case_id)
    body = get_body()

    # Guard 1: clearance must be PENDING_CLEARANCE.
    if case["clearance_status"] != "PENDING_CLEARANCE":
        raise err("ERR_CLEARANCE_NOT_PENDING", "Clearance must be PENDING_CLEARANCE to clear.")

    # Record hp_signed_at if provided.
    hp_signed_at = body.get("hp_signed_at")
    if hp_signed_at is not None:
        if not isinstance(hp_signed_at, str):
            raise err("ERR_INVALID_REQUEST", "hp_signed_at must be a string instant.")
        case["hp_signed_at"] = hp_signed_at

    # Guard 2: H&P must be on file and fresh.
    facility = db.facilities[case["facility_id"]]
    day = db.surgical_days[case["surgical_day_id"]]
    stored_hp = case.get("hp_signed_at")
    if not stored_hp:
        raise err("ERR_HP_WINDOW_EXPIRED", "H&P missing.")
    try:
        fresh = hp_is_fresh(stored_hp, day["service_date"], facility["hp_validity_days"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "hp_signed_at is not a valid instant.")
    if not fresh:
        raise err("ERR_HP_WINDOW_EXPIRED", "H&P is stale.")

    # Guard 3: at least one HP_REVIEW PASS check exists.
    checks = [c for c in db.clearance_checks.values() if c["surgical_case_id"] == case_id]
    if not any(c["check_type"] == "HP_REVIEW" and c["outcome"] == "PASS" for c in checks):
        raise err("ERR_HP_REVIEW_MISSING", "A passing HP_REVIEW clearance check is required.")

    # Guard 4: no un-superseded DEFER after the most recent reset.
    reset_seq = case.get("_last_clearance_reset_seq", 0)
    # DEFER checks recorded after the reset boundary.
    relevant = [c for c in checks if c["_seq"] > reset_seq]
    relevant.sort(key=lambda c: c["_seq"])
    # For each DEFER, it is superseded iff a later PASS of the same check_type exists.
    for c in relevant:
        if c["outcome"] != "DEFER":
            continue
        superseded = any(
            later["_seq"] > c["_seq"]
            and later["check_type"] == c["check_type"]
            and later["outcome"] == "PASS"
            for later in relevant
        )
        if not superseded:
            raise err("ERR_OPEN_FAILED_CHECK", "An un-superseded DEFER check blocks clearing.")

    case["clearance_status"] = "CLEARED"
    touch(case)
    return success(ser_default(case))


# ----------------------------------------------------------------------- start
@bp.route("/asc/surgical-cases/<case_id>/start", methods=["POST"])
def start_case(case_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    case = lookup("surgical_cases", case_id)
    if case["case_status"] != "SCHEDULED":
        raise err("ERR_CASE_NOT_SCHEDULED", "Case must be SCHEDULED to start.")
    if case["clearance_status"] != "CLEARED":
        raise err("ERR_CASE_NOT_CLEARED", "Case clearance must be CLEARED to start.")
    room = db.operating_rooms[case["operating_room_id"]]
    if room["status"] != "AVAILABLE":
        raise err("ERR_OR_OFFLINE", "Assigned operating room is OFFLINE.")
    anesth_id = case.get("anesthesiologist_id")
    if anesth_id is None or not db.anesthesiologists[anesth_id]["active"]:
        raise err("ERR_ANESTHESIA_NOT_ASSIGNED",
                  "An active anesthesiologist must be assigned to start.")
    day = db.surgical_days[case["surgical_day_id"]]
    if day["posture"] != "LOCKED":
        raise err("ERR_DAY_NOT_LOCKED", "Day must be LOCKED before a case enters the OR.")
    case["case_status"] = "IN_OR"
    touch(case)
    return success(ser_default(case))


# ------------------------------------------------------------------ to-recovery
@bp.route("/asc/surgical-cases/<case_id>/to-recovery", methods=["POST"])
def to_recovery(case_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    case = lookup("surgical_cases", case_id)
    if case["case_status"] != "IN_OR":
        raise err("ERR_CASE_NOT_IN_OR", "Case must be IN_OR to move to recovery.")
    bay_id = case.get("recovery_bay_id")
    if bay_id is None or db.recovery_bays[bay_id]["status"] != "AVAILABLE":
        raise err("ERR_RECOVERY_NOT_ASSIGNED",
                  "An AVAILABLE recovery bay must be assigned to move to recovery.")
    case["case_status"] = "IN_RECOVERY"
    touch(case)
    return success(ser_default(case))


# --------------------------------------------------------------------- complete
@bp.route("/asc/surgical-cases/<case_id>/complete", methods=["POST"])
def complete_case(case_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    case = lookup("surgical_cases", case_id)
    body = get_body()
    if case["case_status"] != "IN_RECOVERY":
        raise err("ERR_CASE_NOT_IN_RECOVERY", "Case must be IN_RECOVERY to complete.")
    # actual_minutes provided and positive.
    am = body.get("actual_minutes")
    if am is None or isinstance(am, bool) or not isinstance(am, int) or am <= 0:
        raise err("ERR_ACTUAL_MINUTES_REQUIRED", "actual_minutes must be supplied and positive.")
    # Every CaseImplant must have consumed_qty recorded.
    implants = _case_implants(case_id)
    for ci in implants:
        if ci["status"] == "RESERVED" and ci.get("consumed_qty") is None:
            raise err("ERR_IMPLANT_NOT_SETTLED",
                      "Every implant must have consumed_qty recorded before completion.")

    case["actual_minutes"] = am
    case["case_status"] = "COMPLETED"

    # Cascade: RESERVED implants -> CONSUMED (decrement reserved_qty by planned_qty,
    # on_hand_qty by consumed_qty).
    for ci in implants:
        if ci["status"] != "RESERVED":
            continue
        consumed = ci.get("consumed_qty")
        # consumed_qty already validated to be in [0, planned_qty] when recorded.
        ci["status"] = "CONSUMED"
        supply = db.supply_items[ci["supply_item_id"]]
        supply["reserved_qty"] -= ci["planned_qty"]
        supply["on_hand_qty"] -= consumed
        touch(supply)
        touch(ci)

    procedure = db.procedures[case["procedure_id"]]
    case["actual_cost_cents"] = actual_case_cost(case, procedure)
    case["cms_payment_cents"] = asc_payment_grouping(case, procedure)
    touch(case)

    day = db.surgical_days[case["surgical_day_id"]]
    recompute_day(day)
    touch(day)
    return success(ser_default(case))


# ----------------------------------------------------------------------- cancel
@bp.route("/asc/surgical-cases/<case_id>/cancel", methods=["POST"])
def cancel_case(case_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    case = lookup("surgical_cases", case_id)
    if case["case_status"] != "SCHEDULED":
        raise err("ERR_CASE_NOT_CANCELLABLE", "Only SCHEDULED cases may be cancelled.")
    cancel_case_effects(case)
    return success(ser_default(case))


# ------------------------------------------------------------------ implants
@bp.route("/asc/surgical-cases/<case_id>/implants", methods=["POST"])
def attach_implant(case_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    case = lookup("surgical_cases", case_id)
    body = get_body()
    supply_item_id = require_str(body, "supply_item_id")
    supply = lookup("supply_items", supply_item_id)
    if supply["facility_id"] != case["facility_id"]:
        raise err("ERR_SUPPLY_ITEM_NOT_FOUND", "Supply item not in facility.")
    planned_qty = require_positive_int(body, "planned_qty")
    available = supply["on_hand_qty"] - supply["reserved_qty"]
    if available < planned_qty:
        raise err("ERR_SUPPLY_INSUFFICIENT", "Insufficient available supply.")

    rec = stamp_common({
        "surgical_case_id": case_id,
        "supply_item_id": supply_item_id,
        "planned_qty": planned_qty,
        "consumed_qty": None,
        "status": "RESERVED",
    })
    db.case_implants[rec["id"]] = rec
    supply["reserved_qty"] += planned_qty
    touch(supply)
    recompute_estimate_if_scheduled(case)
    touch(case)
    return success(ser_default(rec), status=201)


@bp.route("/asc/case-implants/<implant_id>", methods=["PATCH"])
def record_consumed(implant_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    implant = lookup("case_implants", implant_id)
    body = get_body()
    cq = body.get("consumed_qty")
    if cq is None or isinstance(cq, bool) or not isinstance(cq, int):
        raise err("ERR_INVALID_REQUEST", "consumed_qty must be an integer.")
    if cq < 0 or cq > implant["planned_qty"]:
        raise err("ERR_CONSUMED_QTY_INVALID", "consumed_qty out of [0, planned_qty].")
    implant["consumed_qty"] = cq
    touch(implant)
    return success(ser_default(implant))


@bp.route("/asc/surgical-cases/<case_id>/implants/<implant_id>/release", methods=["POST"])
def release_implant(case_id, implant_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    case = lookup("surgical_cases", case_id)
    implant = lookup("case_implants", implant_id)
    if implant["surgical_case_id"] != case_id:
        raise err("ERR_CASE_IMPLANT_NOT_FOUND", "Implant does not belong to this case.")
    if implant["status"] != "RESERVED":
        raise err("ERR_IMPLANT_NOT_RESERVED", "Implant must be RESERVED to release.")
    implant["status"] = "RELEASED"
    supply = db.supply_items[implant["supply_item_id"]]
    supply["reserved_qty"] -= implant["planned_qty"]
    touch(supply)
    touch(implant)
    recompute_estimate_if_scheduled(case)
    touch(case)
    return success(ser_default(implant))


@bp.route("/asc/case-implants", methods=["GET"])
def list_implants():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.case_implants.values())
    for field in ("surgical_case_id", "supply_item_id"):
        v = _arg(field)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/case-implants/<implant_id>", methods=["GET"])
def get_implant(implant_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("case_implants", implant_id)))


def _arg(name):
    from flask import request
    return request.args.get(name)
