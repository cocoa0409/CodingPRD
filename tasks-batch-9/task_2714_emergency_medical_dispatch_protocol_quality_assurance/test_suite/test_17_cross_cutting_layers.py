"""Cross-cutting layers of the EMD dispatch QA API.

Covers the two optimistic-concurrency comparands (the review version guarding an
appended score sheet and the dispatcher version guarding a manual coaching
plan), the full recomputation of the dispatcher compliance roll-up across a
finalize and its compensating void, and the composition of list filters with the
pagination window on the review list.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.assertions import (
    approx1,
    approx2,
    assert_created_at_ascending,
    assert_instant_equals,
)

CLOCK = "2026-08-20T00:00:00Z"

SECTIONS_92 = {
    "case_entry": (23, 25),
    "key_questions": (23, 25),
    "pre_arrival": (23, 25),
    "final_coding": (23, 25),
}
SECTIONS_88 = {
    "case_entry": (22, 25),
    "key_questions": (22, 25),
    "pre_arrival": (22, 25),
    "final_coding": (22, 25),
}
SECTIONS_PARTIAL = {
    "case_entry": (18, 20),
    "key_questions": (26, 30),
    "pre_arrival": (0, 0),
    "final_coding": (5, 7),
}
SECTIONS_ALL_FULL = {
    "case_entry": (20, 20),
    "key_questions": (30, 30),
    "pre_arrival": (0, 0),
    "final_coding": (7, 7),
}


def _program_with_dispatcher(api):
    """A programme with an APPROVED MPDS card set, one dispatcher, clock at CLOCK."""
    program = fx.new_program(api)
    version = fx.new_approved_version(api, program["id"], version_label="MPDS-13.0")
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, CLOCK)
    return program, version, dispatcher


IMMUTABLE_SHEET_KEYS = (
    "id",
    "review_id",
    "sheet_round",
    "submitted_by_user_id",
    "case_entry_pct",
    "key_questions_pct",
    "pre_arrival_pct",
    "final_coding_pct",
    "provisional_composite_score",
    "determinant_accuracy",
)


def test_a_stale_review_version_blocks_a_second_score_sheet(api):
    """PRD §2.7: "Submitting a score sheet (`POST /reviews/{id}/scores`) requires
    `expected_review_version`, carrying the `version` of the target review as the
    client last observed it. If that value does not equal the review's current
    `version` — because another reviewer appended a sheet, because a supervisor
    adjudicated a rebuttal, or because a cascade touched the row — the submission
    is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412)."
    PRD §3.5: "Sheets themselves are **append-only**: each submission creates a
    new score sheet whose `sheet_round` is one greater than the review's
    `current_sheet_round` at the moment of submission, and no earlier sheet is
    ever mutated or deleted."
    PRD §3.5: "Each accepted submission increments the review's `version` by 1,
    which is precisely why a client must re-read the review before submitting a
    second sheet."

    Design: Corner/cross_cutting_layers/a_stale_review_version_blocks_a_second_score_sheet
    """
    program, version, dispatcher = _program_with_dispatcher(api)
    call = fx.ingest_call(api, dispatcher["id"], received_at="2026-08-05T09:00:00Z")
    period = fx.new_period(api, program["id"], target_sample_count=1)
    review = fx.target(api, period["id"], call["id"], "COMPLAINT")
    observed_version = review["version"]

    sheet_one = validate_success(
        api.submit_scores(
            review["id"],
            f.section_score_payload(observed_version, SECTIONS_PARTIAL, "10-C-4"),
            u.REVIEWER,
        ),
        201,
    )
    assert sheet_one["sheet_round"] == 1
    refreshed_version = validate_success(
        api.get_review(review["id"], u.REVIEWER), 200
    )["version"]
    assert refreshed_version != observed_version

    validate_error(
        api.submit_scores(
            review["id"],
            f.section_score_payload(observed_version, SECTIONS_ALL_FULL, "10-C-4"),
            u.REVIEWER,
        ),
        err.ERR_STALE_REVIEW_VERSION,
    )
    _, meta = validate_paginated(
        api.list_score_sheets(review["id"], u.SUPERVISOR, {"limit": 100})
    )
    assert meta["total_count"] == 1, "the refused replay must not append a sheet"

    sheet_two = validate_success(
        api.submit_scores(
            review["id"],
            f.section_score_payload(refreshed_version, SECTIONS_ALL_FULL, "10-C-4"),
            u.REVIEWER,
        ),
        201,
    )
    assert sheet_two["sheet_round"] == 2

    sheets, meta = validate_paginated(
        api.list_score_sheets(review["id"], u.SUPERVISOR, {"limit": 100})
    )
    assert meta["total_count"] == 2
    assert [row["sheet_round"] for row in sheets] == [1, 2]
    assert_created_at_ascending(sheets)

    preserved = sheets[0]
    for key in IMMUTABLE_SHEET_KEYS:
        assert preserved[key] == sheet_one[key], (
            f"the round-1 sheet's {key} must never be rewritten"
        )
    assert_instant_equals(preserved["created_at"], sheet_one["created_at"])

    after = validate_success(api.get_review(review["id"], u.SUPERVISOR), 200)
    assert after["provisional_composite_score"] == approx1(100.0), (
        "the review reads the current sheet, which is the round-2 sheet"
    )
    assert after["current_sheet_round"] == 2
    assert after["version"] == refreshed_version + 1


def test_a_stale_dispatcher_version_blocks_a_manual_coaching_plan(api):
    """PRD §2.7: "Creating a manual coaching plan (`POST /coaching-plans`) requires
    `expected_dispatcher_version`, carrying the `version` of the target dispatcher
    as the client last observed it. If that value does not equal the dispatcher's
    current `version`, the create is rejected with `ERR_STALE_DISPATCHER_VERSION`
    (HTTP 412)."
    PRD §3.8: "The plan is written with `origin` `MANUAL`, `status` `ASSIGNED`,
    `required_hours` from the severity table and `credited_hours` at 0.00."
    PRD §3.8: "Consequently the dispatcher's `remediation_hours_owed` is
    recomputed, their `dispatch_privilege` re-derived, and the dispatcher row's
    `version` incremented."

    Design: Corner/cross_cutting_layers/a_stale_dispatcher_version_blocks_a_manual_coaching_plan
    """
    program, version, dispatcher = _program_with_dispatcher(api)
    observed_version = dispatcher["version"]

    certified = validate_success(
        api.certify_dispatcher(
            dispatcher["id"], {"protocol_version_id": version["id"]}, u.ADMIN
        ),
        200,
    )
    assert certified["certification_status"] == "CERTIFIED"
    refreshed_version = certified["version"]
    assert refreshed_version != observed_version, (
        "certification mutates the dispatcher row behind the supervisor's back"
    )

    validate_error(
        api.create_coaching_plan(
            f.coaching_plan_payload(dispatcher["id"], observed_version),
            u.SUPERVISOR,
        ),
        err.ERR_STALE_DISPATCHER_VERSION,
    )
    _, meta = validate_paginated(
        api.list_coaching_plans(
            u.SUPERVISOR, {"dispatcher_id": dispatcher["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, "the refused create must not write a plan"
    untouched = validate_success(api.get_dispatcher(dispatcher["id"], u.ADMIN), 200)
    assert untouched["remediation_hours_owed"] == approx2(0.00)

    plan = validate_success(
        api.create_coaching_plan(
            f.coaching_plan_payload(dispatcher["id"], refreshed_version),
            u.SUPERVISOR,
        ),
        201,
    )
    assert plan["origin"] == "MANUAL"
    assert plan["status"] == "ASSIGNED"
    assert plan["severity"] == "STANDARD"
    assert plan["required_hours"] == approx1(4.0)
    assert plan["credited_hours"] == approx2(0.00)

    after = validate_success(api.get_dispatcher(dispatcher["id"], u.ADMIN), 200)
    assert after["remediation_hours_owed"] == approx2(4.00)
    assert after["dispatch_privilege"] == "FULL", (
        "4.00 owed hours does not exceed the 6.0-hour restriction threshold"
    )
    assert after["version"] == refreshed_version + 1


def test_the_compliance_rollup_reconciles_after_each_finalize_and_void(api):
    """PRD §2.8: "When a review is finalized, the dispatcher's case count, point
    total and compliance percentage are recomputed by walking that dispatcher's
    finalized reviews; when the same review is later voided, the same walk runs
    again over the smaller set."
    PRD §3.7: "`reviewed_case_count` is the number of such reviews,
    `compliance_points_total` is the sum of their `final_composite_score` values
    rounded half up to 1 decimal place, and `compliance_pct` is that total divided
    by the count, rounded half up to 1 decimal place."
    PRD §3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it
    is at or above the programme's `target_compliance_pct`, `WATCH` when it is
    below that but at or above `watch_floor_pct`, and `PROBATION` when it is below
    the watch floor; a dispatcher with no finalized reviews is `UNRATED`."
    PRD §3.7: "Because the review has left the finalized set, the dispatcher's
    `reviewed_case_count`, `compliance_points_total`, `compliance_pct` and
    `compliance_posture` are recomputed over the remaining finalized reviews — and
    because the recomputation is a full walk rather than a subtraction, the point
    ledger returns to exactly the value it held before the finalization, with no
    drift."
    PRD §3.7: "Every void sets `status` to `VOIDED`, stamps `voided_at` from the
    logical clock, records the `void_reason`, returns the underlying call record
    from `SELECTED` to `INGESTED`, and recomputes the period's
    `selected_review_count` — which is what returns a consumed sample slot to the
    quota, since that counter counts only reviews in `SELECTED`, `SCORED`,
    `DISPUTED` or `FINALIZED`."

    Design: Corner/cross_cutting_layers/the_compliance_rollup_reconciles_after_each_finalize_and_void
    """
    program, version, dispatcher = _program_with_dispatcher(api)
    call_one = fx.ingest_call(api, dispatcher["id"], received_at="2026-08-05T09:00:00Z")
    call_two = fx.ingest_call(api, dispatcher["id"], received_at="2026-08-06T09:00:00Z")
    period = fx.new_period(api, program["id"], target_sample_count=2)
    review_one = fx.target(api, period["id"], call_one["id"], "COMPLAINT")
    review_two = fx.target(api, period["id"], call_two["id"], "COMPLAINT")
    fx.score(
        api,
        review_one["id"],
        sections=SECTIONS_92,
        expected_review_version=review_one["version"],
    )
    fx.score(
        api,
        review_two["id"],
        sections=SECTIONS_88,
        expected_review_version=review_two["version"],
    )

    first = validate_success(
        api.finalize_review(review_one["id"], {"finalization_note": "first case"}, u.SUPERVISOR),
        200,
    )
    assert first["final_composite_score"] == approx1(92.0)
    ledger = validate_success(api.get_dispatcher(dispatcher["id"], u.ADMIN), 200)
    assert ledger["reviewed_case_count"] == 1
    assert ledger["compliance_points_total"] == approx1(92.0)
    assert ledger["compliance_pct"] == approx1(92.0)
    assert ledger["compliance_posture"] == "GOOD"

    second = validate_success(
        api.finalize_review(review_two["id"], {"finalization_note": "second case"}, u.SUPERVISOR),
        200,
    )
    assert second["final_composite_score"] == approx1(88.0)
    ledger = validate_success(api.get_dispatcher(dispatcher["id"], u.ADMIN), 200)
    assert ledger["reviewed_case_count"] == 2
    assert ledger["compliance_points_total"] == approx1(180.0)
    assert ledger["compliance_pct"] == approx1(90.0)
    assert ledger["compliance_posture"] == "GOOD", (
        "the posture comparison against target_compliance_pct is inclusive"
    )

    voided = validate_success(
        api.void_review(review_two["id"], {"void_reason": "AUDIO_UNAVAILABLE"}, u.SUPERVISOR),
        200,
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "AUDIO_UNAVAILABLE"
    assert voided["final_composite_score"] is None
    assert voided["compliant"] is None

    ledger = validate_success(api.get_dispatcher(dispatcher["id"], u.ADMIN), 200)
    assert ledger["reviewed_case_count"] == 1
    assert ledger["compliance_points_total"] == approx1(92.0), (
        "the voided case left the population rather than being averaged in"
    )
    assert ledger["compliance_pct"] == approx1(92.0)
    assert ledger["compliance_posture"] == "GOOD"

    calls, _ = validate_paginated(
        api.list_call_records(dispatcher["id"], u.ADMIN, {"limit": 100})
    )
    by_id = {row["id"]: row for row in calls}
    assert by_id[call_two["id"]]["status"] == "INGESTED"
    assert by_id[call_one["id"]]["status"] == "SELECTED"

    finalized, meta = validate_paginated(
        api.list_reviews(
            u.SUPERVISOR,
            {"dispatcher_id": dispatcher["id"], "status": "FINALIZED", "limit": 100},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in finalized] == [review_one["id"]]


def test_filters_and_paging_compose_on_the_review_list(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted value
    is 100."
    PRD §2.3: "`offset` is the number of items to skip before the page begins;
    when omitted it defaults to 0 and its minimum accepted value is 0."
    PRD §2.3: "Unless a subsection below says otherwise, every list endpoint
    returns its resources ordered by `created_at` ascending."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    number of rows matching the filters before the page window is applied and
    `has_more` indicates whether rows remain beyond it."
    PRD §3.9: "Beyond single-resource reads, the list surfaces accept filters
    that mirror the fields above, all of them optional and all combinable with
    `limit` and `offset`: a programme's protocol versions may be filtered by
    `status` and by `protocol_family`; a version's rollouts by `golive_status`;
    dispatchers by `program_id`, `certified_protocol_version_id`,
    `compliance_posture`, `dispatch_privilege`, and `certification_status`; a
    dispatcher's calls by `call_type` and `status`; a programme's sampling periods
    by `status` and `call_type`; reviews by `sampling_period_id`,
    `call_record_id`, `dispatcher_id`, `protocol_version_id`, `status`, and
    `high_risk`; a review's rebuttals and a review's clinical record by `status`;
    coaching plans by `dispatcher_id`, `source_review_id`, `status`, `severity`,
    and `origin`; a plan's sessions and a curriculum version's sessions by
    `status`; and a programme's accreditation reports by `status` and `variant`."

    Design: Corner/cross_cutting_layers/filters_and_paging_compose_on_the_review_list
    """
    program, version, dispatcher = _program_with_dispatcher(api)
    calls = [
        fx.ingest_call(api, dispatcher["id"], received_at=received)
        for received in (
            "2026-08-05T09:00:00Z",
            "2026-08-06T09:00:00Z",
            "2026-08-07T09:00:00Z",
            "2026-08-08T09:00:00Z",
        )
    ]
    period = fx.new_period(
        api, program["id"], sampling_mode="MIXED", target_sample_count=4
    )
    reviews = [fx.target(api, period["id"], call["id"], "COMPLAINT") for call in calls]
    fx.score(
        api,
        reviews[0]["id"],
        sections=SECTIONS_92,
        expected_review_version=reviews[0]["version"],
    )
    finalized = validate_success(
        api.finalize_review(reviews[0]["id"], {"finalization_note": "clean case"}, u.SUPERVISOR),
        200,
    )
    assert finalized["status"] == "FINALIZED"
    still_selected = [review["id"] for review in reviews[1:]]

    first_page, first_meta = validate_paginated(
        api.list_reviews(u.SUPERVISOR, {"status": "SELECTED", "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3, (
        "total_count counts the rows matching the filter before the page window"
    )
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert_created_at_ascending(first_page)

    second_page, second_meta = validate_paginated(
        api.list_reviews(u.SUPERVISOR, {"status": "SELECTED", "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(paged_ids) == len(set(paged_ids)), "the two pages must not overlap"
    assert set(paged_ids) == set(still_selected)
    assert reviews[0]["id"] not in paged_ids, (
        "the finalized review is excluded by the status filter, not merely paged away"
    )
    assert {row["status"] for row in first_page + second_page} == {"SELECTED"}

    finalized_rows, finalized_meta = validate_paginated(
        api.list_reviews(u.SUPERVISOR, {"status": "FINALIZED", "limit": 2, "offset": 0})
    )
    assert finalized_meta["total_count"] == 1
    assert finalized_meta["has_more"] is False
    assert [row["id"] for row in finalized_rows] == [reviews[0]["id"]]
    assert finalized_rows[0]["final_composite_score"] == approx1(92.0)

    composed, composed_meta = validate_paginated(
        api.list_reviews(
            u.SUPERVISOR,
            {
                "dispatcher_id": dispatcher["id"],
                "status": "SELECTED",
                "limit": 1,
                "offset": 1,
            },
        )
    )
    assert composed_meta["total_count"] == 3, (
        "both filters narrow the population before the window is applied"
    )
    assert composed_meta["has_more"] is True
    assert len(composed) == 1
    assert composed[0]["id"] == still_selected[1]

    every_row, every_meta = validate_paginated(
        api.list_reviews(u.SUPERVISOR, {"dispatcher_id": dispatcher["id"], "limit": 100})
    )
    assert every_meta["total_count"] == 4
    assert every_meta["has_more"] is False
    assert [row["id"] for row in every_row] == [review["id"] for review in reviews]
    assert_created_at_ascending(every_row)

    other_period, other_meta = validate_paginated(
        api.list_reviews(u.SUPERVISOR, {"sampling_period_id": period["id"], "limit": 100})
    )
    assert other_meta["total_count"] == 4
    assert {row["protocol_version_id"] for row in other_period} == {version["id"]}
