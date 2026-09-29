"""Endpoint corners: the computed pay-for-performance read, the restatement
fan-out, junction-endpoint reference resolution, the remediation coverage gate
and the pay-program collection filter.

Each test drives one endpoint the PRD declares and asserts exactly what that
endpoint is specified to return: the alignment projection for a single program,
one clawback determination per over-paid in-scope award, the not-found error of
the first unresolved identifier, the outreach floor that gates remediation, and
the filtered `total_count` of the pay-program listing.
"""

from test_helpers import (
    CHAIR,
    CONSULTANT,
    COUNSEL,
    IR_LEAD,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_member_payload,
    analyze_payload,
    api_client,
    assert_money,
    assert_clawback_determination,
    carry_cda_draft_to_filed,
    certify_metric,
    certify_vote,
    create_award,
    create_company,
    create_engagement,
    create_pay_program,
    create_peer_group,
    create_restatement_event,
    create_screen,
    hold_engagement,
    peer_group_version,
    read_cda_draft,
    read_metric,
    read_pay_program,
    read_peer_group,
    remediation_payload,
    restated_metric_result,
    run_engagement_to_held,
    schedule_engagement,
    set_clock,
    settle_award,
    setup_award,
    setup_issuer,
    setup_pay_program,
    submit_metric_result,
    read_restatement_event,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_pay_for_performance_read_projects_the_stored_program_alignment_fields():
    """The computed read is a projection of stored state, not a second derivation.

    PRD: "Otherwise, count the `ACCEPTED` peers whose disclosed `ceo_tdc_usd` is
    **strictly less** than the program's `realized_pay_total_usd`, divide that
    count by the number of `ACCEPTED` peers, multiply by 100 and round half-up to
    two decimal places to obtain `pay_percentile_rank`."

    PRD: "A dedicated computed read returns this whole picture for a single
    program: `realized_pay_total_usd`, `realizable_pay_total_usd`,
    `pay_percentile_rank`, `tsr_percentile_rank`, `degree_of_alignment`,
    `alignment_status` and `accepted_peer_count`."

    Design: Corner/endpoints/the_pay_for_performance_computed_read_matches_the_stored_program_fields
    """
    env = setup_pay_program(approve=False)
    env = setup_award(env, label="psu", vehicle="LONG_TERM_PSU")
    program_id = env["program"]["id"]

    picture = validate_success(api_client.get_pay_for_performance(program_id, CHAIR), 200)

    # Nothing has vested, so nothing has been delivered.
    assert_money(picture["realized_pay_total_usd"], 0.00, "realized_pay_total_usd")
    # 100,000 units marked at the issuer's current 50.00 at the assumed 100.00 percent.
    assert_money(picture["realizable_pay_total_usd"], 5000000.00, "realizable_pay_total_usd")
    # BRVO's disclosed 12,000,000.00 is not strictly below a realized total of 0.00.
    assert_money(picture["pay_percentile_rank"], 0.00, "pay_percentile_rank")
    assert_money(picture["tsr_percentile_rank"], 30.00, "tsr_percentile_rank")
    assert_money(picture["degree_of_alignment"], 30.00, "degree_of_alignment")
    assert picture["alignment_status"] == "ALIGNED"
    assert picture["accepted_peer_count"] == 1

    program = read_pay_program(program_id)
    for field in (
        "realized_pay_total_usd",
        "realizable_pay_total_usd",
        "pay_percentile_rank",
        "tsr_percentile_rank",
        "degree_of_alignment",
        "alignment_status",
    ):
        assert picture[field] == program[field], (
            f"the computed read must report the stored {field}: "
            f"{picture[field]} versus {program[field]}"
        )


def test_analyze_writes_one_determination_per_over_paid_in_scope_award():
    """One analyze call fans out over every in-scope award and sizes each recovery.

    PRD: "A determination row is created, in status `CALCULATED`, only for awards
    whose `recoverable_amount_usd` is strictly greater than 0.00; awards yielding
    exactly 0.00 produce no row at all."

    PRD: "The event's `determination_count` is the number of rows created and its
    `recoverable_total_usd` is the sum of their recoverable amounts, rounded to
    two decimal places."

    Design: Corner/endpoints/analyze_creates_one_determination_per_over_paid_in_scope_award
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR", "COST_RATIO_STEP"),
        executive_profiles=("CEO", "CFO"),
        approve=True,
    )
    program_id = env["program"]["id"]
    adj_eps, cost_ratio = env["metrics"]

    submit_metric_result(adj_eps["id"], 5.50)
    submit_metric_result(cost_ratio["id"], 0.63)
    certify_metric(adj_eps["id"])
    certify_metric(cost_ratio["id"])

    ceo_award = create_award(program_id, env["executives"]["CEO"]["id"], "ANNUAL_INCENTIVE")
    cfo_award = create_award(program_id, env["executives"]["CFO"]["id"], "ANNUAL_INCENTIVE")

    set_clock("2026-10-01T00:00:00Z")
    settle_award(ceo_award["id"], "VEST", "2026-09-30T00:00:00Z")
    settle_award(cfo_award["id"], "VEST", "2026-09-30T00:00:00Z")

    event = create_restatement_event(env["issuer"]["id"])

    analyzed = validate_success(
        api_client.analyze_restatement_event(
            event["id"],
            analyze_payload([restated_metric_result(adj_eps["id"], 5.00)]),
            COUNSEL,
        ),
        200,
    )
    assert analyzed["status"] == "ANALYZED"

    reread_event = read_restatement_event(env["issuer"]["id"], event["id"])
    assert reread_event["determination_count"] == 2
    assert_money(reread_event["recoverable_total_usd"], 780000.00, "recoverable_total_usd")

    rows, meta = validate_paginated(
        api_client.list_clawback_determinations(
            COUNSEL, {"restatement_event_id": event["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    by_award = {row["payout_award_id"]: row for row in rows}
    assert set(by_award) == {ceo_award["id"], cfo_award["id"]}

    # The blended factor drops from 130.00 to 100.00 for both awards.
    ceo_determination = by_award[ceo_award["id"]]
    assert_clawback_determination(ceo_determination)
    assert ceo_determination["status"] == "CALCULATED"
    assert_money(ceo_determination["original_factor_pct"], 130.00, "original_factor_pct")
    assert_money(ceo_determination["restated_factor_pct"], 100.00, "restated_factor_pct")
    assert_money(ceo_determination["restated_amount_usd"], 1800000.00, "restated_amount_usd")
    assert_money(
        ceo_determination["recoverable_amount_usd"], 540000.00, "recoverable_amount_usd"
    )

    cfo_determination = by_award[cfo_award["id"]]
    assert_clawback_determination(cfo_determination)
    assert cfo_determination["status"] == "CALCULATED"
    assert_money(cfo_determination["restated_amount_usd"], 800000.00, "restated_amount_usd")
    assert_money(
        cfo_determination["recoverable_amount_usd"], 240000.00, "recoverable_amount_usd"
    )

    assert read_metric(program_id, adj_eps["id"])["status"] == "RESTATED"
    assert read_metric(program_id, cost_ratio["id"])["status"] == "CERTIFIED", (
        "a metric the request did not name keeps its current reading"
    )


def test_adding_a_member_resolves_the_path_group_before_the_body_company():
    """The junction endpoint resolves both endpoints of the association first.

    PRD: "The first identifier in the path that does not resolve to an existing
    row determines the 404 that is returned, and no rule further right is
    evaluated."

    PRD: "Foreign keys supplied in a request body are resolved after every path
    identifier has resolved, and among themselves in the order the endpoint's
    input list declares them: `peer_company_id`, `peer_group_id`,
    `ceo_executive_id`, `executive_id` and `payout_award_id` each raise the
    not-found error of the entity they point at."

    Design: Corner/endpoints/adding_a_member_requires_both_sides_of_the_link_to_exist
    """
    env = setup_issuer()
    bravo = create_company("BRVO")
    group = create_peer_group(env["issuer"]["id"])
    guard = peer_group_version(group["id"])

    validate_error(
        api_client.add_peer_group_member(
            NON_EXISTENT_UUID,
            add_member_payload(bravo["id"], guard, "SIZE_MATCH"),
            CONSULTANT,
        ),
        ApiErrorId.ERR_PEER_GROUP_NOT_FOUND,
        404,
    )

    validate_error(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(NON_EXISTENT_UUID, guard, "SIZE_MATCH"),
            CONSULTANT,
        ),
        ApiErrorId.ERR_COMPANY_NOT_FOUND,
        404,
    )

    member = validate_success(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(bravo["id"], guard, "SIZE_MATCH"),
            CONSULTANT,
        ),
        201,
    )
    assert member["peer_group_id"] == group["id"]
    assert member["peer_company_id"] == bravo["id"]
    assert read_peer_group(group["id"])["version"] == 2, (
        "only the successful link may bump the group's version"
    )


def test_remediation_is_refused_below_the_coverage_floor_and_accepted_once_it_is_reached():
    """Remediation is gated on the live coverage aggregate, not on a flag.

    PRD: "Remediation is refused on any program whose `vote_status` is not
    `FAILED`, with `ERR_VOTE_NOT_FAILED`, and — the substantive gate — it requires
    that the committee have actually engaged holders of at least 30.00 percent of
    shares outstanding: an `outreach_coverage_pct` below 30.00 is refused with
    `ERR_OUTREACH_COVERAGE_INSUFFICIENT`."

    Design: Corner/endpoints/remediation_is_rejected_below_the_coverage_floor_and_accepted_once_outreach_reaches_it
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR",),
        metric_overrides=[{"weight_pct": 100.00}],
        approve=True,
    )
    program_id = env["program"]["id"]

    run_engagement_to_held(
        program_id, "BlackRock", 20.00, "2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z"
    )
    vanguard = create_engagement(program_id, "Vanguard", 11.00, "MEETING")
    schedule_engagement(vanguard["id"], "2027-03-02T00:00:00Z", "2027-03-06T00:00:00Z")

    create_screen(program_id, "ISS", IR_LEAD)
    cda = carry_cda_draft_to_filed(program_id)
    certify_vote(program_id, 400000, 600000)

    failed = read_pay_program(program_id)
    assert failed["vote_status"] == "FAILED"
    assert_money(failed["outreach_coverage_pct"], 20.00, "outreach_coverage_pct")

    validate_error(
        api_client.remediate_pay_program(program_id, remediation_payload(), CHAIR),
        ApiErrorId.ERR_OUTREACH_COVERAGE_INSUFFICIENT,
        422,
    )

    hold_engagement(vanguard["id"], "CONCERNED", IR_LEAD)
    assert_money(
        read_pay_program(program_id)["outreach_coverage_pct"], 31.00, "outreach_coverage_pct"
    )

    remediated = validate_success(
        api_client.remediate_pay_program(program_id, remediation_payload(), CHAIR), 200
    )
    assert remediated["vote_status"] == "REMEDIATED"
    assert remediated["design_status"] == "CLOSED"
    assert read_cda_draft(program_id, cda["id"])["status"] == "FILED", (
        "remediation does not reopen the filed disclosure"
    )


def test_listing_pay_programs_narrows_the_total_count_by_design_status():
    """The declared filter narrows the counted result set, not merely the page.

    PRD: "Programs can be listed with filters on `issuer_company_id`,
    `peer_group_id`, `ceo_executive_id`, `design_status` and `vote_status`, which
    is the practical way to find, say, every program that has been disclosed but
    not yet voted."

    PRD: "The response `meta` object of a list response carries `limit`,
    `offset`, `total_count` and `has_more`, where `total_count` is the size of the
    filtered result set before the window is applied."

    Design: Corner/endpoints/listing_pay_programs_filters_by_design_status
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR",),
        metric_overrides=[{"weight_pct": 100.00}],
        approve=True,
    )
    approved_id = env["program"]["id"]
    draft = create_pay_program(
        env["issuer"]["id"],
        env["peer_group"]["id"],
        env["ceo"]["id"],
        fiscal_year=2027,
        meeting_date="2028-05-10T00:00:00Z",
    )

    filtered, filtered_meta = validate_paginated(
        api_client.list_pay_programs(
            CONSULTANT,
            {
                "issuer_company_id": env["issuer"]["id"],
                "design_status": "DRAFT",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert filtered_meta["total_count"] == 1
    assert [row["id"] for row in filtered] == [draft["id"]]
    assert filtered_meta["has_more"] is False
    assert filtered_meta["limit"] == 10
    assert filtered_meta["offset"] == 0

    everything, everything_meta = validate_paginated(
        api_client.list_pay_programs(
            CONSULTANT,
            {"issuer_company_id": env["issuer"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert everything_meta["total_count"] == 2
    assert {row["id"] for row in everything} == {approved_id, draft["id"]}
    assert read_pay_program(approved_id)["design_status"] == "COMMITTEE_APPROVED"
    assert read_pay_program(draft["id"])["design_status"] == "DRAFT"
