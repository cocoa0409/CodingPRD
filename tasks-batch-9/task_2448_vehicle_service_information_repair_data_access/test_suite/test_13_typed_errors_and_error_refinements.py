"""Typed errors and the refinements that keep two neighbouring failures apart.

Covers the ten per-entity not-found identifiers against an empty database, the
two distinguishable unusable-pin failures, the credential and attestation gates
re-evaluated at credential issuance, the completion refusal reserved for a job
awaiting revalidation, and the entitlement-status gate on a session request.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_1_USER_ID,
    CONTENT_PUBLISHER_1_USER_ID,
    DEFAULT_CREDENTIAL_EXPIRY,
    NOT_FOUND_PRECEDENCE,
    ApiErrorId,
    AuditSubjectEntity,
    DistributionStatus,
    EntitlementStatus,
    IdentityStatus,
    JobStatus,
    SeatStatus,
    SessionStatus,
    ToolStatus,
    assert_gateway_session,
    assert_programming_job,
    assert_publication,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_content_publisher_headers,
    make_platform_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# Ten well-formed identifiers that no row in an empty database can carry.
MISSING_IDS = [
    f"00000000-0000-4000-8000-0000000000{index:02d}" for index in range(10, 20)
]


def _tool_row(api, ctx, tool_id):
    rows, _meta = validate_paginated(
        api.list_shop_diagnostic_tools(
            ctx["shop"]["id"], ctx["manager_headers"], {"limit": 100}
        )
    )
    return next(row for row in rows if row["id"] == tool_id)


class TestEveryEntityTypeReportsItsOwnNotFound:
    """Ten lookups against an empty database answer with ten different ids."""

    def test_the_ten_typed_not_founds_are_pairwise_distinct(self, api):
        """No generic not-found: each entity type names itself in the error id.

        PRD 2.6: "Each entity type has its own not-found error, and the same error
        is used whether the missing identifier arrived in the path or in the
        request body: `ERR_MANUFACTURER_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`,
        `ERR_LICENSE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
        `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`,
        `ERR_PUBLICATION_NOT_FOUND`, `ERR_PUBLICATION_VERSION_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND` and `ERR_JOB_NOT_FOUND`, all HTTP 404." Those ten
        are also the sequence in which "Primary references are resolved in that
        order of entity precedence".

        Design: Corner/errors/not_found_ids_are_distinct_per_entity_type_not_found
        """
        admin = make_platform_admin_headers()
        officer = make_compliance_officer_headers(COMPLIANCE_OFFICER_1_USER_ID)
        publisher = make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)
        (
            manufacturer_id,
            shop_id,
            license_id,
            technician_id,
            entitlement_id,
            seat_id,
            publication_id,
            version_id,
            session_id,
            job_id,
        ) = MISSING_IDS

        observed = [
            validate_error(
                api.get_manufacturer(manufacturer_id, admin),
                ApiErrorId.MANUFACTURER_NOT_FOUND,
                404,
            )["error_id"],
            validate_error(
                api.get_shop(shop_id, admin), ApiErrorId.SHOP_NOT_FOUND, 404
            )["error_id"],
            validate_error(
                api.activate_license(license_id, admin),
                ApiErrorId.LICENSE_NOT_FOUND,
                404,
            )["error_id"],
            validate_error(
                api.suspend_technician(
                    technician_id, factories.reason_payload("REVIEW"), officer
                ),
                ApiErrorId.TECHNICIAN_NOT_FOUND,
                404,
            )["error_id"],
            validate_error(
                api.get_entitlement(entitlement_id, admin),
                ApiErrorId.ENTITLEMENT_NOT_FOUND,
                404,
            )["error_id"],
            validate_error(
                api.get_seat_assignment(seat_id, admin),
                ApiErrorId.SEAT_ASSIGNMENT_NOT_FOUND,
                404,
            )["error_id"],
            validate_error(
                api.get_publication(publication_id, admin),
                ApiErrorId.PUBLICATION_NOT_FOUND,
                404,
            )["error_id"],
            validate_error(
                api.publish_publication_version(version_id, publisher),
                ApiErrorId.PUBLICATION_VERSION_NOT_FOUND,
                404,
            )["error_id"],
            validate_error(
                api.get_gateway_session(session_id, admin),
                ApiErrorId.SESSION_NOT_FOUND,
                404,
            )["error_id"],
            validate_error(
                api.get_programming_job(job_id, admin), ApiErrorId.JOB_NOT_FOUND, 404
            )["error_id"],
        ]

        assert observed == NOT_FOUND_PRECEDENCE
        assert len(set(observed)) == 10


class TestPinningAVersionThatWasNeverAvailable:
    """WITHHELD is refused as never-published, not as stale."""

    def test_the_withheld_sibling_is_refused_while_the_published_one_queues(self, api):
        """Version 2 never left WITHHELD, so only version 1 can carry a job.

        PRD 3.8: "At queue time the pinned version must be usable: a version still
        in `WITHHELD` was never available and is refused with
        `ERR_VERSION_NOT_PUBLISHED` (HTTP 409)", and "A successful queue opens the
        job in `QUEUED` with `repin_count` at 0 and `abort_reason` null, and
        increments the pinned version's `active_pin_count` by 1." PRD 3.6 keeps the
        two publication pointers apart: "`current_version_no` tracks the highest
        version number ever minted beneath it, and `published_version_id` names the
        single child version whose availability axis currently reads `PUBLISHED`,
        or null when none does."

        Design: Corner/errors/error_version_not_published_when_pinning_withheld_version
        """
        ctx = fixtures.build_active_session(api, covered_area_codes=("POWERTRAIN",))
        published_id = ctx["versions"]["main"]["id"]
        withheld = fixtures.mint_version(
            api, ctx, key="v2", source_tsb_ref="TSB-0002"
        )
        assert withheld["distribution_status"] == DistributionStatus.WITHHELD
        session_id = ctx["sessions"]["main"]["id"]
        technician_headers = ctx["tech_headers"]["main"]

        validate_error(
            api.create_programming_job(
                factories.programming_job_payload(session_id, withheld["id"]),
                technician_headers,
            ),
            ApiErrorId.VERSION_NOT_PUBLISHED,
            409,
        )

        queued = validate_success(
            api.create_programming_job(
                factories.programming_job_payload(session_id, published_id),
                technician_headers,
            ),
            201,
        )
        assert_programming_job(queued)
        assert queued["status"] == JobStatus.QUEUED
        assert queued["pinned_publication_version_id"] == published_id
        assert queued["repin_count"] == 0
        assert queued["abort_reason"] is None

        pinned = fixtures.refresh_version(api, ctx, key="main")
        assert pinned["distribution_status"] == DistributionStatus.PUBLISHED
        assert pinned["active_pin_count"] == 1
        unpinned = fixtures.refresh_version(api, ctx, key="v2")
        assert unpinned["distribution_status"] == DistributionStatus.WITHHELD
        assert unpinned["active_pin_count"] == 0

        publication = validate_success(
            api.get_publication(
                ctx["publications"]["main"]["id"], make_platform_admin_headers()
            )
        )
        assert_publication(publication)
        assert publication["current_version_no"] == 2
        assert publication["published_version_id"] == published_id


class TestPinningAVersionThatHasBeenOvertaken:
    """SUPERSEDED is refused as stale, and the newer sibling takes the job."""

    def test_the_superseded_version_is_refused_while_the_current_one_queues(self, api):
        """Version 1 was published once, so its refusal names staleness.

        PRD 3.8: "a version in `SUPERSEDED` or `RECALLED` is refused with
        `ERR_STALE_PUBLICATION_VERSION` (HTTP 409) — the two failures are kept
        distinguishable on purpose." PRD 3.6 explains how version 1 got there:
        publication "takes the previously published sibling version of the same
        publication, if there was one, through `PUBLISHED → SUPERSEDED`", and
        repoints "the parent publication's `published_version_id`" at the newly
        published row.

        Design: Corner/errors/error_stale_publication_version_when_pinning_superseded_version
        """
        ctx = fixtures.build_active_session(api, covered_area_codes=("POWERTRAIN",))
        stale_id = ctx["versions"]["main"]["id"]
        fixtures.mint_version(api, ctx, key="v2", source_tsb_ref="TSB-0002")
        current = fixtures.publish_version(api, ctx, key="v2")
        assert current["distribution_status"] == DistributionStatus.PUBLISHED
        session_id = ctx["sessions"]["main"]["id"]
        technician_headers = ctx["tech_headers"]["main"]

        validate_error(
            api.create_programming_job(
                factories.programming_job_payload(session_id, stale_id),
                technician_headers,
            ),
            ApiErrorId.STALE_PUBLICATION_VERSION,
            409,
        )

        queued = validate_success(
            api.create_programming_job(
                factories.programming_job_payload(session_id, current["id"]),
                technician_headers,
            ),
            201,
        )
        assert_programming_job(queued)
        assert queued["status"] == JobStatus.QUEUED
        assert queued["pinned_publication_version_id"] == current["id"]

        superseded = fixtures.refresh_version(api, ctx, key="main")
        assert superseded["distribution_status"] == DistributionStatus.SUPERSEDED
        assert superseded["active_pin_count"] == 0
        newest = fixtures.refresh_version(api, ctx, key="v2")
        assert newest["distribution_status"] == DistributionStatus.PUBLISHED
        assert newest["active_pin_count"] == 1

        publication = validate_success(
            api.get_publication(
                ctx["publications"]["main"]["id"], make_platform_admin_headers()
            )
        )
        assert publication["published_version_id"] == current["id"]


class TestTheCredentialIsRecheckedAtIssuance:
    """A session requested under a valid credential still cannot be activated later."""

    def test_activation_after_the_credential_lapses_mints_nothing(self, api):
        """The clock has passed credential_expires_at, so no token and no occupancy.

        PRD 3.7: activation checks "that technician's `credential_expires_at` must
        lie strictly after the current logical clock, failing which
        `ERR_SECURITY_CREDENTIAL_EXPIRED`". The refused call leaves the request
        exactly as it opened it — "A successful request opens the session in
        `REQUESTED` with `credential_token` null" — and none of the activation side
        effects run, so the tool never becomes "`OCCUPIED` with
        `occupied_by_session_id` set to this session" and no
        `SESSION_CREDENTIAL_ISSUED` audit row is appended.

        Design: Corner/errors/error_security_credential_expired_at_session_activate
        """
        ctx = fixtures.build_seated_technician(
            api,
            covered_area_codes=("POWERTRAIN",),
            credential_expires_at="2026-08-02T00:00:00Z",
        )
        fixtures.add_session(api, ctx, key="main", activate=False)
        session_id = ctx["sessions"]["main"]["id"]
        technician_headers = ctx["tech_headers"]["main"]
        fixtures.set_clock(api, ctx, "2026-08-03T09:00:00Z")

        validate_error(
            api.activate_gateway_session(session_id, technician_headers),
            ApiErrorId.SECURITY_CREDENTIAL_EXPIRED,
            409,
        )

        session = fixtures.refresh_session(api, ctx)
        assert_gateway_session(session)
        assert session["status"] == SessionStatus.REQUESTED
        assert session["credential_token"] is None

        tool = _tool_row(api, ctx, ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.IDLE
        assert tool["occupied_by_session_id"] is None

        events, meta = validate_paginated(
            api.list_audit_events(
                make_compliance_officer_headers(),
                {
                    "subject_entity": AuditSubjectEntity.GATEWAY_SESSION,
                    "subject_id": session_id,
                },
            )
        )
        assert meta["total_count"] == 0
        assert events == []


class TestTheToolAttestationIsRecheckedAtIssuance:
    """A valid credential is not enough when the scanner's attestation has lapsed."""

    def test_activation_at_the_attestation_instant_is_refused(self, api):
        """The technician stays VERIFIED; it is the tool that bars the session.

        PRD 3.7: activation requires that "the tool's
        `oem_attestation_expires_at` must lie strictly after the current logical
        clock, so a session cannot be activated at or after the attestation
        instant, failing which `ERR_TOOL_ATTESTATION_EXPIRED`". The credential gate
        ahead of it passed, and a tool "starts `IDLE`, and `occupied_by_session_id`
        names the session currently holding it or is null while the tool is idle".

        Design: Corner/errors/error_tool_attestation_expired_at_session_activate
        """
        ctx = fixtures.build_seated_technician(
            api,
            covered_area_codes=("POWERTRAIN",),
            tool_serial_no="SN-STALE",
            oem_attestation_expires_at="2026-08-02T00:00:00Z",
        )
        fixtures.add_session(api, ctx, key="main", activate=False)
        session_id = ctx["sessions"]["main"]["id"]
        technician_headers = ctx["tech_headers"]["main"]
        fixtures.set_clock(api, ctx, "2026-08-03T09:00:00Z")

        validate_error(
            api.activate_gateway_session(session_id, technician_headers),
            ApiErrorId.TOOL_ATTESTATION_EXPIRED,
            409,
        )

        roster, _roster_meta = validate_paginated(
            api.list_shop_technicians(
                ctx["shop"]["id"], ctx["manager_headers"], {"limit": 100}
            )
        )
        technician = next(
            row for row in roster if row["id"] == ctx["technicians"]["main"]["id"]
        )
        assert technician["identity_status"] == IdentityStatus.VERIFIED
        assert technician["credential_expires_at"].startswith(
            DEFAULT_CREDENTIAL_EXPIRY[:19]
        )

        session = fixtures.refresh_session(api, ctx)
        assert session["status"] == SessionStatus.REQUESTED
        assert session["credential_token"] is None

        tool = _tool_row(api, ctx, ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.IDLE


class TestCompletionIsBarredWithItsOwnError:
    """A job awaiting revalidation gets the refined error, not the generic one."""

    def test_completing_a_job_whose_pin_was_superseded_names_revalidation(self, api):
        """The refusal reads ERR_JOB_REVALIDATION_REQUIRED and the session lives on.

        PRD 3.8: "asking a job that sits in `REVALIDATION_REQUIRED` to complete is
        refused with `ERR_JOB_REVALIDATION_REQUIRED` (HTTP 409), a refinement that
        exists so the technician learns *why* completion is barred instead of
        receiving a generic state error. Asking any other non-`IN_PROGRESS` job to
        complete yields plain `ERR_INVALID_STATE`." The job reached that state
        through PRD 3.6 hop 2, which "reaches into every programming job pinned to
        that superseded version: jobs in `IN_PROGRESS` go
        `IN_PROGRESS → REVALIDATION_REQUIRED`".

        Design: Corner/errors/error_job_revalidation_required_when_completing_unpinned_job
        """
        ctx = fixtures.build_session_with_started_job(
            api, covered_area_codes=("POWERTRAIN",)
        )
        pinned_id = ctx["versions"]["main"]["id"]
        fixtures.mint_version(api, ctx, key="v2", source_tsb_ref="TSB-0002")
        fixtures.publish_version(api, ctx, key="v2")
        technician_headers = ctx["tech_headers"]["main"]

        validate_error(
            api.complete_programming_job(
                ctx["jobs"]["main"]["id"], technician_headers
            ),
            ApiErrorId.JOB_REVALIDATION_REQUIRED,
            409,
        )

        job = fixtures.refresh_job(api, ctx)
        assert_programming_job(job)
        assert job["status"] == JobStatus.REVALIDATION_REQUIRED
        assert job["pinned_publication_version_id"] == pinned_id
        assert job["repin_count"] == 0

        superseded = fixtures.refresh_version(api, ctx, key="main")
        assert superseded["distribution_status"] == DistributionStatus.SUPERSEDED

        session = fixtures.refresh_session(api, ctx)
        assert session["status"] == SessionStatus.ACTIVE


class TestTheSessionRequestReadsTheEntitlementStatus:
    """The seat is fine; it is the entitlement behind it that is not yet ACTIVE."""

    def test_a_pending_entitlement_refuses_the_request_that_activation_then_allows(
        self, api
    ):
        """The identical request fails on PENDING and succeeds once ACTIVE.

        PRD 3.7: "The entitlement behind the named seat must be `ACTIVE`, or the
        request is refused with `ERR_ENTITLEMENT_NOT_ACTIVE` (HTTP 409)", and on
        the accepted call the session opens "in `REQUESTED` with `credential_token`
        null, `termination_reason` null, and all four money fields —
        `base_subtotal_cents`, `discount_cents`, `surcharge_cents` and
        `total_access_fee_cents` — at 0". PRD 3.5 keeps the junction itself
        untouched: "a new seat opens in `ACTIVE` with a null `revocation_reason`".

        Design: Corner/errors/error_entitlement_not_active_when_requesting_session_on_pending_entitlement
        """
        ctx = fixtures.build_seated_technician(
            api, covered_area_codes=("POWERTRAIN",), activate_entitlement=False
        )
        seat_id = ctx["seats"]["main"]["id"]
        tool_id = ctx["tools"]["main"]["id"]
        technician_headers = ctx["tech_headers"]["main"]
        request_payload = factories.gateway_session_payload(seat_id, tool_id)

        validate_error(
            api.create_gateway_session(request_payload, technician_headers),
            ApiErrorId.ENTITLEMENT_NOT_ACTIVE,
            409,
        )

        seat = validate_success(
            api.get_seat_assignment(seat_id, ctx["manager_headers"])
        )
        assert seat["status"] == SeatStatus.ACTIVE
        assert seat["revocation_reason"] is None

        activated = validate_success(
            api.activate_entitlement(
                ctx["entitlement"]["id"], ctx["manager_headers"]
            )
        )
        assert activated["status"] == EntitlementStatus.ACTIVE

        session = validate_success(
            api.create_gateway_session(request_payload, technician_headers), 201
        )
        assert_gateway_session(session)
        assert session["status"] == SessionStatus.REQUESTED
        assert session["credential_token"] is None
        assert session["termination_reason"] is None
        assert session["base_subtotal_cents"] == 0
        assert session["discount_cents"] == 0
        assert session["surcharge_cents"] == 0
        assert session["total_access_fee_cents"] == 0

        rows, meta = validate_paginated(
            api.list_gateway_sessions(
                technician_headers, {"seat_assignment_id": seat_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == session["id"]
        assert rows[0]["status"] == SessionStatus.REQUESTED
