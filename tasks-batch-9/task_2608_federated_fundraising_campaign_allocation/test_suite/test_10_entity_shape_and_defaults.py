"""Resource shape on arrival: echoed inputs, declared defaults, computed
counters, server-minted system fields, and the shape of the refusals that guard
creation.

Every test here reads one resource through the endpoints the PRD declares for
it, so the assertions are about what the API stores and what it derives, never
about how it stores it.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_AGENCY_NOT_FOUND,
    ERR_CYCLE_NOT_FOUND,
    ERR_DUPLICATE_PANEL_SCORE,
    ERR_INVALID_REQUEST,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_date_equals,
    assert_is_false,
    assert_is_null,
    assert_money,
    require_by,
)
from test_helpers.factories import (
    allocation_request_payload,
    panel_assignment_payload,
    pledge_payload,
)
from test_helpers.fixtures import (
    create_active_employer,
    create_agency,
    create_campaign,
    create_coordinator,
    create_cycle,
    create_open_campaign,
    create_panelist,
    seat_panelist,
)
from test_helpers.test_users import make_admin_headers, make_coordinator_headers

OTHER_UNUSED_UUID = "33333333-3333-4333-8333-333333333333"


def test_a_newly_admitted_agency_echoes_its_inputs_and_starts_as_an_applicant():
    """PRD 3.6: "A newly admitted agency stands at `membership_status` `APPLICANT`,
    with `latest_standing_score` null because no review has been certified,
    `designated_passthrough_ytd` at 0.00, `open_review_count` and `probation_count` at
    0, and `outcome_report_delinquent` false."

    Nothing has scored the agency yet, so every computed field must still be sitting
    at the value admission gives it.

    Design: Corner/entities/agency_creation_returns_declared_fields_and_applicant_initial_state
    """
    agency = validate_success(
        api_client.create_agency(
            {
                "legal_name": "Riverbend Community Aid",
                "ein": "600000001",
                "primary_priority_area": "HEALTH",
            },
            make_admin_headers(),
        ),
        201,
    )

    assert agency["legal_name"] == "Riverbend Community Aid"
    assert agency["ein"] == "600000001"
    assert agency["primary_priority_area"] == "HEALTH"
    assert agency["membership_status"] == "APPLICANT"
    assert_is_null(agency["latest_standing_score"], "latest_standing_score")
    assert_money(agency["designated_passthrough_ytd"], "0.00", "designated_passthrough_ytd")
    assert agency["open_review_count"] == 0
    assert agency["probation_count"] == 0
    assert_is_false(agency["outcome_report_delinquent"], "outcome_report_delinquent")

    assert_common_fields(agency, "agency")
    assert agency["version"] == 1, "a freshly created resource carries version 1"
    assert agency["created_at"] == agency["updated_at"], (
        "nothing has mutated the agency, so the two audit stamps agree"
    )

    reread = validate_success(api_client.get_agency(agency["id"], make_admin_headers()))
    assert reread["id"] == agency["id"]
    assert reread["membership_status"] == "APPLICANT"


def test_an_employer_registered_with_only_its_two_required_inputs_takes_the_defaults():
    """PRD 3.1: "`payroll_periods_per_year` records how many payroll runs the employer
    executes annually; it defaults to 26, must fall between 0 and 52 inclusive, and a
    value of 0 declares that this employer cannot host payroll deduction at all."

    PRD 3.1: "`historical_shrinkage_rate_bps` records the employer's own historical
    payroll-pledge loss experience in basis points; it defaults to 800, meaning 8
    percent, and must fall between 0 and 10000 inclusive."

    PRD 3.1: "An employer registered with `partnership_signed` true is created directly
    in `ACTIVE`; otherwise it is created in `PROSPECT`."

    Design: Corner/entities/employer_omitted_optional_inputs_take_declared_defaults
    """
    employer = validate_success(
        api_client.create_employer(
            {"legal_name": "Fairfield Machine Works", "employee_count": 250},
            make_admin_headers(),
        ),
        201,
    )

    assert employer["legal_name"] == "Fairfield Machine Works"
    assert employer["employee_count"] == 250
    assert employer["payroll_periods_per_year"] == 26
    assert employer["historical_shrinkage_rate_bps"] == 800
    assert_is_false(employer["partnership_signed"], "partnership_signed")
    assert employer["status"] == "PROSPECT", (
        "the defaulted partnership_signed false is what leaves the employer a prospect"
    )
    assert_is_null(employer["suspended_reason"], "suspended_reason")
    assert employer["active_campaign_count"] == 0

    activated = validate_success(
        api_client.activate_employer(employer["id"], make_admin_headers())
    )
    assert activated["status"] == "ACTIVE", (
        "PROSPECT is precisely the posture that makes the countersignature legal"
    )
    assert activated["partnership_signed"] is True


def test_reading_back_a_freshly_opened_campaign_shows_stored_inputs_and_zeroed_totals():
    """PRD 3.2: "The campaign is created in `PLANNED` posture, with every gross, fee and
    loss aggregate zeroed and every reconciliation output null:
    `provisional_estimated_loss`, `provisional_net_expected_revenue`,
    `reserve_absorbed_amount`, `final_actual_loss`, `final_net_expected_revenue`,
    `realized_shrinkage_rate_bps`, `solicitation_closed_at` and `reconciled_at` all
    begin as null."

    Opening the campaign changes its posture and nothing else: no pledge has been
    recorded, so the read surfaces stored inputs and untouched aggregates rather than
    recomputing a loss estimate on the way out.

    Design: Corner/entities/campaign_get_returns_stored_inputs_and_computed_totals
    """
    employer = create_active_employer(legal_name="Clearwater Mutual", employee_count=180)
    campaign = create_campaign(
        employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="500.00",
    )
    validate_success(api_client.open_campaign(campaign["id"], make_admin_headers()))

    reread = validate_success(
        api_client.get_campaign(campaign["id"], make_admin_headers())
    )

    assert reread["employer_id"] == employer["id"]
    assert reread["campaign_year"] == 2026
    assert_date_equals(reread["solicitation_start_date"], "2026-07-01", "start date")
    assert_date_equals(reread["solicitation_end_date"], "2026-09-30", "end date")
    assert_money(reread["loss_reserve_amount"], "500.00", "loss_reserve_amount")
    assert reread["posture"] == "OPEN"

    assert_money(reread["confirmed_gross_total"], "0.00", "confirmed_gross_total")
    assert_money(reread["designated_gross_total"], "0.00", "designated_gross_total")
    assert_money(reread["undesignated_gross_total"], "0.00", "undesignated_gross_total")
    assert_money(reread["designation_fee_total"], "0.00", "designation_fee_total")

    assert_is_null(reread["provisional_estimated_loss"], "provisional_estimated_loss")
    assert_is_null(
        reread["provisional_net_expected_revenue"], "provisional_net_expected_revenue"
    )
    assert_is_null(reread["reserve_absorbed_amount"], "reserve_absorbed_amount")
    assert_is_null(reread["final_actual_loss"], "final_actual_loss")
    assert_is_null(reread["final_net_expected_revenue"], "final_net_expected_revenue")
    assert_is_null(reread["realized_shrinkage_rate_bps"], "realized_shrinkage_rate_bps")
    assert_is_null(reread["solicitation_closed_at"], "solicitation_closed_at")
    assert_is_null(reread["reconciled_at"], "reconciled_at")


def test_the_pledge_list_pages_a_three_row_campaign_and_reports_what_remains():
    """PRD 2.3: "`limit` caps the number of records returned; when omitted it defaults
    to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

    PRD 2.3: "Both appear in the `meta` object of the envelope alongside `total_count`
    (the number of records matching the filter before pagination) and `has_more` (true
    when records remain beyond the current page)."

    Design: Corner/entities/pledge_list_filtered_by_campaign_paginates_with_total_count_and_has_more
    """
    admin = make_admin_headers()
    _, campaign = create_open_campaign(
        solicitation_start_date="2026-07-01", solicitation_end_date="2026-09-30"
    )
    recorded = []
    for donor_reference, giving_method, gross_amount in (
        ("L-001", "ONE_TIME_CHECK", "100.00"),
        ("L-002", "CREDIT_CARD", "200.00"),
        ("L-003", "STOCK_GIFT", "300.00"),
    ):
        recorded.append(
            validate_success(
                api_client.create_pledge(
                    campaign["id"],
                    pledge_payload(
                        donor_reference=donor_reference,
                        giving_method=giving_method,
                        gross_amount=gross_amount,
                    ),
                    admin,
                ),
                201,
            )["id"]
        )

    first_page, first_meta = validate_paginated(
        api_client.list_pledges(
            admin, {"campaign_id": campaign["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, "the page is capped by the requested limit"
    assert first_meta["total_count"] == 3, "total_count counts the whole filtered set"
    assert first_meta["has_more"] is True, "one row still lies beyond this page"
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api_client.list_pledges(
            admin, {"campaign_id": campaign["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1, "the offset skips the first two rows"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False, "nothing remains beyond the final page"
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2

    unpaged, unpaged_meta = validate_paginated(
        api_client.list_pledges(admin, {"campaign_id": campaign["id"]})
    )
    assert len(unpaged) == 3, "the default limit of 10 admits all three rows"
    assert unpaged_meta["total_count"] == 3
    assert unpaged_meta["has_more"] is False
    assert unpaged_meta["limit"] == 10, "limit defaults to 10 when omitted"
    assert unpaged_meta["offset"] == 0, "offset defaults to 0 when omitted"

    assert {row["id"] for row in first_page} | {row["id"] for row in second_page} == set(
        recorded
    ), "the two pages together cover the campaign's pledges exactly once"
    for row in unpaged:
        assert row["campaign_id"] == campaign["id"], "the filter admits nothing else"


def test_probing_an_agency_id_that_belongs_to_nobody_is_a_not_found_error():
    """PRD 2.9: "The resolution order across this API is: employer, campaign, pledge,
    agency, agency review, allocation cycle, allocation request, panelist, outcome
    report — yielding `ERR_EMPLOYER_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`,
    `ERR_PLEDGE_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_AGENCY_REVIEW_NOT_FOUND`,
    `ERR_CYCLE_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND` and
    `ERR_OUTCOME_REPORT_NOT_FOUND` respectively, all with HTTP 404."

    A real agency exists, so the collection is not empty; the probed identifier is
    simply unused, and that must be an error envelope rather than an empty success.

    Design: Corner/entities/get_agency_with_unknown_uuid_returns_agency_not_found
    """
    admin = make_admin_headers()
    agency = create_agency(
        legal_name="Northgate Shelter Network",
        ein="600000002",
        primary_priority_area="BASIC_NEEDS",
    )

    missing = validate_error(
        api_client.get_agency(NON_EXISTENT_UUID, admin), ERR_AGENCY_NOT_FOUND, 404
    )
    assert isinstance(missing.get("message"), str) and missing["message"].strip(), (
        "the error envelope carries a human-readable message"
    )

    untouched = validate_success(api_client.get_agency(agency["id"], admin))
    assert untouched["version"] == 1, "the refused probe touched nothing"
    assert untouched["legal_name"] == "Northgate Shelter Network"


def test_admitting_an_agency_without_every_required_input_is_refused_on_shape():
    """PRD 2.10: "Request-shape validation on every write: all required fields present;
    every value matching its declared type, enum membership and numeric range; money
    fields carrying at most 2 decimals and ratio fields at most 4
    (`ERR_INVALID_REQUEST`, 400)."

    None of the three admission inputs carries a default, so dropping any one of them
    is a shape failure rather than a domain one.

    Design: Corner/entities/create_agency_missing_required_ein_returns_invalid_request
    """
    admin = make_admin_headers()
    complete = {
        "legal_name": "Halfway House Coalition",
        "ein": "600000004",
        "primary_priority_area": "BASIC_NEEDS",
    }

    for omitted in ("ein", "legal_name", "primary_priority_area"):
        payload = {key: value for key, value in complete.items() if key != omitted}
        validate_error(
            api_client.create_agency(payload, admin), ERR_INVALID_REQUEST, 400
        )

    admitted = validate_success(api_client.create_agency(complete, admin), 201)
    assert admitted["ein"] == "600000004", (
        "the refusals persisted nothing, so the complete payload is still free to land"
    )
    assert admitted["membership_status"] == "APPLICANT"


def test_the_active_campaign_counter_only_moves_when_a_campaign_opens():
    """PRD 3.1: "The employer's `active_campaign_count` is always the number of that
    employer's campaigns whose posture is either `OPEN` or `SOLICITATION_CLOSED`,
    re-derived whenever a campaign of that employer is created or changes posture."

    The two solicitation windows touch at 2026-08-01 without intersecting, because the
    window is half-open, so both campaigns are legal and both may open.

    Design: Corner/entities/employer_active_campaign_count_is_computed_on_campaign_open
    """
    admin = make_admin_headers()
    employer = create_active_employer(
        legal_name="Summit Dairy Cooperative", employee_count=320
    )
    first = create_campaign(
        employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-08-01",
    )
    second = create_campaign(
        employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-08-01",
        solicitation_end_date="2026-09-01",
    )
    assert first["posture"] == "PLANNED"
    assert second["posture"] == "PLANNED"

    while_planned = validate_success(api_client.get_employer(employer["id"], admin))
    assert while_planned["active_campaign_count"] == 0, (
        "a PLANNED campaign is neither OPEN nor SOLICITATION_CLOSED"
    )

    opened_first = validate_success(api_client.open_campaign(first["id"], admin))
    assert opened_first["posture"] == "OPEN"
    after_one = validate_success(api_client.get_employer(employer["id"], admin))
    assert after_one["active_campaign_count"] == 1

    opened_second = validate_success(api_client.open_campaign(second["id"], admin))
    assert opened_second["posture"] == "OPEN"
    after_two = validate_success(api_client.get_employer(employer["id"], admin))
    assert after_two["active_campaign_count"] == 2


def test_a_coordinator_recorded_pledge_takes_its_recorder_from_the_caller_headers():
    """PRD 3.3: "When a coordinator records the pledge, `recorded_by_coordinator_id` is
    stamped from `X-User-ID`; the pledge's `campaign_id` is the campaign it was
    solicited inside."

    PRD 3.1: "The coordinator's `recorded_pledge_count` counts the pledges whose
    `recorded_by_coordinator_id` is that coordinator and whose designation status is
    `CONFIRMED`, `AMENDED` or `LOCKED` — draft pledges do not count toward a
    coordinator's tally, and neither do written-off ones as long as their designation
    status is one of those three."

    The recorder appears in no input schema, so acting as the coordinator is the only
    way to set it; the tally then stays at 0 until the draft is confirmed.

    Design: Corner/entities/pledge_system_fields_are_server_minted_from_headers
    """
    admin = make_admin_headers()
    employer = create_active_employer(
        legal_name="Copperfield Utilities", employee_count=410
    )
    coordinator = create_coordinator(
        employer["id"],
        full_name="Dana Reyes",
        email="dana.reyes@copperfield.example",
        coordinator_role="LEAD",
    )
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )

    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="S-001",
                giving_method="PAYROLL_DEDUCTION",
                gross_amount="240.00",
            ),
            make_coordinator_headers(coordinator["id"]),
        ),
        201,
    )

    assert pledge["recorded_by_coordinator_id"] == coordinator["id"]
    assert pledge["campaign_id"] == campaign["id"]
    assert pledge["designation_status"] == "DRAFT"
    assert pledge["collection_status"] == "PENDING"
    assert_common_fields(pledge, "pledge")
    assert pledge["version"] == 1
    assert pledge["created_at"] == pledge["updated_at"]

    roster, meta = validate_paginated(
        api_client.list_employer_coordinators(employer["id"], admin)
    )
    assert meta["total_count"] == 1
    seated = require_by(roster, "id", coordinator["id"])
    assert seated["recorded_pledge_count"] == 0, (
        "the pledge is still DRAFT, and a draft pledge does not count toward the tally"
    )
    assert seated["status"] == "ACTIVE"

    validate_success(api_client.confirm_pledge(pledge["id"], admin))
    roster_after, _ = validate_paginated(
        api_client.list_employer_coordinators(employer["id"], admin)
    )
    assert require_by(roster_after, "id", coordinator["id"])["recorded_pledge_count"] == 1, (
        "confirmation re-derives the recording coordinator's tally"
    )


def test_a_pledge_that_breaks_its_declared_types_never_reaches_the_campaign_books():
    """PRD 3.3: "The payload carries a `donor_reference` — the employer-side donor
    identifier, 1 to 40 characters, unique within the campaign, and rejected with
    `ERR_DUPLICATE_DONOR_REFERENCE` when it collides with another pledge of the same
    campaign — together with a `giving_method` of `PAYROLL_DEDUCTION`,
    `ONE_TIME_CHECK`, `CREDIT_CARD` or `STOCK_GIFT`, and a `gross_amount` that must be
    strictly greater than zero with at most two decimal places."

    A non-member enum value, a three-decimal amount and a zero amount are all shape
    failures, so each is refused before any campaign state is consulted.

    Design: Corner/entities/create_pledge_with_invalid_enum_giving_method_returns_invalid_request
    """
    admin = make_admin_headers()
    employer = create_active_employer(legal_name="Anchor Bay Foods", employee_count=275)
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )

    rejected = (
        {"donor_reference": "T-001", "giving_method": "BITCOIN", "gross_amount": 100.00},
        {"donor_reference": "T-002", "giving_method": "CREDIT_CARD", "gross_amount": 100.001},
        {"donor_reference": "T-003", "giving_method": "CREDIT_CARD", "gross_amount": 0.00},
    )
    for payload in rejected:
        validate_error(
            api_client.create_pledge(campaign["id"], payload, admin),
            ERR_INVALID_REQUEST,
            400,
        )

    _, meta = validate_paginated(
        api_client.list_pledges(admin, {"campaign_id": campaign["id"]})
    )
    assert meta["total_count"] == 0, "not one of the three refusals created a pledge row"

    reread = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert_money(reread["confirmed_gross_total"], "0.00", "confirmed_gross_total")


def test_an_allocation_request_resolves_both_of_its_body_foreign_keys():
    """PRD 2.9: "Foreign keys supplied inside a request body are resolved the same way
    and raise the same 404 codes: `employer_id`, `campaign_id`, `agency_id`, `cycle_id`,
    `panelist_id`, `request_id`, and the `agency_id` of each element of a `designations`
    array."

    Drafting needs no membership standing — that is checked at submission — so the same
    body with both identifiers real creates the request in `DRAFT`.

    Design: Corner/entities/allocation_request_with_unknown_cycle_fk_returns_cycle_not_found
    """
    admin = make_admin_headers()
    cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="300000.00",
        max_award_per_agency="100000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    agency = create_agency(
        legal_name="Willow Creek Youth Services",
        ein="600000003",
        primary_priority_area="EDUCATION",
    )
    body = {
        "requested_amount": "40000.00",
        "priority_area": "EDUCATION",
        "narrative_summary": "After-school tutoring expansion.",
    }

    validate_error(
        api_client.create_allocation_request(
            allocation_request_payload(NON_EXISTENT_UUID, agency["id"], **body), admin
        ),
        ERR_CYCLE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_allocation_request(
            allocation_request_payload(cycle["id"], OTHER_UNUSED_UUID, **body), admin
        ),
        ERR_AGENCY_NOT_FOUND,
        404,
    )

    drafted = validate_success(
        api_client.create_allocation_request(
            allocation_request_payload(cycle["id"], agency["id"], **body), admin
        ),
        201,
    )
    assert drafted["status"] == "DRAFT"
    assert drafted["cycle_id"] == cycle["id"]
    assert drafted["agency_id"] == agency["id"]
    assert_is_null(drafted["submitted_at"], "submitted_at")

    reread_cycle = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert reread_cycle["submitted_request_count"] == 0, (
        "drafting a request is not submitting it"
    )


def test_one_panelist_seated_on_two_cycles_is_reachable_from_either_side():
    """PRD 3.7: "A volunteer may hold at most one seat per cycle, and a second seating
    attempt is refused with `ERR_DUPLICATE_PANEL_SCORE`."

    The seat is the junction between a cycle and a volunteer, so seating the same
    volunteer on two different cycles must be visible from the volunteer's roster as
    two rows and from each cycle's roster as one.

    Design: Corner/entities/panel_assignment_junction_is_listable_from_both_cycle_and_panelist
    """
    admin = make_admin_headers()
    panelist = create_panelist(
        full_name="Marcus Hale",
        email="marcus.hale@panel.example",
        expertise_area="FINANCE",
    )
    first_cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="200000.00",
        max_award_per_agency="80000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    second_cycle = create_cycle(
        cycle_year=2027,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="200000.00",
        max_award_per_agency="80000.00",
        request_window_start="2027-07-01",
        request_window_end="2027-10-01",
    )
    chair_seat = seat_panelist(
        first_cycle["id"], panelist["id"], conflict_declared=False, assignment_role="CHAIR"
    )
    scorer_seat = seat_panelist(
        second_cycle["id"], panelist["id"], conflict_declared=False, assignment_role="SCORER"
    )

    held, held_meta = validate_paginated(
        api_client.list_panelist_panel_assignments(panelist["id"], admin)
    )
    assert held_meta["total_count"] == 2, "the volunteer holds one seat on each cycle"
    assert {row["id"] for row in held} == {chair_seat["id"], scorer_seat["id"]}
    assert require_by(held, "cycle_id", first_cycle["id"])["id"] == chair_seat["id"]
    assert require_by(held, "cycle_id", second_cycle["id"])["id"] == scorer_seat["id"]

    chaired, chaired_meta = validate_paginated(
        api_client.list_cycle_panel_assignments(
            first_cycle["id"], admin, {"assignment_role": "CHAIR"}
        )
    )
    assert chaired_meta["total_count"] == 1, "the first cycle has exactly one chair"
    assert chaired[0]["id"] == chair_seat["id"]
    assert chaired[0]["assignment_role"] == "CHAIR"
    assert chaired[0]["panelist_id"] == panelist["id"]

    validate_error(
        api_client.create_panel_assignment(
            first_cycle["id"],
            panel_assignment_payload(
                panelist["id"], conflict_declared=False, assignment_role="SCORER"
            ),
            admin,
        ),
        ERR_DUPLICATE_PANEL_SCORE,
        409,
    )

    still_two, still_meta = validate_paginated(
        api_client.list_panelist_panel_assignments(panelist["id"], admin)
    )
    assert still_meta["total_count"] == 2, "the refused seating created nothing"
    for seat in still_two:
        assert seat["submitted_score_count"] == 0, "no score has been filed anywhere yet"
        assert_is_false(seat["conflict_declared"], "conflict_declared")
