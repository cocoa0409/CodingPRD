"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API process before every individual test, so the
database is empty at the start of every test — each fixture rebuilds its
preconditions from scratch using only PRD-declared endpoints.

Uses ``get_success_data()`` (lenient validator) internally so setup
failures surface as clear "Setup failed" errors rather than confusing
assertion failures inside the test body.

Identity threading (PRD §2.1): any fixture that creates a StudentAthlete
MUST thread that athlete's id through ``make_student_athlete_headers``
for any downstream athlete-role call (NIL deal proposal, offer accept /
decline, transfer-portal entry / withdraw). Coach identity is also
threaded when affiliation matters (PRD §3.4): the X-User-ID that stamps
an offer is the one allowed to send / withdraw it.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_program_payload,
    create_period_payload,
    create_student_athlete_payload,
    create_eligibility_certification_payload,
    deny_certification_payload,
    create_recruiting_contact_payload,
    create_scholarship_offer_payload,
    send_scholarship_offer_payload,
    create_nil_deal_payload,
    reject_nil_deal_payload,
    create_transfer_portal_entry_payload,
    match_transfer_portal_entry_payload,
    create_booster_incident_payload,
    sustain_booster_incident_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_student_athlete_headers,
    make_coach_headers,
    make_nil_reviewer_headers,
)


# ─── Clock primitive (PRD §2.8) ─────────────────────────


def set_clock(to_iso8601: str) -> None:
    """Pin the system clock for deterministic period selection / portal
    window logic (PRD §2.8)."""
    get_success_data(api_client.set_clock(
        set_clock_payload(to_iso8601),
        TEST_USERS["compliance_officer_headers"],
    ))


def sweep_portal_expirations() -> dict:
    """Run the idempotent portal-expiration sweep (PRD §2.8, §3.6)."""
    return get_success_data(api_client.sweep_portal_expirations(
        TEST_USERS["compliance_officer_headers"],
    ))


# ─── Primitive entity builders ──────────────────────────


def create_program(
    sport_code: str = "FOOTBALL",
    school_name: str = "Test University",
    scholarship_slot_cap: int = 85,
) -> dict:
    return get_success_data(api_client.create_program(
        create_program_payload(
            sport_code=sport_code,
            school_name=school_name,
            scholarship_slot_cap=scholarship_slot_cap,
        ),
        TEST_USERS["compliance_officer_headers"],
    ))


def create_period(
    program_id: str,
    period_type: str = "CONTACT",
    starts_at: str = "2026-06-01T00:00:00Z",
    ends_at: str = "2026-06-30T00:00:00Z",
) -> dict:
    return get_success_data(api_client.create_period(
        program_id,
        create_period_payload(
            period_type=period_type,
            starts_at=starts_at,
            ends_at=ends_at,
        ),
        TEST_USERS["compliance_officer_headers"],
    ))


def create_student_athlete(
    full_name: str = "Test Athlete",
    sport_code: str = "FOOTBALL",
    gpa: float = 3.500,
    amateurism_flag: Optional[bool] = True,
) -> dict:
    return get_success_data(api_client.create_student_athlete(
        create_student_athlete_payload(
            full_name=full_name,
            sport_code=sport_code,
            gpa=gpa,
            amateurism_flag=amateurism_flag,
        ),
        TEST_USERS["compliance_officer_headers"],
    ))


def submit_certification(student_athlete_id: str) -> dict:
    return get_success_data(api_client.create_eligibility_certification(
        create_eligibility_certification_payload(student_athlete_id),
        TEST_USERS["eligibility_center_headers"],
    ))


def approve_certification(cert_id: str) -> dict:
    return get_success_data(api_client.approve_eligibility_certification(
        cert_id, TEST_USERS["eligibility_center_headers"],
    ))


def deny_certification(cert_id: str, denial_reason: str = "GPA_BELOW_MIN") -> dict:
    return get_success_data(api_client.deny_eligibility_certification(
        cert_id,
        deny_certification_payload(denial_reason=denial_reason),
        TEST_USERS["eligibility_center_headers"],
    ))


def certify_athlete(athlete: dict) -> dict:
    """Walk the certification lifecycle to CERTIFIED.

    PRD §3.2: submit a certification on the athlete, then approve it; this
    flips the athlete's eligibility_status to CERTIFIED. Returns the
    approved certification.
    """
    cert = submit_certification(athlete["id"])
    return approve_certification(cert["id"])


# ─── Scholarship offer lifecycle helpers ────────────────


def create_draft_offer(
    program_id: str,
    student_athlete_id: str,
    annual_value_cents: int = 5_000_000,
    coach_user_id: Optional[str] = None,
) -> dict:
    """Create a DRAFT scholarship offer. If `coach_user_id` is supplied the
    offer is authored under that coach identity (PRD §3.4: the X-User-ID
    that stamps the offer becomes the one allowed to send / withdraw it)."""
    headers = (make_coach_headers(coach_user_id)
               if coach_user_id else TEST_USERS["coach_headers"])
    return get_success_data(api_client.create_scholarship_offer(
        create_scholarship_offer_payload(
            program_id=program_id,
            student_athlete_id=student_athlete_id,
            annual_value_cents=annual_value_cents,
        ),
        headers,
    ))


def send_offer(
    offer_id: str,
    expected_program_version: int,
    coach_user_id: Optional[str] = None,
) -> dict:
    headers = (make_coach_headers(coach_user_id)
               if coach_user_id else TEST_USERS["coach_headers"])
    return get_success_data(api_client.send_scholarship_offer(
        offer_id,
        send_scholarship_offer_payload(
            expected_program_version=expected_program_version,
        ),
        headers,
    ))


def create_and_send_offer(
    program: dict,
    athlete: dict,
    annual_value_cents: int = 5_000_000,
    coach_user_id: Optional[str] = None,
) -> Tuple[dict, dict]:
    """Create a DRAFT offer and immediately send it (DRAFT → SENT).

    Returns (sent_offer, refreshed_program). The athlete must already be
    CERTIFIED and the program must have a free slot (PRD §3.4).
    """
    offer = create_draft_offer(
        program["id"], athlete["id"],
        annual_value_cents=annual_value_cents,
        coach_user_id=coach_user_id,
    )
    sent = send_offer(offer["id"], program["version"], coach_user_id=coach_user_id)
    refreshed_program = get_success_data(api_client.get_program(
        program["id"], TEST_USERS["compliance_officer_headers"],
    ))
    return sent, refreshed_program


# ─── NIL deal lifecycle helpers ─────────────────────────


def create_nil_deal(
    athlete: dict,
    brand_name: str = "Test Brand",
    gross_value_cents: int = 100_000,
    agent_fee_pct: Optional[float] = 0.0,
) -> dict:
    """Athlete-role call; X-User-ID must equal athlete["id"] (PRD §2.1)."""
    return get_success_data(api_client.create_nil_deal(
        create_nil_deal_payload(
            student_athlete_id=athlete["id"],
            brand_name=brand_name,
            gross_value_cents=gross_value_cents,
            agent_fee_pct=agent_fee_pct,
        ),
        make_student_athlete_headers(athlete["id"]),
    ))


def submit_nil_deal(deal_id: str, reviewer_user_id: Optional[str] = None) -> dict:
    headers = (make_nil_reviewer_headers(reviewer_user_id)
               if reviewer_user_id else TEST_USERS["nil_reviewer_headers"])
    return get_success_data(api_client.submit_nil_deal_for_review(
        deal_id, headers,
    ))


def request_nil_deal_revision(deal_id: str,
                              reviewer_user_id: Optional[str] = None) -> dict:
    headers = (make_nil_reviewer_headers(reviewer_user_id)
               if reviewer_user_id else TEST_USERS["nil_reviewer_headers"])
    return get_success_data(api_client.request_nil_deal_revision(
        deal_id, headers,
    ))


# ─── Transfer portal helpers ────────────────────────────


def enter_portal(athlete: dict, source_program: dict) -> dict:
    return get_success_data(api_client.create_transfer_portal_entry(
        create_transfer_portal_entry_payload(
            student_athlete_id=athlete["id"],
            source_program_id=source_program["id"],
        ),
        make_student_athlete_headers(athlete["id"]),
    ))


# ─── Booster incident helpers ───────────────────────────


def report_incident(
    program: dict,
    athlete: dict,
    alleged_value_cents: int = 100_000,
    booster_name: str = "Test Booster",
) -> dict:
    return get_success_data(api_client.create_booster_incident(
        create_booster_incident_payload(
            program_id=program["id"],
            student_athlete_id=athlete["id"],
            booster_name=booster_name,
            alleged_value_cents=alleged_value_cents,
        ),
        TEST_USERS["compliance_officer_headers"],
    ))


def open_investigation(incident_id: str) -> dict:
    return get_success_data(api_client.open_investigation(
        incident_id, TEST_USERS["compliance_officer_headers"],
    ))


def sustain_incident(incident_id: str, expected_version: int) -> dict:
    return get_success_data(api_client.sustain_booster_incident(
        incident_id,
        sustain_booster_incident_payload(
            expected_boosterincident_version=expected_version,
        ),
        TEST_USERS["compliance_officer_headers"],
    ))


def report_and_sustain_incident(
    program: dict,
    athlete: dict,
    alleged_value_cents: int,
    booster_name: str = "Test Booster",
) -> dict:
    """Three-step walk REPORTED → INVESTIGATING → SUSTAINED.

    PRD §3.7 requires opening an investigation before sustaining, and
    sustain carries OCC on the incident's version.
    """
    inc = report_incident(program, athlete,
                          alleged_value_cents=alleged_value_cents,
                          booster_name=booster_name)
    investigating = open_investigation(inc["id"])
    return sustain_incident(inc["id"], investigating["version"])


# ─── Composite fixtures ─────────────────────────────────


def setup_certified_athlete(
    sport_code: str = "FOOTBALL",
    full_name: str = "Test Athlete",
    gpa: float = 3.500,
) -> dict:
    """Create + certify an athlete (PRD §3.2). Returns the certified athlete
    (re-fetched so eligibility_status reflects CERTIFIED)."""
    athlete = create_student_athlete(
        full_name=full_name, sport_code=sport_code, gpa=gpa,
    )
    cert = submit_certification(athlete["id"])
    approve_certification(cert["id"])
    return get_success_data(api_client.get_student_athlete(
        athlete["id"], TEST_USERS["compliance_officer_headers"],
    ))


def setup_program_with_certified_athlete(
    sport_code: str = "FOOTBALL",
    scholarship_slot_cap: int = 85,
    full_name: str = "Test Athlete",
) -> Tuple[dict, dict]:
    """Create a Program plus one CERTIFIED athlete in the same sport.

    The most common starting point for offer-lifecycle tests.
    """
    program = create_program(
        sport_code=sport_code,
        scholarship_slot_cap=scholarship_slot_cap,
    )
    athlete = setup_certified_athlete(sport_code=sport_code, full_name=full_name)
    return program, athlete


def setup_program_with_sent_offer(
    sport_code: str = "FOOTBALL",
    scholarship_slot_cap: int = 85,
    annual_value_cents: int = 5_000_000,
    coach_user_id: Optional[str] = None,
) -> Tuple[dict, dict, dict]:
    """Program + CERTIFIED athlete + offer in SENT.

    Returns (refreshed_program, athlete, sent_offer). The program has
    slots_committed == 1 after the send.
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code=sport_code, scholarship_slot_cap=scholarship_slot_cap,
    )
    offer, refreshed_program = create_and_send_offer(
        program, athlete,
        annual_value_cents=annual_value_cents,
        coach_user_id=coach_user_id,
    )
    return refreshed_program, athlete, offer


def setup_nil_deal_under_review(
    sport_code: str = "WBB",
    gross_value_cents: int = 200_000,
    agent_fee_pct: float = 0.0,
    submitter_user_id: Optional[str] = None,
) -> Tuple[dict, dict]:
    """CERTIFIED athlete + NIL deal walked through to UNDER_REVIEW.

    Returns (athlete, deal). The submitter's X-User-ID is recorded for the
    segregation-of-duties check at approval (PRD §3.5).
    """
    athlete = setup_certified_athlete(sport_code=sport_code)
    deal = create_nil_deal(
        athlete,
        gross_value_cents=gross_value_cents,
        agent_fee_pct=agent_fee_pct,
    )
    submit_nil_deal(deal["id"], reviewer_user_id=submitter_user_id)
    return athlete, get_success_data(api_client.get_nil_deal(
        deal["id"], TEST_USERS["nil_reviewer_headers"],
    ))


def setup_program_at_postseason_ban(
    sport_code: str = "FOOTBALL",
    scholarship_slot_cap: int = 85,
) -> Tuple[dict, dict, dict, dict]:
    """Drive a program all the way to penalty_tier == POSTSEASON_BAN.

    PRD §3.7 / §3.4: a weight-15 sustained incident (alleged_value_cents
    >= 2,500,000 ⇒ weight 15) by itself reaches the BAN_FLOOR of 15. The
    setup also creates one SENT offer that, post-sustain, cascade-withdraws.

    Returns (program, athlete, sent_offer_pre_cascade, sustained_incident).
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code=sport_code, scholarship_slot_cap=scholarship_slot_cap,
    )
    offer, program_after_send = create_and_send_offer(program, athlete)
    sustained = report_and_sustain_incident(
        program_after_send, athlete,
        alleged_value_cents=5_000_000,
    )
    return program_after_send, athlete, offer, sustained


def setup_program_at_level_one(
    sport_code: str = "MBB",
    scholarship_slot_cap: int = 13,
) -> Tuple[dict, dict, dict]:
    """Drive a program to penalty_tier == LEVEL_I via one weight-3 incident.

    PRD §3.7: total >= 1 and < 5 → LEVEL_I. An alleged_value of 100,000
    cents (≥ 50,000 and < 500,000) yields weight 3.

    Returns (program_after_sustain, athlete, sustained_incident).
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code=sport_code, scholarship_slot_cap=scholarship_slot_cap,
    )
    sustained = report_and_sustain_incident(
        program, athlete, alleged_value_cents=100_000,
    )
    refreshed = get_success_data(api_client.get_program(
        program["id"], TEST_USERS["compliance_officer_headers"],
    ))
    return refreshed, athlete, sustained


def setup_athlete_in_portal_window(
    entered_at_iso: str = "2026-01-01T00:00:00Z",
    sport_code: str = "MBB",
) -> Tuple[dict, dict, dict, dict]:
    """Clock + source program + destination program + CERTIFIED athlete
    in an ENTERED transfer portal entry.

    Returns (source_program, destination_program, athlete, entry).
    """
    set_clock(entered_at_iso)
    source = create_program(sport_code=sport_code, school_name="Source U")
    destination = create_program(sport_code=sport_code, school_name="Destination U")
    athlete = setup_certified_athlete(sport_code=sport_code)
    entry = enter_portal(athlete, source)
    return source, destination, athlete, entry
