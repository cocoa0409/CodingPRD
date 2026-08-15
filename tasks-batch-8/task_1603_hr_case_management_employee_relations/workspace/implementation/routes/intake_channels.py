"""Intake channel configuration endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_DUPLICATE
from middleware import authorize
from response import success_object
from services.core import new_record, list_response, serialize_channel
from validate import Payload

bp = Blueprint("intake_channels", __name__)

CHANNEL_CODES = {"HOTLINE", "WEB_PORTAL", "MANAGER_REFERRAL", "HR_DIRECT",
                 "ANONYMOUS_LETTER"}
CATEGORIES = {"HARASSMENT", "DISCRIMINATION", "RETALIATION", "POLICY_VIOLATION",
              "SAFETY", "COMPENSATION", "OTHER"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@bp.post("/er/intake-channels")
def create_channel():
    authorize({"ERManager"})
    p = Payload(request.get_json(silent=True))
    channel_code = p.get_enum("channel_code", CHANNEL_CODES, required=True)
    display_name = p.get_str("display_name", required=True)
    default_category = p.get_enum("default_category", CATEGORIES, required=True)
    default_severity = p.get_enum("default_severity", SEVERITIES, required=False)
    requires_identity = p.get_bool("requires_reporter_identity", required=False)
    sla_business_days = p.get_int("sla_business_days", required=True, minimum=1)

    # priority 15 — unique channel_code
    for ch in db["intake_channels"].values():
        if channel_code is not None and ch["channel_code"] == channel_code:
            raise_error(ERR_DUPLICATE,
                        f"channel_code {channel_code} already exists")

    # priority 24
    p.raise_if_errors()

    rec = new_record()
    rec.update({
        "channel_code": channel_code,
        "display_name": display_name,
        "default_category": default_category,
        "default_severity": default_severity or "MEDIUM",
        "requires_reporter_identity": (requires_identity
                                       if requires_identity is not None else False),
        "sla_business_days": sla_business_days,
    })
    db["intake_channels"][rec["id"]] = rec
    return success_object(serialize_channel(rec), status=201)


@bp.get("/er/intake-channels")
def list_channels():
    authorize({"ERManager", "Investigator", "HRAnalyst"})
    return list_response(list(db["intake_channels"].values()), serialize_channel)
