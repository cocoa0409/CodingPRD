"""Corner behaviour of the dual-basis figures and of the reconciliation checkpoint: both variants are stored
side by side, only the governing one moves fuel, and a posted run is the only way to correct a ledger."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F,
)

BIG_CREDIT = 100_000_000_000
# a TRUCK parcel whose gauge delta (advisory) is exactly 400 liters above its meter ticket (governing)
SPLIT_PARCEL = dict(delivery_mode="TRUCK", supplier_name="Refinery One",
                    meter_ticket_gross_liters=30000.0, tank_opening_gauge_liters=0.0,
                    tank_closing_gauge_liters=30400.0, temperature_c=15.0,
                    certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)


class TestBothBasesAreVisible:
    def test_the_receipt_and_the_run_each_report_two_bases_at_once(self, api):
        """PRD §3.2: "For a `TRUCK` parcel the `governing_gross_liters` is the supplier meter ticket and the
        `advisory_gross_liters` is the gauge delta; for a `PIPELINE` parcel it is the other way round — the
        gauge delta governs and the meter ticket becomes advisory."
        PRD §3.2: "The `advisory_net_volume_liters` repeats the fourth, fifth and sixth steps on the advisory
        gross basis, using the same correction factor and the same measured water figure against a cap of one
        half of one percent of the advisory gross; it exists purely for the reconciliation audit trail and
        never enters the ledger."
        PRD §3.9: "`variance_pct_throughput_basis` uses the throughput denominator and is the **governing**
        figure; `variance_pct_opening_stock_basis` uses the derived opening stock and is advisory, reported
        for the auditor."
        PRD §3.9: "The distinction has teeth: for a busy farm the opening-stock denominator is far larger
        than throughput, so the same absolute variance can sit comfortably under tolerance on the advisory
        basis while breaching it on the governing basis, and conversely a quiet period with little movement
        makes even a tiny absolute variance breach tolerance."

        Design: Corner/complexity_layers/both_variants_are_persisted_side_by_side
        """
        env = fx.setup_fuel_farm()
        tank = fx.make_released_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                     safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                     opening_volume_liters=0.0)
        receipt = fx.record_receipt(tank["id"], **SPLIT_PARCEL)

        stored = fx.read_receipt(receipt["id"])
        assert stored["governing_gross_liters"] == pytest.approx(30000.00, abs=0.005)
        assert stored["advisory_gross_liters"] == pytest.approx(30400.00, abs=0.005)
        assert stored["net_volume_liters"] == pytest.approx(30000.00, abs=0.005)
        assert stored["advisory_net_volume_liters"] == pytest.approx(30400.00, abs=0.005)

        run_env = fx.setup_completed_order(
            meter_end_liters=20_000.0, account_overrides={"credit_limit_cents": BIG_CREDIT})
        run = fx.open_reconciliation_run(run_env["farm"]["id"], "2026-08-10T00:00:00Z",
                                        "2026-08-11T00:00:00Z")
        fx.set_clock("2026-08-11T01:00:00Z")
        measured = fx.measure_reconciliation_run(
            run["id"], [{"storage_tank_id": run_env["tank"]["id"],
                         "measured_volume_liters": 979950.0, "temperature_c": 15.0}])

        assert measured["variance_liters"] == pytest.approx(-50.00, abs=0.005)
        assert measured["throughput_liters"] == pytest.approx(20000.00, abs=0.005)
        assert measured["variance_pct_throughput_basis"] == pytest.approx(0.2500, abs=0.00005)
        assert measured["variance_pct_opening_stock_basis"] < \
            measured["variance_pct_throughput_basis"], \
            "the advisory denominator is the whole opening stock, so its percentage is far smaller"
        assert measured["status"] == "MEASURED"

    def test_only_the_governing_net_reaches_the_tank_and_the_permit_day(self, api):
        """PRD §3.2: "**Sixth**, `net_volume_liters` is the corrected volume less the applied deduction,
        rounded half up to two decimals again."
        PRD §3.2: "A `FarmOperator` records an inbound parcel the moment it lands, and the arithmetic
        performed at that instant is frozen forever: the volumes computed on creation are never recomputed,
        and they are exactly what a later release verdict adds to the tank ledger."
        PRD §3.4: "The `book_volume_liters` is the tank's `opening_volume_liters`, plus the sum of
        `net_volume_liters` over every receipt destined for this tank whose `status` is `RELEASED`, minus the
        sum of `net_liters` over every uplift ticket drawn from this tank whose `status` is `POSTED` or
        `BILLED`, plus the sum of `adjustment_liters` written for this tank by every reconciliation run whose
        `status` is `POSTED`, the whole rounded half up to two decimals."

        Design: Corner/complexity_layers/only_the_governing_variant_moves_money_or_fuel
        """
        env = fx.setup_fuel_farm()
        tank = fx.make_released_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                     safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                     opening_volume_liters=0.0)
        receipt = fx.make_released_receipt(tank["id"], **SPLIT_PARCEL)
        assert receipt["advisory_net_volume_liters"] == pytest.approx(30400.00, abs=0.005)

        assert fx.read_tank(tank["id"])["book_volume_liters"] == \
            pytest.approx(30000.00, abs=0.005), \
            "the 400-liter gauge-versus-meter discrepancy is evidence, not fuel"
        assert fx.read_farm(env["farm"]["id"])["active_permit_throughput_used_liters"] == \
            pytest.approx(30000.00, abs=0.005)


class TestTheRunIsTheLedgerCheckpoint:
    def test_a_manual_dip_records_but_never_corrects(self, api):
        """PRD §3.4: "The tank ledger is never maintained incrementally. On each of its triggers — a receipt
        release, an uplift ticket being posted, an uplift ticket being voided, an order abort, and a
        reconciliation run being posted — the tank's figures are recomputed in full from the source rows."
        PRD §3.9: "Posting writes the signed per-tank variance into the ledger as that tank's
        `adjustment_liters`, with the effect that each measured tank's `book_volume_liters` afterwards equals
        its corrected measured volume exactly."
        PRD §3.4: "The measurement writes `last_gauge_volume_liters`, stamps `last_gauge_at_utc` from the
        logical clock, and stores the water depth."

        Design: Corner/complexity_layers/a_run_is_the_only_way_to_correct_the_ledger
        """
        env = fx.setup_completed_order(
            meter_end_liters=20_000.0, account_overrides={"credit_limit_cents": BIG_CREDIT})
        tank_id = env["tank"]["id"]
        assert fx.read_tank(tank_id)["book_volume_liters"] == \
            pytest.approx(980000.00, abs=0.005)

        fx.gauge_tank(tank_id, measured_volume_liters=900_000.0)

        dipped = fx.read_tank(tank_id)
        assert dipped["last_gauge_volume_liters"] == pytest.approx(900000.00, abs=0.005)
        assert dipped["book_volume_liters"] == pytest.approx(980000.00, abs=0.005), \
            "a dip is an observation; it has no ledger authority whatsoever"

        run = fx.open_reconciliation_run(env["farm"]["id"], "2026-08-10T00:00:00Z",
                                        "2026-08-11T00:00:00Z")
        fx.set_clock("2026-08-11T01:00:00Z")
        fx.measure_reconciliation_run(run["id"],
                                     [{"storage_tank_id": tank_id,
                                       "measured_volume_liters": 979950.0,
                                       "temperature_c": 15.0}])
        posted = validate_success(api.post_reconciliation_run(run["id"], fx.ADMIN), 200)

        assert posted["status"] == "POSTED"
        assert posted["adjustment_liters"] == pytest.approx(-50.00, abs=0.005)
        assert fx.read_tank(tank_id)["book_volume_liters"] == \
            pytest.approx(979950.00, abs=0.005)

    def test_two_runs_over_the_same_period_both_post(self, api):
        """PRD §3.9: "Reconciliation begins when a `FarmOperator` opens a run over a `period_start_utc` and
        a `period_end_utc` strictly later than the start."
        PRD §3.9: "The per-tank book figure is the tank's `book_volume_liters` as the ledger stands at
        measure time."
        PRD §3.9: "Posting writes the signed per-tank variance into the ledger as that tank's
        `adjustment_liters`, with the effect that each measured tank's `book_volume_liters` afterwards equals
        its corrected measured volume exactly."

        Design: Corner/complexity_layers/overlapping_run_periods_are_permitted_but_double_count
        """
        env = fx.setup_completed_order(
            meter_end_liters=20_000.0, account_overrides={"credit_limit_cents": BIG_CREDIT})
        tank_id, farm_id = env["tank"]["id"], env["farm"]["id"]

        first = fx.open_reconciliation_run(farm_id, "2026-08-10T00:00:00Z",
                                          "2026-08-11T00:00:00Z")
        fx.set_clock("2026-08-11T01:00:00Z")
        fx.measure_reconciliation_run(first["id"],
                                     [{"storage_tank_id": tank_id,
                                       "measured_volume_liters": 979950.0,
                                       "temperature_c": 15.0}])
        validate_success(api.post_reconciliation_run(first["id"], fx.ADMIN), 200)
        assert fx.read_tank(tank_id)["book_volume_liters"] == \
            pytest.approx(979950.00, abs=0.005)

        # the same period again — nothing guards the overlap
        second = validate_success(api.create_reconciliation_run(
            farm_id, F.create_reconciliation_run_payload(
                period_start_utc="2026-08-10T00:00:00Z",
                period_end_utc="2026-08-11T00:00:00Z"), fx.OPERATOR), 201)
        measured = fx.measure_reconciliation_run(
            second["id"], [{"storage_tank_id": tank_id,
                            "measured_volume_liters": 979950.0, "temperature_c": 15.0}])

        assert measured["variance_liters"] == pytest.approx(0.00, abs=0.005), \
            "the second run measures against the book the first one already corrected"
        posted = validate_success(api.post_reconciliation_run(second["id"], fx.ADMIN), 200)
        assert posted["adjustment_liters"] == pytest.approx(0.00, abs=0.005)
        assert fx.read_tank(tank_id)["book_volume_liters"] == \
            pytest.approx(979950.00, abs=0.005)

    def test_a_backwards_period_is_refused_at_creation(self, api):
        """PRD §3.9: "Reconciliation begins when a `FarmOperator` opens a run over a `period_start_utc` and
        a `period_end_utc` strictly later than the start."
        PRD §2.10: "**Payload shape and static constraints.** Required-field presence and type correctness
        (`ERR_INVALID_PAYLOAD`) precede declared value constraints (`ERR_FIELD_OUT_OF_RANGE`), which cover
        every numeric range and enumeration membership declared in this document as well as the relational
        constraints — a receipt's closing gauge must exceed its opening gauge, an uplift's meter end reading
        must exceed its meter start reading, a fuelling window's end must be later than its start, a
        reconciliation or billing period's end must be later than its start, and a tank's safe fill volume
        must not exceed its shell capacity."
        PRD §3.9: "Measurements may not be posted until the logical clock has reached or passed the run's
        `period_end_utc` — an early attempt is `ERR_PERIOD_NOT_ELAPSED`."

        Design: Corner/complexity_layers/run_period_must_be_well_ordered
        """
        env = fx.setup_farm_with_released_tank()

        # both instants are in the future, so the elapsed-period rule could also have complained
        validate_error(api.create_reconciliation_run(
            env["farm"]["id"], F.create_reconciliation_run_payload(
                period_start_utc="2026-08-20T00:00:00Z",
                period_end_utc="2026-08-19T00:00:00Z"), fx.OPERATOR),
                       ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

        runs, meta = validate_paginated(api.list_reconciliation_runs(env["farm"]["id"],
                                                                    fx.OPERATOR))
        assert runs == []
        assert meta["total_count"] == 0, "the refused create left no run behind"
