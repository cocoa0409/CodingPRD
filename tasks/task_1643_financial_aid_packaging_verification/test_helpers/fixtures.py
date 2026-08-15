"""Composite setup helpers.

The harness restarts the server before every individual test, so every test
starts against an empty database. These helpers build complete precondition
chains out of PRD-declared endpoints only. Setup calls use get_success_data()
so a broken precondition surfaces as a clear "Setup step failed" error.

Identity threading: Student-role calls are entity-backed, so accept / decline /
revision / acknowledge calls always use make_student_headers(student["id"]).
Segregation-of-duties scenarios thread distinct opaque officer ids via
make_aid_officer_headers("officer-alpha") / ("officer-beta").
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_TEST,
    FUND_SPEC_PELL,
    SSN_NOT_SELECTED_A,
)
from .factories import (
    create_aid_year_payload,
    create_award_package_payload,
    create_conflicting_info_case_payload,
    create_disbursement_payload,
    create_external_aid_payload,
    create_fund_type_payload,
    create_isir_payload,
    create_pj_case_payload,
    create_student_payload,
    line_acceptance,
)
from .test_users import TEST_USERS, make_aid_officer_headers, make_student_headers

DIRECTOR = TEST_USERS["aid_director_headers"]
OFFICER = TEST_USERS["aid_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: clock, aid year, funds, students, ISIR import
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_TEST):
    """Set the logical clock (AidDirector-only test-driving capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def create_aid_year(**overrides):
    """Create an AidYear in DRAFT. Returns the aid year."""
    return get_success_data(api_client.create_aid_year(
        create_aid_year_payload(**overrides), DIRECTOR))


def create_fund(aid_year_id, **overrides):
    """Create a FundType in DRAFT under the aid year. Returns the fund."""
    return get_success_data(api_client.create_fund_type(
        create_fund_type_payload(aid_year_id, **overrides), DIRECTOR))


def activate_fund(fund_type_id):
    return get_success_data(api_client.activate_fund_type(fund_type_id, DIRECTOR))


def open_aid_year(aid_year_id):
    return get_success_data(api_client.open_aid_year(aid_year_id, DIRECTOR))


def setup_open_aid_year(fund_specs=None, year_overrides=None):
    """Clock set, aid year created, every fund created+activated, year OPEN.

    Returns {"aid_year": ..., "funds": {fund_code: fund}}.
    """
    set_clock()
    aid_year = create_aid_year(**(year_overrides or {}))
    funds = {}
    for spec in (fund_specs if fund_specs is not None else [FUND_SPEC_PELL]):
        fund = create_fund(aid_year["id"], **spec)
        funds[fund["fund_code"]] = fund
    for fund in funds.values():
        funds[fund["fund_code"]] = activate_fund(fund["id"])
    aid_year = open_aid_year(aid_year["id"])
    return {"aid_year": aid_year, "funds": funds}


def register_student(ssn=SSN_NOT_SELECTED_A, **overrides):
    """Register a student. Returns the student."""
    return get_success_data(api_client.create_student(
        create_student_payload(ssn, **overrides), OFFICER))


def register_sap_ready_student(ssn=SSN_NOT_SELECTED_A, **overrides):
    """Register a student whose SAP inputs pass every gate (gpa 3.00, 30/30
    credits), then run the STANDARD evaluation so sap_status is GOOD_STANDING."""
    overrides.setdefault("gpa_hundredths", 300)
    overrides.setdefault("cumulative_attempted_credits", 30)
    overrides.setdefault("cumulative_completed_credits", 30)
    student = register_student(ssn, **overrides)
    get_success_data(api_client.evaluate_sap(student["id"], {}, OFFICER))
    return get_success_data(api_client.get_student(student["id"], OFFICER))


def import_isir(student_id, aid_year_id, **overrides):
    """Import an ISIR transaction. Returns the record."""
    return get_success_data(api_client.create_isir_record(
        create_isir_payload(student_id, aid_year_id, **overrides), OFFICER))


def get_isir(isir_id):
    return get_success_data(api_client.get_isir_record(isir_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 2: verification casework
# ---------------------------------------------------------------------------

def find_verification_case(student_id):
    """First verification case for the student, or None when none exists."""
    data, _meta = validate_paginated(
        api_client.list_student_verification_cases(student_id, OFFICER))
    return data[0] if data else None


def get_verification_case(case_id):
    return get_success_data(api_client.get_verification_case(case_id, OFFICER))


def get_case_documents(case_id):
    data, _meta = validate_paginated(
        api_client.list_verification_documents(case_id, OFFICER))
    return data


def documents_by_type(docs):
    return {d["doc_type"]: d for d in docs}


def drive_case_to_under_review(case_id, accept_count=3):
    """Mark every required document received, accept the first `accept_count`,
    then begin review. Returns the case (UNDER_REVIEW)."""
    docs = get_case_documents(case_id)
    for doc in docs:
        get_success_data(api_client.mark_document_received(doc["id"], OFFICER))
    for doc in docs[:accept_count]:
        get_success_data(api_client.accept_document(doc["id"], OFFICER))
    return get_success_data(api_client.begin_review_verification_case(case_id, OFFICER))


def waive_open_verification_case(student_id,
                                 waived_reason="Director waiver per office policy"):
    """Waive the student's verification case when one exists. Returns the case
    or None. Used when a scenario needs Title IV disbursement eligibility for a
    student whose record was institutionally selected for verification."""
    case = find_verification_case(student_id)
    if case is None:
        return None
    return get_success_data(api_client.waive_verification_case(
        case["id"], waived_reason, DIRECTOR))


def setup_selected_student_case(year_funds, ssn, isir_overrides=None):
    """Import an ISIR for a verification-selected student and return
    (student, isir, case). The case is in DOCUMENTS_REQUESTED with three
    REQUESTED required documents."""
    student = register_student(ssn)
    isir = import_isir(student["id"], year_funds["aid_year"]["id"],
                       **(isir_overrides or {}))
    case = find_verification_case(student["id"])
    assert case is not None, "expected the selected ISIR to open a verification case"
    return student, isir, case


# ---------------------------------------------------------------------------
# Tier 3: packaging lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_package(student_id, aid_year_id):
    return get_success_data(api_client.create_award_package(
        create_award_package_payload(student_id, aid_year_id), OFFICER))


def build_package(package_id):
    return get_success_data(api_client.build_award_package(package_id, OFFICER))


def notify_package(package_id):
    return get_success_data(api_client.notify_award_package(package_id, OFFICER))


def get_package(package_id):
    return get_success_data(api_client.get_award_package(package_id, OFFICER))


def get_package_lines(package_id):
    data, _meta = validate_paginated(
        api_client.list_package_award_lines(package_id, OFFICER))
    return data


def lines_by_fund(lines, funds):
    """Map fund_code -> AwardLine. Robust against list-order ties because the
    packaging waterfall creates every line within a single build call."""
    by_id = {f["id"]: code for code, f in funds.items()}
    return {by_id[line["fund_type_id"]]: line for line in lines}


def get_package_notifications(package_id):
    data, _meta = validate_paginated(
        api_client.list_package_notifications(package_id, OFFICER))
    return data


def accept_lines(package_id, student_id, line_amounts):
    """Student acceptance call. line_amounts: list of (line_id, accept_cents)."""
    payload = [line_acceptance(line_id, cents) for line_id, cents in line_amounts]
    return api_client.accept_award_package(
        package_id, payload, make_student_headers(student_id))


def accept_package_in_full(package_id, student_id):
    """Accept every offered line at its full offered amount. Returns the
    updated package."""
    lines = get_package_lines(package_id)
    resp = accept_lines(package_id, student_id,
                        [(line["id"], line["offered_cents"]) for line in lines])
    return get_success_data(resp)


def lock_package(package_id):
    """Lock with the package's currently observed version (OCC). Returns the
    LOCKED package."""
    current = get_package(package_id)
    return get_success_data(api_client.lock_award_package(
        package_id, current["version"], OFFICER))


def setup_notified_package(ssn=SSN_NOT_SELECTED_A, fund_specs=None,
                           student_overrides=None, isir_overrides=None,
                           year_overrides=None):
    """Open aid year + student + current ISIR + package built and notified.
    Returns dict(aid_year, funds, student, isir, package, lines)."""
    env = setup_open_aid_year(fund_specs, year_overrides)
    student = register_student(ssn, **(student_overrides or {}))
    isir = import_isir(student["id"], env["aid_year"]["id"],
                       **(isir_overrides or {}))
    package = create_package(student["id"], env["aid_year"]["id"])
    package = build_package(package["id"])
    package = notify_package(package["id"])
    lines = get_package_lines(package["id"])
    return {**env, "student": student, "isir": isir,
            "package": package, "lines": lines}


# ---------------------------------------------------------------------------
# Tier 4: disbursement pipeline (package LOCKED, line DISBURSING)
# ---------------------------------------------------------------------------

def setup_disbursing_line(ssn=SSN_NOT_SELECTED_A, fund_specs=None,
                          student_overrides=None, isir_overrides=None):
    """Full pipeline: notified package, student accepts every line in full,
    officer locks, first line moved to DISBURSING. The student is SAP-evaluated
    to GOOD_STANDING so eligibility checks can pass.

    Returns dict(aid_year, funds, student, isir, package, lines, line).
    """
    env = setup_notified_package(
        ssn=ssn, fund_specs=fund_specs,
        student_overrides=student_overrides, isir_overrides=isir_overrides)
    env["student"] = _ensure_sap_evaluated(env["student"])
    package = accept_package_in_full(env["package"]["id"], env["student"]["id"])
    package = lock_package(package["id"])
    line = env["lines"][0]
    line = get_success_data(api_client.begin_line_disbursement(line["id"], OFFICER))
    return {**env, "package": package, "line": line}


def _ensure_sap_evaluated(student):
    """Run the STANDARD SAP evaluation once so sap_status leaves NOT_EVALUATED.
    Any first evaluation lands in GOOD_STANDING or WARNING, both of which pass
    the disbursement eligibility SAP gate (PRD §3.7 check 2)."""
    get_success_data(api_client.evaluate_sap(student["id"], {}, OFFICER))
    return get_success_data(api_client.get_student(student["id"], OFFICER))


def schedule_disbursement(line_id, scheduled_cents, term_code="2026-FALL"):
    """Create a SCHEDULED disbursement against a DISBURSING line."""
    return get_success_data(api_client.create_disbursement(
        create_disbursement_payload(line_id, scheduled_cents=scheduled_cents,
                                    term_code=term_code), OFFICER))


def evaluate_disbursement(disbursement_id):
    return get_success_data(
        api_client.evaluate_disbursement_eligibility(disbursement_id, OFFICER))


def post_disbursement(disbursement_id):
    return get_success_data(api_client.post_disbursement(disbursement_id, OFFICER))


def schedule_evaluate_post(line_id, scheduled_cents, term_code="2026-FALL"):
    """Schedule + evaluate + post in one call. Returns the POSTED record."""
    disb = schedule_disbursement(line_id, scheduled_cents, term_code)
    disb = evaluate_disbursement(disb["id"])
    return post_disbursement(disb["id"])


# ---------------------------------------------------------------------------
# Tier 5: over-award and reconciliation scenarios
# ---------------------------------------------------------------------------

OVERAWARD_FUND_SPECS = [
    {"fund_code": "PELL", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 739500, "pool_budget_cents": 0, "packaging_rank": 1,
     "requires_verification_complete": False},
    {"fund_code": "SUB", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 350000, "pool_budget_cents": 0, "packaging_rank": 2,
     "requires_verification_complete": False},
    {"fund_code": "INST_GRANT", "category": "INSTITUTIONAL", "need_based": True,
     "annual_cap_cents": 500000, "pool_budget_cents": 800000, "packaging_rank": 3,
     "requires_verification_complete": False},
]


def setup_overaward_case(ssn, external_aid_cents=900000):
    """PELL 739500 + SUB 350000 + INST_GRANT 500000 accepted (1_589_500 total),
    then external aid reported so total aid exceeds the 2_400_000 COA and an
    OverawardCase opens. Returns dict(aid_year, funds, student, package,
    lines_by_code, case)."""
    env = setup_notified_package(ssn=ssn, fund_specs=OVERAWARD_FUND_SPECS)
    package = accept_package_in_full(env["package"]["id"], env["student"]["id"])
    get_success_data(api_client.create_external_aid(
        create_external_aid_payload(env["student"]["id"], env["aid_year"]["id"],
                                    amount_cents=external_aid_cents), OFFICER))
    cases, _meta = validate_paginated(
        api_client.list_student_overaward_cases(env["student"]["id"], OFFICER))
    assert cases, "expected over-award detection to open a case"
    return {**env, "package": package,
            "lines_by_code": lines_by_fund(env["lines"], env["funds"]),
            "case": cases[0]}


def setup_reconciling_year(federal_reported_cents):
    """Aid year with an ACTIVE PELL fund, packaging locked (no in-flight
    packages), reconciliation begun, federal figure imported and compared.
    Returns dict(aid_year, funds, run)."""
    env = setup_open_aid_year()
    aid_year = env["aid_year"]
    get_success_data(api_client.lock_packaging(aid_year["id"], DIRECTOR))
    get_success_data(api_client.begin_reconciliation(aid_year["id"], DIRECTOR))
    runs, _meta = validate_paginated(
        api_client.list_aid_year_reconciliation_runs(aid_year["id"], DIRECTOR))
    run = runs[0]
    get_success_data(api_client.import_federal(run["id"], federal_reported_cents,
                                               DIRECTOR))
    run = get_success_data(api_client.compare_reconciliation_run(run["id"], DIRECTOR))
    return {**env, "run": run}


def setup_reconciliation_with_posted(posted_cents=100000,
                                     federal_reported_cents=99800,
                                     ssn="555667777"):
    """Full pipeline: PELL 739500 accepted + locked, line DISBURSING, one
    disbursement posted; then the year is packaging-locked, reconciliation
    begun, the federal figure imported and compared.

    The fixture student's ISIR is institutionally selected for verification, so
    the case is waived first — Title IV disbursement eligibility requires the
    case to be absent, COMPLETED_SATISFIED, or WAIVED (PRD §3.7 check 3).
    """
    env = setup_disbursing_line(ssn=ssn)
    waive_open_verification_case(env["student"]["id"])
    disb = schedule_evaluate_post(env["line"]["id"], posted_cents)
    aid_year_id = env["aid_year"]["id"]
    get_success_data(api_client.lock_packaging(aid_year_id, DIRECTOR))
    get_success_data(api_client.begin_reconciliation(aid_year_id, DIRECTOR))
    runs, _meta = validate_paginated(
        api_client.list_aid_year_reconciliation_runs(aid_year_id, DIRECTOR))
    run = runs[0]
    get_success_data(api_client.import_federal(run["id"], federal_reported_cents,
                                               DIRECTOR))
    run = get_success_data(api_client.compare_reconciliation_run(run["id"], DIRECTOR))
    return {**env, "disbursement": disb, "run": run}


# ---------------------------------------------------------------------------
# Conflicting information and professional judgment
# ---------------------------------------------------------------------------

def open_conflicting_info_case(student_id, aid_year_id, subject_field="agi_cents",
                               claimed_value_cents=None, opener="officer-alpha"):
    payload = create_conflicting_info_case_payload(
        student_id, aid_year_id, subject_field=subject_field)
    if claimed_value_cents is not None:
        payload["claimed_value_cents"] = claimed_value_cents
    return get_success_data(api_client.create_conflicting_info_case(
        payload, make_aid_officer_headers(opener)))


def create_pj_case(student_id, aid_year_id, **overrides):
    return get_success_data(api_client.create_pj_case(
        create_pj_case_payload(student_id, aid_year_id, **overrides), OFFICER))
