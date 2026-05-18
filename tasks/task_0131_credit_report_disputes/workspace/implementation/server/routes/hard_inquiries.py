"""HardInquiry routes — gated by freeze and lock per PRD §3.12."""
from __future__ import annotations

from flask import Blueprint

from ..auth import current_principal, require_auth
from ..calculations import recompute_fico_on_report
from ..clock import clock
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_create_append_only, store
from ..utils import parse_json_body, require_field


bp_hard_inquiries = Blueprint("hard_inquiries", __name__)


@bp_hard_inquiries.route(
    "/credit_reports/<credit_report_id>/hard_inquiries", methods=["POST"]
)
@require_auth(["Furnisher"])
def request_hard_inquiry(credit_report_id: str):
    report = store.credit_reports.get(credit_report_id)
    if report is None:
        raise ApiError("ERR_NOT_FOUND", "CreditReport not found.", 404)
    body = parse_json_body()
    requesting_furnisher_id = require_field(body, "requesting_furnisher_id", types=[str])
    furnisher = store.furnishers.get(requesting_furnisher_id)
    if furnisher is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "requesting_furnisher_id does not exist.", 400
        )
    # Ownership: Furnisher caller must match requesting_furnisher_id.
    user_id, user_role = current_principal()
    if user_role == "Furnisher" and user_id != requesting_furnisher_id:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Furnisher may only request inquiries for themselves.",
            403,
        )

    with store.lock:
        consumer_id = report["consumer_id"]
        bureau = report["bureau"]

        # Priority 14: freeze gating (freeze takes precedence over lock per PRD §3.12).
        active_freeze = any(
            f["consumer_id"] == consumer_id
            and f["bureau"] == bureau
            and f["status"] == "ACTIVE"
            for f in store.credit_freezes.values()
        )
        if active_freeze:
            inquiry = stamp_create_append_only(
                {
                    "credit_report_id": credit_report_id,
                    "requesting_furnisher_id": requesting_furnisher_id,
                    "inquiry_day": clock.day,
                    "outcome": "BLOCKED_FREEZE",
                }
            )
            store.hard_inquiries[inquiry["id"]] = inquiry
            raise ApiError(
                "ERR_HARD_INQUIRY_BLOCKED_BY_FREEZE",
                "Hard inquiry blocked by an active CreditFreeze.",
                409,
            )

        active_lock = any(
            l["consumer_id"] == consumer_id
            and l["bureau"] == bureau
            and l["status"] == "LOCKED"
            for l in store.credit_locks.values()
        )
        if active_lock:
            inquiry = stamp_create_append_only(
                {
                    "credit_report_id": credit_report_id,
                    "requesting_furnisher_id": requesting_furnisher_id,
                    "inquiry_day": clock.day,
                    "outcome": "BLOCKED_LOCK",
                }
            )
            store.hard_inquiries[inquiry["id"]] = inquiry
            raise ApiError(
                "ERR_HARD_INQUIRY_BLOCKED_BY_LOCK",
                "Hard inquiry blocked by an active CreditLock.",
                409,
            )

        inquiry = stamp_create_append_only(
            {
                "credit_report_id": credit_report_id,
                "requesting_furnisher_id": requesting_furnisher_id,
                "inquiry_day": clock.day,
                "outcome": "ACCEPTED",
            }
        )
        store.hard_inquiries[inquiry["id"]] = inquiry
        # Accepted inquiries influence FICO (recent-inquiries component).
        recompute_fico_on_report(credit_report_id)

    return json_object(inquiry, 201)
