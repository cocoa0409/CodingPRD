"""Compliance summary report, the default logical clock, and list filtering."""
from test_helpers import (
    ApiErrorId,
    create_active_license,
    create_disciplinary_event,
    create_employee,
    create_license,
    create_license_type,
    create_role_requirement,
    get_success_data,
    make_officer_headers,
    confirm_disciplinary_event,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, create_pe_license_type

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
HR = TEST_USERS["hr_headers"]
OFFICER1 = make_officer_headers("officer-1")
OFFICER2 = make_officer_headers("officer-2")


class TestComplianceSummary:
    def test_report_counts_reflect_verification_overdue(self, api):
        """PRD §3.3: "`verification_posture` itself reads `NEVER_VERIFIED` while
        `last_verified_on` is null, `OVERDUE` once the logical current date is
        strictly after `next_verification_due_on` — a current date exactly equal
        to the due date still reads `CURRENT` — and `CURRENT` otherwise."
        PRD §3.9: "a compliance-summary capability gives `ComplianceAdmin`,
        `ComplianceOfficer`, `HRPartner`, and `ExternalAuditor` callers — but
        not employees — a live posture readout: `authorized_employee_count`,
        `restricted_employee_count`, `flagged_employee_count`,
        `expired_license_count`, `overdue_verification_count`,
        `open_screening_count`, `committed_reimbursement_cents`, and
        `paid_reimbursement_cents`."

        Design: Corner/endpoints/report_counts_reflect_verification_overdue
        """
        from test_helpers import constants
        payload = dict(constants.LVN_TYPE_PAYLOAD)  # 30-day cadence, CE 0
        resp = api.create_license_type(payload, ADMIN)
        lt = get_success_data(resp, 201)
        create_role_requirement(lt["id"])
        emp = create_employee(work_email="nora.rpt@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="LVN-9401")
        # due = min(2026-08-01 + 30d, 2027-06-30) = 2026-08-31.
        set_clock("2026-09-15T00:00:00Z")

        report = get_success_data(api.get_compliance_summary(ADMIN))
        assert report["overdue_verification_count"] == 1
        assert report["restricted_employee_count"] == 1
        assert report["authorized_employee_count"] == 0


class TestAuthorizationPartitionInvariant:
    def _two_nurse_scenario(self, api):
        lt = create_license_type()
        create_role_requirement(lt["id"])
        emp1 = create_employee(work_email="nora.part@example.com")
        emp2 = create_employee(full_name="Nick Nurse",
                               work_email="nick.part@example.com")
        lic1 = create_active_license(emp1["id"], lt["id"],
                                     license_number="RN-8501")
        create_active_license(emp2["id"], lt["id"], license_number="RN-8502",
                              source="NURSYS")
        return lt, emp1, emp2, lic1

    def test_authorization_partition_conserved_through_suspend(self, api):
        """PRD §3.9: "a live posture readout: `authorized_employee_count`,
        `restricted_employee_count`, `flagged_employee_count`,
        `expired_license_count`, `overdue_verification_count`,
        `open_screening_count`, `committed_reimbursement_cents`, and
        `paid_reimbursement_cents`."
        PRD §3.7: "suspension engages the `LICENSE_SUSPENDED` reason, and
        revocation feeds the `LICENSE_LAPSED` bucket".

        Design: Difficulty/compensating_invariant/authorization_partition_conserved_through_suspend_resolve
        """
        lt, emp1, emp2, lic1 = self._two_nurse_scenario(api)
        base = get_success_data(api.get_compliance_summary(ADMIN))
        assert base["authorized_employee_count"] == 2
        assert base["restricted_employee_count"] == 0

        event = create_disciplinary_event(
            lic1["id"], headers=OFFICER1, board_case_number="B-21",
            event_type="SUSPENSION", effective_on="2026-08-01")
        confirm_disciplinary_event(event["id"], headers=OFFICER2)

        mid = get_success_data(api.get_compliance_summary(ADMIN))
        assert mid["authorized_employee_count"] == 1
        assert mid["restricted_employee_count"] == 1
        assert (mid["authorized_employee_count"] + mid["restricted_employee_count"]
                == base["authorized_employee_count"]
                + base["restricted_employee_count"] == 2)

    def test_authorization_partition_restored_through_resolve(self, api):
        """PRD §3.7: "a resolved `SUSPENSION` lifts — the license returns from
        `SUSPENDED` to `ACTIVE` — only when no other open suspension still
        covers that license"; "re-derives the holder's work authorization".

        Design: Difficulty/compensating_invariant/authorization_partition_conserved_through_suspend_resolve
        """
        lt, emp1, emp2, lic1 = self._two_nurse_scenario(api)
        event = create_disciplinary_event(
            lic1["id"], headers=OFFICER1, board_case_number="B-21",
            event_type="SUSPENSION", effective_on="2026-08-01")
        confirm_disciplinary_event(event["id"], headers=OFFICER2)
        validate_success(api.resolve_disciplinary_event(
            event["id"], "Suspension lifted by board", OFFICER2), 200)

        end = get_success_data(api.get_compliance_summary(ADMIN))
        assert end["authorized_employee_count"] == 2
        assert end["restricted_employee_count"] == 0


class TestDefaultLogicalClock:
    def test_logical_clock_default_is_fixed(self, api):
        """PRD §2.5: "Before any clock-setting call has been made, the logical
        clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to the
        host's clock afterwards."
        PRD §3.7: "an `effective_on` date that may not lie after the logical
        current date (`ERR_INVALID_REQUEST`)".

        Design: Corner/cross_cutting_complexity/logical_clock_default_is_fixed
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.clock@example.com")
        lic = create_license(emp["id"], lt["id"], license_number="RN-9602")

        resp = api.create_disciplinary_event(lic["id"], {
            "board_case_number": "B-81", "event_type": "WARNING",
            "effective_on": "2026-08-02", "received_via": "BOARD_FEED",
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

        ok = validate_success(api.create_disciplinary_event(lic["id"], {
            "board_case_number": "B-82", "event_type": "WARNING",
            "effective_on": "2026-08-01", "received_via": "BOARD_FEED",
        }, OFFICER), 201)
        assert ok["status"] == "RECEIVED"


class TestLicenseFiltering:
    def test_licenses_filter_by_status(self, api):
        """PRD §3.3: "The inventory supports listing with `employee_id`,
        `license_type_id`, `state_code`, `status`, `verification_posture`, or
        `alert_tier` filters".

        Design: Corner/cross_cutting_complexity/licenses_filter_by_status
        """
        lt_rn = create_license_type()
        lt_pe = create_pe_license_type()
        emp = create_employee(work_email="nora.filt@example.com")
        lic_rn = create_license(emp["id"], lt_rn["id"], license_number="RN-9603")
        lic_pe = create_license(emp["id"], lt_pe["id"], license_number="PE-9604")
        validate_success(api.verify_license(lic_rn["id"], {
            "verified_on": "2026-08-01", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER), 200)

        active, meta_active = validate_paginated(api.list_licenses(
            OFFICER, params={"employee_id": emp["id"], "status": "ACTIVE"}))
        assert meta_active["total_count"] == 1
        assert active[0]["id"] == lic_rn["id"]

        pending, meta_pending = validate_paginated(api.list_licenses(
            OFFICER, params={"employee_id": emp["id"],
                             "status": "PENDING_VERIFICATION"}))
        assert meta_pending["total_count"] == 1
        assert pending[0]["id"] == lic_pe["id"]
