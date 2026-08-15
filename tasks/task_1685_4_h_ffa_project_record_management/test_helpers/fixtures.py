"""Composite setup helpers for multi-step test preconditions.

Every helper builds its preconditions from scratch against a fresh server using
only PRD-declared endpoints, and uses get_success_data() so a broken setup step
fails loudly with "Setup step failed" rather than a confusing assert.

Identity threading: Volunteer and Member are entity-backed roles, so every
ownership-gated or actor-recorded call is made with make_*_headers(entity_id)
— never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_animal_tag_payload,
    create_attendance_payload,
    create_award_application_payload,
    create_club_payload,
    create_fair_entry_payload,
    create_ledger_entry_payload,
    create_meeting_payload,
    create_member_payload,
    create_pen_payload,
    create_project_payload,
    create_record_book_payload,
    create_room_payload,
    create_scholarship_app_payload,
    create_stall_assignment_payload,
    create_treasury_transaction_payload,
    create_volunteer_payload,
    evaluate_award_payload,
    nominate_award_payload,
    set_clock_payload,
    submit_record_book_payload,
    complete_project_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_volunteer_headers

ADMIN = TEST_USERS["program_admin_headers"]


# ─── Tier 0: clock + simple creators ────────────────────────────────────────

def set_logical_clock(to_iso8601: str) -> dict:
    """Advance the program-year logical clock (ProgramAdmin-only)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def create_club(**overrides) -> dict:
    return get_success_data(api_client.create_club(create_club_payload(**overrides), ADMIN))


def create_volunteer(club_id: str, **overrides) -> dict:
    """Register a volunteer (PENDING). Returns the volunteer."""
    return get_success_data(
        api_client.create_volunteer(create_volunteer_payload(club_id, **overrides), ADMIN)
    )


def clear_volunteer(volunteer_id: str) -> dict:
    return get_success_data(api_client.clear_volunteer(volunteer_id, ADMIN))


def create_cleared_volunteer(club_id: str, **overrides) -> dict:
    """Register + clear a volunteer (score defaults make them clearable)."""
    vol = create_volunteer(club_id, **overrides)
    return clear_volunteer(vol["id"])


def create_denied_volunteer(club_id: str, **overrides) -> dict:
    vol = create_volunteer(club_id, **overrides)
    return get_success_data(api_client.deny_volunteer(vol["id"], ADMIN))


def create_member(club_id: str, acting_volunteer_id: str, **overrides) -> dict:
    """Enroll a member (ENROLLED, posture INELIGIBLE) as a volunteer."""
    return get_success_data(
        api_client.create_member(
            create_member_payload(club_id, **overrides),
            make_volunteer_headers(acting_volunteer_id),
        )
    )


def activate_member(member_id: str, volunteer_id: str) -> dict:
    return get_success_data(
        api_client.activate_member(member_id, make_volunteer_headers(volunteer_id))
    )


def create_active_member(club_id: str, volunteer_id: str, **overrides) -> dict:
    member = create_member(club_id, volunteer_id, **overrides)
    return activate_member(member["id"], volunteer_id)


def create_room(**overrides) -> dict:
    return get_success_data(api_client.create_room(create_room_payload(**overrides), ADMIN))


def create_pen(**overrides) -> dict:
    return get_success_data(api_client.create_pen(create_pen_payload(**overrides), ADMIN))


# ─── Tier 1: base world (club + two cleared volunteers + room) ──────────────

def setup_club_with_volunteers(**club_overrides) -> dict:
    """Club + two distinct CLEARED volunteers + one room.

    Two volunteers are needed wherever segregation of duties applies (award
    endorse must come from a different volunteer than the nominator).
    Returns {"club", "vol1", "vol2", "room"}.
    """
    club = create_club(**club_overrides)
    vol1 = create_cleared_volunteer(club["id"])
    vol2 = create_cleared_volunteer(club["id"])
    room = create_room()
    return {"club": club, "vol1": vol1, "vol2": vol2, "room": room}


# ─── Tier 2: member / project / record book pipelines ───────────────────────

def setup_active_member_with_project(
    ctx: dict,
    officer: bool = False,
    project_type: str = "FOODS",
    program_year: int = TEST_DEFAULTS["PROGRAM_YEAR"],
    birth_date: str = "2009-01-01",
) -> tuple:
    """ACTIVE member + ACTIVE project. Returns (member, project)."""
    member = create_active_member(
        ctx["club"]["id"], ctx["vol1"]["id"], is_club_officer=officer, birth_date=birth_date
    )
    project = get_success_data(
        api_client.create_project(
            create_project_payload(member["id"], project_type=project_type, program_year=program_year),
            make_member_headers(member["id"]),
        )
    )
    project = get_success_data(
        api_client.start_project(project["id"], make_member_headers(member["id"]))
    )
    return member, project


def create_draft_record_book_with_entry(
    project_id: str,
    member_id: str,
    entry_kind: str = "EXPENSE",
    amount_cents: int = 1000,
    hours: float = 0,
) -> dict:
    """DRAFT record book carrying one POSTED ledger line. Returns the book."""
    rb = get_success_data(
        api_client.create_record_book(
            create_record_book_payload(project_id), make_member_headers(member_id)
        )
    )
    get_success_data(
        api_client.create_ledger_entry(
            create_ledger_entry_payload(
                rb["id"], entry_kind=entry_kind, amount_cents=amount_cents, hours=hours
            ),
            make_member_headers(member_id),
        )
    )
    return rb


def submit_book(
    record_book: dict,
    member_id: str,
    scores: dict = None,
    submit_at: str = TEST_DEFAULTS["CLOCK_ON_TIME"],
) -> dict:
    """Set the logical clock, then submit the book with its current version.

    Returns the SUBMITTED record book.
    """
    set_logical_clock(submit_at)
    payload = submit_record_book_payload(record_book["version"], **(scores or {}))
    return get_success_data(
        api_client.submit_record_book(record_book["id"], payload, make_member_headers(member_id))
    )


def review_and_approve_book(record_book_id: str, volunteer_id: str) -> dict:
    """begin-review + approve as a CLEARED volunteer. Returns APPROVED book."""
    headers = make_volunteer_headers(volunteer_id)
    get_success_data(api_client.begin_review_record_book(record_book_id, headers))
    return get_success_data(api_client.approve_record_book(record_book_id, headers))


def build_approved_record_book(
    ctx: dict,
    member: dict,
    project: dict,
    scores: dict = None,
    submit_at: str = TEST_DEFAULTS["CLOCK_ON_TIME"],
    entry_kind: str = "EXPENSE",
    amount_cents: int = 1000,
    hours: float = 0,
) -> dict:
    """DRAFT book + one POSTED entry -> submit -> begin-review -> approve."""
    rb = create_draft_record_book_with_entry(
        project["id"], member["id"], entry_kind=entry_kind, amount_cents=amount_cents, hours=hours
    )
    submit_book(rb, member["id"], scores=scores, submit_at=submit_at)
    return review_and_approve_book(rb["id"], ctx["vol1"]["id"])


# ─── Tier 3: attendance + eligibility posture ───────────────────────────────

def record_attendance_and_hold(
    ctx: dict,
    member_id: str,
    dispositions: list,
    start_day: int = 1,
) -> list:
    """One meeting per disposition on consecutive June 2026 days in ctx's room;
    record the member's disposition at each; mark every meeting held.

    Marking held recomputes the posture of every ACTIVE member of the club.
    Returns the list of created meetings.
    """
    vol_headers = make_volunteer_headers(ctx["vol1"]["id"])
    meetings = []
    for i, disposition in enumerate(dispositions):
        day = start_day + i
        meeting = get_success_data(
            api_client.create_meeting(
                create_meeting_payload(
                    ctx["club"]["id"],
                    ctx["room"]["id"],
                    starts_at=f"2026-06-{day:02d}T10:00:00Z",
                    ends_at=f"2026-06-{day:02d}T11:00:00Z",
                ),
                vol_headers,
            )
        )
        get_success_data(
            api_client.create_attendance(
                create_attendance_payload(meeting["id"], member_id, attendance_status=disposition),
                vol_headers,
            )
        )
        get_success_data(api_client.mark_meeting_held(meeting["id"], vol_headers))
        meetings.append(meeting)
    return meetings


def tag_animal(
    project_id: str,
    member_id: str,
    species: str,
    owned_since: str,
    tag_number: str = None,
) -> dict:
    payload = create_animal_tag_payload(
        project_id, species=species, owned_since=owned_since, **({"tag_number": tag_number} if tag_number else {})
    )
    return get_success_data(api_client.create_animal_tag(payload, make_member_headers(member_id)))


def verify_tag(tag_id: str, volunteer_id: str) -> dict:
    return get_success_data(api_client.verify_animal_tag(tag_id, make_volunteer_headers(volunteer_id)))


def setup_eligible_member(
    ctx: dict = None,
    officer: bool = True,
    project_type: str = "FOODS",
    species: str = None,
    owned_since: str = "2026-06-01T00:00:00Z",
    dispositions: list = None,
) -> dict:
    """Member whose posture computes to ELIGIBLE once the book is approved:
    100% attendance (1 PRESENT of 1, meeting held), ACTIVE project, APPROVED
    record book, and a VERIFIED animal tag when a livestock species is given.

    Returns {"ctx", "member", "project", "record_book", "animal_tag"}.
    """
    ctx = ctx or setup_club_with_volunteers()
    member, project = setup_active_member_with_project(ctx, officer=officer, project_type=project_type)
    record_attendance_and_hold(ctx, member["id"], dispositions or ["PRESENT"])
    animal_tag = None
    if species is not None:
        animal_tag = verify_tag(
            tag_animal(project["id"], member["id"], species, owned_since)["id"], ctx["vol1"]["id"]
        )
    record_book = build_approved_record_book(ctx, member, project)
    return {
        "ctx": ctx,
        "member": member,
        "project": project,
        "record_book": record_book,
        "animal_tag": animal_tag,
    }


# ─── Tier 4: fair entries, stalls ───────────────────────────────────────────

def create_fair_entry(member_id: str, project_id: str, fair_level: str = "COUNTY") -> dict:
    return get_success_data(
        api_client.create_fair_entry(
            create_fair_entry_payload(member_id, project_id, fair_level=fair_level),
            make_member_headers(member_id),
        )
    )


def setup_confirmed_fair_entry(
    species: str = None,
    owned_since: str = "2026-06-01T00:00:00Z",
    fair_level: str = "COUNTY",
) -> dict:
    """ELIGIBLE member (livestock-tagged when species given) + ENTERED fair entry
    + volunteer confirmation. Returns the setup dict with "fair_entry" added."""
    project_type = species if species else "FOODS"
    setup = setup_eligible_member(project_type=project_type, species=species, owned_since=owned_since)
    fair_entry = create_fair_entry(setup["member"]["id"], setup["project"]["id"], fair_level)
    confirmed = get_success_data(
        api_client.confirm_fair_entry(
            fair_entry["id"], make_volunteer_headers(setup["ctx"]["vol1"]["id"])
        )
    )
    setup["fair_entry"] = confirmed
    return setup


# ─── Tier 5: award pipeline ─────────────────────────────────────────────────

def create_award_application(member_id: str, record_book_id: str, track: str = "DEGREE") -> dict:
    return get_success_data(
        api_client.create_award_application(
            create_award_application_payload(member_id, record_book_id, award_track=track),
            make_member_headers(member_id),
        )
    )


def nominate_award(application_id: str, club_id: str, volunteer_id: str) -> dict:
    """Nominate with a fresh expected_club_version read (the club's version
    advances on every STAR nomination, so it is re-read immediately before)."""
    club = get_success_data(api_client.get_club(club_id, make_volunteer_headers(volunteer_id)))
    return get_success_data(
        api_client.nominate_award_application(
            application_id,
            nominate_award_payload(club["version"]),
            make_volunteer_headers(volunteer_id),
        )
    )


def setup_nominated_award(ctx: dict, member: dict, record_book: dict, track: str = "DEGREE") -> dict:
    """DRAFT award application on an APPROVED book, nominated by vol1."""
    app = create_award_application(member["id"], record_book["id"], track)
    return nominate_award(app["id"], ctx["club"]["id"], ctx["vol1"]["id"])


def setup_endorsed_award(ctx: dict, member: dict, record_book: dict, track: str = "DEGREE") -> dict:
    """NOMINATED (vol1) then ENDORSED by a different volunteer (vol2)."""
    app = setup_nominated_award(ctx, member, record_book, track)
    return get_success_data(
        api_client.endorse_award_application(app["id"], make_volunteer_headers(ctx["vol2"]["id"]))
    )


def setup_evaluated_award(
    ctx: dict,
    member: dict,
    record_book: dict,
    track: str = "DEGREE",
    participation_pct: int = 100,
    leadership_pts: int = 15,
) -> dict:
    """ENDORSED then EVALUATED; rubric_score and award_tier land on the response."""
    app = setup_endorsed_award(ctx, member, record_book, track)
    return get_success_data(
        api_client.evaluate_award_application(
            app["id"],
            evaluate_award_payload(participation_pct, leadership_pts),
            make_volunteer_headers(ctx["vol1"]["id"]),
        )
    )


# ─── Tier 6: scholarship pipeline ───────────────────────────────────────────

def complete_project_with_grade(project_id: str, volunteer_id: str, grade: str) -> dict:
    return get_success_data(
        api_client.complete_project(
            project_id, complete_project_payload(grade), make_volunteer_headers(volunteer_id)
        )
    )


def setup_member_with_completed_projects(ctx: dict, member: dict, grades: list) -> list:
    """One COMPLETED project per grade (each with its own APPROVED record book).

    Returns [{"project", "record_book", "grade"}, ...] in the order of grades.
    Non-livestock project types keep the tag requirement out of scope.
    """
    non_livestock = ["FOODS", "CROPS", "ROBOTICS"]
    completed = []
    for i, grade in enumerate(grades):
        project = get_success_data(
            api_client.create_project(
                create_project_payload(
                    member["id"], project_type=non_livestock[i % len(non_livestock)]
                ),
                make_member_headers(member["id"]),
            )
        )
        project = get_success_data(
            api_client.start_project(project["id"], make_member_headers(member["id"]))
        )
        record_book = build_approved_record_book(ctx, member, project)
        project = complete_project_with_grade(project["id"], ctx["vol1"]["id"], grade)
        completed.append({"project": project, "record_book": record_book, "grade": grade})
    return completed


def setup_open_scholarship_app(
    ctx: dict,
    member: dict,
    record_book: dict,
    participation_pct: int = 100,
    leadership_pts: int = 15,
) -> dict:
    """SCHOLARSHIP-track award application on the given APPROVED book, evaluated
    (the given inputs yield GOLD or SILVER for the standard book scores), then a
    scholarship application linked to it. Returns the OPEN scholarship app."""
    award_app = setup_evaluated_award(
        ctx,
        member,
        record_book,
        track="SCHOLARSHIP",
        participation_pct=participation_pct,
        leadership_pts=leadership_pts,
    )
    return get_success_data(
        api_client.create_scholarship_app(
            create_scholarship_app_payload(member["id"], award_app["id"]),
            make_member_headers(member["id"]),
        )
    )


# ─── Tier 7: treasury ───────────────────────────────────────────────────────

def post_dues(club_id: str, volunteer_id: str, amount_cents: int) -> dict:
    """A POSTED dues payment; credits the club treasury immediately."""
    return get_success_data(
        api_client.create_treasury_transaction(
            create_treasury_transaction_payload(
                club_id, txn_kind="DUES_PAYMENT", amount_cents=amount_cents
            ),
            make_volunteer_headers(volunteer_id),
        )
    )


def post_reimbursement(club_id: str, volunteer_id: str, amount_cents: int) -> dict:
    """A POSTED expense reimbursement; does not touch the balance until approved."""
    return get_success_data(
        api_client.create_treasury_transaction(
            create_treasury_transaction_payload(
                club_id, txn_kind="EXPENSE_REIMBURSEMENT", amount_cents=amount_cents
            ),
            make_volunteer_headers(volunteer_id),
        )
    )


def get_club_balance(club_id: str, volunteer_id: str) -> int:
    club = get_success_data(api_client.get_club(club_id, make_volunteer_headers(volunteer_id)))
    return club["treasury_balance_cents"]
