"""Carrier routes: onboarding, lifecycle transitions, billing close, invoice
preview, ROI report (PRD 3.1, 3.8)."""
import calendar
from datetime import date

from flask import Blueprint, request

import db
from db import store
from errors import ApiError
from middleware import body_json, ctx, need_str, require_role
from response import ok
from services import billing
from services.sweep import close_subscription

bp = Blueprint("carriers", __name__)


def _get_carrier_or_404(carrier_id):
    carrier = store.carriers.get(carrier_id)
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND", 404, "carrier id does not exist")
    return carrier


@bp.post("/api/carriers")
def create_carrier():
    _uid, role = ctx()
    require_role(role, ("PlatformAdmin",))
    body = body_json()
    dot = need_str(body, "dot_number")
    name = need_str(body, "legal_name")
    for c in store.carriers.values():
        if c["dot_number"] == dot:
            raise ApiError("ERR_DUPLICATE_DOT_NUMBER", 409, "dot_number already registered")
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "dot_number": dot,
        "legal_name": name,
        "status": "ENROLLED",
        "eligibility_status": "NOT_EVALUATED",
        "latest_snapshot_id": None,
        "latest_iss_score": None,
        "latest_safety_rating": None,
        "credit_balance_cents": 0,
        "credit_ledger": [],
        "closed_billing_periods": [],
        "version": 1,
    }
    db.stamp(rec)
    store.carriers[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/carriers/<carrierId>")
def get_carrier(carrierId):
    ctx()
    return ok(db.public(_get_carrier_or_404(carrierId)), 200)


def _terminate_cascade(carrier):
    """Carrier termination cascades (PRD 3.1): credentials -> DEACTIVATED
    (CARRIER_TERMINATED); subscriptions -> CLOSED (TERMINATED_CARRIER);
    overrides -> REVOKED."""
    for cred in store.credentials.values():
        if cred["carrier_id"] == carrier["id"] and cred["status"] != "DEACTIVATED":
            cred["status"] = "DEACTIVATED"
            cred["status_reason"] = "CARRIER_TERMINATED"
            db.bump(cred)
    for sub in store.subscriptions.values():
        if sub["carrier_id"] == carrier["id"] and sub["status"] in (
            "SCHEDULED",
            "ACTIVE",
            "PAUSED",
        ):
            close_subscription(sub, "TERMINATED_CARRIER")
    for o in store.overrides.values():
        if o["carrier_id"] == carrier["id"] and o["status"] in (
            "REQUESTED",
            "APPROVED",
            "ACTIVE",
        ):
            o["status"] = "REVOKED"
            db.bump(o)


@bp.post("/api/carriers/<carrierId>/transition")
def carrier_transition(carrierId):
    _uid, role = ctx()
    body = body_json()
    to_status = body.get("to_status")
    # Rung 2: role admission is per target state on this endpoint.
    if role not in ("ComplianceOfficer", "PlatformAdmin"):
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "role not admitted for carrier transitions")
    if to_status in ("ACTIVE", "SUSPENDED") and role != "ComplianceOfficer":
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403, "ACTIVE/SUSPENDED transitions require ComplianceOfficer"
        )
    if to_status == "TERMINATED" and role != "PlatformAdmin":
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "TERMINATED requires PlatformAdmin")
    # Rung 4: existence
    carrier = _get_carrier_or_404(carrierId)
    # Rung 5: state-machine legality (valid target states only)
    if to_status in ("ACTIVE", "SUSPENDED", "TERMINATED"):
        cur = carrier["status"]
        legal = (
            (to_status == "ACTIVE" and cur in ("ENROLLED", "SUSPENDED"))
            or (to_status == "SUSPENDED" and cur == "ACTIVE")
            or (to_status == "TERMINATED" and cur in ("ENROLLED", "ACTIVE", "SUSPENDED"))
        )
        if not legal:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"carrier cannot transition from {cur} to {to_status}",
            )
        # Rung 7: business safety gates in pinned order
        if (
            to_status == "ACTIVE"
            and cur == "ENROLLED"
            and carrier["eligibility_status"] not in ("ELIGIBLE", "CONDITIONAL")
        ):
            raise ApiError(
                "ERR_CARRIER_INELIGIBLE_FOR_APPROVAL",
                422,
                "approve-enrollment requires posture ELIGIBLE or CONDITIONAL",
            )
        if (
            to_status == "ACTIVE"
            and cur == "SUSPENDED"
            and carrier["eligibility_status"] == "INELIGIBLE"
        ):
            raise ApiError(
                "ERR_CARRIER_STILL_INELIGIBLE",
                422,
                "reinstate requires posture other than INELIGIBLE",
            )
    else:
        # Rung 12: invalid/missing enum member
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "to_status must be one of ACTIVE, SUSPENDED, TERMINATED"
        )
    if to_status == "TERMINATED":
        _terminate_cascade(carrier)
    carrier["status"] = to_status
    db.bump(carrier)
    return ok(db.public(carrier), 200)


@bp.post("/api/carriers/<carrierId>/close-billing-period")
def close_billing(carrierId):
    _uid, role = ctx()
    require_role(role, ("FinanceAdmin",))
    carrier = _get_carrier_or_404(carrierId)
    body = body_json()
    py = body.get("period_year")
    pm = body.get("period_month")
    # Rung 9: temporal sanity (only evaluable when the period parses)
    period_ok = (
        isinstance(py, int)
        and not isinstance(py, bool)
        and isinstance(pm, int)
        and not isinstance(pm, bool)
        and 1 <= pm <= 12
    )
    if period_ok:
        last = date(py, pm, calendar.monthrange(py, pm)[1])
        if last >= db.today():
            raise ApiError(
                "ERR_BILLING_PERIOD_NOT_CLOSABLE",
                422,
                "billing period has not fully elapsed",
            )
    # Rung 12: field ranges
    if not isinstance(py, int) or isinstance(py, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_year must be an integer")
    if not isinstance(pm, int) or isinstance(pm, bool) or not (1 <= pm <= 12):
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_month must be an integer in 1..12")
    # Rung 13: period uniqueness
    label = f"{py:04d}-{pm:02d}"
    if label in carrier["closed_billing_periods"]:
        raise ApiError(
            "ERR_BILLING_PERIOD_ALREADY_CLOSED", 409, "billing period already closed"
        )
    inv = billing.close_billing_period(carrier, py, pm)
    return ok(db.public(inv), 201)


@bp.get("/api/carriers/<carrierId>/invoice-preview")
def invoice_preview(carrierId):
    ctx()
    carrier = _get_carrier_or_404(carrierId)
    today = db.today()
    raw_y = request.args.get("period_year")
    raw_m = request.args.get("period_month")
    if raw_y is None:
        py = today.year
    else:
        try:
            py = int(raw_y)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "period_year must be an integer")
    if raw_m is None:
        pm = today.month
    else:
        try:
            pm = int(raw_m)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "period_month must be an integer")
        if not (1 <= pm <= 12):
            raise ApiError("ERR_INVALID_REQUEST", 400, "period_month must be in 1..12")
    return ok(billing.invoice_preview(carrier, py, pm), 200)


@bp.get("/api/carriers/<carrierId>/roi-report")
def roi_report(carrierId):
    ctx()
    carrier = _get_carrier_or_404(carrierId)
    raw_y = request.args.get("period_year")
    raw_m = request.args.get("period_month")
    if raw_y is None or raw_m is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_year and period_month are required"
        )
    try:
        py = int(raw_y)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_year must be an integer")
    try:
        pm = int(raw_m)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_month must be an integer")
    if not (1 <= pm <= 12):
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_month must be in 1..12")
    variant = request.args.get("variant", "STANDARD")
    if variant not in ("STANDARD", "CONSERVATIVE"):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "variant must be STANDARD or CONSERVATIVE"
        )
    return ok(billing.roi_report(carrier, py, pm, variant), 200)
