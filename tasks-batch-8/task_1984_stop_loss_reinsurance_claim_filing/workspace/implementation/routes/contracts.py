"""Stop-loss contract endpoints (PRD §3.1-3.2): create, activate, renew, reads."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import READ_ALL, get_one, list_response
from services.accumulation import applicable_specific_deductible
from services.core import new_record, public, touch
from util import CLOCK, norm_dt, parse_dt
from validate import (
    get_body, req_str, req_int, opt_int, req_enum, req_number, req_datetime,
    require_path_resource, require_ref,
)

bp = Blueprint("contracts", __name__)

CONTRACT_BASES = {"POLICY_YEAR", "PAID"}


def _read_contract_terms(body):
    """Shared shape validation for create/renew payloads (ERR_INVALID_REQUEST)."""
    terms = {
        "policy_year_start": norm_dt(req_datetime(body, "policy_year_start")),
        "policy_year_end": norm_dt(req_datetime(body, "policy_year_end")),
        "contract_basis": req_enum(body, "contract_basis", CONTRACT_BASES),
        "specific_deductible_cents": req_int(body, "specific_deductible_cents"),
        "aggregate_deductible_cents": req_int(body, "aggregate_deductible_cents"),
        "aggregating_specific_deductible_cents": opt_int(
            body, "aggregating_specific_deductible_cents", None),
        "filing_deadline_days": req_int(body, "filing_deadline_days", minimum=1),
        "notice_threshold_pct": req_number(body, "notice_threshold_pct"),
        "run_in_days": req_int(body, "run_in_days", minimum=0),
        "run_out_days": req_int(body, "run_out_days", minimum=0),
    }
    if not (0 < terms["notice_threshold_pct"] <= 1):
        raise_error(ERR_INVALID_REQUEST, "notice_threshold_pct must be > 0 and <= 1")
    if parse_dt(terms["policy_year_end"]) <= parse_dt(terms["policy_year_start"]):
        raise_error(ERR_INVALID_REQUEST, "policy_year_end must be after policy_year_start")
    return terms


@bp.post("/stop-loss/contracts")
def create_contract():
    authorized(["PlanAdministrator"])
    body = get_body()
    plan_id = req_str(body, "plan_id")
    terms = _read_contract_terms(body)
    require_ref("plans", plan_id, "plan_id")
    rec = new_record("contracts", {
        "plan_id": plan_id,
        **terms,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/stop-loss/contracts/<rid>")
def get_contract(rid):
    return get_one("contracts", rid, READ_ALL)


@bp.get("/stop-loss/contracts")
def list_contracts():
    return list_response("contracts", READ_ALL,
                         {"plan_id": request.args.get("plan_id")})


@bp.post("/stop-loss/contracts/<rid>/activate")
def activate_contract(rid):
    authorized(["PlanAdministrator"])
    get_body()
    contract = require_path_resource("contracts", rid)

    # Every failed activation precondition surfaces as ERR_INVALID_STATE (PRD §3.2).
    if contract["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"contract in {contract['status']} cannot be activated")
    now = CLOCK.now()
    if not (parse_dt(contract["policy_year_start"]) <= now
            < parse_dt(contract["policy_year_end"])):
        raise_error(ERR_INVALID_STATE,
                    "current logical instant is outside the contract's policy year")
    if contract["specific_deductible_cents"] < 0 or contract["aggregate_deductible_cents"] < 0:
        raise_error(ERR_INVALID_STATE, "deductibles must be zero or greater")
    agg_spec = contract["aggregating_specific_deductible_cents"]
    if agg_spec is not None and agg_spec < contract["specific_deductible_cents"]:
        raise_error(ERR_INVALID_STATE,
                    "aggregating_specific_deductible_cents must be at least the "
                    "specific deductible")
    # Sibling contracts on a different coverage basis legitimately coexist; the
    # exclusivity invariant is per coverage basis.
    for other in db["contracts"].values():
        if (other["id"] != contract["id"] and other["plan_id"] == contract["plan_id"]
                and other["status"] == "IN_FORCE"
                and other["contract_basis"] == contract["contract_basis"]):
            raise_error(ERR_INVALID_STATE,
                        "another contract for this plan and basis is already IN_FORCE")

    # Materialize the ledgers (PRD §2.6): one AGGREGATE row, one SPECIFIC row
    # per ACTIVE member of the plan.
    new_record("accumulations", {
        "contract_id": contract["id"],
        "member_id": None,
        "scope": "AGGREGATE",
        "accumulated_cents": 0,
        "excess_cents": 0,
        "applicable_deductible_cents": contract["aggregate_deductible_cents"],
        "notice_triggered": False,
    })
    for member in db["members"].values():
        if member["plan_id"] == contract["plan_id"] and member["status"] == "ACTIVE":
            new_record("accumulations", {
                "contract_id": contract["id"],
                "member_id": member["id"],
                "scope": "SPECIFIC",
                "accumulated_cents": 0,
                "excess_cents": 0,
                "applicable_deductible_cents": applicable_specific_deductible(
                    contract, member["id"]),
                "notice_triggered": False,
            })
    touch(contract)
    contract["status"] = "IN_FORCE"
    return success_object(public(contract))


@bp.post("/stop-loss/contracts/<rid>/renew")
def renew_contract(rid):
    authorized(["PlanAdministrator"])
    body = get_body()
    new_start = req_datetime(body, "new_policy_year_start")
    new_end = req_datetime(body, "new_policy_year_end")
    specific = req_int(body, "specific_deductible_cents")
    aggregate = req_int(body, "aggregate_deductible_cents")
    agg_spec = opt_int(body, "aggregating_specific_deductible_cents", None)
    deadline = req_int(body, "filing_deadline_days", minimum=1)
    threshold = req_number(body, "notice_threshold_pct")
    run_in = req_int(body, "run_in_days", minimum=0)
    run_out = req_int(body, "run_out_days", minimum=0)
    if not (0 < threshold <= 1):
        raise_error(ERR_INVALID_REQUEST, "notice_threshold_pct must be > 0 and <= 1")
    if parse_dt(new_end) <= parse_dt(new_start):
        raise_error(ERR_INVALID_REQUEST,
                    "new_policy_year_end must be after new_policy_year_start")

    contract = require_path_resource("contracts", rid)
    if contract["status"] != "EXPIRED":
        raise_error(ERR_INVALID_STATE,
                    f"only an EXPIRED contract may be renewed (current: {contract['status']})")
    # Continuity is mandatory: the new policy year begins exactly where the old
    # one ended (transition precondition — violation is ERR_INVALID_STATE).
    if parse_dt(new_start) != parse_dt(contract["policy_year_end"]):
        raise_error(ERR_INVALID_STATE,
                    "new_policy_year_start must equal the expiring contract's "
                    "policy_year_end")

    successor = new_record("contracts", {
        "plan_id": contract["plan_id"],
        "policy_year_start": norm_dt(new_start),
        "policy_year_end": norm_dt(new_end),
        "contract_basis": contract["contract_basis"],
        "specific_deductible_cents": specific,
        "aggregate_deductible_cents": aggregate,
        "aggregating_specific_deductible_cents": agg_spec,
        "filing_deadline_days": deadline,
        "notice_threshold_pct": threshold,
        "run_in_days": run_in,
        "run_out_days": run_out,
        "status": "DRAFT",
    })
    touch(contract)
    contract["status"] = "RENEWED"
    return success_object(public(successor), status=201)


def expire_contracts_up_to(now):
    """Logical-clock side effect: IN_FORCE -> EXPIRED when the clock reaches
    policy_year_end (PRD §2.10). Fires as part of the clock-set operation."""
    for contract in db["contracts"].values():
        if contract["status"] == "IN_FORCE" and parse_dt(contract["policy_year_end"]) <= now:
            touch(contract)
            contract["status"] = "EXPIRED"
