"""Consent windows: the symmetric thirty-day buffer around a closed coverage interval."""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.fixtures import ANALYST, execute_consent, register_employee


FALK = {
    "full_name": "Greta Falk",
    "employee_number": "E-6801",
    "annual_salary_usd": 600_000.00,
    "officer_flag": False,
}


def _employee_with_august_window(api):
    """An employee whose only executed consent covers 2026-08-01 to 2026-08-31."""
    employee = register_employee(api, **FALK)
    consent = execute_consent(
        api,
        employee["id"],
        coverage_start_date="2026-08-01T00:00:00Z",
        coverage_end_date="2026-08-31T00:00:00Z",
        consent_form_reference="CF-9401-A",
    )
    return employee, consent


class TestConsentWindowBuffer:
    def test_a_gap_of_exactly_thirty_days_still_conflicts(self, api):
        """Thirty days of clearance is not enough clearance.

        "Two windows conflict when the new window's `coverage_start_date` falls
        on or before the existing window's `coverage_end_date` advanced by 30
        days, and at the same time the existing window's `coverage_start_date`
        falls on or before the new window's `coverage_end_date` advanced by 30
        days. Because both comparisons are inclusive, a gap of exactly 30 days
        between two windows still conflicts; a gap of 31 days is accepted. A
        conflict is rejected with `ERR_CONSENT_WINDOW_OVERLAP` (HTTP 409)." A
        window opening on 2026-09-30 sits exactly 30 days after the existing
        window closed, so it is refused and no record is written.

        Design: Difficulty/resource_temporal_overlap/consent_window_buffer_rejects_a_thirty_day_gap_and_accepts_thirty_one
        """
        employee, existing = _employee_with_august_window(api)

        validate_error(
            api.create_consent_record(
                {
                    "employee_id": employee["id"],
                    "coverage_start_date": "2026-09-30T00:00:00Z",
                    "coverage_end_date": "2027-08-31T00:00:00Z",
                    "consent_form_reference": "CF-9401-B",
                    "notice_and_consent_version": "NC-2026.1",
                },
                ANALYST,
            ),
            "ERR_CONSENT_WINDOW_OVERLAP",
            409,
        )

        items, _meta = validate_paginated(
            api.list_consent_records(ANALYST, params={"employee_id": employee["id"]})
        )
        references = [item["consent_form_reference"] for item in items]
        assert "CF-9401-B" not in references, "the refused window is not stored"
        assert len(items) == 1

        unchanged = validate_success(api.get_consent_record(existing["id"], ANALYST))
        assert unchanged["status"] == "EXECUTED", (
            "the refused creation leaves the signed window alone"
        )

    def test_a_gap_of_thirty_one_days_is_accepted_as_a_new_draft(self, api):
        """One more day of clearance clears the buffer on both sides.

        With the buffer satisfied the record is created the way any consent
        record is created: "The analyst creates it in `DRAFT` by supplying the
        `employee_id` giving notice and consent, the inclusive
        `coverage_start_date` and inclusive `coverage_end_date` of the interval,
        the `consent_form_reference` identifying the signed document, and the
        `notice_and_consent_version` tag of the template used; `executed_at`
        starts unset."

        Design: Difficulty/resource_temporal_overlap/consent_window_buffer_rejects_a_thirty_day_gap_and_accepts_thirty_one
        """
        employee, existing = _employee_with_august_window(api)

        created = validate_success(
            api.create_consent_record(
                {
                    "employee_id": employee["id"],
                    "coverage_start_date": "2026-10-01T00:00:00Z",
                    "coverage_end_date": "2027-09-30T00:00:00Z",
                    "consent_form_reference": "CF-9401-C",
                    "notice_and_consent_version": "NC-2026.1",
                },
                ANALYST,
            ),
            201,
        )
        assert created["status"] == "DRAFT"
        assert created["consent_form_reference"] == "CF-9401-C"
        assert created["executed_at"] is None

        items, meta = validate_paginated(
            api.list_consent_records(ANALYST, params={"employee_id": employee["id"]})
        )
        assert meta["total_count"] == 2
        references = sorted(item["consent_form_reference"] for item in items)
        assert references == ["CF-9401-A", "CF-9401-C"]

        unchanged = validate_success(api.get_consent_record(existing["id"], ANALYST))
        assert unchanged["status"] == "EXECUTED"
        assert unchanged["coverage_end_date"].startswith("2026-08-31")

        insured = validate_success(api.get_employee(employee["id"], ANALYST))
        assert insured["insurable_interest_status"] == "ESTABLISHED", (
            "a 600,000.00 salary already qualifies on the salary path"
        )
