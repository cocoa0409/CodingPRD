"""The two standing-score variants on one review row, and the four-link
probation cascade that ends by restricting an allocation cycle.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_is_false,
    assert_is_null,
    assert_is_true,
    assert_money,
)
from test_helpers.factories import certify_payload
from test_helpers.fixtures import (
    certify_review,
    create_agency,
    create_open_cycle,
    create_submitted_request,
    file_review,
)
from test_helpers.test_users import make_admin_headers, make_finance_reviewer_headers


SELF_REPORTED = {
    "fiscal_year": 2025,
    "program_expense_ratio": "0.7800",
    "admin_expense_ratio": "0.1900",
    "months_operating_reserve": "4.00",
    "governance_checklist_passed_count": 8,
    "audit_opinion": "UNQUALIFIED",
}
AUDITED = {
    "audited_program_expense_ratio": "0.7400",
    "audited_admin_expense_ratio": "0.2700",
    "audited_months_operating_reserve": "3.00",
}


def _agency_with_pending_review():
    agency = create_agency(
        legal_name="Riverside Family Services",
        ein="123456789",
        primary_priority_area="EDUCATION",
    )
    review = file_review(agency["id"], **SELF_REPORTED)
    return agency, review


def test_preliminary_variant_reads_self_reported_ratios_and_zeroes_audit_points():
    """PRD 3.6: "Audit points are 10 for an `UNQUALIFIED` opinion, 5 for `QUALIFIED`,
    and 0 for both `ADVERSE` and `NONE` — except in the preliminary variant, which
    forces audit points to 0 no matter what `audit_opinion` says, because nothing has
    been audited yet."

    Design: Difficulty/dual_variant_calc/agency_standing_preliminary_vs_certified_score_divergence
    """
    agency, review = _agency_with_pending_review()
    admin = make_admin_headers()

    assert review["status"] == "PENDING"
    assert review["review_basis"] == "SELF_REPORTED"
    assert_money(review["preliminary_score"], "80.00", "preliminary_score")
    assert_is_null(review["certified_score"], "certified_score")
    assert_is_null(review["standards_met"], "standards_met")
    assert_is_false(review["restatement_penalty_applied"], "restatement_penalty_applied")
    assert_is_null(review["audited_program_expense_ratio"], "audited_program_expense_ratio")

    reread = validate_success(api_client.get_agency(agency["id"], admin))
    assert reread["membership_status"] == "UNDER_FINANCIAL_REVIEW"
    assert reread["open_review_count"] == 1
    assert_is_null(reread["latest_standing_score"], "latest_standing_score")


def test_certified_variant_diverges_from_the_preliminary_score_on_the_same_review():
    """PRD 3.6: "The restatement penalty is a flat 7.5 and applies only in the
    certified variant, only when the audited program expense ratio came in more than
    0.02 below the self-reported one — precisely, when
    `audited_program_expense_ratio` is strictly less than `program_expense_ratio`
    minus 0.02 — and in that case `restatement_penalty_applied` is recorded as true."

    Design: Difficulty/dual_variant_calc/agency_standing_preliminary_vs_certified_score_divergence
    """
    agency, review = _agency_with_pending_review()

    certified = validate_success(
        api_client.certify_agency_review(
            agency["id"], review["id"], certify_payload(**AUDITED),
            make_finance_reviewer_headers(),
        )
    )

    assert certified["status"] == "CERTIFIED"
    assert certified["review_basis"] == "AUDITED"
    assert_money(certified["preliminary_score"], "80.00", "preliminary_score")
    assert_money(certified["certified_score"], "69.50", "certified_score")
    assert_is_true(certified["restatement_penalty_applied"], "restatement_penalty_applied")
    assert_is_false(certified["standards_met"], "standards_met")
    assert certified["preliminary_score"] != certified["certified_score"], (
        "the two variants must disagree on the same review: 80.00 against 69.50"
    )


def test_certified_score_in_the_probation_band_moves_the_agency_to_probation():
    """PRD 3.6: "A score of at least 55.00 but below 70.00 moves it
    `UNDER_FINANCIAL_REVIEW → PROBATION` and increments `probation_count`."

    Design: Difficulty/dual_variant_calc/agency_standing_preliminary_vs_certified_score_divergence
    """
    agency, review = _agency_with_pending_review()
    admin = make_admin_headers()

    certify_review(agency["id"], review["id"], **AUDITED)

    reread = validate_success(api_client.get_agency(agency["id"], admin))
    assert reread["membership_status"] == "PROBATION"
    assert_money(reread["latest_standing_score"], "69.50", "latest_standing_score")
    assert reread["probation_count"] == 1
    assert reread["open_review_count"] == 0


def _good_standing_agency(legal_name, ein, priority_area):
    """A GOOD_STANDING agency whose fiscal 2024 review certified at 100.00."""
    agency = create_agency(
        legal_name=legal_name, ein=ein, primary_priority_area=priority_area
    )
    review = file_review(
        agency["id"],
        fiscal_year=2024,
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


def _cascade_scenario():
    """Two submitted requests on one OPEN cycle, and a second PENDING review on A."""
    agency_a = _good_standing_agency(
        "Greenline Community Center", "600000001", "EDUCATION"
    )
    agency_b = _good_standing_agency(
        "Westbrook Shelter Network", "600000002", "BASIC_NEEDS"
    )
    cycle, _ = create_open_cycle(
        3,
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="500000.00",
        max_award_per_agency="200000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-12-31",
    )
    request_a = create_submitted_request(
        cycle["id"],
        agency_a["id"],
        requested_amount="40000.00",
        priority_area="EDUCATION",
        narrative_summary="Community center program expansion.",
    )
    request_b = create_submitted_request(
        cycle["id"],
        agency_b["id"],
        requested_amount="30000.00",
        priority_area="BASIC_NEEDS",
        narrative_summary="Overnight shelter capacity.",
    )
    second_review = file_review(agency_a["id"], **SELF_REPORTED)
    return agency_a, agency_b, cycle, request_a, request_b, second_review


def test_certification_cascades_through_membership_into_the_submitted_request():
    """PRD 3.6: "Every allocation request belonging to that agency whose status is
    `SUBMITTED` or `UNDER_PANEL_REVIEW`, and whose cycle posture is `OPEN` or
    `RESTRICTED`, has its current status copied into `status_before_suspension` and
    then moves `SUBMITTED → SUSPENDED_REVIEW` or `UNDER_PANEL_REVIEW →
    SUSPENDED_REVIEW` accordingly."

    Design: Difficulty/transitive_cascade/agency_probation_cascade_four_links_to_cycle_restriction
    """
    agency_a, _, _, request_a, _, second_review = _cascade_scenario()
    admin = make_admin_headers()

    certified = validate_success(
        api_client.certify_agency_review(
            agency_a["id"], second_review["id"], certify_payload(**AUDITED),
            make_finance_reviewer_headers(),
        )
    )

    assert certified["status"] == "CERTIFIED", "link 1 certifies the review"
    assert_money(certified["certified_score"], "69.50", "certified_score")

    reread_agency = validate_success(api_client.get_agency(agency_a["id"], admin))
    assert reread_agency["membership_status"] == "PROBATION", "link 2 is caused by link 1"
    assert_money(reread_agency["latest_standing_score"], "69.50", "latest_standing_score")
    assert reread_agency["probation_count"] == 1
    assert reread_agency["open_review_count"] == 0

    reread_request = validate_success(
        api_client.get_allocation_request(request_a["id"], admin)
    )
    assert reread_request["status"] == "SUSPENDED_REVIEW", "link 3 is caused by link 2"
    assert reread_request["status_before_suspension"] == "SUBMITTED"


def test_cascade_link_four_restricts_the_cycle_and_blocks_awards():
    """PRD 3.6: "Link 4 then re-derives, on each cycle touched, the
    `suspended_request_count` and the `suspended_request_ratio`, and when that ratio
    reaches 0.34 the cycle moves `OPEN → RESTRICTED` with `awards_blocked` set to
    true."

    Design: Difficulty/transitive_cascade/agency_probation_cascade_four_links_to_cycle_restriction
    """
    agency_a, agency_b, cycle, _, request_b, second_review = _cascade_scenario()
    admin = make_admin_headers()

    before = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert before["posture"] == "OPEN"
    assert before["submitted_request_count"] == 2
    assert before["suspended_request_count"] == 0
    assert_decimal_equals(before["suspended_request_ratio"], "0.0000", "ratio before")
    assert_is_false(before["awards_blocked"], "awards_blocked before")

    certify_review(agency_a["id"], second_review["id"], **AUDITED)

    after = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert after["suspended_request_count"] == 1, "link 4 recomputes the suspension counter"
    assert_decimal_equals(after["suspended_request_ratio"], "0.5000", "suspended_request_ratio")
    assert after["posture"] == "RESTRICTED"
    assert_is_true(after["awards_blocked"], "awards_blocked")
    assert after["submitted_request_count"] == 2, "the submitted counter is unchanged"

    untouched = validate_success(api_client.get_allocation_request(request_b["id"], admin))
    assert untouched["status"] == "SUBMITTED", "agency B is untouched by the cascade"
    assert_is_null(untouched["status_before_suspension"], "status_before_suspension")
    reread_b = validate_success(api_client.get_agency(agency_b["id"], admin))
    assert reread_b["membership_status"] == "GOOD_STANDING"
