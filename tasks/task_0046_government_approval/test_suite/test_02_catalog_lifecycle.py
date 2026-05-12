"""Department, Matter, MatterVersion, MaterialTemplate, and
CertificateTemplate lifecycle: creation, publication, supersession,
retirement, ARCHIVED cascade.

Covers PRD §3.1 (Authoring the Matter Catalog), §3.2 (Routing),
§3.3 (Templates), parts of §2.5 (Cascading side effects),
§2.10 (Optimistic concurrency).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_certificate_template,
    assert_department,
    assert_matter,
    assert_matter_version,
    assert_material_template,
    create_certificate_template_payload,
    create_department,
    create_department_payload,
    create_matter,
    create_matter_payload,
    create_matter_version_draft,
    create_matter_version_payload,
    create_material_template_payload,
    create_published_certificate_template,
    create_published_material_template,
    get_success_data,
    is_iso8601_timestamp,
    make_catalog_manager_headers,
    make_certificate_officer_headers,
    make_routing,
    publish_matter_version,
    setup_application_under_review_single_dept,
    setup_single_department_published_version,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Department CRUD (PRD §3.1)
# ===========================================================================
class TestDepartmentLifecycle:
    def test_create_department_returns_active_default(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "a status of either ACTIVE or ARCHIVED defaulting
        to ACTIVE."

        Claim: a freshly registered Department has status=='ACTIVE'.
        """
        resp = api.create_department(
            create_department_payload(), platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_department(data)
        assert data["status"] == "ACTIVE"
        assert data["parent_department_id"] is None

    def test_create_department_with_parent(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "an optional parent_department_id that points at a
        parent department for hierarchical override and escalation
        routing (null at the top of the hierarchy)."

        Claim: parent_department_id round-trips on creation.
        """
        parent = create_department()
        resp = api.create_department(
            create_department_payload(
                parent_department_id=parent["id"], include_parent=True,
            ),
            platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["parent_department_id"] == parent["id"]

    def test_duplicate_department_code_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §2.7: "Unique-field collisions -- Department code, Matter
        code, MatterVersion version_label within a matter, MaterialTemplate
        code, CertificateTemplate code -- are reported as
        ERR_DUPLICATE_RESOURCE with HTTP status 409."

        Claim: two POST /departments with the same code -> second is
        ERR_DUPLICATE_RESOURCE.
        """
        payload = create_department_payload()
        first = api.create_department(payload, platform_admin_headers)
        validate_success(first, expected_status=201)
        second = api.create_department(payload, platform_admin_headers)
        validate_error(second, ApiErrorId.ERR_DUPLICATE_RESOURCE)


# ===========================================================================
# Matter CRUD (PRD §3.1)
# ===========================================================================
class TestMatterLifecycle:
    def test_create_matter_starts_draft_only(
        self, api,
    ):
        """PRD §3.1: "The new shell's status is DRAFT_ONLY and its
        current_published_version_id is null until the first version is
        published."

        Claim: POST /matters yields status=='DRAFT_ONLY' and
        current_published_version_id is null.
        """
        dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        resp = api.create_matter(
            create_matter_payload(owning_department_id=dept["id"]),
            headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_matter(data)
        assert data["status"] == "DRAFT_ONLY"
        assert data["current_published_version_id"] is None

    def test_duplicate_matter_code_rejected(self, api):
        """PRD §2.7: "Unique-field collisions -- ... Matter code ... --
        are reported as ERR_DUPLICATE_RESOURCE with HTTP status 409."

        Claim: posting a Matter with a duplicate code -> ERR_DUPLICATE_RESOURCE.
        """
        dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        payload = create_matter_payload(owning_department_id=dept["id"])
        first = api.create_matter(payload, headers)
        validate_success(first, expected_status=201)
        second = api.create_matter(payload, headers)
        validate_error(second, ApiErrorId.ERR_DUPLICATE_RESOURCE)


# ===========================================================================
# MaterialTemplate / CertificateTemplate publish lifecycle (PRD §3.3)
# ===========================================================================
class TestTemplatePublishing:
    def test_material_template_starts_draft(self, api):
        """PRD §3.3: "New templates start in DRAFT; a separate publish
        step transitions them to PUBLISHED."

        Claim: POST /material-templates yields status=='DRAFT'.
        """
        dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        resp = api.create_material_template(
            create_material_template_payload(), headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_material_template(data)
        assert data["status"] == "DRAFT"

    def test_material_template_publish_transitions_to_published(self, api):
        """PRD §3.3: "New templates start in DRAFT; a separate publish
        step transitions them to PUBLISHED."

        Claim: POST /material-templates/{id}/publish moves DRAFT -> PUBLISHED.
        """
        dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        create_resp = api.create_material_template(
            create_material_template_payload(), headers,
        )
        template = validate_success(create_resp, expected_status=201)
        pub = api.publish_material_template(template["id"], headers)
        data = validate_success(pub)
        assert data["status"] == "PUBLISHED"

    def test_certificate_template_required_variables_must_appear_in_body(
        self, api, certificate_officer_headers,
    ):
        """PRD §3.3: "every entry of required_variables must appear in
        body_template."

        Claim: a CertificateTemplate whose required_variables names a
        token absent from body_template is rejected as ERR_VALIDATION_FAILED.
        """
        payload = create_certificate_template_payload(
            body_template="No placeholders here.",
            required_variables=["applicant_name"],
        )
        resp = api.create_certificate_template(
            payload, certificate_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


# ===========================================================================
# MatterVersion publish-time validation (PRD §3.1, §3.2)
# ===========================================================================
class TestMatterVersionPublishGuards:
    def test_publish_with_unpublished_material_is_rejected(self, api):
        """PRD §3.1: "every MaterialTemplate referenced in
        required_material_template_ids must already be in status PUBLISHED
        and the referenced CertificateTemplate must likewise be PUBLISHED,
        otherwise the request is rejected with
        ERR_DEPENDENT_TEMPLATE_UNPUBLISHED."

        Claim: a MatterVersion with a DRAFT material is rejected at
        publish time with ERR_DEPENDENT_TEMPLATE_UNPUBLISHED.
        """
        dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        # Create but do NOT publish the material template.
        draft_material_resp = api.create_material_template(
            create_material_template_payload(), headers,
        )
        draft_material = validate_success(draft_material_resp,
                                          expected_status=201)
        cert_template = create_published_certificate_template()
        matter = create_matter(
            catalog_manager_headers=headers,
            owning_department_id=dept["id"],
        )
        routing = make_routing(
            mode="SERIAL",
            lead_department_id=dept["id"],
            stages=[{"department_id": dept["id"], "sla_days": 5}],
            aggregation_rule=None,
        )
        version_payload = create_matter_version_payload(
            required_material_template_ids=[draft_material["id"]],
            certificate_template_id=cert_template["id"],
            review_routing=routing,
        )
        # Create the draft (allowed).
        version_resp = api.create_matter_version(
            matter["id"], version_payload, headers,
        )
        version = validate_success(version_resp, expected_status=201)
        # Publish must fail.
        pub_resp = api.publish_matter_version(
            matter["id"], version["id"], headers,
        )
        validate_error(pub_resp, ApiErrorId.ERR_DEPENDENT_TEMPLATE_UNPUBLISHED)

    def test_committed_exceeds_statutory_is_rejected(self, api):
        """PRD §3.1: "two time-limit dimensions ... committed_time_limit_days
        between 1 and the version's statutory_time_limit_days -- a publish
        that violates this inequality is rejected with
        ERR_TIME_LIMIT_INVERSION."

        Claim: committed > statutory at create time yields
        ERR_TIME_LIMIT_INVERSION.
        """
        dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        primary = create_published_material_template(
            catalog_manager_headers=headers,
        )
        cert_template = create_published_certificate_template()
        matter = create_matter(
            catalog_manager_headers=headers,
            owning_department_id=dept["id"],
        )
        routing = make_routing(
            mode="SERIAL",
            lead_department_id=dept["id"],
            stages=[{"department_id": dept["id"], "sla_days": 5}],
            aggregation_rule=None,
        )
        payload = create_matter_version_payload(
            required_material_template_ids=[primary["id"]],
            certificate_template_id=cert_template["id"],
            review_routing=routing,
            statutory_time_limit_days=5,
            committed_time_limit_days=10,
        )
        resp = api.create_matter_version(matter["id"], payload, headers)
        validate_error(resp, ApiErrorId.ERR_TIME_LIMIT_INVERSION)

    def test_routing_serial_with_aggregation_rule_is_rejected(self, api):
        """PRD §3.2: "when mode is SERIAL, aggregation_rule must be null
        and a single rejection at any stage ends the review. Any deviation
        from these rules is rejected with ERR_ROUTING_INVALID."

        Claim: SERIAL routing with a non-null aggregation_rule is rejected.
        """
        dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        primary = create_published_material_template(
            catalog_manager_headers=headers,
        )
        cert_template = create_published_certificate_template()
        matter = create_matter(
            catalog_manager_headers=headers,
            owning_department_id=dept["id"],
        )
        bad_routing = {
            "mode": "SERIAL",
            "lead_department_id": dept["id"],
            "stages": [{"department_id": dept["id"], "sla_days": 5}],
            "aggregation_rule": "ALL_AGREE",  # illegal for SERIAL
        }
        payload = create_matter_version_payload(
            required_material_template_ids=[primary["id"]],
            certificate_template_id=cert_template["id"],
            review_routing=bad_routing,
        )
        resp = api.create_matter_version(matter["id"], payload, headers)
        validate_error(resp, ApiErrorId.ERR_ROUTING_INVALID)

    def test_routing_parallel_without_aggregation_rule_is_rejected(self, api):
        """PRD §3.2: "aggregation_rule is required when mode is PARALLEL
        and must be one of ALL_AGREE, MAJORITY, or LEAD_DECIDES."

        Claim: PARALLEL routing missing aggregation_rule -> ERR_ROUTING_INVALID.
        """
        dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        primary = create_published_material_template(
            catalog_manager_headers=headers,
        )
        cert_template = create_published_certificate_template()
        matter = create_matter(
            catalog_manager_headers=headers,
            owning_department_id=dept["id"],
        )
        bad_routing = {
            "mode": "PARALLEL",
            "lead_department_id": dept["id"],
            "stages": [{"department_id": dept["id"], "sla_days": 5}],
            "aggregation_rule": None,
        }
        payload = create_matter_version_payload(
            required_material_template_ids=[primary["id"]],
            certificate_template_id=cert_template["id"],
            review_routing=bad_routing,
        )
        resp = api.create_matter_version(matter["id"], payload, headers)
        validate_error(resp, ApiErrorId.ERR_ROUTING_INVALID)

    def test_routing_lead_not_in_stages_is_rejected(self, api):
        """PRD §3.2: "lead_department_id must equal the department_id of
        one of the entries in stages."

        Claim: lead_department_id outside stages -> ERR_ROUTING_INVALID.
        """
        dept = create_department()
        other_dept = create_department()
        headers = make_catalog_manager_headers(dept["id"])
        primary = create_published_material_template(
            catalog_manager_headers=headers,
        )
        cert_template = create_published_certificate_template()
        matter = create_matter(
            catalog_manager_headers=headers,
            owning_department_id=dept["id"],
        )
        bad_routing = {
            "mode": "SERIAL",
            "lead_department_id": other_dept["id"],   # not in stages
            "stages": [{"department_id": dept["id"], "sla_days": 5}],
            "aggregation_rule": None,
        }
        payload = create_matter_version_payload(
            required_material_template_ids=[primary["id"]],
            certificate_template_id=cert_template["id"],
            review_routing=bad_routing,
        )
        resp = api.create_matter_version(matter["id"], payload, headers)
        validate_error(resp, ApiErrorId.ERR_ROUTING_INVALID)


# ===========================================================================
# Publish auto-supersede + Matter pointer (PRD §2.5, §3.1)
# ===========================================================================
class TestPublishCascade:
    def test_publish_v2_auto_supersedes_v1(self, api):
        """PRD §3.1: "If a previously PUBLISHED sibling existed, it is
        auto-cascaded from PUBLISHED to SUPERSEDED in the same request --
        that sibling becomes read-only but in-flight applications retain
        their pinned matter_version_id and continue against the rules
        they snapshotted at submission."

        Claim: publishing V2 flips V1 from PUBLISHED to SUPERSEDED in
        the same request, and Matter.current_published_version_id
        repoints to V2.
        """
        ctx = setup_single_department_published_version()
        v1 = ctx["version"]
        # Create + publish a sibling V2 on the same matter.
        v2_draft = create_matter_version_draft(
            matter_id=ctx["matter"]["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
            required_material_template_ids=ctx["all_required_material_template_ids"],
            certificate_template_id=ctx["certificate_template"]["id"],
            review_routing=v1["review_routing"],
        )
        v2 = publish_matter_version(
            matter_id=ctx["matter"]["id"],
            version_id=v2_draft["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
        )
        # Refresh v1.
        v1_refresh = get_success_data(
            api.get_matter_version(
                ctx["matter"]["id"], v1["id"], ctx["catalog_manager_headers"],
            )
        )
        assert v1_refresh["status"] == "SUPERSEDED"
        assert v2["status"] == "PUBLISHED"
        # Matter.current_published_version_id repoints.
        matter_refresh = get_success_data(
            api.get_matter(ctx["matter"]["id"], ctx["catalog_manager_headers"])
        )
        assert matter_refresh["current_published_version_id"] == v2["id"]
        assert matter_refresh["status"] == "PUBLISHED"


# ===========================================================================
# Retirement (PRD §3.1)
# ===========================================================================
class TestMatterVersionRetirement:
    def test_retire_published_with_in_flight_application_is_rejected(self, api):
        """PRD §3.1: "Retirement requires that no application whose
        review_status falls outside {APPROVED, REJECTED, WITHDRAWN}
        still references the version."

        Claim: retiring a PUBLISHED version while an Application in
        UNDER_REVIEW references it -> ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/matter_version_retire_blocked_by_in_flight_application_pair
        """
        ctx = setup_application_under_review_single_dept()
        resp = api.retire_matter_version(
            ctx["matter"]["id"], ctx["version"]["id"],
            ctx["catalog_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_retire_published_no_other_published_archives_matter(self, api):
        """PRD §3.1: "retirement of a PUBLISHED version that equals the
        matter's current_published_version_id clears that pointer, and
        if the matter then has no surviving PUBLISHED version its status
        flips to ARCHIVED."

        Claim: retiring the only PUBLISHED version with no in-flight
        applications -> Matter.status = ARCHIVED, current_published_version_id
        is null.
        """
        ctx = setup_single_department_published_version()
        resp = api.retire_matter_version(
            ctx["matter"]["id"], ctx["version"]["id"],
            ctx["catalog_manager_headers"],
        )
        validate_success(resp)
        matter_refresh = get_success_data(
            api.get_matter(ctx["matter"]["id"], ctx["catalog_manager_headers"])
        )
        assert matter_refresh["status"] == "ARCHIVED"
        assert matter_refresh["current_published_version_id"] is None
