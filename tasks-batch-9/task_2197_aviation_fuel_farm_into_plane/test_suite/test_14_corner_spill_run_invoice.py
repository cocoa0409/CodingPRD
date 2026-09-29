"""Corner behaviour of the closing machinery: the reportable-volume knife edge, the containment
bound, the reconciliation period gate and its exact measurement set, and the invoice's bounded
dispute budget, reissue link and payment ceiling."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, make_airline_rep_headers, make_billing_headers,
)


class TestSpillIncidentCorners:
    def test_a_spill_a_hundredth_below_the_threshold_may_not_be_escalated(self, api):
        """PRD §3.8: "**Escalation, `REPORTED → ESCALATED`,** is lawful only when the spilled volume has
        reached the governing permit's `max_reportable_spill_liters` — the comparison is inclusive, so a
        spill of exactly the reportable volume must be escalated — and only when a non-empty
        `regulator_reference` is supplied."
        PRD §3.8: "A volume below the threshold, or a missing reference, is rejected with
        `ERR_SPILL_NOT_REPORTABLE`."
        PRD §3.8: "**Hop one** recomputes the farm's posture, which becomes `FROZEN` because an
        escalated incident now exists at the farm."

        Design: Corner/entities/escalate_below_the_reportable_volume
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_reportable_spill_liters": 20.0})
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        farm_id = env["farm"]["id"]

        small = fx.report_spill(farm_id, spilled_volume_liters=19.99, surface="APRON")
        validate_error(api.escalate_spill(small["id"],
                                          {"regulator_reference": "REG-2026-0007"}, fx.ENVIRO),
                       ApiErrorId.ERR_SPILL_NOT_REPORTABLE, 422)
        assert fx.read_spill(small["id"])["status"] == "REPORTED"
        assert fx.read_farm(farm_id)["posture"] == "RESTRICTED", \
            "an open incident restricts the farm but never freezes it"

        exact = fx.report_spill(farm_id, spilled_volume_liters=20.0, surface="APRON")
        escalated = validate_success(api.escalate_spill(
            exact["id"], {"regulator_reference": "REG-2026-0008"}, fx.ENVIRO))

        assert escalated["status"] == "ESCALATED"
        assert escalated["regulator_reference"] == "REG-2026-0008"
        assert fx.read_farm(farm_id)["posture"] == "FROZEN"

    def test_containing_more_than_was_spilled_is_out_of_range(self, api):
        """PRD §3.8: "**Containment, `REPORTED → CONTAINED`,** is the non-reportable path and skips
        escalation entirely: it is lawful only when the spilled volume is strictly below the governing
        permit's `max_reportable_spill_liters`, and it requires a `contained_volume_liters` no greater
        than the `spilled_volume_liters`."
        PRD §3.8: "Its effects are correspondingly narrow — the reliability penalty is applied to the
        attributed asset when a `fueling_asset_id` was recorded, which may itself drive that asset
        `IN_SERVICE → DOWN_MAINTENANCE`; the farm's `open_spill_count` and posture are recomputed; and
        the incident's, the farm's and (when attributed) the asset's `version` each rise by one."

        Design: Corner/entities/contained_volume_greater_than_spilled_volume
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_reportable_spill_liters": 40.0})
        truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        spill = fx.report_spill(env["farm"]["id"], spilled_volume_liters=25.0,
                                surface="APRON", fueling_asset_id=truck["id"])

        validate_error(api.contain_spill(spill["id"], {"contained_volume_liters": 30.0},
                                         fx.ENVIRO),
                       ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

        after = fx.read_spill(spill["id"])
        assert after["status"] == "REPORTED"
        assert after["contained_volume_liters"] is None
        asset = fx.read_asset(truck["id"])
        assert asset["reliability_score"] == 100, "the refused containment charged no penalty"
        assert asset["status"] == "IN_SERVICE"

    def test_containing_exactly_the_spilled_volume_is_the_boundary_that_passes(self, api):
        """PRD §3.8: "An escalated incident reaches containment by the same action from a different
        origin: `ESCALATED → CONTAINED` requires only a `contained_volume_liters` no greater than the
        spilled volume, applies the same reliability penalty, and recomputes the open spill count and
        posture."
        PRD §3.8: "That recomputation is how a farm thaws: the farm leaves `FROZEN` once no escalated
        incident remains at it and its permit is `ACTIVE` and unexpired, landing on `RESTRICTED` while
        any incident is still merely `REPORTED`."

        Design: Corner/entities/contained_volume_greater_than_spilled_volume
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_reportable_spill_liters": 20.0})
        truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        spill = fx.report_spill(env["farm"]["id"], spilled_volume_liters=25.0,
                                surface="APRON", fueling_asset_id=truck["id"])
        fx.escalate_spill(spill["id"], regulator_reference="REG-2026-0009")
        assert fx.read_farm(env["farm"]["id"])["posture"] == "FROZEN"

        contained = validate_success(api.contain_spill(
            spill["id"], {"contained_volume_liters": 25.0}, fx.ENVIRO))

        assert contained["status"] == "CONTAINED"
        assert contained["contained_volume_liters"] == pytest.approx(25.0, abs=0.005)
        asset = fx.read_asset(truck["id"])
        assert asset["reliability_score"] == 85, \
            "three 10-litre steps at 5 points each, on a sealed apron"
        assert asset["status"] == "DOWN_MAINTENANCE", "the freeze cascade parked it"
        farm = fx.read_farm(env["farm"]["id"])
        assert farm["open_spill_count"] == 0
        assert farm["posture"] == "RESTRICTED", \
            "the farm thawed out of FROZEN but has no in-service asset left"


class TestReconciliationRunCorners:
    def test_measurements_wait_for_the_period_end_and_are_taken_at_it_exactly(self, api):
        """PRD §3.9: "Measurements may not be posted until the logical clock has reached or passed the
        run's `period_end_utc` — an early attempt is `ERR_PERIOD_NOT_ELAPSED`."
        PRD §3.9: "The run opens in `OPEN` with `tank_measurements` an empty array,
        `receipts_net_liters`, `uplifts_net_liters` and `throughput_liters` at 0.0, `variance_liters`,
        `variance_pct_throughput_basis`, `variance_pct_opening_stock_basis` and `adjustment_liters`
        null, and `posted_by_user_id` null."

        Design: Corner/entities/measure_before_the_period_has_elapsed
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        tank_id = env["tank"]["id"]
        run = fx.open_reconciliation_run(env["farm"]["id"],
                                         period_start_utc="2026-08-10T00:00:00Z",
                                         period_end_utc="2026-08-10T07:00:00Z")
        assert run["status"] == "OPEN"
        assert run["tank_measurements"] == []
        assert run["variance_liters"] is None

        measurements = [{"storage_tank_id": tank_id, "measured_volume_liters": 1_000_000.0,
                         "temperature_c": 15.0}]
        validate_error(api.measure_reconciliation_run(
            run["id"], {"tank_measurements": measurements}, fx.OPERATOR),
            ApiErrorId.ERR_PERIOD_NOT_ELAPSED, 409)

        fx.set_clock("2026-08-10T07:00:00Z")
        measured = fx.measure_reconciliation_run(run["id"], measurements)

        assert measured["status"] == "MEASURED", "the clock standing exactly on the end is enough"
        assert measured["variance_liters"] == pytest.approx(0.00, abs=0.005)

    def test_the_measurement_set_excludes_a_retired_tank_and_admits_no_stranger(self, api):
        """PRD §3.9: "The `tank_measurements` payload is an array of objects, each carrying a
        `storage_tank_id`, a `measured_volume_liters` and a `temperature_c`, and it must contain
        **exactly one entry for each storage tank at the farm whose `service_status` is `IN_SERVICE` or
        `ISOLATED`, and no entry for any other tank**."
        PRD §3.9: "Tanks that are `OUT_OF_SERVICE` are excluded and contribute no variance. A set that
        is short, long, or contains a stranger is rejected with `ERR_MEASUREMENT_SET_INCOMPLETE`."

        Design: Corner/entities/measurement_set_must_cover_in_service_and_isolated_tanks_only
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        farm_id, working = env["farm"]["id"], env["tank"]["id"]
        second = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                  safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                  opening_volume_liters=0.0)
        retired = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                   safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                   opening_volume_liters=0.0)
        fx.isolate_tank(retired["id"], "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
        validate_success(api.change_tank_service_status(
            retired["id"], {"to_status": "OUT_OF_SERVICE"}, fx.ADMIN))

        run = fx.open_reconciliation_run(farm_id, period_start_utc="2026-08-10T00:00:00Z",
                                         period_end_utc="2026-08-10T07:00:00Z")
        fx.set_clock("2026-08-10T07:00:00Z")

        def entry(tank_id):
            return {"storage_tank_id": tank_id, "measured_volume_liters": 0.0,
                    "temperature_c": 15.0}

        validate_error(api.measure_reconciliation_run(
            run["id"], {"tank_measurements": [entry(working), entry(second["id"]),
                                              entry(retired["id"])]}, fx.OPERATOR),
            ApiErrorId.ERR_MEASUREMENT_SET_INCOMPLETE, 422)
        runs, _meta = validate_paginated(api.list_reconciliation_runs(farm_id, fx.OPERATOR))
        assert [r["status"] for r in runs] == ["OPEN"]

        validate_error(api.measure_reconciliation_run(
            run["id"], {"tank_measurements": [entry(working)]}, fx.OPERATOR),
            ApiErrorId.ERR_MEASUREMENT_SET_INCOMPLETE, 422)

        measured = fx.measure_reconciliation_run(
            run["id"], [entry(working), entry(second["id"])])
        assert measured["status"] == "MEASURED", "exactly the two live tanks, no more and no less"


class TestInvoiceCorners:
    @staticmethod
    def _issued_invoice():
        return fx.setup_issued_invoice(
            meter_end_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": False},
            permit_overrides={"max_daily_throughput_liters": 400000.0})

    def test_the_third_dispute_is_refused_after_two_resolved_rounds(self, api):
        """PRD §3.9: "An `AirlineRep` owning the account may dispute an issued invoice,
        `ISSUED → DISPUTED`, provided the acting identifier is the invoice's `airline_account_id`, the
        invoice's `amount_paid_cents` is zero, and its `dispute_round` is at most 1 — so an invoice may
        be disputed at most twice, and a third attempt on an invoice already at a `dispute_round` of 2
        is rejected with `ERR_DISPUTE_LIMIT_REACHED`."
        PRD §3.9: "Resolution, `DISPUTED → ISSUED`, is a `BillingClerk` action refused when the acting
        identifier equals the invoice's `issued_by_user_id`; it raises `dispute_round` by one, stamps
        `dispute_resolved_by_user_id`, and raises the invoice's `version` by one, so the cycle
        `ISSUED → DISPUTED → ISSUED` is bounded at two rounds."

        Design: Corner/entities/dispute_budget_is_exhausted_after_two_rounds
        """
        env = self._issued_invoice()
        invoice_id = env["invoice"]["id"]
        rep = make_airline_rep_headers(env["account"]["id"])
        resolver = make_billing_headers("clerk-two")

        for expected_round in (1, 2):
            disputed = validate_success(api.dispute_invoice(invoice_id, rep))
            assert disputed["status"] == "DISPUTED"
            resolved = validate_success(api.resolve_invoice_dispute(invoice_id, resolver))
            assert resolved["status"] == "ISSUED"
            assert resolved["dispute_round"] == expected_round

        validate_error(api.dispute_invoice(invoice_id, rep),
                       ApiErrorId.ERR_DISPUTE_LIMIT_REACHED, 409)

        final = fx.read_invoice(invoice_id)
        assert final["status"] == "ISSUED"
        assert final["dispute_round"] == 2
        assert final["dispute_resolved_by_user_id"] == "clerk-two"

    def test_a_reissue_sweeps_the_same_tickets_and_points_back_at_the_void(self, api):
        """PRD §3.9: "Tickets already `BILLED` and tickets `VOIDED` are never swept, which is precisely
        why voiding an invoice and reissuing it re-sweeps exactly the same tickets."
        PRD §3.9: "A `BillingClerk` creates a draft naming the `airline_account_id` to bill, a
        `period_start_utc`, a `period_end_utc` strictly later than the start, the mandatory
        `expected_airline_account_version`, and optionally a `replaces_invoice_id` when the draft is a
        reissue superseding a previously voided invoice."
        PRD §3.9: "**Step four** sets `total_cents` to the subtotal, less the rebate, plus the admin
        fee."

        Design: Corner/entities/reissue_links_through_replaces_invoice_id
        """
        env = self._issued_invoice()
        original = fx.read_invoice(env["invoice"]["id"])
        assert original["subtotal_cents"] == 1433393
        assert original["total_cents"] == 1439127

        voided = validate_success(api.void_invoice(original["id"], fx.BILLING))
        assert voided["status"] == "VOIDED"

        reissue = fx.create_draft_invoice(env["account"]["id"],
                                          period_start_utc="2026-08-10T00:00:00Z",
                                          period_end_utc="2026-08-11T00:00:00Z",
                                          replaces_invoice_id=original["id"])
        assert reissue["replaces_invoice_id"] == original["id"]
        assert reissue["subtotal_cents"] == 1433393
        assert reissue["admin_fee_cents"] == 5734
        assert reissue["total_cents"] == 1439127, "the same tickets reproduce the same money"
        assert fx.read_uplift(env["uplift"]["id"])["invoice_id"] == reissue["id"]

        replacements, _meta = validate_paginated(api.list_invoices(
            fx.BILLING, {"replaces_invoice_id": original["id"]}))
        assert [i["id"] for i in replacements] == [reissue["id"]]

    def test_a_payment_may_settle_the_invoice_but_never_overshoot_it(self, api):
        """PRD §3.9: "Payments are recorded against an issued invoice with an `amount_cents` that must
        be strictly positive and must not push the cumulative `amount_paid_cents` above the invoice's
        `total_cents`; a violation of either bound is `ERR_PAYMENT_EXCEEDS_BALANCE`."
        PRD §3.9: "Once the cumulative paid amount reaches the total the invoice moves
        `ISSUED → PAID`, both exposure figures fall by the invoice total, and the invoice's and
        account's `version` each rise by one."

        Design: Corner/entities/payment_larger_than_the_balance
        """
        env = self._issued_invoice()
        invoice_id = env["invoice"]["id"]
        total = fx.read_invoice(invoice_id)["total_cents"]
        assert total == 1439127

        validate_error(api.create_payment(invoice_id, {"amount_cents": total + 1}, fx.BILLING),
                       ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, 422)
        held = fx.read_invoice(invoice_id)
        assert held["status"] == "ISSUED"
        assert held["amount_paid_cents"] == 0

        validate_success(api.create_payment(invoice_id, {"amount_cents": total}, fx.BILLING),
                         201)

        settled = fx.read_invoice(invoice_id)
        assert settled["status"] == "PAID"
        assert settled["amount_paid_cents"] == total
        account = fx.read_account(env["account"]["id"])
        assert account["invoiced_exposure_cents"] == 0
        assert account["accrual_exposure_cents"] == 0
