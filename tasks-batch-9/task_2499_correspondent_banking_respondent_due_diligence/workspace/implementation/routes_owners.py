"""Beneficial ownership and the four-level look-through (PRD 3.3)."""

from flask import Blueprint

import calc
import cascade
import store
from common import (ALL, arg, eq, list_scope, need, need_respondent, paged,
                    scoped_child, start, PREFIX)
from errors import fail
from response import ok, ok_list
from validate import body, fbool, fenum, fnum, fstr, q2, validate

bp = Blueprint("owners", __name__)

OWNER_TYPES = ("NATURAL_PERSON", "LEGAL_ENTITY", "STATE")
REJECTIONS = ("DOCUMENT_MISSING", "IDENTITY_MISMATCH", "SANCTIONS_HIT",
              "REFUSED_DISCLOSURE")

CREATE_SPEC = [
    fstr("owner_name", True, 1, 160),
    fenum("owner_type", OWNER_TYPES, True),
    fnum("ownership_pct", True, None, "100.00", "0.00"),
    fstr("country_of_residence", True, 1, None),
    fstr("parent_owner_id", False, 1, None),
    fbool("is_pep", False),
]


@bp.post(PREFIX + "/respondents/<respondent_id>/beneficial-owners")
def declare_owner(respondent_id):
    start(("ComplianceAnalyst", "RespondentContact"), respondent_id)
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, CREATE_SPEC)
    cascade.guard_not_closed(resp)
    if store.jurisdiction_by_code(data["country_of_residence"]) is None:
        fail("ERR_JURISDICTION_PROFILE_NOT_FOUND",
             "country_of_residence %s does not resolve." % data["country_of_residence"])
    parent = None
    parent_id = data.get("parent_owner_id")
    if parent_id is not None:
        parent = store.get("owners", parent_id)
        if parent is None:
            fail("ERR_BENEFICIAL_OWNER_NOT_FOUND", "parent_owner_id does not resolve.")
        if parent["respondent_bank_id"] != resp["id"]:
            fail("ERR_CROSS_RESPONDENT_REFERENCE",
                 "The parent owner belongs to another respondent.")
        chain = calc.owner_chain(parent)
        seen = set()
        for node in chain:
            if node["id"] in seen:
                fail("ERR_OWNERSHIP_CYCLE_DETECTED",
                     "The ownership chain of the parent already contains a cycle.")
            seen.add(node["id"])
        depth = int(parent["chain_depth"]) + 1
        if depth > 4:
            fail("ERR_OWNERSHIP_DEPTH_EXCEEDED",
                 "The ownership chain may not exceed four levels.")
    else:
        depth = 1
    pct = q2(data["ownership_pct"])
    siblings = [o for o in store.owners_of(resp["id"])
                if o.get("parent_owner_id") == parent_id]
    total = pct
    for sibling in siblings:
        total = total + sibling["ownership_pct"]
    if total > q2("100.00"):
        fail("ERR_OWNERSHIP_PCT_EXCEEDS_100",
             "Sibling ownership percentages may not exceed 100.00.")
    row = store.insert("owners", {
        "respondent_bank_id": resp["id"],
        "parent_owner_id": parent_id,
        "owner_name": data["owner_name"],
        "owner_type": data["owner_type"],
        "ownership_pct": pct,
        "country_of_residence": data["country_of_residence"],
        "is_pep": bool(data.get("is_pep", False)),
        "chain_depth": depth,
        "effective_ownership_pct": q2("0.00"),
        "verification_status": "PENDING",
        "verified_by_user_id": None,
        "rejection_reason": None,
    })
    row["effective_ownership_pct"] = calc.effective_ownership_pct(row)
    return ok(row, 201)


@bp.get(PREFIX + "/beneficial-owners")
def list_owners():
    ctx = start(ALL)
    scope_id = list_scope(ctx)
    rows = store.by_seq(store.all_rows("owners"))
    rows = eq(rows, "respondent_bank_id", scope_id)
    rows = eq(rows, "parent_owner_id", arg("parent_owner_id"))
    rows = eq(rows, "verification_status", arg("verification_status"))
    rows = eq(rows, "owner_type", arg("owner_type"))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/beneficial-owners/<owner_id>")
def read_owner(owner_id):
    ctx = start(ALL)
    return ok(scoped_child("owners", owner_id, ctx))


@bp.post(PREFIX + "/beneficial-owners/<owner_id>/verification")
def verification(owner_id):
    ctx = start(("ComplianceAnalyst",))
    owner = need("owners", owner_id)
    data = body()
    validate(data, [
        fenum("action", ("VERIFY", "REJECT", "RESET"), True),
        fenum("rejection_reason", REJECTIONS, False),
    ])
    resp = store.get("respondents", owner["respondent_bank_id"])
    action = data["action"]
    if action == "VERIFY":
        if resp["dd_state"] in ("DECLINED", "TERMINATED"):
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "A declined or terminated respondent accepts no verification.")
    cascade.guard_not_closed(resp)
    if action == "VERIFY":
        if owner["verification_status"] != "PENDING":
            fail("ERR_INVALID_OWNER_STATE", "Only a pending owner may be verified.")
        if owner.get("parent_owner_id"):
            parent = store.get("owners", owner["parent_owner_id"])
            if parent is None or parent["verification_status"] != "VERIFIED":
                fail("ERR_INVALID_OWNER_STATE",
                     "The parent owner must be verified first.")
        country = store.jurisdiction_by_code(owner["country_of_residence"])
        if country is not None and country["sanctions_status"] == "COMPREHENSIVELY_SANCTIONED":
            fail("ERR_INVALID_OWNER_STATE",
                 "An owner resident in a comprehensively sanctioned jurisdiction "
                 "cannot be verified.")
        owner["verification_status"] = "VERIFIED"
        owner["verified_by_user_id"] = ctx.user_id
        owner["rejection_reason"] = None
        owner["effective_ownership_pct"] = calc.effective_ownership_pct(owner)
        store.touch(owner)
    elif action == "REJECT":
        if owner["verification_status"] != "PENDING":
            fail("ERR_INVALID_OWNER_STATE", "Only a pending owner may be rejected.")
        if data.get("rejection_reason") is None:
            fail("ERR_INVALID_REQUEST_BODY", "rejection_reason is required to reject.")
        owner["verification_status"] = "REJECTED"
        owner["rejection_reason"] = data["rejection_reason"]
        owner["verified_by_user_id"] = ctx.user_id
        store.touch(owner)
        _revert_descendants(owner)
    else:
        if owner["verification_status"] != "REJECTED":
            fail("ERR_INVALID_OWNER_STATE", "Only a rejected owner may be reset.")
        if owner["rejection_reason"] == "SANCTIONS_HIT":
            fail("ERR_INVALID_OWNER_STATE", "A sanctions hit is never reset.")
        owner["verification_status"] = "PENDING"
        owner["rejection_reason"] = None
        owner["verified_by_user_id"] = None
        store.touch(owner)
    calc.ownership_rollup(resp)
    store.touch(resp)
    return ok(owner)


def _revert_descendants(owner):
    rows = store.owners_of(owner["respondent_bank_id"])
    frontier = {owner["id"]}
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row.get("parent_owner_id") in frontier and row["id"] not in frontier:
                frontier.add(row["id"])
                changed = True
    for row in store.by_seq([r for r in rows if r["id"] in frontier and r["id"] != owner["id"]]):
        if row["verification_status"] == "VERIFIED":
            row["verification_status"] = "PENDING"
            row["verified_by_user_id"] = None
            store.touch(row)
