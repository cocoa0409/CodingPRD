"""RBAC: segregation of duties and Resident ownership rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_building,
    create_site,
    create_unit,
    create_work_order,
    make_maintenance_lead_headers,
    make_resident_headers,
    make_site_manager_headers,
    setup_active_tenancy,
    setup_certified_site,
    setup_eligible_household,
    setup_site_with_units,
    create_tenancy,
    conduct_inspection,
    create_inspection,
    issue_findings,
    make_compliance_inspector_headers,
    validate_error,
    validate_success,
    walk_work_order_to_completed,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
LEAD = TEST_USERS["maintenance_lead_headers"]


class TestSegregationOfDuties:
    def test_sod_work_order_self_verify_rejected(self, api):
        """PRD §2.10: "A work order completed by one operator can be verified
        only by a different one: verification requires the caller's
        `X-User-ID` to differ from the recorded `completed_by`, and a match is
        rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_work_order_self_verify_rejected
        """
        site = create_site(name="S")
        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        wo = create_work_order(unit["id"], "OTHER", "MINOR", "d")
        walk_work_order_to_completed(wo["id"], completed_by="shared-1")

        # The same person id wearing SiteManager cannot verify own work.
        self_verify = api.update_work_order(
            wo["id"], {"status": "VERIFIED"},
            make_site_manager_headers("shared-1"))
        validate_error(self_verify, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        other = validate_success(api.update_work_order(
            wo["id"], {"status": "VERIFIED"},
            make_site_manager_headers("sm-9")))
        assert other["status"] == "VERIFIED"

    def test_sod_inspection_self_cure_rejected(self, api):
        """PRD §2.10: "Symmetrically, the inspector who issued a regulatory
        inspection's findings may not certify their cure: cure certification
        requires the caller's `X-User-ID` to differ from `issued_by`, with the
        same error on a match. The verifier and cure-certifier identities are
        recorded as `verified_by` and `cure_certified_by` respectively."

        Design: Corner/rbac/sod_inspection_self_cure_rejected
        """
        ctx = setup_certified_site(site_name="S")
        inspection = create_inspection(ctx["site"]["id"], "HUD",
                                       "2026-08-15", inspector_id="ci-1")
        conduct_inspection(inspection["id"], inspector_id="ci-1")
        issue_findings(
            inspection["id"],
            [{"unit_id": ctx["unit"]["id"], "severity": "MINOR",
              "code": "SCR-01"}], inspector_id="ci-1")

        self_cure = api.update_regulatory_inspection(
            inspection["id"], {"status": "CURE_CERTIFIED"},
            make_compliance_inspector_headers("ci-1"))
        validate_error(self_cure,
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        cured = validate_success(api.update_regulatory_inspection(
            inspection["id"], {"status": "CURE_CERTIFIED"},
            make_compliance_inspector_headers("ci-2")))
        assert cured["status"] == "CURE_CERTIFIED"
        assert cured["cure_certified_by"] == "ci-2"

    def test_maintenance_lead_cannot_verify(self, api):
        """PRD §2.1: "`SiteManager` runs the property day to day: pest
        treatments, complaint handling, and work-order verification and
        closure. `MaintenanceLead` supervises maintenance: triage, assignment,
        execution, and completion of work orders."
        PRD §2.1: "A recognized role attempting an operation it is not
        permitted to perform is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/maintenance_lead_cannot_verify
        """
        site = create_site(name="S")
        building = create_building(site["id"])
        unit = create_unit(site["id"], building["id"])
        wo = create_work_order(unit["id"], "OTHER", "MINOR", "d")
        walk_work_order_to_completed(wo["id"], completed_by="ml-1")

        resp = api.update_work_order(
            wo["id"], {"status": "VERIFIED"},
            make_maintenance_lead_headers("ml-2"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestResidentOwnership:
    def test_resident_files_complaint_and_notice_for_own_tenancy(self, api):
        """PRD §3.7: "A `Resident` files against their own tenancy — the
        `tenancy_id` must resolve to a tenancy whose `household_id` equals the
        caller's `X-User-ID`, otherwise `ERR_INSUFFICIENT_PERMISSIONS`"
        PRD §3.4: "A `Resident` may give notice on their own tenancy — the
        tenancy's `household_id` must equal the caller's `X-User-ID`,
        otherwise `ERR_INSUFFICIENT_PERMISSIONS` — and the recorded
        `notice_reason` is `RESIDENT`."

        Design: Corner/rbac/resident_files_complaint_and_notice_for_own_tenancy
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam RO")
        household_id = ctx["household"]["id"]
        resident = make_resident_headers(household_id)

        complaint = validate_success(api.create_complaint(
            {"tenancy_id": ctx["tenancy"]["id"], "category": "UTILITY",
             "description": "meter reading dispute"}, resident),
            expected_status=201)
        assert complaint["status"] == "FILED"

        notice = validate_success(api.update_tenancy(
            ctx["tenancy"]["id"], {"status": "NOTICE"}, resident))
        assert notice["status"] == "NOTICE"
        assert notice["notice_reason"] == "RESIDENT"

    def test_resident_cannot_file_for_other_household(self, api):
        """PRD §2.1: "When `X-User-Role` is `Resident`, `X-User-ID` is the
        `id` of the acting `Household`; ownership checks on any resource that
        references a household compare that household foreign key —
        concretely, the tenancy's `household_id` when a resident files a
        complaint or gives notice — against `X-User-ID`, and a mismatch is
        `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/resident_cannot_file_for_other_household
        """
        ctx = setup_site_with_units(site_name="S", unit_specs=[
            {"unit_code": "U1"}, {"unit_code": "U2"}])
        _, u2 = ctx["units"]
        h1 = setup_eligible_household(name="Fam R1")["household"]
        h2 = setup_eligible_household(
            name="Fam R2", members=(("R2", "1991-01-01", "HEAD"),))[
            "household"]
        t2 = create_tenancy(h2["id"], u2["id"])
        activated = validate_success(api.update_tenancy(
            t2["id"], {"status": "ACTIVE"}, INTAKE))
        assert activated["status"] == "ACTIVE", "Setup failed"

        stranger = make_resident_headers(h1["id"])
        complaint = api.create_complaint(
            {"tenancy_id": t2["id"], "category": "OTHER",
             "description": "not my home"}, stranger)
        validate_error(complaint, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        notice = api.update_tenancy(t2["id"], {"status": "NOTICE"}, stranger)
        validate_error(notice, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
