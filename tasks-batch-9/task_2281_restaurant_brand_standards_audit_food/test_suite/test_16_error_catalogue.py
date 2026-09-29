"""The declared error catalogue: each identifier reached on its own path."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_EPOCH,
    FIRST_VISIT_END,
    FIRST_VISIT_START,
    INTEGRATOR_HEADERS,
    NON_EXISTENT_UUID,
    SCORE_SHEET_ONE_CRITICAL,
    SCORE_SHEET_SHADOW_CLOSE,
    ApiErrorId,
    add_rubric_items,
    advance_clock,
    api_client,
    assert_instant,
    audit_visit_payload,
    auditor_payload,
    brand_payload,
    calibration_record_payload,
    create_auditor,
    create_brand,
    create_franchisee,
    create_rubric_draft,
    dispute_payload,
    evidence_photo_payload,
    finalize_visit,
    franchisee_payload,
    health_inspection_payload,
    live_brand_version,
    location_payload,
    make_auditor_headers,
    make_calibration_reviewer_headers,
    rescore_payload,
    resolve_dispute_payload,
    rubric_item_payload,
    rubric_version_payload,
    schedule_visit,
    score_visit,
    scored_item_payload,
    setup_brand_program,
    setup_filed_dispute,
    setup_in_progress_visit,
    setup_submitted_corrective_action,
    setup_verified_corrective_action,
    start_visit,
    submit_visit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_payload,
    void_payload,
)

LATER_VISIT_START = "2026-08-26T09:00:00Z"
LATER_VISIT_END = "2026-08-26T13:00:00Z"


class TestBodyForeignKeys:
    def test_every_body_foreign_key_reports_its_own_not_found_error(self):
        """Ten unresolvable body keys produce ten different 404 identifiers.

        PRD: "Foreign keys carried in a request body are resolved after the path and before any
        business rule, and produce the corresponding 404 for the entity that is missing —
        including `ERR_RUBRIC_ITEM_NOT_FOUND` for a `rubric_item_id` that does not exist."

        Design: Corner/errors/every_body_foreign_key_404_is_triggerable_with_its_own_error_id
        """
        program = setup_filed_dispute(item_code="BS-1", requested_points=15)
        location_id = program["location"]["id"]
        auditor_id = program["auditor"]["id"]
        rubric_version_id = program["rubric_version"]["id"]
        visit_id = program["visit"]["id"]

        def visit_candidate(**overrides):
            payload = audit_visit_payload(
                location_id, auditor_id, rubric_version_id,
                LATER_VISIT_START, LATER_VISIT_END,
            )
            payload.update(overrides)
            return payload

        validate_error(
            api_client.create_franchisee(
                franchisee_payload(NON_EXISTENT_UUID, legal_name="Ghost Holdings LLC"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_BRAND_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_location(
                location_payload(
                    program["brand"]["id"], NON_EXISTENT_UUID,
                    store_number="SKWR-099", region_code="WEST",
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_FRANCHISEE_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_audit_visit(
                visit_candidate(auditor_id=NON_EXISTENT_UUID), ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_AUDITOR_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_audit_visit(
                visit_candidate(rubric_version_id=NON_EXISTENT_UUID), ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_RUBRIC_VERSION_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_audit_visit(
                visit_candidate(visit_type="SHADOW", shadow_of_visit_id=NON_EXISTENT_UUID),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_VISIT_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_health_inspection(
                health_inspection_payload(NON_EXISTENT_UUID, CLOCK_EPOCH, 90, "A"),
                INTEGRATOR_HEADERS,
            ),
            ApiErrorId.ERR_LOCATION_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_scored_item(
                visit_id, scored_item_payload(NON_EXISTENT_UUID, 10),
                program["auditor_headers"],
            ),
            ApiErrorId.ERR_RUBRIC_ITEM_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_dispute(
                dispute_payload(NON_EXISTENT_UUID, 15), program["franchisee_headers"],
            ),
            ApiErrorId.ERR_SCORED_ITEM_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:00:00Z", corrective_action_id=NON_EXISTENT_UUID,
                    file_uri="s3://ev/a.jpg",
                ),
                program["franchisee_headers"],
            ),
            ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:00:00Z", dispute_id=NON_EXISTENT_UUID,
                    file_uri="s3://ev/b.jpg",
                ),
                program["franchisee_headers"],
            ),
            ApiErrorId.ERR_DISPUTE_NOT_FOUND,
            expected_status=404,
        )

        _, meta = validate_paginated(
            api_client.list_audit_visits(ADMIN_HEADERS, params={"location_id": location_id})
        )
        assert meta["total_count"] == 1, "none of the ten refused calls created a row"


class TestRubricAuthoringGates:
    def test_authoring_and_publish_gates_each_report_their_own_error(self):
        """Uniqueness is scoped three ways and the two publish gates fire in order.

        PRD: "Duplicate `item_code` or `display_order` values inside one rubric version are
        likewise rejected with `ERR_DUPLICATE_RUBRIC_ENTRY`."

        PRD: "A points mismatch reports `ERR_RUBRIC_TOTAL_MISMATCH`, while a missing critical
        item or an empty section reports `ERR_RUBRIC_SECTION_INCOMPLETE`."

        Design: Corner/errors/rubric_authoring_and_publish_gates_are_each_triggerable
        """
        advance_clock(CLOCK_EPOCH)
        brand = create_brand()
        brand_id = brand["id"]

        balanced = create_rubric_draft(brand_id, expected_brand_version=brand["version"])
        incomplete = create_rubric_draft(
            brand_id, version_label="RV-2026.4", total_points=45,
        )
        add_rubric_items(
            balanced["id"],
            items=[
                {"item_code": "FS-1", "section": "FOOD_SAFETY", "max_points": 30,
                 "is_critical": True, "display_order": 1},
                {"item_code": "BS-1", "section": "BRAND_STANDARDS", "max_points": 15,
                 "is_critical": False, "display_order": 3},
                {"item_code": "FC-1", "section": "FACILITY", "max_points": 12,
                 "is_critical": False, "display_order": 5},
            ],
        )
        add_rubric_items(
            incomplete["id"],
            items=[
                {"item_code": "FS-1", "section": "FOOD_SAFETY", "max_points": 30,
                 "is_critical": True, "display_order": 1},
                {"item_code": "BS-1", "section": "BRAND_STANDARDS", "max_points": 15,
                 "is_critical": False, "display_order": 3},
            ],
        )

        validate_error(
            api_client.create_rubric_item(
                balanced["id"],
                rubric_item_payload("FS-1", "FOOD_SAFETY", 25, 7),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_RUBRIC_ENTRY,
            expected_status=409,
        )
        validate_error(
            api_client.create_rubric_item(
                balanced["id"],
                rubric_item_payload("FS-9", "FOOD_SAFETY", 25, 1),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_RUBRIC_ENTRY,
            expected_status=409,
        )
        validate_error(
            api_client.create_rubric_version(
                rubric_version_payload(brand_id, live_brand_version(brand_id)),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_RUBRIC_ENTRY,
            expected_status=409,
        )

        validate_error(
            api_client.publish_rubric_version(balanced["id"], ADMIN_HEADERS, {}),
            ApiErrorId.ERR_RUBRIC_TOTAL_MISMATCH,
            expected_status=422,
        )
        validate_success(
            api_client.create_rubric_item(
                balanced["id"],
                rubric_item_payload("BS-2", "BRAND_STANDARDS", 43, 4),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        published = validate_success(
            api_client.publish_rubric_version(balanced["id"], ADMIN_HEADERS, {})
        )
        assert published["status"] == "PUBLISHED", \
            "30 + 15 + 12 + 43 now equals the declared 100"
        assert published["item_count"] == 4
        assert published["critical_item_count"] == 1

        validate_error(
            api_client.publish_rubric_version(incomplete["id"], ADMIN_HEADERS, {}),
            ApiErrorId.ERR_RUBRIC_SECTION_INCOMPLETE,
            expected_status=422,
        )

        rows, meta = validate_paginated(
            api_client.list_rubric_items(
                incomplete["id"], ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, \
            "item_code FS-1 and display_order 1 were reusable in a different rubric version"
        assert {row["section"] for row in rows} == {"FOOD_SAFETY", "BRAND_STANDARDS"}


class TestDuplicateResourceCodes:
    def test_codes_are_unique_globally_or_within_the_brand_as_declared(self):
        """One error identifier covers three code fields with two different scopes.

        PRD: "`brand_code`, `employee_code`, and `store_number` within a brand are unique —
        `ERR_DUPLICATE_RESOURCE_CODE` (HTTP 409), on `POST /brands`, `POST /auditors`, and
        `POST /locations`."

        Design: Corner/errors/duplicate_resource_codes_are_rejected_with_brand_scoped_store_numbers
        """
        program = setup_brand_program()

        validate_error(
            api_client.create_brand(
                brand_payload(name="Skewer House West", brand_code="SKWR"), ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_RESOURCE_CODE,
            expected_status=409,
        )
        validate_error(
            api_client.create_auditor(
                auditor_payload(full_name="Rae Ito", employee_code="AUD-101"), ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_RESOURCE_CODE,
            expected_status=409,
        )
        validate_error(
            api_client.create_location(
                location_payload(
                    program["brand"]["id"], program["franchisee"]["id"],
                    store_number="SKWR-014", region_code="WEST",
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_RESOURCE_CODE,
            expected_status=409,
        )

        other_brand = create_brand(name="Skewer House Express", brand_code="SKWX")
        other_franchisee = create_franchisee(
            other_brand["id"], legal_name="Lakeshore QSR Group Inc",
            contact_email="ops@lakeshore.test",
        )
        reused = validate_success(
            api_client.create_location(
                location_payload(
                    other_brand["id"], other_franchisee["id"], store_number="SKWR-014",
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert reused["store_number"] == "SKWR-014", \
            "store numbers are unique within a brand, not across brands"
        assert reused["brand_id"] == other_brand["id"]

        for brand_id in (program["brand"]["id"], other_brand["id"]):
            _, meta = validate_paginated(
                api_client.list_locations(ADMIN_HEADERS, params={"brand_id": brand_id})
            )
            assert meta["total_count"] == 1

        first_brand = validate_success(
            api_client.get_brand(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert first_brand["location_count"] == 1, "the refused duplicate was never counted"


class TestVisitShapeErrors:
    def test_window_ordering_and_shadow_linkage_report_distinct_errors(self):
        """A degenerate window, two link shapes and two illegal targets stay separable.

        PRD: "The window itself must be non-degenerate: `scheduled_end_at` strictly after
        `scheduled_start_at`, or `ERR_INVALID_VISIT_WINDOW`."

        PRD: "`shadow_of_visit_id` must be present exactly when `visit_type` is `SHADOW` and
        absent otherwise; either mismatch is rejected with `ERR_SHADOW_LINK_MISMATCH`. The named
        target must be a non-shadow visit at the same location, pinned to the same
        `rubric_version_id`, and not itself voided; a target that fails any of those tests is
        rejected with `ERR_SHADOW_TARGET_INVALID`."

        Design: Corner/errors/visit_window_and_shadow_link_shape_errors_are_each_triggerable
        """
        program = setup_brand_program(with_reviewer=True)
        location_id = program["location"]["id"]
        auditor_id = program["auditor"]["id"]
        reviewer_id = program["reviewer"]["id"]
        rubric_version_id = program["rubric_version"]["id"]

        primary = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
        voided = schedule_visit(program, "2026-08-12T09:00:00Z", "2026-08-12T13:00:00Z")
        voided = validate_success(
            api_client.void_audit_visit(
                voided["id"], void_payload("SCHEDULING_ERROR"), ADMIN_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        shadow = schedule_visit(
            program, FIRST_VISIT_START, FIRST_VISIT_END, visit_type="SHADOW",
            auditor_id=reviewer_id, shadow_of_visit_id=primary["id"],
        )

        def candidate(start_at, end_at, acting_auditor_id, **overrides):
            return audit_visit_payload(
                location_id, acting_auditor_id, rubric_version_id,
                start_at, end_at, **overrides,
            )

        validate_error(
            api_client.create_audit_visit(
                candidate("2026-08-20T13:00:00Z", "2026-08-20T13:00:00Z", auditor_id),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_VISIT_WINDOW,
            expected_status=422,
        )
        validate_error(
            api_client.create_audit_visit(
                candidate(
                    "2026-08-21T09:00:00Z", "2026-08-21T13:00:00Z", auditor_id,
                    shadow_of_visit_id=primary["id"],
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_SHADOW_LINK_MISMATCH,
            expected_status=422,
        )
        validate_error(
            api_client.create_audit_visit(
                candidate(
                    "2026-08-21T09:00:00Z", "2026-08-21T13:00:00Z", reviewer_id,
                    visit_type="SHADOW",
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_SHADOW_LINK_MISMATCH,
            expected_status=422,
        )
        validate_error(
            api_client.create_audit_visit(
                candidate(
                    "2026-08-20T09:00:00Z", "2026-08-20T13:00:00Z", auditor_id,
                    visit_type="SHADOW", shadow_of_visit_id=shadow["id"],
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_SHADOW_TARGET_INVALID,
            expected_status=422,
        )
        validate_error(
            api_client.create_audit_visit(
                candidate(
                    "2026-08-20T09:00:00Z", "2026-08-20T13:00:00Z", reviewer_id,
                    visit_type="SHADOW", shadow_of_visit_id=voided["id"],
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_SHADOW_TARGET_INVALID,
            expected_status=422,
        )

        rows, meta = validate_paginated(
            api_client.list_audit_visits(
                ADMIN_HEADERS, params={"location_id": location_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3, "no refused candidate was persisted"
        assert {row["id"] for row in rows} == {primary["id"], voided["id"], shadow["id"]}


class TestProvisionalAuditorGate:
    def test_a_provisional_auditor_may_not_start_verify_or_review(self):
        """The block is the actor, not the resource, and certification lifts all three.

        PRD: "An auditor whose `status` is `PROVISIONAL` may be scheduled onto a calendar but
        may not act: visit start, corrective-action verification, dispute information requests,
        and dispute resolution all reject with `ERR_AUDITOR_NOT_CERTIFIED`."

        Design: Corner/errors/provisional_auditors_cannot_start_verify_or_review_until_certified
        """
        program = setup_submitted_corrective_action(item_code="FS-1")
        program = setup_filed_dispute(
            program=program, item_code="BS-1", requested_points=15,
        )
        action_id = program["action"]["id"]
        assert program["action"]["status"] == "SUBMITTED"
        assert program["dispute"]["status"] == "FILED"

        provisional = create_auditor(full_name="Lee Park", employee_code="AUD-202")
        assert provisional["status"] == "PROVISIONAL"
        assert provisional["reliability_score"] == pytest.approx(70.00, abs=0.01)
        provisional_headers = make_auditor_headers(provisional["id"])
        provisional_reviewer_headers = make_calibration_reviewer_headers(provisional["id"])

        later = schedule_visit(
            program, LATER_VISIT_START, LATER_VISIT_END, auditor_id=provisional["id"],
        )
        assert later["status"] == "SCHEDULED", \
            "a provisional auditor may still be placed on the calendar"

        validate_error(
            api_client.verify_corrective_action(
                action_id, verify_payload("ACCEPTED"), provisional_headers,
            ),
            ApiErrorId.ERR_AUDITOR_NOT_CERTIFIED,
            expected_status=409,
        )
        validate_error(
            api_client.request_dispute_info(
                program["dispute"]["id"],
                {"information_requested": "Send the dated tile replacement invoice."},
                provisional_reviewer_headers,
            ),
            ApiErrorId.ERR_AUDITOR_NOT_CERTIFIED,
            expected_status=409,
        )

        advance_clock("2026-08-26T08:30:00Z")
        validate_error(
            api_client.start_audit_visit(later["id"], provisional_headers, {}),
            ApiErrorId.ERR_AUDITOR_NOT_CERTIFIED,
            expected_status=409,
        )

        certified = validate_success(
            api_client.certify_auditor(provisional["id"], ADMIN_HEADERS, {})
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["reliability_score"] == pytest.approx(70.00, abs=0.01), \
            "the floor is met exactly, and the floor is not a strict inequality"
        assert_instant(
            certified["certification_period_start"], "2026-08-26T08:30:00Z",
            "certification_period_start",
        )
        assert certified["suspension_reason"] is None

        started = validate_success(
            api_client.start_audit_visit(later["id"], provisional_headers, {})
        )
        assert started["status"] == "IN_PROGRESS", \
            "the identical call now passes the priority-13 check"
        assert_instant(started["started_at"], "2026-08-26T08:30:00Z", "started_at")


class TestCorrectiveActionAndDisputeGates:
    def test_state_gates_and_dispute_point_ranges_each_report_their_own_error(self):
        """Two state errors and two range errors stay distinct from the duplicate-filing error.

        PRD: "`requested_points` must exceed the scored item's current `points_awarded` and must
        not exceed the rubric item's `max_points`; a value outside that range is rejected with
        `ERR_DISPUTE_POINTS_INVALID`. Only one live dispute may exist per scored item: if another
        dispute on the same item is in `FILED`, `INFO_REQUESTED`, or `EVIDENCE_REVIEW`, the
        filing is rejected with `ERR_DISPUTE_ALREADY_OPEN`."

        PRD: "Any action attempted against a dispute whose current state does not permit it — a
        supplement against a resolved dispute, a resolution against a dispute still in `FILED` —
        is rejected with `ERR_INVALID_DISPUTE_STATE`."

        Design: Corner/errors/corrective_action_and_dispute_gate_errors_are_each_triggerable
        """
        program = setup_filed_dispute(
            item_code="BS-1", requested_points=15, with_reviewer=True,
        )
        disputed_item = program["disputed_item"]
        dispute_id = program["dispute"]["id"]

        validate_error(
            api_client.verify_corrective_action(
                program["actions"]["FS-1"]["id"], verify_payload("ACCEPTED"),
                program["auditor_headers"],
            ),
            ApiErrorId.ERR_INVALID_CORRECTIVE_ACTION_STATE,
            expected_status=409,
        )
        validate_error(
            api_client.resolve_dispute(
                dispute_id, resolve_dispute_payload("UPHELD"),
                program["reviewer_calibration_headers"],
            ),
            ApiErrorId.ERR_INVALID_DISPUTE_STATE,
            expected_status=409,
        )

        validate_error(
            api_client.create_dispute(
                dispute_payload(disputed_item["id"], 12), program["franchisee_headers"],
            ),
            ApiErrorId.ERR_DISPUTE_POINTS_INVALID,
            expected_status=422,
        )
        validate_error(
            api_client.create_dispute(
                dispute_payload(disputed_item["id"], 20), program["franchisee_headers"],
            ),
            ApiErrorId.ERR_DISPUTE_POINTS_INVALID,
            expected_status=422,
        )
        validate_error(
            api_client.create_dispute(
                dispute_payload(disputed_item["id"], 15), program["franchisee_headers"],
            ),
            ApiErrorId.ERR_DISPUTE_ALREADY_OPEN,
            expected_status=409,
        )

        other = validate_success(
            api_client.create_dispute(
                dispute_payload(program["scored"]["FC-1"]["id"], 12),
                program["franchisee_headers"],
            ),
            expected_status=201,
        )
        assert other["status"] == "FILED", \
            "the open-dispute rule is scoped to one scored item at a time"

        rows, meta = validate_paginated(
            api_client.list_disputes(
                ADMIN_HEADERS,
                params={"scored_item_id": disputed_item["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1, "none of the three refused filings persisted"
        assert rows[0]["id"] == dispute_id


class TestLateCureAndVoidBlocking:
    def test_an_escalated_critical_action_blocks_late_cure_and_a_verified_one_blocks_void(self):
        """The critical track closes to late cures while the standard track stays open.

        PRD: "Because a critical action leaves `OVERDUE` in the same operation that put it
        there, a late submission against it is rejected with `ERR_LATE_CURE_NOT_ALLOWED`."

        PRD: "It requires that no scored item be `UNDER_DISPUTE` and that no corrective action
        created by this visit be `VERIFIED` — a verified remediation is a fact about the world
        that a void cannot retract, so the attempt is rejected with
        `ERR_VERIFIED_ACTION_BLOCKS_VOID`."

        Design: Corner/errors/late_cure_and_void_blocking_errors_are_each_triggerable
        """
        program = setup_verified_corrective_action(item_code="BS-1")
        critical_id = program["actions"]["FS-1"]["id"]
        standard_id = program["actions"]["FC-1"]["id"]
        visit_id = program["visit"]["id"]

        for action_id in (critical_id, standard_id):
            validate_success(
                api_client.create_evidence_photo(
                    evidence_photo_payload(
                        "2026-08-05T12:50:00Z", corrective_action_id=action_id,
                        file_uri=f"s3://ev/{action_id}.jpg",
                    ),
                    program["franchisee_headers"],
                ),
                expected_status=201,
            )

        advance_clock("2026-08-09T00:00:00Z")
        first_sweep = validate_success(api_client.run_overdue_sweep(ADMIN_HEADERS, {}))
        assert first_sweep["swept_count"] == 1
        assert first_sweep["escalated_count"] == 1

        escalated = validate_success(
            api_client.get_corrective_action(critical_id, ADMIN_HEADERS)
        )
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalated_at"] is not None

        validate_error(
            api_client.submit_corrective_action(
                critical_id, program["franchisee_headers"],
                {"remediation_note": "Hood degreased, late but done."},
            ),
            ApiErrorId.ERR_LATE_CURE_NOT_ALLOWED,
            expected_status=409,
        )
        validate_error(
            api_client.void_audit_visit(
                visit_id, void_payload("RUBRIC_DEFECT"), ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_VERIFIED_ACTION_BLOCKS_VOID,
            expected_status=409,
        )

        advance_clock("2026-08-20T00:00:00Z")
        second_sweep = validate_success(api_client.run_overdue_sweep(ADMIN_HEADERS, {}))
        assert second_sweep["swept_count"] == 1, "only the standard action was still open"
        assert second_sweep["overdue_count"] == 1
        assert second_sweep["escalated_count"] == 0

        late_cure = validate_success(
            api_client.submit_corrective_action(
                standard_id, program["franchisee_headers"],
                {"remediation_note": "Tile regrouted after the deadline."},
            )
        )
        assert late_cure["status"] == "SUBMITTED", \
            "a standard action may still be cured from OVERDUE"
        assert late_cure["submission_count"] == 1

        visit = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        assert visit["status"] == "FINALIZED", "the refused void changed nothing"
        assert visit["composite_score"] == pytest.approx(90.70, abs=0.01)

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["escalation_level"] == 1
        assert location["franchise_agreement_status"] == "NOTICE_OF_DEFAULT"
        assert location["open_corrective_action_count"] == 1


class TestCalibrationInputErrors:
    def test_incomplete_calibration_inputs_and_a_repeat_recording_are_refused(self):
        """Both input failures share one code, and the shadow visit admits one record only.

        PRD: "The named visit must have `visit_type` `SHADOW`, must have a non-null
        `shadow_of_visit_id`, and both visits must carry a non-null `composite_score`; any of
        those failing reports `ERR_CALIBRATION_INPUTS_INCOMPLETE`. Only one calibration record
        may ever exist per shadow visit, and a second attempt is rejected with
        `ERR_CALIBRATION_ALREADY_RECORDED`."

        Design: Corner/errors/calibration_input_and_uniqueness_errors_are_each_triggerable
        """
        program = setup_brand_program(with_reviewer=True)
        auditor_id = program["auditor"]["id"]
        reviewer_id = program["reviewer"]["id"]
        reviewer_headers = program["reviewer_calibration_headers"]

        primary = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
        scored_shadow = schedule_visit(
            program, FIRST_VISIT_START, FIRST_VISIT_END, visit_type="SHADOW",
            auditor_id=reviewer_id, shadow_of_visit_id=primary["id"],
        )
        unscored_shadow = schedule_visit(
            program, "2026-08-06T09:00:00Z", "2026-08-06T13:00:00Z", visit_type="SHADOW",
            auditor_id=reviewer_id, shadow_of_visit_id=primary["id"],
        )
        assert unscored_shadow["composite_score"] is None

        start_visit(program, primary["id"], at=FIRST_VISIT_START)
        score_visit(program, primary["id"], SCORE_SHEET_ONE_CRITICAL)
        submit_visit(program, primary["id"])
        start_visit(program, scored_shadow["id"], auditor_id=reviewer_id)
        score_visit(
            program, scored_shadow["id"], SCORE_SHEET_SHADOW_CLOSE, auditor_id=reviewer_id,
        )
        submit_visit(program, scored_shadow["id"], auditor_id=reviewer_id)
        finalized_primary = finalize_visit(program, primary["id"], at=FIRST_VISIT_END)
        assert finalized_primary["composite_score"] == pytest.approx(90.70, abs=0.01)

        validate_error(
            api_client.create_calibration_record(
                calibration_record_payload(primary["id"]), reviewer_headers,
            ),
            ApiErrorId.ERR_CALIBRATION_INPUTS_INCOMPLETE,
            expected_status=422,
        )
        validate_error(
            api_client.create_calibration_record(
                calibration_record_payload(unscored_shadow["id"]), reviewer_headers,
            ),
            ApiErrorId.ERR_CALIBRATION_INPUTS_INCOMPLETE,
            expected_status=422,
        )

        record = validate_success(
            api_client.create_calibration_record(
                calibration_record_payload(scored_shadow["id"]), reviewer_headers,
            ),
            expected_status=201,
        )
        assert record["variance_points"] == pytest.approx(0.50, abs=0.01), \
            "90.70 against the shadow's 90.20"
        assert record["band"] == "EXCELLENT"
        assert record["reliability_delta"] == pytest.approx(4.00, abs=0.01)

        validate_error(
            api_client.create_calibration_record(
                calibration_record_payload(scored_shadow["id"]), reviewer_headers,
            ),
            ApiErrorId.ERR_CALIBRATION_ALREADY_RECORDED,
            expected_status=409,
        )

        audited = validate_success(api_client.get_auditor(auditor_id, ADMIN_HEADERS))
        assert audited["reliability_score"] == pytest.approx(74.00, abs=0.01), \
            "the +4.00 delta was applied exactly once"

        rows, meta = validate_paginated(
            api_client.list_auditor_calibration_records(
                auditor_id, ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == record["id"]


class TestScoringAndRescoreCeilings:
    def test_duplicate_scoring_and_the_third_rescore_are_each_refused(self):
        """One item is scored once, then corrected at most twice.

        PRD: "The rubric item is not already scored on this visit — `ERR_ITEM_ALREADY_SCORED`
        (HTTP 409), on `POST /audit-visits/{id}/scored-items`."

        PRD: "`rescore_count` is below 2 — `ERR_RESCORE_LIMIT_REACHED` (HTTP 409), on
        `POST /audit-visits/{id}/rescore`."

        Design: Corner/errors/duplicate_item_scoring_and_the_rescore_ceiling_are_each_triggerable
        """
        program = setup_in_progress_visit()
        visit_id = program["visit"]["id"]
        auditor_headers = program["auditor_headers"]
        item_ids = program["item_ids"]

        first = validate_success(
            api_client.create_scored_item(
                visit_id, scored_item_payload(item_ids["FS-1"], 27), auditor_headers,
            ),
            expected_status=201,
        )
        validate_error(
            api_client.create_scored_item(
                visit_id, scored_item_payload(item_ids["FS-1"], 25), auditor_headers,
            ),
            ApiErrorId.ERR_ITEM_ALREADY_SCORED,
            expected_status=409,
        )

        for code, points in (
            ("FS-2", 20), ("BS-1", 12), ("BS-2", 15), ("FC-1", 10), ("FC-2", 8),
        ):
            validate_success(
                api_client.create_scored_item(
                    visit_id, scored_item_payload(item_ids[code], points), auditor_headers,
                ),
                expected_status=201,
            )

        submitted = validate_success(
            api_client.submit_audit_visit(visit_id, auditor_headers, {})
        )
        assert submitted["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert submitted["grade"] == "PASS"
        assert submitted["rescore_count"] == 0

        raised = validate_success(
            api_client.rescore_audit_visit(
                visit_id,
                rescore_payload(first["id"], 30, submitted["version"]),
                auditor_headers,
            )
        )
        assert raised["rescore_count"] == 1
        assert raised["version"] == submitted["version"] + 1
        assert raised["composite_score"] == pytest.approx(97.20, abs=0.01), \
            "0.60 * 95.33 + 0.40 * 100.00 once the critical violation is gone"
        assert raised["grade"] == "PASS"

        restored = validate_success(
            api_client.rescore_audit_visit(
                visit_id,
                rescore_payload(first["id"], 27, raised["version"]),
                auditor_headers,
            )
        )
        assert restored["rescore_count"] == 2
        assert restored["version"] == raised["version"] + 1
        assert restored["composite_score"] == pytest.approx(90.70, abs=0.01)

        validate_error(
            api_client.rescore_audit_visit(
                visit_id,
                rescore_payload(first["id"], 29, restored["version"]),
                auditor_headers,
            ),
            ApiErrorId.ERR_RESCORE_LIMIT_REACHED,
            expected_status=409,
        )

        final = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        assert final["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert final["rescore_count"] == 2
        assert final["version"] == restored["version"], \
            "the refused third rescore did not advance the version"

        scored_item = validate_success(api_client.get_scored_item(first["id"], ADMIN_HEADERS))
        assert scored_item["effective_points_awarded"] == 27
        assert scored_item["original_points_awarded"] == 27, \
            "the first judgement survives both corrections"
