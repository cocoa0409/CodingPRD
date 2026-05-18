"""Test-driving system endpoints: clock advance, clock read, sweep."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..calculations import recompute_posture
from ..clock import clock
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_update, store
from ..utils import parse_json_body, require_field


bp_system_ops = Blueprint("system_ops", __name__)


@bp_system_ops.route("/_clock/advance", methods=["POST"])
@require_auth(["PlatformAdmin"])
def advance_clock():
    body = parse_json_body()
    days = require_field(body, "days", types=[int])
    if isinstance(days, bool) or days < 1:
        raise ApiError("ERR_INVALID_REQUEST", "days must be a positive integer.", 400)
    new_day = clock.advance(days)
    return json_object({"day": new_day}, 200)


@bp_system_ops.route("/_clock", methods=["GET"])
@require_auth(["PlatformAdmin", "Consumer", "BureauOperator", "Furnisher", "CFPBOperator"])
def get_clock():
    return json_object({"day": clock.day}, 200)


@bp_system_ops.route("/_sweep/run", methods=["POST"])
@require_auth(["PlatformAdmin"])
def run_sweep():
    """Per PRD §2.11/§3.3:

    For each FurnisherInquiry with response=PENDING AND
    reverification_deadline_day STRICTLY LESS THAN clock.day:
      - response = NO_RESPONSE
      - parent Dispute advances to RESULTS_PENDING (system arm)
    """
    swept: list[str] = []
    with store.lock:
        for fi in list(store.furnisher_inquiries.values()):
            if (
                fi["response"] == "PENDING"
                and fi["reverification_deadline_day"] < clock.day
            ):
                dispute = store.disputes.get(fi["dispute_id"])
                if dispute is None or dispute["status"] != "UNDER_INVESTIGATION":
                    # Dispute may have already moved on (operator won the race).
                    continue
                fi["response"] = "NO_RESPONSE"
                # response_day stays null per scaffold: "null if NO_RESPONSE"
                dispute["status"] = "RESULTS_PENDING"
                stamp_update(dispute)
                recompute_posture(dispute["credit_report_id"])
                swept.append(dispute["id"])
    return json_object({"swept_dispute_ids": swept, "count": len(swept)}, 200)
