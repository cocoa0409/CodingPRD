"""Thresholds, constants and precision in the derived-value layer.

The six-line bill, the two reliability variants, the proof ladder and the slot
count are all pure functions of declared inputs, so each one is pinned here on
the exact input where a plausible mis-reading would show up as a different
number: an inclusive boundary, an hour boundary, a capped unit count, a repeating
quotient, and a tie that must fall to a timestamp.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    OPS_USER_A,
    Scenario,
    Z1_STANDARD_LINES,
    Z1_STANDARD_SUBTOTAL_CENTS,
    active_allocation,
    adjudicate,
    advance_to_assigned,
    advance_to_out_for_delivery,
    advance_to_picked_up,
    allocations_for,
    assert_courier_counters,
    assert_cost_share_pct,
    assert_fee_lines,
    assert_grant_ledger,
    assert_instant,
    assert_payer_mix,
    assert_reliability_scores,
    assert_window_occupancy,
    attempts_for,
    build_courier,
    build_network,
    build_queued_delivery,
    build_ready_order,
    build_window,
    factories,
    find_by,
    latest_case,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    record_attempt,
    redepart,
    reserve_delivery,
    set_clock,
    start_review,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}
LONG_WINDOW = {"window_end": utc_ts(3, 22), "capacity_slots": 1}

# Zone Z1 priced for a standard bag, plus the one line each case adds.
AFTER_HOURS_LINES = [705, 861, 0, 0, 305, 0]
THREE_RUN_LINES = [705, 861, 0, 0, 0, 800]


@pytest.fixture
def two_bags_across_the_signature_threshold(api):
    """A 25000-cent bag at the door and a 24999-cent bag still queued behind it."""
    net = build_network(api)
    at_threshold = build_ready_order(api, net, **{**STANDARD_ORDER, "total_rx_value_cents": 25000})
    below = build_ready_order(api, net, **{**STANDARD_ORDER, "total_rx_value_cents": 24999})
    window = build_window(api, net.zone["id"], window_end=utc_ts(3, 22), capacity_slots=2)
    first = reserve_delivery(api, net, at_threshold["id"], window["id"])
    second = reserve_delivery(api, net, below["id"], window["id"])
    courier = build_courier(api)

    scn_a = Scenario(net=net, order=at_threshold, window=window, delivery=first)
    scn_b = Scenario(net=net, order=below, window=window, delivery=second)
    advance_to_assigned(api, scn_a, courier=courier)
    advance_to_picked_up(api, scn_a)
    advance_to_out_for_delivery(api, scn_a, depart_clock=utc_ts(3, 14))
    return scn_a, scn_b, courier


class TestSignatureThresholdIsInclusive:
    """"`signature_required` is true when the bag is cold, or controlled, or its
    `total_rx_value_cents` is at least 25000 cents — that is, at least 250
    dollars, with a bag valued at exactly 250 dollars already requiring a
    signature."
    """

    def test_a_bag_worth_exactly_the_threshold_needs_a_signature_at_the_door(
        self, api, two_bags_across_the_signature_threshold
    ):
        """The value rule is enforced twice: at intake and again at handover.

        "If the delivery's `signature_required` is true, `signature_captured` must
        be true — a missing signature is `ERR_SIGNATURE_REQUIRED`"

        Design: Corner/calculations/signature_threshold_is_enforced_at_attempt_time_from_25000_cents
        """
        scn_a, _scn_b, _courier = two_bags_across_the_signature_threshold
        assert scn_a.order["signature_required"] is True
        assert scn_a.delivery["required_id_verification"] == "PHOTO_ID"

        unsigned = api.record_attempt(
            scn_a.delivery["id"],
            factories.attempt_payload(
                "DELIVERED",
                id_verification_method="PHOTO_ID",
                signature_captured=False,
                recipient_relationship="SELF",
            ),
            headers=scn_a.courier_headers,
        )
        validate_error(unsigned, "ERR_SIGNATURE_REQUIRED", 409)
        assert attempts_for(api, scn_a.delivery["id"]) == []

        signed = validate_success(
            api.record_attempt(
                scn_a.delivery["id"],
                factories.attempt_payload(
                    "DELIVERED",
                    id_verification_method="PHOTO_ID",
                    signature_captured=True,
                    recipient_relationship="SELF",
                ),
                headers=scn_a.courier_headers,
            ),
            201,
        )
        assert signed["outcome"] == "DELIVERED"
        assert read_delivery(api, scn_a.delivery["id"])["custody_status"] == "DELIVERED"

    def test_one_cent_below_the_threshold_closes_on_a_date_of_birth_check(
        self, api, two_bags_across_the_signature_threshold
    ):
        """24999 cents falls through the whole cascade to its default rung.

        "and everything else, cold bags included, settles at `DOB_MATCH`, which is
        checked against the patient's `date_of_birth` at the door"

        Design: Corner/calculations/signature_threshold_is_enforced_at_attempt_time_from_25000_cents
        """
        scn_a, scn_b, courier = two_bags_across_the_signature_threshold
        record_attempt(
            api,
            scn_a,
            "DELIVERED",
            id_verification_method="PHOTO_ID",
            signature_captured=True,
            recipient_relationship="SELF",
        )

        assert scn_b.order["signature_required"] is False
        assert scn_b.delivery["required_id_verification"] == "DOB_MATCH"

        advance_to_assigned(
            api, scn_b, courier=courier, explicit=False, dispatch_clock=utc_ts(3, 14, 5)
        )
        advance_to_picked_up(api, scn_b)
        advance_to_out_for_delivery(api, scn_b, depart_clock=None)
        attempt = record_attempt(
            api, scn_b, "DELIVERED", id_verification_method="DOB_MATCH"
        )
        assert attempt["outcome"] == "DELIVERED"
        assert attempt["signature_captured"] is False

        assert_courier_counters(
            read_courier(api, courier["id"]), attempt_total_count=2, delivered_count=2
        )
        assert_reliability_scores(read_courier(api, courier["id"]), rolling=100.00)


@pytest.fixture
def two_windows_across_the_after_hours_boundary(api):
    """Two identical standard bags, one on a 19:00Z window and one on a 20:00Z one."""
    net = build_network(api)
    early_order = build_ready_order(api, net, **STANDARD_ORDER)
    late_order = build_ready_order(api, net, **STANDARD_ORDER)
    early_window = build_window(
        api,
        net.zone["id"],
        window_start=utc_ts(3, 19),
        window_end=utc_ts(3, 19, 45),
        capacity_slots=1,
    )
    late_window = build_window(
        api,
        net.zone["id"],
        window_start=utc_ts(3, 20),
        window_end=utc_ts(3, 22),
        capacity_slots=1,
    )
    early = reserve_delivery(api, net, early_order["id"], early_window["id"])
    late = reserve_delivery(api, net, late_order["id"], late_window["id"])
    return net, early, late


class TestAfterHoursLineKeyedToWindowStart:
    """"`after_hours_line_cents` is the zone's `after_hours_fee_cents` when the
    window's `window_start` falls at or after 20:00 UTC or before 06:00 UTC, and 0
    otherwise."
    """

    def test_only_the_window_starting_at_twenty_hundred_carries_the_fifth_line(
        self, api, two_windows_across_the_after_hours_boundary
    ):
        """A 19:00Z start is inside hours even though the run itself is late.

        "Pricing produces an ordered vector of six line items, never a pre-summed
        total, because every downstream money rule consumes the vector rather than
        the sum."

        Design: Corner/calculations/after_hours_line_is_keyed_to_the_window_start_hour_boundary
        """
        _net, early, late = two_windows_across_the_after_hours_boundary
        early_bill = active_allocation(api, early["id"])
        assert_fee_lines(early_bill, Z1_STANDARD_LINES)
        assert early_bill["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS
        assert early_bill["patient_gross_share_cents"] == 157

        late_bill = active_allocation(api, late["id"])
        assert_fee_lines(late_bill, AFTER_HOURS_LINES)
        assert late_bill["fee_subtotal_cents"] == 1871
        assert late_bill["patient_gross_share_cents"] == 188
        assert_cost_share_pct(late_bill, 0.10)

    def test_the_member_share_moves_by_the_rounded_new_line_alone(
        self, api, two_windows_across_the_after_hours_boundary
    ):
        """31 cents, not 30.5, and the pharmacy still swallows both residues.

        "multiply each line by the applicable cost-share fraction, round each
        product half up to a whole cent, and only then add the six rounded results
        together to obtain `patient_gross_share_cents`"

        Design: Corner/calculations/after_hours_line_is_keyed_to_the_window_start_hour_boundary
        """
        net, early, late = two_windows_across_the_after_hours_boundary
        early_bill = active_allocation(api, early["id"])
        late_bill = active_allocation(api, late["id"])
        assert late_bill["patient_gross_share_cents"] - early_bill[
            "patient_gross_share_cents"
        ] == 31

        assert_payer_mix(
            early_bill,
            plan_grant_cents=150,
            patient_payable_cents=0,
            pharmacy_payable_cents=1416,
        )
        assert_payer_mix(
            late_bill,
            plan_grant_cents=150,
            patient_payable_cents=0,
            pharmacy_payable_cents=1721,
        )

        assert_grant_ledger(
            read_grant(api, net.grant["id"]),
            committed_cents=300,
            consumed_cents=0,
            remaining_cents=99_700,
        )


@pytest.fixture
def all_four_handling_combinations(api):
    """One cold-certified CII-licensed site releasing one bag of each kind."""
    net = build_network(api)
    plain = build_ready_order(api, net, **STANDARD_ORDER)
    cold = build_ready_order(api, net, **{**STANDARD_ORDER, "cold_chain_required": True})
    controlled = build_ready_order(api, net, **{**STANDARD_ORDER, "controlled_schedule": "CIII"})
    both = build_ready_order(
        api,
        net,
        **{**STANDARD_ORDER, "cold_chain_required": True, "controlled_schedule": "CII"},
    )
    return net, plain, cold, controlled, both


class TestHandlingClassMatrix:
    """"The `handling_class` is `COLD_CHAIN_CONTROLLED` when the bag is both cold
    and controlled, `COLD_CHAIN` when it is only cold, `CONTROLLED` when it is
    only controlled, and `STANDARD` otherwise."
    """

    def test_each_cell_of_the_cold_by_controlled_matrix_names_its_own_class(
        self, api, all_four_handling_combinations
    ):
        """Four inputs, four classes, and no two of them share a proof profile.

        "`required_id_verification` is selected by a strictly ordered cascade: a
        `CII` schedule demands `GOVT_ID_SCAN`; failing that, a `CIII` schedule
        demands `PHOTO_ID`; failing that, a `total_rx_value_cents` of at least
        25000 demands `PHOTO_ID`"

        Design: Corner/calculations/handling_class_matrix_covers_all_four_cold_controlled_combinations
        """
        _net, plain, cold, controlled, both = all_four_handling_combinations

        # `handling_class` is snapshotted onto the Delivery at reservation time,
        # so an order row carries only the two derived proof fields.
        assert plain["signature_required"] is False
        assert plain["required_id_verification"] == "DOB_MATCH"

        assert cold["signature_required"] is True
        assert cold["required_id_verification"] == "DOB_MATCH"

        assert controlled["signature_required"] is True
        assert controlled["required_id_verification"] == "PHOTO_ID"

        assert both["signature_required"] is True
        assert both["required_id_verification"] == "GOVT_ID_SCAN"

    def test_all_four_bags_clear_the_release_gate_at_this_site(
        self, api, all_four_handling_combinations
    ):
        """The licence tier and the cold certification cover every cell.

        "`controlled_license_tier` `NONE` covers only a `NONE` schedule, `CIII_V`
        covers `NONE` and `CIII`, and `CII_V` covers `NONE`, `CIII`, and `CII`,
        while a cold bag additionally requires `cold_chain_certified` to be true."

        Design: Corner/calculations/handling_class_matrix_covers_all_four_cold_controlled_combinations
        """
        net, plain, cold, controlled, both = all_four_handling_combinations
        for order in (plain, cold, controlled, both):
            assert order["status"] == "READY"

        rows, meta = validate_paginated(
            api.list_pharmacy_orders(
                net.pharmacy_headers, pharmacy_id=net.pharmacy["id"], status="READY"
            )
        )
        assert meta["total_count"] == 4
        assert len(rows) == 4


@pytest.fixture
def one_failure_then_one_success(api):
    """Ray Ortiz misses at 14:00Z and delivers at 15:00Z; Ida Nunez never works."""
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW)
    working = build_courier(api)
    idle = build_courier(api, display_name="Ida Nunez")
    advance_to_assigned(api, scn, courier=working)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=utc_ts(3, 14))
    first = record_attempt(api, scn, "NO_ANSWER")
    redepart(api, scn, utc_ts(3, 15))
    second = record_attempt(
        api, scn, "DELIVERED", id_verification_method="DOB_MATCH", recipient_relationship="SELF"
    )
    return scn, working, idle, first, second


class TestRollingScoreRoundsHalfUp:
    """"Multiply each attempt's `reliability_credit` by its weight, sum those
    products, divide by the sum of the weights used, multiply by 100, and round
    half up to two decimals."
    """

    def test_the_repeating_quotient_lands_on_two_decimals(
        self, api, one_failure_then_one_success
    ):
        """100 * 1.4 / 1.8 is 77.777…, and the stored figure is 77.78.

        "both read a `reliability_credit` of 1.0 for a `DELIVERED` outcome, 0.5
        for `NO_ANSWER`, `REFUSED`, `ADDRESS_INVALID`, or `ID_MISMATCH`, and 0.0
        for `COLD_BREACH`"

        Design: Corner/calculations/rolling_score_rounds_half_up_to_two_decimals_on_a_repeating_quotient
        """
        _scn, working, _idle, first, second = one_failure_then_one_success
        assert first["reliability_credit"] == pytest.approx(0.5, abs=0.01)
        assert second["reliability_credit"] == pytest.approx(1.0, abs=0.01)

        courier = read_courier(api, working["id"])
        assert_reliability_scores(courier, rolling=77.78, lifetime=50.00)
        assert_courier_counters(courier, attempt_total_count=2, delivered_count=1)

    def test_the_two_variants_disagree_and_neither_suspends_this_early(
        self, api, one_failure_then_one_success
    ):
        """A courier with no history takes the declared branch, not an empty average.

        "The minimum-attempts gate matters: a courier two attempts into a
        disastrous career is not suspended even at a lifetime score of 0.00."

        Design: Corner/calculations/rolling_score_rounds_half_up_to_two_decimals_on_a_repeating_quotient
        """
        _scn, working, idle, _first, _second = one_failure_then_one_success
        assert read_courier(api, working["id"])["status"] == "AVAILABLE"

        untouched = read_courier(api, idle["id"])
        assert_reliability_scores(untouched, rolling=100.00, lifetime=100.00)
        assert_courier_counters(
            untouched, attempt_total_count=0, delivered_count=0, status="AVAILABLE"
        )


@pytest.fixture
def a_denied_case_on_a_three_run_bag(api):
    """Three failed runs, the bag back on the shelf, and the case adjudicated DENY."""
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW)
    advance_to_assigned(api, scn)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=utc_ts(3, 14))
    record_attempt(api, scn, "NO_ANSWER")
    redepart(api, scn, utc_ts(3, 15))
    record_attempt(api, scn, "REFUSED")
    redepart(api, scn, utc_ts(3, 18))
    record_attempt(api, scn, "NO_ANSWER")
    scn.case = latest_case(api, scn.delivery["id"])
    return scn


class TestReattemptSurchargeCapsAtTwoUnits:
    """"`reattempt_line_cents` is 400 cents for each billable attempt beyond the
    first, counting no fewer than zero such units and no more than two"
    """

    def test_denial_leaves_the_bill_provisional_and_billable(
        self, api, a_denied_case_on_a_three_run_bag
    ):
        """The physical answer is RETURNED; the money question is still open.

        "The case moves `UNDER_REVIEW → DENIED` and `credit_cents` is set to 0."

        Design: Corner/calculations/reattempt_surcharge_caps_at_two_units_in_the_final_variant
        """
        scn = a_denied_case_on_a_three_run_bag
        before_return = read_delivery(api, scn.delivery["id"])
        assert before_return["attempt_count"] == 3
        assert before_return["custody_status"] == "RETURN_PENDING"

        returned = validate_success(
            api.confirm_return(scn.delivery["id"], headers=scn.pharmacy_headers)
        )
        assert returned["custody_status"] == "RETURNED"

        start_review(api, scn.case["id"])
        decided = adjudicate(
            api, scn.case["id"], "DENY", read_delivery(api, scn.delivery["id"])["version"]
        )
        assert decided["disposition"] == "DENY"
        assert decided["credit_cents"] == 0
        assert decided["adjudicated_by_ops_user_id"] == OPS_USER_A
        assert read_delivery(api, scn.delivery["id"])["settlement_status"] == "PROVISIONAL"

    def test_the_final_bill_charges_two_surcharge_units_for_three_runs(
        self, api, a_denied_case_on_a_three_run_bag
    ):
        """min(max(3 - 1, 0), 2) is 2, so the sixth line is 800 and not 1200.

        "On a final bill, *billable attempts* is no longer pinned to 1: it becomes
        the delivery's `attempt_count`, or 1 if no run was ever recorded."

        Design: Corner/calculations/reattempt_surcharge_caps_at_two_units_in_the_final_variant
        """
        scn = a_denied_case_on_a_three_run_bag
        validate_success(api.confirm_return(scn.delivery["id"], headers=scn.pharmacy_headers))
        start_review(api, scn.case["id"])
        adjudicate(
            api, scn.case["id"], "DENY", read_delivery(api, scn.delivery["id"])["version"]
        )
        validate_success(api.close_exception_case(scn.case["id"], headers=OPS_HEADERS))

        settled = validate_success(
            api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS)
        )
        assert settled["settlement_status"] == "FINALIZED"
        assert settled["fee_subtotal_cents"] == 2366

        final = find_by(allocations_for(api, scn.delivery["id"]), variant="FINAL")
        assert_fee_lines(final, THREE_RUN_LINES)
        assert_payer_mix(
            final,
            patient_gross_share_cents=237,
            plan_grant_cents=150,
            absorption_tier_cents=50,
            pharmacy_absorption_cents=50,
            patient_payable_cents=37,
            pharmacy_payable_cents=2179,
        )

        assert_grant_ledger(
            read_grant(api, scn.net.grant["id"]), committed_cents=0, consumed_cents=150
        )
        assert read_order(api, scn.order["id"])["status"] == "RETURNED_TO_STOCK"


@pytest.fixture
def a_single_slot_window_and_a_spare_order(api):
    """One slot, one bag holding it, and a second READY bag with nowhere to go."""
    net = build_network(api)
    first_order = build_ready_order(api, net, **STANDARD_ORDER)
    second_order = build_ready_order(api, net, **STANDARD_ORDER)
    window = build_window(api, net.zone["id"], window_end=utc_ts(3, 22), capacity_slots=1)
    held = reserve_delivery(api, net, first_order["id"], window["id"])
    return net, second_order, window, held


class TestWindowOccupancyIsAFilteredCount:
    """"Occupancy of a window is defined by membership, not by a counter.
    `reserved_slots` is the number of deliveries pointing at that window whose
    `custody_status` is `QUEUED`, `ASSIGNED`, `PICKED_UP`, `OUT_FOR_DELIVERY`, or
    `ATTEMPT_FAILED`"
    """

    def test_a_cancellation_frees_the_slot_for_a_different_order(
        self, api, a_single_slot_window_and_a_spare_order
    ):
        """The slot is refused while held and granted the moment it leaves the set.

        "the window must not be `CLOSED` or `FULL` by status flag, or the request
        is `ERR_WINDOW_CLOSED`"

        Design: Corner/calculations/window_occupancy_counts_only_the_reserved_custody_states
        """
        net, second_order, window, held = a_single_slot_window_and_a_spare_order
        refused = api.create_delivery(
            factories.delivery_payload(
                second_order["id"], window["id"], read_window(api, window["id"])["version"]
            ),
            headers=net.pharmacy_headers,
        )
        validate_error(refused, "ERR_WINDOW_CLOSED", 409)
        _rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, window_id=window["id"])
        )
        assert meta["total_count"] == 1

        validate_success(api.cancel_delivery(held["id"], headers=net.pharmacy_headers))
        assert_window_occupancy(
            read_window(api, window["id"]),
            reserved_slots=0,
            available_slots=1,
            status="OPEN",
        )

        admitted = reserve_delivery(api, net, second_order["id"], window["id"])
        assert admitted["custody_status"] == "QUEUED"
        assert_window_occupancy(
            read_window(api, window["id"]),
            reserved_slots=1,
            available_slots=0,
            status="FULL",
        )

    def test_a_failed_run_keeps_the_slot_because_the_bag_is_still_out(
        self, api, a_single_slot_window_and_a_spare_order
    ):
        """ATTEMPT_FAILED is inside the reserved set, so the count does not drop.

        "A run that lands at `ATTEMPT_FAILED` raises `attempt_count`, stamps
        `last_attempt_at` from the clock, recomputes both courier reliability
        scores and may cascade a suspension (§3.7), and deliberately **keeps the
        window slot reserved**, because the bag is still out against that window."

        Design: Corner/calculations/window_occupancy_counts_only_the_reserved_custody_states
        """
        net, second_order, window, held = a_single_slot_window_and_a_spare_order
        validate_success(api.cancel_delivery(held["id"], headers=net.pharmacy_headers))
        admitted = reserve_delivery(api, net, second_order["id"], window["id"])

        scn = Scenario(net=net, order=second_order, window=window, delivery=admitted)
        advance_to_assigned(api, scn)
        advance_to_picked_up(api, scn)
        advance_to_out_for_delivery(api, scn, depart_clock=utc_ts(3, 14))
        record_attempt(api, scn, "NO_ANSWER")

        failed = read_delivery(api, admitted["id"])
        assert failed["custody_status"] == "ATTEMPT_FAILED"
        assert failed["attempt_count"] == 1
        assert_window_occupancy(
            read_window(api, window["id"]),
            reserved_slots=1,
            available_slots=0,
            status="FULL",
        )

        rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, window_id=window["id"])
        )
        assert meta["total_count"] == 2
        assert sorted(row["custody_status"] for row in rows) == [
            "ATTEMPT_FAILED",
            "CANCELLED",
        ]


@pytest.fixture
def two_indistinguishable_couriers(api):
    """Ray Ortiz onboarded at 09:00Z and Ida Nunez at 09:30Z, alike in every way.

    Both carry the untouched 100.00 rolling score and an `active_delivery_count`
    of 0, so only the third ranking key can separate them — and the two
    onboarding instants are kept apart so that key is itself decisive.
    """
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW)
    first = build_courier(api)
    set_clock(api, utc_ts(3, 9, 30))
    second = build_courier(api, display_name="Ida Nunez")
    set_clock(api, utc_ts(3, 13, 45))
    return scn, first, second


class TestSelectorTieBreakIsCreatedAt:
    """"Candidates are then ordered by `rolling_reliability_score` descending,
    ties broken by `active_delivery_count` ascending, and any remaining ties
    broken by `created_at` ascending — never by identifier."
    """

    def test_the_earlier_onboarded_courier_wins_a_two_key_tie(
        self, api, two_indistinguishable_couriers
    ):
        """Both leading keys are equal, so the offer follows the earlier row.

        "and a `rank_score` holding the selected courier's
        `rolling_reliability_score` at selection time — or 0.00 when the offer came
        from an operator override"

        Design: Corner/calculations/selector_tie_break_falls_to_created_at_ascending_never_to_id
        """
        scn, first, second = two_indistinguishable_couriers
        early = read_courier(api, first["id"])
        late = read_courier(api, second["id"])
        assert early["rolling_reliability_score"] == late["rolling_reliability_score"]
        assert early["active_delivery_count"] == 0
        assert late["active_delivery_count"] == 0

        offer = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
            ),
            201,
        )
        assert offer["courier_id"] == first["id"]
        assert offer["rank_score"] == pytest.approx(100.00, abs=0.01)
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "QUEUED"

    def test_excluding_the_winner_promotes_the_runner_up(
        self, api, two_indistinguishable_couriers
    ):
        """The ordering is total, so the second offer is as predictable as the first.

        "The first row after that ordering is the courier offered the job."

        Design: Corner/calculations/selector_tie_break_falls_to_created_at_ascending_never_to_id
        """
        scn, first, second = two_indistinguishable_couriers
        offer = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
            ),
            201,
        )
        validate_success(
            api.revoke_assignment(
                offer["id"], headers=OPS_HEADERS, payload={"notes": "reassigning"}
            )
        )
        assert read_delivery(api, scn.delivery["id"])["excluded_courier_ids"] == [first["id"]]

        reoffer = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
            ),
            201,
        )
        assert reoffer["courier_id"] == second["id"]
        assert_instant(reoffer["offer_expires_at"], utc_ts(3, 13, 55))

        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 2
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "QUEUED"
