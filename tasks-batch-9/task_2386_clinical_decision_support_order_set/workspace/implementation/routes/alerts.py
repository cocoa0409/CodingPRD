"""Alert lifecycle, burden monitoring windows and raw firing reads (PRD §3.5, §3.7)."""
from flask import Blueprint, request

import const
import validate
from common import add_days, base_record, now, touch
from db import db
from errors import ApiError
from middleware import (authenticate, caller_id, check_freeze, check_read_freeze,
                        get_alert, get_window)
from response import created, ok, paginate
from services import domain

bp = Blueprint("alerts", __name__)


@bp.get("/cds/alerts")
def list_alerts():
    authenticate(const.ANY_ROLE)
    check_read_freeze("alert")
    records = list(db.alerts.values())
    for field in ("content_request_id", "designed_by_clinician_id", "linked_order_set_id",
                  "severity_tier", "review_state", "lifecycle_state",
                  "latest_burden_classification"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return paginate(records)


@bp.get("/cds/alerts/<cid>")
def read_alert(cid):
    authenticate(const.ANY_ROLE)
    alert = get_alert(cid)
    check_read_freeze("alert")
    return ok(alert)


# ------------------------------------------------------------------ activation
@bp.post("/cds/alerts/<cid>/activate")
def activate(cid):
    authenticate(("CommitteeChair",))
    alert = get_alert(cid)
    data = validate.body()
    validate.string(data, "activation_note")

    if alert["lifecycle_state"] != "UNPUBLISHED" or alert["review_state"] != "APPROVED":
        raise ApiError("ERR_ALERT_NOT_APPROVED", "Alert is not an approved, unpublished design")

    check_freeze("alert")

    if alert.get("_deciding_reviewer_id") == caller_id():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The deciding specialty approver may not activate this alert",
        )

    if alert["severity_tier"] == "TIER_1_HARD_STOP":
        if not (alert.get("hard_stop_justification") or "").strip():
            raise ApiError(
                "ERR_TIER1_JUSTIFICATION_REQUIRED",
                "A TIER_1_HARD_STOP alert requires a hard_stop_justification",
            )

    if alert["override_reason_required"]:
        if len(alert["override_reason_codes"] or []) < const.MIN_OVERRIDE_REASON_CODES:
            raise ApiError(
                "ERR_OVERRIDE_REASON_REQUIRED",
                "At least %d override_reason_codes must be declared"
                % const.MIN_OVERRIDE_REASON_CODES,
            )

    if alert["linked_order_set_id"]:
        linked = db.order_sets.get(alert["linked_order_set_id"])
        if linked is None or linked["publication_state"] != "PUBLISHED":
            raise ApiError("ERR_LINKED_ORDER_SET_NOT_PUBLISHED", "Linked order set is not PUBLISHED")

    risk_class = domain.alert_risk_class(alert)
    anchor = now()
    due = add_days(anchor, domain.review_interval_days(risk_class))
    expiration = add_days(due, const.GRACE_PERIOD_DAYS)

    alert["lifecycle_state"] = "ACTIVE"
    domain.apply_schedule_to_alert(alert, due, expiration)
    touch(alert)

    domain.create_annual_task("ALERT", alert, due, expiration, None, cycle_index=1)
    domain.maybe_close_content_request(db.content_requests.get(alert["content_request_id"]))
    return ok(alert)


# ------------------------------------------------------------------ suspend / resume
@bp.post("/cds/alerts/<cid>/suspend")
def suspend(cid):
    authenticate(("CommitteeChair",))
    alert = get_alert(cid)
    data = validate.body()
    reason = validate.string(data, "suspension_reason", required=True)

    if alert["lifecycle_state"] != "ACTIVE":
        raise ApiError("ERR_ALERT_NOT_ACTIVE", "Alert is not ACTIVE")

    check_freeze("alert")

    domain.suspend_alert(alert, reason)
    return ok(alert)


@bp.post("/cds/alerts/<cid>/resume")
def resume(cid):
    authenticate(("CommitteeChair",))
    alert = get_alert(cid)
    data = validate.body()
    validate.string(data, "resume_note")

    if alert["lifecycle_state"] != "SUSPENDED":
        raise ApiError("ERR_ALERT_NOT_SUSPENDED", "Alert is not SUSPENDED")
    if alert["review_state"] != "APPROVED":
        raise ApiError("ERR_ALERT_NOT_APPROVED", "Alert is no longer APPROVED")

    check_freeze("alert")

    if alert["linked_order_set_id"]:
        linked = db.order_sets.get(alert["linked_order_set_id"])
        if linked is None or linked["publication_state"] != "PUBLISHED":
            raise ApiError("ERR_LINKED_ORDER_SET_NOT_PUBLISHED", "Linked order set is not PUBLISHED")

    alert["lifecycle_state"] = "ACTIVE"
    alert["suspension_reason"] = None
    touch(alert)
    return ok(alert)


# ------------------------------------------------------------------ retirement
@bp.post("/cds/alerts/<cid>/retire")
def retire(cid):
    authenticate(("CommitteeChair",))
    alert = get_alert(cid)
    data = validate.body()
    validate.string(data, "retirement_rationale", required=True)

    if alert["lifecycle_state"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_ALERT_NOT_ACTIVE", "Only an ACTIVE or SUSPENDED alert may be retired")

    check_freeze("alert")

    if not domain.retirement_gate_satisfied(alert):
        raise ApiError(
            "ERR_RETIREMENT_CRITERIA_NOT_MET",
            "The low-value retirement gate is not satisfied",
        )

    domain.retire_alert(alert)
    return ok(alert)


# ------------------------------------------------------------------ burden windows
@bp.post("/cds/alerts/<cid>/burden-windows")
def open_window(cid):
    authenticate((const.SYSTEM_ADMIN, "CommitteeChair"))
    alert = get_alert(cid)
    data = validate.body()

    expected_version = validate.integer(data, "expected_alert_version", required=True)
    window_start = validate.instant(data, "window_start", required=True)
    window_end = validate.instant(data, "window_end", required=True)

    if not window_start < window_end:
        raise ApiError("ERR_INVALID_WINDOW_BOUNDS", "window_end must be strictly after window_start")

    if expected_version != alert["version"]:
        raise ApiError("ERR_STALE_ALERT_VERSION", "Alert version is stale")

    check_freeze("alert")

    # Half-open overlap against settled windows only (PRD §3.7).
    for existing in sorted(domain.windows_of_alert(alert["id"]), key=lambda w: w.get("_seq", 0)):
        if existing["state"] not in ("CLOSED", "FINALIZED"):
            continue
        if window_start < existing["window_end"] and existing["window_start"] < window_end:
            raise ApiError(
                "ERR_BURDEN_WINDOW_OVERLAP",
                "The interval overlaps a settled burden window of this alert",
            )

    # An OPEN predecessor is legitimately superseded.
    for existing in sorted(domain.windows_of_alert(alert["id"]), key=lambda w: w.get("_seq", 0)):
        if existing["state"] == "OPEN":
            domain.close_window(existing, alert, "SUPERSEDED_BY_NEW_WINDOW")

    window = base_record()
    window.update({
        "alert_id": alert["id"],
        "window_start": window_start,
        "window_end": window_end,
        "state": "OPEN",
        "severity_tier_snapshot": alert["severity_tier"],
        "fire_count": 0,
        "override_count": 0,
        "accept_count": 0,
        "distinct_fired_clinician_count": 0,
        "distinct_overriding_clinician_count": 0,
        "override_rate": None,
        "volume_factor": None,
        "burden_index": None,
        "burden_index_clinician_weighted": None,
        "burden_classification": None,
        "reopen_count": 0,
        "closure_reason": None,
        "closed_at": None,
    })
    db.burden_windows[window["id"]] = window
    return created(window)


@bp.get("/cds/alerts/<cid>/burden-windows")
def list_windows(cid):
    authenticate(const.ANY_ROLE)
    alert = get_alert(cid)
    check_read_freeze("alert")
    records = domain.windows_of_alert(alert["id"])
    state = request.args.get("state")
    classification = request.args.get("burden_classification")
    if state:
        records = [r for r in records if r["state"] == state]
    if classification:
        records = [r for r in records if r["burden_classification"] == classification]
    return paginate(records)


@bp.post("/cds/alerts/<cid>/burden-windows/<wid>/close")
def close_window(cid, wid):
    authenticate((const.SYSTEM_ADMIN, "CommitteeChair"))
    alert = get_alert(cid)
    window = get_window(alert, wid)
    data = validate.body()
    reason = validate.enum(
        data, "closure_reason", const.CLOSURE_REASONS, default="MANUAL_CLOSE"
    )

    if window["state"] != "OPEN":
        raise ApiError("ERR_BURDEN_WINDOW_NOT_OPEN", "Burden window is not OPEN")

    check_freeze("alert")

    domain.close_window(window, alert, reason)
    return ok(window)


@bp.post("/cds/alerts/<cid>/burden-windows/<wid>/reopen")
def reopen_window(cid, wid):
    authenticate((const.SYSTEM_ADMIN,))
    alert = get_alert(cid)
    window = get_window(alert, wid)
    data = validate.body()
    validate.string(data, "reopen_reason", required=True)

    if window["state"] != "CLOSED":
        raise ApiError("ERR_BURDEN_WINDOW_NOT_CLOSED", "Only a CLOSED window may be reopened")

    for other in domain.windows_of_alert(alert["id"]):
        if other["id"] != window["id"] and other["state"] == "OPEN":
            raise ApiError("ERR_ANOTHER_WINDOW_OPEN", "Another window of this alert is OPEN")

    check_freeze("alert")

    window["state"] = "OPEN"
    window["fire_count"] = 0
    window["override_count"] = 0
    window["accept_count"] = 0
    window["distinct_fired_clinician_count"] = 0
    window["distinct_overriding_clinician_count"] = 0
    window["override_rate"] = None
    window["volume_factor"] = None
    window["burden_index"] = None
    window["burden_index_clinician_weighted"] = None
    window["burden_classification"] = None
    window["closure_reason"] = None
    window["closed_at"] = None
    window["reopen_count"] += 1
    touch(window)

    domain.recompute_alert_ledger(alert)
    return ok(window)


# ------------------------------------------------------------------ raw firings
@bp.get("/cds/alerts/<cid>/override-events")
def list_override_events(cid):
    authenticate(const.ANY_ROLE)
    alert = get_alert(cid)
    check_read_freeze("alert")
    records = domain.events_of_alert(alert["id"])

    accepted = validate.query_bool("accepted")
    if accepted is not None:
        records = [r for r in records if r["accepted"] is accepted]
    code = request.args.get("override_reason_code")
    if code:
        records = [r for r in records if r["override_reason_code"] == code]
    start = validate.query_instant("fired_at_from")
    if start is not None:
        records = [r for r in records if r["fired_at"] >= start]
    end = validate.query_instant("fired_at_to")
    if end is not None:
        records = [r for r in records if r["fired_at"] <= end]

    return paginate(records, sort_key=lambda r: (r["fired_at"], r.get("_seq", 0)))
