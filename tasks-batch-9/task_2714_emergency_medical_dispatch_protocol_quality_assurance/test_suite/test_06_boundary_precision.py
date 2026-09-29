"""Numeric boundaries the PRD pins to a single decimal or a single second.

Three thresholds are exercised at the exact tick and one step past it: the
GOOD/WATCH posture boundary at ``target_compliance_pct``, the 120-second
first-compression limit that arms the late-compression cap, and the
``hours_owed_restriction_threshold`` that curtails a dispatcher's privilege.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2
from test_helpers.test_users import DIRECTOR, SUPERVISOR

WORKING_CLOCK = "2026-08-20T00:00:00Z"

# Four sections all landing on exactly 90.00, so the weighted composite is 90.0.
AT_TARGET_SECTIONS = {
    "case_entry": (18, 20),
    "key_questions": (27, 30),
    "pre_arrival": (9, 10),
    "final_coding": (9, 10),
}
# 90.00 / 90.00 / 88.00 / 93.33 -> weighted 89.8995 -> 89.9.
ONE_TENTH_BELOW_SECTIONS = {
    "case_entry": (18, 20),
    "key_questions": (27, 30),
    "pre_arrival": (22, 25),
    "final_coding": (28, 30),
}


def _two_dispatcher_posture_env(api):
    """Two dispatchers, one sheet each, both reviews scored and ready to finalize."""
    program = fx.new_program(api, target_compliance_pct=90.0, watch_floor_pct=80.0)
    fx.new_approved_version(api, program["id"], version_label="MPDS-13.0")
    dispatcher_a = fx.new_dispatcher(api, program["id"], employee_code="EMD-F01",
                                     full_name="Petra Alvi")
    dispatcher_b = fx.new_dispatcher(api, program["id"], employee_code="EMD-F02",
                                     full_name="Quinn Baros")
    fx.set_clock(api, WORKING_CLOCK)
    call_a = fx.ingest_call(api, dispatcher_a["id"], call_reference="C-F001",
                            received_at="2026-08-05T09:00:00Z")
    call_b = fx.ingest_call(api, dispatcher_b["id"], call_reference="C-F002",
                            received_at="2026-08-06T09:00:00Z")
    period = fx.new_period(api, program["id"], target_sample_count=2)
    review_a = fx.target(api, period["id"], call_a["id"], "NEW_HIRE_AUDIT")
    review_b = fx.target(api, period["id"], call_b["id"], "NEW_HIRE_AUDIT")
    fx.score(api, review_a["id"], sections=AT_TARGET_SECTIONS,
             reviewer_determinant_code="10-C-4",
             expected_review_version=review_a["version"])
    sheet_b = fx.score(api, review_b["id"], sections=ONE_TENTH_BELOW_SECTIONS,
                       reviewer_determinant_code="10-C-4",
                       expected_review_version=review_b["version"])
    return {
        "program_id": program["id"],
        "dispatcher_a_id": dispatcher_a["id"],
        "dispatcher_b_id": dispatcher_b["id"],
        "review_a_id": review_a["id"],
        "review_b_id": review_b["id"],
        "sheet_b": sheet_b,
    }


def test_composite_exactly_at_the_target_reads_compliant_and_a_good_posture(api):
    """PRD 3.7: "`compliant` is true when `final_composite_score` is at or above the
    programme's `target_compliance_pct` and false otherwise."
    PRD 3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is at
    or above the programme's `target_compliance_pct`, `WATCH` when it is below that but
    at or above `watch_floor_pct`, and `PROBATION` when it is below the watch floor; a
    dispatcher with no finalized reviews is `UNRATED`."
    PRD 3.8: "And if none of those clauses match, no plan is created at all — a
    dispatcher whose posture came out `GOOD` on an accurately coded case is left alone."

    Design: Difficulty/boundary_precision_check/posture_boundary_at_exactly_the_target_versus_one_tenth_below
    """
    env = _two_dispatcher_posture_env(api)

    finalized = validate_success(
        api.finalize_review(env["review_a_id"], {"finalization_note": "at target"}, SUPERVISOR)
    )
    assert finalized["pre_penalty_composite_score"] == approx1(90.0)
    assert finalized["penalty_points"] == approx1(0.0)
    assert finalized["final_composite_score"] == approx1(90.0)
    assert finalized["compliant"] is True

    dispatcher = fx.get_dispatcher(api, env["dispatcher_a_id"])
    assert dispatcher["reviewed_case_count"] == 1
    assert dispatcher["compliance_points_total"] == approx1(90.0)
    assert dispatcher["compliance_pct"] == approx1(90.0)
    assert dispatcher["compliance_posture"] == "GOOD"
    assert dispatcher["remediation_hours_owed"] == approx2(0.00)
    assert dispatcher["dispatch_privilege"] == "FULL"

    plans = fx.list_plans_for(api, env["dispatcher_a_id"])
    assert plans == [], f"a GOOD posture on an accurate code must create no plan, got {plans}"


def test_composite_one_tenth_below_the_target_reads_watch_and_coaches_the_weakest_section(api):
    """PRD 3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is at
    or above the programme's `target_compliance_pct`, `WATCH` when it is below that but
    at or above `watch_floor_pct`, and `PROBATION` when it is below the watch floor; a
    dispatcher with no finalized reviews is `UNRATED`."
    PRD 3.8: "Otherwise, when the posture is `WATCH`, the plan is `ADVISORY` and targets
    the weakest section."
    PRD 3.8: ""The weakest section" means the lowest of the four section percentages on
    the review's current sheet, mapping `case_entry_pct` to `CASE_ENTRY`,
    `key_questions_pct` to `KEY_QUESTIONS`, `pre_arrival_pct` to
    `PRE_ARRIVAL_INSTRUCTIONS`, and `final_coding_pct` to `FINAL_CODING`."

    Design: Difficulty/boundary_precision_check/posture_boundary_at_exactly_the_target_versus_one_tenth_below
    """
    env = _two_dispatcher_posture_env(api)

    finalized = validate_success(
        api.finalize_review(
            env["review_b_id"], {"finalization_note": "one tenth below target"}, SUPERVISOR
        )
    )
    assert finalized["pre_penalty_composite_score"] == approx1(89.9)
    assert finalized["penalty_points"] == approx1(0.0)
    assert finalized["final_composite_score"] == approx1(89.9)
    assert finalized["compliant"] is False

    dispatcher = fx.get_dispatcher(api, env["dispatcher_b_id"])
    assert dispatcher["compliance_pct"] == approx1(89.9)
    assert dispatcher["compliance_posture"] == "WATCH"
    assert dispatcher["remediation_hours_owed"] == approx2(2.00)
    assert dispatcher["dispatch_privilege"] == "FULL"

    plans = fx.list_plans_for(api, env["dispatcher_b_id"])
    assert len(plans) == 1, f"a WATCH posture must yield exactly one plan, got {plans}"
    plan = plans[0]
    assert plan["origin"] == "AUTO"
    assert plan["severity"] == "ADVISORY"
    assert plan["severity_rank"] == 1
    assert plan["focus_area"] == "PRE_ARRIVAL_INSTRUCTIONS"
    assert plan["required_hours"] == approx1(2.0)


def test_section_percentages_are_rounded_before_the_composite_is_formed(api):
    """PRD 2.6: "Section percentages are rounded to 2 decimal places first, and the
    composite is then computed from those already-rounded percentages and rounded once
    to 1 decimal place."
    PRD 3.5: "The sheet's `provisional_composite_score` is then the arithmetic mean of
    those four already-rounded percentages, rounded half up to 1 decimal place — under
    this view each of the four sections contributes exactly one quarter, regardless of
    the weights on the pinned protocol version, and no determinant penalty is applied."

    Design: Difficulty/boundary_precision_check/posture_boundary_at_exactly_the_target_versus_one_tenth_below
    """
    env = _two_dispatcher_posture_env(api)
    sheet = env["sheet_b"]

    assert sheet["case_entry_pct"] == approx2(90.00)
    assert sheet["key_questions_pct"] == approx2(90.00)
    assert sheet["pre_arrival_pct"] == approx2(88.00)
    assert sheet["final_coding_pct"] == approx2(93.33)
    # The unweighted mean of the four rounded percentages sits above the target even
    # though the weighted composite computed at finalization falls below it.
    assert sheet["provisional_composite_score"] == approx1(90.3)

    finalized = validate_success(
        api.finalize_review(env["review_b_id"], {"finalization_note": "weighted"}, SUPERVISOR)
    )
    assert finalized["pre_penalty_composite_score"] == approx1(89.9)


def _dacpr_env(api, time_to_first_compression_sec, recognition_time_sec=10,
               outcome_category="ROSC_FIELD"):
    """A CARDIAC_ARREST case with a bystander already compressing, DA-CPR scored."""
    return fx.high_risk_scored_env(
        api,
        dacpr_overrides={
            "cardiac_arrest_recognized": True,
            "recognition_time_sec": recognition_time_sec,
            "time_to_first_compression_sec": time_to_first_compression_sec,
            "dacpr_instructions_delivered": True,
            "compressions_coached": True,
        },
        call_overrides={"bystander_cpr_in_progress": True},
        outcome_category=outcome_category,
        program_overrides={"high_risk_target_pct": 85.0},
    )


def test_first_compression_at_exactly_120_seconds_is_compliant_and_uncapped(api):
    """PRD 3.6: "`compression_compliant` is true when `time_to_first_compression_sec` is
    at or below 120 seconds — exactly 120 seconds is compliant."
    PRD 3.6: "One cap then applies after the rounding: when `compression_compliant` is
    false, a late first compression caps the index at 50.0 no matter how strong the rest
    of the performance was, so the stored `dacpr_index` becomes the lower of the rounded
    index and 50.0."
    PRD 3.6: "Finally `dacpr_pass` is true when `dacpr_index` is at or above 75.0 and
    false otherwise."

    Design: Difficulty/boundary_precision_check/compression_limit_at_120_versus_121_seconds_triggers_the_late_cap
    """
    env = _dacpr_env(api, 120)
    record = env["high_risk_review"]

    assert record["status"] == "DACPR_SCORED"
    assert record["compression_compliant"] is True, "120 seconds is at the limit, not past it"
    # Bystander weights 55 / 30 / 15 over sub-scores 88.888.. / 0.0 / 100.0.
    assert record["dacpr_index"] == approx1(63.9)
    assert record["dacpr_pass"] is False


def test_first_compression_at_121_seconds_caps_the_index_at_fifty(api):
    """PRD 3.6: "`compression_compliant` is true when `time_to_first_compression_sec` is
    at or below 120 seconds — exactly 120 seconds is compliant."
    PRD 3.6: "One cap then applies after the rounding: when `compression_compliant` is
    false, a late first compression caps the index at 50.0 no matter how strong the rest
    of the performance was, so the stored `dacpr_index` becomes the lower of the rounded
    index and 50.0."

    Design: Difficulty/boundary_precision_check/compression_limit_at_120_versus_121_seconds_triggers_the_late_cap
    """
    env = _dacpr_env(api, 121, outcome_category="NO_ROSC")
    record = env["high_risk_review"]

    assert record["status"] == "DACPR_SCORED"
    assert record["compression_compliant"] is False, "121 seconds is past the 120-second limit"
    # The honest weighted index is the same 63.9 as at 120 seconds; the cap replaces it.
    assert record["dacpr_index"] == approx1(50.0)
    assert record["dacpr_pass"] is False


def test_coaching_only_sign_off_is_permitted_when_the_capped_index_sits_on_the_floor(api):
    """PRD 3.6: "Classifying a case as coaching-only takes the record `DACPR_SCORED →
    COACHING_ONLY`, and it is gated: a record whose `dacpr_index` is below 50.0 is too
    poor a performance to close as a coaching matter, and an attempt to do so is refused
    with `ERR_SENTINEL_CLASSIFICATION_REQUIRED` — below that floor the classification
    must be `SENTINEL_EVENT`."
    PRD 3.6: "Exclusively on this branch, an `ADVISORY` automatic coaching plan carrying
    2.0 required hours and a `focus_area` of `DACPR` is created or upgraded **only when
    `dacpr_pass` is false**; when the case passed on the index, no plan is created at all."

    Design: Difficulty/boundary_precision_check/compression_limit_at_120_versus_121_seconds_triggers_the_late_cap
    """
    env = _dacpr_env(api, 121, outcome_category="NO_ROSC")
    assert env["high_risk_review"]["dacpr_index"] == approx1(50.0)

    signed = validate_success(
        api.sign_off_high_risk_review(
            env["high_risk_review_id"],
            f.sign_off_payload(
                "COACHING_ONLY",
                director_notes="Index sits exactly on the sentinel floor.",
            ),
            DIRECTOR,
        )
    )
    assert signed["status"] == "COACHING_ONLY", "50.0 is not below 50.0"
    assert signed["classification"] == "COACHING_ONLY"

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["sentinel_event_count"] == 0

    plans = fx.list_plans_for(api, env["dispatcher_id"])
    assert len(plans) == 1, f"a failing coaching-only case must yield one plan, got {plans}"
    assert plans[0]["severity"] == "ADVISORY"
    assert plans[0]["focus_area"] == "DACPR"
    assert plans[0]["required_hours"] == approx1(2.0)


def test_coaching_only_sign_off_is_refused_when_the_index_falls_below_the_floor(api):
    """PRD 3.6: "Classifying a case as coaching-only takes the record `DACPR_SCORED →
    COACHING_ONLY`, and it is gated: a record whose `dacpr_index` is below 50.0 is too
    poor a performance to close as a coaching matter, and an attempt to do so is refused
    with `ERR_SENTINEL_CLASSIFICATION_REQUIRED` — below that floor the classification
    must be `SENTINEL_EVENT`."
    PRD 3.6: "The recognition sub-score decays linearly against a 90-second limit: it is
    one hundred multiplied by the amount by which 90 seconds exceeds `recognition_time_sec`,
    divided by 90, with the shortfall treated as zero once the recognition time reaches or
    passes 90 seconds."

    Design: Difficulty/boundary_precision_check/compression_limit_at_120_versus_121_seconds_triggers_the_late_cap
    """
    env = _dacpr_env(api, 122, recognition_time_sec=60, outcome_category="NO_ROSC")
    record = env["high_risk_review"]

    # Recognition sub-score 100 * (90 - 60) / 90 = 33.33..; the weighted index is
    # already under the 50.0 cap, so the cap does not bind.
    assert record["compression_compliant"] is False
    assert record["dacpr_index"] == approx1(33.3)
    assert record["dacpr_pass"] is False

    response = api.sign_off_high_risk_review(
        env["high_risk_review_id"],
        f.sign_off_payload("COACHING_ONLY", director_notes="Attempting to close as coaching."),
        DIRECTOR,
    )
    validate_error(response, err.ERR_SENTINEL_CLASSIFICATION_REQUIRED)

    unchanged = fx.get_high_risk_review(api, env["review_id"], env["high_risk_review_id"])
    assert unchanged["status"] == "DACPR_SCORED"
    assert unchanged["classification"] is None


def _hours_ledger_env(api):
    """Two dispatchers, each owing 8.0 hours, with one session apiece to be completed."""
    program = fx.new_program(
        api, accreditation_body="STATE_OEMS", hours_owed_restriction_threshold=6.0
    )
    version = fx.new_approved_version(api, program["id"], version_label="MPDS-13.0")
    dispatcher_p = fx.new_dispatcher(api, program["id"], employee_code="EMD-H01",
                                     full_name="Tova Lindqvist")
    dispatcher_q = fx.new_dispatcher(api, program["id"], employee_code="EMD-H02",
                                     full_name="Ulric Mbeki")
    fx.set_clock(api, WORKING_CLOCK)
    plan_p = fx.new_coaching_plan(api, dispatcher_p["id"], severity="CRITICAL",
                                  focus_area="DETERMINANT_CODING")
    plan_q = fx.new_coaching_plan(api, dispatcher_q["id"], severity="CRITICAL",
                                  focus_area="DETERMINANT_CODING")
    session_p = fx.new_session(api, plan_p["id"], version["id"],
                               starts_at="2026-08-15T09:00:00Z",
                               ends_at="2026-08-15T11:00:00Z", modality="ONE_ON_ONE")
    session_q = fx.new_session(api, plan_q["id"], version["id"],
                               starts_at="2026-08-15T09:00:00Z",
                               ends_at="2026-08-15T10:45:00Z", modality="ONE_ON_ONE")
    return {
        "dispatcher_p_id": dispatcher_p["id"],
        "dispatcher_q_id": dispatcher_q["id"],
        "plan_p_id": plan_p["id"],
        "plan_q_id": plan_q["id"],
        "session_p_id": session_p["id"],
        "session_q_id": session_q["id"],
    }


def test_owing_exactly_the_restriction_threshold_leaves_the_dispatcher_at_full(api):
    """PRD 3.8: "Otherwise, when `remediation_hours_owed` is **strictly greater** than the
    programme's `hours_owed_restriction_threshold`, the privilege is `RESTRICTED` — owing
    exactly the threshold leaves a dispatcher at `FULL`."
    PRD 3.8: "For each open plan the shortfall is the plan's `required_hours` less its
    `credited_hours`, floored at 0.00 so that over-delivery on one plan can never offset
    another plan's shortfall; `remediation_hours_owed` is the sum of those per-plan
    shortfalls, rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/hours_owed_exactly_at_the_restriction_threshold_versus_a_quarter_hour_over
    """
    env = _hours_ledger_env(api)

    completed = validate_success(
        api.complete_retraining_session(
            env["session_p_id"], {"attendance_confirmed": True}, SUPERVISOR
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["duration_hours"] == approx2(2.00)

    plan = fx.get_plan(api, env["plan_p_id"])
    assert plan["credited_hours"] == approx2(2.00)
    assert plan["required_hours"] == approx1(8.0)
    assert plan["status"] == "IN_PROGRESS", "credit short of the requirement must not verify"

    dispatcher = fx.get_dispatcher(api, env["dispatcher_p_id"])
    assert dispatcher["remediation_hours_owed"] == approx2(6.00)
    assert dispatcher["dispatch_privilege"] == "FULL", "6.00 is not strictly greater than 6.0"


def test_owing_a_quarter_hour_over_the_threshold_restricts_the_dispatcher(api):
    """PRD 3.8: "Otherwise, when `remediation_hours_owed` is **strictly greater** than the
    programme's `hours_owed_restriction_threshold`, the privilege is `RESTRICTED` — owing
    exactly the threshold leaves a dispatcher at `FULL`."
    PRD 3.8: "A successful scheduling writes the session against its plan through
    `coaching_plan_id`, with `status` `SCHEDULED`, no `attendance_confirmed`, no
    `cancel_reason` and no `completed_at`, and computes `duration_hours` as the elapsed
    time from `starts_at` to `ends_at` expressed in hours — the elapsed seconds divided by
    3600 — rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/hours_owed_exactly_at_the_restriction_threshold_versus_a_quarter_hour_over
    """
    env = _hours_ledger_env(api)

    completed = validate_success(
        api.complete_retraining_session(
            env["session_q_id"], {"attendance_confirmed": True}, SUPERVISOR
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["duration_hours"] == approx2(1.75)

    plan = fx.get_plan(api, env["plan_q_id"])
    assert plan["credited_hours"] == approx2(1.75)
    assert plan["status"] == "IN_PROGRESS"

    dispatcher = fx.get_dispatcher(api, env["dispatcher_q_id"])
    assert dispatcher["remediation_hours_owed"] == approx2(6.25)
    assert dispatcher["dispatch_privilege"] == "RESTRICTED"


def test_the_privilege_split_is_attributable_to_the_hours_ledger_alone(api):
    """PRD 3.8: "`dispatch_privilege` is derived from three inputs — the owed-hours ledger,
    `certification_status`, and `sentinel_event_count` — and is re-evaluated after every
    recomputation of any of them."
    PRD 3.8: "Otherwise, when `remediation_hours_owed` is **strictly greater** than the
    programme's `hours_owed_restriction_threshold`, the privilege is `RESTRICTED` — owing
    exactly the threshold leaves a dispatcher at `FULL`."

    Design: Difficulty/boundary_precision_check/hours_owed_exactly_at_the_restriction_threshold_versus_a_quarter_hour_over
    """
    env = _hours_ledger_env(api)

    fx.complete_session(api, env["session_p_id"])
    fx.complete_session(api, env["session_q_id"])

    dispatcher_p = fx.get_dispatcher(api, env["dispatcher_p_id"])
    dispatcher_q = fx.get_dispatcher(api, env["dispatcher_q_id"])

    for dispatcher in (dispatcher_p, dispatcher_q):
        assert dispatcher["certification_status"] == "PROVISIONAL"
        assert dispatcher["sentinel_event_count"] == 0

    assert dispatcher_p["remediation_hours_owed"] == approx2(6.00)
    assert dispatcher_p["dispatch_privilege"] == "FULL"
    assert dispatcher_q["remediation_hours_owed"] == approx2(6.25)
    assert dispatcher_q["dispatch_privilege"] == "RESTRICTED"
