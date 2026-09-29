"""Computed lists, pinned tiers and the clock-derived safe harbor ladder."""

from test_helpers import (
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    api_client,
    assert_instant,
    assert_missing_content_keys_in_canonical_order,
    assert_neutrality_codes_in_declared_order,
    assert_parental_notice,
    certified_service,
    create_age_screen,
    create_consent,
    create_service,
    deliver_notice_to_consent,
    grant_consent,
    mixed_audience_service,
    open_verification,
    parental_notice_payload,
    publish_notice,
    published_notice,
    read_age_screen,
    read_assessment,
    read_consent,
    read_notice,
    read_service,
    service_version,
    set_clock,
    set_screen_status,
    validate_error,
    validate_success,
)


class TestNeutralityCodesInDeclaredOrder:
    """Every violation comes from its own guard, and the list order is fixed."""

    def test_01_all_four_codes_appear_in_the_declared_order_and_block_activation(self):
        """A screen carrying any code cannot go live.

        The codes "appear in this fixed order regardless of which are present:
        `PREFILLED_AGE` when `default_prefilled_age` is not null; `RETRY_ALLOWED` when
        `retry_allowed_on_fail` is true; `OUTCOME_NOT_PERSISTED` when
        `outcome_session_persisted` is false; and `UNVERIFIED_INHERIT` when `mechanism` is
        `ACCOUNT_AGE_INHERIT` and `inherited_from_verified_account` is false." "Activation is
        refused with `ERR_AGE_SCREEN_NOT_NEUTRAL` (HTTP 422) while
        `neutrality_violation_codes` is non-empty".

        Design: Corner/calculations/neutrality_violation_codes_accumulate_in_declared_order
        """
        service = mixed_audience_service(name="Neutrality Order Service")
        offending = create_age_screen(
            service["id"],
            mechanism="ACCOUNT_AGE_INHERIT",
            default_prefilled_age=8,
            retry_allowed_on_fail=True,
            outcome_session_persisted=False,
            inherited_from_verified_account=False,
        )

        assert offending["neutrality_violation_codes"] == [
            "PREFILLED_AGE",
            "RETRY_ALLOWED",
            "OUTCOME_NOT_PERSISTED",
            "UNVERIFIED_INHERIT",
        ], (
            "all four guards fire, in the declared order, got "
            f"{offending['neutrality_violation_codes']}"
        )
        assert_neutrality_codes_in_declared_order(offending["neutrality_violation_codes"])

        in_review = set_screen_status(offending["id"], "IN_REVIEW", ENGINEER_HEADERS)
        assert in_review["neutrality_violation_codes"] == [
            "PREFILLED_AGE",
            "RETRY_ALLOWED",
            "OUTCOME_NOT_PERSISTED",
            "UNVERIFIED_INHERIT",
        ], "submission recomputes the verdict from the same field values"

        validate_error(
            api_client.set_age_screen_status(
                offending["id"], {"to_status": "ACTIVE"}, OFFICER_HEADERS
            ),
            "ERR_AGE_SCREEN_NOT_NEUTRAL",
        )
        assert read_age_screen(service["id"], offending["id"])["status"] == "IN_REVIEW", (
            "the refused activation left the screen under review"
        )

    def test_02_the_inherit_code_needs_its_mechanism_and_a_clean_screen_activates(self):
        """Two of the four guards are silent on a date-of-birth screen.

        "`UNVERIFIED_INHERIT` cannot arise on a `NEUTRAL_DOB_ENTRY` or `AGE_RANGE_SELECT`
        screen no matter what `inherited_from_verified_account` says, because the mechanism
        condition is part of the test." "A fully neutral screen carries an empty list." "A
        successful activation stamps `activated_at` with the current logical-clock instant".

        Design: Corner/calculations/neutrality_violation_codes_accumulate_in_declared_order
        """
        service = mixed_audience_service(name="Neutrality Order Service")

        two_codes = create_age_screen(
            service["id"],
            mechanism="NEUTRAL_DOB_ENTRY",
            retry_allowed_on_fail=True,
            outcome_session_persisted=False,
            inherited_from_verified_account=False,
        )
        assert two_codes["neutrality_violation_codes"] == [
            "RETRY_ALLOWED",
            "OUTCOME_NOT_PERSISTED",
        ], (
            "the omitted prefilled age and the wrong mechanism silence two guards, got "
            f"{two_codes['neutrality_violation_codes']}"
        )

        clean = create_age_screen(
            service["id"],
            mechanism="NEUTRAL_DOB_ENTRY",
            retry_allowed_on_fail=False,
            outcome_session_persisted=True,
        )
        assert clean["neutrality_violation_codes"] == []

        set_screen_status(clean["id"], "IN_REVIEW", ENGINEER_HEADERS)
        activated = set_screen_status(clean["id"], "ACTIVE", OFFICER_HEADERS)

        assert activated["status"] == "ACTIVE"
        assert_instant(activated["activated_at"], STARTUP_CLOCK, "activated_at")


class TestMissingContentKeysInCanonicalOrder:
    """The gap list follows the specification's order, not the client's."""

    def test_03_an_incomplete_draft_is_created_but_cannot_be_published(self):
        """Incompleteness is a publication error, not a drafting error.

        "The notice's computed `missing_content_keys` is exactly the required sections that do
        not appear in `content_keys`, listed in that canonical order rather than in the order
        the client supplied — and duplicates within `content_keys` are ignored". "Publication
        moves it `DRAFT → PUBLISHED` and is refused with `ERR_NOTICE_CONTENT_INCOMPLETE`
        (HTTP 422) while `missing_content_keys` is non-empty." "Operations that bring a new
        resource into existence return `201 Created`."

        Design: Corner/calculations/missing_notice_content_keys_are_listed_in_declared_order_and_block_publish
        """
        service = create_service(name="Partial Notice Service")
        partial = validate_success(
            api_client.create_parental_notice(
                parental_notice_payload(
                    service["id"],
                    service_version(service["id"]),
                    [
                        "RETENTION_AND_DISPOSAL",
                        "USE_PURPOSES",
                        "USE_PURPOSES",
                        "ELEMENTS_COLLECTED",
                    ],
                    notice_label="Partial notice",
                    delivery_channel="EMAIL",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert_parental_notice(partial)
        assert partial["status"] == "DRAFT"
        assert partial["missing_content_keys"] == [
            "OPERATOR_IDENTITY_CONTACT",
            "THIRD_PARTY_DISCLOSURE",
            "PARENTAL_RIGHTS",
            "NO_CONDITIONING_OF_PARTICIPATION",
        ], (
            "the gaps follow the canonical section order and the duplicate counts once, got "
            f"{partial['missing_content_keys']}"
        )
        assert_missing_content_keys_in_canonical_order(partial["missing_content_keys"])

        validate_error(
            api_client.publish_parental_notice(partial["id"], OFFICER_HEADERS),
            "ERR_NOTICE_CONTENT_INCOMPLETE",
        )
        assert read_notice(service["id"], partial["id"])["status"] == "DRAFT", (
            "the refused publication left the draft alone"
        )

    def test_04_a_complete_notice_supplied_out_of_order_publishes(self):
        """A reverse-ordered input still leaves an empty set difference.

        "Seven content sections are required of a direct notice ... A complete notice has an
        empty `missing_content_keys`." "A successful publication does three things beyond
        setting `status` and stamping `published_at` with the current logical-clock instant."

        Design: Corner/calculations/missing_notice_content_keys_are_listed_in_declared_order_and_block_publish
        """
        service = create_service(name="Complete Notice Service")
        complete = validate_success(
            api_client.create_parental_notice(
                parental_notice_payload(
                    service["id"],
                    service_version(service["id"]),
                    [
                        "RETENTION_AND_DISPOSAL",
                        "NO_CONDITIONING_OF_PARTICIPATION",
                        "PARENTAL_RIGHTS",
                        "THIRD_PARTY_DISCLOSURE",
                        "USE_PURPOSES",
                        "ELEMENTS_COLLECTED",
                        "OPERATOR_IDENTITY_CONTACT",
                    ],
                    notice_label="Full notice",
                    delivery_channel="EMAIL",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert complete["missing_content_keys"] == [], (
            f"nothing is missing, got {complete['missing_content_keys']}"
        )

        published = publish_notice(complete["id"])

        assert published["status"] == "PUBLISHED"
        assert_instant(published["published_at"], STARTUP_CLOCK, "published_at")


class TestEmailPlusSecondaryConfirmation:
    """The "plus" step is an independent gate, not a consequence of the tier."""

    def test_05_a_tier_one_email_plus_grant_still_needs_its_confirmation_code(self):
        """The tier clause passes and the confirmation clause fails.

        "when `consent_method` is `EMAIL_PLUS`, a `secondary_confirmation_code` must be
        supplied, otherwise `ERR_EMAIL_PLUS_CONFIRMATION_MISSING`; email-plus is the one
        tier-1 method that relies on a second touch to be credible." "`PARTICIPATION_CORE`
        and `INTERNAL_OPERATIONS` are tier 1", and "`EMAIL_PLUS` and `SCHOOL_AUTHORIZATION`
        are tier 1".

        Design: Corner/calculations/email_plus_grant_requires_its_secondary_confirmation_code
        """
        service = mixed_audience_service(name="Email Plus Service")
        notice = published_notice(service["id"])
        consent = create_consent(
            service["id"],
            notice["id"],
            "guardian.s@x.test",
            "child-605",
            consent_method="EMAIL_PLUS",
            intended_uses=["PARTICIPATION_CORE"],
        )
        assert consent["method_assurance_tier"] == 1
        assert consent["required_tier_at_creation"] == 1, (
            "a core-only request with no approved persistent-identifier integration needs "
            f"tier 1, got {consent['required_tier_at_creation']}"
        )
        assert consent["secondary_confirmation_received"] is False
        deliver_notice_to_consent(consent["id"])
        open_verification(consent["id"])

        validate_error(
            api_client.set_consent_request_status(
                consent["id"],
                {"to_status": "GRANTED", "verification_evidence_code": "EMAIL-S-1"},
                OFFICER_HEADERS,
            ),
            "ERR_EMAIL_PLUS_CONFIRMATION_MISSING",
        )

        refused = read_consent(consent["id"])
        assert refused["status"] == "PENDING_VERIFICATION"
        assert refused["secondary_confirmation_received"] is False

        granted = grant_consent(
            consent["id"], "EMAIL-S-1", secondary_confirmation_code="SEC-S-1"
        )

        assert granted["status"] == "GRANTED"
        assert granted["secondary_confirmation_received"] is True, (
            "a grant that supplied a code records the second touch"
        )
        assert granted["verification_evidence_code"] == "EMAIL-S-1"
        assert_instant(granted["granted_at"], STARTUP_CLOCK, "granted_at")

        after = read_service(service["id"])
        assert after["active_consent_count"] == 1
        assert after["granted_disclosure_consent_count"] == 0, (
            "PARTICIPATION_CORE is not a disclosure use, got "
            f"{after['granted_disclosure_consent_count']}"
        )


class TestDisclosureUseRaisesTheRequiredTier:
    """The requirement is the highest tier among the intended uses."""

    def test_06_adding_a_disclosure_use_rejects_the_tier_one_method_and_admits_tier_three(self):
        """The same method that sufficed for core-only participation now fails.

        "The base requirement is the highest tier among the request's `intended_uses`", and
        "the three uses that put a child's data in front of somebody else —
        `PERSONALIZED_ADVERTISING`, `THIRD_PARTY_DISCLOSURE` and `PUBLIC_POSTING` — are tier
        3." At grant, "`method_assurance_tier` must be greater than or equal to
        `required_tier_at_creation`, otherwise `ERR_CONSENT_METHOD_TIER_INSUFFICIENT`."

        Design: Corner/calculations/third_party_disclosure_use_pins_tier_three_and_rejects_tier_one_methods
        """
        service = mixed_audience_service(name="Disclosure Tier Service")
        notice = published_notice(service["id"])
        weak = create_consent(
            service["id"],
            notice["id"],
            "guardian.t@x.test",
            "child-606",
            consent_method="EMAIL_PLUS",
            intended_uses=["PARTICIPATION_CORE", "THIRD_PARTY_DISCLOSURE"],
        )
        assert weak["method_assurance_tier"] == 1
        assert weak["required_tier_at_creation"] == 3, (
            "the disclosure use raises the bar to tier 3, got "
            f"{weak['required_tier_at_creation']}"
        )
        deliver_notice_to_consent(weak["id"])
        open_verification(weak["id"])

        validate_error(
            api_client.set_consent_request_status(
                weak["id"],
                {
                    "to_status": "GRANTED",
                    "verification_evidence_code": "EMAIL-T-1",
                    "secondary_confirmation_code": "SEC-T-1",
                },
                OFFICER_HEADERS,
            ),
            "ERR_CONSENT_METHOD_TIER_INSUFFICIENT",
        )

        strong = create_consent(
            service["id"],
            notice["id"],
            "guardian.u@x.test",
            "child-607",
            consent_method="GOVT_ID_MATCH",
            intended_uses=["PARTICIPATION_CORE", "THIRD_PARTY_DISCLOSURE"],
        )
        assert strong["method_assurance_tier"] == 3
        assert strong["required_tier_at_creation"] == 3
        deliver_notice_to_consent(strong["id"])
        open_verification(strong["id"])
        granted = grant_consent(strong["id"], "GOVTID-U-1")

        assert granted["status"] == "GRANTED"
        after = read_service(service["id"])
        assert after["active_consent_count"] == 1
        assert after["granted_disclosure_consent_count"] == 1, (
            "only the granted disclosure-bearing request counts, got "
            f"{after['granted_disclosure_consent_count']}"
        )
        assert read_consent(weak["id"])["status"] == "PENDING_VERIFICATION", (
            "a refused grant leaves the row where it was"
        )


class TestSafeHarborExpiryThenLapse:
    """Both clock comparisons are strict, and only lapse touches the posture."""

    def test_07_a_certification_runs_out_at_its_expiry_and_lapses_after_the_grace(self):
        """Four clock positions walk the whole ladder.

        "Otherwise, if the current logical-clock instant is strictly before the governing
        assessment's `expires_at`, the status is `CERTIFIED`. Otherwise, if the current
        instant is strictly before that `expires_at` plus the program's
        `assessment_grace_days` days, the status is `ASSESSMENT_DUE`. Otherwise the status is
        `LAPSED`, which by clause 5 of §2.5 pulls the service's posture to `RESTRICTED`
        unless an earlier clause has already decided it. Both clock comparisons are strict".

        Design: Corner/calculations/safe_harbor_certification_expires_then_lapses_after_the_grace_period
        """
        service = create_service(name="Lapsing Harbor Service")
        certified = certified_service(service["id"])
        assessment_id = certified["assessment_id"]
        assert_instant(certified["assessment"]["certified_at"], STARTUP_CLOCK, "certified_at")
        assert_instant(
            certified["assessment"]["expires_at"], "2027-08-01T00:00:00Z", "expires_at"
        )

        before = read_service(service["id"])
        assert before["safe_harbor_status"] == "CERTIFIED"
        assert_instant(
            before["safe_harbor_expires_at"], "2027-08-01T00:00:00Z", "safe_harbor_expires_at"
        )
        assert before["compliance_posture"] == "OPEN"

        set_clock("2027-07-31T23:59:59.999Z")
        last_valid = read_service(service["id"])
        assert last_valid["safe_harbor_status"] == "CERTIFIED", (
            "one millisecond before expiry the certification still holds, got "
            f"{last_valid['safe_harbor_status']}"
        )
        assert last_valid["compliance_posture"] == "OPEN"

        set_clock("2027-08-01T00:00:00Z")
        at_expiry = read_service(service["id"])
        assert at_expiry["safe_harbor_status"] == "ASSESSMENT_DUE", (
            "at exactly expires_at the service is already due, got "
            f"{at_expiry['safe_harbor_status']}"
        )
        assert at_expiry["compliance_posture"] == "OPEN", (
            "being due does not restrict the posture, got "
            f"{at_expiry['compliance_posture']}"
        )

        set_clock("2027-08-30T23:59:59.999Z")
        last_grace = read_service(service["id"])
        assert last_grace["safe_harbor_status"] == "ASSESSMENT_DUE", (
            "the last instant inside the 30-day grace is still merely due, got "
            f"{last_grace['safe_harbor_status']}"
        )
        assert last_grace["compliance_posture"] == "OPEN"

        set_clock("2027-08-31T00:00:00Z")
        lapsed = read_service(service["id"])
        assert lapsed["safe_harbor_status"] == "LAPSED", (
            "at exactly expires_at plus the grace period the status lapses, got "
            f"{lapsed['safe_harbor_status']}"
        )
        assert lapsed["third_party_exposure_points"] == 0
        assert lapsed["open_audit_count"] == 0
        assert lapsed["compliance_posture"] == "RESTRICTED", (
            "with no exposure and no open audit only the lapse can restrict, got "
            f"{lapsed['compliance_posture']}"
        )
        assert read_assessment(assessment_id)["status"] == "CERTIFIED", (
            "lapse is a clock-derived read, not a state transition"
        )
