"""Beneficiary designations and disposition elections (PRD sections 3.8, 3.9)."""
from flask import Blueprint, request

from authz import (ALL_ROLES, FIDUCIARY, PLATFORM_COMPLIANCE,
                   READ_ROLES_NO_PLATFORM, authenticate, require_action_role,
                   require_fiduciary_estate, require_platform_scope,
                   require_role)
from clock import CLOCK
from db import DB, bump, sorted_records, stamp_new
from errors import ApiError
from response import public, single
from routes.common import paged
from services import authority, lookup
from services import estate as estate_svc
from validation import (bad, parse_body, v_enum, v_id, v_int, v_str, v_text,
                        validate)

bp = Blueprint("dispositions", __name__)

DESIGNATION_SOURCES = ("WILL", "TRUST", "PLATFORM_DESIGNATION")
ELECTIONS = ("MEMORIALIZE", "DELETE", "TRANSFER")
TOTAL_SHARE_BP = 10000
SUPERSEDABLE = ("DRAFT", "PENDING_COUNTERSIGN", "SUBMITTED")

ELECTION_ACTIONS = ("COUNTERSIGN", "SUBMIT", "EXECUTE", "REJECT", "REVERSE")
ELECTION_ACTION_OWNERS = {
    "COUNTERSIGN": FIDUCIARY,
    "SUBMIT": FIDUCIARY,
    "EXECUTE": PLATFORM_COMPLIANCE,
    "REJECT": PLATFORM_COMPLIANCE,
    "REVERSE": PLATFORM_COMPLIANCE,
}

SUPPORT_FLAG = {
    "MEMORIALIZE": "supports_memorialization",
    "DELETE": "supports_deletion",
    "TRANSFER": "supports_transfer",
}


# --------------------------------------------------- BeneficiaryDesignation

@bp.route("/estates/<estate_id>/beneficiary-designations", methods=["POST"])
def create_designation(estate_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request), required={
        "beneficiary_name": v_str(200),
        "share_bp": v_int(1, TOTAL_SHARE_BP),
        "source": v_enum(DESIGNATION_SOURCES),
    }, optional={"relationship": v_str(60)})

    estate = lookup.get_estate(estate_id)
    require_fiduciary_estate(user_id, role, estate_id)
    estate_svc.require_open(estate)

    existing = lookup.estate_designations(estate_id)
    running_total = sum(d["share_bp"] for d in existing)
    if running_total + body["share_bp"] > TOTAL_SHARE_BP:
        raise ApiError("ERR_SHARE_TOTAL_INVALID")

    record = {
        "estate_id": estate_id,
        "beneficiary_name": body["beneficiary_name"],
        "relationship": body.get("relationship"),
        "share_bp": body["share_bp"],
        "source": body["source"],
        "allocation_rank": len(existing) + 1,
        "planned_allocation_cents": 0,
        "received_value_cents": 0,
    }
    stamp_new(record)
    DB.designations[record["id"]] = record
    return single(public(record), 201)


@bp.route("/beneficiary-designations/<designation_id>", methods=["GET"])
def read_designation(designation_id):
    _, role = authenticate(request)
    require_role(role, READ_ROLES_NO_PLATFORM)
    return single(public(lookup.get_designation(designation_id)), 200)


@bp.route("/beneficiary-designations", methods=["GET"])
def list_designations():
    _, role = authenticate(request)
    require_role(role, READ_ROLES_NO_PLATFORM)
    return paged(DB.designations.values(), request.args, {
        "estate_id": "estate_id",
        "source": "source",
    })


# ------------------------------------------------------ DispositionElection

@bp.route("/digital-assets/<asset_id>/disposition-elections", methods=["POST"])
def create_election(asset_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request), required={
        "election": v_enum(ELECTIONS),
        "expected_asset_version": v_int(0),
    }, optional={
        "beneficiary_designation_id": v_id(),
        "election_note": v_text(),
    })

    asset = lookup.get_asset(asset_id)
    designation = None
    if "beneficiary_designation_id" in body:
        designation = lookup.get_designation(body["beneficiary_designation_id"])
    require_fiduciary_estate(user_id, role, asset["estate_id"])
    if body["expected_asset_version"] != asset["version"]:
        raise ApiError("ERR_STALE_ASSET_VERSION")
    estate = lookup.estate_of_asset(asset)
    estate_svc.require_open(estate)

    election = body["election"]
    platform = DB.platforms.get(asset["platform_id"])
    if not authority.has_active_authority(asset):
        raise ApiError("ERR_NO_ACTIVE_AUTHORITY")
    if election == "TRANSFER" and asset["transferability"] != "TRANSFERABLE":
        raise ApiError("ERR_ASSET_NOT_TRANSFERABLE")
    if platform is None or not platform[SUPPORT_FLAG[election]]:
        raise ApiError("ERR_DISPOSITION_UNSUPPORTED")
    if election == "TRANSFER" and designation is None:
        raise ApiError("ERR_BENEFICIARY_REQUIRED")
    if election != "TRANSFER" and designation is not None:
        raise ApiError("ERR_BENEFICIARY_REQUIRED")

    record = {
        "asset_id": asset_id,
        "beneficiary_designation_id": designation["id"] if designation else None,
        "elected_by_fiduciary_id": user_id,
        "countersigned_by_fiduciary_id": None,
        "election": election,
        "status": "PENDING_COUNTERSIGN" if election == "DELETE" else "DRAFT",
        "election_note": body.get("election_note"),
        "attestation": None,
        "platform_confirmation_reference": None,
        "rejection_reason": None,
        "reversal_reason": None,
        "distributed_value_cents": 0,
        "executed_at": None,
    }
    stamp_new(record)
    DB.elections[record["id"]] = record

    return_to_pending = False
    for other in sorted_records(lookup.asset_elections(asset_id)):
        if other["id"] == record["id"] or other["status"] not in SUPERSEDABLE:
            continue
        if other["status"] == "SUBMITTED":
            return_to_pending = True
        other["status"] = "SUPERSEDED"
        bump(other)
    if return_to_pending:
        asset["disposition_status"] = "PENDING"
    bump(asset)
    estate_svc.recompute(estate)
    return single(public(record), 201)


@bp.route("/disposition-elections/<election_id>", methods=["GET"])
def read_election(election_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_election(election_id)), 200)


@bp.route("/disposition-elections", methods=["GET"])
def list_elections():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.elections.values(), request.args, {
        "asset_id": "asset_id",
        "beneficiary_designation_id": "beneficiary_designation_id",
        "elected_by_fiduciary_id": "elected_by_fiduciary_id",
        "countersigned_by_fiduciary_id": "countersigned_by_fiduciary_id",
        "election": "election",
        "status": "status",
    })


@bp.route("/disposition-elections/<election_id>/transitions", methods=["POST"])
def election_transition(election_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY, PLATFORM_COMPLIANCE))
    body = validate(parse_body(request),
                    required={"action": v_enum(ELECTION_ACTIONS)},
                    optional={
                        "attestation": v_text(),
                        "platform_confirmation_reference": v_text(),
                        "reason": v_text(),
                        "rejection_reason": v_text(),
                        "reversal_reason": v_text(),
                    })
    action = body["action"]
    require_action_role(role, action, ELECTION_ACTION_OWNERS)
    reason = body.get("reason")

    election = lookup.get_election(election_id)
    asset = lookup.asset_of_election(election)
    estate = lookup.estate_of_asset(asset)
    platform = DB.platforms.get(asset["platform_id"])
    require_fiduciary_estate(user_id, role, asset["estate_id"])
    require_platform_scope(user_id, role, asset["platform_id"])
    estate_svc.require_open(estate)

    status = election["status"]

    if action == "COUNTERSIGN":
        if status != "PENDING_COUNTERSIGN":
            raise ApiError("ERR_INVALID_ELECTION_STATE")
        actor = DB.fiduciaries.get(user_id)
        if actor is None or actor["letters_status"] != "ISSUED":
            raise ApiError("ERR_LETTERS_NOT_ISSUED")
        if user_id == election["elected_by_fiduciary_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        election["status"] = "DRAFT"
        election["countersigned_by_fiduciary_id"] = user_id
        election["attestation"] = body.get("attestation")
        bump(election)
        return single(public(election), 200)

    if action == "SUBMIT":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_ELECTION_STATE")
        if asset["disposition_status"] != "PENDING":
            raise ApiError("ERR_INVALID_ELECTION_STATE")
        actor = DB.fiduciaries.get(user_id)
        if actor is None or actor["letters_status"] != "ISSUED":
            raise ApiError("ERR_LETTERS_NOT_ISSUED")
        if not authority.has_active_authority(asset):
            raise ApiError("ERR_NO_ACTIVE_AUTHORITY")
        if (election["election"] == "DELETE"
                and election["countersigned_by_fiduciary_id"] is None):
            raise ApiError("ERR_COUNTERSIGN_REQUIRED")
        election["status"] = "SUBMITTED"
        bump(election)
        asset["disposition_status"] = "ELECTED"
        bump(asset)
        estate_svc.recompute(estate)
        return single(public(election), 200)

    if action == "REJECT":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_ELECTION_STATE")
        election["status"] = "REJECTED"
        election["rejection_reason"] = (
            body.get("rejection_reason") if "rejection_reason" in body else reason)
        bump(election)
        if asset["disposition_status"] != "PENDING":
            asset["disposition_status"] = "PENDING"
            bump(asset)
        estate_svc.recompute(estate)
        return single(public(election), 200)

    if action == "EXECUTE":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_ELECTION_STATE")
        if platform is None or platform["status"] == "SUSPENDED":
            raise ApiError("ERR_PLATFORM_SUSPENDED")
        kind = election["election"]
        if not platform[SUPPORT_FLAG[kind]]:
            raise ApiError("ERR_DISPOSITION_UNSUPPORTED")

        if kind == "TRANSFER":
            designation = DB.designations.get(election["beneficiary_designation_id"])
            if (asset["transferability"] != "TRANSFERABLE"
                    or asset["appraised_value_cents"] is None
                    or not estate_svc.has_computed_or_finalized_run(estate["id"])):
                raise ApiError("ERR_VALUATION_REQUIRED")
            amount = asset["appraised_value_cents"]
            if amount > estate["undistributed_value_cents"]:
                raise ApiError("ERR_DISTRIBUTION_POOL_EXHAUSTED")
            if designation is None:
                raise ApiError("ERR_BENEFICIARY_REQUIRED")
            if (designation["received_value_cents"] + amount
                    > designation["planned_allocation_cents"]):
                raise ApiError("ERR_BENEFICIARY_ALLOCATION_EXCEEDED")

        election["status"] = "EXECUTED"
        election["executed_at"] = CLOCK.iso()
        election["platform_confirmation_reference"] = body.get(
            "platform_confirmation_reference")

        if kind == "MEMORIALIZE":
            asset["disposition_status"] = "EXECUTED"
            asset["disposed_at"] = CLOCK.iso()
            bump(asset)
        elif kind == "DELETE":
            asset["disposition_status"] = "PURGED"
            asset["disposed_at"] = CLOCK.iso()
            bump(asset)
        else:
            designation = DB.designations.get(election["beneficiary_designation_id"])
            amount = asset["appraised_value_cents"]
            election["distributed_value_cents"] = amount
            designation["received_value_cents"] += amount
            bump(designation)
            estate["undistributed_value_cents"] -= amount
            bump(estate)
            asset["disposition_status"] = "EXECUTED"
            asset["disposed_at"] = CLOCK.iso()
            bump(asset)
        bump(election)
        estate_svc.recompute(estate)
        return single(public(election), 200)

    # REVERSE
    if status != "EXECUTED":
        raise ApiError("ERR_INVALID_ELECTION_STATE")
    if asset["disposition_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_ELECTION_STATE")
    election["status"] = "REVERSED"
    election["reversal_reason"] = (
        body.get("reversal_reason") if "reversal_reason" in body else reason)
    election["executed_at"] = None
    if election["election"] == "TRANSFER":
        designation = DB.designations.get(election["beneficiary_designation_id"])
        amount = election["distributed_value_cents"]
        if designation is not None:
            designation["received_value_cents"] -= amount
            bump(designation)
        estate["undistributed_value_cents"] += amount
        bump(estate)
        election["distributed_value_cents"] = 0
    bump(election)
    asset["disposition_status"] = "PENDING"
    asset["disposed_at"] = None
    bump(asset)
    estate_svc.recompute(estate)
    return single(public(election), 200)
