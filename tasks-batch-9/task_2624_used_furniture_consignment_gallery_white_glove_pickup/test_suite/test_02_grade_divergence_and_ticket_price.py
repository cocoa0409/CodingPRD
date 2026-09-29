"""Grading a piece twice, and the pinned order of the ticket-price arithmetic."""

from test_helpers import (
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    SCORES_GRADE_C,
    STD_SCHEDULE_STEPS,
    complete_pickup,
    create_item,
    create_truck,
    fetch_consignor,
    fetch_item,
    receive_item,
    schedule_pickup,
    screen_item,
    setup_consignor_with_active_agreement,
)
from test_helpers.test_users import FLOOR_OPERATOR_ID, INTAKE_APPRAISER_ID

TWO_STEP_SCHEDULE = STD_SCHEDULE_STEPS[:2]
WINDOW_START = "2026-08-05T09:00:00Z"
WINDOW_END = "2026-08-05T11:00:00Z"


def _sofa_in_custody_screened_as_b():
    """A 70-cubic-foot sofa photographed at grade B and collected from floor 3."""
    world = setup_consignor_with_active_agreement(
        consignor_overrides={"floor_number": 3, "has_elevator": False}
    )
    sofa = create_item(
        world["agreement"]["id"],
        title="Chesterfield sofa",
        category="SOFA",
        declared_value_cents=189_950,
        photo_count=6,
        volume_cuft=70,
        footprint_sqft=24,
    )
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    truck = create_truck()
    job = schedule_pickup(
        world["consignor"]["id"],
        truck["id"],
        [sofa["id"]],
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    complete_pickup(job["id"], actual_stair_flights=2)
    world["item"] = fetch_item(sofa["id"])
    return world


def test_inspection_overwrites_the_effective_grade_and_ticket_price():
    """Hands-on grading rewrites the effective columns to grade C figures.

    PRD 3.5: "`photo_score` is overwritten, `condition_grade` is overwritten with
    the newly derived grade, and `list_price_cents` is recomputed by the same
    two-step grade-and-category calculation using the new grade"

    Design: Difficulty/dual_variant_calc/condition_grade_provisional_vs_final_list_price_diverges
    """
    world = _sofa_in_custody_screened_as_b()
    item_id = world["item"]["id"]

    assert world["item"]["provisional_condition_grade"] == "B", (
        f"Expected B from the photographs, got {world['item']['provisional_condition_grade']}"
    )
    assert world["item"]["provisional_list_price_cents"] == 126_317, (
        f"Expected 126317, got {world['item']['provisional_list_price_cents']}"
    )

    receive_item(item_id, scores=SCORES_GRADE_C)
    item = fetch_item(item_id)

    assert item["photo_score"] == 5.03, (
        f"Expected 5.03 from 5.0/5.5/4.5, got {item['photo_score']}"
    )
    assert item["condition_grade"] == "C", (
        f"Expected C, got {item['condition_grade']}"
    )
    assert item["list_price_cents"] == 99_249, (
        f"Expected 99249, got {item['list_price_cents']}"
    )
    assert item["current_price_cents"] == 99_249, (
        f"Expected 99249, got {item['current_price_cents']}"
    )


def test_photographed_and_inspected_prices_stay_side_by_side_on_the_row():
    """Both price columns remain readable and unequal after the inspection.

    PRD 3.3: "`provisional_condition_grade` and `provisional_list_price_cents` are
    frozen at their screening values forever, while `condition_grade` and
    `list_price_cents` are the effective figures that later steps overwrite"

    Design: Difficulty/dual_variant_calc/condition_grade_provisional_vs_final_list_price_diverges
    """
    world = _sofa_in_custody_screened_as_b()
    item_id = world["item"]["id"]
    consignor_id = world["consignor"]["id"]

    receive_item(item_id, scores=SCORES_GRADE_C)
    item = fetch_item(item_id)

    assert item["provisional_condition_grade"] == "B", (
        f"The photographed grade must stay B, got {item['provisional_condition_grade']}"
    )
    assert item["provisional_list_price_cents"] == 126_317, (
        "The photographed price must stay 126317, got "
        f"{item['provisional_list_price_cents']}"
    )
    assert item["list_price_cents"] != item["provisional_list_price_cents"], (
        "The two price columns must diverge on this row"
    )
    assert item["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"A one-grade fall is absorbed; got {item['lifecycle_state']}"
    )
    assert item["election_deadline_at"] is None, (
        "No dispute, so no election deadline"
    )
    assert item["received_by_user_id"] == FLOOR_OPERATOR_ID, (
        f"Expected {FLOOR_OPERATOR_ID}, got {item['received_by_user_id']}"
    )
    assert item["screened_by_user_id"] == INTAKE_APPRAISER_ID, (
        f"Expected {INTAKE_APPRAISER_ID}, got {item['screened_by_user_id']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == -44_000, (
        f"Expected -44000 from the collection alone, got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["status"] == "ACTIVE", (
        f"Expected ACTIVE, got {consignor['status']}"
    )


def test_grade_factor_is_rounded_before_the_category_factor_is_applied():
    """The etching tickets at 132550, one cent above the collapsed product.

    PRD 3.3: "First, multiply `declared_value_cents` by the grade factor and round
    the product half up to a whole number of cents: the grade factors are 85
    hundredths for `A`, 70 hundredths for `B`, 55 hundredths for `C` and 40
    hundredths for `D`. Second, take that already-rounded integer number of cents,
    multiply it by the category factor, and round that product half up to a whole
    number of cents."

    Design: Difficulty/combinatorial_formula/list_price_two_step_rounding_order_pinned
    """
    world = setup_consignor_with_active_agreement(schedule_steps=TWO_STEP_SCHEDULE)
    etching = create_item(
        world["agreement"]["id"],
        title="Framed etching",
        category="ART",
        declared_value_cents=129_950,
        photo_count=4,
        volume_cuft=6,
        footprint_sqft=4,
    )

    screen_item(etching["id"], scores=SCORES_GRADE_A)
    item = fetch_item(etching["id"])

    assert item["photo_score"] == 8.55, (
        f"Expected 8.55 from 8.0/9.0/9.0, got {item['photo_score']}"
    )
    assert item["provisional_condition_grade"] == "A", (
        f"Expected A at 8.55, got {item['provisional_condition_grade']}"
    )
    assert item["provisional_list_price_cents"] == 132_550, (
        f"Expected 132550, got {item['provisional_list_price_cents']}"
    )
    assert item["provisional_list_price_cents"] != 132_549, (
        "Collapsing the grade and category factors into one multiplication is wrong"
    )
    assert item["list_price_cents"] == 132_550, (
        f"Screening seeds the effective price too, got {item['list_price_cents']}"
    )
    assert item["current_price_cents"] == 132_550, (
        f"Expected 132550, got {item['current_price_cents']}"
    )


def test_accepted_screening_seeds_both_price_columns_before_custody():
    """The accepted etching is priced and quotable while still in the residence.

    PRD 3.3: "while the derived grade seeds `condition_grade` as well as
    `provisional_condition_grade`, so the piece can be quoted and scheduled onto a
    truck before anyone has physically touched it."

    Design: Difficulty/combinatorial_formula/list_price_two_step_rounding_order_pinned
    """
    world = setup_consignor_with_active_agreement(schedule_steps=TWO_STEP_SCHEDULE)
    etching = create_item(
        world["agreement"]["id"],
        title="Framed etching",
        category="ART",
        declared_value_cents=129_950,
        photo_count=4,
        volume_cuft=6,
        footprint_sqft=4,
    )

    screen_item(etching["id"], scores=SCORES_GRADE_A)
    item = fetch_item(etching["id"])

    assert item["condition_grade"] == "A", (
        f"The effective grade is seeded too, got {item['condition_grade']}"
    )
    assert item["lifecycle_state"] == "SCREEN_ACCEPTED", (
        f"Expected SCREEN_ACCEPTED, got {item['lifecycle_state']}"
    )
    assert item["inventory_state"] == "PENDING_CUSTODY", (
        f"Nobody has collected it yet; got {item['inventory_state']}"
    )
    assert item["screened_by_user_id"] == INTAKE_APPRAISER_ID, (
        f"Expected {INTAKE_APPRAISER_ID}, got {item['screened_by_user_id']}"
    )
    assert item["list_price_cents"] == item["provisional_list_price_cents"] == 132_550, (
        "Both price columns start life on the same figure"
    )
