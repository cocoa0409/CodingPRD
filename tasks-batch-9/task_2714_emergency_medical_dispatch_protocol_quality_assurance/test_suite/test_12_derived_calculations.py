"""Derived arithmetic of the QA record: the deterministic systematic draw, the
protocol pin captured at selection, the accreditation report pool, and the two
composite-score views that a sheet produces at scoring and at finalization.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2
from test_helpers.test_users import ADMIN, OFFICER, REVIEWER, SUPERVISOR

CLOCK = "2026-08-20T00:00:00Z"

ALL_SECTIONS_23_OF_25 = {
    "case_entry": (23, 25),
    "key_questions": (23, 25),
    "pre_arrival": (23, 25),
    "final_coding": (23, 25),
}


def _four_chest_pain_calls(api, dispatcher_id):
    """Four INGESTED CHEST_PAIN calls, one day apart, in ascending received_at."""
    calls = []
    for index, day in enumerate(("05", "06", "07", "08"), start=1):
        calls.append(
            fx.ingest_call(
                api,
                dispatcher_id,
                call_reference=f"C-000{index}",
                call_type="CHEST_PAIN",
                received_at=f"2026-08-{day}T09:00:00Z",
                dispatched_determinant_code="10-C-4",
            )
        )
    return calls


def _call_status_by_id(api, dispatcher_id):
    rows, _meta = validate_paginated(
        api.list_call_records(dispatcher_id, ADMIN, {"limit": 100})
    )
    return {row["id"]: row["status"] for row in rows}


class TestSystematicDraw:
    def test_draw_takes_index_zero_then_one_stride_over_the_ordered_pool(self, api):
        """PRD §3.4: "The number of cases actually drawn is the smallest of three
        quantities: the `requested_count`, the quota still remaining (the period's
        `target_sample_count` less its current `selected_review_count`), and the size of
        the pool."
        PRD §3.4: "The stride is the pool size divided by `requested_count`, discarding
        any fractional part, with a minimum stride of 1."
        PRD §3.4: "Positions are then taken from the ordered pool at index zero, at one
        stride, at two strides, and so on for as long as the running index remains inside
        the pool, and the first however-many-are-needed of those positions are drawn."
        PRD §3.4: "Otherwise the pool is sorted by `received_at` ascending and, where two
        calls share an instant, by `call_reference` ascending in plain ASCII string order,
        which is unambiguous because call references are globally unique."

        Design: Corner/calculations/systematic_draw_selects_by_stride_over_the_ordered_pool
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        c1, c2, c3, c4 = _four_chest_pain_calls(api, env["dispatcher_id"])
        period = fx.new_period(
            api, env["program_id"], sampling_mode="RANDOM", target_sample_count=4
        )

        response = api.draw_random_sample(period["id"], {"requested_count": 2}, SUPERVISOR)
        rows = validate_success(response, 201)

        assert response.json()["response_type"] == "array", (
            "a draw that creates several reviews must be rendered as an array"
        )
        assert len(rows) == 2, f"stride 2 over a pool of 4 draws 2 reviews, got {len(rows)}"
        drawn = {row["call_record_id"] for row in rows}
        assert drawn == {c1["id"], c3["id"]}, (
            f"indices 0 and 2 of the ordered pool are C-0001 and C-0003, got {drawn}"
        )
        assert c2["id"] not in drawn and c4["id"] not in drawn

        statuses = _call_status_by_id(api, env["dispatcher_id"])
        assert statuses[c1["id"]] == "SELECTED"
        assert statuses[c3["id"]] == "SELECTED"
        assert statuses[c2["id"]] == "INGESTED"
        assert statuses[c4["id"]] == "INGESTED"

        reloaded = fx.get_period(api, env["program_id"], period["id"])
        assert reloaded["selected_review_count"] == 2
        assert reloaded["finalized_review_count"] == 0

    def test_drawn_reviews_carry_the_systematic_selection_stamp_and_the_protocol_pin(
        self, api
    ):
        """PRD §3.4: "Each drawn call yields one review with `selection_mode` of `RANDOM`
        and `selection_reason` stamped as `SYSTEMATIC_DRAW`; each drawn call moves
        `INGESTED → SELECTED`; and the period's `selected_review_count` grows by the number
        drawn."
        PRD §3.4: "The second is `high_risk`, which is true when any one of three
        conditions holds — the call's `call_type` is `CARDIAC_ARREST`, or the call's
        `cardiac_arrest_confirmed` flag is true, or the level letter of the call's
        `dispatched_determinant_code` is `E` — and false otherwise."
        PRD §3.4: "Each new review resolves `protocol_version_id` by searching the
        `MPDS_CARDSET` family of the period's programme for the single version whose
        `status` is `APPROVED`, `ACTIVE` or `SUPERSEDED` and whose governing interval
        contains the call's `received_at` — `effective_from` at or before the instant and
        `effective_to` either null or strictly after it."

        Design: Corner/calculations/systematic_draw_selects_by_stride_over_the_ordered_pool
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        _four_chest_pain_calls(api, env["dispatcher_id"])
        period = fx.new_period(
            api, env["program_id"], sampling_mode="RANDOM", target_sample_count=4
        )

        rows = validate_success(
            api.draw_random_sample(period["id"], {"requested_count": 2}, SUPERVISOR), 201
        )

        for row in rows:
            assert row["selection_mode"] == "RANDOM"
            assert row["selection_reason"] == "SYSTEMATIC_DRAW"
            assert row["status"] == "SELECTED"
            assert row["high_risk"] is False, (
                "a CHEST_PAIN call coded at level C is not a high-risk case"
            )
            assert row["protocol_version_id"] == env["version_id"]
            assert row["sampling_period_id"] == period["id"]
            assert row["dispatcher_id"] == env["dispatcher_id"]

    def test_a_repeated_draw_walks_the_remaining_pool_without_reselecting(self, api):
        """PRD §3.4: "The random draw is called "random" by the accreditation standard but is
        deliberately **deterministic and reproducible**, because the accrediting body may ask
        the centre to demonstrate the same sample twice."
        PRD §3.4: "No random number generator and no identifier ordering participate."
        PRD §3.4: "The candidate pool is assembled from call records whose handling
        dispatcher belongs to the period's programme, whose `call_type` equals the period's
        `call_type`, whose `status` is `INGESTED`, whose `received_at` falls inside the
        period's half-open window, and whose handling dispatcher's `dispatch_privilege` is
        anything other than `SUSPENDED` — a suspended dispatcher's calls are withheld from
        the systematic pool entirely."

        Design: Corner/calculations/systematic_draw_selects_by_stride_over_the_ordered_pool
        """
        env = fx.enrolled_dispatcher_env(api, clock=CLOCK)
        c1, c2, c3, c4 = _four_chest_pain_calls(api, env["dispatcher_id"])
        period = fx.new_period(
            api, env["program_id"], sampling_mode="RANDOM", target_sample_count=4
        )

        first = validate_success(
            api.draw_random_sample(period["id"], {"requested_count": 2}, SUPERVISOR), 201
        )
        second = validate_success(
            api.draw_random_sample(period["id"], {"requested_count": 2}, SUPERVISOR), 201
        )

        assert {row["call_record_id"] for row in first} == {c1["id"], c3["id"]}
        assert {row["call_record_id"] for row in second} == {c2["id"], c4["id"]}, (
            "the second draw sees a pool of two still-INGESTED calls and a stride of 1"
        )
        statuses = _call_status_by_id(api, env["dispatcher_id"])
        assert set(statuses.values()) == {"SELECTED"}
        reloaded = fx.get_period(api, env["program_id"], period["id"])
        assert reloaded["selected_review_count"] == 4


def _two_adjacent_versions_env(api):
    """Two touching MPDS_CARDSET windows, both APPROVED, and one enrolled dispatcher.

    MPDS-13.0 governs [2026-07-01, 2026-08-10) and MPDS-14.0 governs
    [2026-08-10, open ended), so a single instant is governed by exactly one of them.
    """
    program = fx.new_program(api, target_compliance_pct=90.0, watch_floor_pct=80.0)
    v13 = fx.new_version(
        api,
        program["id"],
        version_label="MPDS-13.0",
        effective_from="2026-07-01T00:00:00Z",
        effective_to="2026-08-10T00:00:00Z",
    )
    fx.approve_version(api, v13["id"])
    v14 = fx.new_version(
        api,
        program["id"],
        version_label="MPDS-14.0",
        effective_from="2026-08-10T00:00:00Z",
    )
    fx.approve_version(api, v14["id"])
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.certify(api, dispatcher["id"], v14["id"])
    rollout = fx.new_rollout(
        api,
        v14["id"],
        scheduled_golive_at="2026-08-15T00:00:00Z",
        target_dispatcher_count=1,
    )
    fx.set_clock(api, CLOCK)
    old_call = fx.ingest_call(
        api,
        dispatcher["id"],
        call_reference="C-0001",
        received_at="2026-08-05T09:00:00Z",
    )
    new_call = fx.ingest_call(
        api,
        dispatcher["id"],
        call_reference="C-0002",
        received_at="2026-08-12T09:00:00Z",
    )
    period = fx.new_period(api, program["id"], target_sample_count=2)
    return {
        "program_id": program["id"],
        "v13_id": v13["id"],
        "v14_id": v14["id"],
        "rollout_id": rollout["id"],
        "dispatcher_id": dispatcher["id"],
        "old_call_id": old_call["id"],
        "new_call_id": new_call["id"],
        "period_id": period["id"],
    }


class TestProtocolVersionPin:
    def test_each_review_pins_the_version_whose_window_contains_the_call_instant(
        self, api
    ):
        """PRD §3.4: "Each new review resolves `protocol_version_id` by searching the
        `MPDS_CARDSET` family of the period's programme for the single version whose
        `status` is `APPROVED`, `ACTIVE` or `SUPERSEDED` and whose governing interval
        contains the call's `received_at` — `effective_from` at or before the instant and
        `effective_to` either null or strictly after it."

        Design: Corner/calculations/the_pinned_protocol_version_is_frozen_at_selection_time
        """
        env = _two_adjacent_versions_env(api)

        old_review = validate_success(
            api.target_review(
                env["period_id"],
                f.target_review_payload(env["old_call_id"], selection_reason="COMPLAINT"),
                SUPERVISOR,
            ),
            201,
        )
        new_review = validate_success(
            api.target_review(
                env["period_id"],
                f.target_review_payload(env["new_call_id"], selection_reason="COMPLAINT"),
                SUPERVISOR,
            ),
            201,
        )

        assert old_review["protocol_version_id"] == env["v13_id"], (
            "a call received on 2026-08-05 sits inside the MPDS-13.0 window"
        )
        assert new_review["protocol_version_id"] == env["v14_id"], (
            "a call received on 2026-08-12 sits inside the MPDS-14.0 window, even though "
            "that version has not gone live yet"
        )

    def test_a_later_go_live_never_repoints_an_existing_pin(self, api):
        """PRD §3.4: "The four section weights this review will be graded on are read from
        the pinned row forever afterwards, and are **never** re-pointed to whatever version
        happens to be active when the review is eventually finalized."
        PRD §3.3: "The first link takes the rollout's own version `APPROVED → ACTIVE` and
        stamps its `activated_at`."

        Design: Corner/calculations/the_pinned_protocol_version_is_frozen_at_selection_time
        """
        env = _two_adjacent_versions_env(api)
        old_review = validate_success(
            api.target_review(
                env["period_id"],
                f.target_review_payload(env["old_call_id"], selection_reason="COMPLAINT"),
                SUPERVISOR,
            ),
            201,
        )

        validate_success(api.go_live(env["rollout_id"], {"golive_note": "v14 live"}, ADMIN))

        assert fx.get_version(api, env["v14_id"])["status"] == "ACTIVE"
        assert fx.get_version(api, env["v13_id"])["status"] == "APPROVED", (
            "MPDS-13.0 was never ACTIVE, so the go-live cascade has nothing to supersede"
        )
        assert fx.get_review(api, old_review["id"])["protocol_version_id"] == env["v13_id"]


def _two_finalized_reviews_env(api):
    """Two CHEST_PAIN cases, both scored 92.00 in every section and both finalized."""
    env = fx.enrolled_dispatcher_env(
        api,
        program_overrides={
            "target_compliance_pct": 90.0,
            "watch_floor_pct": 80.0,
            "high_risk_target_pct": 85.0,
        },
        clock=CLOCK,
    )
    c1 = fx.ingest_call(
        api, env["dispatcher_id"], call_reference="C-0001", received_at="2026-08-05T09:00:00Z"
    )
    c2 = fx.ingest_call(
        api, env["dispatcher_id"], call_reference="C-0002", received_at="2026-08-06T09:00:00Z"
    )
    period = fx.new_period(api, env["program_id"], target_sample_count=2)
    r1 = fx.target(api, period["id"], c1["id"], "COMPLAINT")
    r2 = fx.target(api, period["id"], c2["id"], "NEW_HIRE_AUDIT")
    fx.score(
        api,
        r1["id"],
        sections=ALL_SECTIONS_23_OF_25,
        expected_review_version=r1["version"],
    )
    fx.score(
        api,
        r2["id"],
        sections=ALL_SECTIONS_23_OF_25,
        expected_review_version=r2["version"],
    )
    fx.finalize(api, r1["id"], "clean case")
    fx.finalize(api, r2["id"], "clean case")
    env.update({"r1_id": r1["id"], "r2_id": r2["id"], "period_id": period["id"]})
    return env


class TestAccreditationReportPool:
    def test_a_voided_review_leaves_the_report_pool_and_lifts_the_compliant_rate(self, api):
        """PRD §3.9: "The report pool is every review in `FINALIZED` whose handling
        dispatcher belongs to the programme in question and whose `finalized_at` falls inside
        the half-open window."
        PRD §3.9: "Voided reviews are excluded even when they were finalized earlier inside
        that same window."
        PRD §3.9: "From a non-empty pool, `review_count` is the size of the pool,
        `compliant_review_count` is how many of those reviews have `compliant` true, and
        `dispatcher_count` is the number of distinct dispatchers contributing at least one
        review to it."
        PRD §3.9: "Under the case-weighted variant every reviewed case counts once: the
        figure is one hundred multiplied by `compliant_review_count`, divided by
        `review_count`, rounded half up to 1 decimal place — so a dispatcher whose calls were
        sampled heavily dominates the programme number."
        PRD §3.9: "A freshly built report has `status` `DRAFT`, no `submitted_to` and no
        `submitted_at`."
        PRD §3.7: "The review's `final_composite_score`, `pre_penalty_composite_score`,
        `penalty_points`, `determinant_accuracy` and `compliant` are all cleared to null, and
        both period counters are recomputed."

        Design: Corner/calculations/the_accreditation_report_counts_only_finalized_reviews_in_window
        """
        env = _two_finalized_reviews_env(api)
        fx.void(api, env["r2_id"], "WRONG_DISPATCHER")

        report = validate_success(
            api.create_accreditation_report(
                env["program_id"],
                f.accreditation_report_payload(variant="CASE_WEIGHTED"),
                OFFICER,
            ),
            201,
        )

        assert report["review_count"] == 1, (
            "the voided review must not survive in the pool"
        )
        assert report["compliant_review_count"] == 1
        assert report["dispatcher_count"] == 1
        assert report["compliance_pct"] == approx1(100.0)
        assert report["status"] == "DRAFT"
        assert report.get("submitted_to") is None

        surviving = fx.get_review(api, env["r1_id"])
        assert surviving["final_composite_score"] == approx1(92.0)
        assert surviving["compliant"] is True
        dropped = fx.get_review(api, env["r2_id"])
        assert dropped["status"] == "VOIDED"
        assert dropped.get("final_composite_score") is None

    def test_a_window_without_high_risk_cases_reports_a_null_high_risk_figure(self, api):
        """PRD §3.9: "`high_risk_review_count` is the number of pool reviews whose
        `high_risk` is true, and `high_risk_pass_count` is how many of those have a clinical
        record whose `dacpr_pass` is true."
        PRD §3.9: "`high_risk_compliance_pct` is one hundred multiplied by the pass count,
        divided by the high-risk count, rounded half up to 1 decimal place; when the
        high-risk count is 0 the field is null rather than 0.0, because a window containing
        no cardiac-arrest cases is not a window in which the centre failed them."
        PRD §3.9: "Finally `threshold_met` is true when `compliance_pct` is at or above the
        programme's `target_compliance_pct` **and** either `high_risk_compliance_pct` is null
        or it is at or above the programme's `high_risk_target_pct`."

        Design: Corner/calculations/the_accreditation_report_counts_only_finalized_reviews_in_window
        """
        env = _two_finalized_reviews_env(api)
        fx.void(api, env["r2_id"], "WRONG_DISPATCHER")

        report = validate_success(
            api.create_accreditation_report(
                env["program_id"],
                f.accreditation_report_payload(variant="CASE_WEIGHTED"),
                OFFICER,
            ),
            201,
        )

        assert report["high_risk_review_count"] == 0
        assert report["high_risk_pass_count"] == 0
        assert report.get("high_risk_compliance_pct") is None, (
            "no high-risk case in the window means null, not 0.0"
        )
        assert report["threshold_met"] is True, (
            "100.0 clears the 90.0 target and the null high-risk figure cannot block it"
        )


class TestInapplicableSection:
    def test_a_zero_possible_section_scores_one_hundred_on_the_unweighted_view(self, api):
        """PRD §3.5: "Each is the points earned divided by the points possible, multiplied by
        one hundred, rounded half up to 2 decimal places."
        PRD §3.5: "A section whose points possible is 0 yields exactly 100.00 rather than an
        undefined value, so an inapplicable section neither helps nor hurts the case under the
        unweighted view."
        PRD §3.5: "The sheet's `provisional_composite_score` is then the arithmetic mean of
        those four already-rounded percentages, rounded half up to 1 decimal place — under
        this view each of the four sections contributes exactly one quarter, regardless of the
        weights on the pinned protocol version, and no determinant penalty is applied."
        PRD §3.5: "If the reviewer's code string is identical to the dispatched code string,
        the accuracy is `ACCURATE`."
        PRD §3.5: "The same value is written onto the review's own
        `provisional_composite_score`, and the review's `scored_at` is stamped from the
        logical clock."

        Design: Corner/calculations/a_zero_possible_section_scores_as_one_hundred_percent
        """
        env = fx.selected_review_env(
            api,
            program_overrides={
                "target_compliance_pct": 90.0,
                "watch_floor_pct": 80.0,
                "hours_owed_restriction_threshold": 6.0,
            },
            clock=CLOCK,
        )

        sheet = validate_success(
            api.submit_scores(
                env["review_id"],
                f.section_score_payload(
                    env["review"]["version"],
                    {
                        "case_entry": (18, 20),
                        "key_questions": (26, 30),
                        "pre_arrival": (0, 0),
                        "final_coding": (5, 7),
                    },
                    "10-C-4",
                ),
                REVIEWER,
            ),
            201,
        )

        assert sheet["case_entry_pct"] == approx2(90.00)
        assert sheet["key_questions_pct"] == approx2(86.67), "26/30 is 86.666… half up to 86.67"
        assert sheet["pre_arrival_pct"] == approx2(100.00), (
            "a section with 0 points possible is exactly 100.00"
        )
        assert sheet["final_coding_pct"] == approx2(71.43), "5/7 is 71.428… half up to 71.43"
        assert sheet["provisional_composite_score"] == approx1(87.0), (
            "the mean of 90.00, 86.67, 100.00 and 71.43 is 87.025, half up to 87.0"
        )
        assert sheet["determinant_accuracy"] == "ACCURATE", "10-C-4 was coded 10-C-4"
        assert fx.get_review(api, env["review_id"])["provisional_composite_score"] == approx1(
            87.0
        )

    def test_the_inapplicable_section_still_carries_its_weight_at_finalization(self, api):
        """PRD §3.7: "The four already-rounded section percentages of the **current** sheet —
        the one whose `sheet_round` equals the review's `current_sheet_round`, superseded
        sheets being excluded entirely — are each multiplied by the corresponding weight on
        the review's pinned protocol version, the four products are summed, and the total is
        rounded half up to 1 decimal place to give `pre_penalty_composite_score`."
        PRD §3.7: "First a base penalty is read from the accuracy class: `ACCURATE` carries
        0.0, `MINOR_MISCODE` carries 2.0, `OVER_TRIAGE` carries 5.0, and `UNDER_TRIAGE`
        carries 10.0 — under-triage is punished five times as hard as an inconsequential
        miscode, because it is the error that sends a basic-life-support crew cold to a dying
        patient."
        PRD §3.7: "`compliant` is true when `final_composite_score` is at or above the
        programme's `target_compliance_pct` and false otherwise."

        Design: Corner/calculations/a_zero_possible_section_scores_as_one_hundred_percent
        """
        env = fx.selected_review_env(
            api,
            program_overrides={
                "target_compliance_pct": 90.0,
                "watch_floor_pct": 80.0,
                "hours_owed_restriction_threshold": 6.0,
            },
            clock=CLOCK,
        )
        fx.score(
            api,
            env["review_id"],
            sections={
                "case_entry": (18, 20),
                "key_questions": (26, 30),
                "pre_arrival": (0, 0),
                "final_coding": (5, 7),
            },
            reviewer_determinant_code="10-C-4",
            expected_review_version=env["review"]["version"],
        )

        finalized = validate_success(
            api.finalize_review(
                env["review_id"], {"finalization_note": "no pre-arrival applied"}, SUPERVISOR
            )
        )

        assert finalized["pre_penalty_composite_score"] == approx1(89.0), (
            "0.2*90.00 + 0.35*86.67 + 0.30*100.00 + 0.15*71.43 is 89.049, half up to 89.0"
        )
        assert finalized["determinant_accuracy"] == "ACCURATE"
        assert finalized["penalty_points"] == approx1(0.0)
        assert finalized["final_composite_score"] == approx1(89.0)
        assert finalized["compliant"] is False, "89.0 falls short of the 90.0 target"
        assert finalized["status"] == "FINALIZED"


MISCODED_SECTIONS = {
    "case_entry": (18, 20),
    "key_questions": (26, 30),
    "pre_arrival": (2, 3),
    "final_coding": (5, 7),
}


def _miscoded_scored_env(api):
    """One SCORED review: sections 90.00 / 86.67 / 66.67 / 71.43, coded 10-C-2 against 10-C-4."""
    env = fx.selected_review_env(
        api,
        program_overrides={
            "target_compliance_pct": 90.0,
            "watch_floor_pct": 80.0,
            "hours_owed_restriction_threshold": 6.0,
        },
        clock=CLOCK,
    )
    env["sheet"] = fx.score(
        api,
        env["review_id"],
        sections=MISCODED_SECTIONS,
        reviewer_determinant_code="10-C-2",
        expected_review_version=env["review"]["version"],
    )
    return env


class TestFinalizationEntersTheLedger:
    def test_the_ledger_is_untouched_while_the_review_is_only_scored(self, api):
        """PRD §3.5: "This provisional figure is what the reviewer sees and what the
        dispatcher sees during the rebuttal window; it is not the figure that enters any
        ledger."
        PRD §3.5: "The same value is written onto the review's own
        `provisional_composite_score`, and the review's `scored_at` is stamped from the
        logical clock."
        PRD §3.7: "The dispatcher's compliance figures are recomputed from scratch over every
        review of theirs in `FINALIZED` — reviews in `SELECTED`, `SCORED`, `DISPUTED` or
        `VOIDED` contribute nothing: `reviewed_case_count` is the number of such reviews,
        `compliance_points_total` is the sum of their `final_composite_score` values rounded
        half up to 1 decimal place, and `compliance_pct` is that total divided by the count,
        rounded half up to 1 decimal place."
        PRD §3.7: "When the count is zero, `compliance_pct` is null rather than 0.0."

        Design: Corner/calculations/finalization_replaces_the_provisional_score_in_the_dispatcher_ledger
        """
        env = _miscoded_scored_env(api)

        assert env["sheet"]["provisional_composite_score"] == approx1(78.7), (
            "the mean of 90.00, 86.67, 66.67 and 71.43 is 78.6925, half up to 78.7"
        )
        assert fx.get_review(api, env["review_id"])["provisional_composite_score"] == approx1(
            78.7
        )
        dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
        assert dispatcher["reviewed_case_count"] == 0
        assert dispatcher["compliance_points_total"] == approx1(0.0)
        assert dispatcher.get("compliance_pct") is None
        assert dispatcher["compliance_posture"] == "UNRATED"

    def test_the_final_weighted_score_and_not_the_provisional_one_enters_the_ledger(self, api):
        """PRD §3.7: "Otherwise, if neither deviation flag is set — the codes differ, but the
        response mode and the resource tier they commit the centre to are the same — the
        accuracy is `MINOR_MISCODE`, because the miscoding had no operational consequence."
        PRD §3.7: "Second, a tier multiplier is selected **from the pre-penalty score, never
        from the post-penalty result**: a pre-penalty score at or above 90.0 selects the high
        tier and multiplies the base by 1.5, a pre-penalty score at or above 75.0 but below
        90.0 selects the mid tier and multiplies by 1.0, and anything below 75.0 selects the
        low tier and multiplies by 0.5."
        PRD §3.7: "`final_composite_score` is the pre-penalty score less the penalty points,
        floored at 0.0 so it can never go negative, rounded half up to 1 decimal place."
        PRD §3.7: "The dispatcher's compliance figures are recomputed from scratch over every
        review of theirs in `FINALIZED` — reviews in `SELECTED`, `SCORED`, `DISPUTED` or
        `VOIDED` contribute nothing: `reviewed_case_count` is the number of such reviews,
        `compliance_points_total` is the sum of their `final_composite_score` values rounded
        half up to 1 decimal place, and `compliance_pct` is that total divided by the count,
        rounded half up to 1 decimal place."

        Design: Corner/calculations/finalization_replaces_the_provisional_score_in_the_dispatcher_ledger
        """
        env = _miscoded_scored_env(api)

        finalized = validate_success(
            api.finalize_review(
                env["review_id"], {"finalization_note": "miscode confirmed"}, SUPERVISOR
            )
        )

        assert finalized["pre_penalty_composite_score"] == approx1(79.1), (
            "0.2*90.00 + 0.35*86.67 + 0.30*66.67 + 0.15*71.43 is exactly 79.05, half up to 79.1"
        )
        assert finalized["determinant_accuracy"] == "MINOR_MISCODE"
        assert finalized["penalty_points"] == approx1(2.0), (
            "a base of 2.0 at the mid tier multiplier of 1.0 is 2.0"
        )
        assert finalized["final_composite_score"] == approx1(77.1)
        assert finalized["compliant"] is False

        dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
        assert dispatcher["reviewed_case_count"] == 1
        assert dispatcher["compliance_points_total"] == approx1(77.1), (
            "the ledger takes the final weighted score, not the provisional 78.7"
        )
        assert dispatcher["compliance_pct"] == approx1(77.1)

    def test_a_below_floor_ledger_yields_probation_and_a_standard_plan_on_the_weakest_section(
        self, api
    ):
        """PRD §3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is at
        or above the programme's `target_compliance_pct`, `WATCH` when it is below that but at
        or above `watch_floor_pct`, and `PROBATION` when it is below the watch floor; a
        dispatcher with no finalized reviews is `UNRATED`."
        PRD §3.8: "Otherwise, when the dispatcher's freshly recomputed `compliance_posture` is
        `PROBATION`, the plan is `STANDARD` and targets the weakest section."
        PRD §3.8: "The weakest section" means the lowest of the four section percentages on
        the review's current sheet, mapping `case_entry_pct` to `CASE_ENTRY`,
        `key_questions_pct` to `KEY_QUESTIONS`, `pre_arrival_pct` to
        `PRE_ARRIVAL_INSTRUCTIONS`, and `final_coding_pct` to `FINAL_CODING`."
        PRD §3.8: "Severity is not decorative: it fixes both `severity_rank` — 1 for
        `ADVISORY`, 2 for `STANDARD`, 3 for `CRITICAL` — and `required_hours`, which is 2.0
        hours for `ADVISORY`, 4.0 hours for `STANDARD`, and 8.0 hours for `CRITICAL`."

        Design: Corner/calculations/finalization_replaces_the_provisional_score_in_the_dispatcher_ledger
        """
        env = _miscoded_scored_env(api)

        fx.finalize(api, env["review_id"], "miscode confirmed")

        dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
        assert dispatcher["compliance_posture"] == "PROBATION", (
            "77.1 is below the 80.0 watch floor"
        )
        plans = fx.list_plans_for(api, env["dispatcher_id"])
        assert len(plans) == 1, f"exactly one automatic plan is expected, got {len(plans)}"
        plan = plans[0]
        assert plan["origin"] == "AUTO"
        assert plan["source_review_id"] == env["review_id"]
        assert plan["severity"] == "STANDARD"
        assert plan["severity_rank"] == 2
        assert plan["focus_area"] == "PRE_ARRIVAL_INSTRUCTIONS", (
            "pre_arrival_pct of 66.67 is the lowest of the four section percentages"
        )
        assert plan["required_hours"] == approx1(4.0)

    def test_owing_less_than_the_restriction_threshold_leaves_the_privilege_full(self, api):
        """PRD §3.8: "For each open plan the shortfall is the plan's `required_hours` less its
        `credited_hours`, floored at 0.00 so that over-delivery on one plan can never offset
        another plan's shortfall; `remediation_hours_owed` is the sum of those per-plan
        shortfalls, rounded half up to 2 decimal places."
        PRD §3.8: "Otherwise, when `remediation_hours_owed` is **strictly greater** than the
        programme's `hours_owed_restriction_threshold`, the privilege is `RESTRICTED` — owing
        exactly the threshold leaves a dispatcher at `FULL`."

        Design: Corner/calculations/finalization_replaces_the_provisional_score_in_the_dispatcher_ledger
        """
        env = _miscoded_scored_env(api)

        fx.finalize(api, env["review_id"], "miscode confirmed")

        dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
        assert dispatcher["remediation_hours_owed"] == approx2(4.00), (
            "one open STANDARD plan requiring 4.0 hours with nothing credited yet"
        )
        assert dispatcher["dispatch_privilege"] == "FULL", (
            "4.00 owed hours do not exceed the 6.0 restriction threshold"
        )
