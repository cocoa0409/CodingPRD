"""Lifecycle transition tests: initial states, legal edges, illegal edges, cycles and cascades.

Every scenario in this module drives one state machine described in the PRD through a
single transition and then reads back the entities the PRD says that transition touches.
"""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    COMPLIANCE,
    COMPLIANCE_2,
    FIRMWARE_ENGINEER,
    REPAIR_TECH,
    ApiErrorId,
    api_client,
    clear_referral,
    confirm_and_ship,
    create_device_payload,
    create_inventory_pool,
    create_provider,
    create_state_policy,
    enroll_care_plan,
    file_compliance_override,
    get_pool,
    get_success_data,
    issue_return_authorization,
    make_licensed_audiologist_headers,
    make_patient_headers,
    place_order,
    register_patient,
    scan_shipment,
    screen_patient,
    set_clock,
    setup_active_care_plan,
    setup_authorized_order,
    setup_delivered_order,
    setup_evaluated_referral,
    setup_placed_order,
    setup_red_flagged_patient,
    setup_return_settled,
    setup_shipped_order,
    simulate_payment,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Shared literals — the canonical CA jurisdiction, order economics and
# screening measurements every recipe in this module reuses.
# ---------------------------------------------------------------------------
_ORDER_ECONOMICS = {
    "model": "NEO",
    "dome_size": "M",
    "tip_type": "OPEN",
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}

# 200000 device subtotal + 1495 shipping + 14500 tax (200000 * 0.0725)
_ORDER_TOTAL_CENTS = 215995

_PASS_MEASUREMENTS = {
    "pure_tone_avg_db": 40.0,
    "asymmetry_db": 5.0,
    "self_reported_difficulty_score": 20,
    "speech_in_noise_pct": 70.0,
}

_STANDARD_PLAN = {
    "plan_tier": "STANDARD",
    "base_fee_cents": 9900,
    "firmware_auto_update_enabled": True,
}


def _campaign_payload(campaign_code: str, **overrides) -> dict:
    """A NEO 4.0.0 → 4.2.1 campaign payload built only from PRD-declared inputs."""
    payload = {
        "campaign_code": campaign_code,
        "model": "NEO",
        "from_version": "4.0.0",
        "to_version": "4.2.1",
        "window_start_utc": "2026-08-05T00:00:00Z",
        "window_end_utc": "2026-09-30T00:00:00Z",
        "batch_size": 1,
        "max_concurrent_installs": 5,
        "is_mandatory_safety": True,
    }
    payload.update(overrides)
    return payload


def _create_campaign(campaign_code: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_firmware_campaign(_campaign_payload(campaign_code, **overrides),
                                            FIRMWARE_ENGINEER)
    )


def _rollout_for_device(device_id: str) -> dict:
    """The single rollout targeting a device (there is no single-rollout read endpoint)."""
    rows = api_client.list_firmware_rollouts(FIRMWARE_ENGINEER,
                                             params={"device_id": device_id}).json()["data"]
    assert rows, f"expected a firmware rollout on device {device_id}"
    return rows[0]


def _assigned_device(order_id: str) -> dict:
    """The device confirm-fit assigned to an order."""
    rows = api_client.list_devices(CARE_OPS, params={"device_order_id": order_id}).json()["data"]
    assert rows, f"expected a device assigned to order {order_id}"
    return rows[0]


def _deliver_patient(policy_id: str, serial_number: str, email: str,
                     with_plan: bool = True) -> dict:
    """One extra patient carried all the way to DELIVERED against a shared policy/pool.

    The device is minted immediately before its own confirm-fit so that exactly one
    IN_STOCK unit is assignable at that moment, keeping the assignment deterministic.
    """
    get_success_data(
        api_client.create_device(create_device_payload(serial_number=serial_number), ADMIN)
    )
    patient = register_patient(policy_id, email=email)
    screen_patient(patient["id"], **_PASS_MEASUREMENTS)
    order = place_order(patient["id"], **_ORDER_ECONOMICS)
    env = {"patient": patient, "order": order}
    if with_plan:
        enroll_care_plan(env, **_STANDARD_PLAN)
    simulate_payment(order["id"])
    confirm_and_ship(order["id"])
    scan_shipment(order["id"], "DELIVERED")
    env["assigned_device"] = _assigned_device(order["id"])
    return env


# ---------------------------------------------------------------------------
# Patient and screening machines
# ---------------------------------------------------------------------------
def test_patient_initial_state_is_registered_with_zeroed_candidacy_counters():
    """PRD §3.1: "A freshly registered patient's `status` is `REGISTERED`,
    `candidacy_risk_score` is 0, `candidacy_risk_band` is `LOW`, `candidacy_risk_variant` is
    `PROVISIONAL_SELF_REPORTED`, `advisory_weight_total` is 0, `open_mandatory_flag_count` is 0,
    `lifetime_return_count` is 0, `screening_attempt_count` is 0, and both
    `waiver_acknowledged_at` and `deactivated_at` are null."

    Design: Corner/state_machines/sm_patient_initial_state_is_registered_on_creation
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy()

    resp = api_client.create_patient(
        {
            "state_policy_id": policy["id"],
            "email": "init@x.test",
            "full_name": "Init One",
            "age_years": 70,
        },
        CARE_OPS,
    )

    patient = validate_success(resp, 201)
    assert patient["status"] == "REGISTERED", "a freshly registered patient starts in REGISTERED"
    assert patient["candidacy_risk_score"] == 0, "candidacy_risk_score starts at 0"
    assert patient["candidacy_risk_band"] == "LOW", "candidacy_risk_band starts at LOW"
    assert patient["candidacy_risk_variant"] == "PROVISIONAL_SELF_REPORTED", (
        "candidacy_risk_variant starts at PROVISIONAL_SELF_REPORTED"
    )
    assert patient["open_mandatory_flag_count"] == 0, "no mandatory flag is open yet"
    assert patient["advisory_weight_total"] == 0, "advisory_weight_total starts at 0"
    assert patient["screening_attempt_count"] == 0, "no screening has been scored yet"
    assert patient["lifetime_return_count"] == 0, "lifetime_return_count starts at 0"
    assert patient["waiver_acknowledged_at"] is None, "waiver_acknowledged_at starts null"
    assert patient["deactivated_at"] is None, "deactivated_at starts null"


def test_screening_draft_moves_to_in_progress_when_measurements_are_recorded():
    """PRD §3.2: "Starting one from `REGISTERED` requires that the patient's governing policy
    is not retired, moves the patient from `REGISTERED` to `SCREENING_IN_PROGRESS`, and creates
    a `ScreeningSession` in `DRAFT` with `attempt_ordinal` 1." PRD §3.2: "Filling in a draft
    records five measurements and moves the session from `DRAFT` to `IN_PROGRESS`". PRD §3.2:
    "The session's `screening_outcome` — `PENDING` until scoring".

    Design: Corner/state_machines/sm_screening_draft_to_in_progress_on_patch
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy()
    patient = register_patient(policy["id"], email="vt@x.test", full_name="Vt One")
    headers = make_patient_headers(patient["id"])
    session = get_success_data(api_client.start_screening_session(patient["id"], {}, headers))

    resp = api_client.update_screening_session(
        session["id"],
        dict(_PASS_MEASUREMENTS, symptom_codes=[]),
        headers,
    )

    updated = validate_success(resp, 200)
    assert updated["status"] == "IN_PROGRESS", "a measured draft moves DRAFT -> IN_PROGRESS"
    assert updated["pure_tone_avg_db"] == 40.0, "pure_tone_avg_db is stored as supplied"
    assert updated["asymmetry_db"] == 5.0, "asymmetry_db is stored as supplied"
    assert updated["self_reported_difficulty_score"] == 20, "difficulty score is stored"
    assert updated["speech_in_noise_pct"] == 70.0, "speech_in_noise_pct is stored as supplied"
    assert updated["screening_outcome"] == "PENDING", "the outcome stays PENDING until scoring"
    assert updated["version"] == 2, "the mutation increments the session's version to 2"

    parent = get_success_data(api_client.get_patient(patient["id"], CARE_OPS))
    assert parent["status"] == "SCREENING_IN_PROGRESS", (
        "the patient sits in SCREENING_IN_PROGRESS from the create call"
    )


def test_red_flag_retake_submit_runs_every_medical_hold_hop():
    """PRD §2.8: "**The medical-hold cascade** fires when a scored screening drives a patient
    into `REFERRAL_REQUIRED`. Hop 1 opens a `ProviderReferral` in `OPEN`. Hop 2 moves every
    `DeviceOrder` of that patient whose `fulfillment_status` is `PENDING_FIT_CONFIRM` or
    `READY_TO_SHIP` to `MEDICAL_HOLD` with `medical_hold_reason` set to `MANDATORY_RED_FLAG`.
    Hop 3 moves every `RemoteFittingSession` in `SCHEDULED` whose `session_type` is
    `INITIAL_FIT` or `FOLLOW_UP` and which references one of those orders to `CANCELLED`, with
    `no_show_charged_cents` forced to 0 — a medical hold never costs the patient a fee. Hop 4
    recomputes `booked_minutes_on_focus_date` and `utilization_pct` for every provider whose
    bookings hop 3 released." PRD §3.3: "the `CANDIDATE_APPROVED` origin additionally marks the
    superseded session `INVALIDATED` with reason `SUPERSEDED`". PRD §3.3: "computing `expires_at`
    as `issued_at` plus the patient's policy `referral_validity_days` days".

    Design: Corner/state_machines/sm_patient_red_flag_submit_runs_cascade_b_all_four_hops
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy()
    provider = create_provider(
        provider_type="TELECARE_FITTER", npi="1000000002", full_name="Fit One",
    )
    patient = register_patient(policy["id"], email="cas@x.test", full_name="Cas One")
    headers = make_patient_headers(patient["id"])
    first = screen_patient(patient["id"], **_PASS_MEASUREMENTS)
    order = place_order(patient["id"], **_ORDER_ECONOMICS)
    session = get_success_data(
        api_client.create_remote_fitting_session(
            {
                "patient_id": patient["id"],
                "session_type": "INITIAL_FIT",
                "scheduled_start_utc": "2026-08-10T10:00:00Z",
                "scheduled_end_utc": "2026-08-10T10:30:00Z",
                "provider_id": provider["id"],
                "device_order_id": order["id"],
            },
            headers,
        )
    )
    retake = get_success_data(
        api_client.start_screening_session(
            patient["id"], {"supersedes_session_id": first["id"]}, headers
        )
    )
    get_success_data(
        api_client.update_screening_session(
            retake["id"], dict(_PASS_MEASUREMENTS, symptom_codes=["SUDDEN_LOSS"]), headers
        )
    )

    resp = api_client.submit_screening_session(retake["id"], headers)

    scored = validate_success(resp, 200)
    assert scored["screening_outcome"] == "RED_FLAG", "a mandatory symptom scores RED_FLAG"

    reread = get_success_data(api_client.get_patient(patient["id"], CARE_OPS))
    assert reread["status"] == "REFERRAL_REQUIRED", "a RED_FLAG drives the patient to REFERRAL_REQUIRED"
    assert reread["open_mandatory_flag_count"] == 1, "the mandatory finding is open"

    superseded = get_success_data(api_client.get_screening_session(first["id"], CARE_OPS))
    assert superseded["status"] == "INVALIDATED", "the superseded session is invalidated"
    assert superseded["invalidated_reason"] == "SUPERSEDED", "with reason SUPERSEDED"

    # hop 1
    referrals, meta = validate_paginated(
        api_client.list_provider_referrals(CARE_OPS, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 1, "hop 1 opens exactly one referral"
    assert referrals[0]["status"] == "OPEN", "hop 1 opens the referral in OPEN"
    assert referrals[0]["expires_at"].startswith("2027-01-28T00:00:00"), (
        "expires_at is issued_at 2026-08-01 plus the policy's 180 validity days"
    )

    # hop 2
    held = get_success_data(api_client.get_device_order(order["id"], CARE_OPS))
    assert held["fulfillment_status"] == "MEDICAL_HOLD", "hop 2 holds the pending order"
    assert held["medical_hold_reason"] == "MANDATORY_RED_FLAG", "with reason MANDATORY_RED_FLAG"
    assert held["payment_status"] == "PENDING_AUTH", "the payment dimension is untouched"

    # hop 3
    cancelled = get_success_data(api_client.get_remote_fitting_session(session["id"], CARE_OPS))
    assert cancelled["status"] == "CANCELLED", "hop 3 cancels the scheduled fitting session"
    assert cancelled["no_show_charged_cents"] == 0, "a medical hold never costs the patient a fee"

    # hop 4
    released = get_success_data(api_client.get_provider(provider["id"], CARE_OPS))
    assert released["booked_minutes_on_focus_date"] == 0, "hop 4 releases the booked minutes"
    assert released["utilization_pct"] == 0, "hop 4 recomputes utilization_pct"


# ---------------------------------------------------------------------------
# DeviceOrder: two independent dimensions
# ---------------------------------------------------------------------------
def test_order_payment_authorization_moves_no_cash():
    """PRD §3.5: "An authorization outcome moves `PENDING_AUTH → AUTHORIZED` with no cash
    movement, leaving `captured_cents` at 0." PRD §2.6: "`open_balance_cents` is defined as
    `captured_cents` minus `refunded_cents` minus `retained_cents`."

    Design: Corner/state_machines/sm_order_payment_pending_auth_to_authorized
    """
    env = setup_placed_order(order_overrides=_ORDER_ECONOMICS, measurements=_PASS_MEASUREMENTS)

    resp = api_client.simulate_payment(
        {"device_order_id": env["order"]["id"], "outcome": "AUTHORIZED"}, ADMIN
    )

    order = validate_success(resp, 200)
    assert order["payment_status"] == "AUTHORIZED", "the payment dimension reaches AUTHORIZED"
    assert order["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
        "the fulfillment dimension is untouched by the authorization"
    )
    assert order["total_cents"] == _ORDER_TOTAL_CENTS, (
        "200000 device subtotal plus 1495 shipping plus 14500 tax"
    )
    assert order["captured_cents"] == 0, "an authorization captures nothing"
    assert order["refunded_cents"] == 0, "nothing has been refunded"
    assert order["retained_cents"] == 0, "nothing has been retained"
    assert order["open_balance_cents"] == 0, "captured minus refunded minus retained is 0"


def test_order_confirm_fit_reserves_a_unit_and_assigns_a_device():
    """PRD §3.5: "Confirmation moves the fulfillment dimension `PENDING_FIT_CONFIRM →
    READY_TO_SHIP`, reserves a unit by decrementing that pool's `on_hand_units` by one and
    incrementing its `reserved_units` by one, assigns an `IN_STOCK` device of the same model by
    moving that device to `ASSIGNED` and writing the order's identity into the device's
    `device_order_id`, and increments the order's `version` by one." PRD §2.6: "every
    `InventoryPool` satisfies an **inventory-conservation identity**: `on_hand_units` plus
    `reserved_units` plus `dispatched_units` always equals `total_units_received`."

    Design: Corner/state_machines/sm_order_confirm_fit_reserves_inventory_and_assigns_device
    """
    env = setup_authorized_order(order_overrides=_ORDER_ECONOMICS,
                                measurements=_PASS_MEASUREMENTS)
    device_id = env["devices"][0]["id"]
    version_before = get_success_data(
        api_client.get_device_order(env["order"]["id"], CARE_OPS)
    )["version"]

    resp = api_client.confirm_fit(env["order"]["id"], CARE_OPS)

    order = validate_success(resp, 200)
    assert order["fulfillment_status"] == "READY_TO_SHIP", "confirm-fit clears the order for shipment"

    pool = get_pool(env["pool"]["id"])
    assert pool["on_hand_units"] == 4, "one of the five on-hand units is reserved away"
    assert pool["reserved_units"] == 1, "the reserved counter takes that unit"
    assert pool["dispatched_units"] == 0, "nothing has been dispatched yet"
    assert pool["total_units_received"] == 5, "the conserved pool total is unchanged"
    assert (pool["on_hand_units"] + pool["reserved_units"] + pool["dispatched_units"]
            == pool["total_units_received"]), "inventory conservation holds after confirm-fit"

    device = get_success_data(api_client.get_device(device_id, CARE_OPS))
    assert device["status"] == "ASSIGNED", "the IN_STOCK unit is flipped to ASSIGNED"
    assert device["device_order_id"] == env["order"]["id"], "the order's identity is written on it"

    reread = get_success_data(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert reread["version"] == version_before + 1, "confirm-fit increments the order's version by one"


def test_order_parallel_dimensions_advance_independently():
    """PRD §3.5: "An order carries **two independent state dimensions on the same row**, and
    they advance under separate triggers." PRD §3.5: "Confirmation moves the fulfillment
    dimension `PENDING_FIT_CONFIRM → READY_TO_SHIP`". PRD §3.5: "An authorization outcome moves
    `PENDING_AUTH → AUTHORIZED` with no cash movement, leaving `captured_cents` at 0."

    Design: Corner/state_machines/sm_order_parallel_dimensions_advance_independently
    """
    env = setup_authorized_order(order_overrides=_ORDER_ECONOMICS,
                                measurements=_PASS_MEASUREMENTS)
    assert env["order"]["payment_status"] == "AUTHORIZED", (
        "the payment leg reaches AUTHORIZED while fulfillment is still PENDING_FIT_CONFIRM"
    )
    assert env["order"]["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
        "the fulfillment leg has not moved yet"
    )

    resp = api_client.confirm_fit(env["order"]["id"], CARE_OPS)

    order = validate_success(resp, 200)
    assert order["payment_status"] == "AUTHORIZED", (
        "the fulfillment transition leaves the payment dimension alone"
    )
    assert order["fulfillment_status"] == "READY_TO_SHIP", "only fulfillment advanced"
    assert order["captured_cents"] == 0, "no cash moved on a fulfillment transition"
    assert order["medical_hold_reason"] is None, "the order was never held"


def test_order_second_ship_call_is_rejected_and_captures_nothing_twice():
    """PRD §2.9 rule 22: "The targeted entity's current state is a declared origin state for the
    requested transition, on every action endpoint that drives a state transition — otherwise
    `ERR_INVALID_STATE` (409)." PRD §3.5: "It moves fulfillment `READY_TO_SHIP → SHIPPED` and
    payment `AUTHORIZED → CAPTURED`, sets `captured_cents` to `total_cents` with
    `refunded_cents` and `retained_cents` at 0 and `open_balance_cents` equal to `total_cents`,
    stamps the device's `shipped_at` from the logical clock and sets its `warranty_expires_at` to
    `shipped_at` plus 730 days (two years), moves the reserved unit onward by decrementing
    `reserved_units` and incrementing `dispatched_units`".

    Design: Corner/state_machines/sm_order_ship_second_call_is_invalid_state
    """
    env = setup_shipped_order(order_overrides=_ORDER_ECONOMICS, measurements=_PASS_MEASUREMENTS)

    resp = api_client.ship_device_order(env["order"]["id"], CARE_OPS)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    order = get_success_data(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["fulfillment_status"] == "SHIPPED", "the refused call leaves fulfillment at SHIPPED"
    assert order["payment_status"] == "CAPTURED", "and payment at CAPTURED"
    assert order["captured_cents"] == _ORDER_TOTAL_CENTS, "the total is captured exactly once"
    assert order["open_balance_cents"] == _ORDER_TOTAL_CENTS, "the open balance is the whole total"

    pool = get_pool(env["pool"]["id"])
    assert pool["on_hand_units"] == 4, "the on-hand count is untouched by the refused call"
    assert pool["reserved_units"] == 0, "the reservation moved onward exactly once"
    assert pool["dispatched_units"] == 1, "exactly one unit is dispatched"

    device = _assigned_device(env["order"]["id"])
    assert device["warranty_expires_at"].startswith("2028-07-31T00:00:00"), (
        "warranty_expires_at is the 2026-08-01 shipment plus 730 days"
    )


def test_order_cancel_from_delivered_is_refused_and_leaves_the_trial_running():
    """PRD §3.5: "Cancelling an unshipped order is available to a care operator with an optional
    `reason_note`. From `PENDING_FIT_CONFIRM` it requires `payment_status` to be `PENDING_AUTH`
    or `AUTHORIZED` and simply voids the authorization with no inventory movement." PRD §2.9
    rule 22: "The targeted entity's current state is a declared origin state for the requested
    transition, on every action endpoint that drives a state transition — otherwise
    `ERR_INVALID_STATE` (409)." PRD §3.5: "A carrier scan against a named `device_order_id` with
    an `event` of `DELIVERED` moves fulfillment `SHIPPED → DELIVERED`, stamps `delivered_at`,
    sets the device to `WITH_PATIENT`, creates the trial period described in §3.6 in `ACTIVE`".

    Design: Corner/state_machines/sm_order_cancel_from_delivered_is_invalid_transition
    """
    env = setup_delivered_order(order_overrides=_ORDER_ECONOMICS, measurements=_PASS_MEASUREMENTS)

    resp = api_client.cancel_device_order(
        env["order"]["id"], {"reason_note": "patient changed mind"}, CARE_OPS
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    order = get_success_data(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["fulfillment_status"] == "DELIVERED", "DELIVERED has no cancel edge"
    assert order["payment_status"] == "CAPTURED", "the payment dimension is untouched"

    trials, meta = validate_paginated(
        api_client.list_trial_periods(CARE_OPS, params={"device_order_id": env["order"]["id"]})
    )
    assert meta["total_count"] == 1, "delivery created exactly one trial period"
    assert trials[0]["status"] == "ACTIVE", "the refused cancel does not touch the running trial"


# ---------------------------------------------------------------------------
# Trial, referral, warranty and repair machines
# ---------------------------------------------------------------------------
def test_trial_extension_is_refused_once_the_return_is_settled():
    """PRD §3.6: "The trial lifecycle admits `ACTIVE`, `PAUSED`, `RETURN_INITIATED`,
    `RETURN_SETTLED`, `EXPIRED_KEPT` and `VOIDED`, of which the last three are terminal."
    PRD §3.6: "A care operator may grant goodwill days by adding a supplied `extension_days`
    count to `extension_days_granted`, which must stay between 0 and 30 inclusive; the grant
    recomputes `effective_end_utc` and increments the trial's `version` by one, and it is
    refused with `ERR_TRIAL_WINDOW_CLOSED` once the clock has passed `effective_end_utc`."
    PRD §2.9 rule 22: "The targeted entity's current state is a declared origin state for the
    requested transition, on every action endpoint that drives a state transition — otherwise
    `ERR_INVALID_STATE` (409)." PRD §2.9: "When a single request violates more than one rule,
    the rule with the lowest priority number below wins and its error is the one returned."

    Design: Corner/state_machines/sm_trial_return_settled_is_terminal_and_rejects_extend
    """
    env = setup_return_settled(
        inspection_grade="RESELLABLE",
        at_iso="2026-08-11T00:00:00Z",
        order_overrides=_ORDER_ECONOMICS,
        measurements=_PASS_MEASUREMENTS,
    )

    resp = api_client.extend_trial_period(env["trial"]["id"], {"extension_days": 10}, CARE_OPS)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    trial = get_success_data(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert trial["status"] == "RETURN_SETTLED", "a settled trial is terminal and cannot reopen"
    assert trial["extension_days_granted"] == 0, "no goodwill days were granted"


def test_referral_returns_to_open_after_a_no_show_on_its_evaluation_slot():
    """PRD §3.3: "Should the evaluation appointment collapse — a no-show or a cancellation — the
    referral cycles `SCHEDULED → OPEN`, incrementing `reschedule_count` and clearing
    `provider_id` so a different audiologist may be booked." PRD §3.4:
    "Recording a no-show requires the clock to be at or after `scheduled_end_utc` and the
    session to be `SCHEDULED`; it moves the session `SCHEDULED → NO_SHOW` and sets
    `no_show_charged_cents` to 2,500 cents (twenty-five dollars) when the patient holds a plan
    whose `status` is `ACTIVE` or `PAST_DUE`, and to 0 otherwise."

    Design: Corner/state_machines/sm_referral_reschedule_cycle_open_scheduled_open
    """
    env = setup_red_flagged_patient(measurements=_PASS_MEASUREMENTS)
    provider = create_provider(npi="1000000003", full_name="Aud Two")
    session = get_success_data(
        api_client.create_remote_fitting_session(
            {
                "patient_id": env["patient"]["id"],
                "session_type": "REFERRAL_EVALUATION",
                "scheduled_start_utc": "2026-08-05T09:00:00Z",
                "scheduled_end_utc": "2026-08-05T09:30:00Z",
                "provider_id": provider["id"],
                "provider_referral_id": env["referral"]["id"],
            },
            make_patient_headers(env["patient"]["id"]),
        )
    )
    booked = get_success_data(api_client.get_provider_referral(env["referral"]["id"], CARE_OPS))
    assert booked["status"] == "SCHEDULED", "booking the evaluation moves the referral to SCHEDULED"
    set_clock("2026-08-05T09:31:00Z")

    resp = api_client.no_show_fitting_session(
        session["id"], make_licensed_audiologist_headers(provider["id"])
    )

    marked = validate_success(resp, 200)
    assert marked["status"] == "NO_SHOW", "the absent patient's session lands in NO_SHOW"
    assert marked["no_show_charged_cents"] == 0, "the patient holds no care plan, so nothing is charged"

    referral = get_success_data(api_client.get_provider_referral(env["referral"]["id"], CARE_OPS))
    assert referral["status"] == "OPEN", "the referral cycles back to OPEN and is bookable again"
    assert referral["reschedule_count"] == 1, "the reschedule counter records the lost slot"
    assert referral["provider_id"] is None, "the provider is released from the referral"

    reread = get_success_data(api_client.get_provider(provider["id"], CARE_OPS))
    assert reread["booked_minutes_on_focus_date"] == 0, "the 30-minute booking is released"


def test_warranty_replace_and_repair_decisions_have_disjoint_side_effects():
    """PRD §3.7: "A `REPLACE` decision moves the claim `TRIAGED → APPROVED_REPLACEMENT`... The
    replace branch mints a new device in `IN_STOCK`, assigns it to the same `device_order_id`,
    writes the new unit's identity into the old device's `replaced_by_device_id` and moves the old
    device to `REPLACED`... and writes `replacement_device_id` on the claim." PRD §3.7: "A
    `REPAIR` decision moves the claim `TRIAGED → APPROVED_REPAIR`... The repair branch creates a
    new repair in `KIT_REQUESTED` for the same device, copying `fault_code` from the originating
    repair or using `PHYSICAL_DAMAGE` for a damage claim, and leaves `replacement_device_id` null
    — no replacement unit is minted." PRD §3.7: "`deductible_cents` is the base of 9,900 cents
    ($99.00) multiplied by the age multiplier and by the kind factor, rounded half up, with the
    integer surcharge added afterwards".

    Design: Corner/state_machines/sm_warranty_decide_replace_and_repair_branches_diverge
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy()
    create_inventory_pool(restock_units=5, sku="NEO-M-OPEN")

    first = _deliver_patient(policy["id"], "SN-BR01", "br1@x.test", with_plan=False)
    device_a = first["assigned_device"]["id"]
    claim_a = get_success_data(
        api_client.create_warranty_claim(
            {"device_id": device_a, "claim_kind": "DAMAGE"},
            make_patient_headers(first["patient"]["id"]),
        )
    )
    get_success_data(api_client.triage_warranty_claim(claim_a["id"], REPAIR_TECH))

    second = _deliver_patient(policy["id"], "SN-BR02", "br2@x.test", with_plan=False)
    device_b = second["assigned_device"]["id"]
    claim_b = get_success_data(
        api_client.create_warranty_claim(
            {"device_id": device_b, "claim_kind": "DAMAGE"},
            make_patient_headers(second["patient"]["id"]),
        )
    )
    get_success_data(api_client.triage_warranty_claim(claim_b["id"], REPAIR_TECH))
    get_success_data(
        api_client.decide_warranty_claim(claim_a["id"], {"decision": "REPLACE"}, COMPLIANCE)
    )

    resp = api_client.decide_warranty_claim(claim_b["id"], {"decision": "REPAIR"}, COMPLIANCE)

    decided = validate_success(resp, 200)
    assert decided["status"] == "APPROVED_REPAIR", "the REPAIR branch lands in APPROVED_REPAIR"
    assert decided["replacement_device_id"] is None, "the repair branch mints no replacement unit"
    assert decided["deductible_cents"] == 3713, (
        "9900 base times the 0.5 age multiplier times the 0.75 DAMAGE factor, half up"
    )

    repairs_b, meta_b = validate_paginated(
        api_client.list_repair_orders(REPAIR_TECH, params={"device_id": device_b})
    )
    assert meta_b["total_count"] == 1, "the repair branch creates exactly one repair"
    assert repairs_b[0]["status"] == "KIT_REQUESTED", "that repair opens in KIT_REQUESTED"

    replaced_claim = get_success_data(api_client.get_warranty_claim(claim_a["id"], COMPLIANCE))
    assert replaced_claim["status"] == "APPROVED_REPLACEMENT", "the REPLACE branch is unaffected"
    assert replaced_claim["replacement_device_id"] is not None, "the replace branch minted a unit"

    old_device = get_success_data(api_client.get_device(device_a, CARE_OPS))
    assert old_device["status"] == "REPLACED", "the replaced unit leaves the patient's hands"
    assert old_device["replaced_by_device_id"] is not None, "the successor is recorded on it"

    _, meta_a = validate_paginated(
        api_client.list_repair_orders(REPAIR_TECH, params={"device_id": device_a})
    )
    assert meta_a["total_count"] == 0, "the replace branch never creates a repair"


def test_repair_closure_posts_the_sla_credit_to_the_linked_plan():
    """PRD §3.7: "`sla_days` is 5 when a plan is linked whose `plan_tier` is `PREMIUM`, 10 when
    the linked plan's tier is `STANDARD`, and 15 when there is no plan at all". PRD §3.7: "Branch
    A closes by returning the unit, moving `REPAIRED → RETURNED_TO_PATIENT`. Closure stamps
    `closed_at`, computes `turnaround_days` and `sla_credit_cents`, credits the linked plan's
    `credit_balance_cents` by the credit amount when a plan exists, sets the device back to
    `WITH_PATIENT`, and — when this repair paused the trial — drives the trial `PAUSED →
    ACTIVE`". PRD §3.7: "`sla_credit_cents` is the days over multiplied by 500 cents per day and
    by that multiplier, rounded half up, and then capped at 5,000 cents ($50.00)".

    Design: Corner/state_machines/sm_repair_return_to_patient_syncs_sla_credit_to_plan_ledger
    """
    env = setup_delivered_order(order_overrides=_ORDER_ECONOMICS, measurements=_PASS_MEASUREMENTS)
    plan = enroll_care_plan(env, **_STANDARD_PLAN)
    set_clock("2026-08-05T00:00:00Z")
    repair = get_success_data(
        api_client.create_repair_order(
            {"device_id": env["assigned_device"]["id"], "fault_code": "INTERMITTENT"}, CARE_OPS
        )
    )
    get_success_data(api_client.send_repair_kit(repair["id"], CARE_OPS))
    get_success_data(api_client.receive_repair_order(repair["id"], REPAIR_TECH))
    set_clock("2026-08-18T00:00:00Z")
    get_success_data(api_client.start_repair_order(repair["id"], REPAIR_TECH))
    get_success_data(
        api_client.resolve_repair_order(repair["id"], {"resolution": "REPAIRED"}, REPAIR_TECH)
    )

    resp = api_client.return_repair_to_patient(repair["id"], REPAIR_TECH)

    closed = validate_success(resp, 200)
    assert closed["status"] == "RETURNED_TO_PATIENT", "branch A closes by returning the unit"
    assert closed["sla_days"] == 10, "a linked STANDARD plan sets the SLA at 10 days"
    assert closed["turnaround_days"] == 13, "2026-08-05 to 2026-08-18 is 13 whole days"
    assert closed["sla_credit_cents"] == 1500, "three days over at 500 cents per day"
    assert closed["closed_at"].startswith("2026-08-18T00:00:00"), "closed_at is stamped from the clock"
    assert closed["pauses_trial"] is True, "the running trial made this repair a pausing repair"

    reread_plan = get_success_data(api_client.get_care_plan_subscription(plan["id"], CARE_OPS))
    assert reread_plan["credit_balance_cents"] == 1500, (
        "the credit is posted to the linked plan's ledger in the same call"
    )

    device = get_success_data(api_client.get_device(env["assigned_device"]["id"], CARE_OPS))
    assert device["status"] == "WITH_PATIENT", "the unit goes back to the patient"

    trial = get_success_data(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert trial["status"] == "ACTIVE", "the paused trial resumes on closure"


# ---------------------------------------------------------------------------
# Return settlement, void and waiver
# ---------------------------------------------------------------------------
def test_return_settlement_lands_every_hop_of_its_cascade():
    """PRD §2.8: "**The return-settlement cascade** fires when a care operator settles an
    inspected return authorization. Hop 1 moves the `TrialPeriod` from `RETURN_INITIATED` to
    `RETURN_SETTLED` and increments `Patient.lifetime_return_count`. Hop 2 moves the
    `DeviceOrder`'s `fulfillment_status` to `RETURNED` and its `payment_status` to either
    `PARTIALLY_REFUNDED` or `REFUNDED`, updating `refunded_cents`, `retained_cents` and
    `open_balance_cents`. Hop 3 sets the `Device.status` to `RETIRED` while retaining its
    `device_order_id` for audit. Hop 4 moves every `CarePlanSubscription` attached to that order
    to `CANCELLED` and forfeits its `credit_balance_cents` by setting it to zero. Hop 5 moves
    every `FirmwareRollout` on that device whose status is `PENDING` or `OFFERED` to
    `CANCELLED_INELIGIBLE` and recomputes the owning campaign's `rollout_count`,
    `installed_count` and `failure_rate_pct`." PRD §2.6: "every `DeviceOrder` satisfies a
    **cash-conservation identity**".

    Design: Corner/state_machines/sm_return_settle_runs_cascade_a_all_five_hops
    """
    env = setup_active_care_plan(
        plan_overrides=_STANDARD_PLAN,
        order_overrides=_ORDER_ECONOMICS,
        measurements=_PASS_MEASUREMENTS,
    )
    device_id = env["assigned_device"]["id"]
    set_clock("2026-08-05T00:00:00Z")
    campaign = _create_campaign("CAMP-CASCADE")
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    get_success_data(api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    rollout = _rollout_for_device(device_id)
    assert rollout["status"] == "PENDING", "the cohort selection leaves the rollout PENDING"

    issue_return_authorization(env, at_iso="2026-08-11T00:00:00Z")
    scan_shipment(env["order"]["id"], "RETURN_PICKED_UP")
    get_success_data(api_client.receive_return_authorization(env["rma"]["id"], CARE_OPS))
    get_success_data(
        api_client.inspect_return_authorization(
            env["rma"]["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
        )
    )

    resp = api_client.settle_return_authorization(env["rma"]["id"], CARE_OPS)

    rma = validate_success(resp, 200)
    assert rma["status"] == "REFUND_SETTLED", "settlement closes the authorization"
    assert rma["restocking_variant"] == "FLAT_PCT", "the CA policy charges a flat percentage"
    assert rma["restocking_fee_cents"] == 20000, "10 percent of the 200000 device component"
    assert rma["non_refundable_shipping_cents"] == 1495, "the policy does not refund shipping"
    assert rma["refund_amount_cents"] == 194500, "215995 less 20000 restocking less 1495 shipping"

    trial = get_success_data(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert trial["status"] == "RETURN_SETTLED", "hop 1 settles the trial"
    assert trial["days_used"] == 10, "2026-08-01 to 2026-08-11 is 10 trial days"

    patient = get_success_data(api_client.get_patient(env["patient"]["id"], CARE_OPS))
    assert patient["lifetime_return_count"] == 1, "hop 1 counts the return against the patient"

    order = get_success_data(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["fulfillment_status"] == "RETURNED", "hop 2 returns the order"
    assert order["payment_status"] == "PARTIALLY_REFUNDED", "a fee was retained, so only part refunds"
    assert order["refunded_cents"] == 194500, "the refund is booked on the order"
    assert order["retained_cents"] == 21495, "20000 restocking plus 1495 shipping is retained"
    assert (order["captured_cents"] - order["refunded_cents"] - order["retained_cents"]
            == order["open_balance_cents"]), "cash conservation holds after settlement"
    assert order["open_balance_cents"] == 0, "the captured amount is fully disposed of"

    device = get_success_data(api_client.get_device(device_id, CARE_OPS))
    assert device["status"] == "RETIRED", "hop 3 retires the returned unit"
    assert device["device_order_id"] == env["order"]["id"], "the order link is retained for audit"

    plan = get_success_data(api_client.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
    assert plan["status"] == "CANCELLED", "hop 4 cancels the attached plan"
    assert plan["credit_balance_cents"] == 0, "hop 4 forfeits any plan credit"

    cancelled_rollout = _rollout_for_device(device_id)
    assert cancelled_rollout["status"] == "CANCELLED_INELIGIBLE", "hop 5 cancels the pending rollout"

    reread_campaign = get_success_data(
        api_client.get_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert reread_campaign["installed_count"] == 0, "hop 5 recomputes the campaign counters"


def test_voiding_a_return_authorization_reactivates_the_trial_without_moving_cash():
    """PRD §3.6: "A care operator may void an `ISSUED` authorization with an optional
    `reason_note`, which is a compensating action: the authorization becomes `VOIDED` with
    `restocking_fee_cents` and `refund_amount_cents` set to 0, the trial reverts
    `RETURN_INITIATED → ACTIVE` (which requires the clock still to be at or before
    `effective_end_utc`), the trial's `version` increments, and the order's cash-conservation
    identity is exactly what it was before the issue." PRD §2.4: "`version`, an integer that starts at 1 when the
    row is created and increments by one on every mutation of that row." PRD §2.8: "a cascade that
    mutates a second resource refreshes that second resource's `updated_at` and increments its
    `version` too".

    Design: Corner/state_machines/sm_return_authorization_void_reverts_trial_without_cash_drift
    """
    env = setup_delivered_order(order_overrides=_ORDER_ECONOMICS, measurements=_PASS_MEASUREMENTS)
    issue_return_authorization(env, at_iso="2026-08-11T00:00:00Z")

    resp = api_client.void_return_authorization(
        env["rma"]["id"], {"reason_note": "patient kept the device"}, CARE_OPS
    )

    rma = validate_success(resp, 200)
    assert rma["status"] == "VOIDED", "the authorization is voided"

    trial = get_success_data(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert trial["status"] == "ACTIVE", "the trial reverts to ACTIVE"
    assert trial["version"] == 3, (
        "1 at creation, 2 on the return authorization and 3 on the void"
    )

    order = get_success_data(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["fulfillment_status"] == "DELIVERED", "the order is untouched by the void"
    assert order["payment_status"] == "CAPTURED", "the payment dimension is untouched"
    assert order["captured_cents"] == _ORDER_TOTAL_CENTS, "the captured amount is unchanged"
    assert order["refunded_cents"] == 0, "no cash moved on the way in or out"
    assert order["retained_cents"] == 0, "nothing was retained"

    patient = get_success_data(api_client.get_patient(env["patient"]["id"], CARE_OPS))
    assert patient["lifetime_return_count"] == 0, "an abandoned return is not counted"


def test_waiving_restocking_lifts_a_settled_return_to_a_full_refund():
    """PRD §3.6: "A compliance officer may afterwards waive retained restocking, optionally
    with a `reason_note`, provided the settled authorization's `restocking_fee_cents` is above 0
    and the clock is within 30 days of `settled_at`." PRD §3.6: "This compensating action moves
    the payment dimension `PARTIALLY_REFUNDED → REFUNDED`, refunding the retained amount so that
    `refunded_cents` equals `captured_cents`, `retained_cents` becomes 0 and `open_balance_cents`
    becomes 0, and rewriting the authorization's `restocking_variant` to `WAIVED` with
    `restocking_fee_cents` and `non_refundable_shipping_cents` set to 0 and `refund_amount_cents`
    set to `captured_cents`." PRD §2.6: "every `DeviceOrder` satisfies a
    **cash-conservation identity**".

    Design: Corner/state_machines/sm_waive_restocking_compensates_settled_return_to_full_refund
    """
    env = setup_return_settled(
        inspection_grade="RESELLABLE",
        at_iso="2026-08-11T00:00:00Z",
        order_overrides=_ORDER_ECONOMICS,
        measurements=_PASS_MEASUREMENTS,
    )
    assert env["rma"]["refund_amount_cents"] == 194500, "the settlement retained 21495 before the waiver"
    set_clock("2026-08-20T00:00:00Z")

    resp = api_client.waive_restocking(env["rma"]["id"], {"reason_note": "goodwill"}, COMPLIANCE)

    rma = validate_success(resp, 200)
    assert rma["restocking_variant"] == "WAIVED", "the waiver rewrites the settlement variant"
    assert rma["restocking_fee_cents"] == 0, "the restocking fee is zeroed"
    assert rma["non_refundable_shipping_cents"] == 0, "the shipping retention is zeroed"
    assert rma["refund_amount_cents"] == _ORDER_TOTAL_CENTS, "the refund rises to the full capture"

    order = get_success_data(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["payment_status"] == "REFUNDED", "the order becomes fully refunded"
    assert order["refunded_cents"] == _ORDER_TOTAL_CENTS, "the whole capture is refunded"
    assert order["retained_cents"] == 0, "nothing is retained after the waiver"
    assert order["captured_cents"] == _ORDER_TOTAL_CENTS, "the capture itself never changes"
    assert (order["captured_cents"] - order["refunded_cents"] - order["retained_cents"]
            == order["open_balance_cents"]), "cash conservation holds after the waiver"

    trial = get_success_data(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert trial["status"] == "RETURN_SETTLED", "the waiver does not un-settle the trial"


# ---------------------------------------------------------------------------
# Care plan billing machine
# ---------------------------------------------------------------------------
def test_successive_billing_cycles_re_enter_active_and_advance_the_ordinal():
    """PRD §3.8: "On success the plan self-loops `ACTIVE → ACTIVE`: the five-step computation
    writes `service_fee_cents`, `loyalty_discount_cents` and `last_charge_cents`, credit is
    consumed, `cycle_ordinal` increments, `cycle_start_utc` advances to the old `cycle_end_utc`
    and `cycle_end_utc` becomes the new `cycle_start_utc` plus 30 days." PRD §3.8: "Step two:
    `service_fee_cents` is 0 when that subtotal is at least 9,900 cents ($99.00)". PRD §3.8: "the
    loyalty rate is 0.15 when `cycle_ordinal` is at least 12, otherwise 0.10 when `cycle_ordinal`
    is at least 6, otherwise 0.0".

    Design: Corner/state_machines/sm_care_plan_billing_self_loop_advances_cycle_ordinal
    """
    env = setup_active_care_plan(
        plan_overrides={"plan_tier": "STANDARD", "base_fee_cents": 9900},
        order_overrides=_ORDER_ECONOMICS,
        measurements=_PASS_MEASUREMENTS,
    )
    assert env["plan"]["status"] == "ACTIVE", "delivery of the attached order activates the plan"
    set_clock("2026-09-01T00:00:00Z")
    first = get_success_data(
        api_client.run_billing_cycle(env["plan"]["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN)
    )
    assert first["cycle_ordinal"] == 1, "the first successful cycle advances the ordinal to 1"
    set_clock("2026-10-01T00:00:00Z")

    resp = api_client.run_billing_cycle(env["plan"]["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN)

    plan = validate_success(resp, 200)
    assert plan["status"] == "ACTIVE", "the billing self-loop re-enters ACTIVE"
    assert plan["cycle_ordinal"] == 2, "a second successful cycle advances the ordinal to 2"
    assert plan["last_charge_cents"] == 9900, (
        "9900 waives the service fee and ordinal 2 earns no loyalty discount"
    )
    assert plan["service_fee_cents"] == 0, "a subtotal of exactly 9900 waives the fee"
    assert plan["loyalty_discount_cents"] == 0, "the loyalty rate below six cycles is 0.0"
    assert plan["dunning_attempts"] == 0, "a successful cycle leaves no dunning state"
    assert plan["credit_balance_cents"] == 0, "there was no credit to consume"


def test_third_dunning_failure_suspends_the_plan_and_cancels_its_rollout():
    """PRD §3.8: "A declining retry self-loops `PAST_DUE → PAST_DUE` and increments
    `dunning_attempts`, likewise requiring the counter to be below 3 beforehand. The third
    failure — the increment that brings `dunning_attempts` to 3 — moves the plan `PAST_DUE →
    SUSPENDED`. Suspension moves every rollout in `PENDING` or `OFFERED` on the device belonging
    to this plan's order to `CANCELLED_INELIGIBLE`, unless the owning campaign's
    `is_mandatory_safety` is true". PRD §2.9 rule 62: "The simulated charge outcome is a success
    for the amount due after credits, on `POST /care-plan-subscriptions/{id}/run-billing-cycle`
    and `POST /care-plan-subscriptions/{id}/retry-payment` — otherwise `ERR_PAYMENT_DECLINED`
    (402)."

    Design: Corner/state_machines/sm_care_plan_third_dunning_failure_suspends_and_cancels_rollouts
    """
    env = setup_active_care_plan(
        plan_overrides=_STANDARD_PLAN,
        order_overrides=_ORDER_ECONOMICS,
        measurements=_PASS_MEASUREMENTS,
    )
    plan_id = env["plan"]["id"]
    device_id = env["assigned_device"]["id"]
    patient_headers = make_patient_headers(env["patient"]["id"])
    set_clock("2026-09-01T00:00:00Z")
    get_success_data(api_client.run_billing_cycle(plan_id, {"charge_outcome": "SUCCEEDED"}, ADMIN))

    set_clock("2026-09-02T00:00:00Z")
    campaign = _create_campaign(
        "CAMP-DUNNING",
        window_start_utc="2026-09-02T00:00:00Z",
        window_end_utc="2026-12-01T00:00:00Z",
        is_mandatory_safety=False,
    )
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    get_success_data(api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    assert _rollout_for_device(device_id)["status"] == "PENDING", (
        "the non-mandatory campaign leaves one PENDING rollout on the device"
    )

    set_clock("2026-10-01T00:00:00Z")
    validate_error(
        api_client.run_billing_cycle(plan_id, {"charge_outcome": "DECLINED"}, ADMIN),
        ApiErrorId.ERR_PAYMENT_DECLINED.value,
    )
    first_failure = get_success_data(api_client.get_care_plan_subscription(plan_id, CARE_OPS))
    assert first_failure["status"] == "PAST_DUE", "the declined cycle moves the plan to PAST_DUE"
    assert first_failure["dunning_attempts"] == 1, "the first failure sets dunning_attempts to 1"
    assert _rollout_for_device(device_id)["status"] == "PENDING", (
        "the first failure does not touch the rollout"
    )

    validate_error(
        api_client.retry_care_plan_payment(plan_id, {"charge_outcome": "DECLINED"}, patient_headers),
        ApiErrorId.ERR_PAYMENT_DECLINED.value,
    )
    second_failure = get_success_data(api_client.get_care_plan_subscription(plan_id, CARE_OPS))
    assert second_failure["status"] == "PAST_DUE", "the second failure self-loops in PAST_DUE"
    assert second_failure["dunning_attempts"] == 2, "the second failure brings the counter to 2"
    assert _rollout_for_device(device_id)["status"] == "PENDING", (
        "the second failure does not touch the rollout either"
    )

    resp = api_client.retry_care_plan_payment(
        plan_id, {"charge_outcome": "DECLINED"}, patient_headers
    )

    validate_error(resp, ApiErrorId.ERR_PAYMENT_DECLINED.value)

    plan = get_success_data(api_client.get_care_plan_subscription(plan_id, CARE_OPS))
    assert plan["status"] == "SUSPENDED", "the third failure suspends the plan"
    assert plan["dunning_attempts"] == 3, "the third failure brings the counter to 3"

    rollout = _rollout_for_device(device_id)
    assert rollout["status"] == "CANCELLED_INELIGIBLE", (
        "suspension cancels the pending rollout because the campaign is not mandatory safety"
    )

    reread_campaign = get_success_data(
        api_client.get_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert reread_campaign["status"] == "ROLLING", "the campaign itself keeps rolling"
    assert reread_campaign["installed_count"] == 0, "no install ever happened"

    device = get_success_data(api_client.get_device(device_id, CARE_OPS))
    assert device["firmware_version"] == "4.0.0", "no firmware moved"


# ---------------------------------------------------------------------------
# Firmware campaign and rollout machines
# ---------------------------------------------------------------------------
def test_campaign_abort_from_scheduled_touches_no_rollout():
    """PRD §3.9: "Aborting from `PAUSED` moves every rollout in `PENDING` or `OFFERED` to
    `CANCELLED_INELIGIBLE` while leaving `INSTALLED` rollouts intact; aborting from `SCHEDULED`
    requires `rollout_count` to be 0 and changes no rollout at all, which is the empty-set edge of
    the same action." PRD §3.9: "`failure_rate_pct` is 100 multiplied by failed rollouts divided by
    the sum of installed and failed rollouts, to one decimal place rounded half up, and reads 0
    when that denominator is 0."

    Design: Corner/state_machines/sm_campaign_abort_from_scheduled_is_the_empty_set_edge
    """
    set_clock("2026-08-05T00:00:00Z")
    campaign = _create_campaign("CAMP-EMPTY", is_mandatory_safety=False)
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))

    resp = api_client.abort_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)

    aborted = validate_success(resp, 200)
    assert aborted["status"] == "ABORTED", "a never-advanced campaign aborts straight from SCHEDULED"
    assert aborted["rollout_count"] == 0, "no cohort was ever selected"
    assert aborted["installed_count"] == 0, "nothing was ever installed"
    assert aborted["failure_rate_pct"] == 0.0, "an empty denominator reads 0"

    rollouts, meta = validate_paginated(
        api_client.list_campaign_rollouts(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert meta["total_count"] == 0, "the abort created or touched no rollout row"
    assert meta["has_more"] is False, "there is nothing to page through"
    assert rollouts == [], "the campaign owns no rollouts"


def test_rollout_offer_is_refused_while_its_campaign_is_paused():
    """PRD §3.9: "An engineer offers the update to the subscriber, moving the rollout `PENDING →
    OFFERED`; this requires the campaign to be `ROLLING`, the clock to be inside the closed
    maintenance window, and either the device's plan to be `ACTIVE` or `TRIALING` or the campaign's
    `is_mandatory_safety` to be true." PRD §2.9 rule 24: "The sibling entity named by the
    transition's precondition is in an allowed state — ... the campaign's `status` is `ROLLING`
    before a rollout may be offered or installed... This applies to `POST
    /remote-fitting-sessions/{id}/start`, `POST /firmware-rollouts/{id}/offer`, `POST
    /firmware-rollouts/{id}/install` and `POST /care-plan-subscriptions/{id}/reinstate` —
    otherwise `ERR_DEPENDENT_STATE_NOT_READY` (409)." PRD §3.9: "Pausing moves it `ROLLING →
    PAUSED`, leaving every `PENDING` rollout exactly where it is and blocking further batch
    selection".

    Design: Corner/state_machines/sm_rollout_offer_guarded_by_campaign_rolling_state
    """
    env = setup_delivered_order(order_overrides=_ORDER_ECONOMICS, measurements=_PASS_MEASUREMENTS)
    set_clock("2026-08-05T00:00:00Z")
    campaign = _create_campaign("CAMP-GUARD")
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    get_success_data(api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    rollout = _rollout_for_device(env["assigned_device"]["id"])
    assert rollout["status"] == "PENDING", "the cohort selection leaves the rollout PENDING"
    get_success_data(api_client.pause_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))

    resp = api_client.offer_firmware_rollout(rollout["id"], FIRMWARE_ENGINEER)

    validate_error(resp, ApiErrorId.ERR_DEPENDENT_STATE_NOT_READY.value)

    reread = _rollout_for_device(env["assigned_device"]["id"])
    assert reread["status"] == "PENDING", "the pause leaves the pending rollout exactly where it is"
    assert reread["attempt_count"] == 0, "no install attempt was consumed"

    reread_campaign = get_success_data(
        api_client.get_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert reread_campaign["status"] == "PAUSED", "the campaign is the entity blocking the offer"


def test_rollout_retry_loop_refuses_a_fourth_install_attempt():
    """PRD §3.9: "A failed rollout may be retried by the patient, moving it `FAILED →
    INSTALLING` and incrementing `attempt_count`, provided `attempt_count` is below 3 and the
    campaign is `ROLLING`; a third failure is not retried." PRD §2.9 rule 55:
    "`FirmwareRollout.attempt_count` is below 3, on `POST /firmware-rollouts/{id}/install` —
    otherwise `ERR_INSTALL_ATTEMPTS_EXHAUSTED` (409)." PRD §3.9: "A failure moves the rollout
    `INSTALLING → FAILED`, sets `failure_code` to `VERSION_DRIFT`, `POWER_LOSS`, `CHECKSUM` or
    `TIMEOUT`, and recomputes `failure_rate_pct`; when that rate rises above 25.0 percent the
    campaign is driven `ROLLING → PAUSED` automatically."

    Design: Corner/state_machines/sm_rollout_retry_loop_capped_at_three_attempts
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy()
    create_inventory_pool(restock_units=10, sku="NEO-M-OPEN")
    cohort = [
        _deliver_patient(policy["id"], f"SN-RT0{index}", f"rt{index}@x.test")
        for index in range(1, 5)
    ]
    set_clock("2026-08-05T00:00:00Z")
    campaign = _create_campaign("CAMP-RETRY", batch_size=4)
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    get_success_data(api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))

    for member in cohort[:3]:
        rollout = _rollout_for_device(member["assigned_device"]["id"])
        get_success_data(api_client.offer_firmware_rollout(rollout["id"], FIRMWARE_ENGINEER))
        get_success_data(
            api_client.install_firmware_rollout(
                rollout["id"], make_patient_headers(member["patient"]["id"])
            )
        )
        get_success_data(
            api_client.report_firmware_install(
                {"firmware_rollout_id": rollout["id"], "outcome": "SUCCESS"}, ADMIN
            )
        )

    last = cohort[3]
    last_headers = make_patient_headers(last["patient"]["id"])
    target = _rollout_for_device(last["assigned_device"]["id"])
    get_success_data(api_client.offer_firmware_rollout(target["id"], FIRMWARE_ENGINEER))
    for attempt in range(1, 4):
        installing = get_success_data(
            api_client.install_firmware_rollout(target["id"], last_headers)
        )
        assert installing["attempt_count"] == attempt, (
            f"install attempt {attempt} increments attempt_count to {attempt}"
        )
        get_success_data(
            api_client.report_firmware_install(
                {
                    "firmware_rollout_id": target["id"],
                    "outcome": "FAILURE",
                    "failure_code": "TIMEOUT",
                },
                ADMIN,
            )
        )

    resp = api_client.install_firmware_rollout(target["id"], last_headers)

    validate_error(resp, ApiErrorId.ERR_INSTALL_ATTEMPTS_EXHAUSTED.value)

    exhausted = _rollout_for_device(last["assigned_device"]["id"])
    assert exhausted["status"] == "FAILED", "a third failure is not retried"
    assert exhausted["attempt_count"] == 3, "the loop admitted exactly three attempts"

    reread_campaign = get_success_data(
        api_client.get_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert reread_campaign["status"] == "ROLLING", (
        "a failure rate of exactly 25.0 is not above 25.0, so the campaign keeps rolling"
    )
    assert reread_campaign["rollout_count"] == 4, "the cohort was four devices wide"
    assert reread_campaign["installed_count"] == 3, "three of the four installs succeeded"
    assert reread_campaign["failure_rate_pct"] == 25.0, "100 times 1 failed over 4 finished"

    device = get_success_data(api_client.get_device(last["assigned_device"]["id"], CARE_OPS))
    assert device["firmware_version"] == "4.0.0", "a failed rollout never moves the firmware"


def test_campaign_completion_waits_for_every_rollout_to_finish():
    """PRD §3.9: "Completing moves it `ROLLING → COMPLETED` and requires no rollout to remain in
    `PENDING`, `OFFERED` or `INSTALLING`; it freezes `installed_count` and `failure_rate_pct`."
    PRD §3.9: "A success moves the rollout `INSTALLING → INSTALLED`... Success sets the device's
    `firmware_version` to the campaign's `to_version`, stamps `installed_at`, and recomputes the
    campaign's `installed_count` and `failure_rate_pct`."

    Design: Corner/state_machines/sm_campaign_complete_requires_every_rollout_terminal
    """
    env = setup_delivered_order(order_overrides=_ORDER_ECONOMICS, measurements=_PASS_MEASUREMENTS)
    device_id = env["assigned_device"]["id"]
    patient_headers = make_patient_headers(env["patient"]["id"])
    set_clock("2026-08-05T00:00:00Z")
    campaign = _create_campaign("CAMP-JOIN")
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    get_success_data(api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    rollout = _rollout_for_device(device_id)
    get_success_data(api_client.offer_firmware_rollout(rollout["id"], FIRMWARE_ENGINEER))

    premature = api_client.complete_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    assert premature.status_code == 409, (
        "completion is refused while a rollout is still OFFERED: "
        f"got {premature.status_code} {premature.text}"
    )
    still_rolling = get_success_data(
        api_client.get_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert still_rolling["status"] == "ROLLING", "the refused completion leaves the campaign ROLLING"

    get_success_data(api_client.install_firmware_rollout(rollout["id"], patient_headers))
    get_success_data(
        api_client.report_firmware_install(
            {"firmware_rollout_id": rollout["id"], "outcome": "SUCCESS"}, ADMIN
        )
    )

    resp = api_client.complete_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)

    completed = validate_success(resp, 200)
    assert completed["status"] == "COMPLETED", "every rollout is terminal, so the campaign completes"
    assert completed["rollout_count"] == 1, "the cohort was a single device"
    assert completed["installed_count"] == 1, "that device installed the update"
    assert completed["failure_rate_pct"] == 0.0, "no rollout failed"

    finished = _rollout_for_device(device_id)
    assert finished["status"] == "INSTALLED", "the rollout reached its terminal INSTALLED state"
    assert finished["attempt_count"] == 1, "it took a single attempt"

    device = get_success_data(api_client.get_device(device_id, CARE_OPS))
    assert device["firmware_version"] == "4.2.1", "success moves the device to the target version"


# ---------------------------------------------------------------------------
# Compliance override, session windows and the patient sink state
# ---------------------------------------------------------------------------
def test_compliance_override_approval_reopens_screening_for_the_patient():
    """PRD §3.3: "Approval moves the override `PENDING → APPROVED`, records
    `approved_by_user_id` and `decided_at`, moves the patient `MEDICALLY_DISQUALIFIED →
    SCREENING_IN_PROGRESS`, invalidates the patient's latest `SCORED` screening with
    `invalidated_reason` `PROVIDER_OVERRIDE` and clears that session's findings, resets
    `open_mandatory_flag_count` to 0 and `advisory_weight_total` to 0.0, and creates a fresh
    screening in `DRAFT` whose `attempt_ordinal` is one more than `screening_attempt_count`."

    Design: Corner/state_machines/sm_compliance_override_approve_resets_patient_and_mints_draft_screening
    """
    env = setup_evaluated_referral(measurements=_PASS_MEASUREMENTS,
                                   provider_overrides={"npi": "1000000004"})
    clear_referral(env, outcome="NOT_CLEARED", note="active pathology")
    disqualified = get_success_data(api_client.get_patient(env["patient"]["id"], CARE_OPS))
    assert disqualified["status"] == "MEDICALLY_DISQUALIFIED", (
        "an uncleared referral disqualifies the patient"
    )
    override = file_compliance_override(
        env["patient"]["id"], justification="second opinion obtained offline"
    )

    resp = api_client.approve_compliance_override(
        env["patient"]["id"], override["id"], COMPLIANCE_2
    )

    approved = validate_success(resp, 200)
    assert approved["status"] == "APPROVED", "the second officer approves the override"
    assert approved["filed_by_user_id"] == COMPLIANCE["X-User-ID"], "the first officer filed it"
    assert approved["approved_by_user_id"] == COMPLIANCE_2["X-User-ID"], (
        "a different officer must approve it"
    )
    assert approved["decided_at"].startswith("2026-08-03T10:05:00"), (
        "decided_at is stamped from the logical clock"
    )

    patient = get_success_data(api_client.get_patient(env["patient"]["id"], CARE_OPS))
    assert patient["status"] == "SCREENING_IN_PROGRESS", "the patient may screen again"
    assert patient["open_mandatory_flag_count"] == 0, "the mandatory flag aggregate is zeroed"
    assert patient["advisory_weight_total"] == 0, "the advisory weight aggregate is zeroed"

    old_session = get_success_data(
        api_client.get_screening_session(env["screening"]["id"], CARE_OPS)
    )
    assert old_session["status"] == "INVALIDATED", "the scored screening is invalidated"
    assert old_session["invalidated_reason"] == "PROVIDER_OVERRIDE", "with reason PROVIDER_OVERRIDE"

    sessions, _ = validate_paginated(
        api_client.list_patient_screening_sessions(env["patient"]["id"], CARE_OPS)
    )
    drafts = [row for row in sessions if row["status"] == "DRAFT"]
    assert len(drafts) == 1, "exactly one fresh draft screening is minted"
    assert drafts[0]["attempt_ordinal"] == 2, (
        "the new draft's attempt_ordinal is one more than the screening_attempt_count of 1"
    )


def test_no_show_one_minute_before_the_window_closes_is_refused():
    """PRD §2.9 rule 36: "Session windows: starting requires the clock to be at or after
    `scheduled_start_utc` and strictly before `scheduled_end_utc`; a patient cancel requires the
    clock to be strictly before `scheduled_start_utc`; a no-show requires the clock to be at or
    after `scheduled_end_utc`. This applies to `POST /remote-fitting-sessions/{id}/start`, `POST
    /remote-fitting-sessions/{id}/cancel` and `POST /remote-fitting-sessions/{id}/no-show` —
    otherwise `ERR_SESSION_WINDOW_NOT_OPEN` (409)." PRD §3.3: "Booking the evaluation moves the
    referral `OPEN → SCHEDULED`".

    Design: Corner/state_machines/sm_session_no_show_before_window_close_is_rejected
    """
    env = setup_red_flagged_patient(measurements=_PASS_MEASUREMENTS)
    provider = create_provider(npi="1000000005", full_name="Aud Four")
    session = get_success_data(
        api_client.create_remote_fitting_session(
            {
                "patient_id": env["patient"]["id"],
                "session_type": "REFERRAL_EVALUATION",
                "scheduled_start_utc": "2026-08-03T10:00:00Z",
                "scheduled_end_utc": "2026-08-03T10:30:00Z",
                "provider_id": provider["id"],
                "provider_referral_id": env["referral"]["id"],
            },
            make_patient_headers(env["patient"]["id"]),
        )
    )
    set_clock("2026-08-03T10:29:00Z")

    resp = api_client.no_show_fitting_session(
        session["id"], make_licensed_audiologist_headers(provider["id"])
    )

    validate_error(resp, ApiErrorId.ERR_SESSION_WINDOW_NOT_OPEN.value)

    reread = get_success_data(api_client.get_remote_fitting_session(session["id"], CARE_OPS))
    assert reread["status"] == "SCHEDULED", "the session is still scheduled one minute early"

    referral = get_success_data(api_client.get_provider_referral(env["referral"]["id"], CARE_OPS))
    assert referral["status"] == "SCHEDULED", "the referral keeps its booking"
    assert referral["reschedule_count"] == 0, "no reschedule cycle was consumed"

    reread_provider = get_success_data(api_client.get_provider(provider["id"], CARE_OPS))
    assert reread_provider["booked_minutes_on_focus_date"] == 30, (
        "the provider's 30 booked minutes are intact"
    )


def test_deactivated_patient_cannot_open_a_new_screening():
    """PRD §3.1: "A patient's candidacy `status` moves through `REGISTERED`,
    `SCREENING_IN_PROGRESS`, `CANDIDATE_APPROVED`, `REFERRAL_REQUIRED`, `PROVIDER_CLEARED`,
    `MEDICALLY_DISQUALIFIED` and the terminal `DEACTIVATED`." PRD §3.1: "All three set
    `deactivated_at` to the current logical clock". PRD §2.9 rule 3: "For an entity-backed role,
    `X-User-ID` is the `id` of an existing backing row (a `Patient` or a `Provider`) that is
    neither `DEACTIVATED` nor `OFFBOARDED`. This applies to every endpoint called as `Patient`,
    `HearingProfessional` or `LicensedAudiologist` — otherwise `ERR_IDENTITY_NOT_FOUND` (401)."

    Design: Corner/state_machines/sm_patient_deactivated_state_rejects_new_screening
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy()
    patient = register_patient(policy["id"], email="dead@x.test", full_name="Dead One")
    get_success_data(api_client.delete_patient(patient["id"], ADMIN))

    resp = api_client.start_screening_session(
        patient["id"], {}, make_patient_headers(patient["id"])
    )

    validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_FOUND.value)

    reread = get_success_data(api_client.get_patient(patient["id"], CARE_OPS))
    assert reread["status"] == "DEACTIVATED", "DEACTIVATED is the terminal sink for a patient"
    assert reread["deactivated_at"].startswith("2026-08-01T00:00:00"), (
        "deactivation stamps deactivated_at from the logical clock"
    )

    _, meta = validate_paginated(
        api_client.list_patient_screening_sessions(patient["id"], CARE_OPS)
    )
    assert meta["total_count"] == 0, "no screening session was created for the deactivated patient"
