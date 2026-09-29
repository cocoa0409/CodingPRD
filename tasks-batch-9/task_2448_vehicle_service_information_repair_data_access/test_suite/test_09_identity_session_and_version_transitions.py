"""Identity transitions, gateway activation side effects and version axis moves.

Covers the source-state guard on revocation, what re-verification does and does
not restore, the three side effects of activating a session, the absence of a
validate self-loop, and what publishing a newer sibling rewrites.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_1_USER_ID,
    CONTENT_PUBLISHER_1_USER_ID,
    CONTENT_PUBLISHER_2_USER_ID,
    VIN_PRIMARY,
    ApiErrorId,
    AuditEventType,
    AuditSubjectEntity,
    DistributionStatus,
    IdentityStatus,
    ReviewStatus,
    Role,
    SeatRevocationReason,
    SeatStatus,
    SessionStatus,
    SessionTerminationReason,
    ToolStatus,
    assert_credential_token_derived_from_session,
    assert_gateway_fee_breakdown,
    assert_gateway_session,
    assert_publication,
    assert_publication_version,
    assert_seat_counts,
    assert_single_audit_event,
    assert_technician,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_content_publisher_headers,
    make_platform_admin_headers,
    make_shop_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRevocationRequiresSuspensionFirst:
    """REVOKED is reachable from SUSPENDED alone."""

    def test_revoking_an_unverified_technician_is_refused_until_suspension(self, api):
        """The same call fails from UNVERIFIED and succeeds from SUSPENDED.

        PRD 3.5: "Revocation is the terminal step and it is reachable only from
        `SUSPENDED → REVOKED`; revoking a technician who is `UNVERIFIED` or
        `VERIFIED` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/technician_revoke_from_unverified_returns_4XX_invalid_state
        """
        admin = make_platform_admin_headers()
        shop = validate_success(api.create_shop(factories.shop_payload(), admin), 201)
        manager = make_shop_manager_headers(shop["id"])
        technician = validate_success(
            api.create_technician(factories.technician_payload(shop["id"]), manager),
            201,
        )
        officer = make_compliance_officer_headers(COMPLIANCE_OFFICER_1_USER_ID)

        validate_error(
            api.revoke_technician(
                technician["id"], factories.reason_payload("FRAUD"), officer
            ),
            ApiErrorId.INVALID_STATE,
            409,
        )
        roster, _meta = validate_paginated(
            api.list_shop_technicians(shop["id"], manager, {"limit": 100})
        )
        untouched = next(row for row in roster if row["id"] == technician["id"])
        assert untouched["identity_status"] == IdentityStatus.UNVERIFIED

        suspended = validate_success(
            api.suspend_technician(
                technician["id"], factories.reason_payload("DOC_MISMATCH"), officer
            )
        )
        assert suspended["identity_status"] == IdentityStatus.SUSPENDED

        revoked = validate_success(
            api.revoke_technician(
                technician["id"], factories.reason_payload("FRAUD"), officer
            )
        )
        assert_technician(revoked)
        assert revoked["identity_status"] == IdentityStatus.REVOKED


class TestReverificationRestoresOnlyTheIdentity:
    """Coming back to VERIFIED undoes none of the suspension cascade."""

    def test_reverifying_leaves_the_seat_revoked_and_the_session_terminated(self, api):
        """Identity returns to VERIFIED while every cascaded row stays where it fell.

        PRD 3.5: verification is reachable "as a re-verification, from
        `SUSPENDED → VERIFIED`", and "Re-verification restores nothing but the
        identity itself: seats that a prior suspension revoked stay `REVOKED`, and
        sessions that suspension terminated stay `TERMINATED`." The job-free session
        prices at 2,500 plus 300 with no discount and a four percent surcharge, and
        PRD 3.3 keeps that accrual out of the credit balance.

        Design: Corner/state_machines/technician_reverify_after_suspension_does_not_restore_seats
        """
        ctx = fixtures.build_active_session(api, covered_area_codes=("POWERTRAIN",))
        technician_id = ctx["technicians"]["main"]["id"]
        officer = make_compliance_officer_headers(COMPLIANCE_OFFICER_1_USER_ID)

        suspended = validate_success(
            api.suspend_technician(
                technician_id, factories.reason_payload("DOC_EXPIRED"), officer
            )
        )
        assert suspended["identity_status"] == IdentityStatus.SUSPENDED

        reverified = validate_success(
            api.verify_technician(
                technician_id,
                factories.verify_technician_payload(identity_document_ref="DL-88999"),
                officer,
            )
        )
        assert_technician(reverified)
        assert reverified["identity_status"] == IdentityStatus.VERIFIED
        assert reverified["identity_document_ref"] == "DL-88999"

        seat = validate_success(
            api.get_seat_assignment(ctx["seats"]["main"]["id"], ctx["manager_headers"])
        )
        assert seat["status"] == SeatStatus.REVOKED
        assert seat["revocation_reason"] == SeatRevocationReason.TECHNICIAN_SUSPENDED

        session = validate_success(
            api.get_gateway_session(
                ctx["sessions"]["main"]["id"], ctx["manager_headers"]
            )
        )
        assert session["status"] == SessionStatus.TERMINATED
        assert (
            session["termination_reason"]
            == SessionTerminationReason.TECHNICIAN_SUSPENDED
        )
        assert_gateway_fee_breakdown(session, 2800, 0, 112, 2912)

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert_seat_counts(entitlement, 0, 3)

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["gateway_fee_accrued_cents"] == 2912
        assert shop["data_credit_balance_cents"] == 115000

        tools, _meta = validate_paginated(
            api.list_shop_diagnostic_tools(
                ctx["shop"]["id"], ctx["manager_headers"], {"limit": 100}
            )
        )
        tool = next(row for row in tools if row["id"] == ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.IDLE
        assert tool["occupied_by_session_id"] is None


class TestSessionActivationSideEffects:
    """One activation call mints the token, seizes the tool and writes the trail."""

    def test_activation_mints_the_token_seizes_the_tool_and_audits_the_vin(self, api):
        """All three declared side effects land, with the fee fields still at zero.

        PRD 3.7: "its `credential_token` is minted as the literal prefix `GW-`
        followed by the first eight hexadecimal characters of the session's own
        `id`, upper-cased. The occupied tool moves to `OCCUPIED` with
        `occupied_by_session_id` set to this session and its own `version` advanced
        by 1, a `SESSION_CREDENTIAL_ISSUED` audit row is appended whose `detail` is
        the literal text `vin=` followed by the session's `vin`". The four money
        fields were opened at 0 by the request and are only stamped when the session
        closes.

        Design: Corner/state_machines/session_activate_side_effects_credential_token_and_tool_occupancy
        """
        ctx = fixtures.build_seated_technician(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_session(
            api, ctx, key="main", technician_key="main", tool_key="main", activate=False
        )
        session_id = ctx["sessions"]["main"]["id"]

        activated = validate_success(
            api.activate_gateway_session(session_id, ctx["tech_headers"]["main"])
        )

        assert_gateway_session(activated)
        assert activated["status"] == SessionStatus.ACTIVE
        assert_credential_token_derived_from_session(activated)
        assert_gateway_fee_breakdown(activated, 0, 0, 0, 0)

        tools, meta = validate_paginated(
            api.list_shop_diagnostic_tools(
                ctx["shop"]["id"],
                ctx["manager_headers"],
                {"status": ToolStatus.OCCUPIED},
            )
        )
        assert meta["total_count"] == 1
        assert tools[0]["id"] == ctx["tools"]["main"]["id"]
        assert tools[0]["status"] == ToolStatus.OCCUPIED
        assert tools[0]["occupied_by_session_id"] == session_id

        events, _event_meta = validate_paginated(
            api.list_audit_events(
                make_compliance_officer_headers(),
                {
                    "subject_entity": AuditSubjectEntity.GATEWAY_SESSION,
                    "subject_id": session_id,
                    "limit": 100,
                },
            )
        )
        event = assert_single_audit_event(
            events,
            AuditEventType.SESSION_CREDENTIAL_ISSUED,
            subject_id=session_id,
            detail=f"vin={VIN_PRIMARY}",
        )
        assert event["actor_role"] == Role.TECHNICIAN
        assert event["actor_user_id"] == ctx["technicians"]["main"]["id"]


class TestValidationHasNoSelfLoop:
    """A second validate on the same version is refused, not re-stamped."""

    def test_validating_twice_keeps_the_first_reviewer(self, api):
        """The second call is ERR_INVALID_STATE and the reviewer id does not move.

        PRD 3.6: "Two preconditions apply: the version's `review_status` must
        currently be `DRAFT`, and its `distribution_status` must not be `RECALLED`
        — recalled material is not re-reviewed, and attempting it is rejected with
        `ERR_INVALID_STATE`", and on the first success "`validated_by_user_id`
        records the acting publisher's `X-User-ID`, the version's `version` advances
        by 1".

        Design: Corner/state_machines/publication_version_validate_twice_second_call_rejected
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        fixtures.add_publication_version(api, ctx, validate=False, publish=False)
        version_id = ctx["versions"]["main"]["id"]

        first = validate_success(
            api.validate_publication_version(
                version_id,
                factories.validate_version_payload(reviewer_notes="first pass"),
                make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID),
            )
        )
        assert_publication_version(first)
        assert first["review_status"] == ReviewStatus.VALIDATED
        assert first["validated_by_user_id"] == CONTENT_PUBLISHER_1_USER_ID
        assert first["distribution_status"] == DistributionStatus.WITHHELD

        validate_error(
            api.validate_publication_version(
                version_id,
                factories.validate_version_payload(reviewer_notes="second pass"),
                make_content_publisher_headers(CONTENT_PUBLISHER_2_USER_ID),
            ),
            ApiErrorId.INVALID_STATE,
            409,
        )

        stored = fixtures.refresh_version(api, ctx)
        assert stored["validated_by_user_id"] == CONTENT_PUBLISHER_1_USER_ID
        assert stored["version"] == 2


class TestPublishingASiblingSupersedesTheIncumbent:
    """Publishing version 2 rewrites version 1 and the parent publication."""

    def test_the_prior_published_version_is_superseded_and_keeps_its_review(self, api):
        """v1 goes SUPERSEDED but stays VALIDATED, and the parent repoints to v2.

        PRD 3.6: hop 1 "takes the previously published sibling version of the same
        publication, if there was one, through `PUBLISHED → SUPERSEDED`; the
        superseded row's `review_status` is left exactly as it was, since
        supersession says nothing about editorial quality", while publication itself
        repoints "the parent publication's `published_version_id`" at the new
        version. Version lists "are ordered by ascending `version_no`".

        Design: Corner/state_machines/publish_newer_sibling_supersedes_prior_published_version
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        fixtures.add_publication_version(api, ctx, validate=True, publish=True)
        first_version_id = ctx["versions"]["main"]["id"]
        fixtures.mint_version(api, ctx, key="v2", source_tsb_ref="TSB-0002")
        fixtures.validate_version(api, ctx, key="v2")

        published = validate_success(
            api.publish_publication_version(
                ctx["versions"]["v2"]["id"],
                make_content_publisher_headers(CONTENT_PUBLISHER_2_USER_ID),
            )
        )
        assert published["distribution_status"] == DistributionStatus.PUBLISHED
        assert published["published_by_user_id"] == CONTENT_PUBLISHER_2_USER_ID

        publication_id = ctx["publications"]["main"]["id"]
        author = make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)
        rows, meta = validate_paginated(
            api.list_publication_versions(publication_id, author, {"limit": 100})
        )
        assert meta["total_count"] == 2
        assert [row["version_no"] for row in rows] == [1, 2]
        assert rows[0]["id"] == first_version_id
        assert rows[0]["distribution_status"] == DistributionStatus.SUPERSEDED
        assert rows[0]["review_status"] == ReviewStatus.VALIDATED
        assert rows[1]["distribution_status"] == DistributionStatus.PUBLISHED

        publication = validate_success(
            api.get_publication(publication_id, make_platform_admin_headers())
        )
        assert_publication(publication)
        assert publication["published_version_id"] == published["id"]
        assert publication["current_version_no"] == 2
