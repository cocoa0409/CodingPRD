"""Operations whose legality is decided by the state of a different entity."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_EPOCH,
    FIRST_VISIT_START,
    ApiErrorId,
    api_client,
    advance_clock,
    assert_instant,
    audit_visit_payload,
    dispute_payload,
    make_auditor_headers,
    setup_brand_program,
    setup_filed_dispute,
    setup_scheduled_visit,
    setup_submitted_visit,
    validate_error,
    validate_paginated,
    validate_success,
    void_payload,
)


class TestVisitStartDependsOnAuditorStanding:
    def test_a_suspended_auditor_cannot_start_their_scheduled_visit(self):
        """The scheduled visit stays put and is blocked at the start instead.

        PRD: "the auditor's `SCHEDULED` visits, by contrast, are left exactly where they are
        and are instead blocked at the moment someone tries to start them, with
        `ERR_AUDITOR_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/visit_start_depends_on_auditor_certification_state
        """
        program = setup_scheduled_visit()
        auditor_id = program["auditor"]["id"]
        validate_success(
            api_client.suspend_auditor(auditor_id, ADMIN_HEADERS, {"note": "Calibration audit"})
        )
        advance_clock(FIRST_VISIT_START)

        validate_error(
            api_client.start_audit_visit(
                program["visit"]["id"], make_auditor_headers(auditor_id), {},
            ),
            ApiErrorId.ERR_AUDITOR_SUSPENDED,
            expected_status=409,
        )

        visit = validate_success(
            api_client.get_audit_visit(program["visit"]["id"], ADMIN_HEADERS)
        )
        assert visit["status"] == "SCHEDULED"
        assert visit["started_at"] is None

    def test_reinstatement_restamps_the_period_and_permits_the_start(self):
        """Certification resets the review window and unblocks the visit.

        PRD: "Certification advances `PROVISIONAL → CERTIFIED` for a new auditor and
        `SUSPENDED → CERTIFIED` for a reinstated one; either way it sets
        `certification_period_start` to the logical clock and clears `suspension_reason`."

        Design: Difficulty/cross_entity_state_dependency/visit_start_depends_on_auditor_certification_state
        """
        program = setup_scheduled_visit()
        auditor_id = program["auditor"]["id"]
        validate_success(
            api_client.suspend_auditor(auditor_id, ADMIN_HEADERS, {"note": "Calibration audit"})
        )
        advance_clock(FIRST_VISIT_START)

        reinstated = validate_success(api_client.certify_auditor(auditor_id, ADMIN_HEADERS, {}))
        assert reinstated["status"] == "CERTIFIED"
        assert reinstated["suspension_reason"] is None
        assert_instant(
            reinstated["certification_period_start"], FIRST_VISIT_START,
            "certification_period_start",
        )

        started = validate_success(
            api_client.start_audit_visit(
                program["visit"]["id"], make_auditor_headers(auditor_id), {},
            )
        )
        assert started["status"] == "IN_PROGRESS"
        assert_instant(started["started_at"], FIRST_VISIT_START, "started_at")


class TestDisputeFilingDependsOnVisitFinalization:
    def test_a_dispute_cannot_be_filed_against_a_submitted_visit(self):
        """A working document is the auditor's to correct, not the franchisee's to appeal.

        PRD: "If the parent visit is not `FINALIZED`, the filing is rejected with
        `ERR_INVALID_VISIT_STATE`."

        Design: Difficulty/cross_entity_state_dependency/dispute_filing_depends_on_parent_visit_being_finalized
        """
        program = setup_submitted_visit()
        scored_item = program["scored"]["FS-1"]

        validate_error(
            api_client.create_dispute(
                dispute_payload(scored_item["id"], 30), program["franchisee_headers"],
            ),
            ApiErrorId.ERR_INVALID_VISIT_STATE,
            expected_status=409,
        )

        item = validate_success(api_client.get_scored_item(scored_item["id"], ADMIN_HEADERS))
        assert item["status"] == "SCORED", "the rejected filing did not freeze the item"
        _, meta = validate_paginated(api_client.list_disputes(ADMIN_HEADERS))
        assert meta["total_count"] == 0

    def test_finalization_opens_the_appeal_path_for_the_same_item(self):
        """Once finalized the identical filing is accepted and freezes the scored item.

        PRD: "In the same operation, the scored item moves `SCORED → UNDER_DISPUTE`, and that
        single fact freezes a great deal: while any scored item of a visit is
        `UNDER_DISPUTE`, that visit can be neither finalized, nor rescored, nor voided."

        Design: Difficulty/cross_entity_state_dependency/dispute_filing_depends_on_parent_visit_being_finalized
        """
        program = setup_filed_dispute(item_code="FS-1", requested_points=30)

        dispute = program["dispute"]
        assert dispute["status"] == "FILED"
        assert dispute["info_request_count"] == 0
        assert dispute["reviewer_auditor_id"] is None, "an unclaimed dispute names no reviewer"
        assert dispute["requested_points"] == 30
        assert dispute["filed_by_franchisee_id"] == program["franchisee"]["id"]

        item = validate_success(
            api_client.get_scored_item(program["disputed_item"]["id"], ADMIN_HEADERS)
        )
        assert item["status"] == "UNDER_DISPUTE"
        assert item["effective_points_awarded"] == 27, "nothing numeric has moved yet"


class TestVoidDependsOnNoDisputedChild:
    def test_an_open_dispute_blocks_the_void(self):
        """A frozen scored item makes its visit unvoidable.

        PRD: "No scored item of the visit is `UNDER_DISPUTE` — `ERR_UNRESOLVED_DISPUTE`, on
        `POST /audit-visits/{id}/finalize`, `POST /audit-visits/{id}/rescore`, and
        `POST /audit-visits/{id}/void`."

        Design: Difficulty/cross_entity_state_dependency/visit_void_depends_on_no_child_scored_item_under_dispute
        """
        program = setup_filed_dispute(item_code="FS-1", requested_points=30)
        visit_id = program["visit"]["id"]

        validate_error(
            api_client.void_audit_visit(visit_id, void_payload("RUBRIC_DEFECT"), ADMIN_HEADERS),
            ApiErrorId.ERR_UNRESOLVED_DISPUTE,
            expected_status=409,
        )

        visit = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        assert visit["status"] == "FINALIZED"
        assert visit["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert visit["void_reason"] is None

    def test_withdrawing_the_dispute_unblocks_the_void(self):
        """Withdrawal returns the item to SCORED and its visit becomes voidable again.

        PRD: "Withdrawal is available from `FILED`, from `INFO_REQUESTED`, and from
        `EVIDENCE_REVIEW`, accepts an optional `note`, requires that the acting franchisee be
        the dispute's `filed_by_franchisee_id`, stamps `resolved_at`, moves the dispute to
        `WITHDRAWN`, and returns the scored item `UNDER_DISPUTE → SCORED` so that it becomes
        disputable again and its visit becomes finalizable, rescorable, and voidable again."

        Design: Difficulty/cross_entity_state_dependency/visit_void_depends_on_no_child_scored_item_under_dispute
        """
        program = setup_filed_dispute(item_code="FS-1", requested_points=30)
        visit_id = program["visit"]["id"]

        withdrawn = validate_success(
            api_client.withdraw_dispute(
                program["dispute"]["id"], program["franchisee_headers"],
                {"note": "Log misfiled"},
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["resolved_at"] is not None

        item = validate_success(
            api_client.get_scored_item(program["disputed_item"]["id"], ADMIN_HEADERS)
        )
        assert item["status"] == "SCORED"

        voided = validate_success(
            api_client.void_audit_visit(visit_id, void_payload("RUBRIC_DEFECT"), ADMIN_HEADERS)
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "RUBRIC_DEFECT"

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["open_corrective_action_count"] == 0
        assert location["standing_score"] == pytest.approx(0.00, abs=0.01)


class TestVisitCreationDependsOnRubricPublication:
    def test_a_draft_rubric_version_cannot_be_scheduled_against(self):
        """The pinned rubric must be published at the moment the visit is created.

        PRD: "The pinned rubric must be `PUBLISHED` at the moment the visit is created — a
        draft or retired version is rejected with `ERR_RUBRIC_VERSION_NOT_PUBLISHED` — and its
        `effective_from` must fall at or before the visit's `scheduled_start_at`, otherwise the
        request is rejected with `ERR_RUBRIC_NOT_EFFECTIVE`."

        Design: Difficulty/cross_entity_state_dependency/visit_creation_depends_on_rubric_version_being_published
        """
        program = setup_brand_program(publish_rubric=False)
        assert program["rubric_version"]["status"] == "DRAFT"

        payload = audit_visit_payload(
            program["location"]["id"], program["auditor"]["id"],
            program["rubric_version"]["id"],
            "2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z",
        )
        validate_error(
            api_client.create_audit_visit(payload, ADMIN_HEADERS),
            ApiErrorId.ERR_RUBRIC_VERSION_NOT_PUBLISHED,
            expected_status=409,
        )

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 0

    def test_publication_pins_the_visit_to_that_rubric_version(self):
        """Publishing stamps the rubric and lets the identical booking through.

        PRD: "Publication stamps `published_at` with the logical clock."

        Design: Difficulty/cross_entity_state_dependency/visit_creation_depends_on_rubric_version_being_published
        """
        program = setup_brand_program(publish_rubric=False)
        rubric_id = program["rubric_version"]["id"]

        published = validate_success(
            api_client.publish_rubric_version(rubric_id, ADMIN_HEADERS, {})
        )
        assert published["status"] == "PUBLISHED"
        assert_instant(published["published_at"], CLOCK_EPOCH, "published_at")
        assert published["item_count"] == 6
        assert published["critical_item_count"] == 2

        payload = audit_visit_payload(
            program["location"]["id"], program["auditor"]["id"], rubric_id,
            "2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z",
        )
        created = validate_success(
            api_client.create_audit_visit(payload, ADMIN_HEADERS), expected_status=201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["rubric_version_id"] == rubric_id
