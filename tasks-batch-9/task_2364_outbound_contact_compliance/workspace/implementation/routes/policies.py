"""State calling-window policies, holiday calendars and emergencies (§3.5)."""

from flask import Blueprint

import lookup
import validation as v
from db import base_row, by_created_at, db, now_iso, public, touch
from derive import rows, suspend_campaign
from errors import ApiError
from middleware import endpoint, payload
from response import created, listing, ok
from util import dt_of, hhmm_to_minutes

bp = Blueprint("policies", __name__)

REGIMES = ("ONE_PARTY", "ALL_PARTY")
STATUSES = ("ACTIVE", "SUPERSEDED")
EMERGENCY_STATUSES = ("NONE", "ACTIVE")
READ_ROLES = ["PlatformAdmin", "ComplianceOfficer", "CampaignManager", "DialerOperator"]


def _overlaps(a_from, a_to, b_from, b_to):
    return a_from < b_to and b_from < a_to


@bp.post("/compliance/calling-window-policies")
@endpoint(["PlatformAdmin", "ComplianceOfficer"])
def publish_policy():
    body = payload()
    state_code = v.req_state(body, "state_code")
    window_start_local = v.req_hhmm(body, "window_start_local")
    window_end_local = v.req_hhmm(body, "window_end_local")
    recording_consent_regime = v.req_enum(body, "recording_consent_regime", REGIMES)
    effective_from = v.req_datetime(body, "effective_from")
    effective_to = v.req_datetime(body, "effective_to")
    holiday_dates = v.opt_date_list(body, "holiday_dates", [])
    supersedes_policy_id = v.opt_str(body, "supersedes_policy_id")

    if not dt_of(effective_to) > dt_of(effective_from):
        v.bad("Field 'effective_to' must be strictly after 'effective_from'.")

    superseded = None
    if supersedes_policy_id is not None:
        superseded = lookup.calling_window_policy(supersedes_policy_id)

    start_minutes = hhmm_to_minutes(window_start_local)
    end_minutes = hhmm_to_minutes(window_end_local)
    if not start_minutes < end_minutes:
        raise ApiError(
            "ERR_POLICY_PERIOD_OVERLAP",
            "'window_start_local' must be strictly before 'window_end_local'.",
        )
    if superseded is not None:
        if (
            superseded["status"] != "ACTIVE"
            or superseded["state_code"] != state_code
            or dt_of(effective_from) < dt_of(superseded["effective_from"])
        ):
            raise ApiError(
                "ERR_POLICY_PERIOD_OVERLAP",
                "The superseded policy must be an ACTIVE policy of the same state starting no later.",
            )

    new_from = dt_of(effective_from)
    new_to = dt_of(effective_to)
    for existing in by_created_at(rows("calling_window_policies")):
        if existing["state_code"] != state_code or existing["status"] != "ACTIVE":
            continue
        if superseded is not None and existing["id"] == superseded["id"]:
            continue
        if _overlaps(
            new_from, new_to, dt_of(existing["effective_from"]), dt_of(existing["effective_to"])
        ):
            raise ApiError(
                "ERR_POLICY_PERIOD_OVERLAP",
                "The effective period overlaps an ACTIVE policy for the same state.",
            )

    row = base_row()
    row.update(
        {
            "state_code": state_code,
            "window_start_local": window_start_local,
            "window_end_local": window_end_local,
            "window_start_minutes": start_minutes,
            "window_end_minutes": end_minutes,
            "holiday_dates": list(holiday_dates),
            "recording_consent_regime": recording_consent_regime,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "supersedes_policy_id": supersedes_policy_id,
            "status": "ACTIVE",
            "emergency_status": "NONE",
            "emergency_declared_at": None,
            "emergency_note": None,
        }
    )
    db.calling_window_policies[row["id"]] = row

    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        superseded["effective_to"] = effective_from
        touch(superseded)
    return created(public(row))


@bp.get("/compliance/calling-window-policies/<policy_id>")
@endpoint(READ_ROLES)
def read_policy(policy_id):
    return ok(public(lookup.calling_window_policy(policy_id)))


@bp.get("/compliance/calling-window-policies")
@endpoint(READ_ROLES)
def list_policies():
    limit, offset = v.pagination()
    state_code = v.query_str("state_code")
    supersedes_policy_id = v.query_str("supersedes_policy_id")
    status = v.query_enum("status", STATUSES)
    emergency_status = v.query_enum("emergency_status", EMERGENCY_STATUSES)

    matches = rows("calling_window_policies")
    if state_code is not None:
        matches = [p for p in matches if p["state_code"] == state_code]
    if supersedes_policy_id is not None:
        matches = [p for p in matches if p["supersedes_policy_id"] == supersedes_policy_id]
    if status is not None:
        matches = [p for p in matches if p["status"] == status]
    if emergency_status is not None:
        matches = [p for p in matches if p["emergency_status"] == emergency_status]
    matches = by_created_at(matches)
    page, total = v.paginate(matches, limit, offset)
    return listing([public(p) for p in page], limit, offset, total)


@bp.post("/compliance/calling-window-policies/<policy_id>/declare-emergency")
@endpoint(["PlatformAdmin"])
def declare_emergency(policy_id):
    body = payload()
    emergency_note = v.req_str(body, "emergency_note")
    policy = lookup.calling_window_policy(policy_id)
    if policy["status"] != "ACTIVE" or policy["emergency_status"] != "NONE":
        raise ApiError(
            "ERR_POLICY_STATE_INVALID",
            "Only an ACTIVE policy with no emergency in force may declare one.",
        )

    policy["emergency_status"] = "ACTIVE"
    policy["emergency_declared_at"] = now_iso()
    policy["emergency_note"] = emergency_note
    touch(policy)

    for campaign in by_created_at(rows("campaigns")):
        if campaign["status"] != "ACTIVE":
            continue
        if policy["state_code"] not in campaign["target_state_codes"]:
            continue
        suspend_campaign(campaign, "EMERGENCY_RESTRICTION")
    return ok(public(policy))
