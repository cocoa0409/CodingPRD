"""One write that propagates four links deep, in both directions."""

from test_helpers import (
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_deficiency,
    assert_ok,
    assert_program,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_coc_surveyor_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
)

SURVEYOR = make_coc_surveyor_headers("surv-nakamura")
COORDINATOR = make_accreditation_coordinator_headers("coord-lee")


def _program(api, coc_program_id, name):
    return get_success_data(
        api.create_program(
            f.program_payload(
                name=name,
                coc_program_id=coc_program_id,
                annual_analytic_caseload=620,
                reference_year=2018,
                timeliness_standard_days=180,
            ),
            PLATFORM_ADMIN,
        )
    )


def _frozen_by_overdue_backlog(api):
    """Two late QA_PENDING cases freeze the registry and hold the draft batch."""
    program = _program(api, "COC-14557", "Fairhaven Cancer Program")
    author = get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="Dana Whitfield",
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    reviewer = get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="Priya Raman",
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program["id"], source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )

    def _submitted_case(entry_overrides, abstraction_overrides):
        entry = get_success_data(
            api.create_casefinding_entry(
                source["id"],
                f.casefinding_entry_payload(**entry_overrides),
                make_registry_abstractor_headers(author["id"]),
            )
        )
        decided = get_success_data(
            api.reportability_decision(
                entry["id"],
                f.reportability_decision_payload("REPORTABLE"),
                REGISTRY_MANAGER,
            )
        )
        case = get_success_data(
            api.assign_case(
                decided["created_case_id"],
                f.assign_payload(author["id"]),
                REGISTRY_MANAGER,
            )
        )
        abstraction = get_success_data(
            api.create_abstraction(
                f.abstraction_payload(
                    case["id"],
                    author["id"],
                    case["version"],
                    stage_source="PATHOLOGIC",
                    treatment_modalities=["SURGERY"],
                    diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                    outcome_status="ALIVE_NO_EVIDENCE",
                    **abstraction_overrides,
                ),
                make_registry_abstractor_headers(author["id"]),
            )
        )
        get_success_data(
            api.submit_qa(
                abstraction["id"],
                f.submit_qa_payload(submit_note=f.OMIT),
                make_registry_abstractor_headers(author["id"]),
            )
        )
        return case["id"], abstraction["id"]

    case_k1_id, abst_k1_id = _submitted_case(
        {
            "patient_mrn": "MRN-3601",
            "accession_date": "2026-08-05",
            "primary_site_code": "C50.9",
            "histology_code": "8500/3",
            "behavior_code": "MALIGNANT_3",
            "diagnosis_date": "2026-03-02",
            "first_contact_date": "2026-03-09",
            "diagnosed_at_facility": True,
            "first_treatment_at_facility": True,
        },
        {
            "t_category": "T2",
            "n_category": "N0",
            "m_category": "M0",
            "stage_group": "STAGE_II",
            "first_treatment_date": "2026-03-20",
            "last_contact_date": "2026-07-01",
        },
    )
    case_k2_id, abst_k2_id = _submitted_case(
        {
            "patient_mrn": "MRN-3602",
            "accession_date": "2026-08-06",
            "primary_site_code": "C18.9",
            "histology_code": "8140/3",
            "behavior_code": "MALIGNANT_3",
            "diagnosis_date": "2026-03-15",
            "first_contact_date": "2026-03-20",
            "diagnosed_at_facility": True,
            "first_treatment_at_facility": True,
        },
        {
            "t_category": "T1",
            "n_category": "N0",
            "m_category": "M0",
            "stage_group": "STAGE_I",
            "first_treatment_date": "2026-04-01",
            "last_contact_date": "2026-07-05",
        },
    )

    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-01-01",
                period_end="2026-06-30",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    get_success_data(
        api.set_clock(f.clock_payload("2026-09-20T00:00:00Z"), PLATFORM_ADMIN)
    )
    return {
        "program": program,
        "author": author,
        "reviewer": reviewer,
        "case_k1_id": case_k1_id,
        "case_k2_id": case_k2_id,
        "abst_k1_id": abst_k1_id,
        "abst_k2_id": abst_k2_id,
        "batch": batch,
    }


def _approve_k1(api, world):
    return api.qa_decision(
        world["abst_k1_id"],
        f.qa_decision_payload("APPROVED", reviewer_note="abstract accepted"),
        make_qa_reviewer_headers(world["reviewer"]["id"]),
    )


def test_qa_approval_drops_the_overdue_count_and_unfreezes_the_registry(api):
    """One approval takes the overdue backlog from two to one and thaws the program.

    PRD 2.7: "The posture is then decided by four clauses evaluated in exactly
    this order, the first matching clause winning: if the program's
    `accreditation_state` is `PROBATION` or `WITHDRAWN`, the posture is `FROZEN`;
    otherwise, if `open_critical_deficiency_count` is at least 1, the posture is
    `FROZEN`; otherwise, if `overdue_backlog_count` is at least 2, the posture is
    `FROZEN`; otherwise, if `open_backlog_count` is at least 4, the posture is
    `RESTRICTED`; otherwise the posture is `OPEN`."

    Design: Difficulty/transitive_cascade/qa_approval_unfreezes_registry_and_releases_held_submission_depth4
    """
    world = _frozen_by_overdue_backlog(api)
    frozen = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert frozen["registry_posture"] == "FROZEN"

    assert_ok(_approve_k1(api, world))

    program = assert_program(
        assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    )
    assert program["overdue_backlog_count"] == 1
    assert program["open_backlog_count"] == 1
    assert program["registry_posture"] == "OPEN"


def test_leaving_frozen_returns_the_held_batch_and_clears_its_hold_marker(api):
    """The held batch goes back to DRAFT and pre_hold_state is emptied.

    PRD 2.7: "Whenever a recompute moves a program out of `FROZEN`, every
    submission of that program that is in `HOLD` moves `HOLD → DRAFT`, restored
    to the state recorded in `pre_hold_state` and that field is cleared back to
    null."

    Design: Difficulty/transitive_cascade/qa_approval_unfreezes_registry_and_releases_held_submission_depth4
    """
    world = _frozen_by_overdue_backlog(api)
    held = assert_ok(api.get_submission(world["batch"]["id"], REGISTRY_MANAGER))
    assert held["submission_state"] == "HOLD"
    assert held["pre_hold_state"] == "DRAFT"

    assert_ok(_approve_k1(api, world))

    batch = assert_ok(api.get_submission(world["batch"]["id"], REGISTRY_MANAGER))
    assert batch["submission_state"] == "DRAFT"
    assert batch["pre_hold_state"] is None


def test_approval_completes_the_case_late_and_recomputes_the_registrar_figures(api):
    """The approved case closes on the clock date, fifteen days past its due date.

    PRD 3.3: "`APPROVED` is the deepest cascade in the system: the abstraction
    moves `SUBMITTED_FOR_QA → APPROVED` with `approved_at` stamped from the
    clock; because the abstraction was approved the case moves `QA_PENDING →
    COMPLETED` with `completed_on` set to the clock date and `timeliness_status`
    finalised; because the case left the open backlog the registrar's
    `assigned_open_case_count` is decremented by one and their
    `completed_cases_30d`, `productivity_rate_per_day`, and `productivity_status`
    are recomputed; because the backlog shrank, `open_backlog_count`,
    `overdue_backlog_count`, and `registry_posture` are recomputed; and because
    the posture was recomputed, a posture that leaves `FROZEN` returns every held
    batch to its `pre_hold_state`."

    Design: Difficulty/transitive_cascade/qa_approval_unfreezes_registry_and_releases_held_submission_depth4
    """
    world = _frozen_by_overdue_backlog(api)

    abstraction = assert_ok(_approve_k1(api, world))
    assert abstraction["abstraction_state"] == "APPROVED"
    assert abstraction["approved_at"] == "2026-09-20T00:00:00.000Z"

    case_k1 = assert_ok(api.get_case(world["case_k1_id"], REGISTRY_MANAGER))
    assert case_k1["case_state"] == "COMPLETED"
    assert case_k1["completed_on"] == "2026-09-20"
    assert case_k1["timeliness_status"] == "LATE"
    assert case_k1["days_to_due"] == -15

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["assigned_open_case_count"] == 1
    assert author["completed_cases_30d"] == 1
    assert author["productivity_rate_per_day"] == 0.05
    assert author["productivity_status"] == "BELOW"

    case_k2 = assert_ok(api.get_case(world["case_k2_id"], REGISTRY_MANAGER))
    assert case_k2["case_state"] == "QA_PENDING"
    assert case_k2["timeliness_status"] == "LATE"


# --------------------------------------------------------------------------
# deficiency_second_rejection_escalates_to_probation_and_holds_submission_depth4
# --------------------------------------------------------------------------
def _deficiency_at_escalation_cap(api):
    """A MAJOR citation answered twice, rejected once, awaiting the second review."""
    program = _program(api, "COC-14558", "Oakridge Cancer Program")
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-01-01",
                period_end="2026-06-30",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    deficiency = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"],
                severity="MAJOR",
                standard_code="STD-6.1",
                cited_on="2026-08-01",
                evidence_reference="survey-finding-6.1",
            ),
            SURVEYOR,
        )
    )
    get_success_data(
        api.respond_to_deficiency(
            deficiency["id"],
            f.deficiency_response_payload(
                response_narrative="conference minutes attached for the missing months",
                evidence_reference="minutes-2026H1",
            ),
            COORDINATOR,
        )
    )
    get_success_data(
        api.review_deficiency_response(
            deficiency["id"],
            f.deficiency_review_payload(
                "REJECTED", reviewer_notes="minutes do not evidence attendance"
            ),
            SURVEYOR,
        )
    )
    get_success_data(
        api.respond_to_deficiency(
            deficiency["id"],
            f.deficiency_response_payload(
                response_narrative="attendance rosters added for all sessions"
            ),
            COORDINATOR,
        )
    )
    return {"program": program, "batch": batch, "deficiency": deficiency}


def _reject_again(api, world):
    return api.review_deficiency_response(
        world["deficiency"]["id"],
        f.deficiency_review_payload(
            "REJECTED", reviewer_notes="rosters still omit the required coordinator"
        ),
        SURVEYOR,
    )


def test_second_rejection_escalates_the_deficiency_at_the_cap(api):
    """The escalation counter reaching two turns the rejection terminal.

    PRD 3.9: "At the cap — that is, when incrementing `escalation_count` would
    reach two — the deficiency instead moves `RESPONSE_SUBMITTED → ESCALATED`,
    which is terminal, still incrementing `escalation_count`, and the consequence
    propagates four links deep: because the deficiency escalated, the program
    moves `ACCREDITED → PROBATION` if its `accreditation_state` was `ACCREDITED`,
    `SURVEY_SCHEDULED`, or `DEFICIENCY_RESPONSE`; because the program entered
    probation, `registry_posture` is recomputed to `FROZEN`; and because the
    posture became frozen, every draft batch of the program moves to `HOLD` with
    `pre_hold_state` recorded as `DRAFT`."

    Design: Difficulty/transitive_cascade/deficiency_second_rejection_escalates_to_probation_and_holds_submission_depth4
    """
    world = _deficiency_at_escalation_cap(api)

    deficiency = assert_deficiency(assert_ok(_reject_again(api, world)))

    assert deficiency["deficiency_state"] == "ESCALATED"
    assert deficiency["escalation_count"] == 2
    assert deficiency["response_due_date"] == "2026-09-30"


def test_escalation_puts_the_program_on_probation_and_holds_its_draft_batch(api):
    """Probation freezes the registry, which in turn holds the draft batch.

    PRD 2.7: "Whenever a recompute moves a program from `OPEN` or `RESTRICTED`
    into `FROZEN`, every submission of that program that is in `DRAFT` moves
    `DRAFT → HOLD` and has its `pre_hold_state` set to `DRAFT`."

    Design: Difficulty/transitive_cascade/deficiency_second_rejection_escalates_to_probation_and_holds_submission_depth4
    """
    world = _deficiency_at_escalation_cap(api)

    assert_ok(_reject_again(api, world))

    program = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert program["accreditation_state"] == "PROBATION"
    assert program["registry_posture"] == "FROZEN"

    batch = assert_ok(api.get_submission(world["batch"]["id"], REGISTRY_MANAGER))
    assert batch["submission_state"] == "HOLD"
    assert batch["pre_hold_state"] == "DRAFT"
