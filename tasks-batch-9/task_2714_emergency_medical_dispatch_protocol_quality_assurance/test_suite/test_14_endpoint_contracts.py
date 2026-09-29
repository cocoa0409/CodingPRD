"""Endpoint contracts of the QA record: the protocol-version CRUD surfaces, the
director's approval action, the bulk random draw, the associations a targeted
review materialises, the derived dispatcher rollup, and the void refused by an
accreditation lock.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    approx1,
    approx2,
    assert_common_fields,
    assert_instant_equals,
)
from test_helpers.test_users import (
    ADMIN,
    DIRECTOR,
    DIRECTOR_USER_ID,
    OFFICER,
    REVIEWER,
    SUPERVISOR,
)

CLOCK = "2026-08-20T00:00:00Z"


def _approx4(expected):
    """A weight the PRD expresses to 4 decimal places."""
    return pytest.approx(expected, abs=0.00001)


class TestProtocolVersionCrudSurfaces:
    def test_the_created_draft_version_reads_back_and_lists_identically(self, api):
        """PRD §3.2: "A newly registered version has `status` of `DRAFT`, no
        `approved_by_user_id`, no `activated_at`, and no `superseded_at`; no interval-collision
        check runs at registration."
        PRD §3.2: "A `ProgramAdmin` registers it under a programme with a `protocol_family` of
        either `MPDS_CARDSET` or `LOCAL_CARDSET`, a human `version_label` such as "v13.2" which
        must be unique within its programme and family, and the half-open interval during which
        it governs calls: `effective_from` is the inclusive lower bound and `effective_to` the
        exclusive upper bound, with `effective_to` omitted or null meaning the interval runs
        forward without end."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside
        the `meta` object of the envelope, where `total_count` is the number of rows matching the
        filters before the page window is applied and `has_more` indicates whether rows remain
        beyond it."

        Design: Corner/endpoints/protocol_version_create_read_and_list_round_trip
        """
        program = fx.new_program(api)

        created = validate_success(
            api.create_protocol_version(
                program["id"],
                f.protocol_version_payload(version_label="MPDS-13.0"),
                ADMIN,
            ),
            201,
        )
        assert_common_fields(created, expected_version=1)
        assert created["status"] == "DRAFT"
        assert created["program_id"] == program["id"]
        assert created.get("approved_by_user_id") is None
        assert created.get("activated_at") is None

        read = validate_success(api.get_protocol_version(created["id"], REVIEWER))
        assert read["id"] == created["id"]
        assert read["protocol_family"] == "MPDS_CARDSET"
        assert read["version_label"] == "MPDS-13.0"
        assert_instant_equals(read["effective_from"], "2026-07-01T00:00:00Z")
        assert read.get("effective_to") is None, (
            "an omitted effective_to must survive the round trip as null"
        )
        assert read["case_entry_weight"] == _approx4(0.2000)
        assert read["key_questions_weight"] == _approx4(0.3500)
        assert read["pre_arrival_weight"] == _approx4(0.3000)
        assert read["final_coding_weight"] == _approx4(0.1500)
        assert read["status"] == "DRAFT"

        rows, meta = validate_paginated(
            api.list_protocol_versions(
                program["id"],
                SUPERVISOR,
                {"status": "DRAFT", "protocol_family": "MPDS_CARDSET", "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [created["id"]]

    def test_the_status_filter_hides_a_draft_from_the_approved_listing(self, api):
        """PRD §3.9: "Beyond single-resource reads, the list surfaces accept filters that
        mirror the fields above, all of them optional and all combinable with `limit` and
        `offset`: a programme's protocol versions may be filtered by `status` and by
        `protocol_family`; a version's rollouts by `golive_status`; dispatchers by `program_id`,
        `certified_protocol_version_id`, `compliance_posture`, `dispatch_privilege`, and
        `certification_status`; a dispatcher's calls by `call_type` and `status`; a programme's
        sampling periods by `status` and `call_type`; reviews by `sampling_period_id`,
        `call_record_id`, `dispatcher_id`, `protocol_version_id`, `status`, and `high_risk`; a
        review's rebuttals and a review's clinical record by `status`; coaching plans by
        `dispatcher_id`, `source_review_id`, `status`, `severity`, and `origin`; a plan's
        sessions and a curriculum version's sessions by `status`; and a programme's accreditation
        reports by `status` and `variant`."

        Design: Corner/endpoints/protocol_version_create_read_and_list_round_trip
        """
        program = fx.new_program(api)
        fx.new_version(api, program["id"], version_label="MPDS-13.0")

        rows, meta = validate_paginated(
            api.list_protocol_versions(program["id"], SUPERVISOR, {"status": "APPROVED"})
        )

        assert meta["total_count"] == 0
        assert rows == []


class TestProtocolVersionApproval:
    def test_approval_stamps_the_director_and_increments_the_version(self, api):
        """PRD §3.2: "Approving a draft moves it `DRAFT → APPROVED`, stamps
        `approved_by_user_id` with the director's `X-User-ID`, and may carry an optional
        `approval_note`."
        PRD §2.4: "Most resources additionally carry `updated_at`, in the same format, refreshed
        on every mutation of the row, and `version`, an integer that starts at 1 on creation and
        is incremented by 1 on every mutation of that row — including mutations the server
        performs on its own initiative as part of a cascade, not only those a client requests
        directly on that resource."

        Design: Corner/endpoints/approve_stamps_the_director_and_moves_the_version_to_approved
        """
        program = fx.new_program(api)
        draft = fx.new_version(api, program["id"], version_label="MPDS-13.0")
        assert draft["version"] == 1

        approved = validate_success(
            api.approve_protocol_version(
                draft["id"], {"approval_note": "adopted by medical control"}, DIRECTOR
            )
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == DIRECTOR_USER_ID
        assert approved["version"] == 2
        assert approved.get("activated_at") is None, "approval does not activate the version"

    def test_a_second_approval_of_the_same_version_is_refused(self, api):
        """PRD §3.2: "Approval is refused unless the version is currently `DRAFT` — a second
        attempt on an already-approved, active or superseded version is rejected with
        `ERR_VERSION_NOT_APPROVABLE` — and unless the four weights still sum to exactly
        1.0000."

        Design: Corner/endpoints/approve_stamps_the_director_and_moves_the_version_to_approved
        """
        program = fx.new_program(api)
        draft = fx.new_version(api, program["id"], version_label="MPDS-13.0")
        approved = fx.approve_version(api, draft["id"], "adopted by medical control")

        response = api.approve_protocol_version(
            draft["id"], {"approval_note": "second attempt"}, DIRECTOR
        )

        validate_error(response, err.ERR_VERSION_NOT_APPROVABLE, 409)
        reloaded = fx.get_version(api, draft["id"])
        assert reloaded["status"] == "APPROVED"
        assert reloaded["approved_by_user_id"] == approved["approved_by_user_id"]
        assert reloaded["version"] == approved["version"]


def _four_call_random_period_env(api, target_sample_count):
    """Four INGESTED CHEST_PAIN calls one day apart under one OPEN RANDOM period."""
    env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
    calls = []
    for index, day in enumerate(("05", "06", "07", "08"), start=1):
        calls.append(
            fx.ingest_call(
                api,
                env["dispatcher_id"],
                call_reference=f"C-000{index}",
                received_at=f"2026-08-{day}T09:00:00Z",
            )
        )
    env["calls"] = calls
    env["period"] = fx.new_period(
        api,
        env["program_id"],
        sampling_mode="RANDOM",
        target_sample_count=target_sample_count,
    )
    env["period_id"] = env["period"]["id"]
    return env


class TestBulkRandomDraw:
    def test_the_draw_is_capped_by_the_remaining_quota_rather_than_refused(self, api):
        """PRD §3.4: "The number of cases actually drawn is the smallest of three quantities:
        the `requested_count`, the quota still remaining (the period's `target_sample_count` less
        its current `selected_review_count`), and the size of the pool."
        PRD §3.4: "The stride is the pool size divided by `requested_count`, discarding any
        fractional part, with a minimum stride of 1."
        PRD §3.4: "Each drawn call yields one review with `selection_mode` of `RANDOM` and
        `selection_reason` stamped as `SYSTEMATIC_DRAW`; each drawn call moves `INGESTED →
        SELECTED`; and the period's `selected_review_count` grows by the number drawn."

        Design: Corner/endpoints/the_random_draw_is_capped_by_the_remaining_quota
        """
        env = _four_call_random_period_env(api, target_sample_count=2)
        c1, c2, c3, c4 = env["calls"]

        rows = validate_success(
            api.draw_random_sample(env["period_id"], {"requested_count": 3}, SUPERVISOR), 201
        )

        assert len(rows) == 2, (
            "min(requested 3, remaining quota 2, pool 4) is 2, and the surplus is skipped "
            f"rather than rejected, got {len(rows)}"
        )
        assert {row["call_record_id"] for row in rows} == {c1["id"], c2["id"]}, (
            "a stride of floor(4/3) = 1 takes indices 0 and 1 of the ordered pool"
        )
        reloaded = fx.get_period(api, env["program_id"], env["period_id"])
        assert reloaded["selected_review_count"] == 2
        statuses = {
            row["id"]: row["status"]
            for row in validate_paginated(
                api.list_call_records(env["dispatcher_id"], ADMIN, {"limit": 100})
            )[0]
        }
        assert statuses[c3["id"]] == "INGESTED"
        assert statuses[c4["id"]] == "INGESTED"

    def test_a_draw_against_a_filled_quota_is_refused(self, api):
        """PRD §3.4: "Both routes also require that at least one sample slot remains: when
        `selected_review_count` has already reached `target_sample_count`, further selection is
        refused with `ERR_SAMPLE_QUOTA_FILLED`."

        Design: Corner/endpoints/the_random_draw_is_capped_by_the_remaining_quota
        """
        env = _four_call_random_period_env(api, target_sample_count=2)
        fx.draw_random(api, env["period_id"], 3)

        response = api.draw_random_sample(env["period_id"], {"requested_count": 1}, SUPERVISOR)

        validate_error(response, err.ERR_SAMPLE_QUOTA_FILLED, 422)
        rows, meta = validate_paginated(
            api.list_reviews(SUPERVISOR, {"sampling_period_id": env["period_id"], "limit": 100})
        )
        assert meta["total_count"] == 2, "no third review may exist"
        assert len(rows) == 2


class TestTargetedReviewAssociations:
    def test_targeting_an_unknown_call_record_is_reported_as_not_found(self, api):
        """PRD §2.5: "Identifiers supplied in a request body are resolved on the same principle
        and with the same codes — a `program_id`, `protocol_version_id`, `dispatcher_id`,
        `call_record_id` or `source_review_id` that names nothing yields the corresponding
        not-found code, with `ERR_CALL_RECORD_NOT_FOUND` covering an unknown call."

        Design: Corner/endpoints/a_review_links_the_period_call_dispatcher_and_pinned_version
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        fx.ingest_call(
            api, env["dispatcher_id"], call_reference="C-0001", received_at="2026-08-05T09:00:00Z"
        )
        period = fx.new_period(
            api, env["program_id"], sampling_mode="MIXED", target_sample_count=2
        )

        response = api.target_review(
            period["id"],
            f.target_review_payload(NON_EXISTENT_UUID, selection_reason="COMPLAINT"),
            REVIEWER,
        )

        validate_error(response, err.ERR_CALL_RECORD_NOT_FOUND, 404)
        assert fx.get_period(api, env["program_id"], period["id"])["selected_review_count"] == 0

    def test_a_targeted_review_carries_all_four_associations(self, api):
        """PRD §3.4: "A successful targeted selection creates one review with `selection_mode` of
        `TARGETED`, moves the call to `SELECTED`, and increments the period's
        `selected_review_count` by one."
        PRD §3.4: "The first is `dispatcher_id`, copied from the call record so that the review is
        permanently attributed to the dispatcher who handled the call even if the roster later
        changes."
        PRD §3.4: "Each new review resolves `protocol_version_id` by searching the `MPDS_CARDSET`
        family of the period's programme for the single version whose `status` is `APPROVED`,
        `ACTIVE` or `SUPERSEDED` and whose governing interval contains the call's `received_at` —
        `effective_from` at or before the instant and `effective_to` either null or strictly after
        it."

        Design: Corner/endpoints/a_review_links_the_period_call_dispatcher_and_pinned_version
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        call = fx.ingest_call(
            api, env["dispatcher_id"], call_reference="C-0001", received_at="2026-08-05T09:00:00Z"
        )
        period = fx.new_period(
            api, env["program_id"], sampling_mode="MIXED", target_sample_count=2
        )

        review = validate_success(
            api.target_review(
                period["id"],
                f.target_review_payload(call["id"], selection_reason="COMPLAINT"),
                REVIEWER,
            ),
            201,
        )

        assert review["sampling_period_id"] == period["id"]
        assert review["call_record_id"] == call["id"]
        assert review["dispatcher_id"] == env["dispatcher_id"]
        assert review["protocol_version_id"] == env["version_id"]
        assert review["selection_mode"] == "TARGETED"

        for filter_name, filter_value in (
            ("call_record_id", call["id"]),
            ("dispatcher_id", env["dispatcher_id"]),
            ("protocol_version_id", env["version_id"]),
        ):
            rows, meta = validate_paginated(
                api.list_reviews(SUPERVISOR, {filter_name: filter_value, "limit": 100})
            )
            assert meta["total_count"] == 1, f"the {filter_name} filter must find the review"
            assert rows[0]["id"] == review["id"]

        call_rows, _meta = validate_paginated(
            api.list_call_records(env["dispatcher_id"], ADMIN, {"limit": 100})
        )
        assert call_rows[0]["status"] == "SELECTED"


def _two_finalized_scores_env(api):
    """One dispatcher with two finalized reviews, one scoring 92.0 and one scoring 88.0."""
    env = fx.enrolled_dispatcher_env(
        api,
        program_overrides={
            "target_compliance_pct": 90.0,
            "watch_floor_pct": 80.0,
            "hours_owed_restriction_threshold": 6.0,
        },
        clock=CLOCK,
    )
    period = fx.new_period(api, env["program_id"], target_sample_count=2)
    reviews = []
    for index, (day, earned) in enumerate((("05", 23), ("06", 22)), start=1):
        call = fx.ingest_call(
            api,
            env["dispatcher_id"],
            call_reference=f"C-000{index}",
            received_at=f"2026-08-{day}T09:00:00Z",
        )
        review = fx.target(api, period["id"], call["id"], "COMPLAINT")
        fx.score(
            api,
            review["id"],
            sections={
                "case_entry": (earned, 25),
                "key_questions": (earned, 25),
                "pre_arrival": (earned, 25),
                "final_coding": (earned, 25),
            },
            expected_review_version=review["version"],
        )
        fx.finalize(api, review["id"], f"case {index}")
        reviews.append(review)
    env["period_id"] = period["id"]
    env["strong_review_id"] = reviews[0]["id"]
    env["weak_review_id"] = reviews[1]["id"]
    return env


class TestDispatcherRollupRead:
    def test_the_dispatcher_read_serves_the_recomputed_rollup(self, api):
        """PRD §3.7: "The dispatcher's compliance figures are recomputed from scratch over every
        review of theirs in `FINALIZED` — reviews in `SELECTED`, `SCORED`, `DISPUTED` or `VOIDED`
        contribute nothing: `reviewed_case_count` is the number of such reviews,
        `compliance_points_total` is the sum of their `final_composite_score` values rounded half
        up to 1 decimal place, and `compliance_pct` is that total divided by the count, rounded
        half up to 1 decimal place."
        PRD §3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is at or
        above the programme's `target_compliance_pct`, `WATCH` when it is below that but at or
        above `watch_floor_pct`, and `PROBATION` when it is below the watch floor; a dispatcher
        with no finalized reviews is `UNRATED`."
        PRD §3.7: "`compliant` is true when `final_composite_score` is at or above the programme's
        `target_compliance_pct` and false otherwise."

        Design: Corner/endpoints/the_dispatcher_read_exposes_the_derived_compliance_rollup
        """
        env = _two_finalized_scores_env(api)

        dispatcher = validate_success(api.get_dispatcher(env["dispatcher_id"], OFFICER))

        assert dispatcher["reviewed_case_count"] == 2
        assert dispatcher["compliance_points_total"] == approx1(180.0)
        assert dispatcher["compliance_pct"] == approx1(90.0)
        assert dispatcher["compliance_posture"] == "GOOD", (
            "landing exactly on the 90.0 target is GOOD, not WATCH"
        )

        strong = fx.get_review(api, env["strong_review_id"])
        assert strong["final_composite_score"] == approx1(92.0)
        assert strong["compliant"] is True
        weak = fx.get_review(api, env["weak_review_id"])
        assert weak["final_composite_score"] == approx1(88.0)
        assert weak["compliant"] is False

    def test_a_good_posture_leaves_the_hours_ledger_empty_and_creates_no_plan(self, api):
        """PRD §3.8: "And if none of those clauses match, no plan is created at all — a dispatcher
        whose posture came out `GOOD` on an accurately coded case is left alone."
        PRD §3.8: "For each open plan the shortfall is the plan's `required_hours` less its
        `credited_hours`, floored at 0.00 so that over-delivery on one plan can never offset
        another plan's shortfall; `remediation_hours_owed` is the sum of those per-plan shortfalls,
        rounded half up to 2 decimal places."
        PRD §3.8: "Otherwise, when `remediation_hours_owed` is **strictly greater** than the
        programme's `hours_owed_restriction_threshold`, the privilege is `RESTRICTED` — owing
        exactly the threshold leaves a dispatcher at `FULL`."

        Design: Corner/endpoints/the_dispatcher_read_exposes_the_derived_compliance_rollup
        """
        env = _two_finalized_scores_env(api)

        dispatcher = validate_success(api.get_dispatcher(env["dispatcher_id"], OFFICER))

        assert dispatcher["remediation_hours_owed"] == approx2(0.00)
        assert dispatcher["dispatch_privilege"] == "FULL"
        rows, meta = validate_paginated(
            api.list_coaching_plans(
                SUPERVISOR, {"dispatcher_id": env["dispatcher_id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0, (
            "a non-compliant case alone does not coach a dispatcher whose posture is GOOD"
        )
        assert rows == []


class TestVoidInsideALockedPeriod:
    def _closed_period_with_draft_report(self, api):
        """One FINALIZED review at 92.0, one SCORED sibling, the period CLOSED, report DRAFT."""
        env = fx.enrolled_dispatcher_env(
            api,
            program_overrides={"target_compliance_pct": 90.0, "watch_floor_pct": 80.0},
            clock=CLOCK,
        )
        period = fx.new_period(api, env["program_id"], target_sample_count=2)
        sections = {
            "case_entry": (23, 25),
            "key_questions": (23, 25),
            "pre_arrival": (23, 25),
            "final_coding": (23, 25),
        }
        reviews = []
        for index, day in enumerate(("05", "06"), start=1):
            call = fx.ingest_call(
                api,
                env["dispatcher_id"],
                call_reference=f"C-000{index}",
                received_at=f"2026-08-{day}T09:00:00Z",
            )
            review = fx.target(api, period["id"], call["id"], "COMPLAINT")
            fx.score(
                api, review["id"], sections=sections, expected_review_version=review["version"]
            )
            reviews.append(review)
        fx.finalize(api, reviews[0]["id"], "case 1 accepted")
        fx.close_period(api, period["id"], "quota met")
        report = fx.new_report(api, env["program_id"], variant="CASE_WEIGHTED")
        env.update(
            {
                "period_id": period["id"],
                "finalized_review_id": reviews[0]["id"],
                "scored_review_id": reviews[1]["id"],
                "report_id": report["id"],
            }
        )
        return env

    def test_filing_the_report_locks_the_closed_period_it_drew_on(self, api):
        """PRD §3.9: "Filing takes the report `DRAFT → SUBMITTED`, records the recipient and stamps
        `submitted_at` from the logical clock, and then Cascade C runs."
        PRD §3.9: "Every sampling period of the programme that is in `CLOSED` and whose half-open
        window overlaps the report's half-open window transitions `CLOSED → LOCKED`, stamping
        `locked_at` from the logical clock."

        Design: Corner/endpoints/voiding_a_review_in_a_locked_period_is_refused
        """
        env = self._closed_period_with_draft_report(api)

        submitted = validate_success(
            api.submit_accreditation_report(
                env["report_id"], {"submitted_to": "OVERSIGHT_COMMITTEE"}, OFFICER
            )
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_to"] == "OVERSIGHT_COMMITTEE"
        assert_instant_equals(submitted["submitted_at"], CLOCK)
        period = fx.get_period(api, env["program_id"], env["period_id"])
        assert period["status"] == "LOCKED"
        assert_instant_equals(period["locked_at"], CLOCK)

    def test_voiding_a_finalized_review_inside_a_locked_period_is_refused(self, api):
        """PRD §3.7: "A review may be voided from `SELECTED`, `SCORED`, `DISPUTED` or `FINALIZED`;
        a second attempt on an already-voided review is refused with `ERR_REVIEW_ALREADY_VOIDED`,
        and voiding a finalized review inside a `LOCKED` period is refused with
        `ERR_PERIOD_LOCKED`."
        PRD §3.9: "A review in `SCORED` or `DISPUTED`, by contrast, is real audit work product and
        is deliberately preserved rather than discarded — it is simply frozen, so any later attempt
        to submit a score against it or to finalize it fails with `ERR_PERIOD_LOCKED`."
        PRD §3.9: "Reviews already `FINALIZED` are of course untouched: they are the very rows the
        filed figure was computed from."

        Design: Corner/endpoints/voiding_a_review_in_a_locked_period_is_refused
        """
        env = self._closed_period_with_draft_report(api)
        fx.submit_report(api, env["report_id"], "OVERSIGHT_COMMITTEE")

        response = api.void_review(
            env["finalized_review_id"], {"void_reason": "DUPLICATE_CASE"}, SUPERVISOR
        )

        validate_error(response, err.ERR_PERIOD_LOCKED, 409)
        finalized = fx.get_review(api, env["finalized_review_id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["final_composite_score"] == approx1(92.0)
        dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
        assert dispatcher["reviewed_case_count"] == 1
        assert dispatcher["compliance_pct"] == approx1(92.0)
        assert fx.get_review(api, env["scored_review_id"])["status"] == "SCORED", (
            "the lock freezes a scored review instead of voiding it"
        )
