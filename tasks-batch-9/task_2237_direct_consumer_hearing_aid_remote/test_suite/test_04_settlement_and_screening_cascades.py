"""Multi-hop cascade coverage: return settlement and the red-flag medical hold."""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    FIRMWARE_ENGINEER,
    api_client,
    assert_same_instant,
    get_success_data,
    issue_return_authorization,
    make_patient_headers,
    scan_shipment,
    set_clock,
    setup_active_care_plan,
    setup_registered_patient,
    validate_success,
)

# --- Return-settlement cascade -------------------------------------------------
CAMPAIGN_WINDOW_START = "2026-08-02T00:00:00Z"
CAMPAIGN_WINDOW_END = "2026-09-30T00:00:00Z"
ADVANCE_CLOCK = "2026-08-03T00:00:00Z"
RETURN_CLOCK = "2026-08-07T00:00:00Z"

ORDER_TOTAL_CENTS = 210096
RESTOCKING_FEE_CENTS = 19225
NON_REFUNDABLE_SHIPPING_CENTS = 1495
REFUND_AMOUNT_CENTS = 189376
RETAINED_CENTS = 20720

# --- Medical-hold cascade ------------------------------------------------------
FIT_SESSION_START = "2026-08-10T10:00:00Z"
FIT_SESSION_END = "2026-08-10T11:00:00Z"
REFERRAL_ISSUED_AT = "2026-08-01T00:00:00Z"
REFERRAL_EXPIRES_AT = "2027-01-28T00:00:00Z"


def _inspected_return_with_plan_and_rollout() -> dict:
    """Delivered order + PREMIUM plan + PENDING rollout, return inspected but unsettled."""
    env = setup_active_care_plan(
        policy_overrides={"trial_period_days": 30},
        patient_overrides={"age_years": 69},
        plan_overrides={
            "plan_tier": "PREMIUM",
            "base_fee_cents": 9900,
            "firmware_auto_update_enabled": True,
        },
    )

    env["campaign"] = get_success_data(
        api_client.create_firmware_campaign(
            {
                "campaign_code": "FW-NEO-421",
                "model": "NEO",
                "from_version": "4.0.0",
                "to_version": "4.2.1",
                "window_start_utc": CAMPAIGN_WINDOW_START,
                "window_end_utc": CAMPAIGN_WINDOW_END,
                "batch_size": 3,
                "max_concurrent_installs": 2,
                "is_mandatory_safety": False,
            },
            FIRMWARE_ENGINEER,
        )
    )
    set_clock(ADVANCE_CLOCK)
    get_success_data(api_client.schedule_firmware_campaign(env["campaign"]["id"], FIRMWARE_ENGINEER))
    env["campaign"] = get_success_data(
        api_client.advance_firmware_campaign(env["campaign"]["id"], FIRMWARE_ENGINEER)
    )
    rollouts = api_client.list_campaign_rollouts(
        env["campaign"]["id"], FIRMWARE_ENGINEER, params={"status": "PENDING"}
    ).json()["data"]
    assert rollouts, "Setup failed: the campaign advance enrolled no PENDING rollout"
    env["rollout"] = rollouts[0]

    set_clock(RETURN_CLOCK)
    issue_return_authorization(env)
    scan_shipment(env["order"]["id"], "RETURN_PICKED_UP")
    get_success_data(api_client.receive_return_authorization(env["rma"]["id"], CARE_OPS))
    env["rma"] = get_success_data(
        api_client.inspect_return_authorization(
            env["rma"]["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
        )
    )
    return env


def _red_flag_cascade_environment() -> dict:
    """Order placed and an INITIAL_FIT slot booked BEFORE the red-flag screening submit."""
    env = setup_registered_patient(
        policy_overrides={"trial_period_days": 30, "referral_validity_days": 180, "min_age_years": 18},
        patient_overrides={"age_years": 65},
    )
    env["provider"] = get_success_data(
        api_client.create_provider(
            {
                "provider_type": "TELECARE_FITTER",
                "npi": "1548273901",
                "full_name": "Sam Fitter",
                "licensed_state_codes": ["CA"],
                "daily_capacity_minutes": 480,
                "buffer_minutes": 10,
            },
            ADMIN,
        )
    )
    patient_headers = make_patient_headers(env["patient"]["id"])
    env["order"] = get_success_data(
        api_client.create_device_order(
            env["patient"]["id"],
            {
                "model": "NEO",
                "dome_size": "M",
                "tip_type": "OPEN",
                "list_price_cents": 199900,
                "discount_cents": 9900,
                "accessory_subtotal_cents": 4500,
                "shipping_cents": 1495,
            },
            patient_headers,
        )
    )
    env["session"] = get_success_data(
        api_client.create_remote_fitting_session(
            {
                "patient_id": env["patient"]["id"],
                "session_type": "INITIAL_FIT",
                "scheduled_start_utc": FIT_SESSION_START,
                "scheduled_end_utc": FIT_SESSION_END,
                "provider_id": env["provider"]["id"],
                "device_order_id": env["order"]["id"],
            },
            patient_headers,
        )
    )
    env["screening"] = get_success_data(
        api_client.start_screening_session(env["patient"]["id"], {}, patient_headers)
    )
    get_success_data(
        api_client.update_screening_session(
            env["screening"]["id"],
            {
                "pure_tone_avg_db": 45.0,
                "asymmetry_db": 5.0,
                "self_reported_difficulty_score": 20,
                "speech_in_noise_pct": 70.0,
                "symptom_codes": ["VERTIGO"],
            },
            patient_headers,
        )
    )
    return env


class TestReturnSettlementCascade:
    """POST /return-authorizations/{id}/settle fans out across five entities."""

    def test_settlement_moves_trial_to_return_settled_and_counts_the_return(self):
        """"Settling an inspected authorization moves it `INSPECTED → REFUND_SETTLED`, stamps
        `settled_at`, and runs the five-hop return cascade of §2.8." (§3.6)

        "Hop 1 moves the `TrialPeriod` from `RETURN_INITIATED` to `RETURN_SETTLED` and increments
        `Patient.lifetime_return_count`." (§2.8)

        Design: Difficulty/transitive_cascade/cascade_a_return_settlement_five_hop_chain
        """
        env = _inspected_return_with_plan_and_rollout()

        settled = validate_success(api_client.settle_return_authorization(env["rma"]["id"], CARE_OPS))
        assert settled["status"] == "REFUND_SETTLED", (
            f"settle must move the authorization to REFUND_SETTLED, got {settled['status']!r}"
        )
        assert settled["restocking_fee_cents"] == RESTOCKING_FEE_CENTS, (
            "FLAT_PCT settlement must retain 19225 cents (19000 device + 225 accessory), "
            f"got {settled['restocking_fee_cents']}"
        )
        assert settled["non_refundable_shipping_cents"] == NON_REFUNDABLE_SHIPPING_CENTS, (
            "a policy with shipping_refundable false keeps the whole 1495 cents of outbound "
            f"shipping, got {settled['non_refundable_shipping_cents']}"
        )
        assert settled["refund_amount_cents"] == REFUND_AMOUNT_CENTS, (
            f"refund must be 210096 - 19225 - 1495 = 189376, got {settled['refund_amount_cents']}"
        )

        trial = validate_success(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
        assert trial["status"] == "RETURN_SETTLED", (
            f"hop 1 must move the trial to RETURN_SETTLED, got {trial['status']!r}"
        )
        patient = validate_success(api_client.get_patient(env["patient"]["id"], CARE_OPS))
        assert patient["lifetime_return_count"] == 1, (
            f"hop 1 must increment lifetime_return_count to 1, got {patient['lifetime_return_count']}"
        )

    def test_settlement_partially_refunds_the_order_and_conserves_cash(self):
        """"Hop 2 moves the `DeviceOrder`'s `fulfillment_status` to `RETURNED` and its
        `payment_status` to either `PARTIALLY_REFUNDED` or `REFUNDED`, updating `refunded_cents`,
        `retained_cents` and `open_balance_cents`." (§2.8)

        "`open_balance_cents` is defined as `captured_cents` minus `refunded_cents` minus
        `retained_cents`." (§2.6)

        Design: Difficulty/transitive_cascade/cascade_a_return_settlement_five_hop_chain
        """
        env = _inspected_return_with_plan_and_rollout()

        validate_success(api_client.settle_return_authorization(env["rma"]["id"], CARE_OPS))

        order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["fulfillment_status"] == "RETURNED", (
            f"hop 2 must move fulfillment to RETURNED, got {order['fulfillment_status']!r}"
        )
        assert order["payment_status"] == "PARTIALLY_REFUNDED", (
            "a settlement retaining restocking plus non-refundable shipping moves payment to "
            f"PARTIALLY_REFUNDED, got {order['payment_status']!r}"
        )
        assert order["captured_cents"] == ORDER_TOTAL_CENTS, (
            f"captured_cents must stay at the captured total 210096, got {order['captured_cents']}"
        )
        assert order["refunded_cents"] == REFUND_AMOUNT_CENTS, (
            f"refunded_cents must equal the refund 189376, got {order['refunded_cents']}"
        )
        assert order["retained_cents"] == RETAINED_CENTS, (
            "retained_cents must be restocking 19225 plus non-refundable shipping 1495 = 20720, "
            f"got {order['retained_cents']}"
        )
        assert order["open_balance_cents"] == 0, (
            f"a whole-order return must drive open_balance_cents to 0, got {order['open_balance_cents']}"
        )

    def test_settlement_retires_the_device_and_cancels_the_care_plan(self):
        """"Hop 3 sets the `Device.status` to `RETIRED` while retaining its `device_order_id` for
        audit. Hop 4 moves every `CarePlanSubscription` attached to that order to `CANCELLED` and
        forfeits its `credit_balance_cents` by setting it to zero." (§2.8)

        Design: Difficulty/transitive_cascade/cascade_a_return_settlement_five_hop_chain
        """
        env = _inspected_return_with_plan_and_rollout()

        validate_success(api_client.settle_return_authorization(env["rma"]["id"], CARE_OPS))

        device = validate_success(api_client.get_device(env["assigned_device"]["id"], CARE_OPS))
        assert device["status"] == "RETIRED", (
            f"hop 3 must retire the returned device, got {device['status']!r}"
        )

        plan = validate_success(api_client.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
        assert plan["status"] == "CANCELLED", (
            f"hop 4 must cancel the care plan attached to the order, got {plan['status']!r}"
        )
        assert plan["credit_balance_cents"] == 0, (
            f"hop 4 must forfeit the plan credit balance, got {plan['credit_balance_cents']}"
        )

    def test_settlement_cancels_the_pending_firmware_rollout_on_the_returned_device(self):
        """"Hop 5 moves every `FirmwareRollout` on that device whose status is `PENDING` or
        `OFFERED` to `CANCELLED_INELIGIBLE` and recomputes the owning campaign's `rollout_count`,
        `installed_count` and `failure_rate_pct`." (§2.8)

        "`failure_rate_pct` is 100 multiplied by failed rollouts divided by the sum of installed and
        failed rollouts, to one decimal place rounded half up, and reads 0 when that denominator is
        0." (§3.9)

        Design: Difficulty/transitive_cascade/cascade_a_return_settlement_five_hop_chain
        """
        env = _inspected_return_with_plan_and_rollout()
        assert env["rollout"]["status"] == "PENDING", (
            "the rollout must still be PENDING before the settlement, got "
            f"{env['rollout']['status']!r}"
        )

        validate_success(api_client.settle_return_authorization(env["rma"]["id"], CARE_OPS))

        rows = api_client.list_firmware_rollouts(
            FIRMWARE_ENGINEER, params={"device_id": env["assigned_device"]["id"]}
        ).json()["data"]
        assert len(rows) == 1, f"exactly one rollout targets the returned device, got {len(rows)}"
        assert rows[0]["id"] == env["rollout"]["id"], "the listed rollout must be the enrolled one"
        assert rows[0]["status"] == "CANCELLED_INELIGIBLE", (
            f"hop 5 must cancel the PENDING rollout as ineligible, got {rows[0]['status']!r}"
        )
        assert rows[0]["selection_rank"] == 1, (
            f"the single cohort member keeps selection_rank 1, got {rows[0]['selection_rank']}"
        )

        campaign = validate_success(
            api_client.get_firmware_campaign(env["campaign"]["id"], FIRMWARE_ENGINEER)
        )
        assert campaign["status"] == "ROLLING", (
            f"the campaign itself stays ROLLING, got {campaign['status']!r}"
        )
        assert campaign["installed_count"] == 0, (
            f"no install happened, so installed_count stays 0, got {campaign['installed_count']}"
        )
        assert campaign["failure_rate_pct"] == 0.0, (
            "with no installed and no failed rollouts the failure rate reads 0, got "
            f"{campaign['failure_rate_pct']}"
        )


class TestMedicalHoldCascade:
    """POST /screening-sessions/{id}/submit fans out from a mandatory red flag."""

    def test_red_flag_submit_scores_the_session_and_opens_a_referral(self):
        """"A declared vertigo symptom emits `VERTIGO`, mandatory, weight 0.0." (§3.2)

        "If the mandatory count is greater than zero, the outcome is `RED_FLAG`." (§3.2)

        "Hop 1 opens a `ProviderReferral` in `OPEN`." (§2.8)

        "Hop 1 of that cascade opens a `ProviderReferral` in `OPEN`, populating `reason_codes` with
        the `code` values of the triggering findings ordered by their `detected_at` ascending, naming
        the `triggering_screening_session_id`, stamping `issued_at` from the logical clock, and
        computing `expires_at` as `issued_at` plus the patient's policy `referral_validity_days`
        days." (§3.3)

        Design: Difficulty/transitive_cascade/cascade_b_red_flag_screening_four_hop_fanout
        """
        env = _red_flag_cascade_environment()
        patient_headers = make_patient_headers(env["patient"]["id"])

        scored = validate_success(
            api_client.submit_screening_session(env["screening"]["id"], patient_headers)
        )
        assert scored["status"] == "SCORED", (
            f"submit scores the session in the same request, got {scored['status']!r}"
        )
        assert scored["screening_outcome"] == "RED_FLAG", (
            f"one mandatory finding makes the outcome RED_FLAG, got {scored['screening_outcome']!r}"
        )

        findings = api_client.list_screening_red_flag_findings(
            env["screening"]["id"], patient_headers
        ).json()["data"]
        assert len(findings) == 1, f"only the vertigo symptom fires, got {len(findings)} findings"
        assert findings[0]["code"] == "VERTIGO", f"unexpected finding code {findings[0]['code']!r}"
        assert findings[0]["severity"] == "MANDATORY_REFERRAL", (
            f"a vertigo finding is mandatory, got {findings[0]['severity']!r}"
        )
        assert findings[0]["weight"] == 0.0, (
            f"a mandatory vertigo finding carries weight 0.0, got {findings[0]['weight']}"
        )
        assert findings[0]["cleared_by_referral_id"] is None, (
            "a freshly emitted finding is still open, so cleared_by_referral_id must be null"
        )

        referrals = api_client.list_provider_referrals(
            CARE_OPS, params={"patient_id": env["patient"]["id"]}
        ).json()["data"]
        assert len(referrals) == 1, f"hop 1 opens exactly one referral, got {len(referrals)}"
        referral = referrals[0]
        assert referral["status"] == "OPEN", f"hop 1 opens the referral in OPEN, got {referral['status']!r}"
        assert referral["provider_id"] is None, "a fresh referral has provider_id null"
        assert_same_instant(
            referral["issued_at"], REFERRAL_ISSUED_AT,
            f"issued_at is stamped from the logical clock, got {referral['issued_at']!r}",
        )
        assert_same_instant(
            referral["expires_at"], REFERRAL_EXPIRES_AT,
            "expires_at is issued_at plus the policy's 180 referral_validity_days, got "
            f"{referral['expires_at']!r}",
        )
        assert referral["triggering_screening_session_id"] == env["screening"]["id"], (
            "the referral must name the screening that triggered it"
        )
        assert referral["reason_codes"] == ["VERTIGO"], (
            f"reason_codes carries the triggering finding code, got {referral['reason_codes']!r}"
        )

    def test_red_flag_cascade_puts_the_patient_on_referral_required(self):
        """"A `RED_FLAG` outcome drives the patient into `REFERRAL_REQUIRED`" (§3.3)

        "`open_mandatory_flag_count` is the number of findings at severity `MANDATORY_REFERRAL`
        whose `cleared_by_referral_id` is still null, counted across every screening session whose
        `status` is not `INVALIDATED`. `advisory_weight_total` is the sum of `weight` over findings
        at severity `ADVISORY` whose `cleared_by_referral_id` is null, restricted to the latest
        non-invalidated session, carried to one decimal place." (§3.2)

        Design: Difficulty/transitive_cascade/cascade_b_red_flag_screening_four_hop_fanout
        """
        env = _red_flag_cascade_environment()

        validate_success(
            api_client.submit_screening_session(
                env["screening"]["id"], make_patient_headers(env["patient"]["id"])
            )
        )

        patient = validate_success(api_client.get_patient(env["patient"]["id"], CARE_OPS))
        assert patient["status"] == "REFERRAL_REQUIRED", (
            f"a RED_FLAG outcome drives the patient to REFERRAL_REQUIRED, got {patient['status']!r}"
        )
        assert patient["open_mandatory_flag_count"] == 1, (
            "the single uncleared mandatory finding must be counted, got "
            f"{patient['open_mandatory_flag_count']}"
        )
        assert patient["advisory_weight_total"] == 0.0, (
            f"no advisory finding was emitted, got {patient['advisory_weight_total']}"
        )

    def test_red_flag_cascade_holds_the_order_without_touching_payment(self):
        """"Hop 2 moves every `DeviceOrder` of that patient whose `fulfillment_status` is
        `PENDING_FIT_CONFIRM` or `READY_TO_SHIP` to `MEDICAL_HOLD` with `medical_hold_reason` set to
        `MANDATORY_RED_FLAG`." (§2.8)

        "An order carries **two independent state dimensions on the same row**, and they advance
        under separate triggers." (§3.5)

        Design: Difficulty/transitive_cascade/cascade_b_red_flag_screening_four_hop_fanout
        """
        env = _red_flag_cascade_environment()
        assert env["order"]["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
            "the order must sit in PENDING_FIT_CONFIRM before the trigger, got "
            f"{env['order']['fulfillment_status']!r}"
        )

        validate_success(
            api_client.submit_screening_session(
                env["screening"]["id"], make_patient_headers(env["patient"]["id"])
            )
        )

        order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["fulfillment_status"] == "MEDICAL_HOLD", (
            f"hop 2 must hold the pending order, got {order['fulfillment_status']!r}"
        )
        assert order["medical_hold_reason"] == "MANDATORY_RED_FLAG", (
            f"the hold reason must be MANDATORY_RED_FLAG, got {order['medical_hold_reason']!r}"
        )
        assert order["payment_status"] == "PENDING_AUTH", (
            "the cascade follows the fulfillment dimension only, so payment stays PENDING_AUTH, got "
            f"{order['payment_status']!r}"
        )

    def test_red_flag_cascade_cancels_the_initial_fit_and_releases_provider_capacity(self):
        """"Hop 3 moves every `RemoteFittingSession` in `SCHEDULED` whose `session_type` is
        `INITIAL_FIT` or `FOLLOW_UP` and which references one of those orders to `CANCELLED`, with
        `no_show_charged_cents` forced to 0 — a medical hold never costs the patient a fee. Hop 4
        recomputes `booked_minutes_on_focus_date` and `utilization_pct` for every provider whose
        bookings hop 3 released." (§2.8)

        "the latter as 100 multiplied by `booked_minutes_on_focus_date` divided by
        `daily_capacity_minutes`, rounded half up to one decimal place." (§3.4)

        Design: Difficulty/transitive_cascade/cascade_b_red_flag_screening_four_hop_fanout
        """
        env = _red_flag_cascade_environment()

        before = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS))
        assert before["booked_minutes_on_focus_date"] == 60, (
            "the booked 60-minute session must be counted before the trigger, got "
            f"{before['booked_minutes_on_focus_date']}"
        )
        assert before["utilization_pct"] == 12.5, (
            f"60 of 480 minutes is 12.5 percent, got {before['utilization_pct']}"
        )

        validate_success(
            api_client.submit_screening_session(
                env["screening"]["id"], make_patient_headers(env["patient"]["id"])
            )
        )

        session = validate_success(
            api_client.get_remote_fitting_session(env["session"]["id"], CARE_OPS)
        )
        assert session["status"] == "CANCELLED", (
            f"hop 3 must cancel the SCHEDULED INITIAL_FIT session, got {session['status']!r}"
        )
        assert session["no_show_charged_cents"] == 0, (
            "a medical hold never charges the patient, got "
            f"{session['no_show_charged_cents']}"
        )

        after = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS))
        assert after["booked_minutes_on_focus_date"] == 0, (
            "hop 4 must release the cancelled booking's minutes, got "
            f"{after['booked_minutes_on_focus_date']}"
        )
        assert after["utilization_pct"] == 0.0, (
            f"an empty focus date is 0.0 percent utilised, got {after['utilization_pct']}"
        )
