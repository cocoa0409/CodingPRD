"""Thresholds tested one unit either side of the boundary."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    append_good_faith_entry,
    assert_settlement_conservation,
    create_fee_settlement_payload,
    create_subscriber_report,
    declare_impasse_payload,
    read_negotiation,
    setup_executed_agreement,
    setup_impasse_ready,
    validate_error,
    validate_success,
)

SECOND_PERIOD = {
    "period_label": "2027-02",
    "period_start_utc": "2027-02-01T00:00:00Z",
    "period_end_utc": "2027-03-01T00:00:00Z",
}


def test_penetration_shortfall_of_exactly_fifty_basis_points_is_free(api):
    """A shortfall landing exactly on the grace band yields no penalty.

    PRD §3.9: "A shortfall of at most 50 basis points falls inside an inclusive grace
    band and yields a `penetration_penalty_cents` of 0 - being exactly half a
    percentage point short is free."

    Design: Difficulty/boundary_precision_check/penetration_shortfall_grace_band_exactly_fifty_basis_points
    """
    ctx = setup_executed_agreement(report={"reported_subscriber_count": 99600})

    response = api.create_fee_settlement(
        ctx["agreement"]["id"],
        create_fee_settlement_payload(ctx["report"]["id"]),
        TEST_USERS["group_counsel_headers"],
    )
    settlement = validate_success(response, 201)

    assert settlement["actual_penetration_bp"] == 4150
    assert settlement["penetration_shortfall_bp"] == 50
    assert settlement["penetration_penalty_cents"] == 0
    assert settlement["gross_fee_cents"] == 24900000
    assert settlement["reverse_comp_cents"] == 13695000
    assert settlement["net_retained_cents"] == 11205000
    assert_settlement_conservation(settlement)


def test_penetration_shortfall_one_basis_point_past_the_band_is_penalised_in_full(api):
    """One basis point outside the band multiplies the whole shortfall, not the excess.

    PRD §3.9: "A shortfall above 50 basis points yields a penalty of
    `gross_fee_cents` multiplied by `penetration_shortfall_bp`, multiplied by two,
    divided by ten thousand, and rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/penetration_shortfall_grace_band_exactly_fifty_basis_points
    """
    ctx = setup_executed_agreement(report={"reported_subscriber_count": 99600})
    second_report = create_subscriber_report(
        ctx["station"]["id"],
        ctx["distributor"]["id"],
        reported_subscriber_count=99576,
        **SECOND_PERIOD,
    )

    response = api.create_fee_settlement(
        ctx["agreement"]["id"],
        create_fee_settlement_payload(second_report["id"], **SECOND_PERIOD),
        TEST_USERS["group_counsel_headers"],
    )
    settlement = validate_success(response, 201)

    assert settlement["actual_penetration_bp"] == 4149
    assert settlement["penetration_shortfall_bp"] == 51
    assert settlement["penetration_penalty_cents"] == 253919
    assert settlement["gross_fee_cents"] == 24894000
    assert settlement["reverse_comp_cents"] == 13691700
    assert settlement["net_retained_cents"] == 10948381
    assert_settlement_conservation(settlement)


def test_two_meetings_plus_a_proposal_exchange_do_not_satisfy_good_faith(api):
    """Only MEETING_HELD entries count, so a three-row log can still hold two meetings.

    PRD §3.6: "Entries whose `event_type` is `MEETING_HELD` feed the negotiation's
    `good_faith_meeting_count`; the other four event types are recorded but do not
    count toward it."

    Design: Difficulty/boundary_precision_check/impasse_good_faith_meeting_count_exactly_three_satisfies
    """
    ctx = setup_impasse_ready(meeting_count=2)
    append_good_faith_entry(
        ctx["negotiation"]["id"],
        ctx["negotiator_headers"],
        event_type="PROPOSAL_EXCHANGED",
        occurred_at_utc="2026-08-13T00:00:00Z",
        summary="Written term sheet mailed, no meeting",
    )

    response = api.declare_impasse(
        ctx["negotiation"]["id"],
        declare_impasse_payload(),
        ctx["negotiator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_GOOD_FAITH_NOT_SATISFIED.value, 422)

    negotiation = read_negotiation(ctx["negotiation"]["id"])
    assert negotiation["good_faith_meeting_count"] == 2
    assert negotiation["status"] != "IMPASSE"
    assert negotiation["impasse_declared_at_utc"] is None
    assert len(
        validate_success(
            api.list_good_faith_log(
                ctx["negotiation"]["id"], TEST_USERS["group_counsel_headers"]
            ),
            200,
        )
    ) == 3


def test_the_third_meeting_lands_exactly_on_the_threshold_and_permits_impasse(api):
    """Three meetings satisfy the rule; the comparison is at-least, not more-than.

    PRD §3.6: "The negotiation's `good_faith_meeting_count` must be at least three,
    counting only `MEETING_HELD` entries; exactly three satisfies the rule, and fewer
    is refused with `ERR_GOOD_FAITH_NOT_SATISFIED`."

    Design: Difficulty/boundary_precision_check/impasse_good_faith_meeting_count_exactly_three_satisfies
    """
    ctx = setup_impasse_ready(meeting_count=2)
    append_good_faith_entry(
        ctx["negotiation"]["id"],
        ctx["negotiator_headers"],
        event_type="PROPOSAL_EXCHANGED",
        occurred_at_utc="2026-08-13T00:00:00Z",
        summary="Written term sheet mailed, no meeting",
    )
    append_good_faith_entry(
        ctx["negotiation"]["id"],
        TEST_USERS["compliance_officer_headers"],
        event_type="MEETING_HELD",
        occurred_at_utc="2026-08-19T00:00:00Z",
        summary="Third rate session, mediator present",
    )

    response = api.declare_impasse(
        ctx["negotiation"]["id"],
        declare_impasse_payload(),
        ctx["negotiator_headers"],
    )
    negotiation = validate_success(response, 200)

    assert negotiation["good_faith_meeting_count"] == 3
    assert negotiation["status"] == "IMPASSE"
    assert negotiation["impasse_declared_at_utc"] == "2026-08-01T00:00:00Z"
    assert negotiation["blackout_notice_deadline_utc"] == "2026-12-02T00:00:00Z"
    assert negotiation["notice_compliance_status"] == "NOTICE_PENDING"
