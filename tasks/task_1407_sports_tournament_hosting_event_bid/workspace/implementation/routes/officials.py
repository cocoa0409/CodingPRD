"""Official and OfficialAssignment endpoints (PRD §3.7)."""

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, touch
from errors import (ERR_CERTIFICATION_INSUFFICIENT, ERR_CROSS_EVENT_REFERENCE,
                    ERR_DUPLICATE_ASSIGNMENT, ERR_MATCH_NOT_SCHEDULABLE,
                    ERR_OFFICIAL_DAILY_LIMIT, ERR_OFFICIAL_NOT_ACTIVE,
                    ERR_OFFICIAL_WINDOW_CONFLICT, already_terminal,
                    invalid_state, raise_err)
from listing import list_response
from middleware import (forbid, get_body, opt_bool, opt_int, req_enum, req_str,
                        require_any_authenticated, require_roles)
from response import ok

bp = Blueprint("officials", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Officials
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/officials")
def create_official(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    name = req_str(data, "name")
    level = req_enum(data, "certification_level", svc.CERT_LEVELS)
    needs_housing = opt_bool(data, "needs_housing", default=False)
    game_limit = opt_int(data, "game_limit_per_day", default=4, lo=1)
    o = base_entity()
    o.update({
        "event_id": e["id"],
        "name": name,
        "certification_level": level,
        "needs_housing": needs_housing,
        "game_limit_per_day": game_limit,
        "status": "REGISTERED",
    })
    STORE.officials[o["id"]] = o
    return ok(svc.ser_official(o), status=201)


@bp.get("/events/<id>/officials")
def list_officials(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = [o for o in STORE.officials.values() if o["event_id"] == e["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    level = request.args.get("certification_level")
    if level is not None:
        items = [o for o in items if o["certification_level"] == level]
    items.sort(key=lambda o: (o["name"], o["_seq"]))
    return list_response(items, svc.ser_official)


@bp.get("/officials/<id>")
def get_official(id):
    require_any_authenticated()
    o = svc.get_or_404(STORE.officials, id, "official")
    return ok(svc.ser_official(o))


@bp.post("/officials/<id>/transition")
def transition_official(id):
    require_roles("CommissionAdmin")
    o = svc.get_or_404(STORE.officials, id, "official")
    data = get_body()
    action = req_enum(data, "action", svc.OFFICIAL_ACTIONS)
    if o["status"] in svc.OFFICIAL_TERMINAL:
        already_terminal("official")
    from_state = o["status"]
    targets = {
        ("REGISTERED", "VET"): "VETTED",
        ("VETTED", "ACTIVATE"): "ACTIVE",
        ("ACTIVE", "SUSPEND"): "SUSPENDED",
        ("SUSPENDED", "REINSTATE"): "ACTIVE",
        ("ACTIVE", "DEACTIVATE"): "INACTIVE",
        ("SUSPENDED", "DEACTIVATE"): "INACTIVE",
    }
    target = targets.get((from_state, action))
    if target is None:
        invalid_state(f"Action {action} is not valid for an official in {from_state}.")
    o["status"] = target
    if action in ("SUSPEND", "DEACTIVATE") and from_state == "ACTIVE":
        for a in svc.assignments_of_official(o["id"]):
            if a["status"] in ("PROPOSED", "ACCEPTED"):
                svc.release_assignment(a, "OFFICIAL_SUSPENDED")
    touch(o)
    return ok(svc.ser_official(o))


@bp.get("/officials/<id>/assignments")
def list_official_assignments(id):
    require_any_authenticated()
    o = svc.get_or_404(STORE.officials, id, "official")
    items = svc.assignments_of_official(o["id"])
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return list_response(items, svc.ser_assignment)


# ---------------------------------------------------------------------------
# Official assignments
# ---------------------------------------------------------------------------

@bp.post("/matches/<id>/official-assignments")
def create_assignment(id):
    require_roles("CommissionAdmin")
    m = svc.get_or_404(STORE.matches, id, "match")
    data = get_body()
    official_id = req_str(data, "official_id")
    slot_role = req_enum(data, "slot_role", svc.SLOT_ROLES)
    o = svc.get_or_404(STORE.officials, official_id, "official")
    division = svc.get_or_404(STORE.divisions, m["division_id"], "division")
    # State: match must be SCHEDULED.
    if m["status"] in svc.MATCH_TERMINAL:
        already_terminal("match")
    if m["status"] != "SCHEDULED":
        raise_err(ERR_MATCH_NOT_SCHEDULABLE,
                  "Officials may be proposed only for a SCHEDULED match.")
    # State: official must be ACTIVE.
    if o["status"] in svc.OFFICIAL_TERMINAL:
        already_terminal("official")
    if o["status"] != "ACTIVE":
        raise_err(ERR_OFFICIAL_NOT_ACTIVE, "The official is not ACTIVE.")
    # Business safety: certification.
    is_final_round = (division.get("total_rounds") is not None
                      and m["round_number"] == division["total_rounds"])
    if slot_role == "CREW_CHIEF":
        if o["certification_level"] == "TRAINEE":
            raise_err(ERR_CERTIFICATION_INSUFFICIENT,
                      "A TRAINEE may only hold the ASSISTANT role.")
        if is_final_round and o["certification_level"] != "NATIONAL":
            raise_err(ERR_CERTIFICATION_INSUFFICIENT,
                      "The final round's CREW_CHIEF requires NATIONAL certification.")
    # Business constraint: duplicates.
    for a in svc.assignments_of_match(m["id"]):
        if a["status"] in ("PROPOSED", "ACCEPTED"):
            if a["official_id"] == o["id"]:
                raise_err(ERR_DUPLICATE_ASSIGNMENT,
                          "The official already holds a non-terminal assignment on this match.")
            if slot_role == "CREW_CHIEF" and a["slot_role"] == "CREW_CHIEF":
                raise_err(ERR_DUPLICATE_ASSIGNMENT,
                          "The match already has a non-terminal CREW_CHIEF.")
    # Temporal: 30-minute turnover buffer window conflict.
    if svc.official_window_conflict(o["id"], m["scheduled_start"], m["scheduled_end"]):
        raise_err(ERR_OFFICIAL_WINDOW_CONFLICT,
                  "The match window (with turnover buffer) intersects another assignment.")
    # Cross-event: official must belong to the match's event.
    if o["event_id"] != division["event_id"]:
        raise_err(ERR_CROSS_EVENT_REFERENCE,
                  "The official belongs to a different event.")
    # Fiscal: daily load.
    day = m["scheduled_start"].date()
    if svc.official_daily_load(o["id"], day) >= o["game_limit_per_day"]:
        raise_err(ERR_OFFICIAL_DAILY_LIMIT,
                  "The official has reached their daily game limit.")
    a = base_entity()
    a.update({
        "match_id": m["id"],
        "official_id": o["id"],
        "slot_role": slot_role,
        "status": "PROPOSED",
        "released_reason": None,
    })
    STORE.assignments[a["id"]] = a
    return ok(svc.ser_assignment(a), status=201)


@bp.get("/official-assignments/<id>")
def get_assignment(id):
    require_any_authenticated()
    a = svc.get_or_404(STORE.assignments, id, "official assignment")
    return ok(svc.ser_assignment(a))


@bp.post("/official-assignments/<id>/respond")
def respond_assignment(id):
    uid, role = require_roles("Official")
    a = svc.get_or_404(STORE.assignments, id, "official assignment")
    forbid(a["official_id"] != uid, "An official may respond only to their own assignment.")
    data = get_body()
    response = req_enum(data, "response", {"ACCEPTED", "DECLINED"})
    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        already_terminal("official assignment")
    if a["status"] != "PROPOSED":
        invalid_state("Only a PROPOSED assignment can be answered.")
    o = svc.get_or_404(STORE.officials, a["official_id"], "official")
    if response == "ACCEPTED":
        m = svc.get_or_404(STORE.matches, a["match_id"], "match")
        if m["status"] != "SCHEDULED":
            invalid_state("The match is no longer SCHEDULED.")
        if o["status"] != "ACTIVE":
            raise_err(ERR_OFFICIAL_NOT_ACTIVE, "The official is no longer ACTIVE.")
        a["status"] = "ACCEPTED"
    else:
        a["status"] = "DECLINED"
    touch(a)
    return ok(svc.ser_assignment(a))


@bp.post("/official-assignments/<id>/release")
def release_assignment_endpoint(id):
    require_roles("CommissionAdmin")
    a = svc.get_or_404(STORE.assignments, id, "official assignment")
    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        already_terminal("official assignment")
    if a["status"] not in ("PROPOSED", "ACCEPTED"):
        invalid_state("Only a PROPOSED or ACCEPTED assignment can be released.")
    svc.release_assignment(a, "MANUAL")
    return ok(svc.ser_assignment(a))


@bp.post("/official-assignments/<id>/complete")
def complete_assignment(id):
    require_roles("CommissionAdmin")
    a = svc.get_or_404(STORE.assignments, id, "official assignment")
    if a["status"] in svc.ASSIGNMENT_TERMINAL:
        already_terminal("official assignment")
    if a["status"] != "ACCEPTED":
        invalid_state("Only an ACCEPTED assignment can be marked worked.")
    m = svc.get_or_404(STORE.matches, a["match_id"], "match")
    if m["status"] != "FINAL":
        invalid_state("The match must be FINAL before an assignment is marked worked.")
    a["status"] = "WORKED"
    touch(a)
    return ok(svc.ser_assignment(a))
