"""Cross-cutting layers: stale-version guards, multi-hop cascades, dual-variant
arithmetic, regulatory version pinning and the two cohort selectors.

Every scenario is built from scratch against an empty database with the logical clock
starting at its 2026-08-01T00:00:00Z default, and every expected figure is derived from
the PRD narrative quoted in the test's docstring.
"""
from datetime import datetime

from test_helpers import (
    ADMIN,
    CARE_OPS,
    COMPLIANCE,
    FIRMWARE_ENGINEER,
    ApiErrorId,
    api_client,
    assert_cash_conservation,
    assert_inventory_conservation,
    confirm_and_ship,
    create_devices,
    create_inventory_pool,
    create_provider,
    create_state_policy,
    get_pool,
    get_success_data,
    get_trial_for_order,
    make_licensed_audiologist_headers,
    make_patient_headers,
    place_order,
    register_patient,
    scan_shipment,
    screen_patient,
    set_clock,
    simulate_payment,
    validate_error,
    validate_paginated,
    validate_success,
)

# --- canonical clock instants ---------------------------------------------
CLOCK_START_UTC = "2026-08-01T00:00:00Z"
DAY_TEN_UTC = "2026-08-11T00:00:00Z"

# --- canonical order economics (200000 device + 1495 shipping) ------------
CANONICAL_ORDER = {
    "model": "NEO",
    "dome_size": "M",
    "tip_type": "OPEN",
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}
CAPTURED_CENTS = 215995
SHIPPING_CENTS = 1495

# --- canonical screening measurements ------------------------------------
MEASUREMENTS = {
    "pure_tone_avg_db": 40.0,
    "asymmetry_db": 5.0,
    "self_reported_difficulty_score": 20,
    "speech_in_noise_pct": 70.0,
}

# --- canonical care plan --------------------------------------------------
PLAN_BASE_FEE_CENTS = 9900


# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------
def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC field into a comparable instant."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical_environment(policy_overrides=None, pool_units: int = 5,
                           device_count: int = 1, clock: str = CLOCK_START_UTC) -> dict:
    """Clock + one state policy + a restocked NEO/M/OPEN pool + minted NEO units."""
    set_clock(clock)
    policy = create_state_policy(**(policy_overrides or {}))
    pool = create_inventory_pool(
        restock_units=pool_units, sku="NEO-M-OPEN", model="NEO", dome_size="M", tip_type="OPEN"
    )
    devices = create_devices(device_count, model="NEO", firmware_version="4.0.0")
    return {"policy": policy, "pool": pool, "devices": devices}


def _screened_patient(policy_id: str, symptom_codes=None) -> dict:
    """Register a 70-year-old and submit one screening with the canonical measurements."""
    patient = register_patient(policy_id)
    session = screen_patient(
        patient["id"], symptom_codes=list(symptom_codes or []), **MEASUREMENTS
    )
    return {"patient": patient, "screening": session}


def _deliver(order_id: str) -> dict:
    """Authorize, confirm the fit, ship and record the delivery scan."""
    simulate_payment(order_id)
    confirm_and_ship(order_id)
    return scan_shipment(order_id, "DELIVERED")


def _device_for_order(order_id: str) -> dict:
    rows = api_client.list_devices(CARE_OPS, params={"device_order_id": order_id}).json()["data"]
    assert rows, f"Setup failed: no device is assigned to order {order_id}"
    return rows[0]


def _enroll_plan(patient_id: str, order_id: str, plan_tier: str = "STANDARD",
                 base_fee_cents: int = PLAN_BASE_FEE_CENTS,
                 firmware_auto_update_enabled: bool = True) -> dict:
    return get_success_data(
        api_client.create_care_plan_subscription(
            {
                "patient_id": patient_id,
                "device_order_id": order_id,
                "plan_tier": plan_tier,
                "base_fee_cents": base_fee_cents,
                "firmware_auto_update_enabled": firmware_auto_update_enabled,
            },
            make_patient_headers(patient_id),
        )
    )


def _referral_for_patient(patient_id: str) -> dict:
    rows, _ = validate_paginated(
        api_client.list_provider_referrals(CARE_OPS, params={"patient_id": patient_id})
    )
    assert rows, f"Setup failed: no referral was opened for patient {patient_id}"
    return rows[0]


def _delivered_order_env(policy_overrides=None, pool_units: int = 5) -> dict:
    """Canonical CA patient whose 215995-cent order is delivered on 2026-08-01."""
    env = _canonical_environment(policy_overrides=policy_overrides, pool_units=pool_units)
    env.update(_screened_patient(env["policy"]["id"]))
    env["order"] = place_order(env["patient"]["id"], **CANONICAL_ORDER)
    env["order"] = _deliver(env["order"]["id"])
    env["trial"] = get_trial_for_order(env["order"]["id"])
    env["device"] = _device_for_order(env["order"]["id"])
    return env


def _campaign(campaign_code: str, window_start_utc: str, window_end_utc: str,
              to_version: str = "4.1.0", is_mandatory_safety: bool = False,
              batch_size: int = 5, max_concurrent_installs: int = 2) -> dict:
    return get_success_data(
        api_client.create_firmware_campaign(
            {
                "campaign_code": campaign_code,
                "model": "NEO",
                "from_version": "4.0.0",
                "to_version": to_version,
                "is_mandatory_safety": is_mandatory_safety,
                "batch_size": batch_size,
                "max_concurrent_installs": max_concurrent_installs,
                "window_start_utc": window_start_utc,
                "window_end_utc": window_end_utc,
            },
            FIRMWARE_ENGINEER,
        )
    )


def _settle_whole_order_return(trial_id: str, patient_headers: dict, order_id: str,
                               inspection_grade: str = "RESELLABLE") -> dict:
    """Initiate, receive, inspect and settle a whole-order trial return."""
    trial = validate_success(api_client.get_trial_period(trial_id, CARE_OPS))
    rma = validate_success(
        api_client.create_return_authorization(
            trial_id, {"expected_trial_period_version": trial["version"]}, patient_headers
        ),
        201,
    )
    # §3.6: "A carrier pickup scan moves the authorization ISSUED -> IN_TRANSIT ... Warehouse
    # receipt moves it IN_TRANSIT -> RECEIVED", so the pickup scan is a required precondition.
    scan_shipment(order_id, "RETURN_PICKED_UP")
    get_success_data(api_client.receive_return_authorization(rma["id"], CARE_OPS))
    get_success_data(
        api_client.inspect_return_authorization(
            rma["id"], {"inspection_grade": inspection_grade}, CARE_OPS
        )
    )
    return validate_success(api_client.settle_return_authorization(rma["id"], CARE_OPS))


def _clear_referral_with_audiologist(patient_id: str, provider_id: str, referral_id: str,
                                     session_start_utc: str = "2026-08-03T10:00:00Z",
                                     session_end_utc: str = "2026-08-03T10:30:00Z") -> dict:
    """Book, run and clear a REFERRAL_EVALUATION with the named audiologist."""
    provider_headers = make_licensed_audiologist_headers(provider_id)
    session = validate_success(
        api_client.create_remote_fitting_session(
            {
                "patient_id": patient_id,
                "session_type": "REFERRAL_EVALUATION",
                "provider_id": provider_id,
                "provider_referral_id": referral_id,
                "scheduled_start_utc": session_start_utc,
                "scheduled_end_utc": session_end_utc,
            },
            make_patient_headers(patient_id),
        ),
        201,
    )
    set_clock(session_start_utc)
    get_success_data(api_client.start_fitting_session(session["id"], provider_headers))
    get_success_data(api_client.complete_fitting_session(session["id"], {}, provider_headers))
    return validate_success(
        api_client.record_referral_determination(
            referral_id,
            {"clearance_outcome": "CLEARED", "clearance_note": "no pathology found"},
            provider_headers,
        )
    )


# ===========================================================================
# Optimistic concurrency: the four stale-version guards
# ===========================================================================
def test_goodwill_extension_makes_a_pinned_return_authorization_stale():
    """"`POST /trial-periods/{trial_period_id}/return-authorizations` requires
    `expected_trial_period_version` matching the target `TrialPeriod`'s current `version`. If
    another writer has advanced the trial's version since the client last read it — a superseding
    authorization after a void, or a granted goodwill extension that shifted `effective_end_utc`
    — the create is rejected with `ERR_STALE_TRIAL_VERSION` (HTTP 412)" (PRD §2.7)

    "A care operator may grant goodwill days by adding a supplied `extension_days` count to
    `extension_days_granted`, which must stay between 0 and 30 inclusive; the grant recomputes
    `effective_end_utc` and increments the trial's `version` by one" (PRD §3.6)

    "`effective_end_utc` — the deadline that actually gates a return — is `nominal_end_utc` plus
    `paused_days` days plus `extension_days_granted` days." (PRD §3.6)

    Design: Corner/cross_cutting_complexity_layers/layer_occ_stale_trial_version_on_return_authorization
    """
    env = _delivered_order_env()
    patient_headers = make_patient_headers(env["patient"]["id"])
    observed_version = env["trial"]["version"]

    get_success_data(
        api_client.extend_trial_period(env["trial"]["id"], {"extension_days": 5}, CARE_OPS)
    )

    stale = api_client.create_return_authorization(
        env["trial"]["id"],
        {"expected_trial_period_version": observed_version},
        patient_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_TRIAL_VERSION.value)

    _, meta = validate_paginated(
        api_client.list_trial_return_authorizations(env["trial"]["id"], CARE_OPS)
    )
    assert meta["total_count"] == 0, (
        f"a rejected stale return request must mint no authorization, found {meta['total_count']}"
    )

    trial = validate_success(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert trial["status"] == "ACTIVE", f"the trial must stay ACTIVE, got {trial['status']}"
    assert trial["extension_days_granted"] == 5, (
        f"extension_days_granted should be 5, got {trial['extension_days_granted']}"
    )
    assert _instant(trial["effective_end_utc"]) == _instant("2026-09-20T00:00:00Z"), (
        "effective_end_utc should be nominal end 2026-09-15 plus 5 goodwill days, got "
        f"{trial['effective_end_utc']}"
    )
    assert trial["version"] == observed_version + 1, (
        f"the extension must advance the trial exactly once: {observed_version} -> "
        f"{trial['version']}"
    )

    replay = api_client.create_return_authorization(
        env["trial"]["id"],
        {"expected_trial_period_version": trial["version"]},
        patient_headers,
    )
    validate_success(replay, 201)
    settled_trial = validate_success(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert settled_trial["status"] == "RETURN_INITIATED", (
        f"replaying with the observed version must initiate the return, got {settled_trial['status']}"
    )


def test_first_fit_exchange_makes_a_second_pinned_exchange_stale():
    """"`POST /device-orders/{device_order_id}/fit-exchanges` requires
    `expected_device_order_version` matching the target `DeviceOrder`'s current `version`. A
    mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)." (PRD §2.7)

    "Reservation happens in the same request, so an accepted request lands in `RESERVED`: the
    server writes `to_inventory_pool_id` and `from_inventory_pool_id`, decrements the target
    pool's `on_hand_units` and increments its `reserved_units`, computes `exchange_fee_cents`,
    and increments the order's `version` by one." (PRD §3.6)

    "The owning patient then confirms the new configuration fits, moving the exchange
    `SHIPPED → COMPLETED`: the order's `dome_size` and `tip_type` are rewritten to the requested
    pair" (PRD §3.6)

    "If the order's trial is `ACTIVE` or `PAUSED`, the fee is 0 — exchanges are always free inside
    the trial." (PRD §3.6)

    "And every `InventoryPool` satisfies an **inventory-conservation identity**: `on_hand_units`
    plus `reserved_units` plus `dispatched_units` always equals `total_units_received`." (PRD §2.6)

    Design: Corner/cross_cutting_complexity_layers/layer_occ_stale_order_version_on_fit_exchange
    """
    env = _canonical_environment()
    large_pool = create_inventory_pool(
        restock_units=5, sku="NEO-L-OPEN", model="NEO", dome_size="L", tip_type="OPEN"
    )
    small_pool = create_inventory_pool(
        restock_units=5, sku="NEO-S-OPEN", model="NEO", dome_size="S", tip_type="OPEN"
    )
    env.update(_screened_patient(env["policy"]["id"]))
    patient_headers = make_patient_headers(env["patient"]["id"])
    order = place_order(env["patient"]["id"], **CANONICAL_ORDER)
    order = _deliver(order["id"])
    observed_version = order["version"]

    first = validate_success(
        api_client.create_fit_exchange(
            order["id"],
            {
                "to_dome_size": "L",
                "to_tip_type": "OPEN",
                "expected_device_order_version": observed_version,
            },
            patient_headers,
        ),
        201,
    )
    assert first["status"] == "RESERVED", f"the first exchange should reserve, got {first['status']}"
    assert first["exchange_fee_cents"] == 0, (
        f"exchanges are free inside an ACTIVE trial, got {first['exchange_fee_cents']}"
    )

    stale = api_client.create_fit_exchange(
        order["id"],
        {
            "to_dome_size": "S",
            "to_tip_type": "OPEN",
            "expected_device_order_version": observed_version,
        },
        patient_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ORDER_VERSION.value)

    small = get_pool(small_pool["id"])
    assert small["on_hand_units"] == 5 and small["reserved_units"] == 0, (
        "a rejected stale exchange must reserve nothing in the target pool, got "
        f"on_hand {small['on_hand_units']} / reserved {small['reserved_units']}"
    )
    assert_inventory_conservation(small)

    _, meta = validate_paginated(
        api_client.list_fit_exchanges(CARE_OPS, params={"device_order_id": order["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the accepted exchange may exist, found {meta['total_count']}"
    )

    order_after = validate_success(api_client.get_device_order(order["id"], patient_headers))
    assert order_after["version"] == observed_version + 1, (
        f"the accepted exchange must advance the order exactly once: {observed_version} -> "
        f"{order_after['version']}"
    )
    assert order_after["dome_size"] == "M", (
        "the order's dome_size is only rewritten when the exchange is confirmed, got "
        f"{order_after['dome_size']}"
    )

    replay = validate_success(
        api_client.create_fit_exchange(
            order["id"],
            {
                "to_dome_size": "S",
                "to_tip_type": "OPEN",
                "expected_device_order_version": order_after["version"],
            },
            patient_headers,
        ),
        201,
    )
    assert replay["status"] == "RESERVED", (
        f"replaying with the observed version must reserve, got {replay['status']}"
    )
    small_after = get_pool(small_pool["id"])
    assert small_after["on_hand_units"] == 4 and small_after["reserved_units"] == 1, (
        "the replayed exchange should reserve one S/OPEN unit, got "
        f"on_hand {small_after['on_hand_units']} / reserved {small_after['reserved_units']}"
    )
    large_after = get_pool(large_pool["id"])
    assert large_after["on_hand_units"] == 4 and large_after["reserved_units"] == 1, (
        "the accepted first exchange still holds its L/OPEN unit, got "
        f"on_hand {large_after['on_hand_units']} / reserved {large_after['reserved_units']}"
    )
    assert_inventory_conservation(large_after)


def test_billing_cycle_makes_a_pinned_tier_change_stale():
    """"`POST /care-plan-subscriptions/{subscription_id}/change-tier` requires
    `expected_subscription_version` matching the target `CarePlanSubscription`'s current
    `version`. A mismatch is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)."
    (PRD §2.7)

    "Delivery of the attached order moves the plan `TRIALING → ACTIVE`, setting
    `cycle_start_utc` to the order's `delivered_at`, `cycle_end_utc` to `cycle_start_utc` plus 30
    days, and `cycle_ordinal` to 0." (PRD §3.8)

    "On success the plan self-loops `ACTIVE → ACTIVE`: the five-step computation writes
    `service_fee_cents`, `loyalty_discount_cents` and `last_charge_cents`, credit is consumed,
    `cycle_ordinal` increments" (PRD §3.8)

    Design: Corner/cross_cutting_complexity_layers/layer_occ_stale_subscription_version_on_change_tier
    """
    env = _canonical_environment()
    env.update(_screened_patient(env["policy"]["id"]))
    patient_headers = make_patient_headers(env["patient"]["id"])
    order = place_order(env["patient"]["id"], **CANONICAL_ORDER)
    plan = _enroll_plan(env["patient"]["id"], order["id"])
    _deliver(order["id"])

    plan = validate_success(api_client.get_care_plan_subscription(plan["id"], patient_headers))
    observed_version = plan["version"]
    assert plan["status"] == "ACTIVE", f"delivery must activate the plan, got {plan['status']}"

    set_clock("2026-08-31T00:00:00Z")
    get_success_data(
        api_client.run_billing_cycle(plan["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN)
    )

    stale = api_client.change_care_plan_tier(
        plan["id"],
        {"plan_tier": "PREMIUM", "expected_subscription_version": observed_version},
        patient_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value)

    after = validate_success(api_client.get_care_plan_subscription(plan["id"], patient_headers))
    assert after["plan_tier"] == "STANDARD", (
        f"a rejected stale tier change must leave the tier alone, got {after['plan_tier']}"
    )
    assert after["base_fee_cents"] == PLAN_BASE_FEE_CENTS, (
        f"base_fee_cents should stay {PLAN_BASE_FEE_CENTS}, got {after['base_fee_cents']}"
    )
    assert after["cycle_ordinal"] == 1, (
        f"the succeeded cycle should advance cycle_ordinal to 1, got {after['cycle_ordinal']}"
    )
    assert after["version"] == observed_version + 1, (
        f"the billing run must advance the plan exactly once: {observed_version} -> "
        f"{after['version']}"
    )

    replay = validate_success(
        api_client.change_care_plan_tier(
            plan["id"],
            {"plan_tier": "PREMIUM", "expected_subscription_version": after["version"]},
            patient_headers,
        )
    )
    assert replay["plan_tier"] == "PREMIUM", (
        f"replaying with the observed version must change the tier, got {replay['plan_tier']}"
    )


def test_manual_enrollment_makes_a_second_pinned_enrollment_stale():
    """"`POST /firmware-campaigns/{campaign_id}/manual-enrollments` requires
    `expected_device_version` matching the target `Device`'s current `version`. A mismatch is
    rejected with `ERR_STALE_DEVICE_VERSION` (HTTP 412)." (PRD §2.7)

    "The enrolment creates a rollout in `PENDING` whose `selection_rank` is one more than the
    campaign's current `rollout_count` and whose `from_version_observed` is the device's current
    `firmware_version`, increments the device's `version` by one, and recomputes
    `rollout_count`." (PRD §3.9)

    Design: Corner/cross_cutting_complexity_layers/layer_occ_stale_device_version_on_manual_enrollment
    """
    env = _canonical_environment()
    env.update(_screened_patient(env["policy"]["id"]))
    order = place_order(env["patient"]["id"], **CANONICAL_ORDER)
    _enroll_plan(env["patient"]["id"], order["id"])
    _deliver(order["id"])
    device = _device_for_order(order["id"])
    observed_version = validate_success(api_client.get_device(device["id"], ADMIN))["version"]

    first_campaign = _campaign("CAMP-D1", "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z")
    second_campaign = _campaign(
        "CAMP-D2", "2026-08-07T00:00:00Z", "2026-08-20T00:00:00Z", to_version="4.2.0"
    )
    get_success_data(api_client.schedule_firmware_campaign(first_campaign["id"], FIRMWARE_ENGINEER))
    get_success_data(api_client.schedule_firmware_campaign(second_campaign["id"], FIRMWARE_ENGINEER))

    validate_success(
        api_client.create_manual_enrollment(
            first_campaign["id"],
            {"device_id": device["id"], "expected_device_version": observed_version},
            FIRMWARE_ENGINEER,
        ),
        201,
    )

    stale = api_client.create_manual_enrollment(
        second_campaign["id"],
        {"device_id": device["id"], "expected_device_version": observed_version},
        FIRMWARE_ENGINEER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_DEVICE_VERSION.value)

    _, meta = validate_paginated(
        api_client.list_campaign_rollouts(second_campaign["id"], FIRMWARE_ENGINEER)
    )
    assert meta["total_count"] == 0, (
        f"a rejected stale enrollment must mint no rollout, found {meta['total_count']}"
    )

    device_after = validate_success(api_client.get_device(device["id"], ADMIN))
    assert device_after["version"] == observed_version + 1, (
        f"the accepted enrollment must advance the device exactly once: {observed_version} -> "
        f"{device_after['version']}"
    )
    assert device_after["firmware_version"] == "4.0.0", (
        f"no install ran, so firmware_version stays 4.0.0, got {device_after['firmware_version']}"
    )

    replay = validate_success(
        api_client.create_manual_enrollment(
            second_campaign["id"],
            {"device_id": device["id"], "expected_device_version": device_after["version"]},
            FIRMWARE_ENGINEER,
        ),
        201,
    )
    assert replay["selection_rank"] == 1, (
        "the second campaign had no rollouts, so selection_rank should be 1, got "
        f"{replay['selection_rank']}"
    )
    assert replay["from_version_observed"] == "4.0.0", (
        f"from_version_observed should capture 4.0.0, got {replay['from_version_observed']}"
    )
    assert replay["status"] == "PENDING", (
        f"a fresh enrollment lands in PENDING, got {replay['status']}"
    )


# ===========================================================================
# The two named multi-hop cascades
# ===========================================================================
def test_return_settlement_cascade_lands_every_hop_with_cash_conserved():
    """"**The return-settlement cascade** fires when a care operator settles an inspected return
    authorization. Hop 1 moves the `TrialPeriod` from `RETURN_INITIATED` to `RETURN_SETTLED` and
    increments `Patient.lifetime_return_count`. Hop 2 moves the `DeviceOrder`'s
    `fulfillment_status` to `RETURNED` and its `payment_status` to either `PARTIALLY_REFUNDED` or
    `REFUNDED`, updating `refunded_cents`, `retained_cents` and `open_balance_cents`. Hop 3 sets
    the `Device.status` to `RETIRED` while retaining its `device_order_id` for audit. Hop 4 moves
    every `CarePlanSubscription` attached to that order to `CANCELLED` and forfeits its
    `credit_balance_cents` by setting it to zero. Hop 5 moves every `FirmwareRollout` on that
    device whose status is `PENDING` or `OFFERED` to `CANCELLED_INELIGIBLE`" (PRD §2.8)

    "`open_balance_cents` is defined as `captured_cents` minus `refunded_cents` minus
    `retained_cents`." (PRD §2.6)

    "For a whole-order return, `refund_amount_cents` plus `restocking_fee_cents` plus
    `non_refundable_shipping_cents` equals `captured_cents` exactly." (PRD §3.6)

    Design: Corner/cross_cutting_complexity_layers/layer_cascade_a_five_hops_conserve_cash_end_to_end
    """
    env = _canonical_environment()
    env.update(_screened_patient(env["policy"]["id"]))
    patient_headers = make_patient_headers(env["patient"]["id"])
    order = place_order(env["patient"]["id"], **CANONICAL_ORDER)
    plan = _enroll_plan(env["patient"]["id"], order["id"])
    order = _deliver(order["id"])
    trial = get_trial_for_order(order["id"])
    device = _device_for_order(order["id"])

    campaign = _campaign("CAMP-L5", "2026-08-05T00:00:00Z", "2026-08-30T00:00:00Z")
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    set_clock("2026-08-05T00:00:00Z")
    get_success_data(api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    rollouts, _ = validate_paginated(
        api_client.list_campaign_rollouts(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert len(rollouts) == 1 and rollouts[0]["device_id"] == device["id"], (
        "the consenting delivered unit should be the whole cohort, got "
        f"{[row['device_id'] for row in rollouts]}"
    )
    rollout_id = rollouts[0]["id"]

    set_clock(DAY_TEN_UTC)
    trial = validate_success(api_client.get_trial_period(trial["id"], CARE_OPS))
    rma = validate_success(
        api_client.create_return_authorization(
            trial["id"], {"expected_trial_period_version": trial["version"]}, patient_headers
        ),
        201,
    )
    # §3.6 requires the carrier pickup scan (ISSUED -> IN_TRANSIT) before warehouse receipt.
    scan_shipment(order["id"], "RETURN_PICKED_UP")
    get_success_data(api_client.receive_return_authorization(rma["id"], CARE_OPS))
    get_success_data(
        api_client.inspect_return_authorization(
            rma["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
        )
    )

    settled = validate_success(api_client.settle_return_authorization(rma["id"], CARE_OPS))
    assert settled["status"] == "REFUND_SETTLED", (
        f"settlement terminates the authorization as REFUND_SETTLED, got {settled['status']}"
    )
    assert settled["restocking_variant"] == "FLAT_PCT", (
        "a pinned FLAT_PCT mode with 10 days used yields the FLAT_PCT variant, got "
        f"{settled['restocking_variant']}"
    )
    assert settled["restocking_fee_cents"] == 20000, (
        f"200000 device component at 0.1 is 20000, got {settled['restocking_fee_cents']}"
    )
    assert settled["non_refundable_shipping_cents"] == SHIPPING_CENTS, (
        f"shipping_refundable false retains {SHIPPING_CENTS}, got "
        f"{settled['non_refundable_shipping_cents']}"
    )
    assert settled["refund_amount_cents"] == 194500, (
        f"{CAPTURED_CENTS} minus 20000 minus {SHIPPING_CENTS} is 194500, got "
        f"{settled['refund_amount_cents']}"
    )

    trial_after = validate_success(api_client.get_trial_period(trial["id"], CARE_OPS))
    assert trial_after["status"] == "RETURN_SETTLED", (
        f"hop 1 must settle the trial, got {trial_after['status']}"
    )
    patient_after = validate_success(api_client.get_patient(env["patient"]["id"], CARE_OPS))
    assert patient_after["lifetime_return_count"] == 1, (
        f"hop 1 increments lifetime_return_count to 1, got {patient_after['lifetime_return_count']}"
    )

    order_after = validate_success(api_client.get_device_order(order["id"], CARE_OPS))
    assert order_after["fulfillment_status"] == "RETURNED", (
        f"hop 2 must move fulfillment to RETURNED, got {order_after['fulfillment_status']}"
    )
    assert order_after["payment_status"] == "PARTIALLY_REFUNDED", (
        f"a retained settlement lands on PARTIALLY_REFUNDED, got {order_after['payment_status']}"
    )
    assert order_after["captured_cents"] == CAPTURED_CENTS, (
        f"captured_cents stays {CAPTURED_CENTS}, got {order_after['captured_cents']}"
    )
    assert order_after["refunded_cents"] == 194500, (
        f"refunded_cents must be 194500, got {order_after['refunded_cents']}"
    )
    assert order_after["retained_cents"] == 21495, (
        f"20000 restocking plus {SHIPPING_CENTS} shipping is 21495, got "
        f"{order_after['retained_cents']}"
    )
    assert order_after["open_balance_cents"] == 0, (
        f"a whole-order return closes the open balance, got {order_after['open_balance_cents']}"
    )
    assert_cash_conservation(order_after)

    device_after = validate_success(api_client.get_device(device["id"], ADMIN))
    assert device_after["status"] == "RETIRED", (
        f"hop 3 must retire the device, got {device_after['status']}"
    )
    assert device_after["device_order_id"] == order["id"], (
        "hop 3 retains device_order_id for audit, got "
        f"{device_after['device_order_id']}"
    )

    plan_after = validate_success(api_client.get_care_plan_subscription(plan["id"], CARE_OPS))
    assert plan_after["status"] == "CANCELLED", (
        f"hop 4 must cancel the attached plan, got {plan_after['status']}"
    )
    assert plan_after["credit_balance_cents"] == 0, (
        f"hop 4 forfeits the credit balance, got {plan_after['credit_balance_cents']}"
    )

    rows, _ = validate_paginated(
        api_client.list_firmware_rollouts(FIRMWARE_ENGINEER, params={"device_id": device["id"]})
    )
    rollout_after = next(row for row in rows if row["id"] == rollout_id)
    assert rollout_after["status"] == "CANCELLED_INELIGIBLE", (
        f"hop 5 must cancel the PENDING rollout as ineligible, got {rollout_after['status']}"
    )


def test_medical_hold_cascade_only_reaches_sessions_booked_before_it_fired():
    """"**The medical-hold cascade** fires when a scored screening drives a patient into
    `REFERRAL_REQUIRED`. Hop 1 opens a `ProviderReferral` in `OPEN`. Hop 2 moves every
    `DeviceOrder` of that patient whose `fulfillment_status` is `PENDING_FIT_CONFIRM` or
    `READY_TO_SHIP` to `MEDICAL_HOLD` with `medical_hold_reason` set to `MANDATORY_RED_FLAG`.
    Hop 3 moves every `RemoteFittingSession` in `SCHEDULED` whose `session_type` is `INITIAL_FIT`
    or `FOLLOW_UP` and which references one of those orders to `CANCELLED`, with
    `no_show_charged_cents` forced to 0 — a medical hold never costs the patient a fee. Hop 4
    recomputes `booked_minutes_on_focus_date` and `utilization_pct` for every provider whose
    bookings hop 3 released." (PRD §2.8)

    "computing `expires_at` as `issued_at` plus the patient's policy `referral_validity_days`
    days" (PRD §3.3)

    "the provider's `booked_minutes_on_focus_date` and `utilization_pct` are recomputed, the
    latter as 100 multiplied by `booked_minutes_on_focus_date` divided by `daily_capacity_minutes`,
    rounded half up to one decimal place" (PRD §3.4)

    Design: Corner/cross_cutting_complexity_layers/layer_cascade_b_ordering_sensitivity_on_scheduled_sessions
    """
    env = _canonical_environment()
    provider = create_provider(
        provider_type="TELECARE_FITTER", daily_capacity_minutes=480, buffer_minutes=15
    )
    patient = register_patient(env["policy"]["id"])
    patient_headers = make_patient_headers(patient["id"])
    screening = get_success_data(api_client.start_screening_session(patient["id"], {}, patient_headers))
    order = place_order(patient["id"], **CANONICAL_ORDER)

    session = validate_success(
        api_client.create_remote_fitting_session(
            {
                "patient_id": patient["id"],
                "session_type": "FOLLOW_UP",
                "provider_id": provider["id"],
                "device_order_id": order["id"],
                "scheduled_start_utc": "2026-08-20T10:00:00Z",
                "scheduled_end_utc": "2026-08-20T12:00:00Z",
                "programming_profile": "MILD_SLOPING_V3",
            },
            patient_headers,
        ),
        201,
    )
    assert session["status"] == "SCHEDULED", (
        f"a booking is confirmed in the same request, got {session['status']}"
    )
    booked = validate_success(api_client.get_provider(provider["id"], CARE_OPS))
    assert booked["booked_minutes_on_focus_date"] == 120, (
        f"the 120-minute booking should be counted, got {booked['booked_minutes_on_focus_date']}"
    )

    get_success_data(
        api_client.update_screening_session(
            screening["id"], dict(MEASUREMENTS, symptom_codes=["VERTIGO"]), patient_headers
        )
    )
    get_success_data(api_client.submit_screening_session(screening["id"], patient_headers))

    patient_after = validate_success(api_client.get_patient(patient["id"], CARE_OPS))
    assert patient_after["status"] == "REFERRAL_REQUIRED", (
        f"a mandatory finding drives the patient to REFERRAL_REQUIRED, got {patient_after['status']}"
    )
    assert patient_after["open_mandatory_flag_count"] == 1, (
        f"the open VERTIGO finding must be counted, got {patient_after['open_mandatory_flag_count']}"
    )

    referral = _referral_for_patient(patient["id"])
    assert referral["status"] == "OPEN", f"hop 1 opens the referral, got {referral['status']}"
    assert referral["reason_codes"] == ["VERTIGO"], (
        f"reason_codes should carry the triggering finding code, got {referral['reason_codes']}"
    )
    assert _instant(referral["expires_at"]) == _instant("2027-01-28T00:00:00Z"), (
        "expires_at is 2026-08-01 plus 180 validity days, got "
        f"{referral['expires_at']}"
    )

    order_after = validate_success(api_client.get_device_order(order["id"], CARE_OPS))
    assert order_after["fulfillment_status"] == "MEDICAL_HOLD", (
        f"hop 2 must hold the PENDING_FIT_CONFIRM order, got {order_after['fulfillment_status']}"
    )
    assert order_after["medical_hold_reason"] == "MANDATORY_RED_FLAG", (
        f"the hold reason must be MANDATORY_RED_FLAG, got {order_after['medical_hold_reason']}"
    )

    session_after = validate_success(
        api_client.get_remote_fitting_session(session["id"], CARE_OPS)
    )
    assert session_after["status"] == "CANCELLED", (
        f"hop 3 must cancel the SCHEDULED FOLLOW_UP, got {session_after['status']}"
    )
    assert session_after["no_show_charged_cents"] == 0, (
        f"a medical hold never charges the patient, got {session_after['no_show_charged_cents']}"
    )

    released = validate_success(api_client.get_provider(provider["id"], CARE_OPS))
    assert released["booked_minutes_on_focus_date"] == 0, (
        "hop 4 must release the cancelled booking, got "
        f"{released['booked_minutes_on_focus_date']}"
    )
    assert released["utilization_pct"] == 0.0, (
        f"100 times 0 over 480 is 0.0, got {released['utilization_pct']}"
    )

    later = validate_success(
        api_client.create_remote_fitting_session(
            {
                "patient_id": patient["id"],
                "session_type": "FOLLOW_UP",
                "provider_id": provider["id"],
                "device_order_id": order["id"],
                "scheduled_start_utc": "2026-08-20T14:00:00Z",
                "scheduled_end_utc": "2026-08-20T16:00:00Z",
                "programming_profile": "MILD_SLOPING_V3",
            },
            patient_headers,
        ),
        201,
    )
    assert later["status"] == "SCHEDULED", (
        "a booking made after the cascade has already run is not retroactively cancelled, got "
        f"{later['status']}"
    )
    rebooked = validate_success(api_client.get_provider(provider["id"], CARE_OPS))
    assert rebooked["booked_minutes_on_focus_date"] == 120, (
        f"the later booking is counted again, got {rebooked['booked_minutes_on_focus_date']}"
    )
    assert rebooked["utilization_pct"] == 25.0, (
        f"100 times 120 over 480 is 25.0, got {rebooked['utilization_pct']}"
    )


def test_medical_hold_cascade_skips_terminal_and_ineligible_sessions():
    """"Hop 3 moves every `RemoteFittingSession` in `SCHEDULED` whose `session_type` is
    `INITIAL_FIT` or `FOLLOW_UP` and which references one of those orders to `CANCELLED`, with
    `no_show_charged_cents` forced to 0" (PRD §2.8)

    "Sessions in `COMPLETED`, `NO_SHOW`, `CANCELLED` or `REQUESTED` occupy no interval at all."
    (PRD §3.4)

    "`COMPLETED` and `CANCELLED` are the terminal session states." (PRD §3.4)

    Design: Corner/cross_cutting_complexity_layers/layer_cascade_scope_excludes_terminal_and_delivered_children
    """
    env = _canonical_environment()
    provider = create_provider(
        provider_type="TELECARE_FITTER", daily_capacity_minutes=480, buffer_minutes=15
    )
    patient = register_patient(env["policy"]["id"])
    patient_headers = make_patient_headers(patient["id"])
    screening = get_success_data(api_client.start_screening_session(patient["id"], {}, patient_headers))
    order = place_order(patient["id"], **CANONICAL_ORDER)

    def _book(session_type: str, start_utc: str, end_utc: str) -> dict:
        return validate_success(
            api_client.create_remote_fitting_session(
                {
                    "patient_id": patient["id"],
                    "session_type": session_type,
                    "provider_id": provider["id"],
                    "device_order_id": order["id"],
                    "scheduled_start_utc": start_utc,
                    "scheduled_end_utc": end_utc,
                    "programming_profile": "MILD_SLOPING_V3",
                },
                patient_headers,
            ),
            201,
        )

    eligible = _book("FOLLOW_UP", "2026-08-20T09:00:00Z", "2026-08-20T10:00:00Z")
    already_cancelled = _book("INITIAL_FIT", "2026-08-21T09:00:00Z", "2026-08-21T10:00:00Z")
    validate_success(api_client.cancel_fitting_session(already_cancelled["id"], patient_headers))
    ineligible_type = _book("TROUBLESHOOT", "2026-08-22T09:00:00Z", "2026-08-22T10:00:00Z")

    get_success_data(
        api_client.update_screening_session(
            screening["id"], dict(MEASUREMENTS, symptom_codes=["VERTIGO"]), patient_headers
        )
    )
    get_success_data(api_client.submit_screening_session(screening["id"], patient_headers))

    order_after = validate_success(api_client.get_device_order(order["id"], CARE_OPS))
    assert order_after["fulfillment_status"] == "MEDICAL_HOLD", (
        f"the PENDING_FIT_CONFIRM order is in scope for hop 2, got {order_after['fulfillment_status']}"
    )

    eligible_after = validate_success(
        api_client.get_remote_fitting_session(eligible["id"], CARE_OPS)
    )
    assert eligible_after["status"] == "CANCELLED", (
        f"the SCHEDULED FOLLOW_UP is in scope for hop 3, got {eligible_after['status']}"
    )
    assert eligible_after["no_show_charged_cents"] == 0, (
        f"hop 3 forces no_show_charged_cents to 0, got {eligible_after['no_show_charged_cents']}"
    )

    terminal_after = validate_success(
        api_client.get_remote_fitting_session(already_cancelled["id"], CARE_OPS)
    )
    assert terminal_after["status"] == "CANCELLED", (
        "a session already terminal before the cascade stays CANCELLED, got "
        f"{terminal_after['status']}"
    )

    other_type_after = validate_success(
        api_client.get_remote_fitting_session(ineligible_type["id"], CARE_OPS)
    )
    assert other_type_after["status"] == "SCHEDULED", (
        "a TROUBLESHOOT session is outside hop 3's session_type scope and stays SCHEDULED, got "
        f"{other_type_after['status']}"
    )


# ===========================================================================
# Dual-variant arithmetic
# ===========================================================================
def test_identical_measurements_score_differently_under_the_two_candidacy_variants():
    """"The weighted base is 100 multiplied by the sum of 0.40 times the pure-tone term, 0.25 times
    the difficulty term, 0.20 times the speech-in-noise term and 0.15 times the asymmetry term.
    Under the provisional variant — written by a screening submit that approved candidacy, before
    any provider has examined the patient — the score is that base rounded half up to one decimal
    place, with red-flag evidence excluded entirely and no attenuation applied. Under the
    provider-adjusted variant — written by a licensed clearance — the base is first attenuated to
    85 percent of itself, then increased by 6.0 points for each mandatory finding the clearing
    referral retired and by 2.0 points for each unit of the patient's `advisory_weight_total` as
    observed when the referral was issued; the resulting figure is capped at 100.0 and then rounded
    half up to one decimal place. Rounding happens exactly once, at the end, and never to an
    intermediate term. Identical screening measurements therefore yield a different score under the
    two variants, which is intended. The `candidacy_risk_band` is `LOW` when the score is strictly
    below 35.0, `MODERATE` when it is at least 35.0 and strictly below 65.0, and `HIGH` when it is
    at least 65.0." (PRD §3.2)

    "recomputes `candidacy_risk_score` under the `PROVIDER_ADJUSTED` variant and sets
    `candidacy_risk_variant` to `PROVIDER_ADJUSTED`, moves the patient
    `REFERRAL_REQUIRED → PROVIDER_CLEARED`" (PRD §3.3)

    Design: Corner/cross_cutting_complexity_layers/layer_dual_variant_candidacy_provisional_vs_provider_adjusted
    """
    env = _canonical_environment()
    provider = create_provider(daily_capacity_minutes=480, buffer_minutes=15)
    provisional = _screened_patient(env["policy"]["id"])
    adjusted = _screened_patient(env["policy"]["id"], symptom_codes=["VERTIGO"])

    self_reported = validate_success(api_client.get_patient(provisional["patient"]["id"], CARE_OPS))
    assert self_reported["status"] == "CANDIDATE_APPROVED", (
        f"a clean screening approves candidacy, got {self_reported['status']}"
    )
    assert self_reported["candidacy_risk_variant"] == "PROVISIONAL_SELF_REPORTED", (
        f"a screening submit writes the provisional variant, got {self_reported['candidacy_risk_variant']}"
    )
    assert self_reported["candidacy_risk_score"] == 39.3, (
        "0.40*(40/90) + 0.25*(20/40) + 0.20*(1-0.70) + 0.15*(5/25) scaled by 100 rounds once to "
        f"39.3, got {self_reported['candidacy_risk_score']}"
    )
    assert self_reported["candidacy_risk_band"] == "MODERATE", (
        f"39.3 sits in [35.0, 65.0) so the band is MODERATE, got {self_reported['candidacy_risk_band']}"
    )

    referral = _referral_for_patient(adjusted["patient"]["id"])
    cleared = _clear_referral_with_audiologist(
        adjusted["patient"]["id"], provider["id"], referral["id"]
    )
    assert cleared["clearance_outcome"] == "CLEARED", (
        f"the audiologist cleared the referral, got {cleared['clearance_outcome']}"
    )
    assert cleared["cleared_finding_count"] == 1, (
        f"the single VERTIGO finding was retired, got {cleared['cleared_finding_count']}"
    )

    provider_adjusted = validate_success(
        api_client.get_patient(adjusted["patient"]["id"], CARE_OPS)
    )
    assert provider_adjusted["status"] == "PROVIDER_CLEARED", (
        f"a CLEARED determination moves the patient to PROVIDER_CLEARED, got {provider_adjusted['status']}"
    )
    assert provider_adjusted["candidacy_risk_variant"] == "PROVIDER_ADJUSTED", (
        f"the clearance writes the provider-adjusted variant, got {provider_adjusted['candidacy_risk_variant']}"
    )
    assert provider_adjusted["open_mandatory_flag_count"] == 0, (
        f"the cleared finding no longer counts as open, got {provider_adjusted['open_mandatory_flag_count']}"
    )
    assert provider_adjusted["candidacy_risk_score"] == 39.4, (
        "the same base attenuated to 85 percent plus 6.0 for the one retired mandatory finding "
        f"rounds once to 39.4, got {provider_adjusted['candidacy_risk_score']}"
    )
    assert provider_adjusted["candidacy_risk_band"] == "MODERATE", (
        f"39.4 also sits in [35.0, 65.0), got {provider_adjusted['candidacy_risk_band']}"
    )
    assert provider_adjusted["candidacy_risk_score"] != self_reported["candidacy_risk_score"], (
        "identical measurements must not produce identical scores across the two variants"
    )


def test_flat_pct_and_prorated_daily_settlements_diverge_on_identical_returns():
    """"Under `FLAT_PCT`, the device portion is the device component multiplied by the policy's
    `restocking_fee_pct`, rounded half up; the accessory portion is the accessory component
    multiplied by `restocking_fee_pct` and again by an accessory factor of 0.5 — accessories
    restock at half the device rate — rounded half up. Under `PRORATED_DAILY`, the device portion
    is the policy's `restocking_daily_rate_cents` multiplied by the lesser of `days_used_at_issue`
    and the order's `pinned_trial_days`, and the accessory portion is 0." (PRD §3.6)

    "Step seven sets `refund_amount_cents` to the order's `captured_cents` minus
    `restocking_fee_cents` minus `non_refundable_shipping_cents`, floored at 0." (PRD §3.6)

    "Its inputs are the authorization's own `days_used_at_issue` snapshot and `inspection_grade`,
    the order's `pinned_restocking_mode`, `pinned_trial_days`, `captured_cents` and
    `shipping_cents`, and the **pinned** policy row read at the order's
    `pinned_state_policy_version`" (PRD §3.6)

    Design: Corner/cross_cutting_complexity_layers/layer_dual_variant_restocking_flat_pct_vs_prorated_daily
    """
    env = _canonical_environment(device_count=2)
    prorated_policy = create_state_policy(
        state_code="NV",
        restocking_fee_mode="PRORATED_DAILY",
        restocking_fee_pct=0.0,
        restocking_daily_rate_cents=500,
    )

    flat = _screened_patient(env["policy"]["id"])
    prorated = _screened_patient(prorated_policy["id"])
    flat_order = _deliver(place_order(flat["patient"]["id"], **CANONICAL_ORDER)["id"])
    prorated_order = _deliver(place_order(prorated["patient"]["id"], **CANONICAL_ORDER)["id"])
    assert flat_order["pinned_restocking_mode"] == "FLAT_PCT", (
        f"the CA order pins FLAT_PCT, got {flat_order['pinned_restocking_mode']}"
    )
    assert prorated_order["pinned_restocking_mode"] == "PRORATED_DAILY", (
        f"the NV order pins PRORATED_DAILY, got {prorated_order['pinned_restocking_mode']}"
    )

    set_clock(DAY_TEN_UTC)
    flat_rma = _settle_whole_order_return(
        get_trial_for_order(flat_order["id"])["id"], make_patient_headers(flat["patient"]["id"]),
        flat_order["id"],
    )
    prorated_rma = _settle_whole_order_return(
        get_trial_for_order(prorated_order["id"])["id"],
        make_patient_headers(prorated["patient"]["id"]),
        prorated_order["id"],
    )

    assert flat_rma["days_used_at_issue"] == 10, (
        f"ten whole days elapsed since delivery, got {flat_rma['days_used_at_issue']}"
    )
    assert prorated_rma["days_used_at_issue"] == 10, (
        f"the sibling return is issued on the same day, got {prorated_rma['days_used_at_issue']}"
    )

    assert flat_rma["restocking_variant"] == "FLAT_PCT", (
        f"the pinned FLAT_PCT mode selects the FLAT_PCT variant, got {flat_rma['restocking_variant']}"
    )
    assert flat_rma["restocking_fee_cents"] == 20000, (
        f"200000 times 0.1 with a zero accessory component is 20000, got {flat_rma['restocking_fee_cents']}"
    )
    assert flat_rma["refund_amount_cents"] == 194500, (
        f"{CAPTURED_CENTS} minus 20000 minus {SHIPPING_CENTS} is 194500, got {flat_rma['refund_amount_cents']}"
    )

    assert prorated_rma["restocking_variant"] == "PRORATED_DAILY", (
        f"the pinned PRORATED_DAILY mode selects that variant, got {prorated_rma['restocking_variant']}"
    )
    assert prorated_rma["restocking_fee_cents"] == 5000, (
        "500 cents per day times the lesser of 10 days used and 45 pinned trial days is 5000, got "
        f"{prorated_rma['restocking_fee_cents']}"
    )
    assert prorated_rma["refund_amount_cents"] == 209500, (
        f"{CAPTURED_CENTS} minus 5000 minus {SHIPPING_CENTS} is 209500, got "
        f"{prorated_rma['refund_amount_cents']}"
    )

    assert prorated_rma["refund_amount_cents"] - flat_rma["refund_amount_cents"] == 15000, (
        "the two regimes must diverge by exactly 15000 cents on identical orders, got a gap of "
        f"{prorated_rma['refund_amount_cents'] - flat_rma['refund_amount_cents']}"
    )

    for order_id in (flat_order["id"], prorated_order["id"]):
        order = validate_success(api_client.get_device_order(order_id, CARE_OPS))
        assert order["payment_status"] == "PARTIALLY_REFUNDED", (
            f"both retained settlements land on PARTIALLY_REFUNDED, got {order['payment_status']}"
        )
        assert_cash_conservation(order)


def test_restocking_waiver_switches_the_variant_and_reconciles_the_ledger():
    """"A compliance officer may afterwards waive retained restocking, optionally with a
    `reason_note`, provided the settled authorization's `restocking_fee_cents` is above 0 and the
    clock is within 30 days of `settled_at`. This compensating action moves the payment dimension
    `PARTIALLY_REFUNDED → REFUNDED`, refunding the retained amount so that `refunded_cents` equals
    `captured_cents`, `retained_cents` becomes 0 and `open_balance_cents` becomes 0, and rewriting
    the authorization's `restocking_variant` to `WAIVED` with `restocking_fee_cents` and
    `non_refundable_shipping_cents` set to 0 and `refund_amount_cents` set to `captured_cents`.
    Cash conservation holds before and after." (PRD §3.6)

    Design: Corner/cross_cutting_complexity_layers/layer_dual_variant_switch_to_waived_reconciles_the_ledger
    """
    env = _delivered_order_env()
    set_clock(DAY_TEN_UTC)
    rma = _settle_whole_order_return(
        env["trial"]["id"], make_patient_headers(env["patient"]["id"]), env["order"]["id"]
    )
    assert rma["restocking_variant"] == "FLAT_PCT", (
        f"the settlement retained a FLAT_PCT fee, got {rma['restocking_variant']}"
    )
    before = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert before["retained_cents"] == 21495, (
        f"the ledger retains 20000 plus {SHIPPING_CENTS} before the waiver, got {before['retained_cents']}"
    )
    assert_cash_conservation(before)

    waived = validate_success(
        api_client.waive_restocking(rma["id"], {"reason_note": "goodwill after review"}, COMPLIANCE)
    )
    assert waived["restocking_variant"] == "WAIVED", (
        f"the waiver rewrites the variant to WAIVED, got {waived['restocking_variant']}"
    )
    assert waived["restocking_fee_cents"] == 0, (
        f"the waived fee must be 0, got {waived['restocking_fee_cents']}"
    )
    assert waived["non_refundable_shipping_cents"] == 0, (
        f"the waiver also zeroes retained shipping, got {waived['non_refundable_shipping_cents']}"
    )
    assert waived["refund_amount_cents"] == CAPTURED_CENTS, (
        f"refund_amount_cents becomes captured_cents {CAPTURED_CENTS}, got {waived['refund_amount_cents']}"
    )

    after = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert after["payment_status"] == "REFUNDED", (
        f"the waiver completes the refund, got {after['payment_status']}"
    )
    assert after["captured_cents"] == CAPTURED_CENTS, (
        f"captured_cents is untouched at {CAPTURED_CENTS}, got {after['captured_cents']}"
    )
    assert after["refunded_cents"] == CAPTURED_CENTS, (
        f"refunded_cents must reach captured_cents, got {after['refunded_cents']}"
    )
    assert after["retained_cents"] == 0, (
        f"retained_cents must be 0 after the waiver, got {after['retained_cents']}"
    )
    assert after["open_balance_cents"] == 0, (
        f"open_balance_cents must be 0 after the waiver, got {after['open_balance_cents']}"
    )
    assert_cash_conservation(after)


def test_same_day_return_selects_the_waived_variant_but_still_retains_shipping():
    """"Step two selects the variant, testing in this order: if the pinned mode is `PROHIBITED` the
    variant is `WAIVED`; otherwise if `days_used_at_issue` is 0 the variant is `WAIVED` — a
    same-day return is never charged restocking; otherwise if the pinned mode is `FLAT_PCT` the
    variant is `FLAT_PCT`; otherwise it is `PRORATED_DAILY`." (PRD §3.6)

    "Step six sets `non_refundable_shipping_cents` to 0 when the pinned policy's
    `shipping_refundable` is true, and to the order's `shipping_cents` otherwise." (PRD §3.6)

    Design: Corner/cross_cutting_complexity_layers/layer_dual_variant_switch_to_waived_reconciles_the_ledger
    """
    env = _delivered_order_env()
    rma = _settle_whole_order_return(
        env["trial"]["id"], make_patient_headers(env["patient"]["id"]), env["order"]["id"]
    )

    assert rma["days_used_at_issue"] == 0, (
        f"a return issued on the delivery day has used no days, got {rma['days_used_at_issue']}"
    )
    assert rma["restocking_variant"] == "WAIVED", (
        "zero days used selects WAIVED even under a FLAT_PCT pinned mode, got "
        f"{rma['restocking_variant']}"
    )
    assert rma["restocking_fee_cents"] == 0, (
        f"the WAIVED variant charges no restocking, got {rma['restocking_fee_cents']}"
    )
    assert rma["non_refundable_shipping_cents"] == SHIPPING_CENTS, (
        "shipping_refundable false still retains the outbound charge, got "
        f"{rma['non_refundable_shipping_cents']}"
    )
    assert rma["refund_amount_cents"] == 214500, (
        f"{CAPTURED_CENTS} minus 0 minus {SHIPPING_CENTS} is 214500, got {rma['refund_amount_cents']}"
    )

    order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["payment_status"] == "PARTIALLY_REFUNDED", (
        "retained shipping alone still makes this a partial refund, got "
        f"{order['payment_status']}"
    )
    assert order["retained_cents"] == SHIPPING_CENTS, (
        f"only the {SHIPPING_CENTS} shipping is retained, got {order['retained_cents']}"
    )
    assert order["refunded_cents"] == 214500, (
        f"refunded_cents must be 214500, got {order['refunded_cents']}"
    )
    assert_cash_conservation(order)


# ===========================================================================
# Regulatory version pinning
# ===========================================================================
def test_settlement_reads_the_pinned_policy_version_not_the_amended_one():
    """"When an order is placed, the server copies the purchaser's governing policy identity and
    content onto the order: `state_policy_id`, `pinned_state_policy_version` (the policy's
    `version` as observed at that moment), `pinned_trial_days` (a copy of the policy's
    `trial_period_days`) and `pinned_restocking_mode` (a copy of the policy's
    `restocking_fee_mode`). Amending a policy through `PATCH /state-policies/{id}` increments the
    policy's own `version` by one and does **not** touch the pinned fields of any existing order.
    ... Every restocking computation reads the pinned policy row at the pinned version; live edits
    made after checkout are excluded from the arithmetic." (PRD §2.5)

    "the **pinned** policy row read at the order's `pinned_state_policy_version`; live policy edits
    made after checkout are excluded" (PRD §3.6)

    Design: Corner/cross_cutting_complexity_layers/layer_version_pinning_survives_later_policy_edits
    """
    env = _canonical_environment()
    policy = env["policy"]
    env.update(_screened_patient(policy["id"]))
    order = _deliver(place_order(env["patient"]["id"], **CANONICAL_ORDER)["id"])

    assert order["state_policy_id"] == policy["id"], (
        f"checkout copies the governing policy identity, got {order['state_policy_id']}"
    )
    assert order["pinned_state_policy_version"] == policy["version"], (
        "the pinned version must be the policy version observed at checkout "
        f"{policy['version']}, got {order['pinned_state_policy_version']}"
    )
    assert order["pinned_trial_days"] == 45, (
        f"pinned_trial_days copies trial_period_days 45, got {order['pinned_trial_days']}"
    )
    assert order["pinned_restocking_mode"] == "FLAT_PCT", (
        f"pinned_restocking_mode copies FLAT_PCT, got {order['pinned_restocking_mode']}"
    )

    amended = validate_success(
        api_client.update_state_policy(
            policy["id"], {"restocking_fee_pct": 0.2, "trial_period_days": 30}, ADMIN
        )
    )
    assert amended["restocking_fee_pct"] == 0.2, (
        f"the live policy now charges 0.2, got {amended['restocking_fee_pct']}"
    )
    assert amended["version"] == policy["version"] + 1, (
        f"an amendment advances the policy version once, got {amended['version']}"
    )

    order_after_edit = validate_success(api_client.get_device_order(order["id"], CARE_OPS))
    assert order_after_edit["pinned_state_policy_version"] == policy["version"], (
        "the amendment must not repin the existing order, got "
        f"{order_after_edit['pinned_state_policy_version']}"
    )
    assert order_after_edit["pinned_trial_days"] == 45, (
        f"pinned_trial_days must stay 45, got {order_after_edit['pinned_trial_days']}"
    )

    trial = get_trial_for_order(order["id"])
    assert _instant(trial["nominal_end_utc"]) == _instant("2026-09-15T00:00:00Z"), (
        "the trial still runs the pinned 45 days from the 2026-08-01 delivery, got "
        f"{trial['nominal_end_utc']}"
    )

    set_clock(DAY_TEN_UTC)
    rma = _settle_whole_order_return(
        trial["id"], make_patient_headers(env["patient"]["id"]), order["id"]
    )
    assert rma["restocking_variant"] == "FLAT_PCT", (
        f"the pinned mode still governs, got {rma['restocking_variant']}"
    )
    assert rma["restocking_fee_cents"] == 20000, (
        "the pinned 0.1 rate yields 20000, not the amended 0.2 rate's 40000, got "
        f"{rma['restocking_fee_cents']}"
    )
    assert rma["refund_amount_cents"] == 194500, (
        f"{CAPTURED_CENTS} minus 20000 minus {SHIPPING_CENTS} is 194500, got "
        f"{rma['refund_amount_cents']}"
    )

    order_after = validate_success(api_client.get_device_order(order["id"], CARE_OPS))
    assert order_after["retained_cents"] == 21495, (
        f"the ledger retains 21495 under the pinned rate, got {order_after['retained_cents']}"
    )
    assert_cash_conservation(order_after)


def test_a_later_order_pins_the_new_version_and_repointing_the_patient_repins_nothing():
    """"When an order is placed, the server copies the purchaser's governing policy identity and
    content onto the order: `state_policy_id`, `pinned_state_policy_version` (the policy's
    `version` as observed at that moment)" (PRD §2.5)

    "Amending a policy through `PATCH /state-policies/{id}` increments the policy's own `version`
    by one and does **not** touch the pinned fields of any existing order." (PRD §2.5)

    Design: Corner/cross_cutting_complexity_layers/layer_version_pinning_new_order_takes_v2_and_patient_repoint_does_not_repin
    """
    env = _canonical_environment(pool_units=5, device_count=2)
    policy = env["policy"]
    env.update(_screened_patient(policy["id"]))
    patient_id = env["patient"]["id"]

    first_order = place_order(patient_id, **CANONICAL_ORDER)
    assert first_order["pinned_state_policy_version"] == policy["version"], (
        f"the first order pins the original version, got {first_order['pinned_state_policy_version']}"
    )

    amended = validate_success(
        api_client.update_state_policy(policy["id"], {"restocking_fee_pct": 0.2}, ADMIN)
    )
    assert amended["version"] == policy["version"] + 1, (
        f"the amendment advances the policy version once, got {amended['version']}"
    )

    second_order = place_order(patient_id, **CANONICAL_ORDER)
    assert second_order["pinned_state_policy_version"] == amended["version"], (
        "a later checkout pins the amended version "
        f"{amended['version']}, got {second_order['pinned_state_policy_version']}"
    )

    other_policy = create_state_policy(state_code="NV", restocking_fee_mode="PROHIBITED")
    repointed = validate_success(
        api_client.update_patient(patient_id, {"state_policy_id": other_policy["id"]}, CARE_OPS)
    )
    assert repointed["state_policy_id"] == other_policy["id"], (
        f"the patient now answers to the NV policy, got {repointed['state_policy_id']}"
    )

    first_after = validate_success(api_client.get_device_order(first_order["id"], CARE_OPS))
    second_after = validate_success(api_client.get_device_order(second_order["id"], CARE_OPS))
    for label, order, expected_version in (
        ("first", first_after, policy["version"]),
        ("second", second_after, amended["version"]),
    ):
        assert order["state_policy_id"] == policy["id"], (
            f"the {label} order keeps its pinned policy identity, got {order['state_policy_id']}"
        )
        assert order["pinned_state_policy_version"] == expected_version, (
            f"the {label} order keeps pinned version {expected_version}, got "
            f"{order['pinned_state_policy_version']}"
        )
        assert order["pinned_restocking_mode"] == "FLAT_PCT", (
            f"the {label} order keeps the pinned FLAT_PCT mode, got {order['pinned_restocking_mode']}"
        )
        assert order["pinned_trial_days"] == 45, (
            f"the {label} order keeps pinned_trial_days 45, got {order['pinned_trial_days']}"
        )


# ===========================================================================
# The two cohort selectors
# ===========================================================================
def test_firmware_cohort_excludes_the_device_whose_subscriber_opted_out():
    """"and either the campaign's `is_mandatory_safety` is true or the plan attached to that
    device's order exists with `status` in `ACTIVE` or `TRIALING` and with
    `firmware_auto_update_enabled` true" (PRD §3.9)

    "The first `batch_size` candidates are taken, and for each one a `FirmwareRollout` is created
    in `PENDING` with `selection_rank` counting from 1 in that order and with
    `from_version_observed` captured from the device's current `firmware_version`." (PRD §3.9)

    "A firmware install is only offered when the subscriber's `firmware_auto_update_enabled` is
    true or the campaign's `is_mandatory_safety` is true, on `POST /firmware-rollouts/{id}/offer`
    and `POST /firmware-campaigns/{campaign_id}/manual-enrollments` — otherwise
    `ERR_AUTO_UPDATE_NOT_CONSENTED` (422)." (PRD §2.9)

    Design: Corner/cross_cutting_complexity_layers/layer_selector_cohort_excludes_non_consented_devices
    """
    env = _canonical_environment(device_count=2)
    consenting = _screened_patient(env["policy"]["id"])
    opted_out = _screened_patient(env["policy"]["id"])

    consenting_order = place_order(consenting["patient"]["id"], **CANONICAL_ORDER)
    _enroll_plan(consenting["patient"]["id"], consenting_order["id"],
                 firmware_auto_update_enabled=True)
    _deliver(consenting_order["id"])
    consenting_device = _device_for_order(consenting_order["id"])

    opted_out_order = place_order(opted_out["patient"]["id"], **CANONICAL_ORDER)
    _enroll_plan(opted_out["patient"]["id"], opted_out_order["id"],
                 firmware_auto_update_enabled=False)
    _deliver(opted_out_order["id"])
    opted_out_device = _device_for_order(opted_out_order["id"])

    campaign = _campaign("CAMP-S14", "2026-08-05T00:00:00Z", "2026-08-30T00:00:00Z")
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    set_clock("2026-08-05T00:00:00Z")

    rolling = validate_success(api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    assert rolling["status"] == "ROLLING", (
        f"the first advance moves the campaign to ROLLING, got {rolling['status']}"
    )
    assert rolling["rollout_count"] == 1, (
        f"only the consenting unit was selected, got rollout_count {rolling['rollout_count']}"
    )

    rollouts, meta = validate_paginated(
        api_client.list_campaign_rollouts(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert meta["total_count"] == 1, (
        f"the cohort must hold exactly one rollout, found {meta['total_count']}"
    )
    assert rollouts[0]["device_id"] == consenting_device["id"], (
        f"the consenting device must be the one selected, got {rollouts[0]['device_id']}"
    )
    assert rollouts[0]["selection_rank"] == 1, (
        f"selection_rank counts from 1, got {rollouts[0]['selection_rank']}"
    )
    assert rollouts[0]["status"] == "PENDING", (
        f"a selected rollout is created in PENDING, got {rollouts[0]['status']}"
    )
    assert rollouts[0]["from_version_observed"] == "4.0.0", (
        f"from_version_observed captures 4.0.0, got {rollouts[0]['from_version_observed']}"
    )
    assert all(row["device_id"] != opted_out_device["id"] for row in rollouts), (
        "the opted-out device must be absent from the cohort entirely"
    )

    device_row = validate_success(api_client.get_device(opted_out_device["id"], ADMIN))
    refused = api_client.create_manual_enrollment(
        campaign["id"],
        {"device_id": opted_out_device["id"], "expected_device_version": device_row["version"]},
        FIRMWARE_ENGINEER,
    )
    validate_error(refused, ApiErrorId.ERR_AUTO_UPDATE_NOT_CONSENTED.value)

    _, meta_after = validate_paginated(
        api_client.list_campaign_rollouts(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert meta_after["total_count"] == 1, (
        f"the refused enrollment must mint no rollout, found {meta_after['total_count']}"
    )


def test_referral_provider_selector_prefers_utilization_then_created_at_over_npi():
    """"When the booking omits a provider, the server selects one: candidates are the providers
    whose `provider_type` is `LICENSED_AUDIOLOGIST`, whose `status` is `ACTIVE`, whose
    `licensed_state_codes` contains the patient's `state_code`, who did not perform the
    invalidation of the triggering session, and for whom the daily-capacity gate of §3.4 accepts
    the candidate slot. Providers with `provider_type` `TELECARE_FITTER`, providers in `SUSPENDED`
    or `OFFBOARDED`, and providers unlicensed in the patient's state are excluded. Candidates are
    ranked by their utilization percentage — 100 multiplied by `booked_minutes_on_focus_date`
    divided by `daily_capacity_minutes`, rounded half up to one decimal place before comparison —
    ascending, so the least-loaded audiologist is picked first, with `created_at` ascending and
    then `npi` ascending as tie-breaks" (PRD §3.3)

    "Booking the evaluation moves the referral `OPEN → SCHEDULED` and stamps its `provider_id`
    with the booked provider." (PRD §3.3)

    Design: Corner/cross_cutting_complexity_layers/layer_selector_referral_provider_ranks_by_utilization_then_created_at
    """
    set_clock(CLOCK_START_UTC)
    policy = create_state_policy()
    earliest_audiologist = create_provider(
        npi="1000000022", full_name="Aud Earliest", licensed_state_codes=["CA"],
        daily_capacity_minutes=480, buffer_minutes=15,
    )
    set_clock("2026-08-01T01:00:00Z")
    lower_npi_audiologist = create_provider(
        npi="1000000021", full_name="Aud Lower NPI", licensed_state_codes=["CA"],
        daily_capacity_minutes=480, buffer_minutes=15,
    )
    set_clock("2026-08-01T02:00:00Z")
    busy_audiologist = create_provider(
        npi="1000000020", full_name="Aud Busy", licensed_state_codes=["CA"],
        daily_capacity_minutes=480, buffer_minutes=15,
    )
    fitter = create_provider(
        provider_type="TELECARE_FITTER", npi="1000000023", full_name="Fitter S",
        licensed_state_codes=["CA"], daily_capacity_minutes=480, buffer_minutes=15,
    )

    filler = register_patient(policy["id"])
    filler_headers = make_patient_headers(filler["id"])
    filler_order = place_order(filler["id"], **CANONICAL_ORDER)
    for start_utc, end_utc in (
        ("2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z"),
        ("2026-08-02T11:15:00Z", "2026-08-02T13:15:00Z"),
    ):
        validate_success(
            api_client.create_remote_fitting_session(
                {
                    "patient_id": filler["id"],
                    "session_type": "TROUBLESHOOT",
                    "provider_id": busy_audiologist["id"],
                    "device_order_id": filler_order["id"],
                    "scheduled_start_utc": start_utc,
                    "scheduled_end_utc": end_utc,
                    "programming_profile": "MILD_SLOPING_V3",
                },
                filler_headers,
            ),
            201,
        )

    target = _screened_patient(policy["id"], symptom_codes=["VERTIGO"])
    referral = _referral_for_patient(target["patient"]["id"])
    assert referral["status"] == "OPEN", f"the referral must be OPEN, got {referral['status']}"
    assert referral["provider_id"] is None, (
        f"a fresh referral names no provider, got {referral['provider_id']}"
    )

    booking = validate_success(
        api_client.create_remote_fitting_session(
            {
                "patient_id": target["patient"]["id"],
                "session_type": "REFERRAL_EVALUATION",
                "provider_referral_id": referral["id"],
                "scheduled_start_utc": "2026-08-02T14:00:00Z",
                "scheduled_end_utc": "2026-08-02T14:30:00Z",
            },
            make_patient_headers(target["patient"]["id"]),
        ),
        201,
    )
    assert booking["status"] == "SCHEDULED", (
        f"the evaluation booking is confirmed in the same request, got {booking['status']}"
    )
    assert booking["provider_id"] == earliest_audiologist["id"], (
        "the earliest-created of the two idle audiologists must win the created_at tie-break even "
        f"though its npi is the higher one, got {booking['provider_id']}"
    )
    assert booking["provider_id"] != lower_npi_audiologist["id"], (
        "npi is only consulted after created_at, so the lower-npi audiologist must not be picked"
    )
    assert booking["provider_id"] != fitter["id"], (
        "a TELECARE_FITTER is excluded from the candidate set"
    )

    referral_after = validate_success(
        api_client.get_provider_referral(referral["id"], CARE_OPS)
    )
    assert referral_after["status"] == "SCHEDULED", (
        f"booking moves the referral OPEN to SCHEDULED, got {referral_after['status']}"
    )
    assert referral_after["provider_id"] == earliest_audiologist["id"], (
        f"the referral stamps the booked provider, got {referral_after['provider_id']}"
    )

    busy = validate_success(api_client.get_provider(busy_audiologist["id"], CARE_OPS))
    assert busy["booked_minutes_on_focus_date"] == 240, (
        f"the two 120-minute fillers total 240 minutes, got {busy['booked_minutes_on_focus_date']}"
    )
    assert busy["utilization_pct"] == 50.0, (
        f"100 times 240 over 480 is 50.0, got {busy['utilization_pct']}"
    )


def test_referral_booking_is_refused_when_no_audiologist_is_licensed_in_the_state():
    """"An empty candidate set is rejected with `ERR_NO_ELIGIBLE_PROVIDER`." (PRD §3.3)

    "Providers with `provider_type` `TELECARE_FITTER`, providers in `SUSPENDED` or `OFFBOARDED`,
    and providers unlicensed in the patient's state are excluded." (PRD §3.3)

    Design: Corner/cross_cutting_complexity_layers/layer_selector_referral_provider_ranks_by_utilization_then_created_at
    """
    set_clock(CLOCK_START_UTC)
    policy = create_state_policy()
    create_provider(
        provider_type="TELECARE_FITTER", npi="1000000030", full_name="Fitter In State",
        licensed_state_codes=["CA"], daily_capacity_minutes=480, buffer_minutes=15,
    )
    create_provider(
        npi="1000000031", full_name="Aud Out Of State", licensed_state_codes=["NV"],
        daily_capacity_minutes=480, buffer_minutes=15,
    )

    target = _screened_patient(policy["id"], symptom_codes=["VERTIGO"])
    referral = _referral_for_patient(target["patient"]["id"])

    refused = api_client.create_remote_fitting_session(
        {
            "patient_id": target["patient"]["id"],
            "session_type": "REFERRAL_EVALUATION",
            "provider_referral_id": referral["id"],
            "scheduled_start_utc": "2026-08-02T14:00:00Z",
            "scheduled_end_utc": "2026-08-02T14:30:00Z",
        },
        make_patient_headers(target["patient"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_PROVIDER.value)

    referral_after = validate_success(api_client.get_provider_referral(referral["id"], CARE_OPS))
    assert referral_after["status"] == "OPEN", (
        f"a refused booking leaves the referral OPEN, got {referral_after['status']}"
    )
    assert referral_after["provider_id"] is None, (
        f"a refused booking stamps no provider, got {referral_after['provider_id']}"
    )
