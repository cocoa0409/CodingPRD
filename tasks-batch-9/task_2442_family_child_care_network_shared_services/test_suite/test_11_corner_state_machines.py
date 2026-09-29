"""Declared transitions, terminal states and the side effects that ride along."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    COACH_B_HEADERS,
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    NO_AUTH_HEADERS,
    ApiErrorId,
    accept_assignment,
    active_provider,
    claim_line,
    claim_walked_to,
    complete_exit,
    contract_version,
    create_claim,
    create_enrollment,
    create_license_verification_payload,
    create_provider_payload,
    create_substitute,
    escalate_review,
    exit_network,
    make_substitute_headers,
    open_review,
    order_line,
    provider_with_contract,
    reject_cap,
    request_coverage,
    review_at_cap_rejected_twice,
    schedule_visit,
    set_clock,
    submit_cap,
    withdraw_enrollment,
)

# Local setup builders


def _billing_home(**contract_overrides):
    """An ACTIVE home holding an ACTIVE subsidy contract with four slots."""
    overrides = {
        "daily_rate_cents": 4500,
        "contracted_slots": 4,
        "authorized_amount_cents": 5000000,
        "period_start_on": "2026-08-01T00:00:00Z",
    }
    overrides.update(contract_overrides)
    return provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides=overrides,
    )


def _home_with_one_subsidy_child():
    """A billing home with a single subsidy-certified child holding one slot."""
    ctx = _billing_home()
    ctx["e1"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]
    return ctx


def _pool_home_with_completed_coverage():
    """A home whose one pool member has worked a four-hour morning to completion."""
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
    assignment = request_coverage(
        ctx["provider_id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
        requested_substitute_id=ctx["substitute_id"],
    )
    accept_assignment(assignment["id"], ctx["substitute_id"])
    set_clock("2026-08-05T12:00:00Z")
    ctx["assignment_id"] = assignment["id"]
    return ctx


def _visit_conducted_at_eighty_eight(api):
    """A home whose only completed visit was observed at 88, conducted by coach-b."""
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )
    visit = schedule_visit(
        ctx["provider_id"], "2026-08-10T00:00:00Z", focus_area="ENVIRONMENT"
    )
    set_clock("2026-08-10T00:00:00Z")
    conducted = validate_success(
        api.conduct_visit(
            visit["id"],
            {
                "visit_conducted_on": "2026-08-10T00:00:00Z",
                "observation_score": 88,
                "findings": ["QS-LABELLING"],
                "critical_finding": False,
            },
            COACH_B_HEADERS,
        )
    )
    ctx["visit_id"] = visit["id"]
    ctx["conducted"] = conducted
    return ctx


# Entity lifecycles


def test_verifying_the_license_advances_the_applicant_but_keeps_it_frozen(api):
    """Verification moves APPLICANT to PENDING_AGREEMENT while the posture stays FROZEN.

    The transition answers 200 and bumps the provider from version 1 to version 2, but a
    licensed home with no signed agreement is still not a member, so the derived gate that
    blocks provider-initiated writes does not open yet.

    PRD: "A successful verification advances the provider `APPLICANT → PENDING_AGREEMENT`
    and increments the provider's `version` by one; the posture stays `FROZEN`, because a
    licensed provider with no signed agreement is still not a network member and still may
    not create any records."

    Design: Corner/State Machines/license_verification_moves_applicant_to_pending_agreement
    """
    applied = validate_success(
        api.apply_provider(create_provider_payload(), NO_AUTH_HEADERS), 201
    )
    assert applied["membership_status"] == "APPLICANT"
    assert applied["network_posture"] == "FROZEN"
    assert applied["version"] == 1

    verified = validate_success(
        api.verify_license(
            applied["id"],
            create_license_verification_payload(
                license_number="FCC-1001", license_expires_on="2027-06-30T00:00:00Z"
            ),
            NETWORK_ADMIN_HEADERS,
        ),
        200,
    )
    assert verified["membership_status"] == "PENDING_AGREEMENT"
    assert verified["network_posture"] == "FROZEN"
    assert verified["version"] == 2


def test_executing_an_already_executed_agreement_is_refused_and_fires_no_side_effect(api):
    """A second signature is refused and the provider's version does not move again.

    The first execution left the agreement terminal and the provider on version 4 — one for
    the application, one for the verification, one for the agreement issue and one for the
    activation. The repeat call reports the agreement's own state, keeps `executed_at`
    exactly as it was stamped, and leaves the provider untouched at version 4.

    PRD: "`EXECUTED` is terminal for the agreement; the fee percentage carried onto the
    provider is what the revenue model will later charge against gross monthly revenue."

    Design: Corner/State Machines/execute_agreement_twice_second_call_returns_invalid_agreement_state
    """
    ctx = active_provider(agreement_overrides={"shared_services": ["ENROLLMENT"]})
    assert ctx["agreement"]["status"] == "EXECUTED"
    assert ctx["provider"]["membership_status"] == "ACTIVE"
    assert ctx["provider"]["version"] == 4
    executed_at = ctx["agreement"]["executed_at"]
    assert executed_at is not None

    validate_error(
        api.execute_agreement(ctx["agreement_id"], None, ctx["headers"]),
        ApiErrorId.INVALID_AGREEMENT_STATE.value,
        409,
    )

    agreement = validate_success(api.get_agreement(ctx["agreement_id"], NETWORK_ADMIN_HEADERS))
    assert agreement["status"] == "EXECUTED"
    assert agreement["executed_at"] == executed_at

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["version"] == 4
    assert provider["membership_status"] == "ACTIVE"


def test_a_fresh_claim_and_a_fresh_order_are_born_with_every_money_column_at_zero(api):
    """Drafting and opening both create rows that hold no computed money at all.

    A drafted claim carries five zeroed cent columns and three null bookkeeping fields, and
    an opened order carries five zeroed columns of its own; nothing is valued until the
    claim is submitted or the order is committed.

    PRD: "A created claim sits in `DRAFT` with `provisional_amount_cents`,
    `final_amount_cents`, `advance_paid_cents`, `paid_cents` and `settlement_delta_cents`
    all at 0, with `held_from_status`, `hold_reason` and `rejection_reason` all null, and
    the act of creating it increments the contract's `version` by one."

    PRD: "A new order sits in `OPEN` status with `total_quantity`, `discount_pct`,
    `subtotal_cents`, `insurance_admin_fee_cents` and `total_cents` all at 0; nothing is
    priced until the provider commits."

    Design: Corner/State Machines/newly_created_claim_and_order_start_in_their_declared_initial_states
    """
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={
            "shared_services": ["ENROLLMENT", "BILLING", "GROUP_PURCHASING"]
        },
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-08-01T00:00:00Z",
        },
    )
    enrollment = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )

    claim = create_claim(
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-08",
        [claim_line(enrollment["id"], 20, 0)],
        contract_version(ctx["contract_id"]),
    )
    assert claim["status"] == "DRAFT"
    assert claim["provisional_amount_cents"] == 0
    assert claim["final_amount_cents"] == 0
    assert claim["advance_paid_cents"] == 0
    assert claim["paid_cents"] == 0
    assert claim["settlement_delta_cents"] == 0
    assert claim["held_from_status"] is None
    assert claim["hold_reason"] is None
    assert claim["rejection_reason"] is None

    order = validate_success(
        api.create_order(
            {
                "provider_id": ctx["provider_id"],
                "category": "SUPPLIES",
                "lines": [order_line("ART-KIT", 1250, 4)],
            },
            ctx["headers"],
        ),
        201,
    )
    assert order["status"] == "OPEN"
    assert order["total_quantity"] == 0
    assert float(order["discount_pct"]) == 0
    assert order["subtotal_cents"] == 0
    assert order["insurance_admin_fee_cents"] == 0
    assert order["total_cents"] == 0


def test_a_completed_assignment_refuses_both_accept_and_decline(api):
    """Neither answer is available once coverage has been delivered and costed.

    Four hours at 2000 cents give a base of 8000, no credential premium, and a ten-percent
    administration fee of 800 for a total of 8800. From that terminal staffing state both
    the decline and the accept are refused, the accrued billing dimension is left alone, and
    no identifier is added to the exclusion set.

    PRD: "Accepting requires the assignment's `staffing_status` to be `OFFERED`, requires
    the acting substitute to be the one named on `substitute_id`, and re-checks that their
    `pool_status` is `AVAILABLE` and their `clearance_expires_on` still falls on or after
    the assignment's `end_at`; it moves the assignment `OFFERED → CONFIRMED` and leaves
    `billing_status` untouched."

    Design: Corner/State Machines/completed_assignment_is_locked_down_against_accept_and_decline
    """
    ctx = _pool_home_with_completed_coverage()
    completed = validate_success(
        api.complete_assignment(ctx["assignment_id"], None, ctx["headers"])
    )
    assert completed["staffing_status"] == "COMPLETED"
    assert completed["billing_status"] == "ACCRUED"
    assert completed["total_cost_cents"] == 8800

    substitute_headers = make_substitute_headers(ctx["substitute_id"])
    for call in (api.decline_assignment, api.accept_assignment):
        validate_error(
            call(ctx["assignment_id"], None, substitute_headers),
            ApiErrorId.INVALID_ASSIGNMENT_STATE.value,
            409,
        )

    unchanged = validate_success(
        api.get_assignment(ctx["assignment_id"], NETWORK_ADMIN_HEADERS)
    )
    assert unchanged["staffing_status"] == "COMPLETED"
    assert unchanged["billing_status"] == "ACCRUED"
    assert unchanged["declined_substitute_ids"] == []
    assert unchanged["total_cost_cents"] == 8800


def test_conducting_a_visit_twice_is_refused_and_never_re_scores_the_home(api):
    """The second observation is rejected and the quality score stays on the first one.

    A single completed visit renormalises its own one-half weight, so the score is exactly
    the observed 88.00 and the band is TIER_1 under the coaching-weighted arithmetic. The
    repeat call carrying an observation of 40 is refused, and re-reading the provider still
    shows 88.00 while the visit keeps its original observation and findings.

    PRD: "The visit must be `SCHEDULED`; the conducted date must fall on or after the
    visit's `scheduled_on` and on or before the logical clock date; and the acting operator
    must not be the operator recorded in `coach_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/State Machines/coaching_visit_conduct_twice_second_call_returns_invalid_visit_state
    """
    ctx = _visit_conducted_at_eighty_eight(api)
    assert ctx["conducted"]["status"] == "COMPLETED"

    before = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert float(before["quality_score"]) == 88.00
    assert before["quality_tier"] == "TIER_1"
    assert before["quality_variant_applied"] == "COACHING_WEIGHTED"

    validate_error(
        api.conduct_visit(
            ctx["visit_id"],
            {
                "visit_conducted_on": "2026-08-10T00:00:00Z",
                "observation_score": 40,
                "findings": ["QS-DUPLICATE"],
                "critical_finding": False,
            },
            COACH_B_HEADERS,
        ),
        ApiErrorId.INVALID_VISIT_STATE.value,
        409,
    )

    after = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert float(after["quality_score"]) == 88.00

    visit = validate_success(api.get_visit(ctx["visit_id"], NETWORK_ADMIN_HEADERS))
    assert visit["status"] == "COMPLETED"
    assert float(visit["observation_score"]) == 88
    assert visit["findings"] == ["QS-LABELLING"]


def test_escalation_needs_two_rejections_even_from_the_right_state(api):
    """A review already in CAP_REJECTED cannot escalate on a single rejection.

    One submit-and-reject round leaves the count at 1, so the from-state is perfectly valid
    but the counter precondition is not met. The refusal leaves the review where it was and
    fires none of the four cascade hops: the provider is still ACTIVE and OPEN and the
    contract is still ACTIVE.

    PRD: "The review must be sitting in `CAP_REJECTED`, its `cap_rejection_count` must have
    reached at least two — an earlier attempt returns `ERR_CAP_REJECTION_LIMIT_NOT_REACHED`
    — and the provider must currently be `ACTIVE`."

    Design: Corner/State Machines/escalate_review_before_two_cap_rejections_returns_cap_rejection_limit_not_reached
    """
    ctx = _billing_home()
    review = open_review(ctx["provider_id"], ["QS-3"], "2026-08-31T00:00:00Z")
    assert review["status"] == "OPEN"
    assert review["cap_rejection_count"] == 0

    submit_cap(review["id"], ctx["provider_id"], "First corrective plan")
    rejected = reject_cap(review["id"])
    assert rejected["status"] == "CAP_REJECTED"
    assert rejected["cap_rejection_count"] == 1

    validate_error(
        api.escalate_review(review["id"], None, NETWORK_ADMIN_HEADERS),
        ApiErrorId.CAP_REJECTION_LIMIT_NOT_REACHED.value,
        409,
    )

    still_open = validate_success(api.get_review(review["id"], NETWORK_ADMIN_HEADERS))
    assert still_open["status"] == "CAP_REJECTED"
    assert still_open["cap_rejection_count"] == 1

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["membership_status"] == "ACTIVE"
    assert provider["network_posture"] == "OPEN"

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["status"] == "ACTIVE"


def test_beginning_an_exit_freezes_the_home_and_releases_only_the_committed_slot(api):
    """One call marks both families for transition but hands back a single subsidy slot.

    The subsidy child was holding a slot and the private child never was, so the contract
    falls from one committed slot to none while its four contracted slots all become
    available again. Both enrollments land in TRANSITION_PENDING with `slot_committed`
    false, projected revenue collapses to 0, and the contract itself is not terminated.

    PRD: "The second hop follows from the first: because those enrollments have left
    `ENROLLED`, each one that was holding a contracted subsidy slot releases it — the
    contract's `committed_slots` falls by one, its `available_slots` rises by one, and the
    enrollment's `slot_committed` becomes false — and this happens only for enrollments
    whose `slot_committed` was true."

    Design: Corner/State Machines/exit_network_side_effects_freeze_provider_and_release_committed_slots
    """
    ctx = _home_with_one_subsidy_child()
    ctx["e2"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-2",
        family_name="Brody",
        days_per_week=5,
        private_monthly_tuition_cents=102000,
        subsidy_certified=False,
    )["id"]

    before = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert before["committed_slots"] == 1
    assert before["available_slots"] == 3

    exiting = exit_network(ctx["provider_id"], exit_reason="RETIREMENT")
    assert exiting["membership_status"] == "EXITING"
    assert exiting["network_posture"] == "FROZEN"
    assert exiting["projected_monthly_revenue_cents"] == 0

    for enrollment_id in (ctx["e1"], ctx["e2"]):
        row = validate_success(api.get_enrollment(enrollment_id, NETWORK_ADMIN_HEADERS))
        assert row["status"] == "TRANSITION_PENDING"
        assert row["slot_committed"] is False

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["committed_slots"] == 0
    assert contract["available_slots"] == 4
    assert contract["status"] == "ACTIVE"


def test_the_exit_only_finalizes_once_the_last_transitioning_family_is_resolved(api):
    """Finalizing is refused while a child is still transitioning, then succeeds.

    With the child in TRANSITION_PENDING the finalization is refused and the provider stays
    in EXITING. Withdrawing the child resolves the last open family, so the identical call
    then reaches the only terminal membership state and terminates the money behind it.

    PRD: "Only once none of the provider's enrollments remains in `ENROLLED` or
    `TRANSITION_PENDING` status may the exit be finalized; attempting to finalize earlier
    returns `ERR_EXIT_TRANSITIONS_PENDING`."

    PRD: "Finalizing also terminates the money: every subsidy contract of that provider
    moves to `TERMINATED`, whether it was `ACTIVE` or `SUSPENDED_FOR_QUALITY` beforehand,
    and no further claim may be created or submitted against a terminated contract."

    Design: Corner/State Machines/complete_exit_bubbles_up_only_after_every_transitioning_enrollment_is_resolved
    """
    ctx = _home_with_one_subsidy_child()
    exit_network(ctx["provider_id"], exit_reason="RETIREMENT")

    validate_error(
        api.complete_exit(ctx["provider_id"], None, NETWORK_ADMIN_HEADERS),
        ApiErrorId.EXIT_TRANSITIONS_PENDING.value,
        409,
    )
    mid_exit = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert mid_exit["membership_status"] == "EXITING"

    withdrawn = withdraw_enrollment(ctx["e1"], ctx["provider_id"], "2026-08-31T00:00:00Z")
    assert withdrawn["status"] == "WITHDRAWN"

    exited = complete_exit(ctx["provider_id"])
    assert exited["membership_status"] == "EXITED"
    assert exited["network_posture"] == "FROZEN"

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["status"] == "TERMINATED"


def test_the_hold_cascade_skips_the_reconciled_sibling_claim(api):
    """Of three sibling claims only the DRAFT and SUBMITTED rows are frozen.

    June is walked to RECONCILED at 20 * 4500 == 90000, July is left SUBMITTED at the same
    90000, and August is left in DRAFT. Escalation holds July and August, each recording the
    status it came from, and gives July's provisional 90000 back to the contract. June keeps
    its verified valuation and its status, so the contract's claimed total is June's 90000
    alone.

    PRD: "Hop three moves every subsidy claim of those contracts that is in `DRAFT` or
    `SUBMITTED` status to `HELD`, recording the status it came from in `held_from_status`
    and setting `hold_reason` to the literal string `CONTRACT_SUSPENDED_FOR_QUALITY`; a
    claim held out of `SUBMITTED` additionally gives its `provisional_amount_cents` back to
    its contract's `claimed_amount_cents`, while a claim held out of `DRAFT` had consumed no
    authorization and therefore returns none."

    Design: Corner/State Machines/quality_escalation_holds_only_draft_and_submitted_claims_leaving_reconciled_alone
    """
    ctx = _billing_home(period_start_on="2026-06-01T00:00:00Z", absence_rate_pct=50)
    e1 = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]

    june = claim_walked_to(
        "RECONCILED", ctx["contract_id"], ctx["provider_id"], "2026-06",
        [claim_line(e1, 20, 0)],
    )
    assert june["final_amount_cents"] == 90000
    july = claim_walked_to(
        "SUBMITTED", ctx["contract_id"], ctx["provider_id"], "2026-07",
        [claim_line(e1, 20, 0)],
    )
    assert july["provisional_amount_cents"] == 90000
    august = claim_walked_to(
        "DRAFT", ctx["contract_id"], ctx["provider_id"], "2026-08",
        [claim_line(e1, 20, 0)],
    )

    review = review_at_cap_rejected_twice(
        ctx["provider_id"], ["QS-3"], "2026-08-31T00:00:00Z"
    )
    escalated = escalate_review(review["id"])
    assert escalated["status"] == "ESCALATED_TO_LICENSING"

    held_july = validate_success(api.get_claim(july["id"], FISCAL_OFFICER_HEADERS))
    assert held_july["status"] == "HELD"
    assert held_july["held_from_status"] == "SUBMITTED"
    assert held_july["hold_reason"] == "CONTRACT_SUSPENDED_FOR_QUALITY"

    held_august = validate_success(api.get_claim(august["id"], FISCAL_OFFICER_HEADERS))
    assert held_august["status"] == "HELD"
    assert held_august["held_from_status"] == "DRAFT"

    untouched = validate_success(api.get_claim(june["id"], FISCAL_OFFICER_HEADERS))
    assert untouched["status"] == "RECONCILED"
    assert untouched["final_amount_cents"] == 90000
    assert untouched["held_from_status"] is None

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["claimed_amount_cents"] == 90000
