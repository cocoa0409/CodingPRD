"""Routes: events, RSVPs, sales-center appointments, residents, notices, board seats."""
from datetime import timedelta

from flask import Blueprint

from core import (
    DB, actor, require_roles, body, check_no_undeclared, req_string, req_int,
    req_enum, opt_int, opt_id, req_datetime, opt_datetime, validation, err,
    invalid_state, new_entity, touch, get_or_404, check_body_fk, ok_object,
    filter_args, EVENT_LEAD_DAYS, ELECTION_WINDOW_DAYS, QUORUM_PCT,
    MAX_CONCURRENT_TOURS, VENUE_TO_AMENITY, TOTAL_SEATS,
)
from serializers import (
    event_out, rsvp_out, appointment_out, resident_out, notice_out,
    board_seat_out, event_confirmed_count,
)
from routes_core import paginate_pairs

bp = Blueprint("lifestyle", __name__)

LC = ["LifestyleCoordinator"]

VENUES = {"CLUBHOUSE", "POOL_DECK", "EVENT_LAWN", "SALES_CENTER"}
NOTICE_TYPES = {"ASSESSMENT_CHANGE", "TRANSITION_UPDATE", "AMENITY_DELINQUENCY",
                "GENERAL_MEETING", "BUDGET_ADOPTION"}


# ---------------------------------------------------------------------------
# Community events
# ---------------------------------------------------------------------------
@bp.route("/mpc/events", methods=["POST"])
def create_event():
    _, role = actor()
    require_roles(role, LC)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    budget = check_body_fk("budget", DB.budgets, data.get("charged_budget_id"))
    check_no_undeclared(data, {"community_id", "title", "venue", "start_at",
                               "end_at", "capacity", "cost_cents",
                               "charged_budget_id"})
    req_string(data, "community_id")
    title = req_string(data, "title")
    venue = req_enum(data, "venue", VENUES)
    start = req_datetime(data, "start_at")
    end = req_datetime(data, "end_at")
    capacity = req_int(data, "capacity", minimum=1)
    cost = opt_int(data, "cost_cents", 0, minimum=0)
    charged = opt_id(data, "charged_budget_id")
    if end <= start:
        validation("end_at must be strictly after start_at")
    if cost > 0 and charged is None:
        validation("charged_budget_id is required when cost_cents > 0")
    e = new_entity()
    e.update({
        "community_id": community["id"],
        "title": title,
        "venue": venue,
        "start_at": start,
        "end_at": end,
        "capacity": capacity,
        "cost_cents": cost,
        "charged_budget_id": charged,
        "status": "PROPOSED",
    })
    DB.events[e["id"]] = e
    return ok_object(event_out(e), 201)


@bp.route("/mpc/events", methods=["GET"])
def list_events():
    actor()
    f = filter_args(["community_id", "charged_budget_id"])
    raw = [e for e in DB.events.values()
           if f.get("community_id") in (None, e["community_id"])
           and f.get("charged_budget_id") in (None, e["charged_budget_id"])]
    return paginate_pairs(raw, event_out)


@bp.route("/mpc/events/<eid>", methods=["GET"])
def get_event(eid):
    actor()
    e = get_or_404("event", DB.events, eid)
    return ok_object(event_out(e))


@bp.route("/mpc/events/<eid>/schedule", methods=["POST"])
def schedule_event(eid):
    _, role = actor()
    require_roles(role, LC)
    e = get_or_404("event", DB.events, eid)
    data = body()
    check_no_undeclared(data, set())
    if e["status"] != "PROPOSED":
        invalid_state("Event is not PROPOSED")
    # Business safety: amenity posture gate.
    mapped = VENUE_TO_AMENITY.get(e["venue"])
    if mapped is not None:
        ok = any(
            a["community_id"] == e["community_id"]
            and a["amenity_type"] == mapped
            and a["status"] in ("UNDER_CONSTRUCTION", "OPEN")
            for a in DB.amenities.values()
        )
        if not ok:
            err("ERR_AMENITY_NOT_OPEN", 409,
                "Mapped amenity must be UNDER_CONSTRUCTION or OPEN")
    # Temporal gate: lead time.
    now = DB.now()
    if e["start_at"] < now + timedelta(days=EVENT_LEAD_DAYS):
        err("ERR_EVENT_LEAD_TIME", 422,
            "Event start_at is before logical clock + 14 days")
    # Overlap gate: half-open [start_at, end_at) overlap at the same venue.
    for other in DB.events.values():
        if (other["id"] != e["id"] and other["status"] == "SCHEDULED"
                and other["community_id"] == e["community_id"]
                and other["venue"] == e["venue"]
                and other["start_at"] < e["end_at"]
                and e["start_at"] < other["end_at"]):
            err("ERR_VENUE_OVERLAP", 409,
                "Another SCHEDULED event occupies the venue")
    # Fiscal gate.
    if e["cost_cents"] > 0:
        budget = DB.budgets.get(e["charged_budget_id"]) if e["charged_budget_id"] else None
        if budget is None or budget["status"] != "ADOPTED":
            err("ERR_EVENT_BUDGET_EXCEEDED", 402,
                "Charged budget must be ADOPTED")
        line = sum(li["amount_cents"] for li in DB.line_items.values()
                   if li["budget_id"] == budget["id"]
                   and li["category"] == "EVENTS_PROGRAMMING")
        committed = sum(ev["cost_cents"] for ev in DB.events.values()
                        if ev["charged_budget_id"] == budget["id"]
                        and ev["status"] in ("SCHEDULED", "COMPLETED"))
        remaining = line - committed
        if e["cost_cents"] > remaining:
            err("ERR_EVENT_BUDGET_EXCEEDED", 402,
                "Event cost exceeds the remaining EVENTS_PROGRAMMING line")
    e["status"] = "SCHEDULED"
    touch(e)
    return ok_object(event_out(e))


def _cancel_event_rsvps(event_id):
    for r in DB.rsvps.values():
        if r["event_id"] == event_id and r["status"] in ("CONFIRMED", "WAITLISTED"):
            r["status"] = "CANCELLED"
            touch(r)


@bp.route("/mpc/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    _, role = actor()
    require_roles(role, LC)
    e = get_or_404("event", DB.events, eid)
    data = body()
    check_no_undeclared(data, set())
    if e["status"] not in ("PROPOSED", "SCHEDULED"):
        invalid_state("Event is not PROPOSED or SCHEDULED")
    e["status"] = "CANCELLED"
    touch(e)
    _cancel_event_rsvps(e["id"])
    return ok_object(event_out(e))


# ---------------------------------------------------------------------------
# Event RSVPs
# ---------------------------------------------------------------------------
@bp.route("/mpc/rsvps", methods=["POST"])
def create_rsvp():
    user_id, role = actor()
    require_roles(role, ["HomeownerResident"])
    data = body()
    event = check_body_fk("event", DB.events, data.get("event_id"))
    resident = check_body_fk("resident", DB.residents, data.get("resident_id"))
    check_no_undeclared(data, {"event_id", "resident_id", "party_size"})
    req_string(data, "event_id")
    rid = req_string(data, "resident_id")
    if rid != user_id:
        err("ERR_FORBIDDEN_ROLE", 403,
            "X-User-ID must equal resident_id")
    party = req_int(data, "party_size", minimum=1)
    if event["status"] != "SCHEDULED":
        invalid_state("Event is not SCHEDULED")
    confirmed = event_confirmed_count(event["id"])
    fits = confirmed + party <= event["capacity"]
    r = new_entity()
    r.update({
        "event_id": event["id"],
        "resident_id": resident["id"],
        "party_size": party,
        "status": "CONFIRMED" if fits else "WAITLISTED",
    })
    DB.rsvps[r["id"]] = r
    return ok_object(rsvp_out(r), 201)


@bp.route("/mpc/rsvps", methods=["GET"])
def list_rsvps():
    actor()
    f = filter_args(["event_id", "resident_id"])
    raw = [r for r in DB.rsvps.values()
           if f.get("event_id") in (None, r["event_id"])
           and f.get("resident_id") in (None, r["resident_id"])]
    return paginate_pairs(raw, rsvp_out)


@bp.route("/mpc/rsvps/<rid>", methods=["GET"])
def get_rsvp(rid):
    actor()
    r = get_or_404("rsvp", DB.rsvps, rid)
    return ok_object(rsvp_out(r))


@bp.route("/mpc/rsvps/<rid>/cancel", methods=["POST"])
def cancel_rsvp(rid):
    user_id, role = actor()
    require_roles(role, ["HomeownerResident", "LifestyleCoordinator"])
    r = get_or_404("rsvp", DB.rsvps, rid)
    data = body()
    check_no_undeclared(data, set())
    if role == "HomeownerResident" and r["resident_id"] != user_id:
        err("ERR_FORBIDDEN_ROLE", 403,
            "Only the booking resident may cancel this RSVP")
    if r["status"] not in ("CONFIRMED", "WAITLISTED"):
        invalid_state("RSVP is not CONFIRMED or WAITLISTED")
    was_confirmed = r["status"] == "CONFIRMED"
    r["status"] = "CANCELLED"
    touch(r)
    if was_confirmed:
        # Strict head-of-line waitlist promotion: exactly one promotion,
        # only if the earliest-created WAITLISTED rsvp fits.
        event = DB.events.get(r["event_id"])
        if event is not None:
            waiting = sorted(
                (x for x in DB.rsvps.values()
                 if x["event_id"] == event["id"] and x["status"] == "WAITLISTED"),
                key=lambda x: x["created_at"],
            )
            if waiting:
                head = waiting[0]
                confirmed = event_confirmed_count(event["id"])
                if confirmed + head["party_size"] <= event["capacity"]:
                    head["status"] = "CONFIRMED"
                    touch(head)
    return ok_object(rsvp_out(r))


# ---------------------------------------------------------------------------
# Sales-center appointments
# ---------------------------------------------------------------------------
@bp.route("/mpc/appointments", methods=["POST"])
def create_appointment():
    _, role = actor()
    require_roles(role, LC)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    check_no_undeclared(data, {"community_id", "agent_name", "visitor_name",
                               "start_at", "end_at"})
    req_string(data, "community_id")
    agent = req_string(data, "agent_name")
    visitor = req_string(data, "visitor_name")
    start = req_datetime(data, "start_at")
    end = req_datetime(data, "end_at")
    if end <= start:
        validation("end_at must be strictly after start_at")
    overlapping = sum(
        1 for a in DB.appointments.values()
        if a["community_id"] == community["id"] and a["status"] == "BOOKED"
        and a["start_at"] < end and start < a["end_at"]
    )
    if overlapping >= MAX_CONCURRENT_TOURS:
        err("ERR_TOUR_CAPACITY_REACHED", 409,
            "A fourth overlapping BOOKED tour would exceed the capacity")
    a = new_entity()
    a.update({
        "community_id": community["id"],
        "agent_name": agent,
        "visitor_name": visitor,
        "start_at": start,
        "end_at": end,
        "status": "BOOKED",
    })
    DB.appointments[a["id"]] = a
    return ok_object(appointment_out(a), 201)


@bp.route("/mpc/appointments", methods=["GET"])
def list_appointments():
    actor()
    f = filter_args(["community_id"])
    raw = [a for a in DB.appointments.values()
           if f.get("community_id") in (None, a["community_id"])]
    return paginate_pairs(raw, appointment_out)


@bp.route("/mpc/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    actor()
    a = get_or_404("appointment", DB.appointments, aid)
    return ok_object(appointment_out(a))


@bp.route("/mpc/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    _, role = actor()
    require_roles(role, LC)
    a = get_or_404("appointment", DB.appointments, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] != "BOOKED":
        invalid_state("Appointment is not BOOKED")
    a["status"] = "CANCELLED"
    touch(a)
    return ok_object(appointment_out(a))


@bp.route("/mpc/appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    _, role = actor()
    require_roles(role, LC)
    a = get_or_404("appointment", DB.appointments, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] != "BOOKED":
        invalid_state("Appointment is not BOOKED")
    a["status"] = "COMPLETED"
    touch(a)
    return ok_object(appointment_out(a))


# ---------------------------------------------------------------------------
# Residents
# ---------------------------------------------------------------------------
@bp.route("/mpc/residents", methods=["POST"])
def create_resident():
    _, role = actor()
    require_roles(role, LC)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    check_no_undeclared(data, {"community_id", "full_name", "email"})
    req_string(data, "community_id")
    name = req_string(data, "full_name")
    email = req_string(data, "email")
    for r in DB.residents.values():
        if r["community_id"] == community["id"] and r["email"] == email:
            validation("email must be unique within the community")
    r = new_entity()
    r.update({
        "community_id": community["id"],
        "lot_id": None,
        "full_name": name,
        "email": email,
        "owner_since": None,
        "status": "PROSPECT",
    })
    DB.residents[r["id"]] = r
    return ok_object(resident_out(r), 201)


@bp.route("/mpc/residents", methods=["GET"])
def list_residents():
    actor()
    f = filter_args(["community_id", "lot_id"])
    raw = [r for r in DB.residents.values()
           if f.get("community_id") in (None, r["community_id"])
           and f.get("lot_id") in (None, r["lot_id"])]
    return paginate_pairs(raw, resident_out)


@bp.route("/mpc/residents/<rid>", methods=["GET"])
def get_resident(rid):
    actor()
    r = get_or_404("resident", DB.residents, rid)
    return ok_object(resident_out(r))


@bp.route("/mpc/residents/<rid>/record-purchase", methods=["POST"])
def record_purchase(rid):
    _, role = actor()
    require_roles(role, LC)
    r = get_or_404("resident", DB.residents, rid)
    data = body()
    lot = check_body_fk("lot", DB.lots, data.get("lot_id"))
    check_no_undeclared(data, {"lot_id"})
    req_string(data, "lot_id")
    if r["status"] != "PROSPECT":
        invalid_state("Resident is not PROSPECT")
    if lot["status"] not in ("UNDER_CONTRACT", "CLOSED"):
        err("ERR_LOT_NOT_UNDER_CONTRACT", 409,
            "Lot must be UNDER_CONTRACT or CLOSED")
    if lot["community_id"] != r["community_id"]:
        err("ERR_RESIDENT_COMMUNITY_MISMATCH", 422,
            "Lot belongs to a different community than the resident")
    r["status"] = "PURCHASER"
    r["lot_id"] = lot["id"]
    touch(r)
    return ok_object(resident_out(r))


@bp.route("/mpc/residents/<rid>/archive", methods=["POST"])
def archive_resident(rid):
    _, role = actor()
    require_roles(role, LC)
    r = get_or_404("resident", DB.residents, rid)
    data = body()
    check_no_undeclared(data, set())
    if r["status"] not in ("PROSPECT", "PURCHASER", "OWNER"):
        invalid_state("Resident cannot be archived from its state")
    r["status"] = "FORMER"
    touch(r)
    return ok_object(resident_out(r))


# ---------------------------------------------------------------------------
# Resident notices
# ---------------------------------------------------------------------------
@bp.route("/mpc/notices", methods=["POST"])
def create_notice():
    _, role = actor()
    require_roles(role, LC)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    budget = check_body_fk("budget", DB.budgets, data.get("budget_id"))
    rate = check_body_fk("rate", DB.rates, data.get("assessment_rate_id"))
    check_no_undeclared(data, {"community_id", "notice_type", "subject", "body",
                               "send_at", "effective_date", "budget_id",
                               "assessment_rate_id"})
    req_string(data, "community_id")
    ntype = req_enum(data, "notice_type", NOTICE_TYPES)
    subject = req_string(data, "subject")
    body_text = req_string(data, "body")
    send_at = req_datetime(data, "send_at")
    effective = opt_datetime(data, "effective_date", None)
    n = new_entity()
    n.update({
        "community_id": community["id"],
        "notice_type": ntype,
        "subject": subject,
        "body": body_text,
        "send_at": send_at,
        "sent_at": None,
        "effective_date": effective,
        "budget_id": budget["id"] if budget else None,
        "assessment_rate_id": rate["id"] if rate else None,
        "supersedes_notice_id": None,
        "status": "DRAFT",
    })
    DB.notices[n["id"]] = n
    return ok_object(notice_out(n), 201)


@bp.route("/mpc/notices", methods=["GET"])
def list_notices():
    actor()
    f = filter_args(["community_id", "budget_id", "assessment_rate_id",
                     "supersedes_notice_id"])
    raw = [n for n in DB.notices.values()
           if f.get("community_id") in (None, n["community_id"])
           and f.get("budget_id") in (None, n["budget_id"])
           and f.get("assessment_rate_id") in (None, n["assessment_rate_id"])
           and f.get("supersedes_notice_id") in (None, n["supersedes_notice_id"])]
    return paginate_pairs(raw, notice_out)


@bp.route("/mpc/notices/<nid>", methods=["GET"])
def get_notice(nid):
    actor()
    n = get_or_404("notice", DB.notices, nid)
    return ok_object(notice_out(n))


@bp.route("/mpc/notices/<nid>/schedule", methods=["POST"])
def schedule_notice(nid):
    _, role = actor()
    require_roles(role, LC)
    n = get_or_404("notice", DB.notices, nid)
    data = body()
    check_no_undeclared(data, set())
    if n["notice_type"] == "BUDGET_ADOPTION" and not n["budget_id"]:
        validation("BUDGET_ADOPTION notices require budget_id")
    if n["notice_type"] == "ASSESSMENT_CHANGE" and not n["assessment_rate_id"]:
        validation("ASSESSMENT_CHANGE notices require assessment_rate_id")
    if n["status"] != "DRAFT":
        invalid_state("Notice is not DRAFT")
    if n["send_at"] <= DB.now():
        err("ERR_SEND_AT_IN_PAST", 422,
            "send_at must be strictly after the logical clock")
    n["status"] = "SCHEDULED"
    touch(n)
    return ok_object(notice_out(n))


@bp.route("/mpc/notices/<nid>/cancel", methods=["POST"])
def cancel_notice(nid):
    _, role = actor()
    require_roles(role, LC)
    n = get_or_404("notice", DB.notices, nid)
    data = body()
    check_no_undeclared(data, set())
    if n["status"] not in ("DRAFT", "SCHEDULED"):
        invalid_state("Notice is not DRAFT or SCHEDULED")
    n["status"] = "CANCELLED"
    touch(n)
    return ok_object(notice_out(n))


@bp.route("/mpc/notices/<nid>/supersede", methods=["POST"])
def supersede_notice(nid):
    _, role = actor()
    require_roles(role, LC)
    n = get_or_404("notice", DB.notices, nid)
    data = body()
    check_no_undeclared(data, {"subject", "body", "send_at", "effective_date"})
    subject = req_string(data, "subject")
    body_text = req_string(data, "body")
    send_at = req_datetime(data, "send_at")
    effective = opt_datetime(data, "effective_date", None)
    if n["status"] not in ("DRAFT", "SCHEDULED", "SENT"):
        invalid_state("Notice cannot be superseded from its state")
    n["status"] = "SUPERSEDED"
    touch(n)
    succ = new_entity()
    succ.update({
        "community_id": n["community_id"],
        "notice_type": n["notice_type"],
        "subject": subject,
        "body": body_text,
        "send_at": send_at,
        "sent_at": None,
        "effective_date": effective,
        "budget_id": n["budget_id"],
        "assessment_rate_id": n["assessment_rate_id"],
        "supersedes_notice_id": n["id"],
        "status": "DRAFT",
    })
    DB.notices[succ["id"]] = succ
    return ok_object(notice_out(succ), 201)


# ---------------------------------------------------------------------------
# Board seats
# ---------------------------------------------------------------------------
@bp.route("/mpc/board-seats", methods=["GET"])
def list_board_seats():
    actor()
    f = filter_args(["community_id", "holder_resident_id"])
    raw = [s for s in DB.board_seats.values()
           if f.get("community_id") in (None, s["community_id"])
           and f.get("holder_resident_id") in (None, s["holder_resident_id"])]
    return paginate_pairs(raw, board_seat_out,
                          sort_key=lambda s: (s["seat_no"], s["created_at"]))


@bp.route("/mpc/board-seats/<sid>", methods=["GET"])
def get_board_seat(sid):
    actor()
    s = get_or_404("board_seat", DB.board_seats, sid)
    return ok_object(board_seat_out(s))


@bp.route("/mpc/board-seats/<sid>/call-election", methods=["POST"])
def call_election(sid):
    _, role = actor()
    require_roles(role, ["AssociationDirector"])
    s = get_or_404("board_seat", DB.board_seats, sid)
    data = body()
    check_no_undeclared(data, set())
    ok = ((s["status"] == "VACANT" and s["seat_class"] == "OWNER_ELECTED")
          or s["status"] == "LAPSED")
    if not ok:
        err("ERR_SEAT_NOT_VACANT", 409,
            "call-election requires a VACANT or LAPSED OWNER_ELECTED seat")
    s["eligible_voter_count"] = sum(
        1 for r in DB.residents.values()
        if r["community_id"] == s["community_id"] and r["status"] == "OWNER")
    s["election_deadline"] = DB.now() + timedelta(days=ELECTION_WINDOW_DAYS)
    s["status"] = "ELECTION_CALLED"
    touch(s)
    return ok_object(board_seat_out(s))


@bp.route("/mpc/board-seats/<sid>/certify-election", methods=["POST"])
def certify_election(sid):
    _, role = actor()
    require_roles(role, ["AssociationDirector"])
    s = get_or_404("board_seat", DB.board_seats, sid)
    data = body()
    holder = check_body_fk("resident", DB.residents, data.get("holder_resident_id"))
    check_no_undeclared(data, {"votes_cast", "votes_for", "holder_resident_id"})
    votes_cast = req_int(data, "votes_cast", minimum=0)
    votes_for = req_int(data, "votes_for", minimum=0)
    req_string(data, "holder_resident_id")
    if s["status"] != "ELECTION_CALLED":
        invalid_state("Seat is not ELECTION_CALLED")
    quorum = -(-s["eligible_voter_count"] * QUORUM_PCT // 100)  # ceil
    if votes_cast < quorum:
        err("ERR_QUORUM_NOT_MET", 409, "Quorum not met")
    if votes_for * 2 <= votes_cast:
        err("ERR_ELECTION_MAJORITY_NOT_REACHED", 409,
            "Strict majority required")
    eligible = (holder["community_id"] == s["community_id"]
                and holder["status"] == "OWNER")
    if eligible:
        for other in DB.board_seats.values():
            if (other["community_id"] == s["community_id"]
                    and other["holder_resident_id"] == holder["id"]
                    and other["status"] in ("FILLED", "ELECTION_CALLED")):
                eligible = False
                break
    if not eligible:
        err("ERR_HOLDER_NOT_ELIGIBLE", 422,
            "Holder must be an OWNER resident of the community not already holding a seat")
    s["holder_resident_id"] = holder["id"]
    s["holder_name"] = holder["full_name"]
    s["status"] = "FILLED"
    touch(s)
    return ok_object(board_seat_out(s))
