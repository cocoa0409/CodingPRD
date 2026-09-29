"""Dialer configuration and its approval track (§3.6)."""

from flask import Blueprint, g

import lookup
import validation as v
from calculations import REGULATORY_ABANDONMENT_CEILING_PCT
from db import base_row, db, public, touch
from derive import pacing_lines
from errors import ApiError
from middleware import endpoint, payload
from response import created, ok
from util import pct

bp = Blueprint("dialer", __name__)

MODES = ("PREVIEW", "POWER", "PREDICTIVE")


@bp.post("/compliance/dialer-profiles")
@endpoint(["DialerOperator", "CampaignManager"])
def create_profile():
    body = payload()
    mode = v.req_enum(body, "mode", MODES)
    agents_available = v.req_int(body, "agents_available", 1, 500)
    abandonment_limit_pct = v.opt_decimal(body, "abandonment_limit_pct", "3.00", "0.01", "100.00")
    amd_enabled = v.opt_bool(body, "amd_enabled", False)
    amd_abandon_on_machine = v.opt_bool(body, "amd_abandon_on_machine", False)
    abandon_message_seconds = v.opt_int(body, "abandon_message_seconds", 2, 1, 10)

    row = base_row()
    row.update(
        {
            "mode": mode,
            "abandonment_limit_pct": pct(abandonment_limit_pct),
            "amd_enabled": amd_enabled,
            "amd_abandon_on_machine": amd_abandon_on_machine,
            "abandon_message_seconds": abandon_message_seconds,
            "agents_available": agents_available,
            "requires_waiver": abandonment_limit_pct > REGULATORY_ABANDONMENT_CEILING_PCT,
            "waiver_reference": None,
            "max_lines_last_computed": agents_available,
            "status": "DRAFT",
            "locked_reason": None,
            "approved_by_user_id": None,
        }
    )
    db.dialer_profiles[row["id"]] = row
    return created(public(row))


@bp.get("/compliance/dialer-profiles/<profile_id>")
@endpoint(["DialerOperator", "CampaignManager", "ComplianceOfficer", "PlatformAdmin"])
def read_profile(profile_id):
    return ok(public(lookup.dialer_profile(profile_id)))


@bp.post("/compliance/dialer-profiles/<profile_id>/approve")
@endpoint(["ComplianceOfficer"])
def approve_profile(profile_id):
    body = payload()
    waiver_reference = v.opt_str(body, "waiver_reference")
    profile = lookup.dialer_profile(profile_id)
    if profile["status"] not in ("DRAFT", "LOCKED"):
        raise ApiError(
            "ERR_DIALER_PROFILE_STATE_INVALID",
            "Only a DRAFT or LOCKED dialer profile may be approved.",
        )
    if profile["requires_waiver"] and (waiver_reference is None or not waiver_reference.strip()):
        raise ApiError(
            "ERR_ABANDONMENT_LIMIT_WAIVER_REQUIRED",
            "A limit above the 3.00%% regulatory ceiling requires a waiver_reference.",
        )

    profile["status"] = "APPROVED"
    profile["approved_by_user_id"] = g.user_id
    profile["locked_reason"] = None
    profile["waiver_reference"] = waiver_reference if profile["requires_waiver"] else None
    profile["max_lines_last_computed"] = pacing_lines(profile, None)
    touch(profile)
    return ok(public(profile))
