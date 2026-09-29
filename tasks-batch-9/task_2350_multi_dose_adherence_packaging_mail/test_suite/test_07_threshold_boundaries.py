"""Boundary probes on the payer's refill-too-soon threshold and the cold-chain excursion limit.

Both metrics are integers compared against a fixed limit, and each rule states its own
inclusivity: the refill-too-soon edit clears at the threshold value itself, while the
cold-chain delivery branch forks only above 120 minutes.
"""

from test_helpers import (
    TECHNICIAN_ID,
    ApiErrorId,
    api_client,
    assert_cycle_state,
    assert_line_state,
    assert_memo,
    assert_patient_posture,
    assert_shipment_state,
    atorvastatin_payload,
    cold_chain_shipment_payload,
    do_adjudicate,
    do_deliver,
    insulin_payload,
    line_by_prescription,
    memo_by_reason,
    metformin_payload,
    pouch_roll_shipment_payload,
    read_cycle,
    read_cycle_events,
    read_lines,
    read_memos,
    read_patient,
    read_prescription,
    setup_draft_cycle,
    setup_shipped_cycle,
    technician_headers,
    validate_error,
)


def _draft_cycle_with_prior_fill(last_dispensed_date, with_clearing_line=False):
    """A draft cycle whose 100-day prior fill was dispensed on the given date.

    When ``with_clearing_line`` is set, a never-filled generic tablet is staged
    alongside it. That second line always clears the refill-too-soon edit (a first
    fill scores 100 percent) and routes to ``POUCH``, so roll generation reaches the
    payer gate instead of stopping at the absence of packable lines.
    """
    specs = [
        lambda patient_id: metformin_payload(
            patient_id,
            last_dispensed_date=last_dispensed_date,
            last_dispensed_days_supply=100,
        )
    ]
    if with_clearing_line:
        specs.append(atorvastatin_payload)
    return setup_draft_cycle(
        clock="2026-08-10T00:00:00Z",
        plan_overrides={"refill_too_soon_threshold_pct": 75},
        prescriptions=specs,
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )


def _shipped_cycle_with_cold_chain_parcel():
    """A cycle carrying a pouch line and a refrigerated line, both parcels in transit."""
    return setup_shipped_cycle(
        clock="2026-08-10T00:00:00Z",
        prescriptions=[metformin_payload, insulin_payload],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
        image_confidence_pct=96,
        shipments=[pouch_roll_shipment_payload(), cold_chain_shipment_payload()],
    )


class TestRefillTooSoonThresholdBoundary:
    """The refill-too-soon percentage probed at 74, 75 and 76 against a threshold of 75."""

    def test_percentage_exactly_at_the_threshold_clears_the_line(self):
        """A refill percentage landing exactly on the plan threshold clears and prices the line.

        The edit clears when `refill_pct_used` is greater than or equal to the plan's
        `refill_too_soon_threshold_pct` — the comparison is **inclusive**, so a value exactly at
        the threshold clears — or when the cycle carries a travel exception whose
        `waives_refill_too_soon` is true.
        The line's copay begins as an exact unrounded amount: choose the per-day rate by
        `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects
        `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` —
        multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the
        plan's `coinsurance_pct`, and divide by one hundred.
        That exact value is then rounded half-up to whole cents and stored as `copay_cents`.
        The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines
        whose `line_status` is `ADJUDICATED` or `PACKED_OUT`.
        The payer dimension resolves by counting held lines: if at least one line ended
        `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one
        line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and
        it becomes `CLEARED`.

        Design: Difficulty/boundary_precision_check/refill_too_soon_threshold_exact_boundary_on_adjudicate
        """
        scenario = _draft_cycle_with_prior_fill("2026-06-01")

        cycle = do_adjudicate(scenario.cycle_id)

        assert_cycle_state(
            cycle, packaging_status="LINES_ADJUDICATED", insurance_status="CLEARED"
        )
        assert cycle["total_copay_cents"] == 762, cycle
        line = line_by_prescription(read_lines(scenario.cycle_id), scenario.rx_id())
        assert line["refill_pct_used"] == 75, line
        assert_line_state(line, line_status="ADJUDICATED", hold_reason=None)
        assert line["copay_cents"] == 762, line

    def test_percentage_one_point_below_the_threshold_holds_the_line(self):
        """A refill percentage one point short of the threshold holds the line and blocks the roll.

        The edit clears when `refill_pct_used` is greater than or equal to the plan's
        `refill_too_soon_threshold_pct` — the comparison is **inclusive**, so a value exactly at
        the threshold clears — or when the cycle carries a travel exception whose
        `waives_refill_too_soon` is true.
        A line that fails the edit becomes `HELD_TOO_SOON` with `hold_reason` `REFILL_TOO_SOON`.
        Lines that are held, excluded, superseded or credited contribute nothing to
        `total_copay_cents`.
        The payer dimension resolves by counting held lines: if at least one line ended
        `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one
        line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and
        it becomes `CLEARED`.
        Its gates are evaluated in this order: the cycle's `packaging_status` must be
        `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be
        `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have
        `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise
        `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a
        prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the
        segment the new roll would occupy must not collide with a live roll of the same patient
        under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then,
        if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with
        `ERR_REFILL_TOO_SOON`.

        Design: Difficulty/boundary_precision_check/refill_too_soon_threshold_exact_boundary_on_adjudicate
        """
        scenario = _draft_cycle_with_prior_fill("2026-06-02", with_clearing_line=True)
        held_id = scenario.rx_named("Metformin ER")["id"]
        cleared_id = scenario.rx_named("Atorvastatin")["id"]

        cycle = do_adjudicate(scenario.cycle_id)

        assert_cycle_state(
            cycle,
            packaging_status="LINES_ADJUDICATED",
            insurance_status="REJECTED_TOO_SOON",
        )
        # 34 cents per generic day over 28 days at an 80 percent patient share is
        # 761.6, which rounds half-up to 762 — the cleared line's contribution alone,
        # because the held line contributes nothing.
        assert cycle["total_copay_cents"] == 762, cycle
        lines = read_lines(scenario.cycle_id)
        line = line_by_prescription(lines, held_id)
        assert line["refill_pct_used"] == 74, line
        assert_line_state(
            line, line_status="HELD_TOO_SOON", hold_reason="REFILL_TOO_SOON"
        )
        cleared = line_by_prescription(lines, cleared_id)
        assert_line_state(
            cleared,
            line_status="ADJUDICATED",
            hold_reason=None,
            packable_route="POUCH",
        )
        assert cleared["copay_cents"] == 762, cleared

        response = api_client.generate_roll(
            scenario.cycle_id, technician_headers(TECHNICIAN_ID)
        )

        validate_error(response, ApiErrorId.REFILL_TOO_SOON)
        assert_cycle_state(
            read_cycle(scenario.cycle_id), packaging_status="LINES_ADJUDICATED"
        )

    def test_percentage_one_point_above_the_threshold_clears_and_dispenses(self):
        """A refill percentage one point past the threshold clears and stamps the dispense.

        The edit clears when `refill_pct_used` is greater than or equal to the plan's
        `refill_too_soon_threshold_pct` — the comparison is **inclusive**, so a value exactly at
        the threshold clears — or when the cycle carries a travel exception whose
        `waives_refill_too_soon` is true.
        The payer dimension resolves by counting held lines: if at least one line ended
        `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one
        line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and
        it becomes `CLEARED`.
        Then `days_dispensed_total` rises by the line's `days_supply_filled`,
        `refills_remaining` falls by 1 and `refills_consumed` rises by 1.

        Design: Difficulty/boundary_precision_check/refill_too_soon_threshold_exact_boundary_on_adjudicate
        """
        scenario = _draft_cycle_with_prior_fill("2026-05-31")

        cycle = do_adjudicate(scenario.cycle_id)

        assert_cycle_state(cycle, insurance_status="CLEARED")
        line = line_by_prescription(read_lines(scenario.cycle_id), scenario.rx_id())
        assert line["refill_pct_used"] == 76, line
        assert_line_state(line, line_status="ADJUDICATED", hold_reason=None)
        prescription = read_prescription(scenario.rx_id())
        assert prescription["refills_remaining"] == 2, prescription
        assert prescription["refills_consumed"] == 1, prescription


class TestColdChainExcursionLimitBoundary:
    """The reported excursion probed at exactly 120 minutes and at 121 minutes."""

    def test_excursion_at_exactly_the_limit_still_delivers(self):
        """An excursion of exactly 120 minutes delivers the parcel and moves no money.

        The ordinary branch applies to any parcel whose `shipment_kind` is not `COLD_CHAIN`, and
        to a cold-chain parcel whose `cold_chain_excursion_minutes` is at most 120: `status`
        becomes `DELIVERED` and nothing else changes.
        The reported figure is stored on the shipment in both branches, and `delivered_at` is set
        to the clock in both branches.

        Design: Difficulty/boundary_precision_check/cold_chain_excursion_limit_exact_boundary_on_deliver
        """
        scenario = _shipped_cycle_with_cold_chain_parcel()
        cold_chain = scenario.shipment_of_kind("COLD_CHAIN")
        memos_before = read_memos(scenario.patient_id)
        balance_before = read_patient(scenario.patient_id)["credit_balance_cents"]

        shipment = do_deliver(cold_chain["id"], 120)

        assert_shipment_state(shipment, status="DELIVERED")
        assert shipment["cold_chain_excursion_minutes"] == 120, shipment
        memos_after = read_memos(scenario.patient_id)
        assert [memo["reason"] for memo in memos_after] == [
            memo["reason"] for memo in memos_before
        ], memos_after
        assert all(
            memo["reason"] != "COLD_CHAIN_EXCURSION" for memo in memos_after
        ), memos_after
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=balance_before
        )

    def test_excursion_one_minute_past_the_limit_returns_the_parcel(self):
        """An excursion of 121 minutes returns the parcel and credits the refrigerated line.

        The exception branch applies only to a `COLD_CHAIN` parcel whose
        `cold_chain_excursion_minutes` is strictly greater than 120 — the drug is no longer safe,
        so the parcel is returned and the entire dispense is unwound:
        `status` becomes `EXCEPTION_RETURNED`.
        Every line named in `covers_line_ids` becomes `CREDITED`.
        An adherence event is appended with `event_type` `DELIVERY_EXCEPTION` and `source`
        `SYSTEM_SCAN`, attributed to the cycle through `cycle_id`.

        Design: Difficulty/boundary_precision_check/cold_chain_excursion_limit_exact_boundary_on_deliver
        """
        scenario = _shipped_cycle_with_cold_chain_parcel()
        cold_chain = scenario.shipment_of_kind("COLD_CHAIN")
        refrigerated_rx_id = scenario.rx_named("Insulin glargine")["id"]

        shipment = do_deliver(cold_chain["id"], 121)

        assert_shipment_state(shipment, status="EXCEPTION_RETURNED")
        assert shipment["cold_chain_excursion_minutes"] == 121, shipment
        line = line_by_prescription(read_lines(scenario.cycle_id), refrigerated_rx_id)
        assert_line_state(line, line_status="CREDITED")
        events = read_cycle_events(scenario.cycle_id)
        exceptions = [
            event for event in events if event["event_type"] == "DELIVERY_EXCEPTION"
        ]
        assert len(exceptions) == 1, events
        assert exceptions[0]["source"] == "SYSTEM_SCAN", exceptions[0]

    def test_excursion_one_minute_past_the_limit_credits_the_line_copay(self):
        """The returned parcel mints a credit for the credited line's copay and drops the total.

        The line's copay begins as an exact unrounded amount: choose the per-day rate by
        `copay_tier` — `GENERIC` selects `generic_copay_cents_per_day`, `PREFERRED_BRAND` selects
        `brand_copay_cents_per_day`, `SPECIALTY` selects `specialty_copay_cents_per_day` —
        multiply it by the line's `days_supply_filled`, then multiply by one hundred minus the
        plan's `coinsurance_pct`, and divide by one hundred.
        That exact value is then rounded half-up to whole cents and stored as `copay_cents`.
        `final_copay_cents` is computed by summing the **unrounded** per-line amounts over the
        lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT` — each amount being the tier's
        per-day rate multiplied by the line's `days_supply_filled`, multiplied by one hundred
        minus `coinsurance_pct`, divided by one hundred — and rounding that single sum half-up to
        whole cents.
        `rounding_delta_cents` is `total_copay_cents` minus `final_copay_cents`.
        When `rounding_delta_cents` is at least 1 cent, a credit memo is issued with `reason`
        `ROUNDING_TRUEUP`, `amount_cents` equal to `rounding_delta_cents` and `status` `ISSUED`,
        and the patient's `credit_balance_cents` rises by that amount.
        A credit memo is issued with `reason` `COLD_CHAIN_EXCURSION`, `amount_cents` equal to the
        sum of `copay_cents` over the credited lines and `status` `ISSUED`, and the patient's
        `credit_balance_cents` rises by that amount.
        The cycle's `total_copay_cents` is recomputed over its remaining lines whose
        `line_status` is `ADJUDICATED` or `PACKED_OUT`; credited lines no longer contribute.

        Design: Difficulty/boundary_precision_check/cold_chain_excursion_limit_exact_boundary_on_deliver
        """
        scenario = _shipped_cycle_with_cold_chain_parcel()
        cold_chain = scenario.shipment_of_kind("COLD_CHAIN")

        do_deliver(cold_chain["id"], 121)

        memo = memo_by_reason(read_memos(scenario.patient_id), "COLD_CHAIN_EXCURSION")
        assert_memo(
            memo,
            reason="COLD_CHAIN_EXCURSION",
            amount_cents=986,
            status="ISSUED",
            cycle_id=scenario.cycle_id,
        )
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=987
        )
        cycle = read_cycle(scenario.cycle_id)
        assert cycle["total_copay_cents"] == 762, cycle
        assert cycle["final_copay_cents"] == 1747, cycle

    def test_excursion_one_minute_past_the_limit_reverses_the_dispense(self):
        """The returned parcel unwinds the refrigerated prescription's dispense exactly.

        Because those lines were credited, each one's prescription reverses its dispense exactly:
        `days_dispensed_total` falls by that line's `days_supply_filled`, `refills_remaining`
        rises by 1, `refills_consumed` falls by 1, and `last_dispensed_date` and
        `last_dispensed_days_supply` are restored verbatim from `prior_last_dispensed_date` and
        `prior_last_dispensed_days_supply`.
        The refills invariant therefore holds again, and a subsequent cycle adjudicates against
        the pre-dispense history rather than against a fill the patient never received.

        Design: Difficulty/boundary_precision_check/cold_chain_excursion_limit_exact_boundary_on_deliver
        """
        scenario = _shipped_cycle_with_cold_chain_parcel()
        cold_chain = scenario.shipment_of_kind("COLD_CHAIN")
        refrigerated_rx_id = scenario.rx_named("Insulin glargine")["id"]

        do_deliver(cold_chain["id"], 121)

        prescription = read_prescription(refrigerated_rx_id)
        assert prescription["days_dispensed_total"] == 0, prescription
        assert prescription["refills_remaining"] == 3, prescription
        assert prescription["refills_consumed"] == 0, prescription
        assert prescription["last_dispensed_date"] == "2026-07-18", prescription
        assert prescription["last_dispensed_days_supply"] == 28, prescription
