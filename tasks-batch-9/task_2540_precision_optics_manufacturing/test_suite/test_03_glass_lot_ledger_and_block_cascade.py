"""The blank-conservation ledger, melt certification and the lot block cascade."""

from test_helpers import (
    ERR_INSUFFICIENT_BLANKS,
    HOLD_REASON_GLASS_LOT_BLOCKED,
    CANCEL_REASON_WORK_ORDER_CANCELLED,
    CANCEL_REASON_WORK_ORDER_HELD,
    QM_PRIMARY,
    assert_blank_conservation,
    assert_blank_ledger,
    assert_booked_minutes,
    assert_row_ids,
    build_block_payload,
    build_cancel_work_order_payload,
    build_certification_payload,
    build_process_run_payload,
    build_work_order_payload,
    create_certified_lot,
    create_glass_lot,
    create_instrument,
    create_released_design,
    make_procurement_officer_headers,
    make_process_technician_headers,
    make_quality_manager_headers,
    open_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

BLOCK_REASON = "STRIAE_NONCONFORMANCE_FOUND_IN_RETEST"


def _lot_with_open_run(api, element_count=2):
    """A certified lot, one work order on it, and one scheduled polishing run."""
    design = create_released_design(api, design_code="OD-2540-BLK")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    work_order = open_work_order(
        api, design["id"], lot["id"], lot["version"], element_count=element_count
    )
    instrument = create_instrument(api, instrument_code="IF-2540-1")
    run = validate_success(
        api.create_process_run(
            build_process_run_payload(work_order["id"], instrument["id"]),
            make_process_technician_headers(),
        ),
        expected_status=201,
    )
    return {
        "design": design,
        "lot": lot,
        "work_order": work_order,
        "instrument": instrument,
        "run": run,
    }


class TestGlassLotBlockCascade:
    """Blocking a melt lot is the widest cascade in the plant."""

    def test_blocking_a_lot_holds_every_open_work_order_drawing_on_it(self, api):
        """Hop one blocks the lot and hop two holds the order it feeds.

        The PRD states that hop two "takes every work order drawing on this lot
        whose fabrication state is one of `BLANKS_RESERVED`, `GRINDING`,
        `POLISHING`, `FIGURING`, `FIGURE_ACCEPTED`, `COATING` or `COATED`" and
        "sets each one's `hold_reason` to the literal string `GLASS_LOT_BLOCKED`".

        Design: Difficulty/transitive_cascade/glass_lot_block_cascade_holds_orders_cancels_runs_and_frees_instrument_minutes
        """
        ctx = _lot_with_open_run(api)

        blocked = validate_success(
            api.block_glass_lot(
                ctx["lot"]["id"],
                build_block_payload(block_reason=BLOCK_REASON),
                make_quality_manager_headers(QM_PRIMARY),
            ),
            expected_status=200,
        )

        assert blocked["lot_status"] == "BLOCKED", (
            f"lot_status must be BLOCKED, got {blocked['lot_status']}"
        )
        assert blocked["block_reason"] == BLOCK_REASON, (
            f"block_reason must be recorded, got {blocked['block_reason']}"
        )
        order = validate_success(
            api.get_work_order(
                ctx["work_order"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )
        assert order["process_status"] == "HELD", (
            f"process_status must be HELD, got {order['process_status']}"
        )
        assert order["hold_reason"] == HOLD_REASON_GLASS_LOT_BLOCKED, (
            f"hold_reason must be GLASS_LOT_BLOCKED, got {order['hold_reason']}"
        )
        assert order["compliance_status"] == "UNCLASSIFIED", (
            "the compliance dimension is untouched by a lot block, got "
            f"{order['compliance_status']}"
        )

    def test_the_block_cancels_the_open_runs_of_every_order_it_held(self, api):
        """Hop three sweeps the shop-floor calendar clear.

        The PRD states that hop three "takes each work order just held and, for
        every one of its process runs whose `run_status` is `SCHEDULED` or
        `IN_PROCESS` — again in `created_at` ascending order — sets `run_status` to
        `CANCELLED` and `cancel_reason` to the literal string `WORK_ORDER_HELD`."

        Design: Difficulty/transitive_cascade/glass_lot_block_cascade_holds_orders_cancels_runs_and_frees_instrument_minutes
        """
        ctx = _lot_with_open_run(api)

        api.block_glass_lot(
            ctx["lot"]["id"],
            build_block_payload(block_reason=BLOCK_REASON),
            make_quality_manager_headers(QM_PRIMARY),
        )

        run = validate_success(
            api.get_process_run(ctx["run"]["id"], make_process_technician_headers()),
            expected_status=200,
        )
        assert run["run_status"] == "CANCELLED", (
            f"run_status must be CANCELLED, got {run['run_status']}"
        )
        assert run["cancel_reason"] == CANCEL_REASON_WORK_ORDER_HELD, (
            f"cancel_reason must be WORK_ORDER_HELD, got {run['cancel_reason']}"
        )
        assert run["window_minutes"] == 120, (
            f"window_minutes must be 120, got {run['window_minutes']}"
        )

    def test_the_block_frees_the_instrument_minutes_and_leaves_the_ledger_alone(
        self, api
    ):
        """Hop four returns the metrology capacity the cancelled run was holding.

        The PRD states that hop four "releases the metrology capacity those
        cancelled runs were holding: for each run just cancelled, the booked-minutes
        total of its metrology instrument is decremented by that run's
        `window_minutes`".

        Design: Difficulty/transitive_cascade/glass_lot_block_cascade_holds_orders_cancels_runs_and_frees_instrument_minutes
        """
        ctx = _lot_with_open_run(api)
        before = validate_success(
            api.get_metrology_instrument(
                ctx["instrument"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )
        assert_booked_minutes(before, 120)

        api.block_glass_lot(
            ctx["lot"]["id"],
            build_block_payload(block_reason=BLOCK_REASON),
            make_quality_manager_headers(QM_PRIMARY),
        )

        after = validate_success(
            api.get_metrology_instrument(
                ctx["instrument"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )
        assert_booked_minutes(after, 0)
        lot = validate_success(
            api.get_glass_lot(ctx["lot"]["id"], make_procurement_officer_headers()),
            expected_status=200,
        )
        assert_blank_ledger(lot, reserved=3, consumed=0, scrapped=0, available=17, total=20)


class TestWorkOrderCancellationRestoresConservation:
    """Cancelling an order is a compensating cascade over the same ledger."""

    def test_cancelling_a_work_order_returns_every_reserved_blank(self, api):
        """The frozen reservation of five blanks comes back in full.

        The PRD states that hop two "returns the substrate: the lot's
        `reserved_blank_count` falls by the order's frozen reservation and the same
        number of blanks reappears in `available_blank_count`".

        Design: Difficulty/compensating_invariant/work_order_cancel_restores_glass_lot_blank_conservation
        """
        ctx = _lot_with_open_run(api, element_count=4)
        assert ctx["work_order"]["spare_blank_count"] == 1, (
            f"spare_blank_count must be 1, got {ctx['work_order']['spare_blank_count']}"
        )
        assert ctx["work_order"]["reserved_blank_count"] == 5, (
            "reserved_blank_count must be 5, got "
            f"{ctx['work_order']['reserved_blank_count']}"
        )

        cancelled = validate_success(
            api.cancel_work_order(
                ctx["work_order"]["id"],
                build_cancel_work_order_payload(
                    cancel_reason="CUSTOMER_ORDER_WITHDRAWN"
                ),
                make_process_technician_headers(),
            ),
            expected_status=200,
        )

        assert cancelled["process_status"] == "CANCELLED", (
            f"process_status must be CANCELLED, got {cancelled['process_status']}"
        )
        lot = validate_success(
            api.get_glass_lot(ctx["lot"]["id"], make_procurement_officer_headers()),
            expected_status=200,
        )
        assert_blank_ledger(lot, reserved=0, consumed=0, scrapped=0, available=20, total=20)

    def test_the_cancellation_moves_nothing_into_consumed_or_scrapped(self, api):
        """A cancelled order consumed nothing, so nothing is written off.

        The PRD states that on cancellation "nothing moves into the consumed or
        scrapped counters, because a cancelled order consumed nothing".

        Design: Difficulty/compensating_invariant/work_order_cancel_restores_glass_lot_blank_conservation
        """
        ctx = _lot_with_open_run(api, element_count=4)

        api.cancel_work_order(
            ctx["work_order"]["id"],
            build_cancel_work_order_payload(cancel_reason="CUSTOMER_ORDER_WITHDRAWN"),
            make_process_technician_headers(),
        )

        lot = validate_success(
            api.get_glass_lot(ctx["lot"]["id"], make_procurement_officer_headers()),
            expected_status=200,
        )
        assert lot["consumed_blank_count"] == 0
        assert lot["scrapped_blank_count"] == 0
        assert lot["lot_status"] == "RELEASED", (
            "a lot with every blank back in availability is not depleted, got "
            f"{lot['lot_status']}"
        )
        assert_blank_conservation(lot)

    def test_the_cancellation_cancels_the_open_run_and_frees_the_station(self, api):
        """Hop three releases the shop floor the order was holding.

        The PRD states that "every process run of this order whose `run_status` is
        `SCHEDULED` or `IN_PROCESS`, in `created_at` ascending order, is set to
        `CANCELLED` with `cancel_reason` set to the literal string
        `WORK_ORDER_CANCELLED`".

        Design: Difficulty/compensating_invariant/work_order_cancel_restores_glass_lot_blank_conservation
        """
        ctx = _lot_with_open_run(api, element_count=4)

        api.cancel_work_order(
            ctx["work_order"]["id"],
            build_cancel_work_order_payload(cancel_reason="CUSTOMER_ORDER_WITHDRAWN"),
            make_process_technician_headers(),
        )

        run = validate_success(
            api.get_process_run(ctx["run"]["id"], make_process_technician_headers()),
            expected_status=200,
        )
        instrument = validate_success(
            api.get_metrology_instrument(
                ctx["instrument"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )
        assert run["run_status"] == "CANCELLED"
        assert run["cancel_reason"] == CANCEL_REASON_WORK_ORDER_CANCELLED, (
            f"cancel_reason must be WORK_ORDER_CANCELLED, got {run['cancel_reason']}"
        )
        assert_booked_minutes(instrument, 0)


def test_certification_recomputes_the_effective_grades_from_the_measured_pair(api):
    """A quarantined lot already has effective grades; certification overrides them.

    The PRD states that "`effective_index_homogeneity_grade` is the measured
    index-homogeneity grade whenever that is non-null and otherwise falls back to
    the declared grade".

    Design: Corner/entities/certification_recomputes_the_effective_grades_from_the_measured_pair
    """
    lot = create_glass_lot(
        api,
        lot_code="GL-2540-CERT",
        declared_index_homogeneity_grade="H2",
        declared_striae_grade="A",
    )

    assert lot["lot_status"] == "QUARANTINED", (
        f"a received lot is QUARANTINED, got {lot['lot_status']}"
    )
    assert lot["measured_index_homogeneity_grade"] is None
    assert lot["measured_striae_grade"] is None
    assert lot["certificate_reference"] is None
    assert lot["effective_index_homogeneity_grade"] == "H2", (
        "the effective grade falls back to the declared grade, got "
        f"{lot['effective_index_homogeneity_grade']}"
    )
    assert lot["effective_striae_grade"] == "A"

    certified = validate_success(
        api.certify_glass_lot(
            lot["id"],
            build_certification_payload(
                measured_index_homogeneity_grade="H3",
                measured_striae_grade="B",
                certificate_reference="CERT-2540-1",
            ),
            make_procurement_officer_headers(),
        ),
        expected_status=200,
    )

    assert certified["lot_status"] == "RELEASED", (
        f"certification releases the lot, got {certified['lot_status']}"
    )
    assert certified["measured_index_homogeneity_grade"] == "H3"
    assert certified["measured_striae_grade"] == "B"
    assert certified["certificate_reference"] == "CERT-2540-1"
    assert certified["effective_index_homogeneity_grade"] == "H3", (
        "the measured grade now governs, got "
        f"{certified['effective_index_homogeneity_grade']}"
    )
    assert certified["effective_striae_grade"] == "B"
    assert certified["version"] == lot["version"] + 1, (
        f"certification increments the lot version, got {certified['version']}"
    )


def test_glass_lot_listing_pages_and_filters_over_the_same_two_rows(api):
    """One page window and two filters read the same two-row collection.

    The PRD states that "`limit` controls page size: its default is 10, its minimum
    is 1 and its maximum is 100" and that "`total_count` is the number of rows
    matching the request's filters **before** the page window is applied".

    Design: Corner/entities/glass_lot_listing_pages_and_filters_over_the_same_two_rows
    """
    released = create_certified_lot(
        api, lot_code="GL-2540-L1", glass_type="N-BK7"
    )
    quarantined = create_glass_lot(
        api, lot_code="GL-2540-L2", glass_type="S-FPL53"
    )
    headers = make_procurement_officer_headers()

    everything, meta = validate_paginated(api.list_glass_lots(headers))
    assert_row_ids(everything, [released["id"], quarantined["id"]], "the lot listing")
    assert meta["total_count"] == 2, (
        f"total_count must be 2, got {meta['total_count']}"
    )
    assert meta["limit"] == 10, f"limit must default to 10, got {meta['limit']}"
    assert meta["offset"] == 0
    assert meta["has_more"] is False

    by_type, type_meta = validate_paginated(
        api.list_glass_lots(headers, params={"glass_type": "S-FPL53"})
    )
    assert_row_ids(by_type, [quarantined["id"]], "the glass_type filtered listing")
    assert type_meta["total_count"] == 1

    by_status, status_meta = validate_paginated(
        api.list_glass_lots(headers, params={"lot_status": "RELEASED"})
    )
    assert_row_ids(by_status, [released["id"]], "the lot_status filtered listing")
    assert status_meta["total_count"] == 1

    first_page, first_meta = validate_paginated(
        api.list_glass_lots(headers, params={"limit": 1})
    )
    assert_row_ids(first_page, [released["id"]], "the first page of one row")
    assert first_meta["total_count"] == 2, (
        "total_count counts the filter match, not the page, got "
        f"{first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_glass_lots(headers, params={"limit": 1, "offset": 1})
    )
    assert_row_ids(second_page, [quarantined["id"]], "the second page of one row")
    assert second_meta["has_more"] is False


def test_exact_blank_equality_is_admissible_and_the_next_reservation_is_rejected(api):
    """A reservation may take the last blank, and the following one may not.

    The PRD states that "The reservation is admissible only when the lot's
    `available_blank_count` **before** the move is greater than or equal to that
    frozen figure; exact equality is admissible, and anything less is refused with
    `ERR_INSUFFICIENT_BLANKS`."

    Design: Corner/validations/exact_blank_equality_is_admissible_and_the_next_reservation_is_rejected
    """
    design = create_released_design(api, design_code="OD-2540-EQ")
    lot = create_certified_lot(api, lot_code="GL-2540-EQ", total_blank_count=4)

    exact = open_work_order(
        api, design["id"], lot["id"], lot["version"], element_count=3
    )
    assert exact["reserved_blank_count"] == 4, (
        f"reserved_blank_count must be 4, got {exact['reserved_blank_count']}"
    )
    drained = validate_success(
        api.get_glass_lot(lot["id"], make_procurement_officer_headers()),
        expected_status=200,
    )
    assert_blank_ledger(drained, reserved=4, consumed=0, scrapped=0, available=0, total=4)
    assert drained["lot_status"] == "RELEASED", (
        "a lot with blanks still out on reservation is not depleted, got "
        f"{drained['lot_status']}"
    )
    assert drained["version"] == 3, (
        f"lot version must be 3 after receipt, certification and one reservation, "
        f"got {drained['version']}"
    )

    refused = api.create_work_order(
        build_work_order_payload(
            design["id"], lot["id"], drained["version"], element_count=1
        ),
        make_process_technician_headers(),
    )

    validate_error(refused, ERR_INSUFFICIENT_BLANKS)
    unchanged = validate_success(
        api.get_glass_lot(lot["id"], make_procurement_officer_headers()),
        expected_status=200,
    )
    assert_blank_ledger(
        unchanged, reserved=4, consumed=0, scrapped=0, available=0, total=4
    )
    assert unchanged["version"] == 3, (
        f"a refused reservation may not bump the lot version, got {unchanged['version']}"
    )


def test_the_blank_ledger_is_already_correct_in_the_response_that_changed_it(api):
    """No settling step separates the reservation from its observable effect.

    The PRD states that "by the time a response is emitted, every downstream row the
    cascade reaches is already in its final state, and a subsequent read of that row
    observes the propagated value".

    Design: Corner/consistency_model/the_blank_ledger_is_already_correct_in_the_response_that_changed_it
    """
    design = create_released_design(api, design_code="OD-2540-CON")
    lot = create_certified_lot(api, lot_code="GL-2540-4", total_blank_count=4)

    order = open_work_order(
        api, design["id"], lot["id"], lot["version"], element_count=3
    )

    assert order["spare_blank_count"] == 1, (
        f"spare_blank_count must be 1, got {order['spare_blank_count']}"
    )
    assert order["reserved_blank_count"] == 4, (
        "the create response itself carries the frozen reservation, got "
        f"{order['reserved_blank_count']}"
    )
    immediate = validate_success(
        api.get_glass_lot(lot["id"], make_procurement_officer_headers()),
        expected_status=200,
    )
    assert_blank_ledger(immediate, reserved=4, consumed=0, scrapped=0, available=0, total=4)
    repeat = validate_success(
        api.get_glass_lot(lot["id"], make_procurement_officer_headers()),
        expected_status=200,
    )
    assert_blank_ledger(repeat, reserved=4, consumed=0, scrapped=0, available=0, total=4)
    assert repeat["lot_status"] == "RELEASED"
