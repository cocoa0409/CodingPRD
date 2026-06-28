"""Cascade and conserved-quantity tests (§2.6, §3.3, §3.4, §3.6, §3.7).

Plan cancellation runs compensating cascades (deposit refund + session cancel +
lot release). Commit cascades the plan ledger and provider counts. Loyalty
points and lot units are conserved across forward action + compensating reversal.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    make_provider_headers,
    make_clinic_admin_headers,
    setup_booked_session,
    setup_committed_session,
    setup_active_plan,
    book_session,
    add_before_photo,
    commit_session,
    open_complication,
    plan_version,
    assert_lot_conserved,
    assert_loyalty_conserved,
)


# ---------------------------------------------------------------------------
# transitive_cascade
# ---------------------------------------------------------------------------
def test_cancel_plan_cascades_session_cancel_and_lot_release(api):
    """PRD §3.3: "Cancellation runs two compensating cascades: every `POSTED`
    deposit on the plan is set to `REFUNDED`, after which `deposit_paid_cents`
    recomputes to 0; and every `BOOKED` session on the plan is set to `CANCELLED`,
    which releases the lot units each had reserved (described in §3.4)." PRD §3.4:
    "Cancelling is permitted only from `BOOKED` ... and moves the session to
    `CANCELLED`, releasing every reserved unit the session holds back to the
    relevant lots' `remaining_units` ..."

    Depth-3 cascade: cancel plan -> session `CANCELLED` -> lot units released. Lot
    returns to remaining 100 / reserved 0; deposit flips `REFUNDED`.

    Design: Difficulty/transitive_cascade/cancel_plan_cascades_session_cancel_releases_lot_units
    """
    sc = setup_booked_session(required_deposit_cents=5000, planned_units=20,
                              max_units_authorized=30, add_before=False)
    admin = make_clinic_admin_headers()
    pv = plan_version(sc.plan_id, sc.injector_id)
    plan = validate_success(api.cancel_plan(
        sc.plan_id, {"expected_treatment_plan_version": pv}, admin))
    assert plan["status"] == "CANCELLED"

    session = validate_success(api.get_treatment_session(
        sc.session_id, make_provider_headers(sc.injector_id)))
    assert session["status"] == "CANCELLED", (
        f"booked session should cascade to CANCELLED, got {session['status']}")

    lot = validate_success(api.get_injectable_lot(sc.lot_id, admin))
    assert lot["reserved_units"] == 0, (
        f"lot reserved_units should release to 0, got {lot['reserved_units']}")
    assert lot["remaining_units"] == 100, (
        f"lot remaining_units should restore to 100, got {lot['remaining_units']}")

    deposits, _ = validate_paginated(api.list_deposits(
        admin, params={"treatment_plan_id": sc.plan_id}))
    assert len(deposits) == 1
    assert deposits[0]["status"] == "REFUNDED", (
        f"POSTED deposit should cascade to REFUNDED, got {deposits[0]['status']}")


def test_cancel_plan_recomputes_deposit_paid_to_zero(api):
    """PRD §3.3: "Cancellation runs two compensating cascades: every `POSTED`
    deposit on the plan is set to `REFUNDED`, after which `deposit_paid_cents`
    recomputes to 0 ..."

    Design: Difficulty/transitive_cascade/cancel_plan_cascades_session_cancel_releases_lot_units
    """
    sc = setup_booked_session(required_deposit_cents=5000, planned_units=20,
                              max_units_authorized=30, add_before=False)
    admin = make_clinic_admin_headers()
    pv = plan_version(sc.plan_id, sc.injector_id)
    plan = validate_success(api.cancel_plan(
        sc.plan_id, {"expected_treatment_plan_version": pv}, admin))
    assert plan["status"] == "CANCELLED"
    assert plan["deposit_paid_cents"] == 0, (
        f"deposit_paid_cents should recompute to 0 after refund cascade, "
        f"got {plan['deposit_paid_cents']}")


def test_commit_cascades_plan_ledger(api):
    """PRD §3.6: "The plan's `finalized_series_cost_cents` increases by
    `final_charge_cents`, its `sessions_committed` increases by 1, its
    `provisional_series_cost_cents` recomputes over the remaining sessions, and its
    version increments by 1."

    Non-member 20u @1000 -> final_charge 20000; finalized becomes 20000,
    `sessions_committed` becomes 1.

    Design: Difficulty/transitive_cascade/commit_cascades_plan_ledger_and_provider_count
    """
    sc = setup_committed_session(member=False, list_price_per_unit_cents=1000,
                                 planned_units=20, max_units_authorized=30)
    hdr = make_provider_headers(sc.injector_id)
    plan = validate_success(api.get_treatment_plan(sc.plan_id, hdr))
    assert plan["finalized_series_cost_cents"] == 20000, (
        f"finalized_series_cost_cents should be 20000, "
        f"got {plan['finalized_series_cost_cents']}")
    assert plan["sessions_committed"] == 1, (
        f"sessions_committed should be 1, got {plan['sessions_committed']}")


def test_commit_cascades_provider_committed_count(api):
    """PRD §3.6: "Finally the injecting provider's `committed_session_count` is
    recomputed." PRD §3.6: "That line's cost is the `actual_units` multiplied by the
    plan's `list_price_per_unit_cents` multiplied by one minus the discount
    fraction, rounded half up to whole cents."

    After one commit the injector's `committed_session_count` is 1.

    Design: Difficulty/transitive_cascade/commit_cascades_plan_ledger_and_provider_count
    """
    sc = setup_committed_session(member=False, list_price_per_unit_cents=1000,
                                 planned_units=20, max_units_authorized=30)
    hdr = make_provider_headers(sc.injector_id)
    session = validate_success(api.get_treatment_session(sc.session_id, hdr))
    assert session["final_charge_cents"] == 20000
    provider = validate_success(api.get_provider(sc.injector_id, hdr))
    assert provider["committed_session_count"] == 1, (
        f"committed_session_count should be 1, got {provider['committed_session_count']}")


# ---------------------------------------------------------------------------
# compensating_invariant
# ---------------------------------------------------------------------------
def test_loyalty_points_conserved_under_commit_then_refund(api):
    """PRD §2.6: "A forward action followed by its compensating reversal must
    leave every one of these totals back at its pre-action value." PRD §3.7:
    "When the mode is `REFUND`, the system runs a compensation: it sets the case's
    `refund_cents` to the originating session's `final_charge_cents`; it reverses
    that session's loyalty by subtracting the session's `points_earned_cents_basis`
    from the loyalty account's `points_earned` and subtracting the session's
    `loyalty_points_redeemed` from its `points_redeemed`, then recomputing
    `points_balance`; and it subtracts the session's `final_charge_cents` from the
    plan's `finalized_series_cost_cents`."

    PLUS member, 2-session plan @1333. S1: 30u, redeem 0 -> charge 33992, earn
    339. S2: 20u, redeem 200 -> charge 22461, earn 224. `REFUND`-resolving S2's
    complication reverses exactly S2: earned 339, redeemed 0, balance 339;
    `refund_cents` 22461; plan finalized back to 33992.

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_under_commit_then_refund
    """
    sc = setup_active_plan(member=True, member_discount_pct=0.15,
                           loyalty_program="ALLE", list_price_per_unit_cents=1333,
                           planned_sessions=2, planned_units_per_session=30,
                           max_units_authorized=40, lot_units=200, open_loyalty=True)
    inj = sc.injector_id
    hdr = make_provider_headers(inj)

    # Session 1: 30u, redeem 0
    s1 = book_session(sc.plan_id, sc.standing_order_id, inj, sc.lot_id, 30,
                      sc.plan_version, loyalty_points_redeemed=0)
    add_before_photo(sc.patient_id, s1["id"], inj)
    commit_session(s1["id"], inj, actual_units=30)

    # Session 2: 20u, redeem 200
    pv = plan_version(sc.plan_id, inj)
    s2 = book_session(sc.plan_id, sc.standing_order_id, inj, sc.lot_id, 20, pv,
                      loyalty_points_redeemed=200)
    add_before_photo(sc.patient_id, s2["id"], inj)
    commit_session(s2["id"], inj, actual_units=20)

    case = open_complication(s2["id"], inj, severity="MODERATE")
    validate_success(api.resolve_complication(
        case["id"], {"resolution_mode": "REFUND"}, hdr))

    account = validate_success(api.get_loyalty_account(sc.loyalty_account_id, hdr))
    assert account["points_earned"] == 339, (
        f"points_earned should restore to 339, got {account['points_earned']}")
    assert account["points_redeemed"] == 0, (
        f"points_redeemed should restore to 0, got {account['points_redeemed']}")
    assert account["points_balance"] == 339, (
        f"points_balance should restore to 339, got {account['points_balance']}")
    assert_loyalty_conserved(account)

    resolved_case = validate_success(api.get_complication_case(case["id"], hdr))
    assert resolved_case["refund_cents"] == 22461, (
        f"refund_cents should equal S2 final_charge 22461, "
        f"got {resolved_case['refund_cents']}")

    plan = validate_success(api.get_treatment_plan(sc.plan_id, hdr))
    assert plan["finalized_series_cost_cents"] == 33992, (
        f"finalized should drop back to S1's 33992 after refund, "
        f"got {plan['finalized_series_cost_cents']}")


def test_loyalty_points_accumulate_forward_before_refund(api):
    """PRD §3.6: "The patient's loyalty account then adds `points_earned_cents_basis`
    to its `points_earned`, adds the session's `loyalty_points_redeemed` to its
    `points_redeemed`, and recomputes `points_balance`." PRD §2.6: "For every
    `LoyaltyAccount`, `points_balance` equals `points_earned` minus `points_redeemed`
    after every operation ..."

    Before any refund, two committed sessions (earn 339 then 224; redeem 0 then
    200) leave `points_earned`=563, `points_redeemed`=200, balance=363 — the forward
    ledger that the refund will later reverse.

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_under_commit_then_refund
    """
    sc = setup_active_plan(member=True, member_discount_pct=0.15,
                           loyalty_program="ALLE", list_price_per_unit_cents=1333,
                           planned_sessions=2, planned_units_per_session=30,
                           max_units_authorized=40, lot_units=200, open_loyalty=True)
    inj = sc.injector_id
    hdr = make_provider_headers(inj)
    s1 = book_session(sc.plan_id, sc.standing_order_id, inj, sc.lot_id, 30,
                      sc.plan_version, loyalty_points_redeemed=0)
    add_before_photo(sc.patient_id, s1["id"], inj)
    commit_session(s1["id"], inj, actual_units=30)
    pv = plan_version(sc.plan_id, inj)
    s2 = book_session(sc.plan_id, sc.standing_order_id, inj, sc.lot_id, 20, pv,
                      loyalty_points_redeemed=200)
    add_before_photo(sc.patient_id, s2["id"], inj)
    commit_session(s2["id"], inj, actual_units=20)

    account = validate_success(api.get_loyalty_account(sc.loyalty_account_id, hdr))
    assert account["points_earned"] == 563, (
        f"points_earned should be 339+224=563, got {account['points_earned']}")
    assert account["points_redeemed"] == 200, (
        f"points_redeemed should be 200, got {account['points_redeemed']}")
    assert account["points_balance"] == 363, (
        f"points_balance should be 563-200=363, got {account['points_balance']}")
    assert_loyalty_conserved(account)


def test_lot_units_conserved_under_book_then_cancel(api):
    """PRD §2.6: "For every `InjectableLot`, the relationship `remaining_units` equals
    `total_units` minus `reserved_units` minus `consumed_units` holds after every
    operation ..." PRD §3.4: "Cancelling is permitted only from `BOOKED` ... and
    moves the session to `CANCELLED`, releasing every reserved unit the session
    holds back to the relevant lots' `remaining_units` ..."

    Booking 20 of a 100-unit lot moves 20 to reserved; cancelling releases them,
    restoring remaining 100 / reserved 0 / consumed 0.

    Design: Difficulty/compensating_invariant/lot_units_conserved_under_book_then_cancel
    """
    sc = setup_booked_session(planned_units=20, max_units_authorized=30, add_before=False)
    admin = make_clinic_admin_headers()
    lot_after_book = validate_success(api.get_injectable_lot(sc.lot_id, admin))
    assert lot_after_book["reserved_units"] == 20, (
        f"lot should reserve 20 after booking, got {lot_after_book['reserved_units']}")

    session = validate_success(api.cancel_session(sc.session_id, admin))
    assert session["status"] == "CANCELLED"

    lot = validate_success(api.get_injectable_lot(sc.lot_id, admin))
    assert lot["remaining_units"] == 100, (
        f"remaining_units should restore to 100, got {lot['remaining_units']}")
    assert lot["reserved_units"] == 0, (
        f"reserved_units should release to 0, got {lot['reserved_units']}")
    assert lot["consumed_units"] == 0, (
        f"consumed_units should stay 0, got {lot['consumed_units']}")
    assert_lot_conserved(lot)


def test_lot_conservation_holds_at_booked_state(api):
    """PRD §2.6: "For every `InjectableLot`, the relationship `remaining_units` equals
    `total_units` minus `reserved_units` minus `consumed_units` holds after every
    operation; `total_units` is fixed at intake and never changes thereafter, while
    `reserved_units` and `consumed_units` move as sessions reserve, commit, cancel, or
    no-show." PRD §3.4: "incrementing the lot's `reserved_units` and recomputing its
    `remaining_units`, until the full `planned_units` are reserved."

    Booking 20 of a 100-unit lot yields reserved 20, remaining 80, consumed 0 —
    with total == remaining + reserved + consumed == 100.

    Design: Difficulty/compensating_invariant/lot_units_conserved_under_book_then_cancel
    """
    sc = setup_booked_session(planned_units=20, max_units_authorized=30, add_before=False)
    admin = make_clinic_admin_headers()
    lot = validate_success(api.get_injectable_lot(sc.lot_id, admin))
    assert lot["reserved_units"] == 20, (
        f"reserved_units should be 20 after booking, got {lot['reserved_units']}")
    assert lot["remaining_units"] == 80, (
        f"remaining_units should be 80 after booking, got {lot['remaining_units']}")
    assert lot["consumed_units"] == 0
    assert lot["total_units"] == 100
    assert_lot_conserved(lot)
