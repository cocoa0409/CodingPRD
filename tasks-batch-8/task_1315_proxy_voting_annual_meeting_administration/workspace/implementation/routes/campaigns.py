"""SolicitationCampaign endpoints (PRD §3.6).

CONTESTED meetings only. Windows must be well-formed and close at or before
meeting_datetime. Same-party windows must be separated by at least 24 hours,
in either direction.
"""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CAMPAIGN_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_MEETING_NOT_CONTESTED,
    ERR_MEETING_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_field,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("campaigns", __name__)

MIN_GAP = timedelta(hours=24)


def get_campaign_or_404(campaign_id: str) -> dict:
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise_err(ERR_CAMPAIGN_NOT_FOUND, "SolicitationCampaign id does not exist")
    return campaign


@bp.route("/proxy/solicitation-campaigns", methods=["POST"])
@require_roles("ProxyAdministrator")
def create_campaign(_user_id: str, _role: str):
    body = get_json_body()
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")

    # Temporal (precedence 6): window well-formed and closing at or before the
    # meeting itself.
    start_at = require_field(body, "start_at")
    end_at = require_field(body, "end_at")
    start_dt = parse_iso8601(start_at, "start_at")
    end_dt = parse_iso8601(end_at, "end_at")
    if not end_dt > start_dt:
        raise_err(ERR_INVALID_REQUEST, "end_at must be strictly after start_at")
    meeting_dt = parse_iso8601(meeting["meeting_datetime"], "meeting_datetime")
    if end_dt > meeting_dt:
        raise_err(
            ERR_INVALID_REQUEST,
            "Campaign window must close at or before meeting_datetime",
        )

    # Domain (precedence 8): contested-only, then the 24-hour same-party gap.
    if meeting["meeting_type"] != "CONTESTED":
        raise_err(
            ERR_MEETING_NOT_CONTESTED,
            "Solicitation campaigns are allowed only for CONTESTED meetings",
        )
    soliciting_party = require_string(body, "soliciting_party")
    for existing in db.campaigns.values():
        if (
            existing["meeting_id"] != meeting_id
            or existing["soliciting_party"] != soliciting_party
        ):
            continue
        ex_start = parse_iso8601(existing["start_at"], "start_at")
        ex_end = parse_iso8601(existing["end_at"], "end_at")
        separated = (start_dt >= ex_end + MIN_GAP) or (ex_start >= end_dt + MIN_GAP)
        if not separated:
            raise_err(
                ERR_CAMPAIGN_WINDOW_OVERLAP,
                "Same-party campaign windows must be separated by at least 24 hours",
            )

    campaign = {
        "meeting_id": meeting_id,
        "soliciting_party": soliciting_party,
        "start_at": start_at,
        "end_at": end_at,
    }
    db.stamp_new(campaign)
    db.campaigns[campaign["id"]] = campaign
    return success_object(serialize(campaign), 201)


@bp.route("/proxy/solicitation-campaigns", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def list_campaigns(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.campaigns.values()))
    items = apply_filters(items, ["meeting_id", "soliciting_party"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/solicitation-campaigns/<campaign_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def get_campaign(campaign_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_campaign_or_404(campaign_id)))
