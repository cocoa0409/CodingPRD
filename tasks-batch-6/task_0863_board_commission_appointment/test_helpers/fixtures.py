"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Uses get_success_data() (lenient) so a setup failure surfaces as a clear
"Setup failed" rather than a confusing downstream assertion error.

Identity threading: Applicant is entity-backed, so every applicant-owned call
(submit / resubmit / file) uses make_applicant_headers(applicant["id"]).
AppointingAuthority and ConfirmingMember ids are threaded explicitly so
segregation-of-duties (nominator != confirmer) holds.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_board_payload, create_seat_payload, create_vacancy_payload,
    create_applicant_payload, create_application_payload,
    create_appointment_payload, create_meeting_payload,
    create_attendance_payload, create_removal_payload,
    create_reappointment_payload,
)
from .test_users import (
    TEST_USERS, make_clerk_headers, make_authority_headers,
    make_confirming_headers, make_ethics_headers, make_applicant_headers,
)

CLERK = TEST_USERS["clerk_headers"]


# ─── Primitives ───────────────────────────────────────────────
def set_clock(to_iso8601):
    """Advance the server logical clock (BoardClerk-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, CLERK))


def new_board(**overrides) -> dict:
    return get_success_data(api_client.create_board(create_board_payload(**overrides), CLERK))


def new_seat(board_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_seat(create_seat_payload(board_id, **overrides), CLERK))


def new_applicant(**overrides) -> dict:
    return get_success_data(
        api_client.create_applicant(create_applicant_payload(**overrides), CLERK))


def new_vacancy(seat_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_vacancy(create_vacancy_payload(seat_id, **overrides), CLERK))


def eligible_application(vacancy_id, applicant_id, residency_attested=True,
                        **app_overrides) -> dict:
    """Submit -> start-review -> decide-eligibility(true). Returns ELIGIBLE application."""
    app = get_success_data(api_client.create_application(
        create_application_payload(applicant_id, vacancy_id,
                                   residency_attested=residency_attested, **app_overrides),
        make_applicant_headers(applicant_id)))
    api_client.start_review(app["id"], CLERK)
    return get_success_data(
        api_client.decide_eligibility(app["id"], {"eligible": True}, CLERK))


def nominate(application_id, seat_id, term_start_date, seat_version,
             auth_id="auth-1") -> dict:
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(application_id, seat_id, term_start_date, seat_version),
        make_authority_headers(auth_id)))


def confirm(appointment_id, yes_votes=3, no_votes=0, cm_id="cm-1") -> dict:
    return get_success_data(api_client.confirm_appointment(
        appointment_id, {"yes_votes": yes_votes, "no_votes": no_votes},
        make_confirming_headers(cm_id)))


def seat_version(seat_id) -> int:
    return get_success_data(api_client.get_seat(seat_id, CLERK))["version"]


def term_for_seat(seat_id, status=None) -> dict:
    params = {"seat_id": seat_id}
    if status:
        params["status"] = status
    res = api_client.list_terms(CLERK, params=params)
    data = get_success_data(res)
    assert data, f"Setup failed: no term for seat {seat_id} (status={status})"
    return data[0]


def held_meeting(board_id, scheduled_date) -> dict:
    """Create -> post-notice -> hold. Requires clock >= scheduled_date."""
    m = get_success_data(
        api_client.create_meeting(create_meeting_payload(board_id, scheduled_date), CLERK))
    api_client.post_notice(m["id"], CLERK)
    return get_success_data(api_client.hold_meeting(m["id"], CLERK))


def record_attendance(term_id, meeting_id, presence) -> dict:
    return get_success_data(api_client.create_attendance(
        create_attendance_payload(term_id, meeting_id, presence), CLERK))


def disclosures_for_term(term_id, status=None) -> list:
    params = {"term_id": term_id}
    if status:
        params["status"] = status
    return get_success_data(api_client.list_disclosures(CLERK, params=params))


# ─── Composite: seat a member (the most-reused preamble) ──────
def setup_seated_member(board_overrides=None, seat_overrides=None,
                        applicant_overrides=None, clock=None,
                        term_start_date="2026-06-01T00:00:00Z",
                        yes_votes=3, no_votes=0, auth_id="auth-1", cm_id="cm-1"):
    """Board -> seat -> applicant -> vacancy -> eligible application -> nominate
    -> confirm -> fetch the resulting ACTIVE Term.

    Returns a SimpleNamespace(board, seat, applicant, application, appointment,
    term, auth_id, cm_id).
    """
    if clock is not None:
        set_clock(clock)
    board = new_board(**(board_overrides or {}))
    seat = new_seat(board["id"], **(seat_overrides or {}))
    applicant = new_applicant(**(applicant_overrides or {}))
    vacancy = new_vacancy(seat["id"])
    application = eligible_application(vacancy["id"], applicant["id"])
    appointment = nominate(application["id"], seat["id"], term_start_date,
                           seat["version"], auth_id=auth_id)
    confirmed = confirm(appointment["id"], yes_votes=yes_votes, no_votes=no_votes,
                        cm_id=cm_id)
    term = term_for_seat(seat["id"], status="ACTIVE")
    return SimpleNamespace(
        board=board, seat=seat, applicant=applicant, application=application,
        appointment=confirmed, term=term, vacancy=vacancy,
        auth_id=auth_id, cm_id=cm_id,
    )


def setup_nominated_appointment(board_overrides=None, seat_overrides=None,
                                applicant_overrides=None, clock=None,
                                term_start_date="2026-06-01T00:00:00Z",
                                auth_id="auth-1"):
    """Board -> seat -> applicant -> vacancy -> eligible application -> nominate.
    Stops at NOMINATED (no confirm). Returns SimpleNamespace(..., appointment)."""
    if clock is not None:
        set_clock(clock)
    board = new_board(**(board_overrides or {}))
    seat = new_seat(board["id"], **(seat_overrides or {}))
    applicant = new_applicant(**(applicant_overrides or {}))
    vacancy = new_vacancy(seat["id"])
    application = eligible_application(vacancy["id"], applicant["id"])
    appointment = nominate(application["id"], seat["id"], term_start_date,
                           seat["version"], auth_id=auth_id)
    return SimpleNamespace(
        board=board, seat=seat, applicant=applicant, application=application,
        vacancy=vacancy, appointment=appointment, auth_id=auth_id,
    )


def setup_initiated_removal(reason="FOR_CAUSE", clock="2026-06-05T00:00:00Z",
                            effective_date="2026-06-05T00:00:00Z",
                            board_overrides=None, ethics_id="ethics-1"):
    """Seat a member, then initiate a RemovalAction (INITIATED) via EthicsOfficer.
    Returns SimpleNamespace(scene=<seated-member>, removal)."""
    scene = setup_seated_member(clock=clock, board_overrides=board_overrides)
    removal = get_success_data(api_client.create_removal(
        create_removal_payload(scene.term["id"], reason, effective_date),
        make_ethics_headers(ethics_id)))
    scene.removal = removal
    return scene
