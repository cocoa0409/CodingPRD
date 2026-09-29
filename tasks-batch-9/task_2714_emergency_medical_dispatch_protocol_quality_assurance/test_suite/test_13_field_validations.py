"""Field- and rule-level validation of the QA record: weight normalization, the
logical-clock envelope on ingestion, programme scope on targeting, the rebuttal
deadline, the two quota gates on closing a period, and the rejection ordering
between call-type agreement and the temporal envelope.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, assert_instant_equals
from test_helpers.test_users import ADMIN, SUPERVISOR, make_dispatcher_headers

CLOCK = "2026-08-20T00:00:00Z"

MISCODED_SECTIONS = {
    "case_entry": (18, 20),
    "key_questions": (26, 30),
    "pre_arrival": (2, 3),
    "final_coding": (5, 7),
}
CLEAN_SECTIONS = {
    "case_entry": (23, 25),
    "key_questions": (23, 25),
    "pre_arrival": (23, 25),
    "final_coding": (23, 25),
}


class TestProtocolWeightNormalization:
    @pytest.mark.parametrize(
        "case_entry, key_questions, pre_arrival, final_coding, why",
        [
            (0.2500, 0.2500, 0.2500, 0.2000, "the four weights sum to 0.9500"),
            (0.2501, 0.2500, 0.2500, 0.2500, "the four weights sum to 1.0001"),
            (-0.1000, 0.4500, 0.5000, 0.1500, "the set sums to 1.0000 but holds a negative member"),
        ],
    )
    def test_a_weight_set_that_is_not_normalized_is_rejected(
        self, api, case_entry, key_questions, pre_arrival, final_coding, why
    ):
        """PRD §3.2: "The substance of a version is its four section weights —
        `case_entry_weight`, `key_questions_weight`, `pre_arrival_weight`, and
        `final_coding_weight` — each a non-negative value expressed to 4 decimal places, and
        the four together summing to exactly 1.0000 at that precision."
        PRD §3.2: "A set of weights that does not sum to exactly one, or that contains a
        negative member, is rejected with `ERR_WEIGHTS_NOT_NORMALIZED`."

        Design: Corner/validations/weights_that_do_not_sum_to_one_are_rejected
        """
        program = fx.new_program(api)

        response = api.create_protocol_version(
            program["id"],
            f.protocol_version_payload(
                version_label="MPDS-13.0",
                case_entry_weight=case_entry,
                key_questions_weight=key_questions,
                pre_arrival_weight=pre_arrival,
                final_coding_weight=final_coding,
            ),
            ADMIN,
        )

        validate_error(response, err.ERR_WEIGHTS_NOT_NORMALIZED, 422)
        rows, _meta = validate_paginated(
            api.list_protocol_versions(program["id"], ADMIN, {"limit": 100})
        )
        assert rows == [], f"no version may be persisted when {why}"

    def test_a_weight_set_that_sums_to_exactly_one_is_accepted(self, api):
        """PRD §3.2: "A set of weights that does not sum to exactly one, or that contains a
        negative member, is rejected with `ERR_WEIGHTS_NOT_NORMALIZED`."
        PRD §3.2: "A newly registered version has `status` of `DRAFT`, no
        `approved_by_user_id`, no `activated_at`, and no `superseded_at`; no interval-collision
        check runs at registration."

        Design: Corner/validations/weights_that_do_not_sum_to_one_are_rejected
        """
        program = fx.new_program(api)

        version = validate_success(
            api.create_protocol_version(
                program["id"],
                f.protocol_version_payload(
                    version_label="MPDS-13.0",
                    case_entry_weight=0.2500,
                    key_questions_weight=0.2500,
                    pre_arrival_weight=0.2500,
                    final_coding_weight=0.2500,
                ),
                ADMIN,
            ),
            201,
        )

        assert version["status"] == "DRAFT"
        assert version.get("approved_by_user_id") is None
        assert version.get("activated_at") is None
        assert version.get("superseded_at") is None


class TestCallReceivedAtEnvelope:
    def test_a_call_received_exactly_at_the_logical_clock_is_accepted(self, api):
        """PRD §3.1: "It carries `received_at`, the instant the call was answered, which may
        not be after the logical clock — a call from the future is rejected with
        `ERR_CALL_RECEIVED_IN_FUTURE`."

        Design: Corner/validations/a_call_received_exactly_at_the_logical_clock_is_accepted
        """
        program = fx.new_program(api)
        dispatcher = fx.new_dispatcher(api, program["id"])
        fx.set_clock(api, "2026-08-05T09:00:00Z")

        call = validate_success(
            api.create_call_record(
                dispatcher["id"],
                f.call_record_payload(
                    call_reference="C-EQ-1", received_at="2026-08-05T09:00:00Z"
                ),
                ADMIN,
            ),
            201,
        )

        assert call["status"] == "INGESTED"
        assert_instant_equals(call["received_at"], "2026-08-05T09:00:00Z")

    def test_a_call_received_one_second_after_the_clock_is_rejected(self, api):
        """PRD §3.1: "It carries `received_at`, the instant the call was answered, which may
        not be after the logical clock — a call from the future is rejected with
        `ERR_CALL_RECEIVED_IN_FUTURE`."

        Design: Corner/validations/a_call_received_exactly_at_the_logical_clock_is_accepted
        """
        program = fx.new_program(api)
        dispatcher = fx.new_dispatcher(api, program["id"])
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        accepted = fx.ingest_call(
            api, dispatcher["id"], call_reference="C-EQ-1", received_at="2026-08-05T09:00:00Z"
        )

        response = api.create_call_record(
            dispatcher["id"],
            f.call_record_payload(call_reference="C-EQ-2", received_at="2026-08-05T09:00:01Z"),
            ADMIN,
        )

        validate_error(response, err.ERR_CALL_RECEIVED_IN_FUTURE, 422)
        rows, _meta = validate_paginated(
            api.list_call_records(dispatcher["id"], ADMIN, {"limit": 100})
        )
        assert [row["id"] for row in rows] == [accepted["id"]], (
            "one second past the clock is already the future"
        )


class TestProgrammeScopeOnTargeting:
    def test_targeting_a_call_handled_in_another_programme_is_refused(self, api):
        """PRD §2.5: "This service is multi-programme, and cross-aggregate references must
        agree on programme scope: the protocol version a dispatcher is certified on must belong
        to that dispatcher's program, a call targeted into a sampling period must have been
        handled by a dispatcher of the period's program, and the curriculum version taught in a
        retraining session must belong to the coached dispatcher's program."
        PRD §2.5: "A reference that resolves but crosses a programme boundary is rejected with
        `ERR_PROGRAM_SCOPE_MISMATCH` (HTTP 409)."
        PRD §3.4: "A successful targeted selection creates one review with `selection_mode` of
        `TARGETED`, moves the call to `SELECTED`, and increments the period's
        `selected_review_count` by one."

        Design: Corner/validations/targeting_a_call_from_another_program_is_rejected
        """
        program_a = fx.new_program(api, name="Program A")
        program_b = fx.new_program(api, name="Program B", accreditation_body="NAED_LOCAL")
        fx.new_approved_version(api, program_a["id"], version_label="A-MPDS-13.0")
        fx.new_approved_version(api, program_b["id"], version_label="B-MPDS-13.0")
        dispatcher_b = fx.new_dispatcher(api, program_b["id"])
        fx.set_clock(api, CLOCK)
        call_b = fx.ingest_call(
            api,
            dispatcher_b["id"],
            call_reference="C-B-0001",
            call_type="CHEST_PAIN",
            received_at="2026-08-05T09:00:00Z",
        )
        period_a = fx.new_period(api, program_a["id"], target_sample_count=1)

        response = api.target_review(
            period_a["id"],
            f.target_review_payload(call_b["id"], selection_reason="COMPLAINT"),
            SUPERVISOR,
        )

        validate_error(response, err.ERR_PROGRAM_SCOPE_MISMATCH, 409)
        rows, meta = validate_paginated(
            api.list_reviews(SUPERVISOR, {"sampling_period_id": period_a["id"], "limit": 100})
        )
        assert rows == [] and meta["total_count"] == 0
        call_rows, _meta = validate_paginated(
            api.list_call_records(dispatcher_b["id"], ADMIN, {"limit": 100})
        )
        assert call_rows[0]["status"] == "INGESTED"
        assert fx.get_period(api, program_a["id"], period_a["id"])["selected_review_count"] == 0


class TestRebuttalWindow:
    def _scored_env(self, api):
        return fx.scored_review_env(
            api,
            sections=MISCODED_SECTIONS,
            reviewer_determinant_code="10-C-2",
            clock=CLOCK,
        )

    def test_a_rebuttal_filed_one_day_past_the_window_is_refused(self, api):
        """PRD §3.7: "And the dispute must arrive no later than the review's `scored_at` plus
        the programme's `rebuttal_window_days`, with the boundary instant itself still inside
        the window; a late dispute is refused with `ERR_REBUTTAL_WINDOW_CLOSED`."

        Design: Corner/validations/a_rebuttal_filed_after_the_window_closes_is_rejected
        """
        env = self._scored_env(api)
        before = fx.get_review(api, env["review_id"])
        fx.set_clock(api, "2026-09-04T00:00:00Z")

        response = api.create_rebuttal(
            env["review_id"],
            f.rebuttal_payload(
                grounds_category="PROTOCOL_AMBIGUITY",
                narrative="the card wording was ambiguous for this complaint",
            ),
            make_dispatcher_headers(env["dispatcher_id"]),
        )

        validate_error(response, err.ERR_REBUTTAL_WINDOW_CLOSED, 422)
        after = fx.get_review(api, env["review_id"])
        assert after["status"] == "SCORED"
        assert after["rebuttal_round_count"] == 0
        assert after["version"] == before["version"], "a refused filing changes nothing"
        assert fx.list_rebuttals_for(api, env["review_id"]) == []

    def test_a_rebuttal_filed_on_the_boundary_day_is_accepted(self, api):
        """PRD §3.7: "And the dispute must arrive no later than the review's `scored_at` plus
        the programme's `rebuttal_window_days`, with the boundary instant itself still inside
        the window; a late dispute is refused with `ERR_REBUTTAL_WINDOW_CLOSED`."
        PRD §3.7: "An accepted filing creates a rebuttal in `status` `SUBMITTED`, linked by
        `review_id`, with `round_index` one greater than the review's `rebuttal_round_count` at
        the time of filing and `submitted_by_user_id` recording the filing dispatcher — always
        the same identifier as the review's `dispatcher_id`."

        Design: Corner/validations/a_rebuttal_filed_after_the_window_closes_is_rejected
        """
        env = self._scored_env(api)
        fx.set_clock(api, "2026-09-03T00:00:00Z")

        rebuttal = validate_success(
            api.create_rebuttal(
                env["review_id"],
                f.rebuttal_payload(
                    grounds_category="PROTOCOL_AMBIGUITY",
                    narrative="the card wording was ambiguous for this complaint",
                ),
                make_dispatcher_headers(env["dispatcher_id"]),
            ),
            201,
        )

        assert rebuttal["status"] == "SUBMITTED", (
            "scored_at 2026-08-20 plus the default 14-day window still includes 2026-09-03"
        )
        assert rebuttal["round_index"] == 1
        after = fx.get_review(api, env["review_id"])
        assert after["status"] == "DISPUTED"
        assert after["rebuttal_round_count"] == 1


class TestClosingQuotaGate:
    def test_a_period_holding_fewer_selections_than_its_quota_cannot_close(self, api):
        """PRD §3.4: "Closing demands that the quota has been met: `selected_review_count` must
        be at or above `target_sample_count`, with exact equality passing, and a premature close
        is refused with `ERR_SAMPLE_QUOTA_NOT_MET`."

        Design: Corner/validations/closing_a_period_below_its_quota_is_rejected
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        call = fx.ingest_call(
            api, env["dispatcher_id"], call_reference="C-0001", received_at="2026-08-05T09:00:00Z"
        )
        period = fx.new_period(api, env["program_id"], target_sample_count=3)
        fx.target(api, period["id"], call["id"], "COMPLAINT")

        response = api.close_sampling_period(
            period["id"], {"closing_note": "premature close"}, SUPERVISOR
        )

        validate_error(response, err.ERR_SAMPLE_QUOTA_NOT_MET, 422)
        reloaded = fx.get_period(api, env["program_id"], period["id"])
        assert reloaded["status"] == "OPEN"
        assert reloaded.get("closed_at") is None
        assert reloaded["selected_review_count"] == 1

    def test_a_period_holding_exactly_its_quota_closes(self, api):
        """PRD §3.4: "Closing demands that the quota has been met: `selected_review_count` must
        be at or above `target_sample_count`, with exact equality passing, and a premature close
        is refused with `ERR_SAMPLE_QUOTA_NOT_MET`."
        PRD §3.4: "Closing a period is a `QaSupervisor` action carrying an optional
        `closing_note`, and it moves the period `OPEN → CLOSED` with `closed_at` stamped from
        the logical clock."

        Design: Corner/validations/closing_a_period_below_its_quota_is_rejected
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        period = fx.new_period(api, env["program_id"], target_sample_count=3)
        for index, day in enumerate(("05", "06", "07"), start=1):
            call = fx.ingest_call(
                api,
                env["dispatcher_id"],
                call_reference=f"C-000{index}",
                received_at=f"2026-08-{day}T09:00:00Z",
            )
            fx.target(api, period["id"], call["id"], "COMPLAINT")

        closed = validate_success(
            api.close_sampling_period(period["id"], {"closing_note": "quota met"}, SUPERVISOR)
        )

        assert closed["status"] == "CLOSED"
        assert_instant_equals(closed["closed_at"], CLOCK)
        assert closed["selected_review_count"] == 3


class TestEscalatedSamplingFloor:
    def _program_env(self, api):
        return fx.enrolled_dispatcher_env(
            api,
            program_overrides={
                "target_compliance_pct": 90.0,
                "watch_floor_pct": 80.0,
                "escalated_sample_floor": 4,
            },
            clock=CLOCK,
        )

    def test_a_probation_dispatchers_thinly_sampled_period_cannot_close(self, api):
        """PRD §3.4: "There is a second, sharper gate for centres with a struggling dispatcher:
        if any dispatcher whose cases the period selected currently sits in
        `compliance_posture` `PROBATION`, then the period's `target_sample_count` must be at or
        above the programme's `escalated_sample_floor` before the period may be closed, and a
        period sampled too thinly for a dispatcher in that condition is refused with
        `ERR_ESCALATED_SAMPLING_REQUIRED`."
        PRD §3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is at or
        above the programme's `target_compliance_pct`, `WATCH` when it is below that but at or
        above `watch_floor_pct`, and `PROBATION` when it is below the watch floor; a dispatcher
        with no finalized reviews is `UNRATED`."

        Design: Corner/validations/the_escalated_sample_floor_applies_only_to_probation_dispatchers
        """
        env = self._program_env(api)
        first_call = fx.ingest_call(
            api, env["dispatcher_id"], call_reference="C-0001", received_at="2026-08-05T09:00:00Z"
        )
        second_call = fx.ingest_call(
            api, env["dispatcher_id"], call_reference="C-0002", received_at="2026-08-06T09:00:00Z"
        )
        first_period = fx.new_period(api, env["program_id"], target_sample_count=1)
        first_review = fx.target(api, first_period["id"], first_call["id"], "COMPLAINT")
        fx.score(
            api,
            first_review["id"],
            sections=MISCODED_SECTIONS,
            reviewer_determinant_code="10-C-2",
            expected_review_version=first_review["version"],
        )
        fx.finalize(api, first_review["id"], "probation driver")
        second_period = fx.new_period(api, env["program_id"], target_sample_count=1)
        fx.target(api, second_period["id"], second_call["id"], "COMPLAINT")

        dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
        assert dispatcher["compliance_pct"] == approx1(77.1)
        assert dispatcher["compliance_posture"] == "PROBATION"

        response = api.close_sampling_period(
            second_period["id"], {"closing_note": "quota of 1 is met"}, SUPERVISOR
        )

        validate_error(response, err.ERR_ESCALATED_SAMPLING_REQUIRED, 422)
        reloaded = fx.get_period(api, env["program_id"], second_period["id"])
        assert reloaded["status"] == "OPEN", (
            "the quota of 1 is met, so only the posture-conditional gate can be refusing"
        )
        assert reloaded.get("closed_at") is None

    def test_the_same_thinly_sampled_period_closes_for_a_good_dispatcher(self, api):
        """PRD §3.4: "There is a second, sharper gate for centres with a struggling dispatcher:
        if any dispatcher whose cases the period selected currently sits in
        `compliance_posture` `PROBATION`, then the period's `target_sample_count` must be at or
        above the programme's `escalated_sample_floor` before the period may be closed, and a
        period sampled too thinly for a dispatcher in that condition is refused with
        `ERR_ESCALATED_SAMPLING_REQUIRED`."
        PRD §3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is at or
        above the programme's `target_compliance_pct`, `WATCH` when it is below that but at or
        above `watch_floor_pct`, and `PROBATION` when it is below the watch floor; a dispatcher
        with no finalized reviews is `UNRATED`."

        Design: Corner/validations/the_escalated_sample_floor_applies_only_to_probation_dispatchers
        """
        env = self._program_env(api)
        first_call = fx.ingest_call(
            api, env["dispatcher_id"], call_reference="C-0001", received_at="2026-08-05T09:00:00Z"
        )
        second_call = fx.ingest_call(
            api, env["dispatcher_id"], call_reference="C-0002", received_at="2026-08-06T09:00:00Z"
        )
        first_period = fx.new_period(api, env["program_id"], target_sample_count=1)
        first_review = fx.target(api, first_period["id"], first_call["id"], "COMPLAINT")
        fx.score(
            api,
            first_review["id"],
            sections=CLEAN_SECTIONS,
            expected_review_version=first_review["version"],
        )
        fx.finalize(api, first_review["id"], "clean case")
        second_period = fx.new_period(api, env["program_id"], target_sample_count=1)
        fx.target(api, second_period["id"], second_call["id"], "COMPLAINT")

        dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
        assert dispatcher["compliance_pct"] == approx1(92.0)
        assert dispatcher["compliance_posture"] == "GOOD"

        closed = validate_success(
            api.close_sampling_period(
                second_period["id"], {"closing_note": "quota of 1 is met"}, SUPERVISOR
            )
        )

        assert closed["status"] == "CLOSED", (
            "the escalated floor of 4 binds only when a selected dispatcher is on PROBATION"
        )


class TestRejectionOrderingOnTargeting:
    def test_the_call_type_disagreement_is_reported_before_the_window_violation(self, api):
        """PRD §2.9: "When a request violates more than one rule, exactly one error is returned,
        and which one is fully determined by the ladder below. Checks are evaluated in this order
        and the first violated rule wins:"
        PRD §2.9: "13. **Programme scope agreement**, then **call-type agreement** —
        `ERR_PROGRAM_SCOPE_MISMATCH`, then `ERR_CALL_TYPE_MISMATCH`."
        PRD §2.9: "18. **Temporal envelopes** — `ERR_CALL_RECEIVED_IN_FUTURE`,
        `ERR_CALL_OUTSIDE_PERIOD`, `ERR_REBUTTAL_WINDOW_CLOSED`, `ERR_REVIEW_DEADLINE_PASSED`,
        `ERR_INVALID_TIME_WINDOW`, `ERR_REPORT_WINDOW_INVALID`."
        PRD §3.4: "The call's `call_type` must equal the period's `call_type`, or it fails with
        `ERR_CALL_TYPE_MISMATCH`."

        Design: Corner/validations/the_call_type_mismatch_is_reported_before_the_period_window
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        doubly_invalid = fx.ingest_call(
            api,
            env["dispatcher_id"],
            call_reference="C-0007",
            call_type="TRAUMA",
            received_at="2026-07-15T09:00:00Z",
            dispatched_determinant_code="30-B-1",
        )
        period = fx.new_period(api, env["program_id"], call_type="CHEST_PAIN", target_sample_count=1)

        response = api.target_review(
            period["id"],
            f.target_review_payload(doubly_invalid["id"], selection_reason="SENTINEL_FLAG"),
            SUPERVISOR,
        )

        validate_error(response, err.ERR_CALL_TYPE_MISMATCH, 409)
        rows, _meta = validate_paginated(
            api.list_call_records(env["dispatcher_id"], ADMIN, {"limit": 100})
        )
        assert rows[0]["status"] == "INGESTED"

    def test_the_window_check_is_reached_once_the_call_type_agrees(self, api):
        """PRD §3.4: "The call's `received_at` must fall inside the period's half-open window, or
        it fails with `ERR_CALL_OUTSIDE_PERIOD`."
        PRD §2.9: "18. **Temporal envelopes** — `ERR_CALL_RECEIVED_IN_FUTURE`,
        `ERR_CALL_OUTSIDE_PERIOD`, `ERR_REBUTTAL_WINDOW_CLOSED`, `ERR_REVIEW_DEADLINE_PASSED`,
        `ERR_INVALID_TIME_WINDOW`, `ERR_REPORT_WINDOW_INVALID`."

        Design: Corner/validations/the_call_type_mismatch_is_reported_before_the_period_window
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        outside_window = fx.ingest_call(
            api,
            env["dispatcher_id"],
            call_reference="C-0008",
            call_type="CHEST_PAIN",
            received_at="2026-07-15T09:00:00Z",
        )
        period = fx.new_period(api, env["program_id"], call_type="CHEST_PAIN", target_sample_count=1)

        response = api.target_review(
            period["id"],
            f.target_review_payload(outside_window["id"], selection_reason="SENTINEL_FLAG"),
            SUPERVISOR,
        )

        validate_error(response, err.ERR_CALL_OUTSIDE_PERIOD, 422)
        assert fx.get_period(api, env["program_id"], period["id"])["selected_review_count"] == 0
