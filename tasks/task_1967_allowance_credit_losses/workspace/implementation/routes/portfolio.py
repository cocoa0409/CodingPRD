"""PortfolioSegment, Loan, EconomicScenario endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CHARGE_OFF_EXCEEDS_BALANCE,
    ERR_DUPLICATE_LOAN_NUMBER,
    ERR_DUPLICATE_SEGMENT_CODE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_RECOVERY_EXCEEDS_CHARGE_OFF,
    ERR_SCENARIO_IN_USE,
    ERR_SCENARIO_WINDOW_OVERLAP,
    ERR_SEGMENT_NOT_OPEN,
)
from middleware import ALL_ROLES, require_roles
from response import success_response
from services import (
    BASE_RATE_BY_BAND,
    IN_FLIGHT_RUN_STATUSES,
    PRODUCT_TYPES,
    RISK_BANDS,
    RISK_RATINGS,
    SCENARIO_TYPES,
    WATCH_RATE_THRESHOLD_BPS,
    compute_individually_evaluated,
    flag_draft_runs_for_segmentation_review,
    get_or_404,
    public,
    recompute_segment_rate,
    stamp_new,
    touch,
)
from validation import (
    get_body,
    opt_int,
    paginate,
    parse_pagination,
    quarter_index,
    req_enum,
    req_int,
    req_period,
    req_str,
    sorted_by_creation,
)

bp = Blueprint("portfolio", __name__)


# ---------------------------------------------------------------------------
# PortfolioSegment
# ---------------------------------------------------------------------------

@bp.post("/cecl/portfolio-segments")
def create_segment():
    require_roles(["CreditAnalyst"])
    body = get_body()
    segment_code = req_str(body, "segment_code")
    name = req_str(body, "name")
    product_type = req_enum(body, "product_type", PRODUCT_TYPES)
    band = req_enum(body, "risk_rating_band", RISK_BANDS)
    vintage_year = req_int(body, "vintage_year")
    for existing in db.segments.values():
        if existing["segment_code"] == segment_code:
            raise ApiError(
                ERR_DUPLICATE_SEGMENT_CODE,
                409,
                "segment_code already exists: %s" % segment_code,
            )
    segment = stamp_new(
        {
            "segment_code": segment_code,
            "name": name,
            "product_type": product_type,
            "risk_rating_band": band,
            "vintage_year": vintage_year,
            "status": "OPEN",
            "origination_total_cents": 0,
            "ytd_gross_charge_offs_cents": 0,
            "ytd_recoveries_cents": 0,
        }
    )
    db.segments[segment["id"]] = segment
    return success_response(serialize_segment(segment), 201)


def serialize_segment(segment):
    out = public(segment)
    out["charge_off_rate_bps"] = segment.get("charge_off_rate_bps", 0)
    out["base_loss_rate_bps"] = BASE_RATE_BY_BAND[segment["risk_rating_band"]]
    return out


@bp.get("/cecl/portfolio-segments/<segmentId>")
def get_segment(segmentId):
    require_roles(ALL_ROLES)
    segment = get_or_404(db.segments, segmentId, "PortfolioSegment")
    return success_response(serialize_segment(segment), 200)


@bp.get("/cecl/portfolio-segments/<segmentId>/loans")
def list_segment_loans(segmentId):
    require_roles(ALL_ROLES)
    get_or_404(db.segments, segmentId, "PortfolioSegment")
    limit, offset = parse_pagination()
    items = [l for l in db.loans.values() if l["segment_id"] == segmentId]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success_response([public(l) for l in page], 200, "array", pagination)


@bp.get("/cecl/portfolio-segments/<segmentId>/qualitative-factors")
def list_segment_factors(segmentId):
    require_roles(ALL_ROLES)
    get_or_404(db.segments, segmentId, "PortfolioSegment")
    limit, offset = parse_pagination()
    items = [f for f in db.factors.values() if f["segment_id"] == segmentId]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success_response([public(f) for f in page], 200, "array", pagination)


# ---------------------------------------------------------------------------
# Loan
# ---------------------------------------------------------------------------

@bp.post("/cecl/loans")
def create_loan():
    require_roles(["CreditAnalyst"])
    body = get_body()
    segment_id = req_str(body, "segment_id")
    loan_number = req_str(body, "loan_number")
    amortized_cost = req_int(body, "amortized_cost_cents")
    risk_rating = req_enum(body, "risk_rating", RISK_RATINGS)
    delinquency_days = opt_int(body, "delinquency_days", 0)
    collateral_value = opt_int(body, "collateral_value_cents", 0)
    if amortized_cost <= 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "amortized_cost_cents must be greater than zero"
        )
    if delinquency_days < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "delinquency_days may not be negative")
    if collateral_value < 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "collateral_value_cents may not be negative"
        )
    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "segment_id does not identify an existing segment")
    for existing in db.loans.values():
        if existing["loan_number"] == loan_number:
            raise ApiError(
                ERR_DUPLICATE_LOAN_NUMBER,
                409,
                "loan_number already exists: %s" % loan_number,
            )
    if segment["status"] != "OPEN":
        raise ApiError(
            ERR_SEGMENT_NOT_OPEN,
            409,
            "Loans can only be booked into an OPEN segment",
        )
    loan = stamp_new(
        {
            "segment_id": segment_id,
            "loan_number": loan_number,
            "amortized_cost_cents": amortized_cost,
            "risk_rating": risk_rating,
            "delinquency_days": delinquency_days,
            "collateral_value_cents": collateral_value,
            "individually_evaluated": compute_individually_evaluated(
                risk_rating, amortized_cost
            ),
            "status": "ACTIVE",
            "charged_off_total_cents": 0,
            "recovered_total_cents": 0,
        }
    )
    db.loans[loan["id"]] = loan
    segment["origination_total_cents"] += amortized_cost
    recompute_segment_rate(segment)
    touch(segment)
    return success_response(public(loan), 201)


@bp.get("/cecl/loans/<loanId>")
def get_loan(loanId):
    require_roles(ALL_ROLES)
    loan = get_or_404(db.loans, loanId, "Loan")
    return success_response(public(loan), 200)


@bp.post("/cecl/loans/<loanId>/charge_off")
def charge_off_loan(loanId):
    require_roles(["CreditAnalyst"])
    loan = get_or_404(db.loans, loanId, "Loan")
    body = get_body()
    amount = req_int(body, "charge_off_amount_cents")
    req_period(body, "charge_off_period")
    if loan["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an ACTIVE loan can be charged off",
        )
    if amount < 1 or amount > loan["amortized_cost_cents"]:
        raise ApiError(
            ERR_CHARGE_OFF_EXCEEDS_BALANCE,
            422,
            "charge_off_amount_cents must be at least 1 and no more than the amortized cost",
        )
    # Loan mutation
    loan["amortized_cost_cents"] -= amount
    loan["charged_off_total_cents"] += amount
    if loan["amortized_cost_cents"] == 0:
        loan["status"] = "CHARGED_OFF"
    touch(loan)
    # Cascade hop 1: segment cumulative counters
    segment = db.segments[loan["segment_id"]]
    segment["ytd_gross_charge_offs_cents"] += amount
    # Cascade hop 2: recompute rate; OPEN -> WATCH when strictly above threshold
    rate = recompute_segment_rate(segment)
    entered_watch = False
    if rate > WATCH_RATE_THRESHOLD_BPS and segment["status"] == "OPEN":
        segment["status"] = "WATCH"
        entered_watch = True
    touch(segment)
    # Cascade hop 3: flag DRAFT runs on WATCH entry
    if entered_watch:
        flag_draft_runs_for_segmentation_review()
    return success_response(public(loan), 200)


@bp.post("/cecl/loans/<loanId>/record_recovery")
def record_recovery(loanId):
    require_roles(["CreditAnalyst"])
    loan = get_or_404(db.loans, loanId, "Loan")
    body = get_body()
    amount = req_int(body, "recovery_amount_cents")
    req_period(body, "recovery_period")
    if amount < 1:
        raise ApiError(
            ERR_RECOVERY_EXCEEDS_CHARGE_OFF,
            422,
            "recovery_amount_cents must be at least 1",
        )
    if loan["status"] == "ACTIVE" and loan["charged_off_total_cents"] == 0:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Nothing to recover against: the loan has no charge-offs",
        )
    if loan["recovered_total_cents"] + amount > loan["charged_off_total_cents"]:
        raise ApiError(
            ERR_RECOVERY_EXCEEDS_CHARGE_OFF,
            422,
            "Cumulative recoveries would exceed cumulative charge-offs on the loan",
        )
    loan["recovered_total_cents"] += amount
    touch(loan)
    segment = db.segments[loan["segment_id"]]
    segment["ytd_recoveries_cents"] += amount
    rate = recompute_segment_rate(segment)
    if rate <= WATCH_RATE_THRESHOLD_BPS and segment["status"] == "WATCH":
        segment["status"] = "OPEN"
    touch(segment)
    return success_response(public(loan), 200)


# ---------------------------------------------------------------------------
# EconomicScenario
# ---------------------------------------------------------------------------

@bp.post("/cecl/economic-scenarios")
def create_scenario():
    require_roles(["ModelValidator"])
    body = get_body()
    name = req_str(body, "name")
    scenario_type = req_enum(body, "scenario_type", SCENARIO_TYPES)
    unemployment = req_int(body, "unemployment_rate_bps")
    gdp_growth = req_int(body, "gdp_growth_bps")
    from_period = req_period(body, "effective_from_period")
    to_period = req_period(body, "effective_to_period")
    from_idx = quarter_index(from_period)
    to_idx = quarter_index(to_period)
    if to_idx <= from_idx:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "effective_to_period must be strictly after effective_from_period",
        )
    for existing in db.scenarios.values():
        if existing["scenario_type"] != scenario_type:
            continue
        if existing["status"] != "ACTIVE":
            continue
        ex_from = quarter_index(existing["effective_from_period"])
        ex_to = quarter_index(existing["effective_to_period"])
        # Half-open windows [from, to) overlap iff from1 < to2 and from2 < to1
        if from_idx < ex_to and ex_from < to_idx:
            raise ApiError(
                ERR_SCENARIO_WINDOW_OVERLAP,
                409,
                "Half-open window overlaps another ACTIVE scenario of the same type",
            )
    scenario = stamp_new(
        {
            "name": name,
            "scenario_type": scenario_type,
            "unemployment_rate_bps": unemployment,
            "gdp_growth_bps": gdp_growth,
            "effective_from_period": from_period,
            "effective_to_period": to_period,
            "status": "ACTIVE",
        }
    )
    db.scenarios[scenario["id"]] = scenario
    return success_response(public(scenario), 201)


@bp.get("/cecl/economic-scenarios/<scenarioId>")
def get_scenario(scenarioId):
    require_roles(ALL_ROLES)
    scenario = get_or_404(db.scenarios, scenarioId, "EconomicScenario")
    return success_response(public(scenario), 200)


@bp.post("/cecl/economic-scenarios/<scenarioId>/archive")
def archive_scenario(scenarioId):
    require_roles(["ModelValidator"])
    get_body()
    scenario = get_or_404(db.scenarios, scenarioId, "EconomicScenario")
    if scenario["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an ACTIVE scenario can be archived",
        )
    for run in db.runs.values():
        if run["status"] not in IN_FLIGHT_RUN_STATUSES:
            continue
        for entry in run["scenario_weights"]:
            if entry["scenario_id"] == scenario["id"]:
                raise ApiError(
                    ERR_SCENARIO_IN_USE,
                    409,
                    "Scenario is referenced by an in-flight run and cannot be archived",
                )
    scenario["status"] = "ARCHIVED"
    touch(scenario)
    return success_response(public(scenario), 200)
