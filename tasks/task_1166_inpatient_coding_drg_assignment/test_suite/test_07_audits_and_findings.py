"""Pre-bill coding audits: sampling, findings, apply/dismiss cascades,
accuracy scoring variants, credential review threshold, window overlap."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_finding,
    get_success_data,
    make_audit,
    make_auditor_headers,
    make_coder,
    resolve_finding,
    setup_accepted_case,
    setup_audit_on_accepted_case,
    validate_error,
    validate_success,
)


class TestAuditAccuracyCodeVsFinancialVariant:
    def _setup_applied_poa_finding(self, api, tag):
        """Subject's accepted case: principal + CC(poa=N) + NONE + 1 procedure.
        The CC line is excluded while poa=N, so the case groups at 650000; the
        APPLY flips poa to Y and regroups it to WITH_CC / 910000."""
        ctx = setup_accepted_case(
            f"MRN-DV2{tag}", f"E-DV2A{tag}",
            acuity="MEDICAL_HIGH", credential="CCS", total_charges_cents=2000000,
            dx_lines=[
                {"icd_code": "I21.09", "poa": "Y", "sequence": 1, "is_principal": True},
                {"icd_code": "E11.65", "poa": "N", "sequence": 2, "cc_level": "CC"},
                {"icd_code": "J44.1", "poa": "Y", "sequence": 3},
            ],
            proc_lines=[{"pcs_code": "0DJ08ZZ"}],
        )
        auditor = make_coder(f"E-DV2B{tag}", credential="RHIA", full_name="Aud Itor")
        ctx["auditor"] = auditor
        ctx["audit"] = make_audit(ctx["coder"]["id"], auditor["id"])
        ctx["finding"] = add_finding(
            ctx["audit"]["id"], auditor["id"], ctx["case"]["id"],
            finding_type="POA_CORRECTION",
            target_diagnosis_id=ctx["dx_line_ids"][1], corrected_poa="Y",
        )
        ctx["resolved"] = resolve_finding(ctx["finding"]["id"], auditor["id"], "APPLY")
        return ctx

    def test_accuracy_variants_diverge_on_same_findings(self, api, manager_headers):
        """PRD §3.8: "`accuracy_code_based` is one minus the ratio of incorrect
        lines to total lines, rounded half up to four decimal places" and
        "`accuracy_financial` is one minus the capped ratio, again rounded half
        up to four decimal places. Identical findings therefore yield a
        different score under the two variants."

        1 applied finding over 4 lines -> 0.7500; delta 260000 over corrected
        expected 910000 -> 1 - 0.2857 = 0.7143.

        Design: Difficulty/dual_variant_calc/audit_accuracy_code_vs_financial_variant
        """
        ctx = self._setup_applied_poa_finding(api, "")
        completed = validate_success(
            api.complete_audit(ctx["audit"]["id"], make_auditor_headers(ctx["auditor"]["id"])),
            200,
        )
        assert completed["accuracy_code_based"] == pytest.approx(0.7500, abs=1e-6)
        assert completed["accuracy_financial"] == pytest.approx(0.7143, abs=1e-6)
        assert completed["accuracy_code_based"] != completed["accuracy_financial"]

    def test_completion_updates_subject_coder_profile(self, api, manager_headers):
        """PRD §3.8: "Completion then writes the subject coder's profile:
        `accuracy_running` takes the new `accuracy_code_based`, and
        `credential_review_required` becomes true exactly when that score is
        strictly below 0.9500".

        Design: Difficulty/dual_variant_calc/audit_accuracy_code_vs_financial_variant
        """
        ctx = self._setup_applied_poa_finding(api, "P")
        validate_success(
            api.complete_audit(ctx["audit"]["id"], make_auditor_headers(ctx["auditor"]["id"])),
            200,
        )
        coder = validate_success(api.get_coder(ctx["coder"]["id"], manager_headers), 200)
        assert coder["accuracy_running"] == pytest.approx(0.7500, abs=1e-6)
        assert coder["credential_review_required"] is True


class TestAuditApplyPoaCascade:
    def _setup(self, api, tag):
        """Accepted case (MCC line admitted poa=N -> 650000) + open audit."""
        ctx = setup_audit_on_accepted_case(
            f"MRN-TC1{tag}", f"E-TC1A{tag}", f"E-TC1B{tag}",
            acuity="MEDICAL_HIGH", credential="CCS", total_charges_cents=2000000,
            dx_lines=[
                {"icd_code": "I21.09", "poa": "Y", "sequence": 1, "is_principal": True},
                {"icd_code": "N18.6", "poa": "N", "sequence": 2, "cc_level": "MCC"},
            ],
        )
        assert ctx["case"]["expected_reimbursement_cents"] == 650000
        return ctx

    def test_apply_cascades_line_case_and_bill(self, api, clerk_headers):
        """PRD §3.8: "First, the correction lands on the chart's lines: the
        targeted line has its `poa` flipped for a POA correction ... Second,
        the coded case is recomputed from the mutated lines — `severity_level`,
        `relative_weight`, and `expected_reimbursement_cents` refresh and the
        case's `version` increments by one. Third, if a bill exists in `DRAFT`
        or `READY`, its `expected_reimbursement_cents` follows the case's new
        value."

        Design: Difficulty/transitive_cascade/audit_apply_poa_cascade
        """
        ctx = self._setup(api, "")
        # Bill born READY (chart already CODED) at 650000
        bill = get_success_data(
            api.create_bill({"account_id": ctx["account"]["id"]}, clerk_headers)
        )
        assert bill["status"] == "READY"
        assert bill["expected_reimbursement_cents"] == 650000
        case_before = ctx["case"]
        mcc_line_id = ctx["dx_line_ids"][1]
        finding = add_finding(
            ctx["audit"]["id"], ctx["auditor"]["id"], case_before["id"],
            finding_type="POA_CORRECTION",
            target_diagnosis_id=mcc_line_id, corrected_poa="Y",
        )
        resolved = validate_success(
            api.resolve_finding(finding["id"], {"resolution": "APPLY"},
                                make_auditor_headers(ctx["auditor"]["id"])),
            200,
        )
        assert resolved["status"] == "APPLIED"

        line = get_success_data(
            api.get_diagnosis_line(mcc_line_id, make_auditor_headers(ctx["auditor"]["id"]))
        )
        assert line["poa"] == "Y", "hop 1: the POA correction lands on the line"

        case = get_success_data(
            api.get_coded_case(case_before["id"], make_auditor_headers(ctx["auditor"]["id"]))
        )
        assert case["severity_level"] == "WITH_MCC"
        assert case["relative_weight"] == pytest.approx(2.1000)
        assert case["expected_reimbursement_cents"] == 1365000
        assert case["version"] == case_before["version"] + 1

        bill_after = get_success_data(api.get_bill(bill["id"], clerk_headers))
        assert bill_after["status"] == "READY"
        assert bill_after["expected_reimbursement_cents"] == 1365000

    def test_apply_records_delta_and_increments_applied_count(self, api, clerk_headers):
        """PRD §3.8: "Fourth, the audit's `applied_findings_count` increases by
        one, and the finding's `delta_reimbursement_cents` records the signed
        difference between the new and the old expected reimbursement before
        the finding closes as `APPLIED`."

        Design: Difficulty/transitive_cascade/audit_apply_poa_cascade
        """
        ctx = self._setup(api, "D")
        get_success_data(api.create_bill({"account_id": ctx["account"]["id"]}, clerk_headers))
        finding = add_finding(
            ctx["audit"]["id"], ctx["auditor"]["id"], ctx["case"]["id"],
            finding_type="POA_CORRECTION",
            target_diagnosis_id=ctx["dx_line_ids"][1], corrected_poa="Y",
        )
        resolved = validate_success(
            api.resolve_finding(finding["id"], {"resolution": "APPLY"},
                                make_auditor_headers(ctx["auditor"]["id"])),
            200,
        )
        assert resolved["delta_reimbursement_cents"] == 715000
        audit = get_success_data(
            api.get_audit(ctx["audit"]["id"], make_auditor_headers(ctx["auditor"]["id"]))
        )
        assert audit["applied_findings_count"] == 1


class TestAccuracyThresholdExactly095:
    def _run_subject(self, api, tag, num_secondary_lines):
        """Subject codes one case with (1 principal + N secondary + 1
        procedure) ACTIVE lines; one POA_CORRECTION finding is APPLIED."""
        dx = [{"icd_code": "I21.09", "poa": "Y", "sequence": 1, "is_principal": True},
              {"icd_code": "E11.65", "poa": "N", "sequence": 2, "cc_level": "CC"}]
        fillers = ["J44.1", "I10", "E78.5", "N17.9", "J96.00", "D62", "K21.9",
                   "M79.3", "G47.33", "E66.01", "F32.9", "G89.29", "L89.152",
                   "N39.0", "A41.9", "B95.61", "J18.9"]
        for i in range(num_secondary_lines - 1):
            dx.append({"icd_code": fillers[i], "poa": "Y", "sequence": 3 + i})
        ctx = setup_accepted_case(
            f"MRN-BP2{tag}", f"E-BP2{tag}",
            acuity="MEDICAL_HIGH", credential="CCS", total_charges_cents=900000,
            dx_lines=dx, proc_lines=[{"pcs_code": "0DJ08ZZ"}],
        )
        auditor = make_coder(f"E-BP2{tag}U", credential="RHIA", full_name="Aud Three")
        audit = make_audit(ctx["coder"]["id"], auditor["id"])
        finding = add_finding(
            audit["id"], auditor["id"], ctx["case"]["id"],
            finding_type="POA_CORRECTION",
            target_diagnosis_id=ctx["dx_line_ids"][1], corrected_poa="Y",
        )
        resolve_finding(finding["id"], auditor["id"], "APPLY")
        completed = get_success_data(
            api.complete_audit(audit["id"], make_auditor_headers(auditor["id"]))
        )
        coder = get_success_data(api.get_coder(ctx["coder"]["id"], make_auditor_headers(auditor["id"])))
        return completed, coder

    def test_accuracy_exactly_095_not_flagged(self, api):
        """PRD §3.8: "`credential_review_required` becomes true exactly when
        that score is strictly below 0.9500, clearing back to false at 0.9500
        or above."

        20 ACTIVE lines, 1 applied finding -> 0.9500, not flagged.

        Design: Difficulty/boundary_precision_check/accuracy_threshold_exactly_095
        """
        completed, coder = self._run_subject(api, "A", num_secondary_lines=18)
        assert completed["accuracy_code_based"] == pytest.approx(0.9500, abs=1e-6)
        assert coder["credential_review_required"] is False

    def test_accuracy_below_095_flagged(self, api):
        """PRD §3.5: "`credential_review_required` is set true when a completed
        audit's code-based accuracy falls strictly below 0.9500".

        4 ACTIVE lines, 1 applied finding -> 0.7500, flagged.

        Design: Difficulty/boundary_precision_check/accuracy_threshold_exactly_095
        """
        completed, coder = self._run_subject(api, "B", num_secondary_lines=2)
        assert completed["accuracy_code_based"] == pytest.approx(0.7500, abs=1e-6)
        assert coder["credential_review_required"] is True


class TestAuditWindowHalfOpenAdjacency:
    def test_adjacent_window_allowed(self, api, manager_headers):
        """PRD §3.8: "because each window includes its start and excludes its
        end, a new window that begins exactly when an existing window ends is
        permitted".

        Design: Difficulty/resource_temporal_overlap/audit_window_half_open_adjacency
        """
        subject = make_coder("E-TO2A", credential="CCS", full_name="Sub Ject")
        auditor = make_coder("E-TO2B", credential="RHIA", full_name="Aud Itor")
        make_audit(subject["id"], auditor["id"],
                   window_start="2026-03-01T00:00:00Z", window_end="2026-04-01T00:00:00Z",
                   sample_size=3)
        adjacent = validate_success(
            api.create_audit(
                {
                    "subject_coder_id": subject["id"],
                    "window_start": "2026-04-01T00:00:00Z",
                    "window_end": "2026-05-01T00:00:00Z",
                    "sample_size": 3,
                },
                make_auditor_headers(auditor["id"]),
            ),
            201,
        )
        assert adjacent["status"] == "IN_REVIEW"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.8: "Sampling windows for the same subject coder may not
        overlap: ... any true overlap is rejected with
        `ERR_AUDIT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_window_half_open_adjacency
        """
        subject = make_coder("E-TO2C", credential="CCS", full_name="Sub Ject")
        auditor = make_coder("E-TO2D", credential="RHIA", full_name="Aud Itor")
        make_audit(subject["id"], auditor["id"],
                   window_start="2026-03-01T00:00:00Z", window_end="2026-04-01T00:00:00Z",
                   sample_size=3)
        res = api.create_audit(
            {
                "subject_coder_id": subject["id"],
                "window_start": "2026-03-15T00:00:00Z",
                "window_end": "2026-04-15T00:00:00Z",
                "sample_size": 3,
            },
            make_auditor_headers(auditor["id"]),
        )
        validate_error(res, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP, expected_status=409)


def test_resolve_finding_dismiss_keeps_case(api, manager_headers):
    """PRD §3.8: "Dismissal is the quiet path: no line, case, bill, or coder
    is mutated, `delta_reimbursement_cents` is set to zero, and the finding
    closes as `DISMISSED`."

    Design: Corner/state_machines/resolve_finding_dismiss_keeps_case
    """
    ctx = setup_audit_on_accepted_case(
        "MRN-SM4", "E-SM4A", "E-SM4B",
        acuity="MEDICAL_LOW", credential="CCS", total_charges_cents=900000,
    )
    auditor_h = make_auditor_headers(ctx["auditor"]["id"])
    pdx_id = ctx["dx_line_ids"][0]
    case_before = ctx["case"]
    finding = add_finding(
        ctx["audit"]["id"], ctx["auditor"]["id"], case_before["id"],
        finding_type="POA_CORRECTION", target_diagnosis_id=pdx_id, corrected_poa="W",
    )
    dismissed = validate_success(
        api.resolve_finding(finding["id"], {"resolution": "DISMISS"}, auditor_h), 200
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["delta_reimbursement_cents"] == 0

    case_after = get_success_data(api.get_coded_case(case_before["id"], auditor_h))
    assert case_after["version"] == case_before["version"]
    assert case_after["expected_reimbursement_cents"] == 650000
    line = get_success_data(api.get_diagnosis_line(pdx_id, auditor_h))
    assert line["poa"] == "Y"


def test_audit_self_subject_forbidden(api):
    """PRD §2.9: "At audit creation, the caller's `X-User-ID` must differ from
    the `subject_coder_id`; a self-audit is rejected with
    `ERR_SELF_AUDIT_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/audit_self_subject_forbidden
    """
    coder = make_coder("E-VAE", credential="RHIA", full_name="Self Audit")
    res = api.create_audit(
        {
            "subject_coder_id": coder["id"],
            "window_start": "2026-04-01T00:00:00Z",
            "window_end": "2026-05-01T00:00:00Z",
            "sample_size": 3,
        },
        make_auditor_headers(coder["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SELF_AUDIT_FORBIDDEN, expected_status=403)


def test_create_audit_with_cca_auditor_rejected(api):
    """PRD §3.8: "the auditor must be an `ACTIVE` coder holding a credential
    rank of at least `CCS` (insufficient rank is rejected with
    `ERR_CODER_CREDENTIAL_INSUFFICIENT`)".

    Design: Corner/validations/create_audit_with_cca_auditor_rejected
    """
    low = make_coder("E-VAF1", credential="CCA", full_name="Low Cred")
    subject = make_coder("E-VAF2", credential="CCS", full_name="Sub Ject")
    res = api.create_audit(
        {
            "subject_coder_id": subject["id"],
            "window_start": "2026-04-01T00:00:00Z",
            "window_end": "2026-05-01T00:00:00Z",
            "sample_size": 3,
        },
        make_auditor_headers(low["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CODER_CREDENTIAL_INSUFFICIENT, expected_status=422)


def test_finding_for_unsampled_case_rejected(api):
    """PRD §3.8: "Each finding names a `coded_case_id` — which must belong to
    the audit's `sampled_case_ids`, with out-of-sample cases refused by
    `ERR_CASE_NOT_IN_SAMPLE`".

    Design: Corner/validations/finding_for_unsampled_case_rejected
    """
    ctx = setup_accepted_case(
        "MRN-VAG", "E-VAG1", acuity="MEDICAL_LOW", credential="CCS"
    )
    other_subject = make_coder("E-VAG2", credential="CCS", full_name="Sub T")
    auditor = make_coder("E-VAG3", credential="RHIA", full_name="Aud Itor")
    audit = make_audit(other_subject["id"], auditor["id"])  # empty sample
    res = api.create_finding(
        audit["id"],
        {
            "coded_case_id": ctx["case"]["id"],
            "finding_type": "POA_CORRECTION",
            "target_diagnosis_id": ctx["dx_line_ids"][0],
            "corrected_poa": "W",
        },
        make_auditor_headers(auditor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CASE_NOT_IN_SAMPLE, expected_status=422)


def test_complete_audit_with_open_finding_rejected(api):
    """PRD §3.8: "The complete action belongs to the audit's own auditor and is
    refused with `ERR_OPEN_FINDINGS_REMAIN` while any finding on the audit is
    still `OPEN`."

    Design: Corner/validations/complete_audit_with_open_finding_rejected
    """
    ctx = setup_audit_on_accepted_case(
        "MRN-VAH", "E-VAH1", "E-VAH2",
        acuity="MEDICAL_LOW", credential="CCS",
    )
    add_finding(
        ctx["audit"]["id"], ctx["auditor"]["id"], ctx["case"]["id"],
        finding_type="POA_CORRECTION",
        target_diagnosis_id=ctx["dx_line_ids"][0], corrected_poa="W",
    )
    res = api.complete_audit(
        ctx["audit"]["id"], make_auditor_headers(ctx["auditor"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_OPEN_FINDINGS_REMAIN, expected_status=409)
    audit = get_success_data(
        api.get_audit(ctx["audit"]["id"], make_auditor_headers(ctx["auditor"]["id"]))
    )
    assert audit["status"] == "IN_REVIEW"
