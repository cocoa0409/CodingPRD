"""Composite setup helpers.

The database is empty at the start of every test, so each helper here builds the
state it needs from the ground up through real API calls. Helpers are layered:
the small ones create a single resource, the larger ones drive a whole workflow
to the point a test wants to start from.

All setup calls go through ``get_success_data`` so that a broken setup step
fails loudly with the server's own error id rather than silently producing a
half-built world.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ACCREDITATION_COORDINATOR,
    ACCREDITATION_COORDINATOR_2,
    COC_SURVEYOR,
    COC_SURVEYOR_2,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    STATE_REGISTRY_LIAISON,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
)

# ============================================================================
# Tier 1 — single resources and the primitive state steps
# ============================================================================


def set_clock(client: ApiClient, current_utc):
    """Move the logical clock forward; this is also a reconciliation checkpoint."""
    return get_success_data(client.set_clock(f.clock_payload(current_utc), PLATFORM_ADMIN))


def create_program(client: ApiClient, **overrides):
    return get_success_data(
        client.create_program(f.program_payload(**overrides), PLATFORM_ADMIN)
    )


def read_program(client: ApiClient, program_id, headers=REGISTRY_MANAGER):
    return get_success_data(client.get_program(program_id, headers))


def create_abstractor(client: ApiClient, program_id, **overrides):
    return get_success_data(
        client.create_abstractor(
            f.abstractor_payload(program_id, **overrides), REGISTRY_MANAGER
        )
    )


def read_abstractor(client: ApiClient, abstractor_id, headers=REGISTRY_MANAGER):
    return get_success_data(client.get_abstractor(abstractor_id, headers))


def create_source(client: ApiClient, program_id, **overrides):
    return get_success_data(
        client.create_casefinding_source(
            f.casefinding_source_payload(program_id, **overrides), REGISTRY_MANAGER
        )
    )


def create_entry(client: ApiClient, source_id, **overrides):
    return get_success_data(
        client.create_casefinding_entry(
            source_id, f.casefinding_entry_payload(**overrides), REGISTRY_MANAGER
        )
    )


def read_entry(client: ApiClient, entry_id, headers=REGISTRY_MANAGER):
    return get_success_data(client.get_casefinding_entry(entry_id, headers))


def decide_reportable(client: ApiClient, entry_id, **overrides):
    """Record a REPORTABLE determination, which mints the tumor case."""
    return get_success_data(
        client.reportability_decision(
            entry_id,
            f.reportability_decision_payload("REPORTABLE", **overrides),
            REGISTRY_MANAGER,
        )
    )


def decide_non_reportable(client: ApiClient, entry_id, **overrides):
    payload = f.reportability_decision_payload("NON_REPORTABLE", **overrides)
    return get_success_data(
        client.reportability_decision(entry_id, payload, REGISTRY_MANAGER)
    )


def read_case(client: ApiClient, case_id, headers=REGISTRY_MANAGER):
    return get_success_data(client.get_case(case_id, headers))


def case_of_entry(client: ApiClient, entry_id, headers=REGISTRY_MANAGER):
    """Resolve the case an entry minted through the entry's created_case_id."""
    entry = read_entry(client, entry_id, headers)
    assert entry["created_case_id"] is not None, "entry minted no case"
    return read_case(client, entry["created_case_id"], headers)


def assign_case(client: ApiClient, case_id, abstractor_id):
    return get_success_data(
        client.assign_case(case_id, f.assign_payload(abstractor_id), REGISTRY_MANAGER)
    )


def unassign_case(client: ApiClient, case_id, **overrides):
    return get_success_data(
        client.unassign_case(case_id, f.unassign_payload(**overrides), REGISTRY_MANAGER)
    )


def create_abstraction(client: ApiClient, case_id, abstractor_id, **overrides):
    """Read the case first so that expected_case_version is the current one."""
    case = read_case(client, case_id)
    payload = f.abstraction_payload(
        case_id, abstractor_id, case["version"], **overrides
    )
    return get_success_data(
        client.create_abstraction(
            payload, make_registry_abstractor_headers(abstractor_id)
        )
    )


def submit_for_qa(client: ApiClient, abstraction_id, abstractor_id, **overrides):
    return get_success_data(
        client.submit_qa(
            abstraction_id,
            f.submit_qa_payload(**overrides),
            make_registry_abstractor_headers(abstractor_id),
        )
    )


def qa_decision(client: ApiClient, abstraction_id, reviewer_id, verdict, **overrides):
    return get_success_data(
        client.qa_decision(
            abstraction_id,
            f.qa_decision_payload(verdict, **overrides),
            make_qa_reviewer_headers(reviewer_id),
        )
    )


def reopen_draft(client: ApiClient, abstraction_id, abstractor_id, **overrides):
    return get_success_data(
        client.reopen_draft(
            abstraction_id,
            f.reopen_draft_payload(**overrides),
            make_registry_abstractor_headers(abstractor_id),
        )
    )


def open_audit(client: ApiClient, abstraction_id, auditor_id, **overrides):
    return get_success_data(
        client.create_qa_audit(
            f.qa_audit_payload(abstraction_id, auditor_id, **overrides),
            REGISTRY_MANAGER,
        )
    )


def score_audit(client: ApiClient, audit_id, auditor_id, **overrides):
    return get_success_data(
        client.score_qa_audit(
            audit_id,
            f.audit_score_payload(**overrides),
            make_qa_reviewer_headers(auditor_id),
        )
    )


def void_audit(client: ApiClient, audit_id, **overrides):
    return get_success_data(
        client.void_qa_audit(audit_id, f.audit_void_payload(**overrides), REGISTRY_MANAGER)
    )


def record_contact(client: ApiClient, case_id, **overrides):
    return get_success_data(
        client.create_follow_up_contact(
            case_id, f.follow_up_contact_payload(**overrides), REGISTRY_MANAGER
        )
    )


def create_submission(client: ApiClient, program_id, **overrides):
    return get_success_data(
        client.create_submission(
            f.submission_payload(program_id, **overrides), REGISTRY_MANAGER
        )
    )


def read_submission(client: ApiClient, submission_id, headers=REGISTRY_MANAGER):
    return get_success_data(client.get_submission(submission_id, headers))


def add_item(client: ApiClient, submission_id, case_id):
    """Re-read the batch so that expected_submission_version is current."""
    submission = read_submission(client, submission_id)
    return get_success_data(
        client.add_submission_item(
            submission_id,
            f.submission_item_payload(case_id, submission["version"]),
            REGISTRY_MANAGER,
        )
    )


def transmit(client: ApiClient, submission_id, **overrides):
    return get_success_data(
        client.transmit_submission(
            submission_id, f.transmit_payload(**overrides), REGISTRY_MANAGER
        )
    )


def post_edit_results(client: ApiClient, submission_id, item_results):
    return get_success_data(
        client.post_edit_results(
            submission_id,
            f.edit_results_payload(item_results),
            STATE_REGISTRY_LIAISON,
        )
    )


def resolve_item(client: ApiClient, submission_id, item_id, **overrides):
    return get_success_data(
        client.resolve_submission_item(
            submission_id, item_id, f.resolve_item_payload(**overrides), REGISTRY_MANAGER
        )
    )


def pay_assessment(client: ApiClient, submission_id, amount_cents):
    return get_success_data(
        client.create_assessment_payment(
            submission_id, f.assessment_payment_payload(amount_cents), REGISTRY_MANAGER
        )
    )


def create_session(client: ApiClient, program_id, **overrides):
    return get_success_data(
        client.create_conference_session(
            f.conference_session_payload(program_id, **overrides),
            ACCREDITATION_COORDINATOR,
        )
    )


def record_attendance(client: ApiClient, session_id, attendee_ref, discipline, **overrides):
    return get_success_data(
        client.record_attendance(
            session_id,
            f.attendance_payload(attendee_ref, discipline, **overrides),
            ACCREDITATION_COORDINATOR,
        )
    )


def hold_session(client: ApiClient, session_id, presented, prospective, **overrides):
    return get_success_data(
        client.hold_session(
            session_id,
            f.hold_session_payload(presented, prospective, **overrides),
            ACCREDITATION_COORDINATOR,
        )
    )


def credit_session(client: ApiClient, session_id, disposition="CREDIT", **overrides):
    return get_success_data(
        client.credit_session(
            session_id,
            f.credit_session_payload(disposition, **overrides),
            ACCREDITATION_COORDINATOR,
        )
    )


def create_measure(client: ApiClient, program_id, **overrides):
    return get_success_data(
        client.create_quality_measure(
            f.quality_measure_payload(program_id, **overrides), REGISTRY_MANAGER
        )
    )


def evaluate_measure(client: ApiClient, measure_id, strata):
    return get_success_data(
        client.evaluate_quality_measure(
            measure_id, f.evaluate_measure_payload(strata), REGISTRY_MANAGER
        )
    )


def improvement_project(client: ApiClient, measure_id, action, **overrides):
    return get_success_data(
        client.improvement_project(
            measure_id,
            f.improvement_project_payload(action, **overrides),
            ACCREDITATION_COORDINATOR,
        )
    )


def cite_deficiency(client: ApiClient, program_id, severity="MAJOR", headers=None, **overrides):
    return get_success_data(
        client.create_deficiency(
            f.deficiency_payload(program_id, severity, **overrides),
            headers or COC_SURVEYOR,
        )
    )


def respond_to_deficiency(client: ApiClient, deficiency_id, headers=None, **overrides):
    return get_success_data(
        client.respond_to_deficiency(
            deficiency_id,
            f.deficiency_response_payload(**overrides),
            headers or ACCREDITATION_COORDINATOR,
        )
    )


def review_deficiency(client: ApiClient, deficiency_id, outcome, headers=None, **overrides):
    return get_success_data(
        client.review_deficiency_response(
            deficiency_id,
            f.deficiency_review_payload(outcome, **overrides),
            headers or COC_SURVEYOR,
        )
    )


# ============================================================================
# Tier 2 — the entity hierarchy a workflow needs before it can start
# ============================================================================


def registry_world(client: ApiClient, program=None, **program_overrides):
    """A program with one casefinding source, one registrar, and one reviewer.

    The reviewer is a second registrar of the same program because the QA
    verdict must be recorded by a user who is not the abstraction's author.
    """
    program = program or create_program(client, **program_overrides)
    source = create_source(client, program["id"])
    abstractor = create_abstractor(client, program["id"], name="Primary Registrar")
    reviewer = create_abstractor(client, program["id"], name="Senior Reviewer")
    return {
        "program": program,
        "source": source,
        "abstractor": abstractor,
        "reviewer": reviewer,
    }


def program_with_source(client: ApiClient, **program_overrides):
    program = create_program(client, **program_overrides)
    source = create_source(client, program["id"])
    return {"program": program, "source": source}


# ============================================================================
# Tier 3 — full lifecycle shortcuts along the case state progression
# ============================================================================


def identified_case(client: ApiClient, world=None, entry=None, **entry_overrides):
    """Carry an entry through a REPORTABLE determination so a case is minted."""
    world = world or registry_world(client)
    entry = entry or create_entry(client, world["source"]["id"], **entry_overrides)
    decide_reportable(client, entry["id"])
    case = case_of_entry(client, entry["id"])
    return dict(world, entry=entry, case=case)


def assigned_case(client: ApiClient, world=None, abstractor_id=None, **entry_overrides):
    state = identified_case(client, world=world, **entry_overrides)
    abstractor_id = abstractor_id or state["abstractor"]["id"]
    case = assign_case(client, state["case"]["id"], abstractor_id)
    return dict(state, case=case, working_abstractor_id=abstractor_id)


def in_abstraction_case(client: ApiClient, world=None, **kwargs):
    """Case in IN_ABSTRACTION with a DRAFT abstraction attached."""
    abstraction_overrides = kwargs.pop("abstraction_overrides", {}) or {}
    state = assigned_case(client, world=world, **kwargs)
    abstraction = create_abstraction(
        client,
        state["case"]["id"],
        state["working_abstractor_id"],
        **abstraction_overrides,
    )
    return dict(
        state,
        abstraction=abstraction,
        case=read_case(client, state["case"]["id"]),
    )


def qa_pending_case(client: ApiClient, world=None, **kwargs):
    """Case in QA_PENDING with its abstraction SUBMITTED_FOR_QA."""
    state = in_abstraction_case(client, world=world, **kwargs)
    abstraction = submit_for_qa(
        client, state["abstraction"]["id"], state["working_abstractor_id"]
    )
    return dict(
        state,
        abstraction=abstraction,
        case=read_case(client, state["case"]["id"]),
    )


def completed_case(client: ApiClient, world=None, **kwargs):
    """Case driven all the way to COMPLETED through an APPROVED QA verdict."""
    state = qa_pending_case(client, world=world, **kwargs)
    abstraction = qa_decision(
        client, state["abstraction"]["id"], state["reviewer"]["id"], "APPROVED"
    )
    return dict(
        state,
        abstraction=abstraction,
        case=read_case(client, state["case"]["id"]),
    )


def reworked_case(client: ApiClient, world=None, **kwargs):
    """Case back in IN_ABSTRACTION after a REWORK_REQUIRED verdict."""
    state = qa_pending_case(client, world=world, **kwargs)
    abstraction = qa_decision(
        client, state["abstraction"]["id"], state["reviewer"]["id"], "REWORK_REQUIRED"
    )
    return dict(
        state,
        abstraction=abstraction,
        case=read_case(client, state["case"]["id"]),
    )


def approved_abstraction_with_open_audit(client: ApiClient, world=None, **kwargs):
    """An APPROVED abstraction with an OPEN audit held by the reviewer."""
    audit_overrides = kwargs.pop("audit_overrides", {}) or {}
    state = completed_case(client, world=world, **kwargs)
    audit = open_audit(
        client,
        state["abstraction"]["id"],
        state["reviewer"]["id"],
        **audit_overrides,
    )
    return dict(state, audit=audit)


def draft_submission_with_completed_case(client: ApiClient, world=None, **kwargs):
    """A DRAFT batch carrying one item for a COMPLETED case."""
    submission_overrides = kwargs.pop("submission_overrides", {}) or {}
    state = completed_case(client, world=world, **kwargs)
    submission = create_submission(
        client, state["program"]["id"], **submission_overrides
    )
    item = add_item(client, submission["id"], state["case"]["id"])
    return dict(
        state,
        submission=read_submission(client, submission["id"]),
        item=item,
    )


def transmitted_submission(client: ApiClient, world=None, **kwargs):
    state = draft_submission_with_completed_case(client, world=world, **kwargs)
    submission = transmit(client, state["submission"]["id"])
    return dict(state, submission=submission)


def edits_returned_submission(client: ApiClient, world=None, **kwargs):
    """A batch back in EDITS_RETURNED with one EDIT_FAILED item."""
    edit_codes = kwargs.pop("edit_codes", ["IF25"])
    state = transmitted_submission(client, world=world, **kwargs)
    post_edit_results(
        client,
        state["submission"]["id"],
        [f.item_result(state["case"]["id"], "EDIT_FAILED", edit_codes)],
    )
    return dict(
        state,
        submission=read_submission(client, state["submission"]["id"]),
        item=get_success_data(
            client.get_submission_item(state["item"]["id"], REGISTRY_MANAGER)
        ),
    )


def accepted_submission(client: ApiClient, world=None, **kwargs):
    """A batch that closed on the all-accepted branch."""
    state = transmitted_submission(client, world=world, **kwargs)
    post_edit_results(
        client,
        state["submission"]["id"],
        [f.item_result(state["case"]["id"], "ACCEPTED", [])],
    )
    return dict(
        state, submission=read_submission(client, state["submission"]["id"])
    )


# ============================================================================
# Tier 4 — accumulation and threshold targeting
# ============================================================================


def identified_backlog(client: ApiClient, world=None, count=4, **entry_overrides):
    """Mint ``count`` cases that all stay in IDENTIFIED, filling the backlog."""
    world = world or registry_world(client)
    cases = []
    for index in range(count):
        entry = create_entry(
            client,
            world["source"]["id"],
            patient_mrn=f"MRN-BACKLOG-{index + 1}",
            **entry_overrides,
        )
        decide_reportable(client, entry["id"])
        cases.append(case_of_entry(client, entry["id"]))
    return dict(world, cases=cases, program=read_program(client, world["program"]["id"]))


def restricted_program(client: ApiClient, world=None):
    """Four open cases restrict the registry without freezing it."""
    state = identified_backlog(client, world=world, count=4)
    assert state["program"]["registry_posture"] == "RESTRICTED", state["program"][
        "registry_posture"
    ]
    return state


def frozen_program(client: ApiClient, world=None, **deficiency_overrides):
    """One open CRITICAL deficiency freezes the registry immediately."""
    world = world or registry_world(client)
    deficiency = cite_deficiency(
        client, world["program"]["id"], "CRITICAL", **deficiency_overrides
    )
    program = read_program(client, world["program"]["id"])
    assert program["registry_posture"] == "FROZEN", program["registry_posture"]
    return dict(world, deficiency=deficiency, program=program)


def abstractor_at_capacity(client: ApiClient, world=None, target=0.2):
    """A registrar sitting exactly at their derived capacity cap.

    A target of 0.2 cases per day multiplied by ten and rounded half up gives a
    cap of two open cases, so two assignments saturate the registrar.
    """
    world = world or registry_world(client)
    cap_abstractor = create_abstractor(
        client,
        world["program"]["id"],
        name="Capped Registrar",
        credential="TRAINEE",
        productivity_target_cases_per_day=target,
    )
    cases = []
    for index in range(2):
        entry = create_entry(
            client, world["source"]["id"], patient_mrn=f"MRN-CAP-{index + 1}"
        )
        decide_reportable(client, entry["id"])
        case = case_of_entry(client, entry["id"])
        cases.append(assign_case(client, case["id"], cap_abstractor["id"]))
    return dict(
        world,
        cap_abstractor=read_abstractor(client, cap_abstractor["id"]),
        cases=cases,
    )


def rework_round_at_cap(client: ApiClient, world=None, **kwargs):
    """An abstraction that has already used both permitted rework reopens.

    Three REWORK_REQUIRED verdicts with a reopen after the first two leave
    ``rework_round`` at two, which is the point at which reopening is refused.
    """
    state = reworked_case(client, world=world, **kwargs)
    abstraction_id = state["abstraction"]["id"]
    abstractor_id = state["working_abstractor_id"]
    reviewer_id = state["reviewer"]["id"]
    for _ in range(2):
        reopen_draft(client, abstraction_id, abstractor_id)
        submit_for_qa(client, abstraction_id, abstractor_id)
        qa_decision(client, abstraction_id, reviewer_id, "REWORK_REQUIRED")
    return dict(
        state,
        abstraction=get_success_data(
            client.get_abstraction(abstraction_id, REGISTRY_MANAGER)
        ),
        case=read_case(client, state["case"]["id"]),
    )


def auditor_at_window_capacity(client: ApiClient, world=None):
    """An auditor holding the two mutually overlapping windows they are allowed."""
    world = world or registry_world(client)
    first = completed_case(client, world=world)
    second = completed_case(client, world=world)
    auditor_id = world["reviewer"]["id"]
    audit_one = open_audit(
        client,
        first["abstraction"]["id"],
        auditor_id,
        window_start="2026-07-01",
        window_end="2026-07-31",
    )
    audit_two = open_audit(
        client,
        second["abstraction"]["id"],
        auditor_id,
        window_start="2026-07-15",
        window_end="2026-08-15",
    )
    return dict(
        world,
        first=first,
        second=second,
        auditor_id=auditor_id,
        audit_one=audit_one,
        audit_two=audit_two,
    )


def critical_fail_cascade(client: ApiClient, world=None, **kwargs):
    """A CRITICAL_FAIL audit that dragged an APPROVED abstraction into rework."""
    audited_field_count = kwargs.pop("audited_field_count", 40)
    critical = kwargs.pop("critical_discrepancy_count", 1)
    state = approved_abstraction_with_open_audit(client, world=world, **kwargs)
    audit = score_audit(
        client,
        state["audit"]["id"],
        state["reviewer"]["id"],
        audited_field_count=audited_field_count,
        critical_discrepancy_count=critical,
    )
    return dict(
        state,
        audit=audit,
        abstraction=get_success_data(
            client.get_abstraction(state["abstraction"]["id"], REGISTRY_MANAGER)
        ),
        case=read_case(client, state["case"]["id"]),
    )


def rejected_deficiency_response(client: ApiClient, world=None, severity="MAJOR"):
    """A deficiency whose first response has been rejected once."""
    world = world or registry_world(client)
    deficiency = cite_deficiency(client, world["program"]["id"], severity)
    respond_to_deficiency(client, deficiency["id"], ACCREDITATION_COORDINATOR)
    deficiency = review_deficiency(
        client, deficiency["id"], "REJECTED", COC_SURVEYOR
    )
    return dict(world, deficiency=deficiency)


def credited_sessions(client: ApiClient, program_id, schedule, coordinator_ref=None):
    """Drive a list of (start_at, end_at) slots through to CREDITED.

    Quorum needs every required discipline present for at least 30 minutes and a
    prospective ratio of at least 0.80, so each session presents five cases with
    four of them prospective.
    """
    disciplines = [
        "SURGERY",
        "MEDICAL_ONCOLOGY",
        "RADIATION_ONCOLOGY",
        "PATHOLOGY",
        "RADIOLOGY",
    ]
    sessions = []
    for index, (start_at, end_at) in enumerate(schedule):
        session = create_session(
            client, program_id, start_at=start_at, end_at=end_at
        )
        for slot, discipline in enumerate(disciplines):
            ref = (
                coordinator_ref
                if coordinator_ref and slot == 0
                else f"attendee-{index + 1}-{slot + 1}"
            )
            record_attendance(
                client,
                session["id"],
                ref,
                discipline,
                attended_minutes=45,
                is_required_coordinator=(slot == 0 and coordinator_ref is not None),
            )
        set_clock(client, start_at)
        hold_session(client, session["id"], 5, 4)
        sessions.append(credit_session(client, session["id"], "CREDIT"))
    return sessions


# ============================================================================
# Tier 5 — finalization and terminal states
# ============================================================================


def survey_scheduled_program(client: ApiClient, world=None, survey_date="2026-12-01"):
    """A program moved ACCREDITED -> SURVEY_SCHEDULED."""
    world = world or registry_world(client)
    program = get_success_data(
        client.survey_schedule(
            world["program"]["id"],
            f.survey_schedule_payload(survey_date=survey_date),
            ACCREDITATION_COORDINATOR,
        )
    )
    return dict(world, program=program)


def survey_completed_program(client: ApiClient, world=None, completed_on="2026-08-01",
                             surveyor_headers=None):
    """A completed survey with no open MAJOR or CRITICAL deficiency: back to ACCREDITED."""
    state = survey_scheduled_program(client, world=world)
    program = get_success_data(
        client.survey_complete(
            state["program"]["id"],
            f.survey_complete_payload(completed_on=completed_on),
            surveyor_headers or COC_SURVEYOR,
        )
    )
    return dict(state, program=program)


def deficiency_response_program(client: ApiClient, world=None, completed_on="2026-08-01",
                                surveyor_headers=None):
    """A completed survey with one open MAJOR deficiency: into DEFICIENCY_RESPONSE."""
    world = world or registry_world(client)
    deficiency = cite_deficiency(client, world["program"]["id"], "MAJOR")
    state = survey_scheduled_program(client, world=world)
    program = get_success_data(
        client.survey_complete(
            state["program"]["id"],
            f.survey_complete_payload(completed_on=completed_on),
            surveyor_headers or COC_SURVEYOR,
        )
    )
    return dict(state, program=program, deficiency=deficiency)


def accreditation_decision_ready_program(client: ApiClient, world=None):
    """A program in DEFICIENCY_RESPONSE whose only deficiency has been resolved.

    Both ACCREDIT gates are then clear: no open MAJOR or CRITICAL deficiency
    remains and a program with no completed cases reports a Commission-variant
    follow-up rate of 100.0.
    """
    state = deficiency_response_program(client, world=world)
    respond_to_deficiency(client, state["deficiency"]["id"], ACCREDITATION_COORDINATOR)
    deficiency = review_deficiency(
        client, state["deficiency"]["id"], "ACCEPTED", COC_SURVEYOR_2
    )
    return dict(
        state,
        deficiency=deficiency,
        program=read_program(client, state["program"]["id"]),
    )


def probation_program(client: ApiClient, world=None):
    """A second rejected response escalates the deficiency and lands PROBATION."""
    state = rejected_deficiency_response(client, world=world)
    respond_to_deficiency(client, state["deficiency"]["id"], ACCREDITATION_COORDINATOR_2)
    deficiency = review_deficiency(
        client, state["deficiency"]["id"], "REJECTED", COC_SURVEYOR
    )
    program = read_program(client, state["program"]["id"])
    assert program["accreditation_state"] == "PROBATION", program["accreditation_state"]
    return dict(state, deficiency=deficiency, program=program)


def withdrawn_program(client: ApiClient, world=None):
    """A withdrawn program: terminal, and permanently frozen."""
    state = probation_program(client, world=world)
    program = get_success_data(
        client.accreditation_decision(
            state["program"]["id"],
            f.accreditation_decision_payload(decision="WITHDRAW"),
            COC_SURVEYOR_2,
        )
    )
    return dict(state, program=program)


def voided_audit_after_cascade(client: ApiClient, world=None, **kwargs):
    """A CRITICAL_FAIL cascade that has then been fully reversed by a void."""
    state = critical_fail_cascade(client, world=world, **kwargs)
    audit = void_audit(client, state["audit"]["id"])
    return dict(
        state,
        audit=audit,
        abstraction=get_success_data(
            client.get_abstraction(state["abstraction"]["id"], REGISTRY_MANAGER)
        ),
        case=read_case(client, state["case"]["id"]),
    )


def project_required_measure(client: ApiClient, world=None, **measure_overrides):
    """A measure that came in under threshold and now owes a project."""
    world = world or registry_world(client)
    measure = create_measure(client, world["program"]["id"], **measure_overrides)
    measure = evaluate_measure(
        client, measure["id"], [f.stratum("STAGE_I", 10, 5)]
    )
    return dict(world, measure=measure)


def project_active_measure(client: ApiClient, world=None, target_rate_pct=80.0,
                           **measure_overrides):
    state = project_required_measure(client, world=world, **measure_overrides)
    measure = improvement_project(
        client,
        state["measure"]["id"],
        "OPEN",
        project_title="Raise radiation therapy compliance",
        target_rate_pct=target_rate_pct,
    )
    return dict(state, measure=measure)


def held_session(client: ApiClient, world=None, presented=5, prospective=4,
                 start_at="2026-08-05T13:00:00Z", end_at="2026-08-05T14:00:00Z",
                 disciplines=None, attended_minutes=45,
                 coordinator_ref="coord-1", **session_overrides):
    """A session held after the clock reached its start instant."""
    world = world or registry_world(client)
    disciplines = disciplines or [
        "SURGERY",
        "MEDICAL_ONCOLOGY",
        "RADIATION_ONCOLOGY",
        "PATHOLOGY",
        "RADIOLOGY",
    ]
    session = create_session(
        client,
        world["program"]["id"],
        start_at=start_at,
        end_at=end_at,
        **session_overrides,
    )
    for index, discipline in enumerate(disciplines):
        record_attendance(
            client,
            session["id"],
            coordinator_ref if index == 0 else f"attendee-{index + 1}",
            discipline,
            attended_minutes=attended_minutes,
            is_required_coordinator=(index == 0),
        )
    set_clock(client, end_at)
    session = hold_session(client, session["id"], presented, prospective)
    return dict(world, session=session)


def completed_case_late(client: ApiClient, world=None, first_contact_date="2025-01-15",
                        diagnosis_date="2025-01-10", completion_instant="2026-08-01T00:00:00Z",
                        **kwargs):
    """A case completed after its abstract due date, so it reports LATE.

    With the default 180-day standard a first contact in January 2025 is due in
    July 2025, which the logical clock has already passed.
    """
    state = completed_case(
        client,
        world=world,
        diagnosis_date=diagnosis_date,
        first_contact_date=first_contact_date,
        **kwargs,
    )
    return state
