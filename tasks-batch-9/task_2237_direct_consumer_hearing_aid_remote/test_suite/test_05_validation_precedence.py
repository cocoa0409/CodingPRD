"""Dual-failure requests: the lower-numbered rule is the one the caller hears about."""
from test_helpers import (
    CARE_OPS,
    ApiErrorId,
    api_client,
    assert_same_instant,
    create_inventory_pool,
    get_pool,
    get_success_data,
    get_trial_for_order,
    make_patient_headers,
    open_repair_order,
    place_order,
    set_clock,
    setup_delivered_order,
    setup_red_flagged_patient,
    simulate_payment,
    validate_error,
    validate_success,
)

CA_POLICY = {
    "state_code": "CA",
    "otc_sales_permitted": True,
    "telehealth_fitting_permitted": True,
    "min_age_years": 18,
    "trial_period_days": 30,
    "restocking_fee_mode": "FLAT_PCT",
    "restocking_fee_pct": 0.1000,
    "restocking_fee_cap_cents": 0,
    "shipping_refundable": False,
    "referral_validity_days": 180,
    "waiver_required": False,
}

TRIAL_READ_CLOCK = "2026-08-20T00:00:00Z"
PAST_WINDOW_CLOCK = "2026-09-05T00:00:00Z"
EFFECTIVE_END_UTC = "2026-08-31T00:00:00Z"
SIMPLE_ORDER = {
    "list_price_cents": 100000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 0,
}
SIMPLE_ORDER_CAPTURED_CENTS = 107250


def _red_flagged_patient_with_unstocked_order() -> dict:
    """A NEO/XL/POWER order (no such pool) placed by a patient carrying an open red flag."""
    env = setup_red_flagged_patient(
        symptom_codes=("VERTIGO",), policy_overrides=CA_POLICY, patient_overrides={"age_years": 65}
    )
    env["order"] = place_order(env["patient"]["id"], dome_size="XL", tip_type="POWER")
    env["order"] = simulate_payment(env["order"]["id"])
    return env


def _late_return_attempt_with_repair_in_flight() -> dict:
    """Delivered order whose trial window has closed while a mail-in repair kit is out."""
    env = setup_delivered_order(policy_overrides=CA_POLICY,
                               patient_overrides={"age_years": 72},
                               order_overrides=SIMPLE_ORDER)
    set_clock(TRIAL_READ_CLOCK)
    env["trial"] = get_trial_for_order(env["order"]["id"])
    open_repair_order(env, fault_code="INTERMITTENT")
    env["repair"] = get_success_data(api_client.send_repair_kit(env["repair"]["id"], CARE_OPS))
    set_clock(PAST_WINDOW_CLOCK)
    return env


def _delivered_order_with_two_pools() -> dict:
    """Delivered NEO/M/OPEN order plus a stocked NEO/L/CLOSED alternative pool."""
    env = setup_delivered_order(policy_overrides=CA_POLICY, patient_overrides={"age_years": 63})
    env["alt_pool"] = create_inventory_pool(
        restock_units=3, sku="NEO-L-CLOSED", model="NEO", dome_size="L", tip_type="CLOSED"
    )
    env["order"] = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    return env


class TestMissingPoolBeatsOpenMandatoryReferral:
    """POST /device-orders/{id}/confirm-fit violating rule 13 and rule 28 at once."""

    def test_confirm_fit_reports_the_missing_pool_not_the_open_referral(self):
        """"When a single request violates more than one rule, the rule with the lowest priority
        number below wins and its error is the one returned." (§2.9)

        "A fit confirmation for a patient with an open mandatory red flag whose model-dome-tip triple
        has no pool row violates both rule 28 and rule 13; rule 13 wins, so the caller sees
        `ERR_INVENTORY_POOL_NOT_FOUND`, because referential existence is checked before the safety
        band." (§2.9)

        Design: Difficulty/priority_pair_validation_conflict/confirm_fit_missing_pool_beats_open_mandatory_referral
        """
        env = _red_flagged_patient_with_unstocked_order()

        patient = validate_success(api_client.get_patient(env["patient"]["id"], CARE_OPS))
        assert patient["open_mandatory_flag_count"] == 1, (
            "the safety rule must genuinely be violated too, but open_mandatory_flag_count is "
            f"{patient['open_mandatory_flag_count']}"
        )
        assert patient["status"] == "REFERRAL_REQUIRED", (
            f"the red-flagged patient must sit in REFERRAL_REQUIRED, got {patient['status']!r}"
        )

        response = api_client.confirm_fit(env["order"]["id"], CARE_OPS)
        validate_error(response, ApiErrorId.ERR_INVENTORY_POOL_NOT_FOUND.value)

    def test_rejected_fit_confirmation_reserves_nothing_and_leaves_the_order_pending(self):
        """"An `InventoryPool` matching the requested `model`, `dome_size` and `tip_type` triple
        exists, on `POST /device-orders/{id}/confirm-fit` and
        `POST /device-orders/{device_order_id}/fit-exchanges` — otherwise
        `ERR_INVENTORY_POOL_NOT_FOUND` (404)." (§2.9)

        "And every `InventoryPool` satisfies an **inventory-conservation identity**: `on_hand_units`
        plus `reserved_units` plus `dispatched_units` always equals `total_units_received`." (§2.6)

        Design: Difficulty/priority_pair_validation_conflict/confirm_fit_missing_pool_beats_open_mandatory_referral
        """
        env = _red_flagged_patient_with_unstocked_order()

        validate_error(
            api_client.confirm_fit(env["order"]["id"], CARE_OPS),
            ApiErrorId.ERR_INVENTORY_POOL_NOT_FOUND.value,
        )

        order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
            "the rejected confirmation must leave fulfillment in PENDING_FIT_CONFIRM, got "
            f"{order['fulfillment_status']!r}"
        )
        assert order["payment_status"] == "AUTHORIZED", (
            f"payment must remain AUTHORIZED, got {order['payment_status']!r}"
        )

        pool = get_pool(env["pool"]["id"])
        assert pool["on_hand_units"] == 5, (
            f"the unrelated NEO/M/OPEN pool keeps its 5 on-hand units, got {pool['on_hand_units']}"
        )
        assert pool["reserved_units"] == 0, (
            f"no reservation may happen on a rejected request, got {pool['reserved_units']}"
        )
        assert pool["dispatched_units"] == 0, (
            f"nothing was dispatched, got {pool['dispatched_units']}"
        )
        assert pool["total_units_received"] == 5, (
            f"the restocked total stays 5, got {pool['total_units_received']}"
        )

        device = validate_success(api_client.get_device(env["devices"][0]["id"], CARE_OPS))
        assert device["status"] == "IN_STOCK", (
            f"no device may be assigned by a rejected confirmation, got {device['status']!r}"
        )
        assert device["device_order_id"] is None, (
            f"the device must stay unlinked, got {device['device_order_id']!r}"
        )


class TestTrialWindowClosedBeatsRepairBlock:
    """POST /trial-periods/{id}/return-authorizations violating rule 34 and rule 40 at once."""

    def test_late_return_request_reports_the_closed_window_not_the_repair_block(self):
        """"A return request made after `effective_end_utc` on an order whose device is currently in
        repair violates both rule 34 and rule 40; rule 34 wins, so the caller sees
        `ERR_TRIAL_WINDOW_CLOSED`." (§2.9)

        "No `RepairOrder` on the order's device is in `KIT_SENT`, `RECEIVED` or `IN_REPAIR`, on
        `POST /trial-periods/{trial_period_id}/return-authorizations` — otherwise
        `ERR_REPAIR_IN_PROGRESS_BLOCKS_RETURN` (409)." (§2.9)

        "`sla_days` is 5 when a plan is linked whose `plan_tier` is `PREMIUM`, 10 when the linked
        plan's tier is `STANDARD`, and 15 when there is no plan at all" (§3.7)

        Design: Difficulty/priority_pair_validation_conflict/trial_window_closed_beats_repair_in_progress_block
        """
        env = _late_return_attempt_with_repair_in_flight()

        repair = validate_success(api_client.get_repair_order(env["repair"]["id"], CARE_OPS))
        assert repair["status"] == "KIT_SENT", (
            "the repair must genuinely block returns as well, but its status is "
            f"{repair['status']!r}"
        )
        assert repair["sla_days"] == 15, (
            f"a patient with no care plan gets the 15-day SLA fallback, got {repair['sla_days']}"
        )
        assert repair["received_at"] is None, (
            "the kit was never received, so received_at must stay null, got "
            f"{repair['received_at']!r}"
        )

        response = api_client.create_return_authorization(
            env["trial"]["id"],
            {"expected_trial_period_version": env["trial"]["version"]},
            make_patient_headers(env["patient"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_TRIAL_WINDOW_CLOSED.value)

    def test_rejected_late_return_issues_no_authorization_and_keeps_the_cash_captured(self):
        """"The logical clock is at or before the trial's `effective_end_utc`, on
        `POST /trial-periods/{trial_period_id}/return-authorizations` and
        `POST /trial-periods/{id}/extend` — otherwise `ERR_TRIAL_WINDOW_CLOSED` (409)." (§2.9)

        "And `effective_end_utc` — the deadline that actually gates a return — is `nominal_end_utc`
        plus `paused_days` days plus `extension_days_granted` days." (§3.6)

        "receipt stamps `received_at` (which starts the SLA clock), sets the device to `IN_REPAIR`,
        recomputes `sla_days` from the plan tier, and when `pauses_trial` is true drives the trial
        `ACTIVE → PAUSED`" (§3.7)

        Design: Difficulty/priority_pair_validation_conflict/trial_window_closed_beats_repair_in_progress_block
        """
        env = _late_return_attempt_with_repair_in_flight()
        patient_headers = make_patient_headers(env["patient"]["id"])

        validate_error(
            api_client.create_return_authorization(
                env["trial"]["id"],
                {"expected_trial_period_version": env["trial"]["version"]},
                patient_headers,
            ),
            ApiErrorId.ERR_TRIAL_WINDOW_CLOSED.value,
        )

        trial = validate_success(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
        assert_same_instant(
            trial["effective_end_utc"], EFFECTIVE_END_UTC,
            "a repair whose kit was never received never pauses the trial, so the deadline stays "
            f"2026-08-31T00:00:00Z, got {trial['effective_end_utc']!r}",
        )
        assert trial["paused_days"] == 0, (
            f"no pause interval was ever opened, got paused_days {trial['paused_days']}"
        )
        assert trial["extension_days_granted"] == 0, (
            f"no goodwill days were granted, got {trial['extension_days_granted']}"
        )

        rows = api_client.list_trial_return_authorizations(env["trial"]["id"], CARE_OPS).json()["data"]
        assert rows == [], f"the rejected request must create no authorization, got {len(rows)} rows"

        order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["fulfillment_status"] == "DELIVERED", (
            f"fulfillment must stay DELIVERED, got {order['fulfillment_status']!r}"
        )
        assert order["payment_status"] == "CAPTURED", (
            f"payment must stay CAPTURED, got {order['payment_status']!r}"
        )
        assert order["captured_cents"] == SIMPLE_ORDER_CAPTURED_CENTS, (
            f"the captured total stays 107250, got {order['captured_cents']}"
        )
        assert order["refunded_cents"] == 0, (
            f"a rejected return refunds nothing, got {order['refunded_cents']}"
        )


class TestStaleOrderVersionBeatsSameFitConfiguration:
    """POST /device-orders/{id}/fit-exchanges violating rule 19 and rule 42 at once."""

    def test_stale_exchange_token_reports_staleness_not_the_identical_configuration(self):
        """"When a single request violates more than one rule, the rule with the lowest priority
        number below wins and its error is the one returned." (§2.9)

        "`expected_device_order_version` equals `DeviceOrder.version`, on
        `POST /device-orders/{device_order_id}/fit-exchanges` — otherwise
        `ERR_STALE_ORDER_VERSION` (412)." (§2.9, rule 19)

        "The requested `to_dome_size` and `to_tip_type` pair differs from the order's current
        `dome_size` and `tip_type` pair, on `POST /device-orders/{device_order_id}/fit-exchanges` —
        otherwise `ERR_SAME_FIT_CONFIGURATION` (422)." (§2.9, rule 42)

        "Stale-version detection deliberately runs **before** state legality, so a stale writer is
        told about staleness rather than about a state it cannot yet see." (§2.9)

        Design: Difficulty/priority_pair_validation_conflict/stale_order_version_beats_same_fit_configuration
        """
        env = _delivered_order_with_two_pools()
        order = env["order"]
        assert order["dome_size"] == "M" and order["tip_type"] == "OPEN", (
            "the requested pair must genuinely equal the current configuration, but the order is "
            f"{order['dome_size']!r}/{order['tip_type']!r}"
        )

        response = api_client.create_fit_exchange(
            order["id"],
            {
                "to_dome_size": "M",
                "to_tip_type": "OPEN",
                "expected_device_order_version": order["version"] - 1,
            },
            make_patient_headers(env["patient"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STALE_ORDER_VERSION.value)

    def test_rejected_stale_exchange_leaves_the_order_and_both_pools_untouched(self):
        """"`POST /device-orders/{device_order_id}/fit-exchanges` requires
        `expected_device_order_version` matching the target `DeviceOrder`'s current `version`. A
        mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). A completed exchange
        legitimately rewrites `dome_size` and `tip_type`, so a writer holding an earlier view would
        reserve against the wrong source pool and break inventory conservation." (§2.7)

        "Reservation happens in the same request, so an accepted request lands in `RESERVED`: the
        server writes `to_inventory_pool_id` and `from_inventory_pool_id`, decrements the target
        pool's `on_hand_units` and increments its `reserved_units`, computes `exchange_fee_cents`,
        and increments the order's `version` by one." (§3.6)

        Design: Difficulty/priority_pair_validation_conflict/stale_order_version_beats_same_fit_configuration
        """
        env = _delivered_order_with_two_pools()
        order_version_before = env["order"]["version"]

        validate_error(
            api_client.create_fit_exchange(
                env["order"]["id"],
                {
                    "to_dome_size": "M",
                    "to_tip_type": "OPEN",
                    "expected_device_order_version": order_version_before - 1,
                },
                make_patient_headers(env["patient"]["id"]),
            ),
            ApiErrorId.ERR_STALE_ORDER_VERSION.value,
        )

        rows = api_client.list_fit_exchanges(
            CARE_OPS, params={"device_order_id": env["order"]["id"]}
        ).json()["data"]
        assert rows == [], f"the rejected exchange must create no row, got {len(rows)}"

        order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["version"] == order_version_before, (
            "a rejected request increments nothing, so version must stay "
            f"{order_version_before}, got {order['version']}"
        )
        assert order["dome_size"] == "M", (
            f"the order's dome size must be unchanged, got {order['dome_size']!r}"
        )
        assert order["tip_type"] == "OPEN", (
            f"the order's tip type must be unchanged, got {order['tip_type']!r}"
        )

        source_pool = get_pool(env["pool"]["id"])
        assert source_pool["on_hand_units"] == 4, (
            "the delivered unit already left the NEO/M/OPEN shelf, so on_hand stays 4, got "
            f"{source_pool['on_hand_units']}"
        )
        assert source_pool["reserved_units"] == 0, (
            f"no exchange reservation may exist, got {source_pool['reserved_units']}"
        )
        assert source_pool["dispatched_units"] == 1, (
            f"the one delivered unit stays dispatched, got {source_pool['dispatched_units']}"
        )
        assert source_pool["total_units_received"] == 5, (
            f"the NEO/M/OPEN total stays 5, got {source_pool['total_units_received']}"
        )

        target_pool = get_pool(env["alt_pool"]["id"])
        assert target_pool["on_hand_units"] == 3, (
            f"the NEO/L/CLOSED pool keeps all 3 units on hand, got {target_pool['on_hand_units']}"
        )
        assert target_pool["reserved_units"] == 0, (
            f"nothing may be reserved in the alternative pool, got {target_pool['reserved_units']}"
        )
        assert target_pool["dispatched_units"] == 0, (
            f"nothing was dispatched from the alternative pool, got {target_pool['dispatched_units']}"
        )
        assert target_pool["total_units_received"] == 3, (
            f"the NEO/L/CLOSED total stays 3, got {target_pool['total_units_received']}"
        )
