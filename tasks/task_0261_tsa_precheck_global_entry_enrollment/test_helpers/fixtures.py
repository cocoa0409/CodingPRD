"""Composite setup helpers for the Trusted Traveler Enrollment API.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Helpers
use get_success_data() internally so a broken precondition surfaces a clear
"Setup step failed" error rather than a confusing assertion later.

Identity threading: the Applicant role is entity-backed, so every ownership-gated
applicant call uses make_applicant_headers(applicant["id"]) — never the shared
TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_program_payload,
    create_applicant_payload,
    create_center_payload,
    create_slot_payload,
    create_application_payload,
    pay_payload,
    background_check_payload,
    appointment_payload,
    biometric_payload,
)
from .test_users import TEST_USERS, make_applicant_headers


ADMIN = TEST_USERS["scheduling_admin_headers"]
VETTING = TEST_USERS["vetting_officer_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]
APPEALS = TEST_USERS["appeals_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Pin the deterministic server clock."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_program(**overrides):
    """Create a Program (defaults: PRECHECK base 7800, validity 5)."""
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), ADMIN)
    )


def create_applicant(**overrides):
    """Register an Applicant (defaults: US_CITIZEN)."""
    return get_success_data(
        api_client.create_applicant(create_applicant_payload(**overrides), ADMIN)
    )


def create_center(**overrides):
    """Create an OPEN EnrollmentCenter."""
    return get_success_data(
        api_client.create_center(create_center_payload(**overrides), ADMIN)
    )


def create_slot(center_id, **overrides):
    """Create an AVAILABLE AppointmentSlot at a center."""
    return get_success_data(
        api_client.create_slot(create_slot_payload(center_id, **overrides), ADMIN)
    )


def create_draft_application(applicant_id, **overrides):
    """Create a DRAFT Application owned by the applicant."""
    headers = make_applicant_headers(applicant_id)
    return get_success_data(
        api_client.create_application(
            create_application_payload(applicant_id, **overrides), headers
        )
    )


def get_application(application_id):
    """Re-read an Application (as admin) to capture its live version."""
    return get_success_data(api_client.get_application(application_id, ADMIN))


def app_version(application_id):
    """Return the live Application.version."""
    return get_application(application_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: program + applicant baseline
# ---------------------------------------------------------------------------

def setup_program_and_applicant(program_overrides=None, applicant_overrides=None,
                                with_clock=True):
    """Clock + Program + Applicant. Returns (program, applicant)."""
    if with_clock:
        set_clock()
    program = create_program(**(program_overrides or {}))
    applicant = create_applicant(**(applicant_overrides or {}))
    return program, applicant


# ---------------------------------------------------------------------------
# Tier 2: application lifecycle progression
# ---------------------------------------------------------------------------

def setup_submitted_application(program_overrides=None, applicant_overrides=None,
                                pay_amount=7800, with_clock=True):
    """Program + applicant + a SUBMITTED application that has paid `pay_amount`.

    Returns (program, applicant, application). When pay_amount is None, no
    payment is recorded (fee remains unpaid).
    """
    program, applicant = setup_program_and_applicant(
        program_overrides, applicant_overrides, with_clock=with_clock
    )
    app = create_draft_application(applicant["id"])
    headers = make_applicant_headers(applicant["id"])
    if pay_amount is not None:
        get_success_data(
            api_client.pay_application(app["id"], pay_payload(pay_amount), headers)
        )
    get_success_data(api_client.submit_application(app["id"], headers))
    return program, applicant, get_application(app["id"])


def setup_vetting_application(program_overrides=None, bg_overrides=None,
                             pay_amount=7800, with_clock=True):
    """Application advanced to VETTING with a PENDING BackgroundCheck.

    Returns (program, applicant, application, background_check).
    """
    program, applicant, app = setup_submitted_application(
        program_overrides=program_overrides, pay_amount=pay_amount, with_clock=with_clock
    )
    bc = get_success_data(
        api_client.create_background_check(
            app["id"], background_check_payload(**(bg_overrides or {})), VETTING
        )
    )
    return program, applicant, get_application(app["id"]), bc


def setup_cleared_application(program_overrides=None, bg_overrides=None,
                             pay_amount=7800, vetting_user_id=None, with_clock=True):
    """Application in VETTING with a CLEARED BackgroundCheck (adjudicated).

    bg_overrides default to criminal_hits=1 (risk 15, well below threshold) so
    adjudication clears. Returns (program, applicant, application, background_check).
    """
    bg = {"criminal_hits": 1}
    if bg_overrides:
        bg.update(bg_overrides)
    vetting_headers = (
        TEST_USERS["vetting_officer_headers"] if vetting_user_id is None
        else _vetting_headers(vetting_user_id)
    )
    program, applicant, app = setup_submitted_application(
        program_overrides=program_overrides, pay_amount=pay_amount, with_clock=with_clock
    )
    bc = get_success_data(
        api_client.create_background_check(app["id"], background_check_payload(**bg), vetting_headers)
    )
    get_success_data(api_client.adjudicate(app["id"], vetting_headers))
    return program, applicant, get_application(app["id"]), get_background_check(bc["id"])


def _vetting_headers(user_id):
    from .test_users import make_vetting_officer_headers
    return make_vetting_officer_headers(user_id)


def get_background_check(bc_id):
    return get_success_data(api_client.get_background_check(bc_id, VETTING))


# ---------------------------------------------------------------------------
# Tier 3: booking + appointment lifecycle
# ---------------------------------------------------------------------------

def setup_confirmed_appointment(program_overrides=None, center_overrides=None,
                                slot_overrides=None, with_clock=True):
    """CLEARED application + booked slot -> CONFIRMED Appointment,
    application advanced to INTERVIEW_SCHEDULED.

    Returns (program, applicant, application, center, slot, appointment).
    """
    if with_clock:
        set_clock()
    program = create_program(**(program_overrides or {}))
    center = create_center(**(center_overrides or {}))
    slot = create_slot(center["id"], **(slot_overrides or {}))
    applicant = create_applicant()
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api_client.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api_client.submit_application(app["id"], headers))
    get_success_data(
        api_client.create_background_check(
            app["id"], background_check_payload(criminal_hits=1), VETTING
        )
    )
    get_success_data(api_client.adjudicate(app["id"], VETTING))
    version = app_version(app["id"])
    appt = get_success_data(
        api_client.create_appointment(
            appointment_payload(app["id"], slot["id"], version), headers
        )
    )
    return (
        program, applicant, get_application(app["id"]),
        center, slot, appt,
    )


def book_appointment(application_id, slot_id, applicant_id):
    """Book an appointment for an already-CLEARED application against a slot,
    using the live application version. Returns the Appointment."""
    headers = make_applicant_headers(applicant_id)
    version = app_version(application_id)
    return get_success_data(
        api_client.create_appointment(
            appointment_payload(application_id, slot_id, version), headers
        )
    )


def setup_interview_complete(with_clock=True):
    """Application driven through to INTERVIEW_COMPLETE (accepted biometrics,
    completed interview). Returns (program, applicant, application, center,
    slot, appointment).
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment(
        with_clock=with_clock
    )
    get_success_data(
        api_client.create_biometric_capture(biometric_payload(appt["id"]), ENROLLMENT)
    )
    get_success_data(api_client.complete_appointment(appt["id"], ENROLLMENT))
    return program, applicant, get_application(app["id"]), center, slot, appt


def setup_approved_application(program_overrides=None, with_clock=True):
    """Full happy path to APPROVED with an ACTIVE KTN issued.

    Returns (program, applicant, application, center, slot, appointment, ktn).
    """
    if with_clock:
        set_clock()
    program = create_program(**(program_overrides or {}))
    center = create_center()
    slot = create_slot(center["id"])
    applicant = create_applicant()
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api_client.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api_client.submit_application(app["id"], headers))
    get_success_data(
        api_client.create_background_check(
            app["id"], background_check_payload(criminal_hits=1), VETTING
        )
    )
    get_success_data(api_client.adjudicate(app["id"], VETTING))
    version = app_version(app["id"])
    appt = get_success_data(
        api_client.create_appointment(
            appointment_payload(app["id"], slot["id"], version), headers
        )
    )
    get_success_data(
        api_client.create_biometric_capture(biometric_payload(appt["id"]), ENROLLMENT)
    )
    get_success_data(api_client.complete_appointment(appt["id"], ENROLLMENT))
    get_success_data(api_client.approve_application(app["id"], ENROLLMENT))
    ktns, _meta = _list_ktns(app["id"])
    ktn = ktns[0]
    return program, applicant, get_application(app["id"]), center, slot, appt, ktn


def _list_ktns(application_id):
    resp = api_client.list_application_ktns(application_id, ADMIN)
    body = resp.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 4: denial / appeal setup
# ---------------------------------------------------------------------------

def setup_denied_application(vetting_user_id="vetting-officer-1", with_clock=True):
    """Application DENIED via ADVERSE adjudication (watchlist_hits=2 -> risk 100).

    The adjudicating VettingOfficer id is pinned so segregation-of-duties tests
    can vary the appeals officer. Returns (program, applicant, application,
    background_check).
    """
    if with_clock:
        set_clock()
    program = create_program()
    applicant = create_applicant()
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api_client.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api_client.submit_application(app["id"], headers))
    vetting_headers = _vetting_headers(vetting_user_id)
    bc = get_success_data(
        api_client.create_background_check(
            app["id"], background_check_payload(watchlist_hits=2), vetting_headers
        )
    )
    get_success_data(api_client.adjudicate(app["id"], vetting_headers))
    return program, applicant, get_application(app["id"]), get_background_check(bc["id"])


def setup_appeal_pending(vetting_user_id="vetting-officer-1", with_clock=True):
    """Application DENIED then appeal filed -> APPEAL_PENDING, appeal OPEN.

    Returns (program, applicant, application, background_check, appeal).
    """
    program, applicant, app, bc = setup_denied_application(
        vetting_user_id=vetting_user_id, with_clock=with_clock
    )
    from .factories import appeal_payload
    headers = make_applicant_headers(applicant["id"])
    appeal = get_success_data(
        api_client.file_appeal(app["id"], appeal_payload(filed_reason="appeal"), headers)
    )
    return program, applicant, get_application(app["id"]), bc, appeal


# ---------------------------------------------------------------------------
# Tier 5: redress setup
# ---------------------------------------------------------------------------

def setup_vetting_with_redress_filed(watchlist_hits=1, match_strength_score=20,
                                     program_overrides=None, with_clock=True):
    """Application in VETTING with a scored BackgroundCheck and a FILED
    RedressCase against it (not yet resolved).

    Returns (program, applicant, application, background_check, redress).
    """
    from .factories import redress_payload
    program, applicant, app, bc = setup_vetting_application(
        program_overrides=program_overrides,
        bg_overrides={"watchlist_hits": watchlist_hits},
        with_clock=with_clock,
    )
    headers = make_applicant_headers(applicant["id"])
    redress = get_success_data(
        api_client.create_redress_case(
            redress_payload(app["id"], match_strength_score), headers
        )
    )
    return program, applicant, get_application(app["id"]), bc, redress


# ---------------------------------------------------------------------------
# Tier 6: multi-applicant / capacity setup
# ---------------------------------------------------------------------------

def setup_cleared_application_at_center(center_id, applicant_overrides=None):
    """Within an existing program/center context, create a fresh applicant whose
    application is CLEARED and ready to book. Returns (applicant, application).
    """
    applicant = create_applicant(**(applicant_overrides or {}))
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api_client.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api_client.submit_application(app["id"], headers))
    get_success_data(
        api_client.create_background_check(
            app["id"], background_check_payload(criminal_hits=1), VETTING
        )
    )
    get_success_data(api_client.adjudicate(app["id"], VETTING))
    return applicant, get_application(app["id"])
