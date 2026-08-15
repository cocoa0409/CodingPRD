"""Composite setup helpers. All multi-step preconditions are built here so tests
focus on assertions. Setup calls use get_success_data() so a setup failure
surfaces as a clear fixture error, not a confusing test assertion.

All fixtures build their preconditions from scratch against an empty database —
the runner restarts the server before every test.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .factories import (
    create_donor_payload,
    create_bike_payload,
    create_part_payload,
    create_helmet_part_payload,
    create_volunteer_payload,
    create_training_session_payload,
    create_participant_payload,
    create_hour_log_payload,
    create_membership_payload,
    full_checklist,
)
from .test_users import (
    TEST_USERS,
    make_volunteer_headers,
    make_participant_headers,
    make_member_headers,
    make_coordinator_headers,
    make_director_headers,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]
APPROVER = TEST_USERS["coordinator_approver_headers"]


# ---------------------------------------------------------------------------
# Tier 0: small building blocks
# ---------------------------------------------------------------------------

def make_donor(**overrides) -> dict:
    """Create a donor and return its body."""
    resp = api_client.create_donor(create_donor_payload(**overrides), COORD)
    return get_success_data(resp)


def make_bike(donor_id: str, **overrides) -> dict:
    """Create a RECEIVED bike and return its body."""
    resp = api_client.create_bike(create_bike_payload(donor_id, **overrides), COORD)
    return get_success_data(resp)


def triage_bike(bike_id: str, grade: str, frame_damage: bool = False) -> dict:
    resp = api_client.triage_bike(
        bike_id, {"condition_grade": grade, "frame_damage": frame_damage}, COORD
    )
    return get_success_data(resp)


def make_part(**overrides) -> dict:
    resp = api_client.create_part(create_part_payload(**overrides), COORD)
    return get_success_data(resp)


def make_helmet_part(**overrides) -> dict:
    resp = api_client.create_part(create_helmet_part_payload(**overrides), COORD)
    return get_success_data(resp)


def restock_part(part_id: str, quantity: int, unit_cost_cents=None) -> dict:
    payload = {"quantity": quantity}
    if unit_cost_cents is not None:
        payload["unit_cost_cents"] = unit_cost_cents
    resp = api_client.restock_part(part_id, payload, COORD)
    return get_success_data(resp)


def make_volunteer(**overrides) -> dict:
    resp = api_client.create_volunteer(create_volunteer_payload(**overrides), COORD)
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, COORD)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: volunteer training / promotion progression
# ---------------------------------------------------------------------------

def attend_sessions(volunteer_id: str, specs) -> dict:
    """Create, enroll, and complete `specs` training sessions for one volunteer.

    `specs` is a list of dicts with keys: topic/scheduled_start/scheduled_end/
    credit_hours/capacity/overrides. The clock is advanced past the latest end
    before completion. Returns the latest volunteer body.
    """
    session_ids = []
    attendance_ids = []
    latest_end = None
    for spec in specs:
        payload = create_training_session_payload(**spec)
        s = get_success_data(api_client.create_training_session(payload, COORD))
        a = get_success_data(
            api_client.enroll_in_session(s["id"], {"volunteer_id": volunteer_id}, COORD)
        )
        session_ids.append(s["id"])
        attendance_ids.append(a["id"])
        if latest_end is None or spec["scheduled_end"] > latest_end:
            latest_end = spec["scheduled_end"]
    if latest_end is not None:
        # advance clock past the latest session end
        # parse minimal ISO: take date part and bump by one day
        day = latest_end[:10]
        y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
        # simple next-day (all PRD dates are within a month)
        d += 1
        if d > 28:
            d = 1
            m += 1
            if m > 12:
                m = 1
                y += 1
        set_clock(f"{y:04d}-{m:02d}-{d:02d}T00:00:00Z")
    for sid, aid in zip(session_ids, attendance_ids):
        get_success_data(
            api_client.complete_training_session(
                sid, {"marks": [{"attendance_id": aid, "outcome": "ATTENDED"}]}, COORD
            )
        )
    return get_success_data(api_client.get_volunteer(volunteer_id, COORD))


def make_apprentice(volunteer_id: str | None = None) -> dict:
    """Return an APPRENTICE volunteer (8h, 2 sessions) promoted once."""
    v = make_volunteer() if volunteer_id is None else get_success_data(
        api_client.get_volunteer(volunteer_id, COORD)
    )
    attend_sessions(
        v["id"],
        [
            {"topic": "A1", "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_end": "2026-08-02T11:00:00Z", "credit_hours": 5},
            {"topic": "A2", "scheduled_start": "2026-08-03T10:00:00Z",
             "scheduled_end": "2026-08-03T11:00:00Z", "credit_hours": 5},
        ],
    )
    get_success_data(api_client.promote_volunteer(v["id"], DIRECTOR))
    return get_success_data(api_client.get_volunteer(v["id"], COORD))


def make_journeyman(volunteer_id: str | None = None) -> dict:
    """Return a JOURNEYMAN volunteer (24h, 5 sessions) promoted twice."""
    v = make_volunteer() if volunteer_id is None else get_success_data(
        api_client.get_volunteer(volunteer_id, COORD)
    )
    attend_sessions(
        v["id"],
        [
            {"topic": "J1", "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_end": "2026-08-02T11:00:00Z", "credit_hours": 6},
            {"topic": "J2", "scheduled_start": "2026-08-03T10:00:00Z",
             "scheduled_end": "2026-08-03T11:00:00Z", "credit_hours": 6},
            {"topic": "J3", "scheduled_start": "2026-08-04T10:00:00Z",
             "scheduled_end": "2026-08-04T11:00:00Z", "credit_hours": 6},
            {"topic": "J4", "scheduled_start": "2026-08-05T10:00:00Z",
             "scheduled_end": "2026-08-05T11:00:00Z", "credit_hours": 6},
            {"topic": "J5", "scheduled_start": "2026-08-06T10:00:00Z",
             "scheduled_end": "2026-08-06T11:00:00Z", "credit_hours": 6},
        ],
    )
    get_success_data(api_client.promote_volunteer(v["id"], DIRECTOR))
    get_success_data(api_client.promote_volunteer(v["id"], DIRECTOR))
    return get_success_data(api_client.get_volunteer(v["id"], COORD))


def make_lead_and_inspector():
    """Return (lead, inspector) volunteers: lead APPRENTICE, inspector JOURNEYMAN.

    Uses the shared 5-session pipeline: lead attends the first two sessions,
    inspector attends all five. After completions, promote lead once and the
    inspector twice.
    """
    lead = make_volunteer(full_name="V Lead", email="vl@x.org")
    insp = make_volunteer(full_name="V Insp", email="vi@x.org")

    sessions = []
    marks_per_session = []
    for i in range(5):
        day = 2 + i
        s = get_success_data(
            api_client.create_training_session(
                create_training_session_payload(
                    topic=f"T{i+1}",
                    scheduled_start=f"2026-08-{day:02d}T10:00:00Z",
                    scheduled_end=f"2026-08-{day:02d}T11:00:00Z",
                    credit_hours=6,
                ),
                COORD,
            )
        )
        sessions.append(s["id"])
        marks = []
        la = get_success_data(
            api_client.enroll_in_session(s["id"], {"volunteer_id": lead["id"]}, COORD)
        ) if i < 2 else None
        ia = get_success_data(
            api_client.enroll_in_session(s["id"], {"volunteer_id": insp["id"]}, COORD)
        )
        if la is not None:
            marks.append({"attendance_id": la["id"], "outcome": "ATTENDED"})
        marks.append({"attendance_id": ia["id"], "outcome": "ATTENDED"})
        marks_per_session.append(marks)

    set_clock("2026-08-07T00:00:00Z")
    for sid, marks in zip(sessions, marks_per_session):
        get_success_data(
            api_client.complete_training_session(sid, {"marks": marks}, COORD)
        )
    get_success_data(api_client.promote_volunteer(lead["id"], DIRECTOR))
    get_success_data(api_client.promote_volunteer(insp["id"], DIRECTOR))
    get_success_data(api_client.promote_volunteer(insp["id"], DIRECTOR))
    lead = get_success_data(api_client.get_volunteer(lead["id"], COORD))
    insp = get_success_data(api_client.get_volunteer(insp["id"], COORD))
    return lead, insp


# ---------------------------------------------------------------------------
# Tier 2: bike pipeline to READY_FOR_DISPOSITION
# ---------------------------------------------------------------------------

def log_usage(bike_id: str, part_id: str, quantity: int, expected_part_version: int,
              volunteer_id: str) -> dict:
    resp = api_client.create_usage_log(
        bike_id,
        {
            "part_id": part_id,
            "quantity": quantity,
            "expected_part_version": expected_part_version,
        },
        make_volunteer_headers(volunteer_id),
    )
    return get_success_data(resp)


def make_ready_bike(donor_id: str | None = None, bike_type: str = "ROAD",
                    grade: str = "B", part_unit_cost_cents: int = 500,
                    part_quantity: int = 1, part_restock: int = 10,
                    wheel_size_inches: float = 27,
                    part_category: str = "MISC"):
    """Full refurb pipeline to READY_FOR_DISPOSITION.

    Returns (bike, part, lead, inspector). Uses a shared APPRENTICE lead and
    JOURNEYMAN inspector and one COMMITTED usage so parts_cost_cents is
    part_unit_cost_cents * part_quantity.
    """
    if donor_id is None:
        donor_id = make_donor()["id"]
    lead, insp = make_lead_and_inspector()
    bike = make_bike(donor_id, bike_type=bike_type, wheel_size_inches=wheel_size_inches)
    triage_bike(bike["id"], grade, False)
    get_success_data(
        api_client.route_bike(
            bike["id"],
            {"destination": "REFURBISH", "refurb_lead_volunteer_id": lead["id"]},
            COORD,
        )
    )
    part = make_part(category=part_category, unit_cost_cents=part_unit_cost_cents)
    part = restock_part(part["id"], part_restock)
    log_usage(bike["id"], part["id"], part_quantity, part["version"], lead["id"])
    get_success_data(api_client.submit_safety(bike["id"], make_volunteer_headers(lead["id"])))
    get_success_data(
        api_client.create_safety_inspection(
            bike["id"],
            {"result": "PASS", "checklist": full_checklist(True)},
            make_volunteer_headers(insp["id"]),
        )
    )
    bike = get_success_data(api_client.get_bike(bike["id"], COORD))
    return bike, part, lead, insp


def make_scrap_pending_bike(donor_id: str | None = None, material: str = "STEEL",
                            weight_kg: float = 5.0, recycler_name: str = "RecCo"):
    """Drive a bike to SCRAP_PENDING with one OPEN scrap ticket.

    Returns (bike, ticket).
    """
    if donor_id is None:
        donor_id = make_donor()["id"]
    bike = make_bike(donor_id)
    triage_bike(bike["id"], "D", True)
    get_success_data(api_client.route_bike(bike["id"], {"destination": "SCRAP"}, COORD))
    ticket = get_success_data(
        api_client.create_scrap_ticket(
            bike["id"],
            {"material": material, "weight_kg": weight_kg, "recycler_name": recycler_name},
            COORD,
        )
    )
    bike = get_success_data(api_client.get_bike(bike["id"], COORD))
    return bike, ticket


def make_scrapped_bike(donor_id: str | None = None, material: str = "STEEL",
                       weight_kg: float = 5.0):
    """Drive a bike all the way to SCRAPPED (ticket PICKED_UP).

    Returns (bike, ticket).
    """
    bike, ticket = make_scrap_pending_bike(donor_id, material, weight_kg)
    get_success_data(api_client.pickup_scrap_ticket(ticket["id"], DIRECTOR))
    bike = get_success_data(api_client.get_bike(bike["id"], COORD))
    ticket = get_success_data(api_client.get_scrap_ticket(ticket["id"], COORD))
    return bike, ticket


def make_harvest_queue_bike(donor_id: str | None = None) -> dict:
    """Grade-D bike routed to HARVEST_QUEUE."""
    if donor_id is None:
        donor_id = make_donor()["id"]
    bike = make_bike(donor_id)
    triage_bike(bike["id"], "D", False)
    get_success_data(api_client.route_bike(bike["id"], {"destination": "HARVEST"}, COORD))
    return get_success_data(api_client.get_bike(bike["id"], COORD))


# ---------------------------------------------------------------------------
# Tier 3: earn-a-bike participants
# ---------------------------------------------------------------------------

def make_participant(age_group: str = "ADULT", **overrides) -> dict:
    payload = create_participant_payload(age_group=age_group, **overrides)
    resp = api_client.create_participant(payload, COORD)
    return get_success_data(resp)


def log_hours(participant_id: str, work_date: str, hours: int,
              activity_type: str = "SHOP_HELP", shift_id: str | None = None,
              as_user_id: str | None = None) -> dict:
    payload = create_hour_log_payload(
        work_date=work_date, hours=hours, activity_type=activity_type
    )
    if shift_id is not None:
        payload["shift_id"] = shift_id
    headers = (
        make_participant_headers(participant_id)
        if as_user_id is None
        else make_coordinator_headers(as_user_id)
    )
    resp = api_client.create_hour_log(participant_id, payload, headers)
    return get_success_data(resp)


def approve_log(log_id: str, participant_id: str, approver_user_id: str = "sc-approver-1") -> dict:
    participant = get_success_data(api_client.get_participant(participant_id, COORD))
    resp = api_client.approve_hour_log(
        log_id,
        {"expected_participant_version": participant["version"]},
        make_coordinator_headers(approver_user_id),
    )
    return get_success_data(resp)


def make_hours_met_participant(age_group: str = "ADULT", total_hours: int | None = None):
    """Participant with enough approved hours to reach HOURS_MET.

    Returns (participant, hour_log_ids).
    """
    p = make_participant(age_group=age_group)
    set_clock("2026-08-07T00:00:00Z")
    required = 8 if age_group == "YOUTH" else 12
    total = total_hours if total_hours is not None else required
    logs = []
    remaining = total
    day = 2
    while remaining > 0:
        chunk = min(6, remaining)
        log = log_hours(p["id"], f"2026-08-{day:02d}", chunk)
        logs.append(log["id"])
        remaining -= chunk
        day += 1
    for lid in logs:
        approve_log(lid, p["id"])
    p = get_success_data(api_client.get_participant(p["id"], COORD))
    return p, logs


# ---------------------------------------------------------------------------
# Tier 4: memberships and stand sessions
# ---------------------------------------------------------------------------

def make_membership(**overrides) -> dict:
    from .factories import create_membership_payload
    resp = api_client.create_membership(create_membership_payload(**overrides), COORD)
    return get_success_data(resp)


def book_session(membership_id: str, stand_number: int, start_time: str,
                 end_time: str, as_coordinator: bool = False) -> dict:
    payload = {
        "stand_number": stand_number,
        "start_time": start_time,
        "end_time": end_time,
    }
    headers = COORD if as_coordinator else make_member_headers(membership_id)
    resp = api_client.book_session(membership_id, payload, headers)
    return get_success_data(resp)


def start_and_close_session(session_id: str, membership_id: str) -> dict:
    """Start then close a session as the owning member. Returns CLOSED body."""
    get_success_data(api_client.start_session(session_id, make_member_headers(membership_id)))
    return get_success_data(
        api_client.close_session(session_id, make_member_headers(membership_id))
    )
