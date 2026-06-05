"""Difficulty rule 4 — transitive depth-3 cascade chains (PRD §3.5, §3.6, §3.7).

Cancel-offering => withdraw enrollments => refund contributions; and run-purchase
last batch => close offering => complete enrollments (+ charge accrual ledger).
"""
from test_helpers import (
    validate_success,
    get_success_data,
    setup_enrolled_participant,
    contribute,
    close_enrollment,
    create_purchase_period,
    open_batch,
    certify_batch,
    run_batch,
    make_participant_headers,
)


# ─── Instance 1: cancel offering -> withdraw -> refund (depth 3) ────
def test_cancel_offering_withdraws_enrollment(api, admin_headers):
    """PRD §3.7: "The cancellation triggers a deep cascade: every enrollment under
    the offering transitions to WITHDRAWN, and each such withdrawal refunds all of
    that enrollment's POSTED contributions (each affected contribution becomes
    REFUNDED and the enrollment's refunded_contribution_cents is recomputed)".

    Design: Difficulty/transitive_cascade/cancel_offering_withdraws_enrollment_refunds_contributions_depth3
    """
    _, offering, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    contribute(enrollment["id"], gross_pay_cents=500000)  # 10% => 50000c POSTED
    cancelled = validate_success(api.cancel_offering(offering["id"], admin_headers))
    assert cancelled["status"] == "CANCELLED", cancelled
    refreshed = validate_success(api.get_enrollment(enrollment["id"], admin_headers))
    assert refreshed["status"] == "WITHDRAWN", refreshed


def test_cancel_offering_refunds_contributions(api, admin_headers):
    """PRD §3.7: "each such withdrawal refunds all of that enrollment's POSTED
    contributions (each affected contribution becomes REFUNDED and the enrollment's
    refunded_contribution_cents is recomputed)".

    50000c POSTED (gross 500000 at 10%) => after cancel, the contribution is REFUNDED
    and enrollment.refunded_contribution_cents == 50000.

    Design: Difficulty/transitive_cascade/cancel_offering_withdraws_enrollment_refunds_contributions_depth3
    """
    _, offering, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    contribute(enrollment["id"], gross_pay_cents=500000)
    get_success_data(api.cancel_offering(offering["id"], admin_headers))
    refreshed = validate_success(api.get_enrollment(enrollment["id"], admin_headers))
    assert refreshed["refunded_contribution_cents"] == 50000, refreshed
    contributions, _ = _list(api, api.list_contributions, admin_headers,
                             {"enrollment_id": enrollment["id"]})
    assert contributions, "expected at least one contribution"
    assert all(c["status"] == "REFUNDED" for c in contributions), contributions


# ─── Instance 2: run last batch -> close offering -> complete enrollment ──
def _single_batch_certified(rate_pct=10, gross=1000000):
    _, offering, participant, enrollment = setup_enrolled_participant(
        offering_overrides={"grant_date_fmv_cents": 1000, "duration_months": 6},
        rate_pct=rate_pct,
    )
    contribute(enrollment["id"], gross_pay_cents=gross)
    close_enrollment(offering["id"])
    batch = create_purchase_period(
        offering["id"], purchase_date="2024-05-31T00:00:00.000Z",
        purchase_date_fmv_cents=1200,
    )
    open_batch(batch["id"])
    certified = certify_batch(batch["id"])
    return offering, participant, enrollment, batch, certified["version"]


def test_run_purchase_closes_offering_and_completes_enrollment(api, admin_headers):
    """PRD §3.7: "When the buy is run on a batch and that batch is the last
    non-terminal purchase period in its offering ... the parent offering bubbles up
    from ACTIVE to CLOSED. As the offering closes, every enrollment under it still in
    ENROLLED status auto-transitions to COMPLETED."

    Design: Difficulty/transitive_cascade/run_purchase_charges_ledger_closes_offering_completes_enrollment_depth3
    """
    offering, participant, enrollment, batch, version = _single_batch_certified()
    run_batch(batch["id"], version)
    off = validate_success(api.get_offering_period(offering["id"], admin_headers))
    assert off["status"] == "CLOSED", off
    enr = validate_success(api.get_enrollment(enrollment["id"], admin_headers))
    assert enr["status"] == "COMPLETED", enr


def test_run_purchase_charges_accrual_ledger(api, admin_headers):
    """PRD §3.5: "the grant_date_value_applied_cents charged against the annual
    accrual cap (the shares purchased multiplied by the offering's
    grant_date_fmv_cents)".
    PRD §3.6: "After the buy, the charged grant_date_value_applied_cents is added
    into the participant-year's accrued_grant_value_cents".

    gross 1000000 at 10% => 100000c; price = round_half_up(1000*0.85)=850;
    shares = floor(100000/850) = 117; grant value = 117*1000 = 117000.

    Design: Difficulty/transitive_cascade/run_purchase_charges_ledger_closes_offering_completes_enrollment_depth3
    """
    offering, participant, enrollment, batch, version = _single_batch_certified()
    run_batch(batch["id"], version)
    ledgers, _ = _list(api, api.list_accrual_ledgers, admin_headers,
                       {"participant_id": participant["id"]})
    rows_2024 = [l for l in ledgers if l["calendar_year"] == 2024]
    assert len(rows_2024) == 1, ledgers
    assert rows_2024[0]["accrued_grant_value_cents"] == 117000, rows_2024[0]


def _list(api, list_fn, headers, params):
    resp = list_fn(headers, params=params)
    body = resp.json()
    return body["data"], body["meta"]
