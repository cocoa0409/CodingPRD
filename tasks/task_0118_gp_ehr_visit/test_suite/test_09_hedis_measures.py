"""HEDIS measurement: AWV, CBP, TSC, CCS — provisional vs final freeze.

PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CBP_DIASTOLIC_CEIL,
    CBP_SYSTOLIC_CEIL,
    advance_clock_to,
    anchor_clock,
    hedis_recompute_payload,
    setup_encounter_with_preventive_lines,
    setup_patient_for_tsc_provisional_vs_final,
    setup_two_patients_for_cbp_boundary,
    TEST_USERS,
    validate_paginated,
    validate_success,
)


def _find_measure(rows, measure_id):
    """Helper: find a HEDIS measurement row by measure_id."""
    for row in rows:
        if row.get("measure_id") == measure_id:
            return row
    return None


# ===========================================================================
# §3.8 CBP boundary precision: bp_systolic < 140 strict
# ===========================================================================
class TestCbpSystolicBoundary:

    # difficulty: boundary_precision_check/hedis_cbp_systolic_140_exclusive_boundary
    def test_cbp_systolic_139_passes_numerator(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.8: "The numerator is met when the denominator is
        met and the patient's most recent COMPLETED encounter in the
        year has both vital_signs.bp_systolic strictly less than 140
        and vital_signs.bp_diastolic strictly less than 90."

        Claim: a CBP-eligible patient (age 50, I10 in
        chronic_conditions, ACTIVE) with most-recent COMPLETED
        encounter showing bp_systolic=139, bp_diastolic=89 has
        in_numerator==true (139 < 140, 89 < 90).
        """
        setup = setup_two_patients_for_cbp_boundary()
        patient_a = setup["patient_a"]
        # Run HEDIS recompute for 2026.
        res = api.hedis_recompute(
            hedis_recompute_payload(
                year=2026, patient_ids=[patient_a["id"]],
            ),
            clinic_admin_headers,
        )
        body = validate_success(res)
        # Response shape may be a list of measurements or paginated.
        rows = body if isinstance(body, list) else [body]
        # Now read back via the GET.
        get_res = api.get_hedis_measurements(
            patient_a["id"], 2026,
            TEST_USERS["clinic_admin_headers"],
        )
        get_body = validate_success(get_res)
        rows = get_body if isinstance(get_body, list) else [get_body]
        cbp = _find_measure(rows, "CBP")
        assert cbp is not None, (
            "CBP measure row must be present for an I10-coded "
            "patient after the HEDIS recompute"
        )
        assert cbp["in_denominator"] is True
        assert cbp["in_numerator"] is True, (
            "Patient A with bp_systolic=139 must satisfy CBP numerator"
        )

    # difficulty: boundary_precision_check/hedis_cbp_systolic_140_exclusive_boundary
    def test_cbp_systolic_140_fails_numerator(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.8: "The numerator is met when the denominator is
        met and the patient's most recent COMPLETED encounter in the
        year has both vital_signs.bp_systolic strictly less than 140
        and vital_signs.bp_diastolic strictly less than 90."

        Claim: a CBP-eligible patient whose most-recent encounter
        has bp_systolic=140 fails the numerator (140 is NOT < 140).
        """
        setup = setup_two_patients_for_cbp_boundary()
        patient_b = setup["patient_b"]
        api.hedis_recompute(
            hedis_recompute_payload(
                year=2026, patient_ids=[patient_b["id"]],
            ),
            clinic_admin_headers,
        )
        get_res = api.get_hedis_measurements(
            patient_b["id"], 2026,
            TEST_USERS["clinic_admin_headers"],
        )
        body = validate_success(get_res)
        rows = body if isinstance(body, list) else [body]
        cbp = _find_measure(rows, "CBP")
        assert cbp is not None
        assert cbp["in_denominator"] is True
        assert cbp["in_numerator"] is False, (
            "Patient B with bp_systolic=140 must fail the CBP "
            "strict < 140 numerator"
        )


# ===========================================================================
# §3.8 AWV — preventive line drives numerator via cascade
# ===========================================================================
class TestAwvCascadeFromEncounterCompletion:

    # difficulty: transitive_cascade/encounter_complete_to_cpt_allowed_to_hedis_snapshot
    def test_complete_physical_with_preventive_line_marks_awv_numerator(
        self, api,
    ):
        """PRD §3.8: "AWV ... The numerator is met when the
        denominator is met and at least one COMPLETED encounter
        exists in the measurement year that has at least one
        CptLineItem whose snapshotted is_preventive is true."

        PRD §3.3: "the server recomputes the patient's
        HedisMeasurement rows for the current calendar year, but
        only for the AWV and CBP measures."

        Claim: after the cascade fires on encounter completion (with
        a preventive line attached), the AWV in-numerator boolean is
        true for the patient and current year.
        """
        setup = setup_encounter_with_preventive_lines()
        patient = setup["patient"]
        encounter = setup["encounter"]
        provider = setup["provider"]
        # Complete the encounter (the setup left it CHECKED_IN with
        # vitals patched and both line items attached).
        from test_helpers import complete_encounter
        completed = complete_encounter(encounter["id"], provider["id"])
        assert completed["status"] == "COMPLETED"
        # GET the HEDIS measurements for 2026 (the encounter date).
        get_res = api.get_hedis_measurements(
            patient["id"], 2026,
            TEST_USERS["clinic_admin_headers"],
        )
        body = validate_success(get_res)
        rows = body if isinstance(body, list) else [body]
        awv = _find_measure(rows, "AWV")
        # The cascade writes/updates AWV; PRD §3.3 commits to AWV +
        # CBP recompute on completion of the current-year encounter.
        assert awv is not None, (
            "AWV measure row must be present after encounter "
            "completion in the same calendar year"
        )
        assert awv["in_denominator"] is True, (
            "Patient age 30+, ACTIVE, must be in AWV denominator"
        )
        assert awv["in_numerator"] is True, (
            "Patient has a COMPLETED current-year encounter with a "
            "preventive line ⇒ AWV in_numerator must be true"
        )

    # difficulty: transitive_cascade/encounter_complete_to_cpt_allowed_to_hedis_snapshot
    def test_completion_without_preventive_line_does_not_satisfy_awv(
        self, api,
    ):
        """PRD §3.8: "AWV ... The numerator is met when the
        denominator is met and at least one COMPLETED encounter
        exists in the measurement year that has at least one
        CptLineItem whose snapshotted is_preventive is true."

        Claim: a COMPLETED encounter whose only line item is NOT
        preventive does NOT satisfy the AWV numerator.
        """
        anchor_clock()
        advance_clock_to("2026-06-15T10:00:00.000Z")
        from test_helpers import (
            create_pcp_provider, create_patient, bind_patient_to_pcp,
            schedule_encounter, checkin_encounter,
            create_cpt_code_entry, add_cpt_line_item,
            complete_encounter, iso_anchor_offset,
            patch_encounter_vitals,
        )
        provider = create_pcp_provider()
        patient = create_patient(
            date_of_birth="1995-06-15",  # 31 in 2026
            sex_at_birth="MALE",
        )
        patient = bind_patient_to_pcp(patient["id"], provider["id"])
        e = schedule_encounter(
            patient["id"], provider["id"],
            encounter_type="PHYSICAL",
            scheduled_start="2026-06-15T11:00:00.000Z",
            scheduled_end="2026-06-15T11:30:00.000Z",
            chief_complaint="Physical without preventive code",
        )
        advance_clock_to("2026-06-15T10:50:00.000Z")
        e = checkin_encounter(e["id"])
        e = patch_encounter_vitals(e["id"])
        cpt_nonprev = create_cpt_code_entry(
            cpt_code="99214", list_price_cents=12000,
            allowed_price_cents=8000, is_preventive=False,
        )
        add_cpt_line_item(e["id"], cpt_nonprev["cpt_code"], units=1)
        e = complete_encounter(e["id"], provider["id"])
        get_res = api.get_hedis_measurements(
            patient["id"], 2026, TEST_USERS["clinic_admin_headers"],
        )
        body = validate_success(get_res)
        rows = body if isinstance(body, list) else [body]
        awv = _find_measure(rows, "AWV")
        assert awv is not None, "AWV row should exist"
        assert awv["in_denominator"] is True, (
            "Patient is age 31, ACTIVE ⇒ in AWV denominator"
        )
        assert awv["in_numerator"] is False, (
            "Encounter has no preventive line ⇒ AWV in_numerator "
            "must be false"
        )


# ===========================================================================
# §3.8 TSC provisional vs final-year-end variants
# ===========================================================================
class TestTscProvisionalVsFinal:

    # difficulty: dual_variant_calc/hedis_provisional_ytd_vs_final_year_end_on_patient
    def test_tsc_provisional_current_smoker_without_99406(
        self, api,
    ):
        """PRD §3.8: "TSC ... The numerator is met when the
        denominator is met, the patient's smoking_status is in the
        set {NEVER, FORMER, CURRENT}, and additionally, if the
        smoking status is CURRENT, at least one CONSULTATION
        encounter exists in the measurement year carrying a
        CptLineItem with cpt_code equal to either 99406 or 99407."

        PRD §3.8: "Provisional, year-to-date. Used when the HEDIS
        read endpoint is called with the as_of query parameter equal
        to YTD. Looks only at COMPLETED encounters whose actual_end
        is at or before the current server time. The denominator's
        status check uses the patient's status and smoking_status
        as they are right now rather than as they will be on
        December 31."

        Claim: at YTD time (Nov 2026), a patient with
        smoking_status=CURRENT whose 2026 encounter has neither
        99406 nor 99407 fails the TSC numerator on the YTD read.
        """
        setup = setup_patient_for_tsc_provisional_vs_final()
        patient = setup["patient"]
        get_res = api.get_hedis_measurements(
            patient["id"], 2026,
            TEST_USERS["clinic_admin_headers"],
            params={"as_of": "YTD"},
        )
        body = validate_success(get_res)
        rows = body if isinstance(body, list) else [body]
        tsc = _find_measure(rows, "TSC")
        assert tsc is not None, (
            "TSC row should appear in the YTD provisional response"
        )
        assert tsc["in_numerator"] is False, (
            "Provisional TSC with CURRENT smoker and no 99406/99407 "
            "in the year must fail the numerator"
        )

    # difficulty: dual_variant_calc/hedis_provisional_ytd_vs_final_year_end_on_patient
    def test_tsc_final_after_smoking_status_flips_to_former(
        self, api,
    ):
        """PRD §3.8: "Final, year-end freeze. ... The denominator
        status check uses the patient's status and smoking_status
        as of December 31."

        Claim: the same patient, after PATCHing smoking_status to
        FORMER late in the year, has TSC in_numerator==true on the
        final-year-end freeze (smoking_status pinned to Dec 31 is
        FORMER, which is in {NEVER, FORMER, CURRENT}; the 99406
        consultation requirement applies only when smoking_status
        is CURRENT at the freeze point).
        """
        setup = setup_patient_for_tsc_provisional_vs_final()
        patient = setup["patient"]
        # PATCH smoking_status to FORMER (allowed by PRD §3.1).
        from test_helpers import patch_patient_payload
        patch_res = api.patch_patient(
            patient["id"],
            patch_patient_payload(smoking_status="FORMER"),
            TEST_USERS["nurse_headers"],
        )
        validate_success(patch_res)
        # Advance clock past year-end and run the recompute action.
        advance_clock_to("2027-01-02T00:00:00.000Z")
        api.hedis_recompute(
            hedis_recompute_payload(
                year=2026, patient_ids=[patient["id"]],
            ),
            TEST_USERS["clinic_admin_headers"],
        )
        get_res = api.get_hedis_measurements(
            patient["id"], 2026,
            TEST_USERS["clinic_admin_headers"],
        )
        body = validate_success(get_res)
        rows = body if isinstance(body, list) else [body]
        tsc = _find_measure(rows, "TSC")
        assert tsc is not None
        # PRD: with smoking_status pinned to FORMER on Dec 31, the
        # special CURRENT-only 99406/99407 requirement does NOT
        # apply, so the patient (FORMER, with a COMPLETED visit in
        # the year) satisfies the numerator.
        assert tsc["in_numerator"] is True, (
            "Final TSC with smoking_status=FORMER on Dec 31 must "
            "satisfy the numerator (FORMER is in the qualifying set "
            "and no 99406/99407 requirement applies)"
        )
