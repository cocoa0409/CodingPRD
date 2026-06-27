"""TreatmentPlan workflow helpers (PRD §3.4-§3.6)."""
from clock import clock, format_iso8601_ms, parse_iso8601
from db import db
from errors import err
from models import base_record, touch
from services.calculations import case_price
from services.dates import add_weeks
from services.minor import is_minor_for_case


def clinician_licensed(clinician, patient):
    return patient["state_code"] in clinician["license_state_codes"]


def assert_assigned_and_licensed(plan, case, acting_clinician_id):
    """Plan-review actions require the acting clinician to be the case's assigned
    reviewer and licensed in the patient's state (PRD §3.4/§3.5/§3.6)."""
    clinician = db.clinicians.get(acting_clinician_id)
    patient = db.patients.get(case["patient_id"])
    # Acting clinician must be the assigned one and licensed in the patient state.
    if (clinician is None
            or case["assigned_clinician_id"] != acting_clinician_id
            or not clinician_licensed(clinician, patient)):
        raise err("ERR_CLINICIAN_NOT_LICENSED",
                  "Acting clinician is not the assigned, suitably-licensed reviewer.")


def approve_plan(plan, case):
    """Price the case, generate AlignerStep rows, compute scheduled_ship_at."""
    # pricing
    total = case_price(
        case["list_price_cents"], case["intake_channel"],
        plan["proposed_step_count"], plan.get("discount_code"),
    )
    case["total_contracted_cents"] = total

    approval_dt = clock.now()
    weeks_per_step = plan["weeks_per_step"]
    n = plan["proposed_step_count"]
    for idx in range(1, n + 1):
        step = base_record(common_fields=True)
        ship_dt = add_weeks(approval_dt, (idx - 1) * weeks_per_step)
        step.update({
            "case_id": case["id"],
            "step_index": idx,
            "status": "PLANNED",
            "supersedes_step_id": None,
            "scheduled_ship_at": format_iso8601_ms(ship_dt),
        })
        db.aligner_steps[step["id"]] = step
    case["planned_step_count"] = n

    case["status"] = "PLAN_APPROVED"
    touch(case)
    plan["status"] = "APPROVED"
    touch(plan)


def decline_plan(plan, case):
    """Set plan ELIGIBILITY_DECLINED, case DECLINED, auto-open a refund."""
    plan["status"] = "ELIGIBILITY_DECLINED"
    touch(plan)
    case["status"] = "DECLINED"
    touch(case)
    # auto-open RefundRequest (reason=ELIGIBILITY_DECLINE) — cascade depth 1.
    # Opening a refund increments case.version (PRD §3.11).
    refund = base_record(common_fields=True)
    refund.update({
        "case_id": case["id"],
        "reason": "ELIGIBILITY_DECLINE",
        "status": "OPEN",
        "computed_refund_cents": 0,
        "restocking_fee_cents": 0,
    })
    db.refunds[refund["id"]] = refund
    touch(case)
    return refund
