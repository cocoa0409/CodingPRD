"""Participant enrolment, certification, activation and relationship reads."""

from flask import Blueprint

from db import bump, db, new_record, order_key
from errors import ApiError
from middleware import authorize, require_scope
from response import created, list_response, object_response
from timeutils import parse_business_date
from validation import (
    opt_enum,
    opt_string,
    payload,
    req_bool,
    req_enum,
    req_string,
    routing_number,
)
from routes.helpers import query_value
from services import liquidity, lookup, serializers
from services.constants import (
    CERTIFICATION_OUTCOMES,
    IN_FLIGHT_STATUSES,
    MIN_PREFUND_CENTS,
    PARTICIPATION_MODELS,
    STATUS_CHANGE_TARGETS,
)

bp = Blueprint("participants", __name__)

ALL_ROLES = [
    "NetworkOperator", "ParticipantAdmin", "LiquidityOfficer",
    "PaymentOperator", "FraudReviewer", "CoreBankingSystem",
]


@bp.route("/participants", methods=["POST"])
def create_participant():
    authorize(["NetworkOperator"])
    body = payload()
    legal_name = req_string(body, "legal_name")
    number = routing_number(body, "routing_number")
    agent = req_string(body, "settlement_agent_reference")
    model = opt_enum(body, "participation_model", PARTICIPATION_MODELS, "RECEIVE_ONLY")
    for row in db.participants.values():
        if row["routing_number"] == number:
            raise ApiError(
                "ERR_DUPLICATE_ROUTING_NUMBER",
                "That routing number is already held by an enrolled participant.",
            )
    row = new_record()
    row.update({
        "legal_name": legal_name,
        "routing_number": number,
        "settlement_agent_reference": agent,
        "participation_model": model,
        "enrollment_status": "DRAFT",
        "operational_posture": "NORMAL",
        "attestation_document_reference": None,
        "certification_test_suite_version": None,
        "certification_round": 0,
        "go_live_business_date": None,
        "suspension_reason": None,
        "_passed_rounds": [],
    })
    db.participants[row["id"]] = row
    return created(serializers.participant(row))


@bp.route("/participants/<participant_id>", methods=["GET"])
def get_participant(participant_id):
    user_id, role = authorize(ALL_ROLES)
    require_scope(user_id, role, participant_id)
    return object_response(serializers.participant(lookup.participant(participant_id)))


@bp.route("/participants/<participant_id>/participation-model", methods=["PATCH"])
def patch_participation_model(participant_id):
    user_id, role = authorize(["ParticipantAdmin"])
    require_scope(user_id, role, participant_id)
    participant = lookup.participant(participant_id)
    body = payload()
    model = req_enum(body, "participation_model", PARTICIPATION_MODELS)
    if participant["enrollment_status"] not in ("DRAFT", "ATTESTATION_PENDING", "REMEDIATION"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The participation model may only be changed before go-live.",
        )
    participant["participation_model"] = model
    bump(participant)
    return object_response(serializers.participant(participant))


@bp.route("/participants/<participant_id>/attestation", methods=["POST"])
def post_attestation(participant_id):
    user_id, role = authorize(["ParticipantAdmin"])
    require_scope(user_id, role, participant_id)
    participant = lookup.participant(participant_id)
    body = payload()
    reference = req_string(body, "attestation_document_reference")
    confirmed = req_bool(body, "operational_readiness_confirmed")
    if participant["enrollment_status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "An attestation is only accepted while the participant is DRAFT.",
        )
    if not confirmed:
        raise ApiError(
            "ERR_ATTESTATION_INCOMPLETE",
            "operational_readiness_confirmed must be true.",
        )
    participant["attestation_document_reference"] = reference
    participant["enrollment_status"] = "ATTESTATION_PENDING"
    bump(participant)
    return object_response(serializers.participant(participant))


@bp.route("/participants/<participant_id>/certification-window", methods=["POST"])
def post_certification_window(participant_id):
    authorize(["NetworkOperator"])
    participant = lookup.participant(participant_id)
    body = payload()
    suite = req_string(body, "certification_test_suite_version")
    if participant["enrollment_status"] not in ("ATTESTATION_PENDING", "REMEDIATION"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A certification window opens from ATTESTATION_PENDING or REMEDIATION only.",
        )
    participant["certification_test_suite_version"] = suite
    participant["certification_round"] = participant["certification_round"] + 1
    participant["enrollment_status"] = "CERTIFICATION_TESTING"
    bump(participant)
    return object_response(serializers.participant(participant))


@bp.route("/participants/<participant_id>/certification-results", methods=["POST"])
def post_certification_results(participant_id):
    authorize(["NetworkOperator"])
    participant = lookup.participant(participant_id)
    body = payload()
    outcome = req_enum(body, "outcome", CERTIFICATION_OUTCOMES)
    if participant["enrollment_status"] != "CERTIFICATION_TESTING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Results are only recorded while the participant is CERTIFICATION_TESTING.",
        )
    if outcome == "PASS":
        participant["enrollment_status"] = "CERTIFIED"
        if participant["certification_round"] not in participant["_passed_rounds"]:
            participant["_passed_rounds"].append(participant["certification_round"])
    else:
        participant["enrollment_status"] = "REMEDIATION"
    bump(participant)
    return object_response(serializers.participant(participant))


@bp.route("/participants/<participant_id>/activation", methods=["POST"])
def post_activation(participant_id):
    authorize(["NetworkOperator"])
    participant = lookup.participant(participant_id)
    body = payload()
    go_live = req_string(body, "go_live_business_date")
    parse_business_date(go_live)
    if participant["enrollment_status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Activation is only permitted from CERTIFIED.",
        )
    account = lookup.account_of_participant(participant_id)
    if account is not None:
        if liquidity.current_balance(account) < MIN_PREFUND_CENTS:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The prefunded position is below the network minimum.",
            )
        if account["alert_tier"] != "GREEN":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The prefunded position must be banded GREEN to go live.",
            )
    if (account is None
            or not participant["attestation_document_reference"]
            or participant["certification_round"] not in participant["_passed_rounds"]):
        raise ApiError(
            "ERR_ACTIVATION_PREREQUISITES_NOT_MET",
            "A position account, an attestation reference and a PASS result in the "
            "current certification round are all required.",
        )
    participant["go_live_business_date"] = go_live
    participant["enrollment_status"] = "LIVE"
    liquidity.rederive_posture(participant, bump_participant=False)
    bump(participant)
    return object_response(serializers.participant(participant))


@bp.route("/participants/<participant_id>/status-change", methods=["POST"])
def post_status_change(participant_id):
    authorize(["NetworkOperator"])
    participant = lookup.participant(participant_id)
    body = payload()
    target = req_enum(body, "target_status", STATUS_CHANGE_TARGETS)
    reason = opt_string(body, "suspension_reason")
    current = participant["enrollment_status"]
    if target == "SUSPENDED":
        if current != "LIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a LIVE participant may be suspended.")
        participant["suspension_reason"] = reason
        participant["enrollment_status"] = "SUSPENDED"
        liquidity.rederive_posture(participant, bump_participant=False)
    elif target == "LIVE":
        if current != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a SUSPENDED participant may be reinstated.")
        participant["suspension_reason"] = None
        participant["enrollment_status"] = "LIVE"
        liquidity.rederive_posture(participant, bump_participant=False)
    else:
        if current not in ("LIVE", "SUSPENDED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Withdrawal is available from LIVE or SUSPENDED only.",
            )
        if lookup.transfers_of_participant(participant_id, IN_FLIGHT_STATUSES):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Every in-flight transfer must be resolved before withdrawal.",
            )
        participant["suspension_reason"] = reason
        participant["enrollment_status"] = "WITHDRAWN"
        participant["operational_posture"] = "SEND_FROZEN"
    bump(participant)
    return object_response(serializers.participant(participant))


@bp.route("/participants/<participant_id>/position-accounts", methods=["GET"])
def list_participant_position_accounts(participant_id):
    user_id, role = authorize(["NetworkOperator", "ParticipantAdmin", "LiquidityOfficer", "CoreBankingSystem"])
    require_scope(user_id, role, participant_id)
    lookup.participant(participant_id)
    rows = sorted(
        [a for a in db.position_accounts.values() if a["participant_id"] == participant_id],
        key=order_key,
    )
    return list_response(rows, serializers.position_account)


@bp.route("/participants/<participant_id>/segment-policies", methods=["GET"])
def list_participant_segment_policies(participant_id):
    user_id, role = authorize(["NetworkOperator", "ParticipantAdmin", "PaymentOperator"])
    require_scope(user_id, role, participant_id)
    lookup.participant(participant_id)
    segment = query_value("segment")
    rows = [p for p in db.segment_policies.values() if p["participant_id"] == participant_id]
    if segment is not None:
        rows = [p for p in rows if p["segment"] == segment]
    rows.sort(key=lambda p: (p["effective_from"], p["created_at"], p["_seq"]), reverse=True)
    return list_response(rows, serializers.segment_policy)


@bp.route("/participants/<participant_id>/customer-accounts", methods=["GET"])
def list_participant_customer_accounts(participant_id):
    user_id, role = authorize(["NetworkOperator", "ParticipantAdmin", "PaymentOperator", "FraudReviewer"])
    require_scope(user_id, role, participant_id)
    lookup.participant(participant_id)
    segment = query_value("segment")
    status = query_value("status")
    rows = [c for c in db.customer_accounts.values() if c["participant_id"] == participant_id]
    if segment is not None:
        rows = [c for c in rows if c["segment"] == segment]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=order_key)
    return list_response(rows, serializers.customer_account)


@bp.route("/participants/<participant_id>/outage-events", methods=["GET"])
def list_participant_outage_events(participant_id):
    user_id, role = authorize(["NetworkOperator", "ParticipantAdmin", "PaymentOperator"])
    require_scope(user_id, role, participant_id)
    lookup.participant(participant_id)
    status = query_value("status")
    rows = [e for e in db.outage_events.values() if e["participant_id"] == participant_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows.sort(key=order_key)
    return list_response(rows, serializers.outage_event)


