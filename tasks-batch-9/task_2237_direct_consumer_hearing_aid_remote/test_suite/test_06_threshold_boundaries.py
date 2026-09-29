"""Inclusive-boundary behaviour: provider capacity, whole-day counting, advisory weight."""
from test_helpers import (
    CARE_OPS,
    ApiErrorId,
    api_client,
    assert_same_instant,
    create_provider,
    get_success_data,
    make_patient_headers,
    setup_registered_patient,
    setup_return_received,
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

# --- Provider capacity ---------------------------------------------------------
DAILY_CAPACITY_MINUTES = 120
FIRST_SLOT = ("2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z")
CEILING_SLOT = ("2026-08-10T11:00:00Z", "2026-08-10T12:00:00Z")
OVERFLOW_SLOT = ("2026-08-10T13:00:00Z", "2026-08-10T13:15:00Z")
NEXT_DAY_SLOT = ("2026-08-11T09:00:00Z", "2026-08-11T09:15:00Z")

# --- Zero-day return -----------------------------------------------------------
RMA_ISSUED_AT = "2026-08-01T23:59:59Z"
TRIAL_STARTED_AT = "2026-08-01T00:00:00Z"
RETURN_DEADLINE_UTC = "2026-08-15T23:59:59Z"
DAMAGE_SURCHARGE_CENTS = 28500
FLAT_PCT_RESTOCKING_CENTS = 47725
NON_REFUNDABLE_SHIPPING_CENTS = 1495
REFUND_AMOUNT_CENTS = 180101

# --- Advisory threshold --------------------------------------------------------
REFERRAL_EXPIRES_AT = "2027-01-28T00:00:00Z"


def _provider_with_one_booked_hour() -> dict:
    """A 120-minute-capacity fitter carrying a single 60-minute booking on 2026-08-10."""
    env = setup_registered_patient(policy_overrides=CA_POLICY, patient_overrides={"age_years": 62})
    env["provider"] = create_provider(
        provider_type="TELECARE_FITTER",
        npi="1760488321",
        full_name="Cap Tester",
        licensed_state_codes=["CA"],
        daily_capacity_minutes=DAILY_CAPACITY_MINUTES,
        buffer_minutes=0,
    )
    env["session"] = _book(env, FIRST_SLOT, expect_created=True)
    return env


def _book(env: dict, slot, expect_created: bool = False):
    """Request a TROUBLESHOOT session in `slot`; return the created row or the raw response."""
    response = api_client.create_remote_fitting_session(
        {
            "patient_id": env["patient"]["id"],
            "session_type": "TROUBLESHOOT",
            "scheduled_start_utc": slot[0],
            "scheduled_end_utc": slot[1],
            "provider_id": env["provider"]["id"],
        },
        make_patient_headers(env["patient"]["id"]),
    )
    if expect_created:
        return get_success_data(response)
    return response


def _same_day_damaged_return() -> dict:
    """Delivered order returned 86,399 seconds later, received at the depot, not yet inspected."""
    return setup_return_received(
        at_iso=RMA_ISSUED_AT, policy_overrides=CA_POLICY, patient_overrides={"age_years": 74}
    )


def _measured_screening(symptom_codes) -> dict:
    """A registered 65-year-old with a measured but unsubmitted screening."""
    env = setup_registered_patient(policy_overrides=CA_POLICY, patient_overrides={"age_years": 65})
    headers = make_patient_headers(env["patient"]["id"])
    env["screening"] = get_success_data(
        api_client.start_screening_session(env["patient"]["id"], {}, headers)
    )
    get_success_data(
        api_client.update_screening_session(
            env["screening"]["id"],
            {
                "pure_tone_avg_db": 45.0,
                "asymmetry_db": 5.0,
                "self_reported_difficulty_score": 20,
                "speech_in_noise_pct": 70.0,
                "symptom_codes": list(symptom_codes),
            },
            headers,
        )
    )
    return env


class TestProviderDailyCapacityBoundary:
    """The capacity ceiling is inclusive and is keyed on the candidate's UTC focus date."""

    def test_booking_that_exactly_fills_the_daily_capacity_is_accepted(self):
        """"The booking is accepted when the already-booked minutes plus the candidate's
        `duration_minutes` is at most `daily_capacity_minutes`; exact equality is accepted, so a
        provider with 480 minutes of capacity may take a 60-minute session on top of 420 already
        booked but not on top of 421." (§3.4)

        "the provider's `booked_minutes_on_focus_date` and `utilization_pct` are recomputed, the
        latter as 100 multiplied by `booked_minutes_on_focus_date` divided by
        `daily_capacity_minutes`, rounded half up to one decimal place." (§3.4)

        Design: Difficulty/boundary_precision_check/provider_capacity_exact_equality_accepted_then_one_over_rejected
        """
        env = _provider_with_one_booked_hour()

        baseline = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS))
        assert baseline["booked_minutes_on_focus_date"] == 60, (
            f"the single 60-minute booking must be counted, got {baseline['booked_minutes_on_focus_date']}"
        )
        assert baseline["utilization_pct"] == 50.0, (
            f"60 of 120 minutes is 50.0 percent, got {baseline['utilization_pct']}"
        )

        created = validate_success(_book(env, CEILING_SLOT), 201)
        assert created["status"] == "SCHEDULED", (
            f"creation confirms the slot in the same request, got {created['status']!r}"
        )
        assert created["duration_minutes"] == 60, (
            f"an 11:00-12:00 slot is 60 minutes, got {created['duration_minutes']}"
        )

        provider = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS))
        assert provider["booked_minutes_on_focus_date"] == 120, (
            "60 + 60 exactly fills the day, got "
            f"{provider['booked_minutes_on_focus_date']}"
        )
        assert provider["utilization_pct"] == 100.0, (
            f"a full day reads 100.0 percent, got {provider['utilization_pct']}"
        )

    def test_booking_one_quarter_hour_over_the_daily_capacity_is_rejected(self):
        """"Exceeding the ceiling is rejected with `ERR_PROVIDER_CAPACITY_EXCEEDED`." (§3.4)

        "`booked_minutes_on_focus_date` is the sum of `duration_minutes` over that provider's
        sessions whose `status` is `SCHEDULED`, `IN_PROGRESS` or `COMPLETED` and whose own
        `scheduled_start_utc` falls on that same UTC date." (§3.4)

        Design: Difficulty/boundary_precision_check/provider_capacity_exact_equality_accepted_then_one_over_rejected
        """
        env = _provider_with_one_booked_hour()
        _book(env, CEILING_SLOT, expect_created=True)

        validate_error(
            _book(env, OVERFLOW_SLOT), ApiErrorId.ERR_PROVIDER_CAPACITY_EXCEEDED.value
        )

        provider = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS))
        assert provider["booked_minutes_on_focus_date"] == 120, (
            "the rejected request must change nothing, got "
            f"{provider['booked_minutes_on_focus_date']}"
        )
        assert provider["utilization_pct"] == 100.0, (
            f"utilization must stay 100.0, got {provider['utilization_pct']}"
        )

        rows = api_client.list_remote_fitting_sessions(
            CARE_OPS, params={"provider_id": env["provider"]["id"], "status": "SCHEDULED"}
        ).json()["data"]
        assert len(rows) == 2, (
            f"only the two accepted bookings may exist, got {len(rows)} scheduled sessions"
        )

    def test_the_same_rejected_slot_length_is_accepted_on_the_next_focus_date(self):
        """"The focus date is the UTC calendar date of the candidate's `scheduled_start_utc`" (§3.4)

        "Sessions in `NO_SHOW`, `CANCELLED` or `REQUESTED` are excluded, and a session that runs past
        midnight is attributed entirely to the date of its start." (§3.4)

        Design: Difficulty/boundary_precision_check/provider_capacity_exact_equality_accepted_then_one_over_rejected
        """
        env = _provider_with_one_booked_hour()
        _book(env, CEILING_SLOT, expect_created=True)
        validate_error(
            _book(env, OVERFLOW_SLOT), ApiErrorId.ERR_PROVIDER_CAPACITY_EXCEEDED.value
        )

        created = validate_success(_book(env, NEXT_DAY_SLOT), 201)
        assert created["status"] == "SCHEDULED", (
            "the fifteen minutes the full day refused fit on the next day, got "
            f"{created['status']!r}"
        )
        assert created["duration_minutes"] == 15, (
            f"a 09:00-09:15 slot is 15 minutes, got {created['duration_minutes']}"
        )

        provider = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS))
        assert provider["booked_minutes_on_focus_date"] == 15, (
            "the focus date moved to 2026-08-11, which holds only the 15-minute booking, got "
            f"{provider['booked_minutes_on_focus_date']}"
        )
        assert provider["utilization_pct"] == 12.5, (
            f"15 of 120 minutes is 12.5 percent, got {provider['utilization_pct']}"
        )


class TestZeroDayReturnBoundary:
    """86,399 seconds under trial is zero whole days, which waives percentage restocking."""

    def test_a_return_issued_one_second_short_of_a_day_snapshots_zero_days_used(self):
        """"Elapsed days are the counting-window end minus `started_at`, in seconds, divided by
        86,400 and floored, so a span of exactly 86,400 seconds counts as one day while 86,399 counts
        as zero." (§3.6)

        "Initiation creates a `ReturnAuthorization` in `ISSUED` with a globally unique human-facing
        `rma_code`, a `days_used_at_issue` snapshot of the trial's `days_used` at that instant, a
        `return_deadline_utc` of the current clock plus 14 days (two weeks)" (§3.6)

        Design: Difficulty/boundary_precision_check/zero_day_return_waives_restocking_but_not_damage_surcharge
        """
        env = _same_day_damaged_return()

        trial = validate_success(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
        assert_same_instant(
            trial["started_at"], TRIAL_STARTED_AT,
            f"the delivery scan starts the trial at 2026-08-01T00:00:00Z, got {trial['started_at']!r}",
        )
        assert trial["days_used"] == 0, (
            f"86,399 seconds is zero whole days, got days_used {trial['days_used']}"
        )

        rma = validate_success(api_client.get_return_authorization(env["rma"]["id"], CARE_OPS))
        assert rma["days_used_at_issue"] == 0, (
            f"the issue-time snapshot must be 0, got {rma['days_used_at_issue']}"
        )
        assert_same_instant(
            rma["return_deadline_utc"], RETURN_DEADLINE_UTC,
            "the deadline is the issue instant plus 14 days, got "
            f"{rma['return_deadline_utc']!r}",
        )

    def test_zero_days_used_waives_the_percentage_restocking_even_under_flat_pct(self):
        """"Step two selects the variant, testing in this order: if the pinned mode is `PROHIBITED`
        the variant is `WAIVED`; otherwise if `days_used_at_issue` is 0 the variant is `WAIVED` — a
        same-day return is never charged restocking; otherwise if the pinned mode is `FLAT_PCT` the
        variant is `FLAT_PCT`; otherwise it is `PRORATED_DAILY`." (§3.6)

        "Under `WAIVED`, both portions are 0." (§3.6)

        Design: Difficulty/boundary_precision_check/zero_day_return_waives_restocking_but_not_damage_surcharge
        """
        env = _same_day_damaged_return()

        order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["pinned_restocking_mode"] == "FLAT_PCT", (
            "the order pinned the percentage mode at checkout, got "
            f"{order['pinned_restocking_mode']!r}"
        )

        inspected = validate_success(
            api_client.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "DAMAGED"}, CARE_OPS
            )
        )
        assert inspected["status"] == "INSPECTED", (
            f"inspection moves the authorization to INSPECTED, got {inspected['status']!r}"
        )
        assert inspected["restocking_variant"] == "WAIVED", (
            "a zero-day return waives restocking despite the pinned FLAT_PCT mode, got "
            f"{inspected['restocking_variant']!r}"
        )
        assert inspected["restocking_fee_cents"] != FLAT_PCT_RESTOCKING_CENTS, (
            "the percentage branch must not run, but the fee is the FLAT_PCT figure "
            f"{inspected['restocking_fee_cents']}"
        )

    def test_damage_surcharge_survives_the_waived_variant(self):
        """"Step four adds a **third, independently rounded component**: a damage surcharge. A
        `DAMAGED` grade surcharges the device component multiplied by 0.15, rounded half up ... This
        surcharge applies **even under the `WAIVED` variant** — a state's prohibition on restocking
        fees does not shield a patient from damage they caused." (§3.6)

        "Step seven sets `refund_amount_cents` to the order's `captured_cents` minus
        `restocking_fee_cents` minus `non_refundable_shipping_cents`, floored at 0." (§3.6)

        Design: Difficulty/boundary_precision_check/zero_day_return_waives_restocking_but_not_damage_surcharge
        """
        env = _same_day_damaged_return()

        inspected = validate_success(
            api_client.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "DAMAGED"}, CARE_OPS
            )
        )
        assert inspected["restocking_fee_cents"] == DAMAGE_SURCHARGE_CENTS, (
            "the fee is the damage surcharge alone, 190000 times 0.15 = 28500, got "
            f"{inspected['restocking_fee_cents']}"
        )
        assert inspected["non_refundable_shipping_cents"] == NON_REFUNDABLE_SHIPPING_CENTS, (
            "a policy with shipping_refundable false keeps the 1495 cents of shipping, got "
            f"{inspected['non_refundable_shipping_cents']}"
        )
        assert inspected["refund_amount_cents"] == REFUND_AMOUNT_CENTS, (
            "the refund is 210096 - 28500 - 1495 = 180101, got "
            f"{inspected['refund_amount_cents']}"
        )


class TestAdvisoryReferralThreshold:
    """The 2.5 advisory-weight threshold is inclusive."""

    def test_advisory_weights_summing_to_exactly_two_point_five_score_a_red_flag(self):
        """"A declared pain symptom emits `EAR_PAIN` at severity `ADVISORY` with weight 1.5. ... A
        declared wax symptom emits `IMPACTED_CERUMEN`, advisory, weight 1.0." (§3.2)

        "Otherwise, if the advisory sum is at least 2.5 — the threshold is inclusive, so a pain
        finding plus a wax finding, totalling 2.5, is a red flag — the outcome is also
        `RED_FLAG`." (§3.2)

        "Scoring runs a **finding detection table in exactly this order**, appending a
        `RedFlagFinding` for each condition that holds" (§3.2)

        Design: Difficulty/boundary_precision_check/advisory_referral_threshold_inclusive_at_two_point_five
        """
        env = _measured_screening(("PAIN", "WAX"))
        headers = make_patient_headers(env["patient"]["id"])

        scored = validate_success(api_client.submit_screening_session(env["screening"]["id"], headers))
        assert scored["status"] == "SCORED", (
            f"submit scores the session in the same request, got {scored['status']!r}"
        )
        assert scored["screening_outcome"] == "RED_FLAG", (
            f"an advisory sum of exactly 2.5 is a red flag, got {scored['screening_outcome']!r}"
        )

        findings = api_client.list_screening_red_flag_findings(
            env["screening"]["id"], headers
        ).json()["data"]
        assert len(findings) == 2, f"pain and wax emit two findings, got {len(findings)}"
        assert findings[0]["code"] == "EAR_PAIN", (
            f"the pain finding comes first in the detection table, got {findings[0]['code']!r}"
        )
        assert findings[0]["severity"] == "ADVISORY", (
            f"a pain finding is advisory, got {findings[0]['severity']!r}"
        )
        assert findings[0]["weight"] == 1.5, (
            f"a pain finding weighs 1.5, got {findings[0]['weight']}"
        )
        assert findings[1]["code"] == "IMPACTED_CERUMEN", (
            f"the wax finding comes second, got {findings[1]['code']!r}"
        )
        assert findings[1]["severity"] == "ADVISORY", (
            f"a wax finding is advisory, got {findings[1]['severity']!r}"
        )
        assert findings[1]["weight"] == 1.0, (
            f"a wax finding weighs 1.0, got {findings[1]['weight']}"
        )

    def test_red_flag_at_the_inclusive_threshold_opens_a_referral_without_mandatory_findings(self):
        """"A `RED_FLAG` outcome drives the patient into `REFERRAL_REQUIRED`" (§3.3)

        "`advisory_weight_total` is the sum of `weight` over findings at severity `ADVISORY` whose
        `cleared_by_referral_id` is null, restricted to the latest non-invalidated session, carried to
        one decimal place." (§3.2)

        "Hop 1 of that cascade opens a `ProviderReferral` in `OPEN` ... stamping `issued_at` from the
        logical clock, and computing `expires_at` as `issued_at` plus the patient's policy
        `referral_validity_days` days." (§3.3)

        Design: Difficulty/boundary_precision_check/advisory_referral_threshold_inclusive_at_two_point_five
        """
        env = _measured_screening(("PAIN", "WAX"))

        validate_success(
            api_client.submit_screening_session(
                env["screening"]["id"], make_patient_headers(env["patient"]["id"])
            )
        )

        patient = validate_success(api_client.get_patient(env["patient"]["id"], CARE_OPS))
        assert patient["status"] == "REFERRAL_REQUIRED", (
            f"the threshold red flag must block candidacy, got {patient['status']!r}"
        )
        assert patient["advisory_weight_total"] == 2.5, (
            f"the advisory total is carried as 2.5, got {patient['advisory_weight_total']}"
        )
        assert patient["open_mandatory_flag_count"] == 0, (
            "no mandatory finding was emitted, so the mandatory counter stays 0, got "
            f"{patient['open_mandatory_flag_count']}"
        )

        referrals = api_client.list_provider_referrals(
            CARE_OPS, params={"patient_id": env["patient"]["id"]}
        ).json()["data"]
        assert len(referrals) == 1, f"exactly one referral is opened, got {len(referrals)}"
        assert referrals[0]["status"] == "OPEN", (
            f"the new referral is OPEN, got {referrals[0]['status']!r}"
        )
        assert_same_instant(
            referrals[0]["expires_at"], REFERRAL_EXPIRES_AT,
            "expires_at is the 2026-08-01 issue instant plus 180 days, got "
            f"{referrals[0]['expires_at']!r}",
        )

    def test_advisory_weights_below_the_threshold_approve_candidacy_provisionally(self):
        """"Otherwise, if the advisory sum is greater than zero, the outcome is
        `ADVISORY_PASS`." (§3.2)

        "A `PASS` or `ADVISORY_PASS` moves the patient `SCREENING_IN_PROGRESS →
        CANDIDATE_APPROVED`, provided there are no mandatory findings, the advisory sum is below 2.5,
        and the patient's `age_years` is at least the policy's `min_age_years`. That transition
        recomputes `candidacy_risk_score` under the `PROVISIONAL_SELF_REPORTED` variant, sets
        `candidacy_risk_variant` to `PROVISIONAL_SELF_REPORTED`, derives `candidacy_risk_band` from
        the new score, refreshes `advisory_weight_total`, sets `open_mandatory_flag_count` to 0, and
        increments `screening_attempt_count`." (§3.2)

        "The `candidacy_risk_band` is `LOW` when the score is strictly below 35.0, `MODERATE` when it
        is at least 35.0 and strictly below 65.0, and `HIGH` when it is at least 65.0." (§3.2)

        Design: Difficulty/boundary_precision_check/advisory_referral_threshold_inclusive_at_two_point_five
        """
        env = _measured_screening(("WAX", "TINNITUS_ONE_EAR"))

        scored = validate_success(
            api_client.submit_screening_session(
                env["screening"]["id"], make_patient_headers(env["patient"]["id"])
            )
        )
        assert scored["screening_outcome"] == "ADVISORY_PASS", (
            f"an advisory sum of 2.0 stays below the threshold, got {scored['screening_outcome']!r}"
        )

        patient = validate_success(api_client.get_patient(env["patient"]["id"], CARE_OPS))
        assert patient["status"] == "CANDIDATE_APPROVED", (
            f"a sub-threshold advisory pass approves candidacy, got {patient['status']!r}"
        )
        assert patient["advisory_weight_total"] == 2.0, (
            f"wax plus one-ear tinnitus totals 2.0, got {patient['advisory_weight_total']}"
        )
        assert patient["candidacy_risk_score"] == 41.5, (
            f"the provisional composite for these measurements is 41.5, got "
            f"{patient['candidacy_risk_score']}"
        )
        assert patient["candidacy_risk_variant"] == "PROVISIONAL_SELF_REPORTED", (
            f"a screening submit writes the provisional variant, got {patient['candidacy_risk_variant']!r}"
        )
        assert patient["candidacy_risk_band"] == "MODERATE", (
            f"41.5 sits in the MODERATE band, got {patient['candidacy_risk_band']!r}"
        )

        referrals = api_client.list_provider_referrals(
            CARE_OPS, params={"patient_id": env["patient"]["id"]}
        ).json()["data"]
        assert referrals == [], (
            f"a sub-threshold advisory pass opens no referral, got {len(referrals)} rows"
        )
