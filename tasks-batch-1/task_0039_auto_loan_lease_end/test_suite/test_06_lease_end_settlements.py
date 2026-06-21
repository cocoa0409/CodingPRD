"""Lease-end settlements: RETURN vs PURCHASE total_due divergence, per-year-rounded
mileage overage, the RENEW fork that mints a new lease, and election validation.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_matured_lease, elect_lease_end,
    create_settlement_payload,
    TEST_USERS, make_borrower_headers,
    assert_settlement,
)

FM = TEST_USERS["finance_manager_headers"]


def test_return_total_due_is_disposition_plus_mileage(api):
    """PRD §3.6: "The settlement's `total_due_cents` is the disposition fee plus the mileage
    overage."

    Design: Difficulty/dual_variant_calc/lease_end_return_vs_purchase_diverge
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RETURN", 40693, matured["version"],
                                  per_year_excess_miles=[1501, 1701, 1491]), borrower), 201)
    assert_settlement(settlement)
    assert settlement["total_due_cents"] == 145094


def test_purchase_total_due_is_residual_plus_purchase_fee(api):
    """PRD §3.6: "On a purchase, the settlement's `purchase_amount_cents` is the vehicle's
    `residual_value_cents` plus the lease's `purchase_option_fee_cents`, and the settlement's
    `total_due_cents` equals that same purchase amount — no disposition fee and no mileage overage
    are charged on a purchase, so `mileage_overage_cents` and `disposition_charge_cents` are 0 and
    `renewed_lease_id` is null."

    Design: Difficulty/dual_variant_calc/lease_end_return_vs_purchase_diverge
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "PURCHASE", 38000, matured["version"]),
        borrower), 201)
    assert settlement["total_due_cents"] == 1880000


def test_mileage_overage_rounded_per_year_then_summed(api):
    """PRD §3.6: "for each lease-year, multiply that year's excess-mile count from
    `per_year_excess_miles` by the lease's `per_mile_overage_rate_cents` and round that year's
    charge half-up to whole cents, then sum the rounded yearly charges."

    Design: Difficulty/combinatorial_formula/lease_mileage_overage_round_per_year_then_sum
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RETURN", 40693, matured["version"],
                                  per_year_excess_miles=[1501, 1701, 1491]), borrower), 201)
    # round-per-year-then-sum = 105594, vs sum-then-round = 105593.
    assert settlement["mileage_overage_cents"] == 105594


def test_mileage_overage_disposition_charge_set(api):
    """PRD §3.6: "The settlement's `disposition_charge_cents` is set to the lease's
    `disposition_fee_cents`."

    Design: Difficulty/combinatorial_formula/lease_mileage_overage_round_per_year_then_sum
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RETURN", 40693, matured["version"],
                                  per_year_excess_miles=[1501, 1701, 1491]), borrower), 201)
    assert settlement["disposition_charge_cents"] == 39500


def test_renew_election_mints_new_lease_and_settles(api):
    """PRD §3.6: "As the cascade, the system mints a new `Lease` in `ACTIVE` status on the same
    vehicle, with its capitalized cost set to the vehicle's `residual_value_cents` and its term
    set to `renew_term_months`; the new lease's `id` is recorded on the settlement as
    `renewed_lease_id`. The maturing lease advances `RENEWED` then to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/lease_maturing_branching_fork_join
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RENEW", 35000, matured["version"],
                                  renew_term_months=24), borrower), 201)
    assert settlement["renewed_lease_id"] is not None
    lease_after = validate_success(api.get_lease(matured["id"], borrower), 200)
    assert lease_after["status"] == "SETTLED"


def test_renew_settlement_total_due_zero(api):
    """PRD §3.6: "On a renewal, the settlement's `total_due_cents` is 0 — the outstanding
    obligation rolls into a fresh contract — and its `mileage_overage_cents`,
    `disposition_charge_cents`, and `purchase_amount_cents` are all 0."

    Design: Difficulty/non_linear_state_machine/lease_maturing_branching_fork_join
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RENEW", 35000, matured["version"],
                                  renew_term_months=24), borrower), 201)
    assert settlement["total_due_cents"] == 0


def test_renew_conserves_obligation_to_new_lease_vehicle_stays_financed(api):
    """PRD §3.6: "As the cascade, the system mints a new `Lease` in `ACTIVE` status on the same
    vehicle, with its capitalized cost set to the vehicle's `residual_value_cents` and its term
    set to `renew_term_months`; the new lease's `id` is recorded on the settlement as
    `renewed_lease_id`. The maturing lease advances `RENEWED` then to `SETTLED`."

    Design: Difficulty/compensating_invariant/lease_renew_obligation_conserved_to_new_lease
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RENEW", 35000, matured["version"],
                                  renew_term_months=24), borrower), 201)
    assert settlement["total_due_cents"] == 0
    assert settlement["renewed_lease_id"] is not None
    assert settlement["renewed_lease_id"] != matured["id"]
    # Vehicle stays FINANCED: the open-obligation count is conserved at 1 (old lease settled,
    # new lease active on the same vehicle).
    vehicle_after = validate_success(api.get_vehicle(vehicle["id"], FM), 200)
    assert vehicle_after["status"] == "FINANCED"


def test_renew_minted_lease_is_active_on_same_vehicle(api):
    """PRD §3.6: "As the cascade, the system mints a new `Lease` in `ACTIVE` status on the same
    vehicle, with its capitalized cost set to the vehicle's `residual_value_cents` and its term
    set to `renew_term_months`; the new lease's `id` is recorded on the settlement as
    `renewed_lease_id`."

    Design: Difficulty/compensating_invariant/lease_renew_obligation_conserved_to_new_lease
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RENEW", 35000, matured["version"],
                                  renew_term_months=24), borrower), 201)
    new_lease = validate_success(api.get_lease(settlement["renewed_lease_id"], borrower), 200)
    assert new_lease["status"] == "ACTIVE"
    assert new_lease["vehicle_id"] == vehicle["id"]


def test_return_at_allowance_zero_overage(api):
    """PRD §3.6: "for each lease-year, multiply that year's excess-mile count from
    `per_year_excess_miles` by the lease's `per_mile_overage_rate_cents` and round that year's
    charge half-up to whole cents, then sum the rounded yearly charges."

    Design: Difficulty/boundary_precision_check/mileage_exact_allowance_zero_overage
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RETURN", 36000, matured["version"],
                                  per_year_excess_miles=[0, 0, 0]), borrower), 201)
    assert settlement["mileage_overage_cents"] == 0


def test_return_at_allowance_total_due_is_disposition_only(api):
    """PRD §3.6: "The settlement's `total_due_cents` is the disposition fee plus the mileage
    overage."

    Design: Difficulty/boundary_precision_check/mileage_exact_allowance_zero_overage
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    settlement = validate_success(api.create_settlement(
        create_settlement_payload(matured["id"], "RETURN", 36000, matured["version"],
                                  per_year_excess_miles=[0, 0, 0]), borrower), 201)
    assert settlement["total_due_cents"] == 39500


def test_election_on_active_lease_returns_not_electable(api):
    """PRD §3.6: "An election may be made only while the lease is `MATURING`; attempting it on a
    lease in any other state is rejected with `ERR_LEASE_NOT_ELECTABLE`."

    Design: Difficulty/cross_entity_state_dependency/lease_election_requires_lease_maturing
    """
    # ACTIVE (not matured) lease: setup_matured_lease matures, so build directly.
    from test_helpers import setup_lease
    customer, vehicle, lease = setup_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    res = api.create_settlement(
        create_settlement_payload(lease["id"], "PURCHASE", 30000, lease["version"]), borrower)
    validate_error(res, "ERR_LEASE_NOT_ELECTABLE")


def test_election_requires_maturing_state_distinct_from_loan_vehicle_pair(api):
    """PRD §3.6: "An election may be made only while the lease is `MATURING`; attempting it on a
    lease in any other state is rejected with `ERR_LEASE_NOT_ELECTABLE`."

    Design: Difficulty/cross_entity_state_dependency/lease_election_requires_lease_maturing
    """
    from test_helpers import setup_lease
    customer, vehicle, lease = setup_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    assert lease["status"] == "ACTIVE"
    res = api.create_settlement(
        create_settlement_payload(lease["id"], "RETURN", 30000, lease["version"],
                                  per_year_excess_miles=[0, 0, 0]), borrower)
    validate_error(res, "ERR_LEASE_NOT_ELECTABLE")


def test_return_wrong_length_mileage_schedule_returns_422(api):
    """PRD §3.6: "A `RETURN` election requires `per_year_excess_miles` to be present and of length
    exactly `term_months` divided by 12; a missing or wrong-length list is rejected with
    `ERR_MILEAGE_SCHEDULE_INVALID`."

    Design: Corner/validations/return_wrong_length_mileage_schedule_returns_422
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)  # term 36 -> expects 3
    borrower = make_borrower_headers(customer["id"])
    res = api.create_settlement(
        create_settlement_payload(matured["id"], "RETURN", 40000, matured["version"],
                                  per_year_excess_miles=[100, 200]), borrower)
    validate_error(res, "ERR_MILEAGE_SCHEDULE_INVALID")


def test_renew_without_term_returns_renew_term_invalid(api):
    """PRD §3.6: "A `RENEW` election requires `renew_term_months` to be present and greater than
    0; an absent or non-positive renewal term is rejected with `ERR_RENEW_TERM_INVALID`."

    Design: Corner/validations/renew_without_term_returns_renew_term_invalid
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    res = api.create_settlement(
        create_settlement_payload(matured["id"], "RENEW", 35000, matured["version"]), borrower)
    validate_error(res, "ERR_RENEW_TERM_INVALID")
