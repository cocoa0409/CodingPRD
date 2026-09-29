"""Request-evaluation-order and conditional-validation compliance tests.

Each test drives a request that violates two rules at once (or that only passes once a
conditional precondition is satisfied) and pins the single error the PRD says the caller
must see.
"""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    NON_EXISTENT_UUID,
    REPAIR_TECH,
    ApiErrorId,
    api_client,
    assert_inventory_conservation,
    create_inventory_pool,
    create_provider,
    create_state_policy,
    create_state_policy_payload,
    get_pool,
    get_success_data,
    is_iso8601_timestamp,
    make_hearing_professional_headers,
    make_patient_headers,
    make_reimbursement_headers,
    place_order,
    register_patient,
    scan_shipment,
    set_clock,
    setup_active_care_plan,
    setup_authorized_order,
    setup_delivered_order,
    setup_red_flagged_patient,
    setup_registered_patient,
    setup_return_settled,
    setup_shipped_order,
    validate_error,
    validate_paginated,
    validate_success,
)

# Canonical order money used by the design recipes: a 200000-cent instrument with no
# discount, no accessories and 1495 cents of shipping.
ORDER_200K = {
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}

# Clean screening measurements that keep the patient out of the red-flag path.
CLEAN_MEASUREMENTS = {"pure_tone_avg_db": 40.0}


def test_billing_cycle_on_cancelled_plan_reports_invalid_state_not_payment_declined():
    """PRD §2.9: "When a single request violates more than one rule, the rule with the
    lowest priority number below wins and its error is the one returned."
    PRD §2.9: "A billing-cycle run against a cancelled subscription with a declining
    instrument violates both rule 22 and rule 62; rule 22 wins, so the caller sees
    `ERR_INVALID_STATE`."

    Design: Corner/validations/validation_conflict1_invalid_state_beats_payment_declined
    """
    env = setup_active_care_plan(
        plan_overrides={
            "plan_tier": "STANDARD",
            "base_fee_cents": 9900,
            "firmware_auto_update_enabled": True,
        },
        order_overrides=ORDER_200K,
        measurements=CLEAN_MEASUREMENTS,
    )
    patient_headers = make_patient_headers(env["patient"]["id"])
    plan_id = env["plan"]["id"]

    cancelled = validate_success(
        api_client.cancel_care_plan_subscription(
            plan_id, {"reason_note": "patient request"}, patient_headers
        )
    )
    assert cancelled["status"] == "CANCELLED", "patient cancellation must terminate the plan"

    resp = api_client.run_billing_cycle(plan_id, {"charge_outcome": "DECLINED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    plan = validate_success(api_client.get_care_plan_subscription(plan_id, CARE_OPS))
    assert plan["status"] == "CANCELLED", "the rejected cycle must not revive the plan"
    assert plan["cycle_ordinal"] == 0, "no cycle may be advanced by a rejected billing run"
    assert plan["dunning_attempts"] == 0, "a state-rejected run must not record a dunning attempt"


def test_confirm_fit_reports_missing_pool_before_open_mandatory_red_flag():
    """PRD §2.9: "A fit confirmation for a patient with an open mandatory red flag whose
    model-dome-tip triple has no pool row violates both rule 28 and rule 13; rule 13 wins,
    so the caller sees `ERR_INVENTORY_POOL_NOT_FOUND`, because referential existence is
    checked before the safety band."
    PRD §2.9 rule 13: "An `InventoryPool` matching the requested `model`, `dome_size` and
    `tip_type` triple exists, on `POST /device-orders/{id}/confirm-fit` and
    `POST /device-orders/{device_order_id}/fit-exchanges` — otherwise
    `ERR_INVENTORY_POOL_NOT_FOUND` (404)."

    Design: Corner/validations/validation_conflict2_inventory_pool_not_found_beats_mandatory_referral_open
    """
    env = setup_red_flagged_patient(symptom_codes=("VERTIGO",), measurements=CLEAN_MEASUREMENTS)
    # The bootstrapped pool is NEO/M/OPEN, so an L-dome order has no matching pool row.
    order = place_order(env["patient"]["id"], dome_size="L", **ORDER_200K)

    resp = api_client.confirm_fit(order["id"], CARE_OPS)
    validate_error(resp, ApiErrorId.ERR_INVENTORY_POOL_NOT_FOUND.value)

    order_after = validate_success(api_client.get_device_order(order["id"], CARE_OPS))
    assert order_after["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
        "a rejected confirm-fit must leave the order awaiting confirmation"
    )
    patient = validate_success(api_client.get_patient(env["patient"]["id"], CARE_OPS))
    assert patient["open_mandatory_flag_count"] == 1, (
        "the mandatory red flag must still be open, proving the safety band was never reached"
    )


def test_return_request_after_trial_end_reports_window_closed_not_device_in_repair():
    """PRD §2.9: "A return request made after `effective_end_utc` on an order whose device
    is currently in repair violates both rule 34 and rule 40; rule 34 wins, so the caller
    sees `ERR_TRIAL_WINDOW_CLOSED`."
    PRD §2.9 rule 34: "The logical clock is at or before the trial's `effective_end_utc`,
    on `POST /trial-periods/{trial_period_id}/return-authorizations` and
    `POST /trial-periods/{id}/extend` — otherwise `ERR_TRIAL_WINDOW_CLOSED` (409)."

    Design: Corner/validations/validation_conflict3_trial_window_closed_beats_repair_in_progress
    """
    env = setup_delivered_order(order_overrides=ORDER_200K, measurements=CLEAN_MEASUREMENTS)
    patient_headers = make_patient_headers(env["patient"]["id"])
    trial_id = env["trial"]["id"]

    # Well past the 45-day trial window.
    set_clock("2026-09-20T00:00:00Z")
    repair = get_success_data(
        api_client.create_repair_order(
            {"device_id": env["assigned_device"]["id"], "fault_code": "NO_SOUND"}, CARE_OPS
        )
    )
    get_success_data(api_client.send_repair_kit(repair["id"], CARE_OPS))
    set_clock("2026-09-21T00:00:00Z")
    get_success_data(api_client.receive_repair_order(repair["id"], REPAIR_TECH))
    get_success_data(api_client.start_repair_order(repair["id"], REPAIR_TECH))

    set_clock("2026-09-22T00:00:00Z")
    trial = validate_success(api_client.get_trial_period(trial_id, patient_headers))
    resp = api_client.create_return_authorization(
        trial_id, {"expected_trial_period_version": trial["version"]}, patient_headers
    )
    validate_error(resp, ApiErrorId.ERR_TRIAL_WINDOW_CLOSED.value)

    _rows, meta = validate_paginated(api_client.list_trial_return_authorizations(trial_id, CARE_OPS))
    assert meta["total_count"] == 0, "no return authorization may exist after the closed-window refusal"


def test_foreign_patient_cancelling_shipped_exchange_reports_ownership_before_state():
    """PRD §2.9: "And a patient cancelling another patient's shipped exchange violates both
    rule 5 and rule 22; rule 5 wins, so the caller sees `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.9 rule 22: "The targeted entity's current state is a declared origin state for
    the requested transition, on every action endpoint that drives a state transition —
    otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/validations/validation_conflict4_not_resource_owner_beats_invalid_state
    """
    env = setup_delivered_order(order_overrides=ORDER_200K, measurements=CLEAN_MEASUREMENTS)
    create_inventory_pool(restock_units=5, sku="NEO-S-OPEN", model="NEO", dome_size="S", tip_type="OPEN")
    owner_headers = make_patient_headers(env["patient"]["id"])
    stranger = register_patient(env["policy"]["id"])
    stranger_headers = make_patient_headers(stranger["id"])

    order = validate_success(api_client.get_device_order(env["order"]["id"], owner_headers))
    exchange = validate_success(
        api_client.create_fit_exchange(
            order["id"],
            {
                "to_dome_size": "S",
                "to_tip_type": "OPEN",
                "expected_device_order_version": order["version"],
                "allow_backorder": False,
            },
            owner_headers,
        ),
        201,
    )
    shipped = get_success_data(api_client.ship_fit_exchange(exchange["id"], CARE_OPS))
    assert shipped["status"] == "SHIPPED", "the exchange must be SHIPPED before the cancel attempts"

    resp = api_client.cancel_fit_exchange(exchange["id"], {"reason_note": "not mine"}, stranger_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    unchanged = validate_success(api_client.get_fit_exchange(exchange["id"], CARE_OPS))
    assert unchanged["status"] == "SHIPPED", "the foreign cancel must not move the exchange"

    owner_resp = api_client.cancel_fit_exchange(
        exchange["id"], {"reason_note": "not mine"}, owner_headers
    )
    validate_error(owner_resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_stale_trial_version_reported_before_terminal_trial_state():
    """PRD §2.9 rule 18: "`expected_trial_period_version` equals `TrialPeriod.version`, on
    `POST /trial-periods/{trial_period_id}/return-authorizations` — otherwise
    `ERR_STALE_TRIAL_VERSION` (412)."
    PRD §2.9 rule 21: "Stale-version detection deliberately runs **before** state legality,
    so a stale writer is told about staleness rather than about a state it cannot yet see."
    PRD §2.9 rule 23: "The targeted entity is not already in a terminal state for its
    machine, on every action endpoint that drives a state transition — otherwise
    `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/validations/validation_occ_priority_18_answers_before_terminal_state_rule
    """
    env = setup_return_settled(
        inspection_grade="RESELLABLE",
        at_iso="2026-08-11T00:00:00Z",
        order_overrides=ORDER_200K,
        measurements=CLEAN_MEASUREMENTS,
    )
    patient_headers = make_patient_headers(env["patient"]["id"])
    trial_id = env["trial"]["id"]

    stale = api_client.create_return_authorization(
        trial_id, {"expected_trial_period_version": 1}, patient_headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_TRIAL_VERSION.value)

    trial = validate_success(api_client.get_trial_period(trial_id, patient_headers))
    assert trial["version"] != 1, "the settled trial must have advanced past the stale version"
    fresh = api_client.create_return_authorization(
        trial_id, {"expected_trial_period_version": trial["version"]}, patient_headers
    )
    validate_error(fresh, ApiErrorId.ERR_ALREADY_TERMINAL.value)

    _rows, meta = validate_paginated(api_client.list_trial_return_authorizations(trial_id, CARE_OPS))
    assert meta["total_count"] == 1, "neither refusal may add a second return authorization"


def test_invalid_enum_reported_before_duplicate_state_code():
    """PRD §2.9 rule 16: "Every supplied enum value is a member of its field's declared
    value set, on every POST and PATCH endpoint with enum inputs — otherwise
    `ERR_INVALID_ENUM_VALUE` (422)."
    PRD §2.9 rule 17: "Natural keys are unused — `Patient.email`, `Provider.npi`,
    `Device.serial_number`, `InventoryPool.sku`, `FirmwareCampaign.campaign_code`,
    `StatePolicy.state_code`, and the server-minted `ReturnAuthorization.rma_code` — on
    `POST /patients`, `POST /providers`, `POST /devices`, `POST /inventory-pools`,
    `POST /firmware-campaigns` and `POST /state-policies` — otherwise `ERR_DUPLICATE_KEY`
    (409)."

    Design: Corner/validations/validation_enum_check_precedes_duplicate_key_check
    """
    set_clock("2026-08-01T00:00:00Z")
    create_state_policy(state_code="CA")

    bad_enum_duplicate = create_state_policy_payload(
        state_code="CA", restocking_fee_mode="BOGUS_MODE"
    )
    resp = api_client.create_state_policy(bad_enum_duplicate, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)

    duplicate_only = dict(bad_enum_duplicate, restocking_fee_mode="FLAT_PCT")
    resp = api_client.create_state_policy(duplicate_only, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)

    _rows, meta = validate_paginated(api_client.list_state_policies(ADMIN))
    assert meta["total_count"] == 1, "neither rejected create may persist a second policy"


def test_unknown_policy_reference_reported_before_retired_policy_rule():
    """PRD §2.9 rule 11: "Every foreign key supplied in a request body resolves to an
    existing row, on every POST and PATCH endpoint that accepts foreign keys — otherwise
    `ERR_REFERENCE_NOT_FOUND` (404)."
    PRD §2.9 rule 12: "A referenced `StatePolicy` has `is_retired` false when it is being
    newly assigned, on `POST /patients`, `PATCH /patients/{id}` and
    `POST /patients/{patient_id}/device-orders`; already-pinned retired policies stay valid
    on existing orders — otherwise `ERR_STATE_POLICY_RETIRED` (409)."
    PRD §2.5: "Soft-retiring a policy through `DELETE /state-policies/{id}` sets
    `is_retired` to true and increments `version`; retired policies remain readable and
    remain pinned on existing orders".

    Design: Corner/validations/validation_cascading_reference_existence_runs_before_retired_check
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy(state_code="CA")
    retired = validate_success(api_client.delete_state_policy(policy["id"], ADMIN))
    assert retired["is_retired"] is True, "DELETE must soft-retire the policy"

    resp = api_client.create_patient(
        {
            "state_policy_id": policy["id"],
            "email": "retired@x.test",
            "full_name": "Ret One",
            "age_years": 70,
        },
        CARE_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STATE_POLICY_RETIRED.value)

    resp = api_client.create_patient(
        {
            "state_policy_id": NON_EXISTENT_UUID,
            "email": "unknown-policy@x.test",
            "full_name": "Ret Two",
            "age_years": 70,
        },
        CARE_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)

    still_readable = validate_success(api_client.get_state_policy(policy["id"], ADMIN))
    assert still_readable["is_retired"] is True, "a retired policy must remain readable"


def test_segregation_of_duties_reported_before_claim_eligibility_ceiling():
    """PRD §2.9 rule 8: "Segregation of duties on approval: the approving `X-User-ID`
    differs from `ReimbursementClaim.submitted_by_user_id` ... This applies to
    `POST /reimbursement-claims/{id}/decide` and
    `POST /patients/{patient_id}/compliance-overrides/{override_id}/approve` — otherwise
    `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §2.9 rule 60: "`claimed_amount_cents` is at most `eligible_amount_cents`, on
    `POST /reimbursement-claims/{id}/decide` with `decision` `APPROVE` — otherwise
    `ERR_CLAIM_AMOUNT_EXCEEDS_ELIGIBLE` (422)."

    Design: Corner/validations/validation_segregation_of_duties_answers_before_fiscal_eligibility
    """
    env = setup_delivered_order(order_overrides=ORDER_200K, measurements=CLEAN_MEASUREMENTS)
    patient_headers = make_patient_headers(env["patient"]["id"])
    repair = get_success_data(
        api_client.create_repair_order(
            {"device_id": env["assigned_device"]["id"], "fault_code": "MOISTURE"}, CARE_OPS
        )
    )
    claim = validate_success(
        api_client.create_reimbursement_claim(
            {
                "patient_id": env["patient"]["id"],
                "subject_kind": "REPAIR_ORDER",
                "repair_order_id": repair["id"],
                "claimed_amount_cents": 90000,
                "document_codes": ["INVOICE", "PROOF_OF_PAYMENT"],
                "insurance_benefit_cap_cents": 0,
                "insurance_benefit_used_cents": 0,
                "fsa_balance_cents": 0,
            },
            patient_headers,
        ),
        201,
    )
    submitter = make_reimbursement_headers("spec-1")
    reviewer = make_reimbursement_headers("spec-2")
    get_success_data(api_client.submit_reimbursement_claim(claim["id"], submitter))
    get_success_data(api_client.start_reimbursement_review(claim["id"], reviewer))

    resp = api_client.decide_reimbursement_claim(claim["id"], {"decision": "APPROVE"}, submitter)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    unchanged = validate_success(api_client.get_reimbursement_claim(claim["id"], reviewer))
    assert unchanged["status"] == "UNDER_REVIEW", "the refused decision must leave the claim in review"
    assert unchanged["approved_by_user_id"] is None, "no approver may be stamped by a refused decision"

    resp = api_client.decide_reimbursement_claim(claim["id"], {"decision": "APPROVE"}, reviewer)
    validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_EXCEEDS_ELIGIBLE.value)


def test_initial_fit_start_requires_delivered_order_then_succeeds_after_delivery():
    """PRD §2.9 rule 24: "The sibling entity named by the transition's precondition is in an
    allowed state — the order's `fulfillment_status` is `DELIVERED` before an `INITIAL_FIT`
    session may start ... This applies to `POST /remote-fitting-sessions/{id}/start` ... —
    otherwise `ERR_DEPENDENT_STATE_NOT_READY` (409)."
    PRD §3.4: "for an `INITIAL_FIT` the linked order's `fulfillment_status` must already be
    `DELIVERED`"

    Design: Corner/validations/validation_cross_entity_initial_fit_start_requires_delivered_order
    """
    env = setup_shipped_order(order_overrides=ORDER_200K, measurements=CLEAN_MEASUREMENTS)
    provider = create_provider(
        provider_type="TELECARE_FITTER",
        npi="1000000009",
        licensed_state_codes=["CA"],
        daily_capacity_minutes=480,
        buffer_minutes=0,
    )
    patient_headers = make_patient_headers(env["patient"]["id"])
    provider_headers = make_hearing_professional_headers(provider["id"])
    session = validate_success(
        api_client.create_remote_fitting_session(
            {
                "patient_id": env["patient"]["id"],
                "session_type": "INITIAL_FIT",
                "provider_id": provider["id"],
                "device_order_id": env["order"]["id"],
                "scheduled_start_utc": "2026-08-20T10:00:00Z",
                "scheduled_end_utc": "2026-08-20T11:00:00Z",
                "programming_profile_code": "MILD_SLOPING_V3",
            },
            patient_headers,
        ),
        201,
    )

    set_clock("2026-08-20T10:30:00Z")
    resp = api_client.start_fitting_session(session["id"], provider_headers)
    validate_error(resp, ApiErrorId.ERR_DEPENDENT_STATE_NOT_READY.value)
    still_scheduled = validate_success(
        api_client.get_remote_fitting_session(session["id"], patient_headers)
    )
    assert still_scheduled["status"] == "SCHEDULED", "the refused start must not move the session"

    scan_shipment(env["order"]["id"], "DELIVERED")
    started = validate_success(api_client.start_fitting_session(session["id"], provider_headers))
    assert started["status"] == "IN_PROGRESS", (
        "the identical start must succeed once the linked order is DELIVERED"
    )


def test_expired_referral_blocks_referral_evaluation_booking():
    """PRD §2.9 rule 32: "The logical clock is strictly before the referral's `expires_at`,
    on `POST /remote-fitting-sessions` with `session_type` `REFERRAL_EVALUATION` and on
    `POST /provider-referrals/{id}/determination` — otherwise `ERR_REFERRAL_EXPIRED` (409)."
    PRD §3.3: the referral is opened "computing `expires_at` as `issued_at` plus the patient's
    policy `referral_validity_days` days".

    Design: Corner/validations/validation_temporal_expired_referral_blocks_evaluation_booking
    """
    env = setup_red_flagged_patient(
        symptom_codes=("VERTIGO",),
        measurements=CLEAN_MEASUREMENTS,
        policy_overrides={"referral_validity_days": 90},
    )
    provider = create_provider(
        npi="1000000010",
        licensed_state_codes=["CA"],
        daily_capacity_minutes=480,
        buffer_minutes=0,
    )
    patient_headers = make_patient_headers(env["patient"]["id"])

    # 2026-08-01 + 90 days = 2026-10-30, so the clock is past expiry.
    set_clock("2026-11-01T00:00:00Z")
    resp = api_client.create_remote_fitting_session(
        {
            "patient_id": env["patient"]["id"],
            "session_type": "REFERRAL_EVALUATION",
            "provider_id": provider["id"],
            "provider_referral_id": env["referral"]["id"],
            "scheduled_start_utc": "2026-11-05T10:00:00Z",
            "scheduled_end_utc": "2026-11-05T11:00:00Z",
        },
        patient_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REFERRAL_EXPIRED.value)

    _rows, meta = validate_paginated(
        api_client.list_remote_fitting_sessions(
            CARE_OPS, params={"patient_id": env["patient"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "an expired referral must leave no session booked"


def test_second_pause_refused_once_paused_days_exceeds_budget():
    """PRD §2.9 rule 53: "The trial's `paused_days` is below 60 before a new pause may open,
    on `POST /repair-orders/{id}/receive` — otherwise `ERR_PAUSE_BUDGET_EXHAUSTED` (409)."
    PRD §3.6: "And the trial carries an aggregate budget: once `paused_days` has reached 60,
    which is inclusive, no new pause may open, rejected with `ERR_PAUSE_BUDGET_EXHAUSTED`."

    Design: Corner/validations/validation_aggregate_pause_budget_exhausted_at_sixty_days
    """
    env = setup_delivered_order(order_overrides=ORDER_200K, measurements=CLEAN_MEASUREMENTS)
    device_id = env["assigned_device"]["id"]

    first = get_success_data(
        api_client.create_repair_order({"device_id": device_id, "fault_code": "MOISTURE"}, CARE_OPS)
    )
    get_success_data(api_client.send_repair_kit(first["id"], CARE_OPS))
    set_clock("2026-08-05T00:00:00Z")
    get_success_data(api_client.receive_repair_order(first["id"], REPAIR_TECH))
    get_success_data(api_client.start_repair_order(first["id"], REPAIR_TECH))
    set_clock("2026-10-15T00:00:00Z")
    get_success_data(api_client.resolve_repair_order(first["id"], {"resolution": "REPAIRED"}, REPAIR_TECH))
    get_success_data(api_client.return_repair_to_patient(first["id"], REPAIR_TECH))

    set_clock("2026-10-16T00:00:00Z")
    second = get_success_data(
        api_client.create_repair_order({"device_id": device_id, "fault_code": "BATTERY"}, CARE_OPS)
    )
    get_success_data(api_client.send_repair_kit(second["id"], CARE_OPS))

    resp = api_client.receive_repair_order(second["id"], REPAIR_TECH)
    validate_error(resp, ApiErrorId.ERR_PAUSE_BUDGET_EXHAUSTED.value)

    unchanged = validate_success(api_client.get_repair_order(second["id"], REPAIR_TECH))
    assert unchanged["status"] == "KIT_SENT", "the refused receipt must leave the repair at KIT_SENT"

    rows, _meta = validate_paginated(
        api_client.list_trial_periods(CARE_OPS, params={"device_order_id": env["order"]["id"]})
    )
    assert rows[0]["status"] == "ACTIVE", "the refused receipt must not open a second pause"
    assert rows[0]["paused_days"] == 71, "the accumulated pause budget must stay at 71 days"


def test_confirm_fit_passes_only_after_waiver_acknowledgement():
    """PRD §2.9 rule 29: "When the pinned policy's `waiver_required` is true, the patient's
    `waiver_acknowledged_at` is non-null, on `POST /device-orders/{id}/confirm-fit` —
    otherwise `ERR_WAIVER_NOT_ACKNOWLEDGED` (422)."
    PRD §3.5: confirm-fit "reserves a unit by decrementing that pool's `on_hand_units` by
    one and incrementing its `reserved_units` by one, assigns an `IN_STOCK` device of the
    same model"

    Design: Corner/validations/validation_conditional_waiver_requirement_satisfied_lets_confirm_fit_pass
    """
    env = setup_authorized_order(
        policy_overrides={"state_code": "TX", "waiver_required": True},
        order_overrides=ORDER_200K,
        measurements=CLEAN_MEASUREMENTS,
    )
    order_id = env["order"]["id"]
    patient_id = env["patient"]["id"]

    resp = api_client.confirm_fit(order_id, CARE_OPS)
    validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ACKNOWLEDGED.value)

    patient = validate_success(
        api_client.acknowledge_waiver(patient_id, make_patient_headers(patient_id))
    )
    assert patient["waiver_acknowledged_at"] is not None, "acknowledgement must stamp the patient"
    assert is_iso8601_timestamp(patient["waiver_acknowledged_at"]), (
        "waiver_acknowledged_at must be an ISO 8601 UTC timestamp"
    )

    confirmed = validate_success(api_client.confirm_fit(order_id, CARE_OPS))
    assert confirmed["fulfillment_status"] == "READY_TO_SHIP", (
        "the identical confirm-fit must pass once the waiver is acknowledged"
    )

    pool = get_pool(env["pool"]["id"])
    assert pool["on_hand_units"] == 4, "the reservation must decrement on_hand_units by one"
    assert pool["reserved_units"] == 1, "the reservation must increment reserved_units by one"
    assert_inventory_conservation(pool)

    devices, _meta = validate_paginated(
        api_client.list_devices(CARE_OPS, params={"device_order_id": order_id})
    )
    assert len(devices) == 1, "confirm-fit must assign exactly one device to the order"
    assert devices[0]["status"] == "ASSIGNED", "the reserved device must move to ASSIGNED"


def test_telehealth_prohibition_requires_provider_licensed_in_patient_state():
    """PRD §2.9 rule 30: "When the patient's policy has `telehealth_fitting_permitted` false,
    the booked provider's `licensed_state_codes` contains the patient's `state_code`, on
    `POST /remote-fitting-sessions` — otherwise `ERR_TELEHEALTH_NOT_PERMITTED_IN_STATE`
    (422)."
    PRD §3.4: "When the patient's policy has `telehealth_fitting_permitted` false, the
    booked provider must be licensed in the patient's own `state_code`, otherwise the
    booking is rejected with `ERR_TELEHEALTH_NOT_PERMITTED_IN_STATE`."

    Design: Corner/validations/validation_conditional_telehealth_flag_requires_in_state_provider
    """
    env = setup_registered_patient(policy_overrides={"telehealth_fitting_permitted": False})
    out_of_state = create_provider(
        provider_type="TELECARE_FITTER",
        npi="1000000013",
        licensed_state_codes=["NV"],
        daily_capacity_minutes=480,
        buffer_minutes=0,
    )
    in_state = create_provider(
        provider_type="TELECARE_FITTER",
        npi="1000000014",
        licensed_state_codes=["CA"],
        daily_capacity_minutes=480,
        buffer_minutes=0,
    )
    patient_headers = make_patient_headers(env["patient"]["id"])
    booking = {
        "patient_id": env["patient"]["id"],
        "session_type": "FOLLOW_UP",
        "provider_id": out_of_state["id"],
        "scheduled_start_utc": "2026-08-20T10:00:00Z",
        "scheduled_end_utc": "2026-08-20T11:00:00Z",
    }

    resp = api_client.create_remote_fitting_session(booking, patient_headers)
    validate_error(resp, ApiErrorId.ERR_TELEHEALTH_NOT_PERMITTED_IN_STATE.value)

    _rows, meta = validate_paginated(
        api_client.list_remote_fitting_sessions(
            CARE_OPS, params={"patient_id": env["patient"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "the rejected booking must not persist a session"

    session = validate_success(
        api_client.create_remote_fitting_session(
            dict(booking, provider_id=in_state["id"]), patient_headers
        ),
        201,
    )
    assert session["status"] == "SCHEDULED", "an in-state provider must be bookable"


def test_third_information_request_refused_with_counter_frozen_at_two():
    """PRD §2.9 rule 47: "`info_request_count` is below 2, on
    `POST /reimbursement-claims/{id}/request-info` — otherwise
    `ERR_INFO_REQUEST_LIMIT_REACHED` (409)."
    PRD §3.8: "The cycle from review through an information request and back is capped at
    two requests."

    Design: Corner/validations/validation_info_request_limit_reached_on_third_cycle
    """
    env = setup_delivered_order(order_overrides=ORDER_200K, measurements=CLEAN_MEASUREMENTS)
    patient_headers = make_patient_headers(env["patient"]["id"])
    documents = ["INVOICE", "AUDIOGRAM_OR_WAIVER", "PROOF_OF_PAYMENT", "LMN"]
    claim = validate_success(
        api_client.create_reimbursement_claim(
            {
                "patient_id": env["patient"]["id"],
                "subject_kind": "DEVICE_ORDER",
                "device_order_id": env["order"]["id"],
                "claimed_amount_cents": 50000,
                "document_codes": documents,
                "insurance_benefit_cap_cents": 50000,
                "insurance_benefit_used_cents": 0,
                "fsa_balance_cents": 0,
            },
            patient_headers,
        ),
        201,
    )
    specialist = make_reimbursement_headers("spec-1")
    get_success_data(api_client.submit_reimbursement_claim(claim["id"], specialist))
    get_success_data(api_client.start_reimbursement_review(claim["id"], specialist))

    for requested in (["LMN"], ["INVOICE"]):
        get_success_data(
            api_client.request_reimbursement_info(
                claim["id"], {"requested_document_codes": requested}, specialist
            )
        )
        get_success_data(
            api_client.supply_reimbursement_info(
                claim["id"], {"document_codes": documents}, patient_headers
            )
        )
        get_success_data(api_client.start_reimbursement_review(claim["id"], specialist))

    resp = api_client.request_reimbursement_info(
        claim["id"], {"requested_document_codes": ["LMN"]}, specialist
    )
    validate_error(resp, ApiErrorId.ERR_INFO_REQUEST_LIMIT_REACHED.value)

    frozen = validate_success(api_client.get_reimbursement_claim(claim["id"], specialist))
    assert frozen["status"] == "UNDER_REVIEW", "the refused request must leave the claim in review"
    assert frozen["info_request_count"] == 2, "the counter must stay frozen at the cap of two"


def test_fit_exchange_to_same_configuration_is_refused_without_touching_inventory():
    """PRD §2.9 rule 42: "The requested `to_dome_size` and `to_tip_type` pair differs from
    the order's current `dome_size` and `tip_type` pair, on
    `POST /device-orders/{device_order_id}/fit-exchanges` — otherwise
    `ERR_SAME_FIT_CONFIGURATION` (422)."
    PRD §3.6: an accepted exchange "decrements the target pool's `on_hand_units` and
    increments its `reserved_units`, computes `exchange_fee_cents`, and increments the
    order's `version` by one."

    Design: Corner/validations/validation_same_fit_configuration_rejected_before_inventory_checks
    """
    env = setup_delivered_order(order_overrides=ORDER_200K, measurements=CLEAN_MEASUREMENTS)
    patient_headers = make_patient_headers(env["patient"]["id"])
    order = validate_success(api_client.get_device_order(env["order"]["id"], patient_headers))

    resp = api_client.create_fit_exchange(
        order["id"],
        {
            "to_dome_size": "M",
            "to_tip_type": "OPEN",
            "expected_device_order_version": order["version"],
            "allow_backorder": False,
        },
        patient_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SAME_FIT_CONFIGURATION.value)

    after = validate_success(api_client.get_device_order(order["id"], patient_headers))
    assert after["version"] == order["version"], "a refused exchange must not bump the order version"

    pool = get_pool(env["pool"]["id"])
    assert pool["reserved_units"] == 0, "a refused exchange must not reserve inventory"
    assert_inventory_conservation(pool)
