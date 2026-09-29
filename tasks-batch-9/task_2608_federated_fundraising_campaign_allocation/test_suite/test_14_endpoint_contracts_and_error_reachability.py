"""Endpoint contracts — the create/read round trip, the action endpoint, the
junction endpoint and the computed read — and the reachability of the declared
error catalogue: every 404, the campaign and pledge gates, the cycle and panel
gates, nested path integrity, the pool guard, the reporting gates and the
cross-cycle delinquency bar.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_AGENCY_NOT_FOUND,
    ERR_AGENCY_REVIEW_NOT_FOUND,
    ERR_AWARD_EXCEEDS_AGENCY_CAP,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CAMPAIGN_NOT_FULLY_REMITTED,
    ERR_CAMPAIGN_NOT_OPEN,
    ERR_COLLECTION_EXCEEDS_OUTSTANDING,
    ERR_CYCLE_NOT_FOUND,
    ERR_CYCLE_NOT_OPEN,
    ERR_DUPLICATE_DONOR_REFERENCE,
    ERR_DUPLICATE_PANEL_SCORE,
    ERR_DUPLICATE_REQUEST_FOR_CYCLE,
    ERR_EMPLOYER_INVALID_STATE,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_OUTCOME_REPORT_DELINQUENT,
    ERR_OUTCOME_REPORT_NOT_FOUND,
    ERR_PANEL_NOT_SEATED,
    ERR_PANELIST_CONFLICT_DECLARED,
    ERR_PANELIST_NOT_ASSIGNED,
    ERR_PANELIST_NOT_FOUND,
    ERR_PLEDGE_NOT_CONFIRMED,
    ERR_PLEDGE_NOT_FOUND,
    ERR_POOL_INSUFFICIENT,
    ERR_REPORT_INVALID_STATE,
    ERR_REQUEST_INVALID_STATE,
    ERR_REQUEST_NOT_FOUND,
    ERR_REVIEW_AGENCY_MISMATCH,
    ERR_SITE_VISIT_WINDOW_INVALID,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_date_equals,
    assert_decimal_equals,
    assert_is_false,
    assert_is_null,
    assert_money,
    require_by,
)
from test_helpers.factories import (
    allocation_request_payload,
    certify_payload,
    collection_payload,
    panel_assignment_payload,
    panel_score_payload,
    panelist_payload,
    pledge_payload,
    revision_request_payload,
    site_visit_payload,
)
from test_helpers.fixtures import (
    create_active_employer,
    create_agency,
    create_campaign,
    create_cycle,
    create_employer,
    create_good_standing_agency,
    create_open_cycle,
    create_outcome_report,
    create_panelist,
    create_request,
    create_submitted_request,
    current_cycle_version,
    file_review,
    file_score,
    finalize,
    seat_panelist,
    set_clock,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_allocations_director_headers,
    make_finance_reviewer_headers,
    make_panelist_headers,
)


UNUSED_EMPLOYER_ID = "aaaaaaaa-0000-4000-8000-000000000001"
UNUSED_CAMPAIGN_ID = "aaaaaaaa-0000-4000-8000-000000000002"
UNUSED_PLEDGE_ID = "aaaaaaaa-0000-4000-8000-000000000003"
UNUSED_AGENCY_ID = "aaaaaaaa-0000-4000-8000-000000000004"
UNUSED_CYCLE_ID = "aaaaaaaa-0000-4000-8000-000000000005"
UNUSED_REQUEST_ID = "aaaaaaaa-0000-4000-8000-000000000006"
UNUSED_PANELIST_ID = "aaaaaaaa-0000-4000-8000-000000000007"
UNUSED_REPORT_ID = "aaaaaaaa-0000-4000-8000-000000000008"
UNUSED_REVIEW_ID = "aaaaaaaa-0000-4000-8000-000000000009"
UNUSED_PANELIST_FK = "11111111-1111-4111-8111-111111111111"
UNUSED_CYCLE_PATH = "22222222-2222-4222-8222-222222222222"


def test_a_panelist_round_trips_every_field_and_starts_with_no_seats():
    """PRD 3.7: "A `UnitedFundAdmin` or an `AllocationsDirector` records a panelist's
    `full_name` (1 to 120 characters), `email` (containing an at-sign and globally unique
    across all panelists) and `expertise_area`, which is the subject-matter lane the
    volunteer was recruited for and may be `BASIC_NEEDS`, `EDUCATION`, `HEALTH`,
    `FINANCIAL_STABILITY` or `FINANCE`."

    PRD 3.7: "Both `submitted_score_count`, the number of scores the volunteer has ever
    filed, and `site_visit_count`, the number of outcome reports whose site visit the
    volunteer scheduled, begin at 0."

    PRD 2.3: "`limit` caps the number of records returned; when omitted it defaults to 10,
    its minimum accepted value is 1 and its maximum accepted value is 100."

    Design: Corner/endpoints/panelist_standard_crud_create_then_read_round_trip
    """
    admin = make_admin_headers()

    created = validate_success(
        api_client.create_panelist(
            panelist_payload(
                full_name="Imogen Baptiste",
                email="imogen.baptiste@panel.example",
                expertise_area="FINANCIAL_STABILITY",
            ),
            make_allocations_director_headers(),
        ),
        201,
    )

    assert created["full_name"] == "Imogen Baptiste"
    assert created["email"] == "imogen.baptiste@panel.example"
    assert created["expertise_area"] == "FINANCIAL_STABILITY"
    assert created["submitted_score_count"] == 0
    assert created["site_visit_count"] == 0
    assert created["version"] == 1
    assert_common_fields(created, "panelist")

    reread = validate_success(api_client.get_panelist(created["id"], admin))
    for field in (
        "id",
        "full_name",
        "email",
        "expertise_area",
        "submitted_score_count",
        "site_visit_count",
        "version",
        "created_at",
        "updated_at",
    ):
        assert reread[field] == created[field], f"the read re-derived {field}"

    seats, meta = validate_paginated(
        api_client.list_panelist_panel_assignments(created["id"], admin)
    )
    assert seats == [], "a brand-new volunteer holds no seats"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == 10, "the omitted limit defaults to 10"
    assert meta["offset"] == 0


def test_countersigning_is_a_transition_that_cannot_be_replayed():
    """PRD 3.1: "Countersigning later is a distinct administrative act available only to a
    `UnitedFundAdmin`: it advances the partnership `PROSPECT → ACTIVE` and sets
    `partnership_signed` to true."

    PRD 3.1: "Because an employer registered as already signed is `ACTIVE` on arrival, a
    countersignature attempt against it has nothing to advance and is refused with
    `ERR_EMPLOYER_INVALID_STATE`."

    Design: Corner/endpoints/activate_employer_action_endpoint_rejects_second_activation_with_invalid_state
    """
    admin = make_admin_headers()
    unsigned = create_employer(legal_name="Bellhaven Foods", employee_count=500)
    signed = create_active_employer(legal_name="Tanager Mutual", employee_count=120)

    assert unsigned["status"] == "PROSPECT"
    assert unsigned["version"] == 1
    assert_is_false(unsigned["partnership_signed"], "partnership_signed at registration")
    assert signed["status"] == "ACTIVE", (
        "registering with the agreement already countersigned skips the transition"
    )

    activated = validate_success(api_client.activate_employer(unsigned["id"], admin))
    assert activated["status"] == "ACTIVE"
    assert activated["partnership_signed"] is True
    assert activated["version"] == 2, "the transition is one mutation"

    validate_error(
        api_client.activate_employer(unsigned["id"], admin), ERR_EMPLOYER_INVALID_STATE, 409
    )
    validate_error(
        api_client.activate_employer(signed["id"], admin), ERR_EMPLOYER_INVALID_STATE, 409
    )

    final = validate_success(api_client.get_employer(unsigned["id"], admin))
    assert final["version"] == 2, "the refused replay did not bump the version"
    assert final["status"] == "ACTIVE"
    assert final["active_campaign_count"] == 0, "activation opens no campaign"


def test_a_panel_seat_needs_both_of_its_endpoints_to_resolve():
    """PRD 2.9: "When a path names more than one resource, existence is validated strictly
    left to right, and the first identifier that resolves to nothing determines the error."

    PRD 3.7: "Seating a volunteer on a cycle creates a panel seat carrying the `cycle_id`
    of the panel and the `panelist_id` of the volunteer, and is performed by a
    `UnitedFundAdmin` or an `AllocationsDirector`."

    Design: Corner/endpoints/panel_assignment_with_unknown_panelist_fk_returns_panelist_not_found
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    panelist = create_panelist(
        full_name="Desmond Achebe",
        email="desmond.achebe@panel.example",
        expertise_area="FINANCE",
    )
    cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="FINANCIAL_STABILITY",
        opening_undesignated_pool="150000.00",
        max_award_per_agency="40000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )

    validate_error(
        api_client.create_panel_assignment(
            cycle["id"],
            panel_assignment_payload(UNUSED_PANELIST_FK, conflict_declared=False),
            director,
        ),
        ERR_PANELIST_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_panel_assignment(
            UNUSED_CYCLE_PATH,
            panel_assignment_payload(panelist["id"], conflict_declared=False),
            director,
        ),
        ERR_CYCLE_NOT_FOUND,
        404,
    )

    seat = validate_success(
        api_client.create_panel_assignment(
            cycle["id"],
            panel_assignment_payload(
                panelist["id"], conflict_declared=False, assignment_role="CHAIR"
            ),
            director,
        ),
        201,
    )

    assert seat["cycle_id"] == cycle["id"]
    assert seat["panelist_id"] == panelist["id"]
    assert seat["assignment_role"] == "CHAIR"
    assert_is_false(seat["conflict_declared"], "conflict_declared")
    assert seat["submitted_score_count"] == 0

    from_cycle, cycle_meta = validate_paginated(
        api_client.list_cycle_panel_assignments(cycle["id"], admin)
    )
    assert cycle_meta["total_count"] == 1
    assert require_by(from_cycle, "id", seat["id"])["panelist_id"] == panelist["id"]

    from_panelist, panelist_meta = validate_paginated(
        api_client.list_panelist_panel_assignments(panelist["id"], admin)
    )
    assert panelist_meta["total_count"] == 1
    assert require_by(from_panelist, "id", seat["id"])["cycle_id"] == cycle["id"]

    reread_cycle = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert reread_cycle["posture"] == "DRAFT", "seating a panel does not open the cycle"


def test_the_fund_summary_is_derived_on_read_from_an_untouched_pool():
    """PRD 3.8: "The cycle's overall fund position is available as a computed read that
    reports, for one cycle, its `cycle_id` and `posture`, the `opening_undesignated_pool`,
    the `available_undesignated_pool`, the `awarded_total`, a `base_award_total` and a
    `designation_offset_total` and a `strategic_supplement_total` summing those three
    components across the cycle's awarded requests, an `awarded_request_count`, plus the
    `suspended_request_count`, the `suspended_request_ratio` and the `awards_blocked`
    flag."

    PRD 3.7: "The `suspended_request_ratio` is the suspended count divided by the
    submitted count, rounded half up to four decimal places, and exactly 0.0000 when no
    request of the cycle has ever been submitted."

    Design: Corner/endpoints/impact_fund_summary_computed_read_on_freshly_opened_cycle
    """
    panelist = create_panelist(
        full_name="Perpetua Vance",
        email="perpetua.vance@panel.example",
        expertise_area="HEALTH",
    )
    cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="300000.00",
        max_award_per_agency="100000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    seat_panelist(cycle["id"], panelist["id"], conflict_declared=False)
    opened = validate_success(
        api_client.open_allocation_cycle(cycle["id"], make_allocations_director_headers())
    )
    assert opened["posture"] == "OPEN"

    summary = validate_success(
        api_client.get_impact_fund_summary(cycle["id"], make_finance_reviewer_headers())
    )

    assert summary["cycle_id"] == cycle["id"]
    assert summary["posture"] == "OPEN"
    assert_money(summary["opening_undesignated_pool"], "300000.00", "opening pool")
    assert_money(
        summary["available_undesignated_pool"], "300000.00", "available_undesignated_pool"
    )
    assert_money(summary["awarded_total"], "0.00", "awarded_total")
    assert_money(summary["base_award_total"], "0.00", "base_award_total")
    assert_money(summary["designation_offset_total"], "0.00", "designation_offset_total")
    assert_money(
        summary["strategic_supplement_total"], "0.00", "strategic_supplement_total"
    )
    assert summary["awarded_request_count"] == 0
    assert summary["suspended_request_count"] == 0
    assert_decimal_equals(
        summary["suspended_request_ratio"], "0.0000", "suspended_request_ratio"
    )
    assert_is_false(summary["awards_blocked"], "awards_blocked")


def test_every_declared_not_found_code_names_its_own_resource():
    """PRD 2.9: "The resolution order across this API is: employer, campaign, pledge,
    agency, agency review, allocation cycle, allocation request, panelist, outcome report
    — yielding `ERR_EMPLOYER_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`,
    `ERR_AGENCY_NOT_FOUND`, `ERR_AGENCY_REVIEW_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND` and `ERR_OUTCOME_REPORT_NOT_FOUND`
    respectively, all with HTTP 404."

    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    The last leg is the nested case: the agency in the path is real and only the review id
    is unused, so left-to-right resolution reaches the review before it can complain about
    anything else.

    Design: Corner/errors/all_path_segment_and_body_fk_not_found_errors_are_triggerable
    """
    admin = make_admin_headers()
    agency = create_agency(
        legal_name="Fourohfour Community Aid",
        ein="620000001",
        primary_priority_area="BASIC_NEEDS",
    )

    legs = (
        (api_client.get_employer(UNUSED_EMPLOYER_ID, admin), ERR_EMPLOYER_NOT_FOUND),
        (api_client.get_campaign(UNUSED_CAMPAIGN_ID, admin), ERR_CAMPAIGN_NOT_FOUND),
        (api_client.get_pledge(UNUSED_PLEDGE_ID, admin), ERR_PLEDGE_NOT_FOUND),
        (api_client.get_agency(UNUSED_AGENCY_ID, admin), ERR_AGENCY_NOT_FOUND),
        (api_client.get_allocation_cycle(UNUSED_CYCLE_ID, admin), ERR_CYCLE_NOT_FOUND),
        (
            api_client.get_allocation_request(UNUSED_REQUEST_ID, admin),
            ERR_REQUEST_NOT_FOUND,
        ),
        (api_client.get_panelist(UNUSED_PANELIST_ID, admin), ERR_PANELIST_NOT_FOUND),
        (
            api_client.get_outcome_report(UNUSED_REPORT_ID, admin),
            ERR_OUTCOME_REPORT_NOT_FOUND,
        ),
    )
    for response, expected_error in legs:
        error = validate_error(response, expected_error, 404)
        assert isinstance(error["message"], str) and error["message"], (
            f"{expected_error} must carry a human-readable message"
        )

    nested = api_client.certify_agency_review(
        agency["id"], UNUSED_REVIEW_ID, certify_payload(), make_finance_reviewer_headers()
    )
    validate_error(nested, ERR_AGENCY_REVIEW_NOT_FOUND, 404)

    untouched = validate_success(api_client.get_agency(agency["id"], admin))
    assert untouched["membership_status"] == "APPLICANT", (
        "the refused certification never reached the agency"
    )
    assert untouched["version"] == 1


def test_the_campaign_and_pledge_gates_fire_each_at_its_own_moment():
    """PRD 2.10: "11. Campaign posture must be `OPEN` for pledge recording, pledge
    confirmation and designation amendment (`ERR_CAMPAIGN_NOT_OPEN`)."

    PRD 3.3: "The payload carries a `donor_reference` — the employer-side donor
    identifier, 1 to 40 characters, unique within the campaign, and rejected with
    `ERR_DUPLICATE_DONOR_REFERENCE` when it collides with another pledge of the same
    campaign — together with a `giving_method` of `PAYROLL_DEDUCTION`, `ONE_TIME_CHECK`,
    `CREDIT_CARD` or `STOCK_GIFT`, and a `gross_amount` that must be strictly greater than
    zero with at most two decimal places."

    PRD 3.5: "The `amount` may not exceed the pledge's outstanding balance, which is
    `gross_amount` minus `collected_amount`; a larger remittance is refused with
    `ERR_COLLECTION_EXCEEDS_OUTSTANDING`."

    PRD 3.5: "Beyond the posture check, it requires that no pledge of the campaign whose
    designation status is `CONFIRMED` or `AMENDED` still sits at `PENDING` collection; if
    one does, reconciliation is refused with `ERR_CAMPAIGN_NOT_FULLY_REMITTED`."

    Design: Corner/errors/campaign_and_pledge_state_gate_errors_are_triggerable
    """
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    employer = create_active_employer(legal_name="Gale Harbor Shipping", employee_count=180)
    campaign = create_campaign(
        employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    assert campaign["posture"] == "PLANNED"

    body = pledge_payload(
        donor_reference="G-001", giving_method="ONE_TIME_CHECK", gross_amount="500.00"
    )
    validate_error(
        api_client.create_pledge(campaign["id"], body, admin), ERR_CAMPAIGN_NOT_OPEN, 409
    )

    validate_success(api_client.open_campaign(campaign["id"], admin))
    pledge = validate_success(api_client.create_pledge(campaign["id"], body, admin), 201)

    validate_error(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="G-001", giving_method="CREDIT_CARD", gross_amount="75.00"
            ),
            admin,
        ),
        ERR_DUPLICATE_DONOR_REFERENCE,
        409,
    )

    validate_error(
        api_client.create_collection(
            pledge["id"], collection_payload("100.00", "2026-08-01"), finance
        ),
        ERR_PLEDGE_NOT_CONFIRMED,
        409,
    )

    validate_success(api_client.confirm_pledge(pledge["id"], admin))

    validate_error(
        api_client.create_collection(
            pledge["id"], collection_payload("600.00", "2026-08-01"), finance
        ),
        ERR_COLLECTION_EXCEEDS_OUTSTANDING,
        422,
    )

    closed = validate_success(api_client.close_campaign_solicitation(campaign["id"], admin))
    assert closed["posture"] == "SOLICITATION_CLOSED"

    validate_error(
        api_client.reconcile_campaign(campaign["id"], finance),
        ERR_CAMPAIGN_NOT_FULLY_REMITTED,
        422,
    )

    reread_pledge = validate_success(api_client.get_pledge(pledge["id"], admin))
    assert reread_pledge["collection_status"] == "PENDING", (
        "both refused remittances left the collection axis untouched"
    )
    assert_money(reread_pledge["collected_amount"], "0.00", "collected_amount")
    assert reread_pledge["designation_status"] == "CONFIRMED"

    reread_campaign = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert reread_campaign["posture"] == "SOLICITATION_CLOSED", (
        "the refused reconciliation did not move the posture"
    )
    assert_money(reread_campaign["confirmed_gross_total"], "500.00", "confirmed_gross_total")

    _, meta = validate_paginated(
        api_client.list_pledges(admin, {"campaign_id": campaign["id"]})
    )
    assert meta["total_count"] == 1, "only the one accepted pledge exists"


def test_the_cycle_and_panel_gates_fire_each_at_its_own_moment():
    """PRD 3.7: "It requires at least one seat on the cycle whose `conflict_declared` is
    false; a cycle with no conflict-free seat cannot open and is refused with
    `ERR_PANEL_NOT_SEATED`."

    PRD 3.7: "The cycle must be `OPEN`; `DRAFT` cycles are refused with
    `ERR_CYCLE_NOT_OPEN` and `FROZEN` cycles with `ERR_CYCLE_FROZEN`."

    PRD 3.7: "And the `requested_amount` must not exceed twice the cycle's
    `max_award_per_agency` — the organization will read an ask of up to double the ceiling
    but no more — with an excess refused as `ERR_AWARD_EXCEEDS_AGENCY_CAP`."

    PRD 3.7: "An agency may hold only one live request per cycle: if it already holds a
    request on that cycle in any status other than `PANEL_DECLINED`, the draft is refused
    with `ERR_DUPLICATE_REQUEST_FOR_CYCLE`, which is what lets a declined agency try again
    in the same cycle."

    PRD 2.10: "20. Allocation request status must be one the operation accepts: `DRAFT` to
    submit; either `SUBMITTED` or `UNDER_PANEL_REVIEW` to finalize review or to file a
    score; `PANEL_APPROVED` to award; either `AWARDED` or `REPORTING` to rescind an award;
    `AWARDED` to file an outcome report (`ERR_REQUEST_INVALID_STATE`)."

    PRD 3.7: "The volunteer must hold a seat on that request's cycle, or the filing is
    refused with `ERR_PANELIST_NOT_ASSIGNED`; if that seat carries `conflict_declared` true
    the filing is refused with `ERR_PANELIST_CONFLICT_DECLARED`; and a volunteer may file
    at most one score per request, a second attempt being refused with
    `ERR_DUPLICATE_PANEL_SCORE`."

    Design: Corner/errors/cycle_and_request_gate_errors_are_triggerable
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    agency_a = create_good_standing_agency(
        legal_name="Alder Grove Services",
        ein="620000002",
        primary_priority_area="BASIC_NEEDS",
    )
    agency_b = create_good_standing_agency(
        legal_name="Beacon Hill Outreach",
        ein="620000003",
        primary_priority_area="EDUCATION",
    )
    conflict_free = create_panelist(
        full_name="Gate Panelist One",
        email="g1.gate@panel.example",
        expertise_area="BASIC_NEEDS",
    )
    conflicted = create_panelist(
        full_name="Gate Panelist Two",
        email="g2.gate@panel.example",
        expertise_area="EDUCATION",
    )
    unseated = create_panelist(
        full_name="Gate Panelist Three",
        email="g3.gate@panel.example",
        expertise_area="HEALTH",
    )
    cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="100000.00",
        max_award_per_agency="20000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    over_cap = create_request(
        cycle["id"],
        agency_a["id"],
        requested_amount="50000.00",
        priority_area="BASIC_NEEDS",
        narrative_summary="Cap-busting ask used to trigger the ceiling.",
    )

    validate_error(
        api_client.open_allocation_cycle(cycle["id"], director), ERR_PANEL_NOT_SEATED, 422
    )
    assert validate_success(api_client.get_allocation_cycle(cycle["id"], admin))[
        "posture"
    ] == "DRAFT"

    validate_error(
        api_client.submit_allocation_request(over_cap["id"], admin), ERR_CYCLE_NOT_OPEN, 409
    )

    seat_panelist(
        cycle["id"], conflict_free["id"], conflict_declared=False, assignment_role="CHAIR"
    )
    seat_panelist(
        cycle["id"], conflicted["id"], conflict_declared=True, assignment_role="SCORER"
    )
    opened = validate_success(api_client.open_allocation_cycle(cycle["id"], director))
    assert opened["posture"] == "OPEN"
    assert_money(
        opened["available_undesignated_pool"], "100000.00", "available_undesignated_pool"
    )

    validate_error(
        api_client.submit_allocation_request(over_cap["id"], admin),
        ERR_AWARD_EXCEEDS_AGENCY_CAP,
        422,
    )
    assert validate_success(api_client.get_allocation_request(over_cap["id"], admin))[
        "status"
    ] == "DRAFT"

    validate_error(
        api_client.create_allocation_request(
            allocation_request_payload(
                cycle["id"],
                agency_a["id"],
                requested_amount="15000.00",
                priority_area="BASIC_NEEDS",
                narrative_summary="Second ask by the same agency on the same cycle.",
            ),
            admin,
        ),
        ERR_DUPLICATE_REQUEST_FOR_CYCLE,
        409,
    )

    validate_error(
        api_client.create_panel_score(
            over_cap["id"],
            panel_score_payload(80, 80, 80),
            make_panelist_headers(conflict_free["id"]),
        ),
        ERR_REQUEST_INVALID_STATE,
        409,
    )

    in_play = create_submitted_request(
        cycle["id"],
        agency_b["id"],
        requested_amount="18000.00",
        priority_area="EDUCATION",
        narrative_summary="Within-ceiling ask that reaches SUBMITTED.",
    )
    assert in_play["status"] == "SUBMITTED"

    validate_error(
        api_client.create_panel_score(
            in_play["id"],
            panel_score_payload(70, 70, 70),
            make_panelist_headers(conflicted["id"]),
        ),
        ERR_PANELIST_CONFLICT_DECLARED,
        422,
    )
    validate_error(
        api_client.create_panel_score(
            in_play["id"],
            panel_score_payload(70, 70, 70),
            make_panelist_headers(unseated["id"]),
        ),
        ERR_PANELIST_NOT_ASSIGNED,
        422,
    )

    accepted = validate_success(
        api_client.create_panel_score(
            in_play["id"],
            panel_score_payload(90, 80, 70),
            make_panelist_headers(conflict_free["id"]),
        ),
        201,
    )
    assert_money(accepted["weighted_score"], "81.50", "weighted_score")

    validate_error(
        api_client.create_panel_score(
            in_play["id"],
            panel_score_payload(60, 60, 60),
            make_panelist_headers(conflict_free["id"]),
        ),
        ERR_DUPLICATE_PANEL_SCORE,
        409,
    )

    reread = validate_success(api_client.get_allocation_request(in_play["id"], admin))
    assert reread["status"] == "UNDER_PANEL_REVIEW"
    assert reread["eligible_score_count"] == 1, "only the accepted score counts"

    for refused in (conflicted, unseated):
        assert validate_success(api_client.get_panelist(refused["id"], admin))[
            "submitted_score_count"
        ] == 0, "a refused filing never touches the volunteer's tally"
    assert validate_success(api_client.get_panelist(conflict_free["id"], admin))[
        "submitted_score_count"
    ] == 1


def test_certifying_a_review_under_the_wrong_agency_is_a_relationship_failure():
    """PRD 2.9: "Existence alone is not integrity. Where a path nests one resource inside
    another, the child must actually belong to the named parent: certifying a review
    requires that the review named by `review_id` in the path belong to the agency named
    earlier in the same path, and a mismatch is rejected with `ERR_REVIEW_AGENCY_MISMATCH`
    (409)."

    PRD 3.6: "The review must still be `PENDING`, or the attempt is refused with
    `ERR_REVIEW_ALREADY_CERTIFIED`; the review must belong to the agency named earlier in
    the path, or the attempt is refused with `ERR_REVIEW_AGENCY_MISMATCH`; and the agency
    must not be `SUSPENDED_MEMBERSHIP`, or the attempt is refused with
    `ERR_AGENCY_MEMBERSHIP_TERMINAL`."

    PRD 3.6: "A score of 70.00 or more moves the agency `UNDER_FINANCIAL_REVIEW → GOOD_STANDING`."

    The control leg certifies the very same review under its own agency and succeeds, so
    the refusal is attributable to the mismatched parent alone.

    Design: Corner/errors/certify_review_under_wrong_agency_path_returns_review_agency_mismatch
    """
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    first_agency = create_agency(
        legal_name="Crosswalk Legal Aid",
        ein="620000004",
        primary_priority_area="FINANCIAL_STABILITY",
    )
    file_review(first_agency["id"], fiscal_year=2025)
    second_agency = create_agency(
        legal_name="Dunmore Arts Collective",
        ein="620000005",
        primary_priority_area="EDUCATION",
    )
    second_review = file_review(second_agency["id"], fiscal_year=2025)

    validate_error(
        api_client.certify_agency_review(
            first_agency["id"], second_review["id"], certify_payload(), finance
        ),
        ERR_REVIEW_AGENCY_MISMATCH,
        409,
    )

    reviews, meta = validate_paginated(
        api_client.list_agency_reviews(second_agency["id"], admin)
    )
    assert meta["total_count"] == 1
    assert require_by(reviews, "id", second_review["id"])["status"] == "PENDING", (
        "the mismatched certification left the review untouched"
    )
    assert validate_success(api_client.get_agency(first_agency["id"], admin))[
        "membership_status"
    ] == "UNDER_FINANCIAL_REVIEW"

    certified = validate_success(
        api_client.certify_agency_review(
            second_agency["id"], second_review["id"], certify_payload(), finance
        )
    )

    assert certified["status"] == "CERTIFIED"
    assert certified["review_basis"] == "AUDITED"
    assert_money(certified["certified_score"], "90.00", "certified_score")

    reread_second = validate_success(api_client.get_agency(second_agency["id"], admin))
    assert reread_second["membership_status"] == "GOOD_STANDING"
    assert_money(reread_second["latest_standing_score"], "90.00", "latest_standing_score")

    reread_first = validate_success(api_client.get_agency(first_agency["id"], admin))
    assert reread_first["membership_status"] == "UNDER_FINANCIAL_REVIEW", (
        "the other agency is still mid-review and was never certified"
    )
    assert_is_null(reread_first["latest_standing_score"], "latest_standing_score")


def test_the_supplement_can_push_a_perfectly_fitting_base_past_the_pool():
    """PRD 3.8: "The cycle's `available_undesignated_pool` must be strictly greater than
    zero, and the assembled award computed below — before its final clamp — must not exceed
    that available pool; either failure is refused with `ERR_POOL_INSUFFICIENT`."

    PRD 3.8: "Step six assembles the unclamped award as the net figure plus the strategic
    supplement, and this is the figure the pool-sufficiency check tests."

    PRD 3.8: "Step seven applies the pool clamp last: `total_award` is the smaller of the
    unclamped award and the cycle's `available_undesignated_pool`."

    Against a 1000.00 pool, the 2000.00 ask scales to 1630.00 and step three clamps the
    base to exactly the pool at 1000.00; the 0.06 supplement of 60.00 then carries the
    unclamped total to 1060.00, which the guard must refuse rather than clamp back down.

    Design: Corner/errors/award_supplement_pushing_total_above_available_pool_returns_pool_insufficient
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    agency = create_good_standing_agency(
        legal_name="Everly Credit Counseling",
        ein="620000006",
        primary_priority_area="FINANCIAL_STABILITY",
    )
    cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="1000.00",
        max_award_per_agency="2000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    panelists = [
        create_panelist(
            full_name=f"Pool Panelist {label}",
            email=f"{label.lower()}.pool@panel.example",
            expertise_area=area,
        )
        for label, area in (
            ("One", "FINANCIAL_STABILITY"),
            ("Two", "FINANCE"),
            ("Three", "HEALTH"),
        )
    ]
    for panelist in panelists:
        seat_panelist(cycle["id"], panelist["id"], conflict_declared=False)
    validate_success(api_client.open_allocation_cycle(cycle["id"], director))

    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="2000.00",
        priority_area="FINANCIAL_STABILITY",
        narrative_summary="Financial coaching cohort.",
    )
    for panelist in panelists:
        file_score(
            request["id"],
            panelist["id"],
            priority_alignment_score=90,
            outcome_evidence_score=80,
            capacity_score=70,
        )
    approved = finalize(request["id"])
    assert approved["status"] == "PANEL_APPROVED"
    assert_money(approved["composite_score"], "81.50", "composite_score")
    assert approved["eligible_score_count"] == 3

    version_before = current_cycle_version(cycle["id"])
    refused = api_client.create_award(
        cycle["id"],
        {"request_id": request["id"], "expected_allocation_cycle_version": version_before},
        director,
    )
    validate_error(refused, ERR_POOL_INSUFFICIENT, 422)

    reread_request = validate_success(
        api_client.get_allocation_request(request["id"], admin)
    )
    assert reread_request["status"] == "PANEL_APPROVED", "the refused award moved nothing"
    for field in (
        "base_award",
        "designation_offset",
        "strategic_supplement",
        "total_award",
        "awarded_at",
        "outcome_report_due_date",
    ):
        assert_is_null(reread_request[field], field)

    reread_cycle = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert_money(
        reread_cycle["available_undesignated_pool"], "1000.00", "available_undesignated_pool"
    )
    assert_money(reread_cycle["awarded_total"], "0.00", "awarded_total")
    assert reread_cycle["version"] == version_before, (
        "a refused award does not bump the concurrency field"
    )

    summary = validate_success(api_client.get_impact_fund_summary(cycle["id"], director))
    assert_money(
        summary["available_undesignated_pool"], "1000.00", "available_undesignated_pool"
    )
    assert summary["awarded_request_count"] == 0


def _reporting_scenario():
    """One REPORTING request with a filed report and a fourth, non-scoring seat."""
    agency = create_good_standing_agency(
        legal_name="Foxglove Health Partners",
        ein="620000007",
        primary_priority_area="HEALTH",
    )
    cycle, panelists = create_open_cycle(
        4,
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="300000.00",
        max_award_per_agency="100000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="80000.00",
        priority_area="HEALTH",
        narrative_summary="Community clinic evening hours.",
    )
    return agency, cycle, panelists, request


def test_the_reporting_gates_refuse_disposition_and_two_bad_windows():
    """PRD 2.10: "Outcome report status must be exactly the status the requested
    transition starts from: `SUBMITTED` to schedule a site visit, `SITE_VISIT_SCHEDULED`
    to complete it, `SITE_VISIT_COMPLETED` to accept or to request a revision, and
    `REVISION_REQUESTED` to resubmit (`ERR_REPORT_INVALID_STATE`)."

    PRD 3.9: "Third, window sanity: `site_visit_window_start` must be on or after the date
    part of the report's `submitted_at`, `site_visit_window_end` must be on or after
    `site_visit_window_start`, and `site_visit_window_end` must be no later than the date
    part of `submitted_at` plus 90 calendar days; any violation is refused with
    `ERR_SITE_VISIT_WINDOW_INVALID`."

    PRD 3.9: "Scheduling stores the window and increments the volunteer's
    `site_visit_count`."

    The report is stamped at 2026-08-01, so a window opening 2026-07-15 is too early and
    one closing 2026-11-05 runs past the 90-day lead that ends 2026-10-30; the third,
    legal window then schedules and proves the four refusals were about their own checks.

    Design: Corner/errors/outcome_report_pre_site_visit_transition_and_window_errors_are_triggerable
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    agency, cycle, panelists, request = _reporting_scenario()
    scorers, monitor = panelists[:3], panelists[3]
    triple = (90, 80, 70)
    for panelist in scorers:
        file_score(
            request["id"],
            panelist["id"],
            priority_alignment_score=triple[0],
            outcome_evidence_score=triple[1],
            capacity_score=triple[2],
        )
    approved = finalize(request["id"])
    assert approved["status"] == "PANEL_APPROVED"
    validate_success(
        api_client.create_award(
            cycle["id"],
            {
                "request_id": request["id"],
                "expected_allocation_cycle_version": current_cycle_version(cycle["id"]),
            },
            director,
        )
    )
    awarded = validate_success(api_client.get_allocation_request(request["id"], admin))
    assert awarded["status"] == "AWARDED"
    assert_money(awarded["total_award"], "67156.00", "total_award")
    assert_date_equals(
        awarded["outcome_report_due_date"], "2027-01-28", "outcome_report_due_date"
    )

    report = create_outcome_report(
        request["id"], agency["id"], funds_expended="70000.00"
    )
    assert report["status"] == "SUBMITTED"
    assert report["revision_round_count"] == 0
    assert_decimal_equals(
        report["expenditure_variance_pct"], "4.23", "expenditure_variance_pct"
    )
    assert_is_null(report["site_visit_panelist_id"], "site_visit_panelist_id")
    assert validate_success(api_client.get_allocation_request(request["id"], admin))[
        "status"
    ] == "REPORTING"

    validate_error(
        api_client.accept_outcome_report(report["id"], director),
        ERR_REPORT_INVALID_STATE,
        409,
    )
    validate_error(
        api_client.request_outcome_report_revision(
            report["id"], revision_request_payload(), director
        ),
        ERR_REPORT_INVALID_STATE,
        409,
    )

    monitor_headers = make_panelist_headers(monitor["id"])
    validate_error(
        api_client.schedule_site_visit(
            report["id"],
            site_visit_payload("2026-07-15", "2026-07-20"),
            monitor_headers,
        ),
        ERR_SITE_VISIT_WINDOW_INVALID,
        422,
    )
    validate_error(
        api_client.schedule_site_visit(
            report["id"],
            site_visit_payload("2026-08-05", "2026-11-05"),
            monitor_headers,
        ),
        ERR_SITE_VISIT_WINDOW_INVALID,
        422,
    )

    still_submitted = validate_success(api_client.get_outcome_report(report["id"], admin))
    assert still_submitted["status"] == "SUBMITTED", "four refusals moved nothing"
    assert_is_null(still_submitted["site_visit_panelist_id"], "site_visit_panelist_id")
    assert_is_null(still_submitted["site_visit_window_start"], "site_visit_window_start")

    scheduled = validate_success(
        api_client.schedule_site_visit(
            report["id"],
            site_visit_payload("2026-08-10", "2026-08-20"),
            monitor_headers,
        )
    )

    assert scheduled["status"] == "SITE_VISIT_SCHEDULED"
    assert scheduled["site_visit_panelist_id"] == monitor["id"]
    assert_date_equals(
        scheduled["site_visit_window_start"], "2026-08-10", "site_visit_window_start"
    )
    assert_date_equals(
        scheduled["site_visit_window_end"], "2026-08-20", "site_visit_window_end"
    )
    assert_is_null(scheduled["site_visit_findings"], "site_visit_findings")

    reread_monitor = validate_success(api_client.get_panelist(monitor["id"], admin))
    assert reread_monitor["site_visit_count"] == 1, "only the accepted window counted"
    assert reread_monitor["submitted_score_count"] == 0, (
        "the monitoring volunteer never scored this request"
    )


def test_an_overdue_report_bars_only_its_own_agency_from_the_next_cycle():
    """PRD 3.9: "An agency's `outcome_report_delinquent` flag is true when at least one of
    its allocation requests is `AWARDED` or `REPORTING`, has a non-null
    `outcome_report_due_date`, has a due date the logical clock's date is strictly past,
    and has no outcome report at `ACCEPTED`."

    PRD 3.9: "Delinquency is the enforcement behind the reporting obligation, and it is
    re-derived whenever a report is filed or accepted, whenever a request is awarded, and
    whenever the logical clock moves."

    PRD 3.7: "The agency's `outcome_report_delinquent` flag must be false, or the
    submission is refused with `ERR_OUTCOME_REPORT_DELINQUENT`."

    The clock stops first at 2027-01-20, eight days ahead of the 2027-01-28 due date, so
    the flag is still false; only the move to 2027-02-01 makes the date strictly past.
    The second agency, holding no award at all, submits into the same cycle unimpeded.

    Design: Corner/errors/overdue_outcome_report_blocks_next_cycle_submission_with_delinquent_error
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    delinquent_agency = create_good_standing_agency(
        legal_name="Gladstone Family Center",
        ein="620000008",
        primary_priority_area="HEALTH",
    )
    clear_agency = create_good_standing_agency(
        legal_name="Hartley Bridge Coalition",
        ein="620000009",
        primary_priority_area="BASIC_NEEDS",
    )
    first_cycle, first_panelists = create_open_cycle(
        3,
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="300000.00",
        max_award_per_agency="100000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    first_request = create_submitted_request(
        first_cycle["id"],
        delinquent_agency["id"],
        requested_amount="80000.00",
        priority_area="HEALTH",
        narrative_summary="Family stabilization case management.",
    )
    for panelist in first_panelists:
        file_score(
            first_request["id"],
            panelist["id"],
            priority_alignment_score=90,
            outcome_evidence_score=80,
            capacity_score=70,
        )
    finalize(first_request["id"])
    validate_success(
        api_client.create_award(
            first_cycle["id"],
            {
                "request_id": first_request["id"],
                "expected_allocation_cycle_version": current_cycle_version(
                    first_cycle["id"]
                ),
            },
            director,
        )
    )
    awarded = validate_success(
        api_client.get_allocation_request(first_request["id"], admin)
    )
    assert awarded["status"] == "AWARDED"
    assert_money(awarded["total_award"], "67156.00", "total_award")
    assert_date_equals(
        awarded["outcome_report_due_date"], "2027-01-28", "outcome_report_due_date"
    )

    second_cycle, _ = create_open_cycle(
        1,
        cycle_year=2027,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="200000.00",
        max_award_per_agency="50000.00",
        request_window_start="2027-01-01",
        request_window_end="2027-03-01",
    )
    delinquent_draft = create_request(
        second_cycle["id"],
        delinquent_agency["id"],
        requested_amount="20000.00",
        priority_area="HEALTH",
        narrative_summary="Continued family stabilization.",
    )
    clear_draft = create_request(
        second_cycle["id"],
        clear_agency["id"],
        requested_amount="20000.00",
        priority_area="BASIC_NEEDS",
        narrative_summary="Winter shelter overflow beds.",
    )

    set_clock("2027-01-20T09:00:00Z")
    before_due = validate_success(
        api_client.get_agency(delinquent_agency["id"], admin)
    )
    assert_is_false(
        before_due["outcome_report_delinquent"], "outcome_report_delinquent"
    )

    set_clock("2027-02-01T09:00:00Z")
    past_due = validate_success(api_client.get_agency(delinquent_agency["id"], admin))
    assert past_due["outcome_report_delinquent"] is True, (
        "the clock is now strictly past the 2027-01-28 due date"
    )

    validate_error(
        api_client.submit_allocation_request(
            delinquent_draft["id"], admin
        ),
        ERR_OUTCOME_REPORT_DELINQUENT,
        422,
    )
    assert validate_success(
        api_client.get_allocation_request(delinquent_draft["id"], admin)
    )["status"] == "DRAFT", "the barred submission left the draft alone"

    submitted = validate_success(
        api_client.submit_allocation_request(clear_draft["id"], admin)
    )
    assert submitted["status"] == "SUBMITTED", "the clear agency is unaffected"
    assert_is_false(
        validate_success(api_client.get_agency(clear_agency["id"], admin))[
            "outcome_report_delinquent"
        ],
        "outcome_report_delinquent",
    )

    assert validate_success(
        api_client.get_allocation_request(first_request["id"], admin)
    )["status"] == "AWARDED", "the unreported award is still open"
