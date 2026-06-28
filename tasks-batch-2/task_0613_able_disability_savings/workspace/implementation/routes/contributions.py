"""Contribution routes: post (OCC + headroom) and reverse."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from middleware import get_identity, require_role
from response import ok, created, ok_list
from errors import err
from services import domain
from clock import clock
from routes.common import (
    get_body, find_or_404, require_enum, require_positive_amount, paginate,
    check_account_owner, check_occ,
)

bp = Blueprint("contributions", __name__)

ALL_ROLES = {"ProgramAdministrator", "Beneficiary", "AuthorizedRepresentative"}
CONTRIB_TYPES = {"REGULAR", "ABLE_TO_WORK", "ROLLOVER_529"}


@bp.post("/able/accounts/<aid>/contributions")
def post_contribution(aid):
    user_id, role = get_identity()
    require_role(role, ALL_ROLES)
    a = find_or_404(db.accounts, aid, "Account")
    # ownership (priority 4)
    check_account_owner(a, role, user_id)
    body = get_body()
    # body well-formedness (priority 5: ERR_INVALID_REQUEST)
    ctype = require_enum(body, "contribution_type", CONTRIB_TYPES)
    amount = require_positive_amount(body, "amount_cents")
    if ctype == "ROLLOVER_529":
        sp = body.get("source_529_plan")
        if not isinstance(sp, str) or sp == "":
            raise err("ERR_INVALID_REQUEST", "source_529_plan required for ROLLOVER_529")
    if "expected_account_version" not in body or body["expected_account_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_account_version is required")
    # OCC (priority 7)
    check_occ(body, a)
    # account-open (priority 8)
    if a["status"] != "OPEN":
        raise err("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN")
    # business rules (headroom) — order pinned per §3.6
    b = db.beneficiaries[a["beneficiary_id"]]
    program = db.programs[b["program_id"]]
    if ctype in ("REGULAR", "ROLLOVER_529"):
        used = domain.regular_ytd(aid)
        room = program["annual_contribution_cap_cents"] - used
        if amount > room:
            raise err("ERR_ANNUAL_CAP_EXCEEDED", "Annual contribution cap exceeded")
        if ctype == "ROLLOVER_529":
            if amount > program["annual_contribution_cap_cents"]:
                raise err("ERR_ROLLOVER_LIMIT_EXCEEDED",
                          "Single rollover exceeds the annual contribution cap")
    elif ctype == "ABLE_TO_WORK":
        if b["employer_retirement_plan_participant"]:
            raise err("ERR_ATW_INELIGIBLE",
                      "ABLE-to-Work contribution by employer retirement plan participant")
        atw_cap = min(program["able_to_work_fpl_cents"],
                      b["gross_employment_income_ytd_cents"])
        room = atw_cap - domain.atw_ytd(aid)
        if amount > room:
            raise err("ERR_ATW_CAP_EXCEEDED", "ABLE-to-Work contribution cap exceeded")

    c = {
        "account_id": aid,
        "contribution_type": ctype,
        "amount_cents": amount,
        "source_529_plan": body.get("source_529_plan") if ctype == "ROLLOVER_529" else None,
        "contribution_date": clock.iso()[:10],
        "status": "POSTED",
    }
    stamp_new(c)
    db.contributions[c["id"]] = c
    # ledger effects (single account mutation -> version +1)
    a["basis_cents"] += amount
    a["balance_cents"] += amount
    domain.recompute_ssi_posture(a)
    touch(a)
    return created(domain.serialize_contribution(c))


@bp.get("/able/contributions/<cid>")
def get_contribution(cid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    c = find_or_404(db.contributions, cid, "Contribution")
    return ok(domain.serialize_contribution(c))


@bp.get("/able/contributions")
def list_contributions():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    account_id = request.args.get("account_id")
    items = list(db.contributions.values())
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_contribution(c) for c in page],
                   limit, offset, total)


@bp.post("/able/contributions/<cid>/reverse")
def reverse_contribution(cid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    c = find_or_404(db.contributions, cid, "Contribution")
    # state (priority 6)
    if c["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Contribution is not POSTED")
    a = db.accounts[c["account_id"]]
    # account-open (priority 8)
    if a["status"] != "OPEN":
        raise err("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN")
    c["status"] = "REVERSED"
    touch(c)
    a["basis_cents"] -= c["amount_cents"]
    a["balance_cents"] -= c["amount_cents"]
    domain.recompute_ssi_posture(a)
    touch(a)
    return ok(domain.serialize_contribution(c))
