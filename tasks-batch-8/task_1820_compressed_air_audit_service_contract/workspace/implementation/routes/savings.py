"""Savings cases: dual state dimensions (savings + rebate), model/rebase/measure/file."""

from datetime import date as _date

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import RETROFIT_APPROVED_OR_LATER, compute_deemed, utility_rebate
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    conflict,
    invalid_request,
    invalid_state,
    not_found,
    ERR_BASELINE_SUPERSEDED,
    ERR_FACILITY_MISMATCH,
    ERR_FACILITY_NOT_ACTIVE,
    ERR_POST_WINDOW_BEFORE_ACCEPTANCE,
    ERR_PROFILE_NOT_LOCKED,
    ERR_RETROFIT_NOT_ACCEPTED,
    ERR_RETROFIT_NOT_APPROVED,
    ERR_RETROFIT_STALE,
    ERR_SEGREGATION_OF_DUTIES,
)
import store
from store import new_resource, touch
from util import body_or_empty, opt_str, parse_pagination, public, req_str, sort_and_page

bp = Blueprint("savings", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_or_404(case_id):
    case = store.savings_cases.get(case_id)
    if case is None:
        raise not_found("SavingsCase not found")
    return case


def _locked_profile_of(facility_id):
    for p in store.demand_profiles.values():
        if p["facility_id"] == facility_id and p["status"] == "LOCKED":
            return p
    return None


@bp.route("/savings-cases", methods=["POST"])
def create_case():
    require_roles(["EnergyEngineer"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    baseline_profile_id = req_str(body, "baseline_profile_id")
    retrofit_project_id = req_str(body, "retrofit_project_id")

    fac = store.facilities.get(facility_id)
    if fac is None:
        raise not_found("Facility not found")

    # gates in pinned order: facility ACTIVE -> baseline LOCKED -> retrofit APPROVED+ -> mismatch
    if fac["status"] != "ACTIVE":
        raise conflict(ERR_FACILITY_NOT_ACTIVE, "Facility must be ACTIVE to create a savings case")

    baseline = store.demand_profiles.get(baseline_profile_id)
    if baseline is None or baseline["status"] != "LOCKED":
        raise conflict(ERR_PROFILE_NOT_LOCKED, "Baseline DemandProfile must be LOCKED")

    project = store.retrofit_projects.get(retrofit_project_id)
    if project is None or project["status"] not in RETROFIT_APPROVED_OR_LATER:
        raise conflict(ERR_RETROFIT_NOT_APPROVED, "RetrofitProject must be APPROVED or later")

    if baseline["facility_id"] != facility_id or project["facility_id"] != facility_id:
        raise conflict(ERR_FACILITY_MISMATCH, "Referenced entities must belong to the same facility")

    case = new_resource()
    case.update(
        {
            "facility_id": facility_id,
            "baseline_profile_id": baseline_profile_id,
            "baseline_profile_version": baseline["version"],
            "baseline_stale": False,
            "retrofit_project_id": retrofit_project_id,
            "retrofit_stale": False,
            "deemed_annual_savings_kwh": 0,
            "measured_annual_savings_kwh": None,
            "post_profile_id": None,
            "savings_status": "DRAFT",
            "rebate_status": "NONE",
            "provisional_rebate_cents": None,
            "final_rebate_cents": None,
        }
    )
    store.savings_cases[case["id"]] = case
    return ok_object(public(case), 201)


@bp.route("/savings-cases", methods=["GET"])
def list_cases():
    require_roles(ALL_ROLES)
    items = list(store.savings_cases.values())
    for param, field in (
        ("facility_id", "facility_id"),
        ("baseline_profile_id", "baseline_profile_id"),
        ("post_profile_id", "post_profile_id"),
        ("retrofit_project_id", "retrofit_project_id"),
        ("savings_status", "savings_status"),
        ("rebate_status", "rebate_status"),
    ):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[field] == value]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(c) for c in page], limit, offset, total)


@bp.route("/savings-cases/<savingsCaseId>", methods=["GET"])
def get_case(savingsCaseId):
    user_id, role = require_roles(ALL_ROLES)
    case = _get_or_404(savingsCaseId)
    check_ownership(user_id, role, case["facility_id"])
    return ok_object(public(case), 200)


@bp.route("/savings-cases/<savingsCaseId>/model", methods=["POST"])
def model(savingsCaseId):
    require_roles(["EnergyEngineer"])
    case = _get_or_404(savingsCaseId)
    if case["savings_status"] != "DRAFT":
        raise invalid_state("SavingsCase savings_status must be DRAFT to model")
    # pinned order: baseline staleness wins over retrofit staleness
    if case["baseline_stale"]:
        raise conflict(ERR_BASELINE_SUPERSEDED, "Pinned baseline profile was superseded")
    if case["retrofit_stale"]:
        raise conflict(ERR_RETROFIT_STALE, "Referenced retrofit project was cancelled")
    project = store.retrofit_projects.get(case["retrofit_project_id"])
    if project is None or project["status"] not in RETROFIT_APPROVED_OR_LATER:
        raise conflict(ERR_RETROFIT_NOT_APPROVED, "RetrofitProject must be APPROVED or later")

    case["deemed_annual_savings_kwh"] = compute_deemed(case)
    case["savings_status"] = "MODELED"
    touch(case)
    return ok_object(public(case), 200)


@bp.route("/savings-cases/<savingsCaseId>/rebase", methods=["POST"])
def rebase(savingsCaseId):
    require_roles(["EnergyEngineer"])
    case = _get_or_404(savingsCaseId)
    body = body_or_empty()
    new_project_id = opt_str(body, "retrofit_project_id")

    if not (case["baseline_stale"] or case["retrofit_stale"]):
        raise invalid_state("Rebase requires baseline_stale or retrofit_stale to be set")

    locked = _locked_profile_of(case["facility_id"])
    if locked is None:
        raise conflict(ERR_PROFILE_NOT_LOCKED, "No LOCKED DemandProfile exists for this facility")

    new_project = None
    if new_project_id is not None:
        new_project = store.retrofit_projects.get(new_project_id)
        # state-tier gate before referential-tier gate (per PRD §3.6)
        if new_project is None or new_project["status"] not in RETROFIT_APPROVED_OR_LATER:
            raise conflict(ERR_RETROFIT_NOT_APPROVED, "Replacement RetrofitProject must be APPROVED or later")
        if new_project["facility_id"] != case["facility_id"]:
            raise conflict(ERR_FACILITY_MISMATCH, "Replacement RetrofitProject must belong to the same facility")

    case["baseline_profile_id"] = locked["id"]
    case["baseline_profile_version"] = locked["version"]
    case["baseline_stale"] = False
    if new_project is not None:
        case["retrofit_project_id"] = new_project["id"]
        case["retrofit_stale"] = False
    case["savings_status"] = "DRAFT"
    case["deemed_annual_savings_kwh"] = 0
    touch(case)
    return ok_object(public(case), 200)


@bp.route("/savings-cases/<savingsCaseId>/open-measurement", methods=["POST"])
def open_measurement(savingsCaseId):
    require_roles(["EnergyEngineer"])
    case = _get_or_404(savingsCaseId)
    if case["savings_status"] != "MODELED":
        raise invalid_state("SavingsCase savings_status must be MODELED to open measurement")
    project = store.retrofit_projects.get(case["retrofit_project_id"])
    if project is None or project["status"] != "ACCEPTED":
        raise conflict(ERR_RETROFIT_NOT_ACCEPTED, "RetrofitProject must be ACCEPTED before measurement opens")
    case["savings_status"] = "MEASUREMENT_OPEN"
    touch(case)
    return ok_object(public(case), 200)


@bp.route("/savings-cases/<savingsCaseId>/close-measurement", methods=["POST"])
def close_measurement(savingsCaseId):
    user_id, _role = require_roles(["EnergyEngineer"])
    case = _get_or_404(savingsCaseId)
    body = body_or_empty()
    post_profile_id = req_str(body, "post_profile_id")

    if case["savings_status"] != "MEASUREMENT_OPEN":
        raise invalid_state("SavingsCase savings_status must be MEASUREMENT_OPEN to close measurement")

    # gates in order: LOCKED -> same facility -> window after acceptance -> SoD
    post = store.demand_profiles.get(post_profile_id)
    if post is None or post["status"] != "LOCKED":
        raise conflict(ERR_PROFILE_NOT_LOCKED, "Post-measurement profile must be LOCKED")
    if post["facility_id"] != case["facility_id"]:
        raise conflict(ERR_FACILITY_MISMATCH, "Post-measurement profile must belong to the same facility")
    project = store.retrofit_projects.get(case["retrofit_project_id"])
    accepted = _date.fromisoformat(project["accepted_date"]) if project and project["accepted_date"] else None
    if accepted is None or _date.fromisoformat(post["window_start_date"]) <= accepted:
        raise conflict(
            ERR_POST_WINDOW_BEFORE_ACCEPTANCE,
            "Post-measurement window must begin after retrofit acceptance",
        )
    baseline = store.demand_profiles.get(case["baseline_profile_id"])
    if baseline is not None and user_id == baseline["locked_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Closer must differ from the baseline locker")

    case["post_profile_id"] = post["id"]
    case["measured_annual_savings_kwh"] = baseline["baseline_annual_kwh"] - post["baseline_annual_kwh"]
    case["savings_status"] = "MEASURED"
    touch(case)
    return ok_object(public(case), 200)


@bp.route("/savings-cases/<savingsCaseId>/file-rebate", methods=["POST"])
def file_rebate(savingsCaseId):
    require_roles(["EnergyEngineer"])
    case = _get_or_404(savingsCaseId)
    if case["rebate_status"] != "NONE" or case["savings_status"] not in ("MODELED", "MEASURED"):
        raise invalid_state("Rebate filing requires rebate_status NONE and savings MODELED or MEASURED")
    project = store.retrofit_projects.get(case["retrofit_project_id"])
    cost = project["project_cost_cents"] if project else 0
    # provisional rebate is ALWAYS computed from deemed savings, even when MEASURED
    case["provisional_rebate_cents"] = utility_rebate(case["deemed_annual_savings_kwh"], cost)
    case["rebate_status"] = "FILED"
    touch(case)
    return ok_object(public(case), 200)


@bp.route("/savings-cases/<savingsCaseId>/record-rebate-decision", methods=["POST"])
def record_rebate_decision(savingsCaseId):
    require_roles(["DealerAdmin", "ContractManager"])
    case = _get_or_404(savingsCaseId)
    body = body_or_empty()
    outcome = req_str(body, "outcome")
    if outcome not in ("APPROVED", "REJECTED"):
        raise invalid_request("outcome must be APPROVED or REJECTED")
    if case["rebate_status"] != "FILED":
        raise invalid_state("SavingsCase rebate_status must be FILED to record a decision")

    if outcome == "APPROVED":
        project = store.retrofit_projects.get(case["retrofit_project_id"])
        cost = project["project_cost_cents"] if project else 0
        # final rebate over measured savings when MEASURED, else deemed
        figure = (
            case["measured_annual_savings_kwh"]
            if case["savings_status"] == "MEASURED"
            else case["deemed_annual_savings_kwh"]
        )
        case["final_rebate_cents"] = utility_rebate(figure, cost)
        case["rebate_status"] = "APPROVED"
    else:
        case["rebate_status"] = "REJECTED"
    touch(case)
    return ok_object(public(case), 200)
