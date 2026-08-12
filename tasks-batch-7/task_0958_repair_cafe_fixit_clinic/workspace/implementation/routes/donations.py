"""Donation pledges, valuation at RECEIVED, receipting, and refunds."""

from flask import Blueprint

import db
import serializers as ser
import services
from errors import (
    ERR_DONATION_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_INVALID_DONATION_STATE,
    ERR_VALIDATION,
    ERR_VISITOR_NOT_FOUND,
    raise_err,
)
from middleware import require_roles
from response import success
from util import as_enum, as_int, as_num, as_str, body, list_response, opt, req

bp = Blueprint("donations", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")
DONATION_TYPES = ("MONETARY", "IN_KIND")


def get_donation_or_404(donation_id):
    rec = db.donations.get(donation_id)
    if rec is None:
        raise_err(ERR_DONATION_NOT_FOUND, "Donation %s does not exist" % donation_id)
    return rec


@bp.post("/api/donations")
@require_roles("IntakeVolunteer")
def create_donation():
    b = body()
    donation_type = as_enum(req(b, "donation_type"), "donation_type", DONATION_TYPES)
    # Existence (priority 3): body FKs in declared order.
    event_id = opt(b, "event_id")
    if event_id is not None:
        as_str(event_id, "event_id")
        if event_id not in db.events:
            raise_err(ERR_EVENT_NOT_FOUND, "RepairEvent %s does not exist" % event_id)
    visitor_id = opt(b, "visitor_id")
    if visitor_id is not None:
        as_str(visitor_id, "visitor_id")
        if visitor_id not in db.visitors:
            raise_err(ERR_VISITOR_NOT_FOUND, "Visitor %s does not exist" % visitor_id)

    amount_cents = None
    in_kind_lines = None
    if donation_type == "MONETARY":
        amount_cents = as_int(req(b, "amount_cents"), "amount_cents", lo=1)
    else:
        lines = req(b, "in_kind_lines")
        if not isinstance(lines, list) or not lines:
            raise_err(ERR_VALIDATION, "in_kind_lines must be a non-empty array")
        in_kind_lines = []
        for idx, line in enumerate(lines):
            if not isinstance(line, dict):
                raise_err(ERR_VALIDATION, "in_kind_lines[%d] must be an object" % idx)
            description = as_str(req(line, "description"), "in_kind_lines[%d].description" % idx)
            category = as_str(req(line, "category"), "in_kind_lines[%d].category" % idx)
            declared = as_int(
                req(line, "declared_value_cents"),
                "in_kind_lines[%d].declared_value_cents" % idx,
                lo=0,
            )
            age = as_num(req(line, "age_years"), "in_kind_lines[%d].age_years" % idx, lo=0)
            in_kind_lines.append(
                {
                    "description": description,
                    "category": category,
                    "declared_value_cents": declared,
                    "age_years": age,
                }
            )

    rec = db.stamp_new(
        {
            "event_id": event_id,
            "visitor_id": visitor_id,
            "donation_type": donation_type,
            "amount_cents": amount_cents,
            "in_kind_lines": in_kind_lines,
            "status": "PLEDGED",
            "received_at": None,
            "receipt_value_cents": None,
            "campaign_value_cents": None,
        }
    )
    db.donations[rec["id"]] = rec
    return success(ser.donation(rec), 201)


@bp.get("/api/donations")
@require_roles(*ALL_ROLES)
def list_donations():
    return list_response(
        db.donations.values(),
        ser.donation,
        [("event_id", "event_id"), ("visitor_id", "visitor_id"), ("status", "status")],
    )


@bp.get("/api/donations/<donation_id>")
@require_roles(*ALL_ROLES)
def get_donation(donation_id):
    return success(ser.donation(get_donation_or_404(donation_id)), 200)


@bp.post("/api/donations/<donation_id>/receive")
@require_roles("IntakeVolunteer")
def receive_donation(donation_id):
    donation = get_donation_or_404(donation_id)
    if donation["status"] != "PLEDGED":
        raise_err(ERR_INVALID_DONATION_STATE, "Only a PLEDGED donation can be received")
    # Compute then freeze both valuations at the RECEIVED transition.
    donation["receipt_value_cents"] = services.donation_receipt_value(donation)
    donation["campaign_value_cents"] = services.donation_campaign_value(donation)
    donation["received_at"] = db.clock.now_iso()
    donation["status"] = "RECEIVED"
    db.touch(donation)
    return success(ser.donation(donation), 200)


@bp.post("/api/donations/<donation_id>/receipt")
@require_roles("IntakeVolunteer")
def receipt_donation(donation_id):
    donation = get_donation_or_404(donation_id)
    if donation["status"] != "RECEIVED":
        raise_err(ERR_INVALID_DONATION_STATE, "Only a RECEIVED donation can be receipted")
    donation["status"] = "RECEIPTED"
    db.touch(donation)
    return success(ser.donation(donation), 200)


@bp.post("/api/donations/<donation_id>/refund")
@require_roles("Coordinator")
def refund_donation(donation_id):
    donation = get_donation_or_404(donation_id)
    if donation["status"] != "RECEIVED":
        raise_err(ERR_INVALID_DONATION_STATE, "Only a RECEIVED donation can be refunded")
    donation["status"] = "REFUNDED"
    db.touch(donation)
    return success(ser.donation(donation), 200)
