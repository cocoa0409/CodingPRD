"""Assignment and DamageReport endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from core import (GRADE_RANK, STORE, append_event, assignment_json, auth,
                  base_record, body, check_occ, create_fee, depreciated_value,
                  fail, family_path_scope, get_assignment, get_program,
                  get_report, get_student, get_unit, late_fee_cents,
                  list_response, now, ok_object, provisional_fee,
                  reject_stray_occ, report_json, req_dt, req_enum, req_str,
                  recompute_posture, rhu, set_lifecycle, touch, whole_days)

bp = Blueprint("assignments", __name__)

ASSIGN_READ = ["DistrictAdmin", "Registrar", "SiteTechnician", "Family"]
DAMAGE_CATEGORIES = ["COSMETIC", "FUNCTIONAL", "LIQUID", "SCREEN", "LOSS", "THEFT"]
GRADES = ["A", "B", "C", "D", "F"]


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ---------------------------------------------------------- assignments ----
@bp.post("/api/programs/<progId>/students/<studentId>/assignments")
def create_assignment(progId, studentId):
    b = body()
    asset_unit_id = req_str(b, "asset_unit_id")
    expected_return = req_dt(b, "expected_return_date")
    reject_stray_occ(b, "expected_student_version")
    auth(["Registrar"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    # Priority 3: program posture.
    if prog["status"] != "ACTIVE":
        fail("ERR_PROGRAM_STATE_FORBIDS", 409, "Assignment creation requires an ACTIVE program")
    # Priority 4: optimistic concurrency on the student.
    check_occ(b, "expected_student_version", stu["version"])
    # Priority 6: family agreement gate.
    if stu["family_agreement_status"] != "SIGNED":
        fail("ERR_AGREEMENT_NOT_SIGNED", 409, "Family agreement must be SIGNED")
    # Priority 7: suspension gate.
    if stu["financial_posture"] == "SUSPENDED":
        fail("ERR_STUDENT_SUSPENDED", 409, "SUSPENDED students cannot take new obligations")
    # Priority 8: the unit must be deployable.
    unit = STORE["units"].get(asset_unit_id)
    if unit is None:
        fail("ERR_ASSET_NOT_FOUND", 404, "Asset unit %s does not exist" % asset_unit_id)
    fleet = STORE["fleets"].get(unit["fleet_id"])
    if fleet is None or fleet["program_id"] != prog["id"]:
        fail("ERR_ASSET_NOT_FOUND", 404, "Asset unit %s does not exist" % asset_unit_id)
    if unit["lifecycle_status"] != "READY" or unit["condition_grade"] == "F":
        fail("ERR_ASSET_NOT_READY", 409,
             "Unit must be READY with condition_grade other than F")
    rec = base_record()
    rec.update({
        "student_account_id": stu["id"],
        "asset_unit_id": unit["id"],
        "expected_return_date": expected_return,
        "checked_out_at": now(),
        "checked_in_at": None,
        "checkout_condition_grade": unit["condition_grade"],
        "return_condition_grade": None,
        "late_return_days": None,
        "status": "ACTIVE",
    })
    STORE["assignments"][rec["id"]] = rec
    unit["assigned_to_student_id"] = stu["id"]
    set_lifecycle(unit, "DEPLOYED", "DEPLOY")
    touch(stu)  # assignment creation increments StudentAccount.version by 1
    return ok_object(assignment_json(rec), 201)


@bp.get("/api/programs/<progId>/students/<studentId>/assignments")
def list_assignments(progId, studentId):
    uid, role = auth(ASSIGN_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    st = _q("status")
    recs = [a for a in STORE["assignments"].values()
            if a["student_account_id"] == stu["id"]
            and (st is None or a["status"] == st)]
    return list_response(recs, assignment_json)


@bp.get("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>")
def get_assignment_route(progId, studentId, assignmentId):
    uid, role = auth(ASSIGN_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    return ok_object(assignment_json(get_assignment(assignmentId, stu)))


@bp.post("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>/return")
def return_assignment(progId, studentId, assignmentId):
    b = body()
    return_grade = req_enum(b, "return_condition_grade", GRADES)
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    asg = get_assignment(assignmentId, stu)
    if asg["status"] not in ("ACTIVE", "OVERDUE"):
        fail("ERR_INVALID_STATE", 409, "Assignment must be ACTIVE or OVERDUE to return")
    asg["checked_in_at"] = now()
    asg["return_condition_grade"] = return_grade
    asg["late_return_days"] = max(0, whole_days(asg["expected_return_date"], now()))
    asg["status"] = "RETURNED"
    touch(asg)
    if asg["late_return_days"] > 0:
        fee = late_fee_cents(asg["late_return_days"], stu["free_lunch_eligible"])
        if fee > 0:
            create_fee(stu, "LATE_RETURN", fee)
    unit = STORE["units"].get(asg["asset_unit_id"])
    if unit is not None:
        if GRADE_RANK[return_grade] > GRADE_RANK[asg["checkout_condition_grade"]]:
            # Worse than checkout: system files a damage report (PRD 3.5).
            category = "FUNCTIONAL" if return_grade in ("D", "F") else "COSMETIC"
            rep = base_record()
            rep.update({
                "assignment_id": asg["id"],
                "reported_by_role": "SYSTEM",
                "damage_category": category,
                "observed_condition_grade": return_grade,
                "provisional_fee_cents": provisional_fee(unit, category),
                "final_fee_cents": None,
                "status": "DRAFT",
                "_sent_to_repair": True,
            })
            STORE["reports"][rep["id"]] = rep
            unit["_repair_student_id"] = stu["id"]
            set_lifecycle(unit, "IN_REPAIR", "REPAIR_START",
                          {"damage_report_id": rep["id"]}, relocated=True)
            rep["_repair_start_event_id"] = unit.get("_repair_start_event_id")
        else:
            set_lifecycle(unit, "READY", relocated=True)
    return ok_object(assignment_json(asg))


@bp.post("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>/declare-lost")
def declare_lost(progId, studentId, assignmentId):
    b = body()
    reject_stray_occ(b)
    auth(["Registrar"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    asg = get_assignment(assignmentId, stu)
    if asg["status"] != "OVERDUE":
        fail("ERR_INVALID_STATE", 409, "Assignment must be OVERDUE to declare lost")
    if whole_days(asg["expected_return_date"], now()) < 30:
        fail("ERR_NOT_OVERDUE_LONG_ENOUGH", 409,
             "declare-lost requires the assignment to be OVERDUE for at least 30 days")
    asg["status"] = "LOST"
    touch(asg)
    unit = STORE["units"].get(asg["asset_unit_id"])
    if unit is not None:
        fleet = STORE["fleets"][unit["fleet_id"]]
        create_fee(stu, "NON_RETURN", fleet["unit_replacement_cost_cents"])
        set_lifecycle(unit, "END_OF_LIFE", "RETIRE")
    return ok_object(assignment_json(asg))


# -------------------------------------------------------- damage reports ---
@bp.post("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>/damage-reports")
def create_report(progId, studentId, assignmentId):
    b = body()
    category = req_enum(b, "damage_category", DAMAGE_CATEGORIES)
    observed = req_enum(b, "observed_condition_grade", GRADES)
    reject_stray_occ(b)
    uid, role = auth(["Family", "SiteTechnician"])
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    asg = get_assignment(assignmentId, stu)
    unit = STORE["units"].get(asg["asset_unit_id"])
    reported_by = "FAMILY" if role == "Family" else "SITE_TECH"
    rec = base_record()
    rec.update({
        "assignment_id": asg["id"],
        "reported_by_role": reported_by,
        "damage_category": category,
        "observed_condition_grade": observed,
        "provisional_fee_cents": provisional_fee(unit, category) if unit else 0,
        "final_fee_cents": None,
        "status": "DRAFT",
        "_sent_to_repair": False,
        "_repair_start_event_id": None,
    })
    STORE["reports"][rec["id"]] = rec
    # FUNCTIONAL/LIQUID/SCREEN with observed D/F sends the unit to the depot.
    if (unit is not None and category in ("FUNCTIONAL", "LIQUID", "SCREEN")
            and observed in ("D", "F") and unit["lifecycle_status"] == "DEPLOYED"):
        unit["_repair_student_id"] = stu["id"]
        set_lifecycle(unit, "IN_REPAIR", "REPAIR_START",
                      {"damage_report_id": rec["id"]})
        evs = [e for e in STORE["events"].values()
               if e["asset_unit_id"] == unit["id"] and e["event_type"] == "REPAIR_START"]
        if evs:
            rec["_repair_start_event_id"] = max(evs, key=lambda e: e["_seq"])["id"]
            unit["_repair_start_event_id"] = rec["_repair_start_event_id"]
        rec["_sent_to_repair"] = True
    return ok_object(report_json(rec), 201)


@bp.get("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>/damage-reports")
def list_reports(progId, studentId, assignmentId):
    uid, role = auth(ASSIGN_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    asg = get_assignment(assignmentId, stu)
    st = _q("status")
    recs = [r for r in STORE["reports"].values()
            if r["assignment_id"] == asg["id"]
            and (st is None or r["status"] == st)]
    return list_response(recs, report_json)


@bp.get("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>/damage-reports/<reportId>")
def get_report_route(progId, studentId, assignmentId, reportId):
    uid, role = auth(ASSIGN_READ)
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    asg = get_assignment(assignmentId, stu)
    return ok_object(report_json(get_report(reportId, asg)))


@bp.post("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>/damage-reports/<reportId>/submit")
def submit_report(progId, studentId, assignmentId, reportId):
    b = body()
    reject_stray_occ(b)
    uid, role = auth(["Family"])
    family_path_scope(studentId, uid, role)
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    asg = get_assignment(assignmentId, stu)
    rep = get_report(reportId, asg)
    if rep["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Report must be DRAFT to submit")
    if stu["family_agreement_status"] != "SIGNED":
        fail("ERR_AGREEMENT_NOT_SIGNED", 409, "Family agreement must be SIGNED")
    rep["status"] = "SUBMITTED"  # provisional_fee_cents frozen at submit time
    touch(rep)
    return ok_object(report_json(rep))


@bp.post("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>/damage-reports/<reportId>/confirm")
def confirm_report(progId, studentId, assignmentId, reportId):
    b = body()
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    asg = get_assignment(assignmentId, stu)
    rep = get_report(reportId, asg)
    if rep["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", 409, "Report must be SUBMITTED to confirm")
    unit = STORE["units"].get(asg["asset_unit_id"])
    gross = rep["provisional_fee_cents"]
    # Step 2: insurance deductible application (PRD 3.6).
    policy = None
    payout = 0
    if stu["insurance_enrolled"]:
        for p in STORE["policies"].values():
            if p["student_account_id"] == stu["id"] and p["status"] == "ACTIVE":
                policy = p
                break
    if policy is not None:
        remaining = policy["coverage_cap_cents"] - policy["_cumulative_payouts_cents"]
        if remaining >= gross - policy["deductible_cents"]:
            payout = max(0, gross - policy["deductible_cents"])
        else:
            payout = max(0, remaining)
        responsibility = gross - payout
    else:
        responsibility = gross
    # Step 3: fee waiver for free-lunch-eligible students (80%).
    if stu["free_lunch_eligible"]:
        waived = rhu(Decimal(responsibility) * Decimal("0.80"))
        responsibility -= waived
    # Step 4: enforcement cap at depreciated value for C/D/F observations.
    if rep["observed_condition_grade"] in ("C", "D", "F") and unit is not None:
        responsibility = min(responsibility, depreciated_value(unit))
    rep["final_fee_cents"] = responsibility
    rep["status"] = "CONFIRMED"
    touch(rep)
    stu["lifetime_damage_count"] += 1
    if policy is not None:
        policy["_cumulative_payouts_cents"] += payout
        if policy["_cumulative_payouts_cents"] >= policy["coverage_cap_cents"]:
            policy["status"] = "EXHAUSTED"
            touch(policy)
            stu["insurance_enrolled"] = False
    fee_type = "INSURANCE_DEDUCTIBLE" if policy is not None else "DAMAGE"
    create_fee(stu, fee_type, responsibility,
               source_damage_report_id=rep["id"],
               policy_id=policy["id"] if policy is not None else None)
    return ok_object(report_json(rep))


@bp.post("/api/programs/<progId>/students/<studentId>/assignments/<assignmentId>/damage-reports/<reportId>/dismiss")
def dismiss_report(progId, studentId, assignmentId, reportId):
    b = body()
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    stu = get_student(studentId, prog)
    asg = get_assignment(assignmentId, stu)
    rep = get_report(reportId, asg)
    if rep["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", 409, "Report must be SUBMITTED to dismiss")
    rep["status"] = "DISMISSED"
    touch(rep)
    unit = STORE["units"].get(asg["asset_unit_id"])
    if (unit is not None and rep.get("_sent_to_repair")
            and unit["lifecycle_status"] == "IN_REPAIR"):
        supersedes = rep.get("_repair_start_event_id")
        set_lifecycle(unit, "DEPLOYED", "CORRECTION", {}, supersedes)
        unit["assigned_to_student_id"] = stu["id"]
    return ok_object(report_json(rep))
