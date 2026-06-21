"""Dose-validity replay and catch-up due-date calculations.

Covers the chronological dose-validity computation (age / interval with the
four-day grace window) and the two-baseline due-date variants of the schedule
engine.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_patient_with_doses, setup_catalog_and_patient, run_evaluation,
    find_antigen_result, record_dose, api_client, make_registrar_headers,
    create_product_payload,
)

REG = make_registrar_headers()

DTAP = dict(product_code="DTAP", antigen="DTAP", doses_in_series=5,
            min_age_days=42, recommended_age_days=60, min_interval_days=28,
            grace_period_days=4)


class TestDueDateVariants:
    def test_minimum_and_recommended_due_dates_diverge_by_grace(self, api):
        """PRD §3.6: "When the valid-dose count is greater than zero, the
        next_valid_due_date is the last valid date plus min_interval_days reduced
        by the grace window, and the next_recommended_due_date is the last valid
        date plus the full min_interval_days with no grace applied."

        With one valid DTAP dose on 2026-01-01 (min_interval 28, grace 4):
        next_valid_due_date = 2026-01-01 + 24 = 2026-01-25;
        next_recommended_due_date = 2026-01-01 + 28 = 2026-01-29.

        Design: Difficulty/dual_variant_calc/due_date_minimum_vs_recommended_diverge
        """
        _, _, _, patient, _ = setup_patient_with_doses(
            dose_dates=["2026-01-01"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-11-01"},
            clock="2026-01-10T00:00:00Z")
        ev = run_evaluation(patient["id"], "2026-01-10")
        res = find_antigen_result(ev, "DTAP")
        assert res["next_valid_due_date"] == "2026-01-25", \
            f"expected graced min-interval due date, got {res['next_valid_due_date']}"
        assert res["next_recommended_due_date"] == "2026-01-29", \
            f"expected ungraced recommended due date, got {res['next_recommended_due_date']}"

    def test_due_date_variants_differ_by_exactly_grace_days(self, api):
        """PRD §3.6: "the recommended baseline uses the un-graced cadence and
        therefore always lands on the same date or later than the minimum
        baseline for identical patient data."

        The two due dates differ by exactly the grace window (4 days):
        2026-01-25 vs 2026-01-29.

        Design: Difficulty/dual_variant_calc/due_date_minimum_vs_recommended_diverge
        """
        _, _, _, patient, _ = setup_patient_with_doses(
            dose_dates=["2026-01-01"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-11-01"},
            clock="2026-01-10T00:00:00Z")
        ev = run_evaluation(patient["id"], "2026-01-10")
        res = find_antigen_result(ev, "DTAP")
        assert res["next_recommended_due_date"] == "2026-01-29"
        assert res["next_valid_due_date"] == "2026-01-25"


class TestCompletenessVsCertificateType:
    def test_conditional_evaluation_has_partial_completeness(self, api):
        """PRD §3.6: "for each mandated antigen, the per-antigen percentage is
        100 multiplied by the lesser of its valid-dose count and its required
        count, divided by its required count, and that quotient is rounded
        half-up to 2 decimal places per antigen first."

        One valid MMR dose of a 2-dose series, second not yet due ->
        completeness_pct == 50.00.

        Design: Difficulty/dual_variant_calc/completeness_pct_vs_certificate_type_diverge
        """
        prod = create_product_payload(
            product_code="MMR2", antigen="MMR", doses_in_series=2,
            min_age_days=0, recommended_age_days=0, min_interval_days=28,
            grace_period_days=4)
        _, _, _, patient, _ = setup_patient_with_doses(
            dose_dates=["2026-01-01"], product_overrides=prod,
            patient_overrides={"date_of_birth": "2025-12-01"},
            clock="2026-01-10T00:00:00Z")
        ev = run_evaluation(patient["id"], "2026-01-10")
        assert ev["completeness_pct"] == 50.00, \
            f"expected 50.00, got {ev['completeness_pct']}"

    def test_conditional_status_when_gap_not_yet_due(self, api):
        """PRD §3.6: "otherwise, if every unsatisfied antigen has a
        next_valid_due_date strictly after the as_of_date (its next dose is not
        yet due), the status is CONDITIONAL".

        The MMR second dose's next_valid_due_date (2026-01-25) is after as_of
        2026-01-10, so overall_status is CONDITIONAL even though completeness is
        below 100.

        Design: Difficulty/dual_variant_calc/completeness_pct_vs_certificate_type_diverge
        """
        prod = create_product_payload(
            product_code="MMR2", antigen="MMR", doses_in_series=2,
            min_age_days=0, recommended_age_days=0, min_interval_days=28,
            grace_period_days=4)
        _, _, _, patient, _ = setup_patient_with_doses(
            dose_dates=["2026-01-01"], product_overrides=prod,
            patient_overrides={"date_of_birth": "2025-12-01"},
            clock="2026-01-10T00:00:00Z")
        ev = run_evaluation(patient["id"], "2026-01-10")
        assert ev["overall_status"] == "CONDITIONAL", \
            f"expected CONDITIONAL, got {ev['overall_status']}"


class TestIntervalGraceBranch:
    def test_dose_at_exactly_graced_minimum_interval_is_valid(self, api):
        """PRD §2.7: "otherwise, if a prior valid date exists and the number of
        days from that prior valid date to this dose's administered_date is
        strictly less than the product's min_interval_days reduced by the grace
        window, its validity is INVALID_INTERVAL and it is not counted; otherwise
        the dose is VALID".

        Dose2 exactly 24 days (= min_interval 28 - grace 4) after dose1 is VALID
        and assigned dose_number 2.

        Design: Difficulty/combinatorial_formula/catchup_interval_max_of_age_and_interval_branch
        """
        _, provider, lot, patient, _ = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"},
            clock="2026-06-01T00:00:00Z")
        dose2 = record_dose(patient["id"], lot["id"], provider["id"],
                            "2025-03-04")
        assert dose2["validity"] == "VALID", \
            f"expected VALID at graced minimum, got {dose2['validity']}"
        assert dose2["dose_number"] == 2, \
            f"expected dose_number 2, got {dose2['dose_number']}"

    def test_dose_one_day_below_graced_minimum_rejected(self, api):
        """PRD §3.2: "a dose whose gap from the prior valid same-antigen dose is
        less than min_interval_days reduced by the grace window is refused
        outright with ERR_INTERVAL_TOO_SHORT (HTTP 422) rather than being
        recorded and merely flagged INVALID_INTERVAL."

        Dose2 at 23 days after dose1 (one short of the graced minimum of 24) is
        rejected.

        Design: Difficulty/combinatorial_formula/catchup_interval_max_of_age_and_interval_branch
        """
        product, provider, lot, patient, _ = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"},
            clock="2026-06-01T00:00:00Z")
        from test_helpers import create_immunization_payload
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-03-03"), REG)
        validate_error(resp, ApiErrorId.ERR_INTERVAL_TOO_SHORT.value)


class TestRoundPerAntigenThenAverage:
    def test_completeness_rounds_per_antigen_before_averaging(self, api):
        """PRD §3.6: "The overall completeness_pct is then the sum of those
        already-rounded per-antigen percentages divided by the number of mandated
        antigens, with that average rounded half-up to 2 decimal places."

        DTAP 2/5 -> 40.00 and MMR 0/2 -> 0.00; average (40.00 + 0.00)/2 = 20.00.

        Design: Difficulty/combinatorial_formula/completeness_round_per_antigen_then_average
        """
        from test_helpers import (
            create_provider, create_lot, create_patient, record_dose,
            set_clock,
        )
        set_clock("2026-06-01T00:00:00Z")
        dtap = get_success_data(api_client.create_product(
            create_product_payload(**DTAP), REG))
        mmr = get_success_data(api_client.create_product(
            create_product_payload(product_code="MMR", antigen="MMR",
                                   doses_in_series=2, min_age_days=0,
                                   recommended_age_days=0, min_interval_days=28,
                                   grace_period_days=4), REG))
        provider = create_provider(authorized_product_codes=["DTAP", "MMR"])
        lot = create_lot(dtap["id"])
        patient = create_patient(date_of_birth="2025-01-01")
        record_dose(patient["id"], lot["id"], provider["id"], "2025-02-08")
        record_dose(patient["id"], lot["id"], provider["id"], "2025-03-08")
        ev = run_evaluation(patient["id"], "2026-06-01")
        assert ev["completeness_pct"] == 20.00, \
            f"expected 20.00 (round-per-antigen-then-average), got {ev['completeness_pct']}"

    def test_per_antigen_percentage_capped_at_required(self, api):
        """PRD §3.6: "the per-antigen percentage is 100 multiplied by the lesser
        of its valid-dose count and its required count, divided by its required
        count, and that quotient is rounded half-up to 2 decimal places per
        antigen first."

        DTAP 2/5 contributes 40.00 and the unsatisfied MMR antigen contributes
        0.00, averaging to 20.00 — the pinned per-antigen-first order.

        Design: Difficulty/combinatorial_formula/completeness_round_per_antigen_then_average
        """
        from test_helpers import (
            create_provider, create_lot, create_patient, record_dose, set_clock,
        )
        set_clock("2026-06-01T00:00:00Z")
        dtap = get_success_data(api_client.create_product(
            create_product_payload(**DTAP), REG))
        get_success_data(api_client.create_product(
            create_product_payload(product_code="MMR", antigen="MMR",
                                   doses_in_series=2, min_age_days=0,
                                   recommended_age_days=0, min_interval_days=28,
                                   grace_period_days=4), REG))
        provider = create_provider(authorized_product_codes=["DTAP", "MMR"])
        lot = create_lot(dtap["id"])
        patient = create_patient(date_of_birth="2025-01-01")
        record_dose(patient["id"], lot["id"], provider["id"], "2025-02-08")
        record_dose(patient["id"], lot["id"], provider["id"], "2025-03-08")
        ev = run_evaluation(patient["id"], "2026-06-01")
        dtap_res = find_antigen_result(ev, "DTAP")
        assert dtap_res["valid_dose_count"] == 2
        assert ev["completeness_pct"] == 20.00
