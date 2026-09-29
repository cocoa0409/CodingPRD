"""Entity-shape assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

_DATE_LEN = len("2026-08-01")


# --------------------------------------------------------------- shared stamps
def assert_identity_fields(entity):
    """Every minted resource carries a bare UUID id and a created_at instant."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"created_at is not an ISO 8601 instant: {entity['created_at']!r}"
    assert entity["created_at"].endswith("Z"), entity["created_at"]
    fractional = entity["created_at"].split(".")[-1]
    assert len(fractional) == 4, (
        "created_at must carry exactly three fractional digits: "
        f"{entity['created_at']!r}"
    )


def assert_versioned(entity, expected_version=None):
    """Most resources also carry updated_at and an integer version from 1."""
    assert_identity_fields(entity)
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), entity["version"]
    assert entity["version"] >= 1, entity["version"]
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_calendar_date(value, field="date"):
    assert isinstance(value, str) and len(value) == _DATE_LEN, f"{field}={value!r}"
    assert value[4] == "-" and value[7] == "-", f"{field}={value!r}"


def assert_rounded(value, places, field="value"):
    assert isinstance(value, (int, float)), f"{field}={value!r}"
    quantised = round(float(value), places)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{field}={value!r} is not rounded to {places} decimal place(s)"
    )


# ---------------------------------------------------------------------- program
def assert_program(program, expected_version=None):
    assert_versioned(program, expected_version)
    for field in (
        "name",
        "coc_program_id",
        "annual_analytic_caseload",
        "reference_year",
        "timeliness_standard_days",
        "accreditation_state",
        "registry_posture",
        "identified_case_count",
        "open_backlog_count",
        "overdue_backlog_count",
        "open_critical_deficiency_count",
        "follow_up_rate_coc_pct",
        "follow_up_rate_state_pct",
        "lost_to_follow_up_pct",
        "required_sessions_12mo",
        "credited_sessions_12mo",
        "conference_frequency_compliant",
        "coordinator_attendance_compliant",
        "next_survey_due_year",
    ):
        assert field in program, f"program is missing {field}"
    assert program["registry_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert program["accreditation_state"] in (
        "ACCREDITED",
        "SURVEY_SCHEDULED",
        "DEFICIENCY_RESPONSE",
        "PROBATION",
        "WITHDRAWN",
    )
    for pct in ("follow_up_rate_coc_pct", "follow_up_rate_state_pct", "lost_to_follow_up_pct"):
        assert_rounded(program[pct], 1, pct)
    return program


# ------------------------------------------------------------------- abstractor
def assert_abstractor(abstractor, expected_version=None):
    assert_versioned(abstractor, expected_version)
    for field in (
        "program_id",
        "name",
        "credential",
        "productivity_target_cases_per_day",
        "certification_expires_on",
        "employment_status",
        "assigned_open_case_count",
        "lifetime_discrepancy_points",
        "audit_fail_streak",
        "completed_cases_30d",
        "quality_score_rolling_90d",
        "quality_score_cumulative",
        "productivity_rate_per_day",
        "productivity_status",
    ):
        assert field in abstractor, f"abstractor is missing {field}"
    assert abstractor["credential"] in ("CTR", "NON_CTR", "TRAINEE")
    assert abstractor["employment_status"] in (
        "ACTIVE",
        "SUSPENDED_FROM_ABSTRACTING",
        "LOA",
        "TERMINATED",
    )
    assert abstractor["productivity_status"] in ("MEETS", "BELOW")
    assert_rounded(abstractor["quality_score_rolling_90d"], 1, "quality_score_rolling_90d")
    assert_rounded(abstractor["quality_score_cumulative"], 1, "quality_score_cumulative")
    assert_rounded(abstractor["productivity_rate_per_day"], 2, "productivity_rate_per_day")
    return abstractor


# ------------------------------------------------------------ casefinding source
def assert_casefinding_source(source, expected_version=None):
    assert_versioned(source, expected_version)
    for field in (
        "program_id",
        "source_type",
        "expected_monthly_volume",
        "entries_this_month",
        "casefinding_completeness_pct",
        "last_reconciled_through",
    ):
        assert field in source, f"casefinding source is missing {field}"
    assert source["source_type"] in (
        "PATHOLOGY",
        "DISEASE_INDEX",
        "RADIATION_ONCOLOGY",
        "MEDICAL_ONCOLOGY",
        "AUTOPSY",
    )
    assert_rounded(source["casefinding_completeness_pct"], 1, "casefinding_completeness_pct")
    assert 0.0 <= source["casefinding_completeness_pct"] <= 100.0
    return source


# ------------------------------------------------------------- casefinding entry
def assert_casefinding_entry(entry, expected_version=None):
    assert_versioned(entry, expected_version)
    for field in (
        "source_id",
        "program_id",
        "patient_mrn",
        "accession_date",
        "primary_site_code",
        "histology_code",
        "behavior_code",
        "diagnosis_date",
        "first_contact_date",
        "diagnosed_at_facility",
        "first_treatment_at_facility",
        "ambiguous_terminology_flag",
        "referral_lag_days",
        "class_of_case_code",
        "analytic_flag",
        "suggested_reportability",
        "suggested_reason_code",
        "reportability_state",
        "decision_reason_code",
        "override_reason_code",
        "decided_by_user_id",
        "created_case_id",
        "reopen_count",
    ):
        assert field in entry, f"casefinding entry is missing {field}"
    assert entry["class_of_case_code"] in (
        "CLASS_00",
        "CLASS_10",
        "CLASS_20",
        "CLASS_31",
        "CLASS_40",
    )
    assert entry["reportability_state"] in (
        "PENDING_REVIEW",
        "REPORTABLE",
        "NON_REPORTABLE",
    )
    assert isinstance(entry["referral_lag_days"], int)
    assert isinstance(entry["analytic_flag"], bool)
    return entry


# -------------------------------------------------------------------- tumor case
def assert_tumor_case(case, expected_version=None):
    assert_versioned(case, expected_version)
    for field in (
        "entry_id",
        "program_id",
        "patient_mrn",
        "class_of_case_code",
        "analytic_flag",
        "diagnosis_date",
        "first_contact_date",
        "sequence_number",
        "accession_number",
        "case_state",
        "submission_state",
        "assigned_abstractor_id",
        "abstract_due_date",
        "days_to_due",
        "timeliness_status",
        "completed_on",
        "vital_status",
        "last_contact_date",
        "follow_up_due_date",
        "follow_up_status",
    ):
        assert field in case, f"tumor case is missing {field}"
    assert case["case_state"] in (
        "IDENTIFIED",
        "ASSIGNED",
        "IN_ABSTRACTION",
        "QA_PENDING",
        "REWORK_PENDING",
        "COMPLETED",
        "VOIDED",
    )
    assert case["submission_state"] in (
        "NOT_SUBMITTED",
        "PENDING_SUBMISSION",
        "SUBMITTED",
        "ACCEPTED",
        "EDIT_REJECTED",
    )
    assert case["timeliness_status"] in ("ON_TIME", "AT_RISK", "LATE")
    assert case["vital_status"] in ("ALIVE", "DEAD", "UNKNOWN")
    assert isinstance(case["days_to_due"], int)
    assert isinstance(case["sequence_number"], int)
    return case


def assert_accession_number(case, expected):
    assert case["accession_number"] == expected, (
        f"expected accession_number {expected}, got {case['accession_number']}"
    )


# ------------------------------------------------------------------- abstraction
def assert_abstraction(abstraction, expected_version=None):
    assert_versioned(abstraction, expected_version)
    for field in (
        "case_id",
        "abstractor_id",
        "abstraction_state",
        "supersedes_abstraction_id",
        "rework_round",
        "completeness_score",
        "missing_required_fields",
        "stage_source",
        "stage_group",
        "treatment_modalities",
        "outcome_status",
        "submitted_at",
        "approved_at",
    ):
        assert field in abstraction, f"abstraction is missing {field}"
    assert abstraction["abstraction_state"] in (
        "DRAFT",
        "SUBMITTED_FOR_QA",
        "APPROVED",
        "REWORK_REQUIRED",
        "REJECTED",
        "SUPERSEDED",
    )
    assert isinstance(abstraction["completeness_score"], int)
    assert 0 <= abstraction["completeness_score"] <= 100
    assert isinstance(abstraction["missing_required_fields"], list)
    assert abstraction["missing_required_fields"] == sorted(
        abstraction["missing_required_fields"]
    ), "missing_required_fields must be sorted alphabetically"
    return abstraction


# ---------------------------------------------------------------------- qa audit
def assert_qa_audit(audit, expected_version=None):
    assert_versioned(audit, expected_version)
    for field in (
        "abstraction_id",
        "auditor_id",
        "audit_type",
        "window_start",
        "window_end",
        "audit_state",
        "audited_field_count",
        "minor_discrepancy_count",
        "major_discrepancy_count",
        "critical_discrepancy_count",
        "weighted_error_score",
        "verdict",
        "cascade_applied",
        "scored_at",
    ):
        assert field in audit, f"qa audit is missing {field}"
    assert audit["audit_state"] in ("OPEN", "CLOSED_PASS", "CLOSED_FAIL", "VOIDED")
    assert audit["audit_type"] in ("ROUTINE_10PCT", "TARGETED", "PRE_SURVEY")
    assert audit["verdict"] in (None, "PASS", "MINOR_FAIL", "CRITICAL_FAIL")
    assert isinstance(audit["weighted_error_score"], int)
    assert isinstance(audit["cascade_applied"], bool)
    return audit


def assert_weighted_error_score(audit, critical, major, minor):
    """Five points per critical, three per major, one per minor."""
    expected = 5 * critical + 3 * major + 1 * minor
    assert audit["weighted_error_score"] == expected, (
        f"expected weighted_error_score {expected}, got {audit['weighted_error_score']}"
    )


# -------------------------------------------------------------- follow-up contact
def assert_follow_up_contact(contact):
    """A follow-up contact is an immutable event row: no updated_at, no version."""
    assert_identity_fields(contact)
    assert "updated_at" not in contact, "follow-up contacts carry no updated_at"
    assert "version" not in contact, "follow-up contacts carry no version"
    for field in (
        "case_id",
        "contact_date",
        "contact_method",
        "outcome",
        "vital_status_at_contact",
        "counts_for_follow_up",
        "recorded_by_user_id",
    ):
        assert field in contact, f"follow-up contact is missing {field}"
    assert contact["outcome"] in (
        "CONTACT_MADE",
        "NO_RESPONSE",
        "DECEASED",
        "MOVED_UNKNOWN",
    )
    assert isinstance(contact["counts_for_follow_up"], bool)
    return contact


# -------------------------------------------------------------------- submission
def assert_submission(submission, expected_version=None):
    assert_versioned(submission, expected_version)
    for field in (
        "program_id",
        "period_start",
        "period_end",
        "deadline_date",
        "submission_state",
        "pre_hold_state",
        "total_case_count",
        "accepted_item_count",
        "failed_item_count",
        "resubmission_round",
        "late_case_count",
        "assessment_due_cents",
        "assessment_paid_cents",
        "relief_pct",
        "edit_error_codes",
        "transmitted_at",
    ):
        assert field in submission, f"submission is missing {field}"
    assert submission["submission_state"] in (
        "DRAFT",
        "HOLD",
        "TRANSMITTED",
        "EDITS_RETURNED",
        "ACCEPTED",
    )
    for cents in ("assessment_due_cents", "assessment_paid_cents"):
        assert isinstance(submission[cents], int), f"{cents} must be integer cents"
    assert isinstance(submission["edit_error_codes"], list)
    return submission


def assert_submission_item(item, expected_version=None):
    assert_versioned(item, expected_version)
    for field in ("submission_id", "case_id", "edit_status", "edit_codes"):
        assert field in item, f"submission item is missing {field}"
    assert item["edit_status"] in ("PENDING", "ACCEPTED", "EDIT_FAILED", "RESOLVED")
    assert isinstance(item["edit_codes"], list)
    return item


# ------------------------------------------------------------ conference session
def assert_conference_session(session, expected_version=None):
    assert_versioned(session, expected_version)
    for field in (
        "program_id",
        "start_at",
        "end_at",
        "required_disciplines",
        "session_state",
        "attendances",
        "cases_presented_count",
        "prospective_case_count",
        "prospective_case_ratio",
        "quorum_met",
        "credited_on",
    ):
        assert field in session, f"conference session is missing {field}"
    assert session["session_state"] in (
        "SCHEDULED",
        "HELD",
        "CREDITED",
        "NOT_CREDITED",
    )
    assert isinstance(session["attendances"], list)
    assert isinstance(session["quorum_met"], bool)
    assert_rounded(session["prospective_case_ratio"], 3, "prospective_case_ratio")
    return session


def assert_attendance_entry(entry):
    for field in (
        "attendee_ref",
        "discipline",
        "is_required_coordinator",
        "attended_minutes",
    ):
        assert field in entry, f"attendance entry is missing {field}"
    return entry


# --------------------------------------------------------------- quality measure
def assert_quality_measure(measure, expected_version=None):
    assert_versioned(measure, expected_version)
    for field in (
        "program_id",
        "measure_code",
        "measurement_year",
        "threshold_pct",
        "measure_state",
        "strata",
        "included_strata_count",
        "performance_state",
    ):
        assert field in measure, f"quality measure is missing {field}"
    assert measure["measure_state"] in (
        "DRAFT",
        "MEASURED",
        "PROJECT_REQUIRED",
        "PROJECT_ACTIVE",
        "PROJECT_CLOSED_ACHIEVED",
        "PROJECT_CLOSED_MISSED",
    )
    assert measure["performance_state"] in (
        "NOT_EVALUATED",
        "EXCEEDS",
        "MEETS",
        "UNDER_THRESHOLD",
    )
    assert isinstance(measure["strata"], list)
    return measure


# -------------------------------------------------------------------- deficiency
def assert_deficiency(deficiency, expected_version=None):
    assert_versioned(deficiency, expected_version)
    for field in (
        "program_id",
        "standard_code",
        "severity",
        "cited_on",
        "response_due_date",
        "deficiency_state",
        "escalation_count",
        "response_narrative",
        "reviewer_notes",
        "source_measure_id",
    ):
        assert field in deficiency, f"deficiency is missing {field}"
    assert deficiency["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert deficiency["deficiency_state"] in (
        "CITED",
        "RESPONSE_SUBMITTED",
        "RESPONSE_REJECTED",
        "RESOLVED",
        "ESCALATED",
    )
    assert isinstance(deficiency["escalation_count"], int)
    return deficiency


# ----------------------------------------------------------- domain invariants
OPEN_BACKLOG_STATES = (
    "IDENTIFIED",
    "ASSIGNED",
    "IN_ABSTRACTION",
    "QA_PENDING",
    "REWORK_PENDING",
)
WORKLOAD_STATES = ("ASSIGNED", "IN_ABSTRACTION", "QA_PENDING", "REWORK_PENDING")


def _all_records(list_call, headers, **filters):
    records = []
    offset = 0
    while True:
        params = dict(filters)
        params.update({"limit": 100, "offset": offset})
        response = list_call(headers, params=params)
        data, meta = validate_paginated(response)
        records.extend(data)
        if not meta.get("has_more"):
            break
        offset += 100
    return records


def assert_workload_ledger_conserved(client, headers, program_id):
    """Registrar workload must equal the program's assigned open case count."""
    abstractors = _all_records(client.list_abstractors, headers, program_id=program_id)
    cases = _all_records(client.list_cases, headers, program_id=program_id)
    ledger_total = sum(a["assigned_open_case_count"] for a in abstractors)
    actual_total = sum(
        1
        for c in cases
        if c["assigned_abstractor_id"] is not None
        and c["case_state"] in WORKLOAD_STATES
    )
    assert ledger_total == actual_total, (
        "open abstraction workload is not conserved: registrars report "
        f"{ledger_total} open cases, the case population holds {actual_total}"
    )
    return ledger_total


def assert_discrepancy_points_conserved(client, headers, abstractor_id):
    """lifetime_discrepancy_points equals the closed audits' weighted scores."""
    abstractor = get_success_data(client.get_abstractor(abstractor_id, headers))
    abstractions = _all_records(
        client.list_abstractions, headers, abstractor_id=abstractor_id
    )
    expected = 0
    for abstraction in abstractions:
        audits = _all_records(
            client.list_qa_audits, headers, abstraction_id=abstraction["id"]
        )
        for audit in audits:
            if audit["audit_state"] in ("CLOSED_PASS", "CLOSED_FAIL"):
                expected += audit["weighted_error_score"]
    assert abstractor["lifetime_discrepancy_points"] == expected, (
        f"expected lifetime_discrepancy_points {expected}, got "
        f"{abstractor['lifetime_discrepancy_points']}"
    )
    return expected


def assert_reportable_case_parity(client, headers, program_id):
    """Non-voided cases, REPORTABLE entries, and identified_case_count agree."""
    program = get_success_data(client.get_program(program_id, headers))
    cases = _all_records(client.list_cases, headers, program_id=program_id)
    entries = _all_records(
        client.list_casefinding_entries, headers, program_id=program_id
    )
    live_cases = sum(1 for c in cases if c["case_state"] != "VOIDED")
    reportable_entries = sum(
        1 for e in entries if e["reportability_state"] == "REPORTABLE"
    )
    assert live_cases == reportable_entries == program["identified_case_count"], (
        "reportable-case parity broken: non-voided cases="
        f"{live_cases}, REPORTABLE entries={reportable_entries}, "
        f"identified_case_count={program['identified_case_count']}"
    )
    return live_cases


def assert_posture(program, expected_posture):
    assert program["registry_posture"] == expected_posture, (
        f"expected registry_posture {expected_posture}, got "
        f"{program['registry_posture']}"
    )


def assert_created(response):
    """Resource creation returns HTTP 201."""
    return validate_success(response, expected_status=201)


def assert_ok(response):
    """Every other successful call returns HTTP 200."""
    return validate_success(response, expected_status=200)
