"""The wage engine: the four referential apprentice/rate checks (ladder rungs
15-18) and the pinned four-step finalization arithmetic of PRD 3.6."""

from decimal import Decimal

import calc
import db
import derive
from errors import ApiError

ZERO = Decimal("0")


def worker_program(worker):
    if worker is None or worker.get("apprentice_program_id") is None:
        return None
    return db.apprentice_programs.get(worker["apprentice_program_id"])


# ---------------------------------------------------------------------------
# Rungs 15-18, evaluated rung by rung across every candidate line
# ---------------------------------------------------------------------------
def check_referential(project, candidates):
    """candidates is a list of (line_like, worker) pairs.

    line_like needs classification_code and reported_as_apprentice.
    """
    # Rung 15 -- apprentice program registration
    for line, worker in candidates:
        if not line["reported_as_apprentice"]:
            continue
        program = worker_program(worker)
        if program is None or program["registration_status"] != "REGISTERED":
            raise ApiError(
                "ERR_APPRENTICE_PROGRAM_NOT_REGISTERED",
                "The apprentice's program is missing or not REGISTERED.",
            )

    # Rung 16 -- apprentice trade alignment against the matched rate row
    for line, worker in candidates:
        if not line["reported_as_apprentice"]:
            continue
        rate = calc.match_wage_rate(project, line["classification_code"])
        if rate is None:
            continue
        program = worker_program(worker)
        if program["trade_code"] != rate["trade_code"]:
            raise ApiError(
                "ERR_APPRENTICE_TRADE_MISMATCH",
                "The apprentice program's trade_code differs from the matched wage rate's trade_code.",
            )

    # Rung 17 -- apprentice period within the published scale and the program
    for line, worker in candidates:
        if not line["reported_as_apprentice"]:
            continue
        program = worker_program(worker)
        period = worker.get("apprentice_period")
        rate = calc.match_wage_rate(project, line["classification_code"])
        if period is None:
            raise ApiError(
                "ERR_APPRENTICE_PERIOD_OUT_OF_SCALE",
                "The worker carries no apprentice_period.",
            )
        if period > program["period_count"]:
            raise ApiError(
                "ERR_APPRENTICE_PERIOD_OUT_OF_SCALE",
                "apprentice_period exceeds the program's period_count.",
            )
        if rate is not None and period > len(rate["apprentice_scale_pct"]):
            raise ApiError(
                "ERR_APPRENTICE_PERIOD_OUT_OF_SCALE",
                "apprentice_period exceeds the matched wage rate's apprentice scale.",
            )

    # Rung 18 -- wage rate coverage
    for line, worker in candidates:
        if calc.match_wage_rate(project, line["classification_code"]) is None:
            raise ApiError(
                "ERR_NO_WAGE_RATE_FOR_CLASSIFICATION",
                "No wage rate row for this classification, determination and zone.",
            )


# ---------------------------------------------------------------------------
# Finalization: the four pinned steps
# ---------------------------------------------------------------------------
def run_wage_engine(submission, project, assignment, lines):
    rates = {}
    workers = {}
    for line in lines:
        rates[line["id"]] = calc.match_wage_rate(project, line["classification_code"])
        workers[line["id"]] = db.workers.get(line["worker_id"])

    def trade_of(line):
        rate = rates[line["id"]]
        return rate["trade_code"] if rate is not None else None

    def program_of(line):
        return worker_program(workers[line["id"]])

    # Step one -- the apprentice ratio
    excess = calc.apprentice_ratio_compliance(lines, trade_of, program_of)

    # Step two -- the required prevailing rate
    for line in lines:
        rate = rates[line["id"]]
        required_base, required_fringe = calc.required_prevailing_rate(
            line, workers[line["id"]], rate
        )
        line["required_base_cents"] = required_base
        line["required_fringe_cents"] = required_fringe

    # Step three -- the creditable fringe
    for line in lines:
        plan = (
            db.fringe_plans.get(line["fringe_plan_id"])
            if line["fringe_plan_id"] is not None
            else None
        )
        line["creditable_fringe_cents"] = calc.creditable_fringe_per_line(
            line, plan, line["required_fringe_cents"]
        )

    # Step four -- the underpayment
    straight_total, make_whole_total = calc.underpayment_restitution(
        lines, lambda line: rates[line["id"]]
    )

    submission["excess_apprentice_hours"] = excess
    submission["total_hours_reported"] = sum((calc.line_hours(l) for l in lines), ZERO)
    submission["straight_time_underpayment_cents"] = straight_total
    submission["make_whole_underpayment_cents"] = make_whole_total

    portal = db.reporting_portals.get(project["reporting_portal_id"])
    if portal is not None:
        submission["filing_due_at"] = calc.portal_filing_deadline(submission, portal)

    return excess, make_whole_total


def recompute_after_supersede(submission, project):
    """Cascade hop 3 of the WageDetermination supersede: redo the wage
    arithmetic on a DRAFT / PENDING_CERTIFICATION submission's lines against
    the successor's rate rows. reclassified_journey_hours is left as filed."""
    lines = derive.lines_of_submission(submission["id"])
    priced = []
    rates = {}
    for line in lines:
        rate = calc.match_wage_rate(project, line["classification_code"])
        if rate is None:
            continue
        rates[line["id"]] = rate
        priced.append(line)

    for line in priced:
        rate = rates[line["id"]]
        worker = db.workers.get(line["worker_id"])
        program = worker_program(worker)
        if line["reported_as_apprentice"] and (
            program is None
            or worker.get("apprentice_period") is None
            or worker["apprentice_period"] > len(rate["apprentice_scale_pct"])
        ):
            continue
        required_base, required_fringe = calc.required_prevailing_rate(line, worker, rate)
        line["required_base_cents"] = required_base
        line["required_fringe_cents"] = required_fringe
        plan = (
            db.fringe_plans.get(line["fringe_plan_id"])
            if line["fringe_plan_id"] is not None
            else None
        )
        line["creditable_fringe_cents"] = calc.creditable_fringe_per_line(
            line, plan, required_fringe
        )

    straight_total, make_whole_total = calc.underpayment_restitution(
        priced, lambda line: rates[line["id"]]
    )
    submission["straight_time_underpayment_cents"] = straight_total
    submission["make_whole_underpayment_cents"] = make_whole_total
    db.touch(submission)
