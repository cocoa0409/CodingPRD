"""Input validation: evidence targeting, cross-rubric scoring, clock limits and notice."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_EPOCH,
    FIRST_VISIT_END,
    FIRST_VISIT_START,
    INTEGRATOR_HEADERS,
    ApiErrorId,
    add_rubric_items,
    advance_clock,
    api_client,
    audit_visit_payload,
    create_brand,
    create_certified_auditor,
    create_franchisee,
    create_location,
    create_rubric_draft,
    evidence_photo_payload,
    health_inspection_payload,
    live_brand_version,
    make_auditor_headers,
    scored_item_payload,
    setup_brand_program,
    setup_filed_dispute,
    setup_finalized_visit,
    setup_in_progress_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEvidenceTargeting:
    def test_a_photo_with_both_or_neither_target_is_rejected(self):
        """The same rule catches the ambiguous shape and the orphan shape.

        PRD: "An **EvidencePhoto** is attached by either a `Franchisee` or an `Auditor` and
        names exactly one of `corrective_action_id` and `dispute_id`; naming both, or naming
        neither, is rejected with `ERR_EVIDENCE_TARGET_AMBIGUOUS`."

        Design: Corner/validations/evidence_photo_with_both_or_neither_target_is_rejected
        """
        program = setup_filed_dispute(item_code="BS-1", requested_points=15)
        action_id = program["actions"]["FS-1"]["id"]

        validate_error(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:00:00Z",
                    corrective_action_id=action_id,
                    dispute_id=program["dispute"]["id"],
                    file_uri="s3://ev/both.jpg",
                ),
                program["franchisee_headers"],
            ),
            ApiErrorId.ERR_EVIDENCE_TARGET_AMBIGUOUS,
            expected_status=422,
        )
        validate_error(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:00:00Z",
                    file_uri="s3://ev/neither.jpg", caption="Orphan upload",
                ),
                program["franchisee_headers"],
            ),
            ApiErrorId.ERR_EVIDENCE_TARGET_AMBIGUOUS,
            expected_status=422,
        )

        action = validate_success(api_client.get_corrective_action(action_id, ADMIN_HEADERS))
        assert action["evidence_photo_count"] == 0, "neither upload was partially persisted"
        assert action["status"] == "ASSIGNED"

        rows, meta = validate_paginated(
            api_client.list_corrective_action_evidence_photos(
                action_id, ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_exactly_one_target_satisfies_the_rule_for_both_target_kinds(self):
        """One endpoint serves both parents, and each photo hangs off only its own.

        PRD: "An evidence photo names exactly one of `corrective_action_id` and `dispute_id` —
        `ERR_EVIDENCE_TARGET_AMBIGUOUS` (HTTP 422), on `POST /evidence-photos`."

        Design: Corner/validations/exactly_one_evidence_target_satisfies_the_rule_for_both_target_kinds
        """
        program = setup_filed_dispute(item_code="BS-1", requested_points=15)
        action_id = program["actions"]["FS-1"]["id"]
        dispute_id = program["dispute"]["id"]

        action_photo = validate_success(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:40:00Z", corrective_action_id=action_id,
                    file_uri="s3://ev/hood-after.jpg", caption="Hood after degreasing",
                ),
                program["franchisee_headers"],
            ),
            expected_status=201,
        )
        assert action_photo["uploaded_by_role"] == "Franchisee"

        dispute_photo = validate_success(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:45:00Z", dispute_id=dispute_id,
                    file_uri="s3://ev/tile-invoice.jpg",
                ),
                program["franchisee_headers"],
            ),
            expected_status=201,
        )
        assert dispute_photo["id"] != action_photo["id"]

        action = validate_success(api_client.get_corrective_action(action_id, ADMIN_HEADERS))
        assert action["evidence_photo_count"] == 1, "only the action-targeted photo counted"

        submitted = validate_success(
            api_client.submit_corrective_action(
                action_id, program["franchisee_headers"],
                {"remediation_note": "Hood degreased"},
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_count"] == 1

        supplemented = validate_success(
            api_client.supplement_dispute(
                dispute_id, program["franchisee_headers"], {"note": "Invoice attached"},
            )
        )
        assert supplemented["status"] == "EVIDENCE_REVIEW"
        assert supplemented["info_request_count"] == 0, \
            "no information request was needed to reach evidence review"

        dispute_rows, dispute_meta = validate_paginated(
            api_client.list_dispute_evidence_photos(
                dispute_id, ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            )
        )
        assert dispute_meta["total_count"] == 1
        assert dispute_rows[0]["id"] == dispute_photo["id"]

        action_rows, action_meta = validate_paginated(
            api_client.list_corrective_action_evidence_photos(
                action_id, ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            )
        )
        assert action_meta["total_count"] == 1
        assert action_rows[0]["id"] == action_photo["id"]


class TestCrossRubricScoring:
    def test_scoring_an_item_from_another_rubric_version_is_rejected(self):
        """An existing item outside the pinned rubric is a 422, not a 404.

        PRD: "A scored item's rubric item belongs to the visit's pinned rubric version —
        `ERR_RUBRIC_ITEM_NOT_IN_VISIT_RUBRIC` (HTTP 422), on
        `POST /audit-visits/{id}/scored-items`."

        Design: Corner/validations/scoring_an_item_from_another_rubric_version_is_rejected
        """
        program = setup_in_progress_visit()
        brand_id = program["brand"]["id"]
        visit_id = program["visit"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        other = create_rubric_draft(
            brand_id,
            expected_brand_version=live_brand_version(brand_id),
            version_label="RV-2026.2",
        )
        other_items = add_rubric_items(other["id"])

        validate_error(
            api_client.create_scored_item(
                visit_id,
                scored_item_payload(other_items["FS-1"]["id"], 27),
                auditor_headers,
            ),
            ApiErrorId.ERR_RUBRIC_ITEM_NOT_IN_VISIT_RUBRIC,
            expected_status=422,
        )

        accepted = validate_success(
            api_client.create_scored_item(
                visit_id,
                scored_item_payload(program["item_ids"]["FS-1"], 27),
                auditor_headers,
            ),
            expected_status=201,
        )
        assert accepted["status"] == "SCORED"
        assert accepted["severity"] == "CRITICAL"

        rows, meta = validate_paginated(
            api_client.list_scored_items(
                ADMIN_HEADERS, params={"visit_id": visit_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, "the refused call persisted nothing"
        assert rows[0]["id"] == accepted["id"]


class TestSuppliedTimestamps:
    def test_supplied_timestamps_may_equal_the_clock_but_never_exceed_it(self):
        """Equality is accepted on both channels; one second past is refused.

        PRD: "Client-supplied instants that describe the past are validated against the same
        clock: neither `captured_at` on a photo nor `inspection_date` on a health inspection may
        lie after the current logical clock, and a violation of either is rejected with
        `ERR_TIMESTAMP_IN_FUTURE` (HTTP 422)."

        Design: Corner/validations/supplied_timestamps_may_equal_the_clock_but_never_exceed_it
        """
        program = setup_finalized_visit()
        location_id = program["location"]["id"]
        action_id = program["actions"]["FS-1"]["id"]

        validate_error(
            api_client.create_health_inspection(
                health_inspection_payload(location_id, "2026-08-06T00:00:00Z", 95, "A"),
                INTEGRATOR_HEADERS,
            ),
            ApiErrorId.ERR_TIMESTAMP_IN_FUTURE,
            expected_status=422,
        )
        on_the_dot = validate_success(
            api_client.create_health_inspection(
                health_inspection_payload(location_id, FIRST_VISIT_END, 95, "A"),
                INTEGRATOR_HEADERS,
            ),
            expected_status=201,
        )
        assert on_the_dot["status"] == "RECORDED"

        validate_error(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T13:00:01Z", corrective_action_id=action_id,
                    file_uri="s3://ev/late.jpg",
                ),
                program["franchisee_headers"],
            ),
            ApiErrorId.ERR_TIMESTAMP_IN_FUTURE,
            expected_status=422,
        )
        validate_success(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    FIRST_VISIT_END, corrective_action_id=action_id,
                    file_uri="s3://ev/onthedot.jpg",
                ),
                program["franchisee_headers"],
            ),
            expected_status=201,
        )

        action = validate_success(api_client.get_corrective_action(action_id, ADMIN_HEADERS))
        assert action["evidence_photo_count"] == 1

        visit = validate_success(
            api_client.get_audit_visit(program["visit"]["id"], ADMIN_HEADERS)
        )
        assert visit["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert visit["health_component_percent"] is None, \
            "the accepted inspection did not alter an already finalized visit"


class TestSubmitCompleteness:
    def test_submit_requires_every_critical_item_scored_while_gaps_score_zero(self):
        """The critical gate is a hard stop; non-critical gaps merely earn nothing.

        PRD: "Non-critical items may be left unscored; the arithmetic treats them as having
        earned zero of their maximum points, which is a deliberate incentive to score the whole
        rubric."

        Design: Corner/validations/submit_requires_every_critical_item_scored_while_non_critical_gaps_score_zero
        """
        program = setup_in_progress_visit()
        visit_id = program["visit"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        validate_success(
            api_client.create_scored_item(
                visit_id, scored_item_payload(program["item_ids"]["FS-1"], 27), auditor_headers,
            ),
            expected_status=201,
        )
        validate_error(
            api_client.submit_audit_visit(visit_id, auditor_headers, {}),
            ApiErrorId.ERR_CRITICAL_ITEMS_UNSCORED,
            expected_status=422,
        )

        validate_success(
            api_client.create_scored_item(
                visit_id, scored_item_payload(program["item_ids"]["FS-2"], 20), auditor_headers,
            ),
            expected_status=201,
        )
        submitted = validate_success(
            api_client.submit_audit_visit(visit_id, auditor_headers, {})
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["food_safety_percent"] == pytest.approx(95.00, abs=0.01)
        assert submitted["brand_standards_percent"] == pytest.approx(0.00, abs=0.01), \
            "the unscored non-critical items still count in their section denominator"
        assert submitted["facility_percent"] == pytest.approx(0.00, abs=0.01)
        assert submitted["critical_violation_count"] == 1
        assert submitted["critical_penalty_points"] == pytest.approx(5.00, abs=0.01)
        assert submitted["composite_score"] == pytest.approx(63.50, abs=0.01), \
            "0.60 * 42.50 + 0.40 * 95.00"
        assert submitted["grade"] == "FAIL"

        _, meta = validate_paginated(
            api_client.list_scored_items(
                ADMIN_HEADERS, params={"visit_id": visit_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, "unscored items produce no scored-item rows"


class TestAnnouncedNotice:
    def test_the_notice_rule_applies_only_to_announced_visits(self):
        """An unannounced visit a day out is fine; an announced one at 57 hours is not.

        PRD: "That value must be at least 72.00 — three full days of notice — and a shorter
        lead time is rejected with `ERR_ANNOUNCED_NOTICE_TOO_SHORT`. For `UNANNOUNCED` and
        `SHADOW` visits `announced_notice_hours` stays null, since neither carries a notice
        obligation."

        Design: Corner/validations/the_seventy_two_hour_notice_rule_applies_only_to_announced_visits
        """
        program = setup_brand_program(brand_overrides={"unannounced_min_ratio_pct": 0})
        location_id = program["location"]["id"]

        def candidate(start_at, end_at, visit_type):
            return audit_visit_payload(
                location_id, program["auditor"]["id"], program["rubric_version"]["id"],
                start_at, end_at, visit_type=visit_type,
            )

        unannounced = validate_success(
            api_client.create_audit_visit(
                candidate("2026-08-02T09:00:00Z", "2026-08-02T13:00:00Z", "UNANNOUNCED"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert unannounced["visit_type"] == "UNANNOUNCED"
        assert unannounced["announced_notice_hours"] is None, \
            "33 hours of notice is irrelevant to an unannounced visit"

        validate_error(
            api_client.create_audit_visit(
                candidate("2026-08-03T09:00:00Z", "2026-08-03T13:00:00Z", "ANNOUNCED"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_ANNOUNCED_NOTICE_TOO_SHORT,
            expected_status=422,
        )

        announced = validate_success(
            api_client.create_audit_visit(
                candidate("2026-08-04T01:00:00Z", "2026-08-04T05:00:00Z", "ANNOUNCED"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert announced["announced_notice_hours"] == pytest.approx(73.00, abs=0.01)

        _, meta = validate_paginated(
            api_client.list_audit_visits(ADMIN_HEADERS, params={"location_id": location_id})
        )
        assert meta["total_count"] == 2, "the short-notice candidate was not persisted"


class TestCascadingRubricChecks:
    def test_effectiveness_is_only_checked_once_publication_passes(self):
        """The effective_from problem is invisible while the version is still a draft.

        PRD: "The pinned rubric must be `PUBLISHED` at the moment the visit is created — a
        draft or retired version is rejected with `ERR_RUBRIC_VERSION_NOT_PUBLISHED` — and its
        `effective_from` must fall at or before the visit's `scheduled_start_at`, otherwise the
        request is rejected with `ERR_RUBRIC_NOT_EFFECTIVE`."

        Design: Corner/validations/rubric_effectiveness_is_only_checked_once_the_publication_check_passes
        """
        advance_clock(CLOCK_EPOCH)
        brand = create_brand()
        franchisee = create_franchisee(brand["id"])
        location = create_location(brand["id"], franchisee["id"])
        auditor = create_certified_auditor()
        draft = create_rubric_draft(brand["id"], effective_from="2026-09-01T00:00:00Z")
        add_rubric_items(draft["id"])

        def candidate(start_at, end_at):
            return audit_visit_payload(
                location["id"], auditor["id"], draft["id"], start_at, end_at,
            )

        validate_error(
            api_client.create_audit_visit(
                candidate(FIRST_VISIT_START, FIRST_VISIT_END), ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_RUBRIC_VERSION_NOT_PUBLISHED,
            expected_status=409,
        )

        published = validate_success(
            api_client.publish_rubric_version(draft["id"], ADMIN_HEADERS, {})
        )
        assert published["status"] == "PUBLISHED"

        validate_error(
            api_client.create_audit_visit(
                candidate(FIRST_VISIT_START, FIRST_VISIT_END), ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_RUBRIC_NOT_EFFECTIVE,
            expected_status=422,
        )

        created = validate_success(
            api_client.create_audit_visit(
                candidate("2026-09-05T09:00:00Z", "2026-09-05T13:00:00Z"), ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert created["status"] == "SCHEDULED"

        _, meta = validate_paginated(
            api_client.list_audit_visits(
                ADMIN_HEADERS, params={"rubric_version_id": draft["id"]}
            )
        )
        assert meta["total_count"] == 1
