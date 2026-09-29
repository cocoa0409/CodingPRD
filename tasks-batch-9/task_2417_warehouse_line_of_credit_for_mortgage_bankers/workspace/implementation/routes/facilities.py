"""Facility routes: booking, posture, the advance-rate grid and the panels."""

from datetime import date, timedelta

from flask import Blueprint, request

from clock import clock
from db import base_row, by_created_at, db, touch
from errors import ApiError
from middleware import (
    BORROWER,
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    WIRE_OPERATOR,
    own_facility,
    require_auth,
)
from money import floor_cents, frac
from response import ok
from routes.common import (
    filter_by,
    get_facility,
    get_investor,
    list_response,
)
from serializers import (
    aging_run_out,
    commitment_out,
    covenant_test_out,
    custodian_out,
    exposure_summary_out,
    facility_out,
    investor_out,
    ledger_entry_out,
    margin_call_out,
    product_rate_out,
)
from services import aging, computed, covenant
from services.constants import (
    CLEAN_COVENANT_STATUSES,
    COMMITMENT_BUFFER_DAYS,
    COVENANT_BREACH_PAYDOWN_PCT,
    PRODUCT_CODES,
    COUNTERPARTY_RATINGS,
)
from services.states import create_margin_call, restrict_if_active, suspend_facility
from validation import (
    MISSING,
    body,
    bad,
    reject_system_fields,
    v_bool,
    v_date,
    v_digits,
    v_enum,
    v_id,
    v_int,
    v_rate,
    v_string,
)

bp = Blueprint("facilities", __name__)


# ------------------------------------------------------------------- booking

@bp.post("/facilities")
def create_facility():
    user_id, _role = require_auth([CREDIT_OFFICER])
    data = body()
    reject_system_fields(data, {
        "id": MISSING,
        "created_at": MISSING,
        "updated_at": MISSING,
        "status": "PENDING_APPROVAL",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "approved_at": None,
        "last_accrual_at": None,
        "outstanding_principal_cents": 0,
        "accrued_fee_balance_cents": 0,
        "wet_outstanding_cents": 0,
        "aged_outstanding_cents": 0,
        "scratch_and_dent_outstanding_cents": 0,
        "open_margin_call_count": 0,
        "consecutive_breach_count": 0,
        "escalated_demand_count": 0,
        "last_covenant_status": "NOT_TESTED",
        "version": 1,
    })
    borrower_legal_name = v_string(data, "borrower_legal_name", max_len=200)
    committed = v_int(data, "committed_amount_cents", minimum=100000000)
    wet = v_int(data, "wet_sublimit_cents", minimum=0, maximum=committed)
    aged = v_int(data, "aged_sublimit_cents", minimum=0, maximum=committed)
    scratch = v_int(data, "scratch_and_dent_sublimit_cents", minimum=0,
                    maximum=committed)
    min_tnw = v_int(data, "min_tangible_net_worth_cents", minimum=0)
    min_liq = v_int(data, "min_liquidity_cents", minimum=0)
    min_ttm = v_int(data, "min_ttm_net_income_cents", minimum=0)
    max_conc = v_rate(data, "max_investor_concentration_pct",
                      exclusive_min=0, exclusive_max=1)
    bailee_period_days = v_int(data, "bailee_period_days", required=False,
                              minimum=1, maximum=90, default=30)
    unused_line_fee_rate = v_rate(data, "unused_line_fee_rate", minimum=0,
                                  exclusive_max=1)
    settlement_account_last4 = v_digits(data, "settlement_account_last4", 4)

    facility = base_row()
    facility.update({
        "borrower_legal_name": borrower_legal_name,
        "committed_amount_cents": committed,
        "wet_sublimit_cents": wet,
        "aged_sublimit_cents": aged,
        "scratch_and_dent_sublimit_cents": scratch,
        "min_tangible_net_worth_cents": min_tnw,
        "min_liquidity_cents": min_liq,
        "min_ttm_net_income_cents": min_ttm,
        "max_investor_concentration_pct": max_conc,
        "bailee_period_days": bailee_period_days,
        "unused_line_fee_rate": unused_line_fee_rate,
        "settlement_account_last4": settlement_account_last4,
        "status": "PENDING_APPROVAL",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "approved_at": None,
        "last_accrual_at": None,
    })
    db.facilities[facility["id"]] = facility
    return ok(facility_out(facility), 201)


@bp.get("/facilities")
def list_facilities():
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST])
    rows = by_created_at(list(db.facilities.values()))
    rows = filter_by(rows, "status")
    return list_response(rows, facility_out)


@bp.get("/facilities/<facility_id>")
def read_facility(facility_id):
    user_id, role = require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, WIRE_OPERATOR,
                                  BORROWER])
    facility = get_facility(facility_id)
    own_facility(user_id, role, facility["id"])
    return ok(facility_out(facility))


@bp.post("/facilities/<facility_id>/approve")
def approve_facility(facility_id):
    user_id, _role = require_auth([CREDIT_OFFICER])
    facility = get_facility(facility_id)
    body()
    if facility["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_FACILITY_INVALID_STATE",
                       "Only a PENDING_APPROVAL facility may be approved.")
    if not computed.facility_rate_rows(facility["id"]):
        raise ApiError("ERR_NO_ADVANCE_RATES_CONFIGURED",
                       "The facility has no configured product advance rate.")
    if facility["created_by_user_id"] == user_id:
        raise ApiError("ERR_DUAL_CONTROL_VIOLATION",
                       "A facility may not be approved by its creator.")
    now = clock.now()
    facility["status"] = "ACTIVE"
    facility["approved_by_user_id"] = user_id
    facility["approved_at"] = now
    facility["last_accrual_at"] = now
    touch(facility)
    return ok(facility_out(facility))


@bp.post("/facilities/<facility_id>/suspend")
def suspend_facility_route(facility_id):
    require_auth([CREDIT_OFFICER])
    facility = get_facility(facility_id)
    data = body()
    v_string(data, "reason", max_len=500)
    if facility["status"] not in ("ACTIVE", "RESTRICTED"):
        raise ApiError("ERR_FACILITY_INVALID_STATE",
                       "Only an ACTIVE or RESTRICTED facility may be suspended.")
    suspend_facility(facility)
    return ok(facility_out(facility))


@bp.post("/facilities/<facility_id>/reinstate")
def reinstate_facility(facility_id):
    require_auth([CREDIT_OFFICER])
    facility = get_facility(facility_id)
    body()
    if facility["status"] != "SUSPENDED":
        raise ApiError("ERR_FACILITY_INVALID_STATE",
                       "Only a SUSPENDED facility may be reinstated.")
    fid = facility["id"]
    if (computed.open_margin_call_count(fid) > 0
            or computed.has_defaulted_call(fid)
            or computed.last_covenant_status(fid) not in CLEAN_COVENANT_STATUSES
            or computed.escalated_demand_count(fid) > 0):
        raise ApiError("ERR_OPEN_MARGIN_CALL",
                       "The facility is not clean enough to be reinstated.")
    facility["status"] = "ACTIVE"
    touch(facility)
    return ok(facility_out(facility))


# --------------------------------------------------------- advance-rate grid

@bp.post("/facilities/<facility_id>/product-advance-rates")
def create_product_rate(facility_id):
    require_auth([CREDIT_OFFICER])
    facility = get_facility(facility_id)
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING, "version": 1,
                                "facility_id": facility["id"]})
    product_code = v_enum(data, "product_code", PRODUCT_CODES)
    advance_rate = v_rate(data, "advance_rate", exclusive_min=0, maximum=1)
    wet_funding_allowed = v_bool(data, "wet_funding_allowed", default=True)
    wet_haircut = v_rate(data, "wet_haircut", required=False, minimum=0,
                         default=0.02)
    if frac(wet_haircut) >= frac(advance_rate):
        bad("Field 'wet_haircut' must be strictly less than 'advance_rate'.")
    dwell_limit_days = v_int(data, "dwell_limit_days", minimum=1, maximum=365)
    aging_step_days = v_int(data, "aging_step_days", required=False, minimum=1,
                            default=15)
    curtailment_step_rate = v_rate(data, "curtailment_step_rate", required=False,
                                   minimum=0, exclusive_max=1, default=0.005)
    product_sublimit_cents = v_int(data, "product_sublimit_cents", required=False,
                                   minimum=0, default=None)

    if facility["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_FACILITY_INVALID_STATE",
                       "Advance rate rows may only be added while the facility is "
                       "PENDING_APPROVAL.")
    if computed.rate_row_for(facility["id"], product_code) is not None:
        raise ApiError("ERR_DUPLICATE_ADVANCE_RATE",
                       "A rate row already exists for %s." % product_code)

    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "product_code": product_code,
        "advance_rate": advance_rate,
        "wet_funding_allowed": wet_funding_allowed,
        "wet_haircut": wet_haircut,
        "dwell_limit_days": dwell_limit_days,
        "aging_step_days": aging_step_days,
        "curtailment_step_rate": curtailment_step_rate,
        "product_sublimit_cents": product_sublimit_cents,
    })
    db.product_rates[row["id"]] = row
    return ok(product_rate_out(row), 201)


@bp.get("/facilities/<facility_id>/product-advance-rates")
def list_product_rates(facility_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    facility = get_facility(facility_id)
    rows = computed.facility_rate_rows(facility["id"])
    return list_response(rows, product_rate_out)


# ------------------------------------------------------------ custodian panel

@bp.post("/facilities/<facility_id>/custodians")
def create_custodian(facility_id):
    require_auth([CREDIT_OFFICER])
    facility = get_facility(facility_id)
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING, "version": 1,
                                "status": "APPROVED",
                                "facility_id": facility["id"]})
    custodian_name = v_string(data, "custodian_name", max_len=200)
    hours = v_int(data, "wet_receipt_deadline_hours", required=False, minimum=1,
                  maximum=240, default=72)
    if facility["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_NOT_ACTIVE",
                       "The facility must be ACTIVE to register a custodian.")
    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "custodian_name": custodian_name,
        "wet_receipt_deadline_hours": hours,
        "status": "APPROVED",
    })
    db.custodians[row["id"]] = row
    return ok(custodian_out(row), 201)


@bp.get("/facilities/<facility_id>/custodians")
def list_facility_custodians(facility_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST])
    facility = get_facility(facility_id)
    rows = filter_by(computed.facility_custodians(facility["id"]), "status")
    return list_response(rows, custodian_out)


# ------------------------------------------------------------ investor panel

@bp.post("/facilities/<facility_id>/investors")
def create_investor(facility_id):
    require_auth([CREDIT_OFFICER])
    facility = get_facility(facility_id)
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING, "version": 1,
                                "status": "PENDING_APPROVAL", "approved_at": None,
                                "exposure_cents": 0,
                                "facility_id": facility["id"]})
    investor_name = v_string(data, "investor_name", max_len=200)
    rating = v_enum(data, "counterparty_rating", COUNTERPARTY_RATINGS)
    limit_pct = v_rate(data, "concentration_limit_pct", exclusive_min=0, maximum=1)
    if facility["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_NOT_ACTIVE",
                       "The facility must be ACTIVE to add a take-out investor.")
    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "investor_name": investor_name,
        "counterparty_rating": rating,
        "concentration_limit_pct": limit_pct,
        "status": "PENDING_APPROVAL",
        "approved_at": None,
    })
    db.investors[row["id"]] = row
    return ok(investor_out(row), 201)


@bp.get("/facilities/<facility_id>/investors")
def list_facility_investors(facility_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST])
    facility = get_facility(facility_id)
    rows = filter_by(computed.facility_investors(facility["id"]), "status")
    return list_response(rows, investor_out)


# --------------------------------------------------------------- commitments

@bp.post("/facilities/<facility_id>/commitments")
def create_commitment(facility_id):
    require_auth([CREDIT_OFFICER])
    facility = get_facility(facility_id)
    data = body()
    # priority 5: body existence, resolving within the addressed facility
    investor_id = v_id(data, "investor_id")
    investor = get_investor(investor_id)
    if investor["facility_id"] != facility["id"]:
        raise ApiError("ERR_INVESTOR_NOT_FOUND",
                       "No such investor on this facility: %s" % investor_id)
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING, "version": 1,
                                "status": "OPEN", "allocated_amount_cents": 0,
                                "settled_amount_cents": 0,
                                "facility_id": facility["id"]})
    product_code = v_enum(data, "product_code", PRODUCT_CODES)
    committed = v_int(data, "committed_amount_cents", exclusive_min=0)
    price_pct = v_rate(data, "price_pct", exclusive_min=0.5, maximum=1.2)
    effective_on, effective_date = v_date(data, "effective_on")
    expires_on, expires_date = v_date(data, "expires_on")
    if expires_date < effective_date:
        bad("Field 'expires_on' must be on or after 'effective_on'.")

    if facility["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_NOT_ACTIVE",
                       "The facility must be ACTIVE to record a commitment.")
    if investor["status"] != "APPROVED":
        raise ApiError("ERR_INVESTOR_NOT_APPROVED",
                       "The named investor is not APPROVED.")

    # priority 37: the proposed window widened by two days on each side
    widened_start = effective_date - timedelta(days=COMMITMENT_BUFFER_DAYS)
    widened_end = expires_date + timedelta(days=COMMITMENT_BUFFER_DAYS)
    for other in computed.facility_commitments(facility["id"]):
        if other["investor_id"] != investor_id:
            continue
        if other["status"] not in ("OPEN", "PARTIALLY_ALLOCATED"):
            continue
        other_start = date.fromisoformat(other["effective_on"])
        other_end = date.fromisoformat(other["expires_on"])
        if widened_start <= other_end and other_start <= widened_end:
            raise ApiError("ERR_COMMITMENT_WINDOW_CONFLICT",
                           "The proposed window conflicts with an existing "
                           "commitment window for this investor.")

    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "investor_id": investor_id,
        "product_code": product_code,
        "committed_amount_cents": committed,
        "price_pct": price_pct,
        "effective_on": effective_on,
        "expires_on": expires_on,
        "status": "OPEN",
    })
    db.commitments[row["id"]] = row
    return ok(commitment_out(row), 201)


@bp.get("/facilities/<facility_id>/commitments")
def list_facility_commitments(facility_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    facility = get_facility(facility_id)
    rows = computed.facility_commitments(facility["id"])
    rows = filter_by(rows, "status")
    rows = filter_by(rows, "investor_id")
    return list_response(rows, commitment_out)


# -------------------------------------------------------------- margin calls

@bp.get("/facilities/<facility_id>/margin-calls")
def list_facility_margin_calls(facility_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    facility = get_facility(facility_id)
    rows = computed.facility_margin_calls(facility["id"])
    rows = filter_by(rows, "status")
    rows = filter_by(rows, "trigger_reason")
    return list_response(rows, margin_call_out)


# ------------------------------------------------------------ covenant tests

@bp.post("/facilities/<facility_id>/covenant-tests")
def create_covenant_test(facility_id):
    user_id, _role = require_auth([CREDIT_OFFICER, BORROWER])
    facility = get_facility(facility_id)
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING, "version": 1,
                                "facility_id": facility["id"]})
    period_end, period_date = v_date(data, "period_end")
    tnw = v_int(data, "tangible_net_worth_cents")
    liquidity = v_int(data, "liquidity_cents")
    net_income = v_int(data, "net_income_cents")

    existing = computed.facility_covenant_tests(facility["id"])
    stored_periods = set(t["period_end"] for t in existing)
    if existing and period_end not in stored_periods:
        latest = max(t["period_end"] for t in existing)
        if period_end < latest:
            bad("Field 'period_end' must be strictly later than every stored "
                "period_end on the facility.")
    # priority 30
    if period_end in stored_periods:
        raise ApiError("ERR_DUPLICATE_COVENANT_PERIOD",
                       "A covenant test already exists for %s." % period_end)

    priors = covenant.priors_newest_first(facility["id"])
    variant, metric, breach_codes, status = covenant.evaluate(
        facility, tnw, liquidity, net_income, priors)

    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "period_end": period_end,
        "tangible_net_worth_cents": tnw,
        "liquidity_cents": liquidity,
        "net_income_cents": net_income,
        "certified_by_user_id": user_id,
        "profitability_variant": variant,
        "profitability_metric_cents": metric,
        "breach_codes": breach_codes,
        "status": status,
        "waived_by_user_id": None,
    })
    db.covenant_tests[row["id"]] = row

    if status == "BREACH":
        restrict_if_active(facility)
        amount = floor_cents(frac(computed.outstanding_principal(facility["id"]))
                             * COVENANT_BREACH_PAYDOWN_PCT)
        create_margin_call(facility, None, "COVENANT_BREACH", amount)
        if computed.consecutive_breach_count(facility["id"]) >= 2 \
                and facility["status"] != "SUSPENDED":
            suspend_facility(facility)

    return ok(covenant_test_out(row), 201)


@bp.get("/facilities/<facility_id>/covenant-tests")
def list_covenant_tests(facility_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    facility = get_facility(facility_id)
    rows = computed.facility_covenant_tests(facility["id"])
    rows = filter_by(rows, "status")
    rows = sorted(rows, key=lambda t: (t["period_end"], t["created_at"], t["_seq"]))
    return list_response(rows, covenant_test_out)


# ---------------------------------------------------------------- aging run

@bp.post("/facilities/<facility_id>/aging-run")
def facility_aging_run(facility_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST])
    facility = get_facility(facility_id)
    body()
    summary = aging.run(facility)
    return ok(aging_run_out(summary))


# ------------------------------------------------- ledger and reconciliation

@bp.get("/facilities/<facility_id>/ledger-entries")
def list_facility_ledger(facility_id):
    user_id, role = require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    facility = get_facility(facility_id)
    own_facility(user_id, role, facility["id"])
    rows = computed.facility_ledger(facility["id"])
    rows = filter_by(rows, "entry_type")
    rows = filter_by(rows, "direction")
    advance_id = request.args.get("advance_id")
    if advance_id is not None and advance_id != "":
        rows = [r for r in rows if r["advance_id"] == advance_id]
    return list_response(rows, ledger_entry_out)


@bp.get("/facilities/<facility_id>/exposure-summary")
def facility_exposure_summary(facility_id):
    user_id, role = require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    facility = get_facility(facility_id)
    own_facility(user_id, role, facility["id"])
    return ok(exposure_summary_out(facility))
