from flask import Blueprint

import calc
import find
import serialize
import validators as v
from auth import endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import db, new_record, sorted_records, touch

bp = Blueprint("plans", __name__)

READ_ROLES = ["CorpsDirector", "BusinessManager", "Member"]
LIST_ROLES = ["CorpsDirector", "BusinessManager"]


@bp.route("/payment-plans", methods=["POST"])
@endpoint(["BusinessManager"])
def create_plan():
    body = v.get_body()
    member_id = v.req_str(body, "member_id")
    contract_id = v.req_str(body, "member_contract_id")
    due_raw, first_due = v.req_date(body, "first_due_date")
    expected_version = v.req_int(body, "expected_member_version")
    # Rung 8 -- member then contract, in declaration order.
    member = find.member(member_id)
    contract = find.contract(contract_id)
    # Rung 10 -- stale-view protection on the parent member.
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION",
                       "expected_member_version does not match the member's current version.")
    # Rung 14 -- the contract must be EXECUTED.
    if contract["status"] != "EXECUTED":
        raise ApiError("ERR_CONTRACT_NOT_EXECUTED",
                       "The referenced contract is not EXECUTED.")
    # Rung 27 -- the plan's member must be the contract's member.
    if contract["member_id"] != member_id:
        raise ApiError("ERR_CONTRACT_MEMBER_MISMATCH",
                       "The contract names a different member.")

    plan_type = contract["payment_plan_type"]
    schedule = calc.installment_schedule(contract["tuition_amount_cents"], plan_type)

    # A second plan for the same member legitimately supersedes the prior one.
    for prior in sorted_records(db.plans):
        if prior["member_id"] == member_id and prior["status"] in ("ACTIVE", "DELINQUENT"):
            prior["status"] = "SUPERSEDED"
            touch(prior)

    record = new_record()
    record.update({
        "member_id": member_id,
        "member_contract_id": contract_id,
        "plan_type": plan_type,
        "first_due_date": due_raw,
        "_first_due_date": first_due,
        "installment_count": schedule["installment_count"],
        "principal_cents": contract["tuition_amount_cents"],
        "surcharge_cents": schedule["surcharge_cents"],
        "financed_total_cents": schedule["financed_total_cents"],
        "installment_base_cents": schedule["installment_base_cents"],
        "installment_remainder_cents": schedule["installment_remainder_cents"],
        "late_fee_accrued_cents": 0,
        "delinquency_strikes": 0,
        "status": "ACTIVE",
    })
    db.plans[record["id"]] = record
    # Plan creation advances the financed member's version by one.
    touch(member)
    return object_response(serialize.plan(record), 201)


@bp.route("/payment-plans/<payment_plan_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_plan(payment_plan_id):
    return object_response(serialize.plan(find.plan(payment_plan_id)))


@bp.route("/payment-plans", methods=["GET"])
@endpoint(LIST_ROLES)
def list_plans():
    member_id = v.arg_str("member_id")
    contract_id = v.arg_str("member_contract_id")
    status = v.arg_str("status")
    records = []
    for record in sorted_records(db.plans):
        if member_id is not None and record["member_id"] != member_id:
            continue
        if contract_id is not None and record["member_contract_id"] != contract_id:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return paginate(records, serialize.plan)
