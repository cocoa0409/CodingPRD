"""Sponsors and the contract gate on booth approval (PRD 3.8)."""

from flask import Blueprint

import db
from auth import authorize, own_event
from db import S
from response import ok, ok_list
from validate import (
    body, get_event, get_sponsor, pagination, paginate, qs, req_enum, req_str,
)

bp = Blueprint("sponsors", __name__)

PACKAGE_TIERS = ("BRONZE", "SILVER", "GOLD")


@bp.route("/api/events/<event_id>/sponsors", methods=["POST"])
def create_sponsor(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    b = body()
    name = req_str(b, "name")
    package_tier = req_enum(b, "package_tier", PACKAGE_TIERS)
    contact_email = req_str(b, "contact_email")

    row = db.new_row({
        "event_id": event["id"],
        "name": name,
        "package_tier": package_tier,
        "contact_email": contact_email,
        "contract_status": "UNSIGNED",
    })
    S.sponsors[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/events/<event_id>/sponsors", methods=["GET"])
def list_event_sponsors(event_id):
    authorize("Organizer", "PlatformAdmin", "FinanceAdmin")
    event = get_event(event_id)
    limit, offset = pagination()
    rows = [s for s in S.sponsors.values() if s.get("event_id") == event["id"]]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/sponsors", methods=["GET"])
def list_sponsors():
    authorize("Organizer", "PlatformAdmin", "FinanceAdmin", "SponsorUser")
    limit, offset = pagination()
    event_id = qs("event_id")
    package_tier = qs("package_tier")
    contract_status = qs("contract_status")
    rows = [
        s for s in S.sponsors.values()
        if (event_id is None or s.get("event_id") == event_id)
        and (package_tier is None or s.get("package_tier") == package_tier)
        and (contract_status is None or s.get("contract_status") == contract_status)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/sponsors/<sponsor_id>", methods=["GET"])
def read_sponsor(sponsor_id):
    authorize("Organizer", "PlatformAdmin", "FinanceAdmin", "SponsorUser")
    return ok(db.serialize(get_sponsor(sponsor_id)))


@bp.route("/api/sponsors/<sponsor_id>/sign-contract", methods=["POST"])
def sign_contract(sponsor_id):
    authorize("Organizer")
    sponsor = get_sponsor(sponsor_id)
    event = S.events.get(sponsor.get("event_id"))
    if event is not None:
        own_event(event)
    b = body()
    req_str(b, "signed_by")
    sponsor["contract_status"] = "SIGNED"
    db.touch(sponsor)
    return ok(db.serialize(sponsor))
