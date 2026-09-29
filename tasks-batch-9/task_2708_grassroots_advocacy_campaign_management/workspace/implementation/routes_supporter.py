"""Supporter and ConsentEvent endpoints (PRD 3.2)."""

from flask import Blueprint

import calc
import gates
import serializers as S
from common import (
    R_COMPLIANCE,
    R_DIRECTOR,
    R_ORGANIZER,
    R_STRATEGIST,
    R_SUPPORTER,
    by_created,
    check_shape,
    db,
    dec,
    err,
    f_enum,
    f_str,
    f_str_list,
    get_body,
    must,
    must_fk,
    new_row,
    now_dt,
    ok,
    ok_list,
    pagination,
    q_bool,
    q_str,
    require_role,
    touch,
)

bp = Blueprint("supporter", __name__)

SOURCES = ("PETITION", "EVENT", "DIGITAL_AD", "REFERRAL")
CONSENT_ACTIONS = ("GRANT", "REVOKE")


def _next_sequence_no(supporter_id):
    existing = calc.consent_events_of(supporter_id)
    if not existing:
        return 1
    return max(int(e["sequence_no"]) for e in existing) + 1


def _append_consent(supporter, channel, action, lawful_basis, source_reference):
    row = new_row(versioned=False)
    row.update(
        {
            "supporter_id": supporter["id"],
            "channel": channel,
            "action": action,
            "lawful_basis": lawful_basis if action == "GRANT" else None,
            "source_reference": source_reference,
            "sequence_no": _next_sequence_no(supporter["id"]),
            "effective_at": row["created_at"],
        }
    )
    db.consent_events[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Supporters
# ---------------------------------------------------------------------------


@bp.post("/advocacy/supporters")
def create_supporter():
    require_role(R_ORGANIZER, R_DIRECTOR)
    body = get_body()
    campaign = must_fk("campaign", body, "campaign_id")
    check_shape(
        body,
        required=("campaign_id", "full_name", "email", "district_code",
                  "acquisition_source"),
        optional=("phone", "initial_consent_channels", "lawful_basis",
                  "consent_source_reference"),
    )
    full_name = f_str(body, "full_name", max_len=120)
    email = f_str(body, "email", max_len=200)
    district = f_str(body, "district_code", max_len=16)
    source = f_enum(body, "acquisition_source", SOURCES)
    phone = f_str(body, "phone", max_len=32, required=False)
    channels = f_str_list(
        body, "initial_consent_channels", choices=calc.CONSENT_CHANNELS, required=False
    )
    lawful_basis = f_str(body, "lawful_basis", max_len=40, required=False)
    source_reference = f_str(
        body, "consent_source_reference", max_len=120, required=False
    )
    if "@" not in email:
        err("ERR_INVALID_REQUEST", "email must contain an '@' character")
    if channels and phone is None and any(c in ("SMS", "PHONE") for c in channels):
        err(
            "ERR_INVALID_REQUEST",
            "phone is required when capturing initial SMS or PHONE consent",
        )
    gates.gate_campaign_active(campaign)
    if channels:
        gates.gate_lawful_basis("GRANT", lawful_basis)
    row = new_row()
    row.update(
        {
            "campaign_id": campaign["id"],
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "district_code": district,
            "acquisition_source": source,
            "email_consent_state": "NONE",
            "sms_consent_state": "NONE",
            "phone_consent_state": "NONE",
            "suppressed": False,
            "consent_event_count": 0,
            "touches_reserved": 0,
            "touches_consumed": 0,
            "action_count": 0,
            "thanked_count": 0,
            "engagement_score": dec("0.00"),
            "retention_score": dec("0.00"),
        }
    )
    db.supporters[row["id"]] = row
    for channel in channels or []:
        _append_consent(row, channel, "GRANT", lawful_basis, source_reference)
    # PRD 3.2: consent replay, then the acquisition-source engagement seed.
    calc.resolve_consent(row)
    row["engagement_score"] = calc.r2(calc.SOURCE_BONUS[source])
    row["version"] = 1
    row["updated_at"] = row["created_at"]
    calc.cascade(campaign, segments=True, reach=True, revalidate=True)
    return ok(S.supporter_out(row), 201)


@bp.get("/advocacy/supporters/<supporter_id>")
def get_supporter(supporter_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    row = must("supporter", supporter_id)
    return ok(S.supporter_out(row))


@bp.get("/advocacy/supporters")
def list_supporters():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    campaign_id = q_str("campaign_id")
    district = q_str("district_code")
    source = q_str("acquisition_source")
    suppressed = q_bool("suppressed")
    rows = by_created(list(db.supporters.values()))
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if district is not None:
        rows = [r for r in rows if r["district_code"] == district]
    if source is not None:
        rows = [r for r in rows if r["acquisition_source"] == source]
    if suppressed is not None:
        rows = [r for r in rows if bool(r["suppressed"]) is suppressed]
    return ok_list([S.supporter_out(r) for r in rows], limit, offset)


@bp.get("/advocacy/supporters/<supporter_id>/consent-events")
def list_supporter_consent_events(supporter_id):
    require_role(R_COMPLIANCE, R_DIRECTOR, R_SUPPORTER)
    must("supporter", supporter_id)
    gates.gate_owner_supporter(supporter_id)
    limit, offset = pagination()
    channel = q_str("channel")
    rows = calc.consent_events_of(supporter_id)
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    return ok_list([S.consent_event_out(r) for r in rows], limit, offset)


@bp.get("/advocacy/supporters/<supporter_id>/spokesperson-profiles")
def list_supporter_profiles(supporter_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_SUPPORTER)
    must("supporter", supporter_id)
    gates.gate_owner_supporter(supporter_id)
    limit, offset = pagination()
    rows = calc.profiles_of_supporter(supporter_id)
    return ok_list([S.spokesperson_out(r) for r in rows], limit, offset)


# ---------------------------------------------------------------------------
# Consent events
# ---------------------------------------------------------------------------


@bp.post("/advocacy/consent-events")
def create_consent_event():
    require_role(R_COMPLIANCE, R_ORGANIZER, R_SUPPORTER)
    body = get_body()
    supporter = must_fk("supporter", body, "supporter_id")
    check_shape(
        body,
        required=("supporter_id", "channel", "action", "source_reference"),
        optional=("lawful_basis",),
    )
    channel = f_enum(body, "channel", calc.CONSENT_CHANNELS)
    action = f_enum(body, "action", CONSENT_ACTIONS)
    source_reference = f_str(body, "source_reference", max_len=120)
    lawful_basis = f_str(body, "lawful_basis", max_len=40, required=False)
    gates.gate_owner_supporter(supporter["id"])
    campaign = db.campaigns[supporter["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_lawful_basis(action, lawful_basis)
    row = _append_consent(supporter, channel, action, lawful_basis, source_reference)
    calc.resolve_consent(supporter)
    calc.cascade(campaign, segments=True, reach=True, revalidate=True)
    return ok(S.consent_event_out(row), 201)


@bp.get("/advocacy/consent-events")
def list_consent_events():
    require_role(R_COMPLIANCE, R_DIRECTOR)
    limit, offset = pagination()
    supporter_id = q_str("supporter_id")
    channel = q_str("channel")
    action = q_str("action")
    rows = sorted(
        db.consent_events.values(),
        key=lambda e: (e["created_at"], e["sequence_no"], e["_seq"]),
    )
    if supporter_id is not None:
        rows = [r for r in rows if r["supporter_id"] == supporter_id]
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if action is not None:
        rows = [r for r in rows if r["action"] == action]
    return ok_list([S.consent_event_out(r) for r in rows], limit, offset)


@bp.get("/advocacy/consent-events/<consent_event_id>")
def get_consent_event(consent_event_id):
    require_role(R_COMPLIANCE, R_DIRECTOR, R_SUPPORTER)
    row = must("consent_event", consent_event_id)
    gates.gate_owner_supporter(row["supporter_id"])
    return ok(S.consent_event_out(row))
