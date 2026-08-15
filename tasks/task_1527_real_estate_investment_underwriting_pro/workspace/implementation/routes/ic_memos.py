"""IC Memo and IC Vote endpoints."""
from flask import request

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import auth, READ_ROLES
from response import ok, ok_list
from services import deal_memos, memo_votes
from util import (
    get_deal,
    get_memo,
    ic_memo_view,
    ic_vote_view,
    init_common_fields,
    json_body,
    paginate,
    parse_enum_field,
    parse_pagination,
    parse_str_field,
    touch,
)

RECOMMENDATIONS = ["PURSUE", "PASS", "RENEGOTIATE"]
VOTE_VALUES = ["YES", "NO", "ABSTAIN"]
IC_QUORUM_YES = 2


def register(app):
    @app.post("/re-underwriting/deals/<deal_id>/ic-memos")
    def create_memo(deal_id):
        _user_id, _role = auth(allowed=["Analyst"])
        d = get_deal(deal_id)
        body = json_body()

        # body FK existence
        scenario_id = body.get("scenario_id")
        if scenario_id is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Missing required field: scenario_id"
            )
        scenario = DB["scenarios"].get(scenario_id)
        if scenario is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Scenario does not exist")

        recommendation = parse_enum_field(body, "recommendation", RECOMMENDATIONS)
        thesis = parse_str_field(body, "thesis")
        risks = parse_str_field(body, "risks")

        # referential: scenario must belong to same deal AND be COMPUTED
        if scenario["deal_id"] != deal_id or scenario["status"] != "COMPUTED":
            raise ApiError(
                "ERR_SCENARIO_NOT_COMPUTED",
                422,
                "scenario_id must resolve to a Scenario in COMPUTED status for this deal",
            )

        # OCC check
        expected = body.get("expected_deal_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    "expected_deal_version must be an integer",
                )
            if expected != d["version"]:
                raise ApiError(
                    "ERR_STALE_VERSION",
                    412,
                    "expected_deal_version does not match deal.version",
                )

        rec = {
            "id": new_id(),
            "deal_id": deal_id,
            "scenario_id": scenario_id,
            "recommendation": recommendation,
            "thesis": thesis,
            "risks": risks,
            "status": "DRAFT",
            "submitted_at": None,
            "decided_at": None,
        }
        init_common_fields(rec)
        DB["ic_memos"][rec["id"]] = rec
        touch(d)  # bump parent deal version
        return ok(ic_memo_view(rec), status=201)

    @app.get("/re-underwriting/deals/<deal_id>/ic-memos")
    def list_deal_memos(deal_id):
        auth(allowed=READ_ROLES)
        get_deal(deal_id)
        limit, offset = parse_pagination()
        items = list(deal_memos(deal_id))
        items = _apply_memo_filters(items)
        items.sort(key=lambda m: m["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([ic_memo_view(m) for m in page], total, limit, offset)

    @app.get("/re-underwriting/ic-memos")
    def list_all_memos():
        auth(allowed=READ_ROLES)
        limit, offset = parse_pagination()
        items = list(DB["ic_memos"].values())
        deal_id = request.args.get("deal_id")
        if deal_id is not None:
            items = [m for m in items if m["deal_id"] == deal_id]
        items = _apply_memo_filters(items)
        items.sort(key=lambda m: m["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([ic_memo_view(m) for m in page], total, limit, offset)

    @app.get("/re-underwriting/ic-memos/<memo_id>")
    def get_memo_route(memo_id):
        auth(allowed=READ_ROLES)
        m = get_memo(memo_id)
        return ok(ic_memo_view(m))

    @app.post("/re-underwriting/ic-memos/<memo_id>/submit")
    def submit_memo(memo_id):
        user_id, _role = auth(allowed=["Analyst"])
        m = get_memo(memo_id)
        d = DB["deals"][m["deal_id"]]
        if m["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Memo is not in DRAFT status")
        if d["status"] != "UNDERWRITING":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Deal is not in UNDERWRITING status"
            )
        if d["analyst_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", 403, "Caller is not the deal's analyst")
        scenario = DB["scenarios"].get(m["scenario_id"])
        if scenario is None or scenario["status"] != "COMPUTED":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Memo's scenario is not in COMPUTED status",
            )
        m["status"] = "SUBMITTED"
        m["submitted_at"] = now_iso()
        touch(m)
        return ok(ic_memo_view(m))

    @app.post("/re-underwriting/ic-memos/<memo_id>/vote")
    def cast_vote(memo_id):
        user_id, role = auth(allowed=["IC_Member", "IC_Chair"])
        m = get_memo(memo_id)
        d = DB["deals"][m["deal_id"]]

        # state: memo must be UNDER_VOTE (priority 6/17)
        if m["status"] != "UNDER_VOTE":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Memo is not in UNDER_VOTE status",
            )

        body = json_body()
        vote = parse_enum_field(body, "vote", VOTE_VALUES)
        comment = body.get("comment")
        if comment is not None and not isinstance(comment, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "comment must be a string")

        # duplicate vote (priority 15)
        for v in memo_votes(memo_id):
            if v["voter_user_id"] == user_id:
                raise ApiError(
                    "ERR_DUPLICATE_VOTE",
                    409,
                    "Voter has already cast a vote on this memo",
                )

        # segregation of duties (priority 16)
        if user_id == d["analyst_id"]:
            raise ApiError(
                "ERR_SEG_DUTIES",
                403,
                "Deal analyst may not cast an ICVote on this deal's memo",
            )

        rec = {
            "id": new_id(),
            "memo_id": memo_id,
            "voter_user_id": user_id,
            "vote": vote,
            "comment": comment,
            "cast_at": now_iso(),
            "created_at": now_iso(),
        }
        DB["ic_votes"][rec["id"]] = rec

        # tally after recording
        votes = memo_votes(memo_id)
        yes_count = sum(1 for v in votes if v["vote"] == "YES")
        no_count = sum(1 for v in votes if v["vote"] == "NO")

        if no_count >= 1:
            # cascade to REJECTED
            m["status"] = "REJECTED"
            m["decided_at"] = now_iso()
            touch(m)
            d["status"] = "REJECTED"
            # rejected_reason from the NO vote's comment (most recent NO)
            no_votes = [v for v in votes if v["vote"] == "NO"]
            no_votes.sort(key=lambda v: v["created_at"])
            d["rejected_reason"] = no_votes[-1]["comment"]
            touch(d)
        elif yes_count >= IC_QUORUM_YES and no_count == 0:
            m["status"] = "APPROVED"
            m["decided_at"] = now_iso()
            touch(m)
            d["status"] = "APPROVED"
            d["approved_at"] = now_iso()
            touch(d)

        return ok(ic_vote_view(rec), status=201)

    @app.post("/re-underwriting/ic-memos/<memo_id>/reject")
    def reject_memo(memo_id):
        _user_id, _role = auth(allowed=["IC_Chair"])
        m = get_memo(memo_id)
        d = DB["deals"][m["deal_id"]]
        if m["status"] != "UNDER_VOTE":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Memo is not in UNDER_VOTE status"
            )
        body = json_body()
        reason = parse_str_field(body, "reason")

        m["status"] = "REJECTED"
        m["decided_at"] = now_iso()
        touch(m)
        d["status"] = "REJECTED"
        d["rejected_reason"] = reason
        touch(d)
        return ok(ic_memo_view(m))

    @app.get("/re-underwriting/ic-memos/<memo_id>/votes")
    def list_votes(memo_id):
        auth(allowed=READ_ROLES)
        get_memo(memo_id)
        limit, offset = parse_pagination()
        items = sorted(memo_votes(memo_id), key=lambda v: v["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([ic_vote_view(v) for v in page], total, limit, offset)


def _apply_memo_filters(items):
    status = request.args.get("status")
    scenario_id = request.args.get("scenario_id")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if scenario_id is not None:
        items = [m for m in items if m["scenario_id"] == scenario_id]
    return items
