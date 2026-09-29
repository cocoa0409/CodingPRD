"""Screening red-flag detection, candidacy scoring, order totals, trial day counting
and restocking-settlement arithmetic.

Every expectation in this module is a number the PRD pins explicitly, including the
direction of every rounding and the inclusivity of every boundary.
"""
from datetime import datetime

import pytest

from test_helpers import (
    CARE_OPS,
    CLOCK_START_UTC,
    REPAIR_TECH,
    api_client,
    create_state_policy,
    get_pool,
    get_success_data,
    make_licensed_audiologist_headers,
    make_patient_headers,
    open_repair_order,
    register_patient,
    screening_measurements_payload,
    set_clock,
    setup_delivered_order,
    setup_evaluated_referral,
    setup_return_received,
    validate_success,
)

# The canonical symptom-free profile used by every recipe that must not trip a finding.
_MILD_PROFILE = {
    "pure_tone_avg_db": 40.0,
    "asymmetry_db": 5.0,
    "self_reported_difficulty_score": 20,
    "speech_in_noise_pct": 70.0,
    "symptom_codes": [],
}

# Order economics used by the settlement recipes: device subtotal 200000, no accessories.
_PLAIN_ORDER = {
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so a trailing 'Z' and '.000Z' compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual: str, expected: str, label: str) -> None:
    assert _instant(actual) == _instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def _submit_screening(policy_overrides=None, patient_overrides=None, **measurements):
    """Policy + patient + one measured screening, submitted. Returns (patient, session, resp)."""
    set_clock(CLOCK_START_UTC)
    policy = create_state_policy(**(policy_overrides or {}))
    patient = register_patient(policy["id"], **(patient_overrides or {}))
    headers = make_patient_headers(patient["id"])
    session = get_success_data(api_client.start_screening_session(patient["id"], {}, headers))
    get_success_data(
        api_client.update_screening_session(
            session["id"], screening_measurements_payload(**measurements), headers
        )
    )
    resp = api_client.submit_screening_session(session["id"], headers)
    return patient, session, resp


def _findings(session_id: str, patient_id: str) -> list:
    return get_success_data(
        api_client.list_screening_red_flag_findings(
            session_id, make_patient_headers(patient_id), params={"limit": 100}
        )
    )


def _read_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, CARE_OPS))


class TestRedFlagDetectionThresholds:
    """The finding-detection table's numeric boundaries and its dedupe-on-code rule."""

    def test_severe_loss_finding_fires_at_exactly_71_db(self):
        """If `pure_tone_avg_db` is at least 71.0 — the boundary itself counts as severe — it
        emits `SEVERE_LOSS_THRESHOLD`, mandatory, weight 0.0.

        If the mandatory count is greater than zero, the outcome is `RED_FLAG`.

        A freshly registered patient's `status` is `REGISTERED`, `candidacy_risk_score` is 0
        (PRD §3.1, §3.2)

        Design: Corner/calculations/calc_red_flag_severe_loss_at_threshold_71_is_inclusive
        """
        patient, session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=71.0,
            asymmetry_db=0.0,
            self_reported_difficulty_score=0,
            speech_in_noise_pct=100.0,
            symptom_codes=[],
        )
        data = validate_success(resp, 200)
        assert data["status"] == "SCORED", f"status should be SCORED, got {data['status']}"
        assert data["screening_outcome"] == "RED_FLAG", (
            f"screening_outcome should be RED_FLAG at 71.0 dB, got {data['screening_outcome']}"
        )

        findings = _findings(session["id"], patient["id"])
        assert len(findings) == 1, f"exactly 1 finding expected, got {len(findings)}: {findings}"
        assert findings[0]["code"] == "SEVERE_LOSS_THRESHOLD", (
            f"finding code should be SEVERE_LOSS_THRESHOLD, got {findings[0]['code']}"
        )
        assert findings[0]["severity"] == "MANDATORY_REFERRAL", (
            f"severity should be MANDATORY_REFERRAL, got {findings[0]['severity']}"
        )
        assert findings[0]["weight"] == pytest.approx(0.0, abs=1e-6), (
            f"weight should be 0.0, got {findings[0]['weight']}"
        )

        pat = _read_patient(patient["id"])
        assert pat["status"] == "REFERRAL_REQUIRED", (
            f"patient status should be REFERRAL_REQUIRED, got {pat['status']}"
        )
        assert pat["open_mandatory_flag_count"] == 1, (
            f"open_mandatory_flag_count should be 1, got {pat['open_mandatory_flag_count']}"
        )
        assert pat["advisory_weight_total"] == pytest.approx(0.0, abs=1e-6), (
            f"advisory_weight_total should be 0.0, got {pat['advisory_weight_total']}"
        )
        assert pat["candidacy_risk_score"] == pytest.approx(0, abs=1e-6), (
            "candidacy_risk_score should stay 0 because no candidacy approval ran, got "
            f"{pat['candidacy_risk_score']}"
        )

    def test_severe_loss_finding_silent_just_below_71_db(self):
        """If `pure_tone_avg_db` is at least 71.0 — the boundary itself counts as severe — it
        emits `SEVERE_LOSS_THRESHOLD`, mandatory, weight 0.0.

        Otherwise, with an empty finding set, the outcome is `PASS`.

        The weighted base is 100 multiplied by the sum of 0.40 times the pure-tone term, 0.25
        times the difficulty term, 0.20 times the speech-in-noise term and 0.15 times the
        asymmetry term. ... the score is that base rounded half up to one decimal place

        The `candidacy_risk_band` is `LOW` when the score is strictly below 35.0 (PRD §3.2)

        Design: Corner/calculations/calc_red_flag_severe_loss_just_below_threshold_70_9
        """
        patient, session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=70.9,
            asymmetry_db=0.0,
            self_reported_difficulty_score=0,
            speech_in_noise_pct=100.0,
            symptom_codes=[],
        )
        data = validate_success(resp, 200)
        assert data["screening_outcome"] == "PASS", (
            f"screening_outcome should be PASS at 70.9 dB, got {data['screening_outcome']}"
        )
        assert _findings(session["id"], patient["id"]) == [], (
            "no finding may be emitted at 70.9 dB"
        )

        pat = _read_patient(patient["id"])
        assert pat["status"] == "CANDIDATE_APPROVED", (
            f"patient status should be CANDIDATE_APPROVED, got {pat['status']}"
        )
        assert pat["candidacy_risk_score"] == pytest.approx(31.5, abs=1e-6), (
            f"candidacy_risk_score should be 31.5, got {pat['candidacy_risk_score']}"
        )
        assert pat["candidacy_risk_band"] == "LOW", (
            f"candidacy_risk_band should be LOW at 31.5, got {pat['candidacy_risk_band']}"
        )
        assert pat["candidacy_risk_variant"] == "PROVISIONAL_SELF_REPORTED", (
            "candidacy_risk_variant should be PROVISIONAL_SELF_REPORTED, got "
            f"{pat['candidacy_risk_variant']}"
        )

    def test_asymmetry_finding_fires_at_exactly_15_db(self):
        """Finally, if `asymmetry_db` is at least 15.0 — again inclusive — it emits
        `SUDDEN_UNILATERAL_LOSS`, mandatory, weight 0.0

        If the mandatory count is greater than zero, the outcome is `RED_FLAG`. (PRD §3.2)

        Design: Corner/calculations/calc_red_flag_asymmetry_at_threshold_15_is_inclusive
        """
        patient, session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=40.0,
            asymmetry_db=15.0,
            self_reported_difficulty_score=20,
            speech_in_noise_pct=70.0,
            symptom_codes=[],
        )
        data = validate_success(resp, 200)
        assert data["screening_outcome"] == "RED_FLAG", (
            f"screening_outcome should be RED_FLAG at 15.0 dB asymmetry, got "
            f"{data['screening_outcome']}"
        )

        findings = _findings(session["id"], patient["id"])
        assert len(findings) == 1, f"exactly 1 finding expected, got {len(findings)}: {findings}"
        assert findings[0]["code"] == "SUDDEN_UNILATERAL_LOSS", (
            f"finding code should be SUDDEN_UNILATERAL_LOSS, got {findings[0]['code']}"
        )
        advisory = [f for f in findings if f["severity"] == "ADVISORY"]
        assert advisory == [], f"no advisory finding expected, got {advisory}"

        pat = _read_patient(patient["id"])
        assert pat["open_mandatory_flag_count"] == 1, (
            f"open_mandatory_flag_count should be 1, got {pat['open_mandatory_flag_count']}"
        )

    def test_asymmetry_finding_silent_just_below_15_db(self):
        """Finally, if `asymmetry_db` is at least 15.0 — again inclusive — it emits
        `SUDDEN_UNILATERAL_LOSS`, mandatory, weight 0.0

        The asymmetry term is `asymmetry_db` divided by 25, capped at 1.0. The weighted base is
        100 multiplied by the sum of 0.40 times the pure-tone term, 0.25 times the difficulty
        term, 0.20 times the speech-in-noise term and 0.15 times the asymmetry term.

        `MODERATE` when it is at least 35.0 and strictly below 65.0 (PRD §3.2)

        Design: Corner/calculations/calc_red_flag_asymmetry_just_below_threshold_14_9
        """
        patient, session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=40.0,
            asymmetry_db=14.9,
            self_reported_difficulty_score=20,
            speech_in_noise_pct=70.0,
            symptom_codes=[],
        )
        data = validate_success(resp, 200)
        assert data["screening_outcome"] == "PASS", (
            f"screening_outcome should be PASS at 14.9 dB asymmetry, got "
            f"{data['screening_outcome']}"
        )
        assert _findings(session["id"], patient["id"]) == [], (
            "no finding may be emitted at 14.9 dB asymmetry"
        )

        pat = _read_patient(patient["id"])
        assert pat["status"] == "CANDIDATE_APPROVED", (
            f"patient status should be CANDIDATE_APPROVED, got {pat['status']}"
        )
        assert pat["candidacy_risk_score"] == pytest.approx(45.2, abs=1e-6), (
            f"candidacy_risk_score should be 45.2, got {pat['candidacy_risk_score']}"
        )
        assert pat["candidacy_risk_band"] == "MODERATE", (
            f"candidacy_risk_band should be MODERATE at 45.2, got {pat['candidacy_risk_band']}"
        )

    def test_advisory_weight_sum_of_exactly_2_5_is_a_red_flag(self):
        """A declared pain symptom emits `EAR_PAIN` at severity `ADVISORY` with weight 1.5. A
        declared one-ear tinnitus symptom emits `UNILATERAL_TINNITUS`, advisory, weight 1.0.

        Otherwise, if the advisory sum is at least 2.5 — the threshold is inclusive, so a pain
        finding plus a wax finding, totalling 2.5, is a red flag — the outcome is also
        `RED_FLAG`. (PRD §3.2)

        Design: Corner/calculations/calc_red_flag_advisory_sum_at_2_5_is_inclusive_red_flag
        """
        patient, session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=40.0,
            asymmetry_db=5.0,
            self_reported_difficulty_score=20,
            speech_in_noise_pct=70.0,
            symptom_codes=["PAIN", "TINNITUS_ONE_EAR"],
        )
        data = validate_success(resp, 200)
        assert data["screening_outcome"] == "RED_FLAG", (
            "screening_outcome should be RED_FLAG when the advisory sum is exactly 2.5, got "
            f"{data['screening_outcome']}"
        )

        findings = _findings(session["id"], patient["id"])
        advisory = [f for f in findings if f["severity"] == "ADVISORY"]
        mandatory = [f for f in findings if f["severity"] == "MANDATORY_REFERRAL"]
        assert len(advisory) == 2, f"2 advisory findings expected, got {len(advisory)}: {findings}"
        assert len(mandatory) == 0, f"no mandatory finding expected, got {mandatory}"
        weights = {f["code"]: f["weight"] for f in advisory}
        assert weights.get("EAR_PAIN") == pytest.approx(1.5, abs=1e-6), (
            f"EAR_PAIN weight should be 1.5, got {weights.get('EAR_PAIN')}"
        )
        assert weights.get("UNILATERAL_TINNITUS") == pytest.approx(1.0, abs=1e-6), (
            f"UNILATERAL_TINNITUS weight should be 1.0, got {weights.get('UNILATERAL_TINNITUS')}"
        )

        pat = _read_patient(patient["id"])
        assert pat["status"] == "REFERRAL_REQUIRED", (
            f"patient status should be REFERRAL_REQUIRED, got {pat['status']}"
        )
        assert pat["advisory_weight_total"] == pytest.approx(2.5, abs=1e-6), (
            f"advisory_weight_total should be 2.5, got {pat['advisory_weight_total']}"
        )
        assert pat["open_mandatory_flag_count"] == 0, (
            f"open_mandatory_flag_count should be 0, got {pat['open_mandatory_flag_count']}"
        )

    def test_advisory_weight_sum_of_2_0_is_only_an_advisory_pass(self):
        """A declared one-ear tinnitus symptom emits `UNILATERAL_TINNITUS`, advisory, weight 1.0.
        A declared wax symptom emits `IMPACTED_CERUMEN`, advisory, weight 1.0.

        Otherwise, if the advisory sum is greater than zero, the outcome is `ADVISORY_PASS`.

        Under the provisional variant — written by a screening submit that approved candidacy,
        before any provider has examined the patient — the score is that base rounded half up to
        one decimal place, with red-flag evidence excluded entirely and no attenuation applied.
        (PRD §3.2)

        Design: Corner/calculations/calc_red_flag_advisory_sum_2_0_is_only_advisory_pass
        """
        patient, session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=40.0,
            asymmetry_db=5.0,
            self_reported_difficulty_score=20,
            speech_in_noise_pct=70.0,
            symptom_codes=["WAX", "TINNITUS_ONE_EAR"],
        )
        data = validate_success(resp, 200)
        assert data["screening_outcome"] == "ADVISORY_PASS", (
            "screening_outcome should be ADVISORY_PASS when the advisory sum is 2.0, got "
            f"{data['screening_outcome']}"
        )
        findings = _findings(session["id"], patient["id"])
        assert len(findings) == 2, f"2 findings expected, got {len(findings)}: {findings}"

        pat = _read_patient(patient["id"])
        assert pat["status"] == "CANDIDATE_APPROVED", (
            f"patient status should be CANDIDATE_APPROVED, got {pat['status']}"
        )
        assert pat["advisory_weight_total"] == pytest.approx(2.0, abs=1e-6), (
            f"advisory_weight_total should be 2.0, got {pat['advisory_weight_total']}"
        )
        assert pat["open_mandatory_flag_count"] == 0, (
            f"open_mandatory_flag_count should be 0, got {pat['open_mandatory_flag_count']}"
        )
        assert pat["candidacy_risk_score"] == pytest.approx(39.3, abs=1e-6), (
            "candidacy_risk_score should be 39.3 with advisory evidence excluded, got "
            f"{pat['candidacy_risk_score']}"
        )

        referrals = get_success_data(
            api_client.list_provider_referrals(CARE_OPS, params={"patient_id": patient["id"]})
        )
        assert referrals == [], f"an ADVISORY_PASS must open no referral, got {referrals}"

    def test_sudden_loss_symptom_and_asymmetry_emit_one_deduplicated_finding(self):
        """A declared symptom of sudden loss emits `SUDDEN_UNILATERAL_LOSS` at severity
        `MANDATORY_REFERRAL` with weight 0.0. ... when both the sudden-loss symptom and the
        asymmetry threshold are present, exactly one finding with that code is emitted, not two,
        because findings are deduplicated on `code`. (PRD §3.2)

        Design: Corner/calculations/calc_red_flag_dedupe_on_code_emits_one_sudden_loss_finding
        """
        patient, session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=40.0,
            asymmetry_db=20.0,
            self_reported_difficulty_score=20,
            speech_in_noise_pct=70.0,
            symptom_codes=["SUDDEN_LOSS"],
        )
        data = validate_success(resp, 200)
        assert data["screening_outcome"] == "RED_FLAG", (
            f"screening_outcome should be RED_FLAG, got {data['screening_outcome']}"
        )

        findings = _findings(session["id"], patient["id"])
        assert len(findings) == 1, (
            f"exactly 1 deduplicated finding expected, got {len(findings)}: {findings}"
        )
        sudden = [f for f in findings if f["code"] == "SUDDEN_UNILATERAL_LOSS"]
        assert len(sudden) == 1, f"exactly 1 SUDDEN_UNILATERAL_LOSS expected, got {len(sudden)}"

        by_session = get_success_data(
            api_client.list_red_flag_findings(
                CARE_OPS, params={"screening_session_id": session["id"], "limit": 100}
            )
        )
        assert len(by_session) == 1, (
            f"the session must own exactly 1 finding, got {len(by_session)}: {by_session}"
        )

        pat = _read_patient(patient["id"])
        assert pat["open_mandatory_flag_count"] == 1, (
            f"open_mandatory_flag_count should be 1 and not 2, got "
            f"{pat['open_mandatory_flag_count']}"
        )

    def test_age_below_policy_minimum_emits_mandatory_finding(self):
        """Then, if the patient's `age_years` is strictly below the policy's `min_age_years`, the
        table emits `AGE_BELOW_MINIMUM`, mandatory, weight 0.0.

        computing `expires_at` as `issued_at` plus the patient's policy `referral_validity_days`
        days (PRD §3.2, §3.3)

        Design: Corner/calculations/calc_red_flag_age_below_state_minimum_emits_mandatory_finding
        """
        patient, session, resp = _submit_screening(
            policy_overrides={
                "state_code": "TX",
                "min_age_years": 65,
                "trial_period_days": 30,
                "referral_validity_days": 90,
            },
            patient_overrides={"age_years": 64},
            **_MILD_PROFILE,
        )
        data = validate_success(resp, 200)
        assert data["screening_outcome"] == "RED_FLAG", (
            f"screening_outcome should be RED_FLAG for an under-age patient, got "
            f"{data['screening_outcome']}"
        )

        findings = _findings(session["id"], patient["id"])
        assert len(findings) == 1, f"exactly 1 finding expected, got {len(findings)}: {findings}"
        assert findings[0]["code"] == "AGE_BELOW_MINIMUM", (
            f"finding code should be AGE_BELOW_MINIMUM, got {findings[0]['code']}"
        )
        assert findings[0]["severity"] == "MANDATORY_REFERRAL", (
            f"severity should be MANDATORY_REFERRAL, got {findings[0]['severity']}"
        )

        pat = _read_patient(patient["id"])
        assert pat["status"] == "REFERRAL_REQUIRED", (
            f"patient status should be REFERRAL_REQUIRED, got {pat['status']}"
        )
        assert pat["state_code"] == "TX", (
            f"denormalized state_code should be TX, got {pat['state_code']}"
        )

        referrals = get_success_data(
            api_client.list_provider_referrals(CARE_OPS, params={"patient_id": patient["id"]})
        )
        assert len(referrals) == 1, f"exactly 1 referral expected, got {len(referrals)}"
        _assert_instant(
            referrals[0]["expires_at"],
            "2026-10-30T00:00:00Z",
            "referral expires_at (issued 2026-08-01 plus referral_validity_days 90)",
        )


class TestCandidacyScoring:
    """Band edges, variant divergence and the input set that feeds the composite."""

    def test_candidacy_band_is_high_at_exactly_65_0(self):
        """The pure-tone term is `pure_tone_avg_db` divided by 90, capped at 1.0. The difficulty
        term is `self_reported_difficulty_score` divided by 40. The speech-in-noise term is 1.0
        minus `speech_in_noise_pct` divided by 100 ... The asymmetry term is `asymmetry_db` divided
        by 25, capped at 1.0. The weighted base is 100 multiplied by the sum of 0.40 times the
        pure-tone term, 0.25 times the difficulty term, 0.20 times the speech-in-noise term and
        0.15 times the asymmetry term.

        and `HIGH` when it is at least 65.0. (PRD §3.2)

        Design: Corner/calculations/calc_candidacy_band_high_at_exactly_65_0_inclusive
        """
        patient, _session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=67.5,
            asymmetry_db=0.0,
            self_reported_difficulty_score=40,
            speech_in_noise_pct=50.0,
            symptom_codes=[],
        )
        data = validate_success(resp, 200)
        assert data["screening_outcome"] == "PASS", (
            f"screening_outcome should be PASS, got {data['screening_outcome']}"
        )

        pat = _read_patient(patient["id"])
        assert pat["candidacy_risk_score"] == pytest.approx(65.0, abs=1e-6), (
            f"candidacy_risk_score should be 65.0, got {pat['candidacy_risk_score']}"
        )
        assert pat["candidacy_risk_band"] == "HIGH", (
            f"candidacy_risk_band should be HIGH at exactly 65.0, got {pat['candidacy_risk_band']}"
        )
        assert pat["status"] == "CANDIDATE_APPROVED", (
            f"patient status should be CANDIDATE_APPROVED, got {pat['status']}"
        )

    def test_candidacy_band_is_moderate_just_below_65(self):
        """`MODERATE` when it is at least 35.0 and strictly below 65.0, and `HIGH` when it is at
        least 65.0.

        Rounding happens exactly once, at the end, and never to an intermediate term. (PRD §3.2)

        Design: Corner/calculations/calc_candidacy_band_moderate_just_below_65
        """
        patient, _session, resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=67.5,
            asymmetry_db=0.0,
            self_reported_difficulty_score=40,
            speech_in_noise_pct=50.5,
            symptom_codes=[],
        )
        validate_success(resp, 200)

        pat = _read_patient(patient["id"])
        assert pat["candidacy_risk_score"] == pytest.approx(64.9, abs=1e-6), (
            f"candidacy_risk_score should be 64.9, got {pat['candidacy_risk_score']}"
        )
        assert pat["candidacy_risk_band"] == "MODERATE", (
            f"candidacy_risk_band should be MODERATE at 64.9, got {pat['candidacy_risk_band']}"
        )

    def test_provider_adjusted_score_diverges_from_provisional_on_same_measurements(self):
        """Under the provider-adjusted variant — written by a licensed clearance — the base is
        first attenuated to 85 percent of itself, then increased by 6.0 points for each mandatory
        finding the clearing referral retired and by 2.0 points for each unit of the patient's
        `advisory_weight_total` as observed when the referral was issued; the resulting figure is
        capped at 100.0 and then rounded half up to one decimal place. ... Identical screening
        measurements therefore yield a different score under the two variants, which is intended.

        it stamps `cleared_by_referral_id` on every still-open finding whose `code` appears in the
        referral's `reason_codes`, increments the referral's `cleared_finding_count` accordingly,
        recomputes the patient's `open_mandatory_flag_count` (which should now be zero) ...
        recomputes `candidacy_risk_score` under the `PROVIDER_ADJUSTED` variant and sets
        `candidacy_risk_variant` to `PROVIDER_ADJUSTED`, moves the patient `REFERRAL_REQUIRED →
        PROVIDER_CLEARED` (PRD §3.2, §3.3)

        Design: Corner/calculations/calc_candidacy_provider_adjusted_variant_diverges_from_provisional
        """
        env = setup_evaluated_referral(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            provider_overrides={"licensed_state_codes": ["CA"]},
            symptom_codes=("SUDDEN_LOSS",),
            measurements={
                "pure_tone_avg_db": 40.0,
                "asymmetry_db": 5.0,
                "self_reported_difficulty_score": 20,
                "speech_in_noise_pct": 70.0,
            },
        )
        provider_headers = make_licensed_audiologist_headers(env["provider"]["id"])
        resp = api_client.record_referral_determination(
            env["referral"]["id"],
            {"clearance_outcome": "CLEARED", "clearance_note": "no pathology found"},
            provider_headers,
        )
        referral = validate_success(resp, 200)
        assert referral["clearance_outcome"] == "CLEARED", (
            f"clearance_outcome should be CLEARED, got {referral['clearance_outcome']}"
        )
        assert referral["cleared_finding_count"] == 1, (
            f"cleared_finding_count should be 1, got {referral['cleared_finding_count']}"
        )

        pat = _read_patient(env["patient"]["id"])
        assert pat["status"] == "PROVIDER_CLEARED", (
            f"patient status should be PROVIDER_CLEARED, got {pat['status']}"
        )
        assert pat["candidacy_risk_variant"] == "PROVIDER_ADJUSTED", (
            f"candidacy_risk_variant should be PROVIDER_ADJUSTED, got "
            f"{pat['candidacy_risk_variant']}"
        )
        assert pat["candidacy_risk_score"] == pytest.approx(39.4, abs=1e-6), (
            "candidacy_risk_score should be 39.4 under the provider-adjusted variant (the "
            f"provisional variant on the same measurements gives 39.3), got "
            f"{pat['candidacy_risk_score']}"
        )
        assert pat["candidacy_risk_band"] == "MODERATE", (
            f"candidacy_risk_band should be MODERATE, got {pat['candidacy_risk_band']}"
        )
        assert pat["open_mandatory_flag_count"] == 0, (
            f"open_mandatory_flag_count should be 0 after clearance, got "
            f"{pat['open_mandatory_flag_count']}"
        )

        cleared = get_success_data(
            api_client.list_red_flag_findings(
                CARE_OPS, params={"cleared_by_referral_id": env["referral"]["id"], "limit": 100}
            )
        )
        assert len(cleared) == 1, (
            f"exactly 1 finding should carry the clearing referral, got {len(cleared)}: {cleared}"
        )

    def test_candidacy_score_ignores_the_superseded_screening(self):
        """Candidacy risk is a weighted composite of the patient's latest non-invalidated screening
        — specifically the session with `status` `SCORED` ordered by `scored_at` descending with
        `created_at` descending as the tie-break, with `INVALIDATED` sessions excluded entirely.

        A `SCORED` session becomes `INVALIDATED` when a newer session names it through
        `supersedes_session_id` ... with `invalidated_reason` set to `SUPERSEDED`

        In general, a session's `attempt_ordinal` is one more than the number of prior sessions for
        the same `patient_id` ordered by `created_at` ascending (PRD §3.2)

        Design: Corner/calculations/calc_candidacy_input_set_excludes_invalidated_sessions
        """
        patient, first_session, first_resp = _submit_screening(
            policy_overrides={"state_code": "CA", "min_age_years": 18},
            patient_overrides={"age_years": 70},
            pure_tone_avg_db=40.0,
            asymmetry_db=5.0,
            self_reported_difficulty_score=20,
            speech_in_noise_pct=70.0,
            symptom_codes=[],
        )
        validate_success(first_resp, 200)

        headers = make_patient_headers(patient["id"])
        retake = get_success_data(
            api_client.start_screening_session(
                patient["id"], {"supersedes_session_id": first_session["id"]}, headers
            )
        )
        get_success_data(
            api_client.update_screening_session(
                retake["id"],
                screening_measurements_payload(
                    pure_tone_avg_db=67.5,
                    asymmetry_db=0.0,
                    self_reported_difficulty_score=40,
                    speech_in_noise_pct=50.0,
                    symptom_codes=[],
                ),
                headers,
            )
        )
        data = validate_success(api_client.submit_screening_session(retake["id"], headers), 200)
        assert data["attempt_ordinal"] == 2, (
            f"the retake's attempt_ordinal should be 2, got {data['attempt_ordinal']}"
        )
        assert data["screening_outcome"] == "PASS", (
            f"screening_outcome should be PASS, got {data['screening_outcome']}"
        )

        old = get_success_data(api_client.get_screening_session(first_session["id"], headers))
        assert old["status"] == "INVALIDATED", (
            f"the superseded session should be INVALIDATED, got {old['status']}"
        )
        assert old["invalidated_reason"] == "SUPERSEDED", (
            f"invalidated_reason should be SUPERSEDED, got {old['invalidated_reason']}"
        )

        pat = _read_patient(patient["id"])
        assert pat["candidacy_risk_score"] == pytest.approx(65.0, abs=1e-6), (
            "candidacy_risk_score should be the retake's 65.0, not the superseded 39.3, got "
            f"{pat['candidacy_risk_score']}"
        )
        assert pat["candidacy_risk_band"] == "HIGH", (
            f"candidacy_risk_band should be HIGH, got {pat['candidacy_risk_band']}"
        )
        assert pat["screening_attempt_count"] == 2, (
            f"screening_attempt_count should be 2, got {pat['screening_attempt_count']}"
        )


class TestOrderTotalComposition:
    """Sales tax is levied on the merchandise base only, and rounded exactly once."""

    def test_order_tax_excludes_shipping_from_the_taxable_base(self):
        """The device subtotal is `list_price_cents` minus `discount_cents`. The taxable base is
        that subtotal plus `accessory_subtotal_cents`; shipping is deliberately not taxable.
        `tax_cents` is the taxable base multiplied by the sales-tax rate of 0.0725 (7.25 percent),
        rounded half up — this is the single rounding in the whole composition. `total_cents` is the
        device subtotal plus `accessory_subtotal_cents` plus `shipping_cents` plus `tax_cents`. All
        four cash counters — `captured_cents`, `refunded_cents`, `retained_cents` and
        `open_balance_cents` — start at 0, and no other order's figures participate. (PRD §3.5)

        Design: Corner/calculations/calc_order_total_composition_excludes_shipping_from_tax
        """
        set_clock(CLOCK_START_UTC)
        policy = create_state_policy(state_code="CA", min_age_years=18)
        patient = register_patient(policy["id"], age_years=70)
        headers = make_patient_headers(patient["id"])
        session = get_success_data(api_client.start_screening_session(patient["id"], {}, headers))
        get_success_data(
            api_client.update_screening_session(
                session["id"], screening_measurements_payload(**_MILD_PROFILE), headers
            )
        )
        get_success_data(api_client.submit_screening_session(session["id"], headers))

        resp = api_client.create_device_order(
            patient["id"],
            {
                "model": "NEO",
                "dome_size": "M",
                "tip_type": "OPEN",
                "list_price_cents": 200000,
                "discount_cents": 0,
                "accessory_subtotal_cents": 0,
                "shipping_cents": 1495,
            },
            headers,
        )
        order = validate_success(resp, 201)
        assert order["tax_cents"] == 14500, (
            f"tax_cents should be 14500 on a 200000 taxable base, got {order['tax_cents']}"
        )
        assert order["total_cents"] == 215995, (
            f"total_cents should be 215995, got {order['total_cents']}"
        )
        assert order["captured_cents"] == 0, (
            f"captured_cents should be 0, got {order['captured_cents']}"
        )
        assert order["refunded_cents"] == 0, (
            f"refunded_cents should be 0, got {order['refunded_cents']}"
        )
        assert order["retained_cents"] == 0, (
            f"retained_cents should be 0, got {order['retained_cents']}"
        )
        assert order["open_balance_cents"] == 0, (
            f"open_balance_cents should be 0, got {order['open_balance_cents']}"
        )

    def test_order_tax_is_rounded_once_over_the_combined_base(self):
        """The taxable base is that subtotal plus `accessory_subtotal_cents`; shipping is
        deliberately not taxable. `tax_cents` is the taxable base multiplied by the sales-tax rate
        of 0.0725 (7.25 percent), rounded half up — this is the single rounding in the whole
        composition. `total_cents` is the device subtotal plus `accessory_subtotal_cents` plus
        `shipping_cents` plus `tax_cents`. (PRD §3.5)

        Design: Corner/calculations/calc_order_total_single_rounding_on_tax_only
        """
        set_clock(CLOCK_START_UTC)
        policy = create_state_policy(state_code="CA", min_age_years=18)
        patient = register_patient(policy["id"], age_years=70)
        headers = make_patient_headers(patient["id"])
        session = get_success_data(api_client.start_screening_session(patient["id"], {}, headers))
        get_success_data(
            api_client.update_screening_session(
                session["id"], screening_measurements_payload(**_MILD_PROFILE), headers
            )
        )
        get_success_data(api_client.submit_screening_session(session["id"], headers))

        resp = api_client.create_device_order(
            patient["id"],
            {
                "model": "NEO",
                "dome_size": "M",
                "tip_type": "OPEN",
                "list_price_cents": 100035,
                "discount_cents": 0,
                "accessory_subtotal_cents": 40035,
                "shipping_cents": 1495,
            },
            headers,
        )
        order = validate_success(resp, 201)
        assert order["tax_cents"] == 10155, (
            "tax_cents should be 10155 from a single rounding of the combined 140070 base "
            f"(per-component rounding would give 10156), got {order['tax_cents']}"
        )
        assert order["total_cents"] == 151720, (
            f"total_cents should be 151720, got {order['total_cents']}"
        )
        assert order["open_balance_cents"] == 0, (
            f"open_balance_cents should be 0, got {order['open_balance_cents']}"
        )


class TestTrialDayCounting:
    """Whole 24-hour blocks, and pause intervals that touch at their endpoints."""

    def test_trial_day_counter_flips_at_exactly_86400_seconds(self):
        """`paused_days` is the total merged paused duration in seconds divided by 86,400 seconds
        (24 hours) and floored. Elapsed days are the counting-window end minus `started_at`, in
        seconds, divided by 86,400 and floored, so a span of exactly 86,400 seconds counts as one
        day while 86,399 counts as zero. `days_used` is the elapsed days minus `paused_days`,
        floored at 0. And `effective_end_utc` — the deadline that actually gates a return — is
        `nominal_end_utc` plus `paused_days` days plus `extension_days_granted` days.

        A `TrialPeriod` is created with ... `status` `ACTIVE`, `started_at` equal to the order's
        `delivered_at`, `nominal_end_utc` equal to `started_at` plus the order's
        `pinned_trial_days` days (PRD §3.6)

        Design: Corner/calculations/calc_trial_days_used_86400_second_boundary
        """
        env = setup_delivered_order(
            policy_overrides={"state_code": "CA", "min_age_years": 18, "trial_period_days": 45},
            patient_overrides={"age_years": 70},
            measurements=dict(_MILD_PROFILE),
            order_overrides=dict(_PLAIN_ORDER),
        )
        patient_headers = make_patient_headers(env["patient"]["id"])

        set_clock("2026-08-01T23:59:59Z")
        almost = validate_success(
            api_client.get_trial_period(env["trial"]["id"], patient_headers), 200
        )
        assert almost["days_used"] == 0, (
            f"days_used should still be 0 after 86399 seconds, got {almost['days_used']}"
        )

        set_clock("2026-08-02T00:00:00Z")
        data = validate_success(
            api_client.get_trial_period(env["trial"]["id"], patient_headers), 200
        )
        assert data["days_used"] == 1, (
            f"days_used should be 1 at exactly 86400 seconds, got {data['days_used']}"
        )
        assert data["paused_days"] == 0, (
            f"paused_days should be 0, got {data['paused_days']}"
        )
        _assert_instant(data["started_at"], "2026-08-01T00:00:00Z", "trial started_at")
        _assert_instant(
            data["nominal_end_utc"],
            "2026-09-15T00:00:00Z",
            "nominal_end_utc (started_at plus pinned_trial_days 45)",
        )
        _assert_instant(data["effective_end_utc"], "2026-09-15T00:00:00Z", "effective_end_utc")
        assert data["status"] == "ACTIVE", f"trial status should be ACTIVE, got {data['status']}"

    def test_touching_pause_intervals_merge_instead_of_double_counting(self):
        """Intervals are sorted by `pause_start_utc` ascending with their insertion order in the
        array as the tie-break, then merged: when the next interval's start is at or before the
        running interval's end, the two merge and the running end becomes the later of the two ends
        — touching endpoints therefore merge rather than double-count.

        No second pause may be opened while one is still open — the open pause blocks it, rejected
        with `ERR_PAUSE_INTERVAL_OVERLAP` — while intervals that merely touch at their endpoints are
        legitimate.

        receipt stamps `received_at` (which starts the SLA clock) ... and when `pauses_trial` is
        true drives the trial `ACTIVE → PAUSED`

        `sla_days` is 5 when a plan is linked whose `plan_tier` is `PREMIUM`, 10 when the linked
        plan's tier is `STANDARD`, and 15 when there is no plan at all. (PRD §3.6, §3.7)

        Design: Corner/calculations/calc_trial_pause_touching_intervals_merge_into_one
        """
        env = setup_delivered_order(
            policy_overrides={"state_code": "CA", "min_age_years": 18, "trial_period_days": 45},
            patient_overrides={"age_years": 70},
            measurements=dict(_MILD_PROFILE),
            order_overrides=dict(_PLAIN_ORDER),
        )
        patient_headers = make_patient_headers(env["patient"]["id"])

        set_clock("2026-08-05T00:00:00Z")
        first = open_repair_order(env, fault_code="INTERMITTENT")
        get_success_data(api_client.send_repair_kit(first["id"], CARE_OPS))
        get_success_data(api_client.receive_repair_order(first["id"], REPAIR_TECH))

        set_clock("2026-08-08T00:00:00Z")
        get_success_data(api_client.start_repair_order(first["id"], REPAIR_TECH))
        get_success_data(
            api_client.resolve_repair_order(first["id"], {"resolution": "REPAIRED"}, REPAIR_TECH)
        )
        get_success_data(api_client.return_repair_to_patient(first["id"], REPAIR_TECH))

        second = open_repair_order(env, fault_code="BATTERY")
        get_success_data(api_client.send_repair_kit(second["id"], CARE_OPS))

        resp = api_client.receive_repair_order(second["id"], REPAIR_TECH)
        repair = validate_success(resp, 200)
        assert repair["status"] == "RECEIVED", (
            "a pause opening at the instant the previous pause closed must be accepted, got "
            f"status {repair['status']}"
        )
        _assert_instant(repair["received_at"], "2026-08-08T00:00:00Z", "repair received_at")
        assert repair["sla_days"] == 15, (
            f"sla_days should be 15 with no care plan attached, got {repair['sla_days']}"
        )

        paused = validate_success(
            api_client.get_trial_period(env["trial"]["id"], patient_headers), 200
        )
        assert paused["status"] == "PAUSED", (
            f"the trial should be PAUSED, got {paused['status']}"
        )

        set_clock("2026-08-10T00:00:00Z")
        data = validate_success(
            api_client.get_trial_period(env["trial"]["id"], patient_headers), 200
        )
        assert data["paused_days"] == 5, (
            "paused_days should be 5 because the touching intervals merge into one span, got "
            f"{data['paused_days']}"
        )
        assert data["days_used"] == 4, (
            f"days_used should be 4 (9 elapsed days minus 5 paused), got {data['days_used']}"
        )
        _assert_instant(
            data["effective_end_utc"],
            "2026-09-20T00:00:00Z",
            "effective_end_utc (nominal end plus 5 paused days)",
        )


class TestReturnRestockingSettlement:
    """The seven settlement steps: variant selection, per-component rounding, surcharge, cap."""

    def test_each_restocking_component_is_rounded_before_the_sum(self):
        """Step three computes per-component restocking, **rounding each component to the cent
        before anything is summed**. Under `FLAT_PCT`, the device portion is the device component
        multiplied by the policy's `restocking_fee_pct`, rounded half up; the accessory portion is
        the accessory component multiplied by `restocking_fee_pct` and again by an accessory factor
        of 0.5 — accessories restock at half the device rate — rounded half up.

        Summing the components first and rounding the total once is explicitly forbidden and yields
        a different number of cents. Step six sets `non_refundable_shipping_cents` to 0 when the
        pinned policy's `shipping_refundable` is true, and to the order's `shipping_cents`
        otherwise. Step seven sets `refund_amount_cents` to the order's `captured_cents` minus
        `restocking_fee_cents` minus `non_refundable_shipping_cents`, floored at 0. (PRD §3.6)

        Design: Corner/calculations/calc_return_settlement_rounds_each_component_before_summing
        """
        env = setup_return_received(
            at_iso="2026-08-11T00:00:00Z",
            policy_overrides={
                "state_code": "CA",
                "min_age_years": 18,
                "trial_period_days": 45,
                "restocking_fee_mode": "FLAT_PCT",
                "restocking_fee_pct": 0.075,
                "restocking_fee_cap_cents": 0,
                "shipping_refundable": False,
            },
            patient_overrides={"age_years": 70},
            measurements=dict(_MILD_PROFILE),
            order_overrides={
                "list_price_cents": 100033,
                "discount_cents": 0,
                "accessory_subtotal_cents": 40011,
                "shipping_cents": 1495,
            },
        )
        rma = validate_success(
            api_client.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
            ),
            200,
        )
        assert rma["status"] == "INSPECTED", f"status should be INSPECTED, got {rma['status']}"
        assert rma["restocking_variant"] == "FLAT_PCT", (
            f"restocking_variant should be FLAT_PCT, got {rma['restocking_variant']}"
        )
        assert rma["days_used_at_issue"] == 10, (
            f"days_used_at_issue should be 10, got {rma['days_used_at_issue']}"
        )
        assert rma["restocking_fee_cents"] == 9002, (
            "restocking_fee_cents should be 9002 (7502 device + 1500 accessory, each rounded "
            f"before summing; rounding the sum once would give 9003), got "
            f"{rma['restocking_fee_cents']}"
        )
        assert rma["non_refundable_shipping_cents"] == 1495, (
            f"non_refundable_shipping_cents should be 1495, got "
            f"{rma['non_refundable_shipping_cents']}"
        )
        assert rma["refund_amount_cents"] == 141195, (
            f"refund_amount_cents should be 141195, got {rma['refund_amount_cents']}"
        )

        order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS), 200)
        assert order["captured_cents"] == 151692, (
            f"captured_cents should be 151692, got {order['captured_cents']}"
        )
        assert order["tax_cents"] == 10153, (
            f"tax_cents should be 10153, got {order['tax_cents']}"
        )

    def test_prorated_daily_variant_charges_the_daily_rate_instead_of_a_percentage(self):
        """otherwise if the pinned mode is `FLAT_PCT` the variant is `FLAT_PCT`; otherwise it is
        `PRORATED_DAILY`.

        Under `PRORATED_DAILY`, the device portion is the policy's `restocking_daily_rate_cents`
        multiplied by the lesser of `days_used_at_issue` and the order's `pinned_trial_days`, and
        the accessory portion is 0. (PRD §3.6)

        Design: Corner/calculations/calc_return_settlement_prorated_daily_diverges_from_flat_pct
        """
        env = setup_return_received(
            at_iso="2026-08-11T00:00:00Z",
            policy_overrides={
                "state_code": "OR",
                "min_age_years": 18,
                "trial_period_days": 45,
                "restocking_fee_mode": "PRORATED_DAILY",
                "restocking_fee_pct": 0.0,
                "restocking_daily_rate_cents": 500,
                "restocking_fee_cap_cents": 0,
                "shipping_refundable": False,
            },
            patient_overrides={"age_years": 70},
            measurements=dict(_MILD_PROFILE),
            order_overrides=dict(_PLAIN_ORDER),
        )
        rma = validate_success(
            api_client.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
            ),
            200,
        )
        assert rma["restocking_variant"] == "PRORATED_DAILY", (
            f"restocking_variant should be PRORATED_DAILY, got {rma['restocking_variant']}"
        )
        assert rma["restocking_fee_cents"] == 5000, (
            "restocking_fee_cents should be 5000 (500 per day for min(10 days used, 45 pinned "
            f"trial days)), got {rma['restocking_fee_cents']}"
        )
        assert rma["non_refundable_shipping_cents"] == 1495, (
            f"non_refundable_shipping_cents should be 1495, got "
            f"{rma['non_refundable_shipping_cents']}"
        )
        assert rma["refund_amount_cents"] == 209500, (
            f"refund_amount_cents should be 209500, got {rma['refund_amount_cents']}"
        )

    def test_same_instant_return_is_waived_even_under_a_percentage_policy(self):
        """Step two selects the variant, testing in this order: if the pinned mode is `PROHIBITED`
        the variant is `WAIVED`; otherwise if `days_used_at_issue` is 0 the variant is `WAIVED` — a
        same-day return is never charged restocking; otherwise if the pinned mode is `FLAT_PCT` the
        variant is `FLAT_PCT`.

        Initiation creates a `ReturnAuthorization` in `ISSUED` with ... a `days_used_at_issue`
        snapshot of the trial's `days_used` at that instant, a `return_deadline_utc` of the current
        clock plus 14 days (two weeks) (PRD §3.6)

        Design: Corner/calculations/calc_return_settlement_zero_day_edge_forces_waived
        """
        env = setup_return_received(
            policy_overrides={
                "state_code": "CA",
                "min_age_years": 18,
                "trial_period_days": 45,
                "restocking_fee_mode": "FLAT_PCT",
                "restocking_fee_pct": 0.1,
                "restocking_fee_cap_cents": 0,
                "shipping_refundable": False,
            },
            patient_overrides={"age_years": 70},
            measurements=dict(_MILD_PROFILE),
            order_overrides=dict(_PLAIN_ORDER),
        )
        rma = validate_success(
            api_client.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "RESELLABLE"}, CARE_OPS
            ),
            200,
        )
        assert rma["days_used_at_issue"] == 0, (
            f"days_used_at_issue should be 0 on a same-instant return, got "
            f"{rma['days_used_at_issue']}"
        )
        assert rma["restocking_variant"] == "WAIVED", (
            "restocking_variant should be WAIVED because the zero-day test precedes the mode "
            f"test, got {rma['restocking_variant']}"
        )
        assert rma["restocking_fee_cents"] == 0, (
            f"restocking_fee_cents should be 0, got {rma['restocking_fee_cents']}"
        )
        assert rma["non_refundable_shipping_cents"] == 1495, (
            f"non_refundable_shipping_cents should be 1495, got "
            f"{rma['non_refundable_shipping_cents']}"
        )
        assert rma["refund_amount_cents"] == 214500, (
            f"refund_amount_cents should be 214500, got {rma['refund_amount_cents']}"
        )
        _assert_instant(
            rma["return_deadline_utc"],
            "2026-08-15T00:00:00Z",
            "return_deadline_utc (issue clock plus 14 days)",
        )

    def test_damage_surcharge_survives_a_prohibited_restocking_policy(self):
        """Step four adds a **third, independently rounded component**: a damage surcharge. A
        `DAMAGED` grade surcharges the device component multiplied by 0.15, rounded half up ... This
        surcharge applies **even under the `WAIVED` variant** — a state's prohibition on restocking
        fees does not shield a patient from damage they caused.

        a `RESELLABLE` grade credits the unit straight back to stock by decrementing the pool's
        `dispatched_units` and incrementing its `on_hand_units`, while a `REFURBISHABLE` or
        `DAMAGED` grade credits nothing (PRD §3.6)

        Design: Corner/calculations/calc_return_settlement_damage_surcharge_survives_prohibited_waiver
        """
        env = setup_return_received(
            at_iso="2026-08-11T00:00:00Z",
            policy_overrides={
                "state_code": "NY",
                "min_age_years": 18,
                "trial_period_days": 45,
                "restocking_fee_mode": "PROHIBITED",
                "restocking_fee_pct": 0.0,
                "restocking_fee_cap_cents": 0,
                "shipping_refundable": False,
            },
            patient_overrides={"age_years": 70},
            measurements=dict(_MILD_PROFILE),
            order_overrides=dict(_PLAIN_ORDER),
        )
        rma = validate_success(
            api_client.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "DAMAGED"}, CARE_OPS
            ),
            200,
        )
        assert rma["restocking_variant"] == "WAIVED", (
            f"restocking_variant should be WAIVED under a PROHIBITED mode, got "
            f"{rma['restocking_variant']}"
        )
        assert rma["restocking_fee_cents"] == 30000, (
            "restocking_fee_cents should be 30000 (device 0 + accessory 0 + damage surcharge "
            f"30000), got {rma['restocking_fee_cents']}"
        )
        assert rma["non_refundable_shipping_cents"] == 1495, (
            f"non_refundable_shipping_cents should be 1495, got "
            f"{rma['non_refundable_shipping_cents']}"
        )
        assert rma["refund_amount_cents"] == 184500, (
            f"refund_amount_cents should be 184500, got {rma['refund_amount_cents']}"
        )

        pool = get_pool(env["pool"]["id"])
        assert pool["on_hand_units"] == 4, (
            f"a DAMAGED grade must not credit stock back, so on_hand_units should be 4, got "
            f"{pool['on_hand_units']}"
        )
        assert pool["dispatched_units"] == 1, (
            f"dispatched_units should still be 1, got {pool['dispatched_units']}"
        )

    def test_restocking_cap_clips_the_sum_of_the_rounded_components(self):
        """Step five sums the three already-rounded components and applies the cap: when the pinned
        policy's `restocking_fee_cap_cents` is 0 the raw sum stands unchanged; otherwise
        `restocking_fee_cents` is the lesser of the raw sum and the cap. (PRD §3.6)

        Design: Corner/calculations/calc_return_settlement_cap_applies_to_sum_of_rounded_components
        """
        env = setup_return_received(
            at_iso="2026-08-11T00:00:00Z",
            policy_overrides={
                "state_code": "WA",
                "min_age_years": 18,
                "trial_period_days": 45,
                "restocking_fee_mode": "FLAT_PCT",
                "restocking_fee_pct": 0.1,
                "restocking_fee_cap_cents": 10000,
                "shipping_refundable": False,
            },
            patient_overrides={"age_years": 70},
            measurements=dict(_MILD_PROFILE),
            order_overrides=dict(_PLAIN_ORDER),
        )
        rma = validate_success(
            api_client.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "DAMAGED"}, CARE_OPS
            ),
            200,
        )
        assert rma["restocking_variant"] == "FLAT_PCT", (
            f"restocking_variant should be FLAT_PCT, got {rma['restocking_variant']}"
        )
        assert rma["restocking_fee_cents"] == 10000, (
            "restocking_fee_cents should be 10000, the lesser of the raw sum 20000 + 0 + 30000 "
            f"and the cap 10000, got {rma['restocking_fee_cents']}"
        )
        assert rma["refund_amount_cents"] == 204500, (
            f"refund_amount_cents should be 204500, got {rma['refund_amount_cents']}"
        )

    def test_refurbishable_surcharge_rate_with_refundable_shipping(self):
        """a `REFURBISHABLE` grade surcharges the device component multiplied by 0.05, rounded half
        up; a `RESELLABLE` grade surcharges nothing.

        Step six sets `non_refundable_shipping_cents` to 0 when the pinned policy's
        `shipping_refundable` is true, and to the order's `shipping_cents` otherwise. Step seven
        sets `refund_amount_cents` to the order's `captured_cents` minus `restocking_fee_cents`
        minus `non_refundable_shipping_cents`, floored at 0. (PRD §3.6)

        Design: Corner/calculations/calc_return_settlement_refurbishable_rate_with_refundable_shipping
        """
        env = setup_return_received(
            at_iso="2026-08-11T00:00:00Z",
            policy_overrides={
                "state_code": "AZ",
                "min_age_years": 18,
                "trial_period_days": 45,
                "restocking_fee_mode": "FLAT_PCT",
                "restocking_fee_pct": 0.1,
                "restocking_fee_cap_cents": 0,
                "shipping_refundable": True,
            },
            patient_overrides={"age_years": 70},
            measurements=dict(_MILD_PROFILE),
            order_overrides=dict(_PLAIN_ORDER),
        )
        rma = validate_success(
            api_client.inspect_return_authorization(
                env["rma"]["id"], {"inspection_grade": "REFURBISHABLE"}, CARE_OPS
            ),
            200,
        )
        assert rma["restocking_fee_cents"] == 30000, (
            "restocking_fee_cents should be 30000 (flat 20000 plus the 0.05 refurbishable "
            f"surcharge 10000), got {rma['restocking_fee_cents']}"
        )
        assert rma["non_refundable_shipping_cents"] == 0, (
            "non_refundable_shipping_cents should be 0 when the pinned policy refunds shipping, "
            f"got {rma['non_refundable_shipping_cents']}"
        )
        assert rma["refund_amount_cents"] == 185995, (
            f"refund_amount_cents should be 185995, got {rma['refund_amount_cents']}"
        )
