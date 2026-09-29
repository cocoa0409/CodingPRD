"""Segment limit policies and customer deposit accounts."""

from flask import Blueprint

from db import bump, db, new_record, now
from errors import ApiError
from middleware import authorize, require_scope
from response import created, object_response
from timeutils import parse_instant
from validation import opt_bool, opt_id, payload, req_enum, req_int, req_id, req_string
from services import lookup, serializers
from services.constants import SEGMENTS

bp = Blueprint("configuration", __name__)

POSITIVE_INFINITY = None


def _overlaps(a_from, a_to, b_from, b_to):
    """Half-open window intersection; a null end is unbounded."""
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


@bp.route("/segment-policies", methods=["POST"])
def create_segment_policy():
    user_id, role = authorize(["ParticipantAdmin"])
    body = payload()
    raw_participant = opt_id(body, "participant_id")
    if raw_participant is not None:
        require_scope(user_id, role, raw_participant)
    participant_id = req_id(body, "participant_id")
    participant = lookup.participant(participant_id)

    segment = req_enum(body, "segment", SEGMENTS)
    per_transaction = req_int(body, "per_transaction_limit_cents", minimum=1)
    daily_aggregate = req_int(body, "daily_aggregate_limit_cents", minimum=1)
    window_count = req_int(body, "rolling_window_count_limit", minimum=1)
    window_amount = req_int(body, "rolling_window_amount_limit_cents", minimum=1)
    effective_from = parse_instant(req_string(body, "effective_from"))
    raw_to = body.get("effective_to")
    effective_to = parse_instant(raw_to) if raw_to is not None else None
    supersede = opt_bool(body, "supersede_open_ended", False)
    expected_version = req_int(body, "expected_participant_version")
    if daily_aggregate < per_transaction:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "daily_aggregate_limit_cents must be at least per_transaction_limit_cents.",
        )
    if effective_to is not None and effective_to <= effective_from:
        raise ApiError(
            "ERR_INVALID_INTERVAL",
            "effective_to must be strictly later than effective_from.",
        )
    if expected_version != participant["version"]:
        raise ApiError(
            "ERR_STALE_PARTICIPANT_VERSION",
            "The participant version has advanced since it was read.",
        )
    if participant["enrollment_status"] != "LIVE":
        raise ApiError(
            "ERR_PARTICIPANT_NOT_LIVE",
            "Only a LIVE participant may publish segment policies.",
        )

    incumbents = [
        p for p in db.segment_policies.values()
        if p["participant_id"] == participant_id
        and p["segment"] == segment
        and p["superseded_at"] is None
    ]
    to_close = []
    for incumbent in incumbents:
        if (supersede and incumbent["effective_to"] is None
                and incumbent["effective_from"] <= effective_from):
            to_close.append(incumbent)
            continue
        if _overlaps(effective_from, effective_to,
                     incumbent["effective_from"], incumbent["effective_to"]):
            raise ApiError(
                "ERR_POLICY_WINDOW_OVERLAP",
                "Another policy window for that participant and segment overlaps this one.",
            )
    for incumbent in to_close:
        incumbent["effective_to"] = effective_from
        incumbent["superseded_at"] = now()
        bump(incumbent)

    policy = new_record()
    policy.update({
        "participant_id": participant_id,
        "segment": segment,
        "per_transaction_limit_cents": per_transaction,
        "daily_aggregate_limit_cents": daily_aggregate,
        "rolling_window_count_limit": window_count,
        "rolling_window_amount_limit_cents": window_amount,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "superseded_at": None,
    })
    db.segment_policies[policy["id"]] = policy
    bump(participant)
    return created(serializers.segment_policy(policy))


@bp.route("/customer-accounts", methods=["POST"])
def create_customer_account():
    user_id, role = authorize(["ParticipantAdmin"])
    body = payload()
    raw_participant = opt_id(body, "participant_id")
    if raw_participant is not None:
        require_scope(user_id, role, raw_participant)
    participant_id = req_id(body, "participant_id")
    participant = lookup.participant(participant_id)

    segment = req_enum(body, "segment", SEGMENTS)
    reference = req_string(body, "account_reference")
    baseline = req_int(body, "fraud_risk_baseline", minimum=0)
    if baseline > 100:
        raise ApiError("ERR_INVALID_REQUEST", "fraud_risk_baseline must be between 0 and 100.")
    if participant["enrollment_status"] != "LIVE":
        raise ApiError(
            "ERR_PARTICIPANT_NOT_LIVE",
            "Only a LIVE participant may register customer accounts.",
        )
    for row in db.customer_accounts.values():
        if row["participant_id"] == participant_id and row["account_reference"] == reference:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                "That account reference is already registered for the participant.",
            )
    account = new_record()
    account.update({
        "participant_id": participant_id,
        "segment": segment,
        "account_reference": reference,
        "fraud_risk_baseline": baseline,
        "status": "ACTIVE",
        "restricted_at": None,
    })
    db.customer_accounts[account["id"]] = account
    return created(serializers.customer_account(account))


@bp.route("/customer-accounts/<account_id>", methods=["GET"])
def get_customer_account(account_id):
    user_id, role = authorize(["NetworkOperator", "ParticipantAdmin", "PaymentOperator", "FraudReviewer"])
    account = lookup.customer_account(account_id)
    require_scope(user_id, role, account["participant_id"])
    return object_response(serializers.customer_account(account))
