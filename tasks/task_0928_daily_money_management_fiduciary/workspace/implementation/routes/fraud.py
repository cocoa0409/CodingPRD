"""Fraud alerts: intake scoring, adjudication and the confirmed-fraud freeze."""

from datetime import timedelta

from flask import Blueprint

from core import calc
from core import constants as K
from core import serialize
from core.aggregates import freeze_sweep, recompute_account
from core.audit import set_client, set_subject
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import audited, authorize, resolve, resolve_body_ref
from core.store import bump, db, new_row

bp = Blueprint("fraud", __name__)

READ_ROLES = ("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer", "PlatformAdmin")


@bp.post("/dmm/fraud-alerts")
@audited("FraudAlert")
def raise_alert():
    ctx = authorize("ComplianceOfficer", "BillPaySpecialist")  # rungs 1-2
    account = resolve_body_ref(ctx, "account_id", "accounts")  # rung 3
    payment = resolve_body_ref(ctx, "payment_id", "payments")
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("account_id", str, True),
        ("payment_id", str, True),
        ("reason_code", str, True),
        ("detail", str, False),
    ])
    ctx.check_enum("reason_code", K.FRAUD_REASON_CODE)         # rung 5

    payee = db.payees.get(payment["payee_id"])
    score = calc.fraud_score(payment, payee)
    band = calc.fraud_band(score)
    created_at = db.now
    row = new_row("fraud_alerts", {
        "account_id": account["id"],
        "payment_id": payment["id"],
        "reason_code": ctx.body["reason_code"],
        "detail": ctx.body.get("detail"),
        "intake_risk_score": score,
        "intake_risk_band": band,
        "review_risk_score": None,
        "review_risk_band": None,
        "ack_due_at": created_at + timedelta(hours=calc.fraud_ack_sla_hours(band)),
        "acknowledged_at": None,
        "status": "NEW",
        "disposition_note": None,
    })
    set_subject(row["id"])
    return object_response(serialize.fraud_alert(row), 201)


@bp.post("/dmm/fraud-alerts/<fid>/disposition")
@audited("FraudAlert", path_param="fid")
def dispose_alert(fid):
    ctx = authorize("ComplianceOfficer")                       # rungs 1-2
    alert = resolve("fraud_alerts", fid)                       # rung 3
    account = db.accounts.get(alert["account_id"])
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("action", str, True),
        ("disposition_note", str, False),
    ])
    ctx.check_enum("action", K.FRAUD_ALERT_ACTION)             # rung 5

    action = ctx.body["action"]
    current = alert["status"]
    if action == "ACKNOWLEDGE":                                # rung 12
        if current not in ("NEW", "ESCALATED"):
            fail("ERR_INVALID_STATE", "The alert cannot be acknowledged from here.")
    else:
        if current != "ACKNOWLEDGED":
            fail("ERR_INVALID_STATE", "The alert must be ACKNOWLEDGED first.")

    if ctx.body.get("disposition_note") is not None:
        alert["disposition_note"] = ctx.body["disposition_note"]

    if action == "ACKNOWLEDGE":
        alert["status"] = "ACKNOWLEDGED"
        alert["acknowledged_at"] = db.now
        # The review variant re-reads settled_payment_count as it stands now.
        payment = db.payments.get(alert["payment_id"])
        payee = db.payees.get(payment["payee_id"])
        review_score = calc.fraud_score(payment, payee)
        alert["review_risk_score"] = review_score
        alert["review_risk_band"] = calc.fraud_band(review_score)
    elif action == "DISMISS":
        alert["status"] = "DISMISSED"
    else:
        alert["status"] = "CONFIRMED_FRAUD"
        if account is not None:
            account["fraud_posture"] = "FROZEN"
            freeze_sweep(account)
            recompute_account(account)
            bump(account)

    bump(alert)
    return object_response(serialize.fraud_alert(alert), 200)


@bp.get("/dmm/fraud-alerts")
def list_alerts():
    authorize(*READ_ROLES)
    rows = db.ordered("fraud_alerts")
    for field in ("account_id", "payment_id", "status"):
        rows = filter_exact(rows, field)
    return paginate(rows, serialize.fraud_alert)


@bp.get("/dmm/fraud-alerts/<fid>")
def read_alert(fid):
    authorize(*READ_ROLES)
    return object_response(serialize.fraud_alert(resolve("fraud_alerts", fid)), 200)
