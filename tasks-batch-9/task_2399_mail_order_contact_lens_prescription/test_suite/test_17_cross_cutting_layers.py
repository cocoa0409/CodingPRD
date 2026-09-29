"""Cross-cutting layers: optimistic concurrency, deferred sweeps and the
reconciled hold counters.

Each test builds its own world from an empty database, pinning the logical clock
whenever a deadline comparison is involved.
"""

from test_helpers import (
    ApiErrorId,
    CO_ALPHA,
    CO_ALPHA_HEADERS,
    CO_BRAVO,
    FO_HEADERS,
    WORKING_TUESDAY_10AM,
    apply_substitution_payload,
    assert_ledger_values,
    assert_version_incremented,
    compliance_events,
    file_prescriber_dispute_payload,
    get_ledger,
    make_compliance_headers,
    make_prescriber_headers,
    new_auto_reorder_schedule,
    new_order,
    new_reorder_hold,
    release_reorder_hold,
    set_clock,
    setup_substitution_candidates,
    setup_verification_round,
    setup_verified_prescription,
    validate_error,
    validate_paginated,
    validate_success,
)


def event_type_count(prescription_id: str, event_type: str) -> int:
    """How many events of one type sit in a prescription's append-only trail."""
    return sum(
        1
        for event in compliance_events(prescription_id)
        if event["event_type"] == event_type
    )


class TestOptimisticConcurrencyLayer:
    """The two write operations that carry a mandatory version token."""

    def test_replayed_pre_write_order_version_is_refused_then_accepted_with_the_current_one(
        self, api
    ):
        """PRD §2.9: "Its value must equal the order's current `version` — the
        value the caller last read back from that order."

        PRD §2.9: "If the stored `version` differs, the substitution is refused
        with `ERR_STALE_ORDER_VERSION` (HTTP 412) and no field on the order
        changes, which prevents a warehouse operator from overwriting a
        substitution decision they never saw."

        PRD §2.9: "A successful substitution increments the order's `version`, so
        the next substitution attempt must present the new value."

        PRD §3.6: "Substitution is deliberately **price-neutral**: it sets
        `fulfilled_product_id`, `substitution_type`, `parameter_deviation_index`,
        `fulfilled_od_sphere` and `fulfilled_os_sphere`, appends a
        `SUBSTITUTION_APPLIED` compliance event, and increments the order's
        `version`, while leaving `unit_price_cents`, `subtotal_cents`,
        `shipping_cents` and `total_cents` exactly as they were."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_order_version_on_substitution_returns_412
        """
        scenario = setup_substitution_candidates(
            [{"brand": "OptiSoft"}, {"brand": "ClearWay"}],
            clock="2026-08-01T00:00:00Z",
            equivalence_overrides={
                "equivalence_class": "CLINICAL",
                "requires_patient_consent": False,
            },
        )
        order_id = scenario["order"]["id"]
        version_before = scenario["order"]["version"]
        second_product = scenario["substitutes"][0]
        third_product = scenario["substitutes"][1]

        first = validate_success(
            api.apply_substitution(
                order_id,
                apply_substitution_payload(second_product["id"], version_before),
                FO_HEADERS,
            )
        )
        assert first["fulfilled_product_id"] == second_product["id"]
        assert float(first["parameter_deviation_index"]) == 0.00
        assert_version_incremented(first["version"], version_before)
        version_after = first["version"]

        validate_error(
            api.apply_substitution(
                order_id,
                apply_substitution_payload(third_product["id"], version_before),
                FO_HEADERS,
            ),
            ApiErrorId.ERR_STALE_ORDER_VERSION,
        )

        unchanged = validate_success(api.get_order(order_id, FO_HEADERS))
        assert unchanged["fulfilled_product_id"] == second_product["id"]
        assert unchanged["version"] == version_after
        assert unchanged["total_cents"] == 6400

        retried = validate_success(
            api.apply_substitution(
                order_id,
                apply_substitution_payload(third_product["id"], version_after),
                FO_HEADERS,
            )
        )
        assert retried["fulfilled_product_id"] == third_product["id"]
        assert_version_incremented(retried["version"], version_after)

        assert (
            event_type_count(scenario["prescription"]["id"], "SUBSTITUTION_APPLIED") == 2
        )

    def test_prescription_version_moved_by_a_verification_round_stales_a_dispute_filing(
        self, api
    ):
        """PRD §2.9: "Filing a prescriber dispute requires
        `expected_prescription_version` in the request body, again non-optional,
        carrying the prescription `version` the prescriber last read."

        PRD §2.9: "If the stored `version` differs, no dispute row is created and
        the request is refused with `ERR_STALE_PRESCRIPTION_VERSION` (HTTP 412) —
        a prescriber must not be able to dispute a version of a prescription that
        has already been corrected or superseded out from under them."

        PRD §3.3: "Its `round_number` is a one-based index within the
        prescription, set to the prescription's `verification_rounds` plus one,
        and the prescription's `verification_rounds` is then incremented."

        PRD §2.4: "`version` — an integer that starts at 1 on creation and
        increments by one on every mutation of the row."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_prescription_version_on_dispute_filing_returns_412
        """
        scenario = setup_verification_round(clock=WORKING_TUESDAY_10AM)
        prescription_id = scenario["prescription"]["id"]
        prescriber_id = scenario["prescriber"]["id"]
        prescriber_auth = make_prescriber_headers(prescriber_id)
        version_before_round = scenario["prescription"]["version"]

        validate_error(
            api.file_prescriber_dispute(
                file_prescriber_dispute_payload(
                    prescription_id, prescriber_id, version_before_round
                ),
                prescriber_auth,
            ),
            ApiErrorId.ERR_STALE_PRESCRIPTION_VERSION,
        )

        _, meta = validate_paginated(
            api.list_prescriber_disputes(
                CO_ALPHA_HEADERS, params={"prescription_id": prescription_id}
            )
        )
        assert meta["total_count"] == 0

        current = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert current["verification_rounds"] == 1
        assert_version_incremented(current["version"], version_before_round)

        dispute = validate_success(
            api.file_prescriber_dispute(
                file_prescriber_dispute_payload(
                    prescription_id, prescriber_id, current["version"]
                ),
                prescriber_auth,
            ),
            201,
        )
        assert dispute["status"] == "OPEN"
        assert dispute["dispute_reason"] == "NOT_MY_PATIENT"

        assert event_type_count(prescription_id, "DISPUTE_FILED") == 1


class TestDeferredSweepLayer:
    """The verification sweep acts on the instant the deadline is reached."""

    def test_sweep_promotes_at_the_deadline_and_not_one_second_earlier(self, api):
        """PRD §3.3: "Each request's `passive_deadline_at` is computed by
        advancing a business-hour budget from `sent_at`: **eight** business hours
        when the receiving provider's `directory_verified` flag is true, and
        **twelve** business hours when it is false, because a prescriber the
        patient merely named deserves longer to object than one the directory
        confirmed."

        PRD §3.4: "Every verification request still in `SENT` whose
        `passive_deadline_at` has been reached, meaning the current logical time
        is at or after it, moves to the terminal `PASSIVE_TIMEOUT` with
        `response_type` left null."

        PRD §3.4: "Its prescription is promoted from `PENDING_VERIFICATION` to
        `VERIFIED_ACTIVE`, a `PASSIVE_PROMOTED` compliance event is appended, and
        every order against that prescription whose `verification_state` is
        `RX_PENDING` moves to `RX_CLEARED` in `created_at` ascending order, each
        appending its own `PASSIVE_PROMOTED` compliance event with
        `subject_type` `Order`."

        Design: Corner/cross_cutting_complexity_layers/verification_sweep_promotes_only_once_the_deadline_arrives
        """
        scenario = setup_verification_round(clock=WORKING_TUESDAY_10AM)
        prescription_id = scenario["prescription"]["id"]
        request_id = scenario["verification_request"]["id"]
        order = new_order(
            scenario["customer"]["id"],
            prescription_id,
            scenario["product"]["id"],
            1,
            1,
        )
        assert order["verification_state"] == "RX_PENDING"

        set_clock("2026-09-09T08:59:59Z")
        too_early = validate_success(api.run_verification_sweep(CO_ALPHA_HEADERS))
        assert too_early["promoted_prescription_ids"] == []
        assert too_early["timed_out_request_ids"] == []
        assert too_early["expired_prescription_ids"] == []
        assert too_early["holds_opened_count"] == 0
        assert too_early["schedules_paused_count"] == 0

        still_pending = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert still_pending["status"] == "PENDING_VERIFICATION"
        assert (
            validate_success(api.get_order(order["id"], FO_HEADERS))[
                "verification_state"
            ]
            == "RX_PENDING"
        )

        set_clock("2026-09-09T09:00:00Z")
        at_deadline = validate_success(api.run_verification_sweep(CO_ALPHA_HEADERS))
        assert at_deadline["promoted_prescription_ids"] == [prescription_id]
        assert at_deadline["timed_out_request_ids"] == [request_id]

        timed_out = validate_success(
            api.get_verification_request(request_id, CO_ALPHA_HEADERS)
        )
        assert timed_out["status"] == "PASSIVE_TIMEOUT"
        assert timed_out["response_type"] is None

        cleared = validate_success(api.get_order(order["id"], FO_HEADERS))
        assert cleared["verification_state"] == "RX_CLEARED"
        assert cleared["fulfillment_state"] == "PENDING"

        repeat = validate_success(api.run_verification_sweep(CO_ALPHA_HEADERS))
        assert repeat["promoted_prescription_ids"] == []


class TestDerivedHoldCounterLayer:
    """`open_hold_count` follows both exits from OPEN independently."""

    def test_open_hold_count_tracks_release_and_escalation_independently(self, api):
        """PRD §2.7: "`open_hold_count` is the number of that customer's reorder
        holds whose `status` is `OPEN`."

        PRD §2.7: "`auto_reorder_enabled` is true exactly when
        `active_schedule_count` is greater than zero and `open_hold_count` is
        zero, and false in every other case."

        PRD §3.7: "Creating a schedule increments the customer's
        `active_schedule_count` and recomputes `auto_reorder_enabled`."

        PRD §3.7: "Opening a hold manually records the acting `X-User-ID` in
        `opened_by_user_id`, increments the customer's `open_hold_count`,
        recomputes `auto_reorder_enabled`, and appends a `HOLD_OPENED` compliance
        event."

        PRD §3.7: "A release records `released_by_user_id`, appends a
        `HOLD_RELEASED` compliance event, and recomputes the customer's
        `open_hold_count` and `auto_reorder_enabled`."

        PRD §3.7: "Alternatively a compliance officer may escalate the hold
        instead of releasing it, supplying an `escalated_reason` that is recorded
        on the row; escalation moves the hold to `ESCALATED`, appends a
        `HOLD_ESCALATED` compliance event, and — because `ESCALATED` is no longer
        `OPEN` — also decrements `open_hold_count` and recomputes
        `auto_reorder_enabled`, so escalation clears the fulfilment block just as
        release does."

        Design: Corner/cross_cutting_complexity_layers/open_hold_count_reconciles_across_open_release_and_escalate
        """
        scenario = setup_verified_prescription(clock="2026-08-01T00:00:00Z")
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]
        new_auto_reorder_schedule(
            customer_id, prescription_id, scenario["product"]["id"]
        )
        assert_ledger_values(
            get_ledger(customer_id), open_hold_count=0, auto_reorder_enabled=True
        )

        first_hold = new_reorder_hold(customer_id, prescription_id, actor=CO_ALPHA)
        second_hold = new_reorder_hold(customer_id, prescription_id, actor=CO_ALPHA)
        assert_ledger_values(
            get_ledger(customer_id), open_hold_count=2, auto_reorder_enabled=False
        )

        release_reorder_hold(
            first_hold["id"], actor=CO_BRAVO, note="documents received"
        )
        assert_ledger_values(
            get_ledger(customer_id), open_hold_count=1, auto_reorder_enabled=False
        )

        escalated = validate_success(
            api.escalate_reorder_hold(
                second_hold["id"],
                {"escalated_reason": "second review"},
                make_compliance_headers(CO_ALPHA),
            )
        )
        assert escalated["status"] == "ESCALATED"

        assert_ledger_values(
            get_ledger(customer_id), open_hold_count=0, auto_reorder_enabled=True
        )

        _, open_meta = validate_paginated(
            api.list_reorder_holds(
                CO_ALPHA_HEADERS,
                params={"customer_id": customer_id, "status": "OPEN"},
            )
        )
        assert open_meta["total_count"] == 0
        _, all_meta = validate_paginated(api.list_reorder_holds(CO_ALPHA_HEADERS))
        assert all_meta["total_count"] == 2

        assert event_type_count(prescription_id, "HOLD_RELEASED") == 1
        assert event_type_count(prescription_id, "HOLD_ESCALATED") == 1
