"""The project demand ledger, the posture gate and the derived counters.

PRD 2.5 (posture), 2.11 (ledger), 3.8 (fee schedule), 3.9 (thresholds).
"""
from decimal import Decimal

import db
from utils import _dec, rhu

LEDGER_ELIGIBLE_STATES = ("CONVERGED", "QC_PASSED", "SEALED")
FROZEN_PROJECT_STATUSES = ("CORRECTIVE_ACTION", "CLOSED_OUT")
ACCEPTANCE_FLOW_FACTOR = Decimal("0.95")

# review fee by cycle number; the fourth cycle is the last the authority accepts
REVIEW_FEE_BY_CYCLE = {1: 0.00, 2: 0.00, 3: 250.00, 4: 500.00}
RESUBMITTAL_CYCLE_LIMIT = 4


def recompute_posture(project):
    """design_posture is derived, never supplied (PRD 2.5)."""
    if project.get("status") in FROZEN_PROJECT_STATUSES:
        posture = "FROZEN"
    elif (project.get("open_major_comment_count") or 0) > 0:
        posture = "GATED"
    else:
        posture = "OPEN"
    project["design_posture"] = posture
    return posture


def calculations_of(project_id):
    return [c for c in db.calculations.values() if c["project_id"] == project_id]


def aux_systems_of(project_id):
    return [a for a in db.aux_systems.values() if a["project_id"] == project_id]


def recompute_ledger(project):
    """The three ledger steps: eligible set, governing selection, auxiliary roll-up."""
    eligible = [
        c
        for c in calculations_of(project["id"])
        if c["state"] in LEDGER_ELIGIBLE_STATES
    ]
    if eligible:
        eligible.sort(
            key=lambda c: (
                -_dec(c["hazard_total_demand_gpm"]),
                c["created_at"],
                c.get("_seq", 0),
            )
        )
        winner = eligible[0]
        project["governing_hydraulic_calculation_id"] = winner["id"]
        project["governing_demand_gpm"] = rhu(winner["hazard_total_demand_gpm"], 1)
    else:
        project["governing_hydraulic_calculation_id"] = None
        project["governing_demand_gpm"] = 0.0

    auxiliary = Decimal("0")
    for system in aux_systems_of(project["id"]):
        if system["status"] != "WITHDRAWN":
            auxiliary = auxiliary + _dec(system["demand_gpm"])
    project["auxiliary_demand_gpm"] = rhu(auxiliary, 1)
    project["total_system_demand_gpm"] = rhu(
        _dec(project["governing_demand_gpm"]) + _dec(project["auxiliary_demand_gpm"]), 1
    )


def governing_calculation(project):
    calc_id = project.get("governing_hydraulic_calculation_id")
    if calc_id is None:
        return None
    return db.calculations.get(calc_id)


def acceptance_thresholds(project):
    """Frozen on the acceptance test row at creation and never re-derived."""
    governing = governing_calculation(project)
    return {
        "required_flow_gpm": rhu(
            _dec(project["total_system_demand_gpm"]) * ACCEPTANCE_FLOW_FACTOR, 1
        ),
        "required_residual_psi": float(governing["required_psi_at_base_of_riser"]),
    }


def review_fee_for_cycle(cycle_number):
    return REVIEW_FEE_BY_CYCLE.get(cycle_number, 500.00)


def accrue_review_fee(project, fee_usd):
    project["review_fee_balance_usd"] = rhu(
        _dec(project["review_fee_balance_usd"]) + _dec(fee_usd), 2
    )


OUTSTANDING_COMMENT_STATES = ("OPEN", "RESPONDED")


def comments_of(submittal_id):
    return [c for c in db.review_comments.values() if c["submittal_id"] == submittal_id]


def submittals_of(project_id):
    return [s for s in db.submittals.values() if s["project_id"] == project_id]


def recount_submittal_comments(submittal):
    """open_comment_count counts OPEN or RESPONDED; major_comment_count the MAJOR ones."""
    outstanding = [
        c for c in comments_of(submittal["id"]) if c["state"] in OUTSTANDING_COMMENT_STATES
    ]
    submittal["open_comment_count"] = len(outstanding)
    submittal["major_comment_count"] = len(
        [c for c in outstanding if c["severity"] == "MAJOR"]
    )


def recount_project_major_comments(project):
    """MAJOR comments in OPEN or RESPONDED across every package of the project."""
    total = 0
    for submittal in submittals_of(project["id"]):
        for comment in comments_of(submittal["id"]):
            if (
                comment["severity"] == "MAJOR"
                and comment["state"] in OUTSTANDING_COMMENT_STATES
            ):
                total += 1
    project["open_major_comment_count"] = total
    return total
