"""BackgroundCheck routes — including the FAIL cascade."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format, now
from ..common import bump, get_json_body, require_enum, require_fields, stamp_new
from ..errors import ApiError
from ..lookups import path_background_check, path_offer
from ..response import respond
from ..serializers import serialize_background_check
from ..services import (
    cascade_offer_rescind, post_hire_revoke, recompute_goal_for_requisition,
)
from ..store import store


background_checks_bp = Blueprint("background_checks", __name__)


VENDORS = {"ACME_BG", "VERIFY_INC", "FED_CHECKS"}
OUTCOMES = {"PASS", "FAIL"}


@background_checks_bp.post("/offers/<oid>/background-check")
@require_auth("Recruiter")
def order_background_check(oid):
    body = get_json_body()
    require_fields(body, "vendor")
    vendor = require_enum(body["vendor"], "vendor", VENDORS)

    with store.lock:
        offer = path_offer(oid)
        if g.user_id != store.offers_created_by.get(offer["id"]):
            raise ApiError("ERR_FORBIDDEN", "Only the creating recruiter may order a background check")
        # PRD §3.7: "Exactly one background check may be active per offer".
        # "Active" reads as non-terminal; the terminal states are
        # PASSED, FAILED, and CANCELLED. So a new BGC may be ordered
        # against an offer when no PENDING BGC currently exists.
        # This is the reading that makes PRD §3.5's "BGC must be PASSED
        # to approve final step" and §3.7's "FAIL on APPROVED/EXTENDED/
        # ACCEPTED offer fires the cascade" simultaneously reachable.
        for bg in store.background_checks.values():
            if bg["offer_id"] == oid and bg["status"] == "PENDING":
                raise ApiError("ERR_INVALID_STATE", "An active BackgroundCheck already exists for this offer")
        ts = iso_format(now())
        bg = stamp_new({
            "offer_id": oid,
            "vendor": vendor,
            "status": "PENDING",
            "ordered_at": ts,
            "result_received_at": None,
        })
        store.background_checks[bg["id"]] = bg
    return respond(serialize_background_check(bg), 201)


@background_checks_bp.get("/background-checks/<bid>")
@require_auth("Recruiter", "ComplianceOfficer", "PlatformAdmin")
def get_background_check(bid):
    with store.lock:
        return respond(serialize_background_check(path_background_check(bid)))


@background_checks_bp.post("/background-checks/<bid>/report-result")
@require_auth("ComplianceOfficer")
def report_result(bid):
    body = get_json_body()
    require_fields(body, "outcome")
    outcome = require_enum(body["outcome"], "outcome", OUTCOMES)

    with store.lock:
        bg = path_background_check(bid)
        if bg["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "BackgroundCheck is not PENDING")
        bg["status"] = "PASSED" if outcome == "PASS" else "FAILED"
        bg["result_received_at"] = iso_format(now())
        bump(bg)

        if outcome == "FAIL":
            offer = store.offers.get(bg["offer_id"])
            if offer is not None:
                if offer["status"] in {"APPROVED", "EXTENDED"}:
                    cascade_offer_rescind(offer, reason_for_app="FAILED_BACKGROUND_CHECK")
                elif offer["status"] == "ACCEPTED":
                    post_hire_revoke(offer)
                # If offer is in other states the BG fail still records but no cascade applies.
        return respond(serialize_background_check(bg))


@background_checks_bp.post("/background-checks/<bid>/cancel")
@require_auth("Recruiter")
def cancel_background_check(bid):
    with store.lock:
        bg = path_background_check(bid)
        if bg["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "BackgroundCheck is not PENDING")
        offer = store.offers.get(bg["offer_id"])
        if offer is None:
            raise ApiError("ERR_NOT_FOUND", "Linked offer not found")
        if g.user_id != store.offers_created_by.get(offer["id"]):
            raise ApiError("ERR_FORBIDDEN", "Only the creating recruiter may cancel this background check")
        if offer["status"] not in {"NEGOTIATING", "DECLINED", "RESCINDED", "EXPIRED"}:
            raise ApiError(
                "ERR_INVALID_STATE",
                "Linked offer is still live — background check cannot be cancelled",
            )
        bg["status"] = "CANCELLED"
        bump(bg)
        return respond(serialize_background_check(bg))
