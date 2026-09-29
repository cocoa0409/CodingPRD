"""Field operations: ordering, mobilizing, reporting and review (PRD 3.7)."""
from flask import Blueprint

import calc
import validate as v
from auth import (AWARD_AUTHORITY, CONTRACTOR, DETERMINATION_REVIEWER,
                  FIELD_INSPECTOR, FUNDING_OFFICER, PROCUREMENT_OFFICER,
                  PROGRAM_ADMIN, endpoint, not_owner, role, user_id)
from envelope import filter_value, object_response, paginated
from errors import ApiError
from lookup import collect, get_contract, get_contractor, get_job, get_well
from store import clock, db, days, new_row, touch

bp = Blueprint("jobs", __name__)

REVIEW_ACTIONS = ("ACCEPT", "REWORK")
MAX_REWORK_ROUNDS = 2
CREW_BLOCKING_STATUSES = ("SCHEDULED", "MOBILIZED", "FIELD_REPORTED",
                          "REWORK_REQUIRED")
AUTHORIZED_ACCESS = ("AGREEMENT_EXECUTED", "ENTRY_ORDERED")
TASK_TYPES = ("EQUIPMENT_REMOVAL", "PIT_CLOSURE", "REVEGETATION")

JOB_READERS = (PROGRAM_ADMIN, FIELD_INSPECTOR, PROCUREMENT_OFFICER,
               AWARD_AUTHORITY, FUNDING_OFFICER, CONTRACTOR)


def bad_transition(message):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def contract_not_active():
    return ApiError(
        "ERR_CONTRACT_NOT_ACTIVE",
        "The unit-cost contract is not ACTIVE.",
    )


def ceiling_exceeded():
    return ApiError(
        "ERR_CONTRACT_CEILING_EXCEEDED",
        "The contract's obligation would exceed its ceiling.",
    )


def _well_jobs(well_id):
    return [j for j in db.jobs.values() if j["well_id"] == well_id]


def _apply_contract_obligation(contract, obligation, may_close=False):
    """Raise the contract's obligation.

    PRD 3.7 attaches the ACTIVE -> CLOSED transition to the field report alone
    ("If it lands exactly on `ceiling_cents`, the contract transitions
    `ACTIVE -> CLOSED`"); the contract-exposure paragraph that governs ordering a
    job states only the rejection rule, so an order that lands exactly on the
    ceiling leaves the contract ACTIVE.
    """
    contract["obligated_cents"] = obligation
    if (may_close and contract["status"] == "ACTIVE"
            and obligation == contract["ceiling_cents"]):
        contract["status"] = "CLOSED"
    touch(contract)


@bp.route("/plugging-jobs", methods=["POST"])
@endpoint((PROGRAM_ADMIN, PROCUREMENT_OFFICER))
def create_job():
    data = v.body()

    # Step 6: body reference existence, left to right.
    if isinstance(data.get("well_id"), str) and data["well_id"] != "":
        get_well(data["well_id"])
    if isinstance(data.get("contract_id"), str) and data["contract_id"] != "":
        get_contract(data["contract_id"])

    well_id = v.str_field(data, "well_id")
    contract_id = v.str_field(data, "contract_id")
    scheduled_start = v.datetime_field(data, "scheduled_start")
    planned_cement_sacks = v.int_field(data, "planned_cement_sacks",
                                       exclusive_minimum=0)
    planned_rig_days = v.int_field(data, "planned_rig_days", exclusive_minimum=0)
    planned_casing_ft = v.int_field(data, "planned_casing_ft", minimum=0)

    well = get_well(well_id)
    contract = get_contract(contract_id)

    # Step 11: the referenced well must be ORPHAN_CONFIRMED.
    if well["status"] != "ORPHAN_CONFIRMED":
        raise ApiError(
            "ERR_WELL_NOT_ORPHAN_CONFIRMED",
            "Plugging may only be ordered for an ORPHAN_CONFIRMED well.",
        )

    for existing in _well_jobs(well_id):
        if existing["status"] != "RECLAIMED":
            raise bad_transition("This well already carries a live plugging job.")

    crew_window_end_at = scheduled_start + days(
        planned_rig_days + calc.CREW_DEMOB_BUFFER_DAYS
    )

    # Step 14: half-open crew occupancy intervals may not overlap.
    for other in db.jobs.values():
        if other["status"] not in CREW_BLOCKING_STATUSES:
            continue
        other_contract = db.contracts.get(other["contract_id"])
        if other_contract is None:
            continue
        if other_contract["contractor_id"] != contract["contractor_id"]:
            continue
        if (scheduled_start < other["crew_window_end_at"]
                and other["scheduled_start"] < crew_window_end_at):
            raise ApiError(
                "ERR_CREW_WINDOW_CONFLICT",
                "The crew is already occupied during that window.",
            )

    # Step 15: the contract must be usable.
    if contract["status"] != "ACTIVE":
        raise contract_not_active()

    estimate = calc.plugging_estimate_cents(
        contract, planned_cement_sacks, planned_rig_days, planned_casing_ft
    )

    # Step 17: contract exposure.
    obligation = calc.contract_obligation_cents(contract_id, extra_estimate=estimate)
    if obligation > contract["ceiling_cents"]:
        raise ceiling_exceeded()

    row = new_row()
    row.update({
        "well_id": well_id,
        "contract_id": contract_id,
        "scheduled_start": scheduled_start,
        "planned_cement_sacks": planned_cement_sacks,
        "planned_rig_days": planned_rig_days,
        "planned_casing_ft": planned_casing_ft,
        "plugging_cost_estimate_cents": estimate,
        "crew_window_end_at": crew_window_end_at,
        "status": "SCHEDULED",
        "rework_round": 0,
        "cement_sacks_used": None,
        "rig_days_used": None,
        "casing_removed_ft": None,
        "downhole_conditions": None,
        "plug_intervals": None,
        "last_round_cost_cents": None,
        "actual_cost_cents": 0,
        "funded_cents": 0,
        "mobilized_at": None,
        "plugging_accepted_at": None,
        "reclaimed_at": None,
    })
    db.jobs[row["id"]] = row

    _apply_contract_obligation(contract, obligation)

    well["status"] = "PLUGGING_SCHEDULED"
    touch(well)

    return object_response(row, 201)


@bp.route("/plugging-jobs/<job_id>", methods=["GET"])
@endpoint(JOB_READERS)
def fetch_job(job_id):
    return object_response(get_job(job_id))


@bp.route("/plugging-jobs", methods=["GET"])
@endpoint(JOB_READERS)
def list_jobs():
    well_id = filter_value("well_id")
    contract_id = filter_value("contract_id")
    status = filter_value("status")

    def keep(row):
        if well_id is not None and row["well_id"] != well_id:
            return False
        if contract_id is not None and row["contract_id"] != contract_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(collect(db.jobs, keep))


@bp.route("/plugging-jobs/<job_id>/mobilize", methods=["POST"])
@endpoint((PROGRAM_ADMIN, FIELD_INSPECTOR))
def mobilize_job(job_id):
    job = get_job(job_id)

    if job["status"] != "SCHEDULED":
        raise bad_transition(
            "A job in %s cannot be mobilized." % job["status"]
        )

    well = get_well(job["well_id"])
    contract = get_contract(job["contract_id"])
    contractor = get_contractor(contract["contractor_id"])

    # Step 12: safety gate.
    if well["access_status"] not in AUTHORIZED_ACCESS:
        raise ApiError(
            "ERR_SITE_ACCESS_NOT_AUTHORIZED",
            "The agency has no legal right of entry on this well site.",
        )

    # Step 15: referential business gates, in the declared order.
    if contractor["license_status"] != "GOOD_STANDING":
        raise ApiError(
            "ERR_CONTRACTOR_NOT_ELIGIBLE",
            "The contractor's licence is %s." % contractor["license_status"],
        )
    if contract["status"] != "ACTIVE":
        raise contract_not_active()

    job["status"] = "MOBILIZED"
    job["mobilized_at"] = clock()
    touch(job)
    return object_response(job)


def _obligation_with_actual(contract_id, job_id, candidate_actual):
    total = 0
    for job in db.jobs.values():
        if job["contract_id"] != contract_id:
            continue
        actual = candidate_actual if job["id"] == job_id else job["actual_cost_cents"]
        total += max(job["plugging_cost_estimate_cents"], actual or 0)
    return total


@bp.route("/plugging-jobs/<job_id>/field-report", methods=["POST"])
@endpoint((FIELD_INSPECTOR, CONTRACTOR), needs_user_id=True)
def file_field_report(job_id):
    job = get_job(job_id)
    contract = get_contract(job["contract_id"])

    # Step 3: contractors may only report on their own work.
    if role() == CONTRACTOR and contract["contractor_id"] != user_id():
        raise not_owner("This plugging job belongs to another contractor.")

    data = v.body()
    cement_sacks_used = v.int_field(data, "cement_sacks_used", minimum=0)
    rig_days_used = v.int_field(data, "rig_days_used", minimum=0)
    casing_removed_ft = v.int_field(data, "casing_removed_ft", minimum=0)
    downhole_conditions = v.str_field(data, "downhole_conditions")
    plug_intervals = v.array_field(data, "plug_intervals")

    if job["status"] not in ("MOBILIZED", "REWORK_REQUIRED"):
        raise bad_transition(
            "A field report cannot be filed on a job in %s." % job["status"]
        )

    # Step 15: the contract must still be usable.
    if contract["status"] != "ACTIVE":
        raise contract_not_active()

    round_number = job["rework_round"] + 1
    round_cost = calc.round_cost_cents(
        contract, round_number, cement_sacks_used, rig_days_used, casing_removed_ft
    )
    candidate_actual = job["actual_cost_cents"] + round_cost

    # Step 17: nothing is written when the ceiling would be breached.
    obligation = _obligation_with_actual(contract["id"], job["id"], candidate_actual)
    if obligation > contract["ceiling_cents"]:
        raise ceiling_exceeded()

    job["cement_sacks_used"] = cement_sacks_used
    job["rig_days_used"] = rig_days_used
    job["casing_removed_ft"] = casing_removed_ft
    job["downhole_conditions"] = downhole_conditions
    job["plug_intervals"] = plug_intervals
    job["last_round_cost_cents"] = round_cost
    job["actual_cost_cents"] = candidate_actual
    job["status"] = "FIELD_REPORTED"
    touch(job)

    _apply_contract_obligation(contract, obligation, may_close=True)

    return object_response(job)


@bp.route("/plugging-jobs/<job_id>/review", methods=["POST"])
@endpoint((PROGRAM_ADMIN, DETERMINATION_REVIEWER))
def review_field_report(job_id):
    job = get_job(job_id)
    data = v.body()
    action = v.enum_field(data, "action", REVIEW_ACTIONS)
    v.str_field(data, "findings")

    if job["status"] != "FIELD_REPORTED":
        raise bad_transition(
            "A job in %s has no field report awaiting review." % job["status"]
        )

    if action == "REWORK":
        # Step 16: bounded operations cycle.
        if job["rework_round"] >= MAX_REWORK_ROUNDS:
            raise ApiError(
                "ERR_REWORK_LIMIT_EXCEEDED",
                "This job has already used its %d rework rounds."
                % MAX_REWORK_ROUNDS,
            )
        job["rework_round"] += 1
        job["status"] = "REWORK_REQUIRED"
        touch(job)
        return object_response(job)

    job["status"] = "PLUGGED"
    job["plugging_accepted_at"] = clock()
    touch(job)

    # Cascade hop 1: the three surface reclamation tasks.
    for task_type in TASK_TYPES:
        task = new_row()
        task.update({
            "job_id": job["id"],
            "task_type": task_type,
            "status": "PENDING",
            "inspection_round": 0,
            "inspected_by_user_id": None,
            "notes": None,
            "completed_at": None,
        })
        db.tasks[task["id"]] = task

    # Cascade hops 2-4: the well, then the operator's computed fields.
    well = get_well(job["well_id"])
    if well["status"] == "PLUGGING_SCHEDULED":
        well["status"] = "PLUGGED"
        touch(well)
        operator = db.operators.get(well["operator_id"])
        if operator is not None:
            calc.recompute_operator(operator)

    return object_response(job)
