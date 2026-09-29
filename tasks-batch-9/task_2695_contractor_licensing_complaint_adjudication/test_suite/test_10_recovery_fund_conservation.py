"""Two quantities that must balance at every checkpoint of a payout-and-repayment run.

The first is cash: the pool the board appropriated is only ever moved between the
appropriation's balance and the debt the licence owes, so the two must always add
back to the opening figure. The second is a derived counter: a qualifier's live
designation count is decremented by one cascade and re-incremented by an entirely
different one, and it must land back on exactly its old value.
"""

from test_helpers import (
    FUND_ADJUDICATOR_HEADERS,
    LICENSING_ANALYST_HEADERS,
    AssignmentStatus,
    ClaimStatus,
    CompliancePosture,
    LicenseStatus,
    assert_fields,
    assert_qualification_count,
    assert_recovery_fund_claim,
    constants as K,
    factories as F,
    fixtures as FX,
    validate_paginated,
    validate_success,
)

OPENING_BALANCE_CENTS = 5000000


def _paid_out_licence_owing_the_fund(api):
    """A bonded C-20 licence that has just had 900,000 disbursed on its account."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    fund_account = FX.open_fund_account(api)
    classification = FX.create_c20_classification(api)
    ctx = FX.mint_active_license(
        api,
        classification,
        legal_name="Conserve Air LLC",
        contact_email="cons@x.test",
        full_name="Connie Serve",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    FX.verify_bond(
        api,
        ctx.license_id,
        amount_cents=K.C20["required_bond_amount_cents"],
        carrier_name="Surety Two",
        policy_number="BND-CV",
    )
    consumer = FX.register_consumer(
        api, full_name="Cash Consumer", contact_email="cash@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    _complaint, claim = FX.approved_court_judgment_claim(
        api,
        ctx,
        fund_account,
        consumer,
        alleged_loss_cents=1000000,
        claimed_amount_cents=900000,
        judgment_amount_cents=1000000,
        judgment_docket_number="CV-2026-4412",
        judgment_entered_on="2026-05-01",
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        adjudication_clock="2026-09-01T00:00:00Z",
    )
    paid = FX.pay_claim(api, claim["id"], fund_account["id"])
    return ctx, fund_account, paid


def _credit_repayment(api, ctx, repayment_amount_cents):
    """Credits a repayment against the licence using its current version as token."""
    current = FX.read_license(api, ctx.license_id)
    return validate_success(
        api.credit_recovery_repayment(
            ctx.license_id,
            F.repayment_payload(repayment_amount_cents, current["version"]),
            ctx.licensee_headers,
        )
    )


def test_01_the_payout_checkpoint_balances_the_pool_against_the_new_debt(api):
    """Cash has only moved from the appropriation onto the licence as debt.

    PRD: "The live `balance_cents` is fully derived and is initialised to the
    appropriated amount: it is the `initial_balance_cents`, less the sum of
    `paid_amount_cents` over every claim charged to this account whose `status` is
    `PAID` or `REIMBURSED`, plus the sum of `repaid_amount_cents` over every claim
    charged to this account."

    Design: Difficulty/compensating_invariant/recovery_fund_cash_is_conserved_across_a_payout_and_two_partial_repayments
    """
    ctx, fund_account, paid = _paid_out_licence_owing_the_fund(api)

    assert_recovery_fund_claim(
        paid,
        status=ClaimStatus.PAID,
        awarded_amount_cents=900000,
        paid_amount_cents=900000,
        repaid_amount_cents=0,
    )
    balance = FX.read_fund_account(api, fund_account["id"])["balance_cents"]
    debt = FX.read_license(api, ctx.license_id)[
        "outstanding_recovery_repayment_cents"
    ]
    assert balance == 4100000, "the pool has fallen by exactly the sum disbursed"
    assert debt == 900000, "the licence now owes exactly the sum disbursed"
    assert balance + debt == OPENING_BALANCE_CENTS, (
        "cash is conserved: the pool plus the debt is the appropriated opening figure"
    )


def test_02_a_partial_repayment_moves_cash_back_and_leaves_the_suspension(api):
    """The 400,000 credit reappears in the pool cent for cent and nothing lifts.

    PRD: "The appropriation's `balance_cents` rises by the credited amount, the
    licence's `outstanding_recovery_repayment_cents` falls by it, and the licensee's
    `outstanding_recovery_payout_cents` follows."

    PRD: "Partial repayments simply lower the outstanding figure and leave the
    suspension in place, which is exactly why the stale-version guard on this
    endpoint matters."

    Design: Difficulty/compensating_invariant/recovery_fund_cash_is_conserved_across_a_payout_and_two_partial_repayments
    """
    ctx, fund_account, _paid = _paid_out_licence_owing_the_fund(api)

    credited = _credit_repayment(api, ctx, 400000)

    assert_fields(
        credited,
        {
            "outstanding_recovery_repayment_cents": 500000,
            "status": LicenseStatus.SUSPENDED,
        },
    )
    balance = FX.read_fund_account(api, fund_account["id"])["balance_cents"]
    assert balance == 4500000, "the credited cash is back in the appropriation"
    assert balance + credited["outstanding_recovery_repayment_cents"] == (
        OPENING_BALANCE_CENTS
    ), "the invariant holds again at the partial-repayment checkpoint"
    assert_fields(
        validate_success(api.get_licensee(ctx.licensee_id, LICENSING_ANALYST_HEADERS)),
        {"outstanding_recovery_payout_cents": 500000},
    )


def test_03_the_closing_repayment_restores_the_pool_and_lifts_the_suspension(api):
    """The second credit clears the debt, so the payout suspension ends itself.

    PRD: "When the credit brings `outstanding_recovery_repayment_cents` to exactly
    zero **and** the licence's `suspension_reason` is `RECOVERY_FUND_PAYOUT`, the
    payout suspension lifts of its own accord: the licence moves `SUSPENDED →
    ACTIVE`, both `suspension_reason` and `suspension_until` are cleared to null"

    Design: Difficulty/compensating_invariant/recovery_fund_cash_is_conserved_across_a_payout_and_two_partial_repayments
    """
    ctx, fund_account, _paid = _paid_out_licence_owing_the_fund(api)
    _credit_repayment(api, ctx, 400000)

    closed = _credit_repayment(api, ctx, 500000)

    assert_fields(
        closed,
        {
            "outstanding_recovery_repayment_cents": 0,
            "status": LicenseStatus.ACTIVE,
            "suspension_reason": None,
            "suspension_until": None,
            "compliance_posture": CompliancePosture.CONDITIONAL,
        },
    )
    balance = FX.read_fund_account(api, fund_account["id"])["balance_cents"]
    assert balance == OPENING_BALANCE_CENTS, (
        "every cent that left the appropriation has come back to it"
    )
    assert balance + closed["outstanding_recovery_repayment_cents"] == (
        OPENING_BALANCE_CENTS
    ), "the invariant closes on the opening figure with no debt left"


def test_04_the_absorbed_claim_is_reimbursed_while_the_odometer_stands(api):
    """The two credits are absorbed by the one paid claim, which turns terminal.

    PRD: "A successful credit increments the licence's `version` by one and is
    absorbed by the licence's paid claims **oldest first, in `created_at` ascending
    order**: each claim's `repaid_amount_cents` rises until it reaches that claim's
    `paid_amount_cents`, at which point the claim moves `PAID → REIMBURSED` and the
    remainder of the credit rolls on to the next claim."

    Design: Difficulty/compensating_invariant/recovery_fund_cash_is_conserved_across_a_payout_and_two_partial_repayments
    """
    ctx, _fund_account, paid = _paid_out_licence_owing_the_fund(api)
    _credit_repayment(api, ctx, 400000)

    _credit_repayment(api, ctx, 500000)

    assert_recovery_fund_claim(
        validate_success(api.get_claim(paid["id"], FUND_ADJUDICATOR_HEADERS)),
        status=ClaimStatus.REIMBURSED,
        paid_amount_cents=900000,
        repaid_amount_cents=900000,
    )
    assert_fields(
        FX.read_license(api, ctx.license_id),
        {
            "recovery_paid_to_date_cents": 900000,
            "outstanding_recovery_repayment_cents": 0,
        },
    )


def _slot_released_by_a_payout(api):
    """A licence suspended by disbursement, its sole designation held in abeyance."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    fund_account = FX.open_fund_account(api)
    classification = FX.create_c20_classification(api)
    ctx = FX.mint_active_license(
        api,
        classification,
        legal_name="Slot Conserve Air LLC",
        contact_email="slotc@x.test",
        full_name="Quincy Slot",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    consumer = FX.register_consumer(
        api, full_name="Slot Sufferer", contact_email="slots@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    _complaint, claim = FX.approved_court_judgment_claim(
        api,
        ctx,
        fund_account,
        consumer,
        alleged_loss_cents=1000000,
        claimed_amount_cents=900000,
        judgment_amount_cents=950000,
        judgment_docket_number="CV-2026-5510",
        judgment_entered_on="2026-05-01",
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        adjudication_clock="2026-09-01T00:00:00Z",
    )
    assignment = FX.find_assignment_for_license(api, ctx.license_id)
    assert_qualification_count(_read_individual(api, ctx.individual_id), 1)
    return ctx, fund_account, claim, assignment


def _read_individual(api, individual_id):
    return validate_success(
        api.get_qualifying_individual(individual_id, LICENSING_ANALYST_HEADERS)
    )


def _active_assignments_of(api, individual_id):
    rows, meta = validate_paginated(
        api.list_qualifier_assignments(
            LICENSING_ANALYST_HEADERS,
            {
                "qualifying_individual_id": individual_id,
                "status": AssignmentStatus.ACTIVE,
            },
        )
    )
    return rows, meta


def test_05_the_payout_drops_the_counter_to_the_number_of_live_designations(api):
    """The counter and the list of live designations agree at zero after the payout.

    PRD: "Whenever a `License` enters `SUSPENDED` from `ACTIVE`, every qualifier
    designation on that licence whose `status` is `ACTIVE` moves to
    `SUSPENDED_BY_LICENSE`, and because each of those designations has left `ACTIVE`,
    the `active_qualification_count` of its qualifying individual falls by one."

    Design: Difficulty/compensating_invariant/qualifier_slot_count_is_conserved_across_a_payout_and_a_full_repayment
    """
    ctx, fund_account, claim, assignment = _slot_released_by_a_payout(api)

    FX.pay_claim(api, claim["id"], fund_account["id"])

    assert_qualification_count(_read_individual(api, ctx.individual_id), 0)
    rows, _meta = _active_assignments_of(api, ctx.individual_id)
    assert rows == [], (
        "the derived counter must equal the number of designations still ACTIVE"
    )
    assert_fields(
        validate_success(
            api.get_qualifier_assignment(assignment["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": AssignmentStatus.SUSPENDED_BY_LICENSE},
    )


def test_06_a_single_full_repayment_returns_the_counter_to_exactly_one(api):
    """One repayment, one restored designation, and no double increment.

    PRD: "When a licence returns from `SUSPENDED` to `ACTIVE` — whether by completing
    recovery repayment or by analyst reinstatement — every designation on it sitting
    in `SUSPENDED_BY_LICENSE` returns to `ACTIVE` provided its window has not closed
    (that is, its `effective_to` is null or is on or after the clock date), and each
    such return raises that qualifier's `active_qualification_count` by one."

    Design: Difficulty/compensating_invariant/qualifier_slot_count_is_conserved_across_a_payout_and_a_full_repayment
    """
    ctx, fund_account, claim, assignment = _slot_released_by_a_payout(api)
    FX.pay_claim(api, claim["id"], fund_account["id"])

    restored = _credit_repayment(api, ctx, 900000)

    assert_fields(restored, {"status": LicenseStatus.ACTIVE})
    assert_qualification_count(_read_individual(api, ctx.individual_id), 1)
    assert_fields(
        validate_success(
            api.get_qualifier_assignment(assignment["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": AssignmentStatus.ACTIVE, "withdrawn_on": None},
    )


def test_07_the_restored_counter_still_matches_the_live_designation_list(api):
    """The counter is a derivation, not a tally that can drift out of step.

    PRD: "A derived `active_qualification_count`, initialised to zero, tracks how
    many designations that person currently holds in `ACTIVE` status; it is the number
    the concurrent-qualification cap is measured against"

    Design: Difficulty/compensating_invariant/qualifier_slot_count_is_conserved_across_a_payout_and_a_full_repayment
    """
    ctx, fund_account, claim, _assignment = _slot_released_by_a_payout(api)
    FX.pay_claim(api, claim["id"], fund_account["id"])

    _credit_repayment(api, ctx, 900000)

    rows, _meta = _active_assignments_of(api, ctx.individual_id)
    counter = _read_individual(api, ctx.individual_id)["active_qualification_count"]
    assert len(rows) == counter == 1, (
        "the counter must equal the count of ACTIVE designations after the round trip"
    )
    assert_recovery_fund_claim(
        validate_success(api.get_claim(claim["id"], FUND_ADJUDICATOR_HEADERS)),
        status=ClaimStatus.REIMBURSED,
        repaid_amount_cents=900000,
    )
    assert_fields(
        FX.read_fund_account(api, fund_account["id"]),
        {"balance_cents": OPENING_BALANCE_CENTS},
    )
