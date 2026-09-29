"""
Queue A — §1.8 rule ``compensating_invariant``.

Both instances exercise a compensating action: it must restore the dollar
identity exactly, and it must restore nothing else — the audit record and the
downstream decisions stay where the original act left them.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import (
    assert_commitment_conservation,
    assert_fields,
    assert_loan_ledger,
    assert_nulls,
    assert_ratio,
)
from test_helpers.factories import (
    draw_disbursement_payload,
    draw_void_payload,
)
from test_helpers.fixtures import (
    build_approved_draw,
    build_draft_application,
    build_house_campaign,
    chain_through_authorization,
    chain_through_loan,
    submit_to_underwriting,
)
from test_helpers.test_users import CREDIT_ANALYST, LOAN_SERVICER

VOID_REASON = "Wire returned by the bank; contractor never funded"


def _disbursed_draw(api):
    """The reference borrower with one 60000000 draw approved and disbursed."""
    chain = chain_through_loan(api)
    draw = build_approved_draw(api, chain.loan_id)
    disbursed = get_success_data(
        api.disburse_draw_request(
            draw["id"],
            draw_disbursement_payload(disbursement_date="2026-08-05T00:00:00Z"),
            LOAN_SERVICER,
        )
    )
    return chain, disbursed


def test_voiding_a_disbursed_draw_moves_every_bucket_back(api):
    """
    All six ledger effects of the disbursement reverse, including the interest-reserve sweep.

    PRD §3.7: "Every movement the disbursement made is replayed backwards using the
    figures the disbursement itself recorded: `disbursed_principal_cents` falls by the
    approved amount and `undrawn_commitment_cents` rises by the same amount,
    `retainage_held_cents` falls by `retainage_cents`, `interest_reserve_shortfall_cents`
    rises by `interest_reserve_applied_cents`, and `outstanding_principal_cents` falls by
    the approved amount."

    PRD §3.7: "Where the void brings `disbursed_principal_cents` back to 0, the loan also
    moves `CONSTRUCTION_DRAW → PENDING_FIRST_DRAW`, returning to its pre-draw servicing
    state."

    PRD §2.11: "Voiding a disbursed draw moves every bucket the disbursement moved back by
    the identical amount."

    Design: Difficulty/compensating_invariant/draw_void_restores_loan_commitment_conservation
    """
    chain, disbursed = _disbursed_draw(api)
    before = chain.read_loan()
    assert_loan_ledger(
        before,
        principal_cents=225000000,
        disbursed_principal_cents=60000000,
        undrawn_commitment_cents=165000000,
        cancelled_commitment_cents=0,
        retainage_held_cents=6000000,
        interest_reserve_shortfall_cents=0,
        outstanding_principal_cents=60000000,
        servicing_status="CONSTRUCTION_DRAW",
    )

    voided = get_success_data(
        api.void_draw_request(
            disbursed["id"], draw_void_payload(void_reason=VOID_REASON), LOAN_SERVICER
        )
    )

    assert_fields(voided, status="VOIDED", void_reason=VOID_REASON)
    assert_loan_ledger(
        chain.read_loan(),
        principal_cents=225000000,
        disbursed_principal_cents=0,
        undrawn_commitment_cents=225000000,
        cancelled_commitment_cents=0,
        retainage_held_cents=0,
        retainage_released_cents=0,
        interest_reserve_shortfall_cents=1500000,
        outstanding_principal_cents=0,
        reserved_draw_cents=0,
        servicing_status="PENDING_FIRST_DRAW",
        risk_posture="OPEN",
    )


def test_the_voided_draw_keeps_the_waterfall_figures_it_recorded(api):
    """
    The reversal is driven by the draw's own audit record, and that record survives it.

    PRD §3.7: "A successful disbursement stores `completion_pct_at_disbursement`,
    `retainage_cents`, `interest_reserve_applied_cents`, `inspection_fee_cents` and
    `net_disbursed_cents` on the draw and moves it `APPROVED → DISBURSED`."

    PRD §3.7: "The draw moves `DISBURSED → VOIDED`, which is terminal, and `version`
    advances by 1 on the draw and by 1 on the loan."

    PRD §2.11: "From then on, the sum of `disbursed_principal_cents`,
    `undrawn_commitment_cents` and `cancelled_commitment_cents` must always equal
    `principal_cents`."

    Design: Difficulty/compensating_invariant/draw_void_restores_loan_commitment_conservation
    """
    chain, disbursed = _disbursed_draw(api)
    assert_commitment_conservation(chain.read_loan())

    voided = get_success_data(
        api.void_draw_request(
            disbursed["id"], draw_void_payload(void_reason=VOID_REASON), LOAN_SERVICER
        )
    )

    assert_fields(
        voided,
        status="VOIDED",
        approved_amount_cents=60000000,
        retainage_cents=6000000,
        interest_reserve_applied_cents=1500000,
        inspection_fee_cents=45000,
        net_disbursed_cents=52455000,
        version=disbursed["version"] + 1,
    )
    assert_ratio(voided["completion_pct_at_disbursement"], 0.2666, "completion_pct_at_disbursement")
    reread = get_success_data(api.get_draw_request(disbursed["id"], LOAN_SERVICER))
    assert_fields(reread, status="VOIDED", net_disbursed_cents=52455000, retainage_cents=6000000)
    assert_commitment_conservation(chain.read_loan())


LAPSE_REASON_SHORT = "Donor relocated out of state"
REINSTATEMENT_NOTE = "Donor renewed the commitment in writing"


def _lapsed_campaign_with_pledge_advance(api):
    """
    'Build His House' with the MAJOR donor two installments short and then lapsed, so the
    campaign sits in UNDERPERFORMING and the PLEDGE_ADVANCE application has been pushed to
    REVISION_REQUESTED.
    """
    chain = chain_through_authorization(api)
    built = build_house_campaign(api, chain.institution_id)
    application = build_draft_application(
        api,
        chain.institution_id,
        chain.governance_authorization_id,
        pledge_campaign_id=built["campaign"]["id"],
        purpose="PLEDGE_ADVANCE",
        requested_amount_cents=60000000,
        term_months=120,
        interest_rate_bps=700,
    )
    submit_to_underwriting(
        api, application["id"], analyst_note="Pledge advance against the capital campaign"
    )
    lapsed = get_success_data(
        api.lapse_pledge(built["major"]["id"], {"lapse_reason": LAPSE_REASON_SHORT}, LOAN_SERVICER)
    )
    return built, application, lapsed


def _campaign(api, campaign_id):
    return get_success_data(api.get_pledge_campaign(campaign_id, CREDIT_ANALYST))


def test_reinstatement_restores_the_pledged_dollar_identity_and_the_campaign_status(api):
    """
    Both valuations return to their pre-lapse figures and the campaign climbs back to OPEN.

    PRD §3.3: "The pledged amount moves out of `lapsed_pledged_cents` and back into
    `active_pledged_cents`, restoring the pledged-dollar conservation identity bucket for
    bucket, both projected values are recomputed, and the campaign may be driven
    `UNDERPERFORMING → OPEN`."

    PRD §3.3: "The reverse transition `UNDERPERFORMING → OPEN` fires whenever the
    conservative value recovers to or above the same 80-percent floor, following a
    reinstatement or an installment payment, and advances the campaign's `version` by 1 —
    but it does **not** roll those applications back."

    PRD §3.3: "The campaign's `attrition_adjusted_value_cents` is the collected cash plus
    the sum of those per-pledge contributions."

    Design: Difficulty/compensating_invariant/pledge_reinstate_restores_campaign_pledged_dollar_conservation
    """
    built, _application, lapsed = _lapsed_campaign_with_pledge_advance(api)
    campaign_id = built["campaign"]["id"]
    assert_fields(lapsed, status="LAPSED")
    assert_fields(
        _campaign(api, campaign_id),
        status="UNDERPERFORMING",
        active_pledged_cents=85000000,
        lapsed_pledged_cents=40000000,
        attrition_adjusted_value_cents=86200000,
    )

    reinstated = get_success_data(
        api.reinstate_pledge(
            built["major"]["id"], {"reinstatement_note": REINSTATEMENT_NOTE}, LOAN_SERVICER
        )
    )

    assert_fields(reinstated, status="ACTIVE")
    after = _campaign(api, campaign_id)
    assert_fields(
        after,
        status="OPEN",
        active_pledged_cents=125000000,
        lapsed_pledged_cents=0,
        fulfilled_pledged_cents=0,
        total_pledged_cents=125000000,
        collected_to_date_cents=25000000,
        attrition_adjusted_value_cents=109560000,
        sponsor_projected_value_cents=117000000,
    )
    assert (
        after["active_pledged_cents"]
        + after["lapsed_pledged_cents"]
        + after["fulfilled_pledged_cents"]
        == after["total_pledged_cents"]
    )


def test_reinstatement_preserves_the_counters_and_leaves_the_application_in_revision(api):
    """
    The dollar compensation is exact; the state compensation is deliberately partial.

    PRD §3.3: "It clears `lapse_reason` back to null and preserves `collected_cents`,
    `payments_made_count` and `missed_payments_count` exactly as they stood — a reinstated
    pledge that had missed two installments still carries its penalty rate."

    PRD §3.3: "A donor who has missed two or more installments is penalised a further 15
    percentage points, and the resulting rate is capped at 60 percent no matter how the
    components add up."

    PRD §3.3: "The pledged-dollar invariant is restored; the underwriting decision is
    not."

    PRD §3.5: "It serves both the first submission and every re-submission: an application
    in `DRAFT` moves `DRAFT → UNDERWRITING`, and an application that came back from
    committee or from an underperforming campaign moves `REVISION_REQUESTED → UNDERWRITING`
    through the very same act."

    Design: Difficulty/compensating_invariant/pledge_reinstate_restores_campaign_pledged_dollar_conservation
    """
    built, application, _lapsed = _lapsed_campaign_with_pledge_advance(api)
    flagged = get_success_data(api.get_loan_application(application["id"], CREDIT_ANALYST))
    assert_fields(
        flagged,
        status="REVISION_REQUESTED",
        revision_reason="PLEDGE_CAMPAIGN_UNDERPERFORMING",
        revision_count=1,
    )

    reinstated = get_success_data(
        api.reinstate_pledge(
            built["major"]["id"], {"reinstatement_note": REINSTATEMENT_NOTE}, LOAN_SERVICER
        )
    )

    assert_fields(
        reinstated,
        status="ACTIVE",
        collected_cents=8000000,
        payments_made_count=1,
        missed_payments_count=2,
    )
    assert_nulls(reinstated, "lapse_reason")
    assert_ratio(reinstated["effective_attrition_pct"], 0.2700, "effective_attrition_pct")
    assert_fields(
        get_success_data(api.get_loan_application(application["id"], CREDIT_ANALYST)),
        status="REVISION_REQUESTED",
        revision_reason="PLEDGE_CAMPAIGN_UNDERPERFORMING",
        revision_count=1,
    )
