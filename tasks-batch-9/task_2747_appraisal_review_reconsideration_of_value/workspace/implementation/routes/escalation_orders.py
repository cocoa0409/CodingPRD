"""Escalation order staffing, completion and cancellation."""

from flask import Blueprint

import db
import response
import validate as V
from errors import fail
from middleware import (ROLE_AMC_COORDINATOR, ROLE_APPRAISER, ROLE_CHIEF_APPRAISER,
                        ROLE_COMPLIANCE, ROLE_DESK_REVIEWER, require_owner,
                        require_roles)
from routes.common import (PREFIX, active_membership, body_fk, filter_equals,
                           find_loan, find_order)
from services import escalation as esc_svc
from services import loans as loan_svc
from services import panel as panel_svc
from services import revision as revision_svc

bp = Blueprint("escalation_orders", __name__)


@bp.get(PREFIX + "/escalation-orders/<order_id>")
def get_order(order_id):
    require_roles(ROLE_CHIEF_APPRAISER, ROLE_DESK_REVIEWER, ROLE_AMC_COORDINATOR,
                  ROLE_COMPLIANCE, ROLE_APPRAISER)
    return response.ok(find_order(order_id))


@bp.get(PREFIX + "/escalation-orders")
def list_orders():
    require_roles(ROLE_CHIEF_APPRAISER, ROLE_DESK_REVIEWER, ROLE_AMC_COORDINATOR,
                  ROLE_COMPLIANCE)
    rows = db.ordered(db.escalation_orders)
    rows = filter_equals(rows, "desk_review_id")
    rows = filter_equals(rows, "assigned_appraiser_id")
    rows = filter_equals(rows, "amc_id")
    rows = filter_equals(rows, "status")
    return response.page(rows)


@bp.post(PREFIX + "/escalation-orders/<order_id>/assign")
def assign_order(order_id):
    require_roles(ROLE_CHIEF_APPRAISER)
    order = find_order(order_id)
    data = V.body()
    candidate = body_fk(data, "assigned_appraiser_id", db.appraisers,
                        "ERR_APPRAISER_NOT_FOUND")
    V.req_str(data, "assigned_appraiser_id")

    has_start = V.present(data, "inspection_window_start")
    has_end = V.present(data, "inspection_window_end")
    if not has_start and not has_end:
        fail("ERR_INVALID_REQUEST", "An inspection window is required.")
    window_start = V.opt_dt(data, "inspection_window_start")
    window_end = V.opt_dt(data, "inspection_window_end")

    if order["status"] not in ("PENDING_ASSIGNMENT", "REASSIGNMENT_REQUIRED"):
        fail("ERR_ESCALATION_NOT_PENDING")

    review = db.desk_reviews.get(order["desk_review_id"])
    appraisal = db.appraisals.get(review["appraisal_id"]) if review else None

    if active_membership(candidate["id"], order["amc_id"]) is None:
        fail("ERR_APPRAISER_NOT_ON_PANEL")

    if order["escalation_type"] == "SECOND_APPRAISAL":
        if candidate["panel_status"] != "ACTIVE":
            fail("ERR_APPRAISER_INELIGIBLE")
    else:
        if candidate["panel_status"] not in ("ACTIVE", "PROBATION"):
            fail("ERR_APPRAISER_INELIGIBLE")
    if appraisal is not None and candidate["id"] == appraisal["appraiser_id"]:
        fail("ERR_APPRAISER_INELIGIBLE")

    if window_start is None or window_end is None or window_start >= window_end:
        fail("ERR_INVALID_WINDOW")

    if esc_svc.window_conflict(candidate["id"], window_start, window_end,
                               exclude_order_id=order["id"]):
        fail("ERR_INSPECTION_WINDOW_CONFLICT")

    base, surcharge, discount_bps, total = esc_svc.price(
        order["escalation_type"], order["due_at"], db.now())

    amc = db.amcs.get(order["amc_id"])
    prior_spend = panel_svc.escalation_spend(order["amc_id"], exclude_order_id=order["id"])
    if amc is not None and prior_spend + total > amc["escalation_budget_cents"]:
        fail("ERR_ESCALATION_BUDGET_EXCEEDED")

    prior_assignee_id = order.get("assigned_appraiser_id")
    order["assigned_appraiser_id"] = candidate["id"]
    order["inspection_window_start"] = window_start
    order["inspection_window_end"] = window_end
    order["base_fee_cents"] = base
    order["rush_surcharge_cents"] = surcharge
    order["discount_pct_bps"] = discount_bps
    order["total_cost_cents"] = total
    order["status"] = "ASSIGNED"
    db.bump(order)

    if prior_assignee_id is not None and prior_assignee_id != candidate["id"]:
        prior = db.appraisers.get(prior_assignee_id)
        if prior is not None:
            panel_svc.refresh_appraiser_counters(prior)
    panel_svc.refresh_appraiser_counters(candidate)
    if amc is not None:
        panel_svc.refresh_amc_counters(amc)
    return response.ok(order)


@bp.post(PREFIX + "/escalation-orders/<order_id>/complete")
def complete_order(order_id):
    user_id, _ = require_roles(ROLE_AMC_COORDINATOR)
    order = find_order(order_id)
    require_owner(order["amc_id"], user_id)
    data = V.body()
    resulting_value = V.req_int(data, "resulting_value_cents", positive=True)
    documentation_note = V.req_str(data, "documentation_note")

    if order["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE")

    review = db.desk_reviews.get(order["desk_review_id"])
    appraisal = db.appraisals.get(review["appraisal_id"]) if review else None
    loan = find_loan(appraisal["loan_file_id"]) if appraisal else None

    if appraisal is not None and loan_svc.appraisal_quarantined(appraisal):
        fail("ERR_BIAS_QUARANTINE_ACTIVE")

    if appraisal is not None and revision_svc.exceeds_cap(appraisal, resulting_value):
        fail("ERR_REVISION_EXCEEDS_CAP")

    order["status"] = "COMPLETED"
    order["resulting_value_cents"] = resulting_value
    order["documentation_note"] = documentation_note
    db.bump(order)

    if review is not None and review["status"] == "ESCALATED":
        review["status"] = "CLOSED"
        db.bump(review)

    if appraisal is not None:
        appraisal["review_status"] = "VALUE_REVISED"
        db.bump(appraisal)
        if loan is not None:
            loan["value_of_record_appraisal_id"] = appraisal["id"]
            loan["collateral_status"] = "VALUE_REVISED"
            db.bump(loan)
        revision_svc.write_revision(appraisal, loan, order["escalation_type"],
                                    order["id"], resulting_value, documentation_note)
        author = db.appraisers.get(appraisal["appraiser_id"])
        if author is not None:
            panel_svc.recompute_performance(author)

    assignee = db.appraisers.get(order.get("assigned_appraiser_id"))
    if assignee is not None:
        panel_svc.refresh_appraiser_counters(assignee)
    amc = db.amcs.get(order["amc_id"])
    if amc is not None:
        panel_svc.refresh_amc_counters(amc)
    return response.ok(order)


@bp.post(PREFIX + "/escalation-orders/<order_id>/cancel")
def cancel_order(order_id):
    require_roles(ROLE_CHIEF_APPRAISER)
    order = find_order(order_id)
    data = V.body()
    cancel_reason = V.req_str(data, "cancel_reason")

    if order["status"] not in ("PENDING_ASSIGNMENT", "ASSIGNED", "REASSIGNMENT_REQUIRED"):
        fail("ERR_INVALID_STATE")

    was_staffed = order["status"] in ("ASSIGNED", "REASSIGNMENT_REQUIRED")
    order["status"] = "CANCELLED"
    order["cancel_reason"] = cancel_reason
    db.bump(order)

    review = db.desk_reviews.get(order["desk_review_id"])
    if review is not None and review["status"] == "ESCALATED":
        review["status"] = "SUBMITTED"
        db.bump(review)
        appraisal = db.appraisals.get(review["appraisal_id"])
        if appraisal is not None and appraisal["review_status"] == "ESCALATED":
            appraisal["review_status"] = "IN_DESK_REVIEW"
            db.bump(appraisal)

    if was_staffed:
        assignee = db.appraisers.get(order.get("assigned_appraiser_id"))
        if assignee is not None:
            panel_svc.refresh_appraiser_counters(assignee)
        amc = db.amcs.get(order["amc_id"])
        if amc is not None:
            panel_svc.refresh_amc_counters(amc)
    return response.ok(order)
