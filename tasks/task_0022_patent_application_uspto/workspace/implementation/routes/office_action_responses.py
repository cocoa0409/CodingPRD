"""Office action responses."""

from flask import Blueprint, request

from db import db, new_id
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.body import get_json_body, require_string, require_int
from services.calc import extension_fee
from services.dateutil import add_months
from services.pagination import parse_pagination, slice_sorted
from services.serialize import office_action_response_to_wire
from services.application_svc import (
    APP_TERMINAL_STATES,
    bump_application,
    bump_office_action,
)


bp = Blueprint("office_action_responses", __name__)


def _validate_amendment_range(claim_amendment_count: int):
    """VAL-CLAIMS-RANGE applied to claim_amendment_count (the response's local count)."""
    if not (1 <= int(claim_amendment_count) <= 500):
        raise_api(
            "ERR_CLAIM_COUNTS_INVALID",
            "claim_amendment_count must be in [1, 500]",
        )


@bp.route("/office-action-responses", methods=["POST"])
@require_roles("Applicant")
def create_response(_user_id, _role):
    body = get_json_body()
    oa_id = require_string(body, "office_action_id")
    extension_months = require_int(body, "extension_months_requested")
    claim_amendment_count = require_int(body, "claim_amendment_count")

    # Priority 5: FK existence
    oa = db.office_actions.get(oa_id)
    if oa is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", f"OfficeAction {oa_id} not found")
    app = db.applications.get(oa["application_id"])
    if app is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND",
            f"Application {oa['application_id']} not found",
        )

    # Priority 7: terminal lockdown
    if oa["status"] in {"RESPONDED", "EXPIRED", "WITHDRAWN"}:
        raise_api(
            "ERR_TERMINAL_STATE",
            f"OfficeAction status {oa['status']} is terminal",
        )
    if app["status"] in APP_TERMINAL_STATES or app["status"] == "ISSUED":
        raise_api(
            "ERR_TERMINAL_STATE",
            f"Application status {app['status']} is terminal",
        )

    # Priority 6: state
    if oa["status"] != "OUTSTANDING":
        raise_api(
            "ERR_INVALID_STATE",
            f"OfficeAction must be OUTSTANDING (current: {oa['status']})",
        )
    if app["status"] != "OFFICE_ACTION_OUTSTANDING":
        raise_api(
            "ERR_INVALID_STATE",
            f"Application must be OFFICE_ACTION_OUTSTANDING (current: {app['status']})",
        )
    if oa["action_type"] == "NOTICE_OF_ALLOWANCE":
        # NOAs are responded via issue-fee payment, not OA-response.
        raise_api(
            "ERR_INVALID_STATE",
            "NOTICE_OF_ALLOWANCE actions cannot be responded to",
        )

    # Priority 18: VAL-EXTENSION-MONTHS — checked BEFORE EXTENSION_FEE
    if extension_months not in (0, 1, 2, 3):
        raise_api(
            "ERR_EXTENSION_MONTHS_INVALID",
            "extension_months_requested must be in {0, 1, 2, 3}",
        )

    # Priority 16: VAL-CLAIMS-RANGE applies to claim_amendment_count
    _validate_amendment_range(claim_amendment_count)

    # Compute applicant for entity_size
    applicant = db.applicants.get(app["applicant_id"])
    if applicant is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND", "Applicant for this application was not found"
        )

    # Timeliness check (deadline + extension, capped at maximum_due_date)
    now = db.current_utc_dt()
    extended_due = add_months(oa["shortened_due_date"], extension_months)
    timely = (
        now <= extended_due
        and extended_due <= oa["maximum_due_date"]
    )
    # If extension would push past the maximum, the response is REJECTED_LATE.
    # The scaffold makes ACCEPTED the only allowed creation status — REJECTED_LATE
    # rejects creation with state error per the AC transition predicate.
    if not timely:
        raise_api(
            "ERR_INVALID_STATE",
            "Response is not timely (past shortened_due_date + extension or past maximum_due_date)",
        )

    expected_extension_fee = extension_fee(extension_months, applicant["entity_size"])

    # Per scaffold: "Payment with payment_category=EXTENSION and amount_cents == ...
    # POSTED in the same transaction iff extension_months_requested > 0".
    # We do NOT require the client to pre-post an EXTENSION fee here — the
    # extension_fee_cents is computed and recorded on the response itself.
    # Clients that wish to record an actual fee payment use POST /fee-payments
    # with payment_category=EXTENSION; the expected amount is the same value
    # computed below by §1.3 EXTENSION_FEE.

    # ---- Side effects ----
    resp_id = new_id()
    response = {
        "id": resp_id,
        "office_action_id": oa_id,
        "response_filed_at": now,
        "extension_months_requested": extension_months,
        "claim_amendment_count": claim_amendment_count,
        "extension_fee_cents": expected_extension_fee,
        "response_status": "ACCEPTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.office_action_responses[resp_id] = response

    oa["status"] = "RESPONDED"
    bump_office_action(oa)

    app["status"] = "RESPONSE_FILED"
    bump_application(app)

    return success(office_action_response_to_wire(response), http_status=201)


@bp.route("/office-action-responses/<rid>", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin", "USPTOExaminer")
def get_response(rid, **_):
    r = db.office_action_responses.get(rid)
    if r is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND", f"OfficeActionResponse {rid} not found"
        )
    return success(office_action_response_to_wire(r))


@bp.route("/office-action-responses", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin", "USPTOExaminer")
def list_responses(**_):
    limit, offset = parse_pagination()
    oa_filter = request.args.get("office_action_id")
    items = []
    for r in db.office_action_responses.values():
        if oa_filter and r["office_action_id"] != oa_filter:
            continue
        items.append(r)
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [office_action_response_to_wire(r) for r in page], limit, offset, total
    )
