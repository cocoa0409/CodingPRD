"""Shop events and the derived service status: parallel dimensions on one unit,
the failed-inspection cascade and the damage-point ceiling."""


from test_helpers import (
    TEST_USERS,
    fail_dot_inspection,
    file_maintenance_event,
    list_units,
    open_assessment,
    read_agreement,
    read_agreement_unit,
    read_branch,
    read_customer,
    read_trailer,
    setup_agreement_active,
    setup_agreement_reserved,
    setup_pending_chargeback,
    submit_assessment,
)

ADMIN = TEST_USERS["fleet_admin_headers"]

_TWENTY_FIVE_POINT_ITEMS = [
    {"severity": "MODERATE", "quantity": 2, "unit_cost_cents": 30000,
     "description": "roof panel"},
    {"severity": "MINOR", "quantity": 3, "unit_cost_cents": 10000,
     "description": "scuff"},
]


def test_failed_inspection_moves_service_status_while_availability_holds_on_rent(api):
    """PRD §3.7: "A `DOT_INSPECTION` event with `passed` false is the head of the
    deepest cascade in the fleet. It sets `last_dot_passed` to false, which forces
    the unit `SERVICEABLE → OOS_DOT_EXPIRED`."
    PRD §3.1: "Commercial availability and mechanical condition are tracked as two
    independent dimensions on the same unit."

    Design: Difficulty/non_linear_state_machine/trailer_service_dimension_moves_while_availability_dimension_holds_on_rent
    """
    scn = setup_agreement_active(checkout_date="2026-08-20")
    assert read_trailer(scn["trailer_id"])["availability_status"] == "ON_RENT"

    fail_dot_inspection(scn["trailer_id"], performed_on="2026-08-25",
                        hub_miles_at_event=42000, cost_cents=12000)

    trailer = read_trailer(scn["trailer_id"])
    assert trailer["availability_status"] == "ON_RENT", (
        "the commercial dimension does not move because the shop dimension did"
    )
    assert trailer["service_status"] == "OOS_DOT_EXPIRED"
    assert trailer["last_dot_passed"] is False


def test_a_unit_already_out_with_a_customer_is_not_swapped_off_its_contract(api):
    """PRD §3.7: "Contract unit lines that are already `OUT` are not swapped out; a
    unit already with a customer stays on its contract until it is returned."
    PRD §3.7: "Every contract unit line standing on that unit in status `ALLOCATED`
    is then swapped out, moving `ALLOCATED → SWAPPED_OUT`."

    Design: Difficulty/non_linear_state_machine/trailer_service_dimension_moves_while_availability_dimension_holds_on_rent
    """
    scn = setup_agreement_active(checkout_date="2026-08-20")

    fail_dot_inspection(scn["trailer_id"], performed_on="2026-08-25",
                        hub_miles_at_event=42000, cost_cents=12000)

    assert read_agreement_unit(scn["unit_id"])["status"] == "OUT"
    assert read_agreement(scn["agreement_id"])["status"] == "ACTIVE"
    assert read_trailer(scn["trailer_id"])["service_status"] == "OOS_DOT_EXPIRED"


def test_failed_inspection_swaps_out_the_allocated_line_and_frees_the_unit(api):
    """PRD §3.7: "For each such swap the trailer's availability returns `ALLOCATED
    → AVAILABLE`, but only when no other contract unit line on that same trailer
    remains in status `ALLOCATED` or `OUT`; when another live booking still stands
    on the unit, the availability dimension is left unchanged."
    PRD §3.7: "Every contract unit line standing on that unit in status `ALLOCATED`
    is then swapped out, moving `ALLOCATED → SWAPPED_OUT`."

    Design: Difficulty/transitive_cascade/failed_dot_inspection_cascade_depth3_reverts_agreement_to_pending_allocation
    """
    scn = setup_agreement_reserved()
    unit_id = list_units(agreement_id=scn["agreement_id"])[0]["id"]

    fail_dot_inspection(scn["trailer_id"], performed_on="2026-08-10",
                        hub_miles_at_event=41000)

    trailer = read_trailer(scn["trailer_id"])
    assert trailer["service_status"] == "OOS_DOT_EXPIRED"
    assert trailer["availability_status"] == "AVAILABLE"
    assert read_agreement_unit(unit_id)["status"] == "SWAPPED_OUT"

    branch = read_branch(scn["branch_id"])
    assert branch["serviceable_available_count"] == 0, (
        "the unit is idle but no longer serviceable"
    )
    assert branch["on_hand_count"] == 1


def test_a_swapped_out_line_walks_the_contract_back_with_its_pricing_intact(api):
    """PRD §3.7: "And for each swap, when the owning contract is in `RESERVED` and
    its `allocated_unit_count` has now fallen below its `unit_count`, that contract
    falls back `RESERVED → PENDING_ALLOCATION` — with, as section 3.5 states, its
    `rate_card_id` and `quoted_total_cents` left pinned at the values they already
    hold."
    PRD §3.5: "Once pinned, the card and the quote are permanent."

    Design: Difficulty/transitive_cascade/failed_dot_inspection_cascade_depth3_reverts_agreement_to_pending_allocation
    """
    scn = setup_agreement_reserved()
    before = read_agreement(scn["agreement_id"])
    assert before["quoted_total_cents"] == 123240
    pinned_card = before["rate_card_id"]

    fail_dot_inspection(scn["trailer_id"], performed_on="2026-08-10",
                        hub_miles_at_event=41000)

    after = read_agreement(scn["agreement_id"])
    assert after["status"] == "PENDING_ALLOCATION"
    assert after["allocated_unit_count"] == 0
    assert after["quoted_total_cents"] == 123240, "the quote stays pinned"
    assert after["rate_card_id"] == pinned_card, "the card stays pinned"


def test_twenty_four_damage_points_leaves_the_unit_serviceable(api):
    """PRD §3.7: "`OOS_DAMAGE`, when the live damage-point sum is at least 25. The
    damage boundary is inclusive as well: exactly 25 points puts the unit out of
    service, and 24 points does not."
    PRD §3.8: "In parallel the server accumulates `damage_points` as the sum, over
    the same line items, of the severity's point weight multiplied by the item's
    `quantity`, where a `MINOR` item is worth 3 points each, a `MODERATE` item 8
    points each, and a `MAJOR` item 15 points each."

    Design: Difficulty/boundary_precision_check/damage_points_inclusive_threshold_24_stays_serviceable_25_goes_out_of_service
    """
    scn = setup_pending_chargeback(
        line_items=[{"severity": "MODERATE", "quantity": 3, "unit_cost_cents": 30000,
                     "description": "three moderate panels"}]
    )
    assert scn["assessment"]["damage_points"] == 24
    assert scn["assessment"]["assessed_amount_cents"] == 112500

    trailer = read_trailer(scn["trailer_id"])
    assert trailer["damage_points"] == 24
    assert trailer["service_status"] == "SERVICEABLE", "24 points is below the ceiling"


def test_a_repair_clears_the_watermark_and_exactly_25_points_puts_the_unit_out(api):
    """PRD §3.7: "A `DAMAGE_REPAIR` event sets the unit's `last_damage_repair_at`
    to that event's own `created_at`, sweeping every earlier assessment out of the
    live damage-point sum; when the resulting sum falls below 25 and neither an
    inspection problem nor a maintenance-mileage problem stands in the way, the
    unit moves `OOS_DAMAGE → SERVICEABLE`."
    PRD §3.7: "`OOS_DAMAGE`, when the live damage-point sum is at least 25. The
    damage boundary is inclusive as well: exactly 25 points puts the unit out of
    service, and 24 points does not."

    Design: Difficulty/boundary_precision_check/damage_points_inclusive_threshold_24_stays_serviceable_25_goes_out_of_service
    """
    scn = setup_pending_chargeback(
        line_items=[{"severity": "MODERATE", "quantity": 3, "unit_cost_cents": 30000,
                     "description": "three moderate panels"}]
    )
    assert read_trailer(scn["trailer_id"])["damage_points"] == 24

    file_maintenance_event(scn["trailer_id"], event_type="DAMAGE_REPAIR",
                           performed_on="2026-09-04", hub_miles_at_event=42000,
                           cost_cents=75000)
    repaired = read_trailer(scn["trailer_id"])
    assert repaired["damage_points"] == 0, "the repair watermark sweeps the earlier sum"
    assert repaired["service_status"] == "SERVICEABLE"

    second = open_assessment(scn, line_items=_TWENTY_FIVE_POINT_ITEMS)
    submitted = submit_assessment(second["id"])
    assert submitted["damage_points"] == 25

    trailer = read_trailer(scn["trailer_id"])
    assert trailer["damage_points"] == 25
    assert trailer["service_status"] == "OOS_DAMAGE", "exactly 25 points is out of service"
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 234900
