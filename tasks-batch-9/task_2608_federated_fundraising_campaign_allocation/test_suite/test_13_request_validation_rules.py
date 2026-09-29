"""Request-shape and cross-entity validation rules: the inclusive designation
floor, the aggregate gross ceiling, the payroll-availability gate, the two
distinct empty-and-sub-quorum review failures, and the header ladder that runs
before anything is looked up at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_DESIGNATION_EXCEEDS_GROSS,
    ERR_NO_ELIGIBLE_SCORES,
    ERR_PANEL_QUORUM_NOT_MET,
    ERR_PAYROLL_METHOD_UNAVAILABLE,
    ERR_ROLE_NOT_PERMITTED,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_common_fields, assert_is_null, assert_money
from test_helpers.factories import agency_payload, designation_line, pledge_payload
from test_helpers.fixtures import (
    create_active_employer,
    create_good_standing_agency,
    create_open_campaign,
    create_open_cycle,
    create_submitted_request,
    file_score,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_allocations_director_headers,
    make_panelist_headers,
)


UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": "op-grants-officer",
    "X-User-Role": "GrantsOfficer",
    "Content-Type": "application/json",
}
ROLELESS_HEADERS = {
    "X-User-ID": "op-united-fund-admin",
    "Content-Type": "application/json",
}
PANELIST_WITHOUT_A_SEAT = "00000000-0000-4000-8000-000000000abc"


def test_a_designation_line_at_exactly_the_minimum_is_accepted():
    """PRD 3.3: "Every `designated_amount` must be at least 25.00, the minimum
    designation the organization will process, and a smaller line is refused with
    `ERR_DESIGNATION_BELOW_MINIMUM`."

    "At least 25.00" is an inclusive floor, so the line at exactly 25.00 is stored
    and priced rather than refused.

    Design: Corner/validations/designation_at_exact_minimum_amount_of_twenty_five_passes
    """
    admin = make_admin_headers()
    agency = create_good_standing_agency(
        legal_name="Cedar Ridge Youth Corps",
        ein="610000007",
        primary_priority_area="EDUCATION",
    )
    employer = create_active_employer(legal_name="Ironwood Millworks", employee_count=95)
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )

    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="M-001",
                giving_method="ONE_TIME_CHECK",
                gross_amount="60.00",
                designations=[designation_line(agency["id"], "25.00")],
            ),
            admin,
        ),
        201,
    )

    assert_money(pledge["designated_amount_total"], "25.00", "designated_amount_total")
    assert_money(pledge["designation_fee_total"], "1.81", "designation_fee_total")
    assert_money(pledge["net_designated_total"], "23.19", "net_designated_total")
    assert_money(pledge["undesignated_amount"], "35.00", "undesignated_amount")
    assert pledge["designation_status"] == "DRAFT"

    lines, meta = validate_paginated(
        api_client.list_pledge_designations(pledge["id"], admin)
    )
    assert meta["total_count"] == 1, "the line at the floor was stored, not dropped"
    assert_money(lines[0]["designated_amount"], "25.00", "line designated_amount")
    assert_money(lines[0]["processing_fee"], "1.81", "line processing_fee")


def test_two_individually_valid_lines_may_still_overshoot_the_pledge_gross():
    """PRD 3.3: "And the designated amounts must not sum to more than the pledge's
    `gross_amount`; an excess is refused with `ERR_DESIGNATION_EXCEEDS_GROSS`, while any
    shortfall is not an error at all — it is the donor's undesignated contribution."

    Each of the 60.00 and 50.00 lines clears the per-line floor on its own, so only the
    aggregate rule can reject this body; accepting it would mint a negative
    `undesignated_amount`.

    Design: Corner/validations/designation_lines_each_valid_but_sum_exceeds_pledge_gross_returns_exceeds_gross
    """
    admin = make_admin_headers()
    agency = create_good_standing_agency(
        legal_name="Northgate Family Shelter",
        ein="610000008",
        primary_priority_area="BASIC_NEEDS",
    )
    employer = create_active_employer(legal_name="Sable Point Insurance", employee_count=340)
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )

    refused = api_client.create_pledge(
        campaign["id"],
        pledge_payload(
            donor_reference="A-001",
            giving_method="ONE_TIME_CHECK",
            gross_amount="100.00",
            designations=[
                designation_line(agency["id"], "60.00"),
                designation_line(agency["id"], "50.00"),
            ],
        ),
        admin,
    )
    validate_error(refused, ERR_DESIGNATION_EXCEEDS_GROSS, 422)

    _, meta = validate_paginated(
        api_client.list_pledges(admin, {"campaign_id": campaign["id"]})
    )
    assert meta["total_count"] == 0, "the refused pledge was never created"

    reread_campaign = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert_money(reread_campaign["confirmed_gross_total"], "0.00", "confirmed_gross_total")
    assert_money(
        reread_campaign["designated_gross_total"], "0.00", "designated_gross_total"
    )


def test_payroll_deduction_is_refused_only_where_no_payroll_runs():
    """PRD 3.3: "Payroll deduction is only available where payroll exists. A pledge whose
    `giving_method` is `PAYROLL_DEDUCTION` recorded at an employer whose
    `payroll_periods_per_year` is 0 is refused with `ERR_PAYROLL_METHOD_UNAVAILABLE`."

    The refusal is a property of the employer, not of the body: the same employer takes a
    cheque for the same money, and the employer that kept the default 26 periods takes the
    identical payroll body.

    Design: Corner/validations/payroll_deduction_pledge_on_employer_with_zero_payroll_periods_returns_method_unavailable
    """
    admin = make_admin_headers()
    without_payroll = create_active_employer(
        legal_name="Quarry Bend Cooperative",
        employee_count=40,
        payroll_periods_per_year=0,
    )
    _, campaign_without = create_open_campaign(
        without_payroll["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    with_payroll = create_active_employer(
        legal_name="Lakeshore Dental Group", employee_count=40
    )
    _, campaign_with = create_open_campaign(
        with_payroll["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )

    refused = api_client.create_pledge(
        campaign_without["id"],
        pledge_payload(
            donor_reference="P-001",
            giving_method="PAYROLL_DEDUCTION",
            gross_amount="240.00",
        ),
        admin,
    )
    validate_error(refused, ERR_PAYROLL_METHOD_UNAVAILABLE, 422)

    by_cheque = validate_success(
        api_client.create_pledge(
            campaign_without["id"],
            pledge_payload(
                donor_reference="P-001",
                giving_method="ONE_TIME_CHECK",
                gross_amount="240.00",
            ),
            admin,
        ),
        201,
    )
    assert by_cheque["giving_method"] == "ONE_TIME_CHECK", (
        "the same employer accepts the same money by another method"
    )

    by_payroll = validate_success(
        api_client.create_pledge(
            campaign_with["id"],
            pledge_payload(
                donor_reference="P-001",
                giving_method="PAYROLL_DEDUCTION",
                gross_amount="240.00",
            ),
            admin,
        ),
        201,
    )
    assert by_payroll["giving_method"] == "PAYROLL_DEDUCTION"
    assert by_payroll["donor_reference"] == "P-001", (
        "donor_reference uniqueness is scoped to one campaign"
    )

    assert validate_success(api_client.get_employer(without_payroll["id"], admin))[
        "payroll_periods_per_year"
    ] == 0
    assert validate_success(api_client.get_employer(with_payroll["id"], admin))[
        "payroll_periods_per_year"
    ] == 26


def test_an_empty_score_set_and_a_sub_quorum_one_fail_for_different_reasons():
    """PRD 3.7: "An entirely empty pool is its own failure mode, refused with
    `ERR_NO_ELIGIBLE_SCORES`; this is exactly what a still-`SUBMITTED` request produces,
    which is why such a request is admitted by the status gate and then rejected here."

    PRD 3.7: "A non-empty pool of one or two scores fails quorum and is refused with
    `ERR_PANEL_QUORUM_NOT_MET`, because the panel quorum is three."

    Design: Corner/validations/finalize_review_empty_then_sub_quorum_eligible_set_errors_in_priority_order
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    agency = create_good_standing_agency(
        legal_name="Willow Creek Counseling",
        ein="610000009",
        primary_priority_area="HEALTH",
    )
    cycle, panelists = create_open_cycle(
        3,
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="200000.00",
        max_award_per_agency="50000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="30000.00",
        priority_area="HEALTH",
        narrative_summary="Sliding-scale behavioral health intake.",
    )
    assert request["status"] == "SUBMITTED"
    assert request["eligible_score_count"] == 0

    on_empty = api_client.finalize_review(request["id"], director)
    validate_error(on_empty, ERR_NO_ELIGIBLE_SCORES, 422)

    still_submitted = validate_success(
        api_client.get_allocation_request(request["id"], admin)
    )
    assert still_submitted["status"] == "SUBMITTED", "a refused finalization moves nothing"

    file_score(
        request["id"],
        panelists[0]["id"],
        priority_alignment_score=80,
        outcome_evidence_score=80,
        capacity_score=80,
    )
    file_score(
        request["id"],
        panelists[1]["id"],
        priority_alignment_score=70,
        outcome_evidence_score=70,
        capacity_score=70,
    )

    on_sub_quorum = api_client.finalize_review(request["id"], director)
    validate_error(on_sub_quorum, ERR_PANEL_QUORUM_NOT_MET, 422)

    after = validate_success(api_client.get_allocation_request(request["id"], admin))
    assert after["status"] == "UNDER_PANEL_REVIEW", (
        "two filed scores moved the request under review and neither refusal moved it back"
    )
    assert after["eligible_score_count"] == 2
    assert_is_null(after["composite_score"], "composite_score")

    _, meta = validate_paginated(api_client.list_request_scores(request["id"], admin))
    assert meta["total_count"] == 2, "both refusals left the two score rows in place"


def test_the_header_ladder_separates_authentication_from_permission():
    """PRD 2.1: "A request whose `X-User-Role` is absent or is not one of those six
    strings is rejected with `ERR_UNAUTHENTICATED` (401), as is a request that omits
    `X-User-ID` for any role whose identity is backed by a persisted entity."

    PRD 2.1: "Once the caller is authenticated, the role is checked against the set of
    roles the target operation permits; a role outside that set is rejected with
    `ERR_ROLE_NOT_PERMITTED` (403)."

    All three refusals carry the same body, and the globally unique `ein` in that body is
    still available afterwards, which shows none of them reached the data store.

    Design: Corner/validations/request_without_x_user_role_header_returns_unauthenticated
    """
    admin = make_admin_headers()
    body = agency_payload(
        legal_name="Header Test Agency",
        ein="610000010",
        primary_priority_area="HEALTH",
    )

    validate_error(api_client.create_agency(body, ROLELESS_HEADERS), ERR_UNAUTHENTICATED, 401)
    validate_error(
        api_client.create_agency(body, UNKNOWN_ROLE_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api_client.create_agency(body, make_panelist_headers(PANELIST_WITHOUT_A_SEAT)),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    admitted = validate_success(api_client.create_agency(body, admin), 201)

    assert admitted["ein"] == "610000010", (
        "no refused call consumed the globally unique ein"
    )
    assert admitted["legal_name"] == "Header Test Agency"
    assert admitted["membership_status"] == "APPLICANT"
    assert_common_fields(admitted, "agency")
