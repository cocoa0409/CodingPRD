"""Two calls that each break two rules at once, and the ladder that decides which
refusal the caller actually sees.

Both pairs sit inside the same HTTP status, so the status code cannot
disambiguate them; only the declared order of evaluation can. Each pair is
accompanied by isolation legs proving that the losing rule is live on its own.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_AGENCY_NOT_IN_GOOD_STANDING,
    ERR_DESIGNATION_BELOW_MINIMUM,
    ERR_DESIGNATION_TARGET_INELIGIBLE,
    ERR_REQUEST_WINDOW_CLOSED,
)
from test_helpers.assertions import assert_is_null, assert_money
from test_helpers.factories import (
    certify_payload,
    designation_line,
    pledge_payload,
)
from test_helpers.fixtures import (
    certify_review,
    create_active_employer,
    create_agency,
    create_open_campaign,
    create_open_cycle,
    create_request,
    file_review,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_agency_rep_headers,
    make_finance_reviewer_headers,
)


PROBATION_AUDIT = {
    "audited_program_expense_ratio": "0.7400",
    "audited_admin_expense_ratio": "0.2700",
    "audited_months_operating_reserve": "3.00",
}


def _agency_certified_at_one_hundred(legal_name, ein, priority_area):
    """An agency whose certified review scores 100.00, so it is GOOD_STANDING."""
    agency = create_agency(
        legal_name=legal_name, ein=ein, primary_priority_area=priority_area
    )
    review = file_review(
        agency["id"],
        fiscal_year=2025,
        program_expense_ratio="0.9000",
        admin_expense_ratio="0.1000",
        months_operating_reserve="6.00",
        governance_checklist_passed_count=10,
        audit_opinion="UNQUALIFIED",
    )
    certify_review(
        agency["id"],
        review["id"],
        audited_program_expense_ratio="0.9000",
        audited_admin_expense_ratio="0.1000",
        audited_months_operating_reserve="6.00",
    )
    return validate_success(api_client.get_agency(agency["id"], make_admin_headers()))


def _designation_pair_scenario():
    """An OPEN campaign, an untouched APPLICANT agency and a GOOD_STANDING one."""
    employer = create_active_employer(
        legal_name="Pinehurst Insurance Group",
        employee_count=640,
        payroll_periods_per_year=24,
        historical_shrinkage_rate_bps=700,
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    applicant = create_agency(
        legal_name="Riverbend Arts Collective",
        ein="800000001",
        primary_priority_area="FINANCIAL_STABILITY",
    )
    eligible = _agency_certified_at_one_hundred(
        "Fairview Senior Services", "800000002", "BASIC_NEEDS"
    )
    assert applicant["membership_status"] == "APPLICANT", (
        "no review was ever filed for this agency"
    )
    assert eligible["membership_status"] == "GOOD_STANDING"
    return campaign, applicant, eligible


def _record_pledge(campaign_id, agency_id, designated_amount, donor_reference):
    return api_client.create_pledge(
        campaign_id,
        pledge_payload(
            donor_reference=donor_reference,
            giving_method="PAYROLL_DEDUCTION",
            gross_amount="500.00",
            designations=[designation_line(agency_id, designated_amount)],
        ),
        make_admin_headers(),
    )


def _read_campaign(campaign_id):
    return validate_success(api_client.get_campaign(campaign_id, make_admin_headers()))


def test_an_ineligible_designation_target_outranks_a_below_minimum_amount():
    """PRD 2.10: "Checks are evaluated in a fixed ladder, ascending, and the first
    failure is the response."

    One 10.00 line aimed at an `APPLICANT` agency breaks the eligibility gate and the
    minimum-amount gate at once, and both answer 422.

    Design: Difficulty/priority_pair_validation_conflict/ineligible_designation_target_outranks_below_minimum_amount
    """
    campaign, applicant, _ = _designation_pair_scenario()

    validate_error(
        _record_pledge(campaign["id"], applicant["id"], "10.00", "D-PAIR-1"),
        ERR_DESIGNATION_TARGET_INELIGIBLE,
        422,
    )

    reread = _read_campaign(campaign["id"])
    assert_money(reread["confirmed_gross_total"], "0.00", "confirmed_gross_total")
    assert_money(reread["designated_gross_total"], "0.00", "designated_gross_total")
    assert_money(reread["designation_fee_total"], "0.00", "designation_fee_total")


def test_the_per_line_minimum_fires_on_its_own_for_an_eligible_target():
    """PRD 3.3: "Every `designated_amount` must be at least 25.00, the minimum
    designation the organization will process, and a smaller line is refused with
    `ERR_DESIGNATION_BELOW_MINIMUM`."

    Design: Difficulty/priority_pair_validation_conflict/ineligible_designation_target_outranks_below_minimum_amount
    """
    campaign, _, eligible = _designation_pair_scenario()

    validate_error(
        _record_pledge(campaign["id"], eligible["id"], "10.00", "D-PAIR-2"),
        ERR_DESIGNATION_BELOW_MINIMUM,
        422,
    )

    reread = _read_campaign(campaign["id"])
    assert_money(reread["designated_gross_total"], "0.00", "designated_gross_total")


def test_the_eligibility_gate_fires_on_its_own_for_an_ample_amount():
    """PRD 3.3: "Every `agency_id` must resolve to an agency whose membership standing is
    either `GOOD_STANDING` or `PROBATION`; agencies that are `APPLICANT`,
    `UNDER_FINANCIAL_REVIEW` or `SUSPENDED_MEMBERSHIP` may not receive donor
    designations, and targeting one is refused with `ERR_DESIGNATION_TARGET_INELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/ineligible_designation_target_outranks_below_minimum_amount
    """
    campaign, applicant, _ = _designation_pair_scenario()

    validate_error(
        _record_pledge(campaign["id"], applicant["id"], "100.00", "D-PAIR-3"),
        ERR_DESIGNATION_TARGET_INELIGIBLE,
        422,
    )

    reread = _read_campaign(campaign["id"])
    assert_money(reread["designated_gross_total"], "0.00", "designated_gross_total")


def test_the_same_call_with_neither_violation_is_recorded():
    """PRD 3.3: "For each line, the raw fee is that line's `designated_amount` multiplied
    by the donor-designation processing rate of 7.25 percent; the line's
    `processing_fee` is that raw fee rounded half up to two decimal places, or 1.50 —
    the floor the organization charges to touch any designation at all — whichever is
    larger."

    Design: Difficulty/priority_pair_validation_conflict/ineligible_designation_target_outranks_below_minimum_amount
    """
    campaign, _, eligible = _designation_pair_scenario()

    pledge = validate_success(
        _record_pledge(campaign["id"], eligible["id"], "100.00", "D-PAIR-4"), 201
    )

    assert_money(pledge["designated_amount_total"], "100.00", "designated_amount_total")
    assert_money(pledge["designation_fee_total"], "7.25", "designation_fee_total")
    assert_money(pledge["net_designated_total"], "92.75", "net_designated_total")
    assert_money(pledge["undesignated_amount"], "400.00", "undesignated_amount")
    assert pledge["designation_status"] == "DRAFT"


def _submit_pair_scenario():
    """Four DRAFT requests across two cycles, then one agency dropped to probation.

    Every request is drafted before the review is certified, so all four exist and
    differ only in which agency owns them and which cycle they compete in.
    """
    probation = create_agency(
        legal_name="Clearwater Family Support",
        ein="900000001",
        primary_priority_area="BASIC_NEEDS",
    )
    good = _agency_certified_at_one_hundred(
        "Maplewood Health Clinic", "900000002", "HEALTH"
    )
    closed_cycle, _ = create_open_cycle(
        1,
        focus_priority_area="BASIC_NEEDS",
        opening_undesignated_pool="400000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-07-20",
    )
    open_cycle, _ = create_open_cycle(
        1,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="400000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-12-31",
    )
    requests = {
        ("probation", "closed"): create_request(
            closed_cycle["id"],
            probation["id"],
            requested_amount="40000.00",
            priority_area="BASIC_NEEDS",
            narrative_summary="Family support case management.",
        ),
        ("good", "closed"): create_request(
            closed_cycle["id"],
            good["id"],
            requested_amount="40000.00",
            priority_area="HEALTH",
            narrative_summary="Clinic evening hours.",
        ),
        ("probation", "open"): create_request(
            open_cycle["id"],
            probation["id"],
            requested_amount="40000.00",
            priority_area="BASIC_NEEDS",
            narrative_summary="Family support case management, second cycle.",
        ),
        ("good", "open"): create_request(
            open_cycle["id"],
            good["id"],
            requested_amount="40000.00",
            priority_area="HEALTH",
            narrative_summary="Clinic evening hours, second cycle.",
        ),
    }
    review = file_review(probation["id"])
    validate_success(
        api_client.certify_agency_review(
            probation["id"],
            review["id"],
            certify_payload(**PROBATION_AUDIT),
            make_finance_reviewer_headers(),
        )
    )
    return probation, good, closed_cycle, open_cycle, requests


def _submit(request_id, agency_id):
    return api_client.submit_allocation_request(
        request_id, make_agency_rep_headers(agency_id)
    )


def _read_request(request_id):
    return validate_success(
        api_client.get_allocation_request(request_id, make_admin_headers())
    )


def _read_cycle(cycle_id):
    return validate_success(
        api_client.get_allocation_cycle(cycle_id, make_admin_headers())
    )


def test_the_standing_gate_outranks_the_closed_request_window():
    """PRD 2.10: "Checks are evaluated in a fixed ladder, ascending, and the first
    failure is the response."

    The submitting agency sits on probation and the clock has left the cycle's
    request window, so two 422 gates fire on the same call.

    Design: Difficulty/priority_pair_validation_conflict/agency_standing_outranks_closed_request_window
    """
    probation, _, closed_cycle, _, requests = _submit_pair_scenario()

    reread_agency = validate_success(
        api_client.get_agency(probation["id"], make_admin_headers())
    )
    assert reread_agency["membership_status"] == "PROBATION"
    assert_money(reread_agency["latest_standing_score"], "69.50", "latest_standing_score")

    request = requests[("probation", "closed")]
    validate_error(
        _submit(request["id"], probation["id"]), ERR_AGENCY_NOT_IN_GOOD_STANDING, 422
    )

    unchanged = _read_request(request["id"])
    assert unchanged["status"] == "DRAFT"
    assert_is_null(unchanged["submitted_at"], "submitted_at")
    assert _read_cycle(closed_cycle["id"])["submitted_request_count"] == 0


def test_the_request_window_gate_fires_alone_for_an_agency_in_good_standing():
    """PRD 3.7: "The logical clock's date must fall inside the cycle's half-open request
    window, at or after `request_window_start` and strictly before
    `request_window_end`, or the submission is refused with
    `ERR_REQUEST_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/agency_standing_outranks_closed_request_window
    """
    _, good, closed_cycle, _, requests = _submit_pair_scenario()

    request = requests[("good", "closed")]
    validate_error(_submit(request["id"], good["id"]), ERR_REQUEST_WINDOW_CLOSED, 422)

    unchanged = _read_request(request["id"])
    assert unchanged["status"] == "DRAFT"
    assert_is_null(unchanged["submitted_at"], "submitted_at")
    assert _read_cycle(closed_cycle["id"])["submitted_request_count"] == 0


def test_the_standing_gate_fires_alone_inside_an_open_request_window():
    """PRD 3.7: "The agency must be in `GOOD_STANDING` at that moment — an `APPLICANT`, an
    agency mid-re-review at `UNDER_FINANCIAL_REVIEW`, one on `PROBATION` and one at
    `SUSPENDED_MEMBERSHIP` are all refused with `ERR_AGENCY_NOT_IN_GOOD_STANDING`."

    Design: Difficulty/priority_pair_validation_conflict/agency_standing_outranks_closed_request_window
    """
    probation, _, _, open_cycle, requests = _submit_pair_scenario()

    request = requests[("probation", "open")]
    validate_error(
        _submit(request["id"], probation["id"]), ERR_AGENCY_NOT_IN_GOOD_STANDING, 422
    )

    unchanged = _read_request(request["id"])
    assert unchanged["status"] == "DRAFT"
    assert_is_null(unchanged["submitted_at"], "submitted_at")
    assert _read_cycle(open_cycle["id"])["submitted_request_count"] == 0


def test_a_good_standing_agency_inside_the_window_is_admitted():
    """PRD 3.7: "On success, `submitted_at` is stamped from the logical clock and the
    cycle's `submitted_request_count` and `suspended_request_ratio` are re-derived."

    Design: Difficulty/priority_pair_validation_conflict/agency_standing_outranks_closed_request_window
    """
    _, good, _, open_cycle, requests = _submit_pair_scenario()

    request = requests[("good", "open")]
    submitted = validate_success(_submit(request["id"], good["id"]))

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] is not None, "submitted_at is stamped on success"
    assert submitted["submitted_at"].startswith("2026-08-01"), (
        "the logical clock sits at its 2026-08-01T00:00:00Z default"
    )
    assert _read_cycle(open_cycle["id"])["submitted_request_count"] == 1
