"""Composite setup helpers.

Each test runs against a freshly restarted, empty server, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. Helpers use the
lenient get_success_data() validator so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_center_payload,
    create_agreement_payload,
    create_subject_payload,
    create_curriculum_level_payload,
    create_family_payload,
    create_student_payload,
    create_enrollment_payload,
    create_worksheet_payload,
    create_session_payload,
    create_attendance_payload,
    create_invoice_payload,
    unique_territory_code,
)
from .test_users import (
    make_franchise_admin_headers,
    make_center_director_headers,
    make_instructor_headers,
)

ADMIN = make_franchise_admin_headers()
DIRECTOR = make_center_director_headers()
INSTRUCTOR = make_instructor_headers()


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the logical clock; returns nothing useful (output is null)."""
    api_client.set_clock(iso, ADMIN)


# ---------------------------------------------------------------------------
# Tier 1: State progression — Center / Agreement
# ---------------------------------------------------------------------------
def create_center(**overrides) -> dict:
    """Create a PROVISIONING center. Returns the center."""
    resp = api_client.create_center(create_center_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_agreement(center_id, **overrides) -> dict:
    """Create a PENDING agreement for a center. Returns the agreement."""
    resp = api_client.create_agreement(create_agreement_payload(center_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_and_activate_center(clock="2026-05-01T00:00:00Z", agreement_overrides=None, **center_overrides):
    """Set clock -> create center -> create + activate agreement -> activate center
    (to OPERATING). Returns (center, agreement). Re-GETs the center after activation
    so the returned center reflects OPERATING status + bumped version.
    """
    if clock is not None:
        set_clock(clock)
    center = create_center(**center_overrides)
    agreement = create_agreement(center["id"], **(agreement_overrides or {}))
    get_success_data(api_client.activate_agreement(agreement["id"], ADMIN))
    get_success_data(api_client.activate_center(center["id"], ADMIN))
    center = get_success_data(api_client.get_center(center["id"], ADMIN))
    agreement = get_success_data(api_client.get_agreement(agreement["id"], ADMIN))
    return center, agreement


# ---------------------------------------------------------------------------
# Tier 2: Entity hierarchy — Subject / Level / Family / Student
# ---------------------------------------------------------------------------
def create_subject(center_id, **overrides) -> dict:
    resp = api_client.create_subject(create_subject_payload(center_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_level(subject_id, rank, **overrides) -> dict:
    resp = api_client.create_curriculum_level(
        create_curriculum_level_payload(subject_id, rank, **overrides), ADMIN)
    return get_success_data(resp)


def create_level_chain(subject_id, n, worksheets_to_master=2, mastery_score_threshold=80):
    """Create n curriculum levels (ranks 1..n) forming a prerequisite chain.
    Returns the list of level dicts in rank order."""
    levels = []
    prev = None
    for rank in range(1, n + 1):
        extra = {"worksheets_to_master": worksheets_to_master,
                 "mastery_score_threshold": mastery_score_threshold,
                 "label": f"L{rank}"}
        if prev is not None:
            extra["prereq_level_id"] = prev["id"]
        lvl = create_level(subject_id, rank, **extra)
        levels.append(lvl)
        prev = lvl
    return levels


def create_family(center_id, **overrides) -> dict:
    resp = api_client.create_family(create_family_payload(center_id, **overrides), DIRECTOR)
    return get_success_data(resp)


def create_student(family_id, **overrides) -> dict:
    resp = api_client.create_student(create_student_payload(family_id, **overrides), DIRECTOR)
    return get_success_data(resp)


def adjust_wallet(family_id, amount_cents, reason="GOODWILL_CREDIT") -> dict:
    resp = api_client.adjust_wallet(
        family_id, {"amount_cents": amount_cents, "reason": reason}, DIRECTOR)
    return get_success_data(resp)


def setup_operating_center_with_subject(num_levels=1, clock="2026-05-01T00:00:00Z",
                                        worksheets_to_master=2, mastery_score_threshold=80,
                                        **center_overrides):
    """OPERATING center + one subject + a chain of num_levels levels.
    Returns (center, agreement, subject, levels)."""
    center, agreement = create_and_activate_center(clock=clock, **center_overrides)
    subject = create_subject(center["id"])
    levels = create_level_chain(subject["id"], num_levels,
                                worksheets_to_master=worksheets_to_master,
                                mastery_score_threshold=mastery_score_threshold)
    return center, agreement, subject, levels


# ---------------------------------------------------------------------------
# Tier 3: Enrollment lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_enrollment(center_id, student_id, subject_id, **overrides) -> dict:
    resp = api_client.create_enrollment(
        create_enrollment_payload(center_id, student_id, subject_id, **overrides), DIRECTOR)
    return get_success_data(resp)


def place_enrollment(enrollment_id, placement_policy="STRICT", **payload_overrides) -> dict:
    payload = {"placement_policy": placement_policy}
    payload.update(payload_overrides)
    resp = api_client.place_enrollment(enrollment_id, payload, DIRECTOR)
    return get_success_data(resp)


def create_and_place_enrollment(center_id, student_id, subject_id,
                                diagnostic_raw_score=10, placement_policy="STRICT",
                                **create_overrides) -> dict:
    """Create an enrollment with a diagnostic score, then place it (-> ACTIVE).
    Returns the placed (ACTIVE) enrollment."""
    en = create_enrollment(center_id, student_id, subject_id,
                           diagnostic_raw_score=diagnostic_raw_score, **create_overrides)
    return place_enrollment(en["id"], placement_policy=placement_policy)


def setup_active_enrollment(diagnostic_raw_score=10, clock="2026-05-01T00:00:00Z",
                            worksheets_to_master=2, mastery_score_threshold=80,
                            placement_policy="STRICT", **center_overrides):
    """Most common base: OPERATING center + subject + one level + family + student +
    one ACTIVE enrollment. Returns (center, subject, level, family, student, enrollment)."""
    center, _agreement, subject, levels = setup_operating_center_with_subject(
        num_levels=1, clock=clock,
        worksheets_to_master=worksheets_to_master,
        mastery_score_threshold=mastery_score_threshold,
        **center_overrides)
    family = create_family(center["id"])
    student = create_student(family["id"])
    enrollment = create_and_place_enrollment(
        center["id"], student["id"], subject["id"],
        diagnostic_raw_score=diagnostic_raw_score, placement_policy=placement_policy)
    return center, subject, levels[0], family, student, enrollment


# ---------------------------------------------------------------------------
# Worksheets
# ---------------------------------------------------------------------------
def create_worksheet(enrollment_id, level_id, set_number=1, **overrides) -> dict:
    resp = api_client.create_worksheet(
        create_worksheet_payload(enrollment_id, level_id, set_number, **overrides), INSTRUCTOR)
    return get_success_data(resp)


def setup_active_enrollment_with_worksheet(set_number=1, **kwargs):
    """setup_active_enrollment + one ASSIGNED worksheet set.
    Returns (center, subject, level, family, student, enrollment, worksheet)."""
    center, subject, level, family, student, enrollment = setup_active_enrollment(**kwargs)
    worksheet = create_worksheet(enrollment["id"], level["id"], set_number)
    return center, subject, level, family, student, enrollment, worksheet


# ---------------------------------------------------------------------------
# Sessions / attendance
# ---------------------------------------------------------------------------
def create_session(center_id, start_at, end_at, seat_cap, instructor_user_id="instr-1", **overrides) -> dict:
    resp = api_client.create_session(
        create_session_payload(center_id, start_at, end_at, seat_cap,
                               instructor_user_id=instructor_user_id, **overrides), DIRECTOR)
    return get_success_data(resp)


def create_and_open_session(center_id, start_at, end_at, seat_cap, **overrides) -> dict:
    """Create a session then open it (-> OPEN). Returns the OPEN session (re-GET)."""
    sess = create_session(center_id, start_at, end_at, seat_cap, **overrides)
    get_success_data(api_client.open_session(sess["id"], DIRECTOR))
    return get_success_data(api_client.get_session(sess["id"], DIRECTOR))


def book_seat(session_id, enrollment_id) -> dict:
    """Book a seat using the current observed session version. Returns the
    AttendanceRecord. Re-reads the session version immediately before booking."""
    sess = get_success_data(api_client.get_session(session_id, DIRECTOR))
    resp = api_client.create_attendance_record(
        create_attendance_payload(session_id, enrollment_id, sess["version"]), DIRECTOR)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
def family_version(family_id) -> int:
    return get_success_data(api_client.get_family(family_id, DIRECTOR))["version"]


def create_invoice(family_id, center_id, period_month="2026-05", expected_family_version=None) -> dict:
    """Create a draft invoice. If expected_family_version is None, reads the
    family's current version first. Returns the DRAFT invoice."""
    if expected_family_version is None:
        expected_family_version = family_version(family_id)
    resp = api_client.create_invoice(
        create_invoice_payload(family_id, center_id, period_month, expected_family_version), DIRECTOR)
    return get_success_data(resp)


def create_and_issue_invoice(family_id, center_id, period_month="2026-05") -> dict:
    """Create then issue a draft invoice (-> ISSUED). Returns the ISSUED invoice (re-GET)."""
    inv = create_invoice(family_id, center_id, period_month)
    get_success_data(api_client.issue_invoice(inv["id"], DIRECTOR))
    return get_success_data(api_client.get_invoice(inv["id"], DIRECTOR))


def setup_issued_solo_invoice(monthly_tuition_cents=15000, enrollment_fee_cents=5000,
                              agreement_overrides=None, period_month="2026-05",
                              clock="2026-05-01T00:00:00Z"):
    """OPERATING center + family + student + one ACTIVE solo enrollment + an ISSUED
    invoice. Returns (center, agreement, family, student, enrollment, invoice)."""
    center, agreement, subject, levels = setup_operating_center_with_subject(
        num_levels=1, clock=clock,
        monthly_tuition_cents=monthly_tuition_cents,
        enrollment_fee_cents=enrollment_fee_cents,
        agreement_overrides=agreement_overrides)
    family = create_family(center["id"])
    student = create_student(family["id"])
    enrollment = create_and_place_enrollment(center["id"], student["id"], subject["id"])
    invoice = create_and_issue_invoice(family["id"], center["id"], period_month)
    return center, agreement, family, student, enrollment, invoice
