"""TradePackage endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, SUMMARY_ROLES, auth
from response import ok, ok_list
from services import (
    BONDING_POLICIES,
    bids_of,
    get_package,
    get_project,
    package_financials,
    project_clock,
    ser_package,
    sorted_created,
    stamp,
    subs_of,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_iso_dt,
    as_str,
    basis_arg,
    body,
    pagination_args,
    parse_dt,
    required,
    round_half_up_cents,
)

bp = Blueprint("packages", __name__)


@bp.post("/projects/<pid>/trade-packages")
def create_package(pid):
    auth(["BuyoutLead", "GCAdmin"])
    project = get_project(pid)
    data = body()
    trade_code = as_str(required(data, "trade_code"), "trade_code")
    title = as_str(required(data, "title"), "title")
    estimated_budget_cents = as_int(
        required(data, "estimated_budget_cents"), "estimated_budget_cents"
    )
    budgeted_contingency_cents = as_int(
        required(data, "budgeted_contingency_cents"), "budgeted_contingency_cents"
    )
    bonding_policy = as_enum(
        required(data, "bonding_policy"), "bonding_policy", BONDING_POLICIES
    )
    expected_project_version = as_int(
        required(data, "expected_project_version"), "expected_project_version"
    )
    spec_section = data.get("spec_section")
    if spec_section is not None:
        as_str(spec_section, "spec_section")
    bid_due_at = data.get("bid_due_at")
    if bid_due_at is not None:
        as_iso_dt(bid_due_at, "bid_due_at")
    # OCC guard (priority 4) precedes the project-state gate (priority 5).
    if expected_project_version != project["version"]:
        raise ApiError(
            "ERR_STALE_PACKAGE_VERSION",
            412,
            "expected_project_version does not match current Project.version",
        )
    if project["status"] == "SETUP":
        raise ApiError(
            "ERR_PACKAGE_NOT_OPEN", 409, "Project not in BUYOUT_OPEN for child mutations"
        )
    for pk in DB["trade_packages"].values():
        if pk["project_id"] == project["id"] and pk["trade_code"] == trade_code:
            raise ApiError(
                "ERR_VALIDATION", 422, "trade_code must be unique within the project"
            )
    rec = {
        "id": new_id(),
        "project_id": project["id"],
        "trade_code": trade_code,
        "title": title,
        "estimated_budget_cents": estimated_budget_cents,
        "budgeted_contingency_cents": budgeted_contingency_cents,
        "spec_section": spec_section,
        "bid_due_at": bid_due_at,
        "bonding_policy": bonding_policy,
        "status": "DRAFT",
        "awarded_value_cents": 0,
        "buyout_savings_cents": estimated_budget_cents,
        "buyout_posture": None,
    }
    stamp(rec)
    awarded, savings, posture = package_financials(rec, "PROVISIONAL")
    rec["awarded_value_cents"] = awarded
    rec["buyout_savings_cents"] = savings
    rec["buyout_posture"] = posture
    DB["trade_packages"][rec["id"]] = rec
    touch(project)
    return ok(ser_package(rec), status=201)


@bp.get("/trade-packages/<pkg_id>")
def get_one_package(pkg_id):
    auth(ALL_ROLES)
    return ok(ser_package(get_package(pkg_id), basis_arg()))


@bp.get("/projects/<pid>/trade-packages")
def list_packages(pid):
    auth(ALL_ROLES)
    project = get_project(pid)
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = sorted_created(
        pk for pk in DB["trade_packages"].values() if pk["project_id"] == project["id"]
    )
    if status is not None:
        items = [pk for pk in items if pk["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_package(pk) for pk in page], total, limit, offset)


@bp.post("/trade-packages/<pkg_id>/publish")
def publish_package(pkg_id):
    auth(["BuyoutLead"])
    pkg = get_package(pkg_id)
    if pkg["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Trade package is not in DRAFT"
        )
    project = get_project(pkg["project_id"])
    if project["status"] != "BUYOUT_OPEN":
        raise ApiError(
            "ERR_PACKAGE_NOT_OPEN", 409, "Project not in BUYOUT_OPEN for child mutations"
        )
    bid_due_at = pkg.get("bid_due_at")
    if bid_due_at is None or not parse_dt(bid_due_at) > project_clock(project):
        raise ApiError(
            "ERR_BID_WINDOW_INVALID",
            409,
            "bid_due_at must be strictly after the project clock at publish",
        )
    pkg["status"] = "PUBLISHED"
    touch(pkg)
    return ok(ser_package(pkg))


@bp.post("/trade-packages/<pkg_id>/close-bidding")
def close_bidding(pkg_id):
    auth(["BuyoutLead"])
    pkg = get_package(pkg_id)
    if pkg["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Trade package is not in PUBLISHED"
        )
    if not any(b["status"] == "PLACED" for b in bids_of(pkg)):
        raise ApiError(
            "ERR_NO_BIDS_RECEIVED", 409, "close-bidding requires at least one PLACED bid"
        )
    pkg["status"] = "UNDER_LEVELING"
    touch(pkg)
    return ok(ser_package(pkg))


@bp.get("/trade-packages/<pkg_id>/replacement-analysis")
def replacement_analysis(pkg_id):
    auth(SUMMARY_ROLES)
    pkg = get_package(pkg_id)
    items = []
    for s in sorted_created(subs_of(pkg)):
        if not s["default_flag"]:
            continue
        subguard_claim = 0
        if s["bonding_requirement"] == "SUBGUARD":
            subguard_claim = round_half_up_cents(
                Decimal("0.20") * Decimal(s["contract_value_cents"])
            )
        exposure = max(
            0, (s.get("estimated_replacement_cost_cents") or 0) - s["contract_value_cents"]
        ) + subguard_claim
        items.append(
            {
                "subcontract_id": s["id"],
                "bonding_requirement": s["bonding_requirement"],
                "contract_value_cents": s["contract_value_cents"],
                "estimated_replacement_cost_cents": s.get(
                    "estimated_replacement_cost_cents"
                ),
                "subguard_claim_estimate_cents": subguard_claim,
                "exposure_cents": exposure,
            }
        )
    return ok({"items": items})
