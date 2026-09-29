"""Cross-entity preconditions and half-open temporal windows."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    COACH_A_HEADERS,
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    ApiErrorId,
    accept_assignment,
    active_provider,
    api_client,
    apply_provider,
    claim_line,
    claim_walked_to,
    create_contract,
    create_enrollment,
    create_substitute,
    escalate_review,
    execute_agreement,
    exit_network,
    issue_agreement,
    post_remittance,
    provider_with_contract,
    reinstate_provider,
    request_coverage,
    review_at_cap_rejected_twice,
    schedule_visit,
    transfer_enrollment,
    verify_license,
)

# Local setup builders


def _july_billing_home():
    """An ACTIVE home with a July contract and two subsidy children."""
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-07-01T00:00:00Z",
            "absence_rate_pct": 50,
        },
    )
    ctx["e1"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]
    ctx["e2"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-2",
        family_name="Brody",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]
    return ctx


def _reconciled_july_claim_under_suspension():
    """A July claim reconciled at 137250, then frozen by a quality escalation."""
    ctx = _july_billing_home()
    ctx["claim"] = claim_walked_to(
        "RECONCILED",
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-07",
        [claim_line(ctx["e1"], 18, 4), claim_line(ctx["e2"], 10, 2)],
    )
    review = review_at_cap_rejected_twice(
        ctx["provider_id"], ["QS-3", "QS-9"], "2026-08-31T00:00:00Z"
    )
    escalate_review(review["id"])
    return ctx


def _transitioning_child_and_a_second_home():
    """A transitioning subsidy child at one home, plus a second home mid-onboarding."""
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
        contract_overrides={"daily_rate_cents": 4500, "contracted_slots": 4},
    )
    ctx["e1"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]
    exit_network(ctx["provider_id"], exit_reason="RETIREMENT")

    receiving = apply_provider(
        legal_name="Brookside Family Child Care",
        county_tier="STANDARD",
        license_number="FCC-2002",
        license_expires_on="2027-09-30T00:00:00Z",
        capacity_slots=6,
        fixed_monthly_cost_cents=190000,
    )
    verified = verify_license(
        receiving["id"],
        license_number="FCC-2002",
        license_expires_on="2027-09-30T00:00:00Z",
        capacity_slots=6,
    )
    ctx["receiving_id"] = receiving["id"]
    ctx["receiving_agreement_id"] = issue_agreement(
        receiving["id"], verified["version"], shared_services=["ENROLLMENT"]
    )["id"]
    return ctx


def _pool_home_with_confirmed_morning():
    """A home whose one pool member is confirmed 08:00-12:00 on 2026-08-10."""
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["SUBSTITUTE_POOL"]},
    )
    ctx["substitute_id"] = create_substitute(
        full_name="Rosa Nunez",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2000,
        service_county_tiers=["STANDARD"],
    )["id"]
    morning = request_coverage(
        ctx["provider_id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
        requested_substitute_id=ctx["substitute_id"],
    )
    accept_assignment(morning["id"], ctx["substitute_id"])
    return ctx


def _coverage_request(ctx, start_at, end_at, reason="ILLNESS"):
    """Raw coverage request naming the pool member, returning the HTTP response."""
    return api_client.create_assignment(
        {
            "provider_id": ctx["provider_id"],
            "start_at": start_at,
            "end_at": end_at,
            "reason": reason,
            "min_credential_level": "NONE",
            "requested_substitute_id": ctx["substitute_id"],
        },
        ctx["headers"],
    )


def _two_scheduled_visits():
    """A home with visits booked on 2026-08-10 and 2026-08-11."""
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )
    schedule_visit(ctx["provider_id"], "2026-08-10T00:00:00Z", focus_area="ENVIRONMENT")
    schedule_visit(ctx["provider_id"], "2026-08-11T00:00:00Z", focus_area="HEALTH_SAFETY")
    return ctx


# cross_entity_state_dependency


def test_remittance_is_refused_while_the_named_contract_is_suspended(api):
    """A payment cannot be booked against a contract the quality cascade has suspended.

    The claim itself is RECONCILED at 137250 and would happily absorb the payment, but the
    precondition is on the contract rather than on the claim, and the escalation left the
    contract in SUSPENDED_FOR_QUALITY. The post is refused and no remittance row exists.

    PRD: "Posting requires the contract to be `ACTIVE`; a suspended or terminated contract
    returns `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/remittance_post_blocked_while_referenced_contract_suspended_for_quality
    """
    ctx = _reconciled_july_claim_under_suspension()
    assert ctx["claim"]["final_amount_cents"] == 137250
    assert ctx["claim"]["settlement_delta_cents"] == 14850

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["status"] == "SUSPENDED_FOR_QUALITY"

    validate_error(
        api.create_remittance(
            {
                "contract_id": ctx["contract_id"],
                "agency_reference": "AG-2026-07-A",
                "amount_cents": 137250,
                "received_on": "2026-08-01T00:00:00Z",
            },
            FISCAL_OFFICER_HEADERS,
        ),
        ApiErrorId.CONTRACT_NOT_ACTIVE.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_contract_remittances(ctx["contract_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_reinstatement_restores_the_contract_and_the_identical_post_succeeds(api):
    """Lifting probation returns the contract to ACTIVE and the same payment then books.

    The compensating cascade puts the contract back to ACTIVE, so the byte-identical
    remittance is accepted, allocates its whole 137250 to the single reconciled claim,
    leaves nothing unallocated, and settles that claim in full.

    PRD: "The compensating second hop returns every subsidy contract of that provider in
    `SUSPENDED_FOR_QUALITY` status to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/remittance_post_blocked_while_referenced_contract_suspended_for_quality
    """
    ctx = _reconciled_july_claim_under_suspension()
    reinstated = reinstate_provider(ctx["provider_id"])
    assert reinstated["membership_status"] == "ACTIVE"

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["status"] == "ACTIVE"

    remittance = post_remittance(
        ctx["contract_id"],
        "AG-2026-07-A",
        137250,
        received_on="2026-08-01T00:00:00Z",
    )
    assert remittance["status"] == "POSTED"
    assert remittance["unallocated_cents"] == 0
    assert remittance["allocations"] == [
        {"claim_id": ctx["claim"]["id"], "allocated_cents": 137250}
    ]

    settled = validate_success(api.get_claim(ctx["claim"]["id"], NETWORK_ADMIN_HEADERS))
    assert settled["status"] == "SETTLED"
    assert settled["paid_cents"] == 137250

    after = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert after["remitted_cents"] == 137250
    assert after["unallocated_credit_cents"] == 0


def test_transfer_is_refused_until_the_receiving_home_is_active_and_has_a_slot(api):
    """A receiving home that is not yet ACTIVE, then has no contract, is twice ineligible.

    The second home has a verified license but an unexecuted agreement, so it is still
    PENDING_AGREEMENT and cannot take a placement. Executing the agreement fixes its
    membership, but the transferring child is subsidy-certified and the home holds no
    ACTIVE subsidy contract at all, so the very same call is refused a second time.

    PRD: "The receiving home must be a *different* provider that is `ACTIVE` with
    `network_posture` `OPEN`, must have fewer enrollments in `ENROLLED` status than its own
    `capacity_slots`, and — when the transferring child is `subsidy_certified` — must hold
    an `ACTIVE` subsidy contract with at least one available slot; any of those failures
    returns `ERR_RECEIVING_PROVIDER_INELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_transfer_requires_receiving_provider_active_open_with_free_subsidy_slot
    """
    ctx = _transitioning_child_and_a_second_home()
    pending = validate_success(api.get_provider(ctx["receiving_id"], NETWORK_ADMIN_HEADERS))
    assert pending["membership_status"] == "PENDING_AGREEMENT"

    payload = {
        "receiving_provider_id": ctx["receiving_id"],
        "transfer_on": "2026-08-20T00:00:00Z",
    }
    validate_error(
        api.transfer_enrollment(ctx["e1"], payload, NETWORK_ADMIN_HEADERS),
        ApiErrorId.RECEIVING_PROVIDER_INELIGIBLE.value,
        422,
    )

    execute_agreement(ctx["receiving_agreement_id"], ctx["receiving_id"])
    active = validate_success(api.get_provider(ctx["receiving_id"], NETWORK_ADMIN_HEADERS))
    assert active["membership_status"] == "ACTIVE"
    assert active["network_posture"] == "OPEN"

    validate_error(
        api.transfer_enrollment(ctx["e1"], payload, NETWORK_ADMIN_HEADERS),
        ApiErrorId.RECEIVING_PROVIDER_INELIGIBLE.value,
        422,
    )


def test_transfer_succeeds_once_a_slot_exists_and_moves_the_slot_with_the_child(api):
    """Giving the receiving home a one-slot contract lets the placement through.

    The response is the brand-new enrollment, which points back at the source through
    `predecessor_enrollment_id` and commits the receiving contract's only slot. The source
    enrollment becomes TRANSFERRED on the transfer date, and the origin contract keeps the
    slot the exit cascade already released.

    PRD: "A successful placement moves the source enrollment `TRANSITION_PENDING →
    TRANSFERRED` with `exit_on` set to the transfer date, and creates a brand-new enrollment
    at the receiving home whose `predecessor_enrollment_id` points back at the source
    enrollment, whose status is `ENROLLED`, whose `start_on` is the transfer date, and whose
    `child_ref`, `family_name`, `days_per_week`, `private_monthly_tuition_cents` and
    `subsidy_certified` are copied unchanged from the source."

    Design: Difficulty/cross_entity_state_dependency/enrollment_transfer_requires_receiving_provider_active_open_with_free_subsidy_slot
    """
    ctx = _transitioning_child_and_a_second_home()
    execute_agreement(ctx["receiving_agreement_id"], ctx["receiving_id"])
    receiving_contract = create_contract(
        ctx["receiving_id"],
        agency_code="CCDF-02",
        daily_rate_cents=4500,
        contracted_slots=1,
        authorized_amount_cents=5000000,
    )

    placed = transfer_enrollment(ctx["e1"], ctx["receiving_id"], "2026-08-20T00:00:00Z")
    assert placed["predecessor_enrollment_id"] == ctx["e1"]
    assert placed["provider_id"] == ctx["receiving_id"]
    assert placed["status"] == "ENROLLED"
    assert placed["child_ref"] == "CH-1"
    assert placed["subsidy_certified"] is True
    assert placed["slot_committed"] is True

    source = validate_success(api.get_enrollment(ctx["e1"], NETWORK_ADMIN_HEADERS))
    assert source["status"] == "TRANSFERRED"
    assert source["exit_on"].startswith("2026-08-20")
    assert source["slot_committed"] is False

    receiving = validate_success(
        api.get_contract(receiving_contract["id"], NETWORK_ADMIN_HEADERS)
    )
    assert receiving["committed_slots"] == 1
    assert receiving["available_slots"] == 0

    origin = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert origin["committed_slots"] == 0
    assert origin["available_slots"] == 4


# resource_temporal_overlap


def test_a_gap_of_exactly_thirty_minutes_clears_the_travel_buffer(api):
    """A 12:20 start conflicts with a window ending at 12:00; a 12:30 start does not.

    The member is confirmed until 12:00. Moving a 12:20 start thirty minutes earlier gives
    11:50, which falls strictly before 12:00, so the buffered windows touch and the request
    is refused. Moving a 12:30 start back gives exactly 12:00, which is not strictly
    before 12:00, so the gap is wide enough and the assignment is offered.

    PRD: "Concretely, a conflict exists when the new window's start, moved thirty minutes
    earlier, falls strictly before that other assignment's `end_at` **and** the new
    window's end, moved thirty minutes later, falls strictly after that other assignment's
    `start_at`."

    Design: Difficulty/resource_temporal_overlap/substitute_half_open_window_with_thirty_minute_buffer_exact_gap_allowed
    """
    ctx = _pool_home_with_confirmed_morning()

    validate_error(
        _coverage_request(ctx, "2026-08-10T12:20:00Z", "2026-08-10T16:00:00Z"),
        ApiErrorId.SUBSTITUTE_INTERVAL_CONFLICT.value,
        409,
    )

    allowed = validate_success(
        _coverage_request(ctx, "2026-08-10T12:30:00Z", "2026-08-10T16:30:00Z"), 201
    )
    assert allowed["staffing_status"] == "OFFERED"
    assert allowed["substitute_id"] == ctx["substitute_id"]


def test_the_buffer_applies_on_both_sides_and_an_offered_row_still_blocks(api):
    """A window ending exactly 30 minutes before 08:00 fits; one 15 minutes after 16:30 does not.

    Coverage from 04:00 to 07:30 pushes its end out to 08:00, which is not strictly after
    the confirmed window's 08:00 start, so it is accepted. A later 16:45 request pulls its
    start back to 16:15, which falls strictly before the 16:30 end of the merely OFFERED
    afternoon assignment — offered rows count for the conflict test — so it is refused,
    leaving the member holding three assignments.

    PRD: "Finally, the member must have no scheduling conflict: no other assignment of
    theirs whose `staffing_status` is `OFFERED`, `CONFIRMED` or `COMPLETED` may overlap the
    new window once the new window is widened by a travel buffer of half an hour on each
    side."

    Design: Difficulty/resource_temporal_overlap/substitute_half_open_window_with_thirty_minute_buffer_exact_gap_allowed
    """
    ctx = _pool_home_with_confirmed_morning()
    validate_success(
        _coverage_request(ctx, "2026-08-10T12:30:00Z", "2026-08-10T16:30:00Z"), 201
    )

    early = validate_success(
        _coverage_request(ctx, "2026-08-10T04:00:00Z", "2026-08-10T07:30:00Z", "VACATION"),
        201,
    )
    assert early["staffing_status"] == "OFFERED"

    validate_error(
        _coverage_request(ctx, "2026-08-10T16:45:00Z", "2026-08-10T18:00:00Z"),
        ApiErrorId.SUBSTITUTE_INTERVAL_CONFLICT.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_substitute_assignments(ctx["substitute_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 3


def test_a_third_visit_inside_the_twenty_nine_day_window_is_refused(api):
    """A 2026-09-08 request looks back to 2026-08-10 and finds both existing visits.

    The inclusive window runs twenty-nine days either side of the requested date, so it
    spans 2026-08-10 through 2026-10-07 and captures the visits booked on 2026-08-10 and
    2026-08-11. Two is already the ration, so the third booking is refused.

    PRD: "And coaching is rationed: the provider must have fewer than two visits in
    `SCHEDULED` or `COMPLETED` status whose `scheduled_on` falls inside the inclusive window
    running twenty-nine days before to twenty-nine days after the requested date — a
    fifty-nine-day span in total, counting the requested date itself, so a home is not
    visited more than twice in any such stretch."

    Design: Difficulty/resource_temporal_overlap/coaching_visit_inclusive_twentynine_day_calendar_window_aggregate_saturation
    """
    ctx = _two_scheduled_visits()

    validate_error(
        api.create_visit(
            {
                "provider_id": ctx["provider_id"],
                "scheduled_on": "2026-09-08T00:00:00Z",
                "focus_area": "CURRICULUM",
            },
            COACH_A_HEADERS,
        ),
        ApiErrorId.COACHING_WINDOW_SATURATED.value,
        409,
    )


def test_one_day_later_the_window_slides_past_the_earlier_visit_and_admits_a_third(api):
    """A 2026-09-09 request looks back only to 2026-08-11, so it sees a single visit.

    Sliding the requested date forward by one day moves the window to 2026-08-11 through
    2026-10-08, which drops the 2026-08-10 visit out of range. Only one visit remains
    inside, so the booking is accepted and is born with no observation recorded yet.

    PRD: "The scheduling operator's identifier is recorded as `coach_user_id`, and the
    visit starts `SCHEDULED` with a null `conducted_by_user_id`, a null
    `visit_conducted_on`, a null `observation_score`, an empty `findings` array and a
    `critical_finding` flag of false."

    Design: Difficulty/resource_temporal_overlap/coaching_visit_inclusive_twentynine_day_calendar_window_aggregate_saturation
    """
    ctx = _two_scheduled_visits()

    admitted = schedule_visit(
        ctx["provider_id"], "2026-09-09T00:00:00Z", focus_area="CURRICULUM"
    )
    assert admitted["status"] == "SCHEDULED"
    assert admitted["visit_conducted_on"] is None
    assert admitted["observation_score"] is None
    assert admitted["conducted_by_user_id"] is None
    assert admitted["findings"] == []
    assert admitted["critical_finding"] is False

    _, meta = validate_paginated(
        api.list_provider_visits(ctx["provider_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 3
