"""Completeness/accuracy audit determination and the audit-driven penalty cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_acknowledged_encounter,
    create_audit,
    create_encounter,
    create_member,
    create_program,
    create_provider,
    create_rate_schedule,
    create_cycle,
    create_statement,
    create_validated_encounter,
    determine_audit,
    get_success_data,
    list_cycle_penalties,
    setup_basic_scenario,
    setup_determined_fail_audit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import FIN, OPS, STATE


class TestCompletenessVariants:
    def test_completeness_intake_vs_eligibility_divergence(self):
        """PRD §3.8: "Both variants are rounded half up to four decimal places, so a
        cycle with 3 acknowledged encounters, 4 attributed intake encounters, and 4
        member-months reads 0.7500 on the intake variant but 1.5000 on the governing
        variant — three divided by an expectation of two."
        PRD §3.8: "The `determination` is `PASS` exactly when the eligibility-benchmark
        completeness rate reaches or exceeds the program's `completeness_threshold` and
        the accuracy rate reaches or exceeds its `accuracy_threshold` — both boundaries
        inclusive — and `FAIL` otherwise"

        Design: Difficulty/dual_variant_calc/completeness_intake_vs_eligibility_divergence
        """
        program = create_program(name="P-CMP")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        members = [create_member(program["id"], aid_category="TANF") for _ in range(4)]
        provider = create_provider(program["id"])
        # 3 of 4 validated encounters reach ACKNOWLEDGED; e4 is validated but never staged.
        for i in range(3):
            create_acknowledged_encounter(program["id"], cycle["id"], members[i]["id"], provider["id"],
                                          encounter_ref=f"E{i + 1}",
                                          service_from_date=f"2026-08-{10 + i:02d}",
                                          service_to_date=f"2026-08-{10 + i:02d}")
        e4 = create_validated_encounter(program["id"], cycle["id"], members[3]["id"], provider["id"],
                                        encounter_ref="E4", service_from_date="2026-08-13",
                                        service_to_date="2026-08-13")
        assert e4["status"] == "VALIDATED"
        statement = create_statement(cycle["id"])
        assert statement["provisional_paid_cents"] == 200000
        audit = create_audit(cycle["id"], sample_size=10, defect_count=0)
        determined = validate_success(api_client.determine_audit(audit["id"], STATE))
        assert determined["completeness_intake_rate"] == pytest.approx(0.75), "3 accepted / 4 intake"
        assert determined["completeness_eligibility_rate"] == pytest.approx(1.5), "3 accepted / ceil(4 * 0.5) = 2"
        assert determined["accuracy_rate"] == pytest.approx(1.0)
        assert determined["determination"] == "PASS", "the eligibility variant governs: 1.5 >= 0.98"
        _data, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 0, "no penalty on PASS"

    def test_completeness_eligibility_governs_determination_despite_low_intake_rate(self):
        """PRD §3.8: "The governing state view, `completeness_eligibility_rate`, divides
        the same numerator by an eligibility-derived expectation: count the
        member-months (members whose enrollment overlaps the cycle window by at least
        one day), multiply by the benchmark of one-half encounter per member-month, and
        round up to a whole number; the rate is zero when that expectation is zero."
        PRD §3.8: "The `determination` is `PASS` exactly when the eligibility-benchmark
        completeness rate reaches or exceeds the program's `completeness_threshold` and
        the accuracy rate reaches or exceeds its `accuracy_threshold` — both boundaries
        inclusive — and `FAIL` otherwise"

        Design: Difficulty/dual_variant_calc/completeness_intake_vs_eligibility_divergence
        """
        program = create_program(name="P-CMP2")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        m1 = create_member(program["id"], aid_category="TANF")
        create_member(program["id"], aid_category="TANF")
        provider = create_provider(program["id"])
        create_acknowledged_encounter(program["id"], cycle["id"], m1["id"], provider["id"],
                                      encounter_ref="E1")
        # A second intake encounter that REJECTS: it still counts in the intake tally.
        e2 = create_encounter(program["id"], m1["id"], provider["id"], encounter_ref="E2",
                              service_from_date="2026-08-11", service_to_date="2026-08-11",
                              diagnosis_codes=["9XX"], paid_amount_cents=3000,
                              lines=[{"line_number": 1, "procedure_code": "99212", "units": 1,
                                      "billed_amount_cents": 3000, "paid_amount_cents": 3000}])
        rejected = get_success_data(api_client.validate_encounter(e2["id"], OPS))
        assert rejected["status"] == "REJECTED"

        create_statement(cycle["id"])
        audit = create_audit(cycle["id"], sample_size=10, defect_count=0)
        determined = validate_success(api_client.determine_audit(audit["id"], STATE))
        assert determined["completeness_intake_rate"] == pytest.approx(0.5), "1 accepted / 2 intake"
        assert determined["completeness_eligibility_rate"] == pytest.approx(1.0), "1 accepted / ceil(2 * 0.5) = 1"
        assert determined["determination"] == "PASS", (
            "intake variant 0.5 < 0.98 yet the governing eligibility variant 1.0 >= 0.98 yields PASS"
        )


class TestAccuracyBoundary:
    def test_audit_accuracy_exactly_at_threshold_passes(self):
        """PRD §3.8: "The `determination` is `PASS` exactly when the
        eligibility-benchmark completeness rate reaches or exceeds the program's
        `completeness_threshold` and the accuracy rate reaches or exceeds its
        `accuracy_threshold` — both boundaries inclusive — and `FAIL` otherwise"
        PRD §3.8: "The `accuracy_rate` is one minus the ratio of `defect_count` to
        `sample_size`, also rounded half up to four decimal places."

        Design: Difficulty/boundary_precision_check/audit_accuracy_exactly_at_threshold_passes
        """
        program = create_program(name="P-BND1")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        m1 = create_member(program["id"], aid_category="TANF")
        create_member(program["id"], aid_category="TANF")
        provider = create_provider(program["id"])
        create_acknowledged_encounter(program["id"], cycle["id"], m1["id"], provider["id"],
                                      encounter_ref="E1")
        create_statement(cycle["id"])
        audit = create_audit(cycle["id"], sample_size=20, defect_count=1)
        determined = validate_success(api_client.determine_audit(audit["id"], STATE))
        assert determined["accuracy_rate"] == pytest.approx(0.95), "1 - 1/20, the exact boundary value"
        assert determined["completeness_eligibility_rate"] == pytest.approx(1.0)
        assert determined["determination"] == "PASS", "0.95 >= 0.95: boundary is inclusive"
        _data, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 0

    def test_audit_accuracy_one_defect_above_threshold_fails(self):
        """PRD §3.8: "The `determination` is `PASS` exactly when the
        eligibility-benchmark completeness rate reaches or exceeds the program's
        `completeness_threshold` and the accuracy rate reaches or exceeds its
        `accuracy_threshold` — both boundaries inclusive — and `FAIL` otherwise"
        PRD §3.8: "The system creates a PenaltyAssessment in status `ASSESSED` whose
        `reason` is `COMBINED` when both components failed, `COMPLETENESS` when only
        completeness failed, and `ACCURACY` when only accuracy failed."

        Design: Difficulty/boundary_precision_check/audit_accuracy_exactly_at_threshold_passes
        """
        program = create_program(name="P-BND1B")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        m1 = create_member(program["id"], aid_category="TANF")
        create_member(program["id"], aid_category="TANF")
        provider = create_provider(program["id"])
        create_acknowledged_encounter(program["id"], cycle["id"], m1["id"], provider["id"],
                                      encounter_ref="E1")
        create_statement(cycle["id"])
        audit = create_audit(cycle["id"], sample_size=20, defect_count=2)
        determined = validate_success(api_client.determine_audit(audit["id"], STATE))
        assert determined["accuracy_rate"] == pytest.approx(0.90), "one defect more than the boundary"
        assert determined["determination"] == "FAIL", "0.90 < 0.95"
        penalties, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 1
        assert penalties[0]["reason"] == "ACCURACY"
        assert penalties[0]["status"] == "ASSESSED"
        # raw = 5 points * 50000 = 250000; cap = 10% of provisional 100000 = 10000
        assert penalties[0]["amount_cents"] == 10000


class TestPenaltyAmountComputation:
    def test_penalty_nested_min_max_cap_binds(self):
        """PRD §3.8: "The `amount_cents` starts from deficiency points: each component
        contributes the shortfall of its measured rate below its threshold expressed in
        percentage points — a completeness rate of 0.93 against a 0.98 threshold
        contributes 5 points — with a component that met its threshold contributing
        zero. The point total converts at 50000 cents per point into a raw amount, and
        the cap is the program's `penalty_cap_percent` of the cycle statement's
        `provisional_paid_cents`, rounded half up to a whole cent; the assessed amount is
        the smaller of the raw amount and the cap."

        Design: Difficulty/combinatorial_formula/penalty_nested_min_max_cap_binds
        """
        result = setup_determined_fail_audit(program_name="P-PEN", aid_category="SSI",
                                             pmpm_cents=120000, member_count=4,
                                             acknowledged_count=1, sample_size=20, defect_count=4)
        audit = result["audit"]
        assert audit["completeness_eligibility_rate"] == pytest.approx(0.5), "1 accepted / ceil(4 * 0.5) = 2"
        assert audit["accuracy_rate"] == pytest.approx(0.8)
        assert audit["determination"] == "FAIL"
        penalties = result["penalties"]
        assert len(penalties) == 1
        penalty = penalties[0]
        assert penalty["reason"] == "COMBINED", "both components failed"
        # raw = (48 + 15) * 50000 = 3150000; cap = round_half_up(0.10 * 480000) = 48000
        assert penalty["amount_cents"] == 48000
        assert penalty["status"] == "ASSESSED"

    def test_penalty_cap_binds_audit_driven_assessment_via_get(self):
        """PRD §3.8: "The point total converts at 50000 cents per point into a raw
        amount, and the cap is the program's `penalty_cap_percent` of the cycle
        statement's `provisional_paid_cents`, rounded half up to a whole cent; the
        assessed amount is the smaller of the raw amount and the cap."
        PRD §3.8: "Penalty assessments list by `cycle_id`, `audit_id`, and `status`."

        Design: Difficulty/combinatorial_formula/penalty_nested_min_max_cap_binds
        """
        result = setup_determined_fail_audit(program_name="P-PEN2", aid_category="SSI",
                                             pmpm_cents=120000, member_count=4,
                                             acknowledged_count=1, sample_size=20, defect_count=4)
        penalty = result["penalties"][0]
        fetched = validate_success(api_client.get_penalty(penalty["id"], STATE))
        assert fetched["amount_cents"] == 48000
        assert fetched["reason"] == "COMBINED"
        assert fetched["status"] == "ASSESSED"
        assert fetched["cycle_id"] == result["cycle"]["id"]
        assert fetched["audit_id"] == result["audit"]["id"]

    def test_penalty_uncapped_when_raw_below_cap(self):
        """PRD §3.8: "the assessed amount is the smaller of the raw amount and the
        cap."
        PRD §3.8: "The system creates a PenaltyAssessment in status `ASSESSED` whose
        `reason` is `COMBINED` when both components failed, `COMPLETENESS` when only
        completeness failed, and `ACCURACY` when only accuracy failed."

        Design: Corner/calculations/penalty_uncapped_when_raw_below_cap
        """
        result = setup_determined_fail_audit(program_name="P-CALC1", aid_category="SSI",
                                             pmpm_cents=120000, member_count=5,
                                             acknowledged_count=3, sample_size=100, defect_count=6)
        audit = result["audit"]
        assert audit["completeness_eligibility_rate"] == pytest.approx(1.0), "3 accepted / ceil(5 * 0.5) = 3"
        assert audit["accuracy_rate"] == pytest.approx(0.94)
        assert audit["determination"] == "FAIL", "0.94 < 0.95 while completeness 1.0 passes"
        penalties = result["penalties"]
        assert len(penalties) == 1
        assert penalties[0]["reason"] == "ACCURACY"
        # raw = 1 point * 50000 = 50000; cap = 10% of 600000 = 60000; min is the raw amount
        assert penalties[0]["amount_cents"] == 50000


class TestAccuracyPrecision:
    def test_accuracy_rate_rounds_to_four_decimals(self):
        """PRD §3.8: "The `accuracy_rate` is one minus the ratio of `defect_count` to
        `sample_size`, also rounded half up to four decimal places."
        PRD §2.6: "Ratio quantities — completeness rates, accuracy rate, provider error
        rate, and risk scores — are represented with exactly 4 decimal places, rounded
        half up at the final step of their computation."

        Design: Corner/calculations/accuracy_rate_rounds_to_four_decimals
        """
        program = create_program(name="P-CALC2")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        m1 = create_member(program["id"], aid_category="TANF")
        provider = create_provider(program["id"])
        create_acknowledged_encounter(program["id"], cycle["id"], m1["id"], provider["id"],
                                      encounter_ref="E1")
        create_statement(cycle["id"])
        audit = create_audit(cycle["id"], sample_size=3, defect_count=1)
        determined = validate_success(api_client.determine_audit(audit["id"], STATE))
        assert determined["accuracy_rate"] == pytest.approx(0.6667), "round_half_up(1 - 1/3, 4)"
        assert determined["determination"] == "FAIL"
        penalties, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 1
        assert penalties[0]["reason"] == "ACCURACY"


class TestAuditCreationRules:
    def test_audit_sample_invalid_variants_rejected(self):
        """PRD §3.8: "The `StateAgency` opens an audit for a cycle by pinning the sample
        at creation: a `cycle_id`, a `sample_size` of at least one, and a `defect_count`
        between zero and the sample size inclusive."

        Design: Corner/validations/audit_sample_invalid_variants_rejected
        """
        program = create_program(name="P-V4")
        cycle = create_cycle(program["id"])
        resp1 = api_client.create_audit({"cycle_id": cycle["id"], "sample_size": 0, "defect_count": 0}, STATE)
        validate_error(resp1, ApiErrorId.ERR_AUDIT_SAMPLE_INVALID)
        resp2 = api_client.create_audit({"cycle_id": cycle["id"], "sample_size": 10, "defect_count": 11}, STATE)
        validate_error(resp2, ApiErrorId.ERR_AUDIT_SAMPLE_INVALID)
        _data, meta = validate_paginated(api_client.list_audits(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 0

    def test_audit_and_statement_uniqueness_per_cycle(self):
        """PRD §3.8: "At most one audit may exist per cycle, and that uniqueness is
        examined before the sample values — a second audit for the same cycle draws
        `ERR_AUDIT_EXISTS`, while a bad sample draws `ERR_AUDIT_SAMPLE_INVALID`."
        PRD §3.9: "and then the one-statement-per-cycle constraint, a duplicate drawing
        `ERR_STATEMENT_EXISTS`."

        Design: Corner/validations/audit_and_statement_uniqueness_per_cycle
        """
        program = create_program(name="P-V5")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        create_member(program["id"], aid_category="TANF")
        create_audit(cycle["id"], sample_size=5, defect_count=0)
        create_statement(cycle["id"])

        resp_a = api_client.create_audit({"cycle_id": cycle["id"], "sample_size": 8, "defect_count": 1}, STATE)
        validate_error(resp_a, ApiErrorId.ERR_AUDIT_EXISTS)
        resp_s = api_client.create_statement({"cycle_id": cycle["id"]}, FIN)
        validate_error(resp_s, ApiErrorId.ERR_STATEMENT_EXISTS)


class TestPipelinePrerequisites:
    def test_audit_determine_requires_statement_and_reconcile_requires_snapshots(self):
        """PRD §3.8: "Determination by `StateAgency` requires a `DRAFT` audit
        (`ERR_INVALID_STATE_TRANSITION` otherwise) and requires the cycle's capitation
        statement to already exist, since the statement's provisional total anchors the
        penalty cap — its absence is rejected with `ERR_STATEMENT_REQUIRED`."
        PRD §3.9: "Reconciliation by `McoFinance` requires a `PROVISIONAL_ISSUED`
        statement (`ERR_INVALID_STATE_TRANSITION` otherwise) and requires risk scores to
        exist — a null `risk_computed_at` is rejected with `ERR_SNAPSHOTS_REQUIRED`."

        Design: Corner/validations/audit_determine_requires_statement_and_reconcile_requires_snapshots
        """
        program = create_program(name="P-V7")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        create_member(program["id"], aid_category="TANF")
        audit = create_audit(cycle["id"], sample_size=5, defect_count=0)

        resp_d = api_client.determine_audit(audit["id"], STATE)
        validate_error(resp_d, ApiErrorId.ERR_STATEMENT_REQUIRED)

        statement = create_statement(cycle["id"])
        resp_r = api_client.reconcile_statement(statement["id"], FIN)
        validate_error(resp_r, ApiErrorId.ERR_SNAPSHOTS_REQUIRED)

        audit_after = get_success_data(api_client.get_audit(audit["id"], STATE))
        assert audit_after["status"] == "DRAFT"
        statement_after = get_success_data(api_client.get_statement(statement["id"], FIN))
        assert statement_after["status"] == "PROVISIONAL_ISSUED"
