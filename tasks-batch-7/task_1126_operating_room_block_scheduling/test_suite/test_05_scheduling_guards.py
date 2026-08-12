"""Scheduling guards: block state, payload shape, anesthesia span, error priority."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_case_posting,
    make_block,
    make_case,
    make_coverage,
    make_line,
    make_room,
    make_surgeon,
    make_surgeon_headers,
    schedule_case_in_block,
    setup_active_block_with_case,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
NURSE = TEST_USERS["nurse_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


class TestSchedulingPayloadAndState:
    def test_schedule_elective_without_block_rejected(self, api):
        """PRD §3.4: "A payload offering neither the block nor the full emergent
        triple is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/schedule_elective_without_block_returns_invalid_request
        """
        line = make_line()
        surgeon = make_surgeon(line["id"])
        case = make_case(surgeon["id"], procedure_class="STANDARD", priority="ELECTIVE")
        res = api.schedule_case(case["id"], {}, make_surgeon_headers(surgeon["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        assert res.status_code == 400

    def test_schedule_into_draft_block_rejected(self, api):
        """PRD §3.4: "The target block must be `ACTIVE`, else `ERR_BLOCK_NOT_ACTIVE`."

        Design: Corner/state_machines/schedule_into_draft_block_rejected
        """
        line = make_line()
        surgeon = make_surgeon(line["id"])
        room = make_room()
        make_coverage(room["id"], "2026-05-04", 420, 1200)
        block = make_block(line["id"], room["id"], date="2026-05-04")  # stays DRAFT
        case = make_case(surgeon["id"])

        res = api.schedule_case(
            case["id"], {"block_id": block["id"]}, make_surgeon_headers(surgeon["id"])
        )
        validate_error(res, ApiErrorId.ERR_BLOCK_NOT_ACTIVE)
        assert res.status_code == 409
        reread = validate_success(api.get_case(case["id"], ADMIN), 200)
        assert reread["status"] == "POSTED"


class TestAnesthesiaCoverageGuard:
    def test_no_coverage_then_partial_then_full_span(self, api):
        """PRD §3.4: "Anesthesia first: an `ACTIVE` coverage on the target room and
        date must fully span the case from its start through its end plus its
        turnover gap — coverage must contain the case including the turnover — else
        `ERR_NO_ANESTHESIA_COVERAGE`."
        PRD §3.4: "Only `ACTIVE` coverage counts toward scheduling safety."

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_active_full_span_anesthesia_coverage
        """
        line = make_line(name="CTS")
        surgeon = make_surgeon(line["id"], full_name="Dr. C")
        room = make_room()
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=420, end_minute=720, activate=True)
        case = make_case(surgeon["id"], procedure_class="STANDARD")

        # No coverage rows at all.
        res_none = api.schedule_case(
            case["id"], {"block_id": block["id"]}, make_surgeon_headers(surgeon["id"])
        )
        validate_error(res_none, ApiErrorId.ERR_NO_ANESTHESIA_COVERAGE)

        # Partial span [450,700) does not contain occupation [420, 510+25=535).
        partial = make_coverage(room["id"], "2026-05-04", 450, 700, provider_ref="AN-P")
        res_partial = api.schedule_case(
            case["id"], {"block_id": block["id"]}, make_surgeon_headers(surgeon["id"])
        )
        validate_error(res_partial, ApiErrorId.ERR_NO_ANESTHESIA_COVERAGE)

        # Withdrawn coverage never satisfies the guard; a full span does.
        withdrawn = validate_success(
            api.withdraw_anesthesia_coverage(partial["id"], COORDINATOR), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        make_coverage(room["id"], "2026-05-04", 420, 1200, provider_ref="AN-F")
        scheduled = validate_success(
            api.schedule_case(
                case["id"], {"block_id": block["id"]}, make_surgeon_headers(surgeon["id"])
            ),
            200,
        )
        assert_case_posting(scheduled)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["scheduled_start_minute"] == 420

    def test_coverage_must_include_turnover_gap(self, api):
        """PRD §3.4: "Anesthesia first: an `ACTIVE` coverage on the target room and
        date must fully span the case from its start through its end plus its
        turnover gap — coverage must contain the case including the turnover — else
        `ERR_NO_ANESTHESIA_COVERAGE`."

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_active_full_span_anesthesia_coverage
        """
        line = make_line(name="CTS")
        surgeon = make_surgeon(line["id"], full_name="Dr. C")
        room = make_room()
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=420, end_minute=720, activate=True)
        case = make_case(surgeon["id"], procedure_class="STANDARD")

        # Coverage ends exactly at the case end (510) — turnover tail uncovered.
        short = make_coverage(room["id"], "2026-05-04", 420, 510, provider_ref="AN-S")
        res_short = api.schedule_case(
            case["id"], {"block_id": block["id"]}, make_surgeon_headers(surgeon["id"])
        )
        validate_error(res_short, ApiErrorId.ERR_NO_ANESTHESIA_COVERAGE)

        validate_success(api.withdraw_anesthesia_coverage(short["id"], COORDINATOR), 200)
        # Coverage reaching exactly end+turnover (535) contains the occupation.
        make_coverage(room["id"], "2026-05-04", 420, 535, provider_ref="AN-E")
        scheduled = validate_success(
            api.schedule_case(
                case["id"], {"block_id": block["id"]}, make_surgeon_headers(surgeon["id"])
            ),
            200,
        )
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["scheduled_start_minute"] == 420


class TestValidationPriorityPairs:
    def test_state_error_beats_fit_error_on_schedule(self, api):
        """PRD §2.7: "When several checks could reject the same request, they are
        evaluated in the following fixed order, so an earlier failure masks every
        later check" — state preconditions (rule 7) precede fit and overlap
        (rule 10).
        PRD §3.4: "Scheduling is performed by the owning surgeon on a case in
        `POSTED` status — any other status is rejected with
        `ERR_CASE_NOT_SCHEDULABLE`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fit_error_on_schedule
        """
        line = make_line(name="OMFS")
        surgeon = make_surgeon(line["id"], full_name="Dr. O")
        room1 = make_room("OR1")
        room2 = make_room("OR2")
        make_coverage(room1["id"], "2026-05-04", 420, 1200)
        make_coverage(room2["id"], "2026-05-04", 420, 1200)
        block1 = make_block(line["id"], room1["id"], date="2026-05-04",
                            start_minute=420, end_minute=720, activate=True)
        # 80-minute block: cannot fit a 90-minute STANDARD case.
        block2 = make_block(line["id"], room2["id"], date="2026-05-04",
                            start_minute=420, end_minute=500, activate=True)
        case = make_case(surgeon["id"], procedure_class="STANDARD")
        case = schedule_case_in_block(case["id"], block1["id"], surgeon["id"])
        get_started = validate_success(
            api.start_case(case["id"], {"actual_start_minute": 420}, NURSE), 200
        )
        assert get_started["status"] == "IN_PROGRESS"

        res = api.schedule_case(
            case["id"], {"block_id": block2["id"]}, make_surgeon_headers(surgeon["id"])
        )
        validate_error(res, ApiErrorId.ERR_CASE_NOT_SCHEDULABLE)
        assert res.status_code == 409
        reread = validate_success(api.get_case(case["id"], ADMIN), 200)
        assert reread["status"] == "IN_PROGRESS"

    def test_state_and_fit_errors_each_fire_in_isolation(self, api):
        """PRD §3.4: "Scheduling is performed by the owning surgeon on a case in
        `POSTED` status — any other status is rejected with
        `ERR_CASE_NOT_SCHEDULABLE`."
        PRD §3.4: "If the end of the last packed case would exceed the block's
        `end_minute`, scheduling is rejected with `ERR_CASE_DOES_NOT_FIT`".

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fit_error_on_schedule
        """
        line = make_line(name="OMFS")
        surgeon = make_surgeon(line["id"], full_name="Dr. O")
        room1 = make_room("OR1")
        room2 = make_room("OR2")
        make_coverage(room1["id"], "2026-05-04", 420, 1200)
        make_coverage(room2["id"], "2026-05-04", 420, 1200)
        make_coverage(room2["id"], "2026-05-05", 420, 1200, provider_ref="AN-B")
        block1 = make_block(line["id"], room1["id"], date="2026-05-04",
                            start_minute=420, end_minute=720, activate=True)
        big_same_day = make_block(line["id"], room2["id"], date="2026-05-04",
                                  start_minute=600, end_minute=960, activate=True)
        tiny_next_day = make_block(line["id"], room2["id"], date="2026-05-05",
                                   start_minute=420, end_minute=500, activate=True)

        in_progress = make_case(surgeon["id"], procedure_class="STANDARD")
        in_progress = schedule_case_in_block(in_progress["id"], block1["id"], surgeon["id"])
        validate_success(
            api.start_case(in_progress["id"], {"actual_start_minute": 420}, NURSE), 200
        )

        # State alone fails: the target block is large enough and covered.
        res_state = api.schedule_case(
            in_progress["id"], {"block_id": big_same_day["id"]},
            make_surgeon_headers(surgeon["id"]),
        )
        validate_error(res_state, ApiErrorId.ERR_CASE_NOT_SCHEDULABLE)

        # Fit alone fails: a POSTED case on a different date (no padded overlap)
        # whose packed end 510 exceeds the 80-minute block's end 500.
        posted = make_case(surgeon["id"], procedure_class="STANDARD")
        res_fit = api.schedule_case(
            posted["id"], {"block_id": tiny_next_day["id"]},
            make_surgeon_headers(surgeon["id"]),
        )
        validate_error(res_fit, ApiErrorId.ERR_CASE_DOES_NOT_FIT)

    def test_anesthesia_error_beats_block_ownership_mismatch(self, api):
        """PRD §2.7: "When several checks could reject the same request, they are
        evaluated in the following fixed order, so an earlier failure masks every
        later check" — anesthesia safety (rule 9) precedes block-case alignment
        (rule 11).

        Design: Difficulty/priority_pair_validation_conflict/anesthesia_error_beats_block_ownership_mismatch
        """
        line_ct = make_line(name="CT")
        line_gs2 = make_line(name="GS2")
        surgeon_a = make_surgeon(line_ct["id"], full_name="Dr. A")
        surgeon_b = make_surgeon(line_gs2["id"], full_name="Dr. B")
        room = make_room()
        block_b = make_block(line_gs2["id"], room["id"], date="2026-05-04",
                             start_minute=420, end_minute=720,
                             surgeon_id=surgeon_b["id"], activate=True)
        case_x = make_case(surgeon_a["id"], procedure_class="STANDARD")

        res = api.schedule_case(
            case_x["id"], {"block_id": block_b["id"]},
            make_surgeon_headers(surgeon_a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NO_ANESTHESIA_COVERAGE)
        assert res.status_code == 409
        reread = validate_success(api.get_case(case_x["id"], ADMIN), 200)
        assert reread["status"] == "POSTED"

    def test_block_service_mismatch_fires_in_isolation(self, api):
        """PRD §3.4: "Finally alignment: into a surgeon-specific block, the case's
        surgeon must equal the block's `surgeon_id`; into a shared block, the case
        surgeon's `service_line_id` must equal the block's — otherwise
        `ERR_BLOCK_SERVICE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/anesthesia_error_beats_block_ownership_mismatch
        """
        line_ct = make_line(name="CT")
        line_gs2 = make_line(name="GS2")
        surgeon_a = make_surgeon(line_ct["id"], full_name="Dr. A")
        surgeon_b = make_surgeon(line_gs2["id"], full_name="Dr. B")
        room = make_room()
        make_coverage(room["id"], "2026-05-04", 420, 1200)
        block_b = make_block(line_gs2["id"], room["id"], date="2026-05-04",
                             start_minute=420, end_minute=720,
                             surgeon_id=surgeon_b["id"], activate=True)
        case_x = make_case(surgeon_a["id"], procedure_class="STANDARD")

        res = api.schedule_case(
            case_x["id"], {"block_id": block_b["id"]},
            make_surgeon_headers(surgeon_a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BLOCK_SERVICE_MISMATCH)
        assert res.status_code == 409
        assert validate_success(api.get_case(case_x["id"], ADMIN), 200)["status"] == "POSTED"


class TestCoverageLifecycle:
    def test_withdraw_coverage_twice_rejected(self, api):
        """PRD §3.4: "Coverage may later be withdrawn, moving it to `WITHDRAWN` —
        withdrawal requires the coverage to still be `ACTIVE`, else
        `ERR_COVERAGE_NOT_ACTIVE`."

        Design: Corner/state_machines/withdraw_coverage_twice_rejected
        """
        room = make_room()
        coverage = make_coverage(room["id"], "2026-05-04", 420, 1200)
        withdrawn = validate_success(
            api.withdraw_anesthesia_coverage(coverage["id"], COORDINATOR), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"

        res = api.withdraw_anesthesia_coverage(coverage["id"], COORDINATOR)
        validate_error(res, ApiErrorId.ERR_COVERAGE_NOT_ACTIVE)
        assert res.status_code == 409
