"""Each declared error code raised by its own narrow precondition, with no side effect."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    COACH_A_HEADERS,
    COACH_B_HEADERS,
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    ApiErrorId,
    active_provider,
    assert_provider_posture,
    create_enrollment,
    create_enrollment_payload,
    create_food_claim_payload,
    create_order,
    create_visit_payload,
    exit_network,
    meal_line,
    open_review,
    order_line,
    post_remittance,
    provider_with_contract,
    reverse_remittance,
    set_clock,
    withdraw_enrollment,
)

# Local setup builders


def _enrolling_home(**apply_overrides):
    """An ACTIVE home entitled to enrollment support."""
    overrides = {"capacity_slots": 6}
    overrides.update(apply_overrides)
    return active_provider(
        apply_overrides=overrides,
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )


def _coaching_home():
    """An ACTIVE home entitled to coaching support."""
    return active_provider(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )


def _home_with_one_private_child():
    """An ACTIVE home holding a single private-pay child at 90000 cents."""
    ctx = _enrolling_home()
    ctx["e1"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=90000,
        subsidy_certified=False,
    )
    return ctx


# Own-entity state errors


def test_lifting_probation_from_a_home_that_never_had_it_is_refused(api):
    """Reinstatement is declared only out of probation, so an active home cannot be lifted.

    The home walked straight to ACTIVE and was never escalated, so the only declared source
    state of the transition is not the one it occupies. The refusal is a state conflict and
    it writes nothing: membership and version are exactly what they were.

    PRD: "A `NetworkAdmin` lifts probation only when the provider is in `PROBATION` and their
    `open_finding_count` has fallen to zero; the provider moves `PROBATION → ACTIVE`,
    `network_posture` is recomputed to `OPEN`, and the provider's `version` increments by one,
    making `ACTIVE → PROBATION → ACTIVE` a genuine cycle."

    Design: Corner/Errors/reinstate_an_active_provider_returns_invalid_provider_state
    """
    ctx = _enrolling_home()
    before = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert before["membership_status"] == "ACTIVE"

    validate_error(
        api.reinstate_provider(ctx["provider_id"], None, NETWORK_ADMIN_HEADERS),
        ApiErrorId.INVALID_PROVIDER_STATE.value,
        409,
    )

    after = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert_provider_posture(after, "ACTIVE", "OPEN")
    assert after["version"] == before["version"]


def test_withdrawing_a_departed_family_a_second_time_is_refused(api):
    """A withdrawn enrollment is terminal, and the second exit date is never stored.

    The first withdrawal recorded 2026-08-20 and released what there was to release. The
    second call is a state conflict, so the later date does not overwrite the stored one and
    the version does not move. The revenue projection shows the release ran exactly once.

    PRD: "`WITHDRAWN` and `TRANSFERRED` are both terminal for an enrollment."

    Design: Corner/Errors/withdraw_an_already_withdrawn_enrollment_returns_invalid_enrollment_state
    """
    ctx = _home_with_one_private_child()
    withdrawn = withdraw_enrollment(
        ctx["e1"]["id"], ctx["provider_id"], "2026-08-20T00:00:00Z"
    )
    assert withdrawn["status"] == "WITHDRAWN"

    validate_error(
        api.withdraw_enrollment(
            ctx["e1"]["id"], {"exit_on": "2026-08-25T00:00:00Z"}, ctx["headers"]
        ),
        ApiErrorId.INVALID_ENROLLMENT_STATE.value,
        409,
    )

    stored = validate_success(api.get_enrollment(ctx["e1"]["id"], NETWORK_ADMIN_HEADERS))
    assert stored["status"] == "WITHDRAWN"
    assert stored["version"] == withdrawn["version"]
    assert stored["exit_on"][:10] == "2026-08-20"

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["projected_monthly_revenue_cents"] == 0


def test_rejecting_a_plan_that_was_never_submitted_is_refused(api):
    """Rejection is declared only out of CAP_SUBMITTED, so an open review cannot be rejected.

    The review is sitting in its birth state with nothing to reject, so the call is a state
    conflict. The escalation counter is untouched, which matters because that counter is the
    only thing that ever authorizes an escalation.

    PRD: "A coach who is unsatisfied rejects the plan: the review must be `CAP_SUBMITTED`, it
    moves `CAP_SUBMITTED → CAP_REJECTED`, and `cap_rejection_count` increases by one, which is
    the counter that eventually authorizes escalation."

    Design: Corner/Errors/reject_cap_on_an_open_review_returns_invalid_review_state
    """
    ctx = _coaching_home()
    review = open_review(ctx["provider_id"], ["SUP-2"], "2026-09-15T00:00:00Z")
    assert review["status"] == "OPEN"
    assert review["cap_rejection_count"] == 0

    validate_error(
        api.reject_cap(review["id"], None, COACH_B_HEADERS),
        ApiErrorId.INVALID_REVIEW_STATE.value,
        409,
    )

    stored = validate_success(api.get_review(review["id"], NETWORK_ADMIN_HEADERS))
    assert stored["status"] == "OPEN"
    assert stored["cap_rejection_count"] == 0
    assert stored["version"] == review["version"]


def test_committing_a_priced_order_again_is_refused_and_never_re_discounts_it(api):
    """A committed order is terminal, so the pricing cannot be applied to itself twice.

    Five units earn no discount, so the order is priced at its gross 5000. A second commit
    is a state conflict rather than a second discounting pass, so the subtotal is still 5000
    — not 5000 with a discount applied to it — and the version has not moved.

    PRD: "`COMMITTED` is the order's only terminal state, and a committed order cannot be
    committed again."

    Design: Corner/Errors/commit_an_already_committed_order_returns_invalid_order_state
    """
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["GROUP_PURCHASING"]},
    )
    order = create_order(ctx["provider_id"], [order_line("WIPES-12", 1000, 5)])

    committed = validate_success(api.commit_order(order["id"], None, ctx["headers"]))
    assert committed["status"] == "COMMITTED"
    assert float(committed["discount_pct"]) == 0
    assert committed["subtotal_cents"] == 5000
    assert committed["total_cents"] == 5000

    validate_error(
        api.commit_order(order["id"], None, ctx["headers"]),
        ApiErrorId.INVALID_ORDER_STATE.value,
        409,
    )

    stored = validate_success(api.get_order(order["id"], NETWORK_ADMIN_HEADERS))
    assert stored["subtotal_cents"] == 5000
    assert stored["total_cents"] == 5000
    assert stored["version"] == committed["version"]


def test_reversing_a_reversed_payment_again_is_refused_and_never_double_subtracts(api):
    """A reversed remittance is terminal, so the ledger cannot be driven negative.

    Nothing is reconciled, so the whole 5000 is held as credit and the reversal takes exactly
    that back, leaving both ledger columns at zero. The second reversal is a state conflict:
    the stored reason is still the original one and the contract has not gone to -5000.

    PRD: "A `FiscalOfficer` supplies a `reversal_reason`; the remittance must be `POSTED`, and
    it moves `POSTED → REVERSED` with the reason recorded in `reversal_reason` — `REVERSED` is
    terminal."

    Design: Corner/Errors/reverse_an_already_reversed_remittance_returns_invalid_remittance_state
    """
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-08-01T00:00:00Z",
        },
    )
    remittance = post_remittance(
        ctx["contract_id"], "AG-DBL-1", 5000, received_on="2026-08-01T00:00:00Z"
    )
    assert remittance["unallocated_cents"] == 5000

    reversed_row = reverse_remittance(remittance["id"], "AGENCY_RECALL")
    assert reversed_row["status"] == "REVERSED"

    validate_error(
        api.reverse_remittance(
            remittance["id"], {"reversal_reason": "AGENCY_RECALL_AGAIN"}, FISCAL_OFFICER_HEADERS
        ),
        ApiErrorId.INVALID_REMITTANCE_STATE.value,
        409,
    )

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["remitted_cents"] == 0
    assert contract["unallocated_credit_cents"] == 0

    _, meta = validate_paginated(
        api.list_contract_remittances(ctx["contract_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1


# Posture, licensure and calendar errors


def test_a_home_that_has_begun_leaving_may_not_enroll_anyone(api):
    """Beginning an exit freezes the home, and a frozen home cannot write at all.

    The exit moved the home to EXITING, and that status maps to a frozen posture, so the
    enrollment is blocked by the posture gate even though six licensed places are empty and
    the child reference is unused. Nothing is stored.

    PRD: "A `FROZEN` posture blocks every provider-initiated write."

    PRD: "The mapping is total: `APPLICANT`, `PENDING_AGREEMENT`, `EXITING` and `EXITED` all
    map to `FROZEN`; `ACTIVE` maps to `OPEN`; `PROBATION` maps to `RESTRICTED`."

    Design: Corner/Errors/enrollment_create_while_provider_frozen_returns_provider_posture_blocked
    """
    ctx = _enrolling_home()
    exiting = exit_network(ctx["provider_id"], "RETIREMENT")
    assert_provider_posture(exiting, "EXITING", "FROZEN")

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                ctx["provider_id"],
                child_ref="CH-1",
                family_name="Alvarez",
                days_per_week=5,
                private_monthly_tuition_cents=90000,
                subsidy_certified=False,
                start_on="2026-08-05T00:00:00Z",
            ),
            ctx["headers"],
        ),
        ApiErrorId.PROVIDER_POSTURE_BLOCKED.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_enrollments({"provider_id": ctx["provider_id"]}, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_lapsed_licence_stops_enrollment_even_though_membership_is_still_active(api):
    """The licensure gate reads the clock, not the membership status.

    The licence ran out on 2026-08-15 and the clock now stands at 2026-09-01, so the home may
    not take another child. Nothing about the home changed when the licence lapsed: it is
    still an active member with an open posture, which is exactly why the gate has to be
    evaluated per request.

    PRD: "Next comes licensure: a provider whose `license_expires_on` falls earlier than the
    logical clock date cannot enroll anyone, and the attempt returns `ERR_LICENSE_EXPIRED`."

    Design: Corner/Errors/enrollment_create_after_the_license_lapses_returns_license_expired
    """
    ctx = _enrolling_home(license_expires_on="2026-08-15T00:00:00Z")
    assert ctx["agreement"]["status"] == "EXECUTED"

    set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                ctx["provider_id"],
                child_ref="CH-1",
                family_name="Alvarez",
                days_per_week=5,
                private_monthly_tuition_cents=90000,
                subsidy_certified=False,
                start_on="2026-09-01T00:00:00Z",
            ),
            ctx["headers"],
        ),
        ApiErrorId.LICENSE_EXPIRED.value,
        422,
    )

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert_provider_posture(provider, "ACTIVE", "OPEN")

    _, meta = validate_paginated(
        api.list_enrollments({"provider_id": ctx["provider_id"]}, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_corrective_plan_filed_after_the_deadline_is_refused(api):
    """The plan is ten days late, so the review never advances and stores no narrative.

    The deadline was 2026-08-10 and the clock stands at 2026-08-20, so the submission is
    refused. The review is still open with a null narrative, which keeps the coaching cycle
    where it was rather than half-advancing it.

    PRD: "The provider submits a plan by supplying a `cap_narrative`; the review must be in
    `OPEN` or `CAP_REJECTED` status, the review must belong to the acting provider, and the
    logical clock date must fall on or before `cap_due_on`, with a late submission refused as
    `ERR_CAP_DEADLINE_PASSED`."

    Design: Corner/Errors/submit_cap_after_the_deadline_returns_cap_deadline_passed
    """
    ctx = _coaching_home()
    review = open_review(ctx["provider_id"], ["SUP-2"], "2026-08-10T00:00:00Z")
    assert review["status"] == "OPEN"

    set_clock("2026-08-20T00:00:00Z")

    validate_error(
        api.submit_cap(
            review["id"],
            {"cap_narrative": "Storage rack anchored and staff retrained"},
            ctx["headers"],
        ),
        ApiErrorId.CAP_DEADLINE_PASSED.value,
        422,
    )

    stored = validate_success(api.get_review(review["id"], NETWORK_ADMIN_HEADERS))
    assert stored["status"] == "OPEN"
    assert stored["cap_narrative"] is None
    assert stored["cap_submitted_at"] is None


def test_a_visit_may_not_be_booked_for_yesterday_but_today_is_fine(api):
    """The calendar rule is strictly-before, so the clock date itself is still bookable.

    A date sixteen days behind the clock is refused. The identical request for the clock date
    is accepted and the visit is born scheduled, so the rule cannot be an on-or-before test.
    Only the accepted booking is on file.

    PRD: "A visit may not be scheduled for a date earlier than the logical clock date, which
    returns `ERR_VISIT_DATE_IN_PAST`."

    Design: Corner/Errors/schedule_a_coaching_visit_before_today_returns_visit_date_in_past
    """
    ctx = _coaching_home()

    validate_error(
        api.create_visit(
            create_visit_payload(
                ctx["provider_id"], "2026-07-15T00:00:00Z", focus_area="ENVIRONMENT"
            ),
            COACH_A_HEADERS,
        ),
        ApiErrorId.VISIT_DATE_IN_PAST.value,
        422,
    )

    accepted = validate_success(
        api.create_visit(
            create_visit_payload(
                ctx["provider_id"], "2026-08-01T00:00:00Z", focus_area="ENVIRONMENT"
            ),
            COACH_A_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_provider_visits(ctx["provider_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]


# Referential coherence and uniqueness errors


def test_a_meal_line_for_a_child_the_home_never_enrolled_voids_the_whole_filing(api):
    """One unknown child reference on the second line discards the lawful first line too.

    The first line names the home's only enrolled child and is entirely valid, but the second
    names a child who was never enrolled anywhere. The filing is refused as a whole, so the
    month is left unclaimed rather than partially accepted.

    PRD: "Every `child_ref` on a meal line must match the `child_ref` of one of the claiming
    provider's enrollments, or the filing is refused with `ERR_MEAL_LINE_CHILD_UNKNOWN`."

    Design: Corner/Errors/food_claim_meal_line_for_a_child_who_is_not_enrolled_returns_meal_line_child_unknown
    """
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT", "FOOD_PROGRAM"]},
    )
    enrolled = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=90000,
        subsidy_certified=False,
    )
    assert enrolled["child_ref"] == "CH-1"

    validate_error(
        api.create_food_claim(
            create_food_claim_payload(
                ctx["provider_id"],
                "2026-08",
                [
                    meal_line("CH-1", "2026-08-03T00:00:00Z", breakfasts=1, lunches=1, snacks=1),
                    meal_line("CH-9", "2026-08-03T00:00:00Z", breakfasts=1, lunches=1, snacks=1),
                ],
            ),
            ctx["headers"],
        ),
        ApiErrorId.MEAL_LINE_CHILD_UNKNOWN.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_provider_food_claims(ctx["provider_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_child_reference_is_reusable_only_once_the_first_enrollment_has_ended(api):
    """The same reference is refused while the family is live and accepted after they leave.

    Licensed capacity is six and only one place is used, so capacity is not what refuses the
    duplicate. Once the first enrollment is withdrawn it is terminal and no longer occupies
    the reference, so the identical request is accepted as a brand-new row. Both rows remain
    on file and only the live one contributes tuition.

    PRD: "Then the aggregate constraints: the count of the provider's enrollments in
    `ENROLLED` or `TRANSITION_PENDING` status must be strictly less than the provider's
    licensed `capacity_slots`, otherwise `ERR_CAPACITY_EXCEEDED` is returned, and the supplied
    `child_ref` must not already be in use by any non-terminal enrollment of the same
    provider, otherwise `ERR_DUPLICATE_CHILD_REF` is returned."

    Design: Corner/Errors/second_enrollment_reusing_a_live_child_ref_returns_duplicate_child_ref
    """
    ctx = _home_with_one_private_child()
    repeat = create_enrollment_payload(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=3,
        private_monthly_tuition_cents=60000,
        subsidy_certified=False,
        start_on="2026-08-05T00:00:00Z",
    )

    validate_error(
        api.create_enrollment(repeat, ctx["headers"]),
        ApiErrorId.DUPLICATE_CHILD_REF.value,
        409,
    )

    withdrawn = withdraw_enrollment(
        ctx["e1"]["id"], ctx["provider_id"], "2026-08-10T00:00:00Z"
    )
    assert withdrawn["status"] == "WITHDRAWN"

    replacement = validate_success(
        api.create_enrollment(
            create_enrollment_payload(
                ctx["provider_id"],
                child_ref="CH-1",
                family_name="Alvarez",
                days_per_week=3,
                private_monthly_tuition_cents=60000,
                subsidy_certified=False,
                start_on="2026-08-11T00:00:00Z",
            ),
            ctx["headers"],
        ),
        201,
    )
    assert replacement["status"] == "ENROLLED"
    assert replacement["id"] != ctx["e1"]["id"]

    _, meta = validate_paginated(
        api.list_enrollments({"provider_id": ctx["provider_id"]}, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["projected_monthly_revenue_cents"] == 60000
