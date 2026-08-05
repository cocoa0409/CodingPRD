"""Routes: maintenance tickets, technician visit scheduling, resolution."""
from datetime import timedelta

from flask import Blueprint, g

import helpers as h
import domain as d
from state import S, clock_dt

bp = Blueprint("maintenance", __name__)

_AREAS = {"ROOM", "SHARED_KITCHEN", "SHARED_BATH", "LAUNDRY", "COMMON_AREA"}
_SEV = {"CRITICAL", "HIGH", "NORMAL"}


@bp.post("/co-living/tickets")
def create_ticket():
    h.authorize("Member", "CommunityManager")
    b = h.body()
    # Priority 4: ownership for Member (only when a tenancy is referenced)
    if g.role == "Member":
        amid = b.get("affected_membership_id")
        if amid is not None:
            mem = S.memberships.get(amid) if isinstance(amid, str) else None
            if mem is None or mem["member_id"] != g.user_id:
                raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the tenancy")
    # Priority 5: shape
    house_id = h.req_str(b, "house_id")
    area = h.req_enum(b, "area", _AREAS)
    severity = h.req_enum(b, "severity", _SEV)
    description = h.req_str(b, "description")
    room_id = h.opt_str(b, "room_id")
    affected_membership_id = h.opt_str(b, "affected_membership_id")
    # Priority 6: FK
    house = h.find_or_404(S.houses, house_id, "ERR_HOUSE_NOT_FOUND")
    room = None
    if room_id is not None:
        room = h.find_or_404(S.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    if affected_membership_id is not None:
        mem = h.find_or_404(S.memberships, affected_membership_id, "ERR_MEMBERSHIP_NOT_FOUND")
    # Priority 7: linkage coherence
    if room is not None and room["house_id"] != house_id:
        raise h.ApiError("ERR_ENTITY_MISMATCH", "room does not belong to house")
    if affected_membership_id is not None and mem["house_id"] != house_id:
        raise h.ApiError("ERR_ENTITY_MISMATCH", "membership does not belong to house")

    ticket = h.new_common()
    created_dt = clock_dt()
    sla_dt = created_dt + timedelta(hours=d.SLA_HOURS[severity])
    ticket.update({
        "house_id": house_id,
        "room_id": room_id,
        "affected_membership_id": affected_membership_id,
        "area": area,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "sla_deadline_at": h.fmt_instant(sla_dt),
        "visit_start": None,
        "visit_end": None,
        "resolved_at": None,
        "breach_hours": 0,
        "rent_credit_cents": 0,
        "resolution_note": None,
        "_sla_dt": sla_dt,
        "_took_room_oos": None,
    })
    S.tickets[ticket["id"]] = ticket
    # Creation cascade: CRITICAL ROOM ticket on a VACANT room -> OUT_OF_SERVICE
    if (severity == "CRITICAL" and area == "ROOM" and room is not None
            and room["occupancy_state"] == "VACANT"):
        room["occupancy_state"] = "OUT_OF_SERVICE"
        h.touch(room)
        ticket["_took_room_oos"] = room_id
        d.eval_posture(house)
    return h.ok(d.serialize(ticket), 201)


@bp.get("/co-living/tickets/<tid>")
def get_ticket(tid):
    h.authorize(*h.ROLES)
    t = h.find_or_404(S.tickets, tid, "ERR_TICKET_NOT_FOUND")
    return h.ok(d.serialize(t), 200)


@bp.get("/co-living/tickets")
def list_tickets():
    h.authorize(*h.ROLES)
    limit, offset = h.parse_pagination()
    house_id = h.query_val("house_id")
    room_id = h.query_val("room_id")
    amid = h.query_val("affected_membership_id")
    status = h.query_val("status")
    rows = []
    for t in S.tickets.values():
        if house_id is not None and t["house_id"] != house_id:
            continue
        if room_id is not None and t["room_id"] != room_id:
            continue
        if amid is not None and t["affected_membership_id"] != amid:
            continue
        if status is not None and t["status"] != status:
            continue
        rows.append(t)
    rows = h.sort_created(rows)
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


@bp.post("/co-living/tickets/<tid>/schedule")
def schedule_visit(tid):
    h.authorize("CommunityManager")
    t = h.find_or_404(S.tickets, tid, "ERR_TICKET_NOT_FOUND")
    house = S.houses[t["house_id"]]
    b = h.body()
    visit_start = h.req_instant(b, "visit_start")
    visit_end = h.req_instant(b, "visit_end")
    expected = h.req_int_nonneg(b, "expected_house_version")
    # Priority 10: state
    if t["status"] != "OPEN":
        raise h.ApiError("ERR_INVALID_TICKET_STATE", "ticket is not OPEN")
    # Priority 13: OCC on house version
    if expected != house["version"]:
        raise h.ApiError("ERR_STALE_HOUSE_VERSION", "expected_house_version is stale")
    # Priority 18: date range
    if visit_end <= visit_start:
        raise h.ApiError("ERR_INVALID_DATE_RANGE", "visit_end must be after visit_start")
    # Priority 27: capacity — no instant covered by > MAX concurrent SCHEDULED visits
    intervals = []
    for other in S.tickets.values():
        if other["house_id"] == t["house_id"] and other["status"] == "SCHEDULED" \
                and other["_visit_start_dt"] is not None:
            intervals.append((other["_visit_start_dt"], other["_visit_end_dt"]))
    intervals.append((visit_start, visit_end))
    events = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    # process ends (-1) before starts (+1) at the same instant (half-open)
    events.sort(key=lambda x: (x[0], x[1]))
    running = 0
    peak = 0
    for _, delta in events:
        running += delta
        peak = max(peak, running)
    if peak > d.MAX_CONCURRENT_VISITS_PER_HOUSE:
        raise h.ApiError("ERR_VISIT_CAPACITY_CONFLICT", "visit calendar capacity exceeded")

    t["visit_start"] = b["visit_start"]
    t["visit_end"] = b["visit_end"]
    t["_visit_start_dt"] = visit_start
    t["_visit_end_dt"] = visit_end
    t["status"] = "SCHEDULED"
    h.touch(t)
    h.touch(house)  # increments House.version by 1 (the OCC bump)
    return h.ok(d.serialize(t), 200)


@bp.post("/co-living/tickets/<tid>/resolve")
def resolve_ticket(tid):
    h.authorize("CommunityManager")
    t = h.find_or_404(S.tickets, tid, "ERR_TICKET_NOT_FOUND")
    b = h.body()
    note = h.opt_str(b, "resolution_note")
    # Priority 10: state
    if t["status"] not in ("OPEN", "SCHEDULED"):
        raise h.ApiError("ERR_INVALID_TICKET_STATE", "ticket already RESOLVED")

    resolved_dt = clock_dt()
    t["_resolved_dt"] = resolved_dt
    t["resolved_at"] = h.fmt_instant(resolved_dt)
    d.compute_ticket_credit(t)  # sets breach_hours + rent_credit_cents
    t["status"] = "RESOLVED"
    t["resolution_note"] = note
    h.touch(t)

    house = S.houses[t["house_id"]]
    if t["_took_room_oos"] is not None:
        room = S.rooms.get(t["_took_room_oos"])
        if room is not None and room["occupancy_state"] == "OUT_OF_SERVICE":
            room["occupancy_state"] = "VACANT"
            h.touch(room)
    d.eval_posture(house)
    return h.ok(d.serialize(t), 200)
