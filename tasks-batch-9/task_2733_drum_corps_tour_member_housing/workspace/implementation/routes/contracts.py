from flask import Blueprint

import find
import serialize
import validators as v
from auth import acting_user_id, endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import clock_iso, db, new_record, sorted_records, touch

bp = Blueprint("contracts", __name__)

PLAN_TYPES = ("STANDARD_3", "EXTENDED_6")
READ_ROLES = ["CorpsDirector", "MembershipCoordinator", "BusinessManager", "Member"]
LIST_ROLES = ["CorpsDirector", "MembershipCoordinator", "BusinessManager"]
MAX_REVISION_ROUNDS = 3


def _owner_check(contract):
    """Rung 9 -- entity-backed ownership on X-User-ID."""
    if acting_user_id() != contract["member_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This contract belongs to another member.")


@bp.route("/member-contracts", methods=["POST"])
@endpoint(["MembershipCoordinator"])
def create_contract():
    body = v.get_body()
    member_id = v.req_str(body, "member_id")
    amount = v.req_int(body, "tuition_amount_cents")
    plan_type = v.req_enum(body, "payment_plan_type", PLAN_TYPES)
    # Rung 6 -- positivity floors sit ahead of existence.
    v.positive(amount > 0, "tuition_amount_cents must be greater than 0.")
    member = find.member(member_id)
    # Rung 48 -- at most one contract whose status is not VOIDED.
    for other in db.contracts.values():
        if other["member_id"] == member_id and other["status"] != "VOIDED":
            raise ApiError("ERR_CONTRACT_ALREADY_EXISTS",
                           "This member already holds a live contract.")

    record = new_record()
    record.update({
        "member_id": member_id,
        "tuition_amount_cents": amount,
        "payment_plan_type": plan_type,
        "status": "ISSUED",
        "revision_round": 0,
        "revision_note": None,
        "signature_name": None,
        "signed_at": None,
        "executed_at": None,
    })
    db.contracts[record["id"]] = record
    return object_response(serialize.contract(record), 201)


@bp.route("/member-contracts/<member_contract_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_contract(member_contract_id):
    return object_response(serialize.contract(find.contract(member_contract_id)))


@bp.route("/member-contracts", methods=["GET"])
@endpoint(LIST_ROLES)
def list_contracts():
    member_id = v.arg_str("member_id")
    status = v.arg_str("status")
    records = []
    for record in sorted_records(db.contracts):
        if member_id is not None and record["member_id"] != member_id:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return paginate(records, serialize.contract)


@bp.route("/member-contracts/<member_contract_id>/request-revision", methods=["POST"])
@endpoint(["Member"])
def request_revision(member_contract_id):
    body = v.get_body()
    note = v.req_str(body, "revision_note")
    contract = find.contract(member_contract_id)
    _owner_check(contract)
    if contract["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "Only an ISSUED contract may be sent back for revision.")
    contract["status"] = "REVISION_REQUESTED"
    contract["revision_note"] = note
    touch(contract)
    return object_response(serialize.contract(contract))


@bp.route("/member-contracts/<member_contract_id>/reissue", methods=["POST"])
@endpoint(["MembershipCoordinator"])
def reissue_contract(member_contract_id):
    body = v.get_body()
    amount = v.opt_int(body, "tuition_amount_cents")
    plan_type = v.opt_enum(body, "payment_plan_type", PLAN_TYPES)
    contract = find.contract(member_contract_id)
    if contract["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "Only a REVISION_REQUESTED contract may be reissued.")
    # Rung 50 -- the cap is enforced on the reissue, not on the request.
    if contract["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError("ERR_MAX_REVISION_ROUNDS_EXCEEDED",
                       "This contract has exhausted its revision rounds.")
    if amount is not None:
        contract["tuition_amount_cents"] = amount
    if plan_type is not None:
        contract["payment_plan_type"] = plan_type
    contract["status"] = "ISSUED"
    contract["revision_round"] = contract["revision_round"] + 1
    touch(contract)
    return object_response(serialize.contract(contract))


@bp.route("/member-contracts/<member_contract_id>/sign", methods=["POST"])
@endpoint(["Member"])
def sign_contract(member_contract_id):
    body = v.get_body()
    signature_name = v.req_str(body, "signature_name")
    contract = find.contract(member_contract_id)
    _owner_check(contract)
    if contract["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "Only an ISSUED contract may be signed.")
    contract["status"] = "SIGNED_BY_MEMBER"
    contract["signature_name"] = signature_name
    contract["signed_at"] = clock_iso()
    touch(contract)
    return object_response(serialize.contract(contract))


@bp.route("/member-contracts/<member_contract_id>/execute", methods=["POST"])
@endpoint(["CorpsDirector"])
def execute_contract(member_contract_id):
    contract = find.contract(member_contract_id)
    # Rung 13 -- contract state.
    if contract["status"] != "SIGNED_BY_MEMBER":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "Only a SIGNED_BY_MEMBER contract may be executed.")
    member = db.members.get(contract["member_id"])
    # Rung 30 -- member safety outranks the membership-standing check.
    if member is not None and member["medical_status"] != "CLEARED":
        raise ApiError("ERR_MEDICAL_NOT_CLEARED",
                       "The member's medical status is not CLEARED.")
    if member is not None and member["membership_status"] != "OFFERED":
        raise ApiError("ERR_INVALID_MEMBER_STATE",
                       "Only an OFFERED member may be executed onto the roster.")

    contract["status"] = "EXECUTED"
    contract["executed_at"] = clock_iso()
    touch(contract)
    if member is not None:
        member["membership_status"] = "CONTRACTED"
        member["tuition_charged_cents"] = contract["tuition_amount_cents"]
        touch(member)
    return object_response(serialize.contract(contract))
