"""Day-of-surgery execution: start/complete guards, first-case punctuality."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    make_block,
    make_case,
    make_coverage,
    make_line,
    make_room,
    make_surgeon,
    schedule_case_in_block,
    setup_active_block_with_case,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestExecutionStateGuards:
    def test_start_posted_case_rejected(self, api):
        """PRD §3.6: "Recording a case start — supplying `actual_start_minute` —
        requires the case to be `SCHEDULED`, else `ERR_CASE_NOT_SCHEDULED`".

        Design: Corner/state_machines/start_posted_case_rejected
        """
        line = make_line()
        surgeon = make_surgeon(line["id"])
        case = make_case(surgeon["id"])
        res = api.start_case(case["id"], {"actual_start_minute": 420}, NURSE)
        validate_error(res, ApiErrorId.ERR_CASE_NOT_SCHEDULED)
        assert res.status_code == 409
        assert validate_success(api.get_case(case["id"], ADMIN), 200)["status"] == "POSTED"

    def test_complete_unstarted_case_rejected(self, api):
        """PRD §3.6: "Recording a completion — supplying `actual_end_minute` —
        requires the case to be `IN_PROGRESS`, else `ERR_CASE_NOT_IN_PROGRESS`".

        Design: Corner/state_machines/complete_unstarted_case_rejected
        """
        env = setup_active_block_with_case(block_start=420, block_end=720)
        case = env["case"]
        assert case["status"] == "SCHEDULED"
        res = api.complete_case(case["id"], {"actual_end_minute": 600}, NURSE)
        validate_error(res, ApiErrorId.ERR_CASE_NOT_IN_PROGRESS)
        assert res.status_code == 409
        assert validate_success(api.get_case(case["id"], ADMIN), 200)["status"] == "SCHEDULED"


class TestCompletionScorecard:
    def test_completed_case_increments_surgeon_counter(self, api):
        """PRD §3.6: "Completion moves the case to `COMPLETED`, adds 1 to the
        surgeon's `completed_cases_count`, and triggers the bias recomputation over
        the most-recent-twenty window described in §3.3."
        PRD §3.6: "If at that moment the case is the first of its room-day, the
        server also records `first_case_delay_minutes` as the minutes by which the
        actual start passed the scheduled start, floored at zero for an early or
        on-time start".

        Design: Corner/endpoints/completed_case_increments_surgeon_counter
        """
        env = setup_active_block_with_case(block_start=420, block_end=720)
        case = env["case"]
        surgeon_id = env["surgeon"]["id"]

        started = validate_success(
            api.start_case(case["id"], {"actual_start_minute": 420}, NURSE), 200
        )
        assert started["status"] == "IN_PROGRESS"
        completed = validate_success(
            api.complete_case(case["id"], {"actual_end_minute": 510}, NURSE), 200
        )
        assert completed["status"] == "COMPLETED"
        assert completed["first_case_delay_minutes"] == 0

        surgeon = validate_success(api.get_surgeon(surgeon_id, ADMIN), 200)
        assert surgeon["completed_cases_count"] == 1


class TestFirstCasePunctuality:
    def test_grace_boundary_ten_on_time_eleven_late(self, api):
        """PRD §3.6: "A started first case counts as on-time when its delay is at
        most ten minutes — exactly ten is on-time. The surgeon's `on_time_rate_pct`
        is recomputed at each such start as one hundred times the number of their
        started first-cases with delay of at most ten, divided by the number of
        their started first-cases overall, rounded half up to two decimals; a
        surgeon with no started first cases rates 0.00."

        Design: Corner/calculations/first_case_delay_grace_boundary_10_vs_11
        """
        line = make_line()
        surgeon_p = make_surgeon(line["id"], full_name="Dr. P")
        surgeon_q = make_surgeon(line["id"], full_name="Dr. Q")
        room1 = make_room("OR1")
        room2 = make_room("OR2")
        make_coverage(room1["id"], "2026-05-04", 420, 1200)
        make_coverage(room2["id"], "2026-05-04", 420, 1200)
        block1 = make_block(line["id"], room1["id"], date="2026-05-04",
                            start_minute=420, end_minute=720, activate=True)
        block2 = make_block(line["id"], room2["id"], date="2026-05-04",
                            start_minute=420, end_minute=720, activate=True)
        case_p = schedule_case_in_block(
            make_case(surgeon_p["id"])["id"], block1["id"], surgeon_p["id"]
        )
        case_q = schedule_case_in_block(
            make_case(surgeon_q["id"])["id"], block2["id"], surgeon_q["id"]
        )

        started_p = validate_success(
            api.start_case(case_p["id"], {"actual_start_minute": 430}, NURSE), 200
        )
        started_q = validate_success(
            api.start_case(case_q["id"], {"actual_start_minute": 431}, NURSE), 200
        )
        assert started_p["is_first_case_of_day"] is True
        assert started_p["first_case_delay_minutes"] == 10
        assert started_q["is_first_case_of_day"] is True
        assert started_q["first_case_delay_minutes"] == 11

        score_p = validate_success(api.get_surgeon(surgeon_p["id"], ADMIN), 200)
        score_q = validate_success(api.get_surgeon(surgeon_q["id"], ADMIN), 200)
        assert score_p["on_time_rate_pct"] == 100.00  # delay 10 <= grace 10
        assert score_q["on_time_rate_pct"] == 0.00    # delay 11 > grace 10
