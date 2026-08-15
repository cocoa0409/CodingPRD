"""StructuringAlert endpoints."""
from flask import Blueprint, request

from db import now_iso, parse_date_strict, stamp_new, store, touch
from errors import (
    ERR_ALERT_NOT_FOUND,
    ERR_ALERT_WINDOW_OVERLAP,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ApiError,
    bad_request,
)
from middleware import authenticate, body, f_date, f_str, sorted_page
from response import ok, ok_list
from serializers import serialize_alert
from services.audit import main_event

bp = Blueprint("alerts", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]
LIVE_ALERT_STATUSES = ("OPEN", "UNDER_REVIEW")


def get_alert_or_404(alert_id):
    a = store.alerts.get(alert_id)
    if a is None:
        raise ApiError(ERR_ALERT_NOT_FOUND, "Structuring alert not found", 404)
    return a


def windows_overlap(start_a, end_a, start_b, end_b):
    """Closed-interval date semantics: sharing at least one date conflicts;
    touching-but-disjoint windows do not."""
    return start_a <= end_b and start_b <= end_a


@bp.post("/structuring-alerts")
def create_alert():
    authenticate(["BSAOfficer"])
    b = body()
    customer_id = f_str(b, "customer_id")
    ws_raw, ws = f_date(b, "window_start_date")
    we_raw, we = f_date(b, "window_end_date")
    note = f_str(b, "note")
    # Shape-level window checks: start on or before end, span at most 31 days.
    if ws > we or (we - ws).days > 31:
        raise bad_request(
            "Alert window start must be on or before end with a span of at most 31 days"
        )
    customer = store.customers.get(customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "Customer not found", 404)
    for a in store.alerts.values():
        if a["customer_id"] != customer_id or a["status"] not in LIVE_ALERT_STATUSES:
            continue
        a_start = parse_date_strict(a["window_start_date"])
        a_end = parse_date_strict(a["window_end_date"])
        if a_start is not None and a_end is not None and windows_overlap(ws, we, a_start, a_end):
            raise ApiError(
                ERR_ALERT_WINDOW_OVERLAP,
                "Alert window overlaps a live alert for this customer",
                422,
            )
    alert = {
        "customer_id": customer_id,
        "detection_source": "MANUAL",
        "window_start_date": ws_raw,
        "window_end_date": we_raw,
        "detected_amount_cents": 0,
        "distinct_day_count": 0,
        "distinct_branch_count": 0,
        "risk_score": 0,
        "status": "OPEN",
        "note": note,
        "referred_at": None,
    }
    stamp_new(alert)
    store.alerts[alert["id"]] = alert
    main_event(
        "POST /structuring-alerts", "StructuringAlert", alert["id"], None,
        serialize_alert(alert),
    )
    return ok(serialize_alert(alert), status=201)


@bp.get("/structuring-alerts")
def list_alerts():
    authenticate(ALL_ROLES)
    items = list(store.alerts.values())
    for param in ("customer_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a[param] == value]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_alert(a) for a in page], limit, offset, total)


@bp.get("/structuring-alerts/<alert_id>")
def get_alert(alert_id):
    authenticate(ALL_ROLES)
    return ok(serialize_alert(get_alert_or_404(alert_id)))


@bp.post("/structuring-alerts/<alert_id>/begin-review")
def begin_review(alert_id):
    authenticate(["ComplianceAnalyst"])
    alert = get_alert_or_404(alert_id)
    if alert["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Alert is not OPEN", 409)
    before = serialize_alert(alert)
    alert["status"] = "UNDER_REVIEW"
    touch(alert)
    main_event(
        "POST /structuring-alerts/{id}/begin-review", "StructuringAlert",
        alert["id"], before, serialize_alert(alert),
    )
    return ok(serialize_alert(alert))


@bp.post("/structuring-alerts/<alert_id>/dismiss")
def dismiss_alert(alert_id):
    authenticate(["BSAOfficer"])
    b = body()
    disposition_note = f_str(b, "disposition_note")
    alert = get_alert_or_404(alert_id)
    if alert["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Alert is not UNDER_REVIEW", 409)
    before = serialize_alert(alert)
    alert["status"] = "DISMISSED"
    alert["note"] = disposition_note
    touch(alert)
    main_event(
        "POST /structuring-alerts/{id}/dismiss", "StructuringAlert",
        alert["id"], before, serialize_alert(alert),
    )
    return ok(serialize_alert(alert))


@bp.post("/structuring-alerts/<alert_id>/refer")
def refer_alert(alert_id):
    authenticate(["BSAOfficer"])
    b = body()
    referral_note = f_str(b, "referral_note")
    alert = get_alert_or_404(alert_id)
    if alert["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Alert is not UNDER_REVIEW", 409)
    before = serialize_alert(alert)
    alert["status"] = "REFERRED"
    alert["referred_at"] = now_iso()
    alert["note"] = referral_note
    touch(alert)
    customer = store.customers.get(alert["customer_id"])
    if customer is not None:
        customer["structuring_referral_count"] += 1
        touch(customer)
    main_event(
        "POST /structuring-alerts/{id}/refer", "StructuringAlert",
        alert["id"], before, serialize_alert(alert),
    )
    return ok(serialize_alert(alert))


@bp.post("/structuring-alerts/<alert_id>/reopen")
def reopen_alert(alert_id):
    authenticate(["BSAOfficer"])
    b = body()
    note = f_str(b, "note")
    alert = get_alert_or_404(alert_id)
    if alert["status"] != "DISMISSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Alert is not DISMISSED", 409)
    before = serialize_alert(alert)
    alert["status"] = "UNDER_REVIEW"
    alert["note"] = note
    touch(alert)
    main_event(
        "POST /structuring-alerts/{id}/reopen", "StructuringAlert",
        alert["id"], before, serialize_alert(alert),
    )
    return ok(serialize_alert(alert))
