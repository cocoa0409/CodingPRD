"""Templates, the CAN-SPAM approval gate, and the campaign review revision loop."""
from test_helpers import (
    NON_EXISTENT_UUID,
    NON_COMPLIANT_HTML_BODY,
    PLATFORM,
    ApiErrorId,
    create_approved_campaign,
    create_audience,
    create_campaign,
    create_campaign_payload,
    create_dual_only_tenant,
    create_published_template,
    create_segment,
    create_template,
    create_template_payload,
    assert_template,
    make_campaign_author_headers,
    make_compliance_approver_headers,
    provision_tenant,
    read_campaign,
    review_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTemplateLifecycle:
    def test_has_unsubscribe_link_is_derived_from_the_body(self, api):
        """PRD §3.5: "`has_unsubscribe_link` is not an input — it is derived, and reads true
        exactly when the literal substring `{{unsubscribe_url}}` occurs in `html_body`."
        PRD §3.5: "A template is born in `DRAFT` and may be published once, moving
        `DRAFT → PUBLISHED`; publishing from any other state is refused with `ERR_INVALID_STATE`."

        Design: Corner/entities/template_has_unsubscribe_link_computed_from_body
        """
        tenant = provision_tenant(with_approver=False)

        good = validate_success(
            api.create_template(
                create_template_payload(
                    tenant.id,
                    name="Good",
                    subject="S",
                    html_body='<p>x</p><a href="{{unsubscribe_url}}">u</a>',
                ),
                tenant.author_headers,
            ),
            201,
        )
        bad = validate_success(
            api.create_template(
                create_template_payload(
                    tenant.id, name="Bad", subject="S", html_body="<p>no footer</p>"
                ),
                tenant.author_headers,
            ),
            201,
        )

        assert_template(good)
        assert_template(bad)
        assert good["has_unsubscribe_link"] is True
        assert bad["has_unsubscribe_link"] is False
        assert good["status"] == "DRAFT"

    def test_publishing_a_published_template_a_second_time_is_rejected(self, api):
        """PRD §3.5: "A template is born in `DRAFT` and may be published once, moving
        `DRAFT → PUBLISHED`; publishing from any other state is refused with `ERR_INVALID_STATE`."
        PRD §2.4: "`version`, an integer that starts at 1 and increments by exactly one on every
        mutation of that resource."

        Design: Corner/state_machines/publish_template_twice_rejects_second
        """
        tenant = provision_tenant(with_approver=False)
        published = create_published_template(tenant)
        assert published["version"] == 2

        resp = api.publish_template(published["id"], tenant.author_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        after = validate_success(api.get_template(published["id"], tenant.author_headers))
        assert after["version"] == 2, "a rejected call is not a mutation and must not bump version"
        assert after["status"] == "PUBLISHED"

    def test_publish_increments_version_and_refreshes_updated_at(self, api):
        """PRD §2.4: "Mutable resources — `Account`, `AccountUser`, `Audience`, `Subscriber`,
        `ImportJob`, `Segment`, `Template`, `Campaign`, `Send`, `Journey`, `JourneyEnrollment` and
        `BillingCycle` — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on
        every mutation, and `version`, an integer that starts at 1 and increments by exactly one on
        every mutation of that resource."
        PRD §2.4: "Every persisted resource carries an `id` — a server-minted UUID with no type
        prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits
        recording when the row first appeared."

        Design: Corner/cross_cutting_layers/template_version_increments_on_every_mutation
        """
        tenant = provision_tenant(with_approver=False)
        draft = create_template(tenant)
        assert draft["version"] == 1
        created_at = draft["created_at"]

        set_clock("2026-05-04T09:00:00Z")
        published = validate_success(api.publish_template(draft["id"], tenant.author_headers))

        assert published["version"] == 2
        assert published["created_at"] == created_at, "created_at is never rewritten"
        assert published["updated_at"] == "2026-05-04T09:00:00.000Z"


class TestCampaignCreationReferences:
    def test_campaign_naming_an_unknown_template_is_a_not_found(self, api):
        """PRD §2.5: "Body foreign keys resolve — the same not-found family plus
        `ERR_SEGMENT_NOT_FOUND`, applying to account creation of audiences, template creation,
        campaign creation, journey creation, and event injection."

        Design: Corner/errors/err_template_not_found_on_campaign_create
        """
        tenant = provision_tenant(with_approver=False)
        audience = create_audience(tenant, double_optin_required=False)

        resp = api.create_campaign(
            create_campaign_payload(tenant.id, audience["id"], NON_EXISTENT_UUID),
            tenant.author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_NOT_FOUND.value)

    def test_campaign_naming_an_unknown_segment_is_a_not_found(self, api):
        """PRD §2.5: "Body foreign keys resolve — the same not-found family plus
        `ERR_SEGMENT_NOT_FOUND`, applying to account creation of audiences, template creation,
        campaign creation, journey creation, and event injection."

        Design: Corner/errors/err_segment_not_found_on_campaign_create
        """
        tenant = provision_tenant(with_approver=False)
        audience = create_audience(tenant, double_optin_required=False)
        template = create_template(tenant)

        resp = api.create_campaign(
            create_campaign_payload(
                tenant.id, audience["id"], template["id"], segment_id=NON_EXISTENT_UUID
            ),
            tenant.author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_FOUND.value)

    def test_segment_from_another_audience_is_a_referential_mismatch(self, api):
        """PRD §3.5: "When a `segment_id` is supplied, the segment must belong to the very
        audience the campaign targets, or the creation is refused with
        `ERR_SEGMENT_AUDIENCE_MISMATCH`."

        Design: Corner/validations/segment_from_other_audience_rejected_on_campaign_create
        """
        tenant = provision_tenant(with_approver=False)
        list_1 = create_audience(tenant, name="L1", double_optin_required=False)
        list_2 = create_audience(tenant, name="L2", double_optin_required=False)
        segment = create_segment(list_2["id"], tenant.author_headers, min_engagement_score=0)
        template = create_template(tenant)

        resp = api.create_campaign(
            create_campaign_payload(
                tenant.id, list_1["id"], template["id"], segment_id=segment["id"]
            ),
            tenant.author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEGMENT_AUDIENCE_MISMATCH.value)

        campaigns, _ = validate_paginated(api.list_campaigns(PLATFORM, {"account_id": tenant.id}))
        assert campaigns == []


class TestReviewAuthorisation:
    def test_campaign_author_may_not_claim_the_approver_header(self, api):
        """PRD §2.1: "For the two entity-backed roles, the identifier in `X-User-ID` must name an
        existing `AccountUser` whose `user_role` permits the claimed header. An `AccountUser` whose
        `user_role` is `CAMPAIGN_AUTHOR` may claim only `CampaignAuthor`; one whose `user_role` is
        `COMPLIANCE_APPROVER` may claim only `ComplianceApprover`; one whose `user_role` is `DUAL`
        may claim either. Any other combination — an unknown identifier, or a role the operator's
        `user_role` does not permit — is rejected with `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."

        Design: Corner/validations/campaign_author_claiming_approver_role_identity_mismatch
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        template = create_published_template(tenant)
        campaign = create_campaign(tenant, audience["id"], template["id"])
        validate_success(api.submit_campaign_review(campaign["id"], tenant.author_headers))

        # The author's AccountUser.user_role is CAMPAIGN_AUTHOR, not DUAL.
        resp = api.review_campaign(
            campaign["id"],
            review_payload("APPROVE"),
            make_compliance_approver_headers(tenant.author_id),
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_IDENTITY_MISMATCH.value)
        assert read_campaign(campaign["id"])["status"] == "IN_REVIEW"

    def test_forbidden_role_is_reported_before_the_campaign_is_looked_up(self, api):
        """PRD §2.5: "When several rules could reject the same request, the rule that fires is
        always the earliest one in the following sequence. Implementations must not report a later
        failure while an earlier one is also true."
        PRD §2.1: "A request whose claimed role is well-formed but is not among the roles the
        target operation admits is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/campaigns/{id}/review` | Decide a campaign review | ComplianceApprover |"

        Design: Corner/validations/review_forbidden_role_precedes_campaign_not_found
        """
        tenant = provision_tenant(with_approver=False)

        resp = api.review_campaign(
            NON_EXISTENT_UUID, review_payload("APPROVE"), tenant.author_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_approver_may_not_create_a_campaign(self, api):
        """PRD §2.1: "A request whose claimed role is well-formed but is not among the roles the
        target operation admits is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/campaigns` | Create a campaign in `DRAFT` | CampaignAuthor |"

        Design: Corner/rbac/approver_cannot_create_campaign
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        template = create_template(tenant)

        resp = api.create_campaign(
            create_campaign_payload(tenant.id, audience["id"], template["id"]),
            tenant.approver_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

        campaigns, _ = validate_paginated(api.list_campaigns(PLATFORM, {"account_id": tenant.id}))
        assert campaigns == []

    def test_operator_of_another_account_cannot_submit_this_campaign(self, api):
        """PRD §2.1: "Tenant isolation is absolute for the two entity-backed roles: a
        `CampaignAuthor` or `ComplianceApprover` whose own `AccountUser.account_id` differs from
        the owning account of any resource they touch — the account behind a path identifier, an
        `account_id` in the body, the account owning a referenced template, or the account owning
        the audience behind an audience identifier — is rejected with `ERR_CROSS_ACCOUNT_ACCESS`
        (HTTP 403). `PlatformAdmin` is exempt from this check."

        Design: Corner/validations/author_cannot_schedule_other_accounts_campaign
        """
        tenant_a = provision_tenant(name="A", with_approver=False)
        tenant_b = provision_tenant(name="B", with_approver=False)
        audience = create_audience(tenant_a, double_optin_required=False)
        template = create_template(tenant_a)
        campaign = create_campaign(tenant_a, audience["id"], template["id"])

        resp = api.submit_campaign_review(campaign["id"], tenant_b.author_headers)
        validate_error(resp, ApiErrorId.ERR_CROSS_ACCOUNT_ACCESS.value)
        assert read_campaign(campaign["id"])["status"] == "DRAFT"

    def test_dual_operator_may_approve_a_campaign_written_by_someone_else(self, api):
        """PRD §3.5: "The reviewer's `X-User-ID` must differ from the campaign's
        `created_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES` — and
        this holds even for an operator whose `user_role` is `DUAL` and who is therefore perfectly
        entitled to claim the `ComplianceApprover` header: authorship, not permission, is what
        disqualifies them."
        PRD §3.5: "Passing both, the campaign moves `IN_REVIEW → APPROVED`, `approved_by_user_id`
        is stamped from the reviewer's `X-User-ID`, and the template is *pinned*: `pinned_subject`
        takes the template's `subject`, `pinned_html_body` takes its `html_body`, and
        `pinned_template_version` takes its `version`, freezing exactly what compliance signed off
        on."

        Design: Corner/rbac/dual_user_may_approve_a_campaign_authored_by_someone_else
        """
        tenant = provision_tenant(with_approver=False, with_dual=True)
        audience = create_audience(tenant, double_optin_required=False)
        template = create_published_template(tenant)
        campaign = create_campaign(tenant, audience["id"], template["id"])
        validate_success(api.submit_campaign_review(campaign["id"], tenant.author_headers))

        approved = validate_success(
            api.review_campaign(
                campaign["id"],
                review_payload("APPROVE", note="looks good"),
                make_compliance_approver_headers(tenant.dual_id),
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["created_by_user_id"] == tenant.author_id
        assert approved["approved_by_user_id"] == tenant.dual_id
        assert approved["pinned_template_version"] == 2


class TestSegregationOfDutiesPrecedence:
    def test_dual_author_approving_own_campaign_reports_segregation_of_duties(self, api):
        """PRD §3.5: "The reviewer's `X-User-ID` must differ from the campaign's
        `created_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES` — and
        this holds even for an operator whose `user_role` is `DUAL` and who is therefore perfectly
        entitled to claim the `ComplianceApprover` header: authorship, not permission, is what
        disqualifies them."
        PRD §2.5: "When several rules could reject the same request, the rule that fires is always
        the earliest one in the following sequence. Implementations must not report a later failure
        while an earlier one is also true."

        Design: Difficulty/priority_pair_validation_conflict/review_sod_precedes_missing_unsubscribe_link
        """
        account, dual = create_dual_only_tenant()
        author_headers = make_campaign_author_headers(dual["id"])
        audience = validate_success(
            api.create_audience(
                {
                    "account_id": account["id"],
                    "name": "Main",
                    "default_from_email": "hi@acme.com",
                    "double_optin_required": False,
                },
                author_headers,
            ),
            201,
        )
        template = validate_success(
            api.create_template(
                create_template_payload(
                    account["id"], name="NoUnsub", html_body=NON_COMPLIANT_HTML_BODY
                ),
                author_headers,
            ),
            201,
        )
        published = validate_success(api.publish_template(template["id"], author_headers))
        assert published["has_unsubscribe_link"] is False

        campaign = validate_success(
            api.create_campaign(
                create_campaign_payload(account["id"], audience["id"], template["id"]),
                author_headers,
            ),
            201,
        )
        validate_success(api.submit_campaign_review(campaign["id"], author_headers))

        # The DUAL operator authored this campaign AND its template is missing the merge tag.
        resp = api.review_campaign(
            campaign["id"],
            review_payload("APPROVE"),
            make_compliance_approver_headers(dual["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_sod_rejection_leaves_the_campaign_in_review_without_pins(self, api):
        """PRD §3.5: "The reviewer's `X-User-ID` must differ from the campaign's
        `created_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES` — and
        this holds even for an operator whose `user_role` is `DUAL` and who is therefore perfectly
        entitled to claim the `ComplianceApprover` header: authorship, not permission, is what
        disqualifies them."
        PRD §3.5: "The campaign is born in `DRAFT` with `approved_by_user_id`, `review_note`,
        `pinned_subject`, `pinned_html_body`, `pinned_template_version`, `scheduled_at`,
        `send_window_minutes`, `winning_variant` and `winner_selected_at` all null,
        `recipient_snapshot_ids` empty, and `recipient_count`, `reserved_credit_count` and
        `send_charge_cents` all 0."

        Design: Difficulty/priority_pair_validation_conflict/review_sod_precedes_missing_unsubscribe_link
        """
        account, dual = create_dual_only_tenant()
        author_headers = make_campaign_author_headers(dual["id"])
        audience = validate_success(
            api.create_audience(
                {
                    "account_id": account["id"],
                    "name": "Main",
                    "default_from_email": "hi@acme.com",
                    "double_optin_required": False,
                },
                author_headers,
            ),
            201,
        )
        template = validate_success(
            api.create_template(
                create_template_payload(
                    account["id"], name="NoUnsub", html_body=NON_COMPLIANT_HTML_BODY
                ),
                author_headers,
            ),
            201,
        )
        validate_success(api.publish_template(template["id"], author_headers))
        campaign = validate_success(
            api.create_campaign(
                create_campaign_payload(account["id"], audience["id"], template["id"]),
                author_headers,
            ),
            201,
        )
        validate_success(api.submit_campaign_review(campaign["id"], author_headers))

        resp = api.review_campaign(
            campaign["id"],
            review_payload("APPROVE"),
            make_compliance_approver_headers(dual["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        after = read_campaign(campaign["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["approved_by_user_id"] is None
        assert after["pinned_subject"] is None

    def test_missing_unsubscribe_link_blocks_approval_by_a_different_operator(self, api):
        """PRD §3.5: "On `APPROVE`, two CAN-SPAM checks run in order. The campaign's template must
        be `PUBLISHED`, or the decision is refused with `ERR_TEMPLATE_NOT_PUBLISHED`; and that
        template's `has_unsubscribe_link` must be true, or the decision is refused with
        `ERR_MISSING_UNSUBSCRIBE_LINK`."

        Design: Corner/errors/err_missing_unsubscribe_link_on_approve
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        template = create_published_template(
            tenant, html_body=NON_COMPLIANT_HTML_BODY, name="NoUnsub"
        )
        campaign = create_campaign(tenant, audience["id"], template["id"])
        validate_success(api.submit_campaign_review(campaign["id"], tenant.author_headers))

        resp = api.review_campaign(
            campaign["id"], review_payload("APPROVE"), tenant.approver_headers
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_UNSUBSCRIBE_LINK.value)

        after = read_campaign(campaign["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["pinned_html_body"] is None


class TestTemplatePublishGate:
    def test_approve_is_rejected_while_the_template_is_still_draft(self, api):
        """PRD §3.5: "On `APPROVE`, two CAN-SPAM checks run in order. The campaign's template must
        be `PUBLISHED`, or the decision is refused with `ERR_TEMPLATE_NOT_PUBLISHED`; and that
        template's `has_unsubscribe_link` must be true, or the decision is refused with
        `ERR_MISSING_UNSUBSCRIBE_LINK`."
        PRD §3.5: "A template is born in `DRAFT` and may be published once, moving
        `DRAFT → PUBLISHED`; publishing from any other state is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/campaign_approve_gated_on_template_published
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        template = create_template(tenant, name="T1")
        assert template["status"] == "DRAFT"
        assert template["has_unsubscribe_link"] is True, "only the publish gate may fail here"

        campaign = create_campaign(tenant, audience["id"], template["id"])
        validate_success(api.submit_campaign_review(campaign["id"], tenant.author_headers))

        resp = api.review_campaign(
            campaign["id"], review_payload("APPROVE"), tenant.approver_headers
        )
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED.value)
        assert read_campaign(campaign["id"])["status"] == "IN_REVIEW"

    def test_the_same_approve_succeeds_once_the_template_is_published(self, api):
        """PRD §3.5: "On `APPROVE`, two CAN-SPAM checks run in order. The campaign's template must
        be `PUBLISHED`, or the decision is refused with `ERR_TEMPLATE_NOT_PUBLISHED`; and that
        template's `has_unsubscribe_link` must be true, or the decision is refused with
        `ERR_MISSING_UNSUBSCRIBE_LINK`."
        PRD §3.5: "Passing both, the campaign moves `IN_REVIEW → APPROVED`, `approved_by_user_id`
        is stamped from the reviewer's `X-User-ID`, and the template is *pinned*: `pinned_subject`
        takes the template's `subject`, `pinned_html_body` takes its `html_body`, and
        `pinned_template_version` takes its `version`, freezing exactly what compliance signed off
        on."

        Design: Difficulty/cross_entity_state_dependency/campaign_approve_gated_on_template_published
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        template = create_template(tenant, name="T1")
        campaign = create_campaign(tenant, audience["id"], template["id"])
        validate_success(api.submit_campaign_review(campaign["id"], tenant.author_headers))

        validate_error(
            api.review_campaign(campaign["id"], review_payload("APPROVE"), tenant.approver_headers),
            ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED.value,
        )

        validate_success(api.publish_template(template["id"], tenant.author_headers))
        approved = validate_success(
            api.review_campaign(campaign["id"], review_payload("APPROVE"), tenant.approver_headers)
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == tenant.approver_id
        assert approved["pinned_template_version"] == 2


class TestReviewRevisionCycle:
    def test_request_changes_returns_the_campaign_to_draft_and_clears_the_pins(self, api):
        """PRD §3.5: "On `REQUEST_CHANGES`, the campaign cycles back `IN_REVIEW → DRAFT`,
        `approved_by_user_id` is cleared to null, and all three pins — `pinned_subject`,
        `pinned_html_body` and `pinned_template_version` — are cleared to null as well."
        PRD §3.5: "The reviewer supplies a `decision` of either `APPROVE` or `REQUEST_CHANGES`,
        plus an optional `note` that is recorded into `review_note` either way."

        Design: Difficulty/non_linear_state_machine/campaign_review_revision_cycle_in_review_draft_in_review_approved
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        template = create_published_template(tenant)
        campaign = create_campaign(tenant, audience["id"], template["id"])
        validate_success(api.submit_campaign_review(campaign["id"], tenant.author_headers))

        rejected = validate_success(
            api.review_campaign(
                campaign["id"],
                review_payload("REQUEST_CHANGES", note="subject is too long"),
                tenant.approver_headers,
            )
        )
        assert rejected["status"] == "DRAFT"
        assert rejected["approved_by_user_id"] is None
        assert rejected["pinned_subject"] is None
        assert rejected["pinned_html_body"] is None
        assert rejected["pinned_template_version"] is None
        assert rejected["review_note"] == "subject is too long"

    def test_a_resubmitted_campaign_can_be_approved_and_repins_the_template(self, api):
        """PRD §3.5: "The revision loop is unbounded: the author may resubmit and the reviewer may
        re-decide any number of times, and each `APPROVE` re-pins from the template as it stands at
        that moment."
        PRD §3.5: "Passing both, the campaign moves `IN_REVIEW → APPROVED`, `approved_by_user_id`
        is stamped from the reviewer's `X-User-ID`, and the template is *pinned*: `pinned_subject`
        takes the template's `subject`, `pinned_html_body` takes its `html_body`, and
        `pinned_template_version` takes its `version`, freezing exactly what compliance signed off
        on."

        Design: Difficulty/non_linear_state_machine/campaign_review_revision_cycle_in_review_draft_in_review_approved
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        template = create_published_template(tenant, subject="Spring Sale")
        campaign = create_campaign(tenant, audience["id"], template["id"])
        validate_success(api.submit_campaign_review(campaign["id"], tenant.author_headers))
        validate_success(
            api.review_campaign(
                campaign["id"],
                review_payload("REQUEST_CHANGES", note="subject is too long"),
                tenant.approver_headers,
            )
        )

        # DRAFT -> IN_REVIEW is traversed a second time in the same lifetime.
        validate_success(api.submit_campaign_review(campaign["id"], tenant.author_headers))
        approved = validate_success(
            api.review_campaign(
                campaign["id"], review_payload("APPROVE", note="ship it"), tenant.approver_headers
            )
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == tenant.approver_id
        assert approved["pinned_subject"] == "Spring Sale"
        assert approved["pinned_template_version"] == 2
        assert approved["review_note"] == "ship it"
