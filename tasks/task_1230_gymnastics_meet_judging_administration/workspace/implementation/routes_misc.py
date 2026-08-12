"""Routes: awards, spectator tickets, qualification records, live scores, clock."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from common import (AWARD_CATEGORIES, CATEGORY_INDEX, ApiError, DB,
                    TICKET_CLASSES, apply_filters, authorize, body, enum_val,
                    get_or_404, meet_of_session, new_entity, now, ok_array,
                    ok_list, ok_object, parse_dt, req_enum, req_int, req_str,
                    required, set_clock, sort_items, touch)
from logic import (compute_award_ordering, rank_groups,
                   run_system_transitions, session_entries, session_scores)
from serialize import (ser_award, ser_qual_record, ser_score, ser_ticket)

bp = Blueprint("misc", __name__)

AWARD_READ = ["MeetDirector", "MeetReferee", "Coach", "Spectator"]
TICKET_READ_MEET = ["MeetDirector", "GateAttendant"]
QUAL_READ = ["MeetDirector", "MeetReferee", "Coach"]
TICKET_TERMINAL = ("REDEEMED", "REFUNDED", "VOID")
QUAL_TERMINAL = ("CONFIRMED", "DECLINED", "REVOKED")


# ----------------------------------------------------------------------------
# Awards
# ----------------------------------------------------------------------------

@bp.get("/api/v1/sessions/<sid>/awards")
def list_session_awards(sid):
    authorize(AWARD_READ)
    get_or_404(DB.sessions, sid, "Session")
    items = apply_filters(
        sort_items(a for a in DB.awards.values() if a["session_id"] == sid),
        {"category": ("str", "category"), "place": ("int", "place")})
    return ok_list([ser_award(a) for a in items])


@bp.get("/api/v1/athlete-entries/<eid>/awards")
def list_entry_awards(eid):
    authorize(AWARD_READ)
    get_or_404(DB.entries, eid, "AthleteEntry")
    items = sort_items(a for a in DB.awards.values()
                       if a["athlete_entry_id"] == eid)
    return ok_list([ser_award(a) for a in items])


@bp.get("/api/v1/awards/<aid>")
def get_award(aid):
    authorize(AWARD_READ)
    return ok_object(ser_award(get_or_404(DB.awards, aid, "Award")))


@bp.post("/api/v1/sessions/<sid>/awards/generate")
def generate_awards(sid):
    authorize(["MeetDirector"])
    session = get_or_404(DB.sessions, sid, "Session")
    data = body()
    depth = req_int(data, "award_depth_per_category")
    if depth < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "award_depth_per_category must be >= 1")
    if session["state"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Session state is %s, expected CLOSED" % session["state"])
    if any(a["session_id"] == sid for a in DB.awards.values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Awards have already been generated for this session")

    compute_award_ordering(session)
    meet = meet_of_session(session)
    policy = meet["tiebreak_policy"] if meet else "USAG_CLASSIC"
    created = []

    for apparatus in ("VAULT", "UNEVEN_BARS", "BALANCE_BEAM", "FLOOR_EXERCISE"):
        scores = [s for s in session_scores(sid)
                  if s["apparatus"] == apparatus and s["score_state"] == "FINAL"]
        if policy == "USAG_CLASSIC":
            ordered = sorted(scores,
                             key=lambda s: (s["tiebreak_rank"], s["created_at"],
                                            s["_seq"]))
        else:
            ordered = sorted(scores,
                             key=lambda s: (s["tiebreak_rank"], s["created_at"],
                                            s["_seq"]))
        # was_tiebroken: recipient is part of a tied group separated by the chain
        by_total = {}
        for s in scores:
            by_total.setdefault(s["final_total"], []).append(s)
        for s in scores:
            group = by_total[s["final_total"]]
            ranks_in_group = {g["tiebreak_rank"] for g in group}
            s["_was_tiebroken"] = len(group) > 1 and len(ranks_in_group) > 1
        for s in ordered:
            if s["tiebreak_rank"] is None or s["tiebreak_rank"] > depth:
                continue
            a = new_entity()
            a.update({
                "session_id": sid,
                "category": apparatus,
                "place": s["tiebreak_rank"],
                "athlete_entry_id": s["athlete_entry_id"],
                "awarded_at": now(),
                "ceremony_order": None,
                "was_tiebroken": bool(s.get("_was_tiebroken")),
            })
            DB.awards[a["id"]] = a
            created.append(a)

    # All-around category
    entries = [e for e in session_entries(sid) if e["entry_status"] == "COMPLETED"]
    ordered_entries = sorted(entries,
                             key=lambda e: (-(e["all_around_total"] or Decimal("0")),
                                            e["created_at"], e["_seq"]))
    aa_ranks = rank_groups(ordered_entries, lambda e: e["all_around_total"])
    for e in ordered_entries:
        rank = aa_ranks[e["id"]]
        if rank > depth:
            continue
        a = new_entity()
        a.update({
            "session_id": sid,
            "category": "ALL_AROUND",
            "place": rank,
            "athlete_entry_id": e["id"],
            "awarded_at": now(),
            "ceremony_order": None,
            "was_tiebroken": False,
        })
        DB.awards[a["id"]] = a
        created.append(a)

    # Ceremony ordering: category_index * 100 + (max_place - place + 1)
    for category in AWARD_CATEGORIES:
        cat_awards = [a for a in created if a["category"] == category]
        if not cat_awards:
            continue
        max_place = max(a["place"] for a in cat_awards)
        for a in cat_awards:
            a["ceremony_order"] = CATEGORY_INDEX[category] * 100 \
                + (max_place - a["place"] + 1)

    created.sort(key=lambda a: (a["ceremony_order"], a["created_at"], a["_seq"]))
    return ok_array([ser_award(a) for a in created], 201)


# ----------------------------------------------------------------------------
# Spectator tickets
# ----------------------------------------------------------------------------

@bp.post("/api/v1/meets/<mid>/sessions/<sid>/spectator-tickets")
def create_ticket(mid, sid):
    authorize(["MeetDirector", "GateAttendant"])
    get_or_404(DB.meets, mid, "Meet")
    session = get_or_404(DB.sessions, sid, "Session")
    if session["meet_id"] != mid:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404,
                       "Session %s does not belong to meet %s" % (sid, mid))
    data = body()
    holder_name = req_str(data, "holder_name")
    holder_email = req_str(data, "holder_email").lower()
    ticket_class = req_enum(data, "ticket_class", TICKET_CLASSES)
    price_cents = req_int(data, "price_cents")
    seat_section = data.get("seat_section")
    if seat_section is not None and not isinstance(seat_section, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "seat_section must be a string")
    for t in DB.tickets.values():
        if t["session_id"] == sid and t["holder_email"] == holder_email \
                and t["ticket_state"] != "VOID":
            raise ApiError("ERR_TICKET_DUPLICATE_EMAIL", 409,
                           "A non-VOID ticket already exists for this email in "
                           "this session")
    if ticket_class == "COMP":
        if price_cents != 0:
            raise ApiError("ERR_TICKET_PRICE_MISMATCH", 422,
                           "COMP tickets must have price_cents == 0")
    elif price_cents <= 0:
        raise ApiError("ERR_TICKET_PRICE_MISMATCH", 422,
                       "Non-COMP tickets must have a positive price_cents")
    if ticket_class in ("RESERVED", "VIP"):
        if not seat_section:
            raise ApiError("ERR_TICKET_SEAT_SECTION_INVALID", 422,
                           "RESERVED/VIP tickets require a seat_section")
    elif seat_section is not None:
        raise ApiError("ERR_TICKET_SEAT_SECTION_INVALID", 422,
                       "GENERAL_ADMISSION/COMP tickets must not have a "
                       "seat_section")
    t = new_entity()
    t.update({
        "meet_id": mid,
        "session_id": sid,
        "holder_name": holder_name,
        "holder_email": holder_email,
        "ticket_class": ticket_class,
        "seat_section": seat_section,
        "price_cents": price_cents,
        "ticket_state": "ISSUED",
        "scanned_at": None,
        "redeemed_at": None,
    })
    DB.tickets[t["id"]] = t
    return ok_object(ser_ticket(t), 201)


@bp.get("/api/v1/meets/<mid>/spectator-tickets")
def list_meet_tickets(mid):
    authorize(TICKET_READ_MEET)
    get_or_404(DB.meets, mid, "Meet")
    items = apply_filters(
        sort_items(t for t in DB.tickets.values() if t["meet_id"] == mid),
        {"ticket_state": ("str", "ticket_state"),
         "ticket_class": ("str", "ticket_class")})
    return ok_list([ser_ticket(t) for t in items])


@bp.get("/api/v1/sessions/<sid>/spectator-tickets")
def list_session_tickets(sid):
    authorize(TICKET_READ_MEET)
    get_or_404(DB.sessions, sid, "Session")
    items = sort_items(t for t in DB.tickets.values() if t["session_id"] == sid)
    return ok_list([ser_ticket(t) for t in items])


@bp.get("/api/v1/spectator-tickets/<tid>")
def get_ticket(tid):
    authorize(TICKET_READ_MEET)
    return ok_object(ser_ticket(get_or_404(DB.tickets, tid, "SpectatorTicket")))


def _ticket_context(ticket):
    session = DB.sessions.get(ticket["session_id"])
    meet = DB.meets.get(ticket["meet_id"])
    return session, meet


@bp.post("/api/v1/spectator-tickets/<tid>/scan")
def scan_ticket(tid):
    authorize(["GateAttendant"])
    ticket = get_or_404(DB.tickets, tid, "SpectatorTicket")
    session, meet = _ticket_context(ticket)
    if meet is not None and meet["posture"] not in ("WARMUP_OPEN",
                                                    "IN_COMPETITION"):
        raise ApiError("ERR_MEET_POSTURE_FORBIDS", 409,
                       "Meet posture %s forbids scanning" % meet["posture"])
    if ticket["ticket_state"] in TICKET_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Ticket is in terminal state %s" % ticket["ticket_state"])
    if ticket["ticket_state"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Ticket state is %s, expected ISSUED"
                       % ticket["ticket_state"])
    t = now()
    if session is not None and not (
            session["scheduled_start"] - timedelta(hours=2) <= t
            <= session["scheduled_end"]):
        raise ApiError("ERR_TICKET_OUTSIDE_SCAN_WINDOW", 422,
                       "Scan is outside the admission window")
    ticket["ticket_state"] = "SCANNED"
    ticket["scanned_at"] = now()
    touch(ticket)
    return ok_object(ser_ticket(ticket))


@bp.post("/api/v1/spectator-tickets/<tid>/redeem")
def redeem_ticket(tid):
    authorize(["GateAttendant"])
    ticket = get_or_404(DB.tickets, tid, "SpectatorTicket")
    if ticket["ticket_state"] in TICKET_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Ticket is in terminal state %s" % ticket["ticket_state"])
    if ticket["ticket_state"] != "SCANNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Ticket state is %s, expected SCANNED"
                       % ticket["ticket_state"])
    ticket["ticket_state"] = "REDEEMED"
    ticket["redeemed_at"] = now()
    touch(ticket)
    return ok_object(ser_ticket(ticket))


@bp.post("/api/v1/spectator-tickets/<tid>/refund")
def refund_ticket(tid):
    authorize(["MeetDirector"])
    ticket = get_or_404(DB.tickets, tid, "SpectatorTicket")
    session, meet = _ticket_context(ticket)
    if ticket["ticket_state"] in TICKET_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Ticket is in terminal state %s" % ticket["ticket_state"])
    if ticket["ticket_state"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Ticket state is %s, expected ISSUED"
                       % ticket["ticket_state"])
    if session is not None and now() >= session["scheduled_start"]:
        raise ApiError("ERR_REFUND_WINDOW_CLOSED", 422,
                       "Refunds are not permitted after doors open")
    ticket["ticket_state"] = "REFUNDED"
    touch(ticket)
    return ok_object(ser_ticket(ticket))


@bp.post("/api/v1/spectator-tickets/<tid>/void")
def void_ticket(tid):
    authorize(["MeetDirector"])
    ticket = get_or_404(DB.tickets, tid, "SpectatorTicket")
    session, meet = _ticket_context(ticket)
    if meet is not None and meet["posture"] != "DRAFT":
        raise ApiError("ERR_MEET_POSTURE_FORBIDS", 409,
                       "Tickets may only be voided while the meet is DRAFT")
    if ticket["ticket_state"] in TICKET_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Ticket is in terminal state %s" % ticket["ticket_state"])
    if ticket["ticket_state"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Ticket state is %s, expected ISSUED"
                       % ticket["ticket_state"])
    ticket["ticket_state"] = "VOID"
    touch(ticket)
    return ok_object(ser_ticket(ticket))


# ----------------------------------------------------------------------------
# Qualification records
# ----------------------------------------------------------------------------

@bp.get("/api/v1/athlete-entries/<eid>/qualification-records")
def list_entry_qual_records(eid):
    authorize(QUAL_READ)
    get_or_404(DB.entries, eid, "AthleteEntry")
    items = apply_filters(
        sort_items(r for r in DB.qual_records.values()
                   if r["athlete_entry_id"] == eid),
        {"qualification_state": ("str", "qualification_state")})
    return ok_list([ser_qual_record(r) for r in items])


@bp.get("/api/v1/qualification-records/<rid>")
def get_qual_record(rid):
    authorize(QUAL_READ)
    return ok_object(ser_qual_record(
        get_or_404(DB.qual_records, rid, "QualificationRecord")))


@bp.post("/api/v1/qualification-records/<rid>/confirm")
def confirm_qual_record(rid):
    authorize(["MeetDirector"])
    rec = get_or_404(DB.qual_records, rid, "QualificationRecord")
    if rec["qualification_state"] in QUAL_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "QualificationRecord is in terminal state %s"
                       % rec["qualification_state"])
    if rec["qualification_state"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "QualificationRecord state is %s, expected PROVISIONAL"
                       % rec["qualification_state"])
    entry = DB.entries.get(rec["athlete_entry_id"])
    if entry is None or entry["entry_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Parent AthleteEntry is not COMPLETED")
    session = DB.sessions.get(entry["session_id"])
    meet = DB.meets.get(session["meet_id"]) if session else None
    if meet is None or meet["posture"] not in ("SCORING_CLOSED", "FINALIZED"):
        raise ApiError("ERR_MEET_POSTURE_FORBIDS", 409,
                       "Meet posture %s forbids qualification confirmation"
                       % (meet["posture"] if meet else "unknown"))
    rec["qualification_state"] = "CONFIRMED"
    rec["confirmed_at"] = now()
    touch(rec)
    return ok_object(ser_qual_record(rec))


@bp.post("/api/v1/qualification-records/<rid>/decline")
def decline_qual_record(rid):
    uid, _ = authorize(["Coach"])
    rec = get_or_404(DB.qual_records, rid, "QualificationRecord")
    if rec["qualification_state"] in QUAL_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "QualificationRecord is in terminal state %s"
                       % rec["qualification_state"])
    if rec["qualification_state"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "QualificationRecord state is %s, expected PROVISIONAL"
                       % rec["qualification_state"])
    entry = DB.entries.get(rec["athlete_entry_id"])
    session = DB.sessions.get(entry["session_id"]) if entry else None
    meet = DB.meets.get(session["meet_id"]) if session else None
    has_pass = meet is not None and any(
        p["coach_id"] == uid and p["meet_id"] == meet["id"]
        and p["pass_state"] == "FLOOR_ACCESS_GRANTED"
        for p in DB.passes.values())
    if not has_pass:
        raise ApiError("ERR_COACH_CREDENTIAL_LAPSED", 422,
                       "Coach does not hold floor access on this meet")
    coach = DB.coaches.get(uid)
    gymnast = DB.gymnasts.get(entry["gymnast_id"]) if entry else None
    if coach is None or gymnast is None \
            or coach["affiliated_gym"] != gymnast["home_gym"]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Coach gym does not match gymnast home_gym")
    rec["qualification_state"] = "DECLINED"
    touch(rec)
    return ok_object(ser_qual_record(rec))


@bp.post("/api/v1/qualification-records/<rid>/revoke")
def revoke_qual_record(rid):
    authorize(["MeetDirector"])
    rec = get_or_404(DB.qual_records, rid, "QualificationRecord")
    if rec["qualification_state"] in ("DECLINED", "REVOKED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "QualificationRecord is in terminal state %s"
                       % rec["qualification_state"])
    if rec["qualification_state"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "QualificationRecord state is %s, expected CONFIRMED"
                       % rec["qualification_state"])
    rec["qualification_state"] = "REVOKED"
    touch(rec)
    return ok_object(ser_qual_record(rec))


# ----------------------------------------------------------------------------
# Live scoring read model
# ----------------------------------------------------------------------------

@bp.get("/api/v1/sessions/<sid>/live-scores")
def live_scores(sid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief", "Coach",
               "Spectator"])
    get_or_404(DB.sessions, sid, "Session")
    items = sort_items(
        s for s in session_scores(sid)
        if s["score_state"] in ("PUBLISHED", "FINAL"))
    return ok_list([ser_score(s) for s in items])


# ----------------------------------------------------------------------------
# Administrative logical clock
# ----------------------------------------------------------------------------

@bp.post("/api/v1/_clock/set_current_utc")
def set_clock_endpoint():
    authorize(["MeetDirector"])
    data = body()
    target = parse_dt(required(data, "to_iso8601"), "to_iso8601")
    set_clock(target)
    run_system_transitions()
    return ok_object({}, 200)
