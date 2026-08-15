"""FraudAlert endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("fraud_alerts", __name__)

VALID_RESOLUTIONS = {"FRAUD", "LEGIT"}
VALID_RESPOND_OUTCOMES = {"CONFIRMED_FRAUD", "CONFIRMED_LEGIT"}


def _txn_active_chargeback_credit_cents(txn_id: str) -> int:
    s = 0
    for c in db.chargeback_cases.values():
        if c["auth_transaction_id"] == txn_id and c["cb_status"] in (
            "PROVISIONAL_CREDIT_POSTED",
            "REPRESENTMENT_FILED",
            "RESOLVED_WON",
        ):
            s += c["provisional_credit_cents"]
    return s


def _txn_fraud_credit_cents(txn_id: str, exclude_alert_id: str | None = None) -> int:
    s = 0
    for a in db.fraud_alerts.values():
        if a["auth_transaction_id"] == txn_id and a["alert_status"] == "RESOLVED_FRAUD":
            if exclude_alert_id and a["id"] == exclude_alert_id:
                continue
            s += a["fraud_credit_cents"]
    return s


def _check_duplicate_credit_cap(txn_id: str, additional: int, exclude_alert_id: str | None = None) -> None:
    t = db.auth_transactions[txn_id]
    existing = _txn_active_chargeback_credit_cents(txn_id) + _txn_fraud_credit_cents(txn_id, exclude_alert_id=exclude_alert_id)
    if existing + additional > t["amount_cents"]:
        raise errors.err_duplicate_credit()


def _resolve_alert(alert: dict, resolution: str, fraud_credit_cents: int | None,
                   via_respond: bool) -> dict:
    """Shared resolution logic for analyst resolve and cardholder respond."""
    if alert["alert_status"] not in ("IN_REVIEW", "CONTACT_PENDING"):
        raise errors.err_invalid_state("Alert must be IN_REVIEW or CONTACT_PENDING to resolve")

    # contact freshness check
    last_res = alert.get("resolved_at")
    needed_outcome = "CONFIRMED_FRAUD" if resolution == "FRAUD" else "CONFIRMED_LEGIT"
    match = False
    for c in db.verification_contacts.values():
        if c["alert_id"] != alert["id"]:
            continue
        if c["contact_status"] != "COMPLETED":
            continue
        if c["outcome"] != needed_outcome:
            continue
        if last_res and c["contacted_at"] <= last_res:
            continue
        match = True
        break
    if not match:
        raise errors.err_contact_required()

    if resolution == "LEGIT":
        if fraud_credit_cents not in (None, 0):
            raise errors.err_invalid_request("fraud_credit_cents must be absent or 0 on LEGIT")
        fraud_credit_cents = 0
    else:
        if fraud_credit_cents is None:
            fraud_credit_cents = 0
        if not isinstance(fraud_credit_cents, int) or isinstance(fraud_credit_cents, bool) or fraud_credit_cents < 0:
            raise errors.err_invalid_request("fraud_credit_cents must be a non-negative integer")
        # duplicate-credit cap if a transaction is linked
        if alert.get("auth_transaction_id"):
            _check_duplicate_credit_cap(alert["auth_transaction_id"], fraud_credit_cents, exclude_alert_id=alert["id"])

    alert["alert_status"] = "RESOLVED_FRAUD" if resolution == "FRAUD" else "RESOLVED_LEGIT"
    alert["resolution"] = resolution
    alert["fraud_credit_cents"] = fraud_credit_cents
    alert["resolved_at"] = db.get_clock_iso()
    middleware.touch(alert)

    # side effects
    if alert.get("auth_transaction_id"):
        t = db.auth_transactions[alert["auth_transaction_id"]]
        t["final_disposition"] = "CONFIRMED_FRAUD" if resolution == "FRAUD" else "CONFIRMED_LEGIT"
        middleware.touch(t)

    if resolution == "FRAUD" and alert.get("card_id"):
        card = db.cards.get(alert["card_id"])
        if card and card["card_status"] == "ACTIVE":
            card["card_status"] = "SOFT_BLOCKED"
            card["block_reason"] = "CONFIRMED_FRAUD"
            middleware.touch(card)

    domain._recompute_account(alert["account_id"])
    return alert


@bp.route("/fraudops/fraud-alerts", methods=["POST"])
def create_manual_alert():
    middleware.require_role("FraudAnalyst")
    body = request.get_json(silent=True) or {}
    account_id = body.get("account_id")
    card_id = body.get("card_id")
    auth_txn_id = body.get("auth_transaction_id")

    if not isinstance(account_id, str) or not account_id:
        raise errors.err_invalid_request("account_id is required")
    if not isinstance(card_id, str) or not card_id:
        raise errors.err_invalid_request("card_id is required")

    account = db.accounts.get(account_id)
    if not account:
        raise errors.err_not_found("Account not found")
    card = db.cards.get(card_id)
    if not card:
        raise errors.err_not_found("Card not found")
    if auth_txn_id is not None:
        if not isinstance(auth_txn_id, str):
            raise errors.err_invalid_request("auth_transaction_id must be a string")
        t = db.auth_transactions.get(auth_txn_id)
        if not t:
            raise errors.err_not_found("AuthTransaction not found")
        if t["account_id"] != account_id:
            raise errors.err_invalid_request("auth_transaction_id does not belong to account")
    if card["account_id"] != account_id:
        raise errors.err_invalid_request("card does not belong to account")

    alert = domain.create_alert(
        account_id=account_id,
        card_id=card_id,
        auth_transaction_id=auth_txn_id,
        source="MANUAL",
        band_points=25,
    )
    return response.success(domain.ser_alert(alert), status_code=201)


@bp.route("/fraudops/fraud-alerts", methods=["GET"])
def list_alerts():
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    args = request.args

    # lazy expiry for all alerts (queue order depends on this)
    domain._apply_alert_expiry_all()

    items = list(db.fraud_alerts.values())
    for key in ("account_id", "card_id", "auth_transaction_id", "alert_status", "assigned_to_user_id"):
        v = args.get(key)
        if v:
            items = [a for a in items if a.get(key) == v]

    # queue order: when filtering by OPEN, order by priority DESC, created_at ASC
    if args.get("alert_status") == "OPEN":
        items.sort(key=lambda a: (-a["priority"], a["created_at"], a["id"]))
    else:
        items.sort(key=lambda a: (a["created_at"], a["id"]))

    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_alert(a) for a in sliced], pagination=pg)


@bp.route("/fraudops/fraud-alerts/<aid>", methods=["GET"])
def get_alert(aid):
    user_id, role = middleware.require_role("FraudAnalyst", "FraudOpsManager", "Cardholder")
    a = db.fraud_alerts.get(aid)
    if not a:
        raise errors.err_not_found("FraudAlert not found")
    domain._apply_alert_expiry(a)
    if role == "Cardholder" and user_id != a["account_id"]:
        raise errors.err_not_resource_owner()
    return response.success(domain.ser_alert(a))


@bp.route("/fraudops/fraud-alerts/<aid>/claim", methods=["POST"])
def claim_alert(aid):
    user_id, _ = middleware.require_role("FraudAnalyst")
    a = db.fraud_alerts.get(aid)
    if not a:
        raise errors.err_not_found("FraudAlert not found")
    domain._apply_alert_expiry(a)
    if a["alert_status"] != "OPEN":
        raise errors.err_invalid_state("Alert is not OPEN")
    a["alert_status"] = "IN_REVIEW"
    a["assigned_to_user_id"] = user_id
    middleware.touch(a)
    return response.success(domain.ser_alert(a))


@bp.route("/fraudops/fraud-alerts/<aid>/resolve", methods=["POST"])
def resolve_alert(aid):
    user_id, _ = middleware.require_role("FraudAnalyst")
    a = db.fraud_alerts.get(aid)
    if not a:
        raise errors.err_not_found("FraudAlert not found")
    domain._apply_alert_expiry(a)
    body = request.get_json(silent=True) or {}
    resolution = body.get("resolution")
    fraud_credit = body.get("fraud_credit_cents")
    if resolution not in VALID_RESOLUTIONS:
        raise errors.err_invalid_request("resolution must be FRAUD or LEGIT")
    # custody check
    if a["alert_status"] in ("IN_REVIEW", "CONTACT_PENDING") and a["assigned_to_user_id"] != user_id:
        raise errors.err_forbidden_role("Alert is assigned to another analyst")
    _resolve_alert(a, resolution, fraud_credit, via_respond=False)
    return response.success(domain.ser_alert(a))


@bp.route("/fraudops/fraud-alerts/<aid>/respond", methods=["POST"])
def respond_alert(aid):
    user_id, role = middleware.require_role("Cardholder")
    a = db.fraud_alerts.get(aid)
    if not a:
        raise errors.err_not_found("FraudAlert not found")
    domain._apply_alert_expiry(a)
    if user_id != a["account_id"]:
        raise errors.err_not_resource_owner()
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in VALID_RESPOND_OUTCOMES:
        raise errors.err_invalid_request("outcome must be CONFIRMED_FRAUD or CONFIRMED_LEGIT")

    if a["alert_status"] in ("RESOLVED_FRAUD", "RESOLVED_LEGIT", "EXPIRED"):
        raise errors.err_invalid_state("Alert cannot be resolved from its current state")

    # create IN_APP COMPLETED contact
    contact = middleware.stamp_new(
        {
            "alert_id": a["id"],
            "account_id": a["account_id"],
            "channel": "IN_APP",
            "contact_status": "COMPLETED",
            "outcome": outcome,
            "contacted_at": db.get_clock_iso(),
            "created_by_user_id": "SYSTEM",
        }
    )
    db.verification_contacts[contact["id"]] = contact

    # If the alert was OPEN, the respond path bypasses claim: transition to IN_REVIEW first
    if a["alert_status"] == "OPEN":
        a["alert_status"] = "IN_REVIEW"
        # assigned_to_user_id stays None on the respond path

    resolution = "FRAUD" if outcome == "CONFIRMED_FRAUD" else "LEGIT"
    _resolve_alert(a, resolution, None, via_respond=True)
    return response.success(domain.ser_alert(a))


@bp.route("/fraudops/fraud-alerts/<aid>/reopen", methods=["POST"])
def reopen_alert(aid):
    user_id, role = middleware.require_role("FraudAnalyst", "FraudOpsManager")
    a = db.fraud_alerts.get(aid)
    if not a:
        raise errors.err_not_found("FraudAlert not found")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise errors.err_invalid_request("reason is required")
    if a["alert_status"] not in ("RESOLVED_FRAUD", "RESOLVED_LEGIT"):
        raise errors.err_invalid_state("Alert is not in a resolved state")
    if a["reopen_count"] >= 2:
        raise errors.err_reopen_limit_exceeded()
    resolved_at = db._parse_iso(a["resolved_at"])
    if db.get_clock() >= resolved_at + timedelta(days=30):
        raise errors.err_invalid_state("Reopen window has passed")

    was_fraud = a["alert_status"] == "RESOLVED_FRAUD"
    a["alert_status"] = "IN_REVIEW"
    a["reopen_count"] += 1
    middleware.touch(a)
    if was_fraud:
        # fraud credit stops counting (account recompute handles this since status changed)
        pass
    domain._recompute_account(a["account_id"])
    return response.success(domain.ser_alert(a))
