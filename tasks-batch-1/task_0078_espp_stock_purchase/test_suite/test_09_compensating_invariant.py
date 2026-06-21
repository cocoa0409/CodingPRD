"""Difficulty rule 9 — compensating-action conservation invariants (PRD §3.3, §3.5).

Withdraw conserves total contribution cash; a purchase conserves contribution cash
across the spend/residual split.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    setup_enrolled_participant,
    setup_certified_batch,
    contribute,
    run_batch,
    api_client,
    make_participant_headers,
)


def test_withdraw_zeroes_accumulated_and_sets_refunded(api, admin_headers):
    """PRD §3.3: "An employee may also withdraw entirely from either ENROLLED or
    SUSPENDED, advancing the enrollment to WITHDRAWN; on withdrawal, every POSTED
    contribution for that enrollment becomes REFUNDED, the enrollment's
    refunded_contribution_cents is recomputed to reflect the returned amounts, and its
    accumulated_contribution_cents is reset to 0."

    50000c POSTED (gross 500000 at 10%); after withdraw accumulated==0, refunded==50000.

    Design: Difficulty/compensating_invariant/withdraw_conserves_contribution_cash
    """
    _, _, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    contribute(enrollment["id"], gross_pay_cents=500000)
    ph = make_participant_headers(participant["id"])
    get_success_data(api.withdraw_enrollment(enrollment["id"], ph))
    refreshed = validate_success(api.get_enrollment(enrollment["id"], admin_headers))
    assert refreshed["accumulated_contribution_cents"] == 0, refreshed
    assert refreshed["refunded_contribution_cents"] == 50000, refreshed


def test_withdraw_conserves_total_cash(api, admin_headers):
    """PRD §3.3: "on withdrawal, every POSTED contribution for that enrollment becomes
    REFUNDED, the enrollment's refunded_contribution_cents is recomputed to reflect
    the returned amounts, and its accumulated_contribution_cents is reset to 0."

    Conservation: accumulated_contribution_cents + refunded_contribution_cents equals
    the 50000c ever contributed.

    Design: Difficulty/compensating_invariant/withdraw_conserves_contribution_cash
    """
    _, _, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    contribute(enrollment["id"], gross_pay_cents=500000)
    ph = make_participant_headers(participant["id"])
    get_success_data(api.withdraw_enrollment(enrollment["id"], ph))
    refreshed = validate_success(api.get_enrollment(enrollment["id"], admin_headers))
    total = (
        refreshed["accumulated_contribution_cents"]
        + refreshed["refunded_contribution_cents"]
    )
    assert total == 50000, refreshed


def _settled_purchase_100000c(api, admin_headers):
    ctx = setup_certified_batch(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={"grant_date_fmv_cents": 1000, "duration_months": 6},
        batch_overrides={
            "purchase_date": "2024-05-31T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=10, gross_pay_cents=1000000,
    )
    run_batch(ctx["batch"]["id"], ctx["pp_version"])
    purchases, _ = _list(api, api.list_purchases, admin_headers,
                         {"enrollment_id": ctx["enrollment"]["id"]})
    return purchases[0]


def test_purchase_share_split_values(api, admin_headers):
    """PRD §3.5: "The system records shares_purchased, the spend_cents actually drawn
    from contributions (the shares purchased multiplied by the price per share) ...
    and the residual_cents left over (the enrollment's accumulated contributions minus
    the spend)."

    100000c at price 850 => shares 117, spend 117*850 = 99450, residual 550.

    Design: Difficulty/compensating_invariant/purchase_conserves_shares_and_residual_cash
    """
    purchase = _settled_purchase_100000c(api, admin_headers)
    assert purchase["shares_purchased"] == 117, purchase
    assert purchase["spend_cents"] == 99450, purchase
    assert purchase["residual_cents"] == 550, purchase


def test_purchase_conserves_contribution_cash(api, admin_headers):
    """PRD §3.5: "the spend_cents actually drawn from contributions (the shares
    purchased multiplied by the price per share) ... and the residual_cents left over
    (the enrollment's accumulated contributions minus the spend)."

    Conservation: spend_cents + residual_cents equals the 100000c accumulated.

    Design: Difficulty/compensating_invariant/purchase_conserves_shares_and_residual_cash
    """
    purchase = _settled_purchase_100000c(api, admin_headers)
    assert purchase["spend_cents"] + purchase["residual_cents"] == 100000, purchase


def _list(api, list_fn, headers, params):
    resp = list_fn(headers, params=params)
    body = resp.json()
    return body["data"], body["meta"]
