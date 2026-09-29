"""Members, IP commitments, tool access and programme credit (PRD 3.2)."""

from flask import Blueprint

import calc
import cascade
import common as C
import enums as E
import middleware as M
import shape as S
from db import new_row, now, ordered, set_fields, store
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("members", __name__)


@bp.post("/members")
def create_member():
    M.auth([M.PROGRAM_ADMIN])
    body = S.body_obj()
    legal_name = S.req_str(body, "legal_name", 1, 120)
    contact_email = S.req_str(body, "contact_email", 1, 254)
    tier = S.req_str(body, "tier")
    S.check_enum(tier, E.TIERS, "tier")
    for row in store.members.values():
        if row["legal_name"] == legal_name:
            raise ApiError("ERR_DUPLICATE_NAME", "legal_name already exists")

    member = new_row(
        legal_name=legal_name,
        contact_email=contact_email,
        tier=tier,
        onboarding_state="REGISTERED",
        ip_commitment_type=None,
        essential_patent_count=0,
        ip_scope_specification_id=None,
        ip_executed_at=None,
        ip_withdrawn_at=None,
        credits_purchased_cents=0,
        credits_consumed_cents=0,
        credit_balance_cents=0,
        escrowed_credit_cents=0,
        good_standing=False,
        open_case_count=0,
    )
    store.members[member["id"]] = member
    return object_response(public(member), 201)


@bp.get("/members/<member_id>")
def get_member(member_id):
    M.auth(M.NON_PUBLIC_READ)
    return object_response(public(C.must("member", member_id)), 200)


@bp.get("/members")
def list_members():
    M.auth([M.PROGRAM_ADMIN, M.COMPLIANCE_OFFICER])
    limit, offset = S.paging()
    tier = S.q_enum("tier", E.TIERS)
    onboarding_state = S.q_str("onboarding_state")
    scope = S.q_str("ip_scope_specification_id")
    rows = ordered(store.members.values())
    if tier is not None:
        rows = [r for r in rows if r["tier"] == tier]
    if onboarding_state is not None:
        rows = [r for r in rows if r["onboarding_state"] == onboarding_state]
    if scope is not None:
        rows = [r for r in rows if r["ip_scope_specification_id"] == scope]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/members/<member_id>/ip-commitment")
def execute_ip_commitment(member_id):
    user_id, _ = M.auth([M.MEMBER])
    M.own(user_id, member_id)
    member = C.must("member", member_id)
    body = S.body_obj()
    # rung 5
    spec = C.body_fk("specification", body, "scope_specification_id")
    # rung 6
    commitment_type = S.req_str(body, "ip_commitment_type")
    patent_count = S.req_int(body, "essential_patent_count", 0, None)
    S.req_str(body, "scope_specification_id")
    # rung 7
    S.check_enum(commitment_type, E.IP_COMMITMENT_TYPES, "ip_commitment_type")
    # rung 13
    if spec["status"] not in ("RATIFIED", "DEPRECATED"):
        raise ApiError("ERR_INVALID_SPECIFICATION_STATE",
                       "an IP commitment requires a RATIFIED or DEPRECATED version")
    # rung 14
    if member["onboarding_state"] != "REGISTERED":
        raise ApiError("ERR_INVALID_MEMBER_STATE",
                       "an IP commitment may only be executed from REGISTERED")

    set_fields(
        member,
        ip_commitment_type=commitment_type,
        essential_patent_count=patent_count,
        ip_scope_specification_id=spec["id"],
        ip_executed_at=now(),
        onboarding_state="IP_EXECUTED",
    )
    cascade.recompute_member(member)
    return object_response(public(member), 200)


@bp.post("/members/<member_id>/ip-commitment/withdraw")
def withdraw_ip_commitment(member_id):
    user_id, _ = M.auth([M.MEMBER])
    M.own(user_id, member_id)
    member = C.must("member", member_id)
    if member["onboarding_state"] not in ("IP_EXECUTED", "TOOLS_GRANTED", "TOOLS_REVOKED"):
        raise ApiError("ERR_INVALID_MEMBER_STATE",
                       "withdrawal is only available from IP_EXECUTED, TOOLS_GRANTED or TOOLS_REVOKED")
    set_fields(member, ip_withdrawn_at=now(), onboarding_state="IP_WITHDRAWN")
    cascade.ip_withdrawal_cascade(member)
    return object_response(public(member), 200)


@bp.post("/members/<member_id>/tool-access")
def tool_access(member_id):
    M.auth([M.PROGRAM_ADMIN])
    member = C.must("member", member_id)
    body = S.body_obj()
    decision = S.req_str(body, "decision")
    S.check_enum(decision, E.TOOL_ACCESS_DECISIONS, "decision")
    state = member["onboarding_state"]
    if decision == "GRANT":
        if state not in ("IP_EXECUTED", "TOOLS_REVOKED"):
            raise ApiError("ERR_INVALID_MEMBER_STATE",
                           "a grant requires IP_EXECUTED or TOOLS_REVOKED")
        set_fields(member, onboarding_state="TOOLS_GRANTED")
    else:
        if state != "TOOLS_GRANTED":
            raise ApiError("ERR_INVALID_MEMBER_STATE", "a revocation requires TOOLS_GRANTED")
        set_fields(member, onboarding_state="TOOLS_REVOKED")
    cascade.recompute_member(member)
    return object_response(public(member), 200)


@bp.post("/members/<member_id>/credits")
def purchase_credits(member_id):
    user_id, role = M.auth([M.PROGRAM_ADMIN, M.MEMBER])
    if role == M.MEMBER:
        M.own(user_id, member_id)
    member = C.must("member", member_id)
    body = S.body_obj()
    # rung 6 -- type only; the range is its own rung
    value = body.get("amount_cents")
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        S.bad("amount_cents must be an integer")
    # rung 10
    if value < 1000 or value > 100000000:
        raise ApiError("ERR_CREDIT_AMOUNT_OUT_OF_RANGE",
                       "amount_cents must be between 1000 and 100000000")
    set_fields(member, credits_purchased_cents=member["credits_purchased_cents"] + value)
    cascade.recompute_member(member)
    return object_response(public(member), 200)


@bp.get("/members/<member_id>/credit-ledger")
def credit_ledger(member_id):
    M.auth([M.PROGRAM_ADMIN, M.MEMBER, M.COMPLIANCE_OFFICER])
    member = C.must("member", member_id)
    variant = S.q_enum("variant", E.CREDIT_LEDGER_VARIANTS) or "AVAILABLE"
    return object_response(calc.credit_ledger(member, variant), 200)
