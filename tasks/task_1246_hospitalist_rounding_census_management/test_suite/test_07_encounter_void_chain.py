"""Encounter void cascade: void reopens FINALIZED report and recomputes
totals; double-void rejection; void+re-record conservation invariant.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_encounter_for,
    generate_report,
)

ADMIN = TEST_USERS["group_admin_headers"]


def _finalized_report_two_encounters(api, p_mrn="M801"):
    """H1; P1; E1 ADMISSION_HCP 2.654 + E2 SUBSEQUENT_VISIT 1.115 on 2026-05-04;
    report 2026-05-01..2026-05-31 FINALIZED."""
    set_clock("2026-05-04T12:00:00Z")
    h = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
    p = create_patient(mrn=p_mrn, acuity="MEDIUM", admit_source="DIRECT",
                       stay_type="INPATIENT", admitted_at="2026-05-04T08:00:00Z")
    e1 = create_encounter_for(p["id"], h["id"], "ADMISSION_HCP", "2026-05-04", 2.654)
    e2 = create_encounter_for(p["id"], h["id"], "SUBSEQUENT_VISIT", "2026-05-04", 1.115)
    r = generate_report(h["id"], "2026-05-01", "2026-05-31")
    fin = get_success_data(api.finalize_productivity_report(r["id"], ADMIN))
    assert fin["status"] == "FINALIZED"
    assert fin["total_wrvu_final"] == pytest.approx(3.77, abs=0.001)
    return h, p, e1, e2, fin


class TestEncounterVoidReopensReportChain:
    """Difficulty instance: encounter_void_reopens_report_chain."""

    def test_void_flips_finalized_to_reopened(self, api):
        """PRD §3.8: "when `productivity_report_id` names a `FINALIZED`
        report, the report drops `FINALIZED` → `REOPENED` and its totals
        recompute excluding the voided line, with the report's `version`
        incrementing alongside the encounter's".
        PRD §3.8: "Voiding moves `RECORDED` → `VOIDED`, terminal".

        Design: Difficulty/transitive_cascade/encounter_void_reopens_report_chain
        """
        h, p, e1, e2, fin = _finalized_report_two_encounters(api)
        void_resp = get_success_data(api.void_encounter(
            e1["id"], make_hospitalist_headers(h["id"])
        ))
        assert void_resp["status"] == "VOIDED"
        r_now = get_success_data(api.get_productivity_report(fin["id"], ADMIN))
        assert r_now["status"] == "REOPENED"

    def test_void_recomputes_totals_excluding_voided(self, api):
        """PRD §3.8: "its totals recompute excluding the voided line".
        PRD §3.8: "`total_wrvu_provisional`, the sum of the per-line
        `estimated_wrvu` values — per-line rounding first, summation second."
        PRD §3.8: "the raw `wrvu_value` figures across the linked `RECORDED`
        set are summed first and the total is rounded once".

        Design: Difficulty/transitive_cascade/encounter_void_reopens_report_chain
        """
        h, p, e1, e2, fin = _finalized_report_two_encounters(api)
        api.void_encounter(e1["id"], make_hospitalist_headers(h["id"]))
        r_now = get_success_data(api.get_productivity_report(fin["id"], ADMIN))
        # Only E2 (SUBSEQUENT_VISIT 1.115, est 1.27) remains
        assert r_now["total_wrvu_provisional"] == pytest.approx(1.27, abs=0.001)
        # final: round(1.115, 2) = 1.12 (1.115 rounds half up to 1.12)
        assert r_now["total_wrvu_final"] == pytest.approx(1.12, abs=0.001)
        assert r_now["wrvu_variance"] == pytest.approx(-0.15, abs=0.001)


class TestVoidRerecordConservesFinalWrvu:
    """Difficulty instance: void_rerecord_conserves_final_wrvu."""

    def test_void_leaves_report_reopened(self, api):
        """PRD §3.8: "when `productivity_report_id` names a `FINALIZED`
        report, the report drops `FINALIZED` → `REOPENED`".

        Design: Difficulty/compensating_invariant/void_rerecord_conserves_final_wrvu
        """
        h, p, e1, e2, fin = _finalized_report_two_encounters(api, p_mrn="M971")
        api.void_encounter(e1["id"], make_hospitalist_headers(h["id"]))
        r_now = get_success_data(api.get_productivity_report(fin["id"], ADMIN))
        assert r_now["status"] == "REOPENED"

    def test_void_identical_rerecord_finalize_conserves_totals(self, api):
        """PRD §3.8: "Across the full compensating sequence one conservation
        property holds: for a `FINALIZED` report, voiding an encounter,
        re-recording an identical one (same `encounter_type`, `occurred_on`,
        and `wrvu_value`), and refinalizing leaves both `total_wrvu_final`
        and `total_wrvu_provisional` equal to their pre-void values."
        PRD §3.8: "on a `REOPENED` → `FINALIZED` pass, every currently
        `RECORDED` in-period encounter is linked, including any recorded
        after the first finalize".

        Design: Difficulty/compensating_invariant/void_rerecord_conserves_final_wrvu
        """
        h, p, e1, e2, fin = _finalized_report_two_encounters(api, p_mrn="M972")
        before_final = fin["total_wrvu_final"]
        before_prov = fin["total_wrvu_provisional"]

        api.void_encounter(e1["id"], make_hospitalist_headers(h["id"]))
        # Re-record identical encounter
        e1b = create_encounter_for(p["id"], h["id"], "ADMISSION_HCP", "2026-05-04", 2.654)
        fin2 = get_success_data(api.finalize_productivity_report(fin["id"], ADMIN))
        assert fin2["status"] == "FINALIZED"
        assert fin2["total_wrvu_final"] == pytest.approx(before_final, abs=0.001)
        assert fin2["total_wrvu_provisional"] == pytest.approx(before_prov, abs=0.001)
        # Re-linked on refinalize
        e1b_now = get_success_data(api.get_encounter(e1b["id"], ADMIN))
        assert e1b_now["productivity_report_id"] == fin["id"]


class TestEncounterVoidTwiceRejected:
    """Corner instance: encounter_void_twice_rejected."""

    def test_second_void_fails(self, api):
        """PRD §3.8: "voiding an already-`VOIDED` encounter fails with
        `ERR_ENCOUNTER_ALREADY_VOIDED` (HTTP 409)."

        Design: Corner/state_machines/encounter_void_twice_rejected
        """
        h = create_hospitalist("H One", "ICU", max_census_cap=16)
        p = create_patient(mrn="S006", acuity="LOW", admit_source="DIRECT",
                           stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        e1 = create_encounter_for(p["id"], h["id"], "SUBSEQUENT_VISIT", "2026-05-01", 1.2)
        get_success_data(api.void_encounter(e1["id"], make_hospitalist_headers(h["id"])))
        resp = api.void_encounter(e1["id"], make_hospitalist_headers(h["id"]))
        validate_error(resp, ApiErrorId.ERR_ENCOUNTER_ALREADY_VOIDED)
        e_now = get_success_data(api.get_encounter(e1["id"], ADMIN))
        assert e_now["status"] == "VOIDED"


class TestReportFinalizeFromFinalizedRejected:
    """Corner instance: report_finalize_from_finalized_rejected."""

    def test_finalize_on_finalized_fails(self, api):
        """PRD §3.8: "Finalization moves `PROVISIONAL` → `FINALIZED` — or,
        after a reopen, `REOPENED` → `FINALIZED` — and from any other state
        fails with `ERR_REPORT_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/report_finalize_from_finalized_rejected
        """
        h = create_hospitalist("H One", "ICU", max_census_cap=16)
        r = generate_report(h["id"], "2026-05-01", "2026-05-31")
        get_success_data(api.finalize_productivity_report(r["id"], ADMIN))
        resp = api.finalize_productivity_report(r["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE)
        r_now = get_success_data(api.get_productivity_report(r["id"], ADMIN))
        assert r_now["status"] == "FINALIZED"
