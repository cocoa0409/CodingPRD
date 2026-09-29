"""Round trips that must return a conserved quantity to exactly its starting value: fuel across
uplift-then-abort, permit allowance across a rejected parcel, and airline exposure across
invoice issue-then-void."""
import pytest

from test_helpers import validate_success, fixtures as fx


class TestFuelVolumeConservationAcrossAbort:
    @staticmethod
    def _fuelling_order_with_one_ticket():
        return fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, temperature_c=15.0,
            requested_uplift_liters=20_000.0, max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": False},
            permit_overrides={"max_daily_throughput_liters": 400000.0})

    def test_posting_moves_the_fuel_and_aborting_credits_it_back_exactly_once(self, api):
        """PRD §2.11: "**Fuel volume conservation**: when a truck-delivered order is aborted, the
        voided tickets leave the posted set and the truck's `onboard_volume_liters` recomputes to
        zero, so the sum of the source tank's `book_volume_liters` and the asset's
        `onboard_volume_liters` returns to exactly the value it held before fuelling started."
        PRD §3.6: "**Abort**, `FUELING → ABORTED`, carries an `abort_reason` of `SPILL`,
        `QUALITY_HOLD`, `AIRCRAFT_RELEASE` or `EQUIPMENT_FAILURE`, and compensates everything: every
        `POSTED` ticket on the order becomes `VOIDED` with `voided_reason` `ORDER_ABORTED` and its
        `net_liters` are credited back to the tank's `book_volume_liters`; the requested volume is
        subtracted from the tank's `reserved_volume_liters`; for truck delivery the asset's
        `onboard_volume_liters` recomputes to 0.0 as the voided tickets leave the posted set, so the
        sum of tank book volume and on-board volume returns to exactly its pre-fuelling value; the
        authorization is driven `ISSUED → VOIDED` with `voided_reason` `ORDER_CANCELLED`; pit
        occupancy ends; and the account's accrual exposure returns to its pre-authorization value."
        PRD §3.6: "Posting an uplift ticket is the moment product leaves the ledger."

        Design: Difficulty/compensating_invariant/fuel_volume_conservation_across_uplift_then_abort
        """
        env = self._fuelling_order_with_one_ticket()
        tank_id, truck_id = env["tank"]["id"], env["truck"]["id"]

        before_tank = fx.read_tank(tank_id)
        before_asset = fx.read_asset(truck_id)
        assert before_tank["book_volume_liters"] == pytest.approx(980000.00, abs=0.005)
        assert before_asset["onboard_volume_liters"] == pytest.approx(20000.00, abs=0.005)
        assert (before_tank["book_volume_liters"]
                + before_asset["onboard_volume_liters"]) == pytest.approx(1000000.00, abs=0.005)
        assert fx.read_account(env["account"]["id"])["accrual_exposure_cents"] == 2746393

        aborted = fx.abort_order(env["order"]["id"], abort_reason="AIRCRAFT_RELEASE")
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "AIRCRAFT_RELEASE"

        uplift = fx.read_uplift(env["uplift"]["id"])
        assert uplift["status"] == "VOIDED"
        assert uplift["voided_reason"] == "ORDER_ABORTED"

        tank = fx.read_tank(tank_id)
        asset = fx.read_asset(truck_id)
        assert tank["book_volume_liters"] == pytest.approx(1000000.00, abs=0.005), \
            "crediting the ticket twice would leave 1020000.00 liters"
        assert asset["onboard_volume_liters"] == pytest.approx(0.0, abs=0.005)
        assert (tank["book_volume_liters"]
                + asset["onboard_volume_liters"]) == pytest.approx(1000000.00, abs=0.005)

    def test_the_abort_also_unwinds_the_reservation_the_authorization_and_the_exposure(self, api):
        """PRD §2.11: "**Permit throughput conservation**: a rejected parcel never touched the ledger,
        so rejecting a quarantined receipt leaves the farm's `active_permit_throughput_used_liters`
        exactly as it was — only receipts that reach `RELEASED` and uplift tickets that are `POSTED`
        or `BILLED` count toward the permit day."
        PRD §3.4: "The `available_volume_liters` is the book volume less the reserved volume less the
        farm's `unpumpable_bottom_liters`, rounded half up to two decimals and then floored at 0.0 so
        it can never go negative."
        PRD §3.5: "The **accrual basis** adds two further terms to that figure: the sum of
        `billed_line_cents` over the account's uplift tickets whose `status` is `POSTED` (tickets
        already `BILLED` sit inside an issued invoice and would double-count; `VOIDED` tickets are
        excluded), plus the sum of `reserved_amount_cents` over the account's orders whose `status` is
        `AUTHORIZED`, `ASSIGNED` or `FUELING`."

        Design: Difficulty/compensating_invariant/fuel_volume_conservation_across_uplift_then_abort
        """
        env = self._fuelling_order_with_one_ticket()
        fx.abort_order(env["order"]["id"], abort_reason="AIRCRAFT_RELEASE")

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["reserved_volume_liters"] == pytest.approx(0.00, abs=0.005)
        assert tank["available_volume_liters"] == pytest.approx(999500.00, abs=0.005)

        auth = fx.read_authorization(env["auth"]["id"])
        assert auth["status"] == "VOIDED"
        assert auth["voided_reason"] == "ORDER_CANCELLED"

        account = fx.read_account(env["account"]["id"])
        assert account["accrual_exposure_cents"] == 0
        assert account["invoiced_exposure_cents"] == 0

        farm = fx.read_farm(env["farm"]["id"])
        assert farm["active_permit_throughput_used_liters"] == pytest.approx(0.00, abs=0.005), \
            "a voided ticket leaves the permit-day counter clean"


class TestPermitAndLedgerConservationOnReject:
    @staticmethod
    def _quarantined_parcel():
        env = fx.setup_farm_with_released_tank(
            opening_volume_liters=1_000_000.0,
            permit_overrides={"max_daily_throughput_liters": 400000.0,
                              "max_reportable_spill_liters": 20.0})
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                          turnaround_buffer_minutes=15, differential_pressure_kpa=10.0)
        receipt, sample = fx.make_tested_receipt(
            env["tank"]["id"],
            metrics={"water_reaction_rating": 3, "particulate_mg_per_l": 2.5,
                     "conductivity_ps_per_m": 40.0, "flash_point_c": 41.0},
            delivery_mode="TRUCK", supplier_name="Refinery One",
            meter_ticket_gross_liters=30120.0, tank_opening_gauge_liters=100.0,
            tank_closing_gauge_liters=30100.0, temperature_c=25.0,
            certificate_density_kg_per_m3=795.0, measured_water_liters=200.0)
        env["receipt"] = fx.sign_verdict(receipt["id"], "QUARANTINE", fx.INSPECTOR_B)
        env["sample"] = sample
        return env

    def test_the_quarantine_never_charged_the_permit_day_or_the_ledger(self, api):
        """PRD §3.3: "The `UNDER_TEST → QUARANTINED` branch is the sibling with a wholly disjoint
        effect set, and it is the deeper of the two: it is the depth-three quality cascade."
        PRD §3.2: "The names of the failing metrics are collected into `failed_metrics` in a fixed
        order — water reaction rating first, then particulate, then conductivity, then observed
        density, then flash point — regardless of the order they appeared in the payload."
        PRD §2.7: "Third, the farm is **restricted** if any of four conditions holds: at least one
        storage tank at the farm has `quality_status` `QUARANTINED`; at least one spill incident at
        the farm has `status` `REPORTED`; the farm's `active_permit_throughput_used_liters` has
        reached or exceeded 90 percent of the governing permit's `max_daily_throughput_liters`; or the
        farm's `in_service_asset_count` is zero."

        Design: Difficulty/compensating_invariant/permit_throughput_and_ledger_conservation_on_receipt_reject
        """
        env = self._quarantined_parcel()

        assert env["receipt"]["status"] == "QUARANTINED"
        assert fx.read_tank(env["tank"]["id"])["quality_status"] == "QUARANTINED"
        farm = fx.read_farm(env["farm"]["id"])
        assert farm["posture"] == "RESTRICTED"
        assert farm["active_permit_throughput_used_liters"] == pytest.approx(0.00, abs=0.005)
        assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
            pytest.approx(1000000.00, abs=0.005)

        sample = validate_success(api.get_quality_sample(env["sample"]["id"], fx.INSPECTOR_A))
        assert sample["verdict"] == "FAIL"
        assert sample["failed_metrics"] == ["water_reaction_rating", "particulate_mg_per_l",
                                            "conductivity_ps_per_m"]

    def test_rejecting_the_parcel_restores_quality_and_posture_without_moving_volume(self, api):
        """PRD §3.3: "Rejection is the conservation case: no ledger volume is added and the farm's
        `active_permit_throughput_used_liters` is left exactly as it was, because only receipts that
        actually reached `RELEASED` ever counted toward the permit day."
        PRD §3.3: "Rejection also has a healing effect on the tank — if no other receipt targeting
        that tank is still `QUARANTINED` and the tank's latest periodic tank QA sample carries verdict
        `PASS`, the tank's `quality_status` returns to `RELEASED`."
        PRD §2.7: "The resulting posture is `FROZEN` when the frozen condition holds, otherwise
        `RESTRICTED` when any restricted condition holds, otherwise `OPEN`."

        Design: Difficulty/compensating_invariant/permit_throughput_and_ledger_conservation_on_receipt_reject
        """
        env = self._quarantined_parcel()
        rejected = validate_success(api.reject_fuel_receipt(
            env["receipt"]["id"], fx.OPERATOR,
            {"reason": "off-spec parcel returned to supplier"}))

        assert rejected["status"] == "REJECTED"
        assert rejected["released_at_utc"] is None
        assert rejected["net_volume_liters"] == pytest.approx(29698.32, abs=0.005), \
            "the measurement is retained even though the ledger effect is not"

        farm = fx.read_farm(env["farm"]["id"])
        assert farm["active_permit_throughput_used_liters"] == pytest.approx(0.00, abs=0.005)
        assert farm["posture"] == "OPEN"

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["book_volume_liters"] == pytest.approx(1000000.00, abs=0.005)
        assert tank["available_volume_liters"] == pytest.approx(999500.00, abs=0.005)
        assert tank["quality_status"] == "RELEASED"
        assert tank["service_status"] == "IN_SERVICE"


class TestAirlineExposureConservationAcrossInvoiceRoundTrip:
    @staticmethod
    def _draft_invoice_over_one_ticket():
        env = fx.setup_completed_order(
            meter_end_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": False},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        fx.set_clock("2026-08-11T01:00:00Z")
        env["invoice"] = fx.create_draft_invoice(
            env["account"]["id"], period_start_utc="2026-08-10T00:00:00Z",
            period_end_utc="2026-08-11T00:00:00Z")
        return env

    def test_issuing_replaces_the_uncollected_term_with_the_invoice_balance(self, api):
        """PRD §3.9: "Issuance flips every swept ticket from `POSTED` to `BILLED` and freezes its
        `billed_line_cents`, recomputing the invoice totals one final time in the same four steps;
        stamps `issued_by_user_id` from the acting identifier; and recomputes both of the account's
        exposure figures, where the uncollected-ticket term is replaced by the invoiced-invoice term,
        which additionally carries the admin fee and the rebate."
        PRD §3.9: "**Step three** computes the consortium administration fee on the post-rebate
        subtotal: `admin_fee_cents` is the smaller of 50,000 cents and four tenths of one percent of
        the subtotal less the rebate, rounded half up to whole cents."
        PRD §3.5: "The **invoiced basis** counts only what has actually been billed:
        `invoiced_exposure_cents` is the sum, over the account's invoices whose `status` is `ISSUED`
        or `DISPUTED`, of that invoice's `total_cents` less its `amount_paid_cents`."

        Design: Difficulty/compensating_invariant/airline_exposure_conservation_across_invoice_issue_and_void
        """
        env = self._draft_invoice_over_one_ticket()
        draft = env["invoice"]
        assert draft["status"] == "DRAFT"
        assert draft["subtotal_cents"] == 1433393
        assert draft["volume_rebate_cents"] == 0
        assert draft["admin_fee_cents"] == 5734
        assert draft["total_cents"] == 1439127

        before = fx.read_account(env["account"]["id"])
        assert before["accrual_exposure_cents"] == 1433393
        assert before["invoiced_exposure_cents"] == 0

        issued = validate_success(api.issue_invoice(draft["id"], fx.BILLING))
        assert issued["status"] == "ISSUED"

        ticket = fx.read_uplift(env["uplift"]["id"])
        assert ticket["status"] == "BILLED"
        assert ticket["invoice_id"] == draft["id"]

        after = fx.read_account(env["account"]["id"])
        assert after["invoiced_exposure_cents"] == 1439127
        assert after["accrual_exposure_cents"] == 1439127, \
            "the admin fee rides on top once the money sits in an issued invoice"

    def test_voiding_returns_accrual_exposure_to_exactly_its_pre_issue_value(self, api):
        """PRD §2.11: "**Airline exposure conservation**: voiding an issued invoice returns the
        account's `accrual_exposure_cents` to precisely its pre-issue value, because the swept tickets
        go back to `POSTED` and re-enter the uncollected term at the same amount they left it."
        PRD §3.9: "Voiding is available from both `ISSUED` and `DISPUTED`, and the two branches behave
        identically: each requires an `amount_paid_cents` of zero, each flips every swept ticket from
        `BILLED` back to `POSTED` with its `invoice_id` cleared to null so a reissue can sweep it
        again — the ticket's `voided_reason` of `INVOICE_VOIDED` is recorded only when a ticket is
        retired for good rather than returned to the unbilled pool — and each recomputes both of the
        account's exposure figures, with the accrual figure returning to exactly its pre-issue value."
        PRD §3.9: "`VOIDED` is terminal."

        Design: Difficulty/compensating_invariant/airline_exposure_conservation_across_invoice_issue_and_void
        """
        env = self._draft_invoice_over_one_ticket()
        invoice_id = env["invoice"]["id"]
        validate_success(api.issue_invoice(invoice_id, fx.BILLING))

        voided = validate_success(api.void_invoice(invoice_id, fx.BILLING))
        assert voided["status"] == "VOIDED"
        assert voided["amount_paid_cents"] == 0

        ticket = fx.read_uplift(env["uplift"]["id"])
        assert ticket["status"] == "POSTED"
        assert ticket["invoice_id"] is None
        assert ticket["billed_line_cents"] == 1433393

        account = fx.read_account(env["account"]["id"])
        assert account["accrual_exposure_cents"] == 1433393, \
            "exactly the pre-issue figure, not the invoice total"
        assert account["invoiced_exposure_cents"] == 0
        assert account["status"] == "ACTIVE"

        assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
            pytest.approx(980000.00, abs=0.005), "the money round trip moves no fuel"
