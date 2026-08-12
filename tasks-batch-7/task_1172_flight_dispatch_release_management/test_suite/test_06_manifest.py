"""Payload manifest: rollup rounding order, pinned-plan fuel figures,
payload boundary, cardinality, referential gating, and the CDL-narrowed CG
envelope (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_manifest,
    create_manifest_payload,
    create_mel_item_payload,
    setup_computed_plan,
    setup_locked_plan,
    setup_manifest_chain,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]


class TestComponentRoundingOrder:
    def test_manifest_components_round_before_summing(self, api):
        """PRD §3.4: "The `total_payload_kg` is then the sum of those three
        already-rounded components — so one passenger, one bag, and 0.4 kg of
        cargo total 101 kg, not 100."

        Design: Difficulty/combinatorial_formula/manifest_component_rounding_order_mode_b
        """
        ctx = setup_manifest_chain(
            distance_nm=200,
            leg_overrides={"sched_dep_utc": "2026-05-01T10:00:00Z",
                           "sched_arr_utc": "2026-05-01T10:45:00Z"},
            plan_overrides={"route_code": "DCT", "cruise_altitude_ft": 10000},
            pax_count=1, bags_count=1, cargo_kg=0.4,
        )
        manifest = ctx["manifest"]
        assert_manifest(manifest)
        assert manifest["pax_weight_kg"] == 88
        assert manifest["baggage_kg"] == 13
        assert manifest["cargo_billed_kg"] == 0
        assert manifest["total_payload_kg"] == 101

    def test_contingency_floor_branch_on_short_leg(self, api):
        """PRD §3.3: "The `contingency_kg` is the round-half-up of the larger of
        two quantities: five percent of the penalized exact trip fuel, or a
        floor of 100 kg." On the 200 NM leg the five-percent term (56.875) falls
        below the floor, and required_fuel_kg = rhu(1137.5 + 100 + 546 + 1365)
        = 3149 per the single final rounding.

        Design: Difficulty/combinatorial_formula/manifest_component_rounding_order_mode_b
        """
        ctx = setup_manifest_chain(
            distance_nm=200,
            leg_overrides={"sched_dep_utc": "2026-05-01T10:00:00Z",
                           "sched_arr_utc": "2026-05-01T10:45:00Z"},
            plan_overrides={"route_code": "DCT", "cruise_altitude_ft": 10000},
            pax_count=1, bags_count=1, cargo_kg=0.4,
        )
        plan = validate_success(api.get_plan(ctx["plan"]["id"], ctx["d_headers"]), 200)
        assert plan["contingency_kg"] == 100
        assert plan["required_fuel_kg"] == 3149


class TestSinglePassOrder:
    def _setup_recompute_chain(self, api):
        """Locked standard plan (computed with no manifest) + manifest
        150/150/3000; then recompute (the manifest payload now feeds the weight
        reference) and re-lock."""
        ctx = setup_manifest_chain()
        ctx["plan_required_before_recompute"] = ctx["plan"]["required_fuel_kg"]
        ctx["manifest_tow_before_recompute"] = ctx["manifest"]["takeoff_weight_kg"]
        ctx["manifest_max_payload_before_recompute"] = ctx["manifest"]["max_payload_kg"]
        from test_helpers import recompute_plan, lock_plan
        recompute_plan(ctx)
        ctx["plan_required_after_recompute"] = ctx["plan"]["required_fuel_kg"]
        lock_plan(ctx)
        return ctx

    def test_pinned_fuel_figures_and_recompute_references(self, api):
        """PRD §3.4: "At write time the manifest pins `plan_id` to that locked
        plan, freezing the fuel figures its weight checks run against."
        PRD §3.3: "One input does float: the weight reference behind the
        effective burn now uses the current manifest's `total_payload_kg` when a
        manifest exists, so a manifest filed after the first compute changes
        `burn_eff_kg_per_hour` on the next recompute."
        (No-manifest compute: required 9077, manifest tow 69077, max_payload
        19000; recompute with the 18000 kg manifest: required 9164, tow
        60000 + 9164 = 69164.)

        Design: Difficulty/combinatorial_formula/max_payload_single_pass_order_mode_c
        """
        ctx = self._setup_recompute_chain(api)
        assert ctx["plan_required_before_recompute"] == 9077
        assert ctx["manifest_tow_before_recompute"] == 69077
        assert ctx["manifest_max_payload_before_recompute"] == 19000
        assert ctx["plan_required_after_recompute"] == 9164

        updated = validate_success(
            api.update_manifest(ctx["manifest"]["id"], {"cargo_kg": 3000},
                                ctx["d_headers"]),
            200,
        )
        assert updated["takeoff_weight_kg"] == 69164
        assert updated["max_payload_kg"] == 19000

    def test_manifest_updates_never_rederive_plan_fuel(self, api):
        """PRD §3.4: "The fuel figures in this envelope come only from the
        pinned locked plan; changing the payload never re-derives fuel inside
        this calculation, and the only way to refresh the fuel figures is an
        explicit plan recompute and re-lock."

        Design: Difficulty/combinatorial_formula/max_payload_single_pass_order_mode_c
        """
        ctx = self._setup_recompute_chain(api)
        updated = validate_success(
            api.update_manifest(ctx["manifest"]["id"], {"cargo_kg": 2000},
                                ctx["d_headers"]),
            200,
        )
        assert updated["total_payload_kg"] == 17000
        plan = validate_success(api.get_plan(ctx["plan"]["id"], ctx["d_headers"]), 200)
        assert plan["required_fuel_kg"] == 9164, (
            "manifest writes must not re-derive plan fuel figures"
        )


class TestPayloadBoundary:
    def test_payload_equals_max_accepted_boundary(self, api):
        """PRD §3.4: "`total_payload_kg` must not exceed `max_payload_kg` —
        where equality is accepted, so a payload exactly at the limit passes
        (`ERR_PAYLOAD_EXCEEDS_LIMIT` only when strictly above)."
        (150 pax + 150 bags + 4000 kg cargo = 19000 == max_payload_kg 19000.)

        Design: Difficulty/boundary_precision_check/payload_equals_max_accepted_boundary
        """
        ctx = setup_locked_plan()
        manifest = validate_success(
            api.create_manifest(
                create_manifest_payload(ctx["leg"]["id"], pax_count=150,
                                        bags_count=150, cargo_kg=4000),
                ctx["d_headers"],
            ),
            201,
        )
        assert_manifest(manifest)
        assert manifest["total_payload_kg"] == 19000
        assert manifest["max_payload_kg"] == 19000

    def test_payload_one_kg_over_max_rejected(self, api):
        """PRD §3.4: "`total_payload_kg` must not exceed `max_payload_kg` —
        where equality is accepted, so a payload exactly at the limit passes
        (`ERR_PAYLOAD_EXCEEDS_LIMIT` only when strictly above)." 19001 > 19000
        crosses the boundary.

        Design: Difficulty/boundary_precision_check/payload_equals_max_accepted_boundary
        """
        ctx = setup_manifest_chain(pax_count=150, bags_count=150, cargo_kg=4000)
        res = api.update_manifest(ctx["manifest"]["id"], {"cargo_kg": 4001},
                                  ctx["d_headers"])
        # max_payload_kg is pinned by the mzfw-oew ceiling here, so crossing
        # it also busts zero-fuel weight; PRD §2.9 places both fiscal checks
        # at the same priority level without intra-level ordering.
        validate_error_is_one_of(res, [ApiErrorId.ERR_PAYLOAD_EXCEEDS_LIMIT.value,
                                       ApiErrorId.ERR_MZFW_EXCEEDED.value])


class TestManifestCardinalityAndGating:
    def test_second_manifest_rejected(self, api):
        """PRD §3.4: "Two referential gates guard creation: the leg's current
        non-superseded plan must be `LOCKED` (`ERR_PLAN_NOT_LOCKED` otherwise),
        and a leg carries at most one manifest, so a second create is rejected
        with `ERR_MANIFEST_EXISTS`."

        Design: Corner/validations/second_manifest_rejected
        """
        ctx = setup_manifest_chain()
        res = api.create_manifest(
            create_manifest_payload(ctx["leg"]["id"], pax_count=10, bags_count=10,
                                    cargo_kg=100),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_MANIFEST_EXISTS.value)

    def test_manifest_conflict_referential_beats_fiscal(self, api):
        """PRD §2.9: "10. **Referential prerequisites.** A plan that is not
        locked or a missing manifest yields `ERR_PLAN_NOT_LOCKED` or
        `ERR_MANIFEST_MISSING`." precedes "11. **Fiscal and capacity economics,
        always last.**" — a manifest create against a merely COMPUTED plan
        surfaces ERR_PLAN_NOT_LOCKED even though the 40000 kg cargo would also
        fail the fiscal weight checks.

        Design: Difficulty/priority_pair_validation_conflict/manifest_conflict_referential_beats_fiscal
        """
        ctx = setup_computed_plan()
        assert ctx["plan"]["status"] == "COMPUTED"
        res = api.create_manifest(
            create_manifest_payload(ctx["leg"]["id"], pax_count=1, bags_count=0,
                                    cargo_kg=40000),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_LOCKED.value)

    def test_manifest_referential_gate_masks_fiscal_for_any_load(self, api):
        """PRD §2.9: "10. **Referential prerequisites.** A plan that is not
        locked or a missing manifest yields `ERR_PLAN_NOT_LOCKED` or
        `ERR_MANIFEST_MISSING`." precedes "11. **Fiscal and capacity economics,
        always last.**" — with a COMPUTED plan, a pax-only overload (400 pax)
        is likewise masked by the referential error, and no manifest is
        created.

        Design: Difficulty/priority_pair_validation_conflict/manifest_conflict_referential_beats_fiscal
        """
        ctx = setup_computed_plan()
        res = api.create_manifest(
            create_manifest_payload(ctx["leg"]["id"], pax_count=400, bags_count=0,
                                    cargo_kg=0),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_LOCKED.value)
        data, meta = validate_paginated(
            api.list_manifests(ctx["d_headers"], params={"leg_id": ctx["leg"]["id"]})
        )
        assert meta["total_count"] == 0


class TestCdlCgEnvelope:
    def test_cdl_item_narrows_cg_envelope(self, api):
        """PRD §3.4: "The acceptable envelope normally runs from 20.0 to 31.0
        percent inclusive; when any `OPEN` deferred defect of `category` `CDL`
        exists on the aircraft, the envelope narrows to 22.0 through 30.0
        inclusive. A center of gravity outside the applicable envelope is
        rejected with `ERR_CG_OUT_OF_ENVELOPE`, while a value exactly on either
        bound is accepted." (Cargo 8070 kg on the standard chain yields
        cg_percent_mac 30.50: inside [20.0, 31.0], outside [22.0, 30.0].)

        Design: Corner/calculations/cdl_item_narrows_cg_envelope
        """
        ctx = setup_locked_plan()
        manifest = validate_success(
            api.create_manifest(
                create_manifest_payload(ctx["leg"]["id"], pax_count=0, bags_count=0,
                                        cargo_kg=8070),
                ctx["d_headers"],
            ),
            201,
        )
        assert manifest["cg_percent_mac"] == pytest.approx(30.50, abs=0.001)

        validate_success(
            api.create_mel_item(
                create_mel_item_payload(ctx["aircraft"]["id"], item_code="CDL-9",
                                        category="CDL"),
                SUP,
            ),
            201,
        )
        res = api.update_manifest(manifest["id"], {"cargo_kg": 8070},
                                  ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_CG_OUT_OF_ENVELOPE.value)
