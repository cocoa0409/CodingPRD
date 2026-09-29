"""Placements: creation gates, lifecycle, compliance dimension, fiscal closeout."""

from decimal import Decimal

from flask import Blueprint

import calc
import derive
from auth import require
from db import by_created, db, new_record, today_str, touch
from errors import fail
from response import created, listing, ok
from validation import (f_date, f_enum, f_int, f_num, f_str, get_body, pagination,
                        paginate, q_enum, q_str)

bp = Blueprint("placements", __name__)

PAY_CLASSIFICATIONS = ("PAID", "UNPAID", "STIPEND")
CREDIT_AWARD_MODES = ("HOURS_BASED", "COMPETENCY_BASED")
TRANSPORT_MODES = ("DISTRICT_BUS", "PUBLIC_TRANSIT", "SELF", "GUARDIAN")
LIFECYCLE_STATUSES = ("PROPOSED", "ACTIVE", "COMPLETED", "TERMINATED")
COMPLIANCE_STATUSES = ("PENDING_REVIEW", "CLEARED", "FLAGGED", "BLOCKED")
COMPLIANCE_DECISIONS = ("CLEAR", "FLAG", "UNBLOCK")
SETTLEMENT_MODES = ("PROVISIONAL", "FINAL")
CREDIT_TARGETS = (Decimal("0.50"), Decimal("1.00"), Decimal("1.50"), Decimal("2.00"))


def _overlaps(a_start, a_end, b_start, b_end):
    """Closed intervals; touching endpoints count as overlapping."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/placements")
def create_placement():
    user_id, _role = require("WblCoordinator")
    body = get_body()

    # step 7: foreign keys in declaration order
    student = derive.get_student(f_str(body, "student_id"))
    worksite = derive.get_worksite(f_str(body, "worksite_id"))
    agreement = derive.get_agreement(f_str(body, "agreement_id"))
    supervisor = derive.get_supervisor(f_str(body, "supervisor_id"))
    supersedes_raw = f_str(body, "supersedes_placement_id", required=False)
    supersedes = None
    if supersedes_raw is not None:
        supersedes = derive.get_placement(supersedes_raw)

    # step 8: body shape
    pay_classification = f_enum(body, "pay_classification", PAY_CLASSIFICATIONS)
    hourly_wage_cents = f_int(body, "hourly_wage_cents", required=False, default=0, minimum=0)
    stipend_total_cents = f_int(body, "stipend_total_cents", required=False, default=0, minimum=0)
    scheduled_weekly_hours = f_num(body, "scheduled_weekly_hours", exclusive_min=0)
    start_on = f_date(body, "start_on")
    end_on = f_date(body, "end_on")
    credit_target = f_num(body, "credit_target_credits", minimum="0.50", maximum="2.00")
    if credit_target not in CREDIT_TARGETS:
        fail("ERR_INVALID_REQUEST",
             "Field 'credit_target_credits' must be 0.50, 1.00, 1.50 or 2.00.")
    credit_award_mode = f_enum(body, "credit_award_mode", CREDIT_AWARD_MODES)
    required_cycles = f_int(body, "required_evaluation_cycles", required=False, default=2,
                            minimum=1, maximum=4)
    transportation_mode = f_enum(body, "transportation_mode", TRANSPORT_MODES)
    miles = f_num(body, "commute_round_trip_miles", required=False,
                  default=Decimal("0.00"), minimum=0)
    expected_version = f_int(body, "expected_worksite_version")

    # step 9
    if expected_version != worksite["version"]:
        fail("ERR_STALE_WORKSITE_VERSION",
             "expected_worksite_version does not match the worksite's current version.")

    partner = derive.partner_of_worksite(worksite)

    # step 24
    if agreement["status"] != "EXECUTED":
        fail("ERR_AGREEMENT_NOT_EXECUTED",
             "The referenced partnership agreement is not executed.")
    # step 25
    derive.require_worksite_clearance(worksite)
    # step 26
    derive.require_posture(partner)
    # step 27
    if student["guardian_consent_on_file"] is not True:
        fail("ERR_GUARDIAN_CONSENT_MISSING",
             "The student's guardian consent is not on file.")

    age_at_start = calc.whole_years(student["birth_date"], start_on)
    permit_class_at_start = calc.band_for_age(age_at_start)
    is_minor = permit_class_at_start in calc.MINOR_BANDS

    # step 28
    permits = derive.matching_permits(student["id"], permit_class_at_start,
                                      require_unexpired=True)
    if not permits:
        fail("ERR_WORK_PERMIT_INVALID",
             "The student does not hold a valid work permit for this placement's age band.")
    # step 29
    if is_minor and worksite["hazard_class"] == "PROHIBITED_HAZARD":
        fail("ERR_HAZARDOUS_OCCUPATION_PROHIBITED",
             "A minor may not be placed at a prohibited-hazard worksite.")
    # step 30
    if is_minor and (worksite["hazard_class"] == "LIMITED_HAZARD"
                     or worksite["has_power_machinery"] is True):
        if not any(p["hazardous_endorsement"] is True for p in permits):
            fail("ERR_HAZARDOUS_ENDORSEMENT_MISSING",
                 "The student's work permit lacks the hazardous occupation endorsement.")
    # step 31
    derive.require_supervisor_training(supervisor)
    # step 35
    derive.require_workers_comp(partner)
    # step 39
    if not (start_on >= agreement["effective_on"]
            and end_on <= agreement["expires_on"]
            and end_on > start_on):
        fail("ERR_PLACEMENT_WINDOW_INVALID",
             "The placement window does not sit inside the agreement term.")
    # step 40
    concurrent = 1
    for other in derive.placements_of_worksite(worksite["id"]):
        if other["lifecycle_status"] not in derive.OPEN_LIFECYCLE:
            continue
        if _overlaps(start_on, end_on, other["start_on"], other["end_on"]):
            concurrent += 1
    if concurrent > worksite["max_concurrent_students"]:
        fail("ERR_WORKSITE_CAPACITY_EXCEEDED",
             "The worksite's concurrent student capacity is exhausted for this window.")
    # step 42
    if supervisor["worksite_id"] != worksite["id"]:
        fail("ERR_SUPERVISOR_WORKSITE_MISMATCH",
             "The supervisor does not belong to the placement's worksite.")
    # step 43
    if agreement["worksite_id"] != worksite["id"]:
        fail("ERR_AGREEMENT_WORKSITE_MISMATCH",
             "The agreement does not cover the placement's worksite.")
    # step 44
    if supervisor["active_student_load"] + 1 > supervisor["max_student_load"]:
        fail("ERR_SUPERVISOR_LOAD_EXCEEDED",
             "The supervisor's mentoring load is already at its maximum.")
    # step 45
    if student["eligibility_status"] != "ELIGIBLE":
        fail("ERR_STUDENT_INELIGIBLE", "The student is not eligible for a placement.")
    # step 50
    if pay_classification == "PAID":
        floor = (calc.LEARNER_WAGE_FLOOR_CENTS
                 if student["student_learner_certificate"] is True
                 else calc.MIN_WAGE_CENTS)
        if hourly_wage_cents < floor:
            fail("ERR_WAGE_BELOW_MINIMUM",
                 "The hourly wage is below the applicable wage floor.")
    # step 51
    if pay_classification == "UNPAID":
        if worksite["displaces_paid_employee"] is True or hourly_wage_cents != 0:
            fail("ERR_UNPAID_CLASSIFICATION_INVALID",
                 "An UNPAID placement may not displace a paid employee or carry a wage.")
    elif pay_classification == "STIPEND":
        if stipend_total_cents <= 0 or hourly_wage_cents != 0:
            fail("ERR_UNPAID_CLASSIFICATION_INVALID",
                 "A STIPEND placement requires a positive stipend and no hourly wage.")

    placement = new_record()
    placement.update({
        "student_id": student["id"],
        "worksite_id": worksite["id"],
        "agreement_id": agreement["id"],
        "supervisor_id": supervisor["id"],
        "supersedes_placement_id": supersedes["id"] if supersedes else None,
        "pay_classification": pay_classification,
        "hourly_wage_cents": hourly_wage_cents,
        "stipend_total_cents": stipend_total_cents,
        "scheduled_weekly_hours": scheduled_weekly_hours,
        "start_on": start_on,
        "end_on": end_on,
        "credit_target_credits": credit_target,
        "credit_award_mode": credit_award_mode,
        "required_evaluation_cycles": required_cycles,
        "transportation_mode": transportation_mode,
        "commute_round_trip_miles": miles,
        "student_age_at_start": age_at_start,
        "permit_class_at_start": permit_class_at_start,
        "total_verified_hours": calc.rh(0, 2),
        "closed_cycle_count": 0,
        "credit_eligible": False,
        "provisional_wage_cents": (stipend_total_cents
                                   if pay_classification == "STIPEND" else 0),
        "final_wage_cents": (stipend_total_cents
                             if pay_classification == "STIPEND" else 0),
        "lifecycle_status": "PROPOSED",
        "compliance_status": "PENDING_REVIEW",
        "training_plan_approved_at": None,
        "settled_wage_cents": 0,
        "wage_settlement_mode": "NONE",
        "credits_awarded": calc.rh(0, 2),
        "credit_awarded_by_user_id": None,
        "completed_on": None,
        "termination_reason": None,
        "created_by_user_id": user_id,
    })
    db.placements[placement["id"]] = placement

    derive.recompute_worksite_counters(worksite)
    derive.recompute_supervisor(supervisor)
    derive.recompute_student(student)
    return created(placement)


@bp.post("/placements/<placementId>/activate")
def activate_placement(placementId):
    require("WblCoordinator")
    placement = derive.get_placement(placementId)

    plan = derive.operative_plan(placement["id"])
    if placement["lifecycle_status"] != "PROPOSED":
        fail("ERR_PLACEMENT_NOT_ACTIVATABLE", "The placement is not in the PROPOSED state.")
    if placement["compliance_status"] != "CLEARED":
        fail("ERR_PLACEMENT_NOT_ACTIVATABLE",
             "The placement's compliance dimension has not cleared.")
    if plan is None or plan["status"] != "APPROVED":
        fail("ERR_PLACEMENT_NOT_ACTIVATABLE",
             "The placement has no approved training plan.")

    agreement = db.agreements.get(placement["agreement_id"])
    if agreement is None or agreement["status"] != "EXECUTED":
        fail("ERR_AGREEMENT_NOT_EXECUTED",
             "The referenced partnership agreement is not executed.")
    worksite = derive.get_worksite(placement["worksite_id"])
    derive.require_worksite_clearance(worksite)

    placement["lifecycle_status"] = "ACTIVE"
    touch(placement)
    if not derive.cycles_of(placement["id"]):
        derive.create_cycle(placement, 1, placement["start_on"])
    return ok(placement)


@bp.post("/placements/<placementId>/terminate")
def terminate_placement(placementId):
    require("WblCoordinator")
    placement = derive.get_placement(placementId)
    body = get_body()
    reason = f_str(body, "termination_reason")

    if placement["lifecycle_status"] not in derive.OPEN_LIFECYCLE:
        fail("ERR_PLACEMENT_NOT_ACTIVE",
             "Only a proposed or active placement may be terminated.")

    placement["lifecycle_status"] = "TERMINATED"
    placement["termination_reason"] = reason
    touch(placement)
    derive.cancel_cycles(placement["id"], ("OPEN", "PARTIAL", "SUSPENDED"))
    derive.release_placement_capacity(placement)
    return ok(placement)


@bp.post("/placements/<placementId>/complete")
def complete_placement(placementId):
    require("WblCoordinator")
    placement = derive.get_placement(placementId)

    if placement["lifecycle_status"] != "ACTIVE":
        fail("ERR_PLACEMENT_NOT_ACTIVE", "The placement is not active.")
    if placement["compliance_status"] == "BLOCKED":
        fail("ERR_PLACEMENT_COMPLIANCE_BLOCKED",
             "The placement's compliance dimension is blocked.")
    if placement["closed_cycle_count"] < placement["required_evaluation_cycles"]:
        fail("ERR_EVALUATION_CYCLES_INCOMPLETE",
             "The placement has not closed its required evaluation cycles.")

    placement["lifecycle_status"] = "COMPLETED"
    placement["completed_on"] = today_str()
    touch(placement)
    derive.cancel_cycles(placement["id"], ("OPEN", "PARTIAL"))
    derive.release_placement_capacity(placement)
    return ok(placement)


@bp.post("/placements/<placementId>/compliance-decision")
def compliance_decision(placementId):
    require("ComplianceOfficer")
    placement = derive.get_placement(placementId)
    body = get_body()
    decision = f_enum(body, "decision", COMPLIANCE_DECISIONS)
    f_str(body, "note")

    if placement["lifecycle_status"] not in derive.OPEN_LIFECYCLE:
        fail("ERR_PLACEMENT_NOT_ACTIVE",
             "Only a proposed or active placement carries a compliance decision.")

    current = placement["compliance_status"]
    if decision == "CLEAR":
        if current != "FLAGGED":
            fail("ERR_INVALID_REQUEST",
                 "CLEAR requires the placement's compliance dimension to be FLAGGED.")
        permits = derive.matching_permits(placement["student_id"],
                                          placement["permit_class_at_start"])
        if not permits:
            fail("ERR_WORK_PERMIT_INVALID",
                 "The student does not hold an issued permit for this placement's age band.")
        placement["compliance_status"] = "CLEARED"
        touch(placement)
    elif decision == "FLAG":
        if current != "CLEARED":
            fail("ERR_INVALID_REQUEST",
                 "FLAG requires the placement's compliance dimension to be CLEARED.")
        placement["compliance_status"] = "FLAGGED"
        touch(placement)
    else:  # UNBLOCK
        if current != "BLOCKED":
            fail("ERR_INVALID_REQUEST",
                 "UNBLOCK requires the placement's compliance dimension to be BLOCKED.")
        worksite = derive.get_worksite(placement["worksite_id"])
        if worksite["safety_status"] not in derive.LIVE_SAFETY:
            fail("ERR_WORKSITE_SAFETY_NOT_CURRENT",
                 "The worksite does not hold an approved or conditional safety clearance.")
        derive.require_posture(derive.partner_of_worksite(worksite))
        placement["compliance_status"] = "FLAGGED"
        touch(placement)
        derive.restore_cycles(placement["id"])

    return ok(placement)


@bp.post("/placements/<placementId>/settle-wages")
def settle_wages(placementId):
    require("WblCoordinator")
    placement = derive.get_placement(placementId)
    body = get_body()
    mode = f_enum(body, "mode", SETTLEMENT_MODES)

    if placement["lifecycle_status"] != "COMPLETED":
        fail("ERR_PLACEMENT_NOT_COMPLETED", "The placement is not completed.")
    if placement["compliance_status"] == "BLOCKED":
        fail("ERR_PLACEMENT_COMPLIANCE_BLOCKED",
             "The placement's compliance dimension is blocked.")
    if placement["wage_settlement_mode"] != "NONE":
        fail("ERR_WAGES_ALREADY_SETTLED", "The placement's wages are already settled.")

    provisional, final = calc.wage_variants(placement)
    if placement["pay_classification"] == "PAID" and provisional <= 0:
        fail("ERR_WAGE_SETTLEMENT_NOT_READY",
             "The placement has no logged hours to settle.")

    placement["settled_wage_cents"] = provisional if mode == "PROVISIONAL" else final
    placement["wage_settlement_mode"] = mode
    touch(placement)

    if mode == "FINAL":
        partner = derive.partner_of_placement(placement)
        if partner is not None:
            derive.recompute_partner_liability(partner)
    return ok(placement)


@bp.post("/placements/<placementId>/award-credit")
def award_credit(placementId):
    user_id, _role = require("WblCoordinator")
    placement = derive.get_placement(placementId)

    plan = derive.operative_plan(placement["id"])
    # step 4: segregation of duties against the plan approver
    if plan is not None and plan.get("approved_by_user_id") == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The operator who approved the training plan may not award its credit.")

    if placement["lifecycle_status"] != "COMPLETED":
        fail("ERR_PLACEMENT_NOT_COMPLETED", "The placement is not completed.")
    if placement["compliance_status"] == "BLOCKED":
        fail("ERR_PLACEMENT_COMPLIANCE_BLOCKED",
             "The placement's compliance dimension is blocked.")
    if calc.dec(placement["credits_awarded"]) != calc.ZERO:
        fail("ERR_CREDIT_ALREADY_AWARDED", "Credit has already been awarded.")

    placement["credits_awarded"] = calc.credit_for_mode(placement)
    placement["credit_awarded_by_user_id"] = user_id
    touch(placement)

    student = db.students.get(placement["student_id"])
    if student is not None:
        derive.recompute_student(student)
    return ok(placement)


@bp.get("/placements/<placementId>")
def read_placement(placementId):
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor", "Student")
    return ok(derive.get_placement(placementId))


@bp.get("/placements")
def list_placements():
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor")
    limit, offset = pagination()
    student_id = q_str("student_id")
    worksite_id = q_str("worksite_id")
    agreement_id = q_str("agreement_id")
    supervisor_id = q_str("supervisor_id")
    supersedes_id = q_str("supersedes_placement_id")
    lifecycle_status = q_enum("lifecycle_status", LIFECYCLE_STATUSES)
    compliance_status = q_enum("compliance_status", COMPLIANCE_STATUSES)

    rows = []
    for placement in db.placements.values():
        if student_id is not None and placement["student_id"] != student_id:
            continue
        if worksite_id is not None and placement["worksite_id"] != worksite_id:
            continue
        if agreement_id is not None and placement["agreement_id"] != agreement_id:
            continue
        if supervisor_id is not None and placement["supervisor_id"] != supervisor_id:
            continue
        if supersedes_id is not None and placement["supersedes_placement_id"] != supersedes_id:
            continue
        if lifecycle_status is not None and placement["lifecycle_status"] != lifecycle_status:
            continue
        if compliance_status is not None and placement["compliance_status"] != compliance_status:
            continue
        rows.append(placement)

    page, total = paginate(by_created(rows), limit, offset)
    return listing(page, total, limit, offset)


@bp.get("/placements/<placementId>/wage-preview")
def wage_preview(placementId):
    require("WblCoordinator", "ComplianceOfficer")
    placement = derive.get_placement(placementId)
    provisional, final = calc.wage_variants(placement)
    entries = calc.logged_entries(placement["id"])
    return ok({
        "provisional_wage_cents": provisional,
        "final_wage_cents": final,
        "variance_cents": provisional - final,
        "total_verified_hours": calc.total_logged_hours(placement["id"]),
        "logged_entry_count": len(entries),
    })


@bp.get("/placements/<placementId>/credit-preview")
def credit_preview(placementId):
    require("WblCoordinator", "ComplianceOfficer")
    placement = derive.get_placement(placementId)
    return ok({
        "hours_based_credits": calc.rh(calc.hours_based_credits(placement), 2),
        "competency_based_credits": calc.rh(calc.competency_based_credits(placement), 2),
        "mean_competency_score": calc.mean_competency(placement["id"]),
        "closed_cycle_count": placement["closed_cycle_count"],
        "credit_eligible": placement["credit_eligible"],
    })


@bp.get("/placements/<placementId>/reimbursement")
def reimbursement_preview(placementId):
    require("WblCoordinator")
    placement = derive.get_placement(placementId)
    return ok(calc.reimbursement(placement))
