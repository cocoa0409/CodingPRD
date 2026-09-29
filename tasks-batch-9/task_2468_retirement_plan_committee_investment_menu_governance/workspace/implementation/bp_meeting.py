"""Committee meetings and motions."""
from flask import Blueprint

import calc
from core import (D, as_dec, as_enum, as_int, as_str, authenticate, body, clock,
                  fail, new_row, ok, ok_list, opt_field, paginate, parse_date,
                  public, q_bool, q_int, q_str, req_field,
                  require_actor_plan, resolve_committee_identity, store, touch)
from helpers import (filter_rows, get_row, resolve_body_refs, resolve_subject)

bp = Blueprint("meeting", __name__)


def _member_fit(member, error_id="ERR_TRAINING_NOT_CURRENT"):
    if member["fiduciary_training_status"] != "CURRENT":
        fail("ERR_TRAINING_NOT_CURRENT", "the member's training is not CURRENT")
    if not member.get("acceptance_signed_at"):
        fail("ERR_TRAINING_NOT_CURRENT",
             "the member has no signed fiduciary acceptance")


def _require_chair_present(meeting, actor, require_active=False):
    roster = meeting.get("attendee_member_ids") or []
    if actor.user_id not in roster:
        fail("ERR_CHAIR_NOT_PRESENT", "the acting chair is not on the roster")
    if require_active:
        member = store.members.get(actor.user_id)
        if member is None or member["status"] != "ACTIVE":
            fail("ERR_CHAIR_NOT_PRESENT", "the acting chair is no longer ACTIVE")


# --------------------------------------------------------------------------- #
# Meetings
# --------------------------------------------------------------------------- #

@bp.route("/governance/committee-meetings", methods=["POST"])
def create_meeting():
    actor = authenticate(("PlanSponsorAdmin", "CommitteeChair"))
    resolve_committee_identity(actor)
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans"})
    plan = refs.get("plan_id")
    require_actor_plan(actor, plan["id"])
    meeting_date = as_str(req_field(payload, "meeting_date"), "meeting_date")
    parse_date(meeting_date, "meeting_date")
    quarter_index = as_int(req_field(payload, "quarter_index"), "quarter_index", 0)

    for other in calc.plan_meetings(plan["id"]):
        if other["status"] != "VOID" and other["meeting_date"] == meeting_date:
            fail("ERR_DUPLICATE_RESOURCE",
                 "the plan already has a meeting on that date")

    meeting = new_row({
        "plan_id": plan["id"],
        "meeting_date": meeting_date,
        "quarter_index": quarter_index,
        "status": "SCHEDULED",
        "attendee_member_ids": [],
        "voting_attendee_count": 0,
        "eligible_voting_seat_count": 0,
        "quorum_met": False,
        "charter_version_pinned": None,
        "minutes_doc_ref": None,
        "minutes_approved_at": None,
        "carried_motion_count": 0,
    })
    store.meetings[meeting["id"]] = meeting
    return ok(public(meeting), 201)


@bp.route("/governance/committee-meetings", methods=["GET"])
def list_meetings():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    rows = filter_rows(list(store.meetings.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_int("quarter_index"), "quarter_index"),
                        (q_str("status"), "status"),
                        (q_bool("quorum_met"), "quorum_met"),
                        (q_str("meeting_date"), "meeting_date")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/committee-meetings/<meeting_id>", methods=["GET"])
def get_meeting(meeting_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    return ok(public(get_row("meetings", meeting_id, "meetingId")))


@bp.route("/governance/committee-meetings/<meeting_id>/convene", methods=["POST"])
def convene_meeting(meeting_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    meeting = get_row("meetings", meeting_id, "meetingId")
    plan = store.plans.get(meeting["plan_id"])
    require_actor_plan(actor, plan["id"])
    payload = body()
    refs = resolve_body_refs(payload, {"!attendee_member_ids": "members"},
                             extra_rows={"_meeting": ("meetings", meeting)})
    roster = payload.get("attendee_member_ids") or []
    seen = set()
    for member_id in roster:
        if member_id in seen:
            fail("ERR_INVALID_REQUEST", "attendee_member_ids contains duplicates")
        seen.add(member_id)

    if plan["charter_status"] != "ADOPTED":
        fail("ERR_CHARTER_NOT_ADOPTED", "the committee charter is not adopted")
    if meeting["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "only a SCHEDULED meeting may convene")
    for other in calc.plan_meetings(plan["id"]):
        if other["id"] != meeting["id"] and other["status"] == "IN_SESSION":
            fail("ERR_MEETING_IN_SESSION", "another meeting is already in session")
    if actor.user_id not in roster:
        fail("ERR_CHAIR_NOT_PRESENT", "the acting chair is not on the roster")
    _member_fit(actor.member)

    eligible, attending, quorum_met = calc.quorum_evaluation(plan, roster)
    meeting["attendee_member_ids"] = list(roster)
    meeting["eligible_voting_seat_count"] = eligible
    meeting["voting_attendee_count"] = attending
    meeting["quorum_met"] = quorum_met
    meeting["charter_version_pinned"] = plan["version"]
    meeting["status"] = "IN_SESSION"
    touch(meeting)
    return ok(public(meeting))


@bp.route("/governance/committee-meetings/<meeting_id>/adjourn", methods=["POST"])
def adjourn_meeting(meeting_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    meeting = get_row("meetings", meeting_id, "meetingId")
    require_actor_plan(actor, meeting["plan_id"])

    if meeting["status"] != "IN_SESSION":
        fail("ERR_MEETING_NOT_IN_SESSION", "the meeting is not in session")
    _require_chair_present(meeting, actor)

    for motion in calc.sort_created(calc.meeting_motions(meeting["id"])):
        if motion["status"] == "OPEN":
            motion["status"] = "WITHDRAWN"
            motion["closed_at"] = clock.iso()
            touch(motion)
    meeting["status"] = "ADJOURNED"
    touch(meeting)
    return ok(public(meeting))


@bp.route("/governance/committee-meetings/<meeting_id>/minutes-approve",
          methods=["POST"])
def approve_minutes(meeting_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    meeting = get_row("meetings", meeting_id, "meetingId")
    require_actor_plan(actor, meeting["plan_id"])
    payload = body()
    doc_ref = as_str(req_field(payload, "minutes_doc_ref"), "minutes_doc_ref", 6)

    if meeting["status"] != "ADJOURNED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an ADJOURNED meeting may have its minutes approved")
    _require_chair_present(meeting, actor, require_active=True)
    if not meeting["quorum_met"]:
        fail("ERR_QUORUM_NOT_MET", "the meeting was inquorate")
    _member_fit(actor.member)

    carried = 0
    for motion in calc.meeting_motions(meeting["id"]):
        if motion["status"] == "CARRIED":
            carried += 1
    meeting["carried_motion_count"] = carried
    meeting["minutes_doc_ref"] = doc_ref
    meeting["minutes_approved_at"] = clock.iso()
    meeting["status"] = "MINUTES_APPROVED"
    touch(meeting)
    return ok(public(meeting))


# --------------------------------------------------------------------------- #
# Motions
# --------------------------------------------------------------------------- #

@bp.route("/governance/motions", methods=["POST"])
def create_motion():
    actor = authenticate(("CommitteeChair", "CommitteeMember"))
    resolve_committee_identity(actor)
    payload = body()
    refs = resolve_body_refs(payload, {"!meeting_id": "meetings"})
    meeting = refs.get("meeting_id")
    plan = store.plans.get(meeting["plan_id"])
    require_actor_plan(actor, plan["id"])
    subject_type = as_enum(req_field(payload, "subject_type"), "subject_type",
                           calc.SUBJECT_TYPES)
    subject_id = as_str(req_field(payload, "subject_id"), "subject_id")
    tally_basis = as_enum(opt_field(payload, "tally_basis", "VOTES_CAST"),
                          "tally_basis", calc.TALLY_BASES)
    threshold = as_dec(opt_field(payload, "carried_threshold_pct",
                                 plan["voting_threshold_pct"]),
                       "carried_threshold_pct", 4, "0.0000", "100.0000")
    collection, subject = resolve_subject(subject_type, subject_id)
    from helpers import plan_id_of
    owner = plan_id_of(collection, subject)
    if owner is not None and owner != plan["id"]:
        fail("ERR_CROSS_PLAN_REFERENCE", "subject_id belongs to a different plan")

    if meeting["status"] != "IN_SESSION":
        fail("ERR_MEETING_NOT_IN_SESSION", "the meeting is not in session")

    provider_role = "NONE"
    if subject_type == "RFP_AWARD":
        provider_role = subject.get("provider_role") or "NONE"

    motion = new_row({
        "meeting_id": meeting["id"],
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_provider_role": provider_role,
        "status": "OPEN",
        "tally_basis": tally_basis,
        "carried_threshold_pct": threshold,
        "eligible_voter_count": meeting["voting_attendee_count"],
        "votes": [],
        "for_count": 0,
        "against_count": 0,
        "abstain_count": 0,
        "recuse_count": 0,
        "support_pct": None,
        "closed_at": None,
    })
    store.motions[motion["id"]] = motion
    return ok(public(motion), 201)


@bp.route("/governance/motions", methods=["GET"])
def list_motions():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    rows = filter_rows(list(store.motions.values()),
                       [(q_str("meeting_id"), "meeting_id"),
                        (q_str("subject_type"), "subject_type"),
                        (q_str("subject_id"), "subject_id"),
                        (q_str("status"), "status"),
                        (q_str("tally_basis"), "tally_basis")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/motions/<motion_id>", methods=["GET"])
def get_motion(motion_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    return ok(public(get_row("motions", motion_id, "motionId")))


@bp.route("/governance/motions/<motion_id>/votes", methods=["POST"])
def cast_vote(motion_id):
    actor = authenticate(("CommitteeChair", "CommitteeMember"))
    resolve_committee_identity(actor)
    payload = body()
    member_id = req_field(payload, "member_id")
    if member_id != actor.user_id:
        fail("ERR_ACTOR_NOT_SELF", "a member may cast only their own vote")
    motion = get_row("motions", motion_id, "motionId")
    meeting = store.meetings.get(motion["meeting_id"])
    plan = store.plans.get(meeting["plan_id"])
    refs = resolve_body_refs(payload, {"!member_id": "members"},
                             extra_rows={"_motion": ("motions", motion)})
    member = refs.get("member_id")
    require_actor_plan(actor, plan["id"])
    vote = as_enum(req_field(payload, "vote"), "vote", calc.VOTE_VALUES)
    recusal_basis = payload.get("recusal_basis")
    if recusal_basis is not None:
        recusal_basis = as_str(recusal_basis, "recusal_basis", 1)

    if motion["status"] != "OPEN":
        fail("ERR_OPEN_MOTION_VOTE_LOCK", "the motion is no longer open")
    if member["status"] != "ACTIVE":
        fail("ERR_TRAINING_NOT_CURRENT", "the voting member is not ACTIVE")
    _member_fit(member)

    if vote != "RECUSE":
        conflicted = False
        role = member.get("affiliated_provider_role") or "NONE"
        if role != "NONE" and motion["subject_type"] == "RFP_AWARD" and \
                motion["subject_provider_role"] == role:
            conflicted = True
        if member.get("independence_flag") is False and \
                motion["subject_type"] == "FEE_LEVELIZATION":
            conflicted = True
        if conflicted:
            fail("ERR_RECUSAL_REQUIRED", "the conflicted member must RECUSE")

    entry = {"member_id": member["id"], "vote": vote, "cast_at": clock.iso(),
             "recusal_basis": recusal_basis}
    prior = None
    votes = motion["votes"]
    for index, existing in enumerate(votes):
        if existing["member_id"] == member["id"]:
            prior = existing
            votes[index] = entry
            break
    if prior is None:
        votes.append(entry)
    calc.recount_votes(motion)
    touch(motion)

    if vote != "RECUSE" and (prior is None or prior["vote"] == "RECUSE"):
        member["votes_cast_count"] = member.get("votes_cast_count", 0) + 1
        touch(member)
    return ok(public(motion))


@bp.route("/governance/motions/<motion_id>/close", methods=["POST"])
def close_motion(motion_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    motion = get_row("motions", motion_id, "motionId")
    meeting = store.meetings.get(motion["meeting_id"])
    plan = store.plans.get(meeting["plan_id"])
    require_actor_plan(actor, plan["id"])

    # PRD 2.12 priority 42 prefers the specific state error over the generic
    # one, so a motion whose meeting has adjourned answers with
    # ERR_MEETING_NOT_IN_SESSION rather than ERR_INVALID_STATE_TRANSITION.
    if meeting["status"] != "IN_SESSION":
        fail("ERR_MEETING_NOT_IN_SESSION", "the meeting is not in session")
    if motion["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "the motion is not OPEN")
    if not meeting["quorum_met"]:
        fail("ERR_QUORUM_NOT_MET", "the meeting is inquorate")

    support = calc.motion_tally(motion)
    motion["support_pct"] = support
    motion["closed_at"] = clock.iso()
    # `carried_threshold_pct` is copied verbatim from the plan's charter fraction
    # (0.5000..1.0000) while `support_pct` is a percentage; put both on the same
    # scale before the inclusive comparison. A threshold above 1 is already a
    # percentage (the PRD's 66.6667 example) and is compared as given.
    threshold = D(motion["carried_threshold_pct"])
    if threshold <= D("1"):
        threshold = threshold * D(100)
    if support >= threshold:
        motion["status"] = "CARRIED"
        meeting["carried_motion_count"] = meeting.get("carried_motion_count", 0) + 1
        touch(meeting)
    else:
        motion["status"] = "FAILED"
        if motion["subject_type"] == "FUND_REPLACEMENT":
            proposal = store.proposals.get(motion["subject_id"])
            if proposal is not None and proposal["status"] == "UNDER_REVIEW":
                proposal["status"] = "REJECTED"
                touch(proposal)
                calc.recompute_posture(plan)
                touch(plan)
    touch(motion)
    return ok(public(motion))
