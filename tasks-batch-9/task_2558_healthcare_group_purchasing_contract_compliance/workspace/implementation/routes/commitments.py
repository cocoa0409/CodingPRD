"""Commitments, letters of participation and the leakage report.

PRD sections 3.4 and 3.7 (report).
"""

from decimal import Decimal

from flask import Blueprint

from db import db, ordered
from enums import ELECTION_STATUSES, LOP_STATUSES
from errors import ApiError
from middleware import (
    ALL_ROLES,
    COMPLIANCE_ANALYST,
    CONTRACT_MANAGER,
    MEMBER_MATERIALS_MANAGER,
    authenticate,
    require_member_scope,
)
from response import list_response, object_response
from services.calc import build_leakage_report, closed_contains_date, find_tier
from services.cascade import recompute_active_commitment_count, supersede_on_termination
from services.lookup import get_commitment, resolve_body_fks
from validation import (
    bad,
    body_json,
    field_date,
    field_int,
    field_string,
    paginate,
    pagination,
    query_date,
    query_enum,
    query_string,
)

commitments_bp = Blueprint("commitments", __name__)

LIVE_ELECTION_STATUSES = ("ELECTED", "ACTIVE", "REQUAL_REVIEW")


@commitments_bp.route("/gpo/commitments", methods=["POST"])
def create_commitment():
    acting_user_id, _ = authenticate((MEMBER_MATERIALS_MANAGER,))
    body = body_json()
    declared_member_id = body.get("member_id")
    if isinstance(declared_member_id, str) and declared_member_id:
        require_member_scope(acting_user_id, declared_member_id)

    resolved = resolve_body_fks(body, ("contract_id", "member_id"))
    contract = resolved["contract_id"]
    member = resolved["member_id"]
    if contract is None:
        raise bad("Field 'contract_id' is required.")
    if member is None:
        raise bad("Field 'member_id' is required.")

    elected_tier_code = field_string(body, "elected_tier_code", 1, 40)
    committed_volume_units = field_int(body, "committed_volume_units")
    effective_from = field_date(body, "effective_from")

    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", "A suspended member cannot elect a commitment.")
    if contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", "Commitments can only be elected on an ACTIVE contract."
        )
    for existing in db.commitments.values():
        if (
            existing["member_id"] == member["id"]
            and existing["contract_id"] == contract["id"]
            and existing["election_status"] in LIVE_ELECTION_STATUSES
        ):
            raise ApiError(
                "ERR_DUPLICATE_COMMITMENT",
                "This member already holds a live commitment on this contract.",
            )
    tier = find_tier(contract, elected_tier_code)
    if tier is None:
        raise ApiError(
            "ERR_TIER_CODE_UNKNOWN", "elected_tier_code names no entry of the tier ladder."
        )
    if not closed_contains_date(
        effective_from, contract["effective_from"], contract["effective_to"]
    ):
        raise ApiError(
            "ERR_PERIOD_OUTSIDE_CONTRACT_TERM",
            "effective_from must sit inside the contract term.",
        )
    if (
        committed_volume_units <= 0
        or committed_volume_units < tier["min_committed_volume_units"]
    ):
        raise ApiError(
            "ERR_COMMITTED_VOLUME_BELOW_TIER",
            "committed_volume_units must clear the elected tier's volume floor.",
        )

    row = db.new_row()
    row.update(
        {
            "member_id": member["id"],
            "contract_id": contract["id"],
            "elected_tier_code": elected_tier_code,
            "committed_volume_units": committed_volume_units,
            "effective_from": effective_from,
            "election_status": "ELECTED",
            "lop_status": "NOT_ISSUED",
            "signer_name": None,
            "current_tier_code": None,
            "requalification_round": 0,
            "last_final_compliance_pct": None,
            "ytd_on_contract_spend_cents": 0,
            "ytd_total_category_spend_cents": 0,
            "ytd_measured_volume_units": 0,
            "ytd_leakage_pct": Decimal("0.00"),
            "leakage_flag": False,
        }
    )
    db.commitments[row["id"]] = row
    recompute_active_commitment_count(contract)
    return object_response(row, 201)


@commitments_bp.route("/gpo/commitments/<commitment_id>", methods=["GET"])
def read_commitment(commitment_id):
    authenticate(ALL_ROLES)
    return object_response(get_commitment(commitment_id))


@commitments_bp.route("/gpo/commitments", methods=["GET"])
def list_commitments():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    member_id = query_string("member_id")
    contract_id = query_string("contract_id")
    election_status = query_enum("election_status", ELECTION_STATUSES)
    lop_status = query_enum("lop_status", LOP_STATUSES)
    rows = [
        row
        for row in ordered(db.commitments.values())
        if (member_id is None or row["member_id"] == member_id)
        and (contract_id is None or row["contract_id"] == contract_id)
        and (election_status is None or row["election_status"] == election_status)
        and (lop_status is None or row["lop_status"] == lop_status)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# -- letter of participation -------------------------------------------------


@commitments_bp.route("/gpo/commitments/<commitment_id>/lop/issue", methods=["POST"])
def issue_lop(commitment_id):
    authenticate((CONTRACT_MANAGER,))
    commitment = get_commitment(commitment_id)
    if commitment["lop_status"] not in ("NOT_ISSUED", "VOID"):
        raise ApiError(
            "ERR_INVALID_LOP_STATE", "A letter can only be issued from NOT_ISSUED or VOID."
        )
    if commitment["election_status"] != "ELECTED":
        raise ApiError(
            "ERR_COMMITMENT_NOT_ELECTED",
            "A letter can only be issued while the election is ELECTED.",
        )
    commitment["lop_status"] = "ISSUED"
    commitment["signer_name"] = None
    db.touch(commitment)
    return object_response(commitment)


@commitments_bp.route("/gpo/commitments/<commitment_id>/lop/sign", methods=["POST"])
def sign_lop(commitment_id):
    acting_user_id, _ = authenticate((MEMBER_MATERIALS_MANAGER,))
    commitment = get_commitment(commitment_id)
    require_member_scope(acting_user_id, commitment["member_id"])
    body = body_json()
    signer_name = field_string(body, "signer_name", 1, 120)
    if commitment["lop_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_LOP_STATE", "Only an ISSUED letter can be signed.")
    commitment["lop_status"] = "SIGNED"
    commitment["signer_name"] = signer_name
    db.touch(commitment)
    return object_response(commitment)


@commitments_bp.route("/gpo/commitments/<commitment_id>/lop/countersign", methods=["POST"])
def countersign_lop(commitment_id):
    authenticate((CONTRACT_MANAGER,))
    commitment = get_commitment(commitment_id)
    if commitment["lop_status"] != "SIGNED":
        raise ApiError("ERR_INVALID_LOP_STATE", "Only a SIGNED letter can be countersigned.")
    if commitment["election_status"] != "ELECTED":
        raise ApiError(
            "ERR_COMMITMENT_NOT_ELECTED",
            "Only an ELECTED commitment can be brought into force.",
        )
    contract = db.contracts.get(commitment["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", "The contract must still be ACTIVE to countersign."
        )
    commitment["lop_status"] = "COUNTERSIGNED"
    commitment["election_status"] = "ACTIVE"
    commitment["current_tier_code"] = commitment["elected_tier_code"]
    db.touch(commitment)
    recompute_active_commitment_count(contract)
    return object_response(commitment)


@commitments_bp.route("/gpo/commitments/<commitment_id>/lop/void", methods=["POST"])
def void_lop(commitment_id):
    authenticate((CONTRACT_MANAGER,))
    commitment = get_commitment(commitment_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    if commitment["lop_status"] not in ("ISSUED", "SIGNED"):
        raise ApiError(
            "ERR_INVALID_LOP_STATE", "Only an ISSUED or SIGNED letter can be voided."
        )
    commitment["lop_status"] = "VOID"
    commitment["signer_name"] = None
    db.touch(commitment)
    return object_response(commitment)


# -- requalification and termination -----------------------------------------


@commitments_bp.route(
    "/gpo/commitments/<commitment_id>/open-requalification", methods=["POST"]
)
def open_requalification(commitment_id):
    authenticate((COMPLIANCE_ANALYST,))
    commitment = get_commitment(commitment_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    if commitment["election_status"] != "ACTIVE":
        raise ApiError(
            "ERR_COMMITMENT_NOT_ACTIVE",
            "Only an ACTIVE commitment can enter requalification review.",
        )
    if commitment["lop_status"] != "COUNTERSIGNED":
        raise ApiError(
            "ERR_INVALID_LOP_STATE",
            "Requalification requires a COUNTERSIGNED letter of participation.",
        )
    commitment["election_status"] = "REQUAL_REVIEW"
    db.touch(commitment)
    return object_response(commitment)


@commitments_bp.route("/gpo/commitments/<commitment_id>/terminate", methods=["POST"])
def terminate_commitment(commitment_id):
    authenticate((COMPLIANCE_ANALYST,))
    commitment = get_commitment(commitment_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    previous_status = commitment["election_status"]
    if previous_status not in LIVE_ELECTION_STATUSES:
        raise ApiError(
            "ERR_COMMITMENT_NOT_ACTIVE", "This commitment is already TERMINATED."
        )
    commitment["election_status"] = "TERMINATED"
    db.touch(commitment)
    if previous_status in ("ACTIVE", "REQUAL_REVIEW"):
        supersede_on_termination(commitment)
        contract = db.contracts.get(commitment["contract_id"])
        if contract is not None:
            recompute_active_commitment_count(contract)
    return object_response(commitment)


# -- leakage report ----------------------------------------------------------


@commitments_bp.route("/gpo/commitments/<commitment_id>/leakage-report", methods=["GET"])
def leakage_report(commitment_id):
    acting_user_id, role = authenticate(
        (COMPLIANCE_ANALYST, CONTRACT_MANAGER, MEMBER_MATERIALS_MANAGER)
    )
    commitment = get_commitment(commitment_id)
    if role == MEMBER_MATERIALS_MANAGER:
        require_member_scope(acting_user_id, commitment["member_id"])
    from_date = query_date("from_date")
    to_date = query_date("to_date")
    if to_date <= from_date:
        raise ApiError(
            "ERR_EFFECTIVE_WINDOW_INVALID", "to_date must be strictly after from_date."
        )
    return object_response(build_leakage_report(commitment, from_date, to_date))
