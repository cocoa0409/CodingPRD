"""Spent-hen dispositions, the hen ledger, and house/flock turnover."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_hen_ledger,
    complete_disposition,
    disposition_payload,
    get_flock,
    record_production_days,
    run_daily_ops,
    set_clock,
    setup_depopulating_flock,
    setup_laying_flock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    FARM_MANAGER,
    api_client,
    get_disposition,
    get_house,
    place_flock,
)


class TestFinalDispositionCascade:
    def test_final_disposition_cascades_flock_depleted_house_cleaning(self, api):
        """PRD §3.9: "When the deduction brings `current_hen_count` to exactly
        zero, the flock automatically moves from `DEPOPULATING` to `DEPLETED`
        — the first cascade link — and its house moves from `DEPOPULATING` to
        `CLEANING` with `status_changed_date` stamped and `current_flock_id`
        cleared, the second cascade link."

        Design: Difficulty/transitive_cascade/final_disposition_cascades_flock_depleted_house_cleaning
        """
        ctx = setup_depopulating_flock()
        disp = complete_disposition(
            ctx["flock"]["id"], 1000, method="RENDERING", revenue_cents=5000
        )
        assert disp["status"] == "COMPLETED"

        flock = get_flock(ctx["flock"]["id"])
        assert flock["status"] == "DEPLETED", "hen count at zero must auto-deplete"
        assert flock["current_hen_count"] == 0
        house = get_house(ctx["house"]["id"])
        assert house["status"] == "CLEANING"
        assert house["current_flock_id"] is None

    def test_final_disposition_marks_depleted_date_and_keeps_hen_ledger(self, api):
        """PRD §3.2: "Reaching `DEPLETED` stamps `depleted_date` to the clock
        date, cascades the house from `DEPOPULATING` to `CLEANING` with
        `status_changed_date` restamped, clears the house's `current_flock_id`
        to null, and increments the flock's `version` by 1."
        PRD §2.10: "for any flock, `initial_hen_count` always equals
        `current_hen_count` plus the sum of `mortality_count` across the
        flock's production days plus the sum of `hen_count` across the flock's
        completed, non-voided dispositions."

        Design: Difficulty/transitive_cascade/final_disposition_cascades_flock_depleted_house_cleaning
        """
        ctx = setup_depopulating_flock()
        complete_disposition(
            ctx["flock"]["id"], 1000, method="RENDERING", revenue_cents=5000
        )
        flock = get_flock(ctx["flock"]["id"])
        assert flock["depleted_date"][:10] == "2026-08-01", (
            f"depleted_date must stamp the clock date, got {flock['depleted_date']!r}"
        )
        assert_hen_ledger(flock, completed_disposition_hens=1000)
        house = get_house(ctx["house"]["id"])
        assert house["status_changed_date"][:10] == "2026-08-01"


class TestHenLedgerCompensation:
    def _setup_mortality_and_disposition(self, api):
        """LAYING flock of 1000 with one 3-mortality production day (current
        997), depopulated, with a PLANNED 200-hen disposition."""
        ctx = setup_laying_flock()
        record_production_days(
            ctx["flock"]["id"],
            [
                {
                    "lay_date": "2026-07-31",
                    "eggs_collected": 100,
                    "rejected_eggs": 0,
                    "feed_issued_kg": 0,
                    "mortality_count": 3,
                }
            ],
        )
        validate_success(api.depopulate_flock(ctx["flock"]["id"], FARM_MANAGER))
        disp = validate_success(
            api.create_disposition(
                disposition_payload(
                    ctx["flock"]["id"], method="LIVE_SALE", hen_count=200,
                    revenue_cents=1000,
                ),
                FARM_MANAGER,
            ),
            201,
        )
        return ctx, disp

    def test_disposition_complete_then_void_preserves_hen_balance(self, api):
        """PRD §2.10: "for any flock, `initial_hen_count` always equals
        `current_hen_count` plus the sum of `mortality_count` across the
        flock's production days plus the sum of `hen_count` across the flock's
        completed, non-voided dispositions. Completing a disposition deducts
        hens; voiding a completed disposition restores exactly the same hens;
        net drift must be zero."

        Design: Difficulty/compensating_invariant/disposition_complete_then_void_preserves_hen_balance
        """
        ctx, disp = self._setup_mortality_and_disposition(api)
        validate_success(api.complete_disposition(disp["id"], FARM_MANAGER))
        flock = get_flock(ctx["flock"]["id"])
        assert flock["current_hen_count"] == 797  # 997 - 200
        assert_hen_ledger(flock, completed_disposition_hens=200)  # 1000 == 797+3+200

        voided = validate_success(api.void_disposition(disp["id"], FARM_MANAGER))
        assert voided["status"] == "VOIDED"
        flock = get_flock(ctx["flock"]["id"])
        assert flock["current_hen_count"] == 997, (
            f"the compensating void restores exactly 200 hens, got "
            f"{flock['current_hen_count']}"
        )
        assert_hen_ledger(flock, completed_disposition_hens=0)  # 1000 == 997+3+0

    def test_disposition_void_restores_hens_exactly(self, api):
        """PRD §3.9: "Voiding is the exact compensation: `hen_count` is added
        back to the flock's `current_hen_count`, the disposition's
        `revenue_cents` is withdrawn from the spent-hen credit, the
        disposition moves to terminal `VOIDED`, and both versions increment
        by 1."
        PRD §2.10: "Completing a disposition deducts hens; voiding a completed
        disposition restores exactly the same hens; net drift must be zero."

        Design: Difficulty/compensating_invariant/disposition_complete_then_void_preserves_hen_balance
        """
        ctx, disp = self._setup_mortality_and_disposition(api)
        completed = validate_success(api.complete_disposition(disp["id"], FARM_MANAGER))
        assert completed["status"] == "COMPLETED"
        flock_mid = get_flock(ctx["flock"]["id"])

        voided = validate_success(api.void_disposition(disp["id"], FARM_MANAGER))
        assert voided["status"] == "VOIDED"
        flock_end = get_flock(ctx["flock"]["id"])
        assert flock_end["current_hen_count"] == flock_mid["current_hen_count"] + 200
        assert flock_end["current_hen_count"] == 997
        # Zero net drift across the complete/void pair.
        assert flock_end["initial_hen_count"] == (
            flock_end["current_hen_count"] + flock_end["cumulative_mortality"]
        )


class TestDispositionVoidGate:
    def test_disposition_void_blocked_once_flock_depleted(self, api):
        """PRD §3.9: "A completed disposition can still be voided by a
        `FarmManager` — but only while the flock has not yet reached
        `DEPLETED`, because hens cannot return to a depleted flock; the
        attempt otherwise is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/disposition_void_blocked_once_flock_depleted
        """
        ctx = setup_depopulating_flock()
        disp = complete_disposition(ctx["flock"]["id"], 1000, method="COMPOST")
        assert get_flock(ctx["flock"]["id"])["status"] == "DEPLETED"

        resp = api.void_disposition(disp["id"], FARM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_disposition(disp["id"])["status"] == "COMPLETED"
        assert get_flock(ctx["flock"]["id"])["status"] == "DEPLETED"


class TestHouseTurnover:
    def test_house_turnover_cycle_and_prior_flock_link(self, api):
        """PRD §3.9: "A house in `CLEANING` moves to `RESTING` once the clock
        date is at least 7 days after its `status_changed_date`; a house in
        `RESTING` moves back to `EMPTY` once the clock date is at least 14
        days after its `status_changed_date`."
        PRD §3.1: "Placement also links the flock's self-referential
        `prior_flock_id` to the house's most recently depleted flock —
        selected as the house's flock in `DEPLETED` status with the latest
        `depleted_date`, ties broken by the earliest `created_at` — or leaves
        it null for the house's first flock, which is how the system expresses
        flock turnover inside a house."
        PRD §3.9: "Back at `EMPTY`, the house is eligible for the next
        placement — and that next flock's `prior_flock_id` will link back to
        the flock just depleted"

        Design: Corner/state_machines/house_turnover_cycle_and_prior_flock_link
        """
        ctx = setup_depopulating_flock()
        flock1_id = ctx["flock"]["id"]
        complete_disposition(flock1_id, 1000, method="RENDERING", revenue_cents=5000)
        # House entered CLEANING at the 2026-08-01 clock date.
        assert get_house(ctx["house"]["id"])["status"] == "CLEANING"

        set_clock("2026-08-08T00:00:00Z")  # exactly 7 cleaning days
        run_daily_ops()
        assert get_house(ctx["house"]["id"])["status"] == "RESTING"

        set_clock("2026-08-22T00:00:00Z")  # exactly 14 resting days
        run_daily_ops()
        house = get_house(ctx["house"]["id"])
        assert house["status"] == "EMPTY"

        flock2 = validate_success(
            api.create_flock(
                {
                    "house_id": ctx["house"]["id"],
                    "breed_code": "ISA_WHITE",
                    "breed_peak_rate_pct": 94.0,
                    "placement_date": "2026-08-22",
                    "initial_hen_count": 900,
                    "pullet_cost_cents": 378000,
                },
                FARM_MANAGER,
            ),
            201,
        )
        assert flock2["status"] == "PLACED"
        assert flock2["prior_flock_id"] == flock1_id, (
            "the turnover placement must link back to the depleted flock"
        )
        house = get_house(ctx["house"]["id"])
        assert house["status"] == "OCCUPIED"
        assert house["current_flock_id"] == flock2["id"]
