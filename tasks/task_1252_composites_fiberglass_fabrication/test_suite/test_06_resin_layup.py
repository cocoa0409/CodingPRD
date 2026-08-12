"""Resin batches and layup sessions: pot life, ratio gate, mass ledger, void."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_resin_mass_invariant,
    create_batch,
    create_layup_session_payload,
    record_session,
    set_clock,
    setup_shop,
    setup_work_order_in_layup,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

LAM = TEST_USERS["laminator_headers"]
SM = TEST_USERS["shop_manager_headers"]


class TestPotLifeDualVariant:
    def _setup_two_batches(self, api):
        """WO in LAYUP_IN_PROGRESS; BATCH-N nominal 60 min, BATCH-H 30 C derated."""
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-PL1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-PL1"},
        )
        batch_n = create_batch(batch_code="BATCH-N", nominal_pot_life_minutes=60)
        batch_h = create_batch(
            batch_code="BATCH-H", nominal_pot_life_minutes=60, ambient_temp_c=30.0
        )
        set_clock("2026-06-01T10:45:00Z")  # T0 + 45 minutes
        return ctx, batch_n, batch_h

    def test_nominal_batch_consumable_at_t0_plus_45(self, api):
        """PRD §3.4: "Without an ambient reading, `effective_pot_life_minutes` is
        simply `nominal_pot_life_minutes`." A 60-minute nominal batch mixed at T0 is
        still usable at T0+45.

        Design: Difficulty/dual_variant_calc/resin_pot_life_nominal_vs_temperature_adjusted
        """
        ctx, batch_n, _ = self._setup_two_batches(api)
        session = validate_success(
            api.create_layup_session(
                create_layup_session_payload(
                    ctx["work_order"]["id"], batch_n["id"], resin_used_g=250
                ),
                LAM,
            ),
            201,
        )
        assert session["status"] == "ACTIVE"
        # 250 g POLYESTER: round(250 * 0.35 * 0.10 / 1000, 4) == 0.0088 kg.
        assert session["styrene_emitted_kg"] == pytest.approx(0.0088, abs=1e-9)

    def test_temperature_adjusted_batch_expired_at_t0_plus_45(self, api):
        """PRD §3.4: "when present it must lie between -10 and 60, and it changes
        the working window: the nameplate life is multiplied by one-half raised to
        the power of the temperature difference from the 20 °C reference divided by
        10 — halving for every 10 °C above the reference, doubling for every 10 °C
        below — rounded half-up to whole minutes, and never allowed to fall below a
        floor of 5 minutes." At 30 °C the 60-minute life becomes 30 minutes, so at
        T0+45 the batch is past `expires_at`.
        PRD §3.4: "a batch already expired at consumption time produces
        `ERR_RESIN_POT_LIFE_EXPIRED`" and "Expiry is evaluated lazily: any read of
        the batch, and any attempt to consume it, first checks the clock against
        `expires_at` and moves a still-`MIXED` or `PARTIALLY_CONSUMED` batch to
        `EXPIRED` when the moment has passed."

        Design: Difficulty/dual_variant_calc/resin_pot_life_nominal_vs_temperature_adjusted
        """
        ctx, _, batch_h = self._setup_two_batches(api)
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], batch_h["id"], resin_used_g=250
            ),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_RESIN_POT_LIFE_EXPIRED, expected_status=409)
        batch_after = validate_success(api.get_resin_batch(batch_h["id"], LAM), 200)
        assert batch_after["status"] == "EXPIRED"
        assert batch_after["effective_pot_life_minutes"] == 30


class TestRatioGate:
    def test_resin_batch_rejected_at_creation_on_ratio(self, api):
        """PRD §3.4: "The computed `actual_ratio_pct` — catalyst mass divided by
        resin mass, expressed as a percentage to four decimal places — is compared
        against the target, and if the absolute difference exceeds
        `ratio_tolerance_pct` the batch is born `REJECTED`: creation still succeeds,
        but the batch can never be consumed, answering every consumption attempt
        with `ERR_RESIN_BATCH_NOT_USABLE`."

        Design: Corner/entities/resin_batch_rejected_at_creation_on_ratio
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-D4", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-D4"},
        )
        batch = create_batch(
            batch_code="BATCH-D4",
            resin_mass_g=1000,
            catalyst_mass_g=100,
            target_ratio_pct=2.0,
            ratio_tolerance_pct=1.0,
            nominal_pot_life_minutes=60,
        )
        assert batch["status"] == "REJECTED"
        assert batch["actual_ratio_pct"] == pytest.approx(10.0, abs=1e-9)
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], batch["id"], resin_used_g=100
            ),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_RESIN_BATCH_NOT_USABLE, expected_status=409)


class TestPotLifeBoundary:
    def test_pot_life_consumption_exactly_at_expiry_succeeds(self, api):
        """PRD §3.4: "Either way, the batch stamps `mixed_at` from the logical clock
        and computes `expires_at` as `mixed_at` plus the effective minutes; a batch
        counts as expired only when the current logical time is strictly later than
        `expires_at`, so at the exact expiry instant it remains usable."

        Design: Corner/calculations/pot_life_consumption_exactly_at_expiry_succeeds
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-EB1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-EB1"},
            batch_overrides={"batch_code": "BATCH-EB1", "nominal_pot_life_minutes": 60},
        )
        set_clock("2026-06-01T11:00:00Z")  # exactly T0 + 60 min == expires_at
        session = validate_success(
            api.create_layup_session(
                create_layup_session_payload(
                    ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=100
                ),
                LAM,
            ),
            201,
        )
        assert session["status"] == "ACTIVE"


class TestMassGate:
    def test_consume_beyond_remaining_rejected(self, api):
        """PRD §3.4: "declaring the `resin_used_g` applied — strictly positive and
        no greater than the batch's `remaining_mass_g`, with overdraws refused as
        `ERR_RESIN_MASS_INSUFFICIENT`."

        Design: Corner/errors/consume_beyond_remaining_rejected
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-MS1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-MS1"},
            batch_overrides={"batch_code": "BATCH-MS1"},
        )
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=2000
            ),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_RESIN_MASS_INSUFFICIENT, expected_status=409)
        batch = validate_success(api.get_resin_batch(ctx["batch"]["id"], LAM), 200)
        assert batch["remaining_mass_g"] == pytest.approx(1020.0)
        assert batch["status"] == "MIXED"

    def test_batch_exhausted_at_exact_zero_then_rejected(self, api):
        """PRD §3.4: "a session that consumes the last gram exactly moves it to
        `EXHAUSTED`", and "a `REJECTED`, `EXHAUSTED`, `EXPIRED`, or `QUENCHED`
        batch produces `ERR_RESIN_BATCH_NOT_USABLE`".

        Design: Corner/errors/batch_exhausted_at_exact_zero_then_rejected
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-EX1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-EX1"},
            batch_overrides={
                "batch_code": "BATCH-EX1",
                "resin_mass_g": 400,
                "catalyst_mass_g": 8,
            },
        )
        session = validate_success(
            api.create_layup_session(
                create_layup_session_payload(
                    ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=408
                ),
                LAM,
            ),
            201,
        )
        assert session["status"] == "ACTIVE"
        batch = validate_success(api.get_resin_batch(ctx["batch"]["id"], LAM), 200)
        assert batch["remaining_mass_g"] == pytest.approx(0.0)
        assert batch["status"] == "EXHAUSTED"
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=1
            ),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_RESIN_BATCH_NOT_USABLE, expected_status=409)


class TestQuenchGate:
    def _setup_quenched(self, api):
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-G3", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-G3"},
            batch_overrides={"batch_code": "BATCH-G3"},
        )
        quenched = validate_success(api.quench_resin_batch(ctx["batch"]["id"], LAM), 200)
        return ctx, quenched

    def test_quenched_batch_rejects_consumption(self, api):
        """PRD §3.4: "the batch must be consumable, meaning `MIXED` or
        `PARTIALLY_CONSUMED` and not past `expires_at`" and "a `REJECTED`,
        `EXHAUSTED`, `EXPIRED`, or `QUENCHED` batch produces
        `ERR_RESIN_BATCH_NOT_USABLE`".

        Design: Difficulty/cross_entity_state_dependency/layup_session_gated_on_batch_consumable
        """
        ctx, _ = self._setup_quenched(api)
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=100
            ),
            LAM,
        )
        validate_error(res, ApiErrorId.ERR_RESIN_BATCH_NOT_USABLE, expected_status=409)

    def test_quench_freezes_remaining_mass(self, api):
        """PRD §3.4: "A `Laminator` may also dispose of a live batch by quenching
        it, which moves it to `QUENCHED`, freezes the then-remaining mass into
        `quenched_mass_g`, and drives `remaining_mass_g` to 0."

        Design: Difficulty/cross_entity_state_dependency/layup_session_gated_on_batch_consumable
        """
        _, quenched = self._setup_quenched(api)
        assert quenched["status"] == "QUENCHED"
        assert quenched["quenched_mass_g"] == pytest.approx(1020.0)
        assert quenched["remaining_mass_g"] == pytest.approx(0.0)
        assert_resin_mass_invariant(quenched)


class TestMassConservationAcrossVoid:
    def _setup_voided(self, api):
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-V1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-V1"},
            batch_overrides={"batch_code": "BATCH-V1"},
        )
        session = record_session(ctx, 300)
        return ctx, session

    def test_session_debits_batch_mass(self, api):
        """PRD §3.4: "Mass bookkeeping derives `total_mass_g` as the sum of the two
        components, `consumed_mass_g` starting at 0, and `remaining_mass_g` as the
        total minus consumed minus `quenched_mass_g`." and "the batch's
        `consumed_mass_g` grows by `resin_used_g`"; "a session that leaves the batch
        with resin still on hand moves it from `MIXED` to `PARTIALLY_CONSUMED`".

        Design: Difficulty/compensating_invariant/resin_mass_conservation_across_void
        """
        ctx, _ = self._setup_voided(api)
        batch = validate_success(api.get_resin_batch(ctx["batch"]["id"], LAM), 200)
        assert batch["consumed_mass_g"] == pytest.approx(300.0)
        assert batch["remaining_mass_g"] == pytest.approx(720.0)
        assert batch["status"] == "PARTIALLY_CONSUMED"
        assert_resin_mass_invariant(batch)

    def test_void_restores_batch_mass_exactly(self, api):
        """PRD §3.4: "the batch's `consumed_mass_g` is reduced and its
        `remaining_mass_g` increased by exactly the session's `resin_used_g`, with
        the batch status recomputed so that a full remaining mass returns it to
        `MIXED` and a partial one to `PARTIALLY_CONSUMED`".

        Design: Difficulty/compensating_invariant/resin_mass_conservation_across_void
        """
        ctx, session = self._setup_voided(api)
        validate_success(api.void_layup_session(session["id"], SM), 200)
        batch = validate_success(api.get_resin_batch(ctx["batch"]["id"], LAM), 200)
        assert batch["consumed_mass_g"] == pytest.approx(0.0)
        assert batch["remaining_mass_g"] == pytest.approx(1020.0)
        assert batch["quenched_mass_g"] == pytest.approx(0.0)
        assert batch["status"] == "MIXED"
        assert_resin_mass_invariant(batch)


class TestVoidOnQuenchedBatch:
    def test_void_session_on_quenched_batch_rejected(self, api):
        """PRD §3.4: "A `ShopManager` may void an `ACTIVE` session, moving it to the
        terminal `VOIDED` state — provided the session's batch has not been
        `QUENCHED`, since disposed mass cannot be returned and such an attempt is
        refused with `ERR_INVALID_STATE`."

        Design: Corner/errors/void_session_on_quenched_batch_rejected
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-VQ1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-VQ1"},
            batch_overrides={"batch_code": "BATCH-VQ1"},
        )
        session = record_session(ctx, 100)
        quenched = validate_success(api.quench_resin_batch(ctx["batch"]["id"], LAM), 200)
        assert quenched["status"] == "QUENCHED"
        res = api.void_layup_session(session["id"], SM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestImmediateConsistency:
    def test_read_after_write_immediate_remaining_mass(self, api):
        """PRD §2.4: "Because derived recomputation is immediate, a single client
        request that cascades into another resource — a layup session advancing a
        permit's consumption, a completed cure cycle advancing a mold's wear
        counter — also refreshes that resource's `updated_at` and `version`."
        PRD §3.4: "A three-link cascade follows immediately: the batch's
        `consumed_mass_g` grows by `resin_used_g`".

        Design: Corner/consistency_model/read_after_write_immediate_remaining_mass
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-IM1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-IM1"},
            batch_overrides={"batch_code": "BATCH-IM1"},
        )
        record_session(ctx, 300)
        batch = validate_success(api.get_resin_batch(ctx["batch"]["id"], SM), 200)
        assert batch["remaining_mass_g"] == pytest.approx(720.0)
        assert batch["consumed_mass_g"] == pytest.approx(300.0)
