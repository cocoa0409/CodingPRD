"""Declared state machines: legal transitions, refused ones, and terminal lockdown."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_EPOCH,
    CRITICAL_ACTION_DUE_AT,
    FIRST_VISIT_END,
    FIRST_VISIT_START,
    SCORE_SHEET_ONE_CRITICAL,
    STANDARD_ACTION_DUE_AT,
    ApiErrorId,
    add_rubric_items,
    advance_clock,
    api_client,
    assert_instant,
    attach_action_photo,
    audit_visit_payload,
    create_auditor,
    create_brand,
    create_franchisee,
    create_location,
    create_rubric_draft,
    dispute_payload,
    live_brand_version,
    make_auditor_headers,
    rescore_payload,
    schedule_visit,
    score_visit,
    scored_item_payload,
    setup_brand_program,
    setup_finalized_visit,
    setup_in_progress_visit,
    setup_scheduled_visit,
    setup_submitted_visit,
    setup_verified_corrective_action,
    start_visit,
    submit_visit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_payload,
    void_payload,
)

SECOND_WINDOW_START = "2026-08-19T09:00:00Z"
SECOND_WINDOW_END = "2026-08-19T13:00:00Z"


class TestVisitStart:
    def test_starting_a_scheduled_visit_stamps_the_logical_clock(self):
        """The start transition records the clock and computes nothing.

        PRD: "An auditor opens a visit by starting it, which advances
        `SCHEDULED → IN_PROGRESS` and stamps `started_at` with the logical clock."

        Design: Corner/state_machines/scheduled_visit_starts_and_stamps_started_at_from_the_logical_clock
        """
        program = setup_scheduled_visit()
        advance_clock("2026-08-05T08:30:00Z")

        started = validate_success(
            api_client.start_audit_visit(
                program["visit"]["id"], make_auditor_headers(program["auditor"]["id"]), {},
            )
        )
        assert started["status"] == "IN_PROGRESS"
        assert_instant(started["started_at"], "2026-08-05T08:30:00Z", "started_at")
        assert started["composite_score"] is None, "start computes no score"
        assert started["submitted_at"] is None

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(0.00, abs=0.01)
        assert location["latest_grade"] is None

    def test_the_start_window_opens_exactly_sixty_minutes_early(self):
        """One minute earlier is refused; the boundary minute itself is accepted.

        PRD: "The start window must be open — the logical clock must be at or after
        `scheduled_start_at` minus 60 minutes, so an auditor may open the visit up to an hour
        early but no earlier, and a premature attempt is rejected with
        `ERR_VISIT_WINDOW_NOT_OPEN`."

        Design: Corner/state_machines/visit_cannot_start_more_than_sixty_minutes_before_its_window
        """
        program = setup_scheduled_visit()
        visit_id = program["visit"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        advance_clock("2026-08-05T07:59:00Z")
        validate_error(
            api_client.start_audit_visit(visit_id, auditor_headers, {}),
            ApiErrorId.ERR_VISIT_WINDOW_NOT_OPEN,
            expected_status=409,
        )
        blocked = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        assert blocked["status"] == "SCHEDULED"
        assert blocked["started_at"] is None

        advance_clock("2026-08-05T08:00:00Z")
        started = validate_success(api_client.start_audit_visit(visit_id, auditor_headers, {}))
        assert started["status"] == "IN_PROGRESS"
        assert_instant(started["started_at"], "2026-08-05T08:00:00Z", "started_at")


class TestSubmission:
    def test_submit_computes_every_section_percent_and_the_provisional_composite(self):
        """Submission runs the whole scoring pipeline under the provisional weights.

        PRD: "Submission stamps `submitted_at` and runs the full scoring pipeline described
        below, computing the composite under the `PROVISIONAL` variant, setting
        `composite_variant` to `PROVISIONAL`, and deriving the `grade`. No health-department
        figure participates in a provisional composite."

        Design: Corner/state_machines/submit_computes_every_section_percent_penalty_and_provisional_composite
        """
        program = setup_in_progress_visit(sheet=SCORE_SHEET_ONE_CRITICAL)
        advance_clock("2026-08-05T12:30:00Z")

        submitted = validate_success(
            api_client.submit_audit_visit(
                program["visit"]["id"], make_auditor_headers(program["auditor"]["id"]), {},
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert_instant(submitted["submitted_at"], "2026-08-05T12:30:00Z", "submitted_at")
        assert submitted["food_safety_percent"] == pytest.approx(95.00, abs=0.01), \
            "27 of 30 rounds to 90.00 and 20 of 20 is 100.00, so the mean is 95.00"
        assert submitted["brand_standards_percent"] == pytest.approx(90.00, abs=0.01)
        assert submitted["facility_percent"] == pytest.approx(91.67, abs=0.01), \
            "10 of 12 rounds to 83.33 and 8 of 8 is 100.00"
        assert submitted["critical_violation_count"] == 1
        assert submitted["critical_penalty_points"] == pytest.approx(5.00, abs=0.01)
        assert submitted["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert submitted["composite_variant"] == "PROVISIONAL"
        assert submitted["grade"] == "PASS"
        assert submitted["health_component_percent"] is None
        assert submitted["finalized_at"] is None


class TestFinalization:
    def test_finalize_creates_one_corrective_action_per_violating_item(self):
        """Three violations produce three actions with severity-driven deadlines.

        PRD: "Finalization creates exactly one **CorrectiveAction** per violating scored item —
        that is, per scored item whose `is_violation` is true."

        Design: Corner/state_machines/finalize_creates_one_corrective_action_per_violating_item
        """
        program = setup_submitted_visit()
        advance_clock(FIRST_VISIT_END)

        finalized = validate_success(
            api_client.finalize_audit_visit(program["visit"]["id"], ADMIN_HEADERS, {})
        )
        assert finalized["status"] == "FINALIZED"
        assert_instant(finalized["finalized_at"], FIRST_VISIT_END, "finalized_at")
        assert finalized["health_component_percent"] is None
        assert finalized["linked_health_inspection_id"] is None
        assert finalized["composite_score"] == pytest.approx(90.70, abs=0.01), \
            "with no eligible inspection the final composite keeps the 0.60 / 0.40 weights"
        assert finalized["composite_variant"] == "FINAL"
        assert finalized["grade"] == "PASS"

        rows, meta = validate_paginated(
            api_client.list_corrective_actions(
                ADMIN_HEADERS,
                params={"location_id": program["location"]["id"], "limit": 100, "offset": 0},
            )
        )
        assert meta["total_count"] == 3, \
            "only FS-1, BS-1 and FC-1 lost points; the other three items produced none"
        assert len(rows) == 3

        actions = {}
        for code in ("FS-1", "BS-1", "FC-1"):
            found, _ = validate_paginated(
                api_client.list_corrective_actions(
                    ADMIN_HEADERS, params={"scored_item_id": program["scored"][code]["id"]}
                )
            )
            assert len(found) == 1, f"{code} raised exactly one corrective action"
            actions[code] = found[0]

        critical = actions["FS-1"]
        assert critical["severity"] == "CRITICAL"
        assert_instant(critical["due_at"], CRITICAL_ACTION_DUE_AT, "critical due_at")
        assert critical["status"] == "ASSIGNED"
        assert critical["evidence_photo_count"] == 0
        assert critical["location_id"] == program["location"]["id"]
        assert critical["assigned_franchisee_id"] == program["franchisee"]["id"]

        assert actions["BS-1"]["severity"] == "STANDARD"
        assert_instant(actions["BS-1"]["due_at"], STANDARD_ACTION_DUE_AT, "standard due_at")

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["open_corrective_action_count"] == 3
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01)
        assert location["latest_grade"] == "PASS"

        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["finalized_visit_count"] == 1


class TestIllegalOrdering:
    def test_visit_operations_out_of_order_are_rejected_as_invalid_state(self):
        """Each action endpoint reports the state error rather than a later check.

        PRD: "The target resource is in a state from which the requested transition is legal —
        `ERR_INVALID_VISIT_STATE`, `ERR_INVALID_CORRECTIVE_ACTION_STATE`,
        `ERR_INVALID_DISPUTE_STATE`, `ERR_INVALID_RUBRIC_STATE`, `ERR_INVALID_AUDITOR_STATE`,
        or `ERR_NO_ESCALATION_TO_CURE` as appropriate — on every action endpoint."

        Design: Corner/state_machines/visit_operations_out_of_order_are_rejected_as_invalid_state
        """
        program = setup_scheduled_visit()
        visit_id = program["visit"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        validate_error(
            api_client.submit_audit_visit(visit_id, auditor_headers, {}),
            ApiErrorId.ERR_INVALID_VISIT_STATE, expected_status=409,
        )
        validate_error(
            api_client.finalize_audit_visit(visit_id, ADMIN_HEADERS, {}),
            ApiErrorId.ERR_INVALID_VISIT_STATE, expected_status=409,
        )
        validate_error(
            api_client.create_scored_item(
                visit_id, scored_item_payload(program["item_ids"]["FS-1"], 27), auditor_headers,
            ),
            ApiErrorId.ERR_INVALID_VISIT_STATE, expected_status=409,
        )
        assert validate_success(
            api_client.get_audit_visit(visit_id, ADMIN_HEADERS)
        )["status"] == "SCHEDULED"

        advance_clock(FIRST_VISIT_START)
        validate_success(api_client.start_audit_visit(visit_id, auditor_headers, {}))
        scored = validate_success(
            api_client.create_scored_item(
                visit_id, scored_item_payload(program["item_ids"]["FS-1"], 27), auditor_headers,
            ),
            expected_status=201,
        )

        in_progress = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        validate_error(
            api_client.rescore_audit_visit(
                visit_id,
                rescore_payload(scored["id"], 29, in_progress["version"]),
                auditor_headers,
            ),
            ApiErrorId.ERR_INVALID_VISIT_STATE,
            expected_status=409,
        )
        validate_error(
            api_client.finalize_audit_visit(visit_id, ADMIN_HEADERS, {}),
            ApiErrorId.ERR_INVALID_VISIT_STATE, expected_status=409,
        )
        assert validate_success(
            api_client.get_audit_visit(visit_id, ADMIN_HEADERS)
        )["status"] == "IN_PROGRESS"

        _, meta = validate_paginated(
            api_client.list_scored_items(ADMIN_HEADERS, params={"visit_id": visit_id})
        )
        assert meta["total_count"] == 1, "the scoring attempt from SCHEDULED persisted nothing"

    def test_a_voided_visit_rejects_every_further_transition(self):
        """Void is terminal, and a second void neither overwrites nor re-stamps anything.

        PRD: "Voiding from `SCHEDULED` records the `void_reason` and does nothing else, because
        nothing was ever scored."

        Design: Corner/state_machines/voided_visit_rejects_every_further_transition
        """
        program = setup_scheduled_visit()
        visit_id = program["visit"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        voided = validate_success(
            api_client.void_audit_visit(
                visit_id, void_payload("SCHEDULING_ERROR"), ADMIN_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "SCHEDULING_ERROR"

        validate_error(
            api_client.start_audit_visit(visit_id, auditor_headers, {}),
            ApiErrorId.ERR_INVALID_VISIT_STATE, expected_status=409,
        )
        validate_error(
            api_client.submit_audit_visit(visit_id, auditor_headers, {}),
            ApiErrorId.ERR_INVALID_VISIT_STATE, expected_status=409,
        )
        validate_error(
            api_client.finalize_audit_visit(visit_id, ADMIN_HEADERS, {}),
            ApiErrorId.ERR_INVALID_VISIT_STATE, expected_status=409,
        )
        validate_error(
            api_client.void_audit_visit(visit_id, void_payload("RUBRIC_DEFECT"), ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_VISIT_STATE, expected_status=409,
        )

        reread = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        assert reread["status"] == "VOIDED"
        assert reread["void_reason"] == "SCHEDULING_ERROR", \
            "the refused second void did not overwrite the recorded reason"

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(0.00, abs=0.01)
        assert location["latest_grade"] is None
        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["finalized_visit_count"] == 0

    def test_repeating_publish_and_certify_is_a_state_error(self):
        """Neither repeat is a silent success, and neither re-stamps its instant.

        PRD: "Certifying an already-certified auditor or suspending an already-suspended one is
        rejected with `ERR_INVALID_AUDITOR_STATE`." PRD: "The target resource is in a state
        from which the requested transition is legal — `ERR_INVALID_VISIT_STATE`,
        `ERR_INVALID_CORRECTIVE_ACTION_STATE`, `ERR_INVALID_DISPUTE_STATE`,
        `ERR_INVALID_RUBRIC_STATE`, `ERR_INVALID_AUDITOR_STATE`, or `ERR_NO_ESCALATION_TO_CURE`
        as appropriate — on every action endpoint."

        Design: Corner/state_machines/repeating_publish_and_certify_is_a_state_error_not_a_silent_success
        """
        program = setup_brand_program(publish_rubric=False)
        rubric_id = program["rubric_version"]["id"]
        auditor_id = program["auditor"]["id"]

        published = validate_success(
            api_client.publish_rubric_version(rubric_id, ADMIN_HEADERS, {})
        )
        assert published["status"] == "PUBLISHED"
        assert_instant(published["published_at"], CLOCK_EPOCH, "published_at")

        advance_clock("2026-08-02T00:00:00Z")
        validate_error(
            api_client.publish_rubric_version(rubric_id, ADMIN_HEADERS, {}),
            ApiErrorId.ERR_INVALID_RUBRIC_STATE, expected_status=409,
        )
        validate_error(
            api_client.certify_auditor(auditor_id, ADMIN_HEADERS, {}),
            ApiErrorId.ERR_INVALID_AUDITOR_STATE, expected_status=409,
        )

        rubric = validate_success(api_client.get_rubric_version(rubric_id, ADMIN_HEADERS))
        assert rubric["status"] == "PUBLISHED"
        assert_instant(rubric["published_at"], CLOCK_EPOCH, "published_at after the refusal")

        auditor = validate_success(api_client.get_auditor(auditor_id, ADMIN_HEADERS))
        assert auditor["status"] == "CERTIFIED"
        assert_instant(
            auditor["certification_period_start"], CLOCK_EPOCH, "certification_period_start",
        )


class TestInitialStates:
    def test_every_machine_starts_in_its_declared_initial_state(self):
        """Auditor, rubric version, location, visit and scored item all start as declared.

        PRD: "New auditors enter with `status` `PROVISIONAL`, `reliability_score` 70.00,
        `certification_period_start` null, `suspension_reason` null, and
        `finalized_visit_count` 0."

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        advance_clock(CLOCK_EPOCH)
        brand = create_brand()
        franchisee = create_franchisee(brand["id"])
        location = create_location(brand["id"], franchisee["id"])

        auditor = create_auditor()
        assert auditor["status"] == "PROVISIONAL"
        assert auditor["reliability_score"] == pytest.approx(70.00, abs=0.01)
        assert auditor["certification_period_start"] is None
        assert auditor["suspension_reason"] is None
        assert auditor["finalized_visit_count"] == 0

        draft = create_rubric_draft(brand["id"])
        assert draft["status"] == "DRAFT"
        assert draft["published_at"] is None
        assert draft["item_count"] == 0
        assert draft["critical_item_count"] == 0

        fresh = validate_success(api_client.get_location(location["id"], ADMIN_HEADERS))
        assert fresh["franchise_agreement_status"] == "GOOD_STANDING"
        assert fresh["escalation_level"] == 0
        assert fresh["cure_period_started_at"] is None

        items = add_rubric_items(draft["id"])
        validate_success(api_client.publish_rubric_version(draft["id"], ADMIN_HEADERS, {}))
        validate_success(api_client.certify_auditor(auditor["id"], ADMIN_HEADERS, {}))

        visit = validate_success(
            api_client.create_audit_visit(
                audit_visit_payload(
                    location["id"], auditor["id"], draft["id"],
                    FIRST_VISIT_START, FIRST_VISIT_END,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert visit["status"] == "SCHEDULED"
        assert visit["critical_violation_count"] == 0
        assert visit["critical_penalty_points"] == pytest.approx(0.00, abs=0.01)
        assert visit["started_at"] is None
        assert visit["composite_score"] is None

        advance_clock(FIRST_VISIT_START)
        auditor_headers = make_auditor_headers(auditor["id"])
        validate_success(api_client.start_audit_visit(visit["id"], auditor_headers, {}))
        scored = validate_success(
            api_client.create_scored_item(
                visit["id"], scored_item_payload(items["FS-1"]["id"], 27), auditor_headers,
            ),
            expected_status=201,
        )
        assert scored["status"] == "SCORED"
        assert scored["severity"] == "CRITICAL"
        assert scored["original_points_awarded"] == 27
        assert scored["effective_points_awarded"] == 27
        assert scored["amended_points_awarded"] is None
        assert scored["is_violation"] is True


class TestRubricVersionLifecycle:
    def test_a_rubric_version_walks_draft_to_published_to_retired(self):
        """Publishing a successor retires its predecessor and closes it to new visits.

        PRD: "If the newly published version names a `supersedes_rubric_version_id` and that
        predecessor is currently `PUBLISHED`, the predecessor is driven `PUBLISHED → RETIRED`
        in the same operation."

        Design: Corner/state_machines/rubric_version_walks_draft_to_published_to_retired_and_never_back
        """
        program = setup_brand_program()
        brand_id = program["brand"]["id"]
        first_id = program["rubric_version"]["id"]
        first_published_at = program["rubric_version"]["published_at"]

        successor = create_rubric_draft(
            brand_id,
            expected_brand_version=live_brand_version(brand_id),
            version_label="RV-2026.2",
            supersedes_rubric_version_id=first_id,
        )
        add_rubric_items(successor["id"])
        published = validate_success(
            api_client.publish_rubric_version(successor["id"], ADMIN_HEADERS, {})
        )
        assert published["status"] == "PUBLISHED"

        predecessor = validate_success(api_client.get_rubric_version(first_id, ADMIN_HEADERS))
        assert predecessor["status"] == "RETIRED", \
            "the predecessor was retired without any call addressed to it"
        assert predecessor["published_at"] == first_published_at, \
            "retirement does not clear published_at"

        retired_visit = audit_visit_payload(
            program["location"]["id"], program["auditor"]["id"], first_id,
            FIRST_VISIT_START, FIRST_VISIT_END,
        )
        validate_error(
            api_client.create_audit_visit(retired_visit, ADMIN_HEADERS),
            ApiErrorId.ERR_RUBRIC_VERSION_NOT_PUBLISHED,
            expected_status=409,
        )

        created = validate_success(
            api_client.create_audit_visit(
                audit_visit_payload(
                    program["location"]["id"], program["auditor"]["id"], successor["id"],
                    FIRST_VISIT_START, FIRST_VISIT_END,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert created["rubric_version_id"] == successor["id"]

        _, meta = validate_paginated(
            api_client.list_rubric_versions(
                ADMIN_HEADERS, params={"brand_id": brand_id, "status": "RETIRED"}
            )
        )
        assert meta["total_count"] == 1


class TestSubmittedVisitFork:
    def test_a_submitted_visit_forks_to_finalized_or_voided(self):
        """The same score sheet leaves one visit rated and the other numerically blank.

        PRD: "Voiding from `SUBMITTED` additionally requires that no scored item be
        `UNDER_DISPUTE` (`ERR_UNRESOLVED_DISPUTE`) and clears `composite_score`,
        `composite_variant`, and `grade` back to null; no location field moves, because only
        provisional numbers had ever existed."

        Design: Corner/state_machines/submitted_visit_forks_to_finalized_or_voided_with_different_outcomes
        """
        program = setup_brand_program()
        first = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
        second = schedule_visit(program, SECOND_WINDOW_START, SECOND_WINDOW_END)

        start_visit(program, first["id"], at=FIRST_VISIT_START)
        score_visit(program, first["id"], SCORE_SHEET_ONE_CRITICAL)
        submit_visit(program, first["id"])

        start_visit(program, second["id"], at=SECOND_WINDOW_START)
        score_visit(program, second["id"], SCORE_SHEET_ONE_CRITICAL)
        second_submitted = submit_visit(program, second["id"])
        assert second_submitted["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert second_submitted["grade"] == "PASS"

        advance_clock(SECOND_WINDOW_END)
        finalized = validate_success(
            api_client.finalize_audit_visit(first["id"], ADMIN_HEADERS, {})
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert finalized["composite_variant"] == "FINAL"
        assert finalized["grade"] == "PASS"

        voided = validate_success(
            api_client.void_audit_visit(
                second["id"], void_payload("SCHEDULING_ERROR"), ADMIN_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "SCHEDULING_ERROR"
        assert voided["composite_score"] is None
        assert voided["composite_variant"] is None
        assert voided["grade"] is None

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01), \
            "only the finalized visit enters the standing window"
        assert location["latest_grade"] == "PASS"
        assert location["open_corrective_action_count"] == 3

        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["finalized_visit_count"] == 1


class TestSuspensionBlastRadius:
    def test_suspension_voids_in_progress_visits_but_only_blocks_scheduled_ones(self):
        """The in-flight visit is voided by cascade while the future booking survives.

        PRD: "Every `IN_PROGRESS` visit of the suspended auditor is driven
        `IN_PROGRESS → VOIDED` with `void_reason` `AUDITOR_SUSPENDED`; the auditor's
        `SCHEDULED` visits, by contrast, are left exactly where they are and are instead
        blocked at the moment someone tries to start them, with `ERR_AUDITOR_SUSPENDED`."

        Design: Corner/state_machines/suspending_an_auditor_voids_in_progress_visits_but_only_blocks_scheduled_ones
        """
        program = setup_brand_program()
        auditor_id = program["auditor"]["id"]
        first = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
        second = schedule_visit(program, SECOND_WINDOW_START, SECOND_WINDOW_END)

        advance_clock("2026-08-05T08:30:00Z")
        auditor_headers = make_auditor_headers(auditor_id)
        validate_success(api_client.start_audit_visit(first["id"], auditor_headers, {}))
        validate_success(
            api_client.create_scored_item(
                first["id"], scored_item_payload(program["item_ids"]["FS-1"], 27),
                auditor_headers,
            ),
            expected_status=201,
        )

        advance_clock("2026-08-05T10:00:00Z")
        suspended = validate_success(
            api_client.suspend_auditor(auditor_id, ADMIN_HEADERS, {"note": "Pulled for review"})
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL_REVIEW", \
            "the manual endpoint never records the reliability reason"

        in_flight = validate_success(api_client.get_audit_visit(first["id"], ADMIN_HEADERS))
        assert in_flight["status"] == "VOIDED"
        assert in_flight["void_reason"] == "AUDITOR_SUSPENDED"

        booked = validate_success(api_client.get_audit_visit(second["id"], ADMIN_HEADERS))
        assert booked["status"] == "SCHEDULED", "the scheduled visit was not touched"
        assert booked["void_reason"] is None

        advance_clock("2026-08-19T08:30:00Z")
        validate_error(
            api_client.start_audit_visit(second["id"], auditor_headers, {}),
            ApiErrorId.ERR_AUDITOR_SUSPENDED,
            expected_status=409,
        )
        assert validate_success(
            api_client.get_audit_visit(second["id"], ADMIN_HEADERS)
        )["status"] == "SCHEDULED"

        _, meta = validate_paginated(
            api_client.list_scored_items(ADMIN_HEADERS, params={"visit_id": first["id"]})
        )
        assert meta["total_count"] == 1, \
            "a void deletes no scored item, it only stops it counting"


class TestVerificationBubblesUp:
    def test_verifying_a_critical_action_bubbles_up_to_the_location_and_the_brand(self):
        """Acceptance lowers the open count and the brand index without touching standing.

        PRD: "When the `outcome` is `ACCEPTED`, the action advances `SUBMITTED → VERIFIED`,
        `verified_at` is stamped, the location's `open_corrective_action_count` drops by one,
        and the brand's `brand_risk_index` is recomputed."

        Design: Corner/state_machines/verifying_a_critical_action_bubbles_up_to_the_location_and_the_brand_index
        """
        program = setup_finalized_visit()
        brand_id = program["brand"]["id"]
        action_id = program["actions"]["FS-1"]["id"]

        before = validate_success(api_client.get_brand_risk_index(brand_id, ADMIN_HEADERS))
        assert before["brand_risk_index"] == pytest.approx(11.58, abs=0.01), \
            "0.60 of the 9.30 standing deficit plus 6.00 for one open critical action"
        assert before["open_critical_action_count"] == 1

        advance_clock("2026-08-05T14:00:00Z")
        attach_action_photo(program, action_id, captured_at="2026-08-05T13:45:00Z")
        submitted = validate_success(
            api_client.submit_corrective_action(
                action_id, program["franchisee_headers"],
                {"remediation_note": "Hood degreased and re-inspected"},
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_count"] == 1

        verified = validate_success(
            api_client.verify_corrective_action(
                action_id, verify_payload("ACCEPTED"), program["auditor_headers"],
            )
        )
        assert verified["status"] == "VERIFIED"
        assert_instant(verified["verified_at"], "2026-08-05T14:00:00Z", "verified_at")

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["open_corrective_action_count"] == 2, "down from three"
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01), \
            "verification touches the open count only, never the standing score"
        assert location["escalation_level"] == 0

        after = validate_success(api_client.get_brand_risk_index(brand_id, ADMIN_HEADERS))
        assert after["open_critical_action_count"] == 0
        assert after["average_standing_score"] == pytest.approx(90.70, abs=0.01)
        assert after["brand_risk_index"] == pytest.approx(5.58, abs=0.01)
        assert after["brand_risk_tier"] == "BASELINE"


class TestDisputeRoundTrip:
    def test_filing_and_withdrawing_a_dispute_flips_the_scored_item_across_entities(self):
        """The round trip moves the sibling entity and leaves every number where it was.

        PRD: "An accepted filing sets `filed_by_franchisee_id` from the acting franchisee,
        stamps `filed_at` with the logical clock, leaves `reviewer_auditor_id` null while the
        dispute is unclaimed, sets `info_request_count` to 0, leaves `resolution_points` and
        `resolved_at` null, and enters `status` `FILED`."

        Design: Corner/state_machines/filing_and_withdrawing_a_dispute_flips_the_scored_item_across_entities
        """
        program = setup_finalized_visit()
        scored_item_id = program["scored"]["FS-1"]["id"]
        visit_id = program["visit"]["id"]

        advance_clock("2026-08-06T09:00:00Z")
        dispute = validate_success(
            api_client.create_dispute(
                dispute_payload(scored_item_id, 30), program["franchisee_headers"],
            ),
            expected_status=201,
        )
        assert dispute["status"] == "FILED"
        assert_instant(dispute["filed_at"], "2026-08-06T09:00:00Z", "filed_at")
        assert dispute["filed_by_franchisee_id"] == program["franchisee"]["id"]
        assert dispute["reviewer_auditor_id"] is None
        assert dispute["info_request_count"] == 0
        assert dispute["resolution_points"] is None

        frozen = validate_success(api_client.get_scored_item(scored_item_id, ADMIN_HEADERS))
        assert frozen["status"] == "UNDER_DISPUTE"
        assert frozen["effective_points_awarded"] == 27
        assert frozen["severity"] == "CRITICAL"

        during = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        assert during["composite_score"] == pytest.approx(90.70, abs=0.01), \
            "filing runs no arithmetic"
        assert during["grade"] == "PASS"

        advance_clock("2026-08-06T15:00:00Z")
        withdrawn = validate_success(
            api_client.withdraw_dispute(
                dispute["id"], program["franchisee_headers"], {"note": "Log was illegible"},
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert_instant(withdrawn["resolved_at"], "2026-08-06T15:00:00Z", "resolved_at")

        restored = validate_success(api_client.get_scored_item(scored_item_id, ADMIN_HEADERS))
        assert restored["status"] == "SCORED"
        assert restored["amended_points_awarded"] is None
        assert restored["effective_points_awarded"] == 27

        after = validate_success(api_client.get_audit_visit(visit_id, ADMIN_HEADERS))
        assert after["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert after["grade"] == "PASS"

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01)
        assert location["open_corrective_action_count"] == 3, "the round trip is inert"


class TestSweepSeverityAsymmetry:
    def test_the_sweep_escalates_critical_actions_only(self):
        """Two standard actions land in OVERDUE and stop there.

        PRD: "It reports four figures: `swept_count` for the actions it examined and moved,
        `overdue_count` for those that landed in `OVERDUE`, `escalated_count` for those that
        continued on to `ESCALATED`, and `escalated_location_count` for the number of distinct
        locations affected by an escalation."

        Design: Corner/state_machines/overdue_sweep_escalates_critical_actions_only_and_leaves_standard_ones_overdue
        """
        program = setup_verified_corrective_action(item_code="FS-1")
        critical_id = program["action"]["id"]
        standard_id = program["actions"]["BS-1"]["id"]

        advance_clock("2026-08-20T00:00:00Z")
        sweep = validate_success(api_client.run_overdue_sweep(ADMIN_HEADERS, {}))
        assert sweep["swept_count"] == 2, "both standard actions moved past their due_at"
        assert sweep["overdue_count"] == 2
        assert sweep["escalated_count"] == 0, "the severity guard blocked the second stage"
        assert sweep["escalated_location_count"] == 0

        standard = validate_success(
            api_client.get_corrective_action(standard_id, ADMIN_HEADERS)
        )
        assert standard["status"] == "OVERDUE"
        assert standard["escalated_at"] is None

        critical = validate_success(
            api_client.get_corrective_action(critical_id, ADMIN_HEADERS)
        )
        assert critical["status"] == "VERIFIED", \
            "a terminal action is not re-swept even though its due_at is long past"

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["escalation_level"] == 0
        assert location["franchise_agreement_status"] == "GOOD_STANDING"
        assert location["cure_period_started_at"] is None
        assert location["open_corrective_action_count"] == 2, \
            "OVERDUE actions are still open, unlike escalated ones"

        _, ledger_meta = validate_paginated(
            api_client.list_location_escalation_events(
                program["location"]["id"], ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            )
        )
        assert ledger_meta["total_count"] == 0

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["brand_risk_index"] == pytest.approx(5.58, abs=0.01), \
            "the sweep changed no aggregate"
        assert risk["open_critical_action_count"] == 0
        assert risk["default_location_count"] == 0
