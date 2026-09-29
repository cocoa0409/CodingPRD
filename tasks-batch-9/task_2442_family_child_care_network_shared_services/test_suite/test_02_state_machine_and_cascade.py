"""Non-linear state machines and transitive cascades."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    OMIT,
    ApiErrorId,
    accept_assignment,
    active_provider,
    apply_provider,
    claim_line,
    create_claim,
    create_enrollment,
    create_substitute,
    contract_version,
    decline_assignment,
    escalate_review,
    issue_agreement,
    make_provider_headers,
    provider_with_contract,
    request_coverage,
    review_at_cap_rejected_twice,
    revenue_model,
    set_clock,
    verify_license,
    withdraw_enrollment,
)

# Local setup builders


def _home_with_open_offer():
    """A PENDING_AGREEMENT home holding a fresh eight-percent offer."""
    provider = apply_provider(fixed_monthly_cost_cents=OMIT)
    verified = verify_license(provider["id"])
    agreement = issue_agreement(
        provider["id"],
        verified["version"],
        network_fee_pct=8.0,
        shared_services=["ENROLLMENT", "BILLING"],
    )
    return provider["id"], agreement


def _pool_home_with_two_members():
    """An ACTIVE home plus a cheap and an expensive pool member."""
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["SUBSTITUTE_POOL"]},
    )
    ctx["s1"] = create_substitute(
        full_name="Rosa Nunez",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2000,
        service_county_tiers=["STANDARD"],
    )["id"]
    ctx["s2"] = create_substitute(
        full_name="Dana Okoye",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2400,
        service_county_tiers=["STANDARD"],
    )["id"]
    return ctx


def _home_with_two_subsidy_and_one_private_child(authorized_amount_cents=5000000):
    """An ACTIVE August home with two subsidy children and one private child."""
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": authorized_amount_cents,
            "period_start_on": "2026-08-01T00:00:00Z",
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
    ctx["e3"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-3",
        family_name="Cortez",
        days_per_week=5,
        private_monthly_tuition_cents=102000,
        subsidy_certified=False,
    )["id"]
    return ctx


# non_linear_state_machine


def test_negotiation_cycle_returns_to_sent_and_advances_the_round_index(api):
    """Counter and revise form a genuine cycle whose round counter climbs 1, 2, 3.

    The offer is born at round 1 in SENT. The provider's first counter stores 5.0 and
    moves it to COUNTERED at round 2; staff revise to 7.0, clearing the proposal and
    returning to SENT without touching the counter; the second counter lands at round 3.

    PRD: "A counter moves the agreement `SENT → COUNTERED`, stores the proposed figure
    and increments `round_index` by one."

    Design: Difficulty/non_linear_state_machine/membership_agreement_negotiation_cycle_bounded_at_three_rounds
    """
    provider_id, agreement = _home_with_open_offer()
    provider_headers = make_provider_headers(provider_id)
    assert agreement["status"] == "SENT"
    assert agreement["round_index"] == 1
    assert agreement["proposed_network_fee_pct"] is None
    assert agreement["superseded"] is False
    assert agreement["withdrawal_reason"] is None
    assert agreement["executed_at"] is None

    countered = validate_success(
        api.counter_agreement(
            agreement["id"], {"proposed_network_fee_pct": 5.0}, provider_headers
        )
    )
    assert countered["status"] == "COUNTERED"
    assert countered["round_index"] == 2
    assert float(countered["proposed_network_fee_pct"]) == 5.0

    revised = validate_success(
        api.revise_agreement(
            agreement["id"], {"network_fee_pct": 7.0}, NETWORK_ADMIN_HEADERS
        )
    )
    assert revised["status"] == "SENT"
    assert float(revised["network_fee_pct"]) == 7.0
    assert revised["proposed_network_fee_pct"] is None
    assert revised["round_index"] == 2

    second = validate_success(
        api.counter_agreement(
            agreement["id"], {"proposed_network_fee_pct": 5.0}, provider_headers
        )
    )
    assert second["status"] == "COUNTERED"
    assert second["round_index"] == 3


def test_third_counter_is_refused_and_the_offer_can_still_be_executed(api):
    """Once the round counter reaches three the cycle closes but the offer survives.

    After two counters the round index is 3, so countering again is refused and the
    agreement is left in SENT holding the last revised fee of 6.5. Executing it then
    carries that fee onto the provider and activates membership.

    PRD: "Countering carries a `proposed_network_fee_pct` — the fee the provider is
    willing to accept — and is only available while the agreement is `SENT`, only to the
    provider named on the agreement, and only while `round_index` is still below three; a
    fourth round is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/membership_agreement_negotiation_cycle_bounded_at_three_rounds
    """
    provider_id, agreement = _home_with_open_offer()
    provider_headers = make_provider_headers(provider_id)
    validate_success(
        api.counter_agreement(
            agreement["id"], {"proposed_network_fee_pct": 5.0}, provider_headers
        )
    )
    validate_success(
        api.revise_agreement(agreement["id"], {"network_fee_pct": 7.0}, NETWORK_ADMIN_HEADERS)
    )
    validate_success(
        api.counter_agreement(
            agreement["id"], {"proposed_network_fee_pct": 5.0}, provider_headers
        )
    )
    revised = validate_success(
        api.revise_agreement(agreement["id"], {"network_fee_pct": 6.5}, NETWORK_ADMIN_HEADERS)
    )
    assert revised["status"] == "SENT"
    assert revised["round_index"] == 3

    validate_error(
        api.counter_agreement(
            agreement["id"], {"proposed_network_fee_pct": 4.0}, provider_headers
        ),
        ApiErrorId.NEGOTIATION_ROUNDS_EXHAUSTED.value,
        409,
    )
    still_open = validate_success(api.get_agreement(agreement["id"], NETWORK_ADMIN_HEADERS))
    assert still_open["status"] == "SENT"
    assert still_open["round_index"] == 3

    executed = validate_success(api.execute_agreement(agreement["id"], None, provider_headers))
    assert executed["status"] == "EXECUTED"
    assert executed["executed_at"] is not None

    provider = validate_success(api.get_provider(provider_id, NETWORK_ADMIN_HEADERS))
    assert provider["membership_status"] == "ACTIVE"
    assert provider["network_posture"] == "OPEN"
    assert float(provider["network_fee_pct"]) == 6.5


def test_decline_clears_the_holder_and_re_offers_to_the_next_ranked_member(api):
    """A decline grows the exclusion set and hands the same offer to the dearer member.

    The selector opens on the 2000-cent member because it ranks cheapest first. When that
    member declines, their id is recorded in `declined_substitute_ids`, the holder is
    replaced by the 2400-cent member, and the staffing dimension is back at OFFERED while
    the billing dimension has never moved off UNBILLED.

    PRD: "Declining also requires `OFFERED` status and the acting substitute's ownership;
    the declining member's id is appended to `declined_substitute_ids`, `substitute_id` is
    cleared to null, and the selector re-runs immediately with the grown exclusion set."

    Design: Difficulty/non_linear_state_machine/substitute_assignment_parallel_status_dimensions_with_decline_reoffer_loop
    """
    ctx = _pool_home_with_two_members()
    assignment = request_coverage(
        ctx["provider_id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        reason="VACATION",
        min_credential_level="NONE",
    )
    assert assignment["substitute_id"] == ctx["s1"]
    assert assignment["staffing_status"] == "OFFERED"
    assert assignment["billing_status"] == "UNBILLED"
    assert assignment["declined_substitute_ids"] == []

    reoffered = decline_assignment(assignment["id"], ctx["s1"])
    assert reoffered["substitute_id"] == ctx["s2"]
    assert reoffered["staffing_status"] == "OFFERED"
    assert reoffered["billing_status"] == "UNBILLED"
    assert reoffered["declined_substitute_ids"] == [ctx["s1"]]

    confirmed = accept_assignment(assignment["id"], ctx["s2"])
    assert confirmed["staffing_status"] == "CONFIRMED"
    assert confirmed["billing_status"] == "UNBILLED"


def test_invoicing_moves_only_the_billing_dimension_of_a_completed_assignment(api):
    """Completion advances both dimensions; invoicing advances only the billing one.

    The accepting member charges 2400 cents an hour, so four billable hours give a
    9600-cent subtotal and a ten-percent fee of 960 for a 10560-cent total. Completion
    lands COMPLETED / ACCRUED, invoicing then lands COMPLETED / INVOICED, and only the
    member who actually worked has their completed count raised.

    PRD: "An assignment carries two independent status dimensions, and invoicing moves
    only the second one: a `FiscalOfficer` bills accrued coverage to the provider's
    shared-services account, which requires `billing_status` to be `ACCRUED` and advances
    it `ACCRUED → INVOICED` while `staffing_status` remains `COMPLETED` throughout."

    Design: Difficulty/non_linear_state_machine/substitute_assignment_parallel_status_dimensions_with_decline_reoffer_loop
    """
    ctx = _pool_home_with_two_members()
    assignment = request_coverage(
        ctx["provider_id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        reason="VACATION",
        min_credential_level="NONE",
    )
    decline_assignment(assignment["id"], ctx["s1"])
    accept_assignment(assignment["id"], ctx["s2"])
    set_clock("2026-08-05T12:00:00Z")

    completed = validate_success(
        api.complete_assignment(assignment["id"], None, ctx["headers"])
    )
    assert completed["staffing_status"] == "COMPLETED"
    assert completed["billing_status"] == "ACCRUED"
    assert completed["total_cost_cents"] == 10560

    invoiced = validate_success(
        api.invoice_assignment(assignment["id"], None, FISCAL_OFFICER_HEADERS)
    )
    assert invoiced["staffing_status"] == "COMPLETED"
    assert invoiced["billing_status"] == "INVOICED"
    assert invoiced["total_cost_cents"] == 10560

    worker = validate_success(api.get_substitute(ctx["s2"], NETWORK_ADMIN_HEADERS))
    decliner = validate_success(api.get_substitute(ctx["s1"], NETWORK_ADMIN_HEADERS))
    assert worker["assignment_count_completed"] == 1
    assert decliner["assignment_count_completed"] == 0


# transitive_cascade


def test_escalation_travels_from_review_through_provider_and_contract_to_the_claim(api):
    """One escalation call rewrites four rows: review, provider, contract and claim.

    The review leaves the CAP cycle terminally and hands back its finding, the provider
    drops to PROBATION with a RESTRICTED posture, the contract is suspended, and the
    untouched DRAFT claim is frozen as HELD carrying the status it came from. Because the
    claim was only drafted it had consumed no authorization, so the contract's claimed
    amount stays at 0.

    PRD: "Hop three moves every subsidy claim of those contracts that is in `DRAFT` or
    `SUBMITTED` status to `HELD`, recording the status it came from in `held_from_status`
    and setting `hold_reason` to the literal string `CONTRACT_SUSPENDED_FOR_QUALITY`; a
    claim held out of `SUBMITTED` additionally gives its `provisional_amount_cents` back
    to its contract's `claimed_amount_cents`, while a claim held out of `DRAFT` had
    consumed no authorization and therefore returns none."

    Design: Difficulty/transitive_cascade/quality_escalation_cascade_depth_four_review_provider_contract_claim_revenue
    """
    ctx = _home_with_two_subsidy_and_one_private_child()
    claim = create_claim(
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-08",
        [claim_line(ctx["e1"], 20, 0), claim_line(ctx["e2"], 20, 0)],
        contract_version(ctx["contract_id"]),
    )
    assert claim["status"] == "DRAFT"

    review = review_at_cap_rejected_twice(
        ctx["provider_id"], ["QS-3", "QS-9"], "2026-08-31T00:00:00Z"
    )
    escalated = escalate_review(review["id"])
    assert escalated["status"] == "ESCALATED_TO_LICENSING"

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["membership_status"] == "PROBATION"
    assert provider["network_posture"] == "RESTRICTED"
    assert provider["open_finding_count"] == 0

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["status"] == "SUSPENDED_FOR_QUALITY"
    assert contract["claimed_amount_cents"] == 0

    held = validate_success(api.get_claim(claim["id"], NETWORK_ADMIN_HEADERS))
    assert held["status"] == "HELD"
    assert held["held_from_status"] == "DRAFT"
    assert held["hold_reason"] == "CONTRACT_SUSPENDED_FOR_QUALITY"


def test_escalation_hop_four_drops_the_held_children_out_of_projected_revenue(api):
    """Projected revenue falls from 300000 to 102000 cents as the hold bites.

    Before the escalation the two subsidy children contribute 2 * 4500 * 22 == 198000 and
    the private family contributes 102000, for 300000. Afterwards both subsidy children
    sit on the lines of a HELD claim for the clock month, so the subsidy component
    collapses to 0, revenue is the private 102000 alone, and the margin lands in the
    AT_RISK band.

    PRD: "Hop four recomputes the provider's `projected_monthly_revenue_cents`, and
    because the enrollments named on the lines of a newly held claim for the current clock
    month drop out of the subsidy revenue component, the escalation is visible in the
    provider's projected revenue as well as in their status."

    Design: Difficulty/transitive_cascade/quality_escalation_cascade_depth_four_review_provider_contract_claim_revenue
    """
    ctx = _home_with_two_subsidy_and_one_private_child()
    create_claim(
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-08",
        [claim_line(ctx["e1"], 20, 0), claim_line(ctx["e2"], 20, 0)],
        contract_version(ctx["contract_id"]),
    )

    before = revenue_model(ctx["provider_id"])
    assert before["subsidy_component_cents"] == 198000
    assert before["private_component_cents"] == 102000
    assert before["food_component_cents"] == 0
    assert before["monthly_revenue_cents"] == 300000

    review = review_at_cap_rejected_twice(
        ctx["provider_id"], ["QS-3", "QS-9"], "2026-08-31T00:00:00Z"
    )
    escalate_review(review["id"])

    after = revenue_model(ctx["provider_id"])
    assert after["subsidy_component_cents"] == 0
    assert after["private_component_cents"] == 102000
    assert after["monthly_revenue_cents"] == 102000
    assert after["sustainability"] == "AT_RISK"

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["projected_monthly_revenue_cents"] == 102000


def test_withdrawing_a_subsidy_child_releases_the_slot_it_was_holding(api):
    """One withdrawal moves three things: the status, the flag and the slot ledger.

    With two subsidy children the contract shows 2 committed and 2 available slots.
    Withdrawing one of them turns its `slot_committed` flag off and hands the slot back,
    leaving 1 committed and 3 available while the contracted total is untouched.

    PRD: "`exit_on` is recorded, the provider's `projected_monthly_revenue_cents` is
    recomputed, and any committed subsidy slot is released — the contract's
    `committed_slots` falls by one and its `available_slots` rises by one — **but only
    when `slot_committed` was actually true**."

    Design: Difficulty/transitive_cascade/enrollment_withdraw_cascade_depth_three_status_slot_release_revenue
    """
    ctx = _home_with_two_subsidy_and_one_private_child()
    before = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert before["committed_slots"] == 2
    assert before["available_slots"] == 2

    withdrawn = withdraw_enrollment(ctx["e1"], ctx["provider_id"], "2026-08-15T00:00:00Z")
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["slot_committed"] is False
    assert withdrawn["exit_on"].startswith("2026-08-15")

    after = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert after["committed_slots"] == 1
    assert after["available_slots"] == 3
    assert after["contracted_slots"] == 4


def test_withdrawal_recomputes_the_subsidy_component_at_one_remaining_child(api):
    """The released child stops earning, so revenue falls from 300000 to 201000 cents.

    A single remaining subsidy-bearing enrollment earns 1 * 4500 * 22 == 99000, the
    private family still contributes 102000, and the stored projection agrees with the
    computed read at 201000.

    PRD: "`subsidy_component_cents` is the count of subsidy-bearing enrollments multiplied
    by the contract's `daily_rate_cents` — treated as zero when the provider has no such
    contract — multiplied by the 22 authorized care days in a month."

    Design: Difficulty/transitive_cascade/enrollment_withdraw_cascade_depth_three_status_slot_release_revenue
    """
    ctx = _home_with_two_subsidy_and_one_private_child()
    assert revenue_model(ctx["provider_id"])["monthly_revenue_cents"] == 300000

    withdraw_enrollment(ctx["e1"], ctx["provider_id"], "2026-08-15T00:00:00Z")

    after = revenue_model(ctx["provider_id"])
    assert after["subsidy_component_cents"] == 99000
    assert after["private_component_cents"] == 102000
    assert after["monthly_revenue_cents"] == 201000

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["projected_monthly_revenue_cents"] == 201000
