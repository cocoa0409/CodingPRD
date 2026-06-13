"""COBRA-enrollment endpoints: get/list, certificates, disability extension,
early termination, subsidy grant."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_role
from models import (
    _common, serialize, touch, ENROLLMENT_FIELDS, CERTIFICATE_FIELDS,
    SUBSIDY_FIELDS,
)
from response import object_response, array_response
from timeutil import (
    add_days, add_months, parse_year_month, year_month_index,
)
from services import lifecycle
from services.ledger import recompute_invoice_subsidy, recompute_account
from services.lookup import (
    get_or_404, require_body, require_enum, require_datetime,
    require_number, require_coverage_month, paginate, sorted_by_creation,
)

bp = Blueprint("enrollments", __name__)


@bp.get("/enrollments/<eid>")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def get_enrollment(eid):
    enr = get_or_404(store.enrollments, eid)
    return object_response(serialize(enr, ENROLLMENT_FIELDS))


@bp.get("/enrollments")
@require_role({"PlanAdministrator", "BillingAgent"})
def list_enrollments():
    beneficiary_id = request.args.get("beneficiary_id")
    notice_id = request.args.get("notice_id")
    event_id = request.args.get("event_id")
    items = list(store.enrollments.values())
    if beneficiary_id is not None:
        items = [e for e in items if e["beneficiary_id"] == beneficiary_id]
    if notice_id is not None:
        items = [e for e in items if e["notice_id"] == notice_id]
    if event_id is not None:
        items = [e for e in items if e["event_id"] == event_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(e, ENROLLMENT_FIELDS) for e in page],
                          limit, offset, total)


@bp.get("/enrollments/<eid>/certificates")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def list_enrollment_certificates(eid):
    get_or_404(store.enrollments, eid)
    items = [c for c in store.certificates.values() if c["enrollment_id"] == eid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(c, CERTIFICATE_FIELDS) for c in page],
                          limit, offset, total)


@bp.post("/enrollments/<eid>/apply-disability-extension")
@require_role({"PlanAdministrator"})
def apply_disability_extension(eid):
    enr = get_or_404(store.enrollments, eid)
    body = require_body()
    determination_date = require_datetime(body, "determination_date")

    # PRD §3.8 ordering: window invalidity (ERR_DISABILITY_WINDOW_INVALID,
    # priority 9) before extension-not-applicable (priority 10).
    coverage_start = enr["coverage_start_date"]
    now = store.now()
    window_end = add_days(coverage_start, 60)
    if determination_date < coverage_start or determination_date > window_end:
        raise ApiError("ERR_DISABILITY_WINDOW_INVALID",
                       "Determination date outside the first 60 days of coverage")
    if now > enr["scheduled_end_date"]:
        raise ApiError("ERR_DISABILITY_WINDOW_INVALID",
                       "Disability extension applied after the scheduled end")
    if enr["base_max_months"] != 18:
        raise ApiError("ERR_EXTENSION_NOT_APPLICABLE",
                       "Only 18-month enrollments may be extended")
    lifecycle.apply_disability_extension(enr)
    return object_response(serialize(enr, ENROLLMENT_FIELDS))


@bp.post("/enrollments/<eid>/terminate-early")
@require_role({"PlanAdministrator"})
def terminate_early(eid):
    enr = get_or_404(store.enrollments, eid)
    body = require_body()
    # Body-shape required-field presence (priority 5) precedes state (priority
    # 6); the reason VALUE validity is the dedicated ERR_INVALID_TERMINATION_
    # REASON at priority 11 (after state).
    reason = body.get("reason")
    if reason is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: reason")
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Enrollment is not ACTIVE")
    valid_reasons = {"OTHER_GROUP_COVERAGE", "MEDICARE_ENTITLEMENT", "PLAN_TERMINATED"}
    if reason not in valid_reasons:
        raise ApiError("ERR_INVALID_TERMINATION_REASON",
                       "Termination reason not permitted")
    lifecycle.terminate_early(enr, reason)
    return object_response(serialize(enr, ENROLLMENT_FIELDS))


@bp.post("/enrollments/<eid>/subsidies")
@require_role({"PlanAdministrator"})
def grant_subsidy(eid):
    enr = get_or_404(store.enrollments, eid)
    body = require_body()
    subsidy_pct = require_number(body, "subsidy_pct", minimum=0, maximum=1.0,
                                 min_inclusive=False, max_inclusive=True)
    start_month = require_coverage_month(body, "start_month")
    end_month = require_coverage_month(body, "end_month")

    # Range validity (priority 15, 409): start <= end and within coverage
    # interval [coverage_start month, scheduled_end month].
    sy, sm = parse_year_month(start_month)
    ey, em = parse_year_month(end_month)
    if year_month_index(sy, sm) > year_month_index(ey, em):
        raise ApiError("ERR_INVALID_SUBSIDY_RANGE", "start_month after end_month")
    cs = enr["coverage_start_date"]
    se = enr["scheduled_end_date"]
    interval_lo = year_month_index(cs.year, cs.month)
    interval_hi = year_month_index(se.year, se.month)
    if year_month_index(sy, sm) < interval_lo or year_month_index(ey, em) > interval_hi:
        raise ApiError("ERR_INVALID_SUBSIDY_RANGE",
                       "Subsidy range outside the enrollment coverage interval")

    subsidy = {
        "enrollment_id": enr["id"],
        "subsidy_pct": subsidy_pct,
        "start_month": start_month,
        "end_month": end_month,
        "status": "ACTIVE",
    }
    _common(subsidy)
    store.subsidies[subsidy["id"]] = subsidy

    # Recompute subsidy/beneficiary_owed on OPEN invoices in range, then the
    # account accumulators.
    _recompute_open_invoices_in_range(enr, sy, sm, ey, em)
    return object_response(serialize(subsidy, SUBSIDY_FIELDS), status=201)


def _recompute_open_invoices_in_range(enr, sy, sm, ey, em):
    account = None
    for acc in store.accounts.values():
        if acc["enrollment_id"] == enr["id"]:
            account = acc
            break
    if account is None:
        return
    lo = year_month_index(sy, sm)
    hi = year_month_index(ey, em)
    for inv in store.invoices.values():
        if inv["account_id"] != account["id"]:
            continue
        if inv["status"] != "OPEN":
            continue
        iy, im = parse_year_month(inv["coverage_month"])
        if lo <= year_month_index(iy, im) <= hi:
            recompute_invoice_subsidy(enr, inv)
    recompute_account(account, enr)
