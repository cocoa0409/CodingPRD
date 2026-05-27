"""Office actions: POST/GET /office-actions, GET /office-actions/{id}."""

from flask import Blueprint, request

from db import db, new_id
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.body import get_json_body, require_string, require_enum
from services.dateutil import add_months
from services.pagination import parse_pagination, slice_sorted
from services.serialize import office_action_to_wire
from services.application_svc import (
    APP_TERMINAL_STATES,
    bump_application,
    bump_office_action,
)


bp = Blueprint("office_actions", __name__)


ACTION_TYPES = {"NON_FINAL", "FINAL", "NOTICE_OF_ALLOWANCE"}


@bp.route("/office-actions", methods=["POST"])
@require_roles("USPTOExaminer")
def create_office_action(**_):
    body = get_json_body()
    application_id = require_string(body, "application_id")
    action_type = require_enum(body, "action_type", ACTION_TYPES)

    # Priority 5: FK existence
    app = db.applications.get(application_id)
    if app is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND",
            f"Application {application_id} not found",
        )

    # Priority 7: terminal-state lockdown
    if app["status"] in APP_TERMINAL_STATES or app["status"] == "ISSUED":
        raise_api(
            "ERR_TERMINAL_STATE",
            f"Application status {app['status']} is terminal",
        )

    # State machine: allowed sources by action_type
    if action_type == "NOTICE_OF_ALLOWANCE":
        # Allowed from AWAITING_EXAMINATION, OFFICE_ACTION_OUTSTANDING, or RESPONSE_FILED.
        # (RESPONSE_FILED is permitted because the scaffold's RESPONSE_FILED->
        # OFFICE_ACTION_OUTSTANDING transition admits action_type=NOTICE_OF_ALLOWANCE,
        # and a NoA immediately advances Application.status to ALLOWED.)
        if app["status"] not in {
            "AWAITING_EXAMINATION",
            "OFFICE_ACTION_OUTSTANDING",
            "RESPONSE_FILED",
        }:
            raise_api(
                "ERR_INVALID_STATE",
                f"NOTICE_OF_ALLOWANCE not permitted from status {app['status']}",
            )
    else:
        # NON_FINAL/FINAL: only from AWAITING_EXAMINATION or RESPONSE_FILED
        if app["status"] not in {"AWAITING_EXAMINATION", "RESPONSE_FILED"}:
            # If currently OFFICE_ACTION_OUTSTANDING, the right error is the
            # single-outstanding violation (priority 20) — checked below.
            if app["status"] == "OFFICE_ACTION_OUTSTANDING":
                raise_api(
                    "ERR_OFFICE_ACTION_ALREADY_OUTSTANDING",
                    "An OUTSTANDING OfficeAction already exists for this application",
                )
            raise_api(
                "ERR_INVALID_STATE",
                f"OfficeAction of type {action_type} not permitted from status {app['status']}",
            )

        # Priority 20: VAL-OA-SINGLE-OUTSTANDING — guard against any stray OUTSTANDING
        # OA even if the parent application status somehow says otherwise.
        for oa in db.office_actions.values():
            if oa["application_id"] == application_id and oa["status"] == "OUTSTANDING":
                raise_api(
                    "ERR_OFFICE_ACTION_ALREADY_OUTSTANDING",
                    "An OUTSTANDING OfficeAction already exists for this application",
                )

    # ---- Side effects ---------------------------------------------------
    now = db.current_utc_dt()
    oa_id = new_id()
    oa = {
        "id": oa_id,
        "application_id": application_id,
        "action_type": action_type,
        "issue_date": now,
        "shortened_due_date": add_months(now, 3),
        "maximum_due_date": add_months(now, 6),
        "status": "OUTSTANDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.office_actions[oa_id] = oa

    if action_type == "NOTICE_OF_ALLOWANCE":
        # Withdraw all other OUTSTANDING OAs on this application (excluding this one)
        for existing in db.office_actions.values():
            if (
                existing["id"] != oa_id
                and existing["application_id"] == application_id
                and existing["status"] == "OUTSTANDING"
            ):
                existing["status"] = "WITHDRAWN"
                bump_office_action(existing)
        app["status"] = "ALLOWED"
    else:
        app["status"] = "OFFICE_ACTION_OUTSTANDING"
    bump_application(app)

    return success(office_action_to_wire(oa), http_status=201)


@bp.route("/office-actions/<oa_id>", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin", "USPTOExaminer")
def get_office_action(oa_id, **_):
    oa = db.office_actions.get(oa_id)
    if oa is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", f"OfficeAction {oa_id} not found")
    return success(office_action_to_wire(oa))


@bp.route("/office-actions", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin", "USPTOExaminer")
def list_office_actions(**_):
    limit, offset = parse_pagination()
    app_filter = request.args.get("application_id")
    items = []
    for oa in db.office_actions.values():
        if app_filter and oa["application_id"] != app_filter:
            continue
        items.append(oa)
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [office_action_to_wire(o) for o in page], limit, offset, total
    )
