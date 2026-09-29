"""The quality verdict, the four-hop fulfilment chain and the feedback loop."""

from test_helpers import (
    MEASUREMENTS_AT_CPK_MIN,
    MEASUREMENTS_BELOW_CPK_MIN,
    MEASUREMENTS_SHIFTED_HIGH,
    ApiErrorId,
    api_client,
    complete_machining,
    make_inspector_headers,
    make_quality_manager_headers,
    post_subgroup,
    read_blanket_po,
    read_machine,
    read_part,
    read_quote,
    read_release,
    read_work_order,
    setup_accepted_work_order,
    setup_machining_complete_work_order,
    setup_running_work_order,
    validate_error,
    validate_success,
)

QUALITY = make_quality_manager_headers()


def _disposition(work_order_id, decision, note="recorded by quality"):
    return api_client.disposition_work_order(
        work_order_id, {"decision": decision, "note": note}, QUALITY
    )


class TestParallelDimensions:
    """The production and quality dimensions advance without consulting each other."""

    def test_marginal_subgroup_holds_quality_while_machining_closes_independently(self):
        """PRD 2.8: "Completing machining leaves `quality_status` exactly as it
        was, and a quality transition leaves `machining_status` exactly as it was."
        PRD 3.8: "A subgroup dispositioned `MARGINAL` or `REJECT` moves the work
        order `PENDING_INSPECTION → QUALITY_HOLD` if it was pending, or `IN_SPC →
        QUALITY_HOLD` if a study was already open."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_machining_and_quality_dimensions
        """
        shop = setup_running_work_order()

        marginal = post_subgroup(
            shop.work_order_id,
            shop.characteristic_id,
            shop.gauge_id,
            shop.inspector_id,
            piece_index=200,
            measurements=list(MEASUREMENTS_BELOW_CPK_MIN),
        )
        assert marginal["cpk_short_term"] == 1.292
        assert marginal["disposition"] == "MARGINAL"
        assert marginal["out_of_spec_count"] == 0

        held = read_work_order(shop.work_order_id)
        assert held["quality_status"] == "QUALITY_HOLD"
        assert held["machining_status"] == "RUNNING"

        completed = complete_machining(
            shop.work_order_id,
            shop.machinist_id,
            qty_good=200,
            qty_scrap=0,
            actual_run_seconds=9300,
        )
        assert completed["machining_status"] == "MACHINING_COMPLETE"
        assert completed["quality_status"] == "QUALITY_HOLD"

    def test_release_hold_returns_quality_to_in_spc_without_touching_machining(self):
        """PRD 3.9: "`RELEASE_HOLD` is the lightest of the three and is declared
        only from `QUALITY_HOLD`, moving the work order `QUALITY_HOLD → IN_SPC`.
        The note is recorded on the work order and no sibling entity changes at all
        — this is the return edge that makes the quality dimension cyclic, and it is
        how a job that tripped a marginal subgroup gets a second chance once the
        process has been re-centred."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_machining_and_quality_dimensions
        """
        shop = setup_running_work_order()
        post_subgroup(
            shop.work_order_id,
            shop.characteristic_id,
            shop.gauge_id,
            shop.inspector_id,
            piece_index=200,
            measurements=list(MEASUREMENTS_BELOW_CPK_MIN),
        )
        complete_machining(
            shop.work_order_id,
            shop.machinist_id,
            qty_good=200,
            qty_scrap=0,
            actual_run_seconds=9300,
        )

        released = validate_success(
            _disposition(shop.work_order_id, "RELEASE_HOLD", "deviation reviewed and closed"), 200
        )
        assert released["quality_status"] == "IN_SPC"
        assert released["machining_status"] == "MACHINING_COMPLETE"
        assert released["qty_good"] == 200

        assert read_machine(shop.machine_id)["status"] == "AVAILABLE"
        assert read_release(shop.release_id)["status"] == "IN_PRODUCTION"


class TestFulfilmentChain:
    """Accept fulfils the release, recomputes the order and consumes the quote."""

    def test_accept_fulfils_the_release_and_recomputes_the_order_ledger(self):
        """PRD 3.9: "**Hop one**: the work order's kanban release has its
        `fulfilled_qty` set to the work order's `qty_good` and moves `IN_PRODUCTION
        → FULFILLED`."
        PRD 3.9: "**Hop two**, caused by that release reaching `FULFILLED`: on the
        release's blanket order, the release's `qty` is subtracted from
        `open_released_qty`, the work order's `qty_good` is added to the order's
        `fulfilled_qty`, the shortfall — the release quantity minus the good pieces
        — is added back to `remaining_qty`, and the order's `version` is incremented
        by one."

        Design: Difficulty/transitive_cascade/disposition_accept_to_release_to_blanket_po_to_quote
        """
        shop = setup_machining_complete_work_order()

        accepted = validate_success(
            _disposition(shop.work_order_id, "ACCEPT", "lot accepted"), 200
        )
        assert accepted["quality_status"] == "ACCEPTED"

        release = read_release(shop.release_id)
        assert release["status"] == "FULFILLED"
        assert release["fulfilled_qty"] == 200

        po = read_blanket_po(shop.po_id)
        assert po["open_released_qty"] == 0
        assert po["fulfilled_qty"] == 200
        assert po["remaining_qty"] == 0

    def test_exhausted_order_consumes_the_quote_and_fills_the_observed_figures(self):
        """PRD 3.9: "**Hop three**, caused by that recomputation landing on both
        `remaining_qty` and `open_released_qty` at exactly 0: the blanket order moves
        `ACTIVE → EXHAUSTED`. **Hop four**, caused by the order reaching
        `EXHAUSTED`: the quote behind that order moves `ACCEPTED → CONSUMED`, and no
        further blanket order may ever be created from it."
        PRD 3.9: "The part's observed running figures are recomputed from every
        work order for that part whose `quality_status` is `ACCEPTED`."

        Design: Difficulty/transitive_cascade/disposition_accept_to_release_to_blanket_po_to_quote
        """
        shop = setup_machining_complete_work_order()
        validate_success(_disposition(shop.work_order_id, "ACCEPT", "lot accepted"), 200)

        assert read_blanket_po(shop.po_id)["status"] == "EXHAUSTED"
        assert read_quote(shop.quote_id)["status"] == "CONSUMED"

        part = read_part(shop.part_id)
        assert part["observed_avg_cycle_time_sec"] == 46.5
        assert part["observed_accepted_qty"] == 200


class TestQualitySummaryEmptyCollection:
    """A work order with no subgroups still answers the computed read."""

    def test_summary_with_no_subgroups_reports_zero_and_required_counts(self):
        """PRD 3.8: "For each characteristic of the work order's part, the
        required number of subgroups is the work order's `qty_ordered` divided by
        that characteristic's `sample_freq_pieces`, rounded **up** to a whole
        subgroup."
        PRD 3.8: "the `sample_count` of subgroups actually posted, the
        `required_sample_count` obtained by summing the per-characteristic
        requirements"

        Design: Difficulty/boundary_precision_check/quality_summary_with_zero_samples_returns_nulls
        """
        shop = setup_running_work_order(
            characteristic_overrides={"sample_freq_pieces": 100}
        )

        summary = validate_success(
            api_client.get_quality_summary(
                shop.work_order_id, make_inspector_headers(shop.inspector_id)
            ),
            200,
        )
        assert summary["sample_count"] == 0
        assert summary["required_sample_count"] == 2
        assert summary["characteristic_count"] == 1
        assert summary["out_of_spec_count"] == 0

    def test_summary_with_no_subgroups_reports_null_capability_indices(self):
        """PRD 3.8: "`cpk_short_term_min` — the smallest short-term index among
        those subgroups, or null when no subgroup exists — and `ppk_long_term_min`,
        the smallest long-term index across the characteristics that have at least
        two subgroups, or null when no characteristic has two or more."
        PRD 3.8: "It is undefined — reported as null — whenever fewer than two
        readings have been pooled."

        Design: Difficulty/boundary_precision_check/quality_summary_with_zero_samples_returns_nulls
        """
        shop = setup_running_work_order(
            characteristic_overrides={"sample_freq_pieces": 100}
        )

        summary = validate_success(
            api_client.get_quality_summary(
                shop.work_order_id, make_inspector_headers(shop.inspector_id)
            ),
            200,
        )
        assert summary["cpk_short_term_min"] is None
        assert summary["ppk_long_term_min"] is None
        assert read_work_order(shop.work_order_id)["quality_status"] == "PENDING_INSPECTION"


def test_a_second_disposition_on_an_accepted_job_is_refused():
    """PRD 3.9: "`REJECT` is declared from `IN_SPC` and from `QUALITY_HOLD`, and
    in both cases requires that `machining_status` is already
    `MACHINING_COMPLETE`."
    PRD 2.9: "After those comes the generic state check: the target resource must
    be in a state from which the requested transition is declared, otherwise
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/accepted_work_order_rejects_a_second_disposition
    """
    shop = setup_accepted_work_order()

    response = _disposition(shop.work_order_id, "REJECT", "late scrap found")
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert read_work_order(shop.work_order_id)["quality_status"] == "ACCEPTED"
    assert read_release(shop.release_id)["status"] == "FULFILLED"

    po = read_blanket_po(shop.po_id)
    assert po["status"] == "EXHAUSTED"
    assert po["fulfilled_qty"] == 200


def test_reject_short_closes_the_release_and_returns_the_whole_quantity():
    """PRD 3.9: "It sets `quality_status` to `REJECTED` and moves the work order's
    kanban release `IN_PRODUCTION → SHORT_CLOSED` with `close_reason` recorded as
    `WORK_ORDER_REJECTED` and `fulfilled_qty` left at 0."
    PRD 3.9: "On the release's blanket order, the release's `qty` is subtracted
    from `open_released_qty` and the same quantity is added back to `remaining_qty`
    — the whole release returns to the pool, none of it is credited as fulfilled —
    and the order's `version` is incremented by one."

    Design: Corner/state_machines/reject_disposition_short_closes_release_and_returns_quantity
    """
    shop = setup_machining_complete_work_order()

    rejected = validate_success(
        _disposition(shop.work_order_id, "REJECT", "dimensional escape found at final audit"),
        200,
    )
    assert rejected["quality_status"] == "REJECTED"

    release = read_release(shop.release_id)
    assert release["status"] == "SHORT_CLOSED"
    assert release["fulfilled_qty"] == 0
    assert release["close_reason"] == "WORK_ORDER_REJECTED"

    po = read_blanket_po(shop.po_id)
    assert po["remaining_qty"] == 200
    assert po["open_released_qty"] == 0
    assert po["fulfilled_qty"] == 0
    assert po["status"] == "ACTIVE"
    assert read_quote(shop.quote_id)["status"] == "ACCEPTED"


def test_rejected_jobs_are_excluded_from_the_observed_running_figures():
    """PRD 3.9: "Jobs in `PENDING_INSPECTION`, `IN_SPC`, `QUALITY_HOLD` or
    `REJECTED` are excluded from both figures even when their `machining_status` is
    `MACHINING_COMPLETE` — which is exactly why a rejected disposition does **not**
    recompute them."
    PRD 3.9: "When that sum is zero, `observed_avg_cycle_time_sec` is set to
    null"

    Design: Corner/calculations/observed_cycle_time_excludes_rejected_work_orders
    """
    shop = setup_machining_complete_work_order()

    validate_success(_disposition(shop.work_order_id, "REJECT", "dimensional escape"), 200)

    work_order = read_work_order(shop.work_order_id)
    assert work_order["quality_status"] == "REJECTED"
    assert work_order["machining_status"] == "MACHINING_COMPLETE"

    part = read_part(shop.part_id)
    assert part["observed_avg_cycle_time_sec"] is None
    assert part["observed_accepted_qty"] == 0


def test_accept_before_the_required_subgroup_count_is_refused():
    """PRD 3.9: "every characteristic of the work order's part must have reached
    its required subgroup count as computed in §3.8, failing which the request is
    rejected with `ERR_SPC_SAMPLING_INCOMPLETE` (HTTP 409)"
    PRD 3.8: "The ceiling is applied per characteristic before anything is summed,
    never to a summed ratio."

    Design: Corner/errors/accept_before_the_required_subgroup_count_is_rejected
    """
    shop = setup_running_work_order(characteristic_overrides={"sample_freq_pieces": 100})
    post_subgroup(
        shop.work_order_id,
        shop.characteristic_id,
        shop.gauge_id,
        shop.inspector_id,
        piece_index=100,
        measurements=list(MEASUREMENTS_AT_CPK_MIN),
    )
    complete_machining(
        shop.work_order_id, shop.machinist_id, qty_good=200, qty_scrap=0, actual_run_seconds=9300
    )

    response = _disposition(shop.work_order_id, "ACCEPT", "looks fine")
    validate_error(response, ApiErrorId.ERR_SPC_SAMPLING_INCOMPLETE.value)

    assert read_work_order(shop.work_order_id)["quality_status"] == "IN_SPC"
    assert read_release(shop.release_id)["status"] == "IN_PRODUCTION"
    assert read_blanket_po(shop.po_id)["fulfilled_qty"] == 0


def test_accept_below_the_long_term_capability_floor_is_refused():
    """PRD 3.9: "and the long-term capability index of every characteristic with
    at least two pooled subgroups must be greater than or equal to 1.00, failing
    which the request is rejected with `ERR_CAPABILITY_BELOW_MINIMUM` (HTTP 409)."
    PRD 3.9: "Note the asymmetry between the two capability thresholds: a single
    subgroup is judged against the characteristic's own `cpk_min`, defaulting to
    1.33, while the acceptance gate is judged against a long-term floor of 1.00
    across pooled readings."

    Design: Corner/errors/accept_below_long_term_capability_minimum_is_rejected
    """
    shop = setup_running_work_order(
        characteristic_overrides={"sample_freq_pieces": 100, "cpk_min": 1.33}
    )
    post_subgroup(
        shop.work_order_id,
        shop.characteristic_id,
        shop.gauge_id,
        shop.inspector_id,
        piece_index=100,
        measurements=list(MEASUREMENTS_AT_CPK_MIN),
    )
    post_subgroup(
        shop.work_order_id,
        shop.characteristic_id,
        shop.gauge_id,
        shop.inspector_id,
        piece_index=200,
        measurements=list(MEASUREMENTS_SHIFTED_HIGH),
    )
    complete_machining(
        shop.work_order_id, shop.machinist_id, qty_good=200, qty_scrap=0, actual_run_seconds=9300
    )

    summary = validate_success(
        api_client.get_quality_summary(shop.work_order_id, QUALITY), 200
    )
    assert summary["cpk_short_term_min"] == 1.357
    assert summary["ppk_long_term_min"] == 0.529

    response = _disposition(shop.work_order_id, "ACCEPT", "statistically fine")
    validate_error(response, ApiErrorId.ERR_CAPABILITY_BELOW_MINIMUM.value)

    assert read_work_order(shop.work_order_id)["quality_status"] == "IN_SPC"
    assert read_blanket_po(shop.po_id)["status"] == "ACTIVE"


def test_the_whole_cascade_is_visible_the_moment_the_verdict_returns():
    """PRD 3.9: "An accepted disposition sets `quality_status` to `ACCEPTED` and
    fires a four-hop fulfilment chain that every implementation must apply in full."
    PRD 2.8: "The response body of any of these operations is the primary resource
    named in the URL path, not the cascade's collateral; clients observe the
    collateral by re-reading it."

    Design: Corner/consistency_model/cascade_results_are_visible_in_the_triggering_response
    """
    shop = setup_machining_complete_work_order()

    response = validate_success(
        _disposition(shop.work_order_id, "ACCEPT", "lot accepted"), 200
    )
    assert response["quality_status"] == "ACCEPTED"

    po = read_blanket_po(shop.po_id)
    assert po["status"] == "EXHAUSTED"
    assert po["fulfilled_qty"] == 200
    assert po["remaining_qty"] == 0
    assert read_quote(shop.quote_id)["status"] == "CONSUMED"
