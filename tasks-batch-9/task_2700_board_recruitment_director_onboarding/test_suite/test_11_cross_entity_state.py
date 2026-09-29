"""Cross-entity state gates: the onboarding programme gating a seat, and the
service status of an incumbent gating a renomination row.

Both operations are legal or illegal purely because of the state of rows in a
*different* table; the addressed row never changes between the refused and the
accepted attempt.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_DIRECTOR_NOT_SEATABLE,
    ERR_ONBOARDING_INCOMPLETE,
)
from test_helpers.assertions import assert_fields_equal, assert_onboarding_rollup
from test_helpers.test_users import SECRETARY, STAFF

# Two required items with one of them satisfied: 100 * 1 / 2, so the optional
# continuing-education item sits outside both the numerator and the denominator.
PCT_ONE_OF_TWO_REQUIRED = 50.00
PCT_ALL_REQUIRED = 100.00

# The slate is opened with nine seats, matching the policy's authorized_seats, so
# no seat-count or fee gate can interfere with the incumbent renomination gate.
SLATE_SEAT_COUNT = 9


def _director_midway_through_onboarding(client):
    """One ONBOARDING director with two required items, one done, plus an optional one."""
    X.adopt_policy(client)
    director = X.new_onboarding_director(
        client,
        full_name="Owen Onboard",
        email="owen@issuer.example",
        birth_date="1974-09-09",
        appointed_on="2026-07-01",
    )
    first_required = X.new_onboarding_item(
        client,
        director["id"],
        module_code="BUSINESS_ORIENTATION_101",
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=2.0,
        due_on="2026-09-30",
    )
    second_required = X.new_onboarding_item(
        client,
        director["id"],
        module_code="AUDIT_COMMITTEE_ONBOARDING",
        category="COMMITTEE_ONBOARDING",
        is_required=True,
        credit_hours=2.0,
        due_on="2026-09-30",
    )
    optional_item = X.new_onboarding_item(
        client,
        director["id"],
        module_code="ESG_ELECTIVE",
        category="CONTINUING_EDUCATION",
        is_required=False,
        credit_hours=4.0,
        due_on="2026-12-31",
    )
    X.complete_item(client, first_required["id"])
    return {
        "director": director,
        "first_required": first_required,
        "second_required": second_required,
        "optional_item": optional_item,
    }


def _resigned_and_seated_incumbents(client):
    """Two incumbents, one resigned and one still seated, plus an empty draft slate."""
    X.adopt_policy(client)
    resigned = X.new_seated_director(
        client,
        full_name="Rhea Resigned",
        email="rhea@issuer.example",
        birth_date="1969-01-01",
        appointed_on="2021-06-01",
        is_independent=True,
    )
    seated = X.new_seated_director(
        client,
        full_name="Sana Seated",
        email="sana@issuer.example",
        birth_date="1968-04-04",
        appointed_on="2021-01-01",
        is_independent=True,
    )
    X.record_departure(client, resigned["id"], notice_type="RESIGNATION")
    slate = X.new_slate(client, cycle_year=2026, seat_count=SLATE_SEAT_COUNT)
    return {"resigned": resigned, "seated": seated, "slate": slate}


def test_seating_is_refused_while_a_required_onboarding_item_is_still_pending(client):
    """With one of two required modules still PENDING the director's programme reads
    IN_PROGRESS, and the seat call is refused without touching the service dimension.

    PRD: "The director's `onboarding_status` must be exactly `COMPLETE`; a director whose programme is `NOT_STARTED` or `IN_PROGRESS` is refused with `ERR_ONBOARDING_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/seating_a_director_requires_every_required_onboarding_item_complete
    """
    built = _director_midway_through_onboarding(client)
    director_id = built["director"]["id"]

    assert_onboarding_rollup(
        X.get_director(client, director_id), "IN_PROGRESS", PCT_ONE_OF_TWO_REQUIRED
    )

    validate_error(
        client.seat_director(director_id, SECRETARY), ERR_ONBOARDING_INCOMPLETE, 409
    )

    after = X.get_director(client, director_id)
    assert after["service_status"] == "ONBOARDING"
    assert_onboarding_rollup(after, "IN_PROGRESS", PCT_ONE_OF_TWO_REQUIRED)


def test_the_optional_item_stays_outside_the_onboarding_denominator(client):
    """The rollup counts only required items, so completing the second required module
    takes the percentage to 100.00 while the untouched optional module stays PENDING.

    PRD: "The `onboarding_completion_pct` is 0.00 when nothing is required, and otherwise 100 multiplied by the size of the satisfied set divided by the size of the required set, rounded half up to two decimal places."

    Design: Difficulty/cross_entity_state_dependency/seating_a_director_requires_every_required_onboarding_item_complete
    """
    built = _director_midway_through_onboarding(client)
    director_id = built["director"]["id"]

    assert X.get_director(client, director_id)["onboarding_completion_pct"] == (
        PCT_ONE_OF_TWO_REQUIRED
    )

    X.complete_item(client, built["second_required"]["id"])

    assert_onboarding_rollup(
        X.get_director(client, director_id), "COMPLETE", PCT_ALL_REQUIRED
    )
    assert X.get_item(client, built["optional_item"]["id"])["status"] == "PENDING"


def test_the_same_seat_call_succeeds_once_the_last_required_item_closes(client):
    """Nothing about the director row changes between the two attempts: completing the
    last required module flips the derived dimension to COMPLETE and the seat lands.

    PRD: "Otherwise, when every required item is satisfied the status is `COMPLETE`;"

    Design: Difficulty/cross_entity_state_dependency/seating_a_director_requires_every_required_onboarding_item_complete
    """
    built = _director_midway_through_onboarding(client)
    director_id = built["director"]["id"]

    validate_error(
        client.seat_director(director_id, SECRETARY), ERR_ONBOARDING_INCOMPLETE, 409
    )
    X.complete_item(client, built["second_required"]["id"])

    seated = validate_success(client.seat_director(director_id, SECRETARY), 200)
    assert_fields_equal(
        seated,
        {
            "service_status": "SEATED",
            "onboarding_status": "COMPLETE",
            "onboarding_completion_pct": PCT_ALL_REQUIRED,
        },
    )
    assert X.get_director(client, director_id)["service_status"] == "SEATED"


def test_a_resigned_incumbent_cannot_be_renominated(client):
    """A director whose service dimension reads RESIGNED is not seatable, so the nominee
    row naming them is refused even though the slate itself is a clean DRAFT.

    PRD: "An incumbent subject's `service_status` must be `SEATED` or `RETIREMENT_NOTICED`; a director who is `ONBOARDING`, `RETIRED`, `RESIGNED` or `NOT_RENOMINATED` cannot be renominated and the request is refused with `ERR_DIRECTOR_NOT_SEATABLE`."

    Design: Difficulty/cross_entity_state_dependency/incumbent_renomination_requires_a_seated_director_not_a_resigned_one
    """
    built = _resigned_and_seated_incumbents(client)
    slate_id = built["slate"]["id"]

    assert X.get_director(client, built["resigned"]["id"])["service_status"] == "RESIGNED"
    assert X.get_director(client, built["seated"]["id"])["service_status"] == "SEATED"

    validate_error(
        client.add_slate_nominee(
            slate_id,
            F.nominee_payload(
                built["slate"]["version"],
                1,
                incumbent_director_id=built["resigned"]["id"],
            ),
            STAFF,
        ),
        ERR_DIRECTOR_NOT_SEATABLE,
        409,
    )

    slate = X.get_slate(client, slate_id)
    assert slate["nominee_count"] == 0
    assert slate["status"] == "DRAFT"


def test_the_rejected_renomination_leaves_the_slate_version_reusable(client):
    """The refused nominee add mutated nothing, so the seated incumbent is admitted on the
    very same `expected_slate_version` the rejected call already spent.

    PRD: "The server compares `expected_slate_version` to the slate's current `version` and to nothing else."

    Design: Difficulty/cross_entity_state_dependency/incumbent_renomination_requires_a_seated_director_not_a_resigned_one
    """
    built = _resigned_and_seated_incumbents(client)
    slate_id = built["slate"]["id"]
    opening_version = built["slate"]["version"]

    validate_error(
        client.add_slate_nominee(
            slate_id,
            F.nominee_payload(opening_version, 1, incumbent_director_id=built["resigned"]["id"]),
            STAFF,
        ),
        ERR_DIRECTOR_NOT_SEATABLE,
        409,
    )
    assert X.get_slate(client, slate_id)["version"] == opening_version

    nominee = validate_success(
        client.add_slate_nominee(
            slate_id,
            F.nominee_payload(opening_version, 1, incumbent_director_id=built["seated"]["id"]),
            STAFF,
        ),
        201,
    )
    assert_fields_equal(
        nominee,
        {
            "status": "PROPOSED",
            "is_independent": True,
            "placement_fee_cents": 0,
            "fee_tier_applied": None,
            "nominee_ordinal": 0,
            "voided_at": None,
        },
    )


def test_the_admitted_incumbent_lifts_the_slate_independence_rollups(client):
    """The single independent incumbent nominee makes the counted set one row deep and
    fully independent, so the slate reports 100.00 percent and no shortfall.

    PRD: "The `nominee_count` is the size of that set and the `independent_nominee_count` is the number of those rows whose `is_independent` is true."

    Design: Difficulty/cross_entity_state_dependency/incumbent_renomination_requires_a_seated_director_not_a_resigned_one
    """
    built = _resigned_and_seated_incumbents(client)
    slate_id = built["slate"]["id"]

    X.add_incumbent_nominee(client, slate_id, built["seated"]["id"], 1)

    assert_fields_equal(
        X.get_slate(client, slate_id),
        {
            "nominee_count": 1,
            "independent_nominee_count": 1,
            "independent_nominee_pct": 100.00,
            "independence_shortfall": False,
            "committed_search_fee_cents": 0,
        },
    )
