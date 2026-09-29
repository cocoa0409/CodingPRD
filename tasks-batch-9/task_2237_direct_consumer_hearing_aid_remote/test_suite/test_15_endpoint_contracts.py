"""Endpoint contract tests: CRUD cycles, soft deletes, computed reads and pagination.

Every test exercises the documented request/response contract of one endpoint family and
pins only the observable outcomes the PRD states.
"""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    COMPLIANCE,
    FIRMWARE_ENGINEER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_cash_conservation,
    assert_pagination_meta,
    confirm_and_ship,
    create_devices,
    create_inventory_pool,
    create_provider,
    create_state_policy,
    enroll_care_plan,
    get_success_data,
    is_iso8601_timestamp,
    make_patient_headers,
    place_order,
    register_patient,
    screen_patient,
    scan_shipment,
    set_clock,
    setup_active_care_plan,
    setup_authorized_order,
    setup_red_flagged_patient,
    setup_return_settled,
    simulate_payment,
    validate_error,
    validate_paginated,
    validate_success,
)

ORDER_200K = {
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}

CLEAN_MEASUREMENTS = {"pure_tone_avg_db": 40.0}

TX_POLICY = {
    "state_code": "TX",
    "otc_sales_permitted": True,
    "telehealth_fitting_permitted": True,
    "min_age_years": 21,
    "trial_period_days": 30,
    "restocking_fee_mode": "FLAT_PCT",
    "restocking_fee_pct": 0.05,
    "restocking_fee_cap_cents": 0,
    "shipping_refundable": True,
    "referral_validity_days": 90,
    "waiver_required": False,
    "max_loss_damage_claims": 1,
}


def test_provider_create_read_update_and_filtered_list():
    """PRD §3.4: "A provider is onboarded with a `provider_type` of either
    `TELECARE_FITTER` ... a `daily_capacity_minutes` figure greater than 0 and at most 600
    (ten hours), and an optional `buffer_minutes` gap of between 0 and 60 that defaults to
    10. A new provider's `status` is `ACTIVE`".
    PRD §3.4: "Providers may be listed with a `licensed_state_code` filter that matches a
    single code inside the array."
    PRD §2.8: "Mutating a resource always refreshes its `updated_at` and increments its
    `version`".

    Design: Corner/endpoints/endpoint_provider_full_crud_cycle_with_version_increments
    """
    set_clock("2026-08-01T00:00:00Z")
    created = validate_success(
        api_client.create_provider(
            {
                "provider_type": "TELECARE_FITTER",
                "npi": "1000000020",
                "full_name": "Crud Fitter",
                "licensed_state_codes": ["CA", "NV"],
                "daily_capacity_minutes": 480,
                "buffer_minutes": 10,
            },
            ADMIN,
        ),
        201,
    )
    assert created["version"] == 1, "a freshly created provider starts at version 1"
    assert created["status"] == "ACTIVE", "a new provider's status is ACTIVE"
    assert created["buffer_minutes"] == 10, "the supplied buffer_minutes must be stored"

    fetched = validate_success(api_client.get_provider(created["id"], CARE_OPS))
    assert fetched["npi"] == "1000000020", "the read must return the stored npi"
    assert fetched["daily_capacity_minutes"] == 480, "the read must return the stored capacity"

    patched = validate_success(
        api_client.update_provider(created["id"], {"daily_capacity_minutes": 240}, ADMIN)
    )
    assert patched["daily_capacity_minutes"] == 240, "the amendment must take effect"
    assert patched["buffer_minutes"] == 10, "an unspecified field must be left alone"
    assert patched["version"] == 2, "one amendment increments version by exactly one"

    rows, meta = validate_paginated(
        api_client.list_providers(ADMIN, params={"licensed_state_code": "CA"})
    )
    assert_pagination_meta(meta, 10, 0, 1, False)
    assert rows[0]["id"] == created["id"], "the CA filter must match the provider's array entry"

    rows, meta = validate_paginated(
        api_client.list_providers(ADMIN, params={"licensed_state_code": "TX"})
    )
    assert rows == [], "a state the provider is not licensed in must match nothing"
    assert meta["total_count"] == 0, "an unmatched filter must report a zero total"


def test_patching_patient_state_policy_refreshes_denormalized_state_code():
    """PRD §3.1: "The server denormalizes `state_code` onto the patient from the chosen
    policy and refreshes that copy whenever `state_policy_id` changes on an amendment."
    PRD §4: `GET /hearing-care/patients` — "List patients, filterable by policy (reverse
    reachability for Patient.state_policy_id)".

    Design: Corner/endpoints/endpoint_patch_patient_state_policy_redenormalizes_state_code
    """
    set_clock("2026-08-01T00:00:00Z")
    ca_policy = create_state_policy(state_code="CA")
    tx_policy = validate_success(api_client.create_state_policy(TX_POLICY, ADMIN), 201)
    patient = register_patient(ca_policy["id"], email="e2@x.test", full_name="E Two", age_years=70)
    assert patient["state_code"] == "CA", "registration denormalizes the policy's state code"

    amended = validate_success(
        api_client.update_patient(patient["id"], {"state_policy_id": tx_policy["id"]}, CARE_OPS)
    )
    assert amended["state_policy_id"] == tx_policy["id"], "the amendment must repoint the policy"
    assert amended["state_code"] == "TX", "state_code must be refreshed from the new policy"
    assert amended["email"] == "e2@x.test", "email must be untouched by the policy amendment"
    assert amended["full_name"] == "E Two", "full_name must be untouched by the policy amendment"
    assert amended["age_years"] == 70, "age_years must be untouched by the policy amendment"
    assert amended["version"] == 2, "one amendment increments version by exactly one"

    _rows, meta = validate_paginated(
        api_client.list_patients(CARE_OPS, params={"state_policy_id": ca_policy["id"]})
    )
    assert meta["total_count"] == 0, "the patient must no longer be reachable from the old policy"


def test_soft_retired_policy_stays_readable_and_keeps_serving_existing_patients():
    """PRD §2.5: "Soft-retiring a policy through `DELETE /state-policies/{id}` sets
    `is_retired` to true and increments `version`; retired policies remain readable and
    remain pinned on existing orders".
    PRD §3.1: "A policy is never hard-deleted; retiring one sets `is_retired` (a
    system-managed flag defaulting to false), leaving it queryable and leaving it in force on
    any order that already pinned it."

    Design: Corner/endpoints/endpoint_soft_retired_policy_excluded_from_default_list_but_still_referenced
    """
    set_clock("2026-08-01T00:00:00Z")
    ca_policy = create_state_policy(state_code="CA")
    validate_success(api_client.create_state_policy(TX_POLICY, ADMIN), 201)
    patient = register_patient(ca_policy["id"], email="e3@x.test", full_name="E Three", age_years=70)

    retired = validate_success(api_client.delete_state_policy(ca_policy["id"], ADMIN))
    assert retired["is_retired"] is True, "the soft delete must flip is_retired"
    assert retired["version"] == 2, "retiring increments the policy version by exactly one"

    still_readable = validate_success(api_client.get_state_policy(ca_policy["id"], ADMIN))
    assert still_readable["id"] == ca_policy["id"], "a retired policy must remain readable by id"
    assert still_readable["is_retired"] is True, "the read must report the retired flag"

    linked = validate_success(api_client.get_patient(patient["id"], CARE_OPS))
    assert linked["state_policy_id"] == ca_policy["id"], (
        "the soft delete must not break the patient's live reference"
    )
    assert linked["state_code"] == "CA", "the denormalized state code must survive retirement"


def test_discontinued_pool_blocks_confirm_fit_without_reserving_anything():
    """PRD §3.5: "Discontinuing a pool sets `is_discontinued` to true; a discontinued pool
    refuses new reservations, rejected as `ERR_POOL_DISCONTINUED`, but stays queryable."
    PRD §2.9 rule 51: "The target pool's `is_discontinued` is false, on
    `POST /device-orders/{id}/confirm-fit` and
    `POST /device-orders/{device_order_id}/fit-exchanges` — otherwise
    `ERR_POOL_DISCONTINUED` (409)."

    Design: Corner/endpoints/endpoint_conditional_action_discontinued_pool_blocks_confirm_fit
    """
    env = setup_authorized_order(order_overrides=ORDER_200K, measurements=CLEAN_MEASUREMENTS)
    discontinued = validate_success(api_client.discontinue_inventory_pool(env["pool"]["id"], ADMIN))
    assert discontinued["is_discontinued"] is True, "DELETE must flag the pool as discontinued"

    resp = api_client.confirm_fit(env["order"]["id"], CARE_OPS)
    validate_error(resp, ApiErrorId.ERR_POOL_DISCONTINUED.value)

    order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
        "the refused confirmation must leave the order awaiting confirmation"
    )
    devices, meta = validate_paginated(
        api_client.list_devices(CARE_OPS, params={"device_order_id": env["order"]["id"]})
    )
    assert devices == [], "a refused confirmation must assign no device"
    assert meta["total_count"] == 0, "a refused confirmation must reserve nothing for the order"


def test_delete_patient_deactivates_the_row_instead_of_removing_it():
    """PRD §3.1: "Deactivation is available to a platform operator from `REGISTERED`, from
    `CANDIDATE_APPROVED` and from `MEDICALLY_DISQUALIFIED`, and in all three cases requires
    that the patient hold no `DeviceOrder` whose `fulfillment_status` is anything other than
    `RETURNED` or `CANCELLED`. All three set `deactivated_at` to the current logical clock".
    PRD §2.1 rule 3: "For an entity-backed role, `X-User-ID` is the `id` of an existing
    backing row (a `Patient` or a `Provider`) that is neither `DEACTIVATED` nor
    `OFFBOARDED`. This applies to every endpoint called as `Patient`,
    `HearingProfessional` or `LicensedAudiologist` — otherwise `ERR_IDENTITY_NOT_FOUND`
    (401)."

    Design: Corner/endpoints/endpoint_delete_patient_deactivates_and_invalidates_draft_screenings
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy(state_code="CA")
    patient = register_patient(policy["id"], email="e5@x.test", full_name="E Five", age_years=70)
    assert patient["status"] == "REGISTERED", "a freshly registered patient is REGISTERED"

    deactivated = validate_success(api_client.delete_patient(patient["id"], ADMIN))
    assert deactivated["status"] == "DEACTIVATED", "the delete is a deactivation, not a removal"
    assert deactivated["deactivated_at"] is not None, "deactivation must stamp deactivated_at"
    assert is_iso8601_timestamp(deactivated["deactivated_at"]), (
        "deactivated_at must be an ISO 8601 UTC timestamp"
    )

    still_readable = validate_success(api_client.get_patient(patient["id"], CARE_OPS))
    assert still_readable["id"] == patient["id"], "the deactivated row must still be readable"

    resp = api_client.start_screening_session(
        patient["id"], {}, make_patient_headers(patient["id"])
    )
    validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_FOUND.value)


def test_order_summary_is_a_pure_read_that_reconciles_cash_after_settlement():
    """PRD §3.5: "A dedicated computed read on an order exposes its cash-conservation
    breakdown, its position in the trial, and its fit-exchange history in one response."
    PRD §3.6: "a settlement whose `restocking_fee_cents` plus
    `non_refundable_shipping_cents` exceeds 0 with a positive `refund_amount_cents` moves
    `CAPTURED → PARTIALLY_REFUNDED`, adding `refund_amount_cents` to `refunded_cents` and
    adding the retained restocking plus non-refundable shipping to `retained_cents`, then
    recomputing `open_balance_cents` — which should reach 0 on a whole-order return."
    PRD §2.6: "the amount captured equals the amount refunded plus the amount lawfully
    retained plus the open balance still attributable to a kept device."

    Design: Corner/endpoints/endpoint_computed_read_order_summary_conserves_cash_after_settlement
    """
    env = setup_return_settled(
        inspection_grade="RESELLABLE",
        at_iso="2026-08-11T00:00:00Z",
        order_overrides=ORDER_200K,
        measurements=CLEAN_MEASUREMENTS,
    )
    order_id = env["order"]["id"]
    before = validate_success(api_client.get_device_order(order_id, CARE_OPS))

    summary = validate_success(api_client.get_device_order_summary(order_id, COMPLIANCE))
    again = validate_success(api_client.get_device_order_summary(order_id, COMPLIANCE))
    assert summary == again, "a computed read must be repeatable with an identical body"

    after = validate_success(api_client.get_device_order(order_id, CARE_OPS))
    assert after["version"] == before["version"], "the computed read must mutate nothing"

    assert after["tax_cents"] == 14500, "tax is 200000 * 0.0725 rounded half up"
    assert after["total_cents"] == 215995, "total is 200000 + 1495 shipping + 14500 tax"
    assert after["captured_cents"] == 215995, "shipping captured the whole total"
    assert after["refunded_cents"] == 194500, "the refund is the total less retained amounts"
    assert after["retained_cents"] == 21495, (
        "retained is the 10 percent restocking fee of 20000 plus 1495 non-refundable shipping"
    )
    assert after["open_balance_cents"] == 0, "a whole-order return drives the open balance to 0"
    assert after["payment_status"] == "PARTIALLY_REFUNDED", (
        "a settlement retaining restocking moves payment to PARTIALLY_REFUNDED"
    )
    assert after["fulfillment_status"] == "RETURNED", "the settled return leaves fulfillment RETURNED"
    assert_cash_conservation(after)


def test_referral_evaluation_booking_links_provider_and_referral():
    """PRD §3.3: "Booking the evaluation moves the referral `OPEN → SCHEDULED` and stamps
    its `provider_id` with the booked provider."
    PRD §2.5: "A foreign key supplied in a request body rather than a path — `state_policy_id`,
    `patient_id`, `provider_id`, `device_order_id`, `device_id`, `provider_referral_id`,
    `repair_order_id`, `care_plan_subscription_id`, `originating_repair_order_id`,
    `appeal_of_claim_id`, `firmware_rollout_id`, `supersedes_session_id` — that resolves to
    no row produces `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."
    PRD §3.4: "the provider's `booked_minutes_on_focus_date` and `utilization_pct` are
    recomputed, the latter as 100 multiplied by `booked_minutes_on_focus_date` divided by
    `daily_capacity_minutes`, rounded half up to one decimal place."

    Design: Corner/endpoints/endpoint_cross_reference_link_referral_evaluation_binds_both_entities
    """
    env = setup_red_flagged_patient(symptom_codes=("VERTIGO",), measurements=CLEAN_MEASUREMENTS)
    provider = create_provider(
        provider_type="LICENSED_AUDIOLOGIST",
        npi="1000000021",
        licensed_state_codes=["CA"],
        daily_capacity_minutes=480,
        buffer_minutes=0,
    )
    patient_headers = make_patient_headers(env["patient"]["id"])
    booking = {
        "patient_id": env["patient"]["id"],
        "session_type": "REFERRAL_EVALUATION",
        "provider_id": provider["id"],
        "provider_referral_id": env["referral"]["id"],
        "scheduled_start_utc": "2026-08-20T10:00:00Z",
        "scheduled_end_utc": "2026-08-20T11:00:00Z",
    }

    resp = api_client.create_remote_fitting_session(
        dict(booking, provider_id=NON_EXISTENT_UUID), patient_headers
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)
    untouched = validate_success(api_client.get_provider_referral(env["referral"]["id"], CARE_OPS))
    assert untouched["status"] == "OPEN", "a rejected booking must leave the referral OPEN"

    session = validate_success(api_client.create_remote_fitting_session(booking, patient_headers), 201)
    assert session["status"] == "SCHEDULED", "an accepted booking lands in SCHEDULED"
    assert session["duration_minutes"] == 60, "a 10:00-11:00 slot is 60 minutes long"
    assert session["provider_referral_id"] == env["referral"]["id"], (
        "the session must link the referral it evaluates"
    )

    referral = validate_success(api_client.get_provider_referral(env["referral"]["id"], CARE_OPS))
    assert referral["status"] == "SCHEDULED", "booking moves the referral OPEN to SCHEDULED"
    assert referral["provider_id"] == provider["id"], "booking stamps the referral's provider_id"

    rows, meta = validate_paginated(
        api_client.list_remote_fitting_sessions(
            CARE_OPS, params={"provider_referral_id": env["referral"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "exactly one session must reference the referral"
    assert rows[0]["id"] == session["id"], "the filtered list must return the booked session"

    booked = validate_success(api_client.get_provider(provider["id"], CARE_OPS))
    assert booked["booked_minutes_on_focus_date"] == 60, "the 60-minute booking must be counted"
    assert booked["utilization_pct"] == 12.5, "utilization is 100 * 60 / 480"


def test_pagination_bounds_are_one_through_one_hundred_with_non_negative_offset():
    """PRD §2.9 rule 14: "`limit` is an integer between 1 and 100 inclusive and `offset` is
    an integer of at least 0, on every list endpoint — otherwise `ERR_INVALID_PAGINATION`
    (400)."
    PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset`
    defaults to 0 and has a minimum of 0. A `limit` below 1, a `limit` above 100, or an
    `offset` below 0 is rejected with `ERR_INVALID_PAGINATION` (HTTP 400); both must be
    integers."
    PRD §2.3: the meta block carries "`total_count` (the number of rows matching the filters
    before pagination) and `has_more` (true when `offset` plus the number of returned rows is
    below `total_count`)".

    Design: Corner/endpoints/endpoint_pagination_boundaries_reject_zero_and_one_hundred_one
    """
    set_clock("2026-08-01T00:00:00Z")
    create_devices(3)

    for params in ({"limit": 0}, {"limit": 101}, {"limit": -1}, {"offset": -1}):
        resp = api_client.list_devices(ADMIN, params=params)
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    rows, meta = validate_paginated(api_client.list_devices(ADMIN, params={"limit": 1}))
    assert len(rows) == 1, "limit 1 must return exactly one row"
    assert_pagination_meta(meta, 1, 0, 3, True)

    rows, meta = validate_paginated(api_client.list_devices(ADMIN, params={"limit": 100}))
    assert len(rows) == 3, "limit 100 must return all three devices"
    assert_pagination_meta(meta, 100, 0, 3, False)

    rows, meta = validate_paginated(api_client.list_devices(ADMIN, params={"limit": 2, "offset": 5}))
    assert rows == [], "an offset past the end must return no rows"
    assert_pagination_meta(meta, 2, 5, 3, False)


def test_paged_rollout_reads_partition_the_cohort_exactly():
    """PRD §3.9: "The first `batch_size` candidates are taken, and for each one a
    `FirmwareRollout` is created in `PENDING` with `selection_rank` counting from 1 in that
    order and with `from_version_observed` captured from the device's current
    `firmware_version`."
    PRD §2.3: the meta block carries "`limit` (the effective page size), `offset` (the
    effective starting index), `total_count` (the number of rows matching the filters before
    pagination) and `has_more` (true when `offset` plus the number of returned rows is below
    `total_count`)".
    PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100."

    Design: Corner/endpoints/endpoint_pagination_with_filtering_partitions_rollouts_without_overlap
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy(state_code="CA")
    create_inventory_pool(restock_units=5, sku="NEO-M-OPEN", model="NEO", dome_size="M", tip_type="OPEN")
    create_devices(1, serial_number="SN-E901", model="NEO", firmware_version="4.0.0")
    create_devices(1, serial_number="SN-E902", model="NEO", firmware_version="4.0.0")

    for email in ("e9a@x.test", "e9b@x.test"):
        patient = register_patient(policy["id"], email=email, age_years=70)
        screen_patient(patient["id"], **CLEAN_MEASUREMENTS)
        order = place_order(patient["id"], **ORDER_200K)
        enroll_care_plan(
            {"patient": patient, "order": order},
            plan_tier="STANDARD",
            base_fee_cents=9900,
            firmware_auto_update_enabled=True,
        )
        simulate_payment(order["id"])
        confirm_and_ship(order["id"])
        scan_shipment(order["id"], "DELIVERED")

    campaign = validate_success(
        api_client.create_firmware_campaign(
            {
                "campaign_code": "CAMP-E9",
                "model": "NEO",
                "from_version": "4.0.0",
                "to_version": "4.1.0",
                "is_mandatory_safety": False,
                "batch_size": 2,
                "max_concurrent_installs": 5,
                "window_start_utc": "2026-08-05T00:00:00Z",
                "window_end_utc": "2026-08-30T00:00:00Z",
            },
            FIRMWARE_ENGINEER,
        ),
        201,
    )
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    set_clock("2026-08-05T00:00:00Z")
    get_success_data(api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))

    first_page, meta = validate_paginated(
        api_client.list_campaign_rollouts(
            campaign["id"], FIRMWARE_ENGINEER, params={"limit": 1, "offset": 0}
        )
    )
    assert len(first_page) == 1, "limit 1 must return exactly one rollout"
    assert_pagination_meta(meta, 1, 0, 2, True)

    second_page, meta = validate_paginated(
        api_client.list_campaign_rollouts(
            campaign["id"], FIRMWARE_ENGINEER, params={"limit": 1, "offset": 1}
        )
    )
    assert len(second_page) == 1, "the second page must return exactly one rollout"
    assert_pagination_meta(meta, 1, 1, 2, False)
    assert second_page[0]["id"] != first_page[0]["id"], "the two pages must not overlap"

    ranks = {first_page[0]["selection_rank"], second_page[0]["selection_rank"]}
    assert ranks == {1, 2}, "the cohort's selection ranks count from 1 with no duplicates"
    assert first_page[0]["status"] == "PENDING", "an advanced cohort is created in PENDING"
    assert second_page[0]["status"] == "PENDING", "an advanced cohort is created in PENDING"

    all_rows, meta = validate_paginated(
        api_client.list_campaign_rollouts(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert len(all_rows) == 2, "the unpaged read must return both rollouts"
    assert_pagination_meta(meta, 10, 0, 2, False)


def test_replayed_delivered_scan_is_rejected_and_mints_no_second_trial():
    """PRD §2.9 rule 22: "The targeted entity's current state is a declared origin state for
    the requested transition, on every action endpoint that drives a state transition —
    otherwise `ERR_INVALID_STATE` (409)."
    PRD §3.5: "A carrier scan against a named `device_order_id` with an `event` of
    `DELIVERED` moves fulfillment `SHIPPED → DELIVERED`, stamps `delivered_at`, sets the
    device to `WITH_PATIENT`, creates the trial period described in §3.6 in `ACTIVE` with
    `started_at` equal to `delivered_at`, and activates any care plan attached to that order
    which is still `TRIALING`."
    PRD §3.8: "Delivery of the attached order moves the plan `TRIALING → ACTIVE`, setting
    `cycle_start_utc` to the order's `delivered_at`, `cycle_end_utc` to `cycle_start_utc`
    plus 30 days, and `cycle_ordinal` to 0."

    Design: Corner/endpoints/endpoint_action_replay_second_delivered_scan_creates_no_second_trial
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
    order_id = env["order"]["id"]

    resp = api_client.scan_shipment({"device_order_id": order_id, "event": "DELIVERED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    trials, meta = validate_paginated(
        api_client.list_trial_periods(CARE_OPS, params={"device_order_id": order_id})
    )
    assert meta["total_count"] == 1, "the replayed scan must not mint a second trial period"
    assert trials[0]["status"] == "ACTIVE", "the single trial must remain ACTIVE"

    plan = validate_success(api_client.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
    assert plan["status"] == "ACTIVE", "the plan activated by the first delivery stays ACTIVE"
    assert plan["cycle_ordinal"] == 0, "the replayed scan must not advance the billing cycle"

    order = validate_success(api_client.get_device_order(order_id, CARE_OPS))
    assert order["fulfillment_status"] == "DELIVERED", "the order stays DELIVERED"
    assert plan["cycle_start_utc"] == order["delivered_at"], (
        "the plan's cycle starts at the order's delivered_at"
    )
