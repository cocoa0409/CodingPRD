"""Agent scripts and their review loop (§3.6)."""

from flask import Blueprint, g

import lookup
import validation as v
from db import base_row, db, now_iso, public, touch
from errors import ApiError
from middleware import endpoint, payload
from response import created, ok

bp = Blueprint("scripts", __name__)

CHANNELS = ("VOICE", "SMS")
BLOCK_TYPES = ("IDENTIFICATION", "PURPOSE", "OPT_OUT", "RECORDING_NOTICE")
RECORDING_MODES = ("ONE_PARTY", "ALL_PARTY")


def _disclosure_blocks(body):
    blocks = v.require(body, "disclosure_blocks")
    if not isinstance(blocks, list) or len(blocks) < 1:
        v.bad("Field 'disclosure_blocks' must be a non-empty array.")
    cleaned = []
    for block in blocks:
        if not isinstance(block, dict):
            v.bad("Each disclosure block must be an object.")
        block_type = block.get("block_type")
        text = block.get("text")
        if not isinstance(block_type, str) or block_type not in BLOCK_TYPES:
            v.bad("Each disclosure block needs a valid 'block_type'.")
        if not isinstance(text, str):
            v.bad("Each disclosure block needs a string 'text'.")
        cleaned.append({"block_type": block_type, "text": text})
    types = [block["block_type"] for block in cleaned]
    if "IDENTIFICATION" not in types or "OPT_OUT" not in types:
        v.bad("'disclosure_blocks' must contain an IDENTIFICATION block and an OPT_OUT block.")
    return cleaned


@bp.post("/compliance/agent-scripts")
@endpoint(["CampaignManager", "ComplianceOfficer"])
def create_script():
    body = payload()
    name = v.req_str(body, "name")
    channel = v.req_enum(body, "channel", CHANNELS)
    blocks = _disclosure_blocks(body)
    recording_consent_mode = v.req_enum(body, "recording_consent_mode", RECORDING_MODES)
    covered_state_codes = v.req_str_list(
        body, "covered_state_codes", min_len=1, pattern=v.STATE_RE
    )

    row = base_row()
    row.update(
        {
            "name": name,
            "channel": channel,
            "disclosure_blocks": blocks,
            "recording_consent_mode": recording_consent_mode,
            "covered_state_codes": list(covered_state_codes),
            "status": "DRAFT",
            "approved_by_user_id": None,
            "approved_at": None,
            "change_note": None,
            "review_cycle_count": 0,
        }
    )
    db.agent_scripts[row["id"]] = row
    return created(public(row))


@bp.get("/compliance/agent-scripts/<script_id>")
@endpoint(["CampaignManager", "ComplianceOfficer", "DialerOperator", "PlatformAdmin"])
def read_script(script_id):
    return ok(public(lookup.agent_script(script_id)))


@bp.post("/compliance/agent-scripts/<script_id>/submit-review")
@endpoint(["CampaignManager", "ComplianceOfficer"])
def submit_review(script_id):
    payload()
    script = lookup.agent_script(script_id)
    if script["status"] != "DRAFT":
        raise ApiError("ERR_SCRIPT_STATE_INVALID", "Only a DRAFT script may be submitted.")
    script["status"] = "IN_REVIEW"
    script["change_note"] = None
    touch(script)
    return ok(public(script))


@bp.post("/compliance/agent-scripts/<script_id>/approve")
@endpoint(["ComplianceOfficer"])
def approve_script(script_id):
    body = payload()
    v.req_str(body, "approval_note")
    script = lookup.agent_script(script_id)
    if script["status"] != "IN_REVIEW":
        raise ApiError("ERR_SCRIPT_STATE_INVALID", "Only an IN_REVIEW script may be approved.")
    script["status"] = "APPROVED"
    script["approved_by_user_id"] = g.user_id
    script["approved_at"] = now_iso()
    touch(script)
    return ok(public(script))


@bp.post("/compliance/agent-scripts/<script_id>/request-changes")
@endpoint(["ComplianceOfficer"])
def request_changes(script_id):
    body = payload()
    change_note = v.req_str(body, "change_note")
    script = lookup.agent_script(script_id)
    if script["status"] != "IN_REVIEW":
        raise ApiError(
            "ERR_SCRIPT_STATE_INVALID", "Only an IN_REVIEW script may be sent back to DRAFT."
        )
    script["status"] = "DRAFT"
    script["change_note"] = change_note
    script["review_cycle_count"] = script["review_cycle_count"] + 1
    touch(script)
    return ok(public(script))
