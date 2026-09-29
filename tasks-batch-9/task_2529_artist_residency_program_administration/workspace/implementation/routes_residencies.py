"""Residency formation, scheduling, the two state axes, trainings and stipend schedules."""

from datetime import timedelta

import calc
import domain as D
import store as K
from auth import authorize, require_owner
from envelope import created_rows_response, object_response, paged, query_str
from errors import ApiError
from flask import Blueprint
from store import create_row, store, touch
from validate import (body, d, ds, fk, occ, opt_int, opt_str, path_row,
                      req_date, req_enum, req_int, req_str)

bp = Blueprint("residencies", __name__)

READ_RESIDENCY_ROLES = ["ProgramAdmin", "FinanceOfficer", "VisaCoordinator",
                        "FacilitiesManager", "Funder", "Applicant"]

RESIDENCY_TERMINAL = ("COMPLETED", "TERMINATED", "WITHDRAWN")
LIFECYCLE_ACTIONS = ["CHECK_IN", "COMPLETE", "TERMINATE", "WITHDRAW"]
LIFECYCLE_EDGE = {
    "CHECK_IN": ("SCHEDULED", "IN_RESIDENCE"),
    "COMPLETE": ("IN_RESIDENCE", "COMPLETED"),
    "TERMINATE": ("IN_RESIDENCE", "TERMINATED"),
    "WITHDRAW": ("SCHEDULED", "WITHDRAWN"),
}


def _trainings_covered(res):
    done = set(res["completed_training_types"])
    return all(item in done for item in res["required_training_types"])


# ---------------------------------------------------------------- creation
@bp.route("/residencies", methods=["POST"])
def create_residency():
    authorize(["ProgramAdmin"])
    b = body()
    # group 2 -- body foreign keys in declaration order
    cycle = fk(b, "cycle_id", store.cycles, "ERR_CYCLE_NOT_FOUND")
    applicant = fk(b, "applicant_id", store.applicants, "ERR_APPLICANT_NOT_FOUND")
    discipline = fk(b, "discipline_id", store.disciplines, "ERR_DISCIPLINE_NOT_FOUND")
    predecessor = fk(b, "predecessor_residency_id", store.residencies,
                     "ERR_RESIDENCY_NOT_FOUND")
    source = fk(b, "application_id", store.applications, "ERR_APPLICATION_NOT_FOUND")
    # group 3 -- shape
    req_str(b, "cycle_id")
    req_str(b, "applicant_id")
    req_str(b, "discipline_id")
    opt_str(b, "predecessor_residency_id")
    opt_str(b, "application_id")
    # group 6 -- the cycle must be neither DRAFT nor CLOSED
    if cycle["status"] in ("DRAFT", "CLOSED"):
        raise ApiError("ERR_CYCLE_STAGE_INVALID",
                       "a direct residency may not be created while the cycle is %s"
                       % cycle["status"])
    # group 8 -- the follow-on chain and the discipline's cycle
    if predecessor is not None:
        if predecessor["status"] != "COMPLETED" \
                or predecessor["applicant_id"] != applicant["id"]:
            raise ApiError("ERR_PREDECESSOR_NOT_COMPLETED",
                           "the predecessor residency must be a COMPLETED residency "
                           "of the same artist")
    if discipline["cycle_id"] != cycle["id"]:
        raise ApiError("ERR_PREDECESSOR_NOT_COMPLETED",
                       "the named discipline belongs to a different cycle")

    res = D.new_residency(
        cycle_id=cycle["id"],
        applicant_id=applicant["id"],
        discipline_code=discipline["code"],
        application_id=source["id"] if source is not None else None,
        predecessor_residency_id=predecessor["id"] if predecessor is not None else None,
        weekly_rate_cents=int(cycle["stipend_weekly_rate_cents"]),
        stipend_total_cents=0,
    )
    if D.residency_visa_required(res):
        D.new_visa_case(res["id"])
    touch(cycle)
    return object_response(D.ser_residency(res), 201)


@bp.route("/residencies", methods=["GET"])
def list_residencies():
    authorize(READ_RESIDENCY_ROLES)
    filters = {
        "cycle_id": query_str("cycle_id"),
        "application_id": query_str("application_id"),
        "applicant_id": query_str("applicant_id"),
        "predecessor_residency_id": query_str("predecessor_residency_id"),
        "status": query_str("status"),
        "compliance_status": query_str("compliance_status"),
    }
    rows = D.by_seq(list(store.residencies.values()))
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, D.ser_residency)


@bp.route("/residencies/<residency_id>", methods=["GET"])
def get_residency(residency_id):
    authorize(READ_RESIDENCY_ROLES)
    res = path_row(store.residencies, residency_id, "ERR_RESIDENCY_NOT_FOUND")
    return object_response(D.ser_residency(res))


# ---------------------------------------------------------------- scheduling
@bp.route("/residencies/<residency_id>/schedule", methods=["POST"])
def schedule_residency(residency_id):
    authorize(["ProgramAdmin"])
    res = path_row(store.residencies, residency_id, "ERR_RESIDENCY_NOT_FOUND")
    b = body()
    start = req_date(b, "session_start_date")
    weeks = req_int(b, "session_length_weeks",
                    minimum=K.MIN_SESSION_WEEKS, maximum=K.MAX_SESSION_WEEKS)

    # group 6 -- only a residency that has not yet checked in may be scheduled
    if res["status"] != "SCHEDULED":
        raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                       "a residency in %s cannot be rescheduled" % res["status"])
    cycle = store.cycles[res["cycle_id"]]
    # group 9 -- the offered lengths, then the calendar, then the money
    if weeks not in cycle["session_length_options_weeks"]:
        raise ApiError("ERR_SESSION_LENGTH_NOT_OFFERED",
                       "%d weeks is not one of this cycle's session length options" % weeks)
    if start < store.today():
        raise ApiError("ERR_SESSION_START_IN_PAST",
                       "the session start date is earlier than the current programme date")
    for row in D.residency_disbursements(res["id"]):
        if row["status"] == "PAID":
            raise ApiError("ERR_RESIDENCY_ALREADY_PAID",
                           "money has already moved against the existing calendar")

    rate = int(res["stipend_weekly_rate_cents"])
    new_total = calc.provisional_award(rate, weeks)
    old_total = int(res["stipend_total_cents"] or 0)
    _, uncommitted, _, _ = D.cycle_ledger(cycle)
    if uncommitted < new_total - old_total:
        raise ApiError("ERR_STIPEND_POOL_EXHAUSTED",
                       "the remaining stipend pool cannot cover the confirmed length")

    res["session_start_date"] = ds(start)
    res["session_length_weeks"] = weeks
    res["session_end_date"] = ds(start + timedelta(days=weeks * 7 - 1))
    res["required_training_types"] = D.derive_required_training_types(res)
    D.provision_obligations(res)
    res["stipend_total_cents"] = new_total
    touch(res)

    case = D.visa_case_of(res["id"])
    if case is not None:
        case["case_type"] = calc.visa_case_type(weeks)
        touch(case)
    touch(cycle)
    return object_response(D.ser_residency(res))


# ---------------------------------------------------------------- lifecycle axis
def _check_in(res):
    start = d(res.get("session_start_date"))
    if start is None or store.today() < start:
        raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                       "check-in requires a session start date at or before today")
    if res["compliance_status"] != "CLEARED":
        raise ApiError("ERR_TRAINING_NOT_COMPLETE",
                       "the resident's compliance status is %s, not CLEARED"
                       % res["compliance_status"])
    if D.residency_visa_required(res):
        case = D.visa_case_of(res["id"])
        if case is None or case["status"] != "APPROVED":
            raise ApiError("ERR_VISA_NOT_APPROVED",
                           "the sponsored artist's visa case is not APPROVED")
    res["status"] = "IN_RESIDENCE"
    touch(res)


def _breach_unmet_obligations(res):
    for ob in D.residency_obligations(res["id"]):
        if ob["status"] != "PENDING":
            continue
        if int(ob["completed_count"]) < int(ob["required_count"]):
            ob["status"] = "BREACHED"
            touch(ob)


def _waive_pending_obligations(res, reason):
    for ob in D.residency_obligations(res["id"]):
        if ob["status"] != "PENDING":
            continue
        ob["status"] = "WAIVED"
        ob["waived_reason"] = reason
        touch(ob)


def _complete(res):
    end = d(res.get("session_end_date"))
    if end is None or store.today() < end:
        raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                       "completion requires the programme date to be at or after "
                       "the session end date")
    res["actual_weeks_in_residence"] = res["session_length_weeks"]
    _breach_unmet_obligations(res)
    D.release_studio_assignments(res, "RESIDENCY_COMPLETED", clear_code=False)
    D.release_housing_assignments(res, "RESIDENCY_COMPLETED", clear_code=False)
    D.recompute_obligation_counters(res)
    res["status"] = "COMPLETED"
    touch(res)


def _terminate(res, cycle):
    end = d(res.get("session_end_date"))
    start = d(res.get("session_start_date"))
    if end is None or start is None or store.today() > end:
        raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                       "a residency that has run its full course is completed, "
                       "not terminated")
    settlement = store.today()
    # link 1 -- the weeks actually served, rounded up
    res["actual_weeks_in_residence"] = calc.weeks_served(start, settlement)
    # link 2 -- the unearned schedule is voided
    D.void_scheduled_disbursements(res)
    # link 3 -- the award is re-priced on the settled basis
    res["stipend_basis"] = "FINAL_SETTLED"
    res["stipend_total_cents"] = calc.final_settled_award(
        int(res["stipend_weekly_rate_cents"]), start, settlement)
    # alongside -- the facilities are freed
    D.release_studio_assignments(res, "RESIDENCY_TERMINATED", clear_code=True)
    D.release_housing_assignments(res, "RESIDENCY_TERMINATED", clear_code=True)
    D.recompute_residency_stipend_ledgers(res)
    res["status"] = "TERMINATED"
    touch(res)
    # link 4 -- the cycle ledger is recomputed from the surviving commitments
    touch(cycle)


def _withdraw(res, cycle):
    D.void_scheduled_disbursements(res)
    D.release_studio_assignments(res, "RESIDENCY_WITHDRAWN", clear_code=True)
    D.release_housing_assignments(res, "RESIDENCY_WITHDRAWN", clear_code=True)
    _waive_pending_obligations(res, "RESIDENCY_WITHDRAWN")
    D.deny_visa_case_on_withdrawal(res["id"])
    D.recompute_obligation_counters(res)
    D.recompute_residency_stipend_ledgers(res)
    res["status"] = "WITHDRAWN"
    touch(res)
    touch(cycle)


@bp.route("/residencies/<residency_id>/lifecycle", methods=["POST"])
def residency_lifecycle(residency_id):
    actor = authorize(["ProgramAdmin", "Applicant"])
    res = path_row(store.residencies, residency_id, "ERR_RESIDENCY_NOT_FOUND")
    b = body()
    action = req_enum(b, "action", LIFECYCLE_ACTIONS)
    opt_str(b, "reason", min_len=1, max_len=1000)

    # group 1 (deferred) -- an acting artist may only withdraw, and only their own
    if actor.role == "Applicant":
        if action != "WITHDRAW":
            raise ApiError("ERR_UNAUTHORIZED",
                           "an artist may only withdraw from their own residency")
        require_owner(actor, res["applicant_id"])

    origin, _target = LIFECYCLE_EDGE[action]
    if res["status"] != origin:
        if action == "WITHDRAW":
            raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                           "withdrawal requires the residency to still be SCHEDULED")
        raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                       "%s is not an edge from %s" % (action, res["status"]))

    cycle = store.cycles[res["cycle_id"]]
    if action == "CHECK_IN":
        _check_in(res)
    elif action == "COMPLETE":
        _complete(res)
    elif action == "TERMINATE":
        _terminate(res, cycle)
    else:
        _withdraw(res, cycle)
    return object_response(D.ser_residency(res))


# ---------------------------------------------------------------- compliance axis
@bp.route("/residencies/<residency_id>/compliance", methods=["POST"])
def residency_compliance(residency_id):
    authorize(["FacilitiesManager", "ProgramAdmin"])
    res = path_row(store.residencies, residency_id, "ERR_RESIDENCY_NOT_FOUND")
    b = body()
    action = req_enum(b, "action", ["SUSPEND", "REINSTATE"])
    opt_str(b, "reason", min_len=1, max_len=1000)

    if res["status"] not in ("SCHEDULED", "IN_RESIDENCE"):
        raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                       "a residency in %s admits no compliance action" % res["status"])
    current = res["compliance_status"]
    if action == "SUSPEND":
        if current == "SUSPENDED":
            raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                           "SUSPENDED is not an edge from SUSPENDED")
        # only a cleared resident holds a studio to lose
        if current == "CLEARED":
            D.release_studio_assignments(res, "COMPLIANCE_SUSPENDED", clear_code=True)
        res["compliance_status"] = "SUSPENDED"
    else:
        if current != "SUSPENDED":
            raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                           "CLEARED is not an edge from %s" % current)
        if not _trainings_covered(res):
            raise ApiError("ERR_TRAINING_NOT_COMPLETE",
                           "every required training must be recorded before reinstatement")
        # reinstatement always lands in CLEARED and never restores the studio
        res["compliance_status"] = "CLEARED"
    touch(res)
    return object_response(D.ser_residency(res))


# ---------------------------------------------------------------- safety clearance
@bp.route("/residencies/<residency_id>/trainings", methods=["POST"])
def record_training(residency_id):
    authorize(["FacilitiesManager", "ProgramAdmin"])
    res = path_row(store.residencies, residency_id, "ERR_RESIDENCY_NOT_FOUND")
    b = body()
    training_type = req_str(b, "training_type", min_len=1, max_len=64)

    if res["status"] in RESIDENCY_TERMINAL:
        raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                       "a residency in %s records no further training" % res["status"])
    if training_type not in res["required_training_types"]:
        raise ApiError("ERR_TRAINING_TYPE_NOT_REQUIRED",
                       "%s is not one of this residency's required trainings"
                       % training_type)

    done = set(res["completed_training_types"])
    done.add(training_type)
    res["completed_training_types"] = sorted(done)
    if res["compliance_status"] == "TRAINING_PENDING" and _trainings_covered(res):
        res["compliance_status"] = "CLEARED"
    touch(res)
    return object_response(D.ser_residency(res))


# ---------------------------------------------------------------- stipend schedule
@bp.route("/residencies/<residency_id>/stipend-schedule", methods=["POST"])
def generate_stipend_schedule(residency_id):
    actor = authorize(["FinanceOfficer"])
    res = path_row(store.residencies, residency_id, "ERR_RESIDENCY_NOT_FOUND")
    b = body()
    # group 3 -- shape first, then the OCC guard of group 4
    req_int(b, "expected_residency_version", minimum=0)
    override = opt_int(b, "weekly_rate_override_cents", minimum=0)
    occ(b, "expected_residency_version", res)

    if res["status"] != "SCHEDULED" or res.get("session_start_date") is None:
        raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                       "a stipend schedule requires a SCHEDULED residency with a session")

    cycle = store.cycles[res["cycle_id"]]
    rate = override if override is not None else int(res["stipend_weekly_rate_cents"])
    weeks = int(res["session_length_weeks"])
    new_total = calc.provisional_award(rate, weeks)
    old_total = int(res["stipend_total_cents"] or 0)
    _, uncommitted, _, _ = D.cycle_ledger(cycle)
    if uncommitted < new_total - old_total:
        raise ApiError("ERR_STIPEND_POOL_EXHAUSTED",
                       "the remaining stipend pool cannot cover this schedule")

    # regeneration voids the live schedule and leaves PAID / REVERSED history intact
    D.void_scheduled_disbursements(res)

    start = d(res["session_start_date"])
    end = d(res.get("session_end_date"))
    form = D.residency_tax_form_type(res)
    emitted = []
    for index, period_start, period_end, weeks_in_period, gross in \
            calc.period_plan(weeks, start, end, rate):
        emitted.append(create_row(store.disbursements, {
            "residency_id": res["id"],
            "period_index": index,
            "period_start_date": ds(period_start),
            "period_end_date": ds(period_end),
            "weeks_in_period": weeks_in_period,
            "gross_cents": gross,
            "withholding_cents": 0,
            "net_cents": 0,
            "withholding_rate": None,
            "cumulative_taxable_cents": None,
            "tax_form_type": form,
            "status": "SCHEDULED",
            "paid_on_date": None,
            "scheduled_by_user_id": actor.user_id,
            "paid_by_user_id": None,
        }))

    res["stipend_weekly_rate_cents"] = rate
    res["stipend_total_cents"] = new_total
    D.recompute_residency_stipend_ledgers(res)
    touch(res)
    touch(cycle)
    # A creation endpoint answers 201 with the rows it created, in the strictly
    # ascending period_index order they were emitted in.
    return created_rows_response([D.ser_disbursement(row) for row in emitted])


# ---------------------------------------------------------------- tax report
@bp.route("/residencies/<residency_id>/tax-report", methods=["GET"])
def residency_tax_report(residency_id):
    authorize(["FinanceOfficer", "ProgramAdmin"])
    res = path_row(store.residencies, residency_id, "ERR_RESIDENCY_NOT_FOUND")
    applicant = store.applicants.get(res["applicant_id"])
    form = D.residency_tax_form_type(res)
    rate = calc.withholding_rate(form, bool(applicant["treaty_country"]) if applicant else False)

    paid = [x for x in D.residency_disbursements(res["id"]) if x["status"] == "PAID"]
    annual_gross = sum(int(x["gross_cents"]) for x in paid)
    withheld = sum(int(x["withholding_cents"] or 0) for x in paid)
    annual_taxable, statutory = calc.statutory_liability(annual_gross, rate)
    data = {
        "tax_form_type": form,
        "withholding_rate": float(rate),
        "annual_gross_cents": annual_gross,
        "annual_taxable_cents": annual_taxable,
        "withheld_actual_cents": withheld,
        "statutory_liability_cents": int(statutory),
        "reconciliation_delta_cents": withheld - int(statutory),
        "paid_period_count": len(paid),
    }
    return object_response(data)
