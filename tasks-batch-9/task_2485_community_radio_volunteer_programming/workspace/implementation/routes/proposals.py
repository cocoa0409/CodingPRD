"""Program proposals and committee ballots (PRD 3.3)."""

import response
from db import clock, db, new_row, ordered, touch
from errors import ApiError
from middleware import (
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_VOLUNTEER,
    authenticate,
    body,
    caller_id,
    enum_field,
    int_field,
    int_query,
    invalid,
    language_field,
    list_field,
    lookup,
    str_field,
    str_query,
)
from services import calc
from services import serializers as ser

PROPOSAL_EDITABLE = ("DRAFT", "REVISION_REQUESTED")
PROPOSAL_WITHDRAWABLE = ("DRAFT", "SUBMITTED", "IN_COMMITTEE", "REVISION_REQUESTED")


def register(app):
    @app.post("/program-proposals")
    def create_proposal():
        authenticate(ROLE_VOLUNTEER, ROLE_PROGRAM_DIRECTOR)
        data = body()
        proposer_id = str_field(data, "proposer_volunteer_id")
        title = str_field(data, "title", non_empty=True)
        format_code = enum_field(data, "format_code", calc.FORMAT_CODES)
        language_code = language_field(data, "language_code")
        daypart = enum_field(data, "requested_daypart", calc.DAYPARTS)
        duration = int_field(data, "requested_duration_minutes", 15, 720)
        tags = list_field(data, "diversity_tags", required=False, default=[])
        lookup(db.volunteers, proposer_id, "ERR_VOLUNTEER_NOT_FOUND")
        row = new_row(db.proposals, {
            "proposer_volunteer_id": proposer_id,
            "title": title,
            "format_code": format_code,
            "language_code": language_code,
            "requested_daypart": daypart,
            "requested_duration_minutes": duration,
            "diversity_tags": tags,
            "status": "DRAFT",
            "review_round": 1,
            "composite_score": None,
            "decline_majority": False,
            "decided_at": None,
        })
        return response.created(ser.proposal(row))

    @app.get("/program-proposals")
    def list_proposals():
        authenticate(ROLE_PROGRAM_DIRECTOR, ROLE_COMMITTEE_MEMBER, ROLE_VOLUNTEER, ROLE_COMPLIANCE_OFFICER)
        status = str_query("status")
        proposer_id = str_query("proposer_volunteer_id")
        format_code = str_query("format_code")

        def keep(row):
            if status is not None and row["status"] != status:
                return False
            if proposer_id is not None and row["proposer_volunteer_id"] != proposer_id:
                return False
            if format_code is not None and row["format_code"] != format_code:
                return False
            return True

        return response.listing(ordered(db.proposals, keep), ser.proposal)

    @app.get("/program-proposals/<proposal_id>")
    def get_proposal(proposal_id):
        authenticate(ROLE_PROGRAM_DIRECTOR, ROLE_COMMITTEE_MEMBER, ROLE_VOLUNTEER, ROLE_COMPLIANCE_OFFICER)
        row = lookup(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
        return response.obj(ser.proposal(row))

    @app.patch("/program-proposals/<proposal_id>")
    def patch_proposal(proposal_id):
        authenticate(ROLE_VOLUNTEER)
        existing = db.proposals.get(proposal_id)
        if existing is not None and existing["proposer_volunteer_id"] != caller_id():
            raise ApiError("ERR_NOT_PROPOSAL_OWNER")
        data = body()
        title = str_field(data, "title", required=False, non_empty=True)
        format_code = enum_field(data, "format_code", calc.FORMAT_CODES, required=False)
        language_code = language_field(data, "language_code", required=False)
        daypart = enum_field(data, "requested_daypart", calc.DAYPARTS, required=False)
        duration = int_field(data, "requested_duration_minutes", 15, 720, required=False, default=None)
        tags = list_field(data, "diversity_tags", required=False, default=None)
        row = lookup(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
        if row["status"] not in PROPOSAL_EDITABLE:
            raise ApiError("ERR_NOT_EDITABLE", "A proposal is only editable in DRAFT or REVISION_REQUESTED.")
        changed = False
        for field, value in (
            ("title", title),
            ("format_code", format_code),
            ("language_code", language_code),
            ("requested_daypart", daypart),
            ("requested_duration_minutes", duration),
            ("diversity_tags", tags),
        ):
            if value is not None:
                row[field] = value
                changed = True
        if changed:
            touch(row)
        return response.obj(ser.proposal(row))

    @app.post("/program-proposals/<proposal_id>/submit")
    def submit_proposal(proposal_id):
        authenticate(ROLE_VOLUNTEER)
        existing = db.proposals.get(proposal_id)
        if existing is not None and existing["proposer_volunteer_id"] != caller_id():
            raise ApiError("ERR_NOT_PROPOSAL_OWNER")
        row = lookup(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
        if row["status"] not in PROPOSAL_EDITABLE:
            raise ApiError("ERR_INVALID_STATE", "Only a draft or revision-requested proposal can be submitted.")
        proposer = db.volunteers.get(row["proposer_volunteer_id"])
        if proposer is None or proposer["status"] != "CERTIFIED":
            raise ApiError("ERR_PROPOSER_NOT_CERTIFIED")
        if row["status"] == "DRAFT":
            row["review_round"] = 1
        else:
            row["review_round"] = row["review_round"] + 1
            row["composite_score"] = None
            row["decline_majority"] = False
        row["status"] = "SUBMITTED"
        touch(row)
        return response.obj(ser.proposal(row))

    @app.post("/program-proposals/<proposal_id>/withdraw")
    def withdraw_proposal(proposal_id):
        authenticate(ROLE_VOLUNTEER)
        existing = db.proposals.get(proposal_id)
        if existing is not None and existing["proposer_volunteer_id"] != caller_id():
            raise ApiError("ERR_NOT_PROPOSAL_OWNER")
        row = lookup(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
        if row["status"] not in PROPOSAL_WITHDRAWABLE:
            raise ApiError("ERR_INVALID_STATE", "A decided proposal cannot be withdrawn.")
        row["status"] = "WITHDRAWN"
        touch(row)
        return response.obj(ser.proposal(row))

    @app.post("/program-proposals/<proposal_id>/open-review")
    def open_review(proposal_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        row = lookup(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
        if row["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Only a submitted proposal can be opened for review.")
        if len(calc.seated_committee()) < 3:
            raise ApiError("ERR_COMMITTEE_UNDERSTAFFED")
        row["status"] = "IN_COMMITTEE"
        touch(row)
        return response.obj(ser.proposal(row))

    # ---------------------------------------------------------------- ballots
    @app.post("/program-proposals/<proposal_id>/votes")
    def cast_vote(proposal_id):
        authenticate(ROLE_COMMITTEE_MEMBER)
        caster = db.volunteers.get(caller_id())
        if caster is None or caster.get("committee_seat") is not True:
            raise ApiError("ERR_NOT_COMMITTEE_MEMBER")
        data = body()
        member_id = str_field(data, "member_volunteer_id")
        format_fit = int_field(data, "format_fit_score", 1, 5)
        diversity = int_field(data, "diversity_score", 1, 5)
        quality = int_field(data, "quality_score", 1, 5)
        recommendation = enum_field(data, "recommendation", calc.RECOMMENDATIONS)
        rationale = str_field(data, "rationale", required=False, default=None)

        proposal = db.proposals.get(proposal_id)
        if proposal is not None:
            for vote in db.votes.values():
                if (
                    vote["proposal_id"] == proposal["id"]
                    and vote["member_volunteer_id"] == member_id
                    and vote["review_round"] == proposal["review_round"]
                ):
                    raise ApiError("ERR_DUPLICATE_VOTE")
        proposal = lookup(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
        member = lookup(db.volunteers, member_id, "ERR_VOLUNTEER_NOT_FOUND")
        if member_id == proposal["proposer_volunteer_id"]:
            raise ApiError("ERR_SELF_VOTE_FORBIDDEN")
        if proposal["status"] != "IN_COMMITTEE":
            raise ApiError("ERR_PROPOSAL_NOT_IN_REVIEW")
        if member["status"] in ("SUSPENDED", "RESIGNED"):
            raise ApiError("ERR_VOTER_INELIGIBLE")

        row = new_row(db.votes, {
            "proposal_id": proposal["id"],
            "member_volunteer_id": member_id,
            "review_round": proposal["review_round"],
            "format_fit_score": format_fit,
            "diversity_score": diversity,
            "quality_score": quality,
            "recommendation": recommendation,
            "rationale": rationale,
        }, versioned=False)
        touch(proposal)
        return response.created(ser.committee_vote(row))

    @app.get("/committee-votes")
    def list_votes():
        authenticate(ROLE_PROGRAM_DIRECTOR, ROLE_COMMITTEE_MEMBER, ROLE_COMPLIANCE_OFFICER)
        proposal_id = str_query("proposal_id")
        member_id = str_query("member_volunteer_id")
        review_round = int_query("review_round")

        def keep(row):
            if proposal_id is not None and row["proposal_id"] != proposal_id:
                return False
            if member_id is not None and row["member_volunteer_id"] != member_id:
                return False
            if review_round is not None and row["review_round"] != review_round:
                return False
            return True

        return response.listing(ordered(db.votes, keep), ser.committee_vote)

    @app.get("/committee-votes/<vote_id>")
    def get_vote(vote_id):
        authenticate(ROLE_PROGRAM_DIRECTOR, ROLE_COMMITTEE_MEMBER, ROLE_COMPLIANCE_OFFICER)
        row = lookup(db.votes, vote_id, "ERR_VOTE_NOT_FOUND")
        return response.obj(ser.committee_vote(row))

    # --------------------------------------------------------------- decision
    @app.post("/program-proposals/<proposal_id>/decide")
    def decide_proposal(proposal_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        expected_version = int_field(data, "expected_proposal_version")

        candidate = db.proposals.get(proposal_id)
        if candidate is not None:
            for program in db.programs.values():
                if program["proposal_id"] == candidate["id"]:
                    raise ApiError("ERR_PROGRAM_ALREADY_EXISTS")
        proposal = lookup(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
        if expected_version != proposal["version"]:
            raise ApiError("ERR_STALE_PROPOSAL_VERSION")
        if proposal["status"] != "IN_COMMITTEE":
            raise ApiError("ERR_PROPOSAL_NOT_IN_REVIEW")

        ballots = calc.round_ballots(proposal)
        seated = calc.seated_committee(exclude_volunteer_id=proposal["proposer_volunteer_id"])
        quorum = calc.required_quorum(len(seated))
        if len(ballots) < quorum:
            raise ApiError("ERR_QUORUM_NOT_MET")

        score = calc.composite_score(proposal, ballots)
        declined = calc.decline_majority(ballots)
        proposal["composite_score"] = score
        proposal["decline_majority"] = declined
        proposal["decided_at"] = clock.now

        if declined:
            proposal["status"] = "DECLINED"
        elif score >= calc.Decimal("4.00"):
            proposal["status"] = "APPROVED"
        elif score >= calc.Decimal("3.00"):
            if proposal["review_round"] < 2:
                proposal["status"] = "REVISION_REQUESTED"
            else:
                proposal["status"] = "DECLINED"
        else:
            proposal["status"] = "DECLINED"
        touch(proposal)

        if proposal["status"] == "APPROVED":
            new_row(db.programs, {
                "proposal_id": proposal["id"],
                "host_volunteer_id": proposal["proposer_volunteer_id"],
                "title": proposal["title"],
                "format_code": proposal["format_code"],
                "programming_status": "APPROVED_UNSCHEDULED",
                "compliance_penalty_points": 0,
                "performance_score": None,
                "performance_score_method": None,
                "last_evaluated_at": None,
                "cancellation_reason": None,
            })
        return response.obj(ser.proposal(proposal))
