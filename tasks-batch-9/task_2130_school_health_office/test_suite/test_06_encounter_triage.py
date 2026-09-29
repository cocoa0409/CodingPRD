"""Office encounters: the triage score frozen at arrival, its nested clamps, the
four-way disposition fork and the reopen cycle."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _critical_anaphylaxis_building():
    """A READY building at FULL posture with one CRITICAL anaphylaxis student."""
    ctx = setup_stock_school(
        epinephrine_units=10, albuterol_units=40,
        school_overrides={"name": "Adams Middle", "building_code": "ADM02", "cot_capacity": 3},
        student_overrides={"full_name": "Elin Cruz", "grade_level": 7,
                           "date_of_birth": "2013-02-27T00:00:00Z",
                           "allergy_severity": "ANAPHYLAXIS",
                           "chronic_condition_codes": ["ASTHMA"],
                           "immunization_status": "NONCOMPLIANT"})
    return ctx


def test_the_risk_uplift_is_clamped_at_25_before_the_outer_clamp_applies(api, admin_headers):
    """PRD §3.6: "The student's `risk_tier`, read from the student row at the instant of the
    transition, contributes 0 points at `ROUTINE`, 10 at `ELEVATED` and 20 at `CRITICAL`; an
    anaphylaxis bonus of a further 15 points applies when the student's `allergy_severity` is
    `ANAPHYLAXIS` **and** the `complaint_code` is `ILLNESS` or `MEDICATION`."
    PRD §3.6: "Those two contributions are summed and then capped at 25 — the inner clamp — so a
    `CRITICAL` anaphylaxis student contributes 25 rather than 35."
    PRD §3.6: "The derived flag `requires_ems_review` is true when `triage_score` is at least 85,
    so a score of exactly 85 sets it."

    Design: Difficulty/combinatorial_formula/triage_nested_clamp_caps_risk_uplift_at_25
    """
    ctx = _critical_anaphylaxis_building()
    building = validate_success(api.get_school(ctx["school"]["id"], admin_headers))
    assert building["required_stock_units"] == 1
    assert building["epinephrine_days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert building["albuterol_days_of_supply"] == pytest.approx(33.33, abs=0.001)
    assert building["stock_protocol_status"] == "READY"
    assert building["delivered_students_per_nurse_fte"] == pytest.approx(4.38, abs=0.001)
    assert building["coverage_posture"] == "FULL"

    student = validate_success(api.get_student(ctx["student"]["id"], admin_headers))
    assert student["intake_risk_score"] == 70
    assert student["risk_tier"] == "CRITICAL"

    resp = api.create_health_visit(
        {"student_id": ctx["student"]["id"], "school_id": ctx["school"]["id"],
         "nurse_id": ctx["nurse"]["id"], "complaint_code": "MEDICATION", "acuity": "URGENT"},
        make_nurse_headers(ctx["nurse"]["id"]))
    visit = validate_success(resp, 201)
    assert_health_visit(visit)

    assert visit["triage_score"] == 77, "40 base + 12 complaint + 25 clamped uplift + 0 penalty"
    assert visit["triage_score"] != 87, "the uplift is clamped at 25 before the outer clamp"
    assert visit["requires_ems_review"] is False


def test_the_anaphylaxis_bonus_only_applies_to_illness_and_medication_complaints(api, admin_headers):
    """PRD §3.6: "The `complaint_code` adds 10 points for `INJURY`, 8 for `ILLNESS`, 12 for
    `MEDICATION`, 15 for `CHRONIC_CARE`, 18 for `MENTAL_HEALTH` and 2 for `SCREENING_FOLLOWUP`."
    PRD §3.6: "The student's `risk_tier`, read from the student row at the instant of the
    transition, contributes 0 points at `ROUTINE`, 10 at `ELEVATED` and 20 at `CRITICAL`; an
    anaphylaxis bonus of a further 15 points applies when the student's `allergy_severity` is
    `ANAPHYLAXIS` **and** the `complaint_code` is `ILLNESS` or `MEDICATION`."
    PRD §3.6: "The `acuity` supplies a base of 10 points for `ROUTINE`, 40 for `URGENT` and 70 for
    `EMERGENT`."

    Design: Difficulty/combinatorial_formula/triage_nested_clamp_caps_risk_uplift_at_25
    """
    ctx = _critical_anaphylaxis_building()
    nurse_headers = make_nurse_headers(ctx["nurse"]["id"])

    illness = validate_success(api.create_health_visit(
        {"student_id": ctx["student"]["id"], "school_id": ctx["school"]["id"],
         "nurse_id": ctx["nurse"]["id"], "complaint_code": "ILLNESS", "acuity": "URGENT"},
        nurse_headers), 201)
    assert illness["triage_score"] == 73, "40 + 8 + min(25, 20 + 15) + 0"

    injury = validate_success(api.create_health_visit(
        {"student_id": ctx["student"]["id"], "school_id": ctx["school"]["id"],
         "nurse_id": ctx["nurse"]["id"], "complaint_code": "INJURY", "acuity": "URGENT"},
        nurse_headers), 201)
    assert injury["triage_score"] == 70, "40 + 10 + 20 with no anaphylaxis bonus on an injury"
    assert injury["requires_ems_review"] is False


def _ems_boundary_building():
    """A LIMITED building with two identical CRITICAL anaphylaxis students."""
    base = setup_school_with_coverage(
        school_overrides={"name": "Emerson Middle", "building_code": "EMS19", "cot_capacity": 3})
    profile = {"allergy_severity": "ANAPHYLAXIS", "chronic_condition_codes": ["ASTHMA"],
               "immunization_status": "NONCOMPLIANT"}
    base["student_a"] = create_student(base["school"]["id"], full_name="Kit Alvarez", grade_level=6,
                                       date_of_birth="2014-08-09T00:00:00Z", **profile)
    base["student_b"] = create_student(base["school"]["id"], full_name="Lia Novak", grade_level=6,
                                       date_of_birth="2014-10-25T00:00:00Z", **profile)
    set_clock(MONDAY_0900)
    return base


def test_a_triage_score_of_exactly_85_justifies_an_ems_transport(api, admin_headers):
    """PRD §3.6: "The derived flag `requires_ems_review` is true when `triage_score` is at least
    85, so a score of exactly 85 sets it."
    PRD §3.6: "**`EMS_TRANSPORT`** requires justification: either the encounter's `acuity` is
    `EMERGENT` or its `triage_score` is at least 85, failing which it is refused with
    `ERR_EMS_DISPOSITION_NOT_JUSTIFIED` (HTTP 409) at position 28. On success `guardian_notified`
    is forced to true regardless of what the request body says, the student's
    `observed_risk_score`, `effective_risk_score` and `risk_tier` are recomputed, and the
    building's `stock_protocol_status` is re-evaluated."

    Design: Difficulty/boundary_precision_check/triage_exactly_85_admits_ems_transport_83_does_not
    """
    ctx = _ems_boundary_building()
    nurse_id = ctx["nurse"]["id"]

    visit = open_visit(ctx["student_a"]["id"], ctx["school"]["id"], nurse_id,
                       complaint_code="MEDICATION", acuity="URGENT")
    assert visit["triage_score"] == 85, "40 + 12 + 25 clamped uplift + 8 coverage penalty"
    assert visit["requires_ems_review"] is True
    assess_visit(visit["id"], nurse_id, "Facial swelling after snack")

    resp = api.dispose_health_visit(visit["id"], {"disposition": "EMS_TRANSPORT"},
                                    make_nurse_headers(nurse_id))
    data = validate_success(resp, 200)
    assert data["disposition"] == "EMS_TRANSPORT"
    assert data["guardian_notified"] is True
    assert data["status"] == "DISPOSITIONED"


def test_a_triage_score_below_the_threshold_cannot_justify_an_ems_transport(api, admin_headers):
    """PRD §3.6: "**`EMS_TRANSPORT`** requires justification: either the encounter's `acuity` is
    `EMERGENT` or its `triage_score` is at least 85, failing which it is refused with
    `ERR_EMS_DISPOSITION_NOT_JUSTIFIED` (HTTP 409) at position 28. On success `guardian_notified`
    is forced to true regardless of what the request body says, the student's
    `observed_risk_score`, `effective_risk_score` and `risk_tier` are recomputed, and the
    building's `stock_protocol_status` is re-evaluated."
    PRD §3.6: "Those two contributions are summed and then capped at 25 — the inner clamp — so a
    `CRITICAL` anaphylaxis student contributes 25 rather than 35."

    Design: Difficulty/boundary_precision_check/triage_exactly_85_admits_ems_transport_83_does_not
    """
    ctx = _ems_boundary_building()
    nurse_id = ctx["nurse"]["id"]

    visit = open_visit(ctx["student_b"]["id"], ctx["school"]["id"], nurse_id,
                       complaint_code="INJURY", acuity="URGENT")
    assert visit["triage_score"] == 78, "40 + 10 + 20 uplift with no anaphylaxis bonus + 8 penalty"
    assert visit["requires_ems_review"] is False
    assess_visit(visit["id"], nurse_id, "Forearm abrasion, no deformity")

    resp = api.dispose_health_visit(visit["id"], {"disposition": "EMS_TRANSPORT"},
                                    make_nurse_headers(nurse_id))
    validate_error(resp, ApiErrorId.ERR_EMS_DISPOSITION_NOT_JUSTIFIED.value, 409)

    unchanged = validate_success(api.get_health_visit(visit["id"], admin_headers))
    assert unchanged["status"] == "IN_ASSESSMENT"
    assert unchanged.get("disposition") is None
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 1


def _reopenable_encounter():
    ctx = setup_visit_in_assessment(
        school_overrides={"name": "Dover Elementary", "building_code": "DOV05"},
        student_overrides={"full_name": "Gil Frank", "grade_level": 1,
                           "date_of_birth": "2019-05-08T00:00:00Z"},
        visit_overrides={"complaint_code": "INJURY", "acuity": "ROUTINE"})
    dispose_visit(ctx["visit"]["id"], ctx["nurse"]["id"], "RETURN_TO_CLASS")
    set_clock("2026-08-03T09:30:00Z")
    ctx["closed"] = close_visit(ctx["visit"]["id"], ctx["nurse"]["id"])
    return ctx


def test_the_quiet_branch_closes_and_a_reopen_clears_the_disposition(api, admin_headers):
    """PRD §3.6: "**`RETURN_TO_CLASS`** is the quiet branch: it neither notifies a guardian nor
    touches any screening."
    PRD §3.6: "On success the encounter moves `CLOSED` → `REOPENED`, `disposition` is cleared to
    null, `closed_at` and `minutes_in_office` are cleared to null, `reopen_count` and the
    building's `occupied_cot_count` are each incremented by one, and the triage score is recomputed
    from scratch against the student's *current* `risk_tier` and the building's *current*
    `coverage_posture` — which is why the same encounter can score differently the second time."

    Design: Difficulty/non_linear_state_machine/health_visit_four_way_branch_then_reopen_cycle
    """
    ctx = _reopenable_encounter()
    assert ctx["closed"]["disposition"] == "RETURN_TO_CLASS"
    assert ctx["closed"]["guardian_notified"] is False
    assert ctx["closed"]["minutes_in_office"] == 30
    assert ctx["closed"]["triage_score"] == 28, "10 base + 10 complaint + 0 uplift + 8 penalty"

    reopened = validate_success(api.reopen_health_visit(
        ctx["visit"]["id"], make_nurse_headers(ctx["nurse"]["id"]),
        {"reason_code": "Pain returned within the hour"}))
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened.get("disposition") is None
    assert reopened.get("closed_at") is None
    assert reopened.get("minutes_in_office") is None
    assert reopened["triage_score"] == 28, "the same inputs re-score identically"
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 1


def test_the_second_pass_through_the_fork_takes_a_different_branch(api, admin_headers):
    """PRD §3.6: "**`SEND_HOME`** requires the request body to carry `guardian_notified` as true;
    without it the disposition is refused with `ERR_GUARDIAN_NOTIFICATION_REQUIRED` (HTTP 409) at
    position 27."
    PRD §3.6: "Each disposition requires the encounter to be `IN_ASSESSMENT` and moves it to
    `DISPOSITIONED`, and every branch decrements the building's `occupied_cot_count` by one — but
    there the similarity ends, and the request carries a `disposition` plus, for one branch,
    `guardian_notified`."

    Design: Difficulty/non_linear_state_machine/health_visit_four_way_branch_then_reopen_cycle
    """
    ctx = _reopenable_encounter()
    nurse_id = ctx["nurse"]["id"]
    reopen_visit(ctx["visit"]["id"], nurse_id, "Pain returned within the hour")
    assess_visit(ctx["visit"]["id"], nurse_id, "Swelling now present, guardian called")

    resp = api.dispose_health_visit(
        ctx["visit"]["id"], {"disposition": "SEND_HOME", "guardian_notified": True},
        make_nurse_headers(nurse_id))
    data = validate_success(resp, 200)
    assert data["disposition"] == "SEND_HOME"
    assert data["guardian_notified"] is True
    assert data["status"] == "DISPOSITIONED"
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 0


def test_reading_an_encounter_returns_the_row_the_arrival_created(api, admin_headers):
    """PRD §3.6: "On creation `arrival_at` is stamped with the logical clock, `status` is `OPEN`,
    `disposition` is null, `guardian_notified` is false, `reopen_count` is 0, and
    `occupied_cot_count` at the building is incremented by one."
    PRD §3.6: "**Closure.** A `DISPOSITIONED` encounter is closed once nothing is still reserved
    against it: `pending_administration_count`, which counts the encounter's administration records
    in `PREPARED` status, must be exactly 0, or the close is refused with
    `ERR_PENDING_ADMINISTRATION` (HTTP 409) at ladder position 43."

    Design: Corner/entities/health_visit_retrieval_returns_stored_encounter_fields
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Ashby Elementary", "building_code": "AAA29"},
        student_overrides={"full_name": "Ada Storm", "grade_level": 3,
                           "date_of_birth": "2017-11-11T00:00:00Z"})
    set_clock(MONDAY_0900)
    created = open_visit(base["student"]["id"], base["school"]["id"], base["nurse"]["id"],
                         complaint_code="INJURY", acuity="ROUTINE")

    data = validate_success(api.get_health_visit(created["id"], make_nurse_headers(base["nurse"]["id"])))
    assert_health_visit(data)
    assert data["arrival_at"].startswith("2026-08-03T09:00:00")
    assert data["status"] == "OPEN"
    assert data.get("disposition") is None
    assert data.get("closed_at") is None
    assert data.get("minutes_in_office") is None
    assert data["reopen_count"] == 0
    assert data["guardian_notified"] is False
    assert data["pending_administration_count"] == 0
    assert data["triage_score"] == 28
