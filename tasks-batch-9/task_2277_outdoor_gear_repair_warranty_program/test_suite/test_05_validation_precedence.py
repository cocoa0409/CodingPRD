"""Ordered-gauntlet precedence: when a request violates two checks of PRD §2.11.

Every request in this API runs one ordered gauntlet and the lowest-numbered
failing check owns the response. Each test below builds a request that breaks
two numbered checks at once and pins the earlier one as the answer, then pins
the absence of any side effect the later check would have needed to see.
"""

from test_helpers import (
    ERR_INSUFFICIENT_PART_UNITS,
    ERR_INVALID_WORK_STATE,
    ERR_PART_MODEL_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TECHNICIAN_NOT_CERTIFIED,
    ERR_TECHNICIAN_WINDOW_CONFLICT,
    assert_part_lot_counts,
    assert_row_ids,
    factories,
    make_technician_headers,
    validate_error,
    validate_paginated,
)

# The pack model and its strap lot live on a model the repair order knows
# nothing about — the referential trap of the third precedence pair.
PACK_MODEL_CODE = "PCK-SUMMIT-40"
STRAP_PART_CODE = "SUM40-STRAP-KIT"

BLOCK_DATE = "2026-06-16"
ZIP_BLOCK_START = f"{BLOCK_DATE}T09:00:00Z"
ZIP_BLOCK_END = f"{BLOCK_DATE}T11:00:00Z"
OVERLAP_START = f"{BLOCK_DATE}T10:00:00Z"
OVERLAP_END = f"{BLOCK_DATE}T12:00:00Z"


def _order_in_work_with_assessor_block(world):
    """Push the warranty order to IN_WORK with a block for the assessing tech.

    The order's only bench block belongs to T-101, the technician who authored
    the claim's assessment, so a QC signature from T-101 breaks the segregation
    rule while the order is still short of BENCH_DONE.
    """
    block = world.scenario.work_block(
        world.order_id,
        world.technician_id,
        work_type="FABRIC",
        start_at=ZIP_BLOCK_START,
        end_at=ZIP_BLOCK_END,
    )
    order = world.scenario.read_order(world.order_id)
    assert order["work_status"] == "IN_WORK", order
    return block


def _uncertified_tech_already_booked(world):
    """Book T-102 on a ZIPPER block so a later FRAME request both clashes and
    lands on a lane T-102 holds no certification for."""
    return world.scenario.work_block(
        world.order_id,
        world.second_technician_id,
        work_type="ZIPPER",
        start_at=ZIP_BLOCK_START,
        end_at=ZIP_BLOCK_END,
    )


def _foreign_model_strap_lot(world):
    """Stock a one-unit strap lot under an unrelated pack model."""
    pack_model = world.scenario.model(
        model_code=PACK_MODEL_CODE,
        name="Summit 40 Pack",
        category="PACK_HARNESS",
        msrp_cents=24900,
        release_year=2023,
        warranty_years=5,
    )
    strap_lot = world.scenario.part_lot(
        pack_model["id"],
        part_code=STRAP_PART_CODE,
        part_kind="BUCKLE",
        on_hand_units=1,
        unit_price_cents=1500,
        low_watermark_units=1,
    )
    return pack_model, strap_lot


class TestQcWorkStateBeatsSegregationOfDuties:
    """PRD §2.11 check 12 (work state) outranks check 22 (segregation)."""

    def test_qc_on_in_work_order_by_assessor_reports_invalid_work_state(
        self, api, open_order
    ):
        """QC signed by the assessing technician on an IN_WORK order reports check 12.

        "Every request runs the same ordered gauntlet, and the **first** check that fails produces the response — no later check is evaluated, so a request that violates several rules always reports the earliest one."
        "(12) An order's `work_status` is a legal origin state, else `ERR_INVALID_WORK_STATE` (409); this guards work-block scheduling, bench-complete, quality-control inspection, condemnation, invoicing, release-to-customer and parts reservation."
        "(22) The technician signing a quality-control inspection authored no assessment on that order's claim, else `ERR_SEGREGATION_OF_DUTIES` (403)."
        "**Quality control** is signed by a `RepairTechnician` on an order in `work_status` `BENCH_DONE`, supplying an `outcome` of either a pass or a fail plus optional `notes`."

        Design: Difficulty/priority_pair_validation_conflict/qc_work_state_beats_segregation_of_duties
        """
        _order_in_work_with_assessor_block(open_order)

        response = api.create_qc_inspection(
            open_order.order_id,
            {"outcome": "PASS", "notes": "Looks fine to me."},
            make_technician_headers(open_order.technician_id),
        )

        validate_error(response, ERR_INVALID_WORK_STATE)

    def test_rejected_qc_leaves_order_in_work_and_block_scheduled(
        self, api, open_order
    ):
        """The refused QC signature moves neither the bench dimension nor the block.

        "(12) An order's `work_status` is a legal origin state, else `ERR_INVALID_WORK_STATE` (409); this guards work-block scheduling, bench-complete, quality-control inspection, condemnation, invoicing, release-to-customer and parts reservation."
        "(22) The technician signing a quality-control inspection authored no assessment on that order's claim, else `ERR_SEGREGATION_OF_DUTIES` (403)."
        "A passing inspection moves the order `BENCH_DONE` → `QC_PASSED`."
        "the order's bench dimension begins at `QUEUED` with `commitment_breached` false, `qc_fail_count` at 0, `paid_amount_cents` at 0"

        Design: Difficulty/priority_pair_validation_conflict/qc_work_state_beats_segregation_of_duties
        """
        block = _order_in_work_with_assessor_block(open_order)

        response = api.create_qc_inspection(
            open_order.order_id,
            {"outcome": "PASS", "notes": "Looks fine to me."},
            make_technician_headers(open_order.technician_id),
        )
        validate_error(response, ERR_INVALID_WORK_STATE)

        order = open_order.scenario.read_order(open_order.order_id)
        assert order["work_status"] == "IN_WORK", order
        assert order["qc_fail_count"] == 0, order

        stored_block = open_order.scenario.read_work_block(block["id"])
        assert stored_block["status"] == "SCHEDULED", stored_block

    def test_segregation_answers_once_the_order_reaches_bench_done(
        self, api, bench_completed_order
    ):
        """With check 12 satisfied at BENCH_DONE, check 22 is the one that answers.

        "(12) An order's `work_status` is a legal origin state, else `ERR_INVALID_WORK_STATE` (409); this guards work-block scheduling, bench-complete, quality-control inspection, condemnation, invoicing, release-to-customer and parts reservation."
        "(22) The technician signing a quality-control inspection authored no assessment on that order's claim, else `ERR_SEGREGATION_OF_DUTIES` (403)."
        "The signer must have authored no assessment on this order's claim, or the request is refused with `ERR_SEGREGATION_OF_DUTIES` — the technician who judged defect versus wear may not also certify their own bench's repair."

        Design: Difficulty/priority_pair_validation_conflict/qc_work_state_beats_segregation_of_duties
        """
        order = bench_completed_order.scenario.read_order(
            bench_completed_order.order_id
        )
        assert order["work_status"] == "BENCH_DONE", order

        response = api.create_qc_inspection(
            bench_completed_order.order_id,
            {"outcome": "PASS", "notes": "Looks fine to me."},
            make_technician_headers(bench_completed_order.technician_id),
        )

        validate_error(response, ERR_SEGREGATION_OF_DUTIES)


class TestCertificationBeatsTechnicianWindowConflict:
    """PRD §2.11 check 21 (certification) outranks check 34 (window clash)."""

    def test_uncertified_and_double_booked_block_reports_not_certified(
        self, api, agent_headers, open_order
    ):
        """A FRAME block for a ZIPPER-only technician who is also busy reports check 21.

        "Every request runs the same ordered gauntlet, and the **first** check that fails produces the response — no later check is evaluated, so a request that violates several rules always reports the earliest one."
        "(21) The technician holds the required certification level, else `ERR_TECHNICIAN_NOT_CERTIFIED` (403); on assessment recording this is checked for every entry of the submitted `required_work_types`, and on work-block scheduling for the block's `work_type` when a `technician_id` is explicitly supplied."
        "(34) An explicitly named technician has no scheduled block overlapping the requested interval on half-open semantics, else `ERR_TECHNICIAN_WINDOW_CONFLICT` (409)."
        "When `technician_id` is supplied explicitly, that technician must have roster `status` `ACTIVE`, must belong to the order's centre, must hold a certification for the block's `work_type` at or above that lane's minimum level, and must have no block already in `status` `SCHEDULED` overlapping the requested half-open interval — a conflict is refused with `ERR_TECHNICIAN_WINDOW_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/certification_beats_technician_window_conflict
        """
        _uncertified_tech_already_booked(open_order)

        payload = factories.work_block_payload(
            open_order.order_id,
            work_type="FRAME",
            start_at=OVERLAP_START,
            end_at=OVERLAP_END,
        )
        payload["technician_id"] = open_order.second_technician_id

        response = api.create_work_block(payload, agent_headers)

        validate_error(response, ERR_TECHNICIAN_NOT_CERTIFIED)

    def test_rejected_frame_block_creates_no_row_and_moves_no_minutes(
        self, api, agent_headers, open_order
    ):
        """The refused FRAME block books no bench time for the named technician.

        "(21) The technician holds the required certification level, else `ERR_TECHNICIAN_NOT_CERTIFIED` (403); on assessment recording this is checked for every entry of the submitted `required_work_types`, and on work-block scheduling for the block's `work_type` when a `technician_id` is explicitly supplied."
        "(34) An explicitly named technician has no scheduled block overlapping the requested interval on half-open semantics, else `ERR_TECHNICIAN_WINDOW_CONFLICT` (409)."
        "On success the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`"

        Design: Difficulty/priority_pair_validation_conflict/certification_beats_technician_window_conflict
        """
        zip_block = _uncertified_tech_already_booked(open_order)

        payload = factories.work_block_payload(
            open_order.order_id,
            work_type="FRAME",
            start_at=OVERLAP_START,
            end_at=OVERLAP_END,
        )
        payload["technician_id"] = open_order.second_technician_id

        response = api.create_work_block(payload, agent_headers)
        validate_error(response, ERR_TECHNICIAN_NOT_CERTIFIED)

        rows, _meta = validate_paginated(
            api.list_work_blocks(
                agent_headers, technician_id=open_order.second_technician_id
            )
        )
        assert_row_ids(rows, [zip_block["id"]])

        technician = open_order.scenario.read_technician(
            open_order.second_technician_id
        )
        assert technician["scheduled_minutes_open"] == 120, technician

    def test_window_conflict_answers_on_a_lane_the_technician_is_certified_for(
        self, api, agent_headers, open_order
    ):
        """With check 21 satisfied on the ZIPPER lane, check 34 is the one that answers.

        "(21) The technician holds the required certification level, else `ERR_TECHNICIAN_NOT_CERTIFIED` (403); on assessment recording this is checked for every entry of the submitted `required_work_types`, and on work-block scheduling for the block's `work_type` when a `technician_id` is explicitly supplied."
        "(34) An explicitly named technician has no scheduled block overlapping the requested interval on half-open semantics, else `ERR_TECHNICIAN_WINDOW_CONFLICT` (409)."
        "Two blocks overlap when the existing block's `start_at` is strictly before the requested `end_at` **and** the requested `start_at` is strictly before the existing block's `end_at`."

        Design: Difficulty/priority_pair_validation_conflict/certification_beats_technician_window_conflict
        """
        _uncertified_tech_already_booked(open_order)

        payload = factories.work_block_payload(
            open_order.order_id,
            work_type="ZIPPER",
            start_at=OVERLAP_START,
            end_at=OVERLAP_END,
        )
        payload["technician_id"] = open_order.second_technician_id

        response = api.create_work_block(payload, agent_headers)

        validate_error(response, ERR_TECHNICIAN_WINDOW_CONFLICT)


class TestPartModelMismatchBeatsInsufficientUnits:
    """PRD §2.11 check 26 (lot's model) outranks check 43 (available units)."""

    def test_foreign_lot_oversubscribed_reports_part_model_mismatch(
        self, api, parts_headers, open_order
    ):
        """A three-unit draw on a one-unit lot of a foreign model reports check 26.

        "Every request runs the same ordered gauntlet, and the **first** check that fails produces the response — no later check is evaluated, so a request that violates several rules always reports the earliest one."
        "(26) The part lot belongs to the order's model, or on a substitution draw to that model's `successor_model_id`, else `ERR_PART_MODEL_MISMATCH` (422)."
        "(43) A reservation's `units` does not exceed the lot's `available_units`, else `ERR_INSUFFICIENT_PART_UNITS` (409)."
        "On an exact-code draw the lot must be stocked for the order's own model — a lot whose `gear_model_id` is anything else is refused with `ERR_PART_MODEL_MISMATCH` — and the reservation's `is_substitution` is false."

        Design: Difficulty/priority_pair_validation_conflict/part_model_mismatch_beats_insufficient_units
        """
        _pack_model, strap_lot = _foreign_model_strap_lot(open_order)

        response = api.create_parts_reservation(
            open_order.order_id,
            factories.parts_reservation_payload(strap_lot["id"], STRAP_PART_CODE, 3),
            parts_headers,
        )

        validate_error(response, ERR_PART_MODEL_MISMATCH)

    def test_rejected_draw_leaves_the_foreign_lot_and_the_order_untouched(
        self, api, parts_headers, open_order
    ):
        """The refused draw reserves nothing and mints no reservation row.

        "(26) The part lot belongs to the order's model, or on a substitution draw to that model's `successor_model_id`, else `ERR_PART_MODEL_MISMATCH` (422)."
        "(43) A reservation's `units` does not exceed the lot's `available_units`, else `ERR_INSUFFICIENT_PART_UNITS` (409)."
        "A successful reservation begins with `status` `RESERVED` and a null `settled_at`, increases the lot's `reserved_units` by `units`, recomputes the lot's `available_units`, re-derives the lot's `status`, and then re-derives `parts_support_status` on the lot's model."
        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."

        Design: Difficulty/priority_pair_validation_conflict/part_model_mismatch_beats_insufficient_units
        """
        _pack_model, strap_lot = _foreign_model_strap_lot(open_order)

        response = api.create_parts_reservation(
            open_order.order_id,
            factories.parts_reservation_payload(strap_lot["id"], STRAP_PART_CODE, 3),
            parts_headers,
        )
        validate_error(response, ERR_PART_MODEL_MISMATCH)

        lot = open_order.scenario.read_lot(strap_lot["id"])
        assert_part_lot_counts(
            lot,
            on_hand_units=1,
            reserved_units=0,
            available_units=1,
            status="LOW",
        )

        rows, meta = validate_paginated(
            api.list_parts_reservations(
                parts_headers, repair_order_id=open_order.order_id
            )
        )
        assert rows == [], rows
        assert meta["total_count"] == 0, meta

    def test_insufficient_units_answers_on_a_lot_of_the_orders_own_model(
        self, api, parts_headers, open_order
    ):
        """With check 26 satisfied by the order's own panel lot, check 43 answers.

        "(26) The part lot belongs to the order's model, or on a substitution draw to that model's `successor_model_id`, else `ERR_PART_MODEL_MISMATCH` (422)."
        "(43) A reservation's `units` does not exceed the lot's `available_units`, else `ERR_INSUFFICIENT_PART_UNITS` (409)."
        "Beyond eligibility, `units` below one is refused with `ERR_INVALID_UNITS` and `units` exceeding the lot's `available_units` is refused with `ERR_INSUFFICIENT_PART_UNITS`; a draw exactly equal to `available_units` is allowed and depletes the lot."

        Design: Difficulty/priority_pair_validation_conflict/part_model_mismatch_beats_insufficient_units
        """
        lot = open_order.scenario.read_lot(open_order.panel_lot_id)
        assert lot["available_units"] == 5, lot

        response = api.create_parts_reservation(
            open_order.order_id,
            factories.parts_reservation_payload(
                open_order.panel_lot_id, factories.PANEL_PART_CODE, 6
            ),
            parts_headers,
        )

        validate_error(response, ERR_INSUFFICIENT_PART_UNITS)
