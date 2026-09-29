"""Replacement requests: intake, screening, committee and funding."""

from decimal import Decimal

from flask import Blueprint, g

import lookups
import serializers
from db import db, new_child_row, new_row, ordered, touch
from errors import ApiError
from middleware import (CAPITAL_PLANNER, CLINICAL_REQUESTER, COMMITTEE_MEMBER,
                        guard)
from response import created_response, object_response
from services import allocation as allocation_service
from services import cascades, committee, pricing, ruls, scoring
from validation import (body, bool_field, dt_field, enum_field, int_field,
                        pagination, q_bool, q_str, raw_ref, str_field)

bp = Blueprint("requests", __name__)

VOTES = ("APPROVE", "REJECT", "ABSTAIN", "VETO")
DECISIONS = ("ACCEPT", "RETURN")
MAX_REVISIONS = 3

EDITABLE_STATES = ("DRAFT", "RETURNED")
WITHDRAWABLE_STATES = ("DRAFT", "RETURNED", "SUBMITTED", "SCREENED", "SCORED")
LIVE_SIBLING_EXCLUDED = ("WITHDRAWN", "REJECTED", "DEFERRED")


def _check_mod_cap(modification_cents, capital_cents):
    # Exact integer cross-multiplication of the thirty-percent cap.
    if 10 * modification_cents > 3 * capital_cents:
        raise ApiError("ERR_MODIFICATION_COST_EXCEEDS_CAP")


def _check_mandate(flag, deadline_raw):
    if flag and deadline_raw is None:
        raise ApiError("ERR_MANDATE_DEADLINE_REQUIRED")


def _require_state(request_row, allowed):
    if request_row["status"] not in allowed:
        raise ApiError("ERR_REQUEST_INVALID_STATE")


def _require_own_department(department_id):
    if g.user_id != department_id:
        raise ApiError("ERR_DEPARTMENT_SCOPE_VIOLATION")


# ----------------------------------------------------------------- intake

@bp.route("/capital/requests", methods=["POST"])
@guard(CLINICAL_REQUESTER)
def create_request():
    data = body()
    for key, resolver in (("cycle_id", lookups.cycle),
                          ("department_id", lookups.department),
                          ("asset_id", lookups.asset),
                          ("sponsor_member_id", lookups.member)):
        ref = raw_ref(data, key)
        if ref is not None:
            resolver(ref)

    department_ref = raw_ref(data, "department_id")
    if department_ref is not None:
        _require_own_department(department_ref)

    cycle_id = str_field(data, "cycle_id", 1, None)
    department_id = str_field(data, "department_id", 1, None)
    asset_id = str_field(data, "asset_id", 1, None)
    justification = str_field(data, "clinical_justification", 20, 2000)
    current_volume = int_field(data, "current_annual_volume", 0)
    projected_volume = int_field(data, "projected_annual_volume", 1)
    capital_cents = int_field(data, "estimated_capital_cents", 1)
    service_cents = int_field(data, "annual_service_contract_cents", 0)
    disposable_cents = int_field(data, "disposable_unit_cents", 0)
    sponsor_member_id = str_field(data, "sponsor_member_id", 1, None,
                                  required=False)
    modification_cents = int_field(data, "facility_modification_cents", 0,
                                   required=False, default=0)
    mandate_flag = bool_field(data, "regulatory_mandate_flag", required=False,
                              default=False)
    mandate_raw, mandate_deadline = dt_field(data, "mandate_deadline",
                                             required=False)

    cycle = lookups.cycle(cycle_id)
    department = lookups.department(department_id)
    asset = lookups.asset(asset_id)
    _require_own_department(department["id"])
    if sponsor_member_id is not None:
        lookups.member(sponsor_member_id)

    if asset["department_id"] != department["id"]:
        raise ApiError("ERR_ASSET_DEPARTMENT_MISMATCH")
    _check_mod_cap(modification_cents, capital_cents)
    _check_mandate(mandate_flag, mandate_raw)

    row = new_row({
        "cycle_id": cycle["id"],
        "department_id": department["id"],
        "asset_id": asset["id"],
        "sponsor_member_id": sponsor_member_id,
        "clinical_justification": justification,
        "current_annual_volume": current_volume,
        "projected_annual_volume": projected_volume,
        "estimated_capital_cents": capital_cents,
        "facility_modification_cents": modification_cents,
        "annual_service_contract_cents": service_cents,
        "disposable_unit_cents": disposable_cents,
        "regulatory_mandate_flag": mandate_flag,
        "mandate_deadline": mandate_raw,
        "_mandate_deadline": mandate_deadline,
        "status": "DRAFT",
        "revision_count": 0,
        "return_count": 0,
        "safety_driver": Decimal("0.00"),
        "growth_driver": Decimal("0.00"),
        "regulatory_driver": Decimal("0.00"),
        "eos_driver": Decimal("0.00"),
        "composite_score": Decimal("0.00"),
        "expedited": False,
        "budgetary_operating_5y_cents": 0,
        "budgetary_tco_cents": 0,
        "negotiated_operating_5y_cents": None,
        "negotiated_tco_cents": None,
        "baseline_year1_opex_cents": 0,
        "funded_amount_cents": 0,
    })
    db.requests[row["id"]] = row
    return created_response(serializers.request_row(row))


@bp.route("/capital/requests/<request_id>", methods=["PATCH"])
@guard(CLINICAL_REQUESTER)
def patch_request(request_id):
    request_row = lookups.request_row(request_id)
    data = body()
    ref = raw_ref(data, "sponsor_member_id")
    if ref is not None:
        lookups.member(ref)

    _require_own_department(request_row["department_id"])

    justification = str_field(data, "clinical_justification", 20, 2000,
                              required=False)
    current_volume = int_field(data, "current_annual_volume", 0, required=False)
    projected_volume = int_field(data, "projected_annual_volume", 1,
                                 required=False)
    capital_cents = int_field(data, "estimated_capital_cents", 1, required=False)
    modification_cents = int_field(data, "facility_modification_cents", 0,
                                   required=False)
    service_cents = int_field(data, "annual_service_contract_cents", 0,
                              required=False)
    disposable_cents = int_field(data, "disposable_unit_cents", 0, required=False)
    sponsor_member_id = str_field(data, "sponsor_member_id", 1, None,
                                 required=False)
    mandate_flag = bool_field(data, "regulatory_mandate_flag", required=False)
    mandate_raw, mandate_deadline = dt_field(data, "mandate_deadline",
                                             required=False)

    effective_modification = (modification_cents if modification_cents is not None
                              else request_row["facility_modification_cents"])
    effective_capital = (capital_cents if capital_cents is not None
                         else request_row["estimated_capital_cents"])
    _check_mod_cap(effective_modification, effective_capital)

    effective_flag = (mandate_flag if mandate_flag is not None
                      else request_row["regulatory_mandate_flag"])
    effective_deadline = (mandate_raw if mandate_raw is not None
                          else request_row["mandate_deadline"])
    _check_mandate(effective_flag, effective_deadline)

    _require_state(request_row, EDITABLE_STATES)

    if justification is not None:
        request_row["clinical_justification"] = justification
    if current_volume is not None:
        request_row["current_annual_volume"] = current_volume
    if projected_volume is not None:
        request_row["projected_annual_volume"] = projected_volume
    if capital_cents is not None:
        request_row["estimated_capital_cents"] = capital_cents
    if modification_cents is not None:
        request_row["facility_modification_cents"] = modification_cents
    if service_cents is not None:
        request_row["annual_service_contract_cents"] = service_cents
    if disposable_cents is not None:
        request_row["disposable_unit_cents"] = disposable_cents
    if sponsor_member_id is not None:
        request_row["sponsor_member_id"] = sponsor_member_id
    if mandate_flag is not None:
        request_row["regulatory_mandate_flag"] = mandate_flag
    if mandate_raw is not None:
        request_row["mandate_deadline"] = mandate_raw
        request_row["_mandate_deadline"] = mandate_deadline

    if request_row["status"] == "RETURNED":
        request_row["status"] = "DRAFT"
        request_row["revision_count"] += 1
    touch(request_row)
    return object_response(serializers.request_row(request_row))


@bp.route("/capital/requests/<request_id>", methods=["GET"])
@guard()
def get_request(request_id):
    return object_response(
        serializers.request_row(lookups.request_row(request_id)))


@bp.route("/capital/requests", methods=["GET"])
@guard()
def list_requests():
    limit, offset = pagination()
    rows = lookups.filtered(db.requests.values(), [
        ("cycle_id", q_str("cycle_id")),
        ("department_id", q_str("department_id")),
        ("asset_id", q_str("asset_id")),
        ("sponsor_member_id", q_str("sponsor_member_id")),
        ("status", q_str("status")),
        ("expedited", q_bool("expedited")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.request_row)


# ------------------------------------------------------------- transitions

@bp.route("/capital/requests/<request_id>/submit", methods=["POST"])
@guard(CLINICAL_REQUESTER)
def submit_request(request_id):
    request_row = lookups.request_row(request_id)
    _require_own_department(request_row["department_id"])

    _check_mod_cap(request_row["facility_modification_cents"],
                   request_row["estimated_capital_cents"])
    _check_mandate(request_row["regulatory_mandate_flag"],
                   request_row["mandate_deadline"])

    cycle = lookups.cycle(request_row["cycle_id"])
    if cycle["status"] != "INTAKE_OPEN":
        raise ApiError("ERR_CYCLE_INVALID_STATE")

    _require_state(request_row, EDITABLE_STATES)

    asset = lookups.asset(request_row["asset_id"])
    if asset["status"] == "DECOMMISSIONED" or not ruls.replacement_eligible(asset):
        raise ApiError("ERR_ASSET_NOT_REPLACEMENT_ELIGIBLE")

    for sibling in ordered(db.requests.values()):
        if sibling["id"] == request_row["id"]:
            continue
        if sibling["cycle_id"] != request_row["cycle_id"]:
            continue
        if sibling["asset_id"] != request_row["asset_id"]:
            continue
        if sibling["status"] not in LIVE_SIBLING_EXCLUDED:
            raise ApiError("ERR_DUPLICATE_ASSET_REQUEST")

    if request_row["revision_count"] > MAX_REVISIONS:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")

    request_row["status"] = "SUBMITTED"
    pricing.write_budgetary(request_row)
    touch(request_row)
    return object_response(serializers.request_row(request_row))


@bp.route("/capital/requests/<request_id>/screen", methods=["POST"])
@guard(CAPITAL_PLANNER)
def screen_request(request_id):
    request_row = lookups.request_row(request_id)
    data = body()
    decision = enum_field(data, "decision", DECISIONS)
    str_field(data, "screening_note", 0, 500, required=False)

    cycle = lookups.cycle(request_row["cycle_id"])
    if cycle["status"] not in ("INTAKE_OPEN", "SCORING"):
        raise ApiError("ERR_CYCLE_INVALID_STATE")

    _require_state(request_row, ("SUBMITTED",))

    if decision == "ACCEPT":
        request_row["status"] = "SCREENED"
    else:
        request_row["status"] = "RETURNED"
        request_row["return_count"] += 1
    touch(request_row)
    return object_response(serializers.request_row(request_row))


@bp.route("/capital/requests/<request_id>/withdraw", methods=["POST"])
@guard(CLINICAL_REQUESTER)
def withdraw_request(request_id):
    request_row = lookups.request_row(request_id)
    _require_own_department(request_row["department_id"])
    data = body()
    str_field(data, "withdrawal_reason", 0, 500, required=False)

    _require_state(request_row, WITHDRAWABLE_STATES)

    was_scored = request_row["status"] == "SCORED"
    request_row["status"] = "WITHDRAWN"
    touch(request_row)
    if was_scored:
        cycle = db.cycles.get(request_row["cycle_id"])
        if cycle is not None:
            scoring.refresh_cycle_counts(cycle, bump=True)
    return object_response(serializers.request_row(request_row))


@bp.route("/capital/requests/<request_id>/scores", methods=["GET"])
@guard()
def list_scores(request_id):
    request_row = lookups.request_row(request_id)
    limit, offset = pagination()
    rows = lookups.filtered(
        [s for s in db.scores.values() if s["request_id"] == request_row["id"]],
        [("reason", q_str("reason"))])
    return lookups.paginate(rows, limit, offset, serializers.score)


# ---------------------------------------------------------------- ballots

@bp.route("/capital/requests/<request_id>/votes", methods=["POST"])
@guard(COMMITTEE_MEMBER)
def create_vote(request_id):
    request_row = lookups.request_row(request_id)
    member = lookups.member(g.user_id)
    data = body()
    vote = enum_field(data, "vote", VOTES)
    expected = int_field(data, "expected_request_version")
    rationale = str_field(data, "rationale", 0, 500, required=False)

    cycle = lookups.cycle(request_row["cycle_id"])
    if cycle["status"] != "ALLOCATED":
        raise ApiError("ERR_CYCLE_INVALID_STATE")

    _require_state(request_row, ("SCORED", "IN_COMMITTEE"))

    if expected != request_row["version"]:
        raise ApiError("ERR_STALE_REQUEST_VERSION")

    facility_id = lookups.request_facility_id(request_row)
    if not committee.is_eligible(member, request_row, facility_id):
        raise ApiError("ERR_VOTE_CONFLICT_OF_INTEREST")

    if vote == "VETO" and member["seat"] != "SAFETY_OFFICER":
        raise ApiError("ERR_VETO_NOT_PERMITTED")

    for ballot in ordered(db.votes.values()):
        if (ballot["request_id"] == request_row["id"]
                and ballot["member_id"] == member["id"]
                and not ballot["superseded"]):
            ballot["superseded"] = True

    row = new_child_row({
        "request_id": request_row["id"],
        "member_id": member["id"],
        "vote": vote,
        "rationale": rationale,
        "counted_weight": member["voting_weight"],
        "superseded": False,
    })
    db.votes[row["id"]] = row

    if request_row["status"] == "SCORED":
        request_row["status"] = "IN_COMMITTEE"
    touch(request_row)
    return created_response(serializers.vote(row))


@bp.route("/capital/requests/<request_id>/votes", methods=["GET"])
@guard()
def list_request_votes(request_id):
    request_row = lookups.request_row(request_id)
    limit, offset = pagination()
    rows = lookups.filtered(
        [v for v in db.votes.values() if v["request_id"] == request_row["id"]],
        [("member_id", q_str("member_id")),
         ("superseded", q_bool("superseded"))])
    return lookups.paginate(rows, limit, offset, serializers.vote)


@bp.route("/capital/requests/<request_id>/committee-decision", methods=["POST"])
@guard(COMMITTEE_MEMBER)
def committee_decision(request_id):
    request_row = lookups.request_row(request_id)
    member = lookups.member(g.user_id)
    data = body()
    str_field(data, "decision_note", 0, 500, required=False)

    _require_state(request_row, ("IN_COMMITTEE",))

    if member["seat"] != "CHAIR":
        raise ApiError("ERR_CHAIR_REQUIRED")

    facility_id = lookups.request_facility_id(request_row)
    outcome = committee.tally(request_row, facility_id)
    request_row["status"] = outcome
    touch(request_row)
    return object_response(serializers.request_row(request_row))


# ---------------------------------------------------------------- funding

@bp.route("/capital/requests/<request_id>/fund", methods=["POST"])
@guard(CAPITAL_PLANNER)
def fund_request(request_id):
    request_row = lookups.request_row(request_id)
    cycle = lookups.cycle(request_row["cycle_id"])
    if cycle["status"] != "ALLOCATED":
        raise ApiError("ERR_CYCLE_INVALID_STATE")

    _require_state(request_row, ("APPROVED",))

    if (cycle["allocated_by_user_id"] is not None
            and g.user_id == cycle["allocated_by_user_id"]):
        raise ApiError("ERR_SOD_ALLOCATOR_CANNOT_FUND")

    facility_id = lookups.request_facility_id(request_row)
    allocation = lookups.find_allocation(cycle["id"], facility_id)
    if allocation is None:
        raise ApiError("ERR_NO_FACILITY_ALLOCATION")

    draw = pricing.funded_amount(request_row)
    if allocation["available_cents"] < draw:
        raise ApiError("ERR_ALLOCATION_INSUFFICIENT")

    request_row["status"] = "FUNDED"
    request_row["funded_amount_cents"] = draw
    touch(request_row)

    allocation["committed_cents"] += draw
    allocation_service.refresh_available(allocation)
    cycle_changed = allocation_service.refresh_posture(allocation, cycle)
    touch(allocation)

    if cascades.auto_commit_if_exhausted(cycle):
        cycle_changed = True
        cascades.defer_open_requests(cycle)
    if cycle_changed:
        touch(cycle)

    asset = db.assets.get(request_row["asset_id"])
    if asset is not None and asset["status"] in ("IN_SERVICE", "DERATED"):
        asset["status"] = "REPLACEMENT_PENDING"
        touch(asset)

    return object_response(serializers.request_row(request_row))


@bp.route("/capital/requests/<request_id>/withdraw-funding", methods=["POST"])
@guard(CAPITAL_PLANNER)
def withdraw_funding(request_id):
    request_row = lookups.request_row(request_id)
    data = body()
    str_field(data, "withdrawal_reason", 0, 500, required=False)

    _require_state(request_row, ("FUNDED",))

    for project in db.projects.values():
        if (project["request_id"] == request_row["id"]
                and project["record_status"] == "ACTIVE"):
            raise ApiError("ERR_PROJECT_ACTIVE")

    cycle = lookups.cycle(request_row["cycle_id"])
    facility_id = lookups.request_facility_id(request_row)
    allocation = lookups.find_allocation(cycle["id"], facility_id)
    if allocation is None:
        raise ApiError("ERR_NO_FACILITY_ALLOCATION")

    released = request_row["funded_amount_cents"]

    request_row["status"] = "APPROVED"
    request_row["funded_amount_cents"] = 0
    touch(request_row)

    cascades.apply_committed_delta(allocation, cycle, -released)

    asset = db.assets.get(request_row["asset_id"])
    if asset is not None and asset["status"] == "REPLACEMENT_PENDING":
        asset["status"] = ruls.post_derate_status(asset)
        touch(asset)

    return object_response(serializers.request_row(request_row))
