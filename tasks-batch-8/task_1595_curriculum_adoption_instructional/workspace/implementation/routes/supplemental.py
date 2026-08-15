"""SupplementalRequest endpoints (PRD §3.8): teacher filing, specialist
vetting with segregation of duties and the fiscal envelope."""

from decimal import Decimal

from flask import Blueprint, request

import serializers
from db import bump, new_id, now_clock, refresh, stamp_new, store
from errors import (ApiError, ERR_SEGREGATION_OF_DUTIES, budget_exceeded,
                    invalid_state)
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404, opt_str,
                        req_decimal, req_enum, req_str, require_roles)
from response import paginate, sort_created, success_object
from services.calculations import ledger_available

bp = Blueprint("supplemental_requests", __name__)

SUBJECT_AREAS = ("MATHEMATICS", "ENGLISH_LANGUAGE_ARTS", "SCIENCE",
                 "SOCIAL_STUDIES", "WORLD_LANGUAGES")
GRADE_BANDS = ("K_5", "GRADES_6_8", "GRADES_9_12")


def _get_sr(sr_id):
    return get_or_404(store.supplemental_requests, sr_id, "SupplementalRequest")


@bp.route("/supplemental-requests", methods=["POST"])
def create_supplemental_request():
    user_id, role = auth_context()
    require_roles(role, ("Teacher",))
    body = get_body()
    # Tier 3 body FK resolution precedes the remaining shape checks.
    cycle = None
    raw_cycle_id = body.get("cycle_id")
    if isinstance(raw_cycle_id, str) and raw_cycle_id:
        cycle = get_or_404(store.cycles, raw_cycle_id, "AdoptionCycle")
    title = req_str(body, "title")
    publisher_name = req_str(body, "publisher_name")
    estimated_cost = req_decimal(body, "estimated_cost", minimum=Decimal("0"),
                                 exclusive_minimum=True)
    subject_area = req_enum(body, "subject_area", SUBJECT_AREAS)
    grade_band = req_enum(body, "grade_band", GRADE_BANDS)
    school_code = req_str(body, "school_code")
    justification = opt_str(body, "justification")
    cycle_id = req_str(body, "cycle_id")
    if cycle is None:
        cycle = get_or_404(store.cycles, cycle_id, "AdoptionCycle")
    sr = {
        "id": new_id(),
        "cycle_id": cycle["id"],
        "requester_user_id": user_id,
        "title": title,
        "publisher_name": publisher_name,
        "estimated_cost": estimated_cost,
        "subject_area": subject_area,
        "grade_band": grade_band,
        "school_code": school_code,
        "justification": justification,
        "approver_user_id": None,
        "approved_at": None,
        "status": "SUBMITTED",
    }
    stamp_new(sr)
    store.supplemental_requests[sr["id"]] = sr
    return success_object(serializers.supplemental_request(sr), status=201)


@bp.route("/supplemental-requests", methods=["GET"])
def list_supplemental_requests():
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    items = list(store.supplemental_requests.values())
    cycle_id = request.args.get("cycle_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [s for s in items if s["cycle_id"] == cycle_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate(sort_created(items), serializers.supplemental_request)


@bp.route("/supplemental-requests/<srId>", methods=["GET"])
def get_supplemental_request(srId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    return success_object(serializers.supplemental_request(_get_sr(srId)))


@bp.route("/supplemental-requests/<srId>/transitions", methods=["POST"])
def supplemental_request_transition(srId):
    user_id, role = auth_context()
    require_roles(role, ("InstructionalSpecialist",))
    sr = _get_sr(srId)
    body = get_body()
    to_state = req_enum(body, "to_state", ("VETTING", "APPROVED", "DENIED"))

    if to_state == "VETTING":
        if sr["status"] != "SUBMITTED":
            raise invalid_state("only a SUBMITTED request may enter VETTING")
    elif to_state == "DENIED":
        if sr["status"] != "VETTING":
            raise invalid_state("only a VETTING request may be denied")
    elif to_state == "APPROVED":
        if sr["status"] != "VETTING":
            raise invalid_state("only a VETTING request may be approved")
        # Tier 9 segregation of duties: approver != requester (HTTP 403).
        if user_id == sr["requester_user_id"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "the approver must differ from the requester")
        # Tier 12 fiscal envelope (inclusive: equal balance passes).
        ledger = store.ledgers.get(sr["cycle_id"])
        if ledger is None or ledger_available(ledger) < sr["estimated_cost"]:
            raise budget_exceeded()

    if to_state == "APPROVED":
        sr["approver_user_id"] = user_id
        sr["approved_at"] = now_clock()
        ledger["encumbered_total"] += sr["estimated_cost"]
        refresh(ledger)
    sr["status"] = to_state
    bump(sr)
    return success_object(serializers.supplemental_request(sr))
