"""Inclusive boundaries, empty-set quorum and the two calendar conventions."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_casefinding_entry,
    assert_conference_session,
    assert_created,
    assert_ok,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
    validate_paginated,
)

COORDINATOR = make_accreditation_coordinator_headers("coord-lee")


def _program(api, coc_program_id, name, caseload=620):
    return get_success_data(
        api.create_program(
            f.program_payload(
                name=name,
                coc_program_id=coc_program_id,
                annual_analytic_caseload=caseload,
                reference_year=2018,
                timeliness_standard_days=180,
            ),
            PLATFORM_ADMIN,
        )
    )


# --------------------------------------------------------------------------
# referral_lag_exactly_120_days_is_analytic_class_20_and_121_is_not
# --------------------------------------------------------------------------
def _referral_source(api):
    program = _program(api, "COC-14561", "Alder Grove Cancer Program")
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program["id"],
                source_type="MEDICAL_ONCOLOGY",
                expected_monthly_volume=40,
            ),
            REGISTRY_MANAGER,
        )
    )
    return source


def _referral_entry(api, source_id, mrn, first_contact_date):
    return api.create_casefinding_entry(
        source_id,
        f.casefinding_entry_payload(
            patient_mrn=mrn,
            accession_date="2026-08-05",
            primary_site_code="C50.9",
            histology_code="8500/3",
            behavior_code="MALIGNANT_3",
            diagnosis_date="2026-01-01",
            first_contact_date=first_contact_date,
            diagnosed_at_facility=False,
            first_treatment_at_facility=True,
        ),
        REGISTRY_MANAGER,
    )


def test_referral_lag_of_exactly_120_days_stays_analytic(api):
    """One day either side of the boundary flips the class of case.

    PRD 3.1: "The boundary is inclusive — a lag of exactly 120 days is analytic
    `CLASS_20` while 121 days is non-analytic `CLASS_31`."

    Design: Difficulty/boundary_precision_check/referral_lag_exactly_120_days_is_analytic_class_20_and_121_is_not
    """
    source = _referral_source(api)

    entry_120 = assert_casefinding_entry(
        assert_created(_referral_entry(api, source["id"], "MRN-3901", "2026-05-01"))
    )
    entry_121 = assert_casefinding_entry(
        assert_created(_referral_entry(api, source["id"], "MRN-3902", "2026-05-02"))
    )

    assert entry_120["referral_lag_days"] == 120
    assert entry_120["class_of_case_code"] == "CLASS_20"
    assert entry_120["analytic_flag"] is True
    assert entry_121["referral_lag_days"] == 121
    assert entry_121["class_of_case_code"] == "CLASS_31"
    assert entry_121["analytic_flag"] is False


def test_both_boundary_entries_are_suggested_reportable_and_count_for_completeness(api):
    """Class of case is independent of the reportability suggestion.

    PRD 3.1: "Otherwise, if the behaviour is either `MALIGNANT_3` or `IN_SITU_2`,
    the suggestion is `REPORTABLE` with reason `SEER_REPORTABLE_BEHAVIOR`."

    Design: Difficulty/boundary_precision_check/referral_lag_exactly_120_days_is_analytic_class_20_and_121_is_not
    """
    source = _referral_source(api)

    entry_120 = get_success_data(
        _referral_entry(api, source["id"], "MRN-3901", "2026-05-01")
    )
    entry_121 = get_success_data(
        _referral_entry(api, source["id"], "MRN-3902", "2026-05-02")
    )

    assert entry_120["suggested_reportability"] == "REPORTABLE"
    assert entry_121["suggested_reportability"] == "REPORTABLE"

    reread = assert_ok(api.get_casefinding_source(source["id"], REGISTRY_MANAGER))
    assert reread["entries_this_month"] == 2
    assert reread["casefinding_completeness_pct"] == 5.0


# --------------------------------------------------------------------------
# conference_credit_with_zero_cases_presented_fails_quorum_on_empty_set
# --------------------------------------------------------------------------
ATTENDEES = [
    ("dr-abbott", "SURGERY", True),
    ("dr-bell", "MEDICAL_ONCOLOGY", False),
    ("dr-choi", "RADIATION_ONCOLOGY", False),
    ("dr-devi", "PATHOLOGY", False),
    ("dr-ellis", "RADIOLOGY", False),
]


def _held_session_without_cases(api):
    program = _program(api, "COC-14562", "Pinehurst Cancer Program")
    session = get_success_data(
        api.create_conference_session(
            f.conference_session_payload(
                program["id"],
                start_at="2026-08-05T13:00:00Z",
                end_at="2026-08-05T14:00:00Z",
                required_disciplines=[
                    "SURGERY",
                    "MEDICAL_ONCOLOGY",
                    "RADIATION_ONCOLOGY",
                    "PATHOLOGY",
                    "RADIOLOGY",
                ],
            ),
            COORDINATOR,
        )
    )
    for attendee_ref, discipline, is_coordinator in ATTENDEES:
        payload = f.attendance_payload(attendee_ref, discipline, attended_minutes=45)
        if is_coordinator:
            payload["is_required_coordinator"] = True
        get_success_data(api.record_attendance(session["id"], payload, COORDINATOR))
    get_success_data(
        api.set_clock(f.clock_payload("2026-08-05T14:00:00Z"), PLATFORM_ADMIN)
    )
    get_success_data(
        api.hold_session(
            session["id"],
            f.hold_session_payload(cases_presented_count=0, prospective_case_count=0),
            COORDINATOR,
        )
    )
    return {"program": program, "session": session}


def test_credit_is_refused_when_no_cases_were_presented(api):
    """Every required discipline attended, yet the empty case set defeats quorum.

    PRD 3.7: "Quorum is met when `cases_presented_count` is greater than zero,
    when every discipline in `required_disciplines` appears among the disciplines
    of the qualifying attendances, and when the rounded `prospective_case_ratio`
    is at least 0.80 — a ratio of exactly 0.800 meets the standard."

    Design: Difficulty/boundary_precision_check/conference_credit_with_zero_cases_presented_fails_quorum_on_empty_set
    """
    world = _held_session_without_cases(api)

    response = api.credit_session(
        world["session"]["id"],
        f.credit_session_payload("CREDIT", credit_note="administrative session"),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_CONFERENCE_QUORUM_NOT_MET.value, 409)

    session = assert_conference_session(
        assert_ok(api.get_conference_session(world["session"]["id"], COORDINATOR))
    )
    assert session["session_state"] == "HELD"
    assert session["credited_on"] is None
    assert session["quorum_met"] is False
    assert session["prospective_case_ratio"] == 0.0
    assert session["cases_presented_count"] == 0
    assert all(entry["attended_minutes"] == 45 for entry in session["attendances"])


def test_uncredited_session_never_enters_the_conference_frequency_numerator(api):
    """A held-but-uncredited session leaves the program short of its 24 sessions.

    PRD 3.7: "`credited_sessions_12mo` counts only the program's sessions in
    `CREDITED` whose `start_at` date falls inside the window — `NOT_CREDITED`,
    `HELD`, and `SCHEDULED` sessions are excluded from both numerator and
    denominator — and `conference_frequency_compliant` is true when
    `credited_sessions_12mo` is at least `required_sessions_12mo`."

    Design: Difficulty/boundary_precision_check/conference_credit_with_zero_cases_presented_fails_quorum_on_empty_set
    """
    world = _held_session_without_cases(api)

    api.credit_session(
        world["session"]["id"],
        f.credit_session_payload("CREDIT", credit_note="administrative session"),
        COORDINATOR,
    )

    program = assert_ok(api.get_program(world["program"]["id"], REGISTRY_MANAGER))
    assert program["credited_sessions_12mo"] == 0
    assert program["required_sessions_12mo"] == 24
    assert program["conference_frequency_compliant"] is False


# --------------------------------------------------------------------------
# conference_back_to_back_session_violates_thirty_minute_changeover_buffer
# --------------------------------------------------------------------------
DISCIPLINES = ["SURGERY", "MEDICAL_ONCOLOGY", "PATHOLOGY"]


def _kingsway_with_afternoon_session(api):
    program = _program(api, "COC-14565", "Kingsway Cancer Program")
    session = get_success_data(
        api.create_conference_session(
            f.conference_session_payload(
                program["id"],
                start_at="2026-08-05T13:00:00Z",
                end_at="2026-08-05T14:00:00Z",
                required_disciplines=DISCIPLINES,
            ),
            COORDINATOR,
        )
    )
    return {"program": program, "session": session}


def _candidate(api, program_id, start_at, end_at):
    return api.create_conference_session(
        f.conference_session_payload(
            program_id,
            start_at=start_at,
            end_at=end_at,
            required_disciplines=DISCIPLINES,
        ),
        COORDINATOR,
    )


def test_back_to_back_conference_session_is_refused_by_the_changeover_buffer(api):
    """A candidate starting exactly at the previous end time still conflicts.

    PRD 3.7: "Back-to-back sessions conflict: a candidate starting exactly when
    an existing session ends is refused, because the changeover buffer has not
    elapsed."

    Design: Difficulty/resource_temporal_overlap/conference_back_to_back_session_violates_thirty_minute_changeover_buffer
    """
    world = _kingsway_with_afternoon_session(api)

    response = _candidate(
        api, world["program"]["id"], "2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_CONFERENCE_SLOT_CONFLICT.value, 409)

    existing = assert_ok(
        api.get_conference_session(world["session"]["id"], COORDINATOR)
    )
    assert existing["session_state"] == "SCHEDULED"
    # NOTE: the PRD pins a three-fractional-digit rendering only for the audit
    # stamps it mints itself (2.4) and never says whether a client-supplied
    # instant is echoed byte-for-byte or re-serialised into that canonical form,
    # so the exact echoed spelling of start_at/end_at is not asserted here.


def test_session_starting_exactly_on_the_buffered_edge_is_accepted(api):
    """Thirty minutes after the previous end time is the first legal slot.

    PRD 3.7: "A candidate starting exactly 30 minutes after an existing session
    ends is accepted, because the comparison against the buffered edge is
    strict."

    Design: Difficulty/resource_temporal_overlap/conference_back_to_back_session_violates_thirty_minute_changeover_buffer
    """
    world = _kingsway_with_afternoon_session(api)
    _candidate(api, world["program"]["id"], "2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z")

    accepted = assert_created(
        _candidate(
            api, world["program"]["id"], "2026-08-05T14:30:00Z", "2026-08-05T15:30:00Z"
        )
    )
    assert accepted["session_state"] == "SCHEDULED"

    sessions, _meta = validate_paginated(
        api.list_conference_sessions(
            COORDINATOR, params={"program_id": world["program"]["id"], "limit": 100}
        )
    )
    assert len(sessions) == 2


# --------------------------------------------------------------------------
# third_overlapping_auditor_window_exceeds_capacity_until_one_is_voided
# --------------------------------------------------------------------------
def _auditor_with_two_overlapping_windows(api):
    program = _program(api, "COC-14566", "Silverton Cancer Program")
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
    auditor = get_success_data(
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
    entry = get_success_data(
        api.create_casefinding_entry(
            source["id"],
            f.casefinding_entry_payload(
                patient_mrn="MRN-4201",
                accession_date="2026-08-05",
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
    audit_1 = get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                abstraction["id"],
                auditor["id"],
                audit_type="ROUTINE_10PCT",
                window_start="2026-07-01",
                window_end="2026-07-31",
            ),
            make_qa_reviewer_headers(auditor["id"]),
        )
    )
    get_success_data(
        api.create_qa_audit(
            f.qa_audit_payload(
                abstraction["id"],
                auditor["id"],
                audit_type="TARGETED",
                window_start="2026-07-15",
                window_end="2026-08-15",
            ),
            make_qa_reviewer_headers(auditor["id"]),
        )
    )
    return {
        "author": author,
        "auditor": auditor,
        "abstraction": abstraction,
        "audit_1": audit_1,
    }


def _third_window(api, world):
    return api.create_qa_audit(
        f.qa_audit_payload(
            world["abstraction"]["id"],
            world["auditor"]["id"],
            audit_type="PRE_SURVEY",
            window_start="2026-07-31",
            window_end="2026-08-31",
        ),
        make_qa_reviewer_headers(world["auditor"]["id"]),
    )


def test_third_overlapping_auditor_window_exceeds_the_aggregate_capacity(api):
    """A window that merely touches an existing one still counts as overlapping.

    PRD 3.4: "Overlap is not an error in itself: an auditor may hold up to two
    mutually overlapping windows, and only the third overlapping window is
    refused, with `ERR_AUDITOR_WINDOW_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/third_overlapping_auditor_window_exceeds_capacity_until_one_is_voided
    """
    world = _auditor_with_two_overlapping_windows(api)

    response = _third_window(api, world)

    validate_error(
        response, ApiErrorId.ERR_AUDITOR_WINDOW_CAPACITY_EXCEEDED.value, 409
    )

    author = assert_ok(api.get_abstractor(world["author"]["id"], REGISTRY_MANAGER))
    assert author["lifetime_discrepancy_points"] == 0


def test_voiding_one_window_immediately_releases_the_auditor_slot(api):
    """The identical third request succeeds once a window is voided.

    PRD 3.4: "Only the same auditor's non-voided audits count, so voiding one of
    two overlapping windows immediately makes room for a third."

    Design: Difficulty/resource_temporal_overlap/third_overlapping_auditor_window_exceeds_capacity_until_one_is_voided
    """
    world = _auditor_with_two_overlapping_windows(api)
    _third_window(api, world)

    voided = assert_ok(
        api.void_qa_audit(
            world["audit_1"]["id"],
            f.audit_void_payload(
                void_reason="window opened against the wrong audit programme"
            ),
            REGISTRY_MANAGER,
        )
    )
    assert voided["audit_state"] == "VOIDED"

    retried = assert_created(_third_window(api, world))
    assert retried["audit_state"] == "OPEN"
    assert retried["window_start"] == "2026-07-31"

    audits, _meta = validate_paginated(
        api.list_qa_audits(
            REGISTRY_MANAGER,
            params={"auditor_id": world["auditor"]["id"], "limit": 100},
        )
    )
    assert len([a for a in audits if a["audit_state"] != "VOIDED"]) == 2
