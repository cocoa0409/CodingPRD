"""Bounded rework cycles and two independent state dimensions on one row."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_abstraction,
    assert_ok,
    factories as f,
    get_success_data,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
)


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


def _breast_case_in_abstraction(api, coc_program_id, program_name, mrn, accession_date):
    program = _program(api, coc_program_id, program_name)
    author = _abstractor(api, program["id"], "Dana Whitfield")
    reviewer = _abstractor(api, program["id"], "Priya Raman")
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program["id"], source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )
    entry = get_success_data(
        api.create_casefinding_entry(
            source["id"],
            f.casefinding_entry_payload(
                patient_mrn=mrn,
                accession_date=accession_date,
                primary_site_code="C50.9",
                histology_code="8500/3",
                behavior_code="MALIGNANT_3",
                diagnosis_date="2026-03-02",
                first_contact_date="2026-03-09",
                diagnosed_at_facility=True,
                first_treatment_at_facility=True,
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    decided = get_success_data(
        api.reportability_decision(
            entry["id"], f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )
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
    return {
        "program": program,
        "author": author,
        "reviewer": reviewer,
        "source": source,
        "case": case,
        "abstraction": abstraction,
    }


def _submit(api, world):
    return get_success_data(
        api.submit_qa(
            world["abstraction"]["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(world["author"]["id"]),
        )
    )


def _verdict(api, world, verdict, note=f.OMIT):
    return get_success_data(
        api.qa_decision(
            world["abstraction"]["id"],
            f.qa_decision_payload(verdict, reviewer_note=note),
            make_qa_reviewer_headers(world["reviewer"]["id"]),
        )
    )


def _rework_exhausted_world(api):
    """Two reopens already spent, sitting in REWORK_REQUIRED for a third time."""
    world = _breast_case_in_abstraction(
        api, "COC-14555", "Mill Creek Cancer Program", "MRN-3401", "2026-08-05"
    )
    _submit(api, world)
    _verdict(api, world, "REWORK_REQUIRED", "stage group inconsistent with pathology report")
    get_success_data(
        api.reopen_draft(
            world["abstraction"]["id"],
            f.reopen_draft_payload(stage_group="STAGE_III"),
            make_registry_abstractor_headers(world["author"]["id"]),
        )
    )
    _submit(api, world)
    _verdict(api, world, "REWORK_REQUIRED", "treatment modality still incomplete")
    get_success_data(
        api.reopen_draft(
            world["abstraction"]["id"],
            f.reopen_draft_payload(treatment_modalities=["SURGERY", "CHEMOTHERAPY"]),
            make_registry_abstractor_headers(world["author"]["id"]),
        )
    )
    _submit(api, world)
    _verdict(
        api, world, "REWORK_REQUIRED", "third pass still disagrees with the pathology report"
    )
    return world


def test_third_reopen_of_the_rework_cycle_is_refused_at_the_round_cap(api):
    """The identical reopen call that worked twice now hits the bound.

    PRD 3.3: "Each reopen increments `rework_round` by one, and reopening is
    permitted only while `rework_round` is strictly below two — so the first and
    second reopens succeed and the third is refused with
    `ERR_REWORK_LIMIT_EXCEEDED`, at which point the only ways forward are
    supersession or rejection."

    Design: Difficulty/non_linear_state_machine/abstraction_rework_cycle_reenters_draft_twice_then_hits_round_cap
    """
    world = _rework_exhausted_world(api)

    response = api.reopen_draft(
        world["abstraction"]["id"],
        f.reopen_draft_payload(stage_group="STAGE_II"),
        make_registry_abstractor_headers(world["author"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED.value, 409)

    abstraction = assert_abstraction(
        assert_ok(api.get_abstraction(world["abstraction"]["id"], REGISTRY_MANAGER))
    )
    assert abstraction["rework_round"] == 2
    assert abstraction["abstraction_state"] == "REWORK_REQUIRED"


def test_refused_reopen_applies_none_of_its_field_updates(api):
    """The rejected payload's stage_group never lands on the abstract.

    PRD 3.3: "The registrar who owns a `REWORK_REQUIRED` abstraction may
    re-enter `DRAFT` on it, supplying revised values for any of `stage_source`,
    `t_category`, `n_category`, `m_category`, `stage_group`,
    `first_treatment_date`, `treatment_modalities`, `radiation_start_date`,
    `diagnostic_confirmation_code`, `outcome_status`, and `last_contact_date`;
    whatever is supplied is applied, and then `missing_required_fields` and
    `completeness_score` are recomputed against the revised values."

    Design: Difficulty/non_linear_state_machine/abstraction_rework_cycle_reenters_draft_twice_then_hits_round_cap
    """
    world = _rework_exhausted_world(api)

    api.reopen_draft(
        world["abstraction"]["id"],
        f.reopen_draft_payload(stage_group="STAGE_II"),
        make_registry_abstractor_headers(world["author"]["id"]),
    )

    abstraction = assert_ok(
        api.get_abstraction(world["abstraction"]["id"], REGISTRY_MANAGER)
    )
    assert abstraction["stage_group"] == "STAGE_III"

    case = assert_ok(api.get_case(world["case"]["id"], REGISTRY_MANAGER))
    assert case["case_state"] == "IN_ABSTRACTION"

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["assigned_open_case_count"] == 1


def _transmitted_case_with_open_audit(api):
    """A COMPLETED case that is already out in a transmitted batch."""
    world = _breast_case_in_abstraction(
        api, "COC-14556", "Granite Bay Cancer Program", "MRN-3501", "2026-08-05"
    )
    _submit(api, world)
    _verdict(api, world, "APPROVED")

    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                world["program"]["id"],
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
            f.submission_item_payload(world["case"]["id"], batch["version"]),
            REGISTRY_MANAGER,
        )
    )
    get_success_data(
        api.transmit_submission(batch["id"], f.transmit_payload(), REGISTRY_MANAGER)
    )
    audit = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                world["abstraction"]["id"],
                world["reviewer"]["id"],
                audit_type="ROUTINE_10PCT",
                window_start="2026-07-20",
                window_end="2026-08-10",
            ),
            make_qa_reviewer_headers(world["reviewer"]["id"]),
        )
    )
    world["batch"] = batch
    world["item"] = item
    world["audit"] = audit
    return world


def _score_critical(api, world):
    return api.score_qa_audit(
        world["audit"]["id"],
        f.audit_score_payload(audited_field_count=40, critical_discrepancy_count=1),
        make_qa_reviewer_headers(world["reviewer"]["id"]),
    )


def test_audit_cascade_leaves_the_submission_dimension_of_the_case_untouched(api):
    """The abstraction dimension regresses while the submission dimension holds.

    PRD 3.4: "The case's `submission_state` is pointedly not touched — the two
    dimensions on the row are independent."

    Design: Difficulty/non_linear_state_machine/case_abstraction_and_submission_dimensions_advance_independently
    """
    world = _transmitted_case_with_open_audit(api)

    assert_ok(_score_critical(api, world))

    case = assert_ok(api.get_case(world["case"]["id"], REGISTRY_MANAGER))
    assert case["case_state"] == "REWORK_PENDING"
    assert case["submission_state"] == "SUBMITTED"
    assert case["completed_on"] is None

    batch = assert_ok(api.get_submission(world["batch"]["id"], REGISTRY_MANAGER))
    assert batch["submission_state"] == "TRANSMITTED"

    item = assert_ok(api.get_submission_item(world["item"]["id"], REGISTRY_MANAGER))
    assert item["edit_status"] == "PENDING"


def test_critical_fail_cascade_marks_itself_and_returns_the_case_to_the_worklist(api):
    """The audit records the cascade it applied and the workload counter rises.

    PRD 3.4: "When the verdict is `CRITICAL_FAIL` and the audited abstraction is
    still `APPROVED`, the audit sets `cascade_applied` to true, drags that
    abstraction `APPROVED → REWORK_REQUIRED`, and moves its case `COMPLETED →
    REWORK_PENDING` with `completed_on` cleared to null and the author's
    `assigned_open_case_count` incremented by one; the program's backlog counts
    and posture are then recomputed, and a posture that becomes `FROZEN` moves
    every draft batch to hold."

    Design: Difficulty/non_linear_state_machine/case_abstraction_and_submission_dimensions_advance_independently
    """
    world = _transmitted_case_with_open_audit(api)

    audit = assert_ok(_score_critical(api, world))
    assert audit["cascade_applied"] is True
    assert audit["verdict"] == "CRITICAL_FAIL"

    abstraction = assert_ok(
        api.get_abstraction(world["abstraction"]["id"], REGISTRY_MANAGER)
    )
    assert abstraction["abstraction_state"] == "REWORK_REQUIRED"

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["assigned_open_case_count"] == 1

    program = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert program["registry_posture"] == "OPEN"
