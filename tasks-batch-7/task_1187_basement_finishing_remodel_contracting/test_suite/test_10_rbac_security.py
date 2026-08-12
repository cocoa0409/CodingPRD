"""Role authorization and entity-backed ownership tests (PRD §2.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_design_package_payload,
    create_work_phase_payload,
    get_success_data,
    make_contractor_headers,
    make_homeowner_headers,
    make_subcontractor_headers,
    register_subcontractor,
    setup_design_project,
    setup_scheduling_project,
    validate_error,
    validate_success,
)


class TestForbiddenRoles:
    def test_homeowner_cannot_create_work_phase(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized list is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /api/projects/{id}/work-phases — "Create a sequenced work phase;
        graph, zone, and crew-capacity rules enforced" is authorized for Contractor
        only.

        Design: Corner/rbac/homeowner_cannot_create_work_phase
        """
        ctx = setup_scheduling_project(address="R1 St")
        sub = register_subcontractor(trade="FRAMING", name="Frame R1")
        res = api.create_work_phase(
            ctx["project"]["id"],
            create_work_phase_payload(
                sub["id"], trade="FRAMING", zone="Z1",
                start_date="2026-06-01", end_date="2026-06-08", crew_count=2,
            ),
            make_homeowner_headers(ctx["homeowner"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_subcontractor_cannot_approve_design(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized list is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /api/design-packages/{id}/approve — "Homeowner approves a
        submitted package, superseding any prior approval" is authorized for
        Homeowner only.

        Design: Corner/rbac/subcontractor_cannot_approve_design
        """
        ctx = setup_design_project(address="R2 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        sub = register_subcontractor(trade="FRAMING", name="Frame R2")
        dp = get_success_data(
            api.create_design_package(
                ctx["project"]["id"],
                create_design_package_payload(layout_notes="x"),
                ctr_h,
            )
        )
        validate_success(api.submit_design_package(dp["id"], ctr_h), 200)
        res = api.approve_design_package(
            dp["id"], make_subcontractor_headers(sub["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOwnershipChecks:
    def test_wrong_subcontractor_cannot_start_phase(self, api):
        """PRD §3.6: "The acting subcontractor whose `id` equals the phase's
        `subcontractor_id` starts a `READY` phase — any other caller is rejected with
        `ERR_NOT_RESOURCE_OWNER`"

        Design: Corner/rbac/wrong_subcontractor_cannot_start_phase
        """
        ctx = setup_scheduling_project(address="R3 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        sub_a = register_subcontractor(trade="FRAMING", name="Frame R3A")
        sub_b = register_subcontractor(trade="FRAMING", name="Frame R3B")
        wp = validate_success(
            api.create_work_phase(
                ctx["project"]["id"],
                create_work_phase_payload(
                    sub_a["id"], trade="FRAMING", zone="Z1",
                    start_date="2026-06-01", end_date="2026-06-08", crew_count=2,
                ),
                ctr_h,
            ),
            201,
        )
        res = api.start_work_phase(wp["id"], make_subcontractor_headers(sub_b["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        phase = get_success_data(api.get_work_phase(wp["id"], ctr_h))
        assert phase["status"] == "READY"

    def test_wrong_homeowner_cannot_approve_design(self, api):
        """PRD §3.3: "Both actions require the acting homeowner to own the project
        (`ERR_NOT_RESOURCE_OWNER`) and require the package to be `SUBMITTED`
        (`ERR_INVALID_STATE`)."

        Design: Corner/rbac/wrong_homeowner_cannot_approve_design
        """
        ctx = setup_design_project(address="R4 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        other_ho = get_success_data(
            api.create_homeowner(
                {"name": "H R4B", "email": "hrb@x.com", "phone": "rb"}, ctr_h
            )
        )
        dp = get_success_data(
            api.create_design_package(
                ctx["project"]["id"],
                create_design_package_payload(layout_notes="x"),
                ctr_h,
            )
        )
        validate_success(api.submit_design_package(dp["id"], ctr_h), 200)
        res = api.approve_design_package(
            dp["id"], make_homeowner_headers(other_ho["id"])
        )
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        dp_after = get_success_data(api.get_design_package(dp["id"], ctr_h))
        assert dp_after["status"] == "SUBMITTED"


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed value,
        is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        res = api.list_projects(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
