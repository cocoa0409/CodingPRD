"""Batch, conditional, and computed-read endpoints and their exact after-state."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    STATE_REGISTRY_LIAISON,
    assert_deficiency,
    assert_ok,
    assert_submission,
    assert_submission_item,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_coc_surveyor_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
    validate_paginated,
)

COORDINATOR = make_accreditation_coordinator_headers("user-coord-1")
SURVEYOR = make_coc_surveyor_headers("user-surveyor-1")


def _program(api):
    return get_success_data(
        api.create_program(
            f.program_payload(
                name="Northside Cancer Center",
                coc_program_id="COC-1456N",
                annual_analytic_caseload=300,
                reference_year=2018,
                timeliness_standard_days=180,
            ),
            PLATFORM_ADMIN,
        )
    )


def _registrar(api, program_id, name):
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


def _entry(api, source_id, **overrides):
    base = dict(
        patient_mrn="MRN-0001",
        accession_date="2026-08-03",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-07-01",
        first_contact_date="2026-07-05",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    base.update(overrides)
    return get_success_data(
        api.create_casefinding_entry(
            source_id, f.casefinding_entry_payload(**base), REGISTRY_MANAGER
        )
    )


def _mint(api, entry_id):
    return get_success_data(
        api.reportability_decision(
            entry_id, f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )["created_case_id"]


def _completed_case(api, source_id, author, reviewer, entry_overrides, abstraction_overrides):
    case_id = _mint(api, _entry(api, source_id, **entry_overrides)["id"])
    case = get_success_data(
        api.assign_case(case_id, f.assign_payload(author["id"]), REGISTRY_MANAGER)
    )
    abstraction = get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case_id,
                author["id"],
                case["version"],
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
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
    get_success_data(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(reviewer["id"]),
        )
    )
    return case_id


def _transmitted_batch(api, program_id, case_ids):
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program_id,
                period_start="2026-07-01",
                period_end="2026-07-31",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    items = []
    version = batch["version"]
    for case_id in case_ids:
        items.append(
            get_success_data(
                api.add_submission_item(
                    batch["id"], f.submission_item_payload(case_id, version), REGISTRY_MANAGER
                )
            )
        )
        version = get_success_data(api.get_submission(batch["id"], REGISTRY_MANAGER))["version"]
    get_success_data(
        api.transmit_submission(
            batch["id"], f.transmit_payload(transmit_note="July 2026 batch"), REGISTRY_MANAGER
        )
    )
    return batch, items


def test_a_partial_edit_results_batch_applies_nothing_at_all(api):
    """Coverage is all-or-nothing; only then may the outcomes differ per item.

    PRD 3.6: "The batch must be in `TRANSMITTED`
    (`ERR_SUBMISSION_NOT_TRANSMITTED`); every `case_id` in the array must name an
    item that belongs to this batch, and one that does not is
    `ERR_SUBMISSION_ITEM_NOT_FOUND` (HTTP 404); and the array must cover every item
    on the batch, a partial batch being `ERR_INVALID_REQUEST`."

    PRD 3.6: "The batch itself then forks: if every entry was accepted it reaches
    the terminal `TRANSMITTED → ACCEPTED`; if even one entry failed it goes
    `TRANSMITTED → EDITS_RETURNED`."

    Design: Corner/endpoints/edit_results_batch_omitting_an_item_is_rejected_then_splits_item_outcomes
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    case_1 = _completed_case(
        api,
        source["id"],
        author,
        reviewer,
        {},
        {"first_treatment_date": "2026-07-10", "last_contact_date": "2026-07-20"},
    )
    case_2 = _completed_case(
        api,
        source["id"],
        author,
        reviewer,
        {
            "patient_mrn": "MRN-0002",
            "accession_date": "2026-08-04",
            "primary_site_code": "C34.9",
            "histology_code": "8140/3",
            "diagnosis_date": "2026-07-02",
            "first_contact_date": "2026-07-06",
        },
        {
            "t_category": "T1",
            "stage_group": "STAGE_I",
            "first_treatment_date": "2026-07-12",
            "last_contact_date": "2026-07-21",
        },
    )
    batch, items = _transmitted_batch(api, program["id"], [case_1, case_2])
    transmitted = get_success_data(api.get_submission(batch["id"], REGISTRY_MANAGER))

    validate_error(
        api.post_edit_results(
            batch["id"],
            f.edit_results_payload([f.item_result(case_1, "ACCEPTED", [])]),
            STATE_REGISTRY_LIAISON,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    untouched = assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    assert untouched["submission_state"] == "TRANSMITTED"
    assert untouched["version"] == transmitted["version"]
    for item in items:
        assert assert_ok(api.get_submission_item(item["id"], REGISTRY_MANAGER))[
            "edit_status"
        ] == "PENDING"

    complete = assert_submission(
        assert_ok(
            api.post_edit_results(
                batch["id"],
                f.edit_results_payload(
                    [
                        f.item_result(case_1, "ACCEPTED", []),
                        f.item_result(case_2, "EDIT_FAILED", ["E-1004", "E-2210"]),
                    ]
                ),
                STATE_REGISTRY_LIAISON,
            )
        )
    )
    assert complete["submission_state"] == "EDITS_RETURNED"
    assert complete["accepted_item_count"] == 1
    assert complete["failed_item_count"] == 1
    assert complete["version"] == transmitted["version"] + 1
    assert complete["late_case_count"] == 0
    assert complete["relief_pct"] == 0.0
    assert complete["assessment_due_cents"] == 0

    accepted = assert_submission_item(
        assert_ok(api.get_submission_item(items[0]["id"], REGISTRY_MANAGER))
    )
    failed = assert_ok(api.get_submission_item(items[1]["id"], REGISTRY_MANAGER))
    assert accepted["edit_status"] == "ACCEPTED"
    assert accepted["edit_codes"] == []
    assert failed["edit_status"] == "EDIT_FAILED"
    assert failed["edit_codes"] == ["E-1004", "E-2210"]
    assert assert_ok(api.get_case(case_1, REGISTRY_MANAGER))["submission_state"] == "ACCEPTED"
    assert assert_ok(api.get_case(case_2, REGISTRY_MANAGER))["submission_state"] == "EDIT_REJECTED"


def test_retransmit_waits_for_the_resolution_and_only_then_releases_the_case(api):
    """Resolving moves the item; the case dimension waits for the batch to go back out.

    PRD 3.6: "The note is stored, the `edit_codes` are retained for audit rather
    than cleared, `failed_item_count` is decremented by one, and the case's own
    dimension deliberately stays `EDIT_REJECTED` until the whole batch goes back
    out."

    PRD 3.6: "Its gates fire in order: the batch must be in `EDITS_RETURNED`
    (`ERR_SUBMISSION_NOT_IN_EDIT_RESOLUTION`), `failed_item_count` must be zero
    (`ERR_UNRESOLVED_EDITS`), `resubmission_round` must be strictly below two so
    that the third retransmit is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`,
    the posture must not be `FROZEN`, and finally the assessment must be settled
    (`ERR_ASSESSMENT_UNPAID`)."

    Design: Corner/endpoints/retransmit_blocked_until_every_failed_item_is_resolved
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    case_id = _completed_case(
        api,
        source["id"],
        author,
        reviewer,
        {},
        {"first_treatment_date": "2026-07-10", "last_contact_date": "2026-07-20"},
    )
    batch, items = _transmitted_batch(api, program["id"], [case_id])
    get_success_data(
        api.post_edit_results(
            batch["id"],
            f.edit_results_payload([f.item_result(case_id, "EDIT_FAILED", ["E-1004"])]),
            STATE_REGISTRY_LIAISON,
        )
    )

    validate_error(
        api.retransmit_submission(
            batch["id"], f.retransmit_payload(retransmit_note="First attempt"), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_UNRESOLVED_EDITS.value,
        409,
    )
    blocked = assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    assert blocked["submission_state"] == "EDITS_RETURNED"
    assert blocked["resubmission_round"] == 0
    assert blocked["assessment_due_cents"] == 0

    resolved = assert_ok(
        api.resolve_submission_item(
            batch["id"],
            items[0]["id"],
            f.resolve_item_payload(
                resolution_note="Histology recoded to 8500/3 per pathology addendum"
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    assert resolved["edit_status"] == "RESOLVED"
    assert resolved["resolution_note"] == "Histology recoded to 8500/3 per pathology addendum"
    assert resolved["edit_codes"] == ["E-1004"]
    assert assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))["failed_item_count"] == 0
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))[
        "submission_state"
    ] == "EDIT_REJECTED"

    retransmitted = assert_ok(
        api.retransmit_submission(
            batch["id"],
            f.retransmit_payload(retransmit_note="Second attempt after edit resolution"),
            REGISTRY_MANAGER,
        )
    )
    assert retransmitted["submission_state"] == "TRANSMITTED"
    assert retransmitted["resubmission_round"] == 1
    assert retransmitted["transmitted_at"] == "2026-08-01T00:00:00.000Z"
    assert assert_ok(api.get_submission_item(items[0]["id"], REGISTRY_MANAGER))[
        "edit_status"
    ] == "PENDING"
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))["submission_state"] == "SUBMITTED"


def test_closing_a_project_below_the_threshold_auto_cites_a_major_deficiency(api):
    """The system cites itself, and a major citation leaves the posture open.

    PRD 3.8: "A `final_rate_pct` below `threshold_pct` moves it `PROJECT_ACTIVE →
    PROJECT_CLOSED_MISSED` and reaches across aggregates: because the project
    missed its threshold, the system auto-cites a deficiency against the program
    with `standard_code` `STD 7.3`, `severity` `MAJOR`, `cited_on` set to the
    logical clock date, `source_measure_id` set to this measure's `id`, and
    `deficiency_state` `CITED`."

    PRD 3.8: "Because a major deficiency is now open, the program's
    `registry_posture` is recomputed — a major deficiency on its own does not
    freeze the registry, only a critical one does, as §2.7 sets out — but the open
    deficiency does block an `ACCREDIT` decision until it is closed."

    Design: Corner/endpoints/improvement_project_close_below_threshold_auto_cites_major_deficiency
    """
    program = _program(api)
    measure = get_success_data(
        api.create_quality_measure(
            f.quality_measure_payload(
                program["id"], measure_code="BCSRT", measurement_year=2026, threshold_pct=80.0
            ),
            REGISTRY_MANAGER,
        )
    )
    evaluated = get_success_data(
        api.evaluate_quality_measure(
            measure["id"],
            f.evaluate_measure_payload([f.stratum("STAGE_II", 10, 6)]),
            REGISTRY_MANAGER,
        )
    )
    assert evaluated["performance_rate_pct"] == 60.0
    assert evaluated["performance_state"] == "UNDER_THRESHOLD"
    assert evaluated["measure_state"] == "PROJECT_REQUIRED"
    opened = get_success_data(
        api.improvement_project(
            measure["id"],
            f.improvement_project_payload(
                "OPEN",
                project_title="Radiation referral pathway redesign",
                target_rate_pct=85.0,
            ),
            COORDINATOR,
        )
    )
    assert opened["measure_state"] == "PROJECT_ACTIVE"

    closed = assert_ok(
        api.improvement_project(
            measure["id"],
            f.improvement_project_payload("CLOSE", final_rate_pct=72.0),
            COORDINATOR,
        )
    )
    assert closed["measure_state"] == "PROJECT_CLOSED_MISSED"
    assert closed["final_rate_pct"] == 72.0
    assert closed["performance_state"] == "UNDER_THRESHOLD"

    rows, meta = validate_paginated(
        api.list_deficiencies(SURVEYOR, {"source_measure_id": measure["id"]})
    )
    assert meta["total_count"] == 1
    cited = assert_deficiency(rows[0])
    assert cited["severity"] == "MAJOR"
    assert cited["deficiency_state"] == "CITED"
    assert cited["cited_on"] == "2026-08-01"
    assert cited["response_due_date"] == "2026-09-15"

    reread = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread["open_critical_deficiency_count"] == 0
    assert reread["registry_posture"] == "OPEN"
    assert reread["accreditation_state"] == "ACCREDITED"


def test_an_accepted_response_thaws_the_registry_and_gives_the_batch_back(api):
    """The batch returns to the state the freeze recorded, not to some default.

    PRD 3.9: "`ACCEPTED` moves the deficiency `RESPONSE_SUBMITTED → RESOLVED`,
    which is terminal, stores `reviewer_notes`, recomputes
    `open_critical_deficiency_count`, recomputes `registry_posture`, and — because
    the posture may have just left `FROZEN` — restores every held batch to its
    `pre_hold_state`."

    Design: Corner/endpoints/deficiency_resolution_unfreezes_posture_and_restores_held_submission
    """
    program = _program(api)
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-01-01",
                period_end="2026-06-30",
                deadline_date="2026-08-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    deficiency = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"],
                severity="CRITICAL",
                standard_code="STD-4.4",
                cited_on="2026-08-01",
                evidence_reference="SURVEY-2026-EX-11",
            ),
            SURVEYOR,
        )
    )
    frozen = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert frozen["registry_posture"] == "FROZEN"
    assert frozen["open_critical_deficiency_count"] == 1
    held = assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    assert held["submission_state"] == "HOLD"
    assert held["pre_hold_state"] == "DRAFT"

    responded = get_success_data(
        api.respond_to_deficiency(
            deficiency["id"],
            f.deficiency_response_payload(
                response_narrative=(
                    "Registrar staffing restored and backlog cleared; monthly monitoring in place."
                ),
                evidence_reference="CAP-2026-04",
            ),
            COORDINATOR,
        )
    )
    assert responded["deficiency_state"] == "RESPONSE_SUBMITTED"
    assert assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))[
        "registry_posture"
    ] == "FROZEN"

    reviewed = assert_ok(
        api.review_deficiency_response(
            deficiency["id"],
            f.deficiency_review_payload("ACCEPTED", reviewer_notes="Evidence sufficient."),
            SURVEYOR,
        )
    )
    assert reviewed["deficiency_state"] == "RESOLVED"
    assert reviewed["escalation_count"] == 0

    reread = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread["open_critical_deficiency_count"] == 0
    assert reread["registry_posture"] == "OPEN"
    assert reread["accreditation_state"] == "ACCREDITED"
    assert assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))[
        "submission_state"
    ] == "DRAFT"


def test_the_compliance_summary_can_be_read_twice_with_no_side_effects(api):
    """Two identical reads, and nothing downstream of them has moved.

    PRD 2.9: "The program's compliance summary is a computed read that recomputes
    and returns both rates, the conference compliance flags, the backlog counts and
    the posture without mutating any workflow state."

    PRD 3.7: "A program whose `annual_analytic_caseload` is 500 or more must hold
    two credited sessions per month, and a smaller program one per month, so
    `required_sessions_12mo` is that per-month figure multiplied by twelve: 24
    sessions for a program at exactly 500 cases, 12 for a smaller one."

    Design: Corner/endpoints/compliance_summary_is_repeatable_and_does_not_mutate_workflow_state
    """
    program = _program(api)
    source = _source(api, program["id"])
    case_id = _mint(api, _entry(api, source["id"])["id"])
    before = get_success_data(api.get_case(case_id, REGISTRY_MANAGER))

    first = assert_ok(api.get_compliance_summary(program["id"], SURVEYOR))
    second = assert_ok(api.get_compliance_summary(program["id"], SURVEYOR))

    assert first == second
    assert first["credited_sessions_12mo"] == 0
    assert first["required_sessions_12mo"] == 12
    assert first["conference_frequency_compliant"] is False
    assert first["coordinator_attendance_compliant"] is False
    assert first["identified_case_count"] == 1
    assert first["open_backlog_count"] == 1
    assert first["overdue_backlog_count"] == 0
    assert first["registry_posture"] == "OPEN"

    after = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert after["case_state"] == "IDENTIFIED"
    assert after["version"] == before["version"]
    assert assert_ok(api.get_casefinding_source(source["id"], REGISTRY_MANAGER))[
        "last_reconciled_through"
    ] is None
