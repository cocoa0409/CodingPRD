"""Personally procured move reimbursement bases and the storage-in-transit price build-up."""

import pytest

from test_helpers import (
    COUNSELOR,
    api_client,
    authorize_sit,
    get_success_data,
    pickup_shipment,
    read_shipment,
    release_sit,
    request_sit,
    setup_packed_shipment,
    setup_ppm_submission,
    submit_ppm,
    trip_ticket,
)

TICKETS = [trip_ticket(1, 9200, 5400), trip_ticket(2, 8600, 5200)]


def _approve_packet(ppm_id, note):
    return get_success_data(
        api_client.approve_ppm_submission(ppm_id, {"approval_note": note}, COUNSELOR)
    )


def _two_ppm_packets():
    """One delivered self-move carrying a light-receipt packet and a heavy-receipt one."""
    scenario = setup_ppm_submission(
        trip_tickets=TICKETS,
        ppm_overrides={"documented_expenses_usd": 1200.00, "advance_paid_usd": 2000.00},
    )
    low = scenario["ppm"]
    high = submit_ppm(
        scenario,
        TICKETS,
        documented_expenses_usd=6300.00,
        advance_paid_usd=2000.00,
    )
    approved_low = _approve_packet(low["id"], "Low receipts packet")
    approved_high = _approve_packet(high["id"], "High receipts packet")
    return scenario, approved_low, approved_high


def _shipment_released_from_destination_storage():
    """A 5,286 pound picked-up shipment stored twenty days against twenty-five authorized."""
    scenario = setup_packed_shipment(pack_date="2026-08-15T00:00:00Z")
    scenario["shipment"] = pickup_shipment(
        scenario, actual_pickup_date="2026-08-17T00:00:00Z"
    )
    requested = request_sit(
        scenario,
        "2026-09-16T00:00:00Z",
        requested_days=25,
        sit_type="DESTINATION",
    )
    authorize_sit(requested["id"], 25)
    released = release_sit(scenario, requested["id"], "2026-10-06T00:00:00Z")
    return scenario, released


class TestPpmIncentiveVersusActualExpense:
    """The same tickets and mileage pay differently once the receipts change."""

    def test_the_constructed_cost_prices_the_weight_the_government_would_have_moved(self):
        """7,200 pounds over 1,200 miles constructs 6,404.40 and a 6,084.18 incentive.

        "`gcc_usd`, the government constructed cost, is `allowable_weight_lbs` expressed
        in hundredweight, multiplied by a rate made of a base of 42.75 US dollars per
        hundredweight plus 3.85 US dollars per hundredweight for each hundred miles of
        the orders' `distance_miles`, with the product rounded half up to cents."

        Design: Difficulty/dual_variant_calc/ppm_reimbursement_incentive_versus_actual_expense_basis
        """
        _, low, high = _two_ppm_packets()

        assert low["moved_weight_lbs"] == 7200
        assert low["allowable_weight_lbs"] == 7200
        assert low["gcc_usd"] == pytest.approx(6404.40, abs=0.01)
        assert low["incentive_usd"] == pytest.approx(6084.18, abs=0.01)
        assert high["gcc_usd"] == pytest.approx(6404.40, abs=0.01)
        assert high["incentive_usd"] == pytest.approx(6084.18, abs=0.01)

    def test_light_receipts_land_on_the_incentive_basis(self):
        """1,200.00 of receipts cannot beat the 6,084.18 incentive, so the incentive applies.

        "`applied_basis` becomes `INCENTIVE_BASIS` when the incentive figure is greater
        than or equal to the expense figure, and `ACTUAL_EXPENSE_BASIS` when the expense
        figure is strictly greater — a tie goes to the incentive."

        Design: Difficulty/dual_variant_calc/ppm_reimbursement_incentive_versus_actual_expense_basis
        """
        _, low, _ = _two_ppm_packets()

        assert low["applied_basis"] == "INCENTIVE_BASIS"
        assert low["reimbursement_usd"] == pytest.approx(6084.18, abs=0.01)

    def test_heavy_receipts_land_on_the_actual_expense_basis(self):
        """6,300.00 of receipts beats the incentive and is reimbursed in full.

        "The competing expense figure is the lesser of `documented_expenses_usd` and
        `gcc_usd` — receipts are reimbursed up to, but never beyond, the full constructed
        cost."

        Design: Difficulty/dual_variant_calc/ppm_reimbursement_incentive_versus_actual_expense_basis
        """
        _, _, high = _two_ppm_packets()

        assert high["applied_basis"] == "ACTUAL_EXPENSE_BASIS"
        assert high["reimbursement_usd"] == pytest.approx(6300.00, abs=0.01)

    def test_the_advance_and_the_tax_treatment_follow_the_applied_basis(self):
        """Both packets net the advance off; only the incentive packet is taxed.

        "`taxable_amount_usd` is, under `INCENTIVE_BASIS`, `reimbursement_usd` less
        `documented_expenses_usd`, rounded half up to cents and floored at zero, because
        incentive payments beyond documented cost are taxable income; under
        `ACTUAL_EXPENSE_BASIS` it is 0.00."

        Design: Difficulty/dual_variant_calc/ppm_reimbursement_incentive_versus_actual_expense_basis
        """
        _, low, high = _two_ppm_packets()

        assert low["net_payable_usd"] == pytest.approx(4084.18, abs=0.01)
        assert low["debt_owed_usd"] == pytest.approx(0.00, abs=0.01)
        assert low["taxable_amount_usd"] == pytest.approx(4884.18, abs=0.01)
        assert high["net_payable_usd"] == pytest.approx(4300.00, abs=0.01)
        assert high["debt_owed_usd"] == pytest.approx(0.00, abs=0.01)
        assert high["taxable_amount_usd"] == pytest.approx(0.00, abs=0.01)

    def test_the_two_bases_differ_by_two_hundred_fifteen_dollars_and_change(self):
        """Identical tickets pay 215.82 more on receipts than on the incentive.

        "`reimbursement_usd` is the incentive figure under `INCENTIVE_BASIS` and the
        expense figure under `ACTUAL_EXPENSE_BASIS`, so the same packet yields a
        materially different payable depending on which variant applies."

        Design: Difficulty/dual_variant_calc/ppm_reimbursement_incentive_versus_actual_expense_basis
        """
        _, low, high = _two_ppm_packets()

        difference = high["reimbursement_usd"] - low["reimbursement_usd"]
        assert difference == pytest.approx(215.82, abs=0.01)


class TestStorageFuelSurchargeTier:
    """The surcharge tier reads the pre-surcharge base, never the grand total."""

    def test_release_counts_whole_storage_days_against_the_authorization(self):
        """Twenty days used inside twenty-five authorized leaves no excess day.

        "First, `days_used` is the count of whole days from `entry_date` to
        `release_date`, discarding any partial day, but never fewer than one day — a
        same-day stay still bills a day."

        Design: Difficulty/combinatorial_formula/sit_fuel_surcharge_tier_keyed_on_pre_surcharge_base_cost
        """
        _, released = _shipment_released_from_destination_storage()

        assert released["days_used"] == 20
        assert released["excess_days"] == 0
        assert released["total_authorized_days"] == 25

    def test_the_base_cost_sums_handling_and_first_tier_storage(self):
        """52.86 hundredweight bills 3,615.62 of handling plus 1,110.06 of storage.

        "**Step one** computes three charges, each rounded half up to cents: a handling
        charge of 68.40 US dollars per hundredweight; a first-tier storage charge of 1.05
        US dollars per hundredweight per day for the first-tier days; and an extended
        storage charge of 1.62 US dollars per hundredweight per day for the extra days."

        Design: Difficulty/combinatorial_formula/sit_fuel_surcharge_tier_keyed_on_pre_surcharge_base_cost
        """
        scenario, released = _shipment_released_from_destination_storage()

        assert scenario["shipment"]["billable_weight_lbs"] == 5286
        assert released["sit_base_cost_usd"] == pytest.approx(4725.68, abs=0.01)

    def test_the_surcharge_rate_is_chosen_from_the_base_and_not_from_the_total(self):
        """A 4,725.68 base sits in the middle tier, so the stay totals 5,018.67.

        "**Step three** selects `fuel_surcharge_pct` from `sit_base_cost_usd` — and from
        the base figure only, never from a figure that already contains the surcharge,
        since that definition would be circular: the rate is 0.045 when the base is below
        1,000.00 US dollars, 0.062 when the base is below 5,000.00, and 0.071 when the
        base is 5,000.00 or more — and sets `fuel_surcharge_usd` to the base multiplied by
        that rate, rounded half up to cents."

        Design: Difficulty/combinatorial_formula/sit_fuel_surcharge_tier_keyed_on_pre_surcharge_base_cost
        """
        _, released = _shipment_released_from_destination_storage()

        assert released["fuel_surcharge_pct"] == pytest.approx(0.062, abs=0.0001)
        assert released["fuel_surcharge_usd"] == pytest.approx(292.99, abs=0.01)
        assert released["sit_total_cost_usd"] == pytest.approx(5018.67, abs=0.01)
        assert abs(released["sit_total_cost_usd"] - 5061.19) > 0.01

    def test_a_stay_inside_the_authorization_costs_the_member_nothing(self):
        """No excess day means no member liability, and the goods leave storage.

        "Finally `member_liability_usd` is 0.00 when `excess_days` is zero, and otherwise
        the share of `sit_total_cost_usd` attributable to the excess days — the total
        multiplied by `excess_days` and divided by `days_used`, rounded half up to cents."

        Design: Difficulty/combinatorial_formula/sit_fuel_surcharge_tier_keyed_on_pre_surcharge_base_cost
        """
        scenario, released = _shipment_released_from_destination_storage()

        assert released["member_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert released["status"] == "RELEASED"
        assert read_shipment(scenario["shipment"]["id"])["movement_status"] == "PICKED_UP"
