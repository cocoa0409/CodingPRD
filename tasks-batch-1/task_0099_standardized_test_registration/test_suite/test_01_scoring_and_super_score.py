"""Scoring lifecycle: sitting composite, Super Score, score sends, and the
independent parallel axes of a registration (PRD §3.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiClient, ApiErrorId, TEST_USERS,
    make_candidate_headers,
    fixtures, factories,
)


def _two_released_sat_sittings(api):
    """Build one candidate with two RELEASED SAT sittings:
    sitting A {RW:700, MATH:680} composite 1380; sitting B {RW:660, MATH:740}
    composite 1400. Per-section best is RW 700 + MATH 740 = 1440.
    Returns (candidate, reg_a, reg_b)."""
    center = fixtures.create_center()
    candidate = fixtures.create_candidate(legal_first_name="Ada", legal_last_name="Lovelace")
    sess_a = fixtures.create_session(center["id"], test_date="2026-09-01",
                                     window_start_utc="2026-09-01T13:00:00.000Z",
                                     window_end_utc="2026-09-01T17:00:00.000Z")
    sess_b = fixtures.create_session(center["id"], test_date="2026-10-03",
                                     window_start_utc="2026-10-03T13:00:00.000Z",
                                     window_end_utc="2026-10-03T17:00:00.000Z")
    cid = candidate["id"]
    # Sitting A
    reg_a = fixtures.create_registration(sess_a["id"], cid, sess_a["version"])
    fixtures.confirm_registration(reg_a["id"], cid)
    fixtures.record_id_verification(reg_a["id"], "Ada", "Lovelace", "CA")
    fixtures.check_in(reg_a["id"])
    fixtures.record_score(reg_a["id"], "SAT", {"READING_WRITING": 700, "MATH": 680})
    fixtures.release_score(reg_a["id"])
    # Sitting B
    reg_b = fixtures.create_registration(sess_b["id"], cid, sess_b["version"])
    fixtures.confirm_registration(reg_b["id"], cid)
    fixtures.record_id_verification(reg_b["id"], "Ada", "Lovelace", "CA")
    fixtures.check_in(reg_b["id"])
    fixtures.record_score(reg_b["id"], "SAT", {"READING_WRITING": 660, "MATH": 740})
    return candidate, reg_a, reg_b


class TestSuperScore:
    def test_super_score_is_section_best_not_best_sitting(self, api):
        """PRD §3.8: "For each section in the exam's section set, the system takes
        the maximum value of that section across all qualifying sittings." PRD
        §3.8: "Because the best of each section may come from different sittings,
        the resulting super_composite can exceed any single sitting's composite."

        Design: Difficulty/dual_variant_calc/super_score_section_best_vs_best_sitting
        """
        candidate, reg_a, reg_b = _two_released_sat_sittings(api)
        # Release sitting B — qualifying set now both A and B.
        validate_success(api.release_score(reg_b["id"], TEST_USERS["score_ops_headers"]))

        data_b, _ = _list_score_reports(api, reg_b["id"])
        assert data_b[0]["sitting_composite"] == 1400, "sitting B composite is 1400"
        assert data_b[0]["super_composite"] == 1440, "super = best-RW 700 + best-MATH 740"

        data_a, _ = _list_score_reports(api, reg_a["id"])
        assert data_a[0]["super_composite"] == 1440, "super recomputed for sitting A too"
        # Section-best (1440) strictly exceeds the best single sitting composite (1400).
        assert data_b[0]["super_composite"] != data_b[0]["sitting_composite"]

    def test_super_score_takes_each_section_max_from_its_best_sitting(self, api):
        """PRD §3.8: "For each section in the exam's section set, the system takes
        the maximum value of that section across all qualifying sittings." PRD
        §3.8: "The qualifying set is exactly those score reports whose registration
        has score status RELEASED, the same candidate_id, and the same exam_type;
        sittings that are PENDING, SCORED, or CANCELLED_SCORE are excluded."

        Design: Difficulty/dual_variant_calc/super_score_section_best_vs_best_sitting
        """
        # Sitting A wins RW (700 > 660); sitting B wins MATH (740 > 680). The
        # super composite must pull RW from A and MATH from B = 700 + 740 = 1440,
        # exceeding either sitting's own composite (1380 and 1400).
        candidate, reg_a, reg_b = _two_released_sat_sittings(api)
        validate_success(api.release_score(reg_b["id"], TEST_USERS["score_ops_headers"]))
        data_a, _ = _list_score_reports(api, reg_a["id"])
        data_b, _ = _list_score_reports(api, reg_b["id"])
        assert data_a[0]["sitting_composite"] == 1380, "sitting A composite (700+680)"
        assert data_a[0]["super_composite"] == 1440
        assert data_a[0]["super_composite"] > data_a[0]["sitting_composite"]
        assert data_b[0]["super_composite"] > data_b[0]["sitting_composite"]

    def test_super_score_single_sitting_equals_its_composite(self, api):
        """PRD §3.8: "When exactly one sitting qualifies, the super composite
        equals that sitting's composite."

        Design: Corner/calculations/super_score_single_sitting_equals_its_composite
        """
        center, candidate, session, reg, sr = fixtures.create_released_registration(
            {"READING_WRITING": 640, "MATH": 640}, exam_type="SAT",
        )
        data, _ = _list_score_reports(api, reg["id"])
        assert data[0]["sitting_composite"] == 1280
        assert data[0]["super_composite"] == 1280


class TestScoreSend:
    def test_score_send_freezes_super_composite_when_flag_true(self, api):
        """PRD §3.8: "at the moment it is queued the composite to be transmitted
        is frozen onto the send as sent_composite: when use_super_score is true
        the frozen value is the candidate's super_composite, and when it is false
        it is that sitting's sitting_composite."

        Design: Corner/endpoints/score_send_freezes_super_composite_when_flag_true
        """
        candidate, reg_a, reg_b = _two_released_sat_sittings(api)
        validate_success(api.release_score(reg_b["id"], TEST_USERS["score_ops_headers"]))
        # super_composite is 1440; sitting B composite is 1400.
        resp = api.create_score_send(
            factories.create_score_send_payload(reg_b["id"], "0042", use_super_score=True),
            make_candidate_headers(candidate["id"]),
        )
        data = validate_success(resp, 201)
        assert data["sent_composite"] == 1440, "super, not sitting 1400"
        assert data["status"] == "QUEUED"

    def test_score_send_requires_released_registration(self, api):
        """PRD §3.8: "A send may only be queued when the named registration's
        score status is RELEASED."

        Design: Difficulty/cross_entity_state_dependency/score_send_requires_released_registration
        """
        # CHECKED_IN, SCORED but NOT RELEASED.
        center, candidate, session, reg, sr = fixtures.create_scored_registration(
            {"READING_WRITING": 600, "MATH": 600}, exam_type="SAT",
        )
        assert reg["score_status"] == "SCORED"
        resp = api.create_score_send(
            factories.create_score_send_payload(reg["id"], "0001", use_super_score=False),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_score_send_requires_released_registration_distinct(self, api):
        """PRD §3.8: "A send may only be queued when the named registration's
        score status is RELEASED."

        Design: Difficulty/cross_entity_state_dependency/score_send_requires_released_registration
        """
        # PENDING (never scored) registration: still not RELEASED.
        center, candidate, session, reg = fixtures.create_checked_in_registration()
        assert reg["score_status"] == "PENDING"
        resp = api.create_score_send(
            factories.create_score_send_payload(reg["id"], "0002", use_super_score=False),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestParallelAxes:
    def test_lifecycle_and_score_axes_advance_independently(self, api):
        """PRD §3.8: "The scoring lifecycle runs on a status axis, score_status,
        that is independent of the seat lifecycle axis, lifecycle_status."

        Design: Difficulty/non_linear_state_machine/registration_parallel_axes_lifecycle_and_score_independent
        """
        center, candidate, session, reg, sr = fixtures.create_scored_registration(
            {"READING_WRITING": 600, "MATH": 600}, exam_type="SAT",
        )
        # Advance axis 2 to RELEASED; axis 1 must stay CHECKED_IN.
        released = validate_success(api.release_score(reg["id"], TEST_USERS["score_ops_headers"]))
        assert released["lifecycle_status"] == "CHECKED_IN", "axis 1 unchanged by scoring"
        assert released["score_status"] == "RELEASED", "axis 2 advanced independently"

    def test_score_axis_reaches_released_with_checked_in_lifecycle(self, api):
        """PRD §3.8: "Releasing a scored sitting moves its score status from
        SCORED to RELEASED and makes the sitting eligible to contribute to the
        candidate's Super Score."

        Design: Difficulty/non_linear_state_machine/registration_parallel_axes_lifecycle_and_score_independent
        """
        center, candidate, session, reg, sr = fixtures.create_released_registration(
            {"READING_WRITING": 650, "MATH": 650}, exam_type="SAT",
        )
        assert reg["lifecycle_status"] == "CHECKED_IN"
        assert reg["score_status"] == "RELEASED"


class TestScoreReportPrecondition:
    def test_score_report_requires_checked_in(self, api):
        """PRD §3.8: "Recording is permitted only when the registration's score
        status is PENDING and, crucially, only when its lifecycle status is
        CHECKED_IN; this cross-axis dependency means a candidate must have
        actually sat the exam before a score can be recorded."

        Design: Corner/state_machines/score_report_requires_checked_in_invalid_state
        """
        # CONFIRMED but never CHECKED_IN.
        center, candidate, session, reg = fixtures.create_confirmed_registration()
        resp = api.create_score_report(
            reg["id"], factories.create_score_report_payload("SAT", {"READING_WRITING": 600, "MATH": 600}),
            TEST_USERS["score_ops_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def _list_score_reports(api: ApiClient, registration_id: str):
    from test_helpers import validate_paginated
    resp = api.list_score_reports(TEST_USERS["candidate_headers"], params={"registration_id": registration_id})
    return validate_paginated(resp)
