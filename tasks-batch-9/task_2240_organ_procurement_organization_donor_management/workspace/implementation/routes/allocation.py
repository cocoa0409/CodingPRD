"""Match runs, offer sequencing, acceptance clocks and compensating withdrawal."""

from flask import Blueprint, request

from constants import DECLINE_REASONS, OFFER_DECISIONS, OFFER_STATUSES
from db import clock_now, db, lock
from errors import ApiError
from middleware import authenticate
from response import ok, paginated
from services.domain import (
    offers_of_run,
    promotion_selector,
    set_allocation_status,
    touch,
)
from validation import Body, page, pagination

bp = Blueprint("allocation", __name__)


def resolve_run(run_id):
    record = db.match_runs.get(run_id)
    if record is None:
        raise ApiError("ERR_MATCH_RUN_NOT_FOUND")
    return record


def resolve_offer(offer_id):
    record = db.organ_offers.get(offer_id)
    if record is None:
        raise ApiError("ERR_OFFER_NOT_FOUND")
    return record


@bp.get("/opo/match-runs/<run_id>")
def read_match_run(run_id):
    authenticate("OpoAdmin", "AllocationSpecialist", "MedicalDirector")
    with lock:
        return ok(resolve_run(run_id))


@bp.get("/opo/match-runs/<run_id>/offers")
def list_offers(run_id):
    authenticate("OpoAdmin", "AllocationSpecialist", "MedicalDirector")
    with lock:
        resolve_run(run_id)
        limit, offset = pagination()
        status = request.args.get("status")
        rows = offers_of_run(run_id)
        if status is not None:
            rows = [r for r in rows if r["status"] == status and status in OFFER_STATUSES]
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/match-runs/<run_id>/offers/<offer_id>/respond")
def respond_to_offer(run_id, offer_id):
    user_id, _role = authenticate("AllocationSpecialist")
    with lock:
        run = resolve_run(run_id)
        offer = resolve_offer(offer_id)

        body = Body()
        decision = body.enum("decision", OFFER_DECISIONS, required=True)
        decline_reason = body.enum("decline_reason", DECLINE_REASONS)
        ack = body.boolean("increased_risk_ack", default=False)
        if decision == "DECLINE" and decline_reason is None:
            raise ApiError("ERR_INVALID_REQUEST", "decline_reason is required to decline an offer.")

        if decision in ("ACCEPT", "DECLINE"):
            if offer["status"] != "PENDING" or run["status"] != "OPEN":
                raise ApiError("ERR_OFFER_NOT_PENDING")
        else:
            if offer["status"] != "ACCEPTED" or run["status"] != "CLOSED":
                raise ApiError("ERR_OFFER_NOT_PENDING")

        now = clock_now()
        if decision == "ACCEPT":
            if offer["expires_at"] is None or now >= offer["expires_at"]:
                raise ApiError("ERR_ACCEPTANCE_CLOCK_ELAPSED")

        organ = db.organs.get(run["organ_id"])
        case = db.donor_cases.get(organ["donor_case_id"]) if organ is not None else None
        if case is not None and case["case_posture"] == "FROZEN":
            raise ApiError("ERR_CASE_FROZEN")

        if decision == "ACCEPT":
            if case is not None and case["risk_tier_snapshot"] == "INCREASED_RISK" and not ack:
                raise ApiError("ERR_INCREASED_RISK_ACK_REQUIRED")

        if offer["match_run_id"] != run_id:
            raise ApiError("ERR_OFFER_RUN_MISMATCH")

        if decision == "WITHDRAW_ACCEPTANCE":
            if organ is None or organ["accepted_offer_id"] != offer_id or organ["status"] != "ACCEPTED":
                raise ApiError("ERR_OFFER_NOT_PENDING")

        offer["responded_at"] = now
        offer["responded_by_user_id"] = user_id
        offer["increased_risk_ack"] = ack

        if decision == "ACCEPT":
            offer["status"] = "ACCEPTED"
            touch(offer)
            run["pending_offer_count"] -= 1
            if organ is not None:
                organ["status"] = "ACCEPTED"
                organ["accepted_offer_id"] = offer_id
                touch(organ)
            run["status"] = "CLOSED"
            run["closed_reason"] = "ACCEPTED"
            for peer in offers_of_run(run_id):
                if peer["id"] == offer_id:
                    continue
                if peer["status"] in ("QUEUED", "PENDING"):
                    peer["status"] = "BYPASSED"
                    peer["bypass_reason"] = "PEER_ACCEPTED"
                    touch(peer)
            run["pending_offer_count"] = 0
            run["slots_free"] = run["primary_offer_slots"]
            touch(run)
            if case is not None:
                if case["allocation_status"] in ("MATCH_RUN_OPEN", "OFFERS_IN_FLIGHT"):
                    set_allocation_status(case, "ALLOCATED")
                case["organs_accepted_count"] += 1
                touch(case)

        elif decision == "DECLINE":
            offer["status"] = "DECLINED"
            offer["decline_reason"] = decline_reason
            touch(offer)
            run["pending_offer_count"] -= 1
            run["slots_free"] += 1
            touch(run)
            promotion_selector(run)

        else:
            offer["status"] = "WITHDRAWN"
            touch(offer)
            organ["status"] = "OFFERING"
            organ["accepted_offer_id"] = None
            touch(organ)
            run["status"] = "OPEN"
            run["closed_reason"] = None
            touch(run)
            for peer in offers_of_run(run_id):
                if peer["status"] == "BYPASSED" and peer["bypass_reason"] == "PEER_ACCEPTED":
                    peer["status"] = "QUEUED"
                    peer["bypass_reason"] = None
                    touch(peer)
            if case is not None:
                if case["allocation_status"] == "ALLOCATED":
                    set_allocation_status(case, "OFFERS_IN_FLIGHT")
                case["organs_accepted_count"] = max(0, case["organs_accepted_count"] - 1)
                touch(case)
            promotion_selector(run)

        return ok(offer)


@bp.post("/opo/match-runs/<run_id>/advance")
def advance_match_run(run_id):
    authenticate("AllocationSpecialist")
    with lock:
        run = resolve_run(run_id)
        Body()
        if run["status"] != "OPEN":
            raise ApiError("ERR_MATCH_RUN_NOT_OPEN")
        promoted = promotion_selector(run, sweep=True)
        payload = dict(run)
        payload["promoted_count"] = promoted
        return ok(payload)
