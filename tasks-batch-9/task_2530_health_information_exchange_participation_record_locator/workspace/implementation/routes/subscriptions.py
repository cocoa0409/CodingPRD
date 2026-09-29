"""Notification subscription endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import commit, create, db, snapshot, touch
from errors import ApiError, bad_request
from middleware import (
    HIE_ADMIN,
    PARTICIPANT_ADMIN,
    PRIVACY_OFFICER,
    PUBLIC_HEALTH_OFFICER,
    authenticate,
    require_scope,
)
from response import entity, entity_created, paginate, pagination
from services import repo
from services.counters import recompute_active_subscription_count
from validate import body, opt_id, req_enum, req_enum_list, req_str

bp = Blueprint("subscriptions", __name__)

SUBSCRIPTION_SCOPES = ("PATIENT_PANEL", "CLUSTER", "PUBLIC_HEALTH_CONDUIT")
EVENT_TYPES = ("ADMISSION", "DISCHARGE", "TRANSFER")
SUBSCRIPTION_ACTIONS = ("ACTIVATE", "SUSPEND", "REACTIVATE", "TERMINATE")
LIVE_STATES = ("PENDING_ACTIVATION", "ACTIVE")


@bp.route("/hie/participants/<pid>/notification-subscriptions", methods=["POST"])
def create_subscription(pid):
    actor = authenticate((PARTICIPANT_ADMIN, PUBLIC_HEALTH_OFFICER, HIE_ADMIN))
    require_scope(actor, pid)
    payload = body()
    scope = req_enum(payload, "subscription_scope", SUBSCRIPTION_SCOPES)
    event_types = req_enum_list(payload, "event_types", EVENT_TYPES, allow_empty=False)
    url = req_str(payload, "delivery_endpoint_url")
    if not url.startswith("https://"):
        raise bad_request("delivery_endpoint_url must begin with https://.")
    cluster_id = opt_id(payload, "cluster_id")

    participant = repo.must("participants", pid)
    cluster = None
    if cluster_id is not None:
        cluster = repo.must("clusters", cluster_id)
        if cluster["status"] != "ACTIVE":
            raise ApiError("ERR_CLUSTER_MERGED_AWAY")

    if scope == "PUBLIC_HEALTH_CONDUIT" and participant["org_type"] != "PUBLIC_HEALTH":
        raise ApiError("ERR_CONDUIT_ORG_TYPE_INVALID")

    if scope == "CLUSTER" and cluster_id is None:
        raise ApiError("ERR_SUBSCRIPTION_SCOPE_MISMATCH")
    if scope != "CLUSTER" and cluster_id is not None:
        raise ApiError("ERR_SUBSCRIPTION_SCOPE_MISMATCH")

    row = create(
        db.subscriptions,
        "NotificationSubscription",
        {
            "subscriber_participant_id": pid,
            "subscription_scope": scope,
            "cluster_id": cluster_id,
            "event_types": list(event_types),
            "delivery_endpoint_url": url,
            "activating_conformance_test_id": None,
            "status": "PENDING_ACTIVATION",
            "termination_reason": None,
        },
    )
    return entity_created(row)


@bp.route(
    "/hie/notification-subscriptions/<subscription_id>/lifecycle-transitions",
    methods=["POST"],
)
def lifecycle_transition(subscription_id):
    authenticate((PARTICIPANT_ADMIN, PUBLIC_HEALTH_OFFICER, HIE_ADMIN))
    payload = body()
    action = req_enum(payload, "action", SUBSCRIPTION_ACTIONS)
    reason = None
    if action == "TERMINATE":
        reason = req_str(payload, "reason")

    subscription = repo.must("subscriptions", subscription_id)
    if subscription["status"] == "TERMINATED":
        raise ApiError("ERR_TERMINAL_STATE")

    if action == "ACTIVATE" and subscription["status"] != "PENDING_ACTIVATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action == "SUSPEND" and subscription["status"] not in LIVE_STATES:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action == "REACTIVATE" and subscription["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action == "TERMINATE" and subscription["status"] not in (
        "PENDING_ACTIVATION",
        "ACTIVE",
        "SUSPENDED",
    ):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    participant = repo.must("participants", subscription["subscriber_participant_id"])

    if action in ("ACTIVATE", "REACTIVATE"):
        if participant["onboarding_status"] != "CERTIFIED":
            raise ApiError("ERR_PARTICIPANT_NOT_CERTIFIED")

    qualifying = None
    if action == "ACTIVATE":
        runs = [
            t
            for t in repo.where(
                "conformance_tests",
                participant_id=participant["id"],
                profile="ADT_PUBLISHER",
            )
            if t["status"] == "PASSED"
        ]
        if not runs:
            raise ApiError("ERR_SUBSCRIPTION_CONFORMANCE_MISSING")
        qualifying = runs[0]
        if repo.has_delinquent_invoice(participant["id"]):
            raise ApiError("ERR_PARTICIPATION_FEE_DELINQUENT")

    if action == "ACTIVATE":
        subscription["status"] = "ACTIVE"
        subscription["activating_conformance_test_id"] = qualifying["id"]
    elif action == "SUSPEND":
        subscription["status"] = "SUSPENDED"
    elif action == "REACTIVATE":
        subscription["status"] = "ACTIVE"
    else:
        subscription["status"] = "TERMINATED"
        subscription["termination_reason"] = reason
    touch(subscription)

    participant_snap = snapshot(participant)
    recompute_active_subscription_count(participant)
    commit(participant, participant_snap)
    return entity(subscription)


@bp.route("/hie/notification-subscriptions/<subscription_id>", methods=["GET"])
def read_subscription(subscription_id):
    authenticate(
        (HIE_ADMIN, PARTICIPANT_ADMIN, PUBLIC_HEALTH_OFFICER, PRIVACY_OFFICER)
    )
    return entity(repo.must("subscriptions", subscription_id))


@bp.route("/hie/notification-subscriptions", methods=["GET"])
def list_subscriptions():
    authenticate(
        (HIE_ADMIN, PARTICIPANT_ADMIN, PUBLIC_HEALTH_OFFICER, PRIVACY_OFFICER)
    )
    limit, offset = pagination()
    rows = repo.all_rows("subscriptions")
    for key in (
        "subscriber_participant_id",
        "cluster_id",
        "activating_conformance_test_id",
        "status",
        "subscription_scope",
    ):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, limit, offset)
