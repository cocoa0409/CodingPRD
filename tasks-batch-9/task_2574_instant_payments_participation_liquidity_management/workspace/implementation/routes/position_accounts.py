"""The prefunded position: opening, funding, monitoring and alerts."""

from flask import Blueprint

from db import bump, db, new_record
from errors import ApiError
from middleware import authorize, require_scope
from response import created, list_response, object_response
from routes.helpers import query_value
from validation import opt_string, payload, req_enum, req_int, req_id, req_string
from services import liquidity, lookup, serializers
from services.constants import (
    ACKNOWLEDGEABLE_ALERT_STATUSES,
    MIN_PREFUND_CENTS,
    OPERATOR_ENTRY_TYPES,
)

bp = Blueprint("position_accounts", __name__)


@bp.route("/position-accounts", methods=["POST"])
def create_position_account():
    authorize(["LiquidityOfficer"])
    body = payload()
    participant_id = req_id(body, "participant_id")
    participant = lookup.participant(participant_id)
    opening = req_int(body, "opening_balance_cents", minimum=1)
    warning = req_int(body, "warning_threshold_cents", minimum=0)
    critical = req_int(body, "critical_threshold_cents", minimum=0)
    floor = req_int(body, "floor_cents", minimum=0)
    if not (floor <= critical <= warning <= opening):
        raise ApiError(
            "ERR_INVALID_THRESHOLD_ORDERING",
            "The floor, critical threshold, warning threshold and opening balance "
            "must be ordered from lowest to highest.",
        )
    if lookup.account_of_participant(participant_id) is not None:
        raise ApiError(
            "ERR_DUPLICATE_RESOURCE",
            "That participant already holds a prefunded position account.",
        )
    if opening < MIN_PREFUND_CENTS:
        raise ApiError(
            "ERR_PREFUND_BELOW_MINIMUM",
            "The opening deposit must be at least %d cents." % MIN_PREFUND_CENTS,
        )
    account = new_record()
    account.update({
        "participant_id": participant_id,
        "opening_balance_cents": opening,
        "warning_threshold_cents": warning,
        "critical_threshold_cents": critical,
        "floor_cents": floor,
        "alert_tier": "GREEN",
        "last_ledger_sequence_no": 0,
    })
    db.position_accounts[account["id"]] = account
    liquidity.recompute_band(account)
    liquidity.rederive_posture(participant)
    return created(serializers.position_account(account))


@bp.route("/position-accounts/<account_id>", methods=["GET"])
def get_position_account(account_id):
    user_id, role = authorize(["NetworkOperator", "LiquidityOfficer", "ParticipantAdmin", "PaymentOperator"])
    account = lookup.position_account(account_id)
    require_scope(user_id, role, account["participant_id"])
    return object_response(serializers.position_account(account))


@bp.route("/position-accounts/<account_id>/ledger-adjustments", methods=["POST"])
def post_ledger_adjustment(account_id):
    user_id, _role = authorize(["LiquidityOfficer"])
    account = lookup.position_account(account_id)
    body = payload()
    entry_type = req_enum(body, "entry_type", OPERATOR_ENTRY_TYPES)
    magnitude = req_int(body, "magnitude_cents", minimum=1)
    reference = opt_string(body, "reference")
    signed = magnitude if entry_type in ("FUNDING_CREDIT", "RETURN_CREDIT") else -magnitude
    if liquidity.current_balance(account) + signed < 0:
        raise ApiError(
            "ERR_LEDGER_ADJUSTMENT_WOULD_GO_NEGATIVE",
            "The adjustment would take the funded position below zero.",
        )
    entry = liquidity.post_ledger_entry(
        account, entry_type, magnitude, reference=reference, raised_by_user_id=user_id,
    )
    participant = db.participants.get(account["participant_id"])
    if participant is not None:
        liquidity.rederive_posture(participant)
    return created(serializers.ledger_entry(entry))


@bp.route("/position-accounts/<account_id>/ledger-entries", methods=["GET"])
def list_ledger_entries(account_id):
    user_id, role = authorize(["NetworkOperator", "LiquidityOfficer", "ParticipantAdmin", "CoreBankingSystem"])
    account = lookup.position_account(account_id)
    require_scope(user_id, role, account["participant_id"])
    rows = lookup.entries_of_account(account_id)
    entry_type = query_value("entry_type")
    business_date = query_value("business_date")
    related_transfer_id = query_value("related_transfer_id")
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    if business_date is not None:
        rows = [e for e in rows if e["business_date"] == business_date]
    if related_transfer_id is not None:
        rows = [e for e in rows if e["related_transfer_id"] == related_transfer_id]
    return list_response(rows, serializers.ledger_entry)


@bp.route("/position-accounts/<account_id>/alerts", methods=["GET"])
def list_account_alerts(account_id):
    user_id, role = authorize(["NetworkOperator", "LiquidityOfficer", "ParticipantAdmin"])
    account = lookup.position_account(account_id)
    require_scope(user_id, role, account["participant_id"])
    rows = lookup.alerts_of_account(account_id)
    status = query_value("status")
    tier = query_value("tier")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    if tier is not None:
        rows = [a for a in rows if a["tier"] == tier]
    rows.reverse()
    return list_response(rows, serializers.liquidity_alert)


@bp.route("/position-accounts/<account_id>/liquidity-projection", methods=["GET"])
def get_liquidity_projection(account_id):
    user_id, role = authorize(["NetworkOperator", "LiquidityOfficer", "ParticipantAdmin"])
    account = lookup.position_account(account_id)
    require_scope(user_id, role, account["participant_id"])
    return object_response(serializers.projection(liquidity.projection(account)))


@bp.route("/liquidity-alerts/<alert_id>/acknowledgement", methods=["POST"])
def acknowledge_alert(alert_id):
    user_id, _role = authorize(["LiquidityOfficer"])
    alert = lookup.liquidity_alert(alert_id)
    body = payload()
    plan = req_string(body, "remediation_plan")
    if alert["status"] not in ACKNOWLEDGEABLE_ALERT_STATUSES:
        raise ApiError(
            "ERR_ALERT_NOT_ACKNOWLEDGEABLE",
            "Only an OPEN or ESCALATED alert may be acknowledged.",
        )
    if alert.get("_raised_by_user_id") is not None and alert["_raised_by_user_id"] == user_id:
        raise ApiError(
            "ERR_ALERT_SEGREGATION_OF_DUTIES",
            "The officer whose adjustment raised the alert may not acknowledge it.",
        )
    alert["status"] = "ACKNOWLEDGED"
    alert["acknowledged_by_user_id"] = user_id
    alert["remediation_plan"] = plan
    bump(alert)
    return object_response(serializers.liquidity_alert(alert))
