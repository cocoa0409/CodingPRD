"""Installment schedule allocation, lateness/grace, late-fee cap, payment
escrow cascade, funding-status axis independence, termination voiding, and
auto-end.

Translates corner instances (late-fee grace/cap, termination voiding,
auto-end) and four difficulty instances:
`installment_floor_first_then_residual_to_last_row`,
`lease_status_and_funding_status_axes_move_independently`,
`installment_payment_four_hop_escrow_cascade`, and
`installment_state_error_outranks_payment_amount_mismatch` (queue A).
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx
from test_helpers import make_student_headers

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]


def test_installment_schedule_amounts_floor_then_residual(api):
    """PRD §3.6: "floor the per-installment base share first - the contract
    total divided by the count, truncated - assign that base to installments 1
    through the second-to-last, and push the entire residual onto the last
    installment ... the sum of the schedule equals total_contract_cents to the
    cent, whereas rounding each line independently would not."

    Design: Difficulty/combinatorial_formula/installment_floor_first_then_residual_to_last_row
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    assert len(rows) == 10
    amounts = [r["amount_cents"] for r in rows]
    assert amounts[:9] == [98667] * 9
    assert amounts[9] == 98676
    assert sum(amounts) == 986679 == sc["lease"]["total_contract_cents"]
    assert 98668 not in amounts  # the round-half-up-per-line reading is not used


def test_installment_schedule_due_dates_and_initial_status(api):
    """PRD §3.6: "a due_date that is the lease's term_start_date advanced by 30
    days for each step past the first." PRD §3.6: "a status of SCHEDULED".

    Design: Difficulty/combinatorial_formula/installment_floor_first_then_residual_to_last_row
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    assert rows[0]["sequence_number"] == 1 and rows[0]["due_date"] == "2026-08-15"
    assert rows[1]["due_date"] == "2026-09-14"
    assert rows[8]["due_date"] == "2027-04-12"
    assert rows[9]["sequence_number"] == 10 and rows[9]["due_date"] == "2027-05-12"
    for r in rows:
        assert r["status"] == "SCHEDULED" and r["late_fee_cents"] == 0 and r["paid_cents"] == 0


def test_funding_axis_goes_delinquent_while_lease_stays_active(api):
    """PRD §2.5: "whose due date plus the five-day grace window falls strictly
    before the new clock date, is moved to LATE, and each affected lease's
    funding_status is recomputed to DELINQUENT."

    Design: Difficulty/non_linear_state_machine/lease_status_and_funding_status_axes_move_independently
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    i1 = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    clk = validate_success(api.set_clock("2026-08-21T00:00:00Z", ADMIN), 200)
    assert clk["installments_marked_late_count"] == 1
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    assert rows[0]["status"] == "LATE"
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["funding_status"] == "DELINQUENT" and lease["lease_status"] == "ACTIVE"


def test_funding_axis_returns_current_after_payment_lease_stays_active(api):
    """PRD §3.6: "When it was LATE, the late fee is the amount_cents times 500
    basis points, divided by 10000 and rounded half up, then capped at 7500
    cents". PRD §3.6: "else if every non-VOID charge whose due_date is at or
    before the clock date is PAID, CURRENT".

    Design: Difficulty/non_linear_state_machine/lease_status_and_funding_status_axes_move_independently
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    i1 = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    api.set_clock("2026-08-21T00:00:00Z", ADMIN)
    paid = validate_success(api.pay_installment(i1["id"], {"amount_cents": 98667},
                            make_student_headers(sc["student_id"])), 200)
    assert paid["status"] == "PAID" and paid["late_fee_cents"] == 4933 and paid["paid_cents"] == 103600
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["funding_status"] == "CURRENT" and lease["lease_status"] == "ACTIVE"
    assert lease["paid_cents"] == 103600


def test_payment_cascade_hop1_and_hop2(api):
    """PRD §3.6: "Paying sets the charge PAID, stamps paid_at, sets paid_cents to
    amount_cents plus the late fee, then cascades: the lease's paid_cents is
    recomputed and funding_status re-derived".

    Design: Difficulty/transitive_cascade/installment_payment_four_hop_escrow_cascade
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    clk = validate_success(api.set_clock("2026-08-16T00:00:00Z", ADMIN), 200)
    assert clk["installments_marked_late_count"] == 0
    i1 = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    paid = validate_success(api.pay_installment(i1["id"], {"amount_cents": 98667},
                            make_student_headers(sc["student_id"])), 200)
    assert paid["status"] == "PAID" and paid["late_fee_cents"] == 0 and paid["paid_cents"] == 98667
    assert paid["paid_at"][:10] == "2026-08-16"
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["paid_cents"] == 98667 and lease["funding_status"] == "CURRENT"
    assert lease["lease_status"] == "ACTIVE"


def test_payment_cascade_hop3_and_hop4_escrow_eligibility(api):
    """PRD §3.6: "the property's escrow_balance_cents is recomputed, and
    payout_eligible is re-derived". PRD §3.9: "payout_eligible is true exactly
    when escrow_balance_cents is at least 50000 cents."

    Design: Difficulty/transitive_cascade/installment_payment_four_hop_escrow_cascade
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    api.set_clock("2026-08-16T00:00:00Z", ADMIN)
    i1 = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    api.pay_installment(i1["id"], {"amount_cents": 98667}, make_student_headers(sc["student_id"]))
    prop = fx.get_property(api, sc["prop"]["id"])
    assert prop["escrow_balance_cents"] == 98667
    assert prop["payout_eligible"] is True
    assert prop["maintenance_reserve_cents"] == 0


def test_installment_state_error_outranks_amount_mismatch(api):
    """PRD §2.9: state admissibility (priority 8) precedes the domain business
    rules of §3. PRD §3.6: "a charge that is already PAID or VOID, or whose
    lease is in neither state, is ERR_INSTALLMENT_NOT_PAYABLE."

    Design: Difficulty/priority_pair_validation_conflict/installment_state_error_outranks_payment_amount_mismatch
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    api.set_clock("2026-08-16T00:00:00Z", ADMIN)
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    i1, i2 = rows[0], rows[1]
    sid = make_student_headers(sc["student_id"])
    api.pay_installment(i1["id"], {"amount_cents": 98667}, sid)
    # second payment on the PAID charge, carrying a wrong amount -> state error wins
    validate_error(api.pay_installment(i1["id"], {"amount_cents": 1}, sid),
                   ApiErrorId.ERR_INSTALLMENT_NOT_PAYABLE.value)
    still = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    assert still["status"] == "PAID" and still["paid_cents"] == 98667


def test_payment_amount_mismatch_fires_on_scheduled_charge(api):
    """PRD §3.6: "The owning student pays a charge by supplying amount_cents,
    which must equal the installment's amount_cents exactly; a mismatch is
    ERR_PAYMENT_AMOUNT_MISMATCH, and partial payment is not supported."

    Design: Difficulty/priority_pair_validation_conflict/installment_state_error_outranks_payment_amount_mismatch
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    api.set_clock("2026-08-16T00:00:00Z", ADMIN)
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    i1, i2 = rows[0], rows[1]
    sid = make_student_headers(sc["student_id"])
    api.pay_installment(i1["id"], {"amount_cents": 98667}, sid)
    validate_error(api.pay_installment(i2["id"], {"amount_cents": 1}, sid),
                   ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)
    i1r = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    i2r = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[1]
    assert i1r["status"] == "PAID" and i1r["paid_cents"] == 98667
    assert i2r["status"] == "SCHEDULED" and i2r["paid_cents"] == 0
    assert fx.get_property(api, sc["prop"]["id"])["escrow_balance_cents"] == 98667


def test_late_fee_grace_window_is_strict_at_the_fifth_day(api):
    """PRD §3.6: "an installment becomes LATE only when the new clock date is
    strictly greater than its due_date plus a five-day grace - a payment made
    exactly on the due date plus five days carries no fee."

    Design: Corner/calculations/late_fee_grace_window_is_strict_at_the_fifth_day
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    i1, i2 = rows[0], rows[1]
    sid = make_student_headers(sc["student_id"])
    clk1 = validate_success(api.set_clock("2026-08-20T00:00:00Z", ADMIN), 200)
    assert clk1["installments_marked_late_count"] == 0
    p1 = validate_success(api.pay_installment(i1["id"], {"amount_cents": 98667}, sid), 200)
    assert p1["status"] == "PAID" and p1["late_fee_cents"] == 0 and p1["paid_cents"] == 98667
    clk2 = validate_success(api.set_clock("2026-09-20T00:00:00Z", ADMIN), 200)
    assert clk2["installments_marked_late_count"] == 1
    p2 = validate_success(api.pay_installment(i2["id"], {"amount_cents": 98667}, sid), 200)
    assert p2["status"] == "PAID" and p2["late_fee_cents"] == 4933 and p2["paid_cents"] == 103600
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["paid_cents"] == 202267 and lease["funding_status"] == "CURRENT"
    assert fx.get_property(api, sc["prop"]["id"])["escrow_balance_cents"] == 202267


def test_late_fee_is_capped_at_the_ceiling(api):
    """PRD §3.6: "the late fee is the amount_cents times 500 basis points,
    divided by 10000 and rounded half up, then capped at 7500 cents - whichever
    is smaller."

    Design: Corner/calculations/late_fee_is_capped_at_the_ceiling
    """
    sc = fx.setup_active_lease(api, installment_count=1)
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    i1 = rows[0]
    assert i1["amount_cents"] == 986679 and i1["sequence_number"] == 1
    api.set_clock("2026-08-21T00:00:00Z", ADMIN)
    paid = validate_success(api.pay_installment(i1["id"], {"amount_cents": 986679},
                            make_student_headers(sc["student_id"])), 200)
    assert paid["late_fee_cents"] == 7500  # round_half_up(49333.95)=49334 clamped
    assert paid["paid_cents"] == 994179 and paid["status"] == "PAID"
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["funding_status"] == "SETTLED" and lease["paid_cents"] == 994179
    assert fx.get_property(api, sc["prop"]["id"])["escrow_balance_cents"] == 994179


def test_lease_termination_voids_future_charges_and_releases_bed(api):
    """PRD §3.10: "every installment still SCHEDULED or LATE whose due_date is
    after the clock date becomes VOID ... the bed slot is released and the unit
    and property rollups plus the property posture are re-evaluated".

    Design: Corner/state_machines/lease_termination_voids_future_charges_and_releases_bed
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    api.set_clock("2026-08-16T00:00:00Z", ADMIN)
    i1 = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    api.pay_installment(i1["id"], {"amount_cents": 98667}, make_student_headers(sc["student_id"]))
    term = validate_success(api.terminate_lease(sc["lease"]["id"], MGR,
                            {"reason": "Lease broken by mutual agreement"}), 200)
    assert term["lease_status"] == "TERMINATED" and term["terminated_at"] is not None
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    assert rows[0]["status"] == "PAID"
    assert all(r["status"] == "VOID" for r in rows[1:])
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["funding_status"] == "SETTLED"
    assert lease["paid_cents"] == 98667 and lease["total_contract_cents"] == 986679
    unit = fx.get_unit(api, sc["unit"]["id"])
    assert unit["leased_bed_count"] == 0 and unit["available_bed_count"] == 4
    assert unit["occupancy_status"] == "AVAILABLE"
    prop = fx.get_property(api, sc["prop"]["id"])
    assert prop["available_bed_count"] == 4 and prop["escrow_balance_cents"] == 98667


def test_lease_auto_ends_when_clock_passes_term_end(api):
    """PRD §3.10: "a lease reaches ENDED only through the clock's auto-end
    sweep, when an ACTIVE lease's term_end_date arrives; that too releases the
    bed and re-runs the rollups." PRD §2.5: "every Lease in ACTIVE whose
    term_end_date is at or before the new clock date becomes ENDED".

    Design: Corner/state_machines/lease_auto_ends_when_clock_passes_term_end_after_lateness_sweep
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    clk = validate_success(api.set_clock("2027-08-01T00:00:00Z", ADMIN), 200)
    assert clk["installments_marked_late_count"] == 10 and clk["leases_ended_count"] == 1
    assert clk["sublets_activated_count"] == 0 and clk["sublets_completed_count"] == 0
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["lease_status"] == "ENDED" and lease["funding_status"] == "DELINQUENT"
    rows = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])
    assert all(r["status"] == "LATE" for r in rows)
    unit = fx.get_unit(api, sc["unit"]["id"])
    assert unit["leased_bed_count"] == 0 and unit["occupancy_status"] == "AVAILABLE"
    prop = fx.get_property(api, sc["prop"]["id"])
    assert prop["available_bed_count"] == 4 and prop["escrow_balance_cents"] == 0
