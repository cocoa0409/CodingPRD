"""Scoping the work: line loading, the roll-up order, and the review cycle."""

import pytest

from test_helpers import (
    api_client,
    assert_work_item,
    assert_work_write_up,
    assert_write_up_roll_up,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    PROGRAM_MANAGER,
    REHAB,
    add_work_item,
    build_write_up_with_lines,
    refresh_application,
    refresh_write_up,
    setup_case,
    setup_historic_case,
    submit_write_up,
)

# Three repair lines whose loaded totals only agree with the roll-up when each
# line is rounded before the sum is taken.
LEAD_LINE = {
    "description": "Window sash lead hazard reduction",
    "category": "LEAD_HAZARD_CONTROL",
    "priority_class": "HEALTH_SAFETY",
    "estimated_cost_cents": 1_234_567,
    "is_lead_hazard_reduction": True,
    "is_historic_sensitive": False,
}
HISTORIC_LINE = {
    "description": "Character-defining porch column repair",
    "category": "STRUCTURAL",
    "priority_class": "CODE",
    "estimated_cost_cents": 987_654,
    "is_lead_hazard_reduction": False,
    "is_historic_sensitive": True,
}
PLAIN_LINE = {
    "description": "Kitchen cabinet replacement",
    "category": "ACCESSIBILITY",
    "priority_class": "GENERAL_PROPERTY_IMPROVEMENT",
    "estimated_cost_cents": 500_001,
    "is_lead_hazard_reduction": False,
    "is_historic_sensitive": False,
}


def _list_write_ups_for(application_id):
    response = api_client.list_write_ups(REHAB, {"application_id": application_id})
    return validate_paginated(response)


@pytest.fixture
def three_line_write_up():
    """A submitted scope carrying one lead line, one historic line and one plain line."""
    case = setup_historic_case(stage="inspected", clear_compliance=False)
    write_up, work_items = build_write_up_with_lines(
        case["application"]["id"], [LEAD_LINE, HISTORIC_LINE, PLAIN_LINE]
    )
    case["write_up"] = submit_write_up(write_up["id"])
    case["work_items"] = work_items
    return case


class TestNestedRounding:
    """Line loading, then the sum, then the contingency — in that order."""

    def test_each_repair_line_carries_its_additive_uplift(self, three_line_write_up):
        """Both compliance uplifts load the line, and each line is rounded on its own.

        PRD: "Each line's `protocol_multiplier` starts at 1 and is increased
        **additively** by the uplifts the line triggers: fifteen percent when
        `is_lead_hazard_reduction` is true, and twelve percent when
        `is_historic_sensitive` is true."

        Design: Difficulty/combinatorial_formula/write_up_estimate_pins_round_each_line_then_sum_then_round_contingency
        """
        lead, historic, plain = three_line_write_up["work_items"]

        for line in (lead, historic, plain):
            assert_work_item(line)
        assert lead["protocol_multiplier"] == pytest.approx(1.15, abs=0.01)
        assert lead["line_total_cents"] == 1_419_752, (
            "1,234,567 at 1.15 rounds half up to 1,419,752, got "
            f"{lead['line_total_cents']}"
        )
        assert historic["protocol_multiplier"] == pytest.approx(1.12, abs=0.01)
        assert historic["line_total_cents"] == 1_106_172, (
            "987,654 at 1.12 rounds half up to 1,106,172, got "
            f"{historic['line_total_cents']}"
        )
        assert plain["protocol_multiplier"] == pytest.approx(1.0, abs=0.01)
        assert plain["line_total_cents"] == 500_001

    def test_the_roll_up_sums_rounded_lines_before_rounding_the_contingency(
        self, three_line_write_up
    ):
        """The pinned order lands one cent below the sum-then-round order.

        PRD: "`base_estimate_cents` is then the sum of the already-rounded
        `line_total_cents` of every line on the write-up. `contingency_cents` is
        `base_estimate_cents` multiplied by a flat ten percent contingency,
        rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/write_up_estimate_pins_round_each_line_then_sum_then_round_contingency
        """
        write_up = three_line_write_up["write_up"]

        assert_work_write_up(write_up)
        assert_write_up_roll_up(write_up)
        assert write_up["base_estimate_cents"] == 3_025_925, (
            "Summing the three rounded lines gives 3,025,925, got "
            f"{write_up['base_estimate_cents']}"
        )
        assert write_up["base_estimate_cents"] != 3_025_926, (
            "3,025,926 is the figure produced by summing the raw products before "
            "rounding, which the roll-up order forbids"
        )
        assert write_up["contingency_cents"] == 302_593
        assert write_up["total_estimate_cents"] == 3_328_518
        assert write_up["total_estimate_cents"] != 3_328_519, (
            "3,328,519 is the figure produced by summing the raw products before "
            "rounding, which the roll-up order forbids"
        )

    def test_the_priority_total_restricts_itself_to_the_loaded_priority_lines(
        self, three_line_write_up
    ):
        """The priority subtotal is taken from the loaded line totals, not the raw ones.

        PRD: "`priority_repair_total_cents` is the sum of `line_total_cents`
        restricted to lines whose `priority_class` is `HEALTH_SAFETY` or `CODE`,
        and `work_item_count` is simply the number of lines on the write-up."

        Design: Difficulty/combinatorial_formula/write_up_estimate_pins_round_each_line_then_sum_then_round_contingency
        """
        write_up = three_line_write_up["write_up"]

        assert write_up["priority_repair_total_cents"] == 2_525_924, (
            "The loaded health-and-safety and code lines total 2,525,924, got "
            f"{write_up['priority_repair_total_cents']}"
        )
        assert write_up["work_item_count"] == 3
        assert write_up["state"] == "SUBMITTED"


class TestRevisionCycle:
    """`SUBMITTED` and `REVISION_REQUESTED` form a loop on one write-up row."""

    def test_a_returned_scope_can_be_edited_and_resubmitted(self):
        """The specialist edits lines again and the same row returns to `SUBMITTED`.

        PRD: "The specialist may edit repair lines again and resubmit, moving
        `REVISION_REQUESTED → SUBMITTED` under exactly the same two gates and
        recomputing the same five estimate figures."

        Design: Difficulty/non_linear_state_machine/write_up_revision_cycle_returns_to_submitted_on_the_same_row
        """
        case = setup_case(stage="writeup_submitted")
        write_up_id = case["write_up"]["id"]

        returned = validate_success(
            api_client.request_write_up_revision(
                write_up_id,
                {
                    "revision_note": (
                        "Add the code-required egress window; roof line only is "
                        "not sufficient."
                    )
                },
                PROGRAM_MANAGER,
            ),
            200,
        )
        assert returned["state"] == "REVISION_REQUESTED"

        add_work_item(
            write_up_id,
            description="Bedroom egress window",
            category="WINDOWS",
            priority_class="CODE",
            estimated_cost_cents=400_000,
        )
        resubmitted = submit_write_up(write_up_id)

        assert resubmitted["state"] == "SUBMITTED"
        assert resubmitted["work_item_count"] == 2
        assert resubmitted["base_estimate_cents"] == 2_400_000
        assert resubmitted["contingency_cents"] == 240_000
        assert resubmitted["total_estimate_cents"] == 2_640_000
        assert resubmitted["priority_repair_total_cents"] == 2_400_000

    def test_the_cycle_repeats_on_the_same_row_without_minting_a_revision(self):
        """A second return trip reuses the row and leaves `revision_number` at 1.

        PRD: "That loop may repeat without bound on the same row."

        Design: Difficulty/non_linear_state_machine/write_up_revision_cycle_returns_to_submitted_on_the_same_row
        """
        case = setup_case(stage="writeup_submitted")
        write_up_id = case["write_up"]["id"]
        application_id = case["application"]["id"]

        validate_success(
            api_client.request_write_up_revision(
                write_up_id,
                {"revision_note": "Add the code-required egress window."},
                PROGRAM_MANAGER,
            ),
            200,
        )
        add_work_item(
            write_up_id,
            description="Bedroom egress window",
            category="WINDOWS",
            priority_class="CODE",
            estimated_cost_cents=400_000,
        )
        submit_write_up(write_up_id)
        validate_success(
            api_client.request_write_up_revision(
                write_up_id,
                {
                    "revision_note": (
                        "Second pass: confirm the egress unit is a code-compliant "
                        "size."
                    )
                },
                PROGRAM_MANAGER,
            ),
            200,
        )
        final = submit_write_up(write_up_id)

        assert final["state"] == "SUBMITTED"
        assert final["revision_number"] == 1, (
            "Cycling through review reuses the row rather than opening a new "
            f"revision, got revision_number {final['revision_number']}"
        )
        write_ups, _ = _list_write_ups_for(application_id)
        assert len(write_ups) == 1, (
            f"Exactly one write-up should exist on the case, got {len(write_ups)}"
        )

    def test_the_case_stays_inspected_for_the_whole_review_cycle(self):
        """Only approval moves the case forward, so the cycle leaves it in `INSPECTED`.

        PRD: "Approval by a `ProgramManager` moves the write-up `SUBMITTED →
        APPROVED`, stamps `approved_by_user_id` with the acting `X-User-ID`, and
        drives the case `INSPECTED → WRITEUP_APPROVED`; both rows advance their
        `version` by one."

        Design: Difficulty/non_linear_state_machine/write_up_revision_cycle_returns_to_submitted_on_the_same_row
        """
        case = setup_case(stage="writeup_submitted")
        write_up_id = case["write_up"]["id"]
        application_id = case["application"]["id"]

        assert refresh_application(application_id)["workflow_state"] == "INSPECTED"

        validate_success(
            api_client.request_write_up_revision(
                write_up_id,
                {"revision_note": "Add the code-required egress window."},
                PROGRAM_MANAGER,
            ),
            200,
        )
        assert refresh_application(application_id)["workflow_state"] == "INSPECTED"

        submit_write_up(write_up_id)

        assert refresh_application(application_id)["workflow_state"] == "INSPECTED", (
            "The review cycle never advances the case's workflow axis"
        )
        assert refresh_write_up(write_up_id)["state"] == "SUBMITTED"


