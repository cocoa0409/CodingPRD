"""Compliance report lifecycle: the RETURNED/SUBMITTED cycle, half-open period overlap
(strict vs adjacent), the certification-before-overlap ordering, and terminal lockdown."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_agreement, add_covenant, submit_report, accept_report,
    make_applicant_headers, make_analyst_headers,
)

APPLICANT = make_applicant_headers("applicant-1")
ANALYST = make_analyst_headers("analyst-1")


def _agreement_kept_active(api):
    """Active GRANT agreement carrying one INVESTMENT covenant that always stays BREACHED,
    so acceptance of a report never completes the agreement."""
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    add_covenant(agr_id, covenant_type="INVESTMENT", target_value=1_000_000_000,
                 measurement_start_date="2030-01-01T00:00:00.000Z",
                 measurement_end_date="2030-12-31T00:00:00.000Z")
    return agr_id


def test_report_return_advances_to_returned(api):
    """PRD §3.5: "Returning it for correction advances `SUBMITTED → RETURNED` with an optional
    `reason`; the owning applicant may then resubmit, advancing `RETURNED → SUBMITTED` and
    optionally revising `actual_jobs`, `actual_investment_cents`, and `attestation`."

    Design: Difficulty/non_linear_state_machine/compliance_report_return_resubmit_cycle
    """
    agr_id = _agreement_kept_active(api)
    rep = submit_report(agr_id, actual_jobs=80, attestation=True)
    data = validate_success(api.return_report(rep["id"], ANALYST, {"reason": "restate jobs"}))
    assert data["status"] == "RETURNED"


def test_report_resubmit_returns_to_submitted(api):
    """PRD §3.5: "Returning it for correction advances `SUBMITTED → RETURNED` with an optional
    `reason`; the owning applicant may then resubmit, advancing `RETURNED → SUBMITTED` and
    optionally revising `actual_jobs`, `actual_investment_cents`, and `attestation`."

    Design: Difficulty/non_linear_state_machine/compliance_report_return_resubmit_cycle
    """
    agr_id = _agreement_kept_active(api)
    rep = submit_report(agr_id, actual_jobs=80, attestation=True)
    validate_success(api.return_report(rep["id"], ANALYST, {"reason": "restate jobs"}))
    data = validate_success(api.resubmit_report(rep["id"], APPLICANT, {"actual_jobs": 100, "attestation": True}))
    assert data["status"] == "SUBMITTED"


def test_reporting_period_strict_overlap_rejected(api):
    """PRD §3.5: "the report's half-open period must not overlap the period of any
    already-`ACCEPTED` report on the same agreement, otherwise it fails with
    `ERR_REPORTING_PERIOD_OVERLAP` (HTTP 409)." R2 [2027-06-01,2028-06-01) overlaps the
    accepted R1 [2027-01-01,2028-01-01).

    Design: Difficulty/resource_temporal_overlap/reporting_period_overlap_half_open_intervals
    """
    agr_id = _agreement_kept_active(api)
    r1 = submit_report(agr_id, reporting_year=2027,
                       period_start_date="2027-01-01T00:00:00.000Z",
                       period_end_date="2028-01-01T00:00:00.000Z",
                       actual_jobs=80, attestation=True)
    accept_report(r1["id"])
    r2 = submit_report(agr_id, reporting_year=2028,
                       period_start_date="2027-06-01T00:00:00.000Z",
                       period_end_date="2028-06-01T00:00:00.000Z",
                       actual_jobs=90, attestation=True)
    validate_error(api.accept_report(r2["id"], ANALYST), ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP)


def test_reporting_period_adjacent_half_open_allowed(api):
    """PRD §3.5: "a half-open reporting period bounded by `period_start_date` and an exclusive
    `period_end_date` (which must be strictly after the start)". A period starting exactly at
    the prior period's exclusive end does not overlap and is accepted.

    Design: Difficulty/resource_temporal_overlap/reporting_period_overlap_half_open_intervals
    """
    agr_id = _agreement_kept_active(api)
    r1 = submit_report(agr_id, reporting_year=2027,
                       period_start_date="2027-01-01T00:00:00.000Z",
                       period_end_date="2028-01-01T00:00:00.000Z",
                       actual_jobs=80, attestation=True)
    accept_report(r1["id"])
    r2 = submit_report(agr_id, reporting_year=2028,
                       period_start_date="2028-01-01T00:00:00.000Z",
                       period_end_date="2029-01-01T00:00:00.000Z",
                       actual_jobs=90, attestation=True)
    data = validate_success(api.accept_report(r2["id"], ANALYST))
    assert data["status"] == "ACCEPTED"


def test_accept_uncertified_overlapping_report_reports_certification_first(api):
    """PRD §3.5: "the report's `attestation` must be true, otherwise acceptance fails with
    `ERR_REPORT_NOT_CERTIFIED` (HTTP 422)".
    PRD §2.10: "then remaining domain constraints, then interval-overlap checks, and finally
    fiscal-capacity checks." The uncertified R2 also overlaps R1, but certification is
    checked before overlap so ERR_REPORT_NOT_CERTIFIED wins.

    Design: Difficulty/priority_pair_validation_conflict/certification_vs_overlap_on_accept
    """
    agr_id = _agreement_kept_active(api)
    r1 = submit_report(agr_id, reporting_year=2027,
                       period_start_date="2027-01-01T00:00:00.000Z",
                       period_end_date="2028-01-01T00:00:00.000Z",
                       actual_jobs=80, attestation=True)
    accept_report(r1["id"])
    r2 = submit_report(agr_id, reporting_year=2028,
                       period_start_date="2027-06-01T00:00:00.000Z",
                       period_end_date="2028-06-01T00:00:00.000Z",
                       actual_jobs=90, attestation=False)
    validate_error(api.accept_report(r2["id"], ANALYST), ApiErrorId.ERR_REPORT_NOT_CERTIFIED)


def test_accept_uncertified_report_rejected(api):
    """PRD §3.5: "the report's `attestation` must be true, otherwise acceptance fails with
    `ERR_REPORT_NOT_CERTIFIED` (HTTP 422)". Isolated: a single uncertified report, no overlap.

    Design: Difficulty/priority_pair_validation_conflict/certification_vs_overlap_on_accept
    """
    agr_id = _agreement_kept_active(api)
    rep = submit_report(agr_id, actual_jobs=80, attestation=False)
    validate_error(api.accept_report(rep["id"], ANALYST), ApiErrorId.ERR_REPORT_NOT_CERTIFIED)


def test_accept_already_accepted_report_returns_invalid_state(api):
    """PRD §3.5: "Dispositioning a report from an illegal state yields
    `ERR_COMPLIANCE_REPORT_INVALID_STATE`. `ACCEPTED` is terminal; a returned report cycles
    back through `SUBMITTED` for another disposition."

    Design: Corner/state_machines/accept_already_accepted_report_returns_invalid_state
    """
    agr_id = _agreement_kept_active(api)
    rep = submit_report(agr_id, actual_jobs=80, attestation=True)
    accept_report(rep["id"])
    validate_error(api.accept_report(rep["id"], ANALYST), ApiErrorId.ERR_COMPLIANCE_REPORT_INVALID_STATE)
