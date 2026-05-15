"""Isolation lifecycle — PRD §3.4."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_facility,
    assert_facility_occupancy_invariant,
    assert_isolation,
    create_facility,
    create_isolation_for_person,
    create_isolation_payload,
    create_person,
    daily_report_payload,
    file_case,
    iso_utc_midnight,
    make_cdc_tracer_headers,
    make_hospital_reporter_headers,
    release_isolation,
    setup_centralized_isolation,
    setup_district_with_cdc,
    setup_district_with_hospital_and_cdc,
    setup_isolation_releasable_via_home_mode,
    validate_error,
    validate_success,
    violate_isolation,
)


# ===========================================================================
# Isolation creation — PRD §3.4
# ===========================================================================
class TestIsolationCreation:

    def test_home_mode_isolation_defaults(self, api):
        """PRD §3.4: "The isolation enters ACTIVE with extension_count,
        daily_reports_received, and violations_count all initialized to
        zero, and actual_end_date left unset until termination."

        Claim: a HOME-mode Isolation starts in ACTIVE with all three
        counters at zero.
        """
        region, cdc = setup_district_with_cdc(district_code="D-ISO-1")
        person = create_person(district_code=region["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=cdc["id"], mode="HOME",
        )
        assert_isolation(iso)
        assert iso["status"] == "ACTIVE"
        assert iso["extension_count"] == 0
        assert iso["daily_reports_received"] == 0
        assert iso["violations_count"] == 0
        assert iso["mode"] == "HOME"

    def test_centralized_admission_increments_facility_occupied(self, api):
        """PRD §3.4: "On a successful centralized admission, occupied is
        incremented, the person's isolation_status is set to ACTIVE,
        and if the increment causes occupied to equal capacity the
        facility transitions to FULL."

        Claim: after a CENTRALIZED admission, facility.occupied == 1.
        """
        ctx = setup_centralized_isolation(
            cdc_id="not-used",  # overridden inside the helper
            facility_capacity=3,
        )
        # Re-fetch facility to observe the increment.
        # ctx['cdc_id'] is "not-used" in this fixture invocation — we
        # rebuild without using setup_centralized_isolation. Instead, do
        # it manually so the headers thread correctly.
        region, cdc = setup_district_with_cdc(district_code="D-ISO-2B")
        facility = create_facility(
            district_code=region["district_code"], capacity=3,
        )
        person = create_person(district_code=region["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=cdc["id"],
            mode="CENTRALIZED", facility_id=facility["id"],
        )
        assert iso["status"] == "ACTIVE"
        assert iso["mode"] == "CENTRALIZED"
        assert iso["facility_id"] == facility["id"]
        fac = validate_success(api.get_facility(
            facility["id"],
            make_cdc_tracer_headers(cdc["id"]),
        ))
        assert_facility(fac)
        assert fac["occupied"] == 1, (
            "PRD §3.4: 'occupied is incremented' on centralized admission"
        )
        assert_facility_occupancy_invariant(fac)

    def test_full_facility_blocks_additional_centralized_admission(self, api):
        """PRD §3.4: "Centralized admission additionally checks the
        facility: the facility must have status equal to OPEN and
        occupied strictly less than capacity. Failing that, the request
        is rejected with ERR_FACILITY_AT_CAPACITY."

        Claim: an admission into a facility whose occupied == capacity
        is rejected with ERR_FACILITY_AT_CAPACITY.
        # difficulty: resource_temporal_overlap/isolation_facility_aggregate_capacity
        """
        region, cdc = setup_district_with_cdc(district_code="D-ISO-3")
        facility = create_facility(
            district_code=region["district_code"], capacity=2,
        )
        # Fill the facility.
        for _ in range(2):
            p = create_person(district_code=region["district_code"])
            create_isolation_for_person(
                person_id=p["id"], cdc_id=cdc["id"],
                mode="CENTRALIZED", facility_id=facility["id"],
            )
        # Third attempt must be rejected.
        third = create_person(district_code=region["district_code"])
        payload = create_isolation_payload(
            person_id=third["id"], mode="CENTRALIZED",
            facility_id=facility["id"],
        )
        resp = api.create_isolation(
            payload, make_cdc_tracer_headers(cdc["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_AT_CAPACITY.value)
        # Invariant: occupied does not overflow.
        fac = validate_success(api.get_facility(
            facility["id"], make_cdc_tracer_headers(cdc["id"]),
        ))
        assert fac["occupied"] == 2

    def test_start_date_in_future_rejected(self, api):
        """PRD §3.4: "The start_date must not lie in the future ... is
        rejected with ERR_ISOLATION_DATE_INVALID."

        Claim: posting an Isolation with start_date strictly in the
        future → ERR_ISOLATION_DATE_INVALID.
        """
        region, cdc = setup_district_with_cdc(district_code="D-ISO-4")
        person = create_person(district_code=region["district_code"])
        future_date = iso_utc_midnight(
            datetime.now(timezone.utc) + timedelta(days=7),
        )
        payload = create_isolation_payload(
            person_id=person["id"], mode="HOME",
            start_date=future_date,
        )
        resp = api.create_isolation(
            payload, make_cdc_tracer_headers(cdc["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ISOLATION_DATE_INVALID.value)


# ===========================================================================
# Daily reports — PRD §3.4
# ===========================================================================
class TestDailyReports:

    def test_normal_report_is_not_abnormal(self, api):
        """PRD §3.4: "The server sets is_abnormal true exactly when
        temperature_c is at least the fever threshold or the symptoms
        list is non-empty."

        Claim: temperature 36.6 (below any reasonable fever threshold)
        with empty symptoms list → is_abnormal == false. We deliberately
        choose a temperature WELL below the explicit threshold so the
        boundary itself (which the PRD does not pin numerically) does
        not bite this test.
        """
        region, cdc = setup_district_with_cdc(district_code="D-DR-1")
        person = create_person(district_code=region["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=cdc["id"], mode="HOME",
        )
        resp = api.submit_daily_report(
            iso["id"],
            daily_report_payload(temperature_c=36.6, symptoms=[]),
            make_cdc_tracer_headers(cdc["id"]),
        )
        report = validate_success(resp, 201)
        assert report["is_abnormal"] is False
        # Side effect — counter increments.
        refreshed = validate_success(api.get_isolation(
            iso["id"], make_cdc_tracer_headers(cdc["id"]),
        ))
        assert refreshed["daily_reports_received"] == 1, (
            "PRD §3.4: 'increments daily_reports_received on the parent isolation'"
        )

    def test_report_with_symptoms_is_abnormal(self, api):
        """PRD §3.4: "The server sets is_abnormal true exactly when
        temperature_c is at least the fever threshold or the symptoms
        list is non-empty."

        Claim: a non-empty symptoms list (regardless of temperature) →
        is_abnormal == true.
        """
        region, cdc = setup_district_with_cdc(district_code="D-DR-2")
        person = create_person(district_code=region["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=cdc["id"], mode="HOME",
        )
        resp = api.submit_daily_report(
            iso["id"],
            daily_report_payload(
                temperature_c=36.4, symptoms=["COUGH"],
            ),
            make_cdc_tracer_headers(cdc["id"]),
        )
        report = validate_success(resp, 201)
        assert report["is_abnormal"] is True


# ===========================================================================
# Violation — PRD §3.4
# ===========================================================================
class TestViolation:

    def test_violation_transitions_to_violated_terminated(self, api):
        """PRD §3.4: "A successful violation increments violations_count,
        stamps actual_end_date, sets the person's isolation_status to
        VIOLATED_TERMINATED, transitions the isolation itself to
        VIOLATED_TERMINATED, and for centralized isolations decrements
        occupied."

        Claim: violation on an ACTIVE HOME isolation → status
        VIOLATED_TERMINATED with violations_count == 1.
        """
        region, cdc = setup_district_with_cdc(district_code="D-VIOL-1")
        person = create_person(district_code=region["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=cdc["id"], mode="HOME",
        )
        result = violate_isolation(iso["id"], cdc["id"])
        assert result["status"] == "VIOLATED_TERMINATED"
        assert result["violations_count"] == 1
        person_refreshed = validate_success(api.get_person(
            person["id"], make_cdc_tracer_headers(cdc["id"]),
        ))
        assert person_refreshed["isolation_status"] == "VIOLATED_TERMINATED"

    def test_violation_against_terminal_isolation_rejected(self, api):
        """PRD §3.4: "A violation can only be recorded against a
        non-terminal isolation (ACTIVE or EXTENDED); recording one
        against a terminal isolation is rejected with
        ERR_INVALID_STATE."

        Claim: a violation against a VIOLATED_TERMINATED isolation →
        ERR_INVALID_STATE.
        """
        region, cdc = setup_district_with_cdc(district_code="D-VIOL-2")
        person = create_person(district_code=region["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=cdc["id"], mode="HOME",
        )
        violate_isolation(iso["id"], cdc["id"])
        # Second violation should be rejected.
        resp = api.record_isolation_violation(
            iso["id"], {"reason": "second-breach"},
            make_cdc_tracer_headers(cdc["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Check-release — PRD §3.4
# ===========================================================================
class TestCheckRelease:

    def test_check_release_before_min_days_does_not_release(self, api):
        """PRD §3.4: "First, the elapsed whole-day count since
        start_date must be at least the minimum-days constant for the
        isolation's mode; if not, the outcome is NOT_ELIGIBLE."

        Claim: an Isolation whose elapsed days is less than the minimum
        for its mode is NOT released by the check-release call.
        """
        region, cdc = setup_district_with_cdc(district_code="D-CR-1")
        person = create_person(district_code=region["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=cdc["id"], mode="HOME",
        )
        # We have just created the isolation — no time has elapsed.
        result = release_isolation(iso["id"], cdc["id"])
        # The PRD requires the outcome to NOT be RELEASE. It does not
        # name a specific JSON field for the outcome other than the
        # state-machine status, so we assert via status.
        assert result["status"] != "RELEASED", (
            "PRD §3.4: with 0 days elapsed the release decision is "
            "NOT_ELIGIBLE and status must NOT become RELEASED"
        )

    def test_check_release_after_min_days_with_two_negative_pcr_releases(
        self, api,
    ):
        """PRD §3.4: "If all four checks pass, the outcome is RELEASE.
        ... a RELEASE outcome moves the isolation to its terminal
        status, stamps actual_end_date, sets the person's
        isolation_status to RELEASED."

        Claim: HOME mode after >= 10 elapsed days with two distinct-date
        NEGATIVE PCR tests and no abnormal reports → status RELEASED.
        # difficulty: combinatorial_formula/isolation_release_circular_dependency
        """
        ctx = setup_isolation_releasable_via_home_mode(
            days_isolated=11, test1_day=5, test2_day=9,
        )
        iso = ctx["isolation"]
        cdc_id = ctx["cdc"]["id"]
        result = release_isolation(iso["id"], cdc_id)
        assert result["status"] == "RELEASED", (
            f"PRD §3.4: with all four checks satisfied the outcome must "
            f"be RELEASE; got status={result['status']!r}"
        )
        person_refreshed = validate_success(api.get_person(
            ctx["person"]["id"],
            make_cdc_tracer_headers(cdc_id),
        ))
        assert person_refreshed["isolation_status"] == "RELEASED"
