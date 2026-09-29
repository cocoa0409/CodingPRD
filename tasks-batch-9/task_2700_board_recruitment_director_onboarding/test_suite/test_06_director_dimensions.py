"""One director row, three state dimensions that advance on separate schedules.

The service dimension, the compliance dimension and the onboarding dimension are
moved one at a time while the other two are pinned: closing orientation modules
only drives the onboarding rollup, seating only moves service, and ending an
outside board seat only clears the compliance posture.
"""
from prd_bench_local_runner.testing import validate_success
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_fields_equal, assert_onboarding_rollup
from test_helpers.test_users import STAFF

# The director sits as a chief executive elsewhere, so the sitting-CEO ceiling is
# the limit that applies to them.
OUTSIDE_PUBLIC_BOARDS = 2

# Two outside public seats are recorded while the ceiling still leaves room for
# them (a count of 2 plus this board is 3, which does not exceed 3)...
CEILING_WHILE_SEATS_ARE_RECORDED = 3
PERMISSIVE_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"

# ...and the ceiling is then tightened to 2, which is what puts the director's
# count of 2 plus this board over the limit and makes the posture OVERBOARDED.
CEILING_AFTER_TIGHTENING = 2
TIGHTENED_CYCLE_YEAR = 2027
TIGHTENED_EFFECTIVE_FROM = "2027-01-01T00:00:00Z"

# Moving the clock is what re-derives every director's compliance posture under
# the tightened ceiling; it is the only step here that touches the clock.
CLOCK_AFTER_TIGHTENING = "2026-08-02T00:00:00Z"

# Two required modules, so each closure is worth exactly half the programme.
PCT_NOTHING_DONE = 0.00
PCT_ONE_OF_TWO = 50.00
PCT_BOTH_DONE = 100.00

ITEM_DUE_ON = "2026-09-30"
SEAT_ENDED_ON = "2026-08-01"


def _director_across_three_dimensions(client):
    """One ONBOARDING director who is OVERBOARDED and has touched no module yet.

    Returns the director row and the two outside seats and two required items
    that the triggers act on.
    """
    X.adopt_policy(
        client,
        effective_from=PERMISSIVE_EFFECTIVE_FROM,
        max_public_boards_sitting_ceo=CEILING_WHILE_SEATS_ARE_RECORDED,
    )
    director = X.new_onboarding_director(
        client,
        full_name="Parker Parallel",
        email="parker@issuer.example",
        birth_date="1975-01-01",
        appointed_on="2026-07-01",
        is_sitting_ceo_elsewhere=True,
    )
    company_one = X.new_external_company(
        client,
        name="Northwind Industries",
        ticker="NWI",
        is_public=True,
        is_competitor=False,
        gross_revenue_cents=500000000000,
    )
    company_two = X.new_external_company(
        client,
        name="Cascade Logistics",
        ticker="CSL",
        is_public=True,
        is_competitor=False,
        gross_revenue_cents=300000000000,
    )
    seat_one = X.seat_director_on_board(
        client, director["id"], company_one["id"], seat_role="DIRECTOR", start_on="2023-01-01"
    )
    seat_two = X.seat_director_on_board(
        client, director["id"], company_two["id"], seat_role="DIRECTOR", start_on="2024-01-01"
    )
    item_one = X.new_onboarding_item(
        client,
        director["id"],
        module_code="BUSINESS_ORIENTATION_101",
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=0.0,
        due_on=ITEM_DUE_ON,
    )
    item_two = X.new_onboarding_item(
        client,
        director["id"],
        module_code="BOARD_PORTAL_ACCESS",
        category="DOCUMENT_ACCESS",
        is_required=True,
        credit_hours=0.0,
        due_on=ITEM_DUE_ON,
    )
    X.adopt_policy(
        client,
        cycle_year=TIGHTENED_CYCLE_YEAR,
        effective_from=TIGHTENED_EFFECTIVE_FROM,
        max_public_boards_sitting_ceo=CEILING_AFTER_TIGHTENING,
    )
    X.set_clock(client, CLOCK_AFTER_TIGHTENING)
    return {
        "director": director,
        "seat_one": seat_one,
        "seat_two": seat_two,
        "item_one": item_one,
        "item_two": item_two,
    }


def _end_seat(client, directorship_id):
    return validate_success(
        client.end_external_directorship(
            directorship_id, F.end_directorship_payload(end_on=SEAT_ENDED_ON), STAFF
        ),
        200,
    )


def test_the_three_dimensions_start_in_three_unrelated_states(client):
    """Before any trigger the director is mid-onboarding, has touched no module, and is
    already OVERBOARDED because the sitting-CEO ceiling is the limit that applies.

    PRD: "The applicable limit is the policy's `max_public_boards_sitting_ceo` when the director's `is_sitting_ceo_elsewhere` is true and its `max_public_boards_default` otherwise."

    Design: Difficulty/non_linear_state_machine/director_three_parallel_dimensions_advance_without_touching_each_other
    """
    world = _director_across_three_dimensions(client)

    director = X.get_director(client, world["director"]["id"])

    assert_fields_equal(
        director,
        {
            "service_status": "ONBOARDING",
            "compliance_status": "OVERBOARDED",
            "external_public_board_count": OUTSIDE_PUBLIC_BOARDS,
        },
    )
    assert_onboarding_rollup(director, "NOT_STARTED", PCT_NOTHING_DONE)


def test_closing_the_first_module_moves_only_the_onboarding_dimension(client):
    """One of the two required modules is satisfied, so the programme is IN_PROGRESS while
    the service and compliance dimensions stay exactly where they were.

    PRD: "is `COMPLETED` or `WAIVED` but some required item is still `PENDING`, the status is `IN_PROGRESS`"

    Design: Difficulty/non_linear_state_machine/director_three_parallel_dimensions_advance_without_touching_each_other
    """
    world = _director_across_three_dimensions(client)

    X.complete_item(client, world["item_one"]["id"])

    assert_fields_equal(
        X.get_director(client, world["director"]["id"]),
        {
            "onboarding_status": "IN_PROGRESS",
            "service_status": "ONBOARDING",
            "compliance_status": "OVERBOARDED",
        },
    )


def test_closing_the_second_module_completes_the_programme_and_nothing_else(client):
    """With every required module satisfied the onboarding dimension reads COMPLETE, and the
    director is still neither seated nor back inside the board ceiling.

    PRD: "Otherwise, when every required item is satisfied the status is `COMPLETE`"

    Design: Difficulty/non_linear_state_machine/director_three_parallel_dimensions_advance_without_touching_each_other
    """
    world = _director_across_three_dimensions(client)
    X.complete_item(client, world["item_one"]["id"])

    X.complete_item(client, world["item_two"]["id"])

    assert_fields_equal(
        X.get_director(client, world["director"]["id"]),
        {
            "onboarding_status": "COMPLETE",
            "service_status": "ONBOARDING",
            "compliance_status": "OVERBOARDED",
        },
    )


def test_the_completion_percentage_climbs_one_required_module_at_a_time(client):
    """The percentage is the satisfied share of the required set, so two required modules
    take it from 0.00 to 50.00 and then to 100.00.

    PRD: "otherwise 100 multiplied by the size of the satisfied set divided by the size of the required set, rounded half up to two decimal places"

    Design: Difficulty/non_linear_state_machine/director_three_parallel_dimensions_advance_without_touching_each_other
    """
    world = _director_across_three_dimensions(client)

    assert_onboarding_rollup(
        X.get_director(client, world["director"]["id"]), "NOT_STARTED", PCT_NOTHING_DONE
    )

    X.complete_item(client, world["item_one"]["id"])
    assert_onboarding_rollup(
        X.get_director(client, world["director"]["id"]), "IN_PROGRESS", PCT_ONE_OF_TWO
    )

    X.complete_item(client, world["item_two"]["id"])
    assert_onboarding_rollup(
        X.get_director(client, world["director"]["id"]), "COMPLETE", PCT_BOTH_DONE
    )


def test_seating_moves_the_service_dimension_and_leaves_the_other_two_alone(client):
    """A completed programme is the only precondition seating reads, so the director takes
    their seat while still carrying the OVERBOARDED posture.

    PRD: "A director can be seated and education-delinquent and onboarding-complete all at once; the three dimensions never gate each other except where a rule explicitly says so."

    Design: Difficulty/non_linear_state_machine/director_three_parallel_dimensions_advance_without_touching_each_other
    """
    world = _director_across_three_dimensions(client)
    X.complete_item(client, world["item_one"]["id"])
    X.complete_item(client, world["item_two"]["id"])

    X.seat_director(client, world["director"]["id"])

    assert_fields_equal(
        X.get_director(client, world["director"]["id"]),
        {
            "service_status": "SEATED",
            "onboarding_status": "COMPLETE",
            "compliance_status": "OVERBOARDED",
            "external_public_board_count": OUTSIDE_PUBLIC_BOARDS,
        },
    )


def test_ending_one_outside_seat_moves_only_the_compliance_dimension(client):
    """Giving up the second outside board brings the count back inside the ceiling and the
    posture back to COMPLIANT, while the seat and the programme stay put.

    PRD: "once the row is `ENDED`, if the count plus one is at or below the limit and neither the ownership leg nor the education leg fails, the director returns from `OVERBOARDED` to `COMPLIANT`"

    Design: Difficulty/non_linear_state_machine/director_three_parallel_dimensions_advance_without_touching_each_other
    """
    world = _director_across_three_dimensions(client)
    X.complete_item(client, world["item_one"]["id"])
    X.complete_item(client, world["item_two"]["id"])
    X.seat_director(client, world["director"]["id"])

    _end_seat(client, world["seat_two"]["id"])

    assert_fields_equal(
        X.get_director(client, world["director"]["id"]),
        {
            "compliance_status": "COMPLIANT",
            "external_public_board_count": 1,
            "service_status": "SEATED",
            "onboarding_status": "COMPLETE",
        },
    )
    assert X.get_directorship(client, world["seat_one"]["id"])["status"] == "ACTIVE"
    assert X.get_directorship(client, world["seat_two"]["id"])["status"] == "ENDED"
