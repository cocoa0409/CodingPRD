"""Endpoint corners: the search-firm round trip, the slate filing chain, the
onboarding waiver and the skill-rating junction with its validation override."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ONBOARDING_ITEM_STATE_INVALID,
    ERR_SKILL_CATEGORY_NOT_FOUND,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_firm_ledger,
    assert_gap_row,
    assert_onboarding_rollup,
    assert_page,
)
from test_helpers.test_users import (
    SECRETARY,
    STAFF,
    make_committee_chair_headers,
)

POLICY_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
# Every timestamp in these tests is stamped at the default logical clock instant,
# compared on its second-precision prefix so a fractional rendering still matches.
CLOCK_INSTANT_PREFIX = "2026-08-01T00:00:00"

# ---------------------------------------------------------------------------
# A firm onboarded with only its name, contact and two fee tiers, so the two
# omitted fields fall back to their declared defaults and the four ledger
# fields start at zero.
# ---------------------------------------------------------------------------
FIRM_NAME = "Beacon Search Partners"
FIRM_EMAIL = "partners@beacon.example"
FIRM_TIER1_PCT = 30.0
FIRM_TIER2_PCT = 20.0
FIRM_DEFAULT_FEE_MODEL = "RETAINER"
FIRM_DEFAULT_RETAINER_CENTS = 0

# ---------------------------------------------------------------------------
# One ballot carries the slate when the governing quorum_size is 1.
# ---------------------------------------------------------------------------
SINGLE_BALLOT_QUORUM = 1

# ---------------------------------------------------------------------------
# Two required onboarding items: one completed, one waived.  Half of the
# required set satisfied reads 50.00, and the whole of it reads 100.00.
# ---------------------------------------------------------------------------
WAIVER_REASON = "Credited from prior board service"
HALF_COMPLETE_PCT = 50.00
FULLY_COMPLETE_PCT = 100.00

# ---------------------------------------------------------------------------
# CYBER carries strategic_weight 0.80, requires two covered directors and is
# risk-oversight flagged, so one uncovered director weighs 1 * 0.80 * 1.5.
# ---------------------------------------------------------------------------
CYBER_WEIGHT = 0.80
CYBER_REQUIRED_MIN_DIRECTORS = 2
CYBER_MINOR_WEIGHTED_GAP = 1.20
SELF_RATING = 5
VALIDATED_RATING_DOWN = 2


def _cast_ballot(client, slate_id, voting_director_id, ballot, headers):
    """Cast one ballot and assert the 201 a ballot creation returns."""
    return validate_success(
        client.cast_vote(slate_id, F.vote_payload(voting_director_id, ballot), headers), 201
    )


def _director_in_onboarding_with_two_required_items(client):
    """One ONBOARDING director whose first required item is already COMPLETED."""
    X.adopt_policy(client, effective_from=POLICY_EFFECTIVE_FROM)
    director = X.new_onboarding_director(
        client,
        full_name="Wanda Waiver",
        email="wanda@issuer.example",
        birth_date="1972-01-01",
        appointed_on="2026-07-01",
    )
    completed = X.new_onboarding_item(
        client,
        director["id"],
        module_code="BUSINESS_ORIENTATION_101",
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=2.0,
        due_on="2026-09-30",
    )
    pending = X.new_onboarding_item(
        client,
        director["id"],
        module_code="COMMITTEE_CHARTER_REVIEW",
        category="COMMITTEE_ONBOARDING",
        is_required=True,
        credit_hours=1.5,
        due_on="2026-09-30",
    )
    X.complete_item(client, completed["id"])
    return director, pending


def test_onboarding_a_search_firm_reads_back_with_its_defaults_and_a_zeroed_ledger(client):
    """A firm onboarded with only its name, contact and two fee tiers stores RETAINER and a
    zero retainer credit, and reads back field for field with the same version.

    PRD: "Four ledger fields on the firm are maintained by the server and never written by a client: `placed_nominee_count`, `committed_fee_cents`, `retainer_credit_applied_cents` and `net_payable_cents`, all starting at 0."

    Design: Corner/endpoints/search_firm_create_read_and_list_round_trip
    """
    X.adopt_policy(client, effective_from=POLICY_EFFECTIVE_FROM)

    created = validate_success(
        client.create_search_firm(
            {
                "name": FIRM_NAME,
                "contact_email": FIRM_EMAIL,
                "placement_fee_pct": FIRM_TIER1_PCT,
                "placement_fee_tier2_pct": FIRM_TIER2_PCT,
            },
            SECRETARY,
        ),
        201,
    )
    read_back = validate_success(client.get_search_firm(created["id"], STAFF), 200)

    for firm in (created, read_back):
        assert_fields_equal(
            firm,
            {
                "name": FIRM_NAME,
                "contact_email": FIRM_EMAIL,
                "placement_fee_pct": FIRM_TIER1_PCT,
                "placement_fee_tier2_pct": FIRM_TIER2_PCT,
                "fee_model": FIRM_DEFAULT_FEE_MODEL,
                "retainer_fee_cents": FIRM_DEFAULT_RETAINER_CENTS,
            },
        )
        assert_firm_ledger(firm, 0, 0, 0, 0)
    assert read_back["id"] == created["id"]
    assert read_back["version"] == created["version"]


def test_filing_a_slate_and_recording_the_election_each_stamp_their_own_instant(client):
    """Filing moves the approved slate to FILED with filed_at, recording the election moves it
    to ELECTION_RECORDED, elects the listed nominee, and bumps the version on each call.

    PRD: "The slate becomes `ELECTION_RECORDED` with `election_recorded_at` set to the logical clock instant and `version` incremented by 1."

    Design: Corner/endpoints/slate_action_chain_files_and_records_the_election
    """
    X.adopt_policy(
        client, effective_from=POLICY_EFFECTIVE_FROM, quorum_size=SINGLE_BALLOT_QUORUM
    )
    chair = X.new_seated_director(
        client, full_name="Cora Chair", email="cora@issuer.example",
        birth_date="1962-01-01", appointed_on="2019-01-01", is_independent=True,
    )
    incumbent = X.new_seated_director(
        client, full_name="Ida Incumbent", email="ida@issuer.example",
        birth_date="1968-01-01", appointed_on="2021-01-01", is_independent=True,
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    slate = X.new_slate(client, cycle_year=2026, seat_count=9)
    nominee = X.add_incumbent_nominee(client, slate["id"], incumbent["id"], 1)
    X.submit_slate(client, slate["id"])
    _cast_ballot(client, slate["id"], chair["id"], "FOR", chair_headers)
    approved = X.decide_slate(client, slate["id"], chair_headers, decision="APPROVE")

    filed = X.file_slate(client, slate["id"])
    recorded = X.record_election(client, slate["id"], [nominee["id"]])

    assert filed["status"] == "FILED"
    assert filed["filed_at"].startswith(CLOCK_INSTANT_PREFIX)
    assert recorded["status"] == "ELECTION_RECORDED"
    assert recorded["election_recorded_at"].startswith(CLOCK_INSTANT_PREFIX)
    assert filed["version"] > approved["version"]
    assert recorded["version"] > filed["version"]
    assert X.get_nominee(client, nominee["id"])["status"] == "ELECTED"
    assert X.get_director(client, incumbent["id"])["service_status"] == "SEATED"


def test_governance_staff_may_not_waive_an_onboarding_item(client):
    """The waive action is reserved to the corporate secretary, so a staff attempt is refused
    and leaves the item PENDING with the director's programme still half satisfied.

    PRD: "If `X-User-Role` is not one of the six recognised role names, or is a recognised role that the target operation does not list, the request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/endpoints/waiving_an_onboarding_item_is_allowed_only_for_the_secretary_and_only_while_pending
    """
    director, pending = _director_in_onboarding_with_two_required_items(client)

    validate_error(
        client.waive_onboarding_item(pending["id"], F.waiver_payload(WAIVER_REASON), STAFF),
        ERR_UNAUTHORIZED,
        403,
    )

    assert_fields_equal(
        X.get_item(client, pending["id"]),
        {"status": "PENDING", "waiver_reason": None},
    )
    assert_onboarding_rollup(
        X.get_director(client, director["id"]), "IN_PROGRESS", HALF_COMPLETE_PCT
    )


def test_a_secretary_waiver_satisfies_the_rollup_and_closes_the_item_for_good(client):
    """The waiver records its reason without a completion timestamp, carries the programme to
    100.00 so the director can be seated, and a second waiver of the same item is refused.

    PRD: "a waived required item counts as satisfied for the rollup but contributes no education credit"

    Design: Corner/endpoints/waiving_an_onboarding_item_is_allowed_only_for_the_secretary_and_only_while_pending
    """
    director, pending = _director_in_onboarding_with_two_required_items(client)

    waived = X.waive_item(client, pending["id"], reason=WAIVER_REASON)

    assert_fields_equal(
        waived,
        {"status": "WAIVED", "waiver_reason": WAIVER_REASON, "completed_at": None},
    )
    assert_onboarding_rollup(
        X.get_director(client, director["id"]), "COMPLETE", FULLY_COMPLETE_PCT
    )
    assert X.seat_director(client, director["id"])["service_status"] == "SEATED"
    validate_error(
        client.waive_onboarding_item(pending["id"], F.waiver_payload(WAIVER_REASON), SECRETARY),
        ERR_ONBOARDING_ITEM_STATE_INVALID,
        409,
    )


def test_validating_a_rating_overrides_the_effective_rating_without_touching_the_self_view(client):
    """An unknown category cannot be linked, a new link mirrors the self-rating of 5, and a
    committee validation of 2 takes over the effective rating while the self view stays 5.

    PRD: "When the committee chair validates a rating, they supply a `validated_rating` from 1 through 5; the rating flips to `VALIDATED`, `validated_at` records the logical clock instant, and `effective_rating` becomes the `validated_rating`."

    Design: Corner/endpoints/skill_rating_links_a_director_to_a_category_and_validation_overrides_the_rating
    """
    X.adopt_policy(client, effective_from=POLICY_EFFECTIVE_FROM)
    category = X.new_skill_category(
        client,
        code="CYBER",
        name="Cybersecurity Oversight",
        strategic_weight=CYBER_WEIGHT,
        required_min_directors=CYBER_REQUIRED_MIN_DIRECTORS,
        risk_oversight=True,
        criticality="CORE",
    )
    director = X.new_seated_director(
        client, full_name="Cora Chair", email="cora@issuer.example",
        birth_date="1962-01-01", appointed_on="2019-01-01", is_independent=True,
    )

    validate_error(
        client.create_skill_rating(
            director["id"], F.skill_rating_payload(NON_EXISTENT_UUID, SELF_RATING), STAFF
        ),
        ERR_SKILL_CATEGORY_NOT_FOUND,
        404,
    )
    created = X.record_rating(client, director["id"], category["id"], SELF_RATING)
    validated = X.validate_rating(
        client,
        created["id"],
        VALIDATED_RATING_DOWN,
        make_committee_chair_headers(director["id"]),
    )

    assert_fields_equal(
        created,
        {
            "skill_category_id": category["id"],
            "director_id": director["id"],
            "validation_status": "UNVALIDATED",
            "validated_rating": None,
            "effective_rating": SELF_RATING,
            "validated_at": None,
        },
    )
    assert_fields_equal(
        validated,
        {
            "validation_status": "VALIDATED",
            "self_rating": SELF_RATING,
            "validated_rating": VALIDATED_RATING_DOWN,
            "effective_rating": VALIDATED_RATING_DOWN,
        },
    )
    assert validated["validated_at"].startswith(CLOCK_INSTANT_PREFIX)
    analysis = X.get_gap_analysis(client)
    assert analysis["seated_director_count"] == 1
    assert_gap_row(analysis, "CYBER", 1, 1, CYBER_MINOR_WEIGHTED_GAP, "MINOR_GAP")
    assert_page(client.list_skill_ratings(STAFF), expected_total=1)
