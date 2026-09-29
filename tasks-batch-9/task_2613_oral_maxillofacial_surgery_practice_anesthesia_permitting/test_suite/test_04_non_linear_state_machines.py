"""Non-linear lifecycles: the permit probation cycle, the case's two independent
state dimensions, and the adverse-event fork/join."""
import pytest

from test_helpers import (
    assert_instant_equals,
    ADMIN,
    api_client,
    close_adverse_event,
    fetch_adverse_event,
    file_adverse_event,
    make_quality_reviewer_headers,
    open_morbidity_review,
    record_regulator_notification,
    setup_practice_with_roster,
    sign_off_morbidity_review,
    validate_error,
    create_block,
    create_evaluation_for,
    draft_case,
    fetch_block,
    fetch_case,
    fetch_evaluation,
    fetch_permit,
    fetch_practice,
    hold_case_on_block,
    confirm_case,
    record_inspection_result,
    schedule_inspection,
    set_env_clock,
    setup_permitted_practice,
    sign_evaluation_as,
    validate_success,
    verify_evaluation_as,
)

CLOCK = "2026-09-11T10:00:00Z"

# --- permit_probation_remediation_cycle ---------------------------------------


def _permit_on_probation():
    """An ACTIVE MODERATE_SEDATION permit issued 2026-09-12T10:00:00Z, then failed
    correctably on a re-inspection scored at 2026-09-13T10:00:00Z."""
    env = setup_permitted_practice("MODERATE_SEDATION", clock=CLOCK)
    assert env["permit"]["status"] == "ACTIVE"
    assert_instant_equals(env["permit"]["issued_at"], "2026-09-12T10:00:00Z")
    second = schedule_inspection(env["permit"]["id"], "2026-09-13T10:00:00Z")
    set_env_clock(env, "2026-09-13T10:00:00Z")
    # Five major deficiencies cost 35 points: a score of 65, below the 70 floor.
    result = record_inspection_result(second["id"], 0, 5, 0)
    env["permit"] = fetch_permit(env["permit"]["id"])
    env["practice"] = fetch_practice(env["practice_id"])
    return env, result


def test_failed_correctable_reinspection_drops_a_live_permit_to_probation(api):
    """PRD 3.2: "A `FAILED_CORRECTABLE` result against an `ACTIVE` permit drops it
    to `PROBATION` with `last_enforcement_reason` `DEFICIENCY_SCORE`, increases
    `probation_count` by 1, sets `remediation_deadline_at` to the logical clock plus
    30 days, moves the privilege to `RESTRICTED`, and defers the practice's
    `CLEARED` `DEEP_SEDATION_GENERAL` cases."
    PRD 3.2: "The score starts at 100; each minor deficiency costs 2 points, each
    major deficiency costs 7 points, and each critical deficiency costs 25 points."
    PRD 3.2: "Booking a routine or complaint inspection while the permit is
    `ACTIVE`, on `PROBATION`, or `SUSPENDED` creates the `SCHEDULED` inspection and
    leaves the permit's `status` untouched — a re-inspection does not reopen a
    permit."

    Design: Difficulty/non_linear_state_machine/permit_probation_remediation_cycle
    """
    env, result = _permit_on_probation()

    assert result["inspection_score"] == 65, (
        f"100 less five major deficiencies at 7 points each is 65, got {result['inspection_score']}"
    )
    assert result["status"] == "FAILED_CORRECTABLE"

    permit = env["permit"]
    assert permit["status"] == "PROBATION"
    assert permit["probation_count"] == 1
    assert permit["last_enforcement_reason"] == "DEFICIENCY_SCORE"
    assert_instant_equals(
        permit["remediation_deadline_at"], "2026-10-13T10:00:00Z",
        f"thirty days after the 2026-09-13T10:00:00Z result, got {permit['remediation_deadline_at']}",
    )
    assert_instant_equals(
        permit["issued_at"], "2026-09-12T10:00:00Z",
        "the probation loop does not restamp the issue instant",
    )
    assert_instant_equals(
        permit["expires_at"], "2028-09-12T10:00:00Z",
        "the term is 24 calendar months from issue and the loop never touches it",
    )
    assert env["practice"]["sedation_privilege_state"] == "RESTRICTED"


def test_remediation_returns_to_active_without_resetting_the_history(api):
    """PRD 3.2: "A successful attestation returns the permit to `ACTIVE`, clears both
    `remediation_deadline_at` and `last_enforcement_reason` to null, restores
    `sedation_privilege_state` from `RESTRICTED` to `PERMITTED` — which reopens
    `DEEP_SEDATION_GENERAL` scheduling — and increments the practice's `version`."
    PRD 3.2: "`probation_count` is permanent history and is never decremented, so a
    permit reinstated twice still reports a count of 2."
    PRD 2.10: "Nor does reinstatement extend the permit term — `expires_at` is
    stamped once and is never moved by remediation or re-inspection."

    The permit reaches ACTIVE for the second time carrying different surrounding
    fields than it did the first time.

    Design: Difficulty/non_linear_state_machine/permit_probation_remediation_cycle
    """
    env, _ = _permit_on_probation()

    response = api_client.remediate_permit(
        env["permit"]["id"], {"attestation_note": "All five findings corrected."}, ADMIN
    )
    remediated = validate_success(response)

    assert remediated["status"] == "ACTIVE"
    assert remediated["remediation_deadline_at"] is None
    assert remediated["last_enforcement_reason"] is None
    assert remediated["probation_count"] == 1, (
        f"the backward edge never decrements the history counter, got {remediated['probation_count']}"
    )
    assert_instant_equals(
        remediated["expires_at"], "2028-09-12T10:00:00Z",
        "reinstatement does not extend the term",
    )
    assert fetch_practice(env["practice_id"])["sedation_privilege_state"] == "PERMITTED"


# --- case_scheduling_and_clearance_dimensions_advance_independently ------------

def _case_holding_a_four_hour_block():
    """A MODERATE_SEDATION implant case of 60 minutes holding a 240-minute block,
    with the clock moved to the morning of surgery."""
    env = setup_permitted_practice("MODERATE_SEDATION", clock=CLOCK)
    block = create_block(
        env["practice_id"], env["surgeon"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
    )
    case = draft_case(
        env,
        planned_anesthesia_level="MODERATE_SEDATION",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="IMPLANT",
    )
    hold_case_on_block(case["id"], block["id"])
    set_env_clock(env, "2026-09-14T12:00:00Z")
    return env, case, block


def test_clearance_dimension_advances_twice_while_scheduling_stands_still(api):
    """PRD 3.5: "Signature stamps `signed_at` with the logical clock, recomputes
    `provisional_risk_score` and re-derives `risk_band` from it against the case's
    *current* `planned_anesthesia_level` (so a case whose planned depth changed
    between drafting and signature is rescored, not left stale), advances the
    evaluation from `DRAFT` to `SIGNED`, moves the case's `clearance_status` from
    `NOT_EVALUATED` to `EVALUATED`, and increments the case's `version`."
    PRD 3.5: "`CLEAR` moves the case's `clearance_status` from `EVALUATED` to
    `CLEARED`, which is the only route to a confirmable case."

    Opening, signing and CLEAR-verifying all move the clearance dimension while
    `scheduling_status` sits at `BLOCK_HELD` throughout.

    Design: Difficulty/non_linear_state_machine/case_scheduling_and_clearance_dimensions_advance_independently
    """
    env, case, block = _case_holding_a_four_hour_block()

    evaluation = create_evaluation_for(env, case["id"], env["monitor"]["id"])
    after_open = fetch_case(case["id"])
    assert after_open["scheduling_status"] == "BLOCK_HELD"
    assert after_open["clearance_status"] == "NOT_EVALUATED"

    signed = sign_evaluation_as(evaluation["id"], env["monitor"]["id"])
    after_sign = fetch_case(case["id"])
    assert signed["status"] == "SIGNED"
    assert signed["provisional_risk_score"] == pytest.approx(20.0, abs=0.01)
    assert signed["risk_band"] == "LOW"
    assert after_sign["clearance_status"] == "EVALUATED"
    assert after_sign["scheduling_status"] == "BLOCK_HELD", (
        "signing an evaluation is not a scheduling act"
    )

    verified = verify_evaluation_as(
        env, evaluation["id"], intent="CLEAR",
        solids_minutes_ago=480, clears_minutes_ago=120,
    )
    after_verify = fetch_case(case["id"])
    assert verified["status"] == "VERIFIED"
    assert verified["final_risk_score"] == pytest.approx(20.0, abs=0.01)
    assert verified["npo_solids_minutes"] == 480
    assert verified["npo_clears_minutes"] == 120
    assert after_verify["clearance_status"] == "CLEARED"
    assert after_verify["scheduling_status"] == "BLOCK_HELD", (
        "clearance reached CLEARED with the scheduling dimension untouched"
    )


def test_confirmation_advances_scheduling_while_clearance_stands_still(api):
    """PRD 3.4: "A confirmation that survives all eleven gates advances the case's
    `scheduling_status` from `BLOCK_HELD` to `CONFIRMED` and increments the case's
    `version`."
    PRD 3.4: "The parent block's `utilization_pct` is re-published against the
    confirmed roster and the block's `version` increments as well — the minutes
    themselves were already committed at hold time and do not move again, so
    `committed_minutes` and `open_minutes` are unchanged by confirmation."

    The two dimensions meet only in the confirm precondition: 60 committed minutes
    of a 240-minute block leave 180 open at 25.00 percent.

    Design: Difficulty/non_linear_state_machine/case_scheduling_and_clearance_dimensions_advance_independently
    """
    env, case, block = _case_holding_a_four_hour_block()
    evaluation = create_evaluation_for(env, case["id"], env["monitor"]["id"])
    sign_evaluation_as(evaluation["id"], env["monitor"]["id"])
    verify_evaluation_as(
        env, evaluation["id"], intent="CLEAR",
        solids_minutes_ago=480, clears_minutes_ago=120,
    )

    confirmed = confirm_case(case["id"], block["id"])

    assert confirmed["scheduling_status"] == "CONFIRMED"
    assert confirmed["clearance_status"] == "CLEARED", (
        "confirmation is a scheduling act and leaves the clearance dimension alone"
    )
    ledger = fetch_block(block["id"])
    assert ledger["committed_minutes"] == 60
    assert ledger["open_minutes"] == 180
    assert float(ledger["utilization_pct"]) == pytest.approx(25.00, abs=0.001)
    assert fetch_evaluation(evaluation["id"])["status"] == "VERIFIED"


# --- adverse_event_fork_join_regulator_track ----------------------------------

def _severe_event_signed_off():
    """A SEVERE event reported one hour after it occurred — inside the 72-hour
    deadline — whose morbidity review has been opened and signed off."""
    env = setup_practice_with_roster(clock=CLOCK)
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        with_monitor=False,
    )
    event = file_adverse_event(
        env, case["id"], severity="SEVERE", event_type="UNPLANNED_INTUBATION",
        occurred_at="2026-09-11T09:00:00Z",
    )
    opened = open_morbidity_review(env, event["id"], env["reviewer"]["id"])
    signed_off = sign_off_morbidity_review(
        event["id"], env["reviewer"]["id"], corrective_action_required=True
    )
    return env, case, event, opened, signed_off


def test_closure_is_refused_while_the_regulator_track_has_not_completed(api):
    """PRD 3.9: "`reporting_deadline_at` is `occurred_at` plus 24 hours for a
    `SENTINEL` event, plus 72 hours for a `SEVERE` one, plus 7 days for a `MODERATE`
    one, and plus 30 days for a `MINOR` one."
    PRD 3.9: "The event must be in `REVIEW_SIGNED_OFF`, and the join condition is
    that an event whose `severity` is `SEVERE` or `SENTINEL` must already have
    `regulator_notified` true; a signed-off severe event with no recorded
    notification is refused with `ERR_REGULATOR_NOTIFICATION_REQUIRED` (HTTP 409),
    while `MINOR` and `MODERATE` events may close with the flag still false."

    Design: Difficulty/non_linear_state_machine/adverse_event_fork_join_regulator_track
    """
    env, case, event, opened, signed_off = _severe_event_signed_off()

    assert_instant_equals(event["reporting_deadline_at"], "2026-09-14T09:00:00Z")
    assert event["late_report"] is False
    assert fetch_practice(env["practice_id"])["open_adverse_event_count"] == 1
    assert opened["status"] == "UNDER_MORBIDITY_REVIEW"
    assert opened["reviewer_staff_id"] == env["reviewer"]["id"]
    assert signed_off["status"] == "REVIEW_SIGNED_OFF"
    assert signed_off["corrective_action_required"] is True
    assert signed_off["regulator_notified"] is False

    response = api_client.close_adverse_event(
        event["id"], {}, make_quality_reviewer_headers(env["reviewer"]["id"])
    )
    validate_error(response, "ERR_REGULATOR_NOTIFICATION_REQUIRED", 409)
    assert fetch_adverse_event(event["id"])["status"] == "REVIEW_SIGNED_OFF", (
        "the refused closure leaves the review status exactly where it stood"
    )


def test_regulator_notification_is_a_self_loop_that_unblocks_the_join(api):
    """PRD 3.9: "Recording it sets `regulator_notified` to true and increments the
    event's `version`, and it deliberately does **not** advance `status`."
    PRD 3.9: "Closure moves `status` to the terminal `CLOSED`, recomputes the
    practice's `open_adverse_event_count` so this event drops out of it, and
    increments the practice's `version`."

    Design: Difficulty/non_linear_state_machine/adverse_event_fork_join_regulator_track
    """
    env, case, event, opened, signed_off = _severe_event_signed_off()

    notified = record_regulator_notification(env, event["id"])
    assert notified["regulator_notified"] is True
    assert notified["status"] == "REVIEW_SIGNED_OFF", (
        f"the notification track never advances the review status, got {notified['status']}"
    )
    assert notified["version"] > signed_off["version"]

    closed = close_adverse_event(env, event["id"], env["reviewer"]["id"])
    assert closed["status"] == "CLOSED"
    assert fetch_practice(env["practice_id"])["open_adverse_event_count"] == 0
