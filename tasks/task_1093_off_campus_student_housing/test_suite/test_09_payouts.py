"""Payout settlement: tiered pricing, window filtering, empty-period guard,
overlap guard, segregation of duties, pipeline transitions, and the
disburse/reverse money-conservation invariant.

Translates corner instances (invalid pipeline, window filtering, period
overlap, segregation of duties) and three difficulty instances:
`payout_tier_keyed_on_gross_then_rebate_keyed_on_subtotal`,
`payout_period_with_zero_collections_is_rejected`, and
`payout_disbursement_and_reversal_conserve_property_money` (queue A).
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx
from test_helpers import make_student_headers, make_admin_headers

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = make_admin_headers("admin-2")


def _create_payout(api, prop_id, start, end, admin=ADMIN):
    v = fx.get_property(api, prop_id)["version"]
    return api.create_payout({"property_id": prop_id, "period_start_date": start,
                              "period_end_date": end, "expected_property_version": v}, admin)


def _one_paid_lease(api):
    """Active lease + first installment (98667) paid at 2026-08-16 -> escrow 98667."""
    sc = fx.setup_active_lease(api, installment_count=10)
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    i1 = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    api.pay_installment(i1["id"], {"amount_cents": 98667}, make_student_headers(sc["student_id"]))
    return sc


def _two_paid_leases(api):
    """base + two active leases (beds A/B), both first installments paid at
    2026-08-16 -> property escrow 197334."""
    base = fx.base_property(api)
    s1 = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    s2 = fx.verified_student(api, base["uni"]["id"], "ben@su.edu", full_name="Ben Two",
                             cleanliness_level=3, noise_tolerance=4)
    l1 = fx.active_lease(api, s1["id"], base["unit"]["id"], "A")
    l2 = fx.active_lease(api, s2["id"], base["unit"]["id"], "B")
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    i1 = fx.rent_installments(api, l1["id"], s1["id"])[0]
    i2 = fx.rent_installments(api, l2["id"], s2["id"])[0]
    api.pay_installment(i1["id"], {"amount_cents": 98667}, make_student_headers(s1["id"]))
    api.pay_installment(i2["id"], {"amount_cents": 98667}, make_student_headers(s2["id"]))
    return base, (l1, s1), (l2, s2)


def test_payout_tier_and_fee_from_pre_fee_gross(api):
    """PRD §3.9: "the fee tier, keyed on that pre-fee gross alone:
    platform_fee_bps is 900 when the gross is below 500000 cents ... the fee and
    holdback, each rounded once off the gross: platform_fee_cents is the gross
    times platform_fee_bps divided by 10000 rounded half up, and holdback_cents
    is the gross times 200 basis points divided by 10000 rounded half up."

    Design: Difficulty/combinatorial_formula/payout_tier_keyed_on_gross_then_rebate_keyed_on_subtotal
    """
    base, *_ = _two_paid_leases(api)
    assert fx.get_property(api, base["prop"]["id"])["escrow_balance_cents"] == 197334
    po = validate_success(_create_payout(api, base["prop"]["id"], "2026-08-01", "2026-08-31"), 201)
    assert po["gross_collected_cents"] == 197334
    assert po["platform_fee_bps"] == 900
    assert po["platform_fee_cents"] == 17760
    assert po["holdback_cents"] == 3947


def test_payout_subtotal_rebate_and_net(api):
    """PRD §3.9: "subtotal_cents is the gross minus the fee minus the holdback.
    Fifth, the loyalty rebate: when subtotal_cents is at least 150000 cents,
    rebate_cents is the platform_fee_cents times 1000 basis points divided by
    10000 rounded half up ... Sixth, net_amount_cents is subtotal_cents plus
    rebate_cents."

    Design: Difficulty/combinatorial_formula/payout_tier_keyed_on_gross_then_rebate_keyed_on_subtotal
    """
    base, *_ = _two_paid_leases(api)
    po = validate_success(_create_payout(api, base["prop"]["id"], "2026-08-01", "2026-08-31"), 201)
    assert po["subtotal_cents"] == 175627
    assert po["rebate_cents"] == 1776
    assert po["net_amount_cents"] == 177403
    assert po["status"] == "SUBMITTED" and po["submitted_by_user_id"] == "admin-1"


def test_payout_empty_period_is_rejected(api):
    """PRD §3.9: "this must be strictly greater than 0, or the create is refused
    with ERR_PAYOUT_EMPTY_PERIOD."

    Design: Difficulty/boundary_precision_check/payout_period_with_zero_collections_is_rejected
    """
    sc = _one_paid_lease(api)
    validate_error(_create_payout(api, sc["prop"]["id"], "2026-06-01", "2026-06-30"),
                   ApiErrorId.ERR_PAYOUT_EMPTY_PERIOD.value)
    _, meta = validate_paginated(api.list_payouts(ADMIN, params={"property_id": sc["prop"]["id"]}))
    assert meta["total_count"] == 0


def test_payout_tier1_no_rebate_when_subtotal_below_floor(api):
    """PRD §3.9: "platform_fee_bps is 900 when the gross is below 500000 cents"
    and "otherwise 0" for the rebate when subtotal is below 150000.

    Design: Difficulty/boundary_precision_check/payout_period_with_zero_collections_is_rejected
    """
    sc = _one_paid_lease(api)
    po = validate_success(_create_payout(api, sc["prop"]["id"], "2026-08-01", "2026-08-31"), 201)
    assert po["gross_collected_cents"] == 98667
    assert po["platform_fee_bps"] == 900 and po["platform_fee_cents"] == 8880
    assert po["holdback_cents"] == 1973 and po["subtotal_cents"] == 87814
    assert po["rebate_cents"] == 0  # subtotal 87814 below 150000
    assert po["net_amount_cents"] == 87814


def test_payout_pay_debits_escrow_and_credits_reserve(api):
    """PRD §3.9: "Paying an APPROVED payout moves it APPROVED -> PAID, stamps
    paid_at, decreases the property's escrow_balance_cents by
    gross_collected_cents, increases maintenance_reserve_cents by
    holdback_cents, re-derives payout_eligible".

    Design: Difficulty/compensating_invariant/payout_disbursement_and_reversal_conserve_property_money
    """
    base, (l1, s1), (l2, s2) = _two_paid_leases(api)
    po = validate_success(_create_payout(api, base["prop"]["id"], "2026-08-01", "2026-08-31"), 201)
    api.decide_payout(po["id"], {"decision": "APPROVE"}, ADMIN2)
    before = fx.get_property(api, base["prop"]["id"])
    assert before["escrow_balance_cents"] == 197334 and before["maintenance_reserve_cents"] == 0
    assert before["payout_eligible"] is True
    paid = validate_success(api.pay_payout(po["id"], ADMIN2), 200)
    assert paid["status"] == "PAID" and paid["approved_by_user_id"] == "admin-2"
    prop = fx.get_property(api, base["prop"]["id"])
    assert prop["escrow_balance_cents"] == 0
    assert prop["maintenance_reserve_cents"] == 3947
    assert prop["payout_eligible"] is False


def test_payout_reversal_conserves_property_money(api):
    """PRD §3.9: "Reversing a PAID payout is the compensating action: it moves it
    PAID -> REVERSED, stamps reversed_at, returns the exact gross_collected_cents
    to escrow, removes the holdback_cents from the maintenance reserve ...
    leaving the conserved escrow quantity identical before the pay and after the
    reverse."

    Design: Difficulty/compensating_invariant/payout_disbursement_and_reversal_conserve_property_money
    """
    base, (l1, s1), (l2, s2) = _two_paid_leases(api)
    po = validate_success(_create_payout(api, base["prop"]["id"], "2026-08-01", "2026-08-31"), 201)
    api.decide_payout(po["id"], {"decision": "APPROVE"}, ADMIN2)
    api.pay_payout(po["id"], ADMIN2)
    rev = validate_success(api.reverse_payout(po["id"], ADMIN2, {"reason": "Bank returned the wire"}), 200)
    assert rev["status"] == "REVERSED"
    prop = fx.get_property(api, base["prop"]["id"])
    assert prop["escrow_balance_cents"] == 197334
    assert prop["maintenance_reserve_cents"] == 0
    assert prop["payout_eligible"] is True
    assert fx.get_lease(api, l1["id"])["paid_cents"] == 98667
    assert fx.get_lease(api, l2["id"])["paid_cents"] == 98667


def test_payout_invalid_pipeline_transitions_rejected(api):
    """PRD §3.9: "Deciding a payout that is not SUBMITTED is
    ERR_PAYOUT_INVALID_STATE ... Paying a payout that is not APPROVED, or
    reversing one that is not PAID, is ERR_PAYOUT_INVALID_STATE."

    Design: Corner/state_machines/payout_invalid_pipeline_transitions_rejected
    """
    sc = _one_paid_lease(api)
    po = validate_success(_create_payout(api, sc["prop"]["id"], "2026-08-01", "2026-08-31"), 201)
    validate_error(api.pay_payout(po["id"], ADMIN2), ApiErrorId.ERR_PAYOUT_INVALID_STATE.value)
    assert api.get_payout(po["id"], ADMIN).json()["data"]["status"] == "SUBMITTED"
    rej = validate_success(api.decide_payout(po["id"], {"decision": "REJECT", "note": "Wrong period"}, ADMIN2), 200)
    assert rej["status"] == "REJECTED" and rej["approved_by_user_id"] == "admin-2"
    validate_error(api.reverse_payout(po["id"], ADMIN2, {"reason": "changed mind"}),
                   ApiErrorId.ERR_PAYOUT_INVALID_STATE.value)
    prop = fx.get_property(api, sc["prop"]["id"])
    assert prop["escrow_balance_cents"] == 98667 and prop["maintenance_reserve_cents"] == 0


def test_payout_gross_excludes_payments_outside_the_closed_window(api):
    """PRD §3.9: "the sum of amount_cents plus late_fee_cents over PAID
    installments on the property's leases whose paid_at calendar date lies
    within the closed window".

    Design: Corner/calculations/payout_gross_excludes_payments_outside_the_closed_window
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    sid = make_student_headers(sc["student_id"])
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    api.pay_installment(rows[0]["id"], {"amount_cents": 98667}, sid)
    fx.set_clock(api, "2026-09-20T00:00:00Z")
    api.pay_installment(rows[1]["id"], {"amount_cents": 98667}, sid)  # late -> 103600
    assert fx.get_property(api, sc["prop"]["id"])["escrow_balance_cents"] == 202267
    po = validate_success(_create_payout(api, sc["prop"]["id"], "2026-09-01", "2026-09-30"), 201)
    assert po["gross_collected_cents"] == 103600  # 2026-08-16 payment excluded
    assert po["platform_fee_bps"] == 900 and po["platform_fee_cents"] == 9324
    assert po["holdback_cents"] == 2072 and po["subtotal_cents"] == 92204
    assert po["rebate_cents"] == 0 and po["net_amount_cents"] == 92204


def test_payout_period_overlap_rejected(api):
    """PRD §3.9: "The requested window may not overlap the closed window of
    another payout on the same property that is SUBMITTED, APPROVED, or PAID,
    else ERR_PAYOUT_PERIOD_OVERLAP."

    Design: Corner/validations/payout_period_overlap_rejected
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    sid = make_student_headers(sc["student_id"])
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    api.pay_installment(rows[0]["id"], {"amount_cents": 98667}, sid)
    fx.set_clock(api, "2026-09-20T00:00:00Z")
    api.pay_installment(rows[1]["id"], {"amount_cents": 98667}, sid)
    aug = validate_success(_create_payout(api, sc["prop"]["id"], "2026-08-01", "2026-08-31"), 201)
    assert aug["gross_collected_cents"] == 98667
    validate_error(_create_payout(api, sc["prop"]["id"], "2026-08-15", "2026-09-15"),
                   ApiErrorId.ERR_PAYOUT_PERIOD_OVERLAP.value)
    sep = validate_success(_create_payout(api, sc["prop"]["id"], "2026-09-01", "2026-09-30"), 201)
    assert sep["gross_collected_cents"] == 103600
    _, meta = validate_paginated(api.list_payouts(ADMIN, params={"property_id": sc["prop"]["id"]}))
    assert meta["total_count"] == 2


def test_payout_segregation_of_duties_blocks_self_approval(api):
    """PRD §3.9: "the acting X-User-ID must differ from submitted_by_user_id, or
    the decision is refused with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/validations/payout_segregation_of_duties_blocks_self_approval
    """
    sc = _one_paid_lease(api)
    po = validate_success(_create_payout(api, sc["prop"]["id"], "2026-08-01", "2026-08-31"), 201)
    validate_error(api.decide_payout(po["id"], {"decision": "APPROVE"}, ADMIN),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert api.get_payout(po["id"], ADMIN).json()["data"]["status"] == "SUBMITTED"
    ok = validate_success(api.decide_payout(po["id"], {"decision": "APPROVE"}, ADMIN2), 200)
    assert ok["status"] == "APPROVED" and ok["approved_by_user_id"] == "admin-2"
