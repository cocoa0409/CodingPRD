"""Dispute routes — the central, branching FCRA workflow.

State machine per SCAFFOLD §1.2 / PRD §3.2–§3.4:
    RECEIVED -> UNDER_INVESTIGATION -> RESULTS_PENDING -> {CLOSED_VERIFIED,
                                                          CLOSED_UPDATED,
                                                          CLOSED_DELETED}
    RECEIVED -> CLOSED_DISMISSED  (frivolous direct path)
    CLOSED_VERIFIED | CLOSED_DISMISSED -> ESCALATED -> UNDER_INVESTIGATION (CFPB)
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint

from ..auth import enforce_consumer_ownership, require_auth
from ..calculations import (
    NON_TERMINAL_DISPUTE_STATUSES,
    apply_free_report_grant,
    base_deadline,
    compute_dispute_risk_score,
    extended_deadline,
    recompute_fico_on_report,
    recompute_posture,
    reverification_deadline,
)
from ..clock import clock
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_create, stamp_create_append_only, stamp_update, store
from ..utils import check_occ, parse_json_body, opt_field, require_field


bp_disputes = Blueprint("disputes", __name__)


VALID_CHANNELS = {"ONLINE", "MAIL"}
VALID_ACTIONS = {"CORRECT_BALANCE", "CORRECT_STATUS", "DELETE_ITEM", "CORRECT_DOFD"}
VALID_FURNISHER_RESPONSES = {"VERIFIED", "UPDATED", "DELETED"}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _consumer_or_404(consumer_id: str) -> dict:
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    return consumer


def _dispute_or_404(consumer_id: str, dispute_id: str) -> dict:
    _consumer_or_404(consumer_id)
    d = store.disputes.get(dispute_id)
    if d is None or d["consumer_id"] != consumer_id:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found.", 404)
    return d


def _validate_supporting_documents(docs: Any) -> list[dict]:
    if not isinstance(docs, list) or len(docs) == 0:
        raise ApiError(
            "ERR_NO_SUPPORTING_DOCUMENTS",
            "supporting_documents must be a non-empty array.",
            422,
        )
    for doc in docs:
        if not isinstance(doc, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Each supporting document must be an object.",
                400,
            )
        if "kind" not in doc or "sha256" not in doc:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Each supporting document must include 'kind' and 'sha256'.",
                400,
            )
    return docs


def _count_submissions_against_tradeline(consumer_id: str, tradeline_item_id: str) -> int:
    """Count disputes by this consumer against this tradeline in last 365 days."""
    cutoff = clock.day - 365
    return sum(
        1
        for d in store.disputes.values()
        if d["consumer_id"] == consumer_id
        and d["tradeline_item_id"] == tradeline_item_id
        and d.get("submitted_day", 0) >= cutoff
    )


def _active_dispute_for_tradeline(tradeline_item_id: str) -> dict | None:
    for d in store.disputes.values():
        if (
            d["tradeline_item_id"] == tradeline_item_id
            and d["status"] in NON_TERMINAL_DISPUTE_STATUSES
        ):
            return d
    return None


def _current_inquiry(dispute_id: str) -> dict | None:
    """Most-recent FurnisherInquiry for a dispute (single open one for normal flow)."""
    inquiries = [
        fi for fi in store.furnisher_inquiries.values() if fi["dispute_id"] == dispute_id
    ]
    if not inquiries:
        return None
    # Sort by forwarded_day desc, then by created_at desc.
    inquiries.sort(key=lambda i: (i["forwarded_day"], i["created_at"]), reverse=True)
    return inquiries[0]


def _tradeline_furnisher_id(tradeline_item_id: str) -> str | None:
    ti = store.tradeline_items.get(tradeline_item_id)
    return ti["furnisher_id"] if ti else None


# ----------------------------------------------------------------------
# POST /consumers/{id}/disputes — submit
# ----------------------------------------------------------------------


@bp_disputes.route("/consumers/<consumer_id>/disputes", methods=["POST"])
@require_auth(["Consumer"])
def submit_dispute(consumer_id: str):
    enforce_consumer_ownership(consumer_id)
    consumer = _consumer_or_404(consumer_id)

    body = parse_json_body()
    credit_report_id = require_field(body, "credit_report_id", types=[str])
    tradeline_item_id = require_field(body, "tradeline_item_id", types=[str])
    channel = require_field(body, "channel", types=[str])
    supporting_documents_raw = body.get("supporting_documents")
    requested_action = require_field(body, "requested_action", types=[str])
    requested_payload = opt_field(body, "requested_payload", types=[dict]) or {}

    if channel not in VALID_CHANNELS:
        raise ApiError(
            "ERR_INVALID_REQUEST", f"channel must be one of {sorted(VALID_CHANNELS)}.", 400
        )
    if requested_action not in VALID_ACTIONS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"requested_action must be one of {sorted(VALID_ACTIONS)}.",
            400,
        )

    # Priority 4: cross-consumer reference for body FKs.
    report = store.credit_reports.get(credit_report_id)
    if report is None:
        raise ApiError(
            "ERR_CROSS_CONSUMER_REFERENCE",
            "credit_report_id does not exist.",
            422,
        )
    if report["consumer_id"] != consumer_id:
        raise ApiError(
            "ERR_CROSS_CONSUMER_REFERENCE",
            "credit_report_id belongs to a different consumer.",
            422,
        )
    tradeline = store.tradeline_items.get(tradeline_item_id)
    if tradeline is None:
        raise ApiError(
            "ERR_CROSS_CONSUMER_REFERENCE",
            "tradeline_item_id does not exist.",
            422,
        )
    if tradeline["credit_report_id"] != credit_report_id:
        raise ApiError(
            "ERR_CROSS_CONSUMER_REFERENCE",
            "tradeline_item_id does not belong to credit_report_id.",
            422,
        )

    # Priority 11: supporting documents.
    supporting_documents = _validate_supporting_documents(supporting_documents_raw)

    with store.lock:
        # Priority 12: frivolous threshold — submission #4+ on same tradeline in 365d is frivolous.
        # provisional dispute_risk_score excludes the dispute being submitted (PRD §3.6).
        existing_count = _count_submissions_against_tradeline(consumer_id, tradeline_item_id)
        if existing_count >= 3:
            # The new submission would be the 4th+. That is frivolous.
            raise ApiError(
                "ERR_FRIVOLOUS_DISPUTE",
                "More than 3 disputes on the same tradeline within 365 days.",
                409,
            )

        # Priority 13: at most one active Dispute per TradelineItem.
        if _active_dispute_for_tradeline(tradeline_item_id) is not None:
            raise ApiError(
                "ERR_DUPLICATE_ACTIVE_DISPUTE",
                "An active dispute already exists for this tradeline.",
                409,
            )

        submitted_day = clock.day
        dispute = stamp_create(
            {
                "consumer_id": consumer_id,
                "credit_report_id": credit_report_id,
                "tradeline_item_id": tradeline_item_id,
                "channel": channel,
                "supporting_documents": supporting_documents,
                "requested_action": requested_action,
                "requested_payload": requested_payload,
                "submitted_day": submitted_day,
                "deadline_day": base_deadline(submitted_day),
                "additional_info_accepted": False,
                "investigation_outcome": "PENDING",
                "result_notice_id": None,
                "status": "RECEIVED",
            }
        )
        store.disputes[dispute["id"]] = dispute
        # Posture recompute is technically unnecessary for RECEIVED (non-terminal),
        # but issuing one here keeps the report row consistent if anything triggers off it.
        recompute_posture(credit_report_id)

    return json_object(dispute, 201)


# ----------------------------------------------------------------------
# GET /consumers/{id}/disputes/{id}
# ----------------------------------------------------------------------


@bp_disputes.route("/consumers/<consumer_id>/disputes/<dispute_id>", methods=["GET"])
@require_auth(["Consumer", "BureauOperator", "PlatformAdmin"])
def get_dispute(consumer_id: str, dispute_id: str):
    enforce_consumer_ownership(consumer_id)
    dispute = _dispute_or_404(consumer_id, dispute_id)
    return json_object(dispute, 200)


# ----------------------------------------------------------------------
# POST /consumers/{id}/disputes/{id}/start_investigation
# ----------------------------------------------------------------------


@bp_disputes.route(
    "/consumers/<consumer_id>/disputes/<dispute_id>/start_investigation",
    methods=["POST"],
)
@require_auth(["BureauOperator"])
def start_investigation(consumer_id: str, dispute_id: str):
    dispute = _dispute_or_404(consumer_id, dispute_id)
    body = parse_json_body()
    with store.lock:
        check_occ(dispute, body)
        # Priority 5: state transition allowed only from RECEIVED.
        if dispute["status"] != "RECEIVED":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Investigation can only start from RECEIVED.",
                409,
            )
        # Priority 6: report posture must not be FROZEN.
        report = store.credit_reports[dispute["credit_report_id"]]
        if report["posture"] == "FROZEN":
            raise ApiError(
                "ERR_REPORT_FROZEN",
                "Cannot start investigation while report is FROZEN.",
                409,
            )
        # Priority 11: supporting documents.
        if not dispute["supporting_documents"]:
            raise ApiError(
                "ERR_NO_SUPPORTING_DOCUMENTS",
                "Dispute has no supporting documents.",
                422,
            )
        # Priority 12: frivolous threshold.
        existing_count = sum(
            1
            for d in store.disputes.values()
            if d["consumer_id"] == consumer_id
            and d["tradeline_item_id"] == dispute["tradeline_item_id"]
            and d["id"] != dispute_id
            and d.get("submitted_day", 0) >= clock.day - 365
        )
        if existing_count >= 3:
            raise ApiError(
                "ERR_FRIVOLOUS_DISPUTE",
                "More than 3 disputes on the same tradeline within 365 days.",
                409,
            )

        # Side effect 1: status -> UNDER_INVESTIGATION.
        dispute["status"] = "UNDER_INVESTIGATION"
        stamp_update(dispute)

        # Side effect 2: auto-create one FurnisherInquiry.
        furnisher_id = _tradeline_furnisher_id(dispute["tradeline_item_id"])
        fi = stamp_create_append_only(
            {
                "dispute_id": dispute_id,
                "furnisher_id": furnisher_id,
                "forwarded_day": clock.day,
                "reverification_deadline_day": reverification_deadline(clock.day),
                "response": "PENDING",
                "response_day": None,
                "response_payload": None,
            }
        )
        store.furnisher_inquiries[fi["id"]] = fi

        # Side effect 3: posture recompute -> RESTRICTED.
        recompute_posture(dispute["credit_report_id"])

    return json_object(dispute, 200)


# ----------------------------------------------------------------------
# POST /consumers/{id}/disputes/{id}/additional_info
# ----------------------------------------------------------------------


@bp_disputes.route(
    "/consumers/<consumer_id>/disputes/<dispute_id>/additional_info",
    methods=["POST"],
)
@require_auth(["Consumer"])
def additional_info(consumer_id: str, dispute_id: str):
    enforce_consumer_ownership(consumer_id)
    dispute = _dispute_or_404(consumer_id, dispute_id)
    body = parse_json_body()
    new_docs = body.get("supporting_documents")
    with store.lock:
        check_occ(dispute, body)
        # Priority 5: state.
        if dispute["status"] != "UNDER_INVESTIGATION":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "additional_info requires UNDER_INVESTIGATION.",
                409,
            )
        if dispute["additional_info_accepted"]:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "additional_info has already been accepted.",
                409,
            )
        # Priority 9: deadline must not have passed.
        if clock.day > dispute["deadline_day"]:
            raise ApiError(
                "ERR_DISPUTE_DEADLINE_PASSED",
                "Dispute deadline has passed.",
                409,
            )
        # Validate any supplied new documents (priority 11 — must be non-empty).
        if new_docs is not None:
            validated = _validate_supporting_documents(new_docs)
            dispute["supporting_documents"] = dispute["supporting_documents"] + validated

        dispute["additional_info_accepted"] = True
        dispute["deadline_day"] = extended_deadline(dispute["submitted_day"])
        stamp_update(dispute)

    return json_object(dispute, 200)


# ----------------------------------------------------------------------
# POST /consumers/{id}/disputes/{id}/furnisher_response
# ----------------------------------------------------------------------


@bp_disputes.route(
    "/consumers/<consumer_id>/disputes/<dispute_id>/furnisher_response",
    methods=["POST"],
)
@require_auth(["BureauOperator"])
def furnisher_response(consumer_id: str, dispute_id: str):
    dispute = _dispute_or_404(consumer_id, dispute_id)
    body = parse_json_body()
    response = require_field(body, "response", types=[str])
    response_payload = opt_field(body, "response_payload", types=[dict]) or {}

    if response not in VALID_FURNISHER_RESPONSES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"response must be one of {sorted(VALID_FURNISHER_RESPONSES)}.",
            400,
        )

    with store.lock:
        check_occ(dispute, body)
        # Priority 5: state.
        if dispute["status"] != "UNDER_INVESTIGATION":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "furnisher_response requires UNDER_INVESTIGATION.",
                409,
            )
        inquiry = _current_inquiry(dispute_id)
        if inquiry is None or inquiry["response"] != "PENDING":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "No PENDING FurnisherInquiry for this dispute.",
                409,
            )
        # Priority 8: reage prohibition on furnisher_response.
        # PRD §3.3: 'if the furnisher's response_payload carries a
        # new_dofd_day strictly greater than the tradeline's current
        # reported_dofd_day, the request is rejected with ERR_REAGE_PROHIBITED.'
        # Unconditional on requested_action.
        if (
            "new_dofd_day" in response_payload
            and isinstance(response_payload["new_dofd_day"], int)
            and not isinstance(response_payload["new_dofd_day"], bool)
        ):
            tradeline = store.tradeline_items[dispute["tradeline_item_id"]]
            if response_payload["new_dofd_day"] > tradeline["reported_dofd_day"]:
                raise ApiError(
                    "ERR_REAGE_PROHIBITED",
                    "new_dofd_day cannot be moved later than reported_dofd_day.",
                    409,
                )
        # Priority 9: dispute deadline.
        if clock.day > dispute["deadline_day"]:
            raise ApiError(
                "ERR_DISPUTE_DEADLINE_PASSED",
                "Dispute deadline has passed.",
                409,
            )
        # Priority 10: furnisher reverification deadline (inclusive).
        if clock.day > inquiry["reverification_deadline_day"]:
            raise ApiError(
                "ERR_FURNISHER_LATE",
                "Furnisher reverification deadline has passed.",
                409,
            )

        # Apply side effects on the inquiry (append-only entity — only one initial population).
        inquiry["response"] = response
        inquiry["response_day"] = clock.day
        inquiry["response_payload"] = response_payload

        # Advance dispute -> RESULTS_PENDING.
        dispute["status"] = "RESULTS_PENDING"
        stamp_update(dispute)

    return json_object(dispute, 200)


# ----------------------------------------------------------------------
# POST /consumers/{id}/disputes/{id}/issue_result_notice
# ----------------------------------------------------------------------


def _apply_tradeline_changes(
    tradeline: dict, action: str, payload: dict
) -> bool:
    """Apply payload to tradeline. Returns True if any field actually changed."""
    changed = False
    if action == "CORRECT_BALANCE":
        new_bal = payload.get("new_balance_cents")
        if isinstance(new_bal, int) and not isinstance(new_bal, bool) and new_bal >= 0:
            if tradeline["balance_cents"] != new_bal:
                tradeline["balance_cents"] = new_bal
                changed = True
    elif action == "CORRECT_STATUS":
        new_status = payload.get("new_payment_status")
        if new_status and tradeline["payment_status"] != new_status:
            tradeline["payment_status"] = new_status
            changed = True
    elif action == "CORRECT_DOFD":
        new_dofd = payload.get("new_dofd_day")
        if isinstance(new_dofd, int) and not isinstance(new_dofd, bool):
            if tradeline["reported_dofd_day"] != new_dofd:
                tradeline["reported_dofd_day"] = new_dofd
                changed = True
    elif action == "DELETE_ITEM":
        if tradeline["payment_status"] != "DELETED":
            tradeline["payment_status"] = "DELETED"
            changed = True
    return changed


@bp_disputes.route(
    "/consumers/<consumer_id>/disputes/<dispute_id>/issue_result_notice",
    methods=["POST"],
)
@require_auth(["BureauOperator"])
def issue_result_notice(consumer_id: str, dispute_id: str):
    dispute = _dispute_or_404(consumer_id, dispute_id)
    body = parse_json_body()
    with store.lock:
        check_occ(dispute, body)
        if dispute["status"] != "RESULTS_PENDING":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "issue_result_notice requires RESULTS_PENDING.",
                409,
            )
        inquiry = _current_inquiry(dispute_id)
        if inquiry is None or inquiry["response"] == "PENDING":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "FurnisherInquiry is not in a resolvable state.",
                409,
            )

        tradeline = store.tradeline_items[dispute["tradeline_item_id"]]
        report_id = dispute["credit_report_id"]
        response = inquiry["response"]

        # Priority 7: reage prohibition for issue_result_notice on CORRECT_DOFD.
        # Fires before the deadline check per PRD §3.13 boundary case.
        if (
            response == "UPDATED"
            and dispute["requested_action"] == "CORRECT_DOFD"
        ):
            new_dofd = (inquiry.get("response_payload") or {}).get("new_dofd_day")
            if not isinstance(new_dofd, int) or new_dofd > tradeline["reported_dofd_day"]:
                if isinstance(new_dofd, int) and new_dofd > tradeline["reported_dofd_day"]:
                    raise ApiError(
                        "ERR_REAGE_PROHIBITED",
                        "new_dofd_day cannot be moved later than reported_dofd_day.",
                        409,
                    )

        # Priority 9: deadline.
        if clock.day > dispute["deadline_day"]:
            raise ApiError(
                "ERR_DISPUTE_DEADLINE_PASSED",
                "Dispute deadline has passed.",
                409,
            )

        # Branch on furnisher response.
        if response == "VERIFIED":
            outcome = "VERIFIED"
            free_report_granted = False
            tradeline["verification_status"] = "VERIFIED"
            stamp_update(tradeline)
            summary = "Furnisher verified the disputed item; no changes made."
            new_status = "CLOSED_VERIFIED"
            actual_change = False
        elif response == "UPDATED":
            outcome = "UPDATED"
            free_report_granted = True
            actual_change = _apply_tradeline_changes(
                tradeline, dispute["requested_action"], inquiry.get("response_payload") or {}
            )
            tradeline["verification_status"] = "UPDATED"
            stamp_update(tradeline)
            summary = "Furnisher updated the disputed item per the response payload."
            new_status = "CLOSED_UPDATED"
        elif response in {"DELETED", "NO_RESPONSE"}:
            outcome = "DELETED"
            free_report_granted = True
            actual_change = tradeline["payment_status"] != "DELETED" or tradeline.get(
                "verification_status"
            ) != "DELETED"
            tradeline["payment_status"] = "DELETED"
            tradeline["verification_status"] = "DELETED"
            stamp_update(tradeline)
            summary = (
                "Furnisher could not verify the disputed item; tradeline deleted."
                if response == "NO_RESPONSE"
                else "Furnisher confirmed deletion of the disputed item."
            )
            new_status = "CLOSED_DELETED"
        else:
            # Should never reach: only VERIFIED/UPDATED/DELETED/NO_RESPONSE are possible.
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                f"Unsupported furnisher response: {response}",
                409,
            )

        # Create ResultNotice (append-only).
        notice = stamp_create_append_only(
            {
                "dispute_id": dispute_id,
                "issued_day": clock.day,
                "delivery_channel": dispute["channel"],
                "outcome": outcome,
                "free_report_granted": free_report_granted,
                "summary": summary,
            }
        )
        store.result_notices[notice["id"]] = notice

        # Advance the dispute.
        dispute["status"] = new_status
        dispute["investigation_outcome"] = outcome
        dispute["result_notice_id"] = notice["id"]
        stamp_update(dispute)

        # Side effects: FICO recompute, free-report grant, posture recompute.
        if response in {"UPDATED", "DELETED", "NO_RESPONSE"}:
            recompute_fico_on_report(report_id)
            apply_free_report_grant(
                consumer_id, outcome=outcome, actual_field_changed=actual_change
            )
        recompute_posture(report_id)

    return json_object(notice, 200)


# ----------------------------------------------------------------------
# POST /consumers/{id}/disputes/{id}/dismiss_frivolous
# ----------------------------------------------------------------------


@bp_disputes.route(
    "/consumers/<consumer_id>/disputes/<dispute_id>/dismiss_frivolous",
    methods=["POST"],
)
@require_auth(["BureauOperator"])
def dismiss_frivolous(consumer_id: str, dispute_id: str):
    dispute = _dispute_or_404(consumer_id, dispute_id)
    body = parse_json_body()
    with store.lock:
        check_occ(dispute, body)
        if dispute["status"] != "RECEIVED":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "dismiss_frivolous requires RECEIVED.",
                409,
            )
        # The current dispute is the most-recent submission. Frivolous if there are
        # 3+ prior submissions on the same tradeline within last 365 days (i.e., this is #4+).
        cutoff = clock.day - 365
        prior_count = sum(
            1
            for d in store.disputes.values()
            if d["consumer_id"] == consumer_id
            and d["tradeline_item_id"] == dispute["tradeline_item_id"]
            and d["id"] != dispute_id
            and d.get("submitted_day", 0) >= cutoff
        )
        if prior_count < 3:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Dispute is not frivolous (fewer than 3 prior submissions in 365 days).",
                409,
            )

        dispute["status"] = "CLOSED_DISMISSED"
        dispute["investigation_outcome"] = "DISMISSED_FRIVOLOUS"
        stamp_update(dispute)

        notice = stamp_create_append_only(
            {
                "dispute_id": dispute_id,
                "issued_day": clock.day,
                "delivery_channel": dispute["channel"],
                "outcome": "DISMISSED_FRIVOLOUS",
                "free_report_granted": False,
                "summary": "Dispute dismissed as frivolous.",
            }
        )
        store.result_notices[notice["id"]] = notice
        dispute["result_notice_id"] = notice["id"]
        stamp_update(dispute)
        recompute_posture(dispute["credit_report_id"])

    return json_object(notice, 200)
