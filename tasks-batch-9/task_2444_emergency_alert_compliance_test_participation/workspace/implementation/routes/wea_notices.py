"""WirelessAlertNotice endpoints (PRD 3.5).

Immutable rows: they expose only id and created_at among the audit fields
(PRD 2.5) and recording one mutates no other row.
"""

from flask import Blueprint, request

import serializers
from auth import ANY_ROLE, guard
from envelope import object_response
from routes.helpers import collection_response, filter_equals
from store import base_row, db, mark_created
from validators import (
    EVENT_CODE_RE,
    FIPS_RE,
    get_station,
    get_wea_notice,
    json_body,
    req_array,
    req_datetime,
    req_string,
)

bp = Blueprint("wea_notices", __name__)


@bp.post("/wireless-alert-notices")
@guard("ComplianceAdmin")
def create_wea_notice():
    body = json_body(request)
    station_id = req_string(body, "station_id")
    originator_sequence = req_string(body, "originator_sequence")
    event_code = req_string(body, "event_code", pattern=EVENT_CODE_RE)
    wea_sent_at = req_datetime(body, "wea_sent_at")
    fips_codes = req_array(body, "fips_codes", non_empty=True, member_pattern=FIPS_RE)

    get_station(station_id)

    notice = base_row(versioned=False)
    notice.update({
        "station_id": station_id,
        "originator_sequence": originator_sequence,
        "event_code": event_code,
        "wea_sent_at": wea_sent_at,
        "fips_codes": list(fips_codes),
    })
    db.wea_notices[notice["id"]] = notice
    mark_created(notice)
    return object_response(serializers.wea_notice(notice), 201)


@bp.get("/wireless-alert-notices/<notice_id>")
@guard(*ANY_ROLE)
def read_wea_notice(notice_id):
    notice = get_wea_notice(notice_id)
    return object_response(serializers.wea_notice(notice))


@bp.get("/wireless-alert-notices")
@guard(*ANY_ROLE)
def list_wea_notices():
    rows = list(db.wea_notices.values())
    rows = filter_equals(rows, request, (
        ("station_id", "station_id"),
        ("originator_sequence", "originator_sequence"),
        ("event_code", "event_code"),
    ))
    return collection_response(rows, request, serializers.wea_notice)
