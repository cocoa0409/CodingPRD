"""Service contracts: draft/activate (OCC)/suspend/reinstate/terminate/expire."""

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import SLA_BASE_HOURS
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    conflict,
    invalid_request,
    invalid_state,
    not_found,
    ERR_CONTRACT_NOT_EXPIRED,
    ERR_FACILITY_NOT_ACTIVE,
    ERR_STALE_VERSION,
)
import store
from store import new_resource, touch
from util import add_months, body_or_empty, parse_pagination, public, req_date, req_int, req_str, sort_and_page

bp = Blueprint("contracts", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]
TIERS = ("BASIC", "STANDARD", "PREMIUM")


def _get_or_404(contract_id):
    contract = store.service_contracts.get(contract_id)
    if contract is None:
        raise not_found("ServiceContract not found")
    return contract


def _check_expected_version(body, fac):
    if "expected_facility_version" not in body or body["expected_facility_version"] is None:
        raise invalid_request("Missing required field: expected_facility_version")
    expected = body["expected_facility_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("Field expected_facility_version must be an integer")
    if expected != fac["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_facility_version does not match Facility.version")


@bp.route("/service-contracts", methods=["POST"])
def create_contract():
    require_roles(["ContractManager"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    tier = req_str(body, "tier")
    start = req_date(body, "start_date")
    term_months = req_int(body, "term_months")
    monthly_fee = req_int(body, "monthly_fee_cents")

    if tier not in TIERS:
        raise invalid_request("tier must be BASIC, STANDARD, or PREMIUM")
    if store.facilities.get(facility_id) is None:
        raise not_found("Facility not found")

    contract = new_resource()
    contract.update(
        {
            "facility_id": facility_id,
            "tier": tier,
            "start_date": start.isoformat(),
            "term_months": term_months,
            "end_date": add_months(start, term_months).isoformat(),
            "monthly_fee_cents": monthly_fee,
            "sla_base_hours": SLA_BASE_HOURS[tier],
            "status": "DRAFT",
            "sla_breach_count": 0,
            "termination_penalty_waived": False,
            "termination_fee_cents": None,
            "credits_accrued_total_cents": 0,
            "credits_applied_total_cents": 0,
            "credits_expired_total_cents": 0,
            "credits_outstanding_cents": 0,
        }
    )
    store.service_contracts[contract["id"]] = contract
    return ok_object(public(contract), 201)


@bp.route("/service-contracts", methods=["GET"])
def list_contracts():
    require_roles(ALL_ROLES)
    items = list(store.service_contracts.values())
    facility_id = request.args.get("facility_id")
    tier = request.args.get("tier")
    status = request.args.get("status")
    if facility_id is not None:
        items = [c for c in items if c["facility_id"] == facility_id]
    if tier is not None:
        items = [c for c in items if c["tier"] == tier]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(c) for c in page], limit, offset, total)


@bp.route("/service-contracts/<serviceContractId>", methods=["GET"])
def get_contract(serviceContractId):
    user_id, role = require_roles(ALL_ROLES)
    contract = _get_or_404(serviceContractId)
    check_ownership(user_id, role, contract["facility_id"])
    return ok_object(public(contract), 200)


@bp.route("/service-contracts/<serviceContractId>/activate", methods=["POST"])
def activate(serviceContractId):
    require_roles(["ContractManager"])
    contract = _get_or_404(serviceContractId)
    body = body_or_empty()
    # schema (tier 4): expected_facility_version presence/type
    if "expected_facility_version" not in body or body["expected_facility_version"] is None:
        raise invalid_request("Missing required field: expected_facility_version")
    expected = body["expected_facility_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("Field expected_facility_version must be an integer")

    if contract["status"] != "DRAFT":
        raise invalid_state("ServiceContract must be DRAFT to activate")

    fac = store.facilities.get(contract["facility_id"])
    if fac is None or fac["status"] != "ACTIVE":
        raise conflict(ERR_FACILITY_NOT_ACTIVE, "Facility must be ACTIVE to activate a contract")
    if expected != fac["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_facility_version does not match Facility.version")

    # supersede the facility's currently ACTIVE contract, if any
    for other in store.service_contracts.values():
        if other["facility_id"] == fac["id"] and other["status"] == "ACTIVE" and other["id"] != contract["id"]:
            other["status"] = "SUPERSEDED"
            touch(other)

    contract["status"] = "ACTIVE"
    touch(contract)
    # OCC: activation advances Facility.version by 1
    touch(fac)
    return ok_object(public(contract), 200)


@bp.route("/service-contracts/<serviceContractId>/suspend", methods=["POST"])
def suspend(serviceContractId):
    require_roles(["ContractManager"])
    contract = _get_or_404(serviceContractId)
    if contract["status"] != "ACTIVE":
        raise invalid_state("ServiceContract must be ACTIVE to suspend")
    contract["status"] = "SUSPENDED"
    touch(contract)
    return ok_object(public(contract), 200)


@bp.route("/service-contracts/<serviceContractId>/reinstate", methods=["POST"])
def reinstate(serviceContractId):
    require_roles(["ContractManager"])
    contract = _get_or_404(serviceContractId)
    if contract["status"] != "SUSPENDED":
        raise invalid_state("ServiceContract must be SUSPENDED to reinstate")
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok_object(public(contract), 200)


@bp.route("/service-contracts/<serviceContractId>/terminate", methods=["POST"])
def terminate(serviceContractId):
    require_roles(["ContractManager"])
    contract = _get_or_404(serviceContractId)
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_state("ServiceContract must be ACTIVE or SUSPENDED to terminate")
    contract["status"] = "TERMINATED"
    contract["termination_fee_cents"] = (
        0 if contract["termination_penalty_waived"] else 2 * contract["monthly_fee_cents"]
    )
    touch(contract)
    return ok_object(public(contract), 200)


@bp.route("/service-contracts/<serviceContractId>/expire", methods=["POST"])
def expire(serviceContractId):
    require_roles(["ContractManager"])
    contract = _get_or_404(serviceContractId)
    if contract["status"] != "ACTIVE":
        raise invalid_state("ServiceContract must be ACTIVE to expire")
    # expirable only when the logical clock date is strictly after end_date
    from datetime import date as _date

    if store.clock_today() <= _date.fromisoformat(contract["end_date"]):
        raise conflict(ERR_CONTRACT_NOT_EXPIRED, "Contract is not past its end_date")
    contract["status"] = "EXPIRED"
    touch(contract)
    return ok_object(public(contract), 200)
