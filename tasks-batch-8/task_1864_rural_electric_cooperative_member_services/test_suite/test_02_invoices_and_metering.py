"""Invoices and metering: provisional vs final variants, tiered charge rounding,
seasonal irrigation discount, write-off aging and patronage back-out (PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_invoice_payload,
    create_rate_schedule_payload,
    get_success_data,
    record_meter_readings,
    set_clock,
    setup_cooperative,
    setup_finalized_invoice,
    setup_member,
    setup_published_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)

REP = TEST_USERS["rep"]
ANALYST = TEST_USERS["rate_analyst"]
CLERK = TEST_USERS["billing_clerk"]


def _member_with_location(rate_class="RESIDENTIAL", **loc_overrides):
    setup_cooperative()
    member, location = setup_member(
        status="ACTIVE", rate_class=rate_class, location_overrides=loc_overrides or None)
    return member, location


class TestProvisionalVsFinal:
    def test_invoice_provisional_variant_and_final_recompute(self, api):
        """PRD §3.4: "The invoice is born `PROVISIONAL` in both senses: its
        `status` is `PROVISIONAL` and its `variant` is the `PROVISIONAL` flavor"
        and "On finalize, the `variant` flips to `FINAL` and every charge is
        recomputed from the register: `kwh_billed` becomes the current register
        reading minus the prior register reading".

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_divergence
        """
        member, location = _member_with_location()
        setup_published_schedule(
            customer_charge_cents=2000,
            tiers=[{"up_to_kwh": 1000, "cents_per_kwh": 12},
                   {"up_to_kwh": None, "cents_per_kwh": 9}])
        record_meter_readings(location["id"], [
            ("2026-07-01T00:00:00Z", 1000, 2.0),
            ("2026-08-01T00:00:00Z", 2500, 2.5),
        ])
        provisional = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-07-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z"),
            CLERK), expected_status=201)
        assert provisional["variant"] == "PROVISIONAL"
        assert provisional["status"] == "PROVISIONAL"

        final = validate_success(api.finalize_invoice(provisional["id"], CLERK), 200)
        assert final["variant"] == "FINAL"
        assert final["kwh_billed"] == 1500
        assert final["total_due_cents"] == 2000 + 1000 * 12 + 500 * 9

    def test_provisional_estimate_differs_from_final_total(self, api):
        """PRD §3.4: "its `variant` is the `PROVISIONAL` flavor, a
        forward-looking estimate in which `kwh_billed` is projected from the
        average daily consumption of the prior three `FINALIZED` invoices" and
        "On finalize, the `variant` flips to `FINAL` and every charge is
        recomputed from the register".

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_divergence
        """
        member, location = _member_with_location()
        setup_published_schedule(
            customer_charge_cents=2000,
            tiers=[{"up_to_kwh": 1000, "cents_per_kwh": 12},
                   {"up_to_kwh": None, "cents_per_kwh": 9}])
        record_meter_readings(location["id"], [
            ("2026-07-01T00:00:00Z", 1000, 2.0),
            ("2026-08-01T00:00:00Z", 2500, 2.5),
        ])
        provisional = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-07-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z"),
            CLERK), expected_status=201)
        final = validate_success(api.finalize_invoice(provisional["id"], CLERK), 200)
        # No prior FINALIZED invoices exist, so the provisional estimate cannot
        # equal the register-true 1500-kWh bill.
        assert provisional["total_due_cents"] != final["total_due_cents"]
        assert final["total_due_cents"] == 18500


class TestTieredChargeRounding:
    def test_tiered_energy_charge_per_line_half_up_then_sum(self, api):
        """PRD §2.6: "The tiered energy charge rounds each tier line half-up to
        whole cents first and only then sums the lines — summing unrounded lines
        and rounding once at the end is a different (and non-compliant)
        algorithm."

        Design: Difficulty/combinatorial_formula/tiered_energy_charge_rounding_order
        """
        member, location = _member_with_location(rate_class="COMMERCIAL_GENERAL")
        setup_published_schedule(
            rate_class="COMMERCIAL_GENERAL", code="CG-X", customer_charge_cents=0,
            tiers=[{"up_to_kwh": 1, "cents_per_kwh": 7.5},
                   {"up_to_kwh": None, "cents_per_kwh": 0.5}])
        record_meter_readings(location["id"], [
            ("2026-07-01T00:00:00Z", 0, 0),
            ("2026-08-01T00:00:00Z", 2, 0),
        ])
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-07-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z"),
            CLERK), expected_status=201)
        final = validate_success(api.finalize_invoice(inv["id"], CLERK), 200)
        # Per-line HALF_UP then sum: round(1*7.5)=8, round(1*0.5)=1 -> 9.
        # Sum-then-round would give round(8.0)=8.
        assert final["energy_charge_cents"] == 9
        assert final["total_due_cents"] == 9

    def test_tiered_energy_charge_rounding_tier_boundary(self, api):
        """PRD §3.4: "each tier line is that consumption multiplied by the
        tier's `cents_per_kwh`, rounded half-up to whole cents per line before
        the lines are summed."

        Design: Difficulty/combinatorial_formula/tiered_energy_charge_rounding_order
        """
        member, location = _member_with_location(rate_class="COMMERCIAL_GENERAL")
        setup_published_schedule(
            rate_class="COMMERCIAL_GENERAL", code="CG-Y", customer_charge_cents=0,
            tiers=[{"up_to_kwh": 2, "cents_per_kwh": 2.5},
                   {"up_to_kwh": None, "cents_per_kwh": 1.5}])
        record_meter_readings(location["id"], [
            ("2026-07-01T00:00:00Z", 0, 0),
            ("2026-08-01T00:00:00Z", 3, 0),
        ])
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-07-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z"),
            CLERK), expected_status=201)
        final = validate_success(api.finalize_invoice(inv["id"], CLERK), 200)
        # line1 = round(2 * 2.5) = 5; line2 = round(1 * 1.5) = 2 (HALF_UP) -> 7
        assert final["energy_charge_cents"] == 7


class TestIrrigationBilling:
    def test_irrigation_offseason_discount_applied(self, api):
        """PRD §3.4: "When the location is on the `IRRIGATION` rate class and
        the billing period's month falls outside the cooperative's declared
        irrigation season — the inclusive window from
        `irrigation_season_start_month` through `irrigation_season_end_month` on
        the `Cooperative` — the summed energy charge is then reduced by the
        schedule's `irrigation_offseason_discount_pct`." and "`IRRIGATION`
        locations are billed for at least 5.0 kW even when actual peak demand is
        lower".

        Design: Corner/calculations/irrigation_offseason_discount_applied
        """
        member, location = _member_with_location(
            rate_class="IRRIGATION", irrigation_connected_load_kw=20)
        setup_published_schedule(
            rate_class="IRRIGATION", code="IR-2", customer_charge_cents=5000,
            tiers=[{"up_to_kwh": None, "cents_per_kwh": 10}],
            irrigation_offseason_discount_pct=0.20)
        record_meter_readings(location["id"], [
            ("2026-01-01T00:00:00Z", 0, 2.0),
            ("2026-02-01T00:00:00Z", 1000, 3.0),
        ])
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-01-01T00:00:00Z",
                billing_period_end="2026-02-01T00:00:00Z"),
            CLERK), expected_status=201)
        final = validate_success(api.finalize_invoice(inv["id"], CLERK), 200)
        # January is outside the Apr-Sep season: 1000*10 = 10000, less 20% -> 8000
        assert final["energy_charge_cents"] == 8000
        # Irrigation minimum billing kW floor of 5.0 overrides the 3.0 peak
        assert final["demand_kw_billed"] == 5.0
        assert final["total_due_cents"] == 5000 + 8000 + 0

    def test_irrigation_inseason_no_discount(self, api):
        """PRD §3.4: "When the location is on the `IRRIGATION` rate class and
        the billing period's month falls outside the cooperative's declared
        irrigation season — the inclusive window from
        `irrigation_season_start_month` through `irrigation_season_end_month` on
        the `Cooperative` — the summed energy charge is then reduced by the
        schedule's `irrigation_offseason_discount_pct`."

        Design: Corner/calculations/irrigation_inseason_no_discount
        """
        member, location = _member_with_location(
            rate_class="IRRIGATION", irrigation_connected_load_kw=20)
        setup_published_schedule(
            rate_class="IRRIGATION", code="IR-2", customer_charge_cents=5000,
            tiers=[{"up_to_kwh": None, "cents_per_kwh": 10}],
            irrigation_offseason_discount_pct=0.20)
        record_meter_readings(location["id"], [
            ("2026-07-01T00:00:00Z", 0, 10.0),
            ("2026-08-01T00:00:00Z", 1000, 12.0),
        ])
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-07-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z"),
            CLERK), expected_status=201)
        final = validate_success(api.finalize_invoice(inv["id"], CLERK), 200)
        # July is inside the Apr-Sep season: no discount on 1000*10 = 10000.
        assert final["energy_charge_cents"] == 10000


class TestInvoiceStateGuards:
    def test_finalize_without_reading_returns_reading_missing(self, api):
        """PRD §3.4: "It is blocked until the location has a meter reading whose
        `reading_at` is at or after `billing_period_end` — otherwise
        `ERR_READING_MISSING`."

        Design: Corner/state_machines/finalize_without_reading_returns_reading_missing
        """
        member, location = _member_with_location()
        setup_published_schedule(rate_class="RESIDENTIAL")
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-07-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z"),
            CLERK), expected_status=201)
        resp = api.finalize_invoice(inv["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_READING_MISSING)

    def test_void_provisional_invoice_then_finalize_rejected(self, api):
        """PRD §3.4: "A `PROVISIONAL` invoice that should never have existed can
        be voided (`PROVISIONAL → VOID`)." VOID is a terminal flavor of the bill,
        so a subsequent finalize finds the invoice not in a legitimate
        from-state (`ERR_INVALID_STATE` per §2.8 rule five).

        Design: Corner/state_machines/void_provisional_invoice_valid
        """
        member, location = _member_with_location()
        setup_published_schedule(rate_class="RESIDENTIAL")
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-07-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z"),
            CLERK), expected_status=201)
        voided = validate_success(api.void_invoice(inv["id"], CLERK), 200)
        assert voided["status"] == "VOID"
        resp = api.finalize_invoice(inv["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWriteOff:
    def test_write_off_age_boundary_179_vs_181_days(self, api):
        """PRD §3.4: "or — once its `billing_period_end` lies more than 180 days
        in the past — written off (`FINALIZED → WRITTEN_OFF`); attempting an
        earlier write-off is refused with `ERR_WRITE_OFF_TOO_EARLY`."

        Design: Difficulty/boundary_precision_check/write_off_exactly_180_days
        """
        member, location = _member_with_location()
        setup_published_schedule(
            customer_charge_cents=2000,
            tiers=[{"up_to_kwh": 1000, "cents_per_kwh": 12},
                   {"up_to_kwh": None, "cents_per_kwh": 9}])
        inv = setup_finalized_invoice(
            location["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", 0, 100)
        # 2026-07-30 is 179 days after the 2026-02-01 period end — too early.
        set_clock("2026-07-30T00:00:00Z")
        resp = api.write_off_invoice(inv["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_TOO_EARLY)
        # 2026-08-01 is 181 days after — more than 180, so write-off succeeds.
        set_clock("2026-08-01T00:00:00Z")
        written = validate_success(api.write_off_invoice(inv["id"], CLERK), 200)
        assert written["status"] == "WRITTEN_OFF"

    def test_write_off_immediately_after_finalize_rejected(self, api):
        """PRD §3.4: "or — once its `billing_period_end` lies more than 180 days
        in the past — written off (`FINALIZED → WRITTEN_OFF`); attempting an
        earlier write-off is refused with `ERR_WRITE_OFF_TOO_EARLY`."

        Design: Difficulty/boundary_precision_check/write_off_exactly_180_days
        """
        member, location = _member_with_location()
        setup_published_schedule(rate_class="RESIDENTIAL")
        inv = setup_finalized_invoice(
            location["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 0, 100)
        # The logical clock still reads its 2026-08-01 default: the period end
        # is zero days in the past, far inside the 180-day guard.
        resp = api.write_off_invoice(inv["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_TOO_EARLY)

    def test_write_off_backs_out_patronage_base(self, api):
        """PRD §3.4: "Writing off is a compensating event, not amnesia: the
        invoice's kilowatt-hours are backed out of the member's patronage bases,
        undoing the allocation weight they would otherwise have conferred."

        Design: Corner/calculations/write_off_backs_out_patronage_base
        """
        member, location = _member_with_location()
        setup_published_schedule(rate_class="RESIDENTIAL")
        inv = setup_finalized_invoice(
            location["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", 0, 100)
        before = get_success_data(api.get_member(member["id"], REP), 200)
        assert before["patronage_base_kwh"] == 100
        set_clock("2026-08-01T00:00:00Z")
        validate_success(api.write_off_invoice(inv["id"], CLERK), 200)
        after = get_success_data(api.get_member(member["id"], REP), 200)
        assert after["patronage_base_kwh"] == 0


class TestMeterReadings:
    def test_meter_reading_immutable_event_no_version(self, api):
        """PRD §2.4: "A `MeterReading` and a `Ballot` each carry only `id` and
        `created_at`; both `updated_at` and `version` are absent from these
        resources, because neither is ever mutated after creation."

        Design: Corner/entities/meter_reading_immutable_event_no_version
        """
        member, location = _member_with_location()
        data = validate_success(api.create_meter_reading(
            {"service_location_id": location["id"],
             "reading_at": "2026-08-01T00:00:00Z",
             "kwh_register": 100, "demand_kw": 1.5, "source": "AMR"},
            CLERK), expected_status=201)
        assert data.get("id")
        assert data.get("created_at")
        assert "version" not in data
        assert "updated_at" not in data

    def test_meter_readings_filtered_list_by_location(self, api):
        """PRD §3.4: "Readings are immutable records — they carry only `id` and
        `created_at` per §2.4 — and can be listed filtered by
        `service_location_id`."

        Design: Corner/endpoints/meter_readings_filtered_list_by_location
        """
        setup_cooperative()
        member, loc_a = setup_member(status="ACTIVE", address="1")
        loc_b = get_success_data(api.create_service_location(
            {"member_id": member["id"], "address": "2", "rate_class": "RESIDENTIAL"},
            REP), 201)
        record_meter_readings(loc_a["id"], [
            ("2026-07-01T00:00:00Z", 0, 0),
            ("2026-08-01T00:00:00Z", 50, 0),
        ])
        record_meter_readings(loc_b["id"], [("2026-07-15T00:00:00Z", 10, 0)])
        data, _meta = validate_paginated(
            api.list_meter_readings(CLERK, params={"service_location_id": loc_a["id"]}))
        assert len(data) == 2
        assert all(r["service_location_id"] == loc_a["id"] for r in data)
