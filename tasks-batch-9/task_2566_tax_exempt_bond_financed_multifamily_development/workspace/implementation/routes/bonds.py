"""Bond sizing, closing, operating months, conversion and redemption (PRD 3.5, 3.7)."""

from flask import Blueprint

import calc
import domain
import serialize
import validation as v
from auth import guard, own_project
from envelope import object_response
from errors import fail
from store import db, new_row, now_clock, now_clock_iso, parse_iso, touch

bp = Blueprint("bonds", __name__)


def _require_live_award(allocation, closing_dt=None):
    """Ladder rule 82 -- ERR_ALLOCATION_EXPIRED (the deadline is exclusive)."""
    if allocation.get("status") != "AWARDED":
        fail("ERR_ALLOCATION_EXPIRED",
             "The referenced cap allocation is not a live award.")
    expiry = parse_iso(allocation.get("expiry_date"))
    if expiry is None or now_clock() >= expiry:
        fail("ERR_ALLOCATION_EXPIRED", "The cap award has lapsed.")
    if closing_dt is not None and closing_dt > expiry:
        fail("ERR_ALLOCATION_EXPIRED", "The closing date falls after the award expiry.")


@bp.post("/bond-issues")
def create_bond_issue():
    caller = guard("POST /bond-issues")
    body = v.body()
    own_project(caller, domain.soft_get(db.projects, body.get("project_id")))

    project_id = v.req_id(body, "project_id")
    allocation_id = v.req_id(body, "volume_cap_allocation_id")
    eligible_cost_cents = v.req_int(body, "eligible_cost_cents", minimum=1)
    capitalized_interest_cents = v.req_int(body, "capitalized_interest_cents", minimum=0)
    bond_yield_bps = v.req_int(body, "bond_yield_bps", minimum=1)
    investment_yield_bps = v.req_int(body, "investment_yield_bps", minimum=0)

    project = domain.get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(caller, project)
    allocation = domain.get_or_404(db.allocations, allocation_id, "ERR_ALLOCATION_NOT_FOUND")
    domain.require_developer_active(project)
    _require_live_award(allocation)

    sizing = calc.bond_sizing(eligible_cost_cents, capitalized_interest_cents)
    if sizing["par_amount_cents"] > (allocation.get("awarded_amount_cents") or 0):
        fail("ERR_PAR_EXCEEDS_CAP_AWARD",
             "The solved par amount exceeds the awarded volume cap.")

    row = new_row(db.bond_issues, {
        "project_id": project_id,
        "volume_cap_allocation_id": allocation_id,
        "eligible_cost_cents": eligible_cost_cents,
        "capitalized_interest_cents": capitalized_interest_cents,
        "bond_yield_bps": bond_yield_bps,
        "investment_yield_bps": investment_yield_bps,
        "issuance_allowance_cents": sizing["issuance_allowance_cents"],
        "par_amount_cents": sizing["par_amount_cents"],
        "negative_arbitrage_allowance_cents": sizing["negative_arbitrage_allowance_cents"],
        "status": "DRAFT",
        "closing_date": None,
        "negative_arbitrage_cents": 0,
        "operating_months": [],
        "dscr_bps": None,
        "dscr_basis": None,
        "min_occupancy_bps": None,
        "conversion_date": None,
        "redemption_date": None,
    })
    return object_response(serialize.bond_issue(row), 201)


@bp.post("/bond-issues/<row_id>/issue")
def issue_bonds(row_id):
    guard("POST /bond-issues/{id}/issue")
    body = v.body()
    closing_raw, closing_dt = v.req_dt(body, "closing_date")

    issue = domain.get_or_404(db.bond_issues, row_id, "ERR_BOND_ISSUE_NOT_FOUND")
    project = domain.project_of_row(issue)
    domain.require_developer_active(project)

    if issue.get("status") != "DRAFT":
        fail("ERR_BOND_ISSUE_STATE_INVALID",
             "A bond issue in %s cannot be closed." % issue.get("status"))

    allocation = domain.soft_get(db.allocations, issue.get("volume_cap_allocation_id"))
    if allocation is None:
        fail("ERR_ALLOCATION_NOT_FOUND")
    _require_live_award(allocation, closing_dt)

    agreement = domain.recorded_agreement(issue.get("project_id"))
    if agreement is None:
        fail("ERR_REG_AGREEMENT_NOT_RECORDED",
             "The development has no RECORDED land-use restriction agreement.")

    if (issue.get("par_amount_cents") or 0) > (allocation.get("awarded_amount_cents") or 0):
        fail("ERR_PAR_EXCEEDS_CAP_AWARD",
             "The par amount exceeds the awarded volume cap.")

    ratio = calc.fifty_percent_ratio(issue.get("par_amount_cents") or 0,
                                     project.get("aggregate_basis_cents") or 0)
    if not calc.fifty_percent_passes(ratio):
        fail("ERR_FIFTY_PERCENT_TEST_FAILED",
             "The provisional fifty-percent aggregate basis test fails at %d bps." % ratio)

    if not calc.set_aside_compliance_ratio(project)["set_aside_satisfied"]:
        fail("ERR_SET_ASIDE_NOT_SATISFIED",
             "The development no longer satisfies its set-aside election.")

    issue["status"] = "ISSUED"
    issue["closing_date"] = closing_raw
    touch(issue)

    project["provisional_fifty_percent_ratio_bps"] = ratio
    project["automatic_credit_triggered"] = calc.fifty_percent_passes(ratio)
    if project.get("development_status") == "PLANNING":
        project["development_status"] = "FINANCED"
    touch(project)

    allocation["status"] = "COMMITTED"
    touch(allocation)
    domain.rederive_pool(domain.soft_get(db.cap_pools, allocation.get("cap_pool_id")))

    return object_response(serialize.bond_issue(issue))


@bp.post("/bond-issues/<row_id>/operating-months")
def record_operating_month(row_id):
    caller = guard("POST /bond-issues/{id}/operating-months")
    issue = domain.soft_get(db.bond_issues, row_id)
    own_project(caller, domain.project_of_row(issue))

    body = v.body()
    month_index = v.req_int(body, "month_index", minimum=1)
    noi_cents = v.req_int(body, "noi_cents", minimum=0)
    debt_service_cents = v.req_int(body, "debt_service_cents", minimum=0)
    occupied_units = v.req_int(body, "occupied_units", minimum=0)

    issue = domain.get_or_404(db.bond_issues, row_id, "ERR_BOND_ISSUE_NOT_FOUND")
    project = domain.project_of_row(issue)
    own_project(caller, project)

    if issue.get("status") != "ISSUED":
        fail("ERR_BOND_ISSUE_STATE_INVALID",
             "Operating months may only be recorded on an ISSUED bond.")

    months = issue.get("operating_months") or []
    if month_index != len(months) + 1:
        fail("ERR_DUPLICATE_OPERATING_MONTH",
             "month_index must be exactly %d." % (len(months) + 1))

    was_empty = not months
    months.append({
        "month_index": month_index,
        "noi_cents": noi_cents,
        "debt_service_cents": debt_service_cents,
        "occupied_units": occupied_units,
    })
    issue["operating_months"] = months
    touch(issue)

    if was_empty and project is not None:
        if project.get("development_status") == "UNDER_CONSTRUCTION":
            project["development_status"] = "PLACED_IN_SERVICE"
            project["placed_in_service_date"] = now_clock_iso()
            touch(project)

    return object_response(serialize.bond_issue(issue))


@bp.post("/bond-issues/<row_id>/convert")
def convert_bonds(row_id):
    guard("POST /bond-issues/{id}/convert")
    body = v.body()
    dscr_basis = v.req_enum(body, "dscr_basis", ("T3", "T12"))
    conversion_raw, _conversion_dt = v.req_dt(body, "conversion_date")

    issue = domain.get_or_404(db.bond_issues, row_id, "ERR_BOND_ISSUE_NOT_FOUND")
    if issue.get("status") != "ISSUED":
        fail("ERR_BOND_ISSUE_STATE_INVALID",
             "A bond issue in %s cannot be converted." % issue.get("status"))

    project = domain.project_of_row(issue)
    result = calc.debt_service_coverage(issue, project or {}, dscr_basis)
    if result is None:
        fail("ERR_INSUFFICIENT_OPERATING_HISTORY",
             "Not enough recorded operating months for a %s test." % dscr_basis)
    if result["dscr_bps"] < calc.MIN_DSCR_BPS:
        fail("ERR_DSCR_BELOW_MINIMUM",
             "Coverage of %d bps is below the %d bps minimum."
             % (result["dscr_bps"], calc.MIN_DSCR_BPS))
    if result["min_occupancy_bps"] < calc.STABILIZED_OCCUPANCY_BPS:
        fail("ERR_OCCUPANCY_BELOW_STABILIZATION",
             "Weakest-month occupancy of %d bps is below the %d bps floor."
             % (result["min_occupancy_bps"], calc.STABILIZED_OCCUPANCY_BPS))

    issue["status"] = "CONVERTED"
    issue["conversion_date"] = conversion_raw
    issue["dscr_basis"] = dscr_basis
    issue["dscr_bps"] = result["dscr_bps"]
    issue["min_occupancy_bps"] = result["min_occupancy_bps"]
    touch(issue)

    if project is not None and project.get("development_status") == "PLACED_IN_SERVICE":
        domain.stabilize_project(project, conversion_raw)

    return object_response(serialize.bond_issue(issue))


@bp.post("/bond-issues/<row_id>/mandatory-redeem")
def redeem_bonds(row_id):
    guard("POST /bond-issues/{id}/mandatory-redeem")
    body = v.body()
    redemption_raw, _redemption_dt = v.req_dt(body, "redemption_date")
    reason = v.req_str(body, "reason", allow_empty=False)

    issue = domain.get_or_404(db.bond_issues, row_id, "ERR_BOND_ISSUE_NOT_FOUND")
    if issue.get("status") != "ISSUED":
        fail("ERR_BOND_ISSUE_STATE_INVALID",
             "Only an ISSUED bond may be mandatorily redeemed.")

    issue["status"] = "MANDATORY_REDEEMED"
    issue["redemption_date"] = redemption_raw
    touch(issue)

    for draw in calc.issue_draws(issue["id"]):
        if draw.get("status") in ("SUBMITTED", "APPROVED"):
            draw["status"] = "REJECTED"
            draw["rejection_reason"] = "bond issue redeemed"
            touch(draw)

    project = domain.project_of_row(issue)
    if project is not None:
        if project.get("development_status") in ("FINANCED", "UNDER_CONSTRUCTION",
                                                 "PLACED_IN_SERVICE"):
            project["development_status"] = "WITHDRAWN"
        project["automatic_credit_triggered"] = False
        project["provisional_fifty_percent_ratio_bps"] = None
        touch(project)

    allocation = domain.soft_get(db.allocations, issue.get("volume_cap_allocation_id"))
    if allocation is not None and allocation.get("status") == "COMMITTED":
        allocation["status"] = "RELEASED"
        touch(allocation)
        pool = domain.soft_get(db.cap_pools, allocation.get("cap_pool_id"))
        if pool is not None:
            domain.rederive_pool(pool)
            domain.reinstate_deferred(pool)

    return object_response(serialize.bond_issue(issue))
