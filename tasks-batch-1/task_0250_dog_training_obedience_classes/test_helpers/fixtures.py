"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims need the system in a specific state reached by 5-20 API calls
(create owner -> dog -> vaccinate three types -> trainer -> series -> sessions -> open ->
enroll, then drive sessions/attendance/makeups). These helpers encapsulate the recurring
chains so tests focus on assertions.

Uses get_success_data() (lenient validator) internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading (PRD §2.1): after creating an entity-backed Owner/Trainer, every
ownership/assignment-gated call uses make_owner_headers(owner["id"]) /
make_trainer_headers(trainer["id"]) — never the shared TEST_USERS fallback.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_owner_payload, create_dog_payload, create_vaccination_payload,
    create_behavioral_intake_payload, create_trainer_payload, create_class_series_payload,
    create_class_session_payload, create_enrollment_payload, create_package_payload,
    create_makeup_booking_payload, mark_attendance_payload, set_clock_payload,
)
from .test_users import TEST_USERS, make_owner_headers, make_trainer_headers
from .constants import REQUIRED_VACCINES, DEFAULT_CLOCK_ISO

# Unique email generator so each owner created in a (fresh) DB is distinct within a test.
_email_counter = itertools.count(1)


def _unique_email(tag: str = "owner") -> str:
    return f"{tag}-{next(_email_counter)}@example.com"


# ─── Primitives ───────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    """Set the server's logical UTC clock (PRD §2.10). AdminManager-only."""
    res = api_client.set_clock(set_clock_payload(to_iso8601),
                               TEST_USERS["admin_manager_headers"])
    # Clock endpoint returns no resource body; just confirm it succeeded.
    assert res.status_code in (200, 204), f"Setup failed: set_clock -> {res.status_code} {res.text}"
    return res


def create_owner(**overrides):
    """Create an Owner. Returns the Owner dict."""
    payload = create_owner_payload(email=overrides.pop("email", _unique_email()), **overrides)
    res = api_client.create_owner(payload, TEST_USERS["front_desk_headers"])
    return get_success_data(res)


def create_trainer(certified_levels=None, handles_private=None, **overrides):
    """Create a Trainer (AdminManager-only). Returns the Trainer dict."""
    kwargs = dict(overrides)
    if certified_levels is not None:
        kwargs["certified_levels"] = certified_levels
    if handles_private is not None:
        kwargs["handles_private"] = handles_private
    res = api_client.create_trainer(create_trainer_payload(**kwargs),
                                    TEST_USERS["admin_manager_headers"])
    return get_success_data(res)


def create_dog(owner, **overrides):
    """Register a Dog owned by `owner` (owner_id must equal X-User-ID, so we thread the
    owner identity). Returns the Dog dict."""
    headers = make_owner_headers(owner["id"])
    res = api_client.create_dog(create_dog_payload(owner["id"], **overrides), headers)
    return get_success_data(res)


def vaccinate_fully(owner, dog, administered_on="2026-01-01", expires_on="2027-01-01"):
    """File RABIES + DHPP + BORDETELLA records covering the given window so the dog's
    vaccination_posture becomes COMPLIANT (PRD §3.2). Returns {vaccine_type: record}."""
    headers = make_owner_headers(owner["id"])
    records = {}
    for vt in REQUIRED_VACCINES:
        res = api_client.create_vaccination(
            dog["id"],
            create_vaccination_payload(vt, administered_on=administered_on, expires_on=expires_on),
            headers,
        )
        records[vt] = get_success_data(res)
    return records


def create_package(owner, tier="STARTER"):
    """Purchase a punch-card package for `owner` (PRD §3.12). Returns the Package dict."""
    headers = make_owner_headers(owner["id"])
    res = api_client.create_package(create_package_payload(owner["id"], tier), headers)
    return get_success_data(res)


def create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1,
                        list_price_cents=12000, credit_cost=2, **overrides):
    """Create a DRAFT ClassSeries (AdminManager-only). Returns the series dict."""
    payload = create_class_series_payload(
        level=level, modality=modality, capacity=capacity, session_count=session_count,
        list_price_cents=list_price_cents, credit_cost=credit_cost, **overrides)
    res = api_client.create_class_series(payload, TEST_USERS["admin_manager_headers"])
    return get_success_data(res)


def create_session(series, trainer, sequence_index, starts_at, ends_at, is_makeup_slot=False):
    """Create a ClassSession occurrence (AdminManager-only). Returns the session dict."""
    extra = {}
    if is_makeup_slot:
        extra["is_makeup_slot"] = True
    payload = create_class_session_payload(
        series["id"], trainer["id"], sequence_index=sequence_index,
        starts_at=starts_at, ends_at=ends_at, **extra)
    res = api_client.create_class_session(payload, TEST_USERS["admin_manager_headers"])
    return get_success_data(res)


def _default_sessions(series, trainer, count, makeup=False):
    """Create `count` regular sequential daily sessions (07-01.. 09:00-10:00) for a series.
    Returns list of session dicts. Optionally append a makeup slot a week later."""
    sessions = []
    for i in range(count):
        day = 1 + i
        s = create_session(
            series, trainer, sequence_index=i + 1,
            starts_at=f"2026-07-{day:02d}T09:00:00Z", ends_at=f"2026-07-{day:02d}T10:00:00Z")
        sessions.append(s)
    return sessions


def open_series(series):
    """Open a DRAFT series for enrollment (AdminManager-only). Returns the re-read series
    dict (so callers get the post-open version)."""
    res = api_client.open_class_series(series["id"], TEST_USERS["admin_manager_headers"])
    return get_success_data(res)


def get_series(series_id):
    """Re-read a series to pick up its current version / seats_available."""
    res = api_client.get_class_series(series_id, TEST_USERS["admin_manager_headers"])
    return get_success_data(res)


def enroll(owner, dog, series, payment_method="CASH", package_id=None, series_version=None):
    """Enroll `dog` into `series`, threading the owner's identity. If series_version is not
    supplied we read the live version first (always supplying a fresh expected_series_version).
    Returns the enrollment dict."""
    if series_version is None:
        series_version = get_series(series["id"])["version"]
    extra = {"payment_method": payment_method}
    if package_id is not None:
        extra["package_id"] = package_id
    payload = create_enrollment_payload(dog["id"], series["id"], series_version, **extra)
    res = api_client.create_enrollment(payload, make_owner_headers(owner["id"]))
    return get_success_data(res)


# ─── Tier 2: Standard enroll-ready bundle ──────────────────────────────────────
def setup_enroll_ready_group(session_count=1, list_price_cents=12000, credit_cost=2,
                             capacity=5, level="BASIC", prerequisite_level=None,
                             clock=DEFAULT_CLOCK_ISO):
    """Clock set; owner + fully-vaccinated dog; trainer certified for the level; an OPEN
    GROUP series with `session_count` sessions. Returns a dict bundle:
        {owner, dog, trainer, series, sessions} where series is post-open (carries version).
    """
    set_clock(clock)
    owner = create_owner()
    dog = create_dog(owner)
    vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=[level])
    series_kwargs = {}
    if prerequisite_level is not None:
        series_kwargs["prerequisite_level"] = prerequisite_level
    series = create_series_draft(
        level=level, modality="GROUP", capacity=capacity, session_count=session_count,
        list_price_cents=list_price_cents, credit_cost=credit_cost, **series_kwargs)
    sessions = _default_sessions(series, trainer, session_count)
    series = open_series(series)
    return {"owner": owner, "dog": dog, "trainer": trainer, "series": series, "sessions": sessions}


def setup_enroll_ready_private(session_count=1, list_price_cents=30000, credit_cost=4,
                               level="BASIC", clock=DEFAULT_CLOCK_ISO):
    """Clock set; owner + fully-vaccinated dog; private-capable trainer; an OPEN PRIVATE
    series (capacity 1). Returns {owner, dog, trainer, series, sessions}."""
    set_clock(clock)
    owner = create_owner()
    dog = create_dog(owner)
    vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=[level], handles_private=True)
    series = create_series_draft(
        level=level, modality="PRIVATE", capacity=1, session_count=session_count,
        list_price_cents=list_price_cents, credit_cost=credit_cost)
    sessions = _default_sessions(series, trainer, session_count)
    series = open_series(series)
    return {"owner": owner, "dog": dog, "trainer": trainer, "series": series, "sessions": sessions}


# ─── Tier 3: Attendance / progression shortcuts ────────────────────────────────
def attendance_for_session(session, headers):
    """Return the (single) auto-created EXPECTED AttendanceRecord for a session, by listing
    attendance filtered by session_id. Returns the first record dict."""
    res = api_client.list_attendance_records(headers, params={"session_id": session["id"]})
    data = get_success_data(res)
    assert data, f"Setup failed: no attendance records for session {session['id']}"
    return data[0]


def mark_present_and_complete(session, trainer):
    """Trainer flow for one session: start -> mark its attendance PRESENT -> complete.
    Threads the trainer identity. Returns the completed session dict."""
    t_headers = make_trainer_headers(trainer["id"])
    api_client.start_class_session(session["id"], t_headers)
    att = attendance_for_session(session, t_headers)
    api_client.mark_attendance(session["id"], mark_attendance_payload(att["id"], "PRESENT"), t_headers)
    res = api_client.complete_class_session(session["id"], t_headers)
    return get_success_data(res)


def setup_enrollment_with_attended_sessions(session_count, attend_n, list_price_cents=12000,
                                            credit_cost=2):
    """OPEN GROUP series with `session_count` sessions; one CASH enrollment with the first
    `attend_n` sessions marked PRESENT and completed. Returns
        {owner, dog, trainer, series, sessions, enrollment}.
    """
    bundle = setup_enroll_ready_group(
        session_count=session_count, list_price_cents=list_price_cents, credit_cost=credit_cost)
    enrollment = enroll(bundle["owner"], bundle["dog"], bundle["series"],
                        series_version=bundle["series"]["version"])
    for s in bundle["sessions"][:attend_n]:
        mark_present_and_complete(s, bundle["trainer"])
    bundle["enrollment"] = enrollment
    return bundle


# ─── Tier 4: Makeup-eligibility setup (cancel a session to produce MISSED_PROVIDER) ──
def setup_missed_provider_with_makeup_slot(makeup_trainer=None, makeup_starts="2026-07-08T09:00:00Z",
                                           makeup_ends="2026-07-08T10:00:00Z", level="BASIC"):
    """OPEN GROUP series (2 regular sessions + 1 makeup slot), one ACTIVE enrollment; session 1
    is cancelled, producing a MISSED_PROVIDER attendance. A makeup booking is REQUESTED against
    that attendance. Returns:
        {owner, dog, trainer, series, sessions, makeup_session, enrollment, missed_attendance, makeup_booking}.

    If `makeup_trainer` is supplied the makeup slot is assigned to that (distinct) trainer so the
    trainer-overlap check does not interfere; otherwise it reuses the series trainer at a non-
    conflicting time.
    """
    set_clock(DEFAULT_CLOCK_ISO)
    owner = create_owner()
    dog = create_dog(owner)
    vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=[level])
    series = create_series_draft(level=level, modality="GROUP", capacity=5, session_count=2,
                                 list_price_cents=12000, credit_cost=2)
    sess1 = create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    sess2 = create_session(series, trainer, 2, "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z")
    slot_trainer = makeup_trainer if makeup_trainer is not None else trainer
    makeup_session = create_session(series, slot_trainer, 3, makeup_starts, makeup_ends,
                                    is_makeup_slot=True)
    series = open_series(series)
    enrollment = enroll(owner, dog, series, series_version=series["version"])
    # Cancel session 1 -> its EXPECTED attendance becomes MISSED_PROVIDER (makeup_eligible).
    api_client.cancel_class_session(sess1["id"], TEST_USERS["admin_manager_headers"])
    missed_att = attendance_for_session(sess1, make_owner_headers(owner["id"]))
    res = api_client.create_makeup_booking(
        create_makeup_booking_payload(missed_att["id"], makeup_session["id"]),
        make_owner_headers(owner["id"]))
    makeup_booking = get_success_data(res)
    return {
        "owner": owner, "dog": dog, "trainer": trainer, "series": series,
        "sessions": [sess1, sess2], "makeup_session": makeup_session,
        "enrollment": enrollment, "missed_attendance": missed_att, "makeup_booking": makeup_booking,
    }
