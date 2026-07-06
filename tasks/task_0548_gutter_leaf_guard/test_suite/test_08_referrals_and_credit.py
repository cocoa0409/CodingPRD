"""Referrals: the three-hop accept cascade (job -> won lead -> payable referral +
referrer credit), the compensating clawback when the referee's job is cancelled,
and the self-referral guard.
"""
from test_helpers import (
    ApiErrorId,
    accept_quote,
    create_crew,
    create_lead,
    create_referral_payload,
    create_sales_rep,
    get_job_for_quote,
    schedule_job,
    setup_referral_pending,
    transition_job,
    validate_error,
    validate_success,
)


# ----------------------------------------------------------- accept cascade
def test_accept_creates_job_and_wins_referee_lead(api, admin_headers):
    """PRD §3.5: "First, a **Job** is created in `PENDING` for the accepted quote,
    computing its install days and deposit as described in Section 3.7. Second,
    the birth of that job moves the owning lead from `QUOTED` to `WON`."

    Design: Difficulty/transitive_cascade/accept_quote_cascade_depth3
    """
    ctx = setup_referral_pending(estimated_linear_feet=200, measured_linear_feet=200)
    accepted = accept_quote(ctx["quote"]["id"])
    assert accepted["status"] == "ACCEPTED"
    job = get_job_for_quote(ctx["quote"]["id"])
    assert job["status"] == "PENDING"
    referee = validate_success(api.get_lead(ctx["referee"]["id"], admin_headers))
    assert referee["status"] == "WON"


def test_accept_makes_referral_payable_and_credits_referrer(api, admin_headers):
    """PRD §3.9: "When the referee lead moves from `QUOTED` to `WON` on quote
    acceptance, any referral naming that lead as its referee that is still
    `PENDING` moves to `PAYABLE`. Its `payout_cents` is then computed as the
    smaller of two amounts: the referee's accepted quote `total_cents` multiplied
    by 3 percent and rounded half up to whole cents, or a hard cap of 50,000 cents
    ($500). Becoming payable increases the referrer lead's `credit_balance_cents`
    by that payout."

    Design: Difficulty/transitive_cascade/accept_quote_cascade_depth3
    """
    ctx = setup_referral_pending(estimated_linear_feet=200, measured_linear_feet=200)
    accept_quote(ctx["quote"]["id"])
    referral = validate_success(api.get_referral(ctx["referral"]["id"], admin_headers))
    assert referral["status"] == "PAYABLE"
    assert referral["payout_cents"] == 17100  # round_half_up(570000 * 0.03)
    referrer = validate_success(api.get_lead(ctx["referrer"]["id"], admin_headers))
    assert referrer["credit_balance_cents"] == 17100


# ------------------------------------------------- compensating clawback
def test_referral_payable_credits_referrer_forward(api, admin_headers):
    """PRD §3.9: "Becoming payable increases the referrer lead's
    `credit_balance_cents` by that payout."

    Design: Difficulty/compensating_invariant/referrer_credit_conserved_on_clawback
    """
    ctx = setup_referral_pending(estimated_linear_feet=200, measured_linear_feet=200)
    accept_quote(ctx["quote"]["id"])
    referrer = validate_success(api.get_lead(ctx["referrer"]["id"], admin_headers))
    assert referrer["credit_balance_cents"] == 17100


def test_referee_job_cancel_claws_back_referral_credit(api, admin_headers):
    """PRD §3.9: "When the referee's job is cancelled, any referral naming that
    lead as its referee that is `PAYABLE` or `PAID` is moved to `CLAWED_BACK`, and
    the referrer lead's `credit_balance_cents` is decreased by that referral's
    `payout_cents`."

    Design: Difficulty/compensating_invariant/referrer_credit_conserved_on_clawback
    """
    ctx = setup_referral_pending(estimated_linear_feet=200, measured_linear_feet=200)
    accept_quote(ctx["quote"]["id"])
    job = get_job_for_quote(ctx["quote"]["id"])
    crew = create_crew()
    schedule_job(job["id"], crew["id"], "2026-06-10")
    transition_job(job["id"], "CANCELED")
    referral = validate_success(api.get_referral(ctx["referral"]["id"], admin_headers))
    assert referral["status"] == "CLAWED_BACK"
    referrer = validate_success(api.get_lead(ctx["referrer"]["id"], admin_headers))
    assert referrer["credit_balance_cents"] == 0


# ----------------------------------------------------------- self-referral
def test_self_referral_rejected(api, admin_headers):
    """PRD §3.9: "The two must be different leads; a referral whose referrer and
    referee are the same is rejected with `ERR_SELF_REFERRAL`."

    Design: Corner/validations/self_referral_returns_error
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO16", address="16 St", phone="555-0016")
    resp = api.create_referral(create_referral_payload(lead["id"], lead["id"]), admin_headers)
    validate_error(resp, ApiErrorId.ERR_SELF_REFERRAL)
