"""Gates that read another entity's state, and ledgers that must come back."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_discrepancy_points_conserved,
    assert_ok,
    assert_reportable_case_parity,
    assert_workload_ledger_conserved,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_coc_surveyor_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
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


def _abstractor(api, program_id, name):
    return get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program_id,
                name=name,
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )


def _source(api, program_id):
    return get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program_id, source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )


def _entry(api, source_id, headers, **overrides):
    return get_success_data(
        api.create_casefinding_entry(
            source_id, f.casefinding_entry_payload(**overrides), headers
        )
    )


def _mint(api, entry_id):
    return get_success_data(
        api.reportability_decision(
            entry_id, f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )


# --------------------------------------------------------------------------
# case_assignment_gated_by_critical_deficiency_state_on_another_entity
# --------------------------------------------------------------------------
def _frozen_by_critical_deficiency(api):
    program = _program(api, "COC-14563", "Westbrook Cancer Program")
    author = _abstractor(api, program["id"], "Dana Whitfield")
    source = _source(api, program["id"])
    entry = _entry(
        api,
        source["id"],
        REGISTRY_MANAGER,
        patient_mrn="MRN-4001",
        accession_date="2026-08-05",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-06-02",
        first_contact_date="2026-06-09",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    decided = _mint(api, entry["id"])
    deficiency = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"],
                severity="CRITICAL",
                standard_code="STD-5.4",
                cited_on="2026-08-01",
                evidence_reference="survey-finding-5.4",
            ),
            SURVEYOR,
        )
    )
    return {
        "program": program,
        "author": author,
        "case_id": decided["created_case_id"],
        "deficiency": deficiency,
    }


def _assign(api, world):
    return api.assign_case(
        world["case_id"], f.assign_payload(world["author"]["id"]), REGISTRY_MANAGER
    )


def test_assignment_is_blocked_while_a_critical_deficiency_stands(api):
    """The gate lives on a deficiency two entities away from the case.

    PRD 2.7: "While a program is frozen it accepts no new case assignment, no new
    abstraction, no new submission item, no transmit, and no retransmit; each such
    attempt is rejected with `ERR_REGISTRY_FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/case_assignment_gated_by_critical_deficiency_state_on_another_entity
    """
    world = _frozen_by_critical_deficiency(api)

    validate_error(_assign(api, world), ApiErrorId.ERR_REGISTRY_FROZEN.value, 409)

    case = assert_ok(api.get_case(world["case_id"], REGISTRY_MANAGER))
    assert case["case_state"] == "IDENTIFIED"
    assert case["assigned_abstractor_id"] is None


def test_resolving_the_deficiency_lets_the_identical_assignment_through(api):
    """Accepting the response thaws the registry and the same call now succeeds.

    PRD 3.9: "`ACCEPTED` moves the deficiency `RESPONSE_SUBMITTED → RESOLVED`,
    which is terminal, stores `reviewer_notes`, recomputes
    `open_critical_deficiency_count`, recomputes `registry_posture`, and — because
    the posture may have just left `FROZEN` — restores every held batch to its
    `pre_hold_state`."

    Design: Difficulty/cross_entity_state_dependency/case_assignment_gated_by_critical_deficiency_state_on_another_entity
    """
    world = _frozen_by_critical_deficiency(api)
    _assign(api, world)

    get_success_data(
        api.respond_to_deficiency(
            world["deficiency"]["id"],
            f.deficiency_response_payload(
                response_narrative="corrective action plan filed with evidence",
                evidence_reference="cap-5.4",
            ),
            COORDINATOR,
        )
    )
    reviewed = assert_ok(
        api.review_deficiency_response(
            world["deficiency"]["id"],
            f.deficiency_review_payload("ACCEPTED", reviewer_notes="plan accepted"),
            SURVEYOR,
        )
    )
    assert reviewed["deficiency_state"] == "RESOLVED"

    program = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert program["open_critical_deficiency_count"] == 0
    assert program["registry_posture"] == "OPEN"

    case = assert_ok(_assign(api, world))
    assert case["case_state"] == "ASSIGNED"
    assert case["assigned_abstractor_id"] == world["author"]["id"]

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["assigned_open_case_count"] == 1


# --------------------------------------------------------------------------
# transmit_requires_every_item_case_completed_after_audit_regression
# --------------------------------------------------------------------------
def _draft_batch_with_regressed_case(api):
    program = _program(api, "COC-14564", "Halstead Cancer Program")
    author = _abstractor(api, program["id"], "Dana Whitfield")
    auditor = _abstractor(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    entry = _entry(
        api,
        source["id"],
        make_registry_abstractor_headers(author["id"]),
        patient_mrn="MRN-4101",
        accession_date="2026-08-05",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-03-02",
        first_contact_date="2026-03-09",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    decided = _mint(api, entry["id"])
    case = get_success_data(
        api.assign_case(
            decided["created_case_id"], f.assign_payload(author["id"]), REGISTRY_MANAGER
        )
    )
    abstraction = get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case["id"],
                author["id"],
                case["version"],
                stage_source="PATHOLOGIC",
                t_category="T2",
                n_category="N0",
                m_category="M0",
                stage_group="STAGE_II",
                first_treatment_date="2026-03-20",
                treatment_modalities=["SURGERY"],
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                outcome_status="ALIVE_NO_EVIDENCE",
                last_contact_date="2026-07-01",
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
    get_success_data(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(auditor["id"]),
        )
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
    item = get_success_data(
        api.add_submission_item(
            batch["id"],
            f.submission_item_payload(case["id"], batch["version"]),
            REGISTRY_MANAGER,
        )
    )
    audit = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                abstraction["id"],
                auditor["id"],
                audit_type="PRE_SURVEY",
                window_start="2026-07-25",
                window_end="2026-08-05",
            ),
            make_qa_reviewer_headers(auditor["id"]),
        )
    )
    get_success_data(
        api.score_qa_audit(
            audit["id"],
            f.audit_score_payload(audited_field_count=40, critical_discrepancy_count=1),
            make_qa_reviewer_headers(auditor["id"]),
        )
    )
    return {"program": program, "batch": batch, "item": item, "case_id": case["id"]}


def test_transmit_is_blocked_by_one_member_case_that_left_completed(api):
    """The batch is a valid DRAFT; only the reachable case state blocks it.

    PRD 3.6: "Four gates guard it in a fixed order, as recorded in §2.11: the
    batch must be in `DRAFT`, which is also what a held or already-transmitted
    batch fails on; the posture must not be `FROZEN` (`ERR_REGISTRY_FROZEN`); the
    batch must contain at least one item (`ERR_SUBMISSION_EMPTY`); every item's
    case must still be `COMPLETED`, so a case dragged back into rework by an
    audit blocks the batch with `ERR_CASE_NOT_COMPLETED`; and last of all, any
    outstanding assessment blocks it with `ERR_ASSESSMENT_UNPAID`."

    Design: Difficulty/cross_entity_state_dependency/transmit_requires_every_item_case_completed_after_audit_regression
    """
    world = _draft_batch_with_regressed_case(api)

    response = api.transmit_submission(
        world["batch"]["id"], f.transmit_payload(), REGISTRY_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_CASE_NOT_COMPLETED.value, 409)

    program = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert program["registry_posture"] == "OPEN"


def test_blocked_transmit_leaves_the_batch_and_its_item_as_they_were(api):
    """Nothing about the draft batch or its item moves on the refusal.

    PRD 3.6: "Transmission moves the batch `DRAFT → TRANSMITTED` and every item's
    case `PENDING_SUBMISSION → SUBMITTED`, stamps `transmitted_at` from the
    logical clock, increments the batch `version` by one, and may carry a
    `transmit_note`; items themselves stay `PENDING` because no results have come
    back yet."

    Design: Difficulty/cross_entity_state_dependency/transmit_requires_every_item_case_completed_after_audit_regression
    """
    world = _draft_batch_with_regressed_case(api)

    api.transmit_submission(world["batch"]["id"], f.transmit_payload(), REGISTRY_MANAGER)

    batch = assert_ok(api.get_submission(world["batch"]["id"], REGISTRY_MANAGER))
    assert batch["submission_state"] == "DRAFT"
    assert batch["transmitted_at"] is None
    assert batch["total_case_count"] == 1

    case = assert_ok(api.get_case(world["case_id"], REGISTRY_MANAGER))
    assert case["case_state"] == "REWORK_PENDING"
    assert case["submission_state"] == "PENDING_SUBMISSION"

    item = assert_ok(api.get_submission_item(world["item"]["id"], REGISTRY_MANAGER))
    assert item["edit_status"] == "PENDING"


# --------------------------------------------------------------------------
# workload_ledger_conserved_across_assign_unassign_and_entry_reopen_void
# --------------------------------------------------------------------------
def _two_assigned_cases(api):
    program = _program(api, "COC-14567", "Marlowe Cancer Program")
    author = _abstractor(api, program["id"], "Dana Whitfield")
    source = _source(api, program["id"])
    entry_1 = _entry(
        api,
        source["id"],
        REGISTRY_MANAGER,
        patient_mrn="MRN-4301",
        accession_date="2026-08-03",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-06-02",
        first_contact_date="2026-06-09",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    entry_2 = _entry(
        api,
        source["id"],
        REGISTRY_MANAGER,
        patient_mrn="MRN-4302",
        accession_date="2026-08-04",
        primary_site_code="C34.1",
        histology_code="8140/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-06-02",
        first_contact_date="2026-06-10",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    case_1_id = _mint(api, entry_1["id"])["created_case_id"]
    case_2_id = _mint(api, entry_2["id"])["created_case_id"]
    get_success_data(
        api.assign_case(case_1_id, f.assign_payload(author["id"]), REGISTRY_MANAGER)
    )
    get_success_data(
        api.assign_case(case_2_id, f.assign_payload(author["id"]), REGISTRY_MANAGER)
    )
    return {
        "program": program,
        "author": author,
        "entry_2": entry_2,
        "case_1_id": case_1_id,
        "case_2_id": case_2_id,
    }


def test_release_and_entry_reopen_both_return_the_workload_ledger(api):
    """Two different compensating paths bring the same counter back to zero.

    PRD 2.12: "For any program, the sum of `assigned_open_case_count` across all
    its registrars always equals the number of that program's tumor cases which
    have a non-null `assigned_abstractor_id` and a case state of `ASSIGNED`,
    `IN_ABSTRACTION`, `QA_PENDING`, or `REWORK_PENDING`."

    Design: Difficulty/compensating_invariant/workload_ledger_conserved_across_assign_unassign_and_entry_reopen_void
    """
    world = _two_assigned_cases(api)
    before = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert before["assigned_open_case_count"] == 2

    released = assert_ok(
        api.unassign_case(
            world["case_1_id"],
            f.unassign_payload(unassign_reason="reassigning to the breast site team"),
            REGISTRY_MANAGER,
        )
    )
    assert released["case_state"] == "IDENTIFIED"
    assert released["assigned_abstractor_id"] is None
    midway = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert midway["assigned_open_case_count"] == 1

    assert_ok(
        api.reopen_casefinding_entry(
            world["entry_2"]["id"],
            f.entry_reopen_payload(
                reopen_reason="pathology report amended; behavior code under re-review"
            ),
            REGISTRY_MANAGER,
        )
    )
    case_2 = assert_ok(api.get_case(world["case_2_id"], REGISTRY_MANAGER))
    assert case_2["case_state"] == "VOIDED"
    after = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert after["assigned_open_case_count"] == 0

    assert_workload_ledger_conserved(api, REGISTRY_MANAGER, world["program"]["id"])


def test_reopening_the_entry_restores_parity_and_clears_its_decision(api):
    """The voided case leaves the population and the entry is answerable again.

    PRD 2.12: "For any program, the number of its tumor cases whose case state is
    not `VOIDED` equals the number of its casefinding entries whose
    `reportability_state` is `REPORTABLE`, and both equal the program's
    `identified_case_count`."

    Design: Difficulty/compensating_invariant/workload_ledger_conserved_across_assign_unassign_and_entry_reopen_void
    """
    world = _two_assigned_cases(api)
    get_success_data(
        api.unassign_case(
            world["case_1_id"],
            f.unassign_payload(unassign_reason="reassigning to the breast site team"),
            REGISTRY_MANAGER,
        )
    )

    entry = assert_ok(
        api.reopen_casefinding_entry(
            world["entry_2"]["id"],
            f.entry_reopen_payload(
                reopen_reason="pathology report amended; behavior code under re-review"
            ),
            REGISTRY_MANAGER,
        )
    )
    assert entry["reportability_state"] == "PENDING_REVIEW"
    assert entry["created_case_id"] is None
    assert entry["reopen_count"] == 1
    assert entry["decision_reason_code"] is None

    program = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert program["identified_case_count"] == 1
    assert program["registry_posture"] == "OPEN"
    assert program["open_critical_deficiency_count"] == 0

    assert_reportable_case_parity(api, REGISTRY_MANAGER, world["program"]["id"])


# --------------------------------------------------------------------------
# discrepancy_points_and_rework_cascade_fully_reversed_by_audit_void
# --------------------------------------------------------------------------
def _scored_critical_audit(api):
    program = _program(api, "COC-14568", "Ashfield Cancer Program")
    author = _abstractor(api, program["id"], "Dana Whitfield")
    auditor = _abstractor(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    entry = _entry(
        api,
        source["id"],
        REGISTRY_MANAGER,
        patient_mrn="MRN-4401",
        accession_date="2026-08-03",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-03-02",
        first_contact_date="2026-03-09",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    decided = _mint(api, entry["id"])
    case = get_success_data(
        api.assign_case(
            decided["created_case_id"], f.assign_payload(author["id"]), REGISTRY_MANAGER
        )
    )
    abstraction = get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case["id"],
                author["id"],
                case["version"],
                stage_source="PATHOLOGIC",
                t_category="T2",
                n_category="N0",
                m_category="M0",
                stage_group="STAGE_II",
                first_treatment_date="2026-03-20",
                treatment_modalities=["SURGERY"],
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                outcome_status="ALIVE_NO_EVIDENCE",
                last_contact_date="2026-07-01",
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
    get_success_data(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(auditor["id"]),
        )
    )
    audit = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                abstraction["id"],
                auditor["id"],
                audit_type="ROUTINE_10PCT",
                window_start="2026-07-25",
                window_end="2026-08-05",
            ),
            make_qa_reviewer_headers(auditor["id"]),
        )
    )
    get_success_data(
        api.score_qa_audit(
            audit["id"],
            f.audit_score_payload(audited_field_count=40, critical_discrepancy_count=1),
            make_qa_reviewer_headers(auditor["id"]),
        )
    )
    return {
        "program": program,
        "author": author,
        "abstraction": abstraction,
        "audit": audit,
        "case_id": case["id"],
    }


def _void(api, world):
    return api.void_qa_audit(
        world["audit"]["id"],
        f.audit_void_payload(
            void_reason="audit was opened against the wrong accession; findings withdrawn"
        ),
        REGISTRY_MANAGER,
    )


def test_voiding_the_audit_subtracts_exactly_the_points_it_added(api):
    """Five points and both quality scores return to their pre-score values.

    PRD 2.12: "A registrar's `lifetime_discrepancy_points` always equals the sum
    of `weighted_error_score` over every audit whose audited abstraction was
    produced by that registrar and whose audit state is `CLOSED_PASS` or
    `CLOSED_FAIL`."

    Design: Difficulty/compensating_invariant/discrepancy_points_and_rework_cascade_fully_reversed_by_audit_void
    """
    world = _scored_critical_audit(api)
    before = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert before["lifetime_discrepancy_points"] == 5
    assert before["quality_score_rolling_90d"] == 87.5
    assert before["quality_score_cumulative"] == 97.5
    assert before["audit_fail_streak"] == 1
    assert before["assigned_open_case_count"] == 1

    voided = assert_ok(_void(api, world))
    assert voided["audit_state"] == "VOIDED"

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["lifetime_discrepancy_points"] == 0
    assert author["quality_score_rolling_90d"] == 100.0
    assert author["quality_score_cumulative"] == 100.0
    assert author["audit_fail_streak"] == 0
    assert author["employment_status"] == "ACTIVE"

    assert_discrepancy_points_conserved(api, REGISTRY_MANAGER, world["author"]["id"])


def test_voiding_the_audit_unwinds_the_rework_cascade_it_applied(api):
    """The case returns to COMPLETED with the completion date it originally had.

    PRD 3.4: "Voiding a `CLOSED_FAIL` audit does the same subtraction, decrements
    `audit_fail_streak` by one with a floor of zero (recomputed from the remaining
    non-voided audits), and — if `cascade_applied` was true and the audited
    abstraction is still `REWORK_REQUIRED` with no superseding abstraction —
    unwinds the rework cascade as well: the abstraction returns `REWORK_REQUIRED →
    APPROVED`, the case returns `REWORK_PENDING → COMPLETED` with `completed_on`
    restored to the value it held before the audit cascade rather than reset to
    the current clock date, the author's `assigned_open_case_count` is decremented
    by one, and the program aggregates and posture are recomputed."

    Design: Difficulty/compensating_invariant/discrepancy_points_and_rework_cascade_fully_reversed_by_audit_void
    """
    world = _scored_critical_audit(api)

    assert_ok(_void(api, world))

    abstraction = assert_ok(
        api.get_abstraction(world["abstraction"]["id"], REGISTRY_MANAGER)
    )
    assert abstraction["abstraction_state"] == "APPROVED"

    case = assert_ok(api.get_case(world["case_id"], REGISTRY_MANAGER))
    assert case["case_state"] == "COMPLETED"
    assert case["completed_on"] == "2026-08-01"

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["assigned_open_case_count"] == 0

    program = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert program["registry_posture"] == "OPEN"

    assert_workload_ledger_conserved(api, REGISTRY_MANAGER, world["program"]["id"])
