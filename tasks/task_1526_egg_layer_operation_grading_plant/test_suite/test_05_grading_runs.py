"""Grading runs: pool gates, size-distribution sum, lot materialization, void."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_egg_lot,
    get_flock,
    grading_submit_payload,
    setup_confirmed_lot,
    setup_laying_flock_with_production,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    GRADER,
    QA_MANAGER,
    api_client,
    confirm_grading_run,
    lots_of_run,
)


class TestGradingRunGates:
    def test_grading_run_overdraws_ungraded_pool_rejected(self, api):
        """PRD §3.4: "A `QualityGrader` opens a **GradingRun** with the
        `flock_id`, a whole-run `grade` of `AA`, `A`, or `B`, and
        `eggs_to_grade` — the number of eggs to draw from the flock's
        `ungraded_egg_pool`, greater than zero and no more than the pool, else
        `ERR_INSUFFICIENT_UNGRADED_EGGS` (HTTP 422)"

        Design: Corner/validations/grading_run_overdraws_ungraded_pool_rejected
        """
        ctx = setup_laying_flock_with_production(
            [{"lay_date": "2026-07-31", "eggs_collected": 240}]
        )
        resp = api.create_grading_run(
            {"flock_id": ctx["flock"]["id"], "grade": "A", "eggs_to_grade": 500},
            GRADER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UNGRADED_EGGS)
        assert get_flock(ctx["flock"]["id"])["ungraded_egg_pool"] == 240, (
            "the pool ledger must be untouched by a rejected run"
        )

    def test_submit_distribution_not_summing_rejected(self, api):
        """PRD §3.4: "The nine counts must sum exactly to `eggs_to_grade`; any
        other total is rejected with `ERR_SIZE_DISTRIBUTION_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/submit_distribution_not_summing_rejected
        """
        ctx = setup_laying_flock_with_production(
            [{"lay_date": "2026-07-31", "eggs_collected": 240}]
        )
        run = validate_success(
            api.create_grading_run(
                {"flock_id": ctx["flock"]["id"], "grade": "A", "eggs_to_grade": 240},
                GRADER,
            ),
            201,
        )
        counts = grading_submit_payload(large_count=240, cracked_count=1)  # sums 241
        resp = api.submit_grading_run(run["id"], counts, GRADER)
        validate_error(resp, ApiErrorId.ERR_SIZE_DISTRIBUTION_MISMATCH)
        assert api.get_grading_run(run["id"], QA_MANAGER).json()["data"]["status"] == "DRAFT"

    def test_grading_double_submit_rejected(self, api):
        """PRD §2.8: "Tier 6 is the target entity's own state machine — the
        requested transition must be permitted from its current state, else
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.4: "The grader then submits the candling results, moving the
        run from `DRAFT` to `SUBMITTED`." (no SUBMITTED -> SUBMITTED edge
        exists)

        Design: Corner/state_machines/grading_double_submit_rejected
        """
        ctx = setup_laying_flock_with_production(
            [{"lay_date": "2026-07-31", "eggs_collected": 240}]
        )
        run = validate_success(
            api.create_grading_run(
                {"flock_id": ctx["flock"]["id"], "grade": "A", "eggs_to_grade": 240},
                GRADER,
            ),
            201,
        )
        counts = grading_submit_payload(large_count=240)
        validate_success(api.submit_grading_run(run["id"], counts, GRADER))
        resp = api.submit_grading_run(run["id"], counts, GRADER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert api.get_grading_run(run["id"], QA_MANAGER).json()["data"]["status"] == "SUBMITTED"


class TestLotMaterialization:
    def test_lot_initial_state_after_confirm(self, api):
        """PRD §3.4: "For each size class, the class count divided by 12 and
        rounded down gives the whole dozens; when that dozen figure is greater
        than zero an **EggLot** is created carrying that `size_class`, the
        run's `grade`, the computed `dozen_count`, a `claim_program`
        snapshotted from the farm's `certification_program` at that moment,
        the run's `pack_date`, and a `sell_by_date` computed as `pack_date`
        plus the shelf life for the claim program — 45 days for
        `CONVENTIONAL`, 30 days for `CAGE_FREE`, and 30 days for `PASTURE`."
        PRD §3.4: "Each new lot starts with `lifecycle_status` `FRESH` and
        `hold_status` `CLEAR`"

        Design: Corner/state_machines/lot_initial_state_after_confirm
        """
        ctx = setup_confirmed_lot(grade="AA", eggs_to_grade=240)
        assert len(ctx["lots"]) == 1
        lot = ctx["lots"][0]
        assert_egg_lot(lot)
        assert lot["lifecycle_status"] == "FRESH"
        assert lot["hold_status"] == "CLEAR"
        assert lot["grade"] == "AA"
        assert lot["size_class"] == "LARGE"
        assert lot["dozen_count"] == 20
        assert lot["pack_date"][:10] == "2026-08-01", (
            f"pack_date must stamp the startup clock date, got {lot['pack_date']!r}"
        )
        assert lot["sell_by_date"][:10] == "2026-09-15", (
            f"CONVENTIONAL shelf life is 45 days: 2026-08-01 + 45 = 2026-09-15, "
            f"got {lot['sell_by_date']!r}"
        )
        assert lot["claim_program"] == "CONVENTIONAL"

    def test_loose_egg_remainder_from_sub_dozen_counts(self, api):
        """PRD §3.4: "For each size class, the class count divided by 12 and
        rounded down gives the whole dozens; when that dozen figure is greater
        than zero an **EggLot** is created"
        PRD §3.4: "The remainder eggs of each class — the class count modulo
        12 — flow into the flock's `loose_egg_pool`, while the flock's
        `ungraded_egg_pool` falls by the full `eggs_to_grade`, keeping the egg
        ledger of §2.10 conserved."

        Design: Corner/calculations/loose_egg_remainder_from_sub_dozen_counts
        """
        ctx = setup_confirmed_lot(
            production_days=[
                {"lay_date": "2026-07-31", "eggs_collected": 250, "rejected_eggs": 0}
            ],
            eggs_to_grade=250,
            submit_counts=grading_submit_payload(large_count=250),
        )
        assert len(ctx["lots"]) == 1, "only the LARGE class produced dozens"
        assert ctx["lots"][0]["dozen_count"] == 20, (
            f"floor(250/12) = 20 dozen, got {ctx['lots'][0]['dozen_count']}"
        )
        flock = get_flock(ctx["flock"]["id"])
        assert flock["loose_egg_pool"] == 10, (
            f"250 mod 12 = 10 loose eggs, got {flock['loose_egg_pool']}"
        )
        assert flock["ungraded_egg_pool"] == 0


class TestGradingVoidCompensation:
    def _setup_confirmed_480(self, api):
        """500 eggs / 20 rejects -> pool 480; confirmed run of 480 with
        240 LARGE + 216 JUMBO + 24 undergrades."""
        ctx = setup_confirmed_lot(
            production_days=[
                {
                    "lay_date": "2026-07-31",
                    "eggs_collected": 500,
                    "rejected_eggs": 20,
                    "feed_issued_kg": 0,
                    "mortality_count": 0,
                }
            ],
            eggs_to_grade=480,
            submit_counts=grading_submit_payload(
                large_count=240, jumbo_count=216,
                cracked_count=12, dirty_count=8, blood_spot_count=4,
            ),
        )
        return ctx

    def test_grading_confirm_then_void_preserves_gradable_egg_balance(self, api):
        """PRD §2.10: "for any flock, the sum of `eggs_collected` minus
        `rejected_eggs` across its production days always equals
        `ungraded_egg_pool` plus the sum of `eggs_to_grade` across the flock's
        confirmed, non-voided grading runs. Confirming a run deducts its draw
        from the pool; voiding a confirmed run returns exactly that draw (and
        reclaims the loose remainders it released); net drift must be zero."

        Design: Difficulty/compensating_invariant/grading_confirm_then_void_preserves_gradable_egg_balance
        """
        ctx = self._setup_confirmed_480(api)
        flock = get_flock(ctx["flock"]["id"])
        assert flock["ungraded_egg_pool"] == 0, (
            f"confirm of 480 must drain the pool to 0, got "
            f"{flock['ungraded_egg_pool']}"
        )
        # Egg ledger: 500 collected - 20 rejected == pool 0 + 480 confirmed.
        assert 500 - 20 == flock["ungraded_egg_pool"] + 480

        validate_success(api.void_grading_run(ctx["run"]["id"], QA_MANAGER))
        flock = get_flock(ctx["flock"]["id"])
        assert flock["ungraded_egg_pool"] == 480, (
            f"the compensating void must return exactly 480, got "
            f"{flock['ungraded_egg_pool']}"
        )
        # Egg ledger restored: the run is VOIDED so the second term is zero.
        assert 500 - 20 == flock["ungraded_egg_pool"] + 0

    def test_grading_void_returns_draw_and_expires_lots(self, api):
        """PRD §3.4: "The compensation walks every child lot still in `FRESH`,
        `RELEASED`, or `ALLOCATED` and moves it to `EXPIRED`"
        PRD §3.4: "The full `eggs_to_grade` draw returns to the flock's
        `ungraded_egg_pool`, and the loose remainders the run released — the
        sum, over the six size counts, of each count modulo 12 — are deducted
        back out of `loose_egg_pool`."

        Design: Difficulty/compensating_invariant/grading_confirm_then_void_preserves_gradable_egg_balance
        """
        ctx = self._setup_confirmed_480(api)
        assert len(ctx["lots"]) == 2  # JUMBO 18 dozen + LARGE 20 dozen

        voided = validate_success(api.void_grading_run(ctx["run"]["id"], QA_MANAGER))
        assert voided["status"] == "VOIDED"

        lots = lots_of_run(ctx["run"]["id"])
        assert {lot["lifecycle_status"] for lot in lots} == {"EXPIRED"}, (
            "both child lots must be compensated to EXPIRED"
        )
        flock = get_flock(ctx["flock"]["id"])
        assert flock["ungraded_egg_pool"] == 480
        assert flock["loose_egg_pool"] == 0, (
            "loose remainders (240 mod 12 = 0, 216 mod 12 = 0) stay at 0"
        )
