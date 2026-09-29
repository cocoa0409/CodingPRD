"""Every triggerable refusal: the code, the status, and the untouched neighbours."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    STATE_REGISTRY_LIAISON,
    assert_casefinding_entry,
    assert_conference_session,
    assert_created,
    assert_ok,
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
UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"


def _program(api, **overrides):
    base = dict(
        name="Northside Cancer Center",
        coc_program_id="COC-1456N",
        annual_analytic_caseload=300,
        reference_year=2018,
        timeliness_standard_days=180,
    )
    base.update(overrides)
    return get_success_data(api.create_program(f.program_payload(**base), PLATFORM_ADMIN))


def _registrar(api, program_id, name, **overrides):
    base = dict(
        name=name,
        credential="CTR",
        productivity_target_cases_per_day=2,
        certification_expires_on="2027-12-31",
    )
    base.update(overrides)
    return get_success_data(
        api.create_abstractor(f.abstractor_payload(program_id, **base), REGISTRY_MANAGER)
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


def _entry(api, source_id, mrn="MRN-0001", **overrides):
    base = dict(
        patient_mrn=mrn,
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


def _draft_abstraction(api, case_id, author_id, **overrides):
    case = get_success_data(api.get_case(case_id, REGISTRY_MANAGER))
    return get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case_id,
                author_id,
                case["version"],
                first_treatment_date="2026-07-10",
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                last_contact_date="2026-07-20",
                **overrides,
            ),
            make_registry_abstractor_headers(author_id),
        )
    )


def _submitted_abstraction(api, case_id, author_id):
    abstraction = _draft_abstraction(api, case_id, author_id)
    get_success_data(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(author_id),
        )
    )
    return abstraction


def _approved_abstraction(api, case_id, author_id, reviewer_id):
    abstraction = _submitted_abstraction(api, case_id, author_id)
    get_success_data(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(reviewer_id),
        )
    )
    return abstraction


def _completed_case(api, program_id, mrn="MRN-0001"):
    author = _registrar(api, program_id, "Dana Reyes")
    reviewer = _registrar(api, program_id, "Priya Raman")
    source = _source(api, program_id)
    case_id = _mint(api, _entry(api, source["id"], mrn)["id"])
    get_success_data(api.assign_case(case_id, f.assign_payload(author["id"]), REGISTRY_MANAGER))
    _approved_abstraction(api, case_id, author["id"], reviewer["id"])
    return case_id, author, reviewer, source


def test_a_case_from_another_program_cannot_be_listed_on_this_batch(api):
    """The case is completed and both ids resolve, so only the program disagrees.

    PRD 3.6: "The batch must be in `DRAFT` (`ERR_SUBMISSION_NOT_DRAFT`), the case
    must have reached `COMPLETED` on its abstraction dimension
    (`ERR_CASE_NOT_COMPLETED`), the case's own `submission_state` must still be
    `NOT_SUBMITTED` so no case can appear in two batches
    (`ERR_CASE_ALREADY_IN_SUBMISSION`), and the case must belong to the same program
    as the batch (`ERR_CASE_PROGRAM_MISMATCH`)."

    Design: Corner/errors/foreign_program_case_added_to_a_submission_is_rejected
    """
    program_a = _program(api)
    program_b = _program(api, name="Lakeside Cancer Institute", coc_program_id="COC-2200L")
    foreign_case_id, _author, _reviewer, _source = _completed_case(
        api, program_b["id"], "MRN-0501"
    )
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program_a["id"],
                period_start="2026-07-01",
                period_end="2026-07-31",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )

    error = validate_error(
        api.add_submission_item(
            batch["id"],
            f.submission_item_payload(foreign_case_id, batch["version"]),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_CASE_PROGRAM_MISMATCH.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_CASE_NOT_COMPLETED.value

    reread = assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    assert reread["total_case_count"] == 0
    assert reread["version"] == batch["version"]
    assert assert_ok(api.get_case(foreign_case_id, REGISTRY_MANAGER))[
        "submission_state"
    ] == "NOT_SUBMITTED"

    rows, meta = validate_paginated(
        api.list_submission_items(REGISTRY_MANAGER, {"submission_id": batch["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_an_empty_batch_cannot_be_transmitted_and_owes_nothing(api):
    """Nothing to send, and nothing to pay either.

    PRD 3.6: "Four gates guard it in a fixed order, as recorded in §2.11: the batch
    must be in `DRAFT`, which is also what a held or already-transmitted batch fails
    on; the posture must not be `FROZEN` (`ERR_REGISTRY_FROZEN`); the batch must
    contain at least one item (`ERR_SUBMISSION_EMPTY`); every item's case must still
    be `COMPLETED`, so a case dragged back into rework by an audit blocks the batch
    with `ERR_CASE_NOT_COMPLETED`; and last of all, any outstanding assessment blocks
    it with `ERR_ASSESSMENT_UNPAID`."

    PRD 3.6: "Assessments are paid down by a `RegistryManager` or `PlatformAdmin`
    recording an `amount_cents`, which must be a positive integer and must not exceed
    the outstanding balance of `assessment_due_cents` less `assessment_paid_cents`;
    an overpayment is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/errors/empty_submission_cannot_transmit_and_overpayment_is_rejected
    """
    program = _program(api)
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-07-01",
                period_end="2026-07-31",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )

    validate_error(
        api.transmit_submission(
            batch["id"], f.transmit_payload(transmit_note="Nothing to send"), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_SUBMISSION_EMPTY.value,
        409,
    )
    validate_error(
        api.create_assessment_payment(
            batch["id"], f.assessment_payment_payload(100), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value,
        422,
    )

    reread = assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    assert reread["submission_state"] == "DRAFT"
    assert reread["transmitted_at"] is None
    assert reread["assessment_due_cents"] == 0
    assert reread["assessment_paid_cents"] == 0
    assert reread["version"] == batch["version"]


def test_strata_that_all_drop_out_are_empty_and_a_draft_measure_takes_no_project(api):
    """The emptiness is judged after the filter, and no rate is written.

    PRD 3.8: "Strata whose `eligible_case_count` is zero are dropped before any
    arithmetic happens, and `included_strata_count` is the number that survive; if
    none survive, the evaluation is refused with `ERR_MEASURE_STRATA_EMPTY` and no
    rate field is written."

    PRD 3.8: "`OPEN` records a `project_title` and a `target_rate_pct` and moves the
    measure `PROJECT_REQUIRED → PROJECT_ACTIVE`; a measure not in `PROJECT_REQUIRED`
    is refused with `ERR_PROJECT_NOT_REQUIRED`, and a `target_rate_pct` that is not
    strictly greater than the measure's current `performance_rate_pct` is
    `ERR_INVALID_REQUEST`, because a project must actually aim higher than where the
    program already is."

    Design: Corner/errors/measure_with_no_eligible_strata_and_project_on_a_draft_measure_are_rejected
    """
    program = _program(api)
    measure = get_success_data(
        api.create_quality_measure(
            f.quality_measure_payload(
                program["id"], measure_code="CSTC", measurement_year=2026, threshold_pct=80.0
            ),
            REGISTRY_MANAGER,
        )
    )

    validate_error(
        api.evaluate_quality_measure(
            measure["id"],
            f.evaluate_measure_payload([f.stratum("STAGE_0", 0, 0), f.stratum("STAGE_I", 0, 0)]),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_MEASURE_STRATA_EMPTY.value,
        422,
    )
    refused = assert_ok(api.get_quality_measure(measure["id"], REGISTRY_MANAGER))
    assert refused["performance_rate_pct"] is None
    assert refused["pooled_rate_pct"] is None
    assert refused["included_strata_count"] == 0
    assert refused["measure_state"] == "DRAFT"

    validate_error(
        api.improvement_project(
            measure["id"],
            f.improvement_project_payload(
                "OPEN", project_title="Premature project", target_rate_pct=90.0
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_PROJECT_NOT_REQUIRED.value,
    )
    assert assert_ok(api.get_quality_measure(measure["id"], REGISTRY_MANAGER))[
        "measure_state"
    ] == "DRAFT"


def test_a_restricted_registry_wants_a_ctr_and_a_live_credential(api):
    """Two gates on one call, keyed on the posture and on the clock date.

    PRD 3.2: "A merely restricted registry accepts the assignment only if the
    nominated registrar holds the `CTR` credential; a `NON_CTR` or `TRAINEE`
    registrar may only take on new work while the posture is `OPEN`, and the refusal
    is `ERR_RESTRICTED_REQUIRES_CTR`."

    PRD 2.4: "A registrar's `certification_expires_on` date must be on or after the
    logical clock date to receive an assignment or to author an abstraction — those
    two operations only — and a lapsed credential is rejected with
    `ERR_ABSTRACTOR_CERTIFICATION_EXPIRED`."

    Design: Corner/errors/restricted_posture_requires_ctr_and_expired_certification_blocks_assignment
    """
    program = _program(api)
    non_ctr = _registrar(api, program["id"], "Noor Haddad", credential="NON_CTR")
    lapsed = _registrar(api, program["id"], "Lee Chen", certification_expires_on="2026-07-31")
    eligible = _registrar(api, program["id"], "Dana Reyes")
    source = _source(api, program["id"])
    case_ids = [
        _mint(api, _entry(api, source["id"], mrn)["id"])
        for mrn in ("MRN-0001", "MRN-0002", "MRN-0003", "MRN-0004")
    ]

    restricted = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert restricted["registry_posture"] == "RESTRICTED"
    assert restricted["open_backlog_count"] == 4

    validate_error(
        api.assign_case(case_ids[0], f.assign_payload(non_ctr["id"]), REGISTRY_MANAGER),
        ApiErrorId.ERR_RESTRICTED_REQUIRES_CTR.value,
        409,
    )
    validate_error(
        api.assign_case(case_ids[0], f.assign_payload(lapsed["id"]), REGISTRY_MANAGER),
        ApiErrorId.ERR_ABSTRACTOR_CERTIFICATION_EXPIRED.value,
        409,
    )

    assigned = assert_ok(
        api.assign_case(case_ids[0], f.assign_payload(eligible["id"]), REGISTRY_MANAGER)
    )
    assert assigned["case_state"] == "ASSIGNED"
    assert assert_ok(api.get_abstractor(eligible["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 1
    assert assert_ok(api.get_abstractor(non_ctr["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 0
    assert assert_ok(api.get_abstractor(lapsed["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 0


def test_the_same_attendee_cannot_be_recorded_twice_on_one_session(api):
    """The second post neither appends nor overwrites the first row's minutes.

    PRD 3.7: "The `attendee_ref` must be unique within the session's `attendances`
    array; a repeat is `ERR_DUPLICATE_ATTENDANCE` (HTTP 409)."

    PRD 3.7: "Each call appends an object carrying `attendee_ref`, `discipline`,
    `is_required_coordinator`, and `attended_minutes` to the array and recomputes
    `quorum_met`, which stays false while `cases_presented_count` is still zero no
    matter how many attendees have been recorded."

    Design: Corner/errors/duplicate_attendee_ref_on_one_session_is_rejected
    """
    program = _program(api)
    session = get_success_data(
        api.create_conference_session(
            f.conference_session_payload(
                program["id"],
                start_at="2026-09-10T13:00:00Z",
                end_at="2026-09-10T14:30:00Z",
                required_disciplines=["SURGERY", "MEDICAL_ONCOLOGY"],
            ),
            COORDINATOR,
        )
    )
    get_success_data(
        api.record_attendance(
            session["id"],
            f.attendance_payload("DR-SURG-1", "SURGERY", 45, is_required_coordinator=True),
            COORDINATOR,
        )
    )

    validate_error(
        api.record_attendance(
            session["id"], f.attendance_payload("DR-SURG-1", "PATHOLOGY", 90), COORDINATOR
        ),
        ApiErrorId.ERR_DUPLICATE_ATTENDANCE.value,
        409,
    )

    reread = assert_conference_session(
        assert_ok(api.get_conference_session(session["id"], COORDINATOR))
    )
    assert len(reread["attendances"]) == 1
    row = reread["attendances"][0]
    assert row["attendee_ref"] == "DR-SURG-1"
    assert row["discipline"] == "SURGERY"
    assert row["is_required_coordinator"] is True
    assert row["attended_minutes"] == 45
    assert reread["quorum_met"] is False


def test_an_entry_whose_case_is_already_being_abstracted_cannot_be_reopened(api):
    """The compensating reopen closes as soon as abstracted content exists.

    PRD 2.6: "Reopening is only possible from `REPORTABLE` or `NON_REPORTABLE`, and
    only while `reopen_count` is still below the cap of one reopen per entry; a
    `PENDING_REVIEW` entry, an entry that has already been reopened once, or an entry
    whose minted case has moved beyond `IDENTIFIED` or `ASSIGNED` is rejected with
    `ERR_ENTRY_NOT_REOPENABLE`."

    Design: Corner/errors/entry_reopen_after_abstraction_has_started_is_rejected
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    source = _source(api, program["id"])
    entry = _entry(api, source["id"])
    case_id = _mint(api, entry["id"])
    get_success_data(api.assign_case(case_id, f.assign_payload(author["id"]), REGISTRY_MANAGER))
    abstraction = _draft_abstraction(api, case_id, author["id"])

    validate_error(
        api.reopen_casefinding_entry(
            entry["id"],
            f.entry_reopen_payload(reopen_reason="Pathology amended the behavior code"),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_ENTRY_NOT_REOPENABLE.value,
        409,
    )

    reread = assert_casefinding_entry(
        assert_ok(api.get_casefinding_entry(entry["id"], REGISTRY_MANAGER))
    )
    assert reread["reportability_state"] == "REPORTABLE"
    assert reread["reopen_count"] == 0
    assert reread["created_case_id"] == case_id
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))["case_state"] == "IN_ABSTRACTION"
    assert assert_ok(api.get_abstractor(author["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 1
    assert assert_ok(api.get_abstraction(abstraction["id"], REGISTRY_MANAGER))[
        "abstraction_state"
    ] == "DRAFT"


def test_a_registrar_cannot_pass_qa_on_their_own_abstract(api):
    """The refusal keys on the acting identity, not on the role the caller holds.

    PRD 3.3: "A `QaReviewer` records a `verdict` of `APPROVED`, `REWORK_REQUIRED`, or
    `REJECTED`, optionally with a `reviewer_note`, against an abstraction that must be
    in `SUBMITTED_FOR_QA` (`ERR_ABSTRACTION_NOT_IN_QA`), and the reviewer's
    `X-User-ID` must differ from the abstraction's `abstractor_id`
    (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)."

    PRD 3.3: "Every verdict increments the case's `version` by one, and every verdict
    writes `qa_reviewer_user_id` from the acting user."

    Design: Corner/errors/abstractor_reviewing_own_abstraction_violates_segregation_of_duties
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    case_id = _mint(api, _entry(api, source["id"])["id"])
    get_success_data(api.assign_case(case_id, f.assign_payload(author["id"]), REGISTRY_MANAGER))
    abstraction = _submitted_abstraction(api, case_id, author["id"])

    validate_error(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(author["id"]),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        409,
    )
    refused = assert_ok(api.get_abstraction(abstraction["id"], REGISTRY_MANAGER))
    assert refused["abstraction_state"] == "SUBMITTED_FOR_QA"
    assert refused["qa_reviewer_user_id"] is None
    assert refused["approved_at"] is None
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))["case_state"] == "QA_PENDING"

    approved = assert_ok(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(reviewer["id"]),
        )
    )
    assert approved["abstraction_state"] == "APPROVED"
    assert approved["qa_reviewer_user_id"] == reviewer["id"]
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))["case_state"] == "COMPLETED"
    assert assert_ok(api.get_abstractor(author["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 0


def test_the_deficiency_gate_hides_the_follow_up_gate_until_it_clears(api):
    """Two accreditation gates in order, and the second is invisible behind the first.

    PRD 3.10: "`ACCREDIT` carries two compliance gates: the count of open `MAJOR`
    and `CRITICAL` deficiencies must be zero, otherwise
    `ERR_OPEN_DEFICIENCIES_BLOCK_ACCREDITATION`, and `follow_up_rate_coc_pct` must be
    at least 80.0, otherwise `ERR_FOLLOW_UP_RATE_BELOW_THRESHOLD` — a rate of exactly
    80.0 clears the bar."

    PRD 3.10: "A successful `ACCREDIT` moves the program `DEFICIENCY_RESPONSE →
    ACCREDITED`, or `PROBATION → ACCREDITED` when it was on probation, sets
    `next_survey_due_year` to `survey_year` plus three, recomputes the posture, and
    restores every held batch to its `pre_hold_state` as the freeze lifts; the
    `PROBATION → ACCREDITED` edge is the one that closes the cycle."

    Design: Corner/errors/accreditation_blocked_first_by_open_deficiency_then_by_follow_up_rate
    """
    program = _program(api)
    case_id, author, _reviewer, _source = _completed_case(api, program["id"])
    escalating = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"],
                severity="MAJOR",
                standard_code="STD-4.5",
                cited_on="2026-08-01",
                evidence_reference="Survey finding 1",
            ),
            SURVEYOR,
        )
    )
    get_success_data(api.set_clock(f.clock_payload("2026-09-16T00:00:00Z"), PLATFORM_ADMIN))
    swept = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert swept["accreditation_state"] == "PROBATION"
    assert swept["registry_posture"] == "FROZEN"
    assert assert_ok(api.get_deficiency(escalating["id"], SURVEYOR))[
        "deficiency_state"
    ] == "ESCALATED"

    open_major = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"],
                severity="MAJOR",
                standard_code="STD-6.1",
                cited_on="2026-09-16",
                evidence_reference="Survey finding 2",
            ),
            SURVEYOR,
        )
    )
    decider = make_coc_surveyor_headers("user-surveyor-2")

    validate_error(
        api.accreditation_decision(
            program["id"],
            f.accreditation_decision_payload(decision="ACCREDIT", decision_note="First attempt"),
            decider,
        ),
        ApiErrorId.ERR_OPEN_DEFICIENCIES_BLOCK_ACCREDITATION.value,
        409,
    )
    assert assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))[
        "accreditation_state"
    ] == "PROBATION"

    get_success_data(
        api.respond_to_deficiency(
            open_major["id"],
            f.deficiency_response_payload(
                response_narrative="Corrective action plan filed", evidence_reference="CAP-2"
            ),
            COORDINATOR,
        )
    )
    resolved = get_success_data(
        api.review_deficiency_response(
            open_major["id"],
            f.deficiency_review_payload("ACCEPTED", reviewer_notes="Evidence sufficient"),
            SURVEYOR,
        )
    )
    assert resolved["deficiency_state"] == "RESOLVED"
    assert resolved["escalation_count"] == 0

    validate_error(
        api.accreditation_decision(
            program["id"],
            f.accreditation_decision_payload(decision="ACCREDIT", decision_note="Second attempt"),
            decider,
        ),
        ApiErrorId.ERR_FOLLOW_UP_RATE_BELOW_THRESHOLD.value,
        409,
    )
    assert assert_ok(api.get_compliance_summary(program["id"], SURVEYOR))[
        "follow_up_rate_coc_pct"
    ] == 0.0

    contact = get_success_data(
        api.create_follow_up_contact(
            case_id,
            f.follow_up_contact_payload(
                contact_date="2026-09-16",
                contact_method="CLINIC_VISIT",
                outcome="CONTACT_MADE",
                vital_status_at_contact="ALIVE",
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    assert contact["counts_for_follow_up"] is True
    contacted_case = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert contacted_case["last_contact_date"] == "2026-09-16"
    assert contacted_case["vital_status"] == "ALIVE"
    summary = assert_ok(api.get_compliance_summary(program["id"], SURVEYOR))
    assert summary["follow_up_rate_coc_pct"] == 100.0
    assert summary["lost_to_follow_up_pct"] == 0.0

    accredited = assert_ok(
        api.accreditation_decision(
            program["id"],
            f.accreditation_decision_payload(decision="ACCREDIT", decision_note="Third attempt"),
            decider,
        )
    )
    assert accredited["accreditation_state"] == "ACCREDITED"
    assert accredited["registry_posture"] == "OPEN"


def test_a_withdrawn_program_stops_accepting_reportability_and_accreditation_work(api):
    """The terminal state reaches past the accreditation endpoints into casefinding.

    PRD 3.10: "`WITHDRAW` moves the program `DEFICIENCY_RESPONSE → WITHDRAWN`, or
    `PROBATION → WITHDRAWN` from probation, which is terminal, where the posture
    stays `FROZEN` permanently and no further reportability decision is accepted —
    the program is finished, and §2.7 explains why nothing thaws it."

    PRD 2.6: "A `REPORTABLE` determination is also refused on a program whose
    accreditation has been withdrawn, with `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/errors/withdrawn_program_rejects_every_further_action
    """
    program = _program(api)
    source = _source(api, program["id"])
    entry = _entry(api, source["id"])
    get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="MAJOR", standard_code="STD-4.5", cited_on="2026-08-01"
            ),
            SURVEYOR,
        )
    )
    get_success_data(api.set_clock(f.clock_payload("2026-09-16T00:00:00Z"), PLATFORM_ADMIN))

    withdrawn = assert_ok(
        api.accreditation_decision(
            program["id"],
            f.accreditation_decision_payload(
                decision="WITHDRAW", decision_note="Standard 4.5 unresolved"
            ),
            SURVEYOR,
        )
    )
    assert withdrawn["accreditation_state"] == "WITHDRAWN"
    assert withdrawn["registry_posture"] == "FROZEN"

    validate_error(
        api.reportability_decision(
            entry["id"], f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
        409,
    )
    still_pending = assert_ok(api.get_casefinding_entry(entry["id"], REGISTRY_MANAGER))
    assert still_pending["reportability_state"] == "PENDING_REVIEW"
    assert still_pending["created_case_id"] is None
    _rows, meta = validate_paginated(
        api.list_cases(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0

    validate_error(
        api.survey_schedule(
            program["id"], f.survey_schedule_payload(survey_date="2027-06-01"), COORDINATOR
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
        409,
    )
    assert assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))["survey_date"] is None

    validate_error(
        api.accreditation_decision(
            program["id"],
            f.accreditation_decision_payload(decision="ACCREDIT", decision_note="Reinstate"),
            make_coc_surveyor_headers("user-surveyor-2"),
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
        409,
    )
    assert assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))[
        "accreditation_state"
    ] == "WITHDRAWN"


def test_a_rejected_deficiency_is_not_swept_and_only_fails_on_the_next_response(api):
    """The closed extended window is observable only where a response is filed.

    PRD 3.9: "The response must be filed while the logical clock date is on or
    before `response_due_date` — a response filed on exactly the due date is accepted
    and one filed a day later is refused with
    `ERR_DEFICIENCY_RESPONSE_WINDOW_CLOSED`."

    PRD 3.9: "The clock checkpoint of §2.6 reaches the same terminal state by a
    different route, taking any still-`CITED` deficiency whose `response_due_date`
    the clock has passed straight through `CITED → ESCALATED` with `escalation_count`
    incremented by one, and with the identical program and posture cascade — which is
    precisely why a deficiency sitting in `RESPONSE_REJECTED` past its extended
    deadline is not swept, since only `CITED` deficiencies are in scope."

    Design: Corner/errors/response_after_the_extended_window_closes_is_rejected
    """
    program = _program(api)
    deficiency = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="MAJOR", standard_code="STD-4.5", cited_on="2026-08-01"
            ),
            SURVEYOR,
        )
    )
    get_success_data(
        api.respond_to_deficiency(
            deficiency["id"],
            f.deficiency_response_payload(
                response_narrative="First plan", evidence_reference="CAP-1"
            ),
            COORDINATOR,
        )
    )
    get_success_data(
        api.review_deficiency_response(
            deficiency["id"],
            f.deficiency_review_payload("REJECTED", reviewer_notes="Insufficient evidence"),
            SURVEYOR,
        )
    )
    before = assert_ok(api.get_deficiency(deficiency["id"], SURVEYOR))
    assert before["deficiency_state"] == "RESPONSE_REJECTED"
    assert before["escalation_count"] == 1
    assert before["response_due_date"] == "2026-09-30"

    get_success_data(api.set_clock(f.clock_payload("2026-10-01T00:00:00Z"), PLATFORM_ADMIN))
    unswept = assert_ok(api.get_deficiency(deficiency["id"], SURVEYOR))
    assert unswept["deficiency_state"] == "RESPONSE_REJECTED"
    reread_program = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread_program["accreditation_state"] == "ACCREDITED"
    assert reread_program["registry_posture"] == "OPEN"

    validate_error(
        api.respond_to_deficiency(
            deficiency["id"],
            f.deficiency_response_payload(
                response_narrative="Second plan, filed late", evidence_reference="CAP-2"
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_DEFICIENCY_RESPONSE_WINDOW_CLOSED.value,
        409,
    )
    after = assert_ok(api.get_deficiency(deficiency["id"], SURVEYOR))
    assert after["response_narrative"] == "First plan"
    assert after["evidence_reference"] == "CAP-1"
    assert after["escalation_count"] == 1
    assert after["response_due_date"] == "2026-09-30"


def test_each_unknown_detail_route_names_its_own_entity(api):
    """Nine opaque ids, nine different not-found codes.

    PRD 2.3: "The per-resource codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_ABSTRACTOR_NOT_FOUND`, `ERR_SOURCE_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_ABSTRACTION_NOT_FOUND`,
    `ERR_AUDIT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`,
    `ERR_SUBMISSION_ITEM_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`, and
    `ERR_MEASURE_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/remaining_unknown_path_ids_each_return_their_own_not_found_code
    """
    program = _program(api)
    probes = [
        (api.get_abstraction, "a1", ApiErrorId.ERR_ABSTRACTION_NOT_FOUND),
        (api.get_qa_audit, "a2", ApiErrorId.ERR_AUDIT_NOT_FOUND),
        (api.get_conference_session, "a3", ApiErrorId.ERR_SESSION_NOT_FOUND),
        (api.get_submission, "a4", ApiErrorId.ERR_SUBMISSION_NOT_FOUND),
        (api.get_submission_item, "a5", ApiErrorId.ERR_SUBMISSION_ITEM_NOT_FOUND),
        (api.get_deficiency, "a6", ApiErrorId.ERR_DEFICIENCY_NOT_FOUND),
        (api.get_quality_measure, "a7", ApiErrorId.ERR_MEASURE_NOT_FOUND),
        (api.get_abstractor, "a8", ApiErrorId.ERR_ABSTRACTOR_NOT_FOUND),
        (api.get_follow_up_contact, "a9", ApiErrorId.ERR_CONTACT_NOT_FOUND),
    ]

    for reader, suffix, expected in probes:
        error = validate_error(
            reader(f"00000000-0000-0000-0000-0000000000{suffix}", REGISTRY_MANAGER),
            expected.value,
            404,
        )
        assert isinstance(error["message"], str)
        assert error["message"] != ""
        assert "id" not in error

    untouched = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert untouched["accreditation_state"] == "ACCREDITED"
    assert untouched["identified_case_count"] == 0
    assert untouched["version"] == 1


def test_each_case_dimension_action_names_the_state_it_needed(api):
    """One identified case and one completed case fail different calls differently.

    PRD 3.2: "A `RegistryManager` may release an assigned case, optionally recording
    an `unassign_reason`, moving it `ASSIGNED → IDENTIFIED`; a case that is not
    currently `ASSIGNED` with a non-null `assigned_abstractor_id` is rejected with
    `ERR_CASE_NOT_ASSIGNED`."

    PRD 3.2: "Only a case in `IDENTIFIED` is assignable — an already-assigned,
    in-abstraction, completed, or voided case is rejected with
    `ERR_CASE_NOT_ASSIGNABLE`, and a reworked case must be released before it can be
    re-assigned."

    PRD 3.3: "The case must be in `ASSIGNED` or `REWORK_PENDING`, otherwise the
    create is rejected with `ERR_CASE_NOT_ABSTRACTABLE`."

    PRD 2.6: "The entry must be in `PENDING_REVIEW`, otherwise the request is
    rejected with `ERR_ENTRY_NOT_PENDING_REVIEW`."

    Design: Corner/errors/case_dimension_actions_on_wrong_states_each_return_their_own_code
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    entry_1 = _entry(api, source["id"], "MRN-0001")
    entry_2 = _entry(api, source["id"], "MRN-0002")
    case_1 = _mint(api, entry_1["id"])
    case_2 = _mint(api, entry_2["id"])
    get_success_data(api.assign_case(case_1, f.assign_payload(author["id"]), REGISTRY_MANAGER))
    _approved_abstraction(api, case_1, author["id"], reviewer["id"])
    current = get_success_data(api.get_case(case_1, REGISTRY_MANAGER))

    validate_error(
        api.unassign_case(
            case_2, f.unassign_payload(unassign_reason="Nobody is on it"), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_CASE_NOT_ASSIGNED.value,
        409,
    )
    idle = assert_ok(api.get_case(case_2, REGISTRY_MANAGER))
    assert idle["case_state"] == "IDENTIFIED"
    assert idle["assigned_abstractor_id"] is None

    validate_error(
        api.assign_case(case_1, f.assign_payload(reviewer["id"]), REGISTRY_MANAGER),
        ApiErrorId.ERR_CASE_NOT_ASSIGNABLE.value,
        409,
    )
    assert assert_ok(api.get_abstractor(reviewer["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 0

    error = validate_error(
        api.create_abstraction(
            f.abstraction_payload(
                case_1,
                author["id"],
                current["version"],
                stage_source="CLINICAL",
                t_category=f.OMIT,
                n_category=f.OMIT,
                m_category=f.OMIT,
                stage_group=f.OMIT,
                first_treatment_date=f.OMIT,
                treatment_modalities=f.OMIT,
                diagnostic_confirmation_code=f.OMIT,
                outcome_status=f.OMIT,
                last_contact_date=f.OMIT,
            ),
            make_registry_abstractor_headers(author["id"]),
        ),
        ApiErrorId.ERR_CASE_NOT_ABSTRACTABLE.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_STALE_CASE_VERSION.value
    _rows, meta = validate_paginated(api.list_abstractions(REGISTRY_MANAGER, {"case_id": case_1}))
    assert meta["total_count"] == 1

    validate_error(
        api.reportability_decision(
            entry_1["id"],
            f.reportability_decision_payload(
                "NON_REPORTABLE",
                decision_reason_code="BENIGN_NON_CNS",
                override_reason_code="REGISTRAR_JUDGEMENT",
            ),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_ENTRY_NOT_PENDING_REVIEW.value,
        409,
    )
    reread_entry = assert_ok(api.get_casefinding_entry(entry_1["id"], REGISTRY_MANAGER))
    assert reread_entry["reportability_state"] == "REPORTABLE"
    assert reread_entry["created_case_id"] == case_1


def _incomplete_draft(api, case_id, author_id):
    case = get_success_data(api.get_case(case_id, REGISTRY_MANAGER))
    return get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case_id,
                author_id,
                case["version"],
                stage_source="CLINICAL",
                t_category="T1",
                stage_group="STAGE_I",
                first_treatment_date=f.OMIT,
                treatment_modalities=f.OMIT,
                diagnostic_confirmation_code=f.OMIT,
                outcome_status=f.OMIT,
                last_contact_date=f.OMIT,
            ),
            make_registry_abstractor_headers(author_id),
        )
    )


def test_the_editable_window_and_the_auditable_window_do_not_overlap(api):
    """An APPROVED abstract accepts an audit but no edit; a DRAFT one the reverse.

    PRD 3.3: "Only the abstraction's own `abstractor_id` may submit it, and only
    from `DRAFT` — anything else is `ERR_ABSTRACTION_NOT_DRAFT`."

    PRD 3.3: "An abstraction not in `REWORK_REQUIRED` is refused with
    `ERR_ABSTRACTION_NOT_REWORKABLE`, a caller other than the owning registrar with
    `ERR_NOT_ASSIGNED_ABSTRACTOR`, and a parent case that is neither `IN_ABSTRACTION`
    nor `REWORK_PENDING` with `ERR_CASE_NOT_ABSTRACTABLE`."

    PRD 3.4: "Only an abstraction in `SUBMITTED_FOR_QA` or `APPROVED` may be
    audited; a `DRAFT`, `REWORK_REQUIRED`, `REJECTED`, or `SUPERSEDED` abstraction is
    refused with `ERR_ABSTRACTION_NOT_AUDITABLE`."

    PRD 3.4: "A new audit opens in `OPEN` with `minor_discrepancy_count`,
    `major_discrepancy_count`, `critical_discrepancy_count`, and
    `weighted_error_score` at zero, `verdict` null, and `cascade_applied` false."

    Design: Corner/errors/abstraction_dimension_actions_on_wrong_states_each_return_their_own_code
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    case_1 = _mint(api, _entry(api, source["id"], "MRN-0001")["id"])
    case_2 = _mint(api, _entry(api, source["id"], "MRN-0002")["id"])
    get_success_data(api.assign_case(case_1, f.assign_payload(author["id"]), REGISTRY_MANAGER))
    abst_1 = _approved_abstraction(api, case_1, author["id"], reviewer["id"])
    get_success_data(api.assign_case(case_2, f.assign_payload(author["id"]), REGISTRY_MANAGER))
    abst_2 = _incomplete_draft(api, case_2, author["id"])
    author_headers = make_registry_abstractor_headers(author["id"])
    auditor_headers = make_qa_reviewer_headers(reviewer["id"])

    validate_error(
        api.submit_qa(abst_1["id"], f.submit_qa_payload(submit_note=f.OMIT), author_headers),
        ApiErrorId.ERR_ABSTRACTION_NOT_DRAFT.value,
        409,
    )
    reread_1 = assert_ok(api.get_abstraction(abst_1["id"], REGISTRY_MANAGER))
    assert reread_1["abstraction_state"] == "APPROVED"
    assert reread_1["approved_at"] == "2026-08-01T00:00:00.000Z"

    validate_error(
        api.reopen_draft(
            abst_1["id"], f.reopen_draft_payload(stage_group="STAGE_III"), author_headers
        ),
        ApiErrorId.ERR_ABSTRACTION_NOT_REWORKABLE.value,
        409,
    )
    unchanged_1 = assert_ok(api.get_abstraction(abst_1["id"], REGISTRY_MANAGER))
    assert unchanged_1["rework_round"] == 0
    assert unchanged_1["stage_group"] == "STAGE_II"

    validate_error(
        api.create_qa_audit(
            f.qa_audit_payload(abst_2["id"], reviewer["id"]), auditor_headers
        ),
        ApiErrorId.ERR_ABSTRACTION_NOT_AUDITABLE.value,
        409,
    )
    _rows, meta = validate_paginated(
        api.list_qa_audits(REGISTRY_MANAGER, {"abstraction_id": abst_2["id"]})
    )
    assert meta["total_count"] == 0

    audit = assert_created(
        api.create_qa_audit(f.qa_audit_payload(abst_1["id"], reviewer["id"]), auditor_headers)
    )
    assert audit["audit_state"] == "OPEN"
    assert audit["verdict"] is None
    assert audit["cascade_applied"] is False
    assert audit["weighted_error_score"] == 0

    assert assert_ok(api.get_case(case_1, REGISTRY_MANAGER))["case_state"] == "COMPLETED"
    assert assert_ok(api.get_case(case_2, REGISTRY_MANAGER))["case_state"] == "IN_ABSTRACTION"


def test_each_submission_action_demands_its_own_state_and_says_so(api):
    """Four actions, four different state codes, and one of them outranks a duplicate.

    PRD 3.6: "The batch must be in `DRAFT` (`ERR_SUBMISSION_NOT_DRAFT`), the case
    must have reached `COMPLETED` on its abstraction dimension
    (`ERR_CASE_NOT_COMPLETED`), the case's own `submission_state` must still be
    `NOT_SUBMITTED` so no case can appear in two batches
    (`ERR_CASE_ALREADY_IN_SUBMISSION`), and the case must belong to the same program
    as the batch (`ERR_CASE_PROGRAM_MISMATCH`)."

    PRD 3.6: "The batch must be in `TRANSMITTED` (`ERR_SUBMISSION_NOT_TRANSMITTED`);
    every `case_id` in the array must name an item that belongs to this batch, and one
    that does not is `ERR_SUBMISSION_ITEM_NOT_FOUND` (HTTP 404); and the array must
    cover every item on the batch, a partial batch being `ERR_INVALID_REQUEST`."

    PRD 3.6: "A `RegistryAbstractor` or `RegistryManager` resolves one failed item at
    a time with a mandatory `resolution_note`, moving that item `EDIT_FAILED →
    RESOLVED`; an item in any other `edit_status` is refused with
    `ERR_ITEM_NOT_FAILED`."

    PRD 3.6: "Its gates fire in order: the batch must be in `EDITS_RETURNED`
    (`ERR_SUBMISSION_NOT_IN_EDIT_RESOLUTION`), `failed_item_count` must be zero
    (`ERR_UNRESOLVED_EDITS`), `resubmission_round` must be strictly below two so that
    the third retransmit is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`, the
    posture must not be `FROZEN`, and finally the assessment must be settled
    (`ERR_ASSESSMENT_UNPAID`)."

    PRD 2.11: "The bands, from first-evaluated to last, are: authentication of the
    two headers; authorization of the role against the endpoint; request shape;
    existence of path identifiers, then existence of body foreign keys, then
    membership of ids inside a batched payload; optimistic concurrency; state
    preconditions; safety and compliance gates; temporal gates; referential and
    uniqueness constraints; and finally fiscal gates."

    Design: Corner/errors/submission_lifecycle_actions_on_wrong_states_each_return_their_own_code
    """
    program = _program(api)
    case_id, _author, _reviewer, _source = _completed_case(api, program["id"])
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-07-01",
                period_end="2026-07-31",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    item = get_success_data(
        api.add_submission_item(
            batch["id"], f.submission_item_payload(case_id, batch["version"]), REGISTRY_MANAGER
        )
    )
    draft = get_success_data(api.get_submission(batch["id"], REGISTRY_MANAGER))

    validate_error(
        api.retransmit_submission(
            batch["id"], f.retransmit_payload(retransmit_note="Too early"), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_SUBMISSION_NOT_IN_EDIT_RESOLUTION.value,
        409,
    )
    assert assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))["resubmission_round"] == 0

    validate_error(
        api.add_submission_item(
            batch["id"], f.submission_item_payload(case_id, draft["version"]), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_CASE_ALREADY_IN_SUBMISSION.value,
        409,
    )
    still_draft = assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    assert still_draft["total_case_count"] == 1
    assert still_draft["version"] == draft["version"]

    validate_error(
        api.post_edit_results(
            batch["id"],
            f.edit_results_payload([f.item_result(case_id, "ACCEPTED", [])]),
            STATE_REGISTRY_LIAISON,
        ),
        ApiErrorId.ERR_SUBMISSION_NOT_TRANSMITTED.value,
        409,
    )
    assert assert_ok(api.get_submission_item(item["id"], REGISTRY_MANAGER))[
        "edit_status"
    ] == "PENDING"

    transmitted = assert_ok(
        api.transmit_submission(
            batch["id"],
            f.transmit_payload(transmit_note="July 2026 batch"),
            REGISTRY_MANAGER,
        )
    )
    assert transmitted["submission_state"] == "TRANSMITTED"
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))["submission_state"] == "SUBMITTED"

    error = validate_error(
        api.add_submission_item(
            batch["id"],
            f.submission_item_payload(case_id, transmitted["version"]),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_SUBMISSION_NOT_DRAFT.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_CASE_ALREADY_IN_SUBMISSION.value

    returned = assert_ok(
        api.post_edit_results(
            batch["id"],
            f.edit_results_payload([f.item_result(case_id, "EDIT_FAILED", ["E-1004"])]),
            STATE_REGISTRY_LIAISON,
        )
    )
    assert returned["submission_state"] == "EDITS_RETURNED"
    assert returned["failed_item_count"] == 1
    assert returned["assessment_due_cents"] == 0

    resolved = assert_ok(
        api.resolve_submission_item(
            batch["id"],
            item["id"],
            f.resolve_item_payload(resolution_note="Histology corrected"),
            REGISTRY_MANAGER,
        )
    )
    assert resolved["edit_status"] == "RESOLVED"
    assert resolved["edit_codes"] == ["E-1004"]
    assert assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))["failed_item_count"] == 0

    validate_error(
        api.resolve_submission_item(
            batch["id"],
            item["id"],
            f.resolve_item_payload(resolution_note="Corrected again"),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_ITEM_NOT_FAILED.value,
        409,
    )
    assert assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))["failed_item_count"] == 0


def test_response_and_review_bracket_the_same_window_from_both_sides(api):
    """Reviewing before an answer and answering after resolution both fail.

    PRD 3.9: "Responses are accepted only from `CITED` or `RESPONSE_REJECTED`; a
    deficiency already under review, or terminally `RESOLVED` or `ESCALATED`, is
    refused with `ERR_DEFICIENCY_NOT_RESPONDABLE`."

    PRD 3.9: "A `CoCSurveyor` records an `outcome` of `ACCEPTED` or `REJECTED`,
    optionally with `reviewer_notes`, against a deficiency that must be in
    `RESPONSE_SUBMITTED` (`ERR_DEFICIENCY_NOT_UNDER_REVIEW`), and the reviewing user
    must not be the user recorded on the response
    (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)."

    PRD 3.9: "`ACCEPTED` moves the deficiency `RESPONSE_SUBMITTED → RESOLVED`, which
    is terminal, stores `reviewer_notes`, recomputes `open_critical_deficiency_count`,
    recomputes `registry_posture`, and — because the posture may have just left
    `FROZEN` — restores every held batch to its `pre_hold_state`."

    Design: Corner/errors/deficiency_response_and_review_on_wrong_states_each_return_their_own_code
    """
    program = _program(api)
    deficiency = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="MINOR", standard_code="STD-2.3", cited_on="2026-08-01"
            ),
            SURVEYOR,
        )
    )

    validate_error(
        api.review_deficiency_response(
            deficiency["id"],
            f.deficiency_review_payload("ACCEPTED", reviewer_notes="Nothing filed yet"),
            SURVEYOR,
        ),
        ApiErrorId.ERR_DEFICIENCY_NOT_UNDER_REVIEW.value,
        409,
    )
    cited = assert_ok(api.get_deficiency(deficiency["id"], SURVEYOR))
    assert cited["deficiency_state"] == "CITED"
    assert cited["reviewer_notes"] is None
    # PRD 3.9: a MINOR deficiency must be answered "within 60 days", and
    # response_due_date is cited_on plus that many days -> 2026-08-01 + 60d.
    assert cited["response_due_date"] == "2026-09-30"

    answered = assert_ok(
        api.respond_to_deficiency(
            deficiency["id"],
            f.deficiency_response_payload(
                response_narrative="Conference calendar published", evidence_reference="CAL-1"
            ),
            COORDINATOR,
        )
    )
    assert answered["deficiency_state"] == "RESPONSE_SUBMITTED"

    resolved = assert_ok(
        api.review_deficiency_response(
            deficiency["id"],
            f.deficiency_review_payload("ACCEPTED", reviewer_notes="Accepted"),
            SURVEYOR,
        )
    )
    assert resolved["deficiency_state"] == "RESOLVED"
    assert resolved["escalation_count"] == 0
    assert assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))[
        "open_critical_deficiency_count"
    ] == 0

    validate_error(
        api.respond_to_deficiency(
            deficiency["id"],
            f.deficiency_response_payload(
                response_narrative="Extra evidence", evidence_reference="CAL-2"
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_DEFICIENCY_NOT_RESPONDABLE.value,
        409,
    )
    kept = assert_ok(api.get_deficiency(deficiency["id"], SURVEYOR))
    assert kept["response_narrative"] == "Conference calendar published"
    assert kept["evidence_reference"] == "CAL-1"

    validate_error(
        api.review_deficiency_response(
            deficiency["id"],
            f.deficiency_review_payload("REJECTED", reviewer_notes="Second thoughts"),
            SURVEYOR,
        ),
        ApiErrorId.ERR_DEFICIENCY_NOT_UNDER_REVIEW.value,
        409,
    )
    assert assert_ok(api.get_deficiency(deficiency["id"], SURVEYOR))[
        "deficiency_state"
    ] == "RESOLVED"


def test_neither_workflow_may_be_entered_before_its_trigger_exists(api):
    """A measure that meets its threshold and a session never held both refuse.

    PRD 3.8: "`OPEN` records a `project_title` and a `target_rate_pct` and moves the
    measure `PROJECT_REQUIRED → PROJECT_ACTIVE`; a measure not in `PROJECT_REQUIRED`
    is refused with `ERR_PROJECT_NOT_REQUIRED`, and a `target_rate_pct` that is not
    strictly greater than the measure's current `performance_rate_pct` is
    `ERR_INVALID_REQUEST`, because a project must actually aim higher than where the
    program already is."

    PRD 3.7: "An `AccreditationCoordinator` records a `disposition` of `CREDIT` or
    `NO_CREDIT`, optionally with a `credit_note`, against a session that must be in
    `HELD` (`ERR_SESSION_NOT_HELD`)."

    Design: Corner/errors/project_open_on_a_meeting_measure_and_credit_on_a_scheduled_session_are_rejected
    """
    program = _program(api)
    measure = get_success_data(
        api.create_quality_measure(
            f.quality_measure_payload(
                program["id"], measure_code="CSTC", measurement_year=2026, threshold_pct=80.0
            ),
            REGISTRY_MANAGER,
        )
    )
    evaluated = assert_ok(
        api.evaluate_quality_measure(
            measure["id"],
            f.evaluate_measure_payload(
                [f.stratum("STAGE_I", 20, 17), f.stratum("STAGE_II", 20, 17)]
            ),
            REGISTRY_MANAGER,
        )
    )
    assert evaluated["performance_rate_pct"] == 85.0
    assert evaluated["pooled_rate_pct"] == 85.0
    assert evaluated["included_strata_count"] == 2
    assert evaluated["performance_state"] == "MEETS"

    session = get_success_data(
        api.create_conference_session(
            f.conference_session_payload(
                program["id"],
                start_at="2026-09-10T13:00:00Z",
                end_at="2026-09-10T14:30:00Z",
                required_disciplines=["SURGERY"],
            ),
            COORDINATOR,
        )
    )
    get_success_data(
        api.record_attendance(
            session["id"],
            f.attendance_payload(
                "DR-SURG-1", "SURGERY", attended_minutes=60, is_required_coordinator=True
            ),
            COORDINATOR,
        )
    )

    validate_error(
        api.improvement_project(
            measure["id"],
            f.improvement_project_payload(
                "OPEN", project_title="Unnecessary PI project", target_rate_pct=95.0
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_PROJECT_NOT_REQUIRED.value,
        409,
    )
    reread_measure = assert_ok(api.get_quality_measure(measure["id"], REGISTRY_MANAGER))
    assert reread_measure["project_title"] is None
    assert reread_measure["target_rate_pct"] is None
    assert reread_measure["measure_state"] == "MEASURED"

    validate_error(
        api.credit_session(
            session["id"],
            f.credit_session_payload("CREDIT", credit_note="Looked fine on paper"),
            COORDINATOR,
        ),
        ApiErrorId.ERR_SESSION_NOT_HELD.value,
        409,
    )
    reread_session = assert_conference_session(
        assert_ok(api.get_conference_session(session["id"], COORDINATOR))
    )
    assert reread_session["session_state"] == "SCHEDULED"
    # PRD 3.7: "A new session opens in SCHEDULED with an empty attendances array,
    # cases_presented_count and prospective_case_count at zero".
    assert reread_session["cases_presented_count"] == 0
    assert reread_session["credited_on"] is None

    reread_program = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread_program["credited_sessions_12mo"] == 0
    assert reread_program["conference_frequency_compliant"] is False


def test_the_override_reason_is_demanded_only_where_the_registrar_disagrees(api):
    """The same determination is refused, then accepted, then accepted unjustified.

    PRD 2.6: "When the decision contradicts `suggested_reportability` — a
    `REPORTABLE` determination on an entry the engine suggested was non-reportable, or
    a `NON_REPORTABLE` determination on one it suggested was reportable — a non-empty
    `override_reason_code` is mandatory, and its absence is rejected with
    `ERR_REPORTABILITY_OVERRIDE_REASON_REQUIRED` (HTTP 422)."

    PRD 2.6: "Otherwise, if the behaviour is either `MALIGNANT_3` or `IN_SITU_2`, the
    suggestion is `REPORTABLE` with reason `SEER_REPORTABLE_BEHAVIOR`."

    PRD 2.6: "In every remaining case the suggestion is `NON_REPORTABLE` with reason
    `BENIGN_NON_CNS`."

    PRD 2.6: "Either determination records the `decision_reason_code` and stamps
    `decided_by_user_id` with the acting `X-User-ID`; a `NON_REPORTABLE` determination
    moves the entry to `PENDING_REVIEW → NON_REPORTABLE`, mints nothing, and leaves
    `created_case_id` null."

    Design: Corner/errors/contradicting_the_suggested_reportability_without_an_override_reason_is_rejected
    """
    program = _program(api)
    source = _source(api, program["id"])
    entry_mal = assert_casefinding_entry(
        assert_created(
            api.create_casefinding_entry(
                source["id"],
                f.casefinding_entry_payload(
                    patient_mrn="MRN-0001",
                    accession_date="2026-08-03",
                    primary_site_code="C50.9",
                    histology_code="8500/3",
                    behavior_code="MALIGNANT_3",
                    diagnosis_date="2026-07-01",
                    first_contact_date="2026-07-05",
                    diagnosed_at_facility=True,
                    first_treatment_at_facility=True,
                ),
                REGISTRY_MANAGER,
            )
        )
    )
    entry_ben = assert_casefinding_entry(
        assert_created(
            api.create_casefinding_entry(
                source["id"],
                f.casefinding_entry_payload(
                    patient_mrn="MRN-0002",
                    accession_date="2026-08-03",
                    primary_site_code="C50.9",
                    histology_code="8140/0",
                    behavior_code="BENIGN_0",
                    diagnosis_date="2026-07-01",
                    first_contact_date="2026-07-05",
                    diagnosed_at_facility=True,
                    first_treatment_at_facility=True,
                ),
                REGISTRY_MANAGER,
            )
        )
    )
    assert entry_mal["suggested_reportability"] == "REPORTABLE"
    assert entry_mal["suggested_reason_code"] == "SEER_REPORTABLE_BEHAVIOR"
    assert entry_ben["suggested_reportability"] == "NON_REPORTABLE"
    assert entry_ben["suggested_reason_code"] == "BENIGN_NON_CNS"

    validate_error(
        api.reportability_decision(
            entry_mal["id"],
            f.reportability_decision_payload(
                "NON_REPORTABLE", decision_reason_code="REGISTRAR_JUDGEMENT"
            ),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_REPORTABILITY_OVERRIDE_REASON_REQUIRED.value,
        422,
    )
    untouched = assert_ok(api.get_casefinding_entry(entry_mal["id"], REGISTRY_MANAGER))
    assert untouched["reportability_state"] == "PENDING_REVIEW"
    assert untouched["decision_reason_code"] is None

    justified = assert_ok(
        api.reportability_decision(
            entry_mal["id"],
            f.reportability_decision_payload(
                "NON_REPORTABLE",
                decision_reason_code="REGISTRAR_JUDGEMENT",
                override_reason_code="PATHOLOGY_AMENDED_TO_BENIGN",
            ),
            REGISTRY_MANAGER,
        )
    )
    assert justified["reportability_state"] == "NON_REPORTABLE"
    assert justified["override_reason_code"] == "PATHOLOGY_AMENDED_TO_BENIGN"
    assert justified["created_case_id"] is None

    agreeing = assert_ok(
        api.reportability_decision(
            entry_ben["id"],
            f.reportability_decision_payload(
                "NON_REPORTABLE", decision_reason_code="BENIGN_NON_CNS"
            ),
            REGISTRY_MANAGER,
        )
    )
    assert agreeing["reportability_state"] == "NON_REPORTABLE"
    assert agreeing["override_reason_code"] is None
    assert agreeing["created_case_id"] is None

    _rows, meta = validate_paginated(
        api.list_cases(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_a_rework_pending_case_demands_a_supersede_target_on_its_own_case(api):
    """The one state where the create call changes shape, and it checks the target.

    PRD 3.4: "When the verdict is `CRITICAL_FAIL` and the audited abstraction is
    still `APPROVED`, the audit sets `cascade_applied` to true, drags that abstraction
    `APPROVED → REWORK_REQUIRED`, and moves its case `COMPLETED → REWORK_PENDING` with
    `completed_on` cleared to null and the author's `assigned_open_case_count`
    incremented by one; the program's backlog counts and posture are then recomputed,
    and a posture that becomes `FROZEN` moves every draft batch to hold."

    PRD 3.3: "A second abstraction on a case whose prior abstraction has not reached a
    terminal state must carry `supersedes_abstraction_id`, and its absence is rejected
    with `ERR_SUPERSEDE_TARGET_REQUIRED` (HTTP 422)."

    PRD 3.3: "When `supersedes_abstraction_id` is present it must name an abstraction
    on the same `case_id` whose state is `DRAFT` or `REWORK_REQUIRED`; an abstraction
    on another case, or one already approved, rejected, or superseded, is refused with
    `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 422)."

    PRD 3.3: "Creating a superseding abstraction against a case in `REWORK_PENDING`
    advances that case `REWORK_PENDING → IN_ABSTRACTION`, moves the abstraction it
    names from `REWORK_REQUIRED → SUPERSEDED` (a terminal state), carries the
    superseded abstraction's `rework_round` forward onto the new one — a fresh
    abstraction with nothing to supersede starts at round zero — and increments the
    case's `version` by one."

    Design: Corner/errors/rework_pending_case_demands_a_valid_supersede_target
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    case_1 = _mint(api, _entry(api, source["id"], "MRN-0001")["id"])
    case_2 = _mint(api, _entry(api, source["id"], "MRN-0002")["id"])
    get_success_data(api.assign_case(case_1, f.assign_payload(author["id"]), REGISTRY_MANAGER))
    abst_1 = _approved_abstraction(api, case_1, author["id"], reviewer["id"])
    get_success_data(api.assign_case(case_2, f.assign_payload(author["id"]), REGISTRY_MANAGER))
    abst_2 = _incomplete_draft(api, case_2, author["id"])
    author_headers = make_registry_abstractor_headers(author["id"])
    auditor_headers = make_qa_reviewer_headers(reviewer["id"])

    audit = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(abst_1["id"], reviewer["id"], audit_type="TARGETED"),
            auditor_headers,
        )
    )
    scored = assert_ok(
        api.score_qa_audit(
            audit["id"],
            f.audit_score_payload(audited_field_count=40, critical_discrepancy_count=1),
            auditor_headers,
        )
    )
    assert scored["verdict"] == "CRITICAL_FAIL"
    assert scored["cascade_applied"] is True
    assert assert_ok(api.get_abstraction(abst_1["id"], REGISTRY_MANAGER))[
        "abstraction_state"
    ] == "REWORK_REQUIRED"
    reworking_case = assert_ok(api.get_case(case_1, REGISTRY_MANAGER))
    assert reworking_case["case_state"] == "REWORK_PENDING"
    assert reworking_case["completed_on"] is None

    validate_error(
        api.create_abstraction(
            f.abstraction_payload(
                case_1,
                author["id"],
                reworking_case["version"],
                stage_source="PATHOLOGIC",
                t_category=f.OMIT,
                n_category=f.OMIT,
                m_category=f.OMIT,
                stage_group=f.OMIT,
                first_treatment_date=f.OMIT,
                treatment_modalities=f.OMIT,
                diagnostic_confirmation_code=f.OMIT,
                outcome_status=f.OMIT,
                last_contact_date=f.OMIT,
            ),
            author_headers,
        ),
        ApiErrorId.ERR_SUPERSEDE_TARGET_REQUIRED.value,
        422,
    )
    _rows, meta = validate_paginated(api.list_abstractions(REGISTRY_MANAGER, {"case_id": case_1}))
    assert meta["total_count"] == 1

    validate_error(
        api.create_abstraction(
            f.abstraction_payload(
                case_1,
                author["id"],
                reworking_case["version"],
                stage_source="PATHOLOGIC",
                supersedes_abstraction_id=abst_2["id"],
            ),
            author_headers,
        ),
        ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value,
        422,
    )
    intact = assert_ok(api.get_abstraction(abst_2["id"], REGISTRY_MANAGER))
    assert intact["abstraction_state"] == "DRAFT"
    assert intact["case_id"] == case_2

    replacement = assert_created(
        api.create_abstraction(
            f.abstraction_payload(
                case_1,
                author["id"],
                reworking_case["version"],
                stage_source="PATHOLOGIC",
                t_category="T3",
                n_category="N1",
                m_category="M0",
                stage_group="STAGE_III",
                first_treatment_date="2026-07-10",
                treatment_modalities=["SURGERY"],
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                outcome_status="ALIVE_WITH_DISEASE",
                last_contact_date="2026-07-20",
                supersedes_abstraction_id=abst_1["id"],
            ),
            author_headers,
        )
    )
    assert replacement["abstraction_state"] == "DRAFT"
    assert replacement["supersedes_abstraction_id"] == abst_1["id"]
    assert assert_ok(api.get_case(case_1, REGISTRY_MANAGER))["case_state"] == "IN_ABSTRACTION"
    assert assert_ok(api.get_abstraction(abst_1["id"], REGISTRY_MANAGER))[
        "abstraction_state"
    ] == "SUPERSEDED"

    _rows2, meta2 = validate_paginated(
        api.list_abstractions(REGISTRY_MANAGER, {"case_id": case_1})
    )
    assert meta2["total_count"] == 2
    assert assert_ok(api.get_abstractor(author["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 2


def test_the_third_retransmit_is_refused_even_with_every_edit_resolved(api):
    """Two rounds of edit ping-pong are allowed and the third is not.

    PRD 3.6: "Retransmission then moves the batch `EDITS_RETURNED → TRANSMITTED`,
    optionally with a `retransmit_note`, increments `resubmission_round` by one,
    refreshes `transmitted_at`, increments `version` by one, and returns every
    `RESOLVED` item to `PENDING` with its case moving `EDIT_REJECTED → SUBMITTED`."

    PRD 3.6: "Its gates fire in order: the batch must be in `EDITS_RETURNED`
    (`ERR_SUBMISSION_NOT_IN_EDIT_RESOLUTION`), `failed_item_count` must be zero
    (`ERR_UNRESOLVED_EDITS`), `resubmission_round` must be strictly below two so that
    the third retransmit is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`, the
    posture must not be `FROZEN`, and finally the assessment must be settled
    (`ERR_ASSESSMENT_UNPAID`)."

    Design: Corner/errors/retransmit_beyond_the_second_resubmission_round_is_rejected
    """
    program = _program(api)
    case_id, _author, _reviewer, _source = _completed_case(api, program["id"])
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-07-01",
                period_end="2026-07-31",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    item = get_success_data(
        api.add_submission_item(
            batch["id"], f.submission_item_payload(case_id, batch["version"]), REGISTRY_MANAGER
        )
    )
    get_success_data(
        api.transmit_submission(
            batch["id"], f.transmit_payload(transmit_note="Round 0"), REGISTRY_MANAGER
        )
    )

    def _fail_and_resolve(note):
        get_success_data(
            api.post_edit_results(
                batch["id"],
                f.edit_results_payload([f.item_result(case_id, "EDIT_FAILED", ["E-1004"])]),
                STATE_REGISTRY_LIAISON,
            )
        )
        get_success_data(
            api.resolve_submission_item(
                batch["id"],
                item["id"],
                f.resolve_item_payload(resolution_note=note),
                REGISTRY_MANAGER,
            )
        )

    _fail_and_resolve("Fix 1")
    round_1 = assert_ok(
        api.retransmit_submission(
            batch["id"], f.retransmit_payload(retransmit_note="Round 1"), REGISTRY_MANAGER
        )
    )
    assert round_1["submission_state"] == "TRANSMITTED"
    assert round_1["resubmission_round"] == 1
    assert assert_ok(api.get_submission_item(item["id"], REGISTRY_MANAGER))[
        "edit_status"
    ] == "PENDING"
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))["submission_state"] == "SUBMITTED"

    _fail_and_resolve("Fix 2")
    round_2 = assert_ok(
        api.retransmit_submission(
            batch["id"], f.retransmit_payload(retransmit_note="Round 2"), REGISTRY_MANAGER
        )
    )
    assert round_2["resubmission_round"] == 2

    _fail_and_resolve("Fix 3")
    error = validate_error(
        api.retransmit_submission(
            batch["id"], f.retransmit_payload(retransmit_note="Round 3"), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_RESUBMISSION_LIMIT_EXCEEDED.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_UNRESOLVED_EDITS.value

    final = assert_ok(api.get_submission(batch["id"], REGISTRY_MANAGER))
    assert final["submission_state"] == "EDITS_RETURNED"
    assert final["resubmission_round"] == 2
    assert final["failed_item_count"] == 0
    assert final["assessment_due_cents"] == 0
    assert assert_ok(api.get_submission_item(item["id"], REGISTRY_MANAGER))[
        "edit_status"
    ] == "RESOLVED"
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))[
        "submission_state"
    ] == "EDIT_REJECTED"
