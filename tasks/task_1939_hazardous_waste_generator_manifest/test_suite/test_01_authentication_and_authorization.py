"""Authentication, role gates, ownership, and segregation of duties."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, create_site_payload, create_container_payload,
    create_partner_payload, partner_status_payload,
    create_site, create_stream, create_active_stream, create_area,
    create_container, create_partner, get_partner,
    create_manifest_chain, setup_shippable_site, create_manifest,
    inspect_container, get_container, attach_ldr, sign_manifest_generator,
    ehs_headers, wc_headers, ca_headers,
    make_transporter_agent_headers, make_tsdf_agent_headers,
    build_user_headers, manifest_line_item,
)


class TestUserContextHeader:
    def test_unknown_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/unknown_role_header_unauthenticated
        """
        res = api.create_site(
            create_site_payload(), build_user_headers("user-1", "Wizard"))
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleGates:
    def test_waste_coordinator_cannot_sign_generator(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized role
        list is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: the generator
        signature endpoint authorizes only "EHSManager".

        Design: Corner/rbac/waste_coordinator_cannot_sign_generator
        """
        env = create_manifest_chain(through="DRAFT")
        attach_ldr(env["manifest"]["id"])
        # The drafter's own role is not authorized for the generator signature.
        res = api.sign_manifest_generator(
            env["manifest"]["id"], wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_auditor_cannot_create_containers(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized role
        list is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: container
        placement authorizes only "WasteCoordinator".

        Design: Corner/rbac/auditor_cannot_create_containers
        """
        site = create_site()
        stream = create_active_stream(site["id"])
        area = create_area(site["id"])
        res = api.create_container(
            create_container_payload(stream["id"], area["id"], 10, 50.0),
            ca_headers("aud-1"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_agent_roles_can_read_resources(self, api):
        """PRD §4: "| GET | `/hazwaste/manifests` | List manifests, optionally
        filtered by `site_id`, `transporter_id`, or `tsdf_id` | EHSManager,
        WasteCoordinator, ComplianceAuditor, TransporterAgent, TSDFAgent |" and
        "| GET | `/hazwaste/generator-sites/{siteId}` | Get one generator site
        including computed category and counters | EHSManager, WasteCoordinator,
        ComplianceAuditor, TransporterAgent, TSDFAgent |".

        Design: Corner/rbac/agent_roles_can_read_resources
        """
        site = create_site()
        res = api.list_manifests(
            make_transporter_agent_headers("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"))
        _, meta = validate_paginated(res)
        assert meta["total_count"] == 0
        res = api.get_site(
            site["id"],
            make_tsdf_agent_headers("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"))
        data = validate_success(res)
        assert data["id"] == site["id"]


class TestPartnerIdentityOwnership:
    def test_transporter_agent_identity_mismatch_rejected(self, api):
        """PRD §2.1: "a `TransporterAgent` may only countersign manifests whose
        `transporter_id` equals the agent's `X-User-ID`" and "A mismatch on those
        partner-backed operations is rejected with `ERR_PARTNER_IDENTITY_MISMATCH`
        (HTTP 403)."

        Design: Corner/rbac/transporter_agent_identity_mismatch_rejected
        """
        env = create_manifest_chain(through="GENERATOR_SIGNED")
        manifest = env["manifest"]
        # The TSDF's id is not the manifest's transporter_id.
        res = api.sign_manifest_transporter(
            manifest["id"], make_transporter_agent_headers(env["tsdf"]["id"]))
        validate_error(res, ApiErrorId.ERR_PARTNER_IDENTITY_MISMATCH)
        assert validate_success(api.get_manifest(
            manifest["id"], ehs_headers()))["status"] == "GENERATOR_SIGNED"
        # The matching agent signs successfully.
        from test_helpers import assert_instant_equals
        signed = validate_success(api.sign_manifest_transporter(
            manifest["id"], make_transporter_agent_headers(env["transporter"]["id"])))
        assert signed["status"] == "IN_TRANSIT"
        assert_instant_equals(signed["shipped_at"], "2026-08-01T00:00:00Z",
                              "shipped_at")


class TestSegregationOfDuties:
    def test_sod_partner_self_approve_rejected(self, api):
        """PRD §3.5: "Approval moves a partner from `PENDING` — or from
        `SUSPENDED`, as a reinstatement — to `APPROVED`, and is segregated from
        registration: the approver's `X-User-ID` must differ from the partner's
        `created_by_user_id`, or the call is rejected with
        `ERR_SOD_PARTNER_SELF_APPROVE`."

        Design: Corner/rbac/sod_partner_self_approve_rejected
        """
        partner = create_partner("TRANSPORTER", "HaulCo", "EPA-TR-1", ["D001"],
                                 registrar="aud-1")
        res = api.set_partner_status(
            partner["id"], partner_status_payload("APPROVED"), ca_headers("aud-1"))
        validate_error(res, ApiErrorId.ERR_SOD_PARTNER_SELF_APPROVE)
        assert get_partner(partner["id"])["status"] == "PENDING"
        approved = validate_success(api.set_partner_status(
            partner["id"], partner_status_payload("APPROVED"), ca_headers("aud-2")))
        assert approved["status"] == "APPROVED"

    def test_sod_self_inspection_rejected(self, api):
        """PRD §3.4: "the inspector's `X-User-ID`, recorded on the inspection as
        `inspector_user_id`, must differ from the container's
        `last_action_user_id` — the user who created or most recently moved the
        container may not inspect it, and the attempt is rejected with
        `ERR_SOD_SELF_INSPECTION`."

        Design: Corner/rbac/sod_self_inspection_rejected
        """
        from test_helpers import assert_instant_equals
        site = create_site()
        stream = create_active_stream(site["id"])
        area = create_area(site["id"])
        container = create_container(stream["id"], area["id"], 10, 50.0, "wc-1")
        res = api.create_inspection(container["id"], {"result": "PASS"},
                                    wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_SOD_SELF_INSPECTION)
        inspection = inspect_container(container["id"], "PASS", inspector="wc-2")
        assert inspection["inspector_user_id"] == "wc-2"
        assert_instant_equals(
            get_container(container["id"])["last_inspected_at"],
            "2026-08-01T00:00:00Z", "last_inspected_at")

    def test_sod_manifest_self_sign_isolated_rejected(self, api):
        """PRD §3.6: "the signer's `X-User-ID` must differ from the manifest's
        `created_by_user_id` — the coordinator who drafted the manifest may not
        also certify it, a segregation rejected with `ERR_SOD_MANIFEST_SELF_SIGN`".

        Design: Corner/rbac/sod_manifest_self_sign_isolated_rejected
        """
        env = create_manifest_chain(through="DRAFT", creator="wc-1")
        attach_ldr(env["manifest"]["id"])
        # Manifest is DRAFT and fully certifiable; only the SoD gate can fire.
        res = api.sign_manifest_generator(
            env["manifest"]["id"], ehs_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_SOD_MANIFEST_SELF_SIGN)
        assert validate_success(api.get_manifest(
            env["manifest"]["id"], ehs_headers()))["status"] == "DRAFT"
