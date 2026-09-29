"""Role-based access corners: the negative half of the role matrix, the positive half,
the two ownership-bearing operations, and segregation of duties on a ballot."""
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_fields_equal,
    assert_onboarding_rollup,
    assert_page,
    assert_slate_tallies,
)
from test_helpers.test_users import (
    SECRETARY,
    STAFF,
    make_committee_chair_headers,
    make_committee_member_headers,
    make_search_firm_partner_headers,
    make_seated_director_headers,
)

# The board seats standing for election on the working slate: the whole authorized
# board, so the one-nominee slates below never approach the seat ceiling.
SLATE_SEAT_COUNT = 9

# The proponent behind the shareholder-proposal candidates used throughout, so no
# search firm and no referring director is involved in any ballot below.
PROPONENT = "Cedar Ridge Capital"

# A committee chartered with a single minimum seat, so one active chair seat alone
# already carries the committee to full strength.
COMMITTEE_AUTHORIZED_SEATS = 3
COMMITTEE_MIN_SEATS = 1

# The single interview session behind the segregation-of-duties ballot: one hour on
# a date the default clock has already passed, so the session may be completed.
INTERVIEW_START_AT = "2026-03-02T10:00:00Z"
INTERVIEW_END_AT = "2026-03-02T11:00:00Z"
INTERVIEW_SCORE = 5

# One top-scored interview plus an independent determination, a shareholder-proposal
# sourcing and an empty outside-board load: the candidate's readiness reading.
READINESS_AFTER_ONE_TOP_SCORE = 90.00


def _chair(client, full_name="Cora Chair", email="cora@issuer.example"):
    """One SEATED independent director who acts in the committee-chair capacity."""
    return X.new_seated_director(
        client,
        full_name=full_name,
        email=email,
        birth_date="1962-01-01",
        appointed_on="2019-01-01",
        is_independent=True,
    )


def _proposal_candidate(client, full_name="Sam Sourced", email="sam@cand.example"):
    return X.new_candidate(
        client,
        full_name=full_name,
        email=email,
        birth_date="1974-01-01",
        source_channel="SHAREHOLDER_PROPOSAL",
        shareholder_proponent_name=PROPONENT,
    )


def test_staff_and_members_cannot_reach_secretary_or_chair_exclusive_operations(client):
    """Three calls made in a capacity the endpoint does not list are refused on the role
    alone, so neither the draft screen nor the draft slate reports its state error.

    PRD: "If `X-User-Role` is not one of the six recognised role names, or is a recognised role that the target operation does not list, the request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/staff_and_members_cannot_reach_secretary_or_chair_exclusive_operations
    """
    X.adopt_policy(client)
    chair = _chair(client)
    candidate = _proposal_candidate(client)
    screen = X.open_screen(client, candidate["id"])
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=SLATE_SEAT_COUNT)

    adopt_as_staff = client.adopt_policy(
        F.policy_payload(
            cycle_year=C.NEXT_CYCLE_YEAR, effective_from=C.NEXT_POLICY_EFFECTIVE_FROM
        ),
        STAFF,
    )
    determine_as_staff = client.determine_screen(screen["id"], STAFF)
    decide_as_member = client.decide_slate(
        slate["id"],
        F.decision_payload("APPROVE"),
        make_committee_member_headers(chair["id"]),
    )

    validate_error(adopt_as_staff, E.ERR_UNAUTHORIZED, 403)
    validate_error(determine_as_staff, E.ERR_UNAUTHORIZED, 403)
    validate_error(decide_as_member, E.ERR_UNAUTHORIZED, 403)
    assert_page(client.list_policies(SECRETARY), expected_total=1)
    assert_fields_equal(X.get_screen(client, screen["id"]), {"status": "DRAFT"})
    assert_fields_equal(X.get_slate(client, slate["id"]), {"status": "DRAFT"})


def test_the_corporate_secretary_charters_a_committee_that_other_roles_may_not(client):
    """The positive half of the same matrix for the official record: the secretary's own
    charter call lands, and the new committee opens empty and under strength.

    PRD: "owns the official record: policy adoption, director records, committee charters and assignments, slate filing, election results, compensation awards, waivers and the logical clock."

    Design: Corner/rbac/the_secretary_and_the_chair_can_each_run_their_own_exclusive_operations
    """
    X.adopt_policy(client)

    committee = validate_success(
        client.create_committee(
            F.committee_payload(
                code="AUDIT",
                name="Audit Committee",
                authorized_seats=COMMITTEE_AUTHORIZED_SEATS,
                min_seats=COMMITTEE_MIN_SEATS,
            ),
            SECRETARY,
        ),
        201,
    )

    assert_fields_equal(
        committee, {"filled_seats": 0, "status": "UNDER_STRENGTH", "version": 1}
    )


def test_the_committee_chair_determines_a_screen_and_validates_a_rating(client):
    """The chair's two exclusive judgements both land in the chair capacity: the screen
    reaches a determination that cascades onto the candidate, and the rating flips.

    PRD: "chairs the nominating and governance committee and makes the independence determination, the conflict-of-interest determination, skill-rating validations, interview-round reopenings, onboarding waivers' sibling decisions and the slate decision."

    Design: Corner/rbac/the_secretary_and_the_chair_can_each_run_their_own_exclusive_operations
    """
    X.adopt_policy(client)
    category = X.new_skill_category(
        client,
        code="CYBER",
        name="Cybersecurity Oversight",
        strategic_weight=0.80,
        required_min_directors=2,
        risk_oversight=True,
        criticality="CORE",
    )
    chair = _chair(client)
    chair_headers = make_committee_chair_headers(chair["id"])
    rating = X.record_rating(client, chair["id"], category["id"], 4)
    candidate = _proposal_candidate(client)
    screen = X.open_screen(client, candidate["id"])
    X.submit_screen(client, screen["id"])

    determined = validate_success(client.determine_screen(screen["id"], chair_headers), 200)
    validated = validate_success(
        client.validate_skill_rating(
            rating["id"], F.rating_validation_payload(5), chair_headers
        ),
        200,
    )

    assert_fields_equal(
        determined,
        {"status": "DETERMINED_INDEPENDENT", "determination": "INDEPENDENT"},
    )
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {"status": "SCREEN_PASSED", "independence_result": "INDEPENDENT"},
    )
    assert_fields_equal(
        validated, {"validation_status": "VALIDATED", "effective_rating": 5}
    )


def test_a_seated_director_may_complete_only_their_own_onboarding_item(client):
    """Completion is shared with staff, but in the seated-director capacity the acting
    identity is pinned to the item's owner: the other director's item is untouchable.

    PRD: "which a `SeatedDirector` may do only for their own items, else `ERR_NOT_RESOURCE_OWNER`"

    Design: Corner/rbac/a_seated_director_may_complete_only_their_own_onboarding_item
    """
    X.adopt_policy(client)
    owner = X.new_onboarding_director(
        client,
        full_name="Owen Owner",
        email="owen@issuer.example",
        birth_date="1972-01-01",
        appointed_on="2026-07-01",
    )
    other = X.new_onboarding_director(
        client,
        full_name="Otto Other",
        email="otto@issuer.example",
        birth_date="1973-01-01",
        appointed_on="2026-07-01",
    )
    own_item = X.new_onboarding_item(
        client,
        owner["id"],
        module_code="BUSINESS_ORIENTATION_101",
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=2.0,
        due_on="2026-09-30",
    )
    other_item = X.new_onboarding_item(
        client,
        other["id"],
        module_code="BUSINESS_ORIENTATION_101",
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=2.0,
        due_on="2026-09-30",
    )
    owner_headers = make_seated_director_headers(owner["id"])

    cross_director = client.complete_onboarding_item(other_item["id"], owner_headers)
    own = validate_success(client.complete_onboarding_item(own_item["id"], owner_headers), 200)

    validate_error(cross_director, E.ERR_NOT_RESOURCE_OWNER, 403)
    assert_fields_equal(X.get_item(client, other_item["id"]), {"status": "PENDING"})
    assert_onboarding_rollup(X.get_director(client, other["id"]), "NOT_STARTED", 0.00)
    assert_fields_equal(own, {"status": "COMPLETED"})
    assert_onboarding_rollup(X.get_director(client, owner["id"]), "COMPLETE", 100.00)


def test_a_search_firm_partner_can_read_only_its_own_firm_row(client):
    """The partner capacity is backed by the firm id, so the same read endpoint answers
    for the partner's own firm and refuses a rival's, while staff may read either.

    PRD: "is a partner at a retained executive-search firm who may read only their own firm record and its live placement-fee ledger."

    Design: Corner/rbac/a_search_firm_partner_can_read_only_its_own_firm_row
    """
    X.adopt_policy(client)
    firm_a = X.new_search_firm(
        client,
        name="Beacon Search Partners",
        contact_email="partners@beacon.example",
        placement_fee_pct=30.0,
        placement_fee_tier2_pct=20.0,
    )
    firm_b = X.new_search_firm(
        client,
        name="Meridian Board Search",
        contact_email="team@meridian.example",
        placement_fee_pct=28.0,
        placement_fee_tier2_pct=18.0,
    )
    partner_a = make_search_firm_partner_headers(firm_a["id"])

    cross_firm = client.get_search_firm(firm_b["id"], partner_a)
    own_firm = validate_success(client.get_search_firm(firm_a["id"], partner_a), 200)
    staff_read = validate_success(client.get_search_firm(firm_b["id"], STAFF), 200)

    validate_error(cross_firm, E.ERR_NOT_RESOURCE_OWNER, 403)
    assert_fields_equal(own_firm, {"id": firm_a["id"], "name": "Beacon Search Partners"})
    assert_fields_equal(staff_read, {"id": firm_b["id"], "name": "Meridian Board Search"})


def test_an_interviewer_may_not_ballot_on_the_slate_carrying_their_candidate(client):
    """The director who conducted the candidate's interview is barred from balloting on
    the slate carrying that candidate, while an uninvolved chair's ballot is minuted.

    PRD: "The acting user may not both interview a candidate and ballot on the slate carrying that candidate"

    Design: Corner/rbac/an_interviewer_may_not_ballot_on_the_slate_carrying_the_candidate_they_interviewed
    """
    X.adopt_policy(client, min_completed_interviews=1, quorum_size=1)
    chair = _chair(client)
    chair_headers = make_committee_chair_headers(chair["id"])
    interviewer = X.new_seated_director(
        client,
        full_name="Ivan Interviewer",
        email="ivan@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
        is_independent=True,
    )
    candidate = _proposal_candidate(client, "Cass Candidate", "cass@cand.example")
    X.screen_candidate(client, candidate["id"], chair_headers)
    session = X.schedule_interview(
        client,
        candidate["id"],
        interviewer["id"],
        INTERVIEW_START_AT,
        INTERVIEW_END_AT,
    )
    X.complete_interview(client, session["id"], score=INTERVIEW_SCORE)
    X.record_reference_check(client, candidate["id"])
    X.run_conflict_clearance(client, candidate["id"], chair_headers)
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=SLATE_SEAT_COUNT)
    X.add_candidate_nominee(client, slate["id"], candidate["id"], 1)
    X.submit_slate(client, slate["id"])

    interviewer_ballot = client.cast_vote(
        slate["id"],
        F.vote_payload(interviewer["id"], "FOR"),
        make_committee_member_headers(interviewer["id"]),
    )
    chair_ballot = validate_success(
        client.cast_vote(slate["id"], F.vote_payload(chair["id"], "FOR"), chair_headers), 201
    )

    validate_error(interviewer_ballot, E.ERR_SEGREGATION_OF_DUTIES, 403)
    assert_page(client.list_votes(STAFF), expected_total=1)
    assert_fields_equal(
        chair_ballot, {"ballot": "FOR", "recusal_required": False, "status": "CAST"}
    )
    assert_slate_tallies(X.get_slate(client, slate["id"]), 1, 0, 0, 0, 100.00, True)
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {"status": "NOMINATED", "readiness_score": READINESS_AFTER_ONE_TOP_SCORE},
    )
