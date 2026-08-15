"""Lead endpoints: create, list/get, route (selector policy), respond, expire."""

from __future__ import annotations

from datetime import timedelta
from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_LEAD_NOT_FOUND,
    ERR_LEAD_NOT_ROUTED_TO_DEALER,
    ERR_LEAD_INVALID_STATE,
    ERR_LEAD_NOT_YET_EXPIRED,
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
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("leads", __name__)

LEAD_SLA_HOURS = 72
ROUTABLE_STATUSES = ("NEW", "ORPHANED", "DECLINED", "EXPIRED")


def get_lead_or_404(lead_id: str) -> dict:
    lead = db.leads.get(lead_id)
    if lead is None:
        raise_err(ERR_LEAD_NOT_FOUND, "Lead id does not exist")
    return lead


def _select_candidate(lead: dict):
    """lead_routing_selection: eligibility -> ranking -> tie-break.

    Returns (dealer, assignment) or None when the candidate pool is empty.
    """
    today = db.clock_date().isoformat()
    declined = set(lead.get("declined_dealer_ids") or [])
    candidates = []
    for dealer in db.dealers.values():
        if dealer["status"] != "ACTIVE":
            continue
        if dealer["id"] in declined:
            continue
        qualifying = [
            a
            for a in db.assignments.values()
            if a["status"] == "ACTIVE"
            and a["dealer_id"] == dealer["id"]
            and a["territory_code"] == lead["territory_code"]
            and a["starts_on"] <= today < a["ends_on"]
        ]
        if not qualifying:
            continue
        qualifying.sort(key=lambda a: a["_seq"])
        open_lead_count = sum(
            1
            for l in db.leads.values()
            if l["status"] == "ROUTED" and l.get("routed_dealer_id") == dealer["id"]
        )
        candidates.append((open_lead_count, dealer["_seq"], dealer, qualifying[0]))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    _, _, dealer, assignment = candidates[0]
    return dealer, assignment


@bp.route("/leads", methods=["POST"])
@require_roles("OemSalesOps")
def create_lead(_user_id: str, _role: str):
    body = get_json_body()
    territory_code = require_string(body, "territory_code")
    product_line = require_string(body, "product_line")
    estimated_value_cents = require_int(body, "estimated_value_cents")
    if estimated_value_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "estimated_value_cents must be > 0")
    contact_name = require_string(body, "contact_name")

    lead = {
        "territory_code": territory_code,
        "product_line": product_line,
        "estimated_value_cents": estimated_value_cents,
        "contact_name": contact_name,
        "routed_dealer_id": None,
        "routed_assignment_id": None,
        "declined_dealer_ids": [],
        "routed_at": None,
        "status": "NEW",
    }
    db.stamp_new(lead)
    db.leads[lead["id"]] = lead
    return success_object(serialize(lead), 201)


@bp.route("/leads", methods=["GET"])
@require_roles("Any")
def list_leads(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.leads.values()))
    items = apply_filters(items, ["territory_code", "status", "routed_dealer_id", "routed_assignment_id"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/leads/<lead_id>", methods=["GET"])
@require_roles("Any")
def get_lead(lead_id: str, _user_id: str, _role: str):
    lead = get_lead_or_404(lead_id)
    return success_object(serialize(lead))


@bp.route("/leads/<lead_id>/route", methods=["POST"])
@require_roles("OemSalesOps")
def route_lead(lead_id: str, _user_id: str, _role: str):
    lead = get_lead_or_404(lead_id)
    if lead["status"] not in ROUTABLE_STATUSES:
        raise_err(ERR_LEAD_INVALID_STATE, "route requires lead in NEW, ORPHANED, DECLINED, or EXPIRED")

    selected = _select_candidate(lead)
    if selected is None:
        # Empty candidate pool -> ORPHANED (a normal outcome, not an error).
        lead["status"] = "ORPHANED"
        lead["routed_dealer_id"] = None
        lead["routed_assignment_id"] = None
        lead["routed_at"] = None
    else:
        dealer, assignment = selected
        lead["status"] = "ROUTED"
        lead["routed_dealer_id"] = dealer["id"]
        lead["routed_assignment_id"] = assignment["id"]
        lead["routed_at"] = db.get_current_utc()
    db.touch(lead)
    return success_object(serialize(lead))


@bp.route("/leads/<lead_id>/respond", methods=["POST"])
@require_roles("DealerUser")
def respond_lead(lead_id: str, _user_id: str, _role: str):
    body = get_json_body()
    response = require_enum(body, "response", {"ACCEPT", "DECLINE"})
    lead = get_lead_or_404(lead_id)

    # Priority 5 ownership: responder must be the currently routed dealer.
    if lead.get("routed_dealer_id") != _user_id:
        raise_err(ERR_LEAD_NOT_ROUTED_TO_DEALER, "Responding DealerUser is not the routed dealer")

    # Priority 6 state.
    if lead["status"] != "ROUTED":
        raise_err(ERR_LEAD_INVALID_STATE, "respond requires lead ROUTED")

    if response == "ACCEPT":
        lead["status"] = "ACCEPTED"
    else:
        lead["status"] = "DECLINED"
        lead["declined_dealer_ids"] = (lead.get("declined_dealer_ids") or []) + [_user_id]
        lead["routed_dealer_id"] = None
        lead["routed_assignment_id"] = None
        lead["routed_at"] = None
    db.touch(lead)
    return success_object(serialize(lead))


@bp.route("/leads/<lead_id>/expire", methods=["POST"])
@require_roles("OemSalesOps")
def expire_lead(lead_id: str, _user_id: str, _role: str):
    lead = get_lead_or_404(lead_id)
    # Priority 6 state.
    if lead["status"] != "ROUTED":
        raise_err(ERR_LEAD_INVALID_STATE, "expire requires lead ROUTED")
    # Priority 9 temporal: more than 72 hours past routed_at.
    routed_at = parse_iso8601(lead["routed_at"], "routed_at")
    if db.clock_datetime() <= routed_at + timedelta(hours=LEAD_SLA_HOURS):
        raise_err(ERR_LEAD_NOT_YET_EXPIRED, "Lead expire requires current logical datetime > routed_at + 72 hours")

    expired_dealer = lead["routed_dealer_id"]
    lead["status"] = "EXPIRED"
    if expired_dealer is not None:
        lead["declined_dealer_ids"] = (lead.get("declined_dealer_ids") or []) + [expired_dealer]
    lead["routed_dealer_id"] = None
    lead["routed_assignment_id"] = None
    lead["routed_at"] = None
    db.touch(lead)
    return success_object(serialize(lead))
