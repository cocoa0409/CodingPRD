"""RegulatoryComplaint routes (CFPB escalation lifecycle)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import current_principal, enforce_consumer_ownership, require_auth
from ..calculations import (
    NON_TERMINAL_DISPUTE_STATUSES,
    recompute_posture,
    reverification_deadline,
)
from ..clock import clock
from ..errors import ApiError
from ..responses import json_object
from ..store import (
    stamp_create,
    stamp_create_append_only,
    stamp_update,
    store,
)
from ..utils import check_occ, opt_field, parse_json_body, require_field


bp_regulatory = Blueprint("regulatory", __name__)


@bp_regulatory.route("/consumers/<consumer_id>/regulatory_complaints", methods=["POST"])
@require_auth(["Consumer"])
def file_complaint(consumer_id: str):
    enforce_consumer_ownership(consumer_id)
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    body = parse_json_body()
    dispute_id = require_field(body, "dispute_id", types=[str])
    parent_complaint_id = opt_field(body, "parent_complaint_id", types=[str])
    agency = opt_field(body, "agency", types=[str]) or "CFPB"
    narrative = require_field(body, "narrative", types=[str])

    if agency != "CFPB":
        raise ApiError("ERR_INVALID_REQUEST", "agency must be 'CFPB' in v1.", 400)
    if not (1 <= len(narrative) <= 4000):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "narrative must be between 1 and 4000 characters.",
            400,
        )

    # Priority 4: cross-consumer reference (dispute_id and parent_complaint_id).
    dispute = store.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_CROSS_CONSUMER_REFERENCE", "dispute_id does not exist.", 422)
    if dispute["consumer_id"] != consumer_id:
        raise ApiError(
            "ERR_CROSS_CONSUMER_REFERENCE",
            "dispute_id belongs to a different consumer.",
            422,
        )
    if parent_complaint_id is not None:
        parent = store.regulatory_complaints.get(parent_complaint_id)
        if parent is None:
            raise ApiError(
                "ERR_CROSS_CONSUMER_REFERENCE",
                "parent_complaint_id does not exist.",
                422,
            )
        if parent["consumer_id"] != consumer_id:
            raise ApiError(
                "ERR_CROSS_CONSUMER_REFERENCE",
                "parent_complaint_id belongs to a different consumer.",
                422,
            )

    with store.lock:
        # Priority 16: escalation eligibility (must be CLOSED_VERIFIED or CLOSED_DISMISSED).
        # NOTE: This priority fires BEFORE priority 17 (open complaint) per PRD §3.13.
        if dispute["status"] not in {"CLOSED_VERIFIED", "CLOSED_DISMISSED"}:
            raise ApiError(
                "ERR_NOT_ESCALATABLE",
                "Dispute must be in CLOSED_VERIFIED or CLOSED_DISMISSED to escalate.",
                409,
            )
        # If a refile, parent must be REJECTED.
        if parent_complaint_id is not None:
            parent = store.regulatory_complaints[parent_complaint_id]
            if parent["status"] != "REJECTED":
                raise ApiError(
                    "ERR_NOT_ESCALATABLE",
                    "Refile is only permitted after the parent complaint is REJECTED.",
                    409,
                )
            if parent["dispute_id"] != dispute_id:
                raise ApiError(
                    "ERR_NOT_ESCALATABLE",
                    "Refile parent_complaint_id must reference the same dispute.",
                    409,
                )
        # Priority 17: at most one open complaint per dispute.
        for c in store.regulatory_complaints.values():
            if c["dispute_id"] == dispute_id and c["status"] in {"FILED", "UNDER_REVIEW"}:
                raise ApiError(
                    "ERR_COMPLAINT_ALREADY_OPEN",
                    "An open RegulatoryComplaint already exists for this dispute.",
                    409,
                )

        complaint = stamp_create(
            {
                "consumer_id": consumer_id,
                "dispute_id": dispute_id,
                "parent_complaint_id": parent_complaint_id,
                "agency": agency,
                "narrative": narrative,
                "filed_day": clock.day,
                "status": "FILED",
            }
        )
        store.regulatory_complaints[complaint["id"]] = complaint

        # Side effect: dispute -> ESCALATED.
        dispute["status"] = "ESCALATED"
        stamp_update(dispute)
        store.dispute_escalation_history[dispute["id"]] = True
        recompute_posture(dispute["credit_report_id"])

    return json_object(complaint, 201)


def _complaint_or_404(complaint_id: str) -> dict:
    c = store.regulatory_complaints.get(complaint_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "RegulatoryComplaint not found.", 404)
    return c


@bp_regulatory.route("/regulatory_complaints/<complaint_id>", methods=["GET"])
@require_auth(["Consumer", "CFPBOperator", "PlatformAdmin"])
def get_complaint(complaint_id: str):
    c = _complaint_or_404(complaint_id)
    user_id, user_role = current_principal()
    if user_role == "Consumer" and user_id != c["consumer_id"]:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Consumer may only access their own complaints.",
            403,
        )
    return json_object(c, 200)


@bp_regulatory.route("/regulatory_complaints/<complaint_id>/accept", methods=["POST"])
@require_auth(["CFPBOperator"])
def accept_complaint(complaint_id: str):
    c = _complaint_or_404(complaint_id)
    body = parse_json_body()
    with store.lock:
        check_occ(c, body)
        if c["status"] != "FILED":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Only FILED complaints may be accepted.",
                409,
            )
        c["status"] = "UNDER_REVIEW"
        stamp_update(c)

        # Cascade: dispute ESCALATED -> UNDER_INVESTIGATION (dispute_reopen_cascade).
        dispute = store.disputes.get(c["dispute_id"])
        if dispute is not None and dispute["status"] == "ESCALATED":
            dispute["status"] = "UNDER_INVESTIGATION"
            dispute["deadline_day"] = clock.day + 30
            dispute["additional_info_accepted"] = False
            stamp_update(dispute)

            # Auto-create a fresh FurnisherInquiry.
            tradeline = store.tradeline_items.get(dispute["tradeline_item_id"])
            furnisher_id = tradeline["furnisher_id"] if tradeline else None
            fi = stamp_create_append_only(
                {
                    "dispute_id": dispute["id"],
                    "furnisher_id": furnisher_id,
                    "forwarded_day": clock.day,
                    "reverification_deadline_day": reverification_deadline(clock.day),
                    "response": "PENDING",
                    "response_day": None,
                    "response_payload": None,
                }
            )
            store.furnisher_inquiries[fi["id"]] = fi
            recompute_posture(dispute["credit_report_id"])

    return json_object(c, 200)


@bp_regulatory.route("/regulatory_complaints/<complaint_id>/reject", methods=["POST"])
@require_auth(["CFPBOperator"])
def reject_complaint(complaint_id: str):
    c = _complaint_or_404(complaint_id)
    body = parse_json_body()
    with store.lock:
        check_occ(c, body)
        if c["status"] != "FILED":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Only FILED complaints may be rejected.",
                409,
            )
        c["status"] = "REJECTED"
        stamp_update(c)
    return json_object(c, 200)


@bp_regulatory.route("/regulatory_complaints/<complaint_id>/resolve", methods=["POST"])
@require_auth(["CFPBOperator"])
def resolve_complaint(complaint_id: str):
    c = _complaint_or_404(complaint_id)
    body = parse_json_body()
    with store.lock:
        check_occ(c, body)
        if c["status"] != "UNDER_REVIEW":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Only UNDER_REVIEW complaints may be resolved.",
                409,
            )
        dispute = store.disputes.get(c["dispute_id"])
        if dispute is None or dispute["status"] in NON_TERMINAL_DISPUTE_STATUSES:
            raise ApiError(
                "ERR_DISPUTE_NOT_RECLOSED",
                "Underlying dispute must be back in a terminal CLOSED_* state to resolve.",
                409,
            )
        c["status"] = "RESOLVED"
        stamp_update(c)
    return json_object(c, 200)
