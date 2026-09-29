"""Compensating actions that must return every derived ledger to its earlier value.

Voiding a finalized review, cancelling a completed retraining session and voiding
a merely selected review are each the exact reverse of the action that preceded
them, and each is verified by comparing the recomputed state against the state
recorded before the forward action ran.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2, assert_instant_equals
from test_helpers.test_users import ADMIN, SUPERVISOR

WORKING_CLOCK = "2026-08-20T00:00:00Z"


def test_voiding_a_finalized_review_clears_the_numbers_it_published(api):
    """PRD 3.6: "Every void sets `status` to `VOIDED`, stamps `voided_at` from the logical
    clock, records the `void_reason`, returns the underlying call record from `SELECTED` to
    `INGESTED`, and recomputes the period's `selected_review_count` — which is what returns a
    consumed sample slot to the quota, since that counter counts only reviews in `SELECTED`,
    `SCORED`, `DISPUTED` or `FINALIZED`."
    PRD 3.6: "The review's `final_composite_score`, `pre_penalty_composite_score`,
    `penalty_points`, `determinant_accuracy` and `compliant` are all cleared to null, and
    both period counters are recomputed."

    Design: Difficulty/compensating_invariant/voiding_a_finalized_review_reverses_every_link_of_the_finalize_cascade
    """
    env = fx.under_triage_finalized_env(api)
    finalized = fx.get_review(api, env["review_id"])
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_composite_score"] == approx1(75.0)

    voided = validate_success(
        api.void_review(env["review_id"], {"void_reason": "AUDIO_UNAVAILABLE"}, SUPERVISOR)
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "AUDIO_UNAVAILABLE"
    assert_instant_equals(voided["voided_at"], WORKING_CLOCK)
    assert voided["final_composite_score"] is None
    assert voided["pre_penalty_composite_score"] is None
    assert voided["penalty_points"] is None
    assert voided["determinant_accuracy"] is None
    assert voided["compliant"] is None
    assert_instant_equals(voided["scored_at"], finalized["scored_at"])


def test_voiding_returns_the_dispatcher_ledgers_to_their_pre_finalize_values(api):
    """PRD 3.6: "Because the review has left the finalized set, the dispatcher's
    `reviewed_case_count`, `compliance_points_total`, `compliance_pct` and
    `compliance_posture` are recomputed over the remaining finalized reviews — and because the
    recomputation is a full walk rather than a subtraction, the point ledger returns to
    exactly the value it held before the finalization, with no drift."
    PRD 3.6: "When the count is zero, `compliance_pct` is null rather than 0.0."

    Design: Difficulty/compensating_invariant/voiding_a_finalized_review_reverses_every_link_of_the_finalize_cascade
    """
    env = fx.under_triage_finalized_env(api)
    published = fx.get_dispatcher(api, env["dispatcher_id"])
    assert published["reviewed_case_count"] == 1
    assert published["compliance_pct"] == approx1(75.0)
    assert published["compliance_posture"] == "PROBATION"
    assert published["dispatch_privilege"] == "RESTRICTED"

    fx.void(api, env["review_id"], "AUDIO_UNAVAILABLE")

    reverted = fx.get_dispatcher(api, env["dispatcher_id"])
    assert reverted["reviewed_case_count"] == 0
    assert reverted["compliance_points_total"] == approx1(0.0)
    assert reverted["compliance_pct"] is None, "an unrated dispatcher has no percentage at all"
    assert reverted["compliance_posture"] == "UNRATED"
    assert reverted["remediation_hours_owed"] == approx2(0.00)
    assert reverted["dispatch_privilege"] == "FULL"


def test_the_automatic_plan_is_cancelled_rather_than_deleted(api):
    """PRD 3.6: "Because the source review is gone, every automatic coaching plan attributed
    to it — those whose `origin` is `AUTO`, whose `source_review_id` is this review, and whose
    `status` is `ASSIGNED`, `IN_PROGRESS` or `SUSPENDED` — moves to `CANCELLED` with
    `closure_reason` set to `SOURCE_VOIDED`; any `SCHEDULED` session already booked against
    such a plan is left exactly where it is, but it can no longer be completed, because
    completion requires an open plan."

    Design: Difficulty/compensating_invariant/voiding_a_finalized_review_reverses_every_link_of_the_finalize_cascade
    """
    env = fx.under_triage_finalized_env(api)
    before = fx.list_plans_for(api, env["dispatcher_id"])
    assert len(before) == 1
    assert before[0]["origin"] == "AUTO"
    assert before[0]["severity"] == "CRITICAL"
    assert before[0]["status"] == "ASSIGNED"

    fx.void(api, env["review_id"], "AUDIO_UNAVAILABLE")

    after = fx.list_plans_for(api, env["dispatcher_id"])
    assert len(after) == 1, f"the plan is cancelled, not deleted, got {after}"
    assert after[0]["id"] == before[0]["id"]
    assert after[0]["status"] == "CANCELLED"
    assert after[0]["closure_reason"] == "SOURCE_VOIDED"
    assert after[0]["required_hours"] == approx1(8.0)


def test_the_call_and_period_counters_revert_but_the_score_sheets_are_kept(api):
    """PRD 3.6: "Every void sets `status` to `VOIDED`, stamps `voided_at` from the logical
    clock, records the `void_reason`, returns the underlying call record from `SELECTED` to
    `INGESTED`, and recomputes the period's `selected_review_count` — which is what returns a
    consumed sample slot to the quota, since that counter counts only reviews in `SELECTED`,
    `SCORED`, `DISPUTED` or `FINALIZED`."
    PRD 3.5: "Sheets themselves are **append-only**: each submission creates a new score sheet
    whose `sheet_round` is one greater than the review's `current_sheet_round` at the moment of
    submission, and no earlier sheet is ever mutated or deleted."

    Design: Difficulty/compensating_invariant/voiding_a_finalized_review_reverses_every_link_of_the_finalize_cascade
    """
    env = fx.under_triage_finalized_env(api)
    fx.void(api, env["review_id"], "AUDIO_UNAVAILABLE")

    calls = validate_success(
        api.list_call_records(env["dispatcher_id"], ADMIN, {"limit": 100})
    )
    assert [row["status"] for row in calls if row["id"] == env["call_id"]] == ["INGESTED"]

    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["selected_review_count"] == 0
    assert period["finalized_review_count"] == 0

    sheets = fx.list_sheets(api, env["review_id"])
    assert len(sheets) == 1, "the append-only audit trail is not reversed"
    assert sheets[0]["id"] == env["sheet_id"]
    assert sheets[0]["provisional_composite_score"] == approx1(90.0)
    assert fx.get_review(api, env["review_id"])["current_sheet_round"] == 1


def _verified_plan_env(api):
    """One ADVISORY plan whose single 2.00-hour session has been completed, verifying it."""
    program = fx.new_program(
        api, name="Zephyr EMD QA", accreditation_body="IAED",
        hours_owed_restriction_threshold=6.0,
    )
    version = fx.new_approved_version(
        api, program["id"], version_label="MPDS-13.0",
        effective_from="2026-07-01T00:00:00Z",
    )
    dispatcher = fx.new_dispatcher(api, program["id"], employee_code="EMD-P01",
                                   full_name="Bea Nkemdirim")
    fx.set_clock(api, WORKING_CLOCK)
    plan = fx.new_coaching_plan(
        api, dispatcher["id"], severity="ADVISORY", focus_area="FINAL_CODING"
    )
    session = fx.new_session(
        api,
        plan["id"],
        version["id"],
        starts_at="2026-08-15T09:00:00Z",
        ends_at="2026-08-15T11:00:00Z",
        modality="ONE_ON_ONE",
    )
    fx.complete_session(api, session["id"])
    return {
        "program_id": program["id"],
        "dispatcher_id": dispatcher["id"],
        "plan_id": plan["id"],
        "session_id": session["id"],
    }


def test_completing_the_last_owed_hours_verifies_the_plan_and_empties_the_ledger(api):
    """PRD 3.8: "Completion moves the session `SCHEDULED → COMPLETED`, stamps `completed_at`
    from the logical clock, and recomputes the plan's `credited_hours` as the sum of
    `duration_hours` over every session of the plan in `COMPLETED`, rounded half up to 2
    decimal places — sessions in `SCHEDULED` or `CANCELLED` contribute nothing."
    PRD 3.8: "When `credited_hours` reaches `required_hours`, with exact equality sufficing,
    the plan bubbles up `IN_PROGRESS → VERIFIED` and stamps `verified_at` from the logical
    clock."

    Design: Difficulty/compensating_invariant/cancelling_a_completed_session_returns_the_hours_ledger_and_the_plan_state
    """
    env = _verified_plan_env(api)

    session = fx.get_session(api, env["plan_id"], env["session_id"])
    assert session["status"] == "COMPLETED"
    assert session["duration_hours"] == approx2(2.00)
    assert_instant_equals(session["completed_at"], WORKING_CLOCK)

    plan = fx.get_plan(api, env["plan_id"])
    assert plan["credited_hours"] == approx2(2.00)
    assert plan["status"] == "VERIFIED"
    assert_instant_equals(plan["verified_at"], WORKING_CLOCK)
    assert fx.get_dispatcher(api, env["dispatcher_id"])["remediation_hours_owed"] == approx2(0.00)


def test_cancelling_the_completed_session_pushes_the_plan_back_and_reinstates_the_hours(api):
    """PRD 3.8: "A session in `SCHEDULED` may be cancelled, in which case `credited_hours`
    never changed and no ledger moves at all; a session already in `COMPLETED` may also be
    cancelled, which is a genuine compensating action: `completed_at` is cleared to null and
    `credited_hours` is recomputed over the remaining completed sessions, returning it to
    exactly its pre-completion value."
    PRD 3.8: "If that drops `credited_hours` back below `required_hours` on a plan that had
    reached `VERIFIED`, the plan cycles `VERIFIED → IN_PROGRESS` and its `verified_at` is
    cleared to null."

    Design: Difficulty/compensating_invariant/cancelling_a_completed_session_returns_the_hours_ledger_and_the_plan_state
    """
    env = _verified_plan_env(api)

    cancelled = validate_success(
        api.cancel_retraining_session(
            env["session_id"], {"cancel_reason": "ATTENDANCE_DISPUTED"}, SUPERVISOR
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["completed_at"] is None
    assert cancelled["cancel_reason"] == "ATTENDANCE_DISPUTED"
    assert cancelled["duration_hours"] == approx2(2.00)

    plan = fx.get_plan(api, env["plan_id"])
    assert plan["credited_hours"] == approx2(0.00)
    assert plan["status"] == "IN_PROGRESS"
    assert plan["verified_at"] is None


def test_the_reopened_plan_puts_its_full_requirement_back_into_the_owed_ledger(api):
    """PRD 3.8: "The owed-hours ledger itself is a full recomputation over the dispatcher's
    **open** plans — those in `ASSIGNED`, `IN_PROGRESS` or `SUSPENDED`, with `VERIFIED` and
    `CANCELLED` plans contributing nothing."
    PRD 3.8: "Cancelling a session is the mirror image and carries a free-text
    `cancel_reason`."

    Design: Difficulty/compensating_invariant/cancelling_a_completed_session_returns_the_hours_ledger_and_the_plan_state
    """
    env = _verified_plan_env(api)
    fx.cancel_session(api, env["session_id"], "ATTENDANCE_DISPUTED")

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["remediation_hours_owed"] == approx2(2.00)
    assert dispatcher["dispatch_privilege"] == "FULL", "2.00 owed is not above the 6.0 threshold"

    sessions = validate_success(
        api.list_retraining_sessions(env["plan_id"], SUPERVISOR, {"limit": 100})
    )
    assert [row["id"] for row in sessions] == [env["session_id"]], "cancelled, not deleted"


def _filled_quota_env(api):
    """A one-slot TARGETED period whose only slot is held by a SELECTED review."""
    program = fx.new_program(api, name="Alder EMD QA", accreditation_body="IAED")
    version = fx.new_approved_version(
        api, program["id"], version_label="MPDS-13.0",
        effective_from="2026-07-01T00:00:00Z",
    )
    dispatcher = fx.new_dispatcher(api, program["id"], employee_code="EMD-Q01",
                                   full_name="Cyrus Delacroix")
    fx.set_clock(api, WORKING_CLOCK)
    first_call = fx.ingest_call(api, dispatcher["id"], call_reference="C-Q001",
                               received_at="2026-08-05T09:00:00Z")
    second_call = fx.ingest_call(api, dispatcher["id"], call_reference="C-Q002",
                                received_at="2026-08-06T09:00:00Z")
    period = fx.new_period(api, program["id"], target_sample_count=1)
    review = fx.target(api, period["id"], first_call["id"], "COMPLAINT")
    return {
        "program_id": program["id"],
        "version_id": version["id"],
        "dispatcher_id": dispatcher["id"],
        "first_call_id": first_call["id"],
        "second_call_id": second_call["id"],
        "period_id": period["id"],
        "review_id": review["id"],
    }


def _call_status(api, dispatcher_id, call_id):
    rows = validate_success(api.list_call_records(dispatcher_id, ADMIN, {"limit": 100}))
    for row in rows:
        if row["id"] == call_id:
            return row["status"]
    raise AssertionError(f"call record {call_id} not found")


def test_a_consumed_sample_slot_blocks_both_the_same_call_and_a_second_one(api):
    """PRD 3.4: "And a call already in `status` `SELECTED` cannot be pulled in a second time —
    that is refused with `ERR_CALL_ALREADY_SELECTED`."
    PRD 3.4: "Both routes also require that at least one sample slot remains: when
    `selected_review_count` has already reached `target_sample_count`, further selection is
    refused with `ERR_SAMPLE_QUOTA_FILLED`."

    Design: Difficulty/compensating_invariant/voiding_a_selected_review_returns_the_sample_slot_and_the_call
    """
    env = _filled_quota_env(api)
    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["selected_review_count"] == 1
    assert _call_status(api, env["dispatcher_id"], env["first_call_id"]) == "SELECTED"

    already_selected = api.target_review(
        env["period_id"],
        {"call_record_id": env["first_call_id"], "selection_reason": "SENTINEL_FLAG"},
        SUPERVISOR,
    )
    validate_error(already_selected, err.ERR_CALL_ALREADY_SELECTED)

    quota_filled = api.target_review(
        env["period_id"],
        {"call_record_id": env["second_call_id"], "selection_reason": "COMPLAINT"},
        SUPERVISOR,
    )
    validate_error(quota_filled, err.ERR_SAMPLE_QUOTA_FILLED)


def test_voiding_a_selected_review_returns_the_call_and_the_slot(api):
    """PRD 3.6: "Every void sets `status` to `VOIDED`, stamps `voided_at` from the logical
    clock, records the `void_reason`, returns the underlying call record from `SELECTED` to
    `INGESTED`, and recomputes the period's `selected_review_count` — which is what returns a
    consumed sample slot to the quota, since that counter counts only reviews in `SELECTED`,
    `SCORED`, `DISPUTED` or `FINALIZED`."
    PRD 3.6: "Voiding from `SELECTED` has no ledger consequences at all, because the review
    never contributed a compliance point."

    Design: Difficulty/compensating_invariant/voiding_a_selected_review_returns_the_sample_slot_and_the_call
    """
    env = _filled_quota_env(api)

    voided = validate_success(
        api.void_review(env["review_id"], {"void_reason": "WRONG_DISPATCHER"}, SUPERVISOR)
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "WRONG_DISPATCHER"

    assert _call_status(api, env["dispatcher_id"], env["first_call_id"]) == "INGESTED"
    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["selected_review_count"] == 0
    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["reviewed_case_count"] == 0
    assert dispatcher["compliance_pct"] is None


def test_the_returned_slot_admits_a_brand_new_review_on_the_very_same_call(api):
    """PRD 3.4: "A successful targeted selection creates one review with `selection_mode` of
    `TARGETED`, moves the call to `SELECTED`, and increments the period's
    `selected_review_count` by one."
    PRD 3.4: "Each new review resolves `protocol_version_id` by searching the `MPDS_CARDSET`
    family of the period's programme for the single version whose `status` is `APPROVED`,
    `ACTIVE` or `SUPERSEDED` and whose governing interval contains the call's `received_at` —
    `effective_from` at or before the instant and `effective_to` either null or strictly after
    it."

    Design: Difficulty/compensating_invariant/voiding_a_selected_review_returns_the_sample_slot_and_the_call
    """
    env = _filled_quota_env(api)
    fx.void(api, env["review_id"], "WRONG_DISPATCHER")

    retargeted = validate_success(
        api.target_review(
            env["period_id"],
            {"call_record_id": env["first_call_id"], "selection_reason": "SENTINEL_FLAG"},
            SUPERVISOR,
        ),
        expected_status=201,
    )
    assert retargeted["id"] != env["review_id"], "the slot yields a distinct new review row"
    assert retargeted["status"] == "SELECTED"
    assert retargeted["selection_mode"] == "TARGETED"
    assert retargeted["selection_reason"] == "SENTINEL_FLAG"
    assert retargeted["current_sheet_round"] == 0
    assert retargeted["protocol_version_id"] == env["version_id"]

    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["selected_review_count"] == 1

    all_reviews = validate_success(
        api.list_reviews(SUPERVISOR, {"sampling_period_id": env["period_id"], "limit": 100})
    )
    assert sorted(row["status"] for row in all_reviews) == ["SELECTED", "VOIDED"]
    still_open = validate_success(
        api.list_reviews(
            SUPERVISOR,
            {"sampling_period_id": env["period_id"], "status": "SELECTED", "limit": 100},
        )
    )
    assert [row["id"] for row in still_open] == [retargeted["id"]]
