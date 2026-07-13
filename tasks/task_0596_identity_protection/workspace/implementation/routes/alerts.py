from flask import Blueprint, request

from db import by_seq, db, fmt_dt, new_row, touch
from errors import ApiError
from middleware import (
    auth,
    body,
    must_exist,
    must_exist_fk,
    req_enum,
    req_str,
    require_enrollment_active,
    require_subscriber_owner,
)
from response import ok, ok_list, paginate, read_pagination
from serializers import ser, ser_many
from services import calc
from services.alerts import create_alert

bp = Blueprint("alerts", __name__)

ALERT_TYPES = ("DARK_WEB", "SSN_TRACE", "ACCOUNT_TAKEOVER", "CREDIT_INQUIRY")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


@bp.post("/idp/alerts")
def ingest_alert():
    auth("PlatformAdmin")
    data = body()

    subscriber = must_exist_fk("subscribers", data, "subscriber_id")
    member = must_exist_fk("family_members", data, "family_member_id")

    if subscriber is None:
        req_str(data, "subscriber_id")
    alert_type = req_enum(data, "alert_type", ALERT_TYPES)
    severity = req_enum(data, "severity", SEVERITIES)
    source_detail = req_str(data, "source_detail")

    require_enrollment_active(subscriber)

    if member is not None:
        if member["subscriber_id"] != subscriber["id"]:
            raise ApiError(
                "ERR_FAMILY_MEMBER_MISMATCH",
                "The family member belongs to a different subscriber.",
            )
        if member["monitoring_status"] == "NOT_COVERED":
            raise ApiError(
                "ERR_CHILD_MONITORING_NOT_INCLUDED",
                "This dependent is not covered by the subscriber's plan.",
            )

    alert = create_alert(
        subscriber_id=subscriber["id"],
        family_member_id=member["id"] if member is not None else None,
        alert_type=alert_type,
        severity=severity,
        source_detail=source_detail,
    )

    calc.recompute_risk(subscriber)
    touch(subscriber)
    return ok(ser(alert), 201)


@bp.get("/idp/alerts")
def list_alerts():
    role, user_id = auth(
        "Subscriber", "PlatformAdmin", "ClaimsAdjuster", "RestorationSpecialist"
    )
    limit, offset = read_pagination()

    rows = list(db.alerts.values())
    if role == "Subscriber":
        rows = [a for a in rows if a["subscriber_id"] == user_id]

    subscriber_id = request.args.get("subscriber_id")
    if subscriber_id:
        rows = [a for a in rows if a["subscriber_id"] == subscriber_id]
    family_member_id = request.args.get("family_member_id")
    if family_member_id:
        rows = [a for a in rows if a["family_member_id"] == family_member_id]
    status = request.args.get("status")
    if status:
        rows = [a for a in rows if a["status"] == status]

    rows = by_seq(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_many(page), limit, offset, total)


@bp.get("/idp/alerts/<alert_id>")
def read_alert(alert_id):
    role, user_id = auth(
        "Subscriber", "PlatformAdmin", "ClaimsAdjuster", "RestorationSpecialist"
    )
    alert = must_exist("alerts", alert_id)
    require_subscriber_owner(role, user_id, alert["subscriber_id"])
    return ok(ser(alert))


def _triage_target(alert_id, allowed_roles):
    role, user_id = auth(*allowed_roles)
    alert = must_exist("alerts", alert_id)
    require_subscriber_owner(role, user_id, alert["subscriber_id"])
    subscriber = db.subscribers[alert["subscriber_id"]]
    return alert, subscriber


@bp.post("/idp/alerts/<alert_id>/acknowledge")
def acknowledge(alert_id):
    alert, subscriber = _triage_target(alert_id, ("Subscriber", "PlatformAdmin"))
    body()

    if alert["status"] != "NEW":
        raise ApiError("ERR_INVALID_STATE", "Alert is not NEW.")
    require_enrollment_active(subscriber)

    alert["status"] = "ACKNOWLEDGED"
    touch(alert)
    calc.recompute_risk(subscriber)
    touch(subscriber)
    return ok(ser(alert))


@bp.post("/idp/alerts/<alert_id>/confirm-fraud")
def confirm_fraud(alert_id):
    alert, subscriber = _triage_target(alert_id, ("Subscriber", "PlatformAdmin"))
    body()

    if alert["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", "Alert is not ACKNOWLEDGED.")
    require_enrollment_active(subscriber)

    alert["status"] = "CONFIRMED_FRAUD"
    touch(alert)

    plan = db.plans[subscriber["plan_id"]]
    case = new_row(
        subscriber_id=alert["subscriber_id"],
        origin_alert_id=alert["id"],
        specialist_id=None,
        status="OPEN",
        required_specialist_tier=calc.required_specialist_tier(
            alert["severity"], plan["min_specialist_tier"]
        ),
        info_request=None,
        info_response=None,
        resolution_summary=None,
    )
    db.cases[case["id"]] = case

    calc.recompute_risk(subscriber)
    touch(subscriber)
    return ok(ser(alert))


@bp.post("/idp/alerts/<alert_id>/dismiss")
def dismiss(alert_id):
    alert, subscriber = _triage_target(alert_id, ("Subscriber", "PlatformAdmin"))
    data = body()
    reason = req_str(data, "dismissal_reason")

    if alert["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", "Alert is not ACKNOWLEDGED.")
    require_enrollment_active(subscriber)

    alert["status"] = "DISMISSED"
    alert["dismissal_reason"] = reason
    touch(alert)

    calc.recompute_risk(subscriber)
    touch(subscriber)
    return ok(ser(alert))


@bp.post("/idp/alerts/<alert_id>/escalate")
def escalate(alert_id):
    auth("PlatformAdmin")
    alert = must_exist("alerts", alert_id)
    subscriber = db.subscribers[alert["subscriber_id"]]
    body()

    if alert["status"] != "CONFIRMED_FRAUD":
        raise ApiError("ERR_INVALID_STATE", "Alert is not CONFIRMED_FRAUD.")
    require_enrollment_active(subscriber)

    # Pinned order (PRD §3.5): snapshot the PERSISTED risk_score first.
    snapshot = subscriber["risk_score"] or 0
    tier = calc.alert_escalation_tier(snapshot, alert["severity"])

    alert["status"] = "ESCALATED"
    alert["escalation_tier"] = tier
    alert["escalation_deadline"] = fmt_dt(calc.escalation_deadline(tier))
    touch(alert)

    # Only now do the risk variants see the ESCALATED alert.
    calc.recompute_risk(subscriber)
    touch(subscriber)

    for case in db.cases.values():
        if case["origin_alert_id"] == alert["id"]:
            case["required_specialist_tier"] = calc.max_tier(
                tier, case["required_specialist_tier"]
            )
            touch(case)

    return ok(ser(alert))
