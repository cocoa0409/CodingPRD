"""Committee seats, member appointments, fiduciary training records."""
from flask import Blueprint, request

import calc
from core import (D, as_bool, as_dec, as_enum, as_int, as_str, authenticate,
                  body, clock,
                  fail, new_row, ok, ok_list, opt_field, paginate, parse_date,
                  public, q_bool, q_int, q_str, req_field, store, touch)
from helpers import filter_rows, get_row, resolve_body_refs

bp = Blueprint("committee", __name__)


def _posture(plan):
    calc.recompute_posture(plan)
    touch(plan)


# --------------------------------------------------------------------------- #
# Committee seats
# --------------------------------------------------------------------------- #

@bp.route("/governance/committee-seats", methods=["POST"])
def create_seat():
    authenticate(("PlanSponsorAdmin",))
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans"})
    plan = refs.get("plan_id")
    seat_code = as_str(req_field(payload, "seat_code"), "seat_code", 1, 60)
    seat_class = as_enum(req_field(payload, "seat_class"), "seat_class",
                         calc.SEAT_CLASSES)
    voting = as_bool(req_field(payload, "voting"), "voting")
    seat_index = as_int(req_field(payload, "seat_index"), "seat_index", 1)

    for seat in calc.plan_seats(plan["id"]):
        if seat["status"] != "RETIRED" and seat["seat_code"] == seat_code:
            fail("ERR_DUPLICATE_RESOURCE", "seat_code already exists on this plan")
        if seat["seat_index"] == seat_index:
            fail("ERR_DUPLICATE_RESOURCE", "seat_index already exists on this plan")

    seat = new_row({
        "plan_id": plan["id"],
        "seat_code": seat_code,
        "seat_class": seat_class,
        "voting": voting,
        "status": "VACANT",
        "consecutive_vacant_quarters": 0,
        "seat_index": seat_index,
    })
    store.seats[seat["id"]] = seat
    return ok(public(seat), 201)


@bp.route("/governance/committee-seats", methods=["GET"])
def list_seats():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    rows = filter_rows(list(store.seats.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_str("seat_class"), "seat_class"),
                        (q_bool("voting"), "voting"),
                        (q_str("status"), "status"),
                        (q_str("seat_code"), "seat_code"),
                        (q_int("seat_index"), "seat_index")])
    data, limit, offset, total = paginate(rows, secondary=lambda r: r["seat_index"])
    return ok_list(data, limit, offset, total)


@bp.route("/governance/committee-seats/<seat_id>", methods=["GET"])
def get_seat(seat_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    return ok(public(get_row("seats", seat_id, "seatId")))


def _seat_member(seat_id):
    for member in store.members.values():
        if member["seat_id"] == seat_id and \
                member["status"] in calc.NON_TERMINAL_MEMBER_STATES:
            return member
    return None


@bp.route("/governance/committee-seats/<seat_id>/status", methods=["POST"])
def seat_status(seat_id):
    authenticate(("PlanSponsorAdmin",))
    seat = get_row("seats", seat_id, "seatId")
    payload = body()
    action = as_enum(req_field(payload, "action"), "action",
                     ("SUSPEND", "REINSTATE", "RETIRE"))
    reason = payload.get("reason")
    if reason is not None:
        reason = as_str(reason, "reason", 1)
    plan = store.plans.get(seat["plan_id"])
    holder = _seat_member(seat["id"])

    if action == "SUSPEND":
        if seat["status"] not in ("VACANT", "FILLED"):
            fail("ERR_INVALID_STATE_TRANSITION", "the seat cannot be suspended")
        if seat["status"] == "FILLED":
            for meeting in calc.plan_meetings(seat["plan_id"]):
                if meeting["status"] == "IN_SESSION":
                    fail("ERR_MEETING_IN_SESSION", "a committee meeting is in session")
        was_filled = seat["status"] == "FILLED"
        seat["status"] = "SUSPENDED"
        if reason is not None:
            seat["status_change_reason"] = reason
        touch(seat)
        if was_filled and plan is not None:
            _posture(plan)
    elif action == "REINSTATE":
        if seat["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE_TRANSITION", "only a suspended seat may be reinstated")
        seat["status"] = "FILLED" if holder is not None else "VACANT"
        if reason is not None:
            seat["status_change_reason"] = reason
        touch(seat)
        if plan is not None:
            _posture(plan)
    else:
        if seat["status"] not in ("VACANT", "SUSPENDED"):
            fail("ERR_SEAT_NOT_VACANT", "only a vacant or suspended seat may be retired")
        remaining = [s for s in calc.plan_seats(seat["plan_id"])
                     if s.get("voting") and s["status"] != "RETIRED"
                     and s["id"] != seat["id"]]
        if len(remaining) < 2:
            fail("ERR_CHARTER_SEATS_INSUFFICIENT",
                 "the plan must retain at least two non-retired voting seats")
        if holder is not None:
            fail("ERR_SLOT_HAS_OPEN_PROPOSAL",
                 "the seat still holds a non-terminal appointment")
        seat["status"] = "RETIRED"
        if reason is not None:
            seat["status_change_reason"] = reason
        touch(seat)
        if plan is not None:
            _posture(plan)
    return ok(public(seat))


# --------------------------------------------------------------------------- #
# Committee members
# --------------------------------------------------------------------------- #

@bp.route("/governance/committee-members", methods=["POST"])
def appoint_member():
    authenticate(("PlanSponsorAdmin",))
    payload = body()
    refs = resolve_body_refs(payload, {"!seat_id": "seats"})
    seat = refs.get("seat_id")
    plan = store.plans.get(seat["plan_id"])
    person_name = as_str(req_field(payload, "member_name"), "member_name", 1, 120)
    person_email = as_str(req_field(payload, "person_email"), "person_email", 1, 200)
    start = parse_date(as_str(req_field(payload, "term_start_date"),
                              "term_start_date"), "term_start_date")
    end = parse_date(as_str(req_field(payload, "term_end_date"),
                            "term_end_date"), "term_end_date")
    if end < start:
        fail("ERR_INVALID_REQUEST", "term_end_date must not precede term_start_date")
    doc_ref = payload.get("acceptance_doc_ref")
    if doc_ref is not None:
        doc_ref = as_str(doc_ref, "acceptance_doc_ref", 1)
    provider_role = as_enum(opt_field(payload, "affiliated_provider_role", "NONE"),
                            "affiliated_provider_role", calc.PROVIDER_ROLES)

    if seat["status"] != "VACANT":
        fail("ERR_SEAT_NOT_VACANT", "the seat is not vacant")

    existing = [m for m in store.members.values() if m["seat_id"] == seat["id"]]
    for member in existing:
        if member["status"] not in calc.NON_TERMINAL_MEMBER_STATES:
            continue
        if member["person_email"] == person_email:
            fail("ERR_DUPLICATE_RESOURCE", "person_email already appointed to this seat")
    for member in existing:
        if member["status"] not in calc.NON_TERMINAL_MEMBER_STATES:
            continue
        other_start = parse_date(member["term_start_date"], "term_start_date")
        other_end = parse_date(member["term_end_date"], "term_end_date")
        if calc.intervals_overlap_or_adjacent(start, end, other_start, other_end):
            fail("ERR_SEAT_TERM_OVERLAP",
                 "the term overlaps or abuts an existing appointment on this seat")
    if seat.get("voting") and plan is not None:
        filled = len([s for s in calc.plan_seats(plan["id"])
                      if s.get("voting") and s["status"] == "FILLED"])
        if filled + 1 > plan["max_voting_seats"]:
            fail("ERR_VOTING_SEATS_EXCEEDED",
                 "filling this seat would exceed max_voting_seats")

    member = new_row({
        "seat_id": seat["id"],
        "person_name": person_name,
        "person_email": person_email,
        "status": "APPOINTED",
        "term_start_date": payload["term_start_date"],
        "term_end_date": payload["term_end_date"],
        "acceptance_signed_at": None,
        "acceptance_doc_ref": doc_ref,
        "fiduciary_training_status": "PENDING",
        "affiliated_provider_role": provider_role,
        "independence_flag": provider_role == "NONE",
        "end_term_reason": None,
        "votes_cast_count": 0,
    })
    store.members[member["id"]] = member
    seat["status"] = "FILLED"
    seat["consecutive_vacant_quarters"] = 0
    touch(seat)
    if plan is not None:
        _posture(plan)
    return ok(public(member), 201)


@bp.route("/governance/committee-members", methods=["GET"])
def list_members():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    rows = list(store.members.values())
    plan_id = q_str("plan_id")
    if plan_id is not None:
        rows = [m for m in rows if calc.member_plan_id(m) == plan_id]
    rows = filter_rows(rows,
                       [(q_str("seat_id"), "seat_id"),
                        (q_str("status"), "status"),
                        (q_str("fiduciary_training_status"),
                         "fiduciary_training_status"),
                        (q_str("affiliated_provider_role"),
                         "affiliated_provider_role")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/committee-members/<member_id>", methods=["GET"])
def get_member(member_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    return ok(public(get_row("members", member_id, "memberId")))


@bp.route("/governance/committee-members/<member_id>/acceptance", methods=["POST"])
def sign_acceptance(member_id):
    actor = authenticate(("CommitteeMember", "CommitteeChair"))
    member = get_row("members", member_id, "memberId")
    payload = body()
    doc_ref = payload.get("acceptance_doc_ref")
    if doc_ref is not None:
        doc_ref = as_str(doc_ref, "acceptance_doc_ref", 1)
    if actor.user_id != member["id"]:
        fail("ERR_ACTOR_NOT_SELF", "a member may only sign their own acceptance")
    if member.get("acceptance_signed_at") is not None:
        fail("ERR_ACCEPTANCE_ALREADY_SIGNED", "acceptance has already been signed")
    if member["status"] not in ("APPOINTED", "TRAINING_ASSIGNED"):
        fail("ERR_INVALID_STATE_TRANSITION", "acceptance cannot be signed now")

    member["acceptance_signed_at"] = clock.iso()
    if doc_ref is not None:
        member["acceptance_doc_ref"] = doc_ref
    member["status"] = "ACCEPTANCE_PENDING"
    touch(member)
    plan = store.plans.get(calc.member_plan_id(member))
    if plan is not None:
        plan["documented_acceptance_count"] = \
            plan.get("documented_acceptance_count", 0) + 1
        touch(plan)
    return ok(public(member))


@bp.route("/governance/committee-members/<member_id>/activate", methods=["POST"])
def activate_member(member_id):
    authenticate(("PlanSponsorAdmin",))
    member = get_row("members", member_id, "memberId")
    body()
    if member["status"] not in ("ACCEPTANCE_PENDING", "TRAINING_ASSIGNED"):
        fail("ERR_INVALID_STATE_TRANSITION", "the member cannot be activated now")
    if member.get("acceptance_signed_at") is None or \
            member.get("acceptance_doc_ref") is None:
        fail("ERR_FIDUCIARY_ACCEPTANCE_MISSING",
             "a signed acceptance and its document reference are required")
    calc.refresh_training_status(member)
    if member["fiduciary_training_status"] != "CURRENT":
        fail("ERR_TRAINING_NOT_CURRENT", "fiduciary training is not current")
    seat = store.seats.get(member["seat_id"])
    if seat is None or seat["status"] != "FILLED":
        fail("ERR_SEAT_NOT_ACTIVE", "the member's seat is not FILLED")
    if not calc.date_in_term(member):
        fail("ERR_TERM_NOT_IN_EFFECT", "the logical date is outside the member's term")

    member["status"] = "ACTIVE"
    touch(member)
    plan = store.plans.get(seat["plan_id"])
    if plan is not None:
        _posture(plan)
    return ok(public(member))


@bp.route("/governance/committee-members/<member_id>/end-term", methods=["POST"])
def end_term(member_id):
    authenticate(("PlanSponsorAdmin",))
    member = get_row("members", member_id, "memberId")
    payload = body()
    reason = as_enum(req_field(payload, "end_term_reason"), "end_term_reason",
                     calc.END_TERM_REASONS)
    if member["status"] not in calc.NON_TERMINAL_MEMBER_STATES:
        fail("ERR_INVALID_STATE_TRANSITION", "the appointment has already ended")
    if member["status"] == "APPOINTED" and reason != "REMOVAL_FOR_CAUSE" and \
            reason != "TERM_EXPIRY":
        fail("ERR_INVALID_STATE_TRANSITION",
             "an appointed member may only be removed for cause")
    seat = store.seats.get(member["seat_id"])
    plan = store.plans.get(seat["plan_id"]) if seat else None

    if member["status"] == "ACTIVE":
        for motion in calc.plan_motions(seat["plan_id"] if seat else None):
            if motion["status"] != "OPEN":
                continue
            for entry in motion["votes"]:
                if entry["member_id"] == member["id"]:
                    fail("ERR_OPEN_MOTION_VOTE_LOCK",
                         "the member has voted on a motion that is still open")

    had_acceptance = (member.get("acceptance_signed_at") is not None
                      and member["status"] in ("ACCEPTANCE_PENDING", "ACTIVE"))
    if reason == "RESIGNATION":
        member["status"] = "RESIGNED"
    elif reason == "REMOVAL_FOR_CAUSE":
        member["status"] = "REMOVED"
    else:
        member["status"] = "TERM_EXPIRED"
    member["end_term_reason"] = reason
    touch(member)

    if reason == "REMOVAL_FOR_CAUSE":
        for record in calc.member_records(member["id"]):
            if record["status"] == "ASSIGNED":
                record["status"] = "EXPIRED"
                touch(record)
        calc.refresh_training_status(member)

    if seat is not None and seat["status"] == "FILLED":
        seat["status"] = "VACANT"
        touch(seat)
    if plan is not None:
        if had_acceptance:
            plan["documented_acceptance_count"] = max(
                0, plan.get("documented_acceptance_count", 0) - 1)
        _posture(plan)
    return ok(public(member))


# --------------------------------------------------------------------------- #
# Fiduciary training records
# --------------------------------------------------------------------------- #

def _waive_requested(payload):
    action = payload.get("action")
    if isinstance(action, str) and action.upper() in ("WAIVE", "WAIVED"):
        return True
    if action is None and payload.get("waiver_basis") is not None:
        return True
    return False


@bp.route("/governance/training-records", methods=["POST"])
def create_training_record():
    authenticate(("PlanSponsorAdmin",))
    payload = body()
    refs = resolve_body_refs(payload, {"!member_id": "members"})
    member = refs.get("member_id")
    module = as_enum(req_field(payload, "module_code"), "module_code", calc.MODULES)
    validity = as_int(opt_field(payload, "validity_quarters", 8),
                      "validity_quarters", 1, 20)
    waive = _waive_requested(payload)
    waiver_basis = payload.get("waiver_basis")
    score = payload.get("score_pct")
    if score is not None:
        # The entity types score_pct as an integer while the ladder speaks of an
        # 80.00 floor, so a two-decimal score is accepted and kept integral when
        # it has no fractional part.
        score = as_dec(score, "score_pct", 2, "0.00", "100.00")
        if score == score.to_integral_value():
            score = int(score)
    if waive:
        if waiver_basis is None:
            fail("ERR_INVALID_REQUEST", "waiver_basis is required for a waiver")
        waiver_basis = as_str(waiver_basis, "waiver_basis", 12)
        if module == "FIDUCIARY_DUTIES":
            fail("ERR_MODULE_NOT_WAIVABLE",
                 "the FIDUCIARY_DUTIES module may never be waived")

    plan = store.plans.get(calc.member_plan_id(member))
    fqi = plan["fiscal_quarter_index"] if plan else 0
    for record in calc.member_records(member["id"]):
        if record["module_code"] == module and \
                record["status"] in ("ASSIGNED", "COMPLETED", "WAIVED"):
            fail("ERR_DUPLICATE_RESOURCE",
                 "an open training record already exists for this module")

    record = new_row({
        "member_id": member["id"],
        "module_code": module,
        "status": "WAIVED" if waive else "ASSIGNED",
        "assigned_quarter_index": fqi,
        "completed_quarter_index": fqi if waive else None,
        "score_pct": None if waive else score,
        "waiver_basis": waiver_basis if waive else None,
        "validity_quarters": validity,
    })
    store.training[record["id"]] = record

    if member["status"] == "APPOINTED":
        member["status"] = "TRAINING_ASSIGNED"
    calc.refresh_training_status(member)
    touch(member)
    return ok(public(record), 201)


@bp.route("/governance/training-records", methods=["GET"])
def list_training_records():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "PlanAuditor"))
    rows = filter_rows(list(store.training.values()),
                       [(q_str("member_id"), "member_id"),
                        (q_str("module_code"), "module_code"),
                        (q_str("status"), "status")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/training-records/<record_id>", methods=["GET"])
def get_training_record(record_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "PlanAuditor"))
    return ok(public(get_row("training", record_id, "recordId")))


@bp.route("/governance/training-records/<record_id>/complete", methods=["POST"])
def complete_training_record(record_id):
    actor = authenticate(("PlanSponsorAdmin", "CommitteeMember"))
    record = get_row("training", record_id, "recordId")
    payload = body()
    action = as_enum(opt_field(payload, "action", "COMPLETED"), "action",
                     ("COMPLETED", "WAIVED"))
    score = payload.get("score_pct")
    if score is not None:
        # The entity types score_pct as an integer while the ladder speaks of an
        # 80.00 floor, so a two-decimal score is accepted and kept integral when
        # it has no fractional part.
        score = as_dec(score, "score_pct", 2, "0.00", "100.00")
        if score == score.to_integral_value():
            score = int(score)
    waiver_basis = payload.get("waiver_basis")
    if action == "WAIVED":
        if waiver_basis is None:
            fail("ERR_INVALID_REQUEST", "waiver_basis is required for a waiver")
        waiver_basis = as_str(waiver_basis, "waiver_basis", 12)

    if record["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE_TRANSITION", "the training record is not ASSIGNED")

    member = store.members.get(record["member_id"])
    if action == "COMPLETED":
        if actor.user_id != record["member_id"]:
            fail("ERR_ACTOR_NOT_SELF",
                 "a member may only complete their own training record")
        if score is None or score < 80:
            fail("ERR_TRAINING_SCORE_INSUFFICIENT",
                 "a completed module requires a score of at least 80")
    else:
        if record["module_code"] == "FIDUCIARY_DUTIES":
            fail("ERR_MODULE_NOT_WAIVABLE",
                 "the FIDUCIARY_DUTIES module may never be waived")

    plan = store.plans.get(calc.member_plan_id(member)) if member else None
    fqi = plan["fiscal_quarter_index"] if plan else 0
    record["status"] = action
    record["completed_quarter_index"] = fqi
    if action == "COMPLETED":
        record["score_pct"] = score
    else:
        record["score_pct"] = None
        record["waiver_basis"] = waiver_basis
    touch(record)
    if member is not None:
        before = member["fiduciary_training_status"]
        calc.refresh_training_status(member)
        if member["fiduciary_training_status"] != before:
            touch(member)
    return ok(public(record))
