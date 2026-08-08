"""Care plans, their revision cycle, and five-item symptom assessments."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_care_plan,
    assert_instant_equals_offset,
    assert_symptom_assessment,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    INTAKE,
    NURSE,
    active_care_plan,
    draft_care_plan,
    enroll_patient,
    file_referral,
    file_symptom_assessment,
    read_care_plan,
    read_patient,
    register_patient,
)


# ---------------------------------------------------------------------------
# The plan cannot be put into service before the patient is enrolled
# ---------------------------------------------------------------------------
def test_activating_a_plan_for_a_still_referred_patient_is_an_invalid_state(api):
    """PRD 3.5: "Activating from `DRAFT → ACTIVE` requires the patient's
    `program_status` to be `ACTIVE` or `HOSPICE_ELECTED` — a plan cannot be put
    into service for a patient whose referral has not yet been accepted — and
    leaves `revision_number` at 0."
    PRD 2.5: "**State.** The target row is in a from-state that the requested
    transition declares. Otherwise `ERR_INVALID_STATE` (409). Applies to every
    state-changing endpoint."

    Design: Difficulty/cross_entity_state_dependency/care_plan_activation_requires_patient_past_referral
    """
    patient = register_patient(clock="2026-06-01T00:00:00Z", full_name="Nadia Ilves")
    file_referral(patient["id"])
    plan = draft_care_plan(patient["id"], plan_title="Initial comfort plan")

    rejected = api.activate_care_plan(plan["id"], {}, NURSE)
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE.value, 409)

    unchanged = read_care_plan(plan["id"])
    assert unchanged["status"] == "DRAFT"
    assert read_patient(patient["id"])["program_status"] == "REFERRED"


def test_accepting_the_referral_lets_the_identical_activation_succeed(api):
    """PRD 3.1: "Acceptance moves the referral `RECEIVED → ACCEPTED`, which is
    terminal, and simultaneously moves the patient `REFERRED → ACTIVE` on
    `program_status`, incrementing the patient's `version` by 1 — this is the
    moment the patient becomes a program participant."
    PRD 3.5: "Activating from `DRAFT → ACTIVE` requires the patient's
    `program_status` to be `ACTIVE` or `HOSPICE_ELECTED` — a plan cannot be put
    into service for a patient whose referral has not yet been accepted — and
    leaves `revision_number` at 0."

    Design: Difficulty/cross_entity_state_dependency/care_plan_activation_requires_patient_past_referral
    """
    patient = register_patient(clock="2026-06-01T00:00:00Z", full_name="Nadia Ilves")
    referral = file_referral(patient["id"])
    plan = draft_care_plan(patient["id"], plan_title="Initial comfort plan")

    validate_error(
        api.activate_care_plan(plan["id"], {}, NURSE),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    accepted = validate_success(
        api.decide_referral(referral["id"], {"decision": "ACCEPT"}, INTAKE)
    )
    assert accepted["status"] == "ACCEPTED"
    assert read_patient(patient["id"])["program_status"] == "ACTIVE"

    activated = validate_success(api.activate_care_plan(plan["id"], {}, NURSE))
    assert_care_plan(activated)
    assert activated["status"] == "ACTIVE"
    assert activated["revision_number"] == 0


# ---------------------------------------------------------------------------
# Listing and pagination
# ---------------------------------------------------------------------------
def test_care_plan_list_reports_total_count_and_has_more(api):
    """PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` is true
    exactly when rows remain beyond the returned page."
    PRD 2.3: "`limit` is the maximum number of rows to return; it defaults to 10,
    may be no smaller than 1 and no larger than 100."

    Design: Corner/entities/care_plan_list_pagination_reports_total_count_and_has_more
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Ben Sato")
    for title, problem in (("Plan A", "pain"), ("Plan B", "dyspnea"), ("Plan C", "nausea")):
        draft_care_plan(patient["id"], plan_title=title, problem_list=[problem])

    rows, meta = validate_paginated(
        api.list_care_plans(NURSE, params={"patient_id": patient["id"], "limit": 2, "offset": 0})
    )

    assert len(rows) == 2, f"limit 2 must return exactly two rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert {row["patient_id"] for row in rows} == {patient["id"]}


# ---------------------------------------------------------------------------
# The revision cycle
# ---------------------------------------------------------------------------
def test_two_revision_loops_leave_revision_number_at_two(api):
    """PRD 3.5: "Opening one moves the plan `ACTIVE → UNDER_REVISION`, replaces
    `problem_list` wholesale with the supplied `revised_problem_list`, increments
    the plan's `version` by 1, and requires `expected_care_plan_version` to match
    the plan's current `version` beforehand, as section 2.7 sets out."
    PRD 3.5: "The same activation operation also serves as the way back from a
    revision: `UNDER_REVISION → ACTIVE` increments `revision_number` by 1."

    Design: Corner/state_machines/care_plan_revision_cycle_increments_revision_number_twice
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Hedy Novak")
    plan = active_care_plan(patient["id"], plan_title="Comfort plan", problem_list=["pain"])

    revised = validate_success(
        api.revise_care_plan(
            plan["id"],
            {
                "expected_care_plan_version": plan["version"],
                "revised_problem_list": ["pain", "dyspnea"],
            },
            NURSE,
        )
    )
    assert revised["status"] == "UNDER_REVISION"
    validate_success(
        api.activate_care_plan(plan["id"], {"activation_note": "revision one accepted"}, NURSE)
    )

    current = read_care_plan(plan["id"])
    assert current["revision_number"] == 1

    validate_success(
        api.revise_care_plan(
            plan["id"],
            {
                "expected_care_plan_version": current["version"],
                "revised_problem_list": ["pain", "dyspnea", "delirium"],
            },
            NURSE,
        )
    )
    final = validate_success(
        api.activate_care_plan(plan["id"], {"activation_note": "revision two accepted"}, NURSE)
    )

    assert final["status"] == "ACTIVE"
    assert final["revision_number"] == 2
    assert len(final["problem_list"]) == 3, (
        "each revision replaces problem_list wholesale with the supplied list"
    )


# ---------------------------------------------------------------------------
# Item score bounds
# ---------------------------------------------------------------------------
def test_an_item_score_above_ten_is_a_request_shape_failure(api):
    """PRD 3.5: "Each carries `patient_id`, `care_plan_id`, a `reporter_type` of
    `SELF` or `PROXY`, and five item scores — `item_pain`, `item_dyspnea`,
    `item_nausea`, `item_anxiety` and `item_fatigue` — each an integer from 0 to
    10 inclusive."
    PRD 2.5: "**Request shape.** Every required body field is present; every field
    holds a value of its declared type; every enum-typed field carries a declared
    member of that enum; every bounded numeric field lies inside its declared
    range; and every datetime pair satisfies its ordering rule, meaning
    `scheduled_end` is strictly after `scheduled_start` and `delivery_window_end`
    is strictly after `delivery_window_start`. Otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/symptom_item_score_above_ten_returns_validation
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Eli Farrow")
    plan = active_care_plan(patient["id"], plan_title="Plan", problem_list=["pain"])

    rejected = api.create_symptom_assessment(
        f.symptom_assessment_payload(
            patient["id"],
            plan["id"],
            reporter_type="SELF",
            item_pain=11,
            item_dyspnea=2,
            item_nausea=2,
            item_anxiety=2,
            item_fatigue=2,
        ),
        NURSE,
    )
    validate_error(rejected, ApiErrorId.ERR_VALIDATION.value, 400)

    assert read_patient(patient["id"])["open_symptom_count"] == 0, (
        "a rejected assessment must not move the patient's open symptom counter"
    )


# ---------------------------------------------------------------------------
# The triage axis
# ---------------------------------------------------------------------------
def test_resolving_a_still_open_assessment_is_an_invalid_transition(api):
    """PRD 3.5: "`ACKNOWLEDGE` moves `OPEN → ACKNOWLEDGED` and leaves
    `escalation_status` exactly as it was. `RESOLVE` moves `ACKNOWLEDGED →
    RESOLVED`; it stamps `resolution_reason` as `ESCALATION_DISPOSITIONED` when
    the row's `escalation_status` is `DISPOSITIONED` and as `SYMPTOM_CONTROLLED`
    otherwise; it decrements the patient's `open_symptom_count` by 1; and it
    closes out the after-hours side by moving every on-call escalation naming this
    assessment and sitting in `DISPOSITIONED` to `CLOSED`."
    PRD 3.5: "The assessment is created with `triage_status` `OPEN` and
    `escalation_status` `NONE`, and the patient's `open_symptom_count` increments
    by 1."

    Design: Corner/state_machines/symptom_resolve_from_open_without_acknowledge_returns_invalid_state
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Mira Kaplan")
    plan = active_care_plan(patient["id"], plan_title="Plan", problem_list=["nausea"])
    assessment = file_symptom_assessment(
        patient["id"],
        plan["id"],
        reporter_type="SELF",
        item_pain=2,
        item_dyspnea=2,
        item_nausea=2,
        item_anxiety=1,
        item_fatigue=1,
    )
    assert_symptom_assessment(assessment)

    rejected = api.update_symptom_triage(assessment["id"], {"action": "RESOLVE"}, NURSE)
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_symptom_assessment(assessment["id"], NURSE))
    assert unchanged["triage_status"] == "OPEN"
    assert unchanged["distress_score"] == 16
    assert unchanged["severity_tier"] == "MILD"
    assert_instant_equals_offset(
        unchanged["response_due_at"],
        unchanged["created_at"],
        minutes=1440,
        label="SymptomAssessment.response_due_at",
    )
    assert read_patient(patient["id"])["open_symptom_count"] == 1


# ---------------------------------------------------------------------------
# Distress scoring
# ---------------------------------------------------------------------------
def test_self_and_proxy_reports_of_identical_items_score_differently(api):
    """PRD 3.5: "Under the `SELF` variant all five items carry equal weight: the
    objective sum plus the subjective sum, the whole doubled. Under the `PROXY`
    variant the subjective sum is first discounted to six tenths of its value — a
    weight of 0.6 — added to the undiscounted objective sum, and the total scaled
    by two and a half, a multiplier of 2.5."
    PRD 3.5: "Identical item scores therefore yield a different `distress_score`
    under `PROXY` than under `SELF`."

    Design: Corner/calculations/symptom_distress_self_and_proxy_variants_diverge_on_identical_items
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Otto Salmi")
    plan = active_care_plan(patient["id"], plan_title="Plan", problem_list=["pain"])

    items = dict(item_pain=6, item_dyspnea=6, item_nausea=6, item_anxiety=6, item_fatigue=6)
    self_report = file_symptom_assessment(
        patient["id"], plan["id"], reporter_type="SELF", **items
    )
    proxy_report = file_symptom_assessment(
        patient["id"], plan["id"], reporter_type="PROXY", **items
    )

    assert self_report["distress_score"] == 60, (
        f"(18 + 12) * 2 = 60, got {self_report['distress_score']}"
    )
    assert proxy_report["distress_score"] == 63, (
        f"(18 + 12*0.6) * 2.5 = 63, got {proxy_report['distress_score']}"
    )
    assert self_report["severity_tier"] == "MODERATE"
    assert proxy_report["severity_tier"] == "MODERATE"
    assert_instant_equals_offset(
        self_report["response_due_at"],
        self_report["created_at"],
        minutes=240,
        label="SymptomAssessment.response_due_at",
    )
    assert read_patient(patient["id"])["open_symptom_count"] == 2


def test_severity_tier_floors_are_inclusive_and_ceilings_exclusive(api):
    """PRD 3.5: "`severity_tier` reads off the resulting `distress_score` against
    three floors, every floor inclusive and every ceiling exclusive. A score of 70
    or more is `SEVERE`. A score of at least 40 but below 70 is `MODERATE`. A
    score of at least 15 but below 40 is `MILD`. Anything below 15 is `MINIMAL`.
    The boundaries are exact: 70 is `SEVERE`, 40 is `MODERATE`, 15 is `MILD` and
    14 is `MINIMAL`."
    PRD 3.5: "`response_due_at` is the assessment's `created_at` plus the tier's
    service level: 30 minutes for `SEVERE`, 240 minutes — four hours — for
    `MODERATE`, 1,440 minutes — a full day — for `MILD`, and 4,320 minutes, three
    days, for `MINIMAL`."

    Design: Corner/calculations/symptom_severity_tier_floors_are_inclusive_and_ceilings_exclusive
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Uma Castille")
    plan = active_care_plan(patient["id"], plan_title="Plan", problem_list=["pain"])

    cases = [
        (dict(item_pain=10, item_dyspnea=10, item_nausea=5, item_anxiety=5, item_fatigue=5),
         70, "SEVERE", 30),
        (dict(item_pain=10, item_dyspnea=10, item_nausea=5, item_anxiety=5, item_fatigue=4),
         68, "MODERATE", 240),
        (dict(item_pain=2, item_dyspnea=2, item_nausea=2, item_anxiety=1, item_fatigue=1),
         16, "MILD", 1440),
        (dict(item_pain=2, item_dyspnea=2, item_nausea=1, item_anxiety=1, item_fatigue=1),
         14, "MINIMAL", 4320),
    ]

    for items, expected_score, expected_tier, sla_minutes in cases:
        assessment = file_symptom_assessment(
            patient["id"], plan["id"], reporter_type="SELF", **items
        )
        assert assessment["distress_score"] == expected_score, (
            f"{items} must score {expected_score}, got {assessment['distress_score']}"
        )
        assert assessment["severity_tier"] == expected_tier, (
            f"score {expected_score} must be {expected_tier}, "
            f"got {assessment['severity_tier']}"
        )
        assert_instant_equals_offset(
            assessment["response_due_at"],
            assessment["created_at"],
            minutes=sla_minutes,
            label=f"response_due_at for a {expected_tier} assessment",
        )
