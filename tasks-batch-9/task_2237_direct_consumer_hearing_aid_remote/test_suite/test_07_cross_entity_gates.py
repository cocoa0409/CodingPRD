"""Cross-entity state gates: a transition blocked by a *sibling* entity's state.

Both gates in this module are the same error class — the sibling entity named by
the transition's precondition is not in an allowed state — and both are proven by
running the identical call twice: once while the sibling is in the wrong state and
once after the sibling alone has moved.
"""
from datetime import datetime, timezone

from test_helpers import (
    ADMIN,
    CARE_OPS,
    FIRMWARE_ENGINEER,
    ApiErrorId,
    api_client,
    create_provider,
    get_success_data,
    make_hearing_professional_headers,
    make_patient_headers,
    scan_shipment,
    set_clock,
    setup_active_care_plan,
    setup_shipped_order,
    validate_error,
    validate_success,
)

# Literals below are copied from the fixed scenarios these tests describe.
INITIAL_FIT_START_UTC = "2026-08-10T10:00:00Z"
INITIAL_FIT_END_UTC = "2026-08-10T11:00:00Z"
EXPECTED_CAPTURED_CENTS = 210096
EXPECTED_NOMINAL_END_UTC = "2026-09-09T10:00:00Z"

CAMPAIGN_WINDOW_START_UTC = "2026-08-02T00:00:00Z"
CAMPAIGN_WINDOW_END_UTC = "2026-10-31T00:00:00Z"
ADVANCE_CLOCK_UTC = "2026-08-03T00:00:00Z"
CYCLE_END_UTC = "2026-08-31T00:00:00Z"
EXPECTED_SERVICE_FEE_CENTS = 495
EXPECTED_LAST_CHARGE_CENTS = 5395


def _same_instant(actual: str, expected: str) -> bool:
    """Compare two ISO 8601 UTC timestamps as instants, ignoring fractional spelling."""
    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    return parse(actual) == parse(expected)


# ---------------------------------------------------------------------------
# (RemoteFittingSession, DeviceOrder)
# ---------------------------------------------------------------------------
def _setup_shipped_order_with_booked_initial_fit() -> dict:
    """Order SHIPPED but not delivered, with an INITIAL_FIT session whose window is open."""
    env = setup_shipped_order(
        policy_overrides={"trial_period_days": 30},
        patient_overrides={"age_years": 66},
    )
    env["provider"] = create_provider(
        provider_type="TELECARE_FITTER",
        full_name="Fit Starter",
        daily_capacity_minutes=480,
        buffer_minutes=10,
    )
    env["session"] = get_success_data(
        api_client.create_remote_fitting_session(
            {
                "patient_id": env["patient"]["id"],
                "session_type": "INITIAL_FIT",
                "scheduled_start_utc": INITIAL_FIT_START_UTC,
                "scheduled_end_utc": INITIAL_FIT_END_UTC,
                "provider_id": env["provider"]["id"],
                "device_order_id": env["order"]["id"],
            },
            make_patient_headers(env["patient"]["id"]),
        )
    )
    devices = api_client.list_devices(
        CARE_OPS, params={"device_order_id": env["order"]["id"]}
    ).json()["data"]
    env["assigned_device"] = devices[0]
    # The clock lands exactly on scheduled_start_utc, so the session window is open.
    set_clock(INITIAL_FIT_START_UTC)
    return env


def test_initial_fit_start_rejected_while_linked_order_is_only_shipped():
    """"A provider starts the appointment inside its window, moving it `SCHEDULED → IN_PROGRESS`;
    the clock must be at or after `scheduled_start_utc` and strictly before `scheduled_end_utc`,
    and for an `INITIAL_FIT` the linked order's `fulfillment_status` must already be `DELIVERED`."
    (PRD §3.4)

    "The sibling entity named by the transition's precondition is in an allowed state — the
    order's `fulfillment_status` is `DELIVERED` before an `INITIAL_FIT` session may start ...
    otherwise `ERR_DEPENDENT_STATE_NOT_READY` (409)." (PRD §2.9 rule 24)

    Design: Difficulty/cross_entity_state_dependency/initial_fit_start_requires_linked_order_delivered
    """
    env = _setup_shipped_order_with_booked_initial_fit()
    provider_headers = make_hearing_professional_headers(env["provider"]["id"])

    resp = api_client.start_fitting_session(env["session"]["id"], provider_headers)
    validate_error(resp, ApiErrorId.ERR_DEPENDENT_STATE_NOT_READY.value)

    session = validate_success(
        api_client.get_remote_fitting_session(env["session"]["id"], CARE_OPS)
    )
    assert session["status"] == "SCHEDULED", (
        "a rejected start must leave the session in SCHEDULED, got "
        f"{session['status']!r}"
    )

    order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["fulfillment_status"] == "SHIPPED", (
        "the rejected start must not advance the order's fulfillment dimension, got "
        f"{order['fulfillment_status']!r}"
    )


def test_delivery_scan_advances_order_device_and_starts_the_trial():
    """"A carrier scan against a named `device_order_id` with an `event` of `DELIVERED` moves
    fulfillment `SHIPPED → DELIVERED`, stamps `delivered_at`, sets the device to `WITH_PATIENT`,
    creates the trial period described in §3.6 in `ACTIVE` with `started_at` equal to
    `delivered_at`" (PRD §3.5)

    "A `TrialPeriod` is created with `device_order_id` and a denormalized `patient_id` ... `status`
    `ACTIVE`, `started_at` equal to the order's `delivered_at`, `nominal_end_utc` equal to
    `started_at` plus the order's `pinned_trial_days` days" (PRD §3.6)

    Design: Difficulty/cross_entity_state_dependency/initial_fit_start_requires_linked_order_delivered
    """
    env = _setup_shipped_order_with_booked_initial_fit()

    order = validate_success(
        api_client.scan_shipment(
            {"device_order_id": env["order"]["id"], "event": "DELIVERED"}, ADMIN
        )
    )
    assert order["fulfillment_status"] == "DELIVERED", (
        f"the delivery scan must move fulfillment to DELIVERED, got {order['fulfillment_status']!r}"
    )
    assert order["payment_status"] == "CAPTURED", (
        f"shipping captured payment, so payment_status stays CAPTURED, got {order['payment_status']!r}"
    )
    assert order["captured_cents"] == EXPECTED_CAPTURED_CENTS, (
        f"captured_cents must equal total_cents {EXPECTED_CAPTURED_CENTS}, got {order['captured_cents']}"
    )

    device = validate_success(api_client.get_device(env["assigned_device"]["id"], CARE_OPS))
    assert device["status"] == "WITH_PATIENT", (
        f"delivery must set the assigned device to WITH_PATIENT, got {device['status']!r}"
    )

    trials = api_client.list_trial_periods(
        CARE_OPS, params={"device_order_id": env["order"]["id"]}
    ).json()["data"]
    assert len(trials) == 1, f"delivery must create exactly one trial period, got {len(trials)}"
    trial = trials[0]
    assert trial["status"] == "ACTIVE", f"a new trial is ACTIVE, got {trial['status']!r}"
    assert _same_instant(trial["started_at"], INITIAL_FIT_START_UTC), (
        f"trial started_at must equal delivered_at {INITIAL_FIT_START_UTC}, got {trial['started_at']!r}"
    )
    assert _same_instant(trial["nominal_end_utc"], EXPECTED_NOMINAL_END_UTC), (
        "nominal_end_utc must be started_at plus the pinned 30 trial days "
        f"({EXPECTED_NOMINAL_END_UTC}), got {trial['nominal_end_utc']!r}"
    )


def test_initial_fit_start_succeeds_once_the_order_is_delivered_at_the_same_clock():
    """"for an `INITIAL_FIT` the linked order's `fulfillment_status` must already be `DELIVERED`.
    Starting changes no derived field." (PRD §3.4)

    "A provider starts the appointment inside its window, moving it `SCHEDULED → IN_PROGRESS`"
    (PRD §3.4)

    Design: Difficulty/cross_entity_state_dependency/initial_fit_start_requires_linked_order_delivered
    """
    env = _setup_shipped_order_with_booked_initial_fit()
    provider_headers = make_hearing_professional_headers(env["provider"]["id"])

    blocked = api_client.start_fitting_session(env["session"]["id"], provider_headers)
    validate_error(blocked, ApiErrorId.ERR_DEPENDENT_STATE_NOT_READY.value)

    scan_shipment(env["order"]["id"], "DELIVERED")

    session = validate_success(
        api_client.start_fitting_session(env["session"]["id"], provider_headers)
    )
    assert session["status"] == "IN_PROGRESS", (
        "the identical start call must succeed once the sibling order is DELIVERED, got "
        f"{session['status']!r}"
    )


# ---------------------------------------------------------------------------
# (FirmwareRollout, CarePlanSubscription)
# ---------------------------------------------------------------------------
def _setup_pending_rollout_with_past_due_plan() -> dict:
    """One PENDING rollout of a non-safety ROLLING campaign whose device's plan is PAST_DUE."""
    env = setup_active_care_plan(
        policy_overrides={"trial_period_days": 30},
        patient_overrides={"age_years": 70},
        plan_overrides={"plan_tier": "STANDARD", "base_fee_cents": 4900},
    )
    campaign = get_success_data(
        api_client.create_firmware_campaign(
            {
                "campaign_code": "FW-NEO-421",
                "model": "NEO",
                "from_version": "4.0.0",
                "to_version": "4.2.1",
                "window_start_utc": CAMPAIGN_WINDOW_START_UTC,
                "window_end_utc": CAMPAIGN_WINDOW_END_UTC,
                "is_mandatory_safety": False,
                "batch_size": 3,
                "max_concurrent_installs": 2,
            },
            FIRMWARE_ENGINEER,
        )
    )
    env["campaign"] = get_success_data(
        api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    )

    set_clock(ADVANCE_CLOCK_UTC)
    env["campaign"] = get_success_data(
        api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    )
    rollouts = api_client.list_campaign_rollouts(campaign["id"], FIRMWARE_ENGINEER).json()["data"]
    assert len(rollouts) == 1, f"the advance must select exactly the one eligible device, got {len(rollouts)}"
    env["rollout"] = rollouts[0]

    set_clock(CYCLE_END_UTC)
    # A declined instrument is reported to the caller as ERR_PAYMENT_DECLINED (§2.9 rule 62)
    # while the dunning transition ACTIVE -> PAST_DUE is still committed (§3.8), so the plan
    # has to be read back rather than taken from the failed call's body.
    declined = api_client.run_billing_cycle(env["plan"]["id"], {"charge_outcome": "DECLINED"}, ADMIN)
    assert declined.status_code == 402, (
        f"Setup failed: a declined cycle charge must report 402, got {declined.status_code}: {declined.text}"
    )
    env["plan"] = get_success_data(api_client.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
    assert env["plan"]["status"] == "PAST_DUE", (
        f"Setup failed: the declined cycle must leave the plan PAST_DUE, got {env['plan']['status']!r}"
    )
    return env


def _read_rollout(env: dict) -> dict:
    rows = api_client.list_campaign_rollouts(env["campaign"]["id"], FIRMWARE_ENGINEER).json()["data"]
    for row in rows:
        if row["id"] == env["rollout"]["id"]:
            return row
    raise AssertionError(f"rollout {env['rollout']['id']} disappeared from its campaign listing")


def test_declined_billing_cycle_puts_the_plan_past_due_with_the_five_step_charge():
    """"Step one: the subtotal is `base_fee_cents`, plus a premium surcharge of 2,000 cents ($20.00)
    when `plan_tier` is `PREMIUM`. Step two: `service_fee_cents` is 0 when that subtotal is at least
    9,900 cents ($99.00) ... and 495 cents ($4.95) otherwise. Step three: the fee-inclusive base is
    the subtotal plus `service_fee_cents`." (PRD §3.8)

    "On a declined instrument, with `last_charge_cents` exceeding `credit_balance_cents`, the plan
    moves `ACTIVE → PAST_DUE` with `dunning_attempts` set to 1 and — importantly — `cycle_ordinal`
    **not** incremented" (PRD §3.8)

    Design: Difficulty/cross_entity_state_dependency/rollout_offer_blocked_by_past_due_subscription
    """
    env = _setup_pending_rollout_with_past_due_plan()

    plan = validate_success(api_client.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
    assert plan["status"] == "PAST_DUE", f"a declined cycle moves the plan to PAST_DUE, got {plan['status']!r}"
    assert plan["dunning_attempts"] == 1, (
        f"the first decline sets dunning_attempts to 1, got {plan['dunning_attempts']}"
    )
    assert plan["cycle_ordinal"] == 0, (
        f"a past-due episode must not advance cycle_ordinal, got {plan['cycle_ordinal']}"
    )
    assert plan["service_fee_cents"] == EXPECTED_SERVICE_FEE_CENTS, (
        "a 4900-cent STANDARD subtotal is below the 9900 waiver threshold, so service_fee_cents is "
        f"{EXPECTED_SERVICE_FEE_CENTS}, got {plan['service_fee_cents']}"
    )
    assert plan["last_charge_cents"] == EXPECTED_LAST_CHARGE_CENTS, (
        f"4900 + 495 with no loyalty discount is {EXPECTED_LAST_CHARGE_CENTS}, got {plan['last_charge_cents']}"
    )

    campaign = validate_success(api_client.get_firmware_campaign(env["campaign"]["id"], FIRMWARE_ENGINEER))
    assert campaign["status"] == "ROLLING", (
        f"the first advance moves the campaign to ROLLING, got {campaign['status']!r}"
    )
    assert campaign["is_mandatory_safety"] is False, (
        "this campaign must not be a mandatory-safety campaign, otherwise consent is overridden"
    )


def test_rollout_offer_rejected_while_the_device_plan_is_past_due():
    """"An engineer offers the update to the subscriber, moving the rollout `PENDING → OFFERED`;
    this requires the campaign to be `ROLLING`, the clock to be inside the closed maintenance
    window, and either the device's plan to be `ACTIVE` or `TRIALING` or the campaign's
    `is_mandatory_safety` to be true." (PRD §3.9)

    "The sibling entity named by the transition's precondition is in an allowed state ... This
    applies to `POST /remote-fitting-sessions/{id}/start`, `POST /firmware-rollouts/{id}/offer`,
    `POST /firmware-rollouts/{id}/install` and `POST /care-plan-subscriptions/{id}/reinstate` —
    otherwise `ERR_DEPENDENT_STATE_NOT_READY` (409)." (PRD §2.9 rule 24)

    Design: Difficulty/cross_entity_state_dependency/rollout_offer_blocked_by_past_due_subscription
    """
    env = _setup_pending_rollout_with_past_due_plan()

    resp = api_client.offer_firmware_rollout(env["rollout"]["id"], FIRMWARE_ENGINEER)
    validate_error(resp, ApiErrorId.ERR_DEPENDENT_STATE_NOT_READY.value)

    rollout = _read_rollout(env)
    assert rollout["status"] == "PENDING", (
        f"a rejected offer must leave the rollout in PENDING, got {rollout['status']!r}"
    )


def test_rollout_offer_succeeds_after_a_successful_retry_restores_the_plan():
    """"The patient drives recovery by retrying the charge with a `charge_outcome`. A succeeding
    retry moves the plan `PAST_DUE → ACTIVE`, increments `cycle_ordinal`, advances the cycle window
    and resets `dunning_attempts` to 0" (PRD §3.8)

    "An engineer offers the update to the subscriber, moving the rollout `PENDING → OFFERED`; this
    requires the campaign to be `ROLLING`, the clock to be inside the closed maintenance window, and
    either the device's plan to be `ACTIVE` or `TRIALING` or the campaign's `is_mandatory_safety` to
    be true." (PRD §3.9)

    Design: Difficulty/cross_entity_state_dependency/rollout_offer_blocked_by_past_due_subscription
    """
    env = _setup_pending_rollout_with_past_due_plan()
    patient_headers = make_patient_headers(env["patient"]["id"])

    blocked = api_client.offer_firmware_rollout(env["rollout"]["id"], FIRMWARE_ENGINEER)
    validate_error(blocked, ApiErrorId.ERR_DEPENDENT_STATE_NOT_READY.value)

    plan = validate_success(
        api_client.retry_care_plan_payment(
            env["plan"]["id"], {"charge_outcome": "SUCCEEDED"}, patient_headers
        )
    )
    assert plan["status"] == "ACTIVE", f"a succeeding retry restores ACTIVE, got {plan['status']!r}"
    assert plan["dunning_attempts"] == 0, (
        f"a succeeding retry resets dunning_attempts to 0, got {plan['dunning_attempts']}"
    )
    assert plan["cycle_ordinal"] == 1, (
        f"a succeeding retry increments cycle_ordinal to 1, got {plan['cycle_ordinal']}"
    )

    rollout = validate_success(
        api_client.offer_firmware_rollout(env["rollout"]["id"], FIRMWARE_ENGINEER)
    )
    assert rollout["status"] == "OFFERED", (
        f"the identical offer must succeed once the plan is ACTIVE again, got {rollout['status']!r}"
    )
    assert rollout["selection_rank"] == 1, (
        f"the single selected candidate ranks 1, got {rollout['selection_rank']}"
    )
    assert rollout["from_version_observed"] == "4.0.0", (
        f"from_version_observed captures the device's firmware 4.0.0, got {rollout['from_version_observed']!r}"
    )

    device = validate_success(api_client.get_device(env["assigned_device"]["id"], CARE_OPS))
    assert device["firmware_version"] == "4.0.0", (
        f"an offer installs nothing, so firmware_version stays 4.0.0, got {device['firmware_version']!r}"
    )
