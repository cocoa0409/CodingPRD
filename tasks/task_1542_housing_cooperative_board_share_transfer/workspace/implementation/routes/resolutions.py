"""Board resolutions and votes (PRD §3.2)."""
from flask import request

import domain as D
from db import STORE
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_CROSS_ENTITY_VIOLATION,
    ERR_RESOLUTION_ALREADY_VOTED,
    ERR_SEPARATION_OF_DUTIES,
    ERR_VOTER_ALREADY_CAST,
)
from middleware import ctx, require_role
from response import ok
from util import get_body, req_str, req_enum, opt_str, opt_object
from routes.core import bp, list_response

READ_BOARD = ["PlatformAdmin", "BoardOfficer", "BoardMember", "ManagingAgent"]

RESOLUTION_KINDS = [
    "APPROVE_PURCHASE", "REJECT_PURCHASE", "APPROVE_SCHEDULE", "APPROVE_REFINANCE",
    "APPROVE_SUBLET", "APPROVE_ALTERATION", "ISSUE_ARREARS_ACTION", "SET_POLICY",
]
SUBJECT_KINDS = [
    "PurchaseApplication", "ChargeSchedule", "SubletAgreement",
    "AlterationAgreement", "Shareholder", "Cooperative",
]


@bp.post("/cooperatives/<cid>/resolutions")
def create_resolution(cid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    body = get_body()
    kind = req_enum(body, "resolution_kind", RESOLUTION_KINDS)
    subject_kind = req_enum(body, "subject_entity_kind", SUBJECT_KINDS)
    subject_id = req_str(body, "subject_entity_id")
    payload = opt_object(body, "payload_json", {})
    supersedes = opt_str(body, "supersedes_resolution_id", None)
    # Cross-entity: the subject must exist in this cooperative.
    store_key = D.SUBJECT_STORES[subject_kind]
    if subject_kind == "Cooperative":
        if subject_id != cid:
            raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Subject cooperative does not match path", 422)
    else:
        subject = STORE[store_key].get(subject_id)
        if subject is None or subject.get("cooperative_id") != cid:
            raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Subject entity does not exist", 422)
    if supersedes is not None:
        prior = STORE["resolutions"].get(supersedes)
        if prior is None or prior.get("cooperative_id") != cid:
            raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "supersedes_resolution_id does not exist", 422)
    now = coop["current_utc"]
    res = D.make(
        "resolutions", coop,
        cooperative_id=cid,
        resolution_kind=kind,
        subject_entity_kind=subject_kind,
        subject_entity_id=subject_id,
        payload_json=payload,
        votes_required=D.VOTES_REQUIRED,
        votes_for=0,
        votes_against=0,
        votes_abstain=0,
        resolution_status="OPEN",
        supersedes_resolution_id=supersedes,
        opened_at=now,
        closed_at=None,
        _opened_by=uid,
    )
    return ok(D.ser(res), 201)


@bp.get("/cooperatives/<cid>/resolutions")
def list_resolutions(cid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    return list_response("resolutions", cid, [
        ("resolution_kind", request.args.get("resolution_kind"), False),
        ("resolution_status", request.args.get("resolution_status"), False),
        ("subject_entity_id", request.args.get("subject_entity_id"), False),
    ])


@bp.get("/cooperatives/<cid>/resolutions/<rid>")
def get_resolution(cid, rid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    res = D.get_scoped("resolutions", rid, cid, "Resolution")
    return ok(D.ser(res))


@bp.post("/cooperatives/<cid>/resolutions/<rid>/vote")
def cast_vote(cid, rid):
    uid, role = ctx()
    require_role(role, ["BoardMember"])
    coop = D.get_coop(cid)
    res = D.get_scoped("resolutions", rid, cid, "Resolution")
    body = get_body()
    choice = req_enum(body, "vote_choice", ["FOR", "AGAINST", "ABSTAIN"])
    if res["resolution_status"] != "OPEN":
        raise ApiError(ERR_ALREADY_TERMINAL, "Resolution is closed", 409)
    # Segregation: the opener may not also vote on the same resolution.
    if uid == res.get("_opened_by"):
        raise ApiError(
            ERR_SEPARATION_OF_DUTIES,
            "The BoardOfficer who opened a resolution may not vote on it",
            422,
        )
    dup = any(
        v for v in STORE["resolution_votes"].values()
        if v["resolution_id"] == rid and v["voter_user_id"] == uid
    )
    if dup:
        raise ApiError(ERR_VOTER_ALREADY_CAST, "Voter has already cast a vote on this resolution", 409)
    new_for = res["votes_for"] + (1 if choice == "FOR" else 0)
    new_not_for = res["votes_against"] + res["votes_abstain"] + (0 if choice == "FOR" else 1)
    would_pass = new_for >= res["votes_required"]
    would_fail = new_not_for > (D.BOARD_SEATS - res["votes_required"])
    # Atomicity: a deciding vote that would pass a gated resolution is
    # rejected entirely (vote not recorded) when the gate fails.
    if would_pass:
        D.pre_pass_gates(coop, res)
    now = coop["current_utc"]
    vote = D.make(
        "resolution_votes", coop,
        cooperative_id=cid,
        resolution_id=rid,
        voter_user_id=uid,
        vote_choice=choice,
        cast_at=now,
    )
    res["votes_for"] = new_for
    if choice == "AGAINST":
        res["votes_against"] += 1
    elif choice == "ABSTAIN":
        res["votes_abstain"] += 1
    if would_pass:
        res["resolution_status"] = "PASSED"
        res["closed_at"] = now
        D.touch(res, coop)
        D.apply_resolution_passed(coop, res)
    elif would_fail:
        res["resolution_status"] = "FAILED"
        res["closed_at"] = now
        D.touch(res, coop)
        # A failed approval resolution rejects the underlying submission.
        if res["resolution_kind"] == "APPROVE_SUBLET":
            s = STORE["sublet_agreements"].get(res["subject_entity_id"])
            if s is not None and s["sublet_status"] == "SUBMITTED":
                s["sublet_status"] = "REJECTED"
                D.touch(s, coop)
        elif res["resolution_kind"] == "APPROVE_ALTERATION":
            a = STORE["alteration_agreements"].get(res["subject_entity_id"])
            if a is not None and a["alteration_status"] == "SUBMITTED":
                a["alteration_status"] = "REJECTED"
                D.touch(a, coop)
    else:
        D.touch(res, coop)
    return ok(D.ser(vote), 201)


@bp.post("/cooperatives/<cid>/resolutions/<rid>/withdraw")
def withdraw_resolution(cid, rid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    res = D.get_scoped("resolutions", rid, cid, "Resolution")
    if res["resolution_status"] != "OPEN":
        raise ApiError(ERR_ALREADY_TERMINAL, "Resolution is closed", 409)
    if res["votes_for"] + res["votes_against"] + res["votes_abstain"] > 0:
        raise ApiError(
            ERR_RESOLUTION_ALREADY_VOTED,
            "Resolution may not be withdrawn after a vote has been cast",
            409,
        )
    res["resolution_status"] = "WITHDRAWN"
    res["closed_at"] = coop["current_utc"]
    D.touch(res, coop)
    return ok(D.ser(res))


@bp.get("/cooperatives/<cid>/resolutions/<rid>/votes")
def list_resolution_votes(cid, rid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    D.get_scoped("resolutions", rid, cid, "Resolution")
    items = [
        v for v in D.all_of("resolution_votes", cid)
        if v["resolution_id"] == rid
    ]
    from util import pagination
    total = len(items)
    limit, offset = pagination()
    from response import ok_list
    return ok_list([D.ser(v) for v in items[offset:offset + limit]], total, limit, offset)
