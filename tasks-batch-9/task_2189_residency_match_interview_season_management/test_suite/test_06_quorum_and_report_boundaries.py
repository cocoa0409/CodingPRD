"""Boundaries where the value on the line is the interesting one.

A four-member committee needs exactly three approvals and the third one counts,
and a pipeline report must answer an empty cohort without dividing while rounding
every non-empty share half up to one decimal place.
"""

from __future__ import annotations

from test_helpers import (
    CLOCK_AFTER_INTERVIEW,
    CLOCK_RANKING_DAY,
    CLOCK_WAVE_RELEASE,
    DIRECTOR_NAME,
    LEAD_INTERVIEWER_NAME,
    MEMBER_INTERVIEWER_NAME,
    OMIT,
    UNREPORTED_GROUP_LABEL,
    Ballot,
    RankListStatus,
    ScreeningStatus,
    SeasonBuilder,
    assert_one_decimal,
    expected_quorum_threshold,
    get_success_data,
    setup_program,
    validate_paginated,
    validate_success,
)

COMMITTEE_NAMES = {"f3": "Cyrus Bell", "f4": "Dana Fisk"}
WITHDRAWAL_REASON = "Accepted a position in another specialty"
ONE_OF_THREE = 33.3
ONE_OF_TWO = 50.0


def _list_in_committee_with_four_member_electorate():
    """A list under review whose eligible electorate is four faculty members."""
    builder = SeasonBuilder()
    builder.create_program()
    builder.add_faculty(
        "pd", DIRECTOR_NAME, is_program_director=True, is_committee_member=False
    )
    builder.add_faculty("f1", LEAD_INTERVIEWER_NAME, is_committee_member=True)
    builder.add_faculty("f2", MEMBER_INTERVIEWER_NAME, is_committee_member=True)
    for key, name in COMMITTEE_NAMES.items():
        builder.add_faculty(key, name, is_committee_member=True)
    builder.add_applicant("cand1")
    builder.open_review()
    builder.add_application("app1", "cand1")
    builder.add_reviews("app1", ("f1", "f2"))
    builder.screen("app1")
    builder.open_interviews()
    builder.create_wave(seat_capacity=4)
    builder.create_slot(applicant_capacity=4)
    builder.staff_standard_panel()
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    builder.issue_invitation("inv1", "app1")
    builder.accept_invitation("inv1", "slot1", "cand1")
    builder.clock(CLOCK_AFTER_INTERVIEW)
    builder.complete_slot("slot1")
    builder.add_standard_score_cards("app1", "1")
    builder.clock(CLOCK_RANKING_DAY)
    builder.close_wave()
    builder.open_ranking()
    builder.create_rank_list()
    builder.add_entry("entry1", "app1", 1)
    builder.submit_to_committee()
    return builder


def _cohort_of_three_applications():
    """Three applications: one alum, one IMG, one who declined to report a group."""
    builder = setup_program()
    builder.add_faculty("f1", LEAD_INTERVIEWER_NAME)
    builder.add_applicant("cand1")
    builder.add_applicant(
        "cand2",
        full_name="Omar Diaz",
        medical_school_type="IMG",
        visa_status="NEEDS_J1",
        step2_score=244,
    )
    builder.add_applicant(
        "cand3",
        full_name="Priya Rao",
        step2_score=232,
        self_identified_group=OMIT,
    )
    builder.open_review()
    for index in (1, 2, 3):
        builder.add_application(f"app{index}", f"cand{index}")
    return builder


def test_two_approvals_of_a_four_member_electorate_do_not_resolve_the_round(api):
    """Sixty percent of four rounds up to three, so two approvals are short.

    The list stays under review with no approval timestamp while the third ballot
    is outstanding.

    PRD 3.7: "The eligible electorate is the count of `FacultyMember` rows whose `program_id` equals the list's `program_id` and whose `is_committee_member` is true."
    PRD 3.7: "**Quorum resolution** runs after every single ballot is recorded on a list in `COMMITTEE_REVIEW`."

    Design: Difficulty/boundary_precision_check/quorum_ceiling_threshold_is_inclusive_at_exactly_three_of_four
    """
    builder = _list_in_committee_with_four_member_electorate()

    builder.cast_vote("f1", Ballot.APPROVE)
    builder.cast_vote("f2", Ballot.APPROVE)

    rank_list = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert expected_quorum_threshold(4) == 3, (
        "the helper and the specification must agree that four members need three"
    )
    assert rank_list["status"] == RankListStatus.COMMITTEE_REVIEW, (
        "two of three required approvals must not approve the list, got "
        f"{rank_list['status']}"
    )
    assert rank_list["approved_at"] is None, (
        f"no approval timestamp may be written yet, got {rank_list['approved_at']}"
    )


def test_the_third_approval_meets_the_threshold_inclusively(api):
    """The ballot that lands exactly on the threshold approves the list.

    Three approvals against a threshold of three is an at-or-above comparison, so
    the approve branch fires and stamps its timestamp.

    PRD 3.7: "The quorum threshold is that electorate size multiplied by 0.60 — sixty percent — and then **rounded up to the next whole number** by the ceiling function; an electorate of four therefore needs three, and an electorate of five also needs three."
    PRD 3.7: "The approve branch stamps `RankList.approved_at` with the current logical clock instant and increments `RankList.version` by one."

    Design: Difficulty/boundary_precision_check/quorum_ceiling_threshold_is_inclusive_at_exactly_three_of_four
    """
    builder = _list_in_committee_with_four_member_electorate()
    builder.cast_vote("f1", Ballot.APPROVE)
    builder.cast_vote("f2", Ballot.APPROVE)

    builder.cast_vote("f3", Ballot.APPROVE)

    rank_list = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert rank_list["status"] == RankListStatus.APPROVED, (
        "three approvals of four members should approve the list, got "
        f"{rank_list['status']}"
    )
    assert rank_list["approved_at"] is not None, "the approve branch stamps approved_at"
    assert rank_list["review_round"] == 1

    rows, meta = validate_paginated(
        api.list_votes_of_rank_list(
            builder.id("rank_list"), builder.director("pd"), params={"review_round": 1}
        )
    )
    assert meta["total_count"] == 3, (
        f"exactly three ballots belong to the round, got {meta['total_count']}"
    )
    assert all(row["ballot"] == Ballot.APPROVE for row in rows), (
        f"every counted ballot is an approval, got {[row['ballot'] for row in rows]}"
    )


def test_an_empty_cohort_answers_zero_rates_and_an_empty_bucket_list(api):
    """A program with no applications still answers, with no division performed.

    Every rate is exactly zero and the bucket array is empty rather than absent.

    PRD 3.10: "Every percentage in the report is computed the same way — the subset count divided by `cohort_size`, multiplied by 100, rounded half up to one decimal place — and is exactly 0.0 whenever `cohort_size` is 0, in which case no division is performed at all."
    PRD 3.10: "An empty cohort is an expected state and not an error: every rate is exactly 0.0, `group_buckets` is the empty array, and the endpoint still answers 200 OK."

    Design: Difficulty/boundary_precision_check/pipeline_report_zero_cohort_skips_division_and_one_decimal_half_up
    """
    builder = setup_program()

    report = validate_success(
        api.get_pipeline_report(builder.id("program"), builder.coordinator)
    )

    assert report["cohort_size"] == 0, (
        f"a program with no applications has an empty cohort, got {report['cohort_size']}"
    )
    for field in ("advanced_rate", "img_share", "pipeline_alum_share"):
        assert_one_decimal(report[field], 0.0, f"PipelineReport.{field}")
    assert report["group_buckets"] == [], (
        f"an empty cohort buckets nothing, got {report['group_buckets']}"
    )


def test_a_three_application_cohort_rounds_every_share_to_one_decimal(api):
    """One of three is 33.333..., which the one-place rule rounds half up to 33.3.

    The three group labels include the literal placeholder for the applicant who
    declined to report, and they come back in ascending label order.

    PRD 3.10: "Each application's group label is its applicant's `self_identified_group`, or the literal string `UNREPORTED` when that field is null because the applicant declined to report."
    PRD 3.10: "`group_buckets` is an array holding one object per distinct label present in the cohort, ordered by label in **ascending** order, and each object carries a `group` naming the label, a `count` of cohort applications bearing it, and a `share` computed by the same percentage rule."

    Design: Difficulty/boundary_precision_check/pipeline_report_zero_cohort_skips_division_and_one_decimal_half_up
    """
    builder = _cohort_of_three_applications()

    report = validate_success(
        api.get_pipeline_report(builder.id("program"), builder.coordinator)
    )

    assert report["cohort_size"] == 3
    assert_one_decimal(report["advanced_rate"], 0.0, "PipelineReport.advanced_rate")
    assert_one_decimal(report["img_share"], ONE_OF_THREE, "PipelineReport.img_share")
    assert_one_decimal(
        report["pipeline_alum_share"], ONE_OF_THREE, "PipelineReport.pipeline_alum_share"
    )

    labels = [bucket["group"] for bucket in report["group_buckets"]]
    assert labels == ["GROUP_A", "GROUP_B", UNREPORTED_GROUP_LABEL], (
        f"buckets should be ordered by ascending label, got {labels}"
    )
    for bucket in report["group_buckets"]:
        assert bucket["count"] == 1, (
            f"each label is borne by one application, got {bucket}"
        )
        assert_one_decimal(
            bucket["share"], ONE_OF_THREE, f"group_buckets[{bucket['group']}].share"
        )


def test_a_withdrawn_application_leaves_every_figure_in_the_report(api):
    """Withdrawal shrinks the cohort to two, and one of two is 50.0.

    The withdrawn applicant's bucket disappears entirely rather than dropping to
    a zero count.

    PRD 3.10: "Its cohort is every `Application` under the program whose `screening_status` is `RECEIVED`, `UNDER_REVIEW`, `ADVANCED` or `REJECTED`; `WITHDRAWN` applications are excluded from every figure in the report."
    PRD 3.2: "Withdrawal is the applicant's own prerogative and is permitted from three paper states — `RECEIVED → WITHDRAWN`, `UNDER_REVIEW → WITHDRAWN`, and `ADVANCED → WITHDRAWN` — in every case only when the acting applicant's `id` equals the application's `applicant_id`."

    Design: Difficulty/boundary_precision_check/pipeline_report_zero_cohort_skips_division_and_one_decimal_half_up
    """
    builder = _cohort_of_three_applications()

    builder.withdraw_application("app3", WITHDRAWAL_REASON)

    withdrawn = get_success_data(
        api.get_application(builder.id("app3"), builder.coordinator)
    )
    assert withdrawn["screening_status"] == ScreeningStatus.WITHDRAWN

    report = validate_success(
        api.get_pipeline_report(builder.id("program"), builder.coordinator)
    )
    assert report["cohort_size"] == 2, (
        f"the withdrawn application leaves the cohort, got {report['cohort_size']}"
    )
    assert_one_decimal(report["img_share"], ONE_OF_TWO, "PipelineReport.img_share")
    assert_one_decimal(
        report["pipeline_alum_share"], ONE_OF_TWO, "PipelineReport.pipeline_alum_share"
    )

    buckets = {bucket["group"]: bucket for bucket in report["group_buckets"]}
    assert list(buckets) == ["GROUP_A", "GROUP_B"], (
        f"only the two remaining labels are bucketed, got {list(buckets)}"
    )
    for bucket in buckets.values():
        assert bucket["count"] == 1
        assert_one_decimal(
            bucket["share"], ONE_OF_TWO, f"group_buckets[{bucket['group']}].share"
        )
