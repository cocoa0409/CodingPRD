"""Role separation — the two exclusive operations, coordinator ownership and the
panel's segregation of duties — together with the two optimistic-concurrency
guards, the inclusive escrow threshold, and the immediacy of every recomputed
ledger.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_OWNERSHIP_VIOLATION,
    ERR_REQUEST_INVALID_STATE,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
)
from test_helpers.assertions import (
    assert_bps,
    assert_gross_decomposition,
    assert_is_null,
    assert_money,
    require_by,
)
from test_helpers.factories import (
    amend_payload,
    award_payload,
    collection_payload,
    designation_line,
    panel_score_payload,
    pledge_payload,
    site_visit_findings_payload,
    site_visit_payload,
    write_off_payload,
)
from test_helpers.fixtures import (
    create_active_employer,
    create_coordinator,
    create_cycle,
    create_good_standing_agency,
    create_open_campaign,
    create_open_cycle,
    create_outcome_report,
    create_panelist,
    create_pledge,
    create_request,
    create_submitted_request,
    current_cycle_version,
    file_score,
    finalize,
    remit,
    seat_panelist,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_agency_rep_headers,
    make_allocations_director_headers,
    make_coordinator_headers,
    make_finance_reviewer_headers,
    make_panelist_headers,
)


def test_only_the_seated_volunteer_may_file_a_score_on_a_request():
    """PRD 3.7: "Scoring is exclusive to a `VolunteerPanelist`."

    PRD 2.10: "Role permission for the requested operation (`ERR_ROLE_NOT_PERMITTED`)."

    PRD 2.1: "Once the caller is authenticated, the role is checked against the set of
    roles the target operation permits; a role outside that set is rejected with
    `ERR_ROLE_NOT_PERMITTED` (403)."

    The `AllocationsDirector` and the `UnitedFundAdmin` own every other allocation
    operation, and both are refused on the identical body the seated volunteer files
    successfully.

    Design: Corner/rbac/panelist_exclusive_score_filing_permitted_while_director_cannot_file_scores
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    agency = create_good_standing_agency(
        legal_name="Rimrock Community Trust",
        ein="630000001",
        primary_priority_area="HEALTH",
    )
    panelist = create_panelist(
        full_name="Rbac Panelist One",
        email="r1.rbac@panel.example",
        expertise_area="HEALTH",
    )
    cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="EDUCATION",
        opening_undesignated_pool="120000.00",
        max_award_per_agency="30000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    seat_panelist(
        cycle["id"], panelist["id"], conflict_declared=False, assignment_role="CHAIR"
    )
    validate_success(api_client.open_allocation_cycle(cycle["id"], director))
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="25000.00",
        priority_area="HEALTH",
        narrative_summary="Dental van staffing.",
    )
    body = panel_score_payload(90, 80, 70)

    validate_error(
        api_client.create_panel_score(request["id"], body, director),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api_client.create_panel_score(request["id"], body, admin),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    filed = validate_success(
        api_client.create_panel_score(
            request["id"], body, make_panelist_headers(panelist["id"])
        ),
        201,
    )

    assert filed["panelist_id"] == panelist["id"], "the author comes from X-User-ID"
    assert_money(filed["weighted_score"], "81.50", "weighted_score")
    assert filed["eligible"] is True

    scores, meta = validate_paginated(api_client.list_request_scores(request["id"], admin))
    assert meta["total_count"] == 1, "the two refused calls filed nothing"

    reread = validate_success(api_client.get_allocation_request(request["id"], admin))
    assert reread["eligible_score_count"] == 1
    assert reread["status"] == "UNDER_PANEL_REVIEW"


def test_the_award_endpoint_checks_the_role_before_the_request_status():
    """PRD 2.1: "The director stewards the community impact fund and is the only role that
    may issue or rescind an award."

    PRD 2.11: "A `FinanceReviewer` certifies agency financial reviews and writes off
    pledges but may never issue an award."

    PRD 2.10: "Checks are evaluated in a fixed ladder, ascending, and the first failure is
    the response."

    The request cited is deliberately still `DRAFT`, so the permitted role is stopped by
    the status gate at 20 while the two unpermitted roles never get past the role gate at
    2 — a 403 rather than the 409 the status alone would produce.

    Design: Corner/rbac/allocations_director_exclusive_award_cannot_be_issued_by_united_fund_admin
    """
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    director = make_allocations_director_headers()
    agency = create_good_standing_agency(
        legal_name="Sandpiper Legal Clinic",
        ein="630000002",
        primary_priority_area="FINANCIAL_STABILITY",
    )
    cycle, _ = create_open_cycle(
        1,
        cycle_year=2026,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="90000.00",
        max_award_per_agency="30000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    request = create_request(
        cycle["id"],
        agency["id"],
        requested_amount="20000.00",
        priority_area="FINANCIAL_STABILITY",
        narrative_summary="Eviction defense hotline.",
    )
    assert request["status"] == "DRAFT"
    version = current_cycle_version(cycle["id"])
    body = award_payload(request["id"], version)

    validate_error(
        api_client.create_award(cycle["id"], body, admin), ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(
        api_client.create_award(cycle["id"], body, finance), ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(
        api_client.create_award(cycle["id"], body, director),
        ERR_REQUEST_INVALID_STATE,
        409,
    )

    reread_request = validate_success(
        api_client.get_allocation_request(request["id"], admin)
    )
    assert reread_request["status"] == "DRAFT"
    assert_is_null(reread_request["total_award"], "total_award")
    assert_is_null(reread_request["awarded_at"], "awarded_at")

    reread_cycle = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert reread_cycle["version"] == version, "three refusals mutated nothing"
    assert_money(
        reread_cycle["available_undesignated_pool"], "90000.00", "available_undesignated_pool"
    )
    assert_money(reread_cycle["awarded_total"], "0.00", "awarded_total")


def test_a_coordinator_may_only_record_pledges_inside_its_own_employer():
    """PRD 2.1: "When `X-User-Role` is `CampaignCoordinator`, `X-User-ID` is the `id` of the
    acting `CampaignCoordinator` row. Ownership checks on any resource that references a
    coordinator compare the resource's coordinator foreign key to `X-User-ID`: the acting
    coordinator must be seated at the employer that hosts the campaign being written to,
    and for writes against an existing pledge the pledge's `recorded_by_coordinator_id`
    must equal `X-User-ID`."

    PRD 2.1: "Any ownership check that fails is rejected with `ERR_OWNERSHIP_VIOLATION`
    (403)."

    PRD 3.3: "When a coordinator records the pledge, `recorded_by_coordinator_id` is
    stamped from `X-User-ID`; the pledge's `campaign_id` is the campaign it was solicited
    inside."

    PRD 3.1: "The coordinator's `recorded_pledge_count` counts the pledges whose
    `recorded_by_coordinator_id` is that coordinator and whose designation status is
    `CONFIRMED`, `AMENDED` or `LOCKED` — draft pledges do not count toward a
    coordinator's tally, and neither do written-off ones as long as their designation
    status is one of those three."

    The role header is identical in both attempts, so only the ownership resolution
    separates them, and the donor reference the refused call carried is still free for the
    call that is entitled to it.

    Design: Corner/rbac/coordinator_of_another_employer_cannot_record_pledge_returns_ownership_violation
    """
    admin = make_admin_headers()
    host_employer = create_active_employer(
        legal_name="Thistle Grove Brewing", employee_count=70
    )
    own_coordinator = create_coordinator(
        host_employer["id"],
        full_name="Coordinator Alpha",
        email="alpha.coord@employer-a.example",
    )
    other_employer = create_active_employer(
        legal_name="Umber Valley Transit", employee_count=90
    )
    other_coordinator = create_coordinator(
        other_employer["id"],
        full_name="Coordinator Bravo",
        email="bravo.coord@employer-b.example",
    )
    _, campaign = create_open_campaign(
        host_employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    body = pledge_payload(
        donor_reference="O-001", giving_method="PAYROLL_DEDUCTION", gross_amount="300.00"
    )

    validate_error(
        api_client.create_pledge(
            campaign["id"], body, make_coordinator_headers(other_coordinator["id"])
        ),
        ERR_OWNERSHIP_VIOLATION,
        403,
    )

    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"], body, make_coordinator_headers(own_coordinator["id"])
        ),
        201,
    )

    assert pledge["recorded_by_coordinator_id"] == own_coordinator["id"], (
        "the stamp comes from X-User-ID and never from the body"
    )
    assert pledge["campaign_id"] == campaign["id"]
    assert pledge["designation_status"] == "DRAFT"

    pledges, meta = validate_paginated(
        api_client.list_pledges(admin, {"campaign_id": campaign["id"]})
    )
    assert meta["total_count"] == 1, "the refused attempt recorded nothing"
    assert pledges[0]["donor_reference"] == "O-001", (
        "the refused call consumed no donor reference"
    )

    coordinators, coordinator_meta = validate_paginated(
        api_client.list_employer_coordinators(host_employer["id"], admin)
    )
    assert coordinator_meta["total_count"] == 1
    assert require_by(coordinators, "id", own_coordinator["id"])[
        "recorded_pledge_count"
    ] == 0, "a DRAFT pledge counts toward no coordinator's tally"

    draft_campaign = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert_money(draft_campaign["confirmed_gross_total"], "0.00", "confirmed_gross_total")

    validate_success(
        api_client.confirm_pledge(
            pledge["id"], make_coordinator_headers(own_coordinator["id"])
        )
    )

    host_seats, _ = validate_paginated(
        api_client.list_employer_coordinators(host_employer["id"], admin)
    )
    assert require_by(host_seats, "id", own_coordinator["id"])[
        "recorded_pledge_count"
    ] == 1, "confirmation is what folds the pledge into the recording coordinator's tally"

    other_seats, _ = validate_paginated(
        api_client.list_employer_coordinators(other_employer["id"], admin)
    )
    assert require_by(other_seats, "id", other_coordinator["id"])[
        "recorded_pledge_count"
    ] == 0, "the refused coordinator never recorded anything"


def test_a_scorer_may_not_monitor_the_request_it_judged():
    """PRD 2.11: "And a `VolunteerPanelist` who filed a score against an allocation request
    may never conduct the monitoring site visit on that same request's outcome report; the
    attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

    PRD 3.9: "First, segregation of duties: the acting volunteer must have filed no score at
    all against the request this report accounts for, and a scorer's attempt is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.9: "Only the volunteer who scheduled the visit may complete it: `X-User-ID` must
    equal the report's `site_visit_panelist_id`, and anyone else is refused with
    `ERR_OWNERSHIP_VIOLATION`."

    The refused scorer and the accepted monitor hold identical seats on the same cycle and
    send the identical window, so only the score they did or did not file separates them.

    Design: Corner/rbac/site_visit_by_the_panelist_who_scored_the_request_returns_segregation_of_duties
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    agency = create_good_standing_agency(
        legal_name="Verity House", ein="630000003", primary_priority_area="BASIC_NEEDS"
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
    scorers, monitor = panelists[:3], panelists[3]
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="80000.00",
        priority_area="BASIC_NEEDS",
        narrative_summary="Transitional housing case management.",
    )
    for panelist in scorers:
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
    validate_success(
        api_client.create_award(
            cycle["id"],
            award_payload(request["id"], current_cycle_version(cycle["id"])),
            director,
        )
    )
    awarded = validate_success(api_client.get_allocation_request(request["id"], admin))
    assert_money(awarded["total_award"], "67156.00", "total_award")

    report = create_outcome_report(
        request["id"],
        agency["id"],
        reporting_period_end="2026-07-31",
        persons_served=260,
        outcome_metric_name="households_rehoused",
        outcome_metric_value="84",
        funds_expended="67156.00",
    )
    assert_money(
        report["expenditure_variance_pct"], "0.00", "expenditure_variance_pct"
    )
    assert validate_success(api_client.get_allocation_request(request["id"], admin))[
        "status"
    ] == "REPORTING"

    window = site_visit_payload("2026-08-10", "2026-08-20")
    scorer_headers = make_panelist_headers(scorers[0]["id"])

    validate_error(
        api_client.schedule_site_visit(report["id"], window, scorer_headers),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    scheduled = validate_success(
        api_client.schedule_site_visit(
            report["id"], window, make_panelist_headers(monitor["id"])
        )
    )
    assert scheduled["status"] == "SITE_VISIT_SCHEDULED"
    assert scheduled["site_visit_panelist_id"] == monitor["id"]

    validate_error(
        api_client.complete_site_visit(
            report["id"], site_visit_findings_payload(), scorer_headers
        ),
        ERR_OWNERSHIP_VIOLATION,
        403,
    )

    still_scheduled = validate_success(api_client.get_outcome_report(report["id"], admin))
    assert still_scheduled["status"] == "SITE_VISIT_SCHEDULED"
    assert_is_null(still_scheduled["site_visit_findings"], "site_visit_findings")

    refused_scorer = validate_success(api_client.get_panelist(scorers[0]["id"], admin))
    assert refused_scorer["site_visit_count"] == 0
    assert refused_scorer["submitted_score_count"] == 1
    accepted_monitor = validate_success(api_client.get_panelist(monitor["id"], admin))
    assert accepted_monitor["site_visit_count"] == 1
    assert accepted_monitor["submitted_score_count"] == 0


def test_replaying_an_amendment_from_the_pre_amend_version_is_stale_not_unconfirmed():
    """PRD 2.6: "Amending the designation lines of a pledge requires a non-optional
    `expected_pledge_version` field carrying the client's last observed `version` of the
    target `Pledge`."

    PRD 2.6: "If that value does not equal the pledge's current `version`, the amendment is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    PRD 2.4: "The `version` of a freshly created resource starts at 1 and increments by
    exactly one on every mutation of that resource, including mutations the server performs
    on its own initiative — a cascade that flips a child's status, a recomputed aggregate,
    a stamped timestamp."

    PRD 2.6: "Two write operations touch a parent whose state the client must have observed
    before deciding, and both are guarded by optimistic concurrency control on that parent's
    `version`."

    The replay would also fail the designation-status gate, because the first amendment
    left the pledge `AMENDED`; the concurrency gate at 8 outranks the status gate at 13, so
    the answer is 412 and not the 409 of `ERR_PLEDGE_NOT_CONFIRMED`.

    Design: Corner/complexity_layers/optimistic_concurrency_stale_expected_pledge_version_on_designation_amend
    """
    admin = make_admin_headers()
    agency = create_good_standing_agency(
        legal_name="Waverly Reading Project",
        ein="640000001",
        primary_priority_area="EDUCATION",
    )
    employer = create_active_employer(
        legal_name="Kingfisher Software", employee_count=130
    )
    _, campaign = create_open_campaign(
        employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    pledge = create_pledge(
        campaign["id"],
        donor_reference="V-001",
        giving_method="ONE_TIME_CHECK",
        gross_amount="500.00",
        designations=[designation_line(agency["id"], "100.00")],
    )
    assert pledge["version"] == 1, "a freshly created resource starts at version 1"

    confirmed = validate_success(api_client.confirm_pledge(pledge["id"], admin))
    assert confirmed["version"] == 2, "confirmation is one mutation of the pledge"
    stale_version = confirmed["version"]

    new_lines = [
        designation_line(agency["id"], "200.00"),
        designation_line(agency["id"], "50.00"),
    ]
    amended = validate_success(
        api_client.amend_pledge_designations(
            pledge["id"], amend_payload(stale_version, new_lines), admin
        )
    )

    assert amended["version"] == 3
    assert amended["designation_status"] == "AMENDED"
    assert_money(amended["designated_amount_total"], "250.00", "designated_amount_total")
    assert_money(amended["designation_fee_total"], "18.13", "designation_fee_total")
    assert_money(amended["net_designated_total"], "231.87", "net_designated_total")
    assert_money(amended["undesignated_amount"], "250.00", "undesignated_amount")
    assert_gross_decomposition(amended)

    replay = api_client.amend_pledge_designations(
        pledge["id"], amend_payload(stale_version, new_lines), admin
    )
    validate_error(replay, ERR_STALE_VERSION, 412)

    unchanged = validate_success(api_client.get_pledge(pledge["id"], admin))
    assert unchanged["version"] == 3, "the refused replay was not a mutation"
    assert unchanged["amend_count"] == 1
    assert unchanged["designation_status"] == "AMENDED"

    active, active_meta = validate_paginated(
        api_client.list_pledge_designations(pledge["id"], admin, {"status": "ACTIVE"})
    )
    assert active_meta["total_count"] == 2, "the new line set is two lines wide"
    assert_money(
        require_by(active, "designation_sequence", 1)["processing_fee"],
        "14.50",
        "line 1 processing_fee",
    )
    assert_money(
        require_by(active, "designation_sequence", 2)["processing_fee"],
        "3.63",
        "line 2 processing_fee",
    )

    superseded, superseded_meta = validate_paginated(
        api_client.list_pledge_designations(pledge["id"], admin, {"status": "SUPERSEDED"})
    )
    assert superseded_meta["total_count"] == 1, "the 100.00 line is superseded, not deleted"
    assert_money(
        superseded[0]["collected_designated_amount"], "0.00", "superseded line collected"
    )


def test_the_cycle_version_read_before_opening_is_already_stale_at_award_time():
    """PRD 2.6: "Issuing an award requires a non-optional
    `expected_allocation_cycle_version` field carrying the client's last observed `version`
    of the target `AllocationCycle`."

    PRD 2.6: "Awards draw from a shared pool, so any prior award, rescission, posture
    change or pool recomputation on that cycle invalidates the balance the director based
    the decision on."

    PRD 2.6: "As with the amendment, the cycle's state machine would happily accept the
    second award on its own merits — only the version check refuses it."

    The first leg carries the version read while the cycle was still `DRAFT` and is refused
    even though the request is legitimately `PANEL_APPROVED` and the pool is ample; the
    replay of the successful leg is refused for the same reason rather than for the request
    now being `AWARDED`, because the concurrency gate at 8 precedes the status gate at 20.

    Design: Corner/complexity_layers/optimistic_concurrency_stale_expected_allocation_cycle_version_on_award
    """
    admin = make_admin_headers()
    director = make_allocations_director_headers()
    agency = create_good_standing_agency(
        legal_name="Yarrow Field Nutrition",
        ein="640000002",
        primary_priority_area="BASIC_NEEDS",
    )
    cycle = create_cycle(
        cycle_year=2026,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="200000.00",
        max_award_per_agency="60000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    draft_version = cycle["version"]
    assert draft_version == 1, "the cycle is created at version 1"
    panelists = [
        create_panelist(
            full_name=f"Occ Panelist {label}",
            email=f"{label.lower()}.occ@panel.example",
            expertise_area=area,
        )
        for label, area in (
            ("One", "BASIC_NEEDS"),
            ("Two", "HEALTH"),
            ("Three", "EDUCATION"),
        )
    ]
    seat_panelist(
        cycle["id"], panelists[0]["id"], conflict_declared=False, assignment_role="CHAIR"
    )
    for panelist in panelists[1:]:
        seat_panelist(cycle["id"], panelist["id"], conflict_declared=False)
    opened = validate_success(api_client.open_allocation_cycle(cycle["id"], director))
    assert opened["posture"] == "OPEN"
    assert opened["version"] > draft_version, "opening the cycle advanced the OCC field"

    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="40000.00",
        priority_area="BASIC_NEEDS",
        narrative_summary="Weekend meal packs for six schools.",
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

    validate_error(
        api_client.create_award(
            cycle["id"], award_payload(request["id"], draft_version), director
        ),
        ERR_STALE_VERSION,
        412,
    )
    assert validate_success(api_client.get_allocation_request(request["id"], admin))[
        "status"
    ] == "PANEL_APPROVED", "the stale award moved nothing"

    fresh_version = current_cycle_version(cycle["id"])
    assert fresh_version != draft_version, "the DRAFT-era version is no longer current"
    validate_success(
        api_client.create_award(
            cycle["id"], award_payload(request["id"], fresh_version), director
        )
    )

    awarded = validate_success(api_client.get_allocation_request(request["id"], admin))
    assert awarded["status"] == "AWARDED"
    assert_money(awarded["base_award"], "32600.00", "base_award")
    assert_money(awarded["designation_offset"], "0.00", "designation_offset")
    assert_money(awarded["strategic_supplement"], "1956.00", "strategic_supplement")
    assert_money(awarded["total_award"], "34556.00", "total_award")

    validate_error(
        api_client.create_award(
            cycle["id"], award_payload(request["id"], fresh_version), director
        ),
        ERR_STALE_VERSION,
        412,
    )

    final_cycle = validate_success(api_client.get_allocation_cycle(cycle["id"], admin))
    assert final_cycle["version"] > fresh_version, "the successful award was a mutation"
    assert_money(final_cycle["awarded_total"], "34556.00", "awarded_total")
    assert_money(
        final_cycle["available_undesignated_pool"], "165444.00", "available_undesignated_pool"
    )


def _shrinkage_campaign(legal_name, collected_amount, written_off_amount, prefix):
    """One campaign closed for solicitation, one pledge paid and one written off."""
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    employer = create_active_employer(legal_name=legal_name, employee_count=60)
    _, campaign = create_open_campaign(
        employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
        loss_reserve_amount="0.00",
    )
    paid = create_pledge(
        campaign["id"],
        donor_reference=f"{prefix}-001",
        giving_method="ONE_TIME_CHECK",
        gross_amount=collected_amount,
    )
    validate_success(api_client.confirm_pledge(paid["id"], admin))
    remit(paid["id"], collected_amount)
    lost = create_pledge(
        campaign["id"],
        donor_reference=f"{prefix}-002",
        giving_method="PAYROLL_DEDUCTION",
        gross_amount=written_off_amount,
    )
    validate_success(api_client.confirm_pledge(lost["id"], admin))
    validate_success(
        api_client.write_off_pledge(lost["id"], write_off_payload("TERMINATION"), finance)
    )
    validate_success(api_client.close_campaign_solicitation(campaign["id"], admin))
    return employer, campaign, lost


def test_the_escrow_fork_is_inclusive_at_exactly_fifteen_hundred_basis_points():
    """PRD 3.5: "Finally, `realized_shrinkage_rate_bps` expresses the final loss as basis
    points of confirmed gross: it is `final_actual_loss` divided by `confirmed_gross_total`,
    multiplied by 10000, rounded half up to zero decimal places — or exactly 0 when
    `confirmed_gross_total` is zero."

    PRD 3.5: "When `realized_shrinkage_rate_bps` is strictly less than 1500 — that is, under
    15 percent of confirmed gross — the campaign lands in the ordinary terminal posture
    `SOLICITATION_CLOSED → RECONCILED` and nothing further happens."

    PRD 3.5: "When it is 1500 or more, the boundary value 1500 itself counting as severe,
    the campaign lands in `SOLICITATION_CLOSED → ESCROW_HOLD` and the escrow-hold cascade
    fires: the host employer is forced `ACTIVE → SUSPENDED` with `suspended_reason` set to
    `ESCROW_HOLD_SHRINKAGE`, and every coordinator seated at that employer flips
    `ACTIVE → INACTIVE`."

    One dollar of loss on the same 2000.00 confirmed base separates 1495 basis points from
    exactly 1500, and only the second campaign's employer is suspended.

    Design: Corner/complexity_layers/shrinkage_escrow_threshold_at_exactly_fifteen_hundred_bps_forks_to_escrow_hold
    """
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    under_employer, under_campaign, under_lost = _shrinkage_campaign(
        "Zephyr Marine Supply", "1701.00", "299.00", "EA"
    )
    at_employer, at_campaign, at_lost = _shrinkage_campaign(
        "Alcove Ceramics", "1700.00", "300.00", "EB"
    )

    under = validate_success(api_client.reconcile_campaign(under_campaign["id"], finance))

    assert_money(under["confirmed_gross_total"], "2000.00", "confirmed_gross_total")
    assert_money(under["reserve_absorbed_amount"], "0.00", "reserve_absorbed_amount")
    assert_money(under["final_actual_loss"], "299.00", "final_actual_loss")
    assert_bps(under["realized_shrinkage_rate_bps"], 1495, "realized_shrinkage_rate_bps")
    assert under["posture"] == "RECONCILED"
    assert_money(
        under["final_net_expected_revenue"], "1701.00", "final_net_expected_revenue"
    )

    at_bound = validate_success(api_client.reconcile_campaign(at_campaign["id"], finance))

    assert_money(at_bound["confirmed_gross_total"], "2000.00", "confirmed_gross_total")
    assert_money(at_bound["reserve_absorbed_amount"], "0.00", "reserve_absorbed_amount")
    assert_money(at_bound["final_actual_loss"], "300.00", "final_actual_loss")
    assert_bps(at_bound["realized_shrinkage_rate_bps"], 1500, "realized_shrinkage_rate_bps")
    assert at_bound["posture"] == "ESCROW_HOLD", (
        "the boundary value 1500 itself counts as severe, so this is not RECONCILED"
    )
    assert_money(
        at_bound["final_net_expected_revenue"], "1700.00", "final_net_expected_revenue"
    )

    assert validate_success(api_client.get_employer(under_employer["id"], admin))[
        "status"
    ] == "ACTIVE", "the reconciled campaign fires no cascade"
    suspended = validate_success(api_client.get_employer(at_employer["id"], admin))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspended_reason"] == "ESCROW_HOLD_SHRINKAGE"

    under_pledge = validate_success(api_client.get_pledge(under_lost["id"], admin))
    assert under_pledge["collection_status"] == "WRITTEN_OFF"
    assert_money(under_pledge["uncollected_amount"], "299.00", "uncollected_amount")
    at_pledge = validate_success(api_client.get_pledge(at_lost["id"], admin))
    assert at_pledge["collection_status"] == "WRITTEN_OFF"
    assert_money(at_pledge["uncollected_amount"], "300.00", "uncollected_amount")


def test_every_recomputed_ledger_is_readable_on_the_very_next_call():
    """PRD 2.4: "Because aggregates are stored rather than computed on read, the reader
    should expect a single business action to advance several `version` counters at once."

    PRD 3.3: "Either way, confirmation re-derives the campaign's `confirmed_gross_total`,
    `designated_gross_total`, `undesignated_gross_total` and `designation_fee_total`,
    re-derives the recording coordinator's `recorded_pledge_count`, and re-derives
    `designated_passthrough_ytd` for every agency the pledge designates."

    PRD 3.5: "Every agency holding an `ACTIVE` line of the pledge then has its
    `designated_passthrough_ytd` re-derived, that figure being the sum of
    `collected_designated_amount` over all `ACTIVE` designation lines pointing at that
    agency, across every campaign."

    Each response already carries the figures its own action produced, and the neighbouring
    ledger reads its new value on the first call that follows — no second read is needed
    anywhere to observe a settled value.

    Design: Corner/consistency_model/immediate_visibility_of_recomputed_campaign_and_agency_ledgers_in_same_request
    """
    admin = make_admin_headers()
    finance = make_finance_reviewer_headers()
    agency = create_good_standing_agency(
        legal_name="Bramble Court Hospice",
        ein="640000003",
        primary_priority_area="HEALTH",
    )
    employer = create_active_employer(
        legal_name="Cormorant Freight", employee_count=110
    )
    coordinator = create_coordinator(
        employer["id"],
        full_name="Coordinator Charlie",
        email="charlie.coord@cormorant.example",
    )
    _, campaign = create_open_campaign(
        employer["id"],
        campaign_year=2026,
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    coordinator_headers = make_coordinator_headers(coordinator["id"])

    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="IM-001",
                giving_method="PAYROLL_DEDUCTION",
                gross_amount="400.00",
                designations=[designation_line(agency["id"], "300.00")],
            ),
            coordinator_headers,
        ),
        201,
    )

    assert_money(pledge["designated_amount_total"], "300.00", "designated_amount_total")
    assert_money(pledge["designation_fee_total"], "21.75", "designation_fee_total")
    assert_money(pledge["net_designated_total"], "278.25", "net_designated_total")
    assert_money(pledge["undesignated_amount"], "100.00", "undesignated_amount")
    assert_gross_decomposition(pledge)

    seats, _ = validate_paginated(
        api_client.list_employer_coordinators(employer["id"], admin)
    )
    assert require_by(seats, "id", coordinator["id"])["recorded_pledge_count"] == 0, (
        "a DRAFT pledge is in nobody's tally yet"
    )

    confirmed = validate_success(
        api_client.confirm_pledge(pledge["id"], coordinator_headers)
    )
    assert confirmed["designation_status"] == "CONFIRMED"

    campaign_after_confirm = validate_success(
        api_client.get_campaign(campaign["id"], coordinator_headers)
    )
    assert_money(
        campaign_after_confirm["confirmed_gross_total"], "400.00", "confirmed_gross_total"
    )
    assert_money(
        campaign_after_confirm["designated_gross_total"], "300.00", "designated_gross_total"
    )
    assert_money(
        campaign_after_confirm["undesignated_gross_total"],
        "100.00",
        "undesignated_gross_total",
    )
    assert_money(
        campaign_after_confirm["designation_fee_total"], "21.75", "designation_fee_total"
    )

    seats_after_confirm, _ = validate_paginated(
        api_client.list_employer_coordinators(employer["id"], admin)
    )
    assert require_by(seats_after_confirm, "id", coordinator["id"])[
        "recorded_pledge_count"
    ] == 1, "the confirming call is what the coordinator listing already reflects"

    collected = validate_success(
        api_client.create_collection(
            pledge["id"], collection_payload("400.00", "2026-08-05"), finance
        )
    )

    assert collected["collection_status"] == "COLLECTED"
    assert_money(collected["collected_amount"], "400.00", "collected_amount")
    assert_money(collected["uncollected_amount"], "0.00", "uncollected_amount")

    agency_after_collection = validate_success(
        api_client.get_agency(agency["id"], make_agency_rep_headers(agency["id"]))
    )
    assert_money(
        agency_after_collection["designated_passthrough_ytd"],
        "278.25",
        "designated_passthrough_ytd",
    )
