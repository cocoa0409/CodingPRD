"""Two requests that break two rules at once, and the rule that must be reported.

A disbursement aimed at a never-adjudicated claim out of an emptied pool violates
both a state rule and a fiscal one; a designation offered to an already-saturated
qualifier on a date before the licence existed violates both a referential rule and
a temporal one. In each case the PRD fixes which of the two the caller hears about.
"""

from test_helpers import (
    FUND_ADJUDICATOR_HEADERS,
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    ApplicationDecision,
    ClaimStatus,
    assert_fields,
    assert_qualification_count,
    assert_recovery_fund_claim,
    constants as K,
    factories as F,
    fixtures as FX,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _emptied_pool_and_an_unadjudicated_claim(api):
    """A pool drained to zero by one paid claim, with a sibling still in FILED."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    fund_account = FX.open_fund_account(api, initial_balance_cents=700000)
    ctx = FX.mint_active_license(api)
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    consumer_one = FX.register_consumer(
        api, full_name="Pat Ratepayer", contact_email="pat@home.test"
    )
    consumer_two = FX.register_consumer(
        api, full_name="Rae Homeowner", contact_email="rae@home.test"
    )
    complaint_one = FX.file_complaint(
        api,
        consumer_one["id"],
        ctx.license_id,
        alleged_loss_cents=800000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Rewire abandoned",
    )
    FX.screen_accepted(api, complaint_one["id"])
    complaint_two = FX.file_complaint(
        api,
        consumer_two["id"],
        ctx.license_id,
        alleged_loss_cents=500000,
        contract_date="2026-08-06",
        work_completed_on="2026-08-21",
        description="Subpanel never energised",
    )
    claim_a = FX.file_judgment_claim(
        api,
        fund_account["id"],
        complaint_one["id"],
        consumer_one["id"],
        700000,
        750000,
        "CV-2026-401",
        "2026-09-05",
    )
    claim_b = FX.file_judgment_claim(
        api,
        fund_account["id"],
        complaint_two["id"],
        consumer_two["id"],
        400000,
        450000,
        "CV-2026-402",
        "2026-09-05",
    )
    FX.set_clock(api, "2026-12-04T00:00:00Z")
    FX.approve_claim(api, claim_a["id"])
    paid_a = FX.pay_claim(api, claim_a["id"], fund_account["id"])
    return ctx, fund_account, paid_a, claim_b


def _attempt_payment(api, claim_id, fund_account_id):
    """Presents the appropriation's current version, so only the token is valid."""
    account = FX.read_fund_account(api, fund_account_id)
    return api.pay_claim(
        claim_id, F.payment_payload(account["version"]), FUND_ADJUDICATOR_HEADERS
    )


def test_01_the_claim_state_error_outranks_the_exhausted_pool_error(api):
    """A claim never adjudicated is refused on its state, not on the empty pool.

    PRD: "Disbursement is a `FundAdjudicator` action on a claim in `APPROVED` —
    anything else draws `ERR_CLAIM_STATE_INVALID` — and it must present
    `expected_fund_account_version` as §2.9 requires."

    PRD: "The concurrency check fires first, the claim-state check second, and the
    balance check last."

    Design: Difficulty/priority_pair_validation_conflict/claim_pay_state_error_outranks_fund_exhaustion_error
    """
    _ctx, fund_account, _paid_a, claim_b = _emptied_pool_and_an_unadjudicated_claim(api)

    reported = validate_error(
        _attempt_payment(api, claim_b["id"], fund_account["id"]),
        ApiErrorId.CLAIM_STATE_INVALID,
        409,
    )

    assert reported["error_id"] != ApiErrorId.FUND_BALANCE_EXHAUSTED.value, (
        "the lower-priority fiscal rule must never be the reported one"
    )


def test_02_both_rules_were_genuinely_broken_by_that_one_request(api):
    """The pool really is empty and the target claim really is unadjudicated.

    PRD: "The appropriation must have at least one cent of `balance_cents` to
    disburse from, or the request is refused with `ERR_FUND_BALANCE_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/claim_pay_state_error_outranks_fund_exhaustion_error
    """
    _ctx, fund_account, _paid_a, claim_b = _emptied_pool_and_an_unadjudicated_claim(api)

    assert_fields(FX.read_fund_account(api, fund_account["id"]), {"balance_cents": 0})
    assert_recovery_fund_claim(
        validate_success(api.get_claim(claim_b["id"], FUND_ADJUDICATOR_HEADERS)),
        status=ClaimStatus.FILED,
        awarded_amount_cents=None,
        paid_amount_cents=0,
        adjudicated_on=None,
    )


def test_03_the_refused_disbursement_leaves_every_figure_untouched(api):
    """The paid sibling, the drained pool and the licence's debt all stand as they were.

    PRD: "**Second**, *because* cash has moved, the appropriation's `balance_cents`
    falls by the total disbursed while the licence's `recovery_paid_to_date_cents` and
    `outstanding_recovery_repayment_cents` both rise by that same total, and the
    licensee's `outstanding_recovery_payout_cents` rises with them."

    Design: Difficulty/priority_pair_validation_conflict/claim_pay_state_error_outranks_fund_exhaustion_error
    """
    ctx, fund_account, paid_a, claim_b = _emptied_pool_and_an_unadjudicated_claim(api)

    validate_error(
        _attempt_payment(api, claim_b["id"], fund_account["id"]),
        ApiErrorId.CLAIM_STATE_INVALID,
    )

    assert_recovery_fund_claim(
        validate_success(api.get_claim(paid_a["id"], FUND_ADJUDICATOR_HEADERS)),
        status=ClaimStatus.PAID,
        paid_amount_cents=700000,
    )
    assert_fields(FX.read_fund_account(api, fund_account["id"]), {"balance_cents": 0})
    assert_fields(
        FX.read_license(api, ctx.license_id),
        {"outstanding_recovery_repayment_cents": 700000},
    )
    assert_recovery_fund_claim(
        validate_success(api.get_claim(claim_b["id"], FUND_ADJUDICATOR_HEADERS)),
        status=ClaimStatus.FILED,
        paid_amount_cents=0,
        paid_on=None,
    )


def _saturated_qualifier_and_a_later_licence(api):
    """A person on two open-ended designations, plus a licence issued a month later."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    classification = FX.create_c10_classification(api)
    shared = FX.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        law_score=90,
        trade_score=88,
        full_name="Sam Shared",
    )
    third = FX.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        law_score=91,
        trade_score=87,
        full_name="Tess Third",
    )
    FX.mint_active_license(
        api,
        classification,
        legal_name="Alpha Electric LLC",
        contact_email="a@alpha.test",
        individual=shared,
        declared_net_worth_cents=300000,
    )
    FX.mint_active_license(
        api,
        classification,
        legal_name="Beta Electric LLC",
        contact_email="b@beta.test",
        individual=shared,
        declared_net_worth_cents=300000,
    )
    gamma = FX.register_licensee(
        api, legal_name="Gamma Electric LLC", contact_email="g@gamma.test"
    )
    application = FX.open_application(
        api,
        gamma["id"],
        classification["id"],
        third["id"],
        declared_net_worth_cents=300000,
    )
    validate_success(
        api.submit_application(application["id"], make_licensee_headers(gamma["id"]))
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(ApplicationDecision.APPROVED),
            LICENSING_ANALYST_HEADERS,
        )
    )
    return shared, third, FX.find_license_for_application(api, application["id"])


def test_04_the_capacity_error_outranks_the_effective_date_error(api):
    """A saturated designee on a pre-issuance date is refused on capacity alone.

    PRD: "Then the **concurrent-qualification cap**: a single person may hold at most
    two live designations covering any given date, so the system counts the
    designations already held by the offered person whose `status` is `ACTIVE` and
    whose window — from `effective_from` through `effective_to` inclusive, or
    open-ended when `effective_to` is null — contains the new designation's
    `effective_from`."

    Design: Difficulty/priority_pair_validation_conflict/qualifier_capacity_error_outranks_effective_date_error
    """
    shared, _third, license_three = _saturated_qualifier_and_a_later_licence(api)

    reported = validate_error(
        FX.designate_qualifier(
            api,
            license_three["id"],
            shared["id"],
            license_three["version"],
            effective_from="2026-08-15",
        ),
        ApiErrorId.QUALIFIER_CAPACITY_EXCEEDED,
        422,
    )

    assert reported["error_id"] != ApiErrorId.ASSIGNMENT_EFFECTIVE_DATE_INVALID.value, (
        "the later temporal gate must never be the reported one"
    )


def test_05_the_window_the_request_offered_really_did_escape_the_licence(api):
    """The suppressed rule was genuinely broken: the date precedes issuance.

    PRD: "Finally the **window containment**: `effective_from` must be on or after the
    licence's `issued_on`, and `effective_to`, when supplied, must be on or before the
    licence's `expires_on`; a window escaping either boundary draws
    `ERR_ASSIGNMENT_EFFECTIVE_DATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/qualifier_capacity_error_outranks_effective_date_error
    """
    shared, third, license_three = _saturated_qualifier_and_a_later_licence(api)

    assert_fields(license_three, {"issued_on": "2026-09-01"})
    assert license_three["issued_on"] > "2026-08-15", (
        "the offered effective_from precedes the licence's own issuance"
    )
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(shared["id"], LICENSING_ANALYST_HEADERS)
        ),
        2,
    )
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(third["id"], LICENSING_ANALYST_HEADERS)
        ),
        1,
    )


def test_06_the_refused_designation_neither_lands_nor_bumps_the_licence_version(api):
    """The licence keeps its own qualifier, its version and its single designation.

    PRD: "Both `POST /licensing/qualifier-assignments` and `POST
    /licensing/licenses/{id}/recovery-repayments` increment the target
    `License.version` by one when they succeed, and `POST
    /licensing/recovery-fund-claims/{id}/pay` increments the
    `RecoveryFundAccount.version` by one, so a client performing a run of writes must
    re-read the parent between each."

    Design: Difficulty/priority_pair_validation_conflict/qualifier_capacity_error_outranks_effective_date_error
    """
    shared, third, license_three = _saturated_qualifier_and_a_later_licence(api)

    validate_error(
        FX.designate_qualifier(
            api,
            license_three["id"],
            shared["id"],
            license_three["version"],
            effective_from="2026-08-15",
        ),
        ApiErrorId.QUALIFIER_CAPACITY_EXCEEDED,
    )

    assert_fields(
        FX.read_license(api, license_three["id"]),
        {
            "qualifying_individual_id": third["id"],
            "version": license_three["version"],
        },
    )
    _rows, meta = validate_paginated(
        api.list_qualifier_assignments(
            LICENSING_ANALYST_HEADERS, {"license_id": license_three["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "only the designation minted by the approval cascade may exist on the licence"
    )
