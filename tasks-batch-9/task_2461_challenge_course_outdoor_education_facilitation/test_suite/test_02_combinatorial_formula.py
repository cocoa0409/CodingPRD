"""Quote arithmetic: per-line rounding, the surcharge band and the deposit."""

from test_helpers import assert_money, validate_success
from test_helpers.constants import CLOCK_TEST_UTC
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    booking_version,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    quote_booking,
    set_clock,
)
from test_helpers.test_users import PROGRAM_DIRECTOR

FOUR_HEADS = [
    ("Ada Lin", "2013-05-10", 45.0),
    ("Ben Ortiz", "2013-02-18", 52.0),
    ("Cleo Park", "2012-12-01", 61.0),
    ("Dev Rao", "2013-08-22", 58.0),
]


def _four_head_partner_booking(api, with_high_element=True):
    """A PARTNER booking with four billable heads on the canonical program."""
    set_clock(api, CLOCK_TEST_UTC)
    course_id = create_course(api)
    g_id = create_element(api, course_id, "GROUND_INITIATIVE")
    l_id = create_element(api, course_id, "LOW_ELEMENT")
    h_id = create_element(api, course_id, "HIGH_ELEMENT")
    gc_id = create_funded_client(api)
    b_id, _ = create_booking(api, course_id, gc_id, 4)

    for full_name, birth_date, weight_kg in FOUR_HEADS:
        add_participant(
            api,
            gc_id,
            b_id,
            "ADULT",
            screen=False,
            full_name=full_name,
            birth_date=birth_date,
            weight_kg=weight_kg,
        )

    specs = [
        (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z", None),
        (2, "GROUND_INITIATIVE", "2026-09-15T09:45:00Z", "2026-09-15T10:30:00Z", g_id),
        (3, "LOW_ELEMENT", "2026-09-15T10:30:00Z", "2026-09-15T11:30:00Z", l_id),
    ]
    if with_high_element:
        specs.append(
            (4, "HIGH_ELEMENT", "2026-09-15T13:00:00Z", "2026-09-15T15:00:00Z", h_id)
        )
        specs.append((5, "DEBRIEF", "2026-09-15T15:15:00Z", "2026-09-15T16:00:00Z", None))
    else:
        specs.append((4, "DEBRIEF", "2026-09-15T15:15:00Z", "2026-09-15T16:00:00Z", None))
    block_ids = add_blocks(api, b_id, specs)

    return {
        "course_id": course_id,
        "gc_id": gc_id,
        "b_id": b_id,
        "block_ids": block_ids,
        "h_id": h_id,
    }


class TestQuoteSubtotalRounding:
    """The rounding step sits inside the per-line loop, not after the sum."""

    def test_per_line_rounding_produces_the_declared_subtotal(self, api):
        """Four PARTNER heads on the five-block program subtotal to 35,706 cents.

        PRD 3.5: "The rounding step sits inside the loop, once per line, and summing
        unrounded line amounts to round the total once at the end is a different and
        incorrect number: a `PARTNER` client with four billable heads running the
        canonical five-block program yields lines of 3,145, 4,625, 8,418, 17,205 and
        2,313 cents for a `raw_subtotal_cents` of 35,706, where sum-then-round would
        produce 35,705 — one cent adrift."

        Design: Difficulty/combinatorial_formula/quote_subtotal_rounds_each_program_block_line_before_summing
        """
        world = _four_head_partner_booking(api)

        version = booking_version(api, world["b_id"])
        quoted = validate_success(
            api.quote_booking(
                world["b_id"], {"expected_booking_version": version}, PROGRAM_DIRECTOR
            )
        )

        assert quoted["billable_head_count"] == 4
        assert quoted["block_count"] == 5
        assert_money(quoted["raw_subtotal_cents"], 35706, "raw_subtotal_cents")
        assert quoted["raw_subtotal_cents"] != 35705
        assert quoted["status"] == "QUOTED"
        assert quoted["quote_index"] == 1

    def test_requote_supersedes_the_figures_without_moving_the_subtotal(self, api):
        """Re-running the quote reproduces the same per-line arithmetic in place.

        PRD 3.5: "The booking's `status` must be `DRAFT` or `QUOTED`, otherwise the run
        is refused with `ERR_BOOKING_NOT_QUOTABLE`; a quote run from `DRAFT` advances the
        booking to `QUOTED`, and a re-quote from `QUOTED` supersedes the prior figures in
        place and leaves the status at `QUOTED`."

        Design: Difficulty/combinatorial_formula/quote_subtotal_rounds_each_program_block_line_before_summing
        """
        world = _four_head_partner_booking(api)
        first = quote_booking(api, world["b_id"])
        assert first["quote_index"] == 1

        version = booking_version(api, world["b_id"])
        second = validate_success(
            api.quote_booking(
                world["b_id"], {"expected_booking_version": version}, PROGRAM_DIRECTOR
            )
        )

        assert second["status"] == "QUOTED"
        assert second["quote_index"] == 2
        assert_money(second["raw_subtotal_cents"], 35706, "raw_subtotal_cents")


class TestHighElementSurchargeBand:
    """The band is resolved once, from the subtotal before the surcharge."""

    def test_band_resolved_from_the_pre_surcharge_subtotal(self, api):
        """A 35,706-cent subtotal draws 5 percent, not the 3 percent of the gross total.

        PRD 3.5: "Continuing the example above, a subtotal of 35,706 lands in the 5
        percent band, so the surcharge is 17,205 at 5 percent rounded up, which is 861,
        and `quoted_total_cents` is 36,567. Re-resolving the band against that
        surcharge-inclusive total would drop into the 3 percent band and silently produce
        517 and 36,223 instead; that reading is wrong."

        Design: Difficulty/combinatorial_formula/high_element_surcharge_band_resolved_once_from_pre_surcharge_subtotal
        """
        world = _four_head_partner_booking(api)

        quoted = quote_booking(api, world["b_id"])

        assert_money(quoted["raw_subtotal_cents"], 35706, "raw_subtotal_cents")
        assert_money(
            quoted["high_element_surcharge_cents"], 861, "high_element_surcharge_cents"
        )
        assert quoted["high_element_surcharge_cents"] != 517
        assert_money(quoted["quoted_total_cents"], 36567, "quoted_total_cents")
        assert quoted["quoted_total_cents"] != 36223
        assert_money(quoted["deposit_required_cents"], 9142, "deposit_required_cents")

    def test_program_without_a_high_element_line_draws_no_surcharge(self, api):
        """With no high-element line the surcharge base is zero and the total is the subtotal.

        PRD 3.5: "`high_element_surcharge_cents` is the high-element line total multiplied
        by that rate and rounded **up** to a whole cent — the operator never absorbs a
        partial cent of high-element risk loading."

        PRD 3.5: "`deposit_required_cents` is 25 percent of `quoted_total_cents`, rounded
        up to a whole cent — 9,142 on the 36,567 example."

        Design: Difficulty/combinatorial_formula/high_element_surcharge_band_resolved_once_from_pre_surcharge_subtotal
        """
        world = _four_head_partner_booking(api, with_high_element=False)

        quoted = quote_booking(api, world["b_id"])

        assert quoted["block_count"] == 4
        assert_money(quoted["raw_subtotal_cents"], 18501, "raw_subtotal_cents")
        assert_money(
            quoted["high_element_surcharge_cents"], 0, "high_element_surcharge_cents"
        )
        assert_money(quoted["quoted_total_cents"], 18501, "quoted_total_cents")
        assert_money(quoted["deposit_required_cents"], 4626, "deposit_required_cents")
