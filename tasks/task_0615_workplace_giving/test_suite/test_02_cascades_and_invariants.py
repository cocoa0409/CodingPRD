"""Cascading side effects and compensating (conserved-quantity) invariants.

Covers the depth-3 cascades triggered by donation settle and batch settle, the cap-conservation
invariants on refund / reverse, the exact-cap CAPPED boundary, and immediate consistency
(PRD 2.8, 3.6, 3.7, 3.8).
"""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    setup_giving_scenario,
    create_authorized_donation,
    create_settled_donation,
    create_approved_volunteer_log,
    get_matching_gift_for_donation,
    setup_locked_match_batch,
)

PM = TEST_USERS["program_manager_headers"]
GA = TEST_USERS["giving_admin_headers"]


# ===========================================================================
# Difficulty / transitive_cascade
# ===========================================================================
def test_donation_settle_cascades_to_match_finalize_and_cap_debit(api):
    """PRD 3.6: "Finalization is the side effect of the linked donation moving from `AUTHORIZED`
    to `SETTLED`. At that point the platform recomputes `matched_amount_cents` against live
    consumption. If the clamped result is greater than zero, the matching gift transitions from
    `REQUESTED` to `FINALIZED` and the employee's `match_consumed_ytd_cents` is increased by that
    matched amount."

    Design: Difficulty/transitive_cascade/donation_settle_to_match_to_cap_depth3
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    # base 40000, match_ratio 0.5 -> matched 20000.
    don = create_authorized_donation(s, base_amount_cents=40000, request_match=True)

    settled = validate_success(api.settle_donation(don["id"], GA))
    assert settled["status"] == "SETTLED"

    mg = get_matching_gift_for_donation(don["id"])
    assert mg["status"] == "FINALIZED"
    assert mg["matched_amount_cents"] == 20000

    emp = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp["match_consumed_ytd_cents"] == 20000


def test_donation_settle_raises_campaign_total(api):
    """PRD 3.5: "Settlement moves the donation to `SETTLED`, stamps `settled_at` with the current
    clock value, and increases the campaign's `raised_cents` by the donation's `base_amount_cents`."

    Design: Difficulty/transitive_cascade/donation_settle_to_match_to_cap_depth3
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    don = create_authorized_donation(s, base_amount_cents=40000, request_match=True)
    validate_success(api.settle_donation(don["id"], GA))

    camp = validate_success(api.get_campaign(s["campaign"]["id"], GA))
    assert camp["raised_cents"] == 40000


def test_batch_settle_cascades_to_grant_and_match_settled(api):
    """PRD 3.8: "Settlement then propagates: every `STAGED` grant moves to `SETTLED`; for each
    grant whose source is a match, the underlying matching gift moves from `FINALIZED` to
    `SETTLED` ... the beneficiary charity's `total_received_cents` is increased by the batch's
    `net_total_cents`."

    Design: Difficulty/transitive_cascade/batch_settle_to_grant_to_match_settled_depth3
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    built = setup_locked_match_batch(
        s, base_amount_cents=40000, period_start="2026-01-01T00:00:00Z", period_end="2026-06-30T00:00:00Z"
    )
    settled = validate_success(api.settle_disbursement_batch(built["batch"]["id"], GA))
    assert settled["status"] == "SETTLED"

    grant = validate_success(api.get_grant(built["grant"]["id"], GA))
    assert grant["status"] == "SETTLED"
    assert grant["gross_amount_cents"] == 20000

    mg = validate_success(api.get_matching_gift(built["matching_gift"]["id"], GA))
    assert mg["status"] == "SETTLED"


def test_batch_settle_credits_charity_total_received(api):
    """PRD 3.8: "the beneficiary charity's `total_received_cents` is increased by the batch's
    `net_total_cents` (each settled grant contributing its `net_amount_cents`) ... a charity's
    `total_received_cents` is precisely the sum of `net_amount_cents` over its grants in
    `SETTLED`."

    Design: Difficulty/transitive_cascade/batch_settle_to_grant_to_match_settled_depth3
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    built = setup_locked_match_batch(
        s, base_amount_cents=40000, period_start="2026-01-01T00:00:00Z", period_end="2026-06-30T00:00:00Z"
    )
    validate_success(api.settle_disbursement_batch(built["batch"]["id"], GA))

    # gross 20000, fee floor(20000*0.025)=500, net 19500.
    charity = validate_success(api.get_charity(s["charity"]["id"], GA))
    assert charity["total_received_cents"] == 19500


# ===========================================================================
# Difficulty / boundary_precision_check (match cap exact)
# ===========================================================================
def test_match_cap_exact_consumed_yields_capped_zero(api):
    """PRD 3.6: "If the clamped result is exactly zero — because the annual cap is already fully
    consumed — the matching gift transitions from `REQUESTED` to `CAPPED` with its
    `matched_amount_cents` set to zero and no consumption debit; `CAPPED` is terminal for a fully
    consumed cap."

    Design: Difficulty/boundary_precision_check/match_cap_exact_consumed_yields_capped_zero
    """
    # cap 100000; D0 base 200000 -> matched 100000 fully consumes cap.
    s = setup_giving_scenario(
        employee_overrides={"annual_salary_cents": 24000000},
        campaign_overrides={"goal_cents": 5000000},
    )
    create_settled_donation(s, base_amount_cents=200000, request_match=True)

    # D1 base 10000 with request_match; remaining cap is exactly 0 at settle.
    d1 = create_authorized_donation(s, base_amount_cents=10000, request_match=True)
    validate_success(api.settle_donation(d1["id"], GA))

    mg1 = get_matching_gift_for_donation(d1["id"])
    assert mg1["matched_amount_cents"] == 0
    assert mg1["status"] == "CAPPED"

    emp = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp["match_consumed_ytd_cents"] == 100000


def test_match_cap_no_consumption_debit_on_capped(api):
    """PRD 3.6: "the matching gift transitions from `REQUESTED` to `CAPPED` with its
    `matched_amount_cents` set to zero and no consumption debit; `CAPPED` is terminal for a fully
    consumed cap."

    Design: Difficulty/boundary_precision_check/match_cap_exact_consumed_yields_capped_zero
    """
    s = setup_giving_scenario(
        employee_overrides={"annual_salary_cents": 24000000},
        campaign_overrides={"goal_cents": 5000000},
    )
    create_settled_donation(s, base_amount_cents=200000, request_match=True)
    d1 = create_authorized_donation(s, base_amount_cents=10000, request_match=True)
    validate_success(api.settle_donation(d1["id"], GA))

    # The cap counter is unchanged by the CAPPED gift (no debit beyond the prior 100000).
    emp = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp["match_consumed_ytd_cents"] == 100000, "no further debit on a CAPPED match"


# ===========================================================================
# Difficulty / compensating_invariant
# ===========================================================================
def test_match_cap_conserved_on_settle_then_refund(api):
    """PRD 3.6: "If the linked donation is refunded while its matching gift is still `FINALIZED`
    (not yet `SETTLED`), the platform reverses the gift: it transitions from `FINALIZED` to the
    terminal `REVERSED` state and credits the employee's `match_consumed_ytd_cents` back by the
    matched amount, undoing the earlier debit."

    Design: Difficulty/compensating_invariant/match_cap_conserved_on_settle_then_refund
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    don = create_settled_donation(s, base_amount_cents=40000, request_match=True)
    mg = get_matching_gift_for_donation(don["id"])
    assert mg["matched_amount_cents"] == 20000

    emp_before = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp_before["match_consumed_ytd_cents"] == 20000

    refunded = validate_success(api.refund_donation(don["id"], GA))
    assert refunded["status"] == "REFUNDED"

    mg_after = validate_success(api.get_matching_gift(mg["id"], GA))
    assert mg_after["status"] == "REVERSED"

    emp_after = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp_after["match_consumed_ytd_cents"] == 0, "cap consumption returns to pre-donation value"


def test_match_refund_decrements_campaign_raised(api):
    """PRD 3.5: "A refund decreases the campaign's `raised_cents` by the donation's
    `base_amount_cents`, and if the donation's matching gift is in `FINALIZED`, the refund
    reverses that gift as described in 3.7."

    Design: Difficulty/compensating_invariant/match_cap_conserved_on_settle_then_refund
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    don = create_settled_donation(s, base_amount_cents=40000, request_match=True)

    camp_before = validate_success(api.get_campaign(s["campaign"]["id"], GA))
    assert camp_before["raised_cents"] == 40000

    validate_success(api.refund_donation(don["id"], GA))

    camp_after = validate_success(api.get_campaign(s["campaign"]["id"], GA))
    assert camp_after["raised_cents"] == 0


def test_dfd_cap_conserved_on_approve_then_reverse(api):
    """PRD 3.7: "Before a grant has been staged or settled against it, an `APPROVED` log may be
    reversed by the administering role, moving it to the terminal `REVERSED` state and crediting
    the employee's `dfd_consumed_ytd_cents` back by the grant amount."

    Design: Difficulty/compensating_invariant/dfd_cap_conserved_on_approve_then_reverse
    """
    s = setup_giving_scenario()
    # 630 minutes / 60 * 1500 = floor(15750) = 15750 (under cap 25000).
    log = create_approved_volunteer_log(s, minutes=630, activity_date="2026-03-15T00:00:00Z")
    assert log["grant_amount_cents"] == 15750

    emp_before = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp_before["dfd_consumed_ytd_cents"] == 15750

    reversed_log = validate_success(api.reverse_volunteer_log(log["id"], GA))
    assert reversed_log["status"] == "REVERSED"

    emp_after = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp_after["dfd_consumed_ytd_cents"] == 0, "DfD consumption returns to pre-approval value"


def test_dfd_reverse_preserves_recorded_grant_amount(api):
    """PRD 3.7: "an `APPROVED` log may be reversed by the administering role, moving it to the
    terminal `REVERSED` state and crediting the employee's `dfd_consumed_ytd_cents` back by the
    grant amount."

    Design: Difficulty/compensating_invariant/dfd_cap_conserved_on_approve_then_reverse
    """
    s = setup_giving_scenario()
    log = create_approved_volunteer_log(s, minutes=630, activity_date="2026-03-15T00:00:00Z")
    reversed_log = validate_success(api.reverse_volunteer_log(log["id"], GA))
    # The grant amount recorded on the row is preserved (the credit is to the employee counter).
    assert reversed_log["grant_amount_cents"] == 15750


# ===========================================================================
# Corner / consistency_model
# ===========================================================================
def test_settle_immediately_reflected_in_campaign(api):
    """PRD 3.5: "Settlement moves the donation to `SETTLED`, stamps `settled_at` with the current
    clock value, and increases the campaign's `raised_cents` by the donation's `base_amount_cents`."

    Design: Corner/consistency_model/immediate_consistency_settle_reflected_in_same_response
    """
    s = setup_giving_scenario()
    don = create_authorized_donation(s, base_amount_cents=5000)

    settled = validate_success(api.settle_donation(don["id"], GA))
    assert settled["status"] == "SETTLED"

    camp = validate_success(api.get_campaign(s["campaign"]["id"], GA))
    assert camp["raised_cents"] == 5000, "raised_cents reflects the settlement immediately"
