"""Emission permits: creation, closure, styrene accounting, quota cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_emission_permit,
    create_emission_permit_payload,
    create_layup_session_payload,
    create_ply_book_payload,
    record_session,
    set_clock,
    setup_shop,
    setup_work_order_in_layup,
    validate_error,
    validate_success,
)


class TestPermitCreation:
    def test_permit_create_computed_styrene_used_input_ignored(self, api, ehs_officer_headers):
        """PRD §3.1: "The permit is born `ACTIVE` with `styrene_used_kg` at 0.0."
        A client-supplied styrene_used_kg is not among the accepted inputs, so the
        computed field initializes to 0.0 regardless.

        Design: Corner/entities/permit_create_computed_styrene_used_input_ignored
        """
        payload = create_emission_permit_payload(permit_code="PER-D3")
        payload["styrene_used_kg"] = 99.0
        permit = validate_success(api.create_emission_permit(payload, ehs_officer_headers), 201)
        assert_emission_permit(permit)
        assert permit["styrene_used_kg"] == 0.0
        assert permit["status"] == "ACTIVE"


class TestPermitClosure:
    def test_closed_permit_rejects_second_close(self, api, ehs_officer_headers):
        """PRD §3.1: "Closure is a deliberate, terminal act by an `EHSOfficer`,
        available from either `ACTIVE` or `EXHAUSTED`; attempting to close a permit
        that is already `CLOSED` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/closed_permit_rejects_second_close
        """
        permit = validate_success(
            api.create_emission_permit(
                create_emission_permit_payload(permit_code="PER-CL1"), ehs_officer_headers
            ),
            201,
        )
        closed = validate_success(
            api.close_emission_permit(permit["id"], ehs_officer_headers), 200
        )
        assert closed["status"] == "CLOSED"
        res = api.close_emission_permit(permit["id"], ehs_officer_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestStyreneRounding:
    def test_per_session_rounding_applied_first(self, api):
        """PRD §2.8: "per-session rounding happens first, and the aggregate is a sum
        of already-rounded values, never a recomputation from raw masses."
        PRD §3.4: "Its `styrene_emitted_kg` is computed as the session's `resin_used_g`
        multiplied by the styrene content fraction of the batch's chemistry — 0.35 for
        `POLYESTER`, 0.40 for `VINYL_ESTER`, and 0.0 for `EPOXY` — multiplied by the
        emission factor 0.10 and divided by 1000 to yield kilograms, rounded half-up to
        four decimal places before any aggregation."

        Design: Difficulty/combinatorial_formula/styrene_round_per_session_then_sum
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-S1"},
            work_order_overrides={"work_order_no": "WO-S1", "quantity": 2},
            batch_overrides={"batch_code": "BATCH-S1"},
        )
        sess1 = record_session(ctx, 250)
        sess2 = record_session(ctx, 250)
        # 250 * 0.35 * 0.10 / 1000 = 0.00875 -> round-half-up 4 decimals -> 0.0088
        assert sess1["styrene_emitted_kg"] == pytest.approx(0.0088, abs=1e-9)
        assert sess2["styrene_emitted_kg"] == pytest.approx(0.0088, abs=1e-9)

    def test_permit_aggregate_is_sum_of_rounded_sessions(self, api, ehs_officer_headers):
        """PRD §2.8: "Consumption accumulates into the computed `styrene_used_kg`,
        which is always the sum of the stored per-session `styrene_emitted_kg` values
        of the sessions in `ACTIVE` status posted to that permit — per-session rounding
        happens first, and the aggregate is a sum of already-rounded values, never a
        recomputation from raw masses."
        Two 250 g POLYESTER sessions post 0.0088 each; the permit must read 0.0176,
        not the 0.0175 a round-after-sum order would produce.

        Design: Difficulty/combinatorial_formula/styrene_round_per_session_then_sum
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-S1"},
            work_order_overrides={"work_order_no": "WO-S1", "quantity": 2},
            batch_overrides={"batch_code": "BATCH-S1"},
        )
        record_session(ctx, 250)
        record_session(ctx, 250)
        permit = validate_success(
            api.get_emission_permit(ctx["permit"]["id"], ehs_officer_headers), 200
        )
        assert permit["styrene_used_kg"] == pytest.approx(0.0176, abs=1e-9)


class TestPermitExhaustionCascade:
    def _setup_tiny_permit(self, api):
        return setup_work_order_in_layup(
            permit_overrides={"permit_code": "PER-TINY", "styrene_quota_kg": 0.0176},
            mold_overrides={"mold_code": "MOLD-X1"},
            work_order_overrides={"work_order_no": "WO-X1"},
            batch_overrides={"batch_code": "BATCH-X1"},
        )

    def test_posting_reaching_quota_exactly_flips_permit_exhausted(self, api, ehs_officer_headers):
        """PRD §2.8: "A permit whose usage reaches its quota flips automatically from
        `ACTIVE` to `EXHAUSTED`; equality counts, and the session whose posting reaches
        the quota exactly still succeeds, because admission is judged on the
        post-addition total not exceeding the quota."
        PRD §3.4: "the batch's `consumed_mass_g` grows by `resin_used_g`; the permit's
        `styrene_used_kg` grows by the session's stored emission; and if that posting
        pushes the permit to or beyond its quota, the permit flips to `EXHAUSTED`."

        Design: Difficulty/transitive_cascade/layup_session_to_permit_exhaustion_cascade
        """
        ctx = self._setup_tiny_permit(api)
        record_session(ctx, 250)
        record_session(ctx, 250)
        permit = validate_success(
            api.get_emission_permit(ctx["permit"]["id"], ehs_officer_headers), 200
        )
        assert permit["styrene_used_kg"] == pytest.approx(0.0176, abs=1e-9)
        assert permit["status"] == "EXHAUSTED"
        batch = validate_success(api.get_resin_batch(ctx["batch"]["id"], ehs_officer_headers), 200)
        assert batch["remaining_mass_g"] == pytest.approx(520.0, abs=1e-9)

    def test_exhausted_permit_gates_further_sessions(self, api):
        """PRD §2.8: "An `EXHAUSTED` permit is no longer chosen by the permit
        selector, so later work fails until another permit covers the period."
        PRD §3.4: "an `ACTIVE` permit must cover the current time
        (`ERR_NO_ACTIVE_PERMIT`)".

        Design: Difficulty/transitive_cascade/layup_session_to_permit_exhaustion_cascade
        """
        ctx = self._setup_tiny_permit(api)
        record_session(ctx, 250)
        record_session(ctx, 250)
        res = api.create_layup_session(
            create_layup_session_payload(
                ctx["work_order"]["id"], ctx["batch"]["id"], resin_used_g=100
            ),
            TEST_LAM,
        )
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_PERMIT, expected_status=409)


class TestEpoxyZeroEmission:
    def test_styrene_epoxy_zero_emission(self, api, ehs_officer_headers):
        """PRD §3.4: "Its `styrene_emitted_kg` is computed as the session's
        `resin_used_g` multiplied by the styrene content fraction of the batch's
        chemistry — 0.35 for `POLYESTER`, 0.40 for `VINYL_ESTER`, and 0.0 for `EPOXY`
        — multiplied by the emission factor 0.10 and divided by 1000 to yield
        kilograms, rounded half-up to four decimal places before any aggregation."

        Design: Corner/calculations/styrene_epoxy_zero_emission
        """
        ctx = setup_work_order_in_layup(
            mold_overrides={"mold_code": "MOLD-EP1", "tooling_phase": "PRODUCTION"},
            ply_book_overrides={
                "part_number": "PN-300",
                "part_area_m2": 1.0,
                "plies": [
                    {
                        "seq": 1,
                        "material_code": "GF-450",
                        "orientation_deg": 0,
                        "areal_weight_g_m2": 450,
                    }
                ],
                "resin_system": "EPOXY",
            },
            work_order_overrides={"work_order_no": "WO-EP1", "part_number": "PN-300"},
            batch_overrides={
                "batch_code": "BATCH-EP1",
                "resin_system": "EPOXY",
                "resin_mass_g": 1000,
                "catalyst_mass_g": 500,
                "target_ratio_pct": 50.0,
                "ratio_tolerance_pct": 2.0,
            },
        )
        session = record_session(ctx, 250)
        assert session["styrene_emitted_kg"] == 0.0
        permit = validate_success(
            api.get_emission_permit(ctx["permit"]["id"], ehs_officer_headers), 200
        )
        assert permit["styrene_used_kg"] == 0.0


class TestEmissionLedgerVoid:
    def _setup_session(self, api):
        ctx = setup_work_order_in_layup(
            permit_overrides={"permit_code": "PER-V2"},
            mold_overrides={"mold_code": "MOLD-V2"},
            work_order_overrides={"work_order_no": "WO-V2"},
            batch_overrides={"batch_code": "BATCH-V2"},
        )
        session = record_session(ctx, 250)
        return ctx, session

    def test_session_posts_stored_emission_to_selected_permit(self, api, ehs_officer_headers):
        """PRD §3.4: "the permit's `styrene_used_kg` grows by the session's stored
        emission". The session resolves to the ACTIVE permit covering the logical
        time and posts its stored 0.0088 kg there.

        Design: Difficulty/compensating_invariant/emission_ledger_void_restores_exactly
        """
        ctx, session = self._setup_session(api)
        assert session["styrene_emitted_kg"] == pytest.approx(0.0088, abs=1e-9)
        assert session["permit_id"] == ctx["permit"]["id"]
        permit = validate_success(
            api.get_emission_permit(ctx["permit"]["id"], ehs_officer_headers), 200
        )
        assert permit["styrene_used_kg"] == pytest.approx(0.0088, abs=1e-9)

    def test_void_subtracts_stored_emission_exactly(self, api, ehs_officer_headers, shop_manager_headers):
        """PRD §3.4: "the permit's `styrene_used_kg` is reduced by exactly the
        session's stored `styrene_emitted_kg`, never a recomputed value, with an
        `EXHAUSTED` permit returning to `ACTIVE` if the subtraction brings usage
        back below quota."

        Design: Difficulty/compensating_invariant/emission_ledger_void_restores_exactly
        """
        ctx, session = self._setup_session(api)
        voided = validate_success(
            api.void_layup_session(session["id"], shop_manager_headers), 200
        )
        assert voided["status"] == "VOIDED"
        permit = validate_success(
            api.get_emission_permit(ctx["permit"]["id"], ehs_officer_headers), 200
        )
        assert permit["styrene_used_kg"] == pytest.approx(0.0, abs=1e-9)
        assert permit["status"] == "ACTIVE"


from test_helpers import TEST_USERS

TEST_LAM = TEST_USERS["laminator_headers"]
