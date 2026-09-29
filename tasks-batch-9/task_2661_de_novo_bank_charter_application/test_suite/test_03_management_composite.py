"""
Management fitness: the per-organizer rounding order and the qualification bar.

The canonical board is Dana Whitfield (proposed CEO, 7 years, rating 83), Marcus
Ibarra (proposed CFO, 13 years, rating 71), Priya Raghunathan (proposed CRO, 3
years, rating 66), Elena Kowalski (proposed CCO, 20 years, rating 90) and Theo
Nakamura (director, 10 years, rating 54).
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx, make_independent_director_headers
from test_helpers.assertions import assert_fields_equal, assert_two_decimal_places
from test_helpers.types import (
    COMPOSITION_MET,
    CREDIT_CLEARED,
    DIMENSION_CREDIT,
    DOMAIN_LENDING,
    POLICY_BOARD_ADOPTED,
    POLICY_DRAFT,
    QUALIFICATION_PENDING,
    QUALIFICATION_QUALIFIED,
)
from test_helpers.factories import background_result_payload
from test_helpers import CHARTERING_EXAMINER_HEADERS


def _nine_of_ten_dimensions_cleared(api):
    """Every background dimension resolved clear except Theo Nakamura's credit check."""
    world = fx.seated_group(api, seats=5, clear=False)
    for key in ("o1", "o2", "o3", "o4"):
        fx.clear_background(api, world[key], both=True)
    fx.clear_background(api, world["o5"], both=False)
    return world


# ---------------------------------------------------------------------------
# Difficulty / combinatorial_formula
# ---------------------------------------------------------------------------
def test_each_organizer_subscore_is_rounded_half_up_to_an_integer_first(api):
    """
    Resolving the last outstanding credit check settles all five subscores. Every one is
    the half-up integer of its own weighted sum: 68.05 becomes 68, 75.85 becomes 76, 54.10
    becomes 54, 63.90 becomes 64, and Elena Kowalski's raw 96.50 sits exactly on the
    half-way point and rounds up to 97 rather than down to 96.

    PRD: "The sum of the three components is rounded half up to zero decimal places and persisted in `qualification_subscore` as an integer; the unrounded sum is never persisted anywhere."

    Design: Difficulty/combinatorial_formula/management_composite_rounding_order_pinned_per_organizer
    """
    world = _nine_of_ten_dimensions_cleared(api)
    get_success_data(
        api.record_background_result(
            world["o5"],
            background_result_payload(dimension=DIMENSION_CREDIT, outcome=CREDIT_CLEARED),
            CHARTERING_EXAMINER_HEADERS,
        )
    )

    expected = {"o1": 68, "o2": 76, "o3": 54, "o4": 97, "o5": 64}
    for key, subscore in expected.items():
        organizer = get_success_data(
            api.get_organizer(world[key], CHARTERING_EXAMINER_HEADERS)
        )
        assert_fields_equal(organizer, qualification_subscore=subscore)
        assert isinstance(organizer["qualification_subscore"], int), (
            "the persisted subscore must be an integer, not the unrounded sum"
        )

    o4 = get_success_data(api.get_organizer(world["o4"], CHARTERING_EXAMINER_HEADERS))
    assert o4["qualification_subscore"] == 97, (
        "a raw subscore of exactly 96.50 must round half up to 97"
    )


def test_management_composite_averages_the_persisted_integers_not_the_raw_sums(api):
    """
    The composite sums the five persisted integers — 68, 76, 54, 97 and 64 — for 359, and
    rounds the quotient to 71.80. Averaging the unrounded component sums instead would
    give 358.40 over five, or 71.68, which is a different cent value and not the specified
    computation.

    PRD: "Otherwise, each eligible organizer's already-rounded integer `qualification_subscore` is what enters the sum — the integer rounding has already happened at the organizer level and the persisted integer is authoritative — the sum is divided by the number of eligible organizers, and only that quotient is rounded, half up, to two decimal places."
    PRD: "Averaging unrounded raw subscores and rounding once at the end is a different computation and produces a different cent value; it is not the specified behaviour."

    Design: Difficulty/combinatorial_formula/management_composite_rounding_order_pinned_per_organizer
    """
    world = _nine_of_ten_dimensions_cleared(api)
    get_success_data(
        api.record_background_result(
            world["o5"],
            background_result_payload(dimension=DIMENSION_CREDIT, outcome=CREDIT_CLEARED),
            CHARTERING_EXAMINER_HEADERS,
        )
    )

    group = fx.read_group(api, world["group_id"])
    assert_two_decimal_places(
        group["management_composite_score"], 71.80, "management_composite_score"
    )
    assert round(float(group["management_composite_score"]), 2) != 71.68, (
        "the composite must not be the average of the unrounded component sums"
    )
    assert_fields_equal(group, composition_status=COMPOSITION_MET)

    o5 = get_success_data(api.get_organizer(world["o5"], CHARTERING_EXAMINER_HEADERS))
    assert_fields_equal(o5, qualification_status=QUALIFICATION_QUALIFIED)


# ---------------------------------------------------------------------------
# Difficulty / priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def _lending_domain_already_adopted(api):
    """
    A lending policy already board-adopted, a second lending draft waiting behind it, and
    a passive sixth organizer whose background checks have never been run.
    """
    world = fx.composition_met_group(api)
    world["pol_a"] = fx.draft_policy(
        api, world, DOMAIN_LENDING, "Lending and Credit Administration Policy", "o3"
    )
    fx.adopt_policy(api, world, world["pol_a"], "o4")
    world["pol_b"] = fx.draft_policy(
        api, world, DOMAIN_LENDING, "Revised Lending Policy", "o1"
    )
    fx.add_investor_only_organizer(api, world)
    return world


def test_unqualified_adopter_reports_the_qualification_bar_not_the_domain_collision(api):
    """
    Roland Achebe has no background result on either dimension, so his standing is still
    pending and he may not adopt anything. His attempt on the second lending draft breaks
    the domain-uniqueness constraint too, but the prudential bar sits in an earlier band
    and is the only thing reported.

    PRD: "First, on policy adoption, the acting organizer's qualification bar (`ERR_ORGANIZER_NOT_QUALIFIED`, band 7) sits above the domain-uniqueness constraint (`ERR_POLICY_DOMAIN_ALREADY_ADOPTED`, band 9), so a request made by an unqualified organizer against an already-adopted domain must report `ERR_ORGANIZER_NOT_QUALIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/organizer_qualification_safety_outranks_policy_domain_constraint
    """
    world = _lending_domain_already_adopted(api)
    o6 = get_success_data(api.get_organizer(world["o6"], CHARTERING_EXAMINER_HEADERS))
    assert_fields_equal(o6, qualification_status=QUALIFICATION_PENDING)

    error = validate_error(
        api.adopt_policy_document(
            world["pol_b"], make_independent_director_headers(world["o6"])
        ),
        "ERR_ORGANIZER_NOT_QUALIFIED",
        expected_status=409,
    )
    assert error["error_id"] != "ERR_POLICY_DOMAIN_ALREADY_ADOPTED", (
        "the domain collision must not be reported ahead of the qualification bar"
    )


def test_the_masked_domain_collision_is_genuinely_present_and_nothing_was_written(api):
    """
    The constraint the qualification bar hid is real: the first lending policy is already
    board-adopted, so the domain is taken. The refused draft is left exactly as it was,
    still in draft with no adopter and no adoption instant recorded.

    PRD: "And no other policy of the same group and the same `domain` may already be in `BOARD_ADOPTED` or `EXAMINER_ACCEPTED`, with a duplicate refused by `ERR_POLICY_DOMAIN_ALREADY_ADOPTED`."

    Design: Difficulty/priority_pair_validation_conflict/organizer_qualification_safety_outranks_policy_domain_constraint
    """
    world = _lending_domain_already_adopted(api)
    before = fx.read_policy(api, world["pol_b"])

    validate_error(
        api.adopt_policy_document(
            world["pol_b"], make_independent_director_headers(world["o6"])
        ),
        "ERR_ORGANIZER_NOT_QUALIFIED",
    )

    assert_fields_equal(
        fx.read_policy(api, world["pol_a"]), domain=DOMAIN_LENDING,
        status=POLICY_BOARD_ADOPTED,
    )
    after = fx.read_policy(api, world["pol_b"])
    assert_fields_equal(
        after,
        status=POLICY_DRAFT,
        adopted_by_organizer_id=None,
        adopted_at=None,
        version=before["version"],
    )


def test_a_qualified_adopter_on_the_taken_domain_reaches_the_constraint_band(api):
    """
    With a qualified independent director acting instead, the earlier band is satisfied and
    the request falls through to the constraint that was there all along, proving the lower
    band is genuinely reachable rather than unreachable dead code.

    PRD: "The qualification gate is evaluated *before* the domain-uniqueness gate, so an unqualified organizer trying to adopt a second policy in an already-adopted domain is told about the qualification problem and never about the domain collision."

    Design: Difficulty/priority_pair_validation_conflict/organizer_qualification_safety_outranks_policy_domain_constraint
    """
    world = _lending_domain_already_adopted(api)
    qualified = get_success_data(api.get_organizer(world["o5"], CHARTERING_EXAMINER_HEADERS))
    assert_fields_equal(qualified, qualification_status=QUALIFICATION_QUALIFIED)

    validate_error(
        api.adopt_policy_document(
            world["pol_b"], make_independent_director_headers(world["o5"])
        ),
        "ERR_POLICY_DOMAIN_ALREADY_ADOPTED",
        expected_status=409,
    )
    assert_fields_equal(fx.read_policy(api, world["pol_b"]), status=POLICY_DRAFT)
