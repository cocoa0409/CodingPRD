"""Composite setup helpers: multi-step API preconditions for tests.

Every helper builds its state from scratch against an empty database using
only PRD-declared endpoints, and uses get_success_data() so that a setup
failure surfaces as a clear "Setup step failed" message.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import STANDARD_DISCOUNTED_DUES_CENTS
from .factories import (
    attendance_record_entry,
    audition_decision_payload,
    create_audition_payload,
    create_booking_payload,
    create_committee_payload,
    create_concert_payload,
    create_contract_payload,
    create_grant_payload,
    create_invoice_payload,
    create_member_payload,
    create_payment_payload,
    create_piece_payload,
    create_pledge_payload,
    create_registration_payload,
    create_rehearsal_payload,
    create_score_payload,
    create_checkout_payload,
    create_season_payload,
    create_section_payload,
    create_tour_payload,
    create_venue_payload,
    grant_apply_payload,
    grant_decision_payload,
    score_audition_payload,
)
from .test_users import TEST_USERS, make_member_headers

PRES = TEST_USERS["president_headers"]
TREAS = TEST_USERS["treasurer_headers"]
DIR = TEST_USERS["director_headers"]
LIB = TEST_USERS["librarian_headers"]


# ----------------------------------------------------------------------
# Tier 1: clock, seasons, posture, sections
# ----------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (President)."""
    return get_success_data(api_client.set_clock(to_iso8601, PRES))


def create_season(**overrides) -> dict:
    """Create a season in DRAFT posture with the standard configuration."""
    season = get_success_data(
        api_client.create_season(create_season_payload(**overrides), PRES))
    return season


def advance_posture(season_id: str, posture: str) -> dict:
    return get_success_data(api_client.set_season_posture(season_id, posture, PRES))


def run_checkpoint(season_id: str) -> dict:
    """Read the season's current version, then run the OCC-guarded checkpoint."""
    season = get_success_data(api_client.get_season(season_id, PRES))
    return get_success_data(
        api_client.checkpoint_season(season_id, season["version"], PRES))


def create_section(season_id: str, voice_part="SOPRANO", target_min=1,
                   target_max=2) -> dict:
    return get_success_data(api_client.create_section(
        create_section_payload(season_id, voice_part, target_min, target_max),
        DIR))


def create_open_season_with_section(target_min=1, target_max=2,
                                    voice_part="SOPRANO", **season_overrides):
    """Season created and advanced to OPEN, plus one section.

    Returns (season, section).
    """
    season = create_season(**season_overrides)
    section = create_section(season["id"], voice_part, target_min, target_max)
    season = advance_posture(season["id"], "OPEN")
    return season, section


# ----------------------------------------------------------------------
# Tier 2: members, auditions, enrollment, activation
# ----------------------------------------------------------------------

def create_member(season_id: str, full_name="Ada Alto", email="ada@x.org") -> dict:
    return get_success_data(api_client.create_member(
        create_member_payload(season_id, full_name, email), DIR))


def book_audition(member_id: str, scheduled_at="2026-08-02T10:00:00Z") -> dict:
    return get_success_data(api_client.create_audition(
        create_audition_payload(member_id, scheduled_at), DIR))


def score_audition(audition_id: str, tone_score=8, pitch_score=7,
                   sight_score=9) -> dict:
    return get_success_data(api_client.score_audition(
        audition_id,
        score_audition_payload(tone_score, pitch_score, sight_score), DIR))


def decide_audition(audition_id: str, decision: str, section_id=None) -> dict:
    return get_success_data(api_client.decide_audition(
        audition_id, audition_decision_payload(decision, section_id), DIR))


def enroll_member(season_id: str, section_id: str, full_name="Ada Alto",
                  email="ada@x.org", scheduled_at="2026-08-02T10:00:00Z",
                  scores=(8, 7, 9)) -> dict:
    """Register -> audition -> score -> ACCEPT. Returns the ENROLLED member."""
    member = create_member(season_id, full_name, email)
    audition = book_audition(member["id"], scheduled_at)
    score_audition(audition["id"], *scores)
    decide_audition(audition["id"], "ACCEPT", section_id)
    return get_success_data(api_client.get_member(member["id"], DIR))


def issue_invoice(member_id: str) -> dict:
    return get_success_data(
        api_client.create_invoice(create_invoice_payload(member_id), TREAS))


def pay_dues(member_id: str, amount_cents=STANDARD_DISCOUNTED_DUES_CENTS,
             method="CARD") -> dict:
    return get_success_data(api_client.create_payment(
        create_payment_payload(member_id, amount_cents, method), TREAS))


def activate_member(season_id: str, section_id: str, full_name="Ada Alto",
                    email="ada@x.org", scheduled_at="2026-08-02T10:00:00Z",
                    scores=(8, 7, 9)) -> dict:
    """Enroll + issue invoice + pay the standard discounted dues in full.

    Returns the member after the ENROLLED -> ACTIVE bubble-up.
    """
    member = enroll_member(season_id, section_id, full_name, email,
                           scheduled_at, scores)
    issue_invoice(member["id"])
    pay_dues(member["id"])
    return get_success_data(api_client.get_member(member["id"], DIR))


def setup_rehearsing_season_with_active_member(**kwargs):
    """Season -> OPEN -> section -> ACTIVE member -> REHEARSING.

    Returns (season, section, member).
    """
    season, section = create_open_season_with_section(
        **{k: v for k, v in kwargs.items() if k in ("target_min", "target_max")})
    member = activate_member(season["id"], section["id"])
    season = advance_posture(season["id"], "REHEARSING")
    return season, section, member


# ----------------------------------------------------------------------
# Tier 2: rehearsals and attendance
# ----------------------------------------------------------------------

def create_rehearsal(season_id: str, scheduled_at: str,
                     location="Hall") -> dict:
    return get_success_data(api_client.create_rehearsal(
        create_rehearsal_payload(season_id, scheduled_at, location), DIR))


def record_attendance(rehearsal_id: str, records: list) -> dict:
    return get_success_data(
        api_client.record_attendance(rehearsal_id, records, DIR))


def record_member_attendance(rehearsal_id: str, member_id: str,
                             status: str) -> dict:
    return record_attendance(rehearsal_id,
                             [attendance_record_entry(member_id, status)])


def find_attendance_record(rehearsal_id: str, member_id: str) -> dict:
    resp = api_client.list_attendance_records(
        DIR, params={"rehearsal_id": rehearsal_id, "member_id": member_id})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"Expected one attendance record, got {len(data)}"
    return data[0]


# ----------------------------------------------------------------------
# Tier 2: music library
# ----------------------------------------------------------------------

def create_score(title="Mass in G", copy_count=2,
                 replacement_cost_cents=7000) -> dict:
    return get_success_data(api_client.create_score(
        create_score_payload(title, copy_count, replacement_cost_cents), LIB))


def checkout_score(score_id: str, member_id: str,
                   due_date="2026-08-10T00:00:00Z") -> dict:
    return get_success_data(api_client.create_checkout(
        create_checkout_payload(score_id, member_id, due_date), LIB))


# ----------------------------------------------------------------------
# Tier 2/3: venues, concerts, bookings, pieces, contracts
# ----------------------------------------------------------------------

def create_venue(name="Hall", capacity=100) -> dict:
    return get_success_data(
        api_client.create_venue(create_venue_payload(name, capacity), PRES))


def create_concert(season_id: str, title="Gala", expected_attendance=80) -> dict:
    return get_success_data(api_client.create_concert(
        create_concert_payload(season_id, title, expected_attendance), DIR))


def create_booking(concert_id: str, venue_id: str,
                   start_at="2026-09-10T18:00:00Z",
                   end_at="2026-09-10T21:00:00Z", deposit_cents=1000) -> dict:
    return get_success_data(api_client.create_booking(
        create_booking_payload(concert_id, venue_id, start_at, end_at,
                               deposit_cents), DIR))


def confirm_booking(booking_id: str) -> dict:
    return get_success_data(api_client.confirm_booking(booking_id, TREAS))


def create_piece(concert_id: str, title="Suite", duration_seconds=3600,
                 sequence_no=1, featured_member_ids=None,
                 guest_contract_id=None) -> dict:
    return get_success_data(api_client.create_piece(
        create_piece_payload(concert_id, title, duration_seconds, sequence_no,
                             featured_member_ids, guest_contract_id), DIR))


def create_contract(season_id: str, service_lines=None,
                    travel_stipend_cents=0, concert_id=None,
                    musician_name="Cellist") -> dict:
    return get_success_data(api_client.create_contract(
        create_contract_payload(season_id, musician_name, service_lines,
                                travel_stipend_cents, concert_id), DIR))


def offer_contract(contract_id: str, payload=None) -> dict:
    return get_success_data(
        api_client.offer_contract(contract_id, payload or {}, DIR))


def contract_in_state(season_id: str, target_state: str,
                      rate_cents=30000, concert_id=None,
                      approver_headers=None, payer_headers=None) -> dict:
    """Walk a contract DRAFT -> ... -> target_state.

    Supports DRAFT, OFFERED, COUNTERED (via OCC counter), ACCEPTED,
    APPROVED (approver_headers required) and PAID (approver+payer headers
    required and must differ).
    """
    contract = create_contract(
        season_id, service_lines=[{"kind": "CONCERT", "units": 1,
                                   "rate_cents": rate_cents}],
        concert_id=concert_id)
    if target_state == "DRAFT":
        return contract
    contract = offer_contract(contract["id"])
    if target_state == "OFFERED":
        return contract
    if target_state == "COUNTERED":
        return get_success_data(api_client.counter_contract(
            contract["id"],
            {"expected_guest_contract_version": contract["version"]}, DIR))
    contract = get_success_data(api_client.accept_contract(contract["id"], DIR))
    if target_state == "ACCEPTED":
        return contract
    contract = get_success_data(api_client.approve_contract(
        contract["id"], approver_headers or PRES))
    if target_state == "APPROVED":
        return contract
    contract = get_success_data(api_client.pay_contract(
        contract["id"], payer_headers or TREAS))
    return contract


def setup_concert_with_confirmed_booking(start_at="2026-09-10T18:00:00Z",
                                         end_at="2026-09-10T21:00:00Z",
                                         deposit_cents=1000):
    """REHEARSING season with ACTIVE member + venue + concert + CONFIRMED booking.

    Returns (season, section, member, venue, concert, booking).
    """
    season, section, member = setup_rehearsing_season_with_active_member()
    venue = create_venue()
    concert = create_concert(season["id"])
    booking = create_booking(concert["id"], venue["id"], start_at, end_at,
                             deposit_cents)
    booking = confirm_booking(booking["id"])
    return season, section, member, venue, concert, booking


# ----------------------------------------------------------------------
# Tier 2/3: tours and registrations
# ----------------------------------------------------------------------

def create_tour(season_id: str, seat_count=2, min_seats=1,
                transport_lodging_cost_cents=10000,
                departure_at="2026-12-01T00:00:00Z",
                return_at="2026-12-05T00:00:00Z") -> dict:
    return get_success_data(api_client.create_tour(
        create_tour_payload(season_id, seat_count=seat_count,
                            min_seats=min_seats,
                            transport_lodging_cost_cents=transport_lodging_cost_cents,
                            departure_at=departure_at, return_at=return_at),
        PRES))


def open_tour_registration(tour_id: str) -> dict:
    return get_success_data(
        api_client.transition_tour(tour_id, "OPEN_REGISTRATION", PRES))


def register_member_for_tour(tour_id: str, member_id: str) -> dict:
    """Member self-registration; member_id threads into X-User-ID."""
    return get_success_data(api_client.create_registration(
        create_registration_payload(tour_id), make_member_headers(member_id)))


def confirm_registration(registration_id: str) -> dict:
    return get_success_data(
        api_client.confirm_registration(registration_id, TREAS))


def setup_tour_open_with_active_members(num_members=2, seat_count=2,
                                        min_seats=1, cost=10000):
    """OPEN season with N dues-paid ACTIVE members and a REGISTRATION_OPEN tour.

    Returns (season, section, members, tour).
    """
    season, section = create_open_season_with_section(target_max=4)
    members = []
    for i in range(num_members):
        members.append(activate_member(
            season["id"], section["id"], full_name=f"M{i}",
            email=f"m{i}@x.org", scheduled_at=f"2026-08-02T1{i}:00:00Z"))
    tour = create_tour(season["id"], seat_count=seat_count,
                       min_seats=min_seats,
                       transport_lodging_cost_cents=cost)
    tour = open_tour_registration(tour["id"])
    return season, section, members, tour


# ----------------------------------------------------------------------
# Tier 2/3: scholarships, committees, pledges
# ----------------------------------------------------------------------

def create_grant(member_id: str, requested_cents=5000) -> dict:
    return get_success_data(api_client.create_grant(
        create_grant_payload(member_id, requested_cents), TREAS))


def approve_grant(grant_id: str, approved_cents=None) -> dict:
    return get_success_data(api_client.decide_grant(
        grant_id, grant_decision_payload("APPROVE", approved_cents), TREAS))


def apply_grant(grant_id: str, invoice_id: str, amount_cents=None) -> dict:
    return get_success_data(api_client.apply_grant(
        grant_id, grant_apply_payload(invoice_id, amount_cents), TREAS))


def create_committee(season_id: str, chair_member_id: str, name="Gala",
                     fundraising_goal_cents=50000) -> dict:
    return get_success_data(api_client.create_committee(
        create_committee_payload(season_id, chair_member_id, name,
                                 fundraising_goal_cents), PRES))


def activate_committee(committee_id: str) -> dict:
    return get_success_data(
        api_client.transition_committee(committee_id, "ACTIVATE", PRES))


def create_pledge(committee_id: str, donor_name="Donor A", amount_cents=5000,
                  recorder_headers=None) -> dict:
    return get_success_data(api_client.create_pledge(
        create_pledge_payload(committee_id, donor_name, amount_cents),
        recorder_headers or TREAS))


def setup_active_committee_with_pledges(goal_cents=50000):
    """OPEN season + ACTIVE chair member + ACTIVE committee.

    Returns (season, section, chair_member, committee).
    """
    season, section = create_open_season_with_section()
    chair = activate_member(season["id"], section["id"])
    committee = create_committee(season["id"], chair["id"],
                                 fundraising_goal_cents=goal_cents)
    committee = activate_committee(committee["id"])
    return season, section, chair, committee
