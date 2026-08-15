"""Exclusion-list screening: creation branches, validity windows, resolution."""
from test_helpers import (
    ApiErrorId,
    create_confirmed_match_screening,
    create_employee,
    create_exclusion_screening,
    create_license,
    create_license_payload,
    create_license_type,
    get_success_data,
    make_officer_headers,
    set_clock,
    setup_nurse_with_active_license,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OFFICER = TEST_USERS["officer_headers"]
OFFICER1 = make_officer_headers("officer-1")
OFFICER2 = make_officer_headers("officer-2")


class TestScreeningWindowContainment:
    def test_screening_window_inclusive_end_rejected(self, api):
        """PRD §3.8: "its validity window runs from `screened_on` through
        `valid_until`, inclusive at both ends. Clear windows cannot stack for
        the same employee and list: when an existing `CLOSED_CLEAR` screening
        for the same `employee_id` and `list_source` has a window containing the
        new `screened_on`, creation fails with `ERR_SCREENING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/screening_validity_window_containment
        """
        emp = create_employee(full_name="Audrey Subject",
                              work_email="audrey.scr@example.com")
        scr1 = create_exclusion_screening(emp["id"], screened_on="2026-08-01",
                                          outcome="CLEAR")
        # screened_on 2026-08-01 + 30 days, inclusive.
        assert scr1["valid_until"] == "2026-08-31"

        set_clock("2026-08-31T00:00:00Z")
        resp = api.create_exclusion_screening(emp["id"], {
            "list_source": "OIG_LEIE", "screened_on": "2026-08-31",
            "outcome": "CLEAR",
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_SCREENING_WINDOW_OVERLAP, 422)

    def test_screening_day_after_window_accepted(self, api):
        """PRD §3.8: "A clear screen lands directly in `CLOSED_CLEAR` with
        `valid_until` set to `screened_on` plus thirty days"; "when an existing
        `CLOSED_CLEAR` screening for the same `employee_id` and `list_source`
        has a window containing the new `screened_on`, creation fails with
        `ERR_SCREENING_WINDOW_OVERLAP`" — 2026-09-01 lies outside the
        [2026-08-01, 2026-08-31] window.

        Design: Difficulty/resource_temporal_overlap/screening_validity_window_containment
        """
        emp = create_employee(full_name="Audrey Subject",
                              work_email="audrey.scr2@example.com")
        create_exclusion_screening(emp["id"], screened_on="2026-08-01",
                                   outcome="CLEAR")
        set_clock("2026-09-01T00:00:00Z")
        scr2 = validate_success(api.create_exclusion_screening(emp["id"], {
            "list_source": "OIG_LEIE", "screened_on": "2026-09-01",
            "outcome": "CLEAR",
        }, OFFICER), 201)
        assert scr2["status"] == "CLOSED_CLEAR"
        assert scr2["valid_until"] == "2026-10-01"


class TestScreeningResolution:
    def test_screening_cleared_false_positive_restores_posture(self, api):
        """PRD §3.8: "Clearing a false positive moves the screening to
        `CLEARED_FALSE_POSITIVE` with a `resolution_note` and
        `resolved_by_user_id`, then recomputes the posture: `CLEAR` when no
        other `UNDER_REVIEW` or `CONFIRMED_MATCH` screening remains for the
        employee".
        PRD §3.2: "`SCREENING_FLAGGED` applies when the employee's
        `screening_posture` is `FLAGGED`" — PENDING_REVIEW alone does not
        restrict.

        Design: Corner/state_machines/screening_cleared_false_positive_restores_posture
        """
        lt, emp, lic = setup_nurse_with_active_license(
            email="nora.fp@example.com", license_number="RN-9108")
        scr = create_exclusion_screening(emp["id"], headers=OFFICER1,
                                         list_source="SAM_GSA",
                                         screened_on="2026-08-01",
                                         outcome="FLAGGED")
        mid = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert mid["screening_posture"] == "PENDING_REVIEW"
        assert mid["work_authorization"] == "AUTHORIZED"

        cleared = validate_success(api.clear_false_positive_exclusion_screening(
            scr["id"], "Name collision, different SSN", OFFICER2), 200)
        assert cleared["status"] == "CLEARED_FALSE_POSITIVE"

        end = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert end["screening_posture"] == "CLEAR"
        assert end["work_authorization"] == "AUTHORIZED"


class TestLicenseCreateBlockedByConfirmedMatch:
    def test_license_create_blocked_by_confirmed_exclusion_match(self, api):
        """PRD §3.3: "an employee with any screening standing at
        `CONFIRMED_MATCH` may not have new licenses registered at all, and the
        attempt is refused with `ERR_EMPLOYEE_SCREENING_FLAGGED`."

        Design: Difficulty/cross_entity_state_dependency/license_create_blocked_by_confirmed_exclusion_match
        """
        lt = create_license_type()
        emp = create_employee(full_name="Sam Screener",
                              work_email="sam@example.com")
        create_confirmed_match_screening(emp["id"])

        resp = api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   license_number="RN-8302"), OFFICER)
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_SCREENING_FLAGGED, 403)

    def test_license_create_allowed_after_only_under_review_screening(self, api):
        """PRD §3.3: "an employee with any screening standing at
        `CONFIRMED_MATCH` may not have new licenses registered at all" — an
        `UNDER_REVIEW` screening is not `CONFIRMED_MATCH` and does not trip the
        gate.

        Design: Difficulty/cross_entity_state_dependency/license_create_blocked_by_confirmed_exclusion_match
        """
        lt = create_license_type()
        emp = create_employee(full_name="Sam Screener",
                              work_email="sam.ok@example.com")
        create_exclusion_screening(emp["id"], headers=OFFICER1, outcome="FLAGGED")
        data = validate_success(api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   license_number="RN-8303"), OFFICER), 201)
        assert data["status"] == "PENDING_VERIFICATION"
