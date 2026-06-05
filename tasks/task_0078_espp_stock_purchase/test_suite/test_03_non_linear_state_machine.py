"""Difficulty rule 3 — non-linear state-machine shapes (PRD §3.3, §3.8).

Enrollment cyclic ENROLLED<->SUSPENDED loop, and Disposition branching that
cascades a ShareLot to FULLY_DISPOSED on full sale.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    create_disposition_payload,
    setup_enrolled_participant,
    setup_settled_purchase,
    make_participant_headers,
)


def test_suspend_then_resume_returns_to_enrolled(api):
    """PRD §3.3: "Suspending an enrollment moves it from ENROLLED to SUSPENDED ...
    Resuming moves it back from SUSPENDED to ENROLLED, permitted only when the
    enrollment is SUSPENDED and its parent offering is in OPEN, ENROLLMENT_CLOSED,
    or ACTIVE. This ENROLLED and SUSPENDED pair may cycle freely."

    Design: Difficulty/non_linear_state_machine/enrollment_suspend_resume_cycle
    """
    _, _, participant, enrollment = setup_enrolled_participant()
    ph = make_participant_headers(participant["id"])
    get_success_data(api.suspend_enrollment(enrollment["id"], ph))
    resumed = validate_success(api.resume_enrollment(enrollment["id"], ph))
    assert resumed["status"] == "ENROLLED", resumed


def test_suspend_resume_bumps_version_twice(api):
    """PRD §2.4: "an integer version that begins at 1 and increments by one on every
    mutation."
    PRD §3.3: "This ENROLLED and SUSPENDED pair may cycle freely."

    A fresh enrollment is version 1; suspend (+1) then resume (+1) => version 3.

    Design: Difficulty/non_linear_state_machine/enrollment_suspend_resume_cycle
    """
    _, _, participant, enrollment = setup_enrolled_participant()
    assert enrollment["version"] == 1, enrollment
    ph = make_participant_headers(participant["id"])
    get_success_data(api.suspend_enrollment(enrollment["id"], ph))
    resumed = validate_success(api.resume_enrollment(enrollment["id"], ph))
    assert resumed["version"] == 3, resumed


def _disqualifying_lot(api):
    """A purchased ShareLot (grant 2022-01-01, purchase 2022-06-30, price 850c,
    purchase_fmv 1200c). The exact lot size is read back, not assumed."""
    ctx = setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={
            "grant_date": "2022-01-01T00:00:00.000Z", "grant_date_fmv_cents": 1000,
        },
        batch_overrides={
            "purchase_date": "2022-06-30T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=15,
    )
    return ctx


def test_disqualifying_disposition_income_branch(api):
    """PRD §3.8: "The disposition is QUALIFYING when the sale_date is on or after the
    second anniversary of the lot's grant_date and also on or after the first
    anniversary of the lot's purchase_date; if either anniversary has not yet been
    reached, it is DISQUALIFYING."
    PRD §3.8: "For a disqualifying disposition, the ordinary_income_cents is fixed at
    the spread at purchase regardless of the sale price: the shares sold multiplied
    by the amount, never allowed below 0, by which the batch's purchase_date_fmv_cents
    exceeds the purchase's price_per_share_cents."

    Sale 2022-12-31 is before purchase+1y => DISQUALIFYING; income = shares_sold *
    (1200 - 850). shares_sold computed from the real lot to keep the value PRD-exact.

    Design: Difficulty/non_linear_state_machine/disposition_branching_qualifying_vs_disqualifying_sideeffects
    """
    ctx = _disqualifying_lot(api)
    lot = ctx["share_lot"]
    ph = make_participant_headers(ctx["participant"]["id"])
    shares = lot["shares_remaining"]
    disp = get_success_data(
        api.create_disposition(
            create_disposition_payload(
                lot["id"], ctx["participant"]["id"],
                sale_date="2022-12-31T00:00:00.000Z", shares_sold=shares,
                sale_price_per_share_cents=1500,
            ),
            ph,
        )
    )
    assert disp["disposition_type"] == "DISQUALIFYING", disp
    assert disp["ordinary_income_cents"] == shares * (1200 - 850), disp


def test_full_sale_cascades_share_lot_to_fully_disposed(api):
    """PRD §3.8: "recording it decrements the lot's shares_remaining by the shares
    sold; if that brings shares_remaining to exactly 0, the lot transitions from OPEN
    to FULLY_DISPOSED."

    Selling the entire remaining lot drives shares_remaining to 0 and the lot to
    FULLY_DISPOSED — the cross-entity cascade this instance targets.

    Design: Difficulty/non_linear_state_machine/disposition_branching_qualifying_vs_disqualifying_sideeffects
    """
    ctx = _disqualifying_lot(api)
    lot = ctx["share_lot"]
    ph = make_participant_headers(ctx["participant"]["id"])
    shares = lot["shares_remaining"]
    get_success_data(
        api.create_disposition(
            create_disposition_payload(
                lot["id"], ctx["participant"]["id"],
                sale_date="2022-12-31T00:00:00.000Z", shares_sold=shares,
                sale_price_per_share_cents=1500,
            ),
            ph,
        )
    )
    refreshed = validate_success(api.get_share_lot(lot["id"], ph))
    assert refreshed["shares_remaining"] == 0, refreshed
    assert refreshed["status"] == "FULLY_DISPOSED", refreshed
