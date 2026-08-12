"""Submission-time sequencing rules and DRG grouping / expected reimbursement."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_diagnosis,
    assert_coded_case,
    make_auditor_headers,
    make_coder_headers,
    setup_assigned,
    setup_in_progress,
    setup_submitted_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSubmitGateViolations:
    def test_submit_assignment_from_assigned_rejected(self, api, manager_headers):
        """PRD §3.4: "The submit action on an `IN_PROGRESS` assignment —
        again restricted to the assignment's own coder — enforces four checks";
        per §2.8 "the target resource must be in a state that permits the
        requested transition; generic state-precondition failures yield
        `ERR_INVALID_STATE` (HTTP 409)". PRD §3.4: "A successful submission
        moves the chart from `IN_CODING` to `SUBMITTED`, stamps `submitted_at`,
        and creates exactly one coded case per chart" — a failed submit creates
        none.

        Design: Corner/state_machines/submit_assignment_from_assigned_rejected
        """
        ctx = setup_assigned("MRN-SM2", "E-SM2", acuity="MEDICAL_LOW", credential="CCS")
        res = api.submit_assignment(
            ctx["assignment"]["id"], make_coder_headers(ctx["coder"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        data, meta = validate_paginated(
            api.list_coded_cases(manager_headers, params={"chart_id": ctx["chart"]["id"]})
        )
        assert data == [], "no coded case may be created by a rejected submit"

    def test_submit_without_principal_rejected(self, api, manager_headers):
        """PRD §3.4: "exactly one `ACTIVE` diagnosis line must carry
        `is_principal` (`ERR_PRINCIPAL_DX_REQUIRED` otherwise)".

        Design: Corner/validations/submit_without_principal_rejected
        """
        ctx = setup_in_progress("MRN-VA8", "E-VA8", acuity="MEDICAL_LOW", credential="CCS")
        add_diagnosis(ctx["chart"]["id"], ctx["coder"]["id"],
                      icd_code="J44.1", poa="Y", sequence=1)
        res = api.submit_assignment(
            ctx["assignment"]["id"], make_coder_headers(ctx["coder"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_PRINCIPAL_DX_REQUIRED, expected_status=422)

    def test_submit_with_symptom_principal_rejected(self, api, manager_headers):
        """PRD §3.4: "that principal line's `icd_code` must not start with `R`
        or `Z` (`ERR_INVALID_PRINCIPAL_CODE`)".

        Design: Corner/validations/submit_with_symptom_principal_rejected
        """
        ctx = setup_in_progress("MRN-VA9", "E-VA9", acuity="MEDICAL_LOW", credential="CCS")
        add_diagnosis(ctx["chart"]["id"], ctx["coder"]["id"],
                      icd_code="R07.9", poa="Y", sequence=1, is_principal=True)
        res = api.submit_assignment(
            ctx["assignment"]["id"], make_coder_headers(ctx["coder"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PRINCIPAL_CODE, expected_status=422)

    def test_submit_manifestation_before_etiology_rejected(self, api, manager_headers):
        """PRD §3.4: "every `ACTIVE` manifestation line must be sequenced
        strictly after its etiology line, so a manifestation whose `sequence`
        is less than or equal to its etiology's fails with
        `ERR_MANIFESTATION_ORDER`."

        Design: Corner/validations/submit_manifestation_before_etiology_rejected
        """
        ctx = setup_in_progress("MRN-VAB", "E-VAB", acuity="MEDICAL_LOW", credential="CCS")
        chart_id = ctx["chart"]["id"]
        coder_id = ctx["coder"]["id"]
        add_diagnosis(chart_id, coder_id, icd_code="I21.09", poa="Y", sequence=1,
                      is_principal=True)
        etio = add_diagnosis(chart_id, coder_id, icd_code="E11.9", poa="Y", sequence=3)
        add_diagnosis(chart_id, coder_id, icd_code="E11.621", poa="Y", sequence=2,
                      is_manifestation=True, manifestation_of_id=etio["id"])
        res = api.submit_assignment(ctx["assignment"]["id"], make_coder_headers(coder_id))
        validate_error(res, ApiErrorId.ERR_MANIFESTATION_ORDER, expected_status=422)


class TestGroupingInputSet:
    def test_grouping_excludes_poa_n_secondary(self, api, manager_headers):
        """PRD §3.4: "The eligible secondary diagnoses are the chart's `ACTIVE`
        lines that are not the principal, whose `cc_level` is not `NONE`, and
        whose `poa` is not `N` — a condition that arose after admission is a
        hospital-acquired condition and never raises severity."

        Design: Corner/calculations/grouping_excludes_poa_n_secondary
        """
        ctx = setup_submitted_case(
            "MRN-CL1", "E-CL1",
            acuity="MEDICAL_HIGH", credential="CCS", total_charges_cents=2000000,
            dx_lines=[
                {"icd_code": "I21.09", "poa": "Y", "sequence": 1, "is_principal": True},
                {"icd_code": "N18.6", "poa": "N", "sequence": 2, "cc_level": "MCC"},
            ],
        )
        case = ctx["case"]
        assert_coded_case(case)
        assert case["severity_level"] == "WITHOUT_CC_MCC"
        assert case["relative_weight"] == pytest.approx(1.0000)
        assert case["expected_reimbursement_cents"] == 650000


class TestReimbursementPerComponentRounding:
    def test_outlier_components_rounded_then_summed(self, api, manager_headers):
        """PRD §3.4: "The DRG payment component is the product of a base rate
        of 650000 cents and the case's just-computed `relative_weight`, rounded
        half up to whole cents. ... The outlier payment is eighty percent of
        the amount by which the rounded cost estimate exceeds that threshold —
        zero when the estimate does not exceed it — rounded half up to whole
        cents. The case's `expected_reimbursement_cents` is the sum of the
        rounded DRG payment and the rounded outlier payment".

        Charges 10000000 -> cost estimate 3000000; weight 1.0000 -> drg
        650000; threshold 1150000; outlier round((3000000-1150000)*0.8) =
        1480000; total 2130000.

        Design: Difficulty/combinatorial_formula/reimbursement_per_component_rounding
        """
        ctx = setup_submitted_case(
            "MRN-CF2", "E-CF2",
            acuity="MEDICAL_LOW", credential="CCS", total_charges_cents=10000000,
        )
        case = ctx["case"]
        assert case["severity_level"] == "WITHOUT_CC_MCC"
        assert case["relative_weight"] == pytest.approx(1.0000)
        assert case["expected_reimbursement_cents"] == 2130000

    def test_per_component_order_pinned_over_sum_then_round(self, api, manager_headers):
        """PRD §2.6: "each such component is individually rounded half up to
        whole cents first, and the rounded components are then summed. Summing
        the unrounded components and rounding once at the end is a different,
        forbidden order."

        Same scenario re-read through the single-resource fetch: the pinned
        per-component-then-sum value 2130000 must persist.

        Design: Difficulty/combinatorial_formula/reimbursement_per_component_rounding
        """
        ctx = setup_submitted_case(
            "MRN-CF2B", "E-CF2B",
            acuity="MEDICAL_LOW", credential="CCS", total_charges_cents=10000000,
        )
        case = validate_success(api.get_coded_case(ctx["case"]["id"], manager_headers), 200)
        assert_coded_case(case)
        assert case["expected_reimbursement_cents"] == 2130000


class TestDrgSeverityMsVsApVariant:
    def _setup_ms_grouped_case(self, api, manager_headers):
        ctx = setup_submitted_case(
            "MRN-DV1", "E-DV1",
            acuity="MEDICAL_HIGH", credential="RHIA", total_charges_cents=2000000,
            dx_lines=[
                {"icd_code": "I21.09", "poa": "Y", "sequence": 1,
                 "is_principal": True, "cc_level": "NONE"},
                {"icd_code": "N18.6", "poa": "Y", "sequence": 2, "cc_level": "MCC"},
                {"icd_code": "E11.65", "poa": "Y", "sequence": 3, "cc_level": "CC"},
            ],
        )
        return ctx

    def test_ms_drg_baseline_then_ap_regroup(self, api, manager_headers):
        """PRD §3.4: "Under the `MS_DRG` variant, the `severity_level` is the
        single highest eligible level: `WITH_MCC` if any eligible line is an
        MCC, else `WITH_CC` if any eligible line is a CC, else
        `WITHOUT_CC_MCC`" with weights "1.0000 for `WITHOUT_CC_MCC`, 1.4000
        for `WITH_CC`, and 2.1000 for `WITH_MCC`", while "Under the `AP_DRG`
        variant, severity instead accumulates severity-of-illness points — two
        points per eligible MCC line plus one point per eligible CC line —
        and the `severity_level` is ... `SOI_3` at exactly three ... the AP
        weight table gives ... 1.8000 for `SOI_3`".

        Design: Difficulty/dual_variant_calc/drg_severity_ms_vs_ap_variant
        """
        ctx = self._setup_ms_grouped_case(api, manager_headers)
        case = ctx["case"]
        assert case["grouper_variant"] == "MS_DRG"
        assert case["severity_level"] == "WITH_MCC"
        assert case["relative_weight"] == pytest.approx(2.1000)
        assert case["expected_reimbursement_cents"] == 1365000

        auditor_id = ctx["coder"]["id"]  # entity-backed Auditor identity
        regrouped = validate_success(
            api.regroup_coded_case(
                case["id"],
                {
                    "expected_coded_case_version": case["version"],
                    "grouper_variant": "AP_DRG",
                },
                make_auditor_headers(auditor_id),
            ),
            200,
        )
        assert regrouped["grouper_variant"] == "AP_DRG"
        assert regrouped["severity_level"] == "SOI_3"
        assert regrouped["relative_weight"] == pytest.approx(1.8000)
        assert regrouped["expected_reimbursement_cents"] == 1170000
        assert regrouped["expected_reimbursement_cents"] != 1365000

    def test_ap_variant_diverges_from_ms_on_identical_lines(self, api, manager_headers):
        """PRD §3.4: "Identical line data therefore yields a different
        severity, weight, and expected reimbursement under the two variants."
        One MCC + one CC eligible secondary = 3 SOI points under AP_DRG.

        Design: Difficulty/dual_variant_calc/drg_severity_ms_vs_ap_variant
        """
        ctx = self._setup_ms_grouped_case(api, manager_headers)
        case = ctx["case"]
        version_before = case["version"]
        regrouped = validate_success(
            api.regroup_coded_case(
                case["id"],
                {
                    "expected_coded_case_version": version_before,
                    "grouper_variant": "AP_DRG",
                },
                make_auditor_headers(ctx["coder"]["id"]),
            ),
            200,
        )
        assert regrouped["severity_level"] == "SOI_3"
        assert regrouped["version"] == version_before + 1, (
            "PRD §3.4: a successful regroup 'increments the case's `version` by one'"
        )
        assert regrouped["expected_reimbursement_cents"] == 1170000
