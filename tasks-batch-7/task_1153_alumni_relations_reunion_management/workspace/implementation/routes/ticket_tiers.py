"""TicketTier endpoints."""

from flask import Blueprint

import db
from errors import (
    err_invalid_request, err_not_found, err_stale_version, err_window_overlap,
)
from middleware import require_roles
from response import success_list, success_object
from services.calculations import rederive_posture
from services.common import (
    apply_pagination, format_ts, json_body, new_entity, pagination_args,
    parse_iso, req_int, req_str, touch,
)
from services.serializers import TIER_FIELDS, serialize
from routes.events import get_event_or_404

bp = Blueprint("ticket_tiers", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
TIER_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair",
             "CommitteeVolunteer", "Alumni")


def get_tier_or_404(tier_id):
    t = db.ticket_tiers.get(tier_id)
    if t is None:
        raise err_not_found("TicketTier not found")
    return t


@bp.route("/alumni/events/<eid>/ticket-tiers", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def create_tier(eid, _role, _user_id):
    event = get_event_or_404(eid)
    body = json_body(required=["name", "base_price_cents", "capacity",
                               "sales_start", "sales_end", "expected_event_version"])
    expected = body["expected_event_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_event_version must be an integer")
    if expected != event["version"]:
        raise err_stale_version("ReunionEvent version has advanced")

    name = req_str(body["name"], "name")
    base_price = req_int(body["base_price_cents"], "base_price_cents")
    if base_price < 0:
        raise err_invalid_request("base_price_cents must be >= 0")
    capacity = req_int(body["capacity"], "capacity")
    if capacity < 0:
        raise err_invalid_request("capacity must be >= 0")
    sales_start_dt = parse_iso(body["sales_start"])
    sales_end_dt = parse_iso(body["sales_end"])
    if not sales_start_dt < sales_end_dt:
        raise err_invalid_request("sales_start must be before sales_end")
    pct = body.get("early_bird_discount_pct", 0)
    if pct is None:
        pct = 0
    pct = req_int(pct, "early_bird_discount_pct")
    if pct < 0 or pct > 90:
        raise err_invalid_request("early_bird_discount_pct must be between 0 and 90")

    # half-open [start, end) non-overlap; touching endpoints allowed
    for t in db.ticket_tiers.values():
        if t["event_id"] != eid:
            continue
        if sales_start_dt < t["sales_end_dt"] and t["sales_start_dt"] < sales_end_dt:
            raise err_window_overlap()

    tier = new_entity({
        "event_id": eid,
        "name": name,
        "base_price_cents": base_price,
        "capacity": capacity,
        "sold_count": 0,
        "sales_start": format_ts(sales_start_dt),
        "sales_start_dt": sales_start_dt,
        "sales_end": format_ts(sales_end_dt),
        "sales_end_dt": sales_end_dt,
        "early_bird_discount_pct": pct,
    })
    db.ticket_tiers[tier["id"]] = tier

    # tier creation increments the parent event's version by one, posture re-derived
    rederive_posture(event)
    return success_object(serialize(tier, TIER_FIELDS), status=201)


@bp.route("/alumni/events/<eid>/ticket-tiers", methods=["GET"])
@require_roles(*TIER_READ)
def list_tiers(eid, _role, _user_id):
    get_event_or_404(eid)
    limit, offset = pagination_args()
    rows = [t for t in db.ticket_tiers.values() if t["event_id"] == eid]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(t, TIER_FIELDS) for t in page], limit, offset, total)


@bp.route("/alumni/ticket-tiers/<tid>", methods=["GET"])
@require_roles(*TIER_READ)
def get_tier(tid, _role, _user_id):
    return success_object(serialize(get_tier_or_404(tid), TIER_FIELDS))
