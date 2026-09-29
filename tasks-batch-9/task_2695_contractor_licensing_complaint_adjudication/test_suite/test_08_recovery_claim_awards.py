"""The crude estimate at filing, the real award at adjudication, and the basis gate.

A recovery-fund claim carries two figures computed by two different rules. The
estimate is stamped at filing and never revised; the award is computed afresh at
adjudication and sees the mediation settlement the estimate ignored. Approval also
depends on a state two hops away — the complaint behind the claim's citation.
"""

from test_helpers import (
    FUND_ADJUDICATOR_HEADERS,
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    CitationStatus,
    ClaimBasis,
    ClaimStatus,
    ComplaintStatus,
    LicenseStatus,
    Severity,
    assert_award_never_exceeds_estimate,
    assert_fields,
    assert_recovery_fund_claim,
    constants as K,
    factories as F,
    fixtures as FX,
    validate_error,
    validate_success,
)


def _judgment_claim_after_a_partial_settlement(api):
    """A 1,200,000 judgment claim on a complaint that already collected 300,000."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    fund_account = FX.open_fund_account(api)
    ctx = FX.mint_active_license(api)
    consumer = FX.register_consumer(
        api, full_name="Pat Ratepayer", contact_email="pat@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    complaint = FX.file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=1500000,
        contract_date="2026-08-10",
        work_completed_on="2026-08-20",
        description="Abandoned rewire, deposit not returned",
    )
    FX.screen_accepted(api, complaint["id"])
    FX.fail_mediation(api, complaint["id"], settlement_amount_cents=300000)
    claim = FX.file_judgment_claim(
        api,
        fund_account["id"],
        complaint["id"],
        consumer["id"],
        1200000,
        1400000,
        "CV-2026-118",
        "2026-09-05",
    )
    return ctx, fund_account, complaint, claim


def test_01_the_preliminary_estimate_sees_only_the_claim_and_the_per_claim_cap(api):
    """Neither the settlement already collected nor the judgment enters the estimate.

    PRD: "That estimate is deliberately crude and is never revised afterwards: it is
    the smaller of the `claimed_amount_cents` and the appropriation's
    `per_claim_cap_cents`, and nothing else. It ignores any mediation settlement
    already in the consumer's hands, ignores the judgment amount, and ignores how
    much aggregate room the licence has left."

    Design: Difficulty/dual_variant_calc/recovery_claim_preliminary_estimate_vs_final_award_after_partial_settlement
    """
    _ctx, _fund_account, _complaint, claim = _judgment_claim_after_a_partial_settlement(
        api
    )

    assert_recovery_fund_claim(
        claim,
        status=ClaimStatus.FILED,
        basis=ClaimBasis.COURT_JUDGMENT,
        estimated_award_cents=1200000,
        awarded_amount_cents=None,
        paid_amount_cents=0,
        repaid_amount_cents=0,
    )


def test_02_the_final_award_subtracts_the_settlement_the_estimate_ignored(api):
    """A second, genuinely different computation lands 900,000 on the same row.

    PRD: "Next, subtract the complaint's `settlement_amount_cents` — the cash the
    consumer already collected in mediation — flooring the result at zero, since the
    fund never pays a negative amount."

    Design: Difficulty/dual_variant_calc/recovery_claim_preliminary_estimate_vs_final_award_after_partial_settlement
    """
    _ctx, _fund_account, _complaint, claim = _judgment_claim_after_a_partial_settlement(
        api
    )
    FX.set_clock(api, "2026-12-04T00:00:00Z")

    approved = FX.approve_claim(api, claim["id"])

    assert_recovery_fund_claim(
        approved,
        status=ClaimStatus.APPROVED,
        awarded_amount_cents=900000,
        estimated_award_cents=1200000,
        adjudicated_on="2026-12-04",
    )
    assert_award_never_exceeds_estimate(approved)
    assert (
        approved["estimated_award_cents"] - approved["awarded_amount_cents"] == 300000
    ), "the divergence between the two variants is exactly the settlement"


def test_03_approval_encumbers_the_licence_without_moving_any_cash(api):
    """The appropriation's balance is untouched while the aggregate room shrinks.

    PRD: "Approving a claim encumbers the licence's aggregate room but moves no
    cash, so the pool may legitimately be oversubscribed and the shortfall is
    resolved at disbursement time."

    Design: Difficulty/dual_variant_calc/recovery_claim_preliminary_estimate_vs_final_award_after_partial_settlement
    """
    ctx, fund_account, _complaint, claim = _judgment_claim_after_a_partial_settlement(
        api
    )
    FX.set_clock(api, "2026-12-04T00:00:00Z")

    FX.approve_claim(api, claim["id"])

    assert_fields(
        FX.read_license(api, ctx.license_id),
        {
            "recovery_encumbered_cents": 900000,
            "outstanding_recovery_repayment_cents": 0,
            "status": LicenseStatus.ACTIVE,
        },
    )
    assert_fields(
        FX.read_fund_account(api, fund_account["id"]), {"balance_cents": 5000000}
    )


def _citation_claim_awaiting_its_cascade(api):
    """A 500,000 citation claim whose complaint has not yet reached sanction."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    fund_account = FX.open_fund_account(api)
    classification = FX.create_c20_classification(api)
    ctx = FX.mint_active_license(
        api,
        classification,
        legal_name="Basis HVAC LLC",
        contact_email="ops@basis.test",
        full_name="Bram Basis",
    )
    consumer = FX.register_consumer(
        api, full_name="Cleo Claimant", contact_email="cleo@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    complaint, _investigation, citation = FX.substantiated_citation(
        api,
        ctx,
        consumer["id"],
        severity=Severity.SERIOUS,
        violation_code="B-7092",
        correction_due_date="2026-10-15",
        alleged_loss_cents=800000,
    )
    claim = FX.get_success_data(
        api.create_claim(
            F.claim_payload(fund_account["id"], complaint["id"], 500000),
            FX.make_consumer_headers(consumer["id"]),
        )
    )
    return ctx, fund_account, complaint, citation, claim


def test_04_a_citation_claim_cannot_be_approved_while_the_complaint_is_unsanctioned(api):
    """The gate reads a state two hops from the claim it refuses.

    PRD: "The **basis must be established**: a `FINAL_CITATION` claim may only be
    approved when its complaint sits in `CLOSED_SANCTIONED`, and a `COURT_JUDGMENT`
    claim may only be approved when its complaint sits in `MEDIATION`,
    `INVESTIGATION`, `CITATION_ISSUED` or `CLOSED_SANCTIONED`"

    Design: Difficulty/cross_entity_state_dependency/recovery_claim_approval_blocked_until_its_complaint_is_closed_sanctioned
    """
    _ctx, _fund_account, complaint, _citation, claim = (
        _citation_claim_awaiting_its_cascade(api)
    )

    validate_error(
        api.adjudicate_claim(
            claim["id"],
            F.adjudication_payload("APPROVE"),
            FUND_ADJUDICATOR_HEADERS,
        ),
        ApiErrorId.CLAIM_BASIS_NOT_ESTABLISHED,
    )

    assert_recovery_fund_claim(
        validate_success(api.get_claim(claim["id"], FUND_ADJUDICATOR_HEADERS)),
        status=ClaimStatus.FILED,
        estimated_award_cents=500000,
        awarded_amount_cents=None,
        adjudicated_on=None,
    )
    assert_fields(
        validate_success(
            api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": ComplaintStatus.CITATION_ISSUED},
    )


def test_05_defaulting_the_unappealed_citation_sanctions_the_complaint(api):
    """Finalizing the citation is the cascade that establishes the claim's basis.

    PRD: "the `INITIAL_ASSESSMENT` figure simply becomes collectable, the licensee's
    `unpaid_penalty_cents` rises by that citation's `civil_penalty_cents` less its
    `penalty_paid_cents`, the complaint behind the citation's case moves
    `CITATION_ISSUED → CLOSED_SANCTIONED`, and the licence's `compliance_posture` is
    recomputed"

    Design: Difficulty/cross_entity_state_dependency/recovery_claim_approval_blocked_until_its_complaint_is_closed_sanctioned
    """
    _ctx, _fund_account, complaint, citation, _claim = (
        _citation_claim_awaiting_its_cascade(api)
    )
    FX.set_clock(api, "2026-09-17T00:00:00Z")

    finalized = validate_success(
        api.finalize_citation(citation["id"], LICENSING_ANALYST_HEADERS)
    )

    assert_fields(finalized, {"status": CitationStatus.FINAL})
    assert_fields(
        validate_success(
            api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": ComplaintStatus.CLOSED_SANCTIONED},
    )


def test_06_the_unchanged_request_approves_once_the_cascade_has_landed(api):
    """With the basis established the same adjudication awards the full claim.

    PRD: "An `APPROVE` whose computation yields at least one cent moves the claim
    `FILED → APPROVED`, stamps `awarded_amount_cents` with the award and
    `adjudicated_on` with the clock date, and recomputes the licence's
    `recovery_encumbered_cents`"

    Design: Difficulty/cross_entity_state_dependency/recovery_claim_approval_blocked_until_its_complaint_is_closed_sanctioned
    """
    ctx, fund_account, _complaint, citation, claim = (
        _citation_claim_awaiting_its_cascade(api)
    )
    FX.set_clock(api, "2026-09-17T00:00:00Z")
    validate_success(api.finalize_citation(citation["id"], LICENSING_ANALYST_HEADERS))

    approved = FX.approve_claim(api, claim["id"])

    assert_recovery_fund_claim(
        approved,
        status=ClaimStatus.APPROVED,
        awarded_amount_cents=500000,
        adjudicated_on="2026-09-17",
        paid_amount_cents=0,
    )
    assert_fields(
        FX.read_license(api, ctx.license_id), {"recovery_encumbered_cents": 500000}
    )
    assert_fields(
        FX.read_fund_account(api, fund_account["id"]), {"balance_cents": 5000000}
    )
