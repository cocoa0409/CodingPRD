"""Cancellation settlement: the whole-life closure identity, the deficiency-fee
tier pinned to the pre-fee residual, the five-hop suspension cascade, and the two
chargeback bases.
"""

from test_helpers import (
    ApiErrorId,
    assert_note_settlement_residual_zero,
    commission_cap_cents,
    deficiency_fee_cents,
    factories,
    fixtures,
    note_settlement_residual_cents,
    pro_rata_unearned_premium_cents,
    rule_of_78_rebate_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ANALYST_EXECUTOR,
    ANALYST_NOTICE,
    ANALYST_ORIGIN,
    ANALYST_POA,
    COMPLIANCE,
    make_producer_agent_headers,
)


def _cancelled_600k(
    api,
    policy_number="MC-S-9301",
    agent_payload=None,
    executor_headers=None,
):
    """The 600k note driven all the way to CANCELLATION_REQUESTED.

    Activated at 2026-08-15, serviced on 2026-10-12 so installment 1 is past due
    and carries a 4497 fee, noticed the same day with an effective cancel date of
    2026-10-22, and cancelled under the power of attorney on that date by a handle
    that differs from the notice issuer.
    """
    bundle = fixtures.canonical_600k_note(
        api, policy_number=policy_number, agent_payload=agent_payload
    )
    fixtures.delinquent_note(api, bundle=bundle, service_at="2026-10-12T00:00:00Z")
    fixtures.noticed_note(api, bundle=bundle)
    fixtures.cancelled_note(
        api,
        bundle=bundle,
        execute_at="2026-10-22T00:00:00Z",
        executor_headers=executor_headers or ANALYST_POA,
    )
    return bundle


def _post_return(api, bundle, carrier_returned_cents, posted_date):
    return validate_success(
        api.post_carrier_return(
            bundle["cancel_request_id"],
            factories.return_posting(carrier_returned_cents, posted_date),
            bundle["insurer_headers"],
        ),
        200,
    )


def _chargebacks_of(api, agreement_id):
    rows, meta = validate_paginated(
        api.list_agent_chargebacks(
            COMPLIANCE, {"agreement_id": agreement_id, "limit": 50}
        )
    )
    return rows, meta


class TestNoteSettlementResidualZero:
    """The whole-life closure identity across three settlement channels: the
    rebate, the carrier return and the written-off deficiency."""

    def _cancelled(self, api):
        bundle = _cancelled_600k(api, executor_headers=ANALYST_EXECUTOR)
        assert bundle["activated"]["total_of_payments_cents"] == 539650
        assert bundle["late_fee_amount_cents"] == 4497
        assert bundle["notice"]["effective_cancel_date"] == "2026-10-22"
        assert bundle["notice"]["past_due_amount_cents"] == 94438, (
            "the snapshot is the 89941 past-due installment plus the 4497 fee"
        )
        return bundle

    def test_the_power_of_attorney_nets_the_rebate_against_finance_charge(self, api):
        """The rebate reduces unpaid finance charge and leaves principal alone.

        The PRD states: "The unearned finance charge rebate is granted by the rule
        of section 3.6 and `unpaid_finance_charge_cents` is reduced by it."

        Design: Difficulty/compensating_invariant/note_settlement_residual_zero_across_power_of_attorney_and_carrier_return
        """
        bundle = self._cancelled(api)
        execution = bundle["execution"]

        assert execution["requests_created"] == 1
        assert execution["rebate_applied_cents"] == rule_of_78_rebate_cents(37650, 6, 6)
        assert execution["rebate_applied_cents"] == 37650, (
            "not one payment was ever posted, so all six installments are "
            "unretired and the sum-of-digits rebate returns the whole charge"
        )
        assert execution["estimated_unearned_premium_cents"] == 516164
        assert execution["gross_balance_cents"] == 502000, (
            "principal plus the POST-rebate finance charge, which the rebate has "
            "just driven to zero; the late fee balance is not part of the figure"
        )

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["principal_balance_cents"] == 502000, (
            "netting the rebate against principal instead of finance charge is "
            "the failure this fixture is built to catch"
        )
        assert agreement["unpaid_finance_charge_cents"] == 0
        assert agreement["late_fee_balance_cents"] == 4497
        assert agreement["unapplied_credit_cents"] == 0
        assert agreement["delinquency_stage"] == "CANCELLATION_REQUESTED"

    def test_the_estimate_is_the_pro_rata_share_of_the_half_open_term(self, api):
        """The carrier request carries the pro-rata estimate of the unearned days.

        The PRD states: "Otherwise the pro-rata figure is the policy's
        `financed_premium_cents` multiplied by the unearned days, divided by the
        term length in days, rounded half up."

        Design: Difficulty/compensating_invariant/note_settlement_residual_zero_across_power_of_attorney_and_carrier_return
        """
        bundle = self._cancelled(api)

        request = validate_success(
            api.get_carrier_cancellation_request(
                bundle["cancel_request_id"], ANALYST_ORIGIN
            ),
            200,
        )

        assert request["estimate_method"] == "PRO_RATA"
        assert request["computed_unearned_premium_cents"] == (
            pro_rata_unearned_premium_cents(600000, 365 - 51, 365)
        )
        assert request["computed_unearned_premium_cents"] == 516164, (
            "the term is 365 half-open days from 2026-09-01 to 2027-09-01, and "
            "51 of them are earned by the 2026-10-22 cancellation date"
        )

    def test_the_carrier_return_lands_in_the_pinned_credit_order(self, api):
        """Principal first, then finance charge, then late fees.

        The PRD states: "and the credit is applied to the note in a pinned order —
        first reducing `principal_balance_cents`, then `unpaid_finance_charge_cents`,
        then `late_fee_balance_cents`, with anything left over increasing
        `unapplied_credit_cents`."

        Design: Difficulty/compensating_invariant/note_settlement_residual_zero_across_power_of_attorney_and_carrier_return
        """
        bundle = self._cancelled(api)

        posting = _post_return(api, bundle, 400000, "2026-11-10")

        assert posting["status"] == "RETURN_POSTED"
        assert posting["carrier_returned_cents"] == 400000
        assert posting["variance_cents"] == -116164, (
            "variance_cents is carrier_returned_cents minus "
            "computed_unearned_premium_cents, negative when the carrier returned "
            "less than the platform estimated"
        )

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["unearned_premium_received_cents"] == 400000
        assert agreement["principal_balance_cents"] == 102000, (
            "the whole 400000 credit was absorbed by the 502000 principal"
        )
        assert agreement["unpaid_finance_charge_cents"] == 0
        assert agreement["late_fee_balance_cents"] == 4497, (
            "nothing reached the late fee bucket"
        )
        assert agreement["unapplied_credit_cents"] == 0

    def test_the_settlement_residual_is_exactly_zero(self, api):
        """Every cent of the note is paid, rebated, returned or still owed.

        The PRD states: "The second, **note settlement residual**, must be exactly
        zero once an agreement has reached `CANCELLED_DEFICIENT` or `CLOSED_ZERO`."

        Design: Difficulty/compensating_invariant/note_settlement_residual_zero_across_power_of_attorney_and_carrier_return
        """
        bundle = self._cancelled(api)
        _post_return(api, bundle, 400000, "2026-11-10")

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["status"] == "CANCELLED_DEFICIENT"
        assert agreement["delinquency_stage"] == "CANCELLED"

        assert_note_settlement_residual_zero(
            total_of_payments_cents=539650,
            assessed_late_fees_cents=4497,
            posted_payments_cents=0,
            rebate_granted_cents=37650,
            unearned_premium_received_cents=400000,
            deficiency_before_fee_cents=106497,
            unapplied_credit_cents=0,
        )

    def test_the_deficiency_fee_sits_outside_the_identity(self, api):
        """The fee is new revenue, so folding it in would show as a drift of 5000.

        The PRD states: "When the residual is strictly positive, the financing
        status moves `ACTIVE` → `CANCELLED_DEFICIENT` and `deficiency_balance_cents`
        is set to the residual plus the cancellation fee."

        Design: Difficulty/compensating_invariant/note_settlement_residual_zero_across_power_of_attorney_and_carrier_return
        """
        bundle = self._cancelled(api)
        _post_return(api, bundle, 400000, "2026-11-10")

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["deficiency_balance_cents"] == 106497 + deficiency_fee_cents(
            106497
        )
        assert agreement["deficiency_balance_cents"] == 111497

        leaked = note_settlement_residual_cents(
            total_of_payments_cents=539650,
            assessed_late_fees_cents=4497,
            posted_payments_cents=0,
            rebate_granted_cents=37650,
            unearned_premium_received_cents=400000,
            deficiency_before_fee_cents=111497,
            unapplied_credit_cents=0,
        )
        assert leaked == -5000, (
            "letting the cancellation fee into the identity produces exactly "
            "-5000, which is why the identity is keyed on the pre-fee residual"
        )

    def test_the_return_posting_touches_no_installment_row(self, api):
        """After cancellation the balances, not the schedule, are the accounting.

        The PRD states: "and in neither branch is any installment row touched —
        once coverage has been pulled, the schedule has stopped being the
        accounting of record and the note's balances are."

        Design: Difficulty/compensating_invariant/note_settlement_residual_zero_across_power_of_attorney_and_carrier_return
        """
        bundle = self._cancelled(api)
        _post_return(api, bundle, 400000, "2026-11-10")

        rows, meta = validate_paginated(
            api.list_installments(bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 100})
        )
        assert meta["total_count"] == 6
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAST_DUE", (
            "PAST_DUE installments stay past due and are settled at the balance "
            "level rather than the schedule level"
        )
        assert rows[0]["paid_cents"] == 0
        assert [row["status"] for row in rows[1:]] == ["VOIDED"] * 5, (
            "every installment still SCHEDULED with a paid_cents of zero moves to "
            "VOIDED at execution"
        )


class TestDeficiencyFeeTierKeyedOnPreFeeBalance:
    """The cancellation fee is part of the final deficiency, yet it never enters
    its own tier lookup."""

    def _settled_on_the_tier_boundary(self, api):
        """A 481497 return leaves a pre-fee residual of exactly 25000."""
        bundle = _cancelled_600k(api, policy_number="MC-S-4001")
        bundle["posting"] = _post_return(api, bundle, 481497, "2026-10-30")
        return bundle

    def test_the_execution_grants_the_whole_finance_charge_as_rebate(self, api):
        """Six unretired installments rebate the entire finance charge.

        The PRD states: "Under the `RULE_OF_78` method, the rebate is
        `finance_charge_cents` multiplied by *r*, multiplied by *r* plus one,
        divided by the product of `installment_count` and `installment_count` plus
        one, rounded half up".

        Design: Difficulty/combinatorial_formula/deficiency_fee_tier_keyed_on_pre_fee_balance
        """
        bundle = _cancelled_600k(api, policy_number="MC-S-4001")

        execution = bundle["execution"]
        assert execution["requests_created"] == 1
        assert execution["rebate_applied_cents"] == 37650
        assert execution["estimated_unearned_premium_cents"] == 516164
        assert execution["gross_balance_cents"] == 502000, (
            "the gross balance is principal plus the post-rebate finance charge, "
            "and the rebate has just taken that charge to zero"
        )

    def test_the_tier_is_keyed_on_the_pre_fee_residual(self, api):
        """A residual of exactly 25000 draws the 2500 fee, not the 5000 one.

        The PRD states: "That figure, and only that figure, keys the cancellation
        fee: a residual of zero or less draws no fee; a positive residual of 250
        dollars or less draws a fee of 25 dollars; a residual above 250 dollars
        draws a fee of 50 dollars."

        Design: Difficulty/combinatorial_formula/deficiency_fee_tier_keyed_on_pre_fee_balance
        """
        bundle = self._settled_on_the_tier_boundary(api)

        assert bundle["posting"]["status"] == "RETURN_POSTED"
        assert bundle["posting"]["variance_cents"] == -34667, (
            "481497 returned against a 516164 estimate"
        )

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["principal_balance_cents"] == 20503, (
            "the 481497 credit is applied principal-first, leaving 502000 - 481497"
        )
        assert agreement["unpaid_finance_charge_cents"] == 0
        assert agreement["late_fee_balance_cents"] == 4497
        assert agreement["unapplied_credit_cents"] == 0

        pre_fee = 20503 + 0 + 4497 - 0
        assert pre_fee == 25000, (
            "the residual lands exactly on the 250-dollar tier boundary"
        )
        assert deficiency_fee_cents(pre_fee) == 2500
        assert agreement["deficiency_balance_cents"] == 27500
        assert agreement["status"] == "CANCELLED_DEFICIENT"

    def test_the_fee_never_enters_its_own_tier_input(self, api):
        """A self-referential reading would report 30000 instead of 27500.

        The PRD states: "The evaluation order is pinned precisely because the fee
        is itself part of the final deficiency — the fee never enters its own tier
        input."

        Design: Difficulty/combinatorial_formula/deficiency_fee_tier_keyed_on_pre_fee_balance
        """
        bundle = self._settled_on_the_tier_boundary(api)

        assert deficiency_fee_cents(25000) == 2500
        assert deficiency_fee_cents(27500) == 5000, (
            "feeding the fee back in would cross the boundary and select the "
            "50-dollar tier"
        )

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["deficiency_balance_cents"] == 27500, (
            "25000 is the only residual at which the pinned reading and the "
            "self-referential reading disagree, and the pinned one governs"
        )
        assert agreement["deficiency_balance_cents"] != 30000

    def test_the_chargeback_takes_the_smaller_of_deficiency_and_commission(self, api):
        """A generous commission means the whole deficiency comes back.

        The PRD states: "Under `COMMISSION_CAPPED`, the commission the agency
        earned is the note's `total_premium_cents` multiplied by the agency's
        `agent_commission_bps`, divided by 10000 and rounded half up, and
        `agent_chargeback_cents` is the smaller of `deficiency_balance_cents` and
        that commission — a generous commission means the whole deficiency comes
        back."

        Design: Difficulty/combinatorial_formula/deficiency_fee_tier_keyed_on_pre_fee_balance
        """
        bundle = self._settled_on_the_tier_boundary(api)

        commission = commission_cap_cents(600000, 1200)
        assert commission == 72000
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["agent_chargeback_cents"] == 27500 == min(27500, commission)

        rows, meta = _chargebacks_of(api, bundle["agreement_id"])
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 27500
        assert rows[0]["basis"] == "COMMISSION_CAPPED"

        agent = validate_success(api.get_agent(bundle["agent_id"], COMPLIANCE), 200)
        assert agent["status"] == "ACTIVE", (
            "27500 of exposure is far below the 500000 liability cap"
        )
        assert agent["outstanding_chargeback_cents"] == 27500

    def test_the_settlement_identity_holds_on_the_tier_boundary(self, api):
        """The closure identity is zero with the pre-fee residual of 25000.

        The PRD states: "In words: every dollar of the note is either paid by the
        insured, rebated as unearned finance charge, returned by a carrier, or
        still owed as a deficiency."

        Design: Difficulty/combinatorial_formula/deficiency_fee_tier_keyed_on_pre_fee_balance
        """
        self._settled_on_the_tier_boundary(api)

        assert_note_settlement_residual_zero(
            total_of_payments_cents=539650,
            assessed_late_fees_cents=4497,
            posted_payments_cents=0,
            rebate_granted_cents=37650,
            unearned_premium_received_cents=481497,
            deficiency_before_fee_cents=25000,
            unapplied_credit_cents=0,
        )


def _second_draft_for_the_same_agency(api, bundle):
    """A DRAFT note that shares nothing with the cancelled note but the agency."""
    second = validate_success(
        api.create_agreement(
            factories.agreement(
                bundle["insured_id"],
                bundle["agent_id"],
                bundle["rule_id"],
                first_installment_due_date="2026-12-01",
            ),
            ANALYST_ORIGIN,
        ),
        201,
    )
    validate_success(
        api.attach_policy(
            second["id"],
            factories.financed_policy(
                bundle["insurer_id"],
                policy_number="MC-B-2002",
                effective_date="2026-12-01",
                expiration_date="2027-12-01",
            ),
            ANALYST_ORIGIN,
        ),
        201,
    )
    bundle["second_agreement_id"] = second["id"]
    return bundle


class TestReturnPostingToAgencySuspensionCascade:
    """One carrier cheque settles a request, credits a note, mints a chargeback,
    suspends an agency and blocks an unrelated draft."""

    def _armed(self, api):
        """A reserve-capped agency holding a cancelled note and a spare draft."""
        bundle = _cancelled_600k(
            api,
            policy_number="MC-B-2001",
            agent_payload=factories.reserve_capped_agent(),
        )
        _second_draft_for_the_same_agency(api, bundle)
        return bundle

    def test_the_spare_draft_is_submittable_before_the_posting(self, api):
        """Hop 5's victim is healthy until the cascade reaches it.

        The PRD states: "the producing agency must be `ACTIVE`, or
        `ERR_AGENT_SUSPENDED`".

        Design: Difficulty/transitive_cascade/return_posting_to_agency_suspension_cascade
        """
        bundle = self._armed(api)

        agent = validate_success(api.get_agent(bundle["agent_id"], COMPLIANCE), 200)
        assert agent["status"] == "ACTIVE"
        assert agent["outstanding_chargeback_cents"] == 0
        assert agent["chargeback_reserve_balance_cents"] == 50000

        submitted = validate_success(
            api.submit_agreement(bundle["second_agreement_id"], ANALYST_ORIGIN), 200
        )
        assert submitted["status"] == "PENDING_VERIFICATION", (
            "the spare draft prices and submits cleanly while the agency is ACTIVE"
        )

    def test_hop_one_settles_the_carrier_request(self, api):
        """The posting moves the request terminal and stamps the variance.

        The PRD states: "A strictly positive return moves the request `REQUESTED`
        → `RETURN_POSTED`: `variance_cents` is stamped as `carrier_returned_cents`
        minus `computed_unearned_premium_cents`, which is negative whenever the
        carrier returned less than the platform estimated".

        Design: Difficulty/transitive_cascade/return_posting_to_agency_suspension_cascade
        """
        bundle = self._armed(api)

        request = validate_success(
            api.get_carrier_cancellation_request(
                bundle["cancel_request_id"], COMPLIANCE
            ),
            200,
        )
        assert request["estimate_method"] == "PRO_RATA"
        assert request["computed_unearned_premium_cents"] == 516164

        posting = _post_return(api, bundle, 400000, "2026-10-22")

        assert posting["status"] == "RETURN_POSTED"
        assert posting["carrier_returned_cents"] == 400000
        assert posting["variance_cents"] == -116164

    def test_hop_two_settles_the_note_into_a_deficiency(self, api):
        """Closing the final request credits the note and computes the deficiency.

        The PRD states: "When the posting that closes the final outstanding request
        lands — that is, when every request of the note has reached either
        `RETURN_POSTED` or `CLOSED_NO_RETURN` — the note settles."

        Design: Difficulty/transitive_cascade/return_posting_to_agency_suspension_cascade
        """
        bundle = self._armed(api)

        _post_return(api, bundle, 400000, "2026-10-22")

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["unearned_premium_received_cents"] == 400000
        assert agreement["principal_balance_cents"] == 102000
        assert agreement["unpaid_finance_charge_cents"] == 0, (
            "the 37650 rebate zeroed the finance charge at execution"
        )
        assert agreement["late_fee_balance_cents"] == 4497
        assert agreement["status"] == "CANCELLED_DEFICIENT"
        assert agreement["delinquency_stage"] == "CANCELLED"
        assert agreement["deficiency_balance_cents"] == 106497 + deficiency_fee_cents(
            106497
        )
        assert agreement["deficiency_balance_cents"] == 111497

    def test_hop_three_mints_a_reserve_capped_chargeback(self, api):
        """The headroom, not the commission, caps a reserve-capped agency.

        The PRD states: "Under `RESERVE_CAPPED`, the agency's remaining headroom is
        its `chargeback_liability_cap_cents` minus its current
        `outstanding_chargeback_cents`, floored at zero so a fully exposed agency
        has no headroom at all, and `agent_chargeback_cents` is the smaller of
        `deficiency_balance_cents` and that headroom".

        Design: Difficulty/transitive_cascade/return_posting_to_agency_suspension_cascade
        """
        bundle = self._armed(api)
        _post_return(api, bundle, 400000, "2026-10-22")

        rows, meta = _chargebacks_of(api, bundle["agreement_id"])
        assert meta["total_count"] == 1, "exactly one chargeback row per deficiency"
        row = rows[0]
        assert row["status"] == "PENDING"
        assert row["basis"] == "RESERVE_CAPPED"
        assert row["offset_applied_cents"] == 0
        assert row["reason"] == "CANCELLATION_DEFICIENCY"
        assert row["amount_cents"] == min(111497, 25000 - 0) == 25000

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["agent_chargeback_cents"] == 25000, (
            "the 72000 commission cap is irrelevant to a RESERVE_CAPPED agency"
        )

    def test_hop_four_suspends_the_agency_without_consuming_reserve(self, api):
        """Exposure that reaches the cap suspends; the reserve is untouched.

        The PRD states: "if counting the new row brings that total to or above the
        agency's `chargeback_liability_cap_cents`, the agency moves `ACTIVE` →
        `SUSPENDED_FOR_CHARGEBACKS` and its `version` advances, which immediately
        blocks any further origination naming it."

        Design: Difficulty/transitive_cascade/return_posting_to_agency_suspension_cascade
        """
        bundle = self._armed(api)
        before = validate_success(api.get_agent(bundle["agent_id"], COMPLIANCE), 200)
        _post_return(api, bundle, 400000, "2026-10-22")

        agent = validate_success(api.get_agent(bundle["agent_id"], COMPLIANCE), 200)
        assert agent["status"] == "SUSPENDED_FOR_CHARGEBACKS"
        assert agent["outstanding_chargeback_cents"] == 25000, (
            "25000 of amount_cents minus 0 of offset_applied_cents"
        )
        assert agent["chargeback_reserve_balance_cents"] == 50000, (
            "a chargeback books exposure; it does not consume reserve until it is "
            "offset"
        )
        assert agent["version"] > before["version"]

    def test_hop_five_blocks_the_unrelated_draft(self, api):
        """A note the posting never mentioned becomes unsubmittable.

        The PRD states: "Both suspensions block new origination identically: any
        attempt to create, submit or restructure an agreement naming a suspended
        agency is refused with `ERR_AGENT_SUSPENDED` (HTTP 422)."

        Design: Difficulty/transitive_cascade/return_posting_to_agency_suspension_cascade
        """
        bundle = self._armed(api)
        _post_return(api, bundle, 400000, "2026-10-22")

        validate_error(
            api.submit_agreement(bundle["second_agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.AGENT_SUSPENDED.value,
            422,
        )

        second = validate_success(
            api.get_agreement(bundle["second_agreement_id"], ANALYST_ORIGIN), 200
        )
        assert second["status"] == "DRAFT", (
            "the refusal left the spare note exactly where it was, five hops away "
            "from the carrier cheque that caused it"
        )

    def test_the_cascade_unwinds_along_the_same_chain(self, api):
        """Offsetting the chargeback restores the agency and the spare draft.

        The PRD states: "When the recomputed exposure falls strictly below the
        agency's `chargeback_liability_cap_cents` and the agency is sitting in
        `SUSPENDED_FOR_CHARGEBACKS`, the agency returns to `ACTIVE` and its
        `version` advances — the suspension is released by settlement, not by
        time."

        Design: Difficulty/transitive_cascade/return_posting_to_agency_suspension_cascade
        """
        bundle = self._armed(api)
        _post_return(api, bundle, 400000, "2026-10-22")
        chargeback = _chargebacks_of(api, bundle["agreement_id"])[0][0]
        current = validate_success(
            api.get_agent_chargeback(chargeback["id"], COMPLIANCE), 200
        )

        offset = validate_success(
            api.offset_chargeback(
                chargeback["id"],
                factories.chargeback_offset(25000, current["version"]),
                COMPLIANCE,
            ),
            200,
        )

        assert offset["status"] == "OFFSET", (
            "an offset that exactly equals the remainder settles the row"
        )
        assert offset["offset_applied_cents"] == 25000

        agent = validate_success(api.get_agent(bundle["agent_id"], COMPLIANCE), 200)
        assert agent["status"] == "ACTIVE"
        assert agent["outstanding_chargeback_cents"] == 0
        assert agent["chargeback_reserve_balance_cents"] == 25000, (
            "the offset subtracts the same amount from the reserve"
        )

        resubmitted = validate_success(
            api.submit_agreement(bundle["second_agreement_id"], ANALYST_ORIGIN), 200
        )
        assert resubmitted["status"] == "PENDING_VERIFICATION"
        assert resubmitted["amount_financed_cents"] == 502000, (
            "the spare note becomes submittable again, proving hop 5 was caused by "
            "hop 4 and nothing else"
        )


class TestCommissionCappedVersusReserveCappedChargeback:
    """Two agencies, byte-identical notes, an identical deficiency — and two
    different chargebacks."""

    def _two_agencies_two_identical_notes(self, api):
        """Note A under a commission-capped agency, note B under a reserve-capped
        one, both cancelled under the power of attorney on 2026-10-22."""
        ctx_a = fixtures.origination_context(api)
        agent_b = validate_success(
            api.create_agent(factories.reserve_capped_agent(), COMPLIANCE), 201
        )
        ctx_b = dict(ctx_a)
        ctx_b["agent"] = agent_b
        ctx_b["agent_id"] = agent_b["id"]
        ctx_b["agent_headers"] = make_producer_agent_headers(agent_b["id"])

        note_a = fixtures.verified_agreement(
            api,
            ctx=ctx_a,
            policies=[
                factories.financed_policy(
                    ctx_a["insurer_id"], policy_number="MC-A-2001"
                )
            ],
        )
        note_b = fixtures.verified_agreement(
            api,
            ctx=ctx_b,
            policies=[
                factories.financed_policy(
                    ctx_b["insurer_id"], policy_number="MC-B-2001"
                )
            ],
        )

        fixtures.set_clock(api, "2026-09-01T00:00:00Z")
        for note in (note_a, note_b):
            note["activated"] = validate_success(
                api.activate_agreement(note["agreement_id"], ANALYST_ORIGIN), 200
            )
        fixtures.advance_and_service(api, "2026-10-12T00:00:00Z")
        for note in (note_a, note_b):
            validate_success(
                api.issue_cancellation_notice(note["agreement_id"], ANALYST_NOTICE), 201
            )
        fixtures.set_clock(api, "2026-10-22T00:00:00Z")
        for note in (note_a, note_b):
            note["execution"] = validate_success(
                api.execute_cancellation(note["agreement_id"], ANALYST_POA), 200
            )
            rows, meta = validate_paginated(
                api.list_carrier_cancellation_requests(
                    COMPLIANCE, {"agreement_id": note["agreement_id"], "limit": 10}
                )
            )
            assert meta["total_count"] == 1
            note["cancel_request_id"] = rows[0]["id"]
        return note_a, note_b

    def _both_settled(self, api):
        note_a, note_b = self._two_agencies_two_identical_notes(api)
        note_a["posting"] = _post_return(api, note_a, 400000, "2026-10-30")
        note_b["posting"] = _post_return(api, note_b, 400000, "2026-10-30")
        return note_a, note_b

    def test_the_two_notes_are_identical_up_to_the_deficiency(self, api):
        """The variant switch is the only difference between the two notes.

        The PRD states: "When the residual is strictly positive, the financing
        status moves `ACTIVE` → `CANCELLED_DEFICIENT` and `deficiency_balance_cents`
        is set to the residual plus the cancellation fee."

        Design: Difficulty/dual_variant_calc/commission_capped_vs_reserve_capped_chargeback_divergence
        """
        note_a, note_b = self._both_settled(api)

        for note in (note_a, note_b):
            assert note["activated"]["amount_financed_cents"] == 502000
            assert note["activated"]["finance_charge_cents"] == 37650
            agreement = fixtures.read_agreement(api, note["agreement_id"])
            assert agreement["status"] == "CANCELLED_DEFICIENT"
            assert agreement["delinquency_stage"] == "CANCELLED"
            assert agreement["unearned_premium_received_cents"] == 400000
            assert agreement["principal_balance_cents"] == 102000
            assert agreement["unpaid_finance_charge_cents"] == 0
            assert agreement["late_fee_balance_cents"] == 4497
            assert agreement["deficiency_balance_cents"] == 111497, (
                "106497 of residual plus the 5000 fee, identical on both notes"
            )
        assert note_a["posting"]["status"] == "RETURN_POSTED"
        assert note_a["posting"]["variance_cents"] == -116164
        assert note_b["posting"]["variance_cents"] == -116164

    def test_the_commission_capped_variant_charges_the_earned_commission(self, api):
        """A 72000 commission caps the chargeback well below the deficiency.

        The PRD states: "Under `COMMISSION_CAPPED`, the commission the agency
        earned is the note's `total_premium_cents` multiplied by the agency's
        `agent_commission_bps`, divided by 10000 and rounded half up, and
        `agent_chargeback_cents` is the smaller of `deficiency_balance_cents` and
        that commission — a generous commission means the whole deficiency comes
        back."

        Design: Difficulty/dual_variant_calc/commission_capped_vs_reserve_capped_chargeback_divergence
        """
        note_a, _note_b = self._both_settled(api)

        rows, meta = _chargebacks_of(api, note_a["agreement_id"])
        assert meta["total_count"] == 1
        assert rows[0]["basis"] == "COMMISSION_CAPPED"
        assert rows[0]["amount_cents"] == commission_cap_cents(600000, 1200) == 72000
        assert rows[0]["amount_cents"] == min(111497, 72000)

        agreement = fixtures.read_agreement(api, note_a["agreement_id"])
        assert agreement["agent_chargeback_cents"] == 72000

    def test_the_reserve_capped_variant_charges_only_the_headroom(self, api):
        """The same deficiency yields 25000 when the cap is the binding constraint.

        The PRD states: "Under `RESERVE_CAPPED`, the agency's remaining headroom is
        its `chargeback_liability_cap_cents` minus its current
        `outstanding_chargeback_cents`, floored at zero so a fully exposed agency
        has no headroom at all, and `agent_chargeback_cents` is the smaller of
        `deficiency_balance_cents` and that headroom — an identical deficiency on
        an identical note therefore produces a smaller chargeback for a
        reserve-capped agency, and can push it onto its cap."

        Design: Difficulty/dual_variant_calc/commission_capped_vs_reserve_capped_chargeback_divergence
        """
        _note_a, note_b = self._both_settled(api)

        rows, meta = _chargebacks_of(api, note_b["agreement_id"])
        assert meta["total_count"] == 1
        assert rows[0]["basis"] == "RESERVE_CAPPED"
        assert rows[0]["amount_cents"] == min(111497, 25000 - 0) == 25000, (
            "the 72000 commission the agency earned is irrelevant under this basis"
        )

        agreement = fixtures.read_agreement(api, note_b["agreement_id"])
        assert agreement["agent_chargeback_cents"] == 25000

    def test_only_the_reserve_capped_agency_is_suspended(self, api):
        """The cap comparison, not the deficiency, decides the suspension.

        The PRD states: "The `chargeback_basis` is either `COMMISSION_CAPPED`,
        under which the agency absorbs a deficiency only up to the commission it
        earned, or `RESERVE_CAPPED`, under which it absorbs a deficiency only up to
        its remaining liability headroom."

        Design: Difficulty/dual_variant_calc/commission_capped_vs_reserve_capped_chargeback_divergence
        """
        note_a, note_b = self._both_settled(api)

        agent_a = validate_success(
            api.get_agent(note_a["agent_id"], COMPLIANCE), 200
        )
        assert agent_a["status"] == "ACTIVE", (
            "72000 of exposure stays strictly below the 500000 liability cap"
        )
        assert agent_a["outstanding_chargeback_cents"] == 72000

        agent_b = validate_success(
            api.get_agent(note_b["agent_id"], COMPLIANCE), 200
        )
        assert agent_b["status"] == "SUSPENDED_FOR_CHARGEBACKS", (
            "25000 of exposure reaches the 25000 liability cap"
        )
        assert agent_b["outstanding_chargeback_cents"] == 25000

    def test_the_divergence_is_forty_seven_thousand_cents(self, api):
        """Identical data, two variants, different results.

        The PRD states: "On the deficient branch, the producing agency is made to
        answer for part of what the borrower did not pay, and how much depends on
        the `chargeback_basis` snapshotted from the agency."

        Design: Difficulty/dual_variant_calc/commission_capped_vs_reserve_capped_chargeback_divergence
        """
        note_a, note_b = self._both_settled(api)

        amount_a = _chargebacks_of(api, note_a["agreement_id"])[0][0]["amount_cents"]
        amount_b = _chargebacks_of(api, note_b["agreement_id"])[0][0]["amount_cents"]

        assert amount_a - amount_b == 47000, (
            "72000 under the commission basis against 25000 under the reserve "
            "basis, from a deficiency of 111497 on both notes"
        )
