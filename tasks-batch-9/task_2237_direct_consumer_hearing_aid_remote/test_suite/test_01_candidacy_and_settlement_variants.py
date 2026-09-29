"""Dual-variant calculations: candidacy scoring and restocking settlement.

Both suites drive the SAME measurable inputs through two different triggers and
prove the two variants produce different, independently derived numbers.
"""
from test_helpers import (
    CARE_OPS,
    api_client,
    confirm_and_ship,
    create_devices,
    create_inventory_pool,
    create_provider,
    create_state_policy,
    get_referral_for_patient,
    make_licensed_audiologist_headers,
    make_patient_headers,
    place_order,
    register_patient,
    scan_shipment,
    screen_patient,
    set_clock,
    simulate_payment,
    validate_success,
)

CLEAN_MEASUREMENTS = {
    "pure_tone_avg_db": 45.0,
    "asymmetry_db": 5.0,
    "self_reported_difficulty_score": 20,
    "speech_in_noise_pct": 70.0,
    "symptom_codes": [],
}


# ---------------------------------------------------------------------------
# Shared setup chains
# ---------------------------------------------------------------------------
def _setup_two_variants_from_identical_measurements() -> dict:
    """Two patients submit byte-identical measurements; only one is cleared by an audiologist.

    Patient X screens clean, so the submit writes the provisional score.
    Patient Y screens with a mandatory symptom code, is evaluated by a licensed
    audiologist, and the clearance determination writes the provider-adjusted score.
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy(
        state_code="CA",
        otc_sales_permitted=True,
        telehealth_fitting_permitted=True,
        min_age_years=18,
        trial_period_days=30,
        restocking_fee_mode="FLAT_PCT",
        restocking_fee_pct=0.1000,
        restocking_fee_cap_cents=0,
        shipping_refundable=False,
        referral_validity_days=180,
        waiver_required=False,
        max_loss_damage_claims=2,
    )
    audiologist = create_provider(
        provider_type="LICENSED_AUDIOLOGIST",
        npi="1234567893",
        full_name="Dr. Ada Reyes",
        licensed_state_codes=["CA"],
        daily_capacity_minutes=480,
        buffer_minutes=10,
    )
    patient_x = register_patient(
        policy["id"], email="x@example.com", full_name="Patient X", age_years=65
    )
    patient_y = register_patient(
        policy["id"], email="y@example.com", full_name="Patient Y", age_years=65
    )

    screening_x = screen_patient(patient_x["id"], **CLEAN_MEASUREMENTS)

    red_flag_measurements = dict(CLEAN_MEASUREMENTS, symptom_codes=["VERTIGO"])
    screening_y = screen_patient(patient_y["id"], **red_flag_measurements)
    referral_y = get_referral_for_patient(patient_y["id"])

    audiologist_headers = make_licensed_audiologist_headers(audiologist["id"])
    session_y = validate_success(
        api_client.create_remote_fitting_session(
            {
                "patient_id": patient_y["id"],
                "session_type": "REFERRAL_EVALUATION",
                "scheduled_start_utc": "2026-08-05T09:00:00Z",
                "scheduled_end_utc": "2026-08-05T10:00:00Z",
                "provider_id": audiologist["id"],
                "provider_referral_id": referral_y["id"],
            },
            make_patient_headers(patient_y["id"]),
        ),
        201,
    )
    set_clock("2026-08-05T09:00:00Z")
    validate_success(api_client.start_fitting_session(session_y["id"], audiologist_headers))
    validate_success(
        api_client.complete_fitting_session(session_y["id"], {}, audiologist_headers)
    )

    # Trigger: the licensed clearance is what selects the PROVIDER_ADJUSTED variant.
    validate_success(
        api_client.record_referral_determination(
            referral_y["id"],
            {"clearance_outcome": "CLEARED", "clearance_note": "No pathology on otoscopy."},
            audiologist_headers,
        )
    )

    return {
        "policy": policy,
        "audiologist": audiologist,
        "patient_x": patient_x,
        "patient_y": patient_y,
        "screening_x": screening_x,
        "screening_y": screening_y,
        "referral_y": referral_y,
    }


def _setup_flat_pct_and_prorated_returns() -> dict:
    """Two structurally identical orders under CA FLAT_PCT and TX PRORATED_DAILY.

    Both are delivered at 2026-08-01T00:00:00Z, both returned at 2026-08-07T00:00:00Z
    and both inspected RESELLABLE, so only the pinned restocking mode differs.
    """
    set_clock("2026-08-01T00:00:00Z")
    policy_ca = create_state_policy(
        state_code="CA",
        otc_sales_permitted=True,
        telehealth_fitting_permitted=True,
        min_age_years=18,
        trial_period_days=30,
        restocking_fee_mode="FLAT_PCT",
        restocking_fee_pct=0.1000,
        restocking_fee_cap_cents=0,
        shipping_refundable=False,
        referral_validity_days=180,
        waiver_required=False,
    )
    policy_tx = create_state_policy(
        state_code="TX",
        otc_sales_permitted=True,
        telehealth_fitting_permitted=True,
        min_age_years=18,
        trial_period_days=30,
        restocking_fee_mode="PRORATED_DAILY",
        restocking_daily_rate_cents=2500,
        restocking_fee_cap_cents=0,
        shipping_refundable=False,
        referral_validity_days=180,
        waiver_required=False,
    )
    create_inventory_pool(
        restock_units=5, sku="NEO-M-OPEN", model="NEO", dome_size="M", tip_type="OPEN"
    )
    create_devices(1, serial_number="SN-CA-0001", model="NEO", firmware_version="4.0.0")
    create_devices(1, serial_number="SN-TX-0001", model="NEO", firmware_version="4.0.0")

    patient_ca = register_patient(
        policy_ca["id"], email="ca@example.com", full_name="Cara Ash", age_years=65
    )
    patient_tx = register_patient(
        policy_tx["id"], email="tx@example.com", full_name="Tex Bell", age_years=65
    )
    screen_patient(patient_ca["id"], **CLEAN_MEASUREMENTS)
    screen_patient(patient_tx["id"], **CLEAN_MEASUREMENTS)

    order_economics = {
        "model": "NEO",
        "dome_size": "M",
        "tip_type": "OPEN",
        "list_price_cents": 199900,
        "discount_cents": 9900,
        "accessory_subtotal_cents": 4500,
        "shipping_cents": 1495,
    }
    order_ca = place_order(patient_ca["id"], **order_economics)
    order_tx = place_order(patient_tx["id"], **order_economics)

    for order in (order_ca, order_tx):
        simulate_payment(order["id"], "AUTHORIZED")
    for order in (order_ca, order_tx):
        confirm_and_ship(order["id"])
        scan_shipment(order["id"], "DELIVERED")

    # Exactly 6 * 86,400 seconds of elapsed trial for both orders.
    set_clock("2026-08-07T00:00:00Z")

    rmas = {}
    for key, patient, order in (
        ("ca", patient_ca, order_ca),
        ("tx", patient_tx, order_tx),
    ):
        trials = validate_success(
            api_client.list_trial_periods(CARE_OPS, params={"device_order_id": order["id"]})
        )
        trial = trials[0]
        rmas[key] = validate_success(
            api_client.create_return_authorization(
                trial["id"],
                {"expected_trial_period_version": trial["version"]},
                make_patient_headers(patient["id"]),
            ),
            201,
        )

    for order in (order_ca, order_tx):
        scan_shipment(order["id"], "RETURN_PICKED_UP")
    for key in ("ca", "tx"):
        validate_success(api_client.receive_return_authorization(rmas[key]["id"], CARE_OPS))

    # Trigger: inspection is what runs restocking settlement.
    settled = {}
    for key in ("ca", "tx"):
        settled[key] = validate_success(
            api_client.inspect_return_authorization(
                rmas[key]["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
            )
        )

    return {
        "order_ca": order_ca,
        "order_tx": order_tx,
        "rma_ca": settled["ca"],
        "rma_tx": settled["tx"],
    }


# ---------------------------------------------------------------------------
# dual_variant_calc: candidacy scoring
# ---------------------------------------------------------------------------
class TestCandidacyScoreVariants:
    """Identical measurements, two variants, two different scores."""

    def test_clean_screening_writes_provisional_self_reported_score_of_41_5(self, api):
        """PRD §3.2: "That transition recomputes `candidacy_risk_score` under the `PROVISIONAL_SELF_REPORTED` variant, sets `candidacy_risk_variant` to `PROVISIONAL_SELF_REPORTED`, derives `candidacy_risk_band` from the new score, refreshes `advisory_weight_total`, sets `open_mandatory_flag_count` to 0, and increments `screening_attempt_count`."

        PRD §3.2: "The weighted base is 100 multiplied by the sum of 0.40 times the pure-tone term, 0.25 times the difficulty term, 0.20 times the speech-in-noise term and 0.15 times the asymmetry term. Under the provisional variant — written by a screening submit that approved candidacy, before any provider has examined the patient — the score is that base rounded half up to one decimal place, with red-flag evidence excluded entirely and no attenuation applied."

        PRD §3.2: "The `candidacy_risk_band` is `LOW` when the score is strictly below 35.0, `MODERATE` when it is at least 35.0 and strictly below 65.0, and `HIGH` when it is at least 65.0."

        Design: Difficulty/dual_variant_calc/candidacy_provisional_vs_provider_adjusted_identical_measurements
        """
        env = _setup_two_variants_from_identical_measurements()

        screening = validate_success(
            api.get_screening_session(env["screening_x"]["id"], CARE_OPS)
        )
        assert screening["status"] == "SCORED", (
            f"a submitted clean screening must be SCORED, got {screening['status']}"
        )
        assert screening["screening_outcome"] == "PASS", (
            f"clean measurements must score PASS, got {screening['screening_outcome']}"
        )

        patient = validate_success(api.get_patient(env["patient_x"]["id"], CARE_OPS))
        assert patient["status"] == "CANDIDATE_APPROVED", (
            f"a PASS with no mandatory findings approves candidacy, got {patient['status']}"
        )
        assert patient["candidacy_risk_variant"] == "PROVISIONAL_SELF_REPORTED", (
            "a screening submit writes the provisional variant, got "
            f"{patient['candidacy_risk_variant']}"
        )
        assert patient["candidacy_risk_score"] == 41.5, (
            "the raw weighted base rounded once at the end is 41.5, got "
            f"{patient['candidacy_risk_score']}"
        )
        assert patient["candidacy_risk_band"] == "MODERATE", (
            f"41.5 falls in [35.0, 65.0) so the band is MODERATE, got {patient['candidacy_risk_band']}"
        )

    def test_licensed_clearance_writes_provider_adjusted_score_of_41_3(self, api):
        """PRD §3.2: "Under the provider-adjusted variant — written by a licensed clearance — the base is first attenuated to 85 percent of itself, then increased by 6.0 points for each mandatory finding the clearing referral retired and by 2.0 points for each unit of the patient's `advisory_weight_total` as observed when the referral was issued; the resulting figure is capped at 100.0 and then rounded half up to one decimal place. Rounding happens exactly once, at the end, and never to an intermediate term. Identical screening measurements therefore yield a different score under the two variants, which is intended."

        PRD §3.3: "recomputes `candidacy_risk_score` under the `PROVIDER_ADJUSTED` variant and sets `candidacy_risk_variant` to `PROVIDER_ADJUSTED`, moves the patient `REFERRAL_REQUIRED → PROVIDER_CLEARED`"

        Design: Difficulty/dual_variant_calc/candidacy_provisional_vs_provider_adjusted_identical_measurements
        """
        env = _setup_two_variants_from_identical_measurements()

        patient = validate_success(api.get_patient(env["patient_y"]["id"], CARE_OPS))
        assert patient["status"] == "PROVIDER_CLEARED", (
            f"a CLEARED determination moves the patient to PROVIDER_CLEARED, got {patient['status']}"
        )
        assert patient["candidacy_risk_variant"] == "PROVIDER_ADJUSTED", (
            "the variant is selected by the clearance trigger, never by payload, got "
            f"{patient['candidacy_risk_variant']}"
        )
        assert patient["candidacy_risk_score"] == 41.3, (
            "attenuating the base to 85 percent and adding 6.0 for the single retired "
            f"mandatory finding gives 41.3, got {patient['candidacy_risk_score']}"
        )
        assert patient["candidacy_risk_score"] != 41.5, (
            "41.5 is the provisional reading; the provider-adjusted score must not reuse it"
        )
        assert patient["candidacy_risk_score"] != 35.3, (
            "35.3 is attenuation without the cleared mandatory-finding points"
        )
        assert patient["candidacy_risk_band"] == "MODERATE", (
            f"41.3 falls in [35.0, 65.0) so the band is MODERATE, got {patient['candidacy_risk_band']}"
        )

    def test_clearance_retires_the_single_mandatory_finding_and_clears_the_flag_counters(self, api):
        """PRD §3.2: "A `RED_FLAG` outcome drives the patient into `REFERRAL_REQUIRED`"

        PRD §3.3: "it stamps `cleared_by_referral_id` on every still-open finding whose `code` appears in the referral's `reason_codes`, increments the referral's `cleared_finding_count` accordingly, recomputes the patient's `open_mandatory_flag_count` (which should now be zero) and `advisory_weight_total`"

        Design: Difficulty/dual_variant_calc/candidacy_provisional_vs_provider_adjusted_identical_measurements
        """
        env = _setup_two_variants_from_identical_measurements()

        screening = validate_success(
            api.get_screening_session(env["screening_y"]["id"], CARE_OPS)
        )
        assert screening["screening_outcome"] == "RED_FLAG", (
            "a mandatory symptom code scores RED_FLAG, got "
            f"{screening['screening_outcome']}"
        )

        referral = validate_success(api.get_provider_referral(env["referral_y"]["id"], CARE_OPS))
        assert referral["status"] == "CLEARED", (
            f"the determination moves the referral to CLEARED, got {referral['status']}"
        )
        assert referral["cleared_finding_count"] == 1, (
            "exactly one mandatory finding was retired by this referral, got "
            f"{referral['cleared_finding_count']}"
        )

        patient = validate_success(api.get_patient(env["patient_y"]["id"], CARE_OPS))
        assert patient["open_mandatory_flag_count"] == 0, (
            "the clearance leaves no open mandatory flag, got "
            f"{patient['open_mandatory_flag_count']}"
        )
        assert patient["advisory_weight_total"] == 0.0, (
            "no advisory findings were emitted, so the advisory weight total is 0.0, got "
            f"{patient['advisory_weight_total']}"
        )


# ---------------------------------------------------------------------------
# dual_variant_calc: restocking settlement
# ---------------------------------------------------------------------------
class TestRestockingSettlementVariants:
    """Identical orders returned on identical trial days settle to different refunds."""

    def test_flat_pct_settlement_charges_device_and_half_rate_accessory_components(self, api):
        """PRD §3.6: "Under `FLAT_PCT`, the device portion is the device component multiplied by the policy's `restocking_fee_pct`, rounded half up; the accessory portion is the accessory component multiplied by `restocking_fee_pct` and again by an accessory factor of 0.5 — accessories restock at half the device rate — rounded half up."

        PRD §3.6: "Step six sets `non_refundable_shipping_cents` to 0 when the pinned policy's `shipping_refundable` is true, and to the order's `shipping_cents` otherwise. Step seven sets `refund_amount_cents` to the order's `captured_cents` minus `restocking_fee_cents` minus `non_refundable_shipping_cents`, floored at 0."

        Design: Difficulty/dual_variant_calc/return_settlement_flat_pct_vs_prorated_daily_same_day_return
        """
        env = _setup_flat_pct_and_prorated_returns()

        order = validate_success(api.get_device_order(env["order_ca"]["id"], CARE_OPS))
        assert order["tax_cents"] == 14101, (
            f"the taxable base at 7.25 percent rounds to 14101 cents, got {order['tax_cents']}"
        )
        assert order["total_cents"] == 210096, (
            f"the composed order total is 210096 cents, got {order['total_cents']}"
        )
        assert order["captured_cents"] == 210096, (
            f"shipping captures the whole total, got {order['captured_cents']}"
        )
        assert order["pinned_restocking_mode"] == "FLAT_PCT", (
            "checkout pins the CA policy's FLAT_PCT mode, got "
            f"{order['pinned_restocking_mode']}"
        )
        assert order["pinned_trial_days"] == 30, (
            f"checkout pins trial_period_days 30, got {order['pinned_trial_days']}"
        )

        rma = validate_success(api.get_return_authorization(env["rma_ca"]["id"], CARE_OPS))
        assert rma["days_used_at_issue"] == 6, (
            f"six whole days elapsed before the return was issued, got {rma['days_used_at_issue']}"
        )
        assert rma["restocking_variant"] == "FLAT_PCT", (
            f"the variant follows the pinned mode, got {rma['restocking_variant']}"
        )
        assert rma["restocking_fee_cents"] == 19225, (
            "the device portion 19000 plus the half-rate accessory portion 225 is 19225, got "
            f"{rma['restocking_fee_cents']}"
        )
        assert rma["non_refundable_shipping_cents"] == 1495, (
            "shipping_refundable is false so the order's shipping is retained, got "
            f"{rma['non_refundable_shipping_cents']}"
        )
        assert rma["refund_amount_cents"] == 189376, (
            f"210096 - 19225 - 1495 is 189376, got {rma['refund_amount_cents']}"
        )

    def test_prorated_daily_settlement_charges_the_daily_rate_and_no_accessory_component(self, api):
        """PRD §3.6: "Under `PRORATED_DAILY`, the device portion is the policy's `restocking_daily_rate_cents` multiplied by the lesser of `days_used_at_issue` and the order's `pinned_trial_days`, and the accessory portion is 0."

        PRD §3.6: "Step seven sets `refund_amount_cents` to the order's `captured_cents` minus `restocking_fee_cents` minus `non_refundable_shipping_cents`, floored at 0."

        Design: Difficulty/dual_variant_calc/return_settlement_flat_pct_vs_prorated_daily_same_day_return
        """
        env = _setup_flat_pct_and_prorated_returns()

        order = validate_success(api.get_device_order(env["order_tx"]["id"], CARE_OPS))
        assert order["tax_cents"] == 14101, (
            f"the identical taxable base rounds to the same 14101 cents, got {order['tax_cents']}"
        )
        assert order["total_cents"] == 210096, (
            f"the composed order total is 210096 cents, got {order['total_cents']}"
        )
        assert order["captured_cents"] == 210096, (
            f"shipping captures the whole total, got {order['captured_cents']}"
        )
        assert order["pinned_restocking_mode"] == "PRORATED_DAILY", (
            "checkout pins the TX policy's PRORATED_DAILY mode, got "
            f"{order['pinned_restocking_mode']}"
        )
        assert order["pinned_trial_days"] == 30, (
            f"checkout pins trial_period_days 30, got {order['pinned_trial_days']}"
        )

        rma = validate_success(api.get_return_authorization(env["rma_tx"]["id"], CARE_OPS))
        assert rma["days_used_at_issue"] == 6, (
            f"six whole days elapsed before the return was issued, got {rma['days_used_at_issue']}"
        )
        assert rma["restocking_variant"] == "PRORATED_DAILY", (
            f"the variant follows the pinned mode, got {rma['restocking_variant']}"
        )
        assert rma["restocking_fee_cents"] == 15000, (
            "2500 cents per day times min(6, 30) days is 15000 with no accessory portion, got "
            f"{rma['restocking_fee_cents']}"
        )
        assert rma["non_refundable_shipping_cents"] == 1495, (
            "shipping_refundable is false so the order's shipping is retained, got "
            f"{rma['non_refundable_shipping_cents']}"
        )
        assert rma["refund_amount_cents"] == 193601, (
            f"210096 - 15000 - 1495 is 193601, got {rma['refund_amount_cents']}"
        )

    def test_the_two_variants_diverge_by_exactly_4225_cents_on_identical_orders(self, api):
        """PRD §3.6: "**Restocking settlement** runs at inspection and is the most rounding-sensitive computation in the system. Its inputs are the authorization's own `days_used_at_issue` snapshot and `inspection_grade`, the order's `pinned_restocking_mode`, `pinned_trial_days`, `captured_cents` and `shipping_cents`, and the **pinned** policy row read at the order's `pinned_state_policy_version`; live policy edits made after checkout are excluded."

        PRD §3.6: "Step two selects the variant, testing in this order: if the pinned mode is `PROHIBITED` the variant is `WAIVED`; otherwise if `days_used_at_issue` is 0 the variant is `WAIVED` — a same-day return is never charged restocking; otherwise if the pinned mode is `FLAT_PCT` the variant is `FLAT_PCT`; otherwise it is `PRORATED_DAILY`."

        Design: Difficulty/dual_variant_calc/return_settlement_flat_pct_vs_prorated_daily_same_day_return
        """
        env = _setup_flat_pct_and_prorated_returns()

        rma_ca = validate_success(api.get_return_authorization(env["rma_ca"]["id"], CARE_OPS))
        rma_tx = validate_success(api.get_return_authorization(env["rma_tx"]["id"], CARE_OPS))

        assert rma_ca["days_used_at_issue"] == rma_tx["days_used_at_issue"] == 6, (
            "both returns were issued on the same trial day, got "
            f"{rma_ca['days_used_at_issue']} and {rma_tx['days_used_at_issue']}"
        )
        assert rma_ca["inspection_grade"] == rma_tx["inspection_grade"] == "RESELLABLE", (
            "both units were graded RESELLABLE, got "
            f"{rma_ca['inspection_grade']} and {rma_tx['inspection_grade']}"
        )
        assert rma_tx["refund_amount_cents"] - rma_ca["refund_amount_cents"] == 4225, (
            "the pinned restocking mode is the only difference, and it moves the refund by "
            f"exactly 4225 cents, got "
            f"{rma_tx['refund_amount_cents'] - rma_ca['refund_amount_cents']}"
        )

    def test_whole_order_return_settlement_components_sum_back_to_captured(self, api):
        """PRD §3.6: "For a whole-order return, `refund_amount_cents` plus `restocking_fee_cents` plus `non_refundable_shipping_cents` equals `captured_cents` exactly."

        Design: Difficulty/dual_variant_calc/return_settlement_flat_pct_vs_prorated_daily_same_day_return
        """
        env = _setup_flat_pct_and_prorated_returns()

        for order_key, rma_key, label in (
            ("order_ca", "rma_ca", "FLAT_PCT"),
            ("order_tx", "rma_tx", "PRORATED_DAILY"),
        ):
            order = validate_success(api.get_device_order(env[order_key]["id"], CARE_OPS))
            rma = validate_success(api.get_return_authorization(env[rma_key]["id"], CARE_OPS))
            total = (
                rma["refund_amount_cents"]
                + rma["restocking_fee_cents"]
                + rma["non_refundable_shipping_cents"]
            )
            assert total == order["captured_cents"], (
                f"under {label} the three settlement components must sum back to the captured "
                f"{order['captured_cents']} cents, got {total}"
            )
