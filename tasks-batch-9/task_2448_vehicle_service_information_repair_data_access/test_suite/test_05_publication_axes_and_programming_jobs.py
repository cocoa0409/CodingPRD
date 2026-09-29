"""The two independent publication axes and the job lifecycle that depends on them.

Covers editorial review versus distribution availability, the revalidation loop a
live job runs when its pinned version leaves `PUBLISHED`, and the calibration
document a calibration job needs before it may start.
"""

from test_helpers import (
    CONTENT_PUBLISHER_1_USER_ID,
    CONTENT_PUBLISHER_2_USER_ID,
    ApiErrorId,
    DistributionStatus,
    JobStatus,
    JobType,
    PublicationType,
    ReviewStatus,
    assert_programming_job,
    assert_publication,
    assert_publication_version,
    factories,
    fixtures,
    make_content_publisher_headers,
    make_platform_admin_headers,
    validate_error,
    validate_success,
)


class TestPublicationAxesMoveIndependently:
    """Review status and distribution status never constrain one another."""

    def test_publishing_a_draft_version_moves_only_the_availability_axis(self, api):
        """A DRAFT version can be published, and stays DRAFT afterwards.

        PRD 3.6: "The editorial axis is `review_status`, whose only values are
        `DRAFT` and `VALIDATED`." Publication does not touch it — "On success
        `distribution_status` becomes `PUBLISHED`, `published_by_user_id` records
        the acting publisher, the parent publication's `published_version_id` is
        repointed at this version".

        Design: Difficulty/non_linear_state_machine/publication_version_parallel_axes_move_independently
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        fixtures.add_publication_version(api, ctx, validate=False, publish=False)
        version = ctx["versions"]["main"]
        assert version["review_status"] == ReviewStatus.DRAFT
        assert version["distribution_status"] == DistributionStatus.WITHHELD

        published = validate_success(
            api.publish_publication_version(
                version["id"], make_content_publisher_headers(CONTENT_PUBLISHER_2_USER_ID)
            )
        )

        assert_publication_version(published)
        assert published["distribution_status"] == DistributionStatus.PUBLISHED
        assert published["review_status"] == ReviewStatus.DRAFT
        assert published["published_by_user_id"] == CONTENT_PUBLISHER_2_USER_ID
        assert published["validated_by_user_id"] is None
        assert published["version_no"] == 1

        publication = validate_success(
            api.get_publication(
                published["publication_id"], make_platform_admin_headers()
            )
        )
        assert_publication(publication)
        assert publication["published_version_id"] == published["id"]

    def test_validating_an_already_published_version_moves_only_the_editorial_axis(
        self, api
    ):
        """Post-hoc review advances the review axis and leaves distribution alone.

        PRD 3.6: "On success `review_status` becomes `VALIDATED`,
        `validated_by_user_id` records the acting publisher's `X-User-ID`, the
        version's `version` advances by 1", while the availability axis keeps the
        `PUBLISHED` value it already reached.

        Design: Difficulty/non_linear_state_machine/publication_version_parallel_axes_move_independently
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        fixtures.add_publication_version(api, ctx, validate=False, publish=False)
        version_id = ctx["versions"]["main"]["id"]
        validate_success(
            api.publish_publication_version(
                version_id, make_content_publisher_headers(CONTENT_PUBLISHER_2_USER_ID)
            )
        )

        validated = validate_success(
            api.validate_publication_version(
                version_id,
                factories.validate_version_payload(
                    reviewer_notes="post-hoc editorial review"
                ),
                make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID),
            )
        )

        assert_publication_version(validated)
        assert validated["review_status"] == ReviewStatus.VALIDATED
        assert validated["distribution_status"] == DistributionStatus.PUBLISHED
        assert validated["validated_by_user_id"] == CONTENT_PUBLISHER_1_USER_ID
        assert validated["published_by_user_id"] == CONTENT_PUBLISHER_2_USER_ID
        assert validated["version_no"] == 1


class TestJobRevalidationCycle:
    """A recall pushes a live job out of IN_PROGRESS, and a repin brings it back."""

    def test_a_recall_forces_revalidation_and_drops_the_pin(self, api):
        """The pinned version leaving PUBLISHED takes the job with it.

        PRD 3.8: `REVALIDATION_REQUIRED` "is the cascade described in §3.6, fired
        when the version a live job is pinned to leaves `PUBLISHED`, whether by
        being superseded by a newer sibling or by being recalled outright". "On
        entering `REVALIDATION_REQUIRED` the job's pinned version has its
        `active_pin_count` decremented by 1 and a `JOB_REVALIDATION_REQUIRED`
        audit row is appended."

        Design: Difficulty/non_linear_state_machine/programming_job_revalidation_cycle_returns_to_in_progress_on_repin
        """
        ctx = fixtures.build_revalidation_required_job(
            api,
            job_type=JobType.MODULE_FLASH,
            recall_reason="incorrect torque sequence",
            covered_area_codes=("POWERTRAIN",),
            validate=False,
        )

        recalled = ctx["versions"]["main"]
        assert recalled["distribution_status"] == DistributionStatus.RECALLED
        assert recalled["active_pin_count"] == 0

        job = fixtures.refresh_job(api, ctx)
        assert_programming_job(job)
        assert job["status"] == JobStatus.REVALIDATION_REQUIRED

    def test_repinning_to_the_successor_returns_the_job_to_in_progress(self, api):
        """Repinning counts the loop and moves the pin onto the new version.

        PRD 3.8: "On success the job's `pinned_publication_version_id` is
        replaced, `repin_count` is increased by 1, `status` returns to
        `IN_PROGRESS`, the newly pinned version's `active_pin_count` is increased
        by 1, and the job's `version` advances by 1."

        Design: Difficulty/non_linear_state_machine/programming_job_revalidation_cycle_returns_to_in_progress_on_repin
        """
        ctx = fixtures.build_revalidation_required_job(
            api,
            job_type=JobType.MODULE_FLASH,
            recall_reason="incorrect torque sequence",
            covered_area_codes=("POWERTRAIN",),
            validate=False,
        )
        fixtures.mint_version(
            api, ctx, publication_key="main", key="v2", source_tsb_ref="TSB-0002"
        )
        fixtures.publish_version(
            api, ctx, key="v2", publisher_user_id=CONTENT_PUBLISHER_2_USER_ID
        )
        successor = ctx["versions"]["v2"]

        repinned = validate_success(
            api.repin_programming_job(
                ctx["jobs"]["main"]["id"],
                factories.repin_payload(successor["id"]),
                ctx["tech_headers"]["main"],
            )
        )

        assert_programming_job(repinned)
        assert repinned["status"] == JobStatus.IN_PROGRESS
        assert repinned["pinned_publication_version_id"] == successor["id"]
        assert repinned["repin_count"] == 1

        refreshed = fixtures.refresh_version(api, ctx, key="v2")
        assert refreshed["version_no"] == 2
        assert refreshed["active_pin_count"] == 1


class TestCalibrationDocumentGate:
    """An ADAS calibration job may not start without a live calibration document."""

    def test_a_calibration_job_cannot_start_while_the_document_is_withheld(self, api):
        """A validated-but-withheld calibration document does not satisfy the gate.

        PRD 3.8: "when the `job_type` is `ADAS_CALIBRATION`, there must exist, for
        the same model-and-system cell as the pinned version's own publication, a
        publication of type `CALIBRATION_DOC` carrying a version that is
        simultaneously `VALIDATED` on its editorial axis and `PUBLISHED` on its
        availability axis. If no such calibration document exists, the start is
        refused with `ERR_CALIBRATION_DOC_REQUIRED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/adas_job_start_depends_on_calibration_doc_version_state
        """
        ctx = fixtures.build_active_session(
            api,
            area_codes=("ADAS",),
            covered_area_codes=("ADAS",),
            system_area_code="ADAS",
        )
        fixtures.add_publication_version(
            api,
            ctx,
            key="cal",
            publication_key="cal",
            system_area_code="ADAS",
            publication_type=PublicationType.CALIBRATION_DOC,
            source_tsb_ref="TSB-CAL-0001",
            calibration_procedure_ref="CAL-AX7-ADAS-01",
            validate=True,
            publish=False,
        )
        assert ctx["versions"]["cal"]["review_status"] == ReviewStatus.VALIDATED
        assert (
            ctx["versions"]["cal"]["distribution_status"] == DistributionStatus.WITHHELD
        )

        job = validate_success(
            api.create_programming_job(
                factories.programming_job_payload(
                    ctx["sessions"]["main"]["id"],
                    ctx["versions"]["main"]["id"],
                    job_type=JobType.ADAS_CALIBRATION,
                ),
                ctx["tech_headers"]["main"],
            ),
            201,
        )
        assert job["status"] == JobStatus.QUEUED

        validate_error(
            api.start_programming_job(job["id"], ctx["tech_headers"]["main"]),
            ApiErrorId.CALIBRATION_DOC_REQUIRED,
            422,
        )

        still_queued = validate_success(
            api.get_programming_job(job["id"], ctx["tech_headers"]["main"])
        )
        assert still_queued["status"] == JobStatus.QUEUED

    def test_publishing_the_calibration_document_unblocks_the_identical_start(
        self, api
    ):
        """Once the document is validated and published the same start succeeds.

        PRD 3.8: the gate needs a `CALIBRATION_DOC` version "that is
        simultaneously `VALIDATED` on its editorial axis and `PUBLISHED` on its
        availability axis", and "A successful start sets `status` to
        `IN_PROGRESS`, appends a `JOB_STARTED` audit row whose `detail` is the
        literal text `job_type=` followed by the job's `job_type`".

        Design: Difficulty/cross_entity_state_dependency/adas_job_start_depends_on_calibration_doc_version_state
        """
        ctx = fixtures.build_active_session(
            api,
            area_codes=("ADAS",),
            covered_area_codes=("ADAS",),
            system_area_code="ADAS",
        )
        fixtures.add_publication_version(
            api,
            ctx,
            key="cal",
            publication_key="cal",
            system_area_code="ADAS",
            publication_type=PublicationType.CALIBRATION_DOC,
            source_tsb_ref="TSB-CAL-0001",
            calibration_procedure_ref="CAL-AX7-ADAS-01",
            validate=True,
            publish=False,
        )
        job = validate_success(
            api.create_programming_job(
                factories.programming_job_payload(
                    ctx["sessions"]["main"]["id"],
                    ctx["versions"]["main"]["id"],
                    job_type=JobType.ADAS_CALIBRATION,
                ),
                ctx["tech_headers"]["main"],
            ),
            201,
        )
        validate_error(
            api.start_programming_job(job["id"], ctx["tech_headers"]["main"]),
            ApiErrorId.CALIBRATION_DOC_REQUIRED,
            422,
        )

        calibration = fixtures.publish_version(
            api, ctx, key="cal", publisher_user_id=CONTENT_PUBLISHER_2_USER_ID
        )
        assert calibration["review_status"] == ReviewStatus.VALIDATED
        assert calibration["distribution_status"] == DistributionStatus.PUBLISHED

        started = validate_success(
            api.start_programming_job(job["id"], ctx["tech_headers"]["main"])
        )
        assert_programming_job(started)
        assert started["status"] == JobStatus.IN_PROGRESS

        pinned = fixtures.refresh_version(api, ctx, key="main")
        assert pinned["active_pin_count"] == 1
