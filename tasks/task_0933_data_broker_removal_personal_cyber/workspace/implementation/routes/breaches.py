"""Breach events, ingest fan-out and alert triage (PRD §3.6)."""

from flask import Blueprint, request

import calc
import constants as K
import context
import derive
import envelope
import rows
import serializers
import states
from clock import CLOCK, parse_instant
from context import Ctx
from errors import ApiError
from store import DB, ordered

bp = Blueprint("breaches", __name__)

ALL_READ_ROLES = [
    K.ROLE_PLATFORM_ADMIN,
    K.ROLE_PRIVACY_AGENT,
    K.ROLE_ACCOUNT_OWNER,
    K.ROLE_MEMBER,
    K.ROLE_AUDITOR,
]


@bp.post("/breach-events")
def register_breach_event():
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "name", "type": "string", "required": True},
            {"name": "breach_date", "type": "datetime", "required": True},
            {"name": "disclosed_at", "type": "datetime", "required": True},
            {
                "name": "record_types",
                "type": "array",
                "required": True,
                "non_empty": True,
                "item_type": "string",
                "item_enum": K.BREACH_RECORD_TYPES,
            },
            {
                "name": "base_severity_points",
                "type": "integer",
                "required": True,
                "min": 0,
                "max": 40,
            },
        ]
    )
    breach_dt = parse_instant(fields["breach_date"])
    disclosed_dt = parse_instant(fields["disclosed_at"])
    # Rung 10
    if disclosed_dt < breach_dt:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    event = rows.new_row(
        "breach_events",
        {
            "name": fields["name"],
            # Caller-supplied instants echoed verbatim; parsed copies for logic.
            "breach_date": fields["breach_date"],
            "breach_date_dt": breach_dt,
            "disclosed_at": fields["disclosed_at"],
            "disclosed_at_dt": disclosed_dt,
            "record_types": list(fields["record_types"]),
            "base_severity_points": fields["base_severity_points"],
            "ingest_count": 0,
        },
    )
    return envelope.created(serializers.breach_event(event))


@bp.post("/breach-events/<event_id>/ingest")
def ingest_breach(event_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    event = ctx.path("breach_event", event_id)
    ctx.load_body()
    fields = ctx.validate(
        [
            {
                "name": "matched_identifier_values",
                "type": "array",
                "required": True,
                "item_type": "string",
            }
        ]
    )
    wanted = set(fields["matched_identifier_values"])
    # Only identifiers whose owning profile is ACTIVE or PAUSED ever match;
    # duplicate values inside one payload collapse to a single match per row.
    matched = []
    for identifier in DB.identifiers.values():
        if identifier["identifier_value"] not in wanted:
            continue
        profile = DB.profiles.get(identifier["profile_id"])
        if profile is None or profile["status"] not in ("ACTIVE", "PAUSED"):
            continue
        matched.append(identifier)
    matched.sort(key=lambda i: (i["created_at"], i["id"]))

    created = escalated = unchanged = 0
    for identifier in matched:
        profile = DB.profiles.get(identifier["profile_id"])
        has_open_breached = any(
            f["finding_type"] == "BREACHED_PASSWORD" and f["status"] == "OPEN"
            for f in derive.profile_findings(profile["id"])
        )
        points = calc.breach_points(event, identifier, has_open_breached)
        band = calc.severity_band(points)
        existing = None
        for alert in DB.alerts.values():
            if (
                alert["breach_event_id"] == event["id"]
                and alert["identifier_id"] == identifier["id"]
            ):
                existing = alert
                break
        if existing is None:
            rows.new_row(
                "alerts",
                {
                    "breach_event_id": event["id"],
                    "identifier_id": identifier["id"],
                    "member_id": profile["member_id"],
                    "severity": band,
                    "severity_points": points,
                    "status": "NEW",
                    "acknowledged_at": None,
                    "resolved_at": None,
                    "escalation_count": 0,
                },
            )
            created += 1
            continue
        # Adjudication of friction 5: the severity axis declares the edge list
        # LOW->MEDIUM, MEDIUM->HIGH, HIGH->CRITICAL and LOW->HIGH, while the
        # general rule admits any strictly-greater ordinal. The declared list
        # omits MEDIUM->CRITICAL and LOW->CRITICAL. Reachability-maximising
        # reading: the GENERAL monotonicity rule governs, so MEDIUM->CRITICAL
        # and LOW->CRITICAL are admitted. Restricting to the enumerated edges
        # would silently drop legitimate escalations and would contradict two
        # invariants the PRD states outright -- that severity_points is "the
        # highest value ever computed for that alert" and that an alert "can
        # escalate but never de-escalate".
        if K.SEVERITY_ORDINAL[band] > K.SEVERITY_ORDINAL[existing["severity"]]:
            existing["severity"] = band
            existing["severity_points"] = points
            existing["escalation_count"] = existing["escalation_count"] + 1
            rows.touch(existing)
            escalated += 1
        else:
            # A no-op must be observable as a no-op: updated_at and version are
            # NOT bumped.
            unchanged += 1

    event["ingest_count"] = event["ingest_count"] + 1
    rows.touch(event)
    return envelope.ok(
        {
            "breach_event_id": event["id"],
            "ingest_seq": event["ingest_count"],
            "matched_identifier_count": len(matched),
            "created_alert_count": created,
            "escalated_alert_count": escalated,
            "unchanged_alert_count": unchanged,
        }
    )


# --- alerts -----------------------------------------------------------------

def _account_of(alert):
    member = DB.members.get(alert["member_id"])
    return DB.accounts.get(member["account_id"]) if member else None


def _visible(ctx, alert):
    if not ctx.is_scoped_caller:
        return True
    member = DB.members.get(alert["member_id"])
    if member is None or member["account_id"] != ctx.caller_member["account_id"]:
        return False
    if ctx.is_non_primary_member and alert["member_id"] != ctx.caller_member["id"]:
        return False
    return True


@bp.get("/breach-alerts")
def list_alerts():
    ctx = Ctx(request, ALL_READ_ROLES)
    severity = context.enum_filter(request, "severity", K.ALERT_SEVERITIES)
    status = context.enum_filter(request, "status", K.ALERT_STATUSES)
    limit, offset = context.pagination(request)
    event_id = context.plain_filter(request, "breach_event_id")
    identifier_id = context.plain_filter(request, "identifier_id")
    member_id = context.plain_filter(request, "member_id")
    result = []
    for alert in DB.alerts.values():
        if event_id is not None and alert["breach_event_id"] != event_id:
            continue
        if identifier_id is not None and alert["identifier_id"] != identifier_id:
            continue
        if member_id is not None and alert["member_id"] != member_id:
            continue
        if severity is not None and alert["severity"] != severity:
            continue
        if status is not None and alert["status"] != status:
            continue
        if not _visible(ctx, alert):
            continue
        result.append(alert)
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.alert(a) for a in page], limit, offset, total)


@bp.get("/breach-alerts/<alert_id>")
def read_alert(alert_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    alert = ctx.path("alert", alert_id)
    ctx.own(_account_of(alert)["id"], alert["member_id"])
    return envelope.ok(serializers.alert(alert))


@bp.post("/breach-alerts/<alert_id>/acknowledge")
def acknowledge_alert(alert_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    alert = ctx.path("alert", alert_id)
    account = _account_of(alert)
    ctx.own(account["id"], alert["member_id"])
    ctx.write_gates(account)
    states.gate("alert_status", alert["status"], ("NEW",))
    alert["status"] = "ACKNOWLEDGED"
    alert["acknowledged_at"] = CLOCK.now
    rows.touch(alert)
    return envelope.ok(serializers.alert(alert))


@bp.post("/breach-alerts/<alert_id>/resolve")
def resolve_alert(alert_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    alert = ctx.path("alert", alert_id)
    account = _account_of(alert)
    ctx.own(account["id"], alert["member_id"])
    ctx.write_gates(account)
    states.gate("alert_status", alert["status"], ("ACKNOWLEDGED",))
    alert["status"] = "RESOLVED"
    alert["resolved_at"] = CLOCK.now
    rows.touch(alert)
    return envelope.ok(serializers.alert(alert))
