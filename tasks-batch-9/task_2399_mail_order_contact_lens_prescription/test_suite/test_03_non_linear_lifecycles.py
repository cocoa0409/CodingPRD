"""Non-linear lifecycles: the correction loop, the pause/resume cycle, and the
Order's two parallel state dimensions.

Every scenario is built from scratch against an empty database, and the logical
clock is pinned explicitly because each rule under test reads a deadline, a
cadence or a timestamp off it.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CO_ALPHA_HEADERS,
    FO_HEADERS,
    WORKING_TUESDAY_10AM,
    api_client,
    assert_auto_reorder_schedule,
    assert_order,
    assert_verification_request,
    create_order_payload,
    make_customer_headers,
    new_order,
    pause_schedule,
    respond_to_verification_request,
    send_verification_request,
    set_clock,
    setup_active_schedule,
    setup_correction_pending_prescription,
    setup_pending_verification_prescription,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# Correction loop — a Tuesday 10:00 first round, answered CORRECTED, then a
# second round opened the next morning once the four-business-hour prescriber
# contact cooldown has elapsed.
# --------------------------------------------------------------------------

SECOND_ROUND_CLOCK = "2026-09-09T09:00:00Z"
FIRST_ROUND_DEADLINE = "2026-09-09T09:00:00.000Z"
SECOND_ROUND_DEADLINE = "2026-09-09T17:00:00.000Z"

CORRECTED_OD_SPHERE = -2.50
CORRECTED_OS_SPHERE = -4.00


def _setup_correction_pending_ready_for_second_round() -> dict:
    """A DOCTOR_LOOKUP prescription whose round-1 request came back CORRECTED,
    with the clock moved past the contact cooldown so a round 2 is permitted."""
    scenario = setup_correction_pending_prescription(
        clock=WORKING_TUESDAY_10AM,
        corrected_od_sphere=CORRECTED_OD_SPHERE,
        corrected_os_sphere=CORRECTED_OS_SPHERE,
    )
    set_clock(SECOND_ROUND_CLOCK)
    return scenario


def _open_second_round(scenario: dict):
    return api_client.send_verification_request(
        scenario["prescription"]["id"],
        {"prescriber_id": scenario["prescriber"]["id"]},
        CO_ALPHA_HEADERS,
    )


class TestPrescriptionCorrectionLoop:
    """A CORRECTED response parks the prescription in CORRECTION_PENDING, and a
    fresh verification round walks it back to PENDING_VERIFICATION."""

    def test_corrected_response_parks_prescription_in_correction_pending(self):
        """PRD §3.4: "It sets the request's `status` and `response_type` both to
        `CORRECTED`, moves the prescription from `PENDING_VERIFICATION` to
        `CORRECTION_PENDING`, and overwrites the prescription's `od_sphere` and
        `os_sphere` with the corrected values."

        PRD §3.3: "Its `round_number` is a one-based index within the
        prescription, set to the prescription's `verification_rounds` plus one,
        and the prescription's `verification_rounds` is then incremented."

        Design: Difficulty/non_linear_state_machine/prescription_correction_loop_returns_to_pending_verification
        """
        scenario = setup_correction_pending_prescription(
            clock=WORKING_TUESDAY_10AM,
            corrected_od_sphere=CORRECTED_OD_SPHERE,
            corrected_os_sphere=CORRECTED_OS_SPHERE,
        )

        request = validate_success(
            api_client.get_verification_request(
                scenario["verification_request"]["id"], CO_ALPHA_HEADERS
            )
        )
        assert_verification_request(request)
        assert request["status"] == "CORRECTED"
        assert request["response_type"] == "CORRECTED"

        prescription = validate_success(
            api_client.get_prescription(scenario["prescription"]["id"], ADMIN_HEADERS)
        )
        assert prescription["status"] == "CORRECTION_PENDING"
        assert prescription["verification_rounds"] == 1
        assert float(prescription["od_sphere"]) == CORRECTED_OD_SPHERE
        assert float(prescription["os_sphere"]) == CORRECTED_OS_SPHERE

    def test_second_round_returns_prescription_to_pending_verification(self):
        """PRD §3.3: "This is a self-loop on `PENDING_VERIFICATION` — the
        prescription's `status` does not change — and it is also the way a
        prescription in `CORRECTION_PENDING` returns to `PENDING_VERIFICATION`
        for another attempt."

        PRD §3.3: "Its `round_number` is a one-based index within the
        prescription, set to the prescription's `verification_rounds` plus one,
        and the prescription's `verification_rounds` is then incremented."

        Design: Difficulty/non_linear_state_machine/prescription_correction_loop_returns_to_pending_verification
        """
        scenario = _setup_correction_pending_ready_for_second_round()

        second_round = validate_success(_open_second_round(scenario), 201)
        assert_verification_request(second_round)
        assert second_round["round_number"] == 2
        assert second_round["status"] == "SENT"
        assert second_round["response_type"] is None

        prescription = validate_success(
            api_client.get_prescription(scenario["prescription"]["id"], ADMIN_HEADERS)
        )
        assert prescription["status"] == "PENDING_VERIFICATION"
        assert prescription["verification_rounds"] == 2
        assert float(prescription["od_sphere"]) == CORRECTED_OD_SPHERE
        assert float(prescription["os_sphere"]) == CORRECTED_OS_SPHERE

    def test_second_round_deadline_is_recomputed_from_its_own_send_instant(self):
        """PRD §3.3: "Each request's `passive_deadline_at` is computed by
        advancing a business-hour budget from `sent_at`: **eight** business hours
        when the receiving provider's `directory_verified` flag is true, and
        **twelve** business hours when it is false, because a prescriber the
        patient merely named deserves longer to object than one the directory
        confirmed."

        PRD §3.3: "A successful round creates a **verification request**."

        Design: Difficulty/non_linear_state_machine/prescription_correction_loop_returns_to_pending_verification
        """
        scenario = _setup_correction_pending_ready_for_second_round()

        second_round = validate_success(_open_second_round(scenario), 201)
        assert second_round["sent_at"] == "2026-09-09T09:00:00.000Z"
        assert second_round["passive_deadline_at"] == SECOND_ROUND_DEADLINE

        first_round = validate_success(
            api_client.get_verification_request(
                scenario["verification_request"]["id"], CO_ALPHA_HEADERS
            )
        )
        assert first_round["status"] == "CORRECTED"
        assert first_round["response_type"] == "CORRECTED"
        assert first_round["passive_deadline_at"] == FIRST_ROUND_DEADLINE


# --------------------------------------------------------------------------
# Pause / resume cycle — three boxes per run of a 30-lens daily-disposable SKU
# is 90 days of supply, less the five-day lead time, so the cadence is 85 days
# from the 2026-09-08 anchor.
# --------------------------------------------------------------------------

SCHEDULE_OVERRIDES = {
    "boxes_per_run": 3,
    "anchor_date": "2026-09-08",
    "cadence_basis": "NOMINAL",
}
EXPECTED_CADENCE_DAYS = 85
EXPECTED_NEXT_RUN_AT = "2026-12-02T08:00:00.000Z"


def _setup_paused_schedule() -> dict:
    """One NOMINAL schedule on a VERIFIED_ACTIVE prescription, paused by its own
    patient so the resume trigger has a PAUSED row to act on."""
    scenario = setup_active_schedule(
        clock=WORKING_TUESDAY_10AM, schedule_overrides=SCHEDULE_OVERRIDES
    )
    scenario["paused_schedule"] = pause_schedule(
        scenario["schedule"]["id"], scenario["customer"]["id"]
    )
    return scenario


def _resume(scenario: dict):
    return api_client.resume_auto_reorder_schedule(
        scenario["schedule"]["id"],
        make_customer_headers(scenario["customer"]["id"]),
    )


class TestSchedulePauseResumeCycle:
    """The ACTIVE-PAUSED loop is re-entrant: resuming restores ACTIVE, wipes the
    pause reason and the skip counter, and swings the customer's ledger back."""

    def test_resume_restores_active_and_clears_pause_reason_and_skips(self):
        """PRD §3.7: "Resuming moves it from `PAUSED` back to `ACTIVE`, but only
        when the customer has no hold in `OPEN` status — otherwise
        `ERR_HOLD_OPEN_BLOCKS_ACTION` — and only when the prescription's `status`
        is `VERIFIED_ACTIVE` — otherwise `ERR_PRESCRIPTION_NOT_VERIFIED`; a
        resume clears `pause_reason`, resets `consecutive_skip_count` to zero,
        and recomputes the customer's counters."

        PRD §3.7: "The `ACTIVE`-`PAUSED` loop can be traversed repeatedly."

        Design: Difficulty/non_linear_state_machine/schedule_pause_resume_cycle_clears_pause_reason_and_skips
        """
        scenario = _setup_paused_schedule()
        assert scenario["paused_schedule"]["status"] == "PAUSED"
        assert scenario["paused_schedule"]["pause_reason"] == "CUSTOMER_REQUEST"

        resumed = validate_success(_resume(scenario))
        assert_auto_reorder_schedule(resumed)
        assert resumed["status"] == "ACTIVE"
        assert resumed["pause_reason"] is None
        assert resumed["consecutive_skip_count"] == 0

    def test_resume_does_not_re_anchor_the_cadence(self):
        """PRD §3.7: "Under the `NOMINAL` variant, the supply this run represents
        is `boxes_per_run` multiplied by the product's `lenses_per_box`
        multiplied by the days one lens covers."

        PRD §3.7: "`next_run_at` is the `anchor_date` advanced by `cadence_days`,
        at 08:00 UTC on that date."

        PRD §3.7: "Resuming moves it from `PAUSED` back to `ACTIVE`, but only when
        the customer has no hold in `OPEN` status — otherwise
        `ERR_HOLD_OPEN_BLOCKS_ACTION` — and only when the prescription's `status`
        is `VERIFIED_ACTIVE` — otherwise `ERR_PRESCRIPTION_NOT_VERIFIED`; a
        resume clears `pause_reason`, resets `consecutive_skip_count` to zero,
        and recomputes the customer's counters."

        Design: Difficulty/non_linear_state_machine/schedule_pause_resume_cycle_clears_pause_reason_and_skips
        """
        scenario = _setup_paused_schedule()
        assert scenario["schedule"]["cadence_days"] == EXPECTED_CADENCE_DAYS
        assert scenario["schedule"]["next_run_at"] == EXPECTED_NEXT_RUN_AT

        resumed = validate_success(_resume(scenario))
        assert resumed["cadence_days"] == EXPECTED_CADENCE_DAYS
        assert resumed["next_run_at"] == EXPECTED_NEXT_RUN_AT

    def test_pause_resume_cycle_swings_the_customer_auto_reorder_flag(self):
        """PRD §2.7: "`active_schedule_count` is the number of that customer's
        auto-reorder schedules whose `status` is `ACTIVE`."

        PRD §2.7: "`auto_reorder_enabled` is true exactly when
        `active_schedule_count` is greater than zero and `open_hold_count` is
        zero, and false in every other case."

        PRD §3.7: "A patient pausing their own schedule moves it from `ACTIVE` to
        `PAUSED` with `pause_reason` `CUSTOMER_REQUEST` and recomputes
        `active_schedule_count` and `auto_reorder_enabled`."

        Design: Difficulty/non_linear_state_machine/schedule_pause_resume_cycle_clears_pause_reason_and_skips
        """
        scenario = setup_active_schedule(
            clock=WORKING_TUESDAY_10AM, schedule_overrides=SCHEDULE_OVERRIDES
        )
        customer_id = scenario["customer"]["id"]

        while_active = validate_success(
            api_client.get_customer(customer_id, ADMIN_HEADERS)
        )
        assert while_active["active_schedule_count"] == 1
        assert while_active["auto_reorder_enabled"] is True

        pause_schedule(scenario["schedule"]["id"], customer_id)
        while_paused = validate_success(
            api_client.get_customer(customer_id, ADMIN_HEADERS)
        )
        assert while_paused["active_schedule_count"] == 0
        assert while_paused["auto_reorder_enabled"] is False

        validate_success(_resume(scenario))
        after_resume = validate_success(
            api_client.get_customer(customer_id, ADMIN_HEADERS)
        )
        assert after_resume["active_schedule_count"] == 1
        assert after_resume["auto_reorder_enabled"] is True


# --------------------------------------------------------------------------
# Parallel order dimensions — an order placed against a prescription still in
# PENDING_VERIFICATION starts RX_PENDING / PENDING, the prescriber's CONFIRMED
# response moves only the clearance dimension, and shipping moves only the
# fulfilment dimension.
# --------------------------------------------------------------------------

SHIP_CLOCK_STAMP = "2026-09-08T10:00:00.000Z"


def _setup_order_awaiting_clearance() -> dict:
    """A PENDING order placed against a prescription still in
    PENDING_VERIFICATION, so its clearance dimension starts at RX_PENDING."""
    scenario = setup_pending_verification_prescription(clock=WORKING_TUESDAY_10AM)
    scenario["order"] = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        1,
        1,
    )
    return scenario


def _confirm_the_prescription(scenario: dict) -> dict:
    """Open a verification round and have the named prescriber CONFIRM it, which
    clears the order without touching its fulfilment dimension."""
    scenario["verification_request"] = send_verification_request(
        scenario["prescription"]["id"], scenario["prescriber"]["id"]
    )
    respond_to_verification_request(
        scenario["verification_request"]["id"],
        scenario["prescriber"]["id"],
        "CONFIRMED",
    )
    return scenario


class TestOrderParallelStateDimensions:
    """verification_state and fulfillment_state are two machines on one row, and
    neither advances the other."""

    def test_order_on_unverified_prescription_starts_rx_pending_and_pending(self):
        """PRD §3.5: "A new order carries two independent lifecycle dimensions."

        PRD §3.5: "Its `verification_state` is seeded from the prescription:
        `RX_CLEARED` when the prescription is already `VERIFIED_ACTIVE`, and
        `RX_PENDING` otherwise."

        PRD §3.5: "Its `fulfillment_state` begins at `PENDING`."

        Design: Difficulty/non_linear_state_machine/order_two_state_dimensions_advance_independently
        """
        scenario = setup_pending_verification_prescription(clock=WORKING_TUESDAY_10AM)

        created = validate_success(
            api_client.create_order(
                create_order_payload(
                    scenario["customer"]["id"],
                    scenario["prescription"]["id"],
                    scenario["product"]["id"],
                    1,
                    1,
                ),
                make_customer_headers(scenario["customer"]["id"]),
            ),
            201,
        )
        assert_order(created)
        assert created["verification_state"] == "RX_PENDING"
        assert created["fulfillment_state"] == "PENDING"

        read_back = validate_success(
            api_client.get_order(created["id"], ADMIN_HEADERS)
        )
        assert read_back["verification_state"] == "RX_PENDING"
        assert read_back["fulfillment_state"] == "PENDING"

    def test_confirmed_response_moves_only_the_clearance_dimension(self):
        """PRD §3.4: "Every order against that prescription whose
        `verification_state` is `RX_PENDING` then moves to `RX_CLEARED`,
        processed in `created_at` ascending order, each of those orders
        contributing its own `RESPONSE_RECEIVED` compliance event with
        `subject_type` `Order`."

        PRD §3.4: "The orders' `fulfillment_state` is untouched."

        Design: Difficulty/non_linear_state_machine/order_two_state_dimensions_advance_independently
        """
        scenario = _confirm_the_prescription(_setup_order_awaiting_clearance())

        cleared = validate_success(
            api_client.get_order(scenario["order"]["id"], ADMIN_HEADERS)
        )
        assert_order(cleared)
        assert cleared["verification_state"] == "RX_CLEARED"
        assert cleared["fulfillment_state"] == "PENDING"
        assert cleared["shipped_at"] is None

    def test_shipping_moves_only_the_fulfillment_dimension(self):
        """PRD §3.5: "Neither dimension's transitions ever alter the other:
        clearance never ships an order, and shipping never re-clears one."

        PRD §3.7: "Shipping stamps `shipped_at` from the logical clock and leaves
        `verification_state` untouched."

        Design: Difficulty/non_linear_state_machine/order_two_state_dimensions_advance_independently
        """
        scenario = _confirm_the_prescription(_setup_order_awaiting_clearance())

        shipped = validate_success(
            api_client.ship_order(scenario["order"]["id"], FO_HEADERS)
        )
        assert_order(shipped)
        assert shipped["verification_state"] == "RX_CLEARED"
        assert shipped["fulfillment_state"] == "SHIPPED"
        assert shipped["shipped_at"] == SHIP_CLOCK_STAMP

    def test_order_list_filters_the_two_dimensions_independently(self):
        """PRD §3.5: "Order lists may be filtered by `customer_id`,
        `prescription_id`, `ordered_product_id`, `fulfilled_product_id` and,
        independently, by `verification_state` and `fulfillment_state`."

        PRD §3.5: "Neither dimension's transitions ever alter the other:
        clearance never ships an order, and shipping never re-clears one."

        Design: Difficulty/non_linear_state_machine/order_two_state_dimensions_advance_independently
        """
        scenario = _confirm_the_prescription(_setup_order_awaiting_clearance())
        validate_success(api_client.ship_order(scenario["order"]["id"], FO_HEADERS))

        _, still_pending = validate_paginated(
            api_client.list_orders(
                ADMIN_HEADERS,
                params={
                    "verification_state": "RX_CLEARED",
                    "fulfillment_state": "PENDING",
                },
            )
        )
        assert still_pending["total_count"] == 0

        shipped_rows, shipped_meta = validate_paginated(
            api_client.list_orders(
                ADMIN_HEADERS,
                params={
                    "verification_state": "RX_CLEARED",
                    "fulfillment_state": "SHIPPED",
                },
            )
        )
        assert shipped_meta["total_count"] == 1
        assert shipped_rows[0]["id"] == scenario["order"]["id"]
