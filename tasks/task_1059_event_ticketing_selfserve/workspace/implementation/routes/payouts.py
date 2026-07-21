"""Payouts and the rolling reserve (PRD §3.9)."""
import datetime

from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import derive, lookup, payouts as payout_service, reliability, serializers

bp = Blueprint("payouts", __name__)


def _pending_refunds(event_id):
    for rr in derive.refund_requests_of_event(event_id):
        if rr["status"] in ("REQUESTED", "APPROVED"):
            return True
    return False


@bp.route("/api/payouts", methods=["POST"])
def create_payout():
    middleware.authenticate(["FinanceOfficer"])
    payload = middleware.body()
    organizer_id = middleware.req_string(payload, "organizer_id")
    event_id = middleware.req_string(payload, "event_id")
    expected_organizer_version = middleware.req_int(payload, "expected_organizer_version")

    organizer = lookup.organizer(organizer_id)
    event = lookup.event(event_id)

    if event["status"] not in ("SALES_CLOSED", "COMPLETED"):
        raise ApiError(
            "ERR_INVALID_EVENT_TRANSITION", "The event's sales have not finished yet."
        )

    if expected_organizer_version != organizer["version"]:
        raise ApiError("ERR_STALE_ORGANIZER_VERSION")

    snapshot, _counted = reliability.score(organizer["id"], "TRAILING")

    record = db.base_record()
    record.update(
        {
            "organizer_id": organizer["id"],
            "event_id": event["id"],
            "status": "ACCRUING",
            "reliability_score_snapshot": snapshot,
            "reserve_release_at": db.iso(
                db.parse_iso(event["ends_at"])
                + datetime.timedelta(days=C.ROLLING_RESERVE_RELEASE_DAYS)
            ),
            "reserve_released_cents": 0,
            "approved_by_user_id": None,
            "released_by_user_id": None,
        }
    )
    record.update(payout_service.compute_chain(event, snapshot))
    db.store.payouts[record["id"]] = record

    db.touch(organizer)
    return object_response(serializers.payout(record), 201)


@bp.route("/api/payouts/<payout_id>", methods=["GET"])
def read_payout(payout_id):
    actor = middleware.authenticate(["FinanceOfficer", "Organizer", "PlatformAdmin"])
    record = lookup.payout(payout_id)
    if actor.role == "Organizer" and actor.user_id != record["organizer_id"]:
        lookup.unauthorized()
    return object_response(serializers.payout(record))


@bp.route("/api/payouts", methods=["GET"])
def list_payouts():
    middleware.authenticate(["FinanceOfficer", "Organizer", "PlatformAdmin"])
    organizer_id = request.args.get("organizer_id")
    event_id = request.args.get("event_id")
    status = middleware.query_enum("status", C.PAYOUT_STATUSES)
    records = [
        p
        for p in db.store.payouts.values()
        if (organizer_id is None or p["organizer_id"] == organizer_id)
        and (event_id is None or p["event_id"] == event_id)
        and (status is None or p["status"] == status)
    ]
    return paginate(db.ordered(records), serializers.payout)


def _transition(payout_id):
    actor = middleware.authenticate(["FinanceOfficer"])
    payload = middleware.body()
    record = lookup.payout(payout_id)
    event = lookup.event(record["event_id"])
    return actor, payload, record, event


@bp.route("/api/payouts/<payout_id>/mark-eligible", methods=["POST"])
def mark_eligible(payout_id):
    _actor, _payload, record, event = _transition(payout_id)
    if record["status"] != "ACCRUING":
        raise ApiError("ERR_INVALID_PAYOUT_STATE", "The payout is not ACCRUING.")

    chain = payout_service.compute_chain(event, record["reliability_score_snapshot"])
    if event["status"] != "COMPLETED" or chain["net_amount_cents"] < 0:
        raise ApiError("ERR_PAYOUT_NOT_ELIGIBLE", "The payout is not eligible.")
    if _pending_refunds(event["id"]):
        raise ApiError("ERR_PAYOUT_PENDING_REFUNDS", "A refund on this event is still open.")

    record.update(chain)
    record["status"] = "ELIGIBLE"
    db.touch(record)
    return object_response(serializers.payout(record))


@bp.route("/api/payouts/<payout_id>/hold", methods=["POST"])
def hold_payout(payout_id):
    _actor, payload, record, _event = _transition(payout_id)
    middleware.opt_string(payload, "reason")
    if record["status"] not in ("ACCRUING", "ELIGIBLE"):
        raise ApiError("ERR_INVALID_PAYOUT_STATE", "The payout cannot be held from that status.")
    record["status"] = "ON_HOLD"
    db.touch(record)
    return object_response(serializers.payout(record))


@bp.route("/api/payouts/<payout_id>/resume", methods=["POST"])
def resume_payout(payout_id):
    _actor, _payload, record, event = _transition(payout_id)
    if record["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_PAYOUT_STATE", "The payout is not ON_HOLD.")

    chain = payout_service.compute_chain(event, record["reliability_score_snapshot"])
    if chain["net_amount_cents"] < 0:
        raise ApiError("ERR_PAYOUT_NOT_ELIGIBLE", "The payout's net amount is negative.")

    record.update(chain)
    record["status"] = "ELIGIBLE"
    db.touch(record)
    return object_response(serializers.payout(record))


@bp.route("/api/payouts/<payout_id>/approve", methods=["POST"])
def approve_payout(payout_id):
    actor, _payload, record, _event = _transition(payout_id)
    if record["status"] != "ELIGIBLE":
        raise ApiError("ERR_INVALID_PAYOUT_STATE", "The payout is not ELIGIBLE.")
    if record["net_amount_cents"] < 0:
        raise ApiError("ERR_PAYOUT_NOT_ELIGIBLE", "The payout's net amount is negative.")

    record["status"] = "APPROVED"
    record["approved_by_user_id"] = actor.user_id
    db.touch(record)
    return object_response(serializers.payout(record))


@bp.route("/api/payouts/<payout_id>/release", methods=["POST"])
def release_payout(payout_id):
    actor, _payload, record, _event = _transition(payout_id)
    if record["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PAYOUT_STATE", "The payout is not APPROVED.")
    if actor.user_id == record["approved_by_user_id"]:
        raise ApiError(
            "ERR_SOD_SAME_ACTOR", "The approving operator may not also release the payout."
        )

    record["status"] = "RELEASED"
    record["released_by_user_id"] = actor.user_id
    db.touch(record)
    return object_response(serializers.payout(record))


@bp.route("/api/payouts/<payout_id>/release-reserve", methods=["POST"])
def release_reserve(payout_id):
    _actor, _payload, record, _event = _transition(payout_id)
    if db.now() < db.parse_iso(record["reserve_release_at"]):
        raise ApiError("ERR_RESERVE_NOT_MATURED", "The rolling reserve has not matured yet.")

    record["reserve_released_cents"] = record["reserve_cents"]
    db.touch(record)
    return object_response(serializers.payout(record))
