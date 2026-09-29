"""Transitions taken, transitions refused, and the side effects each one owes."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_conference_session,
    assert_created,
    assert_ok,
    assert_qa_audit,
    assert_tumor_case,
    assert_workload_ledger_conserved,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
)

COORDINATOR = make_accreditation_coordinator_headers("coord-lee")
REQUIRED_THREE = ["SURGERY", "MEDICAL_ONCOLOGY", "RADIATION_ONCOLOGY"]


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


def _assigned_case(api, program_id, author_id):
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program_id, source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )
    entry = get_success_data(
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
    decided = get_success_data(
        api.reportability_decision(
            entry["id"], f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )
    return get_success_data(
        api.assign_case(
            decided["created_case_id"], f.assign_payload(author_id), REGISTRY_MANAGER
        )
    )


def _draft_abstraction(api, case, author_id):
    return get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case["id"],
                author_id,
                case["version"],
                stage_source="PATHOLOGIC",
                t_category="T2",
                n_category="N0",
                m_category="M0",
                stage_group="STAGE_II",
                first_treatment_date="2026-07-10",
                treatment_modalities=["SURGERY"],
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                outcome_status="ALIVE_NO_EVIDENCE",
                last_contact_date="2026-07-20",
            ),
            make_registry_abstractor_headers(author_id),
        )
    )


def _approved_abstraction(api):
    """A program with one approved abstract, its author and an independent reviewer."""
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    case = _assigned_case(api, program["id"], author["id"])
    abstraction = _draft_abstraction(api, case, author["id"])
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
    return {
        "program": program,
        "author": author,
        "reviewer": reviewer,
        "case": case,
        "abstraction": abstraction,
    }


# --------------------------------------------------------------------------
# conference sessions
# --------------------------------------------------------------------------
def _quorum_session(api, program_id, start_at="2026-07-15T13:00:00Z"):
    session = get_success_data(
        api.create_conference_session(
            f.conference_session_payload(
                program_id,
                start_at=start_at,
                end_at="2026-07-15T14:30:00Z",
                required_disciplines=list(REQUIRED_THREE),
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
    get_success_data(
        api.record_attendance(
            session["id"],
            f.attendance_payload("DR-MEDONC-1", "MEDICAL_ONCOLOGY", 45),
            COORDINATOR,
        )
    )
    get_success_data(
        api.record_attendance(
            session["id"],
            f.attendance_payload("DR-RADONC-1", "RADIATION_ONCOLOGY", 45),
            COORDINATOR,
        )
    )
    return session


def test_holding_a_session_turns_posted_counts_into_ratio_and_quorum(api):
    """Eight prospective of ten presented is 0.8, and all three disciplines sat.

    PRD 3.7: "`prospective_case_ratio` is `prospective_case_count` divided by
    `cases_presented_count`, rounded to three decimal places, and 0.0 when no
    cases were presented. Quorum is met when `cases_presented_count` is greater
    than zero, when every discipline in `required_disciplines` appears among the
    disciplines of the qualifying attendances, and when the rounded
    `prospective_case_ratio` is at least 0.80 — a ratio of exactly 0.800 meets the
    standard."

    Design: Corner/state_machines/session_hold_records_case_counts_and_computes_prospective_ratio
    """
    program = _program(api)
    session = _quorum_session(api, program["id"])

    held = assert_conference_session(
        assert_ok(api.hold_session(session["id"], f.hold_session_payload(10, 8), COORDINATOR))
    )

    assert held["session_state"] == "HELD"
    assert held["cases_presented_count"] == 10
    assert held["prospective_case_count"] == 8
    assert held["prospective_case_ratio"] == 0.8
    assert held["quorum_met"] is True
    assert held["credited_on"] is None

    reread = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread["credited_sessions_12mo"] == 0


def test_holding_a_session_before_its_start_instant_is_refused(api):
    """A September session cannot be held while the clock still reads August.

    PRD 3.7: "The session must be `SCHEDULED`, the logical clock instant must have
    reached `start_at` — a session cannot be held before it begins, and the refusal
    is `ERR_SESSION_NOT_YET_STARTED` — and `prospective_case_count` must not exceed
    `cases_presented_count`, an excess being `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/hold_before_session_start_at_rejected
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

    validate_error(
        api.hold_session(session["id"], f.hold_session_payload(6, 6), COORDINATOR),
        ApiErrorId.ERR_SESSION_NOT_YET_STARTED.value,
        409,
    )

    reread = assert_ok(api.get_conference_session(session["id"], COORDINATOR))
    assert reread["session_state"] == "SCHEDULED"
    assert reread["cases_presented_count"] == 0
    assert reread["quorum_met"] is False


def test_no_credit_reaches_a_terminal_state_without_crediting_anything(api):
    """The administrative refusal leaves quorum true and the numerator at zero.

    PRD 3.7: "`NO_CREDIT` moves it `HELD → NOT_CREDITED` with `credited_on` left
    null, so the session never enters the frequency numerator."

    Design: Corner/state_machines/credit_with_no_credit_disposition_leaves_frequency_numerator_untouched
    """
    program = _program(api)
    session = _quorum_session(api, program["id"])
    get_success_data(api.hold_session(session["id"], f.hold_session_payload(10, 8), COORDINATOR))

    credited = assert_ok(
        api.credit_session(
            session["id"],
            f.credit_session_payload(
                "NO_CREDIT", credit_note="no pathology representation present"
            ),
            COORDINATOR,
        )
    )

    assert credited["session_state"] == "NOT_CREDITED"
    assert credited["credited_on"] is None
    assert credited["quorum_met"] is True

    program_after = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert program_after["credited_sessions_12mo"] == 0
    assert program_after["required_sessions_12mo"] == 12
    assert program_after["conference_frequency_compliant"] is False
    assert program_after["coordinator_attendance_compliant"] is False

    validate_error(
        api.credit_session(session["id"], f.credit_session_payload("CREDIT"), COORDINATOR),
        ApiErrorId.ERR_SESSION_NOT_HELD.value,
        409,
    )


# --------------------------------------------------------------------------
# audits
# --------------------------------------------------------------------------
def test_a_freshly_opened_audit_posts_nothing_to_the_quality_ledger(api):
    """Opening an audit is bookkeeping only: every score field starts at zero.

    PRD 3.4: "A new audit opens in `OPEN` with `minor_discrepancy_count`,
    `major_discrepancy_count`, `critical_discrepancy_count`, and
    `weighted_error_score` at zero, `verdict` null, and `cascade_applied` false."

    Design: Corner/state_machines/audit_initial_state_is_open_with_zeroed_discrepancy_counts
    """
    world = _approved_abstraction(api)

    audit = assert_qa_audit(
        assert_created(
            api.create_qa_audit(
                f.qa_audit_payload(
                    world["abstraction"]["id"],
                    world["reviewer"]["id"],
                    audit_type="ROUTINE_10PCT",
                    window_start="2026-08-01",
                    window_end="2026-08-31",
                ),
                REGISTRY_MANAGER,
            )
        )
    )

    assert audit["audit_state"] == "OPEN"
    assert audit["verdict"] is None
    assert audit["weighted_error_score"] == 0
    assert audit["cascade_applied"] is False
    assert audit["minor_discrepancy_count"] == 0
    assert audit["major_discrepancy_count"] == 0
    assert audit["critical_discrepancy_count"] == 0
    assert audit["scored_at"] is None
    assert audit["audit_type"] == "ROUTINE_10PCT"

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["lifetime_discrepancy_points"] == 0
    assert author["quality_score_rolling_90d"] == 100.0


def test_scoring_an_already_closed_audit_cannot_post_its_points_twice(api):
    """The refused second score leaves two points on the ledger, not four.

    PRD 3.4: "An audit already scored is refused with
    `ERR_AUDIT_ALREADY_SCORED`, and a voided audit is refused with
    `ERR_AUDIT_ALREADY_VOIDED` — which, as §2.11 records, is checked first, so
    scoring a voided audit reports the void rather than the prior scoring."

    Design: Corner/state_machines/second_score_on_closed_audit_rejected
    """
    world = _approved_abstraction(api)
    audit = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                world["abstraction"]["id"],
                world["reviewer"]["id"],
                audit_type="ROUTINE_10PCT",
                window_start="2026-08-01",
                window_end="2026-08-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    score = f.audit_score_payload(audited_field_count=40, minor_discrepancy_count=2)
    first = assert_ok(
        api.score_qa_audit(
            audit["id"], score, make_qa_reviewer_headers(world["reviewer"]["id"])
        )
    )
    assert first["verdict"] == "PASS"
    assert first["weighted_error_score"] == 2
    assert first["audit_state"] == "CLOSED_PASS"

    validate_error(
        api.score_qa_audit(
            audit["id"], score, make_qa_reviewer_headers(world["reviewer"]["id"])
        ),
        ApiErrorId.ERR_AUDIT_ALREADY_SCORED.value,
        409,
    )

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["lifetime_discrepancy_points"] == 2
    assert author["audit_fail_streak"] == 0
    assert author["quality_score_rolling_90d"] == 95.0
    assert author["quality_score_cumulative"] == 95.0


def test_a_voided_audit_reports_its_own_terminal_code_on_a_second_void(api):
    """VOIDED accepts no further transition, and the void check is checked first.

    PRD 2.11: "A scoring attempt on an audit that has already been voided reports
    `ERR_AUDIT_ALREADY_VOIDED` rather than `ERR_AUDIT_ALREADY_SCORED`, because the
    voided check is ordered above the open-state check."

    Design: Corner/state_machines/voided_audit_cannot_be_voided_again
    """
    world = _approved_abstraction(api)
    audit = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                world["abstraction"]["id"],
                world["reviewer"]["id"],
                audit_type="TARGETED",
                window_start="2026-08-01",
                window_end="2026-08-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    first = assert_ok(
        api.void_qa_audit(
            audit["id"],
            f.audit_void_payload(void_reason="opened against the wrong abstraction"),
            REGISTRY_MANAGER,
        )
    )
    assert first["audit_state"] == "VOIDED"
    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["lifetime_discrepancy_points"] == 0

    error = validate_error(
        api.void_qa_audit(
            audit["id"], f.audit_void_payload(void_reason="duplicate void attempt"), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_AUDIT_ALREADY_VOIDED.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_AUDIT_ALREADY_SCORED.value

    reread = assert_ok(api.get_qa_audit(audit["id"], REGISTRY_MANAGER))
    assert reread["audit_state"] == "VOIDED"
    assert reread["verdict"] is None

    validate_error(
        api.score_qa_audit(
            audit["id"],
            f.audit_score_payload(audited_field_count=40),
            make_qa_reviewer_headers(world["reviewer"]["id"]),
        ),
        ApiErrorId.ERR_AUDIT_ALREADY_VOIDED.value,
        409,
    )


# --------------------------------------------------------------------------
# abstraction and staffing
# --------------------------------------------------------------------------
def test_a_qa_verdict_on_a_draft_abstraction_reports_the_state_error(api):
    """The abstract was never submitted, so the state check fires first.

    PRD 3.3: "A `QaReviewer` records a `verdict` of `APPROVED`,
    `REWORK_REQUIRED`, or `REJECTED`, optionally with a `reviewer_note`, against
    an abstraction that must be in `SUBMITTED_FOR_QA`
    (`ERR_ABSTRACTION_NOT_IN_QA`), and the reviewer's `X-User-ID` must differ from
    the abstraction's `abstractor_id` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)."

    Design: Corner/state_machines/qa_decision_on_draft_abstraction_rejected
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    case = _assigned_case(api, program["id"], author["id"])
    abstraction = _draft_abstraction(api, case, author["id"])

    error = validate_error(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(reviewer["id"]),
        ),
        ApiErrorId.ERR_ABSTRACTION_NOT_IN_QA.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value

    reread = assert_ok(api.get_abstraction(abstraction["id"], REGISTRY_MANAGER))
    assert reread["abstraction_state"] == "DRAFT"
    assert reread["approved_at"] is None

    reread_case = assert_ok(api.get_case(case["id"], REGISTRY_MANAGER))
    assert reread_case["case_state"] == "IN_ABSTRACTION"
    assert reread_case["completed_on"] is None


def test_suspending_a_registrar_releases_the_case_and_kills_the_draft(api):
    """One status change fires the release, the rejection, and the zeroed count.

    PRD 3.2: "Moving a registrar to `TERMINATED`,
    `SUSPENDED_FROM_ABSTRACTING`, or `LOA` releases their entire open worklist:
    every tumor case assigned to them whose case state is `ASSIGNED`,
    `IN_ABSTRACTION`, `QA_PENDING`, or `REWORK_PENDING` is returned to
    `IDENTIFIED` with `assigned_abstractor_id` cleared to null and its `version`
    incremented by one, processed in ascending `created_at` order."

    PRD 3.2: "Any abstraction sitting on a released case is moved to the terminal
    `REJECTED` state — `DRAFT → REJECTED` for one still being written and
    `REWORK_REQUIRED → REJECTED` for one awaiting rework — since the registrar who
    owned it can no longer work it."

    Design: Corner/state_machines/staffing_suspension_cascades_case_release_and_draft_abstraction_rejection
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    case = _assigned_case(api, program["id"], author["id"])
    abstraction = _draft_abstraction(api, case, author["id"])

    suspended = assert_ok(
        api.set_employment_status(
            author["id"],
            f.employment_status_payload(
                "SUSPENDED_FROM_ABSTRACTING",
                effective_on="2026-08-01",
                reason="certification review",
            ),
            REGISTRY_MANAGER,
        )
    )

    assert suspended["employment_status"] == "SUSPENDED_FROM_ABSTRACTING"
    assert suspended["assigned_open_case_count"] == 0

    released = assert_tumor_case(assert_ok(api.get_case(case["id"], REGISTRY_MANAGER)))
    assert released["case_state"] == "IDENTIFIED"
    assert released["assigned_abstractor_id"] is None

    rejected = assert_ok(api.get_abstraction(abstraction["id"], REGISTRY_MANAGER))
    assert rejected["abstraction_state"] == "REJECTED"

    reread = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread["open_backlog_count"] == 1
    assert reread["identified_case_count"] == 1
    assert reread["registry_posture"] == "OPEN"

    assert_workload_ledger_conserved(api, REGISTRY_MANAGER, program["id"])


def test_one_approval_reconciles_case_registrar_and_program_ledgers(api):
    """The same verdict closes the case on time and refreshes three other rows.

    PRD 3.3: "`APPROVED` is the deepest cascade in the system: the abstraction
    moves `SUBMITTED_FOR_QA → APPROVED` with `approved_at` stamped from the clock;
    because the abstraction was approved the case moves `QA_PENDING → COMPLETED`
    with `completed_on` set to the clock date and `timeliness_status` finalised;
    because the case left the open backlog the registrar's
    `assigned_open_case_count` is decremented by one and their
    `completed_cases_30d`, `productivity_rate_per_day`, and `productivity_status`
    are recomputed; because the backlog shrank, `open_backlog_count`,
    `overdue_backlog_count`, and `registry_posture` are recomputed; and because the
    posture was recomputed, a posture that leaves `FROZEN` returns every held batch
    to its `pre_hold_state`."

    Design: Corner/state_machines/qa_approval_ledger_syncs_program_backlog_and_abstractor_productivity
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    case = _assigned_case(api, program["id"], author["id"])
    abstraction = _draft_abstraction(api, case, author["id"])
    get_success_data(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(author["id"]),
        )
    )

    decided = assert_ok(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED", reviewer_note="stage and treatment verified"),
            make_qa_reviewer_headers(reviewer["id"]),
        )
    )

    assert decided["abstraction_state"] == "APPROVED"
    assert decided["qa_reviewer_user_id"] == reviewer["id"]

    closed = assert_ok(api.get_case(case["id"], REGISTRY_MANAGER))
    assert closed["case_state"] == "COMPLETED"
    assert closed["completed_on"] == "2026-08-01"
    assert closed["timeliness_status"] == "ON_TIME"
    assert closed["days_to_due"] == 153
    assert closed["submission_state"] == "NOT_SUBMITTED"

    registrar = assert_ok(api.get_abstractor(author["id"], REGISTRY_MANAGER))
    assert registrar["assigned_open_case_count"] == 0
    assert registrar["completed_cases_30d"] == 1
    assert registrar["productivity_rate_per_day"] == 0.05
    assert registrar["productivity_status"] == "BELOW"

    reread = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread["open_backlog_count"] == 0
    assert reread["overdue_backlog_count"] == 0
    assert reread["identified_case_count"] == 1
    assert reread["registry_posture"] == "OPEN"
