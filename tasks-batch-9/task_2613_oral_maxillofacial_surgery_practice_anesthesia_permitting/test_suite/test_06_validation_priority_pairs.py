"""Ordered refusals: when one request violates two rules at once, only the
higher-priority error may surface."""
import pytest

from test_helpers import (
    ADMIN,
    SCHEDULER,
    api_client,
    apply_permit,
    clear_case,
    create_block,
    create_evaluation_for,
    create_staff,
    day_of_verification_payload,
    draft_case,
    fetch_block,
    fetch_case,
    fetch_evaluation,
    fetch_permit,
    fetch_practice,
    hold_case_on_block,
    log_drill,
    make_anesthesia_coordinator_headers,
    record_inspection_result,
    schedule_inspection,
    set_env_clock,
    setup_practice_with_roster,
    shift,
    sign_evaluation_as,
    validate_error,
    verify_evaluation_as,
)

CLOCK = "2026-09-11T10:00:00Z"
DAY_OF = "2026-09-14T12:00:00Z"

# --- drill_safety_59_beats_prerequisite_constraint_70 --------------------------


def _case_violating_drills_and_prerequisite():
    """A CLEARED MODERATE_SEDATION case whose office covers only two of its four
    required drill types and whose staged predecessor is still DRAFT."""
    env = setup_practice_with_roster(clock=CLOCK)
    participants = [env["surgeon"]["id"], env["monitor"]["id"]]
    for drill_type in ("AIRWAY_OBSTRUCTION", "LOCAL_ANESTHETIC_TOXICITY"):
        log_drill(env["practice_id"], drill_type, CLOCK, participants)
    permit = apply_permit(env["practice_id"], "MODERATE_SEDATION", CLOCK)
    inspection = schedule_inspection(permit["id"], "2026-09-12T10:00:00Z")
    set_env_clock(env, "2026-09-12T10:00:00Z")
    record_inspection_result(inspection["id"], 0, 0, 0)
    env["permit"] = fetch_permit(permit["id"])

    prerequisite = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-13T09:00:00Z",
        planned_end="2026-09-13T10:00:00Z",
        with_monitor=False,
    )
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
        prerequisite_case_id=prerequisite["id"],
    )
    hold_case_on_block(case["id"], block["id"])
    set_env_clock(env, DAY_OF)
    clear_case(env, case["id"])
    return env, case, block, prerequisite


def test_the_drill_safety_gate_outranks_the_prerequisite_constraint(api):
    """PRD 3.4: "Sixth, the open permit's `drill_compliance_ratio`, recomputed at that
    instant, must be at or above 0.75, or the answer is `ERR_DRILL_COMPLIANCE_LAPSED`
    (HTTP 409) — drills that quietly aged out of the trailing 365-day window stop the
    schedule here, before any sweep has run."
    PRD 3.4: "Eighth, if the case carries a `prerequisite_case_id`, that predecessor's
    `scheduling_status` must be `COMPLETED`; a predecessor still in flight is refused
    with `ERR_PREREQUISITE_CASE_INCOMPLETE` (HTTP 409)."
    PRD 3.4: "Because so many rules converge here, their order is normative and is
    stated in full below; the first violated rule decides the response."

    Design: Difficulty/priority_pair_validation_conflict/drill_safety_59_beats_prerequisite_constraint_70
    """
    env, case, block, prerequisite = _case_violating_drills_and_prerequisite()

    permit = env["permit"]
    assert permit["status"] == "PROBATION"
    assert permit["last_enforcement_reason"] == "DRILL_LAPSE"
    assert float(permit["drill_compliance_ratio"]) == pytest.approx(0.50, abs=0.001)
    assert fetch_practice(env["practice_id"])["sedation_privilege_state"] == "RESTRICTED"
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"
    assert fetch_case(prerequisite["id"])["scheduling_status"] == "DRAFT"

    block_before = fetch_block(block["id"])
    response = api_client.confirm_case(
        case["id"], {"expected_block_version": block_before["version"]}, SCHEDULER
    )
    validate_error(response, "ERR_DRILL_COMPLIANCE_LAPSED", 409)

    assert fetch_case(case["id"])["scheduling_status"] == "BLOCK_HELD"
    assert fetch_block(block["id"])["version"] == block_before["version"], (
        "a rejected confirmation writes nothing"
    )


def test_the_prerequisite_constraint_surfaces_once_drills_are_restored(api):
    """PRD 3.2: "Count the distinct drill types among the qualifying drills — a type
    rehearsed five times counts once, and a type outside the required set counts not
    at all — divide that count by the number of types in the required set, and round
    the quotient half-up to two decimal places."
    PRD 3.2: "A successful attestation returns the permit to `ACTIVE`, clears both
    `remediation_deadline_at` and `last_enforcement_reason` to null, restores
    `sedation_privilege_state` from `RESTRICTED` to `PERMITTED` — which reopens
    `DEEP_SEDATION_GENERAL` scheduling — and increments the practice's `version`."
    PRD 3.4: "Eighth, if the case carries a `prerequisite_case_id`, that predecessor's
    `scheduling_status` must be `COMPLETED`; a predecessor still in flight is refused
    with `ERR_PREREQUISITE_CASE_INCOMPLETE` (HTTP 409)."

    The same confirmation call now answers the lower-priority constraint error, which
    proves the two rules are ordered rather than one of them being dead.

    Design: Difficulty/priority_pair_validation_conflict/drill_safety_59_beats_prerequisite_constraint_70
    """
    env, case, block, prerequisite = _case_violating_drills_and_prerequisite()
    participants = [env["surgeon"]["id"], env["monitor"]["id"]]
    for drill_type in ("LARYNGOSPASM", "CARDIAC_ARREST"):
        log_drill(env["practice_id"], drill_type, env["clock"], participants)
    assert float(fetch_permit(env["permit"]["id"])["drill_compliance_ratio"]) == (
        pytest.approx(1.00, abs=0.001)
    )

    remediated = api_client.remediate_permit(
        env["permit"]["id"], {"attestation_note": "Both missing drills rehearsed."},
        ADMIN,
    )
    assert remediated.status_code == 200, remediated.text
    assert fetch_permit(env["permit"]["id"])["status"] == "ACTIVE"
    assert fetch_practice(env["practice_id"])["sedation_privilege_state"] == "PERMITTED"

    block_before = fetch_block(block["id"])
    response = api_client.confirm_case(
        case["id"], {"expected_block_version": block_before["version"]}, SCHEDULER
    )
    validate_error(response, "ERR_PREREQUISITE_CASE_INCOMPLETE", 409)
    assert fetch_case(case["id"])["scheduling_status"] == "BLOCK_HELD"
    assert fetch_block(block["id"])["version"] == block_before["version"]


# --- referential_75_beats_temporal_76_on_hold_block ----------------------------

def _two_surgeon_room_collision():
    """Two blocks in OR-1 over the same window, one per surgeon. The incumbent case
    holds surgeon one's block; the candidate belongs to surgeon two and starts only
    five minutes after the incumbent ends."""
    env = setup_practice_with_roster(clock=CLOCK, turnover_buffer_minutes=15)
    second_surgeon = create_staff(
        env["practice_id"], "SURGEON", "Dr Beth Okafor",
        acls_expires_on="2027-06-30T00:00:00Z",
    )
    block_a = create_block(
        env["practice_id"], env["surgeon"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
    )
    block_b = create_block(
        env["practice_id"], second_surgeon["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
    )
    incumbent = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        with_monitor=False,
    )
    hold_case_on_block(incumbent["id"], block_a["id"])
    candidate = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T14:05:00Z",
        planned_end="2026-09-14T15:00:00Z",
        primary_surgeon_id=second_surgeon["id"],
        with_monitor=False,
    )
    return env, candidate, block_a, block_b, incumbent


def test_block_surgeon_mismatch_outranks_the_room_turnover_conflict(api):
    """PRD 3.4: "The case's `primary_surgeon_id` must equal the block's `surgeon_id`,
    since a block belongs to one surgeon; a mismatch is `ERR_BLOCK_SURGEON_MISMATCH`
    (HTTP 409). Then comes the turnover test, and finally the capacity test."
    PRD 3.4: "the request is evaluated through six gates in ascending order"

    Design: Difficulty/priority_pair_validation_conflict/referential_75_beats_temporal_76_on_hold_block
    """
    env, candidate, block_a, block_b, incumbent = _two_surgeon_room_collision()

    response = api_client.hold_block(
        candidate["id"], {"block_id": block_a["id"]}, SCHEDULER
    )
    validate_error(response, "ERR_BLOCK_SURGEON_MISMATCH", 409)

    unchanged = fetch_case(candidate["id"])
    assert unchanged["scheduling_status"] == "DRAFT"
    assert unchanged["block_id"] is None
    assert fetch_block(block_a["id"])["committed_minutes"] == 60
    assert fetch_block(block_b["id"])["committed_minutes"] == 0


def test_the_turnover_conflict_surfaces_on_the_correct_surgeons_block(api):
    """PRD 3.4: "The consequence is that a gap shorter than the buffer is a conflict
    while a gap exactly equal to the buffer is not: with the default 15-minute buffer,
    a new case starting 15 minutes after an incumbent ends is admitted, and one
    starting 14 minutes after is refused with `ERR_ROOM_TURNOVER_CONFLICT` (HTTP 409)."
    PRD 3.4: "No other case of the same practice in the same `room_code` whose
    `scheduling_status` is `BLOCK_HELD`, `CONFIRMED`, `IN_RECOVERY`, or `COMPLETED` may
    overlap this case's window once the buffer is appended"

    A five-minute gap is shorter than the fifteen-minute buffer, so the same hold that
    previously answered the referential error now answers the temporal one.

    Design: Difficulty/priority_pair_validation_conflict/referential_75_beats_temporal_76_on_hold_block
    """
    env, candidate, block_a, block_b, incumbent = _two_surgeon_room_collision()

    response = api_client.hold_block(
        candidate["id"], {"block_id": block_b["id"]}, SCHEDULER
    )
    validate_error(response, "ERR_ROOM_TURNOVER_CONFLICT", 409)

    unchanged = fetch_case(candidate["id"])
    assert unchanged["scheduling_status"] == "DRAFT"
    assert unchanged["block_id"] is None
    assert fetch_block(block_b["id"])["committed_minutes"] == 0, (
        "no rejected hold left a partial write on the ledger"
    )


# --- auth_9_beats_fasting_safety_62 --------------------------------------------

def _signed_minimal_sedation_evaluation():
    """A SIGNED evaluation on a MINIMAL_SEDATION case, with the clock moved to the
    morning of surgery."""
    env = setup_practice_with_roster(clock=CLOCK)
    case = draft_case(
        env,
        planned_anesthesia_level="MINIMAL_SEDATION",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="THIRD_MOLAR",
    )
    evaluation = create_evaluation_for(env, case["id"], env["monitor"]["id"])
    sign_evaluation_as(evaluation["id"], env["monitor"]["id"])
    set_env_clock(env, DAY_OF)
    return env, case, evaluation


def _verification_payload(escort_confirmed, solids_minutes_ago):
    return day_of_verification_payload(
        "CLEAR",
        shift(DAY_OF, minutes=-solids_minutes_ago),
        shift(DAY_OF, minutes=-120),
        escort_confirmed=escort_confirmed,
        escort_name="Ada Escort" if escort_confirmed else None,
    )


def test_segregation_of_duties_outranks_both_clinical_gates(api):
    """PRD 3.5: "Three access conditions precede everything: the evaluation must be in
    `SIGNED`, the parent case must be neither `COMPLETED` nor `CANCELLED`, and the
    acting `X-User-ID` must be neither the evaluation's `evaluator_staff_id` nor the
    case's `primary_surgeon_id` — the office may not have one person write, verify, and
    operate. A violation of either identity rule is `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.5: "The gates then run only when `intent` is `CLEAR`, in ascending order."

    The author's own attempt fasted only 300 minutes and confirmed no escort, so the
    fasting and escort gates are violated too, yet the identity rule answers first.

    Design: Difficulty/priority_pair_validation_conflict/auth_9_beats_fasting_safety_62
    """
    env, case, evaluation = _signed_minimal_sedation_evaluation()

    response = api_client.verify_evaluation(
        evaluation["id"],
        _verification_payload(escort_confirmed=False, solids_minutes_ago=300),
        make_anesthesia_coordinator_headers(env["monitor"]["id"]),
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)

    assert fetch_evaluation(evaluation["id"])["status"] == "SIGNED"
    assert fetch_case(case["id"])["clearance_status"] == "EVALUATED"


def test_the_clinical_gates_then_peel_off_in_their_own_order(api):
    """PRD 3.5: "First fasting: for any case whose `planned_anesthesia_level` is above
    `LOCAL_ONLY`, `npo_solids_minutes` must be at least 480 — eight hours without
    solids — and `npo_clears_minutes` at least 120, two hours without clear liquids; a
    shortfall in either is `ERR_FASTING_REQUIREMENT_UNMET` (HTTP 409)."
    PRD 3.5: "Then escort: again for any level above `LOCAL_ONLY`, `escort_confirmed`
    must be true and `escort_name` must be non-empty, since a sedated patient may not
    be discharged without a responsible adult; otherwise the answer is
    `ERR_ESCORT_REQUIRED` (HTTP 409)."
    PRD 3.5: "`final_risk_score` and `risk_band` are recomputed by the final variant
    **before** any gate is evaluated, so the published score reflects reality even on a
    rejected attempt."

    Design: Difficulty/priority_pair_validation_conflict/auth_9_beats_fasting_safety_62
    """
    env, case, evaluation = _signed_minimal_sedation_evaluation()
    verifier_headers = make_anesthesia_coordinator_headers(env["verifier"]["id"])

    short_fast = api_client.verify_evaluation(
        evaluation["id"],
        _verification_payload(escort_confirmed=False, solids_minutes_ago=300),
        verifier_headers,
    )
    validate_error(short_fast, "ERR_FASTING_REQUIREMENT_UNMET", 409)

    no_escort = api_client.verify_evaluation(
        evaluation["id"],
        _verification_payload(escort_confirmed=False, solids_minutes_ago=480),
        verifier_headers,
    )
    validate_error(no_escort, "ERR_ESCORT_REQUIRED", 409)

    assert fetch_evaluation(evaluation["id"])["status"] == "SIGNED"
    assert fetch_case(case["id"])["clearance_status"] == "EVALUATED"

    verified = verify_evaluation_as(
        env, evaluation["id"], intent="CLEAR",
        solids_minutes_ago=480, clears_minutes_ago=120,
    )
    assert verified["status"] == "VERIFIED"
    assert verified["npo_solids_minutes"] == 480
    assert verified["npo_clears_minutes"] == 120
    assert verified["final_risk_score"] == pytest.approx(16.0, abs=0.01), (
        "20 base points scaled by the MINIMAL_SEDATION multiplier of eight tenths"
    )
    assert verified["risk_band"] == "LOW"
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"
