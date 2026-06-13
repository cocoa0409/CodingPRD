"""Billing axis: forward-looking estimate vs chronological settlement, the
lifetime-cap nested min(), SUM-then-round coverage, write-off fee conservation,
and the settlement money-conservation invariant.

All literal expected values are copied verbatim from the design indices.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_billing_conservation,
    TEST_USERS,
    make_patient_headers,
)
import test_helpers.factories as f

ADMIN = TEST_USERS["clinic_admin_headers"]
NURSE = TEST_USERS["nurse_headers"]
EMBRYO = TEST_USERS["embryologist_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


def _clinic():
    return get_success_data(api_client.create_clinic(f.create_clinic_payload(), ADMIN))["id"]


def _package(cid, **kw):
    return get_success_data(api_client.create_package(cid, f.create_package_payload(**kw), ADMIN))["id"]


def _patient(cid, pkg_id=None):
    kw = {} if pkg_id is None else {"insurance_package_id": pkg_id}
    return get_success_data(api_client.create_patient(cid, f.create_patient_payload(**kw), ADMIN))["id"]


def _consent(cid, pat_id, required_for):
    form = get_success_data(
        api_client.create_consent_form(cid, f.create_consent_form_payload(required_for=required_for), ADMIN)
    )
    get_success_data(api_client.publish_consent_form(cid, form["id"], ADMIN))
    get_success_data(
        api_client.create_patient_consent(
            cid, f.create_patient_consent_payload(pat_id, form["id"]), make_patient_headers(pat_id)
        )
    )


def _cycle(cid, pat_id):
    return get_success_data(api_client.create_cycle(cid, f.create_cycle_payload(pat_id), NURSE))["id"]


# ===========================================================================
# Queue A — dual_variant_calc / cycle_estimate_vs_settlement_diverge_same_inputs
# ===========================================================================
class TestEstimateVsSettlementDivergence:
    def _build_diverging_cycle(self):
        """Recreate the dual-variant scenario: base 500000, coverage 0.8,
        stim_med_covered, two meds, two PENDING specimens at estimate; then
        admin one med / cancel the other / store+accrue one specimen, complete.
        """
        cid = _clinic()
        pkg = _package(
            cid, name="Single IVF", base_price_cents=500000, coverage_pct=0.8,
            stim_med_covered=True, cryo_storage_covered=False,
            annual_cryo_storage_cents=60000, lifetime_coverage_cap_cents=1000000,
        )
        pat = _patient(cid, pkg)
        _consent(cid, pat, ["CYCLE_START", "RETRIEVAL", "TRANSFER", "CRYO_STORE"])
        tank = get_success_data(api_client.create_tank(cid, f.create_tank_payload(label="Tank-A", capacity_slots=5), EMBRYO))
        cyc = _cycle(cid, pat)
        get_success_data(api_client.start_stim(cid, cyc, NURSE))
        medA = get_success_data(api_client.create_medication(
            cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=0,
                                              end_day_offset=4, daily_dose_units=300, unit_price_cents=100), NURSE))["id"]
        medB = get_success_data(api_client.create_medication(
            cid, f.create_medication_payload(cyc, drug_name="Menopur", start_day_offset=0,
                                              end_day_offset=2, daily_dose_units=75, unit_price_cents=200), NURSE))["id"]
        sp1 = get_success_data(api_client.create_specimen(cid, f.create_specimen_payload(cyc, tank["id"]), EMBRYO))["id"]
        get_success_data(api_client.create_specimen(cid, f.create_specimen_payload(cyc, tank["id"]), EMBRYO))
        est = get_success_data(api_client.estimate_billing(cid, cyc, BILLING))
        get_success_data(api_client.administer_medication(cid, medA, NURSE))
        get_success_data(api_client.cancel_medication(cid, medB, NURSE))
        get_success_data(api_client.retrieve(cid, cyc, {"oocytes_retrieved": 10}, NURSE))
        get_success_data(api_client.fertilize(cid, cyc, {"embryos_fertilized": 8}, EMBRYO))
        # Storing requires the cycle's protocol_status to be FERTILIZATION or FREEZE_ALL (PRD 3.7),
        # so the store + accrue must happen after fertilization and before the fresh transfer.
        get_success_data(api_client.store_specimen(cid, sp1, {"expected_tank_version": tank["version"]}, EMBRYO))
        get_success_data(api_client.accrue_storage_year(cid, sp1, EMBRYO))
        get_success_data(api_client.transfer(cid, cyc, EMBRYO))
        get_success_data(api_client.create_outcome(cid, f.create_outcome_payload(cyc, clinical_pregnancy=True), NURSE))
        get_success_data(api_client.complete_cycle(cid, cyc, NURSE))
        v = get_success_data(api_client.get_cycle(cid, cyc, BILLING))["version"]
        settled = validate_success(api_client.settle_billing(cid, cyc, {"expected_cycle_version": v}, BILLING))
        return est, settled

    def test_forward_estimate_value(self):
        """PRD 3.9: "The stimulation-medication charge is the sum of `line_total_cents`
        over every medication order on the cycle that is currently `SCHEDULED` or
        `ADMINISTERED` — that is, every order projected to be given." PRD 3.9: "The
        cryo-storage charge assumes exactly one storage-year for each specimen currently
        `PENDING` or `STORED`: it is the count of those specimens multiplied by the
        package's `annual_cryo_storage_cents`."

        Design: Difficulty/dual_variant_calc/cycle_estimate_vs_settlement_diverge_same_inputs
        """
        est, _ = self._build_diverging_cycle()
        assert est["estimated_patient_owed_cents"] == 259000, (
            f"forward-looking estimate must be 259000, got {est['estimated_patient_owed_cents']}"
        )

    def test_chronological_settlement_value_and_divergence(self):
        """PRD 3.9: "The medication charge is the sum of `line_total_cents` over only
        the orders actually `ADMINISTERED` (scheduled-but-not-administered and cancelled
        orders are excluded)." PRD 3.9: "The cryo-storage charge sums, over every specimen
        that ever reached stored ... that specimen's `storage_years_accrued` multiplied by
        the package's `annual_cryo_storage_cents`; a specimen that never left `PENDING`
        contributes nothing."

        Design: Difficulty/dual_variant_calc/cycle_estimate_vs_settlement_diverge_same_inputs
        """
        est, settled = self._build_diverging_cycle()
        assert settled["final_patient_owed_cents"] == 190000, (
            f"chronological settlement must be 190000, got {settled['final_patient_owed_cents']}"
        )
        assert est["estimated_patient_owed_cents"] != settled["final_patient_owed_cents"], (
            "estimate and settlement must diverge for the same cycle"
        )


# ===========================================================================
# Queue A — combinatorial_formula / settlement_multi_input_nested_min_and_conditional_branches
# ===========================================================================
class TestSettlementLifetimeCapBinds:
    def _build_capped_scenario(self):
        cid = _clinic()
        pkg = _package(
            cid, name="Capped IVF", base_price_cents=500000, coverage_pct=0.8,
            stim_med_covered=True, cryo_storage_covered=False,
            annual_cryo_storage_cents=60000, lifetime_coverage_cap_cents=1000000,
        )
        pat = _patient(cid, pkg)
        _consent(cid, pat, ["CYCLE_START", "RETRIEVAL", "TRANSFER"])
        # PRIOR cycle: drive insurer_paid to 980000 via one med line 725000 administered
        prior = _cycle(cid, pat)
        get_success_data(api_client.start_stim(cid, prior, NURSE))
        pm = get_success_data(api_client.create_medication(
            cid, f.create_medication_payload(prior, drug_name="Gonal-F", start_day_offset=0,
                                              end_day_offset=4, daily_dose_units=290, unit_price_cents=500), NURSE))["id"]
        get_success_data(api_client.administer_medication(cid, pm, NURSE))
        get_success_data(api_client.estimate_billing(cid, prior, BILLING))
        get_success_data(api_client.retrieve(cid, prior, {"oocytes_retrieved": 8}, NURSE))
        get_success_data(api_client.fertilize(cid, prior, {"embryos_fertilized": 4}, EMBRYO))
        get_success_data(api_client.transfer(cid, prior, EMBRYO))
        get_success_data(api_client.create_outcome(cid, f.create_outcome_payload(prior, pregnancy_test_result="NEGATIVE"), NURSE))
        get_success_data(api_client.complete_cycle(cid, prior, NURSE))
        pv = get_success_data(api_client.get_cycle(cid, prior, BILLING))["version"]
        prior_settled = validate_success(api_client.settle_billing(cid, prior, {"expected_cycle_version": pv}, BILLING))
        # SECOND cycle: one med line 150000 administered, no cryo
        cyc = _cycle(cid, pat)
        get_success_data(api_client.start_stim(cid, cyc, NURSE))
        m = get_success_data(api_client.create_medication(
            cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=0,
                                              end_day_offset=4, daily_dose_units=300, unit_price_cents=100), NURSE))["id"]
        get_success_data(api_client.administer_medication(cid, m, NURSE))
        get_success_data(api_client.estimate_billing(cid, cyc, BILLING))
        get_success_data(api_client.retrieve(cid, cyc, {"oocytes_retrieved": 9}, NURSE))
        get_success_data(api_client.fertilize(cid, cyc, {"embryos_fertilized": 5}, EMBRYO))
        get_success_data(api_client.transfer(cid, cyc, EMBRYO))
        get_success_data(api_client.create_outcome(cid, f.create_outcome_payload(cyc, live_birth=True), NURSE))
        get_success_data(api_client.complete_cycle(cid, cyc, NURSE))
        v = get_success_data(api_client.get_cycle(cid, cyc, BILLING))["version"]
        settled = validate_success(api_client.settle_billing(cid, cyc, {"expected_cycle_version": v}, BILLING))
        return prior_settled, settled

    def test_prior_insurer_paid_reaches_cap_threshold(self):
        """PRD 3.9: "The covered total is multiplied by `coverage_pct` and rounded half
        up once to whole cents to give the raw insurer amount."

        Design: Difficulty/combinatorial_formula/settlement_multi_input_nested_min_and_conditional_branches
        """
        prior_settled, _ = self._build_capped_scenario()
        assert prior_settled["insurer_paid_cents"] == 980000, (
            f"prior cycle insurer_paid must be 980000, got {prior_settled['insurer_paid_cents']}"
        )

    def test_lifetime_cap_binds_insurer_to_headroom(self):
        """PRD 3.9: "the system computes the prior insurer-paid total as the sum of
        `insurer_paid_cents` over all **other** cycles already `SETTLED` against the same
        package, takes the remaining headroom as the package's `lifetime_coverage_cap_cents`
        minus that prior total but never below zero, and sets `insurer_paid_cents` to the
        smaller of the raw insurer amount and that headroom." PRD 3.9: "The
        `final_patient_owed_cents` is `gross_charge_cents` minus `insurer_paid_cents`."

        Design: Difficulty/combinatorial_formula/settlement_multi_input_nested_min_and_conditional_branches
        """
        _, settled = self._build_capped_scenario()
        assert settled["gross_charge_cents"] == 650000
        assert settled["insurer_paid_cents"] == 20000, (
            f"insurer capped to headroom 20000, got {settled['insurer_paid_cents']}"
        )
        assert settled["final_patient_owed_cents"] == 630000


# ===========================================================================
# Queue A — combinatorial_formula / insurer_coverage_sum_then_round_not_per_line
# ===========================================================================
class TestSumThenRoundCoverage:
    def _build_round_scenario(self):
        cid = _clinic()
        pkg = _package(
            cid, name="HalfCover", base_price_cents=0, coverage_pct=0.5,
            stim_med_covered=True, cryo_storage_covered=False,
            annual_cryo_storage_cents=0, lifetime_coverage_cap_cents=100000000,
        )
        pat = _patient(cid, pkg)
        _consent(cid, pat, ["CYCLE_START"])
        cyc = _cycle(cid, pat)
        get_success_data(api_client.start_stim(cid, cyc, NURSE))
        get_success_data(api_client.create_medication(
            cid, f.create_medication_payload(cyc, drug_name="DrugOne", start_day_offset=0,
                                              end_day_offset=0, daily_dose_units=1, unit_price_cents=100001), NURSE))
        get_success_data(api_client.create_medication(
            cid, f.create_medication_payload(cyc, drug_name="DrugTwo", start_day_offset=0,
                                              end_day_offset=0, daily_dose_units=1, unit_price_cents=100001), NURSE))
        return validate_success(api_client.estimate_billing(cid, cyc, BILLING))

    def test_sum_then_round_gives_expected_owed(self):
        """PRD 2.8: "The rounding is applied once, to the summed covered total — never
        per line item."

        Design: Difficulty/combinatorial_formula/insurer_coverage_sum_then_round_not_per_line
        """
        est = self._build_round_scenario()
        assert est["estimated_patient_owed_cents"] == 100001, (
            f"SUM-then-round owed must be 100001, got {est['estimated_patient_owed_cents']}"
        )

    def test_not_per_line_rounded_result(self):
        """PRD 2.8: "Where a calculation multiplies a covered amount by a coverage
        fraction, the result is rounded **half up** to a whole number of cents. The
        rounding is applied once, to the summed covered total — never per line item."

        Design: Difficulty/combinatorial_formula/insurer_coverage_sum_then_round_not_per_line
        """
        est = self._build_round_scenario()
        assert est["estimated_patient_owed_cents"] != 100000, (
            "per-line rounding would give 100000; SUM-then-round must not"
        )


# ===========================================================================
# Queue A — compensating_invariant / billing_money_conservation_at_settlement
# ===========================================================================
class TestSettlementMoneyConservation:
    def _build_conservation_scenario(self):
        cid = _clinic()
        pkg = _package(
            cid, name="Cons IVF", base_price_cents=500000, coverage_pct=0.8,
            stim_med_covered=True, cryo_storage_covered=False,
            annual_cryo_storage_cents=60000, lifetime_coverage_cap_cents=100000000,
        )
        pat = _patient(cid, pkg)
        _consent(cid, pat, ["CYCLE_START", "RETRIEVAL", "TRANSFER", "CRYO_STORE"])
        tank = get_success_data(api_client.create_tank(cid, f.create_tank_payload(label="Tank-Y", capacity_slots=5), EMBRYO))
        cyc = _cycle(cid, pat)
        get_success_data(api_client.start_stim(cid, cyc, NURSE))
        m = get_success_data(api_client.create_medication(
            cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=0,
                                              end_day_offset=4, daily_dose_units=300, unit_price_cents=100), NURSE))["id"]
        get_success_data(api_client.administer_medication(cid, m, NURSE))
        get_success_data(api_client.retrieve(cid, cyc, {"oocytes_retrieved": 10}, NURSE))
        get_success_data(api_client.fertilize(cid, cyc, {"embryos_fertilized": 6}, EMBRYO))
        sp = get_success_data(api_client.create_specimen(cid, f.create_specimen_payload(cyc, tank["id"]), EMBRYO))["id"]
        get_success_data(api_client.store_specimen(cid, sp, {"expected_tank_version": tank["version"]}, EMBRYO))
        get_success_data(api_client.accrue_storage_year(cid, sp, EMBRYO))
        get_success_data(api_client.transfer(cid, cyc, EMBRYO))
        get_success_data(api_client.create_outcome(
            cid, f.create_outcome_payload(cyc, clinical_pregnancy=True, live_birth=True), NURSE))
        get_success_data(api_client.estimate_billing(cid, cyc, BILLING))
        get_success_data(api_client.complete_cycle(cid, cyc, NURSE))
        v = get_success_data(api_client.get_cycle(cid, cyc, BILLING))["version"]
        return validate_success(api_client.settle_billing(cid, cyc, {"expected_cycle_version": v}, BILLING))

    def test_settlement_amounts_pinned(self):
        """PRD 3.9: "The `gross_charge_cents` is the base plus the medication charge plus
        the cryo charge plus the cancellation component."

        Design: Difficulty/compensating_invariant/billing_money_conservation_at_settlement
        """
        settled = self._build_conservation_scenario()
        assert settled["gross_charge_cents"] == 710000
        assert settled["insurer_paid_cents"] == 520000
        assert settled["final_patient_owed_cents"] == 190000

    def test_money_conservation_identity_holds(self):
        """PRD 3.9: "A conservation invariant must hold at settlement: `gross_charge_cents`
        equals `insurer_paid_cents` plus `final_patient_owed_cents`."

        Design: Difficulty/compensating_invariant/billing_money_conservation_at_settlement
        """
        settled = self._build_conservation_scenario()
        assert_billing_conservation(settled)
        assert settled["gross_charge_cents"] == settled["insurer_paid_cents"] + settled["final_patient_owed_cents"]


# ===========================================================================
# Queue B — calculations / writeoff_fee_conservation
# ===========================================================================
def test_writeoff_keeps_only_cancellation_fee():
    """PRD 3.9: "Only the cancellation fee survives a write-off: the system sets
    `final_patient_owed_cents` equal to the cycle's `cancellation_fee_cents`, sets
    `insurer_paid_cents` to 0, sets `gross_charge_cents` equal to the cancellation fee,
    and forgives all medication and storage charges."

    Design: Corner/calculations/writeoff_fee_conservation
    """
    cid = _clinic()
    pkg = _package(cid, name="WO Pkg", base_price_cents=500000, coverage_pct=0.8,
                   stim_med_covered=True, cryo_storage_covered=False,
                   annual_cryo_storage_cents=60000, lifetime_coverage_cap_cents=100000000)
    pat = _patient(cid, pkg)
    _consent(cid, pat, ["CYCLE_START", "RETRIEVAL"])
    cyc = _cycle(cid, pat)
    get_success_data(api_client.start_stim(cid, cyc, NURSE))
    m = get_success_data(api_client.create_medication(
        cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=0,
                                          end_day_offset=4, daily_dose_units=300, unit_price_cents=100), NURSE))["id"]
    get_success_data(api_client.administer_medication(cid, m, NURSE))
    get_success_data(api_client.estimate_billing(cid, cyc, BILLING))
    get_success_data(api_client.retrieve(cid, cyc, {"oocytes_retrieved": 6}, NURSE))
    v = get_success_data(api_client.get_cycle(cid, cyc, NURSE))["version"]
    get_success_data(api_client.cancel_cycle(cid, cyc, {"expected_cycle_version": v}, NURSE))
    wo = validate_success(api_client.write_off_billing(cid, cyc, BILLING))
    assert wo["final_patient_owed_cents"] == 150000
    assert wo["insurer_paid_cents"] == 0
    assert wo["gross_charge_cents"] == 150000
    assert wo["billing_status"] == "WRITTEN_OFF"


# ===========================================================================
# Queue B — consistency_model / estimate_visible_in_same_response_immediate
# ===========================================================================
def test_estimate_immediately_visible_in_response():
    """PRD 3.9: "A `BillingSpecialist` first produces a **forward-looking estimate**,
    advancing `billing_status` `UNBILLED → ESTIMATED`. ... The estimate populates
    `estimated_patient_owed_cents`..."

    Design: Corner/consistency_model/estimate_visible_in_same_response_immediate
    """
    cid = _clinic()
    pkg = _package(cid, name="Imm Pkg", base_price_cents=0, coverage_pct=0.0,
                   stim_med_covered=False, cryo_storage_covered=False,
                   annual_cryo_storage_cents=0, lifetime_coverage_cap_cents=100000000)
    pat = _patient(cid, pkg)
    _consent(cid, pat, ["CYCLE_START"])
    cyc = _cycle(cid, pat)
    get_success_data(api_client.start_stim(cid, cyc, NURSE))
    get_success_data(api_client.create_medication(
        cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=0,
                                          end_day_offset=4, daily_dose_units=300, unit_price_cents=100), NURSE))
    est = validate_success(api_client.estimate_billing(cid, cyc, BILLING))
    assert est["estimated_patient_owed_cents"] == 150000
    assert est["billing_status"] == "ESTIMATED"
