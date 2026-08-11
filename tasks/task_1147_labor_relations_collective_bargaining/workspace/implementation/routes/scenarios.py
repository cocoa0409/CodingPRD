"""CostingScenario endpoints: create, compute/review/rework, OCC-guarded lock."""

from flask import Blueprint, request

import calc
from db import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SOD_VIOLATION,
    ERR_STALE_AGREEMENT_VERSION,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, page, parse_pagination,
    req_enum, req_id_list, req_int, req_string, serialize, sort_items, touch,
)
from response import success_list, success_object

bp = Blueprint("scenarios", __name__)

SCENARIO_STATUSES = ("DRAFT", "COMPUTED", "REVIEWED", "LOCKED", "SUPERSEDED")


@bp.post("/labor-relations/costing-scenarios")
def create_scenario():
    authenticate(["Negotiator"])
    body = get_body()
    agreement_id = req_string(body, "agreement_id")
    name = req_string(body, "name")
    scenario_mode = req_enum(body, "scenario_mode", ("PROVISIONAL", "FINAL"))
    term_years = req_int(body, "term_years")
    if term_years < 1 or term_years > 5:
        raise_err(ERR_INVALID_REQUEST, "term_years must be within [1, 5]")
    proposal_ids = req_id_list(body, "proposal_ids")

    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    if agreement["status"] in ("ARCHIVED", "REPLACED"):
        raise_err(ERR_INVALID_STATE, "Cannot create a costing scenario on a %s agreement" % agreement["status"])

    scenario = new_entity()
    scenario.update({
        "agreement_id": agreement_id,
        "name": name,
        "scenario_mode": scenario_mode,
        "term_years": term_years,
        "proposal_ids": proposal_ids,
        "status": "DRAFT",
        "computed_by_user_id": None,
        "reviewed_by_user_id": None,
        "locked_by_user_id": None,
        "year_breakdown_cents": None,
        "subtotal_cents": None,
        "reserve_cents": None,
        "total_cost_cents": None,
    })
    db.scenarios[scenario["id"]] = scenario
    return success_object(serialize(scenario), status=201)


@bp.get("/labor-relations/costing-scenarios")
def list_scenarios():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    scenario_mode = request.args.get("scenario_mode")
    items = list(db.scenarios.values())
    if agreement_id is not None:
        items = [s for s in items if s["agreement_id"] == agreement_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if scenario_mode is not None:
        items = [s for s in items if s["scenario_mode"] == scenario_mode]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(s) for s in slice_], limit, offset, total)


@bp.get("/labor-relations/costing-scenarios/<scenario_id>")
def get_scenario(scenario_id):
    authenticate(ALL_ROLES)
    scenario = lookup(db.scenarios, scenario_id, "CostingScenario")
    return success_object(serialize(scenario))


@bp.post("/labor-relations/costing-scenarios/<scenario_id>/state")
def transition_scenario(scenario_id):
    user_id, role = authenticate(["Negotiator"])
    scenario = lookup(db.scenarios, scenario_id, "CostingScenario")
    body = get_body()
    to_status = req_string(body, "to_status")
    if to_status not in SCENARIO_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Unknown scenario status: %s" % to_status)
    if to_status in ("LOCKED", "SUPERSEDED"):
        raise_err(ERR_INVALID_STATE, "Cannot transition a scenario to %s via this endpoint" % to_status)

    if to_status == "COMPUTED":
        if scenario["status"] not in ("DRAFT", "REVIEWED"):
            raise_err(ERR_INVALID_STATE, "Only a DRAFT or REVIEWED scenario can be computed")
        agreement = lookup(db.agreements, scenario["agreement_id"], "CollectiveAgreement")
        proposals = []
        for pid in scenario["proposal_ids"]:
            proposal = db.proposals.get(pid)
            if (proposal is None
                    or proposal["agreement_id"] != scenario["agreement_id"]
                    or proposal["proposal_type"] != "ECONOMIC"
                    or proposal["status"] not in ("ON_TABLE", "ACCEPTED")):
                raise_err(ERR_INVALID_REQUEST,
                          "Every proposal_id must resolve to an ECONOMIC proposal of this agreement in ON_TABLE or ACCEPTED status")
            proposals.append(proposal)
        year_breakdown, subtotal, reserve, total, per_proposal_y1 = calc.compute_scenario(
            scenario, agreement, proposals)
        for pid, line_y1 in per_proposal_y1.items():
            db.proposals[pid]["estimated_year1_cost_cents"] = line_y1
        scenario["year_breakdown_cents"] = year_breakdown
        scenario["subtotal_cents"] = subtotal
        scenario["reserve_cents"] = reserve
        scenario["total_cost_cents"] = total
        scenario["computed_by_user_id"] = user_id
        scenario["status"] = "COMPUTED"
        touch(scenario)

    elif to_status == "REVIEWED":
        if scenario["status"] != "COMPUTED":
            raise_err(ERR_INVALID_STATE, "Only a COMPUTED scenario can be reviewed")
        if user_id == scenario["computed_by_user_id"]:
            raise_err(ERR_SOD_VIOLATION, "Reviewer must differ from computed_by_user_id")
        scenario["reviewed_by_user_id"] = user_id
        scenario["status"] = "REVIEWED"
        touch(scenario)

    else:  # DRAFT (rework loop)
        if scenario["status"] != "REVIEWED":
            raise_err(ERR_INVALID_STATE, "Only a REVIEWED scenario can return to DRAFT")
        scenario["status"] = "DRAFT"
        touch(scenario)

    return success_object(serialize(scenario))


@bp.post("/labor-relations/costing-scenarios/<scenario_id>/lock")
def lock_scenario(scenario_id):
    user_id, role = authenticate(["ChiefNegotiator"])
    scenario = lookup(db.scenarios, scenario_id, "CostingScenario")
    body = get_body()
    expected_version = req_int(body, "expected_agreement_version")

    if scenario["status"] != "REVIEWED":
        raise_err(ERR_INVALID_STATE, "Only a REVIEWED scenario can be locked")
    agreement = lookup(db.agreements, scenario["agreement_id"], "CollectiveAgreement")
    if expected_version != agreement["version"]:
        raise_err(ERR_STALE_AGREEMENT_VERSION, "expected_agreement_version does not match the agreement version")
    if user_id == scenario["computed_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION, "Locker must differ from computed_by_user_id")

    # Lock-supersede: any other LOCKED scenario of this agreement becomes SUPERSEDED
    for other in db.scenarios.values():
        if other["id"] != scenario["id"] and other["agreement_id"] == scenario["agreement_id"] and other["status"] == "LOCKED":
            other["status"] = "SUPERSEDED"
            touch(other)

    scenario["locked_by_user_id"] = user_id
    scenario["status"] = "LOCKED"
    touch(scenario)
    touch(agreement)
    return success_object(serialize(scenario))
