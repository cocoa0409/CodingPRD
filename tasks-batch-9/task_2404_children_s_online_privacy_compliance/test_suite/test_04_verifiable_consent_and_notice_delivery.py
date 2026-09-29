"""Verifiable consent: the pinned assurance tier, notice delivery and the audit gate."""

from test_helpers import (
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    api_client,
    assert_instant,
    create_consent,
    create_integration,
    create_notice,
    create_service,
    deliver_notice_to_consent,
    grant_consent,
    mixed_audience_service,
    open_verification,
    publish_notice,
    published_notice,
    read_consent,
    read_integration,
    read_notice,
    read_service,
    set_integration_status,
    validate_error,
)


class TestRequiredTierPinnedAtCreation:
    """The required tier is a snapshot of the approved integration set, frozen on the row."""

    def test_01_base_requirement_is_the_highest_tier_among_the_intended_uses(self):
        """With no qualifying integration approved, nothing is added to the base.

        "The base requirement is the highest tier among the request's `intended_uses`. To
        that base the system adds one if, at this moment, the service has at least one
        third-party integration whose `status` is `APPROVED` ... otherwise it adds
        nothing." `CONTESTS_PRIZES` is tier 2 and `KNOWLEDGE_BASED_AUTH` is tier 2.

        Design: Difficulty/combinatorial_formula/required_tier_pinned_snapshot_vs_live_integration_set
        """
        service = mixed_audience_service(name="Pinned Tier Service")
        notice = published_notice(service["id"])

        consent = create_consent(
            service["id"],
            notice["id"],
            parent_email="parent.a@example.com",
            child_pseudonym="child-a",
            intended_uses=["PARTICIPATION_CORE", "CONTESTS_PRIZES"],
            consent_method="KNOWLEDGE_BASED_AUTH",
        )

        assert consent["required_tier_at_creation"] == 2, (
            "the highest intended-use tier is 2 and no bump applies, got "
            f"{consent['required_tier_at_creation']}"
        )
        assert consent["method_assurance_tier"] == 2, (
            f"KNOWLEDGE_BASED_AUTH is tier 2, got {consent['method_assurance_tier']}"
        )

        deliver_notice_to_consent(consent["id"])
        open_verification(consent["id"])
        granted = grant_consent(consent["id"])

        assert granted["status"] == "GRANTED", (
            f"a tier-2 method meets a tier-2 requirement, got {granted['status']}"
        )

    def test_02_an_approved_persistent_identifier_integration_bumps_the_next_request(self):
        """The bump is read from the approved set at the creation instant.

        The system "adds one if, at this moment, the service has at least one third-party
        integration whose `status` is `APPROVED`, whose `collects_persistent_identifier` is
        true, and whose `integration_type` is `BEHAVIORAL_AD_NETWORK`, `ANALYTICS` or
        `SOCIAL_PLUGIN`", and "The sum is then capped at 3".

        Design: Difficulty/combinatorial_formula/required_tier_pinned_snapshot_vs_live_integration_set
        """
        service = mixed_audience_service(name="Bumped Tier Service")
        notice = published_notice(service["id"], disclosed_integration_vendors=["MetricPulse"])
        integration = create_integration(
            service["id"],
            vendor_name="MetricPulse",
            integration_type="ANALYTICS",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        approved = set_integration_status(integration["id"], "APPROVED")
        assert approved["exposure_points"] == 30
        after_approval = read_service(service["id"])
        assert after_approval["third_party_exposure_points"] == 30
        assert after_approval["compliance_posture"] == "OPEN"

        consent = create_consent(
            service["id"],
            notice["id"],
            parent_email="parent.b@example.com",
            child_pseudonym="child-b",
            intended_uses=["PARTICIPATION_CORE", "CONTESTS_PRIZES"],
            consent_method="KNOWLEDGE_BASED_AUTH",
        )

        assert consent["required_tier_at_creation"] == 3, (
            "a base of 2 plus the integration bump is 3, got "
            f"{consent['required_tier_at_creation']}"
        )

    def test_03_the_pinned_tier_is_never_re_derived_at_grant_time(self):
        """A request created before the approval keeps the tier it was created with.

        "`required_tier_at_creation` is computed once, from the snapshot of approved
        integrations taken at the creation instant, and is frozen on the row. It is never
        re-derived at grant time — not even though approving another integration later
        would have raised the bump".

        Design: Difficulty/combinatorial_formula/required_tier_pinned_snapshot_vs_live_integration_set
        """
        service = mixed_audience_service(name="Frozen Tier Service")
        notice = published_notice(service["id"], disclosed_integration_vendors=["MetricPulse"])
        consent = create_consent(
            service["id"],
            notice["id"],
            parent_email="parent.a@example.com",
            child_pseudonym="child-a",
            intended_uses=["PARTICIPATION_CORE", "CONTESTS_PRIZES"],
            consent_method="KNOWLEDGE_BASED_AUTH",
        )
        assert consent["required_tier_at_creation"] == 2

        integration = create_integration(
            service["id"],
            vendor_name="MetricPulse",
            integration_type="ANALYTICS",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")

        deliver_notice_to_consent(consent["id"])
        open_verification(consent["id"])
        granted = grant_consent(consent["id"])

        assert granted["status"] == "GRANTED", (
            "the pinned tier of 2 still governs the grant, got " f"{granted['status']}"
        )
        assert granted["required_tier_at_creation"] == 2, (
            "the pinned tier must not be re-derived, got "
            f"{granted['required_tier_at_creation']}"
        )

    def test_04_a_method_below_the_pinned_requirement_cannot_grant(self):
        """A tier-2 method cannot satisfy a tier-3 requirement.

        "`method_assurance_tier` must be greater than or equal to
        `required_tier_at_creation`, otherwise `ERR_CONSENT_METHOD_TIER_INSUFFICIENT`."

        Design: Difficulty/combinatorial_formula/required_tier_pinned_snapshot_vs_live_integration_set
        """
        service = mixed_audience_service(name="Insufficient Method Service")
        notice = published_notice(service["id"], disclosed_integration_vendors=["MetricPulse"])
        first = create_consent(
            service["id"],
            notice["id"],
            parent_email="parent.a@example.com",
            child_pseudonym="child-a",
            intended_uses=["PARTICIPATION_CORE", "CONTESTS_PRIZES"],
            consent_method="KNOWLEDGE_BASED_AUTH",
        )
        deliver_notice_to_consent(first["id"])
        open_verification(first["id"])
        grant_consent(first["id"])

        integration = create_integration(
            service["id"],
            vendor_name="MetricPulse",
            integration_type="ANALYTICS",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")

        second = create_consent(
            service["id"],
            notice["id"],
            parent_email="parent.b@example.com",
            child_pseudonym="child-b",
            intended_uses=["PARTICIPATION_CORE", "CONTESTS_PRIZES"],
            consent_method="KNOWLEDGE_BASED_AUTH",
        )
        assert second["required_tier_at_creation"] == 3
        deliver_notice_to_consent(second["id"])
        open_verification(second["id"])

        validate_error(
            api_client.set_consent_request_status(
                second["id"],
                {"to_status": "GRANTED", "verification_evidence_code": "EVID-002"},
                OFFICER_HEADERS,
            ),
            "ERR_CONSENT_METHOD_TIER_INSUFFICIENT",
        )

        refused = read_consent(second["id"])
        assert refused["status"] == "PENDING_VERIFICATION", (
            f"the refused grant leaves the request pending, got {refused['status']}"
        )
        final = read_service(service["id"])
        assert final["active_consent_count"] == 1, (
            "only the first request was granted, got " f"{final['active_consent_count']}"
        )
        assert final["granted_disclosure_consent_count"] == 0, (
            "neither request names a disclosure use, got "
            f"{final['granted_disclosure_consent_count']}"
        )


class TestDirectNoticeDelivery:
    """Delivery is gated on the notice's publication state and on the channel fit."""

    def test_05_delivery_against_a_draft_notice_is_refused(self):
        """A notice that is not published cannot be delivered.

        "The referenced notice must have `status` of `PUBLISHED`; a draft or superseded
        revision is refused with `ERR_NOTICE_NOT_PUBLISHED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/direct_notice_delivery_gated_by_notice_publication_and_channel
        """
        service = create_service(name="Draft Notice Service")
        notice = create_notice(service["id"])
        assert notice["status"] == "DRAFT"
        consent = create_consent(
            service["id"],
            notice["id"],
            parent_email="parent@example.com",
            child_pseudonym="child-1",
        )

        validate_error(
            api_client.set_consent_request_status(
                consent["id"], {"to_status": "NOTICE_DELIVERED"}, OFFICER_HEADERS
            ),
            "ERR_NOTICE_NOT_PUBLISHED",
        )

        refused = read_consent(consent["id"])
        assert refused["status"] == "INITIATED", (
            f"the refused delivery leaves the request initiated, got {refused['status']}"
        )
        assert refused["notice_delivered_at"] is None, (
            f"a refused delivery stamps nothing, got {refused['notice_delivered_at']}"
        )

    def test_06_publishing_the_notice_unlocks_delivery_and_sets_the_fourteen_day_deadline(self):
        """Once published, the same delivery call succeeds and starts the clock.

        "A successful delivery stamps `notice_delivered_at` with the current logical-clock
        instant and sets `verification_deadline_at` to two weeks — fourteen days — after
        that instant." The clock's startup value is `2026-08-01T00:00:00Z`.

        Design: Difficulty/cross_entity_state_dependency/direct_notice_delivery_gated_by_notice_publication_and_channel
        """
        service = create_service(name="Published Notice Service")
        notice = create_notice(service["id"])
        consent = create_consent(
            service["id"],
            notice["id"],
            parent_email="parent@example.com",
            child_pseudonym="child-1",
        )
        published = publish_notice(notice["id"])
        assert published["status"] == "PUBLISHED"
        assert_instant(published["published_at"], STARTUP_CLOCK, "published_at")

        delivered = deliver_notice_to_consent(consent["id"])

        assert delivered["status"] == "NOTICE_DELIVERED", (
            f"delivery against a published notice succeeds, got {delivered['status']}"
        )
        assert_instant(delivered["notice_delivered_at"], STARTUP_CLOCK, "notice_delivered_at")
        assert_instant(
            delivered["verification_deadline_at"],
            "2026-08-15T00:00:00Z",
            "verification_deadline_at",
        )

    def test_07_a_school_authorization_method_needs_a_school_intermediary_channel(self):
        """The channel must fit the method, even on a published notice.

        "when `consent_method` is `SCHOOL_AUTHORIZATION`, the referenced notice's
        `delivery_channel` must be `SCHOOL_INTERMEDIARY`, otherwise the delivery is refused
        with `ERR_NOTICE_CHANNEL_INCOMPATIBLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/direct_notice_delivery_gated_by_notice_publication_and_channel
        """
        service = create_service(name="Channel Mismatch Service")
        notice = published_notice(service["id"], delivery_channel="EMAIL")
        email_consent = create_consent(
            service["id"],
            notice["id"],
            parent_email="parent@example.com",
            child_pseudonym="child-1",
        )
        deliver_notice_to_consent(email_consent["id"])

        school_consent = create_consent(
            service["id"],
            notice["id"],
            parent_email="school.parent@example.com",
            child_pseudonym="child-2",
            consent_method="SCHOOL_AUTHORIZATION",
        )

        validate_error(
            api_client.set_consent_request_status(
                school_consent["id"], {"to_status": "NOTICE_DELIVERED"}, OFFICER_HEADERS
            ),
            "ERR_NOTICE_CHANNEL_INCOMPATIBLE",
        )

        refused = read_consent(school_consent["id"])
        assert refused["status"] == "INITIATED", (
            f"the refused delivery leaves the request initiated, got {refused['status']}"
        )
        assert refused["notice_delivered_at"] is None
        undisturbed = read_consent(email_consent["id"])
        assert undisturbed["status"] == "NOTICE_DELIVERED", (
            "the compatible request is untouched by the refusal, got "
            f"{undisturbed['status']}"
        )


class TestIntegrationAuditGatePrecedesDisclosure:
    """The disclosure-basis gate is reached before the disclosure-reference gate."""

    def test_08_a_child_directed_social_plugin_without_a_disclosure_consent_is_refused(self):
        """With neither a disclosure consent nor a disclosure reference, the tier gate wins.

        The precedence list places "14. **Third-party integration audit gate**, else
        `ERR_BEHAVIORAL_AD_TIER_UNMET` (422)" before "18. **Integration disclosure**, else
        `ERR_INTEGRATION_NOT_DISCLOSED` (422)", and "the first failing check determines the
        response."

        Design: Difficulty/priority_pair_validation_conflict/integration_safety_gate_p95_beats_disclosure_reference_p105
        """
        service = mixed_audience_service(name="Social Plugin Gate Service")
        integration = create_integration(
            service["id"],
            vendor_name="ShadowReach Ads",
            integration_type="SOCIAL_PLUGIN",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        assert integration["disclosed_in_notice"] is False, (
            "with no published notice the flag defaults to false, got "
            f"{integration['disclosed_in_notice']}"
        )
        assert integration["exposure_points"] == 50, (
            "a SOCIAL_PLUGIN collecting a persistent identifier carries 50 points, got "
            f"{integration['exposure_points']}"
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")

        validate_error(
            api_client.set_third_party_integration_status(
                integration["id"], {"to_status": "APPROVED"}, OFFICER_HEADERS
            ),
            "ERR_BEHAVIORAL_AD_TIER_UNMET",
        )

        assert read_integration(service["id"], integration["id"])["status"] == "AUDIT_PENDING"

    def test_09_with_a_disclosure_consent_granted_the_undisclosed_reference_surfaces(self):
        """Satisfying the tier gate exposes the disclosure-reference failure beneath it.

        "the service's `granted_disclosure_consent_count` must be at least 1" — the count
        of "granted requests whose `intended_uses` include at least one of
        `PERSONALIZED_ADVERTISING`, `THIRD_PARTY_DISCLOSURE` or `PUBLIC_POSTING`". The
        integration must still be disclosed: "`disclosed_in_notice` must be true, otherwise
        the approval is refused with `ERR_INTEGRATION_NOT_DISCLOSED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/integration_safety_gate_p95_beats_disclosure_reference_p105
        """
        service = mixed_audience_service(name="Disclosure Reference Service")
        integration = create_integration(
            service["id"],
            vendor_name="ShadowReach Ads",
            integration_type="SOCIAL_PLUGIN",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        notice = published_notice(service["id"])
        consent = create_consent(
            service["id"],
            notice["id"],
            parent_email="disclosure.parent@example.com",
            child_pseudonym="child-9",
            intended_uses=["PARTICIPATION_CORE", "PERSONALIZED_ADVERTISING"],
            consent_method="GOVT_ID_MATCH",
        )
        assert consent["required_tier_at_creation"] == 3
        deliver_notice_to_consent(consent["id"])
        open_verification(consent["id"])
        grant_consent(consent["id"])
        with_consent = read_service(service["id"])
        assert with_consent["granted_disclosure_consent_count"] == 1

        validate_error(
            api_client.set_third_party_integration_status(
                integration["id"], {"to_status": "APPROVED"}, OFFICER_HEADERS
            ),
            "ERR_INTEGRATION_NOT_DISCLOSED",
        )

        assert read_integration(service["id"], integration["id"])["status"] == "AUDIT_PENDING"

    def test_10_publishing_a_revision_that_names_the_vendor_unlocks_the_approval(self):
        """A new revision naming the vendor supersedes the old one and unlocks approval.

        "publishing a notice that names a vendor is what unlocks that vendor's audit
        approval", and publication "moves any other notice of the same service that was
        `PUBLISHED` to `SUPERSEDED`". Fifty approved points then reach clause 4 of the
        posture computation.

        Design: Difficulty/priority_pair_validation_conflict/integration_safety_gate_p95_beats_disclosure_reference_p105
        """
        service = mixed_audience_service(name="Unlocked Approval Service")
        integration = create_integration(
            service["id"],
            vendor_name="ShadowReach Ads",
            integration_type="SOCIAL_PLUGIN",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        first_notice = published_notice(service["id"])
        consent = create_consent(
            service["id"],
            first_notice["id"],
            parent_email="disclosure.parent@example.com",
            child_pseudonym="child-9",
            intended_uses=["PARTICIPATION_CORE", "PERSONALIZED_ADVERTISING"],
            consent_method="GOVT_ID_MATCH",
        )
        deliver_notice_to_consent(consent["id"])
        open_verification(consent["id"])
        grant_consent(consent["id"])

        second_notice = published_notice(
            service["id"],
            notice_label="Notice r2",
            disclosed_integration_vendors=["ShadowReach Ads"],
        )

        assert read_notice(service["id"], first_notice["id"])["status"] == "SUPERSEDED", (
            "the earlier published revision must be superseded"
        )
        assert second_notice["status"] == "PUBLISHED"
        assert read_integration(service["id"], integration["id"])["disclosed_in_notice"] is True, (
            "publishing a notice naming the vendor sets disclosed_in_notice true"
        )

        approved = set_integration_status(integration["id"], "APPROVED")

        assert approved["status"] == "APPROVED"
        assert approved["exposure_points"] == 50
        final = read_service(service["id"])
        assert final["third_party_exposure_points"] == 50, (
            f"the approved points join the total, got {final['third_party_exposure_points']}"
        )
        assert final["compliance_posture"] == "RESTRICTED", (
            f"50 points restricts the service, got {final['compliance_posture']}"
        )
        assert final["audit_decision_count"] == 1
        assert final["open_audit_count"] == 0
