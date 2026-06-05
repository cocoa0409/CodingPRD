"""Pricing and auto-reload calculations (dual-variant, combinatorial, trips, interop)."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    setup_priced_transponder_read, setup_bound_account, create_plaza,
    record_transponder_read, record_plate_read, price, create_account,
    create_vehicle, credit_account, create_interop_agency,
    api_client, TEST_USERS,
)

OP = TEST_USERS["toll_operator_headers"]
CLERK = TEST_USERS["interop_clerk_headers"]


class TestDualVariantPricing:
    def test_transponder_rate_charges_gross_toll(self, api):
        """PRD §3.6: "For a transponder read, `toll_cents` equals `gross_toll_cents`
        with no further surcharge."
        PRD §3.6: "If `is_peak` is true, multiply the pre-peak amount by the peak
        factor — 10000 plus the plaza's `peak_multiplier_bps`, divided by 10000 — and
        round half up to whole cents".

        Design: Difficulty/dual_variant_calc/toll_pricing_transponder_vs_plate_rate
        """
        _, _, _, _, txn = setup_priced_transponder_read(
            base_rate_cents=400, is_peak=True, declared_axles=2, credit=100000,
            plaza_overrides={"peak_multiplier_bps": 2500, "plate_surcharge_bps": 5000},
            serial="TP-DV-A")
        assert txn["toll_cents"] == 500, f"transponder toll should be 500, got {txn['toll_cents']}"

    def test_plate_rate_applies_plate_surcharge(self, api):
        """PRD §3.6: "For a plate read, the Toll-by-Plate surcharge applies: multiply
        `gross_toll_cents` by the plate factor — 10000 plus the plaza's
        `plate_surcharge_bps`, divided by 10000 — and round half up to whole cents."

        Design: Difficulty/dual_variant_calc/toll_pricing_transponder_vs_plate_rate
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="ABC123")
        plaza = create_plaza(base_rate_cents=400, peak_multiplier_bps=2500,
                             plate_surcharge_bps=5000)
        txn = record_plate_read(plaza["id"], "ABC123", "NY", "2026-02-01T09:00:00Z",
                                is_peak=True, declared_axles=2)
        priced = price(txn["id"])
        assert priced["toll_cents"] == 750, f"plate toll should be 750, got {priced['toll_cents']}"

    def test_transponder_and_plate_tolls_differ(self, api):
        """PRD §3.6: "For a transponder read, `toll_cents` equals `gross_toll_cents`
        with no further surcharge. For a plate read, the Toll-by-Plate surcharge applies".

        Design: Difficulty/dual_variant_calc/toll_pricing_transponder_vs_plate_rate
        """
        account, vehicle, transponder, plaza, tp_txn = setup_priced_transponder_read(
            base_rate_cents=400, is_peak=True, declared_axles=2, credit=100000,
            plaza_overrides={"peak_multiplier_bps": 2500, "plate_surcharge_bps": 5000},
            vehicle_overrides={"plate_number": "ABC123"}, serial="TP-DV-C")
        pl_txn = record_plate_read(plaza["id"], "ABC123", "NY", "2026-02-01T09:00:00Z",
                                   is_peak=True, declared_axles=2)
        pl_priced = price(pl_txn["id"])
        assert tp_txn["toll_cents"] == 500
        assert pl_priced["toll_cents"] == 750
        assert tp_txn["toll_cents"] != pl_priced["toll_cents"]


class TestAutoReloadVariants:
    def test_fixed_policy_adds_flat_amount(self, api):
        """PRD §3.1: "Under the `FIXED` policy the system adds a flat
        `reload_amount_cents` (which must be greater than 0 when auto-reload is enabled,
        and defaults to 4000) regardless of the current balance."

        Design: Difficulty/dual_variant_calc/auto_reload_fixed_vs_restore_to_target
        """
        account, vehicle, transponder, _ = setup_bound_account(
            serial="TP-X", credit=900,
            account_overrides={"auto_reload_enabled": True, "reload_policy": "FIXED",
                               "reload_amount_cents": 4000, "low_balance_threshold_cents": 1000})
        plaza = create_plaza(base_rate_cents=400)
        txn = record_transponder_read(plaza["id"], transponder["id"], "2026-02-01T03:00:00Z",
                                      is_peak=False)
        price(txn["id"])
        acct = validate_success(api.get_account(account["id"], OP), 200)
        # 900 - 400 = 500 (<= 1000) -> +4000 = 4500
        assert acct["balance_cents"] == 4500, f"expected 4500, got {acct['balance_cents']}"

    def test_restore_to_target_tops_up_to_target(self, api):
        """PRD §3.1: "Under the `RESTORE_TO_TARGET` policy the system tops up just enough
        to bring the balance up to `target_balance_cents`".
        PRD §3.1: "Under `RESTORE_TO_TARGET`, the credited amount is the difference
        between `target_balance_cents` and the current (possibly negative) balance".

        Design: Difficulty/dual_variant_calc/auto_reload_fixed_vs_restore_to_target
        """
        account, vehicle, transponder, _ = setup_bound_account(
            serial="TP-Y", credit=900,
            account_overrides={"auto_reload_enabled": True,
                               "reload_policy": "RESTORE_TO_TARGET",
                               "target_balance_cents": 5000,
                               "low_balance_threshold_cents": 1000})
        plaza = create_plaza(base_rate_cents=400)
        txn = record_transponder_read(plaza["id"], transponder["id"], "2026-02-01T03:00:00Z",
                                      is_peak=False)
        price(txn["id"])
        acct = validate_success(api.get_account(account["id"], OP), 200)
        # 900 - 400 = 500 (<= 1000) -> top up to 5000
        assert acct["balance_cents"] == 5000, f"expected 5000, got {acct['balance_cents']}"


class TestCombinatorialFormula:
    def test_axle_surcharge_and_peak_interact_multiplicatively(self, api):
        """PRD §3.6: "First, the axle surcharge is the number of axles above 2 — that is
        `declared_axles` minus 2, but never less than 0 — multiplied by the plaza's
        `axle_surcharge_cents`. Add this to the `base_rate_cents` to get the pre-peak
        amount. If `is_peak` is true, multiply the pre-peak amount by the peak factor".

        Design: Difficulty/combinatorial_formula/toll_tiered_axle_plus_peak_multiplier
        """
        _, _, _, _, txn = setup_priced_transponder_read(
            base_rate_cents=400, is_peak=True, declared_axles=3, credit=100000,
            plaza_overrides={"axle_surcharge_cents": 150, "peak_multiplier_bps": 2500},
            vehicle_overrides={"axle_count": 3}, serial="TP-CMB")
        # (400 + 1*150) * 1.25 = 550 * 1.25 = 687.5 -> 688
        assert txn["gross_toll_cents"] == 688, f"expected 688, got {txn['gross_toll_cents']}"
        assert txn["toll_cents"] == 688, f"expected 688, got {txn['toll_cents']}"

    def test_axle_surcharge_is_per_axle_above_two(self, api):
        """PRD §3.6: "the axle surcharge is the number of axles above 2 — that is
        `declared_axles` minus 2, but never less than 0 — multiplied by the plaza's
        `axle_surcharge_cents`. Add this to the `base_rate_cents` to get the pre-peak
        amount."

        Design: Difficulty/combinatorial_formula/toll_tiered_axle_plus_peak_multiplier
        """
        # 4 axles, off-peak: (400 + 2*150) = 700, no peak multiplier applied.
        _, _, _, _, txn = setup_priced_transponder_read(
            base_rate_cents=400, is_peak=False, declared_axles=4, credit=100000,
            plaza_overrides={"axle_surcharge_cents": 150, "peak_multiplier_bps": 2500},
            vehicle_overrides={"axle_count": 4}, serial="TP-CMB2")
        assert txn["gross_toll_cents"] == 700, f"expected 700, got {txn['gross_toll_cents']}"
        assert txn["toll_cents"] == 700, f"expected 700, got {txn['toll_cents']}"

    def test_trip_rounds_per_segment_then_sums(self, api):
        """PRD §3.7: "the order is pinned to round-per-segment-then-sum: each segment is
        rounded to whole cents first, and the already-rounded segment tolls are added
        together, with no second rounding applied to the sum. The trip creates one
        `TollTransaction` per segment, all in `PRICED` status, and debits the account by
        the trip total."

        Design: Difficulty/combinatorial_formula/trip_round_per_segment_then_sum
        """
        account, vehicle, transponder, _ = setup_bound_account(
            serial="TP-TRIP", credit=100000, vehicle_overrides={"plate_number": "TRIP1"})
        plaza = create_plaza(base_rate_cents=333, peak_multiplier_bps=2500)
        seg = {"plaza_id": plaza["id"], "read_method": "TRANSPONDER",
               "is_peak": True, "declared_axles": 2, "transponder_id": transponder["id"]}
        payload = {"account_id": account["id"], "segments": [
            dict(seg, read_at="2026-02-03T08:00:00Z"),
            dict(seg, read_at="2026-02-03T08:05:00Z"),
        ]}
        res = api.create_batch_trip(payload, OP)
        txns = validate_success(res, 201)
        # 333 * 1.25 = 416.25 -> 416 per segment; 416 + 416 = 832 charged.
        for t in txns:
            assert t["toll_cents"] == 416, f"each segment should be 416, got {t['toll_cents']}"
        acct = validate_success(api.get_account(account["id"], OP), 200)
        assert acct["balance_cents"] == 99168, f"expected 99168, got {acct['balance_cents']}"

    def test_trip_creates_one_priced_transaction_per_segment(self, api):
        """PRD §3.7: "The trip creates one `TollTransaction` per segment, all in
        `PRICED` status, and debits the account by the trip total."

        Design: Difficulty/combinatorial_formula/trip_round_per_segment_then_sum
        """
        account, vehicle, transponder, _ = setup_bound_account(
            serial="TP-TRIP2", credit=100000, vehicle_overrides={"plate_number": "TRIP2"})
        plaza = create_plaza(base_rate_cents=333, peak_multiplier_bps=2500)
        seg = {"plaza_id": plaza["id"], "read_method": "TRANSPONDER",
               "is_peak": True, "declared_axles": 2, "transponder_id": transponder["id"]}
        payload = {"account_id": account["id"], "segments": [
            dict(seg, read_at="2026-02-03T08:00:00Z"),
            dict(seg, read_at="2026-02-03T08:05:00Z"),
        ]}
        txns = validate_success(api.create_batch_trip(payload, OP), 201)
        assert len(txns) == 2, f"expected 2 transactions, got {len(txns)}"
        for t in txns:
            assert t["pricing_status"] == "PRICED"


class TestInteropHomeShare:
    def test_interop_fee_withheld_before_debit(self, api):
        """PRD §3.6: "the withheld amount is `toll_cents` multiplied by the agency's
        `settlement_fee_bps`, divided by 10000, rounded half up; the home debit is
        `toll_cents` minus that withheld amount; the account is debited by the home-debit
        amount, an `INTEROP_DEBIT` ledger entry for the negative home-debit amount is
        appended".

        Design: Corner/calculations/interop_home_share_fee_withheld
        """
        agency = create_interop_agency(name="EZ-NJ", state_code="NJ",
                                       settlement_fee_bps=200, active=True)
        account = create_account()
        credit_account(account["id"], 5000)
        vehicle = create_vehicle(account["id"], plate_number="IO1")
        plaza = create_plaza(name="Pio", state_code="NJ", base_rate_cents=400,
                            peak_multiplier_bps=2500, plate_surcharge_bps=5000)
        txn = record_plate_read(plaza["id"], "IO1", "NY", "2026-03-04T08:00:00Z",
                                is_peak=True, declared_axles=2,
                                interop_agency_id=agency["id"], as_headers=CLERK)
        priced = price(txn["id"])
        # gross 500, plate 750. withheld = round(750*200/10000)=15. home debit 735.
        assert priced["toll_cents"] == 750
        acct = validate_success(api.get_account(account["id"], OP), 200)
        assert acct["balance_cents"] == 4265, f"expected 4265, got {acct['balance_cents']}"

    def test_transponder_offpeak_base_only(self, api):
        """PRD §3.6: "The `base_rate_cents` is the base off-peak toll for a 2-axle
        vehicle". PRD §3.6: "if `is_peak` is false, the pre-peak amount is used
        unchanged. The result is `gross_toll_cents`." PRD §3.6: "For a transponder read,
        `toll_cents` equals `gross_toll_cents` with no further surcharge."

        Design: Corner/calculations/transponder_offpeak_base_only
        """
        _, _, _, _, txn = setup_priced_transponder_read(
            base_rate_cents=400, is_peak=False, declared_axles=2, credit=5000,
            serial="TP-CR")
        assert txn["gross_toll_cents"] == 400
        assert txn["toll_cents"] == 400
