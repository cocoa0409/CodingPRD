"""Clock control, loan files, appraisers, companies and panel memberships."""

from flask import Blueprint

import db
import response
import validate as V
from errors import fail
from middleware import (ALL_ROLES, ROLE_AMC_COORDINATOR, ROLE_APPRAISER,
                        ROLE_BORROWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                        ROLE_DESK_REVIEWER, ROLE_LOAN_OFFICER, require_roles)
from routes.common import (PREFIX, active_membership, body_fk, filter_equals,
                           find_amc, find_appraiser, find_loan, find_membership)
from services import constants as C
from services import loans as loan_svc
from services import panel as panel_svc

bp = Blueprint("reference", __name__)


# ----------------------------------------------------------------- the clock
@bp.post(PREFIX + "/_clock/set_current_utc")
def set_clock():
    require_roles(*ALL_ROLES)
    data = V.body()
    db.set_clock(V.req_dt(data, "current_utc"))
    return response.empty_ok()


# ------------------------------------------------------------------ loan files
@bp.post(PREFIX + "/loan-files")
def create_loan_file():
    require_roles(ROLE_LOAN_OFFICER)
    data = V.body()
    loan_number = V.req_str(data, "loan_number", min_len=1, max_len=32)
    purpose = V.req_enum(data, "loan_purpose", C.LOAN_PURPOSES)
    market_type = V.req_enum(data, "market_type", C.MARKET_TYPES)
    risk_tier = V.req_enum(data, "risk_tier", C.RISK_TIERS)
    loan_amount = V.req_int(data, "loan_amount_cents", positive=True)
    if purpose == "PURCHASE":
        contract_price = V.req_int(data, "contract_price_cents", positive=True)
    else:
        if V.present(data, "contract_price_cents"):
            fail("ERR_INVALID_REQUEST",
                 "contract_price_cents must be null for a refinance.")
        contract_price = None
    borrower_name = V.req_str(data, "borrower_display_name")
    for existing in db.loan_files.values():
        if existing["loan_number"] == loan_number:
            fail("ERR_INVALID_REQUEST", "loan_number is already in use.")

    record = db.make_record({
        "loan_number": loan_number,
        "loan_purpose": purpose,
        "market_type": market_type,
        "risk_tier": risk_tier,
        "loan_amount_cents": loan_amount,
        "contract_price_cents": contract_price,
        "borrower_display_name": borrower_name,
        "underwriting_status": "SUBMITTED",
        "collateral_status": "PENDING_APPRAISAL",
        "value_of_record_appraisal_id": None,
        "current_appraised_value_cents": None,
        "effective_value_cents": None,
        "ltv_bps": None,
        "decision_impact": None,
        "rov_request_count": 0,
    })
    db.loan_files[record["id"]] = record
    return response.created(record)


@bp.get(PREFIX + "/loan-files/<loan_id>")
def get_loan_file(loan_id):
    require_roles(ROLE_LOAN_OFFICER, ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER,
                  ROLE_COMPLIANCE, ROLE_BORROWER)
    return response.ok(find_loan(loan_id))


@bp.get(PREFIX + "/loan-files")
def list_loan_files():
    require_roles(ROLE_LOAN_OFFICER, ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER,
                  ROLE_COMPLIANCE)
    rows = db.ordered(db.loan_files)
    rows = filter_equals(rows, "underwriting_status")
    rows = filter_equals(rows, "collateral_status")
    rows = filter_equals(rows, "risk_tier")
    return response.page(rows)


@bp.post(PREFIX + "/loan-files/<loan_id>/underwriting-status")
def move_underwriting_status(loan_id):
    require_roles(ROLE_LOAN_OFFICER)
    loan = find_loan(loan_id)
    data = V.body()
    target = V.req_enum(data, "target_status", C.UNDERWRITING_STATUSES)
    V.opt_str(data, "note")

    if loan_svc.loan_quarantined(loan):
        fail("ERR_BIAS_QUARANTINE_ACTIVE")

    current = loan["underwriting_status"]
    if target == "CONDITIONALLY_APPROVED":
        if current != "SUBMITTED":
            fail("ERR_INVALID_STATE")
    elif target == "CLOSED":
        if current != "CONDITIONALLY_APPROVED":
            fail("ERR_INVALID_STATE")
        if loan["collateral_status"] not in ("VALUE_ACCEPTED", "VALUE_REVISED"):
            fail("ERR_INVALID_STATE")
        for rov in db.rov_requests.values():
            if (rov["loan_file_id"] == loan["id"]
                    and rov["status"] in ("INTAKE", "AWAITING_APPRAISER")):
                fail("ERR_INVALID_STATE")
    elif target == "WITHDRAWN":
        if current not in ("SUBMITTED", "CONDITIONALLY_APPROVED", "SUSPENDED"):
            fail("ERR_INVALID_STATE")
    else:
        fail("ERR_INVALID_STATE")

    loan["underwriting_status"] = target
    db.bump(loan)

    if target == "WITHDRAWN":
        _cancel_pending_orders(loan)
    return response.ok(loan)


def _cancel_pending_orders(loan):
    appraisal_ids = set(a["id"] for a in db.appraisals.values()
                        if a["loan_file_id"] == loan["id"])
    for order in db.ordered(db.escalation_orders):
        if order["status"] != "PENDING_ASSIGNMENT":
            continue
        review = db.desk_reviews.get(order["desk_review_id"])
        if review is None or review["appraisal_id"] not in appraisal_ids:
            continue
        order["status"] = "CANCELLED"
        db.bump(order)
        if review["status"] == "ESCALATED":
            review["status"] = "SUBMITTED"
            db.bump(review)
        appraisal = db.appraisals.get(review["appraisal_id"])
        if appraisal is not None and appraisal["review_status"] == "ESCALATED":
            appraisal["review_status"] = "IN_DESK_REVIEW"
            db.bump(appraisal)


# ------------------------------------------------------------------ appraisers
@bp.post(PREFIX + "/appraisers")
def create_appraiser():
    require_roles(ROLE_CHIEF_APPRAISER)
    data = V.body()
    full_name = V.req_str(data, "full_name")
    license_number = V.req_str(data, "license_number")
    license_state = V.req_state_code(data, "license_state")
    panel_status = V.opt_enum(data, "panel_status", C.APPRAISER_PANEL_STATUSES, "ACTIVE")
    for existing in db.appraisers.values():
        if existing["license_number"] == license_number:
            fail("ERR_INVALID_REQUEST", "license_number is already in use.")

    record = db.make_record({
        "full_name": full_name,
        "license_number": license_number,
        "license_state": license_state,
        "panel_status": panel_status,
        "probation_started_at": None,
        "removal_reason": None,
        "performance_score_bps": C.BASE_PERFORMANCE_SCORE_BPS,
        "lifetime_performance_score_bps": C.BASE_PERFORMANCE_SCORE_BPS,
        "revision_rate_bps": 0,
        "total_appraisal_count": 0,
        "substantiated_bias_count": 0,
        "sla_miss_count": 0,
        "open_assignment_count": 0,
        "completed_assignment_count": 0,
        "panel_membership_count": 0,
    })
    db.appraisers[record["id"]] = record
    return response.created(record)


@bp.get(PREFIX + "/appraisers/<appraiser_id>")
def get_appraiser(appraiser_id):
    require_roles(ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_DESK_REVIEWER,
                  ROLE_AMC_COORDINATOR, ROLE_APPRAISER)
    return response.ok(find_appraiser(appraiser_id))


@bp.get(PREFIX + "/appraisers")
def list_appraisers():
    require_roles(ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_DESK_REVIEWER,
                  ROLE_AMC_COORDINATOR)
    rows = db.ordered(db.appraisers)
    rows = filter_equals(rows, "panel_status")
    rows = filter_equals(rows, "license_state")
    return response.page(rows)


@bp.post(PREFIX + "/appraisers/<appraiser_id>/panel-review")
def panel_review(appraiser_id):
    require_roles(ROLE_CHIEF_APPRAISER)
    appraiser = find_appraiser(appraiser_id)
    data = V.body()
    expected = V.req_int(data, "expected_appraiser_version")
    action = V.req_enum(data, "panel_action", C.PANEL_ACTIONS)
    removal_reason = V.opt_str(data, "removal_reason")
    V.opt_str(data, "note")

    if expected != appraiser["version"]:
        fail("ERR_STALE_VERSION")

    status = appraiser["panel_status"]
    if action == "MONITOR":
        if status not in ("ACTIVE", "PROBATION", "SUSPENDED"):
            fail("ERR_PANEL_ACTION_NOT_PERMITTED")
        panel_svc.recompute_performance(appraiser)
    elif action == "REINSTATE":
        if status == "PROBATION":
            if appraiser["performance_score_bps"] < C.PROBATION_THRESHOLD_BPS:
                fail("ERR_PANEL_ACTION_NOT_PERMITTED")
            appraiser["panel_status"] = "ACTIVE"
            appraiser["probation_started_at"] = None
        elif status == "SUSPENDED":
            if appraiser["performance_score_bps"] < C.SUSPENSION_THRESHOLD_BPS:
                fail("ERR_PANEL_ACTION_NOT_PERMITTED")
            appraiser["panel_status"] = "PROBATION"
            appraiser["probation_started_at"] = db.now()
        else:
            fail("ERR_PANEL_ACTION_NOT_PERMITTED")
    else:
        if status != "SUSPENDED":
            fail("ERR_PANEL_ACTION_NOT_PERMITTED")
        if appraiser["performance_score_bps"] >= C.REMOVAL_THRESHOLD_BPS:
            fail("ERR_PANEL_ACTION_NOT_PERMITTED")
        if removal_reason is None or removal_reason == "":
            fail("ERR_PANEL_ACTION_NOT_PERMITTED")
        appraiser["panel_status"] = "REMOVED"
        appraiser["removal_reason"] = removal_reason
        for membership in db.ordered(db.panel_memberships):
            if membership["appraiser_id"] == appraiser["id"] and membership["status"] == "ACTIVE":
                membership["status"] = "SUPERSEDED"
                db.bump(membership)
        panel_svc.flag_all_orders_for_removal(appraiser["id"])
        panel_svc.refresh_appraiser_counters(appraiser)

    db.bump(appraiser)
    return response.ok(appraiser)


# ------------------------------------------------------------------- companies
@bp.post(PREFIX + "/amcs")
def create_amc():
    require_roles(ROLE_CHIEF_APPRAISER)
    data = V.body()
    name = V.req_str(data, "name")
    sla_hours = V.opt_int(data, "sla_response_hours", default=72, minimum=1)
    capacity = V.opt_int(data, "concurrent_dispute_capacity", default=2, minimum=1)
    budget = V.opt_int(data, "escalation_budget_cents", default=500000, minimum=0)
    panel_status = V.opt_enum(data, "panel_status", C.AMC_PANEL_STATUSES, "ACTIVE")
    for existing in db.amcs.values():
        if existing["name"] == name:
            fail("ERR_INVALID_REQUEST", "name is already in use.")

    record = db.make_record({
        "name": name,
        "sla_response_hours": sla_hours,
        "concurrent_dispute_capacity": capacity,
        "escalation_budget_cents": budget,
        "panel_status": panel_status,
        "ytd_escalation_spend_cents": 0,
        "sla_breach_count": 0,
        "open_dispute_count": 0,
    })
    db.amcs[record["id"]] = record
    return response.created(record)


@bp.get(PREFIX + "/amcs/<amc_id>")
def get_amc(amc_id):
    require_roles(ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_DESK_REVIEWER,
                  ROLE_AMC_COORDINATOR)
    return response.ok(find_amc(amc_id))


@bp.get(PREFIX + "/amcs")
def list_amcs():
    require_roles(ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_DESK_REVIEWER)
    rows = db.ordered(db.amcs)
    rows = filter_equals(rows, "panel_status")
    return response.page(rows)


# ---------------------------------------------------------- panel memberships
@bp.post(PREFIX + "/panel-memberships")
def create_membership():
    require_roles(ROLE_CHIEF_APPRAISER)
    data = V.body()
    appraiser = body_fk(data, "appraiser_id", db.appraisers, "ERR_APPRAISER_NOT_FOUND")
    amc = body_fk(data, "amc_id", db.amcs, "ERR_AMC_NOT_FOUND")
    V.req_str(data, "appraiser_id")
    V.req_str(data, "amc_id")
    coverage_state = V.req_state_code(data, "coverage_state")
    tier = V.req_enum(data, "tier", C.MEMBERSHIP_TIERS)
    expected = V.req_int(data, "expected_appraiser_version")

    if expected != appraiser["version"]:
        fail("ERR_STALE_VERSION")
    if active_membership(appraiser["id"], amc["id"], coverage_state) is not None:
        fail("ERR_DUPLICATE_PANEL_MEMBERSHIP")

    record = db.make_record({
        "appraiser_id": appraiser["id"],
        "amc_id": amc["id"],
        "coverage_state": coverage_state,
        "tier": tier,
        "status": "ACTIVE",
    })
    db.panel_memberships[record["id"]] = record
    db.bump(appraiser)
    panel_svc.refresh_appraiser_counters(appraiser)
    return response.created(record)


@bp.get(PREFIX + "/panel-memberships/<membership_id>")
def get_membership(membership_id):
    require_roles(ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_AMC_COORDINATOR)
    return response.ok(find_membership(membership_id))


@bp.get(PREFIX + "/panel-memberships")
def list_memberships():
    require_roles(ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_AMC_COORDINATOR,
                  ROLE_DESK_REVIEWER)
    rows = db.ordered(db.panel_memberships)
    rows = filter_equals(rows, "appraiser_id")
    rows = filter_equals(rows, "amc_id")
    rows = filter_equals(rows, "status")
    return response.page(rows)
