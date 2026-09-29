"""Corner behaviour of the two aggregate computations: the airline's dual exposure bases and the
reconciliation variance with its floored denominators and per-tank signed adjustments."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures as fx,
)


def _entry(tank_id, measured_volume_liters):
    return {"storage_tank_id": tank_id, "measured_volume_liters": measured_volume_liters,
            "temperature_c": 15.0}


class TestAirlineCreditExposureCorners:
    def test_the_reservation_term_is_fuel_plus_handling_and_nothing_else(self, api):
        """PRD §3.5: "The reservation term for a single order is computed once, at authorization time,
        and is the sum of two components: the requested volume multiplied by the account's
        `base_price_cents_per_liter` plus the applicable tier differential, rounded half up to whole
        cents; plus an into-plane handling component that is the larger of 2,500 cents and the requested
        volume multiplied by 0.45 cents per liter rounded half up to whole cents."
        PRD §3.5: "The tier differential is selected exactly as it is for a real uplift line, described
        in §3.6, except that the cumulative volume it is keyed on is the account's month-to-date net
        liters *plus* this order's `requested_uplift_liters`."
        PRD §3.5: "The **accrual basis** adds two further terms to that figure: the sum of
        `billed_line_cents` over the account's uplift tickets whose `status` is `POSTED` (tickets already
        `BILLED` sit inside an issued invoice and would double-count; `VOIDED` tickets are excluded), plus
        the sum of `reserved_amount_cents` over the account's orders whose `status` is `AUTHORIZED`,
        `ASSIGNED` or `FUELING`."

        Design: Corner/calculations/reservation_term_excludes_flowage_and_taxes
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"base_price_cents_per_liter": 62.00,
                                                      "credit_limit_cents": 100_000_000})

        order = fx.read_order(env["order"]["id"])
        assert order["reserved_amount_cents"] == 1313000, \
            "20,000 at 65.20 is 1,304,000 plus a 9,000 handling component"

        account = fx.read_account(env["account"]["id"])
        assert account["accrual_exposure_cents"] == 1313000
        assert account["invoiced_exposure_cents"] == 0
        assert account["accrual_exposure_cents"] < 1433393, \
            "flowage, excise and sales tax are deliberately absent from the reservation"

    def test_completion_swaps_the_reservation_for_the_ticket_without_double_counting(self, api):
        """PRD §3.6: "Completion drives the authorization `ISSUED → REDEEMED`; releases the reservation by
        subtracting `requested_uplift_liters` from the tank's `reserved_volume_liters` and recomputing
        `available_volume_liters`, the posted tickets having already debited book volume; ends the order's
        pit occupancy as the order leaves the assigned-or-fuelling set; leaves a truck asset `IN_SERVICE`
        unless its element life has reached 100.0, in which case the asset moves
        `IN_SERVICE → FILTER_DUE`; and recomputes the account's accrual exposure, where the reservation
        term drops out and the uncollected-ticket term enters."
        PRD §3.5: "The **accrual basis** adds two further terms to that figure: the sum of
        `billed_line_cents` over the account's uplift tickets whose `status` is `POSTED` (tickets already
        `BILLED` sit inside an issued invoice and would double-count; `VOIDED` tickets are excluded), plus
        the sum of `reserved_amount_cents` over the account's orders whose `status` is `AUTHORIZED`,
        `ASSIGNED` or `FUELING`."

        Design: Corner/calculations/a_ticket_replaces_its_order_reservation_rather_than_adding_to_it
        """
        env = fx.setup_completed_order(
            meter_end_liters=20_000.0, requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000})
        ticket = fx.read_uplift(env["uplift"]["id"])
        assert ticket["status"] == "POSTED"
        assert ticket["billed_line_cents"] == 1433393

        account = fx.read_account(env["account"]["id"])
        assert account["accrual_exposure_cents"] == 1433393, \
            "the ticket alone, not the ticket plus the 1,313,000 reservation"
        assert account["invoiced_exposure_cents"] == 0, "nothing has been invoiced yet"
        assert fx.read_order(env["order"]["id"])["reserved_amount_cents"] == 1313000, \
            "the order keeps its own figure; it simply no longer counts toward exposure"

    def test_settling_the_invoice_hands_the_whole_credit_limit_back(self, api):
        """PRD §3.9: "Once the cumulative paid amount reaches the total the invoice moves
        `ISSUED → PAID`, both exposure figures fall by the invoice total, and the invoice's and account's
        `version` each rise by one."
        PRD §3.5: "The **invoiced basis** counts only what has actually been billed:
        `invoiced_exposure_cents` is the sum, over the account's invoices whose `status` is `ISSUED` or
        `DISPUTED`, of that invoice's `total_cents` less its `amount_paid_cents`."
        PRD §3.6: "The airline account's `status` must be `ACTIVE` and the accrual-basis exposure,
        including this order's freshly computed `reserved_amount_cents`, must not exceed the account's
        `credit_limit_cents`; failure either way is `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402), which is also
        how a `CREDIT_HOLD` account is refused."

        Design: Corner/calculations/paid_invoice_leaves_both_bases
        """
        env = fx.setup_issued_invoice(
            meter_end_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 1_500_000, "tax_exempt": False})
        invoice_id, account_id = env["invoice"]["id"], env["account"]["id"]
        issued = fx.read_account(account_id)
        assert issued["invoiced_exposure_cents"] == 1439127

        validate_success(api.create_payment(invoice_id, {"amount_cents": 1439127},
                                            fx.BILLING), 201)
        settled = fx.read_account(account_id)
        assert settled["invoiced_exposure_cents"] == 0
        assert settled["accrual_exposure_cents"] == 0

        flight = fx.register_flight(account_id, stand_code="C11",
                                    scheduled_departure_utc="2026-08-10T10:00:00Z")
        auth = fx.issue_authorization(account_id, flight["id"],
                                      max_authorized_liters=20_000.0)
        order = fx.create_order(flight["id"], auth["id"], env["tank"]["id"],
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=20_000.0,
                                window_start_utc="2026-08-10T08:00:00Z",
                                window_end_utc="2026-08-10T09:00:00Z")
        authorized = fx.authorize_order(order["id"])

        assert authorized["status"] == "AUTHORIZED", \
            "1,313,000 fits under the 1,500,000 limit only because the invoice was settled"
        assert fx.read_account(account_id)["accrual_exposure_cents"] == 1313000


class TestReconciliationVarianceCorners:
    def test_a_dead_quiet_period_divides_by_one_litre_rather_than_by_zero(self, api):
        """PRD §3.9: "Two variance percentages are then reported side by side, each the absolute variance
        divided by its denominator and multiplied by one hundred, rounded half up to four decimals, and in
        each case the denominator is taken as the larger of the computed denominator and 1.0 so that a
        dead-quiet period cannot divide by zero."
        PRD §3.9: "The run auto-transitions `MEASURED → VARIANCE_HOLD` on the same request that computed
        the variance when the governing percentage is **strictly greater than** 0.50 percent; a run
        sitting at exactly 0.5000 percent does not hold and posts clean."
        PRD §3.9: "A derived opening stock is also computed as the sum of the measured tanks' book
        volumes, less the period's released receipt volume, plus the period's uplift volume, rounded half
        up to two decimals."

        Design: Corner/calculations/quiet_period_denominator_is_floored_at_one_liter
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        run = fx.open_reconciliation_run(env["farm"]["id"],
                                        period_start_utc="2026-08-10T00:00:00Z",
                                        period_end_utc="2026-08-10T07:00:00Z")
        fx.set_clock("2026-08-10T07:00:00Z")

        measured = fx.measure_reconciliation_run(
            run["id"], [_entry(env["tank"]["id"], 999_900.0)])

        assert measured["receipts_net_liters"] == pytest.approx(0.00, abs=0.005)
        assert measured["uplifts_net_liters"] == pytest.approx(0.00, abs=0.005)
        assert measured["throughput_liters"] == pytest.approx(0.00, abs=0.005)
        assert measured["variance_liters"] == pytest.approx(-100.00, abs=0.005)
        assert measured["variance_pct_throughput_basis"] == pytest.approx(10000.0000,
                                                                         abs=0.00005), \
            "the denominator is floored at 1.0 litre, so the figure is enormous rather than undefined"
        assert measured["variance_pct_opening_stock_basis"] == pytest.approx(0.0100,
                                                                            abs=0.00005)
        assert measured["status"] == "VARIANCE_HOLD"

    def test_a_gain_and_a_loss_that_net_to_nothing_still_move_both_ledgers(self, api):
        """PRD §3.9: "The per-tank variance is the corrected measured volume less the book volume, rounded
        half up to two decimals — a positive number is a gain, a negative number a loss — and the run's
        `variance_liters` is the sum of those per-tank variances, rounded half up to two decimals."
        PRD §3.9: "Posting writes the signed per-tank variance into the ledger as that tank's
        `adjustment_liters`, with the effect that each measured tank's `book_volume_liters` afterwards
        equals its corrected measured volume exactly."
        PRD §3.9: "The variance computation processes the measured tanks in `created_at` ascending
        order."

        Design: Corner/calculations/gain_and_loss_cancel_across_tanks
        """
        env = fx.setup_fuel_farm()
        farm_id = env["farm"]["id"]
        gaining = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                   safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                   opening_volume_liters=100_000.0)
        losing = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                  safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                  opening_volume_liters=100_000.0)
        run = fx.open_reconciliation_run(farm_id, period_start_utc="2026-08-10T00:00:00Z",
                                        period_end_utc="2026-08-10T07:00:00Z")
        fx.set_clock("2026-08-10T07:00:00Z")

        measured = fx.measure_reconciliation_run(
            run["id"], [_entry(gaining["id"], 100_300.0), _entry(losing["id"], 99_700.0)])
        assert measured["variance_liters"] == pytest.approx(0.00, abs=0.005)
        assert measured["status"] == "MEASURED", "a netted variance is no variance at all"

        posted = validate_success(api.post_reconciliation_run(run["id"], fx.ADMIN))
        assert posted["status"] == "POSTED"

        assert fx.read_tank(gaining["id"])["book_volume_liters"] == \
            pytest.approx(100300.00, abs=0.005), "the gain is written even though the run netted flat"
        assert fx.read_tank(losing["id"])["book_volume_liters"] == \
            pytest.approx(99700.00, abs=0.005), "and so is the matching loss"

    def test_a_retired_tank_leaves_both_the_variance_and_the_denominator(self, api):
        """PRD §3.9: "Tanks that are `OUT_OF_SERVICE` are excluded and contribute no variance. A set that
        is short, long, or contains a stranger is rejected with `ERR_MEASUREMENT_SET_INCOMPLETE`."
        PRD §3.9: "A derived opening stock is also computed as the sum of the measured tanks' book
        volumes, less the period's released receipt volume, plus the period's uplift volume, rounded half
        up to two decimals."
        PRD §3.4: "Retiring a tank, `ISOLATED → OUT_OF_SERVICE`, is a `ConsortiumAdmin` action permitted
        only once the tank has been drained down to its unpumpable heel: the tank's `book_volume_liters`
        must not exceed the farm's `unpumpable_bottom_liters`."

        Design: Corner/calculations/out_of_service_tank_is_excluded_from_the_measurement_set
        """
        env = fx.setup_fuel_farm()
        farm_id = env["farm"]["id"]
        working = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                   safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                   opening_volume_liters=100_000.0)
        heel = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                opening_volume_liters=500.0)
        run = fx.open_reconciliation_run(farm_id, period_start_utc="2026-08-10T00:00:00Z",
                                        period_end_utc="2026-08-10T07:00:00Z")

        fx.isolate_tank(heel["id"], "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
        validate_success(api.change_tank_service_status(
            heel["id"], {"to_status": "OUT_OF_SERVICE"}, fx.ADMIN))
        fx.set_clock("2026-08-10T07:00:00Z")

        validate_error(api.measure_reconciliation_run(
            run["id"], {"tank_measurements": [_entry(working["id"], 99_900.0),
                                              _entry(heel["id"], 500.0)]}, fx.OPERATOR),
            ApiErrorId.ERR_MEASUREMENT_SET_INCOMPLETE, 422)

        measured = fx.measure_reconciliation_run(run["id"],
                                                 [_entry(working["id"], 99_900.0)])

        assert measured["variance_liters"] == pytest.approx(-100.00, abs=0.005), \
            "the retired tank contributes no variance of its own"
        assert measured["variance_pct_opening_stock_basis"] == pytest.approx(0.1000,
                                                                            abs=0.00005), \
            "the derived opening stock is 100,000.00, with the retired heel frozen out of it"
        assert fx.read_tank(heel["id"])["book_volume_liters"] == pytest.approx(500.00,
                                                                              abs=0.005)
