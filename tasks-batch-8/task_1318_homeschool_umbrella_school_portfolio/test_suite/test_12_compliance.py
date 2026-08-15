"""Compliance sweep standing recompute/recovery and state reporting."""
from test_helpers import (
    ApiErrorId,
    assert_compliance_report,
    create_open_year,
    create_year_with_registered_enrollment,
    create_notice_payload,
    get_success_data,
    set_clock,
    setup_registered_enrollment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]

YEAR_A = dict(
    label="2026-2027", start_date="2026-08-01", end_date="2027-05-31",
    notice_filing_deadline="2026-09-15T00:00:00Z",
    portfolio_due_date="2027-04-30T00:00:00Z",
    state_report_due_date="2027-06-15T00:00:00Z", mid_year_date="2027-01-15",
)
YEAR_B = dict(
    label="2027-2028", start_date="2027-08-01", end_date="2028-05-31",
    notice_filing_deadline="2027-09-15T00:00:00Z",
    portfolio_due_date="2028-04-30T00:00:00Z",
    state_report_due_date="2028-06-15T00:00:00Z", mid_year_date="2028-01-15",
)


def test_standing_sweep_violation_then_recovery(api):
    """PRD §3.9: "**Hard violations**: the `notice_filing_deadline` has passed
    and no notice of the enrollment stands `ACKNOWLEDGED`; the year's `end_date`
    has passed and the enrollment's `testing_required` is true while
    `testing_satisfied` remains false; the year's `end_date` has passed and
    either `certified_days_counted` falls short of `required_instructional_days`
    or `certified_minutes_credited` falls short of the applicable minute floor —
    `required_minutes_elementary` for grades K–5,
    `required_minutes_secondary` for grades 6–12; or a portfolio of the
    enrollment stands `REJECTED`."
    PRD §3.9: "Any hard violation drives the enrollment to `NONCOMPLIANT`;
    otherwise any soft violation yields `PROBATION`; otherwise the enrollment
    rests at `GOOD_STANDING` — including enrollments recovering from
    `NONCOMPLIANT` once their hard violations clear but soft ones remain, or
    returning all the way to good standing."
    PRD §3.9: "an absolute recompute from current data, so recovery is as
    possible as demotion"

    Design: Corner/state_machines/standing_sweep_violation_then_recovery
    """
    # Build the year and a REGISTERED enrollment whose notice stays DRAFT.
    year = create_open_year(**YEAR_A)
    ctx = setup_registered_enrollment(year["id"], 4, family_name="Fam Sw",
                                      district_code="D-41", date_of_birth="2016-09-09")
    notice = get_success_data(
        api.create_notice(ctx["enrollment"]["id"], create_notice_payload(district_code="D-41"),
                          ctx["parent_headers"])
    )
    set_clock("2026-09-16T00:00:00Z")  # past the 2026-09-15 NOI deadline

    get_success_data(api.run_compliance_sweep(year["id"], DIRECTOR))
    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["compliance_standing"] == "NONCOMPLIANT", (
        "deadline passed with no ACKNOWLEDGED notice"
    )

    # Clear the hard violation: file and acknowledge the notice, then re-sweep.
    get_success_data(api.file_notice(notice["id"], ctx["parent_headers"]))
    get_success_data(api.acknowledge_notice(notice["id"], REGISTRAR))
    get_success_data(api.run_compliance_sweep(year["id"], DIRECTOR))
    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["compliance_standing"] == "GOOD_STANDING", (
        "hard violation cleared; 2026-09-16 precedes the portfolio and mid-year "
        "soft-violation dates"
    )


def test_report_late_flag_boundary(api):
    """PRD §3.9: "Submission, a director action, moves `DRAFT` → `SUBMITTED` —
    or, after a state rejection, `REJECTED` → `SUBMITTED` — stamping
    `submitted_at` and computing the `late` flag: submission after the year's
    `state_report_due_date` is late, while submission exactly at that instant is
    not."
    PRD §3.9: "Once the year stands `CLOSED` — generation against a year in any
    other state fails with `ERR_REPORT_YEAR_NOT_CLOSED` — the director generates
    the year's compliance report, of which at most one may be open at a time: an
    existing report in `DRAFT`, `SUBMITTED`, or `REJECTED` blocks generation
    with `ERR_REPORT_ALREADY_OPEN`."
    PRD §3.9: "Generation snapshots the year at the `generated_at` instant:
    `total_enrollments` counts the year's enrollments not `WITHDRAWN` at that
    moment, `compliant_count` those among them in `GOOD_STANDING`, and
    `noncompliant_enrollment_ids` lists the identifiers of the rest, ordered by
    each enrollment's creation time, earliest first — never by identifier."

    Design: Corner/calculations/report_late_flag_boundary
    """
    year_a, family, student, _enr_a = create_year_with_registered_enrollment(
        **YEAR_A, grade_level=4, family_name="Fam R", district_code="D-49",
    )
    year_b, _f, _s, _enr_b = create_year_with_registered_enrollment(
        **YEAR_B, grade_level=5, family=family, student=student,
    )

    # Generation while year A is still OPEN is refused.
    resp0 = api.create_compliance_report(year_a["id"], DIRECTOR)
    validate_error(resp0, ApiErrorId.ERR_REPORT_YEAR_NOT_CLOSED)

    # Close year A at exactly the report due instant and generate the report.
    set_clock("2027-06-15T00:00:00Z")
    get_success_data(api.close_academic_year(year_a["id"], DIRECTOR))
    rep_a = validate_success(api.create_compliance_report(year_a["id"], DIRECTOR), 201)
    assert_compliance_report(rep_a)
    assert rep_a["status"] == "DRAFT"
    assert rep_a["total_enrollments"] == 1
    assert rep_a["compliant_count"] == 1
    assert rep_a["noncompliant_enrollment_ids"] == []

    # One open report per year.
    resp1 = api.create_compliance_report(year_a["id"], DIRECTOR)
    validate_error(resp1, ApiErrorId.ERR_REPORT_ALREADY_OPEN)

    # Submitted at exactly the due instant: not late (strict > semantics).
    submitted_a = validate_success(api.submit_compliance_report(rep_a["id"], DIRECTOR))
    assert submitted_a["late"] is False

    # Year B: submitted one day past its due date.
    set_clock("2028-06-16T00:00:00Z")
    get_success_data(api.close_academic_year(year_b["id"], DIRECTOR))
    rep_b = validate_success(api.create_compliance_report(year_b["id"], DIRECTOR), 201)
    submitted_b = validate_success(api.submit_compliance_report(rep_b["id"], DIRECTOR))
    assert submitted_b["late"] is True
