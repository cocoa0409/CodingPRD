"""Composite setup helpers for the Yoga & Pilates Studio API.

Each test runs against a freshly restarted, empty server, so every helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so a setup failure surfaces as a clear "Setup failed".

Identity threading: Member and Instructor roles are entity-backed. Any ownership-gated
call uses make_member_headers(member_id) / make_instructor_headers(teacher_id) with the
real entity id. StudioManager is opaque and uses the shared manager headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_studio_manager_headers,
)
from . import factories as F

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=MGR):
    """Set the logical clock. Returns the raw response (data is empty)."""
    return api_client.set_clock(to_iso8601, headers)


def run_ops(headers=MGR):
    """Run the periodic operations sweep at the current logical clock."""
    return api_client.run_ops(headers)


def create_member(email="m@x.com", full_name="Test Member", home_studio_state="CA"):
    """Register a member. Returns the Member resource dict."""
    resp = api_client.create_member(
        F.create_member_payload(email=email, full_name=full_name,
                                home_studio_state=home_studio_state),
        MGR,
    )
    return get_success_data(resp)


def create_room(name="Reformer A", room_type="REFORMER", station_capacity=4):
    """Create a room (opens OPEN). Returns the Room resource dict."""
    resp = api_client.create_room(
        F.create_room_payload(name=name, room_type=room_type, station_capacity=station_capacity),
        MGR,
    )
    return get_success_data(resp)


def create_teacher(full_name="Tara", certifications=("REFORMER",)):
    """Create a teacher (opens ACTIVE). Returns the Teacher resource dict."""
    resp = api_client.create_teacher(
        F.create_teacher_payload(full_name=full_name, certifications=list(certifications)),
        MGR,
    )
    return get_success_data(resp)


def create_intro_offer(name="Two Weeks Unlimited", price_cents=3000,
                       credits_total=-1, window_days=14):
    """Create an intro offer (opens ACTIVE). Returns the IntroOffer resource dict."""
    resp = api_client.create_intro_offer(
        {"name": name, "price_cents": price_cents,
         "credits_total": credits_total, "window_days": window_days},
        MGR,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: state progression — entitlements
# ---------------------------------------------------------------------------
def create_entitlement(member_id, kind="MEMBERSHIP", price_cents=10000,
                       credits_total=-1, cycle_start_utc="2026-02-01T00:00:00Z",
                       **overrides):
    """Create a PENDING entitlement. Returns the Entitlement resource dict."""
    resp = api_client.create_entitlement(
        F.create_entitlement_payload(
            member_id, kind=kind, price_cents=price_cents,
            credits_total=credits_total, cycle_start_utc=cycle_start_utc, **overrides),
        MGR,
    )
    return get_success_data(resp)


def create_active_entitlement(member_id, kind="MEMBERSHIP", price_cents=10000,
                              credits_total=-1, cycle_start_utc="2026-02-01T00:00:00Z",
                              **overrides):
    """Create then activate an entitlement (PENDING -> ACTIVE). Returns the ACTIVE
    Entitlement dict. Clock must already be at/after cycle_start_utc for activation."""
    ent = create_entitlement(member_id, kind=kind, price_cents=price_cents,
                             credits_total=credits_total,
                             cycle_start_utc=cycle_start_utc, **overrides)
    resp = api_client.activate_entitlement(ent["id"], MGR)
    return get_success_data(resp)


def setup_member_with_active_membership(email="m@x.com", cycle_start_utc="2026-02-01T00:00:00Z",
                                        price_cents=10000, credits_total=-1, **ent_overrides):
    """Create a member + an ACTIVE unlimited MEMBERSHIP. Returns (member, entitlement)."""
    member = create_member(email=email)
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP",
                                    price_cents=price_cents, credits_total=credits_total,
                                    cycle_start_utc=cycle_start_utc, **ent_overrides)
    return member, ent


# ---------------------------------------------------------------------------
# Tier 2: sessions
# ---------------------------------------------------------------------------
def create_session(room_id, teacher_id, discipline="REFORMER",
                   start_utc="2026-02-20T10:00:00Z", end_utc="2026-02-20T11:00:00Z",
                   published_capacity=4, **overrides):
    """Create a SCHEDULED class session. Returns the ClassSession dict."""
    resp = api_client.create_class_session(
        F.create_class_session_payload(
            room_id, teacher_id, discipline=discipline, start_utc=start_utc,
            end_utc=end_utc, published_capacity=published_capacity, **overrides),
        MGR,
    )
    return get_success_data(resp)


def create_published_session(room_id, teacher_id, discipline="REFORMER",
                             start_utc="2026-02-20T10:00:00Z", end_utc="2026-02-20T11:00:00Z",
                             published_capacity=4, **overrides):
    """Create + publish a session (SCHEDULED -> OPEN). Returns the published ClassSession dict
    (carries the post-publish version)."""
    session = create_session(room_id, teacher_id, discipline=discipline, start_utc=start_utc,
                             end_utc=end_utc, published_capacity=published_capacity, **overrides)
    resp = api_client.publish_class_session(session["id"], MGR)
    return get_success_data(resp)


def current_session_version(session_id):
    """Re-read a session's current version (used to supply a fresh OCC guard)."""
    data = get_success_data(api_client.get_class_session(session_id, MGR))
    return data["version"]


def book_reservation(member_id, session_id, entitlement_id, expected_version=None):
    """Book a reservation for `member_id`. If expected_version is None, re-reads the
    session's current version first. Returns the Reservation dict."""
    if expected_version is None:
        expected_version = current_session_version(session_id)
    resp = api_client.create_reservation(
        F.create_reservation_payload(member_id, session_id, entitlement_id, expected_version),
        make_member_headers(member_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------
def run_session_no_show(member_id, session_id, entitlement_id,
                        start_clock=None):
    """Book member onto a session and complete it with the reservation still BOOKED so it
    becomes NO_SHOW (mints a NO_SHOW FeeCharge, increments no_show_strike_count). The session
    is started/completed at `start_clock` (defaults to the session start time). Returns the
    Reservation dict as booked."""
    res = book_reservation(member_id, session_id, entitlement_id)
    if start_clock is not None:
        set_clock(start_clock)
    api_client.start_class_session(session_id, MGR)
    api_client.complete_class_session(session_id, MGR)
    return res


def attend_session(member_id, session_id, entitlement_id, start_clock):
    """Book + check-in + complete so the reservation reaches ATTENDED (flips the member's
    is_new_student to false). Returns the Reservation dict as booked."""
    res = book_reservation(member_id, session_id, entitlement_id)
    set_clock(start_clock)
    api_client.start_class_session(session_id, MGR)
    api_client.check_in_reservation(res["id"], make_member_headers(member_id))
    api_client.complete_class_session(session_id, MGR)
    return res


def make_member_established(member_id, room_id, teacher_id, entitlement_id,
                            discipline="VINYASA",
                            start_utc="2026-02-01T06:00:00Z",
                            end_utc="2026-02-01T07:00:00Z"):
    """Drive a member to is_new_student=false by attending one completed session.
    Restores the clock to 2026-02-01T00:00:00Z afterward. Returns nothing."""
    sess = create_published_session(room_id, teacher_id, discipline=discipline,
                                    start_utc=start_utc, end_utc=end_utc,
                                    published_capacity=1)
    attend_session(member_id, sess["id"], entitlement_id, start_clock=start_utc)
    set_clock("2026-02-01T00:00:00Z")


def drive_member_no_show_strikes(member_id, room_id, teacher_id, entitlement_id, count,
                                 discipline="VINYASA"):
    """Create `count` published sessions, book the member on each, and complete each with the
    member still BOOKED so each becomes a NO_SHOW. Builds the member's no_show_strike_count up
    to `count`. Sessions run at 2026-02-01 in sequential one-hour windows. Restores the clock
    to 2026-02-01T00:00:00Z afterward."""
    base_hour = 3
    for i in range(count):
        h1 = base_hour + i
        start = f"2026-02-01T{h1:02d}:00:00Z"
        end = f"2026-02-01T{h1+1:02d}:00:00Z" if h1 + 1 < 24 else "2026-02-01T23:59:00Z"
        sess = create_published_session(room_id, teacher_id, discipline=discipline,
                                        start_utc=start, end_utc=end, published_capacity=1)
        run_session_no_show(member_id, sess["id"], entitlement_id, start_clock=start)
    set_clock("2026-02-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Tier 4: fee charges
# ---------------------------------------------------------------------------
def get_member_fee_charges(member_id, params=None):
    """Return the list of a member's fee charges (data array)."""
    return get_success_data(api_client.list_member_fee_charges(member_id, MGR, params=params))


def first_fee_charge(member_id, params=None):
    """Return the first fee charge for a member (oldest by created_at, per §2.3 default sort)."""
    charges = get_member_fee_charges(member_id, params=params)
    assert charges, f"expected at least one fee charge for member {member_id}"
    return charges[0]


# ---------------------------------------------------------------------------
# Tier 5: workshops + enrollments
# ---------------------------------------------------------------------------
def create_workshop(room_id, lead_teacher_id, kind="WORKSHOP",
                    start_utc="2026-03-01T09:00:00Z", end_utc="2026-03-01T12:00:00Z",
                    seat_capacity=8, deposit_cents=2000, price_cents=8000, **overrides):
    """Create a DRAFT workshop. Returns the Workshop dict."""
    resp = api_client.create_workshop(
        F.create_workshop_payload(
            room_id, lead_teacher_id, kind=kind, start_utc=start_utc, end_utc=end_utc,
            seat_capacity=seat_capacity, deposit_cents=deposit_cents,
            price_cents=price_cents, **overrides),
        MGR,
    )
    return get_success_data(resp)


def create_published_workshop(room_id, lead_teacher_id, **overrides):
    """Create + publish a workshop (DRAFT -> OPEN). Returns the published Workshop dict
    (carries the post-publish version)."""
    workshop = create_workshop(room_id, lead_teacher_id, **overrides)
    resp = api_client.publish_workshop(workshop["id"], MGR)
    return get_success_data(resp)


def current_workshop_version(workshop_id):
    """Re-read a workshop's current version (used to supply a fresh OCC guard)."""
    data = get_success_data(api_client.get_workshop(workshop_id, MGR))
    return data["version"]


def apply_to_workshop(member_id, workshop_id):
    """Apply a member to a workshop (creates an APPLIED enrollment). Returns the Enrollment dict."""
    resp = api_client.create_enrollment(
        F.create_enrollment_payload(member_id, workshop_id),
        make_member_headers(member_id),
    )
    return get_success_data(resp)


def confirm_enrollment(member_id, enrollment_id, expected_workshop_version):
    """Confirm an APPLIED enrollment with an OCC guard. Returns the Enrollment dict."""
    resp = api_client.confirm_enrollment(
        enrollment_id,
        {"expected_workshop_version": expected_workshop_version},
        make_member_headers(member_id),
    )
    return get_success_data(resp)
