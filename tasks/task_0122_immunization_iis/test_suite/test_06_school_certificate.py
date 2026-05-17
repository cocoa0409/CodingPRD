"""School enrollment certificate lifecycle: DRAFT -> ISSUED / DEFICIENT
/ EXEMPTION_GRANTED -> REVOKED, auto-bubble, auto-demote, uniqueness.

PRD §3.8 (certificate lifecycle and coverage evaluation), §3.7
(antigen rules / school_enrollment_required), §2.6 (validation
priority 100 - duplicate).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    PROVIDER_CLINICIAN_ID,
    TEST_USERS,
    anchor_clock,
    assert_school_certificate,
    create_antigen_schedule_rule,
    create_certificate,
    create_patient,
    create_provider_organization,
    create_vaccine_lot,
    create_vaccine_product,
    create_certificate_payload,
    iso_anchor_offset,
    issue_certificate,
    re_get_certificate,
    schedule_and_administer_dose,
    setup_basic_scenario,
    setup_school_required_full_set,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.8 Create / issue paths
# ===========================================================================
class TestCertificateCreation:

    def test_create_certificate_starts_in_draft(self, api):
        """PRD §3.8: "The certificate's patient_id mirrors the URL, its
        certificate_status begins at DRAFT, its missing_antigens starts
        as the empty array, and issued_at is null."

        Claim: a newly created certificate has certificate_status ==
        'DRAFT', missing_antigens == [], issued_at == null.
        """
        patient = create_patient()
        res = api.create_certificate(
            patient["id"],
            create_certificate_payload(school_year="2026-2027",
                                       grade_level="K"),
            TEST_USERS["school_registrar_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["certificate_status"] == "DRAFT"
        assert data["missing_antigens"] == []
        assert data.get("issued_at") is None
        assert_school_certificate(data)

    def test_create_certificate_invalid_school_year_rejected(self, api):
        """PRD §3.8: "school_year (formatted YYYY-YYYY, with the second
        four-digit year exactly one greater than the first)."

        Claim: 2026-2028 (gap not 1) yields ERR_VALIDATION.
        """
        patient = create_patient()
        res = api.create_certificate(
            patient["id"],
            create_certificate_payload(school_year="2026-2028"),
            TEST_USERS["school_registrar_headers"],
        )
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# §3.8 Coverage evaluation: ISSUED vs DEFICIENT vs EXEMPTION_GRANTED
# ===========================================================================
class TestCoverageEvaluation:

    def test_issue_with_full_coverage_becomes_issued(self, api):
        """PRD §3.8: "if missing_antigens evaluates to empty,
        certificate_status becomes ISSUED and issued_at is stamped."

        Claim: when every required antigen is covered by an
        ADMINISTERED dose, /issue produces certificate_status ==
        'ISSUED' with issued_at non-null and missing_antigens == [].
        """
        ctx = setup_school_required_full_set()
        # Administer one of each.
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_mmr"]["id"],
            ctx["lot_mmr"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_dtap"]["id"],
            ctx["lot_dtap"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(seconds=1),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_hepb"]["id"],
            ctx["lot_hepb"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(seconds=2),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        cert = create_certificate(ctx["patient"]["id"])
        issued = issue_certificate(ctx["patient"]["id"], cert["id"])
        assert issued["certificate_status"] == "ISSUED"
        assert issued["missing_antigens"] == []
        assert issued.get("issued_at"), (
            "PRD §3.8: issued_at must be stamped on ISSUED"
        )

    def test_issue_with_missing_antigens_becomes_deficient(self, api):
        """PRD §3.8: "Otherwise, certificate_status becomes DEFICIENT,
        missing_antigens retains the sorted list of uncovered antigens,
        and issued_at remains null."

        Claim: when required antigens are uncovered, /issue produces
        DEFICIENT with sorted missing_antigens.
        """
        ctx = setup_school_required_full_set()
        # Administer only MMR; DTAP and HEPB still uncovered.
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_mmr"]["id"],
            ctx["lot_mmr"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        cert = create_certificate(ctx["patient"]["id"])
        issued = issue_certificate(ctx["patient"]["id"], cert["id"])
        assert issued["certificate_status"] == "DEFICIENT"
        assert issued.get("issued_at") is None
        # PRD §3.8: "sorted alphabetically ascending."
        ma = issued["missing_antigens"]
        assert ma == sorted(ma), (
            f"PRD §3.8: missing_antigens must be sorted asc, got {ma!r}"
        )
        assert "DTAP_DIPHTHERIA" in ma
        assert "HEPB" in ma


# ===========================================================================
# §3.8 Exemption wins
# ===========================================================================
class TestExemption:
    """PRD §3.8: "If medical_exemption_on_file on the patient is true,
    the certificate's certificate_status becomes EXEMPTION_GRANTED,
    missing_antigens is set to the empty array, and issued_at is
    stamped."
    """

    # difficulty: combinatorial_formula/school_coverage_circular_evaluation_order
    def test_exemption_grants_with_empty_missing_antigens(self, api):
        """PRD §3.8: exemption shortcut.

        Claim: a patient with medical_exemption_on_file=true and NO
        administered doses, against a fully-required schedule, produces
        EXEMPTION_GRANTED with missing_antigens == []. This pins the
        evaluation order (exemption first) over the alternate ordering
        that would compute missing_antigens before applying exemption.

        # difficulty: combinatorial_formula/school_coverage_circular_evaluation_order
        """
        anchor_clock()
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0,
            routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
            school_enrollment_required=True,
        )
        patient = create_patient(medical_exemption_on_file=True)
        cert = create_certificate(patient["id"])
        issued = issue_certificate(patient["id"], cert["id"])
        assert issued["certificate_status"] == "EXEMPTION_GRANTED", (
            f"PRD §3.8: medical_exemption_on_file=true must produce "
            f"EXEMPTION_GRANTED, got {issued['certificate_status']!r}"
        )
        assert issued["missing_antigens"] == [], (
            "PRD §3.8: missing_antigens must be empty under exemption"
        )
        assert issued.get("issued_at"), (
            "PRD §3.8: issued_at must be stamped on EXEMPTION_GRANTED"
        )

    # difficulty: combinatorial_formula/school_coverage_circular_evaluation_order
    def test_exemption_wins_over_issued_when_both_apply(self, api):
        """PRD §3.8: "Exemption suppresses the coverage requirement
        entirely - it wins over ISSUED when both could theoretically
        apply."

        Claim: even if the patient has all required antigens covered,
        an exemption flag still produces EXEMPTION_GRANTED (not ISSUED).

        # difficulty: combinatorial_formula/school_coverage_circular_evaluation_order
        """
        ctx = setup_school_required_full_set(medical_exemption_on_file=True)
        # Administer all three required antigens (so coverage is also
        # complete).
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_mmr"]["id"],
            ctx["lot_mmr"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_dtap"]["id"],
            ctx["lot_dtap"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(seconds=1),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_hepb"]["id"],
            ctx["lot_hepb"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(seconds=2),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        cert = create_certificate(ctx["patient"]["id"])
        issued = issue_certificate(ctx["patient"]["id"], cert["id"])
        assert issued["certificate_status"] == "EXEMPTION_GRANTED", (
            f"PRD §3.8: EXEMPTION_GRANTED must win over ISSUED, "
            f"got {issued['certificate_status']!r}"
        )


# ===========================================================================
# §3.8 Empty required-set boundary (difficulty design)
# ===========================================================================
class TestEmptyRequiredSetBoundary:
    """Difficulty design: empty_required_antigen_set_school_coverage.
    PRD §3.8: when no rule has school_enrollment_required=true,
    required_antigens is empty -> missing_antigens is [] -> ISSUED.
    """

    # difficulty: boundary_precision_check/empty_required_antigen_set_school_coverage
    def test_no_required_antigens_yields_issued(self, api):
        """PRD §3.8: "if missing_antigens evaluates to empty,
        certificate_status becomes ISSUED."

        Claim: with exactly one AntigenScheduleRule whose
        school_enrollment_required is FALSE (so required_antigens is
        empty), issuing a certificate for a patient with no doses
        yields ISSUED with missing_antigens == [].

        # difficulty: boundary_precision_check/empty_required_antigen_set_school_coverage
        """
        anchor_clock()
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0,
            routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
            school_enrollment_required=False,
        )
        patient = create_patient(medical_exemption_on_file=False)
        cert = create_certificate(patient["id"])
        issued = issue_certificate(patient["id"], cert["id"])
        assert issued["certificate_status"] == "ISSUED", (
            f"PRD §3.8: empty required_antigens means vacuously covered "
            f"-> ISSUED, got {issued['certificate_status']!r}"
        )
        assert issued["missing_antigens"] == []

    # difficulty: boundary_precision_check/empty_required_antigen_set_school_coverage
    def test_no_rules_at_all_yields_issued(self, api):
        """PRD §3.8: "The system first computes the required antigen
        set as the antigens of every AntigenScheduleRule whose
        school_enrollment_required is true."
        PRD §3.8: "if missing_antigens evaluates to empty,
        certificate_status becomes ISSUED."

        Claim: with NO AntigenScheduleRule rows at all
        (required_antigens trivially empty), /issue still yields
        ISSUED with missing_antigens == [].

        # difficulty: boundary_precision_check/empty_required_antigen_set_school_coverage
        """
        anchor_clock()
        patient = create_patient(medical_exemption_on_file=False)
        cert = create_certificate(patient["id"])
        issued = issue_certificate(patient["id"], cert["id"])
        assert issued["certificate_status"] == "ISSUED", (
            f"PRD §3.8: empty required_antigens (no rules) -> ISSUED, "
            f"got {issued['certificate_status']!r}"
        )
        assert issued["missing_antigens"] == []


# ===========================================================================
# §3.8 / §3.3 Auto-promote DEFICIENT -> ISSUED on later administer
# ===========================================================================
class TestCertificateAutoPromote:

    # difficulty: non_linear_state_machine/school_certificate_branching_with_revert
    def test_deficient_certificate_auto_promotes_after_admin(self, api):
        """PRD §3.8: "A certificate already in DEFICIENT state may
        auto-bubble up to ISSUED when a later dose administration
        causes the recompute (run automatically at administer time,
        see §3.3) to find missing_antigens empty - the system stamps
        issued_at at that moment."

        Claim: a DEFICIENT certificate becomes ISSUED after the patient
        receives an administered dose that covers the only missing
        antigen.

        # difficulty: non_linear_state_machine/school_certificate_branching_with_revert
        """
        ctx = setup_school_required_full_set()
        # Issue cert before any admin -> DEFICIENT with all three missing.
        cert = create_certificate(ctx["patient"]["id"])
        deficient = issue_certificate(ctx["patient"]["id"], cert["id"])
        assert deficient["certificate_status"] == "DEFICIENT"
        # Administer all three antigens.
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_mmr"]["id"],
            ctx["lot_mmr"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_dtap"]["id"],
            ctx["lot_dtap"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(seconds=1),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_hepb"]["id"],
            ctx["lot_hepb"]["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(seconds=2),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        cert_after = re_get_certificate(
            ctx["patient"]["id"], cert["id"],
        )
        assert cert_after["certificate_status"] == "ISSUED", (
            "PRD §3.8 / §3.3: DEFICIENT certificate must auto-promote "
            "to ISSUED when coverage becomes complete"
        )
        assert cert_after["missing_antigens"] == []


# ===========================================================================
# §3.8 Revoke
# ===========================================================================
class TestRevokeCertificate:

    @pytest.mark.parametrize("setup_status", ["ISSUED", "DEFICIENT"])
    def test_revoke_terminal_from_various_states(self, api, setup_status):
        """PRD §3.8: "A SchoolRegistrar may revoke a certificate from
        ISSUED, DEFICIENT, or EXEMPTION_GRANTED into the terminal
        REVOKED state; revocation has no further side effects."

        Claim: /revoke from each of these states sets
        certificate_status == 'REVOKED'.
        """
        ctx = setup_school_required_full_set()
        cert = create_certificate(ctx["patient"]["id"])
        if setup_status == "ISSUED":
            schedule_and_administer_dose(
                ctx["patient"]["id"], ctx["product_mmr"]["id"],
                ctx["lot_mmr"]["id"], ctx["provider_org"]["id"],
                administered_at=iso_anchor_offset(),
                administering_clinician_id=PROVIDER_CLINICIAN_ID,
            )
            schedule_and_administer_dose(
                ctx["patient"]["id"], ctx["product_dtap"]["id"],
                ctx["lot_dtap"]["id"], ctx["provider_org"]["id"],
                administered_at=iso_anchor_offset(seconds=1),
                administering_clinician_id=PROVIDER_CLINICIAN_ID,
            )
            schedule_and_administer_dose(
                ctx["patient"]["id"], ctx["product_hepb"]["id"],
                ctx["lot_hepb"]["id"], ctx["provider_org"]["id"],
                administered_at=iso_anchor_offset(seconds=2),
                administering_clinician_id=PROVIDER_CLINICIAN_ID,
            )
            # PRD §3.3: dose administration recompute auto-bubbles any
            # DRAFT/DEFICIENT cert to ISSUED when missing_antigens is
            # empty. So after the third dose the cert is already ISSUED;
            # re-read rather than calling /issue (which would 409).
            cert = re_get_certificate(ctx["patient"]["id"], cert["id"])
            assert cert["certificate_status"] == "ISSUED"
        elif setup_status == "DEFICIENT":
            cert = issue_certificate(ctx["patient"]["id"], cert["id"])
            assert cert["certificate_status"] == "DEFICIENT"
        res = api.revoke_certificate(
            ctx["patient"]["id"], cert["id"],
            TEST_USERS["school_registrar_headers"],
        )
        data = validate_success(res)
        assert data["certificate_status"] == "REVOKED"

    def test_revoke_exemption_granted(self, api):
        """PRD §3.8: revoke from EXEMPTION_GRANTED is allowed.

        Claim: /revoke on an EXEMPTION_GRANTED certificate ->
        REVOKED.
        """
        anchor_clock()
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0,
            routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
            school_enrollment_required=True,
        )
        patient = create_patient(medical_exemption_on_file=True)
        cert = create_certificate(patient["id"])
        cert = issue_certificate(patient["id"], cert["id"])
        assert cert["certificate_status"] == "EXEMPTION_GRANTED"
        res = api.revoke_certificate(
            patient["id"], cert["id"],
            TEST_USERS["school_registrar_headers"],
        )
        data = validate_success(res)
        assert data["certificate_status"] == "REVOKED"


# ===========================================================================
# §3.8 / §2.6 priority 100: ERR_CERTIFICATE_DUPLICATE
# ===========================================================================
class TestCertificateUniqueness:

    def test_second_non_revoked_certificate_rejected(self, api):
        """PRD §3.8: "At most one certificate with certificate_status
        other than REVOKED may exist for a given (patient_id,
        school_year) pair; a second attempt is rejected with
        ERR_CERTIFICATE_DUPLICATE."

        Claim: creating a second certificate for the same
        (patient, school_year) yields ERR_CERTIFICATE_DUPLICATE.
        """
        patient = create_patient()
        create_certificate(patient["id"], school_year="2026-2027")
        res = api.create_certificate(
            patient["id"],
            create_certificate_payload(school_year="2026-2027"),
            TEST_USERS["school_registrar_headers"],
        )
        validate_error(res, "ERR_CERTIFICATE_DUPLICATE")

    def test_revoked_certificate_allows_new_certificate(self, api):
        """PRD §3.8: "with certificate_status other than REVOKED."

        Claim: after revoking the first cert, a new cert for the same
        (patient, school_year) is allowed.

        PRD §3.8: revoke is only permitted from ISSUED, DEFICIENT, or
        EXEMPTION_GRANTED. The test first issues a draft cert (which
        becomes DEFICIENT or ISSUED depending on coverage), then
        revokes it, then attempts to create a new draft for the same
        (patient, school_year).
        """
        anchor_clock()
        patient = create_patient()
        cert1 = create_certificate(patient["id"], school_year="2026-2027")
        # Move cert1 out of DRAFT (issue runs school-coverage evaluation;
        # with no schedule rules the patient is trivially covered so it
        # lands at ISSUED).
        issue_certificate(patient["id"], cert1["id"])
        api.revoke_certificate(
            patient["id"], cert1["id"],
            TEST_USERS["school_registrar_headers"],
        )
        res = api.create_certificate(
            patient["id"],
            create_certificate_payload(school_year="2026-2027"),
            TEST_USERS["school_registrar_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["certificate_status"] == "DRAFT"
