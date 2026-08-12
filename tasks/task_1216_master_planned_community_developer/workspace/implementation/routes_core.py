"""Routes: logical clock, communities, phases, amenities."""
from flask import Blueprint

from core import (
    DB, actor, require_roles, body, check_no_undeclared, req_string, req_int,
    req_enum, req_datetime, opt_int, opt_id, validation, err, invalid_state,
    not_found, new_entity, touch, get_or_404, check_body_fk, paginate,
    filter_args, ok_object, iso, parse_dt, TOTAL_SEATS, ALL_ROLES,
)
from serializers import community_out, phase_out, amenity_out
from domain import recompute_community_stage  # noqa: F401  (used elsewhere)
import domain

bp = Blueprint("core", __name__)

EXEC = ["DeclarantExecutive"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    actor_result = actor()
    require_roles(actor_result[1], ["PlatformAdmin"])
    data = body()
    check_no_undeclared(data, {"to_iso8601"})
    to = req_datetime(data, "to_iso8601")
    with DB.lock:
        DB.clock = to
        applied = domain.run_sweep()
    return ok_object({"current_utc": iso(DB.clock), "transitions_applied": applied})


# ---------------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------------
@bp.route("/mpc/communities", methods=["POST"])
def create_community():
    actor()
    _, role = actor()
    require_roles(role, EXEC)
    data = body()
    # FK existence rung has nothing to check here; shape next.
    check_no_undeclared(data, {"community_name", "total_planned_units"})
    name = req_string(data, "community_name")
    units = req_int(data, "total_planned_units", minimum=1)
    c = new_entity()
    c.update({
        "community_name": name,
        "total_planned_units": units,
        "status": "PLANNING",
        "closed_unit_count": 0,
        "transition_stage": "DECLARANT_CONTROL",
    })
    DB.communities[c["id"]] = c
    return ok_object(community_out(c), 201)


@bp.route("/mpc/communities", methods=["GET"])
def list_communities():
    actor()
    return paginate_pairs(list(DB.communities.values()), community_out)


def paginate_pairs(raw, serializer, sort_key=None):
    from core import pagination_params, ok_list
    if sort_key is not None:
        raw = sorted(raw, key=sort_key)
    else:
        raw = sorted(raw, key=lambda e: e["created_at"])
    limit, offset = pagination_params()
    total = len(raw)
    page = raw[offset:offset + limit]
    return ok_list([serializer(e) for e in page], total, limit, offset)


@bp.route("/mpc/communities/<cid>", methods=["GET"])
def get_community(cid):
    actor()
    c = get_or_404("community", DB.communities, cid)
    return ok_object(community_out(c))


@bp.route("/mpc/communities/<cid>/activate", methods=["POST"])
def activate_community(cid):
    _, role = actor()
    require_roles(role, EXEC)
    c = get_or_404("community", DB.communities, cid)
    data = body()
    check_no_undeclared(data, {"declarant_director_names"})
    names = data.get("declarant_director_names")
    if (not isinstance(names, list) or len(names) != TOTAL_SEATS
            or any(not isinstance(n, str) or not n for n in names)):
        validation("declarant_director_names must contain exactly five names")
    if c["status"] != "PLANNING":
        invalid_state("Community is not PLANNING")
    c["status"] = "ACTIVE"
    touch(c)
    for i, name in enumerate(names, start=1):
        seat = new_entity()
        seat.update({
            "community_id": c["id"],
            "seat_no": i,
            "seat_class": "DECLARANT_APPOINTED",
            "holder_name": name,
            "holder_resident_id": None,
            "eligible_voter_count": None,
            "election_deadline": None,
            "status": "FILLED",
        })
        DB.board_seats[seat["id"]] = seat
    return ok_object(community_out(c))


@bp.route("/mpc/communities/<cid>/record-turnover", methods=["POST"])
def record_turnover(cid):
    _, role = actor()
    require_roles(role, EXEC)
    c = get_or_404("community", DB.communities, cid)
    data = body()
    check_no_undeclared(data, set())
    if c["status"] != "ACTIVE":
        invalid_state("Community is not ACTIVE")
    from domain import community_pct
    if community_pct(c) < 100:
        err("ERR_TRANSITION_THRESHOLD_NOT_MET", 409,
            "record-turnover requires closed_unit_pct >= 100.00")
    seats = [s for s in DB.board_seats.values() if s["community_id"] == c["id"]]
    ok = len(seats) == TOTAL_SEATS and all(
        s["seat_class"] == "OWNER_ELECTED" and s["status"] == "FILLED" for s in seats
    )
    if not ok:
        err("ERR_TURNOVER_SEATS_NOT_FILLED", 409,
            "All five seats must be OWNER_ELECTED and FILLED")
    c["status"] = "TURNOVER_RECORDED"
    c["transition_stage"] = "TURNOVER_COMPLETE"
    touch(c)
    return ok_object(community_out(c))


@bp.route("/mpc/communities/<cid>/summary", methods=["GET"])
def community_summary(cid):
    actor()
    c = get_or_404("community", DB.communities, cid)
    from domain import community_pct
    from core import dec_num
    seats = [s for s in DB.board_seats.values() if s["community_id"] == c["id"]]
    filled = sum(1 for s in seats
                 if s["seat_class"] == "OWNER_ELECTED" and s["status"] == "FILLED")
    vacant = sum(1 for s in seats
                 if s["seat_class"] == "OWNER_ELECTED" and s["status"] == "VACANT")
    return ok_object({
        "closed_unit_count": c["closed_unit_count"],
        "closed_unit_pct": dec_num(community_pct(c)),
        "transition_stage": c["transition_stage"],
        "owner_elected_seats_filled": filled,
        "owner_elected_seats_vacant": vacant,
    })


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------
@bp.route("/mpc/phases", methods=["POST"])
def create_phase():
    _, role = actor()
    require_roles(role, EXEC)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    check_no_undeclared(data, {"community_id", "phase_name", "sequence_no",
                               "planned_lot_count"})
    req_string(data, "community_id")
    name = req_string(data, "phase_name")
    seq = req_int(data, "sequence_no", minimum=1)
    lots = req_int(data, "planned_lot_count", minimum=1)
    for p in DB.phases.values():
        if p["community_id"] == community["id"] and p["sequence_no"] == seq:
            err("ERR_PHASE_SEQUENCE_BLOCKED", 409,
                "sequence_no already used in this community")
    p = new_entity()
    p.update({
        "community_id": community["id"],
        "phase_name": name,
        "sequence_no": seq,
        "planned_lot_count": lots,
        "closed_lot_count": 0,
        "status": "PLANNED",
    })
    DB.phases[p["id"]] = p
    return ok_object(phase_out(p), 201)


@bp.route("/mpc/phases", methods=["GET"])
def list_phases():
    actor()
    f = filter_args(["community_id"])
    raw = [p for p in DB.phases.values()
           if f.get("community_id") in (None, p["community_id"])]
    return paginate_pairs(raw, phase_out)


@bp.route("/mpc/phases/<pid>", methods=["GET"])
def get_phase(pid):
    actor()
    p = get_or_404("phase", DB.phases, pid)
    return ok_object(phase_out(p))


@bp.route("/mpc/phases/<pid>/open-sales", methods=["POST"])
def open_sales(pid):
    _, role = actor()
    require_roles(role, EXEC)
    p = get_or_404("phase", DB.phases, pid)
    data = body()
    check_no_undeclared(data, set())
    if p["status"] != "PLANNED":
        invalid_state("Phase is not PLANNED")
    community = DB.communities.get(p["community_id"])
    if community is None or community["status"] != "ACTIVE":
        err("ERR_COMMUNITY_NOT_ACTIVE", 409, "Community must be ACTIVE")
    predecessor = None
    for other in DB.phases.values():
        if (other["community_id"] == p["community_id"]
                and other["sequence_no"] == p["sequence_no"] - 1):
            predecessor = other
            break
    if predecessor is not None and predecessor["status"] not in ("DELIVERING", "CLOSED_OUT"):
        err("ERR_PHASE_SEQUENCE_BLOCKED", 409,
            "Predecessor phase must be DELIVERING or CLOSED_OUT")
    p["status"] = "SALES_OPEN"
    touch(p)
    return ok_object(phase_out(p))


@bp.route("/mpc/phases/<pid>/close-out", methods=["POST"])
def close_out_phase(pid):
    _, role = actor()
    require_roles(role, EXEC)
    p = get_or_404("phase", DB.phases, pid)
    data = body()
    check_no_undeclared(data, set())
    if p["status"] != "DELIVERING":
        invalid_state("Phase is not DELIVERING")
    for lot in DB.lots.values():
        if lot["phase_id"] == p["id"] and lot["status"] not in ("CLOSED", "WITHDRAWN"):
            err("ERR_CLOSEOUT_BLOCKED", 409,
                "Every lot must be CLOSED or WITHDRAWN")
    for ag in DB.agreements.values():
        if ag["phase_id"] == p["id"] and ag["status"] not in (
                "COMPLETED", "DEFAULTED", "TERMINATED"):
            err("ERR_CLOSEOUT_BLOCKED", 409,
                "Every agreement on the phase must be terminal")
    p["status"] = "CLOSED_OUT"
    touch(p)
    return ok_object(phase_out(p))


@bp.route("/mpc/phases/<pid>/cancel", methods=["POST"])
def cancel_phase(pid):
    _, role = actor()
    require_roles(role, EXEC)
    p = get_or_404("phase", DB.phases, pid)
    data = body()
    check_no_undeclared(data, set())
    if p["status"] not in ("PLANNED", "SALES_OPEN"):
        invalid_state("Phase is not PLANNED or SALES_OPEN")
    lot_ids = {l["id"] for l in DB.lots.values() if l["phase_id"] == p["id"]}
    for cl in DB.closings.values():
        if cl["lot_id"] in lot_ids and cl["status"] in ("PENDING", "CLOSED"):
            err("ERR_CLOSEOUT_BLOCKED", 409,
                "Closings reference lots of this phase")
    p["status"] = "CANCELLED"
    touch(p)
    for lot in DB.lots.values():
        if lot["phase_id"] == p["id"] and lot["status"] in ("PLATTED", "OFFERED"):
            lot["status"] = "WITHDRAWN"
            touch(lot)
    for ag in DB.agreements.values():
        if ag["phase_id"] == p["id"] and ag["status"] in ("DRAFT", "EXECUTED"):
            ag["status"] = "TERMINATED"
            touch(ag)
            for t in DB.tranches.values():
                if t["agreement_id"] == ag["id"] and t["status"] in ("SCHEDULED", "OPEN"):
                    t["status"] = "CANCELLED"
                    touch(t)
    return ok_object(phase_out(p))


# ---------------------------------------------------------------------------
# Amenities
# ---------------------------------------------------------------------------
AMENITY_TYPES = {"CLUBHOUSE", "POOL", "PARK", "TRAIL_NETWORK", "FITNESS_CENTER",
                 "EVENT_LAWN"}


@bp.route("/mpc/amenities", methods=["POST"])
def create_amenity():
    _, role = actor()
    require_roles(role, EXEC)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    trigger_phase = check_body_fk("phase", DB.phases, data.get("trigger_phase_id"))
    check_no_undeclared(data, {"community_id", "amenity_type", "trigger_phase_id",
                               "trigger_unit_count", "hard_deadline_date",
                               "budgeted_cost_cents"})
    req_string(data, "community_id")
    atype = req_enum(data, "amenity_type", AMENITY_TYPES)
    deadline = req_datetime(data, "hard_deadline_date")
    cost = req_int(data, "budgeted_cost_cents", minimum=0)
    tp = opt_id(data, "trigger_phase_id")
    tc = opt_int(data, "trigger_unit_count")
    if (tp is None) != (tc is None):
        validation("trigger_phase_id and trigger_unit_count must both be present or both absent")
    a = new_entity()
    a.update({
        "community_id": community["id"],
        "amenity_type": atype,
        "trigger_phase_id": tp,
        "trigger_unit_count": tc,
        "hard_deadline_date": deadline,
        "budgeted_cost_cents": cost,
        "delinquency_recorded_at": None,
        "status": "COMMITTED",
    })
    DB.amenities[a["id"]] = a
    return ok_object(amenity_out(a), 201)


@bp.route("/mpc/amenities", methods=["GET"])
def list_amenities():
    actor()
    f = filter_args(["community_id", "trigger_phase_id"])
    raw = [a for a in DB.amenities.values()
           if f.get("community_id") in (None, a["community_id"])
           and f.get("trigger_phase_id") in (None, a["trigger_phase_id"])]
    return paginate_pairs(raw, amenity_out)


@bp.route("/mpc/amenities/<aid>", methods=["GET"])
def get_amenity(aid):
    actor()
    a = get_or_404("amenity", DB.amenities, aid)
    return ok_object(amenity_out(a))


def _amenity_transition(aid, from_states, to_state):
    _, role = actor()
    require_roles(role, EXEC)
    a = get_or_404("amenity", DB.amenities, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] not in from_states:
        invalid_state(f"Amenity cannot move from {a['status']} to {to_state}")
    a["status"] = to_state
    touch(a)
    return ok_object(amenity_out(a))


@bp.route("/mpc/amenities/<aid>/start-design", methods=["POST"])
def amenity_start_design(aid):
    return _amenity_transition(aid, ("COMMITTED",), "IN_DESIGN")


@bp.route("/mpc/amenities/<aid>/start-construction", methods=["POST"])
def amenity_start_construction(aid):
    return _amenity_transition(aid, ("IN_DESIGN",), "UNDER_CONSTRUCTION")


@bp.route("/mpc/amenities/<aid>/open", methods=["POST"])
def amenity_open(aid):
    return _amenity_transition(aid, ("UNDER_CONSTRUCTION", "DELINQUENT"), "OPEN")
