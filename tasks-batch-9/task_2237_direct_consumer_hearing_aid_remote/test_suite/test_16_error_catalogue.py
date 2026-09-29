"""Error-catalogue compliance: each guard returns its own error id.

Every test drives the public API only, starting from an empty database with the
logical clock at its startup default of 2026-08-01T00:00:00Z.
"""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    COMPLIANCE,
    COMPLIANCE_2,
    FIRMWARE_ENGINEER,
    NON_EXISTENT_UUID,
    REIMBURSEMENT,
    REIMBURSEMENT_2,
    REPAIR_TECH,
    ApiErrorId,
    assert_same_instant,
    bootstrap_environment,
    clear_referral,
    confirm_and_ship,
    create_provider,
    create_state_policy,
    enroll_care_plan,
    get_pool,
    get_success_data,
    issue_return_authorization,
    make_licensed_audiologist_headers,
    make_patient_headers,
    open_repair_order,
    place_order,
    register_patient,
    scan_shipment,
    screen_patient,
    set_clock,
    setup_active_care_plan,
    setup_delivered_order,
    setup_evaluated_referral,
    setup_red_flagged_patient,
    setup_return_settled,
    setup_scheduled_campaign,
    setup_screened_patient,
    setup_triaged_warranty_claim,
    simulate_payment,
    validate_error,
    validate_paginated,
    validate_success,
)

# Canonical order economics used throughout this module: a 200,000-cent device
# with no discount, no accessories and 1,495 cents of shipping.
_ORDER = {
    "model": "NEO",
    "dome_size": "M",
    "tip_type": "OPEN",
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}

# Measurements that emit no finding at all, so the screening outcome is PASS.
_CLEAN_SCREEN = {
    "pure_tone_avg_db": 40.0,
    "asymmetry_db": 5.0,
    "self_reported_difficulty_score": 20,
    "speech_in_noise_pct": 70.0,
    "symptom_codes": [],
}

# A request that carries neither X-User-ID nor X-User-Role.
_NO_AUTH_HEADERS = {"Content-Type": "application/json"}

# The required document set for a DEVICE_ORDER reimbursement subject.
_DEVICE_ORDER_DOCS = ["INVOICE", "AUDIOGRAM_OR_WAIVER", "PROOF_OF_PAYMENT", "LMN"]


def _delivered_env(**kwargs):
    """Screened patient → order → authorized → confirmed → shipped → delivered."""
    kwargs.setdefault("order_overrides", dict(_ORDER))
    kwargs.setdefault("measurements", dict(_CLEAN_SCREEN))
    return setup_delivered_order(**kwargs)


def _authorized_order_for_red_flagged_patient(api, env):
    """Place and authorize an order for a patient who already holds an open flag."""
    order = place_order(env["patient"]["id"], **_ORDER)
    env["order"] = simulate_payment(order["id"])
    return env["order"]


def _campaign_payload(**overrides):
    """A campaign that respects subscriber consent and opens on the clock's start."""
    payload = {
        "campaign_code": f"CAMP-{overrides.pop('code_suffix', 'X')}",
        "model": "NEO",
        "from_version": "4.0.0",
        "to_version": "4.1.0",
        "window_start_utc": "2026-08-01T00:00:00Z",
        "window_end_utc": "2026-08-30T00:00:00Z",
        "batch_size": 5,
        "max_concurrent_installs": 5,
        "is_mandatory_safety": False,
    }
    payload.update(overrides)
    return payload


def _device_for_order(api, order_id, headers=CARE_OPS):
    """The device assigned to an order, resolved through the devices list filter."""
    rows, _meta = validate_paginated(api.list_devices(headers, params={"device_order_id": order_id}))
    assert rows, f"expected one device assigned to order {order_id}"
    return rows[0]


class TestAuthenticationErrors:
    """Rules 1 and 3 of the request evaluation order."""

    def test_patient_read_without_auth_headers_is_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and `X-User-Role`.
        If either header is absent or blank, the request fails with
        `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

        Design: Corner/errors/error_missing_auth_headers_when_patient_identity_omitted
        """
        policy = create_state_policy()
        patient = register_patient(policy["id"])

        resp = api.get_patient(patient["id"], _NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

        # The very same read succeeds once the identity headers are present.
        data = validate_success(api.get_patient(patient["id"], make_patient_headers(patient["id"])))
        assert data["id"] == patient["id"], "the authenticated read must return the same patient"

    def test_patient_read_with_unknown_user_id_is_rejected(self, api):
        """PRD §2.1: "If an entity-backed role's `X-User-ID` matches no row of its backing
        entity, or matches a `Patient` whose `status` is `DEACTIVATED` or a `Provider` whose
        `status` is `OFFBOARDED`, the request fails with `ERR_IDENTITY_NOT_FOUND` (HTTP 401)."

        Design: Corner/errors/error_identity_not_found_for_unknown_patient_user_id
        """
        policy = create_state_policy()
        patient = register_patient(policy["id"])

        resp = api.get_patient(patient["id"], make_patient_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_FOUND.value)

        data = validate_success(api.get_patient(patient["id"], make_patient_headers(patient["id"])))
        assert data["id"] == patient["id"], "the acting patient must be able to read itself"


class TestMedicalAndRegulatoryErrors:
    """Rules 25 through 33: the medical safety and state regulation band."""

    def test_order_placement_blocked_when_state_prohibits_otc_sales(self, api):
        """PRD §2.9 rule 25: "The pinned policy's `otc_sales_permitted` is true, on
        `POST /patients/{patient_id}/device-orders` — otherwise
        `ERR_OTC_SALES_PROHIBITED_IN_STATE` (422)."

        Design: Corner/errors/error_otc_sales_prohibited_in_state_blocks_order_creation
        """
        env = setup_screened_patient(
            policy_overrides={"otc_sales_permitted": False},
            measurements=dict(_CLEAN_SCREEN),
        )
        patient_id = env["patient"]["id"]
        assert env["patient"]["status"] != "MEDICALLY_DISQUALIFIED", "setup must leave a candidate"

        resp = api.create_device_order(patient_id, dict(_ORDER), make_patient_headers(patient_id))
        validate_error(resp, ApiErrorId.ERR_OTC_SALES_PROHIBITED_IN_STATE.value)

        rows, meta = validate_paginated(api.list_device_orders(CARE_OPS, params={"patient_id": patient_id}))
        assert meta["total_count"] == 0, "a prohibited sale must not persist an order"
        assert rows == [], "a prohibited sale must not persist an order"

        patient = validate_success(api.get_patient(patient_id, CARE_OPS))
        assert patient["status"] == "CANDIDATE_APPROVED", (
            "a refused order must not disturb the patient's candidacy status"
        )

    def test_confirm_fit_blocked_when_age_edited_below_state_minimum(self, api):
        """PRD §2.9 rule 26: "The patient's `age_years` is at least the policy's
        `min_age_years`, on `POST /patients/{patient_id}/device-orders` and
        `POST /device-orders/{id}/confirm-fit` — otherwise `ERR_AGE_BELOW_STATE_MINIMUM` (422)."

        PRD §3.5: "Confirmation moves the fulfillment dimension `PENDING_FIT_CONFIRM →
        READY_TO_SHIP`, reserves a unit by decrementing that pool's `on_hand_units` by one
        and incrementing its `reserved_units` by one".

        Design: Corner/errors/error_age_below_state_minimum_blocks_confirm_fit_after_age_edit
        """
        env = setup_screened_patient(
            policy_overrides={"min_age_years": 21},
            patient_overrides={"age_years": 25},
            measurements=dict(_CLEAN_SCREEN),
        )
        patient_id = env["patient"]["id"]
        order = place_order(patient_id, **_ORDER)
        simulate_payment(order["id"])

        # The declared age is amended downwards after checkout.
        amended = validate_success(api.update_patient(patient_id, {"age_years": 19}, CARE_OPS))
        assert amended["age_years"] == 19, "the amendment must persist the new age"

        before = validate_success(api.get_device_order(order["id"], CARE_OPS))

        resp = api.confirm_fit(order["id"], CARE_OPS)
        validate_error(resp, ApiErrorId.ERR_AGE_BELOW_STATE_MINIMUM.value)

        after = validate_success(api.get_device_order(order["id"], CARE_OPS))
        assert after["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
            "a refused confirmation must leave the fulfillment dimension untouched"
        )
        assert after["version"] == before["version"], (
            "a refused confirmation must not increment the order version"
        )
        pool = get_pool(env["pool"]["id"])
        assert pool["on_hand_units"] == 5, "no unit may be reserved by a refused confirmation"
        assert pool["reserved_units"] == 0, "no unit may be reserved by a refused confirmation"

    def test_new_fitting_session_blocked_for_medically_disqualified_patient(self, api):
        """PRD §2.9 rule 27: "The patient's `status` is not `MEDICALLY_DISQUALIFIED`, on
        `POST /patients/{patient_id}/device-orders`, `POST /remote-fitting-sessions` and
        `POST /device-orders/{id}/confirm-fit` — otherwise
        `ERR_PATIENT_MEDICALLY_DISQUALIFIED` (409)."

        PRD §3.3: "A `NOT_CLEARED` determination moves the referral `EVALUATED → NOT_CLEARED`
        and drives the patient `REFERRAL_REQUIRED → MEDICALLY_DISQUALIFIED`."

        Design: Corner/errors/error_patient_medically_disqualified_blocks_new_session
        """
        env = setup_evaluated_referral(
            symptom_codes=("VERTIGO",),
            measurements=dict(_CLEAN_SCREEN),
            provider_overrides={"daily_capacity_minutes": 480, "buffer_minutes": 0},
        )
        referral = clear_referral(env, outcome="NOT_CLEARED", note="retrocochlear pathology suspected")
        assert referral["clearance_outcome"] == "NOT_CLEARED", "setup must record the refusal"

        patient_id = env["patient"]["id"]
        patient = validate_success(api.get_patient(patient_id, CARE_OPS))
        assert patient["status"] == "MEDICALLY_DISQUALIFIED", (
            "a NOT_CLEARED determination must disqualify the patient"
        )

        resp = api.create_remote_fitting_session(
            {
                "patient_id": patient_id,
                "session_type": "FOLLOW_UP",
                "scheduled_start_utc": "2026-08-10T10:00:00Z",
                "scheduled_end_utc": "2026-08-10T10:30:00Z",
                "provider_id": env["provider"]["id"],
            },
            make_patient_headers(patient_id),
        )
        validate_error(resp, ApiErrorId.ERR_PATIENT_MEDICALLY_DISQUALIFIED.value)

        rows, meta = validate_paginated(
            api.list_remote_fitting_sessions(CARE_OPS, params={"patient_id": patient_id})
        )
        assert meta["total_count"] == 1, "the refused booking must not be persisted"
        assert rows[0]["id"] == env["session"]["id"], "only the completed evaluation may remain"

    def test_confirm_fit_blocked_while_a_mandatory_referral_is_open(self, api):
        """PRD §2.9 rule 28: "The patient's `open_mandatory_flag_count` is zero, on
        `POST /device-orders/{id}/confirm-fit` and `POST /device-orders/{id}/ship` —
        otherwise `ERR_MANDATORY_REFERRAL_OPEN` (409)."

        PRD §2.9: "A fit confirmation for a patient with an open mandatory red flag whose
        model-dome-tip triple has no pool row violates both rule 28 and rule 13; rule 13 wins,
        so the caller sees `ERR_INVENTORY_POOL_NOT_FOUND`, because referential existence is
        checked before the safety band."

        Design: Corner/errors/error_mandatory_referral_open_blocks_confirm_fit_when_pool_exists
        """
        env = setup_red_flagged_patient(
            symptom_codes=("VERTIGO",),
            measurements=dict(_CLEAN_SCREEN),
        )
        patient = validate_success(api.get_patient(env["patient"]["id"], CARE_OPS))
        assert patient["open_mandatory_flag_count"] == 1, "setup must leave one open mandatory flag"

        order = _authorized_order_for_red_flagged_patient(api, env)
        assert order["payment_status"] == "AUTHORIZED", "setup must authorize the order"

        # The matching pool row exists, so rule 13 cannot pre-empt rule 28.
        pool = get_pool(env["pool"]["id"])
        assert pool["on_hand_units"] == 5, "the model-dome-tip triple must have a stocked pool row"

        resp = api.confirm_fit(order["id"], CARE_OPS)
        validate_error(resp, ApiErrorId.ERR_MANDATORY_REFERRAL_OPEN.value)

        after = validate_success(api.get_device_order(order["id"], CARE_OPS))
        assert after["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
            "a refused confirmation must leave the order in PENDING_FIT_CONFIRM"
        )
        assert after["version"] == order["version"], (
            "a refused confirmation must not increment the order version"
        )
        pool_after = get_pool(env["pool"]["id"])
        assert pool_after["on_hand_units"] == 5, "no unit may be reserved by a refused confirmation"
        assert pool_after["reserved_units"] == 0, "no unit may be reserved by a refused confirmation"

    def test_referral_evaluation_booking_requires_provider_licensed_in_patient_state(self, api):
        """PRD §2.9 rule 31: "For a `REFERRAL_EVALUATION` booking or a clearance determination,
        the provider's `licensed_state_codes` contains the patient's `state_code` regardless of
        telehealth permission. This applies to `POST /remote-fitting-sessions` with
        `session_type` `REFERRAL_EVALUATION` and to `POST /provider-referrals/{id}/determination`
        — otherwise `ERR_PROVIDER_NOT_LICENSED_IN_STATE` (422)."

        PRD §3.4: "For a `REFERRAL_EVALUATION` booking the state-licensure requirement holds
        regardless of the telehealth flag, and its failure is
        `ERR_PROVIDER_NOT_LICENSED_IN_STATE`."

        Design: Corner/errors/error_provider_not_licensed_in_state_on_referral_evaluation
        """
        env = setup_red_flagged_patient(
            symptom_codes=("VERTIGO",),
            measurements=dict(_CLEAN_SCREEN),
            policy_overrides={"telehealth_fitting_permitted": True},
        )
        patient_id = env["patient"]["id"]
        out_of_state = create_provider(
            licensed_state_codes=["NV"], daily_capacity_minutes=480, buffer_minutes=0
        )
        in_state = create_provider(
            licensed_state_codes=["CA"], daily_capacity_minutes=480, buffer_minutes=0
        )

        booking = {
            "patient_id": patient_id,
            "session_type": "REFERRAL_EVALUATION",
            "scheduled_start_utc": "2026-08-05T09:00:00Z",
            "scheduled_end_utc": "2026-08-05T09:30:00Z",
            "provider_referral_id": env["referral"]["id"],
        }
        resp = api.create_remote_fitting_session(
            dict(booking, provider_id=out_of_state["id"]), make_patient_headers(patient_id)
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_LICENSED_IN_STATE.value)

        referral = validate_success(api.get_provider_referral(env["referral"]["id"], CARE_OPS))
        assert referral["status"] == "OPEN", "a refused booking must leave the referral OPEN"
        assert referral["provider_id"] is None, "a refused booking must not stamp provider_id"

        # The identical booking against a CA-licensed audiologist is accepted.
        ok = validate_success(
            api.create_remote_fitting_session(
                dict(booking, provider_id=in_state["id"]), make_patient_headers(patient_id)
            ),
            201,
        )
        assert ok["status"] == "SCHEDULED", "an in-state booking must confirm the slot"

    def test_referral_booking_without_provider_fails_when_no_candidate_qualifies(self, api):
        """PRD §3.3: "candidates are the providers whose `provider_type` is
        `LICENSED_AUDIOLOGIST`, whose `status` is `ACTIVE`, whose `licensed_state_codes`
        contains the patient's `state_code` ... An empty candidate set is rejected with
        `ERR_NO_ELIGIBLE_PROVIDER`."

        PRD §2.9 rule 57: "Referral-provider selection produced a non-empty candidate set, on
        `POST /remote-fitting-sessions` when `session_type` is `REFERRAL_EVALUATION` and
        `provider_id` is omitted — otherwise `ERR_NO_ELIGIBLE_PROVIDER` (409)."

        Design: Corner/errors/error_no_eligible_provider_when_selector_finds_nobody
        """
        env = setup_red_flagged_patient(
            symptom_codes=("VERTIGO",),
            measurements=dict(_CLEAN_SCREEN),
        )
        patient_id = env["patient"]["id"]
        # A CA fitter is the wrong provider_type; the audiologist is licensed elsewhere.
        create_provider(provider_type="TELECARE_FITTER", licensed_state_codes=["CA"])
        create_provider(provider_type="LICENSED_AUDIOLOGIST", licensed_state_codes=["NV"])

        resp = api.create_remote_fitting_session(
            {
                "patient_id": patient_id,
                "session_type": "REFERRAL_EVALUATION",
                "scheduled_start_utc": "2026-08-05T09:00:00Z",
                "scheduled_end_utc": "2026-08-05T09:30:00Z",
                "provider_referral_id": env["referral"]["id"],
            },
            make_patient_headers(patient_id),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PROVIDER.value)

        _rows, meta = validate_paginated(
            api.list_remote_fitting_sessions(CARE_OPS, params={"patient_id": patient_id})
        )
        assert meta["total_count"] == 0, "a refused selection must not persist a session"
        referral = validate_success(api.get_provider_referral(env["referral"]["id"], CARE_OPS))
        assert referral["status"] == "OPEN", "a refused selection must leave the referral OPEN"

    def test_manual_enrollment_blocked_when_subscriber_declined_auto_updates(self, api):
        """PRD §2.9 rule 33: "A firmware install is only offered when the subscriber's
        `firmware_auto_update_enabled` is true or the campaign's `is_mandatory_safety` is true,
        on `POST /firmware-rollouts/{id}/offer` and
        `POST /firmware-campaigns/{campaign_id}/manual-enrollments` — otherwise
        `ERR_AUTO_UPDATE_NOT_CONSENTED` (422)."

        PRD §3.9: "Manual enrolment respects subscriber consent exactly as an automatic offer
        does."

        PRD §3.9: "An empty candidate set is refused with `ERR_NO_ELIGIBLE_DEVICES`."

        Design: Corner/errors/error_auto_update_not_consented_on_manual_enrollment
        """
        env = setup_active_care_plan(
            plan_overrides={"base_fee_cents": 9900, "firmware_auto_update_enabled": False},
            order_overrides=dict(_ORDER),
            measurements=dict(_CLEAN_SCREEN),
        )
        assert env["plan"]["status"] == "ACTIVE", "delivery must activate the plan"
        assert env["plan"]["firmware_auto_update_enabled"] is False, "setup must decline consent"

        campaign = setup_scheduled_campaign(**_campaign_payload(code_suffix="X9"))
        device = validate_success(api.get_device(env["assigned_device"]["id"], FIRMWARE_ENGINEER))

        resp = api.create_manual_enrollment(
            campaign["id"],
            {"device_id": device["id"], "expected_device_version": device["version"]},
            FIRMWARE_ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_AUTO_UPDATE_NOT_CONSENTED.value)

        after = validate_success(api.get_device(device["id"], FIRMWARE_ENGINEER))
        assert after["version"] == device["version"], (
            "a refused enrolment must not increment the device version"
        )
        _rows, meta = validate_paginated(api.list_campaign_rollouts(campaign["id"], FIRMWARE_ENGINEER))
        assert meta["total_count"] == 0, "a refused enrolment must not create a rollout"

        # The same consent gate empties the automatic cohort.
        advance = api.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
        validate_error(advance, ApiErrorId.ERR_NO_ELIGIBLE_DEVICES.value)


class TestExistenceAndUniquenessErrors:
    """Rules 10 and 17: path-segment existence and natural-key uniqueness."""

    def test_second_device_with_same_serial_number_is_rejected(self, api):
        """PRD §2.9 rule 17: "Natural keys are unused — `Patient.email`, `Provider.npi`,
        `Device.serial_number`, `InventoryPool.sku`, `FirmwareCampaign.campaign_code`,
        `StatePolicy.state_code`, and the server-minted `ReturnAuthorization.rma_code` — on
        `POST /patients`, `POST /providers`, `POST /devices`, `POST /inventory-pools`,
        `POST /firmware-campaigns` and `POST /state-policies` — otherwise
        `ERR_DUPLICATE_KEY` (409)."

        Design: Corner/errors/error_duplicate_key_on_device_serial_number
        """
        first = validate_success(
            api.create_device({"serial_number": "SN-X004", "model": "NEO"}, ADMIN), 201
        )
        assert first["serial_number"] == "SN-X004", "the first mint must keep the serial"

        resp = api.create_device({"serial_number": "SN-X004", "model": "NEO"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)

        _rows, meta = validate_paginated(api.list_devices(CARE_OPS))
        assert meta["total_count"] == 1, "the duplicate serial must not mint a second device"

    def test_nested_path_segments_resolve_left_to_right(self, api):
        """PRD §2.5: "For `POST /patients/{patient_id}/compliance-overrides/{override_id}/approve`,
        the `patient_id` segment is resolved first and the `override_id` segment second; the
        first segment that names no existing row produces `ERR_RESOURCE_NOT_FOUND` (HTTP 404)
        without the later segments being consulted."

        PRD §2.9 rule 10: "Every path-segment resource exists, validated left to right, on
        every endpoint with path parameters — otherwise `ERR_RESOURCE_NOT_FOUND` (404)."

        Design: Corner/errors/error_resource_not_found_resolves_path_segments_left_to_right
        """
        policy = create_state_policy()
        patient = register_patient(policy["id"])

        # Unknown first segment: the override id is never consulted.
        first_missing = api.approve_compliance_override(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, COMPLIANCE_2
        )
        validate_error(first_missing, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

        # Known first segment, unknown second segment: still a 404 on the path.
        second_missing = api.approve_compliance_override(
            patient["id"], NON_EXISTENT_UUID, COMPLIANCE_2
        )
        validate_error(second_missing, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

        _rows, meta = validate_paginated(api.list_compliance_overrides(patient["id"], COMPLIANCE))
        assert meta["total_count"] == 0, "no override may be created by a failed approval"


class TestTemporalWindowErrors:
    """Rules 35 and 36: return deadlines and session windows."""

    def test_depot_receipt_after_return_deadline_is_rejected(self, api):
        """PRD §2.9 rule 35: "The logical clock is at or before the authorization's
        `return_deadline_utc`, on `POST /return-authorizations/{id}/receive` and on
        `POST /_shipments/scan` when `event` is `RETURN_PICKED_UP` — otherwise
        `ERR_RETURN_DEADLINE_PASSED` (409)."

        PRD §3.6: "Warehouse receipt moves it `IN_TRANSIT → RECEIVED` and stamps `received_at`,
        again requiring the clock to be at or before `return_deadline_utc`."

        Design: Corner/errors/error_return_deadline_passed_on_late_depot_receipt
        """
        env = _delivered_env()
        rma = issue_return_authorization(env, at_iso="2026-08-11T00:00:00Z")
        assert rma["return_deadline_utc"].startswith("2026-08-25T00:00:00"), (
            "the deadline must be the issue instant plus 14 days, got "
            f"{rma['return_deadline_utc']}"
        )
        scan_shipment(env["order"]["id"], "RETURN_PICKED_UP")

        set_clock("2026-08-26T00:00:00Z")
        resp = api.receive_return_authorization(rma["id"], CARE_OPS)
        validate_error(resp, ApiErrorId.ERR_RETURN_DEADLINE_PASSED.value)

        after = validate_success(api.get_return_authorization(rma["id"], CARE_OPS))
        assert after["received_at"] is None, "a refused receipt must not stamp received_at"
        assert after["refund_amount_cents"] == 0, "a refused receipt must not compute a refund"
        assert after["restocking_fee_cents"] == 0, "a refused receipt must not retain restocking"

        order = validate_success(api.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["refunded_cents"] == 0, "no cash may move on a refused receipt"
        assert order["retained_cents"] == 0, "no cash may move on a refused receipt"

    def test_session_cannot_start_or_no_show_before_its_window(self, api):
        """PRD §2.9 rule 36: "Session windows: starting requires the clock to be at or after
        `scheduled_start_utc` and strictly before `scheduled_end_utc`; a patient cancel requires
        the clock to be strictly before `scheduled_start_utc`; a no-show requires the clock to be
        at or after `scheduled_end_utc`. This applies to
        `POST /remote-fitting-sessions/{id}/start`, `POST /remote-fitting-sessions/{id}/cancel`
        and `POST /remote-fitting-sessions/{id}/no-show` — otherwise
        `ERR_SESSION_WINDOW_NOT_OPEN` (409)."

        Design: Corner/errors/error_session_window_not_open_before_start_instant
        """
        policy = create_state_policy()
        patient = register_patient(policy["id"])
        provider = create_provider(daily_capacity_minutes=480, buffer_minutes=0)
        provider_headers = make_licensed_audiologist_headers(provider["id"])

        session = validate_success(
            api.create_remote_fitting_session(
                {
                    "patient_id": patient["id"],
                    "session_type": "FOLLOW_UP",
                    "scheduled_start_utc": "2026-08-05T10:00:00Z",
                    "scheduled_end_utc": "2026-08-05T10:30:00Z",
                    "provider_id": provider["id"],
                    "programming_profile": "MILD_SLOPING_V3",
                },
                make_patient_headers(patient["id"]),
            ),
            201,
        )
        assert session["status"] == "SCHEDULED", "creation confirms the slot in the same request"

        set_clock("2026-08-05T09:59:00Z")
        early_start = api.start_fitting_session(session["id"], provider_headers)
        validate_error(early_start, ApiErrorId.ERR_SESSION_WINDOW_NOT_OPEN.value)

        early_no_show = api.no_show_fitting_session(session["id"], provider_headers)
        validate_error(early_no_show, ApiErrorId.ERR_SESSION_WINDOW_NOT_OPEN.value)

        unchanged = validate_success(api.get_remote_fitting_session(session["id"], CARE_OPS))
        assert unchanged["status"] == "SCHEDULED", (
            "refused window transitions must leave the session SCHEDULED"
        )

        # The boundary instant itself opens the window.
        set_clock("2026-08-05T10:00:00Z")
        started = validate_success(api.start_fitting_session(session["id"], provider_headers))
        assert started["status"] == "IN_PROGRESS", "the start instant is inclusive"


class TestReturnBlockingErrors:
    """Rules 40 and 41: an in-flight repair or exchange blocks a trial return."""

    def test_return_blocked_while_a_repair_is_in_flight(self, api):
        """PRD §2.9 rule 40: "No `RepairOrder` on the order's device is in `KIT_SENT`,
        `RECEIVED` or `IN_REPAIR`, on
        `POST /trial-periods/{trial_period_id}/return-authorizations` — otherwise
        `ERR_REPAIR_IN_PROGRESS_BLOCKS_RETURN` (409)."

        PRD §3.6: "It requires the clock to be at or before `effective_end_utc`, no repair on
        the order's device to be in `KIT_SENT`, `RECEIVED` or `IN_REPAIR`, and no exchange on
        the order to be in `RESERVED` or `SHIPPED`."

        Design: Corner/errors/error_repair_in_progress_blocks_return_inside_live_trial
        """
        env = _delivered_env()
        patient_headers = make_patient_headers(env["patient"]["id"])
        repair = open_repair_order(env, fault_code="NO_SOUND")
        dispatched = validate_success(api.send_repair_kit(repair["id"], CARE_OPS))
        assert dispatched["status"] == "KIT_SENT", "the mail-in kit must be in flight"

        trial = validate_success(api.get_trial_period(env["trial"]["id"], CARE_OPS))
        assert trial["status"] == "ACTIVE", "a dispatched kit does not yet pause the trial"

        resp = api.create_return_authorization(
            trial["id"], {"expected_trial_period_version": trial["version"]}, patient_headers
        )
        validate_error(resp, ApiErrorId.ERR_REPAIR_IN_PROGRESS_BLOCKS_RETURN.value)

        after = validate_success(api.get_trial_period(trial["id"], CARE_OPS))
        assert after["status"] == "ACTIVE", "a refused return must leave the trial ACTIVE"
        _rows, meta = validate_paginated(api.list_trial_return_authorizations(trial["id"], CARE_OPS))
        assert meta["total_count"] == 0, "a refused return must not issue an authorization"

        # Cancelling the repair clears the block, and the identical return is accepted.
        cancelled = validate_success(
            api.cancel_repair_order(repair["id"], {"reason_note": "patient changed mind"}, CARE_OPS)
        )
        assert cancelled["status"] == "CANCELLED", "the care operator may cancel a dispatched kit"
        reread = validate_success(api.get_trial_period(trial["id"], CARE_OPS))
        issued = validate_success(
            api.create_return_authorization(
                reread["id"], {"expected_trial_period_version": reread["version"]}, patient_headers
            ),
            201,
        )
        assert issued["status"] == "ISSUED", "the unblocked return must be issued"

    def test_return_blocked_while_a_fit_exchange_is_reserved(self, api):
        """PRD §2.9 rule 41: "No `FitExchange` on the order is in `RESERVED` or `SHIPPED`, on
        `POST /trial-periods/{trial_period_id}/return-authorizations` — otherwise
        `ERR_EXCHANGE_IN_PROGRESS_BLOCKS_RETURN` (409)."

        PRD §3.6: "Reservation happens in the same request, so an accepted request lands in
        `RESERVED`".

        Design: Corner/errors/error_exchange_in_progress_blocks_return
        """
        env = _delivered_env()
        patient_headers = make_patient_headers(env["patient"]["id"])
        # The exchange target triple needs its own stocked pool row.
        get_success_data(
            api.create_inventory_pool(
                {"sku": "NEO-S-OPEN", "model": "NEO", "dome_size": "S", "tip_type": "OPEN"}, ADMIN
            )
        )
        target_pool = [p for p in validate_paginated(api.list_inventory_pools(CARE_OPS))[0]
                       if p["sku"] == "NEO-S-OPEN"][0]
        get_success_data(api.restock_inventory_pool(target_pool["id"], {"units": 5}, ADMIN))

        order = validate_success(api.get_device_order(env["order"]["id"], CARE_OPS))
        exchange = validate_success(
            api.create_fit_exchange(
                order["id"],
                {
                    "to_dome_size": "S",
                    "to_tip_type": "OPEN",
                    "expected_device_order_version": order["version"],
                },
                patient_headers,
            ),
            201,
        )
        assert exchange["status"] == "RESERVED", "an accepted exchange reserves in the same request"

        trial = validate_success(api.get_trial_period(env["trial"]["id"], CARE_OPS))
        resp = api.create_return_authorization(
            trial["id"], {"expected_trial_period_version": trial["version"]}, patient_headers
        )
        validate_error(resp, ApiErrorId.ERR_EXCHANGE_IN_PROGRESS_BLOCKS_RETURN.value)

        after = validate_success(api.get_trial_period(trial["id"], CARE_OPS))
        assert after["status"] == "ACTIVE", "a refused return must leave the trial ACTIVE"
        _rows, meta = validate_paginated(api.list_trial_return_authorizations(trial["id"], CARE_OPS))
        assert meta["total_count"] == 0, "a refused return must not issue an authorization"

        # Cancelling the exchange clears the block.
        cancelled = validate_success(
            api.cancel_fit_exchange(exchange["id"], {"reason_note": "keeping current domes"},
                                    patient_headers)
        )
        assert cancelled["status"] == "CANCELLED", "the patient may cancel a reserved exchange"
        reread = validate_success(api.get_trial_period(trial["id"], CARE_OPS))
        issued = validate_success(
            api.create_return_authorization(
                reread["id"], {"expected_trial_period_version": reread["version"]}, patient_headers
            ),
            201,
        )
        assert issued["status"] == "ISSUED", "the unblocked return must be issued"


class TestReimbursementPaperworkErrors:
    """Rules 43 through 46: the polymorphic claim's own validation band."""

    def test_claim_with_two_subject_foreign_keys_is_rejected(self, api):
        """PRD §2.9 rule 43: "Exactly the subject foreign key matching `subject_kind` is
        supplied and the other two are null, on `POST /reimbursement-claims` — otherwise
        `ERR_SUBJECT_KIND_MISMATCH` (422)."

        PRD §3.8: "exactly the one subject reference that matches — `device_order_id`,
        `repair_order_id` or `care_plan_subscription_id` — with the other two left null;
        supplying the wrong combination is `ERR_SUBJECT_KIND_MISMATCH`."

        Design: Corner/errors/error_subject_kind_mismatch_when_two_subject_fks_supplied
        """
        env = _delivered_env()
        repair = open_repair_order(env, fault_code="NO_SOUND")

        resp = api.create_reimbursement_claim(
            {
                "patient_id": env["patient"]["id"],
                "subject_kind": "DEVICE_ORDER",
                "claimed_amount_cents": 100000,
                "device_order_id": env["order"]["id"],
                "repair_order_id": repair["id"],
                "document_codes": list(_DEVICE_ORDER_DOCS),
            },
            REIMBURSEMENT,
        )
        validate_error(resp, ApiErrorId.ERR_SUBJECT_KIND_MISMATCH.value)

        _rows, meta = validate_paginated(api.list_reimbursement_claims(REIMBURSEMENT))
        assert meta["total_count"] == 0, "a mismatched claim must not be drafted"

    def test_second_live_claim_on_the_same_subject_is_rejected(self, api):
        """PRD §2.9 rule 44: "No other `ReimbursementClaim` in `SUBMITTED`, `UNDER_REVIEW`,
        `INFO_REQUESTED`, `APPROVED` or `PAID` references the same subject foreign key, on
        `POST /reimbursement-claims` and `POST /reimbursement-claims/{id}/submit` — otherwise
        `ERR_DUPLICATE_REIMBURSEMENT_SUBJECT` (409)."

        Design: Corner/errors/error_duplicate_reimbursement_subject_on_second_live_claim
        """
        env = _delivered_env()
        draft = {
            "patient_id": env["patient"]["id"],
            "subject_kind": "DEVICE_ORDER",
            "claimed_amount_cents": 100000,
            "device_order_id": env["order"]["id"],
            "document_codes": list(_DEVICE_ORDER_DOCS),
        }
        first = validate_success(api.create_reimbursement_claim(dict(draft), REIMBURSEMENT), 201)
        submitted = validate_success(api.submit_reimbursement_claim(first["id"], REIMBURSEMENT))
        assert submitted["status"] == "SUBMITTED", "the first claim must be live"
        assert submitted["eligible_amount_cents"] == 100000, (
            "eligibility is the lesser of the claimed amount and the order's net capture"
        )

        resp = api.create_reimbursement_claim(dict(draft), REIMBURSEMENT)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REIMBURSEMENT_SUBJECT.value)

        _rows, meta = validate_paginated(
            api.list_reimbursement_claims(REIMBURSEMENT, params={"device_order_id": env["order"]["id"]})
        )
        assert meta["total_count"] == 1, "the duplicate must not be persisted"

    def test_submit_rejected_when_a_required_document_is_missing(self, api):
        """PRD §2.9 rule 45: "`document_codes` is a superset of the required set for the claim's
        `subject_kind`, on `POST /reimbursement-claims/{id}/submit` and
        `POST /reimbursement-claims/{id}/supply-info` — otherwise
        `ERR_DOCUMENTATION_INCOMPLETE` (422)."

        PRD §3.8: "Creation computes `documentation_complete`, which is true exactly when
        `document_codes` is a superset of the required set for the claim's `subject_kind` —
        `INVOICE`, `AUDIOGRAM_OR_WAIVER`, `PROOF_OF_PAYMENT` and `LMN` for a `DEVICE_ORDER`".

        Design: Corner/errors/error_documentation_incomplete_on_submit_without_lmn
        """
        env = _delivered_env()
        claim = validate_success(
            api.create_reimbursement_claim(
                {
                    "patient_id": env["patient"]["id"],
                    "subject_kind": "DEVICE_ORDER",
                    "claimed_amount_cents": 100000,
                    "device_order_id": env["order"]["id"],
                    "document_codes": ["INVOICE", "AUDIOGRAM_OR_WAIVER", "PROOF_OF_PAYMENT"],
                },
                REIMBURSEMENT,
            ),
            201,
        )
        assert claim["documentation_complete"] is False, (
            "a DEVICE_ORDER claim without LMN is not documentation-complete"
        )

        resp = api.submit_reimbursement_claim(claim["id"], REIMBURSEMENT)
        validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE.value)

        after = validate_success(api.get_reimbursement_claim(claim["id"], REIMBURSEMENT))
        assert after["status"] == "DRAFT", "a refused submission must leave the claim in DRAFT"
        assert after["submitted_by_user_id"] is None, (
            "a refused submission must not record a submitter"
        )

    def test_second_appeal_of_the_same_denied_claim_is_rejected(self, api):
        """PRD §2.9 rule 46: "No prior appeal exists for the claim named by
        `appeal_of_claim_id` and that claim's `denial_reason` is not `DUPLICATE_SUBJECT`, on
        `POST /reimbursement-claims` — otherwise `ERR_APPEAL_ALREADY_EXISTS` (409)."

        PRD §3.8: "the appeal is refused when the appealed claim's `denial_reason` is
        `DUPLICATE_SUBJECT` or when an appeal already exists."

        Design: Corner/errors/error_appeal_already_exists_on_second_appeal
        """
        env = _delivered_env()
        draft = {
            "patient_id": env["patient"]["id"],
            "subject_kind": "DEVICE_ORDER",
            "claimed_amount_cents": 100000,
            "device_order_id": env["order"]["id"],
            "document_codes": list(_DEVICE_ORDER_DOCS),
        }
        original = validate_success(api.create_reimbursement_claim(dict(draft), REIMBURSEMENT), 201)
        get_success_data(api.submit_reimbursement_claim(original["id"], REIMBURSEMENT))
        get_success_data(api.start_reimbursement_review(original["id"], REIMBURSEMENT))
        denied = validate_success(
            api.decide_reimbursement_claim(
                original["id"], {"decision": "DENY", "denial_reason": "NOT_COVERED"}, REIMBURSEMENT_2
            )
        )
        assert denied["status"] == "DENIED", "the original claim must be denied before an appeal"

        appeal = validate_success(
            api.create_reimbursement_claim(
                dict(draft, appeal_of_claim_id=original["id"]), REIMBURSEMENT
            ),
            201,
        )
        reopened = validate_success(api.get_reimbursement_claim(original["id"], REIMBURSEMENT))
        assert reopened["status"] == "UNDER_REVIEW", "an appeal reopens the denied claim"

        # Deny the reopened original again so no live claim holds the subject.
        redenied = validate_success(
            api.decide_reimbursement_claim(
                original["id"], {"decision": "DENY", "denial_reason": "NOT_COVERED"}, REIMBURSEMENT_2
            )
        )
        assert redenied["status"] == "DENIED", "the second review must be able to deny again"

        resp = api.create_reimbursement_claim(
            dict(draft, appeal_of_claim_id=original["id"]), REIMBURSEMENT
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_EXISTS.value)

        _rows, meta = validate_paginated(
            api.list_reimbursement_claims(REIMBURSEMENT, params={"appeal_of_claim_id": original["id"]})
        )
        assert meta["total_count"] == 1, "only the first appeal may exist"
        assert _rows[0]["id"] == appeal["id"], "the surviving appeal is the first one"


def _delivered_order_with_plan(api, policy_id, base_fee_cents=9900):
    """Screen, order, enrol a consenting plan, then deliver so the plan activates."""
    patient = register_patient(policy_id)
    screen_patient(patient["id"], **_CLEAN_SCREEN)
    env = {"patient": patient, "order": place_order(patient["id"], **_ORDER)}
    simulate_payment(env["order"]["id"])
    confirm_and_ship(env["order"]["id"])
    enroll_care_plan(env, base_fee_cents=base_fee_cents, firmware_auto_update_enabled=True)
    env["order"] = scan_shipment(env["order"]["id"], "DELIVERED")
    env["device"] = _device_for_order(api, env["order"]["id"])
    return env


def _rollouts_of(api, campaign_id):
    rows, _meta = validate_paginated(api.list_campaign_rollouts(campaign_id, FIRMWARE_ENGINEER))
    return rows


def _rollout_state(api, campaign_id, rollout_id):
    for row in _rollouts_of(api, campaign_id):
        if row["id"] == rollout_id:
            return row
    raise AssertionError(f"rollout {rollout_id} is no longer listed under campaign {campaign_id}")


class TestQuotaAndCapacityErrors:
    """Rules 48, 52 and 54: reschedule, inventory and concurrency ceilings."""

    def test_third_referral_evaluation_booking_is_rejected(self, api):
        """PRD §2.9 rule 48: "`ProviderReferral.reschedule_count` is below 2, so that a third
        reschedule cycle is refused, on `POST /remote-fitting-sessions` with `session_type`
        `REFERRAL_EVALUATION` — otherwise `ERR_MAX_RESCHEDULES_EXCEEDED` (409)."

        PRD §3.4: "The provider's `booked_minutes_on_focus_date` is recomputed, and for a
        `REFERRAL_EVALUATION` the referral is driven `SCHEDULED → OPEN`."

        Design: Corner/errors/error_max_reschedules_exceeded_on_third_referral_booking
        """
        env = setup_red_flagged_patient(
            symptom_codes=("VERTIGO",), measurements=dict(_CLEAN_SCREEN)
        )
        provider = create_provider(daily_capacity_minutes=480, buffer_minutes=0)
        provider_headers = make_licensed_audiologist_headers(provider["id"])
        patient_headers = make_patient_headers(env["patient"]["id"])
        referral_id = env["referral"]["id"]

        def book(start_utc, end_utc):
            return api.create_remote_fitting_session(
                {
                    "patient_id": env["patient"]["id"],
                    "session_type": "REFERRAL_EVALUATION",
                    "scheduled_start_utc": start_utc,
                    "scheduled_end_utc": end_utc,
                    "provider_id": provider["id"],
                    "provider_referral_id": referral_id,
                },
                patient_headers,
            )

        first = validate_success(book("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"), 201)
        set_clock("2026-08-05T11:00:00Z")
        validate_success(api.no_show_fitting_session(first["id"], provider_headers))

        second = validate_success(book("2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z"), 201)
        set_clock("2026-08-06T11:00:00Z")
        validate_success(api.no_show_fitting_session(second["id"], provider_headers))

        referral = validate_success(api.get_provider_referral(referral_id, CARE_OPS))
        assert referral["reschedule_count"] == 2, (
            "two no-shows must have driven the referral back to OPEN twice, got "
            f"reschedule_count {referral['reschedule_count']}"
        )

        third = book("2026-08-07T10:00:00Z", "2026-08-07T11:00:00Z")
        validate_error(third, ApiErrorId.ERR_MAX_RESCHEDULES_EXCEEDED.value)

        after = validate_success(api.get_provider_referral(referral_id, CARE_OPS))
        assert after["status"] == "OPEN", "the refused booking must leave the referral OPEN"
        assert after["reschedule_count"] == 2, "the refused booking must not count as a reschedule"

        rows, meta = validate_paginated(
            api.list_remote_fitting_sessions(CARE_OPS, params={"provider_referral_id": referral_id})
        )
        assert meta["total_count"] == 2, "only the two no-showed sessions may exist"
        assert [row["status"] for row in rows] == ["NO_SHOW", "NO_SHOW"], (
            f"both evaluation sessions must be NO_SHOW, got {[row['status'] for row in rows]}"
        )

    def test_second_confirm_fit_is_rejected_when_the_pool_is_empty(self, api):
        """PRD §2.9 rule 52: "The target pool's `on_hand_units` is at least 1, on
        `POST /device-orders/{id}/confirm-fit` and on
        `POST /device-orders/{device_order_id}/fit-exchanges` when `allow_backorder` is false —
        otherwise `ERR_INVENTORY_POOL_DEPLETED` (409)."

        PRD §3.5: "Confirmation moves the fulfillment dimension `PENDING_FIT_CONFIRM →
        READY_TO_SHIP`, reserves a unit by decrementing that pool's `on_hand_units` by one and
        incrementing its `reserved_units` by one".

        Design: Corner/errors/error_inventory_pool_depleted_on_second_confirm_fit
        """
        env = bootstrap_environment(restock_units=1, device_count=2)
        orders = []
        for _ in range(2):
            patient = register_patient(env["policy"]["id"])
            screen_patient(patient["id"], **_CLEAN_SCREEN)
            order = place_order(patient["id"], **_ORDER)
            orders.append(simulate_payment(order["id"]))

        first = validate_success(api.confirm_fit(orders[0]["id"], CARE_OPS))
        assert first["fulfillment_status"] == "READY_TO_SHIP", "the only unit serves order one"

        resp = api.confirm_fit(orders[1]["id"], CARE_OPS)
        validate_error(resp, ApiErrorId.ERR_INVENTORY_POOL_DEPLETED.value)

        pool = get_pool(env["pool"]["id"])
        assert pool["on_hand_units"] == 0, "the depleted pool must still read 0 on hand"
        assert pool["reserved_units"] == 1, "only the first order may hold a reservation"

        blocked = validate_success(api.get_device_order(orders[1]["id"], CARE_OPS))
        assert blocked["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
            "the refused confirmation must leave the second order awaiting fit confirmation"
        )

        # Restocking one unit unblocks the identical confirmation.
        validate_success(api.restock_inventory_pool(env["pool"]["id"], {"units": 1}, ADMIN))
        retried = validate_success(api.confirm_fit(orders[1]["id"], CARE_OPS))
        assert retried["fulfillment_status"] == "READY_TO_SHIP", (
            "the second order must confirm once stock exists"
        )

    def test_second_install_is_rejected_while_one_install_is_in_flight(self, api):
        """PRD §2.9 rule 54: "The count of the campaign's rollouts in `INSTALLING` is below
        `max_concurrent_installs`, on `POST /firmware-rollouts/{id}/install` and
        `POST /firmware-campaigns/{id}/advance` — otherwise
        `ERR_MAX_CONCURRENT_INSTALLS_REACHED` (409)."

        PRD §3.9: "The patient starts the install, moving `OFFERED → INSTALLING` and incrementing
        `attempt_count`; this requires the count of the campaign's rollouts in `INSTALLING` to be
        strictly below `max_concurrent_installs` and the device to be `WITH_PATIENT`."

        Design: Corner/errors/error_max_concurrent_installs_reached_with_limit_one
        """
        env = bootstrap_environment(device_count=2)
        first = _delivered_order_with_plan(api, env["policy"]["id"])
        second = _delivered_order_with_plan(api, env["policy"]["id"])
        owner_of = {
            first["device"]["id"]: first["patient"]["id"],
            second["device"]["id"]: second["patient"]["id"],
        }

        campaign = validate_success(
            api.create_firmware_campaign(
                _campaign_payload(
                    code_suffix="C22",
                    batch_size=2,
                    max_concurrent_installs=1,
                    window_start_utc="2026-08-05T00:00:00Z",
                    window_end_utc="2026-08-30T00:00:00Z",
                ),
                FIRMWARE_ENGINEER,
            ),
            201,
        )
        validate_success(api.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
        set_clock("2026-08-05T00:00:00Z")
        validate_success(api.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))

        rollouts = _rollouts_of(api, campaign["id"])
        assert len(rollouts) == 2, f"a batch of two must enrol both devices, got {len(rollouts)}"
        for rollout in rollouts:
            validate_success(api.offer_firmware_rollout(rollout["id"], FIRMWARE_ENGINEER))

        lead, trailing = rollouts[0], rollouts[1]
        installing = validate_success(
            api.install_firmware_rollout(lead["id"], make_patient_headers(owner_of[lead["device_id"]]))
        )
        assert installing["status"] == "INSTALLING", "the first patient's install must start"

        resp = api.install_firmware_rollout(
            trailing["id"], make_patient_headers(owner_of[trailing["device_id"]])
        )
        validate_error(resp, ApiErrorId.ERR_MAX_CONCURRENT_INSTALLS_REACHED.value)

        blocked = _rollout_state(api, campaign["id"], trailing["id"])
        assert blocked["status"] == "OFFERED", "the refused install must leave the rollout OFFERED"
        assert blocked["attempt_count"] == 0, "a refused install must not count as an attempt"
        held = _rollout_state(api, campaign["id"], lead["id"])
        assert held["status"] == "INSTALLING", "the in-flight install must be untouched"
        assert held["attempt_count"] == 1, "the in-flight install counts exactly one attempt"

        # Draining the single concurrency slot unblocks the identical install.
        validate_success(
            api.report_firmware_install(
                {"firmware_rollout_id": lead["id"], "outcome": "SUCCESS"}, ADMIN
            )
        )
        retried = validate_success(
            api.install_firmware_rollout(
                trailing["id"], make_patient_headers(owner_of[trailing["device_id"]])
            )
        )
        assert retried["status"] == "INSTALLING", "the freed slot must admit the second install"


class TestFirmwareTelemetryErrors:
    """Rule 49: an install report must still match the version it was pinned against."""

    def test_success_report_is_rejected_after_another_campaign_moved_the_device(self, api):
        """PRD §2.9 rule 49: "The device's `firmware_version` equals the rollout's
        `from_version_observed` at install-report time, on `POST /_firmware/report` when `outcome`
        is `SUCCESS` — otherwise `ERR_FIRMWARE_VERSION_DRIFT` (409)."

        PRD §3.9: "A success moves the rollout `INSTALLING → INSTALLED`, and requires the device's
        current `firmware_version` still to equal `from_version_observed` — any drift is refused
        with `ERR_FIRMWARE_VERSION_DRIFT`."

        Design: Corner/errors/error_firmware_version_drift_when_another_campaign_lands_first
        """
        env = bootstrap_environment(device_count=1)
        subject = _delivered_order_with_plan(api, env["policy"]["id"])
        patient_headers = make_patient_headers(subject["patient"]["id"])

        def scheduled_campaign(**overrides):
            campaign = validate_success(
                api.create_firmware_campaign(_campaign_payload(**overrides), FIRMWARE_ENGINEER), 201
            )
            validate_success(api.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
            return campaign

        # Disjoint closed windows, so the two same-model campaigns do not collide.
        early = scheduled_campaign(
            code_suffix="A21", to_version="4.1.0", batch_size=1,
            window_start_utc="2026-08-05T00:00:00Z", window_end_utc="2026-08-06T00:00:00Z",
        )
        late = scheduled_campaign(
            code_suffix="B21", to_version="4.2.0", batch_size=1,
            window_start_utc="2026-08-07T00:00:00Z", window_end_utc="2026-08-20T00:00:00Z",
        )

        set_clock("2026-08-05T00:00:00Z")
        validate_success(api.advance_firmware_campaign(early["id"], FIRMWARE_ENGINEER))
        early_rollout = _rollouts_of(api, early["id"])[0]
        assert early_rollout["from_version_observed"] == "4.0.0", (
            "the rollout pins the version the device ran when it was selected"
        )
        validate_success(api.offer_firmware_rollout(early_rollout["id"], FIRMWARE_ENGINEER))
        validate_success(api.install_firmware_rollout(early_rollout["id"], patient_headers))

        set_clock("2026-08-07T00:00:00Z")
        validate_success(api.advance_firmware_campaign(late["id"], FIRMWARE_ENGINEER))
        late_rollout = _rollouts_of(api, late["id"])[0]
        validate_success(api.offer_firmware_rollout(late_rollout["id"], FIRMWARE_ENGINEER))
        validate_success(api.install_firmware_rollout(late_rollout["id"], patient_headers))
        validate_success(
            api.report_firmware_install(
                {"firmware_rollout_id": late_rollout["id"], "outcome": "SUCCESS"}, ADMIN
            )
        )

        device = validate_success(api.get_device(subject["device"]["id"], FIRMWARE_ENGINEER))
        assert device["firmware_version"] == "4.2.0", (
            "the second campaign's success must have moved the device to its to_version"
        )

        resp = api.report_firmware_install(
            {"firmware_rollout_id": early_rollout["id"], "outcome": "SUCCESS"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_FIRMWARE_VERSION_DRIFT.value)

        stranded = _rollout_state(api, early["id"], early_rollout["id"])
        assert stranded["status"] == "INSTALLING", (
            "a drifted success report must leave the rollout INSTALLING"
        )
        assert stranded["attempt_count"] == 1, "the refused report must not add an attempt"
        assert stranded["from_version_observed"] == "4.0.0", (
            "the pinned observation must never be rewritten"
        )
        campaign_after = validate_success(api.get_firmware_campaign(early["id"], FIRMWARE_ENGINEER))
        assert campaign_after["installed_count"] == 0, (
            "a refused success report must not count as an install"
        )


class TestWarrantyErrors:
    """Rules 58, 59 and 61: the warranty band's quota, term and money gates."""

    def test_second_damage_decision_is_rejected_once_the_cap_is_reached(self, api):
        """PRD §2.9 rule 58: "`Device.loss_damage_claims_approved` is below the policy's
        `max_loss_damage_claims` for a `LOSS` or `DAMAGE` claim decision, on
        `POST /warranty-claims/{id}/decide` — otherwise `ERR_CLAIM_CAP_REACHED` (409)."

        PRD §3.7: "A `REPLACE` decision moves the claim `TRIAGED → APPROVED_REPLACEMENT`; it
        requires, for a `LOSS` or `DAMAGE` claim, that the device's `loss_damage_claims_approved`
        is strictly below the policy's `max_loss_damage_claims`, and requires either that
        `warranty_expires_at` is strictly after the clock or that `claim_kind` is `LOSS`."

        PRD §3.7: "The ordinal surcharge is 0 when `claim_ordinal` is 1 and 5,000 cents ($50.00)
        otherwise."

        Design: Corner/errors/error_claim_cap_reached_on_second_damage_decision
        """
        env = setup_triaged_warranty_claim(
            claim_kind="DAMAGE",
            policy_overrides={"max_loss_damage_claims": 1},
            order_overrides=dict(_ORDER),
            measurements=dict(_CLEAN_SCREEN),
        )
        device_id = env["assigned_device"]["id"]
        patient_headers = make_patient_headers(env["patient"]["id"])
        first = env["warranty_claim"]
        assert first["deductible_cents"] == 3713, (
            f"a first DAMAGE claim on a new device owes 3713, got {first['deductible_cents']}"
        )

        validate_success(api.decide_warranty_claim(first["id"], {"decision": "REPLACE"}, COMPLIANCE))
        validate_success(
            api.pay_warranty_deductible(first["id"], {"amount_cents": 3713}, patient_headers)
        )
        fulfilled = validate_success(api.fulfill_warranty_claim(first["id"], CARE_OPS))
        assert fulfilled["status"] == "FULFILLED", "the first claim must complete"

        second = validate_success(
            api.create_warranty_claim({"device_id": device_id, "claim_kind": "DAMAGE"}, patient_headers),
            201,
        )
        second = validate_success(api.triage_warranty_claim(second["id"], REPAIR_TECH))
        assert second["deductible_cents"] == 8713, (
            f"a second DAMAGE claim owes 3713 plus the 5000 surcharge, got {second['deductible_cents']}"
        )

        resp = api.decide_warranty_claim(second["id"], {"decision": "REPLACE"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_CLAIM_CAP_REACHED.value)

        blocked = validate_success(api.get_warranty_claim(second["id"], CARE_OPS))
        assert blocked["status"] == "TRIAGED", "a capped decision must leave the claim TRIAGED"
        assert blocked["deductible_cents"] == 8713, "the refused decision must not rewrite the money"
        assert blocked["replacement_device_id"] is None, (
            "a capped decision must not mint a replacement unit"
        )

        device = validate_success(api.get_device(device_id, CARE_OPS))
        assert device["loss_damage_claims_approved"] == 1, (
            "only the fulfilled claim may count against the lifetime cap"
        )
        closed = validate_success(api.get_warranty_claim(first["id"], CARE_OPS))
        assert closed["status"] == "FULFILLED", "the first claim stays fulfilled"
        assert closed["deductible_paid_cents"] == 3713, "the first deductible stays fully paid"

    def test_repair_decision_is_rejected_after_the_warranty_term_ends(self, api):
        """PRD §2.9 rule 59: "`Device.warranty_expires_at` is strictly after the logical clock,
        except when `claim_kind` is `LOSS`, on `POST /warranty-claims/{id}/decide` with `decision`
        `REPLACE` or `REPAIR` — otherwise `ERR_WARRANTY_EXPIRED` (409)."

        PRD §3.5: "stamps the device's `shipped_at` from the logical clock and sets its
        `warranty_expires_at` to `shipped_at` plus 730 days (two years)"

        PRD §3.7: "`device_age_months` is the whole number of months between the device's
        `shipped_at` and the logical clock, floored."

        Design: Corner/errors/error_warranty_expired_blocks_repair_decision_but_not_loss
        """
        env = _delivered_env()
        device_id = env["assigned_device"]["id"]
        patient_headers = make_patient_headers(env["patient"]["id"])

        device = validate_success(api.get_device(device_id, CARE_OPS))
        assert_same_instant(
            device["warranty_expires_at"], "2028-07-31T00:00:00Z",
            "the two-year term must run from the 2026-08-01 shipment, got "
            f"{device['warranty_expires_at']}",
        )

        set_clock("2028-09-01T00:00:00Z")
        defect = validate_success(
            api.create_warranty_claim({"device_id": device_id, "claim_kind": "DEFECT"}, patient_headers),
            201,
        )
        defect = validate_success(api.triage_warranty_claim(defect["id"], REPAIR_TECH))
        assert defect["device_age_months"] == 25, (
            f"the device is 25 whole months old at 2028-09-01, got {defect['device_age_months']}"
        )
        assert defect["deductible_cents"] == 0, "the DEFECT kind factor is 0.0, so nothing is owed"

        resp = api.decide_warranty_claim(defect["id"], {"decision": "REPAIR"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)

        after = validate_success(api.get_warranty_claim(defect["id"], CARE_OPS))
        assert after["status"] == "TRIAGED", "the refused decision must leave the claim TRIAGED"
        assert after["denial_reason"] is None, "a refused decision is not a denial"

        # A LOSS claim on the same expired device is explicitly exempt.
        loss = validate_success(
            api.create_warranty_claim({"device_id": device_id, "claim_kind": "LOSS"}, patient_headers),
            201,
        )
        loss = validate_success(api.triage_warranty_claim(loss["id"], REPAIR_TECH))
        approved = validate_success(
            api.decide_warranty_claim(loss["id"], {"decision": "REPLACE"}, COMPLIANCE)
        )
        assert approved["status"] == "APPROVED_REPLACEMENT", (
            "the LOSS exemption must survive the expired warranty term"
        )

    def test_fulfilment_is_rejected_while_the_deductible_is_part_paid(self, api):
        """PRD §2.9 rule 61: "`deductible_paid_cents` equals `deductible_cents`, on
        `POST /warranty-claims/{id}/fulfill` — otherwise `ERR_DEDUCTIBLE_UNPAID` (402)."

        PRD §3.7: "From `APPROVED_REPLACEMENT`, fulfilment requires only that
        `deductible_paid_cents` equals `deductible_cents`"

        Design: Corner/errors/error_deductible_unpaid_on_partial_payment
        """
        env = setup_triaged_warranty_claim(
            claim_kind="DAMAGE",
            order_overrides=dict(_ORDER),
            measurements=dict(_CLEAN_SCREEN),
        )
        claim = env["warranty_claim"]
        patient_headers = make_patient_headers(env["patient"]["id"])
        assert claim["deductible_cents"] == 3713, (
            f"a DAMAGE claim on a new device owes 3713, got {claim['deductible_cents']}"
        )

        validate_success(api.decide_warranty_claim(claim["id"], {"decision": "REPLACE"}, COMPLIANCE))
        part_paid = validate_success(
            api.pay_warranty_deductible(claim["id"], {"amount_cents": 3000}, patient_headers)
        )
        assert part_paid["deductible_paid_cents"] == 3000, "the partial payment must be recorded"

        resp = api.fulfill_warranty_claim(claim["id"], CARE_OPS)
        validate_error(resp, ApiErrorId.ERR_DEDUCTIBLE_UNPAID.value)

        blocked = validate_success(api.get_warranty_claim(claim["id"], CARE_OPS))
        assert blocked["deductible_cents"] == 3713, "the refusal must not rewrite the deductible"
        assert blocked["deductible_paid_cents"] == 3000, "the refusal must not rewrite the payment"
        assert blocked["status"] != "FULFILLED", (
            f"an unpaid claim must not be fulfilled, got {blocked['status']}"
        )

        # Paying the remaining 713 cents unblocks the identical fulfilment.
        validate_success(
            api.pay_warranty_deductible(claim["id"], {"amount_cents": 713}, patient_headers)
        )
        fulfilled = validate_success(api.fulfill_warranty_claim(claim["id"], CARE_OPS))
        assert fulfilled["status"] == "FULFILLED", "the fully paid claim must fulfil"


class TestCarePlanFiscalErrors:
    """Rules 62, 63 and 64: the billing band, including the state band that shadows it."""

    def test_declined_cycle_charge_reports_the_decline_and_opens_dunning(self, api):
        """PRD §2.9 rule 62: "The simulated charge outcome is a success for the amount due after
        credits, on `POST /care-plan-subscriptions/{id}/run-billing-cycle` and
        `POST /care-plan-subscriptions/{id}/retry-payment` — otherwise `ERR_PAYMENT_DECLINED` (402)."

        PRD §3.8: "On a declined instrument, with `last_charge_cents` exceeding
        `credit_balance_cents`, the plan moves `ACTIVE → PAST_DUE` with `dunning_attempts` set to 1
        and — importantly — `cycle_ordinal` **not** incremented, which is why a past-due episode
        never advances the loyalty tier."

        Design: Corner/errors/error_payment_declined_moves_plan_to_past_due
        """
        env = setup_active_care_plan(
            plan_overrides={"base_fee_cents": 9900, "firmware_auto_update_enabled": True},
            order_overrides=dict(_ORDER),
            measurements=dict(_CLEAN_SCREEN),
        )
        plan = env["plan"]
        assert plan["status"] == "ACTIVE", "delivery must have activated the plan"
        assert plan["cycle_end_utc"].startswith("2026-08-31T00:00:00"), (
            f"the first cycle must close 30 days after delivery, got {plan['cycle_end_utc']}"
        )

        set_clock("2026-08-31T00:00:00Z")
        resp = api.run_billing_cycle(plan["id"], {"charge_outcome": "DECLINED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_DECLINED.value)

        after = validate_success(api.get_care_plan_subscription(plan["id"], CARE_OPS))
        assert after["status"] == "PAST_DUE", (
            f"a declined charge must open a past-due episode, got {after['status']}"
        )
        assert after["dunning_attempts"] == 1, "the first decline is dunning attempt one"
        assert after["cycle_ordinal"] == 0, (
            "a past-due episode must not advance the cycle ordinal"
        )
        assert after["credit_balance_cents"] == 0, "no credit exists to consume"

    def test_paying_from_credit_is_rejected_when_the_balance_is_empty(self, api):
        """PRD §2.9 rule 64: "`credit_balance_cents` is at least the amount being consumed when
        `pay_from_credit` is true, on `POST /care-plan-subscriptions/{id}/run-billing-cycle` —
        otherwise `ERR_CREDIT_BALANCE_INSUFFICIENT` (402)."

        PRD §3.8: "When `pay_from_credit` is true but `credit_balance_cents` is below the computed
        charge, the run is refused with `ERR_CREDIT_BALANCE_INSUFFICIENT`."

        Design: Corner/errors/error_credit_balance_insufficient_when_paying_from_zero_credit
        """
        env = setup_active_care_plan(
            plan_overrides={"base_fee_cents": 9900, "firmware_auto_update_enabled": True},
            order_overrides=dict(_ORDER),
            measurements=dict(_CLEAN_SCREEN),
        )
        plan = env["plan"]
        assert plan["credit_balance_cents"] == 0, "a fresh plan holds no credit"

        set_clock("2026-08-31T00:00:00Z")
        resp = api.run_billing_cycle(
            plan["id"], {"charge_outcome": "SUCCEEDED", "pay_from_credit": True}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_BALANCE_INSUFFICIENT.value)

        after = validate_success(api.get_care_plan_subscription(plan["id"], CARE_OPS))
        assert after["status"] == "ACTIVE", "a refused run must leave the plan ACTIVE"
        assert after["cycle_ordinal"] == 0, "a refused run must not advance the cycle"
        assert after["credit_balance_cents"] == 0, "a refused run must not move credit"

        # The identical run without the credit flag settles normally.
        charged = validate_success(
            api.run_billing_cycle(plan["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN)
        )
        assert charged["cycle_ordinal"] == 1, "the successful run advances the cycle"
        assert charged["last_charge_cents"] == 9900, (
            f"a 9900 STANDARD plan waives the service fee and the loyalty discount, got "
            f"{charged['last_charge_cents']}"
        )

    def test_retry_after_suspension_reports_the_state_band_not_the_dunning_ceiling(self, api):
        """PRD §2.9 rule 22: "The targeted entity's current state is a declared origin state for
        the requested transition, on every action endpoint that drives a state transition —
        otherwise `ERR_INVALID_STATE` (409)."

        PRD §2.9 rule 63: "`CarePlanSubscription.dunning_attempts` is below 3, on
        `POST /care-plan-subscriptions/{id}/retry-payment` — otherwise
        `ERR_DUNNING_LIMIT_REACHED` (409)."

        PRD §2.9: "When a single request violates more than one rule, the rule with the lowest
        priority number below wins and its error is the one returned."

        PRD §2.9: "A billing-cycle run against a cancelled subscription with a declining
        instrument violates both rule 22 and rule 62; rule 22 wins, so the caller sees
        `ERR_INVALID_STATE`."

        PRD §3.8: "A declining retry self-loops `PAST_DUE → PAST_DUE` and increments
        `dunning_attempts`, likewise requiring the counter to be below 3 beforehand. The third
        failure — the increment that brings `dunning_attempts` to 3 — moves the plan
        `PAST_DUE → SUSPENDED`."

        Design: Corner/errors/error_dunning_limit_reached_is_shadowed_by_suspended_state
        """
        env = setup_active_care_plan(
            plan_overrides={"base_fee_cents": 9900, "firmware_auto_update_enabled": True},
            order_overrides=dict(_ORDER),
            measurements=dict(_CLEAN_SCREEN),
        )
        plan_id = env["plan"]["id"]
        patient_headers = make_patient_headers(env["patient"]["id"])

        set_clock("2026-08-31T00:00:00Z")
        validate_error(
            api.run_billing_cycle(plan_id, {"charge_outcome": "DECLINED"}, ADMIN),
            ApiErrorId.ERR_PAYMENT_DECLINED.value,
        )
        for _attempt in range(2):
            validate_error(
                api.retry_care_plan_payment(plan_id, {"charge_outcome": "DECLINED"}, patient_headers),
                ApiErrorId.ERR_PAYMENT_DECLINED.value,
            )

        suspended = validate_success(api.get_care_plan_subscription(plan_id, CARE_OPS))
        assert suspended["status"] == "SUSPENDED", (
            f"the third dunning failure must suspend the plan, got {suspended['status']}"
        )
        assert suspended["dunning_attempts"] == 3, "the counter must have reached three"

        resp = api.retry_care_plan_payment(
            plan_id, {"charge_outcome": "DECLINED"}, patient_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        after = validate_success(api.get_care_plan_subscription(plan_id, CARE_OPS))
        assert after["status"] == "SUSPENDED", "the refused retry must leave the plan SUSPENDED"
        assert after["dunning_attempts"] == 3, "the refused retry must not increment dunning"
        assert after["cycle_ordinal"] == 0, "no dunning episode ever advanced the cycle"


class TestCompensatingWindowErrors:
    """Rule 65: the restocking waiver expires thirty days after settlement."""

    def test_restocking_waiver_is_refused_more_than_thirty_days_after_settlement(self, api):
        """PRD §2.9 rule 65: "The logical clock is at or before the authorization's `settled_at`
        plus 30 days, on `POST /return-authorizations/{id}/waive-restocking` — otherwise
        `ERR_RESTOCKING_WAIVE_WINDOW_CLOSED` (409)."

        PRD §3.6: "A compliance officer may afterwards waive retained restocking, optionally with
        a `reason_note`, provided the settled authorization's `restocking_fee_cents` is above 0
        and the clock is within 30 days of `settled_at`."

        Design: Corner/errors/error_restocking_waive_window_closed_after_thirty_days
        """
        env = setup_return_settled(
            at_iso="2026-08-11T00:00:00Z",
            order_overrides=dict(_ORDER),
            measurements=dict(_CLEAN_SCREEN),
        )
        rma = env["rma"]
        assert rma["settled_at"].startswith("2026-08-11T00:00:00"), (
            f"the settlement instant anchors the waiver window, got {rma['settled_at']}"
        )
        assert rma["restocking_fee_cents"] == 20000, (
            f"a FLAT_PCT return of a 200000 device retains 20000, got {rma['restocking_fee_cents']}"
        )

        set_clock("2026-09-12T00:00:00Z")
        resp = api.waive_restocking(rma["id"], {"reason_note": "goodwill"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_RESTOCKING_WAIVE_WINDOW_CLOSED.value)

        after = validate_success(api.get_return_authorization(rma["id"], CARE_OPS))
        assert after["restocking_fee_cents"] == 20000, "the refused waiver must retain the fee"
        assert after["non_refundable_shipping_cents"] == 1495, (
            "the refused waiver must retain the non-refundable shipping"
        )
        assert after["refund_amount_cents"] == 194500, "the refund must be unchanged"
        assert after["restocking_variant"] == "FLAT_PCT", (
            "the refused waiver must not rewrite the variant to WAIVED"
        )

        order = validate_success(api.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["payment_status"] == "PARTIALLY_REFUNDED", (
            "the order must stay partially refunded"
        )
        assert order["retained_cents"] == 21495, (
            f"20000 restocking plus 1495 shipping stays retained, got {order['retained_cents']}"
        )
