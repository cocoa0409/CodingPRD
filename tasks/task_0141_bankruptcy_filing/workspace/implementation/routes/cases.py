"""Case endpoints — create, get, withdraw, file, schedule-341, conduct-341, dismiss, discharge."""

from flask import Blueprint, g

from middleware import require_auth, parse_json_body
from response import success
from services.case_engine import (
    create_case,
    file_case,
    get_case_or_404,
    withdraw_draft_case,
    schedule_341,
    conduct_341,
    dismiss_case,
    discharge_case,
    run_case_means_test,
    submit_schedule,
    check_occ,
)
from services.serializers import (
    serialize_case,
    serialize_schedule,
    serialize_means_test_result,
)
from db import store


cases_bp = Blueprint("cases", __name__)


@cases_bp.post("/cases")
@require_auth(allowed_roles=["Debtor"])
def create_case_route():
    body = parse_json_body(required_fields=["debtor_id", "chapter_requested"])
    with store.lock:
        case = create_case(
            debtor_id=body["debtor_id"],
            chapter_requested=body["chapter_requested"],
            acting_user_id=g.user_id,
        )
    return success(serialize_case(case), status=201)


@cases_bp.get("/cases/<case_id>")
@require_auth(allowed_roles=["Debtor", "Trustee", "Creditor", "Judge"])
def get_case_route(case_id: str):
    case = get_case_or_404(case_id)
    return success(serialize_case(case))


@cases_bp.delete("/cases/<case_id>")
@require_auth(allowed_roles=["Debtor"])
def delete_case_route(case_id: str):
    # DELETE may carry a body with `version` for OCC. Tolerate missing body.
    body = parse_json_body() or {}
    with store.lock:
        case = get_case_or_404(case_id)
        check_occ(case, body.get("version"))
        case = withdraw_draft_case(case, acting_user_id=g.user_id)
    return success(serialize_case(case))


@cases_bp.post("/cases/<case_id>/schedules")
@require_auth(allowed_roles=["Debtor"])
def submit_schedule_route(case_id: str):
    body = parse_json_body(required_fields=["schedule_type", "line_items"])
    with store.lock:
        case = get_case_or_404(case_id)
        check_occ(case, body.get("version"))
        schedule = submit_schedule(
            case,
            schedule_type=body["schedule_type"],
            line_items=body["line_items"],
            acting_user_id=g.user_id,
        )
    return success(serialize_schedule(schedule), status=201)


@cases_bp.post("/cases/<case_id>/means-test")
@require_auth(allowed_roles=["Debtor", "Trustee"])
def means_test_route(case_id: str):
    parse_json_body()  # tolerate empty body
    with store.lock:
        case = get_case_or_404(case_id)
        result = run_case_means_test(case)
    return success(serialize_means_test_result(result), status=201)


@cases_bp.post("/cases/<case_id>/file")
@require_auth(allowed_roles=["Debtor"])
def file_case_route(case_id: str):
    body = parse_json_body()
    with store.lock:
        case = get_case_or_404(case_id)
        check_occ(case, body.get("version"))
        case = file_case(case, acting_user_id=g.user_id)
    return success(serialize_case(case))


@cases_bp.post("/cases/<case_id>/schedule-341")
@require_auth(allowed_roles=["Trustee"])
def schedule_341_route(case_id: str):
    body = parse_json_body(required_fields=["meeting_date"])
    with store.lock:
        case = get_case_or_404(case_id)
        check_occ(case, body.get("version"))
        case = schedule_341(case, meeting_date_iso=body["meeting_date"])
    return success(serialize_case(case))


@cases_bp.post("/cases/<case_id>/conduct-341")
@require_auth(allowed_roles=["Trustee"])
def conduct_341_route(case_id: str):
    body = parse_json_body()
    with store.lock:
        case = get_case_or_404(case_id)
        check_occ(case, body.get("version"))
        case = conduct_341(case)
    return success(serialize_case(case))


@cases_bp.post("/cases/<case_id>/dismiss")
@require_auth(allowed_roles=["Trustee"])
def dismiss_case_route(case_id: str):
    body = parse_json_body()
    with store.lock:
        case = get_case_or_404(case_id)
        check_occ(case, body.get("version"))
        case = dismiss_case(case)
    return success(serialize_case(case))


@cases_bp.post("/cases/<case_id>/discharge")
@require_auth(allowed_roles=["Judge"])
def discharge_case_route(case_id: str):
    body = parse_json_body()
    with store.lock:
        case = get_case_or_404(case_id)
        check_occ(case, body.get("version"))
        case = discharge_case(case)
    return success(serialize_case(case))
