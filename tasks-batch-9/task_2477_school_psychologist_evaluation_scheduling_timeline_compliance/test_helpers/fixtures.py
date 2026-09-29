"""Composite setup builders.

Every builder drives real endpoints only, so the state it leaves behind is
exactly the state the requirements say those endpoints produce. The database is
empty at the start of each test, so each builder starts from scratch.

`SchoolPsychologist` requests carry the acting psychologist's `id` as
`X-User-ID`, so builders that act in that capacity always take the
psychologist id and derive headers from it.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    assign_evaluator_payload,
    consent_event_payload,
    create_assessment_instrument_payload,
    create_psychologist_payload,
    create_referral_payload,
    create_school_payload,
    decision_payload,
    eligibility_meeting_payload,
    interpreter_session_payload,
    license_seat_payload,
    propose_remedy_payload,
    protocol_order_payload,
    receive_order_payload,
    report_draft_payload,
    reschedule_payload,
    scores_payload,
    start_testing_payload,
    timeline_exclusion_payload,
)
from .test_users import TEST_USERS, make_school_psychologist_headers

ADMIN = TEST_USERS["district_admin_headers"]
SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------- the logical clock ----------------


def set_clock(current_utc, headers=ADMIN) -> dict:
    """Move the district clock and return the echoed instant."""
    return get_success_data(api_client.set_clock(current_utc, headers))


def reset_clock(headers=ADMIN) -> dict:
    """Pin the clock back to the instant it reads before any client moves it."""
    return set_clock(DEFAULT_CLOCK_UTC, headers)


# ---------------- single-entity registration ----------------


def create_school(**overrides) -> dict:
    return get_success_data(
        api_client.create_school(create_school_payload(**overrides), ADMIN), 201
    )


def create_psychologist(school_ids, **overrides) -> dict:
    return get_success_data(
        api_client.create_psychologist(
            create_psychologist_payload(school_ids, **overrides), ADMIN
        ),
        201,
    )


def create_instrument(**overrides) -> dict:
    return get_success_data(
        api_client.create_assessment_instrument(
            create_assessment_instrument_payload(**overrides), ADMIN
        ),
        201,
    )


def create_referral(school_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_referral(create_referral_payload(school_id, **overrides), INTAKE),
        201,
    )


def assign_license_seat(instrument_id, psychologist_id, headers=SUPERVISOR) -> dict:
    return get_success_data(
        api_client.assign_license_seat(
            instrument_id, license_seat_payload(psychologist_id), headers
        ),
        201,
    )


def release_license_seat(instrument_id, seat_id, headers=SUPERVISOR) -> dict:
    return get_success_data(
        api_client.release_license_seat(instrument_id, seat_id, headers)
    )


# ---------------- consent and the evaluation it creates ----------------


def record_consent(referral_id, **overrides) -> dict:
    """Record a consent event and return the refreshed referral."""
    return get_success_data(
        api_client.create_consent_event(
            referral_id, consent_event_payload(**overrides), INTAKE
        )
    )


def consented_referral(school_id, effective_at="2026-08-01T00:00:00Z", **referral_overrides):
    """Intake a referral, record consent, and return (referral, evaluation)."""
    referral = create_referral(school_id, **referral_overrides)
    referral = record_consent(
        referral["id"],
        event_type="CONSENT_RECEIVED",
        effective_at=effective_at,
        parent_signature_reference="SIG-1",
    )
    evaluation = get_evaluation(referral["active_evaluation_id"])
    return referral, evaluation


def waived_referral(school_id, prior_evaluation_id, effective_at="2026-08-01T00:00:00Z",
                    waiver_reason="Three-year review with a current consent on file",
                    **referral_overrides):
    """Intake a REEVALUATION referral, waive consent, return (referral, evaluation)."""
    overrides = dict(referral_overrides)
    overrides.setdefault("referral_type", "REEVALUATION")
    overrides["prior_evaluation_id"] = prior_evaluation_id
    referral = create_referral(school_id, **overrides)
    referral = record_consent(
        referral["id"],
        event_type="CONSENT_WAIVED",
        effective_at=effective_at,
        waiver_reason=waiver_reason,
    )
    evaluation = get_evaluation(referral["active_evaluation_id"])
    return referral, evaluation


def withdraw_consent(referral_id, effective_at="2026-08-01T00:00:00Z") -> dict:
    return record_consent(
        referral_id, event_type="CONSENT_WITHDRAWN", effective_at=effective_at
    )


# ---------------- reads ----------------


def get_evaluation(evaluation_id, headers=SUPERVISOR) -> dict:
    return get_success_data(api_client.get_evaluation(evaluation_id, headers))


def get_referral(referral_id, headers=INTAKE) -> dict:
    return get_success_data(api_client.get_referral(referral_id, headers))


def get_psychologist(psychologist_id, headers=SUPERVISOR) -> dict:
    return get_success_data(api_client.get_psychologist(psychologist_id, headers))


def get_instrument(instrument_id, headers=SUPERVISOR) -> dict:
    return get_success_data(api_client.get_assessment_instrument(instrument_id, headers))


def get_meeting(meeting_id, headers=INTAKE) -> dict:
    return get_success_data(api_client.get_eligibility_meeting(meeting_id, headers))


def evaluation_version(evaluation_id, headers=SUPERVISOR) -> int:
    """Read the current guard value for the two version-guarded operations."""
    return get_evaluation(evaluation_id, headers)["version"]


def list_rows(response) -> list:
    data, _meta = validate_paginated(response)
    return data


def instrument_seats(instrument_id, headers=SUPERVISOR) -> list:
    return list_rows(api_client.list_instrument_license_seats(instrument_id, headers))


def psychologist_seats(psychologist_id, headers=SUPERVISOR) -> list:
    return list_rows(api_client.list_psychologist_license_seats(psychologist_id, headers))


def evaluation_exclusions(evaluation_id, headers=SUPERVISOR) -> list:
    return list_rows(
        api_client.list_evaluation_timeline_exclusions(evaluation_id, headers)
    )


def evaluation_sessions(evaluation_id, headers=SUPERVISOR) -> list:
    return list_rows(
        api_client.list_evaluation_interpreter_sessions(evaluation_id, headers)
    )


def evaluation_breaches(evaluation_id, headers=COMPLIANCE) -> list:
    return list_rows(api_client.list_evaluation_timeline_breaches(evaluation_id, headers))


def meetings_for_evaluation(evaluation_id, headers=INTAKE) -> list:
    return list_rows(
        api_client.list_eligibility_meetings(headers, {"evaluation_id": evaluation_id})
    )


# ---------------- assignment ----------------


def assign_evaluator(evaluation_id, psychologist_id=None, expected_version=None) -> dict:
    """Assign (explicit or selector mode) with a freshly read guard value."""
    if expected_version is None:
        expected_version = evaluation_version(evaluation_id)
    return get_success_data(
        api_client.assign_evaluator(
            evaluation_id,
            assign_evaluator_payload(expected_version, psychologist_id),
            SUPERVISOR,
        )
    )


def place_on_leave(psychologist_id) -> dict:
    return get_success_data(
        api_client.place_psychologist_on_leave(psychologist_id, ADMIN)
    )


# ---------------- the assessment pipeline ----------------


def start_testing(evaluation_id, instrument_id, psychologist_id) -> dict:
    return get_success_data(
        api_client.start_testing(
            evaluation_id,
            start_testing_payload(instrument_id),
            make_school_psychologist_headers(psychologist_id),
        )
    )


def record_scores(evaluation_id, psychologist_id, score_summary="Composite 92, fluency 88"):
    return get_success_data(
        api_client.record_scores(
            evaluation_id,
            scores_payload(score_summary),
            make_school_psychologist_headers(psychologist_id),
        )
    )


def submit_report_draft(evaluation_id, psychologist_id,
                        report_narrative="Draft: eligibility criteria reviewed."):
    return get_success_data(
        api_client.submit_report_draft(
            evaluation_id,
            report_draft_payload(report_narrative),
            make_school_psychologist_headers(psychologist_id),
        )
    )


def review_report(evaluation_id, decision, reviewer_psychologist_id=None, headers=None):
    """Peer-review a draft. Pass a reviewer id to act as a second psychologist."""
    if headers is None:
        headers = (
            make_school_psychologist_headers(reviewer_psychologist_id)
            if reviewer_psychologist_id is not None
            else SUPERVISOR
        )
    return get_success_data(
        api_client.review_report(evaluation_id, decision_payload(decision), headers)
    )


# ---------------- exclusions ----------------


def claim_exclusion(evaluation_id, psychologist_id, exclusion_type, start_date, end_date,
                    claim_note="District closure"):
    return get_success_data(
        api_client.claim_timeline_exclusion(
            timeline_exclusion_payload(
                evaluation_id, exclusion_type, start_date, end_date, claim_note
            ),
            make_school_psychologist_headers(psychologist_id),
        ),
        201,
    )


def decide_exclusion(exclusion_id, decision="APPROVE") -> dict:
    return get_success_data(
        api_client.decide_timeline_exclusion(
            exclusion_id, decision_payload(decision), SUPERVISOR
        )
    )


def approved_exclusion(evaluation_id, psychologist_id, exclusion_type, start_date, end_date,
                       claim_note="District closure"):
    exclusion = claim_exclusion(
        evaluation_id, psychologist_id, exclusion_type, start_date, end_date, claim_note
    )
    return decide_exclusion(exclusion["id"], "APPROVE")


# ---------------- interpreter sessions ----------------


def book_session(evaluation_id, session_start_at, session_end_at, language_code="es",
                 interpreter_name="Test Interpreter", headers=INTAKE):
    return get_success_data(
        api_client.book_interpreter_session(
            interpreter_session_payload(
                evaluation_id,
                session_start_at,
                session_end_at,
                language_code,
                interpreter_name,
            ),
            headers,
        ),
        201,
    )


# ---------------- eligibility meetings ----------------


def create_meeting(evaluation_id, school_id, scheduled_start_at, scheduled_end_at,
                   expected_version=None, headers=INTAKE):
    if expected_version is None:
        expected_version = evaluation_version(evaluation_id)
    return get_success_data(
        api_client.create_eligibility_meeting(
            eligibility_meeting_payload(
                evaluation_id,
                school_id,
                scheduled_start_at,
                scheduled_end_at,
                expected_version,
            ),
            headers,
        ),
        201,
    )


def send_notice(meeting_id) -> dict:
    return get_success_data(api_client.send_meeting_notice(meeting_id, INTAKE))


def reschedule_meeting(meeting_id, scheduled_start_at, scheduled_end_at) -> dict:
    return get_success_data(
        api_client.request_meeting_reschedule(
            meeting_id, reschedule_payload(scheduled_start_at, scheduled_end_at), INTAKE
        )
    )


def hold_meeting(meeting_id) -> dict:
    return get_success_data(api_client.hold_meeting(meeting_id, SUPERVISOR))


def noticed_meeting(evaluation_id, school_id, scheduled_start_at, scheduled_end_at,
                    notice_clock=None):
    """Propose a meeting and issue its parent notice, optionally moving the clock first."""
    meeting = create_meeting(
        evaluation_id, school_id, scheduled_start_at, scheduled_end_at
    )
    if notice_clock is not None:
        set_clock(notice_clock)
    return send_notice(meeting["id"])


# ---------------- protocol orders ----------------


def order_protocols(instrument_id, quantity_requested, rush_flag=False) -> dict:
    return get_success_data(
        api_client.create_protocol_order(
            protocol_order_payload(instrument_id, quantity_requested, rush_flag),
            SUPERVISOR,
        ),
        201,
    )


def decide_order(order_id, decision="APPROVE") -> dict:
    return get_success_data(
        api_client.decide_protocol_order(order_id, decision_payload(decision), ADMIN)
    )


def receive_order(order_id, received_quantity) -> dict:
    return get_success_data(
        api_client.receive_protocol_order(
            order_id, receive_order_payload(received_quantity), SUPERVISOR
        )
    )


# ---------------- compliance sweeps, breaches and remedies ----------------


def run_sweep(headers=COMPLIANCE) -> dict:
    return get_success_data(api_client.run_compliance_sweep(headers))


def first_breach(evaluation_id) -> dict:
    """The breach the sweep opened for this evaluation."""
    breaches = evaluation_breaches(evaluation_id)
    assert breaches, f"expected a breach for evaluation {evaluation_id}"
    return breaches[0]


def propose_remedy(breach_id, remedy_basis, additional_minutes=0,
                   corrective_action_note="Compensatory blocks"):
    return get_success_data(
        api_client.propose_remedy(
            breach_id,
            propose_remedy_payload(
                remedy_basis, additional_minutes, corrective_action_note
            ),
            COMPLIANCE,
        )
    )


def approve_remedy(breach_id) -> dict:
    return get_success_data(api_client.approve_remedy(breach_id, ADMIN))


# ---------------- whole-scenario composites ----------------


def assigned_evaluation(school_overrides=None, psychologist_overrides=None,
                        referral_overrides=None, effective_at="2026-08-01T00:00:00Z"):
    """A building, a psychologist, a consented referral and its assigned evaluation.

    Returns a dict with keys school, psychologist, referral, evaluation.
    """
    school = create_school(**(school_overrides or {}))
    psychologist = create_psychologist(
        [school["id"]], **(psychologist_overrides or {})
    )
    referral, evaluation = consented_referral(
        school["id"], effective_at=effective_at, **(referral_overrides or {})
    )
    evaluation = assign_evaluator(evaluation["id"], psychologist["id"])
    return {
        "school": school,
        "psychologist": psychologist,
        "referral": referral,
        "evaluation": evaluation,
    }


def evaluation_ready_for_testing(school_overrides=None, psychologist_overrides=None,
                        referral_overrides=None, instrument_overrides=None,
                        effective_at="2026-08-01T00:00:00Z"):
    """An assigned evaluation plus an instrument the owner holds a live seat on.

    Adds keys instrument and seat, and books an interpreter session when the
    referral requires interpreter support, so testing-start has every gate met.
    """
    context = assigned_evaluation(
        school_overrides, psychologist_overrides, referral_overrides, effective_at
    )
    instrument = create_instrument(**(instrument_overrides or {}))
    seat = assign_license_seat(instrument["id"], context["psychologist"]["id"])
    context["instrument"] = instrument
    context["seat"] = seat
    if context["evaluation"]["interpreter_required"]:
        context["session"] = book_session(
            context["evaluation"]["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:00:00Z",
            language_code=context["referral"]["primary_language"],
        )
    return context


def evaluation_in_testing(**kwargs) -> dict:
    context = evaluation_ready_for_testing(**kwargs)
    context["evaluation"] = start_testing(
        context["evaluation"]["id"],
        context["instrument"]["id"],
        context["psychologist"]["id"],
    )
    return context


def scored_evaluation(score_summary="Composite 92, fluency 88", **kwargs) -> dict:
    context = evaluation_in_testing(**kwargs)
    context["evaluation"] = record_scores(
        context["evaluation"]["id"], context["psychologist"]["id"], score_summary
    )
    return context


def drafted_evaluation(report_narrative="Draft: eligibility criteria reviewed.", **kwargs):
    context = scored_evaluation(**kwargs)
    context["evaluation"] = submit_report_draft(
        context["evaluation"]["id"], context["psychologist"]["id"], report_narrative
    )
    return context


def final_report_evaluation(**kwargs) -> dict:
    """A drafted report approved by a second psychologist (segregation of duties).

    Adds key reviewer for the psychologist who approved the draft.
    """
    context = drafted_evaluation(**kwargs)
    reviewer = create_psychologist(
        [context["school"]["id"]],
        full_name="Peer Reviewer",
        credential_type="PHD",
    )
    context["reviewer"] = reviewer
    context["evaluation"] = review_report(
        context["evaluation"]["id"], "APPROVE", reviewer_psychologist_id=reviewer["id"]
    )
    return context


def breached_evaluation(clock_after="2026-10-08T00:00:00Z", **kwargs) -> dict:
    """An assigned evaluation swept past its statutory due date.

    Adds keys sweep and breach.
    """
    context = assigned_evaluation(**kwargs)
    set_clock(clock_after)
    context["sweep"] = run_sweep()
    context["evaluation"] = get_evaluation(context["evaluation"]["id"])
    context["breach"] = first_breach(context["evaluation"]["id"])
    return context
