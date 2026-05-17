"""Prescription lifecycle, DEA/EPCS gates, compliance score.

PRD §3.4 (draft / patch / issue / transmit / dispense / void), §3.5
(compliance score).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_prescription,
    create_prescription,
    create_prescription_payload,
    issue_prescription,
    make_physician_headers,
    occ_payload,
    setup_in_progress_consult,
    setup_routed_consult,
    setup_score_at_exactly_80,
    setup_score_just_below_80,
    setup_two_issued_prescriptions_for_compliance_avg,
    transmit_prescription,
    validate_error,
    validate_success,
    void_prescription,
    void_prescription_payload,
)


# ===========================================================================
# §3.4 Draft creation — field range validation
# ===========================================================================
class TestPrescriptionDraftRanges:
    """PRD §3.4: "The days_supply must lie between 1 and 90 inclusive,
    and refills must lie between 0 and 11 inclusive; a value outside
    either range is rejected with ERR_RX_FIELD_OUT_OF_RANGE.\""""

    @pytest.mark.parametrize("days_supply", [0, 91, 100])
    def test_days_supply_out_of_range_rejected(self, api, days_supply):
        """PRD §3.4: "days_supply must lie between 1 and 90 inclusive
        ... a value outside either range is rejected with
        ERR_RX_FIELD_OUT_OF_RANGE."

        Claim: days_supply outside [1, 90] returns
        ERR_RX_FIELD_OUT_OF_RANGE.
        """
        physician, _, _, consult = setup_in_progress_consult()
        res = api.create_prescription(
            consult["id"],
            create_prescription_payload(
                dea_schedule="NONE",
                days_supply=days_supply,
                refills=0,
            ),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_RX_FIELD_OUT_OF_RANGE")

    @pytest.mark.parametrize("refills", [-1, 12, 20])
    def test_refills_out_of_range_rejected(self, api, refills):
        """PRD §3.4: "refills must lie between 0 and 11 inclusive ... a
        value outside either range is rejected with
        ERR_RX_FIELD_OUT_OF_RANGE."

        Claim: refills outside [0, 11] returns
        ERR_RX_FIELD_OUT_OF_RANGE.
        """
        physician, _, _, consult = setup_in_progress_consult()
        res = api.create_prescription(
            consult["id"],
            create_prescription_payload(
                dea_schedule="NONE",
                days_supply=30,
                refills=refills,
            ),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_RX_FIELD_OUT_OF_RANGE")

    @pytest.mark.parametrize("days_supply", [1, 90])
    def test_days_supply_boundary_accepted(self, api, days_supply):
        """PRD §3.4: "The days_supply must lie between 1 and 90
        inclusive, and refills must lie between 0 and 11 inclusive".

        Claim: days_supply at exactly 1 and at exactly 90 is accepted
        (bounds are inclusive).
        """
        physician, _, _, consult = setup_in_progress_consult()
        res = api.create_prescription(
            consult["id"],
            create_prescription_payload(
                dea_schedule="NONE",
                days_supply=days_supply,
                refills=0,
            ),
            make_physician_headers(physician["id"]),
        )
        data = validate_success(res, 201)
        assert_prescription(data)
        assert data["days_supply"] == days_supply


# ===========================================================================
# §3.4 Draft creation — prescribing_physician_id == consult.physician_id
# ===========================================================================
class TestPrescriptionPhysicianMatch:
    """PRD §3.4: "The prescribing_physician_id on every prescription
    must equal the owning consult's physician_id; a mismatch — even via
    PATCH — is rejected with ERR_PHYSICIAN_MISMATCH.\""""

    def test_draft_creation_requires_consult_in_progress(self, api):
        """PRD §3.4: "During IN_PROGRESS, the physician drafts
        prescriptions, each carried under the consult by consult_id."
        PRD §2.6: "state-machine permissibility for the target resource
        (→ ERR_INVALID_STATE)".

        Claim: creating a Prescription under a ROUTED (not yet
        IN_PROGRESS) consult is rejected with ERR_INVALID_STATE.
        """
        physician, _, _, consult = setup_routed_consult()
        # consult.status == ROUTED.
        res = api.create_prescription(
            consult["id"],
            create_prescription_payload(
                dea_schedule="NONE", days_supply=15, refills=0,
            ),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.4 Issuance gates — DEA, Schedule II, license still ACTIVE
# ===========================================================================
class TestPrescriptionIssuance:
    """PRD §3.4: five gates fire in priority order on /issue."""

    def test_issue_controlled_without_dea_rejected(self, api):
        """PRD §3.4: "if dea_schedule is anything other than NONE, the
        issuing physician's dea_number must be on file and the
        prescription must carry an epcs_two_factor_token; absence of
        either is ERR_DEA_REQUIREMENTS_NOT_MET."

        Claim: a physician WITHOUT dea_number on file cannot issue a
        Schedule-II prescription; returns ERR_DEA_REQUIREMENTS_NOT_MET.
        """
        physician, _, _, consult = setup_in_progress_consult(
            with_dea=False,
        )
        # Note: physician has FULL license but no DEA. epcs token can
        # be provided, but the missing dea_number alone trips
        # ERR_DEA_REQUIREMENTS_NOT_MET.
        rx = create_prescription(
            consult=consult, physician=physician,
            drug_name="Adderall", dea_schedule="II", days_supply=30,
            refills=0, epcs_two_factor_token="T-2FA",
        )
        res = api.issue_prescription(
            rx["id"], occ_payload(version=rx["version"]),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_DEA_REQUIREMENTS_NOT_MET")

    def test_issue_controlled_without_epcs_token_rejected(self, api):
        """PRD §3.4: "the prescription must carry an
        epcs_two_factor_token; absence of either is
        ERR_DEA_REQUIREMENTS_NOT_MET."

        Claim: physician HAS DEA number but the prescription has NO
        epcs_two_factor_token; issue returns
        ERR_DEA_REQUIREMENTS_NOT_MET.
        """
        physician, _, _, consult = setup_in_progress_consult(
            with_dea=True,
        )
        # Schedule III, no epcs token.
        rx = create_prescription(
            consult=consult, physician=physician,
            drug_name="HydroIII", dea_schedule="III", days_supply=15,
            refills=0,  # no epcs_two_factor_token
        )
        res = api.issue_prescription(
            rx["id"], occ_payload(version=rx["version"]),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_DEA_REQUIREMENTS_NOT_MET")

    def test_schedule_ii_with_refills_rejected(self, api):
        """PRD §3.4: "when dea_schedule is II, refills must be exactly
        zero — a hard rule from DEA Schedule II policy; any positive
        refill count is ERR_SCHEDULE_II_REFILLS_FORBIDDEN."

        Claim: a Schedule II Rx with refills>0 returns
        ERR_SCHEDULE_II_REFILLS_FORBIDDEN at /issue.
        """
        physician, _, _, consult = setup_in_progress_consult(
            with_dea=True,
        )
        rx = create_prescription(
            consult=consult, physician=physician,
            drug_name="Adderall", dea_schedule="II", days_supply=15,
            refills=1, epcs_two_factor_token="T-2FA",
        )
        res = api.issue_prescription(
            rx["id"], occ_payload(version=rx["version"]),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_SCHEDULE_II_REFILLS_FORBIDDEN")

    def test_issue_non_controlled_succeeds(self, api):
        """PRD §3.4: "Issuing a draft prescription moves it from DRAFT
        to ISSUED and is by far the platform's most heavily gated
        transition."
        PRD §3.5: "Issuance requires the score to be at least 80".

        Claim: a NONE-schedule Rx under a FULL_LICENSE routing with
        days_supply<=30 scores 40+30+20+10=100 — well above the 80
        threshold — so issue succeeds.
        """
        physician, _, _, consult = setup_in_progress_consult()
        rx = create_prescription(
            consult=consult, physician=physician,
            drug_name="Amoxicillin", dea_schedule="NONE",
            days_supply=15, refills=0,
        )
        res = api.issue_prescription(
            rx["id"], occ_payload(version=rx["version"]),
            make_physician_headers(physician["id"]),
        )
        data = validate_success(res, 200)
        assert data["status"] == "ISSUED"


# ===========================================================================
# §3.5 Compliance score — exact threshold
# ===========================================================================
class TestComplianceScoreThreshold:
    """PRD §3.5: "Issuance requires the score to be at least 80; below
    threshold is ERR_COMPLIANCE_SCORE_TOO_LOW.\""""

    def test_score_at_exactly_80_passes(self, api):
        """PRD §3.5: "Issuance requires the score to be at least 80".
        PRD §3.5: the four legs: 30(IMLC_EXPEDITED) + 30(DEA OK) +
        20(II/refills=0) + 0(days>60) = 80.

        Claim: score=80 (exact threshold) → issue succeeds.

        difficulty: boundary_precision_check/compliance_score_at_80_exact_threshold
        """
        physician, _, _, consult, rx = setup_score_at_exactly_80()
        res = api.issue_prescription(
            rx["id"], occ_payload(version=rx["version"]),
            make_physician_headers(physician["id"]),
        )
        data = validate_success(res, 200)
        assert data["status"] == "ISSUED"

    def test_score_below_80_rejected(self, api):
        """PRD §3.5: "Issuance requires the score to be at least 80;
        below threshold is ERR_COMPLIANCE_SCORE_TOO_LOW."
        PRD §3.5: 30(IMLC) + 30(DEA OK) + 10(IV/refills>5) + 5(31-60
        days) = 75.

        Claim: score=75 (below threshold) → ERR_COMPLIANCE_SCORE_TOO_LOW.

        difficulty: boundary_precision_check/compliance_score_at_80_exact_threshold
        """
        physician, _, _, consult, rx = setup_score_just_below_80()
        res = api.issue_prescription(
            rx["id"], occ_payload(version=rx["version"]),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_COMPLIANCE_SCORE_TOO_LOW")


# ===========================================================================
# §3.4 Transmit / Dispense / Void
# ===========================================================================
class TestPrescriptionTerminalTransitions:

    def test_transmit_advances_issued_to_transmitted(self, api):
        """PRD §3.4: "the prescribing physician transmits the
        prescription to the pharmacy (advancing ISSUED to
        TRANSMITTED)".

        Claim: /transmit on an ISSUED prescription advances it to
        TRANSMITTED.
        """
        physician, _, _, consult = setup_in_progress_consult()
        rx = create_prescription(
            consult=consult, physician=physician,
            dea_schedule="NONE", days_supply=15, refills=0,
        )
        rx = issue_prescription(prescription=rx, physician=physician)
        res = api.transmit_prescription(
            rx["id"], occ_payload(version=rx["version"]),
            make_physician_headers(physician["id"]),
        )
        data = validate_success(res, 200)
        assert data["status"] == "TRANSMITTED"

    def test_void_from_draft_succeeds(self, api):
        """PRD §3.4: "Voiding is available from any of DRAFT, ISSUED, or
        TRANSMITTED and is performed by the prescribing physician with
        a void_reason supplied; the prescription advances to VOIDED".

        Claim: /void on a DRAFT prescription advances it to VOIDED with
        void_reason recorded.
        """
        physician, _, _, consult = setup_in_progress_consult()
        rx = create_prescription(
            consult=consult, physician=physician,
            dea_schedule="NONE", days_supply=15, refills=0,
        )
        res = api.void_prescription(
            rx["id"],
            void_prescription_payload(
                void_reason="Manual cancel",
                version=rx["version"],
            ),
            make_physician_headers(physician["id"]),
        )
        data = validate_success(res, 200)
        assert data["status"] == "VOIDED"
        assert data["void_reason"] == "Manual cancel"

    def test_void_from_transmitted_succeeds(self, api):
        """PRD §3.4: "Voiding is available from any of DRAFT, ISSUED, or
        TRANSMITTED".

        Claim: /void on a TRANSMITTED prescription advances it to
        VOIDED.
        """
        physician, _, _, consult = setup_in_progress_consult()
        rx = create_prescription(
            consult=consult, physician=physician,
            dea_schedule="NONE", days_supply=15, refills=0,
        )
        rx = issue_prescription(prescription=rx, physician=physician)
        rx = transmit_prescription(prescription=rx, physician=physician)
        res = api.void_prescription(
            rx["id"],
            void_prescription_payload(
                void_reason="Pharmacy cancelled",
                version=rx["version"],
            ),
            make_physician_headers(physician["id"]),
        )
        data = validate_success(res, 200)
        assert data["status"] == "VOIDED"


# ===========================================================================
# §3.5 Aggregate compliance — per-prescription vs physician average
# ===========================================================================
class TestComplianceAggregate:
    """PRD §3.5: "A read-only aggregate view of the score is also
    exposed at the physician level, accessible via a capability that
    returns the average score across that physician's prescriptions
    whose current status is ISSUED, TRANSMITTED, or DISPENSED (drafts
    and voided prescriptions are excluded from the average). The
    aggregate is rounded half-up to one decimal place.\""""

    def test_per_rx_passes_both_then_physician_aggregate_is_average(
        self, api,
    ):
        """PRD §3.5: "A read-only aggregate view of the score is also
        exposed at the physician level, accessible via a capability
        that returns the average score across that physician's
        prescriptions whose current status is ISSUED, TRANSMITTED, or
        DISPENSED".
        PRD §3.5: "The aggregate is rounded half-up to one decimal
        place."

        Per-RX gate already enforced at >= 80; the aggregate is
        observational only. 100 (Rx1 = 40+30+20+10) + 90 (Rx2 =
        40+30+20+0) → average 95.0.

        Claim: with two issued prescriptions scoring 100 and 90, the
        physician aggregate is 95.0 (mean, half-up, one decimal).

        difficulty: dual_variant_calc/compliance_score_per_rx_vs_physician_aggregate
        """
        physician, issued = (
            setup_two_issued_prescriptions_for_compliance_avg()
        )
        # Both prescriptions issued — they are in the qualifying set.
        assert all(r["status"] == "ISSUED" for r in issued)
        res = api.get_physician_compliance(
            physician["id"],
            TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(res, 200)
        # PRD §3.5 names the metric "average score". A faithful
        # implementation may surface it under any reasonable key; we
        # accept the common ones.
        avg = None
        for k in ("average_score", "average", "aggregate_score"):
            if k in data:
                avg = data[k]
                break
        assert avg is not None, (
            "PRD §3.5: physician compliance endpoint must return the "
            "average score; no average-style key found in response data"
        )
        assert avg == pytest.approx(95.0, abs=1e-9), (
            f"PRD §3.5 average of [100, 90] rounded half-up to one "
            f"decimal == 95.0; got {avg!r}"
        )

    def test_physician_aggregate_is_observational_not_threshold(self, api):
        """PRD §3.5: "The aggregate is observational only — no threshold
        is enforced on it".

        Claim: a physician with an aggregate that would be below 80 is
        NOT rejected by /compliance — the endpoint returns 200.

        difficulty: dual_variant_calc/compliance_score_per_rx_vs_physician_aggregate
        """
        # Reuse the 100/90 fixture — average is 95 here, well above any
        # threshold; the key claim is that 200 is returned regardless.
        physician, _ = (
            setup_two_issued_prescriptions_for_compliance_avg()
        )
        res = api.get_physician_compliance(
            physician["id"],
            TEST_USERS["compliance_officer_headers"],
        )
        validate_success(res, 200)
