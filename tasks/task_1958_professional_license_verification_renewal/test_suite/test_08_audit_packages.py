"""Audit evidence packages: periods, sealing, snapshots, and invalidation."""
from test_helpers import (
    ApiErrorId,
    create_active_license,
    create_audit_package,
    create_disciplinary_event,
    create_employee,
    create_exclusion_screening,
    create_license_type,
    get_success_data,
    make_officer_headers,
    seal_audit_package,
    set_clock,
    validate_error,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER1 = make_officer_headers("officer-1")
AUDITOR = TEST_USERS["auditor_headers"]


class TestAuditPeriodShape:
    def test_audit_period_inverted_rejected(self, api):
        """PRD §3.9: "`period_start` is inclusive, `period_end` is exclusive,
        and the end must fall strictly after the start
        (`ERR_INVALID_AUDIT_PERIOD`)."

        Design: Corner/validations/audit_period_inverted_rejected
        """
        emp = create_employee(full_name="Audrey Subject",
                              work_email="audrey.per@example.com")
        resp = api.create_audit_package(emp["id"], {
            "period_start": "2026-09-01", "period_end": "2026-08-01",
        }, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_PERIOD, 422)


class TestAuditPeriodOverlap:
    def test_adjacent_half_open_periods_coexist(self, api):
        """PRD §3.9: "Periods for the same employee may touch but may not
        intersect — a new package whose half-open period overlaps any `BUILDING`
        or `SEALED` package of the same employee fails with
        `ERR_AUDIT_PERIOD_OVERLAP`; strictly adjacent periods are allowed".

        Design: Difficulty/resource_temporal_overlap/audit_package_half_open_intersection
        """
        emp = create_employee(full_name="Audrey Subject",
                              work_email="audrey@example.com")
        pkg1 = create_audit_package(emp["id"], "2026-08-01", "2026-09-01")
        pkg2 = create_audit_package(emp["id"], "2026-09-01", "2026-10-01")
        assert pkg1["status"] == "BUILDING"
        assert pkg2["status"] == "BUILDING"

    def test_intersecting_period_rejected(self, api):
        """PRD §3.9: "a new package whose half-open period overlaps any
        `BUILDING` or `SEALED` package of the same employee fails with
        `ERR_AUDIT_PERIOD_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/audit_package_half_open_intersection
        """
        emp = create_employee(full_name="Audrey Subject",
                              work_email="audrey.ovl@example.com")
        create_audit_package(emp["id"], "2026-08-01", "2026-09-01")
        resp = api.create_audit_package(emp["id"], {
            "period_start": "2026-08-15", "period_end": "2026-08-20",
        }, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP, 409)


class TestAuditSeal:
    def test_audit_seal_before_period_close_rejected(self, api):
        """PRD §3.9: "The period must already be closed — `period_end` on or
        before the logical current date, otherwise
        `ERR_AUDIT_PERIOD_NOT_CLOSED`".

        Design: Corner/state_machines/audit_seal_before_period_close_rejected
        """
        emp = create_employee(full_name="Audrey Subject",
                              work_email="audrey.seal@example.com")
        pkg = create_audit_package(emp["id"], "2026-08-01", "2026-12-01")
        # Default clock is 2026-08-01, before period_end 2026-12-01.
        resp = api.seal_audit_package(pkg["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_PERIOD_NOT_CLOSED, 422)
        after = get_success_data(api.get_audit_package(pkg["id"], AUDITOR))
        assert after["status"] == "BUILDING"

    def test_audit_snapshot_contents_on_seal(self, api):
        """PRD §3.9: "On sealing, `sealed_at` — null while the package is being
        built — takes the current logical timestamp and the `evidence_snapshot`
        is frozen: for the subject employee, every verification event whose
        `verified_on` falls in the period, every disciplinary event whose
        `effective_on` falls in it, every screening whose `screened_on` falls in
        it, and every `PAID` renewal request whose `paid_on` falls in it."
        "`evidence_item_count` is set to the snapshot's length."

        Design: Corner/endpoints/audit_snapshot_contents_on_seal
        """
        lt = create_license_type()
        emp = create_employee(full_name="Audrey Subject",
                              work_email="audrey.snap@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-9401")
        scr = create_exclusion_screening(emp["id"], headers=OFFICER1,
                                         list_source="OIG_LEIE",
                                         screened_on="2026-08-01", outcome="CLEAR")
        pkg = create_audit_package(emp["id"], "2026-08-01", "2026-09-01")
        set_clock("2026-09-01T00:00:00Z")  # period_end <= logical current date

        sealed = seal_audit_package(pkg["id"])
        assert sealed["status"] == "SEALED"
        assert sealed["evidence_item_count"] == 2
        # One verification event (2026-08-01) and one screening (2026-08-01).
        ref_ids = sorted(item["ref_id"] for item in sealed["evidence_snapshot"])
        assert len(ref_ids) == 2
        assert scr["id"] in ref_ids
        occurred = {item["occurred_on"] for item in sealed["evidence_snapshot"]}
        assert occurred == {"2026-08-01"}

    def test_sealed_audit_package_invalidated_by_late_event(self, api):
        """PRD §3.9: "If any dependent fact lands inside its sealed period — a
        verification recorded with a `verified_on` in the period, a disciplinary
        event with an `effective_on` in it, a screening with a `screened_on` in
        it, or a renewal request paid with a `paid_on` in it — the package flips
        from `SEALED` to `INVALIDATED`, the terminal state, with its snapshot
        retained for forensics".

        Design: Corner/state_machines/sealed_audit_package_invalidated_by_late_event
        """
        lt = create_license_type()
        emp = create_employee(full_name="Audrey Subject",
                              work_email="audrey.inv@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-9106")
        pkg = create_audit_package(emp["id"], "2026-08-01", "2026-09-01")
        set_clock("2026-09-01T00:00:00Z")
        sealed = seal_audit_package(pkg["id"])
        assert sealed["status"] == "SEALED"

        create_disciplinary_event(lic["id"], headers=OFFICER1,
                                  board_case_number="B-51", event_type="WARNING",
                                  effective_on="2026-08-15")
        after = get_success_data(api.get_audit_package(pkg["id"], AUDITOR))
        assert after["status"] == "INVALIDATED"
