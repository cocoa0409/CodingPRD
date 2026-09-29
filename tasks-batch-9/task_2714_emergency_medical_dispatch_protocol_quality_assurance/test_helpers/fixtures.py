"""Composite setup builders.

Every precondition is built from scratch through the endpoints the PRD declares,
because each test runs against an empty database. All setup calls go through
get_success_data() so a broken precondition fails loudly and immediately.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    ADMIN,
    DIRECTOR,
    OFFICER,
    REVIEWER,
    SUPERVISOR,
    make_dispatcher_headers,
)

# ------------------------------------------------------------------- primitives
def set_clock(api, to_iso8601: str) -> str:
    data = get_success_data(api.set_clock(f.clock_payload(to_iso8601), ADMIN))
    return data["current_utc"]


def new_program(api, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_audit_program(f.audit_program_payload(**overrides), ADMIN)
    )


def new_version(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_protocol_version(program_id, f.protocol_version_payload(**overrides), ADMIN)
    )


def approve_version(api, version_id: str, note: str = "adopted") -> Dict[str, Any]:
    return get_success_data(
        api.approve_protocol_version(version_id, {"approval_note": note}, DIRECTOR)
    )


def new_approved_version(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    version = new_version(api, program_id, **overrides)
    return approve_version(api, version["id"])


def new_dispatcher(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_dispatcher(f.dispatcher_payload(program_id, **overrides), ADMIN)
    )


def certify(api, dispatcher_id: str, version_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"protocol_version_id": version_id}
    payload.update(overrides)
    return get_success_data(api.certify_dispatcher(dispatcher_id, payload, ADMIN))


def new_rollout(api, version_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_rollout(version_id, f.rollout_payload(**overrides), ADMIN)
    )


def go_live(api, rollout_id: str, note: str = "go-live coordinated") -> Dict[str, Any]:
    return get_success_data(api.go_live(rollout_id, {"golive_note": note}, ADMIN))


def ingest_call(api, dispatcher_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_call_record(dispatcher_id, f.call_record_payload(**overrides), ADMIN)
    )


def ingest_cardiac_arrest_call(api, dispatcher_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_call_record(
            dispatcher_id, f.cardiac_arrest_call_payload(**overrides), ADMIN
        )
    )


def new_period(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_sampling_period(program_id, f.sampling_period_payload(**overrides), SUPERVISOR)
    )


def target(api, period_id: str, call_record_id: str, reason: str = "COMPLAINT",
           headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.target_review(
            period_id,
            f.target_review_payload(call_record_id, selection_reason=reason),
            headers or SUPERVISOR,
        )
    )


def draw_random(api, period_id: str, requested_count: int) -> List[Dict[str, Any]]:
    return get_success_data(
        api.draw_random_sample(period_id, {"requested_count": requested_count}, SUPERVISOR)
    )


def close_period(api, period_id: str, note: str = "quota met") -> Dict[str, Any]:
    return get_success_data(
        api.close_sampling_period(period_id, {"closing_note": note}, SUPERVISOR)
    )


def get_review(api, review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_review(review_id, SUPERVISOR))


def get_dispatcher(api, dispatcher_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dispatcher(dispatcher_id, ADMIN))


def get_version(api, version_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_protocol_version(version_id, ADMIN))


def get_program(api, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_audit_program(program_id, ADMIN))


def get_plan(api, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_coaching_plan(plan_id, SUPERVISOR))


def get_period(api, program_id: str, period_id: str) -> Dict[str, Any]:
    rows = get_success_data(api.list_sampling_periods(program_id, SUPERVISOR, {"limit": 100}))
    for row in rows:
        if row["id"] == period_id:
            return row
    raise AssertionError(f"sampling period {period_id} not found under program {program_id}")


def get_rollout(api, version_id: str, rollout_id: str) -> Dict[str, Any]:
    rows = get_success_data(api.list_rollouts(version_id, ADMIN, {"limit": 100}))
    for row in rows:
        if row["id"] == rollout_id:
            return row
    raise AssertionError(f"rollout {rollout_id} not found under version {version_id}")


def get_high_risk_review(api, review_id: str, high_risk_review_id: str) -> Dict[str, Any]:
    rows = get_success_data(api.list_high_risk_reviews(review_id, REVIEWER))
    for row in rows:
        if row["id"] == high_risk_review_id:
            return row
    raise AssertionError(
        f"high-risk review {high_risk_review_id} not found under review {review_id}"
    )


def get_session(api, plan_id: str, session_id: str) -> Dict[str, Any]:
    rows = get_success_data(api.list_retraining_sessions(plan_id, SUPERVISOR, {"limit": 100}))
    for row in rows:
        if row["id"] == session_id:
            return row
    raise AssertionError(f"session {session_id} not found under plan {plan_id}")


def get_report(api, program_id: str, report_id: str) -> Dict[str, Any]:
    rows = get_success_data(
        api.list_accreditation_reports(program_id, OFFICER, {"limit": 100})
    )
    for row in rows:
        if row["id"] == report_id:
            return row
    raise AssertionError(f"report {report_id} not found under program {program_id}")


def score(api, review_id: str, sections=None, reviewer_determinant_code: str = "10-C-4",
          expected_review_version: Optional[int] = None,
          headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
    """Submit a score sheet, reading the review's current version when not given."""
    if expected_review_version is None:
        expected_review_version = get_review(api, review_id)["version"]
    if sections is None:
        payload = f.score_payload(
            expected_review_version,
            reviewer_determinant_code=reviewer_determinant_code,
            **overrides,
        )
    else:
        payload = f.section_score_payload(
            expected_review_version, sections, reviewer_determinant_code, **overrides
        )
    return get_success_data(api.submit_scores(review_id, payload, headers or REVIEWER))


def finalize(api, review_id: str, note: str = "finalized after review",
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.finalize_review(review_id, {"finalization_note": note}, headers or SUPERVISOR)
    )


def void(api, review_id: str, reason: str = "AUDIO_UNAVAILABLE") -> Dict[str, Any]:
    return get_success_data(api.void_review(review_id, {"void_reason": reason}, SUPERVISOR))


def file_rebuttal(api, review_id: str, dispatcher_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_rebuttal(
            review_id, f.rebuttal_payload(**overrides), make_dispatcher_headers(dispatcher_id)
        )
    )


def decide_rebuttal(api, rebuttal_id: str, decision: str, notes: str = "decided") -> Dict[str, Any]:
    return get_success_data(
        api.decide_rebuttal(
            rebuttal_id, f.rebuttal_decision_payload(decision, decision_notes=notes), SUPERVISOR
        )
    )


def new_high_risk_review(api, review_id: str, outcome_category: str = "ROSC_FIELD") -> Dict[str, Any]:
    return get_success_data(
        api.create_high_risk_review(
            review_id, f.high_risk_review_payload(outcome_category=outcome_category), REVIEWER
        )
    )


def score_dacpr(api, high_risk_review_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.score_dacpr(high_risk_review_id, f.dacpr_payload(**overrides), REVIEWER)
    )


def sign_off(api, high_risk_review_id: str, classification: str = "COACHING_ONLY",
             notes: str = "reviewed with the reviewer") -> Dict[str, Any]:
    return get_success_data(
        api.sign_off_high_risk_review(
            high_risk_review_id,
            f.sign_off_payload(classification, director_notes=notes),
            DIRECTOR,
        )
    )


def new_coaching_plan(api, dispatcher_id: str, expected_dispatcher_version: Optional[int] = None,
                      **overrides: Any) -> Dict[str, Any]:
    if expected_dispatcher_version is None:
        expected_dispatcher_version = get_dispatcher(api, dispatcher_id)["version"]
    payload = f.coaching_plan_payload(dispatcher_id, expected_dispatcher_version, **overrides)
    return get_success_data(api.create_coaching_plan(payload, SUPERVISOR))


def new_session(api, plan_id: str, version_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_retraining_session(
            plan_id, f.retraining_session_payload(version_id, **overrides), SUPERVISOR
        )
    )


def complete_session(api, session_id: str, attendance_confirmed: bool = True) -> Dict[str, Any]:
    return get_success_data(
        api.complete_retraining_session(
            session_id, {"attendance_confirmed": attendance_confirmed}, SUPERVISOR
        )
    )


def cancel_session(api, session_id: str, cancel_reason: str = "RESCHEDULED") -> Dict[str, Any]:
    return get_success_data(
        api.cancel_retraining_session(session_id, {"cancel_reason": cancel_reason}, SUPERVISOR)
    )


def new_report(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_accreditation_report(
            program_id, f.accreditation_report_payload(**overrides), OFFICER
        )
    )


def submit_report(api, report_id: str, submitted_to: str = "MEDICAL_DIRECTOR") -> Dict[str, Any]:
    return get_success_data(
        api.submit_accreditation_report(report_id, {"submitted_to": submitted_to}, OFFICER)
    )


def list_plans_for(api, dispatcher_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"dispatcher_id": dispatcher_id, "limit": 100}
    query.update(params)
    return get_success_data(api.list_coaching_plans(SUPERVISOR, query))


def list_sheets(api, review_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api.list_score_sheets(review_id, SUPERVISOR, {"limit": 100}))


def list_rebuttals_for(api, review_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api.list_rebuttals(review_id, SUPERVISOR, query))


# ------------------------------------------------------------------ composites
WORKING_CLOCK = "2026-08-20T00:00:00Z"
WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-09-01T00:00:00Z"
VERSION_EFFECTIVE_FROM = "2026-07-01T00:00:00Z"


def program_with_version(api, program_overrides=None, version_overrides=None,
                         clock: str = WORKING_CLOCK) -> Dict[str, Any]:
    """Program, one APPROVED MPDS_CARDSET version, and the clock inside its window."""
    program = new_program(api, **(program_overrides or {}))
    version = new_approved_version(api, program["id"], **(version_overrides or {}))
    set_clock(api, clock)
    return {"program": program, "version": version, "program_id": program["id"],
            "version_id": version["id"]}


def enrolled_dispatcher_env(api, program_overrides=None, version_overrides=None,
                            clock: str = WORKING_CLOCK) -> Dict[str, Any]:
    """program_with_version plus one enrolled dispatcher."""
    env = program_with_version(api, program_overrides, version_overrides, clock)
    dispatcher = new_dispatcher(api, env["program_id"])
    env["dispatcher"] = dispatcher
    env["dispatcher_id"] = dispatcher["id"]
    return env


def selected_review_env(api, program_overrides=None, call_overrides=None,
                        period_overrides=None, selection_reason: str = "COMPLAINT",
                        clock: str = WORKING_CLOCK) -> Dict[str, Any]:
    """A dispatcher, one ingested call, an OPEN TARGETED period and one SELECTED review."""
    env = enrolled_dispatcher_env(api, program_overrides, clock=clock)
    call = ingest_call(api, env["dispatcher_id"], **(call_overrides or {}))
    period = new_period(api, env["program_id"], **(period_overrides or {}))
    review = target(api, period["id"], call["id"], selection_reason)
    env.update(
        {
            "call": call,
            "call_id": call["id"],
            "period": period,
            "period_id": period["id"],
            "review": review,
            "review_id": review["id"],
        }
    )
    return env


def scored_review_env(api, sections=None, reviewer_determinant_code: str = "10-C-4",
                      program_overrides=None, call_overrides=None,
                      period_overrides=None, clock: str = WORKING_CLOCK) -> Dict[str, Any]:
    """selected_review_env plus one submitted score sheet, leaving the review SCORED."""
    env = selected_review_env(
        api,
        program_overrides=program_overrides,
        call_overrides=call_overrides,
        period_overrides=period_overrides,
        clock=clock,
    )
    sheet = score(
        api,
        env["review_id"],
        sections=sections,
        reviewer_determinant_code=reviewer_determinant_code,
        expected_review_version=env["review"]["version"],
    )
    env["sheet"] = sheet
    env["sheet_id"] = sheet["id"]
    return env


def under_triage_finalized_env(api) -> Dict[str, Any]:
    """A CHEST_PAIN call dispatched 10-C-4 but coded 10-E-1 by the reviewer, finalized.

    This is the reference under-triage case: the sheet is all-90%, so the
    pre-penalty composite is 90.0 and the under-triage penalty is applied on top.
    """
    env = scored_review_env(
        api,
        reviewer_determinant_code="10-E-1",
        program_overrides={
            "target_compliance_pct": 90.0,
            "watch_floor_pct": 80.0,
            "high_risk_target_pct": 85.0,
            "hours_owed_restriction_threshold": 6.0,
        },
        call_overrides={"dispatched_determinant_code": "10-C-4"},
    )
    env["finalized"] = finalize(api, env["review_id"], "Under-triage confirmed")
    return env


def high_risk_scored_env(api, dacpr_overrides=None, call_overrides=None,
                         outcome_category: str = "ROSC_FIELD",
                         program_overrides=None) -> Dict[str, Any]:
    """A CARDIAC_ARREST review whose high-risk child has been DA-CPR scored."""
    env = enrolled_dispatcher_env(api, program_overrides)
    call = ingest_cardiac_arrest_call(api, env["dispatcher_id"], **(call_overrides or {}))
    period = new_period(
        api, env["program_id"], call_type="CARDIAC_ARREST", target_sample_count=1
    )
    review = target(api, period["id"], call["id"], "HIGH_RISK_OUTCOME")
    hrcr = new_high_risk_review(api, review["id"], outcome_category)
    scored = score_dacpr(api, hrcr["id"], **(dacpr_overrides or {}))
    env.update(
        {
            "call": call,
            "call_id": call["id"],
            "period": period,
            "period_id": period["id"],
            "review": review,
            "review_id": review["id"],
            "high_risk_review": scored,
            "high_risk_review_id": hrcr["id"],
        }
    )
    return env


def two_version_golive_env(api) -> Dict[str, Any]:
    """Two adjacent APPROVED versions, the first LIVE, the second ready to go live."""
    program = new_program(api, hours_owed_restriction_threshold=6.0)
    v1 = new_version(
        api,
        program["id"],
        version_label="MPDS-13.0",
        effective_from="2026-07-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    approve_version(api, v1["id"])
    v2 = new_version(
        api, program["id"], version_label="MPDS-13.1", effective_from="2026-09-01T00:00:00Z"
    )
    approve_version(api, v2["id"])
    d1 = new_dispatcher(api, program["id"])
    d2 = new_dispatcher(api, program["id"])
    set_clock(api, WORKING_CLOCK)
    certified_d1 = certify(api, d1["id"], v1["id"])
    ro1 = new_rollout(
        api, v1["id"], scheduled_golive_at="2026-08-01T00:00:00Z", target_dispatcher_count=1
    )
    go_live(api, ro1["id"], "v13.0 live")
    certify(api, d2["id"], v2["id"])
    ro2 = new_rollout(
        api, v2["id"], scheduled_golive_at="2026-08-10T00:00:00Z", target_dispatcher_count=1
    )
    return {
        "program": program,
        "program_id": program["id"],
        "v1": v1,
        "v1_id": v1["id"],
        "v2": v2,
        "v2_id": v2["id"],
        "d1": certified_d1,
        "d1_id": d1["id"],
        "d2_id": d2["id"],
        "ro1": ro1,
        "ro1_id": ro1["id"],
        "ro2": ro2,
        "ro2_id": ro2["id"],
    }


def locked_period_env(api) -> Dict[str, Any]:
    """Two calls, one review FINALIZED at 92.0 and one left SELECTED, the period CLOSED
    and a CASE_WEIGHTED DRAFT report covering the same window."""
    env = enrolled_dispatcher_env(
        api,
        program_overrides={"target_compliance_pct": 90.0, "watch_floor_pct": 80.0},
    )
    c1 = ingest_call(api, env["dispatcher_id"], received_at="2026-08-05T09:00:00Z")
    c2 = ingest_call(api, env["dispatcher_id"], received_at="2026-08-06T09:00:00Z")
    period = new_period(api, env["program_id"], target_sample_count=2)
    r1 = target(api, period["id"], c1["id"], "COMPLAINT")
    r2 = target(api, period["id"], c2["id"], "NEW_HIRE_AUDIT")
    sections = {
        "case_entry": (23, 25),
        "key_questions": (23, 25),
        "pre_arrival": (23, 25),
        "final_coding": (23, 25),
    }
    score(api, r1["id"], sections=sections, expected_review_version=r1["version"])
    finalize(api, r1["id"], "clean case")
    close_period(api, period["id"])
    report = new_report(api, env["program_id"])
    env.update(
        {
            "c1": c1,
            "c1_id": c1["id"],
            "c2": c2,
            "c2_id": c2["id"],
            "period": period,
            "period_id": period["id"],
            "r1": r1,
            "r1_id": r1["id"],
            "r2": r2,
            "r2_id": r2["id"],
            "report": report,
            "report_id": report["id"],
        }
    )
    return env
