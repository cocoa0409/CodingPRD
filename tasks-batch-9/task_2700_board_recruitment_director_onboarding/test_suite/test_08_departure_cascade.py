"""A resignation notice, and the two chains that fan out of the single call.

The notice moves the director out of seated service, ends the committee seat that
director occupied and forces the committee to re-derive its seat ledger and
posture; on a separate branch it voids the director's untouched draft award. The
director's other two state dimensions are left where they were.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_committee_ledger, assert_fields_equal
from test_helpers.test_users import SECRETARY

# The audit committee is chartered wide but shallow: five seats authorised and a
# minimum strength of one, so the single chair seat alone reads AT_STRENGTH.
COMMITTEE_AUTHORIZED_SEATS = 5
COMMITTEE_MIN_SEATS = 1

# The resigning director's own record.
APPOINTED_ON = "2022-01-01"
SHARES_HELD = 2000
SHARE_PRICE_CENTS = 90000

# The notice itself.
NOTICE_TYPE = "RESIGNATION"
NOTICE_EFFECTIVE_ON = "2026-08-15"


def _departure_world(client):
    """One seated director holding an active committee chair seat, plus a draft award.

    On return nothing has been triggered: the committee reads one filled seat and
    the compensation award is still `DRAFT`.
    """
    X.adopt_policy(client)

    director = X.new_seated_director(
        client,
        full_name="Rita Resigner",
        email="rita@issuer.example",
        birth_date="1968-06-06",
        appointed_on=APPOINTED_ON,
        shares_held=SHARES_HELD,
    )
    committee = X.new_committee(
        client,
        code="AUDIT",
        name="Audit Committee",
        authorized_seats=COMMITTEE_AUTHORIZED_SEATS,
        min_seats=COMMITTEE_MIN_SEATS,
    )
    assignment = X.seat_assignment(
        client,
        committee["id"],
        director["id"],
        seat_role="CHAIR",
        term_start_on="2026-01-01",
        term_end_on="2026-12-31",
    )
    award = X.new_comp_award(
        client,
        director["id"],
        cycle_year=2026,
        service_start_on="2026-01-01",
        service_end_on="2026-12-31",
        share_price_cents=SHARE_PRICE_CENTS,
        shares_held=SHARES_HELD,
    )

    return {
        "director_id": director["id"],
        "committee_id": committee["id"],
        "assignment_id": assignment["id"],
        "award_id": award["id"],
    }


def _file_resignation(client, director_id):
    """Record the resignation notice with its effective date."""
    return validate_success(
        client.record_departure_notice(
            director_id,
            F.departure_notice_payload(NOTICE_TYPE, effective_on=NOTICE_EFFECTIVE_ON),
            SECRETARY,
        ),
        200,
    )


def test_the_chair_seat_reads_at_strength_before_the_notice(client):
    """The baseline the cascade is measured against: the one active chair assignment
    occupies a seat, so the committee reads one filled seat and full strength.

    PRD: "The `filled_seats` is the count of that committee's assignments whose `status` is exactly `ACTIVE`; `PROPOSED`, `ENDED` and `REVOKED` rows never occupy a seat."

    Design: Difficulty/transitive_cascade/resignation_notice_cascades_director_to_assignment_to_committee_ledger_and_voids_draft_award
    """
    world = _departure_world(client)

    assert_fields_equal(
        X.get_assignment(client, world["assignment_id"]),
        {"status": "ACTIVE", "seat_role": "CHAIR", "ended_reason_code": None},
    )
    assert_committee_ledger(
        X.get_committee(client, world["committee_id"]),
        filled_seats=1,
        status="AT_STRENGTH",
    )
    assert_fields_equal(
        X.get_director(client, world["director_id"]),
        {"service_status": "SEATED", "retirement_notice_at": None},
    )


def test_resignation_notice_moves_the_director_out_of_seated_service(client):
    """Hop one: the notice resigns the director and stamps the notice instant from the
    logical clock.

    PRD: "Both set `retirement_notice_at` to the logical clock instant and cascade three hops"

    Design: Difficulty/transitive_cascade/resignation_notice_cascades_director_to_assignment_to_committee_ledger_and_voids_draft_award
    """
    world = _departure_world(client)

    _file_resignation(client, world["director_id"])

    director = X.get_director(client, world["director_id"])
    assert_fields_equal(director, {"service_status": "RESIGNED"})
    assert is_iso8601_timestamp(director["retirement_notice_at"]), director[
        "retirement_notice_at"
    ]


def test_resignation_notice_ends_the_active_committee_assignment(client):
    """Hop two: the director's active seat is ended by the notice rather than revoked
    by hand, so it carries the retirement-notice reason and an end instant.

    PRD: "every committee assignment of that director whose `status` is `ACTIVE` becomes `ENDED` with `ended_reason_code` `RETIREMENT_NOTICE` and `ended_at` recorded"

    Design: Difficulty/transitive_cascade/resignation_notice_cascades_director_to_assignment_to_committee_ledger_and_voids_draft_award
    """
    world = _departure_world(client)

    _file_resignation(client, world["director_id"])

    assignment = X.get_assignment(client, world["assignment_id"])
    assert_fields_equal(
        assignment, {"status": "ENDED", "ended_reason_code": "RETIREMENT_NOTICE"}
    )
    assert is_iso8601_timestamp(assignment["ended_at"]), assignment["ended_at"]


def test_the_committee_seat_ledger_and_posture_are_re_derived(client):
    """Hop three: with its only active assignment ended two hops upstream, the
    committee falls to no filled seats and its posture regresses from full strength.

    PRD: "each affected committee re-derives its `filled_seats` and posture `status`"

    Design: Difficulty/transitive_cascade/resignation_notice_cascades_director_to_assignment_to_committee_ledger_and_voids_draft_award
    """
    world = _departure_world(client)

    _file_resignation(client, world["director_id"])

    assert_committee_ledger(
        X.get_committee(client, world["committee_id"]),
        filled_seats=0,
        status="UNDER_STRENGTH",
    )


def test_resignation_voids_the_directors_draft_compensation_award(client):
    """The parallel branch: the same notice voids the draft award, which the client
    never named and which sits on a different chain from the committee seat.

    PRD: "A resignation additionally voids every compensation award of that director whose `status` is `DRAFT`, which releases that award's per-director per-cycle uniqueness slot."

    Design: Difficulty/transitive_cascade/resignation_notice_cascades_director_to_assignment_to_committee_ledger_and_voids_draft_award
    """
    world = _departure_world(client)

    assert_fields_equal(X.get_award(client, world["award_id"]), {"status": "DRAFT"})

    _file_resignation(client, world["director_id"])

    assert_fields_equal(X.get_award(client, world["award_id"]), {"status": "VOIDED"})


def test_the_notice_leaves_the_other_two_director_dimensions_alone(client):
    """The service dimension is the only one the notice commands: the onboarding and
    compliance dimensions read exactly as they did before it was recorded.

    PRD: "A director can be seated and education-delinquent and onboarding-complete all at once; the three dimensions never gate each other except where a rule explicitly says so."

    Design: Difficulty/transitive_cascade/resignation_notice_cascades_director_to_assignment_to_committee_ledger_and_voids_draft_award
    """
    world = _departure_world(client)

    before = X.get_director(client, world["director_id"])
    assert_fields_equal(
        before,
        {
            "service_status": "SEATED",
            "onboarding_status": "NOT_STARTED",
            "compliance_status": "COMPLIANT",
        },
    )

    _file_resignation(client, world["director_id"])

    assert_fields_equal(
        X.get_director(client, world["director_id"]),
        {
            "service_status": "RESIGNED",
            "onboarding_status": before["onboarding_status"],
            "compliance_status": before["compliance_status"],
        },
    )
