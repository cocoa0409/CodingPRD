"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database and
the logical clock at its startup default). Lenient get_success_data is used
internally so setup failures surface as clear "Setup failed" errors.

Ownership-gated calls thread the acting entity's id through
make_household_manager_headers / make_instructor_headers (PRD §2.1).
"""
from typing import Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_attendance_record_payload,
    create_class_meeting_payload,
    create_class_session_payload,
    create_household_payload,
    create_instructor_contract_payload,
    create_instructor_payload,
    create_participant_payload,
    create_payment_payload,
    create_program_payload,
    create_registration_payload,
    create_room_payload,
    create_safety_form_payload,
    create_scholarship_application_payload,
    create_season_payload,
)
from .test_users import (
    TEST_USERS,
    make_household_manager_headers,
    make_instructor_headers,
    make_scholarship_reviewer_headers,
)

# Opaque-operator header constants (PRD §2.1: not tied to any persisted entity).
PC = TEST_USERS["program_coordinator_headers"]
FD = TEST_USERS["front_desk_headers"]
FO = TEST_USERS["finance_officer_headers"]
REV1 = make_scholarship_reviewer_headers("rev-1")
REV2 = make_scholarship_reviewer_headers("rev-2")


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, PC))


# ---------------------------------------------------------------------------
# Catalog: seasons, programs, rooms, instructors (PRD §3.1)
# ---------------------------------------------------------------------------

def create_season(**overrides) -> dict:
    return get_success_data(api_client.create_season(create_season_payload(**overrides), PC))


def create_published_season(**overrides) -> dict:
    season = create_season(**overrides)
    return get_success_data(api_client.publish_season(season["id"], PC))


def create_program(season_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_program(create_program_payload(season_id, **overrides), PC)
    )


def create_room(**overrides) -> dict:
    return get_success_data(api_client.create_room(create_room_payload(**overrides), PC))


def create_instructor(**overrides) -> dict:
    return get_success_data(
        api_client.create_instructor(create_instructor_payload(**overrides), PC)
    )


# ---------------------------------------------------------------------------
# Sessions, meetings, contracts (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------

def create_class_session(program_id: str, instructor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_class_session(
            create_class_session_payload(program_id, instructor_id, **overrides), PC,
        )
    )


def create_contract(session_id: str, instructor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_instructor_contract(
            create_instructor_contract_payload(session_id, instructor_id, **overrides),
            PC,
        )
    )


def accept_contract(contract_id: str, instructor_id: str) -> dict:
    return get_success_data(
        api_client.accept_instructor_contract(
            contract_id, make_instructor_headers(instructor_id),
        )
    )


def add_meeting(session_id: str, room_id: str,
                starts_at: str = C.MEETING_START, ends_at: str = C.MEETING_END) -> dict:
    return get_success_data(
        api_client.create_class_meeting(
            create_class_meeting_payload(session_id, room_id, starts_at, ends_at), PC,
        )
    )


def publish_session(session_id: str) -> dict:
    """Publish a DRAFT session; returns the session payload with its fresh version."""
    return get_success_data(api_client.publish_class_session(session_id, PC))


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_class_session(session_id, PC))


def get_session_version(session_id: str) -> int:
    return get_session(session_id)["version"]


def setup_published_session(
    *,
    capacity: int = 5,
    min_enrollment: int = 1,
    fee_resident_cents: int = 5000,
    fee_nonresident_cents: int = 5000,
    enrollment_check_at: str = C.ENROLLMENT_CHECK_AT,
    meeting_times: Optional[Sequence[Tuple[str, str]]] = None,
    contract_overrides: Optional[Dict] = None,
    season_overrides: Optional[Dict] = None,
    program_overrides: Optional[Dict] = None,
    session_overrides: Optional[Dict] = None,
    clock: Optional[str] = C.GENERAL_WINDOW_CLOCK,
) -> dict:
    """Published season + program + room + instructor + session + ACCEPTED
    contract + meeting(s) + PUBLISHED session, with the logical clock moved
    into the general registration window. Returns all created entities plus
    the post-publish session version (the OCC token for the first registration).
    """
    season = create_published_season(**(season_overrides or {}))
    program = create_program(season["id"], **(program_overrides or {}))
    room = create_room()
    instructor = create_instructor()
    session_kwargs = dict(
        capacity=capacity,
        min_enrollment=min_enrollment,
        fee_resident_cents=fee_resident_cents,
        fee_nonresident_cents=fee_nonresident_cents,
        enrollment_check_at=enrollment_check_at,
    )
    session_kwargs.update(session_overrides or {})
    session = create_class_session(program["id"], instructor["id"], **session_kwargs)
    contract = create_contract(session["id"], instructor["id"],
                               **(contract_overrides or {}))
    times = meeting_times if meeting_times is not None else [(C.MEETING_START, C.MEETING_END)]
    meetings = [add_meeting(session["id"], room["id"], s, e) for s, e in times]
    accept_contract(contract["id"], instructor["id"])
    published = publish_session(session["id"])
    if clock is not None:
        set_clock(clock)
    return {
        "season": season,
        "program": program,
        "room": room,
        "instructor": instructor,
        "session": published,
        "contract": contract,
        "meetings": meetings,
        "session_version": published["version"],
    }


def setup_multi_session_catalog(
    session_specs: Sequence[Dict],
    *,
    season_overrides: Optional[Dict] = None,
    program_overrides: Optional[Dict] = None,
    clock: Optional[str] = C.GENERAL_WINDOW_CLOCK,
) -> dict:
    """Published season + one program + N sessions. Each spec is a dict with
    optional keys: title, capacity, min_enrollment, fee_resident_cents,
    fee_nonresident_cents, enrollment_check_at, meeting_times,
    contract_overrides, room_name, instructor_name, instructor_email.
    Every session gets its own room and instructor (so same-slot meetings in
    different sessions never conflict), an ACCEPTED contract, its meetings,
    and is PUBLISHED. Returns {"season", "program", "sessions": [ctx, ...]}
    where each ctx carries the post-publish session_version OCC token.
    """
    season = create_published_season(**(season_overrides or {}))
    program = create_program(season["id"], **(program_overrides or {}))
    sessions = []
    for index, spec in enumerate(session_specs):
        room = create_room(name=spec.get("room_name", f"Room {index + 1}"))
        instructor = create_instructor(
            full_name=spec.get("instructor_name", f"Instructor {index + 1}"),
            email=spec.get("instructor_email", f"instructor{index + 1}@example.org"),
        )
        session = create_class_session(
            program["id"],
            instructor["id"],
            title=spec.get("title", f"S{index + 1}"),
            capacity=spec.get("capacity", 5),
            min_enrollment=spec.get("min_enrollment", 1),
            fee_resident_cents=spec.get("fee_resident_cents", 5000),
            fee_nonresident_cents=spec.get("fee_nonresident_cents", 5000),
            enrollment_check_at=spec.get("enrollment_check_at", C.ENROLLMENT_CHECK_AT),
        )
        contract = create_contract(session["id"], instructor["id"],
                                   **(spec.get("contract_overrides") or {}))
        times = spec.get("meeting_times") or [(C.MEETING_START, C.MEETING_END)]
        meetings = [add_meeting(session["id"], room["id"], s, e) for s, e in times]
        accept_contract(contract["id"], instructor["id"])
        published = publish_session(session["id"])
        sessions.append({
            "session": published,
            "contract": contract,
            "meetings": meetings,
            "room": room,
            "instructor": instructor,
            "session_version": published["version"],
        })
    if clock is not None:
        set_clock(clock)
    return {"season": season, "program": program, "sessions": sessions}


def setup_household_with_scholarship(
    season_id: str,
    approved_pct: int,
    estimated_commitment_cents: int,
    count: int = 1,
    residency: Optional[str] = None,
    account_name: str = "Household",
    name_prefix: str = "Part",
    birth_dates: Optional[Sequence[str]] = None,
    **application_overrides,
) -> Tuple[dict, List[dict], dict]:
    """Household + participants + an APPROVED scholarship application for the
    season (PRD §3.5: start-review and approval by distinct reviewers)."""
    household, participants = setup_household_with_participants(
        count=count, residency=residency, account_name=account_name,
        birth_dates=birth_dates, name_prefix=name_prefix,
    )
    application = submit_and_approve_application(
        household["id"], season_id, approved_pct, estimated_commitment_cents,
        **application_overrides,
    )
    return household, participants, application


def activate_session_by_sweep(ctx: dict) -> dict:
    """Advance the clock to the session's enrollment check and run the season
    sweep; returns the sweep summary (PRD §3.9)."""
    set_clock(ctx["session"]["enrollment_check_at"])
    return run_sweep(ctx["season"]["id"])


def run_sweep(season_id: str) -> dict:
    return get_success_data(api_client.run_season_sweep(season_id, PC))


# ---------------------------------------------------------------------------
# Households and participants (PRD §3.4)
# ---------------------------------------------------------------------------

def create_household(account_name: str = "Household") -> dict:
    """Self-service creation: the minted id is the caller's X-User-ID thereafter."""
    return get_success_data(
        api_client.create_household(
            create_household_payload(account_name=account_name),
            make_household_manager_headers("self-service"),
        )
    )


def household_headers(household) -> dict:
    household_id = household["id"] if isinstance(household, dict) else household
    return make_household_manager_headers(household_id)


def verify_residency(household_id: str, residency_status: str) -> dict:
    return get_success_data(
        api_client.verify_residency(
            household_id, {"residency_status": residency_status}, FD,
        )
    )


def get_household(household_id: str) -> dict:
    return get_success_data(api_client.get_household(household_id, FO))


def get_household_credit(household_id: str) -> int:
    return get_household(household_id)["account_credit_cents"]


def add_participant(household_id: str, full_name: str = "Participant",
                    birth_date: str = C.ADULT_BIRTH_DATE) -> dict:
    return get_success_data(
        api_client.create_participant(
            create_participant_payload(
                household_id, full_name=full_name, birth_date=birth_date,
            ),
            make_household_manager_headers(household_id),
        )
    )


def setup_household_with_participants(
    count: int = 1,
    residency: Optional[str] = None,
    account_name: str = "Household",
    birth_dates: Optional[Sequence[str]] = None,
    name_prefix: str = "Part",
) -> Tuple[dict, List[dict]]:
    """Household (optionally residency-verified) plus `count` participants."""
    household = create_household(account_name)
    if residency is not None:
        verify_residency(household["id"], residency)
        household = get_household(household["id"])
    participants = []
    for i in range(count):
        birth_date = (birth_dates[i] if birth_dates else C.ADULT_BIRTH_DATE)
        participants.append(
            add_participant(household["id"], f"{name_prefix} {i + 1}", birth_date)
        )
    return household, participants


# ---------------------------------------------------------------------------
# Safety forms (PRD §3.4)
# ---------------------------------------------------------------------------

def submit_safety_form(participant_id: str, season_id: str, household_id: str,
                       signer_name: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_safety_form(
            create_safety_form_payload(participant_id, season_id, signer_name,
                                       **overrides),
            make_household_manager_headers(household_id),
        )
    )


def create_verified_safety_form(participant_id: str, season_id: str, household_id: str,
                                signer_name: str) -> dict:
    form = submit_safety_form(participant_id, season_id, household_id, signer_name)
    return get_success_data(api_client.verify_safety_form(form["id"], FD))


# ---------------------------------------------------------------------------
# Scholarship applications (PRD §3.5)
# ---------------------------------------------------------------------------

def submit_application(household_id: str, season_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_scholarship_application(
            create_scholarship_application_payload(household_id, season_id, **overrides),
            make_household_manager_headers(household_id),
        )
    )


def review_and_approve_application(application_id: str, approved_pct: int,
                                   estimated_commitment_cents: int) -> dict:
    """start-review by one reviewer, approve by a different one (PRD §3.5
    segregation of duties)."""
    get_success_data(api_client.start_review_scholarship_application(application_id, REV1))
    return get_success_data(
        api_client.approve_scholarship_application(
            application_id,
            {"approved_pct": approved_pct,
             "estimated_commitment_cents": estimated_commitment_cents},
            REV2,
        )
    )


def submit_and_approve_application(household_id: str, season_id: str, approved_pct: int,
                                   estimated_commitment_cents: int,
                                   **overrides) -> dict:
    application = submit_application(household_id, season_id, **overrides)
    return review_and_approve_application(
        application["id"], approved_pct, estimated_commitment_cents,
    )


# ---------------------------------------------------------------------------
# Registrations, payments, drops (PRD §3.6-§3.8)
# ---------------------------------------------------------------------------

def try_register(session_id: str, participant_id: str, household_id: str,
                 expected_class_session_version: int):
    """Raw registration attempt (may fail); the OCC token is supplied by the caller."""
    return api_client.create_registration(
        create_registration_payload(
            session_id, participant_id, expected_class_session_version,
        ),
        make_household_manager_headers(household_id),
    )


def register_participant(session_id: str, participant_id: str, household_id: str) -> dict:
    """Read the session's current version, then register (PRD §2.7 OCC)."""
    version = get_session_version(session_id)
    response = try_register(session_id, participant_id, household_id, version)
    return get_success_data(response)


def get_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_registration(registration_id, FO))


def pay_registration(registration_id: str, household_id: str,
                     amount_cents: Optional[int] = None,
                     method: str = "EXTERNAL") -> dict:
    """Pay the pinned fee in full (PRD §3.7); defaults to the registration's fee."""
    if amount_cents is None:
        amount_cents = get_registration(registration_id)["fee_charged_cents"]
    return get_success_data(
        api_client.pay_registration(
            registration_id,
            create_payment_payload(amount_cents, method),
            make_household_manager_headers(household_id),
        )
    )


def register_and_pay(session_id: str, participant_id: str, household_id: str,
                     method: str = "EXTERNAL") -> dict:
    registration = register_participant(session_id, participant_id, household_id)
    pay_registration(registration["id"], household_id, method=method)
    return get_registration(registration["id"])


def drop_registration(registration_id: str, household_id: str) -> dict:
    return get_success_data(
        api_client.drop_registration(
            registration_id, make_household_manager_headers(household_id),
        )
    )


def list_payments_for(registration_id: str) -> List[dict]:
    data = get_success_data(
        api_client.list_payments(FO, params={"registration_id": registration_id})
    )
    return data


def find_refund_transaction(registration_id: str) -> dict:
    """The registration's REFUND ledger entry (a CHARGE precedes its REFUND, PRD §3.7)."""
    refunds = [p for p in list_payments_for(registration_id) if p["type"] == "REFUND"]
    assert len(refunds) == 1, (
        f"Expected exactly one REFUND transaction for {registration_id}, "
        f"got {len(refunds)}"
    )
    return refunds[0]


# ---------------------------------------------------------------------------
# Attendance (PRD §3.9)
# ---------------------------------------------------------------------------

def mark_attendance(meeting_id: str, registration_id: str, instructor_id: str,
                    status: str = "PRESENT"):
    """Raw attendance attempt by the session's assigned instructor."""
    return api_client.create_attendance_record(
        create_attendance_record_payload(meeting_id, registration_id, status),
        make_instructor_headers(instructor_id),
    )


def mark_present(meeting_id: str, registration_id: str, instructor_id: str) -> dict:
    return get_success_data(mark_attendance(meeting_id, registration_id, instructor_id))


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_instructor_contract(contract_id, PC))
