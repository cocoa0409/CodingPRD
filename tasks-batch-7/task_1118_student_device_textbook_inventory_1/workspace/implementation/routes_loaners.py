"""LoanerCheckout endpoints (PRD 3.8)."""
import math
from datetime import timedelta

from flask import Blueprint, request

from core import (GRADE_RANK, STORE, auth, base_record, body, create_fee,
                  fail, family_path_scope, get_loaner, get_program,
                  get_student, late_fee_cents, list_response, loaner_json,
                  months_in_service, now, ok_object, opt_int, opt_str,
                  reject_stray_occ, req_enum, set_lifecycle, touch, whole_days)

bp = Blueprint("loaners", __name__)

LOANER_READ = ["DistrictAdmin", "SiteTechnician", "Family"]
REASONS = ["REPAIR", "LOSS_PENDING", "NEW_ENROLLMENT"]


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _program_units(prog_id):
    out = []
    for u in STORE["units"].values():
        fleet = STORE["fleets"].get(u["fleet_id"])
        if fleet is not None and fleet["program_id"] == prog_id:
            out.append(u)
    return out


def _target_class(stu):
    """Class of the student's in-repair unit, else of their open assignment."""
    for u in STORE["units"].values():
        if u.get("_repair_student_id") == stu["id"] and u["lifecycle_status"] == "IN_REPAIR":
            return STORE["fleets"][u["fleet_id"]]["asset_class"]
    for a in STORE["assignments"].values():
        if a["student_account_id"] == stu["id"] and a["status"] in ("ACTIVE", "OVERDUE"):
            u = STORE["units"].get(a["asset_unit_id"])
            if u is not None:
                return STORE["fleets"][u["fleet_id"]]["asset_class"]
    return None


@bp.post("/api/programs/<progId>/students/<studentId>/loaner-checkouts")
def create_loaner(progId, studentId):
    b = body()
    reason = req_enum(b, "checkout_reason", REASONS)
    unit_id = opt_str(b, "loaner_asset_unit_id")
    max_days = opt_int(b, "max_loaner_days", 14, minimum=1)
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    # Priority 7: suspension gate (applies as it does to assignments, PRD 3.8).
    if stu["financial_posture"] == "SUSPENDED":
        fail("ERR_STUDENT_SUSPENDED", 409, "SUSPENDED students cannot take new obligations")
    # Priority 8: referential — named unit must genuinely sit in the pool.
    if unit_id is not None:
        unit = STORE["units"].get(unit_id)
        if unit is not None:
            fleet = STORE["fleets"].get(unit["fleet_id"])
            if fleet is None or fleet["program_id"] != prog["id"]:
                unit = None
        if unit is None:
            fail("ERR_ASSET_NOT_FOUND", 404, "Asset unit %s does not exist" % unit_id)
        if unit["lifecycle_status"] != "LOANER":
            fail("ERR_ASSET_NOT_READY", 409, "Named unit must be in LOANER status")
    else:
        target = _target_class(stu)
        cands = []
        for u in _program_units(prog["id"]):
            if u["lifecycle_status"] != "LOANER" or u["condition_grade"] not in ("A", "B", "C"):
                continue
            if target is not None and STORE["fleets"][u["fleet_id"]]["asset_class"] != target:
                continue
            cands.append(u)
        if not cands:
            fail("ERR_LOANER_POOL_EXHAUSTED", 409, "No eligible units in the loaner pool")
        cands.sort(key=lambda u: (GRADE_RANK[u["condition_grade"]],
                                  months_in_service(u), u["_seq"]))
        unit = cands[0]
    # Priority 9: loaner floor — remaining pool must cover the configured
    # fraction of the deployable fleet, rounded down (PRD 3.8).
    pool = [u for u in _program_units(prog["id"]) if u["lifecycle_status"] == "LOANER"]
    deployable = [u for u in _program_units(prog["id"])
                  if u["lifecycle_status"] in ("READY", "LOANER")]
    floor_needed = math.floor(prog["loaner_pool_threshold_pct"] * len(deployable))
    if len(pool) - 1 < floor_needed:
        fail("ERR_LOANER_FLOOR_BREACH", 409,
             "Allocation would drop the pool below the configured floor")
    rec = base_record()
    rec.update({
        "student_account_id": stu["id"],
        "loaner_asset_unit_id": unit["id"],
        "checkout_reason": reason,
        "max_loaner_days": max_days,
        "returned_at": None,
        "status": "OPEN",
    })
    STORE["loaners"][rec["id"]] = rec
    unit["assigned_to_student_id"] = stu["id"]
    set_lifecycle(unit, "DEPLOYED", "DEPLOY", {"loaner": True})
    return ok_object(loaner_json(rec), 201)


@bp.get("/api/programs/<progId>/students/<studentId>/loaner-checkouts")
def list_loaners(progId, studentId):
    uid, role = auth(LOANER_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    st = _q("status")
    recs = [c for c in STORE["loaners"].values()
            if c["student_account_id"] == stu["id"]
            and (st is None or c["status"] == st)]
    return list_response(recs, loaner_json)


@bp.get("/api/programs/<progId>/students/<studentId>/loaner-checkouts/<checkoutId>")
def get_loaner_route(progId, studentId, checkoutId):
    uid, role = auth(LOANER_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    return ok_object(loaner_json(get_loaner(checkoutId, stu)))


@bp.post("/api/programs/<progId>/students/<studentId>/loaner-checkouts/<checkoutId>/return")
def return_loaner(progId, studentId, checkoutId):
    b = body()
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    chk = get_loaner(checkoutId, stu)
    if chk["status"] not in ("OPEN", "OVERDUE"):
        fail("ERR_INVALID_STATE", 409, "Checkout must be OPEN or OVERDUE to return")
    chk["returned_at"] = now()
    chk["status"] = "RETURNED"
    touch(chk)
    elapsed = whole_days(chk["created_at"], now())
    over = elapsed - chk["max_loaner_days"]
    if over > 0:
        fee = late_fee_cents(over, stu["free_lunch_eligible"])
        if fee > 0:
            create_fee(stu, "LATE_RETURN", fee)
    unit = STORE["units"].get(chk["loaner_asset_unit_id"])
    if unit is not None:
        set_lifecycle(unit, "LOANER", relocated=True)
    return ok_object(loaner_json(chk))


@bp.post("/api/programs/<progId>/students/<studentId>/loaner-checkouts/<checkoutId>/escalate")
def escalate_loaner(progId, studentId, checkoutId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    chk = get_loaner(checkoutId, stu)
    if chk["status"] != "OVERDUE":
        fail("ERR_INVALID_STATE", 409, "Checkout must be OVERDUE to escalate")
    overdue_since = chk["created_at"] + timedelta(days=chk["max_loaner_days"])
    if whole_days(overdue_since, now()) < 7:
        fail("ERR_NOT_OVERDUE_LONG_ENOUGH", 409,
             "Escalation requires the checkout to be OVERDUE for at least 7 days")
    chk["status"] = "ESCALATED"
    touch(chk)
    unit = STORE["units"].get(chk["loaner_asset_unit_id"])
    if unit is not None:
        fleet = STORE["fleets"][unit["fleet_id"]]
        create_fee(stu, "NON_RETURN", fleet["unit_replacement_cost_cents"])
        set_lifecycle(unit, "END_OF_LIFE", "RETIRE")
    return ok_object(loaner_json(chk))
