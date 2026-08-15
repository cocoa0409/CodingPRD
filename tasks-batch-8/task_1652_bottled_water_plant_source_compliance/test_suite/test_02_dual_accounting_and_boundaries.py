"""Dual accounting views (provisional vs certified; gross vs sanitized pools)
and exact boundary semantics on the gallon caps and the wash-cycle ceiling."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_permit,
    create_plant,
    create_withdrawal_event_payload,
    get_success_data,
    post_withdrawal_event,
    run_compliance,
    set_clock,
    setup_released_lot_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    PLANT_ADMIN, SOURCE_MONITOR, COMPLIANCE_OFFICER, PL1, QA1, SL1,
    create_bottle, create_running_wash_with_bottles, loop_bottle_to_dirty,
)


class TestPermitProvisionalVsCertified:
    def test_recorded_events_count_provisionally_but_not_certified(self, api):
        """PRD §2.11: "The **provisional** view counts events in `RECORDED`
        or `FINALIZED` status; the **certified** view counts `FINALIZED`
        events only".

        Design: Difficulty/dual_variant_calc/permit_remaining_provisional_vs_certified
        """
        plant = create_plant("Plant DV1")
        permit = create_permit(plant["id"], permit_number="SP-DV1")
        ev1, _ = post_withdrawal_event(permit["id"], gallons=6000)
        ev2, permit_now = post_withdrawal_event(
            permit["id"], gallons=3000, meter_start=6000
        )

        assert ev1["status"] == "RECORDED"
        assert ev2["status"] == "RECORDED"
        assert permit_now["withdrawn_today_provisional_gallons"] == 9000
        assert permit_now["withdrawn_today_certified_gallons"] == 0
        assert permit_now["withdrawn_month_provisional_gallons"] == 9000
        assert permit_now["withdrawn_month_certified_gallons"] == 0

    def test_certified_view_catches_up_after_finalization(self, api):
        """PRD §3.1: "every `RECORDED` event whose `withdrawal_date` falls
        strictly before the current logical date moves to `FINALIZED` ... and
        the permit's aggregates refresh — the certified variants now include
        the event."

        Design: Difficulty/dual_variant_calc/permit_remaining_provisional_vs_certified
        """
        plant = create_plant("Plant DV1")
        permit = create_permit(plant["id"], permit_number="SP-DV1")
        post_withdrawal_event(permit["id"], gallons=6000)
        post_withdrawal_event(permit["id"], gallons=3000, meter_start=6000)

        set_clock("2026-08-02T00:00:00Z")
        summary = run_compliance(plant["id"])
        assert summary["events_finalized"] == 2

        after = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        assert after["withdrawn_month_provisional_gallons"] == 9000
        assert after["withdrawn_month_certified_gallons"] == 9000
        # The "today" window keys on the current logical date (2026-08-02),
        # so both daily views read zero after the clock moved.
        assert after["withdrawn_today_provisional_gallons"] == 0
        assert after["withdrawn_today_certified_gallons"] == 0


class TestBottlePoolVariants:
    def _five_bottle_population(self, api):
        """Plant with a RELEASED lot and five bottles: b1 delivered, b2
        filled, b3/b4/b5 left SANITIZED."""
        s = setup_released_lot_scenario("Plant DV2", planned_units=1000,
                                        produced_units=1000, preform_units=5000)
        plant, lot = s["plant"], s["lot"]
        b1 = create_bottle(plant["id"], "B-001")
        b2 = create_bottle(plant["id"], "B-002")
        b3 = create_bottle(plant["id"], "B-003")
        b4 = create_bottle(plant["id"], "B-004")
        b5 = create_bottle(plant["id"], "B-005")
        validate_success(api.fill_bottle(b1["id"], {"lot_id": lot["id"]}, PL1))
        validate_success(api.deliver_bottle(b1["id"], SL1))
        validate_success(api.fill_bottle(b2["id"], {"lot_id": lot["id"]}, PL1))
        return plant, lot, b1, b2, b3, b4, b5

    def test_gross_pool_counts_filled_and_delivered_but_sanitized_does_not(self, api):
        """PRD §2.11: "`bottle_gross_pool_units` counts the plant's bottles
        in `SANITIZED`, `FILLED`, or `WITH_CUSTOMER` status ... while
        `bottle_sanitized_pool_units` counts bottles in `SANITIZED` status
        only".

        Design: Difficulty/dual_variant_calc/bottle_pool_gross_vs_sanitized
        """
        plant, _lot, _b1, _b2, _b3, _b4, _b5 = self._five_bottle_population(api)
        read = validate_success(api.get_plant(plant["id"], PLANT_ADMIN))
        assert read["bottle_gross_pool_units"] == 5
        assert read["bottle_sanitized_pool_units"] == 3

    def test_bottle_statuses_underlying_the_pool_divergence(self, api):
        """PRD §2.11: "whenever any bottle of the plant is `FILLED` or
        `WITH_CUSTOMER` the sanitized figure is strictly smaller than the
        gross figure. Both counters recompute on every bottle status
        mutation."

        Design: Difficulty/dual_variant_calc/bottle_pool_gross_vs_sanitized
        """
        plant, _lot, b1, b2, b3, b4, b5 = self._five_bottle_population(api)
        s1 = validate_success(api.get_bottle(b1["id"], SL1))
        s2 = validate_success(api.get_bottle(b2["id"], SL1))
        s3 = validate_success(api.get_bottle(b3["id"], SL1))
        s4 = validate_success(api.get_bottle(b4["id"], SL1))
        s5 = validate_success(api.get_bottle(b5["id"], SL1))
        assert s1["status"] == "WITH_CUSTOMER"
        assert s2["status"] == "FILLED"
        assert s3["status"] == "SANITIZED"
        assert s4["status"] == "SANITIZED"
        assert s5["status"] == "SANITIZED"


class TestDailyCapBoundary:
    def test_posting_to_exactly_the_daily_cap_is_accepted(self, api):
        """PRD §3.1: "Equality is allowed at both levels: a posting that
        brings the provisional total exactly to the cap succeeds and leaves
        zero remaining".

        Design: Difficulty/boundary_precision_check/daily_cap_exact_gallon_boundary
        """
        plant = create_plant("Plant BP1")
        permit = create_permit(plant["id"], permit_number="SP-BP1",
                               daily_cap_gallons=10000, monthly_cap_gallons=200000)
        post_withdrawal_event(permit["id"], gallons=6000)
        ev2, permit_now = post_withdrawal_event(
            permit["id"], gallons=4000, meter_start=6000
        )
        assert ev2["status"] == "RECORDED"
        assert permit_now["withdrawn_today_provisional_gallons"] == 10000

    def test_one_gallon_over_the_daily_cap_is_rejected(self, api):
        """PRD §3.1: "Equality is allowed at both levels ... and one more
        gallon beyond that fails" — with "otherwise
        `ERR_DAILY_CAP_EXCEEDED` (HTTP 409)".

        Design: Difficulty/boundary_precision_check/daily_cap_exact_gallon_boundary
        """
        plant = create_plant("Plant BP1")
        permit = create_permit(plant["id"], permit_number="SP-BP1",
                               daily_cap_gallons=10000, monthly_cap_gallons=200000)
        post_withdrawal_event(permit["id"], gallons=6000)
        _, permit_now = post_withdrawal_event(permit["id"], gallons=4000, meter_start=6000)

        payload = create_withdrawal_event_payload(
            gallons=1, meter_reading_start_gallons=10000,
            meter_reading_end_gallons=10001,
            expected_permit_version=permit_now["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_DAILY_CAP_EXCEEDED)


class TestBottleCycleLimitBoundary:
    def _two_dirty_bottles_at_counts(self, api):
        """Two RETURNED_DIRTY bottles injected to wash counts 149 and 150."""
        s = setup_released_lot_scenario("Plant BP2", planned_units=100,
                                        produced_units=100, preform_units=2000)
        plant, lot = s["plant"], s["lot"]
        b_lo = create_bottle(plant["id"], "B-LO")
        b_hi = create_bottle(plant["id"], "B-HI")
        loop_bottle_to_dirty(plant["id"], b_lo["id"], lot["id"])
        loop_bottle_to_dirty(plant["id"], b_hi["id"], lot["id"])
        lo = get_success_data(api.inject_bottle_wash_cycles(
            {"bottle_id": b_lo["id"], "wash_cycle_count": 149}, PLANT_ADMIN
        ))
        hi = get_success_data(api.inject_bottle_wash_cycles(
            {"bottle_id": b_hi["id"], "wash_cycle_count": 150}, PLANT_ADMIN
        ))
        batch = get_success_data(api.create_wash_batch(
            plant["id"],
            {"washer_unit": "WASHER_A",
             "scheduled_start": "2026-08-05T09:00:00Z",
             "scheduled_end": "2026-08-05T10:00:00Z"},
            SL1,
        ))
        return plant, lo, hi, batch

    def test_bottle_at_149_cycles_is_accepted_into_wash(self, api):
        """PRD §3.8: "each bottle's `wash_cycle_count` must still be below the
        150-wash lifecycle ceiling, otherwise `ERR_BOTTLE_CYCLE_LIMIT` (HTTP
        409)".

        Design: Difficulty/boundary_precision_check/bottle_cycle_limit_149_150_boundary
        """
        plant, lo, _hi, batch = self._two_dirty_bottles_at_counts(api)
        assert lo["wash_cycle_count"] == 149

        resp = api.assign_bottles(batch["id"], {"bottle_ids": [lo["id"]]}, SL1)
        batch_after = validate_success(resp)
        assert batch_after["bottle_count"] == 1
        bottle = validate_success(api.get_bottle(lo["id"], SL1))
        assert bottle["status"] == "IN_WASH"

    def test_bottle_at_150_cycles_is_rejected_from_wash(self, api):
        """PRD §3.8: "each bottle's `wash_cycle_count` must still be below the
        150-wash lifecycle ceiling, otherwise `ERR_BOTTLE_CYCLE_LIMIT` (HTTP
        409) and the bottle must be retired instead."

        Design: Difficulty/boundary_precision_check/bottle_cycle_limit_149_150_boundary
        """
        plant, _lo, hi, batch = self._two_dirty_bottles_at_counts(api)
        assert hi["wash_cycle_count"] == 150

        resp = api.assign_bottles(batch["id"], {"bottle_ids": [hi["id"]]}, SL1)
        validate_error(resp, ApiErrorId.ERR_BOTTLE_CYCLE_LIMIT)
        bottle = validate_success(api.get_bottle(hi["id"], SL1))
        assert bottle["status"] == "RETURNED_DIRTY"
