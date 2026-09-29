"""Composite setup builders.

The pytest fixtures themselves live in the suite's conftest; everything here is
a plain builder function, because most tests need several instances of the same
shape with different data.  Every builder asserts its own success status, so a
test that reaches its trigger knows its setup landed.
"""
from prd_bench_local_runner.testing import validate_success

from . import constants as C
from . import factories as F
from .test_users import (
    SECRETARY,
    STAFF,
    make_committee_chair_headers,
    make_committee_member_headers,
    make_search_firm_partner_headers,
    make_seated_director_headers,
)


# ---------------------------------------------------------------------------
# Governing policy
# ---------------------------------------------------------------------------
def adopt_policy(client, **overrides):
    """Adopt a governance policy with every knob stated explicitly."""
    return validate_success(
        client.adopt_policy(F.policy_payload(**overrides), SECRETARY), 201
    )


# ---------------------------------------------------------------------------
# Single records
# ---------------------------------------------------------------------------
def new_skill_category(client, **kwargs):
    return validate_success(
        client.create_skill_category(F.skill_category_payload(**kwargs), SECRETARY), 201
    )


def new_search_firm(client, **kwargs):
    return validate_success(
        client.create_search_firm(F.search_firm_payload(**kwargs), SECRETARY), 201
    )


def new_external_company(client, **kwargs):
    return validate_success(
        client.create_external_company(F.external_company_payload(**kwargs), SECRETARY),
        201,
    )


def new_public_companies(client, count):
    """`count` distinct public external companies."""
    return [new_external_company(client, is_public=True) for _ in range(count)]


def new_director(client, **kwargs):
    return validate_success(
        client.create_director(F.director_payload(**kwargs), SECRETARY), 201
    )


def new_seated_director(client, **kwargs):
    kwargs.setdefault("initial_service_status", "SEATED")
    return new_director(client, **kwargs)


def new_onboarding_director(client, **kwargs):
    kwargs["initial_service_status"] = "ONBOARDING"
    return new_director(client, **kwargs)


def new_candidate(client, **kwargs):
    return validate_success(
        client.create_candidate(F.candidate_payload(**kwargs), STAFF), 201
    )


def new_search_firm_candidate(client, firm_id, **kwargs):
    kwargs["source_channel"] = "SEARCH_FIRM"
    kwargs["search_firm_id"] = firm_id
    return new_candidate(client, **kwargs)


def new_committee(client, **kwargs):
    return validate_success(
        client.create_committee(F.committee_payload(**kwargs), SECRETARY), 201
    )


def new_slate(client, **kwargs):
    return validate_success(client.create_slate(F.slate_payload(**kwargs), SECRETARY), 201)


def new_onboarding_item(client, director_id, **kwargs):
    return validate_success(
        client.create_onboarding_item(
            director_id, F.onboarding_item_payload(**kwargs), SECRETARY
        ),
        201,
    )


def new_comp_award(client, director_id, **kwargs):
    return validate_success(
        client.create_comp_award(director_id, F.comp_award_payload(**kwargs), SECRETARY),
        201,
    )


def finalize_award(client, award_id):
    return validate_success(client.finalize_comp_award(award_id, SECRETARY))


# ---------------------------------------------------------------------------
# Outside seats
# ---------------------------------------------------------------------------
def seat_director_on_board(client, director_id, company_id, **kwargs):
    return validate_success(
        client.create_external_directorship(
            F.external_directorship_payload(
                company_id, director_id=director_id, **kwargs
            ),
            SECRETARY,
        ),
        201,
    )


def seat_candidate_on_board(client, candidate_id, company_id, **kwargs):
    return validate_success(
        client.create_external_directorship(
            F.external_directorship_payload(
                company_id, candidate_id=candidate_id, **kwargs
            ),
            SECRETARY,
        ),
        201,
    )


def give_director_boards(client, director_id, company_ids):
    return [seat_director_on_board(client, director_id, cid) for cid in company_ids]


def give_candidate_boards(client, candidate_id, company_ids):
    return [seat_candidate_on_board(client, candidate_id, cid) for cid in company_ids]


# ---------------------------------------------------------------------------
# Candidate pipeline walkers
# ---------------------------------------------------------------------------
def open_screen(client, candidate_id, **screen_kwargs):
    """Open a screen; from SOURCED this also moves the candidate to SCREENING."""
    return validate_success(
        client.create_screen(candidate_id, F.screen_payload(**screen_kwargs), STAFF), 201
    )


def submit_screen(client, screen_id):
    return validate_success(client.submit_screen(screen_id, STAFF), 200)


def determine_screen(client, screen_id, chair_headers):
    return validate_success(client.determine_screen(screen_id, chair_headers), 200)


def screen_candidate(client, candidate_id, chair_headers, **screen_kwargs):
    """Walk one screen all the way to a determination and return the screen row."""
    screen = open_screen(client, candidate_id, **screen_kwargs)
    submit_screen(client, screen["id"])
    return determine_screen(client, screen["id"], chair_headers)


def advance_to_screen_passed(client, candidate_id, chair_headers):
    """Clean screen: candidate ends at SCREEN_PASSED with INDEPENDENT."""
    screen_candidate(client, candidate_id, chair_headers)
    return validate_success(client.get_candidate(candidate_id, STAFF), 200)


def schedule_interview(client, candidate_id, interviewer_director_id, start_at, end_at, **kwargs):
    return validate_success(
        client.schedule_interview(
            F.interview_payload(
                candidate_id, interviewer_director_id, start_at=start_at, end_at=end_at, **kwargs
            ),
            STAFF,
        ),
        201,
    )


def complete_interview(client, interview_id, score=4, recommendation="ADVANCE"):
    return validate_success(
        client.complete_interview(
            interview_id, F.interview_completion_payload(score, recommendation), STAFF
        ),
        200,
    )


# Distinct, non-overlapping one-hour windows so an interviewer's calendar stays clean.
def interview_window(slot):
    """A distinct one-hour window per slot number, so calendars never collide."""
    day = 3 + (slot % 20)
    month = 3 + (slot // 20)
    return (
        "2026-{:02d}-{:02d}T09:00:00Z".format(month, day),
        "2026-{:02d}-{:02d}T10:00:00Z".format(month, day),
    )


def run_interviews(client, candidate_id, interviewer_director_ids, scores, first_slot=0):
    """One completed session per score, each on its own interviewer and window.

    `first_slot` shifts the window block so several candidates can share one
    interviewer without ever overlapping that interviewer's calendar.
    """
    sessions = []
    for index, score in enumerate(scores):
        interviewer = interviewer_director_ids[index % len(interviewer_director_ids)]
        start_at, end_at = interview_window(first_slot + index)
        session = schedule_interview(client, candidate_id, interviewer, start_at, end_at)
        sessions.append(complete_interview(client, session["id"], score=score))
    return sessions


def record_reference_check(client, candidate_id, reference_count=3, adverse_findings=False):
    return validate_success(
        client.record_reference_check(
            candidate_id, F.reference_check_payload(reference_count, adverse_findings), STAFF
        ),
        200,
    )


def run_conflict_clearance(client, candidate_id, chair_headers):
    return validate_success(client.run_conflict_clearance(candidate_id, chair_headers), 200)


def advance_to_slate_eligible(
    client,
    candidate_id,
    chair_headers,
    interviewer_director_ids,
    scores=(4, 4, 4),
    first_slot=0,
):
    """SOURCED -> SLATE_ELIGIBLE: screen, interviews, reference check, clearance."""
    advance_to_screen_passed(client, candidate_id, chair_headers)
    run_interviews(
        client, candidate_id, list(interviewer_director_ids), list(scores), first_slot=first_slot
    )
    record_reference_check(client, candidate_id)
    return run_conflict_clearance(client, candidate_id, chair_headers)


# ---------------------------------------------------------------------------
# Slate assembly
# ---------------------------------------------------------------------------
def add_nominee(client, slate_id, expected_slate_version, ballot_order, **kwargs):
    return validate_success(
        client.add_slate_nominee(
            slate_id,
            F.nominee_payload(expected_slate_version, ballot_order, **kwargs),
            STAFF,
        ),
        201,
    )


def slate_version(client, slate_id):
    return validate_success(client.get_slate(slate_id, STAFF), 200)["version"]


def add_candidate_nominee(client, slate_id, candidate_id, ballot_order):
    """Add a candidate nominee, reading the slate version immediately beforehand."""
    return add_nominee(
        client,
        slate_id,
        slate_version(client, slate_id),
        ballot_order,
        candidate_id=candidate_id,
    )


def add_incumbent_nominee(client, slate_id, director_id, ballot_order):
    return add_nominee(
        client,
        slate_id,
        slate_version(client, slate_id),
        ballot_order,
        incumbent_director_id=director_id,
    )


def submit_slate(client, slate_id):
    return validate_success(client.submit_slate_for_review(slate_id, STAFF), 200)


def cast_ballot(client, slate_id, voting_director_id, ballot, member_headers):
    return validate_success(
        client.cast_vote(slate_id, F.vote_payload(voting_director_id, ballot), member_headers),
        201,
    )


def cast_ballots(client, slate_id, ballots_by_director_id):
    """`ballots_by_director_id` is an iterable of (director_id, ballot) pairs."""
    return [
        cast_ballot(
            client, slate_id, director_id, ballot, make_committee_member_headers(director_id)
        )
        for director_id, ballot in ballots_by_director_id
    ]


def decide_slate(client, slate_id, chair_headers, decision="APPROVE"):
    return validate_success(
        client.decide_slate(slate_id, F.decision_payload(decision), chair_headers), 200
    )


def file_slate(client, slate_id):
    return validate_success(client.file_slate(slate_id, SECRETARY), 200)


def record_election(client, slate_id, elected_nominee_ids):
    return validate_success(
        client.record_election(slate_id, F.election_payload(elected_nominee_ids), SECRETARY),
        200,
    )


# ---------------------------------------------------------------------------
# Committee assembly
# ---------------------------------------------------------------------------
def committee_version(client, committee_id):
    return validate_success(client.get_committee(committee_id, SECRETARY), 200)["version"]


def propose_assignment(client, committee_id, director_id, **kwargs):
    return validate_success(
        client.create_assignment(
            committee_id,
            F.assignment_payload(director_id, committee_version(client, committee_id), **kwargs),
            SECRETARY,
        ),
        201,
    )


def activate_assignment(client, assignment_id):
    return validate_success(client.activate_assignment(assignment_id, SECRETARY), 200)


def revoke_assignment(client, assignment_id):
    return validate_success(client.revoke_assignment(assignment_id, SECRETARY), 200)


def seat_assignment(client, committee_id, director_id, **kwargs):
    """Propose and immediately activate one assignment."""
    assignment = propose_assignment(client, committee_id, director_id, **kwargs)
    return activate_assignment(client, assignment["id"])


# ---------------------------------------------------------------------------
# Onboarding and seating
# ---------------------------------------------------------------------------
def complete_item(client, item_id, headers=None):
    return validate_success(
        client.complete_onboarding_item(item_id, headers if headers else SECRETARY), 200
    )


def waive_item(client, item_id, reason="Equivalent prior training on file."):
    return validate_success(
        client.waive_onboarding_item(item_id, F.waiver_payload(reason), SECRETARY), 200
    )


def seat_director(client, director_id):
    return validate_success(client.seat_director(director_id, SECRETARY), 200)


def record_departure(client, director_id, notice_type="RESIGNATION"):
    return validate_success(
        client.record_departure_notice(
            director_id, F.departure_notice_payload(notice_type), SECRETARY
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Clock and reads
# ---------------------------------------------------------------------------
def set_clock(client, current_utc):
    return validate_success(client.set_clock(F.clock_payload(current_utc), SECRETARY), 200)


def get_candidate(client, candidate_id):
    return validate_success(client.get_candidate(candidate_id, STAFF), 200)


def get_director(client, director_id):
    return validate_success(client.get_director(director_id, SECRETARY), 200)


def get_slate(client, slate_id):
    return validate_success(client.get_slate(slate_id, STAFF), 200)


def get_nominee(client, nominee_id):
    return validate_success(client.get_slate_nominee(nominee_id, STAFF), 200)


def get_committee(client, committee_id):
    return validate_success(client.get_committee(committee_id, SECRETARY), 200)


def get_assignment(client, assignment_id):
    return validate_success(client.get_assignment(assignment_id, SECRETARY), 200)


def get_screen(client, screen_id):
    return validate_success(client.get_screen(screen_id, STAFF), 200)


def get_firm(client, firm_id):
    """Read a firm's live ledger as its own partner, which is the owning identity."""
    return validate_success(
        client.get_search_firm(firm_id, make_search_firm_partner_headers(firm_id)), 200
    )


def get_award(client, award_id):
    return validate_success(client.get_comp_award(award_id, SECRETARY), 200)


def get_item(client, item_id):
    return validate_success(client.get_onboarding_item(item_id, SECRETARY), 200)


def get_rating(client, rating_id):
    return validate_success(client.get_skill_rating(rating_id, SECRETARY), 200)


def get_directorship(client, directorship_id):
    return validate_success(client.get_external_directorship(directorship_id, SECRETARY), 200)


def get_gap_analysis(client, variant=None):
    params = {"variant": variant} if variant is not None else None
    return validate_success(client.get_gap_analysis(STAFF, params=params), 200)


# ---------------------------------------------------------------------------
# Skill ratings
# ---------------------------------------------------------------------------
def record_rating(client, director_id, skill_category_id, self_rating, headers=None):
    return validate_success(
        client.create_skill_rating(
            director_id,
            F.skill_rating_payload(skill_category_id, self_rating),
            headers if headers else STAFF,
        ),
        201,
    )


def validate_rating(client, rating_id, validated_rating, chair_headers):
    return validate_success(
        client.validate_skill_rating(
            rating_id, F.rating_validation_payload(validated_rating), chair_headers
        ),
        200,
    )
