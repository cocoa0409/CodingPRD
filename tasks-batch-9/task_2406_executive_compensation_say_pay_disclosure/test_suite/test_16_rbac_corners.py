"""Role authorisation, officer row ownership and segregation of duties.

These tests exercise the access-control layer of the compensation calendar: the
endpoint role lists, the officer's row-scoped ownership check on awards and
determinations, and the three pairs of steps that one `X-User-ID` may never
perform on its own.
"""

from test_helpers import (
    CHAIR_ONE,
    CHAIR_TWO,
    CONSULTANT,
    COUNSEL,
    COUNSEL_ONE,
    COUNSEL_TWO,
    IR_LEAD,
    ApiErrorId,
    adjust_metric,
    api_client,
    approve_peer_group,
    assert_money,
    create_cda_draft,
    create_engagement_payload,
    create_restatement_event_payload,
    create_screen,
    make_comp_committee_chair_headers,
    make_named_executive_officer_headers,
    make_securities_counsel_headers,
    market_data_payload,
    metric_version,
    read_award,
    read_cda_draft,
    read_determination,
    read_metric,
    read_pay_program,
    read_peer_group,
    read_restatement_event,
    setup_award,
    setup_mini_peer_group,
    setup_pay_program,
    setup_restatement_with_determination,
    submit_cda_review,
    submit_metric_result,
    validate_error,
    validate_success,
)


def test_consultant_cannot_approve_the_peer_group_it_screened():
    """The consultant who built and screened a group may not approve it.

    "If the headers are well-formed but the acting role does not appear in the
    authorised-role list of the endpoint being called, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/the_compensation_consultant_cannot_approve_a_peer_group
    """
    env = setup_mini_peer_group(target_status="SCREENED")
    peer_group_id = env["peer_group"]["id"]

    # Creation, the member add and the screen are the group's three mutations.
    assert env["peer_group"]["version"] == 3
    assert env["peer_group"]["status"] == "SCREENED"

    refused = api_client.approve_peer_group(peer_group_id, CONSULTANT)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = read_peer_group(peer_group_id)
    assert unchanged["status"] == "SCREENED"
    assert unchanged["approved_by_user_id"] is None
    assert unchanged["version"] == 3

    approved = approve_peer_group(peer_group_id, CHAIR_ONE)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == CHAIR_ONE
    assert approved["version"] == 4


def test_officer_is_refused_another_officers_award_but_reads_their_own():
    """An award read is scoped to the executive the caller is.

    "Concretely, an officer may read awards only where the award's
    `executive_id` equals their `X-User-ID`, and may read or acknowledge a
    clawback determination only where the determination's award has that same
    `executive_id`."

    Design: Corner/rbac/a_named_executive_officer_cannot_read_another_officers_award
    """
    env = setup_pay_program(approve=False, executive_profiles=("CEO", "CFO"))
    env = setup_award(env, label="ceo_award", executive_label="CEO")
    env = setup_award(env, label="cfo_award", executive_label="CFO")
    ceo_award = env["awards"]["ceo_award"]
    cfo_award = env["awards"]["cfo_award"]
    cfo_headers = make_named_executive_officer_headers(env["executives"]["CFO"]["id"])

    refused = api_client.get_payout_award(ceo_award["id"], cfo_headers)
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    own = validate_success(api_client.get_payout_award(cfo_award["id"], cfo_headers), 200)
    assert own["executive_id"] == env["executives"]["CFO"]["id"]
    # 800,000.00 base times an sti_target_pct of 100.00, divided by 100.
    assert_money(own["target_amount_usd"], 800000.00, "target_amount_usd")

    ceo_seen_by_consultant = read_award(ceo_award["id"])
    assert ceo_seen_by_consultant["executive_id"] == env["executives"]["CEO"]["id"]
    # 1,200,000.00 base times an sti_target_pct of 150.00, divided by 100.
    assert_money(
        ceo_seen_by_consultant["target_amount_usd"], 1800000.00, "target_amount_usd"
    )


def test_authoring_counsel_cannot_legally_clear_the_same_section():
    """Only the acting user id separates authorship from legal clearance.

    "The clearing `X-User-ID` must differ from the section's
    `authored_by_user_id`, or the answer is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_counsel_who_authored_a_section_cannot_legally_clear_it
    """
    env = setup_pay_program()
    program_id = env["program"]["id"]
    create_screen(program_id, "ISS")
    draft = create_cda_draft(
        program_id,
        section_code="CD_AND_A",
        word_count=2000,
        required_tables_included=True,
        author_user_id=COUNSEL_ONE,
    )
    submit_cda_review(draft["id"], COUNSEL_ONE)

    refused = api_client.legal_clear_cda_draft(
        draft["id"], make_securities_counsel_headers(COUNSEL_ONE)
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    still_in_review = read_cda_draft(program_id, draft["id"])
    assert still_in_review["status"] == "IN_REVIEW"
    assert still_in_review["cleared_by_user_id"] is None

    cleared = validate_success(
        api_client.legal_clear_cda_draft(
            draft["id"], make_securities_counsel_headers(COUNSEL_TWO)
        ),
        200,
    )
    assert cleared["status"] == "LEGAL_CLEARED"
    assert cleared["authored_by_user_id"] == COUNSEL_ONE
    assert cleared["cleared_by_user_id"] == COUNSEL_TWO
    # Only filing the CD&A advances the program; clearance leaves it where it was.
    assert read_pay_program(program_id)["design_status"] == "COMMITTEE_APPROVED"


def test_chair_who_adjusted_the_goal_cannot_certify_its_result():
    """The chair who moved a mid-cycle target may not certify the outcome.

    "Certification is refused from any other state with
    `ERR_METRIC_STATE_INVALID`, and refused with `ERR_SEGREGATION_OF_DUTIES`
    when the acting `X-User-ID` equals the metric's `adjusted_by_user_id` — the
    chair who moved a goal may not certify the result measured against it."

    Design: Corner/rbac/the_chair_who_adjusted_a_goal_cannot_certify_its_result
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR",), metric_overrides=[{"weight_pct": 100.00}]
    )
    program_id = env["program"]["id"]
    metric_id = env["metrics"][0]["id"]

    adjusted = adjust_metric(
        metric_id,
        metric_version(program_id, metric_id),
        chair_user_id=CHAIR_ONE,
        target_value=5.50,
    )
    assert adjusted["adjusted_by_user_id"] == CHAIR_ONE
    assert_money(adjusted["locked_target_value"], 5.00, "locked_target_value")
    assert_money(adjusted["target_value"], 5.50, "target_value")
    # |5.50 - 5.00| / |5.00| * 100 == 10.00, inside the 15.00 percent limit.
    assert_money(adjusted["goal_adjustment_pct"], 10.00, "goal_adjustment_pct")

    submit_metric_result(metric_id, 5.50)

    refused = api_client.certify_metric_result(
        metric_id, make_comp_committee_chair_headers(CHAIR_ONE)
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    untouched = read_metric(program_id, metric_id)
    assert untouched["status"] == "RESULT_SUBMITTED"
    assert untouched["certified_by_user_id"] is None

    certified = validate_success(
        api_client.certify_metric_result(
            metric_id, make_comp_committee_chair_headers(CHAIR_TWO)
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == CHAIR_TWO
    # An achievement exactly equal to the adjusted target pays target_payout_pct.
    assert_money(certified["payout_factor_pct"], 100.00, "payout_factor_pct")


def test_acknowledging_identifier_cannot_execute_the_recovery_even_as_chair():
    """The conflict follows the acting user id across the role boundary.

    "Third, the user recorded as a clawback determination's
    `acknowledged_by_user_id` may not execute that determination's recovery."

    Design: Corner/rbac/the_officer_who_acknowledged_a_determination_cannot_execute_its_recovery
    """
    env = setup_restatement_with_determination()
    ceo_id = env["executives"]["CEO"]["id"]
    determination_id = env["determination"]["id"]
    event_id = env["restatement_event"]["id"]
    award_id = env["awards"]["annual_incentive"]["id"]

    assert env["determination"]["status"] == "NOTICED"
    assert env["determination"]["acknowledged_by_user_id"] == ceo_id
    assert_money(
        env["determination"]["recoverable_amount_usd"], 540000.00, "recoverable_amount_usd"
    )

    # The chair role the endpoint requires does not exempt the recorded identifier:
    # "the conflict test is evaluated on the recorded identifier, not on the role."
    refused = api_client.recover_clawback_determination(
        determination_id, make_comp_committee_chair_headers(ceo_id)
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    unchanged = read_determination(determination_id)
    assert unchanged["status"] == "NOTICED"
    assert_money(
        read_restatement_event(env["issuer"]["id"], event_id)["recovered_total_usd"],
        0.00,
        "recovered_total_usd",
    )

    recovered = validate_success(
        api_client.recover_clawback_determination(
            determination_id, make_comp_committee_chair_headers(CHAIR_ONE)
        ),
        200,
    )
    assert recovered["status"] == "RECOVERED"

    event = read_restatement_event(env["issuer"]["id"], event_id)
    assert_money(event["recovered_total_usd"], 540000.00, "recovered_total_usd")
    assert event["status"] == "CLOSED"

    award = read_award(award_id)
    assert award["status"] == "CLAWED_BACK"
    # 2,340,000.00 realized at vest less the 540,000.00 recovered.
    assert_money(award["realized_value_usd"], 1800000.00, "realized_value_usd")


def test_all_five_roles_perform_their_own_exclusive_operation():
    """Each declared role drives an endpoint no other role may call.

    "The `CompConsultant` is the independent adviser: it registers companies and
    officers, refreshes market data, builds and screens peer groups, opens pay
    programs, defines metrics, submits fiscal-year achievements and administers
    awards — and approves nothing."

    Design: Corner/rbac/each_declared_role_performs_its_own_exclusive_operation
    """
    env = setup_pay_program(
        approve=False,
        metric_curves=("ADJ_EPS_LINEAR",),
        metric_overrides=[{"weight_pct": 100.00}],
    )
    env = setup_award(env)
    program_id = env["program"]["id"]
    issuer_id = env["issuer"]["id"]
    metric_id = env["metrics"][0]["id"]
    award_id = env["awards"]["annual_incentive"]["id"]
    ceo_id = env["executives"]["CEO"]["id"]

    # The consultant refreshes market data.
    refreshed = validate_success(
        api_client.refresh_market_data(
            issuer_id, market_data_payload(share_price_usd=55.00), CONSULTANT
        ),
        200,
    )
    assert_money(refreshed["share_price_usd"], 55.00, "share_price_usd")

    # The chair is the only approver, and approval locks every DRAFT metric.
    approved = validate_success(
        api_client.approve_pay_program(
            program_id, make_comp_committee_chair_headers(CHAIR_ONE)
        ),
        200,
    )
    assert approved["design_status"] == "COMMITTEE_APPROVED"
    assert read_metric(program_id, metric_id)["status"] == "LOCKED"

    # Counsel declares the accounting restatement.
    event = validate_success(
        api_client.create_restatement_event(
            issuer_id, create_restatement_event_payload(), COUNSEL
        ),
        201,
    )
    assert event["status"] == "DECLARED"
    assert event["determination_count"] == 0

    # Investor relations runs the shareholder outreach programme.
    engagement = validate_success(
        api_client.create_outreach_engagement(
            program_id,
            create_engagement_payload("BlackRock", 20.00, "MEETING"),
            IR_LEAD,
        ),
        201,
    )
    assert engagement["engagement_status"] == "REQUESTED"

    # The officer inspects their own award.
    own_award = validate_success(
        api_client.get_payout_award(award_id, make_named_executive_officer_headers(ceo_id)),
        200,
    )
    assert own_award["executive_id"] == ceo_id
    assert own_award["status"] == "GRANTED"
