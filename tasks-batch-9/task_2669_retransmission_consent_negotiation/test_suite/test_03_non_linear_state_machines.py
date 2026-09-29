"""Lifecycles that revisit states and dimensions that advance independently."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    append_good_faith_entry,
    declare_impasse_payload,
    execute_agreement_payload,
    network_approval_payload,
    read_agreement,
    read_blackout_notices,
    read_negotiation,
    read_offer,
    read_offers_of_negotiation,
    serve_blackout_notice,
    setup_accepted_agreement,
    setup_negotiation_with_report,
    submit_distributor_offer,
    submit_station_offer,
    validate_error,
    validate_success,
)

DISTRIBUTOR_COUNTER = {
    "base_rate_per_sub_cents": 150,
    "escalator_bp_per_year": 300,
    "penetration_commitment_bp": 3800,
    "includes_digital_rights": False,
    "includes_ooh_rights": False,
    "includes_streaming_rights": False,
}


def _bargain_to_impasse(api):
    """Two station offers around one distributor counter, then three meetings."""
    ctx = setup_negotiation_with_report()
    negotiation_id = ctx["negotiation"]["id"]
    ctx["offer_1"] = submit_station_offer(
        negotiation_id, ctx["station"]["id"], ctx["report"]["id"]
    )
    ctx["offer_2"] = submit_distributor_offer(
        negotiation_id, ctx["distributor"]["id"], ctx["report"]["id"],
        **DISTRIBUTOR_COUNTER,
    )
    ctx["offer_3"] = submit_station_offer(
        negotiation_id, ctx["station"]["id"], ctx["report"]["id"],
        base_rate_per_sub_cents=240,
    )
    for index in range(3):
        append_good_faith_entry(
            negotiation_id,
            ctx["negotiator_headers"],
            event_type="MEETING_HELD",
            summary=f"Bargaining session {index + 1} with both principals present",
        )
    return ctx


def test_negotiation_cycles_through_both_waiting_states_into_impasse(api):
    """Offers alternate the turn, and impasse is stamped from the logical clock.

    PRD §3.6: "Declaring impasse stamps `impasse_declared_at_utc` from the current
    logical clock, recomputes `notice_compliance_status`, and increments the
    negotiation's `version` by one."

    Design: Difficulty/non_linear_state_machine/negotiation_round_trip_cycle_and_impasse_reentry
    """
    ctx = _bargain_to_impasse(api)

    response = api.declare_impasse(
        ctx["negotiation"]["id"],
        declare_impasse_payload(),
        ctx["negotiator_headers"],
    )
    negotiation = validate_success(response, 200)

    assert negotiation["status"] == "IMPASSE"
    assert negotiation["impasse_declared_at_utc"] == "2026-08-01T00:00:00Z"
    assert negotiation["blackout_notice_deadline_utc"] == "2026-12-02T00:00:00Z"
    assert negotiation["round_number"] == 3
    assert negotiation["station_offer_count"] == 2
    assert negotiation["distributor_offer_count"] == 1
    assert negotiation["good_faith_meeting_count"] == 3
    assert negotiation["notice_compliance_status"] == "NOTICE_PENDING"


def test_station_offer_out_of_impasse_reopens_bargaining_and_supersedes_the_notice(api):
    """A fourth offer leaves IMPASSE, and the served notice is no longer operative.

    PRD §3.6: "A station-group offer submitted while the negotiation sits at
    `IMPASSE` advances it `IMPASSE -> AWAITING_DISTRIBUTOR_RESPONSE`, creates the
    offer with `offered_by` of `STATION_GROUP`, increments `round_number` by one,
    moves every blackout notice on the negotiation still in `SERVED` to
    `SUPERSEDED`, resets `notice_compliance_status` to `NOT_REQUIRED`, and increments
    the negotiation's `version` by one."

    Design: Difficulty/non_linear_state_machine/negotiation_round_trip_cycle_and_impasse_reentry
    """
    ctx = _bargain_to_impasse(api)
    negotiation_id = ctx["negotiation"]["id"]
    validate_success(
        api.declare_impasse(
            negotiation_id, declare_impasse_payload(), ctx["negotiator_headers"]
        ),
        200,
    )
    notice = serve_blackout_notice(negotiation_id)
    assert notice["status"] == "SERVED"
    assert notice["required_notice_days_snapshot"] == 30

    response = api.create_offer(
        negotiation_id,
        {
            "subscriber_report_id": ctx["report"]["id"],
            "base_rate_per_sub_cents": 230,
            "escalator_bp_per_year": 700,
            "term_months": 36,
            "tier": "EXPANDED_BASIC",
            "penetration_commitment_bp": 4200,
            "includes_digital_rights": True,
            "includes_ooh_rights": False,
            "includes_streaming_rights": True,
        },
        ctx["negotiator_headers"],
    )
    fourth_offer = validate_success(response, 201)
    assert fourth_offer["round_number"] == 4
    assert fourth_offer["offered_by"] == "STATION_GROUP"

    negotiation = read_negotiation(negotiation_id)
    assert negotiation["status"] == "AWAITING_DISTRIBUTOR_RESPONSE"
    assert negotiation["round_number"] == 4
    assert negotiation["station_offer_count"] == 3
    assert negotiation["distributor_offer_count"] == 1
    assert negotiation["good_faith_meeting_count"] == 3
    assert negotiation["impasse_declared_at_utc"] == "2026-08-01T00:00:00Z"
    assert negotiation["notice_compliance_status"] == "NOT_REQUIRED"

    notices = read_blackout_notices(negotiation_id)
    assert [item["status"] for item in notices] == ["SUPERSEDED"]

    for key in ("offer_1", "offer_2", "offer_3"):
        assert read_offer(ctx[key]["id"])["status"] == "SUBMITTED"
    assert len(read_offers_of_negotiation(negotiation_id)) == 4


def test_execution_is_refused_while_the_network_dimension_is_still_pending(api):
    """The execution dimension cannot advance until the network dimension clears.

    PRD §3.7: "Its `network_approval_status` must be `NOT_REQUIRED` or
    `NETWORK_APPROVED` - both `PENDING_NETWORK` and `NETWORK_REJECTED` block
    execution, and the refusal is `ERR_NETWORK_APPROVAL_PENDING`."

    Design: Difficulty/non_linear_state_machine/agreement_execution_and_network_dimensions_advance_independently
    """
    ctx = setup_accepted_agreement()
    assert ctx["agreement"]["network_approval_status"] == "PENDING_NETWORK"

    response = api.execute_agreement(
        ctx["agreement"]["id"],
        execute_agreement_payload(),
        TEST_USERS["second_group_counsel_headers"],
    )
    validate_error(response, ApiErrorId.ERR_NETWORK_APPROVAL_PENDING.value, 422)

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["execution_status"] == "PENDING_EXECUTION"
    assert agreement["network_approval_status"] == "PENDING_NETWORK"
    assert agreement["executed_by_user_id"] is None


def test_the_two_agreement_dimensions_advance_one_at_a_time(api):
    """Approval moves only the network dimension; execution moves only its own.

    PRD §3.7: "Either decision leaves `execution_status` entirely untouched and
    increments the agreement's `version` by one."

    Design: Difficulty/non_linear_state_machine/agreement_execution_and_network_dimensions_advance_independently
    """
    ctx = setup_accepted_agreement()
    version_before = ctx["agreement"]["version"]

    approved = validate_success(
        api.decide_network_approval(
            ctx["agreement"]["id"],
            network_approval_payload("APPROVE"),
            TEST_USERS["network_representative_headers"],
        ),
        200,
    )
    assert approved["network_approval_status"] == "NETWORK_APPROVED"
    assert approved["execution_status"] == "PENDING_EXECUTION"
    assert approved["version"] == version_before + 1

    executed = validate_success(
        api.execute_agreement(
            ctx["agreement"]["id"],
            execute_agreement_payload(),
            TEST_USERS["second_group_counsel_headers"],
        ),
        200,
    )
    assert executed["execution_status"] == "EXECUTED"
    assert executed["network_approval_status"] == "NETWORK_APPROVED"
    assert executed["accepted_by_user_id"] == "counsel-1"
    assert executed["executed_by_user_id"] == "counsel-2"
    assert executed["version"] == version_before + 2
