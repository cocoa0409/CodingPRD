"""Collateral item and appraisal routes (PRD §3.5)."""
from flask import Blueprint

import db
from auth import (
    ROLE_APPRAISAL_DESK, ROLE_LEGAL_COUNSEL, ROLE_LOAN_ACCOUNTING,
    ROLE_PORTFOLIO_ANALYST, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_SYSTEM_ADMIN,
    ROLE_WORKOUT_OFFICER, require_roles,
)
from db import STORE
from errors import (
    ApiError, ERR_APPRAISAL_NOT_DRAFT, ERR_APPRAISAL_NOT_SUBMITTED,
    ERR_APPRAISAL_STALE, ERR_COLLATERAL_ENCUMBERED, ERR_COLLATERAL_NOT_PLEDGED,
    ERR_FISCAL_LIMIT, ERR_INVALID_STATE, ERR_INVALID_TEMPORAL, ERR_NOT_FOUND,
    ERR_STALE_VERSION,
)
from response import ok, paginate
from services import (
    STALE_APPRAISAL_DAYS, appraisal_out, appraisals_of_collateral,
    collateral_of_loan, collateral_out, get_appraisal, get_collateral,
    get_loan, liquidation_value, recompute_lgd, sorted_rows,
)
from validate import as_datetime, as_enum, as_int, as_str, field, get_body, no_unknown

bp = Blueprint("collateral", __name__)

COLLATERAL_TYPES = ("CRE_REAL_ESTATE", "EQUIPMENT", "INVENTORY", "RECEIVABLES", "SECURITIES")
ITEM_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_APPRAISAL_DESK,
    ROLE_LEGAL_COUNSEL, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SYSTEM_ADMIN,
)
APPRAISAL_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_APPRAISAL_DESK,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)


def resolve_item(loanId, collateralId=None):
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    item = None
    if collateralId is not None:
        item = get_collateral(collateralId)
        if item is None or item["loan_id"] != loanId:
            raise ApiError(ERR_NOT_FOUND, 404, "Collateral item not found")
    return loan, item


def resolve_appraisal(loanId, collateralId, appraisalId):
    loan, item = resolve_item(loanId, collateralId)
    appraisal = get_appraisal(appraisalId)
    if appraisal is None or appraisal["collateral_id"] != collateralId:
        raise ApiError(ERR_NOT_FOUND, 404, "Appraisal not found")
    return loan, item, appraisal


def staleness(effective_dt):
    """Whole days between the effective date and the logical clock."""
    return (db.logical_now() - effective_dt).days


# --------------------------------------------------------------------------
# Collateral items
# --------------------------------------------------------------------------

@bp.route("/loans/<loanId>/collateral", methods=["POST"])
def pledge_collateral(loanId):
    require_roles(ROLE_WORKOUT_OFFICER, ROLE_SYSTEM_ADMIN)
    loan, _ = resolve_item(loanId)
    data = get_body()
    no_unknown(data, {"collateral_type", "description", "liquidation_discount_bps"})
    ctype = as_enum(
        field(data, "collateral_type"), "collateral_type", COLLATERAL_TYPES
    )
    description = as_str(field(data, "description"), "description")
    discount = as_int(
        field(data, "liquidation_discount_bps"), "liquidation_discount_bps", 0, 9000
    )
    item = db.stamp({
        "id": db.new_id(),
        "loan_id": loanId,
        "collateral_type": ctype,
        "description": description,
        "liquidation_discount_bps": discount,
        "current_appraised_value_cents": 0,
        "current_liquidation_value_cents": 0,
        "status": "PLEDGED",
    })
    STORE["collateral"][item["id"]] = item
    return ok(collateral_out(item), 201)


@bp.route("/loans/<loanId>/collateral", methods=["GET"])
def list_collateral(loanId):
    require_roles(*ITEM_READERS)
    resolve_item(loanId)
    rows = [collateral_out(c) for c in sorted_rows(collateral_of_loan(loanId))]
    return paginate(rows)


@bp.route("/loans/<loanId>/collateral/<collateralId>", methods=["GET"])
def get_collateral_route(loanId, collateralId):
    require_roles(*ITEM_READERS)
    _, item = resolve_item(loanId, collateralId)
    return ok(collateral_out(item))


@bp.route("/loans/<loanId>/collateral/<collateralId>/release", methods=["POST"])
def release_collateral(loanId, collateralId):
    require_roles(ROLE_SPECIAL_ASSETS_MANAGER)
    loan, item = resolve_item(loanId, collateralId)
    if item["status"] != "PLEDGED":
        raise ApiError(ERR_COLLATERAL_NOT_PLEDGED, 409, "Collateral is not PLEDGED")
    cases = sorted_rows(
        [c for c in STORE["cases"].values() if c["loan_id"] == loanId]
    )
    open_case = next((c for c in reversed(cases) if c["status"] != "CLOSED"), None)
    unencumbered = loan["current_principal_cents"] == 0 or (
        open_case is None and len(cases) > 0
    )
    if not unencumbered:
        raise ApiError(
            ERR_COLLATERAL_ENCUMBERED, 422,
            "Collateral remains encumbered: principal outstanding and case not CLOSED",
        )
    item["status"] = "RELEASED"
    db.touch(item)
    recompute_lgd(loan)
    return ok(collateral_out(item))


# --------------------------------------------------------------------------
# Appraisals
# --------------------------------------------------------------------------

@bp.route("/loans/<loanId>/collateral/<collateralId>/appraisals", methods=["POST"])
def order_appraisal(loanId, collateralId):
    user_id, _ = require_roles(ROLE_APPRAISAL_DESK)
    loan, item = resolve_item(loanId, collateralId)
    data = get_body()
    no_unknown(data, {
        "appraised_value_cents", "effective_date", "appraiser_id",
        "expected_collateral_version",
    })
    value = as_int(field(data, "appraised_value_cents"), "appraised_value_cents")
    eff_raw, eff_dt = as_datetime(field(data, "effective_date"), "effective_date")
    appraiser = as_str(field(data, "appraiser_id"), "appraiser_id")
    expected = as_int(
        field(data, "expected_collateral_version"), "expected_collateral_version"
    )

    # state (priority 4): ordering flips PLEDGED -> UNDER_REVALUATION
    if item["status"] != "PLEDGED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Collateral item is not in PLEDGED state"
        )
    # OCC (priority 5)
    if expected != item["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale collateral version")
    # fiscal (priority 9): concluded value must be positive
    if value <= 0:
        raise ApiError(
            ERR_FISCAL_LIMIT, 422, "appraised_value_cents must be greater than zero"
        )
    # temporal (priority 10): effective date not in the future
    if eff_dt > db.logical_now():
        raise ApiError(
            ERR_INVALID_TEMPORAL, 422,
            "effective_date must be on or before the current time",
        )

    appraisal = db.stamp({
        "id": db.new_id(),
        "collateral_id": collateralId,
        "appraised_value_cents": value,
        "effective_date": eff_raw,
        "effective_dt": eff_dt,
        "appraiser_id": appraiser,
        "staleness_days": None,
        "status": "DRAFT",
    })
    STORE["appraisals"][appraisal["id"]] = appraisal
    item["status"] = "UNDER_REVALUATION"
    db.touch(item)
    return ok(appraisal_out(appraisal), 201)


@bp.route("/loans/<loanId>/collateral/<collateralId>/appraisals", methods=["GET"])
def list_appraisals(loanId, collateralId):
    require_roles(*APPRAISAL_READERS)
    resolve_item(loanId, collateralId)
    rows = [
        appraisal_out(a) for a in sorted_rows(appraisals_of_collateral(collateralId))
    ]
    return paginate(rows)


@bp.route(
    "/loans/<loanId>/collateral/<collateralId>/appraisals/<appraisalId>/submit",
    methods=["POST"],
)
def submit_appraisal(loanId, collateralId, appraisalId):
    require_roles(ROLE_APPRAISAL_DESK)
    _, _, appraisal = resolve_appraisal(loanId, collateralId, appraisalId)
    if appraisal["status"] != "DRAFT":
        raise ApiError(ERR_APPRAISAL_NOT_DRAFT, 409, "Appraisal is not DRAFT")
    appraisal["staleness_days"] = staleness(appraisal["effective_dt"])
    appraisal["status"] = "SUBMITTED"
    db.touch(appraisal)
    return ok(appraisal_out(appraisal))


@bp.route(
    "/loans/<loanId>/collateral/<collateralId>/appraisals/<appraisalId>/accept",
    methods=["POST"],
)
def accept_appraisal(loanId, collateralId, appraisalId):
    require_roles(ROLE_APPRAISAL_DESK)  # peer role: any desk user may accept
    loan, item, appraisal = resolve_appraisal(loanId, collateralId, appraisalId)
    if appraisal["status"] != "SUBMITTED":
        raise ApiError(ERR_APPRAISAL_NOT_SUBMITTED, 409, "Appraisal is not SUBMITTED")
    # staleness re-evaluated against the logical clock at acceptance
    current_staleness = staleness(appraisal["effective_dt"])
    if current_staleness > STALE_APPRAISAL_DAYS:
        raise ApiError(
            ERR_APPRAISAL_STALE, 422,
            "Appraisal is more than 365 days old at acceptance",
        )
    appraisal["staleness_days"] = current_staleness
    appraisal["status"] = "ACCEPTED"
    db.touch(appraisal)
    item["current_appraised_value_cents"] = appraisal["appraised_value_cents"]
    item["current_liquidation_value_cents"] = liquidation_value(
        appraisal["appraised_value_cents"], item["liquidation_discount_bps"]
    )
    item["status"] = "PLEDGED"
    db.touch(item)
    recompute_lgd(loan)
    return ok(appraisal_out(appraisal))


@bp.route(
    "/loans/<loanId>/collateral/<collateralId>/appraisals/<appraisalId>/reject",
    methods=["POST"],
)
def reject_appraisal(loanId, collateralId, appraisalId):
    require_roles(ROLE_APPRAISAL_DESK)
    _, item, appraisal = resolve_appraisal(loanId, collateralId, appraisalId)
    if appraisal["status"] != "SUBMITTED":
        raise ApiError(ERR_APPRAISAL_NOT_SUBMITTED, 409, "Appraisal is not SUBMITTED")
    appraisal["status"] = "REJECTED"
    db.touch(appraisal)
    item["status"] = "PLEDGED"
    db.touch(item)
    return ok(appraisal_out(appraisal))
