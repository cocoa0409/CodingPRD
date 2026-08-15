"""Withdrawal cases: calculate, recalculate, nested obligation/offer lists."""

import db
import errors
import serializers
import clock
from flask import Blueprint, request
from middleware import (ALL_ROLES, get_auth, require_roles, parse_json_body,
                        parse_pagination)
from response import success_object, success_list
from services import calc
from services.term_days import parse_date
from routes.students import _validate_withdrawal_payload

bp = Blueprint("cases", __name__)


def _get_case_or_404(case_id):
    case = db.withdrawal_cases.get(case_id)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "withdrawal case not found")
    return case


@bp.get("/r2t4/withdrawal-cases")
def list_cases():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.withdrawal_cases.values())
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        items = [c for c in items if c["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.withdrawal_case(c) for c in page],
                        total, limit, offset)


@bp.get("/r2t4/withdrawal-cases/<case_id>")
def get_case(case_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(serializers.withdrawal_case(_get_case_or_404(case_id)))


@bp.post("/r2t4/withdrawal-cases/<case_id>/calculate")
def calculate_case(case_id):
    auth = get_auth()
    require_roles(auth, ["FinancialAidOfficer"])
    parse_json_body()
    case = _get_case_or_404(case_id)
    if case["status"] != "OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "only an OPEN withdrawal case can be calculated")
    calc.run_calculation(case, auth.user_id)
    return success_object(serializers.withdrawal_case(case))


@bp.post("/r2t4/withdrawal-cases/<case_id>/recalculate")
def recalculate_case(case_id):
    auth = get_auth()
    require_roles(auth, ["FinancialAidOfficer"])
    body = parse_json_body()
    case = _get_case_or_404(case_id)

    if case["status"] != "CALCULATED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "only a CALCULATED withdrawal case can be recalculated")

    expected = body.get("expected_withdrawal_case_version")
    if expected is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "expected_withdrawal_case_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "expected_withdrawal_case_version must be an integer")
    if expected != case["version"]:
        errors.raise_error(errors.ERR_STALE_VERSION,
                           "expected_withdrawal_case_version does not match the "
                           "current case version")

    for obligation in db.obligations.values():
        if (obligation["withdrawal_case_id"] == case["id"]
                and obligation["status"] == "RETURNED"):
            errors.raise_error(errors.ERR_RETURN_ALREADY_COMPLETED,
                               "an obligation of the case is already returned")
    for offer in db.offers.values():
        if (offer["withdrawal_case_id"] == case["id"]
                and offer["status"] == "ACCEPTED"):
            errors.raise_error(errors.ERR_OFFER_ALREADY_ACCEPTED,
                               "an offer of the case is already accepted")

    # Apply payload corrections, revalidated exactly as at withdrawal time.
    enrollment = db.enrollments[case["enrollment_id"]]
    term = db.terms[enrollment["term_id"]]

    merged = {
        "withdrawal_type": body.get("withdrawal_type", case["withdrawal_type"]),
        "notification_date": body.get("notification_date", case["notification_date"]),
        "last_attendance_date": body.get("last_attendance_date",
                                         case["last_attendance_date"]),
    }
    inputs = _validate_withdrawal_payload(enrollment, term, merged, auth)
    case["withdrawal_type"] = inputs["withdrawal_type"]
    case["notification_date"] = inputs["notification_date"]
    case["last_attendance_date"] = inputs["last_attendance_date"]

    calc.determine_dates_and_progress(case, term, clock.current_date())
    calc.compensate_case_artifacts(case)
    calc.run_calculation(case, auth.user_id)
    return success_object(serializers.withdrawal_case(case))


@bp.get("/r2t4/withdrawal-cases/<case_id>/obligations")
def list_case_obligations(case_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    _get_case_or_404(case_id)
    limit, offset = parse_pagination(request.args)
    items = [o for o in db.obligations.values()
             if o["withdrawal_case_id"] == case_id]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.obligation(o) for o in page],
                        total, limit, offset)


@bp.get("/r2t4/withdrawal-cases/<case_id>/offers")
def list_case_offers(case_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    _get_case_or_404(case_id)
    limit, offset = parse_pagination(request.args)
    items = [o for o in db.offers.values()
             if o["withdrawal_case_id"] == case_id]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.offer(o) for o in page],
                        total, limit, offset)
