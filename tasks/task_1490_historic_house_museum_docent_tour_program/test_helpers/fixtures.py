"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its startup default 2026-08-01T00:00:00Z).
Setup calls use get_success_data so failures surface as clear "Setup failed"
errors. All callers are responsible for their own assertions.

The canonical chain most tests need:

    rooms -> route (DRAFT) -> script -> submit -> APPROVE review -> publish
    -> route ACTIVE -> certified docent -> slot (SCHEDULED) -> LEAD assigned
    -> LEAD confirmed (slot STAFFED) -> slot OPEN
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_docent_payload,
    create_general_booking_payload,
    create_member_booking_payload,
    create_member_payload,
    create_room_payload,
    create_school_booking_payload,
    create_script_version_payload,
    create_shift_assignment_payload,
    create_tour_route_payload,
    create_tour_slot_payload,
    reschedule_slot_payload,
    review_script_payload,
    training_record_payload,
)
from .test_users import TEST_USERS, make_docent_headers

ADMIN = TEST_USERS["museum_admin_headers"]
CURATOR = TEST_USERS["curator_headers"]
COORDINATOR = TEST_USERS["docent_coordinator_headers"]
FRONT_DESK = TEST_USERS["front_desk_staff_headers"]

DEFAULT_ROOM_SPEC = {
    "name": "Parlor", "floor": 1, "capacity_max": 20,
    "safety_max_party": 12, "collection_tier": "STANDARD",
}
DEFAULT_START = "2026-09-01T10:00:00Z"


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    data = get_success_data(resp)
    if expected_status is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected_status, (
            f"Setup failed at {step}: expected status {expected_status}, "
            f"got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creation
# ---------------------------------------------------------------------------

def create_room(**overrides):
    spec = {**DEFAULT_ROOM_SPEC, **overrides}
    resp = api_client.create_room(create_room_payload(**spec), ADMIN)
    return _ok("create_room", resp, expected_status="OPEN")


def create_rooms(specs):
    """Create one room per spec dict. Returns list of room bodies."""
    return [create_room(**spec) for spec in specs]


def create_route(room_ids, **overrides):
    """Create a DRAFT route. Returns the route body (version starts at 1)."""
    resp = api_client.create_tour_route(
        create_tour_route_payload(room_ids, **overrides), ADMIN)
    return _ok("create_tour_route", resp, expected_status="DRAFT")


def activate_route(route_id):
    resp = api_client.activate_tour_route(route_id, ADMIN)
    return _ok("activate_tour_route", resp, expected_status="ACTIVE")


def create_script(route_id, content_text="Welcome to the house",
                  curriculum_standards=None):
    resp = api_client.create_script_version(
        route_id,
        create_script_version_payload(
            content_text=content_text,
            curriculum_standards=curriculum_standards or [],
        ),
        CURATOR,
    )
    return _ok("create_script_version", resp, expected_status="DRAFT")


def submit_script(script_id):
    resp = api_client.submit_script_version(script_id, CURATOR)
    return _ok("submit_script_version", resp, expected_status="IN_REVIEW")


def approve_script(script_id, accuracy_score=90, reviewer_notes="accurate"):
    resp = api_client.review_script_version(
        script_id,
        review_script_payload(
            "APPROVE", accuracy_score=accuracy_score,
            reviewer_notes=reviewer_notes),
        CURATOR,
    )
    return _ok("approve_script", resp, expected_status="APPROVED")


def publish_script(script_id, expected_route_version):
    resp = api_client.publish_script_version(
        script_id, {"expected_route_version": expected_route_version}, ADMIN)
    return _ok("publish_script", resp, expected_status="PUBLISHED")


def create_docent(full_name="Dee Ocent", email="dee@x.org"):
    resp = api_client.create_docent(
        create_docent_payload(full_name=full_name, email=email), COORDINATOR)
    return _ok("create_docent", resp, expected_status="APPLICANT")


def advance_docent(docent_id, to_status, route_ids=None):
    payload = {"to_status": to_status}
    if route_ids is not None:
        payload["route_ids"] = route_ids
    resp = api_client.advance_docent(docent_id, payload, COORDINATOR)
    return _ok("advance_docent", resp)


def log_training(docent_id, kind, value):
    resp = api_client.log_training_record(
        docent_id, training_record_payload(kind, value), COORDINATOR)
    return _ok("log_training_record", resp)


def create_trainee(full_name="Dee Ocent", email="dee@x.org"):
    """APPLICANT -> TRAINEE (no threshold). Returns the TRAINEE docent."""
    docent = create_docent(full_name=full_name, email=email)
    return advance_docent(docent["id"], "TRAINEE")


def create_trainee_with_training(hours=0, shadow_tours=0, quiz_score=None,
                                 full_name="Dee Ocent", email="dee@x.org"):
    """TRAINEE docent carrying the given training record history."""
    docent = create_trainee(full_name=full_name, email=email)
    if hours:
        docent = log_training(docent["id"], "HOURS", hours)
    for _ in range(shadow_tours):
        docent = log_training(docent["id"], "SHADOW_TOUR", 1)
    if quiz_score is not None:
        docent = log_training(docent["id"], "QUIZ", quiz_score)
    return docent


def create_certified_docent(route_ids, hours=30, shadow_tours=3, quiz_score=90,
                            full_name="Dee Ocent", email="dee@x.org"):
    """TRAINEE + training records that clear every certification threshold,
    then advanced to CERTIFIED over the given routes."""
    docent = create_trainee_with_training(
        hours=hours, shadow_tours=shadow_tours, quiz_score=quiz_score,
        full_name=full_name, email=email)
    resp = api_client.advance_docent(
        docent["id"], {"to_status": "CERTIFIED", "route_ids": route_ids},
        COORDINATOR)
    return _ok("certify_docent", resp, expected_status="CERTIFIED")


def create_slot(route_id, start_at=DEFAULT_START):
    resp = api_client.create_tour_slot(
        create_tour_slot_payload(route_id, start_at=start_at), ADMIN)
    return _ok("create_tour_slot", resp, expected_status="SCHEDULED")


def assign_shift(docent_id, slot_id, shift_role="LEAD"):
    resp = api_client.create_shift_assignment(
        create_shift_assignment_payload(docent_id, slot_id, shift_role),
        COORDINATOR)
    return _ok("create_shift_assignment", resp, expected_status="ASSIGNED")


def confirm_shift(shift_id, docent_id):
    """Ownership-gated: the caller must BE the shift's docent."""
    resp = api_client.confirm_shift_assignment(
        shift_id, make_docent_headers(docent_id))
    return _ok("confirm_shift_assignment", resp, expected_status="CONFIRMED")


def decline_shift(shift_id, docent_id):
    resp = api_client.decline_shift_assignment(
        shift_id, make_docent_headers(docent_id))
    return _ok("decline_shift_assignment", resp, expected_status="DECLINED")


def assign_and_confirm_lead(docent_id, slot_id):
    shift = assign_shift(docent_id, slot_id, "LEAD")
    return confirm_shift(shift["id"], docent_id)


def open_slot(slot_id):
    resp = api_client.open_tour_slot(slot_id, ADMIN)
    return _ok("open_tour_slot", resp, expected_status="OPEN")


def get_slot(slot_id):
    return _ok("get_tour_slot", api_client.get_tour_slot(slot_id, ADMIN))


def get_route(route_id):
    return _ok("get_tour_route", api_client.get_tour_route(route_id, ADMIN))


def get_script(script_id):
    return _ok("get_script_version",
               api_client.get_script_version(script_id, CURATOR))


def get_booking(booking_id):
    return _ok("get_booking", api_client.get_booking(booking_id, FRONT_DESK))


def get_docent(docent_id):
    return _ok("get_docent", api_client.get_docent(docent_id, COORDINATOR))


# ---------------------------------------------------------------------------
# Tier 2 — route with published script
# ---------------------------------------------------------------------------

def setup_active_route_with_script(room_specs=None, route_kind="STANDARD",
                                   duration_minutes=60, base_price_cents=1000,
                                   curriculum_standards=None,
                                   route_name="Main Floor",
                                   content_text="Welcome to the house",
                                   accuracy_score=90):
    """Rooms + route walked to ACTIVE with one PUBLISHED script.

    Returns dict(rooms, route, route_id, script, script_id). The publish uses
    the route's creation version (no mutation between create and publish), so
    the OCC handshake is exercised exactly as the PRD describes.
    """
    rooms = create_rooms(room_specs or [DEFAULT_ROOM_SPEC])
    room_ids = [r["id"] for r in rooms]
    route = create_route(room_ids, kind=route_kind,
                         duration_minutes=duration_minutes,
                         base_price_cents=base_price_cents, name=route_name)
    script = create_script(route["id"], content_text=content_text,
                           curriculum_standards=curriculum_standards)
    submit_script(script["id"])
    approve_script(script["id"], accuracy_score=accuracy_score)
    publish_script(script["id"], route["version"])
    route = activate_route(route["id"])
    return {
        "rooms": rooms,
        "route": route,
        "route_id": route["id"],
        "script": script,
        "script_id": script["id"],
    }


def setup_active_route_no_script(room_specs=None, route_kind="STANDARD",
                                 duration_minutes=60, base_price_cents=1000,
                                 route_name="Main Floor"):
    """Rooms + ACTIVE route with no script at all."""
    rooms = create_rooms(room_specs or [DEFAULT_ROOM_SPEC])
    route = create_route([r["id"] for r in rooms], kind=route_kind,
                         duration_minutes=duration_minutes,
                         base_price_cents=base_price_cents, name=route_name)
    route = activate_route(route["id"])
    return {"rooms": rooms, "route": route, "route_id": route["id"]}


# ---------------------------------------------------------------------------
# Tier 3 — staffed slots
# ---------------------------------------------------------------------------

def setup_staffed_scheduled_slot(room_specs=None, route_kind="STANDARD",
                                 duration_minutes=60, base_price_cents=1000,
                                 curriculum_standards=None,
                                 start_at=DEFAULT_START,
                                 route_name="Main Floor"):
    """Published+ACTIVE route, certified docent, SCHEDULED slot, CONFIRMED
    LEAD (slot STAFFED). Slot is NOT opened.

    Returns dict(rooms, route, route_id, script, docent, docent_id, slot,
    slot_id, shift).
    """
    ctx = setup_active_route_with_script(
        room_specs=room_specs, route_kind=route_kind,
        duration_minutes=duration_minutes, base_price_cents=base_price_cents,
        curriculum_standards=curriculum_standards, route_name=route_name)
    docent = create_certified_docent([ctx["route_id"]])
    slot = create_slot(ctx["route_id"], start_at=start_at)
    shift = assign_and_confirm_lead(docent["id"], slot["id"])
    ctx.update({
        "docent": docent, "docent_id": docent["id"],
        "slot": slot, "slot_id": slot["id"], "shift": shift,
    })
    return ctx


def setup_open_slot(room_specs=None, route_kind="STANDARD", duration_minutes=60,
                    base_price_cents=1000, curriculum_standards=None,
                    start_at=DEFAULT_START, route_name="Main Floor"):
    """The full chain through slot OPEN. Same return shape as
    setup_staffed_scheduled_slot."""
    ctx = setup_staffed_scheduled_slot(
        room_specs=room_specs, route_kind=route_kind,
        duration_minutes=duration_minutes, base_price_cents=base_price_cents,
        curriculum_standards=curriculum_standards, start_at=start_at,
        route_name=route_name)
    ctx["slot"] = open_slot(ctx["slot_id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3b — bookings on an open slot
# ---------------------------------------------------------------------------

def create_general_booking(slot_id, party_size, visitor_name="Ann"):
    resp = api_client.create_booking(
        create_general_booking_payload(slot_id, party_size,
                                       visitor_name=visitor_name),
        FRONT_DESK)
    return _ok("create_general_booking", resp, expected_status="RESERVED")


def create_member_booking(slot_id, member_id, party_size,
                          visitor_name="Mel"):
    resp = api_client.create_booking(
        create_member_booking_payload(slot_id, member_id, party_size,
                                      visitor_name=visitor_name),
        FRONT_DESK)
    return _ok("create_member_booking", resp, expected_status="RESERVED")


def create_school_booking(slot_id, student_count, chaperone_count,
                          grade_level="5", curriculum_standard="HIST-5",
                          visitor_name="Lincoln Elementary"):
    resp = api_client.create_booking(
        create_school_booking_payload(
            slot_id, student_count, chaperone_count,
            grade_level=grade_level, curriculum_standard=curriculum_standard,
            visitor_name=visitor_name),
        FRONT_DESK)
    return _ok("create_school_booking", resp, expected_status="RESERVED")


def confirm_booking(booking_id, paid_cents, headers=None):
    resp = api_client.confirm_booking(
        booking_id, {"paid_cents": paid_cents}, headers or FRONT_DESK)
    return _ok("confirm_booking", resp, expected_status="CONFIRMED")


def cancel_booking(booking_id, headers=None):
    resp = api_client.cancel_booking(booking_id, headers or FRONT_DESK)
    return _ok("cancel_booking", resp, expected_status="CANCELLED")


def create_member(full_name="Mel Member", email="mel@x.org",
                  member_number="M-100", renews_on="2027-06-01"):
    resp = api_client.create_member(
        create_member_payload(full_name=full_name, email=email,
                              member_number=member_number,
                              renews_on=renews_on),
        FRONT_DESK)
    return _ok("create_member", resp, expected_status="ACTIVE")


# ---------------------------------------------------------------------------
# Tier 4 — clock and sweep
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_current_utc", resp)


def run_epoch():
    resp = api_client.run_epoch(ADMIN)
    return _ok("run_epoch", resp)


# ---------------------------------------------------------------------------
# Tier 5 — completed visit (surveys / shift resolution)
# ---------------------------------------------------------------------------

def setup_completed_slot_with_bookings(num_bookings=1, party_size=1,
                                       start_at="2026-08-05T10:00:00Z",
                                       base_price_cents=1000):
    """OPEN slot -> N GENERAL bookings created and CONFIRMED (clock still at
    the startup default, ahead of start) -> clock set to start_at -> slot
    advanced IN_PROGRESS -> COMPLETED.

    Returns dict(ctx..., bookings) where ctx is the setup_open_slot mapping.
    """
    ctx = setup_open_slot(start_at=start_at, base_price_cents=base_price_cents)
    bookings = []
    for i in range(num_bookings):
        booking = create_general_booking(ctx["slot_id"], party_size,
                                         visitor_name=f"Visitor{i}")
        bookings.append(confirm_booking(
            booking["id"], party_size * base_price_cents))
    set_clock(start_at)
    resp = api_client.advance_tour_slot(
        ctx["slot_id"], {"to_status": "IN_PROGRESS"}, ADMIN)
    _ok("advance_to_in_progress", resp, expected_status="IN_PROGRESS")
    resp = api_client.advance_tour_slot(
        ctx["slot_id"], {"to_status": "COMPLETED"}, ADMIN)
    ctx["slot"] = _ok("advance_to_completed", resp, expected_status="COMPLETED")
    ctx["bookings"] = bookings
    return ctx
